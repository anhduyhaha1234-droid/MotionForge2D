"""S11-T03B cut_drift detector (W6) — timecode cut-point drift.

Compares RENDERED cut points (timecodes in integer milliseconds) against
the scene_detector GROUND TRUTH scene boundaries (start frames of scene
rows) and classifies the frame drift against the FROZEN T03A threshold
policy — READ-ONLY — via ``thresholds.classify`` /
``thresholds.get_threshold`` (``cut_drift``: warning >= 3 frames,
blocker >= 12 frames, calibrated from T06A2).  NO boundary is
hard-coded: every tolerance in the evidence comes from the policy entry.

Frame <-> ms conversion goes THROUGH ``CanonicalTimebase`` EXACT
``Fraction`` arithmetic (``frame_to_time`` / ``nearest_frame``) — never
binary-float drift.  For a CFR 30000/1001 (29.97 fps) timebase the
boundary at frame 90 is EXACTLY 3003 ms and a 3303 ms render cut lands on
frame 99 (98.991... -> round-half-up); the detector's ``boundary_time_ms``
is the same canonical millisecond ``scene_ms_range`` produces, so the
scene_detector ground truth and the detector agree at ms precision.

Scene boundary semantics match ``scene_detector.cuts_to_scenes``: a cut
at frame ``f`` means a new scene starts at ``f`` — the boundary of
scene ``position`` is its ``start_frame``.  The detector consumes the
boundary values (scene_detector ground truth) supplied by the
orchestrator in the args contract — it never opens a DB connection
(isolation: detectors run in a bounded child without DB access).

Fail-closed:
- malformed/unknown inputs -> ``QC_CUT_INVALID_ARGS``;
- a drift the policy classifies ``THRESHOLD_INVALID`` (outside the
  calibrated envelope) -> ``QC_CUT_MEASUREMENT_INVALID`` — an
  out-of-calibration drift is a pipeline fault, NOT a reportable issue;
  no QCItem is ever fabricated from it.

QCItem creation goes through the T02B repository ONLY
(``QCItemRepository.create`` — natural-key idempotent upsert).  Evidence
is schema_version=1 and content-derived EXCLUSIVELY (boundary frame,
canonical ms, render timecode, derived frame, drift, policy
identity/boundaries, timebase facts) so two runs over the same inputs
produce byte-identical evidence JSON and the same ``evidence_window_key``
(``cut_drift:<layer>:b<boundary_frame>`` — recheck reuses the same row).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.persistence.qc_items import QCItemRecord, QCItemRepository
from app.services.qc_checks.registry import register_detector
from app.services.qc_checks.thresholds import (
    POLICY_ID,
    STATUS_BLOCKER,
    STATUS_INVALID,
    STATUS_WARNING,
    classify,
    get_threshold,
)
from app.services.timebase import CanonicalTimebase

#: Registry identity (T03A contract — the runner resolves module:detect).
DETECTOR_NAME = "cut_drift"
DETECTOR_VERSION = "1.0.0"
ENTRY_POINT = f"{__name__}:detect"

#: metric == reason_code == category (frozen 1:1 QC taxonomy, T02A).
METRIC = "cut_drift"
REASON_CODE = "cut_drift"
CATEGORY = "cut_drift"

#: Evidence schema (content-derived, byte-stable).
EVIDENCE_SCHEMA_VERSION = 1

#: Default checkpoint identity when the caller does not supply one.
DEFAULT_CHECKPOINT_REF = "s11-qc-t03b"

#: Stable detector error codes.
QC_CUT_INVALID_ARGS = "QC_CUT_INVALID_ARGS"
QC_CUT_MEASUREMENT_INVALID = "QC_CUT_MEASUREMENT_INVALID"


class DetectorError(Exception):
    """Cut-drift detector contract violation with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _round_ms(x: Fraction) -> int:
    """Nearest integer millisecond of an exact ``Fraction`` (round
    half-up) — the SAME canonical integer-ms rule ``scene_ms_range``
    uses, so detector ms == scene_detector GT ms."""
    if x.numerator < 0:
        return -((2 * -x.numerator + x.denominator) // (2 * x.denominator))
    return (2 * x.numerator + x.denominator) // (2 * x.denominator)


def _confidence(value: float, blocker_boundary: float) -> float:
    """Content-derived confidence in [0, 1]: value/blocker capped at 1.0
    and rounded to 6 dp (deterministic — same inputs, same confidence)."""
    return round(min(value / blocker_boundary, 1.0), 6)


def _validate_boundaries(
    boundaries: Any, render_cuts_ms: Any, timebase: CanonicalTimebase
) -> list[tuple[int, int, int]]:
    """Validate and normalize the per-boundary inputs.  Returns
    ``(scene_position, boundary_frame, render_cut_ms)`` triples."""
    if not isinstance(boundaries, (list, tuple)) or not boundaries:
        raise DetectorError(
            QC_CUT_INVALID_ARGS, "scene_boundaries must be a non-empty list"
        )
    if (
        not isinstance(render_cuts_ms, (list, tuple))
        or len(render_cuts_ms) != len(boundaries)
    ):
        raise DetectorError(
            QC_CUT_INVALID_ARGS,
            "render_cuts_ms must be a list with one entry per scene boundary",
        )
    triples: list[tuple[int, int, int]] = []
    seen_positions: set[int] = set()
    for boundary, cut_ms in zip(boundaries, render_cuts_ms):
        if not isinstance(boundary, Mapping):
            raise DetectorError(
                QC_CUT_INVALID_ARGS,
                "each scene_boundaries entry must be an object with "
                "position and start_frame",
            )
        try:
            position = int(boundary["position"])
            boundary_frame = int(boundary["start_frame"])
            cut = int(cut_ms)
        except (TypeError, ValueError, KeyError):
            raise DetectorError(
                QC_CUT_INVALID_ARGS,
                "scene_boundaries entries need integer position/start_frame; "
                "render_cuts_ms entries need integer milliseconds",
            ) from None
        if position < 0 or boundary_frame < 0 or cut < 0:
            raise DetectorError(
                QC_CUT_INVALID_ARGS,
                "position/start_frame/render_cut_ms must be non-negative",
            )
        if position in seen_positions:
            raise DetectorError(
                QC_CUT_INVALID_ARGS, f"duplicate scene position {position!r}"
            )
        seen_positions.add(position)
        triples.append((position, boundary_frame, cut))
    return triples


def _analyze(args: dict[str, Any], checkpoint_ref: str) -> dict[str, Any]:
    """Validate args, convert ms->frame via the CanonicalTimebase EXACT
    Fraction arithmetic, measure per-boundary drift, classify against the
    FROZEN policy and build the full (pure) analysis — no side effects;
    JSON-serializable."""
    workspace_id = args.get("workspace_id")
    project_id = args.get("project_id")
    video_item_id = args.get("video_item_id")
    layer_ref_type = str(args.get("layer_ref_type") or "video_item")
    layer_ref_id = str(args.get("layer_ref_id") or video_item_id or "")
    if not all(
        isinstance(v, str) and v
        for v in (workspace_id, project_id, video_item_id, layer_ref_id)
    ):
        raise DetectorError(
            QC_CUT_INVALID_ARGS,
            "workspace_id/project_id/video_item_id/layer_ref_id must be non-empty strings",
        )

    timebase_payload = args.get("timebase")
    if not isinstance(timebase_payload, Mapping):
        raise DetectorError(
            QC_CUT_INVALID_ARGS,
            "timebase must be a CanonicalTimebase.to_json() payload",
        )
    try:
        timebase = CanonicalTimebase.from_json(dict(timebase_payload))
    except Exception as exc:  # TimebaseError — stable fail-closed
        raise DetectorError(
            QC_CUT_INVALID_ARGS, f"invalid canonical timebase payload: {exc}"
        ) from exc

    triples = _validate_boundaries(
        args.get("scene_boundaries"), args.get("render_cuts_ms"), timebase
    )
    entry = get_threshold(METRIC)
    warning_boundary = float(entry["warning_boundary"])
    blocker_boundary = float(entry["blocker_boundary"])

    measurements: list[dict[str, Any]] = []
    for position, boundary_frame, render_cut_ms in triples:
        # EXACT Fraction arithmetic: frame <-> ms never touches float.
        boundary_time_ms = _round_ms(timebase.frame_to_time(boundary_frame) * 1000)
        render_frame = timebase.nearest_frame(Fraction(render_cut_ms, 1000))
        drift_frames = abs(render_frame - boundary_frame)

        status, code = classify(METRIC, float(drift_frames))
        if status == STATUS_INVALID:
            raise DetectorError(
                QC_CUT_MEASUREMENT_INVALID,
                f"measured cut_drift {drift_frames!r} frames is outside the "
                f"calibrated envelope (policy {POLICY_ID}) — pipeline "
                f"fault, not a QC issue",
            )

        window_key = (
            f"{DETECTOR_NAME}:{layer_ref_type}:{layer_ref_id}:"
            f"b{boundary_frame}"
        )
        evidence: dict[str, Any] = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "metric": METRIC,
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_VERSION,
            "status": status,
            "scene_position": position,
            "boundary_frame": boundary_frame,
            "boundary_time_ms": boundary_time_ms,
            "render_cut_ms": render_cut_ms,
            "render_frame": render_frame,
            "drift_frames": drift_frames,
            "measurement": "abs(render_frame - scene_boundary_frame) frames",
            "timebase": timebase.to_json(),
            "fps": f"{timebase.fps.numerator}/{timebase.fps.denominator}",
            "warning_boundary_frames": int(warning_boundary),
            "blocker_boundary_frames": int(blocker_boundary),
            "policy_id": POLICY_ID,
            "confidence": _confidence(float(drift_frames), blocker_boundary),
            "checkpoint_ref": checkpoint_ref,
        }
        measurements.append(
            {
                "metric": METRIC,
                "value": float(drift_frames),
                "status": status,
                "code": code,
                "severity": status if status in (STATUS_WARNING, STATUS_BLOCKER) else None,
                "reason_code": REASON_CODE,
                "category": CATEGORY,
                "evidence_window_key": window_key,
                "evidence": evidence,
            }
        )

    return {
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_VERSION,
        "metric": METRIC,
        "measurements": measurements,
    }


def detect(args: dict[str, Any]) -> dict[str, Any]:
    """Runner entry point (T03A protocol: ``fn(args_json) -> JSON``).

    Pure analysis — NO DB writes, NO side effects.  The orchestrator
    (T03F) combines the measurements with the policy / repository.
    """
    checkpoint_ref = str(args.get("checkpoint_ref") or DEFAULT_CHECKPOINT_REF)
    return _analyze(args, checkpoint_ref)


def create_qc_items(
    session: Session,
    args: dict[str, Any],
    *,
    checkpoint_ref: str | None = None,
) -> list[QCItemRecord]:
    """Analyze the args and create ONE QCItem per non-pass measurement
    (per drifted scene boundary) through the T02B repository (the ONLY
    creation path, Decision A).

    Natural-key idempotent: re-running on the same inputs reuses the
    existing rows (same ids returned, zero duplicates).  The caller owns
    commit/rollback (repository contract).
    """
    effective_checkpoint = checkpoint_ref or DEFAULT_CHECKPOINT_REF
    analysis = _analyze(args, effective_checkpoint)
    repo = QCItemRepository(session)
    records: list[QCItemRecord] = []
    for measurement in analysis["measurements"]:
        if measurement["severity"] is None:
            continue  # pass -> no item
        records.append(
            repo.create(
                workspace_id=str(args["workspace_id"]),
                project_id=str(args["project_id"]),
                video_item_id=str(args["video_item_id"]),
                layer_ref_type=str(args.get("layer_ref_type") or "video_item"),
                layer_ref_id=str(args.get("layer_ref_id") or args["video_item_id"]),
                reason_code=measurement["reason_code"],
                evidence_window_key=measurement["evidence_window_key"],
                evidence=measurement["evidence"],
                severity=measurement["severity"],
                category=measurement["category"],
                detector=DETECTOR_NAME,
                detector_revision=DETECTOR_VERSION,
                confidence=measurement["evidence"]["confidence"],
                confidence_source="detector",
                checkpoint_ref=effective_checkpoint,
            )
        )
    return records


#: Self-registration into the T03A registry (idempotent identity — the
#: runner refuses to execute an unregistered detector, fail-closed).
_ = register_detector(
    DETECTOR_NAME,
    ENTRY_POINT,
    version=DETECTOR_VERSION,
    description=(
        "cut_drift (timecode): rendered cut timecodes (ms) vs scene "
        "boundary ground truth, converted frame<->ms through "
        "CanonicalTimebase exact Fraction arithmetic, classified against "
        "the frozen T03A threshold policy"
    ),
)
"""S11-T03B trajectory_drift detector (W6) — visual trajectory drift.

Measures the mean absolute horizontal deviation (px) of a RENDERED
(observed) trajectory from the fixture's reference (ground-truth)
trajectory over one analysis window, then classifies the value against
the FROZEN T03A threshold policy — READ-ONLY — via
``thresholds.classify`` / ``thresholds.get_threshold``.  NO boundary is
hard-coded in this module: every boundary in the evidence comes from the
policy entry.

Measurement semantics mirror the T06A2 calibration measurement
``measure_trajectory_drift`` (``tests/s11_qc_calibration_builders.py``
revision 1.0.0): mean |observed - reference| over the window.  The
reference trajectory is the ground truth carried by the QC fixture
(lane-A QC_DOMAIN_CONTRACT §1.2: SegmentMotion/MotionRecord renderer
output is PARTIAL — it has no GT — so the detector consumes the
fixture-provided reference path and never invents one).

Fail-closed:
- malformed/unknown inputs -> ``QC_TRAJECTORY_INVALID_ARGS``;
- a measurement the policy classifies ``THRESHOLD_INVALID`` (non-finite
  or outside the calibrated envelope) -> ``QC_TRAJECTORY_MEASUREMENT_INVALID``
  — an out-of-calibration value is a pipeline fault, NOT a reportable
  issue; no QCItem is ever fabricated from it.

QCItem creation goes through the T02B repository ONLY
(``QCItemRepository.create`` — natural-key idempotent upsert).  Evidence
is schema_version=1 and content-derived EXCLUSIVELY (trajectory content
digests, window, measured value, policy identity/boundaries) so two runs
over the same inputs produce byte-identical evidence JSON and the same
``evidence_window_key`` (recheck reuses the same row).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

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
from app.services.qc_evidence import measure as qcm

#: Registry identity (T03A contract — the runner resolves module:detect).
DETECTOR_NAME = "trajectory_drift"
DETECTOR_VERSION = "1.0.0"
ENTRY_POINT = f"{__name__}:detect"

#: metric == reason_code == category (frozen 1:1 QC taxonomy, T02A).
METRIC = "trajectory_drift"
REASON_CODE = "trajectory_drift"
CATEGORY = "trajectory_drift"

#: Evidence schema (content-derived, byte-stable).
EVIDENCE_SCHEMA_VERSION = 1
#: Evidence precision mirrors the calibration raw-value convention (9 dp).
EVIDENCE_ROUND_DIGITS = 9

#: Default checkpoint identity when the caller does not supply one.
DEFAULT_CHECKPOINT_REF = "s11-qc-t03b"

#: Stable detector error codes.
QC_TRAJECTORY_INVALID_ARGS = "QC_TRAJECTORY_INVALID_ARGS"
QC_TRAJECTORY_MEASUREMENT_INVALID = "QC_TRAJECTORY_MEASUREMENT_INVALID"


class DetectorError(Exception):
    """Trajectory detector contract violation with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _content_digest(values: Sequence[float]) -> str:
    """Content-derived artifact digest: sha256 over the canonical JSON of
    the rounded trajectory points (deterministic across runs/machines)."""
    canonical = json.dumps(
        [round(float(v), EVIDENCE_ROUND_DIGITS) for v in values],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _confidence(value: float, blocker_boundary: float) -> float:
    """Content-derived confidence in [0, 1]: value/blocker capped at 1.0
    and rounded to 6 dp (deterministic — same inputs, same confidence)."""
    return round(min(value / blocker_boundary, 1.0), 6)


def measure(reference_x: Sequence[float], observed_x: Sequence[float]) -> float:
    """Mean absolute horizontal deviation (px) over the window — the SAME
    semantics as the T06A2 calibration measurement (raw value family the
    frozen boundaries come from).  Pure function; caller validates."""
    if len(reference_x) != len(observed_x) or not reference_x:
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS,
            "reference_x and observed_x must be non-empty equal-length sequences",
        )
    total = math.fsum(
        abs(float(o) - float(r)) for r, o in zip(reference_x, observed_x)
    )
    return total / len(reference_x)


def _analyze(args: dict[str, Any], checkpoint_ref: str) -> dict[str, Any]:
    """Validate args, measure, classify against the FROZEN policy and build
    the full (pure) analysis — no side effects; JSON-serializable."""
    workspace_id = args.get("workspace_id")
    project_id = args.get("project_id")
    video_item_id = args.get("video_item_id")
    layer_ref_type = str(args.get("layer_ref_type") or "video_item")
    layer_ref_id = str(args.get("layer_ref_id") or video_item_id or "")
    reference_x = args.get("reference_x")
    observed_x = args.get("observed_x")
    frame_start = args.get("frame_start", 0)

    if not all(
        isinstance(v, str) and v
        for v in (workspace_id, project_id, video_item_id, layer_ref_id)
    ):
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS,
            "workspace_id/project_id/video_item_id/layer_ref_id must be non-empty strings",
        )
    if (
        not isinstance(reference_x, (list, tuple))
        or not isinstance(observed_x, (list, tuple))
        or not reference_x
        or len(reference_x) != len(observed_x)
    ):
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS,
            "reference_x and observed_x must be non-empty equal-length lists",
        )
    try:
        frame_start = int(frame_start)
    except (TypeError, ValueError):
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS, "frame_start must be an integer"
        ) from None
    if frame_start < 0:
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS, "frame_start must be non-negative"
        )

    try:
        refs = [float(v) for v in reference_x]
        obs = [float(v) for v in observed_x]
    except (TypeError, ValueError):
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS, "trajectory points must be numeric"
        ) from None
    if not all(math.isfinite(v) for v in refs) or not all(
        math.isfinite(v) for v in obs
    ):
        raise DetectorError(
            QC_TRAJECTORY_INVALID_ARGS, "trajectory points must be finite"
        )

    value = measure(refs, obs)
    status, code = classify(METRIC, value)
    if status == STATUS_INVALID:
        raise DetectorError(
            QC_TRAJECTORY_MEASUREMENT_INVALID,
            f"measured trajectory_drift {value!r} is outside the calibrated "
            f"envelope (policy {POLICY_ID}) — pipeline fault, not a QC issue",
        )

    entry = get_threshold(METRIC)
    warning_boundary = float(entry["warning_boundary"])
    blocker_boundary = float(entry["blocker_boundary"])
    frame_end = frame_start + len(refs) - 1
    window_key = (
        f"{DETECTOR_NAME}:{layer_ref_type}:{layer_ref_id}:"
        f"w{frame_start}-{frame_end}"
    )

    evidence: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "metric": METRIC,
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_VERSION,
        "status": status,
        "value": round(value, EVIDENCE_ROUND_DIGITS),
        "measurement": "mean_absolute_deviation_px",
        "window": {
            "frame_start": frame_start,
            "frame_end": frame_end,
            "frame_count": len(refs),
        },
        "reference_trajectory_sha256": _content_digest(refs),
        "observed_trajectory_sha256": _content_digest(obs),
        "warning_boundary_px": warning_boundary,
        "blocker_boundary_px": blocker_boundary,
        "policy_id": POLICY_ID,
        "confidence": _confidence(value, blocker_boundary),
        "checkpoint_ref": checkpoint_ref,
    }
    measurement: dict[str, Any] = {
        "metric": METRIC,
        "value": value,
        "status": status,
        "code": code,
        "severity": status if status in (STATUS_WARNING, STATUS_BLOCKER) else None,
        "reason_code": REASON_CODE,
        "category": CATEGORY,
        "evidence_window_key": window_key,
        "evidence": evidence,
    }
    return {
        "detector": DETECTOR_NAME,
        "detector_revision": DETECTOR_VERSION,
        "metric": METRIC,
        "measurements": [measurement],
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
    through the T02B repository (the ONLY creation path, Decision A).

    Natural-key idempotent: re-running on the same inputs reuses the
    existing row (same id returned, zero duplicates).  The caller owns
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
        "trajectory_drift (visual): mean absolute horizontal deviation "
        "(px) of the rendered path from the fixture reference path, "
        "classified against the frozen T03A threshold policy"
    ),
)


# ── MF-END-22.1/22.2/22.3: SOURCE motion vs OUTPUT observations (U09/U11) ────
#
# Motion preservation is a CROSS-SOURCE comparison: the source trace comes
# from the real MF-END-12 role track (preferred) or from the MF-END-13 camera
# window fact's MEASURED rate (the basis is recorded either way), the output
# trace from the MF-END-21 observations — never from the source side itself.
#
# Defects (hard dominates):
# - ``QC_COMPARISON_MOTION_STATIC`` (hard): the source moves above the static
#   floor and the OUTPUT is frozen (no measurable motion at all) — the silent
#   / static output U11 forbids;
# - ``QC_COMPARISON_MOTION_LOST`` (hard) / ``QC_COMPARISON_MOTION_ATTENUATED``
#   (soft): the frozen motion-attenuation policy (level-2/level-4 measured raw
#   values) classifies ``1 - output_motion / source_motion``;
# - ``QC_COMPARISON_FRAME_SHIFT`` (hard/soft by the frozen band): the output
#   moves at the WRONG TIME (best matching step shift in frames).

COMPARISON_DETECTOR_NAME = "trajectory_drift_comparison"


def _round9(value: float) -> float:
    return round(float(value), 9)


def _centre_of(item: Mapping[str, Any]) -> tuple[float, float] | None:
    centre = item.get("centroid")
    if isinstance(centre, (list, tuple)) and len(centre) == 2:
        try:
            x, y = float(centre[0]), float(centre[1])
        except (TypeError, ValueError):
            return None
        if math.isfinite(x) and math.isfinite(y):
            return (x, y)
    box = qcm.bbox_of(item)
    return qcm.bbox_center(box) if box is not None else None


def _source_trace(
    ctx: dict[str, Any], args: dict[str, Any]
) -> tuple[list[tuple[int, float, float]], str, dict[str, Any]]:
    """The SOURCE motion trace: MF-END-12 track first, camera fact second."""
    role = str(args.get("source_role_id") or "")
    detail: dict[str, Any] = {}
    tracks = ctx.get("source_tracks") or {}
    if not role:
        for candidate in tracks.get("tracks") or []:
            if str(candidate.get("kind")) == "person":
                role = str(candidate.get("role_id"))
                break
    trace: list[tuple[int, float, float]] = []
    if role:
        track = qcm.track_by_role(tracks, role)
        if track is not None:
            rows = qcm.granted_rows(track)
            for frame in sorted(rows):
                centre = _centre_of(rows[frame])
                if centre is not None:
                    trace.append((int(frame), centre[0], centre[1]))
            detail["source_role_id"] = role
            detail["source_instance_id"] = str(track.get("instance_id") or "")
    if trace:
        return trace, f"mf12_track:{role}", detail

    window_id = str(args.get("source_window_id") or "")
    fact: dict[str, Any] | None = None
    for candidate in ctx["facts"].get("camera") or []:
        if not window_id or str(candidate.get("window_id")) == window_id:
            fact = dict(candidate)
            break
    if fact is None:
        return [], "", detail
    span = fact.get("span") or {}
    frames = int(span.get("end_frame_exclusive", 0)) - int(span.get("start_frame", 0))
    motion = fact.get("content_motion") or {}
    rate: float | None = None
    rate_key = ""
    if isinstance(motion, Mapping):
        for key in ("mean_px_per_frame", "total_px", "magnitude_px"):
            if motion.get(key) is not None:
                value = float(motion[key])
                rate = value if key == "mean_px_per_frame" or frames <= 0 else value / float(frames)
                rate_key = key
                break
    if str(fact.get("classification") or "") == "static":
        rate = 0.0
        rate_key = "classification_static"
    if rate is None:
        return [], "", {"camera_window_id": fact.get("window_id")}
    trace = [(int(span.get("start_frame", 0)) + i, float(i) * rate, 0.0) for i in range(frames)]
    detail.update(
        {
            "camera_window_id": fact.get("window_id"),
            "camera_classification": fact.get("classification"),
            "camera_rate_px_per_frame": _round9(rate),
            "camera_rate_key": rate_key,
        }
    )
    return trace, f"mf13_camera_window:{fact.get('window_id')}:{rate_key}", detail


def _output_trace(
    ctx: dict[str, Any], args: dict[str, Any], source_role: str
) -> tuple[list[tuple[int, float, float]], dict[str, Any] | None, str]:
    """The OUTPUT motion trace from the MF-END-21 observations."""
    role = str(args.get("output_role_id") or source_role or "")
    track: dict[str, Any] | None = None
    if role:
        track = qcm.track_by_role(ctx["observations"], role)
    if track is None:
        for candidate in ctx["observations"].get("tracks") or []:
            if (candidate.get("role_match") or {}).get("state") == "matched":
                track = dict(candidate)
                role = str(candidate.get("role_id"))
                break
    if track is None:
        return [], None, role
    rows = qcm.output_rows(ctx, role)
    assert rows is not None  # the track exists, so its rows resolve
    trace: list[tuple[int, float, float]] = []
    for frame in sorted(rows["rows"]):
        centre = _centre_of(rows["rows"][frame])
        if centre is not None:
            trace.append((int(frame), centre[0], centre[1]))
    return trace, track, role


def compare_motion_facts(args: dict[str, Any]) -> dict[str, Any]:
    """Compare the source motion with the output observations (U09/U11).

    ``args`` is the shared comparator schema plus optional
    ``source_role_id`` / ``source_window_id`` / ``output_role_id``.
    """
    ctx, refusals = qcm.comparison_context(args)
    if refusals:
        verdict = qcm.compare_verdict(
            [], blocked=refusals, appearance=args.get("appearance")
        )
        return qcm.comparison_result(
            detector=COMPARISON_DETECTOR_NAME,
            reason_code=DETECTOR_NAME,
            verdict=verdict,
            items=[],
            uncertain=[],
            blocked=refusals,
            checked=[],
            ctx={},
            extra={"refusals": refusals},
        )

    items: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []

    source_trace, source_basis, source_detail = _source_trace(ctx, args)
    output_trace, output_track, output_role = _output_trace(
        ctx, args, str(source_detail.get("source_role_id") or "")
    )
    span = ctx["facts"].get("source") or {}
    span_start = int((span.get("span") or {}).get("start_frame", 0))
    span_end = int((span.get("span") or {}).get("end_frame_exclusive", span_start))
    window_frames = list(range(span_start, span_end))

    if not source_trace:
        uncertain.append(
            {
                "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                "role_id": str(source_detail.get("source_role_id") or ""),
                "frames": window_frames,
                "detail": (
                    "no SOURCE motion trace is available (no sealed MF-END-12 "
                    "track supplied and no measurable camera window fact); the "
                    "motion comparison cannot be made and is not guessed"
                ),
            }
        )
    if output_track is None:
        blocked.append(
            {
                "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                "role_id": output_role,
                "frames": window_frames,
                "detail": (
                    f"the output carries no observation track for role "
                    f"{output_role!r}; the motion comparison cannot be made"
                ),
                "output_refusal": qcm.refused_role(ctx["observations"], output_role),
            }
        )
    if not source_trace or output_track is None:
        verdict = qcm.compare_verdict(
            items,
            uncertain=uncertain,
            blocked=blocked,
            appearance=args.get("appearance"),
        )
        return qcm.comparison_result(
            detector=COMPARISON_DETECTOR_NAME,
            reason_code=DETECTOR_NAME,
            verdict=verdict,
            items=items,
            uncertain=uncertain,
            blocked=blocked,
            checked=checked,
            ctx=ctx,
        )

    source_series = [(x, y) for _, x, y in source_trace]
    output_series = [(x, y) for _, x, y in output_trace]
    source_rate = qcm.motion_px_per_frame(source_series)
    output_rate = qcm.motion_px_per_frame(output_series)
    output_frames = [frame for frame, _, _ in output_trace]
    evidence: dict[str, Any] = {
        "source_basis": source_basis,
        "output_role_id": output_role,
        "output_segment_id": str(output_track.get("segment_id") or ""),
        "output_instance_id": str(output_track.get("instance_id") or ""),
        "window": {"start_frame": span_start, "end_frame_exclusive": span_end},
        "measured": {
            "source_trace_points": len(source_trace),
            "output_trace_points": len(output_trace),
            "source_px_per_frame": _round9(source_rate),
            "output_px_per_frame": _round9(output_rate),
        },
        "static_floor_px_per_frame": qcm.COMPARISON_STATIC_MAX_PX_PER_FRAME,
        "source_detail": source_detail,
        "mapping": ctx.get("mapping"),
        "measure": (
            "mean centroid step (px/frame) of the source trace vs the output "
            "observations' centroids, mapped onto the same source frames"
        ),
    }
    frozen_output = output_rate < qcm.COMPARISON_STATIC_MAX_PX_PER_FRAME
    if source_rate < qcm.COMPARISON_STATIC_MAX_PX_PER_FRAME:
        checked.append(
            {
                "status": qcm.VERDICT_PASS,
                "note": "source is static; a static output is consistent",
                "window": evidence["window"],
            }
        )
        if frozen_output:
            evidence["measured"]["frozen_output"] = True
    elif frozen_output:
        ratio = qcm.measure_motion_attenuation(source_series, output_series)
        items.append(
            qcm.comparison_item(
                metric=qcm.METRIC_MOTION_ATTENUATION,
                code=qcm.CODE_MOTION_STATIC,
                level=qcm.LEVEL_HARD,
                severity="blocker",
                role_id=output_role,
                frames=output_frames,
                detail=(
                    f"the SOURCE moves {_round9(source_rate)} px/frame but the "
                    f"OUTPUT is frozen ({_round9(output_rate)} px/frame < "
                    f"{qcm.COMPARISON_STATIC_MAX_PX_PER_FRAME}) — a silent/static "
                    "output where the source has motion (U11)"
                ),
                evidence={**evidence, "attenuation_ratio": _round9(ratio or 0.0)},
            )
        )
        checked.append({"status": qcm.VERDICT_FAIL, "window": evidence["window"]})
    else:
        ratio = qcm.measure_motion_attenuation(source_series, output_series)
        if ratio is None:
            uncertain.append(
                {
                    "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                    "role_id": output_role,
                    "frames": output_frames,
                    "detail": "the source motion is not measurable; no attenuation",
                }
            )
        else:
            status, code = qcm.classify_comparison(
                qcm.METRIC_MOTION_ATTENUATION, ratio
            )
            if status == "invalid":
                uncertain.append(
                    {
                        "code": qcm.CODE_COMPARISON_INVALID,
                        "role_id": output_role,
                        "frames": output_frames,
                        "detail": (
                            f"measured attenuation {_round9(ratio)} is outside the "
                            "frozen calibrated envelope — pipeline fault"
                        ),
                    }
                )
            elif status == "blocker":
                items.append(
                    qcm.comparison_item(
                        metric=qcm.METRIC_MOTION_ATTENUATION,
                        code=qcm.CODE_MOTION_LOST,
                        level=qcm.LEVEL_HARD,
                        severity="blocker",
                        role_id=output_role,
                        frames=output_frames,
                        detail=(
                            f"the output lost the source motion (attenuation "
                            f"{_round9(ratio)} >= blocker boundary)"
                        ),
                        evidence={**evidence, "attenuation_ratio": _round9(ratio)},
                    )
                )
            elif status == "warning":
                items.append(
                    qcm.comparison_item(
                        metric=qcm.METRIC_MOTION_ATTENUATION,
                        code=qcm.CODE_MOTION_ATTENUATED,
                        level=qcm.LEVEL_SOFT,
                        severity="warning",
                        role_id=output_role,
                        frames=output_frames,
                        detail=(
                            f"the output motion is attenuated (attenuation "
                            f"{_round9(ratio)} inside the warning band)"
                        ),
                        evidence={**evidence, "attenuation_ratio": _round9(ratio)},
                    )
                )
            else:
                checked.append(
                    {
                        "status": qcm.VERDICT_PASS,
                        "attenuation_ratio": _round9(ratio),
                        "window": evidence["window"],
                    }
                )

    if len(source_trace) >= 2 and len(output_trace) >= 2:
        source_steps = qcm.step_series([x for _, x, _ in source_trace])
        output_steps = qcm.step_series([x for _, x, _ in output_trace])
        shift = qcm.measure_frame_shift(source_steps, output_steps)
        status, code = qcm.classify_comparison(qcm.METRIC_FRAME_SHIFT, float(shift))
        shift_evidence = {
            **evidence,
            "measured": {
                **evidence["measured"],
                "best_frame_shift_frames": int(shift),
                "tolerance_frames": int(
                    qcm.comparison_threshold(qcm.METRIC_FRAME_SHIFT)["warning_boundary"]
                ),
            },
            "measure": (
                "the source and output step series are aligned over all shifts "
                "(+ = the output happens LATER); the best matching shift is "
                "classified against the frozen time policy"
            ),
        }
        if status == "blocker":
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_FRAME_SHIFT,
                    code=qcm.CODE_FRAME_SHIFT,
                    level=qcm.LEVEL_HARD,
                    severity="blocker",
                    role_id=output_role,
                    frames=output_frames,
                    detail=(
                        f"the output motion happens {shift} frame(s) away from the "
                        "source motion (hard timing defect)"
                    ),
                    evidence=shift_evidence,
                )
            )
        elif status == "warning":
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_FRAME_SHIFT,
                    code=qcm.CODE_FRAME_SHIFT,
                    level=qcm.LEVEL_SOFT,
                    severity="warning",
                    role_id=output_role,
                    frames=output_frames,
                    detail=(
                        f"the output motion is {shift} frame(s) offset from the "
                        "source motion (inside the warning band)"
                    ),
                    evidence=shift_evidence,
                )
            )
        else:
            checked.append(
                {"status": qcm.VERDICT_PASS, "frame_shift_frames": int(shift)}
            )

    verdict = qcm.compare_verdict(
        items, uncertain=uncertain, blocked=blocked, appearance=args.get("appearance")
    )
    return qcm.comparison_result(
        detector=COMPARISON_DETECTOR_NAME,
        reason_code=DETECTOR_NAME,
        verdict=verdict,
        items=items,
        uncertain=uncertain,
        blocked=blocked,
        checked=checked,
        ctx=ctx,
    )

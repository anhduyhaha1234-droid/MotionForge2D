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
from typing import Any, Sequence

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
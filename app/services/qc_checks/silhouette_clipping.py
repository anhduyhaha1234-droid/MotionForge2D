"""S11-T03C silhouette_clipping detector (W6).

Structural detector over mask bbox data vs the render frame boundary:
for every segment whose render window intersects the analysis window, the
clipped-pixel ratio of its mask bbox is measured with the SAME raw formula
T06A2 calibrated (``measure_silhouette_clipping``: clipped area outside the
frame divided by total bbox area, fixture contact_zorder_clipping.json)
and classified against the frozen T03A policy (metric
``silhouette_clipping``, ratio, increasing, warning = level-2 raw,
blocker = level-4 raw).

Classification is BINARY per policy boundaries via ``thresholds.classify``
(read-only consume; zero hard-coded numbers in this module):

- ratio <  warning boundary -> NO item (inside calibrated envelope);
- warning <= ratio < blocker -> ONE warning item (cosmetic clip);
- ratio >= blocker          -> ONE blocker item (subject area cut away).

Contract (production plan W6 · T03C):

- entry point ``detect_silhouette_clipping(args)`` returns a JSON-
  serializable list of QCItem candidates (empty list = pass); runnable by
  the T03A bounded runner in a child process;
- ``register()`` registers the entry point in the shared T03A registry
  (idempotent identity);
- evidence: ``schema_version=1``, ``evidence_window_key`` = sha256 over the
  canonical JSON of the content-derived core (reason, layer ref, metric,
  window, frame, bbox) — deterministic, byte-identical across runs;
- thresholds come ONLY from ``app.services.qc_checks.thresholds`` (T03A
  OWNER, frozen).

Input ``args`` schema (JSON-serializable):

``{analysis_window: {start_frame, end_frame},
    frame: {width, height},
    segments: [{id, logical_id, start_frame, end_frame, mask_artifact_id,
                bbox: [x0, y0, x1, y1]}]}``

Each segment inside the window yields at most ONE item; segments entirely
outside the analysis window are ignored (AC2: no item when in bounds).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.qc_checks.registry import DetectorSpec, register_detector
from app.services.qc_checks.thresholds import (
    STATUS_BLOCKER,
    classify,
    get_threshold,
)

DETECTOR_NAME = "silhouette_clipping"
DETECTOR_REVISION = "1.0.0"

#: Evidence contract version (AC4 — schema_version=1, content-derived).
EVIDENCE_SCHEMA_VERSION = 1


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _window(args: dict[str, Any]) -> dict[str, int]:
    window = args.get("analysis_window")
    if not isinstance(window, dict):
        raise ValueError("silhouette_clipping: analysis_window required")
    start = int(window.get("start_frame", -1))
    end = int(window.get("end_frame", -1))
    if start < 0 or end < start:
        raise ValueError(
            "silhouette_clipping: analysis_window start/end frames invalid "
            f"({start}, {end})"
        )
    return {"start_frame": start, "end_frame": end}


def _frame(args: dict[str, Any]) -> dict[str, float]:
    frame = args.get("frame")
    if not isinstance(frame, dict):
        raise ValueError("silhouette_clipping: frame object required")
    width = float(frame.get("width", 0.0))
    height = float(frame.get("height", 0.0))
    if width <= 0.0 or height <= 0.0:
        raise ValueError(
            "silhouette_clipping: frame width/height must be > 0 "
            f"({width}, {height})"
        )
    return {"width": width, "height": height}


def measure_clipping_ratio(args: dict[str, Any]) -> float:
    """Raw measurement: MAX clipped-pixel ratio across the in-window
    segments (0.0 when nothing is clipped).

    Mirrors T06A2 ``measure_silhouette_clipping`` exactly for one bbox and
    generalizes to the max over the active segments of the window.
    """
    window = _window(args)
    frame = _frame(args)
    segments = args.get("segments")
    if not isinstance(segments, list):
        raise ValueError("silhouette_clipping: segments list required")
    worst = 0.0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = int(seg.get("start_frame", 0))
        end = int(seg.get("end_frame", window["end_frame"]))
        if end < window["start_frame"] or start > window["end_frame"]:
            continue  # render window outside the analysis window
        bbox = seg.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        ratio = _clipped_ratio(bbox, frame)
        if ratio > worst:
            worst = ratio
    return worst


def _clipped_ratio(bbox: list[Any], frame: dict[str, float]) -> float:
    """T06A2 raw formula: clipped area outside the frame / bbox area."""
    x0, y0, x1, y1 = (float(v) for v in bbox)
    width = x1 - x0
    height = y1 - y0
    if width <= 0.0 or height <= 0.0:
        return 0.0  # degenerate mask bbox -> nothing measurable
    clipped_left = max(0.0, -x0)
    clipped_right = max(0.0, x1 - frame["width"])
    clipped_top = max(0.0, -y0)
    clipped_bottom = max(0.0, y1 - frame["height"])
    clipped = (clipped_left + clipped_right) * height + (
        (clipped_top + clipped_bottom) * width
    )
    return float(clipped / (width * height))


def detect_silhouette_clipping(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the silhouette-clipping structural check; QCItem candidates."""
    window = _window(args)
    frame = _frame(args)
    segments = args.get("segments")
    if not isinstance(segments, list):
        raise ValueError("silhouette_clipping: segments list required")
    entry = get_threshold(DETECTOR_NAME)  # READ-ONLY (T03A frozen policy)

    items: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict) or not seg.get("id"):
            continue
        start = int(seg.get("start_frame", 0))
        end = int(seg.get("end_frame", window["end_frame"]))
        if end < window["start_frame"] or start > window["end_frame"]:
            continue  # outside the analysis window -> ignored
        bbox = seg.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        measured = _clipped_ratio(bbox, frame)
        status, code = classify(DETECTOR_NAME, measured)
        if status == STATUS_BLOCKER:
            severity = "blocker"  # subject area cut beyond boundary
        elif status == "warning":
            severity = "warning"  # cosmetic clip
        else:
            continue  # inside the calibrated envelope -> NO item (AC2)
        seg_id = str(seg["id"])
        evidence = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "window": window,
            "frame": frame,
            "bbox": [float(v) for v in bbox],
            "mask_artifact_id": seg.get("mask_artifact_id"),
            "clipped_ratio": measured,
            "threshold": {
                "policy": entry["provenance"]["fixture"],
                "warning_boundary": entry["warning_boundary"],
                "blocker_boundary": entry["blocker_boundary"],
                "code": code,
            },
        }
        metric = {
            "name": DETECTOR_NAME,
            "value": measured,
            "code": code,
        }
        key_core = {
            "reason_code": DETECTOR_NAME,
            "layer_ref_type": "segment",
            "layer_ref_id": seg_id,
            "metric": metric,
            "window": window,
            "frame": frame,
            "bbox": evidence["bbox"],
            "schema_version": EVIDENCE_SCHEMA_VERSION,
        }
        evidence_window_key = hashlib.sha256(
            _canonical_json(key_core).encode("utf-8")
        ).hexdigest()
        confidence = float(seg.get("confidence", 1.0))
        if not 0.0 <= confidence <= 1.0:
            confidence = 1.0
        items.append(
            {
                "reason_code": DETECTOR_NAME,
                "category": DETECTOR_NAME,
                "severity": severity,
                "status": "open",
                "layer_ref_type": "segment",
                "layer_ref_id": seg_id,
                "segment_row_id": None,
                "segment_logical_id": seg.get("logical_id"),
                "evidence_window_key": evidence_window_key,
                "evidence": evidence,
                "detector": DETECTOR_NAME,
                "detector_revision": DETECTOR_REVISION,
                "confidence": confidence,
                "confidence_source": "derived",
                "checkpoint_ref": f"s11-t03c:{DETECTOR_NAME}",
                "metric": metric,
            }
        )
    return items


def register(*, version: str = DETECTOR_REVISION) -> DetectorSpec:
    """Register this detector in the shared T03A registry (idempotent)."""
    return register_detector(
        DETECTOR_NAME,
        "app.services.qc_checks.silhouette_clipping:detect_silhouette_clipping",
        version=version,
        description=(
            "silhouette_clipping: mask bbox clipped outside the render "
            "frame boundary; clipped-pixel ratio classified against the "
            "frozen T03A policy (ratio)"
        ),
    )
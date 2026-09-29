"""S11-T03D temporal_flicker detector (W6).

Frozen contract (C4-F5, overlay §S11 L370-371):

- measures per-frame metric noise inside a window (mean inter-frame
  luminance delta) using the EXACT T06A2 calibration formula
  (``measure_temporal_flicker`` — mean of |diff(luminance)|);
- classification is READ-ONLY from the frozen T03A policy (boundaries are
  the T06A2 raw values: warning=level 2 0.024895525, blocker=level 4
  0.099582099, unit level);
- evidence: schema_version=1, content-derived, idempotent; records the
  frame/window, frame count, feature revision and the measured delta.

Entry point ``detect(args)`` is registry-compatible with the T03A bounded
runner child protocol.  Never returns UNKNOWN/deferred.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.qc_checks.registry import register_detector
from app.services.qc_checks.thresholds import (
    STATUS_BLOCKER,
    classify,
    get_threshold,
    load_policy,
)

REASON_CODE = "temporal_flicker"
CATEGORY = "temporal_flicker"
METRIC = "temporal_flicker"
DETECTOR_REVISION = "1.0.0"

#: Deterministic temporal-feature revision (zero network/model download).
FEATURE_REVISION = "1.0.0"

CONFIDENCE = 0.95


def measure_flicker(luminance: list[float]) -> float:
    """Mean inter-frame luminance delta — the T06A2 measurement formula.

    Deterministic and idempotent over identical input series.
    """
    if len(luminance) < 2:
        return math.inf
    total = 0.0
    for a, b in zip(luminance[:-1], luminance[1:], strict=True):
        total += abs(float(b) - float(a))
    return total / (len(luminance) - 1)


def _window_key(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(
        dict(evidence), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _policy_ref() -> dict[str, Any]:
    entry = get_threshold(METRIC)
    return {
        "policy_id": load_policy()["policy_id"],
        "content_hash": load_policy()["content_hash"],
        "metric": METRIC,
        "unit": entry["unit"],
        "warning_boundary": entry["warning_boundary"],
        "blocker_boundary": entry["blocker_boundary"],
        "sanity_bounds": entry["sanity_bounds"],
    }


def detect(args: dict[str, Any]) -> dict[str, Any]:
    """Run the temporal flicker check on one per-frame metric window.

    Args: context ids, ``window`` ({start_frame, end_frame}) and
    ``luminance`` (per-frame luminance series, deterministic content).
    """
    luminance = [float(v) for v in args.get("luminance") or []]
    flicker_raw = measure_flicker(luminance)
    # Calibration precision: T06A2 raw values are stored rounded to 9
    # decimals — compare at the same precision (deterministic boundary hits).
    flicker = round(flicker_raw, 9)
    status, code = classify(METRIC, flicker)

    items: list[dict[str, Any]] = []
    if status in (STATUS_BLOCKER, "warning"):
        measured = {
            "mean_interframe_luminance_delta": round(flicker, 9),
            "interframe_deltas": [
                round(abs(float(b) - float(a)), 9)
                for a, b in zip(luminance[:-1], luminance[1:], strict=True)
            ],
        }
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "reason_code": REASON_CODE,
            "metric": {
                "name": METRIC,
                "value": round(flicker, 9),
                "unit": "level",
                "policy": _policy_ref(),
            },
            "window": args["window"],
            "frame_count": len(luminance),
            "feature_revision": FEATURE_REVISION,
            "measured": measured,
        }
        items.append(
            {
                "workspace_id": args["workspace_id"],
                "project_id": args["project_id"],
                "video_item_id": args["video_item_id"],
                "layer_ref_type": args["layer_ref_type"],
                "layer_ref_id": args["layer_ref_id"],
                "reason_code": REASON_CODE,
                "evidence_window_key": _window_key(evidence),
                "evidence": evidence,
                "severity": status,
                "category": CATEGORY,
                "detector": REASON_CODE,
                "detector_revision": DETECTOR_REVISION,
                "confidence": CONFIDENCE,
                "confidence_source": "detector",
                "checkpoint_ref": args["checkpoint_ref"],
                "segment_row_id": args.get("segment_row_id"),
                "segment_logical_id": args.get("segment_logical_id"),
            }
        )

    return {
        "detector": REASON_CODE,
        "reason_code": REASON_CODE,
        "status": status,
        "code": code,
        "mean_interframe_luminance_delta": round(flicker, 9),
        "items": items,
    }


register_detector(
    REASON_CODE,
    "app.services.qc_checks.temporal_flicker:detect",
    version=DETECTOR_REVISION,
    description=(
        "Per-frame metric noise inside a window (mean inter-frame luminance "
        "delta, T06A2 formula, frozen policy thresholds) (S11-T03D)."
    ),
)
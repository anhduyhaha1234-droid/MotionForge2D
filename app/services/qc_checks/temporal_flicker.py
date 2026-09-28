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
from app.services.qc_evidence import measure as qcm

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


# ── MF-END-22.3: silent/static OUTPUT + flicker on the RENDERED pixels ───────
#
# ``compare_static_and_flicker`` measures the DECODED OUTPUT's per-frame
# luminance series (the same quantity the frozen T03A flicker policy is
# calibrated on) and, when the source series is supplied, the SOURCE's own:
#
# - a window whose every frame is IDENTICAL (all inter-frame deltas 0.0) while
#   the source moves is a SILENT/STATIC output -> ``QC_COMPARISON_MOTION_STATIC``
#   (hard), the same defect family trajectory_drift reports from the traces,
#   measured here directly on the pixels;
# - a frozen window over a static source is CONSISTENT (recorded, not a defect);
# - a flickering window is classified against the frozen T03A flicker policy
#   (blocker -> hard, warning -> soft).

COMPARISON_DETECTOR_NAME = "temporal_flicker_comparison"

CODE_FLICKER_BLOCKER = "QC_COMPARISON_FLICKER_BLOCKER"
CODE_FLICKER_WARNING = "QC_COMPARISON_FLICKER_WARNING"


def _flicker_item(**kwargs: Any) -> dict[str, Any]:
    """One flicker item bound to the REAL T03A flicker policy entry.

    ``comparison_item`` binds a known comparison metric; flicker is governed
    by the frozen T03A policy, so the item is built with a valid metric and
    then re-bound to the T03A ``temporal_flicker`` entry (boundaries cited
    from that policy, never re-typed) with its window key recomputed.
    """
    item = qcm.comparison_item(metric=qcm.METRIC_MOTION_ATTENUATION, **kwargs)
    entry = get_threshold(METRIC)
    item["metric"] = METRIC
    item["policy"] = {
        "policy_id": load_policy()["policy_id"],
        "content_hash": load_policy()["content_hash"],
        "metric": METRIC,
        "unit": entry["unit"],
        "warning_boundary": entry["warning_boundary"],
        "blocker_boundary": entry["blocker_boundary"],
        "provenance": entry["provenance"],
    }
    core = {k: v for k, v in item.items() if k != "evidence_window_key"}
    item["evidence_window_key"] = qcm.content_digest(core)
    return item


def compare_static_and_flicker(args: dict[str, Any]) -> dict[str, Any]:
    """Check the output pixels for silent/static motion and flicker.

    ``args`` (JSON-safe): ``{luminance: [...], source_luminance: [...] | absent,
    window: {...} | absent, appearance: {...} | absent}`` — the luminance
    series are measured on DECODED frames (output and source respectively).
    """
    luminance = [float(v) for v in args.get("luminance") or []]
    source_luminance = [float(v) for v in args.get("source_luminance") or []]
    window = dict(args.get("window") or {})
    items: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    if len(luminance) < 2:
        uncertain.append(
            {
                "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                "role_id": "",
                "frames": list(window.values()) if window else [],
                "detail": (
                    "fewer than two decoded output frames were supplied, so no "
                    "inter-frame measurement exists (nothing is invented)"
                ),
            }
        )
        verdict = qcm.compare_verdict(
            items, uncertain=uncertain, blocked=blocked, appearance=None
        )
        return {
            "detector": COMPARISON_DETECTOR_NAME,
            "reason_code": REASON_CODE,
            "schema_version": qcm.COMPARISON_SCHEMA_VERSION,
            "revision": qcm.COMPARISON_REVISION,
            "policy": {
                "policy_id": qcm.COMPARISON_POLICY_ID,
                "digest": qcm.comparison_policy_digest(),
            },
            "verdict": verdict,
            "items": [],
            "unknown": uncertain,
            "blocked": [],
            "checked": [],
            "mapping": {},
            "provenance": {},
        }

    deltas = [abs(b - a) for a, b in zip(luminance[:-1], luminance[1:], strict=True)]
    source_deltas = [
        abs(b - a)
        for a, b in zip(source_luminance[:-1], source_luminance[1:], strict=True)
    ]
    max_delta = max(deltas) if deltas else 0.0
    mean_delta = sum(deltas) / float(len(deltas)) if deltas else 0.0
    source_max = max(source_deltas) if source_deltas else None
    source_mean = (
        sum(source_deltas) / float(len(source_deltas)) if source_deltas else None
    )
    frozen = bool(deltas) and max_delta == 0.0
    window_start = int(window.get("start_frame", 0))
    frames = list(range(window_start, window_start + len(luminance)))

    appearance = {
        "mean_interframe_luminance_delta": round(mean_delta, 9),
        "max_interframe_luminance_delta": round(max_delta, 9),
        "frozen_window": frozen,
        "source_mean_interframe_delta": (
            round(source_mean, 9) if source_mean is not None else None
        ),
        "source_max_interframe_delta": (
            round(source_max, 9) if source_max is not None else None
        ),
    }
    checked: list[dict[str, Any]] = []

    if frozen and source_mean is not None and source_mean > 0.0:
        ratio = 1.0 - (mean_delta / source_mean)
        items.append(
            qcm.comparison_item(
                metric=qcm.METRIC_MOTION_ATTENUATION,
                code=qcm.CODE_MOTION_STATIC,
                level=qcm.LEVEL_HARD,
                severity="blocker",
                role_id="",
                frames=frames,
                detail=(
                    "every decoded output frame of this window is IDENTICAL "
                    "(max inter-frame luminance delta 0.0) while the source "
                    f"window moves (mean {round(source_mean, 9)}/frame): a "
                    "silent/static output where the source has motion (U11)"
                ),
                evidence={
                    "appearance": appearance,
                    "measured": {"attenuation_ratio": round(ratio, 9)},
                    "thresholds": qcm.comparison_threshold(
                        qcm.METRIC_MOTION_ATTENUATION
                    ),
                    "window": window,
                    "measure": "decoded output luminance deltas vs the source's",
                },
            )
        )
        checked.append({"status": qcm.VERDICT_FAIL, "reason": "frozen_output"})
    elif frozen:
        checked.append(
            {
                "status": qcm.VERDICT_PASS,
                "reason": "frozen_output_without_source_motion",
                "note": (
                    "the window is frozen and no source motion contradicts it — "
                    "recorded as evidence, not a defect"
                ),
            }
        )

    flicker = round(measure_flicker(luminance), 9)
    status, _code = classify(METRIC, flicker)
    if status == STATUS_BLOCKER:
        items.append(
            _flicker_item(
                code=CODE_FLICKER_BLOCKER,
                level=qcm.LEVEL_HARD,
                severity="blocker",
                role_id="",
                frames=frames,
                detail=(
                    f"the output window flickers beyond the frozen policy "
                    f"(mean inter-frame luminance delta {flicker})"
                ),
                evidence={
                    "appearance": appearance,
                    "measured": {"temporal_flicker": flicker},
                    "window": window,
                },
            )
        )
    elif status == "warning":
        items.append(
            _flicker_item(
                code=CODE_FLICKER_WARNING,
                level=qcm.LEVEL_SOFT,
                severity="warning",
                role_id="",
                frames=frames,
                detail=(
                    f"the output window flickers inside the warning band "
                    f"(mean inter-frame luminance delta {flicker})"
                ),
                evidence={
                    "appearance": appearance,
                    "measured": {"temporal_flicker": flicker},
                    "window": window,
                },
            )
        )
    else:
        checked.append({"status": qcm.VERDICT_PASS, "temporal_flicker": flicker})

    verdict = qcm.compare_verdict(
        items,
        uncertain=uncertain,
        blocked=blocked,
        appearance={**appearance, **(dict(args.get("appearance") or {}))},
    )
    return {
        "detector": COMPARISON_DETECTOR_NAME,
        "reason_code": REASON_CODE,
        "schema_version": qcm.COMPARISON_SCHEMA_VERSION,
        "revision": qcm.COMPARISON_REVISION,
        "policy": {
            "policy_id": qcm.COMPARISON_POLICY_ID,
            "digest": qcm.comparison_policy_digest(),
        },
        "verdict": verdict,
        "items": items,
        "unknown": uncertain,
        "blocked": blocked,
        "checked": checked,
        "mapping": {},
        "provenance": {},
    }

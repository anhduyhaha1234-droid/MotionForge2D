"""S11-T03D edge_halo detector (W6).

Frozen contract (C4-F5, overlay §S11 L370-371):

- measures the halo around the edge of the RENDERED mask against the
  EXPECTED mask (dự kiến — the pinned/reference geometry);
- the metric derives from the T06A2 calibration measurement
  (``measure_edge_halo``: mean halo width px = ring area / inner
  circumference) — same geometry: filled disc + concentric halo ring;
- classification is READ-ONLY from the frozen T03A policy (boundaries are
  the T06A2 raw values: warning=level 2 2.021267777, blocker=level 4
  8.737606376);
- evidence: schema_version=1, content-derived, idempotent; records artifact
  hashes (rendered + expected masks), frame, mask revision, feature revision
  and the measured halo width.

Entry point ``detect(args)`` is registry-compatible with the T03A bounded
runner child protocol.  Never returns UNKNOWN/deferred — evidence hash
corruption fails closed with ``THRESHOLD_INVALID`` and zero items.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.qc_checks.registry import register_detector
from app.services.qc_checks.thresholds import (
    CODE_THRESHOLD_INVALID,
    STATUS_BLOCKER,
    STATUS_INVALID,
    classify,
    get_threshold,
    load_policy,
)

REASON_CODE = "edge_halo"
CATEGORY = "edge_halo"
METRIC = "edge_halo"
DETECTOR_REVISION = "1.0.0"

#: Deterministic local mask-feature revision (zero network/model download).
FEATURE_REVISION = "1.0.0"

CONFIDENCE = 0.95


def _mask_sha256(mask: dict[str, Any]) -> str:
    raw = json.dumps(mask["pixels"], separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _verify_mask_sha256(mask: dict[str, Any], declared: str) -> bool:
    return isinstance(mask, dict) and _mask_sha256(mask) == declared


def measure_halo_width(
    rendered: dict[str, Any], expected: dict[str, Any], inner_radius_px: float
) -> float:
    """Mean halo width (px) — the T06A2 measurement formula.

    ring area = pixels inside the rendered mask but outside the expected
    mask; inner circumference = 2*pi*inner_radius_px.  Deterministic and
    idempotent over identical mask bytes.
    """
    ring_area = 0.0
    for row_r, row_e in zip(rendered["pixels"], expected["pixels"], strict=True):
        for v_r, v_e in zip(row_r, row_e, strict=True):
            if bool(v_r) and not bool(v_e):
                ring_area += 1.0
    circumference = 2.0 * math.pi * float(inner_radius_px)
    if circumference <= 0.0:
        return math.inf
    return ring_area / circumference


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
    """Run the edge halo check on one rendered-mask frame.

    Args: context ids, ``frame_index``, ``mask_revision``, ``inner_radius_px``
    (reference geometry), ``rendered``/``expected`` mask artifacts with
    content-derived sha256 + width/height + pixels.
    """
    rendered = args.get("rendered") or {}
    expected = args.get("expected") or {}
    if not _verify_mask_sha256(
        rendered.get("mask") or {}, rendered.get("sha256", "")
    ) or not _verify_mask_sha256(expected.get("mask") or {}, expected.get("sha256", "")):
        return {
            "detector": REASON_CODE,
            "reason_code": REASON_CODE,
            "status": STATUS_INVALID,
            "code": CODE_THRESHOLD_INVALID,
            "halo_width_px": None,
            "items": [],
        }

    halo_width = round(
        measure_halo_width(
            rendered["mask"], expected["mask"], float(args["inner_radius_px"])
        ),
        9,
    )
    status, code = classify(METRIC, halo_width)

    items: list[dict[str, Any]] = []
    if status in (STATUS_BLOCKER, "warning"):
        measured = {
            "halo_width_px": round(halo_width, 9),
            "ring_area_px": sum(
                1.0
                for row_r, row_e in zip(
                    rendered["mask"]["pixels"], expected["mask"]["pixels"], strict=True
                )
                for v_r, v_e in zip(row_r, row_e, strict=True)
                if bool(v_r) and not bool(v_e)
            ),
            "inner_circumference_px": round(
                2.0 * math.pi * float(args["inner_radius_px"]), 9
            ),
        }
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "reason_code": REASON_CODE,
            "metric": {
                "name": METRIC,
                "value": round(halo_width, 9),
                "unit": "px",
                "policy": _policy_ref(),
            },
            "frame_index": args["frame_index"],
            "mask_revision": args["mask_revision"],
            "feature_revision": FEATURE_REVISION,
            "rendered": {
                "artifact_id": rendered["artifact_id"],
                "sha256": rendered["sha256"],
                "mask": {
                    "width": rendered["mask"]["width"],
                    "height": rendered["mask"]["height"],
                },
            },
            "expected": {
                "artifact_id": expected["artifact_id"],
                "sha256": expected["sha256"],
                "mask": {
                    "width": expected["mask"]["width"],
                    "height": expected["mask"]["height"],
                },
            },
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
        "halo_width_px": round(halo_width, 9),
        "items": items,
    }


register_detector(
    REASON_CODE,
    "app.services.qc_checks.edge_halo:detect",
    version=DETECTOR_REVISION,
    description=(
        "Halo width around the rendered mask edge vs the expected mask "
        "(T06A2 measurement formula, frozen policy thresholds) (S11-T03D)."
    ),
)
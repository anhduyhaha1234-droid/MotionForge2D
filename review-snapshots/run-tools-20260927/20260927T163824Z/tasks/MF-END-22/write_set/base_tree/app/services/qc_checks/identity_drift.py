"""S11-T03D identity_drift detector (W6).

Frozen contract (C4-F5, overlay §S11 L370-371, Decision B):

- visual identity evidence comes from the rendered/masked segment crop plus
  the PINNED pack/slot reference (artifact id + sha256) — never from network
  or model downloads (deterministic local feature only);
- the metric measures the visual identity distance between the current
  rendered evidence and the pinned reference AND between adjacent frames;
- metadata role/instance/cast-pin flip is a fail-closed blocker of its own
  (identity flip item) but NEVER replaces the visual metric — when both fire
  both items are emitted (distinct content-derived evidence window keys);
- thresholds are READ-ONLY from the frozen T03A policy
  (``app.services.qc_checks.thresholds``), whose boundaries are the T06A2
  calibration raw values (warning=level 2, blocker=level 4);
- evidence: schema_version=1, content-derived, idempotent; records artifact
  hashes, frame/window, crop revision, feature revision and the measured
  distance.

The entry point ``detect(args)`` is registry-compatible with the T03A bounded
runner child protocol: JSON dict in, JSON-safe dict out.  It NEVER returns an
UNKNOWN or deferred reason — on evidence corruption it fails closed with
``THRESHOLD_INVALID`` and zero items.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.qc_checks.registry import register_detector
from app.services.qc_checks.thresholds import (
    CODE_THRESHOLD_BLOCKER,
    CODE_THRESHOLD_INVALID,
    CODE_THRESHOLD_PASS,
    STATUS_BLOCKER,
    STATUS_INVALID,
    classify,
    get_threshold,
    load_policy,
)

REASON_CODE = "identity_drift"
CATEGORY = "identity_drift"
METRIC = "identity_drift"
DETECTOR_REVISION = "1.0.0"

#: Deterministic local feature revision — bump only when the feature
#: definition itself changes (zero network/model downloads by contract).
FEATURE_REVISION = "1.0.0"

#: Detector-derived confidence (stable, content-independent).
CONFIDENCE = 0.95
FLIP_CONFIDENCE = 0.98


def _crop_sha256(crop: dict[str, Any]) -> str:
    """Content-derived sha256 of a crop's pixel payload (canonical JSON)."""
    raw = json.dumps(crop["pixels"], separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _verify_crop_sha256(crop: dict[str, Any], declared: str) -> bool:
    return isinstance(crop, dict) and _crop_sha256(crop) == declared


def extract_feature(crop: dict[str, Any]) -> list[float]:
    """Deterministic local feature: flattened grayscale crop values.

    Pure stdlib/numpy-free byte-level deterministic — same pixels always
    produce the same feature vector (the revision pins the definition).
    """
    return [float(v) for row in crop["pixels"] for v in row]


def _rms_distance(a: list[float], b: list[float]) -> float:
    """Root-mean-square pixel difference — the visual identity distance.

    Deterministic euclidean-style distance, unit px (intensity delta); for a
    uniform delta d it is exactly d, making the calibrated policy boundaries
    (warning=2.0, blocker=8.0 from T06A2 raw values) directly actionable.
    """
    n = len(a)
    if n == 0 or len(b) != n:
        return math.inf
    total = 0.0
    for x, y in zip(a, b, strict=True):
        d = x - y
        total += d * d
    return math.sqrt(total / n)


def _window_key(evidence: dict[str, Any]) -> str:
    """Content-derived evidence window key (natural-key idempotency)."""
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


def _evidence_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "frame_index": f["frame_index"],
            "artifact_id": f["artifact_id"],
            "sha256": f["sha256"],
        }
        for f in frames
    ]


def _base_evidence(
    args: dict[str, Any],
    *,
    measured: dict[str, Any],
    reference: dict[str, Any],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "reason_code": REASON_CODE,
        "metric": {
            "name": METRIC,
            "value": measured["measured_distance"],
            "unit": "px",
            "policy": _policy_ref(),
        },
        "pinned_reference": {
            "artifact_id": reference["artifact_id"],
            "sha256": reference["sha256"],
            "crop_revision": reference["crop_revision"],
        },
        "frames": _evidence_frames(frames),
        "feature_revision": FEATURE_REVISION,
        "measured": measured,
    }


def _make_item(
    args: dict[str, Any],
    evidence: dict[str, Any],
    *,
    severity: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "workspace_id": args["workspace_id"],
        "project_id": args["project_id"],
        "video_item_id": args["video_item_id"],
        "layer_ref_type": args["layer_ref_type"],
        "layer_ref_id": args["layer_ref_id"],
        "reason_code": REASON_CODE,
        "evidence_window_key": _window_key(evidence),
        "evidence": evidence,
        "severity": severity,
        "category": CATEGORY,
        "detector": REASON_CODE,
        "detector_revision": DETECTOR_REVISION,
        "confidence": confidence,
        "confidence_source": "detector",
        "checkpoint_ref": args["checkpoint_ref"],
        "segment_row_id": args.get("segment_row_id"),
        "segment_logical_id": args.get("segment_logical_id"),
    }


def detect(args: dict[str, Any]) -> dict[str, Any]:
    """Run the identity drift check on one rendered evidence window.

    Args (JSON-safe): workspace/project/video context, ``pinned_reference``
    (artifact id + sha256 + crop), ``cast_pin`` (authority: expected metadata
    + compatibility verdict from ``ProjectCastMapping`` pin evaluated through
    ``evaluate_compatibility``) and ``frames`` (rendered/masked segment crops
    with their artifact hashes + per-frame metadata).
    """
    reference = args.get("pinned_reference") or {}
    frames = args.get("frames") or []
    cast_pin = args.get("cast_pin") or {}

    # ── evidence integrity: content-derived hashes (fail-closed) ──────────
    ref_crop = reference.get("crop")
    if not _verify_crop_sha256(ref_crop or {}, reference.get("sha256", "")):
        return {
            "detector": REASON_CODE,
            "reason_code": REASON_CODE,
            "status": STATUS_INVALID,
            "code": CODE_THRESHOLD_INVALID,
            "measured_distance": None,
            "identity_flip": {"flipped": False, "flip_kind": None},
            "items": [],
        }
    for frame in frames:
        if not _verify_crop_sha256(frame.get("crop") or {}, frame.get("sha256", "")):
            return {
                "detector": REASON_CODE,
                "reason_code": REASON_CODE,
                "status": STATUS_INVALID,
                "code": CODE_THRESHOLD_INVALID,
                "measured_distance": None,
                "identity_flip": {"flipped": False, "flip_kind": None},
                "items": [],
            }

    # ── deterministic local features ───────────────────────────────────────
    ref_feature = extract_feature(ref_crop or {})
    frame_features: list[list[float]] = [
        extract_feature(f["crop"]) for f in frames
    ]

    # ── visual identity distance: current vs pinned reference, and ─────────
    #    adjacent-frame evidence (worst case wins — fail-closed)
    reference_distances = [
        _rms_distance(feature, ref_feature) for feature in frame_features
    ]
    adjacent_distances: list[float] = []
    for i in range(1, len(frame_features)):
        adjacent_distances.append(
            _rms_distance(frame_features[i], frame_features[i - 1])
        )
    max_reference = max(reference_distances) if reference_distances else 0.0
    max_adjacent = max(adjacent_distances) if adjacent_distances else 0.0
    measured_distance = max(max_reference, max_adjacent)

    status, code = classify(METRIC, measured_distance)
    expected_metadata = cast_pin.get("expected_metadata") or {}
    observed = [dict(f.get("metadata") or {}) for f in frames]
    vs_pin = any(m != expected_metadata for m in observed)
    adjacent_change = any(observed[i] != observed[i - 1] for i in range(1, len(observed)))
    incompatible = cast_pin.get("compatible") is False
    flipped = vs_pin or adjacent_change or incompatible
    if incompatible:
        flip_kind = "cast_authority_incompatible"
    elif adjacent_change:
        flip_kind = "adjacent_metadata_change"
    elif vs_pin:
        flip_kind = "metadata_vs_pin"
    else:
        flip_kind = None

    # Fail-closed overall verdict: a metadata/cast-pin flip raises the whole
    # check to blocker even when the visual metric is inside the pass band
    # (the flip is a blocker of its own — AC2: it never replaces the visual
    # metric, but it does dominate the check status).
    if flipped and code == CODE_THRESHOLD_PASS:
        status = STATUS_BLOCKER
        code = CODE_THRESHOLD_BLOCKER

    measured = {
        "reference_distance_max_px": round(max_reference, 6),
        "max_adjacent_distance_px": round(max_adjacent, 6),
        "measured_distance": round(measured_distance, 6),
    }

    items: list[dict[str, Any]] = []

    # 1) fail-closed identity flip blocker — SEPARATE item, does NOT replace
    #    the visual metric (both are always measured and reported).
    if flipped:
        flip_evidence = _base_evidence(
            args, measured=measured, reference=reference, frames=frames
        )
        flip_evidence["identity_flip"] = {
            "flipped": True,
            "flip_kind": flip_kind,
            "expected": expected_metadata,
            "observed": observed,
            "compatibility": {
                "compatible": cast_pin.get("compatible", True),
                "reasons": list(cast_pin.get("compatibility_reasons") or []),
            },
        }
        items.append(_make_item(args, flip_evidence, severity=STATUS_BLOCKER,
                                confidence=FLIP_CONFIDENCE))

    # 2) visual identity drift item whenever the policy boundary is crossed —
    #    independent of any flip (AC2: flip does not replace the visual metric).
    if status in (STATUS_BLOCKER, "warning"):
        visual_evidence = _base_evidence(
            args, measured=measured, reference=reference, frames=frames
        )
        items.append(_make_item(args, visual_evidence, severity=status,
                                confidence=CONFIDENCE))

    return {
        "detector": REASON_CODE,
        "reason_code": REASON_CODE,
        "status": status,
        "code": code,
        "measured_distance": round(measured_distance, 6),
        "identity_flip": {"flipped": flipped, "flip_kind": flip_kind},
        "items": items,
    }


#: Registry contract (T03A): idempotent registration of the runner entry
#: point.  Re-import in the runner child is side-effect safe (register is
#: identity-idempotent).
register_detector(
    REASON_CODE,
    "app.services.qc_checks.identity_drift:detect",
    version=DETECTOR_REVISION,
    description=(
        "Visual identity distance (pinned reference + adjacent frames) with "
        "fail-closed metadata/cast-pin flip blocker (S11-T03D)."
    ),
)
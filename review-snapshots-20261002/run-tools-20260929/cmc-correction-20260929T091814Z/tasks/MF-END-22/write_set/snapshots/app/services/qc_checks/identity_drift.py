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
from app.services.qc_evidence import measure as qcm

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


# ── MF-END-22.1/22.4: SOURCE identity expectations vs OUTPUT observations ────
#
# The identity comparison asks one binary question per role: is the role's
# instance still linked to its declared identity in the OUTPUT observations
# (MF-END-21 ``role_match``, measured against the pinned cast reference
# pixels)?  An UNMATCHED link (the output pixels no longer match the role's
# reference) is a hard identity loss (the TURN symptom); an AMBIGUOUS match or
# a missing reference is not a defect but MISSING INFORMATION — it is reported
# as a typed UNKNOWN and never guessed into a pass or a fail.

COMPARISON_DETECTOR_NAME = "identity_drift_comparison"


def compare_identity_facts(args: dict[str, Any]) -> dict[str, Any]:
    """Compare the roles' identity links with the source expectations.

    ``args`` is the shared comparator schema plus optional ``expected_roles``
    (the source-side cast list); without it the expected roles are read from
    the output artifact's declared segments and from the source facts.
    """
    from app.services import rendered_observations as ro  # lazy: typed reasons

    ctx, refusals = qcm.comparison_context(args)
    if refusals:
        verdict = qcm.compare_verdict(
            [], blocked=refusals, appearance=args.get("appearance")
        )
        return qcm.comparison_result(
            detector=COMPARISON_DETECTOR_NAME,
            reason_code=REASON_CODE,
            verdict=verdict,
            items=[],
            uncertain=[],
            blocked=refusals,
            checked=[],
            ctx={},
            extra={"refusals": refusals},
        )

    observations = ctx["observations"]
    expected: list[str] = []
    for role in args.get("expected_roles") or []:
        role_id = str(role)
        if role_id and role_id not in expected:
            expected.append(role_id)
    if not expected:
        for segment in observations.get("segments") or []:
            role_id = str(segment.get("role_id") or "")
            if role_id and role_id not in expected:
                expected.append(role_id)
        for fact in ctx["facts"].get("contacts") or []:
            for key in ("subject_role_id", "object_role_id"):
                role_id = str(fact.get(key) or "")
                if role_id and role_id not in expected:
                    expected.append(role_id)
        for fact in ctx["facts"].get("occlusions") or []:
            for key in ("occluder_role_id", "occludee_role_id"):
                role_id = str(fact.get(key) or "")
                if role_id and role_id not in expected:
                    expected.append(role_id)

    span = observations.get("span") or {}
    span_start = int(span.get("start_frame", 0))
    span_end = int(span.get("end_frame_exclusive", span_start))
    window_frames = list(range(span_start, span_end))

    items: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []

    for role in expected:
        track = qcm.track_by_role(observations, role)
        if track is None:
            refusal = qcm.refused_role(observations, role)
            ratio = qcm.measure_unlinked_ratio(["unknown"] * max(1, len(window_frames)))
            status, _code = qcm.classify_comparison(qcm.METRIC_IDENTITY_UNLINKED, ratio)
            level = qcm.LEVEL_HARD if status == "blocker" else qcm.LEVEL_SOFT
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_IDENTITY_UNLINKED,
                    code=qcm.CODE_IDENTITY_LOST,
                    level=level,
                    severity="blocker" if level == qcm.LEVEL_HARD else "warning",
                    role_id=role,
                    frames=window_frames,
                    detail=(
                        f"the output carries NO observation track for the expected "
                        f"role {role!r} — the role's identity is lost in the render"
                    ),
                    evidence={
                        "output_refusal": refusal,
                        "measured": {"unlinked_ratio": ratio},
                        "thresholds": qcm.comparison_threshold(
                            qcm.METRIC_IDENTITY_UNLINKED
                        ),
                        "measure": (
                            "the expected role has no usable output instance: "
                            "every frame of the output window is unlinked"
                        ),
                    },
                )
            )
            checked.append({"role_id": role, "status": qcm.VERDICT_FAIL})
            continue

        match = dict(track.get("role_match") or {})
        state = str(match.get("state") or "")
        reason = match.get("reason")
        linked_role = match.get("role_id")
        track_start = int(track.get("start_frame", span_start))
        track_end = int(track.get("end_frame", span_end))
        role_frames = list(range(track_start, track_end)) or window_frames
        states = ["matched" if state == ro.MATCH_MATCHED else "unknown"] * len(
            role_frames
        )
        ratio = qcm.measure_unlinked_ratio(states)
        status, _code = qcm.classify_comparison(qcm.METRIC_IDENTITY_UNLINKED, ratio)
        base_evidence = {
            "role_id": role,
            "segment_id": str(track.get("segment_id") or ""),
            "instance_id": str(track.get("instance_id") or ""),
            "measured": {
                "unlinked_ratio": ratio,
                "role_match_state": state,
                "role_match_reason": reason,
                "linked_role_id": linked_role,
                "best_distance": match.get("best_distance"),
                "match_max_distance": match.get("match_max_distance"),
            },
            "thresholds": qcm.comparison_threshold(qcm.METRIC_IDENTITY_UNLINKED),
            "frames": role_frames,
            "mapping": ctx.get("mapping"),
            "measure": (
                "the MF-END-21 role link is measured against the role's PINNED "
                "cast reference pixels; the unlinked frame ratio is classified "
                "against the frozen identity policy"
            ),
        }
        if state == ro.MATCH_MATCHED and (
            linked_role == role or match.get("agrees_with_declared_role") is True
        ):
            flags = [
                dict(flag)
                for flag in track.get("flags") or []
                if str(flag.get("code")) == ro.FLAG_UNSTABLE_LINK
            ]
            if flags:
                items.append(
                    qcm.comparison_item(
                        metric=qcm.METRIC_IDENTITY_UNLINKED,
                        code=qcm.CODE_IDENTITY_WEAK,
                        level=qcm.LEVEL_SOFT,
                        severity="warning",
                        role_id=role,
                        frames=[
                            int(flag["frame"])
                            for flag in flags
                            if flag.get("frame") is not None
                        ]
                        or role_frames,
                        detail=(
                            f"the identity link of {role!r} is unstable in the "
                            f"output ({len(flags)} unstable link frame(s))"
                        ),
                        evidence={**base_evidence, "unstable_links": flags},
                    )
                )
                checked.append({"role_id": role, "status": qcm.VERDICT_WARN})
                continue
            checked.append({"role_id": role, "status": qcm.VERDICT_PASS})
            continue
        if state == ro.MATCH_MATCHED:
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_IDENTITY_UNLINKED,
                    code=qcm.CODE_IDENTITY_LOST,
                    level=qcm.LEVEL_HARD,
                    severity="blocker",
                    role_id=role,
                    frames=role_frames,
                    detail=(
                        f"the output instance of {role!r} is linked to a DIFFERENT "
                        f"identity {linked_role!r} — the role has been substituted"
                    ),
                    evidence=base_evidence,
                )
            )
            checked.append({"role_id": role, "status": qcm.VERDICT_FAIL})
            continue
        if reason in (ro.UNKNOWN_REASON_AMBIGUOUS, ro.UNKNOWN_REASON_NO_REFERENCE):
            uncertain.append(
                {
                    "code": qcm.CODE_COMPARISON_UNKNOWN,
                    "role_id": role,
                    "frames": role_frames,
                    "detail": (
                        f"the identity link of {role!r} is a TYPED UNKNOWN on the "
                        f"output (reason={reason!r}); the comparison refuses to "
                        "guess an identity verdict"
                    ),
                    "evidence": base_evidence,
                }
            )
            checked.append({"role_id": role, "status": qcm.VERDICT_UNKNOWN})
            continue
        items.append(
            qcm.comparison_item(
                metric=qcm.METRIC_IDENTITY_UNLINKED,
                code=qcm.CODE_IDENTITY_LOST,
                level=qcm.LEVEL_HARD if status == "blocker" else qcm.LEVEL_SOFT,
                severity="blocker" if status == "blocker" else "warning",
                role_id=role,
                frames=role_frames,
                detail=(
                    f"the output instance of {role!r} does not match its pinned "
                    f"identity (reason={reason!r}, best distance "
                    f"{match.get('best_distance')!r} > max "
                    f"{match.get('match_max_distance')!r})"
                ),
                evidence=base_evidence,
            )
        )
        checked.append(
            {
                "role_id": role,
                "status": qcm.VERDICT_FAIL if status == "blocker" else qcm.VERDICT_WARN,
            }
        )

    verdict = qcm.compare_verdict(
        items, uncertain=uncertain, blocked=blocked, appearance=args.get("appearance")
    )
    return qcm.comparison_result(
        detector=COMPARISON_DETECTOR_NAME,
        reason_code=REASON_CODE,
        verdict=verdict,
        items=items,
        uncertain=uncertain,
        blocked=blocked,
        checked=checked,
        ctx=ctx,
    )

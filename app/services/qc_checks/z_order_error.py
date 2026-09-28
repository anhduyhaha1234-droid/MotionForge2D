"""S11-T03C z_order_error detector (W6).

Structural detector over the occlusion graph vs the OBSERVED render order:

- occluder_segment_id -> occludee_segment_id edges (OcclusionRecord)
  declare that the occluder must render STRICTLY ABOVE the occludee;
- the observed render order comes from the renderer route/lock manifest
  (PREFERRED — consumed via the PUBLIC S09 contract
  ``app.persistence.structural_lock.validate_manifest``, never private
  internals), or from an explicit ``render_order`` list (bottom-to-top),
  or falls back to the scene-graph ``z_order`` ascending sort;
- every occlusion edge active in the analysis window whose occluder is
  NOT strictly above its occludee counts as ONE violation;

the raw violation count (unit ``count`` — the SAME quantity T06A2
calibrated as ``measure_z_order_error``, fixture contact_zorder_clipping.
json) is classified against the frozen T03A policy (metric
``z_order_error``, increasing, warning = level-2 raw, blocker = level-4
raw).

Classification is BINARY per policy boundaries via ``thresholds.classify``
(read-only consume; zero hard-coded numbers in this module):

- violations <  warning boundary -> NO item (inside calibrated envelope);
- warning <= violations < blocker -> ONE warning item;
- violations >= blocker          -> ONE blocker item.

Contract (production plan W6 · T03C + acceptance AC3):

- entry point ``detect_z_order_error(args)`` returns a JSON-serializable
  list of QCItem candidates (empty list = pass); runnable by the T03A
  bounded runner in a child process;
- ``register()`` registers the entry point in the shared T03A registry;
- the renderer lock manifest is read ONLY through the public S09 contract
  (``validate_manifest`` from ``app.persistence.structural_lock``) — no
  private lane imports; an invalid manifest fails closed with the S09
  public error;
- evidence: ``schema_version=1``, ``evidence_window_key`` = sha256 over the
  canonical JSON of the content-derived core (reason, layer ref, metric,
  window, order_source) — deterministic and byte-identical across runs;
- thresholds come ONLY from ``app.services.qc_checks.thresholds`` (T03A
  OWNER, frozen).

Input ``args`` schema (JSON-serializable):

``{analysis_window: {start_frame, end_frame},
    segments: [{id, z_order, start_frame, end_frame}],
    occlusion_edges: [{id, occluder_segment_id, occludee_segment_id,
                       start_frame, end_frame, confidence,
                       confidence_source}],
    render_order: [seg_id, ...] | absent,       # bottom-to-top observed
    lock_manifest: {S09 manifest object} | absent}``

Precedence for the observed render order (bottom index 0 -> top):
``lock_manifest.segments`` list order (via public S09 validation) >
``render_order`` > scene-graph ``z_order`` ascending.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.persistence.structural_lock import validate_manifest
from app.services.qc_checks.registry import DetectorSpec, register_detector
from app.services.qc_checks.thresholds import (
    STATUS_BLOCKER,
    classify,
    get_threshold,
)
from app.services.qc_evidence import measure as qcm

DETECTOR_NAME = "z_order_error"
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
        raise ValueError("z_order_error: analysis_window object required")
    start = int(window.get("start_frame", -1))
    end = int(window.get("end_frame", -1))
    if start < 0 or end < start:
        raise ValueError(
            "z_order_error: analysis_window start/end frames invalid "
            f"({start}, {end})"
        )
    return {"start_frame": start, "end_frame": end}


def _observed_order(args: dict[str, Any]) -> tuple[list[str], str]:
    """Resolve the observed bottom-to-top render order.

    ``lock_manifest`` -> public S09 ``validate_manifest`` (fail-closed);
    ``render_order`` -> explicit list; otherwise scene-graph z_order
    ascending (bottom = lowest z_order).
    """
    manifest = args.get("lock_manifest")
    if manifest is not None:
        validated = validate_manifest(manifest)  # PUBLIC S09 contract
        order = [str(s["occurrence_segment_id"]) for s in validated["segments"]]
        return order, "lock_manifest"
    render_order = args.get("render_order")
    if render_order is not None:
        if not isinstance(render_order, list) or not all(
            isinstance(item, str) and item for item in render_order
        ):
            raise ValueError(
                "z_order_error: render_order must be a list of segment ids"
            )
        return list(render_order), "render_order"
    segments = args.get("segments")
    if not isinstance(segments, list):
        raise ValueError("z_order_error: segments list required")
    ordered = sorted(
        (s for s in segments if isinstance(s, dict) and s.get("id")),
        key=lambda s: (int(s.get("z_order", 0)), str(s["id"])),
    )
    return [str(s["id"]) for s in ordered], "z_order"


def _index_of(order: list[str], seg_id: str) -> int | None:
    try:
        return order.index(seg_id)
    except ValueError:
        return None


def _edges_active(
    args: dict[str, Any], window: dict[str, int]
) -> list[dict[str, Any]]:
    edges = args.get("occlusion_edges")
    if not isinstance(edges, list):
        raise ValueError("z_order_error: occlusion_edges list required")
    active: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        start = int(edge.get("start_frame", 0))
        end = int(edge.get("end_frame", window["end_frame"]))
        if end < window["start_frame"] or start > window["end_frame"]:
            continue  # outside the analysis window
        active.append(edge)
    return active


def measure_z_order_violations(args: dict[str, Any]) -> int:
    """Raw measurement: count of occlusion edges active in the window whose
    occluder is NOT strictly above its occludee in the observed order.

    Mirrors T06A2 ``measure_z_order_error`` (count of order-position
    violations) restricted to the occlusion graph of the analysis window.
    """
    window = _window(args)
    order, _ = _observed_order(args)
    violations = 0
    for edge in _edges_active(args, window):
        occluder = str(edge.get("occluder_segment_id", ""))
        occludee = str(edge.get("occludee_segment_id", ""))
        idx_occluder = _index_of(order, occluder)
        idx_occludee = _index_of(order, occludee)
        if idx_occluder is None or idx_occludee is None:
            continue  # edge segment not in the render order -> not counted
        if idx_occluder <= idx_occludee:
            violations += 1  # occluder not strictly above occludee
    return violations


def detect_z_order_error(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the z-order structural check; returns QCItem candidates."""
    window = _window(args)
    order, order_source = _observed_order(args)
    edges = _edges_active(args, window)
    entry = get_threshold(DETECTOR_NAME)  # READ-ONLY (T03A frozen policy)

    violations = 0
    violated_edges: list[dict[str, Any]] = []
    for edge in edges:
        occluder = str(edge.get("occluder_segment_id", ""))
        occludee = str(edge.get("occludee_segment_id", ""))
        idx_occluder = _index_of(order, occluder)
        idx_occludee = _index_of(order, occludee)
        if idx_occluder is None or idx_occludee is None:
            continue
        if idx_occluder <= idx_occludee:
            violations += 1
            violated_edges.append(
                {"occluder_segment_id": occluder, "occludee_segment_id": occludee}
            )
    status, code = classify(DETECTOR_NAME, float(violations))
    if status == STATUS_BLOCKER:
        severity = "blocker"
    elif status == "warning":
        severity = "warning"
    else:
        return []  # inside the calibrated envelope -> NO item (AC2)

    layer_ref_id = (
        violated_edges[0]["occluder_segment_id"] if violated_edges else ""
    )
    confidence = 1.0
    if violated_edges:
        first = next(
            (e for e in edges if str(e.get("occluder_segment_id", "")) == layer_ref_id),
            None,
        )
        if first is not None:
            candidate_conf = float(first.get("confidence", 1.0))
            if 0.0 <= candidate_conf <= 1.0:
                confidence = candidate_conf
    evidence = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "window": window,
        "order_source": order_source,
        "render_order": order,
        "violated_edges": violated_edges,
        "violations_count": violations,
        "threshold": {
            "policy": entry["provenance"]["fixture"],
            "warning_boundary": entry["warning_boundary"],
            "blocker_boundary": entry["blocker_boundary"],
            "code": code,
        },
    }
    metric = {
        "name": DETECTOR_NAME,
        "value": violations,
        "code": code,
    }
    key_core = {
        "reason_code": DETECTOR_NAME,
        "layer_ref_type": "segment",
        "layer_ref_id": layer_ref_id,
        "metric": metric,
        "window": window,
        "order_source": order_source,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
    }
    evidence_window_key = hashlib.sha256(
        _canonical_json(key_core).encode("utf-8")
    ).hexdigest()
    segments = args.get("segments")
    logical_by_id: dict[str, Any] = {}
    if isinstance(segments, list):
        for seg in segments:
            if isinstance(seg, dict) and seg.get("id"):
                logical_by_id[str(seg["id"])] = seg.get("logical_id")
    return [
        {
            "reason_code": DETECTOR_NAME,
            "category": DETECTOR_NAME,
            "severity": severity,
            "status": "open",
            "layer_ref_type": "segment",
            "layer_ref_id": layer_ref_id,
            "segment_row_id": None,
            "segment_logical_id": logical_by_id.get(layer_ref_id),
            "evidence_window_key": evidence_window_key,
            "evidence": evidence,
            "detector": DETECTOR_NAME,
            "detector_revision": DETECTOR_REVISION,
            "confidence": confidence,
            "confidence_source": "derived",
            "checkpoint_ref": f"s11-t03c:{DETECTOR_NAME}",
            "metric": metric,
        }
    ]


def register(*, version: str = DETECTOR_REVISION) -> DetectorSpec:
    """Register this detector in the shared T03A registry (idempotent)."""
    return register_detector(
        DETECTOR_NAME,
        "app.services.qc_checks.z_order_error:detect_z_order_error",
        version=version,
        description=(
            "z_order_error: observed render order vs occlusion graph; each "
            "violated edge (occluder not strictly above occludee) counts "
            "one, classified against the frozen T03A policy (count); order "
            "read via public S09 lock-manifest contract"
        ),
    )


# ── MF-END-22.1/22.2/22.3: SOURCE occlusion facts vs OUTPUT observations ─────
#
# The source facts (MF-END-13) declare ``occluder in_front_of occludee`` for a
# frame interval, measured with two cues on the SOURCE pixels:
# ``occlusion_run`` (the occludee has no usable mask while another track's box
# covers its reference extent, containment >= 0.55) and ``visible_containment``
# (a visible object inside an occupied silhouette).  This comparator re-measures
# the SAME cues on the OUTPUT observations (MF-END-21):
#
# - PRESERVED: the declared occludee is the hidden one and the declared
#   occluder's box covers the occludee's reference extent (>= 0.55), or — for
#   the visible-containment cue — the occluder is visible and sits inside the
#   occludee's box (containment >= 0.55, the source side's own formula);
# - REVERSED (hard): the declared OCCLUDER is the hidden one in the output and
#   the declared OCCLUDEE's box covers the occluder's reference extent — the
#   pair renders in the opposite order (the value is classified against the
#   frozen ``occlusion_reversal_containment`` policy: warning = level-2
#   measured raw, blocker = level-4 measured raw);
# - nothing measurable -> a typed UNKNOWN, never a pass.

COMPARISON_DETECTOR_NAME = "z_order_error_comparison"

#: A cue needs at least this share of the fact's frames to be measured at all.
COMPARISON_MIN_CUE_FRAMES = 1


def _round9(value: float) -> float:
    return round(float(value), 9)


def _hidden_frames(role_rows: dict[str, Any], frames: list[int]) -> list[int]:
    """Frames of the FACT window the role pays no usable mask for."""
    hidden = (
        set(role_rows["occluded_frames"])
        | set(role_rows["gap_frames"])
        | set(role_rows["out_of_frame_frames"])
    )
    return sorted(hidden & set(frames))


def _reference_extent(
    ctx: dict[str, Any],
    role_id: str,
    frames: list[int],
    output: dict[str, Any],
) -> tuple[tuple[float, float, float, float] | None, str]:
    """The instance's measured reference extent, SOURCE side first.

    The MF-END-13 producer bounds an occlusion run against the instance's
    seed box (or its last visible box).  The comparator prefers the same
    source-side measurement when the sealed MF-END-12 tracks are supplied and
    falls back to the output's own nearest measured box — the basis is always
    recorded, never assumed.
    """
    source_track = qcm.track_by_role(ctx.get("source_tracks") or {}, role_id)
    if source_track is not None:
        seed_box = (source_track.get("seed") or {}).get("box")
        if isinstance(seed_box, (list, tuple)) and len(seed_box) == 4:
            x, y, w, h = (float(v) for v in seed_box)
            if w > 0 and h > 0:
                return (x, y, w, h), "source_seed_box"
        rows = qcm.granted_rows(source_track)
        box = qcm.reference_box(rows, frames)
        if box is not None:
            return box, "source_track_box"
    rows = output.get("rows") or {}
    ordered = sorted(rows, key=lambda frame: (abs(int(frame) - frames[0]), int(frame)))
    box = qcm.reference_box(rows, ordered)
    if box is not None:
        return box, "output_nearest_box"
    return None, "unmeasured"


def compare_occlusion_facts(args: dict[str, Any]) -> dict[str, Any]:
    """Compare the source occlusion facts with the output observations.

    ``args`` is the shared comparator schema (see
    :func:`app.services.qc_evidence.measure.comparison_context`).
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

    for fact in ctx["facts"].get("occlusions") or []:
        if not isinstance(fact, dict):
            continue
        occluder_role = str(fact.get("occluder_role_id") or "")
        occludee_role = str(fact.get("occludee_role_id") or "")
        order = str(fact.get("order") or "in_front_of")
        start = int(fact.get("start_frame", 0))
        end = int(fact.get("end_frame", start))
        frames = list(range(start, end))
        core = {
            "occluder_role_id": occluder_role,
            "occludee_role_id": occludee_role,
            "order": order,
            "span": [start, end],
            "cue": str((fact.get("measured") or {}).get("cue") or ""),
        }
        occluder = qcm.output_rows(ctx, occluder_role)
        occludee = qcm.output_rows(ctx, occludee_role)
        if occluder is None or occludee is None:
            absent = occluder_role if occluder is None else occludee_role
            refusal = qcm.refused_role(ctx["observations"], absent)
            blocked.append(
                {
                    "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                    "role_id": absent,
                    "frames": [start, end - 1],
                    "fact": core,
                    "detail": (
                        f"the output carries no usable observation track for role "
                        f"{absent!r}; the declared occlusion cannot be compared"
                    ),
                    "output_refusal": refusal,
                }
            )
            checked.append({**core, "status": qcm.VERDICT_BLOCKED})
            continue


        occludee_hidden = _hidden_frames(occludee, frames)
        occluder_hidden = _hidden_frames(occluder, frames)
        both_visible = [
            frame
            for frame in frames
            if frame not in occludee_hidden
            and frame not in occluder_hidden
            and qcm.bbox_of(occludee["rows"].get(frame) or {}) is not None
            and qcm.bbox_of(occluder["rows"].get(frame) or {}) is not None
        ]
        record: dict[str, Any] = {
            **core,
            "occludee_hidden_frames": occludee_hidden,
            "occluder_hidden_frames": occluder_hidden,
            "both_visible_frames": both_visible,
        }

        occludee_ref, occludee_basis = _reference_extent(
            ctx, occludee_role, frames, occludee
        )
        occluder_ref, occluder_basis = _reference_extent(
            ctx, occluder_role, frames, occluder
        )
        frame_total = max(1, len(frames))
        hidden_occluder_share = len(occluder_hidden) / float(frame_total)
        hidden_occludee_share = len(occludee_hidden) / float(frame_total)
        visible_share = len(both_visible) / float(frame_total)

        forward_ratio: float | None = None
        forward_frames: list[int] = []
        if occludee_ref is not None and occludee_hidden:
            reference_rows = {
                frame: {"bbox": list(occludee_ref)} for frame in occludee_hidden
            }
            forward_ratio = qcm.measure_containment_mean(
                occluder["rows"], reference_rows, occludee_hidden
            )
            if forward_ratio is not None:
                forward_frames = occludee_hidden

        cue_visible: float | None = None
        if both_visible:
            cue_visible = qcm.measure_containment_mean(
                occludee["rows"], occluder["rows"], both_visible
            )

        reversal_ratio: float | None = None
        reversal_frames: list[int] = []
        if occluder_ref is not None and occluder_hidden:
            reference_rows = {
                frame: {"bbox": list(occluder_ref)} for frame in occluder_hidden
            }
            reversal_ratio = qcm.measure_containment_mean(
                occludee["rows"], reference_rows, occluder_hidden
            )
            if reversal_ratio is not None:
                reversal_frames = occluder_hidden

        evidence = {
            "fact": core,
            "thresholds": {
                "occlusion_min_containment": qcm.COMPARISON_OCCLUSION_MIN_CONTAINMENT,
                "policy": qcm.comparison_threshold(qcm.METRIC_OCCLUSION_REVERSAL),
            },
            "reference_extents": {
                "occludee": {
                    "box": list(occludee_ref) if occludee_ref else None,
                    "basis": occludee_basis,
                },
                "occluder": {
                    "box": list(occluder_ref) if occluder_ref else None,
                    "basis": occluder_basis,
                },
            },
            "measured": {
                "forward_containment": (
                    _round9(forward_ratio) if forward_ratio is not None else None
                ),
                "forward_frames": forward_frames,
                "visible_containment": (
                    _round9(cue_visible) if cue_visible is not None else None
                ),
                "reversal_containment": (
                    _round9(reversal_ratio) if reversal_ratio is not None else None
                ),
                "reversal_frames": reversal_frames,
                "hidden_occluder_share": _round9(hidden_occluder_share),
                "hidden_occludee_share": _round9(hidden_occludee_share),
                "visible_share": _round9(visible_share),
            },
            "mapping": ctx.get("mapping"),
            "measure": (
                "the declared occluder/occludee roles are re-measured on the "
                "OUTPUT observations: which side is hidden over the window and "
                "how much of the hidden instance's reference extent the visible "
                "one covers (containment, the source side's own definition)"
            ),
        }

        # WHO is hidden over the fact's window decides the relation: the
        # declared occluder being the hidden side is the REVERSAL (classified
        # against the frozen reversal policy); the declared occludee being the
        # hidden side (covered by the occluder) is the preserved order, and so
        # is the visible-containment cue (the source side's own formula).
        reversal_applies = hidden_occluder_share >= 0.5 and reversal_ratio is not None
        preserved = (
            (
                hidden_occludee_share >= 0.5
                and forward_ratio is not None
                and forward_ratio >= qcm.COMPARISON_OCCLUSION_MIN_CONTAINMENT
            )
            or (
                visible_share >= 0.5
                and cue_visible is not None
                and cue_visible >= qcm.COMPARISON_OCCLUSION_MIN_CONTAINMENT
            )
            or (
                forward_ratio is not None
                and forward_ratio >= qcm.COMPARISON_OCCLUSION_MIN_CONTAINMENT
            )
        )
        if not reversal_applies and preserved:
            checked.append(
                {
                    **record,
                    "status": qcm.VERDICT_PASS,
                    "preserved_by": (
                        "hidden_occludee_covered_by_occluder"
                        if hidden_occludee_share >= 0.5
                        else "visible_occluder_inside_occludee"
                    ),
                }
            )
            continue
        measured_reversal = (
            reversal_ratio
            if reversal_applies or reversal_ratio is not None
            else None
        )
        if measured_reversal is None:
            uncertain.append(
                {
                    "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                    "role_id": occludee_role,
                    "frames": [start, end - 1],
                    "fact": core,
                    "detail": (
                        "neither cue of the declared occlusion is measurable on "
                        "the output (no hidden side with a measured reference "
                        "extent, no visible containment); nothing is guessed"
                    ),
                }
            )
            checked.append({**record, "status": qcm.VERDICT_UNKNOWN})
            continue
        status, code = qcm.classify_comparison(
            qcm.METRIC_OCCLUSION_REVERSAL, measured_reversal
        )
        if status == "invalid":
            uncertain.append(
                {
                    "code": qcm.CODE_COMPARISON_INVALID,
                    "role_id": occludee_role,
                    "frames": reversal_frames,
                    "fact": core,
                    "detail": (
                        f"measured reversal containment {measured_reversal!r} is "
                        "outside the frozen calibrated envelope — pipeline fault"
                    ),
                }
            )
            checked.append({**record, "status": qcm.VERDICT_UNKNOWN})
            continue
        if status == "blocker":
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_OCCLUSION_REVERSAL,
                    code=qcm.CODE_OCCLUSION_REVERSED,
                    level=qcm.LEVEL_HARD,
                    severity="blocker",
                    role_id=occludee_role,
                    frames=reversal_frames,
                    detail=(
                        f"the declared order {occluder_role!r} in_front_of "
                        f"{occludee_role!r} is REVERSED in the output: "
                        f"{occluder_role!r} is the hidden one and "
                        f"{occludee_role!r} covers {measured_reversal} of its "
                        "reference extent"
                    ),
                    evidence=evidence,
                )
            )
            checked.append({**record, "status": qcm.VERDICT_FAIL})
            continue
        items.append(
            qcm.comparison_item(
                metric=qcm.METRIC_OCCLUSION_REVERSAL,
                code=qcm.CODE_OCCLUSION_WEAKENED,
                level=qcm.LEVEL_SOFT,
                severity="warning",
                role_id=occludee_role,
                frames=reversal_frames,
                detail=(
                    f"the declared order {occluder_role!r} in_front_of "
                    f"{occludee_role!r} is only partially honoured "
                    f"(reversal containment {measured_reversal} inside the "
                    "warning band)"
                ),
                evidence=evidence,
            )
        )
        checked.append({**record, "status": qcm.VERDICT_WARN})

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

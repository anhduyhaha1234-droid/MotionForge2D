"""S11-T03C contact_break detector (W6).

Structural detector over scene-graph/mask data: a ContactRecord edge
(source -> target) that EXPIRED inside the analysis window while the two
segments' render windows still overlap AFTER the contact end is a contact
break candidate.  The measured metric is the minimum vertical gap (px)
between the two segments' mask bboxes over the post-expiry overlap frames
— the SAME raw quantity T06A2 calibrated (``measure_contact_break``:
``np.min(gap_px_per_frame)``, fixture contact_zorder_clipping.json) —
classified against the frozen T03A policy (metric ``contact_break``,
increasing, warning = level-2 raw, blocker = level-4 raw).

Classification is BINARY per policy boundaries via ``thresholds.classify``
(read-only consume; zero hard-coded numbers in this module):

- measured gap <  warning boundary -> NO item (inside calibrated envelope);
- warning <= gap < blocker           -> ONE warning item;
- gap >= blocker                     -> ONE blocker item.

Contract (production plan W6 · T03C):

- entry point ``detect_contact_break(args)`` returns a JSON-serializable
  list of QCItem candidates (empty list = pass); the T03A bounded runner
  executes it in a child process, so the output must stay plain dicts;
- ``register()`` registers the entry point in the shared T03A singleton
  registry (idempotent identity);
- evidence: ``schema_version=1``, ``evidence_window_key`` = sha256 over the
  canonical JSON of the content-derived core (reason, layer ref, metric,
  window, contact facts) — deterministic, byte-identical across repeated
  runs (in-process AND across child processes);
- thresholds come ONLY from ``app.services.qc_checks.thresholds`` (T03A
  OWNER, frozen) — never re-derived or copied here.

Input ``args`` schema (JSON-serializable; frame range is inclusive):

``{analysis_window: {start_frame, end_frame},
    contacts: [{id, source_segment_id, target_segment_id, contact_kind,
                start_frame, end_frame, confidence, confidence_source}],
    segments: [{id, logical_id, z_order, start_frame, end_frame,
                mask_artifact_id, bbox_per_frame: [[x0,y0,x1,y1], ...]}]}``

``bbox_per_frame`` is aligned to the analysis window (index 0 = window's
``start_frame``).  A frame contributes a gap only while BOTH segments are
inside their own render windows AND their bboxes x-ranges overlap (the
vertical contact geometry exists).  A contact whose end_frame == analysis
end_frame is NOT expired (still inside the window) -> no candidate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services import source_interaction_facts as sif
from app.services.qc_checks.registry import DetectorSpec, register_detector
from app.services.qc_checks.thresholds import (
    STATUS_BLOCKER,
    classify,
    get_threshold,
)
from app.services.qc_evidence import measure as qcm

DETECTOR_NAME = "contact_break"
DETECTOR_REVISION = "1.0.0"

#: Evidence contract version (AC4 — schema_version=1, content-derived).
EVIDENCE_SCHEMA_VERSION = 1

#: Canonical serialization used for the content-derived evidence key
#: (same conventions as qc_items.canonical_evidence_json).
def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _window(args: dict[str, Any]) -> dict[str, int]:
    window = args.get("analysis_window")
    if not isinstance(window, dict):
        raise ValueError("contact_break: analysis_window object required")
    start = int(window.get("start_frame", -1))
    end = int(window.get("end_frame", -1))
    if start < 0 or end < start:
        raise ValueError(
            "contact_break: analysis_window start/end frames invalid "
            f"({start}, {end})"
        )
    return {"start_frame": start, "end_frame": end}


def _segments_by_id(args: dict[str, Any]) -> dict[str, dict[str, Any]]:
    segments = args.get("segments")
    if not isinstance(segments, list):
        raise ValueError("contact_break: segments list required")
    by_id: dict[str, dict[str, Any]] = {}
    for seg in segments:
        if not isinstance(seg, dict) or not seg.get("id"):
            raise ValueError("contact_break: every segment needs an id")
        by_id[str(seg["id"])] = seg
    return by_id


def _vertical_gap(a: list[float], b: list[float]) -> float | None:
    """Vertical gap (px) between two bboxes when x-ranges overlap.

    Returns None when there is no horizontal contact geometry (x-ranges
    disjoint) — that frame carries no gap measurement.
    """
    a_x0, a_y0, a_x1, a_y1 = (float(v) for v in a)
    b_x0, b_y0, b_x1, b_y1 = (float(v) for v in b)
    if min(a_x1, b_x1) <= max(a_x0, b_x0):
        return None
    return max(0.0, max(a_y0, b_y0) - min(a_y1, b_y1))


def _bbox_at(seg: dict[str, Any], frame: int, window: dict[str, int]) -> list[float] | None:
    """Window-aligned bbox lookup; None when the segment does not render at
    ``frame`` or carries no per-frame bbox data."""
    if frame < int(seg.get("start_frame", 0)) or frame > int(
        seg.get("end_frame", window["end_frame"])
    ):
        return None
    frames = seg.get("bbox_per_frame")
    if not isinstance(frames, list):
        return None
    index = frame - window["start_frame"]
    if index < 0 or index >= len(frames):
        return None
    bbox = frames[index]
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    return [float(v) for v in bbox]


def measure_contact_gap(args: dict[str, Any]) -> float | None:
    """Raw measurement: min vertical gap (px) over the post-expiry overlap
    frames of the FIRST expired contact with continuing render overlap.

    Mirrors T06A2 ``measure_contact_break`` semantics (min of the per-frame
    gap array) restricted to the after-expiry overlap window.  Returns None
    when no contact qualifies.
    """
    window = _window(args)
    segments = _segments_by_id(args)
    contacts = args.get("contacts")
    if not isinstance(contacts, list):
        raise ValueError("contact_break: contacts list required")

    best_gap: float | None = None
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        exp_end = int(contact.get("end_frame", -1))
        if exp_end >= window["end_frame"]:
            continue  # not expired inside this analysis window
        source = str(contact.get("source_segment_id", ""))
        target = str(contact.get("target_segment_id", ""))
        seg_a = segments.get(source)
        seg_b = segments.get(target)
        if seg_a is None or seg_b is None:
            continue
        gaps: list[float] = []
        for frame in range(exp_end + 1, window["end_frame"] + 1):
            bbox_a = _bbox_at(seg_a, frame, window)
            bbox_b = _bbox_at(seg_b, frame, window)
            if bbox_a is None or bbox_b is None:
                continue
            gap = _vertical_gap(bbox_a, bbox_b)
            if gap is not None:
                gaps.append(gap)
        if not gaps:
            continue  # no render overlap after expiry
        current = min(gaps)
        if best_gap is None or current < best_gap:
            best_gap = current
    return best_gap


def detect_contact_break(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the contact_break structural check; returns QCItem candidates."""
    window = _window(args)
    segments = _segments_by_id(args)
    contacts = args.get("contacts")
    if not isinstance(contacts, list):
        raise ValueError("contact_break: contacts list required")
    entry = get_threshold(DETECTOR_NAME)  # READ-ONLY (T03A frozen policy)

    items: list[dict[str, Any]] = []
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        exp_end = int(contact.get("end_frame", -1))
        if exp_end >= window["end_frame"]:
            continue  # contact still active inside the window -> pass
        source = str(contact.get("source_segment_id", ""))
        target = str(contact.get("target_segment_id", ""))
        contact_kind = str(contact.get("contact_kind", ""))
        seg_a = segments.get(source)
        seg_b = segments.get(target)
        if seg_a is None or seg_b is None:
            continue
        gaps: list[float] = []
        overlap_bounds: list[int] = []
        for frame in range(exp_end + 1, window["end_frame"] + 1):
            bbox_a = _bbox_at(seg_a, frame, window)
            bbox_b = _bbox_at(seg_b, frame, window)
            if bbox_a is None or bbox_b is None:
                continue
            gap = _vertical_gap(bbox_a, bbox_b)
            if gap is not None:
                gaps.append(gap)
                if not overlap_bounds:
                    overlap_bounds.append(frame)
                overlap_bounds.append(frame)
        if not gaps:
            continue  # no continuing render overlap -> pass
        measured = min(gaps)
        status, code = classify(DETECTOR_NAME, measured)
        if status == STATUS_BLOCKER:
            severity = "blocker"
        elif status == "warning":
            severity = "warning"
        else:
            continue  # inside the calibrated envelope -> NO item (AC2)
        layer_ref_id = source
        confidence = float(contact.get("confidence", 1.0))
        if not 0.0 <= confidence <= 1.0:
            confidence = 1.0
        evidence = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "window": window,
            "contact": {
                "source_segment_id": source,
                "target_segment_id": target,
                "contact_kind": contact_kind,
            },
            "overlap_after_expiry_frames": [overlap_bounds[0], overlap_bounds[-1]],
            "measured_gap_px": measured,
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
            "layer_ref_id": layer_ref_id,
            "metric": metric,
            "window": window,
            "contact": evidence["contact"],
            "schema_version": EVIDENCE_SCHEMA_VERSION,
        }
        evidence_window_key = hashlib.sha256(
            _canonical_json(key_core).encode("utf-8")
        ).hexdigest()
        items.append(
            {
                "reason_code": DETECTOR_NAME,
                "category": DETECTOR_NAME,
                "severity": severity,
                "status": "open",
                "layer_ref_type": "segment",
                "layer_ref_id": layer_ref_id,
                "segment_row_id": None,
                "segment_logical_id": seg_a.get("logical_id"),
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
        "app.services.qc_checks.contact_break:detect_contact_break",
        version=version,
        description=(
            "contact_break: expired ContactRecord while segments still "
            "render-overlap after expiry; min vertical gap classified "
            "against the frozen T03A policy (px)"
        ),
    )


# ── MF-END-22.1/22.3/22.4: SOURCE contact facts vs OUTPUT observations ───────
#
# The comparison consumes the SEALED source facts (MF-END-13) and the SEALED
# output observations (MF-END-21); it never re-derives either side and refuses
# (typed UNKNOWN/BLOCKED) when a side is missing or ambiguous.  A source
# contact (person <-> prop interval, measured on the SOURCE pixels) must be
# reproduced by the OUTPUT observations with the source side's own
# definitions: bbox edge gap <= 8 px and (grasp) containment >= 0.55.
#
# Defect taxonomy (hard dominates — the appearance of the output can never
# compensate it):
# - ``QC_COMPARISON_CONTACT_OWNER_CHANGED`` (hard): the declared contact is
#   broken in the output AND another role now holds the object (the BOOK
#   changed owner);
# - ``QC_COMPARISON_CONTACT_LOST`` (hard): the declared contact is broken and
#   no other role holds the object;
# - ``QC_COMPARISON_CONTACT_WEAKENED`` (soft): the contact attenuated into the
#   frozen warning band, or a grasp that is no longer contained.

COMPARISON_DETECTOR_NAME = "contact_break_comparison"


def _round9(value: float) -> float:
    return round(float(value), 9)


def _owner_shift(
    ctx: dict[str, Any],
    *,
    subject_role: str,
    object_role: str,
    object_rows: dict[int, Any],
    frames: list[int],
    declared_gap: float,
) -> dict[str, Any] | None:
    """The closest OTHER output role to the object, when it beats the subject."""
    best: dict[str, Any] | None = None
    for track in ctx["observations"].get("tracks") or []:
        role_id = str(track.get("role_id") or "")
        if not role_id or role_id in (subject_role, object_role):
            continue
        other = qcm.output_rows(ctx, role_id)
        if other is None:
            continue
        other_gap = qcm.measure_contact_gap_px(other["rows"], object_rows, frames)
        if other_gap is None:
            continue
        candidate = {
            "role_id": role_id,
            "gap_px": _round9(other_gap),
            "beats_declared": bool(
                other_gap < declared_gap
                and other_gap <= qcm.COMPARISON_CONTACT_MAX_GAP_PX
            ),
        }
        if best is None or candidate["gap_px"] < best["gap_px"]:
            best = candidate
    if best is None or not best["beats_declared"]:
        return best
    return best


def compare_contact_facts(args: dict[str, Any]) -> dict[str, Any]:
    """Compare the source contact facts with the output observations.

    ``args`` (JSON-safe):

    ``{source_facts: <MF-END-13 sealed payload>,
       output_observations: <MF-END-21 sealed payload>,
       source_tracks: <MF-END-12 sealed payload> | absent,
       frame_map: {source_to_output: {...}} | absent,
       appearance: {...} | absent}``

    Returns the shared comparison envelope (verdict + typed items).
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

    for fact in ctx["facts"].get("contacts") or []:
        if not isinstance(fact, dict):
            continue
        subject_role = str(fact.get("subject_role_id") or "")
        object_role = str(fact.get("object_role_id") or "")
        kind = str(fact.get("kind") or "")
        start = int(fact.get("start_frame", 0))
        end = int(fact.get("end_frame", start))
        frames = list(range(start, end))
        core = {
            "subject_role_id": subject_role,
            "object_role_id": object_role,
            "kind": kind,
            "span": [start, end],
        }
        subject = qcm.output_rows(ctx, subject_role)
        obj = qcm.output_rows(ctx, object_role)
        if subject is None or obj is None:
            absent = subject_role if subject is None else object_role
            refusal = qcm.refused_role(ctx["observations"], absent)
            blocked.append(
                {
                    "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                    "role_id": absent,
                    "frames": [start, end - 1],
                    "fact": core,
                    "detail": (
                        "the output carries no usable observation track for role "
                        f"{absent!r}; the declared contact cannot be compared"
                    ),
                    "output_refusal": refusal,
                }
            )
            checked.append({**core, "status": qcm.VERDICT_BLOCKED})
            continue
        measured = [
            frame
            for frame in frames
            if qcm.bbox_of(subject["rows"].get(frame) or {}) is not None
            and qcm.bbox_of(obj["rows"].get(frame) or {}) is not None
        ]
        record: dict[str, Any] = {
            **core,
            "measured_frames": measured,
            "missing": {
                "subject": sorted(set(subject["missing"]["gap_frames"]) & set(frames)),
                "object": sorted(set(obj["missing"]["gap_frames"]) & set(frames)),
                "object_occluded": sorted(set(obj["occluded_frames"]) & set(frames)),
            },
        }
        if not measured:
            uncertain.append(
                {
                    "code": qcm.CODE_COMPARISON_NOT_OBSERVED,
                    "role_id": subject_role,
                    "frames": [start, end - 1],
                    "fact": core,
                    "detail": (
                        "no frame of the declared contact window carries measured "
                        "boxes on BOTH instances in the output; nothing is guessed"
                    ),
                }
            )
            checked.append({**record, "status": qcm.VERDICT_UNKNOWN})
            continue

        gap = qcm.measure_contact_gap_px(subject["rows"], obj["rows"], measured)
        # containment(subject_box, object_box) — the source side's own
        # direction (fraction of the OBJECT's box covered by the subject).
        containment = qcm.measure_containment_mean(
            subject["rows"], obj["rows"], measured
        )
        assert gap is not None  # measured frames guarantee a value
        status, code = qcm.classify_comparison(qcm.METRIC_CONTACT_GAP, gap)
        evidence = {
            "fact": core,
            "measured_frames": measured,
            "measured_min_gap_px": _round9(gap),
            "measured_mean_containment": (
                _round9(containment) if containment is not None else None
            ),
            "missing": record["missing"],
            "thresholds": {
                "contact_max_gap_px": qcm.COMPARISON_CONTACT_MAX_GAP_PX,
                "contact_min_containment": qcm.COMPARISON_CONTACT_MIN_CONTAINMENT,
                "policy": qcm.comparison_threshold(qcm.METRIC_CONTACT_GAP),
            },
            "mapping": ctx.get("mapping"),
            "measure": (
                "edge-to-edge bbox gap between the two instances' OUTPUT "
                "observations over the declared source frames; a grasp also "
                "requires the object's box to sit inside the subject's box"
            ),
        }
        if status == "invalid":
            uncertain.append(
                {
                    "code": qcm.CODE_COMPARISON_INVALID,
                    "role_id": subject_role,
                    "frames": measured,
                    "fact": core,
                    "detail": (
                        f"measured contact gap {gap!r} px is outside the frozen "
                        "calibrated envelope — a pipeline fault, not a QC claim"
                    ),
                }
            )
            checked.append({**record, "status": qcm.VERDICT_UNKNOWN})
            continue
        if status == "blocker":
            owner = _owner_shift(
                ctx,
                subject_role=subject_role,
                object_role=object_role,
                object_rows=obj["rows"],
                frames=measured,
                declared_gap=gap,
            )
            if owner is not None and owner.get("beats_declared"):
                items.append(
                    qcm.comparison_item(
                        metric=qcm.METRIC_CONTACT_GAP,
                        code=qcm.CODE_CONTACT_OWNER_CHANGED,
                        level=qcm.LEVEL_HARD,
                        severity="blocker",
                        role_id=subject_role,
                        frames=measured,
                        detail=(
                            f"the declared contact {subject_role!r}<->{object_role!r} "
                            f"is broken in the output (min gap {_round9(gap)} px) and "
                            f"{owner['role_id']!r} is now the closest role to the "
                            f"object (gap {owner['gap_px']} px): the object changed "
                            "owner"
                        ),
                        evidence={**evidence, "owner_candidate": owner},
                    )
                )
                checked.append({**record, "status": qcm.VERDICT_FAIL})
                continue
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_CONTACT_GAP,
                    code=qcm.CODE_CONTACT_LOST,
                    level=qcm.LEVEL_HARD,
                    severity="blocker",
                    role_id=subject_role,
                    frames=measured,
                    detail=(
                        f"the declared contact {subject_role!r}<->{object_role!r} is "
                        f"not reproduced by the output (min measured gap "
                        f"{_round9(gap)} px >= blocker boundary); no other role "
                        "holds the object"
                    ),
                    evidence={**evidence, "owner_candidate": owner},
                )
            )
            checked.append({**record, "status": qcm.VERDICT_FAIL})
            continue
        if status == "warning":
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_CONTACT_GAP,
                    code=qcm.CODE_CONTACT_WEAKENED,
                    level=qcm.LEVEL_SOFT,
                    severity="warning",
                    role_id=subject_role,
                    frames=measured,
                    detail=(
                        f"the declared contact {subject_role!r}<->{object_role!r} "
                        f"attenuated in the output (min measured gap "
                        f"{_round9(gap)} px inside the warning band)"
                    ),
                    evidence=evidence,
                )
            )
            checked.append({**record, "status": qcm.VERDICT_WARN})
            continue
        if (
            kind == sif.CONTACT_KIND_GRASP
            and containment is not None
            and containment < qcm.COMPARISON_CONTACT_MIN_CONTAINMENT
        ):
            items.append(
                qcm.comparison_item(
                    metric=qcm.METRIC_CONTACT_GAP,
                    code=qcm.CODE_CONTACT_WEAKENED,
                    level=qcm.LEVEL_SOFT,
                    severity="warning",
                    role_id=subject_role,
                    frames=measured,
                    detail=(
                        "the declared GRASP is no longer contained in the output "
                        f"(mean containment {_round9(containment)} < "
                        f"{qcm.COMPARISON_CONTACT_MIN_CONTAINMENT}) — the contact "
                        "shape changed"
                    ),
                    evidence=evidence,
                )
            )
            checked.append({**record, "status": qcm.VERDICT_WARN})
            continue
        checked.append({**record, "status": qcm.VERDICT_PASS})

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

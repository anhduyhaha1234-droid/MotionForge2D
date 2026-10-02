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
"""S11-T03C detectors self-test — contact_break + z_order_error + silhouette_clipping (W6).

Tests the three structural detectors owned by this task:

- ``app/services/qc_checks/contact_break.py`` — contact edge EXPIRED between two
  segments while their render windows still overlap after the contact end:
  the minimum vertical gap over the post-expiry overlap frames is measured and
  classified against the frozen T03A policy (metric ``contact_break``, px);
- ``app/services/qc_checks/z_order_error.py`` — observed render order
  (renderer route/lock manifest via the PUBLIC S09 contract
  ``structural_lock.validate_manifest``, or explicit ``render_order``, or
  scene-graph z_order fallback) is checked against the occlusion graph:
  every edge where the occluder is NOT strictly above the occludee counts
  as ONE error; the count is classified against ``z_order_error`` (count);
- ``app/services/qc_checks/silhouette_clipping.py`` — mask bbox clipped
  outside the render frame boundary; clipped-pixel ratio (T06A2 raw formula)
  classified against ``silhouette_clipping`` (ratio).

Contract rules under test (production plan W6 · T03C, authority
S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA 34247926...):

1. all three reason codes owned: contact_break, z_order_error,
   silhouette_clipping (Decision B partition);
2. binary pass/fail per policy boundaries — NO item while the measured
   value stays inside the calibrated envelope (warning/blocker read from
   ``get_threshold`` at runtime, never hard-coded: the severity expectations
   of every boundary test are recomputed from the policy itself);
3. renderer route/lock manifest consumed via the public S09 contract only
   (``structural_lock.validate_manifest``) — no private lane imports;
4. evidence ``schema_version=1``, content-derived ``evidence_window_key``
   (sha256 over canonical evidence content), byte-identical idempotent ×2
   (in-process AND across the bounded runner child process);
5. fixtures consume T06A1 builders + T06A2 calibration read-only — the
   threshold-provenance test re-reads the frozen calibration JSON and
   asserts detector boundaries equal the policy boundaries derived from it.

Isolation (lane-B §4 / RESOURCE_PLAN §3): run with a SHORT Windows-native
``--basetemp``, ``-p no:cacheprovider``, ``env -u MOTIONFORGE_DATABASE_URL``.
No DB, no media, no network — pure structural scene-graph/mask dicts.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.persistence.structural_lock import (
    StructuralLockParamsError,
    validate_manifest,
)
from app.services.qc_checks import (
    QC_RUNNER_OK,
    DetectorRun,
    get_threshold,
    registry,
    run_detector,
)
from app.services.qc_checks.contact_break import (
    DETECTOR_NAME as CB_NAME,
    detect_contact_break,
    measure_contact_gap,
    register as register_contact_break,
)
from app.services.qc_checks.silhouette_clipping import (
    DETECTOR_NAME as SC_NAME,
    detect_silhouette_clipping,
    measure_clipping_ratio,
    register as register_silhouette_clipping,
)
from app.services.qc_checks.z_order_error import (
    DETECTOR_NAME as ZO_NAME,
    detect_z_order_error,
    measure_z_order_violations,
    register as register_z_order_error,
)

# ── helpers: deterministic structural scene-graph fixtures ──────────────────

WINDOW = {"start_frame": 0, "end_frame": 47}


def _segment(
    seg_id: str,
    *,
    z_order: int,
    start_frame: int = 0,
    end_frame: int = 47,
    bbox_per_frame: list[list[float]] | None = None,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "id": seg_id,
        "logical_id": f"L-{seg_id}",
        "z_order": z_order,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "mask_artifact_id": f"mask-{seg_id}",
        "bbox_per_frame": bbox_per_frame,
        "bbox": bbox,
    }


def _contact(
    source: str,
    target: str,
    *,
    start_frame: int,
    end_frame: int,
    contact_kind: str = "touch",
    confidence: float = 0.98,
) -> dict[str, Any]:
    return {
        "id": f"contact-{source}-{target}",
        "source_segment_id": source,
        "target_segment_id": target,
        "contact_kind": contact_kind,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "confidence": confidence,
        "confidence_source": "derived",
    }


def _contact_args(
    contacts: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    *,
    window: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {"contacts": contacts, "segments": segments, "analysis_window": window or WINDOW}


def _occlusion(
    occluder: str,
    occludee: str,
    *,
    start_frame: int = 0,
    end_frame: int = 47,
) -> dict[str, Any]:
    return {
        "id": f"occ-{occluder}-{occludee}",
        "occluder_segment_id": occluder,
        "occludee_segment_id": occludee,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "confidence": 0.99,
        "confidence_source": "derived",
    }


def _zorder_args(
    segments: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    window: dict[str, int] | None = None,
    render_order: list[str] | None = None,
    lock_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "segments": segments,
        "occlusion_edges": edges,
        "analysis_window": window or WINDOW,
        "render_order": render_order,
        "lock_manifest": lock_manifest,
    }


def _chain_segments(count: int) -> list[dict[str, Any]]:
    """s0..sN-1; each s_i occludes s_{i+1} (occluder has higher z_order)."""
    segs = []
    for i in range(count):
        segs.append(_segment(f"s{i}", z_order=count - i))
    return segs


def _chain_edges(count: int) -> list[dict[str, Any]]:
    return [_occlusion(f"s{i}", f"s{i + 1}") for i in range(count - 1)]


def _clipping_args(
    segments: list[dict[str, Any]],
    *,
    frame_w: float = 100.0,
    frame_h: float = 100.0,
    window: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "segments": segments,
        "frame": {"width": frame_w, "height": frame_h},
        "analysis_window": window or WINDOW,
    }


def _clip_bbox(clip_px: float) -> list[float]:
    """bbox shifted right by clip_px — same geometry as the T06A2 raw builder."""
    return [20.0 + clip_px, 30.0, 80.0 + clip_px, 70.0]


def _canonical_json(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _assert_item_shape(item: dict[str, Any], reason_code: str) -> None:
    """Every emitted item must satisfy the QCItem candidate contract."""
    assert item["reason_code"] == reason_code
    assert item["category"] == reason_code
    assert item["severity"] in ("blocker", "warning")
    assert item["status"] == "open"
    assert item["layer_ref_type"] == "segment"
    assert item["layer_ref_id"]
    assert item["detector"] == reason_code
    assert item["detector_revision"]
    assert 0.0 <= item["confidence"] <= 1.0
    assert item["confidence_source"] == "derived"
    assert item["evidence"]["schema_version"] == 1
    assert len(item["evidence_window_key"]) == 64
    assert item["metric"]["name"] == reason_code
    assert isinstance(item["metric"]["value"], (int, float))
    assert item["metric"]["code"] in (
        "THRESHOLD_WARNING",
        "THRESHOLD_BLOCKER",
    )


# ── registration fixture (idempotent; safe across parallel reruns) ─────────


@pytest.fixture(scope="module", autouse=True)
def _register_detectors():
    for fn in (
        register_contact_break,
        register_z_order_error,
        register_silhouette_clipping,
    ):
        fn()
    yield
    # teardown: leave the singleton registry just as we found it (idempotent)
    for name in (CB_NAME, ZO_NAME, SC_NAME):
        registry.unregister(name)


# ═══════════════════════════════════════════════════════════════════════════
# contact_break
# ═══════════════════════════════════════════════════════════════════════════


def test_contact_break_expired_contact_still_overlapping_blocker():
    """Contact expired at frame 20; both segments still render-overlap until
    frame 47; the measured minimum gap == blocker boundary (16px) → ONE
    blocker QCItem with reason contact_break.  (Gap > 16 would be outside
    the calibrated envelope → THRESHOLD_INVALID fail-closed, so the binary
    blocker case sits exactly on the boundary.)"""
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    blk = get_threshold("contact_break")["blocker_boundary"]
    # Segment A renders above B: x-ranges overlap every frame; y-gap = blk.
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    # b.y0 = a.y1 + blk → vertical gap exactly the blocker boundary
    b = _segment("seg-b", z_order=20, bbox_per_frame=[[10.0, 20.0 + blk, 40.0, 40.0 + blk]] * w)
    args = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)],
        [a, b],
    )
    items = detect_contact_break(args)
    assert len(items) == 1
    _assert_item_shape(items[0], "contact_break")
    assert items[0]["severity"] == "blocker"
    assert math.isclose(items[0]["metric"]["value"], blk)
    assert items[0]["evidence"]["window"] == {**WINDOW}
    assert items[0]["evidence"]["contact"] == {
        "source_segment_id": "seg-a",
        "target_segment_id": "seg-b",
        "contact_kind": "touch",
    }
    assert items[0]["evidence"]["overlap_after_expiry_frames"] == [21, 47]


def test_contact_break_warning_band():
    """Gap in [warning, blocker) → warning item (binary per policy)."""
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    warn = get_threshold("contact_break")["warning_boundary"]
    blk = get_threshold("contact_break")["blocker_boundary"]
    gap = (warn + blk) / 2.0  # strictly inside the warning band
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    # b.y0 = a.y1 + gap → vertical gap exactly `gap`
    b = _segment(
        "seg-b", z_order=20, bbox_per_frame=[[10.0, 20.0 + gap, 40.0, 40.0 + gap]] * w
    )
    args = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=24)],
        [a, b],
    )
    items = detect_contact_break(args)
    assert len(items) == 1
    _assert_item_shape(items[0], "contact_break")
    assert items[0]["severity"] == "warning"
    assert math.isclose(items[0]["metric"]["value"], gap)


def test_contact_break_within_boundary_no_item():
    """Gap strictly below the warning boundary → NO item (inside envelope)."""
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    warn = get_threshold("contact_break")["warning_boundary"]
    gap = warn / 2.0
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    # b.y0 = a.y1 + gap → vertical gap exactly `gap` (below warning)
    b = _segment(
        "seg-b", z_order=20, bbox_per_frame=[[10.0, 20.0 + gap, 40.0, 40.0 + gap]] * w
    )
    args = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=30)],
        [a, b],
    )
    assert detect_contact_break(args) == []
    assert measure_contact_gap(args) == gap


def test_contact_break_not_expired_or_no_overlap_no_item():
    """No item when the contact has NOT expired yet, or when the segments do
    not render-overlap after expiry, or the bboxes do not x-overlap."""
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    b = _segment("seg-b", z_order=20, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    # contact still active at end of analysis window → not expired
    active = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=47)],
        [a, b],
    )
    assert detect_contact_break(active) == []
    # contact expired but segment b stops rendering right after expiry
    b_short = _segment("seg-b", z_order=20, start_frame=0, end_frame=20, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * 21)
    no_overlap = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)],
        [a, b_short],
    )
    assert detect_contact_break(no_overlap) == []
    # x-ranges never overlap after expiry → no vertical contact geometry
    a_far = _segment("seg-a", z_order=10, bbox_per_frame=[[0.0, 10.0, 10.0, 20.0]] * w)
    b_far = _segment("seg-b", z_order=20, bbox_per_frame=[[90.0, 10.0, 100.0, 20.0]] * w)
    side_by_side = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)],
        [a_far, b_far],
    )
    assert detect_contact_break(side_by_side) == []


@pytest.mark.parametrize(
    "gap_fraction,expected_severity",
    [
        (0.25, None),  # gap = 25% of warning → pass, no item
        (0.999, None),  # gap just below warning → pass, no item
        (1.0, "warning"),  # gap == warning boundary → warning item
        (2.0, "warning"),  # gap inside the warning band (warn < gap < blk)
        (4.0, "blocker"),  # gap == blocker boundary (blk = 4x warn in policy) → blocker
    ],
)
def test_contact_break_severity_follows_policy_boundaries(
    gap_fraction: float, expected_severity: str | None
):
    """Severity mapping is READ from the T03A policy, never hard-coded:
    every expected severity in this table is recomputed from the runtime
    warning/blocker boundaries BEFORE the assert, so a policy change cannot
    hide behind a stale hard-coded expectation."""
    warn = get_threshold("contact_break")["warning_boundary"]
    blk = get_threshold("contact_break")["blocker_boundary"]
    gap = warn * gap_fraction
    expected = None
    if gap < warn:
        expected = None
    elif gap >= blk:
        expected = "blocker"
    elif gap >= warn:
        expected = "warning"
    if expected_severity is not None:
        assert expected == expected_severity  # the TABLE must agree with policy
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    # b.y0 = a.y1 + gap → vertical gap exactly `gap`
    b = _segment(
        "seg-b", z_order=20, bbox_per_frame=[[10.0, 20.0 + gap, 40.0, 40.0 + gap]] * w
    )
    args = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)],
        [a, b],
    )
    items = detect_contact_break(args)
    if expected is None:
        assert items == []
    else:
        assert len(items) == 1
        assert items[0]["severity"] == expected
        assert items[0]["metric"]["code"] == (
            "THRESHOLD_BLOCKER" if expected == "blocker" else "THRESHOLD_WARNING"
        )


# ═══════════════════════════════════════════════════════════════════════════
# z_order_error
# ═══════════════════════════════════════════════════════════════════════════


def test_z_order_error_inverted_render_order_blocker():
    """9-layer occlusion chain rendered in REVERSED order → every edge
    violated (8) >= blocker boundary (8) → ONE blocker QCItem."""
    segments = _chain_segments(9)
    edges = _chain_edges(9)  # 8 edges
    args = _zorder_args(
        segments,
        edges,
        render_order=[f"s{i}" for i in range(9)],  # chain order == fully inverted vs occlusion graph
    )
    items = detect_z_order_error(args)
    assert len(items) == 1
    _assert_item_shape(items[0], "z_order_error")
    assert items[0]["severity"] == "blocker"
    assert items[0]["metric"]["value"] == 8
    assert items[0]["evidence"]["order_source"] == "render_order"


def test_z_order_error_warning_band():
    """5-layer chain partially reversed → 4 violated edges (warning band)."""
    segments = _chain_segments(5)
    edges = _chain_edges(5)  # 4 edges
    # observed chain order: every edge has occluder below occludee → 4 violations
    args = _zorder_args(segments, edges, render_order=["s0", "s1", "s2", "s3", "s4"])
    items = detect_z_order_error(args)
    assert len(items) == 1
    _assert_item_shape(items[0], "z_order_error")
    assert items[0]["severity"] == "warning"
    assert items[0]["metric"]["value"] == 4


def test_z_order_error_within_boundary_no_item():
    """Two flipped adjacent pairs (2 violations < warning=4) → NO item."""
    segments = _chain_segments(5)
    edges = _chain_edges(5)
    args = _zorder_args(segments, edges, render_order=["s1", "s0", "s3", "s2", "s4"])
    items = detect_z_order_error(args)
    assert items == []
    assert measure_z_order_violations(args) == 2


def test_z_order_error_correct_order_no_item():
    """Occlusion-consistent order (occluder above occludee) → zero items."""
    segments = _chain_segments(9)
    edges = _chain_edges(9)
    args = _zorder_args(segments, edges)  # no render_order → z_order fallback, consistent
    assert detect_z_order_error(args) == []
    # explicit consistent order too
    args2 = _zorder_args(
        segments, edges, render_order=[f"s{i}" for i in range(8, -1, -1)]
    )
    assert detect_z_order_error(args2) == []
    assert measure_z_order_violations(args) == 0


def test_z_order_error_ignores_out_of_window_edges():
    """Occlusion edges outside the analysis window are not counted."""
    segments = _chain_segments(9)
    edges = [
        *_chain_edges(9),  # 8 in-window edges
        _occlusion("s0", "s1", start_frame=60, end_frame=90),  # outside window
    ]
    args = _zorder_args(
        segments,
        edges,
        window={"start_frame": 0, "end_frame": 47},
        render_order=[f"s{i}" for i in range(9)],
    )
    items = detect_z_order_error(args)
    assert len(items) == 1
    assert items[0]["metric"]["value"] == 8  # the extra edge is ignored


def test_z_order_error_reads_lock_manifest_via_s09_public_contract():
    """AC3: renderer lock manifest consumed through the PUBLIC S09 contract
    (structural_lock.validate_manifest).  A valid manifest whose segment
    order inverts the occlusion graph → blocker; an INVALID manifest
    (unknown key) fails closed with the S09 public error."""
    segments = _chain_segments(9)
    edges = _chain_edges(9)
    manifest = {
        "frame_count": 48,
        "timebase": {"fps": 30.0, "time_base": "1/30", "start_time_ms": 0},
        "shot_order": ["shot-1"],
        "fingerprints": {
            "z_order": "a" * 64,
            "contacts": "b" * 64,
        },
        "policy_version": "s09-lock-v1",
        "segments": [
            {
                "occurrence_segment_id": f"s{i}",
                "route": "pose_swap",
                "anchor": {"x": 0.5, "y": 0.5},
                "start_frame": 0,
                "end_frame": 47,
                "provenance": {},
            }
            for i in range(9)  # chain order == inverted render order
        ],
    }
    # sanity: the manifest itself is valid per the public S09 contract
    validated = validate_manifest(manifest)
    assert [s["occurrence_segment_id"] for s in validated["segments"]] == [
        f"s{i}" for i in range(9)
    ]
    args = _zorder_args(segments, edges, lock_manifest=manifest)
    items = detect_z_order_error(args)
    assert len(items) == 1
    assert items[0]["severity"] == "blocker"
    assert items[0]["metric"]["value"] == 8
    assert items[0]["evidence"]["order_source"] == "lock_manifest"

    # invalid manifest → fail closed with the S09 public contract error
    bad = {**manifest, "unknown_key": 1}
    with pytest.raises(StructuralLockParamsError):
        detect_z_order_error(_zorder_args(segments, edges, lock_manifest=bad))


def test_z_order_error_severity_follows_policy_boundaries():
    """Violation count classified against runtime policy boundaries."""
    blk = get_threshold("z_order_error")["blocker_boundary"]
    warn = get_threshold("z_order_error")["warning_boundary"]
    cases = [
        (warn - 1, None),  # inside envelope → no item
        (warn, "warning"),
        (blk, "blocker"),
    ]
    for violations, expected in cases:
        count = violations + 1  # chain length = edges + 1
        segments = _chain_segments(count)
        edges = _chain_edges(count)
        # chain order (s0..sN-1) = fully inverted vs occlusion graph → all
        # `violations` edges violated
        args = _zorder_args(
            segments, edges, render_order=[f"s{i}" for i in range(count)]
        )
        items = detect_z_order_error(args)
        if expected is None:
            assert items == []
        else:
            assert len(items) == 1
            assert items[0]["severity"] == expected
            assert items[0]["metric"]["value"] == violations


# ═══════════════════════════════════════════════════════════════════════════
# silhouette_clipping
# ═══════════════════════════════════════════════════════════════════════════


def test_silhouette_clipping_subject_cut_blocker():
    """Mask bbox shifted far outside the render boundary → clipped ratio
    >= blocker boundary → ONE blocker QCItem (subject area cut)."""
    warn = get_threshold("silhouette_clipping")["warning_boundary"]
    blk = get_threshold("silhouette_clipping")["blocker_boundary"]
    # T06A2 raw geometry: clip 50px → ratio 0.5 == blocker boundary
    seg = _segment("seg-a", z_order=10, bbox=_clip_bbox(50.0))
    items = detect_silhouette_clipping(_clipping_args([seg]))
    assert len(items) == 1
    _assert_item_shape(items[0], "silhouette_clipping")
    assert items[0]["severity"] == "blocker"
    assert math.isclose(items[0]["metric"]["value"], blk, rel_tol=1e-9)
    assert math.isclose(measure_clipping_ratio(_clipping_args([seg])), blk, rel_tol=1e-9)
    assert warn < blk  # sanity on the policy itself


def test_silhouette_clipping_cosmetic_warning():
    """Cosmetic clip (ratio in warning band) → warning item."""
    warn = get_threshold("silhouette_clipping")["warning_boundary"]
    blk = get_threshold("silhouette_clipping")["blocker_boundary"]
    clip = (warn + blk) / 2.0
    # invert T06A2 geometry: find clip_px producing ratio = clip
    # ratio(clip) = max(0, x1-100)*40/2400 with x1=80+clip → clip=60*ratio+... solved below
    # ratio = (80 + clip - 100) * 40 / 2400 when clip > 20 → ratio = (clip-20)/60
    clip_px = 20.0 + clip * 60.0
    seg = _segment("seg-a", z_order=10, bbox=_clip_bbox(clip_px))
    args = _clipping_args([seg])
    items = detect_silhouette_clipping(args)
    assert len(items) == 1
    _assert_item_shape(items[0], "silhouette_clipping")
    assert items[0]["severity"] == "warning"
    assert math.isclose(items[0]["metric"]["value"], clip, rel_tol=1e-6)
    assert warn <= items[0]["metric"]["value"] < blk


def test_silhouette_clipping_within_boundary_no_item():
    """Small clip inside the calibrated envelope → NO item."""
    warn = get_threshold("silhouette_clipping")["warning_boundary"]
    # T06A2 raw: clip 25px → ratio 0.0833 < warning
    seg = _segment("seg-a", z_order=10, bbox=_clip_bbox(25.0))
    args = _clipping_args([seg])
    assert detect_silhouette_clipping(args) == []
    assert measure_clipping_ratio(args) < warn


def test_silhouette_clipping_multiple_segments_independent():
    """One segment clipped hard (blocker) + one clean (no item) → exactly
    ONE item for the clipped segment, other untouched."""
    seg_bad = _segment("seg-a", z_order=10, bbox=_clip_bbox(50.0))
    seg_clean = _segment("seg-b", z_order=20, bbox=[5.0, 5.0, 95.0, 95.0])
    args = _clipping_args([seg_bad, seg_clean])
    items = detect_silhouette_clipping(args)
    assert len(items) == 1
    assert items[0]["layer_ref_id"] == "seg-a"
    assert items[0]["severity"] == "blocker"


def test_silhouette_clipping_out_of_window_segment_ignored():
    """Segment whose render window lies outside the analysis window → ignored."""
    seg_in = _segment("seg-a", z_order=10, bbox=_clip_bbox(50.0))
    seg_out = _segment(
        "seg-b", z_order=20, start_frame=60, end_frame=90, bbox=_clip_bbox(50.0)
    )
    args = _clipping_args([seg_in, seg_out])
    items = detect_silhouette_clipping(args)
    assert len(items) == 1
    assert items[0]["layer_ref_id"] == "seg-a"


# ═══════════════════════════════════════════════════════════════════════════
# registry + bounded runner integration (T03A consumption path)
# ═══════════════════════════════════════════════════════════════════════════


def test_detectors_registered_under_owned_names():
    for name, entry in (
        (CB_NAME, "app.services.qc_checks.contact_break:detect_contact_break"),
        (ZO_NAME, "app.services.qc_checks.z_order_error:detect_z_order_error"),
        (SC_NAME, "app.services.qc_checks.silhouette_clipping:detect_silhouette_clipping"),
    ):
        spec = registry.get(name)
        assert spec.entry_point == entry
        assert spec.version == "1.0.0"


def test_detectors_run_via_bounded_runner_child_process():
    """Each detector runs through the T03A bounded runner in a REAL child
    process: registered name + JSON args → DetectorRun with JSON-serializable
    output.  Proves the W6 modules implement the runner contract."""
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    # gap = blocker boundary (16px) → blocker so the runner output shape can
    # be asserted uniformly across the three detectors
    blk = get_threshold("contact_break")["blocker_boundary"]
    b = _segment("seg-b", z_order=20, bbox_per_frame=[[10.0, 20.0 + blk, 40.0, 40.0 + blk]] * w)
    cb_args = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)], [a, b]
    )
    segments = _chain_segments(9)
    edges = _chain_edges(9)
    zo_args = _zorder_args(
        segments, edges, render_order=[f"s{i}" for i in range(9)]
    )
    sc_args = _clipping_args([_segment("seg-a", z_order=10, bbox=_clip_bbox(50.0))])

    for name, args in (
        (CB_NAME, cb_args),
        (ZO_NAME, zo_args),
        (SC_NAME, sc_args),
    ):
        run: DetectorRun = run_detector(
            name,
            args=args,
            deadline_sec=30.0,
            capture_cap_bytes=65536,
        )
        assert run.status == "ok"
        assert run.code == QC_RUNNER_OK
        items = run.output
        assert isinstance(items, list) and len(items) == 1
        assert items[0]["reason_code"] == name
        assert items[0]["severity"] == "blocker"
        # JSON round-trip stability (the child already serialized it once)
        assert json.loads(json.dumps(items)) == items


# ═══════════════════════════════════════════════════════════════════════════
# evidence: schema_version=1, content-derived, byte-identical idempotent ×2
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "args_builder",
    [
        lambda: _contact_args(
            [
                _contact("seg-a", "seg-b", start_frame=0, end_frame=20),
            ],
            [
                _segment(
                    "seg-a", z_order=10,
                    bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * 48,
                ),
                _segment(
                    "seg-b", z_order=20,
                    bbox_per_frame=[[10.0, 34.0, 40.0, 54.0]] * 48,
                ),
            ],
        ),
        lambda: _zorder_args(
            _chain_segments(9),
            _chain_edges(9),
            render_order=[f"s{i}" for i in range(9)],
        ),
        lambda: _clipping_args(
            [_segment("seg-a", z_order=10, bbox=_clip_bbox(50.0))]
        ),
    ],
    ids=["contact_break", "z_order_error", "silhouette_clipping"],
)
def test_evidence_idempotent_byte_identical_x2(args_builder):
    """Two in-process runs of the same detector on the SAME args produce
    byte-identical evidence payloads AND evidence_window_keys (the idempotent
    content-derived contract)."""
    # map each builder to its detector
    if "contacts" in args_builder():
        fn, reason = detect_contact_break, "contact_break"
    elif "occlusion_edges" in args_builder():
        fn, reason = detect_z_order_error, "z_order_error"
    else:
        fn, reason = detect_silhouette_clipping, "silhouette_clipping"
    args = args_builder()
    first = fn(args)
    second = fn(args)
    assert len(first) == 1 and len(second) == 1
    assert _canonical_json(first) == _canonical_json(second)
    assert first[0]["evidence_window_key"] == second[0]["evidence_window_key"]
    assert first[0]["evidence"] == second[0]["evidence"]
    assert first[0]["evidence"]["schema_version"] == 1
    assert first[0]["reason_code"] == reason


def test_evidence_window_key_is_content_derived():
    """evidence_window_key == sha256 over the canonical evidence content —
    deterministic, no randomness, no wall-clock."""
    w = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    a = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w)
    b = _segment("seg-b", z_order=20, bbox_per_frame=[[10.0, 34.0, 40.0, 54.0]] * w)
    args = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)], [a, b]
    )
    items = detect_contact_break(args)
    assert len(items) == 1
    item = items[0]
    content = {
        "reason_code": item["reason_code"],
        "layer_ref_type": item["layer_ref_type"],
        "layer_ref_id": item["layer_ref_id"],
        "metric": item["metric"],
        "window": item["evidence"]["window"],
        "contact": item["evidence"]["contact"],
        "schema_version": item["evidence"]["schema_version"],
    }
    expected = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
    assert item["evidence_window_key"] == expected
    # different measured value → different key (content-derived, not a constant)
    w2 = WINDOW["end_frame"] - WINDOW["start_frame"] + 1
    # b.y0 = a.y1 + warn → gap == warning boundary → key differs from gap==blk
    warn = get_threshold("contact_break")["warning_boundary"]
    a2 = _segment("seg-a", z_order=10, bbox_per_frame=[[10.0, 10.0, 40.0, 20.0]] * w2)
    b2 = _segment(
        "seg-b", z_order=20, bbox_per_frame=[[10.0, 20.0 + warn, 40.0, 40.0 + warn]] * w2
    )
    args2 = _contact_args(
        [_contact("seg-a", "seg-b", start_frame=0, end_frame=20)], [a2, b2]
    )
    items2 = detect_contact_break(args2)
    assert items2[0]["evidence_window_key"] != item["evidence_window_key"]


def test_evidence_idempotent_across_runner_child_process():
    """Same args through the bounded runner TWICE (two fresh child processes)
    → byte-identical output (cross-process idempotency)."""
    segments = _chain_segments(9)
    edges = _chain_edges(9)
    args = _zorder_args(
        segments, edges, render_order=[f"s{i}" for i in range(9)]
    )
    run1: DetectorRun = run_detector(
        ZO_NAME, args=args, deadline_sec=30.0, capture_cap_bytes=65536
    )
    run2: DetectorRun = run_detector(
        ZO_NAME, args=args, deadline_sec=30.0, capture_cap_bytes=65536
    )
    assert run1.output == run2.output
    assert _canonical_json(run1.output) == _canonical_json(run2.output)


# ═══════════════════════════════════════════════════════════════════════════
# threshold provenance: boundaries trace to the frozen T06A2 calibration
# ═══════════════════════════════════════════════════════════════════════════


def test_threshold_boundaries_match_frozen_t06a2_calibration():
    """Detector severity boundaries are the SAME values the T03A policy
    derived from the frozen T06A2 calibration fixture (contact_zorder_
    clipping.json) — read-only consume, no hard-coded numbers in tests."""
    fixture_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "s11_qc"
        / "calibration"
        / "contact_zorder_clipping.json"
    )
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    records = {r["metric"]: r for r in doc["metrics"]}
    for metric in ("contact_break", "z_order_error", "silhouette_clipping"):
        rec = records[metric]
        levels = {lv["level"]: lv["raw_value"] for lv in rec["perturbation_levels"]}
        entry = get_threshold(metric)
        assert entry["warning_boundary"] == levels[2]
        assert entry["blocker_boundary"] == levels[4]
        assert entry["unit"] == rec["unit"]
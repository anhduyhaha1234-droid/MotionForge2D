"""Deterministic shot/layer chunk planner tests (S10-T01B).

Covers all six binary acceptance bullets.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from app.services.s10_chunk_plan import ChunkPlanError, plan_full_apply

# ── helpers ──────────────────────────────────────────────────────────────────


def _h64(i: int) -> str:
    """Deterministic 64-hex hash for tests."""
    return hashlib.sha256(f"hash-{i}".encode()).hexdigest()


def _ckpt(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "checkpoint_id": "ckpt-001",
        "checkpoint_hash": _h64(1),
        "revision": 3,
        "source_generation": "gen-1",
        "video_item_id": "vi-1",
        "project_id": "proj-1",
        "workspace_id": "ws-1",
    }
    if overrides:
        base.update(overrides)
    return base


def _manifest(overrides: dict[str, Any] | None = None, *, frame_count: int = 100) -> dict[str, Any]:
    base: dict[str, Any] = {
        "manifest_hash": _h64(2),
        "policy_version": "policy-v1",
        "source_generation": "gen-1",
        "frame_count": frame_count,
    }
    if overrides:
        base.update(overrides)
    return base


def _scene_manifest(shots: list[tuple[str, int, int]]) -> dict[str, Any]:
    return {
        "shots": [{"shot_id": sid, "start_frame": s, "end_frame": e} for sid, s, e in shots]
    }


def _mapping(layers: list[tuple[str, str, list[str] | None]] | None = None) -> dict[str, Any]:
    if layers is None:
        layers = [("bg", "sprite_affine", None), ("fg", "mesh_warp", None)]
    return {
        "mappings": [
            {"layer_id": lid, "route": route, **({"deps": deps} if deps else {})}
            for lid, route, deps in layers
        ]
    }


def _policy(version: str = "policy-v1") -> dict[str, Any]:
    return {"policy_version": version}


# ── 1. byte-identical canonical plan/hash/IDs twice ─────────────────────────


def test_deterministic_byte_identical_twice() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=100)
    scene = _scene_manifest([("s1", 0, 49), ("s2", 50, 99)])
    mapping_v: dict[str, Any] = _mapping()
    policy = _policy()

    plan_a = plan_full_apply(ckpt, manifest, scene, mapping_v, policy, chunk_frames=16, overlap_frames=4)
    plan_b = plan_full_apply(ckpt, manifest, scene, mapping_v, policy, chunk_frames=16, overlap_frames=4)

    assert plan_a["plan_id"] == plan_b["plan_id"]
    assert plan_a["plan_hash"] == plan_b["plan_hash"]

    # byte-identical canonical JSON of full plan
    j_a = json.dumps(plan_a, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    j_b = json.dumps(plan_b, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert j_a == j_b
    # plan_id is sha256 of canonical plan body (chunks+inputs+version), not circular hash of full plan
    body_a = {"chunks": plan_a["chunks"], "inputs": plan_a["inputs"], "version": plan_a["version"]}
    assert hashlib.sha256(json.dumps(body_a, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == plan_a["plan_id"]

    # chunk IDs identical order
    ids_a = [c["chunk_id"] for c in plan_a["chunks"]]
    ids_b = [c["chunk_id"] for c in plan_b["chunks"]]
    assert ids_a == ids_b
    # content hashes identical
    ch_a = [c["content_hash_input"] for c in plan_a["chunks"]]
    ch_b = [c["content_hash_input"] for c in plan_b["chunks"]]
    assert ch_a == ch_b


def test_deterministic_shuffled_input_still_same() -> None:
    # scene_manifest and mapping order should not affect deterministic sorted output
    ckpt = _ckpt()
    manifest = _manifest(frame_count=60)
    scene_forward = _scene_manifest([("s1", 0, 29), ("s2", 30, 59)])
    scene_reverse_raw = {"shots": [{"shot_id": "s2", "start_frame": 30, "end_frame": 59}, {"shot_id": "s1", "start_frame": 0, "end_frame": 29}]}
    mapping_forward = _mapping([("bg", "sprite_affine", None), ("fg", "mesh_warp", None)])
    mapping_reverse = {"mappings": [{"layer_id": "fg", "route": "mesh_warp"}, {"layer_id": "bg", "route": "sprite_affine"}]}

    pa = plan_full_apply(ckpt, manifest, scene_forward, mapping_forward, _policy(), chunk_frames=10, overlap_frames=2)
    pb = plan_full_apply(ckpt, manifest, scene_reverse_raw, mapping_reverse, _policy(), chunk_frames=10, overlap_frames=2)
    assert pa["plan_id"] == pb["plan_id"]
    assert [c["chunk_id"] for c in pa["chunks"]] == [c["chunk_id"] for c in pb["chunks"]]


# ── 2. every source frame covered exactly once as core; overlap context only ──


def test_every_frame_covered_exactly_once() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=100)
    scene = _scene_manifest([("s1", 0, 39), ("s2", 40, 99)])
    mapping_v: dict[str, Any] = _mapping([("bg", "sprite_affine", None)])
    plan = plan_full_apply(ckpt, manifest, scene, mapping_v, _policy(), chunk_frames=16, overlap_frames=4)

    # Only check one layer (bg) - others would duplicate frames per layer
    # But the contract: every source frame covered exactly once as CORE per layer
    # Test by grouping per layer
    for layer_id in ("bg",):
        chunks = [c for c in plan["chunks"] if c["layer_id"] == layer_id]
        chunks.sort(key=lambda c: c["core_start_frame"])
        covered: list[tuple[int, int]] = [(c["core_start_frame"], c["core_end_frame"]) for c in chunks]
        # check contiguous and exactly once
        cursor = 0
        for s, e in covered:
            assert s == cursor, f"gap or drift: expected {cursor}, got {s}"
            cursor = e + 1
        assert cursor == 100, f"final coverage {cursor} != 100"
        # check no overlaps in core
        for i in range(1, len(covered)):
            assert covered[i][0] == covered[i - 1][1] + 1
            assert covered[i][0] > covered[i - 1][0]
        # overlap metadata must be correct but not affect core coverage
        for c in chunks:
            assert 0 <= c["overlap_before"] <= 4
            assert 0 <= c["overlap_after"] <= 4
        # first chunk has no overlap_before, last has no overlap_after
        assert chunks[0]["overlap_before"] == 0
        assert chunks[-1]["overlap_after"] == 0
        # middle chunks have overlap on both sides where not at shot boundary
        # For this scene split: shot s1 0-39 with chunk 16 -> chunks [0-15,16-31,32-39]
        # middle chunk 16-31 should have before=4 and after=4, etc.


def test_overlap_frames_are_context_only_not_duplicated() -> None:
    # Verify that core ranges do not overlap and that overlap is metadata only
    ckpt = _ckpt()
    manifest = _manifest(frame_count=50)
    scene = _scene_manifest([("s1", 0, 49)])
    plan = plan_full_apply(ckpt, manifest, scene, _mapping([("bg", "sprite_affine", None)]), _policy(), chunk_frames=16, overlap_frames=4)
    chunks = sorted([c for c in plan["chunks"] if c["layer_id"] == "bg"], key=lambda c: c["core_start_frame"])
    # core ranges must be non-overlapping and gap-free
    for i in range(len(chunks) - 1):
        assert chunks[i]["core_end_frame"] + 1 == chunks[i + 1]["core_start_frame"], "core gap or overlap"
    # overlap metadata does not create duplicate core frames
    total_core = sum(c["core_end_frame"] - c["core_start_frame"] + 1 for c in chunks)
    assert total_core == 50
    # overlap values at boundaries
    assert chunks[0]["overlap_before"] == 0
    assert chunks[0]["overlap_after"] == 4
    assert chunks[-1]["overlap_after"] == 0


# ── 3. no gap/cut drift/off-by-one across shot and chunk boundaries ──────────


def test_no_gap_cut_drift_across_shots() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=100)
    scene = _scene_manifest([("s1", 0, 29), ("s2", 30, 59), ("s3", 60, 99)])
    plan = plan_full_apply(ckpt, manifest, scene, _mapping([("l1", "sprite_affine", None)]), _policy(), chunk_frames=10, overlap_frames=2)
    for shot_id, s, e in [("s1", 0, 29), ("s2", 30, 59), ("s3", 60, 99)]:
        chunks = [c for c in plan["chunks"] if c["shot_id"] == shot_id]
        chunks.sort(key=lambda c: c["core_start_frame"])
        assert chunks[0]["core_start_frame"] == s, f"shot {shot_id} first chunk drift"
        assert chunks[-1]["core_end_frame"] == e, f"shot {shot_id} last chunk drift"
        cursor = s
        for c in chunks:
            assert c["core_start_frame"] == cursor, f"shot {shot_id} gap at {cursor}"
            assert c["core_end_frame"] >= c["core_start_frame"]
            cursor = c["core_end_frame"] + 1
        assert cursor == e + 1


def test_single_frame_shot() -> None:
    ckpt = _ckpt()
    # 3 frames: s1 0-0 (1 frame), s2 1-1 (1 frame), s3 2-2 (1 frame)
    manifest = _manifest(frame_count=3)
    scene = _scene_manifest([("s1", 0, 0), ("s2", 1, 1), ("s3", 2, 2)])
    plan = plan_full_apply(ckpt, manifest, scene, _mapping([("bg", "sprite_affine", None)]), _policy(), chunk_frames=10, overlap_frames=2)
    for shot_id, frame in [("s1", 0), ("s2", 1), ("s3", 2)]:
        chunks = [c for c in plan["chunks"] if c["shot_id"] == shot_id]
        assert len(chunks) == 1, f"1-frame shot {shot_id} should have exactly 1 chunk"
        assert chunks[0]["core_start_frame"] == frame
        assert chunks[0]["core_end_frame"] == frame
        assert chunks[0]["overlap_before"] == 0
        assert chunks[0]["overlap_after"] == 0


def test_final_partial_chunk() -> None:
    # 25 frames with chunk_frames 10 -> chunks 0-9, 10-19, 20-24 (partial 5)
    ckpt = _ckpt()
    manifest = _manifest(frame_count=25)
    scene = _scene_manifest([("s1", 0, 24)])
    plan = plan_full_apply(ckpt, manifest, scene, _mapping([("bg", "sprite_affine", None)]), _policy(), chunk_frames=10, overlap_frames=2)
    chunks = sorted([c for c in plan["chunks"] if c["layer_id"] == "bg"], key=lambda c: c["core_start_frame"])
    assert len(chunks) == 3
    assert chunks[0]["core_start_frame"] == 0 and chunks[0]["core_end_frame"] == 9
    assert chunks[1]["core_start_frame"] == 10 and chunks[1]["core_end_frame"] == 19
    assert chunks[2]["core_start_frame"] == 20 and chunks[2]["core_end_frame"] == 24
    # overlap behavior at boundaries
    assert chunks[0]["overlap_before"] == 0 and chunks[0]["overlap_after"] == 2
    assert chunks[1]["overlap_before"] == 2 and chunks[1]["overlap_after"] == 2
    assert chunks[2]["overlap_before"] == 2 and chunks[2]["overlap_after"] == 0


def test_many_small_shots_no_drift() -> None:
    # 10 shots of 10 frames each = 100 frames
    ckpt = _ckpt()
    manifest = _manifest(frame_count=100)
    shots = [(f"s{i}", i * 10, i * 10 + 9) for i in range(10)]
    scene = _scene_manifest(shots)
    plan = plan_full_apply(ckpt, manifest, scene, _mapping([("bg", "sprite_affine", None)]), _policy(), chunk_frames=6, overlap_frames=2)
    for sid, s, e in shots:
        chunks = sorted([c for c in plan["chunks"] if c["shot_id"] == sid], key=lambda c: c["core_start_frame"])
        assert chunks[0]["core_start_frame"] == s
        assert chunks[-1]["core_end_frame"] == e
        cursor = s
        for c in chunks:
            assert c["core_start_frame"] == cursor
            cursor = c["core_end_frame"] + 1
        assert cursor == e + 1


# ── 4. layer/role routes and structural dependencies pinned per chunk ─────────


def test_layer_routes_pinned_per_chunk() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=30)
    scene = _scene_manifest([("s1", 0, 29)])
    mapping_v: dict[str, Any] = _mapping(
        [
            ("background", "sprite_affine", None),
            ("character", "mesh_warp", None),
            ("prop", "part_rig", None),
        ]
    )
    plan = plan_full_apply(ckpt, manifest, scene, mapping_v, _policy(), chunk_frames=10, overlap_frames=2)
    route_by_layer = {"background": "sprite_affine", "character": "mesh_warp", "prop": "part_rig"}
    for c in plan["chunks"]:
        assert c["route"] == route_by_layer[c["layer_id"]], f"route not pinned for {c['chunk_id']}"


def test_structural_deps_pinned() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=40)
    scene = _scene_manifest([("s1", 0, 39)])
    # fg depends on bg via explicit deps, should propagate to every chunk
    mapping_v: dict[str, Any] = _mapping(
        [
            ("bg", "sprite_affine", None),
            ("fg", "mesh_warp", ["bg"]),
        ]
    )
    plan = plan_full_apply(ckpt, manifest, scene, mapping_v, _policy(), chunk_frames=10, overlap_frames=2)
    bg_chunks = [c for c in plan["chunks"] if c["layer_id"] == "bg"]
    fg_chunks = [c for c in plan["chunks"] if c["layer_id"] == "fg"]
    # every fg chunk should have "bg" in deps
    for c in fg_chunks:
        assert "bg" in c["deps"], f"fg chunk {c['chunk_id']} missing base dep bg"
    # also chain deps: each chunk after first should depend on previous chunk in same shot/layer
    fg_sorted = sorted(fg_chunks, key=lambda c: c["core_start_frame"])
    for i in range(1, len(fg_sorted)):
        assert fg_sorted[i - 1]["chunk_id"] in fg_sorted[i]["deps"], "missing sequential dep"
    # cross-layer sequential deps: fg chunk i depends on bg chunk i
    bg_sorted = sorted(bg_chunks, key=lambda c: c["core_start_frame"])
    for i in range(len(fg_sorted)):
        assert bg_sorted[i]["chunk_id"] in fg_sorted[i]["deps"], f"fg chunk {i} missing cross-layer dep on bg {i}"


def test_deps_sorted_deterministic() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=20)
    scene = _scene_manifest([("s1", 0, 19)])
    mapping_v: dict[str, Any] = _mapping(
        [
            ("a", "sprite_affine", ["z", "m"]),
            ("b", "mesh_warp", None),
        ]
    )
    plan = plan_full_apply(ckpt, manifest, scene, mapping_v, _policy(), chunk_frames=10, overlap_frames=2)
    for c in plan["chunks"]:
        assert c["deps"] == sorted(c["deps"]), "deps must be sorted deterministic"


# ── 5. changing pinned input changes plan identity; ambient does not ─────────


def test_changing_pinned_input_changes_plan_id() -> None:
    base_ckpt = _ckpt()
    base_manifest = _manifest(frame_count=50)
    base_scene = _scene_manifest([("s1", 0, 49)])
    base_mapping: dict[str, Any] = _mapping([("bg", "sprite_affine", None)])
    base_policy = _policy("policy-v1")

    base_plan = plan_full_apply(base_ckpt, base_manifest, base_scene, base_mapping, base_policy, chunk_frames=10, overlap_frames=2)
    base_id = base_plan["plan_id"]

    # change checkpoint_hash
    ckpt2 = _ckpt({"checkpoint_hash": _h64(99)})
    p2 = plan_full_apply(ckpt2, base_manifest, base_scene, base_mapping, base_policy, chunk_frames=10, overlap_frames=2)
    assert p2["plan_id"] != base_id

    # change manifest hash
    man2 = _manifest({"manifest_hash": _h64(99)}, frame_count=50)
    p3 = plan_full_apply(base_ckpt, man2, base_scene, base_mapping, base_policy, chunk_frames=10, overlap_frames=2)
    assert p3["plan_id"] != base_id

    # change policy
    p4 = plan_full_apply(base_ckpt, base_manifest, base_scene, base_mapping, _policy("policy-v2"), chunk_frames=10, overlap_frames=2)
    assert p4["plan_id"] != base_id

    # change scene (add shot boundary)
    scene2 = _scene_manifest([("s1", 0, 24), ("s2", 25, 49)])
    p5 = plan_full_apply(base_ckpt, base_manifest, scene2, base_mapping, base_policy, chunk_frames=10, overlap_frames=2)
    assert p5["plan_id"] != base_id

    # change mapping route
    mapping2: dict[str, Any] = _mapping([("bg", "mesh_warp", None)])
    p6 = plan_full_apply(base_ckpt, base_manifest, base_scene, mapping2, base_policy, chunk_frames=10, overlap_frames=2)
    assert p6["plan_id"] != base_id

    # change chunk_frames
    p7 = plan_full_apply(base_ckpt, base_manifest, base_scene, base_mapping, base_policy, chunk_frames=16, overlap_frames=2)
    assert p7["plan_id"] != base_id

    # change overlap
    p8 = plan_full_apply(base_ckpt, base_manifest, base_scene, base_mapping, base_policy, chunk_frames=10, overlap_frames=4)
    assert p8["plan_id"] != base_id


def test_ambient_inputs_do_not_change_identity() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=30)
    scene = _scene_manifest([("s1", 0, 29)])
    mapping_v: dict[str, Any] = _mapping([("bg", "sprite_affine", None)])
    policy = _policy()

    base = plan_full_apply(ckpt, manifest, scene, mapping_v, policy, chunk_frames=10, overlap_frames=2)

    # add ambient extra keys in approved_checkpoint (should be ignored)
    ckpt_ambient = {**ckpt, "ambient_path": "/tmp/foo", "timestamp": time.time(), "pid": os.getpid()}
    manifest_ambient = {**manifest, "ambient_tmp": "/some/path", "generated_at": "2026-01-01"}
    scene_ambient = {**scene, "ambient_source": "/data/video.mp4"}
    mapping_ambient: dict[str, Any] = {**mapping_v, "ambient_note": "ignore me"}

    ambient_plan = plan_full_apply(
        ckpt_ambient,  # type: ignore[arg-type]
        manifest_ambient,  # type: ignore[arg-type]
        scene_ambient,  # type: ignore[arg-type]
        mapping_ambient,  # type: ignore[arg-type]
        policy,
        chunk_frames=10,
        overlap_frames=2,
        extra_ambient="/tmp/not/used",
        some_path=Path("/tmp/foo"),
        timestamp_now=time.time(),
    )
    assert ambient_plan["plan_id"] == base["plan_id"]
    assert [c["chunk_id"] for c in ambient_plan["chunks"]] == [c["chunk_id"] for c in base["chunks"]]
    assert [c["content_hash_input"] for c in ambient_plan["chunks"]] == [c["content_hash_input"] for c in base["chunks"]]


# ── 6. malformed / non-monotonic / overlapping fail closed ───────────────────


def test_empty_shots_fail() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=10)
    with pytest.raises(ChunkPlanError):
        plan_full_apply(ckpt, manifest, {"shots": []}, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)  # type: ignore[arg-type]


def test_overlapping_shots_fail() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=20)
    # overlap: s1 0-15, s2 10-19
    scene = _scene_manifest([("s1", 0, 15), ("s2", 10, 19)])
    with pytest.raises(ChunkPlanError, match="overlap"):
        plan_full_apply(ckpt, manifest, scene, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)


def test_gap_between_shots_fail() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=20)
    # gap: s1 0-9, s2 11-19 (missing frame 10)
    scene = _scene_manifest([("s1", 0, 9), ("s2", 11, 19)])
    with pytest.raises(ChunkPlanError, match="gap"):
        plan_full_apply(ckpt, manifest, scene, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)


def test_not_starting_at_zero_fail() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=10)
    scene = _scene_manifest([("s1", 1, 10)])
    # frame_count would mismatch but first test non-zero start
    with pytest.raises(ChunkPlanError):
        plan_full_apply(ckpt, manifest, scene, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)


def test_non_monotonic_shot_order_still_validated() -> None:
    # non-monotonic but overlapping after sort should fail
    ckpt = _ckpt()
    manifest = _manifest(frame_count=20)
    # s1 10-19, s2 0-9 - sorted they are contiguous so this should PASS (sorting makes monotonic)
    # but if we give s1 0-12 and s2 10-19 -> overlap after sort -> fail
    scene_overlap = _scene_manifest([("s2", 10, 19), ("s1", 0, 12)])
    with pytest.raises(ChunkPlanError, match="overlap"):
        plan_full_apply(ckpt, manifest, scene_overlap, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)


def test_end_before_start_fail() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=10)
    scene: dict[str, Any] = {"shots": [{"shot_id": "s1", "start_frame": 5, "end_frame": 3}]}
    with pytest.raises(ChunkPlanError):
        plan_full_apply(ckpt, manifest, scene, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)


def test_frame_count_mismatch_fail() -> None:
    ckpt = _ckpt()
    # manifest says 100 but shots cover 50
    manifest = _manifest(frame_count=100)
    scene = _scene_manifest([("s1", 0, 49)])
    with pytest.raises(ChunkPlanError, match="frame_count mismatch"):
        plan_full_apply(ckpt, manifest, scene, _mapping(), _policy(), chunk_frames=10, overlap_frames=2)


def test_invalid_checkpoint_fails() -> None:
    with pytest.raises(ChunkPlanError):
        plan_full_apply({"checkpoint_id": ""}, _manifest(), _scene_manifest([("s1", 0, 9)]), _mapping(), _policy(), chunk_frames=10, overlap_frames=2)  # type: ignore[arg-type]
    with pytest.raises(ChunkPlanError):
        plan_full_apply({"checkpoint_id": "x", "checkpoint_hash": "bad"}, _manifest(), _scene_manifest([("s1", 0, 9)]), _mapping(), _policy(), chunk_frames=10, overlap_frames=2)  # type: ignore[arg-type]


def test_invalid_manifest_fails() -> None:
    ckpt = _ckpt()
    with pytest.raises(ChunkPlanError):
        plan_full_apply(ckpt, {"manifest_hash": "bad", "policy_version": "v1", "source_generation": "g", "frame_count": 10}, _scene_manifest([("s1", 0, 9)]), _mapping(), _policy(), chunk_frames=10, overlap_frames=2)  # type: ignore[arg-type]


def test_invalid_route_fails() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=10)
    scene = _scene_manifest([("s1", 0, 9)])
    bad_mapping: dict[str, Any] = {"mappings": [{"layer_id": "bg", "route": "invalid_route"}]}
    with pytest.raises(ChunkPlanError, match="route"):
        plan_full_apply(ckpt, manifest, scene, bad_mapping, _policy(), chunk_frames=10, overlap_frames=2)


def test_duplicate_layer_id_fails() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=10)
    scene = _scene_manifest([("s1", 0, 9)])
    dup: dict[str, Any] = {"mappings": [{"layer_id": "bg", "route": "sprite_affine"}, {"layer_id": "bg", "route": "mesh_warp"}]}
    with pytest.raises(ChunkPlanError, match="duplicate layer_id"):
        plan_full_apply(ckpt, manifest, scene, dup, _policy(), chunk_frames=10, overlap_frames=2)


def test_overlap_greater_than_chunk_fails() -> None:
    ckpt = _ckpt()
    manifest = _manifest(frame_count=10)
    scene = _scene_manifest([("s1", 0, 9)])
    with pytest.raises(ChunkPlanError, match="overlap_frames must be < chunk_frames"):
        plan_full_apply(ckpt, manifest, scene, _mapping(), _policy(), chunk_frames=5, overlap_frames=5)


def test_non_dict_inputs_fail() -> None:
    with pytest.raises(ChunkPlanError):
        plan_full_apply("not a dict", _manifest(), _scene_manifest([("s1", 0, 9)]), _mapping(), _policy())  # type: ignore[arg-type]

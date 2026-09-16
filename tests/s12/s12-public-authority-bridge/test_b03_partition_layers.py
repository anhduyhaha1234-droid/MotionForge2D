"""B03 — temporal partition + occurrence layers (frozen D2 node IDs).

Partition = scene shots (disjoint, contiguous, full coverage); occurrence
intervals = active layers inside it (overlap allowed; repeated roles keep
distinct ranges/regions/routes; no Cartesian application of inactive layers).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from conftest import (
    WS,
    build_graph,
    make_env,
    submit_full_apply,
)

DBOX = {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}
DBOX2 = {"x": 96.0, "y": 30.0, "w": 50.0, "h": 40.0}


def _run_full(env, seed):
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    claimed = env.svc._worker.run_once()
    assert claimed == 1
    return run_id


def _pub_rel(env, run_id: str) -> str:
    with env.factory() as s:
        row = s.execute(
            text(
                "SELECT a.relative_path FROM s10_full_apply_publication p "
                "JOIN artifact a ON a.id = p.artifact_id "
                "WHERE p.run_id=:r AND p.workspace_id=:w AND p.state='completed'"
            ),
            {"r": run_id, "w": WS},
        ).scalar()
    assert row, "completed publication with artifact required"
    return str(row)


def _sidecar(env, run_id: str) -> dict:
    rel = _pub_rel(env, run_id)
    ev = env.managed_root / (rel + ".evidence.json")
    assert ev.is_file(), f"evidence sidecar missing: {ev}"
    return json.loads(ev.read_text(encoding="utf-8"))


def _chunk_rows(env, run_id: str) -> list[dict]:
    with env.factory() as s:
        rows = s.execute(
            text(
                "SELECT shot_id, layer_id, core_start_frame, core_end_frame, "
                "overlap_before, overlap_after FROM s10_full_apply_chunk "
                "WHERE run_id=:r AND workspace_id=:w ORDER BY order_index"
            ),
            {"r": run_id, "w": WS},
        ).mappings().all()
    return [dict(r) for r in rows]


def test_b03_cooccurring_graph_all_occurrences_active_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[
            {"role": "r1", "start": 0, "end": 119, "box": DBOX, "z_order": 0},
            {"role": "r2", "start": 0, "end": 119, "box": DBOX2, "z_order": 1},
        ],
    )
    assert seed["approval_created"] is True
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is True
    assert {o["layer_id"] for o in auth["timeline"]["occurrences"]} == set(seed["segments"])
    run_id = _run_full(env, seed)
    rows = _chunk_rows(env, run_id)
    assert {r["layer_id"] for r in rows} == set(seed["segments"])
    sidecar = _sidecar(env, run_id)
    per_layer = sidecar["per_layer_evidence"]
    assert {r["layer_id"] for r in per_layer} == set(seed["segments"])
    assert all(r["verdict"] == "contributed" for r in per_layer)


def test_b03_partition_covers_every_frame_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 59), (60, 119)],
        segments=[{"role": "r1", "start": 30, "end": 89, "box": DBOX}],
    )
    shots = seed["authority"]["timeline"]["shots"]
    assert len(shots) == 2
    ordered = sorted(shots, key=lambda s: s["start_frame"])
    assert ordered[0]["start_frame"] == 0
    assert ordered[0]["end_frame"] + 1 == ordered[1]["start_frame"]
    assert ordered[-1]["end_frame"] + 1 == 120
    covered = sum(s["end_frame"] - s["start_frame"] + 1 for s in ordered)
    assert covered == 120
    run_id = _run_full(env, seed)
    sidecar = _sidecar(env, run_id)
    assert sidecar["decoded_frame_count"] == 120
    assert sidecar["frame_count" if "frame_count" in sidecar else "decoded_frame_count"] == 120


def test_b03_two_visible_characters_plus_object_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[
            {"role": "r1", "start": 0, "end": 119, "box": DBOX, "z_order": 0},
            {"role": "r2", "start": 0, "end": 119, "box": DBOX2, "z_order": 1},
            {
                "role": "r3",
                "role_name": "Crate",
                "kind": "prop",
                "start": 40,
                "end": 119,
                "box": {"x": 60.0, "y": 70.0, "w": 60.0, "h": 40.0},
                "z_order": 2,
            },
        ],
    )
    run_id = _run_full(env, seed)
    sidecar = _sidecar(env, run_id)
    per_layer = sidecar["per_layer_evidence"]
    assert len({r["layer_id"] for r in per_layer}) == 3
    assert all(r["verdict"] == "contributed" for r in per_layer)
    # the prop covers [40,119]: its rows never claim frames < 40
    for row in per_layer:
        if row["layer_id"] == seed["segments"][list(seed["segments"])[2]]["seg_id"]:
            assert row["range"][0] >= 40


def test_b03_repeated_role_distinct_routes_regions_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[
            {"role": "r1", "start": 0, "end": 59, "box": DBOX, "route": "sprite_affine"},
            {"role": "r1", "start": 60, "end": 119, "box": DBOX2, "route": "pose_swap"},
        ],
    )
    occs = seed["authority"]["timeline"]["occurrences"]
    assert len(occs) == 2
    assert {o["role_id"] for o in occs} == {seed["roles"]["r1"]["role_id"]}
    assert occs[0]["layer_id"] != occs[1]["layer_id"]
    assert {o["route"] for o in occs} == {"sprite_affine", "pose_swap"}
    assert {tuple(o["affected_region"]) for o in occs} == {
        (0.1, 0.1, 0.5, 0.5),
        (0.6, 0.25, 0.3125, 0.3333333333333333),
    } or len({tuple(o["affected_region"]) for o in occs}) == 2
    run_id = _run_full(env, seed)
    sidecar = _sidecar(env, run_id)
    per_layer = sidecar["per_layer_evidence"]
    assert {r["layer_id"] for r in per_layer} == {o["layer_id"] for o in occs}
    assert all(r["verdict"] == "contributed" for r in per_layer)


def test_b03_background_only_interval_source_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    from app.services.renderer_routes.composite import decode_rgb_frames

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 59), (60, 119)],
        segments=[{"role": "r1", "scene": 1, "start": 60, "end": 119, "box": DBOX}],
    )
    run_id = _run_full(env, seed)
    rows = _chunk_rows(env, run_id)
    scene1, scene2 = seed["scene_ids"]
    assert rows, "layer must render chunks in scene 2"
    assert all(r["shot_id"] == scene2 for r in rows)
    sidecar = _sidecar(env, run_id)
    assert sidecar["decoded_frame_count"] == 120

    src = decode_rgb_frames(env.managed_root / seed["source_rel"])
    out = decode_rgb_frames(env.managed_root / _pub_rel(env, run_id))
    assert len(out) == 120
    # background-only interval [0,59] stays source-verbatim (solid frames;
    # mp4v roundtrip tolerance)
    for frame_index in (0, 30, 59):
        diff = np.abs(out[frame_index].astype(int) - src[frame_index].astype(int))
        assert float(diff.mean()) < 6.0, f"frame {frame_index} not source-verbatim"


def test_b03_one_frame_boundary_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 0), (1, 119)],
        segments=[
            {"role": "r1", "scene": 0, "start": 0, "end": 0, "box": DBOX},
            {"role": "r2", "scene": 1, "start": 1, "end": 119, "box": DBOX2},
        ],
    )
    run_id = _run_full(env, seed)
    rows = _chunk_rows(env, run_id)
    one_frame = [r for r in rows if r["core_start_frame"] == 0 and r["core_end_frame"] == 0]
    assert len(one_frame) == 1
    assert one_frame[0]["overlap_before"] == 0 and one_frame[0]["overlap_after"] == 0
    sidecar = _sidecar(env, run_id)
    assert sidecar["decoded_frame_count"] == 120
    row = [r for r in sidecar["per_layer_evidence"] if r["range"] == [0, 0]]
    assert row and row[0]["sampled_frames"] == [0] and row[0]["verdict"] == "contributed"


def test_b03_multiscene_global_vs_local_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fixtures seed GLOBAL ranges (ruling Q2 adapter note): the occurrence
    spans the cut [30,89] and must be chunked per shot, never merged."""
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 59), (60, 119)],
        segments=[{"role": "r1", "start": 30, "end": 89, "box": DBOX}],
    )
    occ = seed["authority"]["timeline"]["occurrences"][0]
    assert (occ["start_frame"], occ["end_frame"]) == (30, 89)  # global preserved
    run_id = _run_full(env, seed)
    rows = _chunk_rows(env, run_id)
    scene1, scene2 = seed["scene_ids"]
    assert {(r["shot_id"], r["core_start_frame"], r["core_end_frame"]) for r in rows} == {
        (scene1, 30, 59),
        (scene2, 60, 89),
    }
    assert len({r["layer_id"] for r in rows}) == 1  # ONE identity across the cut


def test_b03_no_cartesian_inactive_layer_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 59), (60, 119)],
        segments=[
            {"role": "r1", "scene": 0, "start": 0, "end": 59, "box": DBOX},
            {"role": "r2", "scene": 1, "start": 60, "end": 119, "box": DBOX2},
        ],
    )
    run_id = _run_full(env, seed)
    rows = _chunk_rows(env, run_id)
    scene1, scene2 = seed["scene_ids"]
    r1 = seed["segments"][list(seed["segments"])[0]]["seg_id"]
    r2 = seed["segments"][list(seed["segments"])[1]]["seg_id"]
    pairs = {(r["shot_id"], r["layer_id"]) for r in rows}
    assert (scene1, r1) in pairs and (scene2, r2) in pairs
    assert (scene1, r2) not in pairs  # inactive layer never applied
    assert (scene2, r1) not in pairs
    assert all(
        (r["shot_id"], r["layer_id"]) in {(scene1, r1), (scene2, r2)} for r in rows
    )

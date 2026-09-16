"""B04 — shared S09/S10 eligibility (frozen D2 node IDs).

Points-only / missing / ambiguous boxed geometry and unsupported routes are
honestly ineligible with typed reasons and ZERO unintended S10 rows; valid
authoritative boxes proceed.  No guessed rectangles, no readiness flags.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import (
    build_graph,
    make_env,
    run_counts,
    submit_full_apply,
)

DBOX = {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}
MODE_A = {"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.30}


def test_b04_points_only_ineligible_same_reason_and_zero_s10_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "geometry": "points_only"}],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is False
    reasons = " ".join(auth["eligibility"]["reasons"])
    assert seed["geometry_codes"]["box_missing"] in reasons
    excluded = auth["timeline"]["excluded"]
    assert excluded and excluded[0]["reason_code"] == seed["geometry_codes"]["box_missing"]
    assert auth["timeline"]["occurrences"] == []
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert seed["geometry_codes"]["box_missing"] in resp.json()["detail"]
    assert run_counts(env) == (0, 0)


def test_b04_missing_and_ambiguous_geometry_ineligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[
            {"role": "r1", "start": 0, "end": 119, "geometry": "none"},
            {"role": "r2", "start": 0, "end": 119, "geometry": "multi_box"},
        ],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is False
    reasons = " ".join(auth["eligibility"]["reasons"])
    assert seed["geometry_codes"]["box_missing"] in reasons
    assert seed["geometry_codes"]["box_ambiguous"] in reasons
    codes = {e["reason_code"] for e in auth["timeline"]["excluded"]}
    assert codes == {
        seed["geometry_codes"]["box_missing"],
        seed["geometry_codes"]["box_ambiguous"],
    }
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert run_counts(env) == (0, 0)


def test_b04_within_key_differing_boxes_ambiguous_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "geometry": "multi_box"}],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is False
    excluded = auth["timeline"]["excluded"]
    assert excluded[0]["reason_code"] == seed["geometry_codes"]["box_ambiguous"]
    assert auth["timeline"]["occurrences"] == []
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert seed["geometry_codes"]["box_ambiguous"] in resp.json()["detail"]
    assert run_counts(env) == (0, 0)


def test_b04_unsupported_route_ineligible_no_unintended_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "box": DBOX, "route": "mesh_warp"}],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is False
    excluded = auth["timeline"]["excluded"]
    assert excluded[0]["reason_code"] == seed["geometry_codes"]["route_not_executable"]
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"].lower()
    assert "mesh_warp" in detail and "no downgrade" in detail
    assert run_counts(env) == (0, 0)


def test_b04_valid_boxed_authority_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "box": MODE_A}],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is True
    occ = auth["timeline"]["occurrences"][0]
    assert occ["scale_mode"] == "normalized"
    assert occ["affected_region"] == [0.1, 0.1, 0.3, 0.3]
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 202, resp.text
    runs, jobs = run_counts(env)
    assert runs == 1 and jobs >= 1


def test_b04_no_guessed_rectangle_no_readiness_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "geometry": "points_only"}],
    )
    auth = seed["authority"]
    # no invented rectangle anywhere for the points-only occurrence
    assert auth["timeline"]["occurrences"] == []
    assert auth["timeline"]["excluded"][0]["reason_code"] == seed["geometry_codes"]["box_missing"]
    # points evidence preserved verbatim (never converted into a box)
    seg_entry = auth["segments"][0]
    assert seg_entry["geometry"]["segmentation"]["points"]
    assert not seg_entry["geometry"]["segmentation"]["boxes"]
    # no readiness-flag bypass anywhere in the frozen authority
    assert "readiness" not in json.dumps(auth)
    assert auth["eligibility"]["reasons"], "ineligible authority must carry reasons"

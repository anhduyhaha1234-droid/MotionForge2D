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


# ── Q4-coverage additions beyond D2 (QA review `958d021`: ruling v0.2 §5) ──


def test_b04_mode_b_padded_clip_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling v0.2 §5: padded pixel-scale boxes may overrun the frame edge; the
    derived region is the deterministic frame intersection (clip) and the
    authority PROCEEDS (never denied for a padded box)."""
    from app.services.source_locked_timeline import derive_region

    env = make_env(tmp_path, monkeypatch)
    # sanctioned-chain geometry: {400,100,250,250} on 640x360 (x+w=650 > 640)
    box = {"x": 400.0, "y": 100.0, "w": 250.0, "h": 250.0}
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        dims=(640, 360),
        segments=[{"role": "r1", "start": 0, "end": 119, "box": box}],
    )
    # independent recompute straight from the delivered clipping formula
    x2 = min(400.0 + 250.0, 640.0)
    y2 = min(100.0 + 250.0, 360.0)
    expected = [400.0 / 640.0, 100.0 / 360.0, (x2 - 400.0) / 640.0, (y2 - 100.0) / 360.0]
    # and via the real derive_region (same code path the approval uses)
    shared_region, shared_mode = derive_region([400.0, 100.0, 250.0, 250.0], 640, 360)
    assert shared_mode == "pixel"
    assert shared_region == expected

    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is True
    occ = auth["timeline"]["occurrences"][0]
    assert occ["affected_region"] == expected
    assert abs(occ["affected_region"][0] - 0.625) < 1e-12
    assert abs(occ["affected_region"][1] - 0.2777777777777778) < 1e-12
    assert abs(occ["affected_region"][2] - 0.375) < 1e-12
    assert abs(occ["affected_region"][3] - 0.6944444444444444) < 1e-12
    assert occ["scale_mode"] == "pixel"
    assert occ["raw_box"] == [400.0, 100.0, 250.0, 250.0]
    assert occ["geometry_source"] == "segmentation.boxes[0]"
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 202, resp.text
    assert run_counts(env)[0] == 1


def test_b04_scale_unresolved_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pixel-scale box + source dims unavailable → typed deny
    OCCURRENCE_REGION_SCALE_UNRESOLVED (never guessed); zero mutation."""
    from app.services.source_locked_timeline import (
        CODE_REGION_SCALE_UNRESOLVED,
        TimelineAuthorityError,
        derive_region,
    )

    with pytest.raises(TimelineAuthorityError) as err:
        derive_region([100.0, 100.0, 300.0, 300.0], None, None)
    assert err.value.code == CODE_REGION_SCALE_UNRESOLVED

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        hide_dims=True,
        segments=[
            {
                "role": "r1",
                "start": 0,
                "end": 119,
                "box": {"x": 100.0, "y": 100.0, "w": 300.0, "h": 300.0},
            }
        ],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is False
    assert CODE_REGION_SCALE_UNRESOLVED in " ".join(auth["eligibility"]["reasons"])
    excluded = auth["timeline"]["excluded"]
    assert excluded and excluded[0]["reason_code"] == CODE_REGION_SCALE_UNRESOLVED
    assert auth["timeline"]["occurrences"] == []
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert CODE_REGION_SCALE_UNRESOLVED in resp.json()["detail"]
    assert run_counts(env) == (0, 0)


def test_b04_fully_outside_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A box fully outside the frame (x >= src_w) → typed deny
    OCCURRENCE_REGION_OUT_OF_BOUNDS; submit fails closed with zero rows."""
    from app.services.source_locked_timeline import (
        CODE_REGION_OUT_OF_BOUNDS,
        TimelineAuthorityError,
        derive_region,
    )

    with pytest.raises(TimelineAuthorityError) as err:
        derive_region([700.0, 100.0, 50.0, 50.0], 640, 360)
    assert err.value.code == CODE_REGION_OUT_OF_BOUNDS

    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        dims=(640, 360),
        segments=[
            {
                "role": "r1",
                "start": 0,
                "end": 119,
                "box": {"x": 700.0, "y": 100.0, "w": 50.0, "h": 50.0},
            }
        ],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is False
    assert CODE_REGION_OUT_OF_BOUNDS in " ".join(auth["eligibility"]["reasons"])
    excluded = auth["timeline"]["excluded"]
    assert excluded and excluded[0]["reason_code"] == CODE_REGION_OUT_OF_BOUNDS
    assert auth["timeline"]["occurrences"] == []
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 422, resp.text
    assert CODE_REGION_OUT_OF_BOUNDS in resp.json()["detail"]
    assert run_counts(env) == (0, 0)


def test_b04_cross_key_precedence_geometry_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling Q1 cross-key precedence: segmentation.boxes wins over a DIFFERENT
    prompt.boxes (rule, not guess) — the occurrence proceeds with the
    segmentation-derived region and a frozen ``geometry_source``; the prompt
    evidence is preserved verbatim (never merged/overridden)."""
    env = make_env(tmp_path, monkeypatch)
    seed = build_graph(
        env,
        monkeypatch,
        scenes=[(0, 119)],
        segments=[{"role": "r1", "start": 0, "end": 119, "geometry": "cross_key_conflict"}],
    )
    auth = seed["authority"]
    assert auth["eligibility"]["full_apply_executable"] is True
    occ = auth["timeline"]["occurrences"][0]
    seg_expected = [16.0 / 160.0, 12.0 / 120.0, 80.0 / 160.0, 60.0 / 120.0]
    prompt_derived = [30.0 / 160.0, 20.0 / 120.0, 50.0 / 160.0, 50.0 / 120.0]
    assert occ["affected_region"] == seg_expected
    assert occ["affected_region"] != prompt_derived
    assert occ["geometry_source"] == "segmentation.boxes[0]"
    assert occ["scale_mode"] == "pixel"
    assert occ["raw_box"] == [16.0, 12.0, 80.0, 60.0]
    # both evidence keys preserved verbatim in the frozen segment record
    seg_entry = auth["segments"][0]
    assert seg_entry["geometry"]["segmentation"]["boxes"] == [
        {"x": 16.0, "y": 12.0, "w": 80.0, "h": 60.0}
    ]
    assert seg_entry["geometry"]["prompt"]["boxes"] == [
        {"x": 30.0, "y": 20.0, "w": 50.0, "h": 50.0}
    ]
    resp = submit_full_apply(env, seed)
    assert resp.status_code == 202, resp.text
    assert run_counts(env)[0] == 1

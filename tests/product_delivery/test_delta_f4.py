"""DELTA-F4 tests — group-engine cast resolves replacement assets via the FROZEN
mapping (occurrence layer -> object role), never by indexing the layer id space
into the role-keyed manifest.

Defect (measured live, run ``90319e92-af21-4951-b030-5da5ed6d4cb1``): the submit
route builds ``replacement_assets`` keyed by OBJECT ROLE id
(``app/api/routes/s10_full_apply.py`` — ``assets[role_id]``) while the group
chunk members are occurrence LAYER ids; the worker's group path looked the layer
id up directly, so EVERY comfy group run died at chunk 0 with
``replacement_assets missing entry for layer '0cbfa39b-…'`` (0 GPU work).  The
legacy per-layer path already had the correct adapter
(``_stage_layer_asset`` — ``mapping_entry.get("role_id") or layer_id``); the
group path was the missing translation.

Rows (the render world is the DELTA-F1 route-parity fixture: manifest pins come
from the REAL submit-route helper ``_resolve_canonical_render_pins`` over the
persisted v2 authority, the render authority is the REAL service output, and the
scripted engine stands at the ENGINE BOUNDARY — no GPU, no ComfyUI server):

* F4.1 positive: 2 members with 2 DISTINCT roles; render succeeds with exactly
  ONE engine call and every cast member carries ITS OWN mapping role/asset
  (no layer-keyed lookup, no first-member-wins translation).
* F4.2 negative: the FIRST member's role entry is missing from the manifest ->
  typed refusal, ZERO engine calls (fail-closed kept).
* F4.3 negative: the SECOND member's role entry is missing -> typed refusal,
  ZERO engine calls (catches "translate every member with the first entry").
* F4.4 parity/micro: the legacy ``_stage_layer_asset`` adapter resolves the SAME
  role-keyed manifest (both paths share ``_replacement_asset_key``), and legacy
  role-as-layer mappings keep the old fallback behaviour unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import test_delta_f1 as f1

from app.workflow import s10_full_apply_jobs as jobs


def _mapping_entry(world: Any, layer_id: str) -> dict[str, Any]:
    mappings = (world.authority.get("mapping") or {}).get("mappings") or []
    for m in mappings:
        if str(m.get("layer_id")) == layer_id:
            return dict(m)
    raise AssertionError(f"layer {layer_id!r} not in render authority mapping")


# ── F4.1 — positive: layer -> role translation, per member ───────────────────


def test_delta_f4_1_group_cast_resolves_assets_through_the_role_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, seed, _artifacts, scene_pk = f1._seed_world(tmp_path)
    run_id, plan = f1._submit(factory, seed, scene_pk)
    world = f1._EngineWorld(tmp_path, factory, seed, run_id, plan)

    members = list(world.members)
    assert len(members) == 2, f"multi-member group chunk required, got {members}"
    roles = [world.role_by_layer[m] for m in members]
    assert all(roles), f"every member must map to a role, got {roles}"
    assert len(set(roles)) == 2, f"DISTINCT roles per member required, got {roles}"

    # The manifest contract itself: ROLE-keyed, never layer-keyed (route parity).
    manifest_keys = set((world.manifest.get("replacement_assets") or {}).keys())
    assert manifest_keys == set(roles), (
        f"route-parity manifest must be role-keyed: {manifest_keys} vs {roles}"
    )
    assert not (set(members) & manifest_keys), (
        "occurrence layer ids must never key replacement_assets"
    )

    rel, sha, size, evidence = world.render(monkeypatch)

    assert len(world.calls) == 1, "exactly ONE engine request"
    cast = world.calls[0]["cast"]
    assert [str(c["role"]) for c in cast] == members
    for c, lid in zip(cast, members):
        role = world.role_by_layer[lid]
        assert str(c["character_id"]) == role, (
            f"member {lid} must be translated to ITS OWN role {role}, got {c['character_id']}"
        )
        ref = c["references"][0]
        want = world.manifest["replacement_assets"][role]
        assert str(ref["artifact_id"]) == str(want["artifact_id"])
        assert str(ref["sha256"]) == str(want["sha256"]).lower()
        assert str(ref["store_relative_path"]) == str(want["rel"])
    assert evidence["route"] == "shot_group"
    out = world.managed / rel
    assert out.is_file() and f1._sha_file(out) == sha and size > 0


# ── F4.2/F4.3 — negative: missing ROLE entry stays a typed refusal ───────────


def test_delta_f4_2_missing_first_role_entry_refused_zero_engine_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, seed, _artifacts, scene_pk = f1._seed_world(tmp_path)
    run_id, plan = f1._submit(factory, seed, scene_pk)
    world = f1._EngineWorld(tmp_path, factory, seed, run_id, plan)
    first_role = world.role_by_layer[world.members[0]]
    del world.manifest["replacement_assets"][first_role]

    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        world.render(monkeypatch)

    assert "replacement_assets" in str(exc.value)
    assert first_role in str(exc.value), (
        f"the refusal must name the looked-up key {first_role!r}: {exc.value}"
    )
    assert world.calls == [], "a missing role entry must never reach the engine"


def test_delta_f4_3_missing_second_role_entry_refused_zero_engine_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, seed, _artifacts, scene_pk = f1._seed_world(tmp_path)
    run_id, plan = f1._submit(factory, seed, scene_pk)
    world = f1._EngineWorld(tmp_path, factory, seed, run_id, plan)
    second_role = world.role_by_layer[world.members[1]]
    del world.manifest["replacement_assets"][second_role]

    with pytest.raises(jobs.S10FullApplyJobError) as exc:
        world.render(monkeypatch)

    assert "replacement_assets" in str(exc.value)
    assert second_role in str(exc.value), (
        f"the refusal must name the looked-up key {second_role!r}: {exc.value}"
    )
    assert world.calls == [], (
        "every member must be translated (no first-member-wins); missing entry "
        "for member 2 must still refuse before the engine"
    )


# ── F4.4 — parity: both resolution paths share the adapter ──────────────────


def test_delta_f4_4_legacy_adapter_agrees_and_fallback_stays_legacy(
    tmp_path: Path,
) -> None:
    factory, seed, _artifacts, scene_pk = f1._seed_world(tmp_path)
    run_id, plan = f1._submit(factory, seed, scene_pk)
    world = f1._EngineWorld(tmp_path, factory, seed, run_id, plan)

    # (a) the legacy per-layer path stages the SAME role-keyed manifest
    for lid in world.members:
        role = world.role_by_layer[lid]
        stage_dir = jobs._stage_layer_asset(
            world.managed, run_id, lid, world.manifest, _mapping_entry(world, lid)
        )
        staged = stage_dir / f"{lid}.png"
        assert staged.is_file()
        assert f1._sha_file(staged) == str(
            world.manifest["replacement_assets"][role]["sha256"]
        ).lower()

    # (b) micro: the shared adapter, incl. the legacy role-as-layer fallback
    assert jobs._replacement_asset_key({"role_id": "role-x"}, "LAYER-1") == "role-x"
    assert jobs._replacement_asset_key({}, "LAYER-1") == "LAYER-1"
    assert jobs._replacement_asset_key({"role_id": ""}, "LAYER-1") == "LAYER-1"

"""S09-T01 domain tests — ReskinConfig durable contract.

Covers (binary, fail-closed):
1. Only published/compatible/complete PackVersion accepted; unpublished /
   incompatible reject with zero mutation.
2. Revision CAS stale → conflict, zero mutation.
3. Idempotent replay equivalent → existing row; conflicting replay → conflict.
4. Publishing later pack version does not mutate pinned version_id.
7. Domain validation fail-closed for every out-of-domain param
   (anchor, scale, fit_mode, clip_mode, rotation, opacity).

Runs on the isolated conftest client fixture DB only (never MAIN).
"""

from __future__ import annotations

import uuid

import pytest

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import CORE_POSE_SLOTS
from app.persistence.reskin_config import (
    ReskinConfigConflictError,
    ReskinConfigOwnershipError,
    ReskinConfigParamsError,
    ReskinConfigRepository,
    canonical_params_json,
    validate_params,
)

VALID_PARAMS = {
    "anchor": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "fit_mode": "contain",
    "clip_mode": "asset_alpha",
    "offset": {"x": 0.0, "y": 0.0},
    "rotation_offset_deg": 0.0,
    "opacity": 1.0,
}


def _sf():
    svc = deps._job_service
    assert svc is not None
    return svc._session_factory()


def _ensure_ws(s, ws_id: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.persistence.models import Workspace

    s.execute(
        sqlite_insert(Workspace)
        .values(id=ws_id, name=ws_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


def _attach_core_pose_assets(s, ws_id: str, pack_version_id: str) -> None:
    """One ready Artifact + CharacterAsset per CORE_POSE_SLOTS (C1 policy)."""
    from app.persistence.models import Artifact, CharacterAsset

    for slot in CORE_POSE_SLOTS:
        art = Artifact(
            workspace_id=ws_id,
            kind="image",
            state="ready",
            relative_path=f"artifacts/{uuid.uuid4().hex}.png",
            mime_type="image/png",
            size_bytes=100,
            sha256="c" * 64,
        )
        s.add(art)
        s.flush()
        s.add(
            CharacterAsset(
                pack_version_id=pack_version_id,
                workspace_id=ws_id,
                pose_slot=slot,
                artifact_id=art.id,
            )
        )


def _seed_one(ws: str = DEFAULT_WORKSPACE_ID) -> tuple[str, str, str, str]:
    """Project + video + scene + confirmed role + character + published complete pack."""
    with _sf() as s:
        _ensure_ws(s, ws)
        from app.persistence.models import (
            Character,
            CharacterPackVersion,
            ObjectRole,
            Project,
            Scene,
            VideoItem,
        )

        proj = Project(workspace_id=ws, name=f"ReskinProj-{uuid.uuid4().hex[:6]}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title="Vid", position=0)
        s.add(vid)
        s.flush()
        scene = Scene(
            video_item_id=vid.id,
            position=0,
            start_frame=0,
            end_frame=10,
            start_time_ms=0,
            end_time_ms=1000,
            status="pending",
        )
        s.add(scene)
        s.flush()
        role = ObjectRole(
            workspace_id=ws,
            project_id=proj.id,
            video_item_id=vid.id,
            source_generation="1",
            name="Hero",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=ws, name="CharReskin", code=f"cr_{uuid.uuid4().hex[:6]}")
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(
            character_id=char.id, workspace_id=ws, version=1, status="published"
        )
        s.add(pv)
        s.flush()
        _attach_core_pose_assets(s, ws, pv.id)
        s.commit()
        return proj.id, role.id, char.id, pv.id


def _create_pack(
    char_id: str, ws: str, version: int, status: str = "published"
) -> str:
    with _sf() as s:
        from app.persistence.models import CharacterPackVersion

        pv = CharacterPackVersion(
            character_id=char_id, workspace_id=ws, version=version, status=status
        )
        s.add(pv)
        s.flush()
        # Deliberately NO pose assets here: this helper produces a pack in
        # the requested status WITHOUT completeness, for fail-closed tests.
        # Use _create_complete_pack for fully-usable packs.
        s.commit()
        return pv.id


def _create_complete_pack(char_id: str, ws: str, version: int) -> str:
    with _sf() as s:
        from app.persistence.models import CharacterPackVersion

        pv = CharacterPackVersion(
            character_id=char_id, workspace_id=ws, version=version, status="published"
        )
        s.add(pv)
        s.flush()
        _attach_core_pose_assets(s, ws, pv.id)
        s.commit()
        return pv.id


# ── Test 1a: published+compatible+complete accepted ──────────────────────


def test_create_config_accepts_published_complete_pack(
    _patch_project_root: object,
) -> None:
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        record, created = repo.create_config(
            ws, proj, role, char, pv, dict(VALID_PARAMS), f"dom1a-{uuid.uuid4().hex[:6]}"
        )
        s.commit()
        assert created is True
        assert record.pack_version_id == pv
        assert record.params == validate_params(VALID_PARAMS)
        assert record.revision == 1


# ── Test 1b: unpublished pack rejected fail-closed, zero mutation ─────────


@pytest.mark.parametrize("status", ["draft", "validating", "ready", "archived"])
def test_create_config_rejects_unpublished_pack(status: str, _patch_project_root: object) -> None:
    proj, role, char, _pv_ok = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    pv_bad = _create_pack(char, ws, version=2, status=status)
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        before_total = len(repo.list_configs(ws)[0])
        with pytest.raises((ReskinConfigConflictError, ReskinConfigOwnershipError)):
            repo.create_config(
                ws, proj, role, char, pv_bad, dict(VALID_PARAMS), None
            )
        s.rollback()
        assert len(repo.list_configs(ws)[0]) == before_total


# ── Test 1c: incomplete pack rejected fail-closed ─────────────────────────


def test_create_config_rejects_incomplete_pack(_patch_project_root: object) -> None:
    proj, role, char, _pv_ok = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    # published but NO pose assets → incomplete_pack + missing_required_pose
    pv_incomplete = _create_pack(char, ws, version=3, status="published")
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        with pytest.raises(ReskinConfigConflictError, match="compatibility blocked"):
            repo.create_config(ws, proj, role, char, pv_incomplete, dict(VALID_PARAMS), None)
        s.rollback()


# ── Test 2: CAS stale → conflict, zero mutation ───────────────────────────


def test_update_cas_stale_conflict_zero_mutation(_patch_project_root: object) -> None:
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rec, _ = repo.create_config(
            ws, proj, role, char, pv_old, dict(VALID_PARAMS), f"cas2-{uuid.uuid4().hex[:6]}"
        )
        s.commit()
        cid = rec.id

    new_params = dict(VALID_PARAMS)
    new_params["scale"] = 2.0
    # Valid update bumps revision to 2
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        updated = repo.update_config(cid, ws, 1, params=new_params)
        s.commit()
        assert updated.revision == 2
        assert updated.params["scale"] == 2.0

    # Stale expected_revision=1 → conflict; row unchanged
    stale_params = dict(VALID_PARAMS)
    stale_params["scale"] = 9.0
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        with pytest.raises(ReskinConfigConflictError, match="stale revision"):
            repo.update_config(cid, ws, 1, params=stale_params)
        s.rollback()
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        after = repo.get_config(cid, ws)
        assert after.revision == 2
        assert after.params["scale"] == 2.0
        # pack_version_id unchanged by a params-only update
        assert after.pack_version_id == pv_old


# ── Test 3: idempotent replay equivalent → existing; conflicting → 409 ────


def test_replay_equivalent_returns_existing_row(_patch_project_root: object) -> None:
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"replay3-{uuid.uuid4().hex[:6]}"
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        r1, c1 = repo.create_config(ws, proj, role, char, pv, dict(VALID_PARAMS), key)
        s.commit()
        assert c1 is True
        r2, c2 = repo.create_config(ws, proj, role, char, pv, dict(VALID_PARAMS), key)
        s.commit()
        assert c2 is False
        assert r2.id == r1.id
        assert r2.revision == 1
        configs, total = repo.list_configs(ws, project_id=proj)
        assert total == 1


def test_replay_conflicting_payload_conflict_zero_mutation(_patch_project_root: object) -> None:
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"conf3-{uuid.uuid4().hex[:6]}"
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rec, _ = repo.create_config(ws, proj, role, char, pv, dict(VALID_PARAMS), key)
        s.commit()
        cid = rec.id

    conflicting = dict(VALID_PARAMS)
    conflicting["scale"] = 5.0
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        with pytest.raises(ReskinConfigConflictError, match="different reskin config payload"):
            repo.create_config(ws, proj, role, char, pv, conflicting, key)
        s.rollback()
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        after = repo.get_config(cid, ws)
        assert after.revision == 1
        assert after.params["scale"] == 1.0


# ── Test 4: publishing later pack version does NOT mutate the pin ─────────


def test_publish_new_pack_does_not_mutate_pinned_version(_patch_project_root: object) -> None:
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"iso4-{uuid.uuid4().hex[:6]}"
    with _sf() as s:
        repo = ReskinConfigRepository(s)
        rec, _ = repo.create_config(ws, proj, role, char, pv_old, dict(VALID_PARAMS), key)
        s.commit()
        cid = rec.id
        before = repo.get_config(cid, ws)

    _create_complete_pack(char, ws, version=2)
    _create_complete_pack(char, ws, version=3)

    with _sf() as s:
        repo = ReskinConfigRepository(s)
        after = repo.get_config(cid, ws)
        assert after.pack_version_id == pv_old == before.pack_version_id
        assert after.revision == before.revision == 1
        assert after.params == before.params


# ── Test 7: params validation fail-closed (every out-of-domain param) ─────


def _with(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "anchor": {"x": 0.5, "y": 0.5},
        "scale": 1.0,
        "fit_mode": "contain",
        "clip_mode": "asset_alpha",
        "offset": {"x": 0.0, "y": 0.0},
        "rotation_offset_deg": 0.0,
        "opacity": 1.0,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


@pytest.mark.parametrize(
    "bad_params",
    [
        _with(anchor={"x": -0.01, "y": 0.5}),
        _with(anchor={"x": 1.01, "y": 0.5}),
        _with(anchor={"x": 0.5, "y": -1.0}),
        _with(anchor={"x": 0.5}),  # missing y
        _with(scale=0.0),
        _with(scale=-0.5),
        _with(fit_mode="zoom"),
        _with(fit_mode=None),
        _with(clip_mode="magic"),
        _with(offset={"x": float("nan"), "y": 0.0}),
        _with(rotation_offset_deg="ninety"),
        _with(opacity=-0.1),
        _with(opacity=1.01),
        {**_with(), "unknown_key": 1},  # closed key set
        {"anchor": {"x": 0.5, "y": 0.5}},  # missing keys fail-closed
    ],
)
def test_validate_params_fail_closed(bad_params: dict[str, object]) -> None:
    with pytest.raises(ReskinConfigParamsError):
        validate_params(bad_params)


def test_canonical_params_json_deterministic() -> None:
    a = canonical_params_json(_with())
    b = canonical_params_json(dict(reversed(list(_with().items()))))  # type: ignore[arg-type]
    assert a == b
    assert '"anchor":{"x":0.5,"y":0.5}' in a

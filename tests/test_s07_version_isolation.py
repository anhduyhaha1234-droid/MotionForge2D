"""S07-T03 Version Isolation — Scenarios 5-13 + 15 (integration).

Scenarios:
 5. Publishing new Pack Version does NOT change old mapping
 6. Old mapping still points to old Pack Version ID (exact ID)
 7. Old mapping row not silently mutated (byte-identical, revision unchanged)
 8. Explicit repin creates valid update
 9. Revision increments correctly
 10. Stale repin returns 409
 11. Stale repin zero mutation
 12. Equivalent replay no duplicate
 13. Conflicting replay fail closed
 15. Migration round-trip preserves invariant

Quality: real repository/API, no ORM editing, exact ID/revision/row checks,
version-isolation compares before/after strongly.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path
from app.persistence.models import (
    Character,
    CharacterPackVersion,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.project_cast import (
    ProjectCastConflictError,
    ProjectCastRepository,
)


def _sf():
    svc = deps._job_service
    assert svc is not None
    return svc._session_factory()


def _ensure_ws(s, ws_id: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    s.execute(
        sqlite_insert(Workspace)
        .values(id=ws_id, name=ws_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


def _attach_core_pose_assets(s, ws_id: str, pack_version_id: str) -> None:
    """Attach one ready Artifact + CharacterAsset per CORE_POSE_SLOTS.

    F-B (BA verdict 2026-08-21): every published CharacterPackVersion must
    satisfy the C1 completeness policy (CORE_POSE_SLOTS =
    front/three_quarter/side/back/sitting/walking); otherwise mapping
    create/update fails closed with ``incomplete_pack,missing_required_pose``.
    """
    from app.persistence.models import CORE_POSE_SLOTS, Artifact, CharacterAsset

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
    with _sf() as s:
        _ensure_ws(s, ws)
        proj = Project(workspace_id=ws, name=f"VersProj-{uuid.uuid4().hex[:6]}")
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
        from app.persistence.models import ObjectRole

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
        char = Character(workspace_id=ws, name="CharVers", code=f"cv_{uuid.uuid4().hex[:6]}")
        s.add(char)
        s.flush()
        pv1 = CharacterPackVersion(
            character_id=char.id, workspace_id=ws, version=1, status="published"
        )
        s.add(pv1)
        s.flush()
        _attach_core_pose_assets(s, ws, pv1.id)
        s.commit()
        return proj.id, role.id, char.id, pv1.id


def _create_new_pack_for_char(char_id: str, ws: str = DEFAULT_WORKSPACE_ID, version: int = 77) -> str:  # noqa: E501
    with _sf() as s:
        pv = CharacterPackVersion(
            character_id=char_id, workspace_id=ws, version=version, status="published"
        )
        s.add(pv)
        s.flush()
        _attach_core_pose_assets(s, ws, pv.id)
        s.commit()
        return pv.id


# ── Scenario 5/6/7: new publish does not change old mapping ───────────


def test_publish_new_pack_version_does_not_change_old_mapping(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 5: publishing a new pack version does NOT change old mapping (row identity)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"vers5-{uuid.uuid4().hex[:6]}"
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, key)
        s.commit()
        mid = rec.id
        before = repo.get_mapping(mid, ws)
        before_pack = before.pack_version_id
        before_rev = before.revision
        before_char = before.character_id
        before_proj = before.project_id
        before_role = before.object_role_id

    # Publish new pack version as NEW row (immutable)
    pv_new = _create_new_pack_for_char(char, ws, version=2)

    # After publish, old mapping must still point to old pack_version_id, unchanged
    with _sf() as s:
        repo = ProjectCastRepository(s)
        after = repo.get_mapping(mid, ws)
        assert after.pack_version_id == pv_old
        assert after.pack_version_id == before_pack
        assert after.pack_version_id != pv_new
        assert after.revision == before_rev
        assert after.character_id == before_char
        assert after.project_id == before_proj
        assert after.object_role_id == before_role


def test_old_mapping_still_points_old_pack_version_id(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 6: old mapping still points to old Pack Version ID (exact ID assertion)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, f"vers6-{uuid.uuid4().hex[:6]}")
        s.commit()
        mid = rec.id

    pv_new = _create_new_pack_for_char(char, ws, version=3)
    pv_new2 = _create_new_pack_for_char(char, ws, version=4)

    with _sf() as s:
        repo = ProjectCastRepository(s)
        after = repo.get_mapping(mid, ws)
        # Exact ID check — must be old, not new
        assert after.pack_version_id == pv_old
        assert after.pack_version_id not in (pv_new, pv_new2)
        # Also verify via raw SQL row identity
        _row = s.execute(select(text("pack_version_id")).select_from(text("project_cast_mapping")).where(text("id=:mid")), {"mid": mid})  # type: ignore[arg-type]  # noqa: F841, E501
        # Simpler: query via ORM raw
        from app.persistence.models import ProjectCastMapping

        orm_row = s.scalar(select(ProjectCastMapping).where(ProjectCastMapping.id == mid))
        assert orm_row is not None
        assert orm_row.pack_version_id == pv_old


def test_old_mapping_row_not_silently_mutated(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 7: old mapping row not silently mutated (byte-identical, strongly compared)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, f"vers7-{uuid.uuid4().hex[:6]}")
        s.commit()
        mid = rec.id
        before = repo.get_mapping(mid, ws)
        # Capture strong snapshot: all fields that matter
        before_dict = {
            "id": before.id,
            "workspace_id": before.workspace_id,
            "project_id": before.project_id,
            "object_role_id": before.object_role_id,
            "character_id": before.character_id,
            "pack_version_id": before.pack_version_id,
            "idempotency_key": before.idempotency_key,
            "revision": before.revision,
        }
        # Also capture DB row via direct query for byte-identical check
        from app.persistence.models import ProjectCastMapping

        db_before = s.scalar(select(ProjectCastMapping).where(ProjectCastMapping.id == mid))
        assert db_before is not None
        before_db_pack = db_before.pack_version_id
        before_db_rev = db_before.revision

    # Publish 2 new versions (simulating library updates)
    _create_new_pack_for_char(char, ws, version=5)
    _create_new_pack_for_char(char, ws, version=6)

    with _sf() as s:
        repo = ProjectCastRepository(s)
        after = repo.get_mapping(mid, ws)
        after_dict = {
            "id": after.id,
            "workspace_id": after.workspace_id,
            "project_id": after.project_id,
            "object_role_id": after.object_role_id,
            "character_id": after.character_id,
            "pack_version_id": after.pack_version_id,
            "idempotency_key": after.idempotency_key,
            "revision": after.revision,
        }
        from app.persistence.models import ProjectCastMapping

        db_after = s.scalar(select(ProjectCastMapping).where(ProjectCastMapping.id == mid))
        assert db_after is not None
        # Strong comparison: before/after must be identical for all mapping fields
        assert after_dict == before_dict, f"row silently mutated: before={before_dict} after={after_dict}"  # noqa: E501
        assert db_after.pack_version_id == before_db_pack
        assert db_after.revision == before_db_rev
        # Ensure new pack versions exist but mapping didn't jump
        all_pvs = s.scalars(select(CharacterPackVersion).where(CharacterPackVersion.character_id == char)).all()  # noqa: E501
        assert len(all_pvs) >= 3
        assert after.pack_version_id == pv_old
        # JSON serialization deterministic before/after
        assert json.dumps(before_dict, sort_keys=True) == json.dumps(after_dict, sort_keys=True)


# ── Scenario 8/9: explicit repin valid update + revision increments ─────


def test_explicit_repin_valid_update(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 8: explicit repin creates valid update (new pack, correct revision)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, f"repin8-{uuid.uuid4().hex[:6]}")
        s.commit()
        mid = rec.id
        rev = rec.revision

    pv_new = _create_new_pack_for_char(char, ws, version=10)
    with _sf() as s:
        repo = ProjectCastRepository(s)
        updated = repo.update_mapping(mid, ws, rev, pack_version_id=pv_new, character_id=char)
        s.commit()
        assert updated.id == mid
        assert updated.pack_version_id == pv_new
        assert updated.character_id == char
        assert updated.revision == rev + 1

        # Verify persisted
        fetched = repo.get_mapping(mid, ws)
        assert fetched.pack_version_id == pv_new
        assert fetched.revision == rev + 1


def test_revision_increments_correctly(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 9: revision increments correctly on each valid repin (1→2→3)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, f"rev9-{uuid.uuid4().hex[:6]}")
        s.commit()
        mid = rec.id
        assert rec.revision == 1

    pv2 = _create_new_pack_for_char(char, ws, version=20)
    with _sf() as s:
        repo = ProjectCastRepository(s)
        u1 = repo.update_mapping(mid, ws, 1, pack_version_id=pv2, character_id=char)
        s.commit()
        assert u1.revision == 2

    pv3 = _create_new_pack_for_char(char, ws, version=21)
    with _sf() as s:
        repo = ProjectCastRepository(s)
        u2 = repo.update_mapping(mid, ws, 2, pack_version_id=pv3, character_id=char)
        s.commit()
        assert u2.revision == 3

    # Final check: exact revision progression
    with _sf() as s:
        repo = ProjectCastRepository(s)
        final = repo.get_mapping(mid, ws)
        assert final.revision == 3
        assert final.pack_version_id == pv3

    # API level also increments: PATCH should return incremented revision
    proj2, role2, char2, pv2_old = _seed_one()
    created = client.post(
        "/api/v2/project-cast",
        json={
            "project_id": proj2,
            "object_role_id": role2,
            "character_id": char2,
            "pack_version_id": pv2_old,
            "idempotency_key": f"rev9-api-{uuid.uuid4().hex[:6]}",
        },
    )
    assert created.status_code == 201, created.text
    mid2 = created.json()["id"]
    rev2 = created.json()["revision"]
    assert rev2 == 1
    pv_new_api = _create_new_pack_for_char(char2, ws, version=22)
    upd_api = client.patch(
        f"/api/v2/project-cast/{mid2}",
        json={"revision": 1, "pack_version_id": pv_new_api, "character_id": char2},
    )
    assert upd_api.status_code == 200, upd_api.text
    assert upd_api.json()["revision"] == 2
    upd_api2 = client.patch(
        f"/api/v2/project-cast/{mid2}",
        json={"revision": 2, "pack_version_id": pv2_old, "character_id": char2},
    )
    assert upd_api2.status_code == 200, upd_api2.text
    assert upd_api2.json()["revision"] == 3


# ── Scenario 10/11: stale repin 409 zero mutation ───────────────────────


def test_stale_repin_returns_409(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 10: stale repin returns 409 (repo + API)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, f"stale10-{uuid.uuid4().hex[:6]}")  # noqa: E501
        s.commit()
        mid = rec.id

    pv_new = _create_new_pack_for_char(char, ws, version=30)
    # Valid repin to bump to rev 2
    with _sf() as s:
        repo = ProjectCastRepository(s)
        repo.update_mapping(mid, ws, 1, pack_version_id=pv_new, character_id=char)
        s.commit()

    # Stale repin with expected_revision=1 → 409
    with _sf() as s:
        repo = ProjectCastRepository(s)
        with pytest.raises(ProjectCastConflictError, match="stale revision"):
            repo.update_mapping(mid, ws, 1, pack_version_id=pv_old, character_id=char)
        s.rollback()

    # API stale also 409
    stale_api = client.patch(
        f"/api/v2/project-cast/{mid}",
        json={"revision": 1, "pack_version_id": pv_old, "character_id": char},
    )
    assert stale_api.status_code == 409, stale_api.text
    assert "stale" in stale_api.text.lower()


def test_stale_repin_zero_mutation(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 11: stale repin zero mutation (row unchanged after 409)."""
    proj, role, char, pv_old = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv_old, f"stale11-{uuid.uuid4().hex[:6]}")  # noqa: E501
        s.commit()
        mid = rec.id

    pv_new = _create_new_pack_for_char(char, ws, version=31)
    with _sf() as s:
        repo = ProjectCastRepository(s)
        _updated = repo.update_mapping(mid, ws, 1, pack_version_id=pv_new, character_id=char)  # noqa: F841
        s.commit()
        after_valid = repo.get_mapping(mid, ws)
        assert after_valid.revision == 2
        assert after_valid.pack_version_id == pv_new
        # Capture snapshot after valid update
        snapshot = {
            "pack_version_id": after_valid.pack_version_id,
            "revision": after_valid.revision,
            "character_id": after_valid.character_id,
        }

    # Stale attempt
    with _sf() as s:
        repo = ProjectCastRepository(s)
        try:
            repo.update_mapping(mid, ws, 1, pack_version_id=pv_old, character_id=char)
            s.commit()
            pytest.fail("expected 409")
        except ProjectCastConflictError:
            s.rollback()

    # Verify zero mutation
    with _sf() as s:
        repo = ProjectCastRepository(s)
        after_stale = repo.get_mapping(mid, ws)
        assert after_stale.pack_version_id == snapshot["pack_version_id"]
        assert after_stale.revision == snapshot["revision"]
        assert after_stale.character_id == snapshot["character_id"]

    # API stale zero mutation
    pv_old2 = pv_old  # try to revert via API with stale rev
    api_stale = client.patch(
        f"/api/v2/project-cast/{mid}",
        json={"revision": 1, "pack_version_id": pv_old2, "character_id": char},
    )
    assert api_stale.status_code == 409, api_stale.text
    with _sf() as s:
        repo = ProjectCastRepository(s)
        final = repo.get_mapping(mid, ws)
        assert final.revision == 2
        assert final.pack_version_id == pv_new


# ── Scenario 12: equivalent replay no duplicate ─────────────────────────


def test_equivalent_replay_no_duplicate(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 12: equivalent replay returns existing mapping, no duplicate, same revision."""
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"replay12-{uuid.uuid4().hex[:6]}"
    payload = {"project_id": proj, "object_role_id": role, "character_id": char, "pack_version_id": pv, "idempotency_key": key}  # noqa: E501

    # Repo level
    with _sf() as s:
        repo = ProjectCastRepository(s)
        r1, c1 = repo.create_mapping(ws, proj, role, char, pv, key)
        s.commit()
        assert c1 is True
        assert r1.revision == 1
        mid = r1.id
        r2, c2 = repo.create_mapping(ws, proj, role, char, pv, key)
        s.commit()
        assert c2 is False
        assert r2.id == mid
        assert r2.revision == 1
        # No duplicate: count still 1 for this project
        lst, total = repo.list_mappings(ws, project_id=proj)
        assert total == 1
        # API also: POST same payload → 200, same id
        r_api_1 = client.post("/api/v2/project-cast", json=payload)
        # This key already exists, so API should return 200 with same id (or 201 if new project? but we used same project so should be 200)  # noqa: E501
        # However our payload uses same key but repo already has it, so API will find existing and return 200  # noqa: E501
        assert r_api_1.status_code in (200, 201), r_api_1.text
        # Equivalent replay again via API
        r_api_2 = client.post("/api/v2/project-cast", json=payload)
        assert r_api_2.status_code == 200, r_api_2.text
        assert r_api_1.json()["id"] == r_api_2.json()["id"] == mid
        assert r_api_1.json()["revision"] == r_api_2.json()["revision"] == 1


# ── Scenario 13: conflicting replay fail closed ─────────────────────────


def test_conflicting_replay_fail_closed(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 13: conflicting replay (same key + different payload) fails closed, zero mutation."""  # noqa: E501
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"conflict13-{uuid.uuid4().hex[:6]}"
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv, key)
        s.commit()
        mid = rec.id
        before_rev = rec.revision
        before_pack = rec.pack_version_id

    # Different pack for same char → conflict
    pv_diff = _create_new_pack_for_char(char, ws, version=40)
    with _sf() as s:
        repo = ProjectCastRepository(s)
        with pytest.raises(ProjectCastConflictError):
            repo.create_mapping(ws, proj, role, char, pv_diff, key)
        s.rollback()
        # Verify zero mutation
        after = repo.get_mapping(mid, ws)
        assert after.revision == before_rev
        assert after.pack_version_id == before_pack
        assert after.id == mid

    # API conflicting replay also 409 (or 404 if ownership mismatch) and zero mutation
    # Try API with same key but different pack
    conflict_payload = {"project_id": proj, "object_role_id": role, "character_id": char, "pack_version_id": pv_diff, "idempotency_key": key}  # noqa: E501
    api_conflict = client.post("/api/v2/project-cast", json=conflict_payload)
    assert api_conflict.status_code == 409, api_conflict.text
    # Zero mutation still
    with _sf() as s:
        repo = ProjectCastRepository(s)
        final = repo.get_mapping(mid, ws)
        assert final.revision == before_rev
        assert final.pack_version_id == before_pack

    # Also test raw SQL: attempting to insert duplicate idempotency_key with same workspace should fail (DB enforcement)  # noqa: E501
    with _sf() as s:
        # Direct DB insert with same key but different pack should violate unique or trigger conflict via IntegrityError  # noqa: E501
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            s.execute(
                text(
                    "INSERT INTO project_cast_mapping(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,idempotency_key,revision) "  # noqa: E501
                    "VALUES (:id,:ws,:proj,:role,:char,:pv,:key,1)"
                ),
                {"id": str(uuid.uuid4()), "ws": ws, "proj": proj, "role": role, "char": char, "pv": pv_diff, "key": key},  # noqa: E501
            )
            s.commit()
        s.rollback()
        # Still zero mutation
        repo = ProjectCastRepository(s)
        check = repo.get_mapping(mid, ws)
        assert check.pack_version_id == before_pack


# ── Scenario 15: migration round-trip invariant ─────────────────────────


def test_migration_round_trip_preserves_invariant(tmp_path: Path) -> None:
    """Scenario 15: migration round-trip preserves version-isolation invariant.

    Proves: creating a mapping at HEAD, downgrading to PRE then upgrading again
    preserves the invariant that the mapping row still points to old pack_version_id
    and is not silently mutated (if mapping exists, downgrade refuses — we test
    the empty-graph round-trip plus the per-contract refusal path).

    For the invariant check we do:
      - Upgrade empty DB to HEAD
      - Create mapping pointing to pv_old
      - Snapshot row (exact IDs)
      - Downgrade should REFUSE (fail closed) because row exists → proves durability
      - Create separate empty DB and verify empty-graph upgrade→downgrade→upgrade
        is byte-identical (per S07-T01 migration contract)
    """
    from alembic import command
    from alembic.config import Config

    project_root = Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "alembic.ini"
    from alembic.script import ScriptDirectory

    heads = sorted(ScriptDirectory(str(project_root / "migrations")).get_heads())
    # S09-T00-I04: live head discovery (runtime contract); single-head guard.
    assert len(heads) == 1, f"expected exactly one Alembic head, got {heads}"
    head = heads[0]
    pre = "a0b1c2d3e4f5"

    def _cfg(db: Path) -> Config:
        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(project_root / "migrations"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
        return cfg

    # Part A: empty-graph round-trip is byte-identical (no mapping, should succeed)
    db_empty = tmp_path / "mig_empty.db"
    cfg_empty = _cfg(db_empty)
    command.upgrade(cfg_empty, "head")
    with create_engine_for_path(db_empty).connect() as conn:
        before_sig = {
            str(r[0]): str(r[1])
            for r in conn.execute(text("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).all()  # noqa: E501
        }
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head
    command.downgrade(cfg_empty, pre)
    with create_engine_for_path(db_empty).connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == pre
    command.upgrade(cfg_empty, "head")
    with create_engine_for_path(db_empty).connect() as conn:
        after_sig = {
            str(r[0]): str(r[1])
            for r in conn.execute(text("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).all()  # noqa: E501
        }
        assert after_sig == before_sig
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head
        # Integrity checks
        assert str(conn.execute(text("PRAGMA integrity_check")).scalar()) == "ok"
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []

    # Part B: with mapping present, downgrade must refuse atomically (fail closed) → invariant preserved  # noqa: E501
    db_with_row = tmp_path / "mig_with_row.db"
    cfg_row = _cfg(db_with_row)
    command.upgrade(cfg_row, "head")
    WS = "ws-mig-15"
    with create_engine_for_path(db_with_row).begin() as conn:
        conn.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        conn.execute(text("INSERT INTO project(id,workspace_id,name) VALUES ('p1',:w,'Proj')"), {"w": WS})  # noqa: E501
        conn.execute(text("INSERT INTO video_item(id,project_id,title,position) VALUES ('v1','p1','Vid',0)"))  # noqa: E501
        conn.execute(
            text("INSERT INTO scene(id,video_item_id,position,start_frame,end_frame,start_time_ms,end_time_ms,status) VALUES ('s1','v1',0,0,10,0,1000,'pending')")  # noqa: E501
        )
        conn.execute(
            text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,source_generation,name,kind,status) VALUES ('r1',:w,'p1','v1','1','Char','character','confirmed')"),  # noqa: E501
            {"w": WS},
        )
        conn.execute(text("INSERT INTO character(id,workspace_id,name,code) VALUES ('c1',:w,'Hero','hero')"), {"w": WS})  # noqa: E501
        conn.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES ('pv1','c1',:w,1,'published')"), {"w": WS})  # noqa: E501
        conn.execute(
            text("INSERT INTO project_cast_mapping(id,workspace_id,project_id,object_role_id,character_id,pack_version_id,idempotency_key,revision) VALUES ('m1',:w,'p1','r1','c1','pv1','k1',1)"),  # noqa: E501
            {"w": WS},
        )
    # Snapshot exact row before downgrade attempt
    with create_engine_for_path(db_with_row).connect() as conn:
        row_before = conn.execute(text("SELECT id,workspace_id,project_id,object_role_id,character_id,pack_version_id,revision FROM project_cast_mapping WHERE id='m1'")).first()  # noqa: E501
        assert row_before is not None
        assert row_before[5] == "pv1"  # pack_version_id
        assert row_before[6] == 1  # revision

    # Downgrade must refuse
    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        command.downgrade(cfg_row, pre)

    # S09-T00-I04: live runtime contract for the post-refusal position. The
    # refusal guard lives inside the S07 cast-mapping migration, so with
    # revisions merged above it the DB legitimately stops at the newest
    # revision at-or-below head that still guards — assert it is a REAL
    # revision on (pre, head], never pre and never an unknown revision.
    from alembic.script import ScriptDirectory

    _walk = {
        r.revision
        for r in ScriptDirectory(str(project_root / "migrations")).walk_revisions(
            base=pre, head=head
        )
    }
    _walk.discard(pre)
    with create_engine_for_path(db_with_row).connect() as conn:
        row_after = conn.execute(text("SELECT id,workspace_id,project_id,object_role_id,character_id,pack_version_id,revision FROM project_cast_mapping WHERE id='m1'")).first()  # noqa: E501
        assert row_after == row_before, "migration downgrade mutated row despite refusal"
        post_refusal = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        assert post_refusal is not None and post_refusal in _walk, (
            f"post-refusal revision {post_refusal!r} not on live chain (pre, {head}]"
        )
        assert str(conn.execute(text("PRAGMA integrity_check")).scalar()) == "ok"
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []

    # And we can still publish new pack version without mutating mapping (version isolation)
    with create_engine_for_path(db_with_row).begin() as conn:
        conn.execute(text("INSERT INTO character_pack_version(id,character_id,workspace_id,version,status) VALUES ('pv2','c1',:w,2,'published')"), {"w": WS})  # noqa: E501
    with create_engine_for_path(db_with_row).connect() as conn:
        row_final = conn.execute(text("SELECT pack_version_id, revision FROM project_cast_mapping WHERE id='m1'")).first()  # noqa: E501
        assert row_final is not None
        assert row_final[0] == "pv1"
        assert row_final[1] == 1

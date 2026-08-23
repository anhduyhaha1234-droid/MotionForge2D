"""S07-T03 Acceptance — Scenarios 14,16,17,18 (+ Scenario I end-to-end).

Scenarios:
 14. Restart/reopen DB does not lose mapping (fresh process)
 16. Picker shows correct pinned version
 17. Incompatible version blocked
 18. S06/S08 data not mutated
 19-20. Scenario I acceptance via API (desktop+390px covered by frontend specs;
        this file proves the same flow via production API)

Quality: real repository/API, exact ID/revision/row assertions,
restart = fresh process (subprocess + new engine on same temp DB file).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path, create_session_factory
from app.persistence.models import (
    Character,
    CharacterPackVersion,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.project_cast import ProjectCastNotFoundError, ProjectCastRepository


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
            sha256="a" * 64,
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
        proj = Project(workspace_id=ws, name=f"AccProj-{uuid.uuid4().hex[:6]}")
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
        char = Character(workspace_id=ws, name="CharAcc", code=f"ca_{uuid.uuid4().hex[:6]}")
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(
            character_id=char.id, workspace_id=ws, version=1, status="published"
        )
        s.add(pv)
        s.flush()
        # Add assets for picker completeness
        from app.persistence.models import Artifact, CharacterAsset

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
            art = Artifact(
                workspace_id=ws,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="c" * 64,
            )
            s.add(art)
            s.flush()
            asset = CharacterAsset(
                pack_version_id=pv.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id
            )  # noqa: E501
            s.add(asset)
        s.flush()
        s.commit()
        return proj.id, role.id, char.id, pv.id


# ── Scenario 14: restart/reopen no loss (fresh process) ─────────────────


def test_restart_reopen_db_no_loss_fresh_process(client: TestClient, tmp_path: Path) -> None:  # noqa: ARG001
    """Scenario 14: restart/reopen DB does not lose mapping (fresh process / new engine).

    We create a mapping in a dedicated temp DB file, then open the SAME file
    via a fresh engine (simulating process restart) and verify the row is
    byte-identical. Also tests subprocess fresh-process variant.
    """
    db_path = tmp_path / "restart_test.db"
    # Build a fresh DB via alembic upgrade
    from alembic import command
    from alembic.config import Config

    project_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")

    # Now create entities + mapping via this DB (fresh engine)
    engine1 = create_engine_for_path(db_path)
    factory1 = create_session_factory(engine1)
    ws = DEFAULT_WORKSPACE_ID
    # Seed via factory1
    with factory1() as s:
        _ensure_ws(s, ws)
        proj = Project(workspace_id=ws, name="RestartProj")
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
            name="HeroRestart",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=ws, name="CharRestart", code=f"cr_{uuid.uuid4().hex[:6]}")
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(
            character_id=char.id, workspace_id=ws, version=1, status="published"
        )  # noqa: E501
        s.add(pv)
        s.flush()
        from app.persistence.models import Artifact, CharacterAsset

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
            art = Artifact(
                workspace_id=ws,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="d" * 64,
            )
            s.add(art)
            s.flush()
            asset = CharacterAsset(
                pack_version_id=pv.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id
            )  # noqa: E501
            s.add(asset)
        s.flush()
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(
            ws, proj.id, role.id, char.id, pv.id, f"restart-{uuid.uuid4().hex[:6]}"
        )  # noqa: E501
        s.commit()
        mid = rec.id  # noqa: F841
        before_pack = rec.pack_version_id
        before_rev = rec.revision

    # Close engine1 (simulate process exit)
    engine1.dispose()

    # Fresh process: new engine pointing to SAME file
    engine2 = create_engine_for_path(db_path)
    factory2 = create_session_factory(engine2)
    with factory2() as s:
        repo = ProjectCastRepository(s)
        after = repo.get_mapping(mid, ws)
        assert after.id == mid
        assert after.pack_version_id == before_pack
        assert after.revision == before_rev
        assert after.workspace_id == ws

    # Also verify via raw SQL that row exists
    with engine2.connect() as conn:
        row = conn.execute(
            text("SELECT pack_version_id, revision FROM project_cast_mapping WHERE id=:mid"),
            {"mid": mid},
        ).first()  # noqa: E501
        assert row is not None
        assert row[0] == before_pack
        assert row[1] == before_rev
        assert str(conn.execute(text("PRAGMA integrity_check")).scalar()) == "ok"
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    engine2.dispose()

    # Subprocess fresh-process check: spawn a python subprocess that reads the DB
    subprocess_code = textwrap.dedent(
        f"""
        from pathlib import Path
        from sqlalchemy import text
        from app.persistence import create_engine_for_path
        db = Path(r"{db_path.as_posix()}")
        eng = create_engine_for_path(db)
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, pack_version_id, revision "
                    "FROM project_cast_mapping WHERE id=:mid"
                ),
                {{"mid": "{mid}"}},
            ).first()  # noqa: E501
            assert row is not None, "mapping not found in subprocess"
            assert row[1] == "{before_pack}", f"pack mismatch {{row[1]}} != {before_pack}"
            assert row[2] == {before_rev}, f"rev mismatch"
            print("SUBPROCESS_OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", subprocess_code],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"subprocess failed: stdout={result.stdout} stderr={result.stderr}"
    )  # noqa: E501
    assert "SUBPROCESS_OK" in result.stdout


# ── Scenario 16: picker shows correct pinned version ────────────────────


def test_picker_shows_correct_pinned_version(client: TestClient) -> None:
    """Scenario 16: picker shows correct pinned version (browse + compatibility pinned)."""
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    key = f"picker16-{uuid.uuid4().hex[:6]}"
    # Create mapping
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv, key)
        s.commit()
        mid = rec.id  # noqa: F841
    # Picker browse should contain this pack (published, workspace-isolated)
    picker = client.get("/api/v2/project-cast/picker/packs", params={"q": ""})
    assert picker.status_code == 200, picker.text
    body = picker.json()
    assert body["workspace_id"] == ws
    ids = {p["id"] for p in body["packs"]}
    assert pv in ids, f"picker packs missing pinned {pv}; got {ids}"

    # Search filter should also find it by character code/name
    # Get character to know code/name
    with _sf() as s:
        char_row = s.get(Character, char)
        assert char_row is not None
        code = char_row.code
    search = client.get("/api/v2/project-cast/picker/packs", params={"q": code[:4]})
    assert search.status_code == 200
    assert pv in {p["id"] for p in search.json()["packs"]}

    # Compatibility evaluate should show pinned_version_id
    compat = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role, "pack_version_id": pv, "mapping_id": mid},
    )
    assert compat.status_code == 200, compat.text
    cbody = compat.json()
    assert cbody["pinned_version_id"] == pv
    assert cbody["current_revision"] == 1
    assert cbody["workspace_id"] == ws

    # Also without mapping_id but with project+role, should surface pinned
    compat2 = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role, "pack_version_id": pv},
    )
    assert compat2.status_code == 200, compat2.text
    assert compat2.json()["pinned_version_id"] == pv

    # After repin to new pack, picker should still show both packs but compat pinned is new
    pv_new = None
    with _sf() as s:
        new_pv = CharacterPackVersion(
            character_id=char, workspace_id=ws, version=2, status="published"
        )  # noqa: E501
        s.add(new_pv)
        s.flush()
        _attach_core_pose_assets(s, ws, new_pv.id)
        s.commit()
        pv_new = new_pv.id
        # Need assets for new pack to be considered? picker only checks status=published, not assets
    # Repin via API
    upd = client.patch(
        f"/api/v2/project-cast/{mid}",
        json={"revision": 1, "pack_version_id": pv_new, "character_id": char},
    )  # noqa: E501
    assert upd.status_code == 200, upd.text
    assert upd.json()["pack_version_id"] == pv_new

    compat_after = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={
            "project_id": proj,
            "object_role_id": role,
            "pack_version_id": pv_new,
            "mapping_id": mid,
        },  # noqa: E501
    )
    assert compat_after.status_code == 200
    assert compat_after.json()["pinned_version_id"] == pv_new
    assert compat_after.json()["current_revision"] == 2


# ── Scenario 17: incompatible version blocked ───────────────────────────


def test_incompatible_version_blocked(client: TestClient) -> None:
    """Scenario 17: incompatible version blocked (compatibility evaluate blocked true, fail closed)."""  # noqa: E501
    proj, role, char, pv = _seed_one()
    ws = DEFAULT_WORKSPACE_ID
    # Create mapping first (compatible)
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv, f"incompat17-{uuid.uuid4().hex[:6]}")
        s.commit()
        mid = rec.id  # noqa: F841
    # Create an incompatible pack: change character_type to "other" and role is character -> should trigger missing_required_capability / object_kind_mismatch  # noqa: E501
    # Also test unpublished pack
    with _sf() as s:
        # Character of type "other" (incompatible with character role)
        char_other = Character(
            workspace_id=ws,
            name="OtherChar",
            code=f"oth_{uuid.uuid4().hex[:6]}",
            character_type="other",
        )  # noqa: E501
        s.add(char_other)
        s.flush()
        pv_unpublished = CharacterPackVersion(
            character_id=char_other.id, workspace_id=ws, version=1, status="draft"
        )
        s.add(pv_unpublished)
        s.commit()
        pv_other_id = pv_unpublished.id
        _char_other_id = char_other.id  # noqa: F841

        # Also a published pack with incompatible kind (character role vs prop? actually our _kind_compatible allows character->other is False for other char type? need trigger)  # noqa: E501
        # For deterministic test, we will test source_overlay refusal: create source_overlay role
        from app.persistence.models import ObjectRole

        vid2 = s.scalar(select(VideoItem).where(VideoItem.project_id == proj))
        assert vid2 is not None
        role_sov = ObjectRole(
            workspace_id=ws,
            project_id=proj,
            video_item_id=vid2.id,
            source_generation="1",
            name="Overlay",
            kind="source_overlay",
            status="confirmed",
        )
        s.add(role_sov)
        s.commit()
        role_sov_id = role_sov.id

    # Evaluate unpublished pack → should be blocked (unpublished_pack reason, no fallback)
    compat_unpub = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role, "pack_version_id": pv_other_id},
    )
    assert compat_unpub.status_code == 200, compat_unpub.text
    body_unpub = compat_unpub.json()
    assert body_unpub["compatible"] is False
    assert "unpublished_pack" in body_unpub["reasons"]
    assert body_unpub["blocked"] is True
    assert body_unpub["fallback_allowed"] is False

    # Evaluate source_overlay role → should be blocked (source_overlay_refusal)
    # Need a published pack to evaluate against source_overlay role
    with _sf() as s:
        # Reuse pv (published) but evaluate with source_overlay role
        pass
    compat_sov = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role_sov_id, "pack_version_id": pv},
    )
    assert compat_sov.status_code == 200, compat_sov.text
    body_sov = compat_sov.json()
    assert "source_overlay_refusal" in body_sov["reasons"]
    assert body_sov["blocked"] is True
    assert body_sov["fallback_allowed"] is False

    # Evaluate incompatible kind: create a new character of type "prop" and try to map to character role with strict check?  # noqa: E501
    # Actually _kind_compatible allows character<->character only; character role with prop char → mismatch  # noqa: E501
    with _sf() as s:
        char_prop = Character(
            workspace_id=ws,
            name="PropChar",
            code=f"prop_{uuid.uuid4().hex[:6]}",
            character_type="prop",
        )  # noqa: E501
        s.add(char_prop)
        s.flush()
        pv_prop = CharacterPackVersion(
            character_id=char_prop.id, workspace_id=ws, version=1, status="published"
        )  # noqa: E501
        s.add(pv_prop)
        # add assets
        from app.persistence.models import Artifact, CharacterAsset

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
            art = Artifact(
                workspace_id=ws,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="e" * 64,
            )
            s.add(art)
            s.flush()
            asset = CharacterAsset(
                pack_version_id=pv_prop.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id
            )  # noqa: E501
            s.add(asset)
        s.commit()
        pv_prop_id = pv_prop.id

    compat_kind = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role, "pack_version_id": pv_prop_id},
    )
    assert compat_kind.status_code == 200, compat_kind.text
    body_kind = compat_kind.json()
    # character role + prop char should be object_kind_mismatch (per _kind_compatible)
    assert "object_kind_mismatch" in body_kind["reasons"]
    assert body_kind["blocked"] is True

    # Verify that attempting to create mapping with incompatible data via repo is technically
    # allowed (persistence does not enforce compatibility) but compatibility says blocked.
    # The UI must not submit blocked; we prove the API layer does NOT silently fallback.
    # So the test expects that the frontend would disable submit when blocked.
    # Here we show that evaluate is deterministic and blocked remains blocked on repeat.
    compat_repeat = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role, "pack_version_id": pv_prop_id},
    )
    assert compat_repeat.json() == body_kind, "compatibility not deterministic"

    # CORRECTION C1/F5: strict incomplete-pack must be BLOCKED (compatible=false,
    # blocked=true, no fallback, and a direct API write must be rejected).
    # Create a truly incomplete pack: status draft (unpublished) + missing 2 poses
    # => incomplete_pack + unpublished_pack => blocked true
    with _sf() as s:
        char_inc2 = Character(
            workspace_id=ws,
            name="IncBlockedChar",
            code=f"incb_{uuid.uuid4().hex[:6]}",
            character_type="character",
        )  # noqa: E501
        s.add(char_inc2)
        s.flush()
        pv_inc_blocked = CharacterPackVersion(
            character_id=char_inc2.id, workspace_id=ws, version=1, status="draft"
        )  # noqa: E501
        s.add(pv_inc_blocked)
        s.flush()
        # Add only 4 assets (missing sitting/walking) to ensure incomplete_pack
        from app.persistence.models import Artifact, CharacterAsset

        for slot in ("front", "three_quarter", "side", "back"):
            art = Artifact(
                workspace_id=ws,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="f" * 64,
            )
            s.add(art)
            s.flush()
            asset = CharacterAsset(
                pack_version_id=pv_inc_blocked.id,
                workspace_id=ws,
                pose_slot=slot,
                artifact_id=art.id,
            )  # noqa: E501
            s.add(asset)
        s.commit()
        pv_inc_blocked_id = pv_inc_blocked.id
        char_inc2_id = char_inc2.id
        # Fresh role so the direct write below cannot hit the natural-unique
        # conflict before the compatibility gate.
        from app.persistence.models import ObjectRole

        vid_inc = s.scalar(select(VideoItem).where(VideoItem.project_id == proj))
        assert vid_inc is not None
        role_inc = ObjectRole(
            workspace_id=ws,
            project_id=proj,
            video_item_id=vid_inc.id,
            source_generation="1",
            name="IncBlockedRole",
            kind="character",
            status="confirmed",
        )
        s.add(role_inc)
        s.commit()
        role_inc_id = role_inc.id

    compat_inc_blocked = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={"project_id": proj, "object_role_id": role, "pack_version_id": pv_inc_blocked_id},
    )  # noqa: E501
    assert compat_inc_blocked.status_code == 200, compat_inc_blocked.text
    body_inc_blocked = compat_inc_blocked.json()
    assert body_inc_blocked["compatible"] is False, (
        f"incomplete blocked pack should be not compatible, got {body_inc_blocked}"
    )
    assert body_inc_blocked["blocked"] is True, (
        f"incomplete blocked pack should be blocked, got {body_inc_blocked}"
    )
    assert body_inc_blocked["fallback_allowed"] is False, (
        f"incomplete blocked should have no fallback, got {body_inc_blocked}"
    )
    assert "unpublished_pack" in body_inc_blocked["reasons"] or (
        "incomplete_pack" in body_inc_blocked["reasons"]
    )

    # Snapshot mapping state before the direct-write attempt (zero mutation proof)
    with _sf() as s:
        before = s.scalar(
            select(text("COUNT(*)"))
            .select_from(text("project_cast_mapping"))
            .where(text("pack_version_id=:pid")),
            {"pid": pv_inc_blocked_id},
        )  # type: ignore[arg-type]
        assert before == 0, f"blocked pack must have zero mappings before, got {before}"
        total_before = s.scalar(select(text("COUNT(*)")).select_from(text("project_cast_mapping")))  # type: ignore[arg-type]  # noqa: E501
        assert total_before is not None

    # Direct API write bypassing UI must ALSO be rejected by the backend
    # (compatibility gate is authoritative server-side, fail closed).
    direct_write = client.post(
        "/api/v2/project-cast",
        json={
            "project_id": proj,
            "object_role_id": role_inc_id,
            "character_id": char_inc2_id,
            "pack_version_id": pv_inc_blocked_id,
            "idempotency_key": f"incblocked-{uuid.uuid4().hex[:8]}",
        },
    )
    assert direct_write.status_code in (409, 422, 400), (
        f"direct write with incomplete/draft pack must be rejected, "
        f"got {direct_write.status_code}: {direct_write.text}"
    )

    # Zero unintended mutation after the rejected write
    with _sf() as s:
        after = s.scalar(
            select(text("COUNT(*)"))
            .select_from(text("project_cast_mapping"))
            .where(text("pack_version_id=:pid")),
            {"pid": pv_inc_blocked_id},
        )  # type: ignore[arg-type]
        assert after == 0, "zero mapping rows for incomplete-pack blocked case"
        total_after = s.scalar(select(text("COUNT(*)")).select_from(text("project_cast_mapping")))  # type: ignore[arg-type]  # noqa: E501
        assert total_after == total_before, "total mapping count changed after rejected write"


def test_s06_s08_data_not_mutated(client: TestClient) -> None:  # noqa: ARG001
    """Scenario 18: S06/S08 data not mutated by cast operations."""
    ws = DEFAULT_WORKSPACE_ID
    proj, role, char, pv = _seed_one(ws)

    # Snapshot S06 (character library) counts and a sample row
    with _sf() as s:
        char_before_count = s.scalar(select(text("COUNT(*)")).select_from(text("character")))  # type: ignore[arg-type]  # noqa: E501
        char_row_before = s.execute(
            text("SELECT id, name, code, character_type FROM character WHERE id=:cid"),
            {"cid": char},
        ).first()  # noqa: E501
        pv_before = s.execute(
            text(
                "SELECT id, character_id, version, status FROM character_pack_version WHERE id=:pid"
            ),
            {"pid": pv},
        ).first()  # noqa: E501
        asset_count_before = s.scalar(select(text("COUNT(*)")).select_from(text("character_asset")))  # type: ignore[arg-type]  # noqa: E501
        asset_rows_before = s.execute(
            text(
                "SELECT id, pack_version_id, workspace_id, pose_slot, artifact_id "
                "FROM character_asset WHERE pack_version_id=:pid ORDER BY id"
            ),
            {"pid": pv},
        ).all()
        # S08: ObjectRole counts
        role_before = s.execute(
            text("SELECT id, kind, source_generation FROM object_role WHERE id=:rid"), {"rid": role}
        ).first()  # noqa: E501
        role_count_before = s.scalar(select(text("COUNT(*)")).select_from(text("object_role")))  # type: ignore[arg-type]  # noqa: E501

    # Perform cast operations: create mapping, repin, stale fail, etc.
    with _sf() as s:
        repo = ProjectCastRepository(s)
        rec, _ = repo.create_mapping(ws, proj, role, char, pv, f"s06check-{uuid.uuid4().hex[:6]}")
        s.commit()
        mid = rec.id  # noqa: F841
        pv_new = CharacterPackVersion(
            character_id=char, workspace_id=ws, version=2, status="published"
        )  # noqa: E501
        s.add(pv_new)
        s.flush()
        _attach_core_pose_assets(s, ws, pv_new.id)
        s.commit()
        pv_new_id = pv_new.id
        repo = ProjectCastRepository(s)
        repo.update_mapping(mid, ws, 1, pack_version_id=pv_new_id, character_id=char)
        s.commit()
        # Try stale (should fail but not mutate)
        try:
            repo.update_mapping(mid, ws, 1, pack_version_id=pv, character_id=char)
            s.commit()
        except Exception:
            s.rollback()

    # Verify S06/S08 unchanged
    with _sf() as s:
        char_after_row = s.execute(
            text("SELECT id, name, code, character_type FROM character WHERE id=:cid"),
            {"cid": char},
        ).first()  # noqa: E501
        assert char_after_row == char_row_before, "S06 character row mutated"
        pv_after = s.execute(
            text(
                "SELECT id, character_id, version, status FROM character_pack_version WHERE id=:pid"
            ),
            {"pid": pv},
        ).first()  # noqa: E501
        assert pv_after == pv_before, "S06 pack_version row mutated"
        char_after_count = s.scalar(select(text("COUNT(*)")).select_from(text("character")))  # type: ignore[arg-type]  # noqa: E501
        # Count should be +1 for the new pv we created (pv_new) but character count unchanged
        assert char_after_count == char_before_count, "character count changed unexpectedly"
        # Asset rows: only the +6 CORE_POSE assets of pv_new are new; every asset
        # of the ORIGINAL pack (and its artifacts) must be untouched. Verify the
        # original pack's asset rows byte-identical instead of a global count.
        orig_assets_after = s.execute(
            text(
                "SELECT id, pack_version_id, workspace_id, pose_slot, artifact_id "
                "FROM character_asset WHERE pack_version_id=:pid ORDER BY id"
            ),
            {"pid": pv},
        ).all()
        assert sorted(orig_assets_after) == sorted(
            tuple(a) for a in asset_rows_before
        ), "original pack's asset rows mutated"
        asset_count_after = s.scalar(select(text("COUNT(*)")).select_from(text("character_asset")))  # type: ignore[arg-type]  # noqa: E501
        from app.persistence.models import CORE_POSE_SLOTS

        assert asset_count_after == asset_count_before + len(CORE_POSE_SLOTS), (
            f"unexpected asset mutation: {asset_count_before} -> {asset_count_after} "
            "(only +6 core-pose rows for the new published pack allowed)"
        )
        role_after = s.execute(
            text("SELECT id, kind, source_generation FROM object_role WHERE id=:rid"), {"rid": role}
        ).first()  # noqa: E501
        assert role_after == role_before, "S08 ObjectRole mutated"
        role_count_after = s.scalar(select(text("COUNT(*)")).select_from(text("object_role")))  # type: ignore[arg-type]  # noqa: E501
        assert role_count_after == role_count_before, "ObjectRole count changed"


# ── Scenario I end-to-end (API acceptance, complements frontend 19/20) ─────


def test_scenario_i_end_to_end_acceptance(client: TestClient) -> None:
    """Scenario I acceptance via API (covers desktop+390px flow without browser).

    Flow:
      - One pack version reused across 2 projects (independent)
      - Publish new version does not mutate old
      - Explicit repin increments revision
      - Stale 409 zero mutation
      - Picker shows pinned, incompatible blocked
      - Workspace isolation holds throughout
    """
    # Use shared pack helper via seeding
    ws = DEFAULT_WORKSPACE_ID
    with _sf() as s:
        _ensure_ws(s, ws)
        # Shared character+pack
        shared_char = Character(
            workspace_id=ws, name="ScenarioHero", code=f"sce_{uuid.uuid4().hex[:6]}"
        )  # noqa: E501
        s.add(shared_char)
        s.flush()
        shared_pv = CharacterPackVersion(
            character_id=shared_char.id, workspace_id=ws, version=1, status="published"
        )  # noqa: E501
        s.add(shared_pv)
        s.flush()
        from app.persistence.models import Artifact, CharacterAsset

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):
            art = Artifact(
                workspace_id=ws,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="1" * 64,
            )
            s.add(art)
            s.flush()
            s.add(
                CharacterAsset(
                    pack_version_id=shared_pv.id,
                    workspace_id=ws,
                    pose_slot=slot,
                    artifact_id=art.id,
                )
            )  # noqa: E501
        s.flush()
        # Two projects
        proj1 = Project(workspace_id=ws, name="ScenarioProj1")
        proj2 = Project(workspace_id=ws, name="ScenarioProj2")
        s.add_all([proj1, proj2])
        s.flush()
        for proj in (proj1, proj2):
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
                status="pending",  # noqa: E501
            )
            s.add(scene)
            s.flush()
            from app.persistence.models import ObjectRole

            role = ObjectRole(
                workspace_id=ws,
                project_id=proj.id,
                video_item_id=vid.id,
                source_generation="1",
                name=f"Hero-{proj.name}",
                kind="character",
                status="confirmed",  # noqa: E501
            )
            s.add(role)
            s.flush()
        s.commit()
        # Collect ids
        proj1_id = proj1.id
        proj2_id = proj2.id
        shared_char_id = shared_char.id
        shared_pv_id = shared_pv.id
        role1_id = s.scalar(
            select(text("id")).select_from(text("object_role")).where(text("project_id=:pid")),
            {"pid": proj1_id},
        )  # type: ignore[arg-type]  # noqa: E501
        role2_id = s.scalar(
            select(text("id")).select_from(text("object_role")).where(text("project_id=:pid")),
            {"pid": proj2_id},
        )  # type: ignore[arg-type]  # noqa: E501
        # Need to re-query because scalar with text may not work; use ORM
        from app.persistence.models import ObjectRole

        role1_id = s.scalars(select(ObjectRole).where(ObjectRole.project_id == proj1_id)).first().id  # type: ignore[union-attr]  # noqa: E501
        role2_id = s.scalars(select(ObjectRole).where(ObjectRole.project_id == proj2_id)).first().id  # type: ignore[union-attr]  # noqa: E501

    # Step 1: create mapping for proj1
    r1 = client.post(
        "/api/v2/project-cast",
        json={
            "project_id": proj1_id,
            "object_role_id": role1_id,
            "character_id": shared_char_id,
            "pack_version_id": shared_pv_id,
            "idempotency_key": f"sce1-{uuid.uuid4().hex[:6]}",
        },
    )
    assert r1.status_code == 201, r1.text
    mid1 = r1.json()["id"]
    assert r1.json()["pack_version_id"] == shared_pv_id
    assert r1.json()["revision"] == 1

    # Step 2: reuse same pack for proj2 (cross-project)
    r2 = client.post(
        "/api/v2/project-cast",
        json={
            "project_id": proj2_id,
            "object_role_id": role2_id,
            "character_id": shared_char_id,
            "pack_version_id": shared_pv_id,
            "idempotency_key": f"sce2-{uuid.uuid4().hex[:6]}",
        },
    )
    assert r2.status_code == 201, r2.text
    mid2 = r2.json()["id"]
    assert r2.json()["pack_version_id"] == shared_pv_id
    assert mid1 != mid2

    # Step 3: picker shows packs and pinned
    picker = client.get("/api/v2/project-cast/picker/packs")
    assert picker.status_code == 200
    assert shared_pv_id in {p["id"] for p in picker.json()["packs"]}
    compat = client.post(
        "/api/v2/project-cast/compatibility/evaluate",
        json={
            "project_id": proj1_id,
            "object_role_id": role1_id,
            "pack_version_id": shared_pv_id,
            "mapping_id": mid1,
        },  # noqa: E501
    )
    assert compat.status_code == 200
    assert compat.json()["pinned_version_id"] == shared_pv_id

    # Step 4: publish new version → old mapping unchanged
    with _sf() as s:
        new_pv = CharacterPackVersion(
            character_id=shared_char_id, workspace_id=ws, version=2, status="published"
        )  # noqa: E501
        s.add(new_pv)
        s.flush()
        _attach_core_pose_assets(s, ws, new_pv.id)
        s.commit()
        new_pv_id = new_pv.id
    get1 = client.get(f"/api/v2/project-cast/{mid1}")
    assert get1.status_code == 200
    assert get1.json()["pack_version_id"] == shared_pv_id
    assert get1.json()["revision"] == 1
    get2 = client.get(f"/api/v2/project-cast/{mid2}")
    assert get2.json()["pack_version_id"] == shared_pv_id

    # Step 5: explicit repin proj1 → new version
    upd = client.patch(
        f"/api/v2/project-cast/{mid1}",
        json={"revision": 1, "pack_version_id": new_pv_id, "character_id": shared_char_id},
    )  # noqa: E501
    assert upd.status_code == 200, upd.text
    assert upd.json()["revision"] == 2
    assert upd.json()["pack_version_id"] == new_pv_id
    # proj2 still old
    get2_after = client.get(f"/api/v2/project-cast/{mid2}")
    assert get2_after.json()["pack_version_id"] == shared_pv_id
    assert get2_after.json()["revision"] == 1

    # Step 6: stale repin 409 zero mutation
    stale = client.patch(
        f"/api/v2/project-cast/{mid1}",
        json={"revision": 1, "pack_version_id": shared_pv_id, "character_id": shared_char_id},
    )  # noqa: E501
    assert stale.status_code == 409, stale.text
    get1_after_stale = client.get(f"/api/v2/project-cast/{mid1}")
    assert get1_after_stale.json()["revision"] == 2
    assert get1_after_stale.json()["pack_version_id"] == new_pv_id

    # Step 7: workspace isolation still holds (already proven, quick check)
    other_ws = f"ws-sce-other-{uuid.uuid4().hex[:6]}"
    # Create other workspace mapping via direct repo
    with _sf() as s:
        _ensure_ws(s, other_ws)
        proj_o = Project(workspace_id=other_ws, name="OtherProj")
        s.add(proj_o)
        s.flush()
        vid_o = VideoItem(project_id=proj_o.id, title="Vid", position=0)
        s.add(vid_o)
        s.flush()
        scene_o = Scene(
            video_item_id=vid_o.id,
            position=0,
            start_frame=0,
            end_frame=10,
            start_time_ms=0,
            end_time_ms=1000,
            status="pending",
        )  # noqa: E501
        s.add(scene_o)
        s.flush()
        from app.persistence.models import ObjectRole

        role_o = ObjectRole(
            workspace_id=other_ws,
            project_id=proj_o.id,
            video_item_id=vid_o.id,
            source_generation="1",
            name="OtherHero",
            kind="character",
            status="confirmed",  # noqa: E501
        )
        s.add(role_o)
        s.flush()
        char_o = Character(
            workspace_id=other_ws, name="OtherChar", code=f"oc_{uuid.uuid4().hex[:6]}"
        )  # noqa: E501
        s.add(char_o)
        s.flush()
        pv_o = CharacterPackVersion(
            character_id=char_o.id, workspace_id=other_ws, version=1, status="published"
        )  # noqa: E501
        s.add(pv_o)
        s.flush()
        _attach_core_pose_assets(s, other_ws, pv_o.id)
        s.commit()
        repo = ProjectCastRepository(s)
        rec_o, _ = repo.create_mapping(
            other_ws, proj_o.id, role_o.id, char_o.id, pv_o.id, f"sce-other-{uuid.uuid4().hex[:6]}"
        )  # noqa: E501
        s.commit()
        mid_o = rec_o.id
    # Ensure mid_o not visible in default workspace
    all_default = client.get("/api/v2/project-cast")
    assert all_default.status_code == 200
    assert mid_o not in {m["id"] for m in all_default.json()["mappings"]}
    # Direct repo check: default cannot read other
    with _sf() as s:
        repo = ProjectCastRepository(s)
        with pytest.raises(ProjectCastNotFoundError):  # noqa: B017
            repo.get_mapping(mid_o, ws)

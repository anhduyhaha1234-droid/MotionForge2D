from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path
from app.persistence.models import (
    Artifact,
    Character,
    Job,
    ObjectOccurrence,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
    OccurrenceConflictError,
    OccurrenceNotFoundError,
    OwnershipMismatchError,
    RoleConflictError,
    RoleNotFoundError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _alembic_config(path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return config


def _upgrade_to_head(path: Path) -> None:
    command.upgrade(_alembic_config(path), "head")


def _upgrade_to_revision(path: Path, revision: str) -> None:
    command.upgrade(_alembic_config(path), revision)


def _session() -> Session:
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _seed_ownership(session: Session) -> tuple[str, str, str, str]:
    workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
    project = Project(workspace_id=workspace.id, name="Objects")
    video = VideoItem(project=project, title="Primary", position=0)
    scene = Scene(
        video_item=video,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    other_video = VideoItem(project=project, title="Other", position=1)
    other_scene = Scene(
        video_item=other_video,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    session.add_all([workspace, project, video, scene, other_video, other_scene])
    session.commit()
    return project.id, video.id, scene.id, other_scene.id


def _role(
    repo: ObjectIntelligenceRepository, ids: tuple[str, str, str, str], key: str | None = None
):
    project_id, video_id, _, _ = ids
    return repo.create_role(
        DEFAULT_WORKSPACE_ID, project_id, video_id, "1", "Hero", idempotency_key=key
    )


def test_migration_round_trip_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    config = _alembic_config(db)
    command.upgrade(config, "head")
    assert {"object_role", "object_occurrence"} <= set(
        inspect(create_engine_for_path(db)).get_table_names()
    )
    command.downgrade(config, "d5e6f7a8b9c0")
    assert not {"object_role", "object_occurrence"} & set(
        inspect(create_engine_for_path(db)).get_table_names()
    )
    command.upgrade(config, "head")
    assert {"object_role", "object_occurrence"} <= set(
        inspect(create_engine_for_path(db)).get_table_names()
    )


def test_existing_database_upgrade_preserves_rows(tmp_path: Path) -> None:
    db = tmp_path / "preserve.db"
    _upgrade_to_revision(db, "d5e6f7a8b9c0")
    engine = create_engine_for_path(db)
    with Session(engine) as session:
        ids = _seed_ownership(session)
        character = Character(workspace_id=DEFAULT_WORKSPACE_ID, name="C", code="c")
        session.add(character)
        session.commit()
        snapshot = (ids, character.id)
    _upgrade_to_head(db)
    with Session(engine) as session:
        assert session.get(Character, snapshot[1]) is not None
        heads = sorted(ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads())
        # S09-T00-I04: live runtime contract; single-head guard (stricter).
        assert len(heads) == 1, f"expected exactly one Alembic head, got {heads}"
        assert (
            session.execute(text("select version_num from alembic_version")).scalar()
            == heads[0]
        )


def test_head_tables_and_constraints_enforced(tmp_path: Path) -> None:
    db = tmp_path / "constraints.db"
    _upgrade_to_head(db)
    with Session(create_engine_for_path(db)) as session:
        ids = _seed_ownership(session)
        role, _ = _role(ObjectIntelligenceRepository(session), ids)
        session.commit()
        session.add(
            ObjectOccurrence(
                workspace_id=DEFAULT_WORKSPACE_ID,
                project_id=ids[0],
                video_item_id=ids[1],
                role_id=role.id,
                scene_id=ids[2],
                frame_index=0,
                time_ms=0,
                bbox_x=0,
                bbox_y=0,
                bbox_w=1,
                bbox_h=1,
                confidence=1.5,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_create_role_stable_uuid_and_defaults(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        role, created = _role(ObjectIntelligenceRepository(session), ids)
        assert created and uuid.UUID(role.id).version == 4
        assert (role.status, role.kind, role.revision) == ("suggested", "character", 1)
        assert role.created_at and role.updated_at


def test_cross_owner_project_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        other = Workspace(name="other")
        project = Project(workspace=other, name="foreign")
        session.add_all([other, project])
        session.commit()
        with pytest.raises(OwnershipMismatchError):
            ObjectIntelligenceRepository(session).create_role(
                DEFAULT_WORKSPACE_ID, project.id, ids[1], "1", "x"
            )


def test_cross_owner_scene_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        with pytest.raises(OwnershipMismatchError):
            repo.create_occurrence(
                DEFAULT_WORKSPACE_ID,
                role.id,
                ids[3],
                0,
                0,
                bbox_x=0,
                bbox_y=0,
                bbox_w=1,
                bbox_h=1,
                confidence=1,
            )


def test_role_cas_stale_revision_conflict(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        repo.update_role(DEFAULT_WORKSPACE_ID, role.id, 1, name="new")
        with pytest.raises(RoleConflictError):
            repo.update_role(DEFAULT_WORKSPACE_ID, role.id, 1, name="stale")


def test_role_cas_success_bumps_revision(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        assert repo.update_role(DEFAULT_WORKSPACE_ID, role.id, 1, name="new").revision == 2


def test_status_transitions(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        first, _ = _role(repo, ids)
        # The supersession target must share the SAME source generation
        # (F2 correction): the second role uses the same "1" generation.
        second, _ = repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "two")
        confirmed = repo.update_role(DEFAULT_WORKSPACE_ID, first.id, 1, status="confirmed")
        done = repo.update_role(
            DEFAULT_WORKSPACE_ID, confirmed.id, 2, status="superseded", supersedes_role_id=second.id
        )
        with pytest.raises(RoleConflictError):
            repo.update_role(DEFAULT_WORKSPACE_ID, done.id, 3, name="no")


def test_idempotent_create_role_same_key(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        one, _ = _role(repo, ids, "same")
        two, created = _role(repo, ids, "same")
        assert one.id == two.id and not created


def test_idempotent_create_occurrence_natural_key(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        args = dict(bbox_x=0, bbox_y=0, bbox_w=1, bbox_h=1, confidence=0.5)
        one, _ = repo.create_occurrence(DEFAULT_WORKSPACE_ID, role.id, ids[2], 1, 10, **args)
        two, created = repo.create_occurrence(DEFAULT_WORKSPACE_ID, role.id, ids[2], 1, 10, **args)
        assert one.id == two.id and not created


def test_concurrent_create_same_idempotency_key_single_row(client: TestClient) -> None:
    with _session() as seed:
        ids = _seed_ownership(seed)
    with _session() as a:
        first, _ = _role(ObjectIntelligenceRepository(a), ids, "concurrent")
        a.commit()
    with _session() as b:
        second, created = _role(ObjectIntelligenceRepository(b), ids, "concurrent")
        assert second.id == first.id and not created


def test_concurrent_update_cas_last_writer_wins_conflict(client: TestClient) -> None:
    with _session() as seed:
        ids = _seed_ownership(seed)
        role, _ = _role(ObjectIntelligenceRepository(seed), ids)
        seed.commit()
    with _session() as a:
        ObjectIntelligenceRepository(a).update_role(DEFAULT_WORKSPACE_ID, role.id, 1, name="a")
        a.commit()
    with _session() as b:
        repo = ObjectIntelligenceRepository(b)
        with pytest.raises(RoleConflictError):
            repo.update_role(DEFAULT_WORKSPACE_ID, role.id, 1, name="b")
        assert repo.update_role(DEFAULT_WORKSPACE_ID, role.id, 2, name="b").revision == 3


def test_get_operations_zero_durable_mutations(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        session.commit()
        before = session.scalar(select(ObjectRole.revision).where(ObjectRole.id == role.id))
        repo.get_role(DEFAULT_WORKSPACE_ID, role.id)
        repo.list_roles(DEFAULT_WORKSPACE_ID)
        repo.list_occurrences(DEFAULT_WORKSPACE_ID, role.id)
        assert session.scalar(select(ObjectRole.revision).where(ObjectRole.id == role.id)) == before


def test_legacy_mapping_pure_read_only(client: TestClient) -> None:
    data = {
        "objects": [
            {
                "object_id": "o",
                "name": "",
                "kind": "weird",
                "scene_id": 2,
                "selection": {"frame_index": 3, "x": 1, "y": 2, "width": 3, "height": 4},
            }
        ]
    }
    with _session() as session:
        mapping = ObjectIntelligenceRepository(session).map_legacy_objects("p", data)
        assert uuid.UUID(mapping.mapped_objects[0].ephemeral_role_id).version == 4
        assert mapping.mapped_objects[0].suggested_name == "Vật thể"


def _api_seed() -> tuple[str, str, str, str]:
    with _session() as session:
        return _seed_ownership(session)


def _api_role(client: TestClient, ids: tuple[str, str, str, str], key: str | None = None):
    return client.post(
        "/api/v2/object-intelligence/roles",
        json={
            "project_id": ids[0],
            "video_item_id": ids[1],
            "source_generation": "1",
            "name": "Hero",
            "idempotency_key": key,
        },
    )


def test_api_role_crud_and_cas(client: TestClient) -> None:
    ids = _api_seed()
    created = _api_role(client, ids)
    assert created.status_code == 201
    role = created.json()
    assert client.get(f"/api/v2/object-intelligence/roles/{role['id']}").status_code == 200
    assert client.get("/api/v2/object-intelligence/roles").json()["total"] == 1
    assert (
        client.patch(
            f"/api/v2/object-intelligence/roles/{role['id']}", json={"revision": 9, "name": "x"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v2/object-intelligence/roles/{role['id']}", json={"revision": 1, "name": "x"}
        ).json()["revision"]
        == 2
    )


def test_api_idempotent_role_create(client: TestClient) -> None:
    ids = _api_seed()
    one = _api_role(client, ids, "api-key")
    two = _api_role(client, ids, "api-key")
    assert (one.status_code, two.status_code, one.json()["id"]) == (201, 200, two.json()["id"])


def test_api_occurrence_idempotent(client: TestClient) -> None:
    ids = _api_seed()
    role = _api_role(client, ids).json()
    url = f"/api/v2/object-intelligence/roles/{role['id']}/occurrences"
    body = {
        "scene_id": ids[2],
        "frame_index": 1,
        "time_ms": 10,
        "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
        "confidence": 0.5,
    }
    one = client.post(url, json=body)
    two = client.post(url, json=body)
    assert (one.status_code, two.status_code, one.json()["id"]) == (201, 200, two.json()["id"])
    assert len(client.get(url).json()) == 1


def test_api_cross_owner_fail_closed(client: TestClient) -> None:
    ids = _api_seed()
    role = _api_role(client, ids).json()
    response = client.post(
        f"/api/v2/object-intelligence/roles/{role['id']}/occurrences",
        json={
            "scene_id": ids[3],
            "frame_index": 0,
            "time_ms": 0,
            "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
            "confidence": 1,
        },
    )
    assert response.status_code == 409


def test_api_get_endpoints_zero_durable_mutations(client: TestClient) -> None:
    ids = _api_seed()
    role = _api_role(client, ids).json()
    with _session() as session:
        before = session.scalar(select(ObjectRole.revision))
    client.get("/api/v2/object-intelligence/roles")
    client.get(f"/api/v2/object-intelligence/roles/{role['id']}")
    with _session() as session:
        assert session.scalar(select(ObjectRole.revision)) == before


def test_api_legacy_mapping_read_only(client: TestClient, sample_project_data: dict) -> None:
    project_id = "legacy-map"
    root = deps._config.project_root / "projects" / project_id
    root.mkdir(parents=True)
    sample_project_data["objects"] = [
        {
            "object_id": "o1",
            "name": "One",
            "kind": "character",
            "scene_id": 0,
            "selection": {
                "mode": "bounding_box",
                "frame_index": 0,
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
            },
        },
        {
            "object_id": "o2",
            "name": "Two",
            "kind": "prop",
            "scene_id": 1,
            "selection": {
                "mode": "bounding_box",
                "frame_index": 1,
                "x": 1,
                "y": 1,
                "width": 2,
                "height": 2,
            },
        },
    ]
    path = root / "project.json"
    path.write_text(json.dumps(sample_project_data), encoding="utf-8")
    before = path.read_bytes()
    response = client.get(f"/api/v2/object-intelligence/legacy-mapping/{project_id}")
    assert response.status_code == 200 and len(response.json()["mapped_objects"]) == 2
    assert "read-only" in response.json()["note"].lower() and path.read_bytes() == before


# ── CORRECTION ROUND (Codex CHANGES_REQUESTED, findings 1-4) ───────────────


def _seed_other_workspace(session: Session) -> tuple[str, str, str, str]:
    """(workspace_id, project_id, video_id, scene_id) in a foreign workspace."""
    ws = Workspace(name="other-ws")
    session.add(ws)
    session.flush()
    project = Project(workspace_id=ws.id, name="Foreign Project")
    session.add(project)
    session.flush()
    video = VideoItem(project_id=project.id, title="Foreign Video", position=0)
    session.add(video)
    session.flush()
    scene = Scene(
        video_item_id=video.id,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    session.add(scene)
    session.commit()
    return ws.id, project.id, video.id, scene.id


def _seed_second_project_video(session: Session, workspace_id: str) -> tuple[str, str]:
    """A second project + video inside the SAME workspace."""
    project = Project(workspace_id=workspace_id, name="Second Project")
    session.add(project)
    session.flush()
    video = VideoItem(project_id=project.id, title="Second Video", position=0)
    session.add(video)
    session.flush()
    session.commit()
    return project.id, video.id


# ── F1: occurrence route ownership (fail closed) ───────────────────────────


def test_occurrence_role_mismatch_read_fails_closed(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role_a, _ = _role(repo, ids)
        role_b, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "B"
        )
        occ_a, _ = repo.create_occurrence(
            DEFAULT_WORKSPACE_ID,
            role_a.id,
            ids[2],
            1,
            10,
            bbox_x=0,
            bbox_y=0,
            bbox_w=1,
            bbox_h=1,
            confidence=0.5,
        )
        # The correct role reads fine...
        assert (
            repo.get_occurrence(DEFAULT_WORKSPACE_ID, role_a.id, occ_a.id).id == occ_a.id
        )
        # ...but a role-B read of a role-A occurrence fails closed (not-found).
        with pytest.raises(OccurrenceNotFoundError):
            repo.get_occurrence(DEFAULT_WORKSPACE_ID, role_b.id, occ_a.id)


def test_occurrence_role_mismatch_update_fails_closed(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role_a, _ = _role(repo, ids)
        role_b, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "B"
        )
        occ_a, _ = repo.create_occurrence(
            DEFAULT_WORKSPACE_ID,
            role_a.id,
            ids[2],
            1,
            10,
            bbox_x=0,
            bbox_y=0,
            bbox_w=1,
            bbox_h=1,
            confidence=0.5,
        )
        # Correct role: update succeeds and bumps the revision.
        updated = repo.update_occurrence(
            DEFAULT_WORKSPACE_ID, role_a.id, occ_a.id, 1, confidence=0.9
        )
        assert updated.revision == 2
        # Wrong role: fail closed, never update, never leak existence.
        with pytest.raises(OccurrenceNotFoundError):
            repo.update_occurrence(
                DEFAULT_WORKSPACE_ID, role_b.id, occ_a.id, 2, confidence=0.1
            )
        assert (
            repo.get_occurrence(DEFAULT_WORKSPACE_ID, role_a.id, occ_a.id).confidence
            == 0.9
        )


def test_api_role_a_url_cannot_read_or_update_role_b_occurrence(
    client: TestClient,
) -> None:
    ids = _api_seed()
    role_a = _api_role(client, ids).json()
    role_b = client.post(
        "/api/v2/object-intelligence/roles",
        json={
            "project_id": ids[0],
            "video_item_id": ids[1],
            "source_generation": "1",
            "name": "B",
        },
    ).json()
    body = {
        "scene_id": ids[2],
        "frame_index": 1,
        "time_ms": 10,
        "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
        "confidence": 0.5,
    }
    occ = client.post(
        f"/api/v2/object-intelligence/roles/{role_a['id']}/occurrences", json=body
    )
    assert occ.status_code == 201
    occ_id = occ.json()["id"]
    # Read via the role-B list must NOT include role-A's occurrence.
    list_b = client.get(
        f"/api/v2/object-intelligence/roles/{role_b['id']}/occurrences"
    ).json()
    assert all(o["id"] != occ_id for o in list_b)
    # Update via the role-B URL targeting role-A's occurrence -> fail closed 404.
    patch = client.patch(
        f"/api/v2/object-intelligence/roles/{role_b['id']}/occurrences/{occ_id}",
        json={"revision": 1, "confidence": 0.1},
    )
    assert patch.status_code == 404
    # The occurrence is untouched.
    list_a = client.get(
        f"/api/v2/object-intelligence/roles/{role_a['id']}/occurrences"
    ).json()
    assert list_a[0]["id"] == occ_id and list_a[0]["confidence"] == 0.5


# ── F2: supersession target validation ─────────────────────────────────────


def test_supersession_cross_workspace_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        other_ws, other_project, other_video, _ = _seed_other_workspace(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        foreign, _ = repo.create_role(
            other_ws, other_project, other_video, "1", "Foreign"
        )
        with pytest.raises(RoleConflictError):
            repo.update_role(
                DEFAULT_WORKSPACE_ID,
                role.id,
                1,
                status="superseded",
                supersedes_role_id=foreign.id,
            )


def test_supersession_cross_project_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        p2, v2 = _seed_second_project_video(session, DEFAULT_WORKSPACE_ID)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        other, _ = repo.create_role(DEFAULT_WORKSPACE_ID, p2, v2, "1", "Other")
        with pytest.raises(RoleConflictError):
            repo.update_role(
                DEFAULT_WORKSPACE_ID,
                role.id,
                1,
                status="superseded",
                supersedes_role_id=other.id,
            )


def test_supersession_cross_video_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        v2 = VideoItem(project_id=ids[0], title="Other Video", position=2)
        session.add(v2)
        session.flush()
        session.commit()
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        other, _ = repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], v2.id, "1", "Other")
        with pytest.raises(RoleConflictError):
            repo.update_role(
                DEFAULT_WORKSPACE_ID,
                role.id,
                1,
                status="superseded",
                supersedes_role_id=other.id,
            )


def test_supersession_cross_generation_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        other, _ = repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "2", "Other")
        with pytest.raises(RoleConflictError):
            repo.update_role(
                DEFAULT_WORKSPACE_ID,
                role.id,
                1,
                status="superseded",
                supersedes_role_id=other.id,
            )


def test_supersession_self_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        with pytest.raises(RoleConflictError):
            repo.update_role(
                DEFAULT_WORKSPACE_ID,
                role.id,
                1,
                status="superseded",
                supersedes_role_id=role.id,
            )


def test_supersession_terminal_target_rejected(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        _role(repo, ids)
        target, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "Target"
        )
        successor, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "Successor"
        )
        third, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "Third"
        )
        # target becomes terminal (superseded by successor)...
        repo.update_role(
            DEFAULT_WORKSPACE_ID,
            target.id,
            1,
            status="superseded",
            supersedes_role_id=successor.id,
        )
        # ...so it can no longer be a supersession target for anyone.
        with pytest.raises(RoleConflictError):
            repo.update_role(
                DEFAULT_WORKSPACE_ID,
                third.id,
                1,
                status="superseded",
                supersedes_role_id=target.id,
            )
        # The already-superseded role itself is terminal too.
        with pytest.raises(RoleConflictError):
            repo.update_role(DEFAULT_WORKSPACE_ID, target.id, 2, name="no")


# ── F3: genuinely concurrent atomic CAS ────────────────────────────────────


def test_concurrent_cas_atomic_exactly_one_writer_wins(client: TestClient) -> None:
    service = deps._job_service
    assert service is not None
    db_url = str(service._session_factory.kw["bind"].url)
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        session.commit()
        role_id = role.id

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def writer() -> None:
        engine = create_engine_for_path(db_url)
        with Session(engine) as s:
            # Both writers begin with the SAME committed revision (1).
            loaded = s.get(ObjectRole, role_id)
            assert loaded is not None and loaded.revision == 1
            barrier.wait(timeout=30)
            try:
                ObjectIntelligenceRepository(s).update_role(
                    DEFAULT_WORKSPACE_ID, role_id, 1, name="concurrent"
                )
                s.commit()
                outcome = "ok"
            except RoleConflictError:
                s.rollback()
                outcome = "conflict"
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "concurrent writers hung"
    assert sorted(outcomes) == ["conflict", "ok"], outcomes
    with _session() as session:
        final = session.get(ObjectRole, role_id)
        assert final is not None
        assert final.revision == 2 and final.name == "concurrent"


# ── F4: idempotency collision semantics ────────────────────────────────────


def test_idempotency_key_different_project_conflict(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        p2, v2 = _seed_second_project_video(session, DEFAULT_WORKSPACE_ID)
        repo = ObjectIntelligenceRepository(session)
        _role(repo, ids, "key-1")
        with pytest.raises(RoleConflictError):
            repo.create_role(
                DEFAULT_WORKSPACE_ID, p2, v2, "1", "Hero", idempotency_key="key-1"
            )


def test_idempotency_key_different_generation_conflict(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        _role(repo, ids, "key-gen")
        with pytest.raises(RoleConflictError):
            repo.create_role(
                DEFAULT_WORKSPACE_ID,
                ids[0],
                ids[1],
                "2",
                "Hero",
                idempotency_key="key-gen",
            )


def test_idempotency_key_different_payload_conflict(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        _role(repo, ids, "key-name")
        with pytest.raises(RoleConflictError):
            repo.create_role(
                DEFAULT_WORKSPACE_ID,
                ids[0],
                ids[1],
                "1",
                "Different Name",
                idempotency_key="key-name",
            )


def test_occurrence_natural_key_different_payload_conflict(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        role, _ = _role(repo, ids)
        args = dict(bbox_x=0, bbox_y=0, bbox_w=1, bbox_h=1, confidence=0.5)
        repo.create_occurrence(DEFAULT_WORKSPACE_ID, role.id, ids[2], 1, 10, **args)
        with pytest.raises(OccurrenceConflictError):
            repo.create_occurrence(
                DEFAULT_WORKSPACE_ID,
                role.id,
                ids[2],
                1,
                10,
                bbox_x=0,
                bbox_y=0,
                bbox_w=1,
                bbox_h=1,
                confidence=0.9,
            )


def test_api_idempotency_collision_conflict(client: TestClient) -> None:
    ids = _api_seed()
    one = _api_role(client, ids, "api-collide")
    assert one.status_code == 201
    # Same key, different project -> stable 409, never a replay of another role.
    with _session() as session:
        p2, v2 = _seed_second_project_video(session, DEFAULT_WORKSPACE_ID)
    collision = client.post(
        "/api/v2/object-intelligence/roles",
        json={
            "project_id": p2,
            "video_item_id": v2,
            "source_generation": "1",
            "name": "Hero",
            "idempotency_key": "api-collide",
        },
    )
    assert collision.status_code == 409
    # Occurrence: same natural key, different payload -> stable 409.
    role = one.json()
    occ_url = f"/api/v2/object-intelligence/roles/{role['id']}/occurrences"
    body = {
        "scene_id": ids[2],
        "frame_index": 1,
        "time_ms": 10,
        "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
        "confidence": 0.5,
    }
    assert client.post(occ_url, json=body).status_code == 201
    body["confidence"] = 0.9
    assert client.post(occ_url, json=body).status_code == 409


# ── CORRECTION ROUND C2 — current-generation role listing ──────────────────
#
# Acceptance (sprint exit finding): the PUBLIC role list/detail defaults to
# ONLY roles in the backend-authoritative CURRENT source generation; source
# replacement 1 -> 2 hides generation-1 roles; stale-role mutations fail
# closed with ZERO mutation; historical inspection is an explicit separate
# contract (generation=N) that never mixes with the current list; stable role
# IDs remain the identity authority.


def _seed_video_source(
    session: Session, video_id: str, sha: str = "a" * 64
) -> str:
    """Attach a ready video Artifact as the video's current source; return id."""
    art = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="video",
        relative_path=f"video/source-{uuid.uuid4().hex[:8]}.mp4",
        state="ready",
        sha256=sha,
        size_bytes=1234,
        mime_type="video/mp4",
    )
    session.add(art)
    session.flush()
    video = session.get(VideoItem, video_id)
    assert video is not None
    video.source_artifact_id = art.id
    session.commit()
    return art.id


def _seed_completed_discover_job(
    session: Session, video_id: str, generation: str, source_sha: str
) -> str:
    """Insert a COMPLETED DISCOVER_OBJECTS job (backend extraction authority)."""
    job = Job(
        workspace_id=DEFAULT_WORKSPACE_ID,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video_id,
        state="completed",
        input_generation=generation,
        input_manifest_json=json.dumps(
            {"source_sha256": source_sha, "managed_root": "artifacts"}
        ),
    )
    session.add(job)
    session.flush()
    session.commit()
    return job.id


def _api_role_gen(
    client: TestClient, ids: tuple[str, str, str, str], generation: str, name: str = "Hero"
):
    return client.post(
        "/api/v2/object-intelligence/roles",
        json={
            "project_id": ids[0],
            "video_item_id": ids[1],
            "source_generation": generation,
            "name": name,
        },
    )


# ── C2-A: backend-authoritative current generation ─────────────────────────


def test_current_generation_defaults_to_one_without_jobs(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        assert repo.current_generation(DEFAULT_WORKSPACE_ID, ids[1]) == "1"


def test_current_generation_advances_with_completed_jobs(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        sha = "b" * 64
        _seed_video_source(session, ids[1], sha)
        repo = ObjectIntelligenceRepository(session)
        # gen-1 completed for the current source -> current "1".
        _seed_completed_discover_job(session, ids[1], "1", sha)
        assert repo.current_generation(DEFAULT_WORKSPACE_ID, ids[1]) == "1"
        # gen-2 completed for the SAME source -> current advances to "2".
        _seed_completed_discover_job(session, ids[1], "2", sha)
        assert repo.current_generation(DEFAULT_WORKSPACE_ID, ids[1]) == "2"
        # A job for a DIFFERENT source sha never advances the current gen.
        _seed_completed_discover_job(session, ids[1], "9", "c" * 64)
        assert repo.current_generation(DEFAULT_WORKSPACE_ID, ids[1]) == "2"
        # Missing video item fails closed.
        with pytest.raises(RoleNotFoundError):
            repo.current_generation(DEFAULT_WORKSPACE_ID, "00000000-0000-0000-0000-000000000000")


# ── C2-B: list/detail default to current generation; historical explicit ───


def test_list_roles_current_only_and_explicit_generation(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        # gen-1 role is current (no jobs -> current "1"); gen-2 role is stale.
        repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "Current")
        repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "2", "Stale")
        current, _ = repo.list_roles(
            DEFAULT_WORKSPACE_ID, video_item_id=ids[1], only_current=True
        )
        assert sorted(r.source_generation for r in current) == ["1"]
        stale_view, _ = repo.list_roles(
            DEFAULT_WORKSPACE_ID,
            video_item_id=ids[1],
            source_generation="2",
        )
        assert [r.name for r in stale_view] == ["Stale"]
        # Cross-video current-only (no video filter) keeps currentness per video.
        v2 = VideoItem(project_id=ids[0], title="V2", position=2)
        session.add(v2)
        session.flush()
        session.commit()
        repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], v2.id, "1", "Other Current")
        repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], v2.id, "3", "Other Stale")
        all_current, _ = repo.list_roles(DEFAULT_WORKSPACE_ID, only_current=True)
        all_names = sorted(r.name for r in all_current)
        assert "Current" in all_names and "Other Current" in all_names
        assert "Stale" not in all_names and "Other Stale" not in all_names


def test_get_role_current_scope_and_explicit_historical(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        current_role, _ = repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "1", "Cur")
        stale_role, _ = repo.create_role(DEFAULT_WORKSPACE_ID, ids[0], ids[1], "2", "Old")
        assert repo.get_role(
            DEFAULT_WORKSPACE_ID, current_role.id, only_current=True
        ).id == current_role.id
        # Stale detail is fail-closed under the current scope...
        with pytest.raises(RoleNotFoundError):
            repo.get_role(DEFAULT_WORKSPACE_ID, stale_role.id, only_current=True)
        # ...and reachable ONLY via the explicit historical contract.
        assert (
            repo.get_role(DEFAULT_WORKSPACE_ID, stale_role.id, source_generation="2").id
            == stale_role.id
        )
        with pytest.raises(RoleNotFoundError):
            repo.get_role(DEFAULT_WORKSPACE_ID, stale_role.id, source_generation="1")


# ── C2-C: stale-role mutations fail closed with ZERO mutation ──────────────


def test_stale_role_update_fails_closed_zero_mutation(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        stale, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "2", "Stale"
        )
        with pytest.raises(RoleConflictError):
            repo.update_role(DEFAULT_WORKSPACE_ID, stale.id, 1, name="Hacked")
        fresh = repo.get_role(DEFAULT_WORKSPACE_ID, stale.id, source_generation="2")
        assert fresh.revision == 1 and fresh.name == "Stale"


def test_stale_role_occurrence_update_fails_closed(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_ownership(session)
        repo = ObjectIntelligenceRepository(session)
        stale, _ = repo.create_role(
            DEFAULT_WORKSPACE_ID, ids[0], ids[1], "2", "Stale"
        )
        # Evidence creation is the extraction pipeline's contract (not an
        # AC3 stale-op); the CORRECTION path (update_occurrence) must fail
        # closed with zero mutation.
        occ, created = repo.create_occurrence(
            DEFAULT_WORKSPACE_ID, stale.id, ids[2], 1, 10,
            bbox_x=0, bbox_y=0, bbox_w=1, bbox_h=1, confidence=0.5,
        )
        assert created
        with pytest.raises(RoleConflictError):
            repo.update_occurrence(
                DEFAULT_WORKSPACE_ID, stale.id, occ.id, occ.revision,
                review_state="accepted",
            )
        fresh = repo.get_occurrence(DEFAULT_WORKSPACE_ID, stale.id, occ.id)
        assert fresh.revision == occ.revision and fresh.review_state == "unreviewed"


# ── C2-D: API contract — current default, explicit historical, replacement ─


def test_api_list_defaults_current_generation_historical_explicit(
    client: TestClient,
) -> None:
    ids = _api_seed()
    assert _api_role_gen(client, ids, "1", "Current").status_code == 201
    assert _api_role_gen(client, ids, "2", "Historical Role").status_code == 201
    cur = client.get(f"/api/v2/object-intelligence/roles?video_item_id={ids[1]}").json()
    assert cur["scope"] == "current" and cur["current_generation"] == "1"
    assert [r["name"] for r in cur["roles"]] == ["Current"]
    hist = client.get(
        f"/api/v2/object-intelligence/roles?video_item_id={ids[1]}&generation=2"
    ).json()
    assert hist["scope"] == "historical"
    assert [r["name"] for r in hist["roles"]] == ["Historical Role"]
    cur_explicit = client.get(
        f"/api/v2/object-intelligence/roles?video_item_id={ids[1]}&generation=1"
    ).json()
    assert cur_explicit["scope"] == "current"
    assert all(
        r["id"] in {x["id"] for x in cur["roles"]} for r in cur_explicit["roles"]
    )


def test_api_stale_role_detail_and_patch_fail_closed(client: TestClient) -> None:
    ids = _api_seed()
    created = _api_role_gen(client, ids, "2", "Historical Role")
    assert created.status_code == 201
    stale_id = created.json()["id"]
    # Detail: 404 under the current scope...
    assert (
        client.get(f"/api/v2/object-intelligence/roles/{stale_id}").status_code == 404
    )
    # ...200 only via the explicit generation contract.
    hist = client.get(
        f"/api/v2/object-intelligence/roles/{stale_id}?generation=2"
    )
    assert hist.status_code == 200 and hist.json()["source_generation"] == "2"
    # Patch: 409 (stale immutable), zero mutation.
    patch = client.patch(
        f"/api/v2/object-intelligence/roles/{stale_id}",
        json={"revision": 1, "name": "Hacked"},
    )
    assert patch.status_code == 409
    after = client.get(
        f"/api/v2/object-intelligence/roles/{stale_id}?generation=2"
    ).json()
    assert after["revision"] == 1 and after["name"] == "Historical Role"


def test_api_source_replacement_hides_generation1_roles(client: TestClient) -> None:
    ids = _api_seed()
    video_id = ids[1]
    # Backend: current source sha1 + completed gen-1 job.
    with _session() as session:
        _seed_video_source(session, video_id, "d" * 64)
        _seed_completed_discover_job(session, video_id, "1", "d" * 64)
    assert _api_role_gen(client, ids, "1", "Gen1 Hero").status_code == 201
    cur = client.get(f"/api/v2/object-intelligence/roles?video_item_id={video_id}").json()
    assert cur["scope"] == "current" and cur["current_generation"] == "1"
    assert [r["name"] for r in cur["roles"]] == ["Gen1 Hero"]
    # Source replacement 1 -> 2 (same video item): new source sha2 + gen-2 job.
    with _session() as session:
        _seed_video_source(session, video_id, "e" * 64)
        _seed_completed_discover_job(session, video_id, "2", "e" * 64)
    created = _api_role_gen(client, ids, "2", "Gen2 Hero")
    assert created.status_code == 201
    after = client.get(f"/api/v2/object-intelligence/roles?video_item_id={video_id}").json()
    assert after["scope"] == "current" and after["current_generation"] == "2"
    names = [r["name"] for r in after["roles"]]
    assert "Gen2 Hero" in names and "Gen1 Hero" not in names  # AC2: gen-1 hidden
    # Gen-1 roles survive as an EXPLICIT historical view only.
    hist = client.get(
        f"/api/v2/object-intelligence/roles?video_item_id={video_id}&generation=1"
    ).json()
    assert hist["scope"] == "historical"
    assert [r["name"] for r in hist["roles"]] == ["Gen1 Hero"]
    # Mutation of a stale gen-1 role fails closed.
    gen1_id = hist["roles"][0]["id"]
    patch = client.patch(
        f"/api/v2/object-intelligence/roles/{gen1_id}",
        json={"revision": 1, "name": "Hacked"},
    )
    assert patch.status_code == 409
    unchanged = client.get(
        f"/api/v2/object-intelligence/roles/{gen1_id}?generation=1"
    )
    assert unchanged.status_code == 200 and unchanged.json()["name"] == "Gen1 Hero"

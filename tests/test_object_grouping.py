"""Focused S08-T03 suite: cross-scene grouping + curation API.

Covers deterministic grouping (same/different object across scenes,
ambiguity, low confidence), merge/split/confirm (CAS, idempotency,
concurrency, restart, ownership, occurrence collision), stale-revision
conflicts, audit history, never-auto-confirm, evidence preservation and
read-only GET endpoints.
"""

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
    REMOVAL_ONLY_KINDS,
    Artifact,
    Job,
    ObjectGroupingSuggestion,
    ObjectOccurrence,
    ObjectRole,
    Project,
    RoleOperation,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_grouping import (
    ObjectGroupingRepository,
    OperationConflictError,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
    RoleConflictError,
)
from app.services.object_grouping import (
    OccurrenceEvidence,
    RoleEvidence,
    generate_pair_suggestions,
    normalize_name,
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


def _session() -> Session:
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _repo(session: Session) -> ObjectGroupingRepository:
    return ObjectGroupingRepository(session)


def _seed_cluster(session: Session) -> dict[str, str]:
    """Two videos (Primary with two scenes, Other with one) + a second workspace."""
    workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
    other_ws = Workspace(name="foreign-workspace")
    project = Project(workspace_id=workspace.id, name="Objects")
    video = VideoItem(project=project, title="Primary", position=0)
    scene_a = Scene(
        video_item=video,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    scene_b = Scene(
        video_item=video,
        position=1,
        start_frame=100,
        end_frame=110,
        start_time_ms=10000,
        end_time_ms=11000,
        status="pending",
    )
    video_other = VideoItem(project=project, title="Other", position=1)
    scene_other = Scene(
        video_item=video_other,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    other_project = Project(workspace=other_ws, name="Foreign")
    other_video = VideoItem(project=other_project, title="ForeignVideo", position=0)
    other_scene = Scene(
        video_item=other_video,
        position=0,
        start_frame=0,
        end_frame=10,
        start_time_ms=0,
        end_time_ms=1000,
        status="pending",
    )
    session.add_all(
        [
            workspace,
            other_ws,
            project,
            video,
            scene_a,
            scene_b,
            video_other,
            scene_other,
            other_project,
            other_video,
            other_scene,
        ]
    )
    session.commit()
    return {
        "project": project.id,
        "video": video.id,
        "scene_a": scene_a.id,
        "scene_b": scene_b.id,
        "video_other": video_other.id,
        "scene_other": scene_other.id,
        "foreign_workspace": other_ws.id,
        "foreign_project": other_project.id,
        "foreign_video": other_video.id,
        "foreign_scene": other_scene.id,
    }


def _role(
    session: Session,
    cluster: dict[str, str],
    name: str,
    *,
    generation: str = "1",
    video_key: str = "video",
    kind: str = "character",
) -> ObjectRole:
    repo = ObjectIntelligenceRepository(session)
    record, _ = repo.create_role(
        DEFAULT_WORKSPACE_ID,
        cluster["project"],
        cluster[video_key],
        generation,
        name,
        kind=kind,
    )
    return record  # type: ignore[return-value]


def _occurrence(
    session: Session,
    cluster: dict[str, str],
    role_id: str,
    scene_key: str,
    frame: int,
    *,
    time_ms: int = 0,
    bbox: tuple[int, int, int, int] = (10, 10, 40, 40),
    confidence: float = 0.8,
    review_state: str = "accepted",
    reasons: list[str] | None = None,
) -> ObjectOccurrence:
    repo = ObjectIntelligenceRepository(session)
    x, y, w, h = bbox
    record, _ = repo.create_occurrence(
        DEFAULT_WORKSPACE_ID,
        role_id,
        cluster[scene_key],
        frame,
        time_ms,
        bbox_x=x,
        bbox_y=y,
        bbox_w=w,
        bbox_h=h,
        confidence=confidence,
        confidence_source="detector",
        algorithm="deterministic-layout",
        algorithm_version="1",
        reasons=reasons or ["test-evidence"],
        review_state=review_state,
    )
    return record  # type: ignore[return-value]


def _same_object_pair(session: Session, cluster: dict[str, str]) -> tuple[ObjectRole, ObjectRole]:
    """Two roles with the same name and a consistent spatial footprint."""
    role_a = _role(session, cluster, "Hero")
    role_b = _role(session, cluster, "Hero")
    _occurrence(session, cluster, role_a.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40))
    _occurrence(
        session, cluster, role_b.id, "scene_b", 105, time_ms=10500, bbox=(11, 10, 39, 41)
    )
    session.commit()
    return role_a, role_b


def _api_seed() -> dict[str, str]:
    with _session() as session:
        return _seed_cluster(session)


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


# ── migration ──────────────────────────────────────────────────────────────


def test_migration_round_trip_grouping_surfaces(tmp_path: Path) -> None:
    db = tmp_path / "grouping-roundtrip.db"
    config = _alembic_config(db)
    command.upgrade(config, "head")
    engine = create_engine_for_path(db)
    tables = set(inspect(engine).get_table_names())
    assert {"object_role", "object_occurrence"} <= tables
    assert {
        "object_grouping_suggestion",
        "object_role_operation",
    } <= tables
    inspector = inspect(engine)
    suggestion_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("object_grouping_suggestion")
    }
    assert "ck_object_grouping_suggestion_status" in suggestion_checks
    operation_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "object_role_operation"
        )
    }
    assert "ck_object_role_operation_type" in operation_checks
    assert "uq_object_grouping_suggestion_natural" in {
        index["name"] for index in inspector.get_indexes("object_grouping_suggestion")
    }
    command.downgrade(config, "f2a3b4c5d6e7")
    tables = set(inspect(create_engine_for_path(db)).get_table_names())
    assert not {
        "object_grouping_suggestion",
        "object_role_operation",
    } & tables
    command.upgrade(config, "head")
    tables = set(inspect(create_engine_for_path(db)).get_table_names())
    assert {
        "object_grouping_suggestion",
        "object_role_operation",
    } <= tables
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    heads = sorted(ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads())
    # S09-T00-I04: live runtime contract — DB revision must equal the current
    # ScriptDirectory head; single-head guard keeps this stricter than a pin.
    assert len(heads) == 1, f"expected exactly one Alembic head, got {heads}"
    assert version == heads[0]


def test_grouping_constraints_real(tmp_path: Path) -> None:
    """CHECKs in the migration are real: out-of-domain writes fail."""
    db = tmp_path / "grouping-constraints.db"
    _upgrade_to_head(db)
    with Session(create_engine_for_path(db)) as session:
        cluster = _seed_cluster(session)
        role_a = _role(session, cluster, "Hero")
        session.commit()
        session.add(
            ObjectGroupingSuggestion(
                workspace_id=DEFAULT_WORKSPACE_ID,
                project_id=cluster["project"],
                video_item_id=cluster["video"],
                source_generation="1",
                status="bad-status",
                role_ids_json=json.dumps([role_a.id]),
                confidence=0.9,
                reasons_json="[]",
                algorithm="a",
                algorithm_version="1",
                scope="video",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


# ── deterministic grouping algorithm (pure) ──────────────────────────────


def _evidence(
    role_id: str,
    name: str,
    occurrences: list[tuple[int, int, int, int, int, int]],
) -> RoleEvidence:
    return RoleEvidence(
        role_id=role_id,
        name=name,
        kind="character",
        source_generation="1",
        occurrences=tuple(
            OccurrenceEvidence(
                scene_id=f"scene-{frame}",
                frame_index=frame,
                time_ms=time_ms,
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
            )
            for frame, time_ms, x, y, w, h in occurrences
        ),
    )


def test_grouping_algorithm_deterministic_same_inputs() -> None:
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r2", "Hero", [(105, 10500, 11, 10, 39, 41)]),
    ]
    first = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)
    second = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)
    assert first == second
    assert len(first) == 1


def test_same_object_across_scenes_high_confidence() -> None:
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r2", "Hero", [(105, 10500, 11, 10, 39, 41)]),
    ]
    suggestion = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)[0]
    assert suggestion.confidence == 0.9
    assert suggestion.role_ids == ("r1", "r2")
    assert "same-normalized-name" in suggestion.reasons
    assert suggestion.algorithm == "role-fingerprint"
    assert suggestion.algorithm_version == "1"


def test_different_object_across_scenes_low_confidence() -> None:
    """Same name but disjoint footprints -> LOW confidence suggestion."""
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 0, 0, 10, 10)]),
        _evidence("r2", "Hero", [(105, 10500, 800, 800, 10, 10)]),
    ]
    suggestion = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)[0]
    assert suggestion.confidence == 0.45
    assert "spatial-footprint-differs-may-be-distinct-objects" in suggestion.reasons
    assert "occurrences-temporally-disjoint" in suggestion.reasons


def test_different_names_distinct_footprints_no_suggestion() -> None:
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 0, 0, 10, 10)]),
        _evidence("r2", "Villain", [(105, 10500, 800, 800, 10, 10)]),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_ambiguity_different_names_matching_footprint() -> None:
    """Matching footprint + temporally disjoint -> moderate ambiguity."""
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r2", "HeroStunt", [(105, 10500, 11, 10, 39, 41)]),
    ]
    suggestion = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)[0]
    assert suggestion.confidence == 0.6
    assert "occurrences-temporally-disjoint-ambiguity" in suggestion.reasons


def test_algorithm_output_is_pairwise_and_canonical() -> None:
    evidence = [
        _evidence("r-b", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r-a", "Hero", [(105, 10500, 11, 10, 39, 41)]),
        _evidence("r-c", "Hero", [(205, 20500, 12, 10, 38, 42)]),
    ]
    suggestions = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)
    assert {s.role_ids for s in suggestions} == {
        ("r-a", "r-b"),
        ("r-a", "r-c"),
        ("r-b", "r-c"),
    }
    for suggestion in suggestions:
        assert suggestion.role_ids[0] < suggestion.role_ids[1]


def test_normalize_name_folds_whitespace_and_case() -> None:
    assert normalize_name("  Hero  ") == "hero"
    assert normalize_name("Villain\nSide") == "villain side"


# ── generation: durable, pending, idempotent ─────────────────────────────


def test_generate_durable_pending_and_idempotent(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        _same_object_pair(session, cluster)
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    body = {
        "video_item_id": cluster["video"],
        "source_generation": "1",
    }
    first = client.post(url, json=body)
    assert first.status_code == 201
    payload = first.json()
    assert payload["created_count"] == 1
    assert payload["replayed_count"] == 0
    suggestion = payload["suggestions"][0]
    assert suggestion["status"] == "pending"
    assert suggestion["confidence"] == 0.9
    assert suggestion["reasons"]
    assert suggestion["algorithm"] == "role-fingerprint"
    assert suggestion["algorithm_version"] == "1"
    assert set(suggestion["role_ids"]) == {
        _role_ids(cluster)[0],
        _role_ids(cluster)[1],
    }
    # Roles were NEVER auto-confirmed by generation.
    with _session() as session:
        statuses = {
            row.status
            for row in session.scalars(
                select(ObjectRole).where(ObjectRole.video_item_id == cluster["video"])
            ).all()
        }
        assert statuses == {"suggested"}
    # Re-run: full replay, same suggestion ids, 200.
    second = client.post(url, json=body)
    assert second.status_code == 200
    payload2 = second.json()
    assert payload2["created_count"] == 0
    assert payload2["replayed_count"] == 1
    assert payload2["suggestions"][0]["id"] == suggestion["id"]


def _role_ids(cluster: dict[str, str]) -> list[str]:
    with _session() as session:
        return [
            row.id
            for row in session.scalars(
                select(ObjectRole)
                .where(ObjectRole.video_item_id == cluster["video"])
                .order_by(ObjectRole.created_at, ObjectRole.id)
            ).all()
        ]


def test_generate_supersedes_stale_pending_when_roles_change(
    client: TestClient,
) -> None:
    """Generation replays identical sets; stale (merged-away) sets are
    traceably superseded and never re-suggested."""
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    body = {"video_item_id": cluster["video"], "source_generation": "1"}
    first = client.post(url, json=body)
    assert first.status_code == 201
    first_id = first.json()["suggestions"][0]["id"]
    # Simulate a user already reviewing: dismiss the suggestion.
    dismiss = client.post(
        f"/api/v2/object-intelligence/grouping/suggestions/{first_id}/dismiss",
        json={"revision": 1},
    )
    assert dismiss.status_code == 200
    assert dismiss.json()["status"] == "dismissed"
    # Re-generation with the SAME active set: the reviewer's decision is
    # preserved — the dismissed row replays (200), never clobbered.
    second = client.post(url, json=body)
    assert second.status_code == 200
    assert second.json()["replayed_count"] == 1
    assert second.json()["superseded_count"] == 0
    with _session() as session:
        still = session.get(ObjectGroupingSuggestion, first_id)
        assert still is not None and still.status == "dismissed"
    # Merging one role away makes the set stale; the next generation run
    # traceably supersedes the suggestion and produces NO fresh pair.
    with _session() as session:
        role_b_id = role_b.id
    merged = client.post(
        f"/api/v2/object-intelligence/grouping/roles/{role_a.id}/merge",
        json=_merge_body(cluster, [role_b_id], 1),
    )
    assert merged.status_code == 201
    third = client.post(url, json=body)
    assert third.status_code == 201
    assert third.json()["superseded_count"] == 1
    assert third.json()["created_count"] == 0
    assert third.json()["total"] == 0
    with _session() as session:
        superseded = session.get(ObjectGroupingSuggestion, first_id)
        assert superseded is not None and superseded.status == "superseded"
        assert superseded.natural_key is None


# ── merge: CAS, evidence move, audit, boundaries ─────────────────────────


def _merge_url(cluster: dict[str, str]) -> str:
    return "/api/v2/object-intelligence/grouping/roles/{role_id}/merge"


def _merge_body(cluster: dict[str, str], sources: list[str], revision: int, **extra) -> dict:
    return {
        "video_item_id": cluster["video"],
        "revision": revision,
        "source_role_ids": sources,
        **extra,
    }


def test_merge_moves_evidence_supersedes_source_and_audits(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
        occ_a = _occurrence(
            session, cluster, role_a.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40)
        )
        occ_b = _occurrence(
            session,
            cluster,
            role_b.id,
            "scene_b",
            105,
            time_ms=10500,
            bbox=(11, 10, 39, 41),
        )
        session.commit()
        occ_a_id, occ_b_id = occ_a.id, occ_b.id
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_b.id], 1),
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["operation"]["operation_type"] == "merge"
    assert payload["operation"]["source_role_ids"] == [role_b.id]
    transfer = payload["operation"]["transfer_map"]
    assert transfer == [{"role_id": role_b.id, "occurrence_ids": [occ_b_id]}]
    assert payload["operation"]["revision_after"] == 2
    assert payload["target_role"]["id"] == role_a.id
    with _session() as session:
        target = session.get(ObjectRole, role_a.id)
        source = session.get(ObjectRole, role_b.id)
        assert target is not None and target.revision == 2
        assert source is not None
        assert source.status == "superseded"
        assert source.supersedes_role_id == role_a.id
        occ_a_row = session.get(ObjectOccurrence, occ_a_id)
        occ_b_row = session.get(ObjectOccurrence, occ_b_id)
        assert occ_a_row is not None and occ_a_row.role_id == role_a.id
        assert occ_b_row is not None and occ_b_row.role_id == role_a.id
        # Evidence content is NEVER rewritten during a merge.
        assert (
            occ_b_row.confidence,
            occ_b_row.bbox_x,
            occ_b_row.bbox_y,
            occ_b_row.bbox_w,
            occ_b_row.bbox_h,
            occ_b_row.review_state,
            occ_b_row.reasons_json,
        ) == (0.8, 11, 10, 39, 41, "accepted", json.dumps(["test-evidence"]))
        op_count = len(
            session.scalars(
                select(RoleOperation).where(
                    RoleOperation.operation_type == "merge",
                    RoleOperation.target_role_id == role_a.id,
                )
            ).all()
        )
        assert op_count == 1


def test_merge_cas_stale_revision_conflict(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_b.id], 1),
    )
    assert response.status_code == 201
    # Same merge again with the OLD revision -> stale CAS conflict.
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_b.id], 1),
    )
    assert response.status_code == 200  # natural-key replay, NOT a conflict
    with _session() as session:
        # A genuinely different mutation at a stale revision conflicts.
        role_c = _role(session, cluster, "Hero")
        session.commit()
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_c.id], 1),
    )
    assert response.status_code == 409
    assert "stale revision" in response.json()["detail"]


def test_merge_cross_project_video_generation_fail_closed(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        role_gen2 = _role(session, cluster, "Hero", generation="2")
        role_other_video = _role(session, cluster, "Hero", video_key="video_other")
        session.commit()
    for source in (role_gen2.id, role_other_video.id):
        response = client.post(
            _merge_url(cluster).format(role_id=role_a.id),
            json=_merge_body(cluster, [source], 1),
        )
        assert response.status_code == 409, source
    with _session() as session:
        role_other_project = ObjectIntelligenceRepository(session).create_role(
            cluster["foreign_workspace"],
            cluster["foreign_project"],
            cluster["foreign_video"],
            "1",
            "Hero",
        )
        session.commit()
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_other_project[0].id], 1),
    )
    assert response.status_code == 409


def test_merge_self_and_terminal_conflicts(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        role_b = _role(session, cluster, "Hero")
        _occurrence(session, cluster, role_a.id, "scene_a", 5, time_ms=500)
        _occurrence(session, cluster, role_b.id, "scene_b", 105, time_ms=10500)
        session.commit()
    # Self-merge rejected.
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_a.id], 1),
    )
    assert response.status_code == 409
    # Merging a terminal source rejected.
    response = client.post(
        _merge_url(cluster).format(role_id=role_b.id),
        json=_merge_body(cluster, [role_a.id], 1),
    )
    assert response.status_code == 201
    with _session() as session:
        role_c = _role(session, cluster, "Hero")
        session.commit()
    response = client.post(
        _merge_url(cluster).format(role_id=role_c.id),
        json=_merge_body(cluster, [role_a.id], 1),
    )
    assert response.status_code == 409
    assert "terminal" in response.json()["detail"]


def test_merge_occurrence_collision_fails_closed(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        role_b = _role(session, cluster, "Hero")
        # Both roles claim the SAME scene + frame -> merge would duplicate.
        _occurrence(session, cluster, role_a.id, "scene_a", 5, time_ms=500)
        _occurrence(session, cluster, role_b.id, "scene_a", 5, time_ms=500)
        session.commit()
        role_b_id = role_b.id
    response = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_b_id], 1),
    )
    assert response.status_code == 409
    assert "collision" in response.json()["detail"]
    with _session() as session:
        source = session.get(ObjectRole, role_b_id)
        assert source is not None and source.status == "suggested"
        assert not session.scalars(select(RoleOperation)).all()


# ── split: restore one merged original with its exact evidence ───────────


def _split_url(cluster: dict[str, str]) -> str:
    return "/api/v2/object-intelligence/grouping/roles/{role_id}/split"


def test_split_restores_original_with_evidence(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        role_b = _role(session, cluster, "Hero")
        _occurrence(
            session, cluster, role_a.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40)
        )
        occ_b = _occurrence(
            session,
            cluster,
            role_b.id,
            "scene_b",
            105,
            time_ms=10500,
            bbox=(11, 10, 39, 41),
            review_state="edited",
            reasons=["user-touched"],
        )
        session.commit()
        occ_b_id = occ_b.id
        role_b_name = role_b.name
        role_b_kind = role_b.kind
    merged = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_b.id], 1),
    )
    assert merged.status_code == 201
    response = client.post(
        _split_url(cluster).format(role_id=role_a.id),
        json={
            "video_item_id": cluster["video"],
            "revision": 2,
            "original_role_id": role_b.id,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["operation"]["operation_type"] == "split"
    assert payload["operation"]["source_role_ids"] == [role_b.id]
    assert payload["operation"]["transfer_map"] == [
        {"role_id": role_b.id, "occurrence_ids": [occ_b_id]}
    ]
    created = payload["created_role"]
    assert created["name"] == role_b_name
    assert created["kind"] == role_b_kind
    assert created["status"] == "suggested"  # split never auto-confirms
    assert created["source_generation"] == "1"
    with _session() as session:
        occ = session.get(ObjectOccurrence, occ_b_id)
        assert occ is not None and occ.role_id == created["id"]
        # Occurrence content is preserved bit-for-bit across merge+split.
        assert (occ.confidence, occ.review_state, occ.reasons_json, occ.bbox_x) == (
            0.8,
            "edited",
            json.dumps(["user-touched"]),
            11,
        )
        original = session.get(ObjectRole, role_b.id)
        assert original is not None and original.status == "superseded"
        active_names = {
            row.name
            for row in session.scalars(
                select(ObjectRole).where(
                    ObjectRole.video_item_id == cluster["video"],
                    ObjectRole.status.in_(("suggested", "confirmed")),
                )
            ).all()
        }
        assert active_names == {"Hero"}


def test_split_requires_merge_lineage(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        role_b = _role(session, cluster, "Hero")
        _occurrence(session, cluster, role_a.id, "scene_a", 5, time_ms=500)
        _occurrence(session, cluster, role_b.id, "scene_b", 105, time_ms=10500)
        session.commit()
        b_id = role_b.id
        # Supersede via the T01 raw PATCH — NO T03 merge lineage.
        ObjectIntelligenceRepository(session).update_role(
            DEFAULT_WORKSPACE_ID, role_b.id, 1, status="superseded", supersedes_role_id=role_a.id
        )
        session.commit()
    response = client.post(
        _split_url(cluster).format(role_id=role_a.id),
        json={"video_item_id": cluster["video"], "revision": 1, "original_role_id": b_id},
    )
    assert response.status_code == 409
    assert "merge" in response.json()["detail"]


def test_split_stale_revision_and_duplicate_replay(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
        session.commit()
        b_id = role_b.id
    assert (
        client.post(
            _merge_url(cluster).format(role_id=role_a.id),
            json=_merge_body(cluster, [b_id], 1),
        ).status_code
        == 201
    )
    # Stale revision -> CAS conflict.
    stale = client.post(
        _split_url(cluster).format(role_id=role_a.id),
        json={"video_item_id": cluster["video"], "revision": 1, "original_role_id": b_id},
    )
    assert stale.status_code == 409
    # Correct revision, then replay with the same natural key -> same role.
    first = client.post(
        _split_url(cluster).format(role_id=role_a.id),
        json={"video_item_id": cluster["video"], "revision": 2, "original_role_id": b_id},
    )
    assert first.status_code == 201
    second = client.post(
        _split_url(cluster).format(role_id=role_a.id),
        json={"video_item_id": cluster["video"], "revision": 2, "original_role_id": b_id},
    )
    assert second.status_code == 200
    assert second.json()["created_role"]["id"] == first.json()["created_role"]["id"]
    with _session() as session:
        assert len(session.scalars(select(RoleOperation)).all()) == 2  # merge + split


# ── confirm: explicit, audited, idempotent ────────────────────────────────


def _confirm_url(cluster: dict[str, str]) -> str:
    return "/api/v2/object-intelligence/grouping/roles/{role_id}/confirm"


def test_confirm_durable_audited_and_idempotent(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        session.commit()
        role_id = role_a.id
    body = {"video_item_id": cluster["video"], "revision": 1}
    first = client.post(_confirm_url(cluster).format(role_id=role_id), json=body)
    assert first.status_code == 201
    payload = first.json()
    assert payload["role"]["status"] == "confirmed"
    assert payload["role"]["revision"] == 2
    assert payload["operation"]["operation_type"] == "confirm"
    assert payload["operation"]["revision_after"] == 2
    with _session() as session:
        status = session.get(ObjectRole, role_id)
        assert status is not None and status.status == "confirmed"
        assert len(session.scalars(select(RoleOperation)).all()) == 1
    # Replay: same operation row, 200, zero new writes.
    second = client.post(_confirm_url(cluster).format(role_id=role_id), json=body)
    assert second.status_code == 200
    assert second.json()["operation"]["id"] == payload["operation"]["id"]
    with _session() as session:
        assert len(session.scalars(select(RoleOperation)).all()) == 1


def test_confirm_stale_revision_and_terminal_conflict(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero")
        role_b = _role(session, cluster, "Hero")
        session.commit()
        role_a_id, role_b_id = role_a.id, role_b.id
    assert (
        client.post(
            _confirm_url(cluster).format(role_id=role_a_id),
            json={"video_item_id": cluster["video"], "revision": 1},
        ).status_code
        == 201
    )
    # Stale revision -> 409.
    stale = client.post(
        _confirm_url(cluster).format(role_id=role_a_id),
        json={"video_item_id": cluster["video"], "revision": 1},
    )
    assert stale.status_code == 200  # natural-key replay (confirmed already)
    # A materially different mutation with a stale revision conflicts.
    renamed = client.patch(
        f"/api/v2/object-intelligence/roles/{role_a_id}",
        json={"revision": 2, "name": "Hero V2"},
    )
    assert renamed.status_code == 200
    stale2 = client.post(
        _confirm_url(cluster).format(role_id=role_a_id),
        json={"video_item_id": cluster["video"], "revision": 1},
    )
    assert stale2.status_code == 200  # replay is allowed while confirmed
    # Terminal role cannot be confirmed.
    merged = client.post(
        _merge_url(cluster).format(role_id=role_a_id),
        json=_merge_body(cluster, [role_b_id], 3),
    )
    assert merged.status_code == 201
    terminal = client.post(
        _confirm_url(cluster).format(role_id=role_b_id),
        json={"video_item_id": cluster["video"], "revision": 1},
    )
    assert terminal.status_code == 409
    assert "terminal" in terminal.json()["detail"]


# ── concurrency / restart: never duplicate active roles ──────────────────


def test_concurrent_merge_single_operation_and_single_active_role(
    client: TestClient,
) -> None:
    service = deps._job_service
    assert service is not None
    db_url = str(service._session_factory.kw["bind"].url)
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
        cluster_ids = {
            "project": cluster["project"],
            "video": cluster["video"],
        }
        role_a_id, role_b_id = role_a.id, role_b.id

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def writer() -> None:
        engine = create_engine_for_path(db_url)
        with Session(engine) as session:
            barrier.wait(timeout=30)
            try:
                operation, _target, created = ObjectGroupingRepository(
                    session
                ).apply_merge(
                    DEFAULT_WORKSPACE_ID,
                    cluster_ids["project"],
                    cluster_ids["video"],
                    role_a_id,
                    [role_b_id],
                    1,
                )
                session.commit()
                outcome = "created" if created else "replayed"
            except (RoleConflictError, OperationConflictError):
                session.rollback()
                outcome = "conflict"
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "concurrent writers hung"
    assert "created" in outcomes
    with _session() as session:
        operations = session.scalars(select(RoleOperation)).all()
        assert len(operations) == 1
        active = session.scalars(
            select(ObjectRole).where(
                ObjectRole.video_item_id == cluster["video"],
                ObjectRole.status.in_(("suggested", "confirmed")),
            )
        ).all()
        assert len(active) == 1 and active[0].id == role_a_id


def test_restart_replay_never_duplicates_active_roles(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
        role_a_id, role_b_id = role_a.id, role_b.id
    # "Restart": each request below runs on a FRESH session; the same
    # natural-key payload is replayed after a simulated process boundary.
    def fresh_merge() -> int:
        with _session() as session:
            operation, _target, created = ObjectGroupingRepository(session).apply_merge(
                DEFAULT_WORKSPACE_ID,
                cluster["project"],
                cluster["video"],
                role_a_id,
                [role_b_id],
                1,
            )
            session.commit()
            return 1 if created else 0

    assert fresh_merge() == 1
    assert fresh_merge() == 0  # restart replay, zero duplicates
    with _session() as session:
        assert len(session.scalars(select(RoleOperation)).all()) == 1
        active = session.scalars(
            select(ObjectRole).where(
                ObjectRole.video_item_id == cluster["video"],
                ObjectRole.status.in_(("suggested", "confirmed")),
            )
        ).all()
        assert len(active) == 1
    # Split replay across "restart" also returns the SAME created role.
    with _session() as session:
        operation, created_role, created = ObjectGroupingRepository(session).apply_split(
            DEFAULT_WORKSPACE_ID,
            cluster["project"],
            cluster["video"],
            role_a_id,
            role_b_id,
            2,
        )
        session.commit()
        assert created
        created_id = created_role.id
    with _session() as session:
        operation, created_role, created = ObjectGroupingRepository(session).apply_split(
            DEFAULT_WORKSPACE_ID,
            cluster["project"],
            cluster["video"],
            role_a_id,
            role_b_id,
            2,
        )
        session.commit()
        assert not created and created_role.id == created_id
        assert len(session.scalars(select(RoleOperation)).all()) == 2


# ── read-only GET endpoints ───────────────────────────────────────────────


def test_get_endpoints_zero_durable_mutations(client: TestClient) -> None:
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    generated = client.post(
        url, json={"video_item_id": cluster["video"], "source_generation": "1"}
    )
    assert generated.status_code == 201
    suggestion_id = generated.json()["suggestions"][0]["id"]
    with _session() as session:
        before = (
            len(session.scalars(select(ObjectGroupingSuggestion)).all()),
            len(session.scalars(select(RoleOperation)).all()),
            {
                row.id: row.revision
                for row in session.scalars(select(ObjectRole)).all()
            },
        )
    list_response = client.get(
        "/api/v2/object-intelligence/grouping/suggestions",
        params={"video_item_id": cluster["video"]},
    )
    assert list_response.status_code == 200
    detail = client.get(
        f"/api/v2/object-intelligence/grouping/suggestions/{suggestion_id}"
    )
    assert detail.status_code == 200
    assert detail.json()["reasons"]  # review reasons exposed
    ops = client.get(
        "/api/v2/object-intelligence/grouping/operations",
        params={"video_item_id": cluster["video"]},
    )
    assert ops.status_code == 200
    missing = client.get(
        "/api/v2/object-intelligence/grouping/suggestions/"
        + str(uuid.uuid4())
    )
    assert missing.status_code == 404
    with _session() as session:
        after = (
            len(session.scalars(select(ObjectGroupingSuggestion)).all()),
            len(session.scalars(select(RoleOperation)).all()),
            {
                row.id: row.revision
                for row in session.scalars(select(ObjectRole)).all()
            },
        )
    assert before == after


# ── C1: current-generation policy / stable ids / adversarial evidence ───────


def test_duplicate_name_cooccurring_no_suggestion() -> None:
    """Two identical-name objects seen TOGETHER are distinct: no suggestion.

    The display name is never identity authority — co-occurrence with a
    different footprint disproves identity.
    """
    evidence = [
        _evidence("r1", "Coin", [(5, 500, 0, 0, 20, 20)]),
        _evidence("r2", "Coin", [(5, 500, 400, 400, 20, 20)]),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_duplicate_name_temporal_disjoint_low_confidence() -> None:
    """Same name, disjoint footprint, temporally disjoint -> advisory 0.45."""
    evidence = [
        _evidence("r1", "Coin", [(5, 500, 0, 0, 20, 20)]),
        _evidence("r2", "Coin", [(105, 10500, 400, 400, 20, 20)]),
    ]
    suggestion = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)[0]
    assert suggestion.confidence == 0.45
    assert "occurrences-temporally-disjoint" in suggestion.reasons


def test_adversarial_name_spoof_cannot_force_merge() -> None:
    """Matching names + co-occurring evidence CANNOT force a suggestion."""
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 0, 0, 30, 30)]),
        _evidence("r2", "Hero", [(5, 500, 900, 900, 30, 30)]),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_adversarial_different_names_cooccurring_no_suggestion() -> None:
    """Matching footprint but CO-OCCURRING different names: distinct."""
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r2", "Villain", [(5, 500, 11, 10, 39, 41)]),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_evidence_first_different_name_consistent_footprint() -> None:
    """Appearance/track evidence MAY suggest despite different names (0.6)."""
    evidence = [
        _evidence("r1", "Hero", [(5, 500, 10, 10, 40, 40)]),
        _evidence("r2", "StuntDouble", [(105, 10500, 11, 10, 39, 41)]),
    ]
    suggestion = generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS)[0]
    assert suggestion.confidence == 0.6
    assert "spatial-footprint-matches-across-scenes" in suggestion.reasons


def test_missing_occurrence_evidence_no_suggestion() -> None:
    """No occurrence evidence -> no suggestion (name alone is never enough)."""
    evidence = [
        RoleEvidence(
            role_id="r1", name="Hero", kind="character",
            source_generation="g", occurrences=(),
        ),
        RoleEvidence(
            role_id="r2", name="Hero", kind="character",
            source_generation="g", occurrences=(),
        ),
    ]
    assert generate_pair_suggestions(evidence, removal_only_kinds=REMOVAL_ONLY_KINDS) == []


def test_policy_metadata_exposed(client: TestClient) -> None:
    """Backend exposes algorithm/calibration/threshold/advisory semantics."""
    policy = client.get("/api/v2/object-intelligence/grouping/policy")
    assert policy.status_code == 200
    payload = policy.json()
    assert payload["algorithm"] == "role-fingerprint"
    assert payload["algorithm_version"] == "1"
    assert payload["calibration_version"] == "2"
    assert payload["review_threshold"] == 0.35
    assert payload["advisory"] is True
    assert payload["confidence_semantics"]
    # Generate response carries the same policy metadata.
    cluster = _api_seed()
    with _session() as session:
        _same_object_pair(session, cluster)
    generated = client.post(
        "/api/v2/object-intelligence/grouping/suggestions/generate",
        json={"video_item_id": cluster["video"], "source_generation": "1"},
    )
    assert generated.status_code == 201
    gen = generated.json()
    assert gen["calibration_version"] == "2"
    assert gen["policy"]["review_threshold"] == 0.35
    assert gen["policy"]["advisory"] is True


def test_renamed_role_stable_id_preserved(client: TestClient) -> None:
    """Renames never change role ids inside suggestions/operations.

    The suggestion natural key is id-based, so after a rename the SAME
    suggestion row replays and a merge references the same stable ids.
    """
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
        role_b_id = role_b.id
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    body = {"video_item_id": cluster["video"], "source_generation": "1"}
    first = client.post(url, json=body)
    assert first.status_code == 201
    suggestion = first.json()["suggestions"][0]
    assert role_b_id in suggestion["role_ids"]
    # Rename role_b -> the suggestion still references the SAME stable id.
    renamed = client.patch(
        f"/api/v2/object-intelligence/roles/{role_b_id}",
        json={"revision": 1, "name": "Hero Renamed"},
    )
    assert renamed.status_code == 200
    second = client.post(url, json=body)
    assert second.status_code == 200  # id-based natural key -> exact replay
    replayed = second.json()["suggestions"][0]
    assert replayed["id"] == suggestion["id"]
    assert role_b_id in replayed["role_ids"]
    # Advisory content follows the NEW evidence (names now differ): the
    # same stable pair re-derives at the evidence band, never by name.
    assert replayed["confidence"] == 0.6
    assert "different-names" in replayed["reasons"]
    # Merge after rename: operation references the same stable ids.
    merged = client.post(
        _merge_url(cluster).format(role_id=role_a.id),
        json=_merge_body(cluster, [role_b_id], 1),
    )
    assert merged.status_code == 201
    assert merged.json()["operation"]["source_role_ids"] == [role_b_id]


def test_cross_generation_isolation(client: TestClient) -> None:
    """Source replacement 1 -> 2: generation-2 suggestions NEVER mix with the
    generation-1 suggestions; each generation grouping is isolated."""
    cluster = _api_seed()
    with _session() as session:
        _seed_video_source(session, cluster["video"], "s" * 64)
        _seed_completed_discover_job(session, cluster["video"], "1", "s" * 64)
        role_a = _role(session, cluster, "Hero", generation="1")
        role_b = _role(session, cluster, "Hero", generation="1")
        _occurrence(
            session, cluster, role_a.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40)
        )
        _occurrence(
            session, cluster, role_b.id, "scene_b", 105, time_ms=10500, bbox=(11, 10, 39, 41)
        )
        session.commit()
        gen1_ids = {role_a.id, role_b.id}
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    gen1 = client.post(
        url, json={"video_item_id": cluster["video"], "source_generation": "1"}
    )
    assert gen1.status_code == 201
    assert gen1.json()["created_count"] == 1
    suggestion1 = gen1.json()["suggestions"][0]
    assert suggestion1["source_generation"] == "1"
    assert set(suggestion1["role_ids"]) <= gen1_ids
    # Source replacement: generation 2 becomes the backend current.
    with _session() as session:
        _seed_video_source(session, cluster["video"], "t" * 64)
        _seed_completed_discover_job(session, cluster["video"], "2", "t" * 64)
        role_c = _role(session, cluster, "Hero", generation="2")
        role_d = _role(session, cluster, "Hero", generation="2")
        _occurrence(
            session, cluster, role_c.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40)
        )
        _occurrence(
            session, cluster, role_d.id, "scene_b", 105, time_ms=10500, bbox=(11, 10, 39, 41)
        )
        session.commit()
        gen2_ids = {role_c.id, role_d.id}
    gen2 = client.post(
        url, json={"video_item_id": cluster["video"], "source_generation": "2"}
    )
    assert gen2.status_code == 201
    suggestion2 = gen2.json()["suggestions"][0]
    assert suggestion2["source_generation"] == "2"
    assert set(suggestion2["role_ids"]) <= gen2_ids
    assert not (set(suggestion2["role_ids"]) & gen1_ids)
    # The two generations keep separate durable suggestions.
    with _session() as session:
        gens = {
            row.source_generation
            for row in session.scalars(select(ObjectGroupingSuggestion)).all()
        }
        assert gens == {"1", "2"}


def test_concurrent_split_single_operation_and_single_active_role(
    client: TestClient,
) -> None:
    """Two threads split the SAME merge: exactly one op + one created role.

    The duplicate request replays (never a second mutation): outcomes are
    exactly {created, replayed} and the active-role set never grows twice.
    """
    service = deps._job_service
    assert service is not None
    db_url = str(service._session_factory.kw["bind"].url)
    cluster = _api_seed()
    with _session() as session:
        role_a, role_b = _same_object_pair(session, cluster)
        a_id, b_id = role_a.id, role_b.id
        project_id, video_id = cluster["project"], cluster["video"]
    with _session() as session:
        operation, _target, _created = ObjectGroupingRepository(session).apply_merge(
            DEFAULT_WORKSPACE_ID, project_id, video_id, a_id, [b_id], 1
        )
        session.commit()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def writer() -> None:
        engine = create_engine_for_path(db_url)
        with Session(engine) as session:
            barrier.wait(timeout=30)
            try:
                operation, created_role, created = ObjectGroupingRepository(
                    session
                ).apply_split(
                    DEFAULT_WORKSPACE_ID,
                    project_id,
                    video_id,
                    a_id,
                    b_id,
                    2,
                )
                session.commit()
                outcome = "created" if created else "replayed"
            except (RoleConflictError, OperationConflictError):
                session.rollback()
                outcome = "conflict"
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "concurrent splitters hung"
    assert sorted(outcomes) == ["created", "replayed"], outcomes
    with _session() as session:
        split_ops = session.scalars(
            select(RoleOperation).where(
                RoleOperation.operation_type == "split",
                RoleOperation.target_role_id == a_id,
            )
        ).all()
        assert len(split_ops) == 1
        created_ids = [
            role_id
            for op in session.scalars(select(RoleOperation)).all()
            for role_id in _json_ids(op.created_role_ids_json)
        ]
        assert len(created_ids) == 1
        active = session.scalars(
            select(ObjectRole).where(
                ObjectRole.video_item_id == video_id,
                ObjectRole.status.in_(("suggested", "confirmed")),
            )
        ).all()
        assert len(active) == 2  # target A + the ONE restored role B'


def test_boundary_violations_zero_mutation(client: TestClient) -> None:
    """Cross-workspace/project/video/generation attempts mutate NOTHING."""
    cluster = _api_seed()
    with _session() as session:
        role_a = _role(session, cluster, "Hero", generation="1")
        role_gen2 = _role(session, cluster, "Hero", generation="2")
        role_other_video = _role(session, cluster, "Hero", video_key="video_other")
        _occurrence(session, cluster, role_a.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40))
        _occurrence(
            session, cluster, role_gen2.id, "scene_b", 105, time_ms=10500, bbox=(11, 10, 39, 41)
        )
        _occurrence(
            session,
            cluster,
            role_other_video.id,
            "scene_other",
            5,
            time_ms=500,
            bbox=(10, 10, 40, 40),
        )
        session.commit()
        foreign = ObjectIntelligenceRepository(session).create_role(
            cluster["foreign_workspace"],
            cluster["foreign_project"],
            cluster["foreign_video"],
            "1",
            "Hero",
        )
        session.commit()
        a_id, gen2_id, other_video_id, foreign_id = (
            role_a.id,
            role_gen2.id,
            role_other_video.id,
            foreign[0].id,
        )
    with _session() as session:
        before = {
            "ops": len(session.scalars(select(RoleOperation)).all()),
            "suggestions": len(session.scalars(select(ObjectGroupingSuggestion)).all()),
            "roles": {
                row.id: (row.status, row.revision)
                for row in session.scalars(select(ObjectRole)).all()
            },
            "occurrences": {
                row.id: (row.role_id, row.revision)
                for row in session.scalars(select(ObjectOccurrence)).all()
            },
        }
    # Cross-generation merge -> 409.
    assert (
        client.post(
            _merge_url(cluster).format(role_id=a_id),
            json=_merge_body(cluster, [gen2_id], 1),
        ).status_code
        == 409
    )
    # Cross-video merge -> 409.
    assert (
        client.post(
            _merge_url(cluster).format(role_id=a_id),
            json=_merge_body(cluster, [other_video_id], 1),
        ).status_code
        == 409
    )
    # Cross-workspace merge -> 409.
    assert (
        client.post(
            _merge_url(cluster).format(role_id=a_id),
            json=_merge_body(cluster, [foreign_id], 1),
        ).status_code
        == 409
    )
    # Cross-generation split (no lineage) -> 409.
    assert (
        client.post(
            _split_url(cluster).format(role_id=a_id),
            json={
                "video_item_id": cluster["video"],
                "revision": 1,
                "original_role_id": gen2_id,
            },
        ).status_code
        == 409
    )
    with _session() as session:
        after = {
            "ops": len(session.scalars(select(RoleOperation)).all()),
            "suggestions": len(session.scalars(select(ObjectGroupingSuggestion)).all()),
            "roles": {
                row.id: (row.status, row.revision)
                for row in session.scalars(select(ObjectRole)).all()
            },
            "occurrences": {
                row.id: (row.role_id, row.revision)
                for row in session.scalars(select(ObjectOccurrence)).all()
            },
        }
    assert before == after, "boundary violations mutated durable state"


def _json_ids(value: str) -> list[str]:
    import json as _json

    return [str(item) for item in _json.loads(value or "[]")]


# ── C2: current-generation suggestion listing / source replacement ─────────


def _two_generation_scenario(
    client: TestClient, cluster: dict[str, str]
) -> tuple[dict, dict]:
    """Drive source replacement 1 -> 2 with a suggestion per generation.

    Returns (gen1_suggestion, gen2_suggestion) API payloads.
    """
    with _session() as session:
        _seed_video_source(session, cluster["video"], "s" * 64)
        _seed_completed_discover_job(session, cluster["video"], "1", "s" * 64)
        role_a = _role(session, cluster, "Hero", generation="1")
        role_b = _role(session, cluster, "Hero", generation="1")
        _occurrence(
            session, cluster, role_a.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40)
        )
        _occurrence(
            session, cluster, role_b.id, "scene_b", 105, time_ms=10500, bbox=(11, 10, 39, 41)
        )
        session.commit()
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    gen1 = client.post(
        url, json={"video_item_id": cluster["video"], "source_generation": "1"}
    )
    assert gen1.status_code == 201
    gen1_suggestion = gen1.json()["suggestions"][0]
    with _session() as session:
        _seed_video_source(session, cluster["video"], "t" * 64)
        _seed_completed_discover_job(session, cluster["video"], "2", "t" * 64)
        role_c = _role(session, cluster, "Hero", generation="2")
        role_d = _role(session, cluster, "Hero", generation="2")
        _occurrence(
            session, cluster, role_c.id, "scene_a", 5, time_ms=500, bbox=(10, 10, 40, 40)
        )
        _occurrence(
            session, cluster, role_d.id, "scene_b", 105, time_ms=10500, bbox=(11, 10, 39, 41)
        )
        session.commit()
    gen2 = client.post(
        url, json={"video_item_id": cluster["video"], "source_generation": "2"}
    )
    assert gen2.status_code == 201
    gen2_suggestion = gen2.json()["suggestions"][0]
    return gen1_suggestion, gen2_suggestion


def test_suggestion_list_current_only_and_source_replacement(
    client: TestClient,
) -> None:
    """The public suggestion list defaults to ONLY the current generation;
    generation-1 suggestions never appear in the generation-2 list; the
    historical view is an explicit separate contract (never mixed)."""
    cluster = _api_seed()
    gen1_suggestion, gen2_suggestion = _two_generation_scenario(
        client, cluster
    )
    list_url = "/api/v2/object-intelligence/grouping/suggestions"
    current_list = client.get(
        list_url, params={"video_item_id": cluster["video"]}
    )
    assert current_list.status_code == 200
    current = current_list.json()
    assert current["scope"] == "current"
    assert current["current_generation"] == "2"
    ids = [s["id"] for s in current["suggestions"]]
    assert gen2_suggestion["id"] in ids
    assert gen1_suggestion["id"] not in ids  # generation-1 hidden from current
    # Historical: explicit generation=1 is the ONLY way to see gen-1 rows.
    historical = client.get(
        list_url,
        params={"video_item_id": cluster["video"], "source_generation": "1"},
    )
    assert historical.status_code == 200
    assert historical.json()["scope"] == "historical"
    hist_ids = [s["id"] for s in historical.json()["suggestions"]]
    assert gen1_suggestion["id"] in hist_ids
    assert gen2_suggestion["id"] not in hist_ids
    # Detail: current-scope 404 for the stale suggestion; explicit historical
    # generation returns it; the current suggestion is untouched.
    base = "/api/v2/object-intelligence/grouping/suggestions"
    assert client.get(f"{base}/{gen1_suggestion['id']}").status_code == 404
    assert (
        client.get(
            f"{base}/{gen1_suggestion['id']}",
            params={"source_generation": "1"},
        ).status_code
        == 200
    )
    assert client.get(f"{base}/{gen2_suggestion['id']}").status_code == 200


def test_stale_suggestion_and_role_fail_closed_zero_mutation(
    client: TestClient,
) -> None:
    """After source replacement, stale-generation actions fail closed with
    ZERO durable mutation; current-generation actions still work."""
    cluster = _api_seed()
    gen1_suggestion, gen2_suggestion = _two_generation_scenario(
        client, cluster
    )
    with _session() as session:
        stale_role_id = None
        stale_pair_ids: list[str] = []
        current_role_id = None
        for row in session.scalars(select(ObjectRole)).all():
            is_stale = row.source_generation == "1" and row.status != "superseded"
            is_current = row.source_generation == "2" and row.status != "superseded"
            if is_stale and stale_role_id is None:
                stale_role_id = row.id
            elif is_stale:
                stale_pair_ids.append(row.id)
            elif is_current and current_role_id is None:
                current_role_id = row.id
        if stale_role_id is None or current_role_id is None or not stale_pair_ids:
            raise AssertionError("expected one stale pair and one current role")

        def _snapshot() -> dict:
            return {
                "ops": len(session.scalars(select(RoleOperation)).all()),
                "suggestions": {
                    row.id: (row.status, row.revision)
                    for row in session.scalars(select(ObjectGroupingSuggestion)).all()
                },
                "roles": {
                    row.id: (row.status, row.revision)
                    for row in session.scalars(select(ObjectRole)).all()
                },
            }

        before = _snapshot()
    suggestion_base = "/api/v2/object-intelligence/grouping/suggestions"
    # Dismiss a STALE suggestion -> 409, zero mutation.
    assert (
        client.post(
            f"{suggestion_base}/{gen1_suggestion['id']}/dismiss",
            json={"revision": 1},
        ).status_code
        == 409
    )
    # Merge STALE roles -> 409, zero mutation.
    assert (
        client.post(
            _merge_url(cluster).format(role_id=stale_role_id),
            json=_merge_body(cluster, stale_pair_ids, 1),
        ).status_code
        == 409
    )
    # Merge WITH the stale suggestion -> 409, zero mutation.
    assert (
        client.post(
            _merge_url(cluster).format(role_id=stale_role_id),
            json=_merge_body(
                cluster, stale_pair_ids, 1, suggestion_id=gen1_suggestion["id"]
            ),
        ).status_code
        == 409
    )
    # Confirm a STALE role -> 409, zero mutation.
    assert (
        client.post(
            _confirm_url(cluster).format(role_id=stale_role_id),
            json={"video_item_id": cluster["video"], "revision": 1},
        ).status_code
        == 409
    )
    with _session() as session:
        assert before == _snapshot(), "stale actions mutated durable state"
    # Current-generation action still succeeds (guard is generation-specific).
    assert (
        client.post(
            _confirm_url(cluster).format(role_id=current_role_id),
            json={"video_item_id": cluster["video"], "revision": 1},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"{suggestion_base}/{gen2_suggestion['id']}/dismiss",
            json={"revision": 1},
        ).status_code
        == 200
    )


def test_generate_stale_generation_fails_closed(client: TestClient) -> None:
    """Generating for a non-current generation fails closed, ZERO mutation."""
    cluster = _api_seed()
    url = "/api/v2/object-intelligence/grouping/suggestions/generate"
    stale = client.post(
        url, json={"video_item_id": cluster["video"], "source_generation": "2"}
    )
    assert stale.status_code == 409
    with _session() as session:
        assert not session.scalars(select(ObjectGroupingSuggestion)).all()
        assert not session.scalars(select(RoleOperation)).all()


def test_repo_cross_workspace_fails_closed(client: TestClient) -> None:
    with _session() as session:
        cluster = _seed_cluster(session)
        role_a = _role(session, cluster, "Hero")
        session.commit()
        role_a_id = role_a.id
        repo = ObjectGroupingRepository(session)
        from app.persistence.object_grouping import SuggestionNotFoundError
        from app.persistence.object_intelligence import RoleNotFoundError
        with pytest.raises(SuggestionNotFoundError):
            repo.get_suggestion("no-such-workspace", str(uuid.uuid4()))
        # Cross-workspace reads of a foreign role fail closed (no leak).
        with pytest.raises(RoleNotFoundError):
            ObjectIntelligenceRepository(session).get_role(
                "no-such-workspace", role_a_id
            )

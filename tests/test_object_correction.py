"""Focused S08-T05 suite: targeted object correction + recompute.

Covers the dependency/invalidation graph (packet DESIGN.md): exact
affected/unaffected sets, byte/hash immutability of unaffected rows/files,
supersession/archive of affected derived state, durable job contracts
(restart/retry/cancel/concurrency/idempotency/no-orphan) and the
pre-confirmation impacted-scope report.

All tests run on the isolated conftest durable DB + managed root
(``deps._job_service``) — the REAL production wiring: the recompute job runs
through the REAL registered worker (``RECOMPUTE_OBJECTS`` handler).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path
from app.persistence.artifacts import ManagedRoot, hash_file
from app.persistence.jobs import JobRepository
from app.persistence.models import (
    Artifact,
    Job,
    ObjectCorrection,
    ObjectGroupingSuggestion,
    ObjectOccurrence,
    ObjectRole,
    ObjectRoleArtifact,
    Project,
    RoleOperation,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_correction import (
    JOB_TYPE_RECOMPUTE_OBJECTS,
    CorrectionConflictError,
    ObjectCorrectionRepository,
)
from app.persistence.object_grouping import ObjectGroupingRepository
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
    OccurrenceNotFoundError,
    RoleMediaRecord,
)
from app.services.object_correction import (
    CODE_CORRECTION_NOT_FOUND,
    CODE_ROLE_CHANGED,
    recompute_objects_handler,
)
from app.services.object_extraction import (
    PROVIDER_DETERMINISTIC,
    ExtractionError,
    submit_discover_objects,
)
from app.workflow.durable_worker import build_worker_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
SOURCE_MEDIA_BYTES = (bytes(range(1, 256)) * 48) + b"S08-T05-correction-source"
SOURCE_SHA = hashlib.sha256(SOURCE_MEDIA_BYTES).hexdigest()
GENERATION = "1"


def _alembic_config(path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return config


def _svc():
    service = deps._job_service
    assert service is not None
    assert service.session_factory is not None
    return service


def _session() -> Session:
    factory = _svc().session_factory
    assert factory is not None
    return factory()


def _run_worker(svc, max_claims: int = 5) -> int:
    claims = 0
    for _ in range(max_claims):
        claimed = svc.worker.run_once()
        if claimed == 0:
            break
        claims += claimed
    return claims


def _job_state(svc, job_id: str) -> str:
    with svc.session_factory() as session:
        return JobRepository(session).get_job(job_id).state


def _repo(session: Session) -> ObjectCorrectionRepository:
    return ObjectCorrectionRepository(session)


def _seed_video(
    session: Session,
    *,
    title: str = "Primary",
    scene_count: int = 2,
    width: int = 320,
    height: int = 240,
    duration_ms: int = 6000,
) -> dict[str, str]:
    workspace = session.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(workspace)
    project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="Correction Project")
    video = VideoItem(
        project=project,
        title=title,
        position=0,
        width=width,
        height=height,
        duration_ms=duration_ms,
        fps_num=30,
        fps_den=1,
    )
    session.add(project)
    session.flush()
    session.add(video)
    session.flush()
    rel = (
        f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video.id}/import/source.mp4"
    )
    managed_target = _svc().managed_root / rel
    managed_target.parent.mkdir(parents=True, exist_ok=True)
    managed_target.write_bytes(SOURCE_MEDIA_BYTES)
    source = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="video",
        relative_path=rel,
        state="ready",
        sha256=SOURCE_SHA,
        size_bytes=len(SOURCE_MEDIA_BYTES),
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    video.source_artifact_id = source.id
    scene_ids: list[str] = []
    for index in range(scene_count):
        scene = Scene(
            video_item=video,
            position=index,
            start_frame=index * 90,
            end_frame=index * 90 + 89,
            start_time_ms=index * 3000,
            end_time_ms=index * 3000 + 2999,
            status="pending",
        )
        session.add(scene)
        session.flush()
        scene_ids.append(scene.id)
    session.commit()
    return {
        "project": project.id,
        "video": video.id,
        "scenes": scene_ids,
    }


def _seed_source_job(session: Session, ids: dict[str, str]) -> str:
    """A REAL completed DISCOVER job row (satisfies the source_job_id FK)."""
    from sqlalchemy import update as sa_update

    from app.persistence.jobs import JobRepository, StepInput

    job = JobRepository(session).create_job(
        workspace_id=DEFAULT_WORKSPACE_ID,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=ids["video"],
        # The manifest MUST carry the video's real source sha256 so the
        # backend-authoritative current generation (T02-C2) links this job to
        # the source and resolves generation "1" (the roles' generation).
        input_manifest={"schema_version": 1, "source_sha256": SOURCE_SHA},
        idempotency_key=f"seed-job:{uuid.uuid4()}",
        input_generation="1",
        steps=[StepInput(step_code="extract", position=0, step_type="sync")],
        actor="system",
    )
    session.execute(
        sa_update(Job).where(Job.id == job.id).values(state="completed")
    )
    return job.id


def _seed_role(
    session: Session,
    ids: dict[str, str],
    *,
    name: str,
    source_job_id: str | None = None,
    candidate: bool = False,
    status: str = "suggested",
) -> ObjectRole:
    if candidate:
        source_job_id = _seed_source_job(session, ids)
    role = ObjectRole(
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=ids["project"],
        video_item_id=ids["video"],
        source_generation=GENERATION,
        name=name,
        kind="character",
        status=status,
        source_job_id=source_job_id,
    )
    session.add(role)
    session.flush()
    return role


def _seed_occurrence(
    session: Session,
    role: ObjectRole,
    scene_id: str,
    *,
    frame_index: int,
    bbox: tuple[int, int, int, int] = (10, 10, 40, 40),
    confidence: float = 0.6,
) -> ObjectOccurrence:
    occ = ObjectOccurrence(
        workspace_id=role.workspace_id,
        project_id=role.project_id,
        video_item_id=role.video_item_id,
        role_id=role.id,
        scene_id=scene_id,
        frame_index=frame_index,
        time_ms=frame_index * 33,
        bbox_x=bbox[0],
        bbox_y=bbox[1],
        bbox_w=bbox[2],
        bbox_h=bbox[3],
        confidence=confidence,
        confidence_source="detector",
        algorithm="deterministic-layout",
        algorithm_version="1.0.0",
        reasons_json=json.dumps(["deterministic-scene-layout"]),
        review_state="unreviewed",
    )
    session.add(occ)
    session.flush()
    return occ


def _seed_suggestion(
    session: Session,
    ids: dict[str, str],
    *,
    role_ids: list[str],
    confidence: float = 0.9,
) -> ObjectGroupingSuggestion:
    record, _created = ObjectGroupingRepository(session).create_suggestion(
        DEFAULT_WORKSPACE_ID,
        ids["project"],
        ids["video"],
        GENERATION,
        role_ids,
        confidence,
        ["same-normalized-name"],
        "role-fingerprint",
        "1",
    )
    return session.get(ObjectGroupingSuggestion, record.id)


def _seed_media(
    session: Session,
    role: ObjectRole,
    *,
    source_job_id: str,
    sha_prefix: str = "a",
    generation: str = GENERATION,
) -> dict[str, ObjectRoleArtifact]:
    """Seed an OLD active media association (thumbnail + mask) for a role.

    Simulates T02-C1 published DISCOVER media: ready artifact rows + active
    ObjectRoleArtifact rows keyed by stable role id.
    """
    associations: dict[str, ObjectRoleArtifact] = {}
    for idx, purpose in enumerate(("thumbnail", "mask")):
        artifact = Artifact(
            id=f"old-artifact-{role.id}-{purpose}",
            workspace_id=role.workspace_id,
            kind="image",
            relative_path=f"artifacts/{role.workspace_id}/image/{source_job_id}/"
            f"extract/{role.name}-{purpose}.png",
            state="ready",
            sha256=sha_prefix * 64,
            size_bytes=100 + idx,
            mime_type="image/png",
            width=64,
            height=64,
        )
        session.add(artifact)
        assoc = ObjectRoleArtifact(
            id=f"old-assoc-{role.id}-{purpose}",
            workspace_id=role.workspace_id,
            role_id=role.id,
            artifact_id=artifact.id,
            purpose=purpose,
            source_generation=generation,
            source_job_id=source_job_id,
        )
        session.add(assoc)
        associations[purpose] = assoc
    session.flush()
    return associations


def _association_snapshot(
    session: Session,
) -> list[tuple[Any, ...]]:
    """(id, role_id, artifact_id, purpose, generation, job, superseded_by)."""
    return [
        (
            row.id,
            row.role_id,
            row.artifact_id,
            row.purpose,
            row.source_generation,
            row.source_job_id,
            row.superseded_by_id,
        )
        for row in session.scalars(
            select(ObjectRoleArtifact).order_by(ObjectRoleArtifact.id)
        ).all()
    ]


def _snapshot_rows(session: Session) -> dict[str, list[tuple[Any, ...]]]:
    """Full-row snapshot of every S08 table (immutability evidence)."""

    def row_tuple(row: Any, columns: list[str]) -> tuple[Any, ...]:
        return tuple(getattr(row, column) for column in columns)

    return {
        "roles": [
            (
                row.id,
                row.workspace_id,
                row.project_id,
                row.video_item_id,
                row.source_generation,
                row.name,
                row.kind,
                row.status,
                row.supersedes_role_id,
                row.description,
                row.source_job_id,
                row.revision,
            )
            for row in session.scalars(select(ObjectRole).order_by(ObjectRole.id)).all()
        ],
        "occurrences": [
            (
                row.id,
                row.workspace_id,
                row.project_id,
                row.video_item_id,
                row.role_id,
                row.scene_id,
                row.frame_index,
                row.time_ms,
                row.bbox_x,
                row.bbox_y,
                row.bbox_w,
                row.bbox_h,
                row.confidence,
                row.confidence_source,
                row.reasons_json,
                row.review_state,
                row.revision,
            )
            for row in session.scalars(
                select(ObjectOccurrence).order_by(ObjectOccurrence.id)
            ).all()
        ],
        "suggestions": [
            (
                row.id,
                row.status,
                row.role_ids_json,
                row.confidence,
                row.reasons_json,
                row.natural_key,
                row.revision,
            )
            for row in session.scalars(
                select(ObjectGroupingSuggestion).order_by(
                    ObjectGroupingSuggestion.id
                )
            ).all()
        ],
        "artifacts": [
            (
                row.id,
                row.relative_path,
                row.state,
                row.sha256,
                row.size_bytes,
            )
            for row in session.scalars(select(Artifact).order_by(Artifact.id)).all()
        ],
    }


def _file_hashes(svc) -> dict[str, str]:
    """relative_path -> sha256 for every managed file (staging + artifacts)."""
    root = ManagedRoot(svc.managed_root).root
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            rel = str(file_path.relative_to(root)).replace("\\", "/")
            out[rel] = hash_file(file_path)
    return out


def _reassign_request(occ, source: ObjectRole, target: ObjectRole) -> dict[str, Any]:
    return {
        "kind": "reassign",
        "occurrence_id": occ.id,
        "occurrence_revision": occ.revision,
        "source_role_id": source.id,
        "target_role_id": target.id,
        "generation": source.source_generation,
    }


def _ctx(svc, job_id: str, *, crash_at: str | None = None):
    """Hand-built WorkerContext over the REAL job/step/DB (S05/T02 pattern)."""
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        repo = JobRepository(session)
        job = repo.get_job(job_id)
        step = repo.list_steps(job_id)[0]
        token = "test-fence-token"
        cp = step.checkpoint or {"schema_version": 1}

        def write_checkpoint(payload: dict) -> None:
            phase = payload.get("phase")
            if crash_at is not None and phase == crash_at:
                if crash_at == "staged":
                    with factory() as s2:
                        JobRepository(s2).write_checkpoint(
                            step.id, payload, fence_token=token
                        )
                        s2.commit()
                raise RuntimeError(f"simulated crash at {phase}")
            with factory() as s2:
                JobRepository(s2).write_checkpoint(step.id, payload, fence_token=token)
                s2.commit()

        def is_cancelled() -> bool:
            with factory() as s2:
                return JobRepository(s2).get_job(job_id).state == "cancelling"

        return build_worker_context(
            job_id=job.id,
            job_type=job.job_type,
            step_code=step.step_code,
            step_id=step.id,
            workspace_id=job.workspace_id,
            owner_type=job.owner_type,
            owner_id=job.owner_id,
            input_manifest=job.input_manifest,
            attempt=1,
            checkpoint=cp,
            worker_id="test-worker",
            fence_token=token,
            ttl_seconds=3600,
            progress=lambda value, message=None: None,
            write_checkpoint=write_checkpoint,
            is_cancelled=is_cancelled,
            staging_dir=lambda: svc.managed_root / "staging" / job_id / step.step_code,
            session_factory=factory,
        )


# ── Migration / constraints ─────────────────────────────────────────────────


def test_migration_round_trip_correction_surfaces(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    command.upgrade(_alembic_config(db), "head")
    command.downgrade(_alembic_config(db), "f3a4b5c6d7e8")
    command.upgrade(_alembic_config(db), "head")
    engine = create_engine_for_path(db)
    tables = set(inspect(engine).get_table_names())
    assert "object_correction" in tables
    with engine.connect() as conn:
        version = conn.execute(text("select version_num from alembic_version")).scalar()
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(object_correction)"))}
        assoc_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(object_role_artifact)"))
        }
        assoc_fk = conn.execute(text("PRAGMA foreign_key_list(object_role_artifact)")).fetchall()
    heads = sorted(ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads())
    # S09-T00-I04: live runtime contract — DB revision must equal the current
    # ScriptDirectory head; single-head guard keeps this stricter than a pin.
    assert len(heads) == 1, f"expected exactly one Alembic head, got {heads}"
    assert version == heads[0]
    # S08-T05-C1 (finding D): the media supersession column + self-FK exist.
    assert "superseded_by_id" in assoc_cols
    assert any(r[3] == "superseded_by_id" and r[2] == "object_role_artifact" for r in assoc_fk)
    assert {
        "id",
        "workspace_id",
        "project_id",
        "video_item_id",
        "correction_type",
        "status",
        "request_json",
        "impact_json",
        "result_json",
        "recompute_job_id",
        "applied_at",
        "idempotency_key",
        "natural_key",
        "revision",
    } <= cols


def test_correction_constraints_real(tmp_path: Path) -> None:
    db = tmp_path / "constraints.db"
    command.upgrade(_alembic_config(db), "head")
    engine = create_engine_for_path(db)
    with Session(engine) as session:
        ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(ws)
        session.flush()
        project = Project(workspace_id=ws.id, name="P")
        video = VideoItem(project=project, title="V", position=0)
        session.add_all([project, video])
        session.flush()
        bad = ObjectCorrection(
            workspace_id=ws.id,
            project_id=project.id,
            video_item_id=video.id,
            correction_type="bogus",
            status="pending",
            request_json="{}",
            impact_json="{}",
        )
        session.add(bad)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


# ── Impact: exact sets, read-only ───────────────────────────────────────────


def test_impact_reassign_exact_sets_and_zero_mutations(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="Hero-A")
        role_b = _seed_role(session, ids, name="Hero-B")
        role_c = _seed_role(session, ids, name="Hero-C")
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        _seed_occurrence(session, role_b, ids["scenes"][1], frame_index=95)
        occ_c = _seed_occurrence(session, role_c, ids["scenes"][0], frame_index=7)
        s1 = _seed_suggestion(session, ids, role_ids=[role_a.id, role_c.id])
        s2 = _seed_suggestion(session, ids, role_ids=[role_b.id, role_c.id])
        session.commit()
        before = _snapshot_rows(session)
        impact = _repo(session).compute_impact(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            "reassign",
            _reassign_request(occ_a, role_a, role_b),
        )
        after = _snapshot_rows(session)
    assert impact.affected_role_ids == sorted([role_a.id, role_b.id])
    assert impact.affected_occurrence_ids == [occ_a.id]
    assert impact.invalidated_suggestion_ids == sorted([s1.id, s2.id])
    assert impact.artifact_role_ids == []  # no DISCOVER candidate roles
    assert impact.regenerate_suggestions is True
    assert impact.recompute_needed is True
    assert impact.counts["total_roles"] == 3
    assert impact.counts["total_occurrences"] == 3
    # PURE read: no row changed.
    assert after == before
    assert occ_c.id not in impact.affected_occurrence_ids


def test_impact_candidate_edit_role_and_occurrence(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids, name="Hero", candidate=True)
        occ = _seed_occurrence(session, role, ids["scenes"][0], frame_index=5)
        session.commit()
        edit_role = _repo(session).compute_impact(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            "candidate_edit",
            {
                "kind": "candidate_edit",
                "target": "role",
                "role_id": role.id,
                "role_revision": role.revision,
                "name": "Renamed",
                "generation": GENERATION,
            },
        )
        edit_occ = _repo(session).compute_impact(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            "candidate_edit",
            {
                "kind": "candidate_edit",
                "target": "occurrence",
                "role_id": role.id,
                "occurrence_id": occ.id,
                "occurrence_revision": occ.revision,
                "bbox": {"x": 5, "y": 5, "width": 30, "height": 30},
                "generation": GENERATION,
            },
        )
    # Name/kind edits never recompute artifacts (no geometry change).
    assert edit_role.artifact_role_ids == []
    assert edit_role.affected_role_ids == [role.id]
    # Geometry edits recompute the candidate role's artifacts.
    assert edit_occ.artifact_role_ids == [role.id]
    assert edit_occ.affected_occurrence_ids == [occ.id]


def test_impact_merge_and_split_sets(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        target = _seed_role(session, ids, name="Target", candidate=True)
        source = _seed_role(session, ids, name="Source", candidate=True)
        _seed_occurrence(session, target, ids["scenes"][0], frame_index=1)
        occ_s = _seed_occurrence(session, source, ids["scenes"][1], frame_index=91)
        session.commit()
        impact = _repo(session).compute_impact(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            "merge",
            {
                "kind": "merge",
                "target_role_id": target.id,
                "target_revision": target.revision,
                "source_role_ids": [source.id],
                "generation": GENERATION,
            },
        )
    assert impact.affected_role_ids == sorted([target.id, source.id])
    assert impact.affected_occurrence_ids == [occ_s.id]
    assert impact.artifact_role_ids == sorted([target.id, source.id])


def test_impact_fail_closed(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A")
        role_b = _seed_role(session, ids, name="B")
        role_b.status = "superseded"
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        repo = _repo(session)
        # Superseded role can never be part of a correction.
        with pytest.raises(CorrectionConflictError):
            repo.compute_impact(
                DEFAULT_WORKSPACE_ID,
                ids["project"],
                ids["video"],
                "reassign",
                _reassign_request(occ_a, role_a, role_b),
            )
        # Unknown kind -> 422-semantics ValueError.
        with pytest.raises(ValueError):
            repo.compute_impact(
                DEFAULT_WORKSPACE_ID,
                ids["project"],
                ids["video"],
                "bogus",
                {},
            )
        # Occurrence not owned by the source role -> fail closed.
        with pytest.raises(OccurrenceNotFoundError):
            repo.compute_impact(
                DEFAULT_WORKSPACE_ID,
                ids["project"],
                ids["video"],
                "reassign",
                {
                    **{
                        "kind": "reassign",
                        "occurrence_id": occ_a.id,
                        "occurrence_revision": occ_a.revision,
                        "source_role_id": role_b.id,
                        "target_role_id": role_a.id,
                        "generation": GENERATION,
                    }
                },
            )


def test_recompute_needed_only_where_needed(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A")  # no source_job_id
        role_b = _seed_role(session, ids, name="B")
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        impact = _repo(session).compute_impact(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            "reassign",
            _reassign_request(occ_a, role_a, role_b),
        )
    assert impact.invalidated_suggestion_ids == []
    assert impact.artifact_role_ids == []
    assert impact.recompute_needed is False
    assert impact.regenerate_suggestions is False


# ── Create: natural-key idempotency + concurrency ───────────────────────────


def _create_pending(session: Session, ids: dict[str, str], request: dict[str, Any]):
    impact = _repo(session).compute_impact(
        DEFAULT_WORKSPACE_ID, ids["project"], ids["video"], request["kind"], request
    )
    return _repo(session).create_correction(
        DEFAULT_WORKSPACE_ID,
        ids["project"],
        ids["video"],
        request["kind"],
        request,
        impact,
    )


def test_create_pending_natural_key_replay(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A")
        role_b = _seed_role(session, ids, name="B")
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record1, created1 = _create_pending(session, ids, request)
        session.commit()
        record2, created2 = _create_pending(session, ids, request)
        session.commit()
    assert created1 is True and created2 is False
    assert record1.id == record2.id
    assert record1.status == "pending"
    assert record1.natural_key == record2.natural_key


def test_create_natural_key_collision_conflict(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A")
        role_b = _seed_role(session, ids, name="B")
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        _create_pending(session, ids, request)
        session.commit()
        # Same key payload shape but different revision -> different natural
        # key is ALLOWED (a new correction), while a materially different
        # payload under the same natural key is impossible (content-derived).
        other = {**request, "occurrence_revision": request["occurrence_revision"] + 1}
        record, created = _create_pending(session, ids, other)
        session.commit()
    assert created is True
    assert record.request["occurrence_revision"] == request["occurrence_revision"] + 1


def test_concurrent_create_single_row(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A")
        role_b = _seed_role(session, ids, name="B")
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)

    results: list[Any] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        with _session() as session:
            barrier.wait()
            try:
                record, created = _create_pending(session, ids, request)
                session.commit()
                results.append((record.id, created))
            except IntegrityError:
                session.rollback()
                record, created = _create_pending(session, ids, request)
                session.commit()
                results.append((record.id, created))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    with _session() as session:
        count = session.scalar(
            select(func.count()).select_from(ObjectCorrection)
        )
    assert len(results) == 2
    assert len({record_id for record_id, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    assert count == 1


# ── Confirm: reassign with full immutability evidence ───────────────────────


def _seed_discover_artifacts(svc) -> tuple[dict[str, str], dict[str, str]]:
    """Real DISCOVER run (deterministic provider) -> roles with artifacts."""
    with svc.session_factory() as session:
        ids = _seed_video(session)
        session.flush()
    result = submit_discover_objects(
        svc.session_factory,
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=ids["project"],
        video_item_id=ids["video"],
        source_sha256=SOURCE_SHA,
        generation="1",
        provider=PROVIDER_DETERMINISTIC,
        managed_root=svc.managed_root,
        env={"MOTIONFORGE_EXTRACTION_QA_MODE": "1"},
    )
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    return ids, {"job_id": result.job_id}


def test_confirm_reassign_moves_evidence_and_preserves_unaffected(
    client: TestClient,
) -> None:
    svc = _svc()
    ids, discover = _seed_discover_artifacts(svc)
    with _session() as session:
        roles = session.scalars(
            select(ObjectRole).where(ObjectRole.video_item_id == ids["video"])
        ).all()
        assert len(roles) == 2  # subject_01 (scene 0) + subject_02 (scene 1)
        role_a = next(r for r in roles if r.name == "subject_01")
        role_b = next(r for r in roles if r.name == "subject_02")
        role_c = _seed_role(session, ids, name="Hero-C")  # NOT a candidate
        _seed_occurrence(session, role_c, ids["scenes"][0], frame_index=7)
        s1 = _seed_suggestion(session, ids, role_ids=[role_a.id, role_c.id])
        s2 = _seed_suggestion(session, ids, role_ids=[role_b.id, role_c.id])
        session.commit()
        occ_a = session.scalars(
            select(ObjectOccurrence).where(ObjectOccurrence.role_id == role_a.id)
        ).first()
        assert occ_a is not None
        request = _reassign_request(occ_a, role_a, role_b)
        record, created = _create_pending(session, ids, request)
        session.commit()
        before_rows = _snapshot_rows(session)
    before_files = _file_hashes(svc)
    assert len(before_files) >= 5  # 2 thumbnails + 2 masks + manifest

    with _session() as session:
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    assert applied is True
    assert confirmed.status == "applied"
    assert confirmed.recompute_job_id is not None
    assert confirmed.result["from_role_id"] == role_a.id
    assert confirmed.result["to_role_id"] == role_b.id

    with _session() as session:
        after_rows = _snapshot_rows(session)
        moved = session.get(ObjectOccurrence, occ_a.id)
        assert moved is not None
        assert moved.role_id == role_b.id
        assert moved.revision == occ_a.revision + 1
        # Occurrence CONTENT byte-identical (only role_id/revision/updated_at).
        assert moved.bbox_x == occ_a.bbox_x and moved.bbox_y == occ_a.bbox_y
        assert moved.confidence == occ_a.confidence
        assert moved.reasons_json == occ_a.reasons_json
        # Unaffected role C row untouched.
        role_c_after = session.get(ObjectRole, role_c.id)
        assert role_c_after is not None
        assert role_c_after.revision == 1 and role_c_after.status == "suggested"
        # Invalidated suggestions superseded; unaffected rows byte-identical.
        s1_after = session.get(ObjectGroupingSuggestion, s1.id)
        s2_after = session.get(ObjectGroupingSuggestion, s2.id)
        assert s1_after.status == "superseded" and s1_after.natural_key is None
        assert s2_after.status == "superseded" and s2_after.natural_key is None
    # Unaffected ROWS: the only diffs are the moved occurrence + role A/B
    # revision bumps + superseded suggestions + the new correction row.
    role_a_b = {role_a.id, role_b.id}
    for table in ("roles", "occurrences", "suggestions"):
        before = {entry[0]: entry for entry in before_rows[table]}
        after = {entry[0]: entry for entry in after_rows[table]}
        assert set(before) <= set(after)  # nothing deleted
        for row_id, before_entry in before.items():
            after_entry = after[row_id]
            if table == "occurrences" and row_id == occ_a.id:
                assert after_entry[4] == role_b.id  # role_id changed
                assert after_entry[16] == before_entry[16] + 1  # revision +1
                continue
            if table == "roles" and row_id in role_a_b:
                assert after_entry[11] == before_entry[11] + 1  # revision bump
                continue
            if table == "suggestions" and row_id in (s1.id, s2.id):
                continue  # superseded (asserted above)
            assert after_entry == before_entry, (
                f"unaffected {table} row {row_id} changed"
            )

    # Run the recompute job through the REAL worker.
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    after_files = _file_hashes(svc)
    # Every pre-existing file byte-identical; new files only under the
    # recompute job's own path.
    for rel, sha in before_files.items():
        assert after_files.get(rel) == sha, f"file {rel} changed bytes"
    new_files = set(after_files) - set(before_files)
    assert new_files
    recompute_prefix = f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{confirmed.recompute_job_id}/"
    assert all(rel.startswith(recompute_prefix) for rel in new_files)
    # No-orphan: every recompute file has a ready artifact row.
    with _session() as session:
        rows = session.scalars(
            select(Artifact).where(
                Artifact.relative_path.like(recompute_prefix + "%")
            )
        ).all()
        row_paths = {row.relative_path for row in rows}
        assert row_paths == new_files
        assert all(row.state == "ready" for row in rows)
        # Any regenerated suggestion involves ONLY affected roles (the
        # deterministic algorithm decides WHICH pairs exist — correction
        # recompute never invents unaffected pairs).
        new_suggestions = session.scalars(
            select(ObjectGroupingSuggestion).where(
                ObjectGroupingSuggestion.status == "pending"
            )
        ).all()
        affected = {role_a.id, role_b.id}
        for suggestion in new_suggestions:
            ids_json = json.loads(suggestion.role_ids_json)
            assert affected.intersection(ids_json), (
                f"suggestion {suggestion.id} does not involve an affected role"
            )


def test_confirm_reassign_collision_fails_closed_zero_effects(
    client: TestClient,
) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        # B already owns (scene 0, frame 5) -> collision.
        _seed_occurrence(session, role_b, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        with pytest.raises(CorrectionConflictError):
            _repo(session).confirm_correction(
                DEFAULT_WORKSPACE_ID, record.id, record.revision,
                managed_root=str(svc.managed_root),
            )
        session.rollback()
        # Zero effects: correction still pending, no recompute job, no
        # supersession.
        assert session.get(ObjectCorrection, record.id).status == "pending"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.job_type == JOB_TYPE_RECOMPUTE_OBJECTS)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(ObjectGroupingSuggestion)
            )
            == 0
        )
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_a.id


def test_confirm_reassign_stale_revision_conflict(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        # A concurrent writer moves the occurrence's revision.
        from app.persistence.object_intelligence import ObjectIntelligenceRepository

        ObjectIntelligenceRepository(session).update_occurrence(
            DEFAULT_WORKSPACE_ID,
            role_a.id,
            occ_a.id,
            occ_a.revision,
            review_state="accepted",
        )
        session.commit()
        with pytest.raises(CorrectionConflictError):
            _repo(session).confirm_correction(
                DEFAULT_WORKSPACE_ID, record.id, record.revision,
                managed_root=str(svc.managed_root),
            )
        session.rollback()
        assert session.get(ObjectCorrection, record.id).status == "pending"
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_a.id


def test_confirm_candidate_edit_role_and_occurrence(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids, name="Hero", candidate=True)
        occ = _seed_occurrence(session, role, ids["scenes"][0], frame_index=5)
        s1 = _seed_suggestion(session, ids, role_ids=[role.id])
        session.commit()
        role_rev_before = role.revision
        edit = {
            "kind": "candidate_edit",
            "target": "role",
            "role_id": role.id,
            "role_revision": role.revision,
            "name": "Renamed Hero",
            "generation": GENERATION,
        }
        record, _created = _create_pending(session, ids, edit)
        session.commit()
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    assert applied is True
    assert confirmed.result["edited"] == "role"
    assert confirmed.result["fields"] == ["name"]
    with _session() as session:
        role_after = session.get(ObjectRole, role.id)
        assert role_after.name == "Renamed Hero"
        assert role_after.revision == role_rev_before + 1
        assert session.get(ObjectGroupingSuggestion, s1.id).status == "superseded"
        assert session.get(ObjectOccurrence, occ.id).revision == 1  # untouched
    # Name edit: suggestion regeneration ONLY — no artifact recompute.
    assert confirmed.recompute_job_id is not None
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        prefix = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{confirmed.recompute_job_id}/"
        )
        rows = session.scalars(
            select(Artifact).where(Artifact.relative_path.like(prefix + "%"))
        ).all()
        # Only the result manifest (kind document) — zero IMAGE artifacts:
        # a name edit never recomputes geometry-derived media.
        assert len(rows) == 1 and rows[0].kind == "document"


def test_confirm_candidate_edit_occurrence_bbox_recomputes_artifacts(
    client: TestClient,
) -> None:
    svc = _svc()
    ids, discover = _seed_discover_artifacts(svc)
    with _session() as session:
        role = session.scalars(
            select(ObjectRole).where(
                ObjectRole.video_item_id == ids["video"],
                ObjectRole.name == "subject_01",
            )
        ).first()
        assert role is not None
        occ = session.scalars(
            select(ObjectOccurrence).where(ObjectOccurrence.role_id == role.id)
        ).first()
        assert occ is not None
        old_thumbnails = {
            row.relative_path: row.sha256
            for row in session.scalars(
                select(Artifact).where(
                    Artifact.relative_path.like(f"artifacts/%/image/{discover['job_id']}/%")
                )
            ).all()
            if row.relative_path.endswith("_thumbnail.png")
            or "thumbnail" in row.relative_path
        }
        request = {
            "kind": "candidate_edit",
            "target": "occurrence",
            "role_id": role.id,
            "occurrence_id": occ.id,
            "occurrence_revision": occ.revision,
            "bbox": {"x": 60, "y": 50, "width": 80, "height": 90},
            "generation": GENERATION,
        }
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    assert applied is True
    assert confirmed.recompute_job_id is not None
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        moved = session.get(ObjectOccurrence, occ.id)
        assert moved.bbox_x == 60 and moved.bbox_h == 90
        # Old artifacts byte-identical (historical evidence preserved).
        for rel, sha in old_thumbnails.items():
            row = session.scalars(
                select(Artifact).where(Artifact.relative_path == rel)
            ).first()
            assert row is not None and row.sha256 == sha and row.state == "ready"
        # New recompute artifacts exist for the role with DIFFERENT bytes.
        new_rows = session.scalars(
            select(Artifact).where(
                Artifact.relative_path.like(
                    f"artifacts/{DEFAULT_WORKSPACE_ID}/image/"
                    f"{confirmed.recompute_job_id}/%thumbnail%"
                )
            )
        ).all()
        assert len(new_rows) == 1
        assert new_rows[0].sha256 not in old_thumbnails.values()


# ── Confirm: merge / split through the correction flow ──────────────────────


def test_confirm_merge_via_correction(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        target = _seed_role(session, ids, name="Target", candidate=True)
        source = _seed_role(session, ids, name="Source", candidate=True)
        _seed_occurrence(session, target, ids["scenes"][0], frame_index=1)
        occ_s = _seed_occurrence(session, source, ids["scenes"][1], frame_index=91)
        s1 = _seed_suggestion(session, ids, role_ids=[target.id, source.id])
        session.commit()
        request = {
            "kind": "merge",
            "target_role_id": target.id,
            "target_revision": target.revision,
            "source_role_ids": [source.id],
            "generation": GENERATION,
        }
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    assert applied is True
    assert confirmed.result["operation_type"] == "merge"
    with _session() as session:
        source_after = session.get(ObjectRole, source.id)
        assert source_after.status == "superseded"
        assert source_after.supersedes_role_id == target.id
        assert session.get(ObjectOccurrence, occ_s.id).role_id == target.id
        assert session.get(ObjectGroupingSuggestion, s1.id).status == "superseded"
        ops = session.scalars(select(RoleOperation)).all()
        assert len(ops) == 1 and ops[0].operation_type == "merge"
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"


def test_confirm_split_via_correction_recomputes_new_role(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        target = _seed_role(session, ids, name="Merged", candidate=True)
        original = _seed_role(session, ids, name="Original", candidate=True)
        _seed_occurrence(session, target, ids["scenes"][0], frame_index=1)
        occ_o = _seed_occurrence(session, original, ids["scenes"][1], frame_index=91)
        # Build a real T03 merge lineage first.
        grouping = ObjectGroupingRepository(session)
        op, _target, _created = grouping.apply_merge(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            target.id,
            [original.id],
            target.revision,
        )
        session.commit()
        target_after = session.get(ObjectRole, target.id)
        request = {
            "kind": "split",
            "target_role_id": target.id,
            "target_revision": target_after.revision,
            "original_role_id": original.id,
            "generation": GENERATION,
        }
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
        created_role_id = confirmed.result["created_role_id"]
    assert applied is True
    with _session() as session:
        assert session.get(ObjectOccurrence, occ_o.id).role_id == created_role_id
        created = session.get(ObjectRole, created_role_id)
        assert created is not None and created.status == "suggested"
        # The recompute manifest carries BOTH target and the new role.
        job = JobRepository(session).get_job(confirmed.recompute_job_id)
        assert set(job.input_manifest["affected_role_ids"]) == {
            target.id,
            created_role_id,
        }
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"


def test_confirm_no_recompute_when_not_needed(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A")  # no source_job_id
        role_b = _seed_role(session, ids, name="B")
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    assert applied is True
    assert confirmed.recompute_job_id is None
    assert confirmed.result["from_role_id"] == role_a.id
    with _session() as session:
        assert _repo(session).recompute_state(
            DEFAULT_WORKSPACE_ID, record.id
        )["recompute_needed"] is False


# ── Confirm: replay / concurrency / atomic rollback ─────────────────────────


def test_confirm_replay_returns_same_result_no_second_mutation(
    client: TestClient,
) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
        replay, applied_again = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    assert applied is True and applied_again is False
    assert replay.id == confirmed.id
    assert replay.result == confirmed.result
    assert replay.recompute_job_id == confirmed.recompute_job_id
    with _session() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.job_type == JOB_TYPE_RECOMPUTE_OBJECTS)
            )
            == 1
        )


def test_concurrent_confirm_exactly_one_wins(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()

    outcomes: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    CONFIRM_ATTEMPTS = 20

    def worker() -> None:
        # S08-H02-C4 (Finding 4): capture the returned `created` boolean —
        # True = this thread applied, False = the other thread already
        # committed (replay).  A replayed confirm is NEVER misclassified as a
        # fresh apply.  Transient SQLite "database is locked" between the two
        # concurrent writer threads is retried with a small backoff (bounded);
        # the product CAS in confirm_correction is untouched — exactly one
        # thread can ever transition pending->applied.
        with _session() as session:
            barrier.wait()
            created: bool | None = None
            for attempt in range(CONFIRM_ATTEMPTS):
                try:
                    _record, created = _repo(session).confirm_correction(
                        DEFAULT_WORKSPACE_ID, record.id, record.revision,
                        managed_root=str(svc.managed_root),
                    )
                    session.commit()
                    break
                except CorrectionConflictError:
                    session.rollback()
                    created = None
                except OperationalError:
                    # SQLite file-lock contention between the two writers —
                    # transient, not a product failure.
                    session.rollback()
                    created = None
                time.sleep(0.02 * (attempt + 1))
            assert created is not None, "confirm_correction never succeeded"
            with lock:
                outcomes.append("applied" if created else "replayed")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == ["applied", "replayed"]
    with _session() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.job_type == JOB_TYPE_RECOMPUTE_OBJECTS)
            )
            == 1
        )
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_b.id


# ── Durable recompute job: restart / cancel / retry / orphan ────────────────


def _confirmed_correction_with_job(svc, ids, roles_with_artifacts: bool = True):
    with _session() as session:
        role_a = _seed_role(
            session, ids, name="A", candidate=roles_with_artifacts
        )
        role_b = _seed_role(
            session, ids, name="B", candidate=roles_with_artifacts
        )
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        # A keeps a second occurrence so BOTH roles still derive artifacts
        # after the move (A: frame 8; B: frame 95 + moved frame 5).
        _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=8)
        _seed_occurrence(session, role_b, ids["scenes"][1], frame_index=95)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, _applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
        return confirmed


def test_recompute_restart_at_staging_boundary_no_duplicates(
    client: TestClient,
) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    # Crash after the staged checkpoint commit, before publish.
    with pytest.raises(RuntimeError, match="simulated crash"):
        recompute_objects_handler(_ctx(svc, confirmed.recompute_job_id, crash_at="staged"))
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        prefix = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{confirmed.recompute_job_id}/"
        )
        rows = session.scalars(
            select(Artifact).where(Artifact.relative_path.like(prefix + "%"))
        ).all()
        assert len({row.relative_path for row in rows}) == len(rows)  # no dup
        assert len(rows) >= 5  # 2 roles x 2 artifacts + manifest
    assert not any(
        "staging" in rel for rel in _file_hashes(svc)
    )


def test_recompute_restart_at_commit_boundary_no_duplicates(
    client: TestClient,
) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    # Crash between the effect commit and the published checkpoint write.
    with pytest.raises(RuntimeError, match="simulated crash"):
        recompute_objects_handler(_ctx(svc, confirmed.recompute_job_id, crash_at="published"))
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        prefix = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{confirmed.recompute_job_id}/"
        )
        rows = session.scalars(
            select(Artifact).where(Artifact.relative_path.like(prefix + "%"))
        ).all()
        assert len(rows) == 5  # exactly one effect set (no duplicates)
        assert all(row.state == "ready" for row in rows)


def test_cancel_during_recompute_drains_with_zero_effects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.object_correction as correction_service

    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        correction_service, "PHASE_HOOK", lambda phase: (entered.set(), release.wait(10))
    )
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert entered.wait(timeout=10)
    assert svc.cancel_job(confirmed.recompute_job_id) is True
    release.set()
    worker_thread.join(timeout=30)
    assert not worker_thread.is_alive()
    assert _job_state(svc, confirmed.recompute_job_id) == "cancelled"
    with _session() as session:
        prefix = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{confirmed.recompute_job_id}/"
        )
        rows = session.scalars(
            select(Artifact).where(Artifact.relative_path.like(prefix + "%"))
        ).all()
        assert rows == []  # zero rows
        assert (
            session.scalar(
                select(func.count()).select_from(ObjectGroupingSuggestion)
            )
            == 0
        )
    assert not any(
        "staging" in rel for rel in _file_hashes(svc)
    )


def test_cancel_pending_and_confirm_after_cancel_conflict(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        cancelled = _repo(session).cancel_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision
        )
        session.commit()
        # Cancel replay is state-idempotent.
        replay = _repo(session).cancel_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision
        )
        session.commit()
    assert cancelled.status == "cancelled"
    assert replay.status == "cancelled"
    with _session() as session:
        with pytest.raises(CorrectionConflictError):
            _repo(session).confirm_correction(
                DEFAULT_WORKSPACE_ID, record.id, record.revision,
                managed_root=str(svc.managed_root),
            )
        session.rollback()
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_a.id


def test_retry_recompute_after_cancel_successor_completes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.object_correction as correction_service

    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        correction_service, "PHASE_HOOK", lambda phase: (entered.set(), release.wait(10))
    )
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert entered.wait(timeout=10)
    assert svc.cancel_job(confirmed.recompute_job_id) is True
    release.set()
    worker_thread.join(timeout=30)
    assert _job_state(svc, confirmed.recompute_job_id) == "cancelled"
    monkeypatch.setattr(correction_service, "PHASE_HOOK", None)

    with _session() as session:
        successor_id = _repo(session).create_recompute_successor(
            DEFAULT_WORKSPACE_ID, confirmed.id
        )
        session.commit()
    assert successor_id != confirmed.recompute_job_id
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "cancelled"  # immutable
    assert _job_state(svc, successor_id) == "completed"
    with _session() as session:
        assert (
            _repo(session).recompute_state(DEFAULT_WORKSPACE_ID, confirmed.id)["job_id"]
            == successor_id
        )


def test_recompute_stale_roles_fail_closed(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    # A NEWER correction supersedes an affected role before the job runs.
    with _session() as session:
        roles = session.scalars(select(ObjectRole)).all()
        target = next(r for r in roles if r.name == "B")
        target.status = "superseded"
        session.commit()
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "failed"
    with _session() as session:
        job = JobRepository(session).get_job(confirmed.recompute_job_id)
        assert job.error is not None
        assert job.error.get("error_code") == CODE_ROLE_CHANGED


def test_orphan_staging_partials_cleaned_on_rerun(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    staging = svc.managed_root / "staging" / confirmed.recompute_job_id / "recompute"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "role_thumbnail.png.deadbeef.staging").write_bytes(b"partial")
    stray = svc.managed_root / "staging" / str(uuid.uuid4()) / "recompute"
    stray.mkdir(parents=True, exist_ok=True)
    stray_partial = stray / "role_thumbnail.png.deadbeef.staging"
    stray_partial.write_bytes(b"partial")
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    staging_files = [
        rel for rel in _file_hashes(svc) if rel.startswith("staging/")
    ]
    assert staging_files == [str(stray_partial.relative_to(svc.managed_root)).replace("\\", "/")]


def test_corrupt_recompute_artifact_fails_replay(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        artifact = session.scalars(
            select(Artifact)
            .where(Artifact.kind == "image")
            .where(
                Artifact.relative_path.like(
                    f"artifacts/{DEFAULT_WORKSPACE_ID}/image/"
                    f"{confirmed.recompute_job_id}/%"
                )
            )
            .limit(1)
        ).first()
        assert artifact is not None
        rel = artifact.relative_path
    ManagedRoot(svc.managed_root).resolve(rel).write_bytes(b"corrupted")
    with pytest.raises(ExtractionError) as err:
        recompute_objects_handler(_ctx(svc, confirmed.recompute_job_id))
    assert err.value.code == "PUBLICATION_FAILED"


def test_missing_correction_row_fails_recompute(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed = _confirmed_correction_with_job(svc, ids)
    with _session() as session:
        row = session.get(ObjectCorrection, confirmed.id)
        assert row is not None
        session.delete(row)
        session.commit()
    with pytest.raises(ExtractionError) as err:
        recompute_objects_handler(_ctx(svc, confirmed.recompute_job_id))
    assert err.value.code == CODE_CORRECTION_NOT_FOUND


def test_get_and_impact_operations_zero_durable_mutations(client: TestClient) -> None:
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        before = _snapshot_rows(session)
        _repo(session).compute_impact(
            DEFAULT_WORKSPACE_ID,
            ids["project"],
            ids["video"],
            "reassign",
            request,
        )
        _repo(session).get_correction(DEFAULT_WORKSPACE_ID, record.id)
        _repo(session).list_corrections(DEFAULT_WORKSPACE_ID)
        _repo(session).recompute_state(DEFAULT_WORKSPACE_ID, record.id)
        after = _snapshot_rows(session)
    assert after == before


# ══════════════════════════════════════════════════════════════════════════
# S08-T05-C1 (finding D): corrected media becomes canonical.
# RECOMPUTE_OBJECTS REPLACES the affected roles' media links (new
# associations + artifacts under the recompute job; old associations
# superseded via the self-FK, still auditable), resolution serves the
# newest valid media, unaffected links/bytes stay identical, rename keeps
# media, and queued cancel is covered alongside running cancel.
# ══════════════════════════════════════════════════════════════════════════


def _resolve_media(session: Session, role_id: str) -> list[RoleMediaRecord]:
    """The newest valid media of a role via the PUBLIC repository API."""
    return ObjectIntelligenceRepository(session).get_role(
        DEFAULT_WORKSPACE_ID, role_id
    ).media


def _confirmed_geometry_correction_with_media(svc, ids) -> Any:
    """A reassign correction whose affected candidate roles already have
    OLD DISCOVER media associations; returns (confirmed, role_a, old_by_role)."""
    with _session() as session:
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        _seed_media(session, role_a, source_job_id=role_a.source_job_id)
        _seed_media(session, role_b, source_job_id=role_b.source_job_id)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=8)
        _seed_occurrence(session, role_b, ids["scenes"][1], frame_index=95)
        session.commit()
        old_snapshot = _association_snapshot(session)
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, _applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
        return confirmed, role_a, role_b, old_snapshot


def test_recompute_publishes_replacement_media_links(client: TestClient) -> None:
    """D1+D3+D4: recompute publishes NEW association+artifact rows for the
    affected roles and supersedes the OLD ones (auditable); the old rows and
    the unaffected role's links stay byte-identical."""
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed, role_a, role_b, old_snapshot = _confirmed_geometry_correction_with_media(svc, ids)
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    recompute_job = confirmed.recompute_job_id

    with _session() as session:
        after = _association_snapshot(session)
        # Exactly the old 4 associations exist; each is superseded by a new
        # recompute association (role+purpose), none deleted (auditable).
        old_by_id = {ent[0]: ent for ent in old_snapshot}
        new_by_old: dict[str, str] = {}
        for ent in after:
            if ent[0] in old_by_id:
                assert ent[6] is not None  # superseded_by_id set
                new_by_old[ent[0]] = ent[6]
        assert len(new_by_old) == 4
        # Role A + Role B each get exactly 2 NEW active associations.
        new_assocs = [ent for ent in after if ent[0] not in old_by_id]
        assert len(new_assocs) == 4
        for purpose in ("thumbnail", "mask"):
            for role_id in (role_a.id, role_b.id):
                active = [
                    ent for ent in new_assocs
                    if ent[1] == role_id and ent[3] == purpose
                ]
                assert len(active) == 1, (role_id, purpose, active)
                assert active[0][5] == recompute_job
        # Unaffected columns of old rows unchanged except the supersession FK.
        for ent in new_by_old:
            old_row = old_by_id[ent]
            new_row = next(x for x in after if x[0] == ent)
            assert new_row[1:6] == old_row[1:6]
            assert new_row[6] == new_by_old[ent]
        # Media resolution now serves the NEW artifacts of both roles.
        for role_id in (role_a.id, role_b.id):
            media = _resolve_media(session, role_id)
            assert {m.purpose for m in media} == {"thumbnail", "mask"}
            for m in media:
                assert m.source_job_id == recompute_job
                assert m.artifact_id.startswith("recompute-artifact-") or m.artifact_id != ""
        # Old artifact rows are untouched (auditable historical evidence).
        for purpose in ("thumbnail", "mask"):
            old_art = session.get(
                Artifact, f"old-artifact-{role_a.id}-{purpose}"
            )
            assert old_art is not None and old_art.state == "ready"


def test_rename_only_correction_keeps_media(client: TestClient) -> None:
    """D5: a rename (candidate_edit role, no geometry change) regenerates
    suggestions only — it must NOT lose or replace the role's media."""
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids, name="Rename", candidate=True)
        _seed_media(session, role, source_job_id=role.source_job_id)
        _seed_occurrence(session, role, ids["scenes"][0], frame_index=5)
        _seed_suggestion(session, ids, role_ids=[role.id])
        session.commit()
        request = {
            "kind": "candidate_edit",
            "target": "role",
            "role_id": role.id,
            "role_revision": role.revision,
            "name": "Renamed",
            "generation": role.source_generation,
        }
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, _applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        media = _resolve_media(session, role.id)
        assert len(media) == 2
        for m in media:
            assert m.source_job_id == role.source_job_id  # unchanged media link
        by_purpose = {
            row[3]: row for row in _association_snapshot(session)
        }
        assert set(by_purpose) == {"thumbnail", "mask"}
        for purpose, row in by_purpose.items():
            assert row == (
                f"old-assoc-{role.id}-{purpose}",
                role.id,
                f"old-artifact-{role.id}-{purpose}",
                purpose,
                GENERATION,
                role.source_job_id,
                None,
            )


def test_queued_cancel_drains_with_zero_effects_and_successor_retry(
    client: TestClient,
) -> None:
    """D7: cancel while the recompute Job is still QUEUED (never leased)
    drains to a terminal cancelled state with zero media/row effects; the
    applied correction is unchanged; retry creates a successor that
    completes and then replaces the media."""
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
    confirmed, role_a, _role_b, old_snapshot = _confirmed_geometry_correction_with_media(svc, ids)
    # The job was just created (queued) and has NOT been leased/run.
    assert _job_state(svc, confirmed.recompute_job_id) in ("queued", "pending")
    assert svc.cancel_job(confirmed.recompute_job_id) is True
    assert _job_state(svc, confirmed.recompute_job_id) in ("queued", "pending", "cancelling")
    _run_worker(svc, max_claims=10)
    assert _job_state(svc, confirmed.recompute_job_id) == "cancelled"
    with _session() as session:
        # Zero effects: no new associations/artifacts; old media still ACTIVE.
        assert _association_snapshot(session) == old_snapshot
        assert session.scalar(
            select(func.count()).select_from(ObjectGroupingSuggestion)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.relative_path.like(f"%/{confirmed.recompute_job_id}/%"))
        ) == 0
        media = _resolve_media(session, role_a.id)
        assert {m.purpose for m in media} == {"thumbnail", "mask"}
        for m in media:
            assert m.source_job_id == role_a.source_job_id
        # Successor retry (idempotent, predecessor immutable).
        successor_id = _repo(session).create_recompute_successor(
            DEFAULT_WORKSPACE_ID, confirmed.id
        )
        session.commit()
    assert successor_id not in ("", confirmed.recompute_job_id)
    _run_worker(svc, max_claims=10)
    assert _job_state(svc, confirmed.recompute_job_id) == "cancelled"
    assert _job_state(svc, successor_id) == "completed"
    with _session() as session:
        media = _resolve_media(session, role_a.id)
        for m in media:
            assert m.source_job_id == successor_id  # canonical now the successor


def test_unaffected_role_media_bytes_identical_after_recompute(client: TestClient) -> None:
    """D3: the associations + artifact rows of a role NOT touched by the
    correction stay byte/hash identical (incl. still ACTIVE)."""
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, name="A", candidate=True)
        role_b = _seed_role(session, ids, name="B", candidate=True)
        role_c = _seed_role(session, ids, name="C", candidate=True)
        _seed_media(session, role_a, source_job_id=role_a.source_job_id)
        _seed_media(session, role_c, source_job_id=role_c.source_job_id)
        occ_a = _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=5)
        _seed_occurrence(session, role_a, ids["scenes"][0], frame_index=8)
        _seed_occurrence(session, role_b, ids["scenes"][1], frame_index=95)
        session.commit()
        request = _reassign_request(occ_a, role_a, role_b)
        record, _created = _create_pending(session, ids, request)
        session.commit()
        confirmed, _applied = _repo(session).confirm_correction(
            DEFAULT_WORKSPACE_ID, record.id, record.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
        c_old = _association_snapshot(session)
    _run_worker(svc)
    assert _job_state(svc, confirmed.recompute_job_id) == "completed"
    with _session() as session:
        after = _association_snapshot(session)
        c_rows = [e for e in after if e[1] == role_c.id]
        assert c_rows == [e for e in c_old if e[1] == role_c.id]
        for e in c_rows:
            assert e[6] is None  # still ACTIVE, untouched
        # Role B got NEW media (the moved evidence changed its geometry);
        # Role C's media resolution is byte-identical.
        c_media_before = _resolve_media(session, role_c.id)
        assert all(m.source_job_id == role_c.source_job_id for m in c_media_before)

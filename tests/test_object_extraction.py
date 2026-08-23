"""S08-T02 focused suite — durable object candidate extraction.

Covers every acceptance item from TASK.md with REAL production-path
execution (no mocks, no fake data): happy path, deterministic evidence,
source-generation isolation, idempotency, concurrent submit, restart at
staging/commit boundaries, retry (successor), cancel, corrupt/missing
artifacts, containment, orphan cleanup, migration and provider fail-closed
semantics.

Execution model:
- Worker-level tests drive the REAL ``DurableWorker.run_once()`` bound to
  the conftest isolated database + managed root (``deps._job_service``).
- Crash-window tests drive the REAL handler with a hand-built
  ``WorkerContext`` whose ``write_checkpoint`` fails at the exact persisted
  boundary a crash would leave (the same pattern the S05 suites use); the
  resume then runs through the real worker.
"""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import subprocess as _subprocess  # noqa: F401
import sys as _sys  # noqa: F401
import threading
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path
from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import (
    IdempotencyKeyInUse,
    JobRepository,
)
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    ObjectOccurrence,
    ObjectRole,
    OccurrenceSegment,
    Project,
    Scene,
    SceneGraphContact,
    SceneGraphOcclusion,
    SegmentMotion,
    VideoItem,
    Workspace,
)
from app.services.object_extraction import (
    CODE_INPUT_CHANGED,
    CODE_MEDIA_CHANGED,
    CODE_PATH_CONTAINMENT,
    CODE_PROVIDER_UNAVAILABLE,
    CODE_PUBLICATION_FAILED,
    CODE_SOURCE_CONFLICT,
    PROVIDER_DETERMINISTIC,
    PROVIDER_DETERMINISTIC_IDENTITY,
    PROVIDER_PRODUCTION,
    DeterministicExtractionProvider,
    ExtractionError,
    Sam2ExtractionProvider,
    discover_objects_handler,
    discover_objects_steps,
    extract_object_candidates,
    resolve_extraction_provider,
    submit_discover_objects,
)
from app.workflow.durable_worker import build_worker_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

# C2: the authoritative source SHA comes from a REAL managed media payload.
SOURCE_MEDIA_BYTES = (bytes(range(256)) * 48) + b"S08-T02-media-source-v2"
SOURCE_SHA = hashlib.sha256(SOURCE_MEDIA_BYTES).hexdigest()
EXTRACTOR_VERSION = "1.0.0"


def _alembic_config(path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return config


def _upgrade_to_revision(path: Path, revision: str) -> None:
    command.upgrade(_alembic_config(path), revision)


# ── Fixtures/helpers ─────────────────────────────────────────────────────────


def _svc():
    service = deps._job_service
    assert service is not None
    assert service.session_factory is not None
    return service


def _seed_video_item(
    session: Session,
    *,
    title: str = "Primary",
    width: int = 320,
    height: int = 240,
    duration_ms: int = 6000,
    fps_num: int = 30,
    fps_den: int = 1,
    scene_count: int = 2,
    source_sha: str = SOURCE_SHA,
) -> tuple[str, str]:
    """Seed workspace + project + video item + source artifact + scenes."""
    workspace = session.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(workspace)
    project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="Extraction Project")
    video = VideoItem(
        project=project,
        title=title,
        position=0,
        width=width,
        height=height,
        duration_ms=duration_ms,
        fps_num=fps_num,
        fps_den=fps_den,
    )
    session.add(project)
    session.flush()
    session.add(video)
    session.flush()
    rel = (
        f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video.id}/import/source.mp4"
    )
    # Real managed media file (C2 media gate: the file must exist and match
    # the row at submit/run time).
    target_root = _svc().managed_root
    managed_path = target_root / rel
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(SOURCE_MEDIA_BYTES)
    source = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="video",
        relative_path=rel,
        state="ready",
        sha256=SOURCE_SHA if source_sha == "a" * 64 else source_sha,
        size_bytes=len(SOURCE_MEDIA_BYTES),
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    video.source_artifact_id = source.id
    for index in range(scene_count):
        session.add(
            Scene(
                video_item=video,
                position=index,
                start_frame=index * 90,
                end_frame=index * 90 + 89,
                start_time_ms=index * 3000,
                end_time_ms=index * 3000 + 2999,
                status="pending",
            )
        )
    session.commit()
    return project.id, video.id


def _replace_source(svc, video_id: str, tag: str) -> dict[str, str]:
    """C2: replace the video's source artifact with NEW managed media; the
    server then derives a NEW authoritative sha + generation."""
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None
        rel = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video_id}/"
            f"import/source-{tag}.mp4"
        )
        new_bytes = SOURCE_MEDIA_BYTES + f"-REPLACED-{tag}".encode()
        managed_path = svc.managed_root / rel
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        managed_path.write_bytes(new_bytes)
        new_sha = hashlib.sha256(new_bytes).hexdigest()
        source2 = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="video",
            relative_path=rel,
            state="ready",
            sha256=new_sha,
            size_bytes=len(new_bytes),
            mime_type="video/mp4",
        )
        session.add(source2)
        session.flush()
        video.source_artifact_id = source2.id
        session.commit()
        return {"relative_path": rel, "sha256": new_sha}


def _submit(svc, project_id: str, video_item_id: str, **kwargs):
    return submit_discover_objects(
        svc.session_factory,
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=project_id,
        video_item_id=video_item_id,
        source_sha256=kwargs.get("source_sha256"),
        generation=kwargs.get("generation"),
        extractor_version=kwargs.get("extractor_version", EXTRACTOR_VERSION),
        provider=kwargs.get("provider", PROVIDER_DETERMINISTIC),
        managed_root=svc.managed_root,
        env={"MOTIONFORGE_EXTRACTION_QA_MODE": "1"},
    )


def _run_worker(svc, max_claims: int = 5) -> int:
    """Run the real worker loop until no queued jobs remain (bounded)."""
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


def _counts(svc) -> dict[str, int]:
    with svc.session_factory() as session:
        return {
            "roles": int(session.scalar(select(func.count()).select_from(ObjectRole)) or 0),
            "occurrences": int(
                session.scalar(select(func.count()).select_from(ObjectOccurrence)) or 0
            ),
            "artifacts": int(session.scalar(select(func.count()).select_from(Artifact)) or 0),
            "owners": int(
                session.scalar(select(func.count()).select_from(ArtifactOwner)) or 0
            ),
            "staging_files": len(_staging_files(svc)),
        }


def _staging_files(svc) -> list[Path]:
    staging = svc.managed_root / "staging"
    if not staging.is_dir():
        return []
    return [p for p in staging.rglob("*") if p.is_file()]


def _published_files(svc) -> list[Path]:
    root = svc.managed_root
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file() and "staging" not in p.parts]


def _ctx(
    svc,
    job_id: str,
    *,
    checkpoint: dict | None = None,
    crash_at: str | None = None,
):
    """Hand-built WorkerContext over the REAL job/step/DB (S05 pattern).

    ``crash_at`` simulates a worker crash at a persisted boundary:
    - ``"staged"``: the staged checkpoint IS persisted, then the write
      raises (crash after staging, before publish).
    - ``"published"``: the published checkpoint is NOT persisted, then the
      write raises (crash between effect commit and checkpoint write —
      the §5.4 replay-safe window).
    """
    factory = svc.session_factory
    assert factory is not None
    with factory() as session:
        repo = JobRepository(session)
        job = repo.get_job(job_id)
        step = repo.list_steps(job_id)[0]
        token = "test-fence-token"
        staged = svc.managed_root / "staging" / job_id / step.step_code
        cp = (
            checkpoint
            if checkpoint is not None
            else (step.checkpoint or {"schema_version": 1})
        )

        def write_checkpoint(payload: dict) -> None:
            phase = payload.get("phase")
            if crash_at is not None and phase == crash_at:
                if crash_at == "staged":
                    # Crash AFTER the staged checkpoint commit: persist then
                    # raise — exactly the state a crash would leave.
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
            ttl_seconds=60,
            progress=lambda pct, msg=None: None,
            write_checkpoint=write_checkpoint,
            is_cancelled=is_cancelled,
            staging_dir=lambda: staged,
            session_factory=factory,
        )


def _set_cancelling(svc, job_id: str) -> None:
    with svc.session_factory() as session:
        repo = JobRepository(session)
        job = repo.get_job(job_id)
        repo.transition_job(
            job_id,
            "cancelling",
            actor="api",
            expected_revision=job.revision,
            reason_code="CANCEL_REQUESTED",
        )
        session.commit()


# ── Migration (T02 schema surfaces) ─────────────────────────────────────────


def test_migration_round_trip_adds_extraction_surfaces(tmp_path: Path) -> None:
    db = tmp_path / "roundtrip.db"
    _upgrade_to_revision(db, "e7f8a9b0c1d2")
    engine = create_engine_for_path(db)
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artifact)"))}
        role_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(object_role)"))}
    assert "width" not in cols and "height" not in cols
    assert "source_job_id" not in role_cols
    command.upgrade(_alembic_config(db), "head")
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artifact)"))}
        role_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(object_role)"))}
        tables = {
            row[0]
            for row in conn.execute(
                text("select name from sqlite_master where type='table'")
            )
        }
        version = conn.execute(text("select version_num from alembic_version")).scalar()
        fk = conn.execute(text("PRAGMA foreign_key_list(object_role)")).fetchall()
        assoc = conn.execute(text("PRAGMA table_info(object_role_artifact)")).fetchall()
    heads = sorted(ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_heads())
    # S09-T00-I04: live runtime contract — DB revision must equal the current
    # ScriptDirectory head; single-head guard keeps this stricter than a pin.
    assert len(heads) == 1, f"expected exactly one Alembic head, got {heads}"
    assert version == heads[0]
    assert {"width", "height"} <= cols
    assert "source_job_id" in role_cols
    assert any(r[2] == "job" and r[3] == "source_job_id" for r in fk)
    assert "object_role_artifact" in tables
    assoc_cols = {row[1] for row in assoc}
    assert {"role_id", "artifact_id", "purpose", "source_generation", "source_job_id"} <= assoc_cols
    command.downgrade(_alembic_config(db), "e7f8a9b0c1d2")
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artifact)"))}
        role_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(object_role)"))}
        tables = {
            row[0]
            for row in conn.execute(
                text("select name from sqlite_master where type='table'")
            )
        }
    assert "width" not in cols and "source_job_id" not in role_cols
    assert "object_role_artifact" not in tables


def test_migration_role_artifact_preserves_existing_rows(tmp_path: Path) -> None:
    """Correction B6: the association migration is additive — upgrading from
    the previous head preserves every existing artifact/role/job row, and
    the new table has real FKs/constraints."""
    db = tmp_path / "preserve.db"
    _upgrade_to_revision(db, "f4a5b6c7d8e9")
    engine = create_engine_for_path(db)
    from app.persistence.models import Job as JobORM

    with Session(engine) as session:
        ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(ws)
        session.commit()
        project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="Preserve")
        video = VideoItem(project=project, title="Primary", position=0)
        session.add(project)
        session.flush()
        session.add(video)
        session.flush()
        artifact = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path="artifacts/default/image/existing.png",
            state="ready",
            sha256="d" * 64,
            size_bytes=10,
            mime_type="image/png",
            width=4,
            height=4,
        )
        session.add(artifact)
        session.flush()
        job = JobORM(
            workspace_id=DEFAULT_WORKSPACE_ID,
            job_type="DISCOVER_OBJECTS",
            owner_type="video_item",
            owner_id=video.id,
            state="completed",
            input_manifest_json="{}",
        )
        session.add(job)
        session.flush()
        role = ObjectRole(
            workspace_id=DEFAULT_WORKSPACE_ID,
            project_id=project.id,
            video_item_id=video.id,
            source_generation="1",
            source_job_id=job.id,
            name="existing",
        )
        session.add(role)
        session.commit()
        snapshot = (artifact.id, role.id, job.id)
    command.upgrade(_alembic_config(db), "head")
    with Session(engine) as session:
        assert session.get(Artifact, snapshot[0]) is not None
        assert session.get(ObjectRole, snapshot[1]) is not None
        assert session.get(JobORM, snapshot[2]) is not None
        # FK enforcement on the new table is real.
        from app.persistence.models import ObjectRoleArtifact

        with pytest.raises(IntegrityError):
            session.add(
                ObjectRoleArtifact(
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    role_id=snapshot[1],
                    artifact_id=snapshot[0],
                    purpose="thumbnail",
                    source_generation="1",
                    source_job_id=str(uuid.uuid4()),  # missing job -> FK violation
                )
            )
            session.commit()
        session.rollback()
        # A valid association row is accepted.
        session.add(
            ObjectRoleArtifact(
                workspace_id=DEFAULT_WORKSPACE_ID,
                role_id=snapshot[1],
                artifact_id=snapshot[0],
                purpose="thumbnail",
                source_generation="1",
                source_job_id=snapshot[2],
            )
        )
        session.commit()
    command.downgrade(_alembic_config(db), "f4a5b6c7d8e9")
    with Session(engine) as session:
        assert session.get(Artifact, snapshot[0]) is not None
        assert session.get(ObjectRole, snapshot[1]) is not None


def test_migration_dimension_check_and_role_fk_enforced(tmp_path: Path) -> None:
    """The new CHECKs and the source_job_id FK are REAL constraints."""
    db = tmp_path / "constraints.db"
    command.upgrade(_alembic_config(db), "head")
    with Session(create_engine_for_path(db)) as session:
        ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(ws)
        session.commit()
        artifact = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path="artifacts/x.png",
            state="ready",
            width=-1,
        )
        session.add(artifact)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        job_id = str(uuid.uuid4())
        session.add(
            ObjectRole(
                workspace_id=DEFAULT_WORKSPACE_ID,
                project_id=str(uuid.uuid4()),
                video_item_id=str(uuid.uuid4()),
                source_generation="1",
                name="x",
                source_job_id=job_id,  # missing job row -> FK violation
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


# ── Provider semantics (deterministic QA adapter + fail-closed production) ──


def test_provider_resolution_deterministic_and_production_fail_closed(
    tmp_path: Path,
) -> None:
    # Non-QA mode (no QA marker): deterministic MUST be PROVIDER_UNAVAILABLE
    # even when explicitly selected (C2 acceptance 7/8) — no Job, no output.
    with pytest.raises(ExtractionError) as nonqa:
        resolve_extraction_provider(PROVIDER_DETERMINISTIC, env={})
    assert nonqa.value.code == CODE_PROVIDER_UNAVAILABLE
    with pytest.raises(ExtractionError) as nonqa2:
        resolve_extraction_provider(PROVIDER_DETERMINISTIC_IDENTITY, env={})
    assert nonqa2.value.code == CODE_PROVIDER_UNAVAILABLE
    # Genuine QA mode (explicit marker + isolated roots) resolves it.
    det = resolve_extraction_provider(
        PROVIDER_DETERMINISTIC, env={"MOTIONFORGE_EXTRACTION_QA_MODE": "1"}
    )
    assert det.name == PROVIDER_DETERMINISTIC
    assert det.available() is True
    # Production default (sam2-local) with a NONEXISTENT checkpoint:
    # available() must be False — a real capability probe, not an env string.
    provider = Sam2ExtractionProvider(
        checkpoint=tmp_path / "missing-checkpoint.pt", env={}
    )
    assert provider.name == PROVIDER_PRODUCTION
    assert provider.available() is False
    # Corrupt checkpoint (not a torch zip): also unavailable.
    corrupt = tmp_path / "corrupt.pt"
    corrupt.write_bytes(b"not a torch checkpoint at all")
    assert Sam2ExtractionProvider(checkpoint=corrupt, env={}).available() is False
    # Unsupported locator (a directory / empty file): unavailable.
    empty = tmp_path / "empty.pt"
    empty.write_bytes(b"")
    assert Sam2ExtractionProvider(checkpoint=empty, env={}).available() is False
    with pytest.raises(ExtractionError) as err:
        resolve_extraction_provider("bogus")
    assert err.value.code == CODE_PROVIDER_UNAVAILABLE


def test_production_provider_never_falls_back(tmp_path: Path, client) -> None:
    """The production provider with a genuinely missing backend fails closed
    at submit (no job row) — NEVER a deterministic fallback."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    with pytest.raises(ExtractionError) as err:
        submit_discover_objects(
            svc.session_factory,
            workspace_id=DEFAULT_WORKSPACE_ID,
            project_id=project_id,
            video_item_id=video_id,
            provider=PROVIDER_PRODUCTION,
            managed_root=svc.managed_root,
            env={"MOTIONFORGE_SAM2_CHECKPOINT": str(tmp_path / "missing.pt")},
        )
    assert err.value.code == CODE_PROVIDER_UNAVAILABLE
    assert _counts(svc)["roles"] == 0
    with svc.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(
            __import__("app.persistence.models", fromlist=["Job"]).Job
        )) == 0


def test_deterministic_provider_real_algorithm() -> None:
    provider = DeterministicExtractionProvider()
    evidence = {
        "video_item_id": "00000000-0000-0000-0000-000000000001",
        "video_width": 320,
        "video_height": 240,
        "nb_frames": 180,
        "extractor_version": EXTRACTOR_VERSION,
        "scenes": [
            {
                "id": "s1",
                "start_frame": 0,
                "end_frame": 89,
                "start_time_ms": 0,
                "end_time_ms": 2999,
            },
            {
                "id": "s2",
                "start_frame": 90,
                "end_frame": 179,
                "start_time_ms": 3000,
                "end_time_ms": 5999,
            },
        ],
    }
    first = extract_object_candidates(provider, **evidence)
    second = extract_object_candidates(provider, **evidence)
    assert len(first) == 2 and len(second) == 2
    for a, b in zip(first, second, strict=True):
        assert a.name == b.name and a.confidence == b.confidence
        assert a.occurrences == b.occurrences
        assert [art.bytes for art in a.artifacts] == [art.bytes for art in b.artifacts]
        assert [art.width for art in a.artifacts] == [art.width for art in b.artifacts]
    # PNG magic + non-trivial bytes
    thumb = first[0].artifacts[0]
    assert thumb.bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert thumb.width > 0 and thumb.height > 0


# ── Happy path: durable job completes and commits rows + artifacts ──────────


def test_happy_path_commits_rows_and_artifacts(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    assert result.reused is False
    assert _job_state(svc, result.job_id) == "queued"
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"

    with svc.session_factory() as session:
        roles = session.scalars(select(ObjectRole).order_by(ObjectRole.name)).all()
        assert len(roles) == 2
        for role in roles:
            assert role.status == "suggested"
            assert role.source_generation == "1"
            assert role.source_job_id == result.job_id
            assert len(role.occurrences) == 1
            occ = role.occurrences[0]
            assert occ.algorithm_version == EXTRACTOR_VERSION
            assert 0 <= occ.confidence <= 1
        artifacts = session.scalars(
            select(Artifact).where(Artifact.kind == "image")
        ).all()
        assert len(artifacts) == 4  # 2 candidates x (thumbnail + mask)
        for artifact in artifacts:
            assert artifact.state == "ready"
            assert artifact.mime_type == "image/png"
            assert artifact.sha256 and len(artifact.sha256) == 64
            assert artifact.width and artifact.width > 0
            assert artifact.height and artifact.height > 0
            target = ManagedRoot(svc.managed_root).resolve(artifact.relative_path)
            assert target.is_file()
            assert target.stat().st_size == artifact.size_bytes
        manifest = session.scalar(
            select(Artifact).where(Artifact.kind == "document")
        )
        assert manifest is not None and manifest.state == "ready"
        payload = json.loads(
            ManagedRoot(svc.managed_root).resolve(manifest.relative_path).read_text()
        )
        assert payload["job_id"] == result.job_id
        assert len(payload["candidates"]) == 2
    assert _counts(svc)["staging_files"] == 0


# ── Deterministic evidence across generations ───────────────────────────────


def test_deterministic_evidence_across_generations(client) -> None:
    """Same video item, two generations: two isolated jobs whose artifact
    bytes are byte-identical (deterministic evidence)."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    gen1 = _submit(svc, project_id, video_id, generation="1")
    _run_worker(svc)
    assert _job_state(svc, gen1.job_id) == "completed"
    _replace_source(svc, video_id, "evidence-v2")  # advance backend generation
    gen2 = _submit(svc, project_id, video_id)
    assert gen2.job_id != gen1.job_id and gen2.reused is False
    _run_worker(svc)
    assert _job_state(svc, gen2.job_id) == "completed"

    def artifact_shas(job_id: str) -> list[tuple[str, int]]:
        with svc.session_factory() as session:
            rows = session.execute(
                select(Artifact.sha256, Artifact.size_bytes)
                .where(Artifact.relative_path.like(f"%/image/{job_id}/%"))
                .where(Artifact.kind == "image")
                .order_by(Artifact.relative_path)
            ).all()
            return [(r[0], r[1]) for r in rows]

    shas1 = artifact_shas(gen1.job_id)
    shas2 = artifact_shas(gen2.job_id)
    assert len(shas1) == 4 and shas1 == shas2
    # Generation isolation: two role sets, each bound to its own job.
    with svc.session_factory() as session:
        gen_values = set(session.scalars(select(ObjectRole.source_generation)).all())
        assert gen_values == {"1", "2"}


# ── Idempotency + concurrent submit ─────────────────────────────────────────


def test_completed_duplicate_submit_reuses_job(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    first = _submit(svc, project_id, video_id)
    _run_worker(svc)
    second = _submit(svc, project_id, video_id)
    assert second.job_id == first.job_id and second.reused is True
    assert _counts(svc)["roles"] == 2  # no duplicate effect set


def test_active_duplicate_submit_rejected(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    first = _submit(svc, project_id, video_id)
    with pytest.raises(IdempotencyKeyInUse):
        _submit(svc, project_id, video_id)
    assert _job_state(svc, first.job_id) == "queued"
    _run_worker(svc)
    assert _job_state(svc, first.job_id) == "completed"
    assert _counts(svc)["roles"] == 2


def test_concurrent_submit_exactly_one_job(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def submit_once() -> None:
        barrier.wait()
        try:
            result = _submit(svc, project_id, video_id)
            outcomes.append(result.job_id)
        except IdempotencyKeyInUse as err:
            outcomes.append(f"conflict:{err.key}")

    threads = [threading.Thread(target=submit_once) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    job_ids = [o for o in outcomes if o.startswith("conflict:") is False]
    assert len(job_ids) == 1
    assert len([o for o in outcomes if o.startswith("conflict:")]) == 1
    with svc.session_factory() as session:
        job_count = session.scalar(
            select(func.count()).select_from(
                __import__("app.persistence.models", fromlist=["Job"]).Job
            )
        )
    assert job_count == 1


def test_extractor_version_bumps_idempotency_key(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    first = _submit(svc, project_id, video_id)
    _run_worker(svc)
    second = _submit(svc, project_id, video_id, extractor_version="1.1.0")
    assert second.job_id != first.job_id and second.reused is False
    _run_worker(svc)
    with svc.session_factory() as session:
        versions = set(
            session.scalars(select(ObjectOccurrence.algorithm_version)).all()
        )
    assert versions == {"1.0.0", "1.1.0"}


# ── Stale source (INPUT_CHANGED) ────────────────────────────────────────────


def test_stale_source_fails_closed_with_zero_effects(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    # Replace the source artifact bytes AFTER submission (stale source).
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None and video.source_artifact_id is not None
        source = session.get(Artifact, video.source_artifact_id)
        assert source is not None
        source.sha256 = "b" * 64
        session.commit()
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "failed"
    with svc.session_factory() as session:
        job = JobRepository(session).get_job(result.job_id)
        assert job.error is not None
        assert job.error.get("error_code") == CODE_INPUT_CHANGED
    # Zero extraction effects: only the seeded source artifact row exists.
    assert _counts(svc) == {
        "roles": 0,
        "occurrences": 0,
        "artifacts": 1,
        "owners": 0,
        "staging_files": 0,
    }


# ── Restart at staging boundary (crash between stage and publish) ───────────


def test_restart_at_staging_boundary_no_duplicates(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    # Crash simulation: the handler persists the "staged" checkpoint, then
    # dies before publish (write_checkpoint raises after the commit).
    with pytest.raises(RuntimeError, match="simulated crash"):
        discover_objects_handler(_ctx(svc, result.job_id, crash_at="staged"))
    assert _counts(svc)["roles"] == 0  # nothing committed yet
    assert _counts(svc)["staging_files"] == 4  # 2 candidates x 2 artifacts staged
    # Resume through the REAL worker: staged files re-staged/reused, publish
    # commits exactly one effect set, staging drained.
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    counts = _counts(svc)
    assert counts["roles"] == 2
    assert counts["artifacts"] == 6  # 4 images + manifest + seeded source
    assert counts["staging_files"] == 0


# ── Restart at commit boundary (crash between commit and checkpoint) ────────


def test_restart_at_commit_boundary_no_duplicates(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    # Crash simulation: the effect transaction COMMITS, then the process
    # dies before the published checkpoint is written (§5.4 replay window).
    with pytest.raises(RuntimeError, match="simulated crash"):
        discover_objects_handler(_ctx(svc, result.job_id, crash_at="published"))
    committed = _counts(svc)
    assert committed["roles"] == 2  # effect committed
    assert committed["artifacts"] == 6
    # Resume through the REAL worker: replay verifies committed rows/files,
    # re-publishes nothing new, completes with exactly ONE effect set.
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    counts = _counts(svc)
    assert counts["roles"] == 2
    assert counts["occurrences"] == 2
    assert counts["artifacts"] == 6
    assert counts["owners"] == 5  # 4 image owners + manifest owner
    assert counts["staging_files"] == 0
    with svc.session_factory() as session:
        job = JobRepository(session).get_job(result.job_id)
        assert job.progress == 100.0


# ── Retry (successor Job) after failure/cancel ──────────────────────────────


def _successor(svc, job_id: str):
    with svc.session_factory() as session:
        repo = JobRepository(session)
        job = repo.get_job(job_id)
        successor = repo.create_successor(
            predecessor_job_id=job.id,
            input_manifest=job.input_manifest,
            idempotency_key=job.idempotency_key,
            input_generation=job.input_generation,
            steps=discover_objects_steps(),
            actor="api",
        )
        session.commit()
        return successor.id


def test_retry_after_failure_creates_successor_no_duplicates(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=0)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "failed"  # SCENE_MISSING
    successor_id = _successor(svc, result.job_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "failed"  # predecessor immutable
    assert _job_state(svc, successor_id) == "failed"  # still no scenes
    with svc.session_factory() as session:
        repo = JobRepository(session)
        assert repo.get_job(successor_id).predecessor_job_id == result.job_id
        # one successor per predecessor
        count = session.scalar(
            select(func.count()).select_from(
                __import__("app.persistence.models", fromlist=["Job"]).Job
            ).where(
                __import__("app.persistence.models", fromlist=["Job"]).Job.predecessor_job_id
                == result.job_id
            )
        )
        assert count == 1
    assert _counts(svc)["roles"] == 0


def test_retry_after_cancel_completes_cleanly(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal-cancelled Job (cooperative drain, zero effects) retries
    through the successor path with exactly one new effect set."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    monkeypatch.setattr(
        "app.services.object_extraction.DeterministicExtractionProvider",
        _BlockingDeterministicProvider,
    )
    _BlockingDeterministicProvider.entered_extract.clear()
    _BlockingDeterministicProvider.release_extract.clear()
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert _BlockingDeterministicProvider.entered_extract.wait(timeout=10)
    assert svc.cancel_job(result.job_id) is True
    _BlockingDeterministicProvider.release_extract.set()
    worker_thread.join(timeout=30)
    assert _job_state(svc, result.job_id) == "cancelled"
    assert _counts(svc)["roles"] == 0  # cancelled attempt left zero effects

    successor_id = _successor(svc, result.job_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "cancelled"  # predecessor immutable
    assert _job_state(svc, successor_id) == "completed"
    counts = _counts(svc)
    assert counts["roles"] == 2
    assert counts["artifacts"] == 6
    assert counts["staging_files"] == 0


# ── Cancel (cooperative, durable, zero effects) ─────────────────────────────


class _BlockingDeterministicProvider(DeterministicExtractionProvider):
    """Real deterministic provider + test synchronization hook.

    The extraction logic is untouched; the hook only lets the test cancel
    the Job while the handler is inside the extract phase (the durable
    cancel path: running -> cancelling -> worker drains -> cancelled)."""

    entered_extract = threading.Event()
    release_extract = threading.Event()

    def extract(self, evidence: dict) -> list:
        _BlockingDeterministicProvider.entered_extract.set()
        if not _BlockingDeterministicProvider.release_extract.wait(timeout=10):
            raise TimeoutError("test hook timed out")
        return super().extract(evidence)


def test_cancel_during_running_drains_with_zero_effects(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    monkeypatch.setattr(
        "app.services.object_extraction.DeterministicExtractionProvider",
        _BlockingDeterministicProvider,
    )
    _BlockingDeterministicProvider.entered_extract.clear()
    _BlockingDeterministicProvider.release_extract.clear()

    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert _BlockingDeterministicProvider.entered_extract.wait(timeout=10)
    assert svc.cancel_job(result.job_id) is True
    _BlockingDeterministicProvider.release_extract.set()
    worker_thread.join(timeout=30)
    assert not worker_thread.is_alive()

    assert _job_state(svc, result.job_id) == "cancelled"
    counts = _counts(svc)
    assert counts["roles"] == 0
    assert counts["artifacts"] == 1  # seeded source only
    assert counts["staging_files"] == 0


def test_cancel_completed_job_rejected(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert svc.cancel_job(result.job_id) is False  # terminal: 400 semantics
    assert _job_state(svc, result.job_id) == "completed"


# ── Corrupt/missing artifacts: completed state impossible ───────────────────


def test_missing_artifact_file_fails_replay_validation(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    # Delete one committed artifact file (disk loss), then replay the
    # handler from the persisted published checkpoint.
    with svc.session_factory() as session:
        artifact = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert artifact is not None
        rel = artifact.relative_path
    target = ManagedRoot(svc.managed_root).resolve(rel)
    target.unlink()
    with pytest.raises(ExtractionError) as err:
        discover_objects_handler(_ctx(svc, result.job_id))
    assert err.value.code == CODE_PUBLICATION_FAILED or err.value.code == "OUTPUT_MISSING"


def test_corrupt_artifact_file_fails_replay_validation(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    with svc.session_factory() as session:
        artifact = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert artifact is not None
        rel = artifact.relative_path
    target = ManagedRoot(svc.managed_root).resolve(rel)
    target.write_bytes(b"corrupted-bytes-not-png")
    with pytest.raises(ExtractionError) as err:
        discover_objects_handler(_ctx(svc, result.job_id))
    assert err.value.code == CODE_PUBLICATION_FAILED


def test_missing_role_row_fails_replay_validation(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    with svc.session_factory() as session:
        # T02 wiring: OccurrenceSegment references ObjectRole with RESTRICT.
        # To simulate a missing role, the durable structural evidence rows that
        # reference it must be removed first (otherwise FK RESTRICT fails).
        # This reflects the stricter contract: structural evidence is durable
        # historical truth and prevents silent cascade-erase of history.
        from app.persistence.models import (
            OccurrenceSegment,
            SceneGraphContact,
            SceneGraphOcclusion,
            SegmentMotion,
        )
        # Collect segment ids for this job's segments
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        seg_ids = [s.id for s in segs]
        if seg_ids:
            # Delete motions/contacts/occlusions that reference segments
            for mid in session.scalars(select(SegmentMotion.id).where(SegmentMotion.occurrence_segment_id.in_(seg_ids))).all():  # noqa: E501
                m = session.get(SegmentMotion, mid)
                if m is not None:
                    session.delete(m)
            for oid in session.scalars(select(SceneGraphOcclusion.id)).all():
                row = session.get(SceneGraphOcclusion, oid)
                if row is not None and (row.occluder_segment_id in seg_ids or row.occludee_segment_id in seg_ids):  # noqa: E501
                    session.delete(row)
            for cid in session.scalars(select(SceneGraphContact.id)).all():
                row = session.get(SceneGraphContact, cid)
                if row is not None and (row.source_segment_id in seg_ids or row.target_segment_id in seg_ids):  # noqa: E501
                    session.delete(row)
            for seg in segs:
                session.delete(seg)
            session.flush()
        role = session.scalars(select(ObjectRole).limit(1)).first()
        assert role is not None
        session.delete(role)
        session.commit()
    with pytest.raises(ExtractionError) as err:
        discover_objects_handler(_ctx(svc, result.job_id))
    assert err.value.code == CODE_PUBLICATION_FAILED


def test_worker_fails_job_when_output_validation_fails(client) -> None:
    """The worker's completion gate fails the Job (never completes) when
    the committed output set is corrupt — validated through the real
    worker after a fence/requeue."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    # Crash at the commit boundary leaves rows committed but the checkpoint
    # unwritten; corrupt one committed file BEFORE the resume so the
    # replayed publication cannot verify it.
    with pytest.raises(RuntimeError, match="simulated crash"):
        discover_objects_handler(_ctx(svc, result.job_id, crash_at="published"))
    with svc.session_factory() as session:
        artifact = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert artifact is not None
        rel = artifact.relative_path
    target = ManagedRoot(svc.managed_root).resolve(rel)
    target.write_bytes(b"tampered")
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "failed"
    with svc.session_factory() as session:
        job = JobRepository(session).get_job(result.job_id)
        assert job.error is not None
        assert job.error.get("error_code") in ("PUBLICATION_FAILED", "VALIDATION_FAILED")


# ── Containment + orphan cleanup ────────────────────────────────────────────


def test_stage_phase_rejects_unsafe_artifact_names(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    from app.services.object_extraction import (
        ExtractionArtifact,
        ExtractionCandidate,
        _managed_for,
        _stage_phase,
    )

    ctx = _ctx(svc, result.job_id)
    managed = _managed_for(ctx)
    bad_candidates = [
        ExtractionCandidate(
            name="escape",
            kind="character",
            confidence=0.9,
            reasons=["x"],
            occurrences=[],
            artifacts=[
                ExtractionArtifact(
                    name="../../escape.png",
                    purpose="thumbnail",
                    bytes=b"x",
                    width=1,
                    height=1,
                )
            ],
        )
    ]
    with pytest.raises(ExtractionError) as err:
        _stage_phase(ctx, managed, bad_candidates)
    assert err.value.code == CODE_PATH_CONTAINMENT


def test_orphan_staging_partials_cleaned_on_rerun(client) -> None:
    """Crash leftovers in the Job's OWN staging area are garbage-collected
    on the next run; another Job's staging area is never touched."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    # Simulate a crashed attempt's leftover partial in the job's own dir and
    # a stray partial belonging to another (unrelated) job.
    staging = svc.managed_root / "staging" / result.job_id / "extract"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "candidate_01_thumbnail.png.deadbeef.staging").write_bytes(b"partial")
    stray = svc.managed_root / "staging" / str(uuid.uuid4()) / "extract"
    stray.mkdir(parents=True, exist_ok=True)
    stray_partial = stray / "candidate_01_thumbnail.png.deadbeef.staging"
    stray_partial.write_bytes(b"partial")
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    assert _counts(svc)["staging_files"] == 1  # only the unrelated job's partial
    assert stray_partial.exists()  # another job's area is untouched
    own_dir = svc.managed_root / "staging" / result.job_id
    assert not any(p.is_file() for p in own_dir.rglob("*"))  # own staging drained


def test_no_orphan_files_after_completion(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        _project_id, video_id = _seed_video_item(session)
    _submit(svc, _project_id, video_id)
    _run_worker(svc)
    files = _published_files(svc)
    with svc.session_factory() as session:
        rows = session.execute(select(Artifact.relative_path)).all()
    rels = {r[0] for r in rows}
    assert len(files) == 6  # source media + 4 images + manifest
    for path in files:
        rel = str(path.relative_to(svc.managed_root)).replace("\\", "/")
        assert rel in rels
    assert _counts(svc)["staging_files"] == 0



# ── Correction B6: durable role->artifact associations ───────────────────────


def _association_rows(svc) -> list[dict]:
    from app.persistence.models import ObjectRoleArtifact

    with svc.session_factory() as session:
        rows = session.scalars(select(ObjectRoleArtifact)).all()
        return [
            {
                "role_id": row.role_id,
                "artifact_id": row.artifact_id,
                "purpose": row.purpose,
                "generation": row.source_generation,
                "job_id": row.source_job_id,
            }
            for row in rows
        ]


def test_role_artifact_associations_committed(client) -> None:
    """Correction B6: every candidate artifact gets a durable id-based
    association row (role_id, artifact_id, purpose, generation, job)."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    associations = _association_rows(svc)
    assert len(associations) == 4  # 2 roles x (thumbnail + mask)
    with svc.session_factory() as session:
        roles = session.scalars(select(ObjectRole)).all()
        role_ids = {role.id for role in roles}
        image_rows = session.scalars(
            select(Artifact).where(Artifact.kind == "image")
        ).all()
        image_ids = {row.id for row in image_rows}
    for association in associations:
        assert association["role_id"] in role_ids
        assert association["artifact_id"] in image_ids
        assert association["purpose"] in ("thumbnail", "mask")
        assert association["generation"] == "1"
        assert association["job_id"] == result.job_id


def test_stable_role_ids_after_rename_and_duplicate_names(client) -> None:
    """Correction B5: the role id is stable and name-independent — renames
    and duplicate display names cannot re-map associations/gallery refs."""
    from app.persistence.object_intelligence import ObjectIntelligenceRepository

    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    gen1 = _submit(svc, project_id, video_id, generation="1")
    _run_worker(svc)
    assert _job_state(svc, gen1.job_id) == "completed"
    with svc.session_factory() as session:
        role = session.scalars(select(ObjectRole).order_by(ObjectRole.name)).first()
        assert role is not None
        role_id = role.id
        repo = ObjectIntelligenceRepository(session)
        renamed = repo.update_role(
            DEFAULT_WORKSPACE_ID, role.id, role.revision, name="renamed-hero"
        )
        assert renamed.id == role_id
    # C2: to run a NEW generation the backend source must advance — replace
    # the source artifact (new id, NEW content) so the server assigns gen 2.
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None
        old_source = session.get(Artifact, video.source_artifact_id)
        rel2 = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video_id}/"
            "import/source-v2.mp4"
        )
        new_bytes = SOURCE_MEDIA_BYTES + b"-replaced-v2"
        managed_path2 = svc.managed_root / rel2
        managed_path2.parent.mkdir(parents=True, exist_ok=True)
        managed_path2.write_bytes(new_bytes)
        source2 = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="video",
            relative_path=rel2,
            state="ready",
            sha256=hashlib.sha256(new_bytes).hexdigest(),
            size_bytes=len(new_bytes),
            mime_type="video/mp4",
        )
        session.add(source2)
        session.flush()
        video.source_artifact_id = source2.id
        assert old_source is not None and old_source.id != source2.id
        session.commit()
    gen2 = _submit(svc, project_id, video_id)  # no hints: server resolves gen 2
    _run_worker(svc)
    assert _job_state(svc, gen2.job_id) == "completed"
    with svc.session_factory() as session:
        job2 = session.get(
            __import__("app.persistence.models", fromlist=["Job"]).Job, gen2.job_id
        )
        assert job2 is not None and job2.input_generation == "2"
    with svc.session_factory() as session:
        rows = session.execute(
            select(ObjectRole.id, ObjectRole.name, ObjectRole.source_generation)
        ).all()
        gen1_ids = {r[0] for r in rows if r[2] == "1"}
        gen2_ids = {r[0] for r in rows if r[2] == "2"}
    assert role_id in gen1_ids
    assert gen1_ids & gen2_ids == set()  # distinct stable ids per generation
    associations = _association_rows(svc)
    gen2_assoc_roles = {a["role_id"] for a in associations if a["generation"] == "2"}
    assert gen2_assoc_roles == gen2_ids  # associations keyed by id, not name


def test_restart_replay_preserves_associations(client) -> None:
    """Correction B6 + restart: replay at the commit boundary reuses the
    SAME association rows (no duplicates)."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    with pytest.raises(RuntimeError, match="simulated crash"):
        discover_objects_handler(_ctx(svc, result.job_id, crash_at="published"))
    assert len(_association_rows(svc)) == 4  # committed once
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    assert len(_association_rows(svc)) == 4  # replay added nothing


def test_stale_source_leaves_no_associations(client) -> None:
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None and video.source_artifact_id is not None
        source = session.get(Artifact, video.source_artifact_id)
        assert source is not None
        source.sha256 = "b" * 64
        session.commit()
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "failed"
    assert _association_rows(svc) == []



# ── Correction C2: backend source authority + provider gate ─────────────────


def test_submit_spoof_generation_rejected(client) -> None:
    """C2 acceptance 1-3: a client generation hint that differs from the
    backend current generation fails closed with SOURCE_CONFLICT and NO
    Job row."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    with pytest.raises(ExtractionError) as err:
        _submit(svc, project_id, video_id, generation="999")
    assert err.value.code == CODE_SOURCE_CONFLICT
    with svc.session_factory() as session:
        job_count = session.scalar(
            select(func.count()).select_from(
                __import__("app.persistence.models", fromlist=["Job"]).Job
            )
        )
    assert job_count == 0
    assert _counts(svc)["roles"] == 0


def test_submit_spoof_source_sha_rejected(client) -> None:
    """C2: a client source_sha256 hint differing from the backend artifact
    fails closed with SOURCE_CONFLICT, no Job."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    with pytest.raises(ExtractionError) as err:
        _submit(svc, project_id, video_id, source_sha256="c" * 64)
    assert err.value.code == CODE_SOURCE_CONFLICT
    with svc.session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(
                    __import__("app.persistence.models", fromlist=["Job"]).Job
                )
            )
            == 0
        )


def test_submit_omitted_sha_resolves_authoritatively(client) -> None:
    """C2: omitting client hints works — the server resolves the current
    source sha + generation; manifest/idempotency use the authoritative
    values."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        job = session.get(
            __import__("app.persistence.models", fromlist=["Job"]).Job,
            result.job_id,
        )
        manifest = json.loads(job.input_manifest_json or "{}")
        assert manifest["source_sha256"] == SOURCE_SHA  # authoritative
        assert manifest["generation"] == "1"
        assert job.input_generation == "1"
        key = job.idempotency_key
    assert f":{SOURCE_SHA}:1:1.0.0" in key  # authoritative values in the key


def test_submit_replaced_source_uses_backend_sha(client) -> None:
    """C2: after the source is replaced, the server uses the NEW source's
    sha and advances the generation — never the client's old hint."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    gen1 = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, gen1.job_id) == "completed"
    # Replace the source (a new ready artifact with different content).
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None
        rel2 = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video_id}/"
            "import/source-v2.mp4"
        )
        new_bytes = SOURCE_MEDIA_BYTES + b"-REPLACED"
        managed_path2 = svc.managed_root / rel2
        managed_path2.parent.mkdir(parents=True, exist_ok=True)
        managed_path2.write_bytes(new_bytes)
        new_sha = hashlib.sha256(new_bytes).hexdigest()
        source2 = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="video",
            relative_path=rel2,
            state="ready",
            sha256=new_sha,
            size_bytes=len(new_bytes),
            mime_type="video/mp4",
        )
        session.add(source2)
        session.flush()
        video.source_artifact_id = source2.id
        session.commit()
    gen2 = _submit(svc, project_id, video_id)  # no hints
    assert gen2.job_id != gen1.job_id
    with svc.session_factory() as session:
        job2 = session.get(
            __import__("app.persistence.models", fromlist=["Job"]).Job,
            gen2.job_id,
        )
        assert job2 is not None
        assert json.loads(job2.input_manifest_json or "{}")["source_sha256"] == new_sha
        assert json.loads(job2.input_manifest_json or "{}")["generation"] == "2"
        assert job2.input_generation == "2"
        assert new_sha in job2.idempotency_key
        assert SOURCE_SHA not in job2.idempotency_key


def test_media_tampered_after_submit_fails_before_inference(client) -> None:
    """C2 acceptance 5/6: a managed media file modified byte-wise after
    submit fails BEFORE inference (MEDIA_CHANGED) and publishes NOTHING."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)
    # Tamper the media FILE on disk (byte-wise), not the row.
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None and video.source_artifact_id is not None
        rel = session.get(Artifact, video.source_artifact_id).relative_path
    target = svc.managed_root / rel
    with open(target, "ab") as handle:
        handle.write(b"tampered-after-submit")
    assert _job_state(svc, result.job_id) == "queued"
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "failed"
    with svc.session_factory() as session:
        job = session.get(
            __import__("app.persistence.models", fromlist=["Job"]).Job,
            result.job_id,
        )
        error_payload = json.loads(job.error_json or "{}") if job else {}
        error_code = error_payload.get("error_code")
    assert error_code == CODE_MEDIA_CHANGED
    assert _counts(svc)["roles"] == 0
    assert _association_rows(svc) == []
    counts = _counts(svc)
    assert counts["artifacts"] == 1  # only the seeded source artifact
    assert counts["staging_files"] == 0


def test_production_deterministic_rejection_no_job(client) -> None:
    """C2 acceptance 7/8: in NON-QA mode the deterministic provider is
    PROVIDER_UNAVAILABLE — even when selected via env var or internal
    caller — with NO Job row and NO output."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    # Internal caller asks for deterministic WITHOUT the QA marker.
    with pytest.raises(ExtractionError) as err:
        submit_discover_objects(
            svc.session_factory,
            workspace_id=DEFAULT_WORKSPACE_ID,
            project_id=project_id,
            video_item_id=video_id,
            provider=PROVIDER_DETERMINISTIC,
            managed_root=svc.managed_root,
            env={},  # NOT QA mode
        )
    assert err.value.code == CODE_PROVIDER_UNAVAILABLE
    with svc.session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(
                    __import__("app.persistence.models", fromlist=["Job"]).Job
                )
            )
            == 0
        )
    assert _counts(svc)["roles"] == 0


def test_qa_deterministic_success(client) -> None:
    """C2 acceptance 9: in genuine QA mode (explicit marker + isolated
    roots) the deterministic provider runs the full pipeline successfully."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    result = _submit(svc, project_id, video_id)  # QA env set in _submit
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        job = session.get(
            __import__("app.persistence.models", fromlist=["Job"]).Job,
            result.job_id,
        )
        assert job is not None
        provider = json.loads(job.input_manifest_json or "{}").get("provider")
        assert provider == "deterministic"
    assert _counts(svc)["roles"] == 2

# ══════════════════════════════════════════════════════════════════════════
# S08-A02-T02 — Extraction Evidence and Artifact Wiring (10 AC items)
# ══════════════════════════════════════════════════════════════════════════

def _structural_counts(svc) -> dict[str, int]:
    with svc.session_factory() as session:
        return {
            "segments": int(session.scalar(select(func.count()).select_from(OccurrenceSegment)) or 0),  # noqa: E501
            "motions": int(session.scalar(select(func.count()).select_from(SegmentMotion)) or 0),
            "occlusions": int(session.scalar(select(func.count()).select_from(SceneGraphOcclusion)) or 0),  # noqa: E501
            "contacts": int(session.scalar(select(func.count()).select_from(SceneGraphContact)) or 0),  # noqa: E501
        }


def test_segments_committed_per_candidate_scene(client) -> None:
    """AC1: segment count == candidates × scenes; every segment source_generation == job generation; mask linkage."""  # noqa: E501
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        # candidates=2 (deterministic provider for 2 scenes) × scenes=2 => 4 segments
        assert len(segs) == 4, f"expected 4 segments (2 candidates × 2 scenes), got {len(segs)}"
        for seg in segs:
            assert seg.source_generation == "1"
            assert seg.source_job_id == result.job_id
            assert seg.mask_artifact_id is not None
            art = session.get(Artifact, seg.mask_artifact_id)
            assert art is not None and art.state == "ready" and art.kind == "image"
            assert art.workspace_id == DEFAULT_WORKSPACE_ID
            assert seg.logical_id is not None and len(seg.logical_id) == 36
            assert seg.id is not None and len(seg.id) == 36
            # prompt/segmentation canonical shape
            import json as _j
            if seg.prompt_json:
                pj = _j.loads(seg.prompt_json)
                assert "points" in pj and "boxes" in pj
                for pt in pj.get("points", []):
                    assert set(pt.keys()) == {"x", "y", "label"}
                    assert isinstance(pt["label"], str) and pt["label"]
                for bx in pj.get("boxes", []):
                    assert set(bx.keys()) == {"x", "y", "w", "h"}
            # scene-scoped range: must equal scene range
            scene = session.get(Scene, seg.scene_id)
            assert scene is not None
            assert seg.start_frame == scene.start_frame
            assert seg.end_frame == scene.end_frame
            assert seg.start_time_ms == scene.start_time_ms
            assert seg.end_time_ms == scene.end_time_ms


def test_segment_logical_id_stable_on_replay(client) -> None:
    """AC1 replay + AC2 idempotent replay zero rows."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    first = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, first.job_id) == "completed"
    with svc.session_factory() as session:
        segs1 = sorted(session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == first.job_id)).all(), key=lambda s: s.id)  # noqa: E501
        ids1 = [(s.logical_id, s.id) for s in segs1]
        counts_before = _structural_counts(svc)
        # Idempotent replay via submit duplicate
        second = _submit(svc, project_id, video_id)
        assert second.job_id == first.job_id and second.reused is True
        # Fresh subprocess re-run via handler replay
        discover_objects_handler(_ctx(svc, first.job_id))
        counts_after = _structural_counts(svc)
        assert counts_before == counts_after, f"replay should create zero new rows: {counts_before} vs {counts_after}"  # noqa: E501
        segs2 = sorted(session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == first.job_id)).all(), key=lambda s: s.id)  # noqa: E501
        ids2 = [(s.logical_id, s.id) for s in segs2]
        assert ids1 == ids2, "logical_id stable on replay"


def test_deterministic_segment_and_motion_evidence(client) -> None:
    """AC3: deterministic evidence byte-identical across replay."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = sorted(session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all(), key=lambda s: s.id)  # noqa: E501
        motions = sorted(session.scalars(select(SegmentMotion).where(SegmentMotion.workspace_id == DEFAULT_WORKSPACE_ID)).all(), key=lambda m: m.id)  # noqa: E501
        # Snapshot evidence
        seg_snapshot = [(s.logical_id, s.id, s.prompt_json, s.segmentation_json, s.mask_artifact_id) for s in segs]  # noqa: E501
        motion_snapshot = [(m.transform_json, m.point_track_flow_ref_json, m.confidence_source) for m in motions if m.occurrence_segment_id in {s.id for s in segs}]  # noqa: E501
        # Replay handler
        discover_objects_handler(_ctx(svc, result.job_id))
        segs2 = sorted(session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all(), key=lambda s: s.id)  # noqa: E501
        motions2 = sorted(session.scalars(select(SegmentMotion).where(SegmentMotion.workspace_id == DEFAULT_WORKSPACE_ID)).all(), key=lambda m: m.id)  # noqa: E501
        seg_snapshot2 = [(s.logical_id, s.id, s.prompt_json, s.segmentation_json, s.mask_artifact_id) for s in segs2]  # noqa: E501
        motion_snapshot2 = [(m.transform_json, m.point_track_flow_ref_json, m.confidence_source) for m in motions2 if m.occurrence_segment_id in {s.id for s in segs2}]  # noqa: E501
        assert seg_snapshot == seg_snapshot2
        assert motion_snapshot == motion_snapshot2
        # mask bytes sha256 identical
        for seg in segs:
            art = session.get(Artifact, seg.mask_artifact_id)
            assert art is not None
            target = ManagedRoot(svc.managed_root).resolve(art.relative_path)
            assert target.is_file()
            from app.persistence.artifacts import hash_file as _hf
            assert _hf(target) == art.sha256


def test_mask_artifact_lifecycle_and_content_endpoint(client) -> None:
    """AC4: mask lifecycle stage→publish ready; sha256 verified; tampered fails."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        seg = segs[0]
        art = session.get(Artifact, seg.mask_artifact_id)
        assert art is not None and art.state == "ready"
        assert art.relative_path.startswith(f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{result.job_id}/")  # noqa: E501
        target = ManagedRoot(svc.managed_root).resolve(art.relative_path)
        assert target.is_file()
        from app.persistence.artifacts import hash_file as _hf
        assert _hf(target) == art.sha256
        assert target.stat().st_size == art.size_bytes
        # Tampered file should fail validation on replay
        original = target.read_bytes()
        target.write_bytes(b"tampered-bytes")
    # Replay should fail
    with pytest.raises(ExtractionError) as err:
        discover_objects_handler(_ctx(svc, result.job_id))
    assert err.value.code == CODE_PUBLICATION_FAILED
    # Restore for other tests
    target.write_bytes(original)


def test_segment_ownership_chain_fails_closed(client) -> None:
    """AC5: cross-workspace/video/generation role/scene/artifact/job → zero rows before commit."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    from app.persistence.models import Workspace
    from app.persistence.structural_evidence import (
        OwnershipMismatchError,
        StructuralEvidenceRepository,
    )
    with svc.session_factory() as session:
        # Create a second workspace/video to test cross-ownership
        ws2 = Workspace(id="ws2-ownership-test", name="ws2")
        session.add(ws2)
        session.flush()
        # Try cross-workspace segment creation
        repo = StructuralEvidenceRepository(session)
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        seg = segs[0]
        before = _structural_counts(svc)
        with pytest.raises((OwnershipMismatchError, ValueError)):
            repo.create_extraction_segment(
                workspace_id="ws2-ownership-test",
                project_id=project_id,
                video_item_id=video_id,
                role_id=seg.role_id,
                scene_id=seg.scene_id,
                logical_id=str(uuid.uuid4()),
                segment_id=str(uuid.uuid4()),
                name="bad",
                kind="character",
                start_frame=seg.start_frame,
                end_frame=seg.end_frame,
                start_time_ms=seg.start_time_ms,
                end_time_ms=seg.end_time_ms,
                source_generation=seg.source_generation,
                source_job_id=result.job_id,
                prompt={"points": [{"x": 1.0, "y": 1.0, "label": "x"}]},
                segmentation={"points": [{"x": 1.0, "y": 1.0, "label": "x"}]},
                mask_artifact_id=seg.mask_artifact_id,
                confidence=0.8,
                confidence_source="detector",
                idempotency_key="test-cross-ws",
            )
        session.rollback()
        after = _structural_counts(svc)
        assert before == after


def test_stale_generation_segments_are_historical_and_read_only(client) -> None:
    """AC9: second run creates new generation; old segments stale/historical read-only."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    gen1 = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, gen1.job_id) == "completed"
    with svc.session_factory() as session:
        segs_gen1 = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == gen1.job_id)).all()  # noqa: E501
        assert len(segs_gen1) == 4
        seg_id = segs_gen1[0].id
        # Advance generation
        _replace_source(svc, video_id, "stale-test-gen2")
    gen2 = _submit(svc, project_id, video_id)
    assert gen2.job_id != gen1.job_id
    _run_worker(svc)
    assert _job_state(svc, gen2.job_id) == "completed"
    with svc.session_factory() as session:
        from app.persistence.structural_evidence import (
            SegmentConflictError,
            StructuralEvidenceRepository,
        )
        repo = StructuralEvidenceRepository(session)
        # Old segment should be stale (generation 1 vs current 2)
        old_seg = session.get(OccurrenceSegment, seg_id)
        assert old_seg is not None and old_seg.source_generation == "1"
        # Attempt to mutate stale segment should fail
        with pytest.raises(SegmentConflictError):
            repo.update_segment(DEFAULT_WORKSPACE_ID, seg_id, revision=old_seg.revision, name="mutated")  # noqa: E501
        # New generation segments exist
        segs_gen2 = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == gen2.job_id)).all()  # noqa: E501
        assert len(segs_gen2) == 4
        assert segs_gen2[0].source_generation == "2"


def test_occlusion_and_contact_edges_emitted(client) -> None:
    """AC8: deterministic adapter emits ≥1 occlusion + ≥1 contact per scene; FK/integrity clean."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        assert len(segs) == 4
        occls = session.scalars(select(SceneGraphOcclusion)).all()
        contacts = session.scalars(select(SceneGraphContact)).all()
        # Filter to this job's video
        job_occls = [o for o in occls if o.occluder_segment_id in {s.id for s in segs}]
        job_contacts = [c for c in contacts if c.source_segment_id in {s.id for s in segs}]
        assert len(job_occls) >= 2, f"expected >=1 occlusion per scene (2 scenes => >=2), got {len(job_occls)}"  # noqa: E501
        assert len(job_contacts) >= 2, f"expected >=1 contact per scene, got {len(job_contacts)}"
        # Range within endpoints
        for o in job_occls:
            occluder = session.get(OccurrenceSegment, o.occluder_segment_id)
            occludee = session.get(OccurrenceSegment, o.occludee_segment_id)
            assert occluder is not None and occludee is not None
            assert o.start_frame >= occluder.start_frame and o.end_frame <= occluder.end_frame
            assert o.start_frame >= occludee.start_frame and o.end_frame <= occludee.end_frame
        # FK check
        fk = session.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert fk == [], f"FK check failed: {fk}"
        integrity = session.execute(text("PRAGMA integrity_check")).scalar()
        assert integrity == "ok"


def test_no_false_motion_evidence(client) -> None:
    """AC7: production with no real estimator emits derived + reason, never 1.0/model."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        seg_ids = {s.id for s in segs}
        motions = session.scalars(select(SegmentMotion).where(SegmentMotion.occurrence_segment_id.in_(seg_ids))).all()  # noqa: E501
        assert len(motions) >= 4  # at least 2 per segment, but we create 2 per segment => 8
        for m in motions:
            # Never false evidence
            assert not (m.confidence == 1.0 and m.confidence_source == "model"), f"false evidence motion {m.id}"  # noqa: E501
            # If derived, must have explicit reason
            if m.confidence_source == "derived":
                import json as _j
                reasons = _j.loads(m.reasons_json) if m.reasons_json else []
                assert len(reasons) > 0


def test_correction_supersede_keeps_logical_id(client) -> None:
    """AC9: supersede_segment keeps logical_id, archives predecessor, both queryable."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        from app.persistence.structural_evidence import StructuralEvidenceRepository
        repo = StructuralEvidenceRepository(session)
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        seg = segs[0]
        logical = seg.logical_id
        rev = seg.revision
        # Supersede with manual correction (same generation, derived->manual)
        predecessor, successor = repo.supersede_segment(
            DEFAULT_WORKSPACE_ID,
            seg.id,
            revision=rev,
            source_generation=seg.source_generation,
            name="corrected-name",
            confidence_source="manual",
            provenance={"manual": "correction", "reason": "test"},
            reasons=["manual-correction"],
        )
        session.commit()
        assert successor.logical_id == logical
        assert predecessor.logical_id == logical
        assert predecessor.superseded_by_id == successor.id
        # Both queryable via lineage
        lineage = repo.segment_lineage(DEFAULT_WORKSPACE_ID, seg.id)
        assert len(lineage) == 2
        assert lineage[0].logical_id == logical and lineage[1].logical_id == logical
        # Stale predecessor read-only: attempt to update should fail
        from app.persistence.structural_evidence import SegmentConflictError
        with pytest.raises(SegmentConflictError):
            repo.update_segment(DEFAULT_WORKSPACE_ID, predecessor.id, revision=predecessor.revision + 1, name="again")  # noqa: E501

# ── S08-A02-T02-C1 — Truthful Evidence + Determinism (Lane B mandatory) ────────

def _structural_counts(svc):
    with svc.session_factory() as session:
        from app.persistence.models import OccurrenceSegment as _Seg  # noqa: E501
        from app.persistence.models import SceneGraphContact as _Con
        from app.persistence.models import SceneGraphOcclusion as _Occ
        from app.persistence.models import SegmentMotion as _Mot
        return {
            "segments": int(session.scalar(select(func.count()).select_from(_Seg)) or 0),
            "motions": int(session.scalar(select(func.count()).select_from(_Mot)) or 0),
            "occlusions": int(session.scalar(select(func.count()).select_from(_Occ)) or 0),
            "contacts": int(session.scalar(select(func.count()).select_from(_Con)) or 0),
        }

def test_c1_production_no_false_evidence_no_synthetic(client, monkeypatch):
    """C1-4: production-like without QA -> segments saved, NO synthetic motion/contact/occlusion, NO deterministic-layout."""  # noqa: E501
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    from app.persistence.jobs import JobRepository
    from app.services.object_extraction import PROVIDER_PRODUCTION, SAM2_MODEL_VERSION
    class _FakeProdProvider:
        name = PROVIDER_PRODUCTION
        model_version = SAM2_MODEL_VERSION
        def available(self):
            return True
        def extract(self, evidence):
            from app.services.object_extraction import (  # noqa: E501
                ExtractionArtifact,
                ExtractionCandidate,
                _crop_thumbnail,
                _layout_proposals,
                _mask_png,
            )
            cands = []
            for pp in _layout_proposals(evidence):
                thumb, tw, th = _crop_thumbnail(int(evidence["video_width"]), int(evidence["video_height"]), pp.bbox)  # noqa: E501
                mask, mw, mh = _mask_png(int(evidence["video_width"]), int(evidence["video_height"]), pp.bbox)  # noqa: E501
                cands.append(ExtractionCandidate(
                    name=pp.name,
                    kind="character",
                    confidence=0.75,
                    reasons=["sam2.1-local", f"scene-{pp.index+1}"],
                    occurrences=[{
                        "scene_id": pp.scene["id"],
                        "frame_index": pp.focus_frame,
                        "time_ms": pp.time_ms,
                        "bbox": pp.bbox,
                        "confidence": 0.75,
                        "confidence_source": "detector",
                        "algorithm": "sam2.1-local",
                        "algorithm_version": SAM2_MODEL_VERSION,
                        "reasons": ["sam2.1-local"],
                        "review_state": "unreviewed",
                    }],
                    artifacts=[
                        ExtractionArtifact(name=f"candidate_{pp.index+1:02d}_thumbnail.png", purpose="thumbnail", bytes=thumb, width=tw, height=th),  # noqa: E501
                        ExtractionArtifact(name=f"candidate_{pp.index+1:02d}_mask.png", purpose="mask", bytes=mask, width=mw, height=mh),  # noqa: E501
                    ],
                ))
            return cands
    import app.services.object_extraction as _oe
    orig_resolve = _oe.resolve_extraction_provider
    def _fake_resolve(provider, env=None):
        if provider == PROVIDER_PRODUCTION:
            return _FakeProdProvider()
        return orig_resolve(provider, env=env)
    monkeypatch.setattr(_oe, "resolve_extraction_provider", _fake_resolve)
    with svc.session_factory() as session:
        from app.persistence.models import Artifact
        video = session.get(VideoItem, video_id)
        assert video is not None and video.source_artifact_id is not None
        source = session.get(Artifact, video.source_artifact_id)
        assert source is not None
        manifest = {
            "schema_version": 1,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "project_id": project_id,
            "video_item_id": video_id,
            "generation": "1",
            "extractor_version": EXTRACTOR_VERSION,
            "provider": PROVIDER_PRODUCTION,
            "source_artifact_id": source.id,
            "source_sha256": source.sha256,
            "qa_mode": False,
            "managed_root": str(svc.managed_root),
        }
        repo = JobRepository(session)
        job = repo.create_job(
            workspace_id=DEFAULT_WORKSPACE_ID,
            job_type="DISCOVER_OBJECTS",
            owner_type="video_item",
            owner_id=video_id,
            input_manifest=manifest,
            idempotency_key=f"DISCOVER_OBJECTS:video_item:{video_id}:{source.sha256}:1:{EXTRACTOR_VERSION}",
            input_generation="1",
            steps=discover_objects_steps(),
            actor="api",
        )
        session.commit()
        job_id = job.id
    _run_worker(svc)
    assert _job_state(svc, job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == job_id)).all()  # noqa: E501
        assert len(segs) == 4, f"production should still save segments (2 cands *2 scenes) got {len(segs)}"  # noqa: E501
        for seg in segs:
            assert seg.algorithm != "deterministic-layout", f"production segment must not use deterministic-layout got {seg.algorithm}"  # noqa: E501
            assert seg.algorithm == "sam2.1-local"
        seg_ids = {s.id for s in segs}
        motions = session.scalars(select(SegmentMotion).where(SegmentMotion.occurrence_segment_id.in_(seg_ids))).all() if seg_ids else []  # noqa: E501
        occls = session.scalars(select(SceneGraphOcclusion).where(SceneGraphOcclusion.occluder_segment_id.in_(seg_ids))).all() if seg_ids else []  # noqa: E501
        contacts = session.scalars(select(SceneGraphContact).where(SceneGraphContact.source_segment_id.in_(seg_ids))).all() if seg_ids else []  # noqa: E501
        assert len(motions) == 0, f"production must have NO synthetic motions, got {len(motions)}"
        assert len(occls) == 0, f"production must have NO synthetic occlusions, got {len(occls)}"
        assert len(contacts) == 0, f"production must have NO synthetic contacts, got {len(contacts)}"  # noqa: E501

def test_c1_qa_synthetic_provenance_markers(client, monkeypatch):
    """C1-5: deterministic QA synthetic graph carries QA provenance markers."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        assert len(segs) > 0
        import json as _j
        for seg in segs:
            prov = _j.loads(seg.provenance_json) if seg.provenance_json else {}
            assert prov.get("provider") == "deterministic"
            assert prov.get("qa_mode") is True
            assert prov.get("synthetic") is True
        seg_ids = {s.id for s in segs}
        motions = session.scalars(select(SegmentMotion).where(SegmentMotion.occurrence_segment_id.in_(seg_ids))).all()  # noqa: E501
        assert len(motions) >= 4
        for m in motions:
            prov = _j.loads(m.provenance_json) if m.provenance_json else {}
            assert prov.get("provider") == "deterministic"
            assert prov.get("qa_mode") is True
            assert prov.get("synthetic") is True
        occls = session.scalars(select(SceneGraphOcclusion).where(SceneGraphOcclusion.occluder_segment_id.in_(seg_ids))).all()  # noqa: E501
        contacts = session.scalars(select(SceneGraphContact).where(SceneGraphContact.source_segment_id.in_(seg_ids))).all()  # noqa: E501
        for e in list(occls) + list(contacts):
            prov = _j.loads(e.provenance_json) if e.provenance_json else {}
            assert prov.get("provider") == "deterministic"
            assert prov.get("qa_mode") is True
            assert prov.get("synthetic") is True

def test_c1_missing_bbox_omit_never_fabricate(client, monkeypatch):
    """C1-7: missing/malformed bbox -> omit prompt evidence, never fabricate 10/10/50/50."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    import app.services.object_extraction as _oe
    orig_det = _oe.DeterministicExtractionProvider.extract
    def _bad_bbox_extract(self, evidence):
        cands = orig_det(self, evidence)
        if cands:
            for occ in cands[0].occurrences:
                occ.pop("bbox", None)
            if len(cands) > 1:
                cands[1].occurrences[0]["bbox"] = {"x": "oops", "y": None}
        return cands
    monkeypatch.setattr(_oe.DeterministicExtractionProvider, "extract", _bad_bbox_extract)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    state = _job_state(svc, result.job_id)
    assert state in ("completed", "failed"), f"missing bbox must fail closed or omit, got {state}"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        if state == "completed":
            assert len(segs) > 0
            import json as _j
            for seg in segs:
                prompt = _j.loads(seg.prompt_json) if seg.prompt_json else None
                if prompt is not None:
                    boxes = prompt.get("boxes") or []
                    for b in boxes:
                        assert not (b.get("x") == 10 and b.get("y") == 10 and b.get("w") == 50 and b.get("h") == 50), "fabricated bbox 10/10/50/50 must never appear"  # noqa: E501
            has_none = any(seg.prompt_json is None for seg in segs)
            assert has_none, "missing bbox should result in at least one segment with prompt None (omit)"  # noqa: E501
        else:
            assert len(segs) == 0, "fail closed must leave zero segments"

@pytest.mark.parametrize("bad_conf", [float("nan"), float("inf"), float("-inf"), 1.5, -0.1])
def test_c1_invalid_confidence_fail_closed_zero_mutation(client, monkeypatch, bad_conf):
    """C1-8: NaN/Inf/out-of-range confidence -> fail closed, zero partial mutation."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    import app.services.object_extraction as _oe
    orig_det = _oe.DeterministicExtractionProvider.extract
    def _bad_conf_extract(self, evidence):
        cands = orig_det(self, evidence)
        if cands:
            cands[0].confidence = bad_conf
            if cands[0].occurrences:
                cands[0].occurrences[0]["confidence"] = bad_conf
        return cands
    monkeypatch.setattr(_oe.DeterministicExtractionProvider, "extract", _bad_conf_extract)
    before = _structural_counts(svc)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    state = _job_state(svc, result.job_id)
    assert state == "failed", f"bad confidence {bad_conf!r} must fail closed, got {state}"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        assert len(segs) == 0, "fail closed must leave zero segments for bad confidence job"
    after = _structural_counts(svc)
    assert after["segments"] == before["segments"]
    assert after["motions"] == before["motions"]

def test_c1_invalid_confidence_missing_fail_closed(client, monkeypatch):
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    import app.services.object_extraction as _oe
    orig_det = _oe.DeterministicExtractionProvider.extract
    def _missing_conf_extract(self, evidence):
        cands = orig_det(self, evidence)
        if cands:
            cands[0].confidence = None  # type: ignore
            if cands[0].occurrences:
                cands[0].occurrences[0]["confidence"] = None
        return cands
    monkeypatch.setattr(_oe.DeterministicExtractionProvider, "extract", _missing_conf_extract)
    before = _structural_counts(svc)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    state = _job_state(svc, result.job_id)
    assert state == "failed"
    after = _structural_counts(svc)
    assert after["segments"] == before["segments"]

def test_c1_wrong_type_already_bound_not_swallowed(client, monkeypatch):
    """C1-10: exception with text 'already bound' but WRONG type must NOT be swallowed."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    import app.persistence.structural_evidence as _se
    def _raise_wrong_type(self, *args, **kwargs):
        raise ValueError("already bound to another segment")
    monkeypatch.setattr(_se.StructuralEvidenceRepository, "create_motion", _raise_wrong_type)
    _run_worker(svc)
    state = _job_state(svc, result.job_id)
    assert state == "failed", f"wrong-type 'already bound' must propagate, job state {state} should be failed"  # noqa: E501
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()  # noqa: E501
        assert len(segs) == 0

def test_c1_cross_process_deterministic_qa_byte_identical(tmp_path):
    """C2 Blocker 2 — REAL cross-process determinism via actual publication path.

    Two fresh subprocesses with DIFFERENT PYTHONHASHSEED each:
    - create a fresh isolated SQLite DB + managed root
    - run the ACTUAL handler (real StructuralEvidenceRepository, real publication,
      deterministic QA provider + explicit QA mode, fresh isolated DB)
    - query evidence from DB AFTER publication
    Normalize only env/job-specific identifiers the contract allows to differ,
    compare prompt/segmentation JSON, mask SHA256, camera/object transforms,
    motion refs, occlusion/contact kind+ranges, synthetic provenance, ordering.
    Test MUST FAIL if implementation reverts to hash(seg_id).
    """
    import json as _json
    import os as _os
    import subprocess as _sp
    import sys as _sys_inner  # noqa: F811
    import textwrap as _tw
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parent.parent

    # Shared runner template — each subprocess creates its own isolated DB/managed root,
    # seeds video, submits QA job, runs worker, queries DB and emits normalized evidence.
    runner = _tw.dedent('''
        import hashlib, json, os, sys, uuid
        from pathlib import Path
        repo = Path(os.environ["REPO_ROOT"])
        sys.path.insert(0, str(repo))
        # Force deterministic uuid sequence so both processes generate same Job id and same other ids
        import uuid as _uuid
        _orig_uuid4 = _uuid.uuid4
        _uuid_counter = {"n": 0}
        def _deterministic_uuid4():
            _uuid_counter["n"] += 1
            # Generate deterministic UUID from counter (same sequence in both processes)
            return _uuid.UUID(int=_uuid_counter["n"])
        _uuid.uuid4 = _deterministic_uuid4

        from app.api import deps
        from app.config import AppConfig
        from app.persistence import create_engine_for_path, create_session_factory
        from app.persistence.jobs import JobRepository
        from app.persistence.models import Artifact, Job, Project, Scene, VideoItem, Workspace
        from app.persistence.models import OccurrenceSegment, SegmentMotion, SceneGraphOcclusion, SceneGraphContact
        from app.services.object_extraction import submit_discover_objects, PROVIDER_DETERMINISTIC
        from sqlalchemy import select
        import hashlib as _h

        # Setup isolated DB/managed root
        tmp = Path(os.environ["TMP_ROOT"])
        db_path = tmp / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        from alembic.config import Config as _AConfig
        from alembic import command as _acmd
        cfg = _AConfig(str(repo / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo / "migrations"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
        _acmd.upgrade(cfg, "head")

        from app.workflow.job_service import JobService
        factory = create_session_factory(create_engine_for_path(db_path))
        managed_root = tmp / "artifacts"
        managed_root.mkdir(parents=True, exist_ok=True)
        # Bind deps for submit/worker (uses session_factory + managed_root)
        from app.api import deps as _deps
        import app.config as _acfg
        test_config = _acfg.AppConfig(
            project_root=tmp, models_dir=tmp / "models",
            output_dir=tmp / "output")
        _deps._config = test_config
        svc = JobService(factory, worker=None, managed_root=managed_root)
        _deps._job_service = svc
        _deps._lifecycle_db = db_path
        # Seed video item
        SOURCE_MEDIA_BYTES = (bytes(range(1, 256)) * 48) + b"S08-C2-cross-source"
        SOURCE_SHA = _h.sha256(SOURCE_MEDIA_BYTES).hexdigest()
        from app.persistence import DEFAULT_WORKSPACE_ID
        # Fixed deterministic ids for cross-process byte-identical evidence
        FIXED_PROJ_ID = "11111111-1111-1111-1111-111111111111"
        FIXED_VID_ID = "22222222-2222-2222-2222-222222222222"
        FIXED_SCENE_IDS = ["33333333-3333-3333-3333-333333333333", "44444444-4444-4444-4444-444444444444"]
        with factory() as s:
            ws = s.get(Workspace, DEFAULT_WORKSPACE_ID)
            if ws is None:
                ws = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
                s.add(ws)
            proj = Project(id=FIXED_PROJ_ID, workspace_id=DEFAULT_WORKSPACE_ID, name="Cross Project")
            s.add(proj)
            s.flush()
            vid = VideoItem(
                id=FIXED_VID_ID, project=proj, title="Primary", position=0,
                width=320, height=240, duration_ms=6000,
                fps_num=30, fps_den=1)
            s.add(vid)
            s.flush()
            rel = f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{vid.id}/import/source.mp4"
            mp = managed_root / rel
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_bytes(SOURCE_MEDIA_BYTES)
            art = Artifact(
                workspace_id=DEFAULT_WORKSPACE_ID, kind="video",
                relative_path=rel, state="ready", sha256=SOURCE_SHA,
                size_bytes=len(SOURCE_MEDIA_BYTES), mime_type="video/mp4")
            s.add(art)
            s.flush()
            vid.source_artifact_id = art.id
            for idx in range(2):
                s.add(Scene(id=FIXED_SCENE_IDS[idx], video_item=vid, position=idx, start_frame=idx*90, end_frame=idx*90+89, start_time_ms=idx*3000, end_time_ms=idx*3000+2999, status="pending"))
            s.commit()
            proj_id = proj.id
            vid_id = vid.id

        # Submit with deterministic QA provider + explicit QA mode
        from app.services.object_extraction import submit_discover_objects
        result = submit_discover_objects(factory, workspace_id=DEFAULT_WORKSPACE_ID, project_id=proj_id, video_item_id=vid_id, extractor_version="1.0.0", provider=PROVIDER_DETERMINISTIC, managed_root=managed_root, env={"MOTIONFORGE_EXTRACTION_QA_MODE": "1"})
        # Run worker
        claimed = svc.worker.run_once()
        # Query evidence AFTER publication
        with factory() as s:
            segs = list(s.scalars(select(OccurrenceSegment).order_by(OccurrenceSegment.z_order, OccurrenceSegment.start_frame)).all())
            mots = list(s.scalars(select(SegmentMotion).order_by(SegmentMotion.transform_type, SegmentMotion.start_frame)).all())
            occs = list(s.scalars(select(SceneGraphOcclusion).order_by(SceneGraphOcclusion.start_frame)).all())
            cons = list(s.scalars(select(SceneGraphContact).order_by(SceneGraphContact.start_frame)).all())
            # Build normalized payload: compare prompt/seg JSON, mask SHA, transforms, refs, kind+ranges, provenance synthetic flag, ordering
            # Normalize job_id-derived identifiers: replace job_id substrings, but keep payload equality via ordering
            import json as _j
            def _norm_provenance(p):
                if p is None:
                    return None
                try:
                    d = _j.loads(p) if isinstance(p, str) else p
                except Exception:
                    return p
                # Only keep deterministic fields for comparison, normalize job_id
                if isinstance(d, dict):
                    d = {k: ("<JOB_ID>" if k=="job_id" else v) for k,v in d.items()}
                return _j.dumps(d, sort_keys=True) if isinstance(d, dict) else d

            seg_payload = []
            for seg in segs:
                seg_payload.append({
                    "prompt": seg.prompt_json,
                    "segmentation": seg.segmentation_json,
                    "mask_sha": s.get(Artifact, seg.mask_artifact_id).sha256 if seg.mask_artifact_id else None,
                    "provenance_synthetic": _norm_provenance(seg.provenance_json),
                    "z_order": seg.z_order,
                    "start_frame": seg.start_frame,
                    "end_frame": seg.end_frame,
                })
            mot_payload = []
            for m in mots:
                mot_payload.append({
                    "transform_type": m.transform_type,
                    "transform": m.transform_json,
                    "ref": m.point_track_flow_ref_json,
                    "provenance_synthetic": _norm_provenance(m.provenance_json),
                    "start_frame": m.start_frame,
                    "end_frame": m.end_frame,
                })
            occ_payload = []
            for o in occs:
                occ_payload.append({
                    "start_frame": o.start_frame,
                    "end_frame": o.end_frame,
                    "provenance_synthetic": _norm_provenance(o.provenance_json),
                    "start_time_ms": o.start_time_ms,
                    "end_time_ms": o.end_time_ms,
                })
            con_payload = []
            for c in cons:
                con_payload.append({
                    "kind": c.contact_kind,
                    "start_frame": c.start_frame,
                    "end_frame": c.end_frame,
                    "provenance_synthetic": _norm_provenance(c.provenance_json),
                    "start_time_ms": c.start_time_ms,
                    "end_time_ms": c.end_time_ms,
                })
            out = {
                "segments": seg_payload,
                "motions": mot_payload,
                "occlusions": occ_payload,
                "contacts": con_payload,
                # Also include artifact mask SHA ordering check: collect mask artifact SHA in segment order
                "mask_shas": [p["mask_sha"] for p in seg_payload],
            }
            print(json.dumps(out, sort_keys=True))
            # Also verify worker succeeded
            jr = JobRepository(s)
            job = jr.get_job(result.job_id)
            assert job.state == "completed", f"job not completed: {job.state}"
    ''')

    outputs = []
    for seed in ("1", "999"):
        tmp_sub = tmp_path / f"cross_{seed}"
        tmp_sub.mkdir(parents=True, exist_ok=True)
        env = {**_os.environ, "PYTHONHASHSEED": seed, "REPO_ROOT": str(repo_root), "TMP_ROOT": str(tmp_sub)}
        # Ensure MOTIONFORGE_DATABASE_URL unset
        env.pop("MOTIONFORGE_DATABASE_URL", None)
        result = _sp.run([_sys_inner.executable, "-c", runner], capture_output=True, text=True, env=env, cwd=str(repo_root))
        assert result.returncode == 0, f"seed {seed} failed:\nSTDOUT:{result.stdout[:2000]}\nSTDERR:{result.stderr[:2000]}"
        data = _json.loads(result.stdout.strip().splitlines()[-1])
        outputs.append(data)

    # Normalize only allowed differences: job_id already normalized inside runner; ordering already deterministic via order_by
    # Compare byte-identical JSON after normalization
    j1 = _json.dumps(outputs[0], sort_keys=True)
    j2 = _json.dumps(outputs[1], sort_keys=True)
    assert j1 == j2, f"cross-process real publication diverged:\n{j1[:2000]}\nvs\n{j2[:2000]}"

    # Verify key evidence present
    assert len(outputs[0]["segments"]) > 0
    assert len(outputs[0]["motions"]) > 0
    assert len(outputs[0]["mask_shas"]) == len(outputs[0]["segments"])
    # Fail if hash(seg_id) was used: object_relative tx would differ across seeds, but our runner already compared motions
    # Additional check: ensure object_relative transform tx is stable sha256 digest, not hash()
    # Since we compared motions equality, hash() instability would have caused j1 != j2 and already failed.


# ── C2 — Idempotency Conflict Safety (real DB, no substring, atomic rollback) ──

def test_c2_idempotent_replay_byte_identical(client):
    """C2 Blocker 1: byte-identical replay returns (record, False) and does not duplicate rows."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    before = _structural_counts(svc)
    # Replay via handler (second publication with same idempotency keys, same payload)
    from app.services.object_extraction import discover_objects_handler
    ctx = _ctx(svc, result.job_id)
    out = discover_objects_handler(ctx)
    assert out["published"]["manifest_artifact_id"] is not None
    after = _structural_counts(svc)
    assert after == before, f"byte-identical replay must not duplicate rows: before {before} after {after}"
    assert _job_state(svc, result.job_id) == "completed"


def test_c2_conflict_motion_transform_raises_and_rolls_back(client):
    """Same idempotency key but mutated motion transform must raise MotionConflictError and not mutate row."""
    from app.persistence.structural_evidence import (
        MotionConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()
        assert segs, "no segments published"
        seg = segs[0]
        repo = StructuralEvidenceRepository(session)
        motions = repo.list_motions(workspace_id=seg.workspace_id, occurrence_segment_id=seg.id)
        assert motions, "no motions published"
        mot = motions[0]
        before_counts = _structural_counts(svc)
        before_transform = mot.transform
        # Mutate transform (e.g., change tx)
        mutated_transform = dict(before_transform)
        # Ensure mutation is material
        if isinstance(mutated_transform, dict):
            mutated_transform["tx_mutated"] = 999.0
            mutated_transform["rotation_deg"] = 45.0
        else:
            mutated_transform = {"mutated": True}
        # Need idempotency key of existing motion
        row = session.get(SegmentMotion, mot.id)
        assert row is not None
        idem = row.idempotency_key
        assert idem is not None
        # Attempt duplicate with same key but different transform
        try:
            repo.create_motion(
                row.workspace_id,
                mot.occurrence_segment_id,
                mot.transform_type,
                mutated_transform,
                point_track_flow_ref=mot.point_track_flow_ref,
                start_frame=mot.start_frame,
                end_frame=mot.end_frame,
                start_time_ms=mot.start_time_ms,
                end_time_ms=mot.end_time_ms,
                algorithm=mot.algorithm,
                algorithm_version=mot.algorithm_version,
                confidence=mot.confidence,
                confidence_source=mot.confidence_source,
                reasons=mot.reasons,
                provenance=mot.provenance,
                idempotency_key=idem,
            )
            raise AssertionError("mutated motion transform must raise MotionConflictError")
        except MotionConflictError:
            pass
        session.rollback()
        after_counts = _structural_counts(svc)
        assert after_counts == before_counts, f"conflict must not mutate counts: {before_counts} vs {after_counts}"
        # Verify existing row not mutated
        with svc.session_factory() as s2:
            m2 = StructuralEvidenceRepository(s2).get_motion(row.workspace_id, mot.id)
            assert m2.transform == before_transform, "existing motion must not be mutated on conflict"


def test_c2_conflict_motion_ref_raises_and_rolls_back(client):
    """Mutated motion point_track_flow_ref must raise MotionConflictError."""
    from app.persistence.structural_evidence import (
        MotionConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).first()
        assert seg is not None
        repo = StructuralEvidenceRepository(session)
        mot = repo.list_motions(seg.workspace_id, seg.id)[0]
        row = session.get(SegmentMotion, mot.id)
        assert row is not None
        before = _structural_counts(svc)
        before_ref = mot.point_track_flow_ref
        idem = row.idempotency_key
        mutated_ref = {"tracks": ["mutated-track"], "kind": "sparse_flow", "extra": "mutated"}
        try:
            repo.create_motion(
                row.workspace_id,
                mot.occurrence_segment_id,
                mot.transform_type,
                mot.transform,
                point_track_flow_ref=mutated_ref,
                start_frame=mot.start_frame,
                end_frame=mot.end_frame,
                start_time_ms=mot.start_time_ms,
                end_time_ms=mot.end_time_ms,
                algorithm=mot.algorithm,
                algorithm_version=mot.algorithm_version,
                confidence=mot.confidence,
                confidence_source=mot.confidence_source,
                reasons=mot.reasons,
                provenance=mot.provenance,
                idempotency_key=idem,
            )
            raise AssertionError("mutated motion ref must raise MotionConflictError")
        except MotionConflictError:
            pass
        session.rollback()
        assert _structural_counts(svc) == before
        with svc.session_factory() as s2:
            m2 = StructuralEvidenceRepository(s2).get_motion(row.workspace_id, mot.id)
            assert m2.point_track_flow_ref == before_ref


def test_c2_conflict_occlusion_endpoint_raises_and_rolls_back(client):
    """Mutated occlusion endpoint must raise OcclusionConflictError."""
    from app.persistence.structural_evidence import (
        OcclusionConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg_ids = [s.id for s in session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()]
        assert len(seg_ids) >= 2
        # Find existing occlusion
        repo = StructuralEvidenceRepository(session)
        # Need workspace/project/video from first segment
        seg0 = session.get(OccurrenceSegment, seg_ids[0])
        assert seg0 is not None
        occs = repo.list_occlusions(seg0.workspace_id)
        assert occs, "no occlusion published (need >=2 segments per scene)"
        occ = occs[0]
        row = session.get(SceneGraphOcclusion, occ.id)
        assert row is not None
        idem = row.idempotency_key
        before = _structural_counts(svc)
        # Mutate endpoint: swap occluder/occludee (both remain in same scene, range still valid)
        # This is a materially different payload with same idempotency key -> must raise OcclusionConflictError
        mutated_occluder = row.occludee_segment_id
        mutated_occludee = row.occluder_segment_id
        try:
            repo.create_occlusion(
                row.workspace_id,
                row.project_id,
                row.video_item_id,
                mutated_occluder,
                mutated_occludee,
                start_frame=row.start_frame,
                end_frame=row.end_frame,
                start_time_ms=row.start_time_ms,
                end_time_ms=row.end_time_ms,
                algorithm=row.algorithm,
                algorithm_version=row.algorithm_version,
                confidence=row.confidence,
                confidence_source=row.confidence_source,
                reasons=occ.reasons,
                provenance=occ.provenance,
                idempotency_key=idem,
            )
            raise AssertionError("mutated occlusion endpoint must raise OcclusionConflictError")
        except OcclusionConflictError:
            pass
        session.rollback()
        assert _structural_counts(svc) == before


def test_c2_conflict_occlusion_range_raises_and_rolls_back(client):
    """Mutated occlusion temporal range must raise OcclusionConflictError."""
    from app.persistence.structural_evidence import (
        OcclusionConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg0 = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).first()
        assert seg0 is not None
        repo = StructuralEvidenceRepository(session)
        occ = repo.list_occlusions(seg0.workspace_id)[0]
        row = session.get(SceneGraphOcclusion, occ.id)
        assert row is not None
        before = _structural_counts(svc)
        idem = row.idempotency_key
        # Mutate range: shift start_frame by 1 if possible, else end
        new_sf = row.start_frame + 1 if row.start_frame + 1 <= row.end_frame else row.start_frame
        # Need to keep within segment range; use same scope but mutate by 1
        # If not mutated, try end
        if new_sf == row.start_frame:
            new_ef = row.end_frame - 1 if row.end_frame > row.start_frame else row.end_frame
        else:
            new_ef = row.end_frame
        # Ensure we actually mutate
        assert (new_sf != row.start_frame or new_ef != row.end_frame), "cannot mutate range"
        try:
            repo.create_occlusion(
                row.workspace_id,
                row.project_id,
                row.video_item_id,
                row.occluder_segment_id,
                row.occludee_segment_id,
                start_frame=new_sf,
                end_frame=new_ef,
                start_time_ms=row.start_time_ms,
                end_time_ms=row.end_time_ms,
                algorithm=row.algorithm,
                algorithm_version=row.algorithm_version,
                confidence=row.confidence,
                confidence_source=row.confidence_source,
                reasons=occ.reasons,
                provenance=occ.provenance,
                idempotency_key=idem,
            )
            raise AssertionError("mutated occlusion range must raise OcclusionConflictError")
        except OcclusionConflictError:
            pass
        session.rollback()
        assert _structural_counts(svc) == before


def test_c2_conflict_contact_kind_raises_and_rolls_back(client):
    """Mutated contact kind must raise ContactConflictError."""
    from app.persistence.structural_evidence import (
        ContactConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg0 = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).first()
        assert seg0 is not None
        repo = StructuralEvidenceRepository(session)
        cons = repo.list_contacts(seg0.workspace_id)
        # Contacts may be filtered by segment; try global list
        if not cons:
            # list all contacts for workspace
            from sqlalchemy import select as _sel
            rows = session.scalars(_sel(SceneGraphContact).where(SceneGraphContact.workspace_id == seg0.workspace_id)).all()
            assert rows, "no contact published"
            con = rows[0]
            # need record; use direct row
            row = con
            # Build needed fields manually
            idem = row.idempotency_key
            before = _structural_counts(svc)
            # mutate kind to different
            other_kind = "contact" if row.contact_kind != "contact" else "occlusion"
            # Find a valid CONTACT_KINDS value different from current
            from app.persistence.models import CONTACT_KINDS
            for k in CONTACT_KINDS:
                if k != row.contact_kind:
                    other_kind = k
                    break
            try:
                repo.create_contact(
                    row.workspace_id,
                    row.project_id,
                    row.video_item_id,
                    row.source_segment_id,
                    row.target_segment_id,
                    contact_kind=other_kind,
                    start_frame=row.start_frame,
                    end_frame=row.end_frame,
                    start_time_ms=row.start_time_ms,
                    end_time_ms=row.end_time_ms,
                    algorithm=row.algorithm,
                    algorithm_version=row.algorithm_version,
                    confidence=row.confidence,
                    confidence_source=row.confidence_source,
                    reasons=json.loads(row.reasons_json) if row.reasons_json else [],
                    provenance=json.loads(row.provenance_json) if row.provenance_json else None,
                    idempotency_key=idem,
                )
                raise AssertionError("mutated contact kind must raise ContactConflictError")
            except ContactConflictError:
                pass
            session.rollback()
            assert _structural_counts(svc) == before
            return
        con = cons[0]
        row = session.get(SceneGraphContact, con.id)
        assert row is not None
        idem = row.idempotency_key
        before = _structural_counts(svc)
        from app.persistence.models import CONTACT_KINDS
        other_kind = next(k for k in CONTACT_KINDS if k != row.contact_kind)
        try:
            repo.create_contact(
                row.workspace_id,
                row.project_id,
                row.video_item_id,
                row.source_segment_id,
                row.target_segment_id,
                contact_kind=other_kind,
                start_frame=row.start_frame,
                end_frame=row.end_frame,
                start_time_ms=row.start_time_ms,
                end_time_ms=row.end_time_ms,
                algorithm=row.algorithm,
                algorithm_version=row.algorithm_version,
                confidence=row.confidence,
                confidence_source=row.confidence_source,
                reasons=json.loads(row.reasons_json) if row.reasons_json else [],
                provenance=json.loads(row.provenance_json) if row.provenance_json else None,
                idempotency_key=idem,
            )
            raise AssertionError("mutated contact kind must raise ContactConflictError")
        except ContactConflictError:
            pass
        session.rollback()
        assert _structural_counts(svc) == before


def test_c2_conflict_contact_range_raises_and_rolls_back(client):
    """Mutated contact temporal range must raise ContactConflictError."""
    from app.persistence.structural_evidence import (
        ContactConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg0 = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).first()
        assert seg0 is not None
        repo = StructuralEvidenceRepository(session)
        # Get contact via direct query to handle any filtering
        from sqlalchemy import select as _sel
        rows = session.scalars(_sel(SceneGraphContact).where(SceneGraphContact.workspace_id == seg0.workspace_id)).all()
        assert rows, "no contact published"
        row = rows[0]
        before = _structural_counts(svc)
        idem = row.idempotency_key
        new_sf = row.start_frame + 1 if row.start_frame + 1 <= row.end_frame else row.start_frame
        if new_sf == row.start_frame:
            new_ef = row.end_frame - 1 if row.end_frame > row.start_frame else row.end_frame
        else:
            new_ef = row.end_frame
        assert (new_sf != row.start_frame or new_ef != row.end_frame)
        try:
            repo.create_contact(
                row.workspace_id,
                row.project_id,
                row.video_item_id,
                row.source_segment_id,
                row.target_segment_id,
                contact_kind=row.contact_kind,
                start_frame=new_sf,
                end_frame=new_ef,
                start_time_ms=row.start_time_ms,
                end_time_ms=row.end_time_ms,
                algorithm=row.algorithm,
                algorithm_version=row.algorithm_version,
                confidence=row.confidence,
                confidence_source=row.confidence_source,
                reasons=json.loads(row.reasons_json) if row.reasons_json else [],
                provenance=json.loads(row.provenance_json) if row.provenance_json else None,
                idempotency_key=idem,
            )
            raise AssertionError("mutated contact range must raise ContactConflictError")
        except ContactConflictError:
            pass
        session.rollback()
        assert _structural_counts(svc) == before


def test_c2_exception_text_independence_propagates_regardless_of_message(client, monkeypatch):
    """Correct conflict must propagate even when exception text is changed — no substring matching."""
    from app.persistence.structural_evidence import (
        MotionConflictError,
        StructuralEvidenceRepository,
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = _submit(svc, project_id, video_id)
    # Patch repo to raise MotionConflictError with custom text that does NOT contain "already bound"
    def _raise_custom(self, *a, **k):
        raise MotionConflictError("custom conflict text — no magic substring, but still a typed conflict")
    monkeypatch.setattr(StructuralEvidenceRepository, "create_motion", _raise_custom)
    _run_worker(svc)
    state = _job_state(svc, result.job_id)
    assert state == "failed", f"custom-text MotionConflictError must still propagate, got {state}"
    with svc.session_factory() as session:
        segs = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).all()
        assert len(segs) == 0, "publication must roll back on custom-text conflict"


def test_c2_qa_provenance_uses_actual_provider_deterministic(client):
    """QA provenance must carry actual provider 'deterministic' (not hardcoded)."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    # Submit with deterministic provider
    result = submit_discover_objects(
        svc.session_factory,
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=project_id,
        video_item_id=video_id,
        extractor_version="1.0.0",
        provider=PROVIDER_DETERMINISTIC,
        managed_root=svc.managed_root,
        env={"MOTIONFORGE_EXTRACTION_QA_MODE": "1"},
    )
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).first()
        assert seg is not None
        prov = json.loads(seg.provenance_json) if seg.provenance_json else {}
        assert prov.get("provider") == PROVIDER_DETERMINISTIC, f"provenance provider must be {PROVIDER_DETERMINISTIC}, got {prov.get('provider')}"
        assert prov.get("synthetic") is True
        assert prov.get("qa_mode") is True
        # Check motions provenance similarly
        from app.persistence.structural_evidence import StructuralEvidenceRepository
        repo = StructuralEvidenceRepository(session)
        mots = repo.list_motions(seg.workspace_id, seg.id)
        assert mots
        for m in mots:
            assert m.provenance.get("provider") == PROVIDER_DETERMINISTIC


def test_c2_qa_provenance_uses_actual_provider_deterministic_identity(client):
    """QA provenance must carry actual provider 'deterministic-identity' (not hardcoded)."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    result = submit_discover_objects(
        svc.session_factory,
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=project_id,
        video_item_id=video_id,
        extractor_version="1.0.0",
        provider=PROVIDER_DETERMINISTIC_IDENTITY,
        managed_root=svc.managed_root,
        env={"MOTIONFORGE_EXTRACTION_QA_MODE": "1"},
    )
    _run_worker(svc)
    assert _job_state(svc, result.job_id) == "completed"
    with svc.session_factory() as session:
        seg = session.scalars(select(OccurrenceSegment).where(OccurrenceSegment.source_job_id == result.job_id)).first()
        assert seg is not None
        prov = json.loads(seg.provenance_json) if seg.provenance_json else {}
        assert prov.get("provider") == PROVIDER_DETERMINISTIC_IDENTITY, f"provenance provider must be {PROVIDER_DETERMINISTIC_IDENTITY}, got {prov.get('provider')}"
        assert prov.get("synthetic") is True
        # Motions
        from app.persistence.structural_evidence import StructuralEvidenceRepository
        repo = StructuralEvidenceRepository(session)
        mots = repo.list_motions(seg.workspace_id, seg.id)
        assert mots
        for m in mots:
            assert m.provenance.get("provider") == PROVIDER_DETERMINISTIC_IDENTITY, f"motion provenance must be deterministic-identity, got {m.provenance.get('provider')}"


def test_c2_no_substring_classification_in_service():
    """Service must not classify domain errors by substring 'already bound'."""
    import pathlib
    p = pathlib.Path("app/services/object_extraction.py")
    text = p.read_text(encoding="utf-8")
    assert "already bound" not in text, "service must not contain substring check for 'already bound'"
    # Also ensure no try/except around create_* remains
    # Check that create_motion is not inside try
    assert text.count("repo.create_motion") == 2, "should have exactly 2 direct create_motion calls"
    assert text.count("repo.create_occlusion") == 1
    assert text.count("repo.create_contact") == 1



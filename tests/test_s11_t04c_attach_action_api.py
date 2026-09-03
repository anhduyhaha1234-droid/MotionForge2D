"""S11-T04C (W11) — original-audio attach action API + A/V recheck trigger.

Binding behavior map (production plan REV7/C6, block W11 — C4-F3):

- The attach action route is SERVER-OWNED (Decision H): the client payload
  carries ONLY ``{video_item_id}`` — never a filesystem path, handler or
  provider.  The source artifact is resolved from the VideoItem's
  ``source_artifact_id`` authority by ``submit_attach_original_audio``.
- Idempotency + conflict semantics match the existing
  ``AttachSubmitResult`` / ``IdempotencyKeyInUse`` contract: a completed
  duplicate reuses the same Job (``reused=True``); an ACTIVE duplicate
  fails closed (409 on the route).
- The A/V recheck (RUN_QC_CHECKS, audio scope) is enqueued ONLY on the
  verified output-validation completion path — after
  ``_attach_output_validator`` verified the published bytes (or the
  terminal NO_AUDIO_PRESENT outcome) — through
  ``app.services.qc_av_recheck.ensure_av_recheck`` (submit authority T03G).
  Any enqueue failure raises so the attach step NEVER completes
  (fail-closed).
- A route that receives a COMPLETED/REUSED attach job calls
  ``ensure_av_recheck`` to backfill a missing recheck run; retrying the
  validator never creates a duplicate run (idempotency key binds the
  evidence fingerprint + policy hash + scope).
- No code path resolves a QCItem directly.

Isolation: per-test temp SQLite DB (Alembic head), short unique
Windows-native basetemp, ``-p no:cacheprovider``, MOTIONFORGE_DATABASE_URL
stripped by the runner.  Media fixtures are real FFmpeg lavfi synthetics
(skipped cleanly when FFmpeg is unavailable); the durable worker comes
from the REAL default JobService registration block.

RED gate: ``app.services.qc_av_recheck`` and
``app.api.routes.original_audio_action`` do NOT exist at WAVE_BASE —
importing them here is the RED proof.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

# RED gate imports (ModuleNotFoundError before implementation).
from app.api.routes.original_audio_action import (  # noqa: F401
    OriginalAudioAttachRequest,
    OriginalAudioAttachResponse,
)
from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Job,
    JobAttempt,
    JobLease,
    JobStep,
    Project,
    VideoItem,
    Workspace,
)
from app.services import video_import
from app.services.qc_av_recheck import (  # noqa: F401
    AvRecheckEnqueueError,
    attach_recheck_evidence,
    ensure_av_recheck,
)
from app.services.video_import import submit_import
from app.workflow.durable_worker import DurableWorker, WorkerConfig
from app.workflow.job_service import JobService
from app.workflow.original_audio_handler import (
    JOB_TYPE_ATTACH_ORIGINAL_AUDIO,
    _attach_output_validator,  # noqa: F401  (verified-completion gate under test)
    submit_attach_original_audio,
)
from app.workflow.qc_checks_handler import JOB_TYPE_RUN_QC_CHECKS, SCOPE_AUDIO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

WS = "ws-s11-t04c"
P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
V1 = str(uuid.uuid4())
V2 = str(uuid.uuid4())


# ── Audio band registration (T03G contract; orchestrator consumes the
# ── registry read-only) ─────────────────────────────────────────────────────

_AUDIO_REGISTRATION = [
    ("audio_missing", "app.services.qc_checks.audio_missing:detect"),
    ("av_sync_drift", "app.services.qc_checks.av_sync_drift:detect"),
]


@pytest.fixture(scope="module", autouse=True)
def _ensure_audio_band_registered() -> None:
    from app.services.qc_checks import audio_missing, av_sync_drift  # noqa: F401
    from app.services.qc_checks.registry import registry

    for name, entry_point in _AUDIO_REGISTRATION:
        registry.register(name, entry_point)


# ── Deterministic clock/sleeper (mirror test_s11_attach_original_audio_job) ─


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 3, 22, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ── Temp DB fixtures (production schema via Alembic) ────────────────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "t04c.db"


@pytest.fixture()
def session_factory(db_path: Path):
    _upgrade(db_path)
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture()
def ws(session: Session) -> Workspace:
    ws_row = Workspace(name="T04C Workspace")
    session.add(ws_row)
    session.commit()
    return ws_row


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    proj = Project(name="T04C Project", workspace_id=ws.id, status="active")
    session.add(proj)
    session.commit()
    return proj


@pytest.fixture()
def video_item(session: Session, project: Project) -> VideoItem:
    item = VideoItem(
        project_id=project.id,
        title="Clip T04C",
        position=0,
        status="imported",
        revision=1,
    )
    session.add(item)
    session.commit()
    return item


@pytest.fixture()
def managed_root(tmp_path: Path) -> Path:
    root = tmp_path / "managed"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def sleeper() -> FakeSleeper:
    return FakeSleeper()


@pytest.fixture()
def svc(
    session_factory,
    managed_root: Path,
    clock: FakeClock,
    sleeper: FakeSleeper,
) -> JobService:
    """The DEFAULT production JobService over temp roots (real registration)."""
    service = JobService(session_factory, managed_root=managed_root)
    worker = service.worker
    assert worker is not None
    worker._config = WorkerConfig(  # noqa: SLF001 - test seam on own instance
        worker_id="t04c-worker",
        lease_ttl=60,
        heartbeat_interval=15,
        poll_interval=0.01,
        max_attempts=3,
        staging_root=managed_root,
    )
    object.__setattr__(worker, "_clock", clock)
    object.__setattr__(worker, "_sleeper", sleeper)
    return service


@pytest.fixture()
def worker(svc: JobService) -> DurableWorker:
    w = svc.worker
    assert w is not None
    return w


# ── Synthetic media fixtures ─────────────────────────────────────────────────


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)


def _make_media(path: Path, *, audio_codec: list[str], duration: float = 2.0) -> Path:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
        *audio_codec,
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"fixture generation failed: {result.stderr[-300:]}"
    return path


@pytest.fixture()
def aac_source(tmp_path: Path) -> Path:
    return _make_media(tmp_path / "src_aac.mp4", audio_codec=["-c:a", "aac", "-b:a", "64k"])


@pytest.fixture()
def no_audio_source(tmp_path: Path) -> Path:
    return _make_media(tmp_path / "src_noaudio.mp4", audio_codec=["-an"])


# ── Import / attach / recheck helpers ───────────────────────────────────────


def _import_source(
    session_factory,
    worker: DurableWorker,
    ws: Workspace,
    video_item: VideoItem,
    source: Path,
    managed_root: Path,
) -> tuple[str, str]:
    """Run the approved S05-T02 import; returns (job_id, source_artifact_id)."""
    result = submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_path=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        generation="1",
        managed_root=managed_root,
        title=source.name,
    )
    assert worker.run_once() == 1
    with session_factory() as s:
        art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item.id,
                ArtifactOwner.purpose == video_import.ARTIFACT_PURPOSE_SOURCE,
            )
        )
    assert art_id is not None, "import did not link a source artifact"
    return result.job_id, str(art_id)


def _submit_attach(session_factory, ws: Workspace, video_item: VideoItem, managed_root: Path):
    return submit_attach_original_audio(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        generation="1",
        managed_root=managed_root,
    )


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _recheck_jobs(session_factory, *, ws_id: str, video_item_id: str) -> list[Any]:
    with session_factory() as s:
        return [
            j
            for j in JobRepository(s).list_jobs(
                ws_id, owner_type="video_item", owner_id=video_item_id, limit=50
            )
            if j.job_type == JOB_TYPE_RUN_QC_CHECKS
        ]


def _attach_jobs(session_factory, *, ws_id: str, video_item_id: str) -> list[Any]:
    with session_factory() as s:
        return [
            j
            for j in JobRepository(s).list_jobs(
                ws_id, owner_type="video_item", owner_id=video_item_id, limit=50
            )
            if j.job_type == JOB_TYPE_ATTACH_ORIGINAL_AUDIO
        ]


def _attach_attempt_result(session_factory, job_id: str) -> dict[str, Any] | None:
    with session_factory() as s:
        repo = JobRepository(s)
        for attempt in repo.list_attempts(job_id, limit=20):
            if attempt.error is None and isinstance(attempt.result, dict):
                return attempt.result
    return None


def _audio_artifact(session_factory, video_item_id: str) -> Artifact | None:
    with session_factory() as s:
        rows = list(
            s.scalars(
                select(Artifact)
                .join(ArtifactOwner, ArtifactOwner.artifact_id == Artifact.id)
                .where(
                    ArtifactOwner.owner_type == "video_item",
                    ArtifactOwner.owner_id == video_item_id,
                    ArtifactOwner.purpose == "original_audio",
                )
            ).all()
        )
    assert len(rows) <= 1, f"expected at most one original-audio artifact, got {len(rows)}"
    return rows[0] if rows else None


def _force_replay(session_factory, job_id: str) -> None:
    """Reset a terminal job+step to queued/pending and drop lease + attempt
    rows so run_once re-executes the SAME job row (mirror attach suite)."""
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(job_id)[0].id)
        step_row.state = "pending"
        step_row.attempt = 0
        step_row.error_json = None
        step_row.started_at = None
        step_row.finished_at = None
        job_row = s.get(Job, job_id)
        job_row.state = "queued"
        job_row.attempt = 0
        job_row.error_json = None
        job_row.started_at = None
        job_row.finished_at = None
        lease = s.get(JobLease, job_id)
        if lease is not None:
            s.delete(lease)
        for attempt in s.scalars(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        ):
            s.delete(attempt)
        s.commit()


def _force_job_failed(session_factory, job_id: str) -> None:
    """Drive a completed job to terminal FAILED through the real state
    machine: raw reset to queued (test seam), then queued→running→failed
    via the guarded transitions."""
    with session_factory() as s:
        repo = JobRepository(s)
        row = s.get(Job, job_id)
        assert row is not None
        row.state = "queued"
        s.commit()
        r1 = repo.transition_job(
            job_id, "running", actor="system", expected_revision=row.revision
        )
        repo.transition_job(
            job_id, "failed", actor="system", expected_revision=r1.revision
        )
        s.commit()


def _delete_job_rows(session_factory, job_id: str) -> None:
    """Remove a QUEUED job's rows entirely (simulates a missing recheck run:
    the run was never created for an earlier-completed attach)."""
    from app.persistence.models import JobEvent

    with session_factory() as s:
        repo = JobRepository(s)
        for step in repo.list_steps(job_id):
            s.delete(s.get(JobStep, step.id))
        for event in s.scalars(select(JobEvent).where(JobEvent.job_id == job_id)):
            s.delete(event)
        lease = s.get(JobLease, job_id)
        if lease is not None:
            s.delete(lease)
        for attempt in s.scalars(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        ):
            s.delete(attempt)
        s.delete(s.get(Job, job_id))
        s.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Worker-level: verified-completion → A/V recheck trigger (C4-F3 #1/#2/#3/#5)
# ═══════════════════════════════════════════════════════════════════════════


def test_01_no_recheck_before_completion_recheck_after_verified_completion(
    session_factory, svc, worker, ws, video_item, managed_root, aac_source
) -> None:
    """C4-F3 #2 + #1: submission happens BEFORE the attach step completes and
    enqueues nothing; only AFTER the verified output-validation completion
    (published bytes OK) does the A/V recheck exist."""
    _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    assert result.reused is False

    # Submission BEFORE completion: no recheck run may exist yet.
    assert _recheck_jobs(
        session_factory, ws_id=ws.id, video_item_id=video_item.id
    ) == [], "recheck enqueued before the attach step completed (C4-F3 #2)"

    assert worker.run_once() == 1  # the attach job executes and completes
    assert _job_state(session_factory, result.job_id) == "completed"
    assert _audio_artifact(session_factory, video_item.id) is not None

    # After verified completion exactly ONE audio-scope recheck run exists.
    rechecks = _recheck_jobs(
        session_factory, ws_id=ws.id, video_item_id=video_item.id
    )
    assert len(rechecks) == 1, f"expected exactly one recheck run, got {len(rechecks)}"
    assert rechecks[0].input_manifest.get("scope") == SCOPE_AUDIO
    # The recheck is BACKGROUND work: claimed only after higher-priority
    # user jobs (never preempting a later import/attach — the T01 suite
    # contract of ``run_once() == 1`` per submitted job stays intact).
    assert rechecks[0].priority < 50, "recheck run must not preempt user jobs"
    detector_args = rechecks[0].input_manifest.get("detector_args") or {}
    assert set(detector_args) == {"audio_missing", "av_sync_drift"}
    for name in ("audio_missing", "av_sync_drift"):
        args = detector_args[name]
        assert isinstance(args.get("checkpoint"), dict)
        assert args.get("error") is None
    # The envelope is the VERIFIED attach result — published outcome carried.
    published = detector_args["audio_missing"].get("published") or {}
    assert published.get("no_audio_present") is False
    assert isinstance(published.get("final_rel"), str)


def test_02_terminal_no_audio_present_triggers_recheck(
    session_factory, svc, worker, ws, video_item, managed_root, no_audio_source
) -> None:
    """C4-F3 #1 terminal branch: NO_AUDIO_PRESENT completion (zero published
    bytes) still triggers the A/V recheck with the terminal envelope."""
    _import_source(
        session_factory, worker, ws, video_item, no_audio_source, managed_root
    )
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() == 1
    assert _job_state(session_factory, result.job_id) == "completed"
    assert _audio_artifact(session_factory, video_item.id) is None

    rechecks = _recheck_jobs(
        session_factory, ws_id=ws.id, video_item_id=video_item.id
    )
    assert len(rechecks) == 1, f"expected exactly one recheck run, got {len(rechecks)}"
    args = (rechecks[0].input_manifest.get("detector_args") or {}).get("audio_missing") or {}
    published = args.get("published") or {}
    assert published.get("no_audio_present") is True


def test_03_retry_validator_no_duplicate_run_and_active_conflict_covered(
    session_factory, svc, worker, ws, video_item, managed_root, aac_source
) -> None:
    """C4-F3 #3 + #5: the recheck idempotency key binds evidence-fingerprint +
    policy hash + scope — an ACTIVE duplicate is covered (no second run), a
    COMPLETED duplicate is reused, and a retried validator never creates a
    duplicate run.  A terminal FAILED recheck blocks fail-closed instead of
    claiming coverage."""
    _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() == 1  # attach completes; recheck enqueued (queued)
    assert _job_state(session_factory, result.job_id) == "completed"
    rechecks = _recheck_jobs(
        session_factory, ws_id=ws.id, video_item_id=video_item.id
    )
    assert len(rechecks) == 1
    recheck_job_id = rechecks[0].id

    evidence = _attach_attempt_result(session_factory, result.job_id)
    assert evidence is not None

    # ACTIVE duplicate: the run is still queued → covered, NOT duplicated.
    outcome = ensure_av_recheck(
        svc.session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        attach_result=evidence,
    )
    assert outcome.active is True
    assert outcome.reused is False
    assert outcome.job_id == recheck_job_id
    assert len(
        _recheck_jobs(session_factory, ws_id=ws.id, video_item_id=video_item.id)
    ) == 1

    # Let the recheck run execute and complete.
    assert worker.run_once() == 1
    assert _job_state(session_factory, recheck_job_id) == "completed"

    # COMPLETED duplicate → reused, still exactly one run.
    outcome = ensure_av_recheck(
        svc.session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        attach_result=evidence,
    )
    assert outcome.reused is True
    assert outcome.active is False
    assert outcome.job_id == recheck_job_id

    # Retried validator (replay of the completed attach job) → no duplicate.
    _force_replay(session_factory, result.job_id)
    assert worker.run_once() == 1
    assert _job_state(session_factory, result.job_id) == "completed"
    assert len(
        _recheck_jobs(session_factory, ws_id=ws.id, video_item_id=video_item.id)
    ) == 1

    # A TERMINAL FAILED recheck can never be silently covered — fail closed.
    _force_job_failed(session_factory, recheck_job_id)
    assert _job_state(session_factory, recheck_job_id) == "failed"
    with pytest.raises(AvRecheckEnqueueError) as excinfo:
        ensure_av_recheck(
            svc.session_factory,
            workspace_id=ws.id,
            project_id=video_item.project_id,
            video_item_id=video_item.id,
            attach_result=evidence,
        )
    assert excinfo.value.code == "RECHECK_TERMINAL_BLOCKED"
    assert len(
        _recheck_jobs(session_factory, ws_id=ws.id, video_item_id=video_item.id)
    ) == 1


def test_04_enqueue_failure_fail_closed_attach_not_completed(
    session_factory, svc, worker, ws, video_item, managed_root, aac_source, monkeypatch
) -> None:
    """C4-F3 #1/#3: an enqueue error makes the validator raise → the attach
    step NEVER reaches completed and no recheck was created (fail-closed)."""
    _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    result = _submit_attach(session_factory, ws, video_item, managed_root)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated recheck enqueue outage")

    monkeypatch.setattr("app.services.qc_av_recheck.ensure_av_recheck", _boom)
    assert worker.run_once() == 1
    assert _job_state(session_factory, result.job_id) == "failed", (
        "attach step must NOT complete when the recheck enqueue fails"
    )
    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert (job.error or {}).get("error_code") == "VALIDATION_FAILED"
    assert _recheck_jobs(
        session_factory, ws_id=ws.id, video_item_id=video_item.id
    ) == []


def test_05_attach_failure_no_recheck(
    session_factory, svc, worker, ws, video_item, managed_root, aac_source
) -> None:
    """C4-F3 #6: an attach failure (source lost at run time) never enqueues
    the A/V recheck."""
    _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    # Source byte authority is re-validated at run time: remove the managed
    # source file so the handler fails closed.
    with session_factory() as s:
        src_art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item.id,
                ArtifactOwner.purpose == video_import.ARTIFACT_PURPOSE_SOURCE,
            )
        )
        art = s.get(Artifact, src_art_id)
        rel = art.relative_path if art is not None else None
    assert rel is not None
    from app.persistence.artifacts import ManagedRoot

    target = ManagedRoot(managed_root).resolve(rel)
    target.unlink()

    assert worker.run_once() == 1
    assert _job_state(session_factory, result.job_id) == "failed"
    assert _recheck_jobs(
        session_factory, ws_id=ws.id, video_item_id=video_item.id
    ) == []


def test_06_no_direct_qcitem_resolution_and_durable_worker_untouched() -> None:
    """C4-F3 #7 + acceptance 5: no code path resolves a QCItem directly and
    the durable worker is untouched in the diff."""
    import subprocess as _sp

    new_sources = [
        PROJECT_ROOT / "app/services/qc_av_recheck.py",
        PROJECT_ROOT / "app/api/routes/original_audio_action.py",
    ]
    for source in new_sources:
        text = source.read_text(encoding="utf-8")
        assert "QCItem" not in text and "qc_items" not in text and "QcItem" not in text, (
            f"{source.name} must never resolve a QCItem directly"
        )
    handler = PROJECT_ROOT / "app/workflow/original_audio_handler.py"
    raw = handler.read_text(encoding="utf-8")
    # The handler's new hook may only reference the recheck service.
    assert "qc_items" not in raw and "QCItemRepository" not in raw
    assert "qc_av_recheck" in raw

    proc = _sp.run(
        ["git", "diff", "--exit-code", "--", "app/workflow/durable_worker.py",
         "app/services/original_audio_remux.py"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        "durable_worker.py / original_audio_remux.py must be untouched:\n"
        + proc.stdout
        + proc.stderr
    )


# ═══════════════════════════════════════════════════════════════════════════
# Route-level: server-owned original-audio attach action (Decision H)
# ═══════════════════════════════════════════════════════════════════════════

_URL = f"/api/v2/projects/{P1}/original-audio-attach"


def _seed_project_video(session: Any, *, ws: str, pid: str, vid: str) -> None:
    from sqlalchemy import text as _text

    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT04C','','active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": pid, "w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidT04C',0,'imported')"
        ),
        {"v": vid, "p": pid},
    )
    session.commit()


def _route_import(client: TestClient, source: Path, *, pid: str, vid: str) -> str:
    """Real import through the patched deps JobService; returns source
    artifact id.  Requires real media (ffmpeg)."""
    from app.api import deps

    svc = deps.get_job_service()
    factory = svc.session_factory
    worker = svc.worker
    assert factory is not None and worker is not None
    svc.managed_root.mkdir(parents=True, exist_ok=True)
    with factory() as s:
        ws_row = s.get(Workspace, WS)
        assert ws_row is not None
        ws_id = ws_row.id
    submit_import(
        factory,
        workspace_id=ws_id,
        project_id=pid,
        video_item_id=vid,
        source_path=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        generation="1",
        managed_root=svc.managed_root,
        title=source.name,
    )
    assert worker.run_once() == 1
    with factory() as s:
        art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == vid,
                ArtifactOwner.purpose == video_import.ARTIFACT_PURPOSE_SOURCE,
            )
        )
    assert art_id is not None
    return str(art_id)


def test_07_payload_with_path_handler_provider_rejected_422(client: TestClient) -> None:
    """Decision H + acceptance 1: the client payload can never carry a
    filesystem path, handler or provider — extra fields are forbidden."""
    for body in (
        {"video_item_id": V1, "path": "/tmp/source.mp4"},
        {"video_item_id": V1, "source_path": "C:/tmp/source.mp4"},
        {"video_item_id": V1, "handler": "original_audio_handler"},
        {"video_item_id": V1, "provider": "custom"},
        {"video_item_id": V1, "source_artifact_id": "client-chosen"},
    ):
        resp = client.post(_URL, json=body)
        assert resp.status_code == 422, f"body {body} → {resp.status_code}"


def test_08_route_fresh_submit_then_completion_triggers_recheck(
    client: TestClient, tmp_path: Path, aac_source: Path
) -> None:
    """Route end-to-end (Decision H): a fresh server-owned POST queues the
    durable attach job (202, no early recheck), the worker's verified
    completion enqueues exactly one recheck, and a later reuse resubmit
    returns the SAME attach job plus the completed recheck coverage."""
    from app.api import deps

    qc_session = deps.get_job_service().session_factory()
    try:
        _seed_project_video(qc_session, ws=WS, pid=P1, vid=V1)
    finally:
        qc_session.close()

    source_artifact_id = _route_import(client, aac_source, pid=P1, vid=V1)

    resp = client.post(_URL, json={"video_item_id": V1})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["reused"] is False
    assert body["state"] == "queued"
    assert body["job_id"]
    assert body["recheck_job_id"] is None, "no recheck before completion (C4-F3 #2)"
    attach_job_id = body["job_id"]

    # No recheck run exists before the attach step completes.
    svc = deps.get_job_service()
    assert _recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V1) == []

    # Verified completion (real worker) → exactly one recheck run.
    assert svc.worker.run_once() == 1
    assert _job_state(svc.session_factory, attach_job_id) == "completed"
    rechecks = _recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V1)
    assert len(rechecks) == 1

    # The attach job manifest resolved the source from the VideoItem's
    # source_artifact_id authority — no client-supplied path anywhere.
    with svc.session_factory() as s:
        job = JobRepository(s).get_job(attach_job_id)
        manifest = job.input_manifest
        assert manifest.get("source_artifact_id") == source_artifact_id
        for key in ("path", "source_path"):
            assert key not in manifest

    # Let the recheck complete, then resubmit: reused + recheck coverage.
    assert svc.worker.run_once() == 1
    assert _job_state(svc.session_factory, rechecks[0].id) == "completed"
    resp2 = client.post(_URL, json={"video_item_id": V1})
    assert resp2.status_code == 202, resp2.text
    body2 = resp2.json()
    assert body2["reused"] is True
    assert body2["state"] == "reused"
    assert body2["job_id"] == attach_job_id
    assert body2["recheck_job_id"] == rechecks[0].id
    assert body2["recheck_state"] == "reused"
    assert len(_recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V1)) == 1


def test_09_active_conflict_fail_closed_409_and_no_early_recheck(
    client: TestClient, tmp_path: Path, aac_source: Path
) -> None:
    """C4-F3 #4/#5: an ACTIVE duplicate attach fails closed with 409
    (IdempotencyKeyInUse semantics) and the conflict path enqueues nothing."""
    from app.api import deps

    qc_session = deps.get_job_service().session_factory()
    try:
        _seed_project_video(qc_session, ws=WS, pid=P1, vid=V2)
    finally:
        qc_session.close()
    _route_import(client, aac_source, pid=P1, vid=V2)

    resp = client.post(_URL, json={"video_item_id": V2})
    assert resp.status_code == 202, resp.text
    resp2 = client.post(_URL, json={"video_item_id": V2})
    assert resp2.status_code == 409, resp2.text
    assert "IdempotencyKeyInUse" in resp2.json()["detail"]

    svc = deps.get_job_service()
    assert _recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V2) == [], (
        "the conflict path must never enqueue an early recheck"
    )


def test_10_reused_completed_backfills_missing_recheck(
    client: TestClient, tmp_path: Path, aac_source: Path
) -> None:
    """C4-F3 #4/acceptance 4: a route that receives a COMPLETED attach job
    whose recheck run is MISSING backfills it through ensure_av_recheck
    (idempotent — repeated reuse resubmits stay on the same backfilled run)."""
    from app.api import deps

    qc_session = deps.get_job_service().session_factory()
    try:
        _seed_project_video(qc_session, ws=WS, pid=P1, vid=V2)
    finally:
        qc_session.close()
    _route_import(client, aac_source, pid=P1, vid=V2)
    svc = deps.get_job_service()

    resp = client.post(_URL, json={"video_item_id": V2})
    assert resp.status_code == 202
    attach_job_id = resp.json()["job_id"]
    assert svc.worker.run_once() == 1  # attach completes; recheck enqueued
    rechecks = _recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V2)
    assert len(rechecks) == 1
    # Simulate the missing-run condition (e.g. attach completed before the
    # recheck trigger existed): the queued recheck row is gone.
    _delete_job_rows(svc.session_factory, rechecks[0].id)
    assert _recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V2) == []

    # Reused resubmit → the missing recheck run is BACKFILLED.
    resp2 = client.post(_URL, json={"video_item_id": V2})
    assert resp2.status_code == 202, resp2.text
    body2 = resp2.json()
    assert body2["reused"] is True
    assert body2["job_id"] == attach_job_id
    assert body2["recheck_job_id"] is not None
    assert body2["recheck_state"] in ("queued", "active")
    backfilled = _recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V2)
    assert len(backfilled) == 1
    assert backfilled[0].id == body2["recheck_job_id"]

    # A further reuse stays idempotent on the SAME backfilled run.
    resp3 = client.post(_URL, json={"video_item_id": V2})
    assert resp3.status_code == 202
    assert resp3.json()["recheck_job_id"] == body2["recheck_job_id"]
    assert len(_recheck_jobs(svc.session_factory, ws_id=WS, video_item_id=V2)) == 1


def test_11_workspace_mismatch_fail_closed(client: TestClient) -> None:
    """A video_item that does not belong to the route's project/workspace is
    refused with zero side effects (no job rows)."""
    from app.api import deps

    other_ws = "ws-other-t04c"
    qc_session = deps.get_job_service().session_factory()
    try:
        _seed_project_video(qc_session, ws=other_ws, pid=P2, vid=V1)
    finally:
        qc_session.close()

    resp = client.post(_URL, json={"video_item_id": V1})
    assert resp.status_code in (404, 409), resp.text
    svc = deps.get_job_service()
    with svc.session_factory() as s:
        for j in JobRepository(s).list_jobs(WS, limit=50):
            assert j.job_type != JOB_TYPE_ATTACH_ORIGINAL_AUDIO
        for j in JobRepository(s).list_jobs(other_ws, limit=50):
            assert j.job_type != JOB_TYPE_ATTACH_ORIGINAL_AUDIO


def test_12_router_shape_server_owned_and_include_once() -> None:
    """Decision H shape: exactly ONE server-owned POST, zero other mutators,
    the request schema names ONLY video_item_id, app.py includes the router
    exactly once, and the route source never reads a client path."""
    import re

    route_source = (
        PROJECT_ROOT / "app/api/routes/original_audio_action.py"
    ).read_text(encoding="utf-8")
    assert len(re.findall(r"@router\.post\b", route_source)) == 1
    assert re.findall(r"@router\.(put|patch|delete)\b", route_source) == []
    for forbidden in ("path", "handler", "provider"):
        assert not re.search(
            rf"^\s*{forbidden}\s*:", route_source, re.MULTILINE
        ), f"route module must not expose {forbidden!r} as a request field"

    app_source = (PROJECT_ROOT / "app/api/app.py").read_text(encoding="utf-8")
    assert (
        len(re.findall(r"include_router\(original_audio_action\.router\)", app_source))
        == 1
    )
    assert "original_audio_action" in app_source
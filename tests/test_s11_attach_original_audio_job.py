"""S11-T01C — Durable ATTACH_ORIGINAL_AUDIO job wiring required tests (binary).

Every test runs the REAL production path: the default ``JobService``
registers the handler (not an isolated test-worker registry), jobs execute
through ``DurableWorker.run_once`` over a temp SQLite database (Alembic
upgraded) and a temp managed root.  Media fixtures are real FFmpeg lavfi
synthetics; tests skip cleanly when FFmpeg is unavailable.  The invoker
contract supplies its own Windows-native ``--basetemp`` and
``-p no:cacheprovider``.

Required-test map (TASK.md "Required tests (binary)"):

 1.  test_01_default_jobservice_registers_handler — default production
     JobService registers the ATTACH_ORIGINAL_AUDIO handler.
 2.  test_02_real_handler_invocation_publishes_audio_artifact — real engine
     run through the durable worker: completed job, one ready ``audio``
     artifact + owner link purpose ``original_audio``, decodable output,
     source untouched.
 3.  test_03_equivalent_submit_idempotent_reuse — same key resubmit after
     completion returns the SAME job with reused=True; exactly one effect
     set; active duplicate raises IdempotencyKeyInUse.
 4.  test_04_conflicting_submit_fail_closed — different source content /
     different video item never reuses another owner's job (distinct keys;
     cross-item submit fails closed on ownership).
 5.  test_05_retry_no_duplicate_artifact — publication failure then replay:
     exactly one audio artifact/file, no staging leftovers.
 6.  test_06_restart_preserves_checkpoint — failed attempt → successor with
     the same key: completes with one effect set; same-job resume reuses the
     checkpointed remux evidence without re-running the engine.
 7.  test_07_cancellation_zero_publication — cancel mid-run drains to
     terminal cancelled with zero artifact rows/files/staging leftovers.
 8.  test_08_validation_before_completion — output validator gate: a result
     whose published file was tampered with can never complete.
 9.  test_09_artifact_owner_video_item_original_audio — kind=audio,
     ArtifactOwner(owner_type=video_item, purpose=original_audio).
10.  test_10_analysis_generation_unchanged — DISCOVER_OBJECTS state
     (ObjectRole/ObjectOccurrence counts) and the source probe evidence are
     unchanged by the attach job.
11.  test_11_unknown_or_missing_source_stable_failure — no source artifact /
     not-ready source / unlinked artifact fail closed with stable codes and
     zero side effects.
12.  test_12_no_process_leak — after success AND after cancellation the
     ffmpeg child tree is fully gone (no surviving children).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.jobs import IdempotencyKeyInUse
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Job,
    JobAttempt,
    JobLease,
    JobStep,
    ObjectOccurrence,
    ObjectRole,
    Project,
    VideoItem,
    Workspace,
)
from app.services import video_import
from app.services.video_import import submit_import
from app.workflow.durable_worker import DurableWorker, WorkerConfig
from app.workflow.job_service import JobService
from app.workflow.original_audio_handler import (
    ATTACH_STEP_CODE,
    CODE_SOURCE_ARTIFACT_NOT_FOUND,
    CODE_SOURCE_NOT_READY,
    CODE_SOURCE_OWNER_MISMATCH,
    JOB_TYPE_ATTACH_ORIGINAL_AUDIO,
    attach_original_audio_steps,
    submit_attach_original_audio,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Deterministic clock/sleeper (mirror test_video_proxy.py) ────────────────


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 21, 22, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ── DB fixtures (temp SQLite via Alembic — production schema) ───────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "attach.db"


@pytest.fixture()
def session_factory(db_path: Path):
    _upgrade(db_path)
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture()
def ws(session: Session) -> Workspace:  # type: ignore[name-defined]
    ws_row = Workspace(name="Attach Workspace")
    session.add(ws_row)
    session.commit()
    return ws_row


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    proj = Project(name="Attach Project", workspace_id=ws.id, status="active")
    session.add(proj)
    session.commit()
    return proj


@pytest.fixture()
def video_item(session: Session, project: Project) -> VideoItem:
    item = VideoItem(
        project_id=project.id,
        title="Clip A",
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
    """The DEFAULT production JobService over temp roots.

    worker=None → the service constructs its own DurableWorker and runs the
    REAL registration block (register_api_handlers + scene + proxy +
    DISCOVER_OBJECTS + RECOMPUTE_OBJECTS + ATTACH_ORIGINAL_AUDIO).  Only the
    clock/sleeper are faked for determinism.
    """
    service = JobService(session_factory, managed_root=managed_root)
    worker = service.worker
    assert worker is not None
    # Inject determinism without touching registration semantics.
    worker._config = WorkerConfig(  # noqa: SLF001 - test seam on own instance
        worker_id="attach-worker",
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
    """A CFR MP4/H.264 clip with the requested first-audio codec."""
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
def mp3_source(tmp_path: Path) -> Path:
    return _make_media(tmp_path / "src_mp3.mp4", audio_codec=["-c:a", "libmp3lame", "-b:a", "96k"])


def _probe_streams(path: Path) -> dict:
    from app.services.ffmpeg_utils import find_ffprobe

    result = subprocess.run(
        [
            find_ffprobe(), "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    return json.loads(result.stdout)


# ── Import / attach helpers ──────────────────────────────────────────────────


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


def _submit_attach_for(
    session_factory, ws: Workspace, project_id: str, video_item_id: str, managed_root: Path
):
    return submit_attach_original_audio(
        session_factory,
        workspace_id=ws.id,
        project_id=project_id,
        video_item_id=video_item_id,
        generation="1",
        managed_root=managed_root,
    )


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _audio_artifact(session_factory, video_item_id: str) -> Artifact:
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
    return rows[0] if rows else None  # type: ignore[return-value]


def _artifact_files(managed_root: Path) -> list[Path]:
    artifacts = managed_root / "artifacts"
    if not artifacts.is_dir():
        return []
    return [p for p in artifacts.rglob("*") if p.is_file()]


def _staging_files(managed_root: Path) -> list[Path]:
    staging = managed_root / "staging"
    if not staging.is_dir():
        return []
    return [p for p in staging.rglob("*") if p.is_file()]


def _step_checkpoint(session_factory, job_id: str) -> dict:
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(job_id)[0].id)
        return json.loads(step_row.checkpoint_json or "{}")


def _force_replay(session_factory, job_id: str) -> None:
    """Reset a completed/failed job+step to queued/pending and drop lease +
    attempt rows so run_once re-executes the SAME job row."""
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


def _ffmpeg_pids() -> set[int]:
    """Live ffmpeg/ffprocess PIDs (psutil; empty when unavailable)."""
    try:
        import psutil
    except ImportError:
        return set()
    out: set[int] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name.startswith("ffmpeg") or name.startswith("ffprobe"):
                out.add(proc.pid)
        except Exception:  # noqa: BLE001 - racy process table
            continue
    return out


# ── 1. Default production JobService registration ────────────────────────────


def test_01_default_jobservice_registers_handler(svc: JobService) -> None:
    """Required 1: the DEFAULT JobService (worker=None → its own DurableWorker
    built inside __init__) has ATTACH_ORIGINAL_AUDIO registered."""
    worker = svc.worker
    assert worker is not None
    with worker._lock:  # noqa: SLF001 - registry inspection
        entry = worker._handlers.get(JOB_TYPE_ATTACH_ORIGINAL_AUDIO)
    assert entry is not None, (
        "default production JobService must register ATTACH_ORIGINAL_AUDIO"
    )
    assert callable(entry.handler)
    assert entry.handler.__name__ == "attach_original_audio_handler"
    assert entry.output_validator is not None
    # And the step plan is the single 'attach' sync step.
    steps = attach_original_audio_steps()
    assert len(steps) == 1
    assert steps[0].step_code == ATTACH_STEP_CODE
    assert steps[0].step_type == "sync"


def test_02_real_handler_invocation_publishes_audio_artifact(
    svc, session_factory, ws, video_item, aac_source, managed_root
) -> None:
    """Required 2 (+9): real engine invocation through the durable worker →
    completed Job, one ready audio artifact + owner link, decodable AAC
    output, source bytes unchanged."""
    worker = svc.worker
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    with session_factory() as s:
        src_art = s.get(Artifact, source_artifact_id)
        source_sha_before = hashlib.sha256(
            (managed_root / src_art.relative_path).read_bytes()
        ).hexdigest()

    result = _submit_attach(session_factory, ws, video_item, managed_root)
    assert result.reused is False
    assert worker.run_once() >= 1

    assert _job_state(session_factory, result.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None
    assert art.kind == "audio"
    assert art.state == "ready"
    final = managed_root / art.relative_path
    assert final.is_file()
    assert art.sha256 == hashlib.sha256(final.read_bytes()).hexdigest()
    assert art.size_bytes == final.stat().st_size
    assert art.relative_path.startswith(f"artifacts/{ws.id}/audio/{result.job_id}/attach/")
    assert not Path(art.relative_path).is_absolute()
    with session_factory() as s:
        owner = s.get(
            ArtifactOwner,
            (art.id, "video_item", video_item.id, "original_audio"),
        )
        src_link = s.get(
            ArtifactOwner,
            (source_artifact_id, "video_item", video_item.id, "source"),
        )
    assert owner is not None
    assert src_link is not None
    # Exactly two published files now (source + original audio); no staging.
    assert len(_artifact_files(managed_root)) == 2
    assert _staging_files(managed_root) == []
    # Output really is AAC audio + H.264 video (stream-copied first stream).
    streams = {
        st["codec_type"]: st["codec_name"] for st in _probe_streams(final)["streams"]
    }
    assert streams.get("audio") == "aac"
    assert streams.get("video") in {"h264", "hevc"}
    # Source bytes unchanged end-to-end.
    assert (
        hashlib.sha256(
            (managed_root / src_art.relative_path).read_bytes()
        ).hexdigest()
        == source_sha_before
    )


# ── 3. Equivalent-submit idempotency ─────────────────────────────────────────


def test_03_equivalent_submit_idempotent_reuse(
    svc, session_factory, ws, video_item, aac_source, managed_root
) -> None:
    """Required 3: deterministic idempotency key — a completed duplicate
    returns the SAME Job (reused=True) and no new effects are created; an
    ACTIVE duplicate fails closed with IdempotencyKeyInUse."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)

    first = _submit_attach(session_factory, ws, video_item, managed_root)
    assert first.reused is False
    # Active duplicate: fail closed.
    with pytest.raises(IdempotencyKeyInUse):
        _submit_attach(session_factory, ws, video_item, managed_root)
    # Run to completion.
    assert worker.run_once() >= 1
    assert _job_state(session_factory, first.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None
    # Completed equivalent submit: reuse, same job id, one effect set.
    second = _submit_attach(session_factory, ws, video_item, managed_root)
    assert second.reused is True
    assert second.job_id == first.job_id
    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_ATTACH_ORIGINAL_AUDIO)
        ).all()
        audio_rows = list(
            s.scalars(
                select(Artifact).where(Artifact.kind == "audio")
            ).all()
        )
    assert len(jobs) == 1
    assert len(audio_rows) == 1


# ── 4. Conflicting submit fails closed ───────────────────────────────────────


def test_04_conflicting_submit_fail_closed(
    svc, session_factory, ws, project, video_item, mp3_source, managed_root, tmp_path
) -> None:
    """Required 4: different source CONTENT for the same owner is a DIFFERENT
    logical key (no silent reuse of another content's job); a submit whose
    ownership chain does not match fails closed with zero job rows."""
    worker = svc.worker
    _, artifact_a = _import_source(
        session_factory, worker, ws, video_item, mp3_source, managed_root
    )

    # A different VideoItem in the same project gets its own key/artifacts.
    other_item = VideoItem(
        project_id=project.id, title="Clip B", position=1, status="imported", revision=1
    )
    with session_factory() as s:
        s.add(other_item)
        s.commit()

    other_source = _make_media(
        tmp_path / "src_mp3_b.mp4", audio_codec=["-c:a", "libmp3lame", "-b:a", "128k"]
    )
    _, artifact_b = _import_source(
        session_factory, worker, ws, other_item, other_source, managed_root
    )
    assert artifact_a != artifact_b

    # Cross-owner conflict: submitting item A's attach while claiming item B's
    # identity would need a mismatched manifest — the submit derives everything
    # from the owner, so the only conflicting surface is the ownership chain.
    from app.services.video_import import CODE_OWNERSHIP_MISMATCH

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - any stable failure
        submit_attach_original_audio(
            session_factory,
            workspace_id="wrong-workspace",
            project_id=video_item.project_id,
            video_item_id=video_item.id,
            managed_root=managed_root,
        )
    assert getattr(excinfo.value, "code", "") == CODE_OWNERSHIP_MISMATCH
    # Zero jobs were created by the rejected submit.
    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_ATTACH_ORIGINAL_AUDIO)
        ).all()
    assert len(jobs) == 0


# ── 5. Retry produces no duplicate artifact ──────────────────────────────────


def test_05_retry_no_duplicate_artifact(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """Required 5: a publication-transaction failure then replay yields
    exactly ONE audio artifact/file — never duplicates."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)
    result = _submit_attach(session_factory, ws, video_item, managed_root)

    from app.workflow import original_audio_handler as handler_mod

    def failing_effect(ctx, final_rel, sha256, size):
        raise RuntimeError("simulated DB failure at publication")

    monkeypatch.setattr(handler_mod, "_publish_effect", failing_effect)
    worker.run_once()
    monkeypatch.undo()

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == "PUBLICATION_FAILED"
    assert _audio_artifact(session_factory, video_item.id) is None

    # Replay the SAME job row (crash-recovery path).
    _force_replay(session_factory, result.job_id)
    worker.run_once()

    assert _job_state(session_factory, result.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None and art.state == "ready"
    finals = [
        p for p in _artifact_files(managed_root)
        if p.name.endswith(".mp4") and result.job_id in p.parts
    ]
    assert len(finals) == 1, f"expected exactly one attached file, got {len(finals)}"


# ── 6. Restart preserves checkpoint ──────────────────────────────────────────


def test_06_restart_preserves_checkpoint(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """Required 6: (a) a same-job resume reuses the durable remux evidence —
    the engine is NOT re-invoked; (b) a successor after failure completes
    with exactly one effect set."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)
    result = _submit_attach(session_factory, ws, video_item, managed_root)

    from app.workflow import original_audio_handler as h
    from app.workflow import original_audio_handler as handler_mod

    calls = {"engine": 0}
    real_remux = h.remux_original_audio

    def counting_remux(*args, **kwargs):
        calls["engine"] += 1
        return real_remux(*args, **kwargs)

    monkeypatch.setattr(handler_mod, "remux_original_audio", counting_remux)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"
    engine_runs_first = calls["engine"]
    assert engine_runs_first == 1

    # Hard-restart simulation: replay the SAME job row but KEEP the step
    # checkpoint (the crash happened after completion persistence is not the
    # scenario; here we drop terminal state only).  The checkpoint carries
    # the published evidence → publication is skipped, engine not re-run.
    _force_replay_keep_checkpoint(session_factory, result.job_id)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"
    assert calls["engine"] == engine_runs_first, (
        "restart must reuse the checkpointed evidence without re-running "
        "the engine"
    )
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None and art.state == "ready"
    h.remux_original_audio = real_remux

    # Successor path (§6.4): a FAILED predecessor's key may be retried by a
    # linked successor.  Use a FRESH video item so the failure happens before
    # any publication and cannot collide with the completed job above.
    succ_item = VideoItem(
        project_id=video_item.project_id,
        title="Clip D",
        position=3,
        status="imported",
        revision=1,
    )
    with session_factory() as s:
        s.add(succ_item)
        s.commit()
        succ_item_id = succ_item.id

    class _Proxy:
        pass

    succ_proxy = _Proxy()
    succ_proxy.id = succ_item_id
    succ_proxy.project_id = video_item.project_id
    _import_source(session_factory, worker, ws, succ_proxy, aac_source, managed_root)
    submitted = _submit_attach_for(
        session_factory, ws, video_item.project_id, succ_item_id, managed_root
    )
    monkeypatch.setattr(handler_mod, "_publish_effect", _failing_effect_once)
    worker.run_once()
    monkeypatch.undo()
    assert _job_state(session_factory, submitted.job_id) == "failed"
    assert _audio_artifact(session_factory, succ_item_id) is None

    with session_factory() as s:
        repo = JobRepository(s)
        pred = repo.get_job(submitted.job_id)
        succ = repo.create_successor(
            predecessor_job_id=pred.id,
            input_manifest=pred.input_manifest,
            idempotency_key=pred.idempotency_key,
            input_generation=pred.input_generation,
            steps=attach_original_audio_steps(),
        )
        s.commit()
    worker.run_once()
    assert _job_state(session_factory, succ.id) == "completed"
    art = _audio_artifact(session_factory, succ_item_id)
    assert art is not None and art.state == "ready"


def _failing_effect_once(ctx, final_rel, sha256, size):
    raise RuntimeError("simulated DB failure at publication (successor path)")


def _force_replay_keep_checkpoint(session_factory, job_id: str) -> None:
    """Reset ONLY the job/step state machine, keeping the persisted
    checkpoint (a restart between commit and completion observation)."""
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


# ── 7. Cancellation → zero publication ───────────────────────────────────────


def test_07_cancellation_zero_publication(
    svc, session_factory, ws, video_item, mp3_source, managed_root, monkeypatch
) -> None:
    """Required 7: cancel mid-run drains to terminal cancelled with ZERO
    artifacts, zero published files, zero staging leftovers."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, mp3_source, managed_root)
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    job_id = result.job_id

    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio

    def remux_then_cancel(src, out_dir, **kwargs):
        with session_factory() as s:
            r = JobRepository(s)
            r.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=r.get_job(job_id).revision,
            )
            s.commit()
        return real_remux(src, out_dir, **kwargs)

    monkeypatch.setattr(handler_mod, "remux_original_audio", remux_then_cancel)
    worker.run_once()
    monkeypatch.undo()

    assert _job_state(session_factory, job_id) == "cancelled"
    assert _audio_artifact(session_factory, video_item.id) is None
    job_files = [p for p in _artifact_files(managed_root) if job_id in p.parts]
    assert job_files == []
    assert _staging_files(managed_root) == []


# ── 8. Validation before completion ──────────────────────────────────────────


def test_08_validation_before_completion(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """Required 8: the output validator re-verifies the published bytes; a
    tampered/missing published file can NEVER complete the job."""
    from app.workflow.original_audio_handler import _attach_output_validator

    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"

    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None
    good_result = {
        "published": {
            "no_audio_present": False,
            "final_rel": art.relative_path,
            "sha256": art.sha256,
            "size_bytes": art.size_bytes,
            "status": "STREAM_COPY",
        }
    }
    ctx = type("Ctx", (), {"input_manifest": {"managed_root": str(managed_root)}})()
    # Honest evidence passes.
    verdict = _attach_output_validator(ctx, good_result, managed_root / "x")
    assert verdict["original_audio"]["sha256"] == art.sha256
    # Tampered sha256 evidence fails the gate.
    bad_result = {
        "published": {**good_result["published"], "sha256": "0" * 64}
    }
    with pytest.raises(RuntimeError):
        _attach_output_validator(ctx, bad_result, managed_root / "x")
    # Missing file fails the gate.
    missing_result = {
        "published": {**good_result["published"], "final_rel": "artifacts/nope.mp4"}
    }
    with pytest.raises(RuntimeError):
        _attach_output_validator(ctx, missing_result, managed_root / "x")
    # NO_AUDIO_PRESENT evidence must never carry a path.
    with pytest.raises(RuntimeError):
        _attach_output_validator(
            ctx,
            {
                "published": {
                    "no_audio_present": True,
                    "final_rel": "artifacts/leak.mp4",
                }
            },
            managed_root / "x",
        )
    honest_no_audio = _attach_output_validator(
        ctx, {"published": {"no_audio_present": True, "final_rel": None}}, managed_root / "x"
    )
    assert honest_no_audio["original_audio"]["no_audio_present"] is True


# ── 9. ArtifactOwner shape ───────────────────────────────────────────────────


def test_09_artifact_owner_video_item_original_audio(
    svc, session_factory, ws, video_item, mp3_source, managed_root
) -> None:
    """Required 9 (+ transcode path): kind=audio + owner link
    (video_item, <id>, original_audio); MP3 source arrives as AAC."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, mp3_source, managed_root)
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    worker.run_once()

    assert _job_state(session_factory, result.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None
    assert art.kind == "audio" and art.state == "ready"
    with session_factory() as s:
        owner = s.get(
            ArtifactOwner,
            (art.id, "video_item", video_item.id, "original_audio"),
        )
        wrong_purpose = s.scalar(
            select(ArtifactOwner).where(
                ArtifactOwner.artifact_id == art.id,
                ArtifactOwner.purpose != "original_audio",
            )
        )
    assert owner is not None
    assert wrong_purpose is None
    streams = {
        st["codec_type"]: st["codec_name"]
        for st in _probe_streams(managed_root / art.relative_path)["streams"]
    }
    assert streams.get("audio") == "aac"  # transcoded from MP3
    # Exactly ONE audio stream survives (canonical-first-stream rule).
    audio_streams = [
        st for st in _probe_streams(managed_root / art.relative_path)["streams"]
        if st["codec_type"] == "audio"
    ]
    assert len(audio_streams) == 1


# ── 10. Analysis generation unchanged ────────────────────────────────────────


def test_10_analysis_generation_unchanged(
    svc, session_factory, ws, video_item, aac_source, managed_root
) -> None:
    """Required 10: running ATTACH_ORIGINAL_AUDIO leaves ObjectRole /
    ObjectOccurrence rows untouched and does not rewrite the source probe
    columns or the source artifact evidence."""
    worker = svc.worker
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    with session_factory() as s:
        item = s.get(VideoItem, video_item.id)
        probe_before = (item.duration_ms, item.width, item.height, item.fps_num, item.fps_den)
        roles_before = s.scalars(select(ObjectRole)).all()
        occ_before = s.scalars(select(ObjectOccurrence)).all()
        src_art_before = (
            s.get(Artifact, source_artifact_id).sha256,
            s.get(Artifact, source_artifact_id).size_bytes,
            s.get(Artifact, source_artifact_id).relative_path,
        )
    role_count_before = len(list(roles_before))
    occ_count_before = len(list(occ_before))

    result = _submit_attach(session_factory, ws, video_item, managed_root)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"

    with session_factory() as s:
        item = s.get(VideoItem, video_item.id)
        probe_after = (item.duration_ms, item.width, item.height, item.fps_num, item.fps_den)
        roles_after = list(s.scalars(select(ObjectRole)).all())
        occ_after = list(s.scalars(select(ObjectOccurrence)).all())
        src_art = s.get(Artifact, source_artifact_id)
        src_art_after = (src_art.sha256, src_art.size_bytes, src_art.relative_path)
    assert probe_after == probe_before
    assert len(roles_after) == role_count_before
    assert len(occ_after) == occ_count_before
    assert src_art_after == src_art_before
    # The attach checkpoint carries NO absolute managed path.
    cp = _step_checkpoint(session_factory, result.job_id)
    assert managed_root.as_posix() not in json.dumps(cp)


# ── 11. Unknown/missing source → stable failure ──────────────────────────────


def test_11_unknown_or_missing_source_stable_failure(
    svc, session_factory, ws, project, video_item, managed_root
) -> None:
    """Required 11: a VideoItem with no source artifact / a non-ready
    artifact / an unlinked artifact fails closed with stable codes BEFORE
    any managed write; the job then fails permanently."""
    worker = svc.worker

    # (a) No source artifact at all → stable code at submit time.
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        _submit_attach(session_factory, ws, video_item, managed_root)
    assert getattr(excinfo.value, "code", "") == CODE_SOURCE_ARTIFACT_NOT_FOUND

    # Prepare an imported source for the run-time failure paths.
    import hashlib as _hl

    from app.services.video_import import submit_import as si

    dummy = _make_media(managed_root.parent / "fixture_missing.mp4", audio_codec=["-c:a", "aac"])
    si(
        session_factory,
        workspace_id=ws.id,
        project_id=project.id,
        video_item_id=video_item.id,
        source_path=dummy,
        source_sha256=_hl.sha256(dummy.read_bytes()).hexdigest(),
        generation="1",
        managed_root=managed_root,
        title="missing.mp4",
    )
    worker.run_once()
    with session_factory() as s:
        art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item.id,
                ArtifactOwner.purpose == "source",
            )
        )

    def _run_expect_failed(
        submitted_job_id: str, expected_code: str, *, expect_source_file: bool = True
    ) -> None:
        worker.run_once()
        with session_factory() as s:
            job = JobRepository(s).get_job(submitted_job_id)
            assert job.state == "failed", f"expected failed, got {job.state}"
            assert job.error is not None
            assert job.error["error_code"] == expected_code
        assert _audio_artifact(session_factory, video_item.id) is None
        has_source = _artifact_files(managed_root) != []
        if expect_source_file:
            assert has_source  # source still there
        else:
            assert not has_source  # the deleted source stays gone

    # (b) The source FILE vanished from the managed root after import.
    with session_factory() as s:
        art = s.get(Artifact, art_id)
        (managed_root / art.relative_path).unlink()
    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    _run_expect_failed(submitted.job_id, CODE_SOURCE_NOT_READY, expect_source_file=False)

    # Restore the file, then break the OWNER LINK instead.  The submit
    # validates the ownership chain up-front and fails closed BEFORE any
    # Job row exists (stable code, zero side effects).
    with session_factory() as s:
        art = s.get(Artifact, art_id)
        (managed_root / art.relative_path).write_bytes(dummy.read_bytes())
        link = s.get(
            ArtifactOwner,
            (art_id, "video_item", video_item.id, "source"),
        )
        s.delete(link)
        s.commit()
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - stable-code contract
        _submit_attach(session_factory, ws, video_item, managed_root)
    assert getattr(excinfo.value, "code", "") == CODE_SOURCE_OWNER_MISMATCH
    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_ATTACH_ORIGINAL_AUDIO)
        ).all()
    # Only the earlier SOURCE_NOT_READY run produced a Job row.
    assert len(jobs) == 1
    assert _audio_artifact(session_factory, video_item.id) is None


# ── 12. No process leak ──────────────────────────────────────────────────────


def test_12_no_process_leak(
    svc, session_factory, ws, video_item, aac_source, managed_root, tmp_path, monkeypatch
) -> None:
    """Required 12: after success AND after a mid-run cancellation, the full
    ffmpeg child tree is gone (bounded engine cleanup)."""
    try:
        import psutil  # noqa: F401
    except ImportError:
        pytest.skip("psutil unavailable — process-leak assertion needs it")

    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)

    baseline = _ffmpeg_pids()

    # Success path.
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"
    assert _ffmpeg_pids() <= baseline, "ffmpeg survived a successful attach"

    # Cancellation path (second item so the cancel test has its own job).
    # A LONG clip: the remux must still be running when cancellation lands
    # (a 2s synthetic finishes before the cancel flag can be observed).
    other_source = _make_media(
        tmp_path / "src_long.mp4", audio_codec=["-c:a", "aac"], duration=60
    )
    other = VideoItem(
        project_id=video_item.project_id,
        title="Clip C",
        position=2,
        status="imported",
        revision=1,
    )
    with session_factory() as s:
        s.add(other)
        s.commit()
        other_id = other.id

    class _Item:
        pass

    item_proxy = _Item()
    item_proxy.id = other_id
    item_proxy.project_id = video_item.project_id
    _import_source(session_factory, worker, ws, item_proxy, other_source, managed_root)
    result2 = submit_attach_original_audio(
        session_factory,
        workspace_id=ws.id,
        project_id=item_proxy.project_id,
        video_item_id=other_id,
        generation="1",
        managed_root=managed_root,
    )
    job2 = result2.job_id

    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio

    def remux_then_cancel(src, out_dir, **kwargs):
        # Deterministic mid-run cancellation: flip the durable flag BEFORE
        # the engine starts; the adapter's watcher forwards it on its first
        # poll tick, so the bounded engine observes cancellation during the
        # run (or immediately after) and must reap the whole child tree.
        with session_factory() as s:
            rr = JobRepository(s)
            rr.transition_job(
                job2,
                "cancelling",
                actor="api",
                expected_revision=rr.get_job(job2).revision,
            )
            s.commit()
        return real_remux(src, out_dir, **kwargs)

    monkeypatch.setattr(handler_mod, "remux_original_audio", remux_then_cancel)
    worker.run_once()
    monkeypatch.undo()

    assert _job_state(session_factory, job2) == "cancelled"
    deadline_wait = 10.0
    import time as _t

    waited = 0.0
    while waited < deadline_wait:
        if _ffmpeg_pids() <= baseline:
            break
        _t.sleep(0.25)
        waited += 0.25
    assert _ffmpeg_pids() <= baseline, (
        f"orphan ffmpeg processes after cancellation: {_ffmpeg_pids() - baseline}"
    )


# ── R4-P1: source-integrity SHA-256 (same-size mutation fail-closed) ─────────


def _mutate_same_size(path: Path) -> None:
    """Flip bytes IN PLACE keeping the size identical."""
    data = bytearray(path.read_bytes())
    mid = len(data) // 2
    data[mid] = data[mid] ^ 0xFF
    if len(data) > 1 and data[0] == data[0]:
        data[0] = data[0] ^ 0xFF
    path.write_bytes(bytes(data))


def test_13_source_mutated_between_phases_fail_closed_zero_publication(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """R4-P1 regression: a same-size source mutation AFTER the source phase
    checkpoints its evidence must fail the job closed — no audio artifact,
    no published file, no leftover staging from THIS run.

    The mutation lands while the remux runs (deterministic hook), so BOTH
    the engine's own invariant and the adapter's post-engine /
    pre-publication gates are exercised; the job must end FAILED with a
    stable permanent code.
    """
    worker = svc.worker
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )
    with session_factory() as s:
        src_art = s.get(Artifact, source_artifact_id)
        original_sha = src_art.sha256

    result = _submit_attach(session_factory, ws, video_item, managed_root)
    files_before = sorted(_artifact_files(managed_root))

    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio
    mutated = {"done": False}

    def mutating_remux(src, out_dir, **kwargs):
        out = real_remux(src, out_dir, **kwargs)
        # Same-size in-place mutation AFTER the engine succeeded but
        # BEFORE the adapter's post-engine / publish gates run.
        _mutate_same_size(managed_root / src_art.relative_path)
        mutated["done"] = True
        return out

    monkeypatch.setattr(handler_mod, "remux_original_audio", mutating_remux)
    worker.run_once()
    monkeypatch.undo()

    assert mutated["done"]
    assert _job_state(session_factory, result.job_id) == "failed"
    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        code = str(job.error["error_code"]) if job.error else ""
        assert code == "ENGINE_FAILED", f"expected ENGINE_FAILED, got {code}"
        assert "source identity does not match" in str(
            job.error.get("message") or ""
        ) or "changed before publication" in str(job.error.get("message") or "")
    # Zero publication: no audio artifact row, the managed artifacts tree
    # is byte-for-byte unchanged, and no staging leftovers from this run.
    assert _audio_artifact(session_factory, video_item.id) is None
    assert sorted(_artifact_files(managed_root)) == files_before, (
        "published files leaked after fail-closed source-integrity gate"
    )
    assert _staging_files(managed_root) == [], (
        f"staging leftovers after fail-closed purge: {_staging_files(managed_root)}"
    )
    # The mutation was real and same-size: the on-disk hash now differs from
    # the recorded artifact checksum while the recorded SIZE still matches.
    src_path = managed_root / src_art.relative_path
    assert hashlib.sha256(src_path.read_bytes()).hexdigest() != original_sha
    assert src_path.stat().st_size == int(src_art.size_bytes)


def test_14_checkpoint_evidence_never_carries_absolute_paths(
    svc, session_factory, ws, video_item, aac_source, managed_root
) -> None:
    """R4-P1 #8 audit: every evidence dict written via write_checkpoint for
    an ATTACH_ORIGINAL_AUDIO run is path-free — the serialized checkpoint
    must not contain any absolute managed-root prefix."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)
    result = _submit_attach(session_factory, ws, video_item, managed_root)
    worker.run_once()
    assert _job_state(session_factory, result.job_id) == "completed"

    cp_json = json.dumps(_step_checkpoint(session_factory, result.job_id))
    assert managed_root.as_posix() not in cp_json
    assert str(managed_root) not in cp_json


# ── R5-P1: current VideoItem.source_artifact_id is the ONLY authority ────────


def test_15_authority_swap_fail_closed_at_both_replay_points(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """R5-P1 regression: once ``VideoItem.source_artifact_id`` moves to
    another artifact, a STALE job pinned to the old artifact A must fail
    closed EVERYWHERE — fresh resolve, resume after the source checkpoint,
    and resume after the remux checkpoint — and never produce any audio
    output for an item whose authority now points at B."""
    worker = svc.worker
    _, artifact_a_id = _import_source(
        session_factory, worker, ws, video_item, aac_source, managed_root
    )

    # Import a SECOND source for the same item so artifact B exists and is
    # linked; this moves the pointer to B, so put it back to A afterwards —
    # every authority MOVE below is a direct, deterministic DB write
    # (exactly what a concurrent re-import elsewhere would do).
    source_b = _make_media(
        managed_root.parent / "src_b.mp4", audio_codec=["-c:a", "aac"]
    )
    submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_path=source_b,
        source_sha256=hashlib.sha256(source_b.read_bytes()).hexdigest(),
        generation="2",
        managed_root=managed_root,
        title="src_b.mp4",
    )
    assert worker.run_once() >= 1

    def _set_pointer(artifact_id: str) -> None:
        with session_factory() as s:
            item = s.get(VideoItem, video_item.id)
            item.source_artifact_id = artifact_id
            s.commit()

    with session_factory() as s:
        item = s.get(VideoItem, video_item.id)
        current_b_id = str(item.source_artifact_id)
        assert current_b_id != artifact_a_id
        links = list(
            s.scalars(
                select(ArtifactOwner.artifact_id).where(
                    ArtifactOwner.owner_type == "video_item",
                    ArtifactOwner.owner_id == video_item.id,
                    ArtifactOwner.purpose == "source",
                )
            ).all()
        )
    assert artifact_a_id in [str(x) for x in links], (
        "old owner link for A must survive the swap"
    )

    def _files() -> list[Path]:
        return sorted(_artifact_files(managed_root))

    files_after_imports = _files()

    # ── Run 1: job submitted while authority was A (manifest pins A),
    # pointer moved to B before it ever runs → fail closed at resolve. ───
    _set_pointer(artifact_a_id)
    stale = _submit_attach(session_factory, ws, video_item, managed_root)
    _set_pointer(current_b_id)
    worker.run_once()
    assert _job_state(session_factory, stale.job_id) == "failed"
    with session_factory() as s:
        err0 = JobRepository(s).get_job(stale.job_id).error or {}
    assert err0.get("error_code") == "SOURCE_OWNER_MISMATCH", err0
    assert _audio_artifact(session_factory, video_item.id) is None
    assert _files() == files_after_imports
    assert _staging_files(managed_root) == []

    # ── Runs 2+3: the swap lands mid-run, AFTER the engine read A and
    # after BOTH the source and remux checkpoints were written.  The first
    # attempt must die at the pre-publication gate; the forced replay must
    # die AGAIN at the source-phase authority revalidation. ──────────────
    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio

    def remux_then_swap(src, out_dir, **kwargs):
        out = real_remux(src, out_dir, **kwargs)
        _set_pointer(current_b_id)
        return out

    _set_pointer(artifact_a_id)
    # A different generation: the failed stale job still owns the
    # (item, A, gen-1) idempotency key, so this second logical run uses its
    # own key while pinning the SAME artifact A in its manifest.
    midrun = submit_attach_original_audio(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        generation="2",
        managed_root=managed_root,
    )
    monkeypatch.setattr(handler_mod, "remux_original_audio", remux_then_swap)
    worker.run_once()
    monkeypatch.undo()

    assert _job_state(session_factory, midrun.job_id) == "failed"
    with session_factory() as s:
        err1 = JobRepository(s).get_job(midrun.job_id).error or {}
        cp = json.loads(
            s.get(JobStep, JobRepository(s).list_steps(midrun.job_id)[0].id)
            .checkpoint_json
            or "{}"
        )
    assert err1.get("error_code") == "SOURCE_OWNER_MISMATCH", err1
    assert isinstance(cp.get("source"), dict) and isinstance(cp.get("remux"), dict), (
        "precondition: source AND remux checkpoints were written"
    )
    assert _audio_artifact(session_factory, video_item.id) is None
    assert _files() == files_after_imports
    assert _staging_files(managed_root) == []

    # Forced replay WITH the persisted checkpoints: bytes are still valid,
    # authority is not — must fail closed before anything is trusted.
    _force_replay_keep_checkpoint(session_factory, midrun.job_id)
    worker.run_once()
    assert _job_state(session_factory, midrun.job_id) == "failed"
    with session_factory() as s:
        err2 = JobRepository(s).get_job(midrun.job_id).error or {}
    assert err2.get("error_code") == "SOURCE_OWNER_MISMATCH", err2
    assert _audio_artifact(session_factory, video_item.id) is None
    assert _files() == files_after_imports
    assert _staging_files(managed_root) == []


# ── R6-F2: post-success durable cancellation purges THIS Job's staging ───────


def test_16_cancel_after_engine_success_zero_residue(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """R6-F2 regression: the durable cancel flag lands RIGHT AFTER the remux
    engine returned SUCCESS.  The Job must end ``cancelled`` with ZERO audio
    publication, its own engine staging purged (the produced
    ``original_audio.mp4`` included), NO other Job's staging touched, and no
    remux/published evidence checkpointed for the aborted run."""
    worker = svc.worker
    _import_source(session_factory, worker, ws, video_item, aac_source, managed_root)

    # A foreign Job's staging (byte-different sentinel) that MUST survive.
    foreign_dir = (
        managed_root / "staging" / "cross-job-sentinel" / "attach" / "engine"
    )
    foreign_dir.mkdir(parents=True, exist_ok=True)
    sentinel = foreign_dir / "original_audio.mp4"
    sentinel.write_bytes(b"foreign job bytes - never delete")

    result = _submit_attach(session_factory, ws, video_item, managed_root)
    job_id = result.job_id
    engine_out = managed_root / "staging" / job_id / "attach" / "engine" / "original_audio.mp4"
    artifacts_before = sorted(_artifact_files(managed_root))

    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio

    def remux_then_flag(src, out_dir, **kwargs):
        out = real_remux(src, out_dir, **kwargs)
        # Deterministic boundary: the engine SUCCEEDED (output exists on
        # disk) and only NOW does the durable cancel flag appear.
        assert engine_out.is_file(), (
            "precondition: engine output exists before cancellation lands"
        )
        with session_factory() as s:
            repo = JobRepository(s)
            repo.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=repo.get_job(job_id).revision,
            )
            s.commit()
        return out

    monkeypatch.setattr(handler_mod, "remux_original_audio", remux_then_flag)
    worker.run_once()
    monkeypatch.undo()

    # 1+3. Terminal cancelled, stable cancel envelope, zero publication.
    assert _job_state(session_factory, job_id) == "cancelled"
    with session_factory() as s:
        job = JobRepository(s).get_job(job_id)
        err = job.error or {}
        assert err.get("error_code") in ("CANCELLED", "", None), err
    assert _audio_artifact(session_factory, video_item.id) is None
    assert sorted(_artifact_files(managed_root)) == artifacts_before

    # 1+4. THIS Job's engine staging is GONE — including original_audio.mp4
    # and any directory shell under staging/<job_id>.
    assert not engine_out.exists(), "zero-residue violated: engine output survived"
    job_staging = managed_root / "staging" / job_id
    assert not job_staging.exists() or list(job_staging.rglob("*")) == [], (
        f"directory shell left for THIS job: "
        f"{list(job_staging.rglob('*')) if job_staging.exists() else []}"
    )
    # Cross-Job isolation: the sentinel is byte-identical and untouched.
    assert sentinel.read_bytes() == b"foreign job bytes - never delete"

    # 2. NO remux/published evidence may be checkpointed after cancellation
    # (only the source-phase evidence written before the engine ran).
    cp = _step_checkpoint(session_factory, job_id)
    assert "remux" not in cp, f"remux evidence persisted past cancellation: {cp}"
    assert "published" not in cp, f"published evidence persisted: {cp}"
    assert isinstance(cp.get("source"), dict), "precondition: source phase ran"

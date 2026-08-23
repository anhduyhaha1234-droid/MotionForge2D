"""Targeted tests for S05-T02 — managed import with checksum (ANALYZE_MEDIA).

Covers the required scenarios of ``docs/pm/sessions/S05-T02-managed-import/
TASK.md``:

- success: Job completes, exactly one ready ``video`` Artifact, owner link
  purpose ``source``, ``video_item`` probe columns + ``source_artifact_id``;
- checksum/size: the artifact sha256/size come from the copy and match the
  source bytes; a wrong preflight hash aborts before publish
  (``CHECKSUM_MISMATCH``);
- original unchanged: the source file is never mutated/deleted, including
  after a failed import;
- duplicate/idempotent submit: active duplicate → ``IdempotencyKeyInUse``;
  completed duplicate → same Job reused; exactly one effect set;
- copy failure: stable envelope, no artifact, no partial/staging files;
- DB rollback orphan cleanup: a failed publication transaction removes the
  just-published file;
- cancellation: drains to ``cancelled`` with no artifact and cleans staging;
- path escape / symlink containment: ``PATH_CONTAINMENT``, nothing written
  outside the managed root;
- insufficient disk: ``INSUFFICIENT_DISK`` before any byte is copied;
- unsupported V1 media decision: container/codec/audio-codec/HDR fail
  closed with stable codes; ``NO_AUDIO_STREAM`` is accepted with a warning;
- restart recovery: a successor Job after a failed attempt completes without
  duplicate artifacts and cleans crash-leftover staging files.
- Codex correction rounds (S05-T02): owner-safe idempotency (same bytes into
  two VideoItems → two independent Jobs/effect sets); workspace/project/video
  ownership validation at submit AND publication (adversarial cross-scope
  rejection with zero side effects); optional preflight hash (canonical SHA
  recorded from the copy, owner-scoped key without content identity); replay
  publication failure never deletes a previously committed ready artifact
  file.

Every test uses a temporary database + temporary managed root and synthetic
ffmpeg fixtures under ``tmp_path`` (lavfi testsrc + sine).  Tests skip
gracefully when ffmpeg/ffprobe is not available (no-FFmpeg machine safe,
mirroring ``tests/test_ffmpeg_discovery.py``).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.artifacts import ArtifactWriteError, ManagedPathError, ManagedRoot
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
from app.services.video_import import (
    CODE_CHECKSUM_MISMATCH,
    CODE_HDR_UNSUPPORTED,
    CODE_INSUFFICIENT_DISK,
    CODE_NO_AUDIO_STREAM,
    CODE_OWNERSHIP_MISMATCH,
    CODE_PATH_CONTAINMENT,
    CODE_PROJECT_NOT_FOUND,
    CODE_PUBLICATION_FAILED,
    CODE_UNSUPPORTED_CODEC,
    CODE_UNSUPPORTED_CONTAINER,
    CODE_VIDEO_ITEM_NOT_FOUND,
    COPY_STEP_CODE,
    JOB_TYPE_ANALYZE_MEDIA,
    VideoImportError,
    analyze_media_steps,
    register_analyze_media_handler,
    submit_import,
)
from app.workflow.durable_worker import (
    TRANSIENT_ERROR_CODES,
    DurableWorker,
    WorkerConfig,
    error_envelope,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Deterministic clock/sleeper (mirror test_durable_worker.py) ─────────────


class FakeClock:
    """Injectable clock: starts at a fixed UTC instant and advances on demand."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    """Injectable sleeper: records requested delays, never blocks."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ── DB fixtures ──────────────────────────────────────────────────────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """A fresh temporary database path per test."""
    return tmp_path / "import.db"


@pytest.fixture()
def session_factory(db_path: Path):
    """Session factory bound to an upgraded temporary database."""
    _upgrade(db_path)
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def session(session_factory) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture()
def repo(session: Session) -> JobRepository:
    return JobRepository(session)


@pytest.fixture()
def ws(session: Session) -> Workspace:
    ws = Workspace(name="Import Workspace")
    session.add(ws)
    session.commit()
    return ws


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    project = Project(name="Import Project", workspace_id=ws.id, status="active")
    session.add(project)
    session.commit()
    return project


@pytest.fixture()
def video_item(session: Session, project: Project) -> VideoItem:
    item = VideoItem(
        project_id=project.id,
        title="Clip 1",
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
def worker(
    session_factory,
    managed_root: Path,
    clock: FakeClock,
    sleeper: FakeSleeper,
) -> DurableWorker:
    """A worker with fake clock/sleeper and the ANALYZE_MEDIA handler."""
    w = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="import-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
        clock=clock,
        sleeper=sleeper,
    )
    register_analyze_media_handler(w)
    return w


# ── Synthetic video fixtures (lavfi testsrc + sine → tmp_path) ──────────────


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


@pytest.fixture()
def source_video(tmp_path: Path) -> Path:
    """A real MP4/H.264/AAC synthetic fixture (skips when ffmpeg is absent)."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    out = _make_video(tmp_path / "source.mp4")
    assert out is not None, "ffmpeg failed to create the source fixture"
    return out


def _make_video(
    path: Path,
    *,
    vcodec: str = "libx264",
    acodec: str = "aac",
    pix_fmt: str = "yuv420p",
    audio: bool = True,
    duration: float = 1.0,
    fps: int = 30,
) -> Path | None:
    """Create a synthetic video with ffmpeg; None when the encode fails.

    The caller may skip when None (e.g. a codec/feature this ffmpeg build
    does not ship).
    """
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=320x240:rate={fps}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += ["-c:v", vcodec, "-preset", "ultrafast", "-crf", "28", "-pix_fmt", pix_fmt]
    if audio:
        cmd += ["-c:a", acodec, "-b:a", "64k", "-shortest"]
    cmd.append(str(path))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return path


# ── Submit helpers ───────────────────────────────────────────────────────────


def _submit(
    session_factory,
    ws: Workspace,
    video_item: VideoItem,
    source: Path,
    managed_root: Path,
    *,
    source_sha256: str | None = None,
    omit_sha: bool = False,
    generation: str = "1",
) -> object:
    sha = None if omit_sha else (
        source_sha256 or hashlib.sha256(source.read_bytes()).hexdigest()
    )
    return submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_path=source,
        source_sha256=sha,
        generation=generation,
        managed_root=managed_root,
        title=source.name,
    )


def _run_job(worker: DurableWorker) -> None:
    """Execute one queue scan (one job to terminal)."""
    worker.run_once()


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _artifact_rows(session_factory, workspace_id: str) -> list[Artifact]:
    with session_factory() as s:
        return list(
            s.scalars(
                select(Artifact).where(Artifact.workspace_id == workspace_id)
            ).all()
        )


def _staging_files(managed_root: Path) -> list[Path]:
    staging = managed_root / "staging"
    if not staging.is_dir():
        return []
    return [p for p in staging.rglob("*") if p.is_file()]


def _artifact_files(managed_root: Path) -> list[Path]:
    artifacts = managed_root / "artifacts"
    if not artifacts.is_dir():
        return []
    return [p for p in artifacts.rglob("*") if p.is_file()]


# ── AC2: success path ────────────────────────────────────────────────────────


def test_success_import_publishes_ready_source_artifact(
    worker, session_factory, ws, project, video_item, source_video, managed_root
) -> None:
    """AC2: Job completes; one ready artifact; source owner link; probe cols."""
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"

    with session_factory() as s:
        repo = JobRepository(s)
        job = repo.get_job(result.job_id)
        assert job.job_type == JOB_TYPE_ANALYZE_MEDIA
        assert job.owner_type == "video_item"
        assert job.owner_id == video_item.id
        assert job.idempotency_key == (
            f"{JOB_TYPE_ANALYZE_MEDIA}:video_item:{video_item.id}:"
            f"{hashlib.sha256(source_video.read_bytes()).hexdigest()}:1"
        )
        steps = repo.list_steps(result.job_id)
        assert [step.step_code for step in steps] == [COPY_STEP_CODE]
        assert steps[0].state == "completed"

        arts = _artifact_rows(session_factory, ws.id)
        assert len(arts) == 1
        art = arts[0]
        assert art.kind == "video"
        assert art.state == "ready"
        assert art.relative_path.startswith(f"artifacts/{ws.id}/video/")

        owner = s.scalar(
            select(ArtifactOwner).where(ArtifactOwner.artifact_id == art.id)
        )
        assert owner is not None
        assert owner.owner_type == "video_item"
        assert owner.owner_id == video_item.id
        assert owner.purpose == "source"

        item = s.get(VideoItem, video_item.id)
        assert item.source_artifact_id == art.id
        assert item.duration_ms is not None and item.duration_ms > 0
        assert item.width == 320
        assert item.height == 240
        assert item.fps_num == 30
        assert item.fps_den == 1

        # The published file exists at the recorded relative path.
        target = managed_root / art.relative_path
        assert target.is_file()
        assert target.read_bytes() == source_video.read_bytes()

    # No staging leftovers and no channels.json anywhere near the test tree.
    assert _staging_files(managed_root) == []
    assert not list((managed_root / "staging").rglob("*.staging"))


def test_checksum_and_size_recorded_from_copy(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """AC2: artifact sha256/size come from the copy and match the source."""
    source_bytes = source_video.read_bytes()
    expected_sha = hashlib.sha256(source_bytes).hexdigest()
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    arts = _artifact_rows(session_factory, ws.id)
    assert len(arts) == 1
    art = arts[0]
    assert art.sha256 == expected_sha
    assert art.size_bytes == len(source_bytes)
    assert (managed_root / art.relative_path).read_bytes() == source_bytes


def test_checksum_mismatch_aborts_before_publish(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """AC2/AC3: a wrong preflight hash fails the copy before any artifact."""
    wrong_sha = "a" * 64  # valid hex, not the file's hash
    result = _submit(
        session_factory, ws, video_item, source_video, managed_root,
        source_sha256=wrong_sha,
    )
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_CHECKSUM_MISMATCH
    assert _artifact_rows(session_factory, ws.id) == []
    assert _staging_files(managed_root) == []
    assert _artifact_files(managed_root) == []


def test_original_source_never_mutated_or_deleted(
    worker, session_factory, ws, video_item, source_video, managed_root, tmp_path
) -> None:
    """AC2/AC5: the source is read-only across success and failure paths."""
    before = source_video.read_bytes()
    before_size = source_video.stat().st_size

    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"
    assert source_video.exists()
    assert source_video.read_bytes() == before

    # A failed import (unsupported container) must not mutate the source.
    bad = _make_video(tmp_path / "bad.mkv", vcodec="libx264", acodec="aac")
    if bad is None:
        pytest.skip("ffmpeg could not produce the mkv fixture")
    bad_before = bad.read_bytes()
    bad_result = _submit(session_factory, ws, video_item, bad, managed_root)
    _run_job(worker)
    with session_factory() as s:
        job = JobRepository(s).get_job(bad_result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_UNSUPPORTED_CONTAINER
    assert bad.exists()
    assert bad.read_bytes() == bad_before
    assert source_video.read_bytes() == before
    assert source_video.stat().st_size == before_size


# ── AC3: duplicate / idempotent submit ───────────────────────────────────────


def test_duplicate_submit_single_effect_set(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """AC3: active duplicate raises; completed duplicate reuses the Job."""
    from app.persistence.jobs import IdempotencyKeyInUse

    r1 = _submit(session_factory, ws, video_item, source_video, managed_root)

    # Active duplicate → stable conflict (contract §8.1).
    with pytest.raises(IdempotencyKeyInUse):
        _submit(session_factory, ws, video_item, source_video, managed_root)

    _run_job(worker)
    assert _job_state(session_factory, r1.job_id) == "completed"

    # Completed duplicate → same Job reused, no new rows/files.
    r2 = _submit(session_factory, ws, video_item, source_video, managed_root)
    assert r2.job_id == r1.job_id
    assert r2.reused is True

    with session_factory() as s:
        job_ids = s.scalars(select(Job.id)).all()
        assert len(job_ids) == 1
    arts = _artifact_rows(session_factory, ws.id)
    assert len(arts) == 1
    assert len(_artifact_files(managed_root)) == 1


# ── AC4: copy failure / DB rollback / cancellation cleanup ──────────────────


def test_copy_failure_cleans_staging_and_fails(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC4: a failed atomic copy leaves no artifact, no final file, no staging."""
    def failing_stream(self, relative_path, stream, **kwargs):  # type: ignore[no-untyped-def]
        raise ArtifactWriteError("simulated copy failure")

    monkeypatch.setattr(ManagedRoot, "atomic_write_stream", failing_stream)
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PUBLICATION_FAILED
    assert _artifact_rows(session_factory, ws.id) == []
    assert _staging_files(managed_root) == []
    assert _artifact_files(managed_root) == []


def test_db_rollback_orphan_cleanup(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC4: a failed publication transaction removes the published file."""
    def failing_effect(ctx, final_rel, sha256, size, probe):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(video_import, "_publish_effect", failing_effect)
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PUBLICATION_FAILED
    assert _artifact_rows(session_factory, ws.id) == []
    # The just-published file was removed (no orphan), and no staging files.
    assert _artifact_files(managed_root) == []
    assert _staging_files(managed_root) == []


def test_cancellation_drains_and_cleans_staging(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC4: cancel during copy → terminal cancelled, no artifact, staging clean."""
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    job_id = result.job_id
    real_stream = ManagedRoot.atomic_write_stream

    def stream_then_cancel(self, relative_path, stream, **kwargs):  # type: ignore[no-untyped-def]
        out = real_stream(self, relative_path, stream, **kwargs)
        with session_factory() as s:
            r = JobRepository(s)
            r.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=r.get_job(job_id).revision,
            )
            s.commit()
        return out

    monkeypatch.setattr(ManagedRoot, "atomic_write_stream", stream_then_cancel)
    _run_job(worker)

    assert _job_state(session_factory, job_id) == "cancelled"
    assert _artifact_rows(session_factory, ws.id) == []
    assert _staging_files(managed_root) == []
    assert _artifact_files(managed_root) == []


# ── AC5: path escape / symlink containment ───────────────────────────────────


def test_sanitize_name_removes_traversal_components() -> None:
    """AC5: malicious source names cannot add path components to managed paths."""
    assert video_import._sanitize_name("../../escape.mp4") == "escape.mp4"
    assert video_import._sanitize_name("..") == "source.mp4"
    # Both / and \ separators are stripped (basename semantics); the result
    # never contains a separator or a traversal component on any platform.
    mixed = video_import._sanitize_name("a/b\\c.mp4")
    assert "/" not in mixed
    assert "\\" not in mixed
    assert ".." not in mixed
    assert ".." not in Path(video_import._sanitize_name("../../x.mp4")).parts

    # ManagedRoot rejects any crafted traversal outright.
    root = Path(__file__).resolve().parent
    managed = ManagedRoot(root)
    with pytest.raises(ManagedPathError):
        managed.resolve("artifacts/../../evil.mp4")


def test_symlink_escape_rejected_and_nothing_written_outside(
    worker, session_factory, ws, video_item, source_video, managed_root, tmp_path
) -> None:
    """AC5: a symlink inside the root pointing outside fails with
    PATH_CONTAINMENT and nothing is written outside."""
    outside = tmp_path / "outside"
    outside.mkdir()
    art_dir = managed_root / "artifacts" / ws.id / "video"
    art_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        art_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PATH_CONTAINMENT
    assert _artifact_rows(session_factory, ws.id) == []
    assert list(outside.iterdir()) == []
    # The staged copy was removed on the containment failure.
    assert _staging_files(managed_root) == []


# ── AC6: insufficient disk ───────────────────────────────────────────────────


def test_insufficient_disk_rejected_before_copy(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC6: the free-disk guard fails the job before any byte is copied."""
    monkeypatch.setattr(video_import, "_disk_free_bytes", lambda root: 0)
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_INSUFFICIENT_DISK
        assert job.error.get("details", {}).get("required_bytes") is not None
    assert _artifact_rows(session_factory, ws.id) == []
    assert _staging_files(managed_root) == []


# ── AC7: unsupported V1 media decision ───────────────────────────────────────


@pytest.mark.parametrize(
    "extension,vcodec,acodec,pix_fmt,audio,expected_code",
    [
        ("mkv", "libx264", "aac", "yuv420p", True, CODE_UNSUPPORTED_CONTAINER),
        ("mp4", "mpeg4", "aac", "yuv420p", True, CODE_UNSUPPORTED_CODEC),
        # S11 B5 resolution: a non-AAC FIRST audio stream is accepted with an
        # explicit warning — it is no longer a fail-closed rejection (the
        # dedicated S11 regressions live in tests/test_s11_original_audio_contract.py).
        ("mp4", "libx264", "aac", "yuv420p10le", True, CODE_HDR_UNSUPPORTED),
    ],
)
def test_unsupported_media_fails_closed(
    worker,
    session_factory,
    ws,
    video_item,
    managed_root,
    tmp_path,
    extension,
    vcodec,
    acodec,
    pix_fmt,
    audio,
    expected_code,
) -> None:
    """AC7: every unsupported V1 media decision rejects with the stable code."""
    source = _make_video(
        tmp_path / f"case.{extension}",
        vcodec=vcodec,
        acodec=acodec,
        pix_fmt=pix_fmt,
        audio=audio,
    )
    if source is None:
        pytest.skip("ffmpeg could not produce this fixture")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_path=source,
        source_sha256=sha,
        managed_root=managed_root,
    )
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == expected_code
        # Every envelope carries a stable message (never a bare "failed").
        assert isinstance(job.error.get("message"), str)
    assert _artifact_rows(session_factory, ws.id) == []
    assert _staging_files(managed_root) == []


def test_no_audio_stream_is_accepted_with_warning(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    """AC7: NO_AUDIO_STREAM is a warning, not a blocker (PRD §9 Step 4)."""
    source = _make_video(tmp_path / "noaudio.mp4", vcodec="libx264", audio=False)
    if source is None:
        pytest.skip("ffmpeg could not produce the no-audio fixture")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_path=source,
        source_sha256=sha,
        managed_root=managed_root,
    )
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    with session_factory() as s:
        repo = JobRepository(s)
        steps = repo.list_steps(result.job_id)
        checkpoint = steps[0].checkpoint or {}
        probe = checkpoint["probe"]
        assert probe["has_audio"] is False
        codes = [w["code"] for w in probe["warnings"]]
        assert CODE_NO_AUDIO_STREAM in codes
        arts = _artifact_rows(session_factory, ws.id)
        assert len(arts) == 1
        item = s.get(VideoItem, video_item.id)
        assert item.source_artifact_id == arts[0].id

    # The audio-codec metadata is recorded in the probe JSON only — no new
    # durable column was invented (no schema change).
    with session_factory() as s:
        cols = [row[1] for row in s.execute(text("PRAGMA table_info(video_item)")).all()]
    assert "has_audio" not in cols


# ── AC8: restart recovery / successor without duplicates ─────────────────────


def test_restart_recovery_successor_no_duplicate_artifacts(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC8: a failed attempt leaves a crash partial; the successor cleans it
    and completes with exactly one artifact."""
    def crash_copy(self, relative_path, stream, **kwargs):  # type: ignore[no-untyped-def]
        # Simulate a hard crash mid-copy: write a partial staging file, then
        # raise (no cleanup — the process "died").
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.crash.staging")
        partial.write_bytes(b"partial bytes from a crashed copy")
        raise ArtifactWriteError("simulated crash mid-copy")

    monkeypatch.setattr(ManagedRoot, "atomic_write_stream", crash_copy)
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    with session_factory() as s:
        repo = JobRepository(s)
        pred = repo.get_job(result.job_id)
        assert pred.state == "failed"
        # The crash partial is still on disk (no cleanup happened).
        partials = list((managed_root / "staging").rglob("*.staging"))
        assert len(partials) == 1

        # Retry/restart: a successor Job with the same key/generation.
        succ = repo.create_successor(
            predecessor_job_id=pred.id,
            input_manifest=pred.input_manifest,
            idempotency_key=pred.idempotency_key,
            input_generation=pred.input_generation,
            steps=analyze_media_steps(),
        )
        s.commit()
        succ_id = succ.id

    # The successor runs with the REAL handler (crash monkeypatch removed).
    monkeypatch.undo()
    _run_job(worker)

    assert _job_state(session_factory, succ_id) == "completed"
    arts = _artifact_rows(session_factory, ws.id)
    assert len(arts) == 1
    assert arts[0].state == "ready"
    # The predecessor's crash partial was garbage-collected by the successor,
    # and exactly ONE published artifact file exists (no duplicates).
    assert _staging_files(managed_root) == []
    assert len(_artifact_files(managed_root)) == 1
    with session_factory() as s:
        repo = JobRepository(s)
        succ = repo.get_job(succ_id)
        assert succ.predecessor_job_id == result.job_id
        assert succ.idempotency_key == pred.idempotency_key


# ── Probe timeout classification (contract §6.1/§7) ──────────────────────────


def test_probe_timeout_is_transient() -> None:
    """PROBE_TIMEOUT is classified transient so the worker auto-retries."""
    assert "PROBE_TIMEOUT" in TRANSIENT_ERROR_CODES
    envelope = error_envelope("PROBE_TIMEOUT", "budget exhausted")
    assert envelope["class"] == "transient"


def test_probe_timeout_retries_then_fails_exhausted(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """A bounded ffprobe timeout retries up to max_attempts then fails."""
    def timeout_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 30))

    monkeypatch.setattr(subprocess, "run", timeout_run)
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)

    with session_factory() as s:
        repo = JobRepository(s)
        job = repo.get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == "RETRIES_EXHAUSTED"
        from app.persistence.models import JobAttempt

        attempts = s.scalars(
            select(JobAttempt.id).where(JobAttempt.job_id == result.job_id)
        ).all()
        assert len(attempts) >= 3
    assert _artifact_rows(session_factory, ws.id) == []


# ── Correction #1: owner-safe idempotency ───────────────────────────────────


def test_same_bytes_two_video_items_get_own_jobs_and_effects(
    worker, session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """Same source bytes imported into two VideoItems → two independent
    Jobs/effect sets (owner-scoped identity, correction #1)."""
    item2 = VideoItem(
        project_id=project.id, title="Clip 2", position=1, status="imported", revision=1
    )
    session.add(item2)
    session.commit()

    r1 = _submit(session_factory, ws, video_item, source_video, managed_root)
    r2 = _submit(session_factory, ws, item2, source_video, managed_root)
    assert r1.job_id != r2.job_id
    assert r1.reused is False
    assert r2.reused is False

    _run_job(worker)
    _run_job(worker)

    assert _job_state(session_factory, r1.job_id) == "completed"
    assert _job_state(session_factory, r2.job_id) == "completed"

    with session_factory() as s:
        repo = JobRepository(s)
        k1 = repo.get_job(r1.job_id).idempotency_key
        k2 = repo.get_job(r2.job_id).idempotency_key
        assert k1 != k2
        assert f":{video_item.id}:" in k1
        assert f":{item2.id}:" in k2

        arts = _artifact_rows(session_factory, ws.id)
        assert len(arts) == 2
        assert len({a.id for a in arts}) == 2
        for art in arts:
            assert art.state == "ready"
            owner = s.scalar(
                select(ArtifactOwner).where(ArtifactOwner.artifact_id == art.id)
            )
            assert owner is not None
            assert owner.purpose == "source"

        item_a = s.get(VideoItem, video_item.id)
        item_b = s.get(VideoItem, item2.id)
        assert item_a.source_artifact_id is not None
        assert item_b.source_artifact_id is not None
        assert item_a.source_artifact_id != item_b.source_artifact_id

    assert len(_artifact_files(managed_root)) == 2
    assert _staging_files(managed_root) == []


# ── Correction #2: workspace/project/video ownership validation ─────────────


def test_submit_rejects_cross_project_ownership_before_job_creation(
    session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """Cross-project submit: video item belongs to project A, manifest says
    project B → OWNERSHIP_MISMATCH before any Job row exists."""
    other_project = Project(name="Other Project", workspace_id=ws.id, status="active")
    session.add(other_project)
    session.commit()
    with pytest.raises(VideoImportError) as ei:
        submit_import(
            session_factory,
            workspace_id=ws.id,
            project_id=other_project.id,
            video_item_id=video_item.id,
            source_path=source_video,
            source_sha256=hashlib.sha256(source_video.read_bytes()).hexdigest(),
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_OWNERSHIP_MISMATCH
    with session_factory() as s:
        assert s.scalars(select(Job.id)).all() == []
        assert s.scalars(select(Artifact.id)).all() == []
        assert s.scalars(select(ArtifactOwner.artifact_id)).all() == []
    assert _artifact_files(managed_root) == []
    assert _staging_files(managed_root) == []


def test_submit_rejects_cross_workspace_ownership_before_job_creation(
    session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """Cross-workspace submit: project belongs to ws A, manifest says ws B →
    OWNERSHIP_MISMATCH before any Job row exists."""
    ws_b = Workspace(name="Other Workspace")
    session.add(ws_b)
    session.commit()
    with pytest.raises(VideoImportError) as ei:
        submit_import(
            session_factory,
            workspace_id=ws_b.id,
            project_id=project.id,
            video_item_id=video_item.id,
            source_path=source_video,
            source_sha256=hashlib.sha256(source_video.read_bytes()).hexdigest(),
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_OWNERSHIP_MISMATCH
    with session_factory() as s:
        assert s.scalars(select(Job.id)).all() == []
        assert s.scalars(select(Artifact.id)).all() == []
        assert s.scalars(select(ArtifactOwner.artifact_id)).all() == []
    assert _artifact_files(managed_root) == []
    assert _staging_files(managed_root) == []


def test_submit_rejects_missing_project_before_job_creation(
    session_factory, ws, video_item, source_video, managed_root
) -> None:
    """A nonexistent/archived project → PROJECT_NOT_FOUND, no Job row."""
    with pytest.raises(VideoImportError) as ei:
        submit_import(
            session_factory,
            workspace_id=ws.id,
            project_id="no-such-project",
            video_item_id=video_item.id,
            source_path=source_video,
            source_sha256=hashlib.sha256(source_video.read_bytes()).hexdigest(),
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_PROJECT_NOT_FOUND
    with session_factory() as s:
        assert s.scalars(select(Job.id)).all() == []


def test_submit_rejects_missing_video_item_before_job_creation(
    session_factory, ws, project, source_video, managed_root
) -> None:
    """A nonexistent video item → VIDEO_ITEM_NOT_FOUND, no Job row."""
    with pytest.raises(VideoImportError) as ei:
        submit_import(
            session_factory,
            workspace_id=ws.id,
            project_id=project.id,
            video_item_id="no-such-item",
            source_path=source_video,
            source_sha256=hashlib.sha256(source_video.read_bytes()).hexdigest(),
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_VIDEO_ITEM_NOT_FOUND
    with session_factory() as s:
        assert s.scalars(select(Job.id)).all() == []


def test_publication_revalidates_ownership_after_submit(
    worker, session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """Ownership is re-validated at publication: moving the video item to
    another project between submit and run fails with OWNERSHIP_MISMATCH and
    zero artifact/owner/file side effects."""
    result = _submit(session_factory, ws, video_item, source_video, managed_root)

    other_project = Project(name="Moved Project", workspace_id=ws.id, status="active")
    session.add(other_project)
    session.commit()
    item = session.get(VideoItem, video_item.id)
    item.project_id = other_project.id
    session.commit()

    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "failed"
    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.error is not None
        assert job.error["error_code"] == CODE_OWNERSHIP_MISMATCH
    assert _artifact_rows(session_factory, ws.id) == []
    assert _artifact_files(managed_root) == []
    assert _staging_files(managed_root) == []


# ── Correction #3: optional preflight hash (no request-path hashing) ────────


def test_submit_without_preflight_hash_records_canonical_sha(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """No preflight SHA: the request path never hashes the file; the worker
    computes the canonical SHA during the streaming copy and records it on
    the artifact; the idempotency key is owner-scoped (no content identity
    is claimed before the hash exists)."""
    real_sha = hashlib.sha256(source_video.read_bytes()).hexdigest()
    result = _submit(
        session_factory, ws, video_item, source_video, managed_root, omit_sha=True
    )
    assert result.reused is False

    with session_factory() as s:
        repo = JobRepository(s)
        job = repo.get_job(result.job_id)
        assert job.idempotency_key == (
            f"{JOB_TYPE_ANALYZE_MEDIA}:video_item:{video_item.id}:1"
        )
        assert job.input_manifest.get("source_sha256") is None

    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"
    arts = _artifact_rows(session_factory, ws.id)
    assert len(arts) == 1
    # The canonical SHA comes from the copy, not from the request path.
    assert arts[0].sha256 == real_sha
    assert arts[0].size_bytes == source_video.stat().st_size
    assert (managed_root / arts[0].relative_path).read_bytes() == source_video.read_bytes()
    assert _staging_files(managed_root) == []


def test_duplicate_submit_without_preflight_hash_reuses(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """Owner-scoped identity without a preflight hash: active duplicate →
    IdempotencyKeyInUse; completed duplicate → same Job reused (exactly one
    effect set)."""
    from app.persistence.jobs import IdempotencyKeyInUse

    r1 = _submit(
        session_factory, ws, video_item, source_video, managed_root, omit_sha=True
    )
    with pytest.raises(IdempotencyKeyInUse):
        _submit(session_factory, ws, video_item, source_video, managed_root, omit_sha=True)

    _run_job(worker)
    assert _job_state(session_factory, r1.job_id) == "completed"

    r2 = _submit(
        session_factory, ws, video_item, source_video, managed_root, omit_sha=True
    )
    assert r2.job_id == r1.job_id
    assert r2.reused is True
    with session_factory() as s:
        assert len(s.scalars(select(Job.id)).all()) == 1
    assert len(_artifact_files(managed_root)) == 1
    assert len(_artifact_rows(session_factory, ws.id)) == 1


def test_with_preflight_hash_key_embeds_content_identity(
    session_factory, ws, video_item, source_video, managed_root
) -> None:
    """When a preflight hash IS supplied it is part of the owner-scoped key
    (content identity), so same-item duplicate submits of the same bytes
    collide on the same key."""
    sha = hashlib.sha256(source_video.read_bytes()).hexdigest()
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.idempotency_key == (
            f"{JOB_TYPE_ANALYZE_MEDIA}:video_item:{video_item.id}:{sha}:1"
        )


# ── Correction #4: replay cleanup never deletes committed ready files ───────


def test_replay_publication_failure_keeps_committed_artifact(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """A later publication failure during replay must NOT delete a previously
    committed ready artifact file: only files created/moved by the failing
    attempt are removed (correction #4)."""
    result = _submit(session_factory, ws, video_item, source_video, managed_root)
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"
    source_bytes = source_video.read_bytes()

    # Force replay: lose the checkpoint and reset the terminal job/step so
    # the worker re-runs the SAME Job (same job_id → same final path).  This
    # mirrors a reconciler requeue of a fenced claim: the lease is removed
    # (expired), the step rolls back to pending, and append-only attempt rows
    # are cleared — a fenced mid-flight claim records no attempt row, so a
    # fresh claim restarts per-claim attempt numbering at 1.
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(result.job_id)[0].id)
        step_row.checkpoint_json = None
        step_row.state = "pending"
        step_row.attempt = 0
        step_row.error_json = None
        step_row.started_at = None
        step_row.finished_at = None
        job_row = s.get(Job, result.job_id)
        job_row.state = "queued"
        job_row.attempt = 0
        job_row.error_json = None
        job_row.started_at = None
        job_row.finished_at = None
        lease = s.get(JobLease, result.job_id)
        if lease is not None:
            s.delete(lease)
        for attempt in s.scalars(
            select(JobAttempt).where(JobAttempt.job_id == result.job_id)
        ).all():
            s.delete(attempt)
        s.commit()

    # Inject a DB failure at publication during the replay.
    def failing_effect(ctx, final_rel, sha256, size, probe):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated DB failure during replay")

    monkeypatch.setattr(video_import, "_publish_effect", failing_effect)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PUBLICATION_FAILED

        # The committed row survives the failed replay...
        arts = _artifact_rows(session_factory, ws.id)
        assert len(arts) == 1
        assert arts[0].state == "ready"
        art = arts[0]
        owner = s.scalar(
            select(ArtifactOwner).where(ArtifactOwner.artifact_id == art.id)
        )
        assert owner is not None
        assert owner.owner_id == video_item.id
        # ...and the committed file is intact and readable.
        target = managed_root / art.relative_path
        assert target.is_file()
        assert target.read_bytes() == source_bytes
    assert _staging_files(managed_root) == []


def test_publish_file_checksum_mismatch_keeps_existing_final(managed_root) -> None:
    """A pre-existing final file that does not match the recorded checksum
    raises CHECKSUM_MISMATCH and is NOT removed by the publish helper
    (correction #4: cleanup never deletes a previously committed file)."""
    managed = ManagedRoot(managed_root)
    staged = managed.resolve("staging/j1/import/keep.mp4")
    final = managed.resolve("artifacts/ws1/video/j1/import/keep.mp4")
    staged.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    existing_bytes = b"committed-ready-bytes"
    staged_bytes = b"new-attempt-bytes"
    staged.write_bytes(staged_bytes)
    final.write_bytes(existing_bytes)
    recorded_sha = hashlib.sha256(staged_bytes).hexdigest()

    with pytest.raises(VideoImportError) as ei:
        video_import._publish_file(managed, staged, final, recorded_sha)
    assert ei.value.code == CODE_CHECKSUM_MISMATCH
    # The pre-existing committed file is untouched.
    assert final.read_bytes() == existing_bytes

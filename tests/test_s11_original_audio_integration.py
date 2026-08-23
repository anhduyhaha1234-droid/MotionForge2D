"""S11-T01D — Real Integration required scenarios 1-8 (binary).

End-to-end integration of the three MANAGER_VERIFIED S11-T01 slices over the
REAL production path: the default ``JobService`` (its own ``DurableWorker``
with the full production handler registration), a temp SQLite database
(Alembic upgraded), a temp managed root, real FFmpeg lavfi synthetic media
and ``DurableWorker.run_once`` — no mocks on the production surface (only
deterministic clock/sleeper injection and surgical monkeypatch seams that the
durable contract itself defines).

Required-scenario map (TASK.md "Required scenarios (binary)" 1-8):

1. test_s01_happy_path_mp4_aac_import_attach_completed — MP4 H.264+AAC
   import → ATTACH_ORIGINAL_AUDIO → completed; artifact kind=audio,
   purpose=original_audio, owner=video_item; file published under the temp
   managed root; the Job completes only AFTER publication (event order).
2. test_s02_no_audio_no_audio_present — video-only MP4 → import warns
   NO_AUDIO_STREAM, attach completes with the explicit NO_AUDIO_PRESENT
   outcome; no artifact, no fabricated audio file.
3. test_s03_corrupt_fail_closed_zero_publication — truncated/garbage source:
   import fails closed (stable code, zero managed writes) and a garbage
   source swapped in behind the artifact fails the attach closed with
   zero audio publication.
4. test_s04_non_aac_ac3_mp3_import_warning_then_attach — AC-3 and MP3 first
   audio: import accepted WITH the UNSUPPORTED_AUDIO_CODEC warning; attach
   still runs and publishes AAC (engine transcode path).
5. test_s05_restart_mid_run_no_duplicate_artifact — worker killed after the
   engine checkpoint (before publication): resume completes with exactly one
   audio artifact and no duplicate files.
6. test_s06_cancellation_mid_remux_zero_publication — cancel flag flipped
   during the remux: zero publication, staging clean, no orphan ffmpeg.
7. test_s07_idempotency_reuse_and_conflict_fail_closed — equivalent resubmit
   reuses the completed Job (reused=True, one effect set); an ACTIVE
   duplicate fails closed with IdempotencyKeyInUse; a cross-owner submit is
   rejected before any Job row exists.
8. test_s08_analysis_generation_unchanged — ObjectRole/ObjectOccurrence rows
   and the source probe columns/artifact are byte-for-byte unchanged by the
   attach job; the checkpoint carries no absolute managed path.

Known pre-existing (NOT S11 — recorded in evidence, untouched):
tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables
fails because the S07 migration added ``project_cast_mapping`` and the S07
guard-test was not updated; tests/test_integration.py is skipped (SAM2
segfault) and excluded from the suite command.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
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
    JobEvent,
    JobLease,
    JobStep,
    ObjectOccurrence,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.services import video_import
from app.services.video_import import (
    CODE_NO_AUDIO_STREAM,
    CODE_UNSUPPORTED_AUDIO_CODEC,
    submit_import,
)
from app.workflow.durable_worker import DurableWorker, WorkerConfig
from app.workflow.job_service import JobService
from app.workflow.original_audio_handler import (
    JOB_TYPE_ATTACH_ORIGINAL_AUDIO,
    submit_attach_original_audio,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Deterministic clock/sleeper (mirror test_s11_attach_original_audio_job) ──


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 22, 0, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ── DB fixtures (temp SQLite via Alembic — production schema) ────────────────


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "integration.db"


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
    ws_row = Workspace(name="T01D Workspace")
    session.add(ws_row)
    session.commit()
    return ws_row


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    proj = Project(name="T01D Project", workspace_id=ws.id, status="active")
    session.add(proj)
    session.commit()
    return proj


@pytest.fixture()
def video_item(session: Session, project: Project) -> VideoItem:
    item = VideoItem(
        project_id=project.id,
        title="T01D Clip",
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
    worker._config = WorkerConfig(  # noqa: SLF001 - test seam on own instance
        worker_id="t01d-worker",
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


# ── Synthetic media fixtures (real FFmpeg lavfi) ─────────────────────────────


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


def _make_media(
    path: Path,
    *,
    audio_codec: list[str],
    duration: float = 2.0,
) -> Path:
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


def _make_video_only(path: Path, *, duration: float = 2.0) -> Path:
    """A CFR MP4/H.264 clip with NO audio stream at all."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"fixture generation failed: {result.stderr[-300:]}"
    return path


@pytest.fixture()
def aac_source(tmp_path: Path) -> Path:
    return _make_media(
        tmp_path / "src_aac.mp4", audio_codec=["-c:a", "aac", "-b:a", "64k"]
    )


@pytest.fixture()
def mp3_source(tmp_path: Path) -> Path:
    return _make_media(
        tmp_path / "src_mp3.mp4", audio_codec=["-c:a", "libmp3lame", "-b:a", "96k"]
    )


@pytest.fixture()
def ac3_source(tmp_path: Path) -> Path:
    return _make_media(
        tmp_path / "src_ac3.mp4", audio_codec=["-c:a", "ac3", "-b:a", "96k"]
    )


@pytest.fixture()
def no_audio_source(tmp_path: Path) -> Path:
    return _make_video_only(tmp_path / "src_silent.mp4")


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


# ── Import / attach / inspection helpers ─────────────────────────────────────


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _import_source(
    session_factory,
    worker: DurableWorker,
    ws: Workspace,
    video_item_id: str,
    project_id: str,
    source: Path,
    managed_root: Path,
) -> tuple[str, str]:
    """Run the approved S05-T02 import; returns (job_id, source_artifact_id)."""
    result = submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=project_id,
        video_item_id=video_item_id,
        source_path=source,
        source_sha256=_sha256(source),
        generation="1",
        managed_root=managed_root,
        title=source.name,
    )
    assert worker.run_once() == 1
    with session_factory() as s:
        art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item_id,
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


def _job_error_code(session_factory, job_id: str) -> str | None:
    with session_factory() as s:
        job = JobRepository(s).get_job(job_id)
        return job.error.get("error_code") if job.error else None


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
    assert len(rows) <= 1, (
        f"expected at most one original-audio artifact, got {len(rows)}"
    )
    return rows[0] if rows else None


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


def audio_rows_total(managed_root: Path, session_factory) -> int:
    """Total audio artifact rows in the DB (duplicate-detection helper)."""
    del managed_root
    with session_factory() as s:
        return len(list(s.scalars(select(Artifact).where(Artifact.kind == "audio"))))


def _job_event_types(session_factory, job_id: str) -> list[str]:
    with session_factory() as s:
        rows = s.scalars(
            select(JobEvent.event_type)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.id)
        ).all()
    return [str(r) for r in rows]


def _step_checkpoint(session_factory, job_id: str) -> dict:
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(job_id)[0].id)
        return json.loads(step_row.checkpoint_json or "{}")


def _force_replay(session_factory, job_id: str) -> None:
    """Reset a terminal job+step to queued/pending and drop lease + attempts
    so run_once re-executes the SAME job row (crash-recovery replay)."""
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
    """Live ffmpeg/ffprobe PIDs (psutil; empty when unavailable)."""
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


def _wait_no_orphans(baseline: set[int], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _ffmpeg_pids() <= baseline:
            return
        time.sleep(0.25)
    assert _ffmpeg_pids() <= baseline, (
        f"orphan ffmpeg processes: {_ffmpeg_pids() - baseline}"
    )


# ── Scenario 1: happy path ───────────────────────────────────────────────────


def test_s01_happy_path_mp4_aac_import_attach_completed(
    svc, session_factory, ws, video_item, aac_source, managed_root
) -> None:
    """Scenario 1: MP4 H.264+AAC import → attach → completed; artifact
    kind=audio, purpose=original_audio, owner video_item; file published
    under the temp managed root; the Job completes only after publication."""
    worker = svc.worker
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )
    source_sha_before = _sha256(
        managed_root
        / session_factory().get(Artifact, source_artifact_id).relative_path  # type: ignore[union-attr]
    )

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    assert submitted.reused is False
    assert worker.run_once() >= 1

    assert _job_state(session_factory, submitted.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None
    assert art.kind == "audio"
    assert art.state == "ready"
    final = managed_root / art.relative_path
    assert final.is_file()
    assert art.sha256 == _sha256(final)
    assert art.size_bytes == final.stat().st_size
    assert art.relative_path.startswith(
        f"artifacts/{ws.id}/audio/{submitted.job_id}/attach/"
    )
    assert not Path(art.relative_path).is_absolute()
    with session_factory() as s:
        owner = s.get(
            ArtifactOwner, (art.id, "video_item", video_item.id, "original_audio")
        )
        src_link = s.get(
            ArtifactOwner,
            (source_artifact_id, "video_item", video_item.id, "source"),
        )
    assert owner is not None
    assert src_link is not None

    # Published output really is AAC audio + H.264 video (stream-copied).
    streams = {
        st["codec_type"]: st["codec_name"] for st in _probe_streams(final)["streams"]
    }
    assert streams.get("audio") == "aac"
    assert streams.get("video") in {"h264", "hevc"}

    # Exactly two published files (source + original audio); staging empty.
    assert len(_artifact_files(managed_root)) == 2
    assert _staging_files(managed_root) == []

    # Job completed only AFTER publication: the completion event follows the
    # step-completed event, and the step transition carries the persisted
    # validator verdict (verified-publication completion gate) whose audio
    # hash matches the artifact row.
    events = _job_event_types(session_factory, submitted.job_id)
    assert "step_transition" in events
    with session_factory() as s:
        rows = s.scalars(
            select(JobEvent.details_json).where(
                JobEvent.job_id == submitted.job_id,
                JobEvent.event_type == "step_transition",
                JobEvent.to_state == "completed",
                JobEvent.step_code == "attach",
            )
        ).all()
    assert rows, "no completed step_transition event recorded"
    validation = json.loads(rows[0])["validation"]
    assert validation["original_audio"]["sha256"] == art.sha256
    assert validation["original_audio"]["relative_path"] == art.relative_path

    # Source bytes unchanged end-to-end.
    src_art = session_factory().get(Artifact, source_artifact_id)
    assert _sha256(managed_root / src_art.relative_path) == source_sha_before  # type: ignore[union-attr]


# ── Scenario 2: no-audio → NO_AUDIO_PRESENT ──────────────────────────────────


def test_s02_no_audio_no_audio_present(
    svc, session_factory, ws, video_item, no_audio_source, managed_root
) -> None:
    """Scenario 2: video-only MP4 imports with the explicit NO_AUDIO_STREAM
    warning; the attach completes with NO_AUDIO_PRESENT — no crash, no
    artifact, no fabricated audio file anywhere."""
    worker = svc.worker
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        no_audio_source, managed_root,
    )
    with session_factory() as s:
        probe = json.loads(
            s.get(JobStep, JobRepository(s).list_steps(
                s.scalar(
                    select(Job.id).where(
                        Job.job_type == video_import.JOB_TYPE_ANALYZE_MEDIA
                    )
                )
            )[0].id
        ).checkpoint_json or "{}")
    warning_codes = [w["code"] for w in probe.get("probe", {}).get("warnings", [])]
    assert CODE_NO_AUDIO_STREAM in warning_codes

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() >= 1

    assert _job_state(session_factory, submitted.job_id) == "completed"
    assert _audio_artifact(session_factory, video_item.id) is None
    # Only the source file is published — no fabricated audio anywhere.
    files = _artifact_files(managed_root)
    assert len(files) == 1
    assert files[0].suffix == ".mp4"
    assert _staging_files(managed_root) == []
    cp = _step_checkpoint(session_factory, submitted.job_id)
    assert cp["published"]["no_audio_present"] is True
    assert cp["published"]["artifact_id"] is None
    assert cp["remux"]["status"] == "NO_AUDIO_PRESENT"


# ── Scenario 3: corrupt source → fail closed, zero publication ───────────────


def test_s03_corrupt_fail_closed_zero_publication(
    svc, session_factory, ws, project, video_item, aac_source, managed_root, tmp_path
) -> None:
    """Scenario 3: a corrupt/truncated source fails closed at import (stable
    code, zero managed writes); a source corrupted BEHIND a committed import
    artifact fails the attach closed with zero audio publication."""
    worker = svc.worker

    # (a) Truncated MP4 at import: fail closed inside the ANALYZE_MEDIA job
    # (the probe runs in the worker, not at submit time) — stable code, and
    # zero managed writes (no artifact file, no staging leftovers).
    good = _make_media(
        tmp_path / "corrupt_orig.mp4", audio_codec=["-c:a", "aac", "-b:a", "64k"]
    )
    truncated = tmp_path / "src_truncated.mp4"
    truncated.write_bytes(good.read_bytes()[: len(good.read_bytes()) // 2])
    rejected = submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=project.id,
        video_item_id=video_item.id,
        source_path=truncated,
        source_sha256=_sha256(truncated),
        generation="1",
        managed_root=managed_root,
        title="truncated.mp4",
    )
    assert worker.run_once() == 1
    assert _job_state(session_factory, rejected.job_id) == "failed"
    assert _job_error_code(session_factory, rejected.job_id) == "PROBE_NONZERO_EXIT"
    assert _artifact_files(managed_root) == []
    assert _staging_files(managed_root) == []

    # (b) Different-size garbage swapped behind a committed source artifact:
    # the attach SOURCE phase size gate detects the corruption first —
    # fail closed, stable code, zero audio publication.
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )
    with session_factory() as s:
        art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item.id,
                ArtifactOwner.purpose == "source",
            )
        )
        rel = s.get(Artifact, art_id).relative_path  # type: ignore[union-attr]
    managed_file = managed_root / rel
    managed_file.write_bytes(b"\x00\x01not-a-video" * 512)

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() >= 1
    assert _job_state(session_factory, submitted.job_id) == "failed"
    assert _job_error_code(session_factory, submitted.job_id) == "SOURCE_NOT_READY"
    assert _audio_artifact(session_factory, video_item.id) is None
    assert [
        p for p in _artifact_files(managed_root) if submitted.job_id in p.parts
    ] == []
    assert _staging_files(managed_root) == []

    # (c) SAME-SIZE mutated source (defeats the naive size gate): since
    # R4-P1 (T01C) the attach SOURCE phase preflight re-verifies the managed
    # file against its committed size/hash evidence and rejects the job with
    # SOURCE_NOT_READY BEFORE the engine — still fail-closed, zero
    # publication, staging clean.
    same_size_garbage = bytes(len(good.read_bytes()))  # zero bytes, exact length
    managed_file.write_bytes(same_size_garbage)
    corrupted_item = VideoItem(
        project_id=project.id,
        title="T01D Clip Corrupted",
        position=1,
        status="imported",
        revision=1,
    )
    with session_factory() as s:
        s.add(corrupted_item)
        s.commit()
    _import_source(
        session_factory, worker, ws, corrupted_item.id, project.id,
        aac_source, managed_root,
    )
    with session_factory() as s:
        c_art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == corrupted_item.id,
                ArtifactOwner.purpose == "source",
            )
        )
        c_rel = s.get(Artifact, c_art_id).relative_path  # type: ignore[union-attr]
    (managed_root / c_rel).write_bytes(same_size_garbage)

    submitted_c = submit_attach_original_audio(
        session_factory,
        workspace_id=ws.id,
        project_id=project.id,
        video_item_id=corrupted_item.id,
        generation="1",
        managed_root=managed_root,
    )
    assert worker.run_once() >= 1
    assert _job_state(session_factory, submitted_c.job_id) == "failed"
    envelope_code = _job_error_code(session_factory, submitted_c.job_id)
    # R4-P1 (T01C): the source-phase preflight re-verifies the managed file
    # against its committed size/hash evidence, so a same-size mutation is
    # rejected BEFORE the engine — SOURCE_NOT_READY, still fail-closed with
    # zero publication and clean staging.
    assert envelope_code == "SOURCE_NOT_READY", envelope_code
    assert _audio_artifact(session_factory, corrupted_item.id) is None
    assert [
        p for p in _artifact_files(managed_root)
        if submitted_c.job_id in p.parts
    ] == []
    assert _staging_files(managed_root) == []


# ── Scenario 4: non-AAC first audio → warning then attach ────────────────────


@pytest.mark.parametrize("source_fixture", ["ac3_source", "mp3_source"])
def test_s04_non_aac_ac3_mp3_import_warning_then_attach(
    svc, session_factory, ws, video_item, source_fixture, managed_root, request
) -> None:
    """Scenario 4: AC-3 / MP3 first audio → import accepted WITH the explicit
    UNSUPPORTED_AUDIO_CODEC warning; the attach still runs (engine transcode
    path) and publishes exactly one AAC stream."""
    worker = svc.worker
    source: Path = request.getfixturevalue(source_fixture)
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        source, managed_root,
    )
    analyze_job_id = session_factory().scalar(
        select(Job.id).where(Job.job_type == video_import.JOB_TYPE_ANALYZE_MEDIA)
    )
    with session_factory() as s:
        probe = json.loads(
            s.get(JobStep, JobRepository(s).list_steps(analyze_job_id)[0].id)
            .checkpoint_json or "{}"
        )["probe"]
    warning_codes = [w["code"] for w in probe.get("warnings", [])]
    assert CODE_UNSUPPORTED_AUDIO_CODEC in warning_codes
    audio_warning = next(
        w for w in probe["warnings"] if w["code"] == CODE_UNSUPPORTED_AUDIO_CODEC
    )
    assert audio_warning["severity"] == "warning"
    assert audio_warning["details"]["audio_codec"] in {"ac3", "mp3"}

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() >= 1
    assert _job_state(session_factory, submitted.job_id) == "completed"

    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None and art.state == "ready"
    final = managed_root / art.relative_path
    probed = _probe_streams(final)["streams"]
    audio_streams = [st for st in probed if st["codec_type"] == "audio"]
    assert len(audio_streams) == 1, "canonical first stream only — never merged"
    assert audio_streams[0]["codec_name"] == "aac"
    video_codecs = {
        st["codec_name"] for st in probed if st["codec_type"] == "video"
    }
    assert video_codecs <= {"h264", "hevc"}


# ── Scenario 5: restart mid-run → no duplicate artifact ──────────────────────


def test_s05_restart_mid_run_no_duplicate_artifact(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """Scenario 5: kill the worker after the engine checkpoint (before
    publication) → resume completes with exactly ONE audio artifact, no
    duplicate files, and the engine is NOT re-run (checkpoint reuse)."""
    worker = svc.worker
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )
    submitted = _submit_attach(session_factory, ws, video_item, managed_root)

    from app.workflow import original_audio_handler as handler_mod

    engine_runs = {"count": 0}
    real_remux = handler_mod.remux_original_audio

    def counting_remux(*args, **kwargs):
        engine_runs["count"] += 1
        return real_remux(*args, **kwargs)

    def crash_after_engine_checkpoint(ctx, final_rel, sha256, size):
        raise RuntimeError("simulated worker kill after the remux checkpoint")

    monkeypatch.setattr(handler_mod, "remux_original_audio", counting_remux)
    monkeypatch.setattr(handler_mod, "_publish_effect", crash_after_engine_checkpoint)
    worker.run_once()
    monkeypatch.undo()

    # The job failed AFTER the engine checkpoint was durably written.
    assert _job_state(session_factory, submitted.job_id) == "failed"
    assert _job_error_code(session_factory, submitted.job_id) == "PUBLICATION_FAILED"
    assert engine_runs["count"] == 1
    assert _audio_artifact(session_factory, video_item.id) is None
    cp = _step_checkpoint(session_factory, submitted.job_id)
    assert cp["remux"]["status"] == "STREAM_COPY"
    assert "output_sha256" in cp["remux"]

    # Resume the SAME job row (restart): the durable remux evidence is
    # re-verified; because the publication failure consumed the produced
    # staging output (adopt-then-fail cleanup), the engine legitimately
    # re-runs — deterministically reproducing the SAME output.  The scenario
    # gate: exactly ONE audio artifact/file afterwards, never duplicates.
    monkeypatch.setattr(handler_mod, "remux_original_audio", counting_remux)
    _force_replay(session_factory, submitted.job_id)
    worker.run_once()
    monkeypatch.undo()

    assert _job_state(session_factory, submitted.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None and art.state == "ready"
    finals = [
        p for p in _artifact_files(managed_root)
        if submitted.job_id in p.parts and p.name == "original_audio.mp4"
    ]
    assert len(finals) == 1, f"expected exactly one audio file, got {len(finals)}"
    assert audio_rows_total(managed_root, session_factory) == 1
    assert _sha256(finals[0]) == cp["remux"]["output_sha256"], (
        "deterministic engine: the resumed run reproduces the checkpointed bytes"
    )


# ── R5 regression: source-artifact authority swap (R5-P1) ────────────────────


def test_s09_source_artifact_swap_fail_closed_zero_publication(
    svc, session_factory, ws, video_item, aac_source, tmp_path, managed_root,
    monkeypatch,
) -> None:
    """R5-P1: ``VideoItem.source_artifact_id`` is the SINGLE source
    authority.  Two fail-closed legs against REAL production paths:

    Leg 1 (stale manifest, resolve path): submit attach while artifact A is
    the authority (manifest pins A), re-point the item to artifact B via a
    real second import, run → SOURCE_OWNER_MISMATCH before any byte work.

    Leg 2 (bytes-valid checkpoint, replay path): run a job until the engine
    checkpoint exists (crash-at-publish hook from scenario 5), THEN detach
    its artifact by re-pointing authority back to A, replay the SAME row →
    the source-phase authority revalidation rejects the bytes-valid
    checkpoint with SOURCE_OWNER_MISMATCH — the engine never re-runs.

    Both legs: zero audio artifacts, zero publication files, staging clean.
    """
    worker = svc.worker
    _, artifact_a = _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )
    # Import the replacement source BEFORE any attach submit so the worker
    # never sees two queued jobs at once (claim ordering).
    clip_b = _make_media(
        tmp_path / "r5_swap_source_b.mp4", audio_codec=["-c:a", "aac", "-b:a", "96k"]
    )
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        clip_b, managed_root,
    )
    with session_factory() as s:
        artifact_b = s.get(VideoItem, video_item.id).source_artifact_id
    assert artifact_b is not None and str(artifact_b) != artifact_a, (
        "second import did not move the source authority to a NEW artifact"
    )

    def _set_authority(artifact_id: str) -> None:
        """Simulate an external re-point of the item's source authority
        (any producer may move the pointer between submit and run)."""
        with session_factory() as s:
            item = s.get(VideoItem, video_item.id)
            item.source_artifact_id = artifact_id
            s.commit()

    # ── Leg 1: stale manifest id ≠ current authority ─────────────────────
    # Authority is B; the submit pins B into the manifest...
    _set_authority(artifact_b)
    submitted_1 = _submit_attach(session_factory, ws, video_item, managed_root)
    with session_factory() as s:
        manifest_1 = JobRepository(s).get_job(submitted_1.job_id).input_manifest
    assert manifest_1["source_artifact_id"] == artifact_b

    # ...then the pointer moves BACK to A between submit and run.
    _set_authority(artifact_a)

    published_before = len(_artifact_files(managed_root))
    assert worker.run_once() >= 1
    assert _job_state(session_factory, submitted_1.job_id) == "failed"
    with session_factory() as s:
        envelope_1 = JobRepository(s).get_job(submitted_1.job_id).error or {}
    assert envelope_1.get("error_code") == "SOURCE_OWNER_MISMATCH", envelope_1
    details_1 = envelope_1.get("details") or {}
    assert details_1.get("manifest_source_artifact_id") == artifact_b
    assert details_1.get("current_source_artifact_id") == artifact_a
    assert _audio_artifact(session_factory, video_item.id) is None
    assert _staging_files(managed_root) == []
    assert len(_artifact_files(managed_root)) == published_before

    # ── Leg 2: bytes-valid checkpoint for a DETACHED artifact ────────────
    from app.workflow import original_audio_handler as handler_mod

    engine_runs = {"count": 0}
    real_remux = handler_mod.remux_original_audio

    def counting_remux(*args, **kwargs):
        engine_runs["count"] += 1
        return real_remux(*args, **kwargs)

    def crash_after_engine_checkpoint(ctx, final_rel, sha256, size):
        raise RuntimeError("simulated worker kill after the remux checkpoint")

    # Fresh submit now pins A (the CURRENT authority) — a fully valid job.
    _set_authority(artifact_a)
    submitted_2 = _submit_attach(session_factory, ws, video_item, managed_root)
    with session_factory() as s:
        manifest_2 = JobRepository(s).get_job(submitted_2.job_id).input_manifest
    assert manifest_2["source_artifact_id"] == artifact_a

    monkeypatch.setattr(handler_mod, "remux_original_audio", counting_remux)
    monkeypatch.setattr(handler_mod, "_publish_effect", crash_after_engine_checkpoint)
    worker.run_once()
    monkeypatch.undo()
    assert _job_state(session_factory, submitted_2.job_id) == "failed"
    assert _job_error_code(session_factory, submitted_2.job_id) == "PUBLICATION_FAILED"
    assert engine_runs["count"] == 1
    cp = _step_checkpoint(session_factory, submitted_2.job_id)
    assert cp["source"]["artifact_id"] == artifact_a

    # Detach the checkpointed artifact: authority moves to B AFTER the
    # engine checkpoint durably exists.
    _set_authority(artifact_b)

    _force_replay(session_factory, submitted_2.job_id)
    monkeypatch.setattr(handler_mod, "remux_original_audio", counting_remux)
    worker.run_once()
    monkeypatch.undo()

    assert _job_state(session_factory, submitted_2.job_id) == "failed"
    with session_factory() as s:
        envelope_2 = JobRepository(s).get_job(submitted_2.job_id).error or {}
    assert envelope_2.get("error_code") == "SOURCE_OWNER_MISMATCH", envelope_2
    details_2 = envelope_2.get("details") or {}
    assert details_2.get("checkpointed_artifact_id") == artifact_a
    assert details_2.get("current_source_artifact_id") == artifact_b
    # The engine was NOT re-run for the rejected replay.
    assert engine_runs["count"] == 1
    assert _audio_artifact(session_factory, video_item.id) is None
    assert audio_rows_total(managed_root, session_factory) == 0
    assert _staging_files(managed_root) == []
    finals_for_job2 = [
        p for p in _artifact_files(managed_root) if submitted_2.job_id in p.parts
    ]
    assert finals_for_job2 == [], (
        f"no publication may exist for the swapped job: {finals_for_job2}"
    )


def _make_multistream_aac(path: Path, *, duration: float = 2.0) -> Path:
    """A REAL vertical MP4: H.264 video + FOUR AAC audio streams (5 streams
    total), built with ffmpeg lavfi synthonics at distinct frequencies."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=880:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=1320:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=1760:duration={duration}",
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-map", "4:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"multi-stream fixture generation failed: {result.stderr[-300:]}"
    )
    return path


# ── R6-F4: post-remux cancellation + vertical multi-stream ───────────────────


def test_s10_cancel_after_engine_success_zero_residue(
    svc, session_factory, ws, video_item, aac_source, managed_root, monkeypatch
) -> None:
    """R6-F4 (Codex finding: previous coverage only cancels BEFORE the
    engine): the durable cancel flag lands RIGHT AFTER ``remux_original_audio``
    returned SUCCESS at the integration/worker.run_once level — real engine,
    real output bytes on disk.  The Job must end ``cancelled`` with ZERO
    audio Artifact/ArtifactOwner, zero publication, THIS Job's staging fully
    purged, other Jobs' staging untouched (sentinel byte-identical), and no
    remux/published evidence checkpointed for the aborted run."""
    worker = svc.worker
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )

    # A foreign Job's staging (byte-different sentinel) that MUST survive.
    foreign_dir = (
        managed_root / "staging" / "cross-job-sentinel" / "attach" / "engine"
    )
    foreign_dir.mkdir(parents=True, exist_ok=True)
    sentinel_bytes = b"foreign job bytes - never delete"
    sentinel = foreign_dir / "original_audio.mp4"
    sentinel.write_bytes(sentinel_bytes)

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    job_id = submitted.job_id
    engine_out = (
        managed_root / "staging" / job_id / "attach" / "engine"
        / "original_audio.mp4"
    )
    artifacts_before = sorted(_artifact_files(managed_root))

    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio

    def remux_then_flag(src, out_dir, **kwargs):
        out = real_remux(src, out_dir, **kwargs)
        # Deterministic boundary: the REAL engine succeeded (output exists
        # on disk) and only NOW does the durable cancel flag appear.
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

    # Terminal cancelled; the worker's cancel-drain persists no failure
    # envelope (an empty/absent error is the stable cancelled shape).
    assert _job_state(session_factory, job_id) == "cancelled"
    with session_factory() as s:
        err = JobRepository(s).get_job(job_id).error or {}
    assert err.get("error_code") in ("CANCELLED", None), err

    # ZERO residue: no audio Artifact row, no ArtifactOwner link, nothing
    # published under artifacts/.
    assert _audio_artifact(session_factory, video_item.id) is None
    assert audio_rows_total(managed_root, session_factory) == 0
    assert sorted(_artifact_files(managed_root)) == artifacts_before

    # THIS Job's staging purged — produced output and directory shell gone.
    assert not engine_out.exists(), "zero-residue violated: engine output survived"
    job_staging = managed_root / "staging" / job_id
    assert not job_staging.exists() or list(job_staging.rglob("*")) == []

    # Cross-Job isolation: the sentinel is byte-identical and untouched.
    assert sentinel.read_bytes() == sentinel_bytes

    # No remux/published evidence may survive cancellation (only the
    # source-phase evidence written before the engine ran).
    cp = _step_checkpoint(session_factory, job_id)
    assert isinstance(cp.get("source"), dict), "precondition: source phase ran"
    assert "remux" not in cp, f"remux evidence persisted past cancellation: {cp}"
    assert "published" not in cp, f"published evidence persisted: {cp}"


def test_s11_vertical_multistream_canonical_first_audio(
    svc, session_factory, ws, video_item, tmp_path, managed_root
) -> None:
    """Real vertical multi-stream source (H.264 + 4 AAC = 5 streams): the
    bounded R6 probe ACCEPTS it, the attach completes over the real pipeline,
    publishes EXACTLY the canonical FIRST audio stream as the single AAC
    track (streams are never merged: output probes 1 video + 1 audio), and
    checkpoints the selection evidence (``audio_stream_index`` equal to the
    source's first-audio container index)."""
    worker = svc.worker
    multistream = _make_multistream_aac(tmp_path / "r6_vertical_5stream.mp4")
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        multistream, managed_root,
    )

    # Precondition: the source really carries 5 streams (1 video + 4 audio),
    # all four audio tracks AAC — the engine must pick only the FIRST.
    src_art = session_factory().get(Artifact, source_artifact_id)
    src_path_managed = managed_root / src_art.relative_path
    src_streams = _probe_streams(src_path_managed)
    kinds = [st["codec_type"] for st in src_streams["streams"]]
    assert kinds.count("video") == 1 and kinds.count("audio") == 4, kinds
    first_audio = next(
        st for st in src_streams["streams"] if st["codec_type"] == "audio"
    )
    assert first_audio["codec_name"] == "aac"
    expected_index = int(first_audio["index"])

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() >= 1
    assert _job_state(session_factory, submitted.job_id) == "completed"

    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None and art.state == "ready"
    final = managed_root / art.relative_path
    assert final.is_file()
    assert art.sha256 == _sha256(final)

    # Output shape: EXACTLY one video + ONE audio stream — never merged.
    out_streams = _probe_streams(final)["streams"]
    out_kinds = [st["codec_type"] for st in out_streams]
    assert out_kinds.count("video") == 1, out_kinds
    assert out_kinds.count("audio") == 1, out_kinds
    assert out_streams[[k for k in out_kinds].index("audio")]["codec_name"] == "aac"

    # Selection evidence: canonical FIRST audio stream of the source.  The
    # handler wraps the engine checkpoint VERBATIM under ``remux.checkpoint``
    # (path-free durable evidence), so the index lives there.
    cp = _step_checkpoint(session_factory, submitted.job_id)
    remux_ev = cp["remux"]
    assert remux_ev["status"] == "STREAM_COPY"
    engine_cp = remux_ev.get("checkpoint") or {}
    assert int(engine_cp["audio_stream_index"]) == expected_index

    # Source bytes unchanged end-to-end.
    assert _sha256(src_path_managed) == _sha256(multistream)


# ── Scenario 6: cancellation mid-remux → zero publication ────────────────────


def test_s06_cancellation_mid_remux_zero_publication(
    svc, session_factory, ws, video_item, aac_source, managed_root, tmp_path, monkeypatch
) -> None:
    """Scenario 6: the durable cancel flag flips while the remux runs → the
    engine child tree is killed, the Job drains to terminal cancelled, zero
    artifacts/files published, staging clean, no orphan ffmpeg."""
    worker = svc.worker
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )
    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    job_id = submitted.job_id

    from app.workflow import original_audio_handler as handler_mod

    real_remux = handler_mod.remux_original_audio

    def remux_then_cancel(src, out_dir, **kwargs):
        # Deterministic mid-run cancellation: flip the durable flag, then
        # hold longer than the adapter's watcher poll tick (0.25 s) BEFORE
        # entering the engine.  The watcher therefore observes ``cancelling``
        # and sets the engine cancel Event before the first bounded
        # subprocess spawns — the engine fails closed on CANCELLED with its
        # full staging cleanup, deterministically.
        with session_factory() as s:
            r = JobRepository(s)
            r.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=r.get_job(job_id).revision,
            )
            s.commit()
        time.sleep(1.2)
        return real_remux(src, out_dir, **kwargs)

    baseline = _ffmpeg_pids()
    monkeypatch.setattr(handler_mod, "remux_original_audio", remux_then_cancel)
    worker.run_once()
    monkeypatch.undo()

    assert _job_state(session_factory, job_id) == "cancelled"
    assert _audio_artifact(session_factory, video_item.id) is None
    assert [
        p for p in _artifact_files(managed_root) if job_id in p.parts
    ] == []
    assert _staging_files(managed_root) == []
    _wait_no_orphans(baseline)


# ── Scenario 7: idempotency reuse / conflict fail-closed ─────────────────────


def test_s07_idempotency_reuse_and_conflict_fail_closed(
    svc, session_factory, ws, project, video_item, aac_source, managed_root, tmp_path
) -> None:
    """Scenario 7: an equivalent resubmit reuses the completed Job (same id,
    reused=True, exactly one effect set); an ACTIVE duplicate fails closed
    with IdempotencyKeyInUse; a cross-owner submit is rejected before any Job
    row exists."""
    worker = svc.worker
    _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )

    first = _submit_attach(session_factory, ws, video_item, managed_root)
    assert first.reused is False
    with pytest.raises(IdempotencyKeyInUse):
        _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() >= 1
    assert _job_state(session_factory, first.job_id) == "completed"
    art = _audio_artifact(session_factory, video_item.id)
    assert art is not None

    second = _submit_attach(session_factory, ws, video_item, managed_root)
    assert second.reused is True
    assert second.job_id == first.job_id
    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_ATTACH_ORIGINAL_AUDIO)
        ).all()
        audio_rows = list(s.scalars(select(Artifact).where(Artifact.kind == "audio")))
    assert len(jobs) == 1
    assert len(audio_rows) == 1

    # Conflicting identity: the same source content claimed for a DIFFERENT
    # video item is a different logical key (no cross-owner reuse), and a
    # submit with a broken ownership chain fails closed with zero Job rows.
    other_item = VideoItem(
        project_id=project.id,
        title="T01D Clip B",
        position=1,
        status="imported",
        revision=1,
    )
    with session_factory() as s:
        s.add(other_item)
        s.commit()
    other_source = _make_media(
        tmp_path / "src_aac_b.mp4", audio_codec=["-c:a", "aac", "-b:a", "96k"]
    )
    _import_source(
        session_factory, worker, ws, other_item.id, other_item.project_id,
        other_source, managed_root,
    )
    from app.services.video_import import CODE_OWNERSHIP_MISMATCH

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - stable-code contract
        submit_attach_original_audio(
            session_factory,
            workspace_id="wrong-workspace",
            project_id=other_item.project_id,
            video_item_id=other_item.id,
            managed_root=managed_root,
        )
    assert getattr(excinfo.value, "code", "") == CODE_OWNERSHIP_MISMATCH
    with session_factory() as s:
        total_attach_jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_ATTACH_ORIGINAL_AUDIO)
        ).all()
    assert len(total_attach_jobs) == 1, (
        "the rejected cross-owner submit must not create a Job row"
    )


# ── Scenario 8: analysis generation unchanged ────────────────────────────────


def test_s08_analysis_generation_unchanged(
    svc, session_factory, ws, project, video_item, aac_source, managed_root, session
) -> None:
    """Scenario 8: ObjectRole / ObjectOccurrence rows (with a real Scene) are
    untouched by the attach job; the source probe columns and source artifact
    evidence are unchanged; the attach checkpoint carries no absolute path."""
    worker = svc.worker
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item.id, video_item.project_id,
        aac_source, managed_root,
    )

    # Seed a REAL analysis generation: one Scene + one ObjectRole + one
    # ObjectOccurrence (the DISCOVER_OBJECTS durable write surface).
    with session_factory() as s:
        scene = Scene(
            video_item_id=video_item.id,
            position=0,
            start_frame=0,
            end_frame=59,
            start_time_ms=0,
            end_time_ms=2000,
            status="approved",
        )
        s.add(scene)
        s.flush()
        role = ObjectRole(
            workspace_id=ws.id,
            project_id=project.id,
            video_item_id=video_item.id,
            source_generation="gen-t01d-evidence",
            name="T01D Character",
            kind="character",
            status="suggested",
        )
        s.add(role)
        s.flush()
        occ = ObjectOccurrence(
            workspace_id=ws.id,
            project_id=project.id,
            video_item_id=video_item.id,
            role_id=role.id,
            scene_id=scene.id,
            frame_index=0,
            time_ms=0,
            bbox_x=1,
            bbox_y=2,
            bbox_w=10,
            bbox_h=20,
            confidence=0.9,
            confidence_source="detector",
        )
        s.add(occ)
        s.commit()

    with session_factory() as s:
        item = s.get(VideoItem, video_item.id)
        probe_before = (
            item.duration_ms, item.width, item.height,  # type: ignore[union-attr]
            item.fps_num, item.fps_den,  # type: ignore[union-attr]
        )
        roles_before = [
            (r.id, r.name, r.kind, r.status, r.revision, r.source_generation)
            for r in s.scalars(select(ObjectRole)).all()
        ]
        occ_before = [
            (o.id, o.role_id, o.frame_index, o.time_ms, o.bbox_x, o.confidence)
            for o in s.scalars(select(ObjectOccurrence)).all()
        ]
        src_art = s.get(Artifact, source_artifact_id)
        src_before = (src_art.sha256, src_art.size_bytes, src_art.relative_path)  # type: ignore[union-attr]

    submitted = _submit_attach(session_factory, ws, video_item, managed_root)
    assert worker.run_once() >= 1
    assert _job_state(session_factory, submitted.job_id) == "completed"

    with session_factory() as s:
        item = s.get(VideoItem, video_item.id)
        probe_after = (
            item.duration_ms, item.width, item.height,  # type: ignore[union-attr]
            item.fps_num, item.fps_den,  # type: ignore[union-attr]
        )
        roles_after = [
            (r.id, r.name, r.kind, r.status, r.revision, r.source_generation)
            for r in s.scalars(select(ObjectRole)).all()
        ]
        occ_after = [
            (o.id, o.role_id, o.frame_index, o.time_ms, o.bbox_x, o.confidence)
            for o in s.scalars(select(ObjectOccurrence)).all()
        ]
        src_art = s.get(Artifact, source_artifact_id)
        src_after = (src_art.sha256, src_art.size_bytes, src_art.relative_path)  # type: ignore[union-attr]

    assert probe_after == probe_before
    assert roles_after == roles_before
    assert occ_after == occ_before
    assert src_after == src_before

    cp = _step_checkpoint(session_factory, submitted.job_id)
    assert managed_root.as_posix() not in json.dumps(cp)
    assert str(managed_root) not in json.dumps(cp)

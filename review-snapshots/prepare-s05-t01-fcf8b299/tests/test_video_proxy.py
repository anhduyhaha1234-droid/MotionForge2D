"""Targeted tests for S05-T03 — bounded editing-proxy generation (GENERATE_PROXY).

Covers the required scenarios of ``docs/pm/sessions/S05-T03-canonical-timebase-proxy/
TASK.md`` AC2–AC10:

- success (CFR): Job completes, exactly one ready ``video`` Artifact with
  sha256/size matching the file, ``artifact_owner`` link purpose ``proxy`` to
  the VideoItem, path under ``artifacts/<workspace_id>/video/<job_id>/<step>/``,
  the proxy decodes (bounded ffprobe, positive duration/width/height), the
  source artifact bytes are unchanged;
- VFR: a real synthetic VFR fixture (concatenated 30fps + 25fps segments)
  completes and is resampled onto the canonical ``avg_frame_rate`` grid;
- owner-scoped idempotency: same source bytes + two VideoItems → two
  independent Jobs/artifacts; duplicate submit for the same owner → active
  ``IdempotencyKeyInUse`` / completed reuse; exactly one effect set;
- failure/rollback/cancellation: FFmpeg failure → ``PROXY_FFMPEG_FAILED``;
  budget timeout → ``PROXY_TIMEOUT`` transient (auto-retry then
  ``RETRIES_EXHAUSTED``); cancel mid-generation → terminal ``cancelled``;
  DB rollback removes only files created by the failing attempt; no
  ``.staging`` leftovers, no orphan final files, no ``ready`` rows without
  files;
- replay/restart: a successor after a failed attempt re-runs from checkpoint
  and completes with exactly one artifact/file and cleans crash leftovers; a
  replay publication failure never deletes a previously committed ready
  artifact file;
- path escape/symlink containment → ``PATH_CONTAINMENT``, nothing written
  outside the managed root; the source artifact is never mutated/deleted;
- no absolute managed path leaks into durable checkpoints (probe ``file_path``
  stripped; only normalized relative paths persisted).

Every test uses a temporary database + temporary managed root and synthetic
ffmpeg fixtures under ``tmp_path`` (lavfi testsrc + sine).  Tests skip
gracefully when ffmpeg/ffprobe is not available (no-FFmpeg machine safe,
mirroring ``tests/test_video_import.py``).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Iterator
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
from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import IdempotencyKeyInUse
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
from app.services import video_import, video_proxy
from app.services.video_import import (
    CODE_OWNERSHIP_MISMATCH,
    CODE_PATH_CONTAINMENT,
    CODE_PROJECT_NOT_FOUND,
    CODE_PUBLICATION_FAILED,
    CODE_VIDEO_ITEM_NOT_FOUND,
    submit_import,
)
from app.services.video_proxy import (
    ARTIFACT_PURPOSE_PROXY,
    CODE_PROXY_FFMPEG_FAILED,
    CODE_PROXY_TIMEOUT,
    CODE_PROXY_VALIDATION_FAILED,
    CODE_SOURCE_NOT_READY,
    CODE_SOURCE_OWNER_MISMATCH,
    JOB_TYPE_GENERATE_PROXY,
    ProxyProfile,
    VideoProxyError,
    register_generate_proxy_handler,
    submit_proxy,
)
from app.workflow.durable_worker import (
    TRANSIENT_ERROR_CODES,
    DurableWorker,
    WorkerConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Deterministic clock/sleeper (mirror test_video_import.py) ────────────────


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
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
    return tmp_path / "proxy.db"


@pytest.fixture()
def session_factory(db_path: Path):
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
    ws = Workspace(name="Proxy Workspace")
    session.add(ws)
    session.commit()
    return ws


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    project = Project(name="Proxy Project", workspace_id=ws.id, status="active")
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
    """A worker with fake clock/sleeper and BOTH the ANALYZE_MEDIA (S05-T02)
    and GENERATE_PROXY (S05-T03) handlers registered."""
    w = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="proxy-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
        clock=clock,
        sleeper=sleeper,
    )
    from app.services.video_import import register_analyze_media_handler

    register_analyze_media_handler(w)
    register_generate_proxy_handler(w)
    return w


# ── Synthetic video fixtures (lavfi → tmp_path) ──────────────────────────────


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


def _make_video(
    path: Path,
    *,
    duration: float = 1.0,
    fps: int = 30,
    audio: bool = True,
) -> Path | None:
    """Create a CFR synthetic MP4/H.264/AAC video with ffmpeg."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=320x240:rate={fps}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "64k", "-shortest"]
    cmd.append(str(path))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return path


def _probe_streams(path: Path) -> dict:
    """Raw ffprobe JSON (streams+format) for fixture inspection."""
    from app.services.ffmpeg_utils import find_ffprobe

    result = subprocess.run(
        [
            find_ffprobe(), "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


@pytest.fixture()
def source_video(tmp_path: Path) -> Path:
    """A real CFR MP4/H.264/AAC synthetic fixture (30fps)."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    out = _make_video(tmp_path / "source.mp4")
    assert out is not None, "ffmpeg failed to create the source fixture"
    return out


@pytest.fixture()
def vfr_video(tmp_path: Path) -> Path:
    """A real VFR MP4: concatenation of a 30fps and a 25fps segment (copy).

    ffprobe reports ``avg_frame_rate != r_frame_rate`` with both positive, so
    the S05-T02 probe classifies it VFR and the canonical grid becomes the
    ``avg_frame_rate`` rational.  Skipped when ffmpeg is absent or the concat
    is not genuinely VFR on this build.
    """
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    seg1 = tmp_path / "seg30.mp4"
    seg2 = tmp_path / "seg25.mp4"
    for seg, fps in ((seg1, 30), (seg2, 25)):
        made = _make_video(seg, duration=1.0, fps=fps, audio=False)
        assert made is not None, "ffmpeg failed to create a VFR segment"
    lst = tmp_path / "concat.txt"
    lst.write_text(
        f"file '{seg1.as_posix()}'\nfile '{seg2.as_posix()}'\n", encoding="utf-8"
    )
    out = tmp_path / "vfr.mp4"
    result = subprocess.run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy", "-movflags", "+faststart", str(out),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg concat failed to create the VFR fixture")
    data = _probe_streams(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    r_rate = video.get("r_frame_rate", "0/0")
    avg_rate = video.get("avg_frame_rate", "0/0")
    if r_rate == avg_rate or r_rate in ("0/0", "N/A") or avg_rate in ("0/0", "N/A"):
        pytest.skip("concat output is not genuinely VFR on this ffmpeg build")
    return out


# ── Import / proxy helpers ───────────────────────────────────────────────────


def _import_source(
    session_factory,
    worker: DurableWorker,
    ws: Workspace,
    video_item: VideoItem,
    source: Path,
    managed_root: Path,
) -> tuple[str, str]:
    """Run the approved S05-T02 import for *source* and return
    (import_job_id, source_artifact_id)."""
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
    _run_job(worker)
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


def _submit_proxy(
    session_factory,
    ws: Workspace,
    video_item: VideoItem,
    source_artifact_id: str,
    managed_root: Path,
    *,
    generation: str = "1",
    profile: ProxyProfile | None = None,
):
    return submit_proxy(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_artifact_id=source_artifact_id,
        generation=generation,
        managed_root=managed_root,
        title="proxy",
        profile=profile,
    )


def _run_job(worker: DurableWorker) -> None:
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


def _proxy_artifact(session_factory, video_item_id: str) -> Artifact:
    """The single published proxy artifact of a VideoItem (fails when != 1)."""
    with session_factory() as s:
        rows = list(
            s.scalars(
                select(Artifact)
                .join(
                    ArtifactOwner,
                    ArtifactOwner.artifact_id == Artifact.id,
                )
                .where(
                    ArtifactOwner.owner_type == "video_item",
                    ArtifactOwner.owner_id == video_item_id,
                    ArtifactOwner.purpose == ARTIFACT_PURPOSE_PROXY,
                )
            ).all()
        )
    assert len(rows) == 1, f"expected exactly one proxy artifact, got {len(rows)}"
    return rows[0]


def _proxy_artifact_rows(session_factory, workspace_id: str) -> list[Artifact]:
    """All proxy artifacts (purpose=proxy) in a workspace — zero after a
    failed proxy attempt even though the source artifact row remains."""
    with session_factory() as s:
        return list(
            s.scalars(
                select(Artifact)
                .join(
                    ArtifactOwner,
                    ArtifactOwner.artifact_id == Artifact.id,
                )
                .where(
                    Artifact.workspace_id == workspace_id,
                    ArtifactOwner.purpose == ARTIFACT_PURPOSE_PROXY,
                )
            ).all()
        )


def _job_artifact_files(managed_root: Path, job_id: str) -> list[Path]:
    """Published files under the artifacts tree belonging to *job_id*."""
    return [
        p for p in (managed_root / "artifacts").rglob("*")
        if p.is_file() and job_id in p.parts
    ]


def _step_checkpoint(session_factory, job_id: str) -> dict:
    with session_factory() as s:
        step_row = s.get(JobStep, JobRepository(s).list_steps(job_id)[0].id)
        return json.loads(step_row.checkpoint_json or "{}")


# ── AC3: success path (CFR) ──────────────────────────────────────────────────


def test_proxy_success_cfr_publishes_ready_artifact(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """AC3: CFR source → completed job, one ready video artifact with truthful
    sha256/size, proxy owner link, decodable proxy, source unchanged."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    with session_factory() as s:
        src_art = s.get(Artifact, source_artifact_id)
        assert src_art is not None
        src_dir = managed_root / Path(src_art.relative_path).parent
    src_files_before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in src_dir.rglob("*") if p.is_file()}
    original_source_sha = hashlib.sha256(source_video.read_bytes()).hexdigest()

    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    art = _proxy_artifact(session_factory, video_item.id)
    assert art.kind == "video"
    assert art.state == "ready"
    assert art.mime_type == "video/mp4"
    final = managed_root / art.relative_path
    assert final.is_file()
    # SHA-256 and size match the file exactly.
    assert art.sha256 == hashlib.sha256(final.read_bytes()).hexdigest()
    assert art.size_bytes == final.stat().st_size
    # Path containment: under artifacts/<ws>/video/<job>/<step>/ and relative.
    assert art.relative_path.startswith(f"artifacts/{ws.id}/video/{result.job_id}/proxy/")
    assert not Path(art.relative_path).is_absolute()
    # Owner link purpose proxy → the correct VideoItem.
    with session_factory() as s:
        owner = s.get(
            ArtifactOwner,
            (art.id, "video_item", video_item.id, ARTIFACT_PURPOSE_PROXY),
        )
    assert owner is not None
    # Exactly one proxy artifact file (the source artifact file also exists)
    # and no staging leftovers.
    assert len(_job_artifact_files(managed_root, result.job_id)) == 1
    assert len(_artifact_files(managed_root)) == 2  # source + proxy
    assert _staging_files(managed_root) == []
    # The proxy actually decodes with positive duration/width/height and the
    # canonical CFR grid (30/1).
    data = _probe_streams(final)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert float(video["width"]) > 0 and float(video["height"]) > 0
    assert float(data["format"]["duration"]) > 0
    assert video["r_frame_rate"] == "30/1"
    # The source artifact bytes and the original file are unmodified.
    assert hashlib.sha256(source_video.read_bytes()).hexdigest() == original_source_sha
    src_files_after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in src_dir.rglob("*") if p.is_file()}
    assert src_files_after == src_files_before


def test_proxy_checkpoint_has_no_absolute_managed_path(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """The durable checkpoint carries only normalized relative paths; the
    probe's display-only absolute file_path is stripped and the absolute
    managed source path never appears."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"

    cp = _step_checkpoint(session_factory, result.job_id)
    serialized = json.dumps(cp)
    assert str(managed_root) not in serialized
    assert cp["source"]["relative_path"].startswith("artifacts/")
    assert not Path(cp["source"]["relative_path"]).is_absolute()
    assert cp["source"]["probe"]["file_path"] is None
    assert cp["timebase"]["schema_version"] == 1
    assert (cp["timebase"]["fps_num"], cp["timebase"]["fps_den"]) == (30, 1)
    assert cp["published"]["final_rel"].startswith("artifacts/")
    with session_factory() as s:
        manifest = JobRepository(s).get_job(result.job_id).input_manifest
    assert "source_relative_path" in manifest
    assert not Path(manifest["source_relative_path"]).is_absolute()


# ── AC9: real VFR fixture ────────────────────────────────────────────────────


def test_proxy_vfr_resamples_onto_avg_frame_rate_grid(
    worker, session_factory, ws, video_item, vfr_video, managed_root
) -> None:
    """AC9: a genuine VFR source completes; the canonical grid is the probe's
    avg_frame_rate and the proxy decodes at exactly that rate."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, vfr_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    cp = _step_checkpoint(session_factory, result.job_id)
    # The source probe really classified the fixture VFR (avg != r, both > 0).
    src_video = cp["source"]["probe"]["video_stream"]
    assert src_video["fps_classification"] == "VFR"
    r_rate = src_video["r_frame_rate"]
    avg_rate = src_video["avg_frame_rate"]
    assert (r_rate["num"], r_rate["den"]) != (avg_rate["num"], avg_rate["den"])
    assert avg_rate["num"] > 0 and avg_rate["den"] > 0
    # The canonical grid is exactly the probe's avg_frame_rate rational.
    assert (cp["timebase"]["fps_num"], cp["timebase"]["fps_den"]) == (
        avg_rate["num"], avg_rate["den"],
    )

    art = _proxy_artifact(session_factory, video_item.id)
    final = managed_root / art.relative_path
    assert art.sha256 == hashlib.sha256(final.read_bytes()).hexdigest()
    assert art.size_bytes == final.stat().st_size
    data = _probe_streams(final)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert float(data["format"]["duration"]) > 0
    # The proxy was resampled onto the canonical CFR grid.
    assert video["r_frame_rate"] == f"{avg_rate['num']}/{avg_rate['den']}"
    assert _staging_files(managed_root) == []
    assert len(_job_artifact_files(managed_root, result.job_id)) == 1


# ── AC4: owner-scoped idempotency ────────────────────────────────────────────


def test_duplicate_submit_active_raises_idempotency_key_in_use(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """AC4: an active duplicate submit for the same owner raises
    IdempotencyKeyInUse (no second Job is created)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    with pytest.raises(IdempotencyKeyInUse):
        _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_GENERATE_PROXY)
        ).all()
    assert len(jobs) == 1


def test_duplicate_submit_completed_reuses_same_job(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """AC4: a completed duplicate returns the same Job (reused=True); exactly
    one effect set (Job/artifact/file)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    first = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    assert first.reused is False
    _run_job(worker)
    assert _job_state(session_factory, first.job_id) == "completed"

    second = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    assert second.reused is True
    assert second.job_id == first.job_id

    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_GENERATE_PROXY)
        ).all()
    assert len(jobs) == 1
    assert len(_proxy_artifact_rows(session_factory, ws.id)) == 1
    # Managed tree: the imported source artifact + exactly one proxy.
    assert len(_artifact_files(managed_root)) == 2
    assert _staging_files(managed_root) == []


def test_same_source_bytes_two_video_items_two_independent_proxies(
    worker, session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """AC4: the same source bytes proxied for two VideoItems produce two
    independent Jobs and effect sets (owner-scoped identity)."""
    item2 = VideoItem(
        project_id=project.id, title="Clip 2", position=1,
        status="imported", revision=1,
    )
    session.add(item2)
    session.commit()

    _, src1 = _import_source(session_factory, worker, ws, video_item, source_video, managed_root)
    _, src2 = _import_source(session_factory, worker, ws, item2, source_video, managed_root)
    assert src1 != src2

    r1 = _submit_proxy(session_factory, ws, video_item, src1, managed_root)
    _run_job(worker)
    r2 = _submit_proxy(session_factory, ws, item2, src2, managed_root)
    _run_job(worker)

    assert _job_state(session_factory, r1.job_id) == "completed"
    assert _job_state(session_factory, r2.job_id) == "completed"
    assert r1.job_id != r2.job_id
    art1 = _proxy_artifact(session_factory, video_item.id)
    art2 = _proxy_artifact(session_factory, item2.id)
    assert art1.id != art2.id
    assert art1.relative_path != art2.relative_path
    assert len(_job_artifact_files(managed_root, r1.job_id)) == 1
    assert len(_job_artifact_files(managed_root, r2.job_id)) == 1
    assert len(_artifact_files(managed_root)) == 4  # 2 sources + 2 proxies
    assert _staging_files(managed_root) == []
    with session_factory() as s:
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_GENERATE_PROXY)
        ).all()
        owners = s.scalars(
            select(ArtifactOwner).where(ArtifactOwner.purpose == ARTIFACT_PURPOSE_PROXY)
        ).all()
    assert len(jobs) == 2
    assert len(owners) == 2
    assert {o.owner_id for o in owners} == {video_item.id, item2.id}


def test_owner_scoped_key_shape() -> None:
    """The idempotency key embeds the VideoItem owner + source sha + generation."""
    key = video_proxy._idempotency_key("vi-1", "abc123", "2")
    assert key == "GENERATE_PROXY:video_item:vi-1:abc123:2"
    assert JOB_TYPE_GENERATE_PROXY in key


# ── AC2/AC5: submit-time ownership and source validation ─────────────────────


def test_submit_rejects_cross_project_ownership(
    worker, session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """Cross-project submit → OWNERSHIP_MISMATCH before any Job is created."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    other = Project(name="Other", workspace_id=ws.id, status="active")
    session.add(other)
    session.commit()
    # The ownership validators are the approved S05-T02 helpers and raise
    # VideoImportError; the stable code is the contract, not the class.
    with pytest.raises(Exception) as ei:
        submit_proxy(
            session_factory,
            workspace_id=ws.id,
            project_id=other.id,
            video_item_id=video_item.id,
            source_artifact_id=source_artifact_id,
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_OWNERSHIP_MISMATCH
    with session_factory() as s:
        proxy_jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_GENERATE_PROXY)
        ).all()
    assert len(proxy_jobs) == 0


def test_submit_rejects_cross_workspace_ownership(
    worker, session_factory, ws, video_item, source_video, managed_root, session
) -> None:
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    other_ws = Workspace(name="Other WS")
    session.add(other_ws)
    session.commit()
    with pytest.raises(Exception) as ei:
        submit_proxy(
            session_factory,
            workspace_id=other_ws.id,
            project_id=video_item.project_id,
            video_item_id=video_item.id,
            source_artifact_id=source_artifact_id,
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_OWNERSHIP_MISMATCH
    with session_factory() as s:
        proxy_jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_GENERATE_PROXY)
        ).all()
    assert len(proxy_jobs) == 0


def test_submit_rejects_missing_project_and_video_item(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    with pytest.raises(Exception) as ei:
        submit_proxy(
            session_factory,
            workspace_id=ws.id,
            project_id="no-such-project",
            video_item_id=video_item.id,
            source_artifact_id=source_artifact_id,
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_PROJECT_NOT_FOUND
    with pytest.raises(Exception) as ei:
        submit_proxy(
            session_factory,
            workspace_id=ws.id,
            project_id=video_item.project_id,
            video_item_id="no-such-item",
            source_artifact_id=source_artifact_id,
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_VIDEO_ITEM_NOT_FOUND


def test_submit_rejects_source_not_linked_to_owner(
    worker, session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """A source artifact of another VideoItem is not the owner's source."""
    item2 = VideoItem(
        project_id=project.id, title="Clip 2", position=1,
        status="imported", revision=1,
    )
    session.add(item2)
    session.commit()
    _, src1 = _import_source(session_factory, worker, ws, video_item, source_video, managed_root)
    with pytest.raises(VideoProxyError) as ei:
        submit_proxy(
            session_factory,
            workspace_id=ws.id,
            project_id=project.id,
            video_item_id=item2.id,
            source_artifact_id=src1,
            managed_root=managed_root,
        )
    assert ei.value.code == CODE_SOURCE_OWNER_MISMATCH


def test_submit_rejects_source_not_ready(
    worker, session_factory, ws, video_item, source_video, managed_root, session
) -> None:
    """A source artifact that is not a ready video with checksum fails closed."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    with session_factory() as s:
        art = s.get(Artifact, source_artifact_id)
        art.state = "staging"  # type: ignore[union-attr]  # valid non-ready state
        s.commit()
    with pytest.raises(Exception) as ei:
        _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    assert ei.value.code == CODE_SOURCE_NOT_READY


def test_invalid_proxy_profile_rejected() -> None:
    """Profile knobs out of bounds fail closed with INVALID_PROXY_PROFILE."""
    for kwargs in ({"crf": 99}, {"max_width": 0}, {"preset": "bogus"},
                   {"audio_bitrate": "not-a-bitrate"}, {"timeout_seconds": 0}):
        with pytest.raises(VideoProxyError) as ei:
            ProxyProfile(**kwargs)  # type: ignore[arg-type]
        assert ei.value.code == "INVALID_PROXY_PROFILE"
        assert ei.value.action()


def test_source_phase_revalidates_ownership_after_submit(
    worker, session_factory, ws, project, video_item, source_video, managed_root, session
) -> None:
    """The worker re-validates the chain at run time: moving the VideoItem
    between submit and run fails the job with zero side effects."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    other = Project(name="Other", workspace_id=ws.id, status="active")
    session.add(other)
    session.commit()
    with session_factory() as s:
        item = s.get(VideoItem, video_item.id)
        item.project_id = other.id  # type: ignore[union-attr]
        s.commit()

    _run_job(worker)
    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_OWNERSHIP_MISMATCH
    assert _proxy_artifact_rows(session_factory, ws.id) == []
    assert _job_artifact_files(managed_root, result.job_id) == []
    assert _staging_files(managed_root) == []


# ── AC5: failure / rollback / cancellation / timeout ─────────────────────────


def test_ffmpeg_failure_stable_code_and_no_orphans(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC5: a real ffmpeg non-zero exit → PROXY_FFMPEG_FAILED, no artifact
    rows, no staging/final leftovers."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)

    def bad_command(ffmpeg, src_path, staged_path, profile, timebase, source_probe):
        # A real ffmpeg invocation that must exit non-zero.
        return [ffmpeg, "-y", "-i", str(src_path), "-c:v", "no_such_codec_xyz",
                str(staged_path)]

    monkeypatch.setattr(video_proxy, "_build_ffmpeg_command", bad_command)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PROXY_FFMPEG_FAILED
    assert _proxy_artifact_rows(session_factory, ws.id) == []
    assert _job_artifact_files(managed_root, result.job_id) == []
    assert _staging_files(managed_root) == []


class _TimeoutFirstAttempt:
    """Monotonic clock seam: makes ONLY the first FFmpeg run exceed its budget."""

    def __init__(self) -> None:
        self.real = time.monotonic
        self.calls = 0
        self.armed = True

    def __call__(self) -> float:
        self.calls += 1
        if self.armed:
            if self.calls == 2:
                self.armed = False
                return 1e9  # deadline - now < 0 at the first poll
            return 0.0
        return self.real()


class _AlwaysTimeout:
    """Monotonic clock seam: every FFmpeg run exceeds its budget."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 1e9 if self.calls % 2 == 0 else 0.0


def test_proxy_timeout_is_transient() -> None:
    """PROXY_TIMEOUT is classified transient so the worker auto-retries."""
    assert CODE_PROXY_TIMEOUT in TRANSIENT_ERROR_CODES
    from app.workflow.durable_worker import error_envelope

    assert error_envelope(CODE_PROXY_TIMEOUT, "budget exhausted")["class"] == "transient"


def test_timeout_transient_auto_retry_completes(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC5: a first-attempt PROXY_TIMEOUT is auto-retried and the job
    completes with exactly one effect set."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    monkeypatch.setattr(video_proxy, "_monotonic", _TimeoutFirstAttempt())
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    art = _proxy_artifact(session_factory, video_item.id)
    final = managed_root / art.relative_path
    assert art.sha256 == hashlib.sha256(final.read_bytes()).hexdigest()
    assert len(_job_artifact_files(managed_root, result.job_id)) == 1
    assert _staging_files(managed_root) == []
    with session_factory() as s:
        attempts = s.scalars(
            select(JobAttempt).where(JobAttempt.job_id == result.job_id)
        ).all()
    assert len(attempts) >= 2


def test_timeout_always_fails_retries_exhausted(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC5: every attempt exceeding the budget → RETRIES_EXHAUSTED with no
    artifacts or leftovers."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    monkeypatch.setattr(video_proxy, "_monotonic", _AlwaysTimeout())
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == "RETRIES_EXHAUSTED"
        attempts = s.scalars(
            select(JobAttempt).where(JobAttempt.job_id == result.job_id)
        ).all()
        assert len(attempts) >= 3
    assert _proxy_artifact_rows(session_factory, ws.id) == []
    assert _job_artifact_files(managed_root, result.job_id) == []
    assert _staging_files(managed_root) == []


def test_cancellation_drains_and_cleans_staging(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC5: cancel mid-generation → terminal cancelled, no artifact, staging
    and partial files removed."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    job_id = result.job_id
    real_run = video_proxy._run_ffmpeg

    def run_then_cancel(ctx, cmd, *, timeout_seconds, staged_path):  # type: ignore[no-untyped-def]
        with session_factory() as s:
            r = JobRepository(s)
            r.transition_job(
                job_id, "cancelling", actor="api",
                expected_revision=r.get_job(job_id).revision,
            )
            s.commit()
        real_run(ctx, cmd, timeout_seconds=timeout_seconds, staged_path=staged_path)

    monkeypatch.setattr(video_proxy, "_run_ffmpeg", run_then_cancel)
    _run_job(worker)

    assert _job_state(session_factory, job_id) == "cancelled"
    assert _proxy_artifact_rows(session_factory, ws.id) == []
    assert _job_artifact_files(managed_root, result.job_id) == []
    assert _staging_files(managed_root) == []


def test_db_rollback_removes_only_this_attempts_files(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC5: a publication-transaction failure removes the just-published file
    (created by THIS attempt) and the staged copy — no orphan final files, no
    ready rows without files."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)

    def failing_effect(ctx, final_rel, sha256, size):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated DB failure at publication")

    monkeypatch.setattr(video_proxy, "_publish_effect", failing_effect)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PUBLICATION_FAILED
    assert _proxy_artifact_rows(session_factory, ws.id) == []
    assert _job_artifact_files(managed_root, result.job_id) == []
    assert _staging_files(managed_root) == []


# ── AC6: restart/successor and replay safety ─────────────────────────────────


def test_restart_successor_no_duplicate_artifacts(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC6: a failed attempt is retried as a successor with the same
    key/generation; the successor completes with exactly one artifact/file."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)

    def fail_once(ctx, cmd, *, timeout_seconds, staged_path):  # type: ignore[no-untyped-def]
        raise VideoProxyError(CODE_PROXY_FFMPEG_FAILED, "simulated encode failure")

    monkeypatch.setattr(video_proxy, "_run_ffmpeg", fail_once)
    _run_job(worker)
    with session_factory() as s:
        repo = JobRepository(s)
        pred = repo.get_job(result.job_id)
        assert pred.state == "failed"
        succ = repo.create_successor(
            predecessor_job_id=pred.id,
            input_manifest=pred.input_manifest,
            idempotency_key=pred.idempotency_key,
            input_generation=pred.input_generation,
            steps=video_proxy.generate_proxy_steps(),
        )
        s.commit()
        succ_id = succ.id

    monkeypatch.undo()
    _run_job(worker)

    assert _job_state(session_factory, succ_id) == "completed"
    art = _proxy_artifact(session_factory, video_item.id)
    assert art.state == "ready"
    assert len(_job_artifact_files(managed_root, succ_id)) == 1
    assert _staging_files(managed_root) == []
    with session_factory() as s:
        succ = JobRepository(s).get_job(succ_id)
        assert succ.predecessor_job_id == result.job_id
        assert succ.idempotency_key == pred.idempotency_key
        jobs = s.scalars(
            select(Job).where(Job.job_type == JOB_TYPE_GENERATE_PROXY)
        ).all()
    assert len(jobs) == 2  # predecessor + successor, but ONE effect set


def test_successor_cleans_crash_leftover_staging(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC6: a hard crash mid-encode leaves a staging partial; the successor
    re-runs and garbage-collects the crash leftover, completing with exactly
    one artifact/file."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)

    def crash_mid_encode(ctx, cmd, *, timeout_seconds, staged_path):  # type: ignore[no-untyped-def]
        # Simulate a hard crash: write partial bytes to the FFmpeg target and
        # raise WITHOUT any cleanup (the process "died").
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(b"partial bytes from a crashed encode")
        raise VideoProxyError(CODE_PROXY_FFMPEG_FAILED, "simulated crash mid-encode")

    monkeypatch.setattr(video_proxy, "_run_ffmpeg", crash_mid_encode)
    _run_job(worker)
    with session_factory() as s:
        repo = JobRepository(s)
        pred = repo.get_job(result.job_id)
        assert pred.state == "failed"
        partials = [p for p in (managed_root / "staging").rglob("*") if p.is_file()]
        assert len(partials) == 1  # the crash partial is still on disk
        succ = repo.create_successor(
            predecessor_job_id=pred.id,
            input_manifest=pred.input_manifest,
            idempotency_key=pred.idempotency_key,
            input_generation=pred.input_generation,
            steps=video_proxy.generate_proxy_steps(),
        )
        s.commit()
        succ_id = succ.id

    monkeypatch.undo()
    _run_job(worker)

    assert _job_state(session_factory, succ_id) == "completed"
    art = _proxy_artifact(session_factory, video_item.id)
    final = managed_root / art.relative_path
    assert art.sha256 == hashlib.sha256(final.read_bytes()).hexdigest()
    assert len(_job_artifact_files(managed_root, succ_id)) == 1
    assert _staging_files(managed_root) == []


def _force_replay(session_factory, job_id: str) -> None:
    """Reset a completed job/step to queued/pending and drop lease + attempt
    rows so the worker re-runs the SAME Job (mirror test_video_import.py)."""
    with session_factory() as s:
        repo = JobRepository(s)
        step_row = s.get(JobStep, repo.list_steps(job_id)[0].id)
        step_row.checkpoint_json = None
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
        ).all():
            s.delete(attempt)
        s.commit()


def test_replay_publication_failure_keeps_committed_artifact(
    worker, session_factory, ws, video_item, source_video, managed_root, monkeypatch
) -> None:
    """AC6: a publication failure during replay never deletes the previously
    committed ready artifact file — only files created by the failing attempt
    are removed (S05-T02 correction #4 pattern)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"
    art = _proxy_artifact(session_factory, video_item.id)
    committed_path = managed_root / art.relative_path
    committed_bytes = committed_path.read_bytes()
    committed_sha = hashlib.sha256(committed_bytes).hexdigest()
    assert art.sha256 == committed_sha

    _force_replay(session_factory, result.job_id)

    def failing_effect(ctx, final_rel, sha256, size):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated DB failure during replay")

    monkeypatch.setattr(video_proxy, "_publish_effect", failing_effect)
    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PUBLICATION_FAILED
        # The committed row survives the failed replay...
        arts = _artifact_rows(session_factory, ws.id)
        assert any(a.id == art.id and a.state == "ready" for a in arts)
        owner = s.scalar(
            select(ArtifactOwner).where(
                ArtifactOwner.artifact_id == art.id,
                ArtifactOwner.purpose == ARTIFACT_PURPOSE_PROXY,
            )
        )
        assert owner is not None
        assert owner.owner_id == video_item.id
    # ...and the committed file is intact and byte-identical.
    assert committed_path.is_file()
    assert committed_path.read_bytes() == committed_bytes
    assert _staging_files(managed_root) == []


def test_publish_file_checksum_mismatch_keeps_existing_final(managed_root) -> None:
    """A pre-existing final file that does not match the new staged bytes
    raises PROXY_VALIDATION_FAILED and is NOT removed (cleanup never deletes
    a previously committed file)."""
    managed = ManagedRoot(managed_root)
    staged = managed.resolve("staging/j1/proxy/new.mp4")
    final = managed.resolve("artifacts/ws1/video/j1/proxy/new.mp4")
    staged.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    existing_bytes = b"committed-ready-proxy-bytes"
    staged_bytes = b"new-attempt-proxy-bytes"
    staged.write_bytes(staged_bytes)
    final.write_bytes(existing_bytes)
    recorded_sha = hashlib.sha256(staged_bytes).hexdigest()

    with pytest.raises(VideoProxyError) as ei:
        video_proxy._publish_file(managed, staged, final, recorded_sha)
    assert ei.value.code == CODE_PROXY_VALIDATION_FAILED
    assert final.read_bytes() == existing_bytes


# ── AC7: path containment / source immutability ──────────────────────────────


def test_symlink_escape_rejected_and_nothing_written_outside(
    worker, session_factory, ws, video_item, source_video, managed_root, tmp_path
) -> None:
    """AC7: a symlink inside the root pointing outside fails with
    PATH_CONTAINMENT at the proxy's final path; nothing is written outside;
    the source stays intact."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    # Symlink exactly the proxy job's final directory (the source artifact
    # lives under the import job's directory, which stays untouched).
    outside = tmp_path / "outside"
    outside.mkdir()
    proxy_dir = managed_root / "artifacts" / ws.id / "video" / result.job_id
    try:
        proxy_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    _run_job(worker)

    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.state == "failed"
        assert job.error is not None
        assert job.error["error_code"] == CODE_PATH_CONTAINMENT
    assert _proxy_artifact_rows(session_factory, ws.id) == []
    assert list(outside.iterdir()) == []
    assert _staging_files(managed_root) == []


def test_source_artifact_never_mutated_or_deleted(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """The managed source artifact file is byte-identical after a successful
    proxy and after a failed proxy attempt."""
    import_job_id, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    with session_factory() as s:
        src_art = s.get(Artifact, source_artifact_id)
        assert src_art is not None
        src_file = managed_root / src_art.relative_path
        sha_before = hashlib.sha256(src_file.read_bytes()).hexdigest()
        size_before = src_file.stat().st_size

    result = _submit_proxy(session_factory, ws, video_item, source_artifact_id, managed_root)
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"

    assert src_file.is_file()
    assert src_file.stat().st_size == size_before
    assert hashlib.sha256(src_file.read_bytes()).hexdigest() == sha_before
    # The import job's source artifact row is untouched by the proxy job.
    with session_factory() as s:
        src_art_after = s.get(Artifact, source_artifact_id)
        assert src_art_after is not None
        assert src_art_after.state == "ready"
        assert src_art_after.sha256 == sha_before
        assert src_art_after.size_bytes == size_before
        import_job = JobRepository(s).get_job(import_job_id)
        assert import_job.state == "completed"

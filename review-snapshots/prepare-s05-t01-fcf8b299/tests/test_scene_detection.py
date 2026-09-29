"""Targeted tests for S05-T04 — scene detection durable job (ANALYZE_MEDIA reuse).

Covers the required scenarios of ``docs/pm/sessions/S05-T04-scene-detection/
TASK.md`` AC1–AC10:

- success (CFR): Job completes, scene rows are committed in ONE transaction
  with canonical ``start_frame``/``end_frame`` (zero-based inclusive) and
  integer-ms times derived from the exact rational timebase; ``position``
  unique per video; status ``pending``; ``legacy_scene_id`` NULL;
- proxy input: the managed ready proxy artifact is consumed when supplied;
  a proxy that becomes unusable falls back to the managed source;
- canonical timebase evidence: every row's ms range recomputed from the
  persisted schema-versioned timebase payload (CFR 30fps, NTSC 30000/1001,
  real VFR concat) matches exactly — no float drift;
- owner-scoped idempotency: duplicate submit → active ``IdempotencyKeyInUse``
  / completed reuse; the key carries a ``scene_detect`` discriminator;
- retry/replay/restart: the same job's retry reuses the detection checkpoint
  (exactly one FFmpeg run); the crash-window (rows committed, published
  checkpoint missing) reuses the committed rows; a successor after a failed
  attempt creates no duplicate rows and reuses committed rows by evidence;
- cancel/failure/timeout: terminal states leave zero scene rows and no
  staging leftovers; ``SCENE_DETECT_TIMEOUT`` is permanent (no transient
  registration — durable_worker.py is outside this task's write scope);
- input-change protection: a replay whose resolved input differs from the
  checkpointed input fails closed with ``INPUT_CHANGED``;
- foreign rows protection: pre-existing scene rows (legacy/other source)
  fail closed with ``SCENE_EVIDENCE_CONFLICT`` — never overwritten;
- containment: source + proxy artifacts byte-identical after detection; no
  absolute managed path in durable checkpoints;
- deterministic scene ids derived from ``(job_id, position)``.

Every test uses a temporary database + temporary managed root and synthetic
ffmpeg fixtures under ``tmp_path``.  Tests skip gracefully when ffmpeg is not
available (mirroring ``tests/test_video_import.py`` / ``test_video_proxy.py``).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
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
from app.persistence.jobs import IdempotencyKeyInUse
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Job,
    JobStep,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.services import scene_detector, video_import, video_proxy
from app.services.scene_detector import (
    CODE_INPUT_CHANGED,
    CODE_PUBLICATION_FAILED,
    CODE_SCENE_DETECT_FAILED,
    CODE_SCENE_DETECT_TIMEOUT,
    CODE_SCENE_EVIDENCE_CONFLICT,
    JOB_TYPE_ANALYZE_MEDIA,
    SCENE_DETECT_STEP_CODE,
    SceneDetectionProfile,
    SceneDetectorError,
    cuts_to_scenes,
    register_scene_detection_handler,
    scene_ms_range,
    submit_scene_detection,
)
from app.services.timebase import CanonicalTimebase
from app.services.video_import import CODE_OWNERSHIP_MISMATCH, CODE_PROBE_TIMEOUT, submit_import
from app.workflow.durable_worker import (
    TRANSIENT_ERROR_CODES,
    DurableWorker,
    WorkerConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Deterministic clock/sleeper (mirror test_video_proxy.py) ────────────────


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
    return tmp_path / "scenes.db"


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
    ws = Workspace(name="Scene Workspace")
    session.add(ws)
    session.commit()
    return ws


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    project = Project(name="Scene Project", workspace_id=ws.id, status="active")
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
    """A worker with fake clock/sleeper and the ANALYZE_MEDIA dispatcher
    (import + scene_detect, S05-T04) + GENERATE_PROXY (S05-T03) registered."""
    w = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="scene-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
        clock=clock,
        sleeper=sleeper,
    )
    from app.services.video_proxy import register_generate_proxy_handler

    register_generate_proxy_handler(w)
    # Registered LAST: the dispatcher owns ANALYZE_MEDIA (import + scene_detect).
    register_scene_detection_handler(w)
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
    duration: float = 2.0,
    fps: int = 30,
    rate: str | None = None,
    audio: bool = False,
    color: str = "blue",
) -> Path | None:
    """Create a CFR synthetic MP4/H.264 clip with ffmpeg (static color)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    rate_arg = rate or str(fps)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:duration={duration}:size=320x240:rate={rate_arg}",
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


def _make_cut_video(
    path: Path,
    *,
    duration_each: float = 1.0,
    fps: int = 30,
    rate: str | None = None,
) -> Path | None:
    """Create a 2-segment video with ONE hard cut at the segment boundary.

    Two static color segments (blue → red) concatenated in the filter graph:
    exactly one scene change at frame ``round(duration_each * fps)`` with a
    scene score of ~1.0 and zero motion noise.
    """
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    rate_arg = rate or str(fps)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:duration={duration_each}:size=320x240:rate={rate_arg}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=red:duration={duration_each}:size=320x240:rate={rate_arg}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
    ]
    cmd.append(str(path))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    return path


@pytest.fixture()
def source_video(tmp_path: Path) -> Path:
    """A real CFR MP4/H.264 synthetic fixture (30fps, 2s, blue)."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    out = _make_video(tmp_path / "source.mp4")
    assert out is not None, "ffmpeg failed to create the source fixture"
    return out


@pytest.fixture()
def cut_video(tmp_path: Path) -> Path:
    """A 2s/60-frame 30fps clip with exactly one hard cut at frame 30."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    out = _make_cut_video(tmp_path / "cut.mp4")
    assert out is not None, "ffmpeg failed to create the cut fixture"
    return out


@pytest.fixture()
def ntsc_video(tmp_path: Path) -> Path:
    """A 2s NTSC (30000/1001) clip with one hard cut at frame 30 (t=1.001s)."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    out = _make_cut_video(tmp_path / "ntsc.mp4", rate="30000/1001")
    assert out is not None, "ffmpeg failed to create the NTSC fixture"
    return out


@pytest.fixture()
def vfr_video(tmp_path: Path) -> Path:
    """A real VFR MP4: concatenation of a 30fps and a 25fps segment (copy)."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not available")
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    seg1 = tmp_path / "seg30.mp4"
    seg2 = tmp_path / "seg25.mp4"
    for seg, fps in ((seg1, 30), (seg2, 25)):
        made = _make_video(seg, duration=1.0, fps=fps, audio=False)
        assert made is not None, "ffmpeg failed to create a VFR segment"
    lst = tmp_path / "concat.txt"
    lst.write_text(f"file '{seg1.as_posix()}'\nfile '{seg2.as_posix()}'\n", encoding="utf-8")
    out = tmp_path / "vfr.mp4"
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg concat failed to create the VFR fixture")
    probe = video_import.probe_source(out)
    video = probe["video_stream"]
    if video["r_frame_rate"] == video["avg_frame_rate"]:
        pytest.skip("concat output is not genuinely VFR on this ffmpeg build")
    return out


# ── Import / proxy / scene helpers ───────────────────────────────────────────


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


def _generate_proxy(
    session_factory,
    worker: DurableWorker,
    ws: Workspace,
    video_item: VideoItem,
    source_artifact_id: str,
    managed_root: Path,
) -> str:
    """Run the approved S05-T03 GENERATE_PROXY and return the proxy artifact id."""
    video_proxy.submit_proxy(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_artifact_id=source_artifact_id,
        generation="1",
        managed_root=managed_root,
        title="proxy",
    )
    _run_job(worker)
    with session_factory() as s:
        art_id = s.scalar(
            select(ArtifactOwner.artifact_id).where(
                ArtifactOwner.owner_type == "video_item",
                ArtifactOwner.owner_id == video_item.id,
                ArtifactOwner.purpose == video_proxy.ARTIFACT_PURPOSE_PROXY,
            )
        )
    assert art_id is not None, "proxy job did not link a proxy artifact"
    return str(art_id)


def _submit_scene_detection(
    session_factory,
    ws: Workspace,
    video_item: VideoItem,
    source_artifact_id: str,
    managed_root: Path,
    *,
    proxy_artifact_id: str | None = None,
    generation: str = "1",
    profile: SceneDetectionProfile | None = None,
):
    return submit_scene_detection(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_artifact_id=source_artifact_id,
        proxy_artifact_id=proxy_artifact_id,
        generation=generation,
        managed_root=managed_root,
        title="scene_detect",
        profile=profile,
    )


def _run_job(worker: DurableWorker) -> None:
    worker.run_once()


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _job_error(session_factory, job_id: str) -> dict | None:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).error


def _scene_rows(session_factory, video_item_id: str) -> list[Scene]:
    with session_factory() as s:
        return list(
            s.scalars(
                select(Scene).where(Scene.video_item_id == video_item_id).order_by(Scene.position)
            ).all()
        )


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


def _artifact_sha_size(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


# ── Unit tests: cuts → scenes + exact integer-ms mapping ─────────────────────


def test_unit_cuts_to_scenes() -> None:
    """Merging, min-length, tail merge, empty input and clamping rules."""
    # No cuts → the whole video is one scene.
    assert cuts_to_scenes([], 60, 15) == [(0, 59)]
    # One cut at frame 30 → two scenes.
    assert cuts_to_scenes([30], 60, 15) == [(0, 29), (30, 59)]
    # A cut closer than min_scene_len to the previous boundary is merged.
    assert cuts_to_scenes([5, 30], 60, 15) == [(0, 29), (30, 59)]
    # A final tail shorter than min_scene_len merges into the last scene.
    assert cuts_to_scenes([30, 55], 60, 15) == [(0, 29), (30, 59)]
    # Deduplicated and clamped into [0, nb_frames - 1].
    assert cuts_to_scenes([30, 30, 99, -3], 60, 15) == [(0, 29), (30, 59)]
    # Single-frame video is always one scene.
    assert cuts_to_scenes([], 1, 15) == [(0, 0)]
    assert cuts_to_scenes([0], 1, 15) == [(0, 0)]


def test_unit_scene_ms_range_exact() -> None:
    """Integer-ms ranges are exact rational half-up, never float drift."""
    # 30fps: frame 30 starts at exactly 1.000s.
    tb = CanonicalTimebase.from_rational(30, 1, nb_frames=60)
    assert scene_ms_range(tb, 0, 29) == (0, 999)
    assert scene_ms_range(tb, 30, 59) == (1000, 1999)
    # One-frame scene: [t(0), t(1)) = [0, 33.333...) → (0, 32).
    assert scene_ms_range(tb, 0, 0) == (0, 32)
    # NTSC 30000/1001: frame 30 starts at exactly 1.001s.
    tb_ntsc = CanonicalTimebase.from_rational(30000, 1001, nb_frames=60)
    assert scene_ms_range(tb_ntsc, 30, 59) == (1001, 2001)
    assert scene_ms_range(tb_ntsc, 0, 29) == (0, 1000)
    # VFR canonical grid 33/1: frame 33 starts at exactly 1.000s.
    tb_vfr = CanonicalTimebase.from_rational(33, 1, classification="VFR", nb_frames=66)
    assert scene_ms_range(tb_vfr, 33, 65) == (1000, 1999)


# ── AC1/AC2: success path (CFR cut video) ────────────────────────────────────


def test_detect_success_cfr_publishes_scene_rows(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """A 30fps clip with one hard cut → completed job, two canonical scene
    rows (frames zero-based inclusive, times exact rational ms), position
    unique, status pending, legacy_scene_id NULL, source unchanged."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 2, f"expected 2 scene rows, got {len(rows)}"
    assert [r.position for r in rows] == [0, 1]
    assert [(r.start_frame, r.end_frame) for r in rows] == [(0, 29), (30, 59)]
    assert [(r.start_time_ms, r.end_time_ms) for r in rows] == [(0, 999), (1000, 1999)]
    assert all(r.status == "pending" for r in rows)
    assert all(r.revision == 1 for r in rows)
    assert all(r.legacy_scene_id is None for r in rows)
    # Source artifact untouched.
    with session_factory() as s:
        src = s.get(Artifact, source_artifact_id)
        src_file = managed_root / src.relative_path
    assert _artifact_sha_size(src_file) == (src.sha256, src.size_bytes)
    assert _staging_files(managed_root) == []


def test_detect_single_scene_when_no_cuts(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """A static clip (no scene change) → exactly one scene covering the video."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 1
    assert rows[0].start_frame == 0
    assert rows[0].end_frame == 59  # 2s @ 30fps → 60 frames
    assert rows[0].start_time_ms == 0
    assert rows[0].end_time_ms == 1999


def test_scene_times_match_canonical_timebase_payload(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """Every row's ms range equals the exact recomputation from the persisted
    schema-versioned timebase payload — the rows derive from the rational
    grid, not from floats."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"

    cp = _step_checkpoint(session_factory, result.job_id)
    timebase = CanonicalTimebase.from_json(cp["detection"]["timebase"])
    rows = _scene_rows(session_factory, video_item.id)
    assert timebase.fps_num == 30 and timebase.fps_den == 1
    for row in rows:
        start_ms, end_ms = scene_ms_range(timebase, row.start_frame, row.end_frame)
        assert (row.start_time_ms, row.end_time_ms) == (start_ms, end_ms)


def test_ntsc_rational_grid_exact_ms(
    worker, session_factory, ws, video_item, ntsc_video, managed_root
) -> None:
    """NTSC 30000/1001: the cut frame maps to exactly 1001ms (frame 30 starts
    at t=1.001s exactly) and every row recomputes from the rational payload."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, ntsc_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"

    cp = _step_checkpoint(session_factory, result.job_id)
    det = cp["detection"]
    timebase = CanonicalTimebase.from_json(det["timebase"])
    assert (timebase.fps_num, timebase.fps_den) == (30000, 1001)
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) >= 2, f"expected the NTSC cut to be detected, got {len(rows)}"
    # The scene that starts at the cut frame must start at exactly 1001ms.
    cut_rows = [r for r in rows if r.start_time_ms == 1001]
    assert cut_rows, (
        f"no scene starts at exactly 1001ms: {[(r.start_time_ms, r.end_time_ms) for r in rows]}"
    )
    for row in rows:
        start_ms, end_ms = scene_ms_range(timebase, row.start_frame, row.end_frame)
        assert (row.start_time_ms, row.end_time_ms) == (start_ms, end_ms)


def test_vfr_source_detection_exact_rational(
    worker, session_factory, ws, video_item, vfr_video, managed_root
) -> None:
    """A real VFR source maps onto the canonical avg_frame_rate grid; every
    row's ms range recomputes exactly from the persisted payload."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, vfr_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"

    cp = _step_checkpoint(session_factory, result.job_id)
    timebase = CanonicalTimebase.from_json(cp["detection"]["timebase"])
    assert timebase.classification == "VFR"
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) >= 1
    positions = [r.position for r in rows]
    assert len(set(positions)) == len(positions)  # unique per video
    for row in rows:
        assert 0 <= row.start_frame <= row.end_frame < (timebase.nb_frames or 0)
        start_ms, end_ms = scene_ms_range(timebase, row.start_frame, row.end_frame)
        assert (row.start_time_ms, row.end_time_ms) == (start_ms, end_ms)


# ── Input: proxy artifact consumption + source fallback ──────────────────────


def test_detect_uses_proxy_artifact_when_provided(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """Submitting with a valid S05-T03 proxy → the detection consumes the
    managed ready proxy artifact (input evidence kind=proxy)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    proxy_id = _generate_proxy(
        session_factory, worker, ws, video_item, source_artifact_id, managed_root
    )
    result = _submit_scene_detection(
        session_factory,
        ws,
        video_item,
        source_artifact_id,
        managed_root,
        proxy_artifact_id=proxy_id,
    )
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"

    cp = _step_checkpoint(session_factory, result.job_id)
    assert cp["input"]["kind"] == "proxy"
    assert cp["input"]["artifact_id"] == proxy_id
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 2
    # The proxy artifact (and its file) is untouched.
    with session_factory() as s:
        proxy = s.get(Artifact, proxy_id)
        proxy_file = managed_root / proxy.relative_path
    assert _artifact_sha_size(proxy_file) == (proxy.sha256, proxy.size_bytes)


def test_detect_falls_back_to_source_when_proxy_unusable(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """A proxy that becomes unusable after submit (row no longer ready) →
    the detection falls back to the managed source (kind=source)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    proxy_id = _generate_proxy(
        session_factory, worker, ws, video_item, source_artifact_id, managed_root
    )
    result = _submit_scene_detection(
        session_factory,
        ws,
        video_item,
        source_artifact_id,
        managed_root,
        proxy_artifact_id=proxy_id,
    )
    with session_factory() as s:
        proxy = s.get(Artifact, proxy_id)
        proxy.state = "trash"
        s.commit()
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"
    cp = _step_checkpoint(session_factory, result.job_id)
    assert cp["input"]["kind"] == "source"
    assert cp["input"]["artifact_id"] == source_artifact_id
    assert len(_scene_rows(session_factory, video_item.id)) == 2


# ── Owner-scoped idempotency ─────────────────────────────────────────────────


def test_duplicate_submit_active_raises_idempotency_key_in_use(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    _submit_scene_detection(session_factory, ws, video_item, source_artifact_id, managed_root)
    with pytest.raises(IdempotencyKeyInUse):
        _submit_scene_detection(session_factory, ws, video_item, source_artifact_id, managed_root)


def test_duplicate_submit_completed_reuses_same_job(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    first = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)
    assert _job_state(session_factory, first.job_id) == "completed"
    second = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    assert second.job_id == first.job_id
    assert second.reused is True
    assert len(_scene_rows(session_factory, video_item.id)) == 1  # one effect set


def test_owner_scoped_key_shape(
    worker, session_factory, ws, video_item, source_video, managed_root
) -> None:
    """The scene-detection key carries a scene_detect discriminator and never
    collides with the import key namespace."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    with session_factory() as s:
        src = s.get(Artifact, source_artifact_id)
        sha = src.sha256
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    with session_factory() as s:
        job = JobRepository(s).get_job(result.job_id)
        assert job.job_type == JOB_TYPE_ANALYZE_MEDIA
        assert job.idempotency_key == (
            f"ANALYZE_MEDIA:scene_detect:video_item:{video_item.id}:{sha}:1"
        )
        assert job.idempotency_key != (f"ANALYZE_MEDIA:video_item:{video_item.id}:{sha}:1")
        steps = JobRepository(s).list_steps(result.job_id)
        assert [st.step_code for st in steps] == [SCENE_DETECT_STEP_CODE]


# ── Retry / replay / restart (stable Scene IDs, no duplicates) ───────────────


def test_retry_reuses_detection_checkpoint_no_second_ffmpeg(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """A transient failure after the detection checkpoint → the same job's
    retry reuses the checkpoint (exactly one FFmpeg run) and completes with
    exactly two rows."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    real_detect = scene_detector._run_scene_detect
    invocations: list[int] = []

    def counting_detect(ctx, input_path, profile, timebase):
        invocations.append(1)
        return real_detect(ctx, input_path, profile, timebase)

    real_commit = scene_detector._commit_scene_rows
    failed = False

    def commit_fail_once(ctx, det_ev):
        nonlocal failed
        if not failed:
            failed = True
            raise video_import.VideoImportError(
                CODE_PROBE_TIMEOUT, "transient commit failure (injected)"
            )
        return real_commit(ctx, det_ev)

    monkeypatch.setattr(scene_detector, "_run_scene_detect", counting_detect)
    monkeypatch.setattr(scene_detector, "_commit_scene_rows", commit_fail_once)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    assert len(invocations) == 1, "retry must reuse the detection checkpoint"
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 2
    assert _staging_files(managed_root) == []


def test_crash_window_reuses_committed_rows(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """Rows committed but the published checkpoint lost (crash between effect
    commit and checkpoint write) → the retry reuses the committed rows by
    evidence: same ids, no duplicates, no revision churn."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    real_commit = scene_detector._commit_scene_rows
    failed = False

    def commit_then_fail_once(ctx, det_ev):
        nonlocal failed
        rows = real_commit(ctx, det_ev)  # commits the rows
        if not failed:
            failed = True
            raise video_import.VideoImportError(
                CODE_PROBE_TIMEOUT, "transient crash after commit (injected)"
            )
        return rows

    monkeypatch.setattr(scene_detector, "_commit_scene_rows", commit_then_fail_once)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "completed"
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 2
    assert all(r.revision == 1 for r in rows)  # reused, never rewritten
    assert _staging_files(managed_root) == []


def test_successor_no_duplicate_scene_rows(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """A permanent failure before any commit → a successor with the same key
    completes with exactly one effect set (2 jobs, 2 rows)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    first = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )

    def fail_detect(ctx, input_path, profile, timebase):
        raise SceneDetectorError(CODE_SCENE_DETECT_FAILED, "injected detection failure")

    monkeypatch.setattr(scene_detector, "_run_scene_detect", fail_detect)
    _run_job(worker)
    assert _job_state(session_factory, first.job_id) == "failed"
    assert _scene_rows(session_factory, video_item.id) == []

    monkeypatch.undo()
    with session_factory() as s:
        repo = JobRepository(s)
        pred = repo.get_job(first.job_id)
        assert pred.state == "failed"
        succ = repo.create_successor(
            predecessor_job_id=pred.id,
            input_manifest=pred.input_manifest,
            idempotency_key=pred.idempotency_key,
            input_generation=pred.input_generation,
            steps=scene_detector.scene_detection_steps(),
        )
        s.commit()
        second_id = succ.id
    _run_job(worker)
    assert _job_state(session_factory, second_id) == "completed"
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 2
    with session_factory() as s:
        first_job = s.get(Job, first.job_id)
        job_count = len(
            s.scalars(
                select(Job).where(
                    Job.idempotency_key == first_job.idempotency_key,
                    Job.input_generation == first_job.input_generation,
                )
            ).all()
        )
    assert job_count == 2  # predecessor + successor, ONE effect set


def test_successor_reuses_committed_rows_after_failure(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """Rows committed then a permanent failure → a successor reuses them by
    evidence: same scene ids, exactly two rows, no duplicates."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    first = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    real_commit = scene_detector._commit_scene_rows

    def commit_then_permanent_fail(ctx, det_ev):
        real_commit(ctx, det_ev)
        raise SceneDetectorError(CODE_PUBLICATION_FAILED, "injected permanent failure after commit")

    monkeypatch.setattr(scene_detector, "_commit_scene_rows", commit_then_permanent_fail)
    _run_job(worker)
    assert _job_state(session_factory, first.job_id) == "failed"
    committed_ids = [r.id for r in _scene_rows(session_factory, video_item.id)]
    assert len(committed_ids) == 2

    monkeypatch.undo()
    with session_factory() as s:
        repo = JobRepository(s)
        pred = repo.get_job(first.job_id)
        assert pred.state == "failed"
        succ = repo.create_successor(
            predecessor_job_id=pred.id,
            input_manifest=pred.input_manifest,
            idempotency_key=pred.idempotency_key,
            input_generation=pred.input_generation,
            steps=scene_detector.scene_detection_steps(),
        )
        s.commit()
        second_id = succ.id
    _run_job(worker)
    assert _job_state(session_factory, second_id) == "completed"
    rows = _scene_rows(session_factory, video_item.id)
    assert [r.id for r in rows] == committed_ids
    assert len(rows) == 2
    assert _staging_files(managed_root) == []


def test_scene_ids_deterministic(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """Scene ids are deterministic uuids derived from (job_id, position)."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)
    rows = _scene_rows(session_factory, video_item.id)
    expected = [
        str(uuid.uuid5(uuid.NAMESPACE_OID, f"scene-detect:{result.job_id}:{r.position}"))
        for r in rows
    ]
    assert [r.id for r in rows] == expected
    assert len({r.id for r in rows}) == len(rows)


# ── Input-change protection ──────────────────────────────────────────────────


def test_input_changed_fails_closed(
    worker, session_factory, ws, video_item, cut_video, managed_root, sleeper, monkeypatch
) -> None:
    """A retry whose resolved input differs from the checkpointed input
    (proxy becomes unusable between attempts) fails closed with INPUT_CHANGED
    — it never silently re-detects against different bytes."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    proxy_id = _generate_proxy(
        session_factory, worker, ws, video_item, source_artifact_id, managed_root
    )
    result = _submit_scene_detection(
        session_factory,
        ws,
        video_item,
        source_artifact_id,
        managed_root,
        proxy_artifact_id=proxy_id,
    )
    real_commit = scene_detector._commit_scene_rows
    failed = False

    def commit_fail_once(ctx, det_ev):
        nonlocal failed
        if not failed:
            failed = True
            raise video_import.VideoImportError(
                CODE_PROBE_TIMEOUT, "transient failure after detection (injected)"
            )
        return real_commit(ctx, det_ev)

    real_sleeper = sleeper

    def sleep_then_trash_proxy(seconds: float) -> None:
        real_sleeper(seconds)
        with session_factory() as s:
            proxy = s.get(Artifact, proxy_id)
            proxy.state = "trash"
            s.commit()

    monkeypatch.setattr(scene_detector, "_commit_scene_rows", commit_fail_once)
    monkeypatch.setattr(worker, "_sleeper", sleep_then_trash_proxy)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "failed"
    error = _job_error(session_factory, result.job_id)
    assert error is not None and error["error_code"] == CODE_INPUT_CHANGED
    assert _scene_rows(session_factory, video_item.id) == []
    # The checkpoint still records the original proxy input evidence.
    cp = _step_checkpoint(session_factory, result.job_id)
    assert cp["input"]["kind"] == "proxy"


# ── Cancel / failure / timeout (zero rows, clean rollback) ───────────────────


def test_cancel_drains_with_zero_scene_rows(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """Cancel mid-detection → terminal cancelled, zero scene rows, no staging
    leftovers."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    job_id = result.job_id
    real_detect = scene_detector._run_scene_detect

    def detect_then_cancel(ctx, input_path, profile, timebase):
        with session_factory() as s:
            r = JobRepository(s)
            r.transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=r.get_job(job_id).revision,
            )
            s.commit()
        return real_detect(ctx, input_path, profile, timebase)

    monkeypatch.setattr(scene_detector, "_run_scene_detect", detect_then_cancel)
    _run_job(worker)

    assert _job_state(session_factory, job_id) == "cancelled"
    assert _scene_rows(session_factory, video_item.id) == []
    assert _staging_files(managed_root) == []


def test_failure_stable_code_and_zero_rows(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """A detection failure → failed with SCENE_DETECT_FAILED, zero rows."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )

    def fail_detect(ctx, input_path, profile, timebase):
        raise SceneDetectorError(
            CODE_SCENE_DETECT_FAILED,
            "ffmpeg exited 1 (injected)",
            details={"returncode": 1},
        )

    monkeypatch.setattr(scene_detector, "_run_scene_detect", fail_detect)
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "failed"
    error = _job_error(session_factory, result.job_id)
    assert error is not None and error["error_code"] == CODE_SCENE_DETECT_FAILED
    assert error.get("class") == "permanent"
    assert _scene_rows(session_factory, video_item.id) == []
    assert _staging_files(managed_root) == []


class _AlwaysTimeout:
    """Monotonic clock seam: the FFmpeg run exceeds its bounded budget."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 1e9 if self.calls % 2 == 0 else 0.0


def test_timeout_fails_permanent_and_cleans(
    worker, session_factory, ws, video_item, cut_video, managed_root, monkeypatch
) -> None:
    """Budget overrun → SCENE_DETECT_TIMEOUT.  The code is NOT registered as
    transient (durable_worker.py is outside this task's write scope), so the
    job fails permanently with a stable envelope and zero rows."""
    assert CODE_SCENE_DETECT_TIMEOUT not in TRANSIENT_ERROR_CODES
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    monkeypatch.setattr(scene_detector, "_monotonic", _AlwaysTimeout())
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "failed"
    error = _job_error(session_factory, result.job_id)
    assert error is not None and error["error_code"] == CODE_SCENE_DETECT_TIMEOUT
    assert _scene_rows(session_factory, video_item.id) == []
    assert _staging_files(managed_root) == []


def test_foreign_scene_rows_fail_closed_conflict(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """Pre-existing scene rows (e.g. legacy data) never match the detection
    evidence → SCENE_EVIDENCE_CONFLICT; the foreign rows are untouched."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    with session_factory() as s:
        s.add(
            Scene(
                id=str(uuid.uuid4()),
                video_item_id=video_item.id,
                legacy_scene_id=7,
                position=0,
                start_frame=0,
                end_frame=10,
                start_time_ms=0,
                end_time_ms=333,
                status="pending",
            )
        )
        s.commit()
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)

    assert _job_state(session_factory, result.job_id) == "failed"
    error = _job_error(session_factory, result.job_id)
    assert error is not None and error["error_code"] == CODE_SCENE_EVIDENCE_CONFLICT
    rows = _scene_rows(session_factory, video_item.id)
    assert len(rows) == 1
    assert rows[0].legacy_scene_id == 7  # foreign row untouched


# ── Submit-time rejections ───────────────────────────────────────────────────


def test_submit_rejects_cross_project_ownership(
    session_factory, ws, project, video_item, source_video, managed_root, worker
) -> None:
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    other = Project(name="Other", workspace_id=ws.id, status="active")
    with session_factory() as s:
        s.add(other)
        s.commit()
        other_id = other.id
    with pytest.raises(video_import.VideoImportError) as excinfo:
        submit_scene_detection(
            session_factory,
            workspace_id=ws.id,
            project_id=other_id,
            video_item_id=video_item.id,
            source_artifact_id=source_artifact_id,
            managed_root=managed_root,
        )
    assert excinfo.value.code == CODE_OWNERSHIP_MISMATCH


def test_submit_rejects_invalid_proxy_chain(
    session_factory, ws, video_item, source_video, managed_root, worker
) -> None:
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, source_video, managed_root
    )
    with pytest.raises(SceneDetectorError) as excinfo:
        submit_scene_detection(
            session_factory,
            workspace_id=ws.id,
            project_id=video_item.project_id,
            video_item_id=video_item.id,
            source_artifact_id=source_artifact_id,
            proxy_artifact_id=str(uuid.uuid4()),
            managed_root=managed_root,
        )
    assert excinfo.value.code == "PROXY_ARTIFACT_NOT_FOUND"


# ── Containment evidence ─────────────────────────────────────────────────────


def test_detection_checkpoint_has_no_absolute_path(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """No absolute managed path leaks into durable checkpoints."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    result = _submit_scene_detection(
        session_factory, ws, video_item, source_artifact_id, managed_root
    )
    _run_job(worker)
    cp = _step_checkpoint(session_factory, result.job_id)
    raw = json.dumps(cp)
    root_str = str(managed_root.resolve()).replace("\\", "/")
    assert root_str not in raw
    assert "C:" not in raw and "c:" not in raw


def test_source_and_proxy_artifacts_unmodified(
    worker, session_factory, ws, video_item, cut_video, managed_root
) -> None:
    """Source + proxy artifacts (rows and bytes) are byte-identical after a
    detection run."""
    _, source_artifact_id = _import_source(
        session_factory, worker, ws, video_item, cut_video, managed_root
    )
    proxy_id = _generate_proxy(
        session_factory, worker, ws, video_item, source_artifact_id, managed_root
    )
    result = _submit_scene_detection(
        session_factory,
        ws,
        video_item,
        source_artifact_id,
        managed_root,
        proxy_artifact_id=proxy_id,
    )
    with session_factory() as s:
        src = s.get(Artifact, source_artifact_id)
        proxy = s.get(Artifact, proxy_id)
        src_sha, src_size = src.sha256, src.size_bytes
        proxy_sha, proxy_size = proxy.sha256, proxy.size_bytes
        src_path = managed_root / src.relative_path
        proxy_path = managed_root / proxy.relative_path
    _run_job(worker)
    assert _job_state(session_factory, result.job_id) == "completed"
    assert _artifact_sha_size(src_path) == (src_sha, src_size)
    assert _artifact_sha_size(proxy_path) == (proxy_sha, proxy_size)
    with session_factory() as s:
        src = s.get(Artifact, source_artifact_id)
        proxy = s.get(Artifact, proxy_id)
        assert (src.sha256, src.size_bytes) == (src_sha, src_size)
        assert (proxy.sha256, proxy.size_bytes) == (proxy_sha, proxy_size)

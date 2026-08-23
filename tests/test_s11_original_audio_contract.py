"""S11-T01A regressions — Original Audio Import Policy and Contract.

Binary acceptance tests required by ``docs/pm/sessions/
S11-T01A-audio-import-contract/TASK.md`` (one test per required item):

1.  AAC first audio remains accepted.
2.  No-audio remains accepted (explicit NO_AUDIO_STREAM warning).
3.  MP4 H.264/HEVC with a non-AAC FIRST audio stream → accepted WITH an
    explicit ``UNSUPPORTED_AUDIO_CODEC`` warning (never rejected).
4.  Unsupported video codec still rejected (fail-closed unchanged).
5.  Unsupported container still rejected (fail-closed unchanged).
6.  HDR/10-bit policy unchanged (still rejected).
7.  First audio stream remains canonical.
8.  Multi-stream input is never merged (byte-verbatim copy, single
    canonical audio payload).
9.  Probe/checkpoint retains audio codec/index/channels/sample rate.
10. Import does not transcode and does not mutate the source bytes
    (published artifact is byte-identical to the source).

Policy under test: ``docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md``
(B5 resolution appended to ``VIDEO_PREFLIGHT_CONTRACT.md`` §9-R).

Every test uses a temporary database + temporary managed root and
synthetic ffmpeg fixtures under ``tmp_path`` (lavfi testsrc + sine).
Tests skip gracefully when ffmpeg/ffprobe is not available.
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
from sqlalchemy.orm import Session

from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import Project, VideoItem, Workspace
from app.services.video_import import (
    CODE_HDR_UNSUPPORTED,
    CODE_NO_AUDIO_STREAM,
    CODE_UNSUPPORTED_AUDIO_CODEC,
    CODE_UNSUPPORTED_CODEC,
    CODE_UNSUPPORTED_CONTAINER,
    register_analyze_media_handler,
    submit_import,
)
from app.workflow.durable_worker import DurableWorker, WorkerConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


# ── Deterministic clock/sleeper (mirror test_video_import.py) ───────────────


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ── DB / worker fixtures (temp DB only — MOTIONFORGE_DATABASE_URL unused) ───


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


@pytest.fixture()
def session_factory(tmp_path: Path):
    """Session factory bound to an upgraded temporary database."""
    db_path = tmp_path / "s11_audio.db"
    command.upgrade(_alembic_config(db_path), "head")
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def session(session_factory) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture()
def ws(session: Session) -> Workspace:
    ws = Workspace(name="S11 Audio Workspace")
    session.add(ws)
    session.commit()
    return ws


@pytest.fixture()
def project(session: Session, ws: Workspace) -> Project:
    project = Project(
        name="S11 Audio Project", workspace_id=ws.id, status="active"
    )
    session.add(project)
    session.commit()
    return project


@pytest.fixture()
def video_item(session: Session, project: Project) -> VideoItem:
    item = VideoItem(
        project_id=project.id,
        title="S11 Clip",
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
def worker(session_factory, managed_root: Path) -> DurableWorker:
    w = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="s11-audio-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
        clock=FakeClock(),
        sleeper=FakeSleeper(),
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


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)


def _make_video(
    path: Path,
    *,
    vcodec: str = "libx264",
    acodec: str = "aac",
    pix_fmt: str = "yuv420p",
    audio: bool = True,
    duration: float = 1.0,
    fps: int = 30,
    extra_audio_streams: list[str] | None = None,
) -> Path | None:
    """Create a synthetic MP4; optional extra audio streams appended after
    the first (``extra_audio_streams`` holds additional audio codecs)."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=320x240:rate={fps}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    for i, _codec in enumerate(extra_audio_streams or []):
        cmd += [
            "-f", "lavfi",
            "-i", f"sine=frequency={880 * (i + 1)}:duration={duration}",
        ]
    cmd += ["-c:v", vcodec, "-preset", "ultrafast", "-crf", "28", "-pix_fmt", pix_fmt]
    if audio:
        codecs = [acodec, *(extra_audio_streams or [])]
        cmd += ["-c:a", codecs[0], "-b:a", "64k"]
        for stream_pos, codec in enumerate(codecs[1:], start=1):
            cmd += [f"-c:a:{stream_pos}", codec]
        cmd.append("-shortest")
    else:
        # Explicit stream maps keep the no-audio case free of default mappings.
        cmd += ["-map", "0:v"]
    cmd.append(str(path))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return path


def _submit_and_run(worker, session_factory, ws, video_item, source, managed_root):
    result = submit_import(
        session_factory,
        workspace_id=ws.id,
        project_id=video_item.project_id,
        video_item_id=video_item.id,
        source_path=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        managed_root=managed_root,
        title=source.name,
    )
    worker.run_once()
    return result


def _job_state(session_factory, job_id: str) -> str:
    with session_factory() as s:
        return JobRepository(s).get_job(job_id).state


def _job_error_code(session_factory, job_id: str) -> str:
    with session_factory() as s:
        error = JobRepository(s).get_job(job_id).error
        assert error is not None, "expected a failed job with an error envelope"
        return error["error_code"]


def _checkpoint_probe(session_factory, job_id: str) -> dict:
    with session_factory() as s:
        steps = JobRepository(s).list_steps(job_id)
        checkpoint = steps[0].checkpoint or {}
        return checkpoint["probe"]


def _artifact_file(managed_root: Path, relative_path: str) -> Path:
    target = managed_root / relative_path
    assert target.is_file(), f"published artifact missing: {target}"
    return target


# ── Required test 1: AAC remains accepted ────────────────────────────────────


def test_required_1_aac_first_audio_remains_accepted(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(tmp_path / "aac.mp4", acodec="aac")
    assert source is not None, "ffmpeg could not produce the AAC fixture"
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "completed"
    probe = _checkpoint_probe(session_factory, result.job_id)
    assert probe["has_audio"] is True
    assert probe["audio_stream"]["codec_name"] == "aac"
    # No audio-related warnings at all for a clean AAC input.
    codes = [w["code"] for w in probe["warnings"]]
    assert CODE_NO_AUDIO_STREAM not in codes
    assert CODE_UNSUPPORTED_AUDIO_CODEC not in codes


# ── Required test 2: No-audio remains accepted ───────────────────────────────


def test_required_2_no_audio_remains_accepted_with_warning(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(tmp_path / "noaudio.mp4", audio=False)
    assert source is not None, "ffmpeg could not produce the no-audio fixture"
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "completed"
    probe = _checkpoint_probe(session_factory, result.job_id)
    assert probe["has_audio"] is False
    assert probe["audio_stream"] is None
    codes = [w["code"] for w in probe["warnings"]]
    assert CODE_NO_AUDIO_STREAM in codes


# ── Required test 3: non-AAC first audio → accept WITH explicit warning ─────


@pytest.mark.parametrize("non_aac_codec", ["libmp3lame", "ac3"])
def test_required_3_non_aac_first_audio_accepted_with_explicit_warning(
    worker, session_factory, ws, video_item, managed_root, tmp_path, non_aac_codec
) -> None:
    source = _make_video(tmp_path / f"nonaac-{non_aac_codec}.mp4", acodec=non_aac_codec)
    assert source is not None, f"ffmpeg could not produce the {non_aac_codec} fixture"
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    # Accepted — NOT rejected for the audio codec.
    assert _job_state(session_factory, result.job_id) == "completed"

    probe = _checkpoint_probe(session_factory, result.job_id)
    assert probe["has_audio"] is True
    assert probe["audio_stream"]["codec_name"] != "aac"
    audio_warnings = [
        w for w in probe["warnings"] if w["code"] == CODE_UNSUPPORTED_AUDIO_CODEC
    ]
    assert len(audio_warnings) == 1, probe["warnings"]
    warning = audio_warnings[0]
    assert warning["severity"] == "warning"
    assert warning["location"] == "audio_stream.codec_name"
    assert warning["details"]["audio_codec"] == probe["audio_stream"]["codec_name"]
    # Reason: accepted-with-warning semantics + downstream transcode owner.
    assert "accepted with warning" in warning["reason"]
    assert "transcode to AAC" in warning["reason"]
    # Action (VN): import still happens, ATTACH_ORIGINAL_AUDIO auto-transcodes,
    # and the stale convert-then-retry guidance is gone.
    action = warning["action"]
    assert "vẫn được import" in action
    assert "transcode sang AAC" in action
    assert "thử lại" not in action


# ── Required test 4: unsupported video codec still rejected ─────────────────


def test_required_4_unsupported_video_codec_still_rejected(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(tmp_path / "mpeg4.mp4", vcodec="mpeg4", acodec="aac")
    assert source is not None, "ffmpeg could not produce the mpeg4 fixture"
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "failed"
    assert (
        _job_error_code(session_factory, result.job_id) == CODE_UNSUPPORTED_CODEC
    )


# ── Required test 5: unsupported container still rejected ───────────────────


def test_required_5_unsupported_container_still_rejected(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(tmp_path / "clip.mkv", acodec="aac")
    assert source is not None, "ffmpeg could not produce the mkv fixture"
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "failed"
    assert (
        _job_error_code(session_factory, result.job_id)
        == CODE_UNSUPPORTED_CONTAINER
    )


# ── Required test 6: HDR/10-bit policy unchanged ─────────────────────────────


def test_required_6_hdr_10bit_policy_unchanged(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(
        tmp_path / "hdr.mp4", acodec="aac", pix_fmt="yuv420p10le"
    )
    if source is None:
        pytest.skip("this ffmpeg build cannot produce a 10-bit x264 fixture")
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "failed"
    assert _job_error_code(session_factory, result.job_id) == CODE_HDR_UNSUPPORTED


# ── Required test 7: first audio stream remains canonical ────────────────────


def test_required_7_first_audio_stream_remains_canonical(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    # Two audio streams: first AAC (canonical), second MP3 (ignored).
    source = _make_video(
        tmp_path / "dual.mp4", acodec="aac", extra_audio_streams=["libmp3lame"]
    )
    if source is None:
        pytest.skip("ffmpeg could not produce the dual-audio fixture")
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "completed"
    probe = _checkpoint_probe(session_factory, result.job_id)
    # The canonical audio payload IS the first audio stream: AAC at its
    # ffprobe index, not the second (MP3) stream.
    assert probe["audio_stream"]["codec_name"] == "aac"
    assert probe["audio_stream"]["index"] == 1
    # No non-AAC warning: the ignored second stream must not leak into policy.
    codes = [w["code"] for w in probe["warnings"]]
    assert CODE_UNSUPPORTED_AUDIO_CODEC not in codes


# ── Required test 8: multi-stream input is never merged ──────────────────────


def test_required_8_multi_stream_input_not_merged(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(
        tmp_path / "multi.mp4", acodec="aac", extra_audio_streams=["aac"]
    )
    if source is None:
        pytest.skip("ffmpeg could not produce the multi-audio fixture")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "completed"
    probe = _checkpoint_probe(session_factory, result.job_id)
    # Exactly ONE canonical audio payload is recorded (no merged mix-down).
    assert probe["has_audio"] is True
    assert isinstance(probe["audio_stream"], dict)
    # The published artifact is the untouched multi-stream container itself —
    # streams were copied verbatim, never re-mixed into one stream.
    with session_factory() as s:
        from app.persistence.models import Artifact

        art = s.query(Artifact).filter(Artifact.workspace_id == ws.id).one()
        rel = art.relative_path
    artifact = _artifact_file(managed_root, rel)
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == source_sha


# ── Required test 9: probe/checkpoint retains codec/index/channels/rate ──────


def test_required_9_checkpoint_retains_audio_metadata(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(tmp_path / "meta.mp4", acodec="aac")
    assert source is not None, "ffmpeg could not produce the metadata fixture"
    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "completed"
    probe = _checkpoint_probe(session_factory, result.job_id)
    audio = probe["audio_stream"]
    assert set(audio) >= {"index", "codec_name", "channels", "sample_rate"}
    assert audio["codec_name"] == "aac"
    assert audio["index"] == 1
    assert audio["channels"] >= 1
    assert audio["sample_rate"] > 0


# ── Required test 10: import does not transcode or mutate the source ────────


def test_required_10_import_does_not_transcode_or_mutate_source(
    worker, session_factory, ws, video_item, managed_root, tmp_path
) -> None:
    source = _make_video(tmp_path / "verbatim.mp4", acodec="libmp3lame")
    assert source is not None, "ffmpeg could not produce the MP3 fixture"
    before = source.read_bytes()
    source_sha = hashlib.sha256(before).hexdigest()

    result = _submit_and_run(
        worker, session_factory, ws, video_item, source, managed_root
    )
    assert _job_state(session_factory, result.job_id) == "completed"

    # Source bytes are untouched after a completed import.
    assert source.exists()
    assert source.read_bytes() == before

    # The published artifact is BYTE-IDENTICAL to the source: import copied,
    # it did not transcode (a transcode would change the bytes/sha).
    with session_factory() as s:
        from app.persistence.models import Artifact

        art = s.query(Artifact).filter(Artifact.workspace_id == ws.id).one()
        rel = art.relative_path
        assert art.sha256 == source_sha
    artifact = _artifact_file(managed_root, rel)
    assert artifact.read_bytes() == before

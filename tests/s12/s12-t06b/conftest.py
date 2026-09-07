"""S12-T06B shared fixtures — isolated DB + real-media builders + tier marks.

Scope rules (prompt item 5):
- READ-ONLY production: this module only *calls* production code, never
  edits it, and never touches the dev/MAIN database.
- Isolated evidence: every fixture uses a fresh migrated temp DB under
  ``tempfile`` plus a pytest ``tmp_path`` workdir.
- Tier marks: MEASURED (real measured evidence on this host),
  SIMULATED (synthetic/derived, method stated), NOT_RUN (missing env,
  reason stated — never a fake pass).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WS = "ws-s12t06b"
FPS = 10.0

#: Labeled upscale method for the 1080p -> 2160p Scenario F leg.
UPSCALE_METHOD_LABEL = "lanczos-ffmpeg-scale-x4"

#: Set S12_T06B_CLEAN_MACHINE=1 only on a real clean VM/isolated host.
#: A clean venv on the dev host must NEVER count as a clean machine.
CLEAN_MACHINE = os.environ.get("S12_T06B_CLEAN_MACHINE") == "1"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "measured: real measured evidence on this host")
    config.addinivalue_line("markers", "simulated: synthetic/derived evidence, method stated")
    config.addinivalue_line("markers", "not_run: missing environment, reason stated")


# ── toolchain ──────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    links = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Links"
        / "ffmpeg.exe"
    )
    if links.is_file():
        return str(links)
    raise FileNotFoundError("ffmpeg not found (needed for S12-T06B media)")


def _find_ffprobe() -> str:
    found = shutil.which("ffprobe")
    if found:
        return found
    links = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Links"
        / "ffprobe.exe"
    )
    if links.is_file():
        return str(links)
    raise FileNotFoundError("ffprobe not found (needed for S12-T06B probes)")


def ffprobe_json(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            _find_ffprobe(),
            "-hide_banner",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, f"ffprobe failed: {completed.stderr[:300]}"
    import json as _json

    payload: dict[str, Any] = _json.loads(completed.stdout)
    return payload


def probe_dims(path: Path) -> tuple[int, int]:
    payload = ffprobe_json(path)
    streams = payload.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    assert video, f"no video stream in {path}"
    return int(video[0]["width"]), int(video[0]["height"])


def probe_has_audio(path: Path) -> bool:
    payload = ffprobe_json(path)
    return any(s.get("codec_type") == "audio" for s in payload.get("streams", []))


def decode_audio_to_wav(src: Path, dest: Path) -> int:
    """Decode (listen to) the real audio track; returns wav byte size."""
    completed = subprocess.run(
        [
            _find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, f"audio decode failed: {completed.stderr[:300]}"
    return dest.stat().st_size


# ── real media builders (testsrc + sine, never synthetic metadata) ──────

def build_source_1080p(dest: Path, *, duration: float = 3.0) -> Path:
    """Validated 1920x1080 h264 @10fps source WITH a real sine audio track."""
    cmd = [
        _find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=1920x1080:rate={FPS}:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, f"ffmpeg failed: {completed.stderr[:500]}"
    assert dest.is_file()
    return dest


def build_native_4k(dest: Path, *, duration: float = 2.0) -> Path:
    """Real 3840x2160 h264 @10fps source WITH a real sine audio track."""
    cmd = [
        _find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=3840x2160:rate={FPS}:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, f"ffmpeg failed: {completed.stderr[:500]}"
    assert dest.is_file()
    return dest


def upscale_to_4k(src: Path, dest: Path) -> str:
    """Real 1080p -> 3840x2160 upscale (lanczos, audio preserved).

    Returns the method label the caller must attach to the export
    provenance — an unlabeled upscale is a Scenario F failure.
    """
    completed = subprocess.run(
        [
            _find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            "scale=3840:2160:flags=lanczos",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert completed.returncode == 0, f"upscale failed: {completed.stderr[:500]}"
    assert dest.is_file()
    return UPSCALE_METHOD_LABEL


# ── hardware / clean-machine probes ─────────────────────────────────────

def gpu_info() -> list[str]:
    """Best-effort nvidia-smi readout; [] means GPU NOT_RUN (never faked)."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    return proc.stdout.strip().splitlines()


def cpu_info() -> str:
    try:
        proc = subprocess.run(
            ["wmic", "cpu", "get", "name", "/value"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return "cpu-unreadable"


@pytest.fixture()
def require_clean_machine() -> bool:
    """Clean VM/isolated host only; skips as NOT_RUN everywhere else."""
    if not CLEAN_MACHINE:
        pytest.skip(
            "NOT_RUN: no clean VM/isolated machine present "
            "(set S12_T06B_CLEAN_MACHINE=1 on a clean host; "
            "a clean venv on the dev host does NOT qualify)"
        )
    return True


# ── isolated DB (never MAIN/dev) ────────────────────────────────────────

CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _manifest(frame_count: int = 30) -> dict[str, Any]:
    return {
        "frame_count": frame_count,
        "timebase": {"fps": float(FPS), "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


def seed_lineage(factory: Any, frame_count: int = 30) -> str:
    """Seed workspace/project/video/checkpoint/lock; returns manifest_id."""
    from sqlalchemy import text as _text

    from app.persistence.structural_lock import StructuralLockRepository

    with factory() as seed:
        seed.execute(_text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        seed.execute(
            _text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
            {"p": f"p-{WS}", "w": WS},
        )
        seed.execute(
            _text(
                "INSERT INTO video_item(id,project_id,title,position)"
                " VALUES (:v,:p,'Vid',0)"
            ),
            {"v": f"v-{WS}", "p": f"p-{WS}"},
        )
        seed.execute(
            _text(
                "INSERT INTO character(id,workspace_id,name,code)"
                " VALUES ('ch-a',:w,'H','h-a')"
            ),
            {"w": WS},
        )
        seed.execute(
            _text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,"
                "version,status) VALUES ('pv-a','ch-a',:w,1,'published')"
            ),
            {"w": WS},
        )
        seed.execute(
            _text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) VALUES ('rl-a',:w,:p,:v,'g',"
                "'C','character','confirmed')"
            ),
            {"w": WS, "p": f"p-{WS}", "v": f"v-{WS}"},
        )
        seed.execute(
            _text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,"
                "object_role_id,cast_mapping_id,character_id,pack_version_id,"
                "params_json,idempotency_key,revision) VALUES ('rc-a',:w,:p,"
                "'rl-a',NULL,'ch-a','pv-a','{}',NULL,1)"
            ),
            {"w": WS, "p": f"p-{WS}"},
        )
        seed.execute(
            _text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                "loop_hashes_json,timebase_fingerprint,snapshot_json,"
                "checkpoint_hash,note,idempotency_key,revision)"
                " VALUES ('ac-a',:w,:p,'rc-a',1,'[]','[]','tb','{}',"
                ":h,NULL,NULL,1)"
            ),
            {"w": WS, "p": f"p-{WS}", "h": CHK_HASH},
        )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(
                WS, f"p-{WS}", f"v-{WS}", "gen1", _manifest(frame_count)
            )
            s2.commit()
            return str(m1.id)


@pytest.fixture()
def db_factory(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Fresh migrated temp DB factory + manifest_id (isolated, per-test)."""
    from app.persistence import create_engine_for_path, create_session_factory

    db = Path(tempfile.mkdtemp(prefix="s12t06b_")) / "t06b.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    manifest_id = seed_lineage(factory)
    yield factory, manifest_id
    create_engine_for_path(db).dispose()


# ── preflight request/ctx builders (pure, no I/O) ───────────────────────

def make_request(video_item_id: str, **over: Any):  # type: ignore[no-untyped-def]
    from app.schemas.s12_export import ExportPreflightRequest

    kw: dict[str, Any] = {
        "video_item_id": video_item_id,
        "profile_id": "master-4k-h264",
        "aspect_handling": "letterbox",
        "checkpoint": {
            "checkpoint_id": "ac-a",
            "checkpoint_hash": CHK_HASH,
            "checkpoint_revision": 1,
        },
        "lock": {
            "manifest_id": "m-a",
            "manifest_hash": PLAN_HASH,
            "source_generation": "gen1",
        },
    }
    kw.update(over)
    return ExportPreflightRequest(**kw)


def ok_ctx(**over: Any):  # type: ignore[no-untyped-def]
    """Eligible-unless-overridden PreflightContext (isolates one gate)."""
    from app.services.s12_export.preflight import PreflightContext

    kw: dict[str, Any] = {
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "source_found": True,
        "source_ready": True,
        "source_is_partial": False,
        "source_width": 1920,
        "source_height": 1080,
        "source_frame_count": 30,
        "source_native_4k": False,
        "upscale_method": UPSCALE_METHOD_LABEL,
        "checkpoint_found": True,
        "checkpoint_hash_match": True,
        "checkpoint_revision_match": True,
        "checkpoint_cross_project": False,
        "lock_found": True,
        "lock_hash_match": True,
        "lock_generation_match": True,
        "readiness_status": "ready",
        "readiness_policy": "pol",
        "readiness_policy_current": True,
        "disk_free_bytes": 10**13,
        "profile_supported": True,
        "profile_support_basis": "t06b isolated probe basis",
    }
    kw.update(over)
    return PreflightContext(**kw)

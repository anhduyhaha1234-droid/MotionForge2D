"""S12-T03B fixtures — migrated temp DB + seed lineage + real media builders.

Isolated per-test DB (never MAIN): mirrors the T03A seed (workspace /
project / video_item / checkpoint / structural-lock manifest) plus a real
ffmpeg-built validated source clip.  Nothing touches shared conftest or
any test authority outside ``tests/s12/s12-t03b/``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.s12_export import S12ExportRepository
from app.persistence.structural_lock import StructuralLockRepository

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WS = "ws-s12t03b"
FPS = 10
DURATION = 3.0
FRAMES = int(FPS * DURATION)  # 30 frames
WIDTH = 320
HEIGHT = 180

CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _manifest(frame_count: int = FRAMES) -> dict[str, Any]:
    return {
        "frame_count": frame_count,
        "timebase": {"fps": float(FPS), "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


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
    raise FileNotFoundError("ffmpeg not found (needed for S12-T03B media)")


def build_source(dest: Path, *, audio: bool = False) -> Path:
    """Encode the validated source: testsrc 320x180 h264 @10fps x3s + opt sine."""
    cmd = [
        _find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={DURATION}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={DURATION}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(dest))
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, f"ffmpeg failed: {completed.stderr[:500]}"
    assert dest.is_file()
    return dest


@pytest.fixture()
def ctx(tmp_path):  # type: ignore[no-untyped-def]
    """Yield (factory, manifest_id, source_path, audio_path, workdir)."""
    db = Path(__import__("tempfile").mkdtemp(prefix="s12t03b_")) / "t03b.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        seed.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        seed.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
            {"p": f"p-{WS}", "w": WS},
        )
        seed.execute(
            text("INSERT INTO video_item(id,project_id,title,position)"
                 " VALUES (:v,:p,'Vid',0)"),
            {"v": f"v-{WS}", "p": f"p-{WS}"},
        )
        seed.execute(
            text("INSERT INTO character(id,workspace_id,name,code)"
                 " VALUES ('ch-a',:w,'H','h-a')"),
            {"w": WS},
        )
        seed.execute(
            text("INSERT INTO character_pack_version(id,character_id,workspace_id,"
                 "version,status) VALUES ('pv-a','ch-a',:w,1,'published')"),
            {"w": WS},
        )
        seed.execute(
            text("INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                 "source_generation,name,kind,status) VALUES ('rl-a',:w,:p,:v,'g',"
                 "'C','character','confirmed')"),
            {"w": WS, "p": f"p-{WS}", "v": f"v-{WS}"},
        )
        seed.execute(
            text("INSERT INTO reskin_config(id,workspace_id,project_id,"
                 "object_role_id,cast_mapping_id,character_id,pack_version_id,"
                 "params_json,idempotency_key,revision) VALUES ('rc-a',:w,:p,"
                 "'rl-a',NULL,'ch-a','pv-a','{}',NULL,1)"),
            {"w": WS, "p": f"p-{WS}"},
        )
        seed.execute(
            text("INSERT INTO apply_checkpoint(id,workspace_id,project_id,"
                 "reskin_config_id,reskin_config_revision,pack_version_ids_json,"
                 "loop_hashes_json,timebase_fingerprint,snapshot_json,"
                 "checkpoint_hash,note,idempotency_key,revision)"
                 " VALUES ('ac-a',:w,:p,'rc-a',1,'[]','[]','tb','{}',"
                 ":h,NULL,NULL,1)"),
            {"w": WS, "p": f"p-{WS}", "h": CHK_HASH},
        )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(WS, f"p-{WS}", f"v-{WS}", "gen1", _manifest())
            s2.commit()
            manifest_id = m1.id
    workdir = tmp_path / "work"
    workdir.mkdir()
    source = build_source(workdir / "source.mp4")
    audio_src = build_source(workdir / "source_audio.mp4", audio=True)
    yield factory, manifest_id, source, audio_src, workdir
    engine = create_engine_for_path(db)
    engine.dispose()


def make_run(factory, manifest_id: str, **over):  # type: ignore[no-untyped-def]
    """Create + claim a run; returns (run, lease, manifest_hash)."""
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        assert row is not None
        manifest_hash = str(row.manifest_hash)
    kw: dict[str, Any] = {
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": manifest_hash,
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": FRAMES,
        "chunk_config": {"overlap": 4, "max_frames": 12},
    }
    kw.update(over)
    with factory() as s:
        repo = S12ExportRepository(s)
        run, _ = repo.create_run(**kw)
        lease = repo.claim_run(run.id, "worker-1")
        s.commit()
        return run, lease


def make_config(run, lease, source, workdir, **over):  # type: ignore[no-untyped-def]
    from app.services.s12_export.runner import RunnerConfig

    kw: dict[str, Any] = {
        "run_id": run.id,
        "workspace_id": WS,
        "worker_id": "worker-1",
        "fence_token": lease.fence_token,
        "source_path": source,
        "fps": float(FPS),
        "chunk_dir": workdir / "chunks",
        "scratch_dir": workdir / "scratch",
        "output_path": workdir / "export.mp4",
        "audio_source": None,
        "max_frames_per_chunk": 12,
        "overlap_frames": 4,
    }
    kw.update(over)
    return RunnerConfig(**kw)

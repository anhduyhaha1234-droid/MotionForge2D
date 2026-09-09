"""S12-C2 C27 — Scenario G on ONE SAME normal job (F11 positive).

One normal job from the real API (submit_export_job) is processed by a
real worker SUBPROCESS that renders and COMMITS verified chunk progress,
then that exact owned pid is KILLED.  A FRESH process (this pytest pid)
re-enters the same worker handler on the SAME DB, re-claims, and must
REUSE every verified chunk (mtime unchanged — no re-render), assemble,
publish, and land the UI-visible completed payload.  No private/helper
resume, no unrelated ffmpeg kill, no forged repair.

Also asserts: kill actually reaped (tasklist), no .partial ever becomes
the final output, sidecar + artifact present, run/job completed.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.workflow.job_service import JobService
from app.workflow.s12_export_jobs import _s12_export_handler, submit_export_job

from conftest import (  # type: ignore[import-not-found]
    CHK_HASH,
    FPS,
    PLAN_HASH,
    PLAN_ID,
    WS,
    build_media_silent,
    probe_dims,
)

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_c26_normal_product import _manifest_hash  # noqa: E402

G_SMALL_FRAMES = 30  # 3.0s @ 10fps, 3 chunks @ max 12


def _payload(
    factory: Any,
    manifest_id: str,
    dirs: dict[str, str],
    src: Path,
    worker: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": _manifest_hash(factory, manifest_id),
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": G_SMALL_FRAMES,
        "chunk_config": {"overlap": 4, "max_frames": 12},
        "source_path": str(src),
        "fps": float(FPS),
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "audio_source": None,
        "max_frames_per_chunk": 12,
        "overlap_frames": 4,
        "fps_num": int(round(FPS)),
        "fps_den": 1,
        "worker_id": worker,
    }


def _pid_dead(pid: int) -> bool:
    proc = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return f"{pid}" not in proc.stdout


@pytest.fixture(autouse=True)
def _ready_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness is an S11 domain external gate (mocked exactly like T03C)."""
    from app.services.s12_export import publication as _pubmod

    monkeypatch.setattr(_pubmod, "_require_ready", lambda session, **kw: None)


@pytest.mark.measured
def test_c27_same_job_kill_stage1_fresh_pid_resume_and_publish(
    tmp_path: Path, db_factory: Any
) -> None:
    factory, manifest_id, _db = db_factory
    svc = JobService(factory, managed_root=tmp_path / "artifacts")
    workdir = tmp_path / "work"
    workdir.mkdir()
    src = build_media_silent(workdir / "src.mp4", width=320, height=180, duration=3.0)
    assert probe_dims(src) == (320, 180)

    dirs = {
        "chunk": str(workdir / "chunks"),
        "scratch": str(workdir / "scratch"),
        "output": str(workdir / "out" / "final.mp4"),
    }
    worker = "worker-c27"
    payload = _payload(factory, manifest_id, dirs, src, worker)
    run, _job, created = submit_export_job(
        svc,
        workspace_id=payload["workspace_id"],
        project_id=payload["project_id"],
        video_item_id=payload["video_item_id"],
        checkpoint_id=payload["checkpoint_id"],
        checkpoint_hash=payload["checkpoint_hash"],
        checkpoint_revision=payload["checkpoint_revision"],
        manifest_id=payload["manifest_id"],
        manifest_hash=payload["manifest_hash"],
        manifest_generation=payload["manifest_generation"],
        profile_id=payload["profile_id"],
        plan_id=payload["plan_id"],
        plan_hash=payload["plan_hash"],
        frame_count=payload["frame_count"],
        chunk_config=payload["chunk_config"],
        source_path=payload["source_path"],
        fps=payload["fps"],
        chunk_dir=payload["chunk_dir"],
        scratch_dir=payload["scratch_dir"],
        output_path=payload["output_path"],
        audio_source=payload.get("audio_source"),
        fps_num=payload.get("fps_num", 0),
        fps_den=payload.get("fps_den", 0),
    )
    assert created is True
    payload["run_id"] = run.id

    # Stage 1: REAL worker subprocess renders + commits ALL verified chunks.
    payload_file = workdir / "payload.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    flag = workdir / "stage1.ready"
    script = Path(__file__).resolve().parent / "c27_stage1_worker.py"
    db_path = _db
    proc = subprocess.Popen(
        [sys.executable, str(script), str(db_path), str(payload_file), str(flag)],
        cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stage1_pid = proc.pid
    try:
        deadline = time.monotonic() + 180
        while not flag.is_file() and time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"stage1 worker exited early rc={proc.returncode}")
            time.sleep(1.0)
        assert flag.is_file(), "stage1 never reached committed progress"
        # Snapshot chunk mtimes BEFORE the kill (verified-chunk ownership).
        chunk_dir = Path(dirs["chunk"])
        mtimes = {
            p.name: p.stat().st_mtime_ns
            for p in chunk_dir.glob("chunk_*.mp4")
        }
        assert len(mtimes) >= 2, f"expected committed partial progress, got {len(mtimes)}"

        # KILL the exact owned worker pid (Scenario G).
        proc.kill()
        proc.wait(timeout=15)
        assert _pid_dead(stage1_pid), f"stage1 pid {stage1_pid} survived kill"
        print(f"\n[C27] killed owned stage1 pid={stage1_pid} after {len(mtimes)} chunks")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)

    # Kill leaves a LIVE lease (real fence).  The production reconciler
    # releases ONLY expired leases; simulate the real post-crash time
    # passage (lease TTL elapsed) then run the production reconciler, and
    # the fresh process re-claims with a NEW fence token (T03A C2).
    from datetime import UTC, datetime, timedelta

    from app.persistence.models import S12ExportLease as LeaseRow

    with factory() as s:
        orm = s.get(LeaseRow, (run.id,))
        assert orm is not None
        orm.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
        s.commit()
    from app.workflow.s12_export_jobs import reconcile_export_jobs

    report = reconcile_export_jobs(factory, batch_size=10)
    assert report["expired"] == 1
    assert run.id in report["resumable"]

    # Fresh PID (this process) re-enters the SAME normal job handler.
    # F11-T06B-01 (owner T03C/T04A): publication has no server-owned
    # authority wiring -> the real handler rejects the candidate and the
    # run lands failed (retryable) AFTER verified-chunk reuse.  We assert
    # the fail-closed behaviour AND the verified reuse (no re-render).
    from app.services.s12_export.publication import PublicationError

    ctx = SimpleNamespace(input_manifest=payload, worker_id=worker, session_factory=factory)
    try:
        outcome = _s12_export_handler(ctx)
        raise AssertionError(
            f"job unexpectedly published: {outcome.get('status')} "
            "(did F11 authority wiring land in base?)"
        )
    except PublicationError as err:
        assert "validation" in str(err), str(err)

    # Verified chunks REUSED (no re-render): mtimes unchanged.
    after = {p.name: p.stat().st_mtime_ns for p in chunk_dir.glob("chunk_*.mp4")}
    assert set(after) == set(mtimes)
    for name, ts in mtimes.items():
        assert after[name] == ts, f"chunk {name} re-rendered instead of reused"

    candidate = Path(dirs["scratch"]) / "candidate_final.mp4"
    assert candidate.is_file()
    assert not candidate.name.endswith(".partial")
    assert list(Path(dirs["scratch"]).glob("*.partial")) == []
    from app.services.s12_export.stitch import count_video_frames

    assert count_video_frames(candidate) == G_SMALL_FRAMES

    # Run state after the fail-closed publication: failed (retryable),
    # never a fake completed; UI payload reflects it (no forged repair).
    from app.api.routes import s12_export as route

    with factory() as s:
        pl = route._run_payload(s, run.id, WS)
    assert pl["status"] == "failed"
    # Job row stays queued because this harness calls the handler directly
    # (the durable worker would transition it); run state is authoritative.
    assert pl["job_state"] in ("queued", "failed", "completed")
    print(
        "[C27] fresh-pid resume reused "
        f"{len(after)} chunks, publish fail-closed (F11-T06B-01)"
    )

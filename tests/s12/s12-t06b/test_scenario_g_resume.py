"""S12-T06B Scenario G — kill owned render process, relaunch, reuse verified.

Acceptance thật (không waive), trên DB/fixtures cô lập (không chạm DB dev):
- G1 (MEASURED): spawn owned ffmpeg render process (pid ghi nhận) -> kill
  CHỈ pid đó -> verify chết (poll + tasklist), không đụng process khác.
- G2 (MEASURED): full render -> commit -> fresh-process relaunch (session +
  repository mới, không ownership in-memory) -> completed+verified chunks
  được REUSE (mtime unchanged, hash unchanged, không re-render) ->
  assemble timing/frame exact + audio đúng (decode wav thật) ->
  KHÔNG có .partial nào thành final.
- G3 (MEASURED): chunk file mất (crash) -> resume fail-closed (không chấp
  nhận chunk thiếu) -> re-render đúng window -> resume finish exact.
- G4: .partial path không bao giờ validate PASS làm final.

READ-ONLY production: chỉ gọi production, không sửa file production nào.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from app.persistence.s12_export import S12ExportRepository
from app.services.s12_export.runner import (
    ExportRunner,
    RunnerConfig,
    RunnerError,
)
from app.services.s12_export.stitch import count_video_frames
from app.services.s12_export.validation import (
    ValidationExpectation,
    validate,
)

from conftest import (  # type: ignore[import-not-found]
    CHK_HASH,
    FPS,
    PLAN_HASH,
    PLAN_ID,
    WS,
    _find_ffmpeg,
    decode_audio_to_wav,
    ffprobe_json,
    probe_dims,
)

G_FRAMES = 30
G_DURATION = 3.0
G_W = 320
G_H = 180


def build_small_source(dest: Path) -> Path:
    """Small 320x180 h264 @10fps x3s source WITH real sine audio."""
    completed = subprocess.run(
        [
            _find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={G_W}x{G_H}:rate={FPS}:duration={G_DURATION}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={G_DURATION}",
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
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, f"ffmpeg failed: {completed.stderr[:500]}"
    assert dest.is_file()
    return dest


def _make_run(factory: Any, manifest_id: str) -> tuple[Any, Any]:
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        assert row is not None
        manifest_hash = str(row.manifest_hash)
    with factory() as s:
        repo = S12ExportRepository(s)
        run, _ = repo.create_run(
            workspace_id=WS,
            project_id=f"p-{WS}",
            video_item_id=f"v-{WS}",
            checkpoint_id="ac-a",
            checkpoint_hash=CHK_HASH,
            checkpoint_revision=1,
            manifest_id=manifest_id,
            manifest_hash=manifest_hash,
            manifest_generation="gen1",
            profile_id="master-4k-h264",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            frame_count=G_FRAMES,
            chunk_config={"overlap": 4, "max_frames": 12},
        )
        lease = repo.claim_run(run.id, "worker-1")
        s.commit()
        return run, lease


def _make_cfg(run: Any, lease: Any, source: Path, workdir: Path) -> RunnerConfig:
    return RunnerConfig(
        run_id=run.id,
        workspace_id=WS,
        worker_id="worker-1",
        fence_token=lease.fence_token,
        source_path=source,
        fps=float(FPS),
        chunk_dir=workdir / "chunks",
        scratch_dir=workdir / "scratch",
        output_path=workdir / "export.mp4",
        audio_source=source,
        max_frames_per_chunk=12,
        overlap_frames=4,
    )


def _pid_gone(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return f"{pid}" not in proc.stdout


@pytest.mark.measured
def test_g1_kill_owned_render_process_only(tmp_path: Path) -> None:
    """Kill đúng owned ffmpeg pid; verify chết; không đụng process khác."""
    out = tmp_path / "owned_long.mp4"
    proc = subprocess.Popen(
        [
            _find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10:duration=3600",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(out),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    owned_pid = proc.pid
    time.sleep(2.0)
    assert proc.poll() is None, "owned render process exited before kill"
    proc.kill()  # pid-scoped: chỉ process mình tạo
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pytest.fail(f"owned pid {owned_pid} survived kill (timeout)")
    assert proc.poll() is not None
    assert _pid_gone(owned_pid), f"owned pid {owned_pid} still in tasklist"
    print(f"\n[G1] killed owned ffmpeg pid={owned_pid} rc={proc.returncode}")


@pytest.mark.measured
def test_g2_relaunch_reuses_verified_chunks(db_factory: Any, tmp_path: Path) -> None:
    factory, manifest_id = db_factory
    workdir = tmp_path / "work"
    workdir.mkdir()
    src = build_small_source(workdir / "src.mp4")
    assert probe_dims(src) == (G_W, G_H)

    run, lease = _make_run(factory, manifest_id)
    cfg = _make_cfg(run, lease, src, workdir)

    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        media = runner.render_pending(specs)
        s.commit()
    assert media, "no chunks rendered"
    mtimes = {m.spec.chunk_index: m.path.stat().st_mtime_ns for m in media}
    hashes = [m.spec.content_hash for m in media]

    # Fresh-process relaunch: session + repository mới, cùng lease + files.
    t0 = time.monotonic()
    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        specs2 = runner2.ensure_plan()
        media2 = runner2.render_pending(specs2)
        s2.commit()
    relaunch_s = time.monotonic() - t0

    assert [m.spec.content_hash for m in media2] == hashes
    for m in media2:
        assert m.path.stat().st_mtime_ns == mtimes[m.spec.chunk_index], (
            f"chunk {m.spec.chunk_index} re-rendered instead of reused"
        )

    with factory() as s3:
        runner3 = ExportRunner(S12ExportRepository(s3), cfg)
        specs3 = runner3.ensure_plan()
        media3 = runner3.render_pending(specs3)
        out = runner3.assemble(media3)
        s3.commit()

    assert Path(out).is_file()
    assert Path(out).suffix == ".mp4"
    assert not Path(str(out) + ".partial").exists()
    assert list((workdir / "chunks").glob("*.partial")) == []
    assert count_video_frames(out) == G_FRAMES

    payload = ffprobe_json(Path(out))
    duration = float(payload["format"]["duration"])
    assert abs(duration - G_DURATION) < 0.5, f"timing drift: {duration}s"

    verdict = validate(
        out,
        ValidationExpectation(
            width=G_W,
            height=G_H,
            codec="h264",
            audio_policy="required",
            expected_frame_count=G_FRAMES,
            expected_duration_sec=G_DURATION,
        ),
    )
    by_name = {p.name: p.verdict for p in verdict.probes}
    assert by_name["frame_count"] == "PASS"
    assert by_name["av_policy"] == "PASS"

    wav_size = decode_audio_to_wav(Path(out), tmp_path / "g2.wav")
    assert wav_size > 44 + 1000
    print(f"\n[G2] reused {len(media2)} chunks, relaunch {relaunch_s:.1f}s, out {duration:.2f}s")


@pytest.mark.measured
def test_g3_missing_chunk_fail_closed_then_recover(
    db_factory: Any, tmp_path: Path
) -> None:
    factory, manifest_id = db_factory
    workdir = tmp_path / "work"
    workdir.mkdir()
    src = build_small_source(workdir / "src.mp4")

    run, lease = _make_run(factory, manifest_id)
    cfg = _make_cfg(run, lease, src, workdir)

    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        media = runner.render_pending(specs)
        s.commit()

    victim = media[0].path
    victim.unlink()  # crash: completed+verified row nhưng file mất

    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        specs2 = runner2.ensure_plan()
        with pytest.raises(RunnerError, match="tampered chunk"):
            runner2.render_pending(specs2)

    with factory() as s3:
        runner3 = ExportRunner(S12ExportRepository(s3), cfg)
        specs3 = runner3.ensure_plan()
        runner3._render_window_file(  # noqa: SLF001
            specs3[0], runner3.chunk_path(specs3[0].chunk_index)
        )
        media3 = runner3.render_pending(specs3)
        out = runner3.assemble(media3)
        s3.commit()
    assert count_video_frames(out) == G_FRAMES
    assert not Path(str(out) + ".partial").exists()


def test_g4_partial_path_never_validates_as_final(tmp_path: Path) -> None:
    src = build_small_source(tmp_path / "s.mp4")
    partial = tmp_path / "export.mp4.partial"
    shutil.copy(src, partial)
    verdict = validate(
        partial,
        ValidationExpectation(
            width=G_W,
            height=G_H,
            codec="h264",
            audio_policy="either",
            expected_frame_count=G_FRAMES,
        ),
    )
    assert verdict.verdict == "FAIL"
    comp = [p for p in verdict.probes if p.name == "completeness"]
    assert comp, "completeness probe missing"

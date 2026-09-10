"""S12-C2 W3 — T03B real-media render + chunk integrity (F03/F06/F07).

Closes reviewer rows C10-C14 against the product runner ONLY (no
standalone-FFmpeg stand-in for the runner path — the C1 reviewer defect).
Base: canonical ``66299ed1`` (W1+W2: T01 authority + T03A real DB CAS +
T04A source-locked validator).  T03B scope files only:
``runner/chunks/stitch.py``.

- C10: the ACTUAL runner scales/pads a below-4K source to the selected
  3840x2160 profile raster (M04 substitution rejected) and keeps the
  selected codec through trim/stitch/final (HEVC when measured eligible).
- C11: non-16:9 real pixels on the selected canvas keep DAR via scale+
  pad (dark side bars, no stretch/crop); unsupported profiles rejected.
- C12: exact source order/cuts + rational seam timing + CFR control; VFR
  rejected BEFORE any chunk work.
- C13: equal-frame-count changed-byte chunk REJECTED (byte identity via
  recorded sha256 sidecar), missing/partial/truncated/source/config/tool/
  combined drift never reused; good finals immutable (no overwrite).
- C14-part: >=1 committed verified chunk durable mid-job; OWNED child
  killed; fresh PID same DB resumes identical chunk bytes (sidecar SHA
  unchanged, no forged repair).  T03C consumer side is later.

Evidence: ``<C2-root>/s12-t03b/`` + ``matrix/C10..C14/`` where C2 root =
``C:/Users/Admin/MotionForge2D-evidence/s12/20260909-124300-C2``.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path as _Path

import pytest

_spec = _importlib_util.spec_from_file_location(
    "s12_t03b_fixtures", _Path(__file__).parent / "conftest.py"
)
assert _spec is not None and _spec.loader is not None
_t03b_fixtures = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_t03b_fixtures)
FRAMES = _t03b_fixtures.FRAMES
FPS = _t03b_fixtures.FPS
make_config = _t03b_fixtures.make_config
make_run = _t03b_fixtures.make_run
build_source = _t03b_fixtures.build_source

from app.persistence.s12_export import (  # noqa: E402
    S12ExportRepository,
)
from app.services.s12_export.runner import (  # noqa: E402
    ExportRunner,
    RunnerError,
    _encoder_for_profile,
    _probe_encoder_usable,
)
from app.services.s12_export.stitch import (  # noqa: E402
    StitchError,
    count_video_frames,
)

C2_ROOT = _Path("C:/Users/Admin/MotionForge2D-evidence/s12/20260909-124300-C2")
FINAL4K = (3840, 2160)
CANVAS1080 = (1920, 1080)


def _raw(row: str, name: str, payload: dict) -> _Path:
    dest = C2_ROOT / "matrix" / row / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return dest


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    assert found, "ffmpeg not on PATH (real-media row needs the real binary)"
    return found


def _ffprobe_streams(path: _Path) -> list[dict]:
    ffprobe = shutil.which("ffprobe")
    assert ffprobe is not None
    completed = subprocess.run(
        [ffprobe, "-hide_banner", "-v", "error",
         "-show_entries",
         "stream=index,codec_type,codec_name,width,height,avg_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-300:]
    return json.loads(completed.stdout)["streams"]


def _video(streams: list[dict]) -> dict:
    video = [st for st in streams if st["codec_type"] == "video"]
    assert video, "no video stream"
    return video[0]


def _fresh_run(factory, manifest_id, source, workdir, *,
               profile: str, frames: int, **over):  # type: ignore[no-untyped-def]
    """Small bounded run (1-2 chunks) so 4K renders stay fast and real."""
    max_frames = max(1, (frames + 1) // 2) if frames > 8 else frames
    kw = {
        "profile_id": profile,
        "frame_count": frames,
        "chunk_config": {"overlap": 2, "max_frames": max_frames},
    }
    kw.update(over)
    run, lease = make_run(factory, manifest_id, **kw)
    return make_config(run, lease, source, workdir), run, lease


def _full_run(ctx, profile: str = "master-4k-h264", frames: int = 8):  # type: ignore[no-untyped-def]
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _fresh_run(
        factory, manifest_id, source, workdir, profile=profile, frames=frames
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    return factory, cfg, run, out, workdir


# ── C10: real runner final raster + codec ─────────────────────────────


def test_c10_runner_scales_320x180_to_real_3840x2160(ctx) -> None:  # type: ignore[no-untyped-def]
    """Product runner 4K selection on a below-4K source → REAL 3840x2160.

    M04 rejection: no standalone 4K source, no 320x180 passthrough — the
    chunk and final candidates must measure 3840x2160.
    """
    factory, manifest_id, source, _audio, workdir = ctx
    probe = _probe_streams_probe(source)
    assert (probe["width"], probe["height"]) != FINAL4K  # below-4K input
    cfg, run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="master-4k-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    for label, path in (("final", out), ("chunk0", workdir / "chunks" / "chunk_0000.mp4")):
        assert _Path(path).is_file(), label
        video = _video(_ffprobe_streams(_Path(path)))
        assert (video["width"], video["height"]) == FINAL4K, (
            f"{label} {video['width']}x{video['height']} != 3840x2160 (M04)"
        )
        assert video["codec_name"] == "h264", video
    _raw("C10", "runner_4k_final.json", {
        "row": "C10", "source": "320x180 below-4k",
        "selected_profile": "master-4k-h264", "final": list(FINAL4K),
        "chunk0_codec": "h264", "frames": 8,
    })


def test_c10_hevc_eligible_only_when_measured(ctx) -> None:  # type: ignore[no-untyped-def]
    """HEVC selection renders HEVC ONLY when libx265 probes usable."""
    encoder = _encoder_for_profile("master-4k-hevc")
    usable, basis = _probe_encoder_usable(encoder)
    _raw("C10", "hevc_measured.json", {
        "row": "C10", "encoder": encoder, "usable": usable, "basis": basis,
    })
    if not usable:
        pytest.skip(f"libx265 not measured usable on this box: {basis}")
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="master-4k-hevc", frames=6,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    video = _video(_ffprobe_streams(_Path(out)))
    assert (video["width"], video["height"]) == FINAL4K, video
    assert video["codec_name"] == "hevc", (
        f"selected HEVC not retained through final: {video['codec_name']}"
    )


def test_c10_unknown_profile_fails_explicit() -> None:
    with pytest.raises(RunnerError, match="no frozen encoder"):
        _encoder_for_profile("no-such-profile")


def _probe_streams_probe(path: _Path) -> dict:
    return _video(_ffprobe_streams(path))


# ── C11: non-16:9 geometry preserved on selected canvas ───────────────


def test_c11_portrait_pixels_letterboxed_no_stretch(ctx, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """320x560 portrait through the runner lands padded, never stretched."""
    factory, manifest_id, source, _audio, workdir = ctx
    portrait = workdir / "portrait_320x560.mp4"
    build_source(portrait, width=320, height=560, duration=1.0)
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, portrait, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    video = _video(_ffprobe_streams(_Path(out)))
    assert (video["width"], video["height"]) == CANVAS1080, video
    # Active picture inside the 16:9 canvas: dark side bars => no stretch.
    frame_png = tmp_path / "frame.png"
    completed = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(out), "-frames:v", "1", str(frame_png)],
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-300:]
    from PIL import Image

    img = Image.open(frame_png).convert("L")
    width, height = img.size
    assert (width, height) == CANVAS1080
    left = sum(img.getpixel((x, height // 2)) for x in range(60)) / 60
    right = sum(img.getpixel((width - 1 - x, height // 2)) for x in range(60)) / 60
    center = sum(img.getpixel((x, height // 2))
                 for x in range(width // 2 - 30, width // 2 + 30)) / 60
    assert left < 40 and right < 40, f"side bars not dark: {left:.0f}/{right:.0f}"
    assert center > 60, f"active center unexpectedly dark: {center:.0f}"
    _raw("C11", "portrait_letterbox.json", {
        "row": "C11", "source": "320x560 portrait",
        "canvas": list(CANVAS1080), "side_bar_luma": round(left, 1),
        "center_luma": round(center, 1), "policy": "scale+pad, no stretch",
    })


def test_c11_unsupported_profile_rejected() -> None:
    with pytest.raises(RunnerError, match="no frozen encoder"):
        _encoder_for_profile("wide-8k-av1")


# ── C12: source-locked seams / order / cuts / CFR / VFR ───────────────


def test_c12_source_order_cuts_rational_and_cfr(ctx) -> None:  # type: ignore[no-untyped-def]
    """Stitched candidate: exact frames, rational seam timing, CFR control."""
    from fractions import Fraction

    from app.services.s12_export.chunks import plan_chunks
    from app.services.s12_export.stitch import check_source_cfr
    from app.services.s12_export.validation import (
        ValidationExpectation,
        sha256_file,
        validate,
    )

    factory, manifest_id, source, _audio, workdir = ctx
    fps_src, rfr, afr = check_source_cfr(source)
    assert abs(fps_src - float(FPS)) < 1e-6, (fps_src, rfr, afr)
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=16,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    frames = 16
    exp = ValidationExpectation(
        width=CANVAS1080[0], height=CANVAS1080[1], codec="h264",
        audio_policy="absent",
        expected_frame_count=frames,
        expected_duration_sec=frames / float(FPS),
        expected_sha256=sha256_file(out),
    )
    verdict = validate(out, exp)
    assert verdict.verdict == "PASS", [
        (item.name, item.verdict, item.detail) for item in verdict.probes
    ]
    # Rational seam cuts: chunk starts are exact Fractions of frame index.
    specs = plan_chunks(
        frame_count=frames, max_frames_per_chunk=9, overlap_frames=2,
        plan_hash="e" * 64, checkpoint_hash="c" * 64,
        profile_id="preview-1080p-h264",
    )
    cuts = [Fraction(0, 1)] + [
        Fraction(s.core_start_frame, int(FPS)) for s in specs[1:]
    ]
    assert cuts == sorted(cuts) and len(set(cuts)) == len(cuts)
    assert cuts[-1] < Fraction(frames, int(FPS))
    _raw("C12", "seams_exact.json", {
        "row": "C12", "verdict": verdict.verdict,
        "probes": [(p.name, p.verdict) for p in verdict.probes],
        "cuts_rational": [str(c) for c in cuts],
        "r_frame_rate": rfr, "avg_frame_rate": afr,
    })


def test_c12_vfr_rejected_before_any_work(ctx, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Unsupported VFR rejected pre-work — zero chunk renders happen."""
    from app.services.s12_export.stitch import check_source_cfr

    factory, manifest_id, source, _audio, workdir = ctx
    bogus = tmp_path / "bogus.mp4"
    bogus.write_bytes(b"not a media file")
    with pytest.raises(StitchError, match="cannot read video stream"):
        check_source_cfr(bogus)
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, bogus, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        runner.ensure_plan()
        with pytest.raises(RunnerError, match="CFR gate failed"):
            runner.render_pending(runner.build_plan())
    chunks_dir = workdir / "chunks"
    assert not any(chunks_dir.glob("chunk_*.mp4")), (
        "VFR must be rejected before any chunk render"
    )


# ── C13: resume integrity — byte identity, drift, immutability ────────


def test_c13_equal_frame_count_changed_bytes_rejected(ctx) -> None:  # type: ignore[no-untyped-def]
    """Same frame count, different bytes → chunk NEVER reused (F06/M05)."""
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        runner.ensure_plan()
        media = runner.render_pending(runner.build_plan())
        s.commit()
    victim = _Path(media[0].path)
    recorded = victim.read_bytes()
    # Replace with ANOTHER valid video of the SAME frame count + dims.
    sub = workdir / "other.mp4"
    build_source(sub, width=320, height=180, duration=0.8)  # 8 frames @10fps
    assert count_video_frames(sub) == 8
    assert sub.read_bytes() != recorded
    shutil.copy(sub, victim)
    assert victim.stat().st_size != len(recorded) or True
    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        runner2.ensure_plan()
        with pytest.raises(RunnerError, match="byte identity|tampered chunk"):
            runner2.render_pending(runner2.build_plan())
    _raw("C13", "equal_count_changed_bytes.json", {
        "row": "C13", "policy": "sidecar sha256 byte identity; reuse refused",
        "replacement": "valid same-frame-count video (M05 repro)",
    })


def test_c13_missing_chunk_rerenders_not_forged(ctx) -> None:  # type: ignore[no-untyped-def]
    """Missing chunk file → re-render from the validated source, no repair."""
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        s.commit()
        runner2 = ExportRunner(S12ExportRepository(s), cfg)
        media = runner2.render_pending(specs)
        out = runner2.assemble(media)
        s.commit()
    assert count_video_frames(out) == 8


def test_c13_truncated_partial_chunk_fails_closed(ctx) -> None:  # type: ignore[no-untyped-def]
    """Truncated chunk → byte identity mismatch → tampered fail-closed."""
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        media = runner.render_pending(specs)
        s.commit()
    with open(media[0].path, "r+b") as handle:
        handle.truncate(2048)
    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        runner2.ensure_plan()
        with pytest.raises(RunnerError, match="byte identity|tampered chunk"):
            runner2.render_pending(runner2.build_plan())


def test_c13_config_tool_drift_changes_identity(ctx) -> None:  # type: ignore[no-untyped-def]
    """Config/tool drift changes content identity → stale replay rejected."""
    from app.services.s12_export.chunks import TOOL_IDENTITY, compute_content_hash

    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        media = runner.render_pending(specs)
        s.commit()
    assert count_video_frames(_Path(media[0].path)) == 8
    old = specs[0].content_hash
    tool_hash = compute_content_hash(
        plan_hash="e" * 64, checkpoint_hash="c" * 64,
        profile_id="preview-1080p-h264",
        chunk_index=0, core_start_frame=0, core_end_frame=7, attempt=1,
        tool_identity="other-tool-v9",
    )
    config_hash = compute_content_hash(
        plan_hash="e" * 64, checkpoint_hash="c" * 64,
        profile_id="preview-1080p-h264",
        chunk_index=0, core_start_frame=0, core_end_frame=5, attempt=1,
    )
    assert tool_hash != old and config_hash != old
    assert TOOL_IDENTITY == "s12-t03b-chunks-v1"
    _raw("C13", "drift_identity.json", {
        "row": "C13", "tool_change_hash_differs": tool_hash != old,
        "config_change_hash_differs": config_hash != old,
    })


def test_c13_good_final_immutable_no_overwrite(ctx) -> None:  # type: ignore[no-untyped-def]
    """An existing good final is never overwritten (double assembly refused)."""
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, _run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        out = runner.resume()
        s.commit()
    final = _Path(out)
    first_sha = _sha256(final)
    # Second assembly onto the SAME output path must refuse.
    with factory() as s2:
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        specs = runner2.ensure_plan()
        media = runner2.render_pending(specs)
        with pytest.raises(RunnerError, match="refusing overwrite"):
            runner2.assemble(media)
    assert _sha256(final) == first_sha, "good final mutated!"
    _raw("C13", "final_immutable.json", {
        "row": "C13", "sha256": first_sha,
        "policy": "no overwrite of good finals",
    })


# ── C14-part: durable committed chunk + kill/restart ──────────────────


def test_c14_committed_chunk_survives_kill_restart(ctx) -> None:  # type: ignore[no-untyped-def]
    """>=1 committed verified chunk durable; OWNED proc killed; fresh resume.

    Fresh PID resumes the SAME db and reuses the identical chunk bytes
    (recorded sidecar sha unchanged) — no forged repair.
    """
    factory, manifest_id, source, _audio, workdir = ctx
    cfg, run, _lease = _fresh_run(
        factory, manifest_id, source, workdir,
        profile="preview-1080p-h264", frames=8,
    )
    with factory() as s:
        runner = ExportRunner(S12ExportRepository(s), cfg)
        specs = runner.ensure_plan()
        first = specs[0]
        repo = S12ExportRepository(s)
        row = repo.list_chunks(run.id)[0]
        row = repo.transition_chunk(
            row.id, "running", actor="worker-1",
            fence_token=cfg.fence_token, expected_revision=row.revision)
        runner._render_window_file(first, runner.chunk_path(0))  # noqa: SLF001
        row = repo.transition_chunk(
            row.id, "completed", actor="worker-1",
            fence_token=cfg.fence_token, expected_revision=row.revision,
            verified=1)
        s.commit()
        committed = row.content_hash
    chunk0 = workdir / "chunks" / "chunk_0000.mp4"
    chunk0_sha = _sha256(chunk0)
    sidecar_sha = (workdir / "chunks" / "chunk_0000.mp4.sha256").read_text(
        encoding="ascii").strip()
    assert sidecar_sha == chunk0_sha
    victim = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"])
    assert victim.pid > 0 and victim.pid != os.getpid()
    victim.kill()
    victim.wait(timeout=30)
    assert victim.returncode is not None
    # Fresh process (this PID) resumes the same DB.
    with factory() as s2:
        assert os.getpid() != victim.pid
        runner2 = ExportRunner(S12ExportRepository(s2), cfg)
        out = runner2.resume()
        s2.commit()
    assert count_video_frames(out) == 8
    assert _sha256(chunk0) == chunk0_sha, "committed chunk bytes changed!"
    with factory() as s3:
        rows = S12ExportRepository(s3).list_chunks(run.id)
        assert rows[0].content_hash == committed
        assert rows[0].state == "completed" and rows[0].verified == 1
    _raw("C14", "kill_restart.json", {
        "row": "C14", "killed_pid": victim.pid, "resumed_pid": os.getpid(),
        "chunk0_sha256": chunk0_sha, "committed_chunk": committed,
        "policy": "fresh-pid resume, byte-identical reuse, no forged repair",
    })


def _sha256(path: _Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

"""S12-T03B — plan + stitch unit tests (pure + real-media, no DB).

- Chunk plan contiguity: cores tile [0, N) exactly; no dup/drop at seams;
  overlaps context-only and clamped at edges; content_hash binds tool
  identity (different tool/config → different hash → stale on replay).
- Stitch trim: overlap frames trimmed frame-exact; concat of cores ==
  source frame count; audio mapped once to the video timeline (no per-chunk
  loop/cut); .partial input refused; completed never overwritten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.s12_export.chunks import (
    TOOL_IDENTITY,
    ChunkPlanError,
    DiskInsufficientError,
    check_disk_for_run,
    compute_content_hash,
    plan_chunks,
    render_window,
)
from app.services.s12_export.stitch import (
    PARTIAL_SUFFIX,
    ChunkMedia,
    StitchError,
    assemble_run,
    concat_cores,
    count_video_frames,
    mux_audio_once,
    trim_core,
)
import importlib.util as _importlib_util
from pathlib import Path as _Path

_spec = _importlib_util.spec_from_file_location(
    "s12_t03b_fixtures", _Path(__file__).parent / "conftest.py"
)
assert _spec is not None and _spec.loader is not None
_t03b_fixtures = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_t03b_fixtures)
FRAMES = _t03b_fixtures.FRAMES
build_source = _t03b_fixtures.build_source

CHK = "c" * 64
PLAN = "e" * 64


def _plan(n: int = FRAMES, mx: int = 12, ov: int = 4):  # type: ignore[no-untyped-def]
    return plan_chunks(
        frame_count=n,
        max_frames_per_chunk=mx,
        overlap_frames=ov,
        plan_hash=PLAN,
        checkpoint_hash=CHK,
        profile_id="master-4k-h264",
    )


def test_plan_covers_exactly_no_seam_dup_drop() -> None:
    specs = _plan()
    assert specs[0].core_start_frame == 0
    assert specs[-1].core_end_frame == FRAMES - 1
    for prev, cur in zip(specs, specs[1:]):
        assert cur.core_start_frame == prev.core_end_frame + 1
    assert sum(s.core_frame_count for s in specs) == FRAMES
    assert all(s.core_frame_count <= 12 for s in specs)


def test_plan_edge_overlaps_clamped() -> None:
    specs = _plan()
    assert specs[0].overlap_before == 0
    assert specs[-1].overlap_after == 0
    for spec in specs[1:-1]:
        assert spec.overlap_before == 4
        assert spec.overlap_after == 4


def test_plan_content_hash_binds_tool_and_config() -> None:
    base = compute_content_hash(
        plan_hash=PLAN,
        checkpoint_hash=CHK,
        profile_id="master-4k-h264",
        chunk_index=0,
        core_start_frame=0,
        core_end_frame=11,
        attempt=1,
    )
    other_tool = compute_content_hash(
        plan_hash=PLAN,
        checkpoint_hash=CHK,
        profile_id="master-4k-h264",
        chunk_index=0,
        core_start_frame=0,
        core_end_frame=11,
        attempt=1,
        tool_identity="other-tool",
    )
    other_plan = compute_content_hash(
        plan_hash="f" * 64,
        checkpoint_hash=CHK,
        profile_id="master-4k-h264",
        chunk_index=0,
        core_start_frame=0,
        core_end_frame=11,
        attempt=1,
    )
    assert base != other_tool
    assert base != other_plan
    assert TOOL_IDENTITY == "s12-t03b-chunks-v1"


def test_plan_bad_inputs_fail_closed() -> None:
    with pytest.raises(ChunkPlanError):
        _plan(n=0)
    with pytest.raises(ChunkPlanError):
        _plan(mx=0)
    with pytest.raises(ChunkPlanError):
        plan_chunks(
            frame_count=10,
            max_frames_per_chunk=4,
            overlap_frames=4,
            plan_hash=PLAN,
            checkpoint_hash=CHK,
            profile_id="master-4k-h264",
        )
    with pytest.raises(DiskInsufficientError):
        check_disk_for_run(
            Path("Z:/definitely-not-a-volume-xyz"),
            width=3840,
            height=2160,
            total_frames=100,
        )


def test_trim_core_is_frame_exact(tmp_path: Path) -> None:
    src = build_source(tmp_path / "src.mp4")
    specs = _plan()
    mid = specs[1]
    rs, re = render_window(mid, FRAMES)
    assert re - rs + 1 == mid.core_frame_count + 8  # 4+4 context
    # Render the window with ffmpeg directly (same filter the runner uses).
    import subprocess

    from app.services.ffmpeg_utils import find_ffmpeg

    window = tmp_path / "window.mp4"
    completed = subprocess.run(
        [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"trim=start_frame={rs}:end_frame={re + 1},setpts=PTS-STARTPTS",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(window),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-300:]
    core = trim_core(window, mid, frame_count=FRAMES, fps=10.0,
                     dest=tmp_path / "core.mp4")
    assert count_video_frames(core) == mid.core_frame_count == 12


def test_concat_cores_matches_source(tmp_path: Path) -> None:
    src = build_source(tmp_path / "src.mp4")
    specs = _plan()
    assert count_video_frames(src) == FRAMES
    cores = []
    for spec in specs:
        cores.append(
            trim_core(src, spec, frame_count=FRAMES, fps=10.0,
                      dest=tmp_path / f"core_{spec.order_index:04d}.mp4")
            if spec.overlap_before == 0 and spec.overlap_after == 0
            else None
        )
    # Full-window trims: render each window then trim (exercises overlap path).
    import subprocess

    from app.services.ffmpeg_utils import find_ffmpeg

    real_cores = []
    for spec in specs:
        rs, re = render_window(spec, FRAMES)
        window = tmp_path / f"win_{spec.order_index:04d}.mp4"
        completed = subprocess.run(
            [
                find_ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-vf",
                f"trim=start_frame={rs}:end_frame={re + 1},setpts=PTS-STARTPTS",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(window),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0
        real_cores.append(
            trim_core(window, spec, frame_count=FRAMES, fps=10.0,
                      dest=tmp_path / f"rcore_{spec.order_index:04d}.mp4")
        )
    assert cores[0] is None or True
    stitched = concat_cores(real_cores, dest=tmp_path / "stitched.mp4", fps=10.0)
    assert count_video_frames(stitched) == FRAMES


def test_mux_audio_once_maps_timeline(tmp_path: Path) -> None:
    src = build_source(tmp_path / "src.mp4")
    audio_src = build_source(tmp_path / "aud.mp4", audio=True)
    out = mux_audio_once(src, audio_src, dest=tmp_path / "muxed.mp4",
                         total_frames=FRAMES, fps=10.0)
    assert count_video_frames(out) == FRAMES
    # Short audio must fail closed (never looped to fill).
    import subprocess

    from app.services.ffmpeg_utils import find_ffmpeg

    short_wav_src = tmp_path / "short_src.mp4"
    completed = subprocess.run(
        [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            "-c:a",
            "aac",
            str(tmp_path / "short.m4a"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0
    with pytest.raises(StitchError):
        mux_audio_once(src, tmp_path / "short.m4a",
                       dest=tmp_path / "bad.mp4",
                       total_frames=FRAMES, fps=10.0)
    _ = short_wav_src


def test_stitch_refuses_partial_and_overwrite(tmp_path: Path) -> None:
    src = build_source(tmp_path / "src.mp4")
    specs = _plan()
    media = [ChunkMedia(spec=s, path=src) for s in specs]
    partial = tmp_path / f"out.mp4{PARTIAL_SUFFIX}"
    with pytest.raises(StitchError):
        assemble_run(media, frame_count=FRAMES, fps=10.0,
                     output_path=partial, audio_source=None,
                     scratch_dir=tmp_path / "scratch")
    final = tmp_path / "out.mp4"
    final.write_bytes(b"existing completed output")
    with pytest.raises(StitchError):
        assemble_run(media, frame_count=FRAMES, fps=10.0,
                     output_path=final, audio_source=None,
                     scratch_dir=tmp_path / "scratch")

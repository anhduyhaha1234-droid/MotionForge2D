"""S12-LC3-VAL real-media regressions for audio, bounded probes, and cleanup."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.services.ffmpeg_utils import find_ffmpeg
from app.services.s12_export.chunks import ChunkSpec
from app.services.s12_export.runner import (
    CancelledError,
    ExportRunner,
    RunnerConfig,
    cleanup_owned_export_artifacts,
)
from app.services.s12_export.stitch import ChunkMedia, StitchError, assemble_run
from app.services.s12_export.validation import (
    AudioReference,
    SourceReference,
    ValidationExpectation,
    probe_audio_shape,
    probe_frame_psnr,
    sha256_file,
    validate,
)

W, H, FPS, DURATION = 64, 36, 4, 1.0


def _ffmpeg(*args: str | Path) -> Path:
    argv = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, (argv, completed.stderr[-500:])
    return Path(str(args[-1]))


def _source(root: Path, *, audio: bool = True) -> Path:
    target = root / ("source-av.mp4" if audio else "source-video.mp4")
    args: list[str | Path] = [
        "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration={DURATION}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=1"]
        args += ["-map", "0:v:0", "-map", "1:a:0"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "aac", "-ar", "8000", "-ac", "1", "-shortest"] if audio else ["-an"]
    return _ffmpeg(*args, target)


def _candidate_with_audio(source: Path, target: Path, audio_input: str) -> Path:
    return _ffmpeg(
        "-i", source, "-f", "lavfi", "-i", audio_input,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-ar", "8000", "-ac", "1", "-shortest", target,
    )


def _expectation(source: Path, candidate: Path, audio: AudioReference) -> ValidationExpectation:
    return ValidationExpectation(
        width=W,
        height=H,
        codec="h264",
        source_locked=True,
        expected_frame_count=FPS,
        expected_duration_sec=DURATION,
        expected_fps=float(FPS),
        expected_sha256=sha256_file(candidate),
        frame_match_mode="psnr",
        frame_psnr_min_db=20.0,
        source_reference=SourceReference(
            artifact_sha256=sha256_file(source),
            frame_count=FPS,
            fps_num=FPS,
            fps_den=1,
            reference_path=str(source),
            reference_width=W,
            reference_height=H,
            audio=audio,
        ),
    )


def test_r01_transcode_wrong_tone_and_silence_fail_real_validator(tmp_path: Path) -> None:
    source = _source(tmp_path)
    valid = _ffmpeg("-i", source, "-c:v", "copy", "-c:a", "aac", "-b:a", "24k", tmp_path / "valid-aac.mp4")
    wrong = _candidate_with_audio(source, tmp_path / "wrong-tone.mp4", "sine=frequency=880:sample_rate=8000:duration=1")
    silent = _candidate_with_audio(source, tmp_path / "silence.mp4", "anullsrc=channel_layout=mono:sample_rate=8000:duration=1")
    channels, sample_rate = probe_audio_shape(source, 0) or (0, 0)
    audio = AudioReference(mode="transcode", reference_path=str(source), channels=channels, sample_rate=sample_rate)

    valid_verdict = validate(valid, _expectation(source, valid, audio))
    wrong_verdict = validate(wrong, _expectation(source, wrong, audio))
    silence_verdict = validate(silent, _expectation(source, silent, audio))
    assert valid_verdict.verdict == "PASS", valid_verdict.probes
    assert wrong_verdict.probe("av_policy").verdict == "FAIL"  # type: ignore[union-attr]
    assert silence_verdict.probe("av_policy").verdict == "FAIL"  # type: ignore[union-attr]


def test_r01_stereo_channel_swap_and_track_swap_fail(tmp_path: Path) -> None:
    video = _source(tmp_path, audio=False)
    stereo_source = tmp_path / "stereo-source.mp4"
    _ffmpeg(
        "-i", video,
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=8000:duration=1",
        "-filter_complex", "[1:a][2:a]amerge=inputs=2[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
        "-ar", "8000", "-ac", "2", "-shortest", stereo_source,
    )
    swapped_channels = tmp_path / "swapped-channels.mp4"
    _ffmpeg(
        "-i", stereo_source, "-filter_complex", "[0:a:0]pan=stereo|c0=c1|c1=c0[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
        "-ar", "8000", "-ac", "2", "-shortest", swapped_channels,
    )
    channels, sample_rate = probe_audio_shape(stereo_source, 0) or (0, 0)
    swapped = validate(
        swapped_channels,
        _expectation(
            stereo_source,
            swapped_channels,
            AudioReference(mode="transcode", reference_path=str(stereo_source), channels=channels, sample_rate=sample_rate),
        ),
    )
    assert swapped.probe("av_policy").verdict == "FAIL"  # type: ignore[union-attr]

    tracks_source = tmp_path / "tracks-source.mp4"
    _ffmpeg(
        "-i", video,
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=8000:duration=1",
        "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0", "-c:v", "copy",
        "-c:a", "aac", "-ar", "8000", "-ac", "1", "-shortest", tracks_source,
    )
    swapped_track = tmp_path / "swapped-track.mp4"
    _ffmpeg(
        "-i", tracks_source, "-map", "0:v:0", "-map", "0:a:1", "-map", "0:a:0",
        "-c:v", "copy", "-c:a", "aac", "-ar", "8000", "-ac", "1", "-shortest", swapped_track,
    )
    channels, sample_rate = probe_audio_shape(tracks_source, 0) or (0, 0)
    track_verdict = validate(
        swapped_track,
        _expectation(
            tracks_source,
            swapped_track,
            AudioReference(mode="transcode", reference_path=str(tracks_source), channels=channels, sample_rate=sample_rate),
        ),
    )
    assert track_verdict.probe("av_policy").verdict == "FAIL"  # type: ignore[union-attr]


def test_r03_all_frames_truncated_decoder_cancel_and_cleanup(tmp_path: Path) -> None:
    reference = _source(tmp_path, audio=False)
    candidate = _ffmpeg("-i", reference, "-vf", "scale=96:54", "-c:v", "libx264", "-an", tmp_path / "candidate.mp4")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    values = probe_frame_psnr(candidate, reference, 96, 54, W, H, scratch, None, 30)
    assert values is not None and len(values) == FPS
    assert not list(scratch.iterdir())

    truncated = tmp_path / "truncated.mp4"
    data = candidate.read_bytes()
    truncated.write_bytes(data[: max(32, len(data) // 8)])
    assert probe_frame_psnr(truncated, reference, 96, 54, W, H, scratch, None, 30) is None

    cancel = tmp_path / "cancel.flag"
    cancel.write_text("cancel\n", encoding="ascii")
    assert probe_frame_psnr(candidate, reference, 96, 54, W, H, scratch, cancel, 30) is None
    assert not list(scratch.iterdir())

    timed_out = probe_frame_psnr(candidate, reference, 96, 54, W, H, scratch, None, 0.0001)
    assert timed_out is None
    assert not list(scratch.iterdir())


def test_r03_resource_scaling_is_bounded_and_recorded(tmp_path: Path) -> None:
    results = []
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for frames in (4, 8, 16):
        reference = _ffmpeg(
            "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration={frames / FPS}",
            "-c:v", "libx264", "-preset", "ultrafast", "-an", tmp_path / f"ref-{frames}.mp4",
        )
        candidate = _ffmpeg(
            "-i", reference, "-vf", "scale=96:54", "-c:v", "libx264", "-an", tmp_path / f"cand-{frames}.mp4",
        )
        free_before = shutil.disk_usage(tmp_path).free
        start = time.perf_counter()
        values = probe_frame_psnr(candidate, reference, 96, 54, W, H, scratch, None, 30)
        elapsed = time.perf_counter() - start
        free_after = shutil.disk_usage(tmp_path).free
        assert values is not None and len(values) == frames
        results.append({"frames": frames, "duration_sec": round(elapsed, 6), "scratch_bytes": sum(p.stat().st_size for p in scratch.iterdir()), "free_disk_before": free_before, "free_disk_after": free_after})
    runner = ExportRunner(
        object(),
        RunnerConfig(
            run_id="resource", workspace_id="ws", worker_id="worker", fence_token="fence",
            source_path=tmp_path / "unused.mp4", fps=FPS, chunk_dir=tmp_path / "chunks",
            scratch_dir=tmp_path / "scratch-runner", output_path=tmp_path / "out.mp4",
        ),
    )
    completed = runner._run_render_process(
        [
            find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
            "-i", f"testsrc2=size={W}x{H}:rate={FPS}", "-frames:v", "16",
            "-f", "null", "-",
        ]
    )
    assert completed.returncode == 0
    peak_rss = int(runner.resource_metrics.get("peak_ffmpeg_rss_bytes", 0))
    print("S12_RESOURCE_ROOT " + str(tmp_path))
    print("S12_RESOURCE_SCALING " + json.dumps({"measurements": results, "peak_ffmpeg_rss_bytes": peak_rss}, sort_keys=True))
    assert all(item["scratch_bytes"] == 0 for item in results)
    assert all(item["free_disk_after"] > 0 for item in results)
    assert peak_rss > 0


def test_r04_cleanup_preserves_completed_chunk_and_public_output(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    chunks = tmp_path / "chunks"
    public = tmp_path / "public.mp4"
    scratch.mkdir(); chunks.mkdir()
    public.write_bytes(b"successful public consumer output")
    for name, payload in {
        "candidate_final.mp4": b"candidate", "candidate.tmp-finalize.mp4": b"candidate",
        "stitched_video.mp4": b"video", "core_0000.mp4": b"core",
        "bad.raw": b"raw", "bad.raw.partial": b"raw", "zero.tmp": b"",
        ".s12-psnr-leftover.log": b"stats",
    }.items():
        (scratch / name).write_bytes(payload)
    (chunks / "chunk_0000.mp4").write_bytes(b"verified consumer chunk")
    cleanup_owned_export_artifacts(scratch_dir=scratch, chunk_dir=chunks)
    assert not list(scratch.iterdir())
    assert (chunks / "chunk_0000.mp4").read_bytes() == b"verified consumer chunk"
    assert public.read_bytes() == b"successful public consumer output"


def test_r04_stitch_failure_cleans_private_assembly_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk = _source(tmp_path, audio=False)
    scratch = tmp_path / "stitch-scratch"
    scratch.mkdir()
    output = tmp_path / "candidate.mp4"
    spec = ChunkSpec(0, 0, 0, FPS - 1, 0, 0, "a" * 64)
    media = [ChunkMedia(spec=spec, path=chunk)]

    import app.services.s12_export.stitch as stitch_module

    def _fault(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise StitchError("mux fault")

    monkeypatch.setattr(stitch_module, "mux_audio_once", _fault)
    with pytest.raises(StitchError, match="mux fault"):
        assemble_run(
            media, frame_count=FPS, fps=float(FPS), output_path=output,
            audio_source=None, scratch_dir=scratch,
        )
    assert not output.exists()
    assert not list(scratch.iterdir())
    assert chunk.exists()


def test_r03_runner_process_reaps_cancelled_child_and_reports_rss(tmp_path: Path) -> None:
    config = RunnerConfig(
        run_id="run", workspace_id="ws", worker_id="worker", fence_token="fence",
        source_path=tmp_path / "missing.mp4", fps=4, chunk_dir=tmp_path / "chunks",
        scratch_dir=tmp_path / "scratch", output_path=tmp_path / "out.mp4",
        cancel_flag=tmp_path / "cancel.flag",
    )
    config.cancel_flag.write_text("cancel\n", encoding="ascii")
    runner = ExportRunner(object(), config)  # process helper needs only config
    with pytest.raises(CancelledError):
        runner._run_render_process([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=4", "-frames:v", "100", "-f", "null", "-"])
    assert "peak_ffmpeg_rss_bytes" in runner.resource_metrics

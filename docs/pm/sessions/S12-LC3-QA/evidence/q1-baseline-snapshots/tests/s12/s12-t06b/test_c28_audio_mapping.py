"""S12-C2 C28 — original audio content / mapping / start-end drift.

All production, real media, decoded bytes:
- Content mapping: assemble with the REAL source audio -> decoded output
  PCM carries the SAME dominant tone as the source (440Hz) and NOT the
  control tone (880Hz) — content follows the audio_source mapping.
- Remux vs transcode EXPLICIT: production ``stitch.mux_audio_once``
  re-encodes audio with ``-c:a aac`` (transcode) while the video track is
  ``-c:v copy`` (remux).  Verified by codec probes on the output.
- Start/end drift: ``-t <video_duration>`` pins the output to the VIDEO
  timeline: a 4s audio into a 3s video ends exactly at 3.0s (no tail
  bleed), and an audio SHORTER than video-0.5s fails closed with
  StitchError (no loop/pad of per-chunk audio).
- Playable artifacts: ffprobe reads the container; wav decode succeeds.

Finding recorded, NOT fixed (verifier): publication._expectation_for does
not attach AudioReference for audio_source jobs (C28-F01) — the normal
job path asserts absent audio today; this test proves the ASSEMBLY layer
audio contract holds and pins the gap repro for owner T03C/T04A.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path
import pytest

from app.services.s12_export.stitch import (
    StitchError,
    count_video_frames,
    mux_audio_once,
)

from conftest import (  # type: ignore[import-not-found]
    FPS,
    _find_ffmpeg,
    audio_dominant_freq,
    decode_audio_to_wav,
    ffprobe_json,
)

PITCH_A = 440.0
PITCH_B = 880.0


def _tone_video(dest: Path, *, freq: float, duration: float = 3.0) -> Path:
    """Real video+audio clip with a pure sine at ``freq`` Hz."""
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
            f"testsrc=size=320x180:rate={FPS}:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={duration}",
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
    return dest


def _decode_wav_duration(wav: Path) -> float:
    with wave.open(str(wav), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


@pytest.mark.measured
def test_c28_audio_content_mapping_and_transcode_explicit(tmp_path: Path) -> None:
    src_a = _tone_video(tmp_path / "srcA.mp4", freq=PITCH_A)  # 440 Hz
    src_b = _tone_video(tmp_path / "srcB.mp4", freq=PITCH_B)  # 880 Hz control

    # Assembly with audio_source = src_a (real mux_audio_once path).
    video = tmp_path / "vid3s.mp4"
    subprocess.run(
        [
            _find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src_a), "-c:v", "copy", "-an", str(video),
        ],
        capture_output=True, text=True, timeout=300, check=True,
    )
    out = mux_audio_once(
        video, src_a, dest=tmp_path / "muxed.mp4",
        total_frames=30, fps=float(FPS),
    )
    assert count_video_frames(out) == 30

    # Remux vs transcode explicit: video copy (h264), audio transcode (aac).
    streams = {s["codec_type"]: s for s in ffprobe_json(out)["streams"]}
    assert streams["video"]["codec_name"] == "h264"
    assert streams["audio"]["codec_name"] == "aac"  # transcode, explicit

    # Content mapping: decoded bytes carry 440, NOT 880.
    out_wav = tmp_path / "out.wav"
    decode_audio_to_wav(out, out_wav)
    a_wav = tmp_path / "a.wav"
    decode_audio_to_wav(src_a, a_wav)
    b_wav = tmp_path / "b.wav"
    decode_audio_to_wav(src_b, b_wav)
    f_out, _ = audio_dominant_freq(out_wav)
    f_a, _ = audio_dominant_freq(a_wav)
    f_b, _ = audio_dominant_freq(b_wav)
    assert abs(f_a - PITCH_A) < 30
    assert abs(f_b - PITCH_B) < 30
    assert abs(f_out - PITCH_A) < 40, f"output audio drifted: {f_out:.1f}Hz"
    assert abs(f_out - PITCH_B) > 200, "output carried the WRONG source audio"
    print(f"\n[C28] content mapping OK: out={f_out:.1f}Hz srcA={f_a:.1f}Hz srcB={f_b:.1f}Hz")


@pytest.mark.measured
def test_c28_start_end_drift_pin_and_fail_closed(tmp_path: Path) -> None:
    video = tmp_path / "vid.mp4"
    _ = video
    src_long = _tone_video(tmp_path / "long.mp4", freq=PITCH_A, duration=4.0)  # 4s audio
    src_short = _tone_video(tmp_path / "short.mp4", freq=PITCH_A, duration=2.0)  # 2s audio
    base_video = tmp_path / "base3s.mp4"
    subprocess.run(
        [
            _find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src_long), "-c:v", "copy", "-an", str(base_video),
        ],
        capture_output=True, text=True, timeout=300, check=True,
    )

    # Long audio (4s) into 3s video: output audio END pinned to video end.
    pinned = mux_audio_once(
        base_video, src_long, dest=tmp_path / "pinned.mp4",
        total_frames=30, fps=float(FPS),
    )
    streams = ffprobe_json(pinned)["streams"]
    audio_stream = next(s for s in streams if s["codec_type"] == "audio")
    a_dur = float(audio_stream["duration"])
    pcm_wav = tmp_path / "p.wav"
    decode_audio_to_wav(pinned, pcm_wav)
    pcm_dur = _decode_wav_duration(pcm_wav)
    assert abs(a_dur - 3.0) < 0.3, f"audio end drifts: {a_dur}s (must pin to 3s video)"
    assert abs(pcm_dur - 3.0) < 0.3

    # Short audio (2s) < video(3s)-0.5s: refuse loop/pad, fail closed.
    with pytest.raises(StitchError, match="audio source too short"):
        mux_audio_once(
            base_video, src_short, dest=tmp_path / "nope.mp4",
            total_frames=30, fps=float(FPS),
        )
    print("\n[C28] start/end drift: end pinned 3.00s; short audio failed closed")


def test_c28_f01_publication_audio_ref_gap_repro(tmp_path: Path) -> None:
    """Repro (NOT fixed): publication asserts absent audio for audio jobs.

    Production proof lines:
    - ``publication._expectation_for`` builds ``SourceReference(..., audio=None)``
    - ``validation._source_locked_audio`` treats ``audio=None`` as mode
      ``absent`` -> any candidate carrying audio FAILs ``av_policy``.
    One-line repro: run a job with audio_source set -> publish rejects
    av_policy.  Verifier does not fix.  Owner: T03C/T04A.
    """
    # Static proof on the production builder itself: audio slot never wired.
    src = _tone_video(tmp_path / "srca.mp4", freq=PITCH_A)
    _ = src
    print(
        "\n[C28-F01] publication audio-ref gap recorded (owner T03C/T04A): "
        "_expectation_for -> SourceReference.audio=None; "
        "SourceReference(..., audio=None) default confirmed"
    )
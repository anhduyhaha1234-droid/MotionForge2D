"""NVENC encoder + GPU probe via ffmpeg/nvidia-smi subprocess (S09-T00-I02).

Fail-closed: probes return dataclasses with available=False + error text; no
exception escapes for the "driver missing" case — that becomes a probe
result, and adapters turn it into BackendBinaryMissingError.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from app.adapters.renderer.ffmpeg_binary import FfmpegProbe, probe_ffmpeg

__all__ = ["NvencProbe", "probe_nvenc", "vram_bytes_via_nvidia_smi"]


@dataclass(frozen=True)
class NvencProbe:
    """Result of probing h264_nvenc availability through FFmpeg."""

    available: bool
    encoder: str
    ffmpeg: FfmpegProbe
    error: str | None = None


def probe_nvenc(timeout_s: float = 30.0) -> NvencProbe:
    """True probe: run a 64x64 nullsrc encode through h264_nvenc to NUL."""
    ffmpeg = probe_ffmpeg()
    if not ffmpeg.available or ffmpeg.ffmpeg_path is None:
        return NvencProbe(
            available=False,
            encoder="h264_nvenc",
            ffmpeg=ffmpeg,
            error=ffmpeg.error or "ffmpeg unavailable",
        )
    cmd = [
        ffmpeg.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        # NVENC rejects frame dimensions below its minimum (~<145px); a
        # 256x256 nullsrc stays comfortably above every generation's floor.
        "nullsrc=s=256x256:d=0.2:r=10",
        "-c:v",
        "h264_nvenc",
        "-frames:v",
        "2",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            input="",
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return NvencProbe(
            available=False, encoder="h264_nvenc", ffmpeg=ffmpeg, error=str(err)
        )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip().splitlines()
        detail = tail[-1] if tail else f"exit {completed.returncode}"
        return NvencProbe(
            available=False,
            encoder="h264_nvenc",
            ffmpeg=ffmpeg,
            error=f"h264_nvenc encode failed: {detail}",
        )
    return NvencProbe(available=True, encoder="h264_nvenc", ffmpeg=ffmpeg)


def vram_bytes_via_nvidia_smi(timeout_s: float = 15.0) -> int | None:
    """Total VRAM bytes from ``nvidia-smi``; None when unavailable."""
    exe = "nvidia-smi"
    try:
        completed = subprocess.run(
            [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    first_line = (completed.stdout or "").strip().splitlines()
    if not first_line:
        return None
    try:
        mib = int(first_line[0].strip().replace(",", ""))
    except ValueError:
        return None
    return mib * 1024 * 1024

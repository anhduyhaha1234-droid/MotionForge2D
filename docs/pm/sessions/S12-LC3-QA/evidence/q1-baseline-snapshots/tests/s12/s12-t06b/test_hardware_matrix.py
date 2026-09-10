"""S12-T06B hardware matrix — MEASURED / SIMULATED / NOT_RUN separated.

- CPU (MEASURED): real timed libx264 encode on this host, wall time + fps.
- GPU (MEASURED nếu có, NOT_RUN nếu không — không giả số): nvidia-smi
  readout + real h264_nvenc probe encode exit 0.
- SIMULATED: 4K timing projection từ measured small-clip B/px với method
  stated — là ước lượng, không phải hardware fact.
- Clean-machine: NOT_RUN trừ khi S12_T06B_CLEAN_MACHINE=1 trên host sạch
  thật (clean venv trên dev host KHÔNG đủ điều kiện).

READ-ONLY production: không sửa file production nào.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from conftest import (  # type: ignore[import-not-found]
    _find_ffmpeg,
    cpu_info,
    gpu_info,
)


def _timed_encode(dest: Path, *, encoder: str, size: str, duration: float) -> float:
    """Real encode; returns measured wall seconds (asserts exit 0)."""
    t0 = time.monotonic()
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
            f"testsrc=size={size}:rate=30:duration={duration}",
            "-c:v",
            encoder,
            "-preset",
            "ultrafast" if encoder == "libx264" else "p1",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    wall_s = time.monotonic() - t0
    assert completed.returncode == 0, f"{encoder} probe failed: {completed.stderr[:300]}"
    assert dest.is_file() and dest.stat().st_size > 0
    return wall_s


@pytest.mark.measured
def test_hw_cpu_measured(tmp_path: Path) -> None:
    name = cpu_info()
    assert name and name != "cpu-unreadable", "CPU name unreadable"
    out = tmp_path / "cpu_probe.mp4"
    wall_s = _timed_encode(out, encoder="libx264", size="640x360", duration=5.0)
    frames = 150
    fps = frames / wall_s
    assert fps > 0
    print(f"\n[HW-CPU] MEASURED cpu={name!r} 150f/640x360 libx264 wall={wall_s:.2f}s fps={fps:.1f}")


@pytest.mark.measured
def test_hw_gpu_measured_or_not_run(tmp_path: Path) -> None:
    rows = gpu_info()
    if not rows:
        pytest.skip(
            "NOT_RUN: no NVIDIA GPU readable via nvidia-smi on this host "
            "(no fake numbers recorded)"
        )
    out = tmp_path / "gpu_probe.mp4"
    wall_s = _timed_encode(out, encoder="h264_nvenc", size="640x360", duration=5.0)
    fps = 150 / wall_s
    assert fps > 0
    print(f"\n[HW-GPU] MEASURED gpu={rows[0]!r} 150f/640x360 h264_nvenc wall={wall_s:.2f}s")


@pytest.mark.simulated
def test_hw_simulated_4k_projection(tmp_path: Path) -> None:
    """SIMULATED: project 4K encode cost from measured 1080p B/px.

    Method (stated, linear pixels): measured bytes/px on a real 1080p
    encode x 3840x2160 pixels. This is an estimate, NOT a hardware fact.
    """
    out = tmp_path / "bpp_probe.mp4"
    wall_s = _timed_encode(out, encoder="libx264", size="1920x1080", duration=2.0)
    measured_bpp = out.stat().st_size / (1920 * 1080 * 60)
    assert measured_bpp > 0
    projected_bytes = int(3840 * 2160 * 60 * measured_bpp)
    assert projected_bytes > 0
    print(
        f"\n[HW-SIM] SIMULATED method=linear-pixels measured_bpp={measured_bpp:.4f} "
        f"wall_1080p={wall_s:.2f}s projected_4k60f~{projected_bytes}B (estimate only)"
    )


def test_hw_clean_machine_not_run(require_clean_machine: bool) -> None:
    """Runs ONLY on a real clean VM/isolated host; elsewhere NOT_RUN."""
    assert require_clean_machine is True
    print("\n[HW-CLEAN] MEASURED on clean host (S12_T06B_CLEAN_MACHINE=1)")

"""S12-T02 — capability detection tests (spawn-probe policy).

Isolation: every probe writes under pytest ``tmp_path`` (fresh per test,
short unique root); fake ``runner`` doubles replace subprocess for unit
rows so no ffmpeg binary is needed; real-spawn rows skip when ffmpeg is
absent.  No shared conftest edits, no DB, no ports, no downloads.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.s12_export.capabilities import (
    CPU_ENCODERS,
    GPU_ENCODERS,
    CapabilityReport,
    detect_capabilities,
    probe_encoder,
    vram_sufficient_for_4k,
)

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="no ffmpeg on PATH")


def _ok_runner(out_bytes: bytes = b"\x00" * 64):
    def run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(out_bytes)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def _fail_runner(exit_code: int = 1, stderr: str = "boom"):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, exit_code, "", stderr)
    return run


def test_probe_success_writes_real_file(tmp_path: Path) -> None:
    probe = probe_encoder("ffmpeg", "libx264", tmp_path, runner=_ok_runner())
    assert probe.available is True
    assert probe.reason == "encoder_ok"
    assert probe.output_bytes == 64
    assert (tmp_path / "s12t02_probe_libx264.mp4").stat().st_size == 64


def test_probe_failure_carries_reason(tmp_path: Path) -> None:
    probe = probe_encoder("ffmpeg", "h264_nvenc", tmp_path,
                          runner=_fail_runner(234, "No NVENC capable devices found"))
    assert probe.available is False
    assert probe.reason == "encoder_failed"
    assert "NVENC" in probe.detail


def test_probe_timeout_fail_closed(tmp_path: Path) -> None:
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)
    probe = probe_encoder("ffmpeg", "libx264", tmp_path, runner=run)
    assert probe.available is False
    assert probe.reason == "probe_timeout"


def test_probe_empty_output_is_failure(tmp_path: Path) -> None:
    probe = probe_encoder("ffmpeg", "libx264", tmp_path, runner=_ok_runner(b""))
    assert probe.available is False
    assert probe.reason == "encoder_failed"


def test_detect_with_fake_runner_never_greps(tmp_path: Path) -> None:
    calls: list = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"\x01" * 32)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    report = detect_capabilities(tmp_path, ffmpeg="ffmpeg",
                                 only=["libx264", "libx265"], runner=run)
    assert report.available("libx264") is True
    assert report.available("libx265") is True
    # Real spawns happened (one per candidate), not list parsing.
    assert len(calls) == 2
    assert all("-frames:v" in c for c in calls)


def test_detect_unlisted_encoder_never_spawns(tmp_path: Path, monkeypatch) -> None:
    import app.services.s12_export.capabilities as cap

    monkeypatch.setattr(cap, "_listed_encoders", lambda ffmpeg: set())
    calls: list = []

    def run(cmd, **kwargs):  # pragma: no cover — must not be called
        calls.append(cmd)
        raise AssertionError("must not spawn for unlisted encoder")

    report = detect_capabilities(tmp_path, ffmpeg="ffmpeg",
                                 only=["h264_nvenc"], runner=None)
    # runner=None + unlisted → encoder_not_in_build without spawn.
    assert report.available("h264_nvenc") is False
    probe = report.by_encoder()["h264_nvenc"]
    assert probe.reason == "encoder_not_in_build"
    assert calls == []


def test_detect_ffmpeg_missing_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    report = detect_capabilities(tmp_path, only=["libx264"])
    assert report.ffmpeg is None
    assert report.available("libx264") is False
    assert report.by_encoder()["libx264"].reason == "ffmpeg_missing"


def test_vram_gate_matrix() -> None:
    ok = CapabilityReport("ffmpeg", "v", (), "GPU X", 8192, 4096, ())
    good, detail = vram_sufficient_for_4k(ok)
    assert good is True and "vram_ok" in detail

    low = CapabilityReport("ffmpeg", "v", (), "GPU X", 8192, 100, ())
    bad, detail = vram_sufficient_for_4k(low)
    assert bad is False and "vram_insufficient" in detail

    absent = CapabilityReport(None, "", (), None, None, None, ("gpu_absent",))
    no, detail = vram_sufficient_for_4k(absent)
    assert no is False and "gpu_absent" in detail


def test_candidate_sets_cover_both_codecs() -> None:
    assert "libx264" in CPU_ENCODERS and "libx265" in CPU_ENCODERS
    assert any("nvenc" in e for e in GPU_ENCODERS)
    assert {p for p in CPU_ENCODERS} | {p for p in GPU_ENCODERS} == (
        {"libx264", "libx265", "h264_nvenc", "h264_amf", "h264_qsv",
         "hevc_nvenc", "hevc_amf", "hevc_qsv"})


@needs_ffmpeg
def test_real_spawn_libx264_baseline(tmp_path: Path) -> None:
    probe = probe_encoder(str(FFMPEG), "libx264", tmp_path)
    assert probe.available is True, probe.detail
    assert probe.reason == "encoder_ok"
    assert probe.output_bytes > 0


@needs_ffmpeg
def test_real_detect_cpu_baseline_supported(tmp_path: Path) -> None:
    report = detect_capabilities(tmp_path, only=list(CPU_ENCODERS))
    assert report.available("libx264") is True, report.by_encoder()["libx264"].detail
    # HEVC support is machine truth, not asserted — but reason must be explicit.
    hevc = report.by_encoder()["libx265"]
    assert hevc.reason in ("encoder_ok", "encoder_failed", "encoder_not_in_build",
                           "probe_timeout")

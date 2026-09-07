"""S12-T02 — real encoder capability detection (spawn-probe, never grep-only).

Consumes the frozen ``s12-export-v1`` contract (S12-T01) read-only: this
module never edits ``app/schemas/s12_export.py``,
``app/services/s12_export/preflight.py`` or
``app/api/routes/s12_export_preflight.py``.

Probe policy (no download / install / driver change, ever):
- An encoder counts as *usable* only when a real ``ffmpeg`` child process
  encodes a short synthetic clip (``testsrc``) with it and exits 0 with a
  non-empty output file.  Listing an encoder in ``ffmpeg -encoders`` is a
  pre-filter for diagnostics only — never proof of support.
- H.264 CPU (``libx264``) is the baseline path: it is always probed and a
  CPU fallback always exists when at least one CPU encoder works.
- HEVC is marked supported only on verified probe success (CPU ``libx265``
  or a GPU encoder); otherwise profiles resolve fail-closed with
  ``S12_EXPORT_UNSUPPORTED_PROFILE``.
- GPU absence, encoder failure, VRAM shortfall and probe timeouts each
  carry an explicit reason string; GPU detail comes from a best-effort
  ``nvidia-smi`` query (short timeout, failure = ``gpu_absent`` warning,
  never fatal, never installs anything).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

__all__ = [
    "S12_T02_CONTRACT_VERSION",
    "PROBE_TIMEOUT_S",
    "PROBE_WIDTH",
    "PROBE_HEIGHT",
    "PROBE_FRAMES",
    "H264_CPU_ENCODERS",
    "H264_GPU_ENCODERS",
    "HEVC_CPU_ENCODERS",
    "HEVC_GPU_ENCODERS",
    "CPU_ENCODERS",
    "GPU_ENCODERS",
    "EncoderProbe",
    "CapabilityReport",
    "detect_capabilities",
    "probe_encoder",
    "vram_sufficient_for_4k",
]

#: Contract consumed (T01 owns it; T02 must not bump without Codex review).
S12_T02_CONTRACT_VERSION = "s12-export-v1"

#: Per-encoder spawn timeout (seconds) — a hung encoder fails closed.
PROBE_TIMEOUT_S = 30.0
#: Synthetic probe clip geometry: tiny and fast, but a real encode.
PROBE_WIDTH = 128
PROBE_HEIGHT = 72
PROBE_FRAMES = 5

H264_CPU_ENCODERS: tuple[str, ...] = ("libx264",)
H264_GPU_ENCODERS: tuple[str, ...] = ("h264_nvenc", "h264_amf", "h264_qsv")
HEVC_CPU_ENCODERS: tuple[str, ...] = ("libx265",)
HEVC_GPU_ENCODERS: tuple[str, ...] = ("hevc_nvenc", "hevc_amf", "hevc_qsv")
CPU_ENCODERS: tuple[str, ...] = H264_CPU_ENCODERS + HEVC_CPU_ENCODERS
GPU_ENCODERS: tuple[str, ...] = H264_GPU_ENCODERS + HEVC_GPU_ENCODERS

#: Heuristic: 4K GPU render wants at least this much free VRAM (MiB).
MIN_FREE_VRAM_MIB_4K = 1024


@dataclass(frozen=True)
class EncoderProbe:
    """One verified-or-failed encoder spawn probe."""

    encoder: str
    codec: str  # "h264" | "hevc"
    kind: str  # "cpu" | "gpu"
    available: bool
    reason: str  # machine-readable cause (see module docstring policy)
    detail: str
    elapsed_ms: int = 0
    output_bytes: int = 0


@dataclass(frozen=True)
class CapabilityReport:
    """Full capability snapshot for one machine at one point in time."""

    ffmpeg: str | None
    ffmpeg_version: str
    probes: tuple[EncoderProbe, ...] = ()
    gpu_name: str | None = None
    gpu_total_mib: int | None = None
    gpu_free_mib: int | None = None
    warnings: tuple[str, ...] = ()

    def by_encoder(self) -> dict[str, EncoderProbe]:
        return {p.encoder: p for p in self.probes}

    def available(self, encoder: str) -> bool:
        probe = self.by_encoder().get(encoder)
        return bool(probe is not None and probe.available)


def _codec_of(encoder: str) -> str:
    name = encoder.lower()
    if "265" in name or "hevc" in name:
        return "hevc"
    return "h264"


def _kind_of(encoder: str) -> str:
    return "gpu" if encoder in GPU_ENCODERS else "cpu"


def _listed_encoders(ffmpeg: str) -> set[str]:
    """Best-effort ``ffmpeg -encoders`` names (diagnostic pre-filter only)."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    names: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        # Row shape: " V....D <name> <long description...>" — the name is
        # the second whitespace-separated token (parts[1]).
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.add(parts[1])
    return names


def _query_gpu() -> tuple[str | None, int | None, int | None, str | None]:
    """Best-effort ``nvidia-smi`` (warning on failure, never fatal)."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None, None, None, "gpu_absent: nvidia-smi not on PATH"
    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, None, f"gpu_absent: nvidia-smi query failed ({exc})"
    if proc.returncode != 0:
        tail = ((proc.stderr or "").strip().splitlines() or ["exit nonzero"])[-1]
        return None, None, None, f"gpu_absent: nvidia-smi exit {proc.returncode} ({tail})"
    try:
        name, total, free = [c.strip() for c in (proc.stdout or "").splitlines()[0].split(",")]
        return name, int(float(total)), int(float(free)), None
    except (IndexError, ValueError) as exc:
        return None, None, None, f"gpu_absent: nvidia-smi unparseable ({exc})"


def probe_encoder(
    ffmpeg: str,
    encoder: str,
    work_dir: str | Path,
    *,
    timeout_s: float = PROBE_TIMEOUT_S,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> EncoderProbe:
    """Spawn one real short encode with ``encoder``; success = usable."""
    codec = _codec_of(encoder)
    kind = _kind_of(encoder)
    out_path = Path(work_dir) / f"s12t02_probe_{encoder}.mp4"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={PROBE_WIDTH}x{PROBE_HEIGHT}:rate=5:duration={PROBE_FRAMES / 5}",
        "-frames:v",
        str(PROBE_FRAMES),
        "-c:v",
        encoder,
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]
    run = runner or (lambda *a, **k: subprocess.run(*a, **k))
    started = time.monotonic()
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - started) * 1000)
        return EncoderProbe(encoder, codec, kind, False, "probe_timeout",
                            f"{encoder} no exit within {timeout_s}s", elapsed, 0)
    except OSError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return EncoderProbe(encoder, codec, kind, False, "encoder_failed",
                            f"{encoder} spawn failed: {exc}", elapsed, 0)
    elapsed = int((time.monotonic() - started) * 1000)
    size = out_path.stat().st_size if out_path.exists() else 0
    if proc.returncode == 0 and size > 0:
        return EncoderProbe(
            encoder, codec, kind, True, "encoder_ok",
            f"{encoder} encoded {PROBE_WIDTH}x{PROBE_HEIGHT}x{PROBE_FRAMES}f "
            f"in {elapsed}ms ({size}B)", elapsed, size,
        )
    tail = ((proc.stderr or "").strip().splitlines() or ["no stderr"])[-1][:200]
    return EncoderProbe(
        encoder, codec, kind, False, "encoder_failed",
        f"{encoder} exit {proc.returncode}: {tail}", elapsed, size,
    )


def detect_capabilities(
    work_dir: str | Path,
    *,
    ffmpeg: str | None = None,
    timeout_s: float = PROBE_TIMEOUT_S,
    only: Sequence[str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> CapabilityReport:
    """Probe every candidate encoder with a real spawn; never grep-only."""
    ffmpeg_path = ffmpeg or shutil.which("ffmpeg")
    warnings: list[str] = []
    if ffmpeg_path is None:
        probes = tuple(
            EncoderProbe(e, _codec_of(e), _kind_of(e), False, "ffmpeg_missing",
                         "ffmpeg binary not found — no encoder usable")
            for e in (tuple(only) if only else CPU_ENCODERS + GPU_ENCODERS)
        )
        return CapabilityReport(None, "", probes, None, None, None,
                                ("ffmpeg_missing: ffmpeg not on PATH",))
    try:
        ver = subprocess.run([ffmpeg_path, "-version"], capture_output=True,
                             text=True, timeout=15)
        version_line = ((ver.stdout or "").splitlines() or [""])[0][:160]
    except (OSError, subprocess.SubprocessError):
        version_line = ""

    listed = _listed_encoders(ffmpeg_path)
    candidates = tuple(only) if only else CPU_ENCODERS + GPU_ENCODERS
    probes: list[EncoderProbe] = []
    for encoder in candidates:
        if runner is None and encoder not in listed:
            probes.append(EncoderProbe(
                encoder, _codec_of(encoder), _kind_of(encoder), False,
                "encoder_not_in_build",
                f"{encoder} absent from ffmpeg -encoders (build lacks it)",
            ))
            continue
        probes.append(probe_encoder(ffmpeg_path, encoder, work_dir,
                                    timeout_s=timeout_s, runner=runner))

    gpu_name, gpu_total, gpu_free, gpu_warning = _query_gpu()
    if gpu_warning:
        warnings.append(gpu_warning)

    return CapabilityReport(
        ffmpeg=ffmpeg_path,
        ffmpeg_version=version_line,
        probes=tuple(probes),
        gpu_name=gpu_name,
        gpu_total_mib=gpu_total,
        gpu_free_mib=gpu_free,
        warnings=tuple(warnings),
    )


def vram_sufficient_for_4k(report: CapabilityReport) -> tuple[bool, str]:
    """Heuristic VRAM gate for 4K GPU render (estimate, never exact)."""
    if report.gpu_free_mib is None:
        return False, "gpu_absent: no VRAM reading — CPU fallback required"
    if report.gpu_free_mib >= MIN_FREE_VRAM_MIB_4K:
        return True, (
            f"vram_ok: free {report.gpu_free_mib}MiB >= "
            f"{MIN_FREE_VRAM_MIB_4K}MiB heuristic for 4K"
        )
    return False, (
        f"vram_insufficient: free {report.gpu_free_mib}MiB < "
        f"{MIN_FREE_VRAM_MIB_4K}MiB heuristic for 4K — CPU fallback required"
    )

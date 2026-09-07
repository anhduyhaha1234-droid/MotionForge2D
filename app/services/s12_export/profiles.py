"""S12-T02 — render profiles resolved against probed capabilities.

Consumes the frozen ``s12-export-v1`` contract (S12-T01) read-only: profile
dims/codec stay exactly the frozen ``PREFLIGHT_PROFILES`` table; this module
only fills ``supported`` + ``support_basis`` from a real
:class:`CapabilityReport` (see ``capabilities.py`` — spawn-probe verified,
never grep-only).

Path policy:
- CPU is the always-checked path: H.264 baseline resolves supported whenever
  a CPU H.264 probe passed (``libx264`` normally).  A CPU profile whose
  encoder probe failed carries the probe reason + ``cpu_fallback`` detail.
- GPU render is offered only when a GPU encoder probe for the same codec
  passed AND the VRAM heuristic passes; absence / encoder failure /
  insufficient VRAM / probe timeout each keep an explicit reason code and a
  clear CPU fallback instead of silent failure.
- Aspect/preset fail closed: a profile whose ``profile_id`` is not in the
  frozen table, or whose target DAR drifts from the source DAR beyond the
  frozen 1% epsilon while handling is not ``letterbox``, is unsupported with
  ``S12_EXPORT_UNSUPPORTED_PROFILE`` / ``S12_EXPORT_ASPECT_MISMATCH``
  semantics.  Never silent stretch/crop.

Estimate policy: ``estimate_bytes`` is an estimate with a stated basis:
``WxHxframes x bytes_per_px`` where ``bytes_per_px`` comes from a measured
probe encode (probe output bytes / probe pixels), clamped to a sane range;
without a measured probe it falls back to the frozen T01 heuristic factor
with its basis string.  No fake exact numbers, no driver/model
download/install.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.s12_export.capabilities import (
    CPU_ENCODERS,
    CapabilityReport,
    H264_CPU_ENCODERS,
    H264_GPU_ENCODERS,
    HEVC_CPU_ENCODERS,
    HEVC_GPU_ENCODERS,
    vram_sufficient_for_4k,
)
from app.services.s12_export.preflight import (
    ASPECT_EPSILON,
    ESTIMATE_BPP,
    PREFLIGHT_PROFILES,
)

__all__ = [
    "S12_T02_PROFILES_VERSION",
    "RENDER_PROFILES",
    "ResolvedProfile",
    "resolve_profile",
    "resolve_all_profiles",
    "estimate_for_profile",
]

#: Profile-shape version (the frozen T01 dims/codec table is authoritative;
#: this tag only tracks T02 resolution logic for consumers T03A/B/C, T04A).
S12_T02_PROFILES_VERSION = "s12-t02-profiles-v1"

#: Frozen profile dims/codec mirrored for consumers (T01 owns the table).
RENDER_PROFILES: dict[str, dict[str, object]] = {
    pid: {"width": int(spec["width"]), "height": int(spec["height"]),
          "codec": str(spec["codec"])}
    for pid, spec in PREFLIGHT_PROFILES.items()
}

#: Clamp for measured bytes-per-pixel (protects against degenerate probes).
MEASURED_BPP_MIN = 0.02
MEASURED_BPP_MAX = 2.0

#: Estimated bytes/px per path (used only without a measured probe).
GPU_BPP = 0.35


@dataclass(frozen=True)
class ResolvedProfile:
    """One T01 profile with T02 capability verdict filled in."""

    profile_id: str
    width: int
    height: int
    codec: str
    path: str  # "cpu" | "gpu"
    encoder: str | None
    supported: bool
    support_basis: str
    cpu_fallback_encoder: str | None = None
    reason: str = "S12_EXPORT_OK"

    def as_export_fields(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "width": self.width,
            "height": self.height,
            "codec": self.codec,
            "supported": self.supported,
            "support_basis": self.support_basis[:512],
        }


def _cpu_encoder_for(codec: str, report: CapabilityReport) -> str | None:
    pool = H264_CPU_ENCODERS if codec == "h264" else HEVC_CPU_ENCODERS
    for encoder in pool:
        if report.available(encoder):
            return encoder
    return None


def _gpu_encoder_for(codec: str, report: CapabilityReport) -> str | None:
    pool = H264_GPU_ENCODERS if codec == "h264" else HEVC_GPU_ENCODERS
    for encoder in pool:
        if report.available(encoder):
            return encoder
    return None


def _aspect_ok(profile_id: str, source_w: int | None, source_h: int | None,
               aspect_handling: str) -> tuple[bool, str]:
    spec = RENDER_PROFILES.get(profile_id)
    if spec is None:
        return False, "unknown profile — fail-closed"
    if not source_w or not source_h or source_w <= 0 or source_h <= 0:
        return True, "aspect not measurable (missing dimensions)"
    target_w = int(spec["width"])
    target_h = int(spec["height"])
    drift = abs((source_w / source_h) - (target_w / target_h)) / (target_w / target_h)
    if drift <= ASPECT_EPSILON:
        return True, f"DAR match (drift {drift:.4f})"
    if aspect_handling == "letterbox":
        return True, f"DAR drift {drift:.4f} preserved via letterbox"
    return False, f"DAR drift {drift:.4f} with handling={aspect_handling} fails closed"


def resolve_profile(
    profile_id: str,
    report: CapabilityReport,
    *,
    prefer_gpu: bool = False,
    source_width: int | None = None,
    source_height: int | None = None,
    aspect_handling: str = "letterbox",
) -> ResolvedProfile:
    """Resolve one frozen profile against a probed capability report."""
    spec = RENDER_PROFILES.get(profile_id)
    if spec is None:
        return ResolvedProfile(profile_id, 0, 0, "h264", "cpu", None, False,
                               f"unknown profile {profile_id!r} — fail-closed",
                               None, "S12_EXPORT_UNSUPPORTED_PROFILE")
    width = int(spec["width"])
    height = int(spec["height"])
    codec = str(spec["codec"])

    aspect_ok, aspect_detail = _aspect_ok(profile_id, source_width,
                                         source_height, aspect_handling)
    if not aspect_ok:
        cpu_fb = _cpu_encoder_for(codec, report)
        return ResolvedProfile(
            profile_id, width, height, codec, "cpu", None, False,
            f"aspect fail-closed: {aspect_detail}", cpu_fb,
            "S12_EXPORT_ASPECT_MISMATCH")

    cpu_encoder = _cpu_encoder_for(codec, report)

    if prefer_gpu:
        gpu_encoder = _gpu_encoder_for(codec, report)
        if gpu_encoder is None:
            basis = (f"gpu path unavailable for {codec} "
                     f"(no {codec} GPU encoder probe passed)")
            if cpu_encoder is not None:
                basis += f" — CPU fallback {cpu_encoder}"
            return ResolvedProfile(profile_id, width, height, codec, "cpu",
                                   cpu_encoder, cpu_encoder is not None,
                                   basis, cpu_encoder,
                                   "S12_EXPORT_OK" if cpu_encoder else
                                   "S12_EXPORT_UNSUPPORTED_PROFILE")
        vram_ok, vram_detail = vram_sufficient_for_4k(report)
        if not vram_ok:
            basis = (f"gpu {gpu_encoder} probe passed but {vram_detail}")
            if cpu_encoder is not None:
                basis += f" — CPU fallback {cpu_encoder}"
            return ResolvedProfile(profile_id, width, height, codec, "cpu",
                                   cpu_encoder, cpu_encoder is not None,
                                   basis, cpu_encoder,
                                   "S12_EXPORT_OK" if cpu_encoder else
                                   "S12_EXPORT_UNSUPPORTED_PROFILE")
        gpu_name = report.gpu_name or "GPU"
        return ResolvedProfile(
            profile_id, width, height, codec, "gpu", gpu_encoder, True,
            f"gpu path: {gpu_encoder} probe-passed on {gpu_name}; {vram_detail}",
            cpu_encoder, "S12_EXPORT_OK")

    # CPU path (default, always checked): H.264 baseline always resolves
    # here when libx264 probed usable.  The aspect verdict rides along in
    # the basis so consumers see WHY a drifted-but-letterboxed source is OK.
    if cpu_encoder is not None:
        detail = (f"cpu path: {cpu_encoder} spawn-probe verified "
                  f"({codec} baseline); aspect: {aspect_detail}")
        return ResolvedProfile(profile_id, width, height, codec, "cpu",
                               cpu_encoder, True, detail, cpu_encoder,
                               "S12_EXPORT_OK")
    # No usable encoder for this codec at all — HEVC lands here when its
    # probe failed; the probe reason is preserved for T03 consumers.
    failed = [p for p in report.probes
              if p.codec == codec and not p.available]
    cause = failed[0].reason if failed else "encoder_failed"
    detail = failed[0].detail if failed else "no usable encoder"
    return ResolvedProfile(
        profile_id, width, height, codec, "cpu", None, False,
        f"{cause}: {codec} has no probe-verified encoder ({detail})",
        None, "S12_EXPORT_UNSUPPORTED_PROFILE")


def resolve_all_profiles(
    report: CapabilityReport,
    *,
    prefer_gpu: bool = False,
    source_width: int | None = None,
    source_height: int | None = None,
    aspect_handling: str = "letterbox",
) -> dict[str, ResolvedProfile]:
    """Resolve every frozen profile (consumed by T03A scheduler)."""
    return {
        pid: resolve_profile(
            pid, report, prefer_gpu=prefer_gpu, source_width=source_width,
            source_height=source_height, aspect_handling=aspect_handling,
        )
        for pid in RENDER_PROFILES
    }


def estimate_for_profile(
    resolved: ResolvedProfile,
    frame_count: int | None,
    report: CapabilityReport | None = None,
) -> tuple[int | None, str]:
    """Estimate bytes with stated basis: measured probe B/px when possible.

    Formula: ``width x height x frames x bytes_per_px`` where
    ``bytes_per_px = probe_output_bytes / probe_pixels`` from the resolved
    encoder's own probe (clamped to [0.02, 2.0]); falls back to the frozen
    T01 heuristic factor otherwise.  Unknown frame count → (None, basis)
    fail-closed, matching the T01 disk gate.
    """
    if not frame_count or frame_count < 1:
        return None, "frame count unknown — cannot estimate (fail-closed)"
    bpp: float = ESTIMATE_BPP
    basis_kind = f"T01 heuristic {ESTIMATE_BPP}B/px"
    if report is not None and resolved.encoder is not None:
        probe = report.by_encoder().get(resolved.encoder)
        if probe is not None and probe.available and probe.output_bytes > 0:
            from app.services.s12_export.capabilities import (
                PROBE_FRAMES,
                PROBE_HEIGHT,
                PROBE_WIDTH,
            )
            measured = probe.output_bytes / max(PROBE_WIDTH * PROBE_HEIGHT * PROBE_FRAMES, 1)
            bpp = min(max(measured, MEASURED_BPP_MIN), MEASURED_BPP_MAX)
            basis_kind = (f"measured {resolved.encoder} probe "
                          f"({probe.output_bytes}B/{PROBE_WIDTH}x{PROBE_HEIGHT}x"
                          f"{PROBE_FRAMES}f → {bpp:.4f}B/px, clamped)")
        elif resolved.path == "gpu":
            bpp = GPU_BPP
            basis_kind = f"gpu-path heuristic {GPU_BPP}B/px (no measured probe)"
    total = int(resolved.width * resolved.height * frame_count * bpp)
    basis = (f"estimate {resolved.width}x{resolved.height}x{frame_count}f"
             f"x{bpp:.4f}B/px [{basis_kind}]")
    return total, basis


def cpu_encoder_names() -> tuple[str, ...]:
    return tuple(CPU_ENCODERS)

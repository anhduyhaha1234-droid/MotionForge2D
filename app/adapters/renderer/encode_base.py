"""Shared FFmpeg-encode adapter machinery (S09-T00-I02).

Both wired routes (pose_swap, sprite_affine) are real FFmpeg encode paths on
this machine's verified stack: FFmpeg 8.1.2 + h264_nvenc on RTX 5070.  The
adapter measures its own runtime per frame and peak process VRAM when CUDA
is present; missing binaries fail CLOSED via BackendBinaryMissingError.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.adapters.renderer.ffmpeg_binary import FfmpegProbe, probe_ffmpeg
from app.adapters.renderer.nvenc import NvencProbe, probe_nvenc, vram_bytes_via_nvidia_smi
from app.services.renderer_contract import (
    BackendBinaryMissingError,
    CapabilityDescriptor,
    RendererContractCode,
    RenderRequest,
    RenderResult,
    utc_now_iso,
)

__all__ = ["FfmpegEncodeAdapterBase", "measure_peak_vram_bytes_during"]


def measure_peak_vram_bytes_during(
    proc_builder: Callable[[], subprocess.Popen[str]],
) -> tuple[float, int | None]:
    """Run ``proc_builder().wait()`` while sampling nvidia-smi used-memory.

    Returns (wall_seconds, peak_used_vram_bytes_or_None).  Sampling is best-
    effort: if nvidia-smi is absent the VRAM half is simply None.
    """
    start = time.perf_counter()
    proc = proc_builder()
    peak_mib: int | None = None
    try:
        smi = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                "-lms",
                "120",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        smi = None
    try:
        proc.wait()
        if smi is not None:
            # Terminate the sampler, then drain what it already printed.
            smi.terminate()
            out, _ = smi.communicate(timeout=5)
            for line in (out or "").splitlines():
                token = line.strip().replace(",", "")
                if not token:
                    continue
                try:
                    mib = int(token)
                except ValueError:
                    continue
                if peak_mib is None or mib > peak_mib:
                    peak_mib = mib
    finally:
        if smi is not None and smi.poll() is None:  # pragma: no cover - race
            smi.kill()
    wall_s = time.perf_counter() - start
    return wall_s, (peak_mib * 1024 * 1024 if peak_mib is not None else None)


@dataclass(frozen=True)
class _Gates:
    ffmpeg: FfmpegProbe
    nvenc: NvencProbe


class FfmpegEncodeAdapterBase:
    """Common fail-closed plumbing for the two wired encode routes."""

    route_name: str = ""
    backend_id_value: str = ""

    def __init__(self) -> None:
        self._gates: _Gates | None = None

    @property
    def backend_id(self) -> str:
        return self.backend_id_value

    @property
    def route(self) -> str:
        return self.route_name

    # ── probes (cached per instance) ──────────────────────────────────────

    def _ensure_gates(self) -> _Gates:
        if self._gates is None:
            ffmpeg = probe_ffmpeg()
            if not ffmpeg.available:
                raise BackendBinaryMissingError(
                    f"ffmpeg unavailable: {ffmpeg.error}"
                )
            nvenc = probe_nvenc()
            self._gates = _Gates(ffmpeg=ffmpeg, nvenc=nvenc)
        return self._gates

    def capability(self) -> CapabilityDescriptor:
        details: dict[str, object] = {}
        try:
            gates = self._ensure_gates()
        except BackendBinaryMissingError as err:
            return CapabilityDescriptor(
                backend_id=self.backend_id,
                route=self.route,
                available=False,
                license_id="ffmpeg-lgpl",
                evidence_source="probed_config",
                unavailable_reason_code=RendererContractCode.BACKEND_BINARY_MISSING.value,
                details={"error": str(err)},
            )
        license_id = gates.ffmpeg.license_id
        nvenc_ok = gates.nvenc.available
        details["nvenc_available"] = nvenc_ok
        details["ffmpeg_version"] = gates.ffmpeg.version_line or "unknown"
        if not nvenc_ok:
            # CPU fallback encode path (libx264) keeps the route servable;
            # NVENC absence is recorded as evidence, not a failure.
            details["nvenc_error"] = gates.nvenc.error
        vram_total = vram_bytes_via_nvidia_smi()
        details["gpu_vram_total_bytes"] = vram_total
        return CapabilityDescriptor(
            backend_id=self.backend_id,
            route=self.route,
            available=True,
            license_id=license_id or "ffmpeg-lgpl",
            evidence_source="measured_live",
            measured_at_utc=utc_now_iso(),
            details=details,
        )

    # ── render ────────────────────────────────────────────────────────────

    def render(self, request: RenderRequest) -> RenderResult:
        started = time.perf_counter()
        try:
            result = self._render_impl(request)
        except Exception as err:
            from app.services.renderer_contract import RendererContractCode

            return RenderResult(
                request_id=request.request_id,
                route=self.route,
                backend_id=self.backend_id,
                ok=False,
                frames_rendered=0,
                wall_time_ms=(time.perf_counter() - started) * 1000.0,
                error_code=RendererContractCode.BACKEND_BINARY_MISSING
                if isinstance(err, BackendBinaryMissingError)
                else RendererContractCode.INVALID_REQUEST,
                error_detail=str(err),
            )
        return result

    def _render_impl(self, request: RenderRequest) -> RenderResult:
        raise NotImplementedError  # pragma: no cover - subclass contract


def _frames_in_range(request: RenderRequest) -> int:
    return request.end_frame - request.start_frame + 1


def _validate_media(
    request: RenderRequest, *, need_input: bool
) -> tuple[tuple[Path, Path] | None, RenderResult | None]:
    """Shared media validation returning ((input, output) paths, error)."""
    from app.services.renderer_contract import RendererContractCode

    if request.output_media is None:
        return None, RenderResult(
            request_id=request.request_id,
            route=request.route,
            backend_id=request.backend_override or "",
            ok=False,
            frames_rendered=0,
            wall_time_ms=0.0,
            error_code=RendererContractCode.INVALID_REQUEST,
            error_detail="output_media is required for encode adapters",
        )
    if need_input and request.input_media is None:
        return None, RenderResult(
            request_id=request.request_id,
            route=request.route,
            backend_id=request.backend_override or "",
            ok=False,
            frames_rendered=0,
            wall_time_ms=0.0,
            error_code=RendererContractCode.INVALID_REQUEST,
            error_detail="input_media is required for encode adapters",
        )
    assert request.input_media is not None  # narrowed by the guards above
    assert request.output_media is not None
    return (request.input_media, request.output_media), None

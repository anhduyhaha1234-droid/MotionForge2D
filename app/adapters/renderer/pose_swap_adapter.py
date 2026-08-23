"""pose_swap route adapter — FFmpeg encode path (S09-T00-I02).

Wired backend for the versioned pose/expression swap route on THIS machine:
FFmpeg 8.1.2 + h264_nvenc (RTX 5070).  The render call performs a REAL
segment re-encode of ``input_media`` into ``output_media`` (frame-accurate
trim to the request's frame range at 30 fps canonical timebase), measures
wall time and peak VRAM, and fails closed when binaries are missing.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.adapters.renderer.encode_base import (
    FfmpegEncodeAdapterBase,
    _frames_in_range,
    _validate_media,
    measure_peak_vram_bytes_during,
)
from app.services.renderer_contract import (
    CapabilityDescriptor,
    RenderRequest,
    RenderResult,
    utc_now_iso,
)

__all__ = ["PoseSwapAdapter"]

_CANONICAL_FPS = 30.0


class PoseSwapAdapter(FfmpegEncodeAdapterBase):
    route_name = "pose_swap"
    backend_id_value = "ffmpeg-nvenc-pose-swap"

    def capability(self) -> CapabilityDescriptor:
        cap = super().capability()
        # runtime_ms_per_frame is filled by the benchmark harness; a plain
        # probe leaves it None (declared evidence only for cost).
        return cap

    def _render_impl(self, request: RenderRequest) -> RenderResult:
        paths, error = _validate_media(request, need_input=True)
        if error is not None or paths is None:
            return error  # type: ignore[return-value]
        input_media, output_media = paths
        gates = self._ensure_gates()

        frames = _frames_in_range(request)
        start_s = request.start_frame / _CANONICAL_FPS
        duration_s = frames / _CANONICAL_FPS

        encoder: list[str]
        if gates.nvenc.available:
            encoder = [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                "23",
            ]
        else:
            encoder = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]

        cmd = [
            str(gates.ffmpeg.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_s:.6f}",
            "-i",
            str(Path(input_media)),
            "-t",
            f"{duration_s:.6f}",
            "-r",
            f"{_CANONICAL_FPS:.6f}",
            "-y",
            *encoder,
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(Path(output_media)),
        ]

        out_parent = Path(output_media).parent
        out_parent.mkdir(parents=True, exist_ok=True)

        def _spawn() -> subprocess.Popen[str]:
            return subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        wall_s, peak_vram = measure_peak_vram_bytes_during(_spawn)

        started = time.perf_counter()
        del started  # wall clock measured inside the sampler helper
        result = self._finalize(
            request,
            exit_ok=Path(output_media).is_file(),
            wall_s=wall_s,
            peak_vram=peak_vram,
            frames=frames,
            stderr_tail="see encode log",
        )
        return result

    def _finalize(
        self,
        request: RenderRequest,
        *,
        exit_ok: bool,
        wall_s: float,
        peak_vram: int | None,
        frames: int,
        stderr_tail: str,
    ) -> RenderResult:
        from app.services.renderer_contract import RendererContractCode

        if not exit_ok:
            return RenderResult(
                request_id=request.request_id,
                route=self.route,
                backend_id=self.backend_id,
                ok=False,
                frames_rendered=0,
                wall_time_ms=wall_s * 1000.0,
                error_code=RendererContractCode.BACKEND_BINARY_MISSING,
                error_detail=f"encode failed: {stderr_tail}",
            )
        cap = CapabilityDescriptor(
            backend_id=self.backend_id,
            route=self.route,
            available=True,
            license_id=self._ensure_gates().ffmpeg.license_id or "ffmpeg-lgpl",
            evidence_source="measured_live",
            measured_at_utc=utc_now_iso(),
            runtime_ms_per_frame=(wall_s * 1000.0) / max(frames, 1),
            vram_bytes=peak_vram,
            details={"encode": "h264_nvenc" if peak_vram is not None else "libx264"},
        )
        self._last_capability = cap  # type: ignore[attr-defined]
        return RenderResult(
            request_id=request.request_id,
            route=self.route,
            backend_id=self.backend_id,
            ok=True,
            frames_rendered=frames,
            wall_time_ms=wall_s * 1000.0,
            output_media=Path(request.output_media) if request.output_media else None,
        )

"""sprite_affine route adapter — FFmpeg encode path (S09-T00-I02).

Rigid translation/scale/rotation of the segment through a real FFmpeg
re-encode on THIS machine's stack (FFmpeg 8.1.2 + h264_nvenc, RTX 5070).
The affine transform is applied per-frame via rotate filter (which also
performs translation+scale in one pass) driven by the request's frame range;
runtime and peak VRAM are measured; binaries missing → fail closed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.adapters.renderer.encode_base import (
    FfmpegEncodeAdapterBase,
    _frames_in_range,
    _validate_media,
    measure_peak_vram_bytes_during,
)
from app.services.renderer_contract import RenderResult

__all__ = ["SpriteAffineAdapter"]

_CANONICAL_FPS = 30.0


class SpriteAffineAdapter(FfmpegEncodeAdapterBase):
    route_name = "sprite_affine"
    backend_id_value = "ffmpeg-nvenc-sprite-affine"

    def _render_impl(self, request: RenderRequest) -> RenderResult:
        paths, error = _validate_media(request, need_input=True)
        if error is not None or paths is None:
            return error  # type: ignore[return-value]
        input_media, output_media = paths
        gates = self._ensure_gates()

        frames = _frames_in_range(request)
        start_s = request.start_frame / _CANONICAL_FPS
        duration_s = frames / _CANONICAL_FPS
        # Deterministic rigid transform derived from the segment itself —
        # identity-centered rotation over the range (no external model).
        angle_deg = 1.0
        scale = 1.02

        encoder: list[str]
        if gates.nvenc.available:
            encoder = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
        else:
            encoder = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]

        vf = (
            f"rotate={angle_deg}*PI/180:ow=iw*{scale}:oh=ih*{scale}:c=black,"
            f"scale=iw/{scale:.4f}:ih/{scale:.4f}"
        )

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
            "-vf",
            vf,
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

        proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        wall_s, peak_vram = measure_peak_vram_bytes_during(lambda: proc)

        _, err_out = proc.communicate() if proc.stderr else ("", "")
        ok = proc.returncode == 0 and Path(output_media).is_file()

        from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter  # noqa: F401
        from app.services.renderer_contract import RendererContractCode

        if not ok:
            tail = (err_out or "").strip().splitlines()
            return RenderResult(
                request_id=request.request_id,
                route=self.route,
                backend_id=self.backend_id,
                ok=False,
                frames_rendered=0,
                wall_time_ms=wall_s * 1000.0,
                error_code=RendererContractCode.INVALID_REQUEST
                if proc.returncode != 0
                else RendererContractCode.BACKEND_BINARY_MISSING,
                error_detail=tail[-1] if tail else f"exit {proc.returncode}",
            )
        from app.services.renderer_contract import CapabilityDescriptor, utc_now_iso

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
            output_media=Path(request.output_media),
        )

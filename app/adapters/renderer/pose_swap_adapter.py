"""pose_swap route adapter — REAL pose/expression replacement (S09-T02-C1).

F1 correction: this adapter is no longer a trim+re-encode of the source
picture.  It composites the SCHEDULED replacement pose/expression states
over the source frames inside the affected region (deterministic CPU math,
``app/services/renderer_routes/composite.py``), then encodes the composed
frames.  NVENC is only an ENCODE ACCELERATION with provenance; the CPU path
(libx264/mp4v) is the deterministic reference.  No model download, no
network access.
"""

from __future__ import annotations

from app.adapters.renderer.encode_base import (
    FfmpegEncodeAdapterBase,
)
from app.services.renderer_contract import (
    CapabilityDescriptor,
    CapabilityMismatchError,
    RenderRequest,
    RenderResult,
)
from app.services.renderer_routes.composite import (
    canonical_frame_sha256,
    composite_pose_swap_frames,
    decode_rgb_frames,
    write_frames_mp4,
)

__all__ = ["PoseSwapAdapter"]


class PoseSwapAdapter(FfmpegEncodeAdapterBase):
    route_name = "pose_swap"
    backend_id_value = "ffmpeg-nvenc-pose-swap"

    #: Canonical decoded-frame hash of the last successful render (evidence).
    _last_output_sha256: str | None = None
    #: Per-frame active state map of the last successful render (evidence).
    _last_schedule_progress: dict[str, str] | None = None

    def _render_impl(self, request: RenderRequest) -> RenderResult:
        # FAIL BEFORE SUCCESS: binary gates first (stable taxonomy for a
        # vanished encoder), then the FULL typed contract validation —
        # all before any composite/encode work.
        gates = self._ensure_gates()
        request.validate_for_render()

        import time

        started = time.perf_counter()
        assert request.input_media is not None
        source_frames = decode_rgb_frames(request.input_media)
        if len(source_frames) < request.end_frame + 1:
            raise CapabilityMismatchError(
                f"source has {len(source_frames)} frames; render range needs "
                f"{request.end_frame + 1} (0-based inclusive)"
            )
        window = source_frames[
            request.start_frame : request.end_frame + 1
        ]

        progress: dict[str, str] = {}
        composed = composite_pose_swap_frames(window, request, progress=progress)
        expected = request.end_frame - request.start_frame + 1
        if len(composed) != expected:
            raise CapabilityMismatchError(
                f"compositor produced {len(composed)} frames; the inclusive "
                f"range {request.start_frame}..{request.end_frame} requires "
                f"{expected}"
            )

        # C2 (F5): encode at the SOURCE rational fps/timebase — never a
        # canonical retime.
        assert request.source_timebase is not None
        fps = request.timebase().fps_float
        # NVENC is ENCODE ACCELERATION only: the compositor above is the
        # deterministic CPU reference.  Encoder options are OUTPUT options —
        # they must come after the input spec fed by write_frames_mp4.
        encode_backend = "cv2-mp4v-deterministic"
        accelerated = False
        assert request.output_media is not None
        if gates.nvenc.available:
            encode_backend = "h264_nvenc"
            accelerated = True
            nvenc_out = [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-an",
            ]
            write_frames_mp4(
                composed,
                request.output_media,
                fps=fps,
                extra_output_opts=nvenc_out,
            )
        else:
            write_frames_mp4(
                composed,
                request.output_media,
                fps=fps,
            )
        wall_s = time.perf_counter() - started

        exit_ok = request.output_media.is_file()
        # C2 (F5): output_frame_sha256 hashes the CANONICAL DECODED FRAMES
        # of the written artifact (post-encode), not pre-encode buffers.
        output_hash: str | None = None
        decoded_count = 0
        if exit_ok:
            encoded_frames = decode_rgb_frames(request.output_media)
            decoded_count = len(encoded_frames)
            if decoded_count != expected:
                raise CapabilityMismatchError(
                    f"encoded output decodes to {decoded_count} frames; "
                    f"expected exactly {expected} (inclusive range "
                    f"{request.start_frame}..{request.end_frame})"
                )
            output_hash = canonical_frame_sha256(encoded_frames)
        result = self._finalize(
            request,
            exit_ok=exit_ok,
            wall_s=wall_s,
            peak_vram=None,
            frames=expected,
            stderr_tail="ffmpeg nvenc" if accelerated else "cv2 writer",
            compose_backend=encode_backend,
            output_sha256=output_hash,
            progress=progress,
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
        compose_backend: str = "unknown",
        output_sha256: str | None = None,
        progress: dict[str, str] | None = None,
    ) -> RenderResult:
        from app.services.renderer_contract import (
            RendererContractCode,
            utc_now_iso,
        )

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
        cap = self._capability_after_compose(
            compose_backend=compose_backend,
            measured_at_utc=utc_now_iso(),
            runtime_ms_per_frame=(wall_s * 1000.0) / max(frames, 1),
            vram_bytes=peak_vram,
            output_sha256=output_sha256,
            swap_frames=len(progress or {}),
        )
        self._last_capability = cap
        self._last_output_sha256 = output_sha256
        self._last_schedule_progress = dict(progress or {})
        return RenderResult(
            request_id=request.request_id,
            route=self.route,
            backend_id=self.backend_id,
            ok=True,
            frames_rendered=frames,
            wall_time_ms=wall_s * 1000.0,
            output_media=request.output_media,
        )

    def _capability_after_compose(
        self,
        *,
        compose_backend: str,
        measured_at_utc: str,
        runtime_ms_per_frame: float,
        vram_bytes: int | None,
        output_sha256: str | None,
        swap_frames: int,
    ) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            backend_id=self.backend_id,
            route=self.route,
            available=True,
            license_id=self._ensure_gates().ffmpeg.license_id or "ffmpeg-lgpl",
            evidence_source="measured_live",
            measured_at_utc=measured_at_utc,
            runtime_ms_per_frame=runtime_ms_per_frame,
            vram_bytes=vram_bytes,
            details={
                "encode": compose_backend,
                "composite": "pose_swap_schedule_cpu_deterministic",
                "output_frame_sha256": output_sha256,
                "swap_frames": swap_frames,
                "nvenc_provenance": (
                    "acceleration-only; compositor is CPU deterministic"
                    if compose_backend == "h264_nvenc"
                    else "cpu_reference"
                ),
            },
        )

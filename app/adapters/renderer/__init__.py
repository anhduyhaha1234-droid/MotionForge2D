"""Renderer backend adapters (S09-T00-I02).

Only backends VERIFIED AVAILABLE on this machine (lane-B audit, 2026-08-23):
FFmpeg 8.1.2 (gyan.dev full build) with h264_nvenc on RTX 5070.
pose_swap / sprite_affine routes run through the FFmpeg encode path.

NOT wired (no user authority): SAM-2, Cutie, any model download, mesh_warp /
part_rig / controlled_redraw execution backends — those routes currently
raise UnknownCapabilityError (fail closed) when requested.
"""

from app.adapters.renderer.ffmpeg_binary import (
    FfmpegProbe,
    probe_ffmpeg,
)
from app.adapters.renderer.nvenc import (
    NvencProbe,
    probe_nvenc,
    vram_bytes_via_nvidia_smi,
)
from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter

__all__ = [
    "FfmpegProbe",
    "NvencProbe",
    "PoseSwapAdapter",
    "SpriteAffineAdapter",
    "probe_ffmpeg",
    "probe_nvenc",
    "vram_bytes_via_nvidia_smi",
]

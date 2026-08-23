"""Minimal internal route-benchmark harness (S09-T00-I02).

TASK.md acceptance: benchmark pose_swap/sprite_affine BEFORE choosing the
default route mapping.  ``scripts/s09_renderer_benchmark.py`` (I03) is not
present yet, so this in-repo harness provides the measured evidence path:
it renders a real synthetic clip through each wired adapter, records
runtime-per-frame and peak VRAM into a JSON artifact, and returns the
default-route mapping (pose_swap first per overlay §8 priority).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter
from app.services.renderer_contract import (
    CapabilityDescriptor,
    RenderRequest,
    utc_now_iso,
)

__all__ = ["benchmark_wired_routes", "default_route_mapping"]


def _make_synthetic_clip(ffmpeg_exe: str, out_path: Path, frames: int = 24) -> None:
    """Deterministic testsrc clip at the canonical 30 fps timebase."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x240:rate={int(_CANONICAL_FPS_BENCH)}:duration="
        f"{frames / _CANONICAL_FPS_BENCH:.6f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


_CANONICAL_FPS_BENCH = 30.0


def benchmark_wired_routes(
    work_dir: Path,
    *,
    frames: int = 24,
) -> dict[str, Any]:
    """Measure both wired routes on a real synthetic clip.

    Returns a JSON-ready dict with per-route capability evidence and writes
    ``work_dir/route_benchmark.json``.
    """
    from app.adapters.renderer.ffmpeg_binary import probe_ffmpeg

    ffmpeg = probe_ffmpeg()
    if not ffmpeg.available or ffmpeg.ffmpeg_path is None:
        raise RuntimeError(f"ffmpeg unavailable: {ffmpeg.error}")

    clip = work_dir / "bench_input.mp4"
    _make_synthetic_clip(ffmpeg.ffmpeg_path, clip, frames=frames)

    results: dict[str, Any] = {
        "generated_at_utc": utc_now_iso(),
        "clip": str(clip),
        "frames": frames,
        "routes": {},
    }
    adapters: list[tuple[str, Any]] = [
        ("pose_swap", PoseSwapAdapter()),
        ("sprite_affine", SpriteAffineAdapter()),
    ]
    for name, adapter in adapters:
        cap_before: CapabilityDescriptor = adapter.capability()
        out = work_dir / f"bench_{name}.mp4"
        request = RenderRequest(
            request_id=f"bench-{name}-{frames}f",
            workspace_id="benchmark",
            project_id="benchmark",
            video_item_id="benchmark",
            occurrence_segment_id="seg-bench-0",
            route=name,
            start_frame=0,
            end_frame=frames - 1,
            input_media=clip,
            output_media=out,
        )
        result = adapter.render(request)
        entry: dict[str, Any] = {
            "ok": result.ok,
            "wall_time_ms": round(result.wall_time_ms, 3),
            "frames_rendered": result.frames_rendered,
            "output_media": str(result.output_media) if result.output_media else None,
            "error_code": result.error_code.value if result.error_code else None,
            "probe_available": cap_before.available,
            "license_id": cap_before.license_id,
        }
        last = getattr(adapter, "_last_capability", None)
        if last is not None:
            entry["runtime_ms_per_frame"] = (
                round(last.runtime_ms_per_frame, 3)
                if last.runtime_ms_per_frame is not None
                else None
            )
            entry["vram_bytes"] = last.vram_bytes
        results["routes"][name] = entry

    artifact = work_dir / "route_benchmark.json"
    artifact.write_text(json.dumps(results, sort_keys=True, indent=2), encoding="utf-8")
    results["artifact"] = str(artifact)
    return results


def default_route_mapping(benchmark: dict[str, Any]) -> dict[str, str]:
    """Choose defaults ONLY from measured-ok routes; pose_swap wins ties
    (overlay §8: held-pose/expression swap is the default route)."""
    mapping: dict[str, str] = {}
    for name in ("pose_swap", "sprite_affine"):
        entry = benchmark.get("routes", {}).get(name)
        if isinstance(entry, dict) and entry.get("ok") is True:
            mapping[name] = "ffmpeg-nvenc" + ("-pose-swap" if name == "pose_swap" else "-sprite-affine")
    return mapping

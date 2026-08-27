"""S09-T00-I02 tests — wired FFmpeg/NVENC adapters + benchmark harness.

REAL-process coverage on this machine's verified stack (FFmpeg 8.1.2 +
h264_nvenc, RTX 5070): probes succeed/fail-closed honestly, adapters encode a
real synthetic clip, measure runtime/VRAM, and refuse when binaries vanish.
Skips honestly (pytest.skip) if the local stack is absent — never fakes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.adapters.renderer.ffmpeg_binary import FfmpegProbe, probe_ffmpeg
from app.adapters.renderer.nvenc import probe_nvenc, vram_bytes_via_nvidia_smi
from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter
from app.services.renderer_contract import (
    AffectedRegion,
    AffineKeyframe,
    BackendBinaryMissingError,
    CapabilityDescriptor,
    RenderRequest,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def ffmpeg_probe() -> FfmpegProbe:
    probe = probe_ffmpeg()
    if not probe.available:
        pytest.skip(f"FFmpeg unavailable on this machine: {probe.error}")
    return probe


def test_ffmpeg_probe_reports_build_and_license(ffmpeg_probe: FfmpegProbe) -> None:
    assert ffmpeg_probe.license_id in ("ffmpeg-gpl-build", "ffmpeg-lgpl")
    assert ffmpeg_probe.is_gpl_build or ffmpeg_probe.is_lgpl_build
    assert "8.1.2" in (ffmpeg_probe.version_line or "")


def test_nvenc_probe_matches_machine_capability() -> None:
    nvenc = probe_nvenc()
    # On the audited machine this is True; if the driver disappears the probe
    # must say so honestly rather than raise.
    if nvenc.available:
        assert nvenc.error is None
        assert nvenc.encoder == "h264_nvenc"
    else:
        assert nvenc.error


def test_vram_query_returns_bytes_or_none() -> None:
    vram = vram_bytes_via_nvidia_smi()
    if vram is not None:
        assert vram > 1_000_000_000  # RTX 5070-class: >1GiB total


def _render_request(tmp_path: Path, route: str, clip: Path, name: str) -> RenderRequest:
    # S09-T02-C1: renders go through the FULL typed contract — every
    # benchmark/IT request carries a real replacement layer (or pose
    # schedule) so the composite pipeline is what's exercised.
    import cv2
    import numpy as np

    from app.services.renderer_contract import (
        PoseSwapEntry,
        ReplacementAsset,
    )
    from app.services.renderer_routes.composite import probe_source_timebase

    asset_path = tmp_path / f"repl_{name}.png"
    if not asset_path.is_file():
        layer = np.zeros((48, 48, 4), dtype=np.uint8)
        layer[:, :, 1] = 220
        layer[:, :, 3] = 255
        cv2.imwrite(str(asset_path), layer)
    kwargs: dict[str, object] = {
        "workspace_root": tmp_path,
        "affected_region": None,
    }
    if route == "pose_swap":
        pose_asset = ReplacementAsset(path=asset_path, kind="pose_state")
        kwargs["pose_state_assets"] = {"open": pose_asset}
        kwargs["pose_schedule"] = (
            PoseSwapEntry(frame=4, state_id="open", asset=pose_asset),
        )
        kwargs["affected_region"] = AffectedRegion((0.25, 0.25, 0.5, 0.5))
    else:
        kwargs["replacement_asset"] = ReplacementAsset(
            path=asset_path, kind="sprite"
        )
        kwargs["anchor_xy_norm"] = (0.5, 0.5)
        kwargs["affine_keyframes"] = (
            AffineKeyframe(frame=4),
            AffineKeyframe(frame=15, scale=1.05, rotation_deg=2.0),
        )
    return RenderRequest(
        request_id=f"it-{name}",
        workspace_id="ws-it",
        project_id="p-it",
        video_item_id="v-it",
        occurrence_segment_id="sg-it",
        route=route,
        start_frame=4,
        end_frame=15,
        input_media=clip,
        output_media=tmp_path / f"out_{name}.mp4",
        source_timebase=probe_source_timebase(clip),
        **kwargs,  # type: ignore[arg-type]
    )


def _synthetic_clip(ffmpeg_probe: FfmpegProbe, tmp_path: Path, frames: int = 24) -> Path:
    import subprocess

    clip = tmp_path / "clip.mp4"
    cmd = [
        str(ffmpeg_probe.ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=30:duration=0.8",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(clip),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    return clip


@pytest.mark.parametrize("adapter_cls,route", [
    (PoseSwapAdapter, "pose_swap"),
    (SpriteAffineAdapter, "sprite_affine"),
])
def test_adapters_encode_real_segment_and_measure(
    tmp_path: Path,
    adapter_cls: type,
    route: str,
) -> None:
    adapter = adapter_cls()
    cap: CapabilityDescriptor = adapter.capability()
    if not cap.available:
        pytest.skip(f"backend {cap.backend_id} unavailable: {cap.details}")

    from app.adapters.renderer.benchmark_harness import _make_synthetic_clip

    clip_dir = tmp_path / "in"
    clip_dir.mkdir(exist_ok=True)
    _make_synthetic_clip(str(probe_ffmpeg().ffmpeg_path), clip_dir / "clip.mp4", frames=24)
    request = _render_request(tmp_path, route, clip_dir / "clip.mp4", route)
    result = adapter.render(request)

    assert result.ok, f"encode failed: {result.error_code} {result.error_detail}"
    assert result.frames_rendered == 12  # frames 4..15 inclusive
    assert result.output_media is not None and result.output_media.is_file()
    assert result.wall_time_ms > 0

    last: CapabilityDescriptor | None = getattr(adapter, "_last_capability", None)
    assert last is not None and last.runtime_ms_per_frame is not None
    assert last.runtime_ms_per_frame < 1000.0  # sane upper bound for 12 frames


def test_adapter_fails_closed_when_binary_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract: with the binary gone, capability() reports available=False
    (fail-closed descriptor) and render() refuses instead of encoding."""
    import app.adapters.renderer.encode_base as eb

    def _missing(timeout_s: float = 20.0) -> FfmpegProbe:
        return FfmpegProbe(available=False, error="simulated missing binary")

    # A real tiny input media so the typed-contract helper can probe its
    # timebase; cv2 writer keeps this independent of any ffmpeg presence.
    import cv2
    import numpy as np

    clip = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(
        str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (32, 32)
    )
    assert writer.isOpened()
    for i in range(20):
        writer.write(np.full((32, 32, 3), i * 10, dtype=np.uint8))
    writer.release()

    monkeypatch.setattr(eb, "probe_ffmpeg", _missing)
    adapter = PoseSwapAdapter()
    cap = adapter.capability()
    assert cap.available is False
    assert "simulated missing binary" in cap.details.get("error", "")

    request = _render_request(tmp_path, "pose_swap", tmp_path / "clip.mp4", "missing")
    result = adapter.render(request)
    assert result.ok is False
    assert result.error_code is not None and result.error_code.value == (
        "backend_binary_missing"
    )
    # And the router-level gate also refuses to select it.
    from app.services.renderer_router import RendererRouter

    router = RendererRouter([adapter], evidence_dir=tmp_path)
    with pytest.raises(BackendBinaryMissingError):
        router.select_backend(request)


def test_benchmark_harness_end_to_end(tmp_path: Path) -> None:
    from app.adapters.renderer.benchmark_harness import (
        benchmark_wired_routes,
        default_route_mapping,
    )

    ffmpeg = probe_ffmpeg()
    if not ffmpeg.available:
        pytest.skip("FFmpeg unavailable")
    bench = benchmark_wired_routes(tmp_path, frames=24)
    routes = bench["routes"]
    assert set(routes) == {"pose_swap", "sprite_affine"}
    for name, entry in routes.items():
        assert entry["ok"] is True, f"{name}: {entry.get('error_code')}"
        assert entry["runtime_ms_per_frame"] is not None
        assert entry["license_id"] in ("ffmpeg-gpl-build", "ffmpeg-lgpl")
    mapping = default_route_mapping(bench)
    assert mapping["pose_swap"] == "ffmpeg-nvenc-pose-swap"
    artifact = Path(bench["artifact"])
    assert artifact.is_file()
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert data["routes"]["pose_swap"]["ok"] is True


def test_benchmark_before_default_mapping_ordering(tmp_path: Path) -> None:
    """Acceptance: benchmark BEFORE choosing default route mapping."""
    from app.adapters.renderer.benchmark_harness import default_route_mapping

    empty_bench: dict = {"routes": {}}
    assert default_route_mapping(empty_bench) == {}
    failed_bench: dict = {
        "routes": {"pose_swap": {"ok": False}, "sprite_affine": {"ok": False}}
    }
    assert default_route_mapping(failed_bench) == {}


def test_temp_env_guard_still_unset_in_tests() -> None:
    # The task guard must hold during test runs too.
    assert not os.environ.get("MOTIONFORGE_DATABASE_URL")

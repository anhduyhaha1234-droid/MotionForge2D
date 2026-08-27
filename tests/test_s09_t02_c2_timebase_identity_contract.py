"""S09-T02-C2 acceptance tests: production renderer contract (review F5).

Covers the seven mandatory corrections:

1. Rational source fps/timebase (SourceTimebase + tuple coercion) and typed
   layer ordering/occlusion (LayerOrderEntry) — f1_hard_cut / f5_group_
   occlusion representable through PUBLIC request fields only.
2. EXACT inclusive frame count preservation + source timebase at 24 fps,
   30 fps, and the NTSC rational rate 30000/1001.
3. Identity is a TYPED declaration (identity_transform=True + empty
   keyframe track); request IDs never change behavior.
4. output_frame_sha256 hashes canonical DECODED frames of the ENCODED
   artifact; recomputed independently from the output file it must match.
5. alpha_mode semantics executed (straight/premultiplied/fade_in);
   validation failures happen BEFORE any output artifact mutation.
6. Router .execute() dispatches to the route's adapter with stable
   taxonomy/provenance.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.renderer_contract import (
    AffectedRegion,
    AffineKeyframe,
    CapabilityMismatchError,
    LayerOrderEntry,
    PoseSwapEntry,
    RenderRequest,
    ReplacementAsset,
    SourceTimebase,
)
from app.services.renderer_routes.composite import (
    composite_sprite_affine_frames,
    decode_rgb_frames,
    probe_source_timebase,
)

# ── deterministic fixtures ───────────────────────────────────────────────────


def _write_clip(
    path: Path, frames: int = 24, size: tuple[int, int] = (256, 256)
) -> Path:
    """Deterministic gradient clip via the cv2 writer (no ffmpeg needed).

    256x256 keeps every frame above the h264_nvenc minimum frame dimension
    so the accelerated path stays exercisable with tiny fixtures.
    """
    w, h = size
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (w, h)
    )
    assert writer.isOpened()
    for i in range(frames):
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:, :, 0] = (i * 9) % 255
        img[:, :, 1] = (i * 5) % 255
        img[:, :, 2] = 60 + i
        writer.write(img)
    writer.release()
    assert path.is_file()
    return path


def _write_clip_fps(path: Path, frames: int, fps: float) -> Path:
    w, h = 256, 256
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h)
    )
    assert writer.isOpened()
    for i in range(frames):
        img = np.full((h, w, 3), i * 7 % 255, dtype=np.uint8)
        writer.write(img)
    writer.release()
    return path


def _solid_bgra(w: int, h: int, bgra: tuple[int, int, int, int]) -> np.ndarray:
    layer = np.zeros((h, w, 4), dtype=np.uint8)
    layer[:, :, 0], layer[:, :, 1], layer[:, :, 2], layer[:, :, 3] = bgra
    return layer


def _asset(path: Path, bgra: tuple[int, int, int, int]) -> ReplacementAsset:
    if not path.is_file():
        cv2.imwrite(str(path), _solid_bgra(24, 24, bgra))
    return ReplacementAsset(path=path, kind="pose_state")


def _request(tmp_path: Path, run: str, *, frames: int = 24) -> RenderRequest:
    src = tmp_path / f"src_{run}.mp4"
    _write_clip(src, frames=frames)
    red = _asset(tmp_path / "red.png", (0, 0, 255, 255))
    return RenderRequest(
        request_id=f"c2-{run}",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="pose_swap",
        start_frame=0,
        end_frame=frames - 1,
        input_media=src,
        output_media=tmp_path / f"out_{run}.mp4",
        workspace_root=tmp_path,
        source_timebase=(30, 1),
        affected_region=AffectedRegion((0.25, 0.25, 0.5, 0.5)),
        pose_state_assets={"r": red},
        pose_schedule=(
            PoseSwapEntry(frame=frames // 2, state_id="r", asset=red),
        ),
    )


def _render_via_adapter(
    request: RenderRequest, adapter_name: str
) -> tuple[object, object]:
    """Run the REAL adapter pipeline (encode + hash evidence).

    Returns (result, adapter) so tests can read ``adapter._last_capability``
    evidence recorded by the pipeline itself.
    """
    from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
    from app.adapters.renderer.sprite_affine_adapter import (
        SpriteAffineAdapter,
    )

    adapters: dict[str, object] = {
        "pose_swap": PoseSwapAdapter(),
        "sprite_affine": SpriteAffineAdapter(),
    }
    adapter = adapters[adapter_name]
    return adapter.render(request), adapter  # type: ignore[union-attr]


# ── 1+2. rational timebase: probe, contract typing, EXACT frame count ────────


def test_probe_source_timebase_extracts_container_fps(
    tmp_path: Path,
) -> None:
    clip_30 = _write_clip_fps(tmp_path / "c30.mp4", 30, 30.0)
    num, den = probe_source_timebase(clip_30)
    assert abs(num / den - 30.0) < 0.01
    # NTSC rational rate round-trips exactly when ffprobe is available.
    ntsc = tmp_path / "ntsc.mp4"
    from app.adapters.renderer.encode_base import probe_ffmpeg

    probe = probe_ffmpeg(timeout_s=20.0)
    if not probe.available:
        pytest.skip("ffmpeg binary unavailable on this host")
    import subprocess

    subprocess.run(
        [
            str(probe.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x48:rate=30000/1001:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(ntsc),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    n2, d2 = probe_source_timebase(ntsc)
    assert (n2, d2) == (30000, 1001)


def test_source_timebase_fraction_and_validation() -> None:
    tb = SourceTimebase(fps_num=30000, fps_den=1001)
    assert abs(tb.fps_float - 29.97) < 0.001
    assert tb.fps_exact == __import__("fractions").Fraction(30000, 1001)
    with pytest.raises(CapabilityMismatchError):
        SourceTimebase(fps_num=0, fps_den=1)
    with pytest.raises(CapabilityMismatchError):
        SourceTimebase(fps_num=30, fps_den=-1)
    with pytest.raises(CapabilityMismatchError):
        SourceTimebase(fps_num=-30, fps_den=1)


@pytest.mark.parametrize("fps", [24.0, 30.0])
def test_exact_inclusive_frame_count_and_timebase_preserved(
    tmp_path: Path, fps: float
) -> None:
    """Route truth at ≥24fps and 30fps: N source frames → N output frames
    at the SAME rational timebase (no canonical retime, no dropped tail)."""
    src = _write_clip_fps(tmp_path / "src.mp4", 31, fps)
    req = RenderRequest(
        request_id=f"c2-count-{int(fps)}",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="sprite_affine",
        start_frame=3,
        end_frame=26,  # inclusive window of 24 frames inside 31
        input_media=src,
        output_media=tmp_path / "out.mp4",
        workspace_root=tmp_path,
        source_timebase=probe_source_timebase(src),
        replacement_asset=ReplacementAsset(
            path=_asset(tmp_path / "sp.png", (10, 200, 40, 255)).path,
            kind="sprite",
        ),
        anchor_xy_norm=(0.5, 0.5),
        affine_keyframes=(
            AffineKeyframe(frame=3),
            AffineKeyframe(frame=26, scale=1.04),
        ),
        affected_region=AffectedRegion((0.25, 0.25, 0.5, 0.5)),
    )
    result, _adapter = _render_via_adapter(req, "sprite_affine")
    assert result.ok, result.error_detail  # type: ignore[attr-defined]
    out_frames = decode_rgb_frames(req.output_media)
    # EXACT inclusive count: end - start + 1.
    assert len(out_frames) == 24
    # Timebase preserved: probed output fps ≈ declared source fps.
    out_probe = cv2.VideoCapture(str(req.output_media))
    try:
        out_fps = out_probe.get(cv2.CAP_PROP_FPS)
    finally:
        out_probe.release()
    assert abs(out_fps - fps) < 0.05


def test_ntsc_rational_timebase_render_when_ffmpeg_present(
    tmp_path: Path,
) -> None:
    from app.adapters.renderer.encode_base import probe_ffmpeg

    probe = probe_ffmpeg(timeout_s=20.0)
    if not probe.available:
        pytest.skip("ffmpeg binary unavailable on this host")
    import subprocess

    src = tmp_path / "src_ntsc.mp4"
    subprocess.run(
        [
            str(probe.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=256x256:rate=30000/1001:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(src),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    red = _asset(tmp_path / "red.png", (0, 0, 255, 255))
    req = RenderRequest(
        request_id="c2-ntsc",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="pose_swap",
        start_frame=0,
        end_frame=23,
        input_media=src,
        output_media=tmp_path / "out_ntsc.mp4",
        workspace_root=tmp_path,
        source_timebase=(30000, 1001),
        affected_region=AffectedRegion((0.25, 0.25, 0.5, 0.5)),
        pose_state_assets={"r": red},
        pose_schedule=(PoseSwapEntry(frame=12, state_id="r", asset=red),),
    )
    result, _adapter = _render_via_adapter(req, "pose_swap")
    assert result.ok, result.error_detail  # type: ignore[attr-defined]
    cap = cv2.VideoCapture(str(req.output_media))
    try:
        out_fps = cap.get(cv2.CAP_PROP_FPS)
        out_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    assert abs(out_fps - 30000 / 1001) < 0.05
    assert out_count == 24


def test_missing_source_timebase_refused(tmp_path: Path) -> None:
    # The field defaults to None (constructor-safe); the FULL render
    # validation refuses any encode-backed request without it.
    req = replace(_request(tmp_path, "notb"), source_timebase=None)
    with pytest.raises(CapabilityMismatchError, match="source_timebase"):
        req.validate_for_render()


# ── 1. typed layer ordering / occlusion (f5_group_occlusion public) ──────────


def test_layer_order_entry_bounds_and_occlusion_composite(
    tmp_path: Path,
) -> None:
    src_frames = [_gradient(i) for i in range(6)]
    # Real media so validate_for_render passes its earlier file checks and
    # actually reaches the layer_order bounds validation.
    _write_clip(tmp_path / "src_f5.mp4", frames=6)
    sprite = ReplacementAsset(
        path=_asset(tmp_path / "green.png", (20, 220, 20, 255)).path,
        kind="sprite",
    )
    occluder = ReplacementAsset(
        path=_asset(tmp_path / "dark.png", (80, 0, 80, 255)).path,
        kind="sprite",
    )
    base = dict(
        request_id="c2-f5",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="sprite_affine",
        start_frame=0,
        end_frame=5,
        input_media=tmp_path / "src_f5.mp4",
        output_media=tmp_path / "out_f5.mp4",
        workspace_root=tmp_path,
        source_timebase=(30, 1),
        replacement_asset=sprite,
        anchor_xy_norm=(0.5, 0.5),
        affine_keyframes=(AffineKeyframe(frame=0),),
        affected_region=AffectedRegion(None),
        occluder_assets={"veil": occluder},
    )
    # Bounds: entry outside the render range refuses at validate_for_render
    # (constructor accepts; the FULL validation enforces the range).
    req_oob = RenderRequest(
        **base, layer_order=(LayerOrderEntry(99, 100, "replacement", 1),)
    )
    with pytest.raises(CapabilityMismatchError, match="outside render range"):
        req_oob.validate_for_render()
    with pytest.raises(CapabilityMismatchError):
        LayerOrderEntry(-1, 2, "replacement", 1)

    req_above = RenderRequest(
        **base, layer_order=(LayerOrderEntry(0, 5, "replacement", -1),)
    )
    req_below = RenderRequest(
        **base, layer_order=(LayerOrderEntry(0, 5, "replacement", 1),)
    )
    above = composite_sprite_affine_frames(src_frames, req_above)
    below = composite_sprite_affine_frames(src_frames, req_below)
    # plain = same request WITHOUT any occlusion semantics
    plain = composite_sprite_affine_frames(
        src_frames, replace(req_above, layer_order=(), occluder_assets=None)
    )
    # z<0 → occluder covers the replacement; z>0 → occluder sits under it.
    center = above[3].shape[0] // 2, above[3].shape[1] // 2
    px_above = above[3][center[0], center[1]]
    px_below = below[3][center[0], center[1]]
    assert not np.array_equal(px_above, px_below)
    assert not np.array_equal(px_above, plain[3][center[0], center[1]])
    # And the occluded pixel is exactly the occluder's own color.
    assert px_above.tolist() == [80, 0, 80]


def _gradient(i: int) -> np.ndarray:
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    img[:, :, 0] = i * 40 % 255
    img[:, :, 1] = 90
    return img


# ── 3. identity is TYPED — request ids carry no business meaning ─────────────


def test_identity_is_typed_not_request_id_string_matching(
    tmp_path: Path,
) -> None:
    src_frames = [_gradient(i) for i in range(8)]
    sprite = ReplacementAsset(
        path=_asset(tmp_path / "blue.png", (200, 40, 10, 255)).path,
        kind="sprite",
    )

    def make(req_id: str, *, identity: bool) -> RenderRequest:
        return RenderRequest(
            request_id=req_id,
            workspace_id="ws",
            project_id="p",
            video_item_id="v",
            occurrence_segment_id="sg",
            route="sprite_affine",
            start_frame=0,
            end_frame=7,
            workspace_root=tmp_path,
            source_timebase=(30, 1),
            replacement_asset=sprite,
            anchor_xy_norm=(0.5, 0.5),
            affine_keyframes=() if identity else (
                AffineKeyframe(frame=0),
                AffineKeyframe(frame=7, scale=1.15),
            ),
            identity_transform=identity,
            affected_region=AffectedRegion(None),
        )

    plain_named_identity = make("seg@identity", identity=False)
    typed_identity = make("anything-else", identity=True)
    full = make("plain", identity=False)

    out_named = composite_sprite_affine_frames(src_frames, plain_named_identity)
    out_full = composite_sprite_affine_frames(src_frames, full)
    # The "@identity" SUFFIX changes NOTHING (byte-equal composite).
    for a, b in zip(out_named, out_full):
        assert np.array_equal(a, b)
    out_ident = composite_sprite_affine_frames(src_frames, typed_identity)
    # Typed identity ≠ scaled track: geometry differs.
    assert not np.array_equal(out_ident[-1], out_full[-1])

    # Contradictory pairing refuses at the contract boundary.
    with pytest.raises(CapabilityMismatchError):
        replace(typed_identity, affine_keyframes=(AffineKeyframe(frame=0),))


def test_optimized_adapter_ignores_request_id_suffix(
    tmp_path: Path,
) -> None:
    """The optimized backend decides ONLY on the typed field."""
    from app.services.renderer_routes.adaptive_pose_swap import (
        OptimizedSpriteAffineAdapter,
    )

    adapter = OptimizedSpriteAffineAdapter()
    req = replace(_request(tmp_path, "idsuffix"), route="sprite_affine")
    req = replace(
        req,
        replacement_asset=ReplacementAsset(
            path=req.pose_state_assets["r"].path, kind="sprite"
        ),
        pose_state_assets=None,
        pose_schedule=None,
        anchor_xy_norm=(0.5, 0.5),
        affine_keyframes=(AffineKeyframe(frame=0),),
    )
    named = replace(req, request_id="whatever@identity")
    res_named = adapter.render(named)
    assert res_named.ok, res_named.error_detail  # type: ignore[attr-defined]
    assert adapter.last_identity_filter_skip is False


# ── 4. output_frame_sha256 hashes DECODED FRAMES OF THE ARTIFACT ─────────────


def test_output_hash_recomputed_from_file_matches_evidence(
    tmp_path: Path,
) -> None:
    from app.services.renderer_routes.composite import (
        canonical_frame_sha256,
    )

    req = _request(tmp_path, "hashcheck")
    result, adapter = _render_via_adapter(req, "pose_swap")
    assert result.ok, result.error_detail  # type: ignore[attr-defined]
    # INDEPENDENT recompute: decode the artifact again from disk.
    decoded = decode_rgb_frames(req.output_media)
    expected_hash = canonical_frame_sha256(decoded)
    last_cap = getattr(adapter, "_last_capability", None)
    assert last_cap is not None
    recorded = last_cap.details.get("output_frame_sha256")
    assert isinstance(recorded, str) and len(recorded) == 64
    assert recorded == expected_hash
    # And the artifact really has the exact inclusive frame count.
    assert len(decoded) == 24


# ── 5. alpha_mode semantics executed + fail-before-mutation ──────────────────


def test_alpha_mode_semantics_are_executed(tmp_path: Path) -> None:
    from app.services.renderer_routes.composite import apply_alpha_mode

    rgba = _solid_bgra(16, 16, (5, 6, 7, 200)).astype(np.float64)
    straight = apply_alpha_mode(
        rgba.astype(np.uint8).copy(), "straight"
    ).astype(np.float64)
    premult = apply_alpha_mode(rgba.astype(np.uint8).copy(), "premultiplied")
    opaque = apply_alpha_mode(rgba.astype(np.uint8).copy(), "opaque")
    # straight keeps channels as-is; opaque forces full alpha; premultiplied
    # UN-premultiplies RGB by alpha so composite colors are preserved.
    assert float(straight[:, :, 3].max()) == 200.0
    assert float(opaque[:, :, 3].min()) == 255.0
    assert np.all(premult[:, :, :3] >= straight[:, :, :3] - 1e-6)
    with pytest.raises(CapabilityMismatchError):
        apply_alpha_mode(rgba.astype(np.uint8).copy(), "screen_blend")


def test_invalid_requests_fail_before_artifact_mutation(
    tmp_path: Path,
) -> None:
    """Range/containment violations refuse BEFORE any artifact is written."""
    from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter

    req = _request(tmp_path, "failfirst")
    sentinel = req.output_media
    # Output must NOT exist before any accepted render attempt here.
    assert not sentinel.exists()

    # Source decode length < end_frame+1 → adapter refuses BEFORE encode
    # (render() maps the taxonomy error onto the stable INVALID_REQUEST code).
    from app.services.renderer_contract import RendererContractCode

    bad_range = replace(req, end_frame=999)
    result_bad = PoseSwapAdapter().render(bad_range)
    assert result_bad.ok is False
    assert result_bad.error_code is RendererContractCode.INVALID_REQUEST
    assert "1000" in (result_bad.error_detail or "")
    assert not sentinel.exists(), "validation failure mutated the artifact"

    bad_outside = replace(
        req, output_media=tmp_path.parent / "escape_out.mp4"
    )
    with pytest.raises(CapabilityMismatchError):
        bad_outside.validate_for_render()
    assert not sentinel.exists()


# ── 5b. container/output-media validation ────────────────────────────────────


def test_output_must_differ_from_input_and_be_contained(
    tmp_path: Path,
) -> None:
    req = _request(tmp_path, "container")
    same = replace(req, output_media=req.input_media)
    with pytest.raises(CapabilityMismatchError, match="differ"):
        same.validate_for_render()
    outside = replace(req, output_media=req.workspace_root.parent / "x.mp4")
    with pytest.raises(CapabilityMismatchError):
        outside.validate_for_render()


# ── 5c. J1-C2-v2: per-occluder placement rects ───────────────────────────────


def _v2_occlusion_base(tmp_path: Path) -> dict[str, object]:
    """Shared base for per-region occluder tests (sprite free-roam setup)."""
    sprite = ReplacementAsset(
        path=_asset(tmp_path / "green.png", (20, 220, 20, 255)).path,
        kind="sprite",
    )
    occluder = ReplacementAsset(
        path=_asset(tmp_path / "dark.png", (80, 0, 80, 255)).path,
        kind="sprite",
    )
    return dict(
        request_id="c2v2-region",
        workspace_id="ws",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="sg",
        route="sprite_affine",
        start_frame=0,
        end_frame=5,
        input_media=tmp_path / "src_v2.mp4",
        output_media=tmp_path / "out_v2.mp4",
        workspace_root=tmp_path,
        source_timebase=(30, 1),
        replacement_asset=sprite,
        anchor_xy_norm=(0.5, 0.5),
        affine_keyframes=(AffineKeyframe(frame=0),),
        affected_region=AffectedRegion(None),
        occluder_assets={"pillar": occluder},
    )


def test_occluder_region_draws_only_inside_sub_rect(tmp_path: Path) -> None:
    from app.services.renderer_routes.composite import (
        composite_sprite_affine_frames,
    )

    src_frames = [_gradient(i) for i in range(6)]
    req = RenderRequest(
        **_v2_occlusion_base(tmp_path),  # type: ignore[arg-type]
        layer_order=(LayerOrderEntry(0, 5, "replacement", -1),),
        # Pillar occupies x in [0.6, 1.0) of the frame only.
        occluder_regions={"pillar": (0.6, 0.0, 0.4, 1.0)},
    )
    frames = composite_sprite_affine_frames(src_frames, req)
    h, w = frames[3].shape[:2]
    inside_x = int(0.8 * w)
    outside_x = int(0.3 * w)
    cy = h // 2
    # Inside the sub-rect the occluder covers everything (z=-1: after the
    # replacement too).
    assert frames[3][cy, inside_x].tolist() == [80, 0, 80]
    # Outside the sub-rect the frame is untouched source pixels.
    assert np.array_equal(frames[3][cy, outside_x], src_frames[3][cy, outside_x])


def test_occluder_region_z_inversion_zero_free_roam(tmp_path: Path) -> None:
    from app.services.renderer_routes.composite import (
        composite_sprite_affine_frames,
    )

    src_frames = [_gradient(i) for i in range(6)]
    # Replacement free-ROAMS via a translation track sweeping across the
    # whole frame while the pillar stays confined to its sub-rect.
    base = _v2_occlusion_base(tmp_path)
    del base["affine_keyframes"]
    track = (
        AffineKeyframe(frame=0, translation_xy=(-0.45, -0.25)),
        AffineKeyframe(frame=5, translation_xy=(0.35, 0.25)),
    )
    below_req = RenderRequest(
        **base,  # type: ignore[arg-type]
        affine_keyframes=track,
        layer_order=(LayerOrderEntry(0, 5, "replacement", 1),),
        occluder_regions={"pillar": (0.55, 0.3, 0.4, 0.5)},
    )
    above_req = replace(below_req, layer_order=(
        LayerOrderEntry(0, 5, "replacement", -1),
    ))
    plain_req = replace(below_req, layer_order=(), occluder_assets=None)
    below = composite_sprite_affine_frames(src_frames, below_req)
    above = composite_sprite_affine_frames(src_frames, above_req)
    plain = composite_sprite_affine_frames(src_frames, plain_req)

    h, w = below[3].shape[:2]
    # The ONLY legitimate differences are INSIDE the pillar rect where z<0
    # must cover the replacement and z>0 must let it win.  Use the SAME
    # pixel-rect helper the compositor uses so boundary rounding matches.
    from app.services.renderer_routes.composite import _region_px

    rx0, ry0, rx1, ry1 = _region_px((0.55, 0.3, 0.4, 0.5), w, h)
    inversions = 0
    unexplained = 0
    for yy in range(h):
        for xx in range(w):
            b = below[3][yy, xx]
            a = above[3][yy, xx]
            p = plain[3][yy, xx]
            inside = rx0 <= xx < rx1 and ry0 <= yy < ry1
            if inside:
                continue  # occlusion semantics live here — anything goes
            # Outside the sub-rect: z-order must have ZERO effect and the
            # free-roam replacement must match the occluder-free composite.
            if not np.array_equal(b, a):
                inversions += 1
            if not np.array_equal(b, p):
                unexplained += 1
    assert inversions == 0, "z-order effects leaked outside the sub-rect"
    assert unexplained == 0, (
        "visibility changed without any occluder cause"
    )


def test_occluder_region_validation_fail_closed(tmp_path: Path) -> None:
    # Real media so validate_for_render reaches the region checks.
    _write_clip(tmp_path / "src_v2.mp4", frames=6)
    base = _v2_occlusion_base(tmp_path)
    req = RenderRequest(
        **base,  # type: ignore[arg-type]
        layer_order=(LayerOrderEntry(0, 5, "replacement", 1),),
        occluder_regions={"ghost": (0.1, 0.1, 0.2, 0.2)},
    )
    with pytest.raises(CapabilityMismatchError, match="no matching"):
        req.validate_for_render()
    oob = RenderRequest(
        **base,  # type: ignore[arg-type]
        layer_order=(LayerOrderEntry(0, 5, "replacement", 1),),
        occluder_regions={"pillar": (0.9, 0.9, 0.5, 0.5)},
    )
    with pytest.raises(CapabilityMismatchError, match="bounds"):
        oob.validate_for_render()
    nan_rect = RenderRequest(
        **base,  # type: ignore[arg-type]
        layer_order=(LayerOrderEntry(0, 5, "replacement", 1),),
        occluder_regions={"pillar": (float("nan"), 0.0, 0.2, 0.2)},
    )
    with pytest.raises(CapabilityMismatchError):
        nan_rect.validate_for_render()
    zero_w = RenderRequest(
        **base,  # type: ignore[arg-type]
        layer_order=(LayerOrderEntry(0, 5, "replacement", 1),),
        occluder_regions={"pillar": (0.1, 0.1, 0.0, 0.2)},
    )
    with pytest.raises(CapabilityMismatchError, match="positive"):
        zero_w.validate_for_render()


# ── 6. router execute dispatch + stable taxonomy/provenance ──────────────────


def test_router_execute_dispatches_to_route_adapter(
    tmp_path: Path,
) -> None:
    from app.services.renderer_contract import UnknownCapabilityError
    from app.services.renderer_router import RendererRouter

    req = _request(tmp_path, "routerexec")
    router = RendererRouter(
        [_UnrenderablePoseAdapter("fake-pose")],
        evidence_dir=tmp_path,
    )
    # Selection: the ONLY candidate is unavailable → stable taxonomy error.
    with pytest.raises(UnknownCapabilityError):
        router.select_backend(req)
    # execute(): dispatches to the REAL route adapter; provenance carries the
    # SERVING backend's identity (the proxy delegates render() to the inner
    # PoseSwapAdapter, whose backend_id is what lands on the result).
    real = RendererRouter([_RealPoseAdapterProxy()], evidence_dir=tmp_path)
    result = real.execute(req)
    assert result.ok, result.error_detail
    assert result.backend_id == "ffmpeg-nvenc-pose-swap"


class _RealPoseAdapterProxy:
    """Wraps the REAL PoseSwapAdapter under a distinct backend id."""

    route = "pose_swap"

    def __init__(self) -> None:
        from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter

        self._inner = PoseSwapAdapter()

    @property
    def backend_id(self) -> str:
        return "real-proxy"

    def capability(self):
        cap = self._inner.capability()
        from dataclasses import replace as _replace

        return _replace(cap, backend_id="real-proxy")

    def render(self, request):
        return self._inner.render(request)


class _UnrenderablePoseAdapter:
    """Registered pose_swap backend that can never render (unavailable)."""

    route = "pose_swap"

    def __init__(self, backend_id: str) -> None:
        self._bid = backend_id

    @property
    def backend_id(self) -> str:
        return self._bid

    def capability(self):
        from app.services.renderer_contract import CapabilityDescriptor

        return CapabilityDescriptor(
            backend_id=self.backend_id,
            route=self.route,
            available=False,
            license_id="ffmpeg-lgpl",
            details={"error": "simulated unavailable"},
        )

    def render(self, request):  # pragma: no cover - selection must refuse
        raise AssertionError("selection must refuse an unavailable backend")

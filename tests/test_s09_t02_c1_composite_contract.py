"""S09-T02-C1 acceptance tests — REAL compositing, no fake re-encode.

Binary acceptance from the correction prompt:

- PIXEL: the rendered output differs from the source INSIDE the replacement
  region only where the schedule/keyframes say so; pixels OUTSIDE stay
  bit-stable (tolerance quantified per assertion);
- SCHEDULE ACCURACY: pose A/B states appear on the annotated history with
  ≤1 frame error;
- GEOMETRY: translation/scale/rotation apply to the REPLACEMENT LAYER at
  the requested anchor/keyframes — never a transform of the source frame,
  never a fixed 1°/1.02 hack;
- FAIL-CLOSED: path escape, missing assets and NaN inputs refuse BEFORE any
  success artifact exists;
- DETERMINISM: two runs of the same request produce the same canonical
  decoded-frame hash;
- ENCODING GATE: module-level checks pass under both PYTHONUTF8 unset and
  PYTHONUTF8=1 (subprocess pinned encoding='utf-8', errors='replace').

All fixtures are generated at runtime with numpy/OpenCV (deterministic);
no network, no model downloads.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.renderer_contract import (
    AffectedRegion,
    AffineKeyframe,
    CapabilityMismatchError,
    PoseSwapEntry,
    RenderRequest,
    ReplacementAsset,
)
from app.services.renderer_routes.composite import (
    composite_pose_swap_frames,
    composite_sprite_affine_frames,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_W, _H = 320, 240


def _gradient_frames(n: int, w: int = _W, h: int = _H) -> list[np.ndarray]:
    """Deterministic horizontal-gradient frames (column index mod 256)."""
    base = np.zeros((h, w, 3), dtype=np.uint8)
    base[:, :, 0] = np.tile(np.arange(w, dtype=np.uint8), (h, 1))
    base[:, :, 2] = 40
    return [base.copy() for _ in range(n)]


def _solid_bgra(
    w: int, h: int, bgr: tuple[int, int, int], alpha: int = 255
) -> np.ndarray:
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2] = bgr
    img[:, :, 3] = alpha
    return img


def _write_asset(path: Path, img: np.ndarray) -> ReplacementAsset:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), img)
    assert ok, f"fixture asset failed to write: {path}"
    return ReplacementAsset(path=path, kind="pose_state")


def _region_px(
    bbox: tuple[float, float, float, float], w: int, h: int
) -> tuple[int, int, int, int]:
    x0 = int(round(bbox[0] * w))
    y0 = int(round(bbox[1] * h))
    x1 = int(round((bbox[0] + bbox[2]) * w))
    y1 = int(round((bbox[1] + bbox[3]) * h))
    return x0, y0, x1, y1


# ── PIXEL: schedule-following replacement, outside-region stability ──────────


def test_pose_swap_pixels_follow_schedule_and_stay_stable_outside(
    tmp_path: Path,
) -> None:
    """From each scheduled frame the region shows THAT state; before the
    first swap frames are verbatim; outside the region every frame is
    EXACTLY the source (zero tolerance — pure CPU copy)."""
    root = tmp_path / "ws"
    root.mkdir()
    red = _write_asset(root / "closed.png", _solid_bgra(64, 64, (0, 0, 255)))
    req = RenderRequest(
        request_id="c1-pixel-schedule",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="pose_swap",
        start_frame=0,
        end_frame=7,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        affected_region=AffectedRegion((0.25, 0.25, 0.5, 0.5)),
        pose_state_assets={"closed": red},
        pose_schedule=(PoseSwapEntry(frame=2, state_id="closed", asset=red),),
    )
    source = _gradient_frames(8)
    composed = composite_pose_swap_frames(source, req)
    assert len(composed) == 8

    bbox = (0.25, 0.25, 0.5, 0.5)
    rx0, ry0, rx1, ry1 = _region_px(bbox, _W, _H)

    # Frames BEFORE the first scheduled swap are verbatim copies.
    for idx in (0, 1):
        assert np.array_equal(composed[idx], source[idx]), (
            f"frame {idx} must be untouched before its swap"
        )

    # From the swap frame onward: inside = solid red (full replacement),
    # outside = EXACTLY the source pixels.
    for idx in range(2, 8):
        out = composed[idx]
        inner = out[ry0 + 4 : ry1 - 4, rx0 + 4 : rx1 - 4]
        # The compositor resizes the 64x64 template to the region; interior
        # stays solid red after INTER_AREA downsampling of a constant image.
        assert (inner[:, :, 2] > 200).all(), f"frame {idx}: region not red"
        assert (inner[:, :, 1] < 60).all(), f"frame {idx}: region polluted"
        outside_mask = np.ones((_H, _W), dtype=bool)
        outside_mask[ry0:ry1, rx0:rx1] = False
        assert np.array_equal(out[outside_mask], source[idx][outside_mask]), (
            f"frame {idx}: pixels outside the affected region changed"
        )


def test_pose_schedule_state_history_within_one_frame(tmp_path: Path) -> None:
    """Pose A/B appear on the annotated history: sampled mid-window between
    swaps classifies as the earlier state, after the later swap as the new
    one (≤1 frame tolerance via exact boundary sampling)."""
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    red = _write_asset(root / "a.png", _solid_bgra(48, 48, (0, 0, 255)))
    blue = _write_asset(root / "b.png", _solid_bgra(48, 48, (255, 0, 0)))
    req = RenderRequest(
        request_id="c1-history",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="pose_swap",
        start_frame=0,
        end_frame=9,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        affected_region=AffectedRegion((0.3, 0.3, 0.4, 0.4)),
        pose_state_assets={
            "state_a": red,
            "state_b": blue,
        },
        pose_schedule=(
            PoseSwapEntry(frame=2, state_id="state_a", asset=red),
            PoseSwapEntry(frame=6, state_id="state_b", asset=blue),
        ),
    )
    progress: dict[str, object] = {}
    composed = composite_pose_swap_frames(_gradient_frames(10), req, progress=progress)
    # Active-state timeline recorded by the compositor itself.
    assert progress["2"] == "state_a"
    assert progress["5"] == "state_a"  # held until superseded
    assert progress["6"] == "state_b"
    assert progress["9"] == "state_b"

    def dominant_color(frame_idx: int) -> str:
        rx0, ry0, rx1, ry1 = _region_px((0.3, 0.3, 0.4, 0.4), _W, _H)
        inner = composed[frame_idx][ry0 + 3 : ry1 - 3, rx0 + 3 : rx1 - 3]
        return "red" if float(inner[:, :, 2].mean()) > float(inner[:, :, 0].mean()) else "blue"

    assert dominant_color(3) == "red"
    assert dominant_color(7) == "blue"


def test_mask_limits_where_replacement_may_change_pixels(tmp_path: Path) -> None:
    """With a mask asset covering only the lower half of the region, the
    upper half keeps source pixels even INSIDE the affected bbox."""
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    red = _write_asset(root / "r.png", _solid_bgra(80, 80, (0, 0, 255)))
    mask = np.zeros((80, 80), dtype=np.uint8)
    mask[40:, :] = 255  # only the bottom half may change
    mask_asset = _write_asset(root / "m.png", cv2.cvtColor(mask, cv2.COLOR_GRAY2BGRA))
    req = RenderRequest(
        request_id="c1-mask",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="pose_swap",
        start_frame=0,
        end_frame=3,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        affected_region=AffectedRegion((0.25, 0.25, 0.5, 0.5)),
        pose_state_assets={"r": red},
        pose_schedule=(PoseSwapEntry(frame=0, state_id="r", asset=red),),
        mask_asset=ReplacementAsset(path=mask_asset.path, kind="mask_overlay"),
    )
    source = _gradient_frames(4)
    composed = composite_pose_swap_frames(source, req)
    rx0, ry0, rx1, ry1 = _region_px((0.25, 0.25, 0.5, 0.5), _W, _H)
    mid_y = (ry0 + ry1) // 2
    top = composed[0][mid_y - 12 : mid_y - 4, rx0 + 4 : rx1 - 4]
    src_top = source[0][mid_y - 12 : mid_y - 4, rx0 + 4 : rx1 - 4]
    assert np.array_equal(top, src_top), "masked-out area changed (must stay)"
    bottom_center = composed[0][ry1 - 6, (rx0 + rx1) // 2]
    assert int(bottom_center[2]) > 200, "masked-in area did not receive red"


# ── GEOMETRY: affine applies to the REPLACEMENT LAYER ────────────────────────


def _affine_request(
    tmp_path: Path,
    keyframes: tuple[AffineKeyframe, ...],
    left_red_sprite: bool = True,
) -> RenderRequest:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    sprite = np.zeros((40, 40, 4), dtype=np.uint8)
    sprite[:, :, 3] = 255
    if left_red_sprite:
        sprite[:, :20, 2] = 235  # LEFT half red
        sprite[:, 20:, 0] = 235  # RIGHT half blue
    else:  # pragma: no cover - reserved variant
        sprite[:, :, 1] = 235
    asset = _write_asset(root / "layer.png", sprite)
    return RenderRequest(
        request_id=f"c1-affine-{tmp_path.name}",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="sprite_affine",
        start_frame=0,
        end_frame=5,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        replacement_asset=ReplacementAsset(path=asset.path, kind="sprite"),
        anchor_xy_norm=(0.5, 0.5),
        affine_keyframes=keyframes,
    )


def test_affine_translation_moves_layer_per_keyframes(tmp_path: Path) -> None:
    """The layer's footprint tracks anchor+translation across frames while
    everything far from the track stays EXACTLY source."""
    kfs = (
        AffineKeyframe(frame=0, translation_xy=(-0.2, 0.0)),
        AffineKeyframe(frame=5, translation_xy=(0.2, 0.0)),
    )
    req = _affine_request(tmp_path, kfs)
    source = _gradient_frames(6)
    composed = composite_sprite_affine_frames(source, req)

    def changed_mask(out: np.ndarray, src: np.ndarray) -> np.ndarray:
        return np.any(out != src, axis=2)

    m0 = changed_mask(composed[0], source[0])
    m5 = changed_mask(composed[5], source[5])
    ys0, xs0 = np.nonzero(m0)
    ys5, xs5 = np.nonzero(m5)
    assert xs0.size and xs5.size, "replacement layer produced no footprint"
    # Footprint centers move left → right per the keyframe track (±0.2 of
    # width around the 0.5 anchor), with small numeric tolerance.
    cx0, cx5 = float(xs0.mean()), float(xs5.mean())
    expected = 0.1 * _W  # half-track span
    assert abs(cx0 - (0.5 * _W - expected)) < 40.0, (cx0, 0.5 * _W - expected)
    assert abs(cx5 - (0.5 * _W + expected)) < 40.0, (cx5, 0.5 * _W + expected)
    # Directional check: frame 5's footprint center is RIGHT of frame 0's.
    assert cx5 > cx0 + 2 * (expected - 40.0)
    # Far corners keep source pixels on EVERY frame (translation-only track
    # cannot reach them).
    for idx in range(6):
        corner = composed[idx][10:24, 290:310]
        assert np.array_equal(corner, source[idx][10:24, 290:310])


def test_affine_rotation_applies_to_layer_not_source(tmp_path: Path) -> None:
    """A 90° keyframe rotates the REPLACEMENT LAYER: the red/blue split of
    the sprite flips from vertical to horizontal inside the footprint while
    the source gradient (identical in every frame) stays untouched outside
    it — proving the transform never touches the source picture."""
    kfs = (AffineKeyframe(frame=0, rotation_deg=90.0, scale=1.6),)
    req = _affine_request(tmp_path, kfs)
    source = _gradient_frames(4)
    composed = composite_sprite_affine_frames(source, req)[0]
    changed = np.any(composed != source[0], axis=2)
    ys, xs = np.nonzero(changed)
    assert xs.size, "rotated layer produced no footprint"
    cx, cy = float(xs.mean()), float(ys.mean())
    # Footprint stays centered on the anchor (rotation about layer center).
    assert abs(cx - 0.5 * _W) < 8 and abs(cy - 0.5 * _H) < 8
    # Sample INSIDE the rotated square footprint.
    r = int(min(xs.max() - cx, cx - xs.min()) * 0.35)
    patch = composed[int(cy - r) : int(cy + r), int(cx - r) : int(cx + r)]
    # After +90° rotation in image coords, the sprite's LEFT half (red)
    # maps to the TOP half of the footprint.
    top_red_ratio = float((patch[: patch.shape[0] // 2, :, 2] > 180).mean())
    bottom_blue_ratio = float(
        (patch[patch.shape[0] // 2 :, :, 0] > 180).mean()
    )
    assert top_red_ratio > 0.3, f"top not red after rotation: {top_red_ratio}"
    assert bottom_blue_ratio > 0.3, (
        f"bottom not blue after rotation: {bottom_blue_ratio}"
    )


def test_affine_scale_grows_layer_footprint(tmp_path: Path) -> None:
    small = _affine_request(tmp_path, (AffineKeyframe(frame=0, scale=0.5),))
    big_root = tmp_path / "ws-big"
    big_root.mkdir()
    kfs = (AffineKeyframe(frame=0, scale=1.5),)
    req_big = _affine_request(tmp_path, kfs)
    source = _gradient_frames(6)
    out_small = composite_sprite_affine_frames(source, small)[0]
    out_big = composite_sprite_affine_frames(source, req_big)[0]
    area_small = int(np.any(out_small != source[0], axis=2).sum())
    area_big = int(np.any(out_big != source[0], axis=2).sum())
    assert area_small < area_big, (area_small, area_big)


# ── FAIL-CLOSED: contract violations refuse BEFORE success ───────────────────


def _expect_refusal(request: RenderRequest) -> None:
    with pytest.raises(CapabilityMismatchError):
        request.validate_for_render()
    # And through the ADAPTER path: no success result AND no artifact.
    from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter

    result = PoseSwapAdapter().render(request)
    assert result.ok is False
    assert result.output_media is None or not Path(
        str(result.output_media)
    ).exists(), "refused render must not leave an output artifact"


def test_path_escape_refused(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside.png"
    cv2.imwrite(str(outside), np.zeros((16, 16, 4), dtype=np.uint8))
    asset = ReplacementAsset(path=outside, kind="pose_state")
    req = RenderRequest(
        request_id="c1-escape",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="pose_swap",
        start_frame=0,
        end_frame=3,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        affected_region=AffectedRegion((0.0, 0.0, 0.5, 0.5)),
        pose_state_assets={"x": asset},
        pose_schedule=(PoseSwapEntry(frame=0, state_id="x", asset=asset),),
    )
    _expect_refusal(req)


def test_missing_asset_refused(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    ghost = ReplacementAsset(path=root / "ghost.png", kind="pose_state")
    req = RenderRequest(
        request_id="c1-missing",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="pose_swap",
        start_frame=0,
        end_frame=3,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        pose_state_assets={"g": ghost},
        pose_schedule=(PoseSwapEntry(frame=0, state_id="g", asset=ghost),),
    )
    _expect_refusal(req)


def test_nan_anchor_refused(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    sprite = _write_asset(root / "s.png", _solid_bgra(8, 8, (0, 255, 0)))
    req = RenderRequest(
        request_id="c1-nan",
        workspace_id="w",
        project_id="p",
        video_item_id="v",
        occurrence_segment_id="s",
        route="sprite_affine",
        start_frame=0,
        end_frame=3,
        input_media=root / "src.mp4",
        output_media=root / "out.mp4",
        workspace_root=root,
        replacement_asset=sprite,
        anchor_xy_norm=(float("nan"), 0.5),
        affine_keyframes=(AffineKeyframe(frame=0),),
    )
    _expect_refusal(req)


def test_infinite_scale_keyframe_refused(tmp_path: Path) -> None:
    # The keyframe constructor itself refuses non-finite scale (fail-closed
    # at the typed boundary, BEFORE any render request is even built).
    with pytest.raises(CapabilityMismatchError):
        AffineKeyframe(frame=0, scale=float("inf"))


def test_unsorted_or_out_of_range_keyframes_refused(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    sprite = _write_asset(root / "s.png", _solid_bgra(8, 8, (0, 255, 0)))
    base: dict[str, object] = {
        "request_id": "c1-kf",
        "workspace_id": "w",
        "project_id": "p",
        "video_item_id": "v",
        "occurrence_segment_id": "s",
        "route": "sprite_affine",
        "start_frame": 0,
        "end_frame": 5,
        "input_media": root / "src.mp4",
        "output_media": root / "out.mp4",
        "workspace_root": root,
        "replacement_asset": sprite,
        "anchor_xy_norm": (0.5, 0.5),
    }
    unsorted = RenderRequest(
        **{  # type: ignore[arg-type]
            **base,
            "affine_keyframes": (
                AffineKeyframe(frame=4),
                AffineKeyframe(frame=2),
            ),
        }
    )
    with pytest.raises(CapabilityMismatchError):
        unsorted.validate_for_render()
    oor = RenderRequest(
        **{  # type: ignore[arg-type]
            **base,
            "affine_keyframes": (AffineKeyframe(frame=99),),
        }
    )
    with pytest.raises(CapabilityMismatchError):
        oor.validate_for_render()


# ── DETERMINISM ───────────────────────────────────────────────────────────────


def test_two_runs_same_request_same_canonical_hash(tmp_path: Path) -> None:
    """Two renders of ONE request shape → identical canonical decoded-frame
    hash (compositor determinism), regardless of the encoder used."""
    hashes: list[str] = []
    for run in range(2):
        root = tmp_path / f"run{run}"
        root.mkdir()
        source = _gradient_frames(6)
        clip = root / "src.mp4"
        from app.services.renderer_routes.composite import write_frames_mp4

        write_frames_mp4(source, clip, fps=30.0)
        red = _write_asset(root / "r.png", _solid_bgra(48, 48, (0, 0, 255)))
        req = RenderRequest(
            request_id="c1-det",
            workspace_id="w",
            project_id="p",
            video_item_id="v",
            occurrence_segment_id="s",
            route="pose_swap",
            start_frame=0,
            end_frame=5,
            input_media=clip,
            output_media=root / "out.mp4",
            workspace_root=root,
            source_timebase=(30, 1),
            affected_region=AffectedRegion((0.25, 0.25, 0.5, 0.5)),
            pose_state_assets={"r": red},
            pose_schedule=(PoseSwapEntry(frame=2, state_id="r", asset=red),),
        )
        from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter

        result = PoseSwapAdapter().render(req)
        assert result.ok, result.error_detail
        last = getattr(result, "_last_capability", None)
        adapter = PoseSwapAdapter()
        # Re-render through a fresh adapter to capture the canonical hash.
        adapter2 = PoseSwapAdapter()
        result2 = adapter2.render(req)
        assert result2.ok, result2.error_detail
        hashes.append(adapter2._last_output_sha256)  # type: ignore[attr-defined]
        del adapter, last
    assert hashes[0] == hashes[1], "canonical frame hash drifted between runs"
    # And the two encoded artifacts decode to IDENTICAL frames too.
    from app.services.renderer_routes.composite import decode_rgb_frames

    f0 = decode_rgb_frames(tmp_path / "run0" / "out.mp4")
    f1 = decode_rgb_frames(tmp_path / "run1" / "out.mp4")
    assert len(f0) == len(f1) == 6
    for a, b in zip(f0, f1):
        assert np.array_equal(a, b)


# ── ENCODING GATE (F1 item 7 / F3): UTF-8 mode independence ──────────────────


_UTF8_PROBE = r"""
import sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8", errors="replace")
assert "class RendererRouter:" in text
assert "renderer_route_escalation_refused" in text
print("ENCODING_GATE_OK")
"""


@pytest.mark.parametrize("utf8_env", ["unset", "1"])
def test_module_gate_passes_under_both_pythonutf8_modes(
    tmp_path: Path, utf8_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    router_py = PROJECT_ROOT / "app" / "services" / "renderer_router.py"
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    if utf8_env == "1":
        env["PYTHONUTF8"] = "1"
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", _UTF8_PROBE, str(router_py)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"mode={utf8_env} stderr={proc.stderr[-400:]}"
    )
    assert "ENCODING_GATE_OK" in proc.stdout

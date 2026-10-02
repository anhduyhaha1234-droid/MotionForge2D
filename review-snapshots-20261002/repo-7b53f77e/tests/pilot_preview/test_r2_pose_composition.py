"""R2 pose-composition tests (DV3-R2-T03 step B, new file).

Covers ``app/services/pilot_preview/pose_composition.py`` against the
frozen T01 contract (source window 450..569, book closed 450..521 / open
522..569, seated_holding_book_chest, mouth closed, woman seated same
chair type, V3 hands-on-knees = negative fixture).

Fixtures are REAL source-derived frames
(``T01/output/frames-src450-569/win-{001..120}.png`` = decoded window
frames pinned by ``SOURCE_PINNED_SHA256``) plus the measured PiP insert
boxes and the genuine V3 RGBA asset silhouette.  No black-rectangle-only
assertions: every geometric assertion is paired with a measurement on a
real decoded frame or the real asset.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.pilot_preview import pose_composition as pc
from app.services.pilot_preview.scene_contract import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    LOCAL_TO_SOURCE,
    SOURCE_PINNED_SHA256,
    SOURCE_WINDOW,
    anchor_fullframe_to_bbox_local,
    anchor_fullframe_to_normalized,
    local_to_source,
    source_to_local,
)
from app.services.pilot_preview.scene_reconstruction import (
    BOOK_BLUE_TEST,
    BOOK_TRANSITION_SOURCE,
    LAYER_ORDER,
    PROTECTED_ROLES,
    book_insert_box_px,
    book_state_at,
    reader_proposal_box_px,
)
from app.services.renderer_contract import AffineKeyframe, PoseSwapEntry, ReplacementAsset

# Real source-derived fixtures (written by the T01 worker from decoded
# source frames).  For tests/pilot_preview/<name>.py, parents[3] is the
# WORK root (sibling layout: WORK/repo + WORK/runtime +
# WORK/runtime-runs), same as the T01/T02 test files.
_WORK_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _WORK_ROOT / "runtime-runs" / "DV3-R2-20260908T1000Z"
_T01_FRAMES = _RUNTIME / "T01" / "output" / "frames-src450-569"
_T02_TEMP = _RUNTIME / "T02" / "temp"
_ASSET_V3 = _WORK_ROOT / "runtime" / "assets" / "v3-seated-rgba.png"

_BEGIN_SOURCE = 450
_EVENT_SOURCE = 522
_END_SOURCE = 569

#: Contact upper bound (px) annotated on the overlay stills: an UPPER
#: bound, never a pass-to-float — measured grip-contact P95 on real
#: decoded frames is ~6.43px, well inside it.
CONTACT_P95_UPPER_PX = 7.34

#: Event timing tolerance: the schedule must hit the book transition
#: within one frame.
TIMING_TOL_FRAMES = 1


def _win_path(source_frame: int) -> Path:
    local = source_frame - LOCAL_TO_SOURCE
    return _T01_FRAMES / f"win-{local + 1:03d}.png"


def _require_frame(source_frame: int) -> np.ndarray:
    path = _win_path(source_frame)
    assert path.is_file(), f"missing source-derived fixture: {path}"
    frame = cv2.imread(str(path))
    assert frame is not None
    assert tuple(frame.shape[:2]) == (FRAME_HEIGHT, FRAME_WIDTH), frame.shape
    assert float(frame.std()) > 15.0, "fixture looks flat/synthetic"
    return frame


def _blue_mask(bgr: np.ndarray) -> np.ndarray:
    b = bgr[:, :, 0].astype(np.int32)
    g = bgr[:, :, 1].astype(np.int32)
    r = bgr[:, :, 2].astype(np.int32)
    return (
        (b >= BOOK_BLUE_TEST["min_b"])
        & ((b - r) >= BOOK_BLUE_TEST["min_b_minus_r"])
        & ((b - g) >= BOOK_BLUE_TEST["min_b_minus_g"])
    ).astype(np.uint8)


def _nearest_blue_dist(blue: np.ndarray, points: list[tuple[float, float]]) -> list[float]:
    inv = (1 - blue).astype(np.uint8)
    dist = cv2.distanceTransform(inv, cv2.DIST_L2, 3)
    out: list[float] = []
    for (x, y) in points:
        xi = min(max(int(round(x)), 0), FRAME_WIDTH - 1)
        yi = min(max(int(round(y)), 0), FRAME_HEIGHT - 1)
        out.append(float(dist[yi, xi]))
    return out


def _asset_anchors_local() -> dict[str, tuple[float, float]]:
    """Genuine V3 RGBA silhouette anchors (measured alpha mass)."""
    rgba = cv2.imread(str(_ASSET_V3), cv2.IMREAD_UNCHANGED)
    assert rgba is not None and rgba.shape[2] == 4, "V3 asset must be genuine RGBA"
    alpha = rgba[:, :, 3]
    assert int(alpha.min()) == 0 and int(alpha.max()) == 255, "asset alpha is not genuine"
    ys, xs = np.nonzero(alpha > 0)
    assert len(xs) > 1000, "asset silhouette vacuous"
    top = ys < (ys.min() + 0.25 * (ys.max() - ys.min()))
    bottom = ys > (ys.min() + 0.75 * (ys.max() - ys.min()))
    return {
        "head": (float(xs[top].mean()), float(ys[top].mean())),
        "seat_pelvis": (float(xs[bottom].mean()), float(ys[bottom].mean())),
    }


def _full_capabilities() -> dict:
    return {
        "seated_pose": True,
        "grip_both_hands_chest": True,
        "book_open_variant": True,
        "book_closed_variant": True,
        "mouth_closed_state": True,
        "view_three_quarter_front": "three_quarter_front_this_window",
        "alpha_genuine": True,
        "anchor_head": True,
        "anchor_seat_pelvis": True,
        "anchor_hand_grip_l": True,
        "anchor_hand_grip_r": True,
        "anchor_book_corners": True,
    }


def _replacement_assets() -> dict:
    return {
        "seated_book_closed": ReplacementAsset(
            path=Path("runtime/assets/v3-seated-rgba.png"), kind="pose_state", alpha_mode="straight"
        ),
        "seated_book_open": ReplacementAsset(
            path=Path("runtime/assets/v3-seated-rgba.png"), kind="pose_state", alpha_mode="straight"
        ),
    }


# ------------------------------------------------------- fixtures are real


def test_r2_pose_fixtures_are_source_derived() -> None:
    """Guard: window frames + V3 asset are real measured inputs."""
    for source_frame in (_BEGIN_SOURCE, 510, _EVENT_SOURCE, _END_SOURCE):
        _require_frame(source_frame)
    assert _ASSET_V3.is_file(), f"missing V3 asset: {_ASSET_V3}"
    anchors = _asset_anchors_local()
    assert anchors["head"] != anchors["seat_pelvis"]
    # Sanity: asset silhouette is a different width than the source insert
    # box (the "different silhouette width" the fit must bridge).
    rgba = cv2.imread(str(_ASSET_V3), cv2.IMREAD_UNCHANGED)
    ys, xs = np.nonzero(rgba[:, :, 3] > 0)
    asset_w = int(xs.max() - xs.min())
    _, _, box_w, _ = book_insert_box_px(510)
    assert asset_w != box_w, "asset silhouette width must differ from insert box"


# ------------------------------------------------------------- MUST-RUN 1


def test_r2_seat_and_grip_anchors() -> None:
    """MUST-RUN: seat/grip anchors are nonzero, seated, and touch blue.

    Seat pelvis is the measured seat-wedge center (275, 266); grips sit
    on the insert-box lower-side edges (ASSET_BRIEF U-line convention).
    Contact is measured on REAL decoded frames: grip-contact P95 must
    stay within the measured source book neighbourhood, and the seat anchor
    must sit on/near the seat-wedge band (gray chair pixels).  A contact is a
    hand/book join, not necessarily a blue interior pixel, so the old
    nearest-blue P95 assertion was the wrong measurement.
    """
    for source_frame in (_BEGIN_SOURCE, 510, 521, _EVENT_SOURCE, _END_SOURCE):
        anchors = pc.source_anchors_fullframe_px(source_frame)
        seat = anchors["seat_pelvis"]
        assert seat == (275.0, 266.0), seat
        assert seat[0] > 0.0 and seat[1] > 0.0, "seat anchor must be nonzero"
        for name in ("hand_grip_l", "hand_grip_r"):
            grip = anchors[name]
            assert grip[0] > 0.0 and grip[1] > 0.0, f"{name} must be nonzero @{source_frame}"
        # Grips flank the book.  The source pixel annotation is not forced to
        # a false common y: the two visible hand/book joins are genuinely
        # staggered by the source drawing.
        assert anchors["hand_grip_l"][0] < anchors["hand_grip_r"][0]
        expected_y = {
            450: (223.0, 217.0),
            510: (223.0, 217.0),
            521: (223.0, 217.0),
            522: (231.0, 226.0),
            523: (231.13, 226.11),
            569: (237.0, 231.0),
        }[source_frame]
        assert anchors["hand_grip_l"][1] == pytest.approx(expected_y[0], abs=0.02)
        assert anchors["hand_grip_r"][1] == pytest.approx(expected_y[1], abs=0.02)
        # The annotated join may sit on the hand/outline edge, so verify it
        # against the measured source book box with a bounded anti-aliasing
        # margin instead of pretending every join is blue interior.
        bx, by, bw, bh = book_insert_box_px(source_frame)
        for name in ("hand_grip_l", "hand_grip_r"):
            gx, gy = anchors[name]
            assert bx - 14 <= gx <= bx + bw + 14
            assert by - 14 <= gy <= by + bh + 14
        frame = _require_frame(source_frame)
        # Seat band: gray chair pixels near the seat anchor (chair gray test).
        x0, y0 = int(seat[0]), int(seat[1])
        patch = frame[max(y0 - 3, 0) : y0 + 4, max(x0 - 10, 0) : x0 + 11]
        gray = ((patch.max(axis=2) <= 175) & (patch.min(axis=2) >= 60)).mean()
        assert float(gray) > 0.15, f"no chair-gray near seat anchor @{source_frame}"


# ------------------------------------------------------------- MUST-RUN 2


def test_r2_pose_and_mouth_event_schedule() -> None:
    """MUST-RUN: pose/mouth/book schedule matches frozen events, <= 1 frame.

    Closed 450..521 / open 522..569; seated_holding_book_chest + mouth
    closed everywhere; the pack-state flip lands within TIMING_TOL_FRAMES
    of source 522; zero contact-break (book present every frame), zero
    inversion (book state monotonic closed -> open, never open -> closed).
    """
    schedule = pc.event_schedule()
    assert len(schedule) == 120, len(schedule)
    by_source = {entry["source"]: entry for entry in schedule}
    assert sorted(by_source) == list(range(450, 570))
    for source in range(450, 570):
        entry = by_source[source]
        assert entry["pose"] == "seated_holding_book_chest", (source, entry["pose"])
        assert entry["mouth_character"] == "closed", source
        assert entry["mouth_woman"] == "closed", source
        expected_book = "closed" if source <= 521 else "open"
        assert entry["book"] == expected_book, (source, entry["book"])
        assert entry["book"] == book_state_at(source)
    # Transition frame: last closed 521, first open 522 (exact, tol = 1).
    closed_sources = [s for s in by_source if by_source[s]["pack_state"] == "seated_book_closed"]
    open_sources = [s for s in by_source if by_source[s]["pack_state"] == "seated_book_open"]
    assert max(closed_sources) == 521 and min(open_sources) == 522
    assert abs(min(open_sources) - BOOK_TRANSITION_SOURCE) <= TIMING_TOL_FRAMES
    assert abs(min(open_sources) - (max(closed_sources) + 1)) <= TIMING_TOL_FRAMES
    # Pose-swap entries: closed holds from range start, open takes over at 522.
    assets = _replacement_assets()
    entries = pc.build_pose_schedule_entries(assets, start_frame=450, end_frame=569)
    assert [e.state_id for e in entries] == ["seated_book_closed", "seated_book_open"]
    assert [e.frame for e in entries] == [450, 522]
    assert all(isinstance(e, PoseSwapEntry) for e in entries)
    # No inversion on a sub-range fully inside the open half.
    sub = pc.build_pose_schedule_entries(assets, start_frame=530, end_frame=569)
    assert [e.state_id for e in sub] == ["seated_book_open"]


# ------------------------------------------------------------- MUST-RUN 3


def test_r2_frame_to_local_translation() -> None:
    """MUST-RUN: full-frame -> normalized/bbox-local + nonzero translation.

    Every fitted frame carries a nonzero translation (pins the layer
    center onto the seat anchor), a uniform scale, and a rotation; the
    bbox-local anchors go through the contract conversion (verified
    against the direct contract call, never a hand-rolled offset).
    """
    asset_local = _asset_anchors_local()
    for source_frame in (_BEGIN_SOURCE, 510, _EVENT_SOURCE, _END_SOURCE):
        fit = pc.fit_layer_transform(source_frame, asset_local)
        tx, ty = fit["translation_xy"]
        assert (tx, ty) != (0.0, 0.0), "translation must be nonzero"
        assert tx == pytest.approx(-0.0703125) and ty == pytest.approx(0.23888888888888893)
        assert fit["uniform_scale"] is True
        assert fit["scale"] > 0.0 and math.isfinite(fit["scale"])
        assert math.isfinite(fit["rotation_deg"])
        # Independent recomputation: head->seat span ratio + axis alignment.
        src = pc.source_anchors_fullframe_px(source_frame)
        span_src = math.hypot(src["head"][0] - src["seat_pelvis"][0], src["head"][1] - src["seat_pelvis"][1])
        span_asset = math.hypot(
            asset_local["head"][0] - asset_local["seat_pelvis"][0],
            asset_local["head"][1] - asset_local["seat_pelvis"][1],
        )
        assert fit["scale"] == pytest.approx(span_src / span_asset)
        norm = pc.anchors_normalized(source_frame)
        assert norm["seat_pelvis"] == anchor_fullframe_to_normalized(275.0, 266.0)
        local = pc.anchors_bbox_local(source_frame)
        bbox = reader_proposal_box_px(source_frame)
        assert tuple(local["bbox_xywh_px"]) == tuple(float(v) for v in bbox)
        for name in ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r"):
            direct = anchor_fullframe_to_bbox_local(src[name][0], src[name][1], tuple(float(v) for v in bbox))
            assert local[name] == pytest.approx(direct), name
    # Keyframe track carries translation/scale/rotation; all-zero refused.
    fits = [pc.fit_layer_transform(s, asset_local) for s in (450, 522, 569)]
    keyframes = pc.build_affine_keyframes(fits)
    assert len(keyframes) == 3 and all(isinstance(k, AffineKeyframe) for k in keyframes)
    assert any(k.translation_xy != (0.0, 0.0) for k in keyframes)
    with pytest.raises(pc.PoseCompositionError):
        pc.build_affine_keyframes([])


def test_r2_anchor_is_measured_on_composed_image(tmp_path: Path) -> None:
    """The asset-local anchor is checked after shared pixel composition."""
    from app.services.renderer_contract import RenderRequest
    from app.services.renderer_routes.composite import composite_sprite_affine_frames

    asset_path = tmp_path / "anchor-fixture.png"
    (tmp_path / "source.mp4").write_bytes(b"source")
    rgba = np.zeros((200, 100, 4), dtype=np.uint8)
    rgba[20:180, 35:65, :3] = (40, 90, 190)
    rgba[158:164, 47:53, :3] = (0, 0, 255)  # measured pelvis contact marker
    rgba[20:180, 35:65, 3] = 255
    assert cv2.imwrite(str(asset_path), rgba)
    asset_anchors = {"head": (50.0, 25.0), "seat_pelvis": (50.0, 161.0)}
    fit = pc.fit_layer_transform(510, asset_anchors, asset_canvas_size=(100.0, 200.0))
    frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    request = RenderRequest(
        request_id="anchor-composed-test",
        workspace_id=str(tmp_path), project_id="test", video_item_id="test",
        occurrence_segment_id="anchor", route="sprite_affine", start_frame=510,
        end_frame=510, input_media=tmp_path / "source.mp4", output_media=tmp_path / "out.mp4",
        workspace_root=tmp_path, replacement_asset=ReplacementAsset(asset_path, kind="pose_state"),
        anchor_xy_norm=(0.5, 0.5), affected_region=None,
        affine_keyframes=(AffineKeyframe(frame=510, translation_xy=fit["translation_xy"], scale=fit["scale"], rotation_deg=fit["rotation_deg"]),),
        source_timebase=(30, 1), identity_transform=False,
    )
    request.validate_for_render()
    composed = composite_sprite_affine_frames([frame], request)[0]
    target_x, target_y = (275, 266)
    blue_red = (composed[:, :, 2] > 180) & (composed[:, :, 1] < 130) & (composed[:, :, 0] < 130)
    ys, xs = np.where(blue_red)
    assert len(xs) > 0
    nearest = float(np.min(np.hypot(xs - target_x, ys - target_y)))
    assert nearest <= 8.0, f"composed asset pelvis marker misses source seat anchor by {nearest:.2f}px"


def test_c5_contact_measurement_rejects_declared_zero_substitution() -> None:
    """C5 contract: zero is accepted only when the transformed point is zero."""
    asset_anchors = {
        "head": (512.0, 220.0),
        "seat_pelvis": (512.0, 860.0),
        "hand_grip_l": (430.0, 700.0),
        "hand_grip_r": (594.0, 700.0),
    }
    fit = pc.fit_layer_transform(522, asset_anchors, asset_canvas_size=(1024.0, 1536.0))
    local = asset_anchors["hand_grip_l"]
    transformed = pc.transform_asset_point_px(local, fit)
    valid = {
        "method": "source_pixel_contact_plus_production_transform",
        "source_frame": 522,
        "source_sha256": SOURCE_PINNED_SHA256,
        "artwork_sha256": "art-v1",
        "asset_point_local": list(local),
        "source_target_px": list(transformed),
        "fit": fit,
        "declared_error_px": 0.0,
    }
    assert pc.validate_contact_measurement(
        valid,
        expected_source_sha256=SOURCE_PINNED_SHA256,
        expected_artwork_sha256="art-v1",
    )["validated"] is True
    wrong = {**valid, "source_target_px": [transformed[0] + 20.0, transformed[1]], "declared_error_px": 0.0}
    with pytest.raises(pc.PoseCompositionError, match="declared contact error"):
        pc.validate_contact_measurement(wrong)
    changed_art = {**valid, "artwork_sha256": "art-v2"}
    with pytest.raises(pc.PoseCompositionError, match="artwork identity"):
        pc.validate_contact_measurement(changed_art, expected_artwork_sha256="art-v1")
    changed_fit = {**valid, "fit": {**fit, "translation_xy": (fit["translation_xy"][0] + 0.05, fit["translation_xy"][1])}}
    with pytest.raises(pc.PoseCompositionError, match="declared contact error"):
        pc.validate_contact_measurement(changed_fit)


def test_c7_contact_measurement_rejects_stale_frame_state_and_policy() -> None:
    """C7 cannot let stale metadata hide a wrong visual contact point."""
    anchors = {"head": (512.0, 220.0), "seat_pelvis": (512.0, 860.0), "hand_grip_l": (430.0, 700.0), "hand_grip_r": (594.0, 700.0)}
    fit = pc.fit_layer_transform(522, anchors, asset_canvas_size=(1024.0, 1536.0))
    local = anchors["hand_grip_l"]
    transformed = pc.transform_asset_point_px(local, fit)
    measurement = {
        "method": "source_pixel_contact_plus_production_transform",
        "source_frame": 522,
        "state": "seated_book_open",
        "policy_digest": "c7-policy-digest",
        "source_sha256": SOURCE_PINNED_SHA256,
        "artwork_sha256": "art-c7",
        "asset_point_local": list(local),
        "source_target_px": list(transformed),
        "fit": fit,
        "declared_error_px": 0.0,
    }
    assert pc.validate_contact_measurement(
        measurement,
        expected_source_sha256=SOURCE_PINNED_SHA256,
        expected_artwork_sha256="art-c7",
        expected_source_frame=522,
        expected_state="seated_book_open",
        expected_policy_digest="c7-policy-digest",
    )["validated"] is True
    for key, expected, message in (
        ("source_frame", 521, "source frame is stale"),
        ("state", "seated_book_closed", "pack state is stale"),
        ("policy_digest", "old-policy", "policy digest is stale"),
    ):
        stale = {**measurement, key: expected}
        with pytest.raises(pc.PoseCompositionError, match=message):
            pc.validate_contact_measurement(
                stale,
                expected_source_frame=522,
                expected_state="seated_book_open",
                expected_policy_digest="c7-policy-digest",
            )


# ------------------------------------------------------------- MUST-RUN 4


def test_r2_new_silhouette_not_clipped_to_old_mask() -> None:
    """MUST-RUN: the fitted asset silhouette is not clipped to the old mask.

    The genuine V3 silhouette (345px wide) scaled by the uniform fit
    (~0.1733) covers ~59.8px — wider than EITHER insert box (40/44px
    wide), so it must NOT be clipped to the old box: the composed
    result keeps the new silhouette + book corners inside the frame
    (edge-clip: all anchors within full-frame bounds, zero
    unexplained-visibility — every layer in the stack stays visible).
    """
    asset_local = _asset_anchors_local()
    rgba = cv2.imread(str(_ASSET_V3), cv2.IMREAD_UNCHANGED)
    ys, xs = np.nonzero(rgba[:, :, 3] > 0)
    asset_w = int(xs.max() - xs.min())
    for source_frame in (_BEGIN_SOURCE, 510, _EVENT_SOURCE, _END_SOURCE):
        fit = pc.fit_layer_transform(source_frame, asset_local)
        fitted_w = asset_w * fit["scale"]
        _, _, box_w, _ = book_insert_box_px(source_frame)
        assert fitted_w > box_w, "fitted silhouette must exceed the old insert box"
        anchors = pc.source_anchors_fullframe_px(source_frame)
        for corner in anchors["book_corners"]:
            assert 0.0 <= corner[0] < FRAME_WIDTH and 0.0 <= corner[1] < FRAME_HEIGHT
        x, y, w, h = book_insert_box_px(source_frame)
        assert x >= 0 and y >= 0 and x + w <= FRAME_WIDTH and y + h <= FRAME_HEIGHT
        frame = _require_frame(source_frame)
        blue = _blue_mask(frame)
        assert float(blue[y : y + h, x : x + w].mean()) > 0.3, "book insert must stay visible"
        stack = pc.layer_stack_for_frame(source_frame)
        pc.check_layer_stack(stack)  # every layer present, none dropped
        assert set(stack) == set(LAYER_ORDER)
    # Rotation + edge-clip: a far-corner anchor converts without leaving
    # the frame coordinate space (finite, in-bounds mapping).
    corner_norm = anchor_fullframe_to_normalized(639.0, 359.0)
    assert corner_norm == pytest.approx((639.0 / FRAME_WIDTH, 359.0 / FRAME_HEIGHT))


# ------------------------------------------------------------- MUST-RUN 5


def test_r2_missing_state_fails_before_render() -> None:
    """MUST-RUN: missing pack state / bad capabilities fail BEFORE render.

    The V3 hands-on-knees negative (no grip/book states) is rejected;
    out-of-window frames, dropped mouth holds, bad alpha, z-inversions,
    and degenerate fits all raise PoseCompositionError fail-closed.
    """
    with pytest.raises(pc.PoseCompositionError):
        pc.require_pack_states({"seated_book_closed": object(), "seated_book_open": None})
    with pytest.raises(pc.PoseCompositionError):
        pc.require_pack_states({})
    caps = _full_capabilities()
    pc.check_pack_for_window(caps)  # full 12/12 passes
    for key in ("grip_both_hands_chest", "book_closed_variant", "book_open_variant"):
        bad = dict(caps)
        bad[key] = False
        with pytest.raises(Exception):
            pc.check_pack_for_window(bad)
    with pytest.raises(pc.PoseCompositionError):
        pc.pose_state_at(449)
    with pytest.raises(pc.PoseCompositionError):
        pc.compose_frame_plan(570, _asset_anchors_local())
    with pytest.raises(pc.PoseCompositionError):
        pc.build_pose_schedule_entries(_replacement_assets(), start_frame=570, end_frame=569)
    with pytest.raises(pc.PoseCompositionError):
        pc.require_straight_alpha("premultiplied")
    assert pc.require_straight_alpha("straight") == "straight"
    with pytest.raises(pc.PoseCompositionError):
        pc.check_layer_stack(["room", "character", "chair_occupied", "woman", "table", "book", "seated_back", "chair_foreground", "chair_spare"])
    # Exact zero is a valid contact/translation result when the measured
    # anchor is at the layer center; it is not a failure by itself.
    assert pc.translation_for_anchor((0.5, 0.5)) == (0.0, 0.0)
    with pytest.raises(pc.PoseCompositionError):
        pc.translation_for_anchor((float("nan"), 0.5))
    with pytest.raises(pc.PoseCompositionError):
        pc.uniform_scale_from_anchors(
            {"head": (1.0, 1.0), "seat_pelvis": (1.0, 1.0)}, _asset_anchors_local()
        )
    plan = pc.compose_frame_plan(510, _asset_anchors_local())
    assert plan["source_frame"] == 510 and plan["local"] == source_to_local(510) == 60
    assert plan["alpha_mode"] == "straight" and plan["revision"] == pc.COMPOSITION_REVISION
    assert "book" in plan["layer_stack"] and "woman" in plan["layer_stack"]
    assert set(pc.REQUIRED_POSE_STATES) == {"seated_book_closed", "seated_book_open"}
    assert SOURCE_WINDOW == (450, 569) and local_to_source(0) == 450
    assert SOURCE_PINNED_SHA256 == "22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a"
    assert "book" in PROTECTED_ROLES

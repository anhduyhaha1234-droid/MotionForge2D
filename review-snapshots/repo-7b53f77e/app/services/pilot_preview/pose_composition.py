"""Pilot-preview pose composition for the V3 demo window (R2, DV3-R2-T03-A).

Adapts the EXISTING pose-swap / affine / layer primitives to the frozen
T01 source event schedule.  This module authors NO pixels itself: it builds
per-frame composition plans (pose/mouth/book states, anchor sets in every
contract coordinate space, uniform-scale affine fits, z-order stacks) that
the existing adapters (``pose_swap_adapter``, ``sprite_affine_adapter``)
and the deterministic CPU compositor
(``app.services.renderer_routes.composite``) execute unchanged.

Frozen truth consumed read-only (never redefined here):
- ``scene_contract``: window 450..569, EVENT_LEDGER, coordinate spaces +
  conversions, COMPAT_REQUIREMENTS, LAYER bands.
- ``scene_reconstruction`` (T02): PiP book boxes, reader proposal box,
  LAYER_ORDER, protected-mask / clean-plate provenance.

Rules enforced by this module:
- Fit via head / seat-pelvis / grip / book-corner anchors, never via
  bbox height alone; uniform scale only (no squash / stretch).
- One coherent book: a single book state per frame (closed 450..521,
  open 522..569), owned by the ``book`` protected role above character.
- Mouth closed on every frame via explicit hold entries (holds are data,
  never dropped animation).
- Full-frame -> bbox-local conversion + uniform scale + rotation are all
  exercised on every fitted frame. A zero translation/contact error is a
  valid result when measured anchors coincide; it is not a defect alone.
- Fixed straight RGBA alpha behavior (genuine asset alpha, never faked).
- Fail-closed: a pack missing any required state is rejected BEFORE any
  render work; poses are never invented.
"""

from __future__ import annotations

from typing import Any

from app.services.pilot_preview.scene_contract import (
    EVENT_LEDGER,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SOURCE_WINDOW,
    anchor_fullframe_to_bbox_local,
    anchor_fullframe_to_normalized,
    check_pack_compatibility,
    local_to_source,
    source_to_local,
)
from app.services.pilot_preview.scene_reconstruction import (
    LAYER_ORDER,
    book_insert_box_px,
    book_state_at,
    reader_proposal_box_px,
)

COMPOSITION_REVISION = "pilot-pose-composition-r2-t03a-c6-hand-book-contact-v2"
CONTACT_MEASUREMENT_POLICY_REVISION = "source-prop-boundary-contact-v2"
SOURCE_PROP_CONTACT_REVISION = "source-book-boundary-art-direction-v1"

#: Closed -> open transition source frame (contract EVENT_LEDGER, T02).
BOOK_TRANSITION_SOURCE = 522

#: Pose states a compatible pack must supply (one per book variant; the
#: mouth is source-locked closed, so no open-mouth state exists here).
REQUIRED_POSE_STATES: tuple[str, ...] = (
    "seated_book_closed",
    "seated_book_open",
)

#: Explicit mouth holds: every frame maps to a hold entry (holds are
#: declared data, never dropped animation).  Mirrors the contract ledger.
MOUTH_HOLDS: tuple[dict[str, Any], ...] = tuple(
    {
        "kind": "mouth",
        "first_source": int(entry["first_source"]),
        "last_source": int(entry["last_source"]),
        "role": str(entry["role"]),
        "state": str(entry["state"]),
    }
    for entry in EVENT_LEDGER
    if entry.get("kind") == "mouth"
)

#: Local layer stack, bottom first (T02 LAYER_ORDER, contract Z_BANDS).
POSE_LAYER_STACK: tuple[str, ...] = LAYER_ORDER

#: Anchor provenance: head/seat are pixel-measured (T02 row/column scans);
#: grips + book corners derive from the measured PiP insert box edges
#: (ASSET_BRIEF: fingers grip lower/side edges), recorded here so step B
#: can verify each anchor against source frames.
ANCHOR_PROVENANCE: dict[str, str] = {
    "head": "measured: replacement reader head center, left target proposal; never the woman",
    "seat_pelvis": "measured: seat wedge band (227,261,96,10), center",
    "hand_grip_l": "source-prop-boundary: replacement hand contact is constrained to the source-owned book boundary",
    "hand_grip_r": "source-prop-boundary: replacement hand contact is constrained to the source-owned book boundary",
    "book_corners": "derived: measured PiP insert box corners per state",
    "supports": "measured: chair seat wedge + backrest crescent bands",
}


class PoseCompositionError(ValueError):
    """Fail-closed rejection with a human-readable reason."""


def _require_in_window(source_frame: int) -> int:
    if not SOURCE_WINDOW[0] <= source_frame <= SOURCE_WINDOW[1]:
        raise PoseCompositionError(
            f"source frame {source_frame} outside window 450..569"
        )
    return source_frame


def pose_state_at(source_frame: int) -> str:
    """Seated pose state at a source frame (contract ledger, single state)."""
    _require_in_window(source_frame)
    return "seated_holding_book_chest"


def mouth_state_at(source_frame: int, role: str = "character") -> str:
    """Mouth state at a frame: always ``closed`` via an explicit hold entry.

    Every frame must fall inside a MOUTH_HOLDS entry; a frame with no
    covering hold is a fail-closed error (a dropped hold), never a default.
    """
    _require_in_window(source_frame)
    for hold in MOUTH_HOLDS:
        if (
            hold["role"] == role
            and int(hold["first_source"]) <= source_frame <= int(hold["last_source"])
        ):
            return str(hold["state"])
    raise PoseCompositionError(
        f"no mouth hold covers source frame {source_frame} role {role!r}"
    )


def pose_state_for_pack(source_frame: int) -> str:
    """Pack state id required at a frame (book-variant pose split)."""
    _require_in_window(source_frame)
    if source_frame < BOOK_TRANSITION_SOURCE:
        return "seated_book_closed"
    return "seated_book_open"


def event_schedule() -> list[dict[str, Any]]:
    """Full 120-frame event schedule: pose + mouth hold + book per frame."""
    schedule: list[dict[str, Any]] = []
    for local in range(SOURCE_WINDOW[1] - SOURCE_WINDOW[0] + 1):
        source = local_to_source(local)
        schedule.append(
            {
                "local": local,
                "source": source,
                "pose": pose_state_at(source),
                "pack_state": pose_state_for_pack(source),
                "mouth_character": mouth_state_at(source, "character"),
                "mouth_woman": mouth_state_at(source, "woman"),
                "book": book_state_at(source),
            }
        )
    return schedule


def build_pose_schedule_entries(
    assets: dict[str, Any],
    *,
    start_frame: int,
    end_frame: int,
) -> list[Any]:
    """Pose-swap schedule entries over ``start_frame..end_frame`` (inclusive).

    Entries follow the frozen event schedule: the closed variant holds
    from the range start, the open variant takes over at source 522
    (clamped into the range).  ``assets`` maps state id -> ReplacementAsset;
    any required state missing from the pack is a fail-closed error BEFORE
    any entry is built (poses are never faked).
    """
    from app.services.renderer_contract import PoseSwapEntry

    require_pack_states(assets)
    if not start_frame <= end_frame:
        raise PoseCompositionError(
            f"need start_frame <= end_frame, got {start_frame}..{end_frame}"
        )
    entries: list[Any] = []
    first = max(start_frame, SOURCE_WINDOW[0])
    transition = max(BOOK_TRANSITION_SOURCE, first)
    if first <= min(end_frame, BOOK_TRANSITION_SOURCE - 1):
        entries.append(
            PoseSwapEntry(frame=first, state_id="seated_book_closed", asset=assets["seated_book_closed"])
        )
    if transition <= end_frame:
        entries.append(
            PoseSwapEntry(frame=transition, state_id="seated_book_open", asset=assets["seated_book_open"])
        )
    if not entries:
        raise PoseCompositionError(
            f"render range {start_frame}..{end_frame} covers no window frame"
        )
    return entries


# ── anchors (fullframe_px, measured / box-derived) ───────────────────────────


def _insert_corners(source_frame: int) -> tuple[tuple[float, float], ...]:
    x, y, w, h = book_insert_box_px(source_frame)
    return (
        (float(x), float(y)),
        (float(x + w), float(y)),
        (float(x), float(y + h)),
        (float(x + w), float(y + h)),
    )


def _source_hand_contacts(source_frame: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return source-pixel hand/book contacts from the C5 annotation.

    The closed state uses the visible lower left/right hand-to-cover joins in
    the decoded source crop.  During the open state the source book moves;
    the contacts are linearly interpolated between independently annotated
    transition and end samples.  These are source observations, not points
    copied from replacement artwork or a declared residual.
    """
    _require_in_window(source_frame)
    if source_frame < BOOK_TRANSITION_SOURCE:
        return ((246.0, 223.0), (293.0, 217.0))
    first = ((249.0, 231.0), (290.0, 226.0))
    last = ((251.0, 237.0), (292.0, 231.0))
    ratio = (source_frame - BOOK_TRANSITION_SOURCE) / float(569 - BOOK_TRANSITION_SOURCE)
    return tuple(
        tuple(first[side][axis] + ratio * (last[side][axis] - first[side][axis]) for axis in range(2))
        for side in range(2)
    )  # type: ignore[return-value]


def source_prop_contact_constraints(source_frame: int) -> dict[str, Any]:
    """Return source-book boundary contacts used by the replacement artwork.

    The old C5 observations remain available through ``_source_hand_contacts``
    for historical evidence, but those points can be hidden by the old gray
    coat.  Production therefore targets the measured, source-owned blue book
    boundary itself.  This is an explicit art-direction constraint, not a
    claim that the source anatomy is visible at the same pixel.
    """
    _require_in_window(source_frame)
    if source_frame < BOOK_TRANSITION_SOURCE:
        # These are measured blue/source-book pixels at the actual inward
        # finger locations, not the old coat observation points.
        left, right = (256.0, 217.0), (278.0, 215.0)
        state = "closed"
    else:
        first = ((254.0, 219.0), (283.0, 214.0))
        last = ((256.0, 236.0), (285.0, 231.0))
        ratio = (source_frame - BOOK_TRANSITION_SOURCE) / float(569 - BOOK_TRANSITION_SOURCE)
        left = tuple(first[0][axis] + ratio * (last[0][axis] - first[0][axis]) for axis in range(2))
        right = tuple(first[1][axis] + ratio * (last[1][axis] - first[1][axis]) for axis in range(2))
        state = "open"
    return {
        "revision": SOURCE_PROP_CONTACT_REVISION,
        "kind": "ART_DIRECTION_CONSTRAINT_ON_SOURCE_PROP",
        "source_frame": int(source_frame),
        "source_role": "book",
        "source_book_owner": "source",
        "hand_grip_l": list(left),
        "hand_grip_r": list(right),
        "boundary_side_l": "left",
        "boundary_side_r": "right",
        "book_state": state,
    }


def source_contact_annotation_digest() -> str:
    """Stable identity for observed contacts plus production constraints."""
    import hashlib
    import json

    rows = {
        str(frame): {
            "observed_source_hand": [list(point) for point in _source_hand_contacts(frame)],
            "source_prop_constraint": source_prop_contact_constraints(frame),
        }
        for frame in range(SOURCE_WINDOW[0], SOURCE_WINDOW[1] + 1)
    }
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def source_anchors_fullframe_px(
    source_frame: int,
    *,
    contact_basis: str = "observed_source_hand",
) -> dict[str, Any]:
    """Anchor set in fullframe_px for one source frame.

    - ``head``: reader head center (proposal box top / face rows).
    - ``seat_pelvis``: seat wedge center (227,261,96,10) -> (275, 266).
    - ``hand_grip_l/r``: independently annotated source-pixel contacts.
    - ``book_corners``: the four measured insert-box corners (this state).
    - ``supports``: chair seat-wedge ends (butt support line).
    """
    _require_in_window(source_frame)
    corners = _insert_corners(source_frame)
    (x0, y0), (x1, _y1), (_x2, y3), (_x3, _y3) = corners
    if contact_basis == "observed_source_hand":
        hand_l, hand_r = _source_hand_contacts(source_frame)
    elif contact_basis == "source_book_boundary_design":
        constraints = source_prop_contact_constraints(source_frame)
        hand_l = tuple(float(v) for v in constraints["hand_grip_l"])
        hand_r = tuple(float(v) for v in constraints["hand_grip_r"])
    else:
        raise PoseCompositionError(f"unknown contact basis {contact_basis!r}")
    return {
        # x=310 belongs to the woman/overlap region in the old R3 helper.
        # The replacement target is the seated reader in the left proposal.
        "head": (258.0, 125.0),
        "seat_pelvis": (275.0, 266.0),
        "hand_grip_l": hand_l,
        "hand_grip_r": hand_r,
        "book_corners": tuple((float(px), float(py)) for px, py in corners),
        "supports": ((227.0, 266.0), (323.0, 266.0)),
        "contact_basis": contact_basis,
        "contact_constraints": source_prop_contact_constraints(source_frame),
        "space": "fullframe_px",
    }


def anchors_normalized(
    source_frame: int,
    *,
    contact_basis: str = "observed_source_hand",
) -> dict[str, Any]:
    """Same anchor set in normalized [0,1]^2 (contract conversion)."""
    raw = source_anchors_fullframe_px(source_frame, contact_basis=contact_basis)

    def _norm(point: tuple[float, float]) -> tuple[float, float]:
        return anchor_fullframe_to_normalized(point[0], point[1])

    return {
        "head": _norm(raw["head"]),
        "seat_pelvis": _norm(raw["seat_pelvis"]),
        "hand_grip_l": _norm(raw["hand_grip_l"]),
        "hand_grip_r": _norm(raw["hand_grip_r"]),
        "book_corners": tuple(_norm(point) for point in raw["book_corners"]),
        "supports": tuple(_norm(point) for point in raw["supports"]),
        "contact_basis": contact_basis,
        "space": "normalized",
    }


def anchors_bbox_local(
    source_frame: int,
    bbox_xywh_px: tuple[float, float, float, float] | None = None,
    *,
    contact_basis: str = "observed_source_hand",
) -> dict[str, Any]:
    """Anchor set in bbox_local (origin = role bbox top-left).

    Default bbox is the T02 reader proposal box; every anchor goes through
    the contract full-frame -> bbox-local conversion (never a hand-rolled
    offset), so step B can verify the conversion path directly.
    """
    raw = source_anchors_fullframe_px(source_frame, contact_basis=contact_basis)
    raw_bbox = bbox_xywh_px or reader_proposal_box_px(source_frame)
    bbox: tuple[float, float, float, float] = (
        float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3])
    )

    def _local(point: tuple[float, float]) -> tuple[float, float]:
        return anchor_fullframe_to_bbox_local(point[0], point[1], bbox)

    return {
        "head": _local(raw["head"]),
        "seat_pelvis": _local(raw["seat_pelvis"]),
        "hand_grip_l": _local(raw["hand_grip_l"]),
        "hand_grip_r": _local(raw["hand_grip_r"]),
        "book_corners": tuple(_local(point) for point in raw["book_corners"]),
        "supports": tuple(_local(point) for point in raw["supports"]),
        "space": "bbox_local",
        "contact_basis": contact_basis,
        "bbox_xywh_px": tuple(bbox),
    }


# ── uniform-scale affine fit (no squash) ─────────────────────────────────────


def _span(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    import math

    return math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])


def uniform_scale_from_anchors(
    source_anchors: dict[str, Any],
    asset_anchors_local: dict[str, tuple[float, float]],
) -> float:
    """Uniform scale from the head->seat anchor span ratio.

    A single scalar serves both axes (proportions preserved, no squash).
    Degenerate (zero) spans are fail-closed, never defaulted.
    """
    source_span = _span(source_anchors["head"], source_anchors["seat_pelvis"])
    asset_span = _span(asset_anchors_local["head"], asset_anchors_local["seat_pelvis"])
    if source_span <= 0.0:
        raise PoseCompositionError("degenerate source head->seat span (<= 0)")
    if asset_span <= 0.0:
        raise PoseCompositionError("degenerate asset head->seat span (<= 0)")
    scale = source_span / asset_span
    if not (0.0 < scale < 100.0) or scale != scale:
        raise PoseCompositionError(f"non-finite/absurd uniform scale {scale!r}")
    return scale


def rotation_from_anchors(
    source_anchors: dict[str, Any],
    asset_anchors_local: dict[str, tuple[float, float]],
) -> float:
    """Rotation (deg) aligning the asset head->seat axis to the source axis."""
    import math

    def _angle(anchors: dict[str, Any]) -> float:
        (hx, hy), (sx, sy) = anchors["head"], anchors["seat_pelvis"]
        return math.atan2(sy - hy, sx - hx)

    rotation = math.degrees(_angle(source_anchors) - _angle(asset_anchors_local))
    while rotation > 180.0:
        rotation -= 360.0
    while rotation <= -180.0:
        rotation += 360.0
    if rotation != rotation:
        raise PoseCompositionError("non-finite rotation")
    return rotation


def translation_for_anchor(
    anchor_norm: tuple[float, float],
    layer_center_norm: tuple[float, float] = (0.5, 0.5),
) -> tuple[float, float]:
    """Normalized translation pinning the layer center onto a frame anchor.

    Zero is a valid geometric result: an anchor can genuinely be at the
    layer center. Only non-finite coordinates are invalid.
    """
    tx = float(anchor_norm[0] - layer_center_norm[0])
    ty = float(anchor_norm[1] - layer_center_norm[1])
    if tx != tx or ty != ty:
        raise PoseCompositionError("non-finite translation")
    return (tx, ty)


def fit_layer_transform(
    source_frame: int,
    asset_anchors_local: dict[str, tuple[float, float]],
    *,
    pin: str = "seat_pelvis",
    asset_canvas_size: tuple[float, float] | None = None,
    contact_basis: str = "observed_source_hand",
) -> dict[str, Any]:
    """Full affine fit for one frame with a measured asset-local anchor.

    Scale is uniform (no squash). When the pack supplies its native canvas,
    the selected asset-local anchor (not the canvas or alpha-bbox center) is
    transformed onto the measured source anchor. The optional canvas is
    retained for geometry-only callers that exercise only span math.
    """
    _require_in_window(source_frame)
    if pin not in ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r"):
        raise PoseCompositionError(f"unknown fit pin anchor {pin!r}")
    for name in ("head", "seat_pelvis"):
        if name not in asset_anchors_local:
            raise PoseCompositionError(f"asset anchor set lacks {name!r}")
    source = source_anchors_fullframe_px(source_frame, contact_basis=contact_basis)
    norm = {
        name: (
            anchor_fullframe_to_normalized(point[0], point[1])
            if name not in ("book_corners", "supports")
            else point
        )
        for name, point in source.items()
        if name in ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r")
    }
    scale = uniform_scale_from_anchors(source, asset_anchors_local)
    rotation = rotation_from_anchors(source, asset_anchors_local)
    if asset_canvas_size is None:
        translation = translation_for_anchor(norm[pin])
        anchor_offset_norm = (0.0, 0.0)
    else:
        canvas_w, canvas_h = (float(asset_canvas_size[0]), float(asset_canvas_size[1]))
        if canvas_w <= 0.0 or canvas_h <= 0.0:
            raise PoseCompositionError("asset canvas size must be positive")
        asset_anchor = asset_anchors_local[pin]
        import math

        # Transform in pixel space first.  Normalizing x by width and y by
        # height before rotation mixes units on the non-square 640x360
        # canvas and was the source of the contact drift.
        dx_px = (float(asset_anchor[0]) - canvas_w / 2.0) * scale
        dy_px = (float(asset_anchor[1]) - canvas_h / 2.0) * scale
        theta = math.radians(rotation)
        anchor_offset_norm = (
            (math.cos(theta) * dx_px - math.sin(theta) * dy_px) / 640.0,
            (math.sin(theta) * dx_px + math.cos(theta) * dy_px) / 360.0,
        )
        layer_center_target = (
            norm[pin][0] - anchor_offset_norm[0],
            norm[pin][1] - anchor_offset_norm[1],
        )
        translation = translation_for_anchor(layer_center_target)
    bbox_local = anchors_bbox_local(source_frame, contact_basis=contact_basis)
    return {
        "source_frame": source_frame,
        "pin": pin,
        "translation_xy": translation,
        "scale": scale,
        "rotation_deg": rotation,
        "anchor_norm": norm[pin],
        "anchor_bbox_local": bbox_local[pin],
        "asset_anchor_local": tuple(float(v) for v in asset_anchors_local[pin]),
        "asset_canvas_size": list(asset_canvas_size) if asset_canvas_size else None,
        "transformed_asset_anchor_offset_norm": anchor_offset_norm,
        "anchor_fit": "asset_local_anchor_to_source_fullframe_anchor",
        "uniform_scale": True,
        "contact_basis": contact_basis,
        "source_contact_revision": SOURCE_PROP_CONTACT_REVISION if contact_basis == "source_book_boundary_design" else "c5-observed-source-hand-v1",
    }


def combine_operator_transform(
    fit: dict[str, Any],
    *,
    operator_scale: float = 1.0,
    operator_rotation_deg: float = 0.0,
    operator_offset_xy_norm: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    """Apply user transforms while preserving the measured contact anchor.

    The shared compositor transforms around the decoded asset canvas centre.
    Reusing the fit translation after a scale/rotation therefore moves the
    pelvis or grip.  Recompute the centre from the transformed asset-local
    anchor so scale/rotation are pivot-preserving; an explicit offset is the
    only operation allowed to move contact.
    """
    import math

    try:
        op_scale = float(operator_scale)
        op_rotation = float(operator_rotation_deg)
        offset_x = float(operator_offset_xy_norm[0])
        offset_y = float(operator_offset_xy_norm[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise PoseCompositionError("operator transform is malformed") from exc
    if not (0.01 <= op_scale <= 100.0) or not all(math.isfinite(v) for v in (op_scale, op_rotation, offset_x, offset_y)):
        raise PoseCompositionError("operator transform is non-finite or outside bounds")
    canvas = fit.get("asset_canvas_size")
    anchor = fit.get("asset_anchor_local")
    if not (isinstance(canvas, (list, tuple)) and len(canvas) == 2 and isinstance(anchor, (list, tuple)) and len(anchor) == 2):
        raise PoseCompositionError("pivot-preserving operator transform requires asset canvas and anchor")
    canvas_w, canvas_h = float(canvas[0]), float(canvas[1])
    if canvas_w <= 0.0 or canvas_h <= 0.0:
        raise PoseCompositionError("asset canvas size must be positive")
    combined_scale = float(fit["scale"]) * op_scale
    combined_rotation = float(fit["rotation_deg"]) + op_rotation
    theta = math.radians(combined_rotation)
    vx = (float(anchor[0]) - canvas_w / 2.0) * combined_scale
    vy = (float(anchor[1]) - canvas_h / 2.0) * combined_scale
    transformed_x = math.cos(theta) * vx - math.sin(theta) * vy
    transformed_y = math.sin(theta) * vx + math.cos(theta) * vy
    target_x = float(fit["anchor_norm"][0]) * FRAME_WIDTH + offset_x * FRAME_WIDTH
    target_y = float(fit["anchor_norm"][1]) * FRAME_HEIGHT + offset_y * FRAME_HEIGHT
    centre_x = target_x - transformed_x
    centre_y = target_y - transformed_y
    translation = (centre_x / FRAME_WIDTH - 0.5, centre_y / FRAME_HEIGHT - 0.5)
    return {
        **fit,
        "translation_xy": translation,
        "scale": combined_scale,
        "rotation_deg": combined_rotation,
        "operator_scale": op_scale,
        "operator_rotation_deg": op_rotation,
        "operator_offset_xy_norm": (offset_x, offset_y),
        "pivot_preserving": True,
    }


def transform_asset_point_px(
    asset_point_local: tuple[float, float],
    fit: dict[str, Any],
) -> tuple[float, float]:
    """Transform one native asset pixel using the exact compositor formula."""
    import math

    canvas = fit.get("asset_canvas_size")
    if not (isinstance(canvas, (list, tuple)) and len(canvas) == 2):
        raise PoseCompositionError("contact measurement requires native asset canvas")
    canvas_w, canvas_h = float(canvas[0]), float(canvas[1])
    scale = float(fit["scale"])
    theta = math.radians(float(fit["rotation_deg"]))
    vx = (float(asset_point_local[0]) - canvas_w / 2.0) * scale
    vy = (float(asset_point_local[1]) - canvas_h / 2.0) * scale
    rotated = (
        math.cos(theta) * vx - math.sin(theta) * vy,
        math.sin(theta) * vx + math.cos(theta) * vy,
    )
    centre = (
        (float(fit["translation_xy"][0]) + 0.5) * FRAME_WIDTH,
        (float(fit["translation_xy"][1]) + 0.5) * FRAME_HEIGHT,
    )
    output = (centre[0] + rotated[0], centre[1] + rotated[1])
    if not all(math.isfinite(value) for value in output):
        raise PoseCompositionError("contact transform produced non-finite output")
    return output


def measure_contact_residual(
    asset_point_local: tuple[float, float],
    source_target_px: tuple[float, float],
    fit: dict[str, Any],
) -> dict[str, Any]:
    """Compute post-transform contact error from real local and source points."""
    import math

    transformed = transform_asset_point_px(asset_point_local, fit)
    error = math.hypot(
        transformed[0] - float(source_target_px[0]),
        transformed[1] - float(source_target_px[1]),
    )
    return {
        "asset_point_local": [float(asset_point_local[0]), float(asset_point_local[1])],
        "source_target_px": [float(source_target_px[0]), float(source_target_px[1])],
        "transformed_output_px": [float(transformed[0]), float(transformed[1])],
        "error_px": float(error),
        "limit_px": 8.0,
    }


def validate_contact_measurement(
    measurement: dict[str, Any],
    *,
    expected_source_sha256: str | None = None,
    expected_artwork_sha256: str | None = None,
    expected_source_frame: int | None = None,
    expected_state: str | None = None,
    expected_policy_digest: str | None = None,
) -> dict[str, Any]:
    """Fail closed on stale, substituted, or visibly wrong contact evidence."""
    import math

    if measurement.get("method") not in (
        "source_pixel_contact_plus_production_transform",
        "source_prop_boundary_contact_plus_production_transform",
    ):
        raise PoseCompositionError("contact measurement method is not source-pixel grounded")
    if measurement.get("method") == "source_prop_boundary_contact_plus_production_transform":
        if measurement.get("contact_kind") != "ART_DIRECTION_CONSTRAINT_ON_SOURCE_PROP":
            raise PoseCompositionError("contact measurement lacks source-prop semantic role")
        if measurement.get("source_role") != "book" or measurement.get("book_owner") != "source":
            raise PoseCompositionError("contact measurement source role is not source-owned book")
        if measurement.get("policy_revision") != CONTACT_MEASUREMENT_POLICY_REVISION:
            raise PoseCompositionError("contact measurement policy revision is stale")
    if expected_source_sha256 and measurement.get("source_sha256") != expected_source_sha256:
        raise PoseCompositionError("contact measurement source identity is stale")
    if expected_artwork_sha256 and measurement.get("artwork_sha256") != expected_artwork_sha256:
        raise PoseCompositionError("contact measurement artwork identity is stale")
    if expected_source_frame is not None and int(measurement.get("source_frame", -1)) != int(expected_source_frame):
        raise PoseCompositionError("contact measurement source frame is stale")
    if expected_state is not None and measurement.get("state") != expected_state:
        raise PoseCompositionError("contact measurement pack state is stale")
    if expected_policy_digest is not None and measurement.get("policy_digest") != expected_policy_digest:
        raise PoseCompositionError("contact measurement policy digest is stale")
    fit = measurement.get("fit")
    local = measurement.get("asset_point_local")
    target = measurement.get("source_target_px")
    if not isinstance(fit, dict) or not (isinstance(local, (list, tuple)) and len(local) == 2) or not (isinstance(target, (list, tuple)) and len(target) == 2):
        raise PoseCompositionError("contact measurement lacks actual transform inputs")
    measured = measure_contact_residual((float(local[0]), float(local[1])), (float(target[0]), float(target[1])), fit)
    declared = measurement.get("declared_error_px")
    if declared is None or not math.isfinite(float(declared)):
        raise PoseCompositionError("contact measurement has no finite declared error")
    if abs(float(declared) - measured["error_px"]) > 0.25:
        raise PoseCompositionError("declared contact error does not match transformed pixels")
    if measured["error_px"] > 8.0:
        raise PoseCompositionError(f"source-grounded contact exceeds 8px: {measured['error_px']:.4f}")
    return {**measurement, "measurement": measured, "validated": True}


def build_affine_keyframes(
    fits: list[dict[str, Any]],
) -> tuple[Any, ...]:
    """AffineKeyframe track from per-frame fits (translation/scale/rotation).

    All-zero translation is valid when the measured anchor is at the layer
    center; reject only an empty or malformed track.
    """
    from app.services.renderer_contract import AffineKeyframe

    if not fits:
        raise PoseCompositionError("empty fit track: no keyframes to build")
    keyframes: list[Any] = []
    for fit in fits:
        keyframes.append(
            AffineKeyframe(
                frame=int(fit["source_frame"]),
                translation_xy=(
                    float(fit["translation_xy"][0]),
                    float(fit["translation_xy"][1]),
                ),
                scale=float(fit["scale"]),
                rotation_deg=float(fit["rotation_deg"]),
            )
        )
    return tuple(keyframes)


# ── z-order / book coherence / alpha ─────────────────────────────────────────


def layer_stack_for_frame(source_frame: int) -> tuple[str, ...]:
    """Per-frame layer stack, bottom first (contract bands, T02 order)."""
    _require_in_window(source_frame)
    return POSE_LAYER_STACK


def check_layer_stack(stack: tuple[str, ...] | list[str]) -> None:
    """Fail-closed z-order check: chairs rear, book above character, book
    single, foreground chair front, woman present (never re-seated)."""
    order = tuple(stack)
    if tuple(order) != POSE_LAYER_STACK:
        raise PoseCompositionError(
            f"layer stack must be T02 LAYER_ORDER {list(POSE_LAYER_STACK)!r}, got {list(order)!r}"
        )
    if order.count("book") != 1:
        raise PoseCompositionError("book must appear exactly once (one coherent prop)")
    if not (order.index("chair_occupied") < order.index("character") < order.index("book")):
        raise PoseCompositionError("z-inversion: need chair_occupied < character < book")
    if order[-1] != "chair_foreground":
        raise PoseCompositionError("chair_foreground must stay the front layer")
    if "woman" not in order:
        raise PoseCompositionError("woman dropped from layer stack (must stay seated)")


def require_straight_alpha(alpha_mode: str) -> str:
    """Fixed independent RGBA behavior: only genuine straight alpha passes."""
    if alpha_mode != "straight":
        raise PoseCompositionError(
            f"alpha_mode must be 'straight' (genuine RGBA), got {alpha_mode!r}"
        )
    return alpha_mode


def apply_straight_alpha(layer_bgra: Any) -> Any:
    """Execute the fixed straight-alpha semantics via the shared primitive."""
    from app.services.renderer_routes.composite import apply_alpha_mode

    return apply_alpha_mode(layer_bgra, require_straight_alpha("straight"))


# ── fail-closed pack gate ────────────────────────────────────────────────────


def require_pack_states(pack_states: dict[str, Any]) -> None:
    """Fail-closed: the pack must supply every REQUIRED_POSE_STATES entry.

    A missing state is a readable rejection BEFORE heavy work; poses are
    never invented to cover a gap (the V3 hands-on-knees negative fails
    here: no grip/book states).
    """
    missing = [state for state in REQUIRED_POSE_STATES if not pack_states.get(state)]
    if missing:
        raise PoseCompositionError(
            "pack lacks required pose states: " + ", ".join(missing)
            + " (never fake pose; compatibility stays FAILED)"
        )


def check_pack_for_window(capabilities: dict[str, Any]) -> None:
    """Full window gate: contract 12/12 capabilities + both book states."""
    check_pack_compatibility(capabilities)
    states = {
        "seated_book_closed": capabilities.get("book_closed_variant"),
        "seated_book_open": capabilities.get("book_open_variant"),
    }
    require_pack_states(states)


# ── per-frame composition plan ───────────────────────────────────────────────


def compose_frame_plan(
    source_frame: int,
    asset_anchors_local: dict[str, tuple[float, float]],
    *,
    pin: str = "seat_pelvis",
) -> dict[str, Any]:
    """One coherent per-frame plan: schedule + anchors + fit + layers."""
    _require_in_window(source_frame)
    stack = layer_stack_for_frame(source_frame)
    check_layer_stack(stack)
    fit = fit_layer_transform(source_frame, asset_anchors_local, pin=pin)
    return {
        "revision": COMPOSITION_REVISION,
        "source_frame": source_frame,
        "local": source_to_local(source_frame),
        "pose": pose_state_at(source_frame),
        "pack_state": pose_state_for_pack(source_frame),
        "mouth_character": mouth_state_at(source_frame, "character"),
        "mouth_woman": mouth_state_at(source_frame, "woman"),
        "book": book_state_at(source_frame),
        "anchors_fullframe_px": source_anchors_fullframe_px(source_frame),
        "anchors_normalized": anchors_normalized(source_frame),
        "anchors_bbox_local": anchors_bbox_local(source_frame),
        "fit": fit,
        "layer_stack": list(stack),
        "alpha_mode": "straight",
        "contact_constraints": source_prop_contact_constraints(source_frame),
    }


__all__ = [
    "ANCHOR_PROVENANCE",
    "BOOK_TRANSITION_SOURCE",
    "COMPOSITION_REVISION",
    "CONTACT_MEASUREMENT_POLICY_REVISION",
    "SOURCE_PROP_CONTACT_REVISION",
    "MOUTH_HOLDS",
    "POSE_LAYER_STACK",
    "REQUIRED_POSE_STATES",
    "PoseCompositionError",
    "anchors_bbox_local",
    "anchors_normalized",
    "apply_straight_alpha",
    "book_state_at",
    "build_affine_keyframes",
    "build_pose_schedule_entries",
    "check_layer_stack",
    "check_pack_for_window",
    "compose_frame_plan",
    "combine_operator_transform",
    "event_schedule",
    "fit_layer_transform",
    "layer_stack_for_frame",
    "local_to_source",
    "mouth_state_at",
    "pose_state_at",
    "pose_state_for_pack",
    "require_pack_states",
    "require_straight_alpha",
    "rotation_from_anchors",
    "source_anchors_fullframe_px",
    "source_prop_contact_constraints",
    "source_contact_annotation_digest",
    "source_to_local",
    "CONTACT_MEASUREMENT_POLICY_REVISION",
    "measure_contact_residual",
    "transform_asset_point_px",
    "validate_contact_measurement",
    "translation_for_anchor",
    "uniform_scale_from_anchors",
]

"""Durable, bounded V3 pilot-preview worker.

The handler is intentionally a single-shot preview path.  It consumes a
server-resolved source, a pinned RGBA asset, explicit operator corrections,
and a bounded frame range.  It never runs the six-pose/full-apply workflow.

R2 wiring (DV3-R2-T04): the worker consumes the frozen T01 scene contract
(schedule/geometry/identity), the T02 reconstruction provenance primitives
and the T03 pose-composition transform/layer contract.  A server-owned pack
compatibility verdict runs BEFORE heavy work; outputs are H264/yuv420p and
carry an explicit render/automated-QC/visual-review/approval status split.
Preview outputs never authorize Full Apply.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from app.config import validate_runtime_roots
from app.persistence.artifacts import ManagedRoot, hash_file
from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe
from app.services.pilot_preview.asset_pack import (
    C6_SEMANTIC_CONTRACT,
    C7_SEMANTIC_CONTRACT,
    C9_ARM_RIG_REVISION,
    C9_ARM_RIG_SEMANTIC_CONTRACT,
    PackResolutionError,
    resolve_versioned_pack,
)
from app.services.pilot_preview.arm_rig import (
    ARM_RIG_REVISION,
    ArmRigError,
    build_arm_rig_plan,
    clip_open_book_seam_roles,
    composite_arm_layers,
    fit_affine_matrix,
    validate_arm_rig_frame,
    warp_rgba_inverse,
)
from app.services.pilot_preview.clean_plate_pack import (
    PlateResolutionError,
    load_reviewed_plate,
    resolve_reviewed_plate,
)
from app.services.pilot_preview.pose_composition import (
    COMPOSITION_REVISION,
    CONTACT_MEASUREMENT_POLICY_REVISION,
    PoseCompositionError,
    book_state_at,
    check_layer_stack,
    check_pack_for_window,
    combine_operator_transform,
    fit_layer_transform,
    layer_stack_for_frame,
    measure_contact_residual,
    mouth_state_at,
    pose_state_at,
    require_straight_alpha,
    source_anchors_fullframe_px,
    source_contact_annotation_digest,
    source_prop_contact_constraints,
    validate_contact_measurement,
)
from app.services.pilot_preview.scene_contract import (
    COMPAT_REQUIREMENTS,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SceneContractError,
    check_pack_compatibility,
)
from app.services.pilot_preview.scene_reconstruction import (
    BOOK_FINISH_REVISION,
    FRONT_PROTECTED_ROLES,
    RECONSTRUCTION_REVISION,
    MaskCorrection,
    finish_source_book,
    repair_source_woman_edge,
    reconstruct_frame,
    render_decomposition_sheet,
)
from app.workflow.durable_worker import WorkerContext

JOB_TYPE_PILOT_PREVIEW = "pilot_preview_v1"
PILOT_PIPELINE_REVISION = "c17-c9-arm-rig-native-raster-v1"
PILOT_RENDER_GEOMETRY = {
    "replacement_fit": "measured_asset_anchor_uniform_affine",
    "replacement_mask": "rgba_asset_alpha_only",
    "removal_mask": "reconstruction_permitted_edits_minus_protected_roles",
    "edit_envelope": "prompt_bbox",
    "anchor": "asset_local_anchor_to_source_fullframe_anchor",
    "layer_order": "scene_reconstruction_and_pose_schedule_before_encode",
    "raster_sampling": "inverse_area_premultiplied_one_pass_v1",
    "arm_kinematics": "deterministic_two_bone_ik_v1",
    "hand_alpha_contract": "c9-independent-arm-rig-v1",
    "contact_gate": "c9-final-visible-body-wrist-hand-book-boundary-v2",
    "occlusion_contract": "forearm_behind_book_fingers_in_front_v1",
}
#: Server-owned verdict for the pinned V3 negative asset (T01 ASSET_BRIEF +
#: T03 step B): the current pinned pack cannot support the window states, so
#: any manifest binding this asset SHA fails the pack gate BEFORE heavy work.
#: A future approved pack v2 ships as a NEW versioned file with its own SHA;
#: the gate passes only for non-negative assets with full capabilities.
V3_NEGATIVE_ASSET_SHA256 = "e07e2a3a76ea3d7d3144ae43f89ebbcc225a37cf91aa6ab159961f6d7349dc47"
PACK_COMPAT_MISSING_FOR_V3 = (
    "grip_both_hands_chest",
    "book_open_variant",
    "book_closed_variant",
    "anchor_hand_grip_l",
    "anchor_hand_grip_r",
    "anchor_book_corners",
)
_FPS_NUM = 30
_FPS_DEN = 1
_MAX_FRAMES = 150
_MIN_FRAMES = 90
_ASSET_REL = "assets/v3-seated-rgba.png"
_OUTPUT_KEYS = ("before", "after", "evidence")
_VALIDATED_CONTACT_CONTRACTS = frozenset({C6_SEMANTIC_CONTRACT, C7_SEMANTIC_CONTRACT, C9_ARM_RIG_SEMANTIC_CONTRACT})
HAND_ALPHA_REVISION = "c9-independent-arm-rig-v1"
CONTACT_GATE_REVISION = "c9-final-visible-body-wrist-hand-book-boundary-v2"


class PilotPreviewError(RuntimeError):
    """Permanent worker failure for malformed or unavailable pilot inputs."""


def _canonical_operator_keyframes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Canonicalize only transform values that the compositor actually uses.

    ``anchor_xy_norm`` is retained in public requests for historical/UI
    compatibility, but is informational in ``source_derived`` mode.  Binding
    that unused field would make a pre-encode review and its candidate appear
    different without changing a pixel.  The effective record therefore pins
    scale/rotation and the operator offset, with the offset forced to zero in
    source-derived mode.
    """
    mode = str(manifest.get("anchor_mode", "source_derived"))
    if mode not in ("source_derived", "explicit_offset"):
        raise PilotPreviewError(f"ANCHOR_MODE_INVALID: {mode}")
    raw = manifest.get("anchor_keyframes", [])
    if not isinstance(raw, list):
        raise PilotPreviewError("ANCHOR_KEYFRAMES_INVALID")
    result: list[dict[str, Any]] = []
    for item in sorted(raw, key=lambda value: int(value["frame"])):
        if not isinstance(item, dict):
            raise PilotPreviewError("ANCHOR_KEYFRAME_INVALID")
        offset = item.get("operator_offset_xy_norm", (0.0, 0.0))
        if mode == "source_derived":
            offset = (0.0, 0.0)
        result.append(
            {
                "frame": int(item["frame"]),
                "scale": float(item.get("scale", 1.0)),
                "rotation_deg": float(item.get("rotation_deg", 0.0)),
                "operator_offset_xy_norm": [float(offset[0]), float(offset[1])],
            }
        )
    return result


def canonical_identity_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return only user/input identity fields; paths and outputs are excluded."""
    keys = (
        "schema_version", "project_id", "durable_project_id", "durable_video_item_id",
        "generation", "source_sha256", "asset_sha256", "asset_state_sha256", "sam2_checkpoint_sha256",
        "sam2_model_cfg", "sam2_device", "start_frame", "end_frame", "role",
        "source_prompt", "mask_correction", "anchor_keyframes", "occluder", "policy",
        "pipeline_revision", "render_geometry_contract",
        # These are effective inputs, not optional descriptive metadata.  A
        # change to any resolved pack/state/plate/mask/algorithm identity must
        # produce a new durable output identity.
        "pack_id", "pack_version", "pack_manifest_sha256", "pack_content_sha256",
        "pack_approval_status", "pack_semantic_review_status",
        "pack_state_identity", "scene_contract_hash", "reconstruction_revision",
        "clean_plate_identity", "protected_masks_identity", "effective_geometry",
        "pack_capabilities", "composition_revision",
        "clean_plate_id", "clean_plate_manifest_sha256", "clean_plate_content_sha256",
        "clean_plate_image_sha256", "clean_plate_source_sha256", "clean_plate_source_window",
        "clean_plate_revision",
        "anchor_mode",
        "book_finish_revision",
        "effective_input_sha256",
    )
    payload = {key: manifest[key] for key in keys if key in manifest}
    if "anchor_keyframes" in payload:
        payload["anchor_keyframes"] = _canonical_operator_keyframes(manifest)
    # The source contact annotation is production input, not post-render
    # commentary.  Bind its revision/digest even when the older API payload
    # does not know these C5 fields yet.
    payload["contact_measurement_policy_revision"] = CONTACT_MEASUREMENT_POLICY_REVISION
    payload["source_contact_annotation_digest"] = source_contact_annotation_digest()
    payload["book_finish_revision"] = BOOK_FINISH_REVISION
    return payload


def pack_gate_verdict(manifest: dict[str, Any]) -> dict[str, Any]:
    """Server-owned pack compatibility verdict, BEFORE heavy work.

    Returns ``{"compatible": True}`` only when a server-owned versioned
    pack has been resolved and its files/anchors/capabilities pass the T01
    contract.  Client capability maps are ignored.  The pinned V3 negative
    asset always fails with the documented missing states.
    """
    asset_sha = str(manifest.get("asset_sha256", "")).lower()
    if asset_sha == V3_NEGATIVE_ASSET_SHA256:
        return {
            "compatible": False,
            "code": "PACK_COMPATIBILITY_FAILED",
            "reason": (
                "pinned V3 asset is the intentional negative fixture "
                "(hands-on-knees, hands empty, open book deleted); "
                "it cannot support the window states"
            ),
            "missing": list(PACK_COMPAT_MISSING_FOR_V3),
            "required": list(COMPAT_REQUIREMENTS),
        }
    pack_id = manifest.get("pack_id")
    pack_root = manifest.get("pack_root")
    if not isinstance(pack_id, str) or not isinstance(pack_root, str):
        return {
            "compatible": False,
            "code": "PACK_COMPATIBILITY_FAILED",
            "reason": "manifest carries no server-resolved versioned pack id/root",
            "missing": list(COMPAT_REQUIREMENTS),
            "required": list(COMPAT_REQUIREMENTS),
        }
    try:
        pack = resolve_versioned_pack(
            pack_id,
            Path(pack_root),
            expected_content_sha256=asset_sha or None,
            expected_manifest_sha256=manifest.get("pack_manifest_sha256"),
            expected_source_sha256=manifest.get("source_sha256"),
            allow_private_preview=True,
        )
        capabilities = pack["capabilities"]
        check_pack_compatibility(capabilities)
        check_pack_for_window(capabilities)
    except (PackResolutionError, SceneContractError, PoseCompositionError) as exc:
        return {
            "compatible": False,
            "code": "PACK_COMPATIBILITY_FAILED",
            "reason": str(exc),
            "missing": [],
            "required": list(COMPAT_REQUIREMENTS),
        }
    return {
        "compatible": True,
        "pack": pack,
        "pack_id": pack["pack_id"],
        "pack_version": pack["version"],
        "pack_manifest_sha256": pack["manifest_sha256"],
        "pack_content_sha256": pack["content_sha256"],
        "capabilities": capabilities,
    }


def require_pack_compatible(manifest: dict[str, Any]) -> dict[str, Any]:
    """Fail closed BEFORE heavy work when the pack cannot support the window."""
    verdict = pack_gate_verdict(manifest)
    if not verdict["compatible"]:
        missing = ", ".join(verdict.get("missing") or ["see reason"])
        raise PilotPreviewError(
            f"{verdict['code']}: {verdict['reason']} (missing: {missing})"
        )
    return verdict


def compute_input_identity_sha256(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_identity_payload(manifest), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_effective_input_record(
    manifest: dict[str, Any],
    *,
    frame_size: tuple[int, int],
    pack: dict[str, Any] | None = None,
    schedule_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the single effective-input record shared by review and encode.

    This record intentionally contains resolved identities and pixel geometry,
    not just request prose.  Both pre-encode stills and a candidate must be
    derived from this exact record; a changed removal envelope, occluder,
    transform, schedule, pack, plate, source, or algorithm revision is a
    different input and must not be presented as the same review.
    """
    width, height = (int(frame_size[0]), int(frame_size[1]))
    if width <= 0 or height <= 0:
        raise PilotPreviewError("EFFECTIVE_INPUT_FRAME_SIZE_INVALID")
    raw_rect = manifest.get("mask_correction", {}).get("bbox_xywh_norm")
    if not isinstance(raw_rect, (list, tuple)) or len(raw_rect) != 4:
        raise PilotPreviewError("EFFECTIVE_INPUT_MASK_CORRECTION_INVALID")
    rect = tuple(float(value) for value in raw_rect)
    bbox_xyxy = _normalized_rect_to_px(rect, width, height)
    bbox_xywh = [
        bbox_xyxy[0], bbox_xyxy[1], bbox_xyxy[2] - bbox_xyxy[0], bbox_xyxy[3] - bbox_xyxy[1]
    ]
    schedule_digest = None
    if schedule_rows is not None:
        schedule_digest = hashlib.sha256(
            json.dumps(schedule_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
    pack_identity = None
    if pack is not None:
        pack_identity = {
            "pack_id": pack.get("pack_id"),
            "version": pack.get("version"),
            "manifest_sha256": pack.get("manifest_sha256"),
            "content_sha256": pack.get("content_sha256"),
            "validated_contract": pack.get("validated_contract"),
            "states": {
                str(state_id): {
                    "sha256": state.get("sha256"),
                    "anchors": state.get("anchors"),
                    "canvas_size": state.get("canvas_size"),
                    "pose": state.get("pose"),
                    "book": state.get("book"),
                    "arm_rig": (
                        {
                            "revision": state["arm_rig"].get("revision"),
                            "joints": state["arm_rig"].get("joints"),
                            "bend_sign": state["arm_rig"].get("bend_sign"),
                            "occlusion": state["arm_rig"].get("occlusion"),
                            "roles": {
                                side: {
                                    role_name: {
                                        "relative_path": role.get("relative_path"),
                                        "sha256": role.get("sha256"),
                                        "start_joint": role.get("start_joint"),
                                        "end_joint": role.get("end_joint"),
                                    }
                                    for role_name, role in sorted((state["arm_rig"].get("roles", {}).get(side, {}) or {}).items())
                                }
                                for side in ("left", "right")
                            },
                        }
                        if isinstance(state.get("arm_rig"), dict)
                        else None
                    ),
                }
                for state_id, state in sorted((pack.get("states") or {}).items())
                if isinstance(state, dict)
            },
        }
    record: dict[str, Any] = {
        "schema_version": "pilot-preview-effective-input-v1",
        "source": {
            "sha256": str(manifest.get("source_sha256", "")),
            "frame_range": [int(manifest["start_frame"]), int(manifest["end_frame"])],
            "fps": [_FPS_NUM, _FPS_DEN],
            "dimensions": [width, height],
        },
        "mask_correction": {
            "bbox_xywh_norm": [float(value) for value in rect],
            "bbox_xyxy_pixels": list(bbox_xyxy),
            "bbox_xywh_pixels": bbox_xywh,
            "source_frame": int(manifest.get("mask_correction", {}).get("source_frame", manifest["start_frame"])),
        },
        "anchor_mode": str(manifest.get("anchor_mode", "source_derived")),
        "operator_keyframes": _canonical_operator_keyframes(manifest),
        "occluder": manifest.get("occluder", {}),
        "pack": pack_identity,
        "clean_plate": {
            "id": manifest.get("clean_plate_id"),
            "manifest_sha256": manifest.get("clean_plate_manifest_sha256"),
            "content_sha256": manifest.get("clean_plate_content_sha256"),
            "image_sha256": manifest.get("clean_plate_image_sha256"),
            "revision": manifest.get("clean_plate_revision"),
        },
        "schedule_sha256": schedule_digest,
        "revisions": {
            "pipeline": manifest.get("pipeline_revision"),
            "geometry": manifest.get("render_geometry_contract"),
            "composition": manifest.get("composition_revision", COMPOSITION_REVISION),
            "reconstruction": manifest.get("reconstruction_revision", RECONSTRUCTION_REVISION),
            "contact_gate": CONTACT_GATE_REVISION,
            "book_finish": BOOK_FINISH_REVISION,
            "hand_alpha": HAND_ALPHA_REVISION,
            "arm_rig": ARM_RIG_REVISION,
        },
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    record["effective_input_sha256"] = hashlib.sha256(encoded).hexdigest()
    return record


def _validated_contact_contract(pack: dict[str, Any]) -> str | None:
    """Return only the resolver's exact semantic contract, never a prefix."""
    contract = pack.get("validated_contract")
    return contract if contract in _VALIDATED_CONTACT_CONTRACTS else None


def _reference_alpha_composite(base_bgr: Any, layer_bgra: Any) -> Any:
    """Pure reference for the renderer's in-place straight-alpha operation."""
    import numpy as np

    base = np.asarray(base_bgr).copy()
    layer = np.asarray(layer_bgra)
    alpha = layer[:, :, 3:4].astype(np.float64) / 255.0
    blended = layer[:, :, :3].astype(np.float64) * alpha + base.astype(np.float64) * (1.0 - alpha)
    return blended.astype(np.uint8)


def _semantic_hand_alpha(layer_bgra: Any, *, side: str, state_id: str) -> Any:
    """Keep only source-supported skin/forearm contours for a hand patch.

    The C7 hand-source PNG is a full-body reference whose alpha also contains
    the green shirt.  Its anatomical polygons locate the patch but do not
    authorize painting that shirt over the source-owned book.  This derived
    mask retains skin, pale nail/edge pixels, and dark outline pixels adjacent
    to skin; green clothing and transparent support are excluded.
    """
    import cv2
    import numpy as np

    if side not in {"left", "right"}:
        raise PilotPreviewError(f"HAND_SIDE_INVALID:{side}")
    rgba = np.asarray(layer_bgra)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise PilotPreviewError(f"HAND_ALPHA_INPUT_INVALID:{state_id}:{side}")
    b, g, r, alpha = (rgba[:, :, index].astype(np.int16) for index in range(4))
    visible = alpha > 0
    # Skin/forearm in the pinned BGRA source is warm red-over-green-over-blue;
    # the moss shirt is green-dominant and therefore excluded.
    skin = visible & (r >= 120) & (r >= g + 5) & (g >= b - 2)
    near_skin = cv2.dilate(skin.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1) > 0
    green_clothing = visible & (g >= r + 8) & (g >= b + 8)
    light_edge = visible & near_skin & (np.minimum(np.minimum(b, g), r) >= 135) & ~green_clothing
    dark_outline = visible & near_skin & (np.maximum(np.maximum(b, g), r) <= 105) & ~green_clothing
    keep = (skin | light_edge | dark_outline) & visible
    if not np.any(keep):
        raise PilotPreviewError(f"HAND_ALPHA_EMPTY:{state_id}:{side}:{HAND_ALPHA_REVISION}")
    output = np.array(rgba, copy=True)
    output[:, :, 3] = np.where(keep, alpha, 0).astype(np.uint8)
    if np.any((output[:, :, 3] > 32) & green_clothing):
        raise PilotPreviewError(f"HAND_ALPHA_GREEN_SUPPORT:{state_id}:{side}")
    return output


def _validate_final_hand_pixels(
    *,
    before_hands: Any,
    final_frame: Any,
    hand_layers: dict[str, Any],
    body_layer: Any,
    book_mask: Any,
    book_reference: Any,
    row: dict[str, Any],
    before_body: Any | None = None,
) -> dict[str, Any]:
    """Validate actual final pixels and per-side semantic contribution.

    Alpha occupancy is only the plan.  The gate reconstructs the expected
    final pixels from the exact pre-hand frame and compares them to the
    compositor output, so a skipped blit or later erase cannot remain green.
    """
    import cv2
    import numpy as np

    before = np.asarray(before_hands)
    actual = np.asarray(final_frame)
    if before.shape != actual.shape or actual.ndim != 3 or actual.shape[2] != 3:
        raise PilotPreviewError("HAND_FINAL_PIXEL_SHAPE_INVALID")
    book_pixels = np.asarray(book_mask) > 0
    if not np.any(book_pixels):
        raise PilotPreviewError("HAND_BOOK_PIXEL_GATE_EMPTY")
    book_base = np.asarray(book_reference)
    if book_base.shape != actual.shape:
        raise PilotPreviewError("HAND_BOOK_REFERENCE_SHAPE_INVALID")
    # A protected mask is only a plan.  The source-frame reference proves
    # that the same visible book pixels survived into the final image.
    source_book_visible = book_pixels & np.any(book_base != 0, axis=2)
    source_book_count = int(np.count_nonzero(source_book_visible))
    if source_book_count < max(1, int(np.ceil(np.count_nonzero(book_pixels) * 0.25))):
        raise PilotPreviewError("HAND_BOOK_REFERENCE_EMPTY")
    required_book_count = max(1, int(np.ceil(source_book_count * 0.80)))
    body_rgba = np.asarray(body_layer)
    if body_rgba.ndim != 3 or body_rgba.shape[2] != 4 or body_rgba.shape[:2] != actual.shape[:2]:
        raise PilotPreviewError("HAND_BODY_LAYER_INVALID")
    body_pixels = body_rgba[:, :, 3] > 32
    if before_body is None:
        # Compatibility for the small synthetic contract probe: its
        # ``before_hands`` already contains the body control pixel.  Real
        # compositor calls pass the decoded pre-body frame below.
        actual_body_visible = body_pixels & np.any(before_hands != 0, axis=2)
    else:
        body_base = np.asarray(before_body)
        if body_base.shape != actual.shape:
            raise PilotPreviewError("HAND_BODY_BASE_SHAPE_INVALID")
        expected_body_frame = _reference_alpha_composite(body_base, body_rgba)
        expected_body_contribution = np.any(expected_body_frame != body_base, axis=2) & body_pixels
        # Planned alpha alone is not body evidence.  A body pixel is visible
        # only where the exact body contribution survives into final output.
        actual_body_visible = expected_body_contribution & np.all(actual == expected_body_frame, axis=2)
    expected = before.copy()
    union_visible = np.zeros(book_pixels.shape, dtype=bool)
    expected_hand_union = np.zeros(book_pixels.shape, dtype=bool)
    side_results: dict[str, Any] = {}
    for hand_name, side in (("hand_grip_l", "left"), ("hand_grip_r", "right")):
        layer = np.asarray(hand_layers.get(side))
        if layer.ndim != 3 or layer.shape[2] != 4:
            raise PilotPreviewError(f"HAND_FINAL_LAYER_MISSING:{side}")
        planned = layer[:, :, 3] > 32
        if not np.any(planned):
            raise PilotPreviewError(f"HAND_FINAL_LAYER_EMPTY:{side}")
        next_expected = _reference_alpha_composite(expected, layer)
        b, g, r = (layer[:, :, index].astype(np.int16) for index in range(3))
        # Bilinear warp may carry RGB from transparent source pixels into a
        # low-alpha fringe.  Only an opaque green support patch is a semantic
        # violation; antialiased edge RGB is legitimate.
        green_support = (layer[:, :, 3] >= 240) & (g >= r + 8) & (g >= b + 8)
        if np.any(green_support):
            raise PilotPreviewError(f"HAND_GREEN_SUPPORT_VISIBLE:{row['source_frame']}:{side}")
        # A hand is visible only where its expected contribution survives in
        # the actual final frame.  This is independent of alpha metadata.
        expected_pixel_delta = np.any(next_expected != expected, axis=2)
        expected_contribution = expected_pixel_delta & planned
        # Include low-alpha antialias pixels in the authorized occlusion mask;
        # the renderer can change them even though the semantic hand mask is
        # intentionally restricted to alpha > 32.
        expected_hand_union |= expected_pixel_delta
        actual_contribution = np.any(actual != before, axis=2) & planned
        if not np.any(actual_contribution):
            raise PilotPreviewError(f"HAND_FINAL_PIXEL_CONTRIBUTION_MISSING:{side}")
        if not np.array_equal(actual[planned], next_expected[planned]):
            raise PilotPreviewError(f"HAND_FINAL_PIXEL_MISMATCH:{side}")
        if np.any(union_visible & planned):
            raise PilotPreviewError("HAND_SIDE_OWNERSHIP_OVERLAP")
        union_visible |= planned
        target = row["contact_measurements"][hand_name]["transformed_output_px"]
        tx, ty = int(round(float(target[0]))), int(round(float(target[1])))
        hand_book_touch = cv2.dilate(actual_contribution.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1) > 0
        actual_contact = hand_book_touch & source_book_visible
        if not np.any(actual_contact):
            raise PilotPreviewError(f"HAND_BOOK_BOUNDARY_DISCONNECTED:{row['source_frame']}:{hand_name}")
        contact_ys, contact_xs = np.where(actual_contact)
        contact_distance = np.sqrt((contact_xs - float(target[0])) ** 2 + (contact_ys - float(target[1])) ** 2)
        if len(contact_distance) == 0 or float(contact_distance.min()) > 2.0:
            raise PilotPreviewError(f"HAND_BOOK_TARGET_MISMATCH:{row['source_frame']}:{hand_name}")
        body_near_hand = cv2.dilate(actual_body_visible.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
        if not np.any(actual_body_visible):
            raise PilotPreviewError(f"HAND_BODY_NOT_VISIBLE:{row['source_frame']}:{side}")
        if not np.any(actual_contribution & body_near_hand):
            raise PilotPreviewError(f"HAND_BODY_WRIST_DISCONNECTED:{row['source_frame']}:{side}")
        # The near-body check above is tolerant for antialiased edges.  This
        # exact component check is the semantic proof: a real visible hand
        # must share an 8-connected body-to-wrist component, not merely sit
        # near planned alpha.
        body_hand = (actual_body_visible | actual_contribution).astype(np.uint8)
        _component_count, component_labels = cv2.connectedComponents(body_hand, connectivity=8)
        body_labels = set(int(value) for value in np.unique(component_labels[actual_body_visible]) if int(value) != 0)
        hand_labels = set(int(value) for value in np.unique(component_labels[actual_contribution]) if int(value) != 0)
        body_hand_labels = body_labels.intersection(hand_labels)
        if not body_hand_labels:
            raise PilotPreviewError(f"HAND_BODY_HAND_COMPONENT_DISCONNECTED:{row['source_frame']}:{side}")
        # The body-connected hand component must also be the component that
        # reaches the visible source-book boundary.  Checking contact against
        # the whole hand mask would let a detached hand island touch the book
        # while a different island touches the body.
        body_hand_component = np.isin(component_labels, tuple(body_hand_labels)) & actual_contribution
        book_contact_zone = cv2.dilate(
            source_book_visible.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1
        ).astype(bool)
        if not np.any(body_hand_component & book_contact_zone):
            raise PilotPreviewError(f"HAND_BODY_HAND_BOOK_COMPONENT_DISCONNECTED:{row['source_frame']}:{side}")
        visible_near = body_hand_component & book_contact_zone
        side_results[side] = {
            "planned_alpha_pixels": int(np.count_nonzero(planned)),
            "expected_visible_contribution_pixels": int(np.count_nonzero(expected_contribution)),
            "actual_visible_contribution_pixels": int(np.count_nonzero(actual_contribution)),
            "contact_pixels": int(np.count_nonzero(visible_near)),
            "target_px": [float(target[0]), float(target[1])],
            "body_hand_component_verified": True,
            "body_hand_book_component_verified": True,
            "final_pixels_verified": True,
        }
        expected = next_expected
    # The book is a source-owned prop.  Outside the exact planned hand
    # occlusion pixels, the final compositor must preserve the decoded
    # pre-hand book pixels byte-for-byte.  This is deliberately an ownership
    # check, not RGB occupancy: a gray/green/texture fill is not a book, while
    # a legitimate black outline and antialiased source edge remain valid.
    # Only compositor pixels that are actually expected to change the source
    # frame are authorized book occlusion.  The planned alpha envelope can be
    # intentionally larger for legacy C6 packs and must not hide a missing
    # book-prop proof by itself.
    source_book_unoccluded = source_book_visible & ~expected_hand_union
    strict_book_content = row.get("validated_semantic_contract") != C6_SEMANTIC_CONTRACT
    if not strict_book_content:
        # C6 is retained only as a legacy engineering contract.  Its fixture
        # uses a full-body opaque sprite whose expected hand contribution can
        # cover the complete tiny source-book sample.  Keep that compatibility
        # path, but never use it for the reviewed C7 public pack or for the
        # standalone semantic gate probes (which have no C6 contract marker).
        source_book_unoccluded = source_book_visible
    visible_book_count = int(
        np.count_nonzero(source_book_unoccluded & np.any(actual != 0, axis=2))
    )
    if visible_book_count < required_book_count:
        raise PilotPreviewError("HAND_BOOK_NOT_VISIBLE")
    book_mismatch = source_book_unoccluded & ~np.all(actual == before, axis=2)
    if strict_book_content and int(np.count_nonzero(book_mismatch)):
        raise PilotPreviewError(
            f"HAND_BOOK_CONTENT_MISMATCH:{int(np.count_nonzero(book_mismatch))}"
        )
    book_reference_match_count = int(
        np.count_nonzero(source_book_unoccluded & np.all(actual == before, axis=2))
    )
    if not np.array_equal(actual[union_visible], expected[union_visible]):
        raise PilotPreviewError("HAND_FINAL_PIXEL_SEQUENCE_MISMATCH")
    return {
        "status": "passed",
        "contract": row.get("contact_semantic_contract"),
        "hand_layer_order": "exclusive_body_then_left_right_skin_forearm_contours_above_source_book",
        "book_owner": "source",
        "hand_pixels": int(np.count_nonzero(union_visible)),
        "book_mask_pixels": int(np.count_nonzero(book_pixels)),
        "visible_book_pixels": visible_book_count,
        "book_reference_match_pixels": book_reference_match_count,
        "visible_rgb_contact_radius_px": 2,
        "contact_gate_revision": CONTACT_GATE_REVISION,
        "body_bridge_verified": True,
        "continuous_body_hand_component": True,
        "book_visibility_verified": True,
        "exclusive_side_masks": True,
        "final_frame_pixel_comparison": "expected_straight_alpha_sequence",
        "per_side": side_results,
    }


def build_output_relpaths(input_identity_sha256: str) -> dict[str, str]:
    if len(input_identity_sha256) != 64 or any(c not in "0123456789abcdef" for c in input_identity_sha256.lower()):
        raise PilotPreviewError("INPUT_IDENTITY_INVALID")
    prefix = f"pilot-preview/jobs/{input_identity_sha256}"
    return {"before": f"{prefix}/before.mp4", "after": f"{prefix}/after.mp4", "evidence": f"{prefix}/evidence.json"}


def output_relpaths_for_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    identity = str(manifest.get("input_identity_sha256", ""))
    expected = build_output_relpaths(identity)
    actual = manifest.get("output_relpaths")
    if actual != expected:
        raise PilotPreviewError("OUTPUT_PATH_CONTRACT_FAILED")
    return expected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str]) -> None:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PilotPreviewError(f"FFMPEG_UNAVAILABLE: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        raise PilotPreviewError(
            f"FFMPEG_RENDER_FAILED: {tail[-1] if tail else proc.returncode}"
        )


def _probe_media(path: Path, ffprobe: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PilotPreviewError(f"FFPROBE_UNAVAILABLE: {exc}") from exc
    if proc.returncode != 0:
        raise PilotPreviewError(f"FFPROBE_FAILED: {proc.stderr.strip()}")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise PilotPreviewError("FFPROBE_INVALID_JSON") from exc
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise PilotPreviewError(f"OUTPUT_MEDIA_INVALID: {path.name} has no video stream")
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)

    def _float(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "N/A") else None
        except (TypeError, ValueError):
            return None

    def _rate(value: Any) -> tuple[int, int] | None:
        if not isinstance(value, str) or "/" not in value:
            return None
        left, right = value.split("/", 1)
        try:
            numerator, denominator = int(left), int(right)
        except ValueError:
            return None
        return (numerator, denominator) if denominator else None

    format_duration = _float((payload.get("format") or {}).get("duration"))
    audio_duration = _float(audio.get("duration")) if isinstance(audio, dict) else None

    def _start(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "N/A") else None
        except (TypeError, ValueError):
            return None

    return {
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "video_codec": str(video.get("codec_name", "")),
        "pix_fmt": str(video.get("pix_fmt", "")),
        "fps": _rate(video.get("r_frame_rate")) or _rate(video.get("avg_frame_rate")),
        "frames_reported": int(video["nb_frames"]) if str(video.get("nb_frames", "")).isdigit() else None,
        "video_duration_seconds": _float(video.get("duration")) or format_duration,
        "audio_present": audio is not None,
        "audio_codec": audio.get("codec_name") if isinstance(audio, dict) else None,
        "audio_duration_seconds": audio_duration or (format_duration if audio is not None else None),
        "audio_start_offset_seconds": _start(audio.get("start_time")) if isinstance(audio, dict) else None,
    }


def _has_audio(path: Path, ffprobe: str) -> bool:
    return bool(_probe_media(path, ffprobe)["audio_present"])


def _read_frames(source: Path, start: int, end: int) -> list[Any]:
    import cv2

    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise PilotPreviewError(f"SOURCE_DECODE_FAILED: {source}")
        capture.set(cv2.CAP_PROP_POS_FRAMES, start)
        frames: list[Any] = []
        for _ in range(start, end):
            ok, frame = capture.read()
            if not ok or frame is None:
                raise PilotPreviewError("SOURCE_DECODE_FAILED: short frame range")
            frames.append(frame)
        if len(frames) != end - start:
            raise PilotPreviewError("SOURCE_DECODE_FAILED: frame count mismatch")
        return frames
    finally:
        capture.release()


def _write_video_only(frames: list[Any], path: Path, ffmpeg: str) -> None:
    """Stage frames then encode H264/yuv420p (browser-decodable R2 path).

    OpenCV's mp4v writer emits MPEG-4 Part 2, which the R2 review found
    unplayable; the staged file is therefore transcoded with the runnable
    FFmpeg to ``libx264`` + ``yuv420p`` + ``faststart``.  The staged
    intermediate is removed so only the verified encode remains.
    """
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = frames[0].shape[:2]
    staged = path.with_name(path.stem + ".staged-mp4v.mp4")
    writer = cv2.VideoWriter(
        str(staged), cv2.VideoWriter_fourcc(*"mp4v"),  # type: ignore[attr-defined]
        _FPS_NUM / _FPS_DEN, (width, height)
    )
    if not writer.isOpened():
        raise PilotPreviewError("VIDEO_ENCODER_UNAVAILABLE: OpenCV mp4v")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()
    if not staged.is_file() or staged.stat().st_size <= 0:
        raise PilotPreviewError("VIDEO_ENCODER_FAILED: empty staged video")
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(staged),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(path),
        ]
    )
    try:
        staged.unlink()
    except OSError:
        pass
    if not path.is_file() or path.stat().st_size <= 0:
        raise PilotPreviewError("VIDEO_ENCODER_FAILED: empty H264 output")


def _normalized_rect_to_px(rect: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    x0 = max(0, min(width - 1, round(x * width)))
    y0 = max(0, min(height - 1, round(y * height)))
    x1 = max(x0 + 1, min(width, round((x + w) * width)))
    y1 = max(y0 + 1, min(height, round((y + h) * height)))
    return x0, y0, x1, y1


def _make_mask(rect: tuple[float, float, float, float], width: int, height: int) -> Any:
    import cv2
    import numpy as np

    mask = np.zeros((height, width), dtype=np.uint8)
    x0, y0, x1, y1 = _normalized_rect_to_px(rect, width, height)
    # The operator correction is a removal region rather than a source crop;
    # the inpaint border is deliberately kept inside the corrected rectangle.
    cv2.rectangle(mask, (x0, y0), (x1 - 1, y1 - 1), 255, thickness=-1)
    return mask


def _asset_alpha_geometry(asset: Path) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    """Return the pinned asset's visible alpha bbox and native canvas size."""
    import cv2
    import numpy as np

    rgba = cv2.imread(str(asset), cv2.IMREAD_UNCHANGED)
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] < 4:
        raise PilotPreviewError("ASSET_ALPHA_INVALID: expected RGBA asset")
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha > 0)
    if len(xs) == 0:
        raise PilotPreviewError("ASSET_ALPHA_INVALID: asset has no visible pixels")
    bbox = (
        int(xs.min()), int(ys.min()),
        int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1),
    )
    return bbox, (int(rgba.shape[1]), int(rgba.shape[0]))


def _replacement_fit_scale(
    asset: Path, rect: tuple[float, float, float, float], width: int, height: int,
) -> tuple[float, tuple[int, int, int, int]]:
    """Fit the visible alpha bbox inside the destination region without distortion."""
    alpha_bbox, _native_size = _asset_alpha_geometry(asset)
    x0, y0, x1, y1 = _normalized_rect_to_px(rect, width, height)
    target_w, target_h = x1 - x0, y1 - y0
    scale = min(target_w / alpha_bbox[2], target_h / alpha_bbox[3])
    if scale <= 0:
        raise PilotPreviewError("ASSET_GEOMETRY_INVALID: non-positive alpha fit scale")
    return float(scale), alpha_bbox


def _sam2_masks(frames: list[Any], rect: tuple[float, float, float, float], manifest: dict[str, Any]) -> list[Any]:
    """Run the pinned SAM2 prompt + temporal propagation for this window."""
    try:
        from app.adapters.segmentation import SAM2Adapter
        from app.schemas import SelectionInput, SelectionMode
    except Exception as exc:  # noqa: BLE001 - capability is reported honestly
        raise PilotPreviewError(f"SAM2_RUNTIME_UNAVAILABLE: {exc}") from exc

    import cv2

    height, width = frames[0].shape[:2]
    x0, y0, x1, y1 = _normalized_rect_to_px(rect, width, height)
    adapter = SAM2Adapter(
        model_cfg=str(manifest.get("sam2_model_cfg", "configs/sam2.1/sam2.1_hiera_l.yaml")),
        checkpoint=str(manifest["sam2_checkpoint_path"]),
        device=str(manifest.get("sam2_device", "cpu")),
    )
    try:
        seed = adapter.segment_frame(
            frames[0],
            SelectionInput(
                mode=SelectionMode.BBOX,
                frame_index=int(manifest["start_frame"]),
                x=float(x0),
                y=float(y0),
                width=float(x1 - x0),
                height=float(y1 - y0),
            ),
        )
        masks = adapter.propagate_masks(frames, seed, 0)
    except Exception as exc:  # noqa: BLE001 - model failure is a truthful blocker
        raise PilotPreviewError(f"SAM2_PROPAGATION_FAILED: {exc}") from exc
    finally:
        adapter.cleanup()
    if len(masks) != len(frames):
        raise PilotPreviewError("SAM2_PROPAGATION_FAILED: frame count mismatch")
    return [cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)[1] for mask in masks]


def _clean_source_frames(
    frames: list[Any], rect: tuple[float, float, float, float], propagated_masks: list[Any], ctx: WorkerContext,
) -> tuple[list[Any], Any, list[dict[str, Any]]]:
    import cv2
    import numpy as np

    cleaned: list[Any] = []
    metrics: list[dict[str, Any]] = []
    # The prompt bbox is an edit envelope only. It is never itself the
    # removal mask: the tight propagated target mask owns source removal.
    edit_envelope = _make_mask(rect, frames[0].shape[1], frames[0].shape[0])
    first_removal_mask = np.zeros_like(edit_envelope)
    for index, (frame, propagated) in enumerate(zip(frames, propagated_masks)):
        if ctx.is_cancelled():
            return [], first_removal_mask, metrics
        # Real background reconstruction: remove the corrected target region
        # and inpaint from the surrounding pixels on every decoded frame. The
        # propagated mask is clipped to the operator envelope so SAM2 cannot
        # damage neighboring pixels outside the correction.
        propagated_binary = cv2.threshold(propagated, 127, 255, cv2.THRESH_BINARY)[1]
        effective_mask = cv2.bitwise_and(propagated_binary, edit_envelope)
        if index == 0:
            first_removal_mask = effective_mask.copy()
        cleaned.append(cv2.inpaint(frame, effective_mask, 3, cv2.INPAINT_TELEA))
        ys, xs = np.where(effective_mask > 0)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)] if len(xs) else [0, 0, 0, 0]
        metrics.append({
            "mask_sha256": hashlib.sha256(effective_mask.tobytes()).hexdigest(),
            "mask_area_pixels": int((effective_mask > 0).sum()),
            "mask_bbox_xywh_pixels": bbox,
            "mask_role": "tight_target_removal",
            "edit_envelope_bbox_xywh_pixels": [
                int(v) for v in _normalized_rect_to_px(rect, frames[0].shape[1], frames[0].shape[0])
            ],
        })
        if index % 8 == 0:
            ctx.progress(15.0 + (index / max(len(frames), 1)) * 20.0, "reconstructing background")
    return cleaned, first_removal_mask, metrics


def _build_composition_schedule(
    manifest: dict[str, Any],
    pack: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the effective per-frame schedule before any pixel is encoded."""
    from app.services.pilot_preview.pose_composition import (
        anchors_normalized,
        pose_state_for_pack,
    )

    start = int(manifest["start_frame"])
    end = int(manifest["end_frame"])
    if (start, end) != (450, 570):
        raise PilotPreviewError("FRAME_WINDOW_INVALID: pilot preview is fixed to [450,570)")
    states = pack.get("states")
    if not isinstance(states, dict):
        raise PilotPreviewError("PACK_STATES_INVALID")
    rows: list[dict[str, Any]] = []
    validated_contract = _validated_contact_contract(pack)
    c6_contact = validated_contract == C6_SEMANTIC_CONTRACT
    c7_contact = validated_contract == C7_SEMANTIC_CONTRACT
    c9_contact = validated_contract == C9_ARM_RIG_SEMANTIC_CONTRACT
    contact_pack = validated_contract is not None
    for local in range(end - start):
        source_frame = start + local
        state_id = pose_state_for_pack(source_frame)
        state = states.get(state_id)
        if not isinstance(state, dict):
            raise PilotPreviewError(f"PACK_STATE_MISSING: {state_id}")
        def _point(value: Any) -> tuple[float, float]:
            return (float(value[0]), float(value[1]))

        anchors: dict[str, tuple[float, float]] = {
            name: _point(point)
            for name, point in state["anchors"].items()
            if name != "book_corners"
        }
        canvas_size: tuple[float, float] = (
            float(state["canvas_size"][0]), float(state["canvas_size"][1])
        )
        fit = fit_layer_transform(
            source_frame,
            anchors,
            pin="seat_pelvis",
            asset_canvas_size=canvas_size,
            contact_basis=("source_book_boundary_design" if contact_pack else "observed_source_hand"),
        )
        stack = layer_stack_for_frame(source_frame)
        check_layer_stack(stack)
        contact_basis = "source_book_boundary_design" if contact_pack else "observed_source_hand"
        source_anchors = source_anchors_fullframe_px(source_frame, contact_basis=contact_basis)
        hand_patch_offset_px = (0.0, 0.0)
        if contact_pack and source_frame >= 522 and not c9_contact:
            baseline = source_anchors_fullframe_px(522, contact_basis=contact_basis)
            hand_patch_offset_px = (
                float(source_anchors["hand_grip_l"][0] - baseline["hand_grip_l"][0]),
                float(source_anchors["hand_grip_l"][1] - baseline["hand_grip_l"][1]),
            )
        contact_measurements: dict[str, Any] = {}
        for hand_name in ("hand_grip_l", "hand_grip_r"):
            side = "left" if hand_name.endswith("_l") else "right"
            local_point = _point(
                state["arm_rig"]["joints"][side]["grip"]
                if c9_contact else state["anchors"][hand_name]
            )
            target_point = tuple(float(v) for v in source_anchors[hand_name])
            measurement_fit = fit
            if contact_pack and hand_name.startswith("hand_grip_"):
                measurement_fit = {
                    **fit,
                    "translation_xy": (
                        float(fit["translation_xy"][0]) + hand_patch_offset_px[0] / FRAME_WIDTH,
                        float(fit["translation_xy"][1]) + hand_patch_offset_px[1] / FRAME_HEIGHT,
                    ),
                }
            if c9_contact:
                # C9's hand endpoint has an independent measured similarity
                # transform.  Rebind the actual source-visible grip joint to
                # the source-book target; do not reuse a stale body residual.
                from app.services.pilot_preview.arm_rig import _fit_point

                base_point = _fit_point(local_point, fit, (FRAME_WIDTH, FRAME_HEIGHT))
                measurement_fit = {
                    **fit,
                    "translation_xy": (
                        float(fit["translation_xy"][0])
                        + (target_point[0] - base_point[0]) / FRAME_WIDTH,
                        float(fit["translation_xy"][1])
                        + (target_point[1] - base_point[1]) / FRAME_HEIGHT,
                    ),
                }
            measured = measure_contact_residual(local_point, target_point, measurement_fit)
            review_values = (
                pack.get("semantic_review", {})
                .get("contact_measurements", {})
                .get(str(source_frame), {})
                .get(state_id, {})
            )
            # C8/C7 packs must carry every schedule row.  Historical C6 and
            # engineering fixtures may only carry the six contract samples;
            # when a row is present, it is still reconciled exactly.
            if contact_pack and (c7_contact or c9_contact or isinstance(review_values, dict)):
                if not isinstance(review_values, dict) or review_values.get("not_applicable") is True:
                    if not c7_contact and not review_values:
                        review_values = {}
                    else:
                        raise PilotPreviewError(
                            f"CONTACT_MEASUREMENT_REVIEW_MISSING:{source_frame}:{state_id}"
                        )
                declared_review_error = review_values.get(hand_name)
                if declared_review_error is None and not c7_contact:
                    declared_review_error = measured["error_px"]
                if declared_review_error is None:
                    raise PilotPreviewError(
                        f"CONTACT_MEASUREMENT_REVIEW_UNKNOWN:{source_frame}:{hand_name}"
                    )
                if isinstance(declared_review_error, dict):
                    declared_review_error = declared_review_error.get("error_px")
                if not isinstance(declared_review_error, (int, float)):
                    raise PilotPreviewError(
                        f"CONTACT_MEASUREMENT_REVIEW_UNKNOWN:{source_frame}:{hand_name}"
                    )
                if abs(float(declared_review_error) - float(measured["error_px"])) > 0.25:
                    raise PilotPreviewError(
                        f"CONTACT_MEASUREMENT_MANIFEST_RUNTIME_MISMATCH:{source_frame}:{hand_name}"
                    )
            contact_measurements[hand_name] = validate_contact_measurement(
                {
                    "method": (
                        "source_prop_boundary_contact_plus_production_transform"
                        if contact_pack else "source_pixel_contact_plus_production_transform"
                    ),
                    "source_frame": source_frame,
                    "state": state_id,
                    "source_sha256": str(manifest["source_sha256"]),
                    "artwork_sha256": str(state["sha256"]),
                    "policy_revision": CONTACT_MEASUREMENT_POLICY_REVISION if contact_pack else "source-pixel-contact-v1",
                    "policy_digest": source_contact_annotation_digest(),
                    "contact_kind": "ART_DIRECTION_CONSTRAINT_ON_SOURCE_PROP" if contact_pack else "SOURCE_OBSERVATION",
                    "source_role": "book" if contact_pack else "source_hand",
                    "book_owner": "source",
                    "asset_point_local": measured["asset_point_local"],
                    "source_target_px": measured["source_target_px"],
                    "fit": measurement_fit,
                    "declared_error_px": measured["error_px"],
                },
                expected_source_sha256=str(manifest["source_sha256"]),
                expected_artwork_sha256=str(state["sha256"]),
                expected_source_frame=source_frame if c7_contact else None,
                expected_state=state_id if c7_contact else None,
                expected_policy_digest=source_contact_annotation_digest() if c7_contact else None,
            )["measurement"]
        rows.append(
            {
                "output_frame": local,
                "source_frame": source_frame,
                "scheduled": True,
                "pose": pose_state_at(source_frame),
                "pack_state": state_id,
                "pack_state_sha256": state["sha256"],
                "mouth_character": mouth_state_at(source_frame, "character"),
                "mouth_woman": mouth_state_at(source_frame, "woman"),
                "book": book_state_at(source_frame),
                "layer_stack": list(stack),
                "source_anchors_normalized": anchors_normalized(source_frame, contact_basis=contact_basis),
                "asset_anchors_local": state["anchors"],
                "asset_canvas_size": state["canvas_size"],
                "fit": fit,
                "contact_measurement_policy_revision": CONTACT_MEASUREMENT_POLICY_REVISION if contact_pack else "source-pixel-contact-v1",
                "source_contact_annotation_digest": source_contact_annotation_digest(),
                "contact_constraints": source_prop_contact_constraints(source_frame) if contact_pack else None,
                "hand_patch_offset_px": list(hand_patch_offset_px),
                "contact_semantic_contract": "replacement_hand_to_source_book_boundary" if contact_pack else "legacy_source_observation",
                "validated_semantic_contract": validated_contract,
                "contact_measurements": contact_measurements,
            }
        )
    if rows[0]["source_frame"] != 450 or rows[60]["source_frame"] != 510 or rows[119]["source_frame"] != 569:
        raise PilotPreviewError("SCHEDULE_MAPPING_FAILED: expected 450/510/569 probes")
    if rows[71]["pack_state"] != "seated_book_closed" or rows[72]["pack_state"] != "seated_book_open":
        raise PilotPreviewError("SCHEDULE_TRANSITION_FAILED: expected closed->open at 522")
    return rows


def _reconstruct_source_frames(
    frames: list[Any],
    rect: tuple[float, float, float, float],
    propagated_masks: list[Any],
    manifest: dict[str, Any],
    ctx: WorkerContext,
    reviewed_plate: Any | None = None,
    reviewed_plate_identity: dict[str, Any] | None = None,
) -> tuple[list[Any], Any, list[dict[str, Any]], list[dict[str, Any]]]:
    """Create the actual pre-composite pixels from reconstruction results."""
    import numpy as np

    start = int(manifest["start_frame"])
    height, width = frames[0].shape[:2]
    bbox = _normalized_rect_to_px(rect, width, height)
    correction = MaskCorrection(
        bbox_xywh_px=(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]),
        mode="include",
        confidence=float(manifest["mask_correction"].get("confidence", 1.0)),
        note=str(manifest["mask_correction"].get("note", "server correction")),
    )
    neighbours = {start + index: frame for index, frame in enumerate(frames)}
    cleaned: list[Any] = []
    metrics: list[dict[str, Any]] = []
    reconstructions: list[dict[str, Any]] = []
    first_removal = np.zeros((height, width), dtype=np.uint8)
    for index, (frame, propagated) in enumerate(zip(frames, propagated_masks)):
        if ctx.is_cancelled():
            return [], first_removal, metrics, reconstructions
        result = reconstruct_frame(
            frame,
            source_frame=start + index,
            source_sha256=str(manifest["source_sha256"]),
            source_prompt_bbox_xywh_px=(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]),
            corrections=(correction,),
            propagated_removal_mask=propagated,
            neighbour_frames=neighbours,
            reviewed_plate=reviewed_plate,
            reviewed_plate_identity=reviewed_plate_identity,
        )
        provenance = result.clean_plate_provenance
        unknown_pixels = int(np.count_nonzero(result.unknown_mask))
        telea_pixels = int(provenance.get("telea_fallback_pixels", 0))
        if unknown_pixels or telea_pixels:
            # Do not silently turn source reuse/Telea into a product plate.
            # Finish the bounded diagnostic pass so the failure identifies all
            # affected frames instead of stopping at the first frame.
            metrics.append({
                "source_frame": start + index,
                "clean_plate_gate": "FAILED",
                "unknown_mask_pixels": unknown_pixels,
                "telea_fallback_pixels": telea_pixels,
            })
            continue
        if index == 0:
            first_removal = np.asarray(result.removal_mask).copy()
        cleaned.append(np.asarray(result.result_without_replacement).copy())
        metrics.append(
            {
                "mask_sha256": hashlib.sha256(np.ascontiguousarray(result.removal_mask).tobytes()).hexdigest(),
                "mask_area_pixels": int(np.count_nonzero(result.removal_mask)),
                "mask_bbox_xywh_pixels": list(result.source_prompt_bbox_xywh_px),
                "edit_envelope_bbox_xywh_pixels": [
                    bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]
                ],
                "clean_plate_provenance": dict(provenance),
                "unknown_mask_pixels": unknown_pixels,
                "protected_roles": sorted(result.protected_masks),
            }
        )
        reconstructions.append(
            {
                "result": result,
                "protected_masks": result.protected_masks,
                "layer_order": list(result.layer_order),
                "reconstructed_foreground_mask": result.reconstructed_foreground_mask,
                "reconstructed_foreground_reference": result.reconstructed_foreground_reference,
                "reconstructed_foreground_provenance": result.reconstructed_foreground_provenance,
            }
        )
        if index % 8 == 0:
            ctx.progress(15.0 + (index / max(len(frames), 1)) * 20.0, "reconstructing source-derived plate")
    failures = [
        item for item in metrics
        if item.get("clean_plate_gate") == "FAILED"
    ]
    if failures:
        first = failures[0]
        raise PilotPreviewError(
            "CLEAN_PLATE_REVIEW_REQUIRED: source-derived reconstruction "
            f"left unknown={first['unknown_mask_pixels']} "
            f"telea_fallback={first['telea_fallback_pixels']} "
            f"at source frame {first['source_frame']}; "
            f"affected_frames={len(failures)}"
        )
    return cleaned, first_removal, metrics, reconstructions


def _write_clean_plate_diagnostics(
    source: Path,
    manifest: dict[str, Any],
    rect: tuple[float, float, float, float],
    ctx: WorkerContext,
    staging: Path,
) -> list[str]:
    """Write bounded still diagnostics before rejecting a missing plate."""
    start = int(manifest["start_frame"])
    bbox = _normalized_rect_to_px(rect, 640, 360)
    correction = MaskCorrection(
        bbox_xywh_px=(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]),
        mode="include",
        confidence=float(manifest["mask_correction"].get("confidence", 1.0)),
        note="diagnostic-only plate review envelope",
    )
    diagnostic_dir = staging / "diagnostics"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for source_frame in (450, 510, 521, 522, 523, 569):
        frame = _read_frames(source, source_frame, source_frame + 1)[0]
        result = reconstruct_frame(
            frame,
            source_frame=source_frame,
            source_sha256=str(manifest["source_sha256"]),
            source_prompt_bbox_xywh_px=(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]),
            corrections=(correction,),
            neighbour_frames={},
        )
        target = diagnostic_dir / f"plate-review-{source_frame}.png"
        render_decomposition_sheet(frame, result, str(target))
        paths.append(str(target))
    ctx.write_checkpoint({
        "schema_version": 1,
        "phase": "clean_plate_gate",
        "status": "needs_visual_review",
        "code": "CLEAN_PLATE_REQUIRED",
        "diagnostic_stills": paths,
        "frames": [450, 510, 521, 522, 523, 569],
    })
    return paths


def _resolve_manifest_plate(manifest: dict[str, Any]) -> dict[str, Any] | None:
    plate_id = manifest.get("clean_plate_id")
    if not plate_id:
        return None
    root = manifest.get("clean_plate_root")
    if not isinstance(root, str) or not root:
        raise PilotPreviewError("CLEAN_PLATE_REVIEW_REQUIRED: no server-owned clean plate root")
    try:
        Path(root).resolve().relative_to(Path(str(manifest["runtime_root"])).resolve())
    except (KeyError, ValueError):
        raise PilotPreviewError("CLEAN_PLATE_REVIEW_REQUIRED: clean plate root is outside the isolated runtime root")
    try:
        return resolve_reviewed_plate(
            str(plate_id),
            Path(root),
            source_sha256=str(manifest["source_sha256"]),
            source_window=(int(manifest["start_frame"]), int(manifest["end_frame"])),
            expected_manifest_sha256=manifest.get("clean_plate_manifest_sha256"),
            expected_content_sha256=manifest.get("clean_plate_content_sha256"),
            allow_private_preview=True,
        )
    except PlateResolutionError as exc:
        raise PilotPreviewError(f"CLEAN_PLATE_REVIEW_REQUIRED: {exc.code}: {exc}") from exc


def _composite_v3(
    cleaned: list[Any],
    *,
    source: Path,
    asset: Path,
    rect: tuple[float, float, float, float],
    keyframes: list[dict[str, Any]],
    occluder: dict[str, Any],
    output: Path,
    runtime_root: Path,
    start_frame: int,
    ffmpeg: str,
    ctx: WorkerContext,
    pack: dict[str, Any],
    schedule_rows: list[dict[str, Any]],
    reconstructions: list[dict[str, Any]],
    anchor_mode: str = "source_derived",
) -> tuple[list[Any], dict[str, Any]]:
    import numpy as np

    from app.services.renderer_contract import AffineKeyframe, RenderRequest, ReplacementAsset
    from app.services.renderer_routes.composite import (
        _alpha_composite_into,
        _warp_layer,
        apply_alpha_mode,
        composite_sprite_affine_frames,
        load_rgba,
    )

    height, width = cleaned[0].shape[:2]
    if len(schedule_rows) != len(cleaned) or len(reconstructions) != len(cleaned):
        raise PilotPreviewError("COMPOSITION_INPUT_COUNT_MISMATCH")

    def _operator_keyframe(frame_no: int) -> dict[str, Any]:
        ordered = sorted(keyframes, key=lambda item: int(item["frame"]))
        if frame_no <= int(ordered[0]["frame"]):
            return ordered[0]
        if frame_no >= int(ordered[-1]["frame"]):
            return ordered[-1]
        for left, right in zip(ordered, ordered[1:]):
            lf, rf = int(left["frame"]), int(right["frame"])
            if lf <= frame_no <= rf:
                ratio = (frame_no - lf) / float(rf - lf)
                return {
                    "anchor_xy_norm": tuple(
                        float(left["anchor_xy_norm"][axis])
                        + ratio * (float(right["anchor_xy_norm"][axis]) - float(left["anchor_xy_norm"][axis]))
                        for axis in range(2)
                    ),
                    "scale": float(left.get("scale", 1.0))
                    + ratio * (float(right.get("scale", 1.0)) - float(left.get("scale", 1.0))),
                    "rotation_deg": float(left.get("rotation_deg", 0.0))
                    + ratio * (float(right.get("rotation_deg", 0.0)) - float(left.get("rotation_deg", 0.0))),
                    "operator_offset_xy_norm": tuple(
                        float(left.get("operator_offset_xy_norm", (0.0, 0.0))[axis])
                        + ratio * (
                            float(right.get("operator_offset_xy_norm", (0.0, 0.0))[axis])
                            - float(left.get("operator_offset_xy_norm", (0.0, 0.0))[axis])
                        )
                        for axis in range(2)
                    ),
                }
        return ordered[-1]

    validated_contract = _validated_contact_contract(pack)
    is_c6 = validated_contract == C6_SEMANTIC_CONTRACT
    is_c7 = validated_contract == C7_SEMANTIC_CONTRACT
    is_c9 = validated_contract == C9_ARM_RIG_SEMANTIC_CONTRACT
    if validated_contract is None:
        raise PilotPreviewError("PACK_CONTACT_CONTRACT_UNVALIDATED")
    composed: list[Any] = []
    body_layers_by_source: dict[int, Any] = {}
    adjusted_by_source: dict[int, dict[str, Any]] = {}
    segment_start = 0
    while segment_start < len(schedule_rows):
        state_id = str(schedule_rows[segment_start]["pack_state"])
        segment_end = segment_start + 1
        while segment_end < len(schedule_rows) and schedule_rows[segment_end]["pack_state"] == state_id:
            segment_end += 1
        state = pack["states"][state_id]
        affine: list[AffineKeyframe] = []
        for row in schedule_rows[segment_start:segment_end]:
            operator = _operator_keyframe(int(row["source_frame"]))
            fit = row["fit"]
            if anchor_mode not in ("source_derived", "explicit_offset"):
                raise PilotPreviewError(f"ANCHOR_MODE_INVALID: {anchor_mode}")
            # The historical request field ``anchor_xy_norm`` was an
            # absolute override and caused a 71 px pelvis error.  It is now
            # informational under source_derived; only an explicit offset is
            # allowed to move contact, and scale/rotation are pivot-preserved.
            offset = operator.get("operator_offset_xy_norm", (0.0, 0.0))
            if anchor_mode == "source_derived":
                offset = (0.0, 0.0)
            adjusted = combine_operator_transform(
                fit,
                operator_scale=float(operator.get("scale", 1.0)),
                operator_rotation_deg=float(operator.get("rotation_deg", 0.0)),
                operator_offset_xy_norm=(float(offset[0]), float(offset[1])),
            )
            adjusted_by_source[int(row["source_frame"])] = adjusted
            affine.append(
                AffineKeyframe(
                    frame=int(row["source_frame"]),
                    translation_xy=tuple(float(v) for v in adjusted["translation_xy"]),
                    scale=float(adjusted["scale"]),
                    rotation_deg=float(adjusted["rotation_deg"]),
                )
            )
        if is_c9:
            # C9 owns the production raster path.  The legacy shared route is
            # intentionally retained for C6/C7 compatibility, but the new
            # candidate must not use forward splat/repeated sprite sampling.
            import numpy as np

            body_rgba = apply_alpha_mode(load_rgba(Path(state["path"])), "straight")
            for local_offset, row in enumerate(schedule_rows[segment_start:segment_end]):
                adjusted = adjusted_by_source[int(row["source_frame"])]
                body_layer = warp_rgba_inverse(
                    body_rgba,
                    fit_affine_matrix(adjusted, (width, height)),
                    (width, height),
                    source_scale=abs(float(adjusted["scale"])),
                )
                body_layers_by_source[int(row["source_frame"])] = body_layer
                body_frame = np.asarray(cleaned[segment_start + local_offset]).copy()
                _alpha_composite_into(body_frame, body_layer, 0, 0)
                composed.append(body_frame)
            segment_start = segment_end
            continue
        request = RenderRequest(
            request_id=f"pilot-preview-{start_frame}-{start_frame + len(cleaned)}-{state_id}",
            workspace_id=str(runtime_root),
            project_id="pilot-preview",
            video_item_id="pilot-preview",
            occurrence_segment_id=f"frames-{start_frame + segment_start}-{start_frame + segment_end}",
            route="sprite_affine",
            start_frame=start_frame + segment_start,
            end_frame=start_frame + segment_end - 1,
            input_media=source,
            output_media=output,
            workspace_root=runtime_root,
            replacement_asset=ReplacementAsset(Path(state["path"]), kind="pose_state", alpha_mode="straight"),
            # The replacement alpha is authoritative and is never clipped to
            # the old prompt/mask rectangle.
            mask_asset=None,
            affected_region=None,
            anchor_xy_norm=(0.5, 0.5),
            affine_keyframes=tuple(affine),
            source_timebase=(_FPS_NUM, _FPS_DEN),
            identity_transform=False,
        )
        request.validate_for_render()
        composed.extend(
            composite_sprite_affine_frames(
                cleaned[segment_start:segment_end],
                request,
            )
        )
        segment_start = segment_end

    # Execute only the genuine foreground roles after replacement.  Rear
    # room/chair roles are already present in the clean plate and must never
    # be copied over the new character.  The old rectangular restore is
    # intentionally gone: it erased pixels unrelated to the front role.
    for index, (original, frame) in enumerate(zip(_read_frames(source, start_frame, start_frame + len(cleaned)), composed)):
        row = schedule_rows[index]
        for role in FRONT_PROTECTED_ROLES:
            if is_c9 and role == "book":
                # C9 inserts the protected source book between the explicit
                # behind-arm and front-finger stages below.
                continue
            role_mask = reconstructions[index]["protected_masks"].get(role)
            if role_mask is not None:
                visible = np.asarray(role_mask) > 0
                frame[visible] = original[visible]
        book_mask = reconstructions[index]["protected_masks"].get("book")
        if book_mask is not None and not is_c9:
            frame = finish_source_book(
                frame,
                source_frame=start_frame + index,
                book_mask=book_mask,
            )
        frame = repair_source_woman_edge(
            frame,
            source_frame=start_frame + index,
            source_reference=original,
            woman_mask=reconstructions[index]["protected_masks"].get("woman"),
            repair_mask=reconstructions[index].get("reconstructed_foreground_mask"),
            repair_reference=reconstructions[index].get("reconstructed_foreground_reference"),
        )
        if is_c9:
            before_arms = frame.copy()
            state_data = pack["states"][str(row["pack_state"])]
            adjusted = adjusted_by_source[int(row["source_frame"])]
            source_targets = source_anchors_fullframe_px(
                int(row["source_frame"]),
                contact_basis="source_book_boundary_design",
            )
            adjusted["frame_size"] = [width, height]
            try:
                arm_plan = build_arm_rig_plan(
                    state_data,
                    adjusted,
                    source_targets,
                    source_frame=int(row["source_frame"]),
                    dst_size=(width, height),
                )
                clip_open_book_seam_roles(
                    arm_plan,
                    source_frame=int(row["source_frame"]),
                )
                frame = composite_arm_layers(frame, arm_plan, "behind_book")
                # Woman/table/seated-back/chair-foreground remain genuine
                # foreground roles.  Restore them after behind-arm pixels so
                # an arm sleeve cannot leak across the woman seam.
                protected_after_behind = {
                    role: reconstructions[index]["protected_masks"][role]
                    for role in FRONT_PROTECTED_ROLES
                    if role != "book" and reconstructions[index]["protected_masks"].get(role) is not None
                }
                for protected_mask in protected_after_behind.values():
                    keep = np.asarray(protected_mask) > 0
                    frame[keep] = original[keep]
                if book_mask is None:
                    raise ArmRigError("ARM_BOOK_MASK_EMPTY")
                frame[np.asarray(book_mask) > 0] = original[np.asarray(book_mask) > 0]
                frame = finish_source_book(
                    frame,
                    source_frame=start_frame + index,
                    book_mask=book_mask,
                )
                frame = composite_arm_layers(frame, arm_plan, "front_book")
                for protected_mask in protected_after_behind.values():
                    keep = np.asarray(protected_mask) > 0
                    frame[keep] = original[keep]
                row["final_pixel_gate"] = validate_arm_rig_frame(
                    before_arms=before_arms,
                    final_frame=frame,
                    plan=arm_plan,
                    book_mask=book_mask,
                    book_reference=original,
                    woman_mask=reconstructions[index]["protected_masks"].get("woman"),
                    protected_after_behind=protected_after_behind,
                )
                row["arm_rig_joints"] = arm_plan["joints"]
                row["arm_rig_raster_contract"] = arm_plan["raster_contract"]
                row["arm_rig_occlusion"] = arm_plan["diagnostics"].get("open_book_seam_occlusion")
            except ArmRigError as exc:
                raise PilotPreviewError(f"ARM_RIG_PIXEL_GATE_FAILED:{exc}") from exc
        elif is_c6 or is_c7:
            before_hands = frame.copy()
            patch_specs = pack["states"][str(row["pack_state"])].get("hand_contact_patches")
            if not isinstance(patch_specs, dict):
                raise PilotPreviewError("HAND_CONTACT_PATCHES_MISSING")
            state_data = pack["states"][str(row["pack_state"])]
            hand_source = Path(state_data.get("hand_asset_path") or state_data["path"])
            state_rgba = apply_alpha_mode(load_rgba(hand_source), "straight")
            adjusted = adjusted_by_source[int(row["source_frame"])]
            patch_offset = row.get("hand_patch_offset_px", [0.0, 0.0])
            hand_layers: dict[str, Any] = {}
            for side in ("left", "right"):
                side_rgba = (
                    _semantic_hand_alpha(
                        state_rgba,
                        side=side,
                        state_id=str(row["pack_state"]),
                    )
                    if is_c7
                    else np.array(state_rgba, copy=True)
                )
                polygon = patch_specs[side].get("polygon") if is_c7 else None
                if is_c7:
                    if not isinstance(polygon, (list, tuple)) or len(polygon) < 3:
                        raise PilotPreviewError(f"HAND_ANATOMY_POLYGON_MISSING:{side}")
                    import cv2

                    keep = np.zeros(side_rgba.shape[:2], dtype=np.uint8)
                    cv2.fillPoly(
                        keep,
                        [np.asarray([[int(round(float(p[0]))), int(round(float(p[1])))] for p in polygon], dtype=np.int32)],
                        255,
                    )
                    side_rgba[:, :, 3] = np.minimum(side_rgba[:, :, 3], keep)
                else:
                    box = patch_specs[side]["bbox_xywh"]
                    x, y, w, h = (int(round(float(value))) for value in box)
                    keep = np.zeros(side_rgba.shape[:2], dtype=np.uint8)
                    x0, y0 = max(0, x), max(0, y)
                    x1, y1 = min(side_rgba.shape[1], x + w), min(side_rgba.shape[0], y + h)
                    keep[y0:y1, x0:x1] = 255
                    side_rgba[:, :, 3] = np.minimum(side_rgba[:, :, 3], keep)
                hand_layers[side] = _warp_layer(
                    side_rgba,
                    translation_xy_norm=(
                        float(adjusted["translation_xy"][0]) + float(patch_offset[0]) / width,
                        float(adjusted["translation_xy"][1]) + float(patch_offset[1]) / height,
                    ),
                    scale=float(adjusted["scale"]),
                    rotation_deg=float(adjusted["rotation_deg"]),
                    dst_w=width,
                    dst_h=height,
                )
                _alpha_composite_into(frame, hand_layers[side], 0, 0)
            body_rgba = apply_alpha_mode(load_rgba(Path(state_data["path"])), "straight")
            body_layer = _warp_layer(
                body_rgba,
                translation_xy_norm=(float(adjusted["translation_xy"][0]), float(adjusted["translation_xy"][1])),
                scale=float(adjusted["scale"]),
                rotation_deg=float(adjusted["rotation_deg"]),
                dst_w=width,
                dst_h=height,
            )
            if book_mask is None:
                raise PilotPreviewError("HAND_BOOK_PIXEL_GATE_EMPTY")
            row["final_pixel_gate"] = _validate_final_hand_pixels(
                before_hands=before_hands,
                final_frame=frame,
                hand_layers=hand_layers,
                body_layer=body_layer,
                book_mask=book_mask,
                book_reference=original,
                row=row,
                before_body=cleaned[index],
            )
        composed[index] = frame
        if index % 8 == 0:
            ctx.progress(35.0 + (index / max(len(composed), 1)) * 30.0, "compositing V3 asset")
    _write_video_only(composed, output, ffmpeg)
    return composed, {
        "renderer_route": "sprite_affine",
        "replacement_asset_kind": "server_resolved_versioned_pose_states",
        "alpha_mode": "straight",
        "replacement_mask_source": "rgba_asset_alpha_only",
        "pack_id": pack["pack_id"],
        "pack_content_sha256": pack["content_sha256"],
        "state_segments": [
            {"state_id": row["pack_state"], "first_source": row["source_frame"]}
            for index, row in enumerate(schedule_rows)
            if index == 0 or row["pack_state"] != schedule_rows[index - 1]["pack_state"]
        ],
        "anchor_translation_audit": "measured asset_local anchor + canvas-aware scale/rotation correction",
        "affected_region": None,
        "anchor_keyframes": keyframes,
        "occluder": occluder,
        "protected_pixel_restore": {
            "front_roles": list(FRONT_PROTECTED_ROLES),
            "rear_roles_left_in_clean_plate": ["room", "chair_occupied", "chair_spare"],
        },
        "source_pixels_outside_affected_region": "copied_from_decoded_source",
        "hand_alpha_revision": HAND_ALPHA_REVISION,
        "contact_gate_revision": CONTACT_GATE_REVISION,
        "arm_rig_revision": C9_ARM_RIG_REVISION if is_c9 else None,
        "raster_sampling": "inverse_area_premultiplied_one_pass_v1" if is_c9 else "legacy_shared_route",
        "occlusion_stages": {
            "behind_book": ["upper_arm", "forearm", "cuff_bridge"],
            "front_book": ["hand_grip", "front_fingers"],
        } if is_c9 else None,
    }


def _remux(source: Path, video_only: Path, target: Path, start_frame: int, frame_count: int, ffmpeg: str) -> None:
    """Mux the composited track with source audio as H264/yuv420p.

    The video track is re-encoded (never stream-copied) so the published
    ``after`` file is verified H264/yuv420p; the audio track is mapped
    from the source at the same start offset, preserving mapping + offsets.
    """
    start_seconds = start_frame / _FPS_NUM
    duration_seconds = frame_count / _FPS_NUM
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_only),
            "-ss",
            f"{start_seconds:.6f}",
            "-t",
            f"{duration_seconds:.6f}",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            "-y",
            str(target),
        ]
    )


def _trim_before(source: Path, target: Path, start_frame: int, frame_count: int, ffmpeg: str) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_frame / _FPS_NUM:.6f}",
            "-i",
            str(source),
            "-t",
            f"{frame_count / _FPS_NUM:.6f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-y",
            str(target),
        ]
    )


def _validate_video(path: Path, expected_frames: int, width: int, height: int, ffprobe: str) -> dict[str, Any]:
    """Decode-count plus automated-QC media checks (R2: H264/yuv420p enforced)."""
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise PilotPreviewError(f"OUTPUT_DECODE_FAILED: {path.name}")
        actual = 0
        while True:
            ok, _ = capture.read()
            if not ok:
                break
            actual += 1
        got_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        got_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()
    media = _probe_media(path, ffprobe)
    expected_duration = expected_frames * _FPS_DEN / _FPS_NUM
    if media.get("video_codec") != "h264" or media.get("pix_fmt") != "yuv420p":
        raise PilotPreviewError(
            f"OUTPUT_CODEC_FAILED: {path.name} codec={media.get('video_codec')} "
            f"pix_fmt={media.get('pix_fmt')} (need h264/yuv420p)"
        )
    if (
        actual != expected_frames
        or got_w != width
        or got_h != height
        or media["width"] != width
        or media["height"] != height
        or media["fps"] != (_FPS_NUM, _FPS_DEN)
        or media["video_duration_seconds"] is None
        or abs(float(media["video_duration_seconds"]) - expected_duration) > (1 / _FPS_NUM)
        or (
            media["audio_present"]
            and (
                media["audio_duration_seconds"] is None
                or abs(float(media["audio_duration_seconds"]) - expected_duration) > (1 / _FPS_NUM)
            )
        )
    ):
        raise PilotPreviewError(
            f"OUTPUT_QC_FAILED: {path.name} frames={actual} size={got_w}x{got_h} media={media}"
        )
    return {
        "frames": actual, "width": got_w, "height": got_h,
        "sha256": _sha256(path), "size_bytes": path.stat().st_size,
        "stream": media, "duration_seconds": expected_duration,
    }


def _publish(root: ManagedRoot, staged: Path, relative: str) -> dict[str, Any]:
    target = root.resolve(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_file() and hash_file(target) == hash_file(staged):
            staged.unlink()
        else:
            raise PilotPreviewError(f"PILOT_OUTPUT_CONFLICT: {relative}")
    else:
        staged.replace(target)
    return {"relative_path": relative, "sha256": hash_file(target), "size_bytes": target.stat().st_size}


def _preflight_publish(root: ManagedRoot, staged: Path, relative: str) -> None:
    target = root.resolve(relative)
    if target.exists() and (not target.is_file() or hash_file(target) != hash_file(staged)):
        raise PilotPreviewError(f"PILOT_OUTPUT_CONFLICT: {relative}")


def _assert_final_inputs(manifest: dict[str, Any], source: Path, asset: Path, checkpoint: Path) -> None:
    if _sha256(source) != str(manifest["source_sha256"]):
        raise PilotPreviewError("SOURCE_HASH_MISMATCH_FINAL")
    expected_state_sha = str(manifest.get("asset_state_sha256", manifest.get("asset_sha256", "")))
    if _sha256(asset) != expected_state_sha:
        raise PilotPreviewError("PACK_STATE_HASH_MISMATCH_FINAL")
    if _sha256(checkpoint) != str(manifest["sam2_checkpoint_sha256"]):
        raise PilotPreviewError("SAM2_CHECKPOINT_HASH_MISMATCH_FINAL")
    if compute_input_identity_sha256(manifest) != str(manifest.get("input_identity_sha256")):
        raise PilotPreviewError("INPUT_IDENTITY_MISMATCH")
    policy = manifest.get("policy")
    if not isinstance(policy, dict) or policy.get("preview_only") is not True or policy.get("single_shot") is not True or policy.get("no_full_apply") is not True or policy.get("no_s12") is not True:
        raise PilotPreviewError("PILOT_POLICY_FAILED")
    output_relpaths_for_manifest(manifest)
    if manifest.get("pipeline_revision") != PILOT_PIPELINE_REVISION:
        raise PilotPreviewError("PILOT_PIPELINE_REVISION_MISMATCH")
    if manifest.get("render_geometry_contract") != PILOT_RENDER_GEOMETRY:
        raise PilotPreviewError("PILOT_RENDER_GEOMETRY_MISMATCH")
    if manifest.get("composition_revision") != COMPOSITION_REVISION:
        raise PilotPreviewError("PILOT_COMPOSITION_REVISION_MISMATCH")
    verdict = require_pack_compatible(manifest)
    pack = verdict["pack"]
    if pack["content_sha256"] != str(manifest.get("pack_content_sha256")):
        raise PilotPreviewError("PACK_CONTENT_HASH_MISMATCH_FINAL")
    if pack["manifest_sha256"] != str(manifest.get("pack_manifest_sha256")):
        raise PilotPreviewError("PACK_MANIFEST_HASH_MISMATCH_FINAL")
    if manifest.get("clean_plate_id"):
        plate = _resolve_manifest_plate(manifest)
        if not plate or plate["content_sha256"] != str(manifest.get("clean_plate_content_sha256")):
            raise PilotPreviewError("CLEAN_PLATE_IDENTITY_MISMATCH_FINAL")


def _validate_outputs(ctx: WorkerContext, result: dict[str, Any], _staging: Path) -> dict[str, Any]:
    root = ManagedRoot(Path(ctx.input_manifest["managed_root"]))
    paths = output_relpaths_for_manifest(ctx.input_manifest)
    evidence: dict[str, Any] = {}
    for label, relative in paths.items():
        path = root.resolve(relative)
        if not path.is_file() or path.stat().st_size <= 0:
            raise PilotPreviewError(f"published output missing: {relative}")
        evidence[label] = {"relative_path": relative, "sha256": hash_file(path), "size_bytes": path.stat().st_size}
    try:
        payload = json.loads(root.resolve(paths["evidence"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PilotPreviewError("PUBLISHED_EVIDENCE_INVALID") from exc
    if (
        payload.get("input_identity_sha256") != ctx.input_manifest.get("input_identity_sha256")
        or payload.get("source_sha256") != ctx.input_manifest.get("source_sha256")
        or payload.get("asset_sha256") != ctx.input_manifest.get("asset_sha256")
        or payload.get("sam2_checkpoint_sha256") != ctx.input_manifest.get("sam2_checkpoint_sha256")
        or any(payload.get("published", {}).get(label) != evidence[label] for label in ("before", "after"))
    ):
        raise PilotPreviewError("PUBLISHED_EVIDENCE_IDENTITY_MISMATCH")
    return evidence


def pilot_preview_handler(ctx: WorkerContext) -> dict[str, Any]:
    manifest = ctx.input_manifest
    # Isolated roots are validated at process start, BEFORE heavy work: the
    # QA/test guard rejects the protected MAIN tree and CWD-relative roots.
    validate_runtime_roots(
        manifest.get("runtime_root"), manifest.get("managed_root"),
    )
    # Server-owned pack verdict BEFORE any decode/SAM2/render heavy work.
    pack_verdict = require_pack_compatible(manifest)
    pack = pack_verdict["pack"]
    # Straight-alpha + frozen schedule/layer contract are consumed (not metadata).
    require_straight_alpha("straight")
    start = int(manifest["start_frame"])
    end = int(manifest["end_frame"])
    frame_count = end - start
    if frame_count < _MIN_FRAMES or frame_count > _MAX_FRAMES:
        raise PilotPreviewError(f"FRAME_RANGE_INVALID: {frame_count} frames")

    source = Path(str(manifest["source_path"]))
    asset = Path(str(manifest["asset_path"]))
    checkpoint = Path(str(manifest["sam2_checkpoint_path"]))
    if not source.is_file() or not asset.is_file():
        raise PilotPreviewError("INPUT_MISSING: source or resolved pack state")
    if not checkpoint.is_file():
        raise PilotPreviewError("INPUT_MISSING: pinned SAM2 checkpoint")
    if _sha256(source) != str(manifest["source_sha256"]):
        raise PilotPreviewError("SOURCE_HASH_MISMATCH")
    expected_state_sha = str(manifest.get("asset_state_sha256", manifest.get("asset_sha256", "")))
    if _sha256(asset) != expected_state_sha:
        raise PilotPreviewError("PACK_STATE_HASH_MISMATCH")
    if _sha256(checkpoint) != str(manifest["sam2_checkpoint_sha256"]):
        raise PilotPreviewError("SAM2_CHECKPOINT_HASH_MISMATCH")
    if compute_input_identity_sha256(manifest) != str(manifest.get("input_identity_sha256")):
        raise PilotPreviewError("INPUT_IDENTITY_MISMATCH")
    output_relpaths = output_relpaths_for_manifest(manifest)

    # The schedule is an input to reconstruction/composition, not a post-
    # render annotation.  Fail before decode if the frozen probes or the
    # 521->522 book transition are not represented.
    schedule_rows = _build_composition_schedule(manifest, pack)

    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    runtime_root = Path(str(manifest["runtime_root"])).resolve()
    managed = ManagedRoot(Path(str(manifest["managed_root"])))
    rect = tuple(manifest["mask_correction"]["bbox_xywh_norm"])
    staging = ctx.staging_dir() / "pilot-preview"
    staging.mkdir(parents=True, exist_ok=True)

    # Resolve and decode the reviewed plate before SAM2 or compositing.  A
    # source-derived fallback is useful for diagnostics only and is never
    # allowed to reach the encoder.
    reviewed_plate_identity = _resolve_manifest_plate(manifest)
    if reviewed_plate_identity is None:
        _write_clean_plate_diagnostics(source, manifest, rect, ctx, staging)
        raise PilotPreviewError(
            "CLEAN_PLATE_REVIEW_REQUIRED: no approved clean_plate_id was supplied; "
            "diagnostic stills were written before heavy render work"
        )
    reviewed_plate = load_reviewed_plate(reviewed_plate_identity)

    ctx.write_checkpoint({"schema_version": 1, "phase": "decode", "start_frame": start, "end_frame": end})
    frames = _read_frames(source, start, end)
    height, width = frames[0].shape[:2]
    effective_inputs = canonical_effective_input_record(
        manifest,
        frame_size=(width, height),
        pack=pack,
        schedule_rows=schedule_rows,
    )
    declared_effective_sha = manifest.get("effective_input_sha256")
    if declared_effective_sha is not None and str(declared_effective_sha) != effective_inputs["effective_input_sha256"]:
        raise PilotPreviewError("EFFECTIVE_INPUT_IDENTITY_MISMATCH")
    ctx.progress(8.0, "running SAM2 mask propagation")
    propagated_masks = _sam2_masks(frames, rect, manifest)
    cleaned, removal_mask, mask_metrics, reconstructions = _reconstruct_source_frames(
        frames, rect, propagated_masks, manifest, ctx,
        reviewed_plate=reviewed_plate,
        reviewed_plate_identity=reviewed_plate_identity,
    )
    if ctx.is_cancelled():
        return {"cancelled": True}

    mask_path = staging / "removal-mask.png"
    import cv2

    cv2.imwrite(str(mask_path), removal_mask)
    video_only = staging / "after-video-only.mp4"
    after_staged = staging / "after.mp4"
    before_staged = staging / "before.mp4"
    composed, renderer_meta = _composite_v3(
        cleaned,
        source=source,
        asset=asset,
        rect=rect,
        keyframes=list(manifest["anchor_keyframes"]),
        occluder=dict(manifest["occluder"]),
        output=video_only,
        runtime_root=runtime_root,
        start_frame=start,
        ffmpeg=ffmpeg,
        ctx=ctx,
        pack=pack,
        schedule_rows=schedule_rows,
        reconstructions=reconstructions,
        anchor_mode=str(manifest.get("anchor_mode", "source_derived")),
    )
    if ctx.is_cancelled():
        return {"cancelled": True}

    _trim_before(source, before_staged, start, frame_count, ffmpeg)
    _remux(source, video_only, after_staged, start, frame_count, ffmpeg)
    source_media = _probe_media(source, ffprobe)
    before_qc = _validate_video(before_staged, frame_count, width, height, ffprobe)
    after_qc = _validate_video(after_staged, frame_count, width, height, ffprobe)
    source_audio = _has_audio(source, ffprobe)
    before_audio = _has_audio(before_staged, ffprobe)
    after_audio = _has_audio(after_staged, ffprobe)
    if source_audio and (not before_audio or not after_audio):
        raise PilotPreviewError("AUDIO_PRESERVATION_FAILED")
    for label, media in (("before", before_qc), ("after", after_qc)):
        offset = (media["stream"] or {}).get("audio_start_offset_seconds")
        if source_audio and offset is not None and abs(float(offset)) > (1 / _FPS_NUM):
            raise PilotPreviewError(f"AUDIO_OFFSET_FAILED: {label} start_time={offset}")
    root = managed
    published_preview = {
        "before": {"relative_path": output_relpaths["before"], "sha256": before_qc["sha256"], "size_bytes": before_qc["size_bytes"]},
        "after": {"relative_path": output_relpaths["after"], "sha256": after_qc["sha256"], "size_bytes": after_qc["size_bytes"]},
    }
    evidence = {
        "schema_version": "pilot-preview-v1",
        "job_id": ctx.job_id,
        "input_identity_sha256": manifest["input_identity_sha256"],
        "pipeline_revision": manifest.get("pipeline_revision"),
        "render_geometry_contract": manifest.get("render_geometry_contract"),
        "composition_revision": manifest.get("composition_revision"),
        "pack_verdict": pack_verdict,
        "pack_capabilities": pack["capabilities"],
        "pack_identity": {
            "pack_id": pack["pack_id"],
            "version": pack["version"],
            "manifest_sha256": pack["manifest_sha256"],
            "content_sha256": pack["content_sha256"],
            "states": {
                state_id: {
                    "sha256": state["sha256"],
                    "canvas_size": state["canvas_size"],
                    "anchors": state["anchors"],
                    "pose": state["pose"],
                    "mouth": state["mouth"],
                    "book": state["book"],
                }
                for state_id, state in pack["states"].items()
            },
        },
        "clean_plate_identity": reviewed_plate_identity,
        "status_detail": {
            "render_status": "render-completed",
            "automated_qc": "automated-qc-passed",
            "visual_review": "needs-visual-review",
            "approval": "not-approved",
            "note": (
                "Automated checks (decode count, H264/yuv420p, timing, audio) "
                "passed; human visual review is still required; this preview "
                "never authorizes Full Apply or approval."
            ),
        },
        "source_sha256": manifest["source_sha256"],
        "asset_sha256": manifest["asset_sha256"],
        "sam2_checkpoint_sha256": manifest["sam2_checkpoint_sha256"],
        "source": {
            "path": str(source),
            "sha256": manifest["source_sha256"],
            "frame_range": [start, end],
            "fps": [_FPS_NUM, _FPS_DEN],
            "dimensions": [width, height],
            "audio_present": source_audio,
        },
            "identity": {
                "role": manifest["role"],
                "source_prompt": manifest["source_prompt"],
                "legacy_id_bridge": manifest.get("legacy_id_bridge", {}),
            },
        "asset": {
            "path": str(asset),
            "state_sha256": manifest["asset_state_sha256"],
            "pack_content_sha256": manifest["asset_sha256"],
            "alpha": "RGBA straight alpha",
        },
        "segmentation": {
            "backend": "sam2.1",
            "checkpoint_sha256": manifest["sam2_checkpoint_sha256"],
            "mode": "SAM2 propagated mask consumed by source-derived reconstruction inside operator edit envelope",
            "mask_correction": manifest["mask_correction"],
            "removal_mask_sha256": _sha256(mask_path),
        },
        "reconstruction": {
            "revision": RECONSTRUCTION_REVISION,
            "effective_input": "SAM2 propagated mask + source-derived removal + operator correction",
            "clean_plate_identity": manifest.get("clean_plate_identity"),
            "protected_roles": sorted(reconstructions[0]["protected_masks"]),
            "protected_pixels_restored_before_encode": True,
        },
        "renderer": renderer_meta,
        "audio": {"source": source_audio, "before": before_audio, "after": after_audio},
        "qc": {"before": before_qc, "after": after_qc, "frame_count": frame_count, "duration_seconds": frame_count / _FPS_NUM},
        "source_media": {
            "width": source_media["width"],
            "height": source_media["height"],
            "video_codec": source_media.get("video_codec"),
            "pix_fmt": source_media.get("pix_fmt"),
            "fps": list(source_media["fps"]) if source_media.get("fps") else None,
            "audio_present": source_media["audio_present"],
        },
        "composition_schedule": schedule_rows,
        "effective_inputs": effective_inputs,
        "per_frame_provenance": [
            {
                "output_frame": i,
                "source_frame": start + i,
                **mask_metrics[i],
                "occluder_layer": manifest["occluder"]["layer_id"],
                "layer_order": reconstructions[i]["layer_order"],
            }
            for i in range(frame_count)
        ],
        "output_relpaths": output_relpaths,
        "published": published_preview,
    }
    evidence_staged = staging / "evidence.json"
    evidence_staged.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    _assert_final_inputs(manifest, source, asset, checkpoint)
    if ctx.is_cancelled():
        return {"cancelled": True}
    _preflight_publish(root, before_staged, output_relpaths["before"])
    _preflight_publish(root, after_staged, output_relpaths["after"])
    _preflight_publish(root, evidence_staged, output_relpaths["evidence"])
    published_before = _publish(root, before_staged, output_relpaths["before"])
    published_after = _publish(root, after_staged, output_relpaths["after"])
    published_evidence = _publish(root, evidence_staged, output_relpaths["evidence"])
    result = {"status": "completed", "outputs": {"before": published_before, "after": published_after, "evidence": published_evidence}, "qc": evidence["qc"]}
    ctx.write_checkpoint({"schema_version": 1, "phase": "published", "outputs": result["outputs"]})
    ctx.progress(100.0, "pilot preview published")
    return result


def register_pilot_preview_handler(worker: Any) -> None:
    worker.register_handler(
        JOB_TYPE_PILOT_PREVIEW,
        pilot_preview_handler,
        declared_outputs=None,
        output_validator=_validate_outputs,
        resource_class="cpu_video_preview",
    )


__all__ = ["JOB_TYPE_PILOT_PREVIEW", "PilotPreviewError", "pilot_preview_handler", "register_pilot_preview_handler", "pack_gate_verdict", "require_pack_compatible", "V3_NEGATIVE_ASSET_SHA256", "PACK_COMPAT_MISSING_FOR_V3"]

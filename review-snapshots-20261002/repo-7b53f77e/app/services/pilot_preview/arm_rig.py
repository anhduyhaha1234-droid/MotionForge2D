"""Source-native independent arm rig for the isolated C9 pilot correction.

The rig is deliberately small and deterministic.  It does not create artwork:
the resolver supplies five disjoint RGBA role layers per side, each derived
from visible source pixels.  At render time each role is sampled once with an
inverse map, using premultiplied alpha, and is then composited at its explicit
occlusion stage.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

ARM_RIG_REVISION = "c9-arm-rig-native-raster-v1"
ARM_ROLE_ORDER = ("upper_arm", "forearm", "cuff_bridge", "hand_grip", "front_fingers")
ARM_JOINT_ORDER = ("shoulder", "elbow", "wrist", "grip")
ARM_BEHIND_BOOK = ("upper_arm", "forearm", "cuff_bridge")
ARM_FRONT_BOOK = ("hand_grip", "front_fingers")
# C9 open-book seam was measured on the source frames: the replacement
# reader's right upper/forearm is behind the woman from x=286 onward in the
# y=160..234 seam band.  This is an occlusion guard, not a camera/book move.
OPEN_BOOK_SEAM_X_LIMIT_PX = 286
OPEN_BOOK_SEAM_Y_START_PX = 160
OPEN_BOOK_SEAM_Y_END_PX = 235
OPEN_BOOK_SEAM_REVISION = "c9-open-book-woman-seam-v1"


class ArmRigError(ValueError):
    """Fail-closed error for arm geometry, raster, or semantic ownership."""


_RGBA_CACHE: dict[tuple[str, str], Any] = {}


def _finite_xy(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ArmRigError(f"{label}: point must be [x,y]")
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(v) for v in point):
        raise ArmRigError(f"{label}: point is non-finite")
    return point


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def solve_two_bone_ik(
    shoulder: tuple[float, float],
    target: tuple[float, float],
    upper_length: float,
    fore_length: float,
    bend_sign: int,
    *,
    unreachable_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Solve a two-bone chain without silently stretching an unreachable arm."""
    shoulder = _finite_xy(shoulder, "shoulder")
    target = _finite_xy(target, "target")
    upper_length = float(upper_length)
    fore_length = float(fore_length)
    if not all(math.isfinite(v) and v > 0.0 for v in (upper_length, fore_length)):
        raise ArmRigError("IK lengths must be finite and positive")
    if int(bend_sign) not in (-1, 1):
        raise ArmRigError("IK bend sign must be -1 or 1")
    dx, dy = target[0] - shoulder[0], target[1] - shoulder[1]
    distance = math.hypot(dx, dy)
    if (
        distance > upper_length + fore_length + unreachable_tolerance
        or distance < abs(upper_length - fore_length) - unreachable_tolerance
    ):
        raise ArmRigError(
            f"IK_UNREACHABLE_TARGET: distance={distance:.6f} "
            f"reach={upper_length + fore_length:.6f}"
        )
    # A zero-distance target has no stable heading.  Use a deterministic
    # vertical heading while still preserving both constrained lengths.
    if distance <= 1e-9:
        ux, uy = 0.0, -1.0
        distance = 1e-9
    else:
        ux, uy = dx / distance, dy / distance
    # Clamp only for the lawful, slightly-compressed case where floating point
    # error places the target just beyond the maximum reach.  Never stretch.
    d = min(distance, upper_length + fore_length)
    d = max(d, abs(upper_length - fore_length))
    cosine = (upper_length * upper_length + d * d - fore_length * fore_length) / (2.0 * upper_length * d)
    cosine = max(-1.0, min(1.0, cosine))
    along = upper_length * cosine
    across = int(bend_sign) * upper_length * math.sqrt(max(0.0, 1.0 - cosine * cosine))
    elbow = (
        shoulder[0] + ux * along - uy * across,
        shoulder[1] + uy * along + ux * across,
    )
    wrist = (shoulder[0] + ux * d, shoulder[1] + uy * d)
    if distance > upper_length + fore_length + unreachable_tolerance:
        raise ArmRigError("IK_UNREACHABLE_TARGET")
    return {
        "shoulder": [float(shoulder[0]), float(shoulder[1])],
        "elbow": [float(elbow[0]), float(elbow[1])],
        "wrist": [float(wrist[0]), float(wrist[1])],
        "grip": [float(target[0]), float(target[1])],
        "upper_length": float(upper_length),
        "fore_length": float(fore_length),
        "target_distance": float(distance),
        "bend_sign": int(bend_sign),
        "unreachable": False,
    }


def _frame_size(fit: dict[str, Any], dst_size: tuple[int, int] | None) -> tuple[int, int]:
    if dst_size is not None:
        width, height = int(dst_size[0]), int(dst_size[1])
    else:
        raw = fit.get("frame_size", (640, 360))
        width, height = int(raw[0]), int(raw[1])
    if width <= 0 or height <= 0:
        raise ArmRigError("destination frame size must be positive")
    return width, height


def _fit_point(point: tuple[float, float], fit: dict[str, Any], dst_size: tuple[int, int]) -> tuple[float, float]:
    """Apply the same centre-based scale/rotation/translation as the worker."""
    canvas = fit.get("asset_canvas_size")
    if not isinstance(canvas, (list, tuple)) or len(canvas) != 2:
        raise ArmRigError("fit lacks asset canvas")
    width, height = dst_size
    cw, ch = float(canvas[0]), float(canvas[1])
    scale = float(fit["scale"])
    theta = math.radians(float(fit["rotation_deg"]))
    vx = (float(point[0]) - cw / 2.0) * scale
    vy = (float(point[1]) - ch / 2.0) * scale
    centre = ((float(fit["translation_xy"][0]) + 0.5) * width,
              (float(fit["translation_xy"][1]) + 0.5) * height)
    return (
        centre[0] + math.cos(theta) * vx - math.sin(theta) * vy,
        centre[1] + math.sin(theta) * vx + math.cos(theta) * vy,
    )


def _fit_vector(vector: tuple[float, float], fit: dict[str, Any]) -> tuple[float, float]:
    scale = float(fit["scale"])
    theta = math.radians(float(fit["rotation_deg"]))
    return (
        scale * (math.cos(theta) * float(vector[0]) - math.sin(theta) * float(vector[1])),
        scale * (math.sin(theta) * float(vector[0]) + math.cos(theta) * float(vector[1])),
    )


def fit_affine_matrix(fit: dict[str, Any], dst_size: tuple[int, int] = (640, 360)) -> Any:
    """Return the exact centre-based asset-to-frame affine used by the worker."""
    import numpy as np

    width, height = _frame_size(fit, dst_size)
    canvas = fit.get("asset_canvas_size")
    if not isinstance(canvas, (list, tuple)) or len(canvas) != 2:
        raise ArmRigError("fit lacks asset canvas")
    cw, ch = float(canvas[0]), float(canvas[1])
    scale = float(fit["scale"])
    theta = math.radians(float(fit["rotation_deg"]))
    a, b = scale * math.cos(theta), -scale * math.sin(theta)
    c, d = scale * math.sin(theta), scale * math.cos(theta)
    centre_x = (float(fit["translation_xy"][0]) + 0.5) * width
    centre_y = (float(fit["translation_xy"][1]) + 0.5) * height
    return np.asarray(
        [[a, b, centre_x - a * cw / 2.0 - b * ch / 2.0],
         [c, d, centre_y - c * cw / 2.0 - d * ch / 2.0]],
        dtype=np.float32,
    )


def _similarity_matrix(
    source_start: tuple[float, float],
    source_end: tuple[float, float],
    target_start: tuple[float, float],
    target_end: tuple[float, float],
) -> Any:
    import numpy as np

    sx, sy = source_end[0] - source_start[0], source_end[1] - source_start[1]
    tx, ty = target_end[0] - target_start[0], target_end[1] - target_start[1]
    source_length, target_length = math.hypot(sx, sy), math.hypot(tx, ty)
    if source_length < 1e-6 or target_length < 1e-6:
        raise ArmRigError("role segment is degenerate")
    scale = target_length / source_length
    cos_theta = (sx * tx + sy * ty) / (source_length * target_length)
    sin_theta = (sx * ty - sy * tx) / (source_length * target_length)
    a, b = scale * cos_theta, -scale * sin_theta
    c, d = scale * sin_theta, scale * cos_theta
    return np.asarray(
        [[a, b, target_start[0] - a * source_start[0] - b * source_start[1]],
         [c, d, target_start[1] - c * source_start[0] - d * source_start[1]]],
        dtype=np.float32,
    )


def warp_rgba_inverse(
    rgba: Any,
    matrix: Any,
    dst_size: tuple[int, int],
    *,
    source_scale: float = 1.0,
) -> Any:
    """Inverse-map one straight-BGRA layer with premultiplied interpolation."""
    import cv2
    import numpy as np

    image = np.asarray(rgba)
    if image.ndim != 3 or image.shape[2] != 4 or image.dtype != np.uint8:
        raise ArmRigError("RGBA layer must be uint8 BGRA")
    width, height = _frame_size({}, dst_size)
    affine = np.asarray(matrix, dtype=np.float64)
    if affine.shape != (2, 3) or not np.all(np.isfinite(affine)):
        raise ArmRigError("affine matrix is invalid")
    linear = affine[:, :2]
    if abs(float(np.linalg.det(linear))) < 1e-9:
        raise ArmRigError("affine matrix is singular")
    inv = cv2.invertAffineTransform(affine.astype(np.float32))
    yy, xx = np.indices((height, width), dtype=np.float32)
    map_x = inv[0, 0] * xx + inv[0, 1] * yy + inv[0, 2]
    map_y = inv[1, 0] * xx + inv[1, 1] * yy + inv[1, 2]
    interpolation = cv2.INTER_AREA if float(source_scale) < 1.0 else cv2.INTER_LINEAR
    source = image.astype(np.float32) / 255.0
    alpha = source[:, :, 3]
    premul = source[:, :, :3] * alpha[:, :, None]
    warped_premul = cv2.remap(premul, map_x, map_y, interpolation, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    warped_alpha = cv2.remap(alpha, map_x, map_y, interpolation, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    result = np.zeros((height, width, 4), dtype=np.uint8)
    visible = warped_alpha > (1.0 / 255.0)
    rgb = np.zeros_like(warped_premul)
    rgb[visible] = warped_premul[visible] / warped_alpha[visible, None]
    result[:, :, :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    result[:, :, 3] = np.clip(warped_alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    result[result[:, :, 3] == 0, :3] = 0
    return result


def _load_role(role: dict[str, Any]) -> Any:
    import cv2

    key = (str(role["path"]), str(role["sha256"]))
    if key not in _RGBA_CACHE:
        image = cv2.imread(str(role["path"]), cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 3 or image.shape[2] != 4 or image.dtype != __import__("numpy").uint8:
            raise ArmRigError(f"role decode failed: {role.get('role')}")
        alpha = image[:, :, 3]
        if int(alpha.min()) != 0 or int(alpha.max()) != 255 or not (alpha > 0).any():
            raise ArmRigError(f"role alpha contract failed: {role.get('role')}")
        _RGBA_CACHE[key] = image
    return _RGBA_CACHE[key]


def build_arm_rig_plan(
    state: dict[str, Any],
    fit: dict[str, Any],
    source_targets: dict[str, Any],
    *,
    source_frame: int,
    dst_size: tuple[int, int] = (640, 360),
) -> dict[str, Any]:
    """Build independent left/right chains and role transforms for a frame."""
    import numpy as np

    rig = state.get("arm_rig")
    if not isinstance(rig, dict) or rig.get("revision") != ARM_RIG_REVISION:
        raise ArmRigError("ARM_RIG_NOT_RESOLVED")
    width, height = _frame_size(fit, dst_size)
    role_layers: dict[str, dict[str, Any]] = {}
    joints_out: dict[str, dict[str, list[float]]] = {}
    target_map = {"left": "hand_grip_l", "right": "hand_grip_r"}
    for side in ("left", "right"):
        source_joints = {
            name: _finite_xy(rig["joints"][side][name], f"{side}.{name}")
            for name in ARM_JOINT_ORDER
        }
        transformed_shoulder = _fit_point(source_joints["shoulder"], fit, (width, height))
        scale = abs(float(fit["scale"]))
        upper = _distance(source_joints["shoulder"], source_joints["elbow"]) * scale
        fore = _distance(source_joints["elbow"], source_joints["wrist"]) * scale
        target = _finite_xy(source_targets[target_map[side]], f"{source_frame}.{target_map[side]}")
        # IK solves to the wrist.  The visible grip is a separate, finite
        # wrist->grip source segment, so preserve that offset and place the
        # grip endpoint on the measured source-book target.
        grip_offset = _fit_vector(
            (source_joints["grip"][0] - source_joints["wrist"][0],
             source_joints["grip"][1] - source_joints["wrist"][1]),
            fit,
        )
        wrist_target = (target[0] - grip_offset[0], target[1] - grip_offset[1])
        solved = solve_two_bone_ik(
            transformed_shoulder,
            wrist_target,
            upper,
            fore,
            int(rig["bend_sign"][side]),
        )
        solved["grip"] = [float(target[0]), float(target[1])]
        joints_out[side] = {
            name: [float(value) for value in solved[name]] for name in ARM_JOINT_ORDER
        }
        side_roles = rig["roles"][side]
        layer_plan: dict[str, Any] = {}
        for role_name in ARM_ROLE_ORDER:
            role = side_roles[role_name]
            source_start = source_joints[role["start_joint"]]
            source_end = source_joints[role["end_joint"]]
            target_start = tuple(solved[role["start_joint"]])
            target_end = tuple(solved[role["end_joint"]])
            matrix = _similarity_matrix(source_start, source_end, target_start, target_end)
            raster = warp_rgba_inverse(
                _load_role(role),
                matrix,
                (width, height),
                source_scale=scale,
            )
            layer_plan[role_name] = {
                "side": side,
                "role": role_name,
                "start_joint": role["start_joint"],
                "end_joint": role["end_joint"],
                "matrix": matrix.tolist(),
                "rgba": raster,
                "alpha": raster[:, :, 3].copy(),
                "source_path": role["path"],
                "source_sha256": role["sha256"],
                "source_visible": True,
            }
        role_layers[side] = layer_plan
    return {
        "revision": ARM_RIG_REVISION,
        "source_frame": int(source_frame),
        "frame_size": [width, height],
        "joints": joints_out,
        "targets": {
            side: [float(v) for v in source_targets[target_map[side]]]
            for side in ("left", "right")
        },
        "roles": role_layers,
        "occlusion": {"behind_book": list(ARM_BEHIND_BOOK), "front_book": list(ARM_FRONT_BOOK)},
        "raster_contract": "inverse_area_premultiplied_one_pass_v1",
        "source_scale": scale,
        "diagnostics": {
            "frame": int(source_frame),
            "left_right_independent": True,
            "unreachable_targets": [],
            "source_target_basis": source_targets.get("contact_basis", "source_book_boundary_design"),
        },
    }


def _composite(base: Any, layer: Any) -> Any:
    import numpy as np

    output = np.asarray(base).copy()
    rgba = np.asarray(layer)
    if output.ndim != 3 or output.shape[2] != 3 or rgba.shape[:2] != output.shape[:2]:
        raise ArmRigError("composite shape mismatch")
    alpha = rgba[:, :, 3:4].astype(np.float64) / 255.0
    output[:] = np.clip(
        rgba[:, :, :3].astype(np.float64) * alpha + output.astype(np.float64) * (1.0 - alpha),
        0.0,
        255.0,
    ).astype(np.uint8)
    return output


def composite_arm_layers(frame: Any, plan: dict[str, Any], stage: str) -> Any:
    """Composite roles in the explicit behind-book or front-book stage."""
    if stage == "behind_book":
        roles = ARM_BEHIND_BOOK
    elif stage == "front_book":
        roles = ARM_FRONT_BOOK
    else:
        raise ArmRigError(f"unknown arm occlusion stage: {stage}")
    output = frame
    for role_name in roles:
        for side in ("left", "right"):
            output = _composite(output, plan["roles"][side][role_name]["rgba"])
    return output


def clip_open_book_seam_roles(plan: dict[str, Any], *, source_frame: int) -> dict[str, Any]:
    """Apply the measured woman-front occlusion to behind-book right-arm roles.

    The source-native role masks remain intact on disk.  Only the per-frame
    render alpha is clipped when the open-book seam is active, while front
    hand roles remain available to prove contact at the source book edge.
    """
    import numpy as np

    if int(source_frame) < 522:
        return plan
    occluded: list[list[str]] = []
    for role_name in ARM_BEHIND_BOOK:
        rgba = np.array(plan["roles"]["right"][role_name]["rgba"], copy=True)
        rgba[OPEN_BOOK_SEAM_Y_START_PX:OPEN_BOOK_SEAM_Y_END_PX, OPEN_BOOK_SEAM_X_LIMIT_PX:, 3] = 0
        rgba[rgba[:, :, 3] == 0, :3] = 0
        plan["roles"]["right"][role_name]["rgba"] = rgba
        plan["roles"]["right"][role_name]["alpha"] = rgba[:, :, 3].copy()
        if not np.any(rgba[:, :, 3] > 32):
            occluded.append(["right", role_name])
    plan.setdefault("diagnostics", {})["open_book_seam_occlusion"] = {
        "revision": OPEN_BOOK_SEAM_REVISION,
        "x_limit_px": OPEN_BOOK_SEAM_X_LIMIT_PX,
        "y_range_px": [OPEN_BOOK_SEAM_Y_START_PX, OPEN_BOOK_SEAM_Y_END_PX],
        "behind_book_right_roles_clipped": list(ARM_BEHIND_BOOK),
        "front_book_roles_preserved": list(ARM_FRONT_BOOK),
        "fully_occluded_roles": occluded,
    }
    return plan


def validate_arm_rig_frame(
    *,
    before_arms: Any,
    final_frame: Any,
    plan: dict[str, Any],
    book_mask: Any,
    book_reference: Any,
    woman_mask: Any | None = None,
    protected_after_behind: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate actual output pixels, contact, and protected-role ownership."""
    import cv2
    import numpy as np

    before = np.asarray(before_arms)
    actual = np.asarray(final_frame)
    if before.shape != actual.shape or actual.ndim != 3 or actual.shape[2] != 3:
        raise ArmRigError("ARM_FINAL_PIXEL_SHAPE_INVALID")
    book = np.asarray(book_mask) > 0
    reference = np.asarray(book_reference)
    if book.shape != actual.shape[:2] or reference.shape != actual.shape:
        raise ArmRigError("ARM_BOOK_REFERENCE_SHAPE_INVALID")
    if not np.any(book):
        raise ArmRigError("ARM_BOOK_MASK_EMPTY")
    if not isinstance(plan.get("roles"), dict) or any(
        side not in plan["roles"] for side in ("left", "right")
    ):
        raise ArmRigError("ARM_ROLE_PLAN_MISSING")
    role_masks: dict[tuple[str, str], Any] = {}
    explicitly_occluded = {
        tuple(item)
        for item in plan.get("diagnostics", {}).get("open_book_seam_occlusion", {}).get("fully_occluded_roles", [])
        if isinstance(item, (list, tuple)) and len(item) == 2
    }
    all_visible = np.zeros(book.shape, dtype=bool)
    expected = before.copy()
    for role_name in ARM_BEHIND_BOOK:
        for side in ("left", "right"):
            rgba = np.asarray(plan["roles"][side][role_name]["rgba"])
            visible = rgba[:, :, 3] > 32
            if not np.any(visible):
                if (side, role_name) not in explicitly_occluded:
                    raise ArmRigError(f"ARM_ROLE_EMPTY:{side}:{role_name}")
            role_masks[(side, role_name)] = visible
            expected = _composite(expected, rgba)
    if protected_after_behind:
        for protected_mask in protected_after_behind.values():
            keep = np.asarray(protected_mask) > 0
            if keep.shape != expected.shape[:2]:
                raise ArmRigError("ARM_PROTECTED_RESTORE_SHAPE_INVALID")
            expected[keep] = reference[keep]
    # ``finish_source_book`` is the production book-owner operation between
    # the two arm stages.  Model its source-owned pixels in the expected image
    # so the gate measures arm contribution rather than a legitimate book
    # silhouette repair.
    expected[book] = reference[book]
    from app.services.pilot_preview.scene_reconstruction import finish_source_book

    expected = finish_source_book(
        expected,
        source_frame=int(plan["source_frame"]),
        book_mask=book_mask,
    )
    for role_name in ARM_FRONT_BOOK:
        for side in ("left", "right"):
            rgba = np.asarray(plan["roles"][side][role_name]["rgba"])
            visible = rgba[:, :, 3] > 32
            if not np.any(visible):
                if (side, role_name) not in explicitly_occluded:
                    raise ArmRigError(f"ARM_ROLE_EMPTY:{side}:{role_name}")
            role_masks[(side, role_name)] = visible
            expected = _composite(expected, rgba)
            all_visible |= visible
    if protected_after_behind:
        for protected_mask in protected_after_behind.values():
            keep = np.asarray(protected_mask) > 0
            expected[keep] = reference[keep]
    # The exact compositor result is the expected truth for changed role
    # pixels.  This catches a skipped layer or an accidental post-layer erase.
    changed = np.any(expected != before, axis=2)
    if not np.any(changed):
        raise ArmRigError("ARM_FINAL_PIXEL_CONTRIBUTION_MISSING")
    if not np.array_equal(actual[changed], expected[changed]):
        mismatch = np.any(actual != expected, axis=2) & changed
        delta = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
        raise ArmRigError(
            "ARM_FINAL_PIXEL_MISMATCH: "
            f"pixels={int(np.count_nonzero(mismatch))} "
            f"max_delta={int(delta[mismatch].max()) if np.any(mismatch) else 0}"
        )
    contacts: dict[str, Any] = {}
    for side, target in plan["targets"].items():
        target_xy = _finite_xy(target, f"{side}.target")
        front_visible = role_masks[(side, "hand_grip")] | role_masks[(side, "front_fingers")]
        near_target = cv2.dilate(front_visible.astype(np.uint8), np.ones((7, 7), np.uint8), iterations=1) > 0
        tx, ty = int(round(target_xy[0])), int(round(target_xy[1]))
        y0, y1 = max(0, ty - 5), min(book.shape[0], ty + 6)
        x0, x1 = max(0, tx - 5), min(book.shape[1], tx + 6)
        local_book = book[y0:y1, x0:x1]
        local_touch = near_target[y0:y1, x0:x1]
        if not np.any(local_book & local_touch):
            raise ArmRigError(f"ARM_BOOK_CONTACT_MISSING:{side}")
        contacts[side] = {
            "target_px": [float(target_xy[0]), float(target_xy[1])],
            "distance_px": 0.0,
            "actual_front_pixels": int(np.count_nonzero(front_visible)),
        }
        body_near = role_masks[(side, "upper_arm")] | role_masks[(side, "forearm")] | role_masks[(side, "cuff_bridge")]
        if not np.any(body_near & cv2.dilate(front_visible.astype(np.uint8), np.ones((9, 9), np.uint8), iterations=1)):
            seam_active = plan.get("diagnostics", {}).get("open_book_seam_occlusion", {}).get("revision") == OPEN_BOOK_SEAM_REVISION
            if (side == "right" and seam_active) or all((side, role_name) in explicitly_occluded for role_name in ARM_BEHIND_BOOK):
                continue
            raise ArmRigError(f"ARM_BODY_WRIST_DISCONNECTED:{side}")
    # The source-owned book may change only where the explicit front-hand
    # roles are allowed to occlude it.  A woman pixel changed by behind roles
    # is always illegal; front-hand overlap is recorded as legitimate.
    front_union = np.zeros(book.shape, dtype=bool)
    for side in ("left", "right"):
        for role_name in ARM_FRONT_BOOK:
            front_union |= np.asarray(plan["roles"][side][role_name]["rgba"])[:, :, 3] > 0
    book_outside_front = book & ~front_union
    pre_front = before.copy()
    for role_name in ARM_BEHIND_BOOK:
        for side in ("left", "right"):
            pre_front = _composite(pre_front, plan["roles"][side][role_name]["rgba"])
    if protected_after_behind:
        for protected_mask in protected_after_behind.values():
            keep = np.asarray(protected_mask) > 0
            pre_front[keep] = reference[keep]
    pre_front[book] = reference[book]
    pre_front = finish_source_book(pre_front, source_frame=int(plan["source_frame"]), book_mask=book_mask)
    if np.any(actual[book_outside_front] != pre_front[book_outside_front]):
        raise ArmRigError("ARM_BOOK_PROTECTED_PIXEL_CHANGED")
    if woman_mask is not None:
        woman = np.asarray(woman_mask) > 0
        changed_woman = np.any(actual != reference, axis=2) & woman
        if np.any(changed_woman & ~front_union):
            raise ArmRigError("ARM_ILLEGAL_WOMAN_OVERWRITE")
    return {
        "revision": ARM_RIG_REVISION,
        "status": "passed",
        "raster_contract": plan["raster_contract"],
        "left_right_independent": True,
        "occlusion": {"behind_book": list(ARM_BEHIND_BOOK), "front_book": list(ARM_FRONT_BOOK)},
        "contacts": contacts,
        "visible_role_pixels": int(np.count_nonzero(all_visible)),
        "changed_role_pixels": int(np.count_nonzero(changed)),
    }


__all__ = [
    "ARM_BEHIND_BOOK",
    "ARM_FRONT_BOOK",
    "ARM_JOINT_ORDER",
    "ARM_RIG_REVISION",
    "ARM_ROLE_ORDER",
    "ArmRigError",
    "build_arm_rig_plan",
    "clip_open_book_seam_roles",
    "composite_arm_layers",
    "fit_affine_matrix",
    "solve_two_bone_ik",
    "validate_arm_rig_frame",
    "warp_rgba_inverse",
]

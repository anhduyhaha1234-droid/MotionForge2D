"""Server-owned resolver for versioned pilot-preview character packs.

The client may request a pack id, but it never supplies the pack's truth.  A
pack is compatible only after this module has resolved its manifest, hashed
every state image, decoded genuine straight-alpha RGBA pixels, and validated
the measured anchor set on each state.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from app.services.pilot_preview.scene_contract import COMPAT_REQUIREMENTS

PACK_MANIFEST_FILENAME = "manifest.json"
PACK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_STATES = ("seated_book_closed", "seated_book_open")
REQUIRED_ANCHORS = (
    "head",
    "seat_pelvis",
    "hand_grip_l",
    "hand_grip_r",
    "book_corners",
)
REQUIRED_CONTACTS = REQUIRED_ANCHORS
PRIVATE_PREVIEW_STATUSES = frozenset({"APPROVED", "PRIVATE_PREVIEW_INPUT_READY", "PREVIEW_CANDIDATE"})
REQUIRED_SOURCE_SAMPLES = (450, 510, 521, 522, 523, 569)
C6_SEMANTIC_CONTRACT = "c6-source-prop-contact-v2"
C6_CONTACT_POLICY = "source-prop-boundary-contact-v2"
C7_SEMANTIC_CONTRACT = "c7-exclusive-anatomy-v1"
C9_ARM_RIG_SEMANTIC_CONTRACT = "c9-independent-arm-rig-v1"
C9_ARM_RIG_REVISION = "c9-arm-rig-native-raster-v1"
ARM_ROLE_NAMES = ("upper_arm", "forearm", "cuff_bridge", "hand_grip", "front_fingers")
ARM_JOINT_NAMES = ("shoulder", "elbow", "wrist", "grip")
VALIDATED_SEMANTIC_CONTRACTS = frozenset({
    C6_SEMANTIC_CONTRACT,
    C7_SEMANTIC_CONTRACT,
    C9_ARM_RIG_SEMANTIC_CONTRACT,
})


class PackResolutionError(ValueError):
    """A pack is missing, tampered, malformed, or incompatible."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _finite_point(value: Any, *, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PackResolutionError(f"{label} must be [x,y]")
    try:
        point = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise PackResolutionError(f"{label} must contain numbers") from exc
    if not all(math.isfinite(part) for part in point):
        raise PackResolutionError(f"{label} must be finite")
    return point


def _validated_anchors(value: Any, *, width: int, height: int, state_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PackResolutionError(f"{state_id}: anchors are missing")
    anchors: dict[str, Any] = {}
    for name in REQUIRED_ANCHORS:
        if name not in value:
            raise PackResolutionError(f"{state_id}: missing anchor {name}")
        if name == "book_corners":
            corners = value[name]
            if not isinstance(corners, (list, tuple)) or len(corners) != 4:
                raise PackResolutionError(f"{state_id}: book_corners must contain four points")
            anchors[name] = [
                list(_finite_point(point, label=f"{state_id}.{name}[{index}]"))
                for index, point in enumerate(corners)
            ]
        else:
            anchors[name] = list(_finite_point(value[name], label=f"{state_id}.{name}"))
    for name, point_value in anchors.items():
        points = point_value if name == "book_corners" else [point_value]
        if any(
            point[0] < 0.0 or point[1] < 0.0 or point[0] >= width or point[1] >= height
            for point in points
        ):
            raise PackResolutionError(f"{state_id}: {name} lies outside {width}x{height} canvas")
    if anchors["head"] == anchors["seat_pelvis"]:
        raise PackResolutionError(f"{state_id}: head and seat_pelvis must be distinct")
    return anchors


def _decode_rgba(path: Path, *, state_id: str) -> tuple[int, int]:
    import cv2
    import numpy as np

    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise PackResolutionError(f"{state_id}: {path.name} is not a decodable RGBA image")
    alpha = image[:, :, 3]
    if int(alpha.min()) != 0 or int(alpha.max()) != 255:
        raise PackResolutionError(f"{state_id}: alpha must be genuine straight alpha (0 and 255)")
    if int(np.count_nonzero(alpha)) == 0:
        raise PackResolutionError(f"{state_id}: alpha has no visible pixels")
    return int(image.shape[1]), int(image.shape[0])


def _verify_anchors_hit_art(
    path: Path,
    anchors: dict[str, Any],
    *,
    state_id: str,
    anchor_names: tuple[str, ...] = ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r"),
) -> None:
    """Verify replacement anchors land on decoded alpha pixels.

    ``book_corners`` are deliberately excluded: the pilot contract keeps the
    book source-owned and composites it as a protected source prop above the
    replacement.  Requiring those external-prop points to hit replacement
    alpha was the C3 duplicate-book failure mode.
    """
    import cv2

    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise PackResolutionError(f"{state_id}: anchor verification could not decode RGBA")
    alpha = image[:, :, 3]
    points = [anchors[name] for name in anchor_names]
    for point in points:
        x, y = int(round(point[0])), int(round(point[1]))
        if not (0 <= x < alpha.shape[1] and 0 <= y < alpha.shape[0]) or int(alpha[y, x]) == 0:
            raise PackResolutionError(f"{state_id}: anchor {point!r} does not land on replacement art")


def _validated_arm_rig(
    value: Any,
    *,
    pack_dir: Path,
    state_id: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Resolve independent arm roles from server-owned, visible asset pixels."""
    if not isinstance(value, dict) or value.get("revision") != C9_ARM_RIG_REVISION:
        raise PackResolutionError(f"{state_id}: arm rig revision missing or stale")
    if value.get("provenance") != "existing_visible_asset_pixels_only":
        raise PackResolutionError(f"{state_id}: arm rig provenance is not source-visible")
    raw_joints = value.get("joints")
    raw_roles = value.get("roles")
    if not isinstance(raw_joints, dict) or not isinstance(raw_roles, dict):
        raise PackResolutionError(f"{state_id}: arm rig joints/roles missing")
    normalized_joints: dict[str, dict[str, list[float]]] = {}
    normalized_roles: dict[str, dict[str, dict[str, Any]]] = {}
    for side in ("left", "right"):
        joints = raw_joints.get(side)
        roles = raw_roles.get(side)
        if not isinstance(joints, dict) or not isinstance(roles, dict):
            raise PackResolutionError(f"{state_id}:{side}: arm rig side missing")
        side_joints: dict[str, list[float]] = {}
        for name in ARM_JOINT_NAMES:
            point = _finite_point(joints.get(name), label=f"{state_id}.{side}.{name}")
            if not (0.0 <= point[0] < width and 0.0 <= point[1] < height):
                raise PackResolutionError(f"{state_id}:{side}:{name} outside canvas")
            side_joints[name] = [point[0], point[1]]
        for first, second in (("shoulder", "elbow"), ("elbow", "wrist"), ("wrist", "grip")):
            if math.dist(side_joints[first], side_joints[second]) < 1.0:
                raise PackResolutionError(f"{state_id}:{side}: arm joint segment is degenerate")
        if set(roles) != set(ARM_ROLE_NAMES):
            raise PackResolutionError(f"{state_id}:{side}: arm role set is incomplete")
        side_roles: dict[str, dict[str, Any]] = {}
        for role_name in ARM_ROLE_NAMES:
            role = roles.get(role_name)
            if not isinstance(role, dict):
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: role is malformed")
            start_joint = role.get("start_joint")
            end_joint = role.get("end_joint")
            relative = role.get("path")
            if start_joint not in ARM_JOINT_NAMES or end_joint not in ARM_JOINT_NAMES:
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: role joints invalid")
            if not isinstance(relative, str) or not relative.strip():
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: role path missing")
            role_path = (pack_dir / relative).resolve()
            if not _contained(role_path, pack_dir) or not role_path.is_file():
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: role path outside pack or missing")
            actual_sha = _sha256(role_path)
            if actual_sha != str(role.get("sha256", "")).lower():
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: role hash mismatch")
            role_width, role_height = _decode_rgba(role_path, state_id=f"{state_id}.{side}.{role_name}")
            if (role_width, role_height) != (width, height):
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: role canvas mismatch")
            side_roles[role_name] = {
                "role": role_name,
                "path": str(role_path),
                "relative_path": relative.replace("\\", "/"),
                "sha256": actual_sha,
                "canvas_size": [role_width, role_height],
                "start_joint": start_joint,
                "end_joint": end_joint,
                "source_visible": role.get("source_visible") is True,
            }
            if side_roles[role_name]["source_visible"] is not True:
                raise PackResolutionError(f"{state_id}:{side}:{role_name}: source_visible proof missing")
        normalized_joints[side] = side_joints
        normalized_roles[side] = side_roles
    bend_sign = value.get("bend_sign")
    if not isinstance(bend_sign, dict) or set(bend_sign) != {"left", "right"}:
        raise PackResolutionError(f"{state_id}: arm bend signs missing")
    if any(bend_sign[side] not in (-1, 1) for side in ("left", "right")):
        raise PackResolutionError(f"{state_id}: arm bend sign invalid")
    occlusion = value.get("occlusion")
    if not isinstance(occlusion, dict):
        raise PackResolutionError(f"{state_id}: arm occlusion map missing")
    if occlusion.get("behind_book") != ["upper_arm", "forearm", "cuff_bridge"]:
        raise PackResolutionError(f"{state_id}: behind-book roles invalid")
    if occlusion.get("front_book") != ["hand_grip", "front_fingers"]:
        raise PackResolutionError(f"{state_id}: front-book roles invalid")
    return {
        "revision": C9_ARM_RIG_REVISION,
        "provenance": "existing_visible_asset_pixels_only",
        "joints": normalized_joints,
        "roles": normalized_roles,
        "bend_sign": {side: int(bend_sign[side]) for side in ("left", "right")},
        "occlusion": {
            "behind_book": ["upper_arm", "forearm", "cuff_bridge"],
            "front_book": ["hand_grip", "front_fingers"],
        },
    }


def _validated_semantic_review(
    payload: dict[str, Any],
    *,
    camera_view: str,
    source_sha256: str | None,
    states: dict[str, Any],
    allow_private_preview: bool,
) -> dict[str, Any]:
    """Require explicit reviewed pose/contact evidence before capabilities."""
    review = payload.get("compatibility_review")
    allowed_statuses = PRIVATE_PREVIEW_STATUSES if allow_private_preview else frozenset({"APPROVED"})
    if not isinstance(review, dict) or review.get("status") not in allowed_statuses:
        raise PackResolutionError("PACK_SEMANTIC_REVIEW_REQUIRED")
    if not review.get("reviewer") or not review.get("reviewed_at"):
        raise PackResolutionError("PACK_SEMANTIC_REVIEW_INCOMPLETE")
    if review.get("camera_view") != camera_view:
        raise PackResolutionError("PACK_SEMANTIC_CAMERA_VIEW_MISMATCH")
    if review.get("anchor_head_role") != "replacement_character":
        raise PackResolutionError("PACK_HEAD_ANCHOR_ROLE_INVALID")
    if review.get("anchor_seat_pelvis_role") != "replacement_character":
        raise PackResolutionError("PACK_SEAT_ANCHOR_ROLE_INVALID")
    if review.get("book_owner") != "source":
        raise PackResolutionError("PACK_BOOK_OWNER_INVALID")
    if review.get("seat_reference") != "occupied_chair_seat":
        raise PackResolutionError("PACK_SEAT_REFERENCE_INVALID")
    if review.get("pose_compatible") is not True or review.get("book_contact_compatible") is not True:
        raise PackResolutionError("PACK_POSE_CONTACT_INCOMPATIBLE")
    samples = review.get("source_frame_samples")
    if samples != list(REQUIRED_SOURCE_SAMPLES):
        raise PackResolutionError("PACK_CONTACT_SAMPLES_INCOMPLETE")
    review_source_sha = str(review.get("source_sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", review_source_sha):
        raise PackResolutionError("PACK_CONTACT_SOURCE_HASH_MISSING")
    if source_sha256 and review_source_sha != str(source_sha256).lower():
        raise PackResolutionError("PACK_CONTACT_SOURCE_HASH_MISMATCH")
    artwork_hashes = review.get("artwork_sha256")
    if not isinstance(artwork_hashes, dict) or set(artwork_hashes) != set(REQUIRED_STATES):
        raise PackResolutionError("PACK_CONTACT_ARTWORK_HASHES_MISSING")
    for state_id in REQUIRED_STATES:
        if str(artwork_hashes[state_id]).lower() != str(states[state_id]["sha256"]).lower():
            raise PackResolutionError(f"{state_id}: contact artwork hash mismatch")
    semantic_contract = review.get("semantic_contract_revision")
    if semantic_contract not in VALIDATED_SEMANTIC_CONTRACTS:
        raise PackResolutionError("PACK_CONTACT_SEMANTIC_CONTRACT_UNKNOWN")
    # Dispatch is keyed by the server-validated semantic contract, never by a
    # version-string prefix that a client or a future pack can manufacture.
    is_c6 = semantic_contract == C6_SEMANTIC_CONTRACT
    is_c7 = semantic_contract == C7_SEMANTIC_CONTRACT
    if is_c6:
        if review.get("semantic_contract_revision") != C6_SEMANTIC_CONTRACT:
            raise PackResolutionError("PACK_CONTACT_SEMANTIC_CONTRACT_MISSING")
        if review.get("measurement_policy_revision") != C6_CONTACT_POLICY:
            raise PackResolutionError("PACK_CONTACT_POLICY_STALE")
        digest = str(review.get("source_contact_annotation_digest", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest == "0" * 64:
            raise PackResolutionError("PACK_CONTACT_ANNOTATION_DIGEST_MISSING")
        for state_id in REQUIRED_STATES:
            state_contract = states[state_id].get("contact_semantics")
            patches = states[state_id].get("hand_contact_patches")
            if not isinstance(state_contract, dict) or state_contract.get("kind") != "replacement_hand_to_source_book_boundary":
                raise PackResolutionError(f"{state_id}: hand/book semantic contract missing")
            if state_contract.get("book_owner") != "source" or state_contract.get("source_role") != "book":
                raise PackResolutionError(f"{state_id}: hand/book ownership contract invalid")
            if not isinstance(patches, dict) or set(patches) != {"left", "right"}:
                raise PackResolutionError(f"{state_id}: hand contact patches missing")
            for side, patch in patches.items():
                if not isinstance(patch, dict):
                    raise PackResolutionError(f"{state_id}: {side} contact patch malformed")
                _finite_point(patch.get("contact_local"), label=f"{state_id}.{side}.contact_local")
                box = patch.get("bbox_xywh")
                if not isinstance(box, (list, tuple)) or len(box) != 4:
                    raise PackResolutionError(f"{state_id}: {side} contact patch bbox missing")
                values = [float(value) for value in box]
                if not all(math.isfinite(value) for value in values) or values[2] <= 0 or values[3] <= 0:
                    raise PackResolutionError(f"{state_id}: {side} contact patch bbox invalid")
    if is_c7:
        if review.get("semantic_contract_revision") != C7_SEMANTIC_CONTRACT:
            raise PackResolutionError("PACK_C7_ANATOMY_CONTRACT_MISSING")
        if review.get("anatomy_ownership") != "exclusive_body_and_hand_asset":
            raise PackResolutionError("PACK_C7_ANATOMY_OWNERSHIP_INVALID")
        if review.get("body_hand_ownership") != "body_only_no_hands":
            raise PackResolutionError("PACK_C7_BODY_HAND_OWNERSHIP_INVALID")
        for state_id in REQUIRED_STATES:
            contract = states[state_id].get("contact_semantics")
            patches = states[state_id].get("hand_contact_patches")
            if not isinstance(contract, dict) or contract.get("anatomy_ownership") != "exclusive_body_and_hand_asset":
                raise PackResolutionError(f"{state_id}: C7 anatomy ownership missing")
            if not isinstance(patches, dict) or set(patches) != {"left", "right"}:
                raise PackResolutionError(f"{state_id}: C7 hand patches missing")
            for side, patch in patches.items():
                polygon = patch.get("polygon") if isinstance(patch, dict) else None
                if not isinstance(polygon, (list, tuple)) or len(polygon) < 3:
                    raise PackResolutionError(f"{state_id}: {side} anatomical polygon missing")
                for point in polygon:
                    x, y = _finite_point(point, label=f"{state_id}.{side}.polygon")
                    if not (0.0 <= x < states[state_id]["canvas_size"][0] and 0.0 <= y < states[state_id]["canvas_size"][1]):
                        raise PackResolutionError(f"{state_id}: {side} anatomical polygon outside canvas")
    if semantic_contract == C9_ARM_RIG_SEMANTIC_CONTRACT:
        if review.get("anatomy_ownership") != "existing_visible_asset_pixels_only":
            raise PackResolutionError("PACK_ARM_RIG_ANATOMY_OWNERSHIP_INVALID")
        if review.get("body_hand_ownership") != "body_with_independent_arm_roles":
            raise PackResolutionError("PACK_ARM_RIG_BODY_HAND_OWNERSHIP_INVALID")
        if review.get("arm_rig_revision") != C9_ARM_RIG_REVISION:
            raise PackResolutionError("PACK_ARM_RIG_REVISION_INVALID")
        if review.get("occlusion_policy") != "forearm_behind_book_fingers_in_front":
            raise PackResolutionError("PACK_ARM_RIG_OCCLUSION_POLICY_INVALID")
        for state_id in REQUIRED_STATES:
            if not isinstance(states[state_id].get("arm_rig"), dict):
                raise PackResolutionError(f"{state_id}: resolved arm rig missing")
    measurements = review.get("contact_measurements")
    if not isinstance(measurements, dict) or not {str(frame) for frame in REQUIRED_SOURCE_SAMPLES}.issubset(set(measurements)):
        raise PackResolutionError("PACK_CONTACT_MEASUREMENTS_INCOMPLETE")
    for frame in REQUIRED_SOURCE_SAMPLES:
        frame_data = measurements.get(str(frame))
        if not isinstance(frame_data, dict) or set(frame_data) != set(REQUIRED_STATES):
            raise PackResolutionError(f"frame {frame}: contact measurements missing states")
        for state_id in REQUIRED_STATES:
            state_data = frame_data[state_id]
            expected_state = "seated_book_closed" if frame < 522 else "seated_book_open"
            if state_id != expected_state:
                if state_data != {"not_applicable": True}:
                    raise PackResolutionError(
                        f"frame {frame} {state_id}: inactive state must be explicitly not_applicable"
                    )
                continue
            if not isinstance(state_data, dict) or set(state_data) != set(REQUIRED_CONTACTS):
                raise PackResolutionError(f"frame {frame} {state_id}: contact measurements missing contacts")
            for contact in REQUIRED_CONTACTS:
                value = state_data[contact]
                if (
                    semantic_contract == C9_ARM_RIG_SEMANTIC_CONTRACT
                    and contact == "book_corners"
                ):
                    if value != {"not_applicable": True, "owner": "source"}:
                        raise PackResolutionError(
                            f"frame {frame} {state_id} book_corners: "
                            "source-owned book geometry must be explicit not_applicable"
                        )
                    continue
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or float(value) < 0.0
                    or float(value) > 8.0
                ):
                    raise PackResolutionError(f"frame {frame} {state_id} {contact}: contact error must be finite and in [0,8]")
    return review


def _content_sha256(pack_id: str, version: str, camera_view: str, states: dict[str, Any]) -> str:
    def _arm_rig_identity(rig: Any) -> Any:
        if not isinstance(rig, dict):
            return None
        return {
            "revision": rig.get("revision"),
            "provenance": rig.get("provenance"),
            "bend_sign": rig.get("bend_sign"),
            "occlusion": rig.get("occlusion"),
            "joints": rig.get("joints"),
            "roles": {
                side: {
                    role_name: {
                        "relative_path": role.get("relative_path", role.get("path")),
                        "sha256": role.get("sha256"),
                        "canvas_size": role.get("canvas_size"),
                        "start_joint": role.get("start_joint"),
                        "end_joint": role.get("end_joint"),
                        "source_visible": role.get("source_visible"),
                    }
                    for role_name, role in sorted((rig.get("roles", {}).get(side, {}) or {}).items())
                }
                for side in ("left", "right")
            },
        }

    canonical = {
        "pack_id": pack_id,
        "version": version,
        "camera_view": camera_view,
        "states": {
            state_id: {
                "path": state.get("relative_path", state["path"]),
                "sha256": state["sha256"],
                "size_bytes": state["size_bytes"],
                "canvas_size": state["canvas_size"],
                "anchors": state["anchors"],
                "pose": state.get("pose"),
                "mouth": state.get("mouth"),
                "book": state.get("book"),
                "book_owner": state.get("book_owner"),
                "contact_semantics": state.get("contact_semantics"),
                "hand_contact_patches": state.get("hand_contact_patches"),
                "hand_asset_path": state.get("hand_asset_relative_path", state.get("hand_asset_path")),
                "hand_asset_sha256": state.get("hand_asset_sha256"),
                "arm_rig": _arm_rig_identity(state.get("arm_rig")),
            }
            for state_id, state in sorted(states.items())
        },
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_versioned_pack(
    pack_id: str,
    packs_root: Path,
    *,
    expected_content_sha256: str | None = None,
    expected_manifest_sha256: str | None = None,
    expected_source_sha256: str | None = None,
    allow_private_preview: bool = False,
) -> dict[str, Any]:
    """Resolve and validate one server-owned versioned pack.

    The returned paths and capabilities are derived from the files on disk;
    no client capability map is consulted.
    """
    if not isinstance(pack_id, str) or not PACK_ID_RE.fullmatch(pack_id):
        raise PackResolutionError("PACK_ID_INVALID")
    root = Path(packs_root).resolve()
    pack_dir = (root / pack_id).resolve()
    manifest_path = (pack_dir / PACK_MANIFEST_FILENAME).resolve()
    if not _contained(pack_dir, root) or not _contained(manifest_path, pack_dir):
        raise PackResolutionError("PACK_PATH_OWNERSHIP_FAILED")
    if not manifest_path.is_file():
        raise PackResolutionError(f"PACK_MANIFEST_MISSING: {pack_id}")
    manifest_sha = _sha256(manifest_path)
    if expected_manifest_sha256 and manifest_sha != str(expected_manifest_sha256).lower():
        raise PackResolutionError("PACK_MANIFEST_HASH_MISMATCH")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackResolutionError("PACK_MANIFEST_INVALID") from exc
    if not isinstance(payload, dict):
        raise PackResolutionError("PACK_MANIFEST_INVALID")
    semantic_contract_hint = (
        payload.get("compatibility_review", {}).get("semantic_contract_revision")
        if isinstance(payload.get("compatibility_review"), dict)
        else None
    )
    if semantic_contract_hint not in VALIDATED_SEMANTIC_CONTRACTS:
        raise PackResolutionError("PACK_CONTACT_SEMANTIC_CONTRACT_UNKNOWN")
    uses_exclusive_hands = semantic_contract_hint == C7_SEMANTIC_CONTRACT
    if payload.get("pack_id") != pack_id:
        raise PackResolutionError("PACK_IDENTITY_MISMATCH")
    approval = payload.get("approval")
    approval_status = approval.get("status") if isinstance(approval, dict) else None
    allowed_statuses = PRIVATE_PREVIEW_STATUSES if allow_private_preview else frozenset({"APPROVED"})
    if approval_status not in allowed_statuses:
        raise PackResolutionError("PACK_NOT_APPROVED")
    version = payload.get("version")
    camera_view = payload.get("camera_view")
    raw_states = payload.get("states")
    if not isinstance(version, str) or not version.strip():
        raise PackResolutionError("PACK_VERSION_MISSING")
    if not isinstance(camera_view, str) or "three_quarter" not in camera_view:
        raise PackResolutionError("PACK_CAMERA_VIEW_INVALID")
    if not isinstance(raw_states, dict):
        raise PackResolutionError("PACK_STATES_MISSING")
    states: dict[str, Any] = {}
    for state_id in REQUIRED_STATES:
        raw = raw_states.get(state_id)
        if not isinstance(raw, dict):
            raise PackResolutionError(f"PACK_STATE_MISSING: {state_id}")
        relative = raw.get("path")
        if not isinstance(relative, str) or not relative.strip():
            raise PackResolutionError(f"{state_id}: image path missing")
        image_path = (pack_dir / relative).resolve()
        if not _contained(image_path, pack_dir) or not image_path.is_file():
            raise PackResolutionError(f"{state_id}: image path is outside pack or missing")
        actual_sha = _sha256(image_path)
        declared_sha = str(raw.get("sha256", "")).lower()
        if actual_sha != declared_sha:
            raise PackResolutionError(f"{state_id}: image hash mismatch")
        width, height = _decode_rgba(image_path, state_id=state_id)
        declared_size = raw.get("canvas_size", [width, height])
        try:
            normalized_size = tuple(int(value) for value in declared_size)
        except (TypeError, ValueError):
            normalized_size = ()
        if normalized_size != (width, height):
            raise PackResolutionError(f"{state_id}: canvas_size mismatch")
        anchors = _validated_anchors(raw.get("anchors"), width=width, height=height, state_id=state_id)
        _verify_anchors_hit_art(
            image_path,
            anchors,
            state_id=state_id,
            anchor_names=("head", "seat_pelvis")
            if uses_exclusive_hands or semantic_contract_hint == C9_ARM_RIG_SEMANTIC_CONTRACT
            else ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r"),
        )
        hand_asset_path: Path | None = None
        hand_asset_sha: str | None = None
        if uses_exclusive_hands:
            hand_relative = raw.get("hand_asset_path")
            if not isinstance(hand_relative, str) or not hand_relative.strip():
                raise PackResolutionError(f"{state_id}: C7 hand asset path missing")
            hand_asset_path = (pack_dir / hand_relative).resolve()
            if not _contained(hand_asset_path, pack_dir) or not hand_asset_path.is_file():
                raise PackResolutionError(f"{state_id}: C7 hand asset path outside pack or missing")
            hand_asset_sha = _sha256(hand_asset_path)
            if hand_asset_sha != str(raw.get("hand_asset_sha256", "")).lower():
                raise PackResolutionError(f"{state_id}: C7 hand asset hash mismatch")
            _decode_rgba(hand_asset_path, state_id=f"{state_id}.hand_asset")
            _verify_anchors_hit_art(
                hand_asset_path,
                anchors,
                state_id=f"{state_id}.hand_asset",
                anchor_names=("hand_grip_l", "hand_grip_r"),
            )
        expected_book = "closed" if state_id.endswith("closed") else "open"
        if raw.get("pose") != "seated_holding_book_chest":
            raise PackResolutionError(f"{state_id}: pose must be seated_holding_book_chest")
        if raw.get("mouth") != "closed":
            raise PackResolutionError(f"{state_id}: mouth must be explicitly closed")
        if raw.get("book") != expected_book:
            raise PackResolutionError(f"{state_id}: book state must be {expected_book}")
        if raw.get("book_owner") != "source":
            raise PackResolutionError(f"{state_id}: book must be source-owned")
        arm_rig = (
            _validated_arm_rig(
                raw.get("arm_rig"),
                pack_dir=pack_dir,
                state_id=state_id,
                width=width,
                height=height,
            )
            if semantic_contract_hint == C9_ARM_RIG_SEMANTIC_CONTRACT
            else None
        )
        states[state_id] = {
            "state_id": state_id,
            "path": str(image_path),
            "relative_path": relative.replace("\\", "/"),
            "sha256": actual_sha,
            "size_bytes": image_path.stat().st_size,
            "canvas_size": [width, height],
            "anchors": anchors,
            "pose": raw["pose"],
            "mouth": raw["mouth"],
            "book": raw["book"],
            "book_owner": raw["book_owner"],
            "contact_semantics": raw.get("contact_semantics"),
            "hand_contact_patches": raw.get("hand_contact_patches"),
            "hand_asset_path": str(hand_asset_path) if hand_asset_path else None,
            "hand_asset_relative_path": hand_relative if hand_asset_path else None,
            "hand_asset_sha256": hand_asset_sha,
            "arm_rig": arm_rig,
        }

    semantic_review = _validated_semantic_review(
        payload,
        camera_view=camera_view,
        source_sha256=expected_source_sha256,
        states=states,
        allow_private_preview=allow_private_preview,
    )

    content_sha = _content_sha256(pack_id, version, camera_view, states)
    declared_content = str(payload.get("content_sha256", "")).lower()
    if declared_content != content_sha:
        raise PackResolutionError("PACK_CONTENT_HASH_MISMATCH")
    if expected_content_sha256 and content_sha != str(expected_content_sha256).lower():
        raise PackResolutionError("PACK_CONTENT_IDENTITY_MISMATCH")
    capabilities: dict[str, Any] = {
        key: (camera_view if key == "view_three_quarter_front" else True)
        for key in COMPAT_REQUIREMENTS
    }
    capabilities["validated_semantic_contract"] = semantic_contract_hint
    capabilities["effective_contact_policy"] = semantic_review.get("measurement_policy_revision")
    capabilities["exclusive_anatomy_ownership"] = (
        semantic_review.get("anatomy_ownership")
        if semantic_contract_hint in (C7_SEMANTIC_CONTRACT, C9_ARM_RIG_SEMANTIC_CONTRACT)
        else "source_prop_contact"
    )
    if semantic_contract_hint == C9_ARM_RIG_SEMANTIC_CONTRACT:
        capabilities["arm_rig"] = True
        capabilities["arm_rig_revision"] = C9_ARM_RIG_REVISION
        capabilities["arm_role_names"] = list(ARM_ROLE_NAMES)
    return {
        "pack_id": pack_id,
        "version": version,
        "approval_status": approval_status,
        "semantic_review_status": semantic_review["status"],
        "camera_view": camera_view,
        "root": str(pack_dir),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "content_sha256": content_sha,
        "states": states,
        "capabilities": capabilities,
        "semantic_review": semantic_review,
        "validated_contract": semantic_contract_hint,
        "source": "server_resolved_manifest",
    }


__all__ = [
    "ARM_JOINT_NAMES",
    "ARM_ROLE_NAMES",
    "C9_ARM_RIG_REVISION",
    "C9_ARM_RIG_SEMANTIC_CONTRACT",
    "PACK_MANIFEST_FILENAME",
    "PackResolutionError",
    "REQUIRED_ANCHORS",
    "REQUIRED_STATES",
    "resolve_versioned_pack",
]

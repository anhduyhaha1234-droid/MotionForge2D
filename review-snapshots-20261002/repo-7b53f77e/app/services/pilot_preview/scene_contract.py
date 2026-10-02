"""Source-locked scene contract for the V3 pilot window (R2).

Window: source frames 450..569 (inclusive, 120 frames) of the 30 s clip
``source-0040-0110.mp4`` (640x360, 30 fps, 900 frames). Output-local indices
0/60/119 map to source 450/510/569 — every diagnostic named 0/60/119 is
local, never a clip frame.

Roles (per-frame visibility + z-order, no single global layer order):
  character         gray-haired seated reader, left third (replace target)
  book              blue prop held at reader chest (source-sized prop)
  chair_occupied    dark-gray chair under the reader (rear layer)
  chair_spare       second dark-gray chair behind/under the woman (rear layer)
  chair_foreground  light-gray chair back, lower-right foreground (front layer)
  woman             brown-hair woman in magenta dress, center (seated on
                      dark-gray chair, same type as reader's; dress hem covers
                      lap, brown chair legs visible below)
  seated_back       black-haired back-view figure at table (mid-foreground)
  table             wooden table + diorama prop, right (mid layer)
  room              walls/curtain/floor + watermark (background layer)

Ground truth in this window (measured + vision-verified against real
decoded frames, never invented):
  - Reader seated for all 120 frames, both hands on the book at chest.
  - Book CLOSED (single solid blue cover, yellow badge visible at left)
    source 450..521, OPEN (two blue pages with dark center spine line,
    yellow badge occluded) source 522..569. Transition frame: 522
    (win-064..win-072 byte-identical closed; win-073 first open;
    insert-ROI mean step 0.405 -> 0.528 at 521->522).
  - The close-up of the book is a picture-in-picture insert box over the
    reader's chest, full-frame approx (235,210)-(295,285). Wide master
    stays locked; only the insert interior changes at the transition.
  - Reader mouth: closed line for all sampled frames (450/510/522/530/
    545/569). No open-mouth/speaking state exists in this window.
  - Woman SEATED for all 120 frames on a dark-gray chair of the same type
    as the reader's (gray seat band directly under her dress hem, brown
    wooden chair legs to the floor; zero bare legs/feet visible; hip
    height level with the seated reader).
  - Back-view figure seated, back to camera, no visible hands, all frames.
  - Watermark ``Lanh Vcl`` + play icon, bottom-left, all frames (source-only
    state: must be preserved as pixels, never reproduced as graphics).

Known R1 negative (after-frame-119, documented, not re-rendered here):
  - V3 hands-on-knees asset holds NOTHING: the open book is deleted.
  - R1 after-119 keeps the seated woman on her gray chair (comparison
    sheet: woman pixel-identical left/right); the candidate's fault at
    frame 119 is the leftover blue book smear behind/between the
    replacement boy's legs plus head/torso halo, i.e. incomplete removal
    of the source book, not a re-seat of the woman.

Coordinate spaces (explicit on every anchor):
  fullframe_px   pixel coordinates in the 640x360 decoded source frame.
  normalized     full-frame divided by (width, height), in [0,1]^2.
  bbox_local     pixel offset inside a role bbox (origin = bbox top-left).
  asset_local    pixel offset inside the replacement asset's native canvas.
Conversions are pure functions below; anchors always carry their space.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCENE_CONTRACT_VERSION = "pilot-preview-scene-v2"
SOURCE_WINDOW: tuple[int, int] = (450, 569)
WINDOW_FRAMES = 120
FRAME_WIDTH = 640
FRAME_HEIGHT = 360
FPS_NUM = 30
FPS_DEN = 1

# Immutable pins (re-hashed by running, never trusted from memory).
SOURCE_PINNED_SHA256 = "22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a"
SOURCE_PINNED_BYTES = 877221
ASSET_NEGATIVE_SHA256 = "e07e2a3a76ea3d7d3144ae43f89ebbcc225a37cf91aa6ab159961f6d7349dc47"
SAM2_PINNED_SHA256 = "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318"

LOCAL_TO_SOURCE = 450

ROLE_IDS = (
    "character",
    "book",
    "chair_occupied",
    "chair_spare",
    "chair_foreground",
    "woman",
    "seated_back",
    "table",
    "room",
)

COORDINATE_SPACES = ("fullframe_px", "normalized", "bbox_local", "asset_local")

ANCHOR_SPACES = ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r", "book_corners", "supports")

# Event ledger: (first_source, last_source, kind, detail). Only states
# actually observed in decoded frames; no invented states.
EVENT_LEDGER: tuple[dict[str, Any], ...] = (
    {
        "kind": "book_state",
        "first_source": 450,
        "last_source": 521,
        "state": "closed",
        "evidence": "PiP insert src450..src521 (win-001..win-072): single solid blue "
        "cover, yellow badge at left; win-064..win-072 byte-identical",
    },
    {
        "kind": "book_state",
        "first_source": 522,
        "last_source": 569,
        "state": "open",
        "evidence": "insert strip src513..src524: last closed src521, first open "
        "src522 (two blue pages, dark center spine, badge occluded); "
        "insert-ROI mid-blue step 0.405 -> 0.528 at 521->522; open holds "
        "through src569 (white page V + badge triangle behind gutter)",
    },
    {
        "kind": "pose",
        "first_source": 450,
        "last_source": 569,
        "role": "character",
        "state": "seated_holding_book_chest",
        "evidence": "full frames src450/src510/src522/src545/src569: seated, "
        "both hands on book at chest, all samples",
    },
    {
        "kind": "pose",
        "first_source": 450,
        "last_source": 569,
        "role": "woman",
        "state": "seated_same_chair_type",
        "evidence": "full frames src450/src522/src569: gray seat band directly under "
        "dress hem + brown wooden chair legs to floor, zero bare legs/feet, "
        "hip height level with seated reader; R1 after-119 keeps her seated "
        "unchanged (comparison sheet pixel-identical)",
    },
    {
        "kind": "pose",
        "first_source": 450,
        "last_source": 569,
        "role": "seated_back",
        "state": "seated_back_to_camera_no_visible_hands",
        "evidence": "full frames src450/src522/src545/src569 zooms: no hand near face",
    },
    {
        "kind": "mouth",
        "first_source": 450,
        "last_source": 569,
        "role": "character",
        "state": "closed",
        "evidence": "reader zooms src450/src510/src522/src530/src545: short line/dot, "
        "never open; no speaking state exists in this window",
    },
    {
        "kind": "mouth",
        "first_source": 450,
        "last_source": 569,
        "role": "woman",
        "state": "closed",
        "evidence": "full frames src510/src545: closed pink lips, not speaking",
    },
    {
        "kind": "watermark",
        "first_source": 450,
        "last_source": 569,
        "state": "source_only_preserve_pixels",
        "evidence": "all full frames: red play icon + 'Lanh Vcl' bottom-left",
    },
)

# Per-role z-order bands (lower renders first). Bands, not a single global
# order: within a band the contract lists explicit pairwise rules.
Z_BANDS: dict[str, int] = {
    "room": 0,
    "chair_occupied": 1,
    "chair_spare": 1,
    "character": 2,
    "book": 3,
    "woman": 2,
    "table": 2,
    "seated_back": 3,
    "chair_foreground": 4,
}

# Fail-closed compatibility requirements: every key must be present in a
# candidate pack's capability map with a truthy/coverage value, else the
# pack is rejected BEFORE heavy work. Mirrors TARGET_PROFILE §5 dimensions.
COMPAT_REQUIREMENTS: tuple[str, ...] = (
    "seated_pose",
    "grip_both_hands_chest",
    "book_open_variant",
    "book_closed_variant",
    "mouth_closed_state",
    "view_three_quarter_front",
    "alpha_genuine",
    "anchor_head",
    "anchor_seat_pelvis",
    "anchor_hand_grip_l",
    "anchor_hand_grip_r",
    "anchor_book_corners",
)

# Documented failures of the intentional negative fixture (V3 hands-on-knees
# asset + R1 after-119). A compatible pack must not reproduce any of these.
NEGATIVE_KNOWN_FAILURES: tuple[str, ...] = (
    "book_deleted_hands_empty_on_knees",
    "r1_after119_leftover_blue_book_smear_between_legs_plus_halo",
    "no_open_book_variant_for_src522_onwards",
    "no_mouth_open_state_but_window_needs_none",
)


class SceneContractError(ValueError):
    """Fail-closed rejection with a human-readable reason."""


def local_to_source(local: int) -> int:
    """Output-local index (0..119) -> source frame (450..569)."""
    if not 0 <= local <= 119:
        raise SceneContractError(f"local index out of window: {local}")
    return LOCAL_TO_SOURCE + local


def source_to_local(source: int) -> int:
    """Source frame (450..569) -> output-local index (0..119)."""
    if not SOURCE_WINDOW[0] <= source <= SOURCE_WINDOW[1]:
        raise SceneContractError(f"source frame out of window 450..569: {source}")
    return source - LOCAL_TO_SOURCE


def anchor_fullframe_to_normalized(x_px: float, y_px: float) -> tuple[float, float]:
    """fullframe_px -> normalized."""
    return (x_px / FRAME_WIDTH, y_px / FRAME_HEIGHT)


def anchor_fullframe_to_bbox_local(
    x_px: float, y_px: float, bbox_xywh_px: tuple[float, float, float, float]
) -> tuple[float, float]:
    """fullframe_px -> bbox_local (origin at bbox top-left)."""
    bx, by, _, _ = bbox_xywh_px
    return (x_px - bx, y_px - by)


def build_scene_contract(
    *,
    source_sha256: str,
    annotation_rev: str = "r2-20260908",
    pack_id: str = "none",
    pack_sha256: str = "",
) -> dict[str, Any]:
    """Build the deterministic scene contract dict for the fixed window."""
    frames: list[dict[str, Any]] = []
    for local in range(WINDOW_FRAMES):
        source = local_to_source(local)
        book_open = source >= 522
        frames.append(
            {
                "local": local,
                "source": source,
                "roles": {
                    "character": {
                        "visible": True,
                        "z_band": Z_BANDS["character"],
                        "pose": "seated_holding_book_chest",
                        "mouth": "closed",
                    },
                    "book": {
                        "visible": True,
                        "z_band": Z_BANDS["book"],
                        "state": "open" if book_open else "closed",
                    },
                    "chair_occupied": {"visible": True, "z_band": Z_BANDS["chair_occupied"]},
                    "chair_spare": {"visible": True, "z_band": Z_BANDS["chair_spare"]},
                    "chair_foreground": {"visible": True, "z_band": Z_BANDS["chair_foreground"]},
                    "woman": {
                        "visible": True,
                        "z_band": Z_BANDS["woman"],
                        "pose": "seated_same_chair_type",
                        "mouth": "closed",
                    },
                    "seated_back": {
                        "visible": True,
                        "z_band": Z_BANDS["seated_back"],
                        "pose": "seated_back_to_camera_no_visible_hands",
                    },
                    "table": {"visible": True, "z_band": Z_BANDS["table"]},
                    "room": {
                        "visible": True,
                        "z_band": Z_BANDS["room"],
                        "watermark": "source_only_preserve_pixels",
                    },
                },
            }
        )
    return {
        "contract": SCENE_CONTRACT_VERSION,
        "annotation_rev": annotation_rev,
        "window": {"first_source": SOURCE_WINDOW[0], "last_source": SOURCE_WINDOW[1], "frames": WINDOW_FRAMES},
        "timebase": {"fps_num": FPS_NUM, "fps_den": FPS_DEN, "width": FRAME_WIDTH, "height": FRAME_HEIGHT},
        "source": {"sha256": source_sha256, "bytes": SOURCE_PINNED_BYTES},
        "pack": {"pack_id": pack_id, "pack_sha256": pack_sha256},
        "coordinate_spaces": list(COORDINATE_SPACES),
        "anchor_spaces": list(ANCHOR_SPACES),
        "roles": list(ROLE_IDS),
        "z_bands": dict(Z_BANDS),
        "events": [dict(entry) for entry in EVENT_LEDGER],
        "known_negative_failures": list(NEGATIVE_KNOWN_FAILURES),
        "frames": frames,
    }


def scene_contract_hash(contract: dict[str, Any]) -> str:
    """Deterministic SHA-256 over canonical JSON (sorted keys, compact)."""
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_scene_contract(contract: dict[str, Any]) -> None:
    """Fail-closed structural validation. Raises SceneContractError."""
    if contract.get("contract") != SCENE_CONTRACT_VERSION:
        raise SceneContractError(f"wrong contract version: {contract.get('contract')!r}")
    window = contract.get("window", {})
    if (window.get("first_source"), window.get("last_source")) != SOURCE_WINDOW:
        raise SceneContractError(f"window must be 450..569, got {window!r}")
    if contract.get("source", {}).get("sha256") != SOURCE_PINNED_SHA256:
        raise SceneContractError("source sha256 mismatch: contract is not bound to the pinned source")
    frames = contract.get("frames", [])
    if len(frames) != WINDOW_FRAMES:
        raise SceneContractError(f"expected 120 per-frame entries, got {len(frames)}")
    for position, entry in enumerate(frames):
        if entry.get("local") != position:
            raise SceneContractError(f"frame {position}: local index mismatch")
        if entry.get("source") != LOCAL_TO_SOURCE + position:
            raise SceneContractError(f"frame {position}: source mapping must be local+450")
        roles = entry.get("roles", {})
        missing = [role for role in ROLE_IDS if role not in roles]
        if missing:
            raise SceneContractError(f"frame {position}: missing roles {missing}")
    events = contract.get("events", [])
    if len(events) != len(EVENT_LEDGER):
        raise SceneContractError("event ledger length mismatch: states must not be added or dropped")


def check_pack_compatibility(capabilities: dict[str, Any]) -> None:
    """Fail-closed asset-pack gate. Raises SceneContractError naming gaps.

    MUST run before heavy work (SAM2/render). Any missing seated / grip /
    pose / mouth / view / alpha / anchor coverage is a readable reject.
    """
    if not isinstance(capabilities, dict):
        raise SceneContractError("pack incompatible: capability map is not an object")
    missing: list[str] = []
    for key in COMPAT_REQUIREMENTS:
        value = capabilities.get(key)
        # Boolean fields are deliberately strict.  JSON 1/0 and the strings
        # "true"/"false" are not server evidence.
        if key == "view_three_quarter_front":
            if not isinstance(value, str) or "three_quarter" not in value:
                missing.append(key)
        elif type(value) is not bool or value is not True:
            missing.append(key)
    if missing:
        raise SceneContractError(
            "pack incompatible, missing coverage: " + ", ".join(missing)
            + " (negative fixture V3-hands-on-knees fails: "
            + "; ".join(NEGATIVE_KNOWN_FAILURES[:2]) + ")"
        )
    view = capabilities["view_three_quarter_front"]
    if view not in ("three_quarter_front_this_window", "three_quarter_front"):
        raise SceneContractError(
            f"pack incompatible: wrong camera view {view!r}, need this-window seated view"
        )

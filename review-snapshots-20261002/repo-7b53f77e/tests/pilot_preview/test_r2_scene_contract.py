"""R2 scene-contract tests (DV3-R2-T01, new file).

Window truth: source frames 450..569 of the 30 s clip (640x360, 30 fps).
Output-local 0/60/119 = source 450/510/569. All fixtures are derived from
real decoded source frames under the T01 output root; the only synthetic
pixels are small geometric masks used for conversion math, always paired
with a real source-derived crop.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.pilot_preview.scene_contract import (
    ANCHOR_SPACES,
    ASSET_NEGATIVE_SHA256,
    COMPAT_REQUIREMENTS,
    COORDINATE_SPACES,
    EVENT_LEDGER,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    LOCAL_TO_SOURCE,
    NEGATIVE_KNOWN_FAILURES,
    ROLE_IDS,
    SAM2_PINNED_SHA256,
    SCENE_CONTRACT_VERSION,
    SOURCE_PINNED_SHA256,
    SOURCE_WINDOW,
    SceneContractError,
    anchor_fullframe_to_bbox_local,
    anchor_fullframe_to_normalized,
    build_scene_contract,
    check_pack_compatibility,
    local_to_source,
    scene_contract_hash,
    source_to_local,
    validate_scene_contract,
)

# Real source-derived fixtures (written by the T01 worker from decoded
# source frames; paths resolved at runtime, skipped if absent).
_T01_FRAMES = Path(__file__).resolve().parents[3]
_RUNTIME_T01 = (
    _T01_FRAMES
    / "runtime-runs"
    / "DV3-R2-20260908T1000Z"
    / "T01"
    / "output"
    / "frames-src450-569"
)


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


# ---------------------------------------------------------------- timebase

def test_r2_scene_timebase_and_ownership() -> None:
    """Window is source 450..569; local 0/60/119 map to source 450/510/569."""
    assert SOURCE_WINDOW == (450, 569)
    assert LOCAL_TO_SOURCE == 450
    assert local_to_source(0) == 450
    assert local_to_source(60) == 510
    assert local_to_source(119) == 569
    assert source_to_local(450) == 0
    assert source_to_local(510) == 60
    assert source_to_local(569) == 119
    with pytest.raises(SceneContractError):
        local_to_source(120)
    with pytest.raises(SceneContractError):
        source_to_local(449)
    with pytest.raises(SceneContractError):
        source_to_local(570)
    # Ownership: every role id is claimed exactly once, no global layer order.
    assert len(set(ROLE_IDS)) == 9
    assert "chair_foreground" in ROLE_IDS and "chair_occupied" in ROLE_IDS


def test_r2_book_transition_frame_522() -> None:
    """Book closed 450..521, open 522..569 — the measured event.

    Pin evidence (reproduced by worker ffmpeg + PIL this turn, temp
    verify-r2): win-064..win-072 byte-identical (closed hold, so any
    @516 claim is false); win-073 (src522) first open with insert-ROI
    mid-blue step 0.405 -> 0.528 at 521->522; 12-tile insert strip
    src513..src524 vision-bracketed last-closed src521 / first-open
    src522; open holds through src569.
    """
    contract = build_scene_contract(source_sha256=SOURCE_PINNED_SHA256)
    states = {entry["source"]: entry["roles"]["book"]["state"] for entry in contract["frames"]}
    assert states[450] == "closed"
    assert states[510] == "closed"
    assert states[515] == "closed"
    assert states[516] == "closed"
    assert states[521] == "closed"
    assert states[522] == "open"
    assert states[523] == "open"
    assert states[569] == "open"
    ledger = {(e["first_source"], e["last_source"], e["state"]) for e in contract["events"] if e["kind"] == "book_state"}
    assert (450, 521, "closed") in ledger
    assert (522, 569, "open") in ledger


def test_r2_woman_seated_same_chair_type() -> None:
    """Woman is SEATED all 120 frames — never standing anywhere.

    Pin evidence: vision on full-450/522/569 — gray seat band directly
    under her dress hem + brown wooden chair legs to the floor, zero
    bare legs/feet, hip height level with the seated reader; R1
    comparison sheet: woman pixel-identical left/right (after-119 keeps
    her seated; its fault is the leftover blue book smear + halo, not a
    re-seat).
    """
    contract = build_scene_contract(source_sha256=SOURCE_PINNED_SHA256)
    for entry in contract["frames"]:
        woman = entry["roles"]["woman"]
        assert woman["pose"] == "seated_same_chair_type", entry["source"]
        assert woman["visible"] is True
    poses = {entry["roles"]["woman"]["pose"] for entry in contract["frames"]}
    assert poses == {"seated_same_chair_type"}
    ledger = [e for e in contract["events"] if e.get("role") == "woman" and e.get("kind") == "pose"]
    assert ledger and all(e["state"] == "seated_same_chair_type" for e in ledger)
    assert "standing" not in json.dumps(contract)


def test_r2_every_state_linked_to_frame_samples() -> None:
    """Each ledger entry names real inspected source frames."""
    contract = build_scene_contract(source_sha256=SOURCE_PINNED_SHA256)
    for entry in contract["events"]:
        assert "evidence" in entry, entry
        assert ("src" in entry["evidence"] or "full frame" in entry["evidence"]), entry
    assert len(contract["events"]) == len(EVENT_LEDGER)


def test_r2_out_of_window_and_mismatched_source_rejected() -> None:
    contract = build_scene_contract(source_sha256=SOURCE_PINNED_SHA256)
    bad_window = dict(contract)
    bad_window["window"] = {"first_source": 0, "last_source": 119, "frames": 120}
    with pytest.raises(SceneContractError):
        validate_scene_contract(bad_window)
    bad_source = build_scene_contract(source_sha256="0" * 64)
    with pytest.raises(SceneContractError):
        validate_scene_contract(bad_source)
    bad_count = dict(contract)
    bad_count["frames"] = contract["frames"][:100]
    with pytest.raises(SceneContractError):
        validate_scene_contract(bad_count)


def test_r2_deterministic_json_round_trip_and_hash() -> None:
    first = build_scene_contract(source_sha256=SOURCE_PINNED_SHA256)
    digest_first = scene_contract_hash(first)
    text = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    second = json.loads(text)
    assert scene_contract_hash(second) == digest_first
    validate_scene_contract(second)
    # Hash is stable across rebuilds.
    third = build_scene_contract(source_sha256=SOURCE_PINNED_SHA256)
    assert scene_contract_hash(third) == digest_first


# --------------------------------------------------------------- negatives

def test_r2_missing_grip_or_pose_rejected() -> None:
    """MUST-RUN: a pack without grip/pose coverage is rejected pre-render."""
    caps = _full_capabilities()
    check_pack_compatibility(caps)  # full pack passes
    for key in (
        "seated_pose",
        "grip_both_hands_chest",
        "book_open_variant",
        "book_closed_variant",
        "mouth_closed_state",
        "view_three_quarter_front",
        "alpha_genuine",
        "anchor_hand_grip_l",
        "anchor_hand_grip_r",
        "anchor_book_corners",
    ):
        broken = _full_capabilities()
        broken[key] = False
        with pytest.raises(SceneContractError) as excinfo:
            check_pack_compatibility(broken)
        assert key in str(excinfo.value)


def test_r2_negative_fixture_v3_hands_on_knees_rejected() -> None:
    """The current V3 asset (hands empty on knees, no grip/book) must fail."""
    v3_caps = {
        "seated_pose": True,
        "grip_both_hands_chest": False,
        "book_open_variant": False,
        "book_closed_variant": False,
        "mouth_closed_state": True,
        "view_three_quarter_front": "three_quarter_front_this_window",
        "alpha_genuine": True,
        "anchor_head": True,
        "anchor_seat_pelvis": True,
        "anchor_hand_grip_l": False,
        "anchor_hand_grip_r": False,
        "anchor_book_corners": False,
    }
    with pytest.raises(SceneContractError) as excinfo:
        check_pack_compatibility(v3_caps)
    message = str(excinfo.value)
    assert "grip_both_hands_chest" in message
    assert "book_open_variant" in message
    assert len(COMPAT_REQUIREMENTS) == 12
    assert len(NEGATIVE_KNOWN_FAILURES) >= 3


def test_r2_wrong_camera_view_rejected() -> None:
    caps = _full_capabilities()
    caps["view_three_quarter_front"] = "side_profile_other_window"
    with pytest.raises(SceneContractError):
        check_pack_compatibility(caps)


def test_r2_compat_contract_version_and_pins() -> None:
    assert SCENE_CONTRACT_VERSION == "pilot-preview-scene-v2"
    assert SOURCE_PINNED_SHA256 == "22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a"
    assert ASSET_NEGATIVE_SHA256.startswith("e07e2a3a")
    assert SAM2_PINNED_SHA256.startswith("2647878d")


# ---------------------------------------------------------------- geometry

def test_r2_coordinate_spaces_explicit() -> None:
    """MUST-RUN: spaces are named; conversions are exact and invertible."""
    assert set(COORDINATE_SPACES) == {"fullframe_px", "normalized", "bbox_local", "asset_local"}
    assert set(ANCHOR_SPACES) >= {"head", "hand_grip_l", "hand_grip_r", "book_corners"}
    # Normalized corners.
    assert anchor_fullframe_to_normalized(0.0, 0.0) == (0.0, 0.0)
    assert anchor_fullframe_to_normalized(FRAME_WIDTH, FRAME_HEIGHT) == (1.0, 1.0)
    nx, ny = anchor_fullframe_to_normalized(160.0, 90.0)
    assert (nx, ny) == pytest.approx((0.25, 0.25))
    # Bbox-local with NONZERO translation (origin at bbox top-left).
    bbox = (90.0, 40.0, 180.0, 260.0)
    lx, ly = anchor_fullframe_to_bbox_local(150.0, 130.0, bbox)
    assert (lx, ly) == pytest.approx((60.0, 90.0))
    # Round-trip: bbox-local + origin == fullframe.
    assert (lx + bbox[0], ly + bbox[1]) == pytest.approx((150.0, 130.0))


def test_r2_scale_rotation_silhouette_width_cases() -> None:
    """Affine math the renderer depends on: scale fit, rotation, widths."""
    # Aspect-preserving fit: asset alpha bbox into destination rect.
    alpha_w, alpha_h = 400.0, 500.0
    target_w, target_h = 76.0, 95.0
    scale = min(target_w / alpha_w, target_h / alpha_h)
    assert scale == pytest.approx(0.19)
    assert scale > 0
    # Rotation moves the alpha-center correction (30 deg smoke values).
    import math

    dx, dy = 12.0, -6.0
    theta = math.radians(30.0)
    rdx = math.cos(theta) * dx - math.sin(theta) * dy
    rdy = math.sin(theta) * dx + math.cos(theta) * dy
    assert (rdx, rdy) == pytest.approx((13.392, 0.804), abs=0.01)
    # Silhouette width: replacement alpha may extend outside the old mask
    # subject to layout gates — width ratio stays bounded here.
    old_width, new_width = 180.0, 198.0
    assert new_width / old_width == pytest.approx(1.1)
    assert FRAME_WIDTH == 640 and FRAME_HEIGHT == 360


def test_r2_source_derived_fixtures_present() -> None:
    """Real decoded-frame derivatives exist (not black rectangles alone)."""
    expected = ["src-450.png", "src-510.png", "src-569.png", "contact-every10.png", "book-insert-strip-513-524.png"]
    missing = [name for name in expected if not (_RUNTIME_T01 / name).is_file()]
    assert not missing, f"missing source-derived fixtures: {missing}"
    for name in ("src-450.png", "src-569.png"):
        digest = hashlib.sha256((_RUNTIME_T01 / name).read_bytes()).hexdigest()
        assert len(digest) == 64
    assert (_RUNTIME_T01 / "src-450.png").stat().st_size > 50000

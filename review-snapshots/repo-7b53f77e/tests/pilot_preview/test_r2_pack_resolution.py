"""Server-owned versioned-pack resolution tests.

The tiny RGBA files here are engineering fixtures only.  They exercise file
ownership, hashing, alpha, state, and anchor validation; they are not demo
artwork and cannot authorize a visual render.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.pilot_preview.asset_pack import (
    PackResolutionError,
    _content_sha256,
    resolve_versioned_pack,
)
from app.services.pilot_preview.scene_contract import COMPAT_REQUIREMENTS, SceneContractError, check_pack_compatibility
from app.workflow.pilot_preview_jobs import pack_gate_verdict


def _write_engineering_pack(root: Path, pack_id: str = "engineering-pack-v1") -> tuple[Path, str, dict]:
    pack_dir = root / pack_id
    pack_dir.mkdir(parents=True)
    anchors = {
        "head": [40.0, 28.0],
        "seat_pelvis": [40.0, 166.0],
        # Inverse of the real 640x360 affine fit for the source contacts;
        # these are not the old guessed same-y values.
        "hand_grip_l": [17.0, 121.0],
        "hand_grip_r": [63.0, 121.0],
        "book_corners": [[24.0, 76.0], [56.0, 76.0], [56.0, 112.0], [24.0, 112.0]],
    }
    states: dict[str, dict] = {}
    for state_id, colour in (
        ("seated_book_closed", (190, 90, 40, "closed")),
        ("seated_book_open", (170, 110, 55, "open")),
    ):
        image = np.zeros((200, 80, 4), dtype=np.uint8)
        image[20:180, 15:65, :3] = colour[:3]
        image[20:180, 15:65, 3] = 255
        path = pack_dir / f"{state_id}.png"
        assert cv2.imwrite(str(path), image)
        state_anchors = {**anchors}
        if state_id == "seated_book_open":
            # The open-state source book shifts down/right; its local hand
            # anchors are independently fitted rather than replaying closed
            # evidence.
            state_anchors["hand_grip_l"] = [20.0, 128.0]
            state_anchors["hand_grip_r"] = [60.0, 128.0]
        states[state_id] = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "canvas_size": [80, 200],
            "anchors": state_anchors,
            "pose": "seated_holding_book_chest",
            "mouth": "closed",
            "book": colour[3],
            "book_owner": "source",
            "contact_semantics": {
                "kind": "replacement_hand_to_source_book_boundary",
                "book_owner": "source",
                "source_role": "book",
            },
            "hand_contact_patches": {
                "left": {"contact_local": state_anchors["hand_grip_l"], "bbox_xywh": [12, 105, 18, 25]},
                "right": {"contact_local": state_anchors["hand_grip_r"], "bbox_xywh": [50, 105, 18, 25]},
            },
        }
    content_sha = _content_sha256(pack_id, "engineering-v1", "three_quarter_front_this_window", states)
    source_sha = "a" * 64
    measurements = {}
    for frame in (450, 510, 521, 522, 523, 569):
        active = "seated_book_closed" if frame < 522 else "seated_book_open"
        inactive = "seated_book_open" if frame < 522 else "seated_book_closed"
        measurements[str(frame)] = {
            active: {
                contact: 0.0
                for contact in ("head", "seat_pelvis", "hand_grip_l", "hand_grip_r", "book_corners")
            },
            inactive: {"not_applicable": True},
        }
    manifest = {
        "pack_id": pack_id,
        "version": "engineering-v1",
        "camera_view": "three_quarter_front_this_window",
        "content_sha256": content_sha,
        "approval": {"status": "APPROVED", "approved_by": "engineering-test-fixture", "approved_at": "2026-09-09T00:00:00Z"},
        "compatibility_review": {
            "status": "APPROVED",
            "reviewer": "engineering-test-fixture",
            "reviewed_at": "2026-09-09T00:00:00Z",
            "camera_view": "three_quarter_front_this_window",
            "anchor_head_role": "replacement_character",
            "anchor_seat_pelvis_role": "replacement_character",
            "seat_reference": "occupied_chair_seat",
            "pose_compatible": True,
            "book_contact_compatible": True,
            "book_owner": "source",
            "semantic_contract_revision": "c6-source-prop-contact-v2",
            "measurement_policy_revision": "source-prop-boundary-contact-v2",
            "source_contact_annotation_digest": "a" * 64,
            "source_frame_samples": [450, 510, 521, 522, 523, 569],
            "source_sha256": source_sha,
            "artwork_sha256": {state_id: state["sha256"] for state_id, state in states.items()},
            "contact_measurements": measurements,
        },
        "states": states,
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return root, content_sha, manifest


def test_r2_server_resolves_actual_files_hashes_and_anchors(tmp_path: Path) -> None:
    root, content_sha, _manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs")
    resolved = resolve_versioned_pack("engineering-pack-v1", root, expected_content_sha256=content_sha)
    assert resolved["content_sha256"] == content_sha
    assert resolved["capabilities"]["view_three_quarter_front"] == "three_quarter_front_this_window"
    assert all(resolved["capabilities"][key] for key in COMPAT_REQUIREMENTS if key != "view_three_quarter_front")
    assert set(resolved["states"]) == {"seated_book_closed", "seated_book_open"}
    assert Path(resolved["states"]["seated_book_closed"]["path"]).is_file()
    assert resolved["states"]["seated_book_closed"]["anchors"]["seat_pelvis"] == [40.0, 166.0]


def test_r2_client_capabilities_cannot_override_server_pack(tmp_path: Path) -> None:
    root, content_sha, _manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs")
    claimed = {key: False for key in COMPAT_REQUIREMENTS}
    claimed["view_three_quarter_front"] = "side_profile"
    verdict = pack_gate_verdict(
        {
            "pack_id": "engineering-pack-v1",
            "pack_root": str(root),
            "asset_sha256": content_sha,
            "source_sha256": "a" * 64,
            "pack_capabilities": claimed,
        }
    )
    assert verdict["compatible"] is True
    assert verdict["capabilities"]["view_three_quarter_front"] == "three_quarter_front_this_window"


def test_r2_pack_file_tamper_and_path_ownership_fail_closed(tmp_path: Path) -> None:
    root, _content_sha, _manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs")
    closed = root / "engineering-pack-v1" / "seated_book_closed.png"
    closed.write_bytes(closed.read_bytes() + b"tamper")
    with pytest.raises(PackResolutionError, match="image hash mismatch"):
        resolve_versioned_pack("engineering-pack-v1", root)

    root2, _content_sha2, manifest = _write_engineering_pack(tmp_path / "other" / "assets" / "pilot-packs", "owned-pack-v1")
    manifest["states"]["seated_book_open"]["path"] = "../outside.png"
    (root2 / "owned-pack-v1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackResolutionError, match="outside pack or missing"):
        resolve_versioned_pack("owned-pack-v1", root2)


def test_r2_draft_pack_is_not_production_resolvable(tmp_path: Path) -> None:
    root, _content_sha, manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs", "draft-pack-v1")
    manifest["approval"] = {"status": "DRAFT_NOT_APPROVED"}
    (root / "draft-pack-v1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackResolutionError, match="PACK_NOT_APPROVED"):
        resolve_versioned_pack("draft-pack-v1", root)


def test_private_preview_candidate_is_pilot_only(tmp_path: Path) -> None:
    root, content_sha, manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs", "preview-pack-v1")
    manifest["approval"]["status"] = "PRIVATE_PREVIEW_INPUT_READY"
    manifest["compatibility_review"]["status"] = "PRIVATE_PREVIEW_INPUT_READY"
    (root / "preview-pack-v1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackResolutionError, match="PACK_NOT_APPROVED"):
        resolve_versioned_pack("preview-pack-v1", root, expected_content_sha256=content_sha)
    resolved = resolve_versioned_pack(
        "preview-pack-v1",
        root,
        expected_content_sha256=content_sha,
        expected_source_sha256="a" * 64,
        allow_private_preview=True,
    )
    assert resolved["approval_status"] == "PRIVATE_PREVIEW_INPUT_READY"


def test_r2_bool_string_camera_view_is_not_semantic_compatibility() -> None:
    caps = {key: True for key in COMPAT_REQUIREMENTS}
    caps["view_three_quarter_front"] = True
    with pytest.raises(SceneContractError):
        check_pack_compatibility(caps)
    caps["view_three_quarter_front"] = "three_quarter_front_this_window"
    caps["alpha_genuine"] = "true"
    with pytest.raises(SceneContractError):
        check_pack_compatibility(caps)


def test_r2_negative_contact_measurement_is_rejected(tmp_path: Path) -> None:
    root, _content_sha, manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs", "negative-contact-v1")
    manifest["compatibility_review"]["contact_measurements"]["521"]["seated_book_closed"]["seat_pelvis"] = -999.0
    (root / "negative-contact-v1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackResolutionError, match="contact error must be finite"):
        resolve_versioned_pack("negative-contact-v1", root)


def test_c7_server_binds_exclusive_hand_asset_and_semantic_contract(tmp_path: Path) -> None:
    """C7 resolves a body plus owned hand asset; path/hash tamper is fatal."""
    root, _content_sha, manifest = _write_engineering_pack(tmp_path / "assets" / "pilot-packs", "c7-pack-v1")
    pack_dir = root / "c7-pack-v1"
    review = manifest["compatibility_review"]
    review.update({
        "semantic_contract_revision": "c7-exclusive-anatomy-v1",
        "anatomy_ownership": "exclusive_body_and_hand_asset",
        "body_hand_ownership": "body_only_no_hands",
    })
    for state_id, state in manifest["states"].items():
        hand_name = f"{state_id}-hands.png"
        hand_path = pack_dir / hand_name
        hand_path.write_bytes((pack_dir / state["path"]).read_bytes())
        state["hand_asset_path"] = hand_name
        state["hand_asset_sha256"] = hashlib.sha256(hand_path.read_bytes()).hexdigest()
        state["contact_semantics"] = {"anatomy_ownership": "exclusive_body_and_hand_asset"}
        state["hand_contact_patches"] = {
            "left": {"polygon": [[15, 110], [25, 110], [25, 130], [15, 130]]},
            "right": {"polygon": [[55, 110], [65, 110], [65, 130], [55, 130]]},
        }
    manifest["version"] = "c7-exclusive-anatomy-v1"
    manifest["content_sha256"] = _content_sha256(
        manifest["pack_id"], manifest["version"], manifest["camera_view"], manifest["states"]
    )
    (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    resolved = resolve_versioned_pack("c7-pack-v1", root, expected_content_sha256=manifest["content_sha256"])
    assert resolved["states"]["seated_book_closed"]["hand_asset_sha256"] == manifest["states"]["seated_book_closed"]["hand_asset_sha256"]
    manifest["states"]["seated_book_open"]["hand_asset_path"] = "../outside-hands.png"
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackResolutionError, match="hand asset path outside pack or missing"):
        resolve_versioned_pack("c7-pack-v1", root)


def test_c8_pack_rejects_substituted_contact_evidence(tmp_path: Path) -> None:
    """Runtime schedule rejects a manifest value that is not its measured residual."""
    import shutil

    from app.services.pilot_preview.scene_contract import SOURCE_PINNED_SHA256
    from app.workflow.pilot_preview_jobs import PilotPreviewError, _build_composition_schedule

    fixture_root = os.environ.get("MOTIONFORGE_PILOT_FIXTURE_ROOT")
    if not fixture_root:
        pytest.skip("MOTIONFORGE_PILOT_FIXTURE_ROOT is required for the real pack fixture")
    c8_root = Path(fixture_root).resolve()
    pack_root = tmp_path / "packs"
    shutil.copytree(c8_root / "assets" / "pilot-packs" / "luna-reader-seated-c7-v1", pack_root / "luna-reader-seated-c7-v1")
    manifest_path = pack_root / "luna-reader-seated-c7-v1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["compatibility_review"]["contact_measurements"]["450"]["seated_book_closed"]["hand_grip_l"] = 0.0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    pack = resolve_versioned_pack("luna-reader-seated-c7-v1", pack_root, expected_source_sha256=SOURCE_PINNED_SHA256, allow_private_preview=True)
    with pytest.raises(PilotPreviewError, match="CONTACT_MEASUREMENT_MANIFEST_RUNTIME_MISMATCH"):
        _build_composition_schedule({"start_frame": 450, "end_frame": 570, "source_sha256": SOURCE_PINNED_SHA256}, pack)


def test_c8_contract_dispatch_rejects_unknown_semantic_contract(tmp_path: Path) -> None:
    """A version prefix cannot authorize an unvalidated semantic contract."""
    import shutil

    fixture_root = os.environ.get("MOTIONFORGE_PILOT_FIXTURE_ROOT")
    if not fixture_root:
        pytest.skip("MOTIONFORGE_PILOT_FIXTURE_ROOT is required for the real pack fixture")
    c8_root = Path(fixture_root).resolve()
    pack_root = tmp_path / "packs"
    shutil.copytree(c8_root / "assets" / "pilot-packs" / "luna-reader-seated-c7-v1", pack_root / "luna-reader-seated-c7-v1")
    manifest_path = pack_root / "luna-reader-seated-c7-v1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["compatibility_review"]["semantic_contract_revision"] = "c8-unvalidated-contract"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PackResolutionError, match="PACK_CONTACT_SEMANTIC_CONTRACT_UNKNOWN"):
        resolve_versioned_pack("luna-reader-seated-c7-v1", pack_root, allow_private_preview=True)

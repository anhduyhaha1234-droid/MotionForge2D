"""C9 independent-arm, raster, and true-contact regression tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.pilot_preview.arm_rig import (
    ArmRigError,
    build_arm_rig_plan,
    solve_two_bone_ik,
    validate_arm_rig_frame,
    warp_rgba_inverse,
)
from app.services.pilot_preview.pose_composition import (
    fit_layer_transform,
    measure_contact_residual,
    source_anchors_fullframe_px,
    validate_contact_measurement,
)


def _c9_pack() -> dict:
    from app.services.pilot_preview.asset_pack import resolve_versioned_pack

    root = Path(os.environ.get("MOTIONFORGE_C9_PACK_ROOT", ""))
    if not root.is_dir():
        pytest.skip("MOTIONFORGE_C9_PACK_ROOT is required for C9 pack tests")
    return resolve_versioned_pack(
        "luna-reader-arm-rig-c9-v1",
        root,
        expected_source_sha256="22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a",
        allow_private_preview=True,
    )


def test_two_bone_ik_is_constrained_and_rejects_unreachable_target() -> None:
    result = solve_two_bone_ik((0.0, 0.0), (7.0, 2.0), 5.0, 4.0, 1)
    assert result["unreachable"] is False
    assert result["grip"] == [7.0, 2.0]
    assert np.linalg.norm(np.asarray(result["elbow"]) - np.asarray(result["shoulder"])) == pytest.approx(5.0, abs=1e-5)
    assert np.linalg.norm(np.asarray(result["wrist"]) - np.asarray(result["elbow"])) == pytest.approx(4.0, abs=1e-5)
    with pytest.raises(ArmRigError, match="IK_UNREACHABLE_TARGET"):
        solve_two_bone_ik((0.0, 0.0), (20.0, 0.0), 5.0, 4.0, 1)


def test_inverse_raster_is_deterministic_and_has_no_transparent_rgb_halo() -> None:
    rgba = np.zeros((40, 40, 4), dtype=np.uint8)
    rgba[10:30, 10:30, :3] = (24, 180, 240)
    rgba[10:30, 10:30, 3] = 255
    matrix = np.asarray([[0.43, -0.08, 18.25], [0.08, 0.43, 9.75]], dtype=np.float32)
    first = warp_rgba_inverse(rgba, matrix, (32, 24), source_scale=0.43)
    second = warp_rgba_inverse(rgba, matrix, (32, 24), source_scale=0.43)
    assert np.array_equal(first, second)
    assert int(np.count_nonzero(first[:, :, 3])) > 0
    assert not np.any(first[first[:, :, 3] == 0, :3])
    assert int(first[:, :, 3].max()) == 255


def test_c9_plan_has_real_independent_wrist_and_grip_at_all_probes() -> None:
    pack = _c9_pack()
    for source_frame, state_id in ((450, "seated_book_closed"), (510, "seated_book_closed"), (521, "seated_book_closed"), (522, "seated_book_open"), (523, "seated_book_open"), (569, "seated_book_open")):
        state = pack["states"][state_id]
        anchors = {name: tuple(point) for name, point in state["anchors"].items() if name != "book_corners"}
        fit = fit_layer_transform(
            source_frame,
            anchors,
            pin="seat_pelvis",
            asset_canvas_size=tuple(state["canvas_size"]),
            contact_basis="source_book_boundary_design",
        )
        targets = source_anchors_fullframe_px(source_frame, contact_basis="source_book_boundary_design")
        from app.services.pilot_preview.arm_rig import build_arm_rig_plan

        plan = build_arm_rig_plan(state, fit, targets, source_frame=source_frame)
        for side in ("left", "right"):
            wrist = np.asarray(plan["joints"][side]["wrist"])
            grip = np.asarray(plan["joints"][side]["grip"])
            assert np.linalg.norm(wrist - grip) > 1.0
            assert np.linalg.norm(grip - np.asarray(plan["targets"][side])) < 1e-6
            for role in ("upper_arm", "forearm", "cuff_bridge", "hand_grip", "front_fingers"):
                alpha = plan["roles"][side][role]["rgba"][:, :, 3]
                assert int(np.count_nonzero(alpha > 32)) > 0


def test_manifest_zero_error_tamper_is_rejected_from_real_transform() -> None:
    source_anchors = source_anchors_fullframe_px(450, contact_basis="source_book_boundary_design")
    asset_anchors = {
        "head": (509.1075904427166, 182.4522135832712),
        "seat_pelvis": (512.0, 850.0),
        "hand_grip_l": (452.0, 609.0),
        "hand_grip_r": (552.0, 611.0),
    }
    fit = fit_layer_transform(
        450,
        asset_anchors,
        pin="seat_pelvis",
        asset_canvas_size=(1024, 1536),
        contact_basis="source_book_boundary_design",
    )
    actual = measure_contact_residual(asset_anchors["hand_grip_l"], source_anchors["hand_grip_l"], fit)
    assert actual["error_px"] > 0.0
    tampered = {
        "method": "source_prop_boundary_contact_plus_production_transform",
        "source_frame": 450,
        "state": "seated_book_closed",
        "source_sha256": "s" * 64,
        "artwork_sha256": "a" * 64,
        "policy_revision": "source-prop-boundary-contact-v2",
        "policy_digest": "d" * 64,
        "contact_kind": "ART_DIRECTION_CONSTRAINT_ON_SOURCE_PROP",
        "source_role": "book",
        "book_owner": "source",
        "asset_point_local": list(asset_anchors["hand_grip_l"]),
        "source_target_px": list(source_anchors["hand_grip_l"]),
        "fit": fit,
        "declared_error_px": 0.0,
    }
    with pytest.raises(ValueError, match="declared contact error"):
        validate_contact_measurement(tampered)


def test_c9_final_validator_rejects_missing_real_role_contribution() -> None:
    plan = {
        "revision": "c9-arm-rig-native-raster-v1",
        "raster_contract": "inverse_area_premultiplied_one_pass_v1",
        "targets": {"left": [8.0, 10.0], "right": [23.0, 10.0]},
        "roles": {},
    }
    blank = np.zeros((24, 32, 3), dtype=np.uint8)
    book = np.zeros((24, 32), dtype=np.uint8)
    book[7:14, 5:27] = 255
    with pytest.raises(ArmRigError):
        validate_arm_rig_frame(
            before_arms=blank,
            final_frame=blank,
            plan=plan,
            book_mask=book,
            book_reference=blank,
        )


def test_c9_worker_compositor_invokes_arm_rig_for_every_scheduled_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production compositor path consumes the C9 rig, not a helper-only path."""
    import app.workflow.pilot_preview_jobs as jobs
    from app.services.pilot_preview.pose_composition import source_anchors_fullframe_px
    from app.services.pilot_preview.scene_reconstruction import book_insert_box_px

    pack = _c9_pack()
    source_sha = "22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a"
    schedule = jobs._build_composition_schedule(
        {"start_frame": 450, "end_frame": 570, "source_sha256": source_sha}, pack,
    )
    width, height = 640, 360
    import numpy as np

    source_frames: list[np.ndarray] = []
    reconstructions: list[dict] = []
    for local, row in enumerate(schedule):
        source_frame = 450 + local
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x, y, bw, bh = book_insert_box_px(source_frame)
        frame[max(0, y):min(height, y + bh), max(0, x):min(width, x + bw)] = (150, 80, 30)
        source_frames.append(frame)
        book = np.zeros((height, width), dtype=np.uint8)
        book[max(0, y):min(height, y + bh), max(0, x):min(width, x + bw)] = 255
        empty = np.zeros_like(book)
        reconstructions.append({
            "protected_masks": {
                "book": book, "woman": empty, "table": empty,
                "seated_back": empty, "chair_foreground": empty,
            },
            "layer_order": ["room", "chair_occupied", "chair_spare", "seated_character", "book", "woman", "table"],
            "reconstructed_foreground_mask": empty,
            "reconstructed_foreground_reference": frame.copy(),
            "reconstructed_foreground_provenance": {},
        })

    monkeypatch.setattr(jobs, "_read_frames", lambda *_args: source_frames)
    monkeypatch.setattr(jobs, "_write_video_only", lambda _frames, target, _ffmpeg: target.write_bytes(b"c9-test-video"))
    calls: list[int] = []
    original_builder = jobs.build_arm_rig_plan

    def tracked_builder(*args: object, **kwargs: object) -> dict:
        calls.append(int(kwargs["source_frame"]))
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(jobs, "build_arm_rig_plan", tracked_builder)

    class Context:
        def is_cancelled(self) -> bool:
            return False

        def progress(self, _value: float, _message: str) -> None:
            return None

    output = tmp_path / "c9-worker-compositor.mp4"
    composed, _meta = jobs._composite_v3(
        source_frames,
        source=tmp_path / "source.mp4",
        asset=Path(pack["states"]["seated_book_closed"]["path"]),
        rect=(0.32, 0.26, 0.16, 0.60),
        keyframes=[
            {"frame": 450, "anchor_xy_norm": [0.5, 0.5], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.5, 0.5], "scale": 1.0, "rotation_deg": 0.0},
        ],
        occluder={"layer_id": "foreground_right"},
        output=output,
        runtime_root=tmp_path,
        start_frame=450,
        ffmpeg="ffmpeg",
        ctx=Context(),
        pack=pack,
        schedule_rows=schedule,
        reconstructions=reconstructions,
        anchor_mode="source_derived",
    )
    assert output.read_bytes() == b"c9-test-video"
    assert len(composed) == 120
    assert calls == list(range(450, 570))
    assert schedule[71]["source_frame"] == 521
    assert schedule[72]["source_frame"] == 522
    assert all(row["final_pixel_gate"]["status"] == "passed" for row in schedule)

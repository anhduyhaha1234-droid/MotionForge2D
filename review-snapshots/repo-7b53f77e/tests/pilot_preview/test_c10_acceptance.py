"""C10 acceptance probes for visible-book and continuous-body/hand contact."""

from __future__ import annotations

import numpy as np
import pytest

import app.workflow.pilot_preview_jobs as jobs
from app.workflow.pilot_preview_jobs import PilotPreviewError


def _contact_fixture() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    before = np.zeros((40, 40, 3), dtype=np.uint8)
    left = np.zeros((40, 40, 4), dtype=np.uint8)
    right = np.zeros((40, 40, 4), dtype=np.uint8)
    body = np.zeros((40, 40, 4), dtype=np.uint8)
    book = np.zeros((40, 40), dtype=np.uint8)
    left[10, 10] = (30, 80, 180, 255)
    right[30, 30] = (30, 80, 180, 255)
    body[10, 9] = (20, 120, 30, 255)
    body[30, 29] = (20, 120, 30, 255)
    before[10, 9] = (20, 120, 30)
    before[30, 29] = (20, 120, 30)
    before[10, 11] = (90, 70, 40)
    before[30, 31] = (90, 70, 40)
    book[10, 11] = 255
    book[30, 31] = 255
    row = {
        "source_frame": 522,
        "declared_error_px": 0.0,
        "contact_measurements": {
            "hand_grip_l": {"transformed_output_px": [10, 10]},
            "hand_grip_r": {"transformed_output_px": [30, 30]},
        },
    }
    return before, left, right, body, book, row


def _final(before: np.ndarray, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    frame = jobs._reference_alpha_composite(before, left)
    return jobs._reference_alpha_composite(frame, right)


def _call_gate(before, final, left, right, body, book, row):
    body_base = before.copy()
    body_base[body[:, :, 3] > 32] = 0
    return jobs._validate_final_hand_pixels(
        before_hands=before,
        final_frame=final,
        hand_layers={"left": left, "right": right},
        body_layer=body,
        book_mask=book,
        book_reference=before,
        row=row,
        before_body=body_base,
    )


def test_c10_positive_gate_uses_visible_book_and_body_hand_component() -> None:
    before, left, right, body, book, row = _contact_fixture()
    result = _call_gate(before, _final(before, left, right), left, right, body, book, row)
    assert result["book_visibility_verified"] is True
    assert result["continuous_body_hand_component"] is True
    assert result["visible_book_pixels"] == 2


def test_c10_rejects_actual_hand_offset_when_manifest_declares_zero() -> None:
    before, left, right, body, book, row = _contact_fixture()
    shifted = np.zeros_like(left)
    shifted[10, 16] = left[10, 10]
    with pytest.raises(PilotPreviewError, match=r"(HAND_BOOK_BOUNDARY_DISCONNECTED|HAND_BODY_(WRIST_DISCONNECTED|HAND_COMPONENT_DISCONNECTED))"):
        _call_gate(before, _final(before, shifted, right), shifted, right, body, book, row)


def test_c10_rejects_book_mask_when_final_book_pixels_are_erased() -> None:
    before, left, right, body, book, row = _contact_fixture()
    final = _final(before, left, right)
    final[book > 0] = 0
    with pytest.raises(PilotPreviewError, match="HAND_BOOK_NOT_VISIBLE"):
        _call_gate(before, final, left, right, body, book, row)


def test_c11_detached_hand_island_near_book_does_not_prove_body_book_path() -> None:
    """A book-touching hand island cannot borrow a separate body's connection."""
    before, left, right, body, book, row = _contact_fixture()
    positive = _call_gate(before, _final(before, left, right), left, right, body, book, row)
    assert positive["status"] == "passed"

    # Keep the body-connected hand at x=10, but move the left book sample and
    # add a separate hand island adjacent to the book. The manifest target is
    # the new book-side island; only a component-level body→hand→book proof
    # distinguishes it from the disconnected construction.
    before[10, 11] = 0
    book[10, 11] = 0
    before[10, 18] = (90, 70, 40)
    book[10, 18] = 255
    left[10, 17] = (30, 80, 180, 255)
    row["contact_measurements"]["hand_grip_l"]["transformed_output_px"] = [17, 10]

    with pytest.raises(
        PilotPreviewError,
        match=r"^HAND_BODY_HAND_BOOK_COMPONENT_DISCONNECTED:522:left$",
    ):
        _call_gate(before, _final(before, left, right), left, right, body, book, row)


@pytest.mark.parametrize("replacement", [(180, 180, 180), (20, 120, 30)])
def test_c11_rejects_source_book_replaced_by_nonbook_content(replacement: tuple[int, int, int]) -> None:
    """Non-black occupancy cannot masquerade as the source-owned book."""
    before, left, right, body, book, row = _contact_fixture()
    final = _final(before, left, right)
    # Replace only the unoccluded source-book pixels after an otherwise-valid
    # production compositor result.  The gate must use ownership/content, not
    # ``RGB != 0`` occupancy.
    final[book > 0] = replacement
    with pytest.raises(PilotPreviewError, match="HAND_BOOK_CONTENT_MISMATCH"):
        _call_gate(before, final, left, right, body, book, row)


def test_c11_effective_input_ignores_unused_absolute_anchor_but_binds_real_inputs() -> None:
    """Source-derived absolute anchors are informational; real inputs bind."""
    manifest = {
        "start_frame": 450,
        "end_frame": 570,
        "source_sha256": "a" * 64,
        "mask_correction": {"bbox_xywh_norm": [0.32, 0.26, 0.16, 0.60], "source_frame": 450},
        "anchor_mode": "source_derived",
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": [0.40, 0.55], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.42, 0.54], "scale": 1.0, "rotation_deg": 0.0},
        ],
        "occluder": {"layer_id": "foreground_right", "z": -1},
        "pipeline_revision": "c11",
    }
    baseline = jobs.canonical_effective_input_record(manifest, frame_size=(640, 360))
    informational = {**manifest, "anchor_keyframes": [
        {"frame": 450, "anchor_xy_norm": [0.01, 0.99], "scale": 1.0, "rotation_deg": 0.0},
        {"frame": 569, "anchor_xy_norm": [0.99, 0.01], "scale": 1.0, "rotation_deg": 0.0},
    ]}
    assert jobs.canonical_effective_input_record(informational, frame_size=(640, 360))["effective_input_sha256"] == baseline["effective_input_sha256"]
    changed = {**manifest, "occluder": {"layer_id": "none"}}
    assert jobs.canonical_effective_input_record(changed, frame_size=(640, 360))["effective_input_sha256"] != baseline["effective_input_sha256"]


@pytest.mark.parametrize(
    "mutation",
    ("bbox", "occluder", "transform", "pack", "plate", "source"),
)
def test_c11_preencode_candidate_inputs_must_match(mutation: str) -> None:
    """Canonical pre-encode inputs must identify the actual candidate bytes."""
    import copy

    manifest = {
        "start_frame": 450,
        "end_frame": 570,
        "source_sha256": "a" * 64,
        "mask_correction": {"bbox_xywh_norm": [0.32, 0.26, 0.16, 0.60], "source_frame": 450},
        "anchor_mode": "source_derived",
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": [0.40, 0.55], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.42, 0.54], "scale": 1.0, "rotation_deg": 0.0},
        ],
        "occluder": {"layer_id": "foreground_right", "region_xywh_norm": [0.76, 0.34, 0.20, 0.66], "z": -1},
        "clean_plate_id": "plate-v1",
        "clean_plate_manifest_sha256": "b" * 64,
        "clean_plate_content_sha256": "c" * 64,
        "clean_plate_image_sha256": "d" * 64,
        "clean_plate_revision": "plate-rev-1",
        "pipeline_revision": "c11-pipeline",
        "render_geometry_contract": {"replacement_fit": "measured_affine"},
        "composition_revision": "composition-v1",
        "reconstruction_revision": "reconstruction-v1",
    }
    pack = {
        "pack_id": "pack-v1",
        "version": "v1",
        "manifest_sha256": "e" * 64,
        "content_sha256": "f" * 64,
        "validated_contract": "c7-exclusive-anatomy-v1",
        "states": {
            "seated_book_open": {
                "sha256": "1" * 64,
                "anchors": {"seat_pelvis": [512, 850], "hand_grip_l": [441, 620]},
                "canvas_size": [1024, 1536],
                "pose": "seated_holding_book_chest",
                "book": "open",
            },
        },
    }
    schedule = [{"frame": 522, "pack_state": "seated_book_open", "layer_order": ["character", "book", "foreground"]}]

    preencode = jobs.canonical_effective_input_record(
        manifest, frame_size=(640, 360), pack=pack, schedule_rows=schedule,
    )
    preencode_job_manifest = {**manifest, "effective_input_sha256": preencode["effective_input_sha256"]}
    preencode_job_identity = jobs.compute_input_identity_sha256(preencode_job_manifest)

    # The public absolute point is unused in source-derived mode; it must not
    # make a correct pre-encode review look different from its candidate.
    candidate_positive = copy.deepcopy(manifest)
    candidate_positive["anchor_keyframes"][0]["anchor_xy_norm"] = [0.01, 0.99]
    candidate_positive["anchor_keyframes"][1]["anchor_xy_norm"] = [0.99, 0.01]
    positive_record = jobs.canonical_effective_input_record(
        candidate_positive, frame_size=(640, 360), pack=pack, schedule_rows=schedule,
    )
    positive_identity = jobs.compute_input_identity_sha256({
        **candidate_positive, "effective_input_sha256": positive_record["effective_input_sha256"],
    })
    assert positive_record["effective_input_sha256"] == preencode["effective_input_sha256"]
    assert positive_identity == preencode_job_identity

    candidate = copy.deepcopy(manifest)
    candidate_pack = copy.deepcopy(pack)
    if mutation == "bbox":
        candidate["mask_correction"]["bbox_xywh_norm"] = [0.33, 0.26, 0.16, 0.60]
    elif mutation == "occluder":
        candidate["occluder"]["layer_id"] = "none"
    elif mutation == "transform":
        candidate["anchor_keyframes"][0]["scale"] = 1.125
    elif mutation == "pack":
        candidate_pack["content_sha256"] = "2" * 64
    elif mutation == "plate":
        candidate["clean_plate_image_sha256"] = "3" * 64
    elif mutation == "source":
        candidate["source_sha256"] = "4" * 64
    else:  # pragma: no cover - exhaustive parameter contract
        raise AssertionError(mutation)

    # Recompute from the candidate's effective inputs, as the worker does;
    # compare actual canonical hashes and job identities, not a report field.
    candidate_record = jobs.canonical_effective_input_record(
        candidate, frame_size=(640, 360), pack=candidate_pack, schedule_rows=schedule,
    )
    candidate_job_identity = jobs.compute_input_identity_sha256({
        **candidate, "effective_input_sha256": candidate_record["effective_input_sha256"],
    })
    assert candidate_record["effective_input_sha256"] != preencode["effective_input_sha256"], mutation
    assert candidate_job_identity != preencode_job_identity, mutation

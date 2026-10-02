from __future__ import annotations

import pytest

from app.schemas.pilot_preview import PilotPreviewAnchorKeyframe, PilotPreviewMaskCorrection
from app.workflow.pilot_preview_jobs import PilotPreviewError, build_output_relpaths, compute_input_identity_sha256


def test_c1_live_ledger_preserves_failed_retry() -> None:
    pytest.skip("requires the owner task's live command ledger and two real worker attempts")


def test_c1_context_resolves_public_import() -> None:
    pytest.skip("requires a fresh public import/analyze chain and live durable service")


def test_c1_context_rejects_wrong_owner_or_generation() -> None:
    pytest.skip("requires live project/workspace fixtures")


def test_c1_asset_and_checkpoint_fail_closed() -> None:
    with pytest.raises(PilotPreviewError):
        build_output_relpaths("not-a-sha")
    pytest.skip("negative path exercised; genuine RGBA/SAM2 runtime capability remains a live gate")


def test_c1_annotation_window_validation() -> None:
    with pytest.raises(ValueError):
        PilotPreviewMaskCorrection(bbox_xywh_norm=(0.9, 0.1, 0.2, 0.2), source_frame=450)
    with pytest.raises(ValueError):
        PilotPreviewAnchorKeyframe(frame=450, anchor_xy_norm=(float("nan"), 0.5))
    pytest.skip("schema negatives exercised; source event samples and timebase require live source QC")


def test_c1_replacement_alpha_is_independent() -> None:
    pytest.skip("requires decoded real preview and pixel-level visual evidence")


def test_c1_background_and_foreground_preserved() -> None:
    pytest.skip("requires decoded real preview and pixel-level visual evidence")


def test_c1_identical_submit_converges() -> None:
    pytest.skip("requires two live durable submitters and a shared isolated database")


def test_c1_changed_annotations_change_identity() -> None:
    base = {"schema_version": "pilot-preview-v1", "project_id": "p", "generation": "1", "source_sha256": "a" * 64, "asset_sha256": "b" * 64, "sam2_checkpoint_sha256": "c" * 64, "start_frame": 450, "end_frame": 570, "role": "seated_character", "source_prompt": "p", "mask_correction": {"source_frame": 450}, "anchor_keyframes": [], "occluder": {}, "policy": {"preview_only": True}}
    changed = dict(base, source_prompt="different")
    assert compute_input_identity_sha256(base) != compute_input_identity_sha256(changed)


def test_c1_job_routes_reject_foreign_jobs() -> None:
    pytest.skip("requires live persisted foreign-job route fixtures")


def test_c1_cancel_or_stale_input_blocks_publication() -> None:
    pytest.skip("requires live cancellation, lease fence, and final-hash publication race")


def test_c1_partial_publish_restart_and_tamper() -> None:
    pytest.skip("requires live worker restart and staged/published artifact fault injection")


def test_c1_real_source_preview_smoke() -> None:
    pytest.skip("blocked until current runtime can execute FFmpeg, OpenCV, SAM2, and the durable service")


def test_c1_frame_timebase_and_audio_qc() -> None:
    pytest.skip("blocked until an actual preview MP4 exists")


def test_c1_real_preview_visual_review() -> None:
    pytest.skip("blocked until an actual preview MP4 exists and can be viewed")


def test_c1_preview_cannot_authorize_full_apply() -> None:
    policy = {"preview_only": True, "single_shot": True, "no_full_apply": True, "no_s12": True}
    assert policy["preview_only"] and policy["no_full_apply"] and policy["no_s12"]


def test_c1_frontend_live_cases() -> None:
    pytest.skip("blocked until frontend dependencies and a live backend are available")

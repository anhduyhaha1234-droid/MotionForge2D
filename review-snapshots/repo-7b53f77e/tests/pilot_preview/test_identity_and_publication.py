from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.artifacts import ManagedRoot
from app.workflow.pilot_preview_jobs import (
    PILOT_PIPELINE_REVISION,
    PILOT_RENDER_GEOMETRY,
    PilotPreviewError,
    _publish,
    build_output_relpaths,
    compute_input_identity_sha256,
    output_relpaths_for_manifest,
)


def _manifest() -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": "pilot-preview-v1",
        "project_id": "demo",
        "durable_project_id": "durable-demo",
        "durable_video_item_id": "video-demo",
        "generation": "1",
        "source_sha256": "a" * 64,
        "asset_sha256": "b" * 64,
        "sam2_checkpoint_sha256": "c" * 64,
        "sam2_model_cfg": "configs/sam2.1/sam2.1_hiera_l.yaml",
        "sam2_device": "cpu",
        "start_frame": 450,
        "end_frame": 570,
        "role": "seated_character",
        "source_prompt": "replace the seated source character",
        "mask_correction": {"bbox_xywh_norm": [0.32, 0.26, 0.16, 0.6], "source_frame": 450},
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": [0.4, 0.55], "scale": 1.0, "rotation_deg": 0.0},
            {"frame": 569, "anchor_xy_norm": [0.4, 0.55], "scale": 1.0, "rotation_deg": 0.0},
        ],
        "occluder": {"layer_id": "foreground_right", "region_xywh_norm": [0.76, 0.34, 0.2, 0.66], "z": -1},
        "policy": {"preview_only": True, "single_shot": True, "no_full_apply": True, "no_s12": True},
    }
    manifest["input_identity_sha256"] = compute_input_identity_sha256(manifest)
    manifest["output_relpaths"] = build_output_relpaths(str(manifest["input_identity_sha256"]))
    return manifest


def test_C01_input_identity_and_per_job_paths_are_deterministic() -> None:
    manifest = _manifest()
    assert output_relpaths_for_manifest(manifest)["before"].startswith(
        f"pilot-preview/jobs/{manifest['input_identity_sha256']}/"
    )
    assert compute_input_identity_sha256(manifest) == manifest["input_identity_sha256"]


def test_c13_revision_and_geometry_are_bound_to_identity() -> None:
    base = _manifest()
    revised = dict(base)
    revised["pipeline_revision"] = PILOT_PIPELINE_REVISION
    revised["render_geometry_contract"] = dict(PILOT_RENDER_GEOMETRY)
    revised_identity = compute_input_identity_sha256(revised)
    assert revised_identity == compute_input_identity_sha256(revised)
    assert revised_identity != compute_input_identity_sha256(base)
    changed_geometry = dict(revised)
    changed_geometry["render_geometry_contract"] = {
        **PILOT_RENDER_GEOMETRY,
        "replacement_fit": "native_scale",
    }
    assert compute_input_identity_sha256(changed_geometry) != revised_identity


def test_C02_output_path_tampering_fails_closed() -> None:
    manifest = _manifest()
    manifest["output_relpaths"] = {"before": "pilot-preview/before.mp4"}
    with pytest.raises(PilotPreviewError, match="OUTPUT_PATH_CONTRACT_FAILED"):
        output_relpaths_for_manifest(manifest)


def test_c1_publish_does_not_overwrite_completed_job(tmp_path: Path) -> None:
    root = ManagedRoot(tmp_path)
    target = root.resolve("pilot-preview/jobs/demo/after.mp4")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing")
    staged = tmp_path / "after.mp4"
    staged.write_bytes(b"different")
    with pytest.raises(PilotPreviewError, match="PILOT_OUTPUT_CONFLICT"):
        _publish(root, staged, "pilot-preview/jobs/demo/after.mp4")


def test_c1_identical_publish_is_idempotent_for_exact_same_artifact(tmp_path: Path) -> None:
    root = ManagedRoot(tmp_path)
    relative = "pilot-preview/jobs/demo/after.mp4"
    target = root.resolve(relative)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"same")
    staged = tmp_path / "after.mp4"
    staged.write_bytes(b"same")
    published = _publish(root, staged, relative)
    assert published["relative_path"] == relative
    assert not staged.exists()

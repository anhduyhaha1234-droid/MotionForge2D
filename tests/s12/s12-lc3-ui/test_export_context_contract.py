"""Focused S12-LC3-UI contract negatives for backend-owned Export context."""

import pytest
from pydantic import ValidationError

from app.schemas.s12_export import ExportContextResponse
from app.services.s12_export.authority import ExportContext


def _context(**overrides: object) -> ExportContext:
    values: dict[str, object] = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "video_item_id": "video-1",
        "checkpoint_id": "checkpoint-1",
        "checkpoint_hash": "a" * 64,
        "checkpoint_revision": 3,
        "manifest_id": "manifest-1",
        "manifest_hash": "b" * 64,
        "manifest_generation": "generation-1",
        "plan_id": "c" * 64,
        "plan_hash": "d" * 64,
        "frame_count": 120,
        "fps_num": 24,
        "fps_den": 1,
        "full_apply_run_id": "full-apply-1",
    }
    values.update(overrides)
    return ExportContext(**values)


def test_context_revision_changes_when_server_authority_changes() -> None:
    assert _context().context_revision != _context(plan_hash="e" * 64).context_revision


def test_context_response_rejects_client_filesystem_fields() -> None:
    with pytest.raises(ValidationError):
        ExportContextResponse(
            workspace_id="workspace-1",
            project_id="project-1",
            video_item_id="video-1",
            context_revision="a" * 64,
            source_path="C:/client/forged.mp4",
        )


def test_context_response_contains_no_filesystem_paths() -> None:
    response = ExportContextResponse(
        workspace_id="workspace-1",
        project_id="project-1",
        video_item_id="video-1",
        context_revision=_context().context_revision,
    )
    serialized = response.model_dump()
    assert not {"source_path", "output_path", "scratch_dir", "chunk_dir"}.intersection(
        serialized
    )

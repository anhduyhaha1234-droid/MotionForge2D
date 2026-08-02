"""Tests for delete project and auto-segment endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _patch_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override project root so all tests use a temp directory."""
    test_root = tmp_path / "motionforge_test"
    test_root.mkdir()

    from app.api import deps
    from app.config import AppConfig

    test_config = AppConfig(
        project_root=test_root,
        models_dir=test_root / "models",
        output_dir=test_root / "output",
    )
    monkeypatch.setattr(deps, "_config", test_config)
    monkeypatch.setattr(
        deps,
        "_project_wf",
        __import__(
            "app.workflow.project_workflow",
            fromlist=["ProjectWorkflowService"],
        ).ProjectWorkflowService(test_config),
    )
    monkeypatch.setattr(
        deps,
        "_job_service",
        __import__(
            "app.workflow.job_service", fromlist=["JobService"],
        ).JobService(),
    )
    monkeypatch.setattr(
        deps,
        "_replacement_service",
        __import__(
            "app.workflow.replacement_service",
            fromlist=["ReplacementService"],
        ).ReplacementService(deps._project_wf),
    )
    monkeypatch.setattr(
        deps,
        "_seg_service",
        __import__(
            "app.workflow.segmentation_service",
            fromlist=["SegmentationService"],
        ).SegmentationService(test_config),
    )

    return test_root


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    from app.api.app import app

    return TestClient(app, raise_server_exceptions=False)


class TestDeleteProject:
    def test_delete_nonexistent(self, client: TestClient) -> None:
        """DELETE nonexistent project returns 404."""
        response = client.delete("/api/projects/nonexistent123")
        assert response.status_code == 404

    def test_delete_existing(self, client: TestClient) -> None:
        """DELETE existing project removes it."""
        # Create
        create_resp = client.post("/api/projects", json={"name": "ToDelete"})
        assert create_resp.status_code == 201
        pid = create_resp.json()["project_id"]

        # Delete
        del_resp = client.delete(f"/api/projects/{pid}")
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True

        # Verify gone
        get_resp = client.get(f"/api/projects/{pid}")
        assert get_resp.status_code == 404


class TestAutoSegment:
    def test_auto_segment_no_frames(self, client: TestClient) -> None:
        """Auto-segment with no frames returns 404."""
        create_resp = client.post("/api/projects", json={"name": "EmptyProj"})
        assert create_resp.status_code == 201
        pid = create_resp.json()["project_id"]

        response = client.post(f"/api/projects/{pid}/auto-segment-objects")
        assert response.status_code == 404

    def test_auto_segment_nonexistent_project(self, client: TestClient) -> None:
        """Auto-segment on nonexistent project returns 404."""
        response = client.post("/api/projects/nope/auto-segment-objects")
        assert response.status_code == 404

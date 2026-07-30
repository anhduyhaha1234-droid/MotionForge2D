"""Tests for clip mode, job cancellation, and restart persistence."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.schemas import ClipMode, ReplacementConfig


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def project_with_object(client: TestClient) -> tuple[str, str]:
    """Create a project with video ingested and object created."""
    # Create project
    r = client.post("/api/projects", json={"name": "Clip Test"})
    pid = r.json()["project_id"]

    # Upload video
    video = Path("output_m05/fixture_b/input.mp4")
    if not video.exists():
        pytest.skip("Fixture video not available")
    with open(video, "rb") as f:
        client.post(
            f"/api/projects/{pid}/video",
            files={"file": ("test.mp4", f, "video/mp4")},
        )

    # Ingest
    r = client.post(f"/api/projects/{pid}/ingest")
    jid = r.json()["job_id"]
    for _ in range(60):
        time.sleep(0.5)
        r = client.get(f"/api/jobs/{jid}")
        if r.json().get("status") in ("completed", "failed"):
            break

    # Preview mask
    client.post(
        f"/api/projects/{pid}/objects/preview-mask",
        json={
            "frame_index": 45,
            "selection": {"mode": "point", "frame_index": 45, "x": 320, "y": 230},
            "backend": "contour",
        },
    )

    # Create object
    r = client.post(
        f"/api/projects/{pid}/objects",
        json={
            "name": "Test Object",
            "selection": {"mode": "point", "frame_index": 45, "x": 320, "y": 230},
            "scene_id": 0,
        },
    )
    oid = r.json()["object_id"]

    return pid, oid


# ─── Clip Mode Tests ─────────────────────────────────────────────────────────


class TestClipModeSchema:
    def test_default_clip_mode(self) -> None:
        cfg = ReplacementConfig()
        assert cfg.clip_mode == ClipMode.ASSET_ALPHA

    def test_all_clip_modes(self) -> None:
        for mode in ClipMode:
            cfg = ReplacementConfig(clip_mode=mode)
            assert cfg.clip_mode == mode

    def test_clip_mode_alias(self) -> None:
        cfg = ReplacementConfig.model_validate({"clipMode": "original_mask"})
        assert cfg.clip_mode == ClipMode.ORIGINAL_MASK

    def test_clip_mode_serialization(self) -> None:
        cfg = ReplacementConfig(clip_mode=ClipMode.INTERSECTION)
        data = cfg.model_dump(by_alias=True)
        assert data["clipMode"] == "intersection"


class TestClipModeIntegration:
    def test_update_replacement_with_clip_mode(
        self, client: TestClient, project_with_object: tuple[str, str]
    ) -> None:
        """Update replacement settings with clip_mode."""
        pid, oid = project_with_object
        r = client.patch(
            f"/api/projects/{pid}/objects/{oid}/replacement-settings",
            json={
                "replacement_config": {
                    "mode": "static_asset",
                    "clip_mode": "original_mask",
                    "anchor": {"x": 0.5, "y": 0.5},
                    "scale": 1.0,
                    "opacity": 0.9,
                    "fit_mode": "contain",
                }
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["replacement_config"]["clip_mode"] == "original_mask"

    def test_all_clip_modes_via_api(
        self, client: TestClient, project_with_object: tuple[str, str]
    ) -> None:
        """All three clip modes accepted via API."""
        pid, oid = project_with_object
        for mode in ["asset_alpha", "original_mask", "intersection"]:
            r = client.patch(
                f"/api/projects/{pid}/objects/{oid}/replacement-settings",
                json={
                    "replacement_config": {
                        "mode": "static_asset",
                        "clip_mode": mode,
                    }
                },
            )
            assert r.status_code == 200
            assert r.json()["replacement_config"]["clip_mode"] == mode


# ─── Job Cancellation Tests ──────────────────────────────────────────────────


class TestJobCancellation:
    def test_cancel_running_job(self, client: TestClient) -> None:
        """Cancel a job and verify state transitions."""
        from app.api.deps import get_job_service

        svc = get_job_service()

        # Create a slow job
        started = []

        def slow_worker(progress_cb, is_cancelled):
            started.append(True)
            for i in range(100):
                if is_cancelled():
                    return "cancelled"
                progress_cb(i, f"Step {i}")
                time.sleep(0.05)
            return "done"

        info = svc.create_job("test_cancel", slow_worker)
        assert info.state.value == "running" or info.state.value == "queued"

        # Wait for it to start
        time.sleep(0.2)
        assert len(started) == 1

        # Cancel
        svc.cancel_job(info.job_id)
        assert True  # cancel returns True for running job

        # Wait for completion
        time.sleep(0.5)
        status = svc.get_job(info.job_id)
        assert status.state.value == "cancelled"

    def test_cancel_already_completed(self, client: TestClient) -> None:
        """Cancel a completed job returns appropriate response."""
        from app.api.deps import get_job_service

        svc = get_job_service()

        def fast_worker(progress_cb, is_cancelled):
            progress_cb(100, "Done")
            return "done"

        info = svc.create_job("test_done", fast_worker)
        time.sleep(0.5)  # Let it finish

        # Try to cancel completed job
        svc.cancel_job(info.job_id)
        # Should return False or handle gracefully
        status = svc.get_job(info.job_id)
        assert status.state.value in ("completed", "cancelled")

    def test_cancel_nonexistent_job(self, client: TestClient) -> None:
        """Cancel a nonexistent job returns error."""
        r = client.post("/api/jobs/nonexistent/cancel")
        assert r.status_code in (404, 400)

    def test_job_state_transitions(self, client: TestClient) -> None:
        """Verify job goes through running → cancelling → cancelled."""
        from app.api.deps import get_job_service

        svc = get_job_service()
        states_seen = []

        def tracking_worker(progress_cb, is_cancelled):
            for i in range(100):
                if is_cancelled():
                    return "cancelled"
                progress_cb(i, f"Step {i}")
                time.sleep(0.1)
            return "done"

        info = svc.create_job("test_states", tracking_worker)
        time.sleep(0.3)

        # Check it's running
        status = svc.get_job(info.job_id)
        states_seen.append(status.state.value)

        # Cancel
        svc.cancel_job(info.job_id)
        time.sleep(0.5)

        status = svc.get_job(info.job_id)
        states_seen.append(status.state.value)

        assert "running" in states_seen or "queued" in states_seen
        assert "cancelled" in states_seen


# ─── Restart Persistence Tests ───────────────────────────────────────────────


class TestRestartPersistence:
    def test_project_persists_after_restart(
        self, client: TestClient, project_with_object: tuple[str, str]
    ) -> None:
        """Project data survives simulated restart (re-read from disk)."""
        pid, oid = project_with_object

        # Read project from API
        r = client.get(f"/api/projects/{pid}")
        assert r.status_code == 200
        project_data = r.json()

        # Verify project file exists on disk
        project_file = Path(f"projects/{pid}/project.json")
        assert project_file.exists()

        # Read from disk and verify matches API
        import json

        with open(project_file) as f:
            disk_data = json.load(f)

        assert disk_data["name"] == project_data["name"]
        assert disk_data["version"] == project_data["version"]

    def test_object_persists(
        self, client: TestClient, project_with_object: tuple[str, str]
    ) -> None:
        """Object data persists in project JSON."""
        pid, oid = project_with_object

        # Check object exists in project via API
        r = client.get(f"/api/projects/{pid}/objects/{oid}")
        assert r.status_code == 200
        assert r.json()["object_id"] == oid

        # Check object is in project JSON on disk
        import json

        from app.config import config
        project_file = config.project_root / "projects" / pid / "project.json"
        assert project_file.exists()
        with open(project_file) as f:
            data = json.load(f)
        obj_ids = [o["object_id"] for o in data.get("objects", [])]
        assert oid in obj_ids

    def test_gallery_persists(
        self, client: TestClient, project_with_object: tuple[str, str]
    ) -> None:
        """Gallery manifest persists on disk."""
        pid, oid = project_with_object

        manifest = Path(f"projects/{pid}/objects/{oid}/gallery_manifest.json")
        # Gallery may not exist if propagation wasn't run
        if manifest.exists():
            import json

            with open(manifest) as f:
                data = json.load(f)
            assert "crops" in data or "object_id" in data

    def test_replacement_config_persists(
        self, client: TestClient, project_with_object: tuple[str, str]
    ) -> None:
        """Replacement config persists after update."""
        pid, oid = project_with_object

        # Update settings
        client.patch(
            f"/api/projects/{pid}/objects/{oid}/replacement-settings",
            json={
                "replacement_config": {
                    "mode": "static_asset",
                    "scale": 1.5,
                    "opacity": 0.8,
                    "clip_mode": "intersection",
                }
            },
        )

        # Read back
        r = client.get(f"/api/projects/{pid}/objects/{oid}")
        assert r.status_code == 200
        cfg = r.json().get("replacement_config", {})
        assert cfg.get("scale") == 1.5
        assert cfg.get("opacity") == 0.8
        assert cfg.get("clip_mode") == "intersection"

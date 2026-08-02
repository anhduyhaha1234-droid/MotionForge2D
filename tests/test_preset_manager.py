"""Tests for the character preset library & AI auto-pose matching."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as c:
        yield c


class TestPresetManager:
    def test_auto_pose_for_bbox_wide(self) -> None:
        """width > height * 1.1 → sitting (lying/wide pose)."""
        from app.services.preset_manager import CharacterPresetManager

        assert CharacterPresetManager.auto_pose_for_bbox(200, 100) == "sitting"
        assert CharacterPresetManager.auto_pose_for_bbox(250, 200) == "sitting"

    def test_auto_pose_for_bbox_tall(self) -> None:
        """height > width * 1.3 → standing (tall pose)."""
        from app.services.preset_manager import CharacterPresetManager

        assert CharacterPresetManager.auto_pose_for_bbox(100, 200) == "standing"
        assert CharacterPresetManager.auto_pose_for_bbox(100, 140) == "standing"

    def test_auto_pose_for_bbox_balanced(self) -> None:
        """Neither → talking (balanced pose)."""
        from app.services.preset_manager import CharacterPresetManager

        assert CharacterPresetManager.auto_pose_for_bbox(100, 100) == "talking"
        assert CharacterPresetManager.auto_pose_for_bbox(100, 110) == "talking"

    def test_auto_pose_zero_size(self) -> None:
        """Zero/invalid sizes must not crash and return talking."""
        from app.services.preset_manager import CharacterPresetManager

        assert CharacterPresetManager.auto_pose_for_bbox(0, 0) == "talking"
        assert CharacterPresetManager.auto_pose_for_bbox(-5, 100) == "talking"

    def test_builtin_sets_cover_four_poses(self) -> None:
        """Each built-in set has exactly sitting/standing/walking/talking."""
        from app.services.preset_manager import BUILTIN_CHARACTERS

        assert set(BUILTIN_CHARACTERS.keys()) == {"boy_cool", "tho_cute", "gau_nau"}
        for key, spec in BUILTIN_CHARACTERS.items():
            assert set(spec["poses"].keys()) == {
                "sitting",
                "standing",
                "walking",
                "talking",
            }, key

    def test_list_characters_endpoint(self, client: TestClient) -> None:
        """GET /api/presets/characters returns 3 sets × 4 poses."""
        r = client.get("/api/projects/presets/characters")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        chars = body["characters"]
        assert len(chars) == 3
        labels = {c["label"] for c in chars}
        assert labels == {"Bộ Boy Cool", "Bộ Thỏ Cute", "Bộ Gấu Nâu"}
        for c in chars:
            assert len(c["poses"]) == 4

    def test_character_preset_image_endpoint(self, client: TestClient) -> None:
        """GET preset image returns 200 image/png for every set+pose."""
        r = client.get("/api/projects/presets/characters")
        assert r.status_code == 200
        for c in r.json()["characters"]:
            for pose in c["poses"]:
                img = client.get(
                    f"/api/projects/presets/characters/{c['id']}/{pose['pose']}/image"
                )
                assert img.status_code == 200, (c["id"], pose["pose"])
                assert img.headers["content-type"].startswith("image/png")

    def test_apply_character_preset_endpoint(self, client: TestClient) -> None:
        """POST apply copies the pose PNG and sets replacement_config."""
        import cv2
        import numpy as np

        from app.api import deps

        create = client.post("/api/projects", json={"name": "PresetApply"})
        pid = create.json()["project_id"]

        # Frame + object
        proj_root = deps._config.project_root
        frame_dir = proj_root / "projects" / pid / "frames" / "scene_0"
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame = np.full((200, 200, 3), 255, dtype=np.uint8)
        frame[50:150, 50:150] = (0, 0, 0)
        cv2.imwrite(str(frame_dir / "frame_000000.png"), frame)

        obj = client.post(
            f"/api/projects/{pid}/objects",
            json={
                "name": "Nhân vật #1",
                "selection": {
                    "mode": "bounding_box",
                    "frame_index": 0,
                    "x": 60,
                    "y": 60,
                    "width": 80,
                    "height": 80,
                },
                "scene_id": 0,
            },
        )
        assert obj.status_code == 201
        oid = obj.json()["object_id"]

        r = client.post(f"/api/projects/{pid}/presets/characters/boy_cool/sitting/apply")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["object_id"] == oid
        assert body["pose"] == "sitting"
        assert body["asset_path"] == f"objects/{oid}/replacement.png"

        # The replacement PNG must exist on disk
        repl = proj_root / "projects" / pid / "objects" / oid / "replacement.png"
        assert repl.is_file()
        assert repl.stat().st_size > 0

        # Replacement image endpoint serves the preset
        img = client.get(f"/api/projects/{pid}/objects/{oid}/replacement-image")
        assert img.status_code == 200
        assert img.headers["content-type"].startswith("image/png")

    def test_auto_match_returns_pose(self, client: TestClient) -> None:
        """auto-match now reports the AI-chosen pose based on bbox aspect."""
        import cv2
        import numpy as np

        from app.api import deps

        create = client.post("/api/projects", json={"name": "PoseMatch"})
        pid = create.json()["project_id"]

        proj_root = deps._config.project_root
        frame_dir = proj_root / "projects" / pid / "frames" / "scene_0"
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame = np.full((200, 200, 3), 255, dtype=np.uint8)
        frame[50:150, 50:150] = (0, 0, 0)
        cv2.imwrite(str(frame_dir / "frame_000000.png"), frame)

        # Wide object (width 120 > height 60 * 1.1) → sitting
        obj1 = client.post(
            f"/api/projects/{pid}/objects",
            json={
                "name": "WideObj",
                "selection": {
                    "mode": "bounding_box",
                    "frame_index": 0,
                    "x": 40,
                    "y": 90,
                    "width": 120,
                    "height": 60,
                },
                "scene_id": 0,
            },
        )
        assert obj1.status_code == 201
        oid1 = obj1.json()["object_id"]

        # Tall object (width 40 < height 90 / 1.3) → standing in scene 1
        obj2 = client.post(
            f"/api/projects/{pid}/objects",
            json={
                "name": "TallObj",
                "selection": {
                    "mode": "bounding_box",
                    "frame_index": 0,
                    "x": 80,
                    "y": 40,
                    "width": 40,
                    "height": 90,
                },
                "scene_id": 1,
            },
        )
        assert obj2.status_code == 201

        r = client.post(f"/api/projects/{pid}/objects/{oid1}/auto-match")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["pose"] == "sitting"
        assert obj2.json()["object_id"] in body["matched"]

"""Tests for Character Preset Importer workflow (S06-T02)."""

from __future__ import annotations

from pathlib import Path

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.workflow.character_preset_importer import CharacterPresetImporter


def _session():
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def test_import_preset_copies_assets_and_attaches(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    # Create fake preset directory with pose images
    preset_dir = tmp_path / "preset_stickman"
    preset_dir.mkdir()
    (preset_dir / "front.png").write_bytes(b"fake front image bytes")
    (preset_dir / "side.png").write_bytes(b"fake side image bytes")
    (preset_dir / "back.png").write_bytes(b"fake back image bytes")

    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Preset Stickman",
            code="preset_stickman",
            preset_dir=preset_dir,
            description="Imported stickman preset",
        )
        session.commit()

        assert char.name == "Preset Stickman"
        assert char.code == "preset_stickman"
        assert char.status == "draft"
        assert ver.version == 1
        assert len(ver.assets) == 3

        attached_slots = {a.pose_slot for a in ver.assets}
        assert attached_slots == {"front", "side", "back"}

    # Verify original preset files were not mutated
    assert (preset_dir / "front.png").read_bytes() == b"fake front image bytes"
    assert (preset_dir / "side.png").read_bytes() == b"fake side image bytes"

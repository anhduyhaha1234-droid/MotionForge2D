"""Tests for preset manager service."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.workflow.preset_service import (
    CharacterMapping,
    PresetService,
    ProjectPreset,
)


@pytest.fixture
def svc() -> PresetService:
    return PresetService()


@pytest.fixture
def sample_preset() -> ProjectPreset:
    return ProjectPreset(
        name="Test Preset",
        description="A test preset",
        mappings=[
            CharacterMapping(
                original_name="Character A",
                replacement_asset="assets/a.png",
                replacement_config={"scale": 1.2, "opacity": 0.9},
            ),
            CharacterMapping(
                original_name="Character B",
                replacement_asset="assets/b.png",
            ),
        ],
        dubbing_config={"target_lang": "en", "voice": "en-US-AriaNeural"},
    )


class TestPresetSaveLoad:
    def test_save_and_load(
        self, svc: PresetService, sample_preset: ProjectPreset, tmp_path: Path,
    ) -> None:
        """Save and load roundtrip."""
        path = svc.save_preset(sample_preset, tmp_path / "test.json")
        assert path.exists()

        loaded = svc.load_preset(path)
        assert loaded.name == "Test Preset"
        assert len(loaded.mappings) == 2
        assert loaded.mappings[0].original_name == "Character A"

    def test_list_presets(
        self, svc: PresetService, sample_preset: ProjectPreset, tmp_path: Path,
    ) -> None:
        """List presets in directory."""
        svc.save_preset(sample_preset, tmp_path / "preset_a.json")
        svc.save_preset(sample_preset, tmp_path / "preset_b.json")

        presets = svc.list_presets(tmp_path)
        assert len(presets) == 2

    def test_list_presets_empty_dir(
        self, svc: PresetService, tmp_path: Path,
    ) -> None:
        """Listing presets from nonexistent dir returns empty."""
        assert svc.list_presets(tmp_path / "nonexistent") == []

    def test_load_nonexistent(self, svc: PresetService, tmp_path: Path) -> None:
        """Loading nonexistent preset raises error."""
        with pytest.raises(FileNotFoundError):
            svc.load_preset(tmp_path / "nonexistent.json")


class TestPresetApply:
    def test_apply_matches_objects(self, svc: PresetService) -> None:
        """Apply preset matches objects by name."""
        from app.schemas import (
            ReplacementConfig,
            SelectionInput,
            SelectionMode,
            TrackedObject,
        )

        preset = ProjectPreset(
            mappings=[
                CharacterMapping(
                    original_name="Hero",
                    replacement_config={"scale": 1.5},
                ),
            ],
        )

        class FakeProject:
            objects = [
                TrackedObject(
                    object_id="1",
                    name="Hero",
                    scene_id=0,
                    selection=SelectionInput(
                        mode=SelectionMode.POINT,
                        frame_index=0, x=0.0, y=0.0,
                    ),
                    replacement_config=ReplacementConfig(),
                ),
                TrackedObject(
                    object_id="2",
                    name="Villain",
                    scene_id=0,
                    selection=SelectionInput(
                        mode=SelectionMode.POINT,
                        frame_index=0, x=0.0, y=0.0,
                    ),
                    replacement_config=ReplacementConfig(),
                ),
            ]

        updated = svc.apply_preset_to_project(preset, FakeProject())
        assert updated == 1
        assert FakeProject.objects[0].replacement_config.scale == 1.5
        assert FakeProject.objects[1].replacement_config.scale == 1.0  # unchanged

    def test_apply_no_match(self, svc: PresetService) -> None:
        """Apply preset returns 0 when no objects match."""
        from app.schemas import (
            ReplacementConfig,
            SelectionInput,
            SelectionMode,
            TrackedObject,
        )

        preset = ProjectPreset(
            mappings=[
                CharacterMapping(
                    original_name="Nonexistent",
                    replacement_config={"scale": 2.0},
                ),
            ],
        )

        class FakeProject:
            objects = [
                TrackedObject(
                    object_id="1",
                    name="Hero",
                    scene_id=0,
                    selection=SelectionInput(
                        mode=SelectionMode.POINT,
                        frame_index=0, x=0.0, y=0.0,
                    ),
                    replacement_config=ReplacementConfig(),
                ),
            ]

        updated = svc.apply_preset_to_project(preset, FakeProject())
        assert updated == 0


class TestCharacterMapping:
    def test_defaults(self) -> None:
        """CharacterMapping has sensible defaults."""
        m = CharacterMapping()
        assert m.original_name == ""
        assert m.replacement_asset == ""
        assert m.voice_config == {}
        assert m.replacement_config == {}


class TestProjectPreset:
    def test_defaults(self) -> None:
        """ProjectPreset has sensible defaults."""
        p = ProjectPreset()
        assert p.name == "Untitled Preset"
        assert p.version == "1.0.0"
        assert p.mappings == []
        assert p.dubbing_config == {}

"""Tests for Character Preset Importer workflow (S06-T02, corrected).

Covers the S06-T02 contract plus the S06 correction findings:

- R1: original preset files are never mutated.
- R2: every copied asset has a registered SHA-256 checksum and byte size.
- R3: managed ``Artifact`` rows are registered in state ``ready``.
- R4: a draft ``Character`` and ``CharacterPackVersion`` (v1) are created.
- R5: available pose assets are attached to their ``pose_slot``.
- C1: pose files are discovered through the explicit ``PresetLayoutManifest``
  against the repository's real layout (``<set>_<pose>.png``) with the
  documented semantic mapping to canonical slots.
- C2: explicit mappings reject absolute paths, drive/UNC paths and ``..``
  traversal; every resolved file is enforced inside ``preset_dir``.
- C3: managed-file publication is transaction-safe — files written before a
  later DB failure/rollback are cleaned up (no orphan remains).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.artifacts import hash_file
from app.persistence.characters import (
    CharacterCodeConflictError,
    CharacterRepository,
)
from app.persistence.models import CORE_POSE_SLOTS, Artifact, Character
from app.workflow.character_preset_importer import CharacterPresetImporter
from app.workflow.preset_layout_manifest import (
    AmbiguousPresetLayoutError,
    PresetLayoutManifest,
)


def _session():
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _make_preset_dir(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """Create a preset directory with the given filename -> bytes content."""
    preset_dir = tmp_path / "preset"
    preset_dir.mkdir()
    for filename, data in files.items():
        (preset_dir / filename).write_bytes(data)
    return preset_dir


def _artifacts_for(workspace_id: str) -> list[Artifact]:
    """Query the durable DB for image artifacts in the workspace."""
    with _session() as session:
        return (
            session.query(Artifact)
            .filter(Artifact.workspace_id == workspace_id)
            .order_by(Artifact.relative_path.asc())
            .all()
        )


def _managed_files(managed_root: Path) -> list[Path]:
    """Every regular file under the managed root (excluding none)."""
    if not managed_root.exists():
        return []
    return [p for p in managed_root.rglob("*") if p.is_file()]


def _assets_for_version(version_id: str):
    """Return AssetRecord rows for a pack version (fresh query)."""
    with _session() as session:
        repo = CharacterRepository(session)
        record = repo.get_pack_version(version_id, DEFAULT_WORKSPACE_ID)
        return record.assets


def test_import_preset_copies_assets_and_attaches(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    # Create fake preset directory with pose images
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "front.png": b"fake front image bytes",
            "side.png": b"fake side image bytes",
            "back.png": b"fake back image bytes",
        },
    )

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


def test_artifacts_registered_ready_with_sha256_and_size(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "front.png": b"front-bytes",
            "side.jpg": b"side-bytes",
            "back.webp": b"back-bytes",
        },
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Artifact Check",
            code="artifact_check",
            preset_dir=preset_dir,
        )
        session.commit()

        assert len(ver.assets) == 3

    artifacts = _artifacts_for(DEFAULT_WORKSPACE_ID)
    assert len(artifacts) == 3

    # Every artifact: ready state, valid 64-char sha256, size matches bytes
    for art in artifacts:
        assert art.state == "ready"
        assert art.sha256 is not None and len(art.sha256) == 64
        assert art.size_bytes is not None and art.size_bytes > 0

    # Managed files exist on disk and match the originals byte-for-byte
    expected = {
        "front": ("front.png", b"front-bytes", "image/png"),
        "side": ("side.jpg", b"side-bytes", "image/jpeg"),
        "back": ("back.webp", b"back-bytes", "image/webp"),
    }
    by_slot = {a.pose_slot: a for a in _assets_for_version(ver.id)}
    for slot, (filename, content, mime) in expected.items():
        asset = by_slot[slot]
        art = next(a for a in artifacts if a.id == asset.artifact_id)
        assert art.mime_type == mime
        managed_file = managed_root / art.relative_path
        assert managed_file.is_file()
        assert managed_file.read_bytes() == content
        # sha256 registered equals the sha256 of the copied bytes
        assert art.sha256 == hash_file(managed_file)
        assert art.sha256 == hash_file(preset_dir / filename)
        assert art.size_bytes == len(content)


def test_import_with_explicit_pose_mapping(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "pose_0.png": b"front bytes",
            "pose_1.png": b"walking bytes",
            "unused.png": b"unused bytes",
        },
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Mapped Pose",
            code="mapped_pose",
            preset_dir=preset_dir,
            pose_mapping={"front": "pose_0.png", "walking": "pose_1.png"},
        )
        session.commit()

        assert len(ver.assets) == 2
        assert {a.pose_slot for a in ver.assets} == {"front", "walking"}


def test_import_all_core_slots(tmp_path: Path, _patch_project_root: Path) -> None:
    preset_dir = _make_preset_dir(
        tmp_path,
        {f"{slot}.png": f"{slot} bytes".encode() for slot in CORE_POSE_SLOTS},
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Full Pack",
            code="full_pack",
            preset_dir=preset_dir,
        )
        session.commit()

        assert len(ver.assets) == len(CORE_POSE_SLOTS)
        assert {a.pose_slot for a in ver.assets} == set(CORE_POSE_SLOTS)


def test_import_missing_preset_dir_raises(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(FileNotFoundError):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Missing",
                code="missing",
                preset_dir=tmp_path / "does_not_exist",
            )


def test_import_empty_preset_creates_draft_pack(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    preset_dir = _make_preset_dir(tmp_path, {})
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Empty Pack",
            code="empty_pack",
            preset_dir=preset_dir,
        )
        session.commit()

        assert char.status == "draft"
        assert ver.version == 1
        assert ver.status == "draft"
        assert ver.assets == []


def test_import_never_mutates_original_files(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    originals = {
        "front.png": b"original front content",
        "back.jpg": b"original back content",
    }
    preset_dir = _make_preset_dir(tmp_path, originals)

    # Snapshot original hashes before import
    before = {name: hash_file(preset_dir / name) for name in originals}

    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="No Mutate",
            code="no_mutate",
            preset_dir=preset_dir,
        )
        session.commit()

    # Original files still exist with identical bytes
    after = {name: hash_file(preset_dir / name) for name in originals}
    assert before == after
    assert (preset_dir / "front.png").read_bytes() == originals["front.png"]
    assert (preset_dir / "back.jpg").read_bytes() == originals["back.jpg"]


def test_import_duplicate_code_raises_conflict(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    preset_dir = _make_preset_dir(tmp_path, {"front.png": b"front bytes"})
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="First",
            code="dup_code",
            preset_dir=preset_dir,
        )
        session.commit()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(CharacterCodeConflictError):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Second",
                code="dup_code",
                preset_dir=preset_dir,
            )


# ── C1: real repository layout discovery through the manifest ───────────────


def _real_layout_preset(tmp_path: Path, set_name: str, poses: list[str]) -> Path:
    """Build a fixture mirroring the repo layout ``<set>_<pose>.png``."""
    return _make_preset_dir(
        tmp_path,
        {f"{set_name}_{pose}.png": f"{pose} bytes".encode() for pose in poses},
    )


def test_manifest_discovery_real_six_pose_set_maps_to_all_slots(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    # Mirrors the repository's full sets (e.g. tho_cute: back, sitting,
    # standing, talking, three_quarter, walking).
    preset_dir = _real_layout_preset(
        tmp_path,
        "tho_cute",
        ["back", "sitting", "standing", "talking", "three_quarter", "walking"],
    )
    manifest = PresetLayoutManifest()
    discovered = manifest.discover(preset_dir)

    assert set(discovered) == set(CORE_POSE_SLOTS)
    # Semantic mapping contract: talking -> front, standing -> side
    assert discovered["front"] == "tho_cute_talking.png"
    assert discovered["side"] == "tho_cute_standing.png"
    assert discovered["three_quarter"] == "tho_cute_three_quarter.png"


def test_import_real_layout_set_attaches_semantic_slots(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    preset_dir = _real_layout_preset(
        tmp_path,
        "boy_hacker",
        ["back", "sitting", "standing", "talking", "three_quarter", "walking"],
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Boy Hacker",
            code="boy_hacker",
            preset_dir=preset_dir,
        )
        session.commit()

        assert {a.pose_slot for a in ver.assets} == set(CORE_POSE_SLOTS)
        by_slot = {a.pose_slot: a for a in ver.assets}
        # Files copied to managed storage with real layout names discovered
        for _slot, asset in by_slot.items():
            assert asset.artifact_relative_path is not None
            assert (managed_root / asset.artifact_relative_path).is_file()


def test_import_four_pose_set_attaches_only_present_slots(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    # Mirrors boy_cool (4 poses) — no three_quarter/back -> 4 slots only.
    preset_dir = _real_layout_preset(
        tmp_path, "boy_cool", ["sitting", "standing", "talking", "walking"]
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Boy Cool",
            code="boy_cool",
            preset_dir=preset_dir,
        )
        session.commit()

        assert {a.pose_slot for a in ver.assets} == {"front", "side", "sitting", "walking"}


def test_manifest_discovery_against_real_repository_layout(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """Contract evidence: manifest set selection over the repo's real dir.

    Reads the repository's ``presets/characters`` directory (read-only).
    The shared multi-set directory is AMBIGUOUS without an explicit set name,
    and per-set discovery with ``set_name`` maps every full six-pose set to
    all six canonical slots — without mixing poses across sets.
    """
    from app.workflow.preset_layout_manifest import POSE_NAME_TO_SLOT

    real_dir = Path(__file__).resolve().parent.parent / "presets" / "characters"
    if not real_dir.is_dir():
        pytest.skip("real presets/characters directory not available")

    def _set_and_pose(stem: str) -> tuple[str, str] | None:
        for pose in POSE_NAME_TO_SLOT:
            if stem.endswith(f"_{pose}"):
                return stem[: -len(pose) - 1], pose
        return None

    by_set: dict[str, set[str]] = {}
    for path in real_dir.iterdir():
        if not path.is_file():
            continue
        parsed = _set_and_pose(path.stem)
        if parsed is None:
            continue
        set_name, pose = parsed
        by_set.setdefault(set_name, set()).add(pose)

    full_sets = {name for name, poses in by_set.items() if len(poses) >= 6}
    assert len(full_sets) >= 4, f"expected >=4 full six-pose sets, got {sorted(full_sets)}"

    # 1. The shared multi-set directory is ambiguous without set_name.
    manifest = PresetLayoutManifest()
    with pytest.raises(AmbiguousPresetLayoutError) as excinfo:
        manifest.discover(real_dir)
    assert any(name in str(excinfo.value) for name in sorted(full_sets))

    # 2. Per-set discovery on the real layout never mixes sets and covers
    #    every canonical slot for each full set.
    for set_name in sorted(full_sets):
        discovered = manifest.discover(real_dir, set_name=set_name)
        assert set(discovered) == set(CORE_POSE_SLOTS), (
            f"set {set_name} did not discover all six canonical slots: {discovered}"
        )
        for filename in discovered.values():
            assert filename.startswith(f"{set_name}_"), (
                f"set {set_name} discovery leaked foreign file {filename!r}"
            )


def test_manifest_discovery_multi_set_dir_is_ambiguous(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """A directory mixing poses from two sets raises instead of mixing slots."""
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "tho_cute_back.png": b"a",
            "tho_cute_talking.png": b"b",
            "boy_hacker_side.png": b"c",
            "boy_hacker_walking.png": b"d",
        },
    )
    manifest = PresetLayoutManifest()
    with pytest.raises(AmbiguousPresetLayoutError) as excinfo:
        manifest.discover(preset_dir)
    assert "tho_cute" in str(excinfo.value) and "boy_hacker" in str(excinfo.value)

    # Explicit set selection resolves each set independently.
    tho_cute = manifest.discover(preset_dir, set_name="tho_cute")
    assert tho_cute == {"back": "tho_cute_back.png", "front": "tho_cute_talking.png"}
    boy_hacker = manifest.discover(preset_dir, set_name="boy_hacker")
    assert boy_hacker == {"side": "boy_hacker_side.png", "walking": "boy_hacker_walking.png"}

    # Unknown set name fails clearly.
    with pytest.raises(AmbiguousPresetLayoutError, match="not found"):
        manifest.discover(preset_dir, set_name="nope")


def test_import_ambiguous_multi_set_dir_raises_without_side_effects(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """Importer fails clearly on an ambiguous multi-set dir, no rows/files."""
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "tho_cute_back.png": b"a",
            "tho_cute_talking.png": b"b",
            "boy_hacker_side.png": b"c",
        },
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(AmbiguousPresetLayoutError):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Ambiguous",
                code="ambiguous",
                preset_dir=preset_dir,
            )
        session.rollback()

    assert _managed_files(managed_root) == []
    with _session() as session:
        chars = session.query(Character).filter(Character.code == "ambiguous").all()
        assert chars == []


def test_import_preset_with_set_name_from_shared_dir(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """set_name selects one set from a shared multi-set preset directory."""
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            **{f"tho_cute_{pose}.png": f"tho {pose}".encode()
               for pose in ["back", "sitting", "standing", "talking", "three_quarter", "walking"]},
            "boy_cool_sitting.png": b"boy sitting",
            "boy_cool_standing.png": b"boy standing",
            "boy_cool_talking.png": b"boy talking",
            "boy_cool_walking.png": b"boy walking",
        },
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        char, ver = importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Tho Cute",
            code="tho_cute",
            preset_dir=preset_dir,
            set_name="tho_cute",
        )
        session.commit()

        assert {a.pose_slot for a in ver.assets} == set(CORE_POSE_SLOTS)
        # Exactly the selected set's six poses were imported (no boy_cool leaks).
        assert len(ver.assets) == len(CORE_POSE_SLOTS)
        by_slot = {a.pose_slot: a for a in ver.assets}
        for _slot, asset in by_slot.items():
            assert asset.artifact_relative_path is not None
            assert (managed_root / asset.artifact_relative_path).is_file()


# ── C2: explicit mapping containment ─────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_name",
    [
        "../evil.png",
        "sub/../evil.png",
        "../../outside.png",
    ],
)
def test_explicit_mapping_rejects_parent_traversal(
    tmp_path: Path, _patch_project_root: Path, bad_name: str
) -> None:
    preset_dir = _make_preset_dir(tmp_path, {"front.png": b"front bytes"})
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(ValueError, match="parent traversal"):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Bad Traversal",
                code="bad_traversal",
                preset_dir=preset_dir,
                pose_mapping={"front": bad_name},
            )


@pytest.mark.parametrize(
    "bad_name",
    [
        "/etc/passwd",
        "C:/Windows/evil.png",
        "C:\\Windows\\evil.png",
        "//server/share/evil.png",
    ],
)
def test_explicit_mapping_rejects_absolute_and_unc_paths(
    tmp_path: Path, _patch_project_root: Path, bad_name: str
) -> None:
    preset_dir = _make_preset_dir(tmp_path, {"front.png": b"front bytes"})
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(ValueError, match="absolute|UNC"):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Bad Absolute",
                code="bad_absolute",
                preset_dir=preset_dir,
                pose_mapping={"front": bad_name},
            )


def test_explicit_mapping_rejects_escape_via_symlink(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.png").write_bytes(b"evil bytes")
    preset_dir = _make_preset_dir(tmp_path, {"front.png": b"front bytes"})
    link = preset_dir / "linked.png"
    try:
        link.symlink_to(outside / "evil.png")
    except OSError:
        pytest.skip("symlinks not supported on this platform")

    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(ValueError, match="escapes"):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Symlink Escape",
                code="symlink_escape",
                preset_dir=preset_dir,
                pose_mapping={"front": "linked.png"},
            )


def test_explicit_mapping_rejects_missing_file(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    preset_dir = _make_preset_dir(tmp_path, {"front.png": b"front bytes"})
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(ValueError, match="not found"):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Missing File",
                code="missing_file",
                preset_dir=preset_dir,
                pose_mapping={"front": "nope.png"},
            )


# ── C3: transaction-safe managed-file publication ────────────────────────────


def test_mid_import_db_failure_leaves_no_orphan_files(
    tmp_path: Path, _patch_project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure on a LATER attach leaves zero files in managed storage."""
    preset_dir = _make_preset_dir(
        tmp_path,
        {f"{slot}.png": f"{slot} bytes".encode() for slot in CORE_POSE_SLOTS},
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    calls = {"n": 0}
    real_attach = CharacterRepository.attach_asset

    def flaky_attach(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("injected attach failure")
        return real_attach(self, *args, **kwargs)

    monkeypatch.setattr(CharacterRepository, "attach_asset", flaky_attach)

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        with pytest.raises(RuntimeError, match="injected attach failure"):
            importer.import_preset(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="Fail Mid",
                code="fail_mid",
                preset_dir=preset_dir,
            )
        session.rollback()

    assert _managed_files(managed_root) == [], (
        f"orphan managed files after failed import: {_managed_files(managed_root)}"
    )
    # No character rows survive the rollback either.
    with _session() as session:
        chars = session.query(Character).filter(
            Character.code == "fail_mid"
        ).all()
        assert chars == []


def test_rollback_after_successful_import_removes_written_files(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """Caller rollback (later DB failure) removes files written pre-commit."""
    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "front.png": b"front bytes",
            "side.png": b"side bytes",
            "back.png": b"back bytes",
        },
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Rollback Pack",
            code="rollback_pack",
            preset_dir=preset_dir,
        )
        # Import succeeded (files written, rows flushed) — but the caller
        # rolls the transaction back before commit.
        session.rollback()

    assert _managed_files(managed_root) == [], (
        f"orphan managed files after rollback: {_managed_files(managed_root)}"
    )
    with _session() as session:
        chars = session.query(Character).filter(
            Character.code == "rollback_pack"
        ).all()
        assert chars == []


def test_commit_keeps_written_files(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """After a successful commit, managed files legitimately remain."""
    preset_dir = _make_preset_dir(tmp_path, {"front.png": b"front bytes"})
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Commit Pack",
            code="commit_pack",
            preset_dir=preset_dir,
        )
        session.commit()

    assert len(_managed_files(managed_root)) == 1
    with _session() as session:
        chars = session.query(Character).filter(
            Character.code == "commit_pack"
        ).all()
        assert len(chars) == 1


def test_later_rollback_does_not_delete_committed_files(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """Regression (S06-C2 blocker 4): a later unrelated rollback on the SAME
    session must never delete files from a previously committed import.

    after_commit disarms per-operation tracking; the later transaction's
    rollback therefore cleans nothing.
    """
    from app.persistence.models import Workspace

    preset_dir = _make_preset_dir(
        tmp_path,
        {
            "front.png": b"front bytes",
            "side.png": b"side bytes",
        },
    )
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()

    with _session() as session:
        importer = CharacterPresetImporter(session, storage_root=managed_root)
        importer.import_preset(
            workspace_id=DEFAULT_WORKSPACE_ID,
            name="Committed Pack",
            code="committed_pack",
            preset_dir=preset_dir,
        )
        session.commit()

        committed_files = sorted(
            p.name for p in _managed_files(managed_root)
        )
        assert len(committed_files) == 2

        # Begin a LATER transaction on the same session and roll it back.
        ws = Workspace(name="Unrelated Rollback Workspace")
        session.add(ws)
        session.flush()
        session.rollback()

    # The committed import's managed files must still exist.
    remaining = sorted(p.name for p in _managed_files(managed_root))
    assert remaining == committed_files, (
        f"later rollback deleted committed files: {remaining} != {committed_files}"
    )
    # The unrelated row was rolled back; the committed character remains.
    with _session() as session:
        chars = session.query(Character).filter(
            Character.code == "committed_pack"
        ).all()
        assert len(chars) == 1

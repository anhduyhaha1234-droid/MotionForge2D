"""Tests for Character Pack Validation Engine (S06-T03, corrected).

Covers the full asset validation required by S06-T03 in addition to
six-slot completeness:

- artifact linkage + ``ready`` state
- on-disk file existence
- size integrity
- SHA-256 checksum integrity
- image decode
- alpha channel (transparency policy)
- minimum resolution policy
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import CharacterRepository
from app.persistence.models import (
    CORE_POSE_SLOTS,
    Artifact,
    CharacterAsset,
    CharacterPackVersion,
)
from app.workflow.character_validator import (
    MIN_POSE_HEIGHT,
    MIN_POSE_WIDTH,
    is_pack_publishable,
    validate_character_pack,
)


def _session():
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _png_bytes(
    width: int = 256,
    height: int = 256,
    alpha: bool = True,
    opaque: bool = False,
) -> bytes:
    """A real PNG image, optionally with real transparency.

    Default (alpha=True, opaque=False): RGBA with every pixel at alpha 200 —
    real transparency (min alpha < 255) without being fully see-through.
    alpha=False: RGB (no alpha channel at all).
    opaque=True: RGBA where every alpha pixel is 255 — alpha-capable but
    fully opaque, which must be rejected as "no real transparency".
    """
    if alpha:
        a = 255 if opaque else 200
        img = Image.new("RGBA", (width, height), (120, 60, 200, a))
    else:
        img = Image.new("RGB", (width, height), (120, 60, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _register_artifact(
    session,
    rel_path: str,
    *,
    state: str = "ready",
    content: bytes | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
) -> str:
    art = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="image",
        relative_path=rel_path,
        state=state,
        size_bytes=size_bytes if size_bytes is not None else len(content or b""),
        mime_type="image/png",
        sha256=sha256 if sha256 is not None else (
            hashlib.sha256(content).hexdigest() if content is not None else None
        ),
    )
    session.add(art)
    session.flush()
    return art.id


def _build_pack(session, managed_root: Path, files: dict[str, bytes]) -> tuple[str, str]:
    """Create a character + version and attach one real artifact per slot.

    ``files`` maps canonical slot name -> on-disk file bytes.  Returns
    (character_id, version_id).  Caller must commit.
    """
    repo = CharacterRepository(session)
    char = repo.create_character(DEFAULT_WORKSPACE_ID, "Valid Char", "valid_char")
    ver = repo.create_pack_version(char.id, DEFAULT_WORKSPACE_ID)
    for slot, data in files.items():
        rel = f"characters/{char.id}/{slot}.png"
        target = managed_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        art_id = _register_artifact(session, rel, content=data)
        repo.attach_asset(
            version_id=ver.id,
            workspace_id=DEFAULT_WORKSPACE_ID,
            pose_slot=slot,
            artifact_id=art_id,
        )
    session.flush()
    return char.id, ver.id


def _artifact_for_slot(session, version_id: str, slot: str) -> Artifact:
    """Return the Artifact row attached to *slot* of *version_id*."""
    ver = CharacterRepository(session).get_pack_version(
        version_id, DEFAULT_WORKSPACE_ID
    )
    asset = next(a for a in ver.assets if a.pose_slot == slot)
    art = session.get(Artifact, asset.artifact_id)
    assert art is not None
    return art


def test_validation_fails_on_missing_slots(_patch_project_root: Path) -> None:
    with _session() as session:
        repo = CharacterRepository(session)
        char = repo.create_character(DEFAULT_WORKSPACE_ID, "Test Char", "test_char")
        ver = repo.create_pack_version(char.id, DEFAULT_WORKSPACE_ID)

        errors = validate_character_pack(ver)
        assert len(errors) > 0
        assert "Missing required core pose slots" in errors[0]
        assert not is_pack_publishable(ver)


def _all_slot_files() -> dict[str, bytes]:
    return {slot: _png_bytes() for slot in CORE_POSE_SLOTS}


def test_valid_pack_passes_all_checks(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, _all_slot_files())
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert errors == [], errors
        assert is_pack_publishable(ver, managed_root)


def test_artifact_file_missing_on_disk(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    with _session() as session:
        char_id, ver_id = _build_pack(session, managed_root, _all_slot_files())
        # Delete one managed file on disk; its Artifact row remains.
        (managed_root / "characters" / char_id / "front.png").unlink()
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("file missing on disk" in e for e in errors), errors
        assert not is_pack_publishable(ver, managed_root)


def test_artifact_not_in_ready_state(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    with _session() as session:
        # Build a full pack, then flip one artifact to 'staging'.
        _, ver_id = _build_pack(session, managed_root, files)
        front = (
            session.query(Artifact)
            .join(CharacterAsset, CharacterAsset.artifact_id == Artifact.id)
            .join(CharacterPackVersion, CharacterPackVersion.id == CharacterAsset.pack_version_id)
            .filter(CharacterPackVersion.id == ver_id)
            .all()
        )
        front[0].state = "staging"
        session.flush()
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("not in ready state" in e for e in errors), errors
        assert not is_pack_publishable(ver, managed_root)


def test_checksum_mismatch_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    with _session() as session:
        char_id, ver_id = _build_pack(session, managed_root, files)
        # Tamper with one managed file AFTER registration (different pixels
        # -> different PNG bytes -> different SHA-256).
        tampered = BytesIO()
        Image.new("RGBA", (256, 256), (10, 20, 30, 255)).save(tampered, format="PNG")
        target = managed_root / "characters" / char_id / "back.png"
        target.write_bytes(tampered.getvalue())
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("SHA-256 mismatch" in e for e in errors), errors


def test_size_mismatch_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        # Register a wrong size for the sitting artifact, then re-read the
        # pack so the validation sees the mutated row.
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        sitting_asset = next(
            a for a in ver.assets if a.pose_slot == "sitting"
        )
        art = session.get(Artifact, sitting_asset.artifact_id)
        art.size_bytes = art.size_bytes + 1
        session.flush()
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("size mismatch" in e for e in errors), errors


def test_non_image_file_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    files["side"] = b"this is definitely not an image payload"
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("not a decodable image" in e for e in errors), errors


def _palette_png(transparent_index_used: bool) -> bytes:
    """P-mode PNG that DECLARES palette index 1 as transparent.

    - transparent_index_used=False: every pixel uses opaque index 0, so the
      declared transparent index is never rendered -> fully opaque.
    - transparent_index_used=True: an 8x8 corner uses index 1 -> real
      rendered transparency.
    """
    img = Image.new("P", (256, 256))
    palette: list[int] = []
    for i in range(256):
        palette += [i, i, i]
    img.putpalette(palette)
    data = [0] * (256 * 256)
    if transparent_index_used:
        for y in range(8):
            for x in range(8):
                data[y * 256 + x] = 1
    img.putdata(data)
    buf = BytesIO()
    img.save(buf, format="PNG", transparency=1)
    return buf.getvalue()


def test_missing_alpha_channel_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    files["walking"] = _png_bytes(alpha=False)  # RGB, no alpha at all
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("no real transparency" in e for e in errors), errors


def test_fully_opaque_rgba_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    """RGBA with every alpha pixel == 255 is alpha-capable but NOT transparent."""
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    files["front"] = _png_bytes(opaque=True)  # RGBA, all alpha 255
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("no real transparency" in e for e in errors), errors
        assert not is_pack_publishable(ver, managed_root)


def test_palette_declares_transparency_but_pixels_opaque_rejected(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """A P image declaring a transparent index that NO pixel uses is opaque.

    The tRNS entry alone must not satisfy the transparency policy; only
    rendered pixels with alpha < 255 count.
    """
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    files["front"] = _palette_png(transparent_index_used=False)
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("no real transparency" in e for e in errors), errors
        assert not is_pack_publishable(ver, managed_root)


def test_palette_actually_using_transparent_index_accepted(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """A P image whose pixels actually use the transparent index is valid."""
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    files["front"] = _palette_png(transparent_index_used=True)
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert errors == [], errors
        assert is_pack_publishable(ver, managed_root)


def test_single_transparent_pixel_accepted(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """An image with just one alpha<255 pixel has real transparency."""
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    one_pixel = Image.new("RGBA", (256, 256), (120, 60, 200, 255))
    one_pixel.putpixel((0, 0), (0, 0, 0, 0))  # exactly one transparent pixel
    buf = BytesIO()
    one_pixel.save(buf, format="PNG")
    files["front"] = buf.getvalue()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert errors == [], errors
        assert is_pack_publishable(ver, managed_root)


def test_missing_sha256_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        art = _artifact_for_slot(session, ver_id, "front")
        art.sha256 = None
        session.flush()
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("missing its SHA-256 checksum" in e for e in errors), errors
        assert not is_pack_publishable(ver, managed_root)


def test_empty_sha256_cannot_be_stored(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """The schema CHECK (ck_artifact_sha256_len) rejects empty sha256 at the
    DB layer — empty checksum evidence is unrepresentable."""
    from sqlalchemy.exc import IntegrityError

    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        art = _artifact_for_slot(session, ver_id, "front")
        art.sha256 = ""
        with pytest.raises(IntegrityError):
            session.flush()


def test_empty_sha256_rejected_by_validator(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    """Even if a record carried an empty checksum, the validator rejects it."""
    from datetime import UTC, datetime

    from app.persistence.characters import AssetRecord, PackVersionRecord

    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    data = _png_bytes()
    rel = "characters/empty_sha.png"
    target = managed_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    with _session() as session:
        from app.persistence.characters import _ensure_workspace

        _ensure_workspace(session, DEFAULT_WORKSPACE_ID)
        art_id = _register_artifact(session, rel, content=data)
        session.commit()

    now = datetime.now(UTC)
    asset = AssetRecord(
        id="a-empty-sha",
        pack_version_id="v-empty-sha",
        workspace_id=DEFAULT_WORKSPACE_ID,
        pose_slot="front",
        artifact_id=art_id,
        created_at=now,
        updated_at=now,
        artifact_state="ready",
        artifact_sha256="",
        artifact_size_bytes=len(data),
        artifact_relative_path=rel,
        artifact_mime_type="image/png",
    )
    ver = PackVersionRecord(
        id="v-empty-sha",
        character_id="c-empty-sha",
        workspace_id=DEFAULT_WORKSPACE_ID,
        version=1,
        status="draft",
        validation_json=None,
        published_at=None,
        revision=1,
        created_at=now,
        updated_at=now,
        archived_at=None,
        assets=[asset],
    )
    errors = validate_character_pack(ver, managed_root)
    assert any("missing its SHA-256 checksum" in e for e in errors), errors
    assert not is_pack_publishable(ver, managed_root)


def test_missing_size_rejected(tmp_path: Path, _patch_project_root: Path) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        art = _artifact_for_slot(session, ver_id, "front")
        art.size_bytes = None
        session.flush()
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("missing its size" in e for e in errors), errors
        assert not is_pack_publishable(ver, managed_root)


def test_below_minimum_resolution_rejected(
    tmp_path: Path, _patch_project_root: Path
) -> None:
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    files = _all_slot_files()
    files["three_quarter"] = _png_bytes(width=64, height=64)
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, files)
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)
        errors = validate_character_pack(ver, managed_root)
        assert any("below" in e and "resolution" in e for e in errors), errors


def test_resolution_policy_constants_are_positive() -> None:
    assert MIN_POSE_WIDTH >= 1 and MIN_POSE_HEIGHT >= 1


def test_default_storage_root_used_when_omitted(
    tmp_path: Path, _patch_project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without storage_root the validator uses Path('artifacts') relative to cwd.

    Change cwd to a directory without the managed files, so the default
    ``Path("artifacts")`` root cannot find them and validation fails on
    missing files.
    """
    managed_root = tmp_path / "managed_artifacts"
    managed_root.mkdir()
    with _session() as session:
        _, ver_id = _build_pack(session, managed_root, _all_slot_files())
        ver = CharacterRepository(session).get_pack_version(ver_id, DEFAULT_WORKSPACE_ID)

        nowhere = tmp_path / "nowhere"
        nowhere.mkdir()
        monkeypatch.chdir(nowhere)
        errors = validate_character_pack(ver)
        assert any("file missing on disk" in e for e in errors), errors

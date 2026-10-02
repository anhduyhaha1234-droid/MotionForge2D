"""Tests for Character Pack Validation Engine (S06-T03).

Covers the S06-T03 contract:

- R1: all 6 core pose slots must be attached before a pack may publish.
- R2: pose asset files must exist on disk, be non-empty, and match their
  registered size/SHA-256 (file integrity).
- R3: pose images must be RGBA (alpha channel), at least 512x512, and within
  a sane aspect ratio.
- R4: ``publish_pack_version`` refuses to publish when validation fails and
  the API surfaces the errors as 422.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID, ManagedRoot
from app.persistence.characters import (
    CharacterRepository,
    PublishValidationFailedError,
)
from app.persistence.models import CORE_POSE_SLOTS, Artifact
from app.workflow.character_validator import (
    is_pack_publishable,
    validate_character_pack,
)


def _session():
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _managed_root() -> Path:
    """The isolated managed artifact root bound to the test job service."""
    service = deps._job_service
    assert service is not None
    return service._managed_root


def _make_png_bytes(width: int = 512, height: int = 512, channels: int = 4) -> bytes:
    """Encode a solid transparent image of the requested size/channels."""
    image = np.zeros((height, width, channels), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _register_artifact(
    managed_root: Path,
    rel_path: str,
    data: bytes | None,
    state: str = "ready",
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> str:
    """Write *data* to the managed root (when not None) and register Artifact."""
    real_sha: str | None = None
    real_size: int | None = None
    if data is not None:
        real_sha, real_size = ManagedRoot(managed_root).atomic_write_bytes(
            rel_path, data
        )
    with _session() as session:
        art = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=rel_path,
            state=state,
            size_bytes=size_bytes if size_bytes is not None else real_size,
            mime_type="image/png",
            sha256=sha256 if sha256 is not None else real_sha,
        )
        session.add(art)
        session.commit()
        return art.id


def _create_pack_with_assets(
    managed_root: Path,
    slot_data: dict[str, bytes | None],
    state: str = "ready",
):
    """Create a draft character + version and attach one asset per slot.

    ``slot_data`` maps pose slot -> PNG bytes written to the managed root, or
    ``None`` to register an Artifact row whose file does NOT exist on disk.
    """
    with _session() as session:
        repo = CharacterRepository(session, storage_root=managed_root)
        uid = uuid.uuid4().hex[:8]
        char = repo.create_character(
            DEFAULT_WORKSPACE_ID, f"Char {uid}", f"char_{uid}"
        )
        ver = repo.create_pack_version(char.id, DEFAULT_WORKSPACE_ID)
        for slot, data in slot_data.items():
            rel_path = f"characters/{char.id}/{slot}.png"
            art_id = _register_artifact(managed_root, rel_path, data, state=state)
            repo.attach_asset(ver.id, DEFAULT_WORKSPACE_ID, slot, art_id)
        session.commit()
        return repo.get_pack_version(ver.id, DEFAULT_WORKSPACE_ID)


def _full_valid_slots() -> dict[str, bytes]:
    return {slot: _make_png_bytes(512, 512, 4) for slot in CORE_POSE_SLOTS}


# ── Record-level validation ──────────────────────────────────────────────


def test_validation_fails_on_missing_slots(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(_managed_root(), {})
    errors = validate_character_pack(ver)
    assert len(errors) > 0
    assert "Missing required core pose slots" in errors[0]
    assert not is_pack_publishable(ver)


def test_validation_rejects_unlinked_asset(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(_managed_root(), {"front": _make_png_bytes()})
    errors = validate_character_pack(ver, session=_session(), storage_root=_managed_root())
    assert any("not linked to an artifact" in e for e in errors) is False
    # A record whose asset has an empty artifact_id is rejected at record level.
    from app.persistence.characters import AssetRecord

    bare = AssetRecord(
        id="a",
        pack_version_id="v",
        workspace_id=DEFAULT_WORKSPACE_ID,
        pose_slot="front",
        artifact_id="",
        created_at=ver.created_at,
        updated_at=ver.updated_at,
    )
    record_errors = validate_character_pack(ver, session=None)
    assert record_errors == []
    # Validate a standalone version record carrying the bare asset.
    from app.persistence.characters import PackVersionRecord

    stub = PackVersionRecord(
        id=ver.id,
        character_id=ver.character_id,
        workspace_id=ver.workspace_id,
        version=ver.version,
        status=ver.status,
        validation_json=None,
        published_at=None,
        revision=ver.revision,
        created_at=ver.created_at,
        updated_at=ver.updated_at,
        archived_at=None,
        assets=[bare],
    )
    assert any("not linked to an artifact" in e for e in validate_character_pack(stub))


# ── File integrity validation ────────────────────────────────────────────


def test_validation_rejects_missing_file_on_disk(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: None if slot == "front" else _make_png_bytes() for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("file is missing on disk" in e for e in errors)
    assert not is_pack_publishable(ver, session=_session(), storage_root=_managed_root())


def test_validation_rejects_empty_file(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: b"" if slot == "back" else _make_png_bytes() for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("empty (0 bytes)" in e for e in errors)


def test_validation_rejects_checksum_mismatch(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(_managed_root(), _full_valid_slots())
    with _session() as session:
        art = session.get(Artifact, ver.assets[0].artifact_id)
        assert art is not None
        art.sha256 = "b" * 64
        session.commit()
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("checksum mismatch" in e for e in errors)


def test_validation_rejects_size_mismatch(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(_managed_root(), _full_valid_slots())
    with _session() as session:
        art = session.get(Artifact, ver.assets[0].artifact_id)
        assert art is not None
        art.size_bytes = (art.size_bytes or 0) + 999
        session.commit()
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("size mismatch" in e for e in errors)


def test_validation_rejects_artifact_not_ready(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(), _full_valid_slots(), state="staging"
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("not in ready state" in e for e in errors)


def test_validation_rejects_corrupt_image(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: b"not a real image" if slot == "side" else _make_png_bytes() for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("not a readable image" in e for e in errors)


# ── Image quality validation ─────────────────────────────────────────────


def test_validation_rejects_non_rgba_image(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: _make_png_bytes(512, 512, channels=3) for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert len(errors) == len(CORE_POSE_SLOTS)
    assert all("lacks alpha channel" in e for e in errors)


def test_validation_rejects_below_min_resolution(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: _make_png_bytes(256, 256, 4) for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("below the minimum 512x512" in e for e in errors)
    assert len(errors) == len(CORE_POSE_SLOTS)


def test_validation_rejects_extreme_aspect_ratio(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: _make_png_bytes(512, 4096, 4) for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert any("aspect ratio" in e for e in errors)


def test_validation_passes_for_complete_valid_pack(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(_managed_root(), _full_valid_slots())
    with _session() as session:
        errors = validate_character_pack(ver, session=session, storage_root=_managed_root())
    assert errors == []
    assert is_pack_publishable(ver, session=_session(), storage_root=_managed_root())


# ── Publish gate integration ─────────────────────────────────────────────


def test_publish_blocks_invalid_pack_and_stays_draft(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(
        _managed_root(),
        {slot: _make_png_bytes(256, 256, 4) for slot in CORE_POSE_SLOTS},
    )
    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        with pytest.raises(PublishValidationFailedError) as excinfo:
            repo.publish_pack_version(ver.id, DEFAULT_WORKSPACE_ID, ver.revision)
        err = excinfo.value
        assert err.errors
        assert any("below the minimum" in e for e in err.errors)
        assert err.missing_slots == []
    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        version = repo.get_pack_version(ver.id, DEFAULT_WORKSPACE_ID)
        assert version.status == "draft"


def test_publish_succeeds_for_valid_pack(_patch_project_root: Path) -> None:
    ver = _create_pack_with_assets(_managed_root(), _full_valid_slots())
    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        published = repo.publish_pack_version(
            ver.id, DEFAULT_WORKSPACE_ID, ver.revision
        )
        assert published.status == "published"
        assert published.published_at is not None
        assert published.validation_json is not None
        assert "core_slots" in published.validation_json


# ── API publish gate ─────────────────────────────────────────────────────


def test_publish_api_rejects_invalid_image_with_errors(
    client: TestClient, _patch_project_root: Path
) -> None:
    managed_root = _managed_root()
    char_resp = client.post(
        "/api/v2/characters",
        json={"name": "API Invalid", "code": "api_invalid"},
    )
    assert char_resp.status_code == 201
    char_id = char_resp.json()["id"]

    ver_resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert ver_resp.status_code == 201
    ver = ver_resp.json()
    ver_id = ver["id"]

    for index, slot in enumerate(CORE_POSE_SLOTS):
        channels = 3 if index == 0 else 4  # first slot: RGB without alpha
        art_id = _register_artifact(
            managed_root, f"characters/api_{slot}.png", _make_png_bytes(512, 512, channels)
        )
        att = client.post(
            f"/api/v2/characters/versions/{ver_id}/assets",
            json={"pose_slot": slot, "artifact_id": art_id},
        )
        assert att.status_code == 200, att.text

    pub = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub.status_code == 422
    detail = pub.json()["detail"]
    assert "errors" in detail
    assert any("lacks alpha channel" in e for e in detail["errors"])


def test_publish_api_success_for_valid_pack(
    client: TestClient, _patch_project_root: Path
) -> None:
    managed_root = _managed_root()
    char_resp = client.post(
        "/api/v2/characters",
        json={"name": "API Valid", "code": "api_valid"},
    )
    assert char_resp.status_code == 201
    char_id = char_resp.json()["id"]

    ver_resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert ver_resp.status_code == 201
    ver = ver_resp.json()
    ver_id = ver["id"]

    for slot in CORE_POSE_SLOTS:
        art_id = _register_artifact(
            managed_root,
            f"characters/api_ok_{slot}.png",
            _make_png_bytes(512, 512, 4),
        )
        att = client.post(
            f"/api/v2/characters/versions/{ver_id}/assets",
            json={"pose_slot": slot, "artifact_id": art_id},
        )
        assert att.status_code == 200, att.text

    pub = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"

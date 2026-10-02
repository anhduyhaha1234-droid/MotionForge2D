"""Publish-path rejection tests (S06-T03 correction).

Proves the full validator is wired into the publish gate:

- API: ``POST /api/v2/characters/versions/{id}/publish`` rejects invalid
  packs with 422 and a detail containing ``missing_slots`` AND ``errors``.
- Repository: ``CharacterRepository.publish_pack_version`` rejects the same
  invalid packs directly — there is NO bypass through the publish service.
- A fully valid pack publishes through both paths.

Asset failure modes covered: missing on-disk file, artifact not ready,
SHA-256 mismatch, size mismatch, non-image payload, missing alpha channel,
below-minimum resolution, missing slots.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import (
    CharacterRepository,
    PublishValidationFailedError,
)
from app.persistence.models import CORE_POSE_SLOTS, Artifact


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
    """Real PNG; default RGBA alpha 200 (real transparency)."""
    if alpha:
        a = 255 if opaque else 200
        img = Image.new("RGBA", (width, height), (120, 60, 200, a))
    else:
        img = Image.new("RGB", (width, height), (120, 60, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _managed_root() -> Path:
    svc = deps._job_service
    assert svc is not None
    return Path(svc._managed_root)


def _write_managed(rel: str, data: bytes) -> Path:
    target = _managed_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _create_character(client: TestClient, code: str) -> str:
    resp = client.post(
        "/api/v2/characters",
        json={"name": f"Pub {code}", "code": code},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _palette_png(transparent_index_used: bool) -> bytes:
    """P-mode PNG declaring palette index 1 transparent; pixels use index 0
    unless *transparent_index_used* (then an 8x8 corner uses index 1)."""
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


def _attach_artifact(
    client: TestClient,
    ver_id: str,
    slot: str,
    *,
    state: str = "ready",
    data: bytes | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
) -> str:
    data = data if data is not None else _png_bytes()
    rel = f"characters/publish_test/{ver_id}/{slot}.png"
    if state == "ready":
        _write_managed(rel, data)
    with _session() as session:
        art = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=rel,
            state=state,
            size_bytes=size_bytes if size_bytes is not None else len(data),
            mime_type="image/png",
            sha256=sha256 if sha256 is not None else hashlib.sha256(data).hexdigest(),
        )
        session.add(art)
        session.commit()
        artifact_id = art.id
    resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/assets",
        json={"pose_slot": slot, "artifact_id": artifact_id},
    )
    assert resp.status_code == 200, resp.text
    return artifact_id


def _full_valid_pack(client: TestClient, char_id: str) -> dict:
    """Attach six real, ready, alpha-carrying pose files; return version."""
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        _attach_artifact(client, ver["id"], slot)
    return ver


# ── API rejection path ───────────────────────────────────────────────────────


def test_api_publish_rejects_missing_slots(client: TestClient) -> None:
    char_id = _create_character(client, "api_missing_slots")
    ver = _create_version(client, char_id)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "missing_slots" in detail
    assert set(detail["missing_slots"]) == set(CORE_POSE_SLOTS)
    assert any("Missing required core pose slots" in e for e in detail["errors"])
    # The version must NOT have been published.
    fresh = client.get(f"/api/v2/characters/{char_id}/versions").json()
    assert fresh[0]["status"] == "draft"


def test_api_publish_rejects_missing_file_on_disk(client: TestClient) -> None:
    char_id = _create_character(client, "api_missing_file")
    ver = _full_valid_pack(client, char_id)

    # Delete the front asset file; its Artifact row stays.
    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/front.png")
        ).first()
        assert art is not None
        rel = art.relative_path
    (_managed_root() / rel).unlink()

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("file missing on disk" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_non_ready_artifact(client: TestClient) -> None:
    char_id = _create_character(client, "api_not_ready")
    ver = _full_valid_pack(client, char_id)

    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/front.png")
        ).first()
        art.state = "staging"
        session.commit()

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("not in ready state" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_checksum_tamper(client: TestClient) -> None:
    char_id = _create_character(client, "api_checksum")
    ver = _full_valid_pack(client, char_id)

    # Overwrite the walking file with different pixels after registration.
    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/walking.png")
        ).first()
        rel = art.relative_path
    tampered = BytesIO()
    Image.new("RGBA", (256, 256), (1, 2, 3, 255)).save(tampered, format="PNG")
    (_managed_root() / rel).write_bytes(tampered.getvalue())

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("SHA-256 mismatch" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_size_mismatch(client: TestClient) -> None:
    char_id = _create_character(client, "api_size")
    ver = _full_valid_pack(client, char_id)

    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/back.png")
        ).first()
        art.size_bytes = art.size_bytes + 1
        session.commit()

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("size mismatch" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_non_image_payload(client: TestClient) -> None:
    char_id = _create_character(client, "api_non_image")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "side" else b"not an image at all"
        _attach_artifact(client, ver["id"], slot, data=data)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("not a decodable image" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_missing_alpha(client: TestClient) -> None:
    char_id = _create_character(client, "api_alpha")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "three_quarter" else _png_bytes(alpha=False)
        _attach_artifact(client, ver["id"], slot, data=data)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("no real transparency" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_low_resolution(client: TestClient) -> None:
    char_id = _create_character(client, "api_resolution")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "sitting" else _png_bytes(width=32, height=32)
        _attach_artifact(client, ver["id"], slot, data=data)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("below" in e and "resolution" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_fully_opaque_rgba(client: TestClient) -> None:
    """RGBA with every alpha pixel == 255 must not publish (no real transparency)."""
    char_id = _create_character(client, "api_opaque")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "front" else _png_bytes(opaque=True)
        _attach_artifact(client, ver["id"], slot, data=data)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("no real transparency" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_missing_sha256(client: TestClient) -> None:
    char_id = _create_character(client, "api_no_sha")
    ver = _full_valid_pack(client, char_id)

    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/front.png")
        ).first()
        art.sha256 = None
        session.commit()

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any(
        "missing its SHA-256 checksum" in e for e in resp.json()["detail"]["errors"]
    )


def test_api_publish_rejects_missing_size(client: TestClient) -> None:
    char_id = _create_character(client, "api_no_size")
    ver = _full_valid_pack(client, char_id)

    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/front.png")
        ).first()
        art.size_bytes = None
        session.commit()

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("missing its size" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_rejects_palette_unused_transparent_index(
    client: TestClient,
) -> None:
    """A palette PNG declaring a transparent index NO pixel uses cannot publish."""
    char_id = _create_character(client, "api_pal_unused")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "front" else _palette_png(False)
        _attach_artifact(client, ver["id"], slot, data=data)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 422, resp.text
    assert any("no real transparency" in e for e in resp.json()["detail"]["errors"])


def test_api_publish_accepts_palette_using_transparent_index(
    client: TestClient,
) -> None:
    """A palette PNG whose pixels actually use the transparent index publishes."""
    char_id = _create_character(client, "api_pal_used")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "front" else _palette_png(True)
        _attach_artifact(client, ver["id"], slot, data=data)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "published"


def test_api_publish_valid_pack_succeeds(client: TestClient) -> None:
    char_id = _create_character(client, "api_valid")
    ver = _full_valid_pack(client, char_id)

    resp = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert resp.status_code == 200, resp.text
    published = resp.json()
    assert published["status"] == "published"
    assert published["published_at"] is not None


# ── Repository rejection path (no bypass through direct publish) ─────────────


def test_repository_publish_rejects_invalid_pack_no_bypass(
    client: TestClient, _patch_project_root: Path
) -> None:
    """Direct publish_pack_version calls cannot bypass the validator."""
    char_id = _create_character(client, "repo_reject")
    ver = _full_valid_pack(client, char_id)

    # Break an asset AFTER the API setup (delete the side file on disk).
    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/side.png")
        ).first()
        rel = art.relative_path
    (_managed_root() / rel).unlink()

    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        with pytest.raises(PublishValidationFailedError) as excinfo:
            repo.publish_pack_version(ver["id"], DEFAULT_WORKSPACE_ID, ver["revision"])
        assert any("file missing on disk" in e for e in excinfo.value.errors)
        assert any("'side'" in e for e in excinfo.value.errors), excinfo.value.errors


def test_repository_publish_rejects_missing_slots_no_bypass(
    client: TestClient, _patch_project_root: Path
) -> None:
    char_id = _create_character(client, "repo_missing")
    ver = _create_version(client, char_id)

    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        with pytest.raises(PublishValidationFailedError) as excinfo:
            repo.publish_pack_version(ver["id"], DEFAULT_WORKSPACE_ID, ver["revision"])
        assert set(excinfo.value.missing_slots) == set(CORE_POSE_SLOTS)


def test_repository_publish_valid_pack_succeeds(
    client: TestClient, _patch_project_root: Path
) -> None:
    char_id = _create_character(client, "repo_valid")
    ver = _full_valid_pack(client, char_id)

    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        published = repo.publish_pack_version(
            ver["id"], DEFAULT_WORKSPACE_ID, ver["revision"]
        )
        assert published.status == "published"
        session.commit()

    fresh = client.get(f"/api/v2/characters/{char_id}/versions").json()
    assert fresh[0]["status"] == "published"


def test_repository_cannot_store_empty_sha256_evidence(
    client: TestClient, _patch_project_root: Path
) -> None:
    """Empty sha256 is unrepresentable at the repository/DB layer: the schema
    CHECK (ck_artifact_sha256_len) rejects it, so publish evidence can never
    be an empty checksum.  (Missing/None checksums are rejected by the
    publish gate — see test_api_publish_rejects_missing_sha256.)"""
    from sqlalchemy.exc import IntegrityError

    char_id = _create_character(client, "repo_empty_sha")
    _full_valid_pack(client, char_id)

    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/walking.png")
        ).first()
        art.sha256 = ""
        with pytest.raises(IntegrityError):
            session.commit()


def test_repository_publish_rejects_missing_size_no_bypass(
    client: TestClient, _patch_project_root: Path
) -> None:
    """Missing size on an artifact rejects direct repository publish too."""
    char_id = _create_character(client, "repo_no_size")
    ver = _full_valid_pack(client, char_id)

    with _session() as session:
        art = session.query(Artifact).filter(
            Artifact.relative_path.like("%/walking.png")
        ).first()
        art.size_bytes = None
        session.commit()

    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        with pytest.raises(PublishValidationFailedError) as excinfo:
            repo.publish_pack_version(ver["id"], DEFAULT_WORKSPACE_ID, ver["revision"])
        assert any("missing its size" in e for e in excinfo.value.errors), (
            excinfo.value.errors
        )

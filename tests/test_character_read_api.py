"""Focused tests for the Character artifact read API (S06-R02).

Covers the read-only content endpoint and draft validation endpoint:

- real PNG success bytes + MIME via the content endpoint
- AssetData DTO metadata (state, mime, sha256, size, typed content URL)
- missing file / staging artifact / wrong MIME / corrupt image /
  checksum + size mismatch fail closed
- cross-character / cross-version / cross-workspace access fail closed
- traversal (``..``) and symlink escapes fail closed without path leaks
- draft validation parity with the publish gate (same authoritative validator)
- no absolute path disclosure in any response
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
        json={"name": f"Read {code}", "code": code},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _attach_artifact(
    client: TestClient,
    ver_id: str,
    slot: str,
    *,
    state: str = "ready",
    data: bytes | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    mime_type: str = "image/png",
    rel_path: str | None = None,
) -> dict:
    data = data if data is not None else _png_bytes()
    rel = rel_path if rel_path is not None else f"characters/read_api/{ver_id}/{slot}.png"
    if state == "ready" and rel_path is None:
        _write_managed(rel, data)
    with _session() as session:
        art = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=rel,
            state=state,
            size_bytes=size_bytes if size_bytes is not None else len(data),
            mime_type=mime_type,
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
    return resp.json()


def _full_valid_pack(client: TestClient, char_id: str) -> dict:
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        _attach_artifact(client, ver["id"], slot)
    return ver


def _content_url(asset: dict) -> str:
    url = asset["content_url"]
    assert url is not None
    return url


# ── Success path ─────────────────────────────────────────────────────────────


def test_content_endpoint_serves_real_png_bytes_and_mime(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "read_png")
    ver = _create_version(client, char_id)
    data = _png_bytes()
    asset = _attach_artifact(client, ver["id"], "front", data=data)

    resp = client.get(_content_url(asset))
    assert resp.status_code == 200, resp.text
    assert resp.content == data
    assert resp.headers["content-type"].startswith("image/png")


def test_asset_dto_metadata_and_content_url(client: TestClient) -> None:
    char_id = _create_character(client, "read_dto")
    ver = _create_version(client, char_id)
    data = _png_bytes()
    asset = _attach_artifact(client, ver["id"], "front", data=data)

    assert asset["artifact_state"] == "ready"
    assert asset["mime_type"] == "image/png"
    assert asset["sha256"] == hashlib.sha256(data).hexdigest()
    assert asset["size_bytes"] == len(data)
    assert asset["content_url"] == (
        f"/api/v2/characters/{char_id}/versions/{ver['id']}"
        f"/assets/{asset['id']}/content"
    )
    # The DTO must NEVER carry a relative_path / absolute filesystem path.
    assert "relative_path" not in asset
    body = str(asset)
    assert str(_managed_root()) not in body
    assert "artifacts" not in body


def test_list_versions_assets_include_read_metadata(client: TestClient) -> None:
    char_id = _create_character(client, "read_list")
    ver = _full_valid_pack(client, char_id)

    resp = client.get(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 200
    version = next(v for v in resp.json() if v["id"] == ver["id"])
    assert len(version["assets"]) == len(CORE_POSE_SLOTS)
    for asset in version["assets"]:
        assert asset["artifact_state"] == "ready"
        assert asset["mime_type"] == "image/png"
        assert asset["sha256"]
        assert asset["size_bytes"] > 0
        assert asset["content_url"].startswith(
            f"/api/v2/characters/{char_id}/versions/{ver['id']}/assets/"
        )
        assert asset["content_url"].endswith("/content")
        assert "relative_path" not in asset


def test_attach_response_asset_has_content_url(client: TestClient) -> None:
    char_id = _create_character(client, "read_attach_url")
    ver = _create_version(client, char_id)
    asset = _attach_artifact(client, ver["id"], "front")
    assert asset["content_url"].startswith(
        f"/api/v2/characters/{char_id}/versions/{ver['id']}/assets/"
    )


# ── Fail-closed: file/state/type/integrity ───────────────────────────────────


def test_content_missing_file_on_disk_404(client: TestClient) -> None:
    char_id = _create_character(client, "read_missing_file")
    ver = _create_version(client, char_id)
    data = _png_bytes()
    rel = f"characters/read_api/{ver['id']}/front.png"
    _write_managed(rel, data)
    asset = _attach_artifact(client, ver["id"], "front", data=data, rel_path=rel)
    (_managed_root() / rel).unlink()

    resp = client.get(_content_url(asset))
    assert resp.status_code == 404, resp.text
    assert str(_managed_root()) not in resp.text


def test_content_staging_artifact_409(client: TestClient) -> None:
    char_id = _create_character(client, "read_staging")
    ver = _create_version(client, char_id)
    # Attach a ready artifact, then demote its Artifact row to staging (the
    # attach endpoint itself rejects non-ready artifacts, so flip post-attach).
    data = _png_bytes()
    rel = f"characters/read_api/{ver['id']}/front.png"
    _write_managed(rel, data)
    asset = _attach_artifact(client, ver["id"], "front", data=data, rel_path=rel)
    with _session() as session:
        art = session.get(Artifact, asset["artifact_id"])
        assert art is not None
        art.state = "staging"
        session.commit()

    resp = client.get(_content_url(asset))
    assert resp.status_code == 409, resp.text
    assert str(_managed_root()) not in resp.text


def test_content_wrong_mime_422(client: TestClient) -> None:
    char_id = _create_character(client, "read_wrong_mime")
    ver = _create_version(client, char_id)
    asset = _attach_artifact(
        client, ver["id"], "front", mime_type="application/octet-stream"
    )

    resp = client.get(_content_url(asset))
    assert resp.status_code == 422, resp.text
    assert "no approved image MIME type" in resp.text


def test_content_corrupt_image_422(client: TestClient) -> None:
    char_id = _create_character(client, "read_corrupt")
    ver = _create_version(client, char_id)
    data = b"this is definitely not an image payload"
    asset = _attach_artifact(client, ver["id"], "front", data=data)

    resp = client.get(_content_url(asset))
    assert resp.status_code == 422, resp.text
    assert "not a decodable image" in resp.text
    assert str(_managed_root()) not in resp.text


def test_content_checksum_mismatch_422(client: TestClient) -> None:
    char_id = _create_character(client, "read_checksum")
    ver = _create_version(client, char_id)
    data = _png_bytes()
    rel = f"characters/read_api/{ver['id']}/front.png"
    # Register a WRONG checksum while the on-disk file and registered size
    # stay consistent -> only the SHA-256 gate can reject.
    wrong_sha = hashlib.sha256(b"something else entirely").hexdigest()
    _write_managed(rel, data)
    asset = _attach_artifact(
        client,
        ver["id"],
        "front",
        data=data,
        rel_path=rel,
        sha256=wrong_sha,
    )

    resp = client.get(_content_url(asset))
    assert resp.status_code == 422, resp.text
    assert "SHA-256 checksum mismatch" in resp.text


def test_content_size_mismatch_422(client: TestClient) -> None:
    char_id = _create_character(client, "read_size")
    ver = _create_version(client, char_id)
    data = _png_bytes()
    rel = f"characters/read_api/{ver['id']}/front.png"
    _write_managed(rel, data)
    asset = _attach_artifact(
        client,
        ver["id"],
        "front",
        data=data,
        rel_path=rel,
        size_bytes=len(data) + 1,
    )

    resp = client.get(_content_url(asset))
    assert resp.status_code == 422, resp.text
    assert "size mismatch" in resp.text


# ── Ownership isolation ──────────────────────────────────────────────────────


def test_content_cross_character_404(client: TestClient) -> None:
    char_a = _create_character(client, "read_owner_a")
    char_b = _create_character(client, "read_owner_b")
    ver = _create_version(client, char_a)
    asset = _attach_artifact(client, ver["id"], "front")

    url = _content_url(asset).replace(f"/characters/{char_a}/", f"/characters/{char_b}/")
    resp = client.get(url)
    assert resp.status_code == 404, resp.text


def test_content_cross_version_404(client: TestClient) -> None:
    char_id = _create_character(client, "read_xver")
    ver_1 = _create_version(client, char_id)
    ver_2 = _create_version(client, char_id)
    asset = _attach_artifact(client, ver_1["id"], "front")

    url = _content_url(asset).replace(f"/versions/{ver_1['id']}/", f"/versions/{ver_2['id']}/")
    resp = client.get(url)
    assert resp.status_code == 404, resp.text


def test_content_cross_workspace_404(client: TestClient) -> None:
    char_id = _create_character(client, "read_xws")
    ver = _create_version(client, char_id)
    asset = _attach_artifact(client, ver["id"], "front")

    resp = client.get(_content_url(asset), params={"workspace_id": "foreign_ws"})
    assert resp.status_code == 404, resp.text


def test_content_unknown_asset_404(client: TestClient) -> None:
    char_id = _create_character(client, "read_unknown_asset")
    ver = _create_version(client, char_id)
    _attach_artifact(client, ver["id"], "front")

    import uuid

    url = (
        f"/api/v2/characters/{char_id}/versions/{ver['id']}"
        f"/assets/{uuid.uuid4()}/content"
    )
    resp = client.get(url)
    assert resp.status_code == 404, resp.text


# ── Containment: traversal and symlink escapes ───────────────────────────────


def test_content_traversal_escape_422(client: TestClient) -> None:
    char_id = _create_character(client, "read_traversal")
    ver = _create_version(client, char_id)
    data = _png_bytes()
    rel_path = "../outside_managed.png"
    asset = _attach_artifact(
        client,
        ver["id"],
        "front",
        data=data,
        rel_path=rel_path,
        state="ready",
    )

    resp = client.get(_content_url(asset))
    assert resp.status_code == 422, resp.text
    assert "escapes managed storage" in resp.text
    # The failing relative path must not leak into the response.
    assert rel_path not in resp.text
    assert str(_managed_root()) not in resp.text


def test_content_symlink_escape_422(client: TestClient) -> None:
    char_id = _create_character(client, "read_symlink")
    ver = _create_version(client, char_id)
    data = _png_bytes()

    # A managed entry that is a symlink pointing OUTSIDE the managed root.
    outside = _managed_root().parent / "outside_secret.png"
    outside.write_bytes(data)
    link_rel = f"characters/read_api/{ver['id']}/front_link.png"
    link_abs = _managed_root() / link_rel
    link_abs.parent.mkdir(parents=True, exist_ok=True)
    try:
        link_abs.symlink_to(outside)
    except OSError as exc:  # pragma: no cover - platform without symlink rights
        pytest.skip(f"symlink creation unavailable: {exc}")

    asset = _attach_artifact(
        client,
        ver["id"],
        "front",
        data=data,
        rel_path=link_rel,
        state="ready",
    )

    resp = client.get(_content_url(asset))
    assert resp.status_code == 422, resp.text
    assert "escapes managed storage" in resp.text
    assert "outside_secret" not in resp.text


# ── Draft validation parity ──────────────────────────────────────────────────


def test_validation_matches_publish_missing_slots(client: TestClient) -> None:
    char_id = _create_character(client, "read_val_missing")
    ver = _create_version(client, char_id)
    _attach_artifact(client, ver["id"], "front")
    _attach_artifact(client, ver["id"], "back")

    # Draft validation: incomplete + actionable errors.
    val = client.get(f"/api/v2/characters/versions/{ver['id']}/validation")
    assert val.status_code == 200
    body = val.json()
    assert body["version_id"] == ver["id"]
    assert body["character_id"] == char_id
    assert body["status"] == "invalid"
    assert body["complete"] is False
    assert set(body["missing_slots"]) == set(CORE_POSE_SLOTS) - {"front", "back"}
    assert any("Missing required core pose slots" in e for e in body["errors"])

    # Publish rejects with the SAME missing slots (parity).
    pub = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub.status_code == 422
    detail = pub.json()["detail"]
    assert set(detail["missing_slots"]) == set(body["missing_slots"])
    assert detail["errors"] == body["errors"]

    # Still a draft after read-only validation (no mutation, no publish).
    fresh = client.get(f"/api/v2/characters/{char_id}/versions").json()
    assert fresh[0]["status"] == "draft"


def test_validation_valid_when_publishable_and_publish_succeeds(
    client: TestClient,
) -> None:
    char_id = _create_character(client, "read_val_valid")
    ver = _full_valid_pack(client, char_id)

    val = client.get(f"/api/v2/characters/versions/{ver['id']}/validation")
    assert val.status_code == 200
    body = val.json()
    assert body["status"] == "valid"
    assert body["complete"] is True
    assert body["missing_slots"] == []
    assert body["errors"] == []

    pub = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"


def test_validation_parity_for_corrupt_asset(client: TestClient) -> None:
    """The SAME error list must come from draft validation and publish."""
    char_id = _create_character(client, "read_val_corrupt")
    ver = _create_version(client, char_id)
    for slot in CORE_POSE_SLOTS:
        data = _png_bytes() if slot != "side" else b"not an image"
        _attach_artifact(client, ver["id"], slot, data=data)

    val = client.get(f"/api/v2/characters/versions/{ver['id']}/validation")
    assert val.status_code == 200
    body = val.json()
    assert body["status"] == "invalid"
    assert body["complete"] is True
    assert any("not a decodable image" in e for e in body["errors"])

    pub = client.post(
        f"/api/v2/characters/versions/{ver['id']}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub.status_code == 422
    detail = pub.json()["detail"]
    assert detail["errors"] == body["errors"]


def test_validation_unknown_version_404(client: TestClient) -> None:
    import uuid

    resp = client.get(f"/api/v2/characters/versions/{uuid.uuid4()}/validation")
    assert resp.status_code == 404


def test_no_absolute_path_disclosure_anywhere(client: TestClient) -> None:
    """No character API response may leak the managed root or drive paths."""
    char_id = _create_character(client, "read_no_leak")
    ver = _full_valid_pack(client, char_id)

    root_str = str(_managed_root())
    responses = [
        client.get(f"/api/v2/characters/{char_id}"),
        client.get(f"/api/v2/characters/{char_id}/versions"),
        client.get(f"/api/v2/characters/versions/{ver['id']}/validation"),
    ]
    for resp in responses:
        assert resp.status_code in (200, 422), resp.text
        assert root_str not in resp.text, resp.text
        assert ":\\" not in resp.text.replace(root_str, ""), resp.text

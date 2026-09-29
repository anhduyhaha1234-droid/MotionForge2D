"""Focused tests for Character Library domain & API (S06-T01)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import Artifact


def _session():
    service = deps._job_service
    assert service is not None
    return service._session_factory()


def _create_ready_image_artifact(suffix: str = "") -> str:
    """Create a ready image artifact with a REAL managed PNG on disk.

    The publish gate (S06-T03) validates the on-disk file, so test artifacts
    must have an actual decodable image with matching SHA-256/size.
    """
    import hashlib
    import uuid
    from io import BytesIO
    from pathlib import Path

    from PIL import Image

    uid = uuid.uuid4().hex[:8]
    rel = f"characters/test_pose_{uid}_{suffix}.png"
    buf = BytesIO()
    # alpha 200 = real transparency (publish gate rejects fully-opaque RGBA)
    Image.new("RGBA", (256, 256), (120, 60, 200, 200)).save(buf, format="PNG")
    data = buf.getvalue()

    svc = deps._job_service
    assert svc is not None
    target = Path(svc._managed_root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    with _session() as s:
        art = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=rel,
            state="ready",
            size_bytes=len(data),
            mime_type="image/png",
            sha256=hashlib.sha256(data).hexdigest(),
        )
        s.add(art)
        s.commit()
        return art.id


def test_character_crud(client: TestClient) -> None:
    # 1. Create Character
    resp = client.post(
        "/api/v2/characters",
        json={
            "name": "Stickman Hero",
            "code": "stickman_hero",
            "character_type": "character",
            "symmetry": "symmetric",
            "description": "Main stickman character",
        },
    )
    assert resp.status_code == 201, resp.text
    char = resp.json()
    assert char["name"] == "Stickman Hero"
    assert char["code"] == "stickman_hero"
    assert char["status"] == "draft"
    assert char["revision"] == 1
    char_id = char["id"]

    # 2. Duplicate active code conflict (409)
    resp2 = client.post(
        "/api/v2/characters",
        json={"name": "Duplicate", "code": "STICKMAN_HERO"},
    )
    assert resp2.status_code == 409

    # 3. Read Character
    get_resp = client.get(f"/api/v2/characters/{char_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == char_id

    # 4. List Characters
    list_resp = client.get("/api/v2/characters")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] >= 1
    assert any(c["id"] == char_id for c in body["characters"])

    # 5. Update Character (CAS)
    patch_resp = client.patch(
        f"/api/v2/characters/{char_id}",
        json={"name": "Stickman Super Hero", "revision": char["revision"]},
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["name"] == "Stickman Super Hero"
    assert updated["revision"] == 2

    # Stale CAS revision (409)
    stale_resp = client.patch(
        f"/api/v2/characters/{char_id}",
        json={"name": "Stale", "revision": 1},
    )
    assert stale_resp.status_code == 409


def test_pack_version_lifecycle_and_publish_gate(client: TestClient) -> None:
    # Create Character
    char_resp = client.post(
        "/api/v2/characters",
        json={"name": "Pack Test", "code": "pack_test"},
    )
    assert char_resp.status_code == 201
    char_id = char_resp.json()["id"]

    # 1. Create Pack Version
    ver_resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert ver_resp.status_code == 201
    ver = ver_resp.json()
    assert ver["version"] == 1
    assert ver["status"] == "draft"
    ver_id = ver["id"]

    # 2. Try publish without all 6 core slots -> 422 error
    pub_fail = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub_fail.status_code == 422
    assert "missing_slots" in pub_fail.json()["detail"]

    # 3. Attach all 6 core pose slots
    slots = ["front", "three_quarter", "side", "back", "sitting", "walking"]
    for slot in slots:
        art_id = _create_ready_image_artifact(slot)
        att_resp = client.post(
            f"/api/v2/characters/versions/{ver_id}/assets",
            json={"pose_slot": slot, "artifact_id": art_id},
        )
        assert att_resp.status_code == 200, att_resp.text
        asset = att_resp.json()
        assert asset["pose_slot"] == slot

    # 4. Publish Pack Version -> 200 success
    pub_pass = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish",
        json={"revision": ver["revision"]},
    )
    assert pub_pass.status_code == 200, pub_pass.text
    published_ver = pub_pass.json()
    assert published_ver["status"] == "published"
    assert published_ver["published_at"] is not None

    # 5. Immutability check: cannot attach asset to published version (409)
    art_extra = _create_ready_image_artifact()
    att_fail = client.post(
        f"/api/v2/characters/versions/{ver_id}/assets",
        json={"pose_slot": "front", "artifact_id": art_extra},
    )
    assert att_fail.status_code == 409


def test_character_archive(client: TestClient) -> None:
    char_resp = client.post(
        "/api/v2/characters",
        json={"name": "To Archive", "code": "to_archive"},
    )
    assert char_resp.status_code == 201
    char = char_resp.json()

    # Archive character
    arch_resp = client.post(
        f"/api/v2/characters/{char['id']}/archive",
        json={"revision": char["revision"]},
    )
    assert arch_resp.status_code == 200
    assert arch_resp.json()["status"] == "archived"

    # Archived code can now be reused by a new active character
    reuse_resp = client.post(
        "/api/v2/characters",
        json={"name": "Reused Code", "code": "to_archive"},
    )
    assert reuse_resp.status_code == 201

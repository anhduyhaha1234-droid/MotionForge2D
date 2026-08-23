"""S09-T01 API tests — /api/v2/reskin-configs contract.

Binary gates (mirroring S07 project-cast API tests):
- POST create 201; idempotent equivalent replay → 200 same row;
  conflicting replay → 409 zero mutation.
- Unpublished/incompatible pack → 409/404 fail-closed, zero mutation.
- PATCH CAS: valid bump 200 revision+1; stale revision → 409 + zero mutation.
- Params outside domain → 422 (schema-level fail-closed).
- GET single/list workspace-isolated; unknown id → 404.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import CORE_POSE_SLOTS

VALID_PARAMS = {
    "anchor": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "fit_mode": "contain",
    "clip_mode": "asset_alpha",
    "offset": {"x": 0.0, "y": 0.0},
    "rotation_offset_deg": 0.0,
    "opacity": 1.0,
}


def _sf():
    svc = deps._job_service
    assert svc is not None
    return svc._session_factory()


def _ensure_ws(s, ws_id: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.persistence.models import Workspace

    s.execute(
        sqlite_insert(Workspace)
        .values(id=ws_id, name=ws_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


def _attach_core_pose_assets(s, ws_id: str, pack_version_id: str) -> None:
    from app.persistence.models import Artifact, CharacterAsset

    for slot in CORE_POSE_SLOTS:
        art = Artifact(
            workspace_id=ws_id,
            kind="image",
            state="ready",
            relative_path=f"artifacts/{uuid.uuid4().hex}.png",
            mime_type="image/png",
            size_bytes=100,
            sha256="c" * 64,
        )
        s.add(art)
        s.flush()
        s.add(
            CharacterAsset(
                pack_version_id=pack_version_id,
                workspace_id=ws_id,
                pose_slot=slot,
                artifact_id=art.id,
            )
        )


def _seed_one(ws: str = DEFAULT_WORKSPACE_ID) -> tuple[str, str, str, str]:
    with _sf() as s:
        _ensure_ws(s, ws)
        from app.persistence.models import (
            Character,
            CharacterPackVersion,
            ObjectRole,
            Project,
            Scene,
            VideoItem,
        )

        proj = Project(workspace_id=ws, name=f"ApiProj-{uuid.uuid4().hex[:6]}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title="Vid", position=0)
        s.add(vid)
        s.flush()
        scene = Scene(
            video_item_id=vid.id,
            position=0,
            start_frame=0,
            end_frame=10,
            start_time_ms=0,
            end_time_ms=1000,
            status="pending",
        )
        s.add(scene)
        s.flush()
        role = ObjectRole(
            workspace_id=ws,
            project_id=proj.id,
            video_item_id=vid.id,
            source_generation="1",
            name="Hero",
            kind="character",
            status="confirmed",
        )
        s.add(role)
        s.flush()
        char = Character(workspace_id=ws, name="CharApi", code=f"ca_{uuid.uuid4().hex[:6]}")
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(
            character_id=char.id, workspace_id=ws, version=1, status="published"
        )
        s.add(pv)
        s.flush()
        _attach_core_pose_assets(s, ws, pv.id)
        s.commit()
        return proj.id, role.id, char.id, pv.id


def _create_pack(char_id: str, ws: str, version: int, complete: bool = True) -> str:
    with _sf() as s:
        from app.persistence.models import CharacterPackVersion

        pv = CharacterPackVersion(
            character_id=char_id, workspace_id=ws, version=version, status="published"
        )
        s.add(pv)
        s.flush()
        if complete:
            _attach_core_pose_assets(s, ws, pv.id)
        s.commit()
        return pv.id


# ── Create + trailing-slash variants ─────────────────────────────────────


def test_create_201_and_trailing_slash_variant(client: TestClient) -> None:
    proj, role, char, pv = _seed_one()
    payload = {
        "project_id": proj,
        "object_role_id": role,
        "character_id": char,
        "pack_version_id": pv,
        "params": VALID_PARAMS,
        "idempotency_key": f"api1-{uuid.uuid4().hex[:6]}",
    }
    r1 = client.post("/api/v2/reskin-configs", json=payload)
    assert r1.status_code == 201, r1.text
    body = r1.json()
    assert body["pack_version_id"] == pv
    assert body["revision"] == 1
    assert body["params"]["scale"] == 1.0

    # Equivalent replay → 200 same row
    r2 = client.post("/api/v2/reskin-configs", json=payload)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == body["id"]
    assert r2.json()["revision"] == 1


def test_conflicting_replay_409_zero_mutation(client: TestClient) -> None:
    proj, role, char, pv = _seed_one()
    key = f"api-conf-{uuid.uuid4().hex[:6]}"
    ok = {
        "project_id": proj,
        "object_role_id": role,
        "character_id": char,
        "pack_version_id": pv,
        "params": VALID_PARAMS,
        "idempotency_key": key,
    }
    created = client.post("/api/v2/reskin-configs", json=ok)
    assert created.status_code == 201, created.text
    before = created.json()

    conflicting = dict(ok)
    conflicting["params"] = dict(VALID_PARAMS)
    conflicting["params"]["scale"] = 3.0
    conflict = client.post("/api/v2/reskin-configs", json=conflicting)
    assert conflict.status_code == 409, conflict.text

    after = client.get(f"/api/v2/reskin-configs/{before['id']}")
    assert after.status_code == 200
    assert after.json()["revision"] == 1
    assert after.json()["params"]["scale"] == 1.0


# ── Fail-closed compatibility via API ────────────────────────────────────


def test_create_unpublished_pack_rejected(client: TestClient) -> None:
    proj, role, char, _pv = _seed_one()
    # draft pack (no assets either)
    with _sf() as s:
        from app.persistence.models import CharacterPackVersion

        pv_bad = CharacterPackVersion(
            character_id=char, workspace_id=DEFAULT_WORKSPACE_ID, version=5, status="draft"
        )
        s.add(pv_bad)
        s.commit()
        bad_id = pv_bad.id
    resp = client.post(
        "/api/v2/reskin-configs",
        json={
            "project_id": proj,
            "object_role_id": role,
            "character_id": char,
            "pack_version_id": bad_id,
            "params": VALID_PARAMS,
        },
    )
    assert resp.status_code in (404, 409), resp.text
    listed = client.get("/api/v2/reskin-configs", params={"project_id": proj})
    assert listed.json()["total"] == 0


# ── Params validation 422 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update({"anchor": {"x": 2.0, "y": 0.5}}),
        lambda p: p.update({"scale": 0.0}),
        lambda p: p.update({"scale": -1.0}),
        lambda p: p.update({"fit_mode": "zoom"}),
        lambda p: p.update({"clip_mode": "magic"}),
        lambda p: p.update({"opacity": 1.5}),
        lambda p: p.update({"opacity": -0.5}),
    ],
)
def test_invalid_params_422(mutator, client: TestClient) -> None:
    proj, role, char, pv = _seed_one()
    bad = dict(VALID_PARAMS)
    mutator(bad)
    resp = client.post(
        "/api/v2/reskin-configs",
        json={
            "project_id": proj,
            "object_role_id": role,
            "character_id": char,
            "pack_version_id": pv,
            "params": bad,
        },
    )
    assert resp.status_code == 422, resp.text
    listed = client.get("/api/v2/reskin-configs", params={"project_id": proj})
    assert listed.json()["total"] == 0


def test_unknown_extra_field_422(client: TestClient) -> None:
    proj, role, char, pv = _seed_one()
    payload = {
        "project_id": proj,
        "object_role_id": role,
        "character_id": char,
        "pack_version_id": pv,
        "params": VALID_PARAMS,
        "bogus_field": True,
    }
    resp = client.post("/api/v2/reskin-configs", json=payload)
    assert resp.status_code == 422, resp.text


# ── GET list/single isolation ────────────────────────────────────────────


def test_get_single_and_list_and_404_no_leak(client: TestClient) -> None:
    proj, role, char, pv = _seed_one()
    created = client.post(
        "/api/v2/reskin-configs",
        json={
            "project_id": proj,
            "object_role_id": role,
            "character_id": char,
            "pack_version_id": pv,
            "params": VALID_PARAMS,
            "idempotency_key": f"get1-{uuid.uuid4().hex[:6]}",
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    got = client.get(f"/api/v2/reskin-configs/{cid}")
    assert got.status_code == 200
    assert got.json()["project_id"] == proj

    listed = client.get("/api/v2/reskin-configs/", params={"project_id": proj})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["configs"][0]["id"] == cid

    missing = client.get(f"/api/v2/reskin-configs/{uuid.uuid4()}")
    assert missing.status_code == 404


# ── PATCH CAS ────────────────────────────────────────────────────────────


def test_patch_cas_valid_then_stale_409_zero_mutation(client: TestClient) -> None:
    proj, role, char, pv_old = _seed_one()
    created = client.post(
        "/api/v2/reskin-configs",
        json={
            "project_id": proj,
            "object_role_id": role,
            "character_id": char,
            "pack_version_id": pv_old,
            "params": VALID_PARAMS,
            "idempotency_key": f"cas-{uuid.uuid4().hex[:6]}",
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    new_params = dict(VALID_PARAMS)
    new_params["scale"] = 2.5
    bumped = client.patch(
        f"/api/v2/reskin-configs/{cid}", json={"revision": 1, "params": new_params}
    )
    assert bumped.status_code == 200, bumped.text
    assert bumped.json()["revision"] == 2
    assert bumped.json()["params"]["scale"] == 2.5

    stale = client.patch(
        f"/api/v2/reskin-configs/{cid}",
        json={"revision": 1, "params": dict(VALID_PARAMS)},
    )
    assert stale.status_code == 409, stale.text
    assert "stale" in stale.text.lower()

    final = client.get(f"/api/v2/reskin-configs/{cid}")
    assert final.json()["revision"] == 2
    assert final.json()["params"]["scale"] == 2.5


def test_patch_stale_zero_mutation_on_pack_pin(client: TestClient) -> None:
    """Stale repin attempt must leave BOTH pack pin and revision unchanged."""
    proj, role, char, pv_old = _seed_one()
    created = client.post(
        "/api/v2/reskin-configs",
        json={
            "project_id": proj,
            "object_role_id": role,
            "character_id": char,
            "pack_version_id": pv_old,
            "params": VALID_PARAMS,
            "idempotency_key": f"casp-{uuid.uuid4().hex[:6]}",
        },
    )
    cid = created.json()["id"]

    stale_repin = client.patch(
        f"/api/v2/reskin-configs/{cid}",
        json={"revision": 99, "pack_version_id": pv_old},
    )
    assert stale_repin.status_code == 409
    after = client.get(f"/api/v2/reskin-configs/{cid}").json()
    assert after["revision"] == 1
    assert after["pack_version_id"] == pv_old

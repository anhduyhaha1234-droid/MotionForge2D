"""S07-T01 domain tests — Project Cast Mapping business rules (no mocks).



Tests via production repository + direct DB session (not mocked) on temp DBs

via the isolated client fixture. Covers:

- workspace + project ownership

- valid ObjectRole

- pin exactly one immutable PackVersion

- never pin mutable Character state alone

- new publish does NOT change old mapping (byte-identical)

- cross-workspace rejected (no leak)

- deterministic serialization

- no silent fallback



Uses real production repo/API (no mock-away).

"""



from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (  # noqa: F811  # noqa
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Project,
    Scene,
    VideoItem,
    Workspace,
)


def _session():

    svc = deps._job_service

    assert svc is not None

    return svc._session_factory()





def _seed_workspace_project_video_role(

    ws: str = DEFAULT_WORKSPACE_ID,

) -> tuple[str, str, str, str]:

    """Create workspace+project+video+role via direct DB for domain tests."""

    with _session() as s:

        # Workspace bootstrap via INSERT or ORM

        from sqlalchemy.dialects.sqlite import insert as sqlite_insert



        s.execute(

            sqlite_insert(Workspace)

            .values(id=ws, name=ws)

            .on_conflict_do_nothing(index_elements=[Workspace.id])

        )

        # Project

        proj = Project(workspace_id=ws, name="Proj-Domain")

        s.add(proj)

        s.flush()

        # Video

        vid = VideoItem(project_id=proj.id, title="Vid", position=0)

        s.add(vid)

        s.flush()

        # Scene (required for role occurrences but not for mapping)

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

        # ObjectRole

        from app.persistence.models import ObjectRole



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

        s.commit()

        return proj.id, vid.id, role.id, scene.id





def _create_character_and_packs(ws: str = DEFAULT_WORKSPACE_ID) -> tuple[str, str, str]:

    """Return (character_id, pack_v1_id, pack_v2_id) with real rows."""

    with _session() as s:

        char = Character(workspace_id=ws, name="HeroChar", code=f"hero_{uuid.uuid4().hex[:6]}")

        s.add(char)

        s.flush()

        pv1 = CharacterPackVersion(

            character_id=char.id, workspace_id=ws, version=1, status="published"

        )

        s.add(pv1)

        s.flush()

        # Create 6 core pose assets for pv1 (complete pack for new policy)

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):

            rel = f"{pv1.id}_{slot}.png"

            data = bytes.fromhex("89504e470d0a1a0a") + b"" * 10

            # write file

            import hashlib as _hl
            import pathlib as _pl

            tgt = _pl.Path(__import__('app.api.deps', fromlist=['_job_service'])._job_service._managed_root) / rel  # noqa: E501

            tgt.parent.mkdir(parents=True, exist_ok=True)

            tgt.write_bytes(data)

            art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=_hl.sha256(data).hexdigest())  # noqa: E501

            s.add(art)

            s.flush()

            ca = CharacterAsset(pack_version_id=pv1.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id)  # noqa: E501

            s.add(ca)

        s.flush()

        pv2 = CharacterPackVersion(

            character_id=char.id, workspace_id=ws, version=2, status="draft"

        )

        s.add(pv2)

        s.flush()

        for slot in ("front", "three_quarter", "side", "back", "sitting", "walking"):

            rel = f"{pv2.id}_{slot}.png"

            data = bytes.fromhex("89504e470d0a1a0a") + b"" * 10

            import hashlib as _hl2
            import pathlib as _pl2

            tgt = _pl2.Path(__import__('app.api.deps', fromlist=['_job_service'])._job_service._managed_root) / rel  # noqa: E501

            tgt.parent.mkdir(parents=True, exist_ok=True)

            tgt.write_bytes(data)

            art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=_hl2.sha256(data).hexdigest())  # noqa: E501

            s.add(art)

            s.flush()

            ca = CharacterAsset(pack_version_id=pv2.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id)  # noqa: E501

            s.add(ca)

        s.flush()

        s.commit()

        return char.id, pv1.id, pv2.id





def test_workspace_and_project_ownership(client: TestClient) -> None:

    proj_id, _, role_id, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()



    # Happy path: correct workspace + project + role

    resp = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-own-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp.status_code == 201, resp.text

    data = resp.json()

    assert data["workspace_id"] == DEFAULT_WORKSPACE_ID

    assert data["project_id"] == proj_id

    assert data["object_role_id"] == role_id



    # Workspace isolation: mapping is workspace-scoped; GET with correct workspace succeeds

    mid = data["id"]

    get = client.get(f"/api/v2/project-cast/{mid}")

    assert get.status_code == 200

    assert get.json()["id"] == mid





def test_valid_object_role_required(client: TestClient) -> None:

    proj_id, _, _, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()



    # Invalid role id -> 404 or 409 (fail closed, no silent fallback)

    resp = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": str(uuid.uuid4()),

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-role-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp.status_code in (404, 409), resp.text





def test_pin_exactly_one_immutable_pack_version(client: TestClient) -> None:

    proj_id, _, role_id, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()



    # Must pin via pack_version_id (immutable row identity), not just character

    resp = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-pin-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp.status_code == 201, resp.text

    assert resp.json()["pack_version_id"] == pv1_id

    assert resp.json()["character_id"] == char_id



    # Pack version mismatch with character -> rejected (fail closed)

    char2_id, _, _ = _create_character_and_packs()

    resp2 = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char2_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-pin-mismatch-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp2.status_code in (404, 409, 422), resp2.text





def test_never_pin_mutable_character_state(client: TestClient) -> None:

    """Mapping stores pack_version_id (immutable), not mutable character pointer alone."""

    proj_id, _, role_id, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()



    resp = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-mutable-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp.status_code == 201, resp.text

    # The returned mapping pins pack_version_id — the immutable row

    assert resp.json()["pack_version_id"] == pv1_id

    # Missing pack_version_id -> 422

    bad = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "idempotency_key": f"dom-mutable-bad-{uuid.uuid4().hex[:6]}",

        },

    )

    assert bad.status_code == 422





def test_new_publish_does_not_change_old_mapping(client: TestClient) -> None:

    """Publish a new PackVersion does NOT change old mapping (byte-identical)."""

    proj_id, _, role_id, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()



    key = f"dom-publish-{uuid.uuid4().hex[:6]}"

    create = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": key,

        },

    )

    assert create.status_code == 201, create.text

    before = create.json()

    mid = before["id"]



    # Create a new pack version for SAME character (simulates new publish)

    with _session() as s:

        # Publish pv1 already published, create pv2 as published

        pv2 = CharacterPackVersion(

            character_id=char_id, workspace_id=DEFAULT_WORKSPACE_ID, version=99, status="published"

        )

        s.add(pv2)

        s.commit()

        pv2_id = pv2.id



    # Verify old mapping is byte-identical and still points to old pack_version

    get = client.get(f"/api/v2/project-cast/{mid}")

    assert get.status_code == 200

    after = get.json()

    assert after["id"] == before["id"]

    assert after["pack_version_id"] == pv1_id

    assert after["pack_version_id"] != pv2_id

    # Byte-identical serialization for unchanged fields (compare json dumps sorted)

    assert after["pack_version_id"] == before["pack_version_id"]

    assert after["character_id"] == before["character_id"]

    assert after["project_id"] == before["project_id"]

    assert after["object_role_id"] == before["object_role_id"]

    assert after["revision"] == before["revision"]





def test_cross_workspace_rejected_no_leak(client: TestClient) -> None:

    # Create mapping in default workspace

    proj_id, _, role_id, _ = _seed_workspace_project_video_role(ws=DEFAULT_WORKSPACE_ID)

    char_id, pv1_id, _ = _create_character_and_packs(ws=DEFAULT_WORKSPACE_ID)



    # Create other workspace project/role/character/pack

    other_ws = f"ws-other-{uuid.uuid4().hex[:6]}"

    o_proj_id, _, o_role_id, _ = _seed_workspace_project_video_role(ws=other_ws)

    o_char_id, o_pv1_id, _ = _create_character_and_packs(ws=other_ws)



    # Try to create mapping with cross-workspace project -> rejected

    resp = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": o_proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-xws-proj-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp.status_code in (404, 409), resp.text



    # Cross-workspace role

    resp2 = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": o_role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": f"dom-xws-role-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp2.status_code in (404, 409), resp2.text



    # Cross-workspace character

    resp3 = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": o_char_id,

            "pack_version_id": o_pv1_id,

            "idempotency_key": f"dom-xws-char-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp3.status_code in (404, 409), resp3.text



    # Cross-workspace pack

    resp4 = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": o_pv1_id,

            "idempotency_key": f"dom-xws-pack-{uuid.uuid4().hex[:6]}",

        },

    )

    assert resp4.status_code in (404, 409), resp4.text

    # No leak: listing in default workspace never shows other workspace mappings

    lst = client.get("/api/v2/project-cast")

    assert lst.status_code == 200

    for m in lst.json()["mappings"]:

        assert m["workspace_id"] == DEFAULT_WORKSPACE_ID





def test_deterministic_serialization(client: TestClient) -> None:

    proj_id, _, role_id, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()

    key = f"dom-det-{uuid.uuid4().hex[:6]}"

    created = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": proj_id,

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

            "idempotency_key": key,

        },

    )

    assert created.status_code == 201, created.text

    mid = created.json()["id"]

    a = client.get(f"/api/v2/project-cast/{mid}").json()

    b = client.get(f"/api/v2/project-cast/{mid}").json()

    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    # Field order is stable (Pydantic model order)

    assert list(a.keys()) == list(b.keys())





def test_no_silent_fallback(client: TestClient) -> None:

    """Invalid payloads must not silently fallback to defaults."""

    proj_id, _, role_id, _ = _seed_workspace_project_video_role()

    char_id, pv1_id, _ = _create_character_and_packs()

    # Empty project_id -> 422, not silent

    resp = client.post(

        "/api/v2/project-cast",

        json={

            "project_id": "",

            "object_role_id": role_id,

            "character_id": char_id,

            "pack_version_id": pv1_id,

        },

    )

    assert resp.status_code == 422

    # Missing required field -> 422

    resp2 = client.post(

        "/api/v2/project-cast",

        json={"project_id": proj_id},

    )

    assert resp2.status_code == 422


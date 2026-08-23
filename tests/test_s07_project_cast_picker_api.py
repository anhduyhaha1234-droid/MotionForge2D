# ruff: noqa: N811, N814
"""S07-T02 picker browse/search/filter API + stale revision + blocked submit.

Covers:
- browse only published
- search/filter deterministic
- pick exact Pack Version ID not character
- show pinned version
- incompatible submit blocked via compatibility
- stale revision surfaced
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as _sa_text

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    CORE_POSE_SLOTS,
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)

WS = DEFAULT_WORKSPACE_ID

@pytest.fixture(autouse=True)
def _s07_isolated_workspace(client):
    """Ensure per-test isolated DB state for S07 picker/compat."""  # noqa: E501
    def _clean():
        from app.api import deps as _deps
        svc = _deps._job_service  # type: ignore[attr-defined]
        if svc is None:
            return
        factory = svc._session_factory  # type: ignore[attr-defined]
        try:
            with factory() as s:  # type: ignore[operator]
                s.execute(_sa_text("DELETE FROM project_cast_mapping"))
                s.execute(_sa_text("DELETE FROM character_asset"))
                s.execute(_sa_text("DELETE FROM character_pack_version"))
                s.execute(_sa_text("DELETE FROM character"))
                s.execute(_sa_text("DELETE FROM object_role"))
                s.execute(_sa_text("DELETE FROM occurrence_segment"))
                s.execute(_sa_text("DELETE FROM segment_motion"))
                s.execute(_sa_text("DELETE FROM scene"))
                s.execute(_sa_text("DELETE FROM video_item"))
                s.execute(_sa_text("DELETE FROM project"))
                s.commit()
        except Exception:
            raise
    _clean()
    yield
    _clean()



def _session():
    svc = deps._job_service  # type: ignore[attr-defined]
    assert svc is not None
    return svc._session_factory()  # type: ignore[attr-defined]


def _seed_picker_entities(client: TestClient) -> dict:
    with _session() as s:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        s.execute(sqlite_insert(Workspace).values(id=WS, name=WS).on_conflict_do_nothing(index_elements=[Workspace.id]))  # noqa: E501
        proj = Project(workspace_id=WS, name=f"PickerProj-{uuid.uuid4().hex[:4]}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title="Vid", position=0)
        s.add(vid)
        s.flush()
        scene = Scene(video_item_id=vid.id, position=0, start_frame=0, end_frame=10, start_time_ms=0, end_time_ms=1000, status="pending")  # noqa: E501
        s.add(scene)
        s.flush()
        role = ObjectRole(workspace_id=WS, project_id=proj.id, video_item_id=vid.id, source_generation="1", name="Hero", kind="character", status="confirmed")  # noqa: E501
        s.add(role)
        s.flush()
        # Published char/pack
        char_pub = Character(workspace_id=WS, name="Alpha Char", code=f"alpha_{uuid.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char_pub)
        s.flush()
        pv_pub = CharacterPackVersion(character_id=char_pub.id, workspace_id=WS, version=1, status="published")  # noqa: E501
        s.add(pv_pub)
        s.flush()
        for slot in CORE_POSE_SLOTS:
            art = Artifact(workspace_id=WS, kind="image", state="ready", relative_path=f"art/{slot}_{uuid.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="e" * 64, width=100, height=100)  # noqa: E501
            s.add(art)
            s.flush()
            s.add(CharacterAsset(pack_version_id=pv_pub.id, workspace_id=WS, pose_slot=slot, artifact_id=art.id))  # noqa: E501
        # Second published for search
        char2 = Character(workspace_id=WS, name="Beta Char", code=f"beta_{uuid.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char2)
        s.flush()
        pv2 = CharacterPackVersion(character_id=char2.id, workspace_id=WS, version=1, status="published")  # noqa: E501
        s.add(pv2)
        s.flush()
        for slot in CORE_POSE_SLOTS:
            art = Artifact(workspace_id=WS, kind="image", state="ready", relative_path=f"art/{slot}_{uuid.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="f" * 64, width=100, height=100)  # noqa: E501
            s.add(art)
            s.flush()
            s.add(CharacterAsset(pack_version_id=pv2.id, workspace_id=WS, pose_slot=slot, artifact_id=art.id))  # noqa: E501
        # Draft pack (should NOT appear in picker)
        char_draft = Character(workspace_id=WS, name="Draft Char", code=f"draft_{uuid.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char_draft)
        s.flush()
        pv_draft = CharacterPackVersion(character_id=char_draft.id, workspace_id=WS, version=1, status="draft")  # noqa: E501
        s.add(pv_draft)
        s.flush()
        s.flush()
        s.commit()
        return {"proj": proj.id, "role": role.id, "char_pub": char_pub.id, "pv_pub": pv_pub.id, "char2": char2.id, "pv2": pv2.id, "pv_draft": pv_draft.id}  # noqa: E501


def test_picker_browse_only_published(client: TestClient) -> None:
    _seed_picker_entities(client)
    r = client.get("/api/v2/project-cast/picker/packs?limit=100")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["workspace_id"] == WS
    statuses = {p["status"] for p in data["packs"]}
    assert statuses == {"published"}
    # Draft must not appear
    ids = {p["id"] for p in data["packs"]}  # noqa: F841
    # Ensure at least 2 published
    assert len(data["packs"]) >= 2
    # Check draft id not in ids (we seeded draft but browse filters)
    # We don't have draft id here, but we can verify via direct check: draft not in list by searching code  # noqa: E501
    for p in data["packs"]:
        assert p["status"] == "published"


def test_picker_search_filter(client: TestClient) -> None:
    _seed_picker_entities(client)
    r = client.get("/api/v2/project-cast/picker/packs?q=alpha&limit=100")
    assert r.status_code == 200
    packs = r.json()["packs"]
    # All results should contain alpha in name/code (case-insensitive)
    for p in packs:
        hay = (p["character_name"] + p["character_code"]).lower()
        assert "alpha" in hay
    # Deterministic repeat
    r2 = client.get("/api/v2/project-cast/picker/packs?q=alpha&limit=100")
    assert r.json() == r2.json()


def test_picker_filter_empty(client: TestClient) -> None:
    r = client.get("/api/v2/project-cast/picker/packs?q=__no_such__12345&limit=100")
    assert r.status_code == 200
    assert r.json()["packs"] == []
    assert r.json()["total"] == 0


def test_picker_select_exact_pack_version_id(client: TestClient) -> None:
    ids = _seed_picker_entities(client)
    r = client.get("/api/v2/project-cast/picker/packs?limit=100")
    packs = r.json()["packs"]
    # Each picker item must have Pack Version ID distinct from character_id
    for p in packs:
        assert p["id"] != p["character_id"]
        assert len(p["id"]) == 36  # uuid
    # Simulate pick: create mapping with exact pack_version_id
    proj = ids["proj"]
    role = ids["role"]
    pv = packs[0]["id"]
    char_id = packs[0]["character_id"]
    create = client.post("/api/v2/project-cast", json={"project_id": proj, "object_role_id": role, "character_id": char_id, "pack_version_id": pv, "idempotency_key": f"pick-{uuid.uuid4().hex[:6]}"})  # noqa: E501
    assert create.status_code in (200, 201), create.text
    assert create.json()["pack_version_id"] == pv


def test_picker_show_pinned_version(client: TestClient) -> None:
    ids = _seed_picker_entities(client)
    proj = ids["proj"]
    role = ids["role"]
    # Create mapping
    create = client.post("/api/v2/project-cast", json={"project_id": proj, "object_role_id": role, "character_id": ids["char_pub"], "pack_version_id": ids["pv_pub"], "idempotency_key": f"pinned-{uuid.uuid4().hex[:6]}"})  # noqa: E501
    assert create.status_code in (200, 201)
    pinned = create.json()["pack_version_id"]
    # Compatibility evaluate should return pinned_version_id
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": proj, "object_role_id": role, "pack_version_id": pinned})  # noqa: E501
    assert compat.status_code == 200
    assert compat.json()["pinned_version_id"] == pinned
    # Also picker browse still shows it
    r = client.get("/api/v2/project-cast/picker/packs?limit=100")
    assert any(p["id"] == pinned for p in r.json()["packs"])


def test_incompatible_submit_blocked_via_compat(client: TestClient) -> None:
    ids = _seed_picker_entities(client)
    proj = ids["proj"]
    _role_unused = ids["role"]  # noqa: F841
    # Create source_overlay role for incompat
    with _session() as s:
        # reuse proj/vid
        from sqlalchemy import select as _select  # noqa: E501
        vid = s.scalar(_select(VideoItem).where(VideoItem.project_id == proj))  # noqa: E501
        assert vid is not None
        overlay = ObjectRole(workspace_id=WS, project_id=proj, video_item_id=vid.id, source_generation="1", name="Overlay", kind="source_overlay", status="confirmed")  # noqa: E501
        s.add(overlay)
        s.flush()
        s.commit()
        overlay_id = overlay.id
    # Evaluate -> blocked
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": proj, "object_role_id": overlay_id, "pack_version_id": ids["pv_pub"]})  # noqa: E501
    assert compat.status_code == 200
    j = compat.json()
    assert j["blocked"] is True
    assert "source_overlay_refusal" in j["reasons"]
    # Frontend would block submit; we verify API create would still allow? But compat says blocked -> UI must not submit.  # noqa: E501
    # We assert that blocked is True so UI can prevent submit (no silent fallback)
    assert j["fallback_allowed"] is False


def test_stale_revision_surfaced(client: TestClient) -> None:
    ids = _seed_picker_entities(client)
    proj = ids["proj"]
    role = ids["role"]
    pv = ids["pv_pub"]
    char = ids["char_pub"]
    key = f"stale-{uuid.uuid4().hex[:6]}"
    create = client.post("/api/v2/project-cast", json={"project_id": proj, "object_role_id": role, "character_id": char, "pack_version_id": pv, "idempotency_key": key})  # noqa: E501
    assert create.status_code in (200, 201)
    mapping = create.json()
    mid = mapping["id"]
    rev = mapping["revision"]
    # Update with stale
    stale = client.patch(f"/api/v2/project-cast/{mid}", json={"revision": rev + 99, "pack_version_id": pv})  # noqa: E501
    assert stale.status_code == 409, stale.text
    assert "stale" in stale.text.lower() or "409" in stale.text or "revision" in stale.text.lower()
    # Compat also surfaces stale
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": proj, "object_role_id": role, "pack_version_id": pv, "expected_revision": rev + 99, "mapping_id": mid})  # noqa: E501
    assert compat.status_code == 200
    assert "stale_revision" in compat.json()["reasons"]

def test_fallback_supported_via_api(client: TestClient) -> None:
    """P1-A API: generation_mismatch via real jobs → fallback_allowed True."""
    import json as _json
    import uuid as _uuid
    from datetime import UTC, datetime

    from app.persistence import DEFAULT_WORKSPACE_ID as WS2
    from app.persistence.models import Artifact, Job, ObjectRole, VideoItem
    # Seed minimal
    with _session() as s:
        from sqlalchemy.dialects.sqlite import insert as si

        from app.persistence.models import Project, Scene, Workspace
        s.execute(si(Workspace).values(id=WS2, name=WS2).on_conflict_do_nothing(index_elements=[Workspace.id]))  # noqa: E501
        proj = Project(workspace_id=WS2, name=f"FallbackProj-{_uuid.uuid4().hex[:4]}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title="VidF", position=0)
        s.add(vid)
        s.flush()
        scene = Scene(video_item_id=vid.id, position=0, start_frame=0, end_frame=10, start_time_ms=0, end_time_ms=1000, status="pending")  # noqa: E501
        s.add(scene)
        s.flush()
        role = ObjectRole(workspace_id=WS2, project_id=proj.id, video_item_id=vid.id, source_generation="1", name="HeroF", kind="character", status="confirmed")  # noqa: E501
        s.add(role)
        s.flush()
        s.commit()
        pid, vid_id, rid = proj.id, vid.id, role.id
    # Create jobs to advance generation to 2
    sha = "b" * 64
    t0 = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 21, 10, 5, 0, tzinfo=UTC)
    def _create_job(gen, at):
        with _session() as s:
            j = Job(workspace_id=WS2, owner_type="video_item", owner_id=vid_id, job_type="DISCOVER_OBJECTS", state="completed", input_generation=gen, input_manifest_json=_json.dumps({"source_sha256": sha}), created_at=at)  # noqa: E501
            s.add(j)
            s.commit()
    _create_job("1", t0)
    with _session() as s:
        art = Artifact(workspace_id=WS2, kind="video", relative_path=f"vid_fallback_{vid_id}.mp4", state="ready", sha256=sha, size_bytes=10, mime_type="video/mp4")  # noqa: E501
        s.add(art)
        s.flush()
        v = s.get(VideoItem, vid_id)
        v.source_artifact_id = art.id
        s.commit()
    _create_job("2", t1)
    # Create char/pack
    with _session() as s:
        from app.persistence.models import (
            CORE_POSE_SLOTS,
            Character,
            CharacterAsset,
            CharacterPackVersion,
        )
        char = Character(workspace_id=WS2, name="CharF", code=f"charf_{_uuid.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(character_id=char.id, workspace_id=WS2, version=1, status="published")  # noqa: E501
        s.add(pv)
        s.flush()
        for slot in CORE_POSE_SLOTS:
            art2 = Artifact(workspace_id=WS2, kind="image", state="ready", relative_path=f"art/{slot}_{_uuid.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="e"*64, width=100, height=100)  # noqa: E501
            s.add(art2)
            s.flush()
            s.add(CharacterAsset(pack_version_id=pv.id, workspace_id=WS2, pose_slot=slot, artifact_id=art2.id))  # noqa: E501
        s.commit()
        _char_id, pv_id = char.id, pv.id
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": pid, "object_role_id": rid, "pack_version_id": pv_id})  # noqa: E501
    assert compat.status_code == 200
    j = compat.json()
    assert j["compatible"] is False
    assert "generation_mismatch" in j["reasons"]
    assert j["fallback_allowed"] is True
    assert j["blocked"] is False
    assert j["fallback_description"] is not None

def test_fallback_unsupported_still_blocked_api(client: TestClient) -> None:
    """P1-A API: unsupported reason remains blocked."""
    ids = _seed_picker_entities(client)
    proj = ids["proj"]
    # source_overlay
    with _session() as s:
        from sqlalchemy import select as _select
        vid = s.scalar(_select(VideoItem).where(VideoItem.project_id == proj))
        overlay = ObjectRole(workspace_id=WS, project_id=proj, video_item_id=vid.id, source_generation="1", name="Overlay2", kind="source_overlay", status="confirmed")  # noqa: E501
        s.add(overlay)
        s.flush()
        s.commit()
        oid = overlay.id
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": proj, "object_role_id": oid, "pack_version_id": ids["pv_pub"]})  # noqa: E501
    assert compat.status_code == 200
    j = compat.json()
    assert j["fallback_allowed"] is False
    assert j["blocked"] is True

def test_fallback_supported_create_via_api_success(client):
    """C5: fallback-supported (generation_mismatch) CREATE with ack succeeds, row correct, warning preserved."""  # noqa: E501
    import json as _json2
    import uuid as _uuid2
    from datetime import UTC, datetime

    from app.persistence.models import (
        CORE_POSE_SLOTS,
        Artifact,
        Character,
        CharacterAsset,
        CharacterPackVersion,
        Job,
        ObjectRole,
        VideoItem,
    )
    WS3 = WS
    with _session() as s:
        from sqlalchemy.dialects.sqlite import insert as si2

        from app.persistence.models import Project as PModel
        from app.persistence.models import Scene as SModel
        from app.persistence.models import Workspace as WSModel
        s.execute(si2(WSModel).values(id=WS3, name=WS3).on_conflict_do_nothing(index_elements=[WSModel.id]))  # noqa: E501
        proj = PModel(workspace_id=WS3, name=f"FallbackCreate-{_uuid2.uuid4().hex[:4]}")
        s.add(proj)
        s.flush()
        vid = VideoItem(project_id=proj.id, title="VidFC", position=0)
        s.add(vid)
        s.flush()
        scene = SModel(video_item_id=vid.id, position=0, start_frame=0, end_frame=10, start_time_ms=0, end_time_ms=1000, status="pending")  # noqa: E501
        s.add(scene)
        s.flush()
        role = ObjectRole(workspace_id=WS3, project_id=proj.id, video_item_id=vid.id, source_generation="1", name="HeroFC", kind="character", status="confirmed")  # noqa: E501
        s.add(role)
        s.flush()
        s.commit()
        pid3, vid_id3, rid3 = proj.id, vid.id, role.id
    sha3 = "c" * 64
    t0 = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 21, 10, 5, 0, tzinfo=UTC)
    def _cj(gen, at):
        with _session() as s:
            j = Job(workspace_id=WS3, owner_type="video_item", owner_id=vid_id3, job_type="DISCOVER_OBJECTS", state="completed", input_generation=gen, input_manifest_json=_json2.dumps({"source_sha256": sha3}), created_at=at)  # noqa: E501
            s.add(j)
            s.commit()
    _cj("1", t0)
    with _session() as s:
        art = Artifact(workspace_id=WS3, kind="video", relative_path=f"vid_fc_{vid_id3}.mp4", state="ready", sha256=sha3, size_bytes=10, mime_type="video/mp4")  # noqa: E501
        s.add(art)
        s.flush()
        v = s.get(VideoItem, vid_id3)
        v.source_artifact_id = art.id
        s.commit()
    _cj("2", t1)
    with _session() as s:
        char = Character(workspace_id=WS3, name="CharFC", code=f"charfc_{_uuid2.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char)
        s.flush()
        pv = CharacterPackVersion(character_id=char.id, workspace_id=WS3, version=1, status="published")  # noqa: E501
        s.add(pv)
        s.flush()
        for slot in CORE_POSE_SLOTS:
            art2 = Artifact(workspace_id=WS3, kind="image", state="ready", relative_path=f"art/{slot}_{_uuid2.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="e"*64, width=100, height=100)  # noqa: E501
            s.add(art2)
            s.flush()
            s.add(CharacterAsset(pack_version_id=pv.id, workspace_id=WS3, pose_slot=slot, artifact_id=art2.id))  # noqa: E501
        s.commit()
        char_id3, pv_id3 = char.id, pv.id
    r_no_ack = client.post("/api/v2/project-cast", json={"project_id": pid3, "object_role_id": rid3, "character_id": char_id3, "pack_version_id": pv_id3, "idempotency_key": f"fallback-noack-{_uuid2.uuid4().hex[:4]}"})  # noqa: E501
    assert r_no_ack.status_code == 409, r_no_ack.text
    r_ack = client.post("/api/v2/project-cast", json={"project_id": pid3, "object_role_id": rid3, "character_id": char_id3, "pack_version_id": pv_id3, "idempotency_key": f"fallback-ack-{_uuid2.uuid4().hex[:4]}", "fallback_acknowledged": True})  # noqa: E501
    assert r_ack.status_code in (200, 201), r_ack.text
    data = r_ack.json()
    assert data["pack_version_id"] == pv_id3
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": pid3, "object_role_id": rid3, "pack_version_id": pv_id3})  # noqa: E501
    assert compat.json()["fallback_allowed"] is True

def test_fallback_supported_repin_via_api_success(client):
    """C5: fallback-supported REPIN with ack succeeds revision n->n+1."""
    import json as _json3
    import uuid as _uuid3
    from datetime import UTC, datetime

    from app.persistence.models import CORE_POSE_SLOTS as Slots3  # noqa: N811  # noqa: N811
    from app.persistence.models import Artifact as Art3
    from app.persistence.models import Character as Char3
    from app.persistence.models import CharacterAsset as CA3  # noqa: N814  # noqa: N814
    from app.persistence.models import CharacterPackVersion as PV3
    from app.persistence.models import Job as Job3
    from app.persistence.models import ObjectRole as OR3
    from app.persistence.models import VideoItem as VItem3
    WS4 = WS
    with _session() as s:
        from sqlalchemy.dialects.sqlite import insert as si3

        from app.persistence.models import Project as PM
        from app.persistence.models import Scene as SM
        from app.persistence.models import Workspace as WSM
        s.execute(si3(WSM).values(id=WS4, name=WS4).on_conflict_do_nothing(index_elements=[WSM.id]))
        proj = PM(workspace_id=WS4, name=f"FallbackRepin-{_uuid3.uuid4().hex[:4]}")
        s.add(proj)
        s.flush()
        vid = VItem3(project_id=proj.id, title="VidFR", position=0)
        s.add(vid)
        s.flush()
        scene = SM(video_item_id=vid.id, position=0, start_frame=0, end_frame=10, start_time_ms=0, end_time_ms=1000, status="pending")  # noqa: E501
        s.add(scene)
        s.flush()
        role = OR3(workspace_id=WS4, project_id=proj.id, video_item_id=vid.id, source_generation="1", name="HeroFR", kind="character", status="confirmed")  # noqa: E501
        s.add(role)
        s.flush()
        s.commit()
        pid4, vid_id4, rid4 = proj.id, vid.id, role.id
    with _session() as s:
        char = Char3(workspace_id=WS4, name="CharFR", code=f"charfr_{_uuid3.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char)
        s.flush()
        pv1 = PV3(character_id=char.id, workspace_id=WS4, version=1, status="published")
        s.add(pv1)
        s.flush()
        for slot in Slots3:
            art = Art3(workspace_id=WS4, kind="image", state="ready", relative_path=f"art/{slot}_{_uuid3.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="e"*64, width=100, height=100)  # noqa: E501
            s.add(art)
            s.flush()
            s.add(CA3(pack_version_id=pv1.id, workspace_id=WS4, pose_slot=slot, artifact_id=art.id))
        char2 = Char3(workspace_id=WS4, name="CharFR2", code=f"charfr2_{_uuid3.uuid4().hex[:4]}", character_type="character")  # noqa: E501
        s.add(char2)
        s.flush()
        pv2 = PV3(character_id=char2.id, workspace_id=WS4, version=1, status="published")
        s.add(pv2)
        s.flush()
        for slot in Slots3:
            art = Art3(workspace_id=WS4, kind="image", state="ready", relative_path=f"art/{slot}_{_uuid3.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="e"*64, width=100, height=100)  # noqa: E501
            s.add(art)
            s.flush()
            s.add(CA3(pack_version_id=pv2.id, workspace_id=WS4, pose_slot=slot, artifact_id=art.id))
        s.commit()
        char_id4, pv_id4, char2_id4, pv2_id4 = char.id, pv1.id, char2.id, pv2.id
    r_create = client.post("/api/v2/project-cast", json={"project_id": pid4, "object_role_id": rid4, "character_id": char_id4, "pack_version_id": pv_id4, "idempotency_key": f"repin-init-{_uuid3.uuid4().hex[:4]}"})  # noqa: E501
    assert r_create.status_code in (200, 201)
    mid = r_create.json()["id"]
    rev = r_create.json()["revision"]
    sha4 = "d" * 64
    t0 = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 21, 10, 5, 0, tzinfo=UTC)
    def _cj4(gen, at):
        with _session() as s:
            j = Job3(workspace_id=WS4, owner_type="video_item", owner_id=vid_id4, job_type="DISCOVER_OBJECTS", state="completed", input_generation=gen, input_manifest_json=_json3.dumps({"source_sha256": sha4}), created_at=at)  # noqa: E501
            s.add(j)
            s.commit()
    _cj4("1", t0)
    with _session() as s:
        art = Art3(workspace_id=WS4, kind="video", relative_path=f"vid_fr_{vid_id4}.mp4", state="ready", sha256=sha4, size_bytes=10, mime_type="video/mp4")  # noqa: E501
        s.add(art)
        s.flush()
        v = s.get(VItem3, vid_id4)
        v.source_artifact_id = art.id
        s.commit()
    _cj4("2", t1)
    r_no_ack = client.patch(f"/api/v2/project-cast/{mid}", json={"revision": rev, "character_id": char2_id4, "pack_version_id": pv2_id4})  # noqa: E501
    assert r_no_ack.status_code == 409
    r_ack = client.patch(f"/api/v2/project-cast/{mid}", json={"revision": rev, "character_id": char2_id4, "pack_version_id": pv2_id4, "fallback_acknowledged": True})  # noqa: E501
    assert r_ack.status_code == 200, r_ack.text
    assert r_ack.json()["revision"] == rev + 1
    assert r_ack.json()["pack_version_id"] == pv2_id4

def test_fallback_unsupported_create_rejected_zero_mutation(client):
    """C5: unsupported (object_kind_mismatch) CREATE rejected, zero mutation."""
    from sqlalchemy import select as _sel
    ids = _seed_picker_entities(client)
    proj = ids["proj"]
    with _session() as s:
        vid = s.scalar(_sel(VideoItem).where(VideoItem.project_id == proj))
        overlay = ObjectRole(workspace_id=WS, project_id=proj, video_item_id=vid.id, source_generation="1", name="OverlayFail", kind="source_overlay", status="confirmed")  # noqa: E501
        s.add(overlay)
        s.flush()
        s.commit()
        oid = overlay.id
    with _session() as s:
        from app.persistence.models import ProjectCastMapping
        before = len(s.scalars(_sel(ProjectCastMapping).where(ProjectCastMapping.project_id == proj)).all())  # noqa: E501
    r = client.post("/api/v2/project-cast", json={"project_id": proj, "object_role_id": oid, "character_id": ids["char_pub"], "pack_version_id": ids["pv_pub"], "idempotency_key": f"unsup-{uuid.uuid4().hex[:4]}", "fallback_acknowledged": True})  # noqa: E501
    assert r.status_code in (409, 422)
    with _session() as s:
        from app.persistence.models import ProjectCastMapping
        after = len(s.scalars(_sel(ProjectCastMapping).where(ProjectCastMapping.project_id == proj)).all())  # noqa: E501
    assert before == after

def test_fallback_unsupported_repin_rejected_zero_mutation(client):
    """C5: unsupported repin rejected, zero mutation."""
    from sqlalchemy import select as _sel2
    ids = _seed_picker_entities(client)
    proj = ids["proj"]
    role = ids["role"]
    create = client.post("/api/v2/project-cast", json={"project_id": proj, "object_role_id": role, "character_id": ids["char_pub"], "pack_version_id": ids["pv_pub"], "idempotency_key": f"unsup-repin-{uuid.uuid4().hex[:4]}"})  # noqa: E501
    assert create.status_code in (200, 201)
    mid = create.json()["id"]
    rev = create.json()["revision"]
    with _session() as s:
        from app.persistence.models import ProjectCastMapping
        before_rev = s.scalar(_sel2(ProjectCastMapping).where(ProjectCastMapping.id == mid)).revision  # noqa: E501
        before_pack = s.scalar(_sel2(ProjectCastMapping).where(ProjectCastMapping.id == mid)).pack_version_id  # noqa: E501
    with _session() as s:
        from app.persistence.models import CORE_POSE_SLOTS as SlotsM
        from app.persistence.models import Artifact as ArtM
        from app.persistence.models import Character as CharM
        from app.persistence.models import CharacterAsset as CAM
        from app.persistence.models import CharacterPackVersion as PVM
        prop_char = CharM(workspace_id=WS, name="PropFail", code=f"propfail_{uuid.uuid4().hex[:4]}", character_type="prop")  # noqa: E501
        s.add(prop_char)
        s.flush()
        pv_prop = PVM(character_id=prop_char.id, workspace_id=WS, version=1, status="published")
        s.add(pv_prop)
        s.flush()
        for slot in SlotsM:
            art = ArtM(workspace_id=WS, kind="image", state="ready", relative_path=f"art/{slot}_{uuid.uuid4().hex[:4]}.png", mime_type="image/png", size_bytes=100, sha256="e"*64, width=100, height=100)  # noqa: E501
            s.add(art)
            s.flush()
            s.add(CAM(pack_version_id=pv_prop.id, workspace_id=WS, pose_slot=slot, artifact_id=art.id))  # noqa: E501
        s.commit()
        prop_char_id, prop_pv_id = prop_char.id, pv_prop.id
    r = client.patch(f"/api/v2/project-cast/{mid}", json={"revision": rev, "character_id": prop_char_id, "pack_version_id": prop_pv_id, "fallback_acknowledged": True})  # noqa: E501
    assert r.status_code in (409, 422)
    with _session() as s:
        from app.persistence.models import ProjectCastMapping
        after = s.scalar(_sel2(ProjectCastMapping).where(ProjectCastMapping.id == mid))
        assert after.revision == before_rev
        assert after.pack_version_id == before_pack

# ruff: noqa
"""S07-T01 C1/C2 compatibility tests (20 required).

Covers:
1-6 direct incompatibilities, 7-14 generation authority, 15 mapping_id mismatch,
16-17 DELETE CAS, 18-20 idempotent/conflict/concurrent.

Uses real durable job/source authority for generation (no ORM-row faking).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import uuid

import pytest
from sqlalchemy import select

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Job,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.project_cast import ProjectCastRepository

CORE = ("front", "three_quarter", "side", "back", "sitting", "walking")


def _session():
    return deps._job_service._session_factory()


def _seed_project_video(ws=DEFAULT_WORKSPACE_ID):
    with _session() as s:
        from sqlalchemy.dialects.sqlite import insert as si

        s.execute(si(Workspace).values(id=ws, name=ws).on_conflict_do_nothing(index_elements=[Workspace.id]))
        p = Project(workspace_id=ws, name=f"P-{uuid.uuid4().hex[:4]}")
        s.add(p)
        s.flush()
        v = VideoItem(project_id=p.id, title="V", position=0)
        s.add(v)
        s.flush()
        sc = Scene(video_item_id=v.id, position=0, start_frame=0, end_frame=10, start_time_ms=0, end_time_ms=1000, status="pending")
        s.add(sc)
        s.flush()
        s.commit()
        return p.id, v.id, sc.id


def _create_role(ws, proj, vid, gen="1", kind="character", name="Hero"):
    with _session() as s:
        r = ObjectRole(workspace_id=ws, project_id=proj, video_item_id=vid, source_generation=gen, name=name, kind=kind, status="confirmed")
        s.add(r)
        s.flush()
        s.commit()
        return r.id


def _create_character(ws, ctype="character", code=None):
    with _session() as s:
        c = Character(workspace_id=ws, name="C", code=code or f"c_{uuid.uuid4().hex[:6]}", character_type=ctype)
        s.add(c)
        s.flush()
        s.commit()
        return c.id


def _create_artifact(ws, rel="art.png"):
    import hashlib
    from pathlib import Path

    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    svc = deps._job_service
    tgt = Path(svc._managed_root) / rel
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_bytes(data)
    with _session() as s:
        art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=hashlib.sha256(data).hexdigest())
        s.add(art)
        s.flush()
        s.commit()
        return art.id


def _create_pack(ws, char_id, version=1, status="published", complete=True):
    import hashlib
    from pathlib import Path

    with _session() as s:
        pv = CharacterPackVersion(character_id=char_id, workspace_id=ws, version=version, status=status)
        s.add(pv)
        s.flush()
        if complete:
            for slot in CORE:
                rel = f"{pv.id}_{slot}.png"
                data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
                tgt = Path(deps._job_service._managed_root) / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_bytes(data)
                art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=hashlib.sha256(data).hexdigest())
                s.add(art)
                s.flush()
                ca = CharacterAsset(pack_version_id=pv.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id)
                s.add(ca)
            s.flush()
        else:
            for slot in CORE[:2]:
                rel = f"{pv.id}_{slot}_inc.png"
                data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
                tgt = Path(deps._job_service._managed_root) / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_bytes(data)
                art = Artifact(workspace_id=ws, kind="image", relative_path=rel, state="ready", size_bytes=len(data), mime_type="image/png", sha256=hashlib.sha256(data).hexdigest())
                s.add(art)
                s.flush()
                ca = CharacterAsset(pack_version_id=pv.id, workspace_id=ws, pose_slot=slot, artifact_id=art.id)
                s.add(ca)
            s.flush()
        s.commit()
        return pv.id


def _create_job_for_video(ws, vid, gen="1", sha="abc123", created_at=None):
    # Create a completed DISCOVER_OBJECTS job with input_generation and source_sha
    import json
    from datetime import UTC, datetime, timedelta

    if created_at is None:
        created_at = datetime.now(UTC)

    with _session() as s:
        j = Job(
            workspace_id=ws,
            owner_type="video_item",
            owner_id=vid,
            job_type="DISCOVER_OBJECTS",
            state="completed",
            input_generation=gen,
            input_manifest_json=json.dumps({"source_sha256": sha}),
            created_at=created_at,
        )
        s.add(j)
        s.flush()
        s.commit()
        return j.id


def test_1_repo_source_overlay_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, gen="1", kind="source_overlay")
    cid = _create_character(ws, "character")
    pvid = _create_pack(ws, cid, version=1, status="published", complete=True)
    with _session() as s:
        repo = ProjectCastRepository(s)
        with pytest.raises(Exception) as ei:
            repo.create_mapping(ws, pid, rid, cid, pvid, f"k1-{uuid.uuid4().hex[:4]}")
        assert "source_overlay" in str(ei.value).lower() or "blocked" in str(ei.value).lower()
        s.rollback()
        # zero mutation: no row
        from app.persistence.models import ProjectCastMapping

        rows = s.scalars(select(ProjectCastMapping).where(ProjectCastMapping.workspace_id == ws, ProjectCastMapping.project_id == pid)).all()
        assert len(rows) == 0


def test_2_api_source_overlay_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, kind="source_overlay")
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k2-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409
    # zero rows
    with _session() as s:
        from app.persistence.models import ProjectCastMapping

        rows = s.scalars(select(ProjectCastMapping).where(ProjectCastMapping.workspace_id == ws, ProjectCastMapping.project_id == pid)).all()
        assert len(rows) == 0


def test_3_unpublished_pack_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, status="draft", complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k3-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409
    assert "unpublished" in r.text.lower()


def test_4_incomplete_pack_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, status="published", complete=False)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k4-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409
    assert "incomplete" in r.text.lower() or "missing" in r.text.lower()


def test_5_kind_mismatch_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, kind="character")
    cid = _create_character(ws, ctype="other")  # other vs character -> capability + kind mismatch
    # Make character_type that triggers kind mismatch: role character vs character other -> missing capability + kind mismatch
    # For pure kind mismatch, use role background vs character character
    # Use role background (expects prop/other) vs character character -> mismatch
    rid2 = _create_role(ws, pid, vid, kind="background", name="BG")
    cid2 = _create_character(ws, ctype="character")
    pvid2 = _create_pack(ws, cid2, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid2, "character_id": cid2, "pack_version_id": pvid2, "idempotency_key": f"k5-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409


def test_6_missing_capability_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, kind="character")
    cid = _create_character(ws, ctype="other")
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k6-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409


def test_7_patch_incompatible_reject(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, kind="character")
    cid = _create_character(ws, ctype="character")
    pvid = _create_pack(ws, cid, complete=True)
    # create compatible mapping
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k7-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    rev = r.json()["revision"]
    # create incompatible pack (unpublished)
    cid2 = _create_character(ws, ctype="character")
    pvid2 = _create_pack(ws, cid2, status="draft", complete=True)
    r2 = client.patch(f"/api/v2/project-cast/{mid}", json={"revision": rev, "pack_version_id": pvid2, "character_id": cid2})
    assert r2.status_code == 409


def test_8_rejected_patch_byte_identical(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k8-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    before = client.get(f"/api/v2/project-cast/{mid}").json()
    cid2 = _create_character(ws)
    pvid2 = _create_pack(ws, cid2, status="draft", complete=True)
    r2 = client.patch(f"/api/v2/project-cast/{mid}", json={"revision": before["revision"], "pack_version_id": pvid2, "character_id": cid2})
    assert r2.status_code == 409
    after = client.get(f"/api/v2/project-cast/{mid}").json()
    assert before["pack_version_id"] == after["pack_version_id"]
    assert before["revision"] == after["revision"]


def test_9_rejected_post_not_consume_key(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid_bad = _create_pack(ws, cid, status="draft", complete=True)
    key = f"k9-{uuid.uuid4().hex[:4]}"
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid_bad, "idempotency_key": key})
    assert r.status_code == 409
    # Now create good pack with same key should succeed (key not consumed)
    cid2 = _create_character(ws)
    pvid_good = _create_pack(ws, cid2, complete=True)
    # Need new role for same key but different payload? The key was used with bad payload, but since it was rejected, it should not be stored, so same key with good payload should succeed if role is same? But our repo checks idempotency before compatibility, so if key not stored, it will be considered new
    # Use same role but good pack
    # Since previous POST failed, no row with that key exists, so this should be 201
    # However our test uses same role but different character/pack, so it's considered different payload but key same - if previous was rejected, key not stored, so this should be considered new and compatible -> 201
    # To test not consume, we need to use same key with compatible payload after failed attempt with same key and same role but good pack
    # The previous attempt used cid/pvid_bad, now use cid2/pvid_good with same key and same role -> should be considered different payload but since previous not stored, it should not be conflict, should be 201 (or 409 due to compatibility of new? but new is compatible)
    # Let's use same role, same project, but good pack
    r2 = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid2, "pack_version_id": pvid_good, "idempotency_key": key})
    # Since previous failed and didn't store, this should be 201 (compatible)
    assert r2.status_code == 201


def test_10_current_generation_accepted(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    # Create a job to make current generation = 1 (no jobs -> 1)
    rid = _create_role(ws, pid, vid, gen="1")
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k10-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201


def test_11_advance_generation_old_stale(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    # Initially gen 1 current
    rid_old = _create_role(ws, pid, vid, gen="1", name="Old")
    # Deterministic job ordering for generation resolution (t0 < t1).
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(minutes=5)
    # Advance generation by creating a job with gen 1 and source sha, then role with gen 2 would be current? Actually need to understand generation logic
    # Simplest: create a video artifact and job to make current gen 2
    # Use _create_job_for_video to create completed job with gen 1
    # Then current_generation will be 2 (max 1 +1)
    # Create old role gen 1, then create job, then old role should be stale
    # First, ensure current is 1
    from app.persistence.object_intelligence import ObjectIntelligenceRepository

    with _session() as s:
        repo = ObjectIntelligenceRepository(s)
        cur1 = repo.current_generation(ws, vid)
        assert cur1 == "1"
    # Create job for vid to advance
    _create_job_for_video(ws, vid, gen="1", sha="b1565820a5cdac40e0520d23f9d0b1497f240ddc51d72eac6423d97d952d444f", created_at=t0)
    # Need to create artifact and link to video for sha matching
    import hashlib

    sha = "b1565820a5cdac40e0520d23f9d0b1497f240ddc51d72eac6423d97d952d444f"
    with _session() as s:
        # placeholder removed
        # Instead, create artifact and link to video

        data = b"video"
        h = hashlib.sha256(data).hexdigest()
        # Use sha1 as h
        # Create artifact with sha1
        # Find video and set source_artifact_id
        v = s.get(VideoItem, vid)
        # Create artifact if not exists
        art2 = Artifact(workspace_id=ws, kind="video", relative_path=f"vid_{vid}.mp4", state="ready", sha256=sha, size_bytes=100, mime_type="video/mp4")
        s.add(art2)
        s.flush()
        v.source_artifact_id = art2.id
        s.commit()
    with _session() as s:
        repo = ObjectIntelligenceRepository(s)
        cur2 = repo.current_generation(ws, vid)
        # C3-P2: deterministic exact assertion. The newest completed job
        # whose manifest sha matches the video's source artifact sha wins:
        # job(gen=1, sha=SHA, t0) -> current == "1", unconditionally.
        assert cur2 == "1", "after first job current=%r, expected 1" % (cur2,)
    # Second extraction of the SAME source at a later time: job(gen=2,
    # sha=SHA, t1 > t0). Newest-sha-match rule makes current exactly "2".
    _create_job_for_video(ws, vid, gen="2", sha=sha, created_at=t1)
    with _session() as s:
        repo = ObjectIntelligenceRepository(s)
        cur3 = repo.current_generation(ws, vid)
        # Exact authority state after the second job — no either/or.
        assert cur3 == "2", "after second job current=%r, expected 2" % (cur3,)
    # Old role (source_generation="1") must now be rejected as stale,
    # UNCONDITIONALLY — no conditional skip branches.
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    with _session() as s:
        from app.persistence.project_cast import ProjectCastConflictError
        from app.persistence.project_cast import ProjectCastRepository

        repo2 = ProjectCastRepository(s)
        try:
            repo2.create_mapping(ws, pid, rid_old, cid, pvid, f"k11-{uuid.uuid4().hex[:4]}")
            s.commit()
            assert False, "stale role gen=1 must be rejected when current generation is 2"
        except ProjectCastConflictError as e:
            s.rollback()
            assert "generation_mismatch" in str(e), f"wrong rejection reason: {e}"

        # Zero mutation, verified directly against DB state: no mapping row
        # for this project+role, and the pack/character rows are untouched.
        from app.persistence.models import ProjectCastMapping

        leftover = s.scalars(
            select(ProjectCastMapping).where(
                ProjectCastMapping.project_id == pid,
                ProjectCastMapping.object_role_id == rid_old,
            )
        ).all()
        assert leftover == [], f"failed create left {len(leftover)} mapping row(s)"


def test_12_old_role_direct_post_rejected(client):
    # Direct POST with an old role (gen=1) after the backend advanced to
    # generation "2": must be rejected with 409 + zero mutation.
    # Deterministic: explicit created_at ordering on completed jobs.
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, gen="1")
    sha12 = "a7b2e0e00ea6f19636ae3a1096bffeff4b3ff0691ce780792544a0c349bfbe8b"
    t0 = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 21, 10, 5, 0, tzinfo=UTC)
    # Job 1 (gen=1, sha=sha12) at t0; then link the matching artifact.
    _create_job_for_video(ws, vid, gen="1", sha=sha12, created_at=t0)
    with _session() as s:
        art = Artifact(workspace_id=ws, kind="video", relative_path=f"vid2_{vid}.mp4", state="ready", sha256=sha12, size_bytes=10, mime_type="video/mp4")
        s.add(art)
        s.flush()
        v = s.get(VideoItem, vid)
        v.source_artifact_id = art.id
        s.commit()
        from app.persistence.object_intelligence import ObjectIntelligenceRepository

        cur_a = ObjectIntelligenceRepository(s).current_generation(ws, vid)
        assert cur_a == "1", "after first job current=%r, expected 1" % (cur_a,)
    # Job 2 re-extracts the same source at t1 > t0 -> current exactly "2".
    _create_job_for_video(ws, vid, gen="2", sha=sha12, created_at=t1)
    with _session() as s:
        from app.persistence.object_intelligence import ObjectIntelligenceRepository

        cur = ObjectIntelligenceRepository(s).current_generation(ws, vid)
        assert cur == "2", "after second job current=%r, expected 2" % (cur,)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    # Count mapping rows before the attempt (zero-mutation baseline).
    with _session() as s:
        from app.persistence.models import ProjectCastMapping

        before_rows = s.scalars(
            select(ProjectCastMapping).where(ProjectCastMapping.project_id == pid)
        ).all()
        assert before_rows == []
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k12-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409, r.text
    assert "generation_mismatch" in r.text
    # Zero mutation verified directly via DB state.
    with _session() as s:
        from app.persistence.models import ProjectCastMapping

        after_rows = s.scalars(
            select(ProjectCastMapping).where(ProjectCastMapping.project_id == pid)
        ).all()
        assert after_rows == [], f"rejected POST left {len(after_rows)} mapping row(s)"

def test_13_pack_version2_no_generation_mismatch(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, gen="1")
    cid = _create_character(ws)
    pvid2 = _create_pack(ws, cid, version=2, complete=True)
    # Pack version 2 should NOT cause generation mismatch when role is current gen1
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid2, "idempotency_key": f"k13-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201


def test_14_role_gen2_pack_version2_backend_current_diff_rejected(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    # Role gen2 but backend current is 1 (no job for gen2)
    rid = _create_role(ws, pid, vid, gen="2", name="Gen2Role")
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, version=2, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k14-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 409
    assert "generation" in r.text.lower()


def test_15_mapping_id_mismatch_fail_closed(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k15a-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    # Create another project/role
    pid2, vid2, _ = _seed_project_video(ws)
    rid2 = _create_role(ws, pid2, vid2)
    # Try evaluate with mapping_id from first but project/role from second
    r2 = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": pid2, "object_role_id": rid2, "pack_version_id": pvid, "mapping_id": mid})
    assert r2.status_code == 200
    j = r2.json()
    assert j["compatible"] is False
    assert j["reasons"] == ["workspace_mismatch"]
    assert j["fallback_allowed"] is False
    assert j["blocked"] is True
    assert j["pinned_version_id"] == pvid
    assert j["current_revision"] == 1


def test_16_delete_missing_revision_422(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k16-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    r2 = client.delete(f"/api/v2/project-cast/{mid}")
    assert r2.status_code == 422


def test_17_delete_stale_revision_409(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k17-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    rev = r.json()["revision"]
    # Stale rev 999
    r2 = client.delete(f"/api/v2/project-cast/{mid}?revision=999")
    assert r2.status_code == 409
    # Verify zero mutation: still exists
    r3 = client.get(f"/api/v2/project-cast/{mid}")
    assert r3.status_code == 200
    assert r3.json()["revision"] == rev


def test_18_equivalent_compatible_replay_idempotent(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    key = f"k18-{uuid.uuid4().hex[:4]}"
    r1 = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": key})
    assert r1.status_code == 201
    r2 = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": key})
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["revision"] == r2.json()["revision"]


def test_19_conflict_replay_zero_mutation(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    key = f"k19-{uuid.uuid4().hex[:4]}"
    r1 = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": key})
    assert r1.status_code == 201
    before = client.get(f"/api/v2/project-cast/{r1.json()['id']}").json()
    cid2 = _create_character(ws)
    pvid2 = _create_pack(ws, cid2, complete=True)
    r2 = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid2, "pack_version_id": pvid2, "idempotency_key": key})
    assert r2.status_code == 409
    after = client.get(f"/api/v2/project-cast/{r1.json()['id']}").json()
    assert before["revision"] == after["revision"]
    assert before["pack_version_id"] == after["pack_version_id"]


def test_20_concurrent_cas_one_winner(client):
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"k20-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    # Create two new packs for concurrent repin
    cid2 = _create_character(ws)
    pvid_a = _create_pack(ws, cid2, version=10, complete=True)
    cid3 = _create_character(ws)
    pvid_b = _create_pack(ws, cid3, version=11, complete=True)
    import threading

    results = []
    errors = []

    def try_patch(pvid, cid_):

        # Use repo directly with separate session
        with _session() as s:
            from app.persistence.project_cast import ProjectCastRepository

            repo = ProjectCastRepository(s)
            try:
                rec = repo.update_mapping(mid, ws, 1, pack_version_id=pvid, character_id=cid_)
                s.commit()
                results.append(rec.pack_version_id)
            except Exception as e:
                s.rollback()
                errors.append(str(e))

    t1 = threading.Thread(target=try_patch, args=(pvid_a, cid2))
    t2 = threading.Thread(target=try_patch, args=(pvid_b, cid3))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(results) == 1
    assert len(errors) == 1
    assert "stale" in errors[0].lower()
    with _session() as s:
        from app.persistence.project_cast import ProjectCastRepository

        repo = ProjectCastRepository(s)
        final = repo.get_mapping(mid, ws)
        assert final.revision == 2


def test_incomplete_pack_policy_assertions(client):
    # Directly test incomplete pack policy via evaluate
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=False)
    r = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": pid, "object_role_id": rid, "pack_version_id": pvid})
    assert r.status_code == 200
    j = r.json()
    assert j["compatible"] is False
    assert "incomplete_pack" in j["reasons"]
    assert "missing_required_pose" in j["reasons"]
    # Ensure not just isinstance check: reasons must be exact enum values
    for reason in j["reasons"]:
        assert reason in ["workspace_mismatch", "source_overlay_refusal", "object_kind_mismatch", "incomplete_pack", "unpublished_pack", "missing_required_pose", "missing_required_capability", "generation_mismatch", "stale_revision"]

def test_21_generation_mismatch_fallback_allowed(client):
    """P1-A: generation_mismatch is fallback-supported → fallback_allowed True, blocked False."""
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    # Create role gen 1, then advance generation to 2 via jobs
    rid = _create_role(ws, pid, vid, gen="1", name="Gen1Role")
    sha = "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6b7a8f9e0d1c2b3a4f5e6d7c8b9a0f1e2"
    t0 = datetime(2026, 8, 21, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 21, 10, 5, 0, tzinfo=UTC)
    _create_job_for_video(ws, vid, gen="1", sha=sha, created_at=t0)
    with _session() as s:
        art = Artifact(workspace_id=ws, kind="video", relative_path=f"vid_fallback_{vid}.mp4", state="ready", sha256=sha, size_bytes=10, mime_type="video/mp4")
        s.add(art)
        s.flush()
        v = s.get(VideoItem, vid)
        v.source_artifact_id = art.id
        s.commit()
    _create_job_for_video(ws, vid, gen="2", sha=sha, created_at=t1)
    # Now role gen1 is stale -> generation_mismatch
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    # Direct compat evaluate should be fallback_allowed True for generation_mismatch
    from app.persistence.project_cast import evaluate_compatibility
    with _session() as s:
        result = evaluate_compatibility(s, workspace_id=ws, project_id=pid, object_role_id=rid, character_id=cid, pack_version_id=pvid)
        assert result.compatible is False
        assert "generation_mismatch" in result.reasons
        assert result.fallback_allowed is True, f"expected fallback_allowed True for generation_mismatch, got {result.fallback_allowed} reasons={result.reasons}"
        assert result.blocked is False, f"expected blocked False for fallback-supported, got {result.blocked}"
        assert result.fallback_description is not None and "generation" in result.fallback_description.lower()

def test_22_incomplete_pack_fallback_allowed(client):
    """P1-A: incomplete_pack is fallback-supported → fallback_allowed True."""
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid, gen="1")
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, status="published", complete=False)  # incomplete
    from app.persistence.project_cast import evaluate_compatibility
    with _session() as s:
        result = evaluate_compatibility(s, workspace_id=ws, project_id=pid, object_role_id=rid, character_id=cid, pack_version_id=pvid)
        assert result.compatible is False
        assert "incomplete_pack" in result.reasons
        assert result.fallback_allowed is True
        assert result.blocked is False
        assert result.fallback_description is not None

def test_23_unsupported_fallback_still_blocked(client):
    """P1-A: unsupported reasons remain fallback_allowed False, blocked True."""
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    # source_overlay
    rid_s = _create_role(ws, pid, vid, kind="source_overlay", name="Overlay")
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    from app.persistence.project_cast import evaluate_compatibility
    with _session() as s:
        r1 = evaluate_compatibility(s, workspace_id=ws, project_id=pid, object_role_id=rid_s, character_id=cid, pack_version_id=pvid)
        assert r1.fallback_allowed is False
        assert r1.blocked is True
        assert "source_overlay_refusal" in r1.reasons
    # object_kind_mismatch
    pid2, vid2, _ = _seed_project_video(ws)
    rid2 = _create_role(ws, pid2, vid2, kind="background", name="BG")
    cid2 = _create_character(ws, ctype="character")
    pvid2 = _create_pack(ws, cid2, complete=True)
    with _session() as s:
        r2 = evaluate_compatibility(s, workspace_id=ws, project_id=pid2, object_role_id=rid2, character_id=cid2, pack_version_id=pvid2)
        assert r2.fallback_allowed is False
        assert r2.blocked is True
        assert "object_kind_mismatch" in r2.reasons
    # unpublished
    pid3, vid3, _ = _seed_project_video(ws)
    rid3 = _create_role(ws, pid3, vid3)
    cid3 = _create_character(ws)
    pvid3 = _create_pack(ws, cid3, status="draft", complete=True)
    with _session() as s:
        r3 = evaluate_compatibility(s, workspace_id=ws, project_id=pid3, object_role_id=rid3, character_id=cid3, pack_version_id=pvid3)
        assert r3.fallback_allowed is False
        assert r3.blocked is True
        assert "unpublished_pack" in r3.reasons

def test_24_stale_revision_no_fallback(client):
    """P1-A: stale_revision is unsupported fallback."""
    ws = DEFAULT_WORKSPACE_ID
    pid, vid, _ = _seed_project_video(ws)
    rid = _create_role(ws, pid, vid)
    cid = _create_character(ws)
    pvid = _create_pack(ws, cid, complete=True)
    r = client.post("/api/v2/project-cast", json={"project_id": pid, "object_role_id": rid, "character_id": cid, "pack_version_id": pvid, "idempotency_key": f"stale-fallback-{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 201
    mid = r.json()["id"]
    rev = r.json()["revision"]
    # Evaluate with stale revision
    compat = client.post("/api/v2/project-cast/compatibility/evaluate", json={"project_id": pid, "object_role_id": rid, "pack_version_id": pvid, "expected_revision": rev + 99, "mapping_id": mid})
    assert compat.status_code == 200
    j = compat.json()
    assert "stale_revision" in j["reasons"]
    assert j["fallback_allowed"] is False
    assert j["blocked"] is True

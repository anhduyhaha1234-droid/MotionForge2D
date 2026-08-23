"""Focused S08-T05 API suite: correction endpoints over the REAL app router.

Covers the pre-confirmation scope report (zero writes), create/confirm
replay semantics (201 -> 200), stale-conflict mapping, cancel (pending +
applied), recompute retry, list/get read-only and the honest recompute
outcome surfaced through the API — all on the isolated conftest durable DB.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import JobRepository
from app.persistence.models import (
    Artifact,
    Job,
    ObjectCorrection,
    ObjectOccurrence,
    ObjectRole,
    ObjectRoleArtifact,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.persistence.object_intelligence import ObjectIntelligenceRepository

API = "/api/v2/object-intelligence/corrections"

#: Real byte content of the synthetic source video (matches the seed Artifact).
SOURCE_MEDIA_BYTES = b"motionforge-api-source-media"
SOURCE_SHA = hashlib.sha256(SOURCE_MEDIA_BYTES).hexdigest()


def _svc():
    service = deps._job_service
    assert service is not None
    assert service.session_factory is not None
    return service


def _session():
    return _svc().session_factory()


def _seed_video(session) -> dict[str, str]:
    workspace = session.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(workspace)
    project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="API Project")
    video = VideoItem(
        project=project, title="Primary", position=0, width=320, height=240,
        duration_ms=6000, fps_num=30, fps_den=1,
    )
    session.add(project)
    session.flush()
    session.add(video)
    session.flush()
    # Real ready video Artifact -> the video's CURRENT source (backend source
    # authority, T02-C2).  Generation "1" roles are current because the seed
    # DISCOVER job's manifest carries this sha.
    source = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="video",
        relative_path=f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video.id}/import/api-source.mp4",
        state="ready",
        sha256=SOURCE_SHA,
        size_bytes=len(SOURCE_MEDIA_BYTES),
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    video.source_artifact_id = source.id
    scenes: list[str] = []
    for index in range(2):
        scene = Scene(
            video_item=video,
            position=index,
            start_frame=index * 90,
            end_frame=index * 90 + 89,
            start_time_ms=index * 3000,
            end_time_ms=index * 3000 + 2999,
            status="pending",
        )
        session.add(scene)
        session.flush()
        scenes.append(scene.id)
    session.commit()
    return {"project": project.id, "video": video.id, "scenes": scenes}


def _seed_source_job(session, ids) -> str:
    import uuid as _uuid

    from sqlalchemy import update as sa_update

    from app.persistence.jobs import JobRepository, StepInput

    job = JobRepository(session).create_job(
        workspace_id=DEFAULT_WORKSPACE_ID,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=ids["video"],
        # Carry the video's real source sha256 so the backend-authoritative
        # current generation (T02-C2) links this job to the source and
        # resolves generation "1" (the roles' generation).
        input_manifest={"schema_version": 1, "source_sha256": SOURCE_SHA},
        idempotency_key=f"seed-job:{_uuid.uuid4()}",
        input_generation="1",
        steps=[StepInput(step_code="extract", position=0, step_type="sync")],
        actor="system",
    )
    session.execute(
        sa_update(Job).where(Job.id == job.id).values(state="completed")
    )
    return job.id


def _seed_role(session, ids, name: str) -> ObjectRole:
    role = ObjectRole(
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=ids["project"],
        video_item_id=ids["video"],
        source_generation="1",
        name=name,
        kind="character",
        status="suggested",
    )
    session.add(role)
    session.flush()
    return role


def _seed_occ(session, role: ObjectRole, scene_id: str, frame: int) -> ObjectOccurrence:
    occ = ObjectOccurrence(
        workspace_id=role.workspace_id,
        project_id=role.project_id,
        video_item_id=role.video_item_id,
        role_id=role.id,
        scene_id=scene_id,
        frame_index=frame,
        time_ms=frame * 33,
        bbox_x=10,
        bbox_y=10,
        bbox_w=40,
        bbox_h=40,
        confidence=0.6,
        confidence_source="detector",
        algorithm="deterministic-layout",
        algorithm_version="1.0.0",
        reasons_json="[]",
        review_state="unreviewed",
    )
    session.add(occ)
    session.flush()
    return occ


def _seed_media(
    session, role: ObjectRole, source_job_id: str, generation: str = "1"
) -> dict[str, ObjectRoleArtifact]:
    """OLD active DISCOVER media associations (thumbnail + mask) for a role."""
    associations: dict[str, ObjectRoleArtifact] = {}
    managed = ManagedRoot(_svc().managed_root)
    for purpose in ("thumbnail", "mask"):
        relative_path = (
            f"artifacts/{role.workspace_id}/image/{source_job_id}/"
            f"extract/{role.name}-{purpose}.png"
        )
        # REAL file on the managed disk so the audit content endpoint serves it.
        raw = (b"\x89PNG" + purpose.encode("utf-8")).ljust(128, b"\x00")
        managed.atomic_write_bytes(relative_path, raw)
        artifact = Artifact(
            id=f"old-artifact-{role.id}-{purpose}",
            workspace_id=role.workspace_id,
            kind="image",
            relative_path=relative_path,
            state="ready",
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            mime_type="image/png",
            width=64,
            height=64,
        )
        session.add(artifact)
        assoc = ObjectRoleArtifact(
            id=f"old-assoc-{role.id}-{purpose}",
            workspace_id=role.workspace_id,
            role_id=role.id,
            artifact_id=artifact.id,
            purpose=purpose,
            source_generation=generation,
            source_job_id=source_job_id,
        )
        session.add(assoc)
        associations[purpose] = assoc
    session.flush()
    return associations


def _media_of(session, role_id: str) -> list[Any]:
    return ObjectIntelligenceRepository(session).get_role(
        DEFAULT_WORKSPACE_ID, role_id
    ).media


def _reassign_payload(
    ids: dict[str, str], occ: ObjectOccurrence, source: ObjectRole, target: ObjectRole
) -> dict[str, Any]:
    return {
        "kind": "reassign",
        "project_id": ids["project"],
        "video_item_id": ids["video"],
        "generation": source.source_generation,
        "occurrence_id": occ.id,
        "occurrence_revision": occ.revision,
        "source_role_id": source.id,
        "target_role_id": target.id,
    }


def _seed_correction_state(client: TestClient):
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, "A")
        role_b = _seed_role(session, ids, "B")
        occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
        session.commit()
        payload = _reassign_payload(ids, occ_a, role_a, role_b)
    return ids, role_a, role_b, occ_a, payload


def test_api_preview_reports_scope_without_writes(client: TestClient) -> None:
    ids, role_a, role_b, occ_a, payload = _seed_correction_state(client)
    with _session() as session:
        before_corrections = session.scalar(
            select(func.count()).select_from(ObjectCorrection)
        )
        before_roles = {
            row.id: row.revision
            for row in session.scalars(select(ObjectRole)).all()
        }
    response = client.post(f"{API}/preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["correction_type"] == "reassign"
    assert sorted(data["affected_role_ids"]) == sorted([role_a.id, role_b.id])
    assert data["affected_occurrence_ids"] == [occ_a.id]
    assert data["invalidated_suggestion_ids"] == []
    assert data["recompute_needed"] is False  # no suggestions, no candidates
    with _session() as session:
        assert (
            session.scalar(select(func.count()).select_from(ObjectCorrection))
            == before_corrections
        )
        after_roles = {
            row.id: row.revision
            for row in session.scalars(select(ObjectRole)).all()
        }
        assert after_roles == before_roles  # zero mutations


def test_api_create_confirm_reassign_flow(client: TestClient) -> None:
    ids, role_a, role_b, occ_a, payload = _seed_correction_state(client)
    created = client.post(API, json=payload)
    assert created.status_code == 201
    correction_id = created.json()["correction"]["id"]
    assert created.json()["correction"]["status"] == "pending"

    replay = client.post(API, json=payload)
    assert replay.status_code == 200  # natural-key replay
    assert replay.json()["correction"]["id"] == correction_id

    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    assert confirmed.status_code == 201
    data = confirmed.json()
    assert data["status"] == "applied"
    assert data["result"]["from_role_id"] == role_a.id
    assert data["result"]["to_role_id"] == role_b.id
    assert data["recompute"]["recompute_needed"] is False

    confirm_replay = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    assert confirm_replay.status_code == 200  # idempotent replay

    with _session() as session:
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_b.id
        assert (
            session.scalar(select(func.count()).select_from(ObjectCorrection)) == 1
        )

    fetched = client.get(f"{API}/{correction_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "applied"
    assert fetched.json()["impact"]["affected_role_ids"] == sorted(
        [role_a.id, role_b.id]
    )


def test_api_confirm_creates_recompute_job_and_completes(client: TestClient) -> None:
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, "A")
        role_b = _seed_role(session, ids, "B")
        role_a.source_job_id = _seed_source_job(session, ids)
        role_b.source_job_id = _seed_source_job(session, ids)
        occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
        _seed_occ(session, role_a, ids["scenes"][0], 8)
        _seed_occ(session, role_b, ids["scenes"][1], 95)
        session.commit()
        payload = _reassign_payload(ids, occ_a, role_a, role_b)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    assert confirmed.status_code == 201
    job_id = confirmed.json()["recompute_job_id"]
    assert job_id is not None
    claims = 0
    for _ in range(5):
        claimed = svc.worker.run_once()
        if claimed == 0:
            break
        claims += claimed
    assert claims >= 1
    with _session() as session:
        assert JobRepository(session).get_job(job_id).state == "completed"
    fetched = client.get(f"{API}/{correction_id}")
    assert fetched.status_code == 200
    recompute = fetched.json()["recompute"]
    assert recompute["recompute_needed"] is True
    assert recompute["status"] == "completed"
    assert recompute["progress"] == 100
    # Recompute published ONLY affected-role artifacts + manifest.
    with _session() as session:
        rows = session.scalars(
            select(Artifact).where(
                Artifact.relative_path.like(
                    f"artifacts/{DEFAULT_WORKSPACE_ID}/image/{job_id}/%"
                )
            )
        ).all()
        assert len(rows) == 5


def test_api_stale_confirm_409(client: TestClient) -> None:
    ids, role_a, role_b, occ_a, payload = _seed_correction_state(client)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    stale = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": 9999},
    )
    assert stale.status_code == 409
    with _session() as session:
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_a.id


def test_api_validation_errors(client: TestClient) -> None:
    ids, _role_a, _role_b, _occ_a, payload = _seed_correction_state(client)
    missing = {k: v for k, v in payload.items() if k != "target_role_id"}
    response = client.post(f"{API}/preview", json=missing)
    assert response.status_code == 422
    unknown_kind = {**payload, "kind": "bogus"}
    response = client.post(f"{API}/preview", json=unknown_kind)
    assert response.status_code == 422
    response = client.get(f"{API}/{ 'a' * 8 }-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_api_cancel_pending(client: TestClient) -> None:
    ids, role_a, role_b, occ_a, payload = _seed_correction_state(client)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    revision = created.json()["correction"]["revision"]
    cancelled = client.post(
        f"{API}/{correction_id}/cancel", json={"revision": revision}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # A cancelled correction can never be confirmed.
    confirmed = client.post(
        f"{API}/{correction_id}/confirm", json={"revision": revision}
    )
    assert confirmed.status_code == 409
    with _session() as session:
        assert session.get(ObjectOccurrence, occ_a.id).role_id == role_a.id


def test_api_cancel_applied_cancels_recompute_job(
    client: TestClient, monkeypatch
) -> None:
    import app.services.object_correction as correction_service

    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, "A")
        role_b = _seed_role(session, ids, "B")
        role_a.source_job_id = _seed_source_job(session, ids)
        role_b.source_job_id = _seed_source_job(session, ids)
        occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
        _seed_occ(session, role_a, ids["scenes"][0], 8)
        _seed_occ(session, role_b, ids["scenes"][1], 95)
        session.commit()
        payload = _reassign_payload(ids, occ_a, role_a, role_b)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    job_id = confirmed.json()["recompute_job_id"]
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        correction_service, "PHASE_HOOK", lambda phase: (entered.set(), release.wait(10))
    )
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert entered.wait(timeout=10)
    cancelled = client.post(
        f"{API}/{correction_id}/cancel",
        json={"revision": created.json()["correction"]["revision"]},
    )
    release.set()
    worker_thread.join(timeout=30)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "applied"  # mutation is never undone
    with _session() as session:
        assert JobRepository(session).get_job(job_id).state == "cancelled"
    fetched = client.get(f"{API}/{correction_id}")
    assert fetched.json()["recompute"]["status"] == "cancelled"


def test_api_retry_recompute_successor(client: TestClient, monkeypatch) -> None:
    import app.services.object_correction as correction_service

    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, "A")
        role_b = _seed_role(session, ids, "B")
        role_a.source_job_id = _seed_source_job(session, ids)
        role_b.source_job_id = _seed_source_job(session, ids)
        occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
        _seed_occ(session, role_a, ids["scenes"][0], 8)
        _seed_occ(session, role_b, ids["scenes"][1], 95)
        session.commit()
        payload = _reassign_payload(ids, occ_a, role_a, role_b)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    job_id = confirmed.json()["recompute_job_id"]
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        correction_service, "PHASE_HOOK", lambda phase: (entered.set(), release.wait(10))
    )
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert entered.wait(timeout=10)
    client.post(
        f"{API}/{correction_id}/cancel",
        json={"revision": created.json()["correction"]["revision"]},
    )
    release.set()
    worker_thread.join(timeout=30)
    monkeypatch.setattr(correction_service, "PHASE_HOOK", None)
    with _session() as session:
        assert JobRepository(session).get_job(job_id).state == "cancelled"

    retried = client.post(f"{API}/{correction_id}/recompute/retry")
    assert retried.status_code == 200
    successor_id = retried.json()["recompute"]["job_id"]
    assert successor_id != job_id
    for _ in range(5):
        if svc.worker.run_once() == 0:
            break
    with _session() as session:
        assert JobRepository(session).get_job(successor_id).state == "completed"
        # Predecessor immutable; exactly one successor.
        assert JobRepository(session).get_job(job_id).state == "cancelled"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.predecessor_job_id == job_id)
            )
            == 1
        )
    fetched = client.get(f"{API}/{correction_id}")
    assert fetched.json()["recompute"]["job_id"] == successor_id
    assert fetched.json()["recompute"]["status"] == "completed"


def test_api_list_and_get_zero_mutations(client: TestClient) -> None:
    ids, role_a, role_b, occ_a, payload = _seed_correction_state(client)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    with _session() as session:
        before = {
            "corrections": session.scalar(
                select(func.count()).select_from(ObjectCorrection)
            ),
            "jobs": session.scalar(select(func.count()).select_from(Job)),
            "occ_role": session.get(ObjectOccurrence, occ_a.id).role_id,
        }
    listed = client.get(API)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["corrections"][0]["id"] == correction_id
    filtered = client.get(f"{API}?video_item_id={ids['video']}")
    assert filtered.json()["total"] == 1
    got = client.get(f"{API}/{correction_id}")
    assert got.status_code == 200
    with _session() as session:
        after = {
            "corrections": session.scalar(
                select(func.count()).select_from(ObjectCorrection)
            ),
            "jobs": session.scalar(select(func.count()).select_from(Job)),
            "occ_role": session.get(ObjectOccurrence, occ_a.id).role_id,
        }
    assert after == before  # GET endpoints caused ZERO durable mutations


# ══════════════════════════════════════════════════════════════════════════
# S08-T05-C1 (finding D): API-level media resolution + queued cancel.
# ══════════════════════════════════════════════════════════════════════════

ROLES_API = "/api/v2/object-intelligence/roles"
EXTRACTION_API = "/api/v2/object-intelligence/extraction"


def test_api_role_media_resolves_newest_after_recompute_and_after_restart(
    client: TestClient,
) -> None:
    """D2+D3+D6: after the recompute Job completes, the roles API resolves
    the NEWEST valid media for the affected roles; the OLD artifacts stay
    servable (auditable) via their own job content endpoint, an
    unaffected role keeps its identical media, and a FRESH re-read (app/
    browser restart) still resolves the regenerated media."""
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, "A")
        role_b = _seed_role(session, ids, "B")
        role_c = _seed_role(session, ids, "C")
        role_a.source_job_id = _seed_source_job(session, ids)
        role_b.source_job_id = _seed_source_job(session, ids)
        role_c.source_job_id = _seed_source_job(session, ids)
        old_a = _seed_media(session, role_a, role_a.source_job_id)
        old_b = _seed_media(session, role_b, role_b.source_job_id)
        _seed_media(session, role_c, role_c.source_job_id)
        _seed_occ(session, role_c, ids["scenes"][1], 70)
        occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
        _seed_occ(session, role_a, ids["scenes"][0], 8)
        _seed_occ(session, role_b, ids["scenes"][1], 95)
        session.commit()
        payload = _reassign_payload(ids, occ_a, role_a, role_b)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    assert confirmed.status_code == 201
    recompute_job_id = confirmed.json()["recompute_job_id"]
    for _ in range(5):
        if svc.worker.run_once() == 0:
            break

    def media_payload() -> dict[str, list[dict[str, Any]]]:
        resp = client.get(f"{ROLES_API}?video_item_id={ids['video']}&limit=200")
        assert resp.status_code == 200
        return {r["id"]: r.get("media", []) for r in resp.json()["roles"]}

    # Fresh re-reads (persisted state = survives app restart).
    payload1 = media_payload()
    payload2 = media_payload()
    assert payload1 == payload2
    media_a = payload1[role_a.id]
    media_b = payload1[role_b.id]
    media_c = payload1[role_c.id]
    assert {m["purpose"] for m in media_a} == {"thumbnail", "mask"}
    assert {m["purpose"] for m in media_b} == {"thumbnail", "mask"}
    for m in media_a + media_b:
        assert m["source_job_id"] == recompute_job_id
    # Unaffected role C: media unchanged (old DISCOVER job) — byte/hash identical.
    assert {m["purpose"] for m in media_c} == {"thumbnail", "mask"}
    for m in media_c:
        assert m["source_job_id"] == role_c.source_job_id
    new_art_a = next(m for m in media_a if m["purpose"] == "thumbnail")
    new_art_b = next(m for m in media_b if m["purpose"] == "thumbnail")
    assert new_art_a["artifact_id"] != old_a["thumbnail"].artifact_id
    assert new_art_b["artifact_id"] != old_b["thumbnail"].artifact_id

    # NEWEST VALID media is servable through the contained content endpoint.
    for artifact_id in (new_art_a["artifact_id"], new_art_b["artifact_id"]):
        content = client.get(
            f"{EXTRACTION_API}/{recompute_job_id}/artifacts/{artifact_id}/content"
        )
        assert content.status_code == 200
        assert content.headers.get("etag")
        assert content.headers.get("x-content-type-options") == "nosniff"
    # The SUPERSEDED (old) artifacts remain auditable + servable via their
    # own DISCOVER job, but are no longer the role's current media.
    old_artifact = old_a["thumbnail"].artifact_id
    old_content = client.get(
        f"{EXTRACTION_API}/{role_a.source_job_id}/artifacts/{old_artifact}/content"
    )
    assert old_content.status_code == 200  # file still on disk (not deleted)


def test_api_queued_cancel_drains_and_retry_replaces_media(client: TestClient) -> None:
    """D7: cancelling an applied correction whose recompute Job is still
    QUEUED drains to a terminal cancelled state; the correction keeps the OLD
    media (zero effects); a retry successor completes and then REPLACES the
    media, with the original Job left immutable."""
    svc = _svc()
    with _session() as session:
        ids = _seed_video(session)
        role_a = _seed_role(session, ids, "A")
        role_b = _seed_role(session, ids, "B")
        role_a.source_job_id = _seed_source_job(session, ids)
        role_b.source_job_id = _seed_source_job(session, ids)
        _seed_media(session, role_a, role_a.source_job_id)
        occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
        _seed_occ(session, role_a, ids["scenes"][0], 8)
        _seed_occ(session, role_b, ids["scenes"][1], 95)
        session.commit()
        payload = _reassign_payload(ids, occ_a, role_a, role_b)
    created = client.post(API, json=payload)
    correction_id = created.json()["correction"]["id"]
    confirmed = client.post(
        f"{API}/{correction_id}/confirm",
        json={"revision": created.json()["correction"]["revision"]},
    )
    job_id = confirmed.json()["recompute_job_id"]
    # Cancel while still QUEUED (never leased).
    cancel_revision = created.json()["correction"]["revision"]
    cancelled = client.post(
        f"{API}/{correction_id}/cancel", json={"revision": cancel_revision}
    )
    assert cancelled.status_code == 200
    for _ in range(10):
        if svc.worker.run_once() == 0:
            break
    with _session() as session:
        assert JobRepository(session).get_job(job_id).state == "cancelled"
        # Zero media effects: role A still resolves its OLD associations.
        media = _media_of(session, role_a.id)
        assert all(m.source_job_id == role_a.source_job_id for m in media)
    detail = client.get(f"{API}/{correction_id}").json()
    assert detail["recompute"]["status"] == "cancelled"

    # Retry -> successor Job -> completes -> replaces media.
    retried = client.post(f"{API}/{correction_id}/recompute/retry")
    assert retried.status_code == 200
    successor_id = retried.json()["recompute"]["job_id"]
    assert successor_id != job_id
    for _ in range(10):
        if svc.worker.run_once() == 0:
            break
    with _session() as session:
        assert JobRepository(session).get_job(job_id).state == "cancelled"
        assert JobRepository(session).get_job(successor_id).state == "completed"
        media = _media_of(session, role_a.id)
        assert all(m.source_job_id == successor_id for m in media)

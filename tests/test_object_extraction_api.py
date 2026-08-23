"""S08-T02 API tests — submit/read endpoints, exposure semantics, isolation.

Covers the /api/v2/object-intelligence/extraction surface: idempotent
submit through the API, fail-closed production provider path (503, no job
row), read-only GETs with ZERO durable mutations, and no partial/stale
output exposure (409 while active; outputs only for terminal-completed;
empty for cancelled/failed).
"""

from __future__ import annotations

import hashlib
import json
import threading

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.artifacts import ManagedRoot
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Job,
    JobEvent,
    JobStep,
    ObjectOccurrence,
    ObjectRole,
    Project,
    Scene,
    VideoItem,
    Workspace,
)
from app.services.object_extraction import DeterministicExtractionProvider

SOURCE_MEDIA_BYTES = (bytes(range(1, 256)) * 48) + b"S08-T02-API-source"
SOURCE_SHA = hashlib.sha256(SOURCE_MEDIA_BYTES).hexdigest()


def _svc():
    service = deps._job_service
    assert service is not None and service.session_factory is not None
    return service


def _seed_video_item(session: Session, *, scene_count: int = 2) -> tuple[str, str]:
    workspace = session.get(Workspace, DEFAULT_WORKSPACE_ID)
    if workspace is None:
        workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_ID)
        session.add(workspace)
    project = Project(workspace_id=DEFAULT_WORKSPACE_ID, name="Extraction Project")
    video = VideoItem(
        project=project,
        title="Primary",
        position=0,
        width=320,
        height=240,
        duration_ms=6000,
        fps_num=30,
        fps_den=1,
    )
    session.add(project)
    session.flush()
    session.add(video)
    session.flush()
    rel = (
        f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video.id}/import/source.mp4"
    )
    managed_path = _svc().managed_root / rel
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(SOURCE_MEDIA_BYTES)
    source = Artifact(
        workspace_id=DEFAULT_WORKSPACE_ID,
        kind="video",
        relative_path=rel,
        state="ready",
        sha256=SOURCE_SHA,
        size_bytes=len(SOURCE_MEDIA_BYTES),
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    video.source_artifact_id = source.id
    for index in range(scene_count):
        session.add(
            Scene(
                video_item=video,
                position=index,
                start_frame=index * 90,
                end_frame=index * 90 + 89,
                start_time_ms=index * 3000,
                end_time_ms=index * 3000 + 2999,
                status="pending",
            )
        )
    session.commit()
    return project.id, video.id


def _run_worker(svc, max_claims: int = 5) -> int:
    claims = 0
    for _ in range(max_claims):
        claimed = svc.worker.run_once()
        if claimed == 0:
            break
        claims += claimed
    return claims


def _submit(svc, project_id: str, video_item_id: str, **kwargs):
    from app.services.object_extraction import submit_discover_objects

    return submit_discover_objects(
        svc.session_factory,
        workspace_id=DEFAULT_WORKSPACE_ID,
        project_id=project_id,
        video_item_id=video_item_id,
        source_sha256=kwargs.get("source_sha256", SOURCE_SHA),
        generation=kwargs.get("generation", "1"),
        extractor_version=kwargs.get("extractor_version", "1.0.0"),
        provider=kwargs.get("provider", "deterministic"),
        managed_root=svc.managed_root,
    )


class _BlockingDeterministicProvider(DeterministicExtractionProvider):
    """Real deterministic provider + test synchronization hook (see the
    focused suite for the cancel-during-running pattern)."""

    entered_extract = threading.Event()
    release_extract = threading.Event()

    def extract(self, evidence: dict) -> list:
        _BlockingDeterministicProvider.entered_extract.set()
        if not _BlockingDeterministicProvider.release_extract.wait(timeout=10):
            raise TimeoutError("test hook timed out")
        return super().extract(evidence)


def _qa_policy(monkeypatch) -> None:
    """Server policy = deterministic (QA/test deployment).  The provider is
    NEVER supplied by the request body; genuine QA mode is declared so the
    QA-only adapter is authorized (C2 acceptance 7-9)."""
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_PROVIDER", "deterministic")


def _row_counts() -> dict[str, int]:
    svc = _svc()
    with svc.session_factory() as session:
        return {
            "jobs": int(session.scalar(select(func.count()).select_from(Job)) or 0),
            "steps": int(session.scalar(select(func.count()).select_from(JobStep)) or 0),
            "events": int(session.scalar(select(func.count()).select_from(JobEvent)) or 0),
            "roles": int(session.scalar(select(func.count()).select_from(ObjectRole)) or 0),
            "occurrences": int(
                session.scalar(select(func.count()).select_from(ObjectOccurrence)) or 0
            ),
            "artifacts": int(session.scalar(select(func.count()).select_from(Artifact)) or 0),
            "owners": int(
                session.scalar(select(func.count()).select_from(ArtifactOwner)) or 0
            ),
        }


def test_api_submit_and_poll_completed(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
            "source_sha256": SOURCE_SHA,
            "generation": "1",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job_id = body["job_id"]
    assert body["reused"] is False and body["status"] == "queued"

    # While queued, the outputs endpoint refuses (no partial exposure).
    active = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert active.status_code == 409, active.text

    _run_worker(svc)
    status = client.get(f"/api/v2/object-intelligence/extraction/{job_id}")
    assert status.status_code == 200, status.text
    data = status.json()
    assert data["status"] == "completed"
    assert data["job_type"] == "DISCOVER_OBJECTS"
    assert data["provider"] == "deterministic"
    assert data["extractor_version"] == "1.0.0"
    assert data["source_sha256"] == SOURCE_SHA
    assert data["video_item_id"] == video_id
    assert len(data["outputs"]) == 5  # 4 images + manifest
    assert len(data["candidates"]) == 2

    outputs = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert outputs.status_code == 200, outputs.text
    payload = outputs.json()
    assert payload["status"] == "completed"
    assert len(payload["outputs"]) == 5
    assert len(payload["candidates"]) == 2
    for candidate in payload["candidates"]:
        assert len(candidate["artifacts"]) == 2
        for artifact in candidate["artifacts"]:
            assert artifact["sha256"] and len(artifact["sha256"]) == 64
            assert artifact["width"] > 0 and artifact["height"] > 0
            assert artifact["mime_type"] == "image/png"


def test_api_duplicate_submit_reuses_completed(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    payload = {
        "project_id": project_id,
        "video_item_id": video_id,
        "source_sha256": SOURCE_SHA,
    }
    first = client.post("/api/v2/object-intelligence/extraction", json=payload)
    assert first.status_code == 201, first.text
    _run_worker(svc)
    second = client.post("/api/v2/object-intelligence/extraction", json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["reused"] is True


def test_api_active_duplicate_conflict(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    payload = {
        "project_id": project_id,
        "video_item_id": video_id,
    }
    first = client.post("/api/v2/object-intelligence/extraction", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/v2/object-intelligence/extraction", json=payload)
    assert second.status_code == 409, second.text
    assert "in use" in second.text


def test_api_production_provider_fails_closed_no_job_row(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    """Default (production sam2-local) provider with a genuinely missing
    backend => 503 and NO durable Job row — the production path never
    silently falls back (correction B4: real capability probe)."""
    monkeypatch.delenv("MOTIONFORGE_EXTRACTION_PROVIDER", raising=False)
    monkeypatch.setenv(
        "MOTIONFORGE_SAM2_CHECKPOINT", str(tmp_path / "missing.pt")
    )
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    assert resp.status_code == 503, resp.text
    assert "not available" in resp.text
    counts = _row_counts()
    assert counts["jobs"] == 0 and counts["roles"] == 0 and counts["artifacts"] == 1


def test_api_client_supplied_provider_rejected(client: TestClient) -> None:
    """Correction B3: provider choice is SERVER/runtime policy — ANY
    client-supplied value (including the QA provider) is rejected 422."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    for provider_value in ("deterministic", "sam2-local", "bogus"):
        resp = client.post(
            "/api/v2/object-intelligence/extraction",
            json={
                "project_id": project_id,
                "video_item_id": video_id,
                "provider": provider_value,
            },
        )
        assert resp.status_code == 422, (provider_value, resp.text)
        assert "server/runtime policy" in resp.text
    assert _row_counts()["jobs"] == 0


def test_api_get_endpoints_zero_durable_mutations(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
        },
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    before = _row_counts()
    for _ in range(5):
        assert client.get(f"/api/v2/object-intelligence/extraction/{job_id}").status_code == 200
        assert (
            client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs").status_code
            == 200
        )
    assert client.get("/api/v2/object-intelligence/extraction/missing-job").status_code == 404
    after = _row_counts()
    assert before == after


def test_api_outputs_scoped_to_job_path(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    """GET outputs only exposes artifacts under THIS job's managed path —
    an artifact row of another job in the same workspace is never leaked."""
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
        other = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="image",
            relative_path=(
                f"artifacts/{DEFAULT_WORKSPACE_ID}/image/other-job-id/extract/"
                "foreign.png"
            ),
            state="ready",
            sha256="c" * 64,
            size_bytes=10,
            mime_type="image/png",
            width=1,
            height=1,
        )
        session.add(other)
        session.commit()
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
        },
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    outputs = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert outputs.status_code == 200, outputs.text
    rels = [o["relative_path"] for o in outputs.json()["outputs"]]
    assert all(f"/image/{job_id}/" in rel for rel in rels)
    assert not any("other-job-id" in rel for rel in rels)


def test_api_cancelled_job_exposes_no_outputs(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
        },
    )
    job_id = resp.json()["job_id"]
    monkeypatch.setattr(
        "app.services.object_extraction.DeterministicExtractionProvider",
        _BlockingDeterministicProvider,
    )
    _BlockingDeterministicProvider.entered_extract.clear()
    _BlockingDeterministicProvider.release_extract.clear()
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert _BlockingDeterministicProvider.entered_extract.wait(timeout=10)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    _BlockingDeterministicProvider.release_extract.set()
    worker_thread.join(timeout=30)
    assert not worker_thread.is_alive()
    status = client.get(f"/api/v2/object-intelligence/extraction/{job_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "cancelled"
    assert status.json()["outputs"] == []
    assert status.json()["candidates"] == []
    outputs = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert outputs.status_code == 200, outputs.text
    assert outputs.json()["outputs"] == []
    assert outputs.json()["candidates"] == []


def test_api_failed_job_exposes_no_outputs(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=0)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
        },
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    status = client.get(f"/api/v2/object-intelligence/extraction/{job_id}")
    assert status.status_code == 200, status.text
    data = status.json()
    assert data["status"] == "failed"
    assert data["error"] is not None
    assert data["outputs"] == []
    outputs = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert outputs.status_code == 200
    assert outputs.json()["outputs"] == []



# ── Correction B5/B7/B8/B9: stable ids, content endpoint, current lookup ─────


def test_api_outputs_carry_stable_role_ids(
    client: TestClient, monkeypatch
) -> None:
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    payload = client.get(
        f"/api/v2/object-intelligence/extraction/{job_id}/outputs"
    ).json()
    from app.persistence.models import ObjectRole

    with svc.session_factory() as session:
        role_ids = {r[0] for r in session.execute(select(ObjectRole.id)).all()}
    for candidate in payload["candidates"]:
        assert candidate["role_id"]  # stable id present
        assert candidate["role_id"] in role_ids  # matches the durable role row
    assert len({c["role_id"] for c in payload["candidates"]}) == 2


def test_api_content_endpoint_serves_real_bytes(
    client: TestClient, monkeypatch
) -> None:
    """Correction B7: the content endpoint serves the REAL artifact bytes
    with ETag (sha256), nosniff and allowlisted image MIME; 304 on
    If-None-Match; hash/size verified against the row."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    with svc.session_factory() as session:
        artifact = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert artifact is not None
        artifact_id = artifact.id
        expected_sha = artifact.sha256
        expected_size = artifact.size_bytes
    url = f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/{artifact_id}/content"
    content = client.get(url)
    assert content.status_code == 200, content.text
    assert content.headers["etag"] == f'"{expected_sha}"'
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["content-type"].startswith("image/png")
    body = content.content
    assert len(body) == expected_size
    import hashlib

    assert hashlib.sha256(body).hexdigest() == expected_sha
    assert body.startswith(b"\x89PNG")
    # If-None-Match with the current ETag => 304, no body.
    cached = client.get(url, headers={"If-None-Match": f'"{expected_sha}"'})
    assert cached.status_code == 304, cached.text
    assert cached.content == b""


def test_api_content_endpoint_containment_and_stale(
    client: TestClient, monkeypatch
) -> None:
    """Correction B7: 404 for unknown/foreign/non-image artifacts; 409 for
    missing files, hash/size drift, non-ready rows and path escapes."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    with svc.session_factory() as session:
        artifact = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert artifact is not None
        artifact_id = artifact.id
        rel = artifact.relative_path
    url = f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/{artifact_id}/content"
    # Unknown artifact id => 404
    assert client.get(
        f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/not-an-id/content"
    ).status_code == 404
    # Foreign artifact (no association to this job) => 404
    with svc.session_factory() as session:
        foreign = Artifact(
            workspace_id="default",
            kind="image",
            relative_path=f"artifacts/default/image/{job_id}/extract/foreign.png",
            state="ready",
            sha256="e" * 64,
            size_bytes=5,
            mime_type="image/png",
            width=1,
            height=1,
        )
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id
    assert client.get(
        f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/{foreign_id}/content"
    ).status_code == 404
    # Missing file (stale) => 409
    target = ManagedRoot(svc.managed_root).resolve(rel)
    target.unlink()
    assert client.get(url).status_code == 409
    # Restore + tamper => 409 (hash/size mismatch)
    from app.services.object_extraction import _png_bytes

    target.write_bytes(_png_bytes(8, 8, b"\x00" * 256))
    assert client.get(url).status_code == 409
    # Non-image artifact => 404
    with svc.session_factory() as session:
        doc = Artifact(
            workspace_id="default",
            kind="document",
            relative_path=f"artifacts/default/image/{job_id}/extract/notes.txt",
            state="ready",
            sha256="f" * 64,
            size_bytes=3,
            mime_type="text/plain",
        )
        session.add(doc)
        session.commit()
        doc_id = doc.id
    assert client.get(
        f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/{doc_id}/content"
    ).status_code == 404
    # Path-escape row (managed containment rejection) => 409
    with svc.session_factory() as session:
        evil = Artifact(
            workspace_id="default",
            kind="image",
            relative_path="../../escape.png",
            state="ready",
            sha256="a" * 64,
            size_bytes=3,
            mime_type="image/png",
            width=1,
            height=1,
        )
        session.add(evil)
        session.commit()
        evil_id = evil.id
    assert client.get(
        f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/{evil_id}/content"
    ).status_code == 409


def test_api_current_lookup_and_generation_filtering(
    client: TestClient, monkeypatch
) -> None:
    """Correction B8/B9: backend-authoritative current lookup per video +
    generation; list filtering keeps historical rows auditable without
    mixing generations."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    gen1 = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
            "generation": "1",
        },
    ).json()["job_id"]
    _run_worker(svc)
    # C2: generation advances only when the backend source advances.
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None
        rel2 = (
            f"artifacts/{DEFAULT_WORKSPACE_ID}/video/{video_id}/"
            "import/source-v2.mp4"
        )
        new_bytes = SOURCE_MEDIA_BYTES + b"-v2"
        managed_path2 = svc.managed_root / rel2
        managed_path2.parent.mkdir(parents=True, exist_ok=True)
        managed_path2.write_bytes(new_bytes)
        source2 = Artifact(
            workspace_id=DEFAULT_WORKSPACE_ID,
            kind="video",
            relative_path=rel2,
            state="ready",
            sha256=hashlib.sha256(new_bytes).hexdigest(),
            size_bytes=len(new_bytes),
            mime_type="video/mp4",
        )
        session.add(source2)
        session.flush()
        video.source_artifact_id = source2.id
        session.commit()
    gen2 = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    ).json()["job_id"]
    _run_worker(svc)
    # Current (no generation) = newest completed => gen2
    current = client.get(
        "/api/v2/object-intelligence/extraction/current",
        params={"video_item_id": video_id},
    )
    assert current.status_code == 200, current.text
    assert current.json()["job_id"] == gen2
    assert current.json()["status"] == "completed"
    assert current.json()["generation"] == "2"
    # Current for generation 1 => gen1 job only (no mixing)
    current1 = client.get(
        "/api/v2/object-intelligence/extraction/current",
        params={"video_item_id": video_id, "source_generation": "1"},
    )
    assert current1.status_code == 200
    assert current1.json()["job_id"] == gen1
    # Unknown generation => 404
    missing = client.get(
        "/api/v2/object-intelligence/extraction/current",
        params={"video_item_id": video_id, "source_generation": "9"},
    )
    assert missing.status_code == 404
    # List filtering: generation 1 exposes ONLY gen1; no filter exposes both
    list1 = client.get(
        "/api/v2/object-intelligence/extraction",
        params={"video_item_id": video_id, "source_generation": "1"},
    ).json()
    assert [j["job_id"] for j in list1["jobs"]] == [gen1]
    all_jobs = client.get(
        "/api/v2/object-intelligence/extraction",
        params={"video_item_id": video_id},
    ).json()
    assert {j["job_id"] for j in all_jobs["jobs"]} == {gen1, gen2}
    assert all(j["status"] == "completed" for j in all_jobs["jobs"])


def test_api_zero_mutation_includes_new_reads(
    client: TestClient, monkeypatch
) -> None:
    """The new read endpoints (current, list, content) also cause ZERO
    durable mutations."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    with svc.session_factory() as session:
        artifact = session.scalars(
            select(Artifact).where(Artifact.kind == "image").limit(1)
        ).first()
        assert artifact is not None
        artifact_id = artifact.id
    before = _row_counts()
    for _ in range(3):
        client.get(
            "/api/v2/object-intelligence/extraction/current",
            params={"video_item_id": video_id},
        )
        client.get(
            "/api/v2/object-intelligence/extraction",
            params={"video_item_id": video_id, "source_generation": "1"},
        )
        client.get(
            f"/api/v2/object-intelligence/extraction/{job_id}/artifacts/"
            f"{artifact_id}/content"
        )
    assert _row_counts() == before



# ── Correction C2 (API): backend source authority + provider gate ───────────


def test_api_spoof_generation_rejected_no_job(
    client: TestClient, monkeypatch
) -> None:
    """C2 acceptance 1-3: a client generation hint differing from the
    backend current generation => 409 and NO Job row."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
            "generation": "999",
        },
    )
    assert resp.status_code == 409, resp.text
    assert _row_counts()["jobs"] == 0
    assert _row_counts()["roles"] == 0


def test_api_spoof_source_sha_rejected_no_job(
    client: TestClient, monkeypatch
) -> None:
    """C2: a client source_sha256 hint differing from the backend artifact
    => 409 and NO Job row."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={
            "project_id": project_id,
            "video_item_id": video_id,
            "source_sha256": "c" * 64,
        },
    )
    assert resp.status_code == 409, resp.text
    assert _row_counts()["jobs"] == 0


def test_api_omitted_sha_succeeds_with_authoritative_source(
    client: TestClient, monkeypatch
) -> None:
    """C2: omitting the sha hint works — the server resolves the current
    source sha; the completed job's manifest carries the authoritative
    value."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    data = client.get(f"/api/v2/object-intelligence/extraction/{job_id}").json()
    assert data["status"] == "completed"
    assert data["source_sha256"] == SOURCE_SHA  # backend-authoritative
    assert data["generation"] == "1"


def test_api_media_tampered_after_submit_fails_closed(
    client: TestClient, monkeypatch
) -> None:
    """C2 acceptance 5/6: byte-wise media tamper after submit => job fails
    with MEDIA_CHANGED BEFORE inference; zero published outputs."""
    _qa_policy(monkeypatch)
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session)
    resp = client.post(
        "/api/v2/object-intelligence/extraction",
        json={"project_id": project_id, "video_item_id": video_id},
    )
    job_id = resp.json()["job_id"]
    with svc.session_factory() as session:
        video = session.get(VideoItem, video_id)
        assert video is not None and video.source_artifact_id is not None
        rel = session.get(Artifact, video.source_artifact_id).relative_path
    target = ManagedRoot(svc.managed_root).resolve(rel)
    with open(target, "ab") as handle:
        handle.write(b"API-tamper")
    _run_worker(svc)
    data = client.get(f"/api/v2/object-intelligence/extraction/{job_id}").json()
    assert data["status"] == "failed"
    assert "no longer matches its Artifact row" in (data.get("error") or "")
    with svc.session_factory() as session:
        row = session.get(Job, job_id)
        error_payload = json.loads(row.error_json or "{}") if row else {}
        assert error_payload.get("error_code") == "MEDIA_CHANGED"
    counts = _row_counts()
    assert counts["roles"] == 0
    assert counts["artifacts"] == 1  # only the seeded source artifact

def test_graph_readback_only_when_completed(client: TestClient, monkeypatch) -> None:  # noqa: E501
    """AC6: /outputs 409 while active; empty for queued/running/cancelled/failed; graph only when completed."""  # noqa: E501
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_PROVIDER", "deterministic")
    svc = _svc()
    # Ensure worker uses deterministic provider
    # Patch submit to ensure deterministic via env (route uses os.environ)
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    # Submit
    resp = client.post("/api/v2/object-intelligence/extraction", json={"project_id": project_id, "video_item_id": video_id})  # noqa: E501
    assert resp.status_code == 201
    job_id = resp.json()["job_id"]
    # While queued/running: /outputs 409, /{job_id} has empty graph
    r = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    # Job is queued -> active -> 409
    assert r.status_code == 409
    r2 = client.get(f"/api/v2/object-intelligence/extraction/{job_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["outputs"] == []
    assert data.get("segments", []) == []
    assert data.get("motions", []) == []
    # Complete
    _run_worker(svc)
    r3 = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert r3.status_code == 200
    out = r3.json()
    assert len(out["segments"]) == 4
    assert len(out["motions"]) >= 4
    assert len(out["occlusions"]) >= 2
    assert len(out["contacts"]) >= 2
    # Also via /{job_id}
    r4 = client.get(f"/api/v2/object-intelligence/extraction/{job_id}")
    d4 = r4.json()
    assert len(d4["segments"]) == 4
    # Via /segments and /graph
    r5 = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/segments")
    assert r5.status_code == 200
    assert len(r5.json()["segments"]) == 4
    r6 = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/graph")
    assert r6.status_code == 200
    assert len(r6.json()["segments"]) == 4


def test_outputs_endpoint_exposes_only_committed_artifacts(client: TestClient, monkeypatch) -> None:  # noqa: E501
    """AC6: outputs endpoint exposes only committed artifacts; no staging; fail-closed reads."""
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_QA_MODE", "1")
    monkeypatch.setenv("MOTIONFORGE_EXTRACTION_PROVIDER", "deterministic")
    svc = _svc()
    with svc.session_factory() as session:
        project_id, video_id = _seed_video_item(session, scene_count=2)
    resp = client.post("/api/v2/object-intelligence/extraction", json={"project_id": project_id, "video_item_id": video_id})  # noqa: E501
    job_id = resp.json()["job_id"]
    _run_worker(svc)
    r = client.get(f"/api/v2/object-intelligence/extraction/{job_id}/outputs")
    assert r.status_code == 200
    data = r.json()
    # All artifacts must be under job prefix and state ready, no staging
    for art in data["outputs"]:
        assert art["relative_path"].startswith(f"artifacts/{svc.session_factory.__self__ if False else 'default'}/image/{job_id}/") or art["relative_path"].startswith(f"artifacts/default/image/{job_id}/")  # noqa: E501
        assert "staging" not in art["relative_path"]
    # Graph should be present
    assert len(data["segments"]) > 0
    assert len(data["motions"]) > 0


"""S11-T04B (W10) — occurrence/segment-backed correction -> affected rerun.

Binary gates (production plan REV7/C6 SHA 34247926..., W10 block) over the
REAL pipeline + REAL registered HTTP routes (TestClient on the temp app):

1. Rerun scope V1 is EXACTLY occurrence/segment/StructuralLock/renderer
   route (Decision E); any other issue answers an explain-action and NO
   correction request is ever built.
2. No "rerun all" exists: the bridge owns per-item mapping only; the
   qc-items surface stays GET-only; the only recompute-retry POST on the
   corrections router is the pre-existing ``/{id}/recompute/retry``.
3. preview -> confirm -> RECOMPUTE_OBJECTS in ONE transaction (bridge chain
   commits once); the QC item moves to recheck (acknowledged) after publish
   OK and the T03F orchestrator auto-resolves it on a fresh recheck run.
4. Unaffected artifacts are byte-identical after the rerun (artifact rows +
   sha256 + managed bytes unchanged); manifest.affected_role_ids bounds the
   published set.

Isolation: shared conftest ``client`` fixture (isolated project root + temp
Alembic-head DB + patched deps) + REAL JobService worker (``run_once``).
The bridge module does NOT exist at WAVE_BASE — importing it here is the RED
gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import JobRepository, StepInput
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
from app.persistence.qc_items import QCItemRecord, QCItemRepository
from app.services import qc_correction_bridge as bridge
from app.services.qc_correction_bridge import (
    QcCorrectionBridgeError,
    QcRerunOutOfScopeError,
    classify_rerun_scope,
)
from app.services.qc_checks import audio_missing, av_sync_drift  # noqa: F401  (self-register)
from app.services.qc_checks.registry import registry
from app.services.qc_checks.orchestrator import run_full_check_set
from app.workflow.qc_checks_handler import (
    SCOPE_AUDIO,
    compose_check_run_args,
)

API = "/api/v2/object-intelligence/corrections"

SOURCE_MEDIA_BYTES = b"motionforge-t04b-source-media"
SOURCE_SHA = hashlib.sha256(SOURCE_MEDIA_BYTES).hexdigest()

WS = DEFAULT_WORKSPACE_ID
P1 = str(uuid.uuid4())
V1 = str(uuid.uuid4())
V2 = str(uuid.uuid4())

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def _ensure_audio_band_registered() -> None:
    for name, entry_point in (
        ("audio_missing", "app.services.qc_checks.audio_missing:detect"),
        ("av_sync_drift", "app.services.qc_checks.av_sync_drift:detect"),
    ):
        registry.register(name, entry_point)


def _svc():
    service = deps.get_job_service()
    assert service is not None and service.session_factory is not None
    return service


def _session():
    return _svc().session_factory()


# ── seeds ───────────────────────────────────────────────────────────────────


def _seed_video(session, *, pid: str, vid: str) -> dict[str, str]:
    """Workspace + project + video + source artifact + scenes (S08 recipe).

    The given ``pid``/``vid`` are the DURABLE ids (never just name
    decorations) so callers can reference the same project/video from any
    other session against the same DB.
    """
    ws = session.get(Workspace, WS)
    if ws is None:
        session.add(Workspace(id=WS, name=WS))
        session.flush()
    project = Project(id=pid, workspace_id=WS, name=f"T04B-{pid[:8]}")
    session.add(project)
    session.flush()
    video = VideoItem(
        id=vid, project_id=pid, title="T04B", position=0, width=320,
        height=240, duration_ms=6000, fps_num=30, fps_den=1,
    )
    session.add(video)
    session.flush()
    source = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path=f"artifacts/{WS}/video/{video.id}/import/t04b-source.mp4",
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


def _seed_source_job(session, ids: dict[str, str]) -> str:
    """COMPLETED DISCOVER_OBJECTS job — makes generation "1" current."""
    job = JobRepository(session).create_job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=ids["video"],
        input_manifest={"schema_version": 1, "source_sha256": SOURCE_SHA},
        idempotency_key=f"t04b-discover:{uuid.uuid4()}",
        input_generation="1",
        steps=[StepInput(step_code="extract", position=0, step_type="sync")],
        actor="system",
    )
    from sqlalchemy import update as sa_update

    session.execute(sa_update(Job).where(Job.id == job.id).values(state="completed"))
    return job.id


def _seed_role(session, ids: dict[str, str], name: str) -> ObjectRole:
    role = ObjectRole(
        workspace_id=WS,
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


def _seed_occ(
    session, role: ObjectRole, scene_id: str, frame: int
) -> ObjectOccurrence:
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


def _seed_media(session, role: ObjectRole, source_job_id: str, tag: str) -> dict[str, ObjectRoleArtifact]:
    """OLD active DISCOVER media (thumbnail + mask) for a role."""
    associations: dict[str, ObjectRoleArtifact] = {}
    managed = ManagedRoot(_svc().managed_root)
    for purpose in ("thumbnail", "mask"):
        relative_path = (
            f"artifacts/{role.workspace_id}/image/{source_job_id}/"
            f"extract/{tag}-{purpose}.png"
        )
        raw = (b"\x89PNG" + f"{tag}-{purpose}".encode("utf-8")).ljust(128, b"\x00")
        managed.atomic_write_bytes(relative_path, raw)
        artifact = Artifact(
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
        session.flush()
        assoc = ObjectRoleArtifact(
            workspace_id=role.workspace_id,
            role_id=role.id,
            artifact_id=artifact.id,
            purpose=purpose,
            source_generation="1",
            source_job_id=source_job_id,
        )
        session.add(assoc)
        associations[purpose] = assoc
    session.flush()
    return associations


def _create_qc_item(
    session,
    *,
    ids: dict[str, str],
    layer_ref_type: str,
    layer_ref_id: str,
    evidence: dict[str, Any],
    reason_code: str = "trajectory_drift",
    segment_row_id: str | None = None,
    segment_logical_id: str | None = None,
) -> QCItemRecord:
    return QCItemRepository(session).create(
        workspace_id=WS,
        project_id=ids["project"],
        video_item_id=ids["video"],
        layer_ref_type=layer_ref_type,
        layer_ref_id=layer_ref_id,
        reason_code=reason_code,
        evidence_window_key=f"t04b-window-{uuid.uuid4()}",
        evidence={"schema_version": 1, **evidence},
        severity="warning",
        category=reason_code,
        detector="trajectory_drift",
        detector_revision="1.0.0",
        confidence=0.85,
        confidence_source="derived",
        checkpoint_ref="t04b-checkpoint",
        segment_row_id=segment_row_id,
        segment_logical_id=segment_logical_id,
    )


def _seed_occurrence_issue(
    session, *, with_role_b: bool = False, with_role_c: bool = False
) -> dict[str, Any]:
    """Video + completed DISCOVER + roles + occurrences + media + QC item."""
    ids = _seed_video(session, pid=P1, vid=V1)
    job = _seed_source_job(session, ids)
    role_a = _seed_role(session, ids, "A")
    role_a.source_job_id = job
    role_b = _seed_role(session, ids, "B")
    role_b.source_job_id = job
    role_c = _seed_role(session, ids, "C")
    role_c.source_job_id = job
    occ_a = _seed_occ(session, role_a, ids["scenes"][0], 5)
    _seed_occ(session, role_a, ids["scenes"][0], 8)
    _seed_occ(session, role_b, ids["scenes"][1], 95)
    occ_c = _seed_occ(session, role_c, ids["scenes"][1], 42)
    media_a = _seed_media(session, role_a, job, "role-a") if with_role_b else {}
    media_c = _seed_media(session, role_c, job, "role-c") if with_role_c else {}
    session.commit()
    item = _create_qc_item(
        session,
        ids=ids,
        layer_ref_type="object",
        layer_ref_id=f"obj-{uuid.uuid4().hex[:8]}",
        evidence={
            "object_id": f"obj-{role_a.id[:8]}",
            "object_role_id": role_a.id,
            "occurrence_id": occ_a.id,
            "role_revision": role_a.revision,
            "occurrence_revision": occ_a.revision,
        },
    )
    session.commit()
    return {
        "ids": ids,
        "job": job,
        "role_a": role_a,
        "role_b": role_b,
        "role_c": role_c,
        "occ_a": occ_a,
        "occ_c": occ_c,
        "media_a": media_a,
        "media_c": media_c,
        "item": item,
    }


def _artifact_snapshot(session, *, role_id: str | None = None) -> dict[str, str]:
    """{artifact_id: sha256} of all ready images for a role (or all)."""
    query = select(Artifact).where(Artifact.workspace_id == WS)
    return {
        row.id: row.sha256
        for row in session.scalars(query).all()
        if role_id is None
        or session.scalar(
            select(ObjectRoleArtifact.id).where(
                ObjectRoleArtifact.artifact_id == row.id,
                ObjectRoleArtifact.role_id == role_id,
            )
        )
    }


# ── AC1: V1 scope binary gate ───────────────────────────────────────────────


def _scope_item(**overrides: Any) -> QCItemRecord:
    return QCItemRecord(
        id="scope-item-1",
        workspace_id=WS,
        project_id=P1,
        video_item_id=V1,
        segment_row_id=overrides.get("segment_row_id"),
        segment_logical_id=overrides.get("segment_logical_id"),
        layer_ref_type=overrides.get("layer_ref_type", "video_item"),
        layer_ref_id=overrides.get("layer_ref_id", V1),
        reason_code="trajectory_drift",
        evidence_window_key="w",
        evidence=overrides.get("evidence", {"schema_version": 1}),
        status="open",
        severity="warning",
        category="trajectory_drift",
        detector="trajectory_drift",
        detector_revision="1.0.0",
        confidence=0.8,
        confidence_source="derived",
        checkpoint_ref="c",
        revision=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def test_v1_scope_accepts_only_the_four_anchors() -> None:
    """AC1: occurrence / segment / StructuralLock / renderer route ONLY."""
    cases = [
        _scope_item(
            layer_ref_type="object",
            layer_ref_id="obj-1",
            evidence={"schema_version": 1, "object_role_id": "role-1",
                      "occurrence_id": "occ-1"},
        ),
        _scope_item(
            layer_ref_type="segment",
            layer_ref_id="seg-1",
            segment_row_id="seg-1",
            segment_logical_id="seg-logical-1",
            evidence={"schema_version": 1, "segment_id": "seg-1"},
        ),
        _scope_item(
            layer_ref_type="render",
            layer_ref_id="render-ref",
            evidence={"schema_version": 1, "lock_manifest_id": "lock-1"},
        ),
        _scope_item(
            layer_ref_type="route",
            layer_ref_id="seg-route-1",
            evidence={"schema_version": 1, "segment_id": "seg-route-1",
                      "renderer_route": "mesh_warp"},
        ),
    ]
    for item in cases:
        decision = classify_rerun_scope(item)
        assert decision.in_scope is True, (
            f"kind {item.layer_ref_type} must be in V1 scope, got {decision}"
        )
        assert decision.anchor in bridge.RERUN_ANCHORS


def test_v1_scope_rejects_out_of_scope_with_explain_action() -> None:
    """AC1 binary: an out-of-scope issue NEVER yields a correction request —
    the bridge answers an explain-action (Decision E)."""
    rejects = [
        _scope_item(layer_ref_type="frame", layer_ref_id="f",
                    evidence={"schema_version": 1, "frame_index": 42}),
        _scope_item(layer_ref_type="audio", layer_ref_id="audio-job",
                    evidence={"schema_version": 1, "job_id": "audio-job"}),
        _scope_item(layer_ref_type="scene", layer_ref_id="scene-1",
                    evidence={"schema_version": 1, "scene_id": 1}),
        _scope_item(layer_ref_type="video_item", layer_ref_id=V1,
                    evidence={"schema_version": 1, "timecode_ms": 0}),
        _scope_item(layer_ref_type="render", layer_ref_id="r",
                    evidence={"schema_version": 1,
                              "renderer_route": "sprite_affine"}),
        _scope_item(layer_ref_type="route", layer_ref_id="r",
                    evidence={"schema_version": 1, "segment_id": "s",
                              "renderer_route": "bogus_route"}),
        # unknown kind — fail-closed explain (never guessed)
        _scope_item(layer_ref_type="mystery", layer_ref_id="x"),
    ]
    for item in rejects:
        decision = classify_rerun_scope(item)
        assert decision.in_scope is False, (
            f"kind {item.layer_ref_type} must be OUT of V1 scope"
        )
        assert decision.explain_code and decision.explain_reason


def test_out_of_scope_chain_refuses_with_explain_action(
    client: TestClient,
) -> None:
    """The bridge's real entry points refuse out-of-scope items with the
    stable explain-action BEFORE any pipeline call."""
    with _session() as session:
        ids = _seed_video(session, pid=P1, vid=V1)
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="video_item",
            layer_ref_id=ids["video"],
            evidence={"schema_version": 1, "timecode_ms": 0},
        )
        session.commit()
        try:
            bridge.build_correction_request(session, item, workspace_id=WS)
        except QcRerunOutOfScopeError as exc:
            assert exc.code in bridge.EXPLAIN_REASONS
            assert exc.reason
        else:  # pragma: no cover - must raise
            pytest.fail("out-of-scope item must be refused")
        assert classify_rerun_scope(item).in_scope is False


# ── AC3: preview zero-writes (real API) ─────────────────────────────────────


def test_preview_zero_writes_revision_roles_unchanged(client: TestClient) -> None:
    """preview = ZERO durable writes: no correction row, no role/occurrence
    revision bump (bridge payload -> the REAL POST /corrections/preview)."""
    with _session() as session:
        seeded = _seed_occurrence_issue(session)
        item = seeded["item"]
        role_a = seeded["role_a"]
        occ_a = seeded["occ_a"]
    with _session() as session:
        before_corrections = session.scalar(
            select(func.count()).select_from(ObjectCorrection)
        )
        before_role_rev = session.get(ObjectRole, role_a.id).revision
        before_occ_rev = session.get(ObjectOccurrence, occ_a.id).revision

    with _session() as session:
        payload = bridge.build_correction_request(session, item, workspace_id=WS)
    assert payload["kind"] == "candidate_edit"
    assert payload["target"] == "occurrence"
    assert payload["occurrence_id"] == occ_a.id

    response = client.post(f"{API}/preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["correction_type"] == "candidate_edit"
    assert data["affected_role_ids"] == [role_a.id]
    assert data["affected_occurrence_ids"] == [occ_a.id]
    assert data["recompute_needed"] is True  # role_a is DISCOVER-produced

    with _session() as session:
        assert (
            session.scalar(select(func.count()).select_from(ObjectCorrection))
            == before_corrections
        )
        assert session.get(ObjectRole, role_a.id).revision == before_role_rev
        assert (
            session.get(ObjectOccurrence, occ_a.id).revision == before_occ_rev
        )


# ── AC3: one-transaction chain -> RECOMPUTE_OBJECTS successor ───────────────


def test_bridge_chain_confirm_recompute_and_item_recheck(
    client: TestClient,
) -> None:
    """preview -> create -> confirm in ONE caller-owned transaction; the
    RECOMPUTE_OBJECTS Job is created by the pipeline and the REAL worker
    completes it; the QC item then moves to the recheck lane."""
    svc = _svc()
    with _session() as session:
        seeded = _seed_occurrence_issue(session, with_role_b=True)
        item = seeded["item"]
        result = bridge.run_correction_chain(
            session,
            item,
            workspace_id=WS,
            managed_root=str(svc.managed_root),
        )
        assert result.status == "applied"
        assert result.created is True
        assert result.recompute_job_id is not None
        assert result.impact.affected_role_ids == [seeded["role_a"].id]
        session.commit()

    # REAL durable worker completes the recompute successor.
    claims = 0
    for _ in range(5):
        claimed = svc.worker.run_once()
        if claimed == 0:
            break
        claims += claimed
    assert claims >= 1

    with _session() as session:
        job = JobRepository(session).get_job(str(result.recompute_job_id))
        assert job.state == "completed"
        # Real read route reflects the honest recompute outcome.
    fetched = client.get(f"{API}/{result.correction_id}")
    assert fetched.status_code == 200
    recompute = fetched.json()["recompute"]
    assert recompute["status"] == "completed"
    assert recompute["progress"] == 100

    # After publish OK the item moves to the recheck lane (acknowledged).
    with _session() as session:
        current = QCItemRepository(session).get(item.id, WS)
        moved = bridge.mark_item_recheck(session, current, workspace_id=WS)
        session.commit()
        assert moved.status == "acknowledged"


def test_chain_replay_never_duplicates_and_is_guarded_after_correction(
    client: TestClient,
) -> None:
    """The derived idempotency key keeps replay on ONE correction row, and a
    SECOND chain attempt after the correction is refused by the stable
    ROLE_CHANGED guard (the item's recorded evidence is stale BY DESIGN after
    the mutation — recheck first, never a silent duplicate correction)."""
    svc = _svc()
    with _session() as session:
        seeded = _seed_occurrence_issue(session)
        item = seeded["item"]
        first = bridge.run_correction_chain(
            session, item, workspace_id=WS, managed_root=str(svc.managed_root)
        )
        session.commit()
        assert first.created is True
        assert first.status == "applied"

        with pytest.raises(QcCorrectionBridgeError) as exc_info:
            bridge.run_correction_chain(
                session, item, workspace_id=WS, managed_root=str(svc.managed_root)
            )
        assert exc_info.value.code == "ROLE_CHANGED"
        session.rollback()

        # Exactly ONE durable correction row was ever created.
        count = session.scalar(
            select(func.count()).select_from(ObjectCorrection)
        )
        assert count == 1


# ── AC (plan test): unaffected artifacts byte-identical ─────────────────────


def test_unaffected_artifacts_byte_identical_after_rerun(
    client: TestClient,
) -> None:
    """Rerun publishes ONLY the affected role's artifacts; role-C artifacts
    (row id + sha256 + managed bytes) stay byte-identical, cross-checked
    against manifest.affected_role_ids."""
    svc = _svc()
    with _session() as session:
        seeded = _seed_occurrence_issue(session, with_role_c=True)
        item = seeded["item"]
        role_a = seeded["role_a"]
        role_c = seeded["role_c"]
        before_c = _artifact_snapshot(session, role_id=role_c.id)
        assert len(before_c) == 2, "role C must have its own old artifacts"
        before_occ_rev = session.get(ObjectOccurrence, seeded["occ_a"].id).revision
        result = bridge.run_correction_chain(
            session, item, workspace_id=WS, managed_root=str(svc.managed_root)
        )
        session.commit()

    for _ in range(5):
        if svc.worker.run_once() == 0:
            break

    with _session() as session:
        # manifest.affected_role_ids == the only role allowed to change.
        correction = session.scalar(
            select(ObjectCorrection).where(ObjectCorrection.id == result.correction_id)
        )
        assert correction is not None
        impact = json.loads(correction.impact_json)
        assert impact["affected_role_ids"] == [role_a.id]

        after_c = _artifact_snapshot(session, role_id=role_c.id)
        assert after_c == before_c  # byte-identical rows (id + sha256)

        # Managed bytes of role C's artifacts unchanged.
        managed = ManagedRoot(svc.managed_root)
        for artifact_id, sha in after_c.items():
            row = session.get(Artifact, artifact_id)
            raw = managed.resolve(row.relative_path).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == sha

        # Affected role's artifacts were recomputed (old association gone).
        old_a = _artifact_snapshot(session, role_id=role_a.id)
        assert set(old_a) != set(), "role A still has artifacts (new ones)"
        # The recompute job published rows under its own job directory.
        rows = session.scalars(
            select(Artifact).where(
                Artifact.relative_path.like(
                    f"artifacts/{WS}/image/{result.recompute_job_id}/%"
                )
            )
        ).all()
        assert len(rows) >= 1
        # No published artifact belongs to an unaffected role (C).
        for row in rows:
            assoc = session.scalar(
                select(ObjectRoleArtifact.id).where(
                    ObjectRoleArtifact.artifact_id == row.id,
                    ObjectRoleArtifact.role_id == role_c.id,
                )
            )
            assert assoc is None, "unaffected role C must not be republished"
        # The targeted mutation applied on the OCCURRENCE (CAS): review_state
        # rejected + revision bumped exactly once by the pipeline.
        occ_after = session.get(ObjectOccurrence, seeded["occ_a"].id)
        assert occ_after.review_state == "rejected"
        assert occ_after.revision == before_occ_rev + 1


# ── retry: existing corrections/{id}/recompute/retry — NO generic retry ─────


def test_retry_uses_existing_recompute_retry_route(client: TestClient, monkeypatch: Any) -> None:
    """Terminal failed/cancelled recompute is retried through the EXISTING
    ``POST /corrections/{id}/recompute/retry`` successor route — the bridge
    adds no generic retry and no new route."""
    import app.services.object_correction as correction_service

    svc = _svc()
    with _session() as session:
        seeded = _seed_occurrence_issue(session, with_role_b=True)
        item = seeded["item"]
        result = bridge.run_correction_chain(
            session, item, workspace_id=WS, managed_root=str(svc.managed_root)
        )
        session.commit()
        job_id = result.recompute_job_id
        assert job_id is not None

    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        correction_service,
        "PHASE_HOOK",
        lambda phase: (entered.set(), release.wait(10)),
    )
    worker_thread = threading.Thread(target=svc.worker.run_once)
    worker_thread.start()
    assert entered.wait(timeout=10)
    client.post(
        f"{API}/{result.correction_id}/cancel",
        json={"revision": result.applied_revision},
    )
    release.set()
    worker_thread.join(timeout=30)
    monkeypatch.setattr(correction_service, "PHASE_HOOK", None)
    with _session() as session:
        assert JobRepository(session).get_job(str(job_id)).state == "cancelled"

    # The REAL existing retry route (successor job; idempotent).
    retried = client.post(f"{API}/{result.correction_id}/recompute/retry")
    assert retried.status_code == 200
    successor_id = retried.json()["recompute"]["job_id"]
    assert successor_id != job_id
    for _ in range(5):
        if svc.worker.run_once() == 0:
            break
    with _session() as session:
        assert JobRepository(session).get_job(str(successor_id)).state == "completed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.predecessor_job_id == str(job_id))
            )
            == 1
        )
    # The retry path is part of the frozen corrections router (EXISTS).
    paths = client.get("/openapi.json").json()["paths"]
    retry_paths = [
        p for p in paths if "/corrections/" in p and "recompute/retry" in p
    ]
    assert len(retry_paths) == 2  # with and without trailing slash


# ── ROLE_CHANGED stale-guard ────────────────────────────────────────────────


def test_role_changed_guard_blocks_before_pipeline(client: TestClient) -> None:
    """Evidence captured at item-creation time is compared against the
    CURRENT anchor revisions; a changed role/occurrence revision => stable
    ROLE_CHANGED guard (recheck before correction, GAP-8)."""
    with _session() as session:
        seeded = _seed_occurrence_issue(session)
        item = seeded["item"]
        role_a = seeded["role_a"]
        # anchor edits land AFTER the item evidence was recorded
        ObjectIntelligenceRepository(session).update_role(
            WS, role_a.id, role_a.revision, description="corrected elsewhere"
        )
        session.commit()
        with pytest.raises(QcCorrectionBridgeError) as exc_info:
            bridge.run_correction_chain(
                session, item, workspace_id=WS,
                managed_root=str(_svc().managed_root),
            )
        assert exc_info.value.code == "ROLE_CHANGED"
        assert "revision" in exc_info.value.message


def test_role_changed_at_confirm_time_maps_pipeline_conflict(
    client: TestClient,
) -> None:
    """The occurrence anchor changes BETWEEN preview/create and confirm: the
    bridge translates the pipeline's stale-CAS answer to the stable
    ROLE_CHANGED guard (never a silent retry / never a raw 5xx escaping the
    service layer); the HTTP layer's own stable CAS semantics (stale
    correction revision -> 409) stay untouched."""
    svc = _svc()
    with _session() as session:
        seeded = _seed_occurrence_issue(session)
        item = seeded["item"]
        occ_a = seeded["occ_a"]
        payload = bridge.build_correction_request(session, item, workspace_id=WS)
    created = client.post(API, json=payload)
    assert created.status_code == 201
    correction_id = created.json()["correction"]["id"]
    revision = created.json()["correction"]["revision"]

    # The HTTP layer's OWN stable CAS semantics are untouched: confirming
    # with a stale CORRECTION revision answers 409 (S08-T05 contract) while
    # the anchors are still intact.
    stale_revision = revision + 99
    confirmed = client.post(
        f"{API}/{correction_id}/confirm", json={"revision": stale_revision}
    )
    assert confirmed.status_code == 409
    with _session() as session:
        from app.persistence.models import ObjectCorrection as _OC

        row = session.get(_OC, correction_id)
        assert row is not None and row.status == "pending"

    with _session() as session:
        # The anchor occurrence is edited through the REAL CAS path.
        ObjectIntelligenceRepository(session).update_occurrence(
            WS, seeded["role_a"].id, occ_a.id, occ_a.revision, bbox_x=11
        )
        session.commit()

    # Bridge confirm wrapper -> stable ROLE_CHANGED guard (pre-check on the
    # item's recorded evidence + pipeline conflict translation).
    with _session() as session:
        with pytest.raises(QcCorrectionBridgeError) as exc_info:
            bridge.confirm_correction_for_item(
                session,
                item,
                workspace_id=WS,
                correction_id=correction_id,
                revision=revision,
                managed_root=str(svc.managed_root),
            )
        assert exc_info.value.code == "ROLE_CHANGED"
        session.rollback()


# ── AC2: no whole-project rerun ─────────────────────────────────────────────


def test_no_whole_project_rerun_anywhere(client: TestClient) -> None:
    """No 'rerun all' surface exists: the bridge maps per-item only, the
    qc-items surface is GET-only and the corrections router exposes no bulk
    rerun endpoint (the only retry POST is the pre-existing recompute/retry
    successor)."""
    bridge_source = (REPO_ROOT / "app/services/qc_correction_bridge.py").read_text(
        encoding="utf-8"
    )
    assert "@router" not in bridge_source, "bridge must not define routes"
    for forbidden in (
        "rerun_all",
        "rerun_all_",
        "whole_project",
        "rerun_project",
        "RERUN_ALL",
        "recompute_all",
        "RECOMPUTE_ALL",
    ):
        assert forbidden not in bridge_source, f"whole-project rerun symbol {forbidden!r}"
    corrections_source = (REPO_ROOT / "app/api/routes/object_correction.py").read_text(
        encoding="utf-8"
    )
    retry_posts = [
        line.strip()
        for line in corrections_source.splitlines()
        if "@router.post" in line and "recompute/retry" in line
    ]
    assert len(retry_posts) == 2  # only the frozen successor route variants
    qc_items_source = (REPO_ROOT / "app/api/routes/qc_items.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"@router\.(post|put|patch|delete)\b", qc_items_source)


# ── AC3: orchestrator auto-resolve after recheck (T03F consumed) ────────────


def _seed_attach_evidence(
    session, *, pid: str, vid: str, variant: str
) -> str:
    """Completed ATTACH_ORIGINAL_AUDIO job (T03E envelope) — the SAME
    repository authority T03G uses.  variant='blocker' => source audio with
    missing output; variant='no_audio' => terminal NO_AUDIO_PRESENT."""
    from app.persistence.models import JobStep as _JobStep

    if variant == "blocker":
        checkpoint = {
            "schema_version": 1,
            "status": "OK",
            "source_audio_present": True,
            "source_audio_codec": "aac",
            "source_audio_duration": 12.0,
            "output_audio_codec": None,
            "output_audio_duration": None,
            "audio_time_base": None,
            "video_codec": "h264",
            "source_sha256": "b" * 64,
            "source_size_bytes": 2048,
        }
        published: dict[str, Any] = {
            "no_audio_present": False,
            "artifact_id": None,
            "final_rel": None,
            "sha256": None,
            "size_bytes": None,
            "status": "output_missing",
        }
    else:
        checkpoint = {
            "schema_version": 1,
            "status": "NO_AUDIO_PRESENT",
            "mode": None,
            "source_sha256": "a" * 64,
            "source_size_bytes": 1024,
            "source_audio_codec": None,
            "source_audio_duration": None,
            "output_audio_codec": None,
            "output_audio_duration": None,
            "audio_time_base": None,
            "video_codec": "h264",
        }
        published = {
            "no_audio_present": True,
            "artifact_id": None,
            "final_rel": None,
            "sha256": None,
            "size_bytes": None,
            "status": "NO_AUDIO_PRESENT",
        }
    repo = JobRepository(session)
    record = repo.create_job(
        workspace_id=WS,
        job_type="ATTACH_ORIGINAL_AUDIO",
        owner_type="video_item",
        owner_id=vid,
        input_manifest={
            "schema_version": 1,
            "workspace_id": WS,
            "project_id": pid,
            "video_item_id": vid,
            "source_artifact_id": None,
            "source_sha256": "",
            "generation": "1",
        },
        idempotency_key=f"ATTACH_ORIGINAL_AUDIO:video_item:{vid}:{variant}:{'d' * 64}:1",
        input_generation="1",
        steps=[StepInput(step_code="attach_original_audio", position=0, step_type="sync")],
        actor="api",
    )
    step_row = session.get(_JobStep, repo.list_steps(record.id)[0].id)
    for target in ("ready", "running"):
        current = session.get(_JobStep, step_row.id)
        repo.transition_step(
            current.id, target, actor="system",
            expected_revision=current.revision, fence_token="seed-token",
        )
    current_step = session.get(_JobStep, step_row.id)
    repo.record_attempt(
        job_id=record.id,
        step_id=current_step.id,
        step_code="attach_original_audio",
        attempt=1,
        worker_id="seed-worker",
        fence_token="seed-token",
        result={
            "source": {
                "artifact_id": None,
                "relative_path": "",
                "sha256": "",
                "size_bytes": None,
            },
            "remux": {"checkpoint": checkpoint},
            "published": published,
        },
    )
    current_step2 = session.get(_JobStep, step_row.id)
    repo.transition_step(
        current_step2.id, "completed", actor="system",
        expected_revision=current_step2.revision, fence_token="seed-token",
    )
    job_running = repo.get_job(record.id)
    repo.transition_job(
        record.id, "running", actor="system", expected_revision=job_running.revision
    )
    job_running2 = repo.get_job(record.id)
    repo.transition_job(
        record.id, "completed", actor="system",
        expected_revision=job_running2.revision,
    )
    session.commit()
    return record.id


def test_item_marked_recheck_then_orchestrator_auto_resolves(
    client: TestClient,
) -> None:
    """AC3 lifecycle consumption: after publish OK the item is in the recheck
    lane (acknowledged) and the T03F orchestrator AUTO-RESOLVES it on the
    next fresh recheck run that no longer reports the window — all through
    real persisted evidence + the real orchestrator."""
    with _session() as session:
        _seed_video(session, pid=P1, vid=V2)
        session.commit()
    # Phase 1: persisted audio evidence reports the issue -> blocker item.
    with _session() as session:
        _seed_attach_evidence(session, pid=P1, vid=V2, variant="blocker")
        args = compose_check_run_args(
            session,
            workspace_id=WS,
            project_id=P1,
            video_item_id=V2,
            scope=SCOPE_AUDIO,
        )
    summary1 = run_full_check_set(
        _session(),
        workspace_id=WS,
        project_id=P1,
        video_item_id=V2,
        detector_args=args,
        detectors=["audio_missing"],
        deadline_sec=120,
        capture_cap_bytes=1_000_000,
    )
    assert summary1.created == 1
    with _session() as session:
        audit_item = QCItemRepository(session).list(WS, video_item_id=V2)[0][0]
        assert audit_item.status == "open"
        assert audit_item.reason_code == "audio_missing"
        # publish OK -> recheck lane (bridge lifecycle consume)
        moved = bridge.mark_item_recheck(session, audit_item, workspace_id=WS)
        session.commit()
        assert moved.status == "acknowledged"

    # The T03G submit authority queues the durable recheck run (real job).
    with _session() as session:
        result = bridge.submit_recheck_run(
            _svc().session_factory,
            moved,
            workspace_id=WS,
            scope=SCOPE_AUDIO,
            detector_args=args,
        )
        assert result.job_id

    # Phase 2: fresh persisted evidence no longer reports the window.
    with _session() as session:
        _seed_attach_evidence(session, pid=P1, vid=V2, variant="no_audio")
        args2 = compose_check_run_args(
            session,
            workspace_id=WS,
            project_id=P1,
            video_item_id=V2,
            scope=SCOPE_AUDIO,
        )
    summary2 = run_full_check_set(
        _session(),
        workspace_id=WS,
        project_id=P1,
        video_item_id=V2,
        detector_args=args2,
        detectors=["audio_missing"],
        deadline_sec=120,
        capture_cap_bytes=1_000_000,
    )
    assert summary2.resolved_after_recheck == 1
    with _session() as session:
        resolved = QCItemRepository(session).get(moved.id, WS)
        assert resolved.status == "resolved"
        assert resolved.evidence.get("recheck") == "resolved"
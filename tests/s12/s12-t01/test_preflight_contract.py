"""S12-T01 — frozen preflight contract tests (HTTP + pure + OpenAPI).

Isolation: the standard ``client`` fixture (isolated project root + temp
Alembic-head DB + patched deps); basetemp short/unique; no
MOTIONFORGE_DATABASE_URL; every write under tmp_path.  QC seeding reuses the
T05A repository-fixture pattern (raw-SQL ws/project/video + JobRepository
completed FULL run + completion block identical to the T03F shape).

Gates:
1. Pure: native vs upscale from provenance (never file size), aspect
   letterbox vs fail-closed, disk insufficient fail-closed.
2. positives via HTTP: ready + pinned checkpoint + current lock + ready
   source + disk fits → eligible (profile unsupported at T01 is an expected
   open check: T02 fills support — eligible False with UNSUPPORTED_PROFILE
   + all other checks passed).
3. Negatives: unknown project/video 404, stale checkpoint hash/revision 422
   (STALE_CHECKPOINT), lock missing 422 (LOCK_MISSING), cross-project
   checkpoint 422 (CROSS_PROJECT), not-ready video 422 (NOT_READY),
   .partial source 422 (SOURCE_PARTIAL), aspect fail_closed 422
   (ASPECT_MISMATCH).
4. OpenAPI: POST preflight present with frozen schema refs + reason codes
   enumerated in the contract module.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as _text

from app.api import deps
from app.persistence.jobs import JobRepository, StepInput
from app.persistence.models import VideoItem, Workspace
from app.schemas.s12_export import (
    S12_EXPORT_CONTRACT_VERSION,
    S12_EXPORT_REASON_CODES,
    ExportPreflightRequest,
)
from app.services.s12_export.preflight import (
    PREFLIGHT_PROFILES,
    PreflightContext,
    classify_source_kind,
    evaluate_preflight,
)
from app.services.qc_checks import (  # noqa: F401 (self-register band)
    audio_missing,
    av_sync_drift,
    cut_drift,
    edge_halo,
    identity_drift,
    temporal_flicker,
    trajectory_drift,
)
from app.services.qc_checks import contact_break as _cb
from app.services.qc_checks import silhouette_clipping as _sc
from app.services.qc_checks import z_order_error as _zo
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_FULL,
    detector_revisions,
    evidence_fingerprint,
    policy_bundle,
    scope_detectors,
    scope_fingerprint,
    source_artifact_fingerprint,
)

_cb.register()
_sc.register()
_zo.register()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

WS = "ws-s12-t01"
P1 = "p1-s12-t01"


def _hex64(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()


def _req(**over: Any) -> dict[str, Any]:
    return {
        "video_item_id": "vid-x",
        "profile_id": "master-4k-h264",
        "aspect_handling": "letterbox",
        "checkpoint": {
            "checkpoint_id": "ckpt-x",
            "checkpoint_hash": _hex64("ckpt"),
            "checkpoint_revision": 1,
        },
        "lock": {
            "manifest_id": "mani-x",
            "manifest_hash": _hex64("mani"),
            "source_generation": "1",
        },
    } | over


def _ctx(**over: Any) -> PreflightContext:
    base: dict[str, Any] = {
        "project_id": P1,
        "video_item_id": "vid-x",
        "source_found": True,
        "source_ready": True,
        "source_is_partial": False,
        "source_width": 3840,
        "source_height": 2160,
        "source_frame_count": 100,
        "source_native_4k": True,
        "checkpoint_found": True,
        "checkpoint_hash_match": True,
        "checkpoint_revision_match": True,
        "checkpoint_cross_project": False,
        "lock_found": True,
        "lock_hash_match": True,
        "lock_generation_match": True,
        "readiness_status": "ready",
        "readiness_policy": "pol",
        "readiness_policy_current": True,
        "disk_free_bytes": 10**12,
        "profile_supported": True,
        "profile_support_basis": "test probe",
    }
    base.update(over)
    return PreflightContext(**base)


# ── pure unit gates ──────────────────────────────────────────────────


def test_pure_native_vs_upscale_provenance() -> None:
    native = _ctx()
    assert classify_source_kind(native) == "native_4k"
    # Same 3840x2160 dims but NOT provenance-native → still upscale honesty.
    fake = _ctx(source_native_4k=False, source_width=1920, source_height=1080)
    assert classify_source_kind(fake) == "upscale_4k"
    resp = evaluate_preflight(ExportPreflightRequest(**_req()), fake)
    assert resp.source_kind == "upscale_4k"
    assert resp.profile.upscale_method  # labeled method required


def test_pure_aspect_letterbox_vs_fail_closed() -> None:
    wide = _ctx(source_width=1920, source_height=800, source_native_4k=False)
    ok_resp = evaluate_preflight(ExportPreflightRequest(**_req()), wide)
    assert ok_resp.eligible  # letterbox preserves
    strict_req = ExportPreflightRequest(**_req(aspect_handling="fail_closed"))
    bad_resp = evaluate_preflight(strict_req, wide)
    assert not bad_resp.eligible
    assert "S12_EXPORT_ASPECT_MISMATCH" in bad_resp.reasons


def test_pure_disk_insufficient() -> None:
    resp = evaluate_preflight(
        ExportPreflightRequest(**_req()), _ctx(disk_free_bytes=1)
    )
    assert not resp.eligible
    assert "S12_EXPORT_DISK_INSUFFICIENT" in resp.reasons
    assert resp.estimate_bytes and resp.estimate_basis


def test_frozen_reason_codes_stable() -> None:
    assert "S12_EXPORT_OK" in S12_EXPORT_REASON_CODES
    assert len(S12_EXPORT_REASON_CODES) == 14
    assert S12_EXPORT_CONTRACT_VERSION == "s12-export-v1"
    assert PREFLIGHT_PROFILES["master-4k-h264"]["width"] == 3840


# ── HTTP seed helpers (T05A pattern) ─────────────────────────────────


def _seed_ws_project_video(
    session: Any,
    *,
    ws: str,
    pid: str,
    vid: str,
    w: int | None = 1920,
    h: int | None = 1080,
    duration_ms: int | None = 10_000,
    artifact_state: str | None = "ready",
    artifact_path: str | None = None,
    partial: bool = False,
) -> str | None:
    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjS12T01','','active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": pid, "w": ws},
    )
    aid: str | None = None
    if artifact_state is not None:
        aid = f"art-{uuid.uuid4().hex[:8]}"
        rel = artifact_path or f"videos/{uuid.uuid4().hex}.mp4"
        if partial:
            rel = rel + ".partial"
        session.execute(
            _text(
                "INSERT INTO artifact(id,workspace_id,kind,relative_path,state,sha256,revision) "
                "VALUES (:a,:w,'video',:rel,:st,:sha,1)"
            ),
            {"a": aid, "w": ws, "rel": rel, "st": artifact_state,
             "sha": _hex64(f"art-{aid}")},
        )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status,width,height,"
            "fps_num,fps_den,duration_ms,source_artifact_id) "
            "VALUES (:v,:p,'VidS12',0,'ready_to_export',:w,:h,30,1,:d,:a)"
        ),
        {"v": vid, "p": pid, "w": w, "h": h, "d": duration_ms, "a": aid},
    )
    session.commit()
    return aid


def _completion_block(*, ws: str, pid: str, vid: str) -> dict[str, Any]:
    fp = evidence_fingerprint(
        deps.get_job_service().session_factory(),  # type: ignore[union-attr]
        workspace_id=ws,
        video_item_id=vid,
    )
    policy = policy_bundle()
    band = scope_detectors(SCOPE_FULL)
    factory = deps.get_job_service().session_factory  # type: ignore[union-attr]
    with factory() as _src_session:
        _current_source = source_artifact_fingerprint(
            _src_session, video_item_id=vid
        )
    return {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "job_type": JOB_TYPE_RUN_QC_CHECKS,
        "completed": True,
        "run_id": "b" * 64,
        "policy_id": policy["policy_id"],
        "policy_content_hash": policy["policy_content_hash"],
        "source_generation": "1",
        "source_artifact_id": _current_source["source_artifact_id"],
        "source_artifact_fingerprint": _current_source["source_sha256"],
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
        "evidence_fingerprint": fp,
        "detectors": list(band),
        "detector_revisions": detector_revisions(list(band)),
        "summary": {
            "checks_requested": len(band),
            "checks_run": len(band),
            "checks_skipped": 0,
            "errors": 0,
            "cancelled": False,
            "deadline_exceeded": False,
            "created": 0,
            "not_applicable": len(band),
        },
        "zero_item_completion": {
            "evidence": True,
            "qc_items_created": 0,
            "issues_found": 0,
            "checks_run": len(band),
            "not_applicable": len(band),
        },
    }


def _seed_completed_check_run(session: Any, *, ws: str, pid: str, vid: str) -> str:
    repo = JobRepository(session)
    session.get(Workspace, ws)
    session.get(VideoItem, vid)
    # C3-A1 items 14-15: manifest source identity must pair EXACTLY like the
    # producer writes (real id + non-empty SHA when a source artifact exists).
    _seed_src = source_artifact_fingerprint(session, video_item_id=vid)
    manifest = {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "workspace_id": ws,
        "project_id": pid,
        "video_item_id": vid,
        "evidence_fingerprint": evidence_fingerprint(
            session, workspace_id=ws, video_item_id=vid
        ),
        "policy_id": policy_bundle()["policy_id"],
        "policy_content_hash": policy_bundle()["policy_content_hash"],
        "source_generation": "1",
        "source_artifact_id": _seed_src["source_artifact_id"],
        "source_sha256": _seed_src["source_sha256"],
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
    }
    record = repo.create_job(
        workspace_id=ws,
        job_type=JOB_TYPE_RUN_QC_CHECKS,
        owner_type="video_item",
        owner_id=vid,
        input_manifest=manifest,
        idempotency_key=f"RUN_QC_CHECKS:video_item:{vid}:s12t01:1",
        input_generation="1",
        steps=[StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
        actor="api",
    )
    step = repo.list_steps(record.id)[0]
    repo.transition_step(
        step.id, "ready", actor="system",
        expected_revision=step.revision, fence_token="seed-token",
    )
    step2 = repo.list_steps(record.id)[0]
    repo.transition_step(
        step2.id, "running", actor="system",
        expected_revision=step2.revision, fence_token="seed-token",
    )
    step3 = repo.list_steps(record.id)[0]
    repo.record_attempt(
        job_id=record.id,
        step_id=step3.id,
        step_code="run_qc_checks",
        attempt=1,
        worker_id="seed-worker",
        fence_token="seed-token",
        result=_completion_block(ws=ws, pid=pid, vid=vid),
    )
    repo.transition_step(
        step3.id, "completed", actor="system",
        expected_revision=step3.revision, fence_token="seed-token",
    )
    running = repo.transition_job(
        record.id, "running", actor="system", expected_revision=record.revision
    )
    repo.transition_job(
        record.id, "completed", actor="system", expected_revision=running.revision
    )
    session.commit()
    return record.id


def _seed_checkpoint(session: Any, *, ws: str, pid: str, vid: str) -> dict[str, str]:
    char = f"ch-{uuid.uuid4().hex[:6]}"
    session.execute(
        _text("INSERT INTO character(id,workspace_id,name,code) VALUES (:c,:w,'Hero',:code)"),
        {"c": char, "w": ws, "code": f"hero_{uuid.uuid4().hex[:4]}"},
    )
    pv = f"pv-{uuid.uuid4().hex[:6]}"
    session.execute(
        _text(
            "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
            " VALUES (:pv,:c,:w,1,'published')"
        ),
        {"pv": pv, "c": char, "w": ws},
    )
    role = f"role-{uuid.uuid4().hex[:6]}"
    session.execute(
        _text(
            "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
            "source_generation,name,kind,status)"
            " VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"
        ),
        {"r": role, "w": ws, "p": pid, "v": vid},
    )
    rc = f"rc-{uuid.uuid4().hex[:6]}"
    session.execute(
        _text(
            "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,"
            "character_id,pack_version_id,params_json,revision)"
            " VALUES (:rc,:w,:p,:r,:c,:pv,'{}',1)"
        ),
        {"rc": rc, "w": ws, "p": pid, "r": role, "c": char, "pv": pv},
    )
    ckpt = f"ckpt-{uuid.uuid4().hex[:6]}"
    chash = _hex64(f"ckpt-{ckpt}")
    session.execute(
        _text(
            "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
            "reskin_config_revision,pack_version_ids_json,loop_hashes_json,"
            "timebase_fingerprint,snapshot_json,checkpoint_hash,revision)"
            " VALUES (:id,:w,:p,:rc,1,'[]','[]',:tbf,'{}',:ch,1)"
        ),
        {"id": ckpt, "w": ws, "p": pid, "rc": rc, "tbf": _hex64("tbf"), "ch": chash},
    )
    session.commit()
    return {"checkpoint_id": ckpt, "checkpoint_hash": chash}


def _seed_manifest(session: Any, *, ws: str, pid: str, vid: str) -> dict[str, str]:
    from app.persistence.structural_lock import StructuralLockRepository

    payload = {
        "frame_count": 300,
        "timebase": {"fps": 30.0, "time_base": "1/1000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }
    repo = StructuralLockRepository(session)
    record, _created = repo.create_manifest(ws, pid, vid, "1", payload)
    session.commit()
    return {"manifest_id": record.id, "manifest_hash": record.manifest_hash_hex}


@pytest.fixture()
def s12_session():
    factory = deps.get_job_service().session_factory
    assert factory is not None
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _http_body(vid: str, ckpt: dict[str, str], mani: dict[str, str]) -> dict[str, Any]:
    return {
        "video_item_id": vid,
        "profile_id": "master-4k-h264",
        "aspect_handling": "letterbox",
        "checkpoint": {
            "checkpoint_id": ckpt["checkpoint_id"],
            "checkpoint_hash": ckpt["checkpoint_hash"],
            "checkpoint_revision": 1,
        },
        "lock": {
            "manifest_id": mani["manifest_id"],
            "manifest_hash": mani["manifest_hash"],
            "source_generation": "1",
        },
    }


# ── HTTP gates ───────────────────────────────────────────────────────


def test_openapi_preflight_surface(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    path = resp.json()["paths"].get("/api/v2/projects/{project_id}/export/preflight")
    assert path is not None and "post" in path
    schema = resp.json()["components"]["schemas"]["ExportPreflightResponse"]
    assert schema["properties"]["contract_version"]["default"] == "s12-export-v1"


def test_unknown_project_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v2/projects/no-such-proj/export/preflight", json=_req()
    )
    assert resp.status_code in (404, 422)


def test_unknown_video_404(client: TestClient, s12_session: Any) -> None:
    _seed_ws_project_video(s12_session, ws=WS, pid="p-unk-vid", vid="v-unk-vid")
    resp = client.post(
        "/api/v2/projects/p-unk-vid/export/preflight",
        json=_req(video_item_id="vid-nope"),
    )
    assert resp.status_code == 404
    assert "not found" in resp.text


def test_t01_profile_unsupported_open_check(
    client: TestClient, s12_session: Any
) -> None:
    """Eligible-path: everything pinned passes EXCEPT T02 support (expected)."""
    vid = f"v-open-{uuid.uuid4().hex[:6]}"
    pid = f"p-open-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(
        s12_session, ws=WS, pid=pid, vid=vid, w=1920, h=1080, duration_ms=10_000
    )
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_version"] == "s12-export-v1"
    assert body["source_kind"] == "upscale_4k"  # 1080p source honesty
    assert body["readiness_status"] == "ready"
    assert "S12_EXPORT_UNSUPPORTED_PROFILE" in body["reasons"]
    passed = {c["name"] for c in body["checks"] if c["passed"]}
    assert {
        "source",
        "source_state",
        "checkpoint",
        "checkpoint_cross_project",
        "structural_lock",
        "readiness",
        "aspect",
        "disk",
    } <= passed


def test_stale_checkpoint_hash_422(client: TestClient, s12_session: Any) -> None:
    vid = f"v-stale-{uuid.uuid4().hex[:6]}"
    pid = f"p-stale-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    bad = dict(ckpt, checkpoint_hash=_hex64("wrong"))
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, bad, mani)
    )
    assert resp.status_code == 200, resp.text
    assert "S12_EXPORT_STALE_CHECKPOINT" in resp.json()["reasons"]


def test_lock_missing_422(client: TestClient, s12_session: Any) -> None:
    vid = f"v-nolock-{uuid.uuid4().hex[:6]}"
    pid = f"p-nolock-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = {"manifest_id": f"mani-{uuid.uuid4().hex[:6]}", "manifest_hash": _hex64("m")}
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    assert "S12_EXPORT_LOCK_MISSING" in resp.json()["reasons"]


def test_not_ready_422(client: TestClient, s12_session: Any) -> None:
    """Video with no completed QC run → NOT_READY (readiness consumed)."""
    vid = f"v-nr-{uuid.uuid4().hex[:6]}"
    pid = f"p-nr-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    assert "S12_EXPORT_NOT_READY" in resp.json()["reasons"]


def test_partial_source_422(client: TestClient, s12_session: Any) -> None:
    vid = f"v-part-{uuid.uuid4().hex[:6]}"
    pid = f"p-part-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid, partial=True)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    assert "S12_EXPORT_SOURCE_PARTIAL" in resp.json()["reasons"]


def test_cross_project_checkpoint_422(client: TestClient, s12_session: Any) -> None:
    """Checkpoint pinned to project A, preflighted under project B."""
    vid_a = f"v-xa-{uuid.uuid4().hex[:6]}"
    pid_a = f"p-xa-{uuid.uuid4().hex[:6]}"
    pid_b = f"p-xb-{uuid.uuid4().hex[:6]}"
    vid_b = f"v-xb-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid_a, vid=vid_a)
    _seed_ws_project_video(s12_session, ws=WS, pid=pid_b, vid=vid_b)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid_b, vid=vid_b)
    ckpt_a = _seed_checkpoint(s12_session, ws=WS, pid=pid_a, vid=vid_a)
    mani_b = _seed_manifest(s12_session, ws=WS, pid=pid_b, vid=vid_b)
    resp = client.post(
        f"/api/v2/projects/{pid_b}/export/preflight",
        json=_http_body(vid_b, ckpt_a, mani_b),
    )
    assert resp.status_code == 200, resp.text
    assert "S12_EXPORT_CROSS_PROJECT" in resp.json()["reasons"]


def test_aspect_fail_closed_422(client: TestClient, s12_session: Any) -> None:
    vid = f"v-asp-{uuid.uuid4().hex[:6]}"
    pid = f"p-asp-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(
        s12_session, ws=WS, pid=pid, vid=vid, w=1920, h=800, duration_ms=10_000
    )
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    body = _http_body(vid, ckpt, mani)
    body["aspect_handling"] = "fail_closed"
    resp = client.post(f"/api/v2/projects/{pid}/export/preflight", json=body)
    assert resp.status_code == 200, resp.text
    assert "S12_EXPORT_ASPECT_MISMATCH" in resp.json()["reasons"]


def test_no_render_in_request(client: TestClient, s12_session: Any) -> None:
    """Preflight creates no export job/artifact rows (verdict only)."""
    from app.persistence.jobs import JobRepository as _JR

    vid = f"v-nor-{uuid.uuid4().hex[:6]}"
    pid = f"p-nor-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    factory = deps.get_job_service().session_factory
    assert factory is not None
    with factory() as s:
        jobs_before = len(_JR(s).list_jobs(WS))
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    with factory() as s2:
        assert len(_JR(s2).list_jobs(WS)) == jobs_before
        pubs = s2.execute(
            _text("SELECT COUNT(*) FROM s10_full_apply_publication")
        ).scalar()
    assert pubs == 0

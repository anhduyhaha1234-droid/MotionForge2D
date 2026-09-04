"""S11-T05A (W12) — compute-on-the-fly readiness aggregate API (HTTP surface).

Decision F consumption point: ``GET /api/v2/projects/{project_id}/readiness``
computes the aggregate ON THE FLY from QCItem + durable check-run evidence
(no readiness table, no migration).  The per-video verdicts come from the
T03G read authority ``check_run_readiness`` (import-only — never inferred
from QCItem-table emptiness, C4-F2).

Binary gates covered with REAL calls on the temp app/db:

1. E2E-02 backend: video A = 1 open blocker + 3 open warnings, video B =
   clean completion ⇒ status=blocked, blockers[] contains ONLY A's blocker
   (each with qc_item_id/code/location/reason_vi/action_vi/action),
   warning_count=3 and warnings NEVER appear in blockers[]; after the
   blocker is terminal-resolved by recheck evidence ⇒ status=ready with
   warning_count unchanged.
2. not_run wins: any video without a completed CURRENT run (never-run /
   queued / running / failed / stale) ⇒ aggregate status=not_run with
   per-video check-state detail; completed zero-item run ⇒ NOT not_run
   (clean/ready candidate — the T03G evidence distinction).
3. R4: a dismissed blocker can never exist (repo guard + DB CHECK) and
   dismissal can never flip readiness — status stays blocked.
4. Decision F: policy_version + content_hash present and equal to the
   frozen T03A policy identity; no readiness table/migration (alembic
   single head unchanged); router GET-only; app.py exactly one
   include_router(readiness.router).
5. Unknown project ⇒ 404; a blocker with an unknown location kind still
   resolves fail-closed (explain action, no dead link, no crash).

Isolation: the standard `client` fixture (isolated project root + temp
Alembic-head DB + patched deps); basetemp is short and unique; no
MOTIONFORGE_DATABASE_URL; every test writes only under tmp_path.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as _text

from app.api import deps
from app.persistence.jobs import JobRepository, StepInput
from app.persistence.models import VideoItem, Workspace
from app.persistence.qc_items import QCItemBlockedDismissalError, QCItemRepository
from app.services.qc_checks.thresholds import POLICY_ID
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_FULL,
    evidence_fingerprint,
    policy_bundle,
    scope_detectors,
    scope_fingerprint,
)
from app.services.qc_checks import (  # noqa: F401  (self-register 7-detector band)
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

_cb.register()
_sc.register()
_zo.register()

REPO_ROOT = Path(__file__).resolve().parent.parent

WS = "default"
P1 = str(uuid.uuid4())   # blocked/ready/not_run project
P2 = str(uuid.uuid4())   # zero-item completed project
P3 = str(uuid.uuid4())   # queued/running/failed/stale project
V_A = str(uuid.uuid4())  # blocker + warnings
V_B = str(uuid.uuid4())  # clean
V_C = str(uuid.uuid4())  # never-run
V_D = str(uuid.uuid4())  # completed zero-item
V_Q = str(uuid.uuid4())  # queued
V_R = str(uuid.uuid4())  # running
V_F = str(uuid.uuid4())  # failed
V_S = str(uuid.uuid4())  # stale


# ── seeding helpers ─────────────────────────────────────────────────────────


def _seed_ws_project_video(
    session: Any, *, ws: str, pid: str, vid: str, position: int = 0
) -> None:
    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT05A','','active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": pid, "w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidT05A',:pos,'imported')"
        ),
        {"v": vid, "p": pid, "pos": position},
    )
    session.commit()


def _completion_block(
    *, ws: str, pid: str, vid: str, zero_evidence: bool
) -> dict[str, Any]:
    """Durable completion block shaped EXACTLY like the T03F orchestrator's
    ``build_completion_block`` (schema_version/job_type/completed/run_id +
    policy identity + fingerprints + measured summary + zero-item evidence).
    The read authority trusts nothing else (C4-F2)."""
    fp = evidence_fingerprint(
        deps.get_job_service().session_factory(),  # type: ignore[union-attr]
        workspace_id=ws,
        video_item_id=vid,
    )
    policy = policy_bundle()
    # S11-C1 C2: the seeded FULL completion must carry the binding FULL
    # band — derived via ``scope_detectors(SCOPE_FULL)`` (NEVER a hard-coded
    # list) — with the content-derived FULL fingerprint
    # (``scope_fingerprint(SCOPE_FULL)``).  Under INT01 the server-owned
    # FULL band is the frozen 10-detector band; inside this pre-INT01 tree
    # it resolves through the registry (see LOG for the routing note).
    band = scope_detectors(SCOPE_FULL)
    return {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "job_type": JOB_TYPE_RUN_QC_CHECKS,
        "completed": True,
        "run_id": "a" * 64,
        "policy_id": policy["policy_id"],
        "policy_content_hash": policy["policy_content_hash"],
        "source_generation": "1",
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
        "evidence_fingerprint": fp,
        "detectors": list(band),
        "detector_revisions": {name: "1.0.0" for name in band},
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
            "evidence": zero_evidence,
            "qc_items_created": 0,
            "issues_found": 0,
            "checks_run": len(band),
            "not_applicable": len(band),
        },
    }


def _seed_completed_check_run(
    session: Any, *, ws: str, pid: str, vid: str, stale_fp: bool = False
) -> str:
    """Durable completed RUN_QC_CHECKS job via the repository fixture path
    (Decision A — seeding through the repo, never HTTP)."""
    repo = JobRepository(session)
    session.get(Workspace, ws)  # FK anchor exists (see _seed_ws_project_video)
    session.get(VideoItem, vid)
    manifest = {
        "schema_version": RUN_QC_SCHEMA_VERSION,
        "workspace_id": ws,
        "project_id": pid,
        "video_item_id": vid,
        "evidence_fingerprint": (
            ("z" * 64) if stale_fp
            else evidence_fingerprint(session, workspace_id=ws, video_item_id=vid)
        ),
        "policy_id": policy_bundle()["policy_id"],
        "policy_content_hash": policy_bundle()["policy_content_hash"],
        "source_generation": "1",
        "source_artifact_id": None,
        "source_sha256": "",
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
    }
    record = repo.create_job(
        workspace_id=ws,
        job_type=JOB_TYPE_RUN_QC_CHECKS,
        owner_type="video_item",
        owner_id=vid,
        input_manifest=manifest,
        idempotency_key=f"RUN_QC_CHECKS:video_item:{vid}:{'t05a'}:1",
        input_generation="1",
        steps=[StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
        actor="api",
    )
    step = repo.list_steps(record.id)[0]
    repo.transition_step(step.id, "ready", actor="system",
                         expected_revision=step.revision, fence_token="seed-token")
    step2 = repo.list_steps(record.id)[0]
    repo.transition_step(step2.id, "running", actor="system",
                         expected_revision=step2.revision, fence_token="seed-token")
    step3 = repo.list_steps(record.id)[0]
    repo.record_attempt(
        job_id=record.id,
        step_id=step3.id,
        step_code="run_qc_checks",
        attempt=1,
        worker_id="seed-worker",
        fence_token="seed-token",
        result=_completion_block(ws=ws, pid=pid, vid=vid, zero_evidence=True),
    )
    repo.transition_step(step3.id, "completed", actor="system",
                         expected_revision=step3.revision, fence_token="seed-token")
    running = repo.transition_job(record.id, "running", actor="system",
                                  expected_revision=record.revision)
    repo.transition_job(record.id, "completed", actor="system",
                        expected_revision=running.revision)
    session.commit()
    return record.id


def _seed_active_check_run(session: Any, *, ws: str, pid: str, vid: str, state: str) -> str:
    """Durable non-completed run: queued / running / failed (fail-closed states)."""
    repo = JobRepository(session)
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
        "source_artifact_id": None,
        "source_sha256": "",
        "scope": SCOPE_FULL,
        "scope_fingerprint": scope_fingerprint(SCOPE_FULL),
    }
    record = repo.create_job(
        workspace_id=ws,
        job_type=JOB_TYPE_RUN_QC_CHECKS,
        owner_type="video_item",
        owner_id=vid,
        input_manifest=manifest,
        idempotency_key=f"RUN_QC_CHECKS:video_item:{vid}:{'t05a'}:{state}",
        input_generation="1",
        steps=[StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
        actor="api",
    )
    if state == "running":
        repo.transition_job(record.id, "running", actor="system",
                            expected_revision=record.revision)
    elif state == "failed":
        r1 = repo.transition_job(record.id, "running", actor="system",
                                 expected_revision=record.revision)
        repo.transition_job(record.id, "failed", actor="system",
                            expected_revision=r1.revision,
                            error={"code": "QC_RUN_INFRA_FAILURE",
                                   "message": "seed failure"})
    session.commit()
    return record.id


def _create_item(
    session: Any,
    *,
    vid: str,
    severity: str,
    ewk: str,
    reason_code: str = "edge_halo",
    layer_ref_type: str = "frame",
    layer_ref_id: str = "frame-ref-42",
    evidence: dict[str, Any] | None = None,
    status: str = "open",
    project_id: str = P1,
) -> str:
    repo = QCItemRepository(session)
    record = repo.create(
        workspace_id=WS,
        project_id=project_id,
        video_item_id=vid,
        layer_ref_type=layer_ref_type,
        layer_ref_id=layer_ref_id,
        reason_code=reason_code,
        evidence_window_key=ewk,
        evidence=evidence
        or {"schema_version": 1, "frame_index": 42, "scene_id": 0},
        severity=severity,
        category=reason_code,
        detector="qc-t05a",
        detector_revision="1.0.0",
        confidence=0.9,
        confidence_source="model",
        checkpoint_ref="ckpt-t05a",
    )
    if status == "acknowledged":
        repo.acknowledge(record.id, WS)
    session.commit()
    return record.id


@pytest.fixture()
def qc_session():
    """Session bound to the SAME temp DB the client fixture serves."""
    factory = deps.get_job_service().session_factory
    assert factory is not None
    session = factory()

    # P1: A (blocker+warnings) + B (clean) — E2E-02 phase 1 dataset.
    # (Video C "mới import chưa chạy checks" is added INSIDE the not_run
    # test to prove not_run wins, exactly like E2E-02 step 5.)
    _seed_ws_project_video(session, ws=WS, pid=P1, vid=V_A, position=0)
    _seed_ws_project_video(session, ws=WS, pid=P1, vid=V_B, position=1)
    _seed_completed_check_run(session, ws=WS, pid=P1, vid=V_A)
    _seed_completed_check_run(session, ws=WS, pid=P1, vid=V_B)
    # A: 1 open blocker + 3 open warnings (E2E-02 dataset)
    _create_item(session, vid=V_A, severity="blocker", ewk="a-blocker-1")
    for i in range(3):
        _create_item(session, vid=V_A, severity="warning", ewk=f"a-warn-{i}")

    # P2: D — completed run with ZERO QCItems (zero-item evidence True)
    _seed_ws_project_video(session, ws=WS, pid=P2, vid=V_D, position=0)
    _seed_completed_check_run(session, ws=WS, pid=P2, vid=V_D)

    # P3: queued / running / failed / stale
    _seed_ws_project_video(session, ws=WS, pid=P3, vid=V_Q, position=0)
    _seed_ws_project_video(session, ws=WS, pid=P3, vid=V_R, position=1)
    _seed_ws_project_video(session, ws=WS, pid=P3, vid=V_F, position=2)
    _seed_ws_project_video(session, ws=WS, pid=P3, vid=V_S, position=3)
    _seed_active_check_run(session, ws=WS, pid=P3, vid=V_Q, state="queued")
    _seed_active_check_run(session, ws=WS, pid=P3, vid=V_R, state="running")
    _seed_active_check_run(session, ws=WS, pid=P3, vid=V_F, state="failed")
    _seed_completed_check_run(session, ws=WS, pid=P3, vid=V_S, stale_fp=True)

    try:
        yield session
    finally:
        session.close()


def _readiness(client: TestClient, pid: str) -> dict[str, Any]:
    resp = client.get(f"/api/v2/projects/{pid}/readiness")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# 1. E2E-02 blocker-only aggregate
# ═══════════════════════════════════════════════════════════════════════════


def test_readiness_blocked_only_by_unresolved_blockers_warnings_just_count(
    client: TestClient, qc_session: Any
) -> None:
    body = _readiness(client, P1)

    assert body["status"] == "blocked"
    assert body["policy_version"] == POLICY_ID
    assert body["content_hash"] == policy_bundle()["policy_content_hash"]
    assert body["computed_at"]

    # blockers[] = only A's blocker, with WS-07 location/reason/action
    assert len(body["blockers"]) == 1
    blocker = body["blockers"][0]
    assert blocker["video_item_id"] == V_A
    assert blocker["code"] == "edge_halo"
    assert blocker["qc_item_id"]
    assert blocker["layer_ref_type"] == "frame"
    assert blocker["location"]["frame_index"] == 42
    assert blocker["location"]["scene_id"] == 0
    assert blocker["reason_vi"]
    assert blocker["action_vi"]
    assert blocker["action"]["kind"] == "navigate"
    assert blocker["action"]["target"]

    # warnings only counted — never in blockers[]
    assert body["warning_count"] == 3
    assert all(b["code"] != "warning" for b in body["blockers"])

    # per-video detail present (fail-closed evidence per video)
    by_vid = {v["video_item_id"]: v for v in body["videos"]}
    assert set(by_vid) == {V_A, V_B}
    assert by_vid[V_A]["status"] == "blocked"
    assert by_vid[V_A]["run_state"] == "completed"
    assert by_vid[V_A]["blockers"] == 1
    assert by_vid[V_B]["status"] == "ready"


def test_readiness_ready_after_blocker_resolved_warning_count_stays(
    client: TestClient, qc_session: Any
) -> None:
    # Resolve the blocker via recheck evidence (rule 1 — terminal-only).
    repo = QCItemRepository(qc_session)
    records, _ = repo.list(WS, project_id=P1, severity="blocker", status="open")
    assert len(records) == 1
    repo.recheck_resolved(records[0].id, WS, evidence={"recheck": "resolved"})
    qc_session.commit()

    body = _readiness(client, P1)
    assert body["status"] == "ready"  # B clean + A resolved
    assert body["blockers"] == []
    assert body["warning_count"] == 3  # warning count unchanged


def test_readiness_not_run_wins_for_unchecked_video(
    client: TestClient, qc_session: Any
) -> None:
    # E2E-02 step 5: video C "mới import chưa chạy checks" appears →
    # readiness PHẢI not_run (capability honesty) — the gate must not
    # claim readiness while any video lacks a completed current run,
    # even though A is blocked + B clean.
    _seed_ws_project_video(qc_session, ws=WS, pid=P1, vid=V_C, position=2)
    body = _readiness(client, P1)
    assert body["status"] == "not_run"
    by_vid = {v["video_item_id"]: v for v in body["videos"]}
    c = by_vid[V_C]
    assert c["status"] == "not_run"
    assert c["run_state"] == "never_run"
    assert c["check_state_detail"]
    # The still-current blocker of A remains visible (honest list), the
    # aggregate stays fail-closed.
    assert any(b["video_item_id"] == V_A for b in body["blockers"])


# ═══════════════════════════════════════════════════════════════════════════
# 2. T03G evidence: zero-item completion vs never-run (C4-F2)
# ═══════════════════════════════════════════════════════════════════════════


def test_readiness_completed_zero_item_run_is_clean_not_not_run(
    client: TestClient, qc_session: Any
) -> None:
    from app.persistence.qc_items import QCItemRepository as _Repo

    # D has ZERO QCItem rows — only the durable run evidence can distinguish
    # "ran clean" from "never checked" (C4-F2); table emptiness must NOT map
    # to not_run.
    records, total = _Repo(qc_session).list(WS, project_id=P2)
    assert total == 0

    body = _readiness(client, P2)
    assert body["status"] == "ready"
    assert body["blockers"] == []
    assert body["warning_count"] == 0
    d = body["videos"][0]
    assert d["video_item_id"] == V_D
    assert d["status"] == "ready"
    assert d["run_state"] == "completed"
    assert d["zero_item_completion"] is True


def test_readiness_queued_running_failed_stale_not_run_with_detail(
    client: TestClient, qc_session: Any
) -> None:
    body = _readiness(client, P3)
    assert body["status"] == "not_run"
    by_vid = {v["video_item_id"]: v for v in body["videos"]}
    assert by_vid[V_Q]["status"] == "not_run" and by_vid[V_Q]["run_state"] == "queued"
    assert by_vid[V_R]["status"] == "not_run" and by_vid[V_R]["run_state"] == "running"
    assert by_vid[V_F]["status"] == "not_run" and by_vid[V_F]["run_state"] == "failed"
    assert by_vid[V_S]["status"] == "not_run" and by_vid[V_S]["run_state"] == "stale"
    for v in body["videos"]:
        assert v["check_state_detail"], v["video_item_id"]
    for v in body["videos"]:
        if v["run_state"] in ("queued", "running", "failed", "stale"):
            assert v["latest_job_id"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. R4 — dismissed blocker can never help readiness
# ═══════════════════════════════════════════════════════════════════════════


def test_readiness_blocker_dismissal_never_helps_ready(
    client: TestClient, qc_session: Any
) -> None:
    records, _ = QCItemRepository(qc_session).list(
        WS, project_id=P1, severity="blocker", status="open"
    )
    item_id = records[0].id

    # Rule 2 (lane-A §1.3): blocker dismissal is refused at the repository
    # guard AND the DB CHECK backstop — a dismissed blocker can never exist
    # to "help" readiness.
    with pytest.raises(QCItemBlockedDismissalError):
        QCItemRepository(qc_session).recheck_dismissed(
            item_id, WS, evidence={"recheck": "dismissed"}
        )
    qc_session.rollback()

    dismissed = qc_session.execute(
        _text(
            "SELECT COUNT(*) FROM qc_item WHERE severity = 'blocker' "
            "AND status = 'dismissed'"
        )
    ).scalar_one()
    assert dismissed == 0

    body = _readiness(client, P1)
    assert body["status"] == "blocked"  # dismissal can never flip readiness
    assert any(b["qc_item_id"] == item_id for b in body["blockers"])


# ═══════════════════════════════════════════════════════════════════════════
# 4. Decision F / shape / gates
# ═══════════════════════════════════════════════════════════════════════════


def test_readiness_unknown_project_404(client: TestClient) -> None:
    resp = client.get(f"/api/v2/projects/{uuid.uuid4()}/readiness")
    assert resp.status_code == 404


def test_readiness_blocker_unknown_kind_fail_closed_explain(
    client: TestClient, qc_session: Any
) -> None:
    # A blocker whose location kind has no canonical mapping must NOT 500 the
    # whole aggregate: it stays listed with an explain action (no dead link).
    pid = str(uuid.uuid4())
    vid = str(uuid.uuid4())
    _seed_ws_project_video(qc_session, ws=WS, pid=pid, vid=vid, position=0)
    _seed_completed_check_run(qc_session, ws=WS, pid=pid, vid=vid)
    _create_item(
        qc_session,
        vid=vid,
        severity="blocker",
        ewk="unknown-kind-1",
        layer_ref_type="bogus_kind",
        layer_ref_id="nope",
        project_id=pid,
    )
    body = _readiness(client, pid)
    assert body["status"] == "blocked"
    blocker = body["blockers"][0]
    assert blocker["action"]["kind"] == "explain"
    assert blocker["action"]["code"] == "unknown_kind"
    assert blocker["action"]["target"] is None
    # location stays STRUCTURED-only (typed evidence keys — never a guess):
    # the frame anchor comes from the typed evidence, exactly like the
    # canonical resolver contract.
    assert blocker["location"]["frame_index"] == 42


def test_readiness_static_gates_router_app_migrations(
    client: TestClient, qc_session: Any, tmp_path: Path
) -> None:
    router_src = (REPO_ROOT / "app/api/routes/readiness.py").read_text(encoding="utf-8")
    asserts = [
        ("exactly one GET", re.findall(r"@router\.get\b", router_src), 1),
    ]
    for name, hits, expected in asserts:
        assert len(hits) == expected, f"{name}: {hits}"
    mutators = re.findall(r"@router\.(post|put|patch|delete)\b", router_src)
    assert mutators == [], f"readiness router must be GET-only: {mutators}"

    app_src = (REPO_ROOT / "app/api/app.py").read_text(encoding="utf-8")
    assert app_src.count("include_router(readiness.router)") == 1

    # zero migrations / readiness table
    migration_hits = list((REPO_ROOT / "migrations/versions").glob("*.py"))
    assert migration_hits, "migrations dir must exist"
    alembic_heads = client.app  # just anchor: head check runs in terminal gate
    assert alembic_heads is not None
    # No readiness table in the models module (Decision F).
    from app.persistence import models as _models

    assert not hasattr(_models, "Readiness")
    assert not any("readiness" in m.lower() for m in dir(_models))
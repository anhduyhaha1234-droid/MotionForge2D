"""S11-T03G (W8) — server-owned POST action + read authority (HTTP surface).

Decision A gates (production plan REV7/C6, W8 block):

- POST .../qc-check-runs is a SERVER-OWNED action from the plan's listed
  set: the payload carries NO handler/provider/detector implementation
  choice (request schema forbids extra fields, so a payload that tries to
  pick an implementation answers 422); the server composes the check args
  from persisted video evidence only.
- Direct QCItem creation through the API is impossible (Decision A): the
  qc-items surface is GET-only, so any POST attempt answers 405.
- Read authority (GET): returns the latest completed non-stale run that
  matches the current video evidence fingerprint + policy hash; stale
  runs (evidence fingerprint mismatch) are filtered to ``not_run`` with
  check-state detail.

Isolation: the standard `client` fixture (isolated project root + temp
Alembic-head DB + patched deps); the durable worker comes from the REAL
default JobService registration block.
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
from app.persistence.jobs import JobRepository
from app.persistence.models import Artifact, VideoItem
from app.services.qc_checks import audio_missing, av_sync_drift  # noqa: F401  (self-register)
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    RUN_QC_SCHEMA_VERSION,
    SCOPE_AUDIO,
    SCOPE_FULL,
    ensure_full_band_registered,
    evidence_fingerprint,
    policy_bundle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

WS = "default"
P1 = str(uuid.uuid4())
P2 = str(uuid.uuid4())
V1 = str(uuid.uuid4())
V2 = str(uuid.uuid4())
V3 = str(uuid.uuid4())


@pytest.fixture(scope="module", autouse=True)
def _ensure_audio_band_registered() -> None:
    # S11-C4: production full-band registration (registry is
    # production-owned state, never a test-only shim).
    ensure_full_band_registered()


def _seed_project_video(
    session: Any, *, ws: str, pid: str, vid: str, position: int = 0
) -> None:
    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT03G','','active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": pid, "w": ws},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidT03G',:pos,'imported')"
        ),
        {"v": vid, "p": pid, "pos": position},
    )
    session.commit()


def _seed_attach_evidence(session: Any, *, ws: str, pid: str, vid: str) -> None:
    """Repository-side seeding (Decision A) of the video's REAL persisted
    audio evidence: a completed ATTACH_ORIGINAL_AUDIO job whose attempt
    result carries the terminal NO_AUDIO_PRESENT envelope (T03E contract).
    The server-owned POST derives its check args from THIS row — nothing is
    accepted from the client and nothing is fabricated."""
    from app.persistence.jobs import StepInput as _StepInput
    from app.persistence.models import JobStep as _JobStep
    from app.persistence.models import Workspace as _Workspace

    ws_row = session.get(_Workspace, ws)
    assert ws_row is not None
    repo = JobRepository(session)
    video = session.get(VideoItem, vid)
    assert video is not None
    record = repo.create_job(
        workspace_id=ws,
        job_type="ATTACH_ORIGINAL_AUDIO",
        owner_type="video_item",
        owner_id=vid,
        input_manifest={
            "schema_version": 1,
            "workspace_id": ws,
            "project_id": pid,
            "video_item_id": vid,
            "source_artifact_id": None,
            "source_sha256": "",
            "generation": "1",
        },
        idempotency_key=f"ATTACH_ORIGINAL_AUDIO:video_item:{vid}:{'a' * 64}:1",
        input_generation="1",
        steps=[_StepInput(step_code="attach_original_audio", position=0, step_type="sync")],
        actor="api",
    )
    step_row = session.get(_JobStep, repo.list_steps(record.id)[0].id)
    repo.transition_step(step_row.id, "ready", actor="system",
                         expected_revision=step_row.revision, fence_token="seed-token")
    step_row2 = session.get(_JobStep, repo.list_steps(record.id)[0].id)
    repo.transition_step(step_row2.id, "running", actor="system",
                         expected_revision=step_row2.revision, fence_token="seed-token")
    step_row3 = session.get(_JobStep, repo.list_steps(record.id)[0].id)
    result = {
        "source": {
            "artifact_id": None,
            "relative_path": "",
            "sha256": "",
            "size_bytes": None,
        },
        "remux": {
            "checkpoint": {
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
        },
        "published": {
            "no_audio_present": True,
            "artifact_id": None,
            "final_rel": None,
            "sha256": None,
            "size_bytes": None,
            "status": "NO_AUDIO_PRESENT",
        },
    }
    repo.record_attempt(
        job_id=record.id,
        step_id=step_row3.id,
        step_code="attach_original_audio",
        attempt=1,
        worker_id="seed-worker",
        fence_token="seed-token",
        result=result,
    )
    repo.transition_step(
        step_row3.id,
        "completed",
        actor="system",
        expected_revision=step_row3.revision,
        fence_token="seed-token",
    )
    repo.transition_job(
        record.id, "running", actor="system", expected_revision=record.revision
    )
    job_running = repo.get_job(record.id)
    repo.transition_job(
        record.id, "completed", actor="system", expected_revision=job_running.revision
    )
    session.commit()


@pytest.fixture()
def qc_session():
    """A session bound to the SAME temp DB the client fixture serves."""
    factory = deps.get_job_service().session_factory
    assert factory is not None
    session = factory()
    _seed_project_video(session, ws=WS, pid=P1, vid=V1)
    _seed_project_video(session, ws=WS, pid=P1, vid=V2, position=1)
    _seed_project_video(session, ws=WS, pid=P2, vid=V3)
    try:
        yield session
    finally:
        session.close()


def _run_worker_once() -> None:
    worker = deps.get_job_service().worker
    assert worker is not None
    worker.run_once()


def _job_state(session: Any, job_id: str) -> str:
    return JobRepository(session).get_job(job_id).state


# ═══════════════════════════════════════════════════════════════════════════
# Decision A binary gates
# ═══════════════════════════════════════════════════════════════════════════


def test_direct_qc_item_create_via_api_rejected(client: TestClient) -> None:
    """Decision A: arbitrary QCItem CRUD does not exist — any POST/PUT/PATCH
    against the qc-items namespace answers 405/404, never creates rows."""
    url = f"/api/v2/projects/{P1}/qc-items"
    resp = client.post(url, json={"reason_code": "audio_missing", "severity": "blocker"})
    assert resp.status_code in (404, 405)
    resp2 = client.put(url, json={})
    assert resp2.status_code in (404, 405)
    resp3 = client.request("PATCH", f"/api/v2/qc-items/{uuid.uuid4()}", json={})
    assert resp3.status_code in (404, 405)


def test_qc_check_runs_router_has_no_qc_item_mutation(
    client: TestClient, qc_session: Any
) -> None:
    """The check-run router adds exactly the server-owned POST + read-only
    GETs — no arbitrary QCItem mutation surface sneaks in."""
    source = (REPO_ROOT / "app/api/routes/qc_check_runs.py").read_text(encoding="utf-8")
    posts = re.findall(r"@router\.post\b", source)
    assert len(posts) == 1, f"exactly one server-owned POST expected, got {len(posts)}"
    mutators = re.findall(r"@router\.(put|patch|delete)\b", source)
    assert mutators == [], f"unexpected mutation methods: {mutators}"
    gets = re.findall(r"@router\.get\b", source)
    assert len(gets) >= 2


def test_router_source_has_no_detector_implementation_fields(client: TestClient) -> None:
    """Binary: the request schema cannot even name an implementation — the
    route reads ONLY video_item_id + scope."""
    source = (REPO_ROOT / "app/schemas/qc_check_runs.py").read_text(encoding="utf-8")
    for forbidden in ("detector", "handler", "provider"):
        assert not re.search(rf"^\s*{forbidden}\s*:", source, re.MULTILINE), (
            f"request schema must not expose {forbidden!r} as a field"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Server-owned POST
# ═══════════════════════════════════════════════════════════════════════════


def test_post_payload_with_implementation_choice_rejected_422(
    client: TestClient, qc_session: Any
) -> None:
    """A client that tries to pick handler/provider/detectors is refused —
    the POST payload carries NO implementation choice (fail-closed 422)."""
    for body in (
        {"video_item_id": V1, "scope": SCOPE_AUDIO, "detector": "audio_missing"},
        {"video_item_id": V1, "scope": SCOPE_AUDIO, "handler": "qc_checks_handler"},
        {"video_item_id": V1, "scope": SCOPE_AUDIO, "provider": "custom"},
        {"video_item_id": V1, "scope": SCOPE_AUDIO, "detectors": ["audio_missing"]},
    ):
        resp = client.post(f"/api/v2/projects/{P1}/qc-check-runs", json=body)
        assert resp.status_code == 422, f"body {body} → {resp.status_code}"


def test_post_unknown_scope_rejected_422(client: TestClient, qc_session: Any) -> None:
    resp = client.post(
        f"/api/v2/projects/{P1}/qc-check-runs",
        json={"video_item_id": V1, "scope": "bogus-scope"},
    )
    assert resp.status_code == 422


def test_post_missing_video_rejected(client: TestClient, qc_session: Any) -> None:
    resp = client.post(
        f"/api/v2/projects/{P1}/qc-check-runs",
        json={"video_item_id": str(uuid.uuid4()), "scope": SCOPE_AUDIO},
    )
    assert resp.status_code == 404


def test_post_unknown_project_rejected_404(client: TestClient) -> None:
    resp = client.post(
        f"/api/v2/projects/{uuid.uuid4()}/qc-check-runs",
        json={"video_item_id": V1, "scope": SCOPE_AUDIO},
    )
    assert resp.status_code == 404


def test_post_server_owned_runs_to_completed_zero_item(
    client: TestClient, qc_session: Any
) -> None:
    """End-to-end: the server-owned POST creates the durable RUN_QC_CHECKS
    job, the real worker completes it (zero QCItems — NO_AUDIO_PRESENT), and
    the server-owned manifest exposes the submission evidence.

    C1-A: a completed audio-only run is NOT the full authority — the GET
    state/readiness therefore report never_run / not_run (the FULL band
    has no server-side evidence composition path, so no completed FULL
    run can exist for this video; nothing is fabricated).
    """
    _seed_attach_evidence(qc_session, ws=WS, pid=P1, vid=V1)

    resp = client.post(
        f"/api/v2/projects/{P1}/qc-check-runs",
        json={"video_item_id": V1, "scope": SCOPE_AUDIO},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["reused"] is False
    assert body["state"] == "queued"
    job_id = body["job_id"]

    with deps.get_job_service().session_factory() as s:  # type: ignore[union-attr]
        record = JobRepository(s).get_job(job_id)
        manifest = record.input_manifest
        assert record.job_type == JOB_TYPE_RUN_QC_CHECKS
        assert manifest["scope"] == SCOPE_AUDIO
        assert manifest["policy_content_hash"] == policy_bundle()["policy_content_hash"]
        # server-owned: only the authorized band, no client-chosen names
        assert set(manifest["detector_args"]) == {"audio_missing", "av_sync_drift"}
        assert "provider" not in manifest and "handler" not in manifest
        # the client payload never contributed detector args — they were
        # composed from the persisted attach evidence (NO_AUDIO_PRESENT)
        assert manifest["detector_args"]["audio_missing"]["checkpoint"]["status"] == (
            "NO_AUDIO_PRESENT"
        )

    _run_worker_once()
    with deps.get_job_service().session_factory() as s:  # type: ignore[union-attr]
        assert _job_state(s, job_id) == "completed"

    # C1-A read authority: the audio-only job is invisible to the FULL
    # authority — no FULL run ever submitted ⇒ never_run / not_run.
    get = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V1}")
    assert get.status_code == 200
    state = get.json()
    assert state["run_state"] == "never_run"
    assert state["zero_item_completion"] is None
    assert state["job_id"] is None

    ready = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V1}/readiness")
    assert ready.status_code == 200
    rr = ready.json()
    assert rr["status"] == "not_run"  # C1-A: audio-only ≠ full authority
    assert rr["run_state"] == "never_run"


def test_post_active_duplicate_conflict_and_completed_reuse(
    client: TestClient, qc_session: Any
) -> None:
    _seed_attach_evidence(qc_session, ws=WS, pid=P1, vid=V1)
    url = f"/api/v2/projects/{P1}/qc-check-runs"
    first = client.post(url, json={"video_item_id": V1, "scope": SCOPE_AUDIO})
    assert first.status_code == 202
    first_job = first.json()["job_id"]

    # duplicate while active → 409 fail-closed
    dup = client.post(url, json={"video_item_id": V1, "scope": SCOPE_AUDIO})
    assert dup.status_code == 409
    assert "job_id" not in dup.json() or dup.json().get("job_id") != first_job

    _run_worker_once()
    with deps.get_job_service().session_factory() as s:  # type: ignore[union-attr]
        assert _job_state(s, first_job) == "completed"

    # completed duplicate → 202 reuse of the SAME job
    again = client.post(url, json={"video_item_id": V1, "scope": SCOPE_AUDIO})
    assert again.status_code == 202
    assert again.json()["reused"] is True
    assert again.json()["job_id"] == first_job


def test_post_scope_audio_without_attach_evidence_fails_closed(
    client: TestClient, qc_session: Any
) -> None:
    """No persisted audio evidence → the server cannot compose check inputs
    → fail-closed 422; nothing is fabricated and no job is created."""
    resp = client.post(
        f"/api/v2/projects/{P1}/qc-check-runs",
        json={"video_item_id": V2, "scope": SCOPE_AUDIO},
    )
    assert resp.status_code == 422, f"unexpected {resp.status_code}: {resp.text[:300]}"
    detail = resp.json().get("detail", "")
    assert "QC_RUN_EVIDENCE_UNAVAILABLE" in detail


def test_post_full_scope_without_visual_evidence_fails_closed(
    client: TestClient, qc_session: Any
) -> None:
    """scope=full needs the visual band's evidence; V1 has no derivation
    path for it → fail-closed 422, never a fabricated run."""
    resp = client.post(
        f"/api/v2/projects/{P1}/qc-check-runs",
        json={"video_item_id": V1, "scope": "full"},
    )
    assert resp.status_code == 422, f"unexpected {resp.status_code}: {resp.text[:300]}"
    detail = resp.json().get("detail", "")
    assert "QC_RUN_EVIDENCE_UNAVAILABLE" in detail


# ═══════════════════════════════════════════════════════════════════════════
# Read authority (GET)
# ═══════════════════════════════════════════════════════════════════════════


def test_read_authority_never_run_not_run_with_detail(
    client: TestClient, qc_session: Any
) -> None:
    get = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V2}")
    assert get.status_code == 200
    state = get.json()
    assert state["run_state"] == "never_run"
    assert state["zero_item_completion"] is None

    ready = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V2}/readiness")
    assert ready.status_code == 200
    rr = ready.json()
    assert rr["status"] == "not_run"
    assert rr["check_state_detail"]  # fail-closed detail present


def test_read_authority_stale_after_evidence_fingerprint_change(
    client: TestClient, qc_session: Any
) -> None:
    """C1-A: staleness semantics attach to the FULL authority.

    An audio-only completed run never creates FULL authority (GET reports
    never_run before AND after the evidence change), while a directly
    seeded completed CURRENT FULL run goes stale on evidence change.
    """
    from app.workflow.qc_checks_handler import (
        evidence_fingerprint as _fp,
    )
    from app.workflow.qc_checks_handler import (
        policy_bundle as _bundle,
    )

    _seed_attach_evidence(qc_session, ws=WS, pid=P1, vid=V1)
    resp = client.post(
        f"/api/v2/projects/{P1}/qc-check-runs",
        json={"video_item_id": V1, "scope": SCOPE_AUDIO},
    )
    assert resp.status_code == 202
    _run_worker_once()

    # audio-only ⇒ no FULL authority, before and after the evidence change.
    get = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V1}")
    assert get.json()["run_state"] == "never_run"

    # The video's evidence changed: a new generation is recorded on the
    # item (simulating re-import / source replacement).  The audio run
    # still creates no FULL authority.
    with deps.get_job_service().session_factory() as s:  # type: ignore[union-attr]
        item = s.get(VideoItem, V1)
        assert item is not None
        art = Artifact(
            workspace_id=WS,
            kind="video",
            relative_path=f"runs/{V1}/v2.mp4",
            state="ready",
            sha256="c" * 64,
            size_bytes=4096,
            mime_type="video/mp4",
        )
        s.add(art)
        s.flush()
        item.source_artifact_id = art.id
        s.commit()
        new_fp = evidence_fingerprint(s, workspace_id=WS, video_item_id=V1)

    get2 = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V1}")
    assert get2.status_code == 200
    state2 = get2.json()
    assert state2["run_state"] == "never_run"  # C1-A: still no FULL run

    ready = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{V1}/readiness")
    rr = ready.json()
    assert rr["status"] == "not_run"
    assert rr["run_state"] == "never_run"
    assert rr["check_state_detail"]
    assert rr["current_evidence_fingerprint"] == new_fp

    # Contrast: a completed CURRENT FULL run goes stale on evidence
    # change (proves staleness still works for the authority — seeded
    # directly through the repo; the FULL band has no HTTP submit path).
    import uuid as _uuid

    from app.persistence.jobs import JobRepository as _Repo
    from app.persistence.jobs import StepInput as _StepInput
    from app.persistence.qc_check_runs import (
        full_coverage_detectors as _band,
    )
    from app.persistence.qc_check_runs import (
        latest_check_run_state as _latest,
    )
    from app.workflow.qc_checks_handler import scope_fingerprint as _sfp

    V3 = f"v-s11-t03g-full-{_uuid.uuid4().hex[:8]}"
    with deps.get_job_service().session_factory() as s:  # type: ignore[union-attr]
        from sqlalchemy import text as _t

        s.execute(
            _t("INSERT INTO workspace(id, name) VALUES (:w, :w) ON CONFLICT(id) DO NOTHING"),
            {"w": WS},
        )
        s.execute(
            _t(
                "INSERT INTO project(id, workspace_id, name, description, status) "
                "VALUES (:p, :w, :p, '', 'active') ON CONFLICT(id) DO NOTHING"
            ),
            {"p": P1, "w": WS},
        )
        s.execute(
            _t(
                "INSERT INTO video_item(id, project_id, title, position, status) "
                "VALUES (:v, :p, :v, "
                "(SELECT COALESCE(MAX(position),0)+1 FROM video_item WHERE project_id=:p), "
                "'imported') ON CONFLICT(id) DO NOTHING"
            ),
            {"v": V3, "p": P1},
        )
        s.commit()
        bundle = _bundle()
        band = _band()
        fp3 = _fp(s, workspace_id=WS, video_item_id=V3)
        manifest = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "workspace_id": WS,
            "project_id": P1,
            "video_item_id": V3,
            "evidence_fingerprint": fp3,
            "policy_id": bundle.get("policy_id") or "s11-qc-thresholds-v1",
            "policy_content_hash": bundle["policy_content_hash"],
            "source_generation": "1",
            "source_artifact_id": None,
            "source_sha256": "",
            "scope": SCOPE_FULL,
            "scope_fingerprint": _sfp(SCOPE_FULL),
        }
        repo = _Repo(s)
        record = repo.create_job(
            workspace_id=WS,
            job_type=JOB_TYPE_RUN_QC_CHECKS,
            owner_type="video_item",
            owner_id=V3,
            input_manifest=manifest,
            idempotency_key=f"{JOB_TYPE_RUN_QC_CHECKS}:video_item:{V3}:c1a:1",
            input_generation="1",
            steps=[_StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
            actor="api",
        )
        step = repo.list_steps(record.id)[0]
        repo.transition_step(
            step.id, "ready", actor="system",
            expected_revision=step.revision, fence_token="c1a",
        )
        step = repo.list_steps(record.id)[0]
        repo.transition_step(
            step.id, "running", actor="system",
            expected_revision=step.revision, fence_token="c1a",
        )
        step = repo.list_steps(record.id)[0]
        completion = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "job_type": JOB_TYPE_RUN_QC_CHECKS,
            "completed": True,
            "run_id": "d" * 64,
            "policy_id": bundle["policy_id"],
            "policy_content_hash": bundle["policy_content_hash"],
            "source_generation": "1",
            "source_artifact_id": None,
            "source_artifact_fingerprint": "",
            "evidence_fingerprint": fp3,
            "scope": SCOPE_FULL,
            "scope_fingerprint": _sfp(SCOPE_FULL),
            "detectors": list(band),
            "detector_revisions": {name: "1.0.0" for name in band},
            "summary": {
                "run_id": "d" * 64,
                "checks_requested": len(band),
                "checks_run": len(band),
                "checks_skipped": 0,
                "created": 0,
                "reused": 0,
                "resolved_after_recheck": 0,
                "reopened_stale": 0,
                "not_applicable": len(band),
                "errors": 0,
                "cancelled": False,
                "deadline_exceeded": False,
                "run_sec": 0.001,
                "per_detector": {},
            },
            "zero_item_completion": {
                "evidence": True,
                "qc_items_created": 0,
                "issues_found": 0,
                "checks_run": len(band),
                "not_applicable": len(band),
            },
        }
        repo.record_attempt(
            job_id=record.id, step_id=step.id, step_code="run_qc_checks",
            attempt=1, worker_id="seed-c1a", fence_token="c1a",
            result=completion,
        )
        repo.transition_step(
            step.id, "completed", actor="system",
            expected_revision=step.revision, fence_token="c1a",
        )
        r1 = repo.transition_job(
            record.id, "running", actor="system",
            expected_revision=record.revision,
        )
        repo.transition_job(
            record.id, "completed", actor="system",
            expected_revision=r1.revision,
        )
        s.commit()
        cur = _latest(
            s, workspace_id=WS, project_id=P1, video_item_id=V3,
            evidence_fingerprint=fp3,
            policy_content_hash=bundle["policy_content_hash"],
        )
        assert cur.run_state == "completed"  # current FULL ⇒ authority
        # 51 newer audio jobs cannot hide the full authority (C2-A1
        # history pressure: unbounded matching-full query, not
        # limit-then-filter).
        audio_idem = f"{JOB_TYPE_RUN_QC_CHECKS}:video_item:{V3}:c1a:audio"
        for i in range(51):
            repo.create_job(
                workspace_id=WS,
                job_type=JOB_TYPE_RUN_QC_CHECKS,
                owner_type="video_item",
                owner_id=V3,
                input_manifest={
                    **manifest,
                    "scope": SCOPE_AUDIO,
                    "scope_fingerprint": _sfp(SCOPE_AUDIO),
                    "evidence_fingerprint": fp3,
                },
                idempotency_key=f"{audio_idem}:{i}",
                input_generation="1",
                steps=[_StepInput(step_code="run_qc_checks", position=0, step_type="sync")],
                actor="api",
            )
        s.commit()
        pressured = _latest(
            s, workspace_id=WS, project_id=P1, video_item_id=V3,
            evidence_fingerprint=fp3,
            policy_content_hash=bundle["policy_content_hash"],
        )
        assert pressured.run_state == "completed"
        assert pressured.job_id == record.id  # exact full, not any audio
        stale = _latest(
            s, workspace_id=WS, project_id=P1, video_item_id=V3,
            evidence_fingerprint="7" * 64,
            policy_content_hash=bundle["policy_content_hash"],
        )
        assert stale.run_state == "stale"  # evidence moved ⇒ stale/not_run
        # (caller-supplied non-current evidence: the envelope passes — the
        # manifest/completion pair still agrees with each other — and the
        # manifest-vs-current comparison fires the stale branch, exactly
        # as the C1-A contract requires; not_run either way).


def test_read_authority_unknown_video_404(client: TestClient, qc_session: Any) -> None:
    resp = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_c3a1_api_source_identity_tamper_is_not_run(
    client: TestClient, qc_session: Any
) -> None:
    """C3-A1 item 5 over real HTTP: a completed CURRENT FULL run whose
    completion source identity is forged (id-only) ⇒ the project
    readiness row reports not_run (never ready on tampered source)."""
    import uuid as _uuid2

    from app.persistence.jobs import JobRepository as _Repo2
    from app.persistence.jobs import StepInput as _StepInput2
    from app.persistence.qc_check_runs import (
        full_coverage_detectors as _band2,
    )
    from app.workflow.qc_checks_handler import (
        evidence_fingerprint as _fp2,
    )
    from app.workflow.qc_checks_handler import (
        policy_bundle as _bundle2,
    )
    from app.workflow.qc_checks_handler import (
        scope_fingerprint as _sfp2,
    )

    v4 = f"v-s11-t03g-src-{_uuid2.uuid4().hex[:8]}"
    with deps.get_job_service().session_factory() as s:  # type: ignore[union-attr]
        from sqlalchemy import text as _t2

        s.execute(
            _t2("INSERT INTO workspace(id, name) VALUES (:w, :w) ON CONFLICT(id) DO NOTHING"),
            {"w": WS},
        )
        s.execute(
            _t2(
                "INSERT INTO project(id, workspace_id, name, description, status) "
                "VALUES (:p, :w, :p, '', 'active') ON CONFLICT(id) DO NOTHING"
            ),
            {"p": P1, "w": WS},
        )
        s.execute(
            _t2(
                "INSERT INTO video_item(id, project_id, title, position, status) "
                "VALUES (:v, :p, :v, "
                "(SELECT COALESCE(MAX(position),0)+1 FROM video_item WHERE project_id=:p), "
                "'imported') ON CONFLICT(id) DO NOTHING"
            ),
            {"v": v4, "p": P1},
        )
        s.commit()
        bundle = _bundle2()
        band = _band2()
        fp4 = _fp2(s, workspace_id=WS, video_item_id=v4)
        manifest = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "workspace_id": WS,
            "project_id": P1,
            "video_item_id": v4,
            "evidence_fingerprint": fp4,
            "policy_id": bundle.get("policy_id") or "s11-qc-thresholds-v1",
            "policy_content_hash": bundle["policy_content_hash"],
            "source_generation": "1",
            "source_artifact_id": None,
            "source_sha256": "",
            "scope": SCOPE_FULL,
            "scope_fingerprint": _sfp2(SCOPE_FULL),
        }
        repo = _Repo2(s)
        record = repo.create_job(
            workspace_id=WS,
            job_type=JOB_TYPE_RUN_QC_CHECKS,
            owner_type="video_item",
            owner_id=v4,
            input_manifest=manifest,
            idempotency_key=f"{JOB_TYPE_RUN_QC_CHECKS}:video_item:{v4}:c3a1:1",
            input_generation="1",
            steps=[_StepInput2(step_code="run_qc_checks", position=0, step_type="sync")],
            actor="api",
        )
        step = repo.list_steps(record.id)[0]
        repo.transition_step(
            step.id, "ready", actor="system",
            expected_revision=step.revision, fence_token="c3a1",
        )
        step = repo.list_steps(record.id)[0]
        repo.transition_step(
            step.id, "running", actor="system",
            expected_revision=step.revision, fence_token="c3a1",
        )
        step = repo.list_steps(record.id)[0]
        completion = {
            "schema_version": RUN_QC_SCHEMA_VERSION,
            "job_type": JOB_TYPE_RUN_QC_CHECKS,
            "completed": True,
            "run_id": "e" * 64,
            "policy_id": bundle["policy_id"],
            "policy_content_hash": bundle["policy_content_hash"],
            "source_generation": "1",
            # id-only tamper: manifest/current say no-source, the
            # completion claims a ghost source.
            "source_artifact_id": "ghost-artifact",
            "source_artifact_fingerprint": "",
            "evidence_fingerprint": fp4,
            "scope": SCOPE_FULL,
            "scope_fingerprint": _sfp2(SCOPE_FULL),
            "detectors": list(band),
            "detector_revisions": {name: "1.0.0" for name in band},
            "summary": {
                "run_id": "e" * 64,
                "checks_requested": len(band),
                "checks_run": len(band),
                "checks_skipped": 0,
                "created": 0,
                "reused": 0,
                "resolved_after_recheck": 0,
                "reopened_stale": 0,
                "not_applicable": len(band),
                "errors": 0,
                "cancelled": False,
                "deadline_exceeded": False,
                "run_sec": 0.001,
                "per_detector": {},
            },
            "zero_item_completion": {
                "evidence": True,
                "qc_items_created": 0,
                "issues_found": 0,
                "checks_run": len(band),
                "not_applicable": len(band),
            },
        }
        repo.record_attempt(
            job_id=record.id, step_id=step.id, step_code="run_qc_checks",
            attempt=1, worker_id="seed-c3a1", fence_token="c3a1",
            result=completion,
        )
        repo.transition_step(
            step.id, "completed", actor="system",
            expected_revision=step.revision, fence_token="c3a1",
        )
        r1 = repo.transition_job(
            record.id, "running", actor="system",
            expected_revision=record.revision,
        )
        repo.transition_job(
            record.id, "completed", actor="system",
            expected_revision=r1.revision,
        )
        s.commit()
    get = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{v4}")
    assert get.status_code == 200
    assert get.json()["run_state"] == "failed"
    ready = client.get(f"/api/v2/projects/{P1}/qc-check-runs/{v4}/readiness")
    assert ready.status_code == 200
    rr = ready.json()
    assert rr["status"] == "not_run"
    assert rr["run_state"] == "failed"
    assert "source" in rr["check_state_detail"]


def test_read_authority_cross_project_rejected(client: TestClient, qc_session: Any) -> None:
    """V1 belongs to P1 — asking under P2 fails closed (ownership)."""
    resp = client.get(f"/api/v2/projects/{P2}/qc-check-runs/{V1}")
    assert resp.status_code in (404, 409)

"""S09 demo-loop API routes (S09-T03).

Isolated router under /api/v2/s09-demo-loops (disjoint from every legacy
route and from /api/v2/reskin-configs).  Thin API boundary over the durable
core app/workflow/s09_demo_jobs — no business logic here, no silent
fallback:

- POST /submit: creates ONE durable ``s09_demo_loop`` Job whose manifest
  carries the requested loops + evidence paths.  Idempotent via the
  client-supplied idempotency key (equivalent replay → 200 same Job;
  conflicting payload → 409; invalid shape → 422).  The request path never
  runs ffmpeg and never reads benchmark evidence (worker-side, fail-closed).
- GET /{job_id}: status + published artifacts read back from the durable
  attempt result / step checkpoint (404 no leak for unknown ids).
- POST /{job_id}/cancel: guarded durable cancellation via the existing job
  service (200 cancel_requested; 400 terminal; 404 unknown).
- GET /{job_id}/replay: returns the ORIGINAL input manifest so a client can
  re-submit the identical logical work under a NEW idempotency generation
  (the completed/failed/cancelled row itself is immutable by contract).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import get_job_service
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import IdempotencyKeyInUse, JobRepository
from app.schemas.s09_demo_loops import (
    DemoLoopPlanSummary,
    DemoLoopStatusResponse,
    DemoLoopSubmitRequest,
    DemoLoopSubmitResponse,
    PlanRouteSummary,
    PublishedLoopArtifact,
)
from app.workflow.s09_demo_jobs import (
    JOB_TYPE_S09_DEMO_LOOP,
    demo_loop_steps,
)

router = APIRouter(prefix="/api/v2/s09-demo-loops", tags=["s09-demo-loops"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


def _manifest_fingerprint(payload: dict[str, object]) -> str:
    """Stable content identity of a submit payload (conflict detection)."""
    import hashlib
    import json

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _submit(body: DemoLoopSubmitRequest, response: Response) -> DemoLoopSubmitResponse:
    svc = get_job_service()
    payload_manifest: dict[str, object] = {
        "requested_loops": list(body.requested_loops),
        "benchmark_results": body.benchmark_results,
        "fixtures_dir": body.fixtures_dir,
        "pinned_routes": dict(body.pinned_routes or {}),
        "workspace_id": WORKSPACE_ID,
    }
    fingerprint = _manifest_fingerprint(payload_manifest)
    idempotency_key = f"S09_DEMO_LOOP:{fingerprint[:32]}"
    try:
        info = svc.create_job(
            JOB_TYPE_S09_DEMO_LOOP,
            {
                **payload_manifest,
                "benchmark_results": str(body.benchmark_results),
                "fixtures_dir": str(body.fixtures_dir),
            },
            workspace_id=WORKSPACE_ID,
            owner_type="project",
            owner_id=WORKSPACE_ID,
            idempotency_key=idempotency_key,
            steps=demo_loop_steps(),
        )
        # create_job returns the EXISTING record ONLY for an exact replay of
        # a COMPLETED key (COMPLETED_REUSE_STATES = {"completed"}); a fresh
        # creation comes back as "queued".  Surface reused honestly.
        state_val = info.state.value if hasattr(info.state, "value") else str(info.state)
        reused = state_val == "completed"
    except IdempotencyKeyInUse as err:
        raise HTTPException(
            409,
            "an active demo-loop job with an equivalent payload already exists",
        ) from err
    response.status_code = 200 if reused else 201
    return DemoLoopSubmitResponse(
        job_id=info.job_id,
        status=state_val,
        reused=reused,
        detail_url=f"/api/v2/s09-demo-loops/{info.job_id}",
    )


@router.post("/submit", status_code=201)
def submit_demo_loop(body: DemoLoopSubmitRequest, response: Response) -> DemoLoopSubmitResponse:
    return _submit(body, response)


@router.post("/submit/", status_code=201)
def submit_demo_loop_slash(
    body: DemoLoopSubmitRequest, response: Response
) -> DemoLoopSubmitResponse:
    return _submit(body, response)


@router.get("/{job_id:uuid}", status_code=200)
@router.get("/{job_id:uuid}/", status_code=200)
def get_demo_loop_status(job_id: uuid.UUID) -> DemoLoopStatusResponse:
    svc = get_job_service()
    info = svc.get_job(str(job_id))
    if info is None:
        raise HTTPException(404, "Job not found")
    plan_summary: DemoLoopPlanSummary | None = None
    published: list[PublishedLoopArtifact] = []
    factory = svc.session_factory
    if factory is not None:
        with factory() as session:
            repo = JobRepository(session)
            attempts = repo.list_attempts(str(job_id))
            result_payload: dict[str, object] | None = None
            for attempt in reversed(attempts):
                raw = getattr(attempt, "result", None)
                if isinstance(raw, dict):
                    result_payload = raw
                    break
            if result_payload is not None:
                plan_raw = result_payload.get("plan")
                if isinstance(plan_raw, dict):
                    plan_summary = DemoLoopPlanSummary(
                        covered_risk_classes=[
                            str(c) for c in plan_raw.get("covered_risk_classes", [])
                        ],
                        frozen_content_sha256=str(
                            plan_raw.get("frozen_content_sha256", "")
                        ),
                        thresholds_policy=plan_raw.get("thresholds_policy"),
                        loops=[
                            PlanRouteSummary(
                                loop_id=str(e.get("loop_id", "")),
                                routes_by_risk_class=dict(
                                    e.get("routes_by_risk_class", {})
                                ),
                                route_notes=[str(n) for n in e.get("route_notes", [])],
                            )
                            for e in plan_raw.get("loops", [])
                            if isinstance(e, dict)
                        ],
                    )
                pub_raw = result_payload.get("published")
                if isinstance(pub_raw, dict):
                    for lid, ev in sorted(pub_raw.items()):
                        if isinstance(ev, dict):
                            published.append(
                                PublishedLoopArtifact(
                                    loop_id=str(lid),
                                    relative_path=str(ev.get("relative_path", "")),
                                    artifact_id=str(ev.get("artifact_id", "")),
                                    sha256=str(ev.get("sha256", "")),
                                    size_bytes=int(ev.get("size_bytes", 0)),
                                    frame_count=(
                                        int(ev["frame_count"])
                                        if ev.get("frame_count") is not None
                                        else None
                                    ),
                                    reused_existing_file=(
                                        bool(ev["reused_existing_file"])
                                        if ev.get("reused_existing_file") is not None
                                        else None
                                    ),
                                )
                            )
    state = info.state.value if hasattr(info.state, "value") else str(info.state)
    return DemoLoopStatusResponse(
        job_id=info.job_id,
        job_type=info.job_type or JOB_TYPE_S09_DEMO_LOOP,
        state=state,
        progress=float(info.progress),
        error={"message": info.error} if info.error else None,
        created_at=None,
        finished_at=None,
        plan=plan_summary,
        published=published,
    )


@router.post("/{job_id:uuid}/cancel")
@router.post("/{job_id:uuid}/cancel/")
def cancel_demo_loop(job_id: uuid.UUID) -> dict[str, object]:
    svc = get_job_service()
    ok = svc.cancel_job(str(job_id))
    if not ok:
        info = svc.get_job(str(job_id))
        if info is None:
            raise HTTPException(404, "Job not found")
        state = info.state.value if hasattr(info.state, "value") else str(info.state)
        raise HTTPException(400, f"Cannot cancel demo-loop job in state: {state}")
    return {"status": "cancel_requested", "job_id": str(job_id)}


@router.get("/{job_id:uuid}/replay")
@router.get("/{job_id:uuid}/replay/")
def get_demo_loop_replay(job_id: uuid.UUID) -> dict[str, object]:
    """The original input manifest (immutable contract §3 identity)."""
    svc = get_job_service()
    info = svc.get_job(str(job_id))
    if info is None:
        raise HTTPException(404, "Job not found")
    if info.job_type != JOB_TYPE_S09_DEMO_LOOP:
        raise HTTPException(400, f"not a {JOB_TYPE_S09_DEMO_LOOP} job")
    factory = svc.session_factory
    if factory is None:  # pragma: no cover - service always binds one
        raise HTTPException(500, "job service has no session factory")
    with factory() as session:
        repo = JobRepository(session)
        record = repo.get_job(str(job_id))
        steps = repo.list_steps(str(job_id))
        step_states: dict[str, str] = {}
        for s in steps:
            step_states[s.step_code] = s.state
        return {
            "job_id": str(job_id),
            "state": record.state,
            "input_manifest": record.input_manifest,
            "steps": [s.step_code for s in steps],
            "step_states": step_states,
        }


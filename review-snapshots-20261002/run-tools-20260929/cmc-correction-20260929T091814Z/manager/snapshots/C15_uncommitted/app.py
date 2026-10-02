"""FastAPI application — MotionForge 2D API server.

Lifecycle (S02-T05 AC1): the app initializes/upgrades the durable database
through the approved bootstrap path (with the S01 pre-upgrade backup
policy), reconciles stale in-flight Jobs before the worker polls, starts
the durable worker, and on shutdown stops and joins worker + reconciler.
All of it is explicit lifespan wiring — importing this module (or
``app.main``) starts nothing, opens no sessions, creates no files.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api import deps
from app.api.routes import (
    channels,
    durable_characters,
    durable_projects,
    durable_summaries,
    durable_videos,
    frames,
    jobs,
    object_correction,
    object_extraction,
    object_grouping,
    object_intelligence,
    original_audio_action,
    project_cast,
    projects,
    qc_check_runs,
    qc_items,
    qc_navigation,
    readiness,
    reskin_config,
    s09_approval,
    s09_correction,
    s09_demo_compare,
    s09_demo_loops,
    s10_full_apply,
    s12_export,
    s12_export_preflight,
    shot_anchors,
    structural_evidence,
    structural_lock,
)
from app.api.security import (
    InvalidPathIdentifierError,
    OriginGuardMiddleware,
)
from app.lifecycle import Lifecycle
from app.workflow import analyze_orchestrator

log = logging.getLogger("motionforge.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Explicit application lifecycle (AC1).

    Startup:
      0. explicitly initialize the default ``JobService`` — this makes
         it own its engine/database and REBINDS its ``DurableWorker``
         from the placeholder factory to the real session factory
         (S05-C04 public lifecycle binding: the SAME session factory
         then serves the worker, the reconciler and the chain
         orchestrator — one database, one managed root; no private
         service attribute is inspected or patched here),
      1. bootstrap/upgrade the explicit database (approved path + S01
         pre-upgrade backup policy),
      2. reconcile stale in-flight Jobs (S02-T04) BEFORE worker polling,
      3. start the durable worker poll loop,
      4. start the AnalyzeChainOrchestrator: its startup scan resumes every
         incomplete T02→T03→T04 chain from durable rows (idempotent,
         lease/fence-safe) WITHOUT any POST/GET/browser polling, then the
         background loop owns progression until shutdown (S05-C03).
    Shutdown: stop/join the chain orchestrator BEFORE the worker so no new
    chain Jobs are created while the worker drains, then stop/join the
    worker poll loop (the reconciler runs in the same thread as its caller;
    there is no separate reconciler thread to join — :meth:`Lifecycle.stop`
    stops the worker).
    """
    job_service = deps.get_job_service()
    job_service.initialize()
    session_factory = job_service.session_factory
    if session_factory is None:
        raise RuntimeError("job service has no session factory after initialize")
    lifecycle = Lifecycle(job_service, session_factory)
    lifecycle.initialize()
    lifecycle.start()
    analyze_orchestrator.get_analyze_orchestrator().ensure_started()
    app.state.lifecycle = lifecycle
    try:
        yield
    finally:
        analyze_orchestrator.get_analyze_orchestrator().stop(timeout=5.0)
        lifecycle.stop()


app = FastAPI(
    title="MotionForge 2D API",
    version="0.2.0",
    description="Local-first 2D animation motion extraction and replacement",
    redirect_slashes=False,
    lifespan=lifespan,
)

# Cross-origin security boundary (S08-H02): a *configurable allowlist* of the
# real frontend origins — never "*".  Credentials stay off (local JWT-free
# app; no cookie auth).  An untrusted Origin (or "null") on any
# state-changing request is rejected with 403 BEFORE its route runs, preflight
# OPTIONS from an untrusted origin receive no ACAO, and native/CLI clients
# with no Origin header follow the local-app contract.  The allowlist is read
# live from config so launchers/tests can set MOTIONFORGE_CORS_ORIGINS.
app.add_middleware(
    OriginGuardMiddleware,
    origins_provider=lambda: deps.get_config().cors_origins,
    allow_credentials=bool(deps.get_config().cors_allow_credentials),
)

# Register route modules
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(frames.router)
app.include_router(channels.router)
# Durable Project API (S03-T02) — isolated under /api/v2/projects, never
# shadows the legacy /api/projects router (AC7 namespace isolation).
app.include_router(durable_projects.router)
# Durable Video Item API (S03-T03) — nested under the UUID-constrained
# /api/v2/projects/{project_id:uuid}/videos namespace, disjoint from every
# legacy route (AC1/AC9 namespace isolation).
app.include_router(durable_videos.router)
# Durable Project summary read model (S03-T04) — read-only collection and
# item routes under the isolated /api/v2/projects namespace.
app.include_router(durable_summaries.router)
# Durable Character Library API (S06-T01) — /api/v2/characters namespace,
# disjoint from every legacy route (AC1/AC9 namespace isolation).
app.include_router(durable_characters.router)
# Durable Object Intelligence API (S08-T01) — /api/v2/object-intelligence namespace, disjoint from every legacy route.  # noqa: E501
app.include_router(object_intelligence.router)
# Durable Object Candidate Extraction API (S08-T02) — /api/v2/object-intelligence/extraction namespace, disjoint from every legacy route.  # noqa: E501
app.include_router(object_extraction.router)
app.include_router(object_grouping.router)
app.include_router(object_correction.router)
# Durable Structural Evidence API (S08-A02-T01-R2) — isolated under
# /api/v2/structural-evidence, disjoint from every legacy route and from
# /api/v2/object-intelligence (R2 §4).
app.include_router(structural_evidence.router)
# Durable Project Cast Mapping API (S07-T01) — /api/v2/project-cast, disjoint legacy.
app.include_router(project_cast.router)
# Durable ReskinConfig API (S09-T01) — /api/v2/reskin-configs, disjoint from
# every legacy route and from /api/v2/project-cast.
app.include_router(reskin_config.router)
# Durable QC Item READ-ONLY API (S11-T02B) - GET list/detail/filter only (Decision A).
app.include_router(qc_items.router)
app.include_router(qc_check_runs.router)
app.include_router(qc_navigation.router)
app.include_router(readiness.router)
# Server-owned original-audio attach action (S11-T04C) — Decision H: the
# client payload carries ONLY {video_item_id}; the A/V recheck triggers on
# the verified attach completion (worker-side) with a route-side backfill
# for completed/reused attach jobs.
app.include_router(original_audio_action.router)


# Durable S09 demo-loop API (S09-T03) — /api/v2/s09-demo-loops, disjoint
# from every legacy route and from /api/v2/reskin-configs.
app.include_router(s09_demo_loops.router)


# Durable S09 demo comparison API (S09-T04) — /api/v2/s09-demo-compare,
# disjoint from every legacy route, from /api/v2/reskin-configs and from
# the T03 /api/v2/s09-demo-loops namespace.
app.include_router(s09_demo_compare.router)


# Durable targeted-correction API (S09-T05A) — /api/v2/s09-corrections.
# Production wiring per S09 FULL_SPRINT review F4 / fast-track §8 T56:
# the frontend calls this namespace; isolated-app test mounts alone do not
# satisfy production registration.
app.include_router(s09_correction.router)


# Immutable approval/checkpoint API (S09-T06A) — /api/v2/s09-approvals.
# Same F4/T56 production wiring: routes commit explicitly under real
# get_db_session semantics (close-only dependency), so checkpoints survive
# process restart/reload without any test-only auto-commit.
app.include_router(s09_approval.router)


# Durable FullApply orchestration API (S10-T01C) — /api/v2 FullApply.
# Additive, project-scoped; HTTP returns without performing full render
# synchronously — the durable worker executes outside the request.
app.include_router(s10_full_apply.router)


# S12 export preflight (S12-T01) — POST-only verdict, never renders in request.
app.include_router(s12_export_preflight.router)


# S12 export durable jobs (S12-T03C) — submit/status/cancel/retry; the
# request pins rows only, the durable worker renders outside the request.
app.include_router(s12_export.router)


# Public StructuralLock producer (S09-LOCK-PRODUCER-B01) — POST
# /api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock;
# server-derived current source/evidence lock, disjoint from every legacy
# route and from the /api/v2/structural-evidence namespace.
app.include_router(structural_lock.router)


# Public shot-anchor API (MF-END-15 C15) — durable anchor job submit/status/
# retry plus preview/accept/reject/video-gate, layered over the EXISTING job
# authority: the request only pins durable rows, the worker runs the anchor.
app.include_router(shot_anchors.router)


@app.get("/health")
@app.get("/api/v1/health")
@app.head("/health")
@app.head("/api/v1/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "motionforge-2d"}


@app.exception_handler(InvalidPathIdentifierError)
async def invalid_identifier_handler(
    _request: Request, exc: InvalidPathIdentifierError,
) -> JSONResponse:
    """Stable 422 for any uncaught unsafe identifier (S08-H02-C1).

    The centralized resolver (:class:`app.workflow.project_workflow.
    ProjectWorkflowService`) raises this for a hostile project/object
    identifier before any filesystem join; routes that do not translate it
    explicitly must still answer a stable 4xx, never a 500.
    """
    return JSONResponse({"detail": str(exc)}, status_code=422)

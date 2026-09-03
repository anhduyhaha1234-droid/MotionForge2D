"""S11-T03G (W8) — server-owned check-run action + read authority routes.

Decision A surface (the plan's listed server-owned actions):

  POST /api/v2/projects/{project_id}/qc-check-runs
      submit a durable RUN_QC_CHECKS job for one video.  The payload
      carries ONLY {video_item_id, scope} (schema forbids extra fields);
      the server validates ownership, resolves the scope's detector band
      from the registry and composes the check inputs from PERSISTED
      video evidence (never from client-supplied values).  202 Accepted
      (worker executes outside the request); 409 for an active duplicate;
      422 fail-closed for invalid scope / missing persisted evidence.
  GET  /api/v2/projects/{project_id}/qc-check-runs/{video_item_id}
      read authority: latest check-run state, classified against the
      CURRENT video evidence fingerprint + policy hash (stale filtered).
  GET  /api/v2/projects/{project_id}/qc-check-runs/{video_item_id}/readiness
      fail-closed readiness verdict (Decision F consumption point).

There is NO arbitrary QCItem CRUD here and nothing else mutates.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, get_job_service
from app.persistence.jobs import IdempotencyKeyInUse
from app.persistence.models import Project
from app.persistence.qc_check_runs import (
    check_run_readiness,
    latest_check_run_state,
)
from app.schemas.qc_check_runs import (
    QcCheckRunReadinessResponse,
    QcCheckRunStateResponse,
    QcCheckRunSubmitRequest,
    QcCheckRunSubmitResponse,
)
from app.services import video_import
from app.services.video_import import (
    CODE_OWNERSHIP_MISMATCH,
    CODE_PROJECT_NOT_FOUND,
    CODE_VIDEO_ITEM_NOT_FOUND,
    VideoImportError,
)
from app.workflow.qc_checks_handler import (
    QC_RUN_EVIDENCE_UNAVAILABLE,
    QC_RUN_MISSING_ARGS,
    QC_RUN_UNKNOWN_SCOPE,
    QcCheckRunSubmitError,
    compose_check_run_args,
    evidence_fingerprint,
    policy_bundle,
    submit_run_qc_checks,
)

router = APIRouter(prefix="/api/v2", tags=["qc-check-runs"])

#: Submission-time codes that map to 422 (fail-closed request semantics).
_422_CODES = frozenset(
    {QC_RUN_UNKNOWN_SCOPE, QC_RUN_MISSING_ARGS, QC_RUN_EVIDENCE_UNAVAILABLE}
)


def _resolve_workspace(session: Session, project_id: str) -> str:
    """Workspace of an existing project (404 when the project is missing)."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail=f"project {project_id!r} not found",
        )
    return str(project.workspace_id)


def _map_video_import_error(exc: VideoImportError) -> HTTPException:
    if exc.code in (CODE_VIDEO_ITEM_NOT_FOUND, CODE_PROJECT_NOT_FOUND):
        return HTTPException(status_code=404, detail=exc.message)
    if exc.code == CODE_OWNERSHIP_MISMATCH:
        return HTTPException(status_code=409, detail=exc.message)
    return HTTPException(status_code=422, detail=exc.message)


@router.post(
    "/projects/{project_id}/qc-check-runs",
    status_code=202,
    response_model=QcCheckRunSubmitResponse,
)
def submit_qc_check_run(
    project_id: str,
    body: QcCheckRunSubmitRequest,
    session: SessionDep,
) -> QcCheckRunSubmitResponse:
    """Server-owned POST: queue the durable RUN_QC_CHECKS job (202)."""
    workspace_id = _resolve_workspace(session, project_id)
    try:
        video_import._validate_ownership(  # noqa: SLF001 - established contract
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
        )
    except VideoImportError as exc:
        raise _map_video_import_error(exc) from exc
    try:
        detector_args = compose_check_run_args(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
            scope=body.scope,
        )
        result = submit_run_qc_checks(
            get_job_service().session_factory,  # type: ignore[arg-type]
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
            scope=body.scope,
            detector_args=detector_args,
        )
    except QcCheckRunSubmitError as exc:
        code = str(exc.code)
        if code in _422_CODES:
            raise HTTPException(status_code=422, detail=f"{code}: {exc.message}") from exc
        raise HTTPException(status_code=400, detail=f"{code}: {exc.message}") from exc
    except VideoImportError as exc:
        raise _map_video_import_error(exc) from exc
    except IdempotencyKeyInUse as exc:
        raise HTTPException(
            status_code=409,
            detail=f"IdempotencyKeyInUse: {exc}",
        ) from exc
    return QcCheckRunSubmitResponse(
        job_id=result.job_id,
        reused=result.reused,
        state="queued",
        idempotency_key=result.idempotency_key,
        scope=body.scope,
    )


@router.get(
    "/projects/{project_id}/qc-check-runs/{video_item_id}",
    response_model=QcCheckRunStateResponse,
)
def get_qc_check_run_state(
    project_id: str,
    video_item_id: str,
    session: SessionDep,
) -> QcCheckRunStateResponse:
    """Read authority: latest check-run state (stale-filtered)."""
    workspace_id = _resolve_workspace(session, project_id)
    try:
        video_import._validate_ownership(  # noqa: SLF001 - established contract
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
    except VideoImportError as exc:
        raise _map_video_import_error(exc) from exc

    state = latest_check_run_state(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        evidence_fingerprint=evidence_fingerprint(
            session, workspace_id=workspace_id, video_item_id=video_item_id
        ),
        policy_content_hash=policy_bundle()["policy_content_hash"],
    )
    return QcCheckRunStateResponse(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        run_state=state.run_state,
        job_id=state.job_id,
        job_state=state.job_state,
        idempotency_key=state.idempotency_key,
        evidence_fingerprint=state.evidence_fingerprint,
        policy_content_hash=state.policy_content_hash,
        scope=state.scope,
        scope_fingerprint=state.scope_fingerprint,
        detector_revisions=state.detector_revisions,
        summary=state.summary,
        zero_item_completion=state.zero_item_completion,
        evidence_matches=state.evidence_matches,
        policy_matches=state.policy_matches,
        latest_error=state.latest_error,
        check_state_detail=state.check_state_detail,
    )


@router.get(
    "/projects/{project_id}/qc-check-runs/{video_item_id}/readiness",
    response_model=QcCheckRunReadinessResponse,
)
def get_qc_check_run_readiness(
    project_id: str,
    video_item_id: str,
    session: SessionDep,
) -> QcCheckRunReadinessResponse:
    """Fail-closed readiness (Decision F consumption point)."""
    workspace_id = _resolve_workspace(session, project_id)
    try:
        video_import._validate_ownership(  # noqa: SLF001 - established contract
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
        )
    except VideoImportError as exc:
        raise _map_video_import_error(exc) from exc

    current_fp = evidence_fingerprint(
        session, workspace_id=workspace_id, video_item_id=video_item_id
    )
    readiness = check_run_readiness(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        evidence_fingerprint=current_fp,
        policy_content_hash=policy_bundle()["policy_content_hash"],
    )
    return QcCheckRunReadinessResponse(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        status=readiness.status,
        run_state=readiness.run_state,
        blockers=readiness.blockers,
        zero_item_completion=readiness.zero_item_completion,
        evidence_matches=readiness.evidence_matches,
        policy_matches=readiness.policy_matches,
        policy_id=readiness.policy_id,
        policy_content_hash=readiness.policy_content_hash,
        current_evidence_fingerprint=current_fp,
        check_state_detail=readiness.check_state_detail,
        latest_job_id=readiness.latest_job_id,
    )
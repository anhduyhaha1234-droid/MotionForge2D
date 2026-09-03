"""S11-T04C (W11) — server-owned original-audio attach action (Decision H).

  POST /api/v2/projects/{project_id}/original-audio-attach
      attach the ORIGINAL audio for one video_item.  The payload carries
      ONLY ``{video_item_id}`` (extra fields are forbidden — a client can
      never pick a handler/provider or supply a filesystem path).  The
      server resolves the source from the VideoItem's ``source_artifact_id``
      authority (``submit_attach_original_audio``) and the managed root
      from its own JobService config, queues the durable
      ATTACH_ORIGINAL_AUDIO job and answers 202.  The A/V recheck
      (RUN_QC_CHECKS, audio scope) is enqueued ONLY after the attach's
      verified output-validation completion (worker-side hook); a route
      that receives a COMPLETED/REUSED attach job — which executes nothing
      new — ensures the recheck here so a missing run is BACKFILLED
      (idempotent through the T03G submit authority).

  Failure semantics (fail-closed, mirroring the S11 server-owned
  surfaces): 409 for an ACTIVE duplicate (IdempotencyKeyInUse), 404 for
  unknown project/video, 409 for ownership mismatch, 422 for any
  request-side problem (extra fields, source not attachable, recheck
  evidence missing).  Nothing else mutates: exactly one POST, zero
  PUT/PATCH/DELETE, no detection-ledger resolution.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, get_job_service
from app.persistence.jobs import IdempotencyKeyInUse
from app.persistence.models import Project
from app.services import video_import
from app.services.qc_av_recheck import (
    AvRecheckEnqueueError,
    attach_recheck_evidence,
    ensure_av_recheck,
)
from app.services.video_import import (
    CODE_OWNERSHIP_MISMATCH,
    CODE_PROJECT_NOT_FOUND,
    CODE_VIDEO_ITEM_NOT_FOUND,
    VideoImportError,
)
from app.workflow.original_audio_handler import (
    AttachAudioError,
    submit_attach_original_audio,
)
from app.workflow.qc_checks_handler import (
    QC_RUN_EVIDENCE_UNAVAILABLE,
    QC_RUN_MISSING_ARGS,
    QC_RUN_UNKNOWN_SCOPE,
    QcCheckRunSubmitError,
)

router = APIRouter(prefix="/api/v2", tags=["original-audio-action"])

#: Submission-time codes that map to 422 (fail-closed request semantics).
_422_CODES = frozenset(
    {QC_RUN_UNKNOWN_SCOPE, QC_RUN_MISSING_ARGS, QC_RUN_EVIDENCE_UNAVAILABLE}
)


class OriginalAudioAttachRequest(BaseModel):
    """The ONLY accepted client input — the video_item id.

    ``extra="forbid"`` makes any attempt to pass a path, handler, provider
    or source artifact id fail closed with 422 (Decision H — the server
    owns the resolution).
    """

    video_item_id: str
    model_config = ConfigDict(extra="forbid")


class OriginalAudioAttachResponse(BaseModel):
    """Server-owned action result (202 for both fresh and reused submits)."""

    job_id: str
    reused: bool
    state: str
    recheck_job_id: str | None = None
    recheck_state: str | None = None


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


def _map_recheck_enqueue_error(exc: AvRecheckEnqueueError) -> HTTPException:
    """Fail-closed: a reused-attach path without recheck coverage is 422."""
    return HTTPException(
        status_code=422,
        detail=f"{exc.code}: {exc.message}",
    )


@router.post(
    "/projects/{project_id}/original-audio-attach",
    status_code=202,
    response_model=OriginalAudioAttachResponse,
)
def attach_original_audio_action(
    project_id: str,
    body: OriginalAudioAttachRequest,
    session: SessionDep,
) -> OriginalAudioAttachResponse:
    """Server-owned POST: queue the durable ATTACH_ORIGINAL_AUDIO job."""
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

    service = get_job_service()
    session_factory = service.session_factory
    if session_factory is None:
        raise HTTPException(
            status_code=500,
            detail="job service has no session factory",
        )
    try:
        result = submit_attach_original_audio(
            session_factory,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
            managed_root=service.managed_root,
        )
    except AttachAudioError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{exc.code}: {exc.message}",
        ) from exc
    except VideoImportError as exc:
        raise _map_video_import_error(exc) from exc
    except IdempotencyKeyInUse as exc:
        raise HTTPException(
            status_code=409,
            detail=f"IdempotencyKeyInUse: {exc}",
        ) from exc

    # A COMPLETED/REUSED attach job executes nothing new — the worker-side
    # verified-completion hook never runs again, so the A/V recheck must be
    # ensured here (idempotent: an existing run is reused, a missing one is
    # backfilled, an enqueue problem fails this request closed).
    recheck_job_id: str | None = None
    recheck_state: str | None = None
    if result.reused:
        evidence = attach_recheck_evidence(
            session_factory,
            workspace_id=workspace_id,
            attach_job_id=result.job_id,
        )
        if evidence is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "RECHECK_EVIDENCE_UNAVAILABLE: the completed attach job "
                    "carries no successful attempt evidence; cannot backfill "
                    "the A/V recheck"
                ),
            )
        try:
            recheck = ensure_av_recheck(
                session_factory,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=body.video_item_id,
                attach_result=evidence,
                generation="1",
            )
        except AvRecheckEnqueueError as exc:
            raise _map_recheck_enqueue_error(exc) from exc
        except QcCheckRunSubmitError as exc:
            code = str(exc.code)
            status = 422 if code in _422_CODES else 400
            raise HTTPException(
                status_code=status,
                detail=f"{code}: {exc.message}",
            ) from exc
        recheck_job_id = recheck.job_id
        recheck_state = recheck.state

    return OriginalAudioAttachResponse(
        job_id=result.job_id,
        reused=result.reused,
        state="reused" if result.reused else "queued",
        recheck_job_id=recheck_job_id,
        recheck_state=recheck_state,
    )
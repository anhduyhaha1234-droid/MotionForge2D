"""S11-T05A (W12) — readiness aggregate READ-ONLY route (Decision F).

``GET /api/v2/projects/{project_id}/readiness`` computes the aggregate ON
THE FLY from QCItem + durable check-run evidence — there is NO readiness
table and NO migration.  The per-video verdicts are consumed from the T03G
read authority (``check_run_readiness``); ``app/persistence/summaries.py``
capability flip is the ONLY other production change of this task.

The surface is GET-only by construction — zero mutation method decorators
exist in this router (Decision A hold); QCItem rows are created only by
check runs through the internal repository.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.persistence.models import Project
from app.persistence.readiness import (
    ProjectReadinessRecord,
    ReadinessBlockerRecord,
    ReadinessVideoRecord,
    compute_project_readiness,
)
from app.schemas.qc_navigation import CanonicalLocationData, NavigationActionData
from app.schemas.readiness import (
    ReadinessBlocker,
    ReadinessResponse,
    ReadinessVideo,
)

router = APIRouter(prefix="/api/v2", tags=["readiness"])


def _resolve_workspace(session: Session, project_id: str) -> str:
    """Workspace of an existing project (404 when the project is missing)."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail=f"project {project_id!r} not found",
        )
    return str(project.workspace_id)


def _map_blocker(record: ReadinessBlockerRecord) -> ReadinessBlocker:
    return ReadinessBlocker(
        qc_item_id=record.qc_item_id,
        code=record.code,
        video_item_id=record.video_item_id,
        layer_ref_type=record.layer_ref_type,
        layer_ref_id=record.layer_ref_id,
        location=CanonicalLocationData(**record.location),
        reason_vi=record.reason_vi,
        action_vi=record.action_vi,
        action=NavigationActionData(**record.action),
    )


def _map_video(record: ReadinessVideoRecord) -> ReadinessVideo:
    return ReadinessVideo(
        video_item_id=record.video_item_id,
        status=record.status,
        run_state=record.run_state,
        check_state_detail=record.check_state_detail,
        zero_item_completion=record.zero_item_completion,
        latest_job_id=record.latest_job_id,
        blockers=record.blockers,
    )


@router.get("/projects/{project_id}/readiness", response_model=ReadinessResponse)
def get_project_readiness(
    project_id: str,
    session: SessionDep,
) -> ReadinessResponse:
    """Compute the readiness aggregate on the fly (Decision F, GET-only)."""
    workspace_id = _resolve_workspace(session, project_id)
    record: ProjectReadinessRecord = compute_project_readiness(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return ReadinessResponse(
        status=record.status,
        blockers=[_map_blocker(b) for b in record.blockers],
        warning_count=record.warning_count,
        videos=[_map_video(v) for v in record.videos],
        policy_version=record.policy_version,
        content_hash=record.content_hash,
        computed_at=record.computed_at,
    )
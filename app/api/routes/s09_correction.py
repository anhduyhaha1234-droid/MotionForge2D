"""HTTP surface for S09 targeted corrections (S09-T05A).

POST /api/v2/s09-corrections            submit (idempotent, typed payload)
GET  /api/v2/s09-corrections/{id}       read one
GET  /api/v2/s09-corrections            list (workspace/video scoped)
POST /api/v2/s09-corrections/{id}/confirm  CAS pending -> applied
POST /api/v2/s09-corrections/{id}/cancel   CAS pending -> cancelled
GET  /api/v2/videos/{video_id}/s09-correction-counts  benchmark feed

NOTE: intentionally NOT wired into app.api.app within this task — the
app.py include_router line is outside this task's write allowlist; the
integration owner adds ONE line there.  Tests mount the router on an
isolated FastAPI app.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.persistence.structural_evidence import (
    ContactNotFoundError,
    MotionNotFoundError,
    SegmentNotFoundError,
)
from app.schemas.s09_correction import (
    ConfirmCorrectionRequest,
    ContactCorrectionRequest,
    CorrectionCountsOut,
    CorrectionListOut,
    CorrectionOut,
    MaskCorrectionRequest,
    MeshPartsCorrectionRequest,
    RouteOverrideCorrectionRequest,
    SubmitCorrectionRequest,
    SubmittedCorrectionOut,
    ZOrderCorrectionRequest,
)
from app.services.s09_correction import (
    CorrectionConflictError,
    CorrectionImpact,
    CorrectionNotFoundError,
    CorrectionRecord,
    CorrectionValidationError,
    RouteOverrideProvenanceError,
    S09CorrectionRepository,
)

router = APIRouter(
    prefix="/api/v2",
    tags=["s09-corrections"],
)


def _repo(session: Session) -> S09CorrectionRepository:
    return S09CorrectionRepository(session)


def _http_status(err: Exception) -> int:
    if isinstance(err, CorrectionNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(err, CorrectionConflictError):
        return status.HTTP_409_CONFLICT
    if isinstance(err, CorrectionValidationError):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    return status.HTTP_500_INTERNAL_SERVER_ERROR


#: Referenced-but-missing structural objects are client conflicts (409),
#: never 500 — the request was well-formed but points outside the
#: workspace's durable graph.
_MISSING_OBJECT_ERRORS = (
    ContactNotFoundError,
    MotionNotFoundError,
    SegmentNotFoundError,
)


def _out(record: CorrectionRecord) -> CorrectionOut:
    return CorrectionOut(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        video_item_id=record.video_item_id,
        occurrence_segment_id=record.occurrence_segment_id,
        correction_kind=record.correction_kind,
        status=record.status,
        request=record.request,
        impact=record.impact,
        result=record.result,
        applied_at=record.applied_at,
        cancelled_at=record.cancelled_at,
        idempotency_key=record.idempotency_key,
        natural_key=record.natural_key,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("/s09-corrections", response_model=SubmittedCorrectionOut)
def submit_correction(
    body: SubmitCorrectionRequest,
    session: SessionDep,
    response: Response,
) -> SubmittedCorrectionOut:
    repo = _repo(session)
    payload = body.payload
    try:
        kind = {
            MaskCorrectionRequest: "mask",
            ZOrderCorrectionRequest: "z_order",
            ContactCorrectionRequest: "contact",
            MeshPartsCorrectionRequest: "mesh_parts",
            RouteOverrideCorrectionRequest: "route_override",
        }[type(payload)]

        request_dict: dict[str, Any] = payload.model_dump(exclude_none=True)
        if body.affected_loop_ids:
            request_dict["affected_loop_ids"] = list(body.affected_loop_ids)
        # route_override reads project/video ids from the archived request
        # dict; inject the ENVELOPE values (ownership already asserted on
        # them) so a payload can never point the route row elsewhere.
        if kind == "route_override":
            request_dict["project_id"] = body.project_id
            request_dict["video_item_id"] = body.video_item_id

        impact: CorrectionImpact = repo.compute_impact(
            body.workspace_id,
            body.project_id,
            body.video_item_id,
            kind,
            request_dict,
        )
        record, created = repo.create_correction(
            body.workspace_id,
            body.project_id,
            body.video_item_id,
            kind,
            request_dict,
            impact,
            idempotency_key=body.idempotency_key,
        )
    except (
        CorrectionConflictError,
        CorrectionNotFoundError,
        CorrectionValidationError,
        RouteOverrideProvenanceError,
    ) as err:
        raise HTTPException(_http_status(err), str(err)) from err
    except _MISSING_OBJECT_ERRORS as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    session.commit()
    # Repo convention (s09_demo_loops / object_correction): 201 when a new
    # correction is archived; 200 on an idempotent replay.
    response.status_code = 200 if not created else 201
    return SubmittedCorrectionOut(
        correction=_out(record), created=created, replayed=not created
    )


@router.get("/s09-corrections/{correction_id}", response_model=CorrectionOut)
def get_correction(correction_id: str, workspace_id: str, session: SessionDep) -> CorrectionOut:
    try:
        record = _repo(session).get_correction(workspace_id, correction_id)
    except CorrectionNotFoundError as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    return _out(record)


@router.get("/s09-corrections", response_model=CorrectionListOut)
def list_corrections(
    session: SessionDep,
    workspace_id: str,
    video_item_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CorrectionListOut:
    items, total = _repo(session).list_corrections(
        workspace_id, video_item_id=video_item_id, limit=limit, offset=offset
    )
    return CorrectionListOut(
        items=[_out(r) for r in items], total=total, limit=limit, offset=offset
    )


@router.post("/s09-corrections/{correction_id}/confirm", response_model=CorrectionOut)
def confirm_correction(
    correction_id: str, body: ConfirmCorrectionRequest, session: SessionDep
) -> CorrectionOut:
    try:
        record, _applied = _repo(session).confirm_correction(
            body.workspace_id, correction_id, body.revision
        )
    except (
        CorrectionConflictError,
        CorrectionNotFoundError,
        CorrectionValidationError,
    ) as err:
        raise HTTPException(_http_status(err), str(err)) from err
    session.commit()
    return _out(record)


@router.post("/s09-corrections/{correction_id}/cancel", response_model=CorrectionOut)
def cancel_correction(
    correction_id: str, body: ConfirmCorrectionRequest, session: SessionDep
) -> CorrectionOut:
    try:
        record, _cancelled = _repo(session).cancel_correction(
            body.workspace_id, correction_id, body.revision
        )
    except (
        CorrectionConflictError,
        CorrectionNotFoundError,
        CorrectionValidationError,
    ) as err:
        raise HTTPException(_http_status(err), str(err)) from err
    session.commit()
    return _out(record)


@router.get(
    "/videos/{video_item_id}/s09-correction-counts",
    response_model=CorrectionCountsOut,
)
def correction_counts(
    video_item_id: str, workspace_id: str, session: SessionDep
) -> CorrectionCountsOut:
    counts = _repo(session).applied_correction_counts(workspace_id, video_item_id)
    by_kind = counts["by_kind"]
    assert isinstance(by_kind, dict)
    return CorrectionCountsOut(total=int(counts["total"]), by_kind=dict(by_kind))


__all__ = ["router"]

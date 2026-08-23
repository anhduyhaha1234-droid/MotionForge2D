"""Targeted object correction API (S08-T05).

Isolated under ``/api/v2/object-intelligence/corrections`` (disjoint from
every T01/T02/T03 route):

- ``POST /preview`` — the pre-confirmation impacted-scope report (read-only;
  ZERO durable writes).
- ``POST /`` — create the durable pending correction (impact archived);
  natural-key replay returns the same row (200).
- ``POST /{id}/confirm`` — CAS ``pending -> applied``: targeted mutation +
  supersession of exactly the invalidated suggestions + the
  ``RECOMPUTE_OBJECTS`` Job (only where recompute is needed) in ONE
  transaction.  Replay returns the recorded result (200).
- ``GET /{id}`` / ``GET /`` — read-only status (the honest recompute outcome
  follows the successor chain).
- ``POST /{id}/cancel`` — pending correction: CAS cancel; applied correction:
  durable cancel of the recompute Job through the public JobService.
- ``POST /{id}/recompute/retry`` — successor Job for a terminal
  failed/cancelled recompute (contract §6.4), idempotent.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import SessionDep, get_job_service
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import IdempotencyKeyInUse
from app.persistence.object_correction import (
    CorrectionConflictError,
    CorrectionNotFoundError,
    ObjectCorrectionRepository,
)
from app.persistence.object_grouping import OperationConflictError
from app.persistence.object_intelligence import (
    OccurrenceNotFoundError,
    OwnershipMismatchError,
    RoleConflictError,
    RoleNotFoundError,
)
from app.schemas.object_correction import (
    CorrectionCancelRequest,
    CorrectionConfirmRequest,
    CorrectionCreateResponse,
    CorrectionData,
    CorrectionListResponse,
    CorrectionRequest,
    ImpactData,
    RecomputeStateData,
)

router = APIRouter(
    prefix="/api/v2/object-intelligence/corrections", tags=["object-correction"]
)
WORKSPACE_ID = DEFAULT_WORKSPACE_ID

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "reassign": [
        "occurrence_id",
        "occurrence_revision",
        "source_role_id",
        "target_role_id",
    ],
    "candidate_edit": ["target", "role_id"],
    "merge": ["target_role_id", "target_revision", "source_role_ids"],
    "split": ["target_role_id", "target_revision", "original_role_id"],
}


def _request_dict(body: CorrectionRequest) -> dict[str, object]:
    """The canonical correction request dict (set fields only)."""
    payload = body.model_dump(exclude_unset=True, by_alias=True)
    missing = [field for field in _REQUIRED_FIELDS[body.kind] if field not in payload]
    if missing:
        raise HTTPException(
            422,
            f"correction kind {body.kind!r} requires: {', '.join(missing)}",
        )
    if body.kind == "candidate_edit":
        if payload.get("target") == "role":
            missing_edit = [
                field
                for field in ("name", "role_kind", "description")
                if field not in payload
            ]
            if len(missing_edit) == 3:
                raise HTTPException(
                    422, "candidate_edit(target=role) requires at least one edited field"
                )
            if "role_revision" not in payload:
                raise HTTPException(422, "candidate_edit(target=role) requires role_revision")
        else:
            if "occurrence_id" not in payload or "occurrence_revision" not in payload:
                raise HTTPException(
                    422,
                    "candidate_edit(target=occurrence) requires occurrence_id "
                    "and occurrence_revision",
                )
            if not any(k in payload for k in ("bbox", "confidence", "review_state", "reasons")):
                raise HTTPException(
                    422,
                    "candidate_edit(target=occurrence) requires at least one "
                    "edited field",
                )
    payload["generation"] = body.generation
    return payload


def _repo(session: SessionDep) -> ObjectCorrectionRepository:
    return ObjectCorrectionRepository(session)


def _impact_data(impact: object) -> ImpactData:
    """Map a CorrectionImpact to the DTO (mypy-safe attribute access)."""
    from app.persistence.object_correction import CorrectionImpact

    assert isinstance(impact, CorrectionImpact)
    return ImpactData(
        correction_type=impact.correction_type,
        affected_role_ids=list(impact.affected_role_ids),
        affected_occurrence_ids=list(impact.affected_occurrence_ids),
        invalidated_suggestion_ids=list(impact.invalidated_suggestion_ids),
        artifact_role_ids=list(impact.artifact_role_ids),
        regenerate_suggestions=impact.regenerate_suggestions,
        recompute_needed=impact.recompute_needed,
        counts=dict(impact.counts),
    )


@router.post("/preview")
@router.post("/preview/")
def preview_correction(
    body: CorrectionRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> ImpactData:
    """Impacted-scope report BEFORE confirmation — ZERO durable writes."""
    repo = _repo(session)
    try:
        impact = repo.compute_impact(
            workspace_id,
            body.project_id,
            body.video_item_id,
            body.kind,
            _request_dict(body),
        )
    except CorrectionNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except (CorrectionConflictError, RoleConflictError, OccurrenceNotFoundError) as err:
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    return _impact_data(impact)


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_correction(
    body: CorrectionRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> CorrectionCreateResponse:
    """Create the durable pending correction (natural-key replay -> 200)."""
    repo = _repo(session)
    try:
        request_dict = _request_dict(body)
        impact = repo.compute_impact(
            workspace_id, body.project_id, body.video_item_id, body.kind, request_dict
        )
        record, created = repo.create_correction(
            workspace_id,
            body.project_id,
            body.video_item_id,
            body.kind,
            request_dict,
            impact,
            idempotency_key=body.idempotency_key,
        )
        session.commit()
    except (CorrectionConflictError, RoleConflictError, OccurrenceNotFoundError) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        response.status_code = 200
    return CorrectionCreateResponse(
        correction=CorrectionData.from_record(record),
        created=created,
        status=record.status,
    )


@router.post("/{correction_id:uuid}/confirm", status_code=201)
@router.post("/{correction_id:uuid}/confirm/", status_code=201)
def confirm_correction(
    correction_id: uuid.UUID,
    body: CorrectionConfirmRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> CorrectionData:
    """Apply the pending correction exactly once (atomic CAS)."""
    svc = get_job_service()
    if svc.session_factory is None:
        raise HTTPException(503, "job service is not initialized")
    repo = _repo(session)
    try:
        record, created = repo.confirm_correction(
            workspace_id,
            str(correction_id),
            body.revision,
            managed_root=str(svc.managed_root),
        )
        session.commit()
    except CorrectionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except (
        CorrectionConflictError,
        OwnershipMismatchError,
        RoleConflictError,
        RoleNotFoundError,
        OccurrenceNotFoundError,
        OperationConflictError,
        IdempotencyKeyInUse,
    ) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        response.status_code = 200
    recompute = RecomputeStateData(**repo.recompute_state(workspace_id, str(correction_id)))
    return CorrectionData.from_record(record, recompute=recompute)


@router.get("/{correction_id:uuid}")
@router.get("/{correction_id:uuid}/")
def get_correction(
    correction_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CorrectionData:
    repo = _repo(session)
    try:
        record = repo.get_correction(workspace_id, str(correction_id))
    except CorrectionNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    recompute = RecomputeStateData(**repo.recompute_state(workspace_id, str(correction_id)))
    return CorrectionData.from_record(record, recompute=recompute)


@router.get("")
@router.get("/")
def list_corrections(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    video_item_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CorrectionListResponse:
    repo = _repo(session)
    records, total = repo.list_corrections(
        workspace_id, video_item_id=video_item_id, limit=limit, offset=offset
    )
    return CorrectionListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        corrections=[
            CorrectionData.from_record(
                record,
                recompute=RecomputeStateData(
                    **repo.recompute_state(workspace_id, record.id)
                ),
            )
            for record in records
        ],
    )


@router.post("/{correction_id:uuid}/cancel")
@router.post("/{correction_id:uuid}/cancel/")
def cancel_correction(
    correction_id: uuid.UUID,
    body: CorrectionCancelRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CorrectionData:
    """Cancel: pending -> durable CAS cancel; applied -> durable job cancel."""
    repo = _repo(session)
    try:
        record = repo.get_correction(workspace_id, str(correction_id))
        if record.status == "applied":
            state = repo.recompute_state(workspace_id, str(correction_id))
            job_id = state.get("job_id")
            if job_id is not None and state.get("status") not in (
                "completed",
                "failed",
                "cancelled",
            ):
                svc = get_job_service()
                if svc.session_factory is None:
                    raise HTTPException(503, "job service is not initialized")
                svc.cancel_job(str(job_id))
            final = repo.recompute_state(workspace_id, str(correction_id))
            return CorrectionData.from_record(
                record, recompute=RecomputeStateData(**final)
            )
        record = repo.cancel_correction(
            workspace_id, str(correction_id), body.revision
        )
        session.commit()
    except CorrectionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except CorrectionConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    recompute = RecomputeStateData(**repo.recompute_state(workspace_id, str(correction_id)))
    return CorrectionData.from_record(record, recompute=recompute)


@router.post("/{correction_id:uuid}/recompute/retry")
@router.post("/{correction_id:uuid}/recompute/retry/")
def retry_recompute(
    correction_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CorrectionData:
    """Retry the recompute work: successor Job (contract §6.4), idempotent."""
    repo = _repo(session)
    try:
        repo.create_recompute_successor(workspace_id, str(correction_id))
        session.commit()
        record = repo.get_correction(workspace_id, str(correction_id))
    except CorrectionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except CorrectionConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    recompute = RecomputeStateData(**repo.recompute_state(workspace_id, str(correction_id)))
    return CorrectionData.from_record(record, recompute=recompute)

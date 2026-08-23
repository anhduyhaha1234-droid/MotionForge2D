"""Cross-scene grouping and curation API routes (S08-T03).

Isolated under ``/api/v2/object-intelligence/grouping`` (disjoint from every
T01/T02 route):

- ``POST /suggestions/generate`` — deterministic, idempotent generation of
  REVIEWABLE suggestions.  Suggestions are always ``pending`` — this
  endpoint NEVER confirms a role.
- ``GET /suggestions`` / ``GET /suggestions/{id}`` — read-only review list
  and detail exposing confidence + reasons + provenance.
- ``POST /suggestions/{id}/dismiss`` — explicit rejection (CAS).
- ``POST /roles/{id}/merge|split|confirm`` — explicit durable mutations with
  CAS/revision protection, idempotent replay and audit history.
- ``GET /operations`` / ``GET /operations/{id}`` — read-only audit history.

All read endpoints are side-effect free (no commit, no write).  All write
endpoints roll back before raising and map domain errors to stable HTTP
codes (404 missing, 409 conflict/ownership, 422 value).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import SessionDep
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import REMOVAL_ONLY_KINDS
from app.persistence.object_grouping import (
    ObjectGroupingRepository,
    OperationConflictError,
    OperationNotFoundError,
    SuggestionConflictError,
    SuggestionNotFoundError,
    VideoItemNotFoundError,
)
from app.persistence.object_intelligence import (
    OwnershipMismatchError,
    RoleConflictError,
    RoleNotFoundError,
    RoleRecord,
)
from app.schemas.object_grouping import (
    ConfirmRequest,
    ConfirmResultData,
    GenerateResultData,
    GenerateSuggestionsRequest,
    GroupingPolicyData,
    MergeRequest,
    MergeResultData,
    OperationData,
    OperationListResponse,
    SplitRequest,
    SplitResultData,
    SuggestionData,
    SuggestionDismissRequest,
    SuggestionListResponse,
)
from app.schemas.object_intelligence import RoleData
from app.services.object_grouping import (
    DEFAULT_GROUPING_ALGORITHM,
    OccurrenceEvidence,
    RoleEvidence,
    generate_pair_suggestions,
    grouping_policy,
)

router = APIRouter(
    prefix="/api/v2/object-intelligence/grouping", tags=["object-grouping"]
)
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


def _repo(session: SessionDep) -> ObjectGroupingRepository:
    return ObjectGroupingRepository(session)


def _evidence(record: RoleRecord) -> RoleEvidence:
    return RoleEvidence(
        role_id=record.id,
        name=record.name,
        kind=record.kind,
        source_generation=record.source_generation,
        occurrences=tuple(
            OccurrenceEvidence(
                scene_id=occ.scene_id,
                frame_index=occ.frame_index,
                time_ms=occ.time_ms,
                bbox_x=occ.bbox_x,
                bbox_y=occ.bbox_y,
                bbox_w=occ.bbox_w,
                bbox_h=occ.bbox_h,
            )
            for occ in (record.occurrences or [])
        ),
    )


@router.get("/policy")
@router.get("/policy/")
def get_grouping_policy() -> GroupingPolicyData:
    """Backend-authoritative grouping policy metadata (read-only).

    Algorithm/calibration version, confidence semantics, review
    threshold and the advisory guarantee.  Read-only: zero durable
    mutations.
    """
    return GroupingPolicyData.from_policy(grouping_policy())


@router.post("/suggestions/generate", status_code=201)
@router.post("/suggestions/generate/", status_code=201)
def generate_suggestions(
    body: GenerateSuggestionsRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> GenerateResultData:
    """Deterministic grouping run; idempotent (same rows replay).

    Generation is CURRENT-generation only (finding C2 #5): the requested
    ``source_generation`` must equal the backend-authoritative current
    generation of the video item; otherwise the run fails closed with ZERO
    mutation.
    """
    repo = _repo(session)
    try:
        repo.assert_generation_current(
            workspace_id, body.video_item_id, body.source_generation
        )
        project_id = repo.get_video_project(workspace_id, body.video_item_id)
        superseded_count = repo.supersede_stale_suggestions(
            workspace_id,
            body.video_item_id,
            body.source_generation,
            body.algorithm_version,
            body.scope,
        )
        roles = repo.list_active_roles(
            workspace_id, project_id, body.video_item_id, body.source_generation
        )
        algorithm = DEFAULT_GROUPING_ALGORITHM
        pairs = generate_pair_suggestions(
            [_evidence(record) for record in roles],
            removal_only_kinds=REMOVAL_ONLY_KINDS,
            algorithm=algorithm,
            algorithm_version=body.algorithm_version,
        )
        created_count = 0
        replayed_count = 0
        records = []
        for pair in pairs:
            record, created = repo.create_suggestion(
                workspace_id,
                project_id,
                body.video_item_id,
                body.source_generation,
                list(pair.role_ids),
                pair.confidence,
                list(pair.reasons),
                pair.algorithm,
                pair.algorithm_version,
                scope=body.scope,
            )
            records.append(record)
            if created:
                created_count += 1
            else:
                replayed_count += 1
        session.commit()
    except (OwnershipMismatchError, RoleConflictError, OperationConflictError) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except VideoItemNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except SuggestionConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if created_count == 0 and records:
        # Fully idempotent replay of an earlier generation run.
        response.status_code = 200
    policy = grouping_policy(
        algorithm=algorithm, algorithm_version=body.algorithm_version
    )
    return GenerateResultData(
        video_item_id=body.video_item_id,
        source_generation=body.source_generation,
        algorithm=algorithm,
        algorithm_version=body.algorithm_version,
        calibration_version=policy.calibration_version,
        scope=body.scope,
        created_count=created_count,
        replayed_count=replayed_count,
        superseded_count=superseded_count,
        total=len(records),
        suggestions=[SuggestionData.from_record(r) for r in records],
        policy=GroupingPolicyData.from_policy(policy),
    )


@router.get("/suggestions")
@router.get("/suggestions/")
def list_suggestions(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    video_item_id: str | None = None,
    status: str | None = None,
    role_id: str | None = None,
    source_generation: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SuggestionListResponse:
    """Suggestions list; CURRENT-generation default, historical explicit.

    WITHOUT ``source_generation`` only suggestions of the backend current
    generation are returned (``scope="current"``).  An explicit
    ``source_generation`` is the ONLY way to inspect a non-current
    generation (``scope="historical"``) and it is never mixed into the
    current list.  Read-only: zero durable mutations.
    """
    repo = _repo(session)
    records, total = repo.list_suggestions(
        workspace_id,
        video_item_id=video_item_id,
        status=status,
        role_id=role_id,
        source_generation=source_generation,
        only_current=source_generation is None,
        limit=limit,
        offset=offset,
    )
    current_generation: str | None = None
    if video_item_id is not None:
        try:
            current_generation = repo.current_generation(
                workspace_id, video_item_id
            )
        except RoleNotFoundError:
            current_generation = None
    scope = "historical" if source_generation is not None else "current"
    return SuggestionListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        scope=scope,
        source_generation=source_generation,
        current_generation=current_generation,
        suggestions=[SuggestionData.from_record(r) for r in records],
    )


@router.get("/suggestions/{suggestion_id:uuid}")
@router.get("/suggestions/{suggestion_id:uuid}/")
def get_suggestion(
    suggestion_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    source_generation: str | None = None,
) -> SuggestionData:
    """Suggestion detail; current-scope default, historical via explicit
    ``source_generation`` (404 under the current scope for a stale
    suggestion — historical inspection is a separate explicit contract)."""
    repo = _repo(session)
    try:
        return SuggestionData.from_record(
            repo.get_suggestion(
                workspace_id,
                str(suggestion_id),
                only_current=source_generation is None,
                source_generation=source_generation,
            )
        )
    except SuggestionNotFoundError as err:
        raise HTTPException(404, str(err)) from err


@router.post("/suggestions/{suggestion_id:uuid}/dismiss")
@router.post("/suggestions/{suggestion_id:uuid}/dismiss/")
def dismiss_suggestion(
    suggestion_id: uuid.UUID,
    body: SuggestionDismissRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> SuggestionData:
    repo = _repo(session)
    try:
        record = repo.dismiss_suggestion(
            workspace_id, str(suggestion_id), body.revision
        )
        session.commit()
        return SuggestionData.from_record(record)
    except SuggestionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except SuggestionConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err


@router.post("/roles/{role_id:uuid}/merge", status_code=201)
@router.post("/roles/{role_id:uuid}/merge/", status_code=201)
def merge_roles(
    role_id: uuid.UUID,
    body: MergeRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> MergeResultData:
    """Explicit durable merge; CAS on the target; natural-key replay."""
    repo = _repo(session)
    try:
        project_id = repo.get_video_project(workspace_id, body.video_item_id)
        operation, target, created = repo.apply_merge(
            workspace_id,
            project_id,
            body.video_item_id,
            str(role_id),
            body.source_role_ids,
            body.revision,
            suggestion_id=body.suggestion_id,
            idempotency_key=body.idempotency_key,
            note=body.note,
        )
        session.commit()
    except RoleNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except SuggestionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except (
        OwnershipMismatchError,
        RoleConflictError,
        OperationConflictError,
    ) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        # Idempotent replay of an earlier merge: same operation, 200.
        response.status_code = 200
    return MergeResultData(
        operation=OperationData.from_record(operation),
        target_role=RoleData.from_record(target),
    )


@router.post("/roles/{role_id:uuid}/split", status_code=201)
@router.post("/roles/{role_id:uuid}/split/", status_code=201)
def split_role(
    role_id: uuid.UUID,
    body: SplitRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> SplitResultData:
    """Explicit durable split; CAS on the target; natural-key replay."""
    repo = _repo(session)
    try:
        project_id = repo.get_video_project(workspace_id, body.video_item_id)
        operation, created_role, created = repo.apply_split(
            workspace_id,
            project_id,
            body.video_item_id,
            str(role_id),
            body.original_role_id,
            body.revision,
            idempotency_key=body.idempotency_key,
            note=body.note,
        )
        session.commit()
    except (RoleNotFoundError, OperationNotFoundError) as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except (
        OwnershipMismatchError,
        RoleConflictError,
        OperationConflictError,
    ) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        response.status_code = 200
    return SplitResultData(
        operation=OperationData.from_record(operation),
        created_role=RoleData.from_record(created_role),
    )


@router.post("/roles/{role_id:uuid}/confirm", status_code=201)
@router.post("/roles/{role_id:uuid}/confirm/", status_code=201)
def confirm_role(
    role_id: uuid.UUID,
    body: ConfirmRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> ConfirmResultData:
    """Explicit durable confirm; CAS + audit; natural-key replay."""
    repo = _repo(session)
    try:
        project_id = repo.get_video_project(workspace_id, body.video_item_id)
        operation, role, created = repo.apply_confirm(
            workspace_id,
            project_id,
            body.video_item_id,
            str(role_id),
            body.revision,
            idempotency_key=body.idempotency_key,
            note=body.note,
        )
        session.commit()
    except RoleNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except (
        OwnershipMismatchError,
        RoleConflictError,
        OperationConflictError,
    ) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        response.status_code = 200
    return ConfirmResultData(
        operation=OperationData.from_record(operation),
        role=RoleData.from_record(role),
    )


@router.get("/operations")
@router.get("/operations/")
def list_operations(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    video_item_id: str | None = None,
    operation_type: str | None = None,
    role_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperationListResponse:
    repo = _repo(session)
    records, total = repo.list_operations(
        workspace_id,
        video_item_id=video_item_id,
        operation_type=operation_type,
        role_id=role_id,
        limit=limit,
        offset=offset,
    )
    return OperationListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        operations=[OperationData.from_record(r) for r in records],
    )


@router.get("/operations/{operation_id:uuid}")
@router.get("/operations/{operation_id:uuid}/")
def get_operation(
    operation_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> OperationData:
    repo = _repo(session)
    try:
        return OperationData.from_record(
            repo.get_operation(workspace_id, str(operation_id))
        )
    except OperationNotFoundError as err:
        raise HTTPException(404, str(err)) from err

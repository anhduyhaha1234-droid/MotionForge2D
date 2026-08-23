"""Durable Object Intelligence API routes (S08-T01).

Implements the focused API contract for video-global ``ObjectRole`` identity
and ``ObjectOccurrence`` scene/frame evidence under the isolated
``/api/v2/object-intelligence`` namespace (disjoint from every legacy route).

- Read endpoints are side-effect free (no commit, no write).
- Write endpoints are idempotent where requested (idempotency key for roles,
  natural ``(role, scene, frame)`` key for occurrences).
- Ownership is validated fail-closed on every operation; cross-owner requests
  are rejected with 409.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import SessionDep, get_project_workflow
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    OBJECT_KINDS,
    REMOVAL_ONLY_KINDS,
    SOURCE_OVERLAY_KIND,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
    OccurrenceConflictError,
    OccurrenceNotFoundError,
    OwnershipMismatchError,
    RoleConflictError,
    RoleNotFoundError,
)
from app.schemas.object_intelligence import (
    LegacyMappingItemData,
    LegacyMappingResponse,
    OccurrenceCreateRequest,
    OccurrenceData,
    OccurrenceUpdateRequest,
    RoleCreateRequest,
    RoleData,
    RoleKindData,
    RoleKindsResponse,
    RoleListResponse,
    RoleUpdateRequest,
)

router = APIRouter(prefix="/api/v2/object-intelligence", tags=["object-intelligence"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.post("", status_code=201)
@router.post("/", status_code=201)
@router.post("/roles", status_code=201)
@router.post("/roles/", status_code=201)
def create_role(
    body: RoleCreateRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> RoleData:
    repo = ObjectIntelligenceRepository(session)
    try:
        record, created = repo.create_role(
            workspace_id=workspace_id,
            project_id=body.project_id,
            video_item_id=body.video_item_id,
            source_generation=body.source_generation,
            name=body.name,
            kind=body.kind,
            status=body.status,
            description=body.description,
            legacy_object_id=body.legacy_object_id,
            legacy_scene_id=body.legacy_scene_id,
            idempotency_key=body.idempotency_key,
        )
        session.commit()
    except OwnershipMismatchError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except RoleConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        # Idempotent replay: return the existing durable role with 200.
        response.status_code = 200
    return RoleData.from_record(record)


@router.get("")
@router.get("/")
@router.get("/roles")
@router.get("/roles/")
def list_roles(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    video_item_id: str | None = None,
    status: str | None = None,
    generation: str | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RoleListResponse:
    """List roles — CURRENT source generation by default (T01-C2).

    - No ``generation``: ONLY roles in the backend-authoritative current
      source generation of their video item (``scope="current"``).
    - ``generation=N``: EXPLICIT generation view — exactly generation N,
      marked ``scope="current"`` when N equals the backend current, else
      ``scope="historical"``.  The two scopes are never mixed.
    - ``kind`` (S08-A01): optional canonical-kind filter — one of the seven
      ObjectRole kinds; an unknown kind is a stable 422, never a silent
      empty/coercion.
    """
    repo = ObjectIntelligenceRepository(session)
    current_generation: str | None = None
    scope = "current"
    try:
        if video_item_id is not None:
            current_generation = repo.current_generation(workspace_id, video_item_id)
    except RoleNotFoundError:
        # A nonexistent video item is an empty current view (404 would
        # leak nothing and break the gallery's "no video yet" state).
        return RoleListResponse(
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
            total=0,
            roles=[],
            scope="current",
            current_generation=None,
        )
    if generation is not None:
        scope = (
            "current"
            if current_generation is not None and generation == current_generation
            else "historical"
        )
        try:
            records, total = repo.list_roles(
                workspace_id=workspace_id,
                video_item_id=video_item_id,
                status=status,
                source_generation=generation,
                kind=kind,
                limit=limit,
                offset=offset,
            )
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
    else:
        try:
            records, total = repo.list_roles(
                workspace_id=workspace_id,
                video_item_id=video_item_id,
                status=status,
                kind=kind,
                only_current=True,
                limit=limit,
                offset=offset,
            )
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
    return RoleListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        roles=[RoleData.from_record(r) for r in records],
        scope=scope,
        current_generation=current_generation,
    )


@router.get("/kinds")
@router.get("/kinds/")
def role_kinds() -> RoleKindsResponse:
    """The canonical seven-kind ObjectRole taxonomy (S08-A01).

    Backend-authoritative role/layer taxonomy — the ONE place clients derive
    their seven-kind options from (gallery filter, edit dialogs).  The
    removal-only policy flag marks ``source_overlay`` so it is never
    presented as a Character Pack / replacement candidate.
    """
    return RoleKindsResponse(
        kinds=[
            RoleKindData(
                name=kind,
                removal_only=kind in REMOVAL_ONLY_KINDS,
            )
            for kind in OBJECT_KINDS
        ],
        source_overlay=SOURCE_OVERLAY_KIND,
    )


@router.get("/roles/{role_id:uuid}")
@router.get("/roles/{role_id:uuid}/")
def get_role(
    role_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    generation: str | None = None,
) -> RoleData:
    """Role detail — current-scope by default (T01-C2).

    A role from a STALE source generation is 404 unless an explicit
    ``generation`` is supplied matching it (historical detail is a separate,
    explicit contract — never mixed into the current view).
    """
    repo = ObjectIntelligenceRepository(session)
    try:
        return RoleData.from_record(
            repo.get_role(
                workspace_id,
                str(role_id),
                only_current=generation is None,
                source_generation=generation,
            )
        )
    except RoleNotFoundError as err:
        raise HTTPException(404, str(err)) from err


@router.patch("/roles/{role_id:uuid}")
@router.patch("/roles/{role_id:uuid}/")
def update_role(
    role_id: uuid.UUID,
    body: RoleUpdateRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> RoleData:
    repo = ObjectIntelligenceRepository(session)
    try:
        record = repo.update_role(
            workspace_id=workspace_id,
            role_id=str(role_id),
            revision=body.revision,
            name=body.name,
            kind=body.kind,
            status=body.status,
            description=body.description,
            supersedes_role_id=body.supersedes_role_id,
        )
        session.commit()
        return RoleData.from_record(record)
    except RoleNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except RoleConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err


@router.get("/roles/{role_id:uuid}/occurrences")
@router.get("/roles/{role_id:uuid}/occurrences/")
def list_occurrences(
    role_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> list[OccurrenceData]:
    repo = ObjectIntelligenceRepository(session)
    try:
        records = repo.list_occurrences(workspace_id, str(role_id))
    except RoleNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return [OccurrenceData.from_record(r) for r in records]


@router.post("/roles/{role_id:uuid}/occurrences", status_code=201)
@router.post("/roles/{role_id:uuid}/occurrences/", status_code=201)
def create_occurrence(
    role_id: uuid.UUID,
    body: OccurrenceCreateRequest,
    session: SessionDep,
    response: Response,
    workspace_id: str = WORKSPACE_ID,
) -> OccurrenceData:
    repo = ObjectIntelligenceRepository(session)
    try:
        record, created = repo.create_occurrence(
            workspace_id=workspace_id,
            role_id=str(role_id),
            scene_id=body.scene_id,
            frame_index=body.frame_index,
            time_ms=body.time_ms,
            bbox_x=body.bbox.x,
            bbox_y=body.bbox.y,
            bbox_w=body.bbox.width,
            bbox_h=body.bbox.height,
            confidence=body.confidence,
            confidence_source=body.confidence_source,
            algorithm=body.algorithm,
            algorithm_version=body.algorithm_version,
            reasons=body.reasons,
            review_state=body.review_state,
        )
        session.commit()
    except OwnershipMismatchError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except RoleNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except OccurrenceConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    if not created:
        # Idempotent natural-key replay: return the existing occurrence with 200.
        response.status_code = 200
    return OccurrenceData.from_record(record)


@router.patch("/roles/{role_id:uuid}/occurrences/{occurrence_id:uuid}")
@router.patch("/roles/{role_id:uuid}/occurrences/{occurrence_id:uuid}/")
def update_occurrence(
    role_id: uuid.UUID,
    occurrence_id: uuid.UUID,
    body: OccurrenceUpdateRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> OccurrenceData:
    # Fail closed: the occurrence must belong to EXACTLY this role in this
    # workspace — a role-A URL can never update a role-B occurrence.
    repo = ObjectIntelligenceRepository(session)
    bbox = body.bbox
    try:
        record = repo.update_occurrence(
            workspace_id=workspace_id,
            role_id=str(role_id),
            occurrence_id=str(occurrence_id),
            revision=body.revision,
            confidence=body.confidence,
            review_state=body.review_state,
            reasons=body.reasons,
            bbox_x=bbox.x if bbox is not None else None,
            bbox_y=bbox.y if bbox is not None else None,
            bbox_w=bbox.width if bbox is not None else None,
            bbox_h=bbox.height if bbox is not None else None,
        )
        session.commit()
        return OccurrenceData.from_record(record)
    except OccurrenceNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except OccurrenceConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err


@router.get("/legacy-mapping/{project_id}")
@router.get("/legacy-mapping/{project_id}/")
def legacy_mapping(
    project_id: str,
    session: SessionDep,
) -> LegacyMappingResponse:
    """Read-only compatibility mapping from legacy project JSON.

    Loads the legacy project record (read-only), maps every legacy
    ``TrackedObject`` to an EPHEMERAL role id and its occurrence evidence.
    Nothing is written: no commit, no legacy record mutation, and the
    ephemeral ids are never durable truth.
    """
    pwf = get_project_workflow()
    try:
        project_data = pwf.get_project(project_id)
    except FileNotFoundError as err:
        raise HTTPException(404, f"project {project_id!r} not found") from err
    legacy_dict = (
        project_data.model_dump() if hasattr(project_data, "model_dump") else dict(project_data)
    )
    repo = ObjectIntelligenceRepository(session)
    mapping = repo.map_legacy_objects(project_id, legacy_dict)
    return LegacyMappingResponse(
        project_id=project_id,
        source=mapping.source,
        mapped_objects=[
            LegacyMappingItemData(
                legacy_object_id=item.legacy_object_id,
                legacy_scene_id=item.legacy_scene_id,
                legacy_name=item.legacy_name,
                legacy_kind=item.legacy_kind,
                suggested_name=item.suggested_name,
                ephemeral_role_id=item.ephemeral_role_id,
                occurrence_evidence=item.occurrence_evidence,
                source_kind=item.source_kind,
                kind_normalization_reason=item.kind_normalization_reason,
            )
            for item in mapping.mapped_objects
        ],
        note=mapping.note,
    )

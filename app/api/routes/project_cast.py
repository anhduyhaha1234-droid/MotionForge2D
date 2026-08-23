"""Project Cast Mapping API routes (S07-T01 + S07-T02 picker/compat).

Isolated router under /api/v2/project-cast (disjoint from every legacy route).
Built on the verified durable core app.persistence.project_cast — this layer
is the strict API boundary (no business logic, no silent fallback).

Contract:
- Create (POST): idempotent via idempotency_key; equivalent replay 200, conflict 409;  # noqa: E501
  compatibility enforced via authoritative repo policy.
- Get (GET /{id}): single mapping, workspace-isolated, 404 no leak.
- List (GET /): paginated, optionally filtered by project_id, workspace-isolated.
- Update (PATCH /{id}): CAS with revision, stale 409, concurrent one winner; compatibility enforced.
- Delete (DELETE /{id}): CAS required, missing revision → 422, stale → 409, cross-workspace → 404.
- Picker (GET /picker/packs): browse packs, published only, deterministic.
- Compatibility (POST /compatibility/evaluate): deterministic pure eval via same repo function.
- Strict schemas: extra=forbid, strict=True → unknown field 422, no wrong coercion.
- No client workspace authority: workspace_id is server-owned DEFAULT_WORKSPACE_ID.
- Deterministic serialization via typed Pydantic read models.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.api.deps import SessionDep
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.models import (
    Character,
    CharacterPackVersion,
)
from app.persistence.project_cast import (
    ProjectCastConflictError,
    ProjectCastNotFoundError,
    ProjectCastOwnershipError,
    ProjectCastRepository,
    evaluate_compatibility,
)
from app.schemas.project_cast import (
    CompatibilityEvaluateRequest,
    CompatibilityEvaluateResponse,
    PickerPackItem,
    PickerPacksResponse,
    ProjectCastCreateRequest,
    ProjectCastData,
    ProjectCastListResponse,
    ProjectCastUpdateRequest,
)

router = APIRouter(prefix="/api/v2/project-cast", tags=["project-cast"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_mapping(
    body: ProjectCastCreateRequest,
    session: SessionDep,
    response: Response,
    ) -> ProjectCastData:
    repo = ProjectCastRepository(session)
    try:
        record, created = repo.create_mapping(
            workspace_id=WORKSPACE_ID,
            project_id=body.project_id,
            object_role_id=body.object_role_id,
            character_id=body.character_id,
            pack_version_id=body.pack_version_id,
            idempotency_key=body.idempotency_key,
            fallback_acknowledged=body.fallback_acknowledged,
        )
        session.commit()
    except ProjectCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "cast mapping conflict") from err
    if not created:
        response.status_code = 200
    return ProjectCastData.from_record(record)


@router.get("/picker/packs", status_code=200)
def picker_packs(
    session: SessionDep,
        q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PickerPacksResponse:
    from sqlalchemy import func as _func

    filters = [
        CharacterPackVersion.workspace_id == WORKSPACE_ID,
        CharacterPackVersion.status == "published",
    ]
    base_q = (
        select(CharacterPackVersion, Character)
        .join(Character, Character.id == CharacterPackVersion.character_id)
        .where(*filters)
    )
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        base_q = base_q.where(
            (_func.lower(Character.name).like(term))
            | (_func.lower(Character.code).like(term))
            | (_func.lower(CharacterPackVersion.id).like(term))
        )
    count_q = select(_func.count()).select_from(base_q.subquery())
    total = int(session.scalar(count_q) or 0)
    rows = session.execute(
        base_q.options(joinedload(CharacterPackVersion.assets))
        .order_by(CharacterPackVersion.created_at.desc(), CharacterPackVersion.id)
        .offset(offset)
        .limit(limit)
    ).unique().all()
    packs: list[PickerPackItem] = []
    for pack, char in rows:
        packs.append(
            PickerPackItem(
                id=pack.id,
                character_id=pack.character_id,
                workspace_id=pack.workspace_id,
                version=pack.version,
                status=pack.status,
                character_name=char.name,
                character_code=char.code,
                character_type=char.character_type,
                symmetry=char.symmetry,
                published_at=pack.published_at,
                revision=pack.revision,
                created_at=pack.created_at,
                updated_at=pack.updated_at,
                asset_count=len(pack.assets or []),
                pose_slots=[a.pose_slot for a in (pack.assets or [])],
            )
        )
    return PickerPacksResponse(
        workspace_id=WORKSPACE_ID,
        limit=limit,
        offset=offset,
        total=total,
        packs=packs,
        query=q,
    )


@router.post("/compatibility/evaluate", status_code=200)
def evaluate_compatibility_route(
    body: CompatibilityEvaluateRequest,
    session: SessionDep,
    ) -> CompatibilityEvaluateResponse:
    pack = session.get(CharacterPackVersion, body.pack_version_id)
    char_id = pack.character_id if pack is not None else ""
    result = evaluate_compatibility(
        session,
        workspace_id=WORKSPACE_ID,
        project_id=body.project_id,
        object_role_id=body.object_role_id,
        character_id=char_id,
        pack_version_id=body.pack_version_id,
        expected_revision=body.expected_revision,
        mapping_id=body.mapping_id,
    )
    return CompatibilityEvaluateResponse(
        compatible=result.compatible,
        reasons=result.reasons,
        fallback_allowed=result.fallback_allowed,
        fallback_description=result.fallback_description,
        blocked=result.blocked,
        pinned_version_id=result.pinned_version_id,
        current_revision=result.current_revision,
        workspace_id=result.workspace_id,
    )


@router.get("", status_code=200)
@router.get("/", status_code=200)
def list_mappings(
    session: SessionDep,
        project_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectCastListResponse:
    repo = ProjectCastRepository(session)
    try:
        records, total = repo.list_mappings(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
    except ProjectCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return ProjectCastListResponse(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        limit=limit,
        offset=offset,
        total=total,
        mappings=[ProjectCastData.from_record(r) for r in records],
    )


@router.get("/{mapping_id:uuid}", status_code=200)
@router.get("/{mapping_id:uuid}/", status_code=200)
def get_mapping(
    mapping_id: uuid.UUID,
    session: SessionDep,
    ) -> ProjectCastData:
    repo = ProjectCastRepository(session)
    try:
        record = repo.get_mapping(str(mapping_id), WORKSPACE_ID)
    except ProjectCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return ProjectCastData.from_record(record)


@router.patch("/{mapping_id:uuid}", status_code=200)
@router.patch("/{mapping_id:uuid}/", status_code=200)
def update_mapping(
    mapping_id: uuid.UUID,
    body: ProjectCastUpdateRequest,
    session: SessionDep,
    ) -> ProjectCastData:
    repo = ProjectCastRepository(session)
    try:
        record = repo.update_mapping(
            str(mapping_id),
            WORKSPACE_ID,
            expected_revision=body.revision,
            pack_version_id=body.pack_version_id,
            character_id=body.character_id,
            fallback_acknowledged=body.fallback_acknowledged,
        )
        session.commit()
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    return ProjectCastData.from_record(record)


@router.delete("/{mapping_id:uuid}", status_code=204)
@router.delete("/{mapping_id:uuid}/", status_code=204)
def delete_mapping(
    mapping_id: uuid.UUID,
    session: SessionDep,
        revision: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    repo = ProjectCastRepository(session)
    # F-C: workspace-scoped lookup MUST precede the revision requirement so a
    # cross-workspace mapping id yields 404 (no existence leak) even when the
    # caller omitted revision; only a mapping that exists in THIS workspace
    # proceeds to the 422 missing-revision branch below.
    try:
        repo.get_mapping(str(mapping_id), WORKSPACE_ID)
    except ProjectCastNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    if revision is None:
        raise HTTPException(422, "revision is required for delete")
    try:
        repo.delete_mapping(str(mapping_id), WORKSPACE_ID, expected_revision=revision)
        session.commit()
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    return Response(status_code=204)

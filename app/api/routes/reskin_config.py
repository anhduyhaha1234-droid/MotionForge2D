"""ReskinConfig API routes (S09-T01).

Isolated router under /api/v2/reskin-configs (disjoint from every legacy
route). Built on the verified durable core app.persistence.reskin_config —
this layer is the strict API boundary (no business logic, no silent
fallback), mirroring app/api/routes/project_cast.py.

Contract:
- Create (POST): idempotent via idempotency_key; equivalent replay → 200,
  conflicting payload → 409; params validated fail-closed (422);
  compatibility enforced via the reused authoritative S07 policy.
- Get (GET /{id}): single config, workspace-isolated, 404 no leak.
- List (GET /): paginated, optionally filtered by project_id.
- Update (PATCH /{id}): CAS with revision — stale → 409 zero mutation;
  compatibility re-enforced on repin.
- Strict schemas: extra=forbid, strict=True → unknown field 422.
- No client workspace authority: workspace_id is server-owned
  DEFAULT_WORKSPACE_ID.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError

from app.api.deps import SessionDep
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.reskin_config import (
    ReskinConfigConflictError,
    ReskinConfigNotFoundError,
    ReskinConfigOwnershipError,
    ReskinConfigRepository,
)
from app.schemas.reskin_config import (
    RendererRouteEvidence,
    ReskinConfigCreateRequest,
    ReskinConfigData,
    ReskinConfigListResponse,
    ReskinConfigUpdateRequest,
)

router = APIRouter(prefix="/api/v2/reskin-configs", tags=["reskin-config"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_reskin_config(
    body: ReskinConfigCreateRequest,
    session: SessionDep,
    response: Response,
) -> ReskinConfigData:
    repo = ReskinConfigRepository(session)
    try:
        record, created = repo.create_config(
            workspace_id=WORKSPACE_ID,
            project_id=body.project_id,
            object_role_id=body.object_role_id,
            character_id=body.character_id,
            pack_version_id=body.pack_version_id,
            params=body.params.to_domain(),
            idempotency_key=body.idempotency_key,
            cast_mapping_id=body.cast_mapping_id,
            structural_lock_manifest_id=body.structural_lock_manifest_id,
        )
        session.commit()
    except ReskinConfigOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ReskinConfigConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ReskinConfigNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "reskin config conflict") from err
    if not created:
        response.status_code = 200
    return ReskinConfigData.from_record(record)


@router.get("", status_code=200)
@router.get("/", status_code=200)
def list_reskin_configs(
    session: SessionDep,
    project_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReskinConfigListResponse:
    repo = ReskinConfigRepository(session)
    try:
        records, total = repo.list_configs(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
    except ReskinConfigNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return ReskinConfigListResponse(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        limit=limit,
        offset=offset,
        total=total,
        configs=[ReskinConfigData.from_record(r) for r in records],
    )


@router.get("/{config_id:uuid}", status_code=200)
@router.get("/{config_id:uuid}/", status_code=200)
def get_reskin_config(config_id: uuid.UUID, session: SessionDep) -> ReskinConfigData:
    repo = ReskinConfigRepository(session)
    try:
        record = repo.get_config(str(config_id), WORKSPACE_ID)
    except ReskinConfigNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return ReskinConfigData.from_record(record)


@router.get("/{config_id:uuid}/renderer-route-evidence", status_code=200)
@router.get("/{config_id:uuid}/renderer-route-evidence/", status_code=200)
def get_renderer_route_evidence(
    config_id: uuid.UUID, session: SessionDep
) -> list[RendererRouteEvidence]:
    """CompatibilityPolicy evidence per occurrence segment/shot.

    Returns every persisted SegmentRenderRoute decision tied to the config's
    pinned StructuralLockManifest (empty list when no manifest is pinned).
    Read-only; per-segment evidence, never an opaque global score.
    """
    repo = ReskinConfigRepository(session)
    try:
        rows = repo.list_renderer_route_evidence(WORKSPACE_ID, str(config_id))
    except ReskinConfigNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return [RendererRouteEvidence(**row) for row in rows]


@router.patch("/{config_id:uuid}", status_code=200)
@router.patch("/{config_id:uuid}/", status_code=200)
def update_reskin_config(
    config_id: uuid.UUID,
    body: ReskinConfigUpdateRequest,
    session: SessionDep,
) -> ReskinConfigData:
    repo = ReskinConfigRepository(session)
    try:
        record = repo.update_config(
            str(config_id),
            WORKSPACE_ID,
            expected_revision=body.revision,
            params=body.params.to_domain() if body.params is not None else None,
            pack_version_id=body.pack_version_id,
            character_id=body.character_id,
            structural_lock_manifest_id=(
                body.structural_lock_manifest_id
                if "structural_lock_manifest_id" in body.model_fields_set
                else None
            ),
        )
        session.commit()
    except ReskinConfigNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ReskinConfigConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ReskinConfigOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    return ReskinConfigData.from_record(record)

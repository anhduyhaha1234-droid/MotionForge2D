"""Durable Character Library API routes (S06-T01).

Implements `/api/v2/characters` routes for character CRUD, pack versions, pose assets,
and publishing.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import SessionDep, get_job_service
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import (
    CharacterCodeConflictError,
    CharacterConflictError,
    CharacterNotFoundError,
    CharacterRepository,
    PackVersionConflictError,
    PackVersionImmutableError,
    PackVersionNotFoundError,
    PublishValidationFailedError,
)
from app.schemas.characters import (
    AssetData,
    AttachAssetRequest,
    CharacterArchiveRequest,
    CharacterCreateRequest,
    CharacterData,
    CharacterListResponse,
    CharacterUpdateRequest,
    PackVersionData,
    PublishVersionRequest,
    SetDefaultVersionRequest,
)

router = APIRouter(prefix="/api/v2/characters", tags=["durable-characters"])
WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_character(
    body: CharacterCreateRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CharacterData:
    repo = CharacterRepository(session)
    try:
        record = repo.create_character(
            workspace_id=workspace_id,
            name=body.name,
            code=body.code,
            character_type=body.character_type,
            symmetry=body.symmetry,
            description=body.description,
        )
        session.commit()
        return CharacterData.from_record(record)
    except CharacterCodeConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err


@router.get("")
@router.get("/")
def list_characters(
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CharacterListResponse:
    repo = CharacterRepository(session)
    records, total = repo.list_characters(
        workspace_id=workspace_id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return CharacterListResponse(
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        total=total,
        characters=[CharacterData.from_record(r) for r in records],
    )


@router.get("/{character_id:uuid}")
@router.get("/{character_id:uuid}/")
def get_character(
    character_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CharacterData:
    repo = CharacterRepository(session)
    try:
        record = repo.get_character(str(character_id), workspace_id)
        return CharacterData.from_record(record)
    except CharacterNotFoundError as err:
        raise HTTPException(404, str(err)) from err


@router.patch("/{character_id:uuid}")
@router.patch("/{character_id:uuid}/")
def update_character(
    character_id: uuid.UUID,
    body: CharacterUpdateRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CharacterData:
    repo = CharacterRepository(session)
    try:
        record = repo.update_character(
            character_id=str(character_id),
            workspace_id=workspace_id,
            revision=body.revision,
            name=body.name,
            code=body.code,
            character_type=body.character_type,
            symmetry=body.symmetry,
            description=body.description,
        )
        session.commit()
        return CharacterData.from_record(record)
    except CharacterNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except (CharacterConflictError, CharacterCodeConflictError) as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err


@router.post("/{character_id:uuid}/archive")
@router.post("/{character_id:uuid}/archive/")
def archive_character(
    character_id: uuid.UUID,
    body: CharacterArchiveRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CharacterData:
    repo = CharacterRepository(session)
    try:
        record = repo.archive_character(
            character_id=str(character_id),
            workspace_id=workspace_id,
            revision=body.revision,
        )
        session.commit()
        return CharacterData.from_record(record)
    except CharacterNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except CharacterConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err


@router.post("/{character_id:uuid}/default-version")
@router.post("/{character_id:uuid}/default-version/")
def set_default_version(
    character_id: uuid.UUID,
    body: SetDefaultVersionRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> CharacterData:
    repo = CharacterRepository(session)
    try:
        record = repo.set_default_version(
            character_id=str(character_id),
            workspace_id=workspace_id,
            version_id=body.version_id,
            revision=body.revision,
        )
        session.commit()
        return CharacterData.from_record(record)
    except (CharacterNotFoundError, PackVersionNotFoundError) as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except CharacterConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err


@router.post("/{character_id:uuid}/versions", status_code=201)
@router.post("/{character_id:uuid}/versions/", status_code=201)
def create_pack_version(
    character_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> PackVersionData:
    repo = CharacterRepository(session)
    try:
        record = repo.create_pack_version(str(character_id), workspace_id)
        session.commit()
        return PackVersionData.from_record(record)
    except CharacterNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err


@router.get("/{character_id:uuid}/versions")
@router.get("/{character_id:uuid}/versions/")
def list_pack_versions(
    character_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> list[PackVersionData]:
    repo = CharacterRepository(session)
    records = repo.list_pack_versions(str(character_id), workspace_id)
    return [PackVersionData.from_record(r) for r in records]


@router.post("/versions/{version_id:uuid}/assets")
@router.post("/versions/{version_id:uuid}/assets/")
def attach_asset(
    version_id: uuid.UUID,
    body: AttachAssetRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> AssetData:
    repo = CharacterRepository(session)
    try:
        record = repo.attach_asset(
            version_id=str(version_id),
            workspace_id=workspace_id,
            pose_slot=body.pose_slot,
            artifact_id=body.artifact_id,
        )
        session.commit()
        return AssetData.from_record(record)
    except PackVersionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except PackVersionImmutableError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err


@router.post("/versions/{version_id:uuid}/publish")
@router.post("/versions/{version_id:uuid}/publish/")
def publish_version(
    version_id: uuid.UUID,
    body: PublishVersionRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> PackVersionData:
    repo = CharacterRepository(
        session, storage_root=get_job_service()._managed_root
    )
    try:
        record = repo.publish_pack_version(
            version_id=str(version_id),
            workspace_id=workspace_id,
            revision=body.revision,
        )
        session.commit()
        return PackVersionData.from_record(record)
    except PackVersionNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except PackVersionConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except PublishValidationFailedError as err:
        session.rollback()
        raise HTTPException(422, detail={
            "message": str(err),
            "missing_slots": err.missing_slots,
            "errors": err.errors,
        }) from err

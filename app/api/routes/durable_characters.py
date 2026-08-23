"""Durable Character Library API routes (S06-T01).

Implements `/api/v2/characters` routes for character CRUD, pack versions, pose assets,
and publishing.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import SessionDep, get_managed_root
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import (
    AssetContentError,
    AssetNotFoundError,
    AssetNotReadyError,
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
    PackVersionValidationData,
    PublishVersionRequest,
    SetDefaultVersionRequest,
    asset_content_url,
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
    try:
        record = repo.attach_asset(
            version_id=str(version_id),
            workspace_id=workspace_id,
            pose_slot=body.pose_slot,
            artifact_id=body.artifact_id,
        )
        session.commit()
        # The attach route is version-scoped, so resolve the owning character
        # to build the typed content URL for the returned asset DTO.
        version = repo.get_pack_version(str(version_id), workspace_id)
        return AssetData.from_record(
            record,
            content_url=asset_content_url(
                version.character_id, record.pack_version_id, record.id
            ),
        )
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
    repo = CharacterRepository(session, storage_root=get_managed_root())
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


@router.get(
    "/{character_id:uuid}/versions/{version_id:uuid}/assets/{asset_id:uuid}/content"
)
@router.get(
    "/{character_id:uuid}/versions/{version_id:uuid}/assets/{asset_id:uuid}/content/"
)
def get_asset_content(
    character_id: uuid.UUID,
    version_id: uuid.UUID,
    asset_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> FileResponse:
    """Serve a pose asset's image bytes (S06-R02).

    The content endpoint is the ONLY frontend path to pose bytes.  It verifies
    the character → version → asset ownership chain inside the workspace,
    resolves the file strictly through ``ManagedRoot`` containment, and serves
    only a ready, existing, decodable image with an approved MIME type whose
    size/checksum match the registered metadata.

    Failure semantics (fail closed, no filesystem paths in responses):
    - 404: missing/foreign character, version, asset, or file on disk
    - 409: artifact not in ``ready`` state
    - 422: no approved image MIME, corrupt image, checksum/size mismatch,
      path-escape or symlink-escape
    """
    repo = CharacterRepository(session, storage_root=get_managed_root())
    try:
        _asset, path, mime_type = repo.resolve_asset_content(
            character_id=str(character_id),
            version_id=str(version_id),
            asset_id=str(asset_id),
            workspace_id=workspace_id,
        )
    except (PackVersionNotFoundError, AssetNotFoundError) as err:
        raise HTTPException(404, str(err)) from err
    except AssetNotReadyError as err:
        raise HTTPException(409, str(err)) from err
    except AssetContentError as err:
        raise HTTPException(422, str(err)) from err
    return FileResponse(str(path), media_type=mime_type)


@router.get("/versions/{version_id:uuid}/validation")
@router.get("/versions/{version_id:uuid}/validation/")
def get_pack_version_validation(
    version_id: uuid.UUID,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> PackVersionValidationData:
    """Read-only draft validation for a pack version (S06-R02).

    Runs the SAME authoritative validator as publish
    (:func:`app.workflow.character_validator.validate_character_pack`) without
    publishing or mutating the pack.  Returns required-slot completeness and
    the full actionable error list.
    """
    repo = CharacterRepository(session, storage_root=get_managed_root())
    try:
        result = repo.validate_pack_version(str(version_id), workspace_id)
    except PackVersionNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return PackVersionValidationData(
        version_id=result.version_id,
        character_id=result.character_id,
        workspace_id=result.workspace_id,
        status="valid" if not result.errors else "invalid",
        complete=result.complete,
        missing_slots=result.missing_slots,
        errors=result.errors,
    )

"""Durable Character Library API routes (S06-T01).

Implements `/api/v2/characters` routes for character CRUD, pack versions, pose assets,
and publishing.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import SessionDep, get_config, get_job_service, get_managed_root
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
    ReferenceArtworkData,
    ReferenceAssetJobData,
    ReferenceAssetJobRequest,
    ReferenceAssetJobRetryRequest,
    ReferenceAssetJobSubmitData,
    SetDefaultVersionRequest,
    asset_content_url,
)
from app.workflow import character_reference_ingest, reference_asset_jobs

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

# ── Authored reference-artwork ingest (MF-END-03) ────────────────────────────

#: Typed ingest refusal -> (HTTP status, public code).  Lookup walks the
#: exception MRO, so a specialised subclass can never fall through to its
#: base family's status.
_REFERENCE_ARTWORK_REFUSALS: dict[type, tuple[int, str]] = {
    character_reference_ingest.ReferenceKeyRefusedError: (422, "REFERENCE_KEY_REFUSED"),
    character_reference_ingest.ReferencePurposeRefusedError: (422, "INVALID_PURPOSE"),
    character_reference_ingest.ReferenceFilenameRefusedError: (
        422,
        "REFERENCE_FILENAME_REFUSED",
    ),
    character_reference_ingest.ReferenceArtworkRefusedError: (
        422,
        "REFERENCE_ARTWORK_REFUSED",
    ),
    character_reference_ingest.ReferenceArtworkTooLargeError: (
        413,
        "REFERENCE_ARTWORK_TOO_LARGE",
    ),
    character_reference_ingest.ReferenceArtworkPayloadError: (
        415,
        "REFERENCE_ARTWORK_UNREADABLE",
    ),
    PackVersionNotFoundError: (404, "PACK_VERSION_NOT_FOUND"),
    PackVersionImmutableError: (409, "PACK_VERSION_IMMUTABLE"),
}


def _reference_artwork_refusal(err: BaseException) -> tuple[int, str] | None:
    """Map a typed ingest refusal to ``(status, code)``, else None."""
    for klass in type(err).__mro__:
        mapped = _REFERENCE_ARTWORK_REFUSALS.get(klass)
        if mapped is not None:
            return mapped
    return None


@router.post("/versions/{version_id:uuid}/reference-artwork", status_code=201)
@router.post("/versions/{version_id:uuid}/reference-artwork/", status_code=201)
def ingest_reference_artwork(
    version_id: uuid.UUID,
    file: Annotated[UploadFile, File(...)],
    reference_key: Annotated[str, Form(...)],
    session: SessionDep,
    purpose: Annotated[str, Form()] = "artwork",
    workspace_id: str = WORKSPACE_ID,
) -> ReferenceArtworkData:
    """Ingest authored RGB/RGBA reference artwork into a DRAFT pack version.

    This is the FIRST public route that CREATES an authored artwork
    ``Artifact`` (managed bytes + ready row with sha256/size/mime/dimensions)
    and attaches it to the version under the namespaced reference key
    ``<view>@<role>`` (e.g. ``front@character``).  It reuses the existing
    ``character_asset`` rows, so no schema change is involved, and it returns
    the artifact id, sha256, size, verified MIME, dimensions and provenance.

    Admission is decided by the DECODED bytes plus the declared purpose —
    never by the file extension: accepted colour representations are exactly
    RGB (2) and RGBA (6), so a grey-looking RGB artwork is admitted while a
    single-channel mask (mode ``L`` / PNG colour type 0) is refused and never
    converted into artwork.

    Failure semantics (fail closed, no filesystem paths in responses):
    - 404: version missing or foreign to the workspace
    - 409: version is not a draft (published/archived)
    - 413: payload exceeds the configured byte ceiling
    - 415: empty/corrupt/oversize-pixel payload that is not a decodable
      allowlisted image
    - 422: invalid reference key, mask purpose, mask/unsupported colour
      representation, hostile filename
    """
    storage_root = get_managed_root()
    cfg = get_config()
    written: list[str] = []
    try:
        result = character_reference_ingest.ingest_reference_artwork(
            session=session,
            storage_root=storage_root,
            workspace_id=workspace_id,
            version_id=str(version_id),
            reference_key=reference_key,
            purpose=purpose,
            filename=file.filename,
            stream=file.file,
            max_bytes=cfg.max_image_upload_bytes,
            max_dimension=cfg.max_image_dimension,
            max_pixels=cfg.max_image_pixels,
            written=written,
        )
        session.commit()
    except BaseException as err:
        # Every failure path (service refusal, flush error, commit error)
        # rolls the transaction back AND removes bytes this call wrote.
        session.rollback()
        character_reference_ingest.discard_written_files(storage_root, written)
        mapped = _reference_artwork_refusal(err)
        if mapped is None:
            raise
        status, code = mapped
        code = getattr(err, "code", None) or code
        raise HTTPException(
            status,
            detail={
                "code": code,
                "message": str(err),
                "details": dict(getattr(err, "details", {}) or {}),
            },
        ) from err
    return ReferenceArtworkData.from_result(result)


# ── Reference-asset generation jobs (MF-END-09) ──────────────────────────────

#: Typed refusal code -> HTTP status (fail closed; unlisted codes are 422).
_REFERENCE_ASSET_REFUSAL_STATUS: dict[str, int] = {
    "mf_end09_version_not_found": 404,
    "mf_end09_version_not_draft": 409,
    "mf_end09_target_key_present": 409,
    "mf_end09_source_hash_mismatch": 409,
    "mf_end09_job_not_found": 404,
    "mf_end09_job_not_retryable": 409,
    "mf_end09_idempotency_conflict": 409,
    "mf_end09_graph_pin_mismatch": 500,
    "mf_end09_receipt_incomplete": 500,
}


def _reference_asset_refusal(err: reference_asset_jobs.ReferenceAssetJobError) -> HTTPException:
    status = _REFERENCE_ASSET_REFUSAL_STATUS.get(err.code.value, 422)
    return HTTPException(status, detail=err.as_dict())


def _require_reference_asset_job(job_id: str):
    info = get_job_service().get_job(job_id)
    if info is None or str(info.job_type or "") != reference_asset_jobs.JOB_TYPE_REFERENCE_ASSET:
        raise HTTPException(404, detail={"code": "mf_end09_job_not_found", "job_id": job_id})
    return info


@router.post("/versions/{version_id:uuid}/reference-asset-jobs", status_code=202)
@router.post("/versions/{version_id:uuid}/reference-asset-jobs/", status_code=202)
def submit_reference_asset_job(
    version_id: uuid.UUID,
    body: ReferenceAssetJobRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> ReferenceAssetJobSubmitData:
    """Register ONE durable reference-asset generation intent (async).

    The request only validates the live draft pack and inserts the Job row:
    no engine work and no library write happens inside this request.  The
    worker drives graph G1 and the managed ingest; poll the job status for
    progress, the generated asset (draft only) and the cache key.
    """
    repo = CharacterRepository(session, storage_root=get_managed_root())
    try:
        version = repo.get_pack_version(str(version_id), workspace_id)
    except PackVersionNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    try:
        result = reference_asset_jobs.submit_reference_asset_job(
            job_service=get_job_service(),
            workspace_id=workspace_id,
            character_id=str(version.character_id),
            version_id=str(version_id),
            reference_key=body.reference_key,
            view_prompt=body.view_prompt,
            source_reference_key=body.source_reference_key,
            style_version=body.style_version,
            seed=body.seed,
            idempotency_key=body.idempotency_key,
            input_generation=body.input_generation,
        )
    except reference_asset_jobs.ReferenceAssetJobError as err:
        raise _reference_asset_refusal(err) from err
    return ReferenceAssetJobSubmitData(
        job=ReferenceAssetJobData.from_info(result.job),
        content_key=result.content_key,
        reference_key=result.reference_key,
        view=result.view,
        role=result.role,
        duplicate=result.duplicate,
    )


@router.get("/reference-asset-jobs/{job_id}")
@router.get("/reference-asset-jobs/{job_id}/")
def get_reference_asset_job(job_id: str) -> ReferenceAssetJobData:
    """Durable status of one reference-asset job (reference jobs only)."""
    return ReferenceAssetJobData.from_info(_require_reference_asset_job(job_id))


@router.post("/reference-asset-jobs/{job_id}/cancel")
@router.post("/reference-asset-jobs/{job_id}/cancel/")
def cancel_reference_asset_job(job_id: str) -> dict[str, object]:
    """Durably request cancellation; the attempt identity is preserved."""
    _require_reference_asset_job(job_id)
    job_svc = get_job_service()
    if not job_svc.cancel_job(job_id):
        info = job_svc.get_job(job_id)
        raise HTTPException(400, f"Cannot cancel job in state: {info.state.value}")
    return {"status": "cancel_requested", "job_id": job_id}


@router.post("/reference-asset-jobs/{job_id}/retry", status_code=202)
@router.post("/reference-asset-jobs/{job_id}/retry/", status_code=202)
def retry_reference_asset_job(
    job_id: str,
    body: ReferenceAssetJobRetryRequest,
) -> ReferenceAssetJobSubmitData:
    """Retry a TERMINAL reference-asset job as a new input generation.

    The content key (identity/view/style/graph) is unchanged, so a terminal
    receipt is replayed with zero engine submits instead of generating again.
    """
    _require_reference_asset_job(job_id)
    try:
        result = reference_asset_jobs.resubmit_reference_asset_job(
            job_service=get_job_service(),
            job_id=job_id,
            input_generation=body.input_generation,
        )
    except reference_asset_jobs.ReferenceAssetJobError as err:
        raise _reference_asset_refusal(err) from err
    return ReferenceAssetJobSubmitData(
        job=ReferenceAssetJobData.from_info(result.job),
        content_key=result.content_key,
        reference_key=result.reference_key,
        view=result.view,
        role=result.role,
        duplicate=result.duplicate,
    )

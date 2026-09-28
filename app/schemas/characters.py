"""Pydantic schemas for the Character Library API (S06-T01)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CharacterCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=64)
    character_type: str = Field("character", pattern="^(character|prop|other)$")
    symmetry: str = Field("symmetric", pattern="^(symmetric|asymmetric)$")
    description: str | None = None


class CharacterUpdateRequest(BaseModel):
    revision: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, min_length=1, max_length=64)
    character_type: str | None = Field(None, pattern="^(character|prop|other)$")
    symmetry: str | None = Field(None, pattern="^(symmetric|asymmetric)$")
    description: str | None = None


class CharacterArchiveRequest(BaseModel):
    revision: int = Field(..., ge=1)


class SetDefaultVersionRequest(BaseModel):
    revision: int = Field(..., ge=1)
    version_id: str | None = None


class AttachAssetRequest(BaseModel):
    pose_slot: str = Field(..., min_length=1, max_length=64)
    artifact_id: str = Field(..., min_length=1, max_length=36)


class PublishVersionRequest(BaseModel):
    revision: int = Field(..., ge=1)


class AssetData(BaseModel):
    id: str
    pack_version_id: str
    workspace_id: str
    pose_slot: str
    artifact_id: str
    created_at: datetime
    updated_at: datetime

    # Read-only artifact snapshot (S06-R02).  The frontend renders pose
    # previews from the typed content URL, never from filesystem paths.
    artifact_state: str | None = None
    mime_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    content_url: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_record(cls, record: Any, content_url: str | None = None) -> AssetData:
        return cls(
            id=record.id,
            pack_version_id=record.pack_version_id,
            workspace_id=record.workspace_id,
            pose_slot=record.pose_slot,
            artifact_id=record.artifact_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            artifact_state=record.artifact_state,
            mime_type=record.artifact_mime_type,
            sha256=record.artifact_sha256,
            size_bytes=record.artifact_size_bytes,
            content_url=content_url,
        )


class PackVersionData(BaseModel):
    id: str
    character_id: str
    workspace_id: str
    version: int
    status: str
    validation_json: str | None
    published_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    assets: list[AssetData]

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_record(cls, record: Any) -> PackVersionData:
        return cls(
            id=record.id,
            character_id=record.character_id,
            workspace_id=record.workspace_id,
            version=record.version,
            status=record.status,
            validation_json=record.validation_json,
            published_at=record.published_at,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            archived_at=record.archived_at,
            assets=[
                AssetData.from_record(
                    a,
                    content_url=asset_content_url(
                        record.character_id, a.pack_version_id, a.id
                    ),
                )
                for a in record.assets
            ],
        )


def asset_content_url(character_id: str, version_id: str, asset_id: str) -> str:
    """Server-produced content URL for a pose asset.

    The frontend must fetch pose bytes through this typed link; the content
    endpoint verifies ownership/state/type and serves only safe managed files.
    """
    return (
        f"/api/v2/characters/{character_id}/versions/{version_id}"
        f"/assets/{asset_id}/content"
    )


class PackVersionValidationData(BaseModel):
    """Read-only draft validation result (S06-R02).

    Computed by the SAME authoritative validator as publish, without
    publishing or mutating the pack.
    """

    version_id: str
    character_id: str
    workspace_id: str
    status: str
    complete: bool
    missing_slots: list[str]
    errors: list[str]


class ReferenceArtworkData(BaseModel):
    """Public result of an authored reference-artwork ingest (MF-END-03).

    Every identity field is server-derived: sha256/size/mime/dimensions come
    from the VERIFIED bytes (never from the client), ``content_url`` is the
    typed link to the existing asset content endpoint, and no filesystem path
    is ever returned.
    """

    asset_id: str
    version_id: str
    character_id: str
    workspace_id: str
    reference_key: str
    view: str
    role: str
    artifact_id: str
    sha256: str
    size_bytes: int
    mime_type: str
    width: int
    height: int
    decoded_mode: str
    colour_type: int | None = None
    has_alpha: bool = False
    purpose: str
    source_filename: str
    replaced_existing: bool = False
    created_at: datetime | None = None
    content_url: str | None = None

    @classmethod
    def from_result(cls, result: Any) -> ReferenceArtworkData:
        return cls(
            asset_id=result.asset_id,
            version_id=result.version_id,
            character_id=result.character_id,
            workspace_id=result.workspace_id,
            reference_key=result.reference_key,
            view=result.view,
            role=result.role,
            artifact_id=result.artifact_id,
            sha256=result.sha256,
            size_bytes=result.size_bytes,
            mime_type=result.mime_type,
            width=result.width,
            height=result.height,
            decoded_mode=result.decoded_mode,
            colour_type=result.colour_type,
            has_alpha=result.has_alpha,
            purpose=result.purpose,
            source_filename=result.source_filename,
            replaced_existing=result.replaced_existing,
            created_at=result.created_at,
            content_url=asset_content_url(
                result.character_id, result.version_id, result.asset_id
            ),
        )


class CharacterData(BaseModel):
    id: str
    workspace_id: str
    name: str
    code: str
    character_type: str
    symmetry: str
    status: str
    default_version_id: str | None
    description: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_record(cls, record: Any) -> CharacterData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            name=record.name,
            code=record.code,
            character_type=record.character_type,
            symmetry=record.symmetry,
            status=record.status,
            default_version_id=record.default_version_id,
            description=record.description,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            archived_at=record.archived_at,
        )


class CharacterListResponse(BaseModel):
    workspace_id: str
    limit: int
    offset: int
    total: int
    characters: list[CharacterData]


class ReferenceAssetJobRequest(BaseModel):
    """Submit one reference-asset generation intent (MF-END-09).

    ``reference_key`` is the missing ``<view>@<role>`` the job must create;
    ``view_prompt`` must name that view (the graph prompt is validated, never
    invented).  ``source_reference_key`` defaults to the pack convention
    ``front@character`` when omitted.
    """

    reference_key: str = Field(..., min_length=3, max_length=64)
    view_prompt: str = Field(..., min_length=20, max_length=2000)
    source_reference_key: str | None = Field(None, min_length=3, max_length=64)
    style_version: str | None = Field(None, max_length=64)
    seed: int | None = Field(None, ge=0, lt=2**63)
    idempotency_key: str | None = Field(None, min_length=8, max_length=120)
    input_generation: str | None = Field(None, min_length=1, max_length=120)


class ReferenceAssetJobRetryRequest(BaseModel):
    """Retry a terminal reference-asset job (new input generation)."""

    input_generation: str | None = Field(None, min_length=1, max_length=120)


class ReferenceAssetJobSubmitData(BaseModel):
    """Public result of an intent registration (no engine work yet)."""

    job: ReferenceAssetJobData
    content_key: str
    reference_key: str
    view: str
    role: str
    duplicate: bool = False


class ReferenceAssetJobData(BaseModel):
    """Durable status of one reference-asset generation job."""

    job_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    job_type: str = ""
    content_key: str | None = None
    reference_key: str | None = None
    view: str | None = None
    role: str | None = None
    duplicate: bool = False

    @classmethod
    def from_info(
        cls,
        info: Any,
        *,
        content_key: str | None = None,
        reference_key: str | None = None,
        view: str | None = None,
        role: str | None = None,
        duplicate: bool = False,
    ) -> ReferenceAssetJobData:
        state = getattr(info, "state", "")
        return cls(
            job_id=str(info.job_id),
            state=str(getattr(state, "value", state)),
            progress=float(getattr(info, "progress", 0.0) or 0.0),
            message=str(getattr(info, "message", "") or ""),
            job_type=str(getattr(info, "job_type", "") or ""),
            content_key=content_key,
            reference_key=reference_key,
            view=view,
            role=role,
            duplicate=duplicate,
        )

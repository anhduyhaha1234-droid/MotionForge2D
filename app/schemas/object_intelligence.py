"""Pydantic schemas for the Object Intelligence API (S08-T01).

DTOs for the durable video-global ``ObjectRole`` identity and scene/frame
evidence in ``ObjectOccurrence``.  Only stable UUID identities are exposed;
legacy ``object_id``/index values appear exclusively inside the explicit
read-only compatibility mapping and are never durable authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.persistence.models import OBJECT_KIND_PATTERN


class BboxInput(BaseModel):
    """Canonical pixel bounding box (non-negative integers)."""

    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    width: int = Field(..., ge=0)
    height: int = Field(..., ge=0)


class RoleCreateRequest(BaseModel):
    """Create payload for an ObjectRole.

    ``status`` defaults to ``suggested`` so model/import suggestions never
    silently become user truth; confirmation is an explicit later update.
    """

    project_id: str = Field(..., min_length=1)
    video_item_id: str = Field(..., min_length=1)
    source_generation: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=240)
    #: Canonical seven-kind taxonomy; pattern derived from OBJECT_KINDS (F3).
    kind: str = Field("character", pattern=OBJECT_KIND_PATTERN)
    status: str = Field("suggested", pattern="^(suggested|confirmed|superseded)$")
    description: str | None = None
    legacy_object_id: str | None = Field(None, max_length=255)
    legacy_scene_id: int | None = None
    idempotency_key: str | None = Field(None, max_length=255)


class RoleUpdateRequest(BaseModel):
    """CAS update payload: ``revision`` is the required optimistic token."""

    revision: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=240)
    #: Canonical seven-kind taxonomy; pattern derived from OBJECT_KINDS (F3).
    kind: str | None = Field(None, pattern=OBJECT_KIND_PATTERN)
    status: str | None = Field(None, pattern="^(suggested|confirmed|superseded)$")
    description: str | None = None
    supersedes_role_id: str | None = None


class OccurrenceCreateRequest(BaseModel):
    """Create payload for one scene/frame evidence record."""

    scene_id: str = Field(..., min_length=1)
    frame_index: int = Field(..., ge=0)
    time_ms: int = Field(..., ge=0)
    bbox: BboxInput
    confidence: float = Field(..., ge=0, le=1)
    confidence_source: str = Field("model", pattern="^(model|detector|user|manual|derived)$")
    algorithm: str | None = Field(None, max_length=64)
    algorithm_version: str | None = Field(None, max_length=64)
    reasons: list[str] = Field(default_factory=list)
    review_state: str = Field("unreviewed", pattern="^(unreviewed|accepted|rejected|edited)$")


class OccurrenceUpdateRequest(BaseModel):
    """CAS update payload for an occurrence."""

    revision: int = Field(..., ge=1)
    confidence: float | None = Field(None, ge=0, le=1)
    review_state: str | None = Field(None, pattern="^(unreviewed|accepted|rejected|edited)$")
    reasons: list[str] | None = None
    bbox: BboxInput | None = None


class OccurrenceData(BaseModel):
    """Read model for one ObjectOccurrence."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    role_id: str
    scene_id: str
    frame_index: int
    time_ms: int
    bbox: BboxInput
    confidence: float
    confidence_source: str
    algorithm: str | None
    algorithm_version: str | None
    reasons: list[str]
    review_state: str
    revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> OccurrenceData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            role_id=record.role_id,
            scene_id=record.scene_id,
            frame_index=record.frame_index,
            time_ms=record.time_ms,
            bbox=BboxInput(
                x=record.bbox_x,
                y=record.bbox_y,
                width=record.bbox_w,
                height=record.bbox_h,
            ),
            confidence=record.confidence,
            confidence_source=record.confidence_source,
            algorithm=record.algorithm,
            algorithm_version=record.algorithm_version,
            reasons=list(record.reasons or []),
            review_state=record.review_state,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class RoleMediaData(BaseModel):
    """The newest valid media of a role (S08-T05-C1, finding D).

    Resolved from the role's active ``object_role_artifact`` associations
    (``superseded_by_id IS NULL``).  Content is servable through the
    contained image endpoint::

        /api/v2/object-intelligence/extraction/{source_job_id}/artifacts/{artifact_id}/content
    """

    association_id: str
    artifact_id: str
    purpose: str
    relative_path: str
    sha256: str
    size_bytes: int
    width: int | None
    height: int | None
    mime_type: str | None
    source_generation: str
    source_job_id: str


class RoleData(BaseModel):
    """Read model for one ObjectRole (stable identity + evidence)."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    name: str
    kind: str
    status: str
    supersedes_role_id: str | None
    legacy_object_id: str | None
    legacy_scene_id: int | None
    description: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    occurrences: list[OccurrenceData] = Field(default_factory=list)
    media: list[RoleMediaData] = Field(default_factory=list)
    has_media_associations: bool = False

    @classmethod
    def from_record(cls, record: Any) -> RoleData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            video_item_id=record.video_item_id,
            source_generation=record.source_generation,
            name=record.name,
            kind=record.kind,
            status=record.status,
            supersedes_role_id=record.supersedes_role_id,
            legacy_object_id=record.legacy_object_id,
            legacy_scene_id=record.legacy_scene_id,
            description=record.description,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            occurrences=[OccurrenceData.from_record(occ) for occ in (record.occurrences or [])],
            media=[RoleMediaData(**vars(item)) for item in (record.media or [])],
            has_media_associations=bool(getattr(record, "has_media_associations", False)),
        )


class RoleKindData(BaseModel):
    """One canonical ObjectRole kind (S08-A01 source-locked 2D taxonomy).

    ``name`` is the machine kind (one of exactly seven); ``removal_only`` is
    the backend-owned policy flag — ``true`` means the kind is removal-only
    (``source_overlay``): it can never be a Character Pack / replacement
    candidate and grouping never pairs it with anything.
    """

    name: str
    removal_only: bool = False


class RoleKindsResponse(BaseModel):
    """The canonical seven-kind ObjectRole taxonomy (backend-authoritative).

    Exactly one source of truth for the role/layer taxonomy; clients (the
    gallery filter, edit dialogs) derive their options from this endpoint so
    a second production authority is never created in the frontend.
    """

    kinds: list[RoleKindData]
    source_overlay: str = "source_overlay"


class RoleListResponse(BaseModel):
    """Paged role listing (T01-C2: current-generation scoped by default).

    ``scope`` is ``"current"`` for the default view (only roles in the
    backend-authoritative current source generation) and ``"historical"`` for
    an EXPLICIT ``generation=N`` view — the two are never mixed.
    ``current_generation`` carries the backend current generation (when a
    single video item was requested) so clients can assert their state.
    """

    workspace_id: str
    limit: int
    offset: int
    total: int
    roles: list[RoleData]
    scope: str = "current"
    current_generation: str | None = None


class LegacyMappingItemData(BaseModel):
    """One legacy object mapped to an ephemeral, never-persisted role id."""

    legacy_object_id: str
    legacy_scene_id: int
    legacy_name: str
    legacy_kind: str
    suggested_name: str
    ephemeral_role_id: str
    occurrence_evidence: list[dict[str, Any]]
    # S08-A01 legacy provenance: the RAW source kind string and the reason
    # when it was normalized (never silently coerced).
    source_kind: str = ""
    kind_normalization_reason: str | None = None


class LegacyMappingResponse(BaseModel):
    """Read-only compatibility mapping from legacy object data."""

    project_id: str
    source: str
    mapped_objects: list[LegacyMappingItemData]
    note: str

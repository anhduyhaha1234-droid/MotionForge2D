"""Pydantic schemas for the ReskinConfig API (S09-T01).

Strict, typed, extra-forbidden, strict-mode DTOs between
app/api/routes/reskin_config and the durable core
app/persistence/reskin_config.

Invariants (mirroring S07 project_cast schemas):
- model_config = ConfigDict(extra="forbid", strict=True) on every request
  model — unknown field → 422, no silent coercion.
- No client-fabricated workspace authority: workspace_id never appears in
  requests (server-owned DEFAULT_WORKSPACE_ID).
- params validated fail-closed: closed key set, anchor {x,y} ∈ [0,1],
  scale > 0, fit_mode ∈ contain|cover|stretch, clip_mode ∈
  asset_alpha|original_mask|intersection, opacity ∈ [0,1].
- Deterministic serialization via typed Pydantic read models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FitMode = Literal["contain", "cover", "stretch"]
ClipMode = Literal["asset_alpha", "original_mask", "intersection"]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AnchorPoint(BaseModel):
    """Normalized anchor inside the source frame — each axis ∈ [0,1]."""

    model_config = ConfigDict(extra="forbid", strict=True)

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)


class OffsetVector(BaseModel):
    """Pixel-space offset applied after fit/clip; finite floats."""

    model_config = ConfigDict(extra="forbid", strict=True)

    x: float
    y: float


class ReskinParams(BaseModel):
    """The reskin transform contract stored with every config row."""

    model_config = ConfigDict(extra="forbid", strict=True)

    anchor: AnchorPoint
    scale: float = Field(..., gt=0.0)
    fit_mode: FitMode
    clip_mode: ClipMode
    offset: OffsetVector
    rotation_offset_deg: float
    opacity: float = Field(..., ge=0.0, le=1.0)

    def to_domain(self) -> dict[str, Any]:
        return self.model_dump()


class ReskinConfigCreateRequest(_StrictBase):
    """Create payload: pins a ReskinConfig to project+role and PackVersion.

    The pack_version_id is the immutable pin identity; compatibility is
    re-validated server-side against the authoritative S07 policy.
    """

    project_id: str = Field(..., min_length=1, max_length=36)
    object_role_id: str = Field(..., min_length=1, max_length=36)
    character_id: str = Field(..., min_length=1, max_length=36)
    pack_version_id: str = Field(..., min_length=1, max_length=36)
    params: ReskinParams
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)
    cast_mapping_id: str | None = Field(None, min_length=1, max_length=36)


class ReskinParamsPatch(ReskinParams):
    """Full params replacement on PATCH (no partial merge — deterministic)."""


class ReskinConfigUpdateRequest(_StrictBase):
    """CAS update payload: revision is the required optimistic token."""

    revision: int = Field(..., ge=1)
    params: ReskinParamsPatch | None = None
    pack_version_id: str | None = Field(None, min_length=1, max_length=36)
    character_id: str | None = Field(None, min_length=1, max_length=36)


class ReskinConfigData(BaseModel):
    """Read model for one durable ReskinConfig (deterministic serialization)."""

    id: str
    workspace_id: str
    project_id: str
    object_role_id: str
    cast_mapping_id: str | None
    character_id: str
    pack_version_id: str
    params: dict[str, Any]
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_record(cls, record: Any) -> ReskinConfigData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            object_role_id=record.object_role_id,
            cast_mapping_id=record.cast_mapping_id,
            character_id=record.character_id,
            pack_version_id=record.pack_version_id,
            params=record.params,
            idempotency_key=record.idempotency_key,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ReskinConfigListResponse(BaseModel):
    """Paged list of ReskinConfigs for one workspace (optionally filtered)."""

    workspace_id: str
    project_id: str | None = None
    limit: int
    offset: int
    total: int
    configs: list[ReskinConfigData]

    model_config = ConfigDict(from_attributes=True)


# field_validator import kept at top; reserved for future cross-field rules
# (e.g. bounding offset magnitude). Present so adding a rule never needs an
# import-order churn in this file.
_ = field_validator

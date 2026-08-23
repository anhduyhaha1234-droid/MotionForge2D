"""Pydantic schemas for Project Cast Mapping (S07-T01 + S07-T02 picker/compat).

Strict, typed, extra-forbidden, strict-mode DTOs between
/app/api/routes/project_cast and the durable core
/app/persistence/project_cast.

Invariants:
- model_config = ConfigDict(extra="forbid", strict=True) on every request model — unknown field 422.
- No client-fabricated workspace authority: workspace_id never appears in requests.
- No silent coercion: strict=True means string "123" not coerced to int, 1 not coerced to bool.
- Deterministic serialization via typed Pydantic models (stable field order).
- S07-T02 adds READ-only picker + compatibility DTOs (typed, deterministic, no mutation).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProjectCastCreateRequest(_StrictModel):
    """Create payload for a Project Cast Mapping.

    Pins an ObjectRole to an immutable PackVersion. All FK ids are required
    and validated server-side for workspace isolation. The pack_version_id is
    the immutable pin — never a mutable character pointer alone.
    """

    project_id: str = Field(..., min_length=1, max_length=36)
    object_role_id: str = Field(..., min_length=1, max_length=36)
    character_id: str = Field(..., min_length=1, max_length=36)
    pack_version_id: str = Field(..., min_length=1, max_length=36)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)
    fallback_acknowledged: bool = Field(False, description="Client acknowledges fallback warning and intends to pin despite partial compatibility")  # noqa: E501


class ProjectCastUpdateRequest(_StrictModel):
    """CAS update payload: revision is required optimistic token.

    Allows remapping to a new immutable PackVersion (and its Character).
    If pack_version_id is supplied, character_id must be consistent with that
    pack's character_id (validated server-side).
    """

    revision: int = Field(..., ge=1)
    character_id: str | None = Field(None, min_length=1, max_length=36)
    pack_version_id: str | None = Field(None, min_length=1, max_length=36)
    fallback_acknowledged: bool = Field(False, description="Client acknowledges fallback warning and intends to repin despite partial compatibility")  # noqa: E501


class ProjectCastData(BaseModel):
    """Read model for a Project Cast Mapping (deterministic serialization)."""

    id: str
    workspace_id: str
    project_id: str
    object_role_id: str
    character_id: str
    pack_version_id: str
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_record(cls, record: Any) -> ProjectCastData:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            object_role_id=record.object_role_id,
            character_id=record.character_id,
            pack_version_id=record.pack_version_id,
            idempotency_key=record.idempotency_key,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ProjectCastListResponse(BaseModel):
    """Paged list of Project Cast Mappings for one workspace (optionally filtered)."""

    workspace_id: str
    project_id: str | None = None
    limit: int
    offset: int
    total: int
    mappings: list[ProjectCastData]

    model_config = ConfigDict(from_attributes=True)


# ── S07-T02: Library Picker + Compatibility DTOs (READ-only, deterministic) ──


CompatibilityReason = Literal[
    "workspace_mismatch",
    "source_overlay_refusal",
    "object_kind_mismatch",
    "incomplete_pack",
    "unpublished_pack",
    "missing_required_pose",
    "missing_required_capability",
    "generation_mismatch",
    "stale_revision",
]


class PickerPackItem(BaseModel):
    """Single Pack Version entry for the Library Picker (published/usable only)."""

    id: str
    character_id: str
    workspace_id: str
    version: int
    status: str
    character_name: str
    character_code: str
    character_type: str
    symmetry: str
    published_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime
    asset_count: int
    pose_slots: list[str]

    model_config = ConfigDict(from_attributes=True)


class PickerPacksResponse(BaseModel):
    """Paginated picker browse response — only published/usable versions."""

    workspace_id: str
    limit: int
    offset: int
    total: int
    packs: list[PickerPackItem]
    query: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CompatibilityEvaluateRequest(_StrictModel):
    """Request to evaluate compatibility for a proposed mapping.

    All IDs refer to rows in the caller's workspace (server-owned).
    expected_revision is used for stale_revision detection when updating
    an existing mapping (client's last-seen revision).
    """

    project_id: str = Field(..., min_length=1, max_length=36)
    object_role_id: str = Field(..., min_length=1, max_length=36)
    pack_version_id: str = Field(..., min_length=1, max_length=36)
    expected_revision: int | None = Field(None, ge=1)
    mapping_id: str | None = Field(None, min_length=1, max_length=36)


class CompatibilityEvaluateResponse(BaseModel):
    """Deterministic compatibility report (pure function, no GPU/network/time)."""

    compatible: bool
    reasons: list[CompatibilityReason]
    fallback_allowed: bool
    fallback_description: str | None = None
    blocked: bool
    pinned_version_id: str | None = None
    current_revision: int | None = None
    workspace_id: str

    model_config = ConfigDict(from_attributes=True)

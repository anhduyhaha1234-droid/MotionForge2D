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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.cast_recommendation import (
    REQUIRED_VIEW_VOCABULARY,
    GenerationPlanData,
    _unique_nonempty,
)
from app.schemas.shot_reskin import ENGINE_CAPABILITY_PINS


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


# ── MF-END-05: series cast snapshot ("series pin") DTOs ───────────────────────

#: A role key is a stable, series-scoped identifier for one cast slot
#: (e.g. ``ROLE-BOOK-P1``) — it is what makes a frozen pin reusable by the
#: next video of the series; ids never stand in for roles across videos.
SERIES_ROLE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"


class SeriesCastEntryRequest(_StrictModel):
    """One requested ``role_key -> character / pack version / style`` binding."""

    role_key: str = Field(
        ..., min_length=1, max_length=64, pattern=SERIES_ROLE_KEY_PATTERN
    )
    character_id: str = Field(..., min_length=1, max_length=36)
    pack_version_id: str = Field(..., min_length=1, max_length=36)
    style_version: str | None = Field(None, min_length=1, max_length=64)


class SeriesCastSnapshotCreateRequest(_StrictModel):
    """Freeze the series cast set (INSERT-only; a change = a new snapshot)."""

    project_id: str = Field(..., min_length=1, max_length=36)
    entries: list[SeriesCastEntryRequest] = Field(..., min_length=1, max_length=64)


class SeriesCastReferenceData(BaseModel):
    """One frozen per-key asset reference (``pose_slot`` / artifact / sha)."""

    pose_slot: str
    artifact_id: str
    sha256: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SeriesCastEntryData(BaseModel):
    """Frozen entry as read back from the durable snapshot."""

    role_key: str
    character_id: str
    pack_version_id: str
    pack_contract_version: str
    manifest_sha256: str | None = None
    style_version: str | None = None
    references: list[SeriesCastReferenceData]

    model_config = ConfigDict(from_attributes=True)


class SeriesCastSnapshotData(BaseModel):
    """A frozen series cast snapshot (immutable, versioned by index)."""

    id: str
    workspace_id: str
    project_id: str
    snapshot_index: int
    entries_sha256: str
    created_at: datetime
    updated_at: datetime
    entries: list[SeriesCastEntryData]

    model_config = ConfigDict(from_attributes=True)


class SeriesCastSnapshotListResponse(BaseModel):
    """Paginated snapshots, newest index first per project."""

    workspace_id: str
    project_id: str | None = None
    limit: int
    offset: int
    total: int
    snapshots: list[SeriesCastSnapshotData]

    model_config = ConfigDict(from_attributes=True)


class SeriesCastResolutionRequest(_StrictModel):
    """Map one frozen ``role_key`` onto the target video's object role."""

    role_key: str = Field(
        ..., min_length=1, max_length=64, pattern=SERIES_ROLE_KEY_PATTERN
    )
    object_role_id: str = Field(..., min_length=1, max_length=36)


class SeriesCastApplyRequest(_StrictModel):
    """Copy a frozen snapshot onto a new video of the same series.

    The WHOLE set is required — every snapshot ``role_key`` must be resolved
    exactly once, so a shared series cast is never half-applied silently.
    """

    video_item_id: str = Field(..., min_length=1, max_length=36)
    resolutions: list[SeriesCastResolutionRequest] = Field(..., min_length=1, max_length=64)


class SeriesCastApplyEntryData(BaseModel):
    """One copied pin (the mapping row written by the existing service)."""

    role_key: str
    object_role_id: str
    mapping_id: str
    character_id: str
    pack_version_id: str
    manifest_sha256: str | None = None
    created: bool

    model_config = ConfigDict(from_attributes=True)


class SeriesCastApplyResponse(BaseModel):
    """Result of copying a series snapshot onto one video."""

    snapshot_id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    entries_sha256: str
    applied: list[SeriesCastApplyEntryData]
    created_count: int
    replayed_count: int

    model_config = ConfigDict(from_attributes=True)

    model_config = ConfigDict(from_attributes=True)


# ── MF-END-07: recommendation / confirm (U03/U04/U13 API boundary) ──────────
#
# The suggestion route surfaces MF-END-06's READ-ONLY service verbatim; the
# confirm route accepts the user's choice TOGETHER with the trace of the
# recommendation it came from, so a pin is only ever mutated while the live
# server state still supports that trace (a stale basis is a typed refusal).

#: The selection modes a recommendation can report (echoed by the confirm).
CAST_CONFIRM_SELECTION_MODES = ("series_pin", "advisory", "metadata", "manual")


class CastConfirmTrace(_StrictModel):
    """The recommendation the user acted on (the client's echo of it).

    ``selected_pack_version_id`` is the pack the recommendation proposed and it
    must equal the confirmed ``pack_version_id``.  The optional view /
    capability / style fields are the recommendation basis for THIS role (the
    same vocabulary the suggestion request validates); feeding them back lets
    the confirm re-derive the identical candidate set and report actionable
    missing assets instead of guessing.  A ``series_pin`` trace must pin the
    frozen snapshot it came from (MF-END-05) so a stale basis is refused.
    """

    role_key: str = Field(
        ..., min_length=1, max_length=64, pattern=SERIES_ROLE_KEY_PATTERN
    )
    selection_mode: Literal["series_pin", "advisory", "metadata", "manual"]
    selected_pack_version_id: str = Field(..., min_length=1, max_length=36)
    required_views: list[str] = Field(
        default_factory=list, max_length=len(REQUIRED_VIEW_VOCABULARY)
    )
    required_capabilities: list[str] = Field(
        default_factory=list, max_length=len(ENGINE_CAPABILITY_PINS)
    )
    style_version: str | None = Field(None, min_length=1, max_length=64)
    series_snapshot_id: str | None = Field(None, min_length=1, max_length=36)
    series_snapshot_index: int | None = Field(None, ge=0)
    series_entries_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("required_views")
    @classmethod
    def _views_in_vocabulary(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in REQUIRED_VIEW_VOCABULARY]
        if unknown:
            raise ValueError(
                "required_views must come from the measured view vocabulary "
                f"{sorted(REQUIRED_VIEW_VOCABULARY)}; unknown: {unknown}"
            )
        return _unique_nonempty(values, field="required_views")

    @field_validator("required_capabilities")
    @classmethod
    def _capabilities_in_pins(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in ENGINE_CAPABILITY_PINS]
        if unknown:
            raise ValueError(
                "required_capabilities must be pinned engine capabilities "
                f"{list(ENGINE_CAPABILITY_PINS)}; unknown: {unknown}"
            )
        return _unique_nonempty(values, field="required_capabilities")

    @model_validator(mode="after")
    def _series_pin_trace_pins_its_snapshot(self) -> CastConfirmTrace:
        if self.selection_mode == "series_pin":
            missing = [
                name
                for name, value in (
                    ("series_snapshot_id", self.series_snapshot_id),
                    ("series_snapshot_index", self.series_snapshot_index),
                    ("series_entries_sha256", self.series_entries_sha256),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "a series_pin trace must pin the frozen snapshot it was "
                    "derived from; missing: " + ", ".join(missing)
                )
        return self


class CastConfirmRequest(_StrictModel):
    """Confirm ONE recommended cast choice against the live server state.

    ``idempotency_key`` is REQUIRED: an identical confirm always replays the
    same mapping and can never write twice.  ``expected_revision`` is the
    version guard for REPLACING an existing pin — a replacement without it is
    refused (422) and a stale token is refused (409).
    """

    video_item_id: str = Field(..., min_length=1, max_length=36)
    object_role_id: str = Field(..., min_length=1, max_length=36)
    character_id: str = Field(..., min_length=1, max_length=36)
    pack_version_id: str = Field(..., min_length=1, max_length=36)
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    expected_revision: int | None = Field(None, ge=1)
    fallback_acknowledged: bool = False
    recommendation: CastConfirmTrace


class CastConfirmWarningData(BaseModel):
    """One actionable warning about the confirmed choice (never a blocker)."""

    code: str
    detail: str
    action: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CastConfirmTraceData(BaseModel):
    """What the server VERIFIED about the trace (provenance of this write)."""

    role_key: str
    selection_mode: str
    selected_pack_version_id: str
    verified_source: Literal["series_pin", "library_candidate"]
    snapshot_id: str | None = None
    snapshot_index: int | None = None
    entries_sha256: str | None = None
    checked_against: Literal["live_recommendation"] = "live_recommendation"

    model_config = ConfigDict(from_attributes=True)


class CastConfirmResponse(BaseModel):
    """Result of confirming one recommended choice (write or replay)."""

    workspace_id: str
    project_id: str
    mapping: ProjectCastData
    trace: CastConfirmTraceData
    warnings: list[CastConfirmWarningData]
    missing_views: list[str]
    generation: GenerationPlanData
    created: bool
    replayed: bool
    mutations: int
    read_only: bool = False

    model_config = ConfigDict(from_attributes=True)

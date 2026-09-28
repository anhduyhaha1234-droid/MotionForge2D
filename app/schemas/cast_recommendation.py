"""Schemas for the read-only library cast-set recommendation (MF-END-06).

Strict, typed, extra-forbidden DTOs between the recommendation service
(``app/services/cast_recommendation``) and any caller (the MF-END-07 router
will reuse the same models).

Contract rules encoded here (binary acceptance of MF-END-06):

* **No invented identifiers.**  Every ID-carrying field of a result is
  populated from a durable row the service actually resolved (character /
  pack version / snapshot).  Request-side IDs are looked up, never created.
* **No invented vocabulary.**  ``role_key`` re-validates against the frozen
  series-pin grammar (``project_cast._ROLE_KEY_PATTERN``), ``kind`` against
  the canonical object-kind pattern, ``required_views`` against the measured
  view vocabulary (``CORE_POSE_SLOTS`` — the same vocabulary the reference
  ingest publishes), and ``required_capabilities`` against the pinned engine
  capability list (``shot_reskin.ENGINE_CAPABILITY_PINS``).
* **Bounded advisory input.**  ``source_frames`` is capped at
  ``MAX_SOURCE_FRAMES`` frames of *image* artifacts — a whole video is never
  an acceptable advisory payload (the service refuses video artifacts with a
  typed error).
* **No silent coercion.**  Every request model is ``extra="forbid"`` +
  ``strict=True``: an unknown field is a validation error, ``"1"`` is not an
  ``int``, and a list is not a tuple.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.persistence.models import CORE_POSE_SLOTS, OBJECT_KIND_PATTERN
from app.persistence.project_cast import _ROLE_KEY_PATTERN
from app.schemas.shot_reskin import ENGINE_CAPABILITY_PINS

__all__ = [
    "ADVISORY_MODES",
    "CAST_ROLE_KEY_PATTERN",
    "GENERATION_PLAN_NOTE_FULL",
    "GENERATION_PLAN_NOTE_MISSING",
    "GENERATION_PLAN_NOTE_NONE",
    "GENERATION_PLAN_NOTE_STALE_PIN",
    "MAX_SOURCE_FRAMES",
    "REQUIRED_VIEW_VOCABULARY",
    "AdvisoryNoteData",
    "AdvisoryReportData",
    "AdvisoryRoutePinData",
    "CandidateReasonData",
    "CastCandidateData",
    "CastRecommendationRequest",
    "CastRecommendationResult",
    "CastRoleRequirement",
    "FilteredPackData",
    "GenerationPlanData",
    "RoleAdvisoryData",
    "RoleRecommendationData",
    "SeriesContextData",
    "SeriesPinData",
    "SourceFrameInput",
]

#: Advisory modes accepted by the request: ``auto`` (call the pinned route
#: only when the deterministic ranking is genuinely ambiguous) or ``off``
#: (metadata-only result; advisory is never invoked).
ADVISORY_MODES: tuple[str, ...] = ("auto", "off")

#: The frozen series-pin role-key grammar, re-used verbatim so a recommendation
#: role key is exactly the key space a series snapshot can hold (single source:
#: ``app.persistence.project_cast``).
CAST_ROLE_KEY_PATTERN: re.Pattern[str] = _ROLE_KEY_PATTERN

#: View vocabulary a requirement may name — the pack contract's measured view
#: vocabulary (mirror of ``character_reference_ingest.REFERENCE_VIEWS``, which
#: itself is ``CORE_POSE_SLOTS``).  No invented view names.
REQUIRED_VIEW_VOCABULARY: frozenset[str] = frozenset(CORE_POSE_SLOTS)

#: Hard ceiling of source frames attached to one advisory call — an image
#: budget, never a video.  A whole video is NEVER a valid payload.
MAX_SOURCE_FRAMES = 3

#: Generation-plan notes (deterministic strings, asserted by tests).
GENERATION_PLAN_NOTE_FULL = (
    "selected candidate already covers every required view — do not generate assets"
)
GENERATION_PLAN_NOTE_MISSING = (
    "assets are insufficient for the required views — generate ONLY the listed "
    "missing views (reference-asset workflow, MF-END-08)"
)
GENERATION_PLAN_NOTE_NONE = (
    "no eligible candidate for this role — no generation plan is issued"
)
GENERATION_PLAN_NOTE_STALE_PIN = (
    "series pin is stale — re-freeze a new snapshot first; assets must not be "
    "regenerated blindly"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{field} must not contain duplicates: {value!r}")
        seen.add(value)
    return values


# ── request ───────────────────────────────────────────────────────────────────


class SourceFrameInput(_StrictModel):
    """One bounded advisory input frame (a REAL image artifact reference).

    The service resolves the artifact workspace-scoped and refuses anything
    that is not a ready image (a ``video`` artifact is a typed refusal — the
    advisory route never receives a whole video).
    """

    artifact_id: str = Field(..., min_length=1, max_length=36)
    label: str | None = Field(None, min_length=1, max_length=64)


class CastRoleRequirement(_StrictModel):
    """One role of the target video that needs a library pack.

    ``role_key`` is the stable key that matches a series-snapshot entry (the
    series pin is matched by key, never by inference).  ``object_role_id`` is
    optional and, when present, must be a real ObjectRole of the target video
    (the service validates ownership; it is never fabricated).
    """

    role_key: str = Field(..., min_length=1, max_length=64, pattern=CAST_ROLE_KEY_PATTERN.pattern)
    kind: str = Field(..., pattern=OBJECT_KIND_PATTERN)
    object_role_id: str | None = Field(None, min_length=1, max_length=36)
    required_views: list[str] = Field(
        default_factory=list, max_length=len(REQUIRED_VIEW_VOCABULARY)
    )
    required_capabilities: list[str] = Field(
        default_factory=list, max_length=len(ENGINE_CAPABILITY_PINS)
    )
    style_version: str | None = Field(None, min_length=1, max_length=64)

    @field_validator("required_views")
    @classmethod
    def _views_in_vocabulary(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in REQUIRED_VIEW_VOCABULARY]
        if unknown:
            raise ValueError(
                f"required_views must be from the measured view vocabulary "
                f"{sorted(REQUIRED_VIEW_VOCABULARY)}; unknown: {unknown}"
            )
        return _unique_nonempty(values, field="required_views")

    @field_validator("required_capabilities")
    @classmethod
    def _capabilities_in_pins(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in ENGINE_CAPABILITY_PINS]
        if unknown:
            raise ValueError(
                f"required_capabilities must be pinned engine capabilities "
                f"{list(ENGINE_CAPABILITY_PINS)}; unknown: {unknown}"
            )
        return _unique_nonempty(values, field="required_capabilities")


class CastRecommendationRequest(_StrictModel):
    """Read-only recommendation request.

    ``requirements=None`` means: derive one requirement per confirmed role of
    the target video (server-side authority — the client never supplies the
    role inventory).  An explicitly provided list is used as-is (validated).
    """

    video_item_id: str = Field(..., min_length=1, max_length=36)
    requirements: list[CastRoleRequirement] | None = None
    advisory: Literal["auto", "off"] = "auto"
    source_frames: list[SourceFrameInput] = Field(
        default_factory=list, max_length=MAX_SOURCE_FRAMES
    )

    @field_validator("requirements")
    @classmethod
    def _requirements_unique(
        cls, values: list[CastRoleRequirement] | None
    ) -> list[CastRoleRequirement] | None:
        if values is None:
            return None
        if not values:
            raise ValueError("requirements must not be an empty list when provided")
        keys = [value.role_key for value in values]
        _unique_nonempty(keys, field="requirements.role_key")
        return values

    @field_validator("source_frames")
    @classmethod
    def _frames_unique(cls, values: list[SourceFrameInput]) -> list[SourceFrameInput]:
        ids = [value.artifact_id for value in values]
        _unique_nonempty(ids, field="source_frames.artifact_id")
        return values


# ── result ────────────────────────────────────────────────────────────────────


class AdvisoryRoutePinData(_StrictModel):
    """The pinned advisory route, surfaced verbatim so errors are actionable."""

    provider: str
    base_url: str
    api_mode: str
    model: str
    fallback_allowed: bool
    timeout_seconds: float


class AdvisoryNoteData(_StrictModel):
    code: str
    detail: str


class CandidateReasonData(_StrictModel):
    code: str
    detail: str


class SeriesPinData(_StrictModel):
    """The series pin seen for this role (MF-END-05 snapshot entry)."""

    snapshot_id: str
    snapshot_index: int
    entries_sha256: str
    live_ok: bool
    problems: list[str] = Field(default_factory=list)


class CastCandidateData(_StrictModel):
    """One real library candidate for a role (IDs always resolved from rows)."""

    pack_version_id: str
    pack_version: int
    character_id: str
    character_name: str
    character_code: str
    character_type: str
    pack_contract_version: str
    source: Literal["series_snapshot", "library"]
    snapshot_id: str | None = None
    snapshot_index: int | None = None
    live_ok: bool | None = None
    live_problems: list[str] = Field(default_factory=list)
    rank: int
    available_views: list[str]
    missing_views: list[str]
    covers_required_views: bool
    missing_capabilities: list[str]
    style_version: str | None = None
    style_match: bool | None = None
    reasons: list[CandidateReasonData]


class FilteredPackData(_StrictModel):
    """A real published pack that the deterministic hard filter excluded.

    Kept (with its real IDs) so a reviewer can audit WHY it is not a
    candidate — excluded packs never appear in ``candidates``.
    """

    pack_version_id: str
    character_id: str
    character_name: str
    reasons: list[CandidateReasonData]


class GenerationPlanData(_StrictModel):
    """Deterministic generation signal (never an action).

    ``required`` is True ONLY when the selected candidate is short of the
    required views; when assets suffice the plan must say so and never
    propose generating.
    """

    required: bool
    views: list[str]
    estimated_cost_units: int
    unit: str
    note: str


class RoleAdvisoryData(_StrictModel):
    status: Literal["not_requested", "not_needed", "ok", "unavailable"]
    requested: bool
    calls: int
    choice_pack_version_id: str | None = None
    choice_applied: bool = False
    error: str | None = None
    notes: list[AdvisoryNoteData] = Field(default_factory=list)


class RoleRecommendationData(_StrictModel):
    role_key: str
    object_role_id: str | None
    kind: str
    required_views: list[str]
    required_capabilities: list[str]
    style_version: str | None
    series_pin: SeriesPinData | None
    candidates: list[CastCandidateData]
    filtered: list[FilteredPackData]
    selected_pack_version_id: str | None
    selected_character_id: str | None
    selection_mode: Literal["series_pin", "advisory", "metadata", "none"]
    missing_views: list[str]
    generation: GenerationPlanData
    advisory: RoleAdvisoryData


class AdvisoryReportData(_StrictModel):
    status: Literal["not_requested", "not_needed", "ok", "unavailable"]
    route: AdvisoryRoutePinData
    calls: int
    error: str | None = None
    notes: list[AdvisoryNoteData] = Field(default_factory=list)


class SeriesContextData(_StrictModel):
    snapshot_id: str
    snapshot_index: int
    entries_sha256: str
    role_keys: list[str]


class CastRecommendationResult(_StrictModel):
    """Read-only result: no pin is created, changed, or auto-selected.

    ``read_only``/``mutations`` are part of the contract: the service writes
    nothing (no mapping, no artifact, no character, no snapshot).
    """

    workspace_id: str
    project_id: str
    video_item_id: str
    series: SeriesContextData | None
    roles: list[RoleRecommendationData]
    advisory: AdvisoryReportData
    read_only: bool = True
    mutations: int = 0
    manual_choice_available: bool

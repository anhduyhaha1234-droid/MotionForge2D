"""Pydantic schemas for the Structural Evidence API (S08-A02-T01-R2).

Strict, finite-only, extra-forbidden DTOs that sit between the isolated
``/api/v2/structural-evidence`` router and the verified durable core
(``app.persistence.structural_evidence``).

Contract invariants enforced here (R2 §3):

- ``model_config = ConfigDict(extra="forbid")`` on every model — an unknown
  field is a 422 before it ever reaches the repository.
- Finite numbers only: float fields use ``allow_inf_nan=False`` and a
  post-validation walk rejects NaN/Infinity nested inside JSON-object payloads
  (``reasons`` / ``provenance`` / ``transform`` / ``point_track_flow_ref`` /
  prompt points & boxes).
- Enums / patterns are DERIVED from ``app.persistence.models`` constants
  (``OBJECT_KIND_PATTERN``, ``OCCURRENCE_SEGMENT_VISIBILITY_PATTERN``,
  ``CONTACT_KIND_PATTERN``, ``OCCURRENCE_CONFIDENCE_SOURCES``) — no duplicated
  taxonomy literals.  The motion transform types are derived from the
  repository's canonical tuple (``MOTION_TRANSFORM_TYPES``).
- frame/time are non-negative and ``end >= start``.
- ``confidence`` is 0..1.
- algorithm / algorithm_version / idempotency_key strings are bounded.
- ``reasons: list[str]``; ``provenance: dict[str, Any]``.
- The client can NEVER supply a ``logical_id`` or an arbitrary
  ``source_generation`` — those are server/repository-owned and absent from
  every request model (an attempt to send one is an unknown-field 422).
- Current vs historical state is explicit on every segment read (``state``).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.persistence.models import (
    CONTACT_KIND_PATTERN,
    OBJECT_KIND_PATTERN,
    OCCURRENCE_CONFIDENCE_SOURCES,
    OCCURRENCE_SEGMENT_VISIBILITY_PATTERN,
)
from app.persistence.structural_evidence import MOTION_TRANSFORM_TYPES

#: Pydantic ``pattern`` for the canonical confidence sources, DERIVED from the
#: ORM constant (single authority — no duplicate taxonomy literals).
CONFIDENCE_SOURCE_PATTERN = (
    "^(" + "|".join(re.escape(source) for source in OCCURRENCE_CONFIDENCE_SOURCES) + ")$"
)
#: Motion transform-type pattern, DERIVED from the repository canonical tuple.
MOTION_TRANSFORM_PATTERN = (
    "^(" + "|".join(re.escape(transform_type) for transform_type in MOTION_TRANSFORM_TYPES) + ")$"
)


def _assert_finite(value: Any, path: str = "$") -> None:
    """Reject NaN / Infinity anywhere in a JSON-ish payload (R2 §3)."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"non-finite number at {path}: {value!r}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_finite(item, f"{path}[{index}]")


class _StrictModel(BaseModel):
    """Shared strict base: unknown fields are rejected; finite-only payloads;
    frame/time ranges satisfy ``end >= start`` when both bounds are given."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="after")
    def _finite_payload(self) -> Self:
        for key, value in self.__dict__.items():
            _assert_finite(value, key)
        return self

    @model_validator(mode="after")
    def _end_ge_start(self) -> Self:
        start_frame = getattr(self, "start_frame", None)
        end_frame = getattr(self, "end_frame", None)
        start_time_ms = getattr(self, "start_time_ms", None)
        end_time_ms = getattr(self, "end_time_ms", None)
        if start_frame is not None and end_frame is not None and end_frame < start_frame:
            raise ValueError("end_frame must be >= start_frame")
        if (
            start_time_ms is not None
            and end_time_ms is not None
            and end_time_ms < start_time_ms
        ):
            raise ValueError("end_time_ms must be >= start_time_ms")
        return self


# ── segmentation prompt evidence (strict shapes, R2 §3) ──────────────────────

class PromptPoint(_StrictModel):
    """One prompt point with the EXACT supported shape ``{x, y, label}``."""

    x: float = Field(..., allow_inf_nan=False)
    y: float = Field(..., allow_inf_nan=False)
    label: str

    @model_validator(mode="after")
    def _label_non_empty(self) -> Self:
        if not self.label.strip():
            raise ValueError("each point requires a non-empty string 'label'")
        return self


class PromptBox(_StrictModel):
    """One prompt box with the EXACT supported shape ``{x, y, w, h}``."""

    x: float = Field(..., allow_inf_nan=False)
    y: float = Field(..., allow_inf_nan=False)
    w: float = Field(..., ge=0, allow_inf_nan=False)
    h: float = Field(..., ge=0, allow_inf_nan=False)


class PromptEvidence(_StrictModel):
    """Deterministic prompt/segmentation evidence (points and/or boxes)."""

    points: list[PromptPoint] | None = None
    boxes: list[PromptBox] | None = None


# ── occurrence segment requests ──────────────────────────────────────────────

class SegmentCreateRequest(_StrictModel):
    """Create a CURRENT occurrence segment.

    ``source_generation`` and ``logical_id`` are intentionally ABSENT — they
    are server/repository-owned (the router resolves the backend-authoritative
    current generation; the repository owns the lineage identity).  A client
    that sends either receives an unknown-field 422 (extra="forbid").
    """

    project_id: str = Field(..., min_length=1, max_length=36)
    video_item_id: str = Field(..., min_length=1, max_length=36)
    role_id: str = Field(..., min_length=1, max_length=36)
    scene_id: str = Field(..., min_length=1, max_length=36)
    name: str = Field(..., min_length=1, max_length=240)
    kind: str = Field(..., pattern=OBJECT_KIND_PATTERN)
    start_frame: int = Field(..., ge=0)
    end_frame: int = Field(..., ge=0)
    start_time_ms: int = Field(..., ge=0)
    end_time_ms: int = Field(..., ge=0)
    source_job_id: str | None = Field(None, min_length=1, max_length=36)
    prompt: PromptEvidence | None = None
    segmentation: PromptEvidence | None = None
    mask_artifact_id: str | None = Field(None, min_length=1, max_length=36)
    algorithm: str | None = Field(None, min_length=1, max_length=64)
    algorithm_version: str | None = Field(None, min_length=1, max_length=64)
    confidence: float = Field(1.0, ge=0, le=1, allow_inf_nan=False)
    confidence_source: str = Field("model", pattern=CONFIDENCE_SOURCE_PATTERN)
    reasons: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    visibility: str = Field("visible", pattern=OCCURRENCE_SEGMENT_VISIBILITY_PATTERN)
    z_order: int = Field(0, ge=-1000000, le=1000000)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)


class SegmentUpdateRequest(_StrictModel):
    """CAS in-place update of the CURRENT ACTIVE segment."""

    revision: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=240)
    kind: str | None = Field(None, pattern=OBJECT_KIND_PATTERN)
    start_frame: int | None = Field(None, ge=0)
    end_frame: int | None = Field(None, ge=0)
    start_time_ms: int | None = Field(None, ge=0)
    end_time_ms: int | None = Field(None, ge=0)
    prompt: PromptEvidence | None = None
    segmentation: PromptEvidence | None = None
    mask_artifact_id: str | None = Field(None, min_length=1, max_length=36)
    algorithm: str | None = Field(None, min_length=1, max_length=64)
    algorithm_version: str | None = Field(None, min_length=1, max_length=64)
    confidence: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None
    visibility: str | None = Field(None, pattern=OCCURRENCE_SEGMENT_VISIBILITY_PATTERN)
    z_order: int | None = Field(None, ge=-1000000, le=1000000)


class SegmentSupersedeRequest(_StrictModel):
    """AUDITED correction of a segment (CAS).

    Covers BOTH C1-F1 workflows without exposing ``source_generation``: the
    router resolves the backend-authoritative current generation and the
    repository decides workflow A (manual same-generation, requires
    ``user``/``manual`` confidence_source) versus workflow B (re-analysis
    transition, requires a producing ``source_job_id``).
    """

    revision: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=240)
    kind: str | None = Field(None, pattern=OBJECT_KIND_PATTERN)
    start_frame: int | None = Field(None, ge=0)
    end_frame: int | None = Field(None, ge=0)
    start_time_ms: int | None = Field(None, ge=0)
    end_time_ms: int | None = Field(None, ge=0)
    source_job_id: str | None = Field(None, min_length=1, max_length=36)
    target_role_id: str | None = Field(None, min_length=1, max_length=36)
    prompt: PromptEvidence | None = None
    segmentation: PromptEvidence | None = None
    mask_artifact_id: str | None = Field(None, min_length=1, max_length=36)
    algorithm: str | None = Field(None, min_length=1, max_length=64)
    algorithm_version: str | None = Field(None, min_length=1, max_length=64)
    confidence: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    confidence_source: str | None = Field(None, pattern=CONFIDENCE_SOURCE_PATTERN)
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None
    visibility: str | None = Field(None, pattern=OCCURRENCE_SEGMENT_VISIBILITY_PATTERN)
    z_order: int | None = Field(None, ge=-1000000, le=1000000)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)


# ── motion / occlusion / contact requests ────────────────────────────────────

class MotionCreateRequest(_StrictModel):
    """Create one camera-relative / object-relative transform contract."""

    occurrence_segment_id: str = Field(..., min_length=1, max_length=36)
    transform_type: str = Field(..., pattern=MOTION_TRANSFORM_PATTERN)
    transform: dict[str, Any]
    point_track_flow_ref: dict[str, Any] | list[Any] | None = None
    start_frame: int = Field(..., ge=0)
    end_frame: int = Field(..., ge=0)
    start_time_ms: int = Field(..., ge=0)
    end_time_ms: int = Field(..., ge=0)
    algorithm: str | None = Field(None, min_length=1, max_length=64)
    algorithm_version: str | None = Field(None, min_length=1, max_length=64)
    confidence: float = Field(1.0, ge=0, le=1, allow_inf_nan=False)
    confidence_source: str = Field("model", pattern=CONFIDENCE_SOURCE_PATTERN)
    reasons: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _transform_is_object(self) -> Self:
        if not isinstance(self.transform, dict):
            raise ValueError("transform must be a JSON object")
        return self


class MotionUpdateRequest(_StrictModel):
    """CAS update of one motion record."""

    revision: int = Field(..., ge=1)
    transform: dict[str, Any] | None = None
    point_track_flow_ref: dict[str, Any] | list[Any] | None = None
    end_frame: int | None = Field(None, ge=0)
    end_time_ms: int | None = Field(None, ge=0)
    confidence: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None


class OcclusionCreateRequest(_StrictModel):
    """Create one occlusion edge (occluder -> occludee)."""

    project_id: str = Field(..., min_length=1, max_length=36)
    video_item_id: str = Field(..., min_length=1, max_length=36)
    occluder_segment_id: str = Field(..., min_length=1, max_length=36)
    occludee_segment_id: str = Field(..., min_length=1, max_length=36)
    start_frame: int = Field(..., ge=0)
    end_frame: int = Field(..., ge=0)
    start_time_ms: int = Field(..., ge=0)
    end_time_ms: int = Field(..., ge=0)
    algorithm: str | None = Field(None, min_length=1, max_length=64)
    algorithm_version: str | None = Field(None, min_length=1, max_length=64)
    confidence: float = Field(1.0, ge=0, le=1, allow_inf_nan=False)
    confidence_source: str = Field("model", pattern=CONFIDENCE_SOURCE_PATTERN)
    reasons: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)


class OcclusionUpdateRequest(_StrictModel):
    """CAS update of one occlusion edge."""

    revision: int = Field(..., ge=1)
    end_frame: int | None = Field(None, ge=0)
    end_time_ms: int | None = Field(None, ge=0)
    confidence: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None


class ContactCreateRequest(_StrictModel):
    """Create one contact edge/event (source -> target)."""

    project_id: str = Field(..., min_length=1, max_length=36)
    video_item_id: str = Field(..., min_length=1, max_length=36)
    source_segment_id: str = Field(..., min_length=1, max_length=36)
    target_segment_id: str = Field(..., min_length=1, max_length=36)
    contact_kind: str = Field(..., pattern=CONTACT_KIND_PATTERN)
    start_frame: int = Field(..., ge=0)
    end_frame: int = Field(..., ge=0)
    start_time_ms: int = Field(..., ge=0)
    end_time_ms: int = Field(..., ge=0)
    algorithm: str | None = Field(None, min_length=1, max_length=64)
    algorithm_version: str | None = Field(None, min_length=1, max_length=64)
    confidence: float = Field(1.0, ge=0, le=1, allow_inf_nan=False)
    confidence_source: str = Field("model", pattern=CONFIDENCE_SOURCE_PATTERN)
    reasons: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)


class ContactUpdateRequest(_StrictModel):
    """CAS update of one contact edge."""

    revision: int = Field(..., ge=1)
    end_frame: int | None = Field(None, ge=0)
    end_time_ms: int | None = Field(None, ge=0)
    confidence: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None


# ── read models (DTO boundary — never ORM objects) ───────────────────────────

class SegmentData(_StrictModel):
    """One occurrence segment read; ``state`` is explicit current/historical."""

    id: str
    logical_id: str
    lineage_version: int
    workspace_id: str
    project_id: str
    video_item_id: str
    role_id: str
    scene_id: str
    name: str
    kind: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    source_generation: str
    source_job_id: str | None
    prompt: PromptEvidence | None
    segmentation: PromptEvidence | None
    mask_artifact_id: str | None
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    visibility: str
    z_order: int
    superseded_by_id: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str]
    provenance: dict[str, Any]
    state: str  # "current" | "historical" (never mixed)


class MotionData(_StrictModel):
    """One segment motion record read model."""

    id: str
    workspace_id: str
    occurrence_segment_id: str
    transform_type: str
    transform: dict[str, Any]
    point_track_flow_ref: dict[str, Any] | list[Any] | None
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str]
    provenance: dict[str, Any]


class OcclusionData(_StrictModel):
    """One occlusion edge read model."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    occluder_segment_id: str
    occludee_segment_id: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str]
    provenance: dict[str, Any]


class ContactData(_StrictModel):
    """One contact edge read model."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_segment_id: str
    target_segment_id: str
    contact_kind: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str]
    provenance: dict[str, Any]


class SegmentListResponse(_StrictModel):
    """Paged segment listing; ``scope`` never mixes current and historical."""

    workspace_id: str
    limit: int
    offset: int
    total: int
    scope: str  # "current" | "historical"
    current_generation: str | None
    source_generation: str | None
    segments: list[SegmentData]


class LineageResponse(_StrictModel):
    """A segment lineage, OLDEST -> NEWEST (all versions)."""

    workspace_id: str
    logical_id: str
    versions: list[SegmentData]


class SupersedeResultData(_StrictModel):
    """Manual correction / re-analysis result: predecessor historical,
    successor current, shared logical lineage, revisions and provenance — no
    silent mutation."""

    predecessor: SegmentData
    successor: SegmentData
    logical_id: str
    source_generation: str
    predecessor_revision: int
    successor_revision: int

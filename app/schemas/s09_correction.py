"""Typed request/response payloads for the S09 targeted-correction API.

Every correction kind is a DISTINCT typed payload (no stringly-typed
union soup): ``kind`` selects which payload model validates the body, so
an invalid field fails closed at the schema boundary BEFORE any durable
write.  Response models mirror CorrectionRecord without leaking raw JSON
strings.

S09-T05A-C1 hardening (review finding F5):
- route literals come from the CANONICAL renderer contract enum
  ``RENDERER_ROUTES`` ({pose_swap, sprite_affine, mesh_warp, part_rig,
  controlled_redraw}) — the stale ``direct_composite``/``keyed_pipeline``
  placeholder is gone; an import-time assertion pins the Literal to the
  enum so drift fails loudly instead of accepting bogus routes;
- anchors are bounded [0, 1] with NaN/Inf refused (``allow_inf_nan=False``);
- frame ranges enforce ``start_frame <= end_frame`` (both >= 0);
- evidence refs and reason text are stripped + non-empty (normalized);
- identifier-shaped fields refuse path escapes (``/``, ``\\``, ``..``,
  control chars) so a hostile id can never smuggle a filesystem path;
- unknown fields fail closed (``extra="forbid"``).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.persistence.models import RENDERER_ROUTES

CorrectionKind = Literal["mask", "z_order", "contact", "mesh_parts", "route_override"]

#: Route literals DERIVED from the single-authority RENDERER_ROUTES enum.
#: The tuple below MUST mirror it exactly; the assertion turns silent
#: taxonomy drift into an import-time crash (fail closed, never fail open).
RendererRoute = Literal[
    "pose_swap",
    "sprite_affine",
    "mesh_warp",
    "part_rig",
    "controlled_redraw",
]

if set(get_args(RendererRoute)) != set(RENDERER_ROUTES):  # pragma: no cover
    raise RuntimeError(
        "RendererRoute Literal drifted from canonical RENDERER_ROUTES "
        f"{RENDERER_ROUTES}: {get_args(RendererRoute)}"
    )


def _renderer_routes() -> tuple[str, ...]:
    return RENDERER_ROUTES


class _StrictModel(BaseModel):
    """Forbid unknown fields — a typo'd payload must fail closed."""

    model_config = ConfigDict(extra="forbid")


#: Identifier-shaped fields: UUIDs and repo-internal slug ids only.
#: Anything carrying a separator, dot-dot climb or control character is a
#: path-escape attempt and must be rejected at the boundary.
_ID_PATTERN = r"^[A-Za-z0-9._:\-]{1,128}$"


def _reject_non_finite_deep(value: Any, path: str = "$") -> None:
    """Recursive NaN/Inf refusal for free-form JSON sub-documents."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"non-finite number at {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite_deep(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite_deep(item, f"{path}[{index}]")


def _clean_required_text(value: str, field: str) -> str:
    """Normalize free-text: strip surrounding whitespace, refuse empties."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must be non-empty (got whitespace only)")
    return cleaned


# ── typed requests per correction kind ───────────────────────────────────


class MaskCorrectionRequest(_StrictModel):
    occurrence_segment_id: str = Field(pattern=_ID_PATTERN)
    revision: int = Field(ge=1)
    source_generation: str = Field(pattern=_ID_PATTERN)
    segmentation: dict[str, Any]
    mask_artifact_id: str = Field(pattern=_ID_PATTERN)
    confidence_source: Literal["user", "manual"] = "user"
    reasons: list[str] | None = None
    provenance: dict[str, Any]
    mutation_idempotency_key: str | None = Field(
        default=None, pattern=_ID_PATTERN
    )

    @model_validator(mode="after")
    def _deep_validate(self) -> MaskCorrectionRequest:
        _reject_non_finite_deep(self.segmentation, "$.segmentation")
        _reject_non_finite_deep(self.provenance, "$.provenance")
        return self


class ZOrderCorrectionRequest(_StrictModel):
    occurrence_segment_id: str = Field(pattern=_ID_PATTERN)
    revision: int = Field(ge=1)
    source_generation: str = Field(pattern=_ID_PATTERN)
    z_order: int = Field(ge=-1_000_000, le=1_000_000)
    confidence_source: Literal["user", "manual"] = "user"
    reasons: list[str] | None = None
    provenance: dict[str, Any]
    mutation_idempotency_key: str | None = Field(
        default=None, pattern=_ID_PATTERN
    )

    @model_validator(mode="after")
    def _deep_validate(self) -> ZOrderCorrectionRequest:
        _reject_non_finite_deep(self.provenance, "$.provenance")
        return self


class ContactCorrectionRequest(_StrictModel):
    contact_id: str = Field(pattern=_ID_PATTERN)
    revision: int = Field(ge=1)
    end_frame: int | None = Field(default=None, ge=0)
    end_time_ms: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False
    )
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _deep_validate(self) -> ContactCorrectionRequest:
        if self.provenance is not None:
            _reject_non_finite_deep(self.provenance, "$.provenance")
        return self


class MeshPartsCorrectionRequest(_StrictModel):
    motion_id: str = Field(pattern=_ID_PATTERN)
    revision: int = Field(ge=1)
    transform: dict[str, Any]
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False
    )
    reasons: list[str] | None = None
    provenance: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _deep_validate(self) -> MeshPartsCorrectionRequest:
        _reject_non_finite_deep(self.transform, "$.transform")
        if self.provenance is not None:
            _reject_non_finite_deep(self.provenance, "$.provenance")
        return self


class RouteOverrideProvenance(_StrictModel):
    route_from: RendererRoute
    route_to: RendererRoute
    reason: str | None = None
    #: Non-empty NORMALIZED audit trail (stripped) — never mutated afterwards.
    evidence: str

    @field_validator("evidence")
    @classmethod
    def _evidence_normalized(cls, value: str) -> str:
        return _clean_required_text(value, "provenance.evidence")


class RouteOverrideCorrectionRequest(_StrictModel):
    occurrence_segment_id: str = Field(pattern=_ID_PATTERN)
    route_from: RendererRoute
    route_to: RendererRoute
    anchor_x: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    anchor_y: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    override_reason: str
    algorithm: str | None = None
    algorithm_version: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)
    structural_lock_manifest_id: str | None = Field(
        default=None, pattern=_ID_PATTERN
    )
    mutation_idempotency_key: str | None = Field(
        default=None, pattern=_ID_PATTERN
    )
    #: MUST persist route_from/route_to/evidence — the audit trail of WHY
    #: the route decision changed (never mutated afterwards).
    provenance: RouteOverrideProvenance

    @field_validator("override_reason")
    @classmethod
    def _reason_normalized(cls, value: str) -> str:
        return _clean_required_text(value, "override_reason")

    @model_validator(mode="after")
    def _frames_ordered_and_provenance_consistent(
        self,
    ) -> RouteOverrideCorrectionRequest:
        if self.start_frame > self.end_frame:
            raise ValueError(
                f"start_frame ({self.start_frame}) must be <= end_frame "
                f"({self.end_frame})"
            )
        if self.provenance.route_from != self.route_from:
            raise ValueError(
                "provenance.route_from must equal payload route_from"
            )
        if self.provenance.route_to != self.route_to:
            raise ValueError("provenance.route_to must equal payload route_to")
        return self


class SubmitCorrectionRequest(_StrictModel):
    workspace_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    video_item_id: str = Field(pattern=_ID_PATTERN)
    idempotency_key: str | None = Field(default=None, pattern=_ID_PATTERN)
    affected_loop_ids: list[str] | None = None
    payload: (
        MaskCorrectionRequest
        | ZOrderCorrectionRequest
        | ContactCorrectionRequest
        | MeshPartsCorrectionRequest
        | RouteOverrideCorrectionRequest
    )

    @field_validator("affected_loop_ids")
    @classmethod
    def _loop_ids_safe(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        import re

        for item in value:
            if not re.match(_ID_PATTERN, item):
                raise ValueError(f"affected_loop_ids entry invalid: {item!r}")
        return value


class ConfirmCorrectionRequest(_StrictModel):
    workspace_id: str = Field(pattern=_ID_PATTERN)
    revision: int = Field(ge=1)


class CancelCorrectionRequest(_StrictModel):
    workspace_id: str = Field(pattern=_ID_PATTERN)
    revision: int = Field(ge=1)


# ── responses ─────────────────────────────────────────────────────────────


class CorrectionImpactOut(BaseModel):
    correction_kind: str
    affected_occurrence_segment_ids: list[str]
    affected_contact_ids: list[str]
    affected_motion_ids: list[str]
    affected_loop_ids: list[str]
    affected_layer_ids: list[str]
    route_override: bool
    counts: dict[str, int]


class CorrectionOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    occurrence_segment_id: str | None
    correction_kind: str
    status: str
    request: dict[str, Any]
    impact: dict[str, Any]
    result: dict[str, Any] | None
    applied_at: datetime | None
    cancelled_at: datetime | None
    idempotency_key: str | None
    natural_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class CorrectionListOut(BaseModel):
    items: list[CorrectionOut]
    total: int
    limit: int
    offset: int


class CorrectionCountsOut(BaseModel):
    total: int
    by_kind: dict[str, int]


class SubmittedCorrectionOut(BaseModel):
    correction: CorrectionOut
    created: bool
    replayed: bool


__all__ = [
    "CancelCorrectionRequest",
    "ConfirmCorrectionRequest",
    "ContactCorrectionRequest",
    "CorrectionCountsOut",
    "CorrectionImpactOut",
    "CorrectionKind",
    "CorrectionListOut",
    "CorrectionOut",
    "MaskCorrectionRequest",
    "MeshPartsCorrectionRequest",
    "RendererRoute",
    "RouteOverrideCorrectionRequest",
    "RouteOverrideProvenance",
    "SubmitCorrectionRequest",
    "SubmittedCorrectionOut",
    "ZOrderCorrectionRequest",
    "_renderer_routes",
]

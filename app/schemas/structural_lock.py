"""Pydantic schemas for the StructuralLock persistence domain (S09-T00-I01).

Strict, finite-only, extra-forbidden DTOs mirroring the durable core in
``app.persistence.structural_lock``.  These models are the typed shape
S09 consumers (mapping contract, T06 apply) use when exposing or pinning
locks, plus the bounded public producer request/response added by
S09-LOCK-PRODUCER-B01 (router ``app/api/routes/structural_lock.py``,
mounted in ``app/api/app.py``).

Invariants (mirroring sibling schema modules):
- ``model_config = ConfigDict(extra="forbid")`` on every model — unknown
  field is a ValidationError before it ever reaches the repository.
- Renderer routes are DERIVED from ``models.RENDERER_ROUTES`` via a shared
  ``Literal`` — the exact five-value enum {pose_swap, sprite_affine,
  mesh_warp, part_rig, controlled_redraw}, never duplicated literals.
- Contact anchors are normalized x/y ∈ [0,1] with finite-only enforcement.
- Manifest hash must be lowercase sha256 hex; policy versions are bounded.
- The client can NEVER fabricate workspace authority: workspace_id never
  appears in request models (server-owned DEFAULT_WORKSPACE_ID at the API
  layer).
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.persistence.models import RENDERER_ROUTES

RendererRoute = Literal["pose_swap", "sprite_affine", "mesh_warp", "part_rig", "controlled_redraw"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POLICY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PolicyVersion = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")]
SourceGeneration = Annotated[str, Field(min_length=1, max_length=64)]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _reject_non_finite(value: Any) -> Any:
    """Post-validation walk rejecting NaN/Infinity nested in JSON payloads."""
    if isinstance(value, float) and not (
        value == value and -1e308 < value < 1e308  # NaN / ±Inf guard
    ):
        raise ValueError("finite numbers only (NaN/Infinity rejected)")
    if isinstance(value, dict):
        for _key, item in value.items():
            _reject_non_finite(item)
    elif isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    return value


class Timebase(_StrictBase):
    """Frozen timebase fingerprint of the locked source."""

    fps: float = Field(..., gt=0.0, allow_inf_nan=False)
    time_base: str = Field(..., min_length=1, max_length=64)
    start_time_ms: int = Field(..., ge=0)


class Fingerprints(_StrictBase):
    """Deterministic topology fingerprints (lowercase sha256 hex)."""

    z_order: Sha256Hex
    contacts: Sha256Hex


class AnchorXY(_StrictBase):
    """Normalized contact anchor inside the source frame — x,y ∈ [0,1]."""

    x: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    y: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)


class LockedSegment(_StrictBase):
    """Per-segment lock summary embedded in the manifest payload."""

    occurrence_segment_id: str = Field(..., min_length=1)
    route: RendererRoute
    anchor: AnchorXY
    start_frame: int = Field(..., ge=0)
    end_frame: int = Field(..., ge=0)
    provenance: dict[str, Any]

    @field_validator("provenance")
    @classmethod
    def _prov_finite(cls, v: dict[str, Any]) -> dict[str, Any]:
        _reject_non_finite(v)
        return v

    @field_validator("end_frame")
    @classmethod
    def _end_ge_start(cls, v: int, info: Any) -> int:
        start = info.data.get("start_frame")
        if start is not None and v < start:
            raise ValueError("end_frame must be >= start_frame")
        return v


class StructuralLockManifestPayload(_StrictBase):
    """Canonical StructuralLockManifest payload (fail-closed shape)."""

    frame_count: int = Field(..., ge=0)
    timebase: Timebase
    shot_order: list[str] = Field(..., min_length=0)

    @field_validator("shot_order")
    @classmethod
    def _unique_nonempty_shots(cls, v: list[str]) -> list[str]:
        if any(not s.strip() for s in v):
            raise ValueError("shot ids must be non-empty")
        if len(set(v)) != len(v):
            raise ValueError("shot_order must contain unique shot ids")
        return v

    fingerprints: Fingerprints
    segments: list[LockedSegment] = Field(default_factory=list)

    @field_validator("segments")
    @classmethod
    def _unique_segments(cls, v: list[LockedSegment]) -> list[LockedSegment]:
        ids = [s.occurrence_segment_id for s in v]
        if len(set(ids)) != len(ids):
            raise ValueError("segments must reference each occurrence segment at most once")
        return v

    policy_version: PolicyVersion


class SegmentRenderRouteCreate(_StrictBase):
    """Request shape for persisting one renderer-route decision.

    Mirrors ``StructuralLockRepository.record_render_route``; ownership ids
    are supplied by the caller of the persistence layer (the future router
    resolves them server-side).
    """

    occurrence_segment_id: str = Field(..., min_length=1)
    route: RendererRoute
    anchor_x: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    anchor_y: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    start_frame: int = Field(..., ge=0)
    end_frame: int = Field(..., ge=0)
    provenance: dict[str, Any] | None = None
    reasons: list[str] | None = None
    algorithm: str | None = Field(default=None, max_length=64)
    algorithm_version: str | None = Field(default=None, max_length=64)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, allow_inf_nan=False)
    confidence_source: Literal["model", "detector", "user", "manual", "derived"] = "model"
    structural_lock_manifest_id: str | None = None

    @field_validator("provenance")
    @classmethod
    def _prov_finite(
        cls, v: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if v is not None:
            _reject_non_finite(v)
        return v

    @field_validator("end_frame")
    @classmethod
    def _end_ge_start(cls, v: int, info: Any) -> int:
        start = info.data.get("start_frame")
        if start is not None and v < start:
            raise ValueError("end_frame must be >= start_frame")
        return v


class ReskinLockPinUpdate(_StrictBase):
    """CAS pin payload for ReskinConfig additive lock columns."""

    expected_revision: int = Field(..., ge=1)
    structural_lock_manifest_id: str | None = None
    lock_policy_version: PolicyVersion | None = None


class CheckpointLockPinSet(_StrictBase):
    """One-shot immutable pin payload for ApplyCheckpoint lock columns."""

    structural_lock_manifest_id: str | None = None
    lock_policy_version: PolicyVersion | None = None


class StructuralLockProduceRequest(_StrictBase):
    """Bounded public producer request (S09-LOCK-PRODUCER-B01).

    The client may ONLY select the documented policy version and assert the
    expected CURRENT identity (a stale expectation fails closed as a typed
    conflict).  It never supplies authority: workspace ids, filesystem
    paths, routes, manifest blobs or readiness flags are NOT fields, and
    any unknown key is rejected (``extra="forbid"`` → 422).
    """

    expected_source_generation: SourceGeneration | None = None
    expected_source_sha256: Sha256Hex | None = None
    policy_version: PolicyVersion | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class StructuralLockProduceResponse(_StrictBase):
    """Durable identity of the produced/replayed StructuralLockManifest."""

    workspace_id: str = Field(..., min_length=1, max_length=64)
    project_id: str = Field(..., min_length=1, max_length=64)
    video_item_id: str = Field(..., min_length=1, max_length=64)
    manifest_id: str = Field(..., min_length=1, max_length=36)
    manifest_hash: Sha256Hex
    source_generation: SourceGeneration
    source_frame_count: int = Field(..., ge=1)
    source_fps_num: int = Field(..., ge=1)
    source_fps_den: int = Field(..., ge=1)
    policy_version: PolicyVersion
    version: int = Field(..., ge=1)
    status: Literal["draft", "active", "superseded", "voided"]
    created: bool
    segment_count: int = Field(..., ge=0)
    route_decisions_created: int = Field(..., ge=0)
    reasons: list[str] = Field(default_factory=list)


# Re-exported single authority so downstream modules never re-declare the enum.
RENDERER_ROUTE_VALUES: tuple[str, ...] = RENDERER_ROUTES

__all__ = [
    "AnchorXY",
    "CheckpointLockPinSet",
    "Fingerprints",
    "LockedSegment",
    "RENDERER_ROUTE_VALUES",
    "RendererRoute",
    "ReskinLockPinUpdate",
    "SegmentRenderRouteCreate",
    "StructuralLockManifestPayload",
    "StructuralLockProduceRequest",
    "StructuralLockProduceResponse",
    "Timebase",
]

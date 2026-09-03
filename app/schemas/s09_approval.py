"""Typed request/response payloads for the S09-T06A approval API.

Every approval surface is a DISTINCT typed payload (no stringly-typed
union soup): unknown fields fail closed at the schema boundary BEFORE any
durable write (``extra="forbid"``).  Response models mirror the
S09ApprovalRecord without leaking raw JSON strings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Route literals DERIVED from the single-authority RENDERER_ROUTES enum.
RendererRoute = Literal["pose_swap", "sprite_affine", "mesh_warp", "part_rig", "controlled_redraw"]


class _StrictModel(BaseModel):
    """Forbid unknown fields — a typo'd payload must fail closed."""

    model_config = ConfigDict(extra="forbid")


# ── typed requests ────────────────────────────────────────────────────────


class SubmitCheckpointRequest(_StrictModel):
    """One immutable apply-checkpoint submission (the whole approval)."""

    reskin_config_id: str = Field(min_length=1)
    expected_reskin_revision: int = Field(ge=1)
    pack_version_ids: list[str] = Field(min_length=1, max_length=64)
    demo_artifact_ids: list[str] = Field(default_factory=list, max_length=256)
    correction_ids: list[str] = Field(default_factory=list, max_length=4096)
    accepted_warnings: list[str] = Field(default_factory=list, max_length=256)
    overrides: list[str] = Field(default_factory=list, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=255)


class ReplayProbeRequest(_StrictModel):
    """Explicit replay probe: equivalent → replayed row; different → 409."""

    idempotency_key: str = Field(min_length=1, max_length=255)


class ConflictProbeRequest(_StrictModel):
    """Deliberately conflicting submission under an existing key."""

    reskin_config_id: str = Field(min_length=1)
    expected_reskin_revision: int = Field(ge=1)
    pack_version_ids: list[str] = Field(min_length=1, max_length=64)
    demo_artifact_ids: list[str] = Field(default_factory=list, max_length=256)
    correction_ids: list[str] = Field(default_factory=list, max_length=4096)
    accepted_warnings: list[str] = Field(default_factory=list, max_length=256)
    overrides: list[str] = Field(default_factory=list, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)


# ── responses ─────────────────────────────────────────────────────────────


class ReapproveRequest(_StrictModel):
    """Reapproval payload — creates a NEW ``s09.approval/v2`` checkpoint.

    Mirrors :class:`SubmitCheckpointRequest` exactly: the SAME closed-domain
    fields a v1 submission accepts.  The v2 path freezes the nested
    ``full_apply_authority`` (persisted/canonical server authority) into the
    snapshot, so the deterministic reapproval produces a NEW content
    hash/audit identity.  Unknown fields fail closed (extra="forbid").
    """

    reskin_config_id: str = Field(min_length=1)
    expected_reskin_revision: int = Field(ge=1)
    pack_version_ids: list[str] = Field(min_length=1, max_length=64)
    demo_artifact_ids: list[str] = Field(default_factory=list, max_length=256)
    correction_ids: list[str] = Field(default_factory=list, max_length=4096)
    accepted_warnings: list[str] = Field(default_factory=list, max_length=256)
    overrides: list[str] = Field(default_factory=list, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=255)


class FullApplyAuthorityOut(_StrictModel):
    """Server-derived Full Apply authority for ONE checkpoint.

    ``snapshot_schema`` is the frozen snapshot schema (``s09.approval/v2``
    for an executable authority; a v1 checkpoint fails closed with
    ``REAPPROVAL_REQUIRED`` in the HTTP detail instead of a 200 here).
    ``verified`` is the live recomputed checkpoint-hash result.  The
    ``eligibility`` object is the immutable freeze-time capability verdict
    (route unsupported / authority incomplete reasons — never a downgrade).
    """

    checkpoint_id: str
    snapshot_schema: str
    verified: bool
    eligibility: dict[str, Any]
    full_apply_authority: dict[str, Any]


class CheckpointSegmentRouteOut(BaseModel):
    """CompatibilityPolicy evidence for ONE renderer route decision."""

    model_config = ConfigDict(extra="forbid")

    occurrence_segment_id: str
    route: RendererRoute
    anchor_x: float
    anchor_y: float
    start_frame: int
    end_frame: int
    confidence: float
    confidence_source: str
    reasons: list[str]
    provenance: dict[str, Any] | None
    structural_lock_manifest_id: str | None


class CheckpointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    reskin_config_id: str
    reskin_config_revision: int
    structural_lock_manifest_id: str | None
    lock_policy_version: str | None
    pack_version_ids: list[str]
    loop_hashes: list[dict[str, Any]]
    timebase_fingerprint: str
    snapshot: dict[str, Any]
    checkpoint_hash: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class SubmittedCheckpointOut(CheckpointOut):
    replayed: bool


class VerifyCheckpointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    verified: bool
    reason: str


class CheckpointListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    items: list[CheckpointOut]


__all__ = [
    "CheckpointListOut",
    "CheckpointOut",
    "CheckpointSegmentRouteOut",
    "ConflictProbeRequest",
    "FullApplyAuthorityOut",
    "ReapproveRequest",
    "ReplayProbeRequest",
    "SubmitCheckpointRequest",
    "SubmittedCheckpointOut",
    "VerifyCheckpointOut",
]

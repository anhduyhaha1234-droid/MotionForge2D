"""Strict schemas for the S10 FullApply domain (S10-T01A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["pending", "running", "verifying", "completed", "failed", "cancelled"]
ChunkState = Literal["pending", "running", "completed", "failed", "skipped"]
PublicationState = Literal["pending", "verifying", "completed", "failed"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── requests ─────────────────────────────────────────────────────────

class CreateFullApplyRunRequest(_StrictModel):
    project_id: str = Field(min_length=1)
    video_item_id: str = Field(min_length=1)
    apply_checkpoint_id: str = Field(min_length=1)
    expected_checkpoint_hash: str = Field(min_length=64, max_length=64)
    expected_checkpoint_revision: int = Field(ge=1)
    plan_id: str = Field(min_length=64, max_length=64)
    plan_hash: str = Field(min_length=64, max_length=64)
    frame_count: int = Field(ge=1)
    chunk_config: dict[str, Any]
    fps_num: int | None = Field(default=None, ge=1)
    fps_den: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=255)
    natural_key: str | None = Field(default=None, max_length=255)


class CreateChunkRequest(_StrictModel):
    run_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    order_index: int = Field(ge=0)
    shot_id: str = Field(min_length=1)
    core_start_frame: int = Field(ge=0)
    core_end_frame: int = Field(ge=0)
    content_hash: str = Field(min_length=64, max_length=64)
    overlap_before: int = Field(default=0, ge=0, le=64)
    overlap_after: int = Field(default=0, ge=0, le=64)
    layer_id: str | None = Field(default=None, max_length=128)
    object_role_id: str | None = Field(default=None, min_length=1)
    attempt: int = Field(default=1, ge=1)
    natural_key: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=255)


class MarkChunkVerifiedRequest(_StrictModel):
    artifact_id: str = Field(min_length=1)
    verified_content_hash: str = Field(min_length=64, max_length=64)


class CreatePublicationRequest(_StrictModel):
    run_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    frame_count: int = Field(ge=1)
    frame_metadata: dict[str, Any]
    checkpoint_id: str = Field(min_length=1)
    checkpoint_hash: str = Field(min_length=64, max_length=64)
    checkpoint_revision: int = Field(ge=1)
    natural_key: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=255)
    state: PublicationState = Field(default="pending")


# ── responses ────────────────────────────────────────────────────────

class S10RunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    apply_checkpoint_id: str
    apply_checkpoint_hash: str
    apply_checkpoint_revision: int
    plan_id: str
    plan_hash: str
    status: RunStatus
    frame_count: int
    fps_num: int | None
    fps_den: int | None
    chunk_config: dict[str, Any]
    attempt: int
    natural_key: str | None
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class S10ChunkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    workspace_id: str
    run_id: str
    chunk_index: int
    order_index: int
    shot_id: str
    layer_id: str | None
    object_role_id: str | None
    core_start_frame: int
    core_end_frame: int
    overlap_before: int
    overlap_after: int
    content_hash: str
    state: ChunkState
    attempt: int
    artifact_id: str | None
    verified: bool
    natural_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class S10PublicationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    workspace_id: str
    run_id: str
    artifact_id: str
    content_hash: str
    frame_count: int
    frame_metadata: dict[str, Any]
    checkpoint_id: str
    checkpoint_hash: str
    checkpoint_revision: int
    state: PublicationState
    natural_key: str | None
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ChunkState",
    "CreateChunkRequest",
    "CreateFullApplyRunRequest",
    "CreatePublicationRequest",
    "MarkChunkVerifiedRequest",
    "PublicationState",
    "RunStatus",
    "S10ChunkOut",
    "S10PublicationOut",
    "S10RunOut",
]

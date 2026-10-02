"""Strict schemas for the S10 FullApply domain (S10-T01A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


# ── execution backend manifest (MF-END-19.1) ─────────────────────────
#
# The backend axis is ORTHOGONAL to the legacy renderer routes (see
# ``app.schemas.shot_reskin.ExecutionBackend``).  The manifest travels inside
# ``chunk_config["execution_backend"]`` so the deterministic planner (the
# existing S10 authority) validates it, the run row persists it and the worker
# re-derives it before any render.  ABSENT => pure legacy behaviour with
# byte-identical plans to pre-19 runs.

ExecutionBackendName = Literal["legacy_renderer", "comfy_shot_engine"]

#: Per-unit anchor policy of the shot-level backend.  ``accepted_anchor_required``
#: is the DEFAULT: an accepted (and non-stale) MF-END-15 anchor manifest must
#: stand before any render.  ``pinned_input_only`` is an explicit, reasoned
#: DOWNGRADE — it must be declared with ``anchor_policy_reason``; a silent
#: ``require_accepted_anchor=False`` is refused.
AnchorPolicy = Literal["accepted_anchor_required", "pinned_input_only"]

#: Backends whose manifest must pin a registered profile + the frozen graph digest.
BACKENDS_REQUIRING_PROFILE: frozenset[str] = frozenset({"comfy_shot_engine"})


def _is_lower_hex64(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class ShotAnchorPin(_StrictModel):
    """One shot's digest-pinned start anchor (managed-root relative)."""

    relative_path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> ShotAnchorPin:
        if not _is_lower_hex64(self.sha256):
            raise ValueError("anchor sha256 must be lowercase hex64")
        return self


class ExecutionBackendManifest(_StrictModel):
    """Validated execution-backend manifest of one FullApply run (MF-END-19.1)."""

    backend: ExecutionBackendName
    profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    capability: str | None = Field(default=None, min_length=1, max_length=64)
    graph_file: str | None = Field(default=None, min_length=1, max_length=512)
    graph_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    output_node: str | None = Field(default=None, min_length=1, max_length=32)
    engine_base_url: str | None = Field(default=None, min_length=1, max_length=128)
    seed: int | None = Field(default=None, ge=0)
    shot_prompts: dict[str, str] = Field(default_factory=dict)
    shot_anchors: dict[str, ShotAnchorPin] = Field(default_factory=dict)
    shot_units: dict[str, str] = Field(default_factory=dict)
    anchor_policy: AnchorPolicy | None = None
    anchor_policy_reason: str | None = Field(default=None, max_length=400)
    require_accepted_anchor: bool = False

    @model_validator(mode="after")
    def _cross_check(self) -> ExecutionBackendManifest:
        if self.graph_sha256 is not None and not _is_lower_hex64(self.graph_sha256):
            raise ValueError("graph_sha256 must be lowercase hex64")
        if self.engine_base_url is not None and not self.engine_base_url.startswith(
            ("http://127.0.0.1:", "http://localhost:")
        ):
            raise ValueError(
                "engine_base_url must be loopback (the engine only drives a local instance)"
            )
        if self.backend in BACKENDS_REQUIRING_PROFILE:
            if not self.profile_id:
                raise ValueError(
                    f"backend {self.backend!r} requires profile_id (a registered eligible profile)"
                )
            if not self.graph_sha256:
                raise ValueError(
                    f"backend {self.backend!r} requires graph_sha256 (the frozen graph file pin)"
                )
            # MF-END-19 C19: every generation unit must be NAMED and every unit
            # must carry its own prompt (see the planner's shared-prompt refusal).
            if not self.shot_units:
                raise ValueError(
                    f"backend {self.backend!r} requires shot_units (shot_id -> unit_id): a "
                    "per-unit binding is mandatory, never an implicit one-prompt-for-all"
                )
            for shot_key, unit_id in sorted(self.shot_units.items()):
                if not str(shot_key).strip() or not str(unit_id).strip():
                    raise ValueError(
                        f"shot_units[{shot_key!r}] must map a shot to a non-empty unit id"
                    )
            # The accepted-anchor gate is ON by default.  Disabling it silently is
            # refused: a downgrade must be declared, with a reason, in the frozen
            # plan input (so it is visible in the run's authority + receipts).
            if self.anchor_policy == "pinned_input_only" and not (
                self.anchor_policy_reason or ""
            ).strip():
                raise ValueError(
                    "anchor_policy='pinned_input_only' requires anchor_policy_reason "
                    "(an unreasoned anchor-gate downgrade is refused)"
                )
            if (
                "require_accepted_anchor" in self.model_fields_set
                and not self.require_accepted_anchor
                and self.anchor_policy != "pinned_input_only"
            ):
                raise ValueError(
                    "require_accepted_anchor=False silently disables the accepted-anchor "
                    "gate; declare anchor_policy='pinned_input_only' with "
                    "anchor_policy_reason instead"
                )
        else:
            for name in (
                "profile_id",
                "capability",
                "graph_file",
                "graph_sha256",
                "output_node",
                "engine_base_url",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(f"backend {self.backend!r} cannot carry {name}")
            if self.seed is not None:
                raise ValueError(f"backend {self.backend!r} cannot carry a seed pin")
            if self.shot_prompts:
                raise ValueError(f"backend {self.backend!r} cannot carry shot_prompts")
            if self.shot_anchors:
                raise ValueError(f"backend {self.backend!r} cannot carry shot_anchors")
            if self.shot_units:
                raise ValueError(f"backend {self.backend!r} cannot carry shot_units")
            if self.anchor_policy is not None or self.anchor_policy_reason is not None:
                raise ValueError(f"backend {self.backend!r} cannot carry an anchor policy")
            if self.require_accepted_anchor:
                raise ValueError(f"backend {self.backend!r} cannot require_accepted_anchor")
        return self


__all__ = [
    "AnchorPolicy",
    "BACKENDS_REQUIRING_PROFILE",
    "ChunkState",
    "CreateChunkRequest",
    "CreateFullApplyRunRequest",
    "CreatePublicationRequest",
    "ExecutionBackendManifest",
    "ExecutionBackendName",
    "MarkChunkVerifiedRequest",
    "PublicationState",
    "RunStatus",
    "S10ChunkOut",
    "S10PublicationOut",
    "S10RunOut",
    "ShotAnchorPin",
]

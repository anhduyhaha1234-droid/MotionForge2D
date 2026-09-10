"""Frozen S12 export preflight contracts (S12-T01).

Contract-only module: strict, finite-only, extra-forbidden DTOs that freeze
the request/response shape, reason codes, manifest/profile/checkpoint/
validation/publication contracts for every later S12 task (T02, T03A/B/C,
T04A, T05, T06A/B).  No I/O, no DB, no render — pure frozen vocabulary.

Conventions mirror the S10/S11 schema modules:
- ``model_config = ConfigDict(extra="forbid")`` on every model.
- sha256 = lowercase 64-hex; policy versions bounded
  ``^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "S12_EXPORT_REASON_CODES",
    "PreflightReason",
    "ExportProfileId",
    "SourceKind",
    "AspectHandling",
    "CheckpointPin",
    "LockPin",
    "ManifestRef",
    "ExportProfile",
    "PreflightCheck",
    "ExportPreflightRequest",
    "ExportPreflightResponse",
    "ExportContextResponse",
    "ValidationContract",
    "PublicationContract",
    "S12_EXPORT_CONTRACT_VERSION",
]

#: Frozen contract version consumed by T02..T06B (bump = new Codex review).
S12_EXPORT_CONTRACT_VERSION = "s12-export-v1"

#: Closed reason-code vocabulary — every later task must reuse these codes.
S12_EXPORT_REASON_CODES: tuple[str, ...] = (
    "S12_EXPORT_OK",
    "S12_EXPORT_NOT_READY",
    "S12_EXPORT_SOURCE_MISSING",
    "S12_EXPORT_SOURCE_NOT_READY",
    "S12_EXPORT_SOURCE_PARTIAL",
    "S12_EXPORT_LOCK_MISSING",
    "S12_EXPORT_STALE_CHECKPOINT",
    "S12_EXPORT_STALE_POLICY",
    "S12_EXPORT_CROSS_PROJECT",
    "S12_EXPORT_UNSUPPORTED_PROFILE",
    "S12_EXPORT_ASPECT_MISMATCH",
    "S12_EXPORT_DISK_INSUFFICIENT",
    "S12_EXPORT_UNKNOWN_PROJECT",
    "S12_EXPORT_UNKNOWN_VIDEO",
    "S12_EXPORT_FULL_APPLY_MISSING",
    "S12_EXPORT_SOURCE_STALE",
    "S12_EXPORT_SOURCE_SPOOFED",
    "S12_EXPORT_CONFIG_MISSING",
)

PreflightReason = Literal[
    "S12_EXPORT_OK",
    "S12_EXPORT_NOT_READY",
    "S12_EXPORT_SOURCE_MISSING",
    "S12_EXPORT_SOURCE_NOT_READY",
    "S12_EXPORT_SOURCE_PARTIAL",
    "S12_EXPORT_LOCK_MISSING",
    "S12_EXPORT_STALE_CHECKPOINT",
    "S12_EXPORT_STALE_POLICY",
    "S12_EXPORT_CROSS_PROJECT",
    "S12_EXPORT_UNSUPPORTED_PROFILE",
    "S12_EXPORT_ASPECT_MISMATCH",
    "S12_EXPORT_DISK_INSUFFICIENT",
    "S12_EXPORT_UNKNOWN_PROJECT",
    "S12_EXPORT_UNKNOWN_VIDEO",
    "S12_EXPORT_FULL_APPLY_MISSING",
    "S12_EXPORT_SOURCE_STALE",
    "S12_EXPORT_SOURCE_SPOOFED",
    "S12_EXPORT_CONFIG_MISSING",
]

#: Render profiles frozen for T02 capability detection (T02 fills support).
ExportProfileId = Literal[
    "master-4k-h264",
    "master-4k-hevc",
    "preview-1080p-h264",
]

#: Provenance source kind — native vs upscale is provenance, never file size.
SourceKind = Literal["native_4k", "upscale_4k", "below_4k"]

#: Aspect handling policy (WS-08): preserve, never silent stretch/crop.
AspectHandling = Literal["passthrough", "letterbox", "fail_closed"]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckpointPin(_StrictBase):
    """Frozen checkpoint identity the exporter must present (S09/S10 pins)."""

    checkpoint_id: str = Field(min_length=1, max_length=36)
    checkpoint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_revision: int = Field(ge=1)


class LockPin(_StrictBase):
    """Structural-lock manifest pin tying the video to its frozen topology."""

    manifest_id: str = Field(min_length=1, max_length=36)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_generation: str = Field(min_length=1, max_length=64)


class ManifestRef(_StrictBase):
    """Versioned manifest identity for the export run (T03A consumes)."""

    manifest_id: str = Field(min_length=1, max_length=36)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: int = Field(ge=1)


class ExportProfile(_StrictBase):
    """Frozen render profile descriptor (capability filled by T02)."""

    profile_id: ExportProfileId
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    codec: Literal["h264", "hevc"]
    upscale_method: str | None = Field(default=None, max_length=64)
    supported: bool = False
    support_basis: str | None = Field(default=None, max_length=512)


class PreflightCheck(_StrictBase):
    """One named gate result inside the preflight response."""

    name: str = Field(min_length=1, max_length=64)
    passed: bool
    reason: PreflightReason
    detail: str = Field(max_length=1024)


class ExportPreflightRequest(_StrictBase):
    """POST /api/v2/projects/{project_id}/export/preflight body."""

    video_item_id: str = Field(min_length=1, max_length=36)
    profile_id: ExportProfileId = "master-4k-h264"
    aspect_handling: AspectHandling = "letterbox"
    checkpoint: CheckpointPin
    lock: LockPin


class ExportPreflightResponse(_StrictBase):
    """Preflight verdict — no render happens inside the HTTP request.

    ``authority`` carries the SERVER-RESOLVED durable identities (F02): the
    immutable current completed Full Apply output artifact and its owning
    run/publication.  ``job_id`` is the ACTUAL durable Job ID when this
    preflight is answered from an existing queued/running export job of the
    same lineage; it is ``null`` on a pure readiness verdict (no job was
    created — preflight never mutates).
    """

    contract_version: str = Field(default=S12_EXPORT_CONTRACT_VERSION)
    project_id: str = Field(min_length=1)
    video_item_id: str = Field(min_length=1)
    profile: ExportProfile
    source_kind: SourceKind
    source_provenance: str = Field(
        default="",
        max_length=64,
        description="proved-native | unproven (F-OBS-01: native label needs proof)",
    )
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    source_artifact_id: str | None = Field(default=None)
    source_sha256: str | None = Field(default=None)
    source_frame_count: int | None = Field(default=None, ge=1)
    source_fps_num: int | None = Field(default=None, ge=1)
    source_fps_den: int | None = Field(default=None, ge=1)
    full_apply_run_id: str | None = Field(default=None)
    full_apply_publication_id: str | None = Field(default=None)
    job_id: str | None = Field(default=None)
    eligible: bool
    reasons: list[PreflightReason] = Field(default_factory=list)
    checks: list[PreflightCheck] = Field(default_factory=list)
    estimate_bytes: int | None = Field(default=None, ge=0)
    estimate_basis: str = Field(default="", max_length=512)
    readiness_status: str = Field(default="")
    readiness_policy: str = Field(default="")


class ExportContextPlan(_StrictBase):
    """Server-owned plan identity used to submit a current export."""

    plan_id: str = Field(min_length=64, max_length=64)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_count: int = Field(ge=1)
    fps_num: int | None = Field(default=None, ge=1)
    fps_den: int | None = Field(default=None, ge=1)
    chunk_config: dict[str, Any] = Field(default_factory=dict)


class ExportContextRun(_StrictBase):
    """Scoped pointer to the latest durable S12 run, if one exists."""

    run_id: str
    status: str
    attempt: int = Field(ge=1)


class ExportContextResponse(_StrictBase):
    """Read-only backend-owned project/video context for the Export UI."""

    contract_version: str = Field(default=S12_EXPORT_CONTRACT_VERSION)
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_name: str | None = None
    video_item_id: str = Field(min_length=1)
    video_title: str | None = None
    video_status: str | None = None
    video_width: int | None = Field(default=None, ge=1)
    video_height: int | None = Field(default=None, ge=1)
    video_duration_ms: int | None = Field(default=None, ge=0)
    video_fps_num: int | None = Field(default=None, ge=1)
    video_fps_den: int | None = Field(default=None, ge=1)
    checkpoint: CheckpointPin | None = None
    lock: LockPin | None = None
    plan: ExportContextPlan | None = None
    profiles: list[ExportProfile] = Field(default_factory=list)
    current_run: ExportContextRun | None = None
    full_apply_run_id: str | None = None
    context_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    reasons: list[PreflightReason] = Field(default_factory=list)


class ValidationContract(_StrictBase):
    """Frozen output-validation contract consumed by T04A (validator)."""

    contract_version: str = Field(default=S12_EXPORT_CONTRACT_VERSION)
    required_probes: list[str] = Field(
        default_factory=lambda: [
            "resolution",
            "codec",
            "streams",
            "frame_count",
            "frame_order",
            "timebase",
            "duration",
            "av_policy",
            "provenance",
            "completeness",
        ]
    )
    resolution_width: int = 3840
    resolution_height: int = 2160
    verdicts: list[str] = Field(default_factory=lambda: ["PASS", "FAIL", "NOT_MEASURED"])
    partial_suffix: str = ".partial"
    extra: dict[str, Any] | None = None


class PublicationContract(_StrictBase):
    """Frozen publication gate consumed by T03C (validated publication)."""

    contract_version: str = Field(default=S12_EXPORT_CONTRACT_VERSION)
    requires_validation_pass: bool = True
    requires_current_readiness: bool = True
    requires_identity_match: bool = True
    requires_ownership_fence: bool = True
    no_overwrite_completed: bool = True
    partial_visible_as_completed: bool = False

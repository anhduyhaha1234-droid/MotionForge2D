"""Media engine contract V1 — capabilities, request/result DTOs, cache identity,
replay resolution, model registry and the shared GPU lease VIEW.

Frozen by MF-TOOL-CONTRACT.  This module is PURE: pydantic + stdlib only.  It
owns no database, no queue and no concurrency engine.

Two existing subsystems stay the single authority and are only *referenced*
here (see ``docs/technology/mf_engine_v1/MEDIA_ENGINE_CONTRACT.md``):

* renderer capability / route taxonomy —
  ``app/services/renderer_contract.py`` (``CapabilityDescriptor``,
  ``RendererContractCode``, fail-closed ``RendererRouterError`` family) and
  ``app/persistence/models.py::RENDERER_ROUTES`` (single taxonomy authority).
* E01 durable jobs — ``app/persistence/jobs.py`` (``JobRepository``, leases,
  idempotency keys, attempts) governed by
  ``docs/architecture/DURABLE_JOB_CONTRACT.md`` (V1.1).

Consequences enforced by this module, never by convention:

1. Capabilities are DISTINCT.  ``image_edit_multi_reference``,
   ``source_video_motion_transfer``, ``video_edit_controlled`` and
   ``text_to_video`` are separate values; a source-locked capability may not
   silently degrade to T2V/I2V.
2. Backend-managed artifacts are the authority.  Client paths and
   client-supplied graphs are refused with a typed code.
3. Cache identity is computed by the backend from the frozen request facts.
   A reference change invalidates the affected shots only.
4. An unresolved replay RE-ATTACHES or REFUSES.  There is no third action and
   no code path that can issue a second POST.
5. The model registry records release date separated from repo modification
   date, and a UI click can never trigger a download.
6. There is exactly one job store (E01) and one concurrency engine (the E01
   lease).  A second job database or a competing engine is refused.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ARTIFACT_KINDS",
    "CAPABILITY_ABSENCE_IS_EXPLICIT",
    "COMPETING_CONCURRENCY_ENGINE_ALLOWED",
    "E01_JOB_STORE",
    "FORBIDDEN_DEGRADATION_TARGETS",
    "IDENTITY_COMPONENT_FIELDS",
    "MEDIA_ENGINE_CONTRACT_VERSION",
    "NO_AUTO_DOWNLOAD_FROM_UI",
    "PUBLISHABLE_ARTIFACT_KINDS",
    "SECOND_JOB_DATABASE_ALLOWED",
    "SERVER_PUBLISHABLE_TYPES",
    "SOURCE_LOCKED_CAPABILITIES",
    "STATE_ORDER",
    "AudioHandoff",
    "CacheEntry",
    "CacheIdentity",
    "CastBinding",
    "CapabilityOffer",
    "CapabilitySet",
    "DecodedMap",
    "GpuLeaseGrant",
    "GpuLeaseRequest",
    "GpuLeaseView",
    "HardwareProfile",
    "InflightReservation",
    "InvalidationReport",
    "ManagedArtifact",
    "MediaCapability",
    "MediaEngineCancel",
    "MediaEngineFailure",
    "MediaEngineRefusal",
    "MediaEngineRefusalCode",
    "MediaEngineRequest",
    "MediaEngineResult",
    "MediaEngineState",
    "ModelPin",
    "ModelRegistry",
    "ModelRegistryEntry",
    "NodePin",
    "OutputContract",
    "ReferenceArtifact",
    "ReferenceChange",
    "ReplayAction",
    "ReplayDecision",
    "ResourceBudget",
    "ShotRange",
    "SourceLock",
    "StateTransition",
    "WorkflowPins",
    "assert_publishable_set",
    "assert_shared_stack",
    "cache_identity_for",
    "invalidate_for_reference_change",
    "resolve_replay",
]


MEDIA_ENGINE_CONTRACT_VERSION = "mf.media_engine.contract.v1"

#: A UI click must never start a download — models are provisioned out of band.
NO_AUTO_DOWNLOAD_FROM_UI = True
#: Exactly one durable job store: E01 (app/persistence/jobs.py).
E01_JOB_STORE = "e01_durable_jobs"
SECOND_JOB_DATABASE_ALLOWED = False
COMPETING_CONCURRENCY_ENGINE_ALLOWED = False
#: Capability absence is always stated with a reason code, never implied.
CAPABILITY_ABSENCE_IS_EXPLICIT = True

ARTIFACT_KINDS = ("image", "video", "audio", "pose_sheet", "mask", "graph")
#: Kinds that may ever leave the engine as a published output.  Masks, graphs and
#: pose sheets are intermediates: they are managed, but never publishable.
PUBLISHABLE_ARTIFACT_KINDS = ("image", "video", "audio")
#: The SERVER-owned publishable node-output types (COMFY round authority).  A
#: caller's ``OutputContract.publishable_types`` may only narrow this set.
SERVER_PUBLISHABLE_TYPES = ("output",)


class MediaEngineRefusalCode(str, Enum):
    """Typed refusal taxonomy.  Every refusal carries exactly one code."""

    CAPABILITY_UNAVAILABLE = "media_capability_unavailable"
    CAPABILITY_DEGRADATION_REFUSED = "capability_degradation_refused"
    CLIENT_ARTIFACT_PATH_REFUSED = "client_artifact_path_refused"
    CLIENT_GRAPH_REFUSED = "client_graph_refused"
    ARTIFACT_NOT_MANAGED = "artifact_not_managed"
    REPLAY_REFUSED = "replay_refused"
    MODEL_UNAVAILABLE = "model_unavailable"
    AUTO_DOWNLOAD_REFUSED = "auto_download_refused"
    GPU_LEASE_HELD = "gpu_lease_held"
    SECOND_JOB_STORE_REFUSED = "second_job_store_refused"
    COMPETING_CONCURRENCY_ENGINE_REFUSED = "competing_concurrency_engine_refused"
    STATE_TRANSITION_REFUSED = "state_transition_refused"


class MediaEngineRefusal(Exception):
    """Fail-closed refusal.  Never swallowed into a generic error."""

    def __init__(self, code: MediaEngineRefusalCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}


# ── capabilities ──────────────────────────────────────────────────────────────


class MediaCapability(str, Enum):
    """Distinct media-engine capabilities.  No aliases, no synonyms."""

    IMAGE_EDIT_MULTI_REFERENCE = "image_edit_multi_reference"
    SOURCE_VIDEO_MOTION_TRANSFER = "source_video_motion_transfer"
    VIDEO_EDIT_CONTROLLED = "video_edit_controlled"
    TEXT_TO_VIDEO = "text_to_video"


#: Capabilities whose input is a locked source clip.
SOURCE_LOCKED_CAPABILITIES: frozenset[MediaCapability] = frozenset(
    {
        MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER,
        MediaCapability.VIDEO_EDIT_CONTROLLED,
    }
)

#: A source-locked request may NEVER be served by any of these instead.
FORBIDDEN_DEGRADATION_TARGETS: dict[MediaCapability, frozenset[MediaCapability]] = {
    MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER: frozenset(
        {
            MediaCapability.TEXT_TO_VIDEO,
            MediaCapability.IMAGE_EDIT_MULTI_REFERENCE,
        }
    ),
    MediaCapability.VIDEO_EDIT_CONTROLLED: frozenset(
        {
            MediaCapability.TEXT_TO_VIDEO,
            MediaCapability.IMAGE_EDIT_MULTI_REFERENCE,
            MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER,
        }
    ),
}


class CapabilityOffer(BaseModel):
    """One capability as actually offered by a backend right now."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: MediaCapability
    available: bool
    #: Where the numbers came from — mirrors renderer_contract evidence_source.
    evidence_source: str = "declared"
    unavailable_reason_code: str | None = None
    measured_at_utc: str | None = None

    @model_validator(mode="after")
    def _check(self) -> CapabilityOffer:
        if self.evidence_source not in ("measured_live", "probed_config", "declared"):
            raise ValueError(
                "evidence_source must be measured_live|probed_config|declared"
            )
        if self.available and self.unavailable_reason_code is not None:
            raise ValueError("available capability must not carry a reason code")
        if not self.available and not self.unavailable_reason_code:
            # Capability absence is EXPLICIT, never implied.
            raise ValueError("unavailable capability requires an unavailable_reason_code")
        return self


class CapabilitySet(BaseModel):
    """The set of capabilities a deployment can serve, with explicit absence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offers: tuple[CapabilityOffer, ...]

    def _offer(self, capability: MediaCapability) -> CapabilityOffer | None:
        for offer in self.offers:
            if offer.capability == capability:
                return offer
        return None

    def assert_can_serve(
        self,
        requested: MediaCapability,
        *,
        substitute: MediaCapability | None = None,
        operator_approved_substitution: bool = False,
    ) -> CapabilityOffer:
        """Return the offer, or refuse.  Substitution is never silent.

        ``substitute`` is the capability a caller *proposes* to run instead.
        For a source-locked request, substituting a non-source-locked
        capability is refused outright — an operator approval cannot make a
        T2V/I2V result a legitimate motion transfer.
        """

        if substitute is not None and substitute != requested:
            forbidden = FORBIDDEN_DEGRADATION_TARGETS.get(requested, frozenset())
            if requested in SOURCE_LOCKED_CAPABILITIES and substitute in forbidden:
                raise MediaEngineRefusal(
                    MediaEngineRefusalCode.CAPABILITY_DEGRADATION_REFUSED,
                    f"{requested.value} may not be served as {substitute.value}: "
                    "source-locked routes never silently degrade to T2V/I2V",
                )
            if not operator_approved_substitution:
                raise MediaEngineRefusal(
                    MediaEngineRefusalCode.CAPABILITY_DEGRADATION_REFUSED,
                    f"substitution {requested.value} -> {substitute.value} "
                    "requires an explicit approved override",
                )
            requested = substitute

        offer = self._offer(requested)
        if offer is None:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CAPABILITY_UNAVAILABLE,
                f"{requested.value} is not offered by this deployment",
            )
        if not offer.available:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CAPABILITY_UNAVAILABLE,
                f"{requested.value}: {offer.unavailable_reason_code}",
            )
        return offer


# ── request facts ─────────────────────────────────────────────────────────────


class ShotRange(BaseModel):
    """Inclusive frame range in the source clip's own index space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> ShotRange:
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        return self

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame + 1

    def overlaps(self, other: ShotRange) -> bool:
        return self.start_frame <= other.end_frame and other.start_frame <= self.end_frame

    def key(self) -> str:
        return f"{self.start_frame}-{self.end_frame}"


class SourceLock(BaseModel):
    """Source hash + shot range + PTS.  Backend-resolved, never client paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_artifact_id: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64)
    shot_range: ShotRange
    pts_start_ticks: int = Field(ge=0)
    pts_end_ticks: int = Field(ge=0)
    fps_num: int = Field(gt=0)
    fps_den: int = Field(gt=0)

    @property
    def timebase(self) -> str:
        return f"{self.fps_num}/{self.fps_den}"


class ReferenceArtifact(BaseModel):
    """A managed artifact reference.  A raw path is refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    #: Present only so a client-supplied path can be REFUSED with a typed code
    #: instead of a generic pydantic error.
    path: str | None = None

    @model_validator(mode="after")
    def _check(self) -> ReferenceArtifact:
        if self.path:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                "reference artifacts must be addressed by managed artifact_id; "
                f"client path {self.path!r} is not accepted",
            )
        return self


class CastBinding(BaseModel):
    """role -> CharacterID + immutable PackVersion + reference artifact SHAs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    pack_version_id: str = Field(min_length=1)
    references: tuple[ReferenceArtifact, ...] = ()
    style_version: str | None = None

    def role_key(self) -> str:
        return self.role


class ModelPin(BaseModel):
    """Workflow model pin: id + revision + file hash + precision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    file_sha256: str = Field(min_length=64, max_length=64)
    precision: str = Field(min_length=1)


class NodePin(BaseModel):
    """Node pin: node id + class + config hash.  Config is opaque but hashed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1)
    node_class: str = Field(min_length=1)
    config_hash: str = Field(min_length=8)


class WorkflowPins(BaseModel):
    """Everything that must be pinned to make a render reproducible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str = Field(min_length=1)
    workflow_version: str = Field(min_length=1)
    workflow_hash: str = Field(min_length=8)
    model: ModelPin
    nodes: tuple[NodePin, ...] = ()
    config_hash: str = Field(min_length=8)
    seed: int = Field(ge=0)


class AudioHandoff(BaseModel):
    """How audio leaves the engine.  Typed — never an implicit passthrough."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str
    source_artifact_id: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None

    @model_validator(mode="after")
    def _check(self) -> AudioHandoff:
        if self.mode not in ("source_remux", "generated", "silent"):
            raise ValueError("mode must be source_remux|generated|silent")
        if self.mode == "source_remux" and not self.source_artifact_id:
            raise ValueError("source_remux requires source_artifact_id")
        return self


class OutputContract(BaseModel):
    """Decoded output contract: geometry, timebase, audio handoff, publish set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps_num: int = Field(gt=0)
    fps_den: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    container: str = Field(min_length=1)
    video_codec: str = Field(min_length=1)
    audio: AudioHandoff
    #: Server-owned publish allow-list; a caller may only NARROW it.
    publishable_types: tuple[str, ...] = SERVER_PUBLISHABLE_TYPES

    @model_validator(mode="after")
    def _check(self) -> OutputContract:
        if not set(self.publishable_types) <= set(SERVER_PUBLISHABLE_TYPES):
            raise ValueError(
                f"publishable_types may only narrow {SERVER_PUBLISHABLE_TYPES}; "
                f"got {self.publishable_types}"
            )
        return self

    @property
    def timebase(self) -> str:
        return f"{self.fps_num}/{self.fps_den}"


class ResourceBudget(BaseModel):
    """Resource budget handed to the shared GPU lease (E01 resource_class)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_class: str = Field(min_length=1)
    max_wall_seconds: float = Field(gt=0)
    max_vram_bytes: int = Field(ge=0)
    max_output_bytes: int = Field(gt=0)


class MediaEngineRequest(BaseModel):
    """The request DTO.  Ids + hashes + pins.  No paths, no graphs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    series_id: str | None = None
    video_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    job_id: str | None = None

    capability: MediaCapability
    source: SourceLock
    cast: tuple[CastBinding, ...] = ()
    pins: WorkflowPins
    output: OutputContract
    budget: ResourceBudget

    #: Declared ONLY so client-supplied inputs can be refused with a typed
    #: code.  A non-None value is a refusal, never an input.
    client_path: str | None = None
    client_graph: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _refuse_client_supplied_inputs(self) -> MediaEngineRequest:
        if self.client_path:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"backend-managed artifacts are the authority; path {self.client_path!r} "
                "is refused",
            )
        if self.client_graph is not None:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CLIENT_GRAPH_REFUSED,
                "client-supplied graphs are refused; the workflow is pinned server-side",
            )
        roles = [b.role for b in self.cast]
        if len(roles) != len(set(roles)):
            raise ValueError("cast roles must be unique within a request")
        return self


# ── cache identity ────────────────────────────────────────────────────────────


#: The exact component set of a cache identity digest.  ONE authority shared by
#: ``CacheIdentity._check`` and ``cache_identity_for`` so the payload that is
#: hashed and the fields that are validated can never drift apart.
IDENTITY_COMPONENT_FIELDS = (
    "identity_version",
    "source_sha256",
    "shot_range",
    "pts_start_ticks",
    "pts_end_ticks",
    "cast_digest",
    "pack_digest",
    "assets_digest",
    "style_digest",
    "workflow_digest",
    "model_digest",
    "settings_digest",
)


def _identity_payload(source: Any) -> dict[str, Any]:
    """Canonical digest payload from a ``CacheIdentity`` or a plain mapping."""

    if isinstance(source, dict):
        return {name: source[name] for name in IDENTITY_COMPONENT_FIELDS}
    return {name: getattr(source, name) for name in IDENTITY_COMPONENT_FIELDS}


class CacheIdentity(BaseModel):
    """Cache identity = source + range + cast + pack + assets + style +
    workflow + model + settings.  Computed by the backend, never supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_version: str = MEDIA_ENGINE_CONTRACT_VERSION
    source_sha256: str
    shot_range: str
    pts_start_ticks: int
    pts_end_ticks: int
    cast_digest: str
    pack_digest: str
    assets_digest: str
    style_digest: str
    workflow_digest: str
    model_digest: str
    settings_digest: str
    digest: str

    @model_validator(mode="after")
    def _check(self) -> CacheIdentity:
        expected = _digest(_identity_payload(self))
        if expected != self.digest:
            raise ValueError("digest does not match the frozen components")
        return self


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_identity_for(request: MediaEngineRequest) -> CacheIdentity:
    """Derive the cache identity from a frozen request.  Pure and deterministic."""

    cast_payload = [
        {
            "role": b.role,
            "character_id": b.character_id,
            "pack_version_id": b.pack_version_id,
            "style_version": b.style_version,
            "references": sorted((r.artifact_id, r.sha256) for r in b.references),
        }
        for b in request.cast
    ]
    assets_payload = sorted(
        (r.artifact_id, r.sha256) for b in request.cast for r in b.references
    )
    pack_payload = sorted(
        (b.role, b.character_id, b.pack_version_id) for b in request.cast
    )
    style_payload = sorted(
        (b.role, b.style_version) for b in request.cast if b.style_version
    )
    components = {
        "identity_version": MEDIA_ENGINE_CONTRACT_VERSION,
        "source_sha256": request.source.source_sha256,
        "shot_range": request.source.shot_range.key(),
        "pts_start_ticks": request.source.pts_start_ticks,
        "pts_end_ticks": request.source.pts_end_ticks,
        "cast_digest": _digest(cast_payload),
        "pack_digest": _digest(pack_payload),
        "assets_digest": _digest(assets_payload),
        "style_digest": _digest(style_payload),
        "workflow_digest": _digest(
            {
                "workflow_id": request.pins.workflow_id,
                "workflow_version": request.pins.workflow_version,
                "workflow_hash": request.pins.workflow_hash,
                "config_hash": request.pins.config_hash,
                "nodes": sorted(
                    (n.node_id, n.node_class, n.config_hash) for n in request.pins.nodes
                ),
            }
        ),
        "model_digest": _digest(
            {
                "model_id": request.pins.model.model_id,
                "revision": request.pins.model.revision,
                "file_sha256": request.pins.model.file_sha256,
                "precision": request.pins.model.precision,
                "seed": request.pins.seed,
            }
        ),
        "settings_digest": _digest(
            {
                "stage": request.stage,
                "capability": request.capability.value,
                "width": request.output.width,
                "height": request.output.height,
                "fps": request.output.timebase,
                "frame_count": request.output.frame_count,
                "container": request.output.container,
                "video_codec": request.output.video_codec,
                "audio_mode": request.output.audio.mode,
            }
        ),
    }
    digest = _digest(_identity_payload(components))
    return CacheIdentity(digest=digest, **components)


class CacheEntry(BaseModel):
    """A cached shot range plus the role bindings it was produced with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(min_length=1)
    identity: CacheIdentity
    shot_range: ShotRange
    roles: tuple[str, ...] = ()
    style_versions: tuple[tuple[str, str], ...] = ()

    def uses_role(self, role: str) -> bool:
        return role in self.roles


class ReferenceChange(BaseModel):
    """A change to one reference fact for one role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    new_value: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> ReferenceChange:
        if self.kind not in (
            "character_id",
            "pack_version",
            "reference_artifact",
            "style_version",
        ):
            raise ValueError(
                "kind must be character_id|pack_version|reference_artifact|style_version"
            )
        return self


class InvalidationReport(BaseModel):
    """A reference change invalidates the AFFECTED shots and nothing else."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    change: ReferenceChange
    invalidated_entry_ids: tuple[str, ...]
    invalidated_ranges: tuple[str, ...]
    unaffected_entry_ids: tuple[str, ...]

    @property
    def invalidated_count(self) -> int:
        return len(self.invalidated_entry_ids)


def invalidate_for_reference_change(
    entries: tuple[CacheEntry, ...] | list[CacheEntry], change: ReferenceChange
) -> InvalidationReport:
    """Compute the cache invalidation set for a reference change."""

    invalidated: list[CacheEntry] = []
    unaffected: list[str] = []
    for entry in entries:
        hit = entry.uses_role(change.role)
        if not hit and change.kind == "style_version":
            # A style bump only touches entries pinned to a DIFFERENT style.
            for role, version in entry.style_versions:
                if role == change.role and version != change.new_value:
                    hit = True
                    break
        if hit:
            invalidated.append(entry)
        else:
            unaffected.append(entry.entry_id)
    return InvalidationReport(
        change=change,
        invalidated_entry_ids=tuple(e.entry_id for e in invalidated),
        invalidated_ranges=tuple(e.shot_range.key() for e in invalidated),
        unaffected_entry_ids=tuple(unaffected),
    )


# ── result facts ──────────────────────────────────────────────────────────────


class ManagedArtifact(BaseModel):
    """An artifact the backend owns.  Store-relative path, never absolute."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    store_relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    publishable: bool = False

    @model_validator(mode="after")
    def _check(self) -> ManagedArtifact:
        if self.kind not in ARTIFACT_KINDS:
            raise ValueError(f"kind must be one of {ARTIFACT_KINDS}")
        if self.publishable and self.kind not in PUBLISHABLE_ARTIFACT_KINDS:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED,
                f"artifact {self.artifact_id} is a {self.kind} intermediate and can "
                "never be publishable",
            )
        if self.store_relative_path.startswith(("/", "\\")) or ":" in self.store_relative_path:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifact paths are store-relative; got {self.store_relative_path!r}",
            )
        if ".." in self.store_relative_path.replace("\\", "/").split("/"):
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifact path escapes the store: {self.store_relative_path!r}",
            )
        return self


class DecodedMap(BaseModel):
    """Decoded frame map: output frame index -> source frame index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decoded_frames: int = Field(gt=0)
    first_pts_ticks: int = Field(ge=0)
    timebase: str = Field(min_length=3)
    mapping: tuple[int, ...]

    @model_validator(mode="after")
    def _check(self) -> DecodedMap:
        if len(self.mapping) != self.decoded_frames:
            raise ValueError("mapping length must equal decoded_frames")
        if any(i < 0 for i in self.mapping):
            raise ValueError("mapping indices must be >= 0")
        return self


class MediaEngineState(str, Enum):
    """Distinct lifecycle states.  Never collapsed into a boolean."""

    GENERATED = "generated"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    PUBLISHED = "published"


STATE_ORDER: tuple[MediaEngineState, ...] = (
    MediaEngineState.GENERATED,
    MediaEngineState.VALIDATED,
    MediaEngineState.REVIEWED,
    MediaEngineState.ACCEPTED,
    MediaEngineState.PUBLISHED,
)

#: A publication without acceptance is not a state this engine can express.
STATE_TRANSITION_TABLE: dict[MediaEngineState, tuple[MediaEngineState, ...]] = {
    MediaEngineState.GENERATED: (
        MediaEngineState.VALIDATED,
        MediaEngineState.REVIEWED,
        MediaEngineState.ACCEPTED,
    ),
    MediaEngineState.VALIDATED: (
        MediaEngineState.REVIEWED,
        MediaEngineState.ACCEPTED,
    ),
    MediaEngineState.REVIEWED: (MediaEngineState.ACCEPTED,),
    MediaEngineState.ACCEPTED: (MediaEngineState.PUBLISHED,),
    MediaEngineState.PUBLISHED: (),
}


class StateTransition(BaseModel):
    """A requested state transition, checked against the frozen table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_state: MediaEngineState
    to_state: MediaEngineState

    @model_validator(mode="after")
    def _check(self) -> StateTransition:
        allowed = STATE_TRANSITION_TABLE[self.from_state]
        if self.to_state not in allowed:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.STATE_TRANSITION_REFUSED,
                f"{self.from_state.value} -> {self.to_state.value} is not allowed "
                f"(allowed: {[s.value for s in allowed] or 'none'})",
            )
        return self


class MediaEngineFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False


class MediaEngineCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    at_utc: str = Field(min_length=1)


class MediaEngineResult(BaseModel):
    """The result DTO.  Pins + artifacts + decoded map + typed terminal state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_id: str = Field(min_length=1)
    server_epoch: str = Field(min_length=1)
    owner_session: str = Field(min_length=1)
    lease_id: str | None = None
    capability: MediaCapability
    identity: CacheIdentity
    pins: WorkflowPins
    artifacts: tuple[ManagedArtifact, ...]
    decoded: DecodedMap
    audio: AudioHandoff
    state: MediaEngineState = MediaEngineState.GENERATED
    failure: MediaEngineFailure | None = None
    cancel: MediaEngineCancel | None = None

    @model_validator(mode="after")
    def _check(self) -> MediaEngineResult:
        if self.state is MediaEngineState.PUBLISHED:
            if not any(a.publishable for a in self.artifacts):
                raise ValueError("published result requires a publishable artifact")
            if self.failure is not None or self.cancel is not None:
                raise ValueError("published result cannot carry failure/cancel")
        if self.failure is not None and self.cancel is not None:
            raise ValueError("result is either failed or cancelled, not both")
        if self.audio.mode == "source_remux" and self.audio.source_artifact_id is None:
            raise ValueError("source_remux handoff requires source_artifact_id")
        return self


def assert_publishable_set(
    artifacts: tuple[ManagedArtifact, ...] | list[ManagedArtifact],
    *,
    publishable_types: tuple[str, ...] = ("output",),
) -> tuple[ManagedArtifact, ...]:
    """The publication gate for a result's artifacts.

    Only managed artifacts the backend flagged publishable may be published, and
    the allow-list a caller passes may only NARROW the server-owned default —
    never widen it.  Publication is fail-closed: no publishable artifact, or a
    kind outside the allow-list, is a typed refusal, never an empty success.
    """

    if not set(publishable_types) <= set(SERVER_PUBLISHABLE_TYPES):
        raise ValueError(
            f"publishable_types may only narrow {SERVER_PUBLISHABLE_TYPES}; "
            f"got {publishable_types}"
        )
    selected = tuple(a for a in artifacts if a.publishable)
    if not selected:
        raise MediaEngineRefusal(
            MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED,
            "no managed publishable artifact to publish",
        )
    for artifact in selected:
        if artifact.kind not in PUBLISHABLE_ARTIFACT_KINDS:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.ARTIFACT_NOT_MANAGED,
                f"artifact {artifact.artifact_id} ({artifact.kind}) is not publishable",
            )
    return selected


# ── replay ────────────────────────────────────────────────────────────────────


class ReplayAction(str, Enum):
    """The ONLY two outcomes of an unresolved replay.  There is no 'post'."""

    RE_ATTACH = "re_attach"
    REFUSE = "refuse"


class InflightReservation(BaseModel):
    """Durable reservation for an attempt.  Written BEFORE the upstream POST."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    owner_session: str = Field(min_length=1)
    #: outstanding | inflight | acked | ambiguous — mirrors the COMFY round.
    submit_state: str
    workflow_digest: str = Field(min_length=8)
    input_digest: str = Field(min_length=8)
    prompt_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> InflightReservation:
        if self.submit_state not in ("outstanding", "inflight", "acked", "ambiguous"):
            raise ValueError("submit_state must be outstanding|inflight|acked|ambiguous")
        if self.submit_state == "acked" and not self.prompt_id:
            raise ValueError("acked reservation requires prompt_id")
        if self.submit_state in ("outstanding", "inflight") and self.prompt_id:
            raise ValueError("un-acked reservation must not carry a prompt_id")
        return self


class ReplayDecision(BaseModel):
    """Sealed decision.  ``issues_post`` is a constant False."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ReplayAction
    reservation: InflightReservation
    reason_code: str = Field(min_length=1)
    #: Constant.  Present so a reviewer can assert it, not infer it.
    issues_post: bool = False

    @model_validator(mode="after")
    def _check(self) -> ReplayDecision:
        if self.issues_post:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.REPLAY_REFUSED,
                "a replay must never issue a second POST",
            )
        return self


def resolve_replay(
    reservation: InflightReservation,
    *,
    requester_session: str,
    identity_matches: bool,
) -> ReplayDecision:
    """Resolve an unresolved replay by re-attaching or refusing.

    Re-attach is only possible when the reservation is durable, its identity
    (attempt/stage/workflow digest/input digest) matches the caller's, and the
    upstream prompt is already acked.  Everything else refuses — a new POST is
    never an option, which is what stops a replay from duplicating work.
    """

    if reservation.submit_state == "ambiguous":
        return ReplayDecision(
            action=ReplayAction.REFUSE,
            reservation=reservation,
            reason_code="unresolved_ambiguous_reservation",
        )
    if not identity_matches:
        return ReplayDecision(
            action=ReplayAction.REFUSE,
            reservation=reservation,
            reason_code="reservation_identity_mismatch",
        )
    if reservation.submit_state == "acked" and reservation.prompt_id:
        return ReplayDecision(
            action=ReplayAction.RE_ATTACH,
            reservation=reservation,
            reason_code="re_attach_acked_prompt",
        )
    if reservation.owner_session != requester_session:
        return ReplayDecision(
            action=ReplayAction.REFUSE,
            reservation=reservation,
            reason_code="reservation_owned_by_other_session",
        )
    return ReplayDecision(
        action=ReplayAction.REFUSE,
        reservation=reservation,
        reason_code="reservation_not_acked_no_second_submit",
    )


# ── model registry ────────────────────────────────────────────────────────────


class HardwareProfile(BaseModel):
    """MEASURED hardware profile for a model on a concrete device."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    device: str = Field(min_length=1)
    vram_bytes: int = Field(ge=0)
    measured_seconds_per_output_second: float | None = None
    measured_at_utc: str | None = None
    evidence_source: str = "declared"

    @model_validator(mode="after")
    def _check(self) -> HardwareProfile:
        if self.evidence_source not in ("measured_live", "probed_config", "declared"):
            raise ValueError(
                "evidence_source must be measured_live|probed_config|declared"
            )
        if self.evidence_source == "measured_live" and (
            self.measured_seconds_per_output_second is None or not self.measured_at_utc
        ):
            raise ValueError(
                "measured_live profile requires a measurement and a timestamp"
            )
        return self


class ModelRegistryEntry(BaseModel):
    """One registry row: identity, capability, hardware, availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    file_sha256: str = Field(min_length=64, max_length=64)
    precision: str = Field(min_length=1)
    capabilities: tuple[MediaCapability, ...]
    hardware: tuple[HardwareProfile, ...]
    #: Release date of the MODEL (upstream publication).
    release_date: date
    #: Repo modification date of the local checked-in entry — a DIFFERENT fact.
    repo_modified_date: date | None = None
    license_id: str = Field(min_length=1)
    available: bool
    unavailable_reason_code: str | None = None
    download_requires_operator_action: bool = True

    @model_validator(mode="after")
    def _check(self) -> ModelRegistryEntry:
        if not self.capabilities:
            raise ValueError("a registry entry must declare at least one capability")
        if self.available and self.unavailable_reason_code is not None:
            raise ValueError("available entry must not carry a reason code")
        if not self.available and not self.unavailable_reason_code:
            raise ValueError("unavailable entry requires an explicit reason code")
        if not self.download_requires_operator_action:
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.AUTO_DOWNLOAD_REFUSED,
                f"{self.model_id} would allow a non-operator download path",
            )
        return self

    @property
    def dates_are_distinct_facts(self) -> bool:
        return self.repo_modified_date is None or self.repo_modified_date != self.release_date


class ModelRegistry(BaseModel):
    """The registry view.  Lookup only — provisioning is out of band."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[ModelRegistryEntry, ...]

    def for_capability(self, capability: MediaCapability) -> tuple[ModelRegistryEntry, ...]:
        return tuple(e for e in self.entries if capability in e.capabilities)

    def require_available(self, role: str) -> ModelRegistryEntry:
        for entry in self.entries:
            if entry.role == role:
                if not entry.available:
                    raise MediaEngineRefusal(
                        MediaEngineRefusalCode.MODEL_UNAVAILABLE,
                        f"role {role!r} ({entry.model_id}) is unavailable: "
                        f"{entry.unavailable_reason_code}",
                    )
                return entry
        raise MediaEngineRefusal(
            MediaEngineRefusalCode.MODEL_UNAVAILABLE,
            f"role {role!r} is not in the model registry",
        )

    def request_download(self, *, role: str, origin: str) -> None:
        """A UI click can NEVER trigger a download.  Always refuses."""

        if origin == "ui_click":
            raise MediaEngineRefusal(
                MediaEngineRefusalCode.AUTO_DOWNLOAD_REFUSED,
                f"download of {role!r} refused: no automatic download from a UI click",
            )
        raise MediaEngineRefusal(
            MediaEngineRefusalCode.AUTO_DOWNLOAD_REFUSED,
            "downloads are out-of-band operator provisioning, never an API call",
        )


# ── shared GPU lease / single job store ───────────────────────────────────────


class GpuLeaseRequest(BaseModel):
    """A request for the ONE shared GPU lease used by image, video and E01."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1)
    owner_session: str = Field(min_length=1)
    capability: MediaCapability
    budget: ResourceBudget
    priority: int = 0


class GpuLeaseGrant(BaseModel):
    """The single holder of the GPU lease at a point in time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    owner_session: str = Field(min_length=1)
    resource_class: str = Field(min_length=1)
    expires_at_utc: str = Field(
        min_length=20, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    )

    def expired_at(self, now_utc: str) -> bool:
        """Whether the lease has expired at ``now_utc``.

        Expiry itself is owned by E01 (``app/persistence/jobs.py`` lease
        fencing); this view never re-implements it.  The comparison is a plain
        ISO-8601 UTC string compare — lexicographic for the frozen
        ``YYYY-MM-DDTHH:MM:SSZ`` shape — so no clock is read and the answer is
        deterministic for a given pair of strings.
        """

        return now_utc >= self.expires_at_utc


class GpuLeaseView(BaseModel):
    """Read-only view over the E01 lease.  NOT a second concurrency engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_store: str = E01_JOB_STORE
    concurrency_engine: str = E01_JOB_STORE
    holder: GpuLeaseGrant | None = None
    queue: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> GpuLeaseView:
        assert_shared_stack(
            job_store=self.job_store,
            concurrency_engine=self.concurrency_engine,
        )
        if self.holder is not None and self.holder.job_id in self.queue:
            raise ValueError("a job cannot be both the holder and queued")
        if len(self.queue) != len(set(self.queue)):
            raise ValueError("a job may hold at most one queue position")
        return self

    def decide(self, request: GpuLeaseRequest, *, lease_id: str, expires_at_utc: str) -> GpuLeaseSource:
        """Grant only when the single lease is free; otherwise queue (no bypass)."""

        if self.holder is not None and self.holder.job_id != request.job_id:
            return GpuLeaseSource(
                granted=False,
                queue=sorted((*self.queue, request.job_id)),
                view=self,
            )
        return GpuLeaseSource(
            granted=True,
            queue=self.queue,
            view=GpuLeaseView(
                job_store=self.job_store,
                concurrency_engine=self.concurrency_engine,
                holder=GpuLeaseGrant(
                    lease_id=lease_id,
                    job_id=request.job_id,
                    owner_session=request.owner_session,
                    resource_class=request.budget.resource_class,
                    expires_at_utc=expires_at_utc,
                ),
                queue=tuple(j for j in self.queue if j != request.job_id),
            ),
        )


class GpuLeaseSource(BaseModel):
    """Outcome of a lease decision, carrying the resulting view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    granted: bool
    queue: tuple[str, ...]
    view: GpuLeaseView


def assert_shared_stack(*, job_store: str, concurrency_engine: str) -> None:
    """Refuse a second job database or a competing concurrency engine."""

    if job_store != E01_JOB_STORE:
        raise MediaEngineRefusal(
            MediaEngineRefusalCode.SECOND_JOB_STORE_REFUSED,
            f"the only durable job store is {E01_JOB_STORE!r}; got {job_store!r}",
        )
    if concurrency_engine != E01_JOB_STORE:
        raise MediaEngineRefusal(
            MediaEngineRefusalCode.COMPETING_CONCURRENCY_ENGINE_REFUSED,
            f"the only concurrency engine is {E01_JOB_STORE!r}; got {concurrency_engine!r}",
        )

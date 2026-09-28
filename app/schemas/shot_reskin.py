"""Shot reskin delivery contract V1 — shot plan, role/reference mapping,
interaction refs, source-vs-output evidence binding and the ORTHOGONAL
execution-backend axis (MF-END-01).

This module is PURE: pydantic + stdlib only.  It owns no database, no queue and
no renderer; it never executes anything.  It is the shot-level contract the app
builds BEFORE an engine call and records AFTER one.

Composition with the ACCEPTED media-engine contract (MF-TOOL-CONTRACT NR05/NR06,
git blob ``9e4586a1b2cbc8aeb6d35a75c038327533b81b2a`` of
``app/schemas/media_engine.py`` at ``f0b918b``) is by REUSE, never by
redefinition (micro-job MF-END-01.1):

* the engine-facing projections below emit EXACTLY the field sets of
  ``MediaEngineRequest`` (``capability``/``source``/``cast``/``pins``/``output``/
  ``budget``) and :func:`to_engine_request` constructs that DTO when it is
  present in the tree (the accepted transport is an INT job; until it lands the
  module refuses with a typed code instead of degrading);
* the shared vocabulary (capabilities, artifact kinds, publishable kinds, server
  output classification) is PINNED here to the accepted values and cross-checked
  against the DTO by test when the module is importable;
* NR05/NR06 bytes are never modified by this contract.

Contract laws enforced here (never by convention):

1. Intervals are half-open ``[start_frame, end_frame)`` on the decoded index
   space (the product convention); the accepted DTO's ``ShotRange`` is
   INCLUSIVE, so the boundary converts explicitly (``end - 1``) and refuses a
   zero-length or negative span with a typed code.
2. Frame rate and stream time_base are DIFFERENT quantities, on the source and
   on the output; ``timebase`` NEVER returns the frame rate.
3. Roles are declared by the shot's elements.  An interaction, reference set,
   evidence fact or observation that names an undeclared role is refused
   (foreign role).
4. Backend-managed artifacts are the authority: a client path is refused with a
   typed code, and artifact paths are store-relative only.
5. Source facts and output observations are DIFFERENT evidence domains.  A
   source fact is measured on the locked source artifact; an output observation
   is measured on the rendered artifact; an output binding whose artifact IS
   the source (byte-identical sha) is refused.
6. The execution backend is orthogonal to the legacy renderer-route taxonomy:
   ``comfy_shot_engine`` is not a route alias, a legacy route value can never be
   the backend, and a legacy-backend record carries no engine input/output.
7. A model pin handed to the engine must carry a FULL-file sha256 (the accepted
   DTO requires 64 hex); a head-hash-only pin refuses with a typed code.

Frozen examples (``FROZEN_EXAMPLES``) carry the measured PROOF_GATE values of the
BOOK unit (MF-V1-VIDEO14B Phase A) so later tasks bind to real hashes instead of
invented ones; ``docs/contracts/shot-reskin-delivery-v1.md`` embeds the same
JSON and a test proves doc and code parse equal.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ENGINE_ARTIFACT_KINDS",
    "ENGINE_CAPABILITY_PINS",
    "ENGINE_IDENTITY_FIELDS",
    "ENGINE_PUBLISHABLE_ARTIFACT_KINDS",
    "ENGINE_REFERENCE_MINIMA_PIN",
    "ENGINE_REQUEST_TOP_LEVEL_FIELDS",
    "ENGINE_SERVER_OUTPUT_TYPES",
    "ENGINE_SERVER_PUBLISHABLE_TYPES",
    "FROZEN_EXAMPLES",
    "FROZEN_REQUEST_PAYLOAD_SHA256",
    "LEGACY_RENDERER_ROUTES_PIN",
    "MEDIA_ENGINE_ACCEPTED_BLOB_PIN",
    "MEDIA_ENGINE_CONTRACT_VERSION_PIN",
    "MEDIA_ENGINE_DTO_PRESENT",
    "SCHEMA_VERSION",
    "ArtifactRef",
    "ContentHash",
    "ElementUnit",
    "EngineAudioHandoff",
    "EngineDecodedFacts",
    "EngineInputBinding",
    "EngineModelBinding",
    "EngineNodeBinding",
    "EngineOutputBinding",
    "EngineOutputContract",
    "EngineRequestIdentity",
    "EngineResourceBudget",
    "EngineSourceLock",
    "EngineWorkflowPin",
    "ExecutionBackend",
    "InteractionRef",
    "OutputObservation",
    "OutputObservationBinding",
    "ReferenceItem",
    "ReferenceManifest",
    "RoleCastBinding",
    "RoleReferenceSet",
    "ShotEngineError",
    "ShotExecutionRecord",
    "ShotPlan",
    "ShotReskinRefusal",
    "ShotReskinRefusalCode",
    "SourceEvidenceFact",
    "SourceSpan",
    "TimebaseFacts",
    "engine_request_payload",
    "media_engine_module",
    "payload_sha256",
    "to_engine_request",
]

# ── pinned contract identity ──────────────────────────────────────────────────

#: This contract's own version.
SCHEMA_VERSION = "mf.shot_reskin.contract.v1"
#: The accepted media-engine contract this module composes with.
MEDIA_ENGINE_CONTRACT_VERSION_PIN = "mf.media_engine.contract.v1"
#: The accepted NR05/NR06 bytes compiled into f0b918b (never modified here).
MEDIA_ENGINE_ACCEPTED_BLOB_PIN = "9e4586a1b2cbc8aeb6d35a75c038327533b81b2a"
#: The legacy renderer-route taxonomy (app/persistence/models.py::RENDERER_ROUTES)
#: as measured at PRODUCT 2c405f3e.  The execution backend is ORTHOGONAL to it.
LEGACY_RENDERER_ROUTES_PIN = (
    "pose_swap",
    "sprite_affine",
    "mesh_warp",
    "part_rig",
    "controlled_redraw",
)
#: Accepted capability vocabulary (app.schemas.media_engine.MediaCapability).
ENGINE_CAPABILITY_PINS = (
    "image_edit_multi_reference",
    "source_video_motion_transfer",
    "video_edit_controlled",
    "text_to_video",
)
#: Accepted artifact kinds (media_engine.ARTIFACT_KINDS).
ENGINE_ARTIFACT_KINDS = ("image", "video", "audio", "pose_sheet", "mask", "graph")
#: Kinds that may ever be published (media_engine.PUBLISHABLE_ARTIFACT_KINDS).
ENGINE_PUBLISHABLE_ARTIFACT_KINDS = ("image", "video", "audio")
#: Server-owned node-output classification vocabulary (media_engine.SERVER_OUTPUT_TYPES).
ENGINE_SERVER_OUTPUT_TYPES = ("output", "preview", "intermediate", "temp", "input", "unclassified")
#: Only these may ever leave the engine (media_engine.SERVER_PUBLISHABLE_TYPES).
ENGINE_SERVER_PUBLISHABLE_TYPES = ("output",)

#: Field sets of the accepted DTO that the payload builder must match EXACTLY.
ENGINE_REQUEST_TOP_LEVEL_FIELDS = (
    "workspace_id",
    "project_id",
    "series_id",
    "video_id",
    "stage",
    "attempt_id",
    "job_id",
    "capability",
    "source",
    "cast",
    "pins",
    "output",
    "budget",
)
ENGINE_SOURCE_LOCK_FIELDS = (
    "source_artifact_id",
    "source_sha256",
    "shot_range",
    "pts_start_ticks",
    "pts_end_ticks",
    "fps_num",
    "fps_den",
    "stream_timebase_num",
    "stream_timebase_den",
    "decoded_frame_count",
)
ENGINE_IDENTITY_FIELDS = (
    "workspace_id",
    "project_id",
    "series_id",
    "video_id",
    "stage",
    "attempt_id",
    "job_id",
)
ENGINE_CAST_FIELDS = ("role", "character_id", "pack_version_id", "references", "style_version")
ENGINE_REFERENCE_FIELDS = ("artifact_id", "sha256")
ENGINE_WORKFLOW_PIN_FIELDS = (
    "workflow_id",
    "workflow_version",
    "workflow_hash",
    "model",
    "nodes",
    "config_hash",
    "seed",
)
ENGINE_MODEL_PIN_FIELDS = ("model_id", "revision", "file_sha256", "precision")
ENGINE_NODE_PIN_FIELDS = ("node_id", "node_class", "config_hash")
ENGINE_OUTPUT_CONTRACT_FIELDS = (
    "width",
    "height",
    "fps_num",
    "fps_den",
    "frame_count",
    "container",
    "video_codec",
    "audio",
    "stream_timebase_num",
    "stream_timebase_den",
    "publishable_types",
)
ENGINE_AUDIO_FIELDS = ("mode", "source_artifact_id", "sample_rate", "channels", "codec")
ENGINE_BUDGET_FIELDS = ("resource_class", "max_wall_seconds", "max_vram_bytes", "max_output_bytes")
#: Mirrors media_engine.CAPABILITY_REFERENCE_REQUIREMENTS: (min_roles, min_refs_per_role).
ENGINE_REFERENCE_MINIMA_PIN: dict[str, tuple[int, int]] = {
    "source_video_motion_transfer": (1, 1),
    "image_edit_multi_reference": (1, 2),
    "video_edit_controlled": (0, 0),
    "text_to_video": (0, 0),
}


def _canonical_json(payload: Any) -> str:
    """Canonical JSON used for every digest in this module."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(payload: Any) -> str:
    """sha256 of the canonical JSON of ``payload`` (hex, lowercase)."""
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


# ── refusals ──────────────────────────────────────────────────────────────────


class ShotReskinRefusalCode(str, Enum):
    """Typed refusal taxonomy for the shot contract.  One code per refusal."""

    SCHEMA_VERSION_UNSUPPORTED = "schema_version_unsupported"
    CLIENT_ARTIFACT_PATH_REFUSED = "client_artifact_path_refused"
    FOREIGN_ROLE_REFUSED = "foreign_role_refused"
    DUPLICATE_ROLE_REFUSED = "duplicate_role_refused"
    INVALID_INTERVAL_REFUSED = "invalid_interval_refused"
    TIMEBASE_INVALID = "timebase_invalid"
    HASH_FORMAT_INVALID = "hash_format_invalid"
    FULL_FILE_HASH_REQUIRED = "full_file_hash_required"
    EVIDENCE_DOMAIN_MISMATCH = "evidence_domain_mismatch"
    OUTPUT_BINDS_SOURCE_ARTIFACT = "output_binds_source_artifact"
    UNKNOWN_EVIDENCE_REFUSED = "unknown_evidence_refused"
    LEGACY_ROUTE_AS_BACKEND_REFUSED = "legacy_route_as_backend_refused"
    BACKEND_UNKNOWN_REFUSED = "backend_unknown_refused"
    BACKEND_BINDING_INVALID = "backend_binding_invalid"
    ENGINE_CAPABILITY_REQUIRED = "engine_capability_required"
    ENGINE_CAPABILITY_UNKNOWN = "engine_capability_unknown"
    ENGINE_KIND_UNKNOWN = "engine_kind_unknown"
    CAST_REFERENCE_REQUIRED = "cast_reference_required"
    ARTIFACT_NOT_PUBLISHABLE = "artifact_not_publishable"
    RECORD_INCONSISTENT = "record_inconsistent"
    ENGINE_RESULT_INCOMPLETE = "engine_result_incomplete"
    MEDIA_ENGINE_DTO_UNAVAILABLE = "media_engine_dto_unavailable"


#: The refusal name mirrors the accepted DTO's ``MediaEngineRefusal`` on purpose
#: (one taxonomy across the two contracts), so N818 is waived here.
class ShotReskinRefusal(Exception):  # noqa: N818
    """Fail-closed refusal.  Never swallowed into a generic error."""

    def __init__(self, code: ShotReskinRefusalCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}


def _refuse(code: ShotReskinRefusalCode, detail: str) -> None:
    raise ShotReskinRefusal(code, detail)


class _StrictModel(BaseModel):
    """extra=forbid + frozen: a contract type, never a mutable bag."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _is_lower_hex(value: str) -> bool:
    return bool(value) and all(c in "0123456789abcdef" for c in value)


class ExecutionBackend(str, Enum):
    """The execution backend axis — ORTHOGONAL to the legacy renderer routes."""

    LEGACY_RENDERER = "legacy_renderer"
    COMFY_SHOT_ENGINE = "comfy_shot_engine"


# ── shared primitives ─────────────────────────────────────────────────────────


class ContentHash(_StrictModel):
    """A sha256 digest with an explicit SCOPE.

    ``full_file`` digests are 64 hex and may be handed to the engine pin.
    ``head_1mib`` digests are the 16-hex head-hash the P0 inventory records and
    are PROVENANCE ONLY: a model pin needs the full-file digest, so a head-hash
    pin refuses with ``full_file_hash_required`` at the boundary instead of
    smuggling a short digest into the accepted DTO (which requires 64 hex).
    """

    algorithm: Literal["sha256"] = "sha256"
    scope: Literal["full_file", "head_1mib"]
    value: str

    @model_validator(mode="after")
    def _check(self) -> ContentHash:
        if not _is_lower_hex(self.value):
            raise ValueError("hash values must be lowercase hex")
        if self.scope == "full_file" and len(self.value) != 64:
            _refuse(
                ShotReskinRefusalCode.FULL_FILE_HASH_REQUIRED,
                f"a full_file digest is 64 hex chars; got {len(self.value)} "
                f"({self.value[:16]}…) — an engine pin may not carry a head-hash",
            )
        if self.scope == "head_1mib" and len(self.value) != 16:
            raise ValueError("a head_1mib digest is exactly 16 hex chars")
        return self


class ArtifactRef(_StrictModel):
    """A backend-managed artifact reference (ids + digests, never paths)."""

    artifact_id: str = Field(min_length=1)
    kind: Literal["image", "video", "audio", "pose_sheet", "mask", "graph"]
    sha256: str = Field(min_length=64, max_length=64)
    store_relative_path: str = Field(min_length=1)
    size_bytes: int | None = Field(default=None, ge=0)
    #: Present only so a client-supplied path can be REFUSED with a typed code.
    path: str | None = None

    @model_validator(mode="after")
    def _check(self) -> ArtifactRef:
        if not _is_lower_hex(self.sha256):
            raise ValueError("artifact sha256 must be lowercase hex")
        if self.path:
            _refuse(
                ShotReskinRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifacts are addressed by managed artifact_id; client path {self.path!r} "
                "is refused",
            )
        if self.store_relative_path.startswith(("/", "\\")) or ":" in self.store_relative_path:
            _refuse(
                ShotReskinRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifact paths are store-relative; got {self.store_relative_path!r}",
            )
        if ".." in self.store_relative_path.replace("\\", "/").split("/"):
            _refuse(
                ShotReskinRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifact path escapes the store: {self.store_relative_path!r}",
            )
        return self


class SourceSpan(_StrictModel):
    """Half-open interval ``[start_frame, end_frame_exclusive)`` on the decoded
    index space (the product convention; the accepted DTO's ``ShotRange`` is
    inclusive and is converted explicitly at the boundary).

    Every invalid interval refuses with ONE typed code even for negative or
    non-positive bounds, so no caller sees a generic pydantic error for the
    class of input the acceptance names.
    """

    start_frame: int
    end_frame_exclusive: int

    @model_validator(mode="after")
    def _check(self) -> SourceSpan:
        if self.start_frame < 0:
            _refuse(
                ShotReskinRefusalCode.INVALID_INTERVAL_REFUSED,
                f"start_frame must be >= 0; got {self.start_frame}",
            )
        if self.end_frame_exclusive <= self.start_frame:
            _refuse(
                ShotReskinRefusalCode.INVALID_INTERVAL_REFUSED,
                f"interval [{self.start_frame}, {self.end_frame_exclusive}) is empty or "
                "negative: end_frame_exclusive must be > start_frame",
            )
        return self

    @property
    def frame_count(self) -> int:
        return self.end_frame_exclusive - self.start_frame

    def key(self) -> str:
        return f"[{self.start_frame},{self.end_frame_exclusive})"

    def to_engine_shot_range(self) -> dict[str, int]:
        """Inclusive ``ShotRange`` kwargs for the accepted DTO (end - 1)."""
        return {"start_frame": self.start_frame, "end_frame": self.end_frame_exclusive - 1}

    @classmethod
    def from_engine_shot_range(cls, start_frame: int, end_frame: int) -> SourceSpan:
        """Convert the accepted DTO's INCLUSIVE range back to half-open."""
        return cls(start_frame=start_frame, end_frame_exclusive=end_frame + 1)

    def intersects(self, other: SourceSpan) -> bool:
        return (
            self.start_frame < other.end_frame_exclusive
            and other.start_frame < self.end_frame_exclusive
        )

    def contains(self, other: SourceSpan) -> bool:
        return (
            self.start_frame <= other.start_frame
            and other.end_frame_exclusive <= self.end_frame_exclusive
        )


class TimebaseFacts(_StrictModel):
    """The timing facts of one artifact — frame rate and stream time_base are
    DIFFERENT quantities and are never substituted for each other."""

    fps_num: int = Field(gt=0)
    fps_den: int = Field(gt=0)
    #: Container rational time_base (seconds per tick), declared as a pair or not at all.
    stream_timebase_num: int | None = Field(default=None, gt=0)
    stream_timebase_den: int | None = Field(default=None, gt=0)
    #: Display-order PTS span measured on the packet stream (min/max), in ticks.
    pts_start_ticks: int = Field(ge=0)
    pts_end_ticks: int = Field(ge=0)
    #: Decoded frame count, when the backend has already decoded the span.
    decoded_frame_count: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check(self) -> TimebaseFacts:
        if (self.stream_timebase_num is None) != (self.stream_timebase_den is None):
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                "stream time_base must be a complete rational pair "
                "(stream_timebase_num AND stream_timebase_den), never half of one",
            )
        if self.pts_end_ticks < self.pts_start_ticks:
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                f"PTS must be ordered (start={self.pts_start_ticks}, end={self.pts_end_ticks})",
            )
        return self

    @property
    def fps(self) -> str:
        """The frame rate as a rational — NOT the time_base."""
        return f"{self.fps_num}/{self.fps_den}"

    @property
    def stream_timebase(self) -> str | None:
        """The stream's rational time_base, or ``None`` when not probed."""
        if self.stream_timebase_num is None or self.stream_timebase_den is None:
            return None
        return f"{self.stream_timebase_num}/{self.stream_timebase_den}"

    @property
    def timebase(self) -> str | None:
        """Alias of :attr:`stream_timebase` — NEVER the frame rate."""
        return self.stream_timebase

    @property
    def pts_span_ticks(self) -> int:
        return self.pts_end_ticks - self.pts_start_ticks

    def required_pts_span(self, frame_count: int) -> int | None:
        """Minimum ticks the span must hold for ``frame_count`` frames, when the
        time_base is known.  Mirrors the accepted DTO's NR05.2/NR05.3 laws."""
        timebase = self.stream_timebase
        if timebase is None or frame_count <= 1:
            return None
        ratio_num = (frame_count - 1) * self.fps_den * (self.stream_timebase_den or 0)
        return -(-ratio_num // (self.fps_num * (self.stream_timebase_num or 1)))


# ── scene elements, roles, references, interactions ──────────────────────────


class RoleCastBinding(_StrictModel):
    """role → CharacterID + immutable PackVersion + the reference pixels the
    engine projection carries (accepted ``CastBinding`` shape)."""

    role: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    pack_version_id: str = Field(min_length=1)
    references: tuple[ReferenceItem, ...] = ()
    style_version: str | None = None


class ReferenceItem(_StrictModel):
    """One reference artifact for a role (or prop/background)."""

    key: str = Field(min_length=1)
    artifact: ArtifactRef
    view: Literal["front", "side", "back", "close_up", "three_quarter", "other"] | None = None


class RoleReferenceSet(_StrictModel):
    """The references a role carries into a shot."""

    role: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    pack_version_id: str = Field(min_length=1)
    items: tuple[ReferenceItem, ...] = Field(min_length=1)


class ReferenceManifest(_StrictModel):
    """What the shot must carry: per-role references + style/props/background."""

    style_version: str = Field(min_length=1)
    roles: tuple[RoleReferenceSet, ...] = ()
    props: tuple[ReferenceItem, ...] = ()
    background: ReferenceItem | None = None


class ElementUnit(_StrictModel):
    """One role/prop/background actually present in the shot."""

    role: str = Field(min_length=1)
    kind: Literal["person", "prop", "background", "source_frame"]
    source_track_id: str | None = None
    visible_spans: tuple[SourceSpan, ...] = ()
    occlusion: Literal["visible", "occluded", "out_of_frame", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)


class InteractionRef(_StrictModel):
    """A relation between two declared roles over one or more source intervals."""

    subject_role: str = Field(min_length=1)
    relation: Literal[
        "holds", "gives", "receives", "touches", "occludes", "reads", "sits_behind", "none"
    ]
    object_role: str = Field(min_length=1)
    spans: tuple[SourceSpan, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    state: Literal["measured", "confirmed", "unmeasured"] = "unmeasured"
    confidence: float | None = Field(default=None, ge=0, le=1)


# ── evidence domains (U08/U21) ────────────────────────────────────────────────

EvidenceKind = Literal["presence", "contact", "occlusion", "holder", "camera", "event"]


class SourceEvidenceFact(_StrictModel):
    """A fact about the SOURCE — measured on the locked source artifact."""

    evidence_id: str = Field(min_length=1)
    domain: Literal["source"] = "source"
    subject_role: str = Field(min_length=1)
    kind: EvidenceKind
    span: SourceSpan
    artifact: ArtifactRef
    state: Literal["measured", "confirmed"] = "measured"
    confidence: float | None = Field(default=None, ge=0, le=1)


class OutputObservation(_StrictModel):
    """A fact about the OUTPUT — measured on the rendered artifact."""

    observation_id: str = Field(min_length=1)
    domain: Literal["output"] = "output"
    subject_role: str = Field(min_length=1)
    kind: EvidenceKind
    span: SourceSpan
    frame_space: Literal["output_decoded", "source_aligned"] = "output_decoded"
    artifact: ArtifactRef
    state: Literal["measured", "confirmed"] = "measured"
    confidence: float | None = Field(default=None, ge=0, le=1)


class OutputObservationBinding(_StrictModel):
    """Binds observations to the rendered artifact and PROVES the artifact is
    not the source: a byte-identical output sha is refused."""

    state: Literal["observed", "unmeasured"] = "unmeasured"
    source_artifact: ArtifactRef
    output_artifact: ArtifactRef
    observations: tuple[OutputObservation, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> OutputObservationBinding:
        if self.output_artifact.sha256 == self.source_artifact.sha256:
            _refuse(
                ShotReskinRefusalCode.OUTPUT_BINDS_SOURCE_ARTIFACT,
                f"output artifact {self.output_artifact.artifact_id} is byte-identical to the "
                "locked source: a generated result may never be the source returned as output",
            )
        if self.state == "observed":
            if not self.observations:
                _refuse(
                    ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH,
                    "state=observed requires at least one measured observation",
                )
            for obs in self.observations:
                if obs.artifact.sha256 != self.output_artifact.sha256:
                    _refuse(
                        ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH,
                        f"observation {obs.observation_id} is bound to artifact "
                        f"{obs.artifact.sha256[:16]}… but this binding's output artifact is "
                        f"{self.output_artifact.sha256[:16]}…; output facts are measured on "
                        "the rendered artifact",
                    )
        elif self.observations:
            _refuse(
                ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH,
                "state=unmeasured must not carry observations (UNKNOWN/BLOCKED, never [] that "
                "reads as pass)",
            )
        return self


# ── engine-facing bindings (compose the accepted DTO) ────────────────────────


class EngineRequestIdentity(_StrictModel):
    """Identity fields of the accepted ``MediaEngineRequest``."""

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    series_id: str | None = None
    video_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    job_id: str | None = None

    def to_request_kwargs(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ENGINE_IDENTITY_FIELDS}


class EngineSourceLock(_StrictModel):
    """Source artifact + span + timing — the accepted ``SourceLock`` fields."""

    source_artifact_id: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64)
    span: SourceSpan
    timebase: TimebaseFacts
    decoded_frame_count: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check(self) -> EngineSourceLock:
        if not _is_lower_hex(self.source_sha256):
            raise ValueError("source_sha256 must be lowercase hex")
        frames = self.decoded_frame_count or self.span.frame_count
        if frames > 1 and self.timebase.pts_span_ticks == 0:
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                f"pts span is ZERO but the locked span {self.span.key()} holds {frames} "
                "frames: a multi-frame shot cannot be a point in time",
            )
        required = self.timebase.required_pts_span(frames)
        if required is not None and self.timebase.pts_span_ticks < required:
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                f"pts span {self.timebase.pts_span_ticks} ticks cannot hold {frames} frames "
                f"at fps {self.timebase.fps} and stream time_base "
                f"{self.timebase.stream_timebase}: at least {required} ticks are required",
            )
        if (
            self.decoded_frame_count is not None
            and self.decoded_frame_count != self.span.frame_count
        ):
            _refuse(
                ShotReskinRefusalCode.RECORD_INCONSISTENT,
                f"decoded_frame_count {self.decoded_frame_count} != locked span frame count "
                f"{self.span.frame_count}",
            )
        return self

    def to_source_lock_kwargs(self) -> dict[str, Any]:
        return {
            "source_artifact_id": self.source_artifact_id,
            "source_sha256": self.source_sha256,
            "shot_range": self.span.to_engine_shot_range(),
            "pts_start_ticks": self.timebase.pts_start_ticks,
            "pts_end_ticks": self.timebase.pts_end_ticks,
            "fps_num": self.timebase.fps_num,
            "fps_den": self.timebase.fps_den,
            "stream_timebase_num": self.timebase.stream_timebase_num,
            "stream_timebase_den": self.timebase.stream_timebase_den,
            "decoded_frame_count": self.decoded_frame_count
            if self.decoded_frame_count is not None
            else self.timebase.decoded_frame_count,
        }


class EngineModelBinding(_StrictModel):
    """One pinned model FILE (primary or auxiliary)."""

    model_id: str = Field(min_length=1)
    revision: str | None = None
    file: ContentHash
    precision: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> EngineModelBinding:
        if self.file.scope != "full_file":
            _refuse(
                ShotReskinRefusalCode.FULL_FILE_HASH_REQUIRED,
                f"model {self.model_id} carries a {self.file.scope} digest; an engine model pin "
                "requires the full-file sha256",
            )
        return self


class EngineNodeBinding(_StrictModel):
    """One pinned node (id + class + config hash) — accepted ``NodePin`` shape."""

    node_id: str = Field(min_length=1)
    node_class: str = Field(min_length=1)
    config_hash: str = Field(min_length=8)


class EngineWorkflowPin(_StrictModel):
    """The accepted ``WorkflowPins`` shape (one primary model pin + nodes)."""

    workflow_id: str = Field(min_length=1)
    workflow_version: str = Field(min_length=1)
    workflow_hash: str = Field(min_length=64, max_length=64)
    model: EngineModelBinding
    nodes: tuple[EngineNodeBinding, ...] = ()
    config_hash: str = Field(min_length=8)
    seed: int = Field(ge=0)

    def to_pins_kwargs(self) -> dict[str, Any]:
        model = self.model
        if not model.revision:
            _refuse(
                ShotReskinRefusalCode.RECORD_INCONSISTENT,
                f"model {model.model_id} has no provisioning revision recorded; the accepted "
                "DTO requires revision (min_length=1) — record the revision instead of "
                "inventing one",
            )
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "workflow_hash": self.workflow_hash,
            "model": {
                "model_id": model.model_id,
                "revision": model.revision,
                "file_sha256": model.file.value,
                "precision": model.precision,
            },
            "nodes": [
                {"node_id": n.node_id, "node_class": n.node_class, "config_hash": n.config_hash}
                for n in self.nodes
            ],
            "config_hash": self.config_hash,
            "seed": self.seed,
        }


class EngineAudioHandoff(_StrictModel):
    """Typed audio handoff (accepted ``AudioHandoff`` shape)."""

    mode: Literal["source_remux", "generated", "silent"]
    source_artifact_id: str | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)
    codec: str | None = None

    @model_validator(mode="after")
    def _check(self) -> EngineAudioHandoff:
        if self.mode == "source_remux" and not self.source_artifact_id:
            raise ValueError("source_remux handoff requires source_artifact_id")
        return self


class EngineOutputContract(_StrictModel):
    """Decoded output contract (accepted ``OutputContract`` shape)."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps_num: int = Field(gt=0)
    fps_den: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    container: str = Field(min_length=1)
    video_codec: str = Field(min_length=1)
    audio: EngineAudioHandoff
    stream_timebase_num: int | None = Field(default=None, gt=0)
    stream_timebase_den: int | None = Field(default=None, gt=0)
    publishable_types: tuple[str, ...] = ENGINE_SERVER_PUBLISHABLE_TYPES

    @model_validator(mode="after")
    def _check(self) -> EngineOutputContract:
        if (self.stream_timebase_num is None) != (self.stream_timebase_den is None):
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                "output stream time_base must be a complete rational pair, never half of one",
            )
        if not set(self.publishable_types) <= set(ENGINE_SERVER_PUBLISHABLE_TYPES):
            _refuse(
                ShotReskinRefusalCode.ARTIFACT_NOT_PUBLISHABLE,
                f"publishable_types may only narrow {ENGINE_SERVER_PUBLISHABLE_TYPES}; got "
                f"{self.publishable_types}",
            )
        return self

    def to_output_kwargs(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "frame_count": self.frame_count,
            "container": self.container,
            "video_codec": self.video_codec,
            "audio": {
                "mode": self.audio.mode,
                "source_artifact_id": self.audio.source_artifact_id,
                "sample_rate": self.audio.sample_rate,
                "channels": self.audio.channels,
                "codec": self.audio.codec,
            },
            "stream_timebase_num": self.stream_timebase_num,
            "stream_timebase_den": self.stream_timebase_den,
            "publishable_types": list(self.publishable_types),
        }


class EngineResourceBudget(_StrictModel):
    """Resource budget handed to the shared GPU lease (accepted shape)."""

    resource_class: str = Field(min_length=1)
    max_wall_seconds: float = Field(gt=0)
    max_vram_bytes: int = Field(ge=0)
    max_output_bytes: int = Field(gt=0)

    def to_budget_kwargs(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in ENGINE_BUDGET_FIELDS}


class EngineInputBinding(_StrictModel):
    """Everything the engine call is built from — projected EXACTLY onto the
    accepted ``MediaEngineRequest`` field sets."""

    capability: str = Field(min_length=1)
    identity: EngineRequestIdentity
    source: EngineSourceLock
    cast: tuple[RoleCastBinding, ...] = ()
    anchor: ArtifactRef | None = None
    source_window: ArtifactRef
    graph: EngineWorkflowPin
    #: Provenance of the auxiliary files (LoRA / text encoder / vision / VAE); the
    #: engine request carries the primary model pin + workflow/config hashes.
    auxiliary_models: tuple[EngineModelBinding, ...] = ()
    output_contract: EngineOutputContract
    budget: EngineResourceBudget

    @model_validator(mode="after")
    def _check(self) -> EngineInputBinding:
        if self.capability not in ENGINE_CAPABILITY_PINS:
            _refuse(
                ShotReskinRefusalCode.ENGINE_CAPABILITY_UNKNOWN,
                f"{self.capability!r} is not an accepted capability "
                f"{list(ENGINE_CAPABILITY_PINS)}",
            )
        if self.source_window.sha256 != self.source.source_sha256:
            _refuse(
                ShotReskinRefusalCode.RECORD_INCONSISTENT,
                "source_window artifact must be the locked source artifact (same sha256)",
            )
        roles_min, refs_min = ENGINE_REFERENCE_MINIMA_PIN[self.capability]
        if len(self.cast) < roles_min:
            _refuse(
                ShotReskinRefusalCode.CAST_REFERENCE_REQUIRED,
                f"{self.capability} needs at least {roles_min} bound role(s) carrying reference "
                f"pixels; got {len(self.cast)}",
            )
        for binding in self.cast:
            distinct = {item.artifact.sha256 for item in binding.references}
            if len(distinct) < refs_min:
                supplied = len(binding.references)
                duplicates = supplied - len(distinct)
                detail = (
                    f"role {binding.role!r} needs at least {refs_min} INDEPENDENT reference "
                    f"artifact(s); got {len(distinct)}"
                )
                if duplicates:
                    detail += (
                        f" — {supplied} entries were supplied but {duplicates} of them repeat "
                        "reference pixels already counted"
                    )
                _refuse(ShotReskinRefusalCode.CAST_REFERENCE_REQUIRED, detail)
        if self.capability == "source_video_motion_transfer" and self.anchor is None:
            _refuse(
                ShotReskinRefusalCode.RECORD_INCONSISTENT,
                "source_video_motion_transfer requires a start anchor (the G2 gate)",
            )
        return self

    def to_request_payload(self) -> dict[str, Any]:
        """The exact kwargs of the accepted ``MediaEngineRequest``."""
        payload: dict[str, Any] = dict(self.identity.to_request_kwargs())
        payload["capability"] = self.capability
        payload["source"] = self.source.to_source_lock_kwargs()
        payload["cast"] = [
            {
                "role": binding.role,
                "character_id": binding.character_id,
                "pack_version_id": binding.pack_version_id,
                "references": [
                    {"artifact_id": item.artifact.artifact_id, "sha256": item.artifact.sha256}
                    for item in binding.references
                ],
                "style_version": binding.style_version,
            }
            for binding in self.cast
        ]
        payload["pins"] = self.graph.to_pins_kwargs()
        payload["output"] = self.output_contract.to_output_kwargs()
        payload["budget"] = self.budget.to_budget_kwargs()
        return payload

    def request_payload_sha256(self) -> str:
        return payload_sha256(self.to_request_payload())


class EngineArtifactOutput(_StrictModel):
    """One produced artifact (accepted ``ManagedArtifact`` field semantics)."""

    artifact_id: str = Field(min_length=1)
    kind: Literal["image", "video", "audio", "pose_sheet", "mask", "graph"]
    media_type: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    store_relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    publishable: bool = False
    server_output_type: str = "unclassified"

    @model_validator(mode="after")
    def _check(self) -> EngineArtifactOutput:
        if self.kind not in ENGINE_ARTIFACT_KINDS:
            _refuse(
                ShotReskinRefusalCode.ENGINE_KIND_UNKNOWN,
                f"kind must be one of {ENGINE_ARTIFACT_KINDS}; got {self.kind!r}",
            )
        if self.server_output_type not in ENGINE_SERVER_OUTPUT_TYPES:
            raise ValueError(
                f"server_output_type must be one of {ENGINE_SERVER_OUTPUT_TYPES}; got "
                f"{self.server_output_type!r}"
            )
        if self.publishable and self.kind not in ENGINE_PUBLISHABLE_ARTIFACT_KINDS:
            _refuse(
                ShotReskinRefusalCode.ARTIFACT_NOT_PUBLISHABLE,
                f"artifact {self.artifact_id} is a {self.kind} intermediate and can never be "
                "publishable",
            )
        if self.store_relative_path.startswith(("/", "\\")) or ":" in self.store_relative_path:
            _refuse(
                ShotReskinRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifact paths are store-relative; got {self.store_relative_path!r}",
            )
        if ".." in self.store_relative_path.replace("\\", "/").split("/"):
            _refuse(
                ShotReskinRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED,
                f"artifact path escapes the store: {self.store_relative_path!r}",
            )
        return self


class EngineDecodedFacts(_StrictModel):
    """Decoded output facts (accepted ``DecodedMap`` shape; ``mapping`` may be
    absent because the proof receipts do not record one — an engine RESULT that
    requires it refuses instead of inventing it)."""

    decoded_frames: int = Field(gt=0)
    first_pts_ticks: int = Field(ge=0)
    timebase: str = Field(min_length=3)
    mapping: tuple[int, ...] | None = None

    @model_validator(mode="after")
    def _check(self) -> EngineDecodedFacts:
        if self.mapping is not None:
            if len(self.mapping) != self.decoded_frames:
                raise ValueError("mapping length must equal decoded_frames")
            if any(i < 0 for i in self.mapping):
                raise ValueError("mapping indices must be >= 0")
        return self


class EngineOutputBinding(_StrictModel):
    """What the engine returned: prompt receipt + artifacts + decoded facts."""

    prompt_id: str = Field(min_length=1)
    owner_session: str | None = None
    graph_sha256_server: str = Field(min_length=64, max_length=64)
    artifacts: tuple[EngineArtifactOutput, ...] = Field(min_length=1)
    decoded: EngineDecodedFacts
    audio: EngineAudioHandoff
    server_side_wall_s: float = Field(gt=0)
    vram_peak_mib: int = Field(ge=0)

    def assert_result_ready(self) -> None:
        """Fail closed when composition to an engine RESULT is not yet possible."""
        if self.decoded.mapping is None:
            _refuse(
                ShotReskinRefusalCode.ENGINE_RESULT_INCOMPLETE,
                "the accepted result DTO requires a decoded frame map; no mapping was recorded "
                "for this output — record it, do not invent one",
            )


class ShotEngineError(_StrictModel):
    """The error field of a shot execution record."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False
    refusal_code: ShotReskinRefusalCode | None = None


class ShotExecutionRecord(_StrictModel):
    """The shot-level execution record: backend (orthogonal axis) + input/output/
    capability/error.  It never executes anything itself."""

    schema_version: str = SCHEMA_VERSION
    execution_backend: str = Field(min_length=1)
    legacy_route: str | None = None
    capability: str | None = None
    outcome: Literal["pending", "completed", "failed"] = "pending"
    input: EngineInputBinding | None = None
    output: EngineOutputBinding | None = None
    error: ShotEngineError | None = None

    @model_validator(mode="after")
    def _check(self) -> ShotExecutionRecord:
        if self.schema_version != SCHEMA_VERSION:
            _refuse(
                ShotReskinRefusalCode.SCHEMA_VERSION_UNSUPPORTED,
                f"schema_version {self.schema_version!r} is not {SCHEMA_VERSION!r}",
            )
        if self.execution_backend in LEGACY_RENDERER_ROUTES_PIN:
            _refuse(
                ShotReskinRefusalCode.LEGACY_ROUTE_AS_BACKEND_REFUSED,
                f"execution_backend {self.execution_backend!r} is a legacy renderer ROUTE; the "
                "execution backend is an orthogonal axis — a route value is never a backend",
            )
        if self.execution_backend not in tuple(b.value for b in ExecutionBackend):
            _refuse(
                ShotReskinRefusalCode.BACKEND_UNKNOWN_REFUSED,
                f"execution_backend {self.execution_backend!r} is not one of "
                f"{[b.value for b in ExecutionBackend]}",
            )
        if self.execution_backend == ExecutionBackend.COMFY_SHOT_ENGINE.value:
            if self.capability is None:
                _refuse(
                    ShotReskinRefusalCode.ENGINE_CAPABILITY_REQUIRED,
                    "comfy_shot_engine requires an explicit capability",
                )
            if self.capability not in ENGINE_CAPABILITY_PINS:
                _refuse(
                    ShotReskinRefusalCode.ENGINE_CAPABILITY_UNKNOWN,
                    f"capability {self.capability!r} is not an accepted capability",
                )
            if self.legacy_route is not None:
                _refuse(
                    ShotReskinRefusalCode.BACKEND_BINDING_INVALID,
                    "a comfy_shot_engine record never carries a legacy_route: Comfy is not an "
                    "alias of a legacy route and does not inherit its semantics",
                )
        else:  # legacy_renderer
            if self.capability is not None:
                _refuse(
                    ShotReskinRefusalCode.BACKEND_BINDING_INVALID,
                    "a legacy_renderer record carries no engine capability; the legacy route "
                    "taxonomy keeps its own semantics",
                )
            if self.legacy_route is None or self.legacy_route not in LEGACY_RENDERER_ROUTES_PIN:
                _refuse(
                    ShotReskinRefusalCode.BACKEND_BINDING_INVALID,
                    f"legacy_renderer requires legacy_route in {list(LEGACY_RENDERER_ROUTES_PIN)}; "
                    f"got {self.legacy_route!r}",
                )
            if self.input is not None or self.output is not None:
                _refuse(
                    ShotReskinRefusalCode.BACKEND_BINDING_INVALID,
                    "a legacy_renderer record carries no engine input/output",
                )
        if self.outcome == "completed":
            if self.input is None or self.output is None:
                _refuse(
                    ShotReskinRefusalCode.RECORD_INCONSISTENT,
                    "outcome=completed requires both input and output bindings",
                )
            if self.error is not None:
                _refuse(
                    ShotReskinRefusalCode.RECORD_INCONSISTENT,
                    "outcome=completed cannot carry an error",
                )
        elif self.outcome == "failed":
            if self.error is None:
                _refuse(
                    ShotReskinRefusalCode.RECORD_INCONSISTENT,
                    "outcome=failed requires the error field",
                )
            if self.output is not None:
                _refuse(
                    ShotReskinRefusalCode.RECORD_INCONSISTENT,
                    "outcome=failed cannot carry an output binding",
                )
        elif self.output is not None or self.error is not None:
            _refuse(
                ShotReskinRefusalCode.RECORD_INCONSISTENT,
                "outcome=pending carries neither output nor error",
            )
        return self


# ── the shot plan ─────────────────────────────────────────────────────────────


class ShotPlan(_StrictModel):
    """One shot's reskin plan: source span/timebase, declared roles, references,
    interactions, source facts and the output observation binding."""

    schema_version: str = SCHEMA_VERSION
    project_id: str = Field(min_length=1)
    series_id: str | None = None
    video_id: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    source: ArtifactRef
    span: SourceSpan
    timebase: TimebaseFacts
    elements: tuple[ElementUnit, ...] = Field(min_length=1)
    interactions: tuple[InteractionRef, ...] = ()
    reference_manifest: ReferenceManifest
    source_evidence: tuple[SourceEvidenceFact, ...] = ()
    output_observations: OutputObservationBinding | None = None

    @property
    def declared_roles(self) -> frozenset[str]:
        return frozenset(element.role for element in self.elements)

    @model_validator(mode="after")
    def _check(self) -> ShotPlan:
        if self.schema_version != SCHEMA_VERSION:
            _refuse(
                ShotReskinRefusalCode.SCHEMA_VERSION_UNSUPPORTED,
                f"schema_version {self.schema_version!r} is not {SCHEMA_VERSION!r}",
            )
        roles = [element.role for element in self.elements]
        duplicates = sorted({role for role in roles if roles.count(role) > 1})
        if duplicates:
            _refuse(
                ShotReskinRefusalCode.DUPLICATE_ROLE_REFUSED,
                f"element roles must be unique within a shot; duplicated {duplicates}",
            )
        declared = self.declared_roles
        for element in self.elements:
            for span in element.visible_spans:
                if not self.span.contains(span):
                    _refuse(
                        ShotReskinRefusalCode.INVALID_INTERVAL_REFUSED,
                        f"element {element.role} visible span {span.key()} is outside the shot "
                        f"span {self.span.key()}",
                    )
        for interaction in self.interactions:
            for role_name, role in (
                ("subject", interaction.subject_role),
                ("object", interaction.object_role),
            ):
                if role not in declared:
                    _refuse(
                        ShotReskinRefusalCode.FOREIGN_ROLE_REFUSED,
                        f"interaction {role_name} role {role!r} is not declared by this shot's "
                        f"elements {sorted(declared)}",
                    )
            for span in interaction.spans:
                if not self.span.intersects(span):
                    _refuse(
                        ShotReskinRefusalCode.INVALID_INTERVAL_REFUSED,
                        f"interaction span {span.key()} does not intersect the shot span "
                        f"{self.span.key()}",
                    )
        evidence_ids = {fact.evidence_id for fact in self.source_evidence}
        for interaction in self.interactions:
            for ref in interaction.evidence_ids:
                if ref not in evidence_ids:
                    _refuse(
                        ShotReskinRefusalCode.UNKNOWN_EVIDENCE_REFUSED,
                        f"interaction references evidence {ref!r} that is not declared in "
                        "source_evidence",
                    )
        manifest_roles = {role_set.role for role_set in self.reference_manifest.roles}
        foreign = sorted(manifest_roles - declared)
        if foreign:
            _refuse(
                ShotReskinRefusalCode.FOREIGN_ROLE_REFUSED,
                f"reference manifest names role(s) {foreign} that are not declared by this "
                f"shot's elements {sorted(declared)}",
            )
        frames = self.timebase.decoded_frame_count or self.span.frame_count
        if frames > 1 and self.timebase.pts_span_ticks == 0:
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                f"pts span is ZERO but the shot span {self.span.key()} holds {frames} frames",
            )
        required = self.timebase.required_pts_span(frames)
        if required is not None and self.timebase.pts_span_ticks < required:
            _refuse(
                ShotReskinRefusalCode.TIMEBASE_INVALID,
                f"pts span {self.timebase.pts_span_ticks} ticks cannot hold {frames} frames at "
                f"fps {self.timebase.fps} and stream time_base {self.timebase.stream_timebase}: "
                f"at least {required} ticks are required",
            )
        if (
            self.timebase.decoded_frame_count is not None
            and self.timebase.decoded_frame_count != self.span.frame_count
        ):
            _refuse(
                ShotReskinRefusalCode.RECORD_INCONSISTENT,
                f"decoded_frame_count {self.timebase.decoded_frame_count} != span frame count "
                f"{self.span.frame_count}",
            )
        person_roles = {element.role for element in self.elements if element.kind == "person"}
        for interaction in self.interactions:
            for role in (interaction.subject_role, interaction.object_role):
                if role in person_roles and role not in manifest_roles:
                    _refuse(
                        ShotReskinRefusalCode.CAST_REFERENCE_REQUIRED,
                        f"person role {role!r} is referenced by an interaction but has no "
                        "reference set in the manifest: every interacting person must carry "
                        "references before the shot can be rendered",
                    )
        for fact in self.source_evidence:
            if fact.subject_role not in declared:
                _refuse(
                    ShotReskinRefusalCode.FOREIGN_ROLE_REFUSED,
                    f"source evidence {fact.evidence_id} names undeclared role "
                    f"{fact.subject_role!r}",
                )
            if fact.artifact.sha256 != self.source.sha256:
                _refuse(
                    ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH,
                    f"source evidence {fact.evidence_id} is measured on artifact "
                    f"{fact.artifact.sha256[:16]}… but this shot's locked source is "
                    f"{self.source.sha256[:16]}…; source facts are measured on the source",
                )
        if self.output_observations is not None:
            binding = self.output_observations
            if binding.source_artifact.sha256 != self.source.sha256:
                _refuse(
                    ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH,
                    f"output binding names source artifact "
                    f"{binding.source_artifact.sha256[:16]}… which is not this shot's locked "
                    f"source {self.source.sha256[:16]}…",
                )
            for obs in binding.observations:
                if obs.subject_role not in declared:
                    _refuse(
                        ShotReskinRefusalCode.FOREIGN_ROLE_REFUSED,
                        f"output observation {obs.observation_id} names undeclared role "
                        f"{obs.subject_role!r}",
                    )
        return self


# ── engine composition helpers ────────────────────────────────────────────────


def media_engine_module() -> Any | None:
    """The accepted media-engine DTO module, or ``None`` when it is not in the
    tree yet (the accepted transport is an INT job; MF-END-01 binds by name)."""
    try:
        if importlib.util.find_spec("app.schemas.media_engine") is None:
            return None
        from app.schemas import media_engine

        return media_engine
    except (ImportError, ModuleNotFoundError, ValueError):
        return None


MEDIA_ENGINE_DTO_PRESENT: bool = media_engine_module() is not None


def engine_request_payload(binding: EngineInputBinding) -> dict[str, Any]:
    """The exact ``MediaEngineRequest`` kwargs for a shot input binding."""
    return binding.to_request_payload()


def to_engine_request(binding: EngineInputBinding) -> Any:
    """Construct the ACCEPTED ``MediaEngineRequest`` through the real DTO.

    Fails closed with ``media_engine_dto_unavailable`` while the accepted
    contract bytes have not been transported into this tree — never by
    re-implementing or stubbing the DTO here.
    """
    module = media_engine_module()
    if module is None:
        _refuse(
            ShotReskinRefusalCode.MEDIA_ENGINE_DTO_UNAVAILABLE,
            "app.schemas.media_engine is not present in this tree; the accepted NR05/NR06 bytes "
            "(blob " + MEDIA_ENGINE_ACCEPTED_BLOB_PIN + ") are transported by the INT task — "
            "this contract composes the DTO, it never re-implements it",
        )
    payload = binding.to_request_payload()
    return module.MediaEngineRequest(**payload)


def input_binding_from_plan(
    plan: ShotPlan,
    *,
    identity: EngineRequestIdentity,
    capability: str,
    graph: EngineWorkflowPin,
    output_contract: EngineOutputContract,
    budget: EngineResourceBudget,
    anchor: ArtifactRef | None = None,
    auxiliary_models: tuple[EngineModelBinding, ...] = (),
) -> EngineInputBinding:
    """Compose a ShotPlan into the engine input binding — the cast/reference
    projection the accepted DTO consumes.  The plan's manifest is the single
    source of references; nothing is re-derived here."""
    cast = tuple(
        RoleCastBinding(
            role=role_set.role,
            character_id=role_set.character_id,
            pack_version_id=role_set.pack_version_id,
            references=role_set.items,
        )
        for role_set in plan.reference_manifest.roles
    )
    return EngineInputBinding(
        capability=capability,
        identity=identity,
        source=EngineSourceLock(
            source_artifact_id=plan.source.artifact_id,
            source_sha256=plan.source.sha256,
            span=plan.span,
            timebase=plan.timebase,
            decoded_frame_count=plan.timebase.decoded_frame_count,
        ),
        cast=cast,
        anchor=anchor,
        source_window=plan.source,
        graph=graph,
        auxiliary_models=auxiliary_models,
        output_contract=output_contract,
        budget=budget,
    )


# ── frozen examples (measured PROOF_GATE values; see the delivery contract) ───

#: Cast reference paths + digests frozen from the proof (P1_UNIT_MANIFESTS.json).
#: Kept as module constants so the nested example literals stay inside the line
#: budget; the values are the measured ones.
_FROZEN_REF_PATH = {
    "BOOK-P1": "inputs/i1d_cast_boy_hacker_sitting_on_neutral_bg.png",
    "BOOK-P2": "inputs/i1d_cast_dan_choi_standing_on_neutral_bg.png",
    "BOOK-P3": "inputs/i1d_cast_gau_nau_back_on_neutral_bg.png",
}
_FROZEN_REF_SHA = {
    "BOOK-P1": "a60969452f904e5e7249db1ff43d7b552f8d7105fa6bff84c6bc32b9273d02c4",
    "BOOK-P2": "271f1c5789ee8fb9022ab402d834c8f2d4e862f972a105060e457b68b0282496",
    "BOOK-P3": "9658aa3a947ffbf3c062757380438c36eb05bd2959444dddc659afbc60bffd11",
}
#: The submitted P3B graph sha256 (P3B_RECEIPT.json).
_FROZEN_GRAPH_SHA = "b2ab500748d5163797ccef71e6ed9e078682440a656afd6ae4ab4cf43234a36d"

#: The BOOK unit of the MF-V1-VIDEO14B Phase A proof (PROOF_GATE_CANDIDATE.md §5/§9)
#: as a ShotPlan.  Every sha256/span/byte value is MEASURED on the pinned proof
#: evidence; the app-side identity labels (project/series/artifact ids, cast
#: registry ids, evidence ids) are explicit labels because the demo registry does
#: not exist yet (MF-END-02+ creates it).
FROZEN_EXAMPLES: dict[str, Any] = {
    "shot_plan_book": {
        "schema_version": SCHEMA_VERSION,
        "project_id": "demo-project-r28",
        "series_id": "demo-series-r28",
        "video_id": "demo-video-book",
        "unit_id": "BOOK-UNIT-001",
        "shot_id": "BOOK",
        "source": {
            "artifact_id": "artifact.book.source_window",
            "kind": "video",
            "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
            "store_relative_path": "inputs/BOOK_src.mp4",
            "size_bytes": 141833,
        },
        "span": {"start_frame": 0, "end_frame_exclusive": 120},
        "timebase": {
            "fps_num": 30,
            "fps_den": 1,
            "stream_timebase_num": 1,
            "stream_timebase_den": 15360,
            "pts_start_ticks": 0,
            "pts_end_ticks": 60928,
            "decoded_frame_count": 120,
        },
        "elements": [
            {
                "role": "source_frame",
                "kind": "source_frame",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
            {
                "role": "BOOK-P1",
                "kind": "person",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
            {
                "role": "BOOK-P2",
                "kind": "person",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
            {
                "role": "BOOK-P3",
                "kind": "person",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
            {
                "role": "BOOK-P4",
                "kind": "person",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
            {
                "role": "book",
                "kind": "prop",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
            {
                "role": "yellow_part",
                "kind": "prop",
                "visible_spans": [
                    {"start_frame": 0, "end_frame_exclusive": 72},
                    {"start_frame": 105, "end_frame_exclusive": 120},
                ],
                "occlusion": "visible",
            },
            {
                "role": "table",
                "kind": "prop",
                "visible_spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "occlusion": "visible",
            },
        ],
        "interactions": [
            {
                "subject_role": "BOOK-P1",
                "relation": "holds",
                "object_role": "book",
                "spans": [{"start_frame": 0, "end_frame_exclusive": 72}],
                "evidence_ids": ["EV-BOOK-P1-HOLDS-BOOK"],
                "state": "measured",
            },
            {
                "subject_role": "BOOK-P1",
                "relation": "holds",
                "object_role": "book",
                "spans": [{"start_frame": 72, "end_frame_exclusive": 120}],
                "evidence_ids": ["EV-BOOK-BOOKSTATE-OPEN-72"],
                "state": "measured",
            },
            {
                "subject_role": "BOOK-P1",
                "relation": "holds",
                "object_role": "yellow_part",
                "spans": [
                    {"start_frame": 0, "end_frame_exclusive": 72},
                    {"start_frame": 105, "end_frame_exclusive": 120},
                ],
                "evidence_ids": ["EV-BOOK-P1-HOLDS-BOOK"],
                "state": "measured",
            },
            {
                "subject_role": "BOOK-P3",
                "relation": "sits_behind",
                "object_role": "table",
                "spans": [{"start_frame": 0, "end_frame_exclusive": 120}],
                "evidence_ids": ["EV-BOOK-P3-BACK-TO-CAMERA"],
                "state": "measured",
            },
        ],
        "reference_manifest": {
            "style_version": "roundD-style-1",
            "roles": [
                {
                    "role": "BOOK-P1",
                    "character_id": "cast-boy-hacker",
                    "pack_version_id": "demo-packversion-r28",
                    "items": [
                        {
                            "key": "identity_anchor",
                            "artifact": {
                                "artifact_id": "artifact.book.ref.BOOK-P1",
                                "kind": "image",
                                "sha256": _FROZEN_REF_SHA["BOOK-P1"],
                                "store_relative_path": _FROZEN_REF_PATH["BOOK-P1"],
                                "size_bytes": 3586,
                            },
                        }
                    ],
                },
                {
                    "role": "BOOK-P2",
                    "character_id": "cast-dan-choi",
                    "pack_version_id": "demo-packversion-r28",
                    "items": [
                        {
                            "key": "identity_anchor",
                            "artifact": {
                                "artifact_id": "artifact.book.ref.BOOK-P2",
                                "kind": "image",
                                "sha256": _FROZEN_REF_SHA["BOOK-P2"],
                                "store_relative_path": _FROZEN_REF_PATH["BOOK-P2"],
                            },
                        }
                    ],
                },
                {
                    "role": "BOOK-P3",
                    "character_id": "cast-gau-nau",
                    "pack_version_id": "demo-packversion-r28",
                    "items": [
                        {
                            "key": "identity_anchor",
                            "artifact": {
                                "artifact_id": "artifact.book.ref.BOOK-P3",
                                "kind": "image",
                                "sha256": _FROZEN_REF_SHA["BOOK-P3"],
                                "store_relative_path": _FROZEN_REF_PATH["BOOK-P3"],
                            },
                        }
                    ],
                },
            ],
        },
        "source_evidence": [
            {
                "evidence_id": "EV-BOOK-P1-HOLDS-BOOK",
                "subject_role": "BOOK-P1",
                "kind": "holder",
                "span": {"start_frame": 0, "end_frame_exclusive": 120},
                "artifact": {
                    "artifact_id": "artifact.book.source_window",
                    "kind": "video",
                    "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                    "store_relative_path": "inputs/BOOK_src.mp4",
                    "size_bytes": 141833,
                },
                "state": "measured",
            },
            {
                "evidence_id": "EV-BOOK-BOOKSTATE-OPEN-72",
                "subject_role": "BOOK-P1",
                "kind": "event",
                "span": {"start_frame": 72, "end_frame_exclusive": 120},
                "artifact": {
                    "artifact_id": "artifact.book.source_window",
                    "kind": "video",
                    "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                    "store_relative_path": "inputs/BOOK_src.mp4",
                    "size_bytes": 141833,
                },
                "state": "measured",
            },
            {
                "evidence_id": "EV-BOOK-P3-BACK-TO-CAMERA",
                "subject_role": "BOOK-P3",
                "kind": "presence",
                "span": {"start_frame": 0, "end_frame_exclusive": 120},
                "artifact": {
                    "artifact_id": "artifact.book.source_window",
                    "kind": "video",
                    "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                    "store_relative_path": "inputs/BOOK_src.mp4",
                    "size_bytes": 141833,
                },
                "state": "measured",
            },
        ],
        "output_observations": {
            "state": "unmeasured",
            "source_artifact": {
                "artifact_id": "artifact.book.source_window",
                "kind": "video",
                "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                "store_relative_path": "inputs/BOOK_src.mp4",
                "size_bytes": 141833,
            },
            "output_artifact": {
                "artifact_id": "artifact.book.p3b.clip",
                "kind": "video",
                "sha256": "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f",
                "store_relative_path": "p3b/animate2_book_p3b_00001_.mp4",
                "size_bytes": 208053,
            },
        },
    },
    "execution_record_book_p3b": {
        "schema_version": SCHEMA_VERSION,
        "execution_backend": "comfy_shot_engine",
        "legacy_route": None,
        "capability": "source_video_motion_transfer",
        "outcome": "completed",
        "input": {
            "capability": "source_video_motion_transfer",
            "identity": {
                "workspace_id": "demo-workspace",
                "project_id": "demo-project-r28",
                "series_id": "demo-series-r28",
                "video_id": "demo-video-book",
                "stage": "shot_render",
                "attempt_id": "attempt-book-p3b-1",
                "job_id": None,
            },
            "source": {
                "source_artifact_id": "artifact.book.source_window",
                "source_sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                "span": {"start_frame": 0, "end_frame_exclusive": 120},
                "timebase": {
                    "fps_num": 30,
                    "fps_den": 1,
                    "stream_timebase_num": 1,
                    "stream_timebase_den": 15360,
                    "pts_start_ticks": 0,
                    "pts_end_ticks": 60928,
                    "decoded_frame_count": 120,
                },
                "decoded_frame_count": 120,
            },
            "cast": [
                {
                    "role": "BOOK-P1",
                    "character_id": "cast-boy-hacker",
                    "pack_version_id": "demo-packversion-r28",
                    "references": [
                        {
                            "key": "identity_anchor",
                            "artifact": {
                                "artifact_id": "artifact.book.ref.BOOK-P1",
                                "kind": "image",
                                "sha256": _FROZEN_REF_SHA["BOOK-P1"],
                                "store_relative_path": _FROZEN_REF_PATH["BOOK-P1"],
                                "size_bytes": 3586,
                            },
                        }
                    ],
                },
                {
                    "role": "BOOK-P2",
                    "character_id": "cast-dan-choi",
                    "pack_version_id": "demo-packversion-r28",
                    "references": [
                        {
                            "key": "identity_anchor",
                            "artifact": {
                                "artifact_id": "artifact.book.ref.BOOK-P2",
                                "kind": "image",
                                "sha256": _FROZEN_REF_SHA["BOOK-P2"],
                                "store_relative_path": _FROZEN_REF_PATH["BOOK-P2"],
                            },
                        }
                    ],
                },
                {
                    "role": "BOOK-P3",
                    "character_id": "cast-gau-nau",
                    "pack_version_id": "demo-packversion-r28",
                    "references": [
                        {
                            "key": "identity_anchor",
                            "artifact": {
                                "artifact_id": "artifact.book.ref.BOOK-P3",
                                "kind": "image",
                                "sha256": _FROZEN_REF_SHA["BOOK-P3"],
                                "store_relative_path": _FROZEN_REF_PATH["BOOK-P3"],
                            },
                        }
                    ],
                },
            ],
            "anchor": {
                "artifact_id": "artifact.book.anchor_p2",
                "kind": "image",
                "sha256": "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e",
                "store_relative_path": "inputs/anchor_book_p2_00001_.png",
            },
            "source_window": {
                "artifact_id": "artifact.book.source_window",
                "kind": "video",
                "sha256": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                "store_relative_path": "inputs/BOOK_src.mp4",
                "size_bytes": 141833,
            },
            "graph": {
                "workflow_id": "mf.comfy.wan_animate2.motion_transfer",
                "workflow_version": "p3b",
                "workflow_hash": "b2ab500748d5163797ccef71e6ed9e078682440a656afd6ae4ab4cf43234a36d",
                "model": {
                    "model_id": "wan_animate_2_int8_convrot",
                    "revision": None,
                    "file": {
                        "algorithm": "sha256",
                        "scope": "full_file",
                        "value": "0580ecdd65e47e97c30df9670d13a6c4a131d26de5a1faf2ccc78392d5167584",
                    },
                    "precision": "int8",
                    "size_bytes": 16653175528,
                },
                "nodes": [],
                "config_hash": "932454b6b5c4a33a5bffe10b3e67a042cab0471acdab7e4219ce3d5d20fca532",
                "seed": 582699151003550,
            },
            "auxiliary_models": [
                {
                    "model_id": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16",
                    "revision": None,
                    "file": {
                        "algorithm": "sha256",
                        "scope": "full_file",
                        "value": "85c4a61c30e0497aa44b91d93a893b624708461a56fe5485183b28fa07e2dfb3",
                    },
                    "precision": "bf16",
                    "size_bytes": 738005744,
                },
                {
                    "model_id": "umt5_xxl_fp8_e4m3fn_scaled",
                    "revision": None,
                    "file": {
                        "algorithm": "sha256",
                        "scope": "full_file",
                        "value": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
                    },
                    "precision": "fp8_e4m3fn",
                    "size_bytes": 6735906897,
                },
                {
                    "model_id": "clip_vision_h",
                    "revision": None,
                    "file": {
                        "algorithm": "sha256",
                        "scope": "full_file",
                        "value": "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
                    },
                    "precision": "not_recorded",
                    "size_bytes": 1264219396,
                },
                {
                    "model_id": "Wan2_1_VAE_bf16",
                    "revision": None,
                    "file": {
                        "algorithm": "sha256",
                        "scope": "full_file",
                        "value": "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9",
                    },
                    "precision": "bf16",
                    "size_bytes": 253806278,
                },
            ],
            "output_contract": {
                "width": 640,
                "height": 368,
                "fps_num": 30,
                "fps_den": 1,
                "frame_count": 120,
                "container": "mp4",
                "video_codec": "h264",
                "audio": {
                    "mode": "source_remux",
                    "source_artifact_id": "artifact.book.source_window",
                    "sample_rate": 44100,
                    "channels": 2,
                    "codec": "aac",
                },
                "stream_timebase_num": 1,
                "stream_timebase_den": 15360,
                "publishable_types": ["output"],
            },
            "budget": {
                "resource_class": "gpu_12gb",
                "max_wall_seconds": 900.0,
                "max_vram_bytes": 12821706752,
                "max_output_bytes": 536870912,
            },
        },
        "output": {
            "prompt_id": "d1f4e097-458d-4bd4-8049-fe6da26f91c1",
            "owner_session": None,
            "graph_sha256_server": _FROZEN_GRAPH_SHA,
            "artifacts": [
                {
                    "artifact_id": "artifact.book.p3b.clip",
                    "kind": "video",
                    "media_type": "video/mp4",
                    "sha256": "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f",
                    "store_relative_path": "p3b/animate2_book_p3b_00001_.mp4",
                    "size_bytes": 208053,
                },
                {
                    "artifact_id": "artifact.book.p3b.still_first",
                    "kind": "video",
                    "media_type": "video/mp4",
                    "sha256": "a0eb2577607aec9408e4ca8d418ed222fd5c9b9ce941340c10483fc6a2785588",
                    "store_relative_path": "p3b/animate2_book_p3b_00002_.mp4",
                    "size_bytes": 26407,
                },
                {
                    "artifact_id": "artifact.book.p3b.composite",
                    "kind": "video",
                    "media_type": "video/mp4",
                    "sha256": "d1939c5aae91be6190215935f371c719c8d6f1f420cda06c21c74c969e139276",
                    "store_relative_path": "p3b/animate2_book_p3b_00003_.mp4",
                    "size_bytes": 238389,
                },
                {
                    "artifact_id": "artifact.book.p3b.still_second",
                    "kind": "video",
                    "media_type": "video/mp4",
                    "sha256": "3570d93eb155999d146fa84c978f1c5877b5f01ed6cba39b21da9852309bbead",
                    "store_relative_path": "p3b/animate2_book_p3b_00004_.mp4",
                    "size_bytes": 36543,
                },
            ],
            "decoded": {
                "decoded_frames": 120,
                "first_pts_ticks": 0,
                "timebase": "1/15360",
            },
            "audio": {
                "mode": "source_remux",
                "source_artifact_id": "artifact.book.source_window",
                "sample_rate": 44100,
                "channels": 2,
                "codec": "aac",
            },
            "server_side_wall_s": 154.67,
            "vram_peak_mib": 10973,
        },
        "error": None,
    },
    "negative_fixtures": [
        {
            "id": "N01_client_path_on_reference",
            "base": "shot_plan_book",
            "set": [["reference_manifest.roles.0.items.0.artifact.path", "C:/tmp/cast.png"]],
            "expected_refusal_code": "client_artifact_path_refused",
            "note": "a client path is refused by the contract, never resolved",
        },
        {
            "id": "N02_foreign_role_in_interaction",
            "base": "shot_plan_book",
            "set": [["interactions.0.subject_role", "BOOK-P9"]],
            "expected_refusal_code": "foreign_role_refused",
            "note": "interaction may only name declared element roles",
        },
        {
            "id": "N03_foreign_role_in_manifest",
            "base": "shot_plan_book",
            "set": [["reference_manifest.roles.0.role", "BOOK-P9"]],
            "expected_refusal_code": "foreign_role_refused",
            "note": "manifest may only carry declared roles",
        },
        {
            "id": "N04_invalid_interval_span",
            "base": "shot_plan_book",
            "set": [["span.end_frame_exclusive", 0]],
            "expected_refusal_code": "invalid_interval_refused",
            "note": "empty/negative half-open interval",
        },
        {
            "id": "N05_invalid_interval_element_outside",
            "base": "shot_plan_book",
            "set": [["elements.0.visible_spans.0.end_frame_exclusive", 500]],
            "expected_refusal_code": "invalid_interval_refused",
            "note": "element visibility must stay inside the shot span",
        },
        {
            "id": "N06_timebase_half_pair",
            "base": "shot_plan_book",
            "set": [["timebase.stream_timebase_den", None]],
            "expected_refusal_code": "timebase_invalid",
            "note": "time_base is declared as a pair or not at all",
        },
        {
            "id": "N07_timebase_zero_span_multiframe",
            "base": "shot_plan_book",
            "set": [["timebase.pts_start_ticks", 0], ["timebase.pts_end_ticks", 0]],
            "expected_refusal_code": "timebase_invalid",
            "note": "a 120-frame span cannot be a point in time",
        },
        {
            "id": "N08_timebase_pts_capacity",
            "base": "shot_plan_book",
            "set": [["timebase.pts_end_ticks", 4096]],
            "expected_refusal_code": "timebase_invalid",
            "note": "119 frame intervals need >= 60928 ticks at 30/1 and 1/15360",
        },
        {
            "id": "N09_legacy_route_as_backend",
            "base": "execution_record_book_p3b",
            "set": [["execution_backend", "sprite_affine"]],
            "expected_refusal_code": "legacy_route_as_backend_refused",
            "note": "a legacy renderer route is never an execution backend",
        },
        {
            "id": "N10_comfy_with_legacy_route",
            "base": "execution_record_book_p3b",
            "set": [["legacy_route", "pose_swap"]],
            "expected_refusal_code": "backend_binding_invalid",
            "note": "Comfy does not alias a legacy route",
        },
        {
            "id": "N11_backend_unknown",
            "base": "execution_record_book_p3b",
            "set": [["execution_backend", "comfy_engine2"]],
            "expected_refusal_code": "backend_unknown_refused",
            "note": "backend vocabulary is closed",
        },
        {
            "id": "N12_capability_missing",
            "base": "execution_record_book_p3b",
            "set": [["capability", None]],
            "expected_refusal_code": "engine_capability_required",
            "note": "comfy backend without a capability is refused",
        },
        {
            "id": "N13_schema_version_unsupported",
            "base": "execution_record_book_p3b",
            "set": [["schema_version", "mf.shot_reskin.contract.v0"]],
            "expected_refusal_code": "schema_version_unsupported",
            "note": "versioned contract; unknown version refuses",
        },
        {
            "id": "N14_output_binds_source_artifact",
            "base": "shot_plan_book",
            "set": [
                [
                    "output_observations.output_artifact.sha256",
                    "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
                ]
            ],
            "expected_refusal_code": "output_binds_source_artifact",
            "note": "the source returned as output is refused (MF-END-19 acceptance)",
        },
        {
            "id": "N15_source_fact_measured_on_foreign_artifact",
            "base": "shot_plan_book",
            "set": [
                [
                    "source_evidence.0.artifact.sha256",
                    "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e",
                ]
            ],
            "expected_refusal_code": "evidence_domain_mismatch",
            "note": "source facts are measured on the locked source",
        },
        {
            "id": "N16_output_binding_names_foreign_source",
            "base": "shot_plan_book",
            "set": [
                [
                    "output_observations.source_artifact.sha256",
                    "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e",
                ]
            ],
            "expected_refusal_code": "evidence_domain_mismatch",
            "note": "the output binding must name THIS shot's locked source",
        },
        {
            "id": "N17_unknown_evidence_ref",
            "base": "shot_plan_book",
            "set": [["interactions.0.evidence_ids.0", "EV-NOPE"]],
            "expected_refusal_code": "unknown_evidence_refused",
            "note": "interaction evidence must exist in source_evidence",
        },
        {
            "id": "N18_duplicate_role",
            "base": "shot_plan_book",
            "append": [["elements", {"role": "BOOK-P1", "kind": "person"}]],
            "expected_refusal_code": "duplicate_role_refused",
            "note": "element roles are unique within a shot",
        },
        {
            "id": "N19_model_pin_head_hash_only",
            "base": "execution_record_book_p3b",
            "set": [
                [
                    "input.graph.model.file",
                    {"algorithm": "sha256", "scope": "head_1mib", "value": "f7ba70b820aa441f"},
                ]
            ],
            "expected_refusal_code": "full_file_hash_required",
            "note": "the engine pin needs the full-file sha256, not a head-hash",
        },
        {
            "id": "N20_mask_publishable",
            "base": "execution_record_book_p3b",
            "set": [["output.artifacts.0.kind", "mask"], ["output.artifacts.0.publishable", True]],
            "expected_refusal_code": "artifact_not_publishable",
            "note": "a mask is managed but never publishable",
        },
        {
            "id": "N21_artifact_path_escape",
            "base": "execution_record_book_p3b",
            "set": [["output.artifacts.0.store_relative_path", "../escape.mp4"]],
            "expected_refusal_code": "client_artifact_path_refused",
            "note": "store-relative only; traversal refuses",
        },
        {
            "id": "N22_cast_reference_required",
            "base": "execution_record_book_p3b",
            "set": [["input.cast.0.references", []]],
            "expected_refusal_code": "cast_reference_required",
            "note": "motion transfer needs reference pixels per bound role",
        },
        {
            "id": "N23_completed_without_output",
            "base": "execution_record_book_p3b",
            "set": [["output", None]],
            "expected_refusal_code": "record_inconsistent",
            "note": "outcome=completed requires the output binding",
        },
    ],
}

#: sha256 of the canonical engine-request payload built from the frozen BOOK
#: input binding WITH the provisioning revision label ``p3b-r28-local-convrot``
#: supplied (the frozen record keeps ``revision: null`` because the P0 model
#: inventory never recorded one — open item O1; the projection refuses a null
#: revision with a typed code instead of inventing a value).
FROZEN_REQUEST_PAYLOAD_SHA256 = "a81db36912ec6b20389d4cf205703b05dbb28de1ca693b9812b1e600d87bb3bd"


def _resolve_fixture_path(payload: Any, path: str) -> Any:
    node = payload
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def apply_fixture_ops(
    payload: dict[str, Any],
    *,
    set_ops: tuple[tuple[str, Any], ...] = (),
    append_ops: tuple[tuple[str, Any], ...] = (),
) -> dict[str, Any]:
    """Fixture tooling for ``FROZEN_EXAMPLES['negative_fixtures']``.

    Returns a deep copy of ``payload`` with ``set_ops`` (dotted path → value) and
    ``append_ops`` (dotted path to a list → appended value) applied in order.
    Used by the test file and the evidence probes so the fixtures stay one
    machine-readable source.
    """
    clone = copy.deepcopy(payload)
    for path, value in set_ops:
        parts = path.split(".")
        container = _resolve_fixture_path(clone, ".".join(parts[:-1])) if len(parts) > 1 else clone
        key = parts[-1]
        if isinstance(container, list):
            container[int(key)] = value
        else:
            container[key] = value
    for path, value in append_ops:
        node = _resolve_fixture_path(clone, path)
        node.append(copy.deepcopy(value))
    return clone


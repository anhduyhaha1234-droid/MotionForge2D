"""Rendered-output observations — masks/tracks measured on the OUTPUT pixels (MF-END-21).

The source side of a reskin already has a sealed frame → mask → track record
(MF-END-12, :mod:`app.services.source_role_tracks`).  This module is its
OUTPUT-side counterpart: it derives masks and tracks by running a REAL
segmentation/tracking pass over the pixels of the resolved RENDER artifact —
never over the imported source, and never from the intended configuration.

Hard boundaries (each one is a typed, tested refusal):

* the resolved artifact must be a RENDER for this video.  A video with no
  rendered output (the current result IS its imported source), or an artifact
  whose bytes ARE the source's bytes, refuses — "the intended source dressed
  as an output observation" is exactly the fraud this refuses;
* the frame space is the decoded OUTPUT artifact: the builder verifies the
  decoded frame count, the canvas geometry (the same measured geometry the
  source side uses) and that every declared segment frame really decodes; a
  frame the output does not carry refuses instead of being skipped;
* a claimed mask must be MEASURED on the output frame that carries it: it is
  accepted only when the pixels it covers differ from the ring of pixels
  around it (``mask_support_separation``) — a source-shaped crop pasted onto
  an output that does not paint it has no support and refuses;
* the measured mask rules of the source side are re-used verbatim
  (``mask_stats``): an all-canvas or hollow mask never grants a usable
  observation;
* instances are matched to cast/role through the ROLE's published reference
  pixels (the character-library pin, never a source crop) plus the declared
  temporal span.  An ambiguous or unsupported match is a TYPED UNKNOWN —
  the module never guesses a role;
* the sealed artifact binds role / frame / segment / render SHA / extractor
  params, so a reviewer can re-derive every observation from the exact output
  bytes.

Real inference is injected (:class:`OutputMaskEngine`): the shipped
:class:`LevelComponentMaskSource` is a CI-pixel engine (its output pixels are
computed, but its provenance can never be recorded as production), while a
production artifact REQUIRES a real capability probe for the applied engine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from app.persistence.artifacts import ManagedRoot
from app.persistence.models import Artifact, ArtifactOwner
from app.services import source_role_tracks as srt
from app.services.qc_evidence import measure as qcm
from app.services.qc_evidence import observe as obs
from app.services.qc_evidence import sources as src
from app.services.qc_evidence.errors import QcEvidenceError
from app.services.shot_reskin_plan import parse_rational

__all__ = [
    "CODE_DIGEST_MISMATCH",
    "CODE_ENGINE_UNPROBED",
    "CODE_FIXTURE_NOT_PRODUCTION",
    "CODE_FRAME_MAP_INVALID",
    "CODE_FRAME_NOT_OBSERVED",
    "CODE_GEOMETRY_MISMATCH",
    "CODE_MASK_ALL_CANVAS",
    "CODE_MASK_EMPTY",
    "CODE_MASK_HOLLOW",
    "CODE_NO_TRACE",
    "CODE_OBSERVATION_INVALID",
    "CODE_OUTPUT_FOREIGN",
    "CODE_OUTPUT_INVALID",
    "CODE_OUTPUT_IS_SOURCE",
    "CODE_OUTPUT_NOT_RENDER",
    "CODE_REFERENCE_INVALID",
    "CODE_SEGMENT_INVALID",
    "CODE_SERIALIZATION_INVALID",
    "CODE_SUPPORT_AMBIGUOUS",
    "CODE_VALID",
    "CODE_VERSION_UNSUPPORTED",
    "DEFAULT_ALL_CANVAS_RATIO",
    "DEFAULT_AREA_JUMP_RATIO",
    "DEFAULT_HOLLOW_RATIO",
    "DEFAULT_MATCH_MARGIN",
    "DEFAULT_MATCH_MAX_DISTANCE",
    "DEFAULT_MAX_DECODE_FRAMES",
    "DEFAULT_MIN_AREA_PX",
    "DEFAULT_SHIFT_RATIO",
    "DEFAULT_SUPPORT_HALO_PX",
    "FLAG_UNSTABLE_LINK",
    "MATCH_MATCHED",
    "MATCH_UNKNOWN",
    "OBSERVATIONS_SCHEMA_VERSION",
    "OBSERVATIONS_DETECTOR",
    "PERSON_ROLE_KINDS",
    "PROVENANCE_FIXTURE",
    "PROVENANCE_PRODUCTION",
    "RENDER_ROLES",
    "UNKNOWN_REASON_AMBIGUOUS",
    "UNKNOWN_REASON_NO_REFERENCE",
    "UNKNOWN_REASON_UNMATCHED",
    "EngineRecord",
    "LevelComponentMaskSource",
    "OutputMaskEngine",
    "RenderedObservationsArtifact",
    "RenderedObservationsError",
    "RenderedOutput",
    "RenderedReference",
    "RenderedSegment",
    "RenderedTrack",
    "TrackRefusal",
    "assert_artifact",
    "build_rendered_observations",
    "check_artifact",
    "decode_output_frame_map",
    "frame_map_sha256",
    "load_rendered_observations",
    "observe_rendered_output",
    "publish_rendered_observations",
    "references_for_roles",
    "require_production",
    "resolve_rendered_output",
    "segments_from_evidence",
]

# ── vocabulary ───────────────────────────────────────────────────────────────

#: Version of the persisted rendered-observation artifact (managed tag).
OBSERVATIONS_SCHEMA_VERSION = "mf.rendered_observations.v1"

#: Detector label carried by refusals raised from this module.
OBSERVATIONS_DETECTOR = "rendered_observations"

PROVENANCE_PRODUCTION = srt.PROVENANCE_PRODUCTION
PROVENANCE_FIXTURE = srt.PROVENANCE_FIXTURE

#: Roles of the resolved artifact that mean "a render exists for this video".
#: ``source_fallback_no_render`` is deliberately NOT here: the current result
#: being the imported source is the same-geometry case this module refuses.
RENDER_ROLES = ("publication", "owned_result_artifact")

MATCH_MATCHED = "matched"
MATCH_UNKNOWN = "unknown"

UNKNOWN_REASON_AMBIGUOUS = "ambiguous_reference_match"
UNKNOWN_REASON_UNMATCHED = "no_reference_within_distance"
UNKNOWN_REASON_NO_REFERENCE = "no_reference_available"

FLAG_UNSTABLE_LINK = "RENDERED_OBSERVATIONS_UNSTABLE_LINK"

# ── typed refusal codes (module-local, stable strings) ───────────────────────

CODE_OUTPUT_INVALID = "RENDERED_OBSERVATIONS_OUTPUT_INVALID"
CODE_OUTPUT_FOREIGN = "RENDERED_OBSERVATIONS_OUTPUT_FOREIGN"
CODE_OUTPUT_NOT_RENDER = "RENDERED_OBSERVATIONS_OUTPUT_NOT_RENDER"
CODE_OUTPUT_IS_SOURCE = "RENDERED_OBSERVATIONS_OUTPUT_IS_SOURCE"
CODE_FRAME_MAP_INVALID = "RENDERED_OBSERVATIONS_FRAME_MAP_INVALID"
CODE_FRAME_NOT_OBSERVED = "RENDERED_OBSERVATIONS_FRAME_NOT_OBSERVED"
CODE_GEOMETRY_MISMATCH = "RENDERED_OBSERVATIONS_GEOMETRY_MISMATCH"
CODE_MASK_EMPTY = "RENDERED_OBSERVATIONS_MASK_EMPTY"
CODE_MASK_ALL_CANVAS = "RENDERED_OBSERVATIONS_MASK_ALL_CANVAS"
CODE_MASK_HOLLOW = "RENDERED_OBSERVATIONS_MASK_HOLLOW"
CODE_SUPPORT_AMBIGUOUS = "RENDERED_OBSERVATIONS_SUPPORT_AMBIGUOUS"
CODE_SEGMENT_INVALID = "RENDERED_OBSERVATIONS_SEGMENT_INVALID"
CODE_REFERENCE_INVALID = "RENDERED_OBSERVATIONS_REFERENCE_INVALID"
CODE_OBSERVATION_INVALID = "RENDERED_OBSERVATIONS_OBSERVATION_INVALID"
CODE_FIXTURE_NOT_PRODUCTION = "RENDERED_OBSERVATIONS_FIXTURE_NOT_PRODUCTION"
CODE_ENGINE_UNPROBED = "RENDERED_OBSERVATIONS_ENGINE_UNPROBED"
CODE_NO_TRACE = "RENDERED_OBSERVATIONS_NO_TRACE"
CODE_DIGEST_MISMATCH = "RENDERED_OBSERVATIONS_DIGEST_MISMATCH"
CODE_VERSION_UNSUPPORTED = "RENDERED_OBSERVATIONS_VERSION_UNSUPPORTED"
CODE_SERIALIZATION_INVALID = "RENDERED_OBSERVATIONS_SERIALIZATION_INVALID"
CODE_VALID = "RENDERED_OBSERVATIONS_VALID"

# ── measured-rule defaults (the source side's own constants, re-used) ────────

DEFAULT_ALL_CANVAS_RATIO = srt.DEFAULT_ALL_CANVAS_RATIO
DEFAULT_HOLLOW_RATIO = srt.DEFAULT_HOLLOW_RATIO
DEFAULT_MIN_AREA_PX = srt.DEFAULT_MIN_AREA_PX
DEFAULT_SHIFT_RATIO = srt.DEFAULT_SHIFT_RATIO
DEFAULT_AREA_JUMP_RATIO = srt.DEFAULT_AREA_JUMP_RATIO

#: Ring width (px) measured around a claimed mask to establish its pixel
#: support on the output frame.
DEFAULT_SUPPORT_HALO_PX = 4

#: Maximum mean |Δ| between the observed region and the role reference for a
#: match to be claimed at all; beyond it the match is a TYPED UNKNOWN.
DEFAULT_MATCH_MAX_DISTANCE = 24.0

#: Factor the best reference distance must beat the runner-up by, otherwise
#: two roles are equally supported and the match is a TYPED UNKNOWN.
DEFAULT_MATCH_MARGIN = 2.0

#: Hard bound on how many output frames one observation pass decodes.
DEFAULT_MAX_DECODE_FRAMES = 600


class RenderedObservationsError(ValueError):
    """Typed fail-closed error for output-observation work (local codes)."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


# ── canonical serialisation + frame identity ─────────────────────────────────


def canonical_json(payload: Any) -> str:
    """Canonical JSON (sorted keys, no whitespace, ASCII) — byte-stable."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_sha256(payload: Any) -> str:
    """sha256 of the canonical JSON encoding of ``payload``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _gray(value: Any, *, code: str = CODE_OBSERVATION_INVALID) -> np.ndarray:
    """Decode one decoded frame/mask payload to a 2-D float64 matrix."""
    array = np.asarray(value)
    if array.ndim != 2 or array.size == 0:
        raise RenderedObservationsError(
            code,
            f"pixel payload has shape {array.shape}; a 2-D decoded frame is "
            "required to observe the rendered output",
        )
    return array.astype(np.float64)


def frame_digest(frame: Any) -> str:
    """Content digest of one decoded output frame: shape header + gray bytes.

    The shape is inside the hashed payload so a reshape cannot collide, and
    the digest is computed from the DECODED OUTPUT bytes this pass ran on.
    """
    array = _gray(frame)
    height, width = int(array.shape[0]), int(array.shape[1])
    header = b"ROF1" + width.to_bytes(4, "little") + height.to_bytes(4, "little")
    payload = np.ascontiguousarray(array.astype(np.uint8)).tobytes()
    return hashlib.sha256(header + payload).hexdigest()


def frame_map_sha256(frames: Mapping[int, Any]) -> str:
    """Digest of the whole decoded frame map (index → frame content digest).

    Binds the sealed artifact to the exact decoded output frame space: a
    reviewer re-decodes the artifact and recomputes this value.
    """
    return payload_sha256(
        {str(int(index)): frame_digest(frames[index]) for index in sorted(frames)}
    )


def decode_output_frame_map(
    path: Path,
    indices: Sequence[int],
    *,
    detector: str = OBSERVATIONS_DETECTOR,
    max_frames: int = DEFAULT_MAX_DECODE_FRAMES,
) -> dict[int, np.ndarray]:
    """Decode specific frames of the OUTPUT artifact as 2-D gray matrices.

    Every requested index is decoded explicitly (no sampling): the caller's
    segment spans decide which frames carry observations.  Indices that do
    not decode are OMITTED — the builder refuses a span with a missing frame
    instead of silently skipping it.  Bounded by ``max_frames``.
    """
    wanted = sorted({int(i) for i in indices})
    if not wanted:
        return {}
    if len(wanted) > int(max_frames):
        raise RenderedObservationsError(
            CODE_FRAME_MAP_INVALID,
            f"requested {len(wanted)} frames but the decode bound is "
            f"{int(max_frames)}; refusing an unbounded output decode",
        )
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RenderedObservationsError(
            CODE_OUTPUT_INVALID,
            f"output artifact {path.name!r} cannot be decoded (no readable "
            "video stream)",
        )
    out: dict[int, np.ndarray] = {}
    try:
        for index in wanted:
            capture.set(cv2.CAP_PROP_POS_FRAMES, float(index))
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            gray = (
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if frame.ndim == 3
                else np.asarray(frame)
            )
            out[index] = np.asarray(gray, dtype=np.uint8)
    finally:
        capture.release()
    if not out:
        raise RenderedObservationsError(
            CODE_OUTPUT_INVALID,
            f"no frame of output artifact {path.name!r} decoded for the "
            f"requested indices {wanted[:5]}",
        )
    return out


# ── data model ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderedOutput:
    """The RESOLVED render artifact this observation pass measures."""

    artifact_id: str
    sha256: str
    size_bytes: int
    relative_path: str
    #: Resolution role: ``publication`` / ``owned_result_artifact`` (a render)
    #: — ``source_fallback_no_render`` never reaches the builder.
    role: str
    width: int
    height: int
    frame_count: int
    source_artifact_id: str | None
    source_sha256: str
    producer: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "size_bytes": int(self.size_bytes),
            "relative_path": self.relative_path,
            "role": self.role,
            "width": int(self.width),
            "height": int(self.height),
            "frame_count": int(self.frame_count),
            "source_artifact_id": self.source_artifact_id,
            "source_sha256": self.source_sha256,
            "producer": self.producer,
            "facts": dict(self.facts),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RenderedOutput:
        return cls(
            artifact_id=str(payload["artifact_id"]),
            sha256=str(payload["sha256"]),
            size_bytes=int(payload["size_bytes"]),
            relative_path=str(payload["relative_path"]),
            role=str(payload["role"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            frame_count=int(payload["frame_count"]),
            source_artifact_id=(
                str(payload["source_artifact_id"])
                if payload.get("source_artifact_id") is not None
                else None
            ),
            source_sha256=str(payload.get("source_sha256", "")),
            producer=str(payload.get("producer", "")),
            facts=dict(payload.get("facts", {})),
        )


@dataclass(frozen=True)
class RenderedSegment:
    """One declared role/instance span on the OUTPUT frame space.

    The span and the (optional) search window come from persisted evidence
    (the occurrence segment + its published mask bbox): the annotation says
    WHERE to look, the output pixels say WHAT is there.
    """

    segment_id: str
    role_id: str
    kind: str
    start_frame: int
    end_frame: int  # exclusive
    window: tuple[int, int, int, int] | None = None  # (x0, y0, x1, y1)
    note: str = ""

    def validate(self) -> None:
        if not self.segment_id or not self.role_id:
            raise RenderedObservationsError(
                CODE_SEGMENT_INVALID,
                f"segment_id/role_id must be non-empty: {self.segment_id!r}/"
                f"{self.role_id!r}",
            )
        if self.kind not in (srt.ROLE_KIND_PERSON, srt.ROLE_KIND_PROP):
            raise RenderedObservationsError(
                CODE_SEGMENT_INVALID, f"kind must be person|prop: {self.kind!r}"
            )
        if int(self.start_frame) < 0 or int(self.end_frame) <= int(self.start_frame):
            raise RenderedObservationsError(
                CODE_SEGMENT_INVALID,
                f"span must be [start, end) with 0 <= start < end: "
                f"[{self.start_frame}, {self.end_frame})",
            )
        if self.window is not None:
            if len(self.window) != 4 or any(int(v) < 0 for v in self.window):
                raise RenderedObservationsError(
                    CODE_SEGMENT_INVALID,
                    f"window must be 4 non-negative ints: {self.window!r}",
                )
            if int(self.window[2]) <= int(self.window[0]) or int(self.window[3]) <= int(
                self.window[1]
            ):
                raise RenderedObservationsError(
                    CODE_SEGMENT_INVALID, f"window must be non-empty: {self.window!r}"
                )

    def to_payload(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "role_id": self.role_id,
            "kind": self.kind,
            "start_frame": int(self.start_frame),
            "end_frame": int(self.end_frame),
            "window": list(self.window) if self.window is not None else None,
            "note": self.note,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RenderedSegment:
        window = payload.get("window")
        return cls(
            segment_id=str(payload["segment_id"]),
            role_id=str(payload["role_id"]),
            kind=str(payload["kind"]),
            start_frame=int(payload["start_frame"]),
            end_frame=int(payload["end_frame"]),
            window=tuple(int(v) for v in window) if window is not None else None,
            note=str(payload.get("note", "")),
        )


@dataclass(frozen=True)
class RenderedReference:
    """The ROLE's published reference pixels (the identity authority).

    ``frame`` is the decoded 2-D gray matrix of the pinned cast reference
    artifact — never a crop of the video's own source frames.
    """

    role_id: str
    artifact_id: str
    sha256: str
    frame: Any
    pose_slot: str = ""

    def to_payload(self) -> dict[str, Any]:
        array = np.asarray(self.frame)
        return {
            "role_id": self.role_id,
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "pose_slot": self.pose_slot,
            "shape": [int(array.shape[0]), int(array.shape[1])],
        }


@dataclass(frozen=True)
class EngineRecord:
    """Which extractor produced the output masks, with its REAL probe facts."""

    engine_id: str
    provenance: str
    probe: Mapping[str, Any] | None
    probe_digest: str | None
    params: Mapping[str, Any]
    params_digest: str
    candidates: Mapping[str, str]
    inference_ran: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "provenance": self.provenance,
            "probe": dict(self.probe) if self.probe is not None else None,
            "probe_digest": self.probe_digest,
            "params": dict(self.params),
            "params_digest": self.params_digest,
            "candidates": dict(self.candidates),
            "inference_ran": bool(self.inference_ran),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> EngineRecord:
        return cls(
            engine_id=str(payload["engine_id"]),
            provenance=str(payload["provenance"]),
            probe=dict(payload["probe"]) if payload.get("probe") is not None else None,
            probe_digest=payload.get("probe_digest"),
            params=dict(payload.get("params", {})),
            params_digest=str(payload.get("params_digest", "")),
            candidates=dict(payload.get("candidates", {})),
            inference_ran=bool(payload.get("inference_ran", False)),
        )


@dataclass(frozen=True)
class RenderedTrack:
    """One role/instance tracked across the declared output span."""

    segment_id: str
    role_id: str
    kind: str
    instance_id: str
    start_frame: int
    end_frame: int
    observations: tuple[dict[str, Any], ...]
    occlusion_runs: tuple[dict[str, int], ...]
    partial_frames: tuple[int, ...]
    out_of_frame_frames: tuple[int, ...]
    gap_frames: tuple[int, ...]
    flags: tuple[dict[str, Any], ...]
    stability: Mapping[str, Any]
    role_match: Mapping[str, Any]
    trace_complete: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "role_id": self.role_id,
            "kind": self.kind,
            "instance_id": self.instance_id,
            "start_frame": int(self.start_frame),
            "end_frame": int(self.end_frame),
            "observations": [dict(item) for item in self.observations],
            "occlusion_runs": [dict(run) for run in self.occlusion_runs],
            "partial_frames": list(self.partial_frames),
            "out_of_frame_frames": list(self.out_of_frame_frames),
            "gap_frames": list(self.gap_frames),
            "flags": [dict(flag) for flag in self.flags],
            "stability": dict(self.stability),
            "role_match": dict(self.role_match),
            "trace_complete": bool(self.trace_complete),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RenderedTrack:
        return cls(
            segment_id=str(payload["segment_id"]),
            role_id=str(payload["role_id"]),
            kind=str(payload["kind"]),
            instance_id=str(payload["instance_id"]),
            start_frame=int(payload["start_frame"]),
            end_frame=int(payload["end_frame"]),
            observations=tuple(dict(item) for item in payload.get("observations", [])),
            occlusion_runs=tuple(dict(run) for run in payload.get("occlusion_runs", [])),
            partial_frames=tuple(int(v) for v in payload.get("partial_frames", [])),
            out_of_frame_frames=tuple(
                int(v) for v in payload.get("out_of_frame_frames", [])
            ),
            gap_frames=tuple(int(v) for v in payload.get("gap_frames", [])),
            flags=tuple(dict(item) for item in payload.get("flags", [])),
            stability=dict(payload.get("stability", {})),
            role_match=dict(payload.get("role_match", {})),
            trace_complete=bool(payload.get("trace_complete", False)),
        )


@dataclass(frozen=True)
class TrackRefusal:
    """A declared segment that produced no usable output track."""

    segment_id: str
    role_id: str
    code: str
    detail: str = ""

    def to_payload(self) -> dict[str, str]:
        return {
            "segment_id": self.segment_id,
            "role_id": self.role_id,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RenderedObservationsArtifact:
    """Sealed output-side observation record: track + role + render SHA."""

    schema_version: str
    output: Mapping[str, Any]
    source_sha256: str
    source_tracks_digest: str | None
    fps_rational: str
    span: Mapping[str, int]
    frame_size: tuple[int, int]
    frame_map_digest: str
    engine: EngineRecord
    segments: tuple[RenderedSegment, ...]
    tracks: tuple[RenderedTrack, ...]
    refused_tracks: tuple[TrackRefusal, ...]
    flags: tuple[dict[str, Any], ...]
    production: bool
    digest: str
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "output": dict(self.output),
            "source_sha256": self.source_sha256,
            "source_tracks_digest": self.source_tracks_digest,
            "fps_rational": self.fps_rational,
            "span": dict(self.span),
            "frame_size": [int(self.frame_size[0]), int(self.frame_size[1])],
            "frame_map_digest": self.frame_map_digest,
            "engine": self.engine.to_payload(),
            "segments": [segment.to_payload() for segment in self.segments],
            "tracks": [track.to_payload() for track in self.tracks],
            "refused_tracks": [item.to_payload() for item in self.refused_tracks],
            "flags": [dict(flag) for flag in self.flags],
            "production": bool(self.production),
            "extra": dict(self.extra),
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload

    def payload_without_digest(self) -> dict[str, Any]:
        return self.to_payload(include_digest=False)

    def recompute_digest(self) -> str:
        return payload_sha256(self.payload_without_digest())

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RenderedObservationsArtifact:
        version = str(payload.get("schema_version", ""))
        if version != OBSERVATIONS_SCHEMA_VERSION:
            raise RenderedObservationsError(
                CODE_VERSION_UNSUPPORTED,
                f"artifact version {version!r} is not "
                f"{OBSERVATIONS_SCHEMA_VERSION!r}",
            )
        try:
            artifact = cls(
                schema_version=version,
                output=dict(payload["output"]),
                source_sha256=str(payload.get("source_sha256", "")),
                source_tracks_digest=payload.get("source_tracks_digest"),
                fps_rational=str(payload["fps_rational"]),
                span={
                    "start_frame": int(payload["span"]["start_frame"]),
                    "end_frame_exclusive": int(payload["span"]["end_frame_exclusive"]),
                },
                frame_size=tuple(int(v) for v in payload["frame_size"]),
                frame_map_digest=str(payload.get("frame_map_digest", "")),
                engine=EngineRecord.from_payload(payload["engine"]),
                segments=tuple(
                    RenderedSegment.from_payload(segment)
                    for segment in payload.get("segments", [])
                ),
                tracks=tuple(
                    RenderedTrack.from_payload(track)
                    for track in payload.get("tracks", [])
                ),
                refused_tracks=tuple(
                    TrackRefusal(
                        str(item["segment_id"]),
                        str(item["role_id"]),
                        str(item["code"]),
                        str(item.get("detail", "")),
                    )
                    for item in payload.get("refused_tracks", [])
                ),
                flags=tuple(dict(item) for item in payload.get("flags", [])),
                production=bool(payload.get("production", False)),
                digest=str(payload.get("digest", "")),
                extra=dict(payload.get("extra", {})),
            )
        except RenderedObservationsError:
            raise
        except (KeyError, TypeError, ValueError) as err:
            raise RenderedObservationsError(
                CODE_SERIALIZATION_INVALID, f"artifact payload unreadable: {err}"
            ) from err
        expected = artifact.recompute_digest()
        if expected != artifact.digest:
            raise RenderedObservationsError(
                CODE_DIGEST_MISMATCH,
                f"artifact digest {artifact.digest} != recomputed {expected}",
            )
        return artifact


# ── engine protocol + the shipped CI engine ──────────────────────────────────


class OutputMaskEngine(Protocol):
    """Injected output-side extractor (real inference or a real CI computer).

    ``sample`` answers ONE frame of the OUTPUT: the frame passed in is the
    decoded output frame, and any mask returned is a claim about THAT frame's
    pixels — the builder measures the claim before accepting it.
    """

    engine_id: str
    provenance: str
    probe: Mapping[str, Any] | None
    params: Mapping[str, Any]
    candidates: Mapping[str, str]
    inference_ran: bool

    def sample(
        self, frame_index: int, segment: RenderedSegment, frame: np.ndarray
    ) -> srt.MaskSample | None:
        """Answer for one frame; ``None`` means "no observation available"."""


@dataclass
class LevelComponentMaskSource:
    """CI-pixel engine: the output's OWN painted component inside the window.

    Documented deterministic rule (no fabricated mask): inside the segment's
    window the instance is the LARGEST connected component of the pixels that
    differ from the frame's OWN dominant grey level (``background_level`` —
    measured on the decoded output frame, never a constant).  When the window
    holds no such pixel the answer is ``present=False`` (the output paints
    nothing there) — never a mask from somewhere else.

    The provenance is a CI fixture: this engine's answers are computed from
    real output pixels, but it carries no capability probe, so it can never
    be recorded as a production engine (``require_production`` refuses it).
    """

    engine_id: str = "output_level_component"
    provenance: str = PROVENANCE_FIXTURE
    probe: Mapping[str, Any] | None = None
    params: Mapping[str, Any] = field(
        default_factory=lambda: {
            "rule": "largest_connected_component_of_pixels_differing_from_"
            "the_output_frames_own_dominant_grey_level_inside_the_segment_window",
            "connectivity": 8,
            "window_mode": "segment_window_else_full_frame",
        }
    )
    candidates: Mapping[str, Any] = field(default_factory=dict)
    inference_ran: bool = False

    def sample(
        self, frame_index: int, segment: RenderedSegment, frame: np.ndarray
    ) -> srt.MaskSample | None:
        array = _gray(frame)
        level = obs.background_level(array, detector=OBSERVATIONS_DETECTOR)
        painted = np.abs(array - level) > 0.0
        window = segment.window
        if window is not None:
            height, width = array.shape
            x0, y0, x1, y1 = (int(v) for v in window)
            x0, x1 = max(0, min(x0, width)), max(0, min(x1, width))
            y0, y1 = max(0, min(y0, height)), max(0, min(y1, height))
            bounded = np.zeros_like(painted)
            bounded[y0:y1, x0:x1] = painted[y0:y1, x0:x1]
            painted = bounded
        if not painted.any():
            return srt.MaskSample(
                mask=None, method=f"{self.engine_id}:nothing_painted", present=False
            )
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            painted.astype(np.uint8), connectivity=8
        )
        best_label, best_area = 0, 0
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area > best_area:
                best_label, best_area = label, area
        if best_label == 0:
            return srt.MaskSample(
                mask=None, method=f"{self.engine_id}:nothing_painted", present=False
            )
        return srt.MaskSample(
            mask=(labels == best_label), method=f"{self.engine_id}:largest_component"
        )


# ── measured rules ───────────────────────────────────────────────────────────


def _permission(
    stats: Mapping[str, Any],
    *,
    all_canvas_ratio: float,
    hollow_ratio: float,
    min_area_px: int,
) -> tuple[str, str | None, str]:
    """Derive (permission, denial_code, visibility_state) from measured stats.

    Order is fixed and fail-closed: empty → all-canvas → hollow → granted.
    Identical to the source side's rule; the codes are this module's own.
    """
    area = int(stats.get("area_px") or 0)
    if area < max(0, int(min_area_px)):
        return "denied", CODE_MASK_EMPTY, "visible"
    coverage = float(stats.get("coverage_ratio") or 0.0)
    if coverage >= float(all_canvas_ratio):
        return "denied", CODE_MASK_ALL_CANVAS, "visible"
    hole = stats.get("hole_ratio")
    if hole is not None and float(hole) >= float(hollow_ratio):
        return "denied", CODE_MASK_HOLLOW, "visible"
    state = "partial" if stats.get("border_touch") else "visible"
    return "granted", None, state


def _window_wh(window: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    """Convert a half-open (x0, y0, x1, y1) window to (x, y, width, height)."""
    if window is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in window)
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def _centroid(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.nonzero(np.asarray(mask).astype(bool))
    if xs.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def _region_rms(left: Any, right: Any, *, window: tuple[int, int, int, int]) -> float:
    """Mean |Δ| between two frames inside one measured window (same geometry)."""
    a = _gray(left)
    b = _gray(right)
    if a.shape != b.shape:
        raise RenderedObservationsError(
            CODE_REFERENCE_INVALID,
            f"frames {a.shape} and {b.shape} have different geometry; the "
            "match cannot be measured under one window",
        )
    height, width = a.shape
    x0, y0, x1, y1 = (int(v) for v in window)
    x0, x1 = max(0, min(x0, width)), max(0, min(x1, width))
    y0, y1 = max(0, min(y0, height)), max(0, min(y1, height))
    if x1 <= x0 or y1 <= y0:
        raise RenderedObservationsError(
            CODE_REFERENCE_INVALID, f"match window {window!r} is empty"
        )
    delta = np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1])
    return round(float(delta.mean()), 9)


def _match_role(
    *,
    frame: np.ndarray,
    observation: Mapping[str, Any],
    declared_role_id: str,
    references: Mapping[str, RenderedReference],
    max_distance: float,
    margin: float,
) -> dict[str, Any]:
    """Match one measured output instance to a role through reference pixels.

    The comparison window is the instance's MEASURED bbox on the output; the
    reference is cropped under the same window (the same-canvas geometry the
    source side uses).  The result is ``matched`` only when exactly one role
    is supported: a best distance beyond ``max_distance``, or a runner-up
    within ``margin`` × the best, is a TYPED UNKNOWN — never a guess.
    """
    bbox = observation.get("bbox")
    base: dict[str, Any] = {
        "declared_role_id": declared_role_id,
        "role_id": None,
        "state": MATCH_UNKNOWN,
        "reason": UNKNOWN_REASON_NO_REFERENCE,
        "distances": {},
        "best_distance": None,
        "runner_up_distance": None,
        "match_max_distance": float(max_distance),
        "match_margin": float(margin),
        "window": list(observation["window"]) if observation.get("window") else None,
        "frame": int(observation["frame"]),
        "reference_frames": {
            role_id: reference.to_payload() for role_id, reference in references.items()
        },
        "measure": "mean|Δ| between the tracked region's OUTPUT pixels and the "
        "role's published reference pixels under the same measured bbox "
        "window; temporal continuity = the declared segment span",
    }
    if not references:
        return base
    if not bbox:
        base["reason"] = UNKNOWN_REASON_UNMATCHED
        base["detail"] = "the observation carries no measured bbox"
        return base
    x0, y0 = int(bbox[0]), int(bbox[1])
    width, height = int(bbox[2]), int(bbox[3])
    window = (x0, y0, x0 + width, y0 + height)
    distances: dict[str, float] = {}
    for role_id, reference in sorted(references.items()):
        distances[role_id] = _region_rms(frame, reference.frame, window=window)
    base["distances"] = distances
    base["window"] = [int(v) for v in window]
    ordered = sorted(distances.items(), key=lambda item: (item[1], item[0]))
    best_role, best = ordered[0]
    runner = ordered[1][1] if len(ordered) > 1 else None
    base["best_distance"] = float(best)
    base["runner_up_distance"] = float(runner) if runner is not None else None
    if best > float(max_distance):
        base["reason"] = UNKNOWN_REASON_UNMATCHED
        base["nearest_role_id"] = best_role
        return base
    if runner is not None and float(runner) <= float(best) * float(margin):
        base["reason"] = UNKNOWN_REASON_AMBIGUOUS
        base["tied_role_ids"] = [
            role_id for role_id, value in ordered if float(value) <= float(best) * float(margin)
        ]
        return base
    base["state"] = MATCH_MATCHED
    base["reason"] = None
    base["role_id"] = best_role
    base["agrees_with_declared_role"] = best_role == declared_role_id
    return base


def _stability(
    observations: Sequence[Mapping[str, Any]],
    *,
    shift_ratio: float,
    area_jump_ratio: float,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Measured temporal continuity of one output track.

    Consecutive observed frames are linked through their measured centroids
    and areas; a link whose centroid step exceeds ``shift_ratio`` ×
    sqrt(mean area), or whose area jumps by ``area_jump_ratio``, is recorded
    as an unstable link (flag), never silently smoothed.
    """
    areas = [int(item["area_px"]) for item in observations]
    mean_area = float(np.mean(areas)) if areas else 0.0
    max_step = 0.0
    unstable: list[dict[str, Any]] = []
    previous: Mapping[str, Any] | None = None
    for item in observations:
        if previous is not None:
            left = previous.get("centroid")
            right = item.get("centroid")
            if left is not None and right is not None:
                shift = float(
                    np.hypot(float(right[0]) - float(left[0]), float(right[1]) - float(left[1]))
                )
                max_step = max(max_step, shift)
                threshold = float(shift_ratio) * float(np.sqrt(max(mean_area, 1.0)))
                ratio = (
                    max(int(item["area_px"]), 1) / max(int(previous["area_px"]), 1)
                )
                ratio = max(ratio, 1.0 / ratio)
                if shift > threshold or ratio > float(area_jump_ratio):
                    unstable.append(
                        {
                            "frame": int(item["frame"]),
                            "shift_px": round(shift, 9),
                            "shift_threshold_px": round(threshold, 9),
                            "area_ratio": round(ratio, 9),
                        }
                    )
        previous = item
    stability = {
        "observed_frames": len(observations),
        "first_frame": int(observations[0]["frame"]) if observations else None,
        "last_frame": int(observations[-1]["frame"]) if observations else None,
        "mean_area_px": round(mean_area, 9),
        "min_area_px": int(min(areas)) if areas else 0,
        "max_area_px": int(max(areas)) if areas else 0,
        "max_step_shift_px": round(max_step, 9),
        "unstable_links": unstable,
    }
    flags = tuple(
        {
            "code": FLAG_UNSTABLE_LINK,
            "frame": int(link["frame"]),
            "detail": f"unstable link shift={link['shift_px']}px "
            f"area_ratio={link['area_ratio']}",
        }
        for link in unstable
    )
    return stability, flags


# ── production gate ──────────────────────────────────────────────────────────


def require_production(engine: EngineRecord) -> None:
    """Refuse a CI-fixture engine (or an unprobed production claim)."""
    if engine.provenance != PROVENANCE_PRODUCTION:
        raise RenderedObservationsError(
            CODE_FIXTURE_NOT_PRODUCTION,
            f"engine provenance {engine.provenance!r} is a CI fixture; "
            "fixtures never count as production observations",
        )
    if engine.probe is None or not engine.probe_digest:
        raise RenderedObservationsError(
            CODE_ENGINE_UNPROBED,
            f"engine {engine.engine_id!r} has no real capability probe record",
        )
    status = str(dict(engine.probe).get("status", ""))
    if status != srt.STATUS_PROBED_READY:
        raise RenderedObservationsError(
            CODE_ENGINE_UNPROBED,
            f"engine probe status {status!r} is not {srt.STATUS_PROBED_READY!r}",
        )
    if not engine.inference_ran:
        raise RenderedObservationsError(
            CODE_ENGINE_UNPROBED,
            f"engine {engine.engine_id!r} is recorded as applied but "
            "inference did not run",
        )
    if not engine.params or not engine.params_digest:
        raise RenderedObservationsError(
            CODE_ENGINE_UNPROBED,
            f"engine {engine.engine_id!r} records no extractor params; an "
            "observation whose extractor parameters are unknown cannot be "
            "reproduced and is not admissible",
        )


# ── the builder ──────────────────────────────────────────────────────────────


def build_rendered_observations(
    *,
    output: RenderedOutput,
    frames: Mapping[int, Any],
    segments: Sequence[RenderedSegment],
    engine: OutputMaskEngine,
    fps_rational: str,
    references: Mapping[str, RenderedReference] | None = None,
    source_tracks_digest: str | None = None,
    production: bool = False,
    all_canvas_ratio: float = DEFAULT_ALL_CANVAS_RATIO,
    hollow_ratio: float = DEFAULT_HOLLOW_RATIO,
    min_area_px: int = DEFAULT_MIN_AREA_PX,
    support_halo_px: int = DEFAULT_SUPPORT_HALO_PX,
    match_max_distance: float = DEFAULT_MATCH_MAX_DISTANCE,
    match_margin: float = DEFAULT_MATCH_MARGIN,
    shift_ratio: float = DEFAULT_SHIFT_RATIO,
    area_jump_ratio: float = DEFAULT_AREA_JUMP_RATIO,
    strict: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> RenderedObservationsArtifact:
    """Build the sealed output-side observation artifact from REAL frames.

    Fail-closed rules (each with its own typed code):

    * a resolved artifact that is not a render, or whose bytes ARE the
      source's bytes, refuses (``CODE_OUTPUT_NOT_RENDER`` /
      ``CODE_OUTPUT_IS_SOURCE``) — the intended source is never dressed as an
      output observation;
    * the decoded map must carry exactly the declared frame count and the
      video's measured canvas (``CODE_FRAME_MAP_INVALID`` /
      ``CODE_GEOMETRY_MISMATCH``);
    * every frame of a declared segment span must decode
      (``CODE_FRAME_NOT_OBSERVED``); a segment with NO usable observation is a
      recorded refusal (strict: raises ``CODE_NO_TRACE``);
    * a claimed mask must be measurable on the output frame: empty /
      all-canvas / hollow masks and masks whose pixels have NO separation from
      their surrounding ring refuse
      (``CODE_MASK_EMPTY`` / ``CODE_MASK_ALL_CANVAS`` / ``CODE_MASK_HOLLOW`` /
      ``CODE_SUPPORT_AMBIGUOUS``);
    * role matching is a TYPED UNKNOWN when ambiguous / unsupported — the
      declared role is recorded, never silently substituted;
    * ``production=True`` requires a probed, actually-run engine.
    """
    references = dict(references or {})
    if not output.sha256 or len(str(output.sha256)) != 64:
        raise RenderedObservationsError(
            CODE_OUTPUT_INVALID,
            f"output sha256 must be 64 hex chars: {output.sha256!r}",
        )
    if output.role not in RENDER_ROLES:
        raise RenderedObservationsError(
            CODE_OUTPUT_NOT_RENDER,
            f"resolved artifact role {output.role!r} is not a rendered output "
            f"(render roles: {list(RENDER_ROLES)}); the current result being "
            "the imported source cannot be observed as an output",
        )
    if str(output.sha256).lower() == str(output.source_sha256 or "").lower():
        raise RenderedObservationsError(
            CODE_OUTPUT_IS_SOURCE,
            "the resolved output artifact's bytes ARE the imported source "
            "artifact's bytes: observing them would present the intended "
            "source as an output observation",
        )
    parse_rational(fps_rational, what="fps")
    if int(output.frame_count) <= 0:
        raise RenderedObservationsError(
            CODE_FRAME_MAP_INVALID,
            f"the output declares frame_count={output.frame_count}; the frame "
            "map cannot be verified (fail closed)",
        )
    if len(frames) != int(output.frame_count):
        raise RenderedObservationsError(
            CODE_FRAME_MAP_INVALID,
            f"decoded frame map carries {len(frames)} frames but the output "
            f"artifact declares {output.frame_count}",
        )
    expected_shape = (int(output.height), int(output.width))
    decoded: dict[int, np.ndarray] = {}
    for index in sorted(frames):
        array = _gray(frames[index])
        if array.shape != expected_shape:
            raise RenderedObservationsError(
                CODE_GEOMETRY_MISMATCH,
                f"decoded output frame {index} is {array.shape} but the "
                f"video's measured canvas is {expected_shape} (height, width)",
            )
        decoded[int(index)] = array
    if not segments:
        raise RenderedObservationsError(
            CODE_SEGMENT_INVALID,
            "no declared segment spans were supplied; an output observation "
            "without a role/frame declaration cannot be published",
        )
    seen: set[str] = set()
    for segment in segments:
        segment.validate()
        if segment.segment_id in seen:
            raise RenderedObservationsError(
                CODE_SEGMENT_INVALID,
                f"segment {segment.segment_id!r} is declared twice",
            )
        seen.add(segment.segment_id)
    engine_record = EngineRecord(
        engine_id=str(engine.engine_id),
        provenance=str(engine.provenance),
        probe=dict(engine.probe) if engine.probe is not None else None,
        probe_digest=(
            payload_sha256(dict(engine.probe)) if engine.probe is not None else None
        ),
        params=dict(engine.params),
        params_digest=payload_sha256(dict(engine.params)),
        candidates=dict(engine.candidates),
        inference_ran=bool(engine.inference_ran),
    )
    tracks: list[RenderedTrack] = []
    refusals: list[TrackRefusal] = []
    for segment in segments:
        indices = list(range(int(segment.start_frame), int(segment.end_frame)))
        missing = [index for index in indices if index not in decoded]
        if missing:
            raise RenderedObservationsError(
                CODE_FRAME_NOT_OBSERVED,
                f"segment {segment.segment_id!r} declares frames "
                f"{missing[:5]}{'...' if len(missing) > 5 else ''} that the "
                f"decoded output does not carry (map holds "
                f"{min(decoded)}..{max(decoded)}); a wrong-frame declaration "
                "cannot be observed",
            )
        instance_id = f"obs:{str(output.sha256)[:12]}:{segment.segment_id}"
        observations: list[dict[str, Any]] = []
        partial_frames: list[int] = []
        out_of_frame: list[int] = []
        gap_frames: list[int] = []
        occlusion_runs: list[dict[str, int]] = []
        run_start: int | None = None
        for index in indices:
            frame = decoded[index]
            sample = engine.sample(index, segment, frame)
            if sample is None:
                gap_frames.append(index)
                continue
            if not bool(sample.present):
                if bool(sample.out_of_frame):
                    out_of_frame.append(index)
                else:
                    gap_frames.append(index)
                continue
            if sample.mask is None:
                if run_start is None:
                    run_start = index
                continue
            if run_start is not None:
                occlusion_runs.append({"start_frame": run_start, "end_frame": index})
                run_start = None
            mask = np.asarray(sample.mask).astype(bool)
            if mask.ndim != 2 or mask.shape != frame.shape:
                raise RenderedObservationsError(
                    CODE_OBSERVATION_INVALID,
                    f"frame {index}: engine mask shape {mask.shape} does not "
                    f"match the output frame {frame.shape}",
                )
            stats = srt.mask_stats(mask, seed_box=_window_wh(segment.window))
            permission, denial, state = _permission(
                stats,
                all_canvas_ratio=all_canvas_ratio,
                hollow_ratio=hollow_ratio,
                min_area_px=min_area_px,
            )
            if permission != "granted" or denial is not None:
                raise RenderedObservationsError(
                    denial or CODE_MASK_EMPTY,
                    f"frame {index}: the claimed output mask is not usable "
                    f"(area={stats.get('area_px')}px "
                    f"coverage={stats.get('coverage_ratio')} "
                    f"hole_ratio={stats.get('hole_ratio')})",
                )
            support = obs.mask_support_separation(
                frame, mask, halo_px=support_halo_px, detector=OBSERVATIONS_DETECTOR
            )
            separation = support.get("separation")
            if separation is None or float(separation) <= 0.0:
                raise RenderedObservationsError(
                    CODE_SUPPORT_AMBIGUOUS,
                    f"frame {index}: the claimed output mask has no pixel "
                    f"support — its inside and surrounding ring have the same "
                    f"measured appearance (inside={support.get('inside_mean')} "
                    f"outside={support.get('outside_mean')}); a mask the "
                    "output does not paint is not an observation of it",
                )
            if state == "partial":
                partial_frames.append(index)
            centroid = _centroid(mask)
            observations.append(
                {
                    "frame": int(index),
                    "instance_id": instance_id,
                    "state": state,
                    "mask_digest": srt.mask_digest(mask),
                    "method": str(sample.method),
                    "score": float(sample.score) if sample.score is not None else None,
                    "area_px": int(stats.get("area_px") or 0),
                    "coverage_ratio": round(float(stats.get("coverage_ratio") or 0.0), 9),
                    "bbox": [int(v) for v in stats["bbox"]] if stats.get("bbox") else None,
                    "border_touch": bool(stats.get("border_touch")),
                    "solidity": (
                        round(float(stats["solidity"]), 9)
                        if stats.get("solidity") is not None
                        else None
                    ),
                    "hole_ratio": (
                        round(float(stats["hole_ratio"]), 9)
                        if stats.get("hole_ratio") is not None
                        else None
                    ),
                    "centroid": [round(centroid[0], 9), round(centroid[1], 9)]
                    if centroid
                    else None,
                    "support": {
                        "separation": separation,
                        "inside_mean": support.get("inside_mean"),
                        "outside_mean": support.get("outside_mean"),
                        "halo_px": support.get("halo_px"),
                        "inside_px": support.get("inside_px"),
                        "ring_px": support.get("ring_px"),
                    },
                    "seed_window": list(segment.window) if segment.window else None,
                    "measure": "mask measured on the decoded pixels of the "
                    "RENDER output frame; support = separation from the "
                    "surrounding ring on the same frame",
                }
            )
        if run_start is not None:
            occlusion_runs.append(
                {"start_frame": run_start, "end_frame": int(segment.end_frame)}
            )
        if not observations:
            refusal = TrackRefusal(
                segment_id=segment.segment_id,
                role_id=segment.role_id,
                code=CODE_NO_TRACE,
                detail="no frame of the declared span produced a usable "
                "output mask (the output does not paint this instance)",
            )
            if strict:
                raise RenderedObservationsError(
                    CODE_NO_TRACE,
                    f"segment {segment.segment_id!r}: {refusal.detail}",
                )
            refusals.append(refusal)
            continue
        stability, link_flags = _stability(
            observations, shift_ratio=shift_ratio, area_jump_ratio=area_jump_ratio
        )
        anchor = max(observations, key=lambda item: (int(item["area_px"]), -int(item["frame"])))
        role_match = _match_role(
            frame=decoded[int(anchor["frame"])],
            observation=anchor,
            declared_role_id=segment.role_id,
            references=references,
            max_distance=match_max_distance,
            margin=match_margin,
        )
        tracks.append(
            RenderedTrack(
                segment_id=segment.segment_id,
                role_id=segment.role_id,
                kind=segment.kind,
                instance_id=instance_id,
                start_frame=int(segment.start_frame),
                end_frame=int(segment.end_frame),
                observations=tuple(observations),
                occlusion_runs=tuple(occlusion_runs),
                partial_frames=tuple(partial_frames),
                out_of_frame_frames=tuple(out_of_frame),
                gap_frames=tuple(gap_frames),
                flags=tuple(link_flags),
                stability=stability,
                role_match=role_match,
                trace_complete=not gap_frames and not out_of_frame,
            )
        )
    span_start = min(int(segment.start_frame) for segment in segments)
    span_end = max(int(segment.end_frame) for segment in segments)
    artifact = RenderedObservationsArtifact(
        schema_version=OBSERVATIONS_SCHEMA_VERSION,
        output=output.to_payload(),
        source_sha256=str(output.source_sha256 or "").lower(),
        source_tracks_digest=(
            str(source_tracks_digest) if source_tracks_digest else None
        ),
        fps_rational=str(fps_rational),
        span={"start_frame": span_start, "end_frame_exclusive": span_end},
        frame_size=(int(output.width), int(output.height)),
        frame_map_digest=frame_map_sha256(decoded),
        engine=engine_record,
        segments=tuple(segments),
        tracks=tuple(tracks),
        refused_tracks=tuple(refusals),
        flags=(),
        production=bool(production),
        digest="",
        extra=dict(extra or {}),
    )
    if production:
        require_production(artifact.engine)
    artifact = _reseal(artifact)
    violations = check_artifact(artifact)
    if violations:
        raise RenderedObservationsError(
            CODE_OBSERVATION_INVALID,
            f"built artifact violates its own contract: {list(violations)[:5]}",
        )
    return artifact


def _reseal(artifact: RenderedObservationsArtifact) -> RenderedObservationsArtifact:
    """Return a copy of ``artifact`` whose digest covers its current payload."""
    digests = artifact.recompute_digest()
    return RenderedObservationsArtifact(
        schema_version=artifact.schema_version,
        output=artifact.output,
        source_sha256=artifact.source_sha256,
        source_tracks_digest=artifact.source_tracks_digest,
        fps_rational=artifact.fps_rational,
        span=artifact.span,
        frame_size=artifact.frame_size,
        frame_map_digest=artifact.frame_map_digest,
        engine=artifact.engine,
        segments=artifact.segments,
        tracks=artifact.tracks,
        refused_tracks=artifact.refused_tracks,
        flags=artifact.flags,
        production=artifact.production,
        digest=digests,
        extra=artifact.extra,
    )


def check_artifact(artifact: RenderedObservationsArtifact) -> tuple[str, ...]:
    """Re-check a sealed artifact against its own contract (violations list)."""
    violations: list[str] = []
    if artifact.schema_version != OBSERVATIONS_SCHEMA_VERSION:
        violations.append(f"schema_version {artifact.schema_version!r}")
    if artifact.digest and artifact.digest != artifact.recompute_digest():
        violations.append("digest does not cover the payload")
    output = artifact.output
    if not output.get("sha256") or len(str(output.get("sha256"))) != 64:
        violations.append("output sha256 missing/not 64 hex")
    if str(output.get("role", "")) not in RENDER_ROLES:
        violations.append(f"output role {output.get('role')!r} is not a render")
    if str(output.get("sha256", "")).lower() == artifact.source_sha256.lower():
        violations.append("output bytes equal the source bytes")
    if not artifact.frame_map_digest:
        violations.append("frame_map_digest missing")
    span_start = int(artifact.span["start_frame"])
    span_end = int(artifact.span["end_frame_exclusive"])
    if span_end <= span_start:
        violations.append(f"span [{span_start}, {span_end}) is empty")
    if not artifact.tracks and not artifact.refused_tracks:
        violations.append("artifact carries no tracks and no refusals")
    matched_roles: set[str] = set()
    for track in artifact.tracks:
        if not track.instance_id:
            violations.append(f"track {track.segment_id}: instance id missing")
        ids = {str(item.get("instance_id")) for item in track.observations}
        if ids != {track.instance_id}:
            violations.append(
                f"track {track.segment_id}: instance id re-minted mid-track"
            )
        frames = [int(item["frame"]) for item in track.observations]
        if frames != sorted(frames):
            violations.append(f"track {track.segment_id}: frames not increasing")
        if len(set(frames)) != len(frames):
            violations.append(f"track {track.segment_id}: duplicate frames")
        for item in track.observations:
            frame = int(item["frame"])
            if frame < span_start or frame >= span_end:
                violations.append(
                    f"track {track.segment_id}: observation frame {frame} "
                    f"outside span [{span_start}, {span_end})"
                )
            digest = str(item.get("mask_digest", ""))
            if len(digest) != 64:
                violations.append(
                    f"track {track.segment_id}: frame {frame} mask digest "
                    "missing"
                )
            if int(item.get("area_px") or 0) <= 0:
                violations.append(
                    f"track {track.segment_id}: frame {frame} empty mask"
                )
            support = item.get("support")
            if not isinstance(support, dict) or support.get("separation") is None:
                violations.append(
                    f"track {track.segment_id}: frame {frame} carries no "
                    "measured pixel support"
                )
            elif float(support.get("separation") or 0.0) <= 0.0:
                violations.append(
                    f"track {track.segment_id}: frame {frame} mask has no "
                    "pixel support"
                )
        runs = [(int(run["start_frame"]), int(run["end_frame"])) for run in track.occlusion_runs]
        if runs != sorted(runs):
            violations.append(f"track {track.segment_id}: occlusion runs unsorted")
        for index in range(1, len(runs)):
            if runs[index][0] < runs[index - 1][1]:
                violations.append(
                    f"track {track.segment_id}: occlusion runs overlap"
                )
        match = dict(track.role_match or {})
        state = str(match.get("state", ""))
        if state == MATCH_MATCHED:
            if not match.get("role_id"):
                violations.append(
                    f"track {track.segment_id}: matched without a role id"
                )
            matched_roles.add(str(match.get("role_id")))
        elif state == MATCH_UNKNOWN:
            if match.get("role_id") is not None or not match.get("reason"):
                violations.append(
                    f"track {track.segment_id}: unknown match must be typed "
                    "(role_id None + reason)"
                )
        else:
            violations.append(f"track {track.segment_id}: bad match state {state!r}")
    if artifact.production:
        try:
            require_production(artifact.engine)
        except RenderedObservationsError as err:
            violations.append(f"production gate: {err.code}")
    return tuple(violations)


def assert_artifact(
    artifact: RenderedObservationsArtifact,
    *,
    require_production_gate: bool = False,
) -> None:
    """Raise ``CODE_OBSERVATION_INVALID`` when the artifact violates itself."""
    violations = check_artifact(artifact)
    if violations:
        raise RenderedObservationsError(
            CODE_OBSERVATION_INVALID, "; ".join(violations)
        )
    if require_production_gate:
        require_production(artifact.engine)


# ── persisted-evidence resolution ────────────────────────────────────────────


def resolve_rendered_output(
    session: Any,
    managed_root: Path,
    scope: src.VideoScope,
    *,
    detector: str = OBSERVATIONS_DETECTOR,
    output_artifact_id: str | None = None,
) -> RenderedOutput:
    """Resolve + verify the RENDER artifact whose pixels get observed.

    ``output_artifact_id`` pins a specific artifact (ownership is then
    verified explicitly: an artifact owned by ANOTHER video item refuses with
    ``CODE_OUTPUT_FOREIGN``, never silently observed).  Without it the same
    disclosed precedence the QC band uses is applied; a video with no render
    (``source_fallback_no_render``) refuses with ``CODE_OUTPUT_NOT_RENDER``.
    """
    root = Path(managed_root)
    if output_artifact_id:
        evidence = src.read_artifact(
            session, root, scope, str(output_artifact_id), detector=detector
        )
        rows = session.execute(
            _owner_query(scope, str(output_artifact_id))
        ).all()
        allowed = [
            row
            for row in rows
            if str(row[0]) == "video_item"
            and str(row[1]) == scope.video_item_id
            and str(row[2]) in ("result", "render", "publication")
        ]
        if not allowed:
            raise RenderedObservationsError(
                CODE_OUTPUT_FOREIGN,
                f"artifact {output_artifact_id!r} is not a rendered output of "
                f"video item {scope.video_item_id!r} (owners seen: "
                f"{[(str(r[0]), str(r[1]), str(r[2])) for r in rows][:5]}); a "
                "foreign output is never observed as this video's render",
            )
        role = "owned_result_artifact"
        facts: dict[str, Any] = {"reason": "explicit artifact id"}
        producer = "explicit output artifact pin"
    else:
        evidence, role, facts = src.render_result_artifact(
            session, root, scope, detector=detector
        )
        if role not in RENDER_ROLES:
            raise RenderedObservationsError(
                CODE_OUTPUT_NOT_RENDER,
                "the video has no rendered output artifact distinct from its "
                f"imported source (resolved role {role!r}); the source side "
                "would be observed instead of the output",
            )
        producer = str(facts.get("producer", ""))
    source_evidence = src.source_artifact(session, root, scope, detector=detector)
    frame_count = _declared_frame_count(facts, root, evidence)
    if evidence.sha256 == source_evidence.sha256:
        raise RenderedObservationsError(
            CODE_OUTPUT_IS_SOURCE,
            f"resolved output artifact {evidence.artifact_id!r} carries the "
            "imported source artifact's bytes (same sha256); observing it "
            "would present the intended source as an output observation",
        )
    width, height = scope.canvas(detector)
    return RenderedOutput(
        artifact_id=evidence.artifact_id,
        sha256=evidence.sha256,
        size_bytes=evidence.size_bytes,
        relative_path=evidence.relative_path,
        role=role,
        width=int(width),
        height=int(height),
        frame_count=int(frame_count),
        source_artifact_id=source_evidence.artifact_id,
        source_sha256=source_evidence.sha256,
        producer=producer,
        facts=dict(facts),
    )


def _owner_query(scope: src.VideoScope, artifact_id: str) -> Any:
    from sqlalchemy import select

    return (
        select(ArtifactOwner.owner_type, ArtifactOwner.owner_id, ArtifactOwner.purpose)
        .join(Artifact, Artifact.id == ArtifactOwner.artifact_id)
        .where(
            ArtifactOwner.artifact_id == artifact_id,
            Artifact.workspace_id == scope.workspace_id,
        )
        .order_by(ArtifactOwner.purpose, ArtifactOwner.owner_id)
    )


def _declared_frame_count(
    facts: Mapping[str, Any], root: Path, evidence: src.ArtifactEvidence
) -> int:
    """The output's declared frame count: publication meta, else the sidecar.

    Fails closed: an output that declares no frame count cannot have its
    frame map verified, so the observation refuses instead of trusting the
    decode count.
    """
    if facts.get("frame_count") is not None:
        return int(facts["frame_count"])
    sidecar = root / f"{evidence.relative_path}.evidence.json"
    if sidecar.is_file():
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        decoded = payload.get("decoded_frame_count")
        if decoded is not None:
            return int(decoded)
    raise RenderedObservationsError(
        CODE_FRAME_MAP_INVALID,
        f"output artifact {evidence.artifact_id!r} declares no frame count "
        "(no completed publication and no evidence sidecar); the decoded "
        "frame map cannot be verified (fail closed)",
    )


#: Persisted ObjectRole kinds that behave like a PERSON for mask/matching
#: purposes; every other persisted kind (prop/background/foreground/graphic/
#: source_overlay/other) is measured as a PROP.  The raw persisted kind is
#: preserved in the segment's note, so nothing is silently rewritten.
PERSON_ROLE_KINDS: tuple[str, ...] = ("character",)


def segments_from_evidence(
    session: Any,
    managed_root: Path,
    scope: src.VideoScope,
    *,
    detector: str = OBSERVATIONS_DETECTOR,
    segment_ids: Sequence[str] | None = None,
) -> tuple[RenderedSegment, ...]:
    """Declared role spans of the video, from the persisted segments.

    The segment's own published mask bounds the SEARCH WINDOW (where to
    look); it carries no output-side truth — the window only seeds the
    measurement on the render pixels.
    """
    rows = src.current_segments(session, scope)
    wanted = {str(item) for item in segment_ids} if segment_ids else None
    out: list[RenderedSegment] = []
    for row in rows:
        segment_id = str(row.id)
        if wanted is not None and segment_id not in wanted:
            continue
        window: tuple[int, int, int, int] | None = None
        if row.mask_artifact_id:
            evidence = src.read_artifact(
                session, Path(managed_root), scope, str(row.mask_artifact_id), detector=detector
            )
            matrix, _width, _height = qcm.decode_png_gray(
                evidence.data, detector=detector
            )
            window = qcm.mask_bbox(matrix)
        out.append(
            RenderedSegment(
                segment_id=segment_id,
                role_id=str(row.role_id),
                kind=(
                    srt.ROLE_KIND_PERSON
                    if str(row.kind) in PERSON_ROLE_KINDS
                    else srt.ROLE_KIND_PROP
                ),
                start_frame=int(row.start_frame),
                end_frame=int(row.end_frame) + 1,
                window=window,
                note=f"{row.name} (role_kind={row.kind})",
            )
        )
    if not out:
        raise RenderedObservationsError(
            CODE_SEGMENT_INVALID,
            "the video has no current-generation occurrence segments to "
            "observe on the output (the object-extraction producer has not "
            "published the role spans)",
        )
    return tuple(out)


def references_for_roles(
    session: Any,
    managed_root: Path,
    scope: src.VideoScope,
    role_ids: Sequence[str],
    *,
    detector: str = OBSERVATIONS_DETECTOR,
) -> dict[str, RenderedReference]:
    """The pinned cast reference pixels of every role that has a pin.

    A role without a cast pin has NO reference: it is simply absent from the
    mapping (the match for it becomes a typed unknown).  A pin whose
    reference bytes are foreign / tampered / unreadable raises — that is
    broken authority, not a missing one.
    """
    out: dict[str, RenderedReference] = {}
    width, height = scope.canvas(detector)
    for role_id in sorted({str(role) for role in role_ids}):
        try:
            pin = src.cast_pin_for_role(
                session, Path(managed_root), scope, role_id, detector=detector
            )
        except QcEvidenceError as err:
            if err.code == "QC_EVIDENCE_MISSING":
                continue
            raise
        reference = src.pin_reference(pin)
        matrix, ref_width, ref_height = qcm.decode_png_gray(
            reference.data, detector=detector
        )
        if (int(ref_height), int(ref_width)) != (int(height), int(width)):
            raise RenderedObservationsError(
                CODE_REFERENCE_INVALID,
                f"role {role_id!r} reference artifact is "
                f"{ref_width}x{ref_height} but the video canvas is "
                f"{width}x{height}; the match cannot be measured under one "
                "window (fail closed)",
            )
        out[role_id] = RenderedReference(
            role_id=role_id,
            artifact_id=reference.artifact_id,
            sha256=reference.sha256,
            frame=np.asarray(matrix, dtype=np.float64),
            pose_slot=str(pin.get("pose_slot", "")),
        )
    return out


def observe_rendered_output(
    session: Any,
    managed_root: Path,
    scope: src.VideoScope,
    *,
    engine: OutputMaskEngine,
    detector: str = OBSERVATIONS_DETECTOR,
    output_artifact_id: str | None = None,
    segment_ids: Sequence[str] | None = None,
    source_tracks_digest: str | None = None,
    max_frames: int = DEFAULT_MAX_DECODE_FRAMES,
    production: bool = False,
    strict: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> RenderedObservationsArtifact:
    """End-to-end: resolve the render, decode it, observe it, seal the record."""
    output = resolve_rendered_output(
        session,
        managed_root,
        scope,
        detector=detector,
        output_artifact_id=output_artifact_id,
    )
    segments = segments_from_evidence(
        session, managed_root, scope, detector=detector, segment_ids=segment_ids
    )
    span_start = min(segment.start_frame for segment in segments)
    span_end = max(segment.end_frame for segment in segments)
    frames = decode_output_frame_map(
        Path(managed_root) / output.relative_path,
        list(range(span_start, span_end)),
        detector=detector,
        max_frames=max_frames,
    )
    references = references_for_roles(
        session,
        managed_root,
        scope,
        [segment.role_id for segment in segments],
        detector=detector,
    )
    if not scope.fps_num or not scope.fps_den:
        raise RenderedObservationsError(
            CODE_OUTPUT_INVALID,
            "the video item has no persisted canonical timebase "
            "(video_item.fps_num/fps_den are NULL); the output frame space "
            "cannot be pinned (fail closed)",
        )
    extra_payload = dict(extra or {})
    extra_payload.setdefault(
        "source_comparison",
        {
            "source_sha256": output.source_sha256,
            "output_sha256": output.sha256,
            "source_artifact_id": output.source_artifact_id,
            "source_tracks_digest": source_tracks_digest,
            "shared_frame_size": [int(output.width), int(output.height)],
            "note": "both sides are measured under the video's own canvas "
            "geometry; the source side is the sealed MF-END-12 track artifact "
            "when its digest is supplied, otherwise unknown",
        },
    )
    return build_rendered_observations(
        output=output,
        frames=frames,
        segments=segments,
        engine=engine,
        fps_rational=f"{int(scope.fps_num)}/{int(scope.fps_den)}",
        references=references,
        source_tracks_digest=source_tracks_digest,
        production=production,
        strict=strict,
        extra=extra_payload,
    )


# ── publication + read-back ──────────────────────────────────────────────────


def publish_rendered_observations(
    session: Any,
    managed_root: Path,
    *,
    workspace_id: str,
    video_item_id: str,
    relative_path: str,
    artifact: RenderedObservationsArtifact,
) -> dict[str, Any]:
    """Atomically publish the sealed payload + register its managed artifact.

    The bytes written are the artifact's own sealed payload; the artifact row
    carries their true sha256/size, and the owner row is what
    :func:`app.services.qc_evidence.sources.rendered_observations_artifact`
    resolves.  No field is synthesized.
    """
    payload = artifact.to_payload()
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    root = ManagedRoot(Path(managed_root))
    sha256, size_bytes = root.atomic_write_bytes(relative_path, data)
    row = Artifact(
        workspace_id=str(workspace_id),
        kind="document",
        relative_path=str(relative_path),
        state="ready",
        sha256=str(sha256),
        size_bytes=int(size_bytes),
        mime_type="application/json",
    )
    session.add(row)
    session.flush()
    session.add(
        ArtifactOwner(
            artifact_id=row.id,
            owner_type="video_item",
            owner_id=str(video_item_id),
            purpose=src.RENDERED_OBSERVATIONS_PURPOSE,
        )
    )
    session.flush()
    return {
        "artifact_id": str(row.id),
        "relative_path": str(relative_path),
        "sha256": str(sha256),
        "size_bytes": int(size_bytes),
        "digest": artifact.digest,
    }


def load_rendered_observations(
    session: Any,
    managed_root: Path,
    scope: src.VideoScope,
    *,
    detector: str = OBSERVATIONS_DETECTOR,
) -> tuple[src.ArtifactEvidence, RenderedObservationsArtifact]:
    """Read back the newest published observation record (verified bytes)."""
    evidence, payload = src.rendered_observations_artifact(
        session, Path(managed_root), scope, detector=detector
    )
    return evidence, RenderedObservationsArtifact.from_payload(payload)

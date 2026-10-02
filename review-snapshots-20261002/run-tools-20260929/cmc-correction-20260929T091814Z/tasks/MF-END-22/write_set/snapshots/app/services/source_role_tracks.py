"""Role/prop source tracks with a frame → mask → track trace (MF-END-12).

One deterministic pipeline turns a REAL decoded source (its frame space pinned by
the accepted MF-END-11 shot-plan/timebase contracts) plus REAL declared
role/prop seeds into a versioned, sealed ``RoleTracksArtifact``:

* **frame → mask**: every observation binds an ABSOLUTE source frame index to a
  mask computed from that frame's real pixels; the mask is pinned by a content
  digest and measured (area, coverage, bbox, solidity, hole ratio, border
  touch, crop digest).
* **mask → track**: observations are linked into ONE track per declared
  role/prop seed with a STABLE instance id that survives occlusion; contiguous
  occluded frames become explicit occlusion runs and the id is never
  re-minted.
* **fail-closed mask rules**: a mask that covers (almost) the whole canvas or
  is a hollow outline NEVER grants an edit permission; the permission field is
  derived from the measured stats, not from the producer's word.
* **provenance**: a CI fixture mask source can NEVER be recorded as a
  production artifact, and a production artifact REQUIRES a real capability
  probe record for the applied engine.
* **engine honesty**: an engine that has not actually run (e.g. SAM3 without
  weights) is never recorded as applied — :func:`check_engine_claim` refuses a
  ``sam3`` claim unless the artifact carries a real SAM3 probe whose status is
  run.

The module is CPU-only and performs no render: it consumes frames and masks and
serialises measurements.  Real SAM2.1 inference runs through the EXISTING
``app.services.object_extraction.Sam2ExtractionProvider`` capability probe and
the EXISTING ``app.adapters.segmentation`` adapter, injected as a mask source;
this module never fabricates mask pixels.
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

from app.schemas.shot_reskin import SourceSpan
from app.services.shot_reskin_plan import parse_rational

__all__ = [
    "CODE_ARTIFACT_INVALID",
    "CODE_DIGEST_MISMATCH",
    "CODE_DUPLICATE_INSTANCE",
    "CODE_ENGINE_UNPROBED",
    "CODE_FIXTURE_NOT_PRODUCTION",
    "CODE_INSTANCE_CHANGED",
    "CODE_MANIFEST_INVALID",
    "CODE_MASK_ALL_CANVAS",
    "CODE_MASK_EMPTY",
    "CODE_MASK_HOLLOW",
    "CODE_NO_TRACE",
    "CODE_OBSERVATION_INVALID",
    "CODE_PARTIAL_DROPPED",
    "CODE_SAM3_UNPROBED",
    "CODE_SEED_INVALID",
    "CODE_SEED_NOT_SEEN",
    "CODE_SERIALIZATION_INVALID",
    "CODE_SOURCE_CHANGED",
    "CODE_SOURCE_INVALID",
    "CODE_SPAN_INVALID",
    "CODE_VALID",
    "CODE_VERSION_UNSUPPORTED",
    "DEFAULT_ALL_CANVAS_RATIO",
    "DEFAULT_AREA_JUMP_RATIO",
    "DEFAULT_DRIFT_RATIO",
    "DEFAULT_DUPLICATE_IOU",
    "DEFAULT_HOLLOW_RATIO",
    "DEFAULT_MIN_AREA_PX",
    "DEFAULT_SHIFT_RATIO",
    "ENGINE_SAM2_1",
    "ENGINE_SAM3",
    "MANIFEST_SCHEMA",
    "PERMISSION_DENIED",
    "PERMISSION_GRANTED",
    "PROVENANCE_FIXTURE",
    "PROVENANCE_PRODUCTION",
    "ROLE_KIND_PERSON",
    "ROLE_KIND_PROP",
    "STATUS_BLOCKED_DEPENDENCY",
    "STATUS_CI_ONLY",
    "STATUS_NOT_RUN",
    "STATUS_PROBED_READY",
    "TRACKS_SCHEMA_VERSION",
    "VISIBILITY_OCCLUDED",
    "VISIBILITY_OUT_OF_FRAME",
    "VISIBILITY_PARTIAL",
    "VISIBILITY_VISIBLE",
    "EngineRecord",
    "Flag",
    "MaskSample",
    "MaskSource",
    "OcclusionRun",
    "RoleSeed",
    "RoleTrack",
    "RoleTracksArtifact",
    "RoleTracksError",
    "SeedRefusal",
    "WorkflowManifest",
    "build_role_tracks",
    "canonical_json",
    "check_artifact",
    "check_engine_claim",
    "load_workflow_manifest",
    "mask_digest",
    "mask_stats",
    "payload_sha256",
    "require_production",
    "validate_workflow_manifest",
]

# ── schema + vocabulary ──────────────────────────────────────────────────────

#: Version of the persisted role-track artifact (managed-artifact version tag).
TRACKS_SCHEMA_VERSION = "mf.source_role_tracks.v1"

#: Schema of the media workflow manifest this module binds (new, MF-END-12).
MANIFEST_SCHEMA = "mf.role_segmentation_workflow.v1"

PROVENANCE_PRODUCTION = "production"
PROVENANCE_FIXTURE = "ci_fixture"

ROLE_KIND_PERSON = "person"
ROLE_KIND_PROP = "prop"

VISIBILITY_VISIBLE = "visible"
VISIBILITY_PARTIAL = "partial"
VISIBILITY_OCCLUDED = "occluded"
VISIBILITY_OUT_OF_FRAME = "out_of_frame"

PERMISSION_GRANTED = "granted"
PERMISSION_DENIED = "denied"

#: Engine ids (never a wildcard; a new engine is a new id + a real probe).
ENGINE_SAM2_1 = "sam2.1"
ENGINE_SAM3 = "sam3"

#: Engine statuses recorded in the workflow manifest / probe candidates.
STATUS_PROBED_READY = "AVAILABLE_PROBED"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
STATUS_CI_ONLY = "CI_ONLY"

# ── typed reason codes (module-local, stable strings) ────────────────────────

CODE_SOURCE_INVALID = "ROLE_TRACKS_SOURCE_INVALID"
CODE_SPAN_INVALID = "ROLE_TRACKS_SPAN_INVALID"
CODE_SEED_INVALID = "ROLE_TRACKS_SEED_INVALID"
CODE_SEED_NOT_SEEN = "ROLE_TRACKS_SEED_NOT_SEEN"
CODE_MASK_EMPTY = "ROLE_TRACKS_MASK_EMPTY"
CODE_MASK_ALL_CANVAS = "ROLE_TRACKS_MASK_ALL_CANVAS"
CODE_MASK_HOLLOW = "ROLE_TRACKS_MASK_HOLLOW"
CODE_DUPLICATE_INSTANCE = "ROLE_TRACKS_DUPLICATE_INSTANCE"
CODE_FIXTURE_NOT_PRODUCTION = "ROLE_TRACKS_FIXTURE_NOT_PRODUCTION"
CODE_ENGINE_UNPROBED = "ROLE_TRACKS_ENGINE_UNPROBED"
CODE_SAM3_UNPROBED = "ROLE_TRACKS_SAM3_UNPROBED"
CODE_NO_TRACE = "ROLE_TRACKS_NO_TRACE"
CODE_PARTIAL_DROPPED = "ROLE_TRACKS_PARTIAL_DROPPED"
CODE_INSTANCE_CHANGED = "ROLE_TRACKS_INSTANCE_CHANGED"
CODE_SOURCE_CHANGED = "ROLE_TRACKS_SOURCE_CHANGED"
CODE_DIGEST_MISMATCH = "ROLE_TRACKS_DIGEST_MISMATCH"
CODE_VERSION_UNSUPPORTED = "ROLE_TRACKS_VERSION_UNSUPPORTED"
CODE_SERIALIZATION_INVALID = "ROLE_TRACKS_SERIALIZATION_INVALID"
CODE_MANIFEST_INVALID = "ROLE_TRACKS_MANIFEST_INVALID"
CODE_ARTIFACT_INVALID = "ROLE_TRACKS_ARTIFACT_INVALID"
CODE_OBSERVATION_INVALID = "ROLE_TRACKS_OBSERVATION_INVALID"
CODE_VALID = "ROLE_TRACKS_VALID"

# ── measured-rule defaults (documented, overridable via the manifest) ────────

#: coverage_ratio at/above this is an ALL-CANVAS mask: never grants.
DEFAULT_ALL_CANVAS_RATIO = 0.92
#: hole ratio ``(filled - area) / area`` at/above this is a HOLLOW mask: never grants.
DEFAULT_HOLLOW_RATIO = 0.35
#: masks smaller than this carry no usable region: never grants.
DEFAULT_MIN_AREA_PX = 16
#: two seeds whose masks reach this IoU on a frame claim the SAME instance.
DEFAULT_DUPLICATE_IOU = 0.85
#: centroid distance from the seed-box centre, relative to the seed-box diagonal,
#: beyond which the region no longer plausibly belongs to the seeded instance.
DEFAULT_DRIFT_RATIO = 0.75
#: per-step centroid shift relative to sqrt(area) beyond which the link is unstable.
DEFAULT_SHIFT_RATIO = 0.60
#: per-step area factor (either direction) beyond which the link is unstable.
DEFAULT_AREA_JUMP_RATIO = 3.0


class RoleTracksError(ValueError):
    """Typed fail-closed error for role-track work (module-local codes)."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


# ── canonical serialisation helpers ──────────────────────────────────────────


def canonical_json(payload: Any) -> str:
    """Canonical JSON (sorted keys, no whitespace, ASCII) — byte-stable."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_sha256(payload: Any) -> str:
    """sha256 of the canonical JSON encoding of ``payload``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def mask_digest(mask: np.ndarray) -> str:
    """Content digest of one binary mask: shape header + packed bits.

    The shape is inside the hashed payload so a reshape cannot collide.
    """
    binary = np.asarray(mask).astype(bool)
    if binary.ndim != 2:
        raise RoleTracksError(CODE_MASK_EMPTY, f"mask must be 2D, got ndim={binary.ndim}")
    height, width = binary.shape
    header = b"RTM1" + width.to_bytes(4, "little") + height.to_bytes(4, "little")
    return hashlib.sha256(header + np.packbits(binary).tobytes()).hexdigest()


# ── real mask measurements ───────────────────────────────────────────────────


def mask_stats(mask: np.ndarray, seed_box: Sequence[int] | None = None) -> dict[str, Any]:
    """Measure one binary mask on REAL pixels.

    Returns area, coverage ratio, bbox, solidity (area / convex-hull area),
    hole ratio ((filled-area)/area), border touch (frame-edge crop), and — when
    ``seed_box`` is given — the mask/seed-box intersection size.
    """
    binary = np.asarray(mask).astype(bool)
    if binary.ndim != 2 or binary.size == 0:
        raise RoleTracksError(CODE_MASK_EMPTY, "mask must be a non-empty 2D array")
    height, width = binary.shape
    area = int(np.count_nonzero(binary))
    stats: dict[str, Any] = {
        "width": int(width),
        "height": int(height),
        "area_px": area,
        "coverage_ratio": area / float(width * height),
        "bbox": None,
        "solidity": None,
        "hole_ratio": None,
        "border_touch": False,
    }
    if area == 0:
        return stats
    ys, xs = np.nonzero(binary)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    stats["bbox"] = [x0, y0, x1 - x0 + 1, y1 - y0 + 1]
    stats["border_touch"] = bool(x0 == 0 or y0 == 0 or x1 == width - 1 or y1 == height - 1)
    # Solidity: real convex hull of the mask pixels (cv2 on a uint8 copy).
    mask_u8 = (binary * 255).astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        hull_area = float(sum(cv2.contourArea(cv2.convexHull(c)) for c in contours))
        if hull_area > 0:
            stats["solidity"] = min(1.0, area / hull_area)
        # Filled area (holes closed) via the same contours, filled.
        filled = np.zeros_like(mask_u8)
        cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
        filled_area = int(np.count_nonzero(filled))
        stats["hole_ratio"] = max(0.0, (filled_area - area) / float(area))
    if seed_box is not None:
        bx, by, bw, bh = (int(v) for v in seed_box)
        xa, xb = max(0, bx), min(width, bx + max(0, bw))
        ya, yb = max(0, by), min(height, by + max(0, bh))
        inside = int(np.count_nonzero(binary[ya:yb, xa:xb])) if xb > xa and yb > ya else 0
        stats["seed_intersection_px"] = inside
    return stats


def mask_iou(first: np.ndarray, second: np.ndarray) -> float:
    """Intersection-over-union of two binary masks of equal shape."""
    a = np.asarray(first).astype(bool)
    b = np.asarray(second).astype(bool)
    if a.shape != b.shape:
        raise RoleTracksError(CODE_OBSERVATION_INVALID, f"shape mismatch {a.shape} vs {b.shape}")
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 0.0
    return float(np.count_nonzero(a & b)) / union


def _permission_and_state(
    stats: Mapping[str, Any],
    *,
    all_canvas_ratio: float,
    hollow_ratio: float,
    min_area_px: int,
) -> tuple[str, str | None, str]:
    """Derive (permission, denial_code, visibility_state) from measured stats.

    Order is fixed and fail-closed: empty → all-canvas → hollow → granted.
    A denied observation can NEVER carry ``granted``.
    """
    area = int(stats.get("area_px") or 0)
    if area < max(0, int(min_area_px)):
        return PERMISSION_DENIED, CODE_MASK_EMPTY, VISIBILITY_VISIBLE
    coverage = float(stats.get("coverage_ratio") or 0.0)
    if coverage >= all_canvas_ratio:
        return PERMISSION_DENIED, CODE_MASK_ALL_CANVAS, VISIBILITY_VISIBLE
    hole = stats.get("hole_ratio")
    if hole is not None and float(hole) >= hollow_ratio:
        return PERMISSION_DENIED, CODE_MASK_HOLLOW, VISIBILITY_VISIBLE
    state = VISIBILITY_PARTIAL if stats.get("border_touch") else VISIBILITY_VISIBLE
    return PERMISSION_GRANTED, None, state


def _union_iou(a: np.ndarray, b: np.ndarray) -> float:
    """Alias kept for readability at the call site."""
    return mask_iou(a, b)


# ── data model ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoleSeed:
    """One REAL declared role/prop seed on the source frame space."""

    role_id: str
    kind: str
    box: tuple[int, int, int, int]
    #: Frames over which this seed is declared present (absolute indices).
    declare_frames: tuple[int, int]
    partial_required: bool = False
    note: str = ""

    def validate(self) -> None:
        if not self.role_id or not isinstance(self.role_id, str):
            raise RoleTracksError(
                CODE_SEED_INVALID, f"role_id must be a non-empty string: {self.role_id!r}"
            )
        if self.kind not in (ROLE_KIND_PERSON, ROLE_KIND_PROP):
            raise RoleTracksError(CODE_SEED_INVALID, f"kind must be person|prop: {self.kind!r}")
        if len(self.box) != 4 or any(int(v) < 0 for v in self.box):
            raise RoleTracksError(
                CODE_SEED_INVALID, f"box must be 4 non-negative ints: {self.box!r}"
            )
        if int(self.box[2]) <= 0 or int(self.box[3]) <= 0:
            raise RoleTracksError(CODE_SEED_INVALID, f"box must be non-empty: {self.box!r}")
        start, end = (int(v) for v in self.declare_frames)
        if start < 0 or end <= start:
            raise RoleTracksError(
                CODE_SEED_INVALID, f"declare_frames must be [start, end): {self.declare_frames!r}"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "kind": self.kind,
            "box": list(self.box),
            "declare_frames": list(self.declare_frames),
            "partial_required": bool(self.partial_required),
            "note": self.note,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RoleSeed:
        box = tuple(int(v) for v in payload["box"])
        frames = tuple(int(v) for v in payload["declare_frames"])
        return cls(
            role_id=str(payload["role_id"]),
            kind=str(payload["kind"]),
            box=box,  # type: ignore[arg-type]
            declare_frames=frames,  # type: ignore[arg-type]
            partial_required=bool(payload.get("partial_required", False)),
            note=str(payload.get("note", "")),
        )


@dataclass(frozen=True)
class MaskSample:
    """One mask-source answer for one (frame, seed).

    ``mask=None`` with ``present=True`` is the source ASSERTING the instance is
    still there (occluded) — the engine records an occlusion run, never a new
    instance.  ``score`` is the source's own optional measurement (e.g. a model
    logit); it is ``None`` when the source cannot measure one — recorded as
    unknown, never invented.
    """

    mask: np.ndarray | None
    method: str
    present: bool = True
    out_of_frame: bool = False
    score: float | None = None


class MaskSource(Protocol):
    """Injected mask producer (real inference or a real CI-pixel computer)."""

    engine_id: str
    provenance: str
    probe: Mapping[str, Any] | None

    def sample(self, frame_index: int, seed: RoleSeed, frame: np.ndarray) -> MaskSample | None:
        """Answer for one frame; ``None`` means "no observation available"."""


@dataclass(frozen=True)
class Flag:
    code: str
    frame: int | None
    detail: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "frame": self.frame, "detail": self.detail}


@dataclass(frozen=True)
class OcclusionRun:
    """Contiguous frames where the instance was present but had no usable mask."""

    start_frame: int
    end_frame: int  # exclusive

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame

    def to_payload(self) -> dict[str, int]:
        return {"start_frame": self.start_frame, "end_frame": self.end_frame}


@dataclass(frozen=True)
class RoleTrack:
    """One role/prop instance tracked across the declared span.

    The ``instance_id`` is minted ONCE from the seed and stamped on every
    observation; occlusion never re-mints it.
    """

    role_id: str
    kind: str
    instance_id: str
    seed: RoleSeed
    observations: tuple[dict[str, Any], ...]
    occlusion_runs: tuple[OcclusionRun, ...]
    gap_frames: tuple[int, ...]
    partial_frames: tuple[int, ...]
    out_of_frame_frames: tuple[int, ...]
    flags: tuple[Flag, ...]
    stability: Mapping[str, Any]
    trace_complete: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "kind": self.kind,
            "instance_id": self.instance_id,
            "seed": self.seed.to_payload(),
            "observations": [dict(item) for item in self.observations],
            "occlusion_runs": [run.to_payload() for run in self.occlusion_runs],
            "gap_frames": list(self.gap_frames),
            "partial_frames": list(self.partial_frames),
            "out_of_frame_frames": list(self.out_of_frame_frames),
            "flags": [flag.to_payload() for flag in self.flags],
            "stability": dict(self.stability),
            "trace_complete": bool(self.trace_complete),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RoleTrack:
        return cls(
            role_id=str(payload["role_id"]),
            kind=str(payload["kind"]),
            instance_id=str(payload["instance_id"]),
            seed=RoleSeed.from_payload(payload["seed"]),
            observations=tuple(dict(item) for item in payload["observations"]),
            occlusion_runs=tuple(
                OcclusionRun(int(run["start_frame"]), int(run["end_frame"]))
                for run in payload.get("occlusion_runs", [])
            ),
            gap_frames=tuple(int(v) for v in payload.get("gap_frames", [])),
            partial_frames=tuple(int(v) for v in payload.get("partial_frames", [])),
            out_of_frame_frames=tuple(int(v) for v in payload.get("out_of_frame_frames", [])),
            flags=tuple(
                Flag(str(item["code"]), item.get("frame"), str(item.get("detail", "")))
                for item in payload.get("flags", [])
            ),
            stability=dict(payload.get("stability", {})),
            trace_complete=bool(payload.get("trace_complete", False)),
        )


@dataclass(frozen=True)
class SeedRefusal:
    """A declared seed that could not be traced (recorded, never hidden)."""

    role_id: str
    code: str
    detail: str = ""

    def to_payload(self) -> dict[str, str]:
        return {"role_id": self.role_id, "code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EngineRecord:
    """Which engine produced the masks, with its REAL probe evidence."""

    engine_id: str
    provenance: str
    probe: Mapping[str, Any] | None
    probe_digest: str | None
    candidates: Mapping[str, str]
    inference_ran: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "provenance": self.provenance,
            "probe": dict(self.probe) if self.probe is not None else None,
            "probe_digest": self.probe_digest,
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
            candidates=dict(payload.get("candidates", {})),
            inference_ran=bool(payload.get("inference_ran", False)),
        )


@dataclass(frozen=True)
class RoleTracksArtifact:
    """Versioned, sealed frame → mask → track record for one source span."""

    schema_version: str
    source_sha256: str
    span: SourceSpan
    fps_rational: str
    frame_size: tuple[int, int]
    engine: EngineRecord
    manifest_sha256: str
    manifest_version: str
    seeds: tuple[RoleSeed, ...]
    tracks: tuple[RoleTrack, ...]
    refused_seeds: tuple[SeedRefusal, ...]
    flags: tuple[Flag, ...]
    production: bool
    digest: str
    extra: Mapping[str, Any] = field(default_factory=dict)

    # ── serialisation ────────────────────────────────────────────────────

    def to_payload(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "span": {
                "start_frame": self.span.start_frame,
                "end_frame_exclusive": self.span.end_frame_exclusive,
            },
            "fps_rational": self.fps_rational,
            "frame_size": list(self.frame_size),
            "engine": self.engine.to_payload(),
            "manifest_sha256": self.manifest_sha256,
            "manifest_version": self.manifest_version,
            "seeds": [seed.to_payload() for seed in self.seeds],
            "tracks": [track.to_payload() for track in self.tracks],
            "refused_seeds": [item.to_payload() for item in self.refused_seeds],
            "flags": [flag.to_payload() for flag in self.flags],
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
    def from_payload(cls, payload: Mapping[str, Any]) -> RoleTracksArtifact:
        version = str(payload.get("schema_version", ""))
        if version != TRACKS_SCHEMA_VERSION:
            raise RoleTracksError(
                CODE_VERSION_UNSUPPORTED,
                f"artifact version {version!r} is not {TRACKS_SCHEMA_VERSION!r}",
            )
        try:
            span = SourceSpan(
                start_frame=int(payload["span"]["start_frame"]),
                end_frame_exclusive=int(payload["span"]["end_frame_exclusive"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise RoleTracksError(CODE_SERIALIZATION_INVALID, f"span unreadable: {err}") from err
        frame_size = tuple(int(v) for v in payload["frame_size"])
        artifact = cls(
            schema_version=version,
            source_sha256=str(payload["source_sha256"]),
            span=span,
            fps_rational=str(payload["fps_rational"]),
            frame_size=frame_size,  # type: ignore[arg-type]
            engine=EngineRecord.from_payload(payload["engine"]),
            manifest_sha256=str(payload.get("manifest_sha256", "")),
            manifest_version=str(payload.get("manifest_version", "")),
            seeds=tuple(RoleSeed.from_payload(seed) for seed in payload.get("seeds", [])),
            tracks=tuple(RoleTrack.from_payload(track) for track in payload.get("tracks", [])),
            refused_seeds=tuple(
                SeedRefusal(str(item["role_id"]), str(item["code"]), str(item.get("detail", "")))
                for item in payload.get("refused_seeds", [])
            ),
            flags=tuple(
                Flag(str(item["code"]), item.get("frame"), str(item.get("detail", "")))
                for item in payload.get("flags", [])
            ),
            production=bool(payload.get("production", False)),
            digest=str(payload.get("digest", "")),
            extra=dict(payload.get("extra", {})),
        )
        expected = artifact.recompute_digest()
        if expected != artifact.digest:
            raise RoleTracksError(
                CODE_DIGEST_MISMATCH,
                f"artifact digest {artifact.digest} != recomputed {expected}",
            )
        return artifact


# ── engine claim / production guards ─────────────────────────────────────────


def require_production(artifact: RoleTracksArtifact) -> None:
    """Refuse a CI-fixture artifact (or an unprobed production claim)."""
    if not artifact.production:
        raise RoleTracksError(
            CODE_FIXTURE_NOT_PRODUCTION,
            f"artifact provenance {artifact.engine.provenance!r} is a CI fixture; "
            "fixtures never count as production tracks",
        )
    if artifact.engine.provenance != PROVENANCE_PRODUCTION:
        raise RoleTracksError(
            CODE_FIXTURE_NOT_PRODUCTION,
            f"artifact advertises production but its engine provenance is "
            f"{artifact.engine.provenance!r}",
        )
    if artifact.engine.probe is None or not artifact.engine.probe_digest:
        raise RoleTracksError(
            CODE_ENGINE_UNPROBED,
            f"engine {artifact.engine.engine_id!r} has no real capability probe record",
        )
    status = str(dict(artifact.engine.probe).get("status", ""))
    if status != STATUS_PROBED_READY:
        raise RoleTracksError(
            CODE_ENGINE_UNPROBED,
            f"engine probe status {status!r} is not {STATUS_PROBED_READY!r}",
        )


def check_engine_claim(artifact: RoleTracksArtifact, engine_id: str) -> None:
    """Refuse recording ``engine_id`` as applied without a run/probe record.

    Specifically: SAM3 has never run on this machine (no weights) — a claim
    that it was APPLIED is refused, while a manifest/probe status of
    ``NOT_RUN``/``BLOCKED_DEPENDENCY`` is the honest record.
    """
    status = dict(artifact.engine.candidates).get(engine_id)
    if engine_id == artifact.engine.engine_id:
        if not artifact.engine.inference_ran:
            raise RoleTracksError(
                CODE_ENGINE_UNPROBED,
                f"engine {engine_id!r} is recorded as applied but the record says "
                "inference did not run",
            )
        return
    if engine_id == ENGINE_SAM3 or (status is not None and status != STATUS_PROBED_READY):
        raise RoleTracksError(
            CODE_SAM3_UNPROBED if engine_id == ENGINE_SAM3 else CODE_ENGINE_UNPROBED,
            f"{engine_id!r} is recorded as {status!r}: it has not run on this source "
            "and must not be claimed as applied "
            f"(probe digest {artifact.engine.probe_digest!r})",
        )
    raise RoleTracksError(
        CODE_ENGINE_UNPROBED,
        f"engine {engine_id!r} is not the applied engine {artifact.engine.engine_id!r}",
    )


# ── the builder ──────────────────────────────────────────────────────────────


def build_role_tracks(
    *,
    source_sha256: str,
    span: SourceSpan,
    frames: Sequence[np.ndarray],
    fps_rational: str,
    seeds: Sequence[RoleSeed],
    mask_source: MaskSource,
    manifest_sha256: str,
    manifest_version: str,
    production: bool = False,
    all_canvas_ratio: float = DEFAULT_ALL_CANVAS_RATIO,
    hollow_ratio: float = DEFAULT_HOLLOW_RATIO,
    min_area_px: int = DEFAULT_MIN_AREA_PX,
    duplicate_iou: float = DEFAULT_DUPLICATE_IOU,
    drift_ratio: float = DEFAULT_DRIFT_RATIO,
    shift_ratio: float = DEFAULT_SHIFT_RATIO,
    area_jump_ratio: float = DEFAULT_AREA_JUMP_RATIO,
    strict: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> RoleTracksArtifact:
    """Build the sealed role-track artifact from REAL frames + REAL masks.

    Fail-closed rules (each with its own typed code):
    * a declared seed with NO frame→mask→track trace anywhere in its span is
      refused (``CODE_NO_TRACE`` strict / recorded in ``refused_seeds``);
    * a seed whose masks never intersect its own box is refused
      (``CODE_SEED_NOT_SEEN``);
    * two seeds claiming the same instance (mask IoU >= ``duplicate_iou``) are
      flagged on both and refused strict (``CODE_DUPLICATE_INSTANCE``);
    * a partial-required seed with any gap in its declared span is refused
      (``CODE_PARTIAL_DROPPED``) — partial characters are MANDATORY;
    * ``production=True`` with a fixture source (or no probe) is refused
      (``CODE_FIXTURE_NOT_PRODUCTION`` / ``CODE_ENGINE_UNPROBED``).
    """
    if not source_sha256 or len(source_sha256) != 64:
        raise RoleTracksError(
            CODE_SOURCE_INVALID, f"source sha256 must be 64 hex chars: {source_sha256!r}"
        )
    parse_rational(fps_rational, what="fps")
    frame_count = span.frame_count
    if len(frames) != frame_count:
        raise RoleTracksError(
            CODE_SPAN_INVALID,
            f"frames {len(frames)} != span frame_count {frame_count} (frames must be the REAL "
            "decoded span, in order)",
        )
    first = np.asarray(frames[0])
    if first.ndim != 3 or first.shape[2] != 3:
        raise RoleTracksError(CODE_SOURCE_INVALID, f"frames must be HxWx3 BGR, got {first.shape}")
    height, width = int(first.shape[0]), int(first.shape[1])
    for index, frame in enumerate(frames):
        array = np.asarray(frame)
        if array.shape != (height, width, 3):
            raise RoleTracksError(
                CODE_SOURCE_INVALID,
                f"frame {span.start_frame + index} shape {array.shape} != {(height, width, 3)}",
            )

    provenance = str(getattr(mask_source, "provenance", ""))
    engine_id = str(getattr(mask_source, "engine_id", ""))
    probe = getattr(mask_source, "probe", None)
    if not engine_id:
        raise RoleTracksError(CODE_ENGINE_UNPROBED, "mask source has no engine_id")
    if provenance not in (PROVENANCE_PRODUCTION, PROVENANCE_FIXTURE):
        raise RoleTracksError(
            CODE_ENGINE_UNPROBED, f"unknown mask-source provenance {provenance!r}"
        )
    if production:
        if provenance != PROVENANCE_PRODUCTION:
            raise RoleTracksError(
                CODE_FIXTURE_NOT_PRODUCTION,
                f"a {provenance!r} mask source can never be recorded as a production artifact",
            )
        if probe is None or str(dict(probe).get("status", "")) != STATUS_PROBED_READY:
            raise RoleTracksError(
                CODE_ENGINE_UNPROBED,
                f"production build requires a real probe with status {STATUS_PROBED_READY!r}",
            )

    seed_list = tuple(seeds)
    for seed in seed_list:
        seed.validate()
    if not seed_list:
        raise RoleTracksError(CODE_SEED_INVALID, "at least one role/prop seed is required")

    tracks: list[RoleTrack] = []
    refused: list[SeedRefusal] = []
    artifact_flags: list[Flag] = []
    masks_by_role_frame: dict[tuple[str, int], np.ndarray] = {}

    for seed in seed_list:
        observations: list[dict[str, Any]] = []
        occlusion_runs: list[OcclusionRun] = []
        gap_frames: list[int] = []
        partial_frames: list[int] = []
        out_of_frame_frames: list[int] = []
        track_flags: list[Flag] = []
        open_run_start: int | None = None
        declared = range(
            max(span.start_frame, seed.declare_frames[0]),
            min(span.end_frame_exclusive, seed.declare_frames[1]),
        )
        seen_intersection = False
        prev_centroid: tuple[float, float] | None = None
        prev_area: int | None = None
        shifts: list[float] = []

        for index in declared:
            frame = np.asarray(frames[index - span.start_frame])
            sample = mask_source.sample(index, seed, frame)
            if sample is None:
                if open_run_start is not None:
                    occlusion_runs.append(OcclusionRun(open_run_start, index))
                    open_run_start = None
                gap_frames.append(index)
                continue
            if sample.mask is None:
                if sample.out_of_frame:
                    if open_run_start is not None:
                        occlusion_runs.append(OcclusionRun(open_run_start, index))
                        open_run_start = None
                    out_of_frame_frames.append(index)
                    continue
                if sample.present:
                    if open_run_start is None:
                        open_run_start = index
                    continue
                if open_run_start is not None:
                    occlusion_runs.append(OcclusionRun(open_run_start, index))
                    open_run_start = None
                gap_frames.append(index)
                continue
            if open_run_start is not None:
                occlusion_runs.append(OcclusionRun(open_run_start, index))
                open_run_start = None
            stats = mask_stats(sample.mask, seed.box)
            permission, denial, state = _permission_and_state(
                stats,
                all_canvas_ratio=all_canvas_ratio,
                hollow_ratio=hollow_ratio,
                min_area_px=min_area_px,
            )
            if denial is not None:
                track_flags.append(
                    Flag(denial, index, f"{seed.role_id}: mask denied by measured rule")
                )
            if int(stats.get("seed_intersection_px") or 0) > 0:
                seen_intersection = True
            elif denial is None:
                track_flags.append(
                    Flag(CODE_SEED_NOT_SEEN, index, f"{seed.role_id}: mask misses the seed box")
                )
            centroid = _centroid(stats)
            if prev_centroid is not None and centroid is not None:
                shift = (
                    (centroid[0] - prev_centroid[0]) ** 2 + (centroid[1] - prev_centroid[1]) ** 2
                ) ** 0.5
                shifts.append(shift)
                denom = max(1.0, float(stats.get("area_px") or 1) ** 0.5)
                if shift / denom > shift_ratio:
                    track_flags.append(
                        Flag(
                            CODE_OBSERVATION_INVALID,
                            index,
                            f"{seed.role_id}: unstable link shift={shift:.1f}px",
                        )
                    )
            area = int(stats.get("area_px") or 0)
            if prev_area and area:
                factor = max(area / prev_area, prev_area / area)
                if factor > area_jump_ratio:
                    track_flags.append(
                        Flag(
                            CODE_OBSERVATION_INVALID,
                            index,
                            f"{seed.role_id}: area jump x{factor:.2f}",
                        )
                    )
            bx, by, bw, bh = seed.box
            seed_cx, seed_cy = bx + bw / 2.0, by + bh / 2.0
            if centroid is not None:
                seed_diag = (bw * bw + bh * bh) ** 0.5
                drift = ((centroid[0] - seed_cx) ** 2 + (centroid[1] - seed_cy) ** 2) ** 0.5
                if seed_diag > 0 and drift / seed_diag > drift_ratio:
                    track_flags.append(
                        Flag(
                            CODE_OBSERVATION_INVALID,
                            index,
                            f"{seed.role_id}: drift {drift:.1f}px from seed box",
                        )
                    )
            if state == VISIBILITY_PARTIAL:
                partial_frames.append(index)
            crop_sha = _crop_sha256(frame, stats)
            observations.append(
                {
                    "frame": index,
                    "instance_id": _instance_id(seed),
                    "mask_sha256": mask_digest(sample.mask),
                    "area_px": area,
                    "coverage_ratio": float(stats.get("coverage_ratio") or 0.0),
                    "bbox": stats.get("bbox"),
                    "solidity": stats.get("solidity"),
                    "hole_ratio": stats.get("hole_ratio"),
                    "border_touch": bool(stats.get("border_touch")),
                    "state": state,
                    "permission": permission,
                    "denial_code": denial,
                    "method": sample.method,
                    "score": sample.score,
                    "crop_sha256": crop_sha,
                }
            )
            masks_by_role_frame[(seed.role_id, index)] = np.asarray(sample.mask).astype(bool)
            prev_centroid = centroid
            prev_area = area
        if open_run_start is not None:
            occlusion_runs.append(
                OcclusionRun(open_run_start, min(span.end_frame_exclusive, seed.declare_frames[1]))
            )

        granted = [item for item in observations if item["permission"] == PERMISSION_GRANTED]
        trace_complete = bool(granted) and seen_intersection
        if not seen_intersection and observations:
            track_flags.append(
                Flag(CODE_SEED_NOT_SEEN, None, f"{seed.role_id}: no mask ever met the seed box")
            )
            refused.append(
                SeedRefusal(
                    seed.role_id,
                    CODE_SEED_NOT_SEEN,
                    "no mask in the span intersected the seed box (wrong seed / wrong instance)",
                )
            )
        elif not trace_complete:
            refused.append(
                SeedRefusal(
                    seed.role_id,
                    CODE_NO_TRACE,
                    f"no granted frame→mask→track observation in {list(declared)}",
                )
            )
        if seed.partial_required and gap_frames:
            refused.append(
                SeedRefusal(
                    seed.role_id,
                    CODE_PARTIAL_DROPPED,
                    f"partial-required seed has {len(gap_frames)} gap frame(s): {gap_frames[:8]}",
                )
            )
            track_flags.append(
                Flag(CODE_PARTIAL_DROPPED, None, f"{seed.role_id}: gaps {gap_frames[:8]}")
            )
        stability = {
            "n_declared": len(list(declared)),
            "n_observed": len(observations),
            "n_granted": len(granted),
            "n_partial": len(partial_frames),
            "n_occluded_frames": sum(run.frames for run in occlusion_runs),
            "n_out_of_frame": len(out_of_frame_frames),
            "n_gap_frames": len(gap_frames),
            "mean_step_shift_px": (sum(shifts) / len(shifts)) if shifts else None,
            "max_step_shift_px": max(shifts) if shifts else None,
            "mean_area_px": (sum(int(item["area_px"]) for item in observations) / len(observations))
            if observations
            else None,
            "min_area_px": min((int(item["area_px"]) for item in observations), default=None),
            "max_area_px": max((int(item["area_px"]) for item in observations), default=None),
            "first_frame": observations[0]["frame"] if observations else None,
            "last_frame": observations[-1]["frame"] if observations else None,
        }
        tracks.append(
            RoleTrack(
                role_id=seed.role_id,
                kind=seed.kind,
                instance_id=_instance_id(seed),
                seed=seed,
                observations=tuple(observations),
                occlusion_runs=tuple(occlusion_runs),
                gap_frames=tuple(gap_frames),
                partial_frames=tuple(partial_frames),
                out_of_frame_frames=tuple(out_of_frame_frames),
                flags=tuple(track_flags),
                stability=stability,
                trace_complete=trace_complete,
            )
        )

    # Cross-seed ambiguity: two seeds claiming the same instance on one frame.
    for frame in sorted({key[1] for key in masks_by_role_frame}):
        keys = [key for key in masks_by_role_frame if key[1] == frame]
        for i, key_a in enumerate(keys):
            for key_b in keys[i + 1 :]:
                overlap = _union_iou(masks_by_role_frame[key_a], masks_by_role_frame[key_b])
                if overlap >= duplicate_iou:
                    artifact_flags.append(
                        Flag(
                            CODE_DUPLICATE_INSTANCE,
                            frame,
                            f"{key_a[0]} vs {key_b[0]}: mask IoU {overlap:.3f} >= {duplicate_iou}",
                        )
                    )

    engine = EngineRecord(
        engine_id=engine_id,
        provenance=provenance,
        probe=dict(probe) if probe is not None else None,
        probe_digest=payload_sha256(dict(probe)) if probe is not None else None,
        candidates=dict(getattr(mask_source, "candidates", {}) or {}),
        inference_ran=bool(getattr(mask_source, "inference_ran", False)),
    )

    artifact = RoleTracksArtifact(
        schema_version=TRACKS_SCHEMA_VERSION,
        source_sha256=source_sha256,
        span=span,
        fps_rational=fps_rational,
        frame_size=(width, height),
        engine=engine,
        manifest_sha256=manifest_sha256,
        manifest_version=manifest_version,
        seeds=seed_list,
        tracks=tuple(tracks),
        refused_seeds=tuple(refused),
        flags=tuple(artifact_flags),
        production=bool(production),
        digest="",
        extra=dict(extra or {}),
    )
    artifact = RoleTracksArtifact(**{**artifact.__dict__, "digest": artifact.recompute_digest()})

    if strict:
        hard_codes = {item.code for item in refused}
        if CODE_NO_TRACE in hard_codes:
            first = next(item for item in refused if item.code == CODE_NO_TRACE)
            raise RoleTracksError(CODE_NO_TRACE, f"{first.role_id}: {first.detail}")
        if CODE_SEED_NOT_SEEN in hard_codes:
            first = next(item for item in refused if item.code == CODE_SEED_NOT_SEEN)
            raise RoleTracksError(CODE_SEED_NOT_SEEN, f"{first.role_id}: {first.detail}")
        if CODE_PARTIAL_DROPPED in hard_codes:
            first = next(item for item in refused if item.code == CODE_PARTIAL_DROPPED)
            raise RoleTracksError(CODE_PARTIAL_DROPPED, f"{first.role_id}: {first.detail}")
        if any(flag.code == CODE_DUPLICATE_INSTANCE for flag in artifact.flags):
            first = next(flag for flag in artifact.flags if flag.code == CODE_DUPLICATE_INSTANCE)
            raise RoleTracksError(CODE_DUPLICATE_INSTANCE, first.detail)
    return artifact


def _centroid(stats: Mapping[str, Any]) -> tuple[float, float] | None:
    bbox = stats.get("bbox")
    if bbox is None:
        return None
    x, y, w, h = (int(v) for v in bbox)
    return (x + w / 2.0, y + h / 2.0)


def _instance_id(seed: RoleSeed) -> str:
    return f"trk:{seed.role_id}"


def _crop_sha256(frame: np.ndarray, stats: Mapping[str, Any]) -> str | None:
    bbox = stats.get("bbox")
    if bbox is None:
        return None
    x, y, w, h = (int(v) for v in bbox)
    height, width = frame.shape[:2]
    xa, xb = max(0, x), min(width, x + w)
    ya, yb = max(0, y), min(height, y + h)
    if xb <= xa or yb <= ya:
        return None
    crop = np.ascontiguousarray(frame[ya:yb, xa:xb])
    return hashlib.sha256(crop.tobytes()).hexdigest()


# ── artifact validation (tamper / invariant checks) ──────────────────────────


def check_artifact(
    artifact: RoleTracksArtifact,
    *,
    all_canvas_ratio: float = DEFAULT_ALL_CANVAS_RATIO,
    hollow_ratio: float = DEFAULT_HOLLOW_RATIO,
    min_area_px: int = DEFAULT_MIN_AREA_PX,
) -> tuple[str, ...]:
    """Re-verify the artifact's own invariants — returns violated codes.

    Runs on an ALREADY digest-verified artifact, so this catches producers that
    re-sealed an invalid record (the adversarial case the acceptance names).
    """
    violations: list[str] = []
    if artifact.schema_version != TRACKS_SCHEMA_VERSION:
        violations.append(CODE_VERSION_UNSUPPORTED)
    if artifact.recompute_digest() != artifact.digest:
        violations.append(CODE_DIGEST_MISMATCH)
    if artifact.production:
        if artifact.engine.provenance != PROVENANCE_PRODUCTION:
            violations.append(CODE_FIXTURE_NOT_PRODUCTION)
        probe_missing = artifact.engine.probe is None or not artifact.engine.probe_digest
        probe_status = None if probe_missing else str(dict(artifact.engine.probe).get("status", ""))
        if probe_missing or probe_status != STATUS_PROBED_READY:
            violations.append(CODE_ENGINE_UNPROBED)
    elif artifact.engine.provenance == PROVENANCE_PRODUCTION:
        # a production-provenance engine recorded as non-production is a lie
        violations.append(CODE_FIXTURE_NOT_PRODUCTION)
    if not artifact.tracks:
        violations.append(CODE_ARTIFACT_INVALID)
    covered = {track.role_id for track in artifact.tracks if track.trace_complete}
    for seed in artifact.seeds:
        if seed.role_id not in covered:
            violations.append(CODE_NO_TRACE)
    for track in artifact.tracks:
        for observation in track.observations:
            if str(observation.get("instance_id")) != track.instance_id:
                violations.append(CODE_INSTANCE_CHANGED)
                break
        for observation in track.observations:
            if observation.get("permission") != PERMISSION_GRANTED:
                continue
            coverage = float(observation.get("coverage_ratio") or 0.0)
            hole = observation.get("hole_ratio")
            area = int(observation.get("area_px") or 0)
            if area < max(0, int(min_area_px)) or coverage >= all_canvas_ratio:
                violations.append(
                    CODE_MASK_ALL_CANVAS if coverage >= all_canvas_ratio else CODE_MASK_EMPTY
                )
            elif hole is not None and float(hole) >= hollow_ratio:
                violations.append(CODE_MASK_HOLLOW)
    if artifact.engine.engine_id == ENGINE_SAM3 and not artifact.engine.inference_ran:
        violations.append(CODE_SAM3_UNPROBED)
    return tuple(dict.fromkeys(violations))


def assert_artifact(artifact: RoleTracksArtifact, **kwargs: Any) -> None:
    """Raise the FIRST violated invariant code (strict gate for callers)."""
    violations = check_artifact(artifact, **kwargs)
    if violations:
        raise RoleTracksError(
            CODE_ARTIFACT_INVALID, f"artifact invariants violated: {list(violations)}"
        )
    return None


# ── workflow manifest (app/media_workflows/role_segmentation_v1.json) ───────


@dataclass(frozen=True)
class WorkflowManifest:
    """The versioned role-segmentation workflow declaration."""

    workflow_id: str
    schema: str
    version: str
    engines: Mapping[str, Mapping[str, Any]]
    mask_rules: Mapping[str, Any]
    track_rules: Mapping[str, Any]
    refusal_codes: tuple[str, ...]
    digest: str
    raw: Mapping[str, Any]

    def engine_status(self, engine_id: str) -> str | None:
        entry = self.engines.get(engine_id)
        return None if entry is None else str(entry.get("status", ""))


def validate_workflow_manifest(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Structural + honesty checks on a workflow manifest (returns violations)."""
    violations: list[str] = []
    if str(payload.get("schema", "")) != MANIFEST_SCHEMA:
        violations.append(CODE_MANIFEST_INVALID)
    if str(payload.get("workflow_id", "")) != "role_segmentation_v1":
        violations.append(CODE_MANIFEST_INVALID)
    engines = payload.get("engines")
    if not isinstance(engines, Mapping) or not engines:
        violations.append(CODE_MANIFEST_INVALID)
        return tuple(dict.fromkeys(violations))
    for engine_id, entry in engines.items():
        if not isinstance(entry, Mapping):
            violations.append(CODE_MANIFEST_INVALID)
            continue
        status = str(entry.get("status", ""))
        if status not in (
            STATUS_PROBED_READY,
            STATUS_NOT_RUN,
            STATUS_BLOCKED_DEPENDENCY,
            STATUS_CI_ONLY,
        ):
            violations.append(CODE_ENGINE_UNPROBED)
        if (
            engine_id == ENGINE_SAM3
            and status == STATUS_PROBED_READY
            and not entry.get("probe_run")
        ):
            # SAM3 may only be AVAILABLE_PROBED with a real run record attached.
            violations.append(CODE_SAM3_UNPROBED)
    for section in ("mask_rules", "track_rules"):
        if not isinstance(payload.get(section), Mapping) or not payload.get(section):
            violations.append(CODE_MANIFEST_INVALID)
    codes = payload.get("refusal_codes")
    if not isinstance(codes, Sequence) or isinstance(codes, (str, bytes)) or not codes:
        violations.append(CODE_MANIFEST_INVALID)
    return tuple(dict.fromkeys(violations))


def load_workflow_manifest(path: str | Path) -> WorkflowManifest:
    """Load + validate the on-disk manifest; refuse an invalid/honesty-broken one."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise RoleTracksError(CODE_MANIFEST_INVALID, f"manifest not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise RoleTracksError(CODE_MANIFEST_INVALID, f"manifest unreadable: {err}") from err
    violations = validate_workflow_manifest(payload)
    if violations:
        raise RoleTracksError(CODE_MANIFEST_INVALID, f"manifest violates: {list(violations)}")
    body = {key: value for key, value in payload.items() if key != "digest"}
    declared = payload.get("digest")
    if declared is not None and str(declared) != payload_sha256(body):
        raise RoleTracksError(
            CODE_MANIFEST_INVALID,
            f"manifest digest {declared!r} != payload digest {payload_sha256(body)!r}",
        )
    return WorkflowManifest(
        workflow_id=str(payload["workflow_id"]),
        schema=str(payload["schema"]),
        version=str(payload["version"]),
        engines={str(k): dict(v) for k, v in payload["engines"].items()},
        mask_rules=dict(payload["mask_rules"]),
        track_rules=dict(payload["track_rules"]),
        refusal_codes=tuple(str(code) for code in payload["refusal_codes"]),
        digest=str(payload.get("digest", "")) or payload_sha256(body),
        raw=payload,
    )

"""Source interaction facts producer (MF-END-13, product requirement U08/U09/U21).

The missing SOURCE-SIDE producer that turns REAL role/prop tracks and REAL
decoded source frames into measured interaction facts — contact (who holds
what), occlusion order (what is in front of what) and camera/scene motion —
and publishes them through the EXISTING structural-evidence authority.

Contract (fail-closed, measurement-only, zero invented facts):

- Inputs are measured records, never config: the role/prop tracks come from
  the sealed ``mf.source_role_tracks.v1`` artifact (MF-END-12 — SAM2.1 masks
  on the real source) and the camera estimate comes from the REAL decoded
  frames.  A declared interaction/config may only be COMPARED against the
  measurement (``compare_declared``); it never creates, widens or edits a
  fact.  Every fact carries its measured numbers and its evidence refs.
- Missing data is an explicit ``blocked`` observation with a POSITION
  (frame + role/window), never an empty list that reads as "clean" (U21).
- Publishing goes through ``StructuralEvidenceRepository.create_contact /
  create_occlusion / create_motion`` ONLY.  Both endpoints of a contact or
  occlusion fact must be REAL current occurrence segments; when the second
  real endpoint is absent the publish is REFUSED with a typed code
  (``SOURCE_FACTS_SECOND_SEGMENT_MISSING``) — a fake second segment is never
  created to satisfy a schema ("không fake second segment").
- Sealed source facts are immutable: an output-side claim that contradicts a
  sealed source fact is refused (``SOURCE_FACTS_OUTPUT_OVERWRITE``); replay
  of the SAME fact converges (idempotent keys), a different payload for the
  same fact identity is a typed conflict.
- Thresholds are declared here, versioned by ``POLICY_VERSION``, echoed in
  every artifact and compared by tests — they are never tuned after a run to
  turn a red row green.

Not in scope (bounded): no GPU inference here (tracks are produced by
MF-END-12), no render, no output-side QC, no second segment fabrication.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.persistence.structural_evidence import (
    ContactConflictError,
    OcclusionConflictError,
    StructuralEvidenceRepository,
    canonical_json,
)
from app.services import source_role_tracks as srt

__all__ = [
    "ALGORITHM",
    "ALGORITHM_VERSION",
    "CAMERA_BORDER_FRACTION",
    "CAMERA_CUT_MIN_MAD",
    "CAMERA_DOWNSCALE_WIDTH",
    "CAMERA_EVENT_MIN_MAD",
    "CAMERA_EVENT_MIN_RATIO",
    "CAMERA_MIN_RESPONSE",
    "CAMERA_PAN_MIN_PX_PER_FRAME",
    "CAMERA_SAMPLE_STRIDE",
    "CAMERA_STATIC_MAX_PX_PER_FRAME",
    "CONTACT_KIND_GRASP",
    "CONTACT_KIND_TOUCH",
    "CONTACT_MAX_GAP_PX",
    "CONTACT_MIN_CONTAINMENT",
    "CONTACT_MIN_FRAMES",
    "CONTENT_MIN_MEASURED_FRAMES",
    "CONTENT_MIN_TOTAL_PX",
    "CONTENT_STATIC_MAX_PX_PER_FRAME",
    "CAMERA_SHIFT_CAP_FRACTION",
    "UNIFORM_MIN_STD",
    "OCCLUSION_MIN_CONTAINMENT",
    "OCCLUSION_MIN_VISIBLE_FRAMES",
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "STATE_CHANGE_AREA_RATIO",
    "STATE_CHANGE_SHIFT_PX",
    "BlockedObservation",
    "CameraWindowFact",
    "ContactFact",
    "FactSet",
    "OcclusionFact",
    "PublishOutcome",
    "SourceFactsError",
    "bind_facts",
    "build_artifact",
    "check_artifact",
    "check_output_overwrite",
    "compare_declared",
    "derive_contact_facts",
    "derive_occlusion_facts",
    "estimate_camera",
    "fact_id",
    "payload_sha256",
    "publish_facts",
    "track_change_frames",
]

SCHEMA_VERSION = "mf.source_interaction_facts.v1"
POLICY_VERSION = "source-interaction-facts-v1"

#: Algorithm identity stamped on every published row (provenance authority).
ALGORITHM = "source-interaction-facts"
ALGORITHM_VERSION = "1"

#: Contact kinds REUSED from the closed structural-evidence enum: a person
#: holding a prop is ``grasp``; a prop touching the person/hand without a
#: measured containment is ``touch``.  No new kind is invented.
CONTACT_KIND_GRASP = "grasp"
CONTACT_KIND_TOUCH = "touch"

# ── declared measurement thresholds (measured values are below) ───────────────
#: Bbox edge gap (px) at/below which two instances are in contact.
CONTACT_MAX_GAP_PX = 8.0
#: Fraction of the object bbox that must lie inside the subject bbox for the
#: contact to be a HOLD (grasp) rather than a touch.
CONTACT_MIN_CONTAINMENT = 0.55
#: A contact interval shorter than this many frames is not bounded as a fact.
CONTACT_MIN_FRAMES = 2
#: Same containment floor for the "object is in front of the subject body"
#: occlusion reading (a visible object inside the subject bbox is in front).
OCCLUSION_MIN_CONTAINMENT = 0.55
#: Minimum visible frames for an occlusion reading to be a fact.
OCCLUSION_MIN_VISIBLE_FRAMES = 2
#: Track-series change point: relative area jump between consecutive frames.
STATE_CHANGE_AREA_RATIO = 0.30
#: Track-series change point: bbox centre shift between consecutive frames.
STATE_CHANGE_SHIFT_PX = 12.0

#: Camera estimate sampling.
CAMERA_DOWNSCALE_WIDTH = 160
CAMERA_BORDER_FRACTION = 0.10
#: Median border motion (px/frame) at/below which the camera reads STATIC.
CAMERA_STATIC_MAX_PX_PER_FRAME = 0.12
#: Median border motion (px/frame) at/above which the camera reads a PAN.
CAMERA_PAN_MIN_PX_PER_FRAME = 0.30
#: Mean-absolute-luma-difference at/above which a frame boundary is a CUT.
CAMERA_CUT_MIN_MAD = 12.0
#: A content event is a MAD spike without camera discontinuity.
CAMERA_EVENT_MIN_MAD = 0.35
CAMERA_EVENT_MIN_RATIO = 8.0
#: Median phase-correlation response below which the estimate is UNSUPPORTED.
CAMERA_MIN_RESPONSE = 0.30
#: Bounded series recorded in a camera fact (every Nth frame).
CAMERA_SAMPLE_STRIDE = 4
#: Content motion (centre band) — measured with phase correlation.
#: A segment counts as moving content when its cumulative displacement is at
#: least ``CONTENT_MIN_TOTAL_PX`` and its per-frame median is above the
#: content-static floor; otherwise it reads as static content.
CONTENT_MIN_TOTAL_PX = 2.0
CONTENT_STATIC_MAX_PX_PER_FRAME = 0.03
CONTENT_MIN_MEASURED_FRAMES = 5
#: A masked band whose luma std is below this carries no texture to lock on —
#: the pair yields NO measurement (counted, never guessed).
UNIFORM_MIN_STD = 1.0
#: A phase-correlation lock larger than this fraction of the frame is
#: implausible and is discarded as a degenerate lock.
CAMERA_SHIFT_CAP_FRACTION = 0.25

CLASS_STATIC = "static"
CLASS_PAN = "pan"
CLASS_UNSUPPORTED = "unsupported"
CAMERA_CLASSIFICATIONS = (CLASS_STATIC, CLASS_PAN, CLASS_UNSUPPORTED)

# ── typed refusal codes ──────────────────────────────────────────────────────
CODE_TRACKS_INVALID = "SOURCE_FACTS_TRACKS_INVALID"
CODE_VERSION_UNSUPPORTED = "SOURCE_FACTS_VERSION_UNSUPPORTED"
CODE_DIGEST_MISMATCH = "SOURCE_FACTS_DIGEST_MISMATCH"
CODE_ARTIFACT_INVALID = "SOURCE_FACTS_ARTIFACT_INVALID"
CODE_SERIALIZATION_INVALID = "SOURCE_FACTS_SERIALIZATION_INVALID"
CODE_NOT_PRODUCTION = "SOURCE_FACTS_NOT_PRODUCTION"
CODE_MISSING_DATA = "SOURCE_FACTS_MISSING_DATA"
CODE_OCCLUDER_UNMEASURED = "SOURCE_FACTS_OCCLUDER_UNMEASURED"
CODE_SECOND_SEGMENT_MISSING = "SOURCE_FACTS_SECOND_SEGMENT_MISSING"
CODE_SEGMENT_MISSING = "SOURCE_FACTS_SEGMENT_MISSING"
CODE_SOURCE_CHANGED = "SOURCE_FACTS_SOURCE_CHANGED"
CODE_FACT_CONFLICT = "SOURCE_FACTS_FACT_CONFLICT"
CODE_OUTPUT_OVERWRITE = "SOURCE_FACTS_OUTPUT_OVERWRITE"
CODE_UNKNOWN_FACT = "SOURCE_FACTS_UNKNOWN_FACT"
CODE_CROP_MISMATCH = "SOURCE_FACTS_CROP_MISMATCH"
CODE_WINDOW_INVALID = "SOURCE_FACTS_WINDOW_INVALID"


class SourceFactsError(ValueError):
    """Typed refusal with a stable machine-readable code."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def payload_sha256(payload: Any) -> str:
    """Digest of the canonical JSON encoding (sealing + idempotency)."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _finite(value: Any, path: str) -> None:
    """Fail-closed finite walk — a non-finite measurement never survives."""
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SourceFactsError(CODE_ARTIFACT_INVALID, f"non-finite at {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _finite(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite(item, f"{path}[{index}]")
        return
    raise SourceFactsError(CODE_ARTIFACT_INVALID, f"unserialisable at {path}")


def _ms(frame: int, fps_rational: str) -> int:
    """Exact frame -> ms conversion from the measured rational fps."""
    try:
        num_s, den_s = str(fps_rational).split("/")
        num, den = int(num_s), int(den_s)
    except (ValueError, AttributeError) as err:
        raise SourceFactsError(
            CODE_TRACKS_INVALID, f"fps_rational {fps_rational!r} is unreadable"
        ) from err
    if num <= 0 or den <= 0:
        raise SourceFactsError(
            CODE_TRACKS_INVALID, f"fps_rational {fps_rational!r} is not positive"
        )
    return round(frame * 1000 * den / num)


# ── records ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BlockedObservation:
    """A fact that could NOT be measured — with its exact position (U21)."""

    kind: str
    code: str
    position: Mapping[str, Any]
    detail: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "code": self.code,
            "position": dict(self.position),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ContactFact:
    """A measured subject<->object contact interval."""

    subject_role_id: str
    subject_instance_id: str
    object_role_id: str
    object_instance_id: str
    kind: str
    start_frame: int
    end_frame: int  # exclusive
    measured: Mapping[str, Any]
    evidence: Mapping[str, Any]
    confidence: float
    confidence_source: str = "derived"

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame

    def to_payload(self) -> dict[str, Any]:
        return {
            "subject_role_id": self.subject_role_id,
            "subject_instance_id": self.subject_instance_id,
            "object_role_id": self.object_role_id,
            "object_instance_id": self.object_instance_id,
            "kind": self.kind,
            "start_frame": int(self.start_frame),
            "end_frame": int(self.end_frame),
            "frames": int(self.frames),
            "measured": dict(self.measured),
            "evidence": dict(self.evidence),
            "confidence": float(self.confidence),
            "confidence_source": self.confidence_source,
        }


@dataclass(frozen=True)
class OcclusionFact:
    """A measured occlusion ordering: ``occluder`` in front of ``occludee``."""

    occluder_role_id: str
    occluder_instance_id: str
    occludee_role_id: str
    occludee_instance_id: str
    order: str
    start_frame: int
    end_frame: int  # exclusive
    measured: Mapping[str, Any]
    evidence: Mapping[str, Any]
    confidence: float
    confidence_source: str = "derived"

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame

    def to_payload(self) -> dict[str, Any]:
        return {
            "occluder_role_id": self.occluder_role_id,
            "occluder_instance_id": self.occluder_instance_id,
            "occludee_role_id": self.occludee_role_id,
            "occludee_instance_id": self.occludee_instance_id,
            "order": self.order,
            "start_frame": int(self.start_frame),
            "end_frame": int(self.end_frame),
            "frames": int(self.frames),
            "measured": dict(self.measured),
            "evidence": dict(self.evidence),
            "confidence": float(self.confidence),
            "confidence_source": self.confidence_source,
        }


@dataclass(frozen=True)
class CameraWindowFact:
    """One measured camera/scene-motion reading for a REAL source window."""

    window_id: str
    span: Mapping[str, int]
    classification: str
    cut_frames: tuple[int, ...]
    content_events: tuple[int, ...]
    segments_order: tuple[tuple[int, int], ...]
    border_drift: Mapping[str, Any]
    border_response_median: float
    content_motion: Mapping[str, Any] | None
    declared_crop: Mapping[str, Any] | None
    unsupported_reason: str | None
    samples: tuple[tuple[int, float, float], ...]
    confidence: float
    confidence_source: str = "derived"

    @property
    def publishable(self) -> bool:
        return self.classification in (CLASS_STATIC, CLASS_PAN)

    def to_payload(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "span": dict(self.span),
            "classification": self.classification,
            "cut_frames": list(self.cut_frames),
            "content_events": list(self.content_events),
            "segments_order": [list(item) for item in self.segments_order],
            "border_drift": dict(self.border_drift),
            "border_response_median": float(self.border_response_median),
            "content_motion": (
                dict(self.content_motion) if self.content_motion else None
            ),
            "declared_crop": (
                dict(self.declared_crop) if self.declared_crop else None
            ),
            "unsupported_reason": self.unsupported_reason,
            "samples": [list(item) for item in self.samples],
            "confidence": float(self.confidence),
            "confidence_source": self.confidence_source,
        }


@dataclass(frozen=True)
class FactSet:
    """The sealed facts artifact (built once, digest-pinned)."""

    payload: Mapping[str, Any]

    @property
    def digest(self) -> str:
        return str(self.payload.get("digest", ""))

    def to_payload(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class PublishOutcome:
    """Durable publish accounting (created vs idempotent replay)."""

    artifact_digest: str
    contacts_created: int
    contacts_replayed: int
    occlusions_created: int
    occlusions_replayed: int
    motions_created: int
    motions_replayed: int
    segment_ids: tuple[str, ...] = field(default_factory=tuple)


# ── numeric helpers ──────────────────────────────────────────────────────────


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _bbox(observation: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    raw = observation.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    x, y, w, h = (_num(v) for v in raw)
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _visible_observations(track: srt.RoleTrack) -> list[dict[str, Any]]:
    """Granted observations with a usable bbox, ordered by frame index."""
    rows: list[dict[str, Any]] = []
    for item in track.observations:
        if str(item.get("permission")) != srt.PERMISSION_GRANTED:
            continue
        if _bbox(item) is None:
            continue
        rows.append(dict(item))
    rows.sort(key=lambda item: int(item.get("frame", 0)))
    return rows


def _gap_px(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """Edge-to-edge distance between two boxes (0.0 when they overlap)."""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return math.hypot(dx, dy)


def _containment(
    subject: tuple[float, float, float, float],
    object_box: tuple[float, float, float, float],
) -> float:
    """Intersection area / object area (1.0 = object fully inside subject)."""
    ax0, ay0, aw, ah = subject
    bx0, by0, bw, bh = object_box
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    return (ix * iy) / (bw * bh)


def _runs(frames: Iterable[int], *, min_len: int) -> list[tuple[int, int]]:
    """Maximal consecutive-frame runs of length >= ``min_len`` (exclusive end)."""
    ordered = sorted(int(f) for f in frames)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    prev: int | None = None
    for frame in ordered:
        if start is None:
            start = prev = frame
            continue
        if prev is not None and frame == prev + 1:
            prev = frame
            continue
        if prev is not None and prev - start + 1 >= min_len:
            runs.append((start, prev + 1))
        start = prev = frame
    if start is not None and prev is not None and prev - start + 1 >= min_len:
        runs.append((start, prev + 1))
    return runs


def _split_runs(
    run: tuple[int, int], change_frames: Iterable[int]
) -> list[tuple[int, int]]:
    """Split ``[start, end)`` at measured change frames strictly inside it."""
    cuts = sorted({int(f) for f in change_frames if run[0] < int(f) < run[1]})
    if not cuts:
        return [run]
    pieces: list[tuple[int, int]] = []
    cursor = run[0]
    for cut in cuts:
        if cut > cursor:
            pieces.append((cursor, cut))
        cursor = cut
    if cursor < run[1]:
        pieces.append((cursor, run[1]))
    return [piece for piece in pieces if piece[1] - piece[0] >= CONTACT_MIN_FRAMES]


def track_change_frames(track: srt.RoleTrack) -> tuple[int, ...]:
    """Measured change points of one track series (area jump / centre shift).

    Everything is computed from the REAL observation numbers; no declared
    semantic (e.g. "book opens") is needed or invented here.
    """
    rows = _visible_observations(track)
    changes: list[int] = []
    for prev, cur in zip(rows, rows[1:]):
        prev_box, cur_box = _bbox(prev), _bbox(cur)
        if prev_box is None or cur_box is None:
            continue
        frame = int(cur.get("frame", 0))
        prev_area = _num(prev.get("area_px"))
        cur_area = _num(cur.get("area_px"))
        if prev_area > 0 and abs(cur_area - prev_area) / prev_area >= STATE_CHANGE_AREA_RATIO:
            changes.append(frame)
            continue
        dx = (prev_box[0] + prev_box[2] / 2) - (cur_box[0] + cur_box[2] / 2)
        dy = (prev_box[1] + prev_box[3] / 2) - (cur_box[1] + cur_box[3] / 2)
        if math.hypot(dx, dy) >= STATE_CHANGE_SHIFT_PX:
            changes.append(frame)
    return tuple(sorted(set(changes)))


# ── derivation: contacts ─────────────────────────────────────────────────────


def derive_contact_facts(
    artifact: srt.RoleTracksArtifact,
    *,
    change_frames: Sequence[int] = (),
) -> tuple[tuple[ContactFact, ...], tuple[BlockedObservation, ...]]:
    """Measured person<->prop contacts from the REAL tracked observations."""
    facts: list[ContactFact] = []
    blocked: list[BlockedObservation] = []
    persons = [t for t in artifact.tracks if t.kind == srt.ROLE_KIND_PERSON]
    props = [t for t in artifact.tracks if t.kind == srt.ROLE_KIND_PROP]

    for person in persons:
        person_rows = {int(r["frame"]): r for r in _visible_observations(person)}
        for prop in props:
            prop_rows = {int(r["frame"]): r for r in _visible_observations(prop)}
            shared = sorted(set(person_rows) & set(prop_rows))
            grasp_frames: list[int] = []
            touch_frames: list[int] = []
            gaps: dict[int, float] = {}
            contains: dict[int, float] = {}
            for frame in shared:
                p_box = _bbox(person_rows[frame])
                o_box = _bbox(prop_rows[frame])
                if p_box is None or o_box is None:
                    continue
                gap = _gap_px(p_box, o_box)
                contain = _containment(p_box, o_box)
                gaps[frame] = gap
                contains[frame] = contain
                if gap <= CONTACT_MAX_GAP_PX:
                    if contain >= CONTACT_MIN_CONTAINMENT:
                        grasp_frames.append(frame)
                    else:
                        touch_frames.append(frame)

            for kind, frames in (
                (CONTACT_KIND_GRASP, grasp_frames),
                (CONTACT_KIND_TOUCH, touch_frames),
            ):
                for run in _runs(frames, min_len=CONTACT_MIN_FRAMES):
                    for piece in _split_runs(run, change_frames):
                        start, end = piece
                        piece_gaps = [gaps[f] for f in range(start, end) if f in gaps]
                        piece_cont = [contains[f] for f in range(start, end) if f in contains]
                        mean_contain = sum(piece_cont) / len(piece_cont)
                        if kind == CONTACT_KIND_GRASP:
                            confidence = mean_contain
                        else:
                            confidence = max(
                                0.0,
                                1.0
                                - (sorted(piece_gaps)[len(piece_gaps) // 2] / CONTACT_MAX_GAP_PX),
                            )
                        first = prop_rows[start]
                        last = prop_rows[end - 1]
                        facts.append(
                            ContactFact(
                                subject_role_id=person.role_id,
                                subject_instance_id=person.instance_id,
                                object_role_id=prop.role_id,
                                object_instance_id=prop.instance_id,
                                kind=kind,
                                start_frame=start,
                                end_frame=end,
                                measured={
                                    "frames": end - start,
                                    "min_gap_px": round(min(piece_gaps), 4),
                                    "median_gap_px": round(
                                        sorted(piece_gaps)[len(piece_gaps) // 2], 4
                                    ),
                                    "max_gap_px": round(max(piece_gaps), 4),
                                    "mean_containment": round(mean_contain, 6),
                                    "contained_frames": sum(
                                        1 for c in piece_cont if c >= CONTACT_MIN_CONTAINMENT
                                    ),
                                },
                                evidence={
                                    "frames": [start, end - 1],
                                    "mask_sha256_first": str(first.get("mask_sha256")),
                                    "mask_sha256_last": str(last.get("mask_sha256")),
                                    "method": "bbox_gap+containment",
                                },
                                confidence=round(min(1.0, max(0.0, confidence)), 6),
                                confidence_source="derived",
                            )
                        )
            if not grasp_frames and not touch_frames and not shared:
                # No shared VISIBLE frame at all: the pair cannot be decided —
                # that is missing data, with its position (U21).  A pair with
                # measured frames but no contact signal is a measured NEGATIVE
                # (no fact, no blocked entry).
                blocked.append(
                    BlockedObservation(
                        kind="contact",
                        code=CODE_MISSING_DATA,
                        position={
                            "subject_role_id": person.role_id,
                            "object_role_id": prop.role_id,
                            "frames": "span",
                        },
                        detail=(
                            "no shared frame where both real tracks are visible; "
                            "the contact cannot be decided"
                        ),
                    )
                )
    return tuple(facts), tuple(blocked)


# ── derivation: occlusions ───────────────────────────────────────────────────


def derive_occlusion_facts(
    artifact: srt.RoleTracksArtifact,
) -> tuple[tuple[OcclusionFact, ...], tuple[BlockedObservation, ...]]:
    """Measured occlusion orderings from the REAL tracks.

    Two measurable cues, both from live observations:

    * an occlusion RUN on a track (present but no usable mask) whose interval
      overlaps another track's granted frames -> that other track is the
      measured occluder (the only real candidate in front of it);
    * a prop that is VISIBLE and CONTAINED inside a person's bbox -> the prop
      is in front of that person's body (a visible object inside an occupied
      silhouette occludes it).  A contained-but-not-visible prop is NOT a fact.
    """
    facts: list[OcclusionFact] = []
    blocked: list[BlockedObservation] = []

    for track in artifact.tracks:
        for run in track.occlusion_runs:
            # The reference extent while the instance has no usable mask is its
            # DECLARED seed box (a real measurement of the instance's extent);
            # the last visible bbox is the fallback when no seed box exists.
            reference: tuple[float, float, float, float] | None = None
            seed_box = getattr(track.seed, "box", None)
            if seed_box:
                reference = (
                    float(seed_box[0]),
                    float(seed_box[1]),
                    float(seed_box[2]),
                    float(seed_box[3]),
                )
            if reference is None:
                visible_fallback = _visible_observations(track)
                reference = (
                    _bbox(visible_fallback[-1]) if visible_fallback else None
                )
            if reference is None:
                blocked.append(
                    BlockedObservation(
                        kind="occlusion",
                        code=CODE_MISSING_DATA,
                        position={
                            "occludee_role_id": track.role_id,
                            "start_frame": run.start_frame,
                            "end_frame": run.end_frame,
                        },
                        detail=(
                            "no reference extent (seed box / visible frame) to bound "
                            "the occluder against"
                        ),
                    )
                )
                continue
            overlaps: list[tuple[str, str, float]] = []
            for other in artifact.tracks:
                if other.role_id == track.role_id:
                    continue
                other_rows = {
                    int(r["frame"]): r for r in _visible_observations(other)
                }
                ratios: list[float] = []
                for frame in range(run.start_frame, run.end_frame):
                    row = other_rows.get(frame)
                    if row is None:
                        continue
                    other_box = _bbox(row)
                    if other_box is None:
                        continue
                    # measured: how much of the occludee's reference extent the
                    # candidate occluder's granted box covers while it disappears
                    ratios.append(_containment(other_box, reference))
                if len(ratios) >= OCCLUSION_MIN_VISIBLE_FRAMES:
                    mean_ratio = sum(ratios) / len(ratios)
                    # A candidate that barely grazes the reference extent is NOT
                    # named the occluder — a weak candidate stays unmeasured.
                    if mean_ratio >= OCCLUSION_MIN_CONTAINMENT:
                        overlaps.append(
                            (other.role_id, other.instance_id, mean_ratio)
                        )
            if not overlaps:
                blocked.append(
                    BlockedObservation(
                        kind="occlusion",
                        code=CODE_OCCLUDER_UNMEASURED,
                        position={
                            "occludee_role_id": track.role_id,
                            "start_frame": run.start_frame,
                            "end_frame": run.end_frame,
                        },
                        detail=(
                            "no other REAL track observed overlapping the occlusion "
                            "run; an occluder is not invented"
                        ),
                    )
                )
                continue
            overlaps.sort(key=lambda item: (-item[2], item[0]))
            occluder_role, occluder_instance, overlap_ratio = overlaps[0]
            facts.append(
                OcclusionFact(
                    occluder_role_id=occluder_role,
                    occluder_instance_id=occluder_instance,
                    occludee_role_id=track.role_id,
                    occludee_instance_id=track.instance_id,
                    order="in_front_of",
                    start_frame=int(run.start_frame),
                    end_frame=int(run.end_frame),
                    measured={
                        "frames": run.frames,
                        "overlap_ratio": round(overlap_ratio, 6),
                        "cue": "occlusion_run",
                    },
                    evidence={
                        "occludee_run": [
                            int(run.start_frame),
                            int(run.end_frame),
                        ],
                        "reference": "seed_box",
                        "cue": "occlusion_run",
                    },
                    confidence=round(min(1.0, max(0.0, overlap_ratio)), 6),
                    confidence_source="derived",
                )
            )

    persons = [t for t in artifact.tracks if t.kind == srt.ROLE_KIND_PERSON]
    props = [t for t in artifact.tracks if t.kind == srt.ROLE_KIND_PROP]
    for prop in props:
        prop_rows = {int(r["frame"]): r for r in _visible_observations(prop)}
        for person in persons:
            person_rows = {int(r["frame"]): r for r in _visible_observations(person)}
            frames: list[int] = []
            contains: dict[int, float] = {}
            for frame in sorted(set(prop_rows) & set(person_rows)):
                p_box = _bbox(person_rows[frame])
                o_box = _bbox(prop_rows[frame])
                if p_box is None or o_box is None:
                    continue
                contain = _containment(p_box, o_box)
                contains[frame] = contain
                if contain >= OCCLUSION_MIN_CONTAINMENT:
                    frames.append(frame)
            for run in _runs(frames, min_len=OCCLUSION_MIN_VISIBLE_FRAMES):
                start, end = run
                piece_cont = [contains[f] for f in range(start, end) if f in contains]
                mean_contain = sum(piece_cont) / len(piece_cont)
                first, last = prop_rows[start], prop_rows[end - 1]
                facts.append(
                    OcclusionFact(
                        occluder_role_id=prop.role_id,
                        occluder_instance_id=prop.instance_id,
                        occludee_role_id=person.role_id,
                        occludee_instance_id=person.instance_id,
                        order="in_front_of",
                        start_frame=start,
                        end_frame=end,
                        measured={
                            "frames": end - start,
                            "mean_containment": round(mean_contain, 6),
                            "cue": "visible_containment",
                        },
                        evidence={
                            "frames": [start, end - 1],
                            "mask_sha256_first": str(first.get("mask_sha256")),
                            "mask_sha256_last": str(last.get("mask_sha256")),
                            "cue": "visible_containment",
                        },
                        confidence=round(min(1.0, max(0.0, mean_contain)), 6),
                        confidence_source="derived",
                    )
                )
    return tuple(facts), tuple(blocked)


# ── derivation: camera / scene motion ────────────────────────────────────────


def _border_mask(height: int, width: int, frac: float) -> np.ndarray:
    mask = np.ones((height, width), np.float32)
    bh = max(1, int(round(height * frac)))
    bw = max(1, int(round(width * frac)))
    mask[bh : height - bh, bw : width - bw] = 0.0
    return mask


def _centre_mask(height: int, width: int, frac: float) -> np.ndarray:
    mask = np.zeros((height, width), np.float32)
    bh = max(1, int(round(height * frac)))
    bw = max(1, int(round(width * frac)))
    mask[bh : height - bh, bw : width - bw] = 1.0
    return mask


def _phase_shift(
    first: np.ndarray, second: np.ndarray, mask: np.ndarray | None
) -> tuple[float, float, float]:
    window = cv2.createHanningWindow((first.shape[1], first.shape[0]), cv2.CV_32F)
    a = np.float32(first) * (mask if mask is not None else 1.0)
    b = np.float32(second) * (mask if mask is not None else 1.0)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    return float(dx), float(dy), float(response)


def estimate_camera(
    window_id: str,
    frames: Sequence[np.ndarray],
    *,
    span: Mapping[str, int],
    declared_crop: Mapping[str, Any] | None = None,
) -> tuple[CameraWindowFact, tuple[BlockedObservation, ...]]:
    """Measured camera/scene reading for one REAL decoded source window.

    Distinguishes CUT (hard discontinuity), intended CROP (declared and
    pixel-consistent) and UNSUPPORTED observations (ambiguous border motion
    or a weak correlation response) — an unsupported reading is recorded as a
    blocked observation with its position and is never published.
    """
    blocked: list[BlockedObservation] = []
    start = int(span.get("start_frame", 0))
    end = int(span.get("end_frame_exclusive", 0))
    if end <= start:
        raise SourceFactsError(
            CODE_WINDOW_INVALID, f"window {window_id!r} span [{start}, {end}) is empty"
        )
    if len(frames) != end - start:
        raise SourceFactsError(
            CODE_WINDOW_INVALID,
            f"window {window_id!r} got {len(frames)} frames for span [{start}, {end})",
        )
    shapes = {f.shape[:2] for f in frames}
    if len(shapes) != 1:
        raise SourceFactsError(
            CODE_WINDOW_INVALID, f"window {window_id!r} frames have mixed sizes"
        )
    height, width = next(iter(shapes))
    declared = dict(declared_crop) if declared_crop else None
    if declared is not None:
        rect = declared.get("rect")
        if (
            not isinstance(rect, (list, tuple))
            or len(rect) != 4
            or int(rect[2]) != width
            or int(rect[3]) != height
        ):
            blocked.append(
                BlockedObservation(
                    kind="camera",
                    code=CODE_CROP_MISMATCH,
                    position={"window_id": window_id, "frame": start},
                    detail=(
                        "declared crop rect does not match the decoded frame size; "
                        "the crop claim is not pixel-consistent"
                    ),
                )
            )

    if len(frames) < 2:
        fact = CameraWindowFact(
            window_id=window_id,
            span={"start_frame": start, "end_frame_exclusive": end},
            classification=CLASS_UNSUPPORTED,
            cut_frames=(),
            content_events=(),
            segments_order=((start, end),),
            border_drift={"dx": 0.0, "dy": 0.0, "px_per_frame_median": 0.0},
            border_response_median=0.0,
            content_motion=None,
            declared_crop=declared,
            unsupported_reason="single_frame_window",
            samples=(),
            confidence=0.0,
        )
        blocked.append(
            BlockedObservation(
                kind="camera",
                code=CODE_MISSING_DATA,
                position={"window_id": window_id, "frame": start},
                detail="a single-frame window cannot bound camera motion",
            )
        )
        return fact, tuple(blocked)

    target_h = max(2, int(round(height * CAMERA_DOWNSCALE_WIDTH / width)))
    small = [
        cv2.cvtColor(
            cv2.resize(frame, (CAMERA_DOWNSCALE_WIDTH, target_h), interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2GRAY,
        )
        for frame in frames
    ]
    border = _border_mask(target_h, CAMERA_DOWNSCALE_WIDTH, CAMERA_BORDER_FRACTION)
    centre = _centre_mask(target_h, CAMERA_DOWNSCALE_WIDTH, CAMERA_BORDER_FRACTION + 0.05)

    # pass 1 — MAD scan (cut / content-event detection on the full frames).
    rows: list[dict[str, Any]] = []
    for index in range(1, len(small)):
        mad = float(
            np.mean(
                np.abs(
                    small[index].astype(np.float32) - small[index - 1].astype(np.float32)
                )
            )
        )
        rows.append({"frame": start + index, "mad": mad})

    sorted_mad = sorted(row["mad"] for row in rows)
    median_mad = sorted_mad[len(sorted_mad) // 2]
    cut_frames = tuple(
        int(row["frame"]) for row in rows if row["mad"] >= CAMERA_CUT_MIN_MAD
    )
    event_floor = max(CAMERA_EVENT_MIN_MAD, CAMERA_EVENT_MIN_RATIO * median_mad)
    content_events = tuple(
        int(row["frame"])
        for row in rows
        if row["mad"] >= event_floor and int(row["frame"]) not in cut_frames
    )
    boundaries = [start, *cut_frames, end]
    segments_order = tuple(
        (boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)
    )

    # pass 2 — measured motion with a texture guard and CUT boundaries skipped
    # (motion across a hard cut is not a motion sample).
    shift_cap = CAMERA_SHIFT_CAP_FRACTION * min(target_h, CAMERA_DOWNSCALE_WIDTH)

    def region_shift(
        first: np.ndarray, second: np.ndarray, mask: np.ndarray
    ) -> tuple[float, float, float] | None:
        if (
            float(np.std(first[mask > 0])) < UNIFORM_MIN_STD
            or float(np.std(second[mask > 0])) < UNIFORM_MIN_STD
        ):
            return None  # no texture in the band -> no measurement is possible
        dx, dy, response = _phase_shift(first, second, mask)
        if math.hypot(dx, dy) > shift_cap:
            return None  # implausible lock (degenerate correlation)
        return dx, dy, response

    for row in rows:
        frame = int(row["frame"])
        if frame in cut_frames:
            row["skipped"] = "cut_boundary"
            continue
        prev, cur = small[frame - start - 1], small[frame - start]
        got_border = region_shift(prev, cur, border)
        got_centre = region_shift(prev, cur, centre)
        if got_border is None and got_centre is None:
            row["skipped"] = "no_texture"
            continue
        if got_border is not None:
            row["bx"], row["by"], row["bresp"] = got_border
        if got_centre is not None:
            row["cx"], row["cy"], row["cresp"] = got_centre

    measured = [row for row in rows if "by" in row]
    skipped_uniform = sum(1 for row in rows if row.get("skipped") == "no_texture")
    skipped_cut = sum(1 for row in rows if row.get("skipped") == "cut_boundary")
    centre_measured = [row for row in measured if "cx" in row]

    border_mags = [math.hypot(row["bx"], row["by"]) for row in measured]
    if border_mags:
        sorted_mags = sorted(border_mags)
        border_median = sorted_mags[len(sorted_mags) // 2]
        responses = sorted(row["bresp"] for row in measured)
        response_median = responses[len(responses) // 2]
        sum_dx = sum(row["bx"] for row in measured)
        sum_dy = sum(row["by"] for row in measured)
    else:
        border_median = 0.0
        response_median = 0.0
        sum_dx = sum_dy = 0.0
    direction_deg = (
        math.degrees(math.atan2(sum_dy, sum_dx)) if math.hypot(sum_dx, sum_dy) else 0.0
    )

    if not measured:
        classification = CLASS_UNSUPPORTED
        reason: str | None = "no_measured_frames"
    elif response_median < CAMERA_MIN_RESPONSE:
        classification = CLASS_UNSUPPORTED
        reason = "low_correlation_response"
    elif border_median <= CAMERA_STATIC_MAX_PX_PER_FRAME:
        classification = CLASS_STATIC
        reason = None
    elif border_median >= CAMERA_PAN_MIN_PX_PER_FRAME:
        classification = CLASS_PAN
        reason = None
    else:
        classification = CLASS_UNSUPPORTED
        reason = "border_motion_ambiguous"

    content_segments: list[dict[str, Any]] = []
    for seg_start, seg_end in segments_order:
        seg_rows = [
            row for row in centre_measured if seg_start < int(row["frame"]) <= seg_end
        ]
        mags = [math.hypot(row["cx"], row["cy"]) for row in seg_rows]
        total_dx = sum(row["cx"] for row in seg_rows)
        total_dy = sum(row["cy"] for row in seg_rows)
        total_px = math.hypot(total_dx, total_dy)
        entry: dict[str, Any] = {
            "start_frame": int(seg_start),
            "end_frame": int(seg_end),
            "measured_frames": len(seg_rows),
            "total_px": round(total_px, 4),
            "px_per_frame_median": (
                round(mags[len(mags) // 2], 6) if mags else 0.0
            ),
        }
        if len(seg_rows) < CONTENT_MIN_MEASURED_FRAMES:
            entry["classification"] = "unsupported"
            entry["reason"] = "few_measured_frames"
        elif (
            total_px >= CONTENT_MIN_TOTAL_PX
            and entry["px_per_frame_median"] > CONTENT_STATIC_MAX_PX_PER_FRAME
        ):
            entry["classification"] = "moving"
            entry["direction_deg"] = round(
                math.degrees(math.atan2(total_dy, total_dx)), 2
            )
        else:
            entry["classification"] = "static"
        content_segments.append(entry)
    content_motion = (
        {"method": "phase_correlation_centre", "segments": content_segments}
        if content_segments
        else None
    )

    samples = tuple(
        (
            int(row["frame"]),
            round(row["bx"], 4),
            round(row["by"], 4),
        )
        for row in measured
        if (int(row["frame"]) - start - 1) % CAMERA_SAMPLE_STRIDE == 0
    )

    if classification == CLASS_UNSUPPORTED:
        blocked.append(
            BlockedObservation(
                kind="camera",
                code=CODE_MISSING_DATA,
                position={"window_id": window_id, "frame": start},
                detail=(
                    f"camera reading unsupported ({reason}); border median "
                    f"{border_median:.4f} px/frame, response {response_median:.4f}, "
                    f"measured_frames {len(measured)}"
                ),
            )
        )
    if declared is not None and declared.get("rect") is None:
        blocked.append(
            BlockedObservation(
                kind="crop",
                code=CODE_CROP_MISMATCH,
                position={"window_id": window_id, "frame": start},
                detail=(
                    "declared crop carries no pixel-consistent rect; it cannot be "
                    "recorded as an intended crop"
                ),
            )
        )

    fact = CameraWindowFact(
        window_id=window_id,
        span={"start_frame": start, "end_frame_exclusive": end},
        classification=classification,
        cut_frames=cut_frames,
        content_events=content_events,
        segments_order=segments_order,
        border_drift={
            "dx": round(sum_dx, 4),
            "dy": round(sum_dy, 4),
            "direction_deg": round(direction_deg, 2),
            "px_per_frame_median": round(border_median, 6),
            "px_per_frame_max": round(max(border_mags), 6) if border_mags else 0.0,
            "border_fraction": CAMERA_BORDER_FRACTION,
            "measured_frames": len(measured),
            "skipped_uniform_frames": skipped_uniform,
            "skipped_cut_boundary_frames": skipped_cut,
        },
        border_response_median=round(response_median, 6),
        content_motion=content_motion,
        declared_crop=declared,
        unsupported_reason=reason,
        samples=samples,
        confidence=round(max(0.0, min(1.0, response_median)), 6),
        confidence_source="derived",
    )
    return fact, tuple(blocked)


# ── declared-vs-measured comparison (config never creates a fact) ────────────


def compare_declared(
    contacts: Sequence[ContactFact],
    occlusions: Sequence[OcclusionFact],
    camera_windows: Sequence[CameraWindowFact],
    declared: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Compare DECLARED semantics against the measurements (never fabricates).

    ``declared`` may name the expected holder role and/or the expected
    before/after order of a window's cut segments.  Each entry returns a
    ``match`` of True / False / None (unknown — the measurement cannot decide)
    plus the measured evidence used for the decision.
    """
    checks: list[dict[str, Any]] = []
    holder = declared.get("holder")
    if holder:
        subject = str(holder.get("subject_role_id", ""))
        obj = str(holder.get("object_role_id", ""))
        match: bool | None = None
        evidence: dict[str, Any] = {}
        for fact in contacts:
            if fact.subject_role_id == subject and fact.object_role_id == obj:
                match = fact.kind == CONTACT_KIND_GRASP
                evidence = {
                    "kind": fact.kind,
                    "frames": [fact.start_frame, fact.end_frame],
                    "mean_containment": fact.measured.get("mean_containment"),
                }
                break
        else:
            claimed = [
                fact
                for fact in contacts
                if fact.kind == CONTACT_KIND_GRASP and fact.object_role_id == obj
            ]
            if claimed:
                match = False
                evidence = {
                    "measured_holder_role_id": claimed[0].subject_role_id,
                    "frames": [claimed[0].start_frame, claimed[0].end_frame],
                }
        checks.append(
            {
                "check": "holder",
                "match": match,
                "declared": {"subject_role_id": subject, "object_role_id": obj},
                "measured": evidence,
            }
        )
    order = declared.get("cut_order")
    if order:
        window_id = str(order.get("window_id", ""))
        match = None
        evidence = {}
        for fact in camera_windows:
            if fact.window_id != window_id:
                continue
            evidence = {"segments_order": [list(item) for item in fact.segments_order]}
            first = order.get("first_segment")
            if first is not None and len(fact.segments_order) >= 2:
                measured_start = fact.segments_order[0][0]
                match = int(first) == int(measured_start)
            break
        checks.append(
            {
                "check": "cut_order",
                "match": match,
                "declared": dict(order),
                "measured": evidence,
            }
        )
    return tuple(checks)


# ── sealing / verification ───────────────────────────────────────────────────


def _fact_bounds_ok(start: int, end: int, span_start: int, span_end: int) -> bool:
    return span_start <= start < end <= span_end


def build_artifact(
    *,
    tracks: srt.RoleTracksArtifact,
    windows: Sequence[Mapping[str, Any]] = (),
    declared: Mapping[str, Any] | None = None,
    require_production: bool = True,
) -> FactSet:
    """Seal the measured facts for one source span (single digest)."""
    if require_production:
        srt.require_production(tracks)
    violations = srt.check_artifact(tracks)
    if violations:
        raise SourceFactsError(
            CODE_TRACKS_INVALID, f"track artifact invariants violated: {list(violations)}"
        )

    camera_facts: list[CameraWindowFact] = []
    blocked: list[BlockedObservation] = []
    change_frames: set[int] = set()
    for window in windows:
        fact, window_blocked = estimate_camera(
            str(window["window_id"]),
            window["frames"],
            span=window.get("span") or {
                "start_frame": tracks.span.start_frame,
                "end_frame_exclusive": tracks.span.end_frame_exclusive,
            },
            declared_crop=window.get("declared_crop"),
        )
        camera_facts.append(fact)
        blocked.extend(window_blocked)
        # Change frames may only split facts measured on the SAME source:
        # frame indices from a different source window are a different
        # timeline and must never be re-used here.
        if str(window.get("source_sha256") or "") == str(tracks.source_sha256):
            change_frames.update(fact.content_events)
            change_frames.update(fact.cut_frames)

    for track in tracks.tracks:
        change_frames.update(track_change_frames(track))

    contacts, contact_blocked = derive_contact_facts(
        tracks, change_frames=sorted(change_frames)
    )
    occlusions, occlusion_blocked = derive_occlusion_facts(tracks)
    blocked.extend(contact_blocked)
    blocked.extend(occlusion_blocked)

    checks = compare_declared(contacts, occlusions, camera_facts, declared or {})

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "algorithm": {"id": ALGORITHM, "version": ALGORITHM_VERSION},
        "production": bool(tracks.production),
        "source": {
            "sha256": str(tracks.source_sha256),
            "span": {
                "start_frame": tracks.span.start_frame,
                "end_frame_exclusive": tracks.span.end_frame_exclusive,
            },
            "fps_rational": str(tracks.fps_rational),
            "frame_size": list(tracks.frame_size),
        },
        "track_artifact": {
            "schema_version": tracks.schema_version,
            "digest": tracks.digest,
            "engine": tracks.engine.engine_id,
            "manifest_sha256": tracks.manifest_sha256,
        },
        "thresholds": {
            "contact_max_gap_px": CONTACT_MAX_GAP_PX,
            "contact_min_containment": CONTACT_MIN_CONTAINMENT,
            "contact_min_frames": CONTACT_MIN_FRAMES,
            "occlusion_min_containment": OCCLUSION_MIN_CONTAINMENT,
            "occlusion_min_visible_frames": OCCLUSION_MIN_VISIBLE_FRAMES,
            "state_change_area_ratio": STATE_CHANGE_AREA_RATIO,
            "state_change_shift_px": STATE_CHANGE_SHIFT_PX,
            "camera_border_fraction": CAMERA_BORDER_FRACTION,
            "camera_static_max_px_per_frame": CAMERA_STATIC_MAX_PX_PER_FRAME,
            "camera_pan_min_px_per_frame": CAMERA_PAN_MIN_PX_PER_FRAME,
            "camera_cut_min_mad": CAMERA_CUT_MIN_MAD,
            "camera_event_min_mad": CAMERA_EVENT_MIN_MAD,
            "camera_event_min_ratio": CAMERA_EVENT_MIN_RATIO,
            "camera_min_response": CAMERA_MIN_RESPONSE,
        },
        "change_frames": sorted(change_frames),
        "contacts": [fact.to_payload() for fact in contacts],
        "occlusions": [fact.to_payload() for fact in occlusions],
        "camera": [
            dict(
                fact.to_payload(),
                source_sha256=str(
                    next(
                        (
                            window.get("source_sha256")
                            for window in windows
                            if str(window["window_id"]) == fact.window_id
                        ),
                        "",
                    )
                ),
            )
            for fact in camera_facts
        ],
        "declared_checks": [dict(item) for item in checks],
        "blocked": [item.to_payload() for item in blocked],
    }
    _finite(payload, "artifact")
    payload["digest"] = payload_sha256(payload)
    return FactSet(payload=payload)


def check_artifact(artifact: FactSet | Mapping[str, Any]) -> tuple[str, ...]:
    """Re-verify the sealed facts artifact — returns violated codes."""
    payload = artifact.to_payload() if isinstance(artifact, FactSet) else dict(artifact)
    violations: list[str] = []
    if str(payload.get("schema_version")) != SCHEMA_VERSION:
        violations.append(CODE_VERSION_UNSUPPORTED)
    body = {k: v for k, v in payload.items() if k != "digest"}
    if payload_sha256(body) != str(payload.get("digest")):
        violations.append(CODE_DIGEST_MISMATCH)
    source = dict(payload.get("source") or {})
    span = dict(source.get("span") or {})
    span_start = int(span.get("start_frame", 0) or 0)
    span_end = int(span.get("end_frame_exclusive", 0) or 0)
    try:
        _finite(payload, "artifact")
    except SourceFactsError:
        violations.append(CODE_ARTIFACT_INVALID)

    for fact in payload.get("contacts") or []:
        start = int(fact.get("start_frame", 0))
        end = int(fact.get("end_frame", 0))
        if not _fact_bounds_ok(start, end, span_start, span_end):
            violations.append(CODE_ARTIFACT_INVALID)
        measured = dict(fact.get("measured") or {})
        if not measured or measured.get("min_gap_px") is None:
            violations.append(CODE_MISSING_DATA)
        if fact.get("kind") not in (CONTACT_KIND_GRASP, CONTACT_KIND_TOUCH):
            violations.append(CODE_ARTIFACT_INVALID)
        if not fact.get("evidence"):
            violations.append(CODE_ARTIFACT_INVALID)
        if not 0.0 <= _num(fact.get("confidence")) <= 1.0:
            violations.append(CODE_ARTIFACT_INVALID)

    for fact in payload.get("occlusions") or []:
        start = int(fact.get("start_frame", 0))
        end = int(fact.get("end_frame", 0))
        if not _fact_bounds_ok(start, end, span_start, span_end):
            violations.append(CODE_ARTIFACT_INVALID)
        if fact.get("order") != "in_front_of":
            violations.append(CODE_ARTIFACT_INVALID)
        if not fact.get("evidence") or not fact.get("measured"):
            violations.append(CODE_ARTIFACT_INVALID)

    for fact in payload.get("camera") or []:
        if fact.get("classification") not in CAMERA_CLASSIFICATIONS:
            violations.append(CODE_ARTIFACT_INVALID)
        if fact.get("classification") == CLASS_UNSUPPORTED and not fact.get(
            "unsupported_reason"
        ):
            violations.append(CODE_MISSING_DATA)

    for item in payload.get("blocked") or []:
        if not item.get("position"):
            violations.append(CODE_MISSING_DATA)
    return tuple(dict.fromkeys(violations))


def fact_id(fact: Mapping[str, Any]) -> str:
    """Deterministic identity of one fact (used for keys and overwrite checks)."""
    kind = "contact" if "subject_role_id" in fact else "occlusion"
    if kind == "contact":
        parts = (
            kind,
            str(fact.get("subject_role_id")),
            str(fact.get("object_role_id")),
            str(fact.get("kind")),
            str(fact.get("start_frame")),
        )
    else:
        parts = (
            kind,
            str(fact.get("occluder_role_id")),
            str(fact.get("occludee_role_id")),
            str(fact.get("start_frame")),
        )
    return ":".join(parts)


def check_output_overwrite(
    artifact: FactSet | Mapping[str, Any], claim: Mapping[str, Any]
) -> None:
    """Refuse an OUTPUT-side claim that contradicts a sealed source fact.

    Agreement is allowed (an output observation may confirm a source fact);
    a different value for a sealed fact identity is refused with
    ``SOURCE_FACTS_OUTPUT_OVERWRITE``, and an unknown fact id with
    ``SOURCE_FACTS_UNKNOWN_FACT``.
    """
    payload = artifact.to_payload() if isinstance(artifact, FactSet) else dict(artifact)
    origin = str(claim.get("origin", "output"))
    wanted = str(claim.get("fact_id", ""))
    known: dict[str, Mapping[str, Any]] = {}
    for bucket in ("contacts", "occlusions"):
        for fact in payload.get(bucket) or []:
            known[fact_id(fact)] = fact
    if wanted not in known:
        raise SourceFactsError(
            CODE_UNKNOWN_FACT, f"claim names {wanted!r}; no sealed source fact"
        )
    if origin != "output":
        return None
    source = known[wanted]
    value = dict(claim.get("value") or {})
    for key, expected in value.items():
        if key == "kind" and source.get("kind") != expected:
            raise SourceFactsError(
                CODE_OUTPUT_OVERWRITE,
                f"output claim would rewrite {wanted!r} kind "
                f"{source.get('kind')!r} -> {expected!r}",
            )
        if key == "order" and source.get("order") != expected:
            raise SourceFactsError(
                CODE_OUTPUT_OVERWRITE,
                f"output claim would rewrite {wanted!r} order "
                f"{source.get('order')!r} -> {expected!r}",
            )
    return None


# ── publish through the EXISTING authority ───────────────────────────────────


def bind_facts(
    artifact: FactSet | Mapping[str, Any],
    bindings: Mapping[str, str],
) -> dict[str, str]:
    """Resolve every fact endpoint to a REAL occurrence segment.

    ``bindings`` maps role ids to occurrence-segment ids.  A fact whose
    second real endpoint is absent is refused — no fake segment is created.
    """
    payload = artifact.to_payload() if isinstance(artifact, FactSet) else dict(artifact)
    missing: list[str] = []
    for fact in payload.get("contacts") or []:
        for role_key in ("subject_role_id", "object_role_id"):
            role = str(fact.get(role_key))
            if role not in bindings:
                missing.append(f"contact:{role}")
    for fact in payload.get("occlusions") or []:
        for role_key in ("occluder_role_id", "occludee_role_id"):
            role = str(fact.get(role_key))
            if role not in bindings:
                missing.append(f"occlusion:{role}")
    unique = sorted(set(missing))
    if unique:
        raise SourceFactsError(
            CODE_SECOND_SEGMENT_MISSING,
            "facts name roles with no real occurrence segment: " + ", ".join(unique),
        )
    resolved: dict[str, str] = {}
    for role, segment_id in bindings.items():
        resolved[str(role)] = str(segment_id)
    return resolved


def publish_facts(
    session: Any,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    artifact: FactSet | Mapping[str, Any],
    bindings: Mapping[str, str],
    segment_ranges: Mapping[str, Mapping[str, int]],
    idempotency_prefix: str | None = None,
) -> PublishOutcome:
    """Publish the measured facts via StructuralEvidenceRepository ONLY.

    ``segment_ranges`` carries each bound segment's own frame range so a
    camera fact is clipped to the segment it attaches to (the authority
    rejects out-of-range rows).  Contact/occlusion ranges are validated by
    the repository against BOTH real endpoints.
    """
    payload = artifact.to_payload() if isinstance(artifact, FactSet) else dict(artifact)
    violations = check_artifact(payload if isinstance(payload, dict) else artifact)
    if violations:
        raise SourceFactsError(
            CODE_ARTIFACT_INVALID, f"sealed facts invalid: {list(violations)}"
        )
    if not payload.get("production"):
        raise SourceFactsError(
            CODE_NOT_PRODUCTION,
            "the facts come from a CI-fixture track artifact; fixtures are "
            "never published as production facts",
        )
    resolved = bind_facts(payload, bindings)
    source = dict(payload.get("source") or {})
    fps_rational = str(source.get("fps_rational"))
    source_sha = str(source.get("sha256"))
    digest = str(payload.get("digest"))
    prefix = idempotency_prefix or f"source-interaction-facts:{digest}"

    repo = StructuralEvidenceRepository(session)
    contacts_created = contacts_replayed = 0
    occlusions_created = occlusions_replayed = 0
    motions_created = motions_replayed = 0

    for index, fact in enumerate(payload.get("contacts") or []):
        key = f"{prefix}:contact:{index}"
        start = int(fact["start_frame"])
        end = int(fact["end_frame"])
        try:
            _, created = repo.create_contact(
                workspace_id,
                project_id,
                video_item_id,
                resolved[str(fact["subject_role_id"])],
                resolved[str(fact["object_role_id"])],
                str(fact["kind"]),
                start,
                end,
                _ms(start, fps_rational),
                _ms(end, fps_rational),
                algorithm=ALGORITHM,
                algorithm_version=ALGORITHM_VERSION,
                confidence=float(fact["confidence"]),
                confidence_source=str(fact.get("confidence_source", "derived")),
                reasons=[
                    "source-side measured contact (MF-END-13); derived from REAL "
                    "track bbox gap + containment, never from configuration",
                ],
                provenance={
                    "origin": "source",
                    "artifact_digest": digest,
                    "source_sha256": source_sha,
                    "policy_version": POLICY_VERSION,
                    "fact_id": fact_id(fact),
                    "subject_instance_id": str(fact["subject_instance_id"]),
                    "object_instance_id": str(fact["object_instance_id"]),
                    "measured": dict(fact.get("measured") or {}),
                    "evidence": dict(fact.get("evidence") or {}),
                },
                idempotency_key=key,
            )
        except ContactConflictError as err:
            raise SourceFactsError(
                CODE_FACT_CONFLICT, f"contact {key} conflicts: {err}"
            ) from err
        if created:
            contacts_created += 1
        else:
            contacts_replayed += 1

    for index, fact in enumerate(payload.get("occlusions") or []):
        key = f"{prefix}:occlusion:{index}"
        start = int(fact["start_frame"])
        end = int(fact["end_frame"])
        try:
            _, created = repo.create_occlusion(
                workspace_id,
                project_id,
                video_item_id,
                resolved[str(fact["occluder_role_id"])],
                resolved[str(fact["occludee_role_id"])],
                start,
                end,
                _ms(start, fps_rational),
                _ms(end, fps_rational),
                algorithm=ALGORITHM,
                algorithm_version=ALGORITHM_VERSION,
                confidence=float(fact["confidence"]),
                confidence_source=str(fact.get("confidence_source", "derived")),
                reasons=[
                    "source-side measured occlusion order (MF-END-13); measured "
                    "cue is recorded in the fact, order is never assumed",
                ],
                provenance={
                    "origin": "source",
                    "artifact_digest": digest,
                    "source_sha256": source_sha,
                    "policy_version": POLICY_VERSION,
                    "fact_id": fact_id(fact),
                    "occluder_instance_id": str(fact["occluder_instance_id"]),
                    "occludee_instance_id": str(fact["occludee_instance_id"]),
                    "measured": dict(fact.get("measured") or {}),
                    "evidence": dict(fact.get("evidence") or {}),
                },
                idempotency_key=key,
            )
        except OcclusionConflictError as err:
            raise SourceFactsError(
                CODE_FACT_CONFLICT, f"occlusion {key} conflicts: {err}"
            ) from err
        if created:
            occlusions_created += 1
        else:
            occlusions_replayed += 1

    window_count = len(payload.get("camera") or [])
    for index, fact in enumerate(payload.get("camera") or []):
        if str(fact.get("classification")) not in (CLASS_STATIC, CLASS_PAN):
            continue
        win_start = int(fact["span"]["start_frame"])
        win_end = int(fact["span"]["end_frame_exclusive"])
        for role, segment_id in sorted(resolved.items()):
            limits = segment_ranges.get(segment_id)
            if limits is None:
                raise SourceFactsError(
                    CODE_SEGMENT_MISSING,
                    f"no measured range supplied for bound segment {segment_id}",
                )
            start = max(win_start, int(limits["start_frame"]))
            end = min(win_end, int(limits["end_frame"]))
            if end <= start:
                continue
            key = f"{prefix}:camera:{index}:{segment_id}"
            transform = {
                "classification": str(fact["classification"]),
                "window_id": str(fact["window_id"]),
                "border_drift": dict(fact.get("border_drift") or {}),
                "cut_frames": list(fact.get("cut_frames") or []),
                "content_events": list(fact.get("content_events") or []),
                "segments_order": [
                    list(item) for item in fact.get("segments_order") or []
                ],
                "content_motion": (
                    dict(fact["content_motion"]) if fact.get("content_motion") else None
                ),
                "declared_crop": (
                    dict(fact["declared_crop"]) if fact.get("declared_crop") else None
                ),
            }
            point_ref = {
                "sampling": "border_band_phase_correlation",
                "border_fraction": CAMERA_BORDER_FRACTION,
                "stride": CAMERA_SAMPLE_STRIDE,
                "samples": [list(item) for item in fact.get("samples") or []],
            }
            try:
                _, created = repo.create_motion(
                    workspace_id,
                    segment_id,
                    "camera_relative",
                    transform,
                    point_track_flow_ref=point_ref,
                    start_frame=start,
                    end_frame=end,
                    start_time_ms=_ms(start, fps_rational),
                    end_time_ms=_ms(end, fps_rational),
                    algorithm=ALGORITHM,
                    algorithm_version=ALGORITHM_VERSION,
                    confidence=float(fact.get("confidence", 0.0)),
                    confidence_source=str(fact.get("confidence_source", "derived")),
                    reasons=[
                        "source-side measured camera/scene motion (MF-END-13); "
                        "measured on the REAL decoded window border band",
                    ],
                    provenance={
                        "origin": "source",
                        "artifact_digest": digest,
                        "source_sha256": source_sha,
                        "policy_version": POLICY_VERSION,
                        "window_id": str(fact["window_id"]),
                        "role_id": str(role),
                        "windows_in_artifact": window_count,
                    },
                    idempotency_key=key,
                )
            except Exception as err:  # noqa: BLE001 - mapped to a typed conflict
                if err.__class__.__name__.endswith("ConflictError"):
                    raise SourceFactsError(
                        CODE_FACT_CONFLICT, f"camera motion {key} conflicts: {err}"
                    ) from err
                raise
            if created:
                motions_created += 1
            else:
                motions_replayed += 1

    return PublishOutcome(
        artifact_digest=digest,
        contacts_created=contacts_created,
        contacts_replayed=contacts_replayed,
        occlusions_created=occlusions_created,
        occlusions_replayed=occlusions_replayed,
        motions_created=motions_created,
        motions_replayed=motions_replayed,
        segment_ids=tuple(sorted(set(resolved.values()))),
    )

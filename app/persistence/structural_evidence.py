"""Structural-evidence persistence repository (S08-A02-T01-R1, rewritten).

The durable repository for the structural-evidence bridge:

- ``OccurrenceSegment`` — stable occurrence/segment identity, frame/time
  range, generation ownership, prompt/segmentation JSON evidence, mask
  artifact reference and scene-graph geometry (visibility + z-order).
  Carries BOTH a stable ``logical_id`` (lineage identity across corrections,
  F2) and an immutable per-version ``id``.
- ``SegmentMotion`` — camera-relative / object-relative transform contract
  (deterministic JSON + provenance/confidence + temporal validity + durable
  point/track/flow evidence reference).  CONTRACT-ONLY: no engine runs here.
- ``SceneGraphOcclusion`` / ``SceneGraphContact`` — FK-enforced edges with
  temporal validity, provenance and confidence.

R1 recovery contract (Codex findings F1..F11 are normative):

- F1 — dataclass field order keeps every DTO importable (no
  ``non-default follows default`` TypeError).  The import-smoke test imports
  this module.
- F2 — ``logical_id`` is the stable lineage key; ``id`` the per-version
  evidence-record id.  A correction creates a successor record that KEEPS
  ``logical_id``, sets ``predecessor.superseded_by_id`` = successor id,
  NEVER deletes the predecessor and keeps both current + historical rows
  queryable.  Display names are never identity/join keys.
- F3 — no full natural-key ``UniqueConstraint`` on the versioned segment
  table; active rows are deduplicated by the PARTIAL unique index
  ``uq_occurrence_segment_active_identity (WHERE superseded_by_id IS NULL)``
  so versions/generations coexist.
- F4 — generation authority is REUSED from ``ObjectIntelligenceRepository``
  (workspace/video ownership, current source-artifact SHA, completed
  ``DISCOVER_OBJECTS`` job, input generation) — never a naive max+1 copy.
- F5 — every create validates the FULL ownership chain (workspace ->
  project -> video -> scene; workspace/video -> role; video/generation ->
  job; workspace -> mask artifact) and fails BEFORE commit with zero rows.
- F6 — segmentation evidence: mask artifact required + owned; strict prompt
  points/boxes shape; NaN/Infinity REJECTED (``allow_nan=False``); malformed
  durable JSON fails CLOSED (raises ``MalformedJsonError``, never a default).
- F7 — supersession is atomic (successor creation + predecessor CAS inside
  one savepoint, rolled back on conflict) and the lineage walker accepts ANY
  version, finds the oldest predecessor, returns oldest -> newest, and
  detects cycles / dangling links.
- F8 — mutating a historical/superseded record or using a stale revision is
  refused with a stable conflict and ZERO mutation.
- F9 — ``idempotency_key`` is USED (workspace-scoped) for replay/same-payload
  and conflicts on different payloads; the natural key is never an
  idempotency key.
- F10 — end >= start for frames/time; edge/motion ranges within the segment
  range; endpoints in the same video + compatible generation; self-edges
  rejected; confidence in 0..1; z-order/visibility/contact-kind from the
  canonical enum.

The repository never commits — the caller owns the transaction (service/API
layer per the domain contract).
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import String, bindparam, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from app.persistence.models import (
    CONTACT_KINDS,
    OBJECT_KINDS,
    OCCURRENCE_SEGMENT_VISIBILITY,
    REMOVAL_ONLY_KINDS,
    Artifact,
    Job,
    ObjectRole,
    OccurrenceSegment,
    Project,
    Scene,
    SceneGraphContact,
    SceneGraphOcclusion,
    SegmentMotion,
    VideoItem,
    utc_now,
)
from app.persistence.object_intelligence import (
    JOB_TYPE_DISCOVER_OBJECTS,
    ObjectIntelligenceRepository,
)

#: Canonical confidence provenance tags (mirrors the ORM CHECK literal).
CONFIDENCE_SOURCES = ("model", "detector", "user", "manual", "derived")
#: Canonical motion transform types (mirrors the ORM CHECK literal).
MOTION_TRANSFORM_TYPES = ("camera_relative", "object_relative")
#: SQLite param limit guard
_SQLITE_MAX_PARAMS = 900
#: Declared FIXED bind-parameter budget for the FINAL historical COUNT and
#: page SELECT statements (covers ALL predicates: workspace_id, source_generation,
#: role_id, stale_json, plus internal LIMIT/OFFSET).  Every emitted SQL
#: statement for the historical filter has TOTAL bind params <= this budget,
#: INDEPENDENT of stale-video count.  JSON1 approach binds ONE JSON text param
#: regardless of video count (stale_json), so final query = 4-6 params.
_FINAL_QUERY_PARAM_BUDGET = 6
#: Job bulk overhead already accounted in ObjectIntelligenceRepository
#: (_SQLITE_JOB_CHUNK = 900-2).  This module reuses the same chunk sizing via
#: the authoritative batch API, so no unbounded IN-list here.


def _chunked(seq: list[str], size: int = _SQLITE_MAX_PARAMS):  # type: ignore[no-untyped-def]
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


#: Model/detector evidence REQUIRES the producing DISCOVER_OBJECTS job (C1-F5).
REQUIRED_JOB_CONFIDENCE_SOURCES = ("model", "detector")
#: Human-correction tags: manual evidence MUST use user/manual (C1-F1/F5).
MANUAL_CONFIDENCE_SOURCES = ("user", "manual")


def canonical_json(value: Any) -> str:
    """Canonical deterministic JSON encoding (AC7 byte-identical round-trip).

    ``allow_nan=False`` REJECTS NaN / Infinity / -Infinity (R1 F6) — a
    non-finite number can never be serialized into a durable JSON column.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_json(raw: str | None) -> Any:
    """Parse a stored JSON payload, FAIL CLOSED on malformed input (R1 F6).

    A malformed durable JSON payload raises ``MalformedJsonError`` with a
    stable message — it is NEVER silently replaced by a default value (the
    draft's default-on-failure behaviour is a finding and is removed).
    """
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MalformedJsonError(
            "malformed durable JSON payload; refusing to interpret it as a "
            f"default value: {exc}"
        ) from exc


class StructuralEvidenceError(Exception):
    """Base error for the structural-evidence bridge."""


class MalformedJsonError(StructuralEvidenceError):
    """A durable JSON column holds malformed JSON (fail-closed read)."""


class SegmentNotFoundError(StructuralEvidenceError):
    """Segment does not exist in the requested workspace."""


class SegmentConflictError(StructuralEvidenceError):
    """Segment mutation conflicts with current durable state (stale CAS /
    stale generation / terminal superseded row / duplicate active identity)."""


class MotionNotFoundError(StructuralEvidenceError):
    """Segment motion record does not exist."""


class MotionConflictError(StructuralEvidenceError):
    """Motion mutation conflicts with current durable state."""


class OcclusionNotFoundError(StructuralEvidenceError):
    """Occlusion edge does not exist in the requested scope."""


class OcclusionConflictError(StructuralEvidenceError):
    """Occlusion mutation conflicts with current durable state."""


class ContactNotFoundError(StructuralEvidenceError):
    """Contact edge does not exist in the requested scope."""


class ContactConflictError(StructuralEvidenceError):
    """Contact mutation conflicts with current durable state."""


class OwnershipMismatchError(StructuralEvidenceError):
    """An ownership chain did not validate (cross-workspace / cross-video /
    cross-generation / unowned artifact or job)."""


@dataclass(frozen=True)
class SegmentRecord:
    """Read model of one occurrence segment (DTO boundary — no ORM escape)."""

    id: str
    logical_id: str
    lineage_version: int
    workspace_id: str
    project_id: str
    video_item_id: str
    role_id: str
    scene_id: str
    name: str
    kind: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    source_generation: str
    source_job_id: str | None
    prompt_json: str | None
    segmentation_json: str | None
    mask_artifact_id: str | None
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    visibility: str
    z_order: int
    superseded_by_id: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MotionRecord:
    """Read model of one segment motion record."""

    id: str
    workspace_id: str
    occurrence_segment_id: str
    transform_type: str
    transform: dict[str, Any]
    point_track_flow_ref: dict[str, Any] | list[Any] | None
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OcclusionRecord:
    """Read model of one occlusion edge (occluder -> occludee)."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    occluder_segment_id: str
    occludee_segment_id: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContactRecord:
    """Read model of one contact edge/event (source -> target)."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_segment_id: str
    target_segment_id: str
    contact_kind: str
    start_frame: int
    end_frame: int
    start_time_ms: int
    end_time_ms: int
    algorithm: str | None
    algorithm_version: str | None
    confidence: float
    confidence_source: str
    revision: int
    created_at: datetime
    updated_at: datetime
    reasons: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def _new_id() -> str:
    """Opaque public identifier (UUID4 initial; UUIDv7-compatible length)."""
    return str(uuid.uuid4())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return _is_number(value) and math.isfinite(float(value))


def _reasons(value: str | None) -> list[str]:
    parsed = parse_json(value)
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise MalformedJsonError("reasons_json is not a JSON array (fail closed)")
    if not all(isinstance(item, str) for item in parsed):
        raise MalformedJsonError(
            "reasons_json must be an array of strings (fail closed)"
        )
    return list(parsed)


def _provenance(value: str | None) -> dict[str, Any]:
    parsed = parse_json(value)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise MalformedJsonError("provenance_json is not a JSON object (fail closed)")
    return dict(parsed)


def _map_segment(row: OccurrenceSegment) -> SegmentRecord:
    return SegmentRecord(
        id=row.id,
        logical_id=row.logical_id,
        lineage_version=row.lineage_version,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        role_id=row.role_id,
        scene_id=row.scene_id,
        name=row.name,
        kind=row.kind,
        start_frame=row.start_frame,
        end_frame=row.end_frame,
        start_time_ms=row.start_time_ms,
        end_time_ms=row.end_time_ms,
        source_generation=row.source_generation,
        source_job_id=row.source_job_id,
        prompt_json=row.prompt_json,
        segmentation_json=row.segmentation_json,
        mask_artifact_id=row.mask_artifact_id,
        algorithm=row.algorithm,
        algorithm_version=row.algorithm_version,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        visibility=row.visibility,
        z_order=row.z_order,
        superseded_by_id=row.superseded_by_id,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        reasons=_reasons(row.reasons_json),
        provenance=_provenance(row.provenance_json),
    )


def _map_motion(row: SegmentMotion) -> MotionRecord:
    transform = parse_json(row.transform_json)
    if not isinstance(transform, dict):
        raise MalformedJsonError("transform_json is not a JSON object (fail closed)")
    return MotionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        occurrence_segment_id=row.occurrence_segment_id,
        transform_type=row.transform_type,
        transform=dict(transform),
        point_track_flow_ref=parse_json(row.point_track_flow_ref_json),
        start_frame=row.start_frame,
        end_frame=row.end_frame,
        start_time_ms=row.start_time_ms,
        end_time_ms=row.end_time_ms,
        algorithm=row.algorithm,
        algorithm_version=row.algorithm_version,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        reasons=_reasons(row.reasons_json),
        provenance=_provenance(row.provenance_json),
    )


def _map_occlusion(row: SceneGraphOcclusion) -> OcclusionRecord:
    return OcclusionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        occluder_segment_id=row.occluder_segment_id,
        occludee_segment_id=row.occludee_segment_id,
        start_frame=row.start_frame,
        end_frame=row.end_frame,
        start_time_ms=row.start_time_ms,
        end_time_ms=row.end_time_ms,
        algorithm=row.algorithm,
        algorithm_version=row.algorithm_version,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        reasons=_reasons(row.reasons_json),
        provenance=_provenance(row.provenance_json),
    )


def _map_contact(row: SceneGraphContact) -> ContactRecord:
    return ContactRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        source_segment_id=row.source_segment_id,
        target_segment_id=row.target_segment_id,
        contact_kind=row.contact_kind,
        start_frame=row.start_frame,
        end_frame=row.end_frame,
        start_time_ms=row.start_time_ms,
        end_time_ms=row.end_time_ms,
        algorithm=row.algorithm,
        algorithm_version=row.algorithm_version,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        reasons=_reasons(row.reasons_json),
        provenance=_provenance(row.provenance_json),
    )


def _validate_frame_time(
    *,
    start_frame: int,
    end_frame: int,
    start_time_ms: int,
    end_time_ms: int,
) -> None:
    if (
        not isinstance(start_frame, int)
        or not isinstance(end_frame, int)
        or not isinstance(start_time_ms, int)
        or not isinstance(end_time_ms, int)
        or isinstance(start_frame, bool)
        or isinstance(end_frame, bool)
        or isinstance(start_time_ms, bool)
        or isinstance(end_time_ms, bool)
        or start_frame < 0
        or end_frame < 0
        or start_time_ms < 0
        or end_time_ms < 0
    ):
        raise ValueError("frame/time values must be non-negative integers")
    if end_frame < start_frame:
        raise ValueError("end_frame must be >= start_frame")
    if end_time_ms < start_time_ms:
        raise ValueError("end_time_ms must be >= start_time_ms")


def _validate_confidence(confidence: float) -> None:
    if not _is_finite_number(confidence) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be a finite number between 0 and 1")


def _validate_provenance(provenance: dict[str, Any] | None) -> None:
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")


def _validate_prompt_evidence(prompt: dict[str, Any] | None) -> None:
    """Strict structural shape for prompt/segmentation evidence (R1 F6, C1-F6).

    Accepts ``{"points": [{"x": .., "y": .., "label": ".."}], "boxes":
    [{"x": .., "y": .., "w": .., "h": ..}]}``.  ``points`` and ``boxes`` must
    be JSON arrays, each point/box must match its EXACT supported shape (no
    extra or missing keys), every point label is a NON-EMPTY string, every
    coordinate is a finite number, boxes have non-negative width/height, and
    unknown top-level keys are refused.  NaN/Infinity are refused here AND at
    canonical_json serialisation (C1-F6 pre-flush validation).
    """
    if prompt is None:
        return
    if not isinstance(prompt, dict):
        raise ValueError("prompt/segmentation evidence must be a JSON object")
    unknown = set(prompt.keys()) - {"points", "boxes"}
    if unknown:
        raise ValueError(f"unknown prompt evidence key(s): {sorted(unknown)!r}")
    points = prompt.get("points")
    if points is not None and not isinstance(points, list):
        raise ValueError("prompt points must be a JSON array (C1-F6)")
    boxes = prompt.get("boxes")
    if boxes is not None and not isinstance(boxes, list):
        raise ValueError("prompt boxes must be a JSON array (C1-F6)")
    for point in points or []:
        if not isinstance(point, dict):
            raise ValueError("each point must be an object {x, y, label}")
        if set(point.keys()) != {"x", "y", "label"}:
            raise ValueError(
                f"each point must match the exact shape {{x, y, label}} (got "
                f"{sorted(point.keys())}) — C1-F6"
            )
        label = point.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("each point requires a non-empty string 'label'")
        for key in ("x", "y"):
            if not _is_finite_number(point.get(key)):
                raise ValueError(f"point {key!r} must be a finite number")
    for box in boxes or []:
        if not isinstance(box, dict):
            raise ValueError("each box must be an object {x, y, w, h}")
        if set(box.keys()) != {"x", "y", "w", "h"}:
            raise ValueError(
                f"each box must match the exact shape {{x, y, w, h}} (got "
                f"{sorted(box.keys())}) — C1-F6"
            )
        for key in ("x", "y", "w", "h"):
            if not _is_finite_number(box.get(key)):
                raise ValueError(f"box {key!r} must be a finite number")
        if float(box["w"]) < 0 or float(box["h"]) < 0:
            raise ValueError("box width/height must be non-negative")


def _validate_algorithm_fields(
    algorithm: str | None, algorithm_version: str | None
) -> None:
    """Pre-flush length validation for algorithm / algorithm_version (C1-F6)."""
    for value, label in (
        (algorithm, "algorithm"),
        (algorithm_version, "algorithm_version"),
    ):
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string")
        if not value.strip():
            raise ValueError(f"{label} must not be empty")
        if len(value) > 64:
            raise ValueError(f"{label} must be at most 64 chars (C1-F6)")


def _validate_idempotency_key(idempotency_key: str | None) -> None:
    """Empty-key contract + over-length rejection BEFORE DB flush (C1-F3/F6).

    An empty/whitespace idempotency key is rejected (never silently treated
    as 'no key'); an over-length key is rejected pre-flush rather than raising
    an IntegrityError at flush time.
    """
    if idempotency_key is None:
        return
    if not isinstance(idempotency_key, str):
        raise ValueError("idempotency_key must be a string")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty (C1-F3)")
    if len(idempotency_key) > 255:
        raise ValueError("idempotency_key must be at most 255 chars (C1-F6)")


def _validate_reasons_list(reasons: list[str] | None) -> None:
    """Pre-flush validation that reasons is a list[str] (C1-F6)."""
    if reasons is not None and not (
        isinstance(reasons, list) and all(isinstance(r, str) for r in reasons)
    ):
        raise ValueError("reasons must be a list of strings (C1-F6)")

class StructuralEvidenceRepository:
    """Durable repository for the structural-evidence bridge.

    The repository never commits — the caller owns the transaction (the API
    route commits after a successful call; the domain contract requires the
    service layer to own transactions).  Conflict/ownership errors leave the
    durable state byte-identical (zero mutation).
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        # F4: generation authority is the EXISTING backend-authoritative
        # repository (workspace/video ownership + current source-artifact SHA
        # + completed DISCOVER_OBJECTS job + input generation) — never a
        # client hint or a naive max+1 copy.
        self._generation = ObjectIntelligenceRepository(session)

    # ── generation ownership (F4) ──────────────────────────────────────────

    def current_generation(self, workspace_id: str, video_item_id: str) -> str:
        """Backend-authoritative current source generation of a video item.

        Delegates to ``ObjectIntelligenceRepository.current_generation``
        (single authority).  Fail-closed: an unknown video item raises.
        """
        return self._generation.current_generation(workspace_id, video_item_id)

    def _assert_current_generation(self, segment: OccurrenceSegment) -> None:
        """Fail-closed guard: only CURRENT, ACTIVE segments are mutable.

        A superseded (historical) segment, or a segment whose
        ``source_generation`` is stale vs. the backend authority, is
        READ-ONLY: any mutation raises ``SegmentConflictError`` with ZERO
        mutation (R1 F8 / C1-F1).
        """
        if segment.superseded_by_id is not None:
            raise SegmentConflictError(
                f"segment {segment.id!r} is superseded and terminal "
                "(historical rows are read-only)"
            )
        current = self.current_generation(
            segment.workspace_id, segment.video_item_id
        )
        if segment.source_generation != current:
            raise SegmentConflictError(
                f"segment {segment.id!r} belongs to stale source generation "
                f"{segment.source_generation!r}; only current-generation "
                f"segments are mutable (current generation is {current!r})"
            )

    def _assert_active(self, segment: OccurrenceSegment) -> None:
        """Fail-closed guard: the ACTIVE lineage version is mutable.

        Unlike ``_assert_current_generation``, this does NOT require the
        segment to belong to the current generation — a re-analysis
        transition (workflow B, C1-F1) may start from an older-generation
        ACTIVE version.  A superseded (historical) row is always read-only.
        """
        if segment.superseded_by_id is not None:
            raise SegmentConflictError(
                f"segment {segment.id!r} is superseded and terminal "
                "(historical rows are read-only; a lineage never branches)"
            )

    def _assert_segment_generation_authority(
        self, workspace_id: str, video_item_id: str, source_generation: str
    ) -> None:
        """C1-F1: the public create/transition path FAILS CLOSED when the
        requested ``source_generation`` differs from the backend authority
        (``ObjectIntelligenceRepository.current_generation``).  No arbitrary
        future/stale generation is ever created by a caller."""
        current = self.current_generation(workspace_id, video_item_id)
        if source_generation != current:
            raise SegmentConflictError(
                f"cannot create/transition evidence in source generation "
                f"{source_generation!r}: the backend current generation is "
                f"{current!r} — arbitrary future/stale generations are "
                "rejected (C1-F1)"
            )

    # ── ownership / FK existence (F5 / C1-F5) ──────────────────────────────

    def _assert_segment_ownership(
        self, segment: OccurrenceSegment, workspace_id: str
    ) -> None:
        if segment.workspace_id != workspace_id:
            raise OwnershipMismatchError(
                f"segment {segment.id!r} does not belong to workspace {workspace_id!r}"
            )

    def _assert_video_chain(
        self, workspace_id: str, project_id: str, video_item_id: str
    ) -> None:
        """workspace -> project -> video must all be consistent."""
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise OwnershipMismatchError(
                f"project {project_id!r} does not belong to workspace {workspace_id!r}"
            )
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise OwnershipMismatchError(
                f"video_item {video_item_id!r} does not belong to project "
                f"{project_id!r}"
            )

    def _assert_scene_ownership(self, scene_id: str, video_item_id: str) -> None:
        scene = self._session.get(Scene, scene_id)
        if scene is None:
            raise OwnershipMismatchError(f"scene {scene_id!r} does not exist")
        if scene.video_item_id != video_item_id:
            raise OwnershipMismatchError(
                f"scene {scene_id!r} belongs to video {scene.video_item_id!r}, "
                f"not {video_item_id!r} (scene from another video rejected)"
            )

    def _assert_role_ownership(
        self, role_id: str, workspace_id: str, video_item_id: str
    ) -> ObjectRole:
        role = self._session.get(ObjectRole, role_id)
        if role is None:
            raise OwnershipMismatchError(f"role {role_id!r} does not exist")
        if role.workspace_id != workspace_id:
            raise OwnershipMismatchError(
                f"role {role_id!r} does not belong to workspace {workspace_id!r}"
            )
        if role.video_item_id != video_item_id:
            raise OwnershipMismatchError(
                f"role {role_id!r} belongs to video {role.video_item_id!r}, "
                f"not {video_item_id!r} (role from another video rejected)"
            )
        return role

    def _assert_role_compatible(
        self,
        role: ObjectRole,
        source_generation: str,
        kind: str,
    ) -> None:
        """C1-F1/C1-F5: the segment belongs to exactly one generation, and its
        kind is inherited from the enforced ObjectRole taxonomy.  A role whose
        generation is incompatible with the segment's, or whose kind differs
        from the segment kind, fails closed before any row is written."""
        if role.source_generation != source_generation:
            raise OwnershipMismatchError(
                f"role {role.id!r} belongs to source generation "
                f"{role.source_generation!r}, not {source_generation!r} — "
                "role generation is incompatible with the segment generation "
                "(C1-F1)"
            )
        if role.kind != kind:
            raise OwnershipMismatchError(
                f"role {role.id!r} kind {role.kind!r} is incompatible with "
                f"segment kind {kind!r} — a segment kind must match the "
                "ObjectRole taxonomy (C1-F5)"
            )

    def _current_source_sha(self, video_item_id: str) -> str | None:
        """The video item's current source-artifact SHA-256 (C1-F5).

        Resolved through the same authority as ``current_generation`` — the
        video's ``source_artifact_id`` artifact SHA.  ``None`` when the video
        has no source artifact.
        """
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.source_artifact_id is None:
            return None
        artifact = self._session.get(Artifact, video.source_artifact_id)
        return artifact.sha256 if artifact is not None and artifact.sha256 else None

    def _assert_job_ownership(
        self,
        job_id: str | None,
        workspace_id: str,
        video_item_id: str,
        source_generation: str,
    ) -> None:
        """video / source generation -> job: the producing DISCOVER_OBJECTS
        job must own this video's evidence, produce this generation and match
        the video's current source SHA (R1 F5 / C1-F5)."""
        if job_id is None:
            return  # nullable only for user/manual corrections (contract §3.1)
        job = self._session.get(Job, job_id)
        if job is None:
            raise OwnershipMismatchError(f"job {job_id!r} does not exist")
        if job.workspace_id != workspace_id:
            raise OwnershipMismatchError(
                f"job {job_id!r} does not belong to workspace {workspace_id!r}"
            )
        if job.owner_type != "video_item" or job.owner_id != video_item_id:
            raise OwnershipMismatchError(
                f"job {job_id!r} is owned by {job.owner_type!r}:"
                f"{job.owner_id!r}, not video_item:{video_item_id!r} "
                "(job owned by someone else rejected)"
            )
        if job.job_type != JOB_TYPE_DISCOVER_OBJECTS or job.state != "completed":
            raise OwnershipMismatchError(
                f"job {job_id!r} must be a COMPLETED {JOB_TYPE_DISCOVER_OBJECTS} "
                f"job to produce segment evidence (type={job.job_type!r}, "
                f"state={job.state!r})"
            )
        if str(job.input_generation or "") != source_generation:
            raise OwnershipMismatchError(
                f"job {job_id!r} produces generation "
                f"{job.input_generation!r}, not {source_generation!r} "
                "(job of a different generation rejected)"
            )
        # C1-F5: the producing job's manifest source SHA must match the video's
        # current source artifact SHA.
        current_sha = self._current_source_sha(video_item_id)
        manifest_sha = ""
        try:
            parsed = json.loads(job.input_manifest_json or "{}")
            if isinstance(parsed, dict):
                manifest_sha = str(parsed.get("source_sha256") or "")
        except (TypeError, json.JSONDecodeError):
            manifest_sha = ""
        if current_sha is not None and manifest_sha != current_sha:
            raise OwnershipMismatchError(
                f"job {job_id!r} manifest source SHA {manifest_sha!r} does "
                f"not match the video's current source SHA {current_sha!r} "
                "(wrong source SHA job rejected — C1-F5)"
            )

    def _assert_mask_artifact_ownership(
        self, artifact_id: str | None, workspace_id: str
    ) -> None:
        """C1-F5: a mask artifact MUST be a same-workspace, ``kind=image``,
        ``state=ready`` artifact.  Arbitrary video/audio/document artifacts and
        ``staging``/``trash``/``missing``/``failed`` states are rejected."""
        if artifact_id is None:
            return
        artifact = self._session.get(Artifact, artifact_id)
        if artifact is None:
            raise OwnershipMismatchError(f"artifact {artifact_id!r} does not exist")
        if artifact.workspace_id != workspace_id:
            raise OwnershipMismatchError(
                f"artifact {artifact_id!r} does not belong to workspace "
                f"{workspace_id!r} (artifact from another workspace rejected)"
            )
        if artifact.kind != "image":
            raise OwnershipMismatchError(
                f"mask artifact {artifact_id!r} must be kind=image "
                f"(got {artifact.kind!r}) — video/audio/document artifacts "
                "are not valid masks (C1-F5)"
            )
        if artifact.state != "ready":
            raise OwnershipMismatchError(
                f"mask artifact {artifact_id!r} must be state=ready "
                f"(got {artifact.state!r}) — staging/trash/missing/failed "
                "masks are rejected (C1-F5)"
            )

    def _assert_full_ownership(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        role_id: str,
        scene_id: str,
        source_job_id: str | None,
        mask_artifact_id: str | None,
        source_generation: str,
        kind: str,
    ) -> ObjectRole:
        self._assert_video_chain(workspace_id, project_id, video_item_id)
        # C1-F1: generation authority BEFORE any role/job/artifact binding.
        self._assert_segment_generation_authority(
            workspace_id, video_item_id, source_generation
        )
        self._assert_scene_ownership(scene_id, video_item_id)
        role = self._assert_role_ownership(role_id, workspace_id, video_item_id)
        self._assert_role_compatible(role, source_generation, kind)
        self._assert_job_ownership(
            source_job_id, workspace_id, video_item_id, source_generation
        )
        self._assert_mask_artifact_ownership(mask_artifact_id, workspace_id)
        return role

    def _segment_row(self, workspace_id: str, segment_id: str) -> OccurrenceSegment:
        row = self._session.get(OccurrenceSegment, segment_id)
        if row is None:
            raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
        if row.workspace_id != workspace_id:
            raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
        return row

    # ── segmentation contract (F6) ─────────────────────────────────────────

    @staticmethod
    def _validate_segmentation_contract(
        prompt: dict[str, Any] | None,
        segmentation: dict[str, Any] | None,
        mask_artifact_id: str | None,
    ) -> None:
        """A segment carrying segmentation evidence REQUIRES a mask artifact."""
        has_evidence = prompt is not None or segmentation is not None
        if has_evidence and mask_artifact_id is None:
            raise ValueError(
                "segment carries segmentation/prompt evidence but "
                "mask_artifact_id is missing (mask artifact is REQUIRED with "
                "segmentation evidence — R1 F6)"
            )
        _validate_prompt_evidence(prompt)
        _validate_prompt_evidence(segmentation)

    # ── idempotency (F9) ───────────────────────────────────────────────────

    def _idempotent_row(
        self, model: type[Any], workspace_id: str, idempotency_key: str
    ) -> Any:
        """Existing row for a workspace-scoped idempotency key (F9)."""
        return self._session.scalar(
            select(model).where(
                model.workspace_id == workspace_id,
                model.idempotency_key == idempotency_key,
            )
        )

    # ── segments (F2/F3/F5/F6/F9/F10) ──────────────────────────────────────

    # ── IntegrityError handling (C1-F6) ─────────────────────────────────────

    @staticmethod
    def _integrity_message(exc: IntegrityError) -> str:
        return " ".join(str(a or "") for a in getattr(exc, "orig", exc).args)

    @classmethod
    def _is_workspace_idempotency_conflict(
        cls, exc: IntegrityError, table: str
    ) -> bool:
        """True ONLY when the UNIQUE violation is the WORKSPACE-SCOPED
        idempotency index (workspace_id + idempotency_key) of ``table``.

        C1-F6: an IntegrityError is translated to an idempotency replay ONLY
        when this exact constraint is identified.  Any other UNIQUE / FK /
        CHECK violation keeps its true meaning (stable domain error), never a
        blanket 'duplicate'.
        """
        msg = cls._integrity_message(exc)
        return (
            "UNIQUE constraint failed:" in msg
            and f"{table}.workspace_id" in msg
            and f"{table}.idempotency_key" in msg
        )

    @staticmethod
    def _stable_integrity_error(
        exc: IntegrityError, table: str, error_cls: type[StructuralEvidenceError]
    ) -> StructuralEvidenceError:
        """Stable domain error naming the ACTUAL failing constraint (C1-F6)."""
        msg = StructuralEvidenceRepository._integrity_message(exc)
        return error_cls(
            f"{table} persistence conflict: {msg.strip() or str(exc)}"
        )

    # ── segment insert (F2/C1-F2/C1-F3/C1-F6) ───────────────────────────────

    def _insert_segment(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        role_id: str,
        scene_id: str,
        logical_id: str,
        lineage_version: int,
        compare_identity: bool = True,
        placeholder_superseded_by_id: str | None = None,
        segment_id: str | None = None,
        name: str,
        kind: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        source_generation: str,
        source_job_id: str | None,
        prompt_json: str | None,
        segmentation_json: str | None,
        mask_artifact_id: str | None,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
        visibility: str,
        z_order: int,
        idempotency_key: str | None,
    ) -> tuple[OccurrenceSegment, bool]:
        """Idempotent low-level insert of one occurrence-segment row.

        Used by BOTH the public root create (fresh ``logical_id``,
        ``lineage_version=1``) and the controlled successor/supersede path
        (keeps the lineage ``logical_id``, ``version = prior + 1``) — the
        public caller can NEVER attach an arbitrary ``logical_id`` (C1-F2).
        """
        if idempotency_key is not None:
            existing = self._idempotent_row(
                OccurrenceSegment, workspace_id, idempotency_key
            )
            if existing is not None:
                self._assert_equivalent_segment_payload(
                    existing,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    role_id=role_id,
                    scene_id=scene_id,
                    logical_id=logical_id,
                    lineage_version=lineage_version,
                    compare_identity=compare_identity,
                    name=name,
                    kind=kind,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    source_generation=source_generation,
                    source_job_id=source_job_id,
                    prompt_json=prompt_json,
                    segmentation_json=segmentation_json,
                    mask_artifact_id=mask_artifact_id,
                    algorithm=algorithm,
                    algorithm_version=algorithm_version,
                    confidence=confidence,
                    confidence_source=confidence_source,
                    reasons_json=reasons_json,
                    provenance_json=provenance_json,
                    visibility=visibility,
                    z_order=z_order,
                )
                return existing, False

        row = OccurrenceSegment(
            id=segment_id or _new_id(),
            logical_id=logical_id,
            lineage_version=lineage_version,
            superseded_by_id=placeholder_superseded_by_id,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            role_id=role_id,
            scene_id=scene_id,
            name=name,
            kind=kind,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            source_generation=source_generation,
            source_job_id=source_job_id,
            prompt_json=prompt_json,
            segmentation_json=segmentation_json,
            mask_artifact_id=mask_artifact_id,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
            visibility=visibility,
            z_order=z_order,
            idempotency_key=idempotency_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            if (
                idempotency_key is not None
                and self._is_workspace_idempotency_conflict(
                    exc, "occurrence_segment"
                )
            ):
                existing = self._idempotent_row(
                    OccurrenceSegment, workspace_id, idempotency_key
                )
                if existing is not None:
                    self._assert_equivalent_segment_payload(
                        existing,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        video_item_id=video_item_id,
                        role_id=role_id,
                        scene_id=scene_id,
                        logical_id=logical_id,
                        lineage_version=lineage_version,
                        compare_identity=compare_identity,
                        name=name,
                        kind=kind,
                        start_frame=start_frame,
                        end_frame=end_frame,
                        start_time_ms=start_time_ms,
                        end_time_ms=end_time_ms,
                        source_generation=source_generation,
                        source_job_id=source_job_id,
                        prompt_json=prompt_json,
                        segmentation_json=segmentation_json,
                        mask_artifact_id=mask_artifact_id,
                        algorithm=algorithm,
                        algorithm_version=algorithm_version,
                        confidence=confidence,
                        confidence_source=confidence_source,
                        reasons_json=reasons_json,
                        provenance_json=provenance_json,
                        visibility=visibility,
                        z_order=z_order,
                    )
                    return existing, False
            raise self._stable_integrity_error(
                exc, "occurrence_segment", SegmentConflictError
            ) from exc
        return row, True

    @staticmethod
    def _assert_equivalent_segment_payload(
        existing: OccurrenceSegment,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        role_id: str,
        scene_id: str,
        logical_id: str | None = None,
        lineage_version: int | None = None,
        compare_identity: bool = True,
        name: str,
        kind: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        source_generation: str,
        source_job_id: str | None,
        prompt_json: str | None,
        segmentation_json: str | None,
        mask_artifact_id: str | None,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
        visibility: str,
        z_order: int,
    ) -> None:
        """C1-F3: same workspace/key + same canonical identity/payload ->
        replay; ANY differing field (identity OR payload) -> stable conflict.

        Every material field participates — identity fields (workspace,
        project, video, role, scene, logical lineage, lineage version) are NOT
        silently ignored the way the R1 equivalence checks dropped them.  For
        a ROOT create the repository OWNS the lineage id (``compare_identity``
        False) so its fresh per-attempt value is not part of the caller replay
        identity; the controlled supersede path compares it.
        """
        if (
            existing.workspace_id != workspace_id
            or existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.role_id != role_id
            or existing.scene_id != scene_id
            or (
                compare_identity
                and (
                    existing.logical_id != logical_id
                    or existing.lineage_version != lineage_version
                )
            )
            or existing.name != name
            or existing.kind != kind
            or existing.start_frame != start_frame
            or existing.end_frame != end_frame
            or existing.start_time_ms != start_time_ms
            or existing.end_time_ms != end_time_ms
            or existing.source_generation != source_generation
            or existing.source_job_id != source_job_id
            or existing.prompt_json != prompt_json
            or existing.segmentation_json != segmentation_json
            or existing.mask_artifact_id != mask_artifact_id
            or existing.algorithm != algorithm
            or existing.algorithm_version != algorithm_version
            or existing.confidence != confidence
            or existing.confidence_source != confidence_source
            or existing.reasons_json != reasons_json
            or existing.provenance_json != provenance_json
            or existing.visibility != visibility
            or existing.z_order != z_order
        ):
            raise SegmentConflictError(
                f"idempotency key {existing.idempotency_key!r} is already "
                "bound to a materially different segment payload (C1-F3)"
            )

    def create_segment(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        role_id: str,
        scene_id: str,
        name: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        source_generation: str,
        *,
        logical_id: str | None = None,
        kind: str = "character",
        source_job_id: str | None = None,
        prompt: dict[str, Any] | None = None,
        segmentation: dict[str, Any] | None = None,
        mask_artifact_id: str | None = None,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float = 1.0,
        confidence_source: str = "model",
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        visibility: str = "visible",
        z_order: int = 0,
        idempotency_key: str | None = None,
    ) -> tuple[SegmentRecord, bool]:
        """Create one occurrence SEGMENT ROOT (lineage version 1).

        C1-F1/F2/F5/F6:
        - the repository OWNS ``logical_id`` — a public caller passing
          ``logical_id`` is REJECTED (no arbitrary lineage identity);
        - ``source_generation`` MUST equal the backend
          ``current_generation`` (no arbitrary future/stale generation);
        - role generation/kind must be compatible with the segment's;
        - model/detector evidence REQUIRES the producing COMPLETED
          DISCOVER_OBJECTS job (job owner/video/generation/SHA validated);
        - user/manual evidence needs no job and keeps a user provenance.
        Idempotent via the WORKSPACE-SCOPED idempotency key (never the
        natural key); replay identity is compared field-by-field (C1-F3).
        """
        if logical_id is not None:
            raise ValueError(
                "caller cannot attach an arbitrary logical_id: the repository "
                "owns the lineage identity (C1-F2)"
            )
        if kind not in OBJECT_KINDS:
            raise ValueError(f"unknown segment kind {kind!r}")
        if visibility not in OCCURRENCE_SEGMENT_VISIBILITY:
            raise ValueError(f"unknown visibility {visibility!r}")
        if confidence_source not in CONFIDENCE_SOURCES:
            raise ValueError(f"unknown confidence_source {confidence_source!r}")
        if not name.strip() or len(name) > 240:
            raise ValueError("name must be 1..240 chars")
        if not (1 <= len(source_generation) <= 64):
            raise ValueError("source_generation must be 1..64 chars")
        if not -1000000 <= z_order <= 1000000:
            raise ValueError("z_order must be between -1000000 and 1000000")
        _validate_frame_time(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        _validate_confidence(confidence)
        _validate_provenance(provenance)
        _validate_algorithm_fields(algorithm, algorithm_version)
        _validate_idempotency_key(idempotency_key)
        _validate_reasons_list(reasons)
        self._validate_segmentation_contract(prompt, segmentation, mask_artifact_id)
        # F5/C1-F1: FULL ownership + generation + role-compatibility chain
        # before any flush — zero rows on failure.  Runs BEFORE the job-required
        # check so an invalid ownership chain raises its own domain error.
        self._assert_full_ownership(
            workspace_id,
            project_id,
            video_item_id,
            role_id,
            scene_id,
            source_job_id,
            mask_artifact_id,
            source_generation,
            kind,
        )
        # C1-F5: model/detector evidence REQUIRES its producing job.
        if (
            confidence_source in REQUIRED_JOB_CONFIDENCE_SOURCES
            and source_job_id is None
        ):
            raise ValueError(
                "missing model job: model/detector segment evidence requires "
                "the producing COMPLETED DISCOVER_OBJECTS job (source_job_id) "
                "— C1-F5"
            )

        prompt_json = canonical_json(prompt) if prompt is not None else None
        segmentation_json = (
            canonical_json(segmentation) if segmentation is not None else None
        )
        reasons_json = canonical_json(reasons or [])
        provenance_json = (
            canonical_json(provenance) if provenance is not None else None
        )

        row, created = self._insert_segment(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            role_id=role_id,
            scene_id=scene_id,
            logical_id=_new_id(),
            lineage_version=1,
            # Root create: the repository owns the lineage id; a replay's fresh
            # value is not part of the caller idempotency identity (C1-F2/F3).
            compare_identity=False,
            name=name,
            kind=kind,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            source_generation=source_generation,
            source_job_id=source_job_id,
            prompt_json=prompt_json,
            segmentation_json=segmentation_json,
            mask_artifact_id=mask_artifact_id,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
            visibility=visibility,
            z_order=z_order,
            idempotency_key=idempotency_key,
        )
        return _map_segment(row), created

    def create_extraction_segment(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        role_id: str,
        scene_id: str,
        *,
        logical_id: str,
        segment_id: str,
        name: str,
        kind: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        source_generation: str,
        source_job_id: str | None,
        prompt: dict[str, Any] | None = None,
        segmentation: dict[str, Any] | None = None,
        mask_artifact_id: str | None = None,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float = 1.0,
        confidence_source: str = "model",
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        visibility: str = "visible",
        z_order: int = 0,
        idempotency_key: str | None = None,
    ) -> tuple[SegmentRecord, bool]:
        """Deterministic extraction wiring segment (T02 WIRING).

        THIN HELPER for S08-A02-T02 — justified per allowlist:

        - T02 must produce deterministic uuid5 logical_id + record id
          (scene-scoped, job-scoped) inside _publish_effect's transaction.
          The public create_segment OWNS logical_id (rejects caller value)
          per C1-F2 — but extraction wiring is the REPOSITORY-OWNED
          deterministic producer (same transaction, same invariants).
        - This helper REUSES every invariant of the public path:
          full ownership chain, generation authority, role-kind compatibility,
          segmentation contract, confidence/provenance validation, idempotency
          (workspace-scoped key), REQUIRED_JOB guard, REMOVAL_ONLY guard.
        - Never weakens invariants: every check from create_segment is
          replicated; the only difference is the caller supplies the
          deterministic lineage identity (still validated).
        """
        if not logical_id or not segment_id:
            raise ValueError("logical_id and segment_id are required (deterministic wiring)")
        if kind in REMOVAL_ONLY_KINDS:
            raise ValueError(  # noqa: E501
                f"segment kind {kind!r} is removal-only and must never be produced by extraction"  # noqa: E501
            )
        if kind not in OBJECT_KINDS:
            raise ValueError(f"unknown segment kind {kind!r}")
        if visibility not in OCCURRENCE_SEGMENT_VISIBILITY:
            raise ValueError(f"unknown visibility {visibility!r}")
        if confidence_source not in CONFIDENCE_SOURCES:
            raise ValueError(f"unknown confidence_source {confidence_source!r}")
        if not name.strip() or len(name) > 240:
            raise ValueError("name must be 1..240 chars")
        if not (1 <= len(source_generation) <= 64):
            raise ValueError("source_generation must be 1..64 chars")
        if not -1000000 <= z_order <= 1000000:
            raise ValueError("z_order must be between -1000000 and 1000000")
        _validate_frame_time(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        _validate_confidence(confidence)
        _validate_provenance(provenance)
        _validate_algorithm_fields(algorithm, algorithm_version)
        _validate_idempotency_key(idempotency_key)
        _validate_reasons_list(reasons)
        self._validate_segmentation_contract(prompt, segmentation, mask_artifact_id)
        # T02 wiring: full ownership but allow RUNNING job (publication happens before completion)
        self._assert_video_chain(workspace_id, project_id, video_item_id)
        self._assert_segment_generation_authority(
            workspace_id, video_item_id, source_generation
        )
        self._assert_scene_ownership(scene_id, video_item_id)
        _role_obj = self._assert_role_ownership(role_id, workspace_id, video_item_id)
        self._assert_role_compatible(_role_obj, source_generation, kind)
        # Custom job check: allow running or completed DISCOVER_OBJECTS job
        if source_job_id is not None:
            _job = self._session.get(Job, source_job_id)
            if _job is None:
                raise OwnershipMismatchError(f"job {source_job_id!r} does not exist")
            if _job.workspace_id != workspace_id:
                raise OwnershipMismatchError(
                    f"job {source_job_id!r} does not belong to workspace {workspace_id!r}"
                )
            if _job.owner_type != "video_item" or _job.owner_id != video_item_id:
                raise OwnershipMismatchError(
                    f"job {source_job_id!r} is owned by {_job.owner_type!r}:"
                    f"{_job.owner_id!r}, not video_item:{video_item_id!r} "
                    "(job owned by someone else rejected)"
                )
            if _job.job_type != JOB_TYPE_DISCOVER_OBJECTS or _job.state not in (  # noqa: E501
                "running",
                "completed",
                "queued",
            ):
                raise OwnershipMismatchError(
                    f"job {source_job_id!r} must be a DISCOVER_OBJECTS "
                    f"job to produce segment evidence (type={_job.job_type!r}, "
                    f"state={_job.state!r})"
                )
            if str(_job.input_generation or "") != source_generation:
                raise OwnershipMismatchError(
                    f"job {source_job_id!r} produces generation "
                    f"{_job.input_generation!r}, not {source_generation!r} "
                    "(job of a different generation rejected)"
                )
            current_sha = self._current_source_sha(video_item_id)
            manifest_sha = ""
            try:
                import json as _js
                parsed = _js.loads(_job.input_manifest_json or "{}")
                if isinstance(parsed, dict):
                    manifest_sha = str(parsed.get("source_sha256") or "")
            except Exception:
                manifest_sha = ""
            if current_sha is not None and manifest_sha != current_sha:
                raise OwnershipMismatchError(
                    f"job {source_job_id!r} manifest source SHA {manifest_sha!r} does "
                    f"not match the video's current source SHA {current_sha!r} "
                    "(wrong source SHA job rejected — C1-F5)"
                )
        self._assert_mask_artifact_ownership(mask_artifact_id, workspace_id)
        if (
            confidence_source in REQUIRED_JOB_CONFIDENCE_SOURCES
            and source_job_id is None
        ):
            raise ValueError(
                "missing model job: model/detector segment evidence requires "
                "the producing COMPLETED DISCOVER_OBJECTS job (source_job_id) "
                "— C1-F5"
            )
        prompt_json = canonical_json(prompt) if prompt is not None else None
        segmentation_json = (
            canonical_json(segmentation) if segmentation is not None else None
        )
        reasons_json = canonical_json(reasons or [])
        provenance_json = (
            canonical_json(provenance) if provenance is not None else None
        )
        row, created = self._insert_segment(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            role_id=role_id,
            scene_id=scene_id,
            logical_id=logical_id,
            lineage_version=1,
            compare_identity=True,
            segment_id=segment_id,
            name=name,
            kind=kind,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            source_generation=source_generation,
            source_job_id=source_job_id,
            prompt_json=prompt_json,
            segmentation_json=segmentation_json,
            mask_artifact_id=mask_artifact_id,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
            visibility=visibility,
            z_order=z_order,
            idempotency_key=idempotency_key,
        )
        return _map_segment(row), created

    def get_segment(
        self,
        workspace_id: str,
        segment_id: str,
        *,
        only_current: bool = False,
        source_generation: str | None = None,
    ) -> SegmentRecord:
        """Read one segment; both current and historical rows are queryable."""
        row = self._segment_row(workspace_id, segment_id)
        if source_generation is not None:
            if row.source_generation != source_generation:
                raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
        elif only_current and row.source_generation != self.current_generation(
            workspace_id, row.video_item_id
        ):
            raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
        return _map_segment(row)

    def get_segment_by_logical_id(
        self, workspace_id: str, logical_id: str
    ) -> list[SegmentRecord]:
        """All versions of a lineage by its stable logical id (oldest->newest).

        Ordered by ``lineage_version`` (C1-F2) — the version counter, not a
        timestamp, is the authoritative lineage order; no gaps/branches are
        possible because UNIQUE(workspace_id, logical_id, lineage_version).
        """
        rows = self._session.scalars(
            select(OccurrenceSegment)
            .where(
                OccurrenceSegment.workspace_id == workspace_id,
                OccurrenceSegment.logical_id == logical_id,
            )
            .order_by(
                OccurrenceSegment.lineage_version,
                OccurrenceSegment.created_at,
                OccurrenceSegment.id,
            )
        ).all()
        return [_map_segment(row) for row in rows]

    def current_segment_by_logical_id(
        self, workspace_id: str, logical_id: str
    ) -> SegmentRecord | None:
        """C1-F2: explicitly resolve the CURRENT (active) lineage version —
        ``superseded_by_id IS NULL`` is the durable current marker, not only
        the partial natural-key index."""
        row = self._session.scalar(
            select(OccurrenceSegment).where(
                OccurrenceSegment.workspace_id == workspace_id,
                OccurrenceSegment.logical_id == logical_id,
                OccurrenceSegment.superseded_by_id.is_(None),
            )
        )
        return _map_segment(row) if row is not None else None

    def list_segments(
        self,
        workspace_id: str,
        *,
        video_item_id: str | None = None,
        role_id: str | None = None,
        source_generation: str | None = None,
        only_current: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[SegmentRecord], int]:
        """List segments; current-generation default when scoped to a video."""
        filters = [OccurrenceSegment.workspace_id == workspace_id]
        if video_item_id is not None:
            filters.append(OccurrenceSegment.video_item_id == video_item_id)
        if role_id is not None:
            filters.append(OccurrenceSegment.role_id == role_id)
        if source_generation is not None:
            filters.append(
                OccurrenceSegment.source_generation == source_generation
            )
        elif only_current and video_item_id is not None:
            current = self.current_generation(workspace_id, video_item_id)
            filters.append(OccurrenceSegment.source_generation == current)
        total = int(
            self._session.scalar(
                select(func.count(OccurrenceSegment.id)).where(*filters)
            )
            or 0
        )
        rows = self._session.scalars(
            select(OccurrenceSegment)
            .where(*filters)
            .order_by(
                OccurrenceSegment.start_frame,
                OccurrenceSegment.end_frame,
                OccurrenceSegment.z_order,
                OccurrenceSegment.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return [_map_segment(row) for row in rows], total

    def list_historical_segments(
        self,
        workspace_id: str,
        source_generation: str,
        *,
        video_item_id: str | None = None,
        role_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SegmentRecord], int]:
        """Historical segment page with SQL-pushed business filtering (C3 BLOCKER 2).

        Business filter: superseded OR stale generation — pushed into SQL before
        COUNT and before OFFSET/LIMIT.  No full-history load into Python memory.

        - When video_item_id is provided, current_generation is known: if
          source_generation is stale vs current, every row of that generation is
          historical; otherwise only superseded rows are historical.
        - When video_item_id is None, per-video stale detection: rows where
          superseded_by_id IS NOT NULL OR video_item_id is in stale set
          (those videos whose current_generation != source_generation).
        Deterministic ordering: start_frame, end_frame, z_order, id.
        """
        base_filters = [
            OccurrenceSegment.workspace_id == workspace_id,
            OccurrenceSegment.source_generation == source_generation,
        ]
        if video_item_id is not None:
            base_filters.append(OccurrenceSegment.video_item_id == video_item_id)
        if role_id is not None:
            base_filters.append(OccurrenceSegment.role_id == role_id)

        if video_item_id is not None:
            # Fail-closed: unknown/corrupt ownership raises (no swallow)
            cur_gen = self.current_generation(workspace_id, video_item_id)
            is_stale = source_generation != cur_gen
            if is_stale:
                hist_filters = list(base_filters)
            else:
                hist_filters = list(base_filters) + [
                    OccurrenceSegment.superseded_by_id.is_not(None)
                ]
        else:
            # Batch generation via authoritative API (single semantic source,
            # fixed-size parameterized chunking, no per-video compound SELECT)
            distinct_vids = self._session.scalars(
                select(OccurrenceSegment.video_item_id)
                .where(*base_filters)
                .distinct()
            ).all()
            if not distinct_vids:
                hist_filters = list(base_filters) + [
                    OccurrenceSegment.superseded_by_id.is_not(None)
                ]
            else:
                # Authoritative batch resolution (chunked, fail-closed)
                batch = self._generation.batch_current_generation(
                    workspace_id, distinct_vids
                )
                stale_vids = [
                    vid for vid, cur in batch.items() if cur != source_generation
                ]
                if stale_vids:
                    # FIXED bind-parameter budget via SQLite JSON1: bind ONE
                    # JSON text param (stale_json) regardless of stale count.
                    # WHERE video_item_id IN (SELECT value FROM json_each(:stale_json))
                    # has TOTAL params = workspace_id(1)+source_generation(1)+role_id(0/1)
                    # +stale_json(1) = 3-4 (+ LIMIT/OFFSET =6) — INDEPENDENT of
                    # stale count.  No OR IN chain, no UNION ALL, no raw
                    # interpolation. Capability-checked; fails clearly if JSON1
                    # unavailable (never falls back to interpolation).
                    try:
                        self._session.execute(
                            text("SELECT value FROM json_each(:_probe)"),
                            {"_probe": '["__probe__"]'},
                        ).fetchall()
                    except Exception as exc:  # pragma: no cover
                        raise RuntimeError(
                            "SQLite JSON1 extension unavailable — "
                            "json_each() required for bounded historical query "
                            "(cannot fall back to raw interpolation)"
                        ) from exc
                    stale_json = json.dumps(stale_vids)
                    hist_filters = list(base_filters) + [
                        or_(
                            OccurrenceSegment.superseded_by_id.is_not(None),
                            text(
                                "occurrence_segment.video_item_id IN "
                                "(SELECT value FROM json_each(:stale_json))"
                            ).bindparams(
                                bindparam(
                                    "stale_json",
                                    value=stale_json,
                                    type_=String,
                                )
                            ),
                        )
                    ]
                else:
                    hist_filters = list(base_filters) + [
                        OccurrenceSegment.superseded_by_id.is_not(None)
                    ]

        total = int(
            self._session.scalar(select(func.count(OccurrenceSegment.id)).where(*hist_filters)) or 0
        )
        rows = self._session.scalars(
            select(OccurrenceSegment)
            .where(*hist_filters)
            .order_by(
                OccurrenceSegment.start_frame,
                OccurrenceSegment.end_frame,
                OccurrenceSegment.z_order,
                OccurrenceSegment.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return [_map_segment(row) for row in rows], total

    def update_segment(
        self,
        workspace_id: str,
        segment_id: str,
        revision: int,
        *,
        name: str | None = None,
        kind: str | None = None,
        start_frame: int | None = None,
        end_frame: int | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        prompt: dict[str, Any] | None = None,
        segmentation: dict[str, Any] | None = None,
        mask_artifact_id: str | None = None,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float | None = None,
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        visibility: str | None = None,
        z_order: int | None = None,
    ) -> SegmentRecord:
        """CAS in-place update of the CURRENT ACTIVE segment (R1 F8).

        In-place minor edits stay on the active row with a revision bump; an
        audited correction (new version) uses ``supersede_segment``.
        Historical/superseded/stale-generation rows are REFUSED with zero
        mutation; a stale ``revision`` is a stable conflict.
        """
        current = self._session.get(OccurrenceSegment, segment_id)
        if current is None:
            raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
        self._assert_segment_ownership(current, workspace_id)
        # Fail closed BEFORE mutation: historical rows are read-only.
        self._assert_current_generation(current)
        if kind is not None and kind not in OBJECT_KINDS:
            raise ValueError(f"unknown segment kind {kind!r}")
        # C1-F5: a segment kind UPDATE must not diverge from the ObjectRole
        # taxonomy (reclassification uses the explicit role/correction
        # contract, not an in-place occurrence-kind mutation).
        if kind is not None:
            role = self._session.get(ObjectRole, current.role_id)
            if role is None or role.kind != kind:
                raise OwnershipMismatchError(
                    f"segment kind update {kind!r} diverges from the "
                    f"ObjectRole kind {role.kind if role is not None else '?'!r} "
                    "— reclassification must use the role/correction contract "
                    "(C1-F5)"
                )
        if visibility is not None and visibility not in OCCURRENCE_SEGMENT_VISIBILITY:
            raise ValueError(f"unknown visibility {visibility!r}")
        if confidence is not None:
            _validate_confidence(confidence)
        if z_order is not None and not -1000000 <= z_order <= 1000000:
            raise ValueError("z_order must be between -1000000 and 1000000")
        if algorithm is not None or algorithm_version is not None:
            _validate_algorithm_fields(algorithm, algorithm_version)
        if reasons is not None:
            _validate_reasons_list(reasons)
        if provenance is not None:
            _validate_provenance(provenance)

        sf = current.start_frame if start_frame is None else start_frame
        ef = current.end_frame if end_frame is None else end_frame
        st = current.start_time_ms if start_time_ms is None else start_time_ms
        et = current.end_time_ms if end_time_ms is None else end_time_ms
        _validate_frame_time(start_frame=sf, end_frame=ef, start_time_ms=st, end_time_ms=et)
        merged_prompt = (
            prompt
            if prompt is not None
            else (parse_json(current.prompt_json) if current.prompt_json is not None else None)
        )
        merged_segmentation = (
            segmentation
            if segmentation is not None
            else (
                parse_json(current.segmentation_json)
                if current.segmentation_json is not None
                else None
            )
        )
        merged_mask = (
            mask_artifact_id
            if mask_artifact_id is not None
            else current.mask_artifact_id
        )
        # F6: segmentation contract must hold after the edit too.
        self._validate_segmentation_contract(
            merged_prompt, merged_segmentation, merged_mask
        )

        # C2-F2: child evidence must remain inside proposed parent range (BOTH frame and ms).
        proposed_sf = sf
        proposed_ef = ef
        proposed_st = st
        proposed_et = et
        # Check SegmentMotion attached to this segment
        for motion in self._session.scalars(
            select(SegmentMotion).where(SegmentMotion.occurrence_segment_id == segment_id)
        ).all():
            if not (
                motion.start_frame >= proposed_sf
                and motion.end_frame <= proposed_ef
                and motion.start_time_ms >= proposed_st
                and motion.end_time_ms <= proposed_et
            ):
                raise SegmentConflictError(
                    f"segment range update [{proposed_sf},{proposed_ef}] "
                    f"[{proposed_st},{proposed_et}] "
                    f"would orphan attached motion {motion.id!r} range "
                    f"[{motion.start_frame},{motion.end_frame}] "
                    f"[{motion.start_time_ms},{motion.end_time_ms}] (C2-F2)"
                )
        # Check SceneGraphOcclusion where segment is either endpoint
        for occ in self._session.scalars(
            select(SceneGraphOcclusion).where(
                (SceneGraphOcclusion.occluder_segment_id == segment_id)
                | (SceneGraphOcclusion.occludee_segment_id == segment_id)
            )
        ).all():
            if not (
                occ.start_frame >= proposed_sf
                and occ.end_frame <= proposed_ef
                and occ.start_time_ms >= proposed_st
                and occ.end_time_ms <= proposed_et
            ):
                raise SegmentConflictError(
                    f"segment range update [{proposed_sf},{proposed_ef}] "
                    f"[{proposed_st},{proposed_et}] "
                    f"would orphan attached occlusion {occ.id!r} range "
                    f"[{occ.start_frame},{occ.end_frame}] "
                    f"[{occ.start_time_ms},{occ.end_time_ms}] (C2-F2)"
                )
        # Check SceneGraphContact where segment is either endpoint
        for contact in self._session.scalars(
            select(SceneGraphContact).where(
                (SceneGraphContact.source_segment_id == segment_id)
                | (SceneGraphContact.target_segment_id == segment_id)
            )
        ).all():
            if not (
                contact.start_frame >= proposed_sf
                and contact.end_frame <= proposed_ef
                and contact.start_time_ms >= proposed_st
                and contact.end_time_ms <= proposed_et
            ):
                raise SegmentConflictError(
                    f"segment range update [{proposed_sf},{proposed_ef}] "
                    f"[{proposed_st},{proposed_et}] "
                    f"would orphan attached contact {contact.id!r} range "
                    f"[{contact.start_frame},{contact.end_frame}] "
                    f"[{contact.start_time_ms},{contact.end_time_ms}] (C2-F2)"
                )

        values: dict[str, object] = {"revision": revision + 1, "updated_at": utc_now()}
        if name is not None:
            if not name.strip() or len(name) > 240:
                raise ValueError("name must be 1..240 chars")
            values["name"] = name
        if kind is not None:
            values["kind"] = kind
        if start_frame is not None:
            values["start_frame"] = start_frame
        if end_frame is not None:
            values["end_frame"] = end_frame
        if start_time_ms is not None:
            values["start_time_ms"] = start_time_ms
        if end_time_ms is not None:
            values["end_time_ms"] = end_time_ms
        if prompt is not None:
            values["prompt_json"] = canonical_json(prompt)
        if segmentation is not None:
            values["segmentation_json"] = canonical_json(segmentation)
        if mask_artifact_id is not None:
            self._assert_mask_artifact_ownership(mask_artifact_id, workspace_id)
            values["mask_artifact_id"] = mask_artifact_id
        if algorithm is not None:
            values["algorithm"] = algorithm
        if algorithm_version is not None:
            values["algorithm_version"] = algorithm_version
        if confidence is not None:
            values["confidence"] = confidence
        if reasons is not None:
            values["reasons_json"] = canonical_json(reasons)
        if provenance is not None:
            _validate_provenance(provenance)
            values["provenance_json"] = canonical_json(provenance)
        if visibility is not None:
            values["visibility"] = visibility
        if z_order is not None:
            values["z_order"] = z_order

        stmt = (
            update(OccurrenceSegment)
            .where(
                OccurrenceSegment.id == segment_id,
                OccurrenceSegment.workspace_id == workspace_id,
                OccurrenceSegment.revision == revision,
            )
            .values(**values)
            .returning(OccurrenceSegment)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.get(OccurrenceSegment, segment_id)
            current_rev = latest.revision if latest is not None else None
            raise SegmentConflictError(
                f"stale revision {revision}; current revision is {current_rev} "
                "(R1 F8 zero-mutation conflict)"
            ) from None
        return _map_segment(row)

    def supersede_segment(
        self,
        workspace_id: str,
        segment_id: str,
        revision: int,
        *,
        source_generation: str,
        name: str | None = None,
        kind: str | None = None,
        start_frame: int | None = None,
        end_frame: int | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        source_job_id: str | None = None,
        target_role_id: str | None = None,
        prompt: dict[str, Any] | None = None,
        segmentation: dict[str, Any] | None = None,
        mask_artifact_id: str | None = None,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float | None = None,
        confidence_source: str | None = None,
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        visibility: str | None = None,
        z_order: int | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[SegmentRecord, SegmentRecord]:
        """AUDITED correction — TWO explicit workflows (C1-F1).

        A. MANUAL/user correction IN the current source generation
           (``source_generation == prior.source_generation``):
           - predecessor must be current AND active;
           - successor KEEPS the same ``source_generation``, keeps the
             lineage ``logical_id``, gets ``lineage_version = prior+1``;
           - successor MUST carry a ``user``/``manual`` ``confidence_source``
             (never silently inherits machine provenance);
           - predecessor -> historical/read-only; successor -> current.
        B. RE-ANALYSIS TRANSITION to a new source generation
           (``source_generation != prior.source_generation``):
           - target generation MUST equal the backend
             ``ObjectIntelligenceRepository.current_generation()``;
           - producing ``source_job_id`` REQUIRED and must be a COMPLETED
             DISCOVER_OBJECTS job owned by this workspace/video whose
             input_generation and manifest source SHA match;
           - prior may be from an OLDER generation but must be the ACTIVE
             lineage version; predecessor -> successor link atomic.

        The whole operation (successor creation + predecessor CAS) runs inside
        ONE savepoint and rolls back atomically on any stale/conflict.  The
        predecessor is never deleted; both current and historical rows stay
        queryable.  ``UNIQUE(workspace, logical_id, lineage_version)`` and the
        partial unique ``superseded_by`` index guarantee a concurrent supersede
        has exactly one winner (C1-F2).
        """
        prior = self._session.get(OccurrenceSegment, segment_id)
        if prior is None:
            raise SegmentNotFoundError(f"Segment {segment_id!r} not found")
        self._assert_segment_ownership(prior, workspace_id)
        if prior.revision != revision:
            raise SegmentConflictError(
                f"stale revision {revision}; current revision is {prior.revision} "
                "(C1-F1 zero-mutation conflict)"
            )
        if not (1 <= len(source_generation) <= 64):
            raise ValueError("source_generation must be 1..64 chars")
        successor_kind = kind if kind is not None else prior.kind
        if successor_kind not in OBJECT_KINDS:
            raise ValueError(f"unknown segment kind {successor_kind!r}")
        successor_confidence_source = (
            confidence_source if confidence_source is not None else prior.confidence_source
        )
        if confidence_source is not None and confidence_source not in CONFIDENCE_SOURCES:
            raise ValueError(f"unknown confidence_source {confidence_source!r}")
        if visibility is not None and visibility not in OCCURRENCE_SEGMENT_VISIBILITY:
            raise ValueError(f"unknown visibility {visibility!r}")
        if z_order is not None and not -1000000 <= z_order <= 1000000:
            raise ValueError("z_order must be between -1000000 and 1000000")
        if confidence is not None:
            _validate_confidence(confidence)
        _validate_algorithm_fields(algorithm, algorithm_version)
        _validate_idempotency_key(idempotency_key)
        _validate_reasons_list(reasons)
        if provenance is not None:
            _validate_provenance(provenance)

        sf = prior.start_frame if start_frame is None else start_frame
        ef = prior.end_frame if end_frame is None else end_frame
        st = prior.start_time_ms if start_time_ms is None else start_time_ms
        et = prior.end_time_ms if end_time_ms is None else end_time_ms
        _validate_frame_time(start_frame=sf, end_frame=ef, start_time_ms=st, end_time_ms=et)
        successor_prompt = (
            prompt
            if prompt is not None
            else (parse_json(prior.prompt_json) if prior.prompt_json is not None else None)
        )
        successor_segmentation = (
            segmentation
            if segmentation is not None
            else (
                parse_json(prior.segmentation_json)
                if prior.segmentation_json is not None
                else None
            )
        )
        successor_mask = (
            mask_artifact_id if mask_artifact_id is not None else prior.mask_artifact_id
        )
        self._validate_segmentation_contract(
            successor_prompt, successor_segmentation, successor_mask
        )

        # ── workflow selection FIRST (C1-F1) — a wrong target generation is
        # rejected here (before any role binding), with the correct stable
        # error. ─────────────────────────────────────────────────────────────
        if source_generation == prior.source_generation:
            # A. MANUAL same-generation correction (C2-F3: explicit human provenance).
            self._assert_current_generation(prior)  # current AND active
            if successor_confidence_source not in MANUAL_CONFIDENCE_SOURCES:
                raise SegmentConflictError(
                    "manual same-generation correction must carry an explicit "
                    "user/manual confidence_source — a human correction must "
                    "not silently inherit machine provenance (C1-F1 workflow A)"
                )
            # C2-F3: manual correction requires non-empty provenance supplied by caller
            if provenance is None or not isinstance(provenance, dict) or len(provenance) == 0:
                raise SegmentConflictError(
                    "manual same-generation correction requires non-empty provenance "
                    "(human audit/provenance must be supplied; "
                    "never inherit machine provenance — C2-F3)"
                )
            # C2-F1: workflow A must not switch to a different generation via target_role_id
            if target_role_id is not None and target_role_id != prior.role_id:
                # Validate the target role if provided — must be same generation/kind or 409
                target_role = self._session.get(ObjectRole, target_role_id)
                if target_role is None:
                    raise OwnershipMismatchError(
                        f"target role {target_role_id!r} does not exist (C2-F1)"
                    )
                # If target role differs, it must still be same generation/kind; otherwise 409
                # But workflow A should keep prior role — switching generation is forbidden
                if (
                    target_role.source_generation != source_generation
                    or target_role.kind != successor_kind
                ):
                    raise SegmentConflictError(
                        f"manual same-generation correction cannot switch to role "
                        f"{target_role_id!r} "
                        f"with generation {target_role.source_generation!r} "
                        f"/ kind {target_role.kind!r} "
                        f"(C2-F1 workflow A keeps prior role)"
                    )
                # Even if same gen/kind, we still treat as conflict
                # to enforce keep-prior-role unless explicitly same id
                raise SegmentConflictError(
                    f"manual same-generation correction must keep prior role "
                    f"{prior.role_id!r}; "
                    f"target_role_id {target_role_id!r} switching is forbidden (C2-F1)"
                )
            if source_job_id is not None:
                self._assert_job_ownership(
                    source_job_id, workspace_id, prior.video_item_id, source_generation
                )
        else:
            # B. Re-analysis TRANSITION to a new source generation (C2-F1: target role binding).
            self._assert_active(prior)  # ACTIVE version only (may be older gen)
            self._assert_segment_generation_authority(
                workspace_id, prior.video_item_id, source_generation
            )
            if source_job_id is None:
                raise ValueError(
                    "re-analysis transition requires the producing "
                    "source_job_id (a COMPLETED DISCOVER_OBJECTS job) — "
                    "C1-F1 workflow B"
                )
            if successor_confidence_source in MANUAL_CONFIDENCE_SOURCES:
                raise SegmentConflictError(
                    "re-analysis transition must carry model/detector/derived "
                    "evidence — a user/manual correction does not advance the "
                    "source generation (C1-F1 workflow B)"
                )
            self._assert_job_ownership(
                source_job_id, workspace_id, prior.video_item_id, source_generation
            )
            # C2-F1: workflow B requires target_role_id belonging to new generation
            if target_role_id is None:
                raise SegmentConflictError(
                    "re-analysis transition requires target_role_id of the new generation (C2-F1)"
                )

        # C2-F1: Role binding — workflow B uses target_role_id, workflow A keeps prior role.
        if source_generation != prior.source_generation:
            # Workflow B: validate target role
            role = self._session.get(ObjectRole, target_role_id)
            if role is None:
                raise OwnershipMismatchError(
                    f"target role {target_role_id!r} does not exist (C2-F1)"
                )
            if role.workspace_id != workspace_id:
                raise OwnershipMismatchError(
                    f"target role {target_role_id!r} does not belong to "
                    f"workspace {workspace_id!r} (C2-F1)"
                )
            if role.project_id != prior.project_id:
                raise OwnershipMismatchError(
                    f"target role {target_role_id!r} belongs to project {role.project_id!r}, "
                    f"not {prior.project_id!r} (project mismatch -- C3 BLOCKER 1)"
                )
            if role.video_item_id != prior.video_item_id:
                raise OwnershipMismatchError(
                    f"target role {target_role_id!r} belongs to video {role.video_item_id!r}, "
                    f"not {prior.video_item_id!r} (C2-F1)"
                )
            self._assert_role_compatible(role, source_generation, successor_kind)
        else:
            # Workflow A: keep prior role
            role = self._session.get(ObjectRole, prior.role_id)
            if role is None:
                raise OwnershipMismatchError(f"role {prior.role_id!r} does not exist")
            if role.project_id != prior.project_id:
                raise OwnershipMismatchError(
                    f"role {prior.role_id!r} belongs to project {role.project_id!r}, "
                    f"not {prior.project_id!r} (project mismatch -- C3 BLOCKER 1)"
                )
            self._assert_role_compatible(role, source_generation, successor_kind)

        successor_source_job_id = (
            source_job_id if source_job_id is not None else prior.source_job_id
        )
        prompt_json = (
            canonical_json(successor_prompt) if successor_prompt is not None else None
        )
        segmentation_json = (
            canonical_json(successor_segmentation)
            if successor_segmentation is not None
            else None
        )
        reasons_json = canonical_json(
            reasons if reasons is not None else _reasons(prior.reasons_json)
        )
        # C2-F3: for workflow A provenance is required and already validated;
        # never inherit machine provenance when missing.
        provenance_json = (
            canonical_json(provenance)
            if provenance is not None
            else prior.provenance_json
        )

        with self._session.begin_nested():
            # C1-F2/active-identity: a same-generation successor (workflow A)
            # occupies the SAME (role, scene, frames, gen) slot as its still
            # -active predecessor.  The partial unique active-identity index
            # (WHERE superseded_by_id IS NULL) is evaluated per INSERT, so the
            # successor is first inserted with a deferred placeholder id
            # placeholder_superseded_by_id=_new_id() (excluded from the active
            # index; its id is guaranteed fresh/unique), then retargeted to NULL
            # (ACTIVE) after the predecessor CAS — all inside this one atomic
            # savepoint.
            successor_id = _new_id()
            assert target_role_id is not None or source_generation == prior.source_generation
            successor_role_id = (
                target_role_id
                if source_generation != prior.source_generation
                else prior.role_id
            )
            assert successor_role_id is not None
            successor_row, created = self._insert_segment(
                workspace_id=workspace_id,
                project_id=prior.project_id,
                video_item_id=prior.video_item_id,
                role_id=successor_role_id,
                scene_id=prior.scene_id,
                logical_id=prior.logical_id,
                lineage_version=prior.lineage_version + 1,
                placeholder_superseded_by_id=_new_id(),
                segment_id=successor_id,
                name=name if name is not None else prior.name,
                kind=successor_kind,
                start_frame=sf,
                end_frame=ef,
                start_time_ms=st,
                end_time_ms=et,
                source_generation=source_generation,
                source_job_id=successor_source_job_id,
                prompt_json=prompt_json,
                segmentation_json=segmentation_json,
                mask_artifact_id=successor_mask,
                algorithm=algorithm if algorithm is not None else prior.algorithm,
                algorithm_version=(
                    algorithm_version if algorithm_version is not None else prior.algorithm_version
                ),
                confidence=confidence if confidence is not None else prior.confidence,
                confidence_source=successor_confidence_source,
                reasons_json=reasons_json,
                provenance_json=provenance_json,
                visibility=visibility if visibility is not None else prior.visibility,
                z_order=z_order if z_order is not None else prior.z_order,
                idempotency_key=idempotency_key,
            )
            if not created:
                raise SegmentConflictError(
                    "supersede could not create a successor (idempotency "
                    "collision); the correction was rolled back"
                )
            stmt = (
                update(OccurrenceSegment)
                .where(
                    OccurrenceSegment.id == segment_id,
                    OccurrenceSegment.revision == revision,
                )
                .values(
                    superseded_by_id=successor_row.id,
                    revision=revision + 1,
                    updated_at=utc_now(),
                )
                .returning(OccurrenceSegment)
            )
            try:
                prior_row = self._session.execute(stmt).scalar_one()
            except NoResultFound:
                latest_prior = self._session.get(OccurrenceSegment, segment_id)
                current_rev = latest_prior.revision if latest_prior is not None else None
                raise SegmentConflictError(
                    f"stale revision {revision}; current revision is "
                    f"{current_rev} "
                    "(supersede rolled back atomically; C1-F1/F2)"
                ) from None
            # Retarget the successor from its insert placeholder to ACTIVE.
            self._session.execute(
                update(OccurrenceSegment)
                .where(OccurrenceSegment.id == successor_row.id)
                .values(superseded_by_id=None)
            )
            self._session.refresh(successor_row)
        return _map_segment(prior_row), _map_segment(successor_row)

    def segment_lineage(self, workspace_id: str, segment_id: str) -> list[SegmentRecord]:
        """Walk the supersession chain OLDEST -> NEWEST (R1 F7).

        Accepts ANY version in a lineage: first finds the oldest predecessor,
        then walks forward through ``superseded_by_id``.  Detects cycles and
        dangling forward links with stable errors; never returns a reversed
        result.
        """
        start = self._segment_row(workspace_id, segment_id)

        back_seen: set[str] = set()
        current_id = start.id
        oldest = start
        while True:
            if current_id in back_seen:
                raise SegmentConflictError("segment supersession cycle detected")
            back_seen.add(current_id)
            preds = self._session.scalars(
                select(OccurrenceSegment).where(
                    OccurrenceSegment.superseded_by_id == current_id
                )
            ).all()
            if len(preds) > 1:
                # C1-F2: a branch would give the lineage TWO predecessors of the
                # same version — fail closed (a state the repository can never
                # create; only raw corruption could).
                raise SegmentConflictError(
                    f"duplicate predecessor: {len(preds)} rows claim "
                    f"superseded_by_id={current_id!r} (branching lineage — "
                    "C1-F2)"
                )
            if not preds:
                break
            oldest = preds[0]
            current_id = oldest.id

        chain: list[SegmentRecord] = []
        fwd_seen: set[str] = set()
        node_id: str | None = oldest.id
        while node_id is not None:
            if node_id in fwd_seen:
                raise SegmentConflictError("segment supersession cycle detected")
            fwd_seen.add(node_id)
            row = self._session.get(OccurrenceSegment, node_id)
            if row is None:
                raise SegmentConflictError(
                    f"dangling supersession link: {node_id!r} is referenced "
                    "by a predecessor but does not exist"
                )
            chain.append(_map_segment(row))
            node_id = row.superseded_by_id
        return chain

    # ── segment motion (F8/F9/F10) ─────────────────────────────────────────

    def create_motion(
        self,
        workspace_id: str,
        occurrence_segment_id: str,
        transform_type: str,
        transform: dict[str, Any],
        *,
        point_track_flow_ref: dict[str, Any] | list[Any] | None = None,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float = 1.0,
        confidence_source: str = "model",
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[MotionRecord, bool]:
        """Create one motion record for a segment (CONTRACT-ONLY)."""
        if transform_type not in MOTION_TRANSFORM_TYPES:
            raise ValueError(
                f"unknown transform_type {transform_type!r}; expected "
                "'camera_relative' or 'object_relative'"
            )
        if confidence_source not in CONFIDENCE_SOURCES:
            raise ValueError(f"unknown confidence_source {confidence_source!r}")
        _validate_frame_time(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        _validate_confidence(confidence)
        _validate_provenance(provenance)
        _validate_algorithm_fields(algorithm, algorithm_version)
        _validate_idempotency_key(idempotency_key)
        _validate_reasons_list(reasons)
        if not isinstance(transform, dict):
            raise ValueError("transform must be a JSON object")
        segment = self._segment_row(workspace_id, occurrence_segment_id)
        # Motion evidence attaches to a CURRENT ACTIVE segment (F8/F10).
        self._assert_current_generation(segment)
        # C1-F4: motion range must be within the segment range in BOTH frame
        # and time dimensions.
        self._assert_range_within(
            segment, start_frame, end_frame, start_time_ms, end_time_ms
        )

        transform_json = canonical_json(transform)
        ref_json = (
            canonical_json(point_track_flow_ref)
            if point_track_flow_ref is not None
            else None
        )
        reasons_json = canonical_json(reasons or [])
        provenance_json = (
            canonical_json(provenance) if provenance is not None else None
        )

        row = SegmentMotion(
            workspace_id=workspace_id,
            occurrence_segment_id=occurrence_segment_id,
            transform_type=transform_type,
            transform_json=transform_json,
            point_track_flow_ref_json=ref_json,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
            idempotency_key=idempotency_key,
        )
        return self._create_motion_row(
            row,
            idempotency_key=idempotency_key,
            workspace_id=workspace_id,
            occurrence_segment_id=occurrence_segment_id,
            transform_type=transform_type,
            transform_json=transform_json,
            ref_json=ref_json,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
        )

    @staticmethod
    def _assert_equivalent_motion_request(
        existing: SegmentMotion,
        *,
        workspace_id: str,
        occurrence_segment_id: str,
        transform_type: str,
        transform_json: str,
        ref_json: str | None,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
    ) -> None:
        """C1-F3: motion idempotency compares the FULL canonical identity AND
        payload — including ``occurrence_segment_id``, ``transform_type`` and
        ``start_frame`` (the R1 check silently dropped identity fields, so a
        replay with a different segment/type/frame was wrongly treated as a
        duplicate)."""
        if (
            existing.workspace_id != workspace_id
            or existing.occurrence_segment_id != occurrence_segment_id
            or existing.transform_type != transform_type
            or existing.transform_json != transform_json
            or existing.point_track_flow_ref_json != ref_json
            or existing.start_frame != start_frame
            or existing.end_frame != end_frame
            or existing.start_time_ms != start_time_ms
            or existing.end_time_ms != end_time_ms
            or existing.algorithm != algorithm
            or existing.algorithm_version != algorithm_version
            or existing.confidence != confidence
            or existing.confidence_source != confidence_source
            or existing.reasons_json != reasons_json
            or existing.provenance_json != provenance_json
        ):
            raise MotionConflictError(
                f"idempotency key {existing.idempotency_key!r} is already "
                "bound to a materially different motion payload (C1-F3)"
            )

    def _create_motion_row(
        self,
        row: SegmentMotion,
        *,
        idempotency_key: str | None,
        workspace_id: str,
        occurrence_segment_id: str,
        transform_type: str,
        transform_json: str,
        ref_json: str | None,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
    ) -> tuple[MotionRecord, bool]:
        if idempotency_key is not None:
            existing = self._idempotent_row(
                SegmentMotion, workspace_id, idempotency_key
            )
            if existing is not None:
                self._assert_equivalent_motion_request(
                    existing,
                    workspace_id=workspace_id,
                    occurrence_segment_id=occurrence_segment_id,
                    transform_type=transform_type,
                    transform_json=transform_json,
                    ref_json=ref_json,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    algorithm=algorithm,
                    algorithm_version=algorithm_version,
                    confidence=confidence,
                    confidence_source=confidence_source,
                    reasons_json=reasons_json,
                    provenance_json=provenance_json,
                )
                return _map_motion(existing), False
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            if (
                idempotency_key is not None
                and self._is_workspace_idempotency_conflict(exc, "segment_motion")
            ):
                existing = self._idempotent_row(
                    SegmentMotion, workspace_id, idempotency_key
                )
                if existing is not None:
                    self._assert_equivalent_motion_request(
                        existing,
                        workspace_id=workspace_id,
                        occurrence_segment_id=occurrence_segment_id,
                        transform_type=transform_type,
                        transform_json=transform_json,
                        ref_json=ref_json,
                        start_frame=start_frame,
                        end_frame=end_frame,
                        start_time_ms=start_time_ms,
                        end_time_ms=end_time_ms,
                        algorithm=algorithm,
                        algorithm_version=algorithm_version,
                        confidence=confidence,
                        confidence_source=confidence_source,
                        reasons_json=reasons_json,
                        provenance_json=provenance_json,
                    )
                    return _map_motion(existing), False
            # C1-F6: keep the REAL constraint (e.g. the (segment, type,
            # start frame) unique) — never blanket "duplicate".
            raise self._stable_integrity_error(
                exc, "segment_motion", MotionConflictError
            ) from exc
        return _map_motion(row), True

    def list_motions(
        self, workspace_id: str, occurrence_segment_id: str
    ) -> list[MotionRecord]:
        self._segment_row(workspace_id, occurrence_segment_id)
        rows = self._session.scalars(
            select(SegmentMotion)
            .where(SegmentMotion.occurrence_segment_id == occurrence_segment_id)
            .order_by(
                SegmentMotion.transform_type,
                SegmentMotion.start_frame,
                SegmentMotion.id,
            )
        ).all()
        return [_map_motion(row) for row in rows]

    def get_motion(self, workspace_id: str, motion_id: str) -> MotionRecord:
        row = self._session.get(SegmentMotion, motion_id)
        if row is None or row.workspace_id != workspace_id:
            raise MotionNotFoundError(f"Motion {motion_id!r} not found")
        return _map_motion(row)

    def update_motion(
        self,
        workspace_id: str,
        motion_id: str,
        revision: int,
        *,
        transform: dict[str, Any] | None = None,
        point_track_flow_ref: dict[str, Any] | list[Any] | None = None,
        end_frame: int | None = None,
        end_time_ms: int | None = None,
        confidence: float | None = None,
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> MotionRecord:
        """CAS update (R1 F8): owner + current/active segment verified; stale
        revision is a stable conflict with ZERO mutation."""
        current = self._session.get(SegmentMotion, motion_id)
        if current is None or current.workspace_id != workspace_id:
            raise MotionNotFoundError(f"Motion {motion_id!r} not found")
        segment = self._session.get(OccurrenceSegment, current.occurrence_segment_id)
        if segment is None:
            raise SegmentNotFoundError(
                f"Motion {motion_id!r} references a missing segment"
            )
        self._assert_segment_ownership(segment, workspace_id)
        self._assert_current_generation(segment)
        if confidence is not None:
            _validate_confidence(confidence)
        if transform is not None:
            if not isinstance(transform, dict):
                raise ValueError("transform must be a JSON object")
            _validate_provenance(transform)

        end = current.end_frame if end_frame is None else end_frame
        et = current.end_time_ms if end_time_ms is None else end_time_ms
        if end < current.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        if et < current.start_time_ms:
            raise ValueError("end_time_ms must be >= start_time_ms")
        new_end = current.end_frame if end_frame is None else end_frame
        new_et = current.end_time_ms if end_time_ms is None else end_time_ms
        # C1-F4: BOTH frames AND times stay within the segment range.
        self._assert_range_within(
            segment, current.start_frame, new_end, current.start_time_ms, new_et
        )

        values: dict[str, object] = {"revision": revision + 1, "updated_at": utc_now()}
        if transform is not None:
            values["transform_json"] = canonical_json(transform)
        if point_track_flow_ref is not None:
            values["point_track_flow_ref_json"] = canonical_json(point_track_flow_ref)
        if end_frame is not None:
            values["end_frame"] = end_frame
        if end_time_ms is not None:
            values["end_time_ms"] = end_time_ms
        if confidence is not None:
            values["confidence"] = confidence
        if reasons is not None:
            values["reasons_json"] = canonical_json(reasons)
        if provenance is not None:
            _validate_provenance(provenance)
            values["provenance_json"] = canonical_json(provenance)

        stmt = (
            update(SegmentMotion)
            .where(
                SegmentMotion.id == motion_id,
                SegmentMotion.workspace_id == workspace_id,
                SegmentMotion.revision == revision,
            )
            .values(**values)
            .returning(SegmentMotion)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.get(SegmentMotion, motion_id)
            current_rev = latest.revision if latest is not None else None
            raise MotionConflictError(
                f"stale revision {revision}; current revision is {current_rev} "
                "(R1 F8 zero-mutation conflict)"
            ) from None
        return _map_motion(row)

    # ── shared edge helpers (F10) ──────────────────────────────────────────

    @staticmethod
    def _assert_range_within(
        segment: OccurrenceSegment,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
    ) -> None:
        """C1-F4: an edge/motion temporal range must fit the segment range in
        BOTH frame AND time dimensions (R1 F10 only checked frames)."""
        if (
            start_frame < segment.start_frame
            or end_frame > segment.end_frame
            or start_time_ms < segment.start_time_ms
            or end_time_ms > segment.end_time_ms
        ):
            raise ValueError(
                "temporal range "
                f"[{start_frame}, {end_frame}] frames / "
                f"[{start_time_ms}, {end_time_ms}] ms is outside the "
                f"segment range [{segment.start_frame}, {segment.end_frame}] "
                f"frames / [{segment.start_time_ms}, {segment.end_time_ms}] ms "
                "(edge/motion range must be within the segment range — C1-F4)"
            )

    # ── occlusion edges (F8/F9/F10) ────────────────────────────────────────

    def create_occlusion(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        occluder_segment_id: str,
        occludee_segment_id: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        *,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float = 1.0,
        confidence_source: str = "model",
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[OcclusionRecord, bool]:
        """Create one occlusion edge (occluder -> occludee)."""
        if occluder_segment_id == occludee_segment_id:
            raise ValueError("occluder and occludee must be different segments")
        if confidence_source not in CONFIDENCE_SOURCES:
            raise ValueError(f"unknown confidence_source {confidence_source!r}")
        _validate_frame_time(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        _validate_confidence(confidence)
        _validate_provenance(provenance)
        _validate_algorithm_fields(algorithm, algorithm_version)
        _validate_idempotency_key(idempotency_key)
        _validate_reasons_list(reasons)
        self._assert_video_chain(workspace_id, project_id, video_item_id)
        occluder = self._segment_row(workspace_id, occluder_segment_id)
        occludee = self._segment_row(workspace_id, occludee_segment_id)
        if occluder.video_item_id != video_item_id or occludee.video_item_id != video_item_id:
            raise OwnershipMismatchError(
                "occlusion endpoints must belong to the same video item"
            )
        # F10: endpoints must be current-generation (compatible generation).
        self._assert_current_generation(occluder)
        self._assert_current_generation(occludee)
        # C1-F4: the edge range must be within BOTH endpoint segments in BOTH
        # frame and time dimensions.
        self._assert_range_within(
            occluder, start_frame, end_frame, start_time_ms, end_time_ms
        )
        self._assert_range_within(
            occludee, start_frame, end_frame, start_time_ms, end_time_ms
        )

        reasons_json = canonical_json(reasons or [])
        provenance_json = (
            canonical_json(provenance) if provenance is not None else None
        )

        row = SceneGraphOcclusion(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            occluder_segment_id=occluder_segment_id,
            occludee_segment_id=occludee_segment_id,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
            idempotency_key=idempotency_key,
        )
        return self._create_occlusion_row(
            row,
            idempotency_key=idempotency_key,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            occluder_segment_id=occluder_segment_id,
            occludee_segment_id=occludee_segment_id,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
        )

    def _create_occlusion_row(
        self,
        row: SceneGraphOcclusion,
        *,
        idempotency_key: str | None,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        occluder_segment_id: str,
        occludee_segment_id: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
    ) -> tuple[OcclusionRecord, bool]:
        if idempotency_key is not None:
            existing = self._idempotent_row(
                SceneGraphOcclusion, workspace_id, idempotency_key
            )
            if existing is not None:
                self._assert_equivalent_occlusion_request(
                    existing,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    occluder_segment_id=occluder_segment_id,
                    occludee_segment_id=occludee_segment_id,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    algorithm=algorithm,
                    algorithm_version=algorithm_version,
                    confidence=confidence,
                    confidence_source=confidence_source,
                    reasons_json=reasons_json,
                    provenance_json=provenance_json,
                )
                return _map_occlusion(existing), False
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            if (
                idempotency_key is not None
                and self._is_workspace_idempotency_conflict(
                    exc, "scene_graph_occlusion"
                )
            ):
                existing = self._idempotent_row(
                    SceneGraphOcclusion, workspace_id, idempotency_key
                )
                if existing is not None:
                    self._assert_equivalent_occlusion_request(
                        existing,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        video_item_id=video_item_id,
                        occluder_segment_id=occluder_segment_id,
                        occludee_segment_id=occludee_segment_id,
                        start_frame=start_frame,
                        end_frame=end_frame,
                        start_time_ms=start_time_ms,
                        end_time_ms=end_time_ms,
                        algorithm=algorithm,
                        algorithm_version=algorithm_version,
                        confidence=confidence,
                        confidence_source=confidence_source,
                        reasons_json=reasons_json,
                        provenance_json=provenance_json,
                    )
                    return _map_occlusion(existing), False
            # C1-F6: keep the REAL constraint — never a blanket "duplicate".
            raise self._stable_integrity_error(
                exc, "scene_graph_occlusion", OcclusionConflictError
            ) from exc
        return _map_occlusion(row), True

    @staticmethod
    def _assert_equivalent_occlusion_request(
        existing: SceneGraphOcclusion,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        occluder_segment_id: str,
        occludee_segment_id: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
    ) -> None:
        """C1-F3: occlusion idempotency compares the FULL canonical identity —
        including project/video and BOTH endpoint segment ids and the start
        frame — plus the payload.  A replay with a different endpoint pair or
        start frame is a conflict, not a duplicate replay."""
        if (
            existing.workspace_id != workspace_id
            or existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.occluder_segment_id != occluder_segment_id
            or existing.occludee_segment_id != occludee_segment_id
            or existing.start_frame != start_frame
            or existing.end_frame != end_frame
            or existing.start_time_ms != start_time_ms
            or existing.end_time_ms != end_time_ms
            or existing.algorithm != algorithm
            or existing.algorithm_version != algorithm_version
            or existing.confidence != confidence
            or existing.confidence_source != confidence_source
            or existing.reasons_json != reasons_json
            or existing.provenance_json != provenance_json
        ):
            raise OcclusionConflictError(
                f"idempotency key {existing.idempotency_key!r} is already "
                "bound to a materially different occlusion payload (C1-F3)"
            )

    def list_occlusions(
        self, workspace_id: str, *, segment_id: str | None = None
    ) -> list[OcclusionRecord]:
        filters = [SceneGraphOcclusion.workspace_id == workspace_id]
        if segment_id is not None:
            filters.append(
                (SceneGraphOcclusion.occluder_segment_id == segment_id)
                | (SceneGraphOcclusion.occludee_segment_id == segment_id)
            )
        rows = self._session.scalars(
            select(SceneGraphOcclusion)
            .where(*filters)
            .order_by(
                SceneGraphOcclusion.start_frame,
                SceneGraphOcclusion.occluder_segment_id,
                SceneGraphOcclusion.id,
            )
        ).all()
        return [_map_occlusion(row) for row in rows]

    def get_occlusion(self, workspace_id: str, occlusion_id: str) -> OcclusionRecord:
        row = self._session.get(SceneGraphOcclusion, occlusion_id)
        if row is None or row.workspace_id != workspace_id:
            raise OcclusionNotFoundError(f"Occlusion {occlusion_id!r} not found")
        return _map_occlusion(row)

    def update_occlusion(
        self,
        workspace_id: str,
        occlusion_id: str,
        revision: int,
        *,
        end_frame: int | None = None,
        end_time_ms: int | None = None,
        confidence: float | None = None,
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> OcclusionRecord:
        """CAS update (R1 F8): owner + current/active segment endpoints checked;
        stale revision is a stable conflict with ZERO mutation."""
        current = self._session.get(SceneGraphOcclusion, occlusion_id)
        if current is None or current.workspace_id != workspace_id:
            raise OcclusionNotFoundError(f"Occlusion {occlusion_id!r} not found")
        occluder = self._session.get(OccurrenceSegment, current.occluder_segment_id)
        occludee = self._session.get(OccurrenceSegment, current.occludee_segment_id)
        if occluder is None or occludee is None:
            raise OcclusionConflictError(
                f"Occlusion {occlusion_id!r} references a missing endpoint segment"
            )
        self._assert_segment_ownership(occluder, workspace_id)
        self._assert_current_generation(occluder)
        self._assert_current_generation(occludee)
        if confidence is not None:
            _validate_confidence(confidence)

        end = current.end_frame if end_frame is None else end_frame
        if end < current.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        et = current.end_time_ms if end_time_ms is None else end_time_ms
        if et < current.start_time_ms:
            raise ValueError("end_time_ms must be >= start_time_ms")
        new_end = current.end_frame if end_frame is None else end_frame
        new_et = current.end_time_ms if end_time_ms is None else end_time_ms
        # C1-F4: BOTH endpoint segments, BOTH frame+time dimensions.
        self._assert_range_within(
            occluder, current.start_frame, new_end, current.start_time_ms, new_et
        )
        self._assert_range_within(
            occludee, current.start_frame, new_end, current.start_time_ms, new_et
        )

        values: dict[str, object] = {"revision": revision + 1, "updated_at": utc_now()}
        if end_frame is not None:
            values["end_frame"] = end_frame
        if end_time_ms is not None:
            if end_time_ms < current.start_time_ms:
                raise ValueError("end_time_ms must be >= start_time_ms")
            values["end_time_ms"] = end_time_ms
        if confidence is not None:
            values["confidence"] = confidence
        if reasons is not None:
            values["reasons_json"] = canonical_json(reasons)
        if provenance is not None:
            _validate_provenance(provenance)
            values["provenance_json"] = canonical_json(provenance)

        stmt = (
            update(SceneGraphOcclusion)
            .where(
                SceneGraphOcclusion.id == occlusion_id,
                SceneGraphOcclusion.workspace_id == workspace_id,
                SceneGraphOcclusion.revision == revision,
            )
            .values(**values)
            .returning(SceneGraphOcclusion)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.get(SceneGraphOcclusion, occlusion_id)
            current_rev = latest.revision if latest is not None else None
            raise OcclusionConflictError(
                f"stale revision {revision}; current revision is {current_rev} "
                "(R1 F8 zero-mutation conflict)"
            ) from None
        return _map_occlusion(row)

    # ── contact edges (F8/F9/F10) ──────────────────────────────────────────

    def create_contact(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_segment_id: str,
        target_segment_id: str,
        contact_kind: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        *,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float = 1.0,
        confidence_source: str = "model",
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[ContactRecord, bool]:
        """Create one contact edge/event (source -> target)."""
        if source_segment_id == target_segment_id:
            raise ValueError("source and target must be different segments")
        if contact_kind not in CONTACT_KINDS:
            raise ValueError(f"unknown contact_kind {contact_kind!r}")
        if confidence_source not in CONFIDENCE_SOURCES:
            raise ValueError(f"unknown confidence_source {confidence_source!r}")
        _validate_frame_time(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )
        _validate_confidence(confidence)
        _validate_provenance(provenance)
        _validate_algorithm_fields(algorithm, algorithm_version)
        _validate_idempotency_key(idempotency_key)
        _validate_reasons_list(reasons)
        self._assert_video_chain(workspace_id, project_id, video_item_id)
        source = self._segment_row(workspace_id, source_segment_id)
        target = self._segment_row(workspace_id, target_segment_id)
        if source.video_item_id != video_item_id or target.video_item_id != video_item_id:
            raise OwnershipMismatchError(
                "contact endpoints must belong to the same video item"
            )
        # F10: endpoints must be current-generation (compatible generation).
        self._assert_current_generation(source)
        self._assert_current_generation(target)
        # C1-F4: the edge range must be within BOTH endpoint segments in BOTH
        # frame and time dimensions.
        self._assert_range_within(
            source, start_frame, end_frame, start_time_ms, end_time_ms
        )
        self._assert_range_within(
            target, start_frame, end_frame, start_time_ms, end_time_ms
        )

        reasons_json = canonical_json(reasons or [])
        provenance_json = (
            canonical_json(provenance) if provenance is not None else None
        )

        row = SceneGraphContact(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            source_segment_id=source_segment_id,
            target_segment_id=target_segment_id,
            contact_kind=contact_kind,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
            idempotency_key=idempotency_key,
        )
        return self._create_contact_row(
            row,
            idempotency_key=idempotency_key,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            source_segment_id=source_segment_id,
            target_segment_id=target_segment_id,
            contact_kind=contact_kind,
            start_frame=start_frame,
            end_frame=end_frame,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence,
            confidence_source=confidence_source,
            reasons_json=reasons_json,
            provenance_json=provenance_json,
        )

    def _create_contact_row(
        self,
        row: SceneGraphContact,
        *,
        idempotency_key: str | None,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_segment_id: str,
        target_segment_id: str,
        contact_kind: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
    ) -> tuple[ContactRecord, bool]:
        if idempotency_key is not None:
            existing = self._idempotent_row(
                SceneGraphContact, workspace_id, idempotency_key
            )
            if existing is not None:
                self._assert_equivalent_contact_request(
                    existing,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    source_segment_id=source_segment_id,
                    target_segment_id=target_segment_id,
                    contact_kind=contact_kind,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    algorithm=algorithm,
                    algorithm_version=algorithm_version,
                    confidence=confidence,
                    confidence_source=confidence_source,
                    reasons_json=reasons_json,
                    provenance_json=provenance_json,
                )
                return _map_contact(existing), False
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            if (
                idempotency_key is not None
                and self._is_workspace_idempotency_conflict(
                    exc, "scene_graph_contact"
                )
            ):
                existing = self._idempotent_row(
                    SceneGraphContact, workspace_id, idempotency_key
                )
                if existing is not None:
                    self._assert_equivalent_contact_request(
                        existing,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        video_item_id=video_item_id,
                        source_segment_id=source_segment_id,
                        target_segment_id=target_segment_id,
                        contact_kind=contact_kind,
                        start_frame=start_frame,
                        end_frame=end_frame,
                        start_time_ms=start_time_ms,
                        end_time_ms=end_time_ms,
                        algorithm=algorithm,
                        algorithm_version=algorithm_version,
                        confidence=confidence,
                        confidence_source=confidence_source,
                        reasons_json=reasons_json,
                        provenance_json=provenance_json,
                    )
                    return _map_contact(existing), False
            # C1-F6: keep the REAL constraint — never a blanket "duplicate".
            raise self._stable_integrity_error(
                exc, "scene_graph_contact", ContactConflictError
            ) from exc
        return _map_contact(row), True

    @staticmethod
    def _assert_equivalent_contact_request(
        existing: SceneGraphContact,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_segment_id: str,
        target_segment_id: str,
        contact_kind: str,
        start_frame: int,
        end_frame: int,
        start_time_ms: int,
        end_time_ms: int,
        algorithm: str | None,
        algorithm_version: str | None,
        confidence: float,
        confidence_source: str,
        reasons_json: str,
        provenance_json: str | None,
    ) -> None:
        """C1-F3: contact idempotency compares the FULL canonical identity —
        including project/video, BOTH endpoint segment ids, the contact kind
        and the start frame — plus the payload.  A replay with a different
        endpoint/kind/start frame is a conflict, not a duplicate replay."""
        if (
            existing.workspace_id != workspace_id
            or existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.source_segment_id != source_segment_id
            or existing.target_segment_id != target_segment_id
            or existing.contact_kind != contact_kind
            or existing.start_frame != start_frame
            or existing.end_frame != end_frame
            or existing.start_time_ms != start_time_ms
            or existing.end_time_ms != end_time_ms
            or existing.algorithm != algorithm
            or existing.algorithm_version != algorithm_version
            or existing.confidence != confidence
            or existing.confidence_source != confidence_source
            or existing.reasons_json != reasons_json
            or existing.provenance_json != provenance_json
        ):
            raise ContactConflictError(
                f"idempotency key {existing.idempotency_key!r} is already "
                "bound to a materially different contact payload (C1-F3)"
            )

    def list_contacts(
        self, workspace_id: str, *, segment_id: str | None = None
    ) -> list[ContactRecord]:
        filters = [SceneGraphContact.workspace_id == workspace_id]
        if segment_id is not None:
            filters.append(
                (SceneGraphContact.source_segment_id == segment_id)
                | (SceneGraphContact.target_segment_id == segment_id)
            )
        rows = self._session.scalars(
            select(SceneGraphContact)
            .where(*filters)
            .order_by(
                SceneGraphContact.start_frame,
                SceneGraphContact.source_segment_id,
                SceneGraphContact.contact_kind,
                SceneGraphContact.id,
            )
        ).all()
        return [_map_contact(row) for row in rows]

    def get_contact(self, workspace_id: str, contact_id: str) -> ContactRecord:
        row = self._session.get(SceneGraphContact, contact_id)
        if row is None or row.workspace_id != workspace_id:
            raise ContactNotFoundError(f"Contact {contact_id!r} not found")
        return _map_contact(row)

    def update_contact(
        self,
        workspace_id: str,
        contact_id: str,
        revision: int,
        *,
        end_frame: int | None = None,
        end_time_ms: int | None = None,
        confidence: float | None = None,
        reasons: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ContactRecord:
        """CAS update (R1 F8): owner + current/active segment endpoints checked;
        stale revision is a stable conflict with ZERO mutation."""
        current = self._session.get(SceneGraphContact, contact_id)
        if current is None or current.workspace_id != workspace_id:
            raise ContactNotFoundError(f"Contact {contact_id!r} not found")
        source = self._session.get(OccurrenceSegment, current.source_segment_id)
        target = self._session.get(OccurrenceSegment, current.target_segment_id)
        if source is None or target is None:
            raise ContactConflictError(
                f"Contact {contact_id!r} references a missing endpoint segment"
            )
        self._assert_segment_ownership(source, workspace_id)
        self._assert_current_generation(source)
        self._assert_current_generation(target)
        if confidence is not None:
            _validate_confidence(confidence)

        end = current.end_frame if end_frame is None else end_frame
        if end < current.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        et = current.end_time_ms if end_time_ms is None else end_time_ms
        if et < current.start_time_ms:
            raise ValueError("end_time_ms must be >= start_time_ms")
        new_end = current.end_frame if end_frame is None else end_frame
        new_et = current.end_time_ms if end_time_ms is None else end_time_ms
        # C1-F4: BOTH endpoint segments, BOTH frame+time dimensions.
        self._assert_range_within(
            source, current.start_frame, new_end, current.start_time_ms, new_et
        )
        self._assert_range_within(
            target, current.start_frame, new_end, current.start_time_ms, new_et
        )

        values: dict[str, object] = {"revision": revision + 1, "updated_at": utc_now()}
        if end_frame is not None:
            values["end_frame"] = end_frame
        if end_time_ms is not None:
            if end_time_ms < current.start_time_ms:
                raise ValueError("end_time_ms must be >= start_time_ms")
            values["end_time_ms"] = end_time_ms
        if confidence is not None:
            values["confidence"] = confidence
        if reasons is not None:
            values["reasons_json"] = canonical_json(reasons)
        if provenance is not None:
            _validate_provenance(provenance)
            values["provenance_json"] = canonical_json(provenance)

        stmt = (
            update(SceneGraphContact)
            .where(
                SceneGraphContact.id == contact_id,
                SceneGraphContact.workspace_id == workspace_id,
                SceneGraphContact.revision == revision,
            )
            .values(**values)
            .returning(SceneGraphContact)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.get(SceneGraphContact, contact_id)
            current_rev = latest.revision if latest is not None else None
            raise ContactConflictError(
                f"stale revision {revision}; current revision is {current_rev} "
                "(R1 F8 zero-mutation conflict)"
            ) from None
        return _map_contact(row)

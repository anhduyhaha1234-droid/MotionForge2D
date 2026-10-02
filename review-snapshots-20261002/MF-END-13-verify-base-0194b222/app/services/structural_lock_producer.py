"""Public StructuralLock producer (S09-LOCK-PRODUCER-B01, product gap B01).

The missing public caller for the durable ``StructuralLockRepository``:
``POST /api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock``
resolves the CURRENT server-side source/evidence graph of one video item
and freezes it as the next ``StructuralLockManifest`` version.

Producer contract (fail-closed, zero client authority):

- The request carries ONLY a documented policy selector, optional
  ``expected_*`` current-identity tokens and an idempotency key.  Every
  other field (workspace ids, filesystem paths, routes, manifest blobs,
  readiness flags) is rejected at the schema boundary (``extra="forbid"``)
  — the server never reads authority from the body.
- Source authority: the video item's ``source_artifact_id`` must be a
  READY video artifact with a lowercase sha256; the CURRENT generation is
  resolved through ``ObjectIntelligenceRepository.current_generation`` —
  the same backend state the extraction pipeline uses (never client hints).
- Evidence authority: the manifest segments are the CURRENT ACTIVE
  occurrence segments of the current generation (active record only, never
  history), EXCLUDING removal-only role kinds (``source_overlay`` — never
  replacement candidates).  A graph with zero eligible segments is a typed
  denial: an empty manifest is NEVER a success.
- Route authority (TARGET_PROFILE §4 P0-7): renderer routes are PERSISTED
  per occurrence segment in ``segment_render_route``; the producer reads
  the CURRENT decision (latest row) and refuses a non-executable route
  (no downgrade).  When no decision exists yet, the producer persists ONE
  deterministic server-derived default decision (``sprite_affine`` — the
  minimal FULL_APPLY-executable route, anchor {0.5,0.5}, the segment's
  own frame range) bound to the produced manifest, so equivalent replay
  creates no extra route rows.
- Readiness (every S09 executable-authority prerequisite, checked BEFORE
  any mutation): each eligible segment must carry persisted geometry
  evidence (prompt/segmentation points/boxes), an in-scope role, a role
  mapping (ReskinConfig for that role in this project) whose pack version
  is published/ready, and an in-workspace mask artifact when referenced.
- Source timing (R7 F03 correction): the exact frame count + CFR are
  PROVED from the CURRENT source artifact bytes through the existing
  verified facilities (``app.services.structural_lock_source_timing`` →
  ``video_import.probe_source`` + managed-root ``hash_file``).  Missing
  numerator/denominator/duration, an unproven or tampered artifact, a VFR
  source, or any persisted-vs-probe mismatch is a typed denial — no 30fps /
  denominator-1 / one-frame default exists anywhere on this path.
- Creation goes through ``StructuralLockRepository.create_manifest`` ONLY:
  idempotent replay converges on the same row (``created=False``), a
  materially different payload under the same key conflicts (409), and a
  new version archives the previous draft/active row (history is never
  rewritten).  No SQL seed, no auto-approval: pinning stays the existing
  ReskinConfig CAS pin API and approval stays the S09 reapproval path.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.persistence.models import (
    REMOVAL_ONLY_KINDS,
    Artifact,
    CharacterPackVersion,
    ObjectRole,
    OccurrenceSegment,
    Project,
    ReskinConfig,
    Scene,
    SceneGraphContact,
    SceneGraphOcclusion,
    SegmentRenderRoute,
    VideoItem,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceRepository,
    RoleNotFoundError,
)
from app.persistence.structural_evidence import (
    StructuralEvidenceRepository,
    canonical_json,
)
from app.persistence.structural_lock import (
    LockManifestRecord,
    StructuralLockConflictError,
    StructuralLockHashMismatchError,
    StructuralLockNotFoundError,
    StructuralLockOwnershipError,
    StructuralLockParamsError,
    StructuralLockRepository,
)
from app.services.s09_approval import FULL_APPLY_EXECUTABLE_ROUTES
from app.services.source_interaction_facts import ALGORITHM as SOURCE_FACTS_ALGORITHM
from app.services.structural_lock_source_timing import (
    SourceTimingError,
    SourceTimingProof,
    prove_source_timing,
)

__all__ = [
    "PRODUCER_DEFAULT_ROUTE",
    "PRODUCER_POLICY_VERSION",
    "ProduceOutcome",
    "ProducerConflictError",
    "ProducerError",
    "ProducerNotFoundError",
    "ProducerValidationError",
    "SourceGraph",
    "StructuralLockProducer",
    "SUPPORTED_POLICY_VERSIONS",
]

#: The frozen canonical threshold policy version this producer stamps on
#: every manifest it creates (TARGET_PROFILE §8 versioned policy).
PRODUCER_POLICY_VERSION = "structural-thresholds-v1"

#: Documented policy versions a request may SELECT; anything else is a
#: typed denial (fail-closed — a policy selector never names an unknown set).
SUPPORTED_POLICY_VERSIONS = frozenset({PRODUCER_POLICY_VERSION})

#: The deterministic server-derived default renderer route: the minimal
#: FULL_APPLY-executable route (``sprite_affine``).  Used ONLY when no
#: per-segment route decision is persisted yet; later corrections can
#: override it by writing a NEW history row (never mutating this one).
PRODUCER_DEFAULT_ROUTE = "sprite_affine"

CODE_UNKNOWN_PROJECT = "STRUCTURAL_LOCK_UNKNOWN_PROJECT"
CODE_UNKNOWN_VIDEO = "STRUCTURAL_LOCK_UNKNOWN_VIDEO"
CODE_STALE_EXPECTED_GENERATION = "STRUCTURAL_LOCK_STALE_EXPECTED_GENERATION"
CODE_STALE_EXPECTED_SOURCE_SHA = "STRUCTURAL_LOCK_STALE_EXPECTED_SOURCE_SHA256"
CODE_UNSUPPORTED_POLICY = "STRUCTURAL_LOCK_UNSUPPORTED_POLICY"
CODE_SOURCE_NOT_READY = "STRUCTURAL_LOCK_SOURCE_NOT_READY"
CODE_SOURCE_TAMPERED = "STRUCTURAL_LOCK_SOURCE_TAMPERED"
CODE_EVIDENCE_MISSING = "STRUCTURAL_LOCK_EVIDENCE_MISSING"
CODE_EVIDENCE_TAMPERED = "STRUCTURAL_LOCK_EVIDENCE_TAMPERED"
CODE_GEOMETRY_MISSING = "STRUCTURAL_LOCK_GEOMETRY_MISSING"
CODE_ROLE_MISSING = "STRUCTURAL_LOCK_ROLE_MISSING"
CODE_ROLE_MAPPING_MISSING = "STRUCTURAL_LOCK_ROLE_MAPPING_MISSING"
CODE_MASK_CROSS_SCOPE = "STRUCTURAL_LOCK_MASK_CROSS_SCOPE"
CODE_UNSUPPORTED_ROUTE = "STRUCTURAL_LOCK_UNSUPPORTED_ROUTE"
CODE_ROUTE_AMBIGUOUS = "STRUCTURAL_LOCK_ROUTE_AMBIGUOUS"
CODE_CONFLICT = "STRUCTURAL_LOCK_CONFLICT"
CODE_READ_ERROR = "STRUCTURAL_LOCK_READ_ERROR"
CODE_SOURCE_FACTS_SOURCE_MISMATCH = "STRUCTURAL_LOCK_SOURCE_FACTS_SOURCE_MISMATCH"
CODE_SOURCE_FACTS_OUT_OF_SCOPE = "STRUCTURAL_LOCK_SOURCE_FACTS_OUT_OF_SCOPE"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProducerError(Exception):
    """Base producer failure with a stable machine-readable code."""

    http_status = 500
    default_code = "STRUCTURAL_LOCK_PRODUCER_ERROR"

    def __init__(
        self,
        code: str | None = None,
        message: str = "",
        *,
        reasons: tuple[str, ...] = (),
    ) -> None:
        self.code = code or self.default_code
        self.reasons = tuple(reasons)
        super().__init__(message or self.code)

    def detail(self) -> dict[str, Any]:
        """Stable typed error detail (code + message + exact reasons)."""
        return {
            "code": self.code,
            "message": str(self),
            "reasons": list(self.reasons),
        }


class ProducerNotFoundError(ProducerError):
    """Unknown/cross-scope project or video (no existence leak)."""

    http_status = 404
    default_code = CODE_UNKNOWN_VIDEO


class ProducerConflictError(ProducerError):
    """Stale expected identity / idempotency or natural-key conflict."""

    http_status = 409
    default_code = CODE_CONFLICT


class ProducerValidationError(ProducerError):
    """Evidence outside the closed producer domain (fail-closed)."""

    http_status = 422
    default_code = CODE_EVIDENCE_MISSING


@dataclass(frozen=True)
class SourceGraph:
    """Frozen summary of the derived server-side source/evidence graph."""

    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    source_artifact_id: str
    source_sha256: str
    frame_count: int
    fps: float
    fps_num: int
    fps_den: int
    time_base: str
    shot_order: tuple[str, ...]
    segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProduceOutcome:
    """One producer call result: durable manifest + creation accounting."""

    record: LockManifestRecord
    created: bool
    route_decisions_created: int
    graph: SourceGraph


@dataclass(frozen=True)
class _SegmentPlan:
    """One selected occurrence segment + its current route decision."""

    segment: OccurrenceSegment
    role: ObjectRole
    route: str
    anchor_x: float
    anchor_y: float
    decision_id: str | None
    needs_default: bool
    provenance: dict[str, Any]
    z_payload: dict[str, Any]


def _sha256_hex(payload: Any) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    if not _SHA256_RE.match(digest):  # pragma: no cover - defensive
        raise ProducerValidationError(
            CODE_EVIDENCE_TAMPERED, "fingerprint computation produced an invalid digest"
        )
    return digest


def _reject_non_finite(value: Any, path: str) -> None:
    """Fail-closed finite walk over persisted evidence JSON."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ProducerValidationError(
                CODE_EVIDENCE_TAMPERED, f"non-finite number at {path}"
            )
        return
    if isinstance(value, int):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")
        return


def _parse_geometry(raw: str | None, path: str) -> dict[str, Any] | None:
    """Parse persisted segment geometry evidence (points/boxes shape).

    Missing/blank evidence returns ``None`` (geometry missing); stored
    JSON that is malformed, non-object or non-finite fails CLOSED — corrupt
    evidence is never silently defaulted.
    """
    if raw is None or not str(raw).strip():
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as err:
        raise ProducerValidationError(
            CODE_EVIDENCE_TAMPERED, f"{path} is not valid JSON: {err}"
        ) from err
    if not isinstance(value, dict):
        raise ProducerValidationError(
            CODE_EVIDENCE_TAMPERED, f"{path} must be a JSON object"
        )
    _reject_non_finite(value, path)
    return {
        "points": list(value.get("points", []) or []),
        "boxes": list(value.get("boxes", []) or []),
    }


class StructuralLockProducer:
    """Derives and freezes the CURRENT StructuralLockManifest for a video."""

    def __init__(
        self,
        session: Session,
        *,
        managed_root: str | Path | None = None,
    ) -> None:
        self._session = session
        self._lock = StructuralLockRepository(session)
        self._managed_root = managed_root

    # ── public surface ───────────────────────────────────────────────────

    def produce(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        *,
        expected_source_generation: str | None = None,
        expected_source_sha256: str | None = None,
        policy_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProduceOutcome:
        """Produce (or replay) the current structural lock for one video."""
        policy = self._resolve_policy(policy_version)
        if idempotency_key is not None and not idempotency_key.strip():
            raise ProducerValidationError(
                CODE_EVIDENCE_MISSING, "idempotency_key must not be blank"
            )
        try:
            project = self._session.get(Project, project_id)
            if project is None or str(project.workspace_id) != workspace_id:
                raise ProducerNotFoundError(
                    CODE_UNKNOWN_PROJECT,
                    f"project {project_id!r} not found in workspace",
                )
            video = self._session.get(VideoItem, video_item_id)
            if video is None or str(video.project_id) != project_id:
                raise ProducerNotFoundError(
                    CODE_UNKNOWN_VIDEO,
                    f"video item {video_item_id!r} not found in project",
                )

            generation = self._current_generation(workspace_id, video_item_id)
            source = self._source_artifact(workspace_id, video)

            if (
                expected_source_generation is not None
                and str(expected_source_generation) != generation
            ):
                raise ProducerConflictError(
                    CODE_STALE_EXPECTED_GENERATION,
                    "expected source generation "
                    f"{expected_source_generation!r} is stale; current is "
                    f"{generation!r}",
                )
            if (
                expected_source_sha256 is not None
                and str(expected_source_sha256) != str(source.sha256)
            ):
                raise ProducerConflictError(
                    CODE_STALE_EXPECTED_SOURCE_SHA,
                    "expected source sha256 does not match the current source "
                    "artifact checksum",
                )

            scenes = self._scenes(video_item_id)
            if not scenes:
                raise ProducerValidationError(
                    CODE_EVIDENCE_MISSING,
                    "no scene/shot evidence for this video item; the source "
                    "graph is not ready for a structural lock",
                )
            shot_order = [str(scene.id) for scene in scenes]

            segments = self._active_segments(
                workspace_id, project_id, video_item_id, generation
            )
            if not segments:
                raise ProducerValidationError(
                    CODE_EVIDENCE_MISSING,
                    "no current active occurrence segments for the current "
                    "generation; an empty manifest is not a success",
                )

            decisions = self._route_decisions_by_segment(
                workspace_id, video_item_id
            )
            plans = self._build_plans(
                workspace_id,
                project_id,
                video_item_id,
                generation,
                segments,
                decisions,
            )
            if not plans:
                raise ProducerValidationError(
                    CODE_EVIDENCE_MISSING,
                    "every current segment belongs to a removal-only role; "
                    "no replacement segment is available for a lock",
                )

            timing = self._timebase(video, source)
            frame_count = timing.frame_count
            fps = timing.fps
            time_base = timing.time_base
            manifest = {
                "frame_count": frame_count,
                "timebase": {
                    "fps": fps,
                    "time_base": time_base,
                    "start_time_ms": 0,
                },
                "shot_order": shot_order,
                "fingerprints": {
                    "z_order": _sha256_hex(self._z_order_payload(plans)),
                    "contacts": _sha256_hex(
                        self._contacts_payload(
                            workspace_id,
                            video_item_id,
                            {p.segment.id for p in plans},
                        )
                    ),
                },
                "segments": [
                    {
                        "occurrence_segment_id": plan.segment.id,
                        "route": plan.route,
                        "anchor": {"x": plan.anchor_x, "y": plan.anchor_y},
                        "start_frame": int(plan.segment.start_frame),
                        "end_frame": int(plan.segment.end_frame),
                        "provenance": plan.provenance,
                    }
                    for plan in plans
                ],
                "policy_version": policy,
            }
            if source_facts is not None:
                manifest["source_interaction_facts"] = source_facts
                manifest["fingerprints"]["source_interaction_facts"] = _sha256_hex(
                    source_facts
                )

            # Source interaction facts (MF-END-13): when a video HAS published
            # source facts they are frozen into the manifest and its source
            # identity must agree with the manifest's own source artifact —
            # sealed source facts can never be re-bound to another source
            # (a manifest without source facts keeps the exact legacy shape).
            source_facts = self._source_facts_payload(
                workspace_id, video_item_id, {plan.segment.id for plan in plans}
            )
            if source_facts is not None:
                self._validate_source_facts(source_facts, str(source.sha256))

            record, created = self._create_manifest(
                workspace_id,
                project_id,
                video_item_id,
                generation,
                manifest,
                idempotency_key=idempotency_key,
            )
            route_created = self._ensure_default_decisions(
                workspace_id, project_id, video_item_id, plans, record
            )
        except ProducerError:
            raise
        except SQLAlchemyError as err:
            raise ProducerValidationError(
                CODE_READ_ERROR, f"durable read failed: {err}"
            ) from err

        graph = SourceGraph(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            source_generation=generation,
            source_artifact_id=str(source.id),
            source_sha256=str(source.sha256),
            frame_count=frame_count,
            fps=fps,
            fps_num=timing.fps_num,
            fps_den=timing.fps_den,
            time_base=time_base,
            shot_order=tuple(shot_order),
            segment_ids=tuple(plan.segment.id for plan in plans),
        )
        return ProduceOutcome(
            record=record,
            created=created,
            route_decisions_created=route_created,
            graph=graph,
        )

    # ── source / evidence resolution ─────────────────────────────────────

    def _resolve_policy(self, policy_version: str | None) -> str:
        if policy_version is None:
            return PRODUCER_POLICY_VERSION
        if policy_version not in SUPPORTED_POLICY_VERSIONS:
            raise ProducerValidationError(
                CODE_UNSUPPORTED_POLICY,
                f"unsupported policy version {policy_version!r}; documented "
                f"versions are {sorted(SUPPORTED_POLICY_VERSIONS)}",
            )
        return policy_version

    def _current_generation(self, workspace_id: str, video_item_id: str) -> str:
        try:
            return ObjectIntelligenceRepository(
                self._session
            ).current_generation(workspace_id, video_item_id)
        except RoleNotFoundError as err:
            raise ProducerNotFoundError(
                CODE_UNKNOWN_VIDEO, f"video item {video_item_id!r} not found"
            ) from err

    def _source_artifact(self, workspace_id: str, video: VideoItem) -> Artifact:
        if video.source_artifact_id is None:
            raise ProducerValidationError(
                CODE_SOURCE_NOT_READY,
                "video item has no source artifact; the source generation is "
                "not ready for a structural lock",
            )
        source = self._session.get(Artifact, str(video.source_artifact_id))
        if source is None or str(source.workspace_id) != workspace_id:
            raise ProducerValidationError(
                CODE_SOURCE_NOT_READY,
                "source artifact missing or outside this workspace",
            )
        if source.kind != "video" or source.state != "ready":
            raise ProducerValidationError(
                CODE_SOURCE_NOT_READY,
                f"source artifact is not a ready video (kind={source.kind!r}, "
                f"state={source.state!r})",
            )
        sha = str(source.sha256 or "")
        if not _SHA256_RE.match(sha):
            raise ProducerValidationError(
                CODE_SOURCE_TAMPERED,
                "source artifact checksum is missing or not a lowercase "
                "sha256 hex digest",
            )
        return source

    def _scenes(self, video_item_id: str) -> list[Scene]:
        return list(
            self._session.scalars(
                select(Scene)
                .where(Scene.video_item_id == video_item_id)
                .order_by(Scene.position, Scene.id)
            ).all()
        )

    def _active_segments(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        generation: str,
    ) -> list[OccurrenceSegment]:
        rows = list(
            self._session.scalars(
                select(OccurrenceSegment)
                .where(
                    OccurrenceSegment.workspace_id == workspace_id,
                    OccurrenceSegment.video_item_id == video_item_id,
                    OccurrenceSegment.source_generation == generation,
                    OccurrenceSegment.superseded_by_id.is_(None),
                )
                .order_by(
                    OccurrenceSegment.start_frame,
                    OccurrenceSegment.z_order,
                    OccurrenceSegment.id,
                )
            ).all()
        )
        for row in rows:
            if str(row.project_id) != project_id:
                raise ProducerValidationError(
                    CODE_EVIDENCE_TAMPERED,
                    f"segment {row.id!r} carries a foreign project scope",
                )
        return rows

    def _route_decisions_by_segment(
        self, workspace_id: str, video_item_id: str
    ) -> dict[str, list[SegmentRenderRoute]]:
        rows = list(
            self._session.scalars(
                select(SegmentRenderRoute)
                .where(
                    SegmentRenderRoute.workspace_id == workspace_id,
                    SegmentRenderRoute.video_item_id == video_item_id,
                )
                .order_by(
                    SegmentRenderRoute.created_at.desc(),
                    SegmentRenderRoute.id.desc(),
                )
            ).all()
        )
        grouped: dict[str, list[SegmentRenderRoute]] = {}
        for row in rows:
            grouped.setdefault(str(row.occurrence_segment_id), []).append(row)
        return grouped

    # ── per-segment plan build (fail-closed) ─────────────────────────────

    def _build_plans(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        generation: str,
        segments: list[OccurrenceSegment],
        decisions: dict[str, list[SegmentRenderRoute]],
    ) -> list[_SegmentPlan]:
        role_reasons: list[str] = []
        tampered_reasons: list[str] = []
        geometry_reasons: list[str] = []
        mask_reasons: list[str] = []
        mapping_reasons: list[str] = []
        route_reasons: list[str] = []
        ambiguity_reasons: list[str] = []

        plans: list[_SegmentPlan] = []
        for segment in segments:
            role = (
                self._session.get(ObjectRole, str(segment.role_id))
                if segment.role_id
                else None
            )
            if (
                role is None
                or str(role.workspace_id) != workspace_id
                or str(role.project_id) != project_id
                or str(role.video_item_id) != video_item_id
            ):
                role_reasons.append(
                    f"segment {segment.id}: role missing/ambiguous "
                    "(no persisted object role in scope)"
                )
                continue
            if str(role.kind) in REMOVAL_ONLY_KINDS:
                # Removal-only roles are never replacement candidates and
                # are not lock segments (their authority is removal, not
                # reproduction) — they must not be presented as replaceable.
                continue

            # Persisted geometry evidence (points/boxes) — the ONLY geometry
            # authority; malformed evidence fails closed.
            try:
                segmentation = _parse_geometry(
                    segment.segmentation_json,
                    f"segment {segment.id}.segmentation_json",
                )
                prompt = _parse_geometry(
                    segment.prompt_json, f"segment {segment.id}.prompt_json"
                )
            except ProducerValidationError:
                tampered_reasons.append(
                    f"segment {segment.id}: affected geometry evidence is "
                    "corrupt or non-finite"
                )
                continue
            has_geometry = bool(
                (
                    segmentation is not None
                    and (segmentation["points"] or segmentation["boxes"])
                )
                or (prompt is not None and (prompt["points"] or prompt["boxes"]))
            )
            if not has_geometry:
                geometry_reasons.append(
                    f"segment {segment.id}: missing affected geometry "
                    "(segmentation/prompt evidence)"
                )
                continue

            if segment.mask_artifact_id is not None:
                mask = self._session.get(Artifact, str(segment.mask_artifact_id))
                if mask is None or str(mask.workspace_id) != workspace_id:
                    mask_reasons.append(
                        f"segment {segment.id}: mask artifact missing or "
                        "outside this workspace (cross-scope evidence)"
                    )
                    continue

            # Role mapping + published/ready pack (mirrors the S09
            # executable-authority prerequisite — no silent downgrade).
            config = self._session.scalar(
                select(ReskinConfig).where(
                    ReskinConfig.workspace_id == workspace_id,
                    ReskinConfig.project_id == project_id,
                    ReskinConfig.object_role_id == role.id,
                )
            )
            if config is None:
                mapping_reasons.append(
                    f"segment {segment.id}: role {role.id} has no approved "
                    "reskin config mapping"
                )
                continue
            pack = self._session.get(
                CharacterPackVersion, str(config.pack_version_id)
            )
            if pack is None or str(pack.workspace_id) != workspace_id:
                mapping_reasons.append(
                    f"segment {segment.id}: role mapping pack version missing"
                )
                continue
            if str(pack.status) not in ("published", "ready"):
                mapping_reasons.append(
                    f"segment {segment.id}: pack version {pack.id} status "
                    f"{pack.status!r} not published/ready for full apply"
                )
                continue

            rows = decisions.get(str(segment.id)) or []
            decision_id: str | None = None
            needs_default = False
            if rows:
                newest = rows[0]
                same_instant = [
                    row for row in rows if row.created_at == newest.created_at
                ]
                if len({str(row.route) for row in same_instant}) > 1:
                    ambiguity_reasons.append(
                        f"segment {segment.id}: ambiguous concurrent route "
                        "decisions (same timestamp, different routes)"
                    )
                    continue
                if str(newest.route) not in FULL_APPLY_EXECUTABLE_ROUTES:
                    route_reasons.append(
                        f"segment {segment.id}: route {newest.route!r} not "
                        "executable by licensed production adapters — no "
                        "downgrade"
                    )
                    continue
                route = str(newest.route)
                anchor_x = float(newest.anchor_x)
                anchor_y = float(newest.anchor_y)
                decision_id = str(newest.id)
            else:
                route = PRODUCER_DEFAULT_ROUTE
                anchor_x = 0.5
                anchor_y = 0.5
                needs_default = True

            plans.append(
                _SegmentPlan(
                    segment=segment,
                    role=role,
                    route=route,
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                    decision_id=decision_id,
                    needs_default=needs_default,
                    provenance={
                        # STABLE across equivalent replay (never encodes
                        # whether the route decision existed at read time).
                        "segment_logical_id": str(segment.logical_id),
                        "lineage_version": int(segment.lineage_version),
                        "z_order": int(segment.z_order),
                        "visibility": str(segment.visibility),
                        "role_id": str(role.id),
                        "source_generation": generation,
                    },
                    z_payload={
                        "occurrence_segment_id": str(segment.id),
                        "logical_id": str(segment.logical_id),
                        "z_order": int(segment.z_order),
                        "visibility": str(segment.visibility),
                        "start_frame": int(segment.start_frame),
                        "end_frame": int(segment.end_frame),
                    },
                )
            )

        for reasons, code, message in (
            (tampered_reasons, CODE_EVIDENCE_TAMPERED, "corrupt evidence"),
            (role_reasons, CODE_ROLE_MISSING, "role mapping missing"),
            (
                geometry_reasons,
                CODE_GEOMETRY_MISSING,
                "affected geometry missing",
            ),
            (mask_reasons, CODE_MASK_CROSS_SCOPE, "mask evidence cross-scope"),
            (
                mapping_reasons,
                CODE_ROLE_MAPPING_MISSING,
                "role mapping / pack not ready",
            ),
            (ambiguity_reasons, CODE_ROUTE_AMBIGUOUS, "ambiguous route decision"),
            (
                route_reasons,
                CODE_UNSUPPORTED_ROUTE,
                "unsupported route decision",
            ),
        ):
            if reasons:
                raise ProducerValidationError(
                    code, message, reasons=tuple(reasons)
                )
        return plans

    # ── fingerprint payloads (deterministic, evidence-backed) ────────────

    def _z_order_payload(self, plans: list[_SegmentPlan]) -> dict[str, Any]:
        segment_ids = {plan.segment.id for plan in plans}
        occlusions = self._occlusions(
            str(plans[0].segment.workspace_id),
            str(plans[0].segment.video_item_id),
            segment_ids,
        )
        return {
            "segments": [dict(plan.z_payload) for plan in plans],
            "occlusions": occlusions,
        }

    def _occlusions(
        self,
        workspace_id: str,
        video_item_id: str,
        segment_ids: set[str],
    ) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(SceneGraphOcclusion)
                .where(
                    SceneGraphOcclusion.workspace_id == workspace_id,
                    SceneGraphOcclusion.video_item_id == video_item_id,
                )
                .order_by(
                    SceneGraphOcclusion.start_frame,
                    SceneGraphOcclusion.id,
                )
            ).all()
        )
        return [
            {
                "occluder_segment_id": str(row.occluder_segment_id),
                "occludee_segment_id": str(row.occludee_segment_id),
                "start_frame": int(row.start_frame),
                "end_frame": int(row.end_frame),
            }
            for row in rows
            if str(row.occluder_segment_id) in segment_ids
            and str(row.occludee_segment_id) in segment_ids
        ]

    def _contacts_payload(
        self,
        workspace_id: str,
        video_item_id: str,
        segment_ids: set[str],
    ) -> dict[str, Any]:
        rows = list(
            self._session.scalars(
                select(SceneGraphContact)
                .where(
                    SceneGraphContact.workspace_id == workspace_id,
                    SceneGraphContact.video_item_id == video_item_id,
                )
                .order_by(
                    SceneGraphContact.start_frame,
                    SceneGraphContact.id,
                )
            ).all()
        )
        return {
            "contacts": [
                {
                    "source_segment_id": str(row.source_segment_id),
                    "target_segment_id": str(row.target_segment_id),
                    "contact_kind": str(row.contact_kind),
                    "start_frame": int(row.start_frame),
                    "end_frame": int(row.end_frame),
                }
                for row in rows
                if str(row.source_segment_id) in segment_ids
                and str(row.target_segment_id) in segment_ids
            ]
        }

    # ── source interaction facts freeze (MF-END-13) ──────────────────────

    def _source_facts_payload(
        self,
        workspace_id: str,
        video_item_id: str,
        segment_ids: set[str],
    ) -> dict[str, Any] | None:
        """The published source facts for this video, or ``None`` when none.

        Reads the durable rows the source-interaction-facts algorithm wrote
        (never a client payload) and keeps only rows whose endpoints are part
        of the manifest segment set.  ``None`` (no rows at all) leaves the
        legacy manifest shape untouched.
        """
        rows = StructuralEvidenceRepository(self._session).list_source_algorithm_facts(
            workspace_id, video_item_id, algorithm=SOURCE_FACTS_ALGORITHM
        )
        contacts = [
            row for row in rows["contacts"] if str(row["source_segment_id"]) in segment_ids
            and str(row["target_segment_id"]) in segment_ids
        ]
        occlusions = [
            row
            for row in rows["occlusions"]
            if str(row["occluder_segment_id"]) in segment_ids
            and str(row["occludee_segment_id"]) in segment_ids
        ]
        motions = [
            row for row in rows["motions"] if str(row["occurrence_segment_id"]) in segment_ids
        ]
        if not contacts and not occlusions and not motions:
            return None
        provenance = [row.get("provenance") or {} for row in (*contacts, *occlusions, *motions)]
        source_shas = sorted(
            {str(item.get("source_sha256")) for item in provenance if item.get("source_sha256")}
        )
        return {
            "algorithm": SOURCE_FACTS_ALGORITHM,
            "source_sha256": source_shas,
            "contacts": contacts,
            "occlusions": occlusions,
            "motions": motions,
        }

    def _validate_source_facts(
        self, source_facts: dict[str, Any], manifest_source_sha: str
    ) -> None:
        """Fail closed when published facts contradict the frozen source."""
        shas = [str(item) for item in source_facts.get("source_sha256") or []]
        if not shas or len(shas) > 1 or shas[0] != manifest_source_sha:
            raise ProducerValidationError(
                CODE_SOURCE_FACTS_SOURCE_MISMATCH,
                "published source interaction facts are bound to "
                f"{shas!r}, not to the manifest source {manifest_source_sha!r}; "
                "a sealed source fact is never re-bound to another source",
                reasons=tuple(
                    f"source_interaction_facts.source_sha256={value}" for value in shas
                ),
            )

    # ── timebase / manifest creation ─────────────────────────────────────

    def _timebase(self, video: VideoItem, source: Artifact) -> SourceTimingProof:
        """Exact source timing proof (R7 F03) — never defaulted, never
        rounded: only the verified probe's exact ``nb_frames`` + CFR-equal
        rationals, cross-checked against every persisted fact, can pass.

        Missing numerator/denominator/duration, an unproven/tampered source
        artifact, a VFR source or any persisted-vs-probe mismatch is a
        typed denial (zero-durable-mutation, fail closed)."""
        try:
            return prove_source_timing(
                managed_root=self._managed_root,
                video=video,
                source_artifact=source,
            )
        except SourceTimingError as err:
            raise ProducerValidationError(
                err.code, str(err), reasons=err.reasons
            ) from err

    def _create_manifest(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        generation: str,
        manifest: dict[str, Any],
        *,
        idempotency_key: str | None,
    ) -> tuple[LockManifestRecord, bool]:
        try:
            return self._lock.create_manifest(
                workspace_id,
                project_id,
                video_item_id,
                generation,
                manifest,
                expected_hash=None,
                idempotency_key=idempotency_key,
                activate=True,
            )
        except StructuralLockConflictError as err:
            raise ProducerConflictError(CODE_CONFLICT, str(err)) from err
        except StructuralLockHashMismatchError as err:
            raise ProducerValidationError(
                CODE_EVIDENCE_TAMPERED, str(err)
            ) from err
        except StructuralLockParamsError as err:
            raise ProducerValidationError(
                CODE_EVIDENCE_TAMPERED, str(err)
            ) from err
        except StructuralLockNotFoundError as err:
            raise ProducerNotFoundError(CODE_UNKNOWN_VIDEO, str(err)) from err
        except StructuralLockOwnershipError as err:
            raise ProducerNotFoundError(CODE_UNKNOWN_VIDEO, str(err)) from err

    def _ensure_default_decisions(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        plans: list[_SegmentPlan],
        record: LockManifestRecord,
    ) -> int:
        """Persist one deterministic default route decision per missing segment.

        The decision is bound to the produced manifest so the existing
        config-pinned evidence surface can attribute it.  A concurrent
        producer's equivalent decision is reused ONLY when it matches the
        frozen default exactly; anything else is a typed conflict (the
        manifest already frozen must never disagree with the route
        authority).
        """
        created_count = 0
        for plan in plans:
            if not plan.needs_default:
                continue
            segment = plan.segment
            key = (
                f"structural-lock-produce:{video_item_id}:"
                f"{plan.provenance['source_generation']}:{segment.id}"
            )
            expected = (
                PRODUCER_DEFAULT_ROUTE,
                0.5,
                0.5,
                int(segment.start_frame),
                int(segment.end_frame),
            )
            try:
                route_record, created = self._lock.record_render_route(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    occurrence_segment_id=str(segment.id),
                    route=PRODUCER_DEFAULT_ROUTE,
                    anchor_x=0.5,
                    anchor_y=0.5,
                    start_frame=int(segment.start_frame),
                    end_frame=int(segment.end_frame),
                    provenance={
                        "origin": "producer-default",
                        "policy_version": record.policy_version,
                        "segment_logical_id": str(segment.logical_id),
                        "manifest_id": record.id,
                    },
                    reasons=[
                        "producer default route: minimal full-apply-executable "
                        "route (frozen producer policy)"
                    ],
                    algorithm="structural-lock-producer",
                    algorithm_version="1",
                    confidence=1.0,
                    confidence_source="derived",
                    structural_lock_manifest_id=record.id,
                    idempotency_key=key,
                )
            except StructuralLockConflictError as err:
                existing = self._latest_route_decision(workspace_id, str(segment.id))
                if existing is None or (
                    str(existing.route),
                    float(existing.anchor_x),
                    float(existing.anchor_y),
                    int(existing.start_frame),
                    int(existing.end_frame),
                ) != expected:
                    raise ProducerConflictError(
                        CODE_CONFLICT,
                        "route decision for segment "
                        f"{segment.id} conflicts with the frozen manifest",
                    ) from err
                continue
            except (StructuralLockOwnershipError, StructuralLockParamsError) as err:
                raise ProducerValidationError(
                    CODE_EVIDENCE_TAMPERED, str(err)
                ) from err
            actual = (
                str(route_record.route),
                float(route_record.anchor_x),
                float(route_record.anchor_y),
                int(route_record.start_frame),
                int(route_record.end_frame),
            )
            if actual != expected:
                raise ProducerConflictError(
                    CODE_CONFLICT,
                    "existing route decision for segment "
                    f"{segment.id} disagrees with the frozen manifest",
                )
            if created:
                created_count += 1
        return created_count

    def _latest_route_decision(
        self, workspace_id: str, occurrence_segment_id: str
    ) -> SegmentRenderRoute | None:
        return self._session.scalar(
            select(SegmentRenderRoute)
            .where(
                SegmentRenderRoute.workspace_id == workspace_id,
                SegmentRenderRoute.occurrence_segment_id == occurrence_segment_id,
            )
            .order_by(
                SegmentRenderRoute.created_at.desc(),
                SegmentRenderRoute.id.desc(),
            )
            .limit(1)
        )

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session, selectinload

from app.persistence.models import (
    OBJECT_KINDS,
    Artifact,
    Job,
    ObjectOccurrence,
    ObjectRole,
    ObjectRoleArtifact,
    Project,
    Scene,
    VideoItem,
    utc_now,
)

#: Canonical durable job type produced by T02 candidate extraction
#: (mirrors ``app.services.object_extraction.JOB_TYPE_DISCOVER_OBJECTS``).
#: Kept as a module constant here so the persistence repository can resolve
#: the backend-authoritative current generation without a layering inversion
#: (services must never be imported by the persistence layer).
JOB_TYPE_DISCOVER_OBJECTS = "DISCOVER_OBJECTS"

#: SQLite default max parameters is 999; keep chunk comfortably below.
_SQLITE_MAX_PARAMS = 900
#: Fixed bind-parameter budget for job bulk query: job_type (1) + state (1) + owner_id IN (chunk)
#: -> chunk must leave room for 2 extra binds so TOTAL <= _SQLITE_MAX_PARAMS.
_SQLITE_JOB_CHUNK = _SQLITE_MAX_PARAMS - 2
#: Declared fixed budget for batch generation helpers (documentation for instrumentation)
_BATCH_PARAM_BUDGET = _SQLITE_MAX_PARAMS


class ObjectIntelligenceError(Exception):
    """Base error for durable object intelligence."""


class RoleNotFoundError(ObjectIntelligenceError):
    """Role does not exist in the requested workspace."""


class RoleConflictError(ObjectIntelligenceError):
    """Role update conflicts with current durable state."""


class OccurrenceNotFoundError(ObjectIntelligenceError):
    """Occurrence does not exist in the requested workspace."""


class OccurrenceConflictError(ObjectIntelligenceError):
    """Occurrence update conflicts with current durable state."""


class OwnershipMismatchError(ObjectIntelligenceError):
    """An ownership chain did not validate."""


@dataclass(frozen=True)
class OccurrenceRecord:
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    role_id: str
    scene_id: str
    frame_index: int
    time_ms: int
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    confidence: float
    confidence_source: str
    algorithm: str | None
    algorithm_version: str | None
    reasons: list[str]
    review_state: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RoleMediaRecord:
    """The NEWEST VALID media association of a role (S08-T05-C1, finding D).

    Resolved from ``object_role_artifact`` rows where
    ``superseded_by_id IS NULL`` — i.e. exactly the current display-level
    media.  Superseded (older) associations remain in the table for audit
    but are never returned here.  Keyed by stable role id (never display
    name), so renames and duplicate names cannot re-map media.
    """

    association_id: str
    artifact_id: str
    purpose: str
    relative_path: str
    sha256: str
    size_bytes: int
    width: int | None
    height: int | None
    mime_type: str | None
    source_generation: str
    source_job_id: str


@dataclass(frozen=True)
class RoleRecord:
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    name: str
    kind: str
    status: str
    supersedes_role_id: str | None
    legacy_object_id: str | None
    legacy_scene_id: int | None
    description: str | None
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    occurrences: list[OccurrenceRecord]
    media: list[RoleMediaRecord] = field(default_factory=list)
    # S08-T05-C1: True when the role has ANY durable media association (active
    # or superseded).  Display then resolves ONLY the newest valid media — the
    # gallery must NOT fall back to name-matched legacy outputs for a role
    # whose media is association-managed.
    has_media_associations: bool = False


@dataclass(frozen=True)
class LegacyMappingItem:
    legacy_object_id: str
    legacy_scene_id: int
    legacy_name: str
    legacy_kind: str
    suggested_name: str
    ephemeral_role_id: str
    occurrence_evidence: list[dict[str, object]]
    # S08-A01 legacy provenance: the RAW source kind string and the
    # normalization reason when the raw value is not one of the seven
    # canonical kinds (e.g. ``unknown-kind-normalized-to-other``).  Records
    # WHY an historical unknown mapped to ``other`` — never silently lost.
    source_kind: str = ""
    kind_normalization_reason: str | None = None


@dataclass(frozen=True)
class LegacyObjectMapping:
    project_id: str
    source: Literal["legacy-project-json"]
    mapped_objects: list[LegacyMappingItem]
    note: str


def _reasons(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _map_occurrence(row: ObjectOccurrence) -> OccurrenceRecord:
    return OccurrenceRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        role_id=row.role_id,
        scene_id=row.scene_id,
        frame_index=row.frame_index,
        time_ms=row.time_ms,
        bbox_x=row.bbox_x,
        bbox_y=row.bbox_y,
        bbox_w=row.bbox_w,
        bbox_h=row.bbox_h,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        algorithm=row.algorithm,
        algorithm_version=row.algorithm_version,
        reasons=_reasons(row.reasons_json),
        review_state=row.review_state,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _map_role(
    row: ObjectRole,
    media: Iterable[RoleMediaRecord] = (),
    *,
    has_media_associations: bool = False,
) -> RoleRecord:
    return RoleRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        source_generation=row.source_generation,
        name=row.name,
        kind=row.kind,
        status=row.status,
        supersedes_role_id=row.supersedes_role_id,
        legacy_object_id=row.legacy_object_id,
        legacy_scene_id=row.legacy_scene_id,
        description=row.description,
        idempotency_key=row.idempotency_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        occurrences=[_map_occurrence(item) for item in row.occurrences],
        media=list(media),
        has_media_associations=has_media_associations,
    )


def _resolve_role_media(session: Session, role_id: str) -> list[RoleMediaRecord]:
    """The newest valid media of one role (finding D2).

    ``superseded_by_id IS NULL`` is exactly the current display media; every
    older association for the role+purpose points at its replacement via the
    self-FK and remains auditable in the table.
    """
    rows = session.execute(
        select(ObjectRoleArtifact, Artifact)
        .join(Artifact, Artifact.id == ObjectRoleArtifact.artifact_id)
        .where(
            ObjectRoleArtifact.role_id == role_id,
            ObjectRoleArtifact.superseded_by_id.is_(None),
            exists(
                select(ObjectOccurrence.id).where(
                    ObjectOccurrence.role_id == ObjectRoleArtifact.role_id
                )
            ),
        )
        .order_by(
            ObjectRoleArtifact.purpose,
            ObjectRoleArtifact.created_at,
            ObjectRoleArtifact.id,
        )
    ).all()
    return [
        RoleMediaRecord(
            association_id=assoc.id,
            artifact_id=assoc.artifact_id,
            purpose=assoc.purpose,
            relative_path=artifact.relative_path,
            sha256=artifact.sha256 or "",
            size_bytes=artifact.size_bytes or 0,
            width=artifact.width,
            height=artifact.height,
            mime_type=artifact.mime_type,
            source_generation=assoc.source_generation,
            source_job_id=assoc.source_job_id,
        )
        for assoc, artifact in rows
    ]



def _chunked(seq: list[str], size: int) -> Iterable[list[str]]:
    """Yield fixed-size chunks (parameterized, no string interpolation)."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _resolve_generation_from_jobs(
    current_sha: str | None,
    jobs: list[Job],
) -> str:
    """Single semantic source for generation resolution (max-gen/latest-SHA).

    Shared by scalar and batch paths — one truth, no duplication.
    Jobs must be ordered newest-first (created_at desc, id desc) or at
    least contain all completed DISCOVER_OBJECTS jobs for the video.
    """
    max_gen = 0
    latest_for_sha: str | None = None
    for row in jobs:
        gen = str(row.input_generation or "")
        if gen.isdigit():
            try:
                max_gen = max(max_gen, int(gen))
            except ValueError:
                continue
        manifest_sha = ""
        try:
            parsed = json.loads(row.input_manifest_json or "{}")
            if isinstance(parsed, dict):
                manifest_sha = str(parsed.get("source_sha256") or "")
        except (TypeError, json.JSONDecodeError):
            manifest_sha = ""
        if current_sha is not None and manifest_sha == current_sha and latest_for_sha is None:
            latest_for_sha = gen if gen else None
    if latest_for_sha is not None:
        return latest_for_sha
    return str(max_gen + 1) if max_gen else "1"

class ObjectIntelligenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _assert_role_ownership(
        self, workspace_id: str, project_id: str, video_item_id: str
    ) -> None:
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise OwnershipMismatchError("project ownership mismatch")
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise OwnershipMismatchError("video ownership mismatch")

    def _assert_occurrence_ownership(
        self, workspace_id: str, role_id: str, scene_id: str
    ) -> tuple[ObjectRole, Scene]:
        role = self._session.get(ObjectRole, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise OwnershipMismatchError("role ownership mismatch")
        scene = self._session.get(Scene, scene_id)
        if scene is None or scene.video_item_id != role.video_item_id:
            raise OwnershipMismatchError("scene ownership mismatch")
        return role, scene

    # ── Backend-authoritative current source generation (T01-C2) ───────────
    #
    # Mirrors the T02-C2 source authority semantics
    # (``app/services/object_extraction.py`` ``_authoritative_source`` /
    # ``_authoritative_generation``): the CURRENT generation is resolved from
    # durable backend state only — the video item's ``source_artifact_id``
    # (artifact SHA-256) plus the newest COMPLETED DISCOVER_OBJECTS job whose
    # manifest source SHA equals the current source.  Never derived from
    # client hints, display names or role counts.

    def current_generation(self, workspace_id: str, video_item_id: str) -> str:
        """Backend-authoritative CURRENT generation for one video item.

        Raises ``RoleNotFoundError`` when the video item does not exist in the
        workspace (fail closed).  A video item with no completed extraction
        job resolves to the next generation after the highest completed one
        (``"1"`` when none exists) — the same rule T02-C2 applies.
        """
        video = self._session.get(VideoItem, video_item_id)
        if video is None:
            raise RoleNotFoundError(f"Video item {video_item_id!r} not found")
        project = self._session.get(Project, video.project_id)
        if project is None or project.workspace_id != workspace_id:
            raise RoleNotFoundError(f"Video item {video_item_id!r} not found")
        current_sha: str | None = None
        if video.source_artifact_id is not None:
            source = self._session.get(Artifact, video.source_artifact_id)
            if source is not None and source.sha256:
                current_sha = str(source.sha256)
        return self._current_generation_for_source(
            video_item_id, current_sha
        )

    def _current_generation_for_source(
        self, video_item_id: str, current_sha: str | None
    ) -> str:
        """Resolve the current generation for (video, source sha) from jobs.

        Single source of truth via _resolve_generation_from_jobs.
        """
        rows = self._session.scalars(
            select(Job)
            .where(
                Job.job_type == JOB_TYPE_DISCOVER_OBJECTS,
                Job.owner_id == video_item_id,
                Job.state == "completed",
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
        ).all()
        return _resolve_generation_from_jobs(current_sha, list(rows))

    def _current_generation_map(
        self, workspace_id: str, video_item_ids: set[str]
    ) -> dict[str, str]:
        """Batch current-generation resolution for many video items.

        Delegates to authoritative batch_current_generation (bounded,
        parameterized, single semantic source).
        """
        if not video_item_ids:
            return {}
        return self.batch_current_generation(workspace_id, video_item_ids)

    def batch_current_generation(
        self, workspace_id: str, video_item_ids: Iterable[str]
    ) -> dict[str, str]:
        """Authoritative BATCH current-generation API (single semantic source).

        Fixed-size parameterized chunking (<= _SQLITE_MAX_PARAMS TOTAL bind
        params per statement, covering ALL predicates: workspace/project/job
        filters + IN-list; job bulk uses _SQLITE_JOB_CHUNK = 900-2 so TOTAL
        <=900). SQLAlchemy bindparams, never string interpolation. Fail-closed
        on unknown/corrupt ownership (raises RoleNotFoundError, never
        swallowed). Declared budget: every statement <= _SQLITE_MAX_PARAMS
        (with job query TOTAL = len(chunk)+2 <=900); instrumentation must
        count ACTUAL total params per statement.
        """
        vids = list(dict.fromkeys([str(v) for v in video_item_ids if v is not None]))
        if not vids:
            return {}
        # Bulk fetch VideoItems chunked
        video_map: dict[str, VideoItem] = {}
        project_ids: set[str] = set()
        artifact_ids: list[str] = []
        for chunk in _chunked(vids, _SQLITE_MAX_PARAMS):
            video_rows = self._session.scalars(
                select(VideoItem).where(VideoItem.id.in_(chunk))
            ).all()
            for v in video_rows:
                video_map[v.id] = v
                if v.project_id:
                    project_ids.add(v.project_id)
                if v.source_artifact_id:
                    artifact_ids.append(v.source_artifact_id)
            found = {v.id for v in video_rows}
            missing = set(chunk) - found
            if missing:
                raise RoleNotFoundError(f"Video item {next(iter(missing))!r} not found")
        # Workspace ownership check (chunked Project fetch)
        project_map: dict[str, str] = {}
        if project_ids:
            for chunk in _chunked(list(project_ids), _SQLITE_MAX_PARAMS):
                proj_rows = self._session.scalars(
                    select(Project).where(Project.id.in_(chunk))
                ).all()
                for pr in proj_rows:
                    project_map[pr.id] = pr.workspace_id
        for vid, video in video_map.items():
            ws = project_map.get(video.project_id)
            if ws is None or ws != workspace_id:
                raise RoleNotFoundError(f"Video item {vid!r} not found")
        # Artifact SHA map (chunked)
        artifact_map: dict[str, str] = {}
        if artifact_ids:
            uniq = list(dict.fromkeys(artifact_ids))
            for chunk in _chunked(uniq, _SQLITE_MAX_PARAMS):
                art_rows = self._session.scalars(
                    select(Artifact).where(Artifact.id.in_(chunk))
                ).all()
                for a in art_rows:
                    if a.sha256:
                        artifact_map[a.id] = str(a.sha256)
        # Jobs bulk chunked
        from collections import defaultdict

        jobs_by_video: dict[str, list[Job]] = defaultdict(list)
        for chunk in _chunked(vids, _SQLITE_JOB_CHUNK):
            job_rows = self._session.scalars(
                select(Job)
                .where(
                    Job.job_type == JOB_TYPE_DISCOVER_OBJECTS,
                    Job.owner_id.in_(chunk),
                    Job.state == "completed",
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
            ).all()
            for j in job_rows:
                jobs_by_video[j.owner_id].append(j)
        # Ensure per-video ordering is deterministic newest-first
        for vid in list(jobs_by_video.keys()):
            jobs_by_video[vid].sort(
                key=lambda j: (j.created_at.isoformat() if j.created_at is not None else "", j.id),
                reverse=True,
            )
        result: dict[str, str] = {}
        for vid in vids:
            video = video_map[vid]
            sha = artifact_map.get(video.source_artifact_id) if video.source_artifact_id else None
            jobs = jobs_by_video.get(vid, [])
            result[vid] = _resolve_generation_from_jobs(sha, jobs)
        return result

    def _assert_role_current(
        self, workspace_id: str, role: ObjectRole
    ) -> None:
        """Fail-closed guard: only current-generation roles are mutable.

        Apply/dismiss/merge/correction-style mutations on a role that belongs
        to a STALE source generation raise ``RoleConflictError`` with ZERO
        mutation.  Historical inspection is a separate read-only contract;
        historical roles are never silently mutated.
        """
        if role.source_generation != self.current_generation(
            workspace_id, role.video_item_id
        ):
            raise RoleConflictError(
                f"role {role.id!r} belongs to stale source generation "
                f"{role.source_generation!r}; only current-generation roles "
                "are mutable (current generation is "
                f"{self.current_generation(workspace_id, role.video_item_id)!r})"
            )

    def create_role(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_generation: str,
        name: str,
        *,
        kind: str = "character",
        status: str = "suggested",
        description: str | None = None,
        legacy_object_id: str | None = None,
        legacy_scene_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[RoleRecord, bool]:
        if kind not in OBJECT_KINDS:
            raise ValueError(f"unknown role kind {kind!r}")
        if not name.strip():
            raise ValueError("name must not be empty")
        if not source_generation.strip():
            raise ValueError("source_generation must not be empty")
        self._assert_role_ownership(workspace_id, project_id, video_item_id)
        if idempotency_key:
            existing = self._session.scalar(
                select(ObjectRole).where(
                    ObjectRole.workspace_id == workspace_id,
                    ObjectRole.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_equivalent_role_request(
                    existing,
                    project_id,
                    video_item_id,
                    source_generation,
                    name,
                    kind,
                    status,
                    description,
                    legacy_object_id,
                    legacy_scene_id,
                )
                return _map_role(existing), False
        row = ObjectRole(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            source_generation=source_generation,
            name=name,
            kind=kind,
            status=status,
            description=description,
            legacy_object_id=legacy_object_id,
            legacy_scene_id=legacy_scene_id,
            idempotency_key=idempotency_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            if idempotency_key:
                existing = self._session.scalar(
                    select(ObjectRole).where(
                        ObjectRole.workspace_id == workspace_id,
                        ObjectRole.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._assert_equivalent_role_request(
                        existing,
                        project_id,
                        video_item_id,
                        source_generation,
                        name,
                        kind,
                        status,
                        description,
                        legacy_object_id,
                        legacy_scene_id,
                    )
                    return _map_role(existing), False
            raise
        return _map_role(row), True

    @staticmethod
    def _assert_equivalent_role_request(
        existing: ObjectRole,
        project_id: str,
        video_item_id: str,
        source_generation: str,
        name: str,
        kind: str,
        status: str,
        description: str | None,
        legacy_object_id: str | None,
        legacy_scene_id: int | None,
    ) -> None:
        """Idempotency replay is allowed ONLY for an equivalent canonical request.

        A reused idempotency key bound to a materially different payload is a
        conflict — it must never be returned as a successful replay of another
        resource.
        """
        if (
            existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.source_generation != source_generation
            or existing.name != name
            or existing.kind != kind
            or existing.status != status
            or existing.description != description
            or existing.legacy_object_id != legacy_object_id
            or existing.legacy_scene_id != legacy_scene_id
        ):
            raise RoleConflictError(
                f"idempotency key {existing.idempotency_key!r} is already bound "
                "to a different role request"
            )

    def _role_row(self, workspace_id: str, role_id: str) -> ObjectRole:
        row = self._session.scalar(
            select(ObjectRole)
            .options(selectinload(ObjectRole.occurrences))
            .where(ObjectRole.id == role_id, ObjectRole.workspace_id == workspace_id)
        )
        if row is None:
            raise RoleNotFoundError(f"Role {role_id!r} not found")
        return row

    def get_role(
        self,
        workspace_id: str,
        role_id: str,
        *,
        only_current: bool = False,
        source_generation: str | None = None,
    ) -> RoleRecord:
        """Read one role; current-scope fail closed (T01-C2).

        Default (``only_current``): a role from a STALE source generation is
        not found — historical detail is an explicit separate contract via
        ``source_generation`` (the role is returned only when its generation
        matches the requested one, never mixed into the current view).
        """
        row = self._role_row(workspace_id, role_id)
        if source_generation is not None:
            if row.source_generation != source_generation:
                raise RoleNotFoundError(f"Role {role_id!r} not found")
        elif only_current and row.source_generation != self.current_generation(
            workspace_id, row.video_item_id
        ):
            raise RoleNotFoundError(f"Role {role_id!r} not found")
        media = _resolve_role_media(self._session, role_id)
        managed = bool(
            self._session.scalar(
                select(ObjectRoleArtifact.id)
                .where(ObjectRoleArtifact.role_id == role_id)
                .limit(1)
            )
        )
        return _map_role(row, media, has_media_associations=managed)

    def list_roles(
        self,
        workspace_id: str,
        *,
        video_item_id: str | None = None,
        status: str | None = None,
        source_generation: str | None = None,
        kind: str | None = None,
        only_current: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RoleRecord], int]:
        """List roles; current-generation default (T01-C2).

        - ``source_generation`` given → EXACT generation view (the explicit
          historical/current contract; never mixed with other generations).
        - ``only_current`` (no explicit generation) → ONLY roles whose
          generation equals the backend-authoritative current generation of
          their video item.  With ``video_item_id`` this is a single SQL
          filter; without it, currentness is resolved per video item.
        - ``kind`` → optional canonical-kind filter (S08-A01) — one of the
          seven ObjectRole kinds; an unknown kind is a stable ValueError (the
          API maps it to 422), never a silent empty or coercion.
        """
        if kind is not None and kind not in OBJECT_KINDS:
            raise ValueError(f"unknown role kind {kind!r}")
        filters = [ObjectRole.workspace_id == workspace_id]
        if video_item_id is not None:
            filters.append(ObjectRole.video_item_id == video_item_id)
        if status is not None:
            filters.append(ObjectRole.status == status)
        if kind is not None:
            filters.append(ObjectRole.kind == kind)
        if source_generation is not None:
            filters.append(ObjectRole.source_generation == source_generation)
        elif only_current and video_item_id is not None:
            current = self.current_generation(workspace_id, video_item_id)
            filters.append(ObjectRole.source_generation == current)
        if source_generation is not None or not only_current or video_item_id is not None:
            total = int(
                self._session.scalar(
                    select(func.count(ObjectRole.id)).where(*filters)
                )
                or 0
            )
            rows = self._session.scalars(
                select(ObjectRole)
                .options(selectinload(ObjectRole.occurrences))
                .where(*filters)
                .order_by(ObjectRole.created_at.desc(), ObjectRole.id)
                .offset(offset)
                .limit(limit)
            ).all()
        else:
            # Current-only WITHOUT a video filter: resolve currentness per
            # role's own video item (cross-video listing stays current-only).
            candidate_rows = self._session.execute(
                select(
                    ObjectRole.id,
                    ObjectRole.video_item_id,
                    ObjectRole.source_generation,
                ).where(*filters)
            ).all()
            videos = {str(vid) for (_, vid, _) in candidate_rows}
            current_by_video = self._current_generation_map(workspace_id, videos)
            keep = {
                str(rid)
                for (rid, vid, gen) in candidate_rows
                if gen == current_by_video.get(str(vid))
            }
            if not keep:
                return [], 0
            total = len(keep)
            id_filters = [ObjectRole.id.in_(keep), *filters]
            rows = self._session.scalars(
                select(ObjectRole)
                .options(selectinload(ObjectRole.occurrences))
                .where(*id_filters)
                .order_by(ObjectRole.created_at.desc(), ObjectRole.id)
                .offset(offset)
                .limit(limit)
            ).all()
        role_ids = [row.id for row in rows]
        media_rows = self._session.execute(
            select(ObjectRoleArtifact, Artifact)
            .join(Artifact, Artifact.id == ObjectRoleArtifact.artifact_id)
            .where(
                ObjectRoleArtifact.role_id.in_(role_ids),
                ObjectRoleArtifact.superseded_by_id.is_(None),
                exists(
                    select(ObjectOccurrence.id).where(
                        ObjectOccurrence.role_id == ObjectRoleArtifact.role_id
                    )
                ),
            )
            .order_by(
            ObjectRoleArtifact.purpose,
            ObjectRoleArtifact.created_at,
            ObjectRoleArtifact.id,
        )
        ).all()
        media_by_role: dict[str, list[RoleMediaRecord]] = {}
        for assoc, artifact in media_rows:
            media_by_role.setdefault(assoc.role_id, []).append(
                RoleMediaRecord(
                    association_id=assoc.id,
                    artifact_id=assoc.artifact_id,
                    purpose=assoc.purpose,
                    relative_path=artifact.relative_path,
                    sha256=artifact.sha256 or "",
                    size_bytes=artifact.size_bytes or 0,
                    width=artifact.width,
                    height=artifact.height,
                    mime_type=artifact.mime_type,
                    source_generation=assoc.source_generation,
                    source_job_id=assoc.source_job_id,
                )
            )
        managed_role_ids: set[str] = set()
        if role_ids:
            managed_pairs = self._session.execute(
                select(ObjectRoleArtifact.role_id)
                .where(ObjectRoleArtifact.role_id.in_(role_ids))
                .distinct()
            ).all()
            managed_role_ids = {str(rid) for (rid,) in managed_pairs}
        return [
            _map_role(
                row,
                media_by_role.get(row.id, []),
                has_media_associations=row.id in managed_role_ids,
            )
            for row in rows
        ], total

    def update_role(
        self,
        workspace_id: str,
        role_id: str,
        revision: int,
        *,
        name: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        description: str | None = None,
        supersedes_role_id: str | None = None,
    ) -> RoleRecord:
        current = self._session.get(ObjectRole, role_id)
        if current is None or current.workspace_id != workspace_id:
            raise RoleNotFoundError(f"Role {role_id!r} not found")
        if current.status == "superseded":
            raise RoleConflictError("superseded role is terminal")
        if kind is not None and kind not in OBJECT_KINDS:
            raise ValueError(f"unknown role kind {kind!r}")
        # T01-C2: stale-generation roles are immutable (fail closed, zero
        # mutation).  Apply-style operations target the current generation.
        self._assert_role_current(workspace_id, current)
        if status == "superseded":
            if supersedes_role_id is None:
                raise RoleConflictError("superseded requires a supersedes target")
            self._validate_supersession_target(
                workspace_id, role_id, current, supersedes_role_id
            )
        values: dict[str, object] = {"revision": revision + 1, "updated_at": utc_now()}
        if name is not None:
            values["name"] = name
        if kind is not None:
            values["kind"] = kind
        if status is not None:
            values["status"] = status
        if description is not None:
            values["description"] = description
        if supersedes_role_id is not None:
            values["supersedes_role_id"] = supersedes_role_id
        stmt = (
            update(ObjectRole)
            .where(
                ObjectRole.id == role_id,
                ObjectRole.workspace_id == workspace_id,
                ObjectRole.revision == revision,
            )
            .values(**values)
            .returning(ObjectRole)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.scalar(
                select(ObjectRole)
                .where(
                    ObjectRole.id == role_id,
                    ObjectRole.workspace_id == workspace_id,
                )
                .execution_options(populate_existing=True)
            )
            current_revision = latest.revision if latest is not None else None
            raise RoleConflictError(
                f"stale revision {revision}; current revision is {current_revision}"
            ) from None
        return _map_role(row)

    def _validate_supersession_target(
        self,
        workspace_id: str,
        role_id: str,
        current: ObjectRole,
        supersedes_role_id: str,
    ) -> None:
        """Fail-closed validation of a supersession target.

        The target must exist and belong to the SAME workspace, project, video
        item and source generation; it must not be the role itself and must not
        already be terminal (superseded).  Every violation is a stable conflict
        (RoleConflictError -> 409).
        """
        if supersedes_role_id == role_id:
            raise RoleConflictError("supersession target must not be the role itself")
        target = self._session.get(ObjectRole, supersedes_role_id)
        if target is None or target.workspace_id != workspace_id:
            raise RoleConflictError(
                f"supersession target {supersedes_role_id!r} not found in workspace"
            )
        if target.status == "superseded":
            raise RoleConflictError(
                "supersession target is terminal (already superseded)"
            )
        if target.project_id != current.project_id:
            raise RoleConflictError(
                "supersession target must belong to the same project"
            )
        if target.video_item_id != current.video_item_id:
            raise RoleConflictError(
                "supersession target must belong to the same video item"
            )
        if target.source_generation != current.source_generation:
            raise RoleConflictError(
                "supersession target must share the same source generation"
            )

    def create_occurrence(
        self,
        workspace_id: str,
        role_id: str,
        scene_id: str,
        frame_index: int,
        time_ms: int,
        *,
        bbox_x: int,
        bbox_y: int,
        bbox_w: int,
        bbox_h: int,
        confidence: float,
        confidence_source: str = "model",
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        reasons: list[str] | None = None,
        review_state: str = "unreviewed",
    ) -> tuple[OccurrenceRecord, bool]:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if bbox_w < 0 or bbox_h < 0:
            raise ValueError("bbox width and height must be non-negative")
        role, _ = self._assert_occurrence_ownership(workspace_id, role_id, scene_id)
        # Note (T01-C2): occurrence CREATION (evidence attachment) is the
        # extraction pipeline's contract and is NOT treated as a stale-role
        # operation — the T02 worker attaches evidence to the roles it created
        # for the current run, and grouping fixtures attach evidence to
        # explicit generation worlds.  The stale-generation fail-closed guard
        # applies to APPLY/CORRECTION-style mutations (update_role /
        # update_occurrence) under AC3.
        query = select(ObjectOccurrence).where(
            ObjectOccurrence.role_id == role_id,
            ObjectOccurrence.scene_id == scene_id,
            ObjectOccurrence.frame_index == frame_index,
        )
        existing = self._session.scalar(query)
        if existing is not None:
            self._assert_equivalent_occurrence_request(
                existing,
                time_ms,
                bbox_x,
                bbox_y,
                bbox_w,
                bbox_h,
                confidence,
                confidence_source,
                algorithm,
                algorithm_version,
                reasons,
                review_state,
            )
            return _map_occurrence(existing), False
        row = ObjectOccurrence(
            workspace_id=workspace_id,
            project_id=role.project_id,
            video_item_id=role.video_item_id,
            role_id=role_id,
            scene_id=scene_id,
            frame_index=frame_index,
            time_ms=time_ms,
            bbox_x=bbox_x,
            bbox_y=bbox_y,
            bbox_w=bbox_w,
            bbox_h=bbox_h,
            confidence=confidence,
            confidence_source=confidence_source,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            reasons_json=json.dumps(reasons or []),
            review_state=review_state,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalar(query)
            if existing is not None:
                self._assert_equivalent_occurrence_request(
                    existing,
                    time_ms,
                    bbox_x,
                    bbox_y,
                    bbox_w,
                    bbox_h,
                    confidence,
                    confidence_source,
                    algorithm,
                    algorithm_version,
                    reasons,
                    review_state,
                )
                return _map_occurrence(existing), False
            raise
        return _map_occurrence(row), True

    @staticmethod
    def _assert_equivalent_occurrence_request(
        existing: ObjectOccurrence,
        time_ms: int,
        bbox_x: int,
        bbox_y: int,
        bbox_w: int,
        bbox_h: int,
        confidence: float,
        confidence_source: str,
        algorithm: str | None,
        algorithm_version: str | None,
        reasons: list[str] | None,
        review_state: str,
    ) -> None:
        """Natural-key replay is allowed ONLY for an equivalent canonical request.

        A reused (role, scene, frame) key bound to a materially different
        evidence payload is a conflict — it must never return another
        occurrence as a successful replay.
        """
        if (
            existing.time_ms != time_ms
            or existing.bbox_x != bbox_x
            or existing.bbox_y != bbox_y
            or existing.bbox_w != bbox_w
            or existing.bbox_h != bbox_h
            or existing.confidence != confidence
            or existing.confidence_source != confidence_source
            or existing.algorithm != algorithm
            or existing.algorithm_version != algorithm_version
            or existing.review_state != review_state
            or existing.reasons_json != json.dumps(reasons or [])
        ):
            raise OccurrenceConflictError(
                "natural key (role, scene, frame) is already bound to a "
                "different occurrence payload"
            )

    def list_occurrences(self, workspace_id: str, role_id: str) -> list[OccurrenceRecord]:
        self._role_row(workspace_id, role_id)
        rows = self._session.scalars(
            select(ObjectOccurrence)
            .where(ObjectOccurrence.role_id == role_id)
            .order_by(ObjectOccurrence.scene_id, ObjectOccurrence.frame_index)
        ).all()
        return [_map_occurrence(row) for row in rows]

    def get_occurrence(
        self, workspace_id: str, role_id: str, occurrence_id: str
    ) -> OccurrenceRecord:
        """Read one occurrence; fails closed unless it belongs to the exact role.

        A role-A caller can never read a role-B occurrence (not-found, no
        existence leak).
        """
        row = self._session.scalar(
            select(ObjectOccurrence).where(
                ObjectOccurrence.id == occurrence_id,
                ObjectOccurrence.workspace_id == workspace_id,
                ObjectOccurrence.role_id == role_id,
            )
        )
        if row is None:
            raise OccurrenceNotFoundError(f"Occurrence {occurrence_id!r} not found")
        return _map_occurrence(row)

    def update_occurrence(
        self,
        workspace_id: str,
        role_id: str,
        occurrence_id: str,
        revision: int,
        *,
        confidence: float | None = None,
        review_state: str | None = None,
        reasons: list[str] | None = None,
        bbox_x: int | None = None,
        bbox_y: int | None = None,
        bbox_w: int | None = None,
        bbox_h: int | None = None,
    ) -> OccurrenceRecord:
        """CAS update; atomic revision predicate scoped to the exact role.

        The UPDATE matches only when (id, workspace, role, revision) all hold;
        exactly one affected row is required.  A role-A caller can never update
        a role-B occurrence (not-found, no existence leak).
        """
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        for value in (bbox_x, bbox_y, bbox_w, bbox_h):
            if value is not None and value < 0:
                raise ValueError("bbox values must be non-negative")
        # T01-C2: corrections/edits on a stale-generation role fail closed
        # (zero mutation).  The role is resolved BEFORE the CAS so no write
        # can reach the database when the generation is stale.
        role = self._session.get(ObjectRole, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise OccurrenceNotFoundError(f"Occurrence {occurrence_id!r} not found")
        self._assert_role_current(workspace_id, role)
        values: dict[str, object] = {
            "revision": revision + 1,
            "updated_at": utc_now(),
        }
        if confidence is not None:
            values["confidence"] = confidence
        if review_state is not None:
            values["review_state"] = review_state
        if reasons is not None:
            values["reasons_json"] = json.dumps(reasons)
        if bbox_x is not None:
            values["bbox_x"] = bbox_x
        if bbox_y is not None:
            values["bbox_y"] = bbox_y
        if bbox_w is not None:
            values["bbox_w"] = bbox_w
        if bbox_h is not None:
            values["bbox_h"] = bbox_h
        stmt = (
            update(ObjectOccurrence)
            .where(
                ObjectOccurrence.id == occurrence_id,
                ObjectOccurrence.workspace_id == workspace_id,
                ObjectOccurrence.role_id == role_id,
                ObjectOccurrence.revision == revision,
            )
            .values(**values)
            .returning(ObjectOccurrence)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            existing = self._session.scalar(
                select(ObjectOccurrence)
                .where(
                    ObjectOccurrence.id == occurrence_id,
                    ObjectOccurrence.workspace_id == workspace_id,
                )
                .execution_options(populate_existing=True)
            )
            if existing is None or existing.role_id != role_id:
                # Fail closed: missing or owned by a different role — never
                # leak existence across roles.
                raise OccurrenceNotFoundError(
                    f"Occurrence {occurrence_id!r} not found"
                ) from None
            raise OccurrenceConflictError(
                f"stale revision {revision}; current revision is {existing.revision}"
            ) from None
        return _map_occurrence(row)

    def map_legacy_objects(
        self, project_id: str, legacy_project_data: dict[str, object]
    ) -> LegacyObjectMapping:
        mapped: list[LegacyMappingItem] = []
        objects = legacy_project_data.get("objects", [])
        for raw in objects if isinstance(objects, list) else []:
            if not isinstance(raw, dict):
                continue
            selection = raw.get("selection", {})
            if not isinstance(selection, dict):
                selection = {}
            legacy_name = str(raw.get("name") or "")
            kind_value = raw.get("kind")
            raw_kind = str(getattr(kind_value, "value", kind_value) or "other").lower()
            source_kind = raw_kind
            if raw_kind in OBJECT_KINDS:
                kind = raw_kind
                normalization_reason = None
            else:
                # S08-A01 legacy provenance: historical unknown kinds still
                # map to the canonical ``other`` (backward compatible) BUT the
                # exact raw value and reason are recorded — never silently
                # coerced.
                kind = "other"
                normalization_reason = "unknown-kind-normalized-to-other"
            scene_id = int(raw.get("scene_id") or 0)
            evidence: dict[str, object] = {
                "legacy_scene_id": scene_id,
                "frame_index": int(selection.get("frame_index") or 0),
                "bbox": {
                    "x": int(selection.get("x") or 0),
                    "y": int(selection.get("y") or 0),
                    "width": int(selection.get("width") or 0),
                    "height": int(selection.get("height") or 0),
                },
            }
            mapped.append(
                LegacyMappingItem(
                    str(raw.get("object_id") or ""),
                    scene_id,
                    legacy_name,
                kind,
                    legacy_name or "Vật thể",
                    str(uuid.uuid4()),
                    [evidence],
                    source_kind=source_kind,
                    kind_normalization_reason=normalization_reason,
                )
            )
        return LegacyObjectMapping(
            project_id,
            "legacy-project-json",
            mapped,
            "Read-only compatibility mapping; ephemeral identities are never durable truth.",
        )

"""Durable cross-scene grouping + curation repository (S08-T03).

Implements the S08-T03 outcome on top of the S08-T01 ObjectRole /
ObjectOccurrence domain:

- **Reviewable grouping suggestions** are durable rows that ALWAYS start
  ``pending`` and NEVER auto-confirm.  Each suggestion carries confidence,
  review reasons and provenance (algorithm/version).  Generation is
  idempotent: the content-derived ``natural_key`` replay returns the SAME
  suggestion rows, and re-generation supersedes (never deletes) stale
  pending suggestions for the same (video, generation, version, scope).
- **Merge / split / confirm** are explicit durable mutations with
  CAS/revision protection on the affected ObjectRole, a content-derived
  ``natural_key`` (duplicate/concurrent requests and restart replay the SAME
  operation — never a second mutation), and a one-row-per-operation audit
  history (``RoleOperation``) recording target/sources/created roles, the
  exact transferred-occurrence map and the revision reached.
- **Fail closed across project/video/source-generation boundaries**: every
  mutation validates the full ownership chain and rejects cross-owner
  requests with ``OwnershipMismatchError``/``RoleConflictError``.
- **Superseded roles/evidence remain traceable; approved evidence is never
  silently rewritten or deleted**: merges only re-point occurrences
  (role_id + revision bump, content untouched) and record the move; splits
  move exactly the recorded occurrences back to a NEW suggested role (the
  original superseded role stays superseded — no duplicate active role).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.persistence.models import (
    REMOVAL_ONLY_KINDS,
    ObjectGroupingSuggestion,
    ObjectOccurrence,
    ObjectRole,
    Project,
    RoleOperation,
    VideoItem,
    utc_now,
)
from app.persistence.object_intelligence import (
    ObjectIntelligenceError,
    ObjectIntelligenceRepository,
    OccurrenceRecord,
    OwnershipMismatchError,
    RoleConflictError,
    RoleNotFoundError,
    RoleRecord,
)

__all__ = [
    "GroupingError",
    "GroupingNotFoundError",
    "ObjectGroupingRepository",
    "OperationConflictError",
    "OperationNotFoundError",
    "OperationRecord",
    "SuggestionConflictError",
    "SuggestionNotFoundError",
    "SuggestionRecord",
    "TransferEntry",
    "VideoItemNotFoundError",
]


class GroupingError(ObjectIntelligenceError):
    """Base error for durable grouping and curation."""


class GroupingNotFoundError(GroupingError):
    """Base error for missing grouping resources."""


class VideoItemNotFoundError(GroupingNotFoundError):
    """The video item does not exist in the requested workspace."""


class SuggestionNotFoundError(GroupingNotFoundError):
    """Suggestion does not exist in the requested workspace."""


class OperationNotFoundError(GroupingNotFoundError):
    """Operation does not exist in the requested workspace."""


class SuggestionConflictError(GroupingError):
    """Suggestion update conflicts with current durable state."""


class OperationConflictError(GroupingError):
    """Operation conflicts with current durable state (CAS/lineage/equivalence)."""


def merge_kind_conflict_message(
    target_id: str,
    target_kind: str,
    sources: list[tuple[str, str]],
) -> str | None:
    """F2 single-authority invariant: every merge source must share the kind.

    The ONLY place the mixed-kind merge rule is stated.  Both the grouping
    execute path (``apply_merge``) and the correction/merge PREVIEW
    (``ObjectCorrectionRepository.compute_impact``) derive their conflict
    message from THIS helper so the execute path and the preview can never
    drift apart (S08-A01-C1 F2 — no second production policy).

    ``sources`` is a list of ``(source_id, source_kind)``.  Returns the exact
    reject message when any source kind differs from the target's, else
    ``None`` (kind-homogeneous — the merge may proceed).
    """
    for source_id, source_kind in sources:
        if source_kind != target_kind:
            return (
                "merge sources must share the target role kind "
                f"(target {target_id!r} is {target_kind!r}; source "
                f"{source_id!r} is {source_kind!r})"
            )
    return None


@dataclass(frozen=True)
class SuggestionRecord:
    """Read model of one reviewable grouping suggestion."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    status: str
    role_ids: list[str]
    target_role_id: str | None
    confidence: float
    reasons: list[str]
    algorithm: str
    algorithm_version: str
    scope: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TransferEntry:
    """One source role's occurrence ids moved by a merge/split."""

    role_id: str
    occurrence_ids: list[str]


@dataclass(frozen=True)
class OperationRecord:
    """Read model of one audit-recorded merge/split/confirm operation."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    operation_type: str
    target_role_id: str
    source_role_ids: list[str]
    created_role_ids: list[str]
    transfer_map: list[TransferEntry]
    suggestion_id: str | None
    idempotency_key: str | None
    revision_after: int
    note: str | None
    created_at: datetime


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _json_objects(value: str | None) -> list[dict[str, object]]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _strict_list(value: object) -> list[object]:
    """Narrow an unchecked JSON value to a list (mypy-safe)."""
    return value if isinstance(value, list) else []


def _rowcount(result: object) -> int:
    """Mypy-safe rowcount access on an UPDATE result."""
    return int(getattr(result, "rowcount", None) or 0)


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
        reasons=_json_list(row.reasons_json),
        review_state=row.review_state,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _map_role(row: ObjectRole) -> RoleRecord:
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
    )


def _map_suggestion(row: ObjectGroupingSuggestion) -> SuggestionRecord:
    return SuggestionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        source_generation=row.source_generation,
        status=row.status,
        role_ids=_json_list(row.role_ids_json),
        target_role_id=row.target_role_id,
        confidence=row.confidence,
        reasons=_json_list(row.reasons_json),
        algorithm=row.algorithm,
        algorithm_version=row.algorithm_version,
        scope=row.scope,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _map_operation(row: RoleOperation) -> OperationRecord:
    return OperationRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        operation_type=row.operation_type,
        target_role_id=row.target_role_id,
        source_role_ids=_json_list(row.source_role_ids_json),
        created_role_ids=_json_list(row.created_role_ids_json),
        transfer_map=[
            TransferEntry(
                role_id=str(item.get("role_id") or ""),
                occurrence_ids=[
                    str(occ)
                    for occ in _strict_list(item.get("occurrence_ids"))
                ],
            )
            for item in _json_objects(row.transferred_occurrence_ids_json)
        ],
        suggestion_id=row.suggestion_id,
        idempotency_key=row.idempotency_key,
        revision_after=row.revision_after,
        note=row.note,
        created_at=row.created_at,
    )


class ObjectGroupingRepository:
    """Durable grouping suggestions + explicit merge/split/confirm mutations.

    One repository over the same session as the T01/T02 repos.  All
    mutations validate the ownership chain fail-closed and all
    duplicate/concurrent requests replay the SAME durable row via the
    content-derived ``natural_key`` — never a second mutation.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        # Backend-authoritative current-generation resolution (T01-C2
        # surface); shares the SAME session - never a layered copy.
        self._oi = ObjectIntelligenceRepository(session)

    # ── ownership / identity helpers ───────────────────────────────────────

    def _assert_role_ownership(
        self, workspace_id: str, project_id: str, video_item_id: str
    ) -> None:
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise OwnershipMismatchError("project ownership mismatch")
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise OwnershipMismatchError("video ownership mismatch")

    def get_video_project(self, workspace_id: str, video_item_id: str) -> str:
        """Fail-closed project lookup for one video item of the workspace."""
        video = self._session.get(VideoItem, video_item_id)
        if video is None:
            raise VideoItemNotFoundError(
                f"video item {video_item_id!r} not found in workspace"
            )
        project = self._session.get(Project, video.project_id)
        if project is None or project.workspace_id != workspace_id:
            raise OwnershipMismatchError("video item ownership mismatch")
        return video.project_id

    def current_generation(self, workspace_id: str, video_item_id: str) -> str:
        """Backend-authoritative current generation (T01-C2 surface)."""
        return self._oi.current_generation(workspace_id, video_item_id)

    def assert_generation_current(
        self, workspace_id: str, video_item_id: str, source_generation: str
    ) -> None:
        """Generate-time gate: suggestions are created ONLY for the current
        generation of the video item (finding C2 #5).  A stale generation
        fails closed with ZERO mutation.
        """
        current = self._oi.current_generation(workspace_id, video_item_id)
        if source_generation != current:
            raise SuggestionConflictError(
                f"source_generation {source_generation!r} is not the "
                f"backend current generation {current!r}; suggestions can "
                "only be generated for the current generation"
            )

    def _assert_suggestion_current(
        self, workspace_id: str, suggestion: ObjectGroupingSuggestion
    ) -> None:
        """Fail-closed guard: only current-generation suggestions are
        actionable (dismiss, merge-by-suggestion).  Historical inspection is
        a separate read-only contract; stale suggestions are never silently
        mutated.
        """
        current = self._oi.current_generation(
            workspace_id, suggestion.video_item_id
        )
        if suggestion.source_generation != current:
            raise SuggestionConflictError(
                f"suggestion {suggestion.id!r} belongs to stale source "
                f"generation {suggestion.source_generation!r}; only "
                f"current-generation suggestions are actionable (current "
                f"generation is {current!r})"
            )

    def _assert_role_current(self, workspace_id: str, role: ObjectRole) -> None:
        """Fail-closed guard: only current-generation roles are mutable."""
        current = self._oi.current_generation(workspace_id, role.video_item_id)
        if role.source_generation != current:
            raise RoleConflictError(
                f"role {role.id!r} belongs to stale source generation "
                f"{role.source_generation!r}; only current-generation roles "
                f"are mutable (current generation is {current!r})"
            )

    def _role_row(self, workspace_id: str, role_id: str) -> ObjectRole:
        row = self._session.get(ObjectRole, role_id)
        if row is None or row.workspace_id != workspace_id:
            raise RoleNotFoundError(f"Role {role_id!r} not found")
        return row

    def _role_record(self, workspace_id: str, role_id: str) -> RoleRecord:
        row = self._session.scalar(
            select(ObjectRole)
            .options(selectinload(ObjectRole.occurrences))
            .where(ObjectRole.id == role_id, ObjectRole.workspace_id == workspace_id)
        )
        if row is None:
            raise RoleNotFoundError(f"Role {role_id!r} not found")
        return _map_role(row)

    def _suggestion_row(
        self, workspace_id: str, suggestion_id: str
    ) -> ObjectGroupingSuggestion:
        row = self._session.scalar(
            select(ObjectGroupingSuggestion).where(
                ObjectGroupingSuggestion.id == suggestion_id,
                ObjectGroupingSuggestion.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise SuggestionNotFoundError(f"Suggestion {suggestion_id!r} not found")
        return row

    def _operation_row(self, workspace_id: str, operation_id: str) -> RoleOperation:
        row = self._session.scalar(
            select(RoleOperation).where(
                RoleOperation.id == operation_id,
                RoleOperation.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise OperationNotFoundError(f"Operation {operation_id!r} not found")
        return row

    # ── natural keys (content-derived idempotency) ─────────────────────────

    @staticmethod
    def _suggestion_natural_key(
        video_item_id: str,
        source_generation: str,
        algorithm_version: str,
        scope: str,
        sorted_role_ids: list[str],
    ) -> str:
        return (
            f"GROUP:{video_item_id}:{source_generation}:{algorithm_version}:"
            f"{scope}:{_sha256('|'.join(sorted_role_ids))[:32]}"
        )

    @staticmethod
    def _merge_natural_key(target_role_id: str, sources: list[str]) -> str:
        return f"MERGE:{target_role_id}:{_sha256('|'.join(sources))[:32]}"

    @staticmethod
    def _split_natural_key(target_role_id: str, original_role_id: str) -> str:
        return f"SPLIT:{target_role_id}:{original_role_id}"

    @staticmethod
    def _confirm_natural_key(role_id: str) -> str:
        return f"CONFIRM:{role_id}"

    def _replay_operation(
        self,
        workspace_id: str,
        natural_key: str,
        *,
        operation_type: str | None = None,
        target_role_id: str | None = None,
        sources: list[str] | None = None,
        suggestion_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> OperationRecord | None:
        """Replay an already-recorded operation ONLY when equivalent.

        Returns the existing operation for an equivalent canonical request,
        raises ``OperationConflictError`` when the natural key is bound to a
        materially different request, and returns ``None`` when no operation
        exists yet.
        """
        row = self._session.scalar(
            select(RoleOperation).where(
                RoleOperation.workspace_id == workspace_id,
                RoleOperation.natural_key == natural_key,
            )
        )
        if row is None:
            return None
        if operation_type is not None and row.operation_type != operation_type:
            raise OperationConflictError(
                f"natural key {natural_key!r} is bound to a different operation type"
            )
        if (
            target_role_id is not None
            and row.target_role_id != target_role_id
        ):
            raise OperationConflictError(
                f"natural key {natural_key!r} is bound to a different target role"
            )
        if sources is not None and set(_json_list(row.source_role_ids_json)) != set(
            sources
        ):
            raise OperationConflictError(
                f"natural key {natural_key!r} is bound to different source roles"
            )
        if suggestion_id is not None and row.suggestion_id != suggestion_id:
            raise OperationConflictError(
                f"natural key {natural_key!r} is bound to a different suggestion"
            )
        if (
            idempotency_key
            and row.idempotency_key
            and row.idempotency_key != idempotency_key
        ):
            raise OperationConflictError(
                f"natural key {natural_key!r} is bound to a different idempotency key"
            )
        return _map_operation(row)


# ── reviewable grouping suggestions ─────────────────────────────────────

    @staticmethod
    def _assert_equivalent_suggestion(
        existing: ObjectGroupingSuggestion,
        video_item_id: str,
        source_generation: str,
        sorted_role_ids: list[str],
        confidence: float,
        reasons: list[str],
        algorithm: str,
        algorithm_version: str,
        scope: str,
        target_role_id: str | None,
        idempotency_key: str | None,
    ) -> None:
        """Natural-key replay is allowed ONLY for an equivalent request."""
        # Identity fields only: video/generation/role-id set/algorithm/
        # scope/target.  Confidence and reasons are DERIVED advisory content
        # (they legitimately change when the evidence changes, e.g. after a
        # role rename) — they are never part of the natural-key equivalence.
        if (
            existing.video_item_id != video_item_id
            or existing.source_generation != source_generation
            or _json_list(existing.role_ids_json) != sorted_role_ids
            or existing.algorithm != algorithm
            or existing.algorithm_version != algorithm_version
            or existing.scope != scope
            or existing.target_role_id != target_role_id
        ):
            raise SuggestionConflictError(
                f"suggestion natural key {existing.natural_key!r} is already "
                "bound to a different grouping request"
            )
        if (
            idempotency_key
            and existing.idempotency_key
            and existing.idempotency_key != idempotency_key
        ):
            raise SuggestionConflictError(
                f"suggestion idempotency key {idempotency_key!r} is already "
                "bound to a different grouping request"
            )

    def create_suggestion(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_generation: str,
        role_ids: list[str],
        confidence: float,
        reasons: list[str],
        algorithm: str,
        algorithm_version: str,
        *,
        scope: str = "video",
        target_role_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[SuggestionRecord, bool]:
        """Create one pending suggestion; replay returns the existing row.

        The row is ALWAYS created ``pending`` — grouping never auto-confirms.
        """
        sorted_ids = sorted(set(role_ids))
        if not sorted_ids:
            raise ValueError("suggestion requires at least one role id")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not source_generation.strip():
            raise ValueError("source_generation must not be empty")
        self._assert_role_ownership(workspace_id, project_id, video_item_id)
        natural_key = self._suggestion_natural_key(
            video_item_id, source_generation, algorithm_version, scope, sorted_ids
        )
        existing = self._session.scalar(
            select(ObjectGroupingSuggestion).where(
                ObjectGroupingSuggestion.workspace_id == workspace_id,
                ObjectGroupingSuggestion.natural_key == natural_key,
            )
        )
        if existing is not None:
            if existing.status in ("applied", "superseded"):
                # History is not replayable: the natural key should have been
                # detached on apply/supersede; defensive fail-closed.
                raise SuggestionConflictError(
                    "suggestion natural key is bound to a completed "
                    "suggestion (applied/superseded)"
                )
            self._assert_equivalent_suggestion(
                existing,
                video_item_id,
                source_generation,
                sorted_ids,
                confidence,
                reasons,
                algorithm,
                algorithm_version,
                scope,
                target_role_id,
                idempotency_key,
            )
            if existing.status == "pending":
                # Advisory content refresh: the SAME stable role pair was
                # re-derived from changed evidence (e.g. a rename).  The
                # role ids never change; only confidence/reasons follow the
                # current evidence.  Dismissed rows are NEVER refreshed (a
                # reviewer decision is preserved).
                new_reasons_json = json.dumps(reasons)
                if (
                    existing.confidence != confidence
                    or existing.reasons_json != new_reasons_json
                ):
                    self._session.execute(
                        update(ObjectGroupingSuggestion)
                        .where(
                            ObjectGroupingSuggestion.id == existing.id,
                            ObjectGroupingSuggestion.status == "pending",
                        )
                        .values(
                            confidence=confidence,
                            reasons_json=new_reasons_json,
                            updated_at=utc_now(),
                        )
                    )
                    refreshed = self._session.scalar(
                        select(ObjectGroupingSuggestion)
                        .where(ObjectGroupingSuggestion.id == existing.id)
                        .execution_options(populate_existing=True)
                    )
                    if refreshed is None:  # pragma: no cover - defensive
                        raise SuggestionNotFoundError(
                            f"Suggestion {existing.id!r} not found"
                        )
                    existing = refreshed
            return _map_suggestion(existing), False
        row = ObjectGroupingSuggestion(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            source_generation=source_generation,
            status="pending",
            role_ids_json=json.dumps(sorted_ids),
            target_role_id=target_role_id,
            confidence=confidence,
            reasons_json=json.dumps(reasons),
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            scope=scope,
            idempotency_key=idempotency_key,
            natural_key=natural_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalar(
                select(ObjectGroupingSuggestion).where(
                    ObjectGroupingSuggestion.workspace_id == workspace_id,
                    ObjectGroupingSuggestion.natural_key == natural_key,
                )
            )
            if existing is not None:
                if existing.status in ("applied", "superseded"):
                    raise SuggestionConflictError(
                        "suggestion natural key is bound to a completed "
                        "suggestion (applied/superseded)"
                    ) from None
                self._assert_equivalent_suggestion(
                    existing,
                    video_item_id,
                    source_generation,
                    sorted_ids,
                    confidence,
                    reasons,
                    algorithm,
                    algorithm_version,
                    scope,
                    target_role_id,
                    idempotency_key,
                )
                return _map_suggestion(existing), False
            raise
        return _map_suggestion(row), True

    def supersede_stale_suggestions(
        self,
        workspace_id: str,
        video_item_id: str,
        source_generation: str,
        algorithm_version: str,
        scope: str,
    ) -> int:
        """Traceably supersede suggestions whose role set is no longer active.

        Re-running generation for the same (video, generation, version,
        scope) supersedes (never deletes) every pending/dismissed suggestion
        that references at least one role which is no longer in the ACTIVE
        (suggested/confirmed) set of this video + generation — e.g. a role
        that has since been merged away.  Suggestions whose set is still
        fully active are LEFT ALONE so the idempotent replay returns the
        exact same rows (200), never clobbering a reviewer's decision.
        """
        pending = list(
            self._session.scalars(
                select(ObjectGroupingSuggestion).where(
                    ObjectGroupingSuggestion.workspace_id == workspace_id,
                    ObjectGroupingSuggestion.video_item_id == video_item_id,
                    ObjectGroupingSuggestion.source_generation
                    == source_generation,
                    ObjectGroupingSuggestion.algorithm_version
                    == algorithm_version,
                    ObjectGroupingSuggestion.scope == scope,
                    ObjectGroupingSuggestion.status.in_(("pending", "dismissed")),
                )
            ).all()
        )
        if not pending:
            return 0
        active = set(
            self._session.scalars(
                select(ObjectRole.id).where(
                    ObjectRole.workspace_id == workspace_id,
                    ObjectRole.video_item_id == video_item_id,
                    ObjectRole.source_generation == source_generation,
                    ObjectRole.status.in_(("suggested", "confirmed")),
                )
            ).all()
        )
        now = utc_now()
        superseded_count = 0
        for row in pending:
            role_ids = _json_list(row.role_ids_json)
            if not role_ids or any(rid not in active for rid in role_ids):
                result = self._session.execute(
                    update(ObjectGroupingSuggestion)
                    .where(
                        ObjectGroupingSuggestion.id == row.id,
                        ObjectGroupingSuggestion.status.in_(
                            ("pending", "dismissed")
                        ),
                    )
                    .values(
                        status="superseded",
                        revision=ObjectGroupingSuggestion.revision + 1,
                        updated_at=now,
                        natural_key=None,
                    )
                )
                superseded_count += _rowcount(result)
        return superseded_count

    def _supersede_suggestions_for_roles(
        self,
        workspace_id: str,
        video_item_id: str,
        role_ids: set[str],
        *,
        exclude_id: str | None,
        now: datetime,
    ) -> None:
        """Supersede pending suggestions that reference any merged role."""
        rows = self._session.scalars(
            select(ObjectGroupingSuggestion).where(
                ObjectGroupingSuggestion.workspace_id == workspace_id,
                ObjectGroupingSuggestion.video_item_id == video_item_id,
                ObjectGroupingSuggestion.status == "pending",
            )
        ).all()
        for row in rows:
            if row.id == exclude_id:
                continue
            if any(rid in role_ids for rid in _json_list(row.role_ids_json)):
                self._session.execute(
                    update(ObjectGroupingSuggestion)
                    .where(
                        ObjectGroupingSuggestion.id == row.id,
                        ObjectGroupingSuggestion.status == "pending",
                    )
                    .values(
                        status="superseded",
                        revision=ObjectGroupingSuggestion.revision + 1,
                        updated_at=now,
                        natural_key=None,
                    )
                )

    def list_suggestions(
        self,
        workspace_id: str,
        *,
        video_item_id: str | None = None,
        status: str | None = None,
        role_id: str | None = None,
        source_generation: str | None = None,
        only_current: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SuggestionRecord], int]:
        """List suggestions; CURRENT-generation default (finding C2).

        - ``source_generation`` given -> EXACT generation view (the explicit
          historical/current contract; NEVER mixed with other generations).
        - ``only_current`` (no explicit generation) -> ONLY suggestions whose
          generation equals the backend-authoritative current generation of
          their video item.  With ``video_item_id`` this is a single SQL
          filter; without it, currentness is resolved per video item
          (cross-video listing stays current-only).
        """
        filters = [ObjectGroupingSuggestion.workspace_id == workspace_id]
        if video_item_id is not None:
            filters.append(ObjectGroupingSuggestion.video_item_id == video_item_id)
        if status is not None:
            filters.append(ObjectGroupingSuggestion.status == status)
        if source_generation is not None:
            filters.append(
                ObjectGroupingSuggestion.source_generation == source_generation
            )
        elif only_current and video_item_id is not None:
            current = self._oi.current_generation(workspace_id, video_item_id)
            filters.append(
                ObjectGroupingSuggestion.source_generation == current
            )
        if source_generation is not None or not only_current or video_item_id is not None:
            rows = list(
                self._session.scalars(
                    select(ObjectGroupingSuggestion)
                    .where(*filters)
                    .order_by(
                        ObjectGroupingSuggestion.created_at.desc(),
                        ObjectGroupingSuggestion.id,
                    )
                ).all()
            )
        else:
            # Current-only WITHOUT a video filter: resolve currentness per
            # suggestion's own video item (cross-video listing stays
            # current-only; stale generations never leak into it).
            candidates = self._session.execute(
                select(
                    ObjectGroupingSuggestion.id,
                    ObjectGroupingSuggestion.video_item_id,
                    ObjectGroupingSuggestion.source_generation,
                ).where(*filters)
            ).all()
            videos = {str(vid) for (_, vid, _) in candidates}
            current_by_video = {
                vid: self._oi.current_generation(workspace_id, vid)
                for vid in videos
            }
            keep = {
                str(sid)
                for (sid, vid, gen) in candidates
                if gen == current_by_video.get(str(vid))
            }
            if not keep:
                return [], 0
            rows = list(
                self._session.scalars(
                    select(ObjectGroupingSuggestion)
                    .where(
                        ObjectGroupingSuggestion.id.in_(keep),
                        *filters,
                    )
                    .order_by(
                        ObjectGroupingSuggestion.created_at.desc(),
                        ObjectGroupingSuggestion.id,
                    )
                ).all()
            )
        if role_id is not None:
            rows = [
                row for row in rows if role_id in _json_list(row.role_ids_json)
            ]
        total = len(rows)
        return [_map_suggestion(r) for r in rows[offset : offset + limit]], total

    def get_suggestion(
        self,
        workspace_id: str,
        suggestion_id: str,
        *,
        only_current: bool = False,
        source_generation: str | None = None,
    ) -> SuggestionRecord:
        """Read one suggestion; current-scope fail closed (finding C2).

        Default (``only_current``): a suggestion from a STALE source
        generation is not found.  Historical detail is an explicit separate
        contract via ``source_generation`` — the suggestion is returned only
        when its generation matches the requested one, never mixed into the
        current view.
        """
        row = self._suggestion_row(workspace_id, suggestion_id)
        if source_generation is not None:
            if row.source_generation != source_generation:
                raise SuggestionNotFoundError(
                    f"Suggestion {suggestion_id!r} not found"
                )
        elif only_current:
            current = self._oi.current_generation(
                workspace_id, row.video_item_id
            )
            if row.source_generation != current:
                raise SuggestionNotFoundError(
                    f"Suggestion {suggestion_id!r} not found"
                )
        return _map_suggestion(row)

    def dismiss_suggestion(
        self, workspace_id: str, suggestion_id: str, revision: int
    ) -> SuggestionRecord:
        """Explicitly reject a pending suggestion (CAS, state-idempotent).

        Stale (non-current) suggestions fail closed with ZERO mutation:
        only current-generation suggestions are actionable.
        """
        row = self._suggestion_row(workspace_id, suggestion_id)
        self._assert_suggestion_current(workspace_id, row)
        if row.status == "dismissed":
            # State already achieved — a retry replays without a second write.
            return _map_suggestion(row)
        if row.status in ("applied", "superseded"):
            raise SuggestionConflictError(
                f"suggestion is {row.status}; only pending suggestions can be dismissed"
            )
        result = self._session.execute(
            update(ObjectGroupingSuggestion)
            .where(
                ObjectGroupingSuggestion.id == suggestion_id,
                ObjectGroupingSuggestion.workspace_id == workspace_id,
                ObjectGroupingSuggestion.revision == revision,
                ObjectGroupingSuggestion.status == "pending",
            )
            .values(
                status="dismissed",
                revision=ObjectGroupingSuggestion.revision + 1,
                updated_at=utc_now(),
            )
        )
        if _rowcount(result) != 1:
            latest = self._session.scalar(
                select(ObjectGroupingSuggestion)
                .where(
                    ObjectGroupingSuggestion.id == suggestion_id,
                    ObjectGroupingSuggestion.workspace_id == workspace_id,
                )
                .execution_options(populate_existing=True)
            )
            current = latest.revision if latest is not None else None
            raise SuggestionConflictError(
                f"stale revision {revision}; current revision is {current}"
            )
        return _map_suggestion(row)


# ── explicit durable mutations: merge ───────────────────────────────────

    def apply_merge(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        target_role_id: str,
        source_role_ids: list[str],
        revision: int,
        *,
        suggestion_id: str | None = None,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> tuple[OperationRecord, RoleRecord, bool]:
        """Merge sources into the target: CAS, evidence move, audit row.

        - The target and EVERY source must share workspace/project/video and
          source generation (fail closed across boundaries).
        - The target's ``revision`` is the CAS token; every source row is
          atomically superseded (``supersedes_role_id`` = target) — never
          deleted, fully traceable.
        - Occurrence rows are ONLY re-pointed (role_id + revision bump).  No
          content (confidence/bbox/reasons/review_state) is rewritten.  A
          collision on the natural key ``(target, scene, frame)`` aborts the
          whole operation — evidence is never silently dropped.
        - The completed operation is recorded in the audit table with the
          exact transferred-occurrence map; duplicate/concurrent requests and
          restart replay the SAME operation row.
        """
        sources = sorted(set(source_role_ids))
        if not sources:
            raise OperationConflictError("merge requires at least one source role")
        if target_role_id in sources:
            raise OperationConflictError("merge target must not be a source role")
        natural_key = self._merge_natural_key(target_role_id, sources)
        replay = self._replay_operation(
            workspace_id,
            natural_key,
            operation_type="merge",
            target_role_id=target_role_id,
            sources=sources,
            suggestion_id=suggestion_id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay, self._role_record(workspace_id, target_role_id), False

        self._assert_role_ownership(workspace_id, project_id, video_item_id)
        target = self._role_row(workspace_id, target_role_id)
        if target.status == "superseded":
            raise RoleConflictError("merge target is terminal (superseded)")
        source_rows: dict[str, ObjectRole] = {}
        for source_id in sources:
            row = self._session.get(ObjectRole, source_id)
            if (
                row is None
                or row.workspace_id != workspace_id
                or row.project_id != project_id
                or row.video_item_id != video_item_id
            ):
                raise OwnershipMismatchError(
                    "merge source belongs to a different project/video/workspace"
                )
            if row.status == "superseded":
                raise RoleConflictError(
                    f"merge source {source_id} is terminal (superseded)"
                )
            if row.source_generation != target.source_generation:
                raise RoleConflictError(
                    "merge sources must share the target's source generation"
                )
            source_rows[source_id] = row
        # S08-A01 removal-only policy: a source-overlay role (backend-owned,
        # removal-only) can never be a merge participant — it is not a
        # replacement/Character Pack candidate and it never merges with
        # anything (grouping never proposes such pairs either).
        if target.kind in REMOVAL_ONLY_KINDS:
            raise RoleConflictError(
                "removal-only roles (source_overlay) cannot be merge targets"
            )
        for source_row in source_rows.values():
            if source_row.kind in REMOVAL_ONLY_KINDS:
                raise OperationConflictError(
                    "removal-only roles (source_overlay) cannot be merge sources"
                )
        # S08-A01-C1 (F2): kind-safe manual merge — every source MUST share
        # the target's kind (not just removal-only excluded).  A merge is a
        # kind-homogeneous curation action: never silently merge a 'graphic'
        # into a 'character' or a 'background' into a 'prop'.  Reject with a
        # stable conflict BEFORE any mutation (roles/revisions/statuses/
        # occurrences/operations/suggestions stay byte-identical).  The rule
        # is stated ONCE in merge_kind_conflict_message — the correction/
        # merge preview derives the SAME message so both paths never drift.
        message = merge_kind_conflict_message(
            target.id,
            target.kind,
            [(src.id, src.kind) for src in source_rows.values()],
        )
        if message is not None:
            raise OperationConflictError(message)
        # Stale-generation roles/suggestions are NEVER mutable (finding
        # C2 #3): every merge participant must belong to the backend
        # current generation, otherwise fail closed with ZERO mutation.
        self._assert_role_current(workspace_id, target)
        for source_row in source_rows.values():
            self._assert_role_current(workspace_id, source_row)
        applied_suggestion_id: str | None = None
        if suggestion_id is not None:
            suggestion = self._suggestion_row(workspace_id, suggestion_id)
            if suggestion.video_item_id != video_item_id:
                raise OperationConflictError(
                    "suggestion does not belong to this video item"
                )
            self._assert_suggestion_current(workspace_id, suggestion)
            if suggestion.status != "pending":
                raise OperationConflictError(
                    f"suggestion is {suggestion.status}; only pending suggestions "
                    "can drive a merge"
                )
            applied_suggestion_id = suggestion.id
        try:
            now = utc_now()
            target_after = self._session.execute(
                update(ObjectRole)
                .where(
                    ObjectRole.id == target_role_id,
                    ObjectRole.workspace_id == workspace_id,
                    ObjectRole.revision == revision,
                    ObjectRole.status != "superseded",
                )
                .values(revision=ObjectRole.revision + 1, updated_at=now)
                .returning(ObjectRole)
            ).scalar_one_or_none()
            if target_after is None:
                raise RoleConflictError(
                    f"stale revision {revision} for merge target"
                )
            for source in source_rows.values():
                updated = self._session.execute(
                    update(ObjectRole)
                    .where(
                        ObjectRole.id == source.id,
                        ObjectRole.workspace_id == workspace_id,
                        ObjectRole.revision == source.revision,
                        ObjectRole.status != "superseded",
                    )
                    .values(
                        status="superseded",
                        supersedes_role_id=target_role_id,
                        revision=ObjectRole.revision + 1,
                        updated_at=now,
                    )
                    .returning(ObjectRole.id)
                ).scalar_one_or_none()
                if updated is None:
                    raise RoleConflictError(
                        f"merge source {source.id} changed concurrently"
                    )
            occupied = {
                (occ.scene_id, occ.frame_index)
                for occ in self._session.scalars(
                    select(ObjectOccurrence).where(
                        ObjectOccurrence.role_id == target_role_id
                    )
                ).all()
            }
            source_occurrences = self._session.scalars(
                select(ObjectOccurrence)
                .where(ObjectOccurrence.role_id.in_(sources))
                .order_by(ObjectOccurrence.id)
            ).all()
            by_source: dict[str, list[str]] = {}
            for occ in source_occurrences:
                if (occ.scene_id, occ.frame_index) in occupied:
                    raise OperationConflictError(
                        "occurrence collision at "
                        f"scene {occ.scene_id} frame {occ.frame_index} — "
                        "merge would duplicate evidence"
                    )
                by_source.setdefault(occ.role_id, []).append(occ.id)
            transfer: list[dict[str, object]] = []
            for source_id in sources:
                occ_ids = by_source.get(source_id, [])
                if not occ_ids:
                    continue
                moved = self._session.execute(
                    update(ObjectOccurrence)
                    .where(
                        ObjectOccurrence.id.in_(occ_ids),
                        ObjectOccurrence.role_id == source_id,
                    )
                    .values(
                        role_id=target_role_id,
                        revision=ObjectOccurrence.revision + 1,
                        updated_at=now,
                    )
                    .returning(ObjectOccurrence.id)
                ).scalars().all()
                if len(moved) != len(occ_ids):
                    raise OperationConflictError(
                        "occurrence move raced with a concurrent change"
                    )
                transfer.append(
                    {"role_id": source_id, "occurrence_ids": sorted(occ_ids)}
                )
            if applied_suggestion_id is not None:
                self._session.execute(
                    update(ObjectGroupingSuggestion)
                    .where(
                        ObjectGroupingSuggestion.id == applied_suggestion_id,
                        ObjectGroupingSuggestion.status == "pending",
                    )
                    .values(
                        status="applied",
                        revision=ObjectGroupingSuggestion.revision + 1,
                        updated_at=now,
                        natural_key=None,
                    )
                )
            self._supersede_suggestions_for_roles(
                workspace_id,
                video_item_id,
                {target_role_id, *sources},
                exclude_id=applied_suggestion_id,
                now=now,
            )
            operation = RoleOperation(
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                operation_type="merge",
                target_role_id=target_role_id,
                source_role_ids_json=json.dumps(sources),
                created_role_ids_json="[]",
                transferred_occurrence_ids_json=json.dumps(transfer),
                suggestion_id=applied_suggestion_id,
                idempotency_key=idempotency_key,
                natural_key=natural_key,
                revision_after=target_after.revision,
                note=note,
            )
            self._session.add(operation)
            self._session.flush()
        except (RoleConflictError, IntegrityError):
            self._session.rollback()
            replay = self._replay_operation(
                workspace_id,
                natural_key,
                operation_type="merge",
                target_role_id=target_role_id,
                sources=sources,
                suggestion_id=suggestion_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return (
                    replay,
                    self._role_record(workspace_id, target_role_id),
                    False,
                )
            raise
        return _map_operation(operation), _map_role(target_after), True


# ── explicit durable mutations: split ───────────────────────────────────

    def apply_split(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        target_role_id: str,
        original_role_id: str,
        revision: int,
        *,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> tuple[OperationRecord, RoleRecord, bool]:
        """Split one previously merged original role back out of the target.

        - The target's ``revision`` is the CAS token; the target must be
          active (a terminal superseded role cannot be split).
        - The original role must exist and be the SUPERSEDED result of a
          T03 merge into exactly this target (merge lineage via the audit
          table) — a plain T01 supersession has no transferred occurrences
          and is refused (never creates an empty duplicate role).
        - The EXACT occurrences recorded as transferred by the merge are
          moved to a NEW suggested role (same name/kind/generation/content
          as the original — occurrence content is never rewritten).  The
          original superseded role stays superseded: traceable, and never a
          duplicate of the new active role.
        - Duplicate/concurrent requests and restart replay the SAME split
          operation and created role (natural key ``SPLIT:<target>:<orig>``).
        """
        natural_key = self._split_natural_key(target_role_id, original_role_id)
        replay = self._replay_operation(
            workspace_id,
            natural_key,
            operation_type="split",
            target_role_id=target_role_id,
            sources=[original_role_id],
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            created_id = (
                replay.created_role_ids[0] if replay.created_role_ids else None
            )
            if created_id is None:
                raise OperationConflictError(
                    "split replay references no created role"
                )
            return (
                replay,
                self._role_record(workspace_id, created_id),
                False,
            )

        self._assert_role_ownership(workspace_id, project_id, video_item_id)
        target = self._role_row(workspace_id, target_role_id)
        if target.status == "superseded":
            raise RoleConflictError("split target is terminal (superseded)")
        self._assert_role_current(workspace_id, target)
        original = self._session.get(ObjectRole, original_role_id)
        if original is None or original.workspace_id != workspace_id:
            raise RoleNotFoundError(
                f"Role {original_role_id!r} not found in workspace"
            )
        if original.status != "superseded":
            raise OperationConflictError(
                "original role is not superseded — no merge lineage to split"
            )
        if original.supersedes_role_id != target_role_id:
            raise OperationConflictError(
                "original role was not merged into this target"
            )
        merge_op = self._session.scalar(
            select(RoleOperation)
            .where(
                RoleOperation.workspace_id == workspace_id,
                RoleOperation.operation_type == "merge",
                RoleOperation.target_role_id == target_role_id,
            )
            .order_by(RoleOperation.created_at.desc(), RoleOperation.id.desc())
        )
        if merge_op is None or original_role_id not in _json_list(
            merge_op.source_role_ids_json
        ):
            raise OperationConflictError(
                "no merge operation records the original role — split requires "
                "a T03 merge lineage"
            )
        entry = next(
            (
                item
                for item in _json_objects(merge_op.transferred_occurrence_ids_json)
                if str(item.get("role_id")) == original_role_id
            ),
            None,
        )
        if entry is None:
            raise OperationConflictError(
                "merge lineage recorded no transferred occurrences for the "
                "original role"
            )
        occurrence_ids = sorted(
            str(occ) for occ in _strict_list(entry.get("occurrence_ids"))
        )
        if not occurrence_ids:
            raise OperationConflictError(
                "merge lineage recorded no transferred occurrences for the "
                "original role"
            )
        try:
            now = utc_now()
            target_after = self._session.execute(
                update(ObjectRole)
                .where(
                    ObjectRole.id == target_role_id,
                    ObjectRole.workspace_id == workspace_id,
                    ObjectRole.revision == revision,
                    ObjectRole.status != "superseded",
                )
                .values(revision=ObjectRole.revision + 1, updated_at=now)
                .returning(ObjectRole)
            ).scalar_one_or_none()
            if target_after is None:
                raise RoleConflictError(
                    f"stale revision {revision} for split target"
                )
            new_role = ObjectRole(
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                source_generation=target.source_generation,
                name=original.name,
                kind=original.kind,
                status="suggested",
                description=original.description,
                legacy_object_id=original.legacy_object_id,
                legacy_scene_id=original.legacy_scene_id,
                source_job_id=original.source_job_id,
            )
            self._session.add(new_role)
            self._session.flush()
            moved = self._session.execute(
                update(ObjectOccurrence)
                .where(
                    ObjectOccurrence.id.in_(occurrence_ids),
                    ObjectOccurrence.role_id == target_role_id,
                    ObjectOccurrence.workspace_id == workspace_id,
                )
                .values(
                    role_id=new_role.id,
                    revision=ObjectOccurrence.revision + 1,
                    updated_at=now,
                )
                .returning(ObjectOccurrence.id)
            ).scalars().all()
            if len(moved) == 0:
                raise OperationConflictError(
                    "transferred occurrences are no longer on the target — "
                    "split state inconsistent"
                )
            if len(moved) != len(occurrence_ids):
                raise OperationConflictError(
                    "partial occurrence transfer — split state inconsistent"
                )
            operation = RoleOperation(
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                operation_type="split",
                target_role_id=target_role_id,
                source_role_ids_json=json.dumps([original_role_id]),
                created_role_ids_json=json.dumps([new_role.id]),
                transferred_occurrence_ids_json=json.dumps(
                    [
                        {
                            "role_id": original_role_id,
                            "occurrence_ids": sorted(moved),
                        }
                    ]
                ),
                suggestion_id=merge_op.suggestion_id,
                idempotency_key=idempotency_key,
                natural_key=natural_key,
                revision_after=target_after.revision,
                note=note,
            )
            self._session.add(operation)
            self._session.flush()
        except (RoleConflictError, IntegrityError):
            self._session.rollback()
            replay = self._replay_operation(
                workspace_id,
                natural_key,
                operation_type="split",
                target_role_id=target_role_id,
                sources=[original_role_id],
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                created_id = (
                    replay.created_role_ids[0] if replay.created_role_ids else None
                )
                if created_id is not None:
                    return (
                        replay,
                        self._role_record(workspace_id, created_id),
                        False,
                    )
            raise
        return _map_operation(operation), _map_role(new_role), True


# ── explicit durable mutations: confirm ─────────────────────────────────

    def apply_confirm(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        role_id: str,
        revision: int,
        *,
        idempotency_key: str | None = None,
        note: str | None = None,
    ) -> tuple[OperationRecord, RoleRecord, bool]:
        """Explicitly confirm a role (CAS + audit + natural-key replay).

        Confirmation is an explicit user mutation, never automatic: model
        suggestions stay ``suggested`` until this endpoint (or the T01 PATCH)
        is called.  The operation record gives the durable audit trail.
        """
        natural_key = self._confirm_natural_key(role_id)
        replay = self._replay_operation(
            workspace_id,
            natural_key,
            operation_type="confirm",
            target_role_id=role_id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            current = self._role_record(workspace_id, role_id)
            if current.status == "superseded":
                raise RoleConflictError(
                    "role is terminal (superseded); previous confirm cannot "
                    "be replayed"
                )
            return replay, current, False

        self._assert_role_ownership(workspace_id, project_id, video_item_id)
        row = self._role_row(workspace_id, role_id)
        if row.status == "superseded":
            raise RoleConflictError("cannot confirm a terminal (superseded) role")
        self._assert_role_current(workspace_id, row)
        try:
            now = utc_now()
            after = self._session.execute(
                update(ObjectRole)
                .where(
                    ObjectRole.id == role_id,
                    ObjectRole.workspace_id == workspace_id,
                    ObjectRole.revision == revision,
                    ObjectRole.status.in_(("suggested", "confirmed")),
                )
                .values(
                    status="confirmed",
                    revision=ObjectRole.revision + 1,
                    updated_at=now,
                )
                .returning(ObjectRole)
            ).scalar_one_or_none()
            if after is None:
                raise RoleConflictError(f"stale revision {revision} for confirm")
            operation = RoleOperation(
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                operation_type="confirm",
                target_role_id=role_id,
                source_role_ids_json="[]",
                created_role_ids_json="[]",
                transferred_occurrence_ids_json="[]",
                suggestion_id=None,
                idempotency_key=idempotency_key,
                natural_key=natural_key,
                revision_after=after.revision,
                note=note,
            )
            self._session.add(operation)
            self._session.flush()
        except (RoleConflictError, IntegrityError):
            self._session.rollback()
            replay = self._replay_operation(
                workspace_id,
                natural_key,
                operation_type="confirm",
                target_role_id=role_id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                current = self._role_record(workspace_id, role_id)
                if current.status != "superseded":
                    return replay, current, False
            raise
        return _map_operation(operation), _map_role(after), True

    # ── read-only audit history ────────────────────────────────────────────

    def list_operations(
        self,
        workspace_id: str,
        *,
        video_item_id: str | None = None,
        operation_type: str | None = None,
        role_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[OperationRecord], int]:
        filters = [RoleOperation.workspace_id == workspace_id]
        if video_item_id is not None:
            filters.append(RoleOperation.video_item_id == video_item_id)
        if operation_type is not None:
            filters.append(RoleOperation.operation_type == operation_type)
        rows = list(
            self._session.scalars(
                select(RoleOperation)
                .where(*filters)
                .order_by(RoleOperation.created_at.desc(), RoleOperation.id)
            ).all()
        )
        if role_id is not None:
            rows = [
                row
                for row in rows
                if row.target_role_id == role_id
                or role_id in _json_list(row.source_role_ids_json)
                or role_id in _json_list(row.created_role_ids_json)
            ]
        total = len(rows)
        return [_map_operation(r) for r in rows[offset : offset + limit]], total

    def get_operation(self, workspace_id: str, operation_id: str) -> OperationRecord:
        return _map_operation(self._operation_row(workspace_id, operation_id))


# ── read-only role evidence for grouping ─────────────────────────────────

    def list_active_roles(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_generation: str,
    ) -> list[RoleRecord]:
        """Active (suggested/confirmed) roles of one video + generation.

        Superseded roles are excluded (they are terminal and traceable);
        the caller feeds exactly this evidence into the deterministic
        grouping algorithm.
        """
        self._assert_role_ownership(workspace_id, project_id, video_item_id)
        rows = self._session.scalars(
            select(ObjectRole)
            .options(selectinload(ObjectRole.occurrences))
            .where(
                ObjectRole.workspace_id == workspace_id,
                ObjectRole.project_id == project_id,
                ObjectRole.video_item_id == video_item_id,
                ObjectRole.source_generation == source_generation,
                ObjectRole.status.in_(("suggested", "confirmed")),
            )
            .order_by(ObjectRole.created_at, ObjectRole.id)
        ).all()
        return [_map_role(row) for row in rows]

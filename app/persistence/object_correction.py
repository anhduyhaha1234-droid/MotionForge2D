"""Durable targeted object correction repository (S08-T05).

Implements the S08-T05 dependency/invalidation graph (see the packet
DESIGN.md — normative) on top of the T01/T02/T03 durable domain:

- **Impact preview** (:meth:`ObjectCorrectionRepository.compute_impact`) is a
  PURE read that reports the EXACT affected role set, the pending suggestions
  that would be invalidated, the roles whose derived candidate artifacts
  would be recomputed, and whether durable recompute work is needed at all.
  It never writes.

- **Create** (:meth:`create_correction`) archives the pending correction with
  its computed impact; the content-derived ``natural_key`` replays the SAME
  row (duplicate/concurrent requests and restart are idempotent).

- **Confirm** (:meth:`confirm_correction`) is an atomic CAS transition
  ``pending -> applied``: the targeted mutation (reassign / candidate_edit /
  merge / split — reusing the T01/T03 CAS semantics), the supersession of
  exactly the invalidated pending suggestions, the result archive
  (``result_json`` — the old affected mapping is superseded/archived, never
  deleted) and the ``RECOMPUTE_OBJECTS`` Job (ONLY where the impact says
  recompute is needed) are committed in ONE transaction.  Unaffected rows
  and files are never touched.

- **Cancel / retry** follow the durable job contracts: a pending correction
  cancels (CAS); an applied correction's recompute Job is cancelled through
  the public JobService (durable) or retried through
  ``JobRepository.create_successor`` (§6.4).

- **Recompute state** (:meth:`recompute_state`) walks the successor chain so
  the API reports the HONEST terminal outcome of the recompute work.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from app.persistence.jobs import JobRepository, StepInput
from app.persistence.models import (
    Job,
    ObjectCorrection,
    ObjectGroupingSuggestion,
    ObjectOccurrence,
    ObjectRole,
    Project,
    VideoItem,
    utc_now,
)
from app.persistence.object_grouping import ObjectGroupingRepository, merge_kind_conflict_message
from app.persistence.object_intelligence import (
    ObjectIntelligenceError,
    ObjectIntelligenceRepository,
    OccurrenceNotFoundError,
    OwnershipMismatchError,
    RoleNotFoundError,
)

__all__ = [
    "CorrectionConflictError",
    "CorrectionImpact",
    "CorrectionNotFoundError",
    "CorrectionRecord",
    "JOB_TYPE_RECOMPUTE_OBJECTS",
    "ObjectCorrectionRepository",
    "RECOMPUTE_STEP_CODE",
]

#: The durable recompute job class (S08-T05 successor/recompute work).
JOB_TYPE_RECOMPUTE_OBJECTS = "RECOMPUTE_OBJECTS"

#: The single sync step that executes the whole recompute pipeline.
RECOMPUTE_STEP_CODE = "recompute"

#: Correction kinds (must match the model CHECK).
CORRECTION_TYPES = ("reassign", "candidate_edit", "merge", "split")

#: Statuses of suggestions that a correction invalidates (pending only —
#: dismissed rows are reviewer decisions and never re-opened).
_INVALIDATABLE_SUGGESTION_STATUSES = ("pending",)

#: Maximum depth when walking the recompute successor chain.
_MAX_SUCCESSOR_DEPTH = 20


class CorrectionNotFoundError(ObjectIntelligenceError):
    """Correction does not exist in the requested workspace."""


class CorrectionConflictError(ObjectIntelligenceError):
    """Correction update conflicts with current durable state."""


@dataclass(frozen=True)
class CorrectionImpact:
    """The pre-confirmation impacted-scope report (read-only computation)."""

    correction_type: str
    affected_role_ids: list[str]
    affected_occurrence_ids: list[str]
    invalidated_suggestion_ids: list[str]
    artifact_role_ids: list[str]
    regenerate_suggestions: bool
    recompute_needed: bool
    counts: dict[str, int]


@dataclass(frozen=True)
class CorrectionRecord:
    """Read model of one durable object correction."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    correction_type: str
    status: str
    request: dict[str, Any]
    impact: dict[str, Any]
    result: dict[str, Any] | None
    recompute_job_id: str | None
    applied_at: datetime | None
    idempotency_key: str | None
    natural_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _map_record(row: ObjectCorrection) -> CorrectionRecord:
    return CorrectionRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        correction_type=row.correction_type,
        status=row.status,
        request=_json(row.request_json),
        impact=_json(row.impact_json),
        result=_json(row.result_json) if row.result_json else None,
        recompute_job_id=row.recompute_job_id,
        applied_at=row.applied_at,
        idempotency_key=row.idempotency_key,
        natural_key=row.natural_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _canonical_request(request: dict[str, Any]) -> str:
    """Content-derived canonical form of a correction request."""
    return json.dumps(request, sort_keys=True, separators=(",", ":"))


class ObjectCorrectionRepository:
    """Durable correction workflow: impact -> create -> confirm -> recompute.

    One repository over the same session as the T01/T03 repos.  All
    mutations validate the ownership chain fail-closed; duplicate and
    concurrent requests replay the SAME correction via the natural key.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── identity helpers ───────────────────────────────────────────────────

    def _assert_ownership(
        self, workspace_id: str, project_id: str, video_item_id: str
    ) -> None:
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise OwnershipMismatchError("project ownership mismatch")
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise OwnershipMismatchError("video ownership mismatch")

    def _correction_row(self, workspace_id: str, correction_id: str) -> ObjectCorrection:
        row = self._session.scalar(
            select(ObjectCorrection).where(
                ObjectCorrection.id == correction_id,
                ObjectCorrection.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise CorrectionNotFoundError(
                f"Correction {correction_id!r} not found in workspace"
            )
        return row

    def _role_row(self, workspace_id: str, role_id: str) -> ObjectRole:
        # populate_existing=True: raw UPDATE ... RETURNING(id) statements
        # (T03 merge) do not synchronize the identity map, and the correction
        # flow may reuse a session that already applied such mutations.  A
        # stale read would wrongly reject a valid correction or miss a
        # terminal status.  Unlike Session.refresh(), a populate_existing
        # SELECT reloads ONLY the column attributes — the loaded
        # ``occurrences`` relationship and its child objects stay intact
        # (refresh() would cascade-expire them via refresh-expire).
        row = self._session.scalar(
            select(ObjectRole)
            .where(
                ObjectRole.id == role_id,
                ObjectRole.workspace_id == workspace_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RoleNotFoundError(f"Role {role_id!r} not found")
        return row

    def _occurrence_row(
        self, workspace_id: str, role_id: str, occurrence_id: str
    ) -> ObjectOccurrence:
        row = self._session.scalar(
            select(ObjectOccurrence)
            .where(
                ObjectOccurrence.id == occurrence_id,
                ObjectOccurrence.workspace_id == workspace_id,
                ObjectOccurrence.role_id == role_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise OccurrenceNotFoundError(
                f"Occurrence {occurrence_id!r} not found on role {role_id!r}"
            )
        return row

    # ── impact (pure read — the pre-confirmation scope report) ─────────────

    def compute_impact(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        correction_type: str,
        request: dict[str, Any],
    ) -> CorrectionImpact:
        """Compute the exact impacted scope for one correction — NO write.

        Affected roles per kind:
          reassign       -> [source_role_id, target_role_id]
          candidate_edit -> [role_id]
          merge          -> [target_role_id, *source_role_ids]
          split          -> [target_role_id]

        Invalidated suggestions: pending suggestions of this video item whose
        role set intersects the affected roles (never dismissed/applied).
        Artifact roles: affected roles produced by a DISCOVER_OBJECTS run
        (``source_job_id`` NOT NULL) — their derived thumbnails/masks are
        recomputed.
        """
        if correction_type not in CORRECTION_TYPES:
            raise ValueError(f"unknown correction type {correction_type!r}")
        self._assert_ownership(workspace_id, project_id, video_item_id)

        affected = self._affected_role_ids(
            workspace_id, video_item_id, correction_type, request
        )
        affected_occurrence_ids = self._affected_occurrence_ids(
            workspace_id, video_item_id, correction_type, request
        )
        for role_id in affected:
            row = self._role_row(workspace_id, role_id)
            if row.video_item_id != video_item_id:
                raise CorrectionConflictError(
                    f"role {role_id!r} does not belong to video item {video_item_id!r}"
                )
            if row.status == "superseded":
                raise CorrectionConflictError(
                    f"role {role_id!r} is terminal (superseded) — it cannot "
                    "be part of a correction"
                )
        if correction_type in ("merge", "split"):
            target = self._role_row(workspace_id, str(request["target_role_id"]))
            self._assert_generation_match(request, target)
            # S08-A01-C1 (F2): the correction/merge PREVIEW must report the
            # same kind-equality conflict as the execute path (apply_merge),
            # BEFORE any correction is created / confirmed.  Read-only: raise
            # CorrectionConflictError (the route maps it to 409) with ZERO
            # durable mutation, using the SINGLE shared invariant so preview
            # and execute can never drift.
            if correction_type == "merge":
                source_ids = [
                    str(sid) for sid in request.get("source_role_ids") or []
                ]
                message = merge_kind_conflict_message(
                    str(request["target_role_id"]),
                    target.kind,
                    [
                        (sid, self._role_row(workspace_id, sid).kind)
                        for sid in source_ids
                    ],
                )
                if message is not None:
                    raise CorrectionConflictError(message)

        invalidated = list(
            self._session.scalars(
                select(ObjectGroupingSuggestion.id).where(
                    ObjectGroupingSuggestion.workspace_id == workspace_id,
                    ObjectGroupingSuggestion.video_item_id == video_item_id,
                    ObjectGroupingSuggestion.status.in_(
                        _INVALIDATABLE_SUGGESTION_STATUSES
                    ),
                )
            ).all()
        )
        invalidated = [
            sid
            for sid in invalidated
            if self._suggestion_intersects(sid, set(affected))
        ]
        if correction_type == "candidate_edit" and request.get("target") == "role":
            # Name/kind/description edits never change occurrence geometry —
            # derived artifacts are NOT recomputed (DESIGN §3).
            artifact_role_ids: list[str] = []
        else:
            artifact_role_ids = [
                role_id
                for role_id in affected
                if self._role_row(workspace_id, role_id).source_job_id is not None
            ]
        regenerate_suggestions = bool(invalidated)
        recompute_needed = regenerate_suggestions or bool(artifact_role_ids)
        total_roles = int(
            self._session.scalar(
                select(func.count(ObjectRole.id)).where(
                    ObjectRole.workspace_id == workspace_id,
                    ObjectRole.video_item_id == video_item_id,
                )
            )
            or 0
        )
        total_occurrences = len(
            self._session.scalars(
                select(ObjectOccurrence.id).where(
                    ObjectOccurrence.workspace_id == workspace_id,
                    ObjectOccurrence.video_item_id == video_item_id,
                )
            ).all()
        )
        total_suggestions = len(
            self._session.scalars(
                select(ObjectGroupingSuggestion.id).where(
                    ObjectGroupingSuggestion.workspace_id == workspace_id,
                    ObjectGroupingSuggestion.video_item_id == video_item_id,
                )
            ).all()
        )
        return CorrectionImpact(
            correction_type=correction_type,
            affected_role_ids=affected,
            affected_occurrence_ids=affected_occurrence_ids,
            invalidated_suggestion_ids=sorted(invalidated),
            artifact_role_ids=artifact_role_ids,
            regenerate_suggestions=regenerate_suggestions,
            recompute_needed=recompute_needed,
            counts={
                "total_roles": total_roles,
                "total_occurrences": total_occurrences,
                "total_suggestions": total_suggestions,
            },
        )

    def _suggestion_intersects(self, suggestion_id: str, affected: set[str]) -> bool:
        row = self._session.scalar(
            select(ObjectGroupingSuggestion.role_ids_json).where(
                ObjectGroupingSuggestion.id == suggestion_id
            )
        )
        if row is None:
            return False
        try:
            role_ids = json.loads(row)
        except (TypeError, json.JSONDecodeError):
            return False
        return bool(affected.intersection(role_ids))

    def _affected_role_ids(
        self,
        workspace_id: str,
        video_item_id: str,
        correction_type: str,
        request: dict[str, Any],
    ) -> list[str]:
        if correction_type == "reassign":
            return sorted({str(request["source_role_id"]), str(request["target_role_id"])})
        if correction_type == "candidate_edit":
            return [str(request["role_id"])]
        if correction_type == "merge":
            return sorted({str(request["target_role_id"]), *map(str, request["source_role_ids"])})
        if correction_type == "split":
            return [str(request["target_role_id"])]
        raise ValueError(f"unknown correction type {correction_type!r}")

    def _affected_occurrence_ids(
        self,
        workspace_id: str,
        video_item_id: str,
        correction_type: str,
        request: dict[str, Any],
    ) -> list[str]:
        if correction_type == "reassign":
            occ = self._occurrence_row(
                workspace_id, str(request["source_role_id"]), str(request["occurrence_id"])
            )
            if occ.video_item_id != video_item_id:
                raise CorrectionConflictError(
                    "occurrence does not belong to this video item"
                )
            return [occ.id]
        if correction_type == "candidate_edit" and request.get("target") == "occurrence":
            occ = self._occurrence_row(
                workspace_id, str(request["role_id"]), str(request["occurrence_id"])
            )
            if occ.video_item_id != video_item_id:
                raise CorrectionConflictError(
                    "occurrence does not belong to this video item"
                )
            return [occ.id]
        if correction_type == "merge":
            occ_ids = self._session.scalars(
                select(ObjectOccurrence.id).where(
                    ObjectOccurrence.workspace_id == workspace_id,
                    ObjectOccurrence.role_id.in_(
                        [str(rid) for rid in request["source_role_ids"]]
                    ),
                )
            ).all()
            return sorted(occ_ids)
        if correction_type == "split":
            original = self._role_row(workspace_id, str(request["original_role_id"]))
            target_id = str(request["target_role_id"])
            if original.supersedes_role_id != target_id:
                return []
            # The exact transferred set comes from the merge audit row — the
            # preview never approximates.
            from app.persistence.models import RoleOperation

            op = self._session.scalar(
                select(RoleOperation).where(
                    RoleOperation.workspace_id == workspace_id,
                    RoleOperation.operation_type == "merge",
                    RoleOperation.target_role_id == target_id,
                ).order_by(
                    RoleOperation.created_at.desc(), RoleOperation.id.desc()
                )
            )
            if op is None:
                return []
            try:
                transfer = json.loads(op.transferred_occurrence_ids_json)
            except (TypeError, json.JSONDecodeError):
                return []
            for entry in transfer:
                if str(entry.get("role_id")) == original.id:
                    return sorted(str(occ) for occ in entry.get("occurrence_ids", []))
            return []
        return []

    def _assert_generation_match(
        self, request: dict[str, Any], target: ObjectRole
    ) -> None:
        generation = str(request.get("generation") or "")
        if not generation:
            raise CorrectionConflictError("correction requires the source generation")
        if target.source_generation != generation:
            raise CorrectionConflictError(
                "target role does not belong to the requested source generation"
            )

    # ── create (pending correction + archived impact) ──────────────────────

    @staticmethod
    def natural_key(
        correction_type: str, video_item_id: str, request: dict[str, Any]
    ) -> str:
        return (
            f"CORRECTION:{correction_type}:{video_item_id}:"
            f"{_sha256(_canonical_request(request))[:40]}"
        )

    def create_correction(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        correction_type: str,
        request: dict[str, Any],
        impact: CorrectionImpact,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[CorrectionRecord, bool]:
        """Create the durable pending correction (natural-key idempotent)."""
        self._assert_ownership(workspace_id, project_id, video_item_id)
        natural_key = self.natural_key(correction_type, video_item_id, request)
        existing = self._session.scalar(
            select(ObjectCorrection).where(
                ObjectCorrection.workspace_id == workspace_id,
                ObjectCorrection.natural_key == natural_key,
            )
        )
        if existing is not None:
            self._assert_equivalent(existing, project_id, video_item_id, correction_type, request)
            return _map_record(existing), False
        row = ObjectCorrection(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            correction_type=correction_type,
            status="pending",
            request_json=_canonical_request(request),
            impact_json=json.dumps(self._impact_payload(impact), sort_keys=True),
            idempotency_key=idempotency_key,
            natural_key=natural_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalar(
                select(ObjectCorrection).where(
                    ObjectCorrection.workspace_id == workspace_id,
                    ObjectCorrection.natural_key == natural_key,
                )
            )
            if existing is not None:
                self._assert_equivalent(
                    existing, project_id, video_item_id, correction_type, request
                )
                return _map_record(existing), False
            raise
        return _map_record(row), True

    @staticmethod
    def _assert_equivalent(
        existing: ObjectCorrection,
        project_id: str,
        video_item_id: str,
        correction_type: str,
        request: dict[str, Any],
    ) -> None:
        if (
            existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.correction_type != correction_type
            or existing.request_json != _canonical_request(request)
        ):
            raise CorrectionConflictError(
                f"natural key {existing.natural_key!r} is already bound to a "
                "different correction request"
            )

    @staticmethod
    def _impact_payload(impact: CorrectionImpact) -> dict[str, Any]:
        return {
            "correction_type": impact.correction_type,
            "affected_role_ids": impact.affected_role_ids,
            "affected_occurrence_ids": impact.affected_occurrence_ids,
            "invalidated_suggestion_ids": impact.invalidated_suggestion_ids,
            "artifact_role_ids": impact.artifact_role_ids,
            "regenerate_suggestions": impact.regenerate_suggestions,
            "recompute_needed": impact.recompute_needed,
            "counts": impact.counts,
        }

    # ── confirm (CAS: mutation + supersession + recompute job, ONE txn) ────

    def confirm_correction(
        self,
        workspace_id: str,
        correction_id: str,
        revision: int,
        *,
        managed_root: str | None = None,
    ) -> tuple[CorrectionRecord, bool]:
        """Apply a pending correction exactly once (atomic CAS).

        Order inside the transaction: targeted mutation (T01/T03 CAS
        semantics) -> supersede the invalidated pending suggestions ->
        create the RECOMPUTE_OBJECTS Job (only where the impact requires it)
        -> CAS transition ``pending -> applied`` with the result archive.
        Any failure rolls the whole transaction back (the route owns the
        rollback), so a failed confirm leaves ZERO durable effects.
        """
        row = self._correction_row(workspace_id, correction_id)
        if row.status == "applied":
            # Restart/duplicate confirm replays the recorded result.
            return _map_record(row), False
        if row.status == "cancelled":
            raise CorrectionConflictError(
                "correction was cancelled; it can never be confirmed"
            )
        request = _json(row.request_json)
        impact = _json(row.impact_json)

        result, recompute_job_id = self._apply_mutation(
            workspace_id, row, request, impact, managed_root=managed_root
        )
        now = utc_now()
        stmt = (
            update(ObjectCorrection)
            .where(
                ObjectCorrection.id == correction_id,
                ObjectCorrection.workspace_id == workspace_id,
                ObjectCorrection.revision == revision,
                ObjectCorrection.status == "pending",
            )
            .values(
                status="applied",
                applied_at=now,
                updated_at=now,
                revision=ObjectCorrection.revision + 1,
                result_json=json.dumps(result, sort_keys=True),
                recompute_job_id=recompute_job_id,
            )
            .returning(ObjectCorrection)
        )
        try:
            after = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.scalar(
                select(ObjectCorrection)
                .where(
                    ObjectCorrection.id == correction_id,
                    ObjectCorrection.workspace_id == workspace_id,
                )
                .execution_options(populate_existing=True)
            )
            if latest is not None and latest.status == "applied":
                return _map_record(latest), False
            current_revision = latest.revision if latest is not None else None
            raise CorrectionConflictError(
                f"stale revision {revision}; current revision is {current_revision}"
            ) from None
        return _map_record(after), True

    def _apply_mutation(
        self,
        workspace_id: str,
        row: ObjectCorrection,
        request: dict[str, Any],
        impact: dict[str, Any],
        *,
        managed_root: str | None,
    ) -> tuple[dict[str, Any], str | None]:
        """Apply the targeted mutation + supersession; return (result, job_id)."""
        kind = row.correction_type
        if kind == "reassign":
            result = self._apply_reassign(workspace_id, request)
        elif kind == "candidate_edit":
            result = self._apply_candidate_edit(workspace_id, request)
        elif kind == "merge":
            result = self._apply_merge(workspace_id, request)
        elif kind == "split":
            result = self._apply_split(workspace_id, request)
        else:  # pragma: no cover - guarded by the model CHECK
            raise CorrectionConflictError(f"unknown correction type {kind!r}")

        invalidated = list(impact.get("invalidated_suggestion_ids") or [])
        self._supersede_suggestions(workspace_id, invalidated)

        extra_roles: list[str] = []
        if row.correction_type == "split" and result.get("created_role_id"):
            # The split's NEW role only exists at confirm time; it joins the
            # recompute scope so its derived artifacts regenerate too
            # (DESIGN §3 / §5).
            extra_roles = [str(result["created_role_id"])]

        recompute_job_id: str | None = None
        if bool(impact.get("recompute_needed")) or extra_roles:
            recompute_job_id = self._create_recompute_job(
                workspace_id,
                row,
                request,
                impact,
                managed_root=managed_root,
                extra_roles=extra_roles,
            )
        return result, recompute_job_id

    def _supersede_suggestions(
        self, workspace_id: str, suggestion_ids: list[str]
    ) -> None:
        """Traceably supersede exactly the invalidated pending suggestions."""
        if not suggestion_ids:
            return
        now = utc_now()
        for suggestion_id in suggestion_ids:
            self._session.execute(
                update(ObjectGroupingSuggestion)
                .where(
                    ObjectGroupingSuggestion.id == suggestion_id,
                    ObjectGroupingSuggestion.workspace_id == workspace_id,
                    ObjectGroupingSuggestion.status.in_(
                        _INVALIDATABLE_SUGGESTION_STATUSES
                    ),
                )
                .values(
                    status="superseded",
                    revision=ObjectGroupingSuggestion.revision + 1,
                    updated_at=now,
                    natural_key=None,
                )
            )

    def _create_recompute_job(
        self,
        workspace_id: str,
        row: ObjectCorrection,
        request: dict[str, Any],
        impact: dict[str, Any],
        *,
        managed_root: str | None,
        extra_roles: list[str] | None = None,
    ) -> str:
        extra = extra_roles or []
        # Recompute scope = the affected roles that remain ACTIVE after the
        # mutation (a merge supersedes its sources — their artifacts stay as
        # immutable historical evidence and are never recomputed) plus the
        # roles the mutation created (split's new role).
        recompute_ids = sorted(
            {
                role_id
                for role_id in [
                    *list(impact.get("affected_role_ids") or []),
                    *extra,
                ]
                if self._role_row(workspace_id, role_id).status
                in ("suggested", "confirmed")
            }
        )
        if row.correction_type == "candidate_edit" and request.get("target") == "role":
            # A name/kind/description edit never changes occurrence geometry —
            # derived artifacts are NOT recomputed (DESIGN §3).
            artifact_ids: list[str] = []
        else:
            artifact_ids = [
                role_id
                for role_id in recompute_ids
                if self._role_row(workspace_id, role_id).source_job_id is not None
            ]
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "project_id": row.project_id,
            "video_item_id": row.video_item_id,
            "generation": str(request.get("generation") or ""),
            "correction_id": row.id,
            "correction_type": row.correction_type,
            "affected_role_ids": recompute_ids,
            "artifact_role_ids": artifact_ids,
            "regenerate_suggestions": bool(impact.get("regenerate_suggestions")),
        }
        if managed_root is not None:
            manifest["managed_root"] = managed_root
        job = JobRepository(self._session).create_job(
            workspace_id=workspace_id,
            job_type=JOB_TYPE_RECOMPUTE_OBJECTS,
            owner_type="video_item",
            owner_id=row.video_item_id,
            input_manifest=manifest,
            idempotency_key=f"{JOB_TYPE_RECOMPUTE_OBJECTS}:correction:{row.id}",
            input_generation=str(request.get("generation") or "1"),
            steps=[StepInput(step_code=RECOMPUTE_STEP_CODE, position=0, step_type="sync")],
            actor="api",
        )
        return job.id

    # ── targeted mutations (T01/T03 CAS semantics; content never rewritten) ─

    def _apply_reassign(
        self, workspace_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Move one occurrence to another role (content untouched)."""
        occurrence_id = str(request["occurrence_id"])
        source_id = str(request["source_role_id"])
        target_id = str(request["target_role_id"])
        if source_id == target_id:
            raise CorrectionConflictError(
                "reassign requires two different roles"
            )
        occ_revision = int(request["occurrence_revision"])
        source = self._role_row(workspace_id, source_id)
        target = self._role_row(workspace_id, target_id)
        if source.status == "superseded" or target.status == "superseded":
            raise CorrectionConflictError(
                "reassign roles must both be active (not superseded)"
            )
        if source.video_item_id != target.video_item_id:
            raise CorrectionConflictError(
                "reassign roles must belong to the same video item"
            )
        if source.source_generation != target.source_generation:
            raise CorrectionConflictError(
                "reassign roles must share the same source generation"
            )
        occ = self._occurrence_row(workspace_id, source_id, occurrence_id)
        collision = self._session.scalar(
            select(ObjectOccurrence.id).where(
                ObjectOccurrence.role_id == target_id,
                ObjectOccurrence.scene_id == occ.scene_id,
                ObjectOccurrence.frame_index == occ.frame_index,
            )
        )
        if collision is not None:
            raise CorrectionConflictError(
                "occurrence collision at target role "
                f"(scene {occ.scene_id}, frame {occ.frame_index}) — reassign "
                "would duplicate evidence"
            )
        now = utc_now()
        moved = self._session.execute(
            update(ObjectOccurrence)
            .where(
                ObjectOccurrence.id == occurrence_id,
                ObjectOccurrence.workspace_id == workspace_id,
                ObjectOccurrence.role_id == source_id,
                ObjectOccurrence.revision == occ_revision,
            )
            .values(
                role_id=target_id,
                revision=ObjectOccurrence.revision + 1,
                updated_at=now,
            )
            .returning(ObjectOccurrence)
        ).scalar_one_or_none()
        if moved is None:
            latest = self._session.scalar(
                select(ObjectOccurrence)
                .where(
                    ObjectOccurrence.id == occurrence_id,
                    ObjectOccurrence.workspace_id == workspace_id,
                )
                .execution_options(populate_existing=True)
            )
            current = latest.revision if latest is not None else None
            raise CorrectionConflictError(
                f"stale occurrence revision {occ_revision}; current is {current}"
            )
        source_after = self._bump_role_revision(workspace_id, source_id, source.revision)
        target_after = self._bump_role_revision(workspace_id, target_id, target.revision)
        return {
            "occurrence_id": occurrence_id,
            "from_role_id": source_id,
            "to_role_id": target_id,
            "source_role_revision_after": source_after.revision,
            "target_role_revision_after": target_after.revision,
        }

    def _bump_role_revision(
        self, workspace_id: str, role_id: str, revision: int
    ) -> ObjectRole:
        after = self._session.execute(
            update(ObjectRole)
            .where(
                ObjectRole.id == role_id,
                ObjectRole.workspace_id == workspace_id,
                ObjectRole.revision == revision,
                ObjectRole.status != "superseded",
            )
            .values(revision=ObjectRole.revision + 1, updated_at=utc_now())
            .returning(ObjectRole)
        ).scalar_one_or_none()
        if after is None:
            raise CorrectionConflictError(
                f"role {role_id!r} changed concurrently (revision {revision} is stale)"
            )
        return after

    def _apply_candidate_edit(
        self, workspace_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        target = str(request.get("target") or "role")
        if target == "role":
            role_id = str(request["role_id"])
            record = ObjectIntelligenceRepository(self._session).update_role(
                workspace_id,
                role_id,
                int(request["role_revision"]),
                name=request.get("name"),
                kind=request.get("role_kind"),
                description=request.get("description"),
            )
            return {
                "edited": "role",
                "role_id": role_id,
                "fields": sorted(
                    k for k in ("name", "role_kind", "description") if k in request
                ),
                "revision_after": record.revision,
            }
        if target == "occurrence":
            role_id = str(request["role_id"])
            occurrence_id = str(request["occurrence_id"])
            bbox = request.get("bbox")
            reasons = request.get("reasons")
            occ_record = ObjectIntelligenceRepository(self._session).update_occurrence(
                workspace_id,
                role_id,
                occurrence_id,
                int(request["occurrence_revision"]),
                confidence=request.get("confidence"),
                review_state=request.get("review_state"),
                reasons=list(reasons) if isinstance(reasons, list) else None,
                bbox_x=int(bbox["x"]) if isinstance(bbox, dict) else None,
                bbox_y=int(bbox["y"]) if isinstance(bbox, dict) else None,
                bbox_w=int(bbox["width"]) if isinstance(bbox, dict) else None,
                bbox_h=int(bbox["height"]) if isinstance(bbox, dict) else None,
            )
            return {
                "edited": "occurrence",
                "role_id": role_id,
                "occurrence_id": occurrence_id,
                "fields": sorted(
                    k
                    for k in ("bbox", "confidence", "review_state", "reasons")
                    if k in request
                ),
                "revision_after": occ_record.revision,
            }
        raise CorrectionConflictError(
            f"unknown candidate_edit target {target!r} (expected role|occurrence)"
        )

    def _apply_merge(self, workspace_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._role_row(workspace_id, str(request["target_role_id"]))
        for source_id in request["source_role_ids"]:
            self._role_row(workspace_id, str(source_id))
        operation, _target, _created = ObjectGroupingRepository(
            self._session
        ).apply_merge(
            workspace_id,
            self._project_id_of(workspace_id, str(request["target_role_id"])),
            self._video_of(workspace_id, str(request["target_role_id"])),
            str(request["target_role_id"]),
            [str(rid) for rid in request["source_role_ids"]],
            int(request["target_revision"]),
            suggestion_id=request.get("suggestion_id"),
            idempotency_key=None,
            note=request.get("note"),
        )
        return {
            "operation_id": operation.id,
            "operation_type": "merge",
            "target_role_id": str(request["target_role_id"]),
        }

    def _apply_split(self, workspace_id: str, request: dict[str, Any]) -> dict[str, Any]:
        # Refresh every role the T03 apply_split re-reads via session.get so
        # its lineage validation sees the durable state (identity-map
        # staleness from the seeding merge would otherwise fail it closed).
        self._role_row(workspace_id, str(request["target_role_id"]))
        self._role_row(workspace_id, str(request["original_role_id"]))
        operation, created_role, _created = ObjectGroupingRepository(
            self._session
        ).apply_split(
            workspace_id,
            self._project_id_of(workspace_id, str(request["target_role_id"])),
            self._video_of(workspace_id, str(request["target_role_id"])),
            str(request["target_role_id"]),
            str(request["original_role_id"]),
            int(request["target_revision"]),
            idempotency_key=None,
            note=request.get("note"),
        )
        return {
            "operation_id": operation.id,
            "operation_type": "split",
            "target_role_id": str(request["target_role_id"]),
            "created_role_id": created_role.id,
        }

    def _project_id_of(self, workspace_id: str, role_id: str) -> str:
        return self._role_row(workspace_id, role_id).project_id

    def _video_of(self, workspace_id: str, role_id: str) -> str:
        return self._role_row(workspace_id, role_id).video_item_id

    # ── cancel / retry (durable job contracts) ─────────────────────────────

    def cancel_correction(
        self, workspace_id: str, correction_id: str, revision: int
    ) -> CorrectionRecord:
        """Cancel a PENDING correction (CAS; state-idempotent replay)."""
        row = self._correction_row(workspace_id, correction_id)
        if row.status == "cancelled":
            return _map_record(row)
        if row.status == "applied":
            raise CorrectionConflictError(
                "an applied correction cannot be cancelled; cancel its "
                "recompute job instead"
            )
        now = utc_now()
        stmt = (
            update(ObjectCorrection)
            .where(
                ObjectCorrection.id == correction_id,
                ObjectCorrection.workspace_id == workspace_id,
                ObjectCorrection.revision == revision,
                ObjectCorrection.status == "pending",
            )
            .values(
                status="cancelled",
                revision=ObjectCorrection.revision + 1,
                updated_at=now,
            )
            .returning(ObjectCorrection)
        )
        try:
            after = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.scalar(
                select(ObjectCorrection)
                .where(
                    ObjectCorrection.id == correction_id,
                    ObjectCorrection.workspace_id == workspace_id,
                )
                .execution_options(populate_existing=True)
            )
            current = latest.revision if latest is not None else None
            raise CorrectionConflictError(
                f"stale revision {revision}; current revision is {current}"
            ) from None
        return _map_record(after)

    def create_recompute_successor(
        self, workspace_id: str, correction_id: str
    ) -> str:
        """Retry the recompute work: successor of the latest terminal Job (§6.4).

        Idempotent: an existing successor for the same terminal predecessor
        is reused (never a second successor).
        """
        row = self._correction_row(workspace_id, correction_id)
        if row.status != "applied" or row.recompute_job_id is None:
            raise CorrectionConflictError(
                "correction has no recompute job to retry"
            )
        latest_id, state = self._walk_recompute_chain(workspace_id, row.recompute_job_id)
        if latest_id is None:
            raise CorrectionConflictError("recompute job is missing")
        if state not in ("failed", "cancelled"):
            raise CorrectionConflictError(
                f"recompute job {latest_id!r} is {state}; only terminal "
                "failed/cancelled recompute jobs can be retried"
            )
        from app.persistence.jobs import (
            IdempotencyKeyInUse,
            InvalidStateTransition,
            JobNotFoundError,
        )

        repo = JobRepository(self._session)
        predecessor = repo.get_job(latest_id)
        try:
            successor = repo.create_successor(
                predecessor_job_id=latest_id,
                input_manifest=predecessor.input_manifest,
                steps=[
                    StepInput(step_code=RECOMPUTE_STEP_CODE, position=0, step_type="sync")
                ],
            )
        except IdempotencyKeyInUse as err:
            # A successor already exists (concurrent retry won) — reuse it.
            if getattr(err, "job_id", None):
                return str(err.job_id)
            raise CorrectionConflictError(str(err)) from err
        except (JobNotFoundError, InvalidStateTransition) as err:
            raise CorrectionConflictError(str(err)) from err
        return successor.id

    def _walk_recompute_chain(
        self, workspace_id: str, job_id: str
    ) -> tuple[str | None, str | None]:
        """Follow the successor chain from *job_id* to the newest Job."""
        current: str | None = job_id
        state: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_SUCCESSOR_DEPTH):
            if current is None or current in seen:
                break
            seen.add(current)
            row = self._session.execute(
                select(Job.state).where(
                    Job.id == current, Job.workspace_id == workspace_id
                )
            ).first()
            if row is None:
                break
            state = str(row[0])
            successor = self._session.execute(
                select(Job.id).where(Job.predecessor_job_id == current)
            ).first()
            if successor is None:
                break
            current = str(successor[0])
        return current, state

    def recompute_state(
        self, workspace_id: str, correction_id: str
    ) -> dict[str, Any]:
        """The honest recompute outcome: latest Job state + progress/error."""
        row = self._correction_row(workspace_id, correction_id)
        if row.status != "applied" or row.recompute_job_id is None:
            return {
                "recompute_needed": False,
                "job_id": None,
                "status": None,
                "progress": None,
                "error": None,
            }
        job_id, state = self._walk_recompute_chain(workspace_id, row.recompute_job_id)
        progress: float | None = None
        error: str | None = None
        if job_id is not None:
            job = self._session.get(Job, job_id)
            if job is not None and job.workspace_id == workspace_id:
                progress = job.progress
                try:
                    raw_error = json.loads(job.error_json or "{}")
                except (TypeError, json.JSONDecodeError):
                    raw_error = {}
                if isinstance(raw_error, dict):
                    error = str(raw_error.get("message") or "") or None
        return {
            "recompute_needed": True,
            "job_id": job_id,
            "status": state,
            "progress": progress,
            "error": error,
        }

    # ── read-only accessors ────────────────────────────────────────────────

    def get_correction(
        self, workspace_id: str, correction_id: str
    ) -> CorrectionRecord:
        return _map_record(self._correction_row(workspace_id, correction_id))

    def list_corrections(
        self,
        workspace_id: str,
        *,
        video_item_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CorrectionRecord], int]:
        filters = [ObjectCorrection.workspace_id == workspace_id]
        if video_item_id is not None:
            filters.append(ObjectCorrection.video_item_id == video_item_id)
        total = int(
            self._session.scalar(
                select(func.count(ObjectCorrection.id)).where(*filters)
            )
            or 0
        )
        rows = self._session.scalars(
            select(ObjectCorrection)
            .where(*filters)
            .order_by(ObjectCorrection.created_at.desc(), ObjectCorrection.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_map_record(row) for row in rows], total

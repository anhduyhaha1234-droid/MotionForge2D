"""Durable S12 export persistence: run/chunk ownership + atomic claim/fence (S12-T03A).

Implements the s12-export-v1 §6 ownership fence over the S12 ORM entities in
:mod:`app.persistence.models` (``S12ExportRun`` / ``S12ExportChunk`` /
``S12ExportLease``):

- :class:`S12ExportRepository.create_run` pins the FULL export identity at
  creation (frozen ``ApplyCheckpoint`` pin + frozen structural-lock manifest
  pin + frozen T01 profile snapshot + render-plan identity) and fails closed
  on wrong/stale/ambiguous identity.
- :meth:`S12ExportRepository.claim_run` is the single-winner atomic claim:
  exactly one caller wins the ``s12_export_lease`` INSERT; losers fail
  closed.  An expired/released lease may be re-claimed via a guarded CAS on
  ``lease_version`` with a fresh fence token.
- Every worker write carries the lease ``fence_token``; a mismatch raises
  :class:`FencedWorkerError` so a fenced worker can never mutate the run.
- Equivalent replay under the same ``idempotency_key`` returns the existing
  row; a materially different payload raises :class:`IdempotencyConflictError`.
- The lease row is retired, never deleted, so a process restart replays from
  the current lease/run state (same transaction boundaries, no in-memory
  ownership).

All writes go through the caller's session; the caller owns commit/rollback.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.models import (
    S12_EXPORT_CHUNK_STATES,
    S12_EXPORT_RUN_STATUSES,
    ApplyCheckpoint,
    S12ExportChunk,
    S12ExportLease,
    S12ExportRun,
    StructuralLockManifest,
)

__all__ = [
    "FENCED_WORKER_ERROR_CODE",
    "IDEMPOTENCY_CONFLICT_CODE",
    "LEASE_CONFLICT_CODE",
    "S12_EXPORT_TERMINAL_STATUSES",
    "S12ExportError",
    "FencedWorkerError",
    "IdempotencyConflictError",
    "LeaseConflictError",
    "LeaseNotFoundError",
    "RunNotFoundError",
    "StaleIdentityError",
    "S12ExportRepository",
    "ChunkRecord",
    "LeaseRecord",
    "RunRecord",
]

#: Machine-readable error code for fence-token rejections.
FENCED_WORKER_ERROR_CODE = "FENCED_WORKER"
#: Machine-readable error code for live-lease claim conflicts.
LEASE_CONFLICT_CODE = "LEASE_CONFLICT"
#: Machine-readable error code for materially-different idempotent replays.
IDEMPOTENCY_CONFLICT_CODE = "IDEMPOTENCY_CONFLICT"

#: Terminal run statuses — no further worker writes once reached.
S12_EXPORT_TERMINAL_STATUSES = ("completed", "failed", "cancelled")

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class S12ExportError(Exception):
    """Base error for the S12 export persistence domain."""


class RunNotFoundError(S12ExportError):
    """Unknown export run id."""


class StaleIdentityError(S12ExportError):
    """The caller's frozen identity pins do not match the pinned run."""


class LeaseConflictError(S12ExportError):
    """Another worker holds the live lease — exactly one winner per claim."""

    def __init__(self, message: str, *, run_id: str = "") -> None:
        super().__init__(message)
        self.run_id = run_id


class LeaseNotFoundError(S12ExportError):
    """No lease row exists for the run."""


class FencedWorkerError(S12ExportError):
    """The worker's fence token no longer matches — the worker was fenced."""

    def __init__(self, message: str, *, run_id: str = "") -> None:
        super().__init__(message)
        self.run_id = run_id


class IdempotencyConflictError(S12ExportError):
    """Same idempotency key replayed with a materially different payload."""


@dataclass(frozen=True)
class RunRecord:
    """Immutable snapshot of an export run row."""

    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    checkpoint_id: str
    checkpoint_hash: str
    checkpoint_revision: int
    manifest_id: str
    manifest_hash: str
    manifest_generation: str
    profile_id: str
    profile_dims: str
    profile_codec: str
    plan_id: str
    plan_hash: str
    status: str
    frame_count: int
    attempt: int
    natural_key: str | None
    idempotency_key: str | None
    revision: int


@dataclass(frozen=True)
class ChunkRecord:
    """Immutable snapshot of an export chunk row."""

    id: str
    workspace_id: str
    run_id: str
    chunk_index: int
    order_index: int
    core_start_frame: int
    core_end_frame: int
    overlap_before: int
    overlap_after: int
    content_hash: str
    state: str
    attempt: int
    verified: int
    revision: int


@dataclass(frozen=True)
class LeaseRecord:
    """Immutable snapshot of an export lease row."""

    run_id: str
    worker_id: str
    lease_version: int
    fence_token: str
    acquired_at: datetime
    expires_at: datetime
    heartbeat_at: datetime
    ttl_seconds: int


def _map_run(row: S12ExportRun) -> RunRecord:
    return RunRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        checkpoint_id=row.checkpoint_id,
        checkpoint_hash=row.checkpoint_hash,
        checkpoint_revision=row.checkpoint_revision,
        manifest_id=row.manifest_id,
        manifest_hash=row.manifest_hash,
        manifest_generation=row.manifest_generation,
        profile_id=row.profile_id,
        profile_dims=row.profile_dims,
        profile_codec=row.profile_codec,
        plan_id=row.plan_id,
        plan_hash=row.plan_hash,
        status=row.status,
        frame_count=row.frame_count,
        attempt=row.attempt,
        natural_key=row.natural_key,
        idempotency_key=row.idempotency_key,
        revision=row.revision,
    )


def _map_chunk(row: S12ExportChunk) -> ChunkRecord:
    return ChunkRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        chunk_index=row.chunk_index,
        order_index=row.order_index,
        core_start_frame=row.core_start_frame,
        core_end_frame=row.core_end_frame,
        overlap_before=row.overlap_before,
        overlap_after=row.overlap_after,
        content_hash=row.content_hash,
        state=row.state,
        attempt=row.attempt,
        verified=row.verified,
        revision=row.revision,
    )


def _lease_record(row: S12ExportLease) -> LeaseRecord:
    return LeaseRecord(
        run_id=row.run_id,
        worker_id=row.worker_id,
        lease_version=row.lease_version,
        fence_token=row.fence_token,
        acquired_at=row.acquired_at,
        expires_at=row.expires_at,
        heartbeat_at=row.heartbeat_at,
        ttl_seconds=row.ttl_seconds,
    )


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_natural_key(
    *,
    project_id: str,
    video_item_id: str,
    profile_id: str,
    plan_hash: str,
    checkpoint_hash: str,
) -> str:
    """Content-derived lineage identity for an export run (≤255 chars)."""
    raw = "|".join((project_id, video_item_id, profile_id, plan_hash, checkpoint_hash))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_hex64(value: str, field: str) -> None:
    if not _HEX64_RE.match(value or ""):
        raise S12ExportError(f"{field} must be a lowercase 64-hex sha256")


class S12ExportRepository:
    """Ownership + claim/fence repository over the S12 export tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Run creation (identity pin, idempotent) ──────────────────────────

    def create_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        checkpoint_id: str,
        checkpoint_hash: str,
        checkpoint_revision: int,
        manifest_id: str,
        manifest_hash: str,
        manifest_generation: str,
        profile_id: str,
        plan_id: str,
        plan_hash: str,
        frame_count: int,
        chunk_config: dict[str, Any],
        idempotency_key: str | None = None,
        natural_key: str | None = None,
    ) -> tuple[RunRecord, bool]:
        """Pin the FULL export identity and create the run (idempotent).

        The frozen pins are verified read-only against the live rows FIRST
        (fail-closed on wrong/stale/ambiguous identity — s12-export-v1 §4):
        the ``ApplyCheckpoint`` row must exist in the workspace with equal
        hash and ``reskin_config_revision``, and belong to the same project;
        the structural-lock manifest must resolve in the same workspace with
        equal hash, same video + project, equal generation and draft/active
        status.  Returns ``(record, created)`` — ``created=False`` on
        equivalent idempotent replay.
        """
        _require_hex64(checkpoint_hash, "checkpoint_hash")
        _require_hex64(manifest_hash, "manifest_hash")
        _require_hex64(plan_id, "plan_id")
        _require_hex64(plan_hash, "plan_hash")
        if checkpoint_revision < 1:
            raise S12ExportError("checkpoint_revision must be >= 1")
        if frame_count < 1:
            raise S12ExportError("frame_count must be >= 1")
        if not profile_id or len(profile_id) > 64:
            raise S12ExportError("profile_id must be 1..64 chars")
        if not manifest_generation or len(manifest_generation) > 64:
            raise S12ExportError("manifest_generation must be 1..64 chars")

        checkpoint = self._session.get(ApplyCheckpoint, checkpoint_id)
        if checkpoint is None:
            raise StaleIdentityError(f"checkpoint {checkpoint_id!r} not found")
        if checkpoint.workspace_id != workspace_id:
            raise StaleIdentityError("checkpoint is outside this workspace")
        if checkpoint.checkpoint_hash != checkpoint_hash:
            raise StaleIdentityError("checkpoint hash mismatch (stale pin)")
        if checkpoint.reskin_config_revision != checkpoint_revision:
            raise StaleIdentityError("checkpoint revision mismatch (stale pin)")
        if checkpoint.project_id != project_id:
            raise StaleIdentityError(
                "checkpoint belongs to a different project (cross-project)"
            )

        manifest = self._session.get(StructuralLockManifest, manifest_id)
        if manifest is None:
            raise StaleIdentityError(f"manifest {manifest_id!r} not found")
        if manifest.workspace_id != workspace_id:
            raise StaleIdentityError("manifest is outside this workspace")
        if manifest.manifest_hash != manifest_hash:
            raise StaleIdentityError("manifest hash mismatch (stale pin)")
        if manifest.video_item_id != video_item_id or manifest.project_id != project_id:
            raise StaleIdentityError("manifest video/project mismatch (stale pin)")
        if manifest.source_generation != manifest_generation:
            raise StaleIdentityError("manifest generation mismatch (stale pin)")
        if manifest.status not in ("draft", "active"):
            raise StaleIdentityError(
                f"manifest status {manifest.status!r} is not claimable"
            )

        profile_dims, profile_codec = _frozen_profile_dims(profile_id)
        derived_natural = natural_key or compute_natural_key(
            project_id=project_id,
            video_item_id=video_item_id,
            profile_id=profile_id,
            plan_hash=plan_hash,
            checkpoint_hash=checkpoint_hash,
        )

        row = S12ExportRun(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            checkpoint_id=checkpoint_id,
            checkpoint_hash=checkpoint_hash,
            checkpoint_revision=checkpoint_revision,
            manifest_id=manifest_id,
            manifest_hash=manifest_hash,
            manifest_generation=manifest_generation,
            profile_id=profile_id,
            profile_dims=profile_dims,
            profile_codec=profile_codec,
            plan_id=plan_id,
            plan_hash=plan_hash,
            status="pending",
            frame_count=frame_count,
            chunk_config_json=_canonical_json(chunk_config),
            attempt=1,
            natural_key=derived_natural,
            idempotency_key=idempotency_key,
        )
        try:
            with self._session.no_autoflush:
                self._session.add(row)
                self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            return self._replay_after_conflict(
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                checkpoint_hash=checkpoint_hash,
                manifest_hash=manifest_hash,
                manifest_generation=manifest_generation,
                profile_id=profile_id,
                plan_id=plan_id,
                plan_hash=plan_hash,
                idempotency_key=idempotency_key,
                natural_key=derived_natural,
                cause=err,
            )
        return _map_run(row), True

    def _replay_after_conflict(
        self,
        *,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        checkpoint_hash: str,
        manifest_hash: str,
        manifest_generation: str,
        profile_id: str,
        plan_id: str,
        plan_hash: str,
        idempotency_key: str | None,
        natural_key: str,
        cause: IntegrityError,
    ) -> tuple[RunRecord, bool]:
        """Resolve a create_run uniqueness conflict: replay or fail-closed."""
        existing: S12ExportRun | None = None
        if idempotency_key is not None:
            existing = self._session.scalar(
                select(S12ExportRun).where(
                    S12ExportRun.workspace_id == workspace_id,
                    S12ExportRun.idempotency_key == idempotency_key,
                )
            )
        if existing is None:
            existing = self._session.scalar(
                select(S12ExportRun).where(
                    S12ExportRun.workspace_id == workspace_id,
                    S12ExportRun.natural_key == natural_key,
                )
            )
        if existing is None:
            raise S12ExportError(
                f"export run creation conflict resolved to no row: {cause.orig}"
            ) from cause
        same_identity = (
            existing.project_id == project_id
            and existing.video_item_id == video_item_id
            and existing.checkpoint_hash == checkpoint_hash
            and existing.manifest_hash == manifest_hash
            and existing.manifest_generation == manifest_generation
            and existing.profile_id == profile_id
            and existing.plan_id == plan_id
            and existing.plan_hash == plan_hash
        )
        if not same_identity:
            raise IdempotencyConflictError(
                "idempotency/natural key replayed with a materially different "
                f"payload (existing run {existing.id!r})"
            ) from cause
        return _map_run(existing), False

    def get_run(self, run_id: str) -> RunRecord:
        """Return the run snapshot or raise :class:`RunNotFoundError`."""
        row = self._session.get(S12ExportRun, run_id)
        if row is None:
            raise RunNotFoundError(f"export run {run_id!r} not found")
        return _map_run(row)

    # ── Atomic claim / fence ─────────────────────────────────────────────

    def claim_run(
        self, run_id: str, worker_id: str, *, ttl_seconds: int = 300
    ) -> LeaseRecord:
        """Atomically claim the run for *worker_id* (exactly one winner).

        The claim is a guarded single write on the ``s12_export_lease`` row:
        the first INSERT wins (``ON CONFLICT DO NOTHING``); every other
        racing caller sees rowcount 0 and fails with
        :class:`LeaseConflictError` unless the existing lease is
        expired/released, in which case a guarded CAS on ``lease_version``
        re-claims with a fresh fence token.  The winning claim moves the run
        ``pending`` → ``running`` under the same transaction; losers never
        mutate the run.
        """
        run = self._session.get(S12ExportRun, run_id)
        if run is None:
            raise RunNotFoundError(f"export run {run_id!r} not found")
        if ttl_seconds < 1:
            raise S12ExportError("ttl_seconds must be >= 1")
        if run.status == "pending" and run.attempt != 1:
            raise S12ExportError("pending run with attempt != 1 is ambiguous")
        if run.status not in ("pending", "running"):
            raise S12ExportError(
                f"run {run_id} in status {run.status!r} cannot be claimed"
            )

        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)
        token = uuid.uuid4().hex

        def _aware(dt: datetime) -> datetime:
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

        stmt = sqlite_insert(S12ExportLease).values(
            run_id=run_id,
            worker_id=worker_id,
            lease_version=1,
            fence_token=token,
            acquired_at=now,
            expires_at=expires,
            heartbeat_at=now,
            ttl_seconds=ttl_seconds,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=[S12ExportLease.run_id])
        result = cast("CursorResult[Any]", self._session.execute(stmt))
        if result.rowcount == 1:
            self._session.flush()
            if run.status == "pending":
                self._activate_run(run, expected="pending")
            elif run.status != "running":  # pragma: no cover - defensive
                raise S12ExportError(
                    f"run {run_id} status {run.status!r} cannot accept a claim"
                )
            run.revision += 1
            self._session.flush()
            return self.get_lease(run_id) or _lease_record(
                S12ExportLease(
                    run_id=run_id,
                    worker_id=worker_id,
                    lease_version=1,
                    fence_token=token,
                    acquired_at=now,
                    expires_at=expires,
                    heartbeat_at=now,
                    ttl_seconds=ttl_seconds,
                )
            )

        existing = self._session.get(S12ExportLease, run_id)
        if existing is None:  # pragma: no cover - defensive
            raise LeaseConflictError(
                f"lease claim lost for run {run_id} (concurrent writer)",
                run_id=run_id,
            )
        if _aware(existing.expires_at) > now:
            raise LeaseConflictError(
                f"run {run_id} is already leased by worker "
                f"{existing.worker_id!r} until {existing.expires_at.isoformat()} "
                f"(lease_version={existing.lease_version}); only an absent or "
                "expired/released lease may be claimed",
                run_id=run_id,
            )

        old_version = existing.lease_version
        updated = (
            update(S12ExportLease)
            .where(
                S12ExportLease.run_id == run_id,
                S12ExportLease.lease_version == old_version,
                sa_text("expires_at <= :now").bindparams(now=now),
            )
            .values(
                worker_id=worker_id,
                lease_version=old_version + 1,
                fence_token=token,
                acquired_at=now,
                expires_at=expires,
                heartbeat_at=now,
                ttl_seconds=ttl_seconds,
            )
        )
        result = cast("CursorResult[Any]", self._session.execute(updated))
        if result.rowcount != 1:
            raise LeaseConflictError(
                f"lease re-claim lost for run {run_id} (concurrent claimant)",
                run_id=run_id,
            )
        self._session.flush()
        if run.status == "pending":
            self._activate_run(run, expected="pending")
        elif run.status != "running":  # pragma: no cover - defensive
            raise S12ExportError(
                f"run {run_id} status {run.status!r} cannot accept a re-claim"
            )
        run.revision += 1
        self._session.flush()
        return self.get_lease(run_id) or _lease_record(
            S12ExportLease(
                run_id=run_id,
                worker_id=worker_id,
                lease_version=old_version + 1,
                fence_token=token,
                acquired_at=now,
                expires_at=expires,
                heartbeat_at=now,
                ttl_seconds=ttl_seconds,
            )
        )

    def _activate_run(self, run: S12ExportRun, *, expected: str) -> None:
        if run.status != expected:  # pragma: no cover - defensive
            raise S12ExportError(
                f"run {run.id} status {run.status!r} != expected {expected!r}"
            )
        run.status = "running"

    def get_lease(self, run_id: str) -> LeaseRecord | None:
        """Return the current lease snapshot, or None when unclaimed."""
        row = self._session.get(S12ExportLease, run_id)
        return _lease_record(row) if row is not None else None

    def _require_fence_token(self, run_id: str, worker_id: str, fence_token: str) -> S12ExportLease:
        lease = self._session.get(S12ExportLease, run_id)
        if lease is None:
            raise LeaseNotFoundError(f"no lease for run {run_id!r}")
        if lease.worker_id != worker_id or lease.fence_token != fence_token:
            raise FencedWorkerError(
                f"write rejected for run {run_id}: fence token mismatch "
                "(worker was fenced)",
                run_id=run_id,
            )
        return lease

    def heartbeat_lease(
        self,
        run_id: str,
        worker_id: str,
        fence_token: str,
        *,
        ttl_seconds: int | None = None,
    ) -> LeaseRecord:
        """Renew the lease; fails when the token no longer matches."""
        lease = self._require_fence_token(run_id, worker_id, fence_token)
        now = datetime.now(UTC)
        ttl = lease.ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl < 1:
            raise S12ExportError("ttl_seconds must be >= 1")
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=ttl)
        lease.ttl_seconds = ttl
        return _lease_record(lease)

    def release_lease(self, run_id: str, worker_id: str, fence_token: str) -> None:
        """Release the lease (graceful shutdown) — re-claimable from checkpoint."""
        lease = self._require_fence_token(run_id, worker_id, fence_token)
        now = datetime.now(UTC)
        lease.expires_at = now
        lease.heartbeat_at = now

    # ── Fenced worker writes ─────────────────────────────────────────────

    def transition_run(
        self,
        run_id: str,
        to_status: str,
        *,
        actor: str,
        expected_revision: int,
        fence_token: str,
    ) -> RunRecord:
        """Move the run lifecycle state under fence + revision CAS."""
        if to_status not in S12_EXPORT_RUN_STATUSES:
            raise S12ExportError(f"unknown export run status {to_status!r}")
        run = self._session.get(S12ExportRun, run_id)
        if run is None:
            raise RunNotFoundError(f"export run {run_id!r} not found")
        lease = self._require_fence_token(run_id, actor, fence_token)
        _ = lease
        if run.status in S12_EXPORT_TERMINAL_STATUSES:
            raise S12ExportError(
                f"run {run_id} is terminal ({run.status!r}); no further transitions"
            )
        allowed = {
            "pending": ("running", "cancelled"),
            "running": ("verifying", "failed", "cancelled"),
            "verifying": ("completed", "failed", "cancelled"),
        }
        if to_status not in allowed.get(run.status, ()):
            raise S12ExportError(
                f"invalid export run transition {run.status!r} -> {to_status!r}"
            )
        if run.revision != expected_revision:
            raise S12ExportError(
                f"revision mismatch for run {run_id}: expected "
                f"{expected_revision}, current {run.revision}"
            )
        run.status = to_status
        run.revision += 1
        return _map_run(run)

    def upsert_chunk(
        self,
        *,
        run_id: str,
        workspace_id: str,
        chunk_index: int,
        order_index: int,
        core_start_frame: int,
        core_end_frame: int,
        overlap_before: int = 0,
        overlap_after: int = 0,
        content_hash: str,
        attempt: int = 1,
        actor: str,
        fence_token: str,
        expected_content_hash: str | None = None,
    ) -> tuple[ChunkRecord, bool]:
        """Create or replay a chunk boundary under fence (fail-closed).

        The first write wins per (run, chunk_index, attempt); a replay with
        the same ``content_hash`` returns the existing row (``created=False``)
        while a replay with a DIFFERENT hash raises :class:`StaleIdentityError`
        — ambiguous identity never overwrites.  When
        *expected_content_hash* is given, a stored chunk with any other hash
        fails closed even on first read.
        """
        run = self._session.get(S12ExportRun, run_id)
        if run is None:
            raise RunNotFoundError(f"export run {run_id!r} not found")
        self._require_fence_token(run_id, actor, fence_token)
        if run.status in S12_EXPORT_TERMINAL_STATUSES:
            raise S12ExportError(
                f"run {run_id} is terminal ({run.status!r}); chunks are frozen"
            )
        _require_hex64(content_hash, "content_hash")
        if chunk_index < 0 or order_index < 0:
            raise S12ExportError("chunk_index/order_index must be >= 0")
        if core_start_frame < 0 or core_end_frame < core_start_frame:
            raise S12ExportError("invalid chunk core frame range")
        if overlap_before < 0 or overlap_after < 0:
            raise S12ExportError("chunk overlaps must be >= 0")
        if attempt < 1:
            raise S12ExportError("chunk attempt must be >= 1")

        natural = _canonical_json(
            {"run": run_id, "chunk": chunk_index, "attempt": attempt}
        )
        natural_key = hashlib.sha256(natural.encode("utf-8")).hexdigest()
        row = S12ExportChunk(
            workspace_id=workspace_id,
            run_id=run_id,
            chunk_index=chunk_index,
            order_index=order_index,
            core_start_frame=core_start_frame,
            core_end_frame=core_end_frame,
            overlap_before=overlap_before,
            overlap_after=overlap_after,
            content_hash=content_hash,
            state="pending",
            attempt=attempt,
            verified=0,
            natural_key=natural_key,
        )
        try:
            with self._session.no_autoflush:
                self._session.add(row)
                self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            existing = self._session.scalar(
                select(S12ExportChunk).where(
                    S12ExportChunk.run_id == run_id,
                    S12ExportChunk.chunk_index == chunk_index,
                    S12ExportChunk.attempt == attempt,
                )
            )
            if existing is None:
                raise S12ExportError(
                    f"chunk write conflict resolved to no row: {err.orig}"
                ) from err
            if existing.content_hash != content_hash:
                raise StaleIdentityError(
                    f"chunk (run {run_id}, index {chunk_index}, attempt "
                    f"{attempt}) already pinned with a different content_hash "
                    "(ambiguous identity — refusing to overwrite)"
                ) from err
            if (
                expected_content_hash is not None
                and existing.content_hash != expected_content_hash
            ):
                raise StaleIdentityError(
                    "stored chunk content_hash does not match the caller's "
                    "expected pin (stale caller)"
                ) from err
            return _map_chunk(existing), False
        if expected_content_hash is not None and content_hash != expected_content_hash:
            raise StaleIdentityError(
                "chunk content_hash does not match the caller's expected pin"
            )
        return _map_chunk(row), True

    def transition_chunk(
        self,
        chunk_id: str,
        to_state: str,
        *,
        actor: str,
        fence_token: str,
        expected_revision: int,
        verified: int | None = None,
    ) -> ChunkRecord:
        """Move a chunk state under fence + revision CAS."""
        if to_state not in S12_EXPORT_CHUNK_STATES:
            raise S12ExportError(f"unknown export chunk state {to_state!r}")
        chunk = self._session.get(S12ExportChunk, chunk_id)
        if chunk is None:
            raise S12ExportError(f"export chunk {chunk_id!r} not found")
        self._require_fence_token(chunk.run_id, actor, fence_token)
        allowed = {
            "pending": ("running", "skipped"),
            "running": ("completed", "failed", "skipped"),
            "completed": (),
            "failed": (),
            "skipped": (),
        }
        if to_state not in allowed.get(chunk.state, ()):
            raise S12ExportError(
                f"invalid chunk transition {chunk.state!r} -> {to_state!r}"
            )
        if chunk.revision != expected_revision:
            raise S12ExportError(
                f"revision mismatch for chunk {chunk_id}: expected "
                f"{expected_revision}, current {chunk.revision}"
            )
        chunk.state = to_state
        if verified is not None:
            if verified not in (0, 1):
                raise S12ExportError("verified must be 0 or 1")
            chunk.verified = verified
        chunk.revision += 1
        return _map_chunk(chunk)

    def list_chunks(self, run_id: str) -> list[ChunkRecord]:
        """List chunk snapshots for a run in order_index order."""
        rows = self._session.scalars(
            select(S12ExportChunk)
            .where(S12ExportChunk.run_id == run_id)
            .order_by(S12ExportChunk.order_index, S12ExportChunk.id)
        ).all()
        return [_map_chunk(r) for r in rows]


def _frozen_profile_dims(profile_id: str) -> tuple[str, str]:
    """Frozen T01 profile table snapshot (s12-export-v1 §4, read-only)."""
    frozen = {
        "master-4k-h264": ("3840x2160", "h264"),
        "master-4k-hevc": ("3840x2160", "hevc"),
        "preview-1080p-h264": ("1920x1080", "h264"),
    }
    dims_codec = frozen.get(profile_id)
    if dims_codec is None:
        raise S12ExportError(f"unknown export profile {profile_id!r}")
    return dims_codec

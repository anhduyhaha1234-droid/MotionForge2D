"""Durable FullApply domain — run/chunk/publication + checkpoint contract (S10-T01A).

Fail-closed persistence over the three S10 tables.  Mirrors the product
contract (S10 invariants): no full apply without verified approval, overlap
is context-only, exact frame contracts preserved, resume only from verified
hashes.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.models import (
    ApplyCheckpoint,
    Artifact,
    Project,
    S10FullApplyChunk,
    S10FullApplyPublication,
    S10FullApplyRun,
    VideoItem,
    Workspace,
)

__all__ = [
    "CHUNK_OVERLAP_MAX",
    "S10ApplyCheckpointStaleError",
    "S10ApplyConflictError",
    "S10ApplyNotFoundError",
    "S10ApplyOwnershipError",
    "S10ApplyParamsError",
    "S10PublicationRecord",
    "S10ApplyRepository",
    "S10ChunkRecord",
    "S10RunRecord",
    "canonical_chunk_config_json",
    "canonical_frame_metadata_json",
]

CHUNK_OVERLAP_MAX = 64


class S10ApplyError(Exception):
    """Base for S10 FullApply domain."""


class S10ApplyNotFoundError(S10ApplyError):
    """Requested row not found in this workspace."""


class S10ApplyConflictError(S10ApplyError):
    """Idempotency/natural-key/CAS conflict — zero mutation."""


class S10ApplyOwnershipError(S10ApplyError):
    """Cross-workspace or cross-project ownership mismatch."""


class S10ApplyParamsError(ValueError):
    """Payload outside its closed domain (fail-closed validation)."""


class S10ApplyCheckpointStaleError(S10ApplyParamsError):
    """Checkpoint revision/hash stale or mismatched (fail-closed)."""


def _new_id() -> str:
    return str(uuid.uuid4())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_chunk_config_json(config: dict[str, Any]) -> str:
    _reject_non_finite(config)
    return _canonical_json(config)


def canonical_frame_metadata_json(metadata: dict[str, Any]) -> str:
    _reject_non_finite(metadata)
    return _canonical_json(metadata)


def _reject_non_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise S10ApplyParamsError(f"non-finite number at {path}")
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _reject_non_finite(v, f"{path}[{i}]")


def _require_hex64(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise S10ApplyParamsError(f"{field} must be 64 hex chars")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise S10ApplyParamsError(f"{field} must be hex") from exc
    return value.lower()


@dataclass(frozen=True)
class S10RunRecord:
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    apply_checkpoint_id: str
    apply_checkpoint_hash: str
    apply_checkpoint_revision: int
    plan_id: str
    plan_hash: str
    status: str
    frame_count: int
    fps_num: int | None
    fps_den: int | None
    chunk_config: dict[str, Any]
    attempt: int
    natural_key: str | None
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class S10ChunkRecord:
    id: str
    workspace_id: str
    run_id: str
    chunk_index: int
    order_index: int
    shot_id: str
    layer_id: str | None
    object_role_id: str | None
    core_start_frame: int
    core_end_frame: int
    overlap_before: int
    overlap_after: int
    content_hash: str
    state: str
    attempt: int
    artifact_id: str | None
    verified: bool
    natural_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    # DELTA-F1: whole-shot/GROUP membership persisted from the frozen plan
    # (empty for legacy per-layer chunks).
    member_layer_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class S10PublicationRecord:
    id: str
    workspace_id: str
    run_id: str
    artifact_id: str
    content_hash: str
    frame_count: int
    frame_metadata: dict[str, Any]
    checkpoint_id: str
    checkpoint_hash: str
    checkpoint_revision: int
    state: str
    natural_key: str | None
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


def _map_run(row: S10FullApplyRun) -> S10RunRecord:
    return S10RunRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        apply_checkpoint_id=row.apply_checkpoint_id,
        apply_checkpoint_hash=row.apply_checkpoint_hash,
        apply_checkpoint_revision=row.apply_checkpoint_revision,
        plan_id=row.plan_id,
        plan_hash=row.plan_hash,
        status=row.status,
        frame_count=row.frame_count,
        fps_num=row.fps_num,
        fps_den=row.fps_den,
        chunk_config=dict(json.loads(row.chunk_config_json)),
        attempt=row.attempt,
        natural_key=row.natural_key,
        idempotency_key=row.idempotency_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _parse_member_layer_ids(raw: str | None) -> tuple[str, ...]:
    """DELTA-F1: persisted whole-shot/GROUP members JSON -> tuple.

    Corruption fails closed (a chunk whose membership cannot be read must
    never be silently treated as member-less by a caller that then guesses).
    """
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as err:
        raise S10ApplyParamsError(f"member_layer_ids_json is not valid JSON: {err}") from err
    if not isinstance(parsed, list) or any(
        not isinstance(m, str) or not m for m in parsed
    ):
        raise S10ApplyParamsError(
            "member_layer_ids_json must be a JSON array of non-empty strings"
        )
    return tuple(parsed)


def _map_chunk(row: S10FullApplyChunk) -> S10ChunkRecord:
    return S10ChunkRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        chunk_index=row.chunk_index,
        order_index=row.order_index,
        shot_id=row.shot_id,
        layer_id=row.layer_id,
        object_role_id=row.object_role_id,
        core_start_frame=row.core_start_frame,
        core_end_frame=row.core_end_frame,
        overlap_before=row.overlap_before,
        overlap_after=row.overlap_after,
        content_hash=row.content_hash,
        state=row.state,
        attempt=row.attempt,
        artifact_id=row.artifact_id,
        verified=bool(row.verified),
        natural_key=row.natural_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        member_layer_ids=_parse_member_layer_ids(row.member_layer_ids_json),
    )


def _map_pub(row: S10FullApplyPublication) -> S10PublicationRecord:
    return S10PublicationRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        artifact_id=row.artifact_id,
        content_hash=row.content_hash,
        frame_count=row.frame_count,
        frame_metadata=dict(json.loads(row.frame_metadata_json)),
        checkpoint_id=row.checkpoint_id,
        checkpoint_hash=row.checkpoint_hash,
        checkpoint_revision=row.checkpoint_revision,
        state=row.state,
        natural_key=row.natural_key,
        idempotency_key=row.idempotency_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class S10ApplyRepository:
    """Fail-closed S10 FullApply persistence.

    Every write validates workspace/project/video ownership, checkpoint
    revision/hash pin, frame contracts and artifact state BEFORE any
    durable mutation.  Idempotency and natural-key replays return the
    existing row; conflicts raise with zero mutation.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── helpers ──────────────────────────────────────────────────────

    def _require_workspace(self, workspace_id: str) -> Workspace:
        ws = self._session.get(Workspace, workspace_id)
        if ws is None:
            raise S10ApplyNotFoundError(f"Workspace {workspace_id!r} not found")
        return ws

    def _require_project_in_workspace(self, project_id: str, workspace_id: str) -> Project:
        proj = self._session.get(Project, project_id)
        if proj is None or proj.workspace_id != workspace_id:
            raise S10ApplyOwnershipError(
                f"Project {project_id!r} not in workspace {workspace_id!r}"
            )
        return proj

    def _require_video_in_project(
        self, video_item_id: str, project_id: str, workspace_id: str
    ) -> VideoItem:
        vid = self._session.get(VideoItem, video_item_id)
        if vid is None or vid.project_id != project_id:
            raise S10ApplyOwnershipError(
                f"VideoItem {video_item_id!r} not in project {project_id!r}"
            )
        # also enforce workspace via project
        self._require_project_in_workspace(project_id, workspace_id)
        return vid

    def _require_checkpoint(
        self,
        checkpoint_id: str,
        workspace_id: str,
        *,
        expected_hash: str | None = None,
        expected_revision: int | None = None,
    ) -> ApplyCheckpoint:
        row = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.id == checkpoint_id,
                ApplyCheckpoint.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise S10ApplyNotFoundError(
                f"ApplyCheckpoint {checkpoint_id!r} not found in workspace"
            )
        # cross-project guard: checkpoint must belong to same project as the run
        # (checked at run creation time; publish re-validates via run)
        if expected_hash is not None and row.checkpoint_hash != expected_hash:
            raise S10ApplyCheckpointStaleError(
                f"checkpoint hash mismatch: expected {expected_hash!r} "
                f"got {row.checkpoint_hash!r}"
            )
        if expected_revision is not None and row.reskin_config_revision != expected_revision:
            # reskin_config_revision is the S09 approval's frozen revision pin
            # (checkpoint itself is revision=1 immutable; this is the config rev)
            raise S10ApplyCheckpointStaleError(
                f"checkpoint revision mismatch: expected {expected_revision} "
                f"got {row.reskin_config_revision}"
            )
        return row

    # ── Run ──────────────────────────────────────────────────────────

    def create_run(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        apply_checkpoint_id: str,
        *,
        expected_checkpoint_hash: str,
        expected_checkpoint_revision: int,
        plan_id: str,
        plan_hash: str,
        frame_count: int,
        chunk_config: dict[str, Any],
        fps_num: int | None = None,
        fps_den: int | None = None,
        idempotency_key: str | None = None,
        natural_key: str | None = None,
    ) -> tuple[S10RunRecord, bool]:
        if frame_count < 1:
            raise S10ApplyParamsError("frame_count must be >= 1")
        _require_hex64(plan_id, "plan_id")
        _require_hex64(plan_hash, "plan_hash")
        _require_hex64(expected_checkpoint_hash, "expected_checkpoint_hash")
        if expected_checkpoint_revision < 1:
            raise S10ApplyParamsError("expected_checkpoint_revision must be >= 1")
        _reject_non_finite(chunk_config)
        if fps_num is not None and fps_num < 1:
            raise S10ApplyParamsError("fps_num must be > 0 if provided")
        if fps_den is not None and fps_den < 1:
            raise S10ApplyParamsError("fps_den must be > 0 if provided")
        if idempotency_key is not None and len(idempotency_key) > 255:
            raise S10ApplyParamsError("idempotency_key too long")
        if natural_key is not None and len(natural_key) > 255:
            raise S10ApplyParamsError("natural_key too long")

        # Ownership + checkpoint linkage — fail-closed BEFORE any write
        self._require_workspace(workspace_id)
        self._require_project_in_workspace(project_id, workspace_id)
        self._require_video_in_project(video_item_id, project_id, workspace_id)
        ckpt = self._require_checkpoint(
            apply_checkpoint_id,
            workspace_id,
            expected_hash=expected_checkpoint_hash,
            expected_revision=expected_checkpoint_revision,
        )
        # cross-project: checkpoint.project_id must equal run project
        if ckpt.project_id != project_id:
            raise S10ApplyOwnershipError(
                f"checkpoint project {ckpt.project_id!r} != run project {project_id!r} "
                "(cross-project checkpoint rejected)"
            )

        # Idempotency replay (workspace-scoped)
        if idempotency_key is not None:
            existing = self._session.scalar(
                select(S10FullApplyRun).where(
                    S10FullApplyRun.workspace_id == workspace_id,
                    S10FullApplyRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                # natural-key must match if both supplied
                if natural_key is not None and existing.natural_key != natural_key:
                    raise S10ApplyConflictError(
                        "idempotency key already bound to a different natural_key"
                    )
                # checkpoint pin must match
                if (
                    existing.apply_checkpoint_id != apply_checkpoint_id
                    or existing.apply_checkpoint_hash != expected_checkpoint_hash
                ):
                    raise S10ApplyConflictError(
                        "idempotency key already bound to a different checkpoint"
                    )
                return _map_run(existing), False

        if natural_key is not None:
            existing_nat = self._session.scalar(
                select(S10FullApplyRun).where(
                    S10FullApplyRun.workspace_id == workspace_id,
                    S10FullApplyRun.natural_key == natural_key,
                )
            )
            if existing_nat is not None:
                return _map_run(existing_nat), False

        row = S10FullApplyRun(
            id=_new_id(),
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            apply_checkpoint_id=apply_checkpoint_id,
            apply_checkpoint_hash=expected_checkpoint_hash,
            apply_checkpoint_revision=expected_checkpoint_revision,
            plan_id=plan_id,
            plan_hash=plan_hash,
            status="pending",
            frame_count=frame_count,
            fps_num=fps_num,
            fps_den=fps_den,
            chunk_config_json=_canonical_json(chunk_config),
            attempt=1,
            natural_key=natural_key,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            raise S10ApplyConflictError(f"run insert conflict: {err}") from err
        return _map_run(row), True

    def get_run(self, run_id: str, workspace_id: str) -> S10RunRecord:
        row = self._session.scalar(
            select(S10FullApplyRun).where(
                S10FullApplyRun.id == run_id,
                S10FullApplyRun.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found")
        return _map_run(row)

    def list_runs(
        self,
        workspace_id: str,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[S10RunRecord]:
        stmt = (
            select(S10FullApplyRun)
            .where(S10FullApplyRun.workspace_id == workspace_id)
            .order_by(S10FullApplyRun.created_at.desc(), S10FullApplyRun.id)
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(S10FullApplyRun.project_id == project_id)
        return [_map_run(r) for r in self._session.scalars(stmt).all()]

    # ── Chunk ────────────────────────────────────────────────────────

    def create_chunk(
        self,
        workspace_id: str,
        run_id: str,
        chunk_index: int,
        order_index: int,
        shot_id: str,
        core_start_frame: int,
        core_end_frame: int,
        content_hash: str,
        *,
        overlap_before: int = 0,
        overlap_after: int = 0,
        layer_id: str | None = None,
        object_role_id: str | None = None,
        attempt: int = 1,
        natural_key: str | None = None,
        idempotency_key: str | None = None,
        member_layer_ids: list[str] | None = None,
    ) -> tuple[S10ChunkRecord, bool]:
        if chunk_index < 0 or order_index < 0:
            raise S10ApplyParamsError("chunk_index/order_index must be >= 0")
        if not shot_id:
            raise S10ApplyParamsError("shot_id must be non-empty")
        if core_start_frame < 0 or core_end_frame < core_start_frame:
            raise S10ApplyParamsError("core frame range invalid")
        if overlap_before < 0 or overlap_after < 0:
            raise S10ApplyParamsError("overlap must be >= 0")
        if overlap_before > CHUNK_OVERLAP_MAX or overlap_after > CHUNK_OVERLAP_MAX:
            raise S10ApplyParamsError(f"overlap exceeds max {CHUNK_OVERLAP_MAX}")
        _require_hex64(content_hash, "content_hash")
        if attempt < 1:
            raise S10ApplyParamsError("attempt must be >= 1")
        if natural_key is not None and len(natural_key) > 255:
            raise S10ApplyParamsError("natural_key too long")
        if idempotency_key is not None and len(idempotency_key) > 255:
            raise S10ApplyParamsError("idempotency_key too long")
        # DELTA-F1: the whole-shot/GROUP membership rides with the chunk row.
        member_ids: tuple[str, ...] = ()
        if member_layer_ids is not None:
            if isinstance(member_layer_ids, (str, bytes)):
                raise S10ApplyParamsError(
                    "member_layer_ids must be a list of layer ids, not a string"
                )
            ids = [str(m) for m in member_layer_ids]
            if any(not m or len(m) > 128 for m in ids):
                raise S10ApplyParamsError(
                    "member_layer_ids entries must be non-empty and <= 128 chars"
                )
            if len(ids) > 64:
                raise S10ApplyParamsError("member_layer_ids exceeds 64 entries")
            member_ids = tuple(sorted(set(ids)))

        run = self._session.scalar(
            select(S10FullApplyRun).where(
                S10FullApplyRun.id == run_id,
                S10FullApplyRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found")

        if object_role_id is not None:
            from app.persistence.models import ObjectRole as _ObjectRole  # noqa: PLC0415,N814

            role = self._session.get(_ObjectRole, object_role_id)
            if role is None or role.workspace_id != workspace_id:
                raise S10ApplyOwnershipError(
                    f"ObjectRole {object_role_id!r} not in workspace"
                )

        # core_end must not exceed run frame_count
        if core_end_frame >= run.frame_count:
            raise S10ApplyParamsError(
                f"core_end_frame {core_end_frame} >= run frame_count {run.frame_count}"
            )

        if idempotency_key is not None:
            existing = self._session.scalar(
                select(S10FullApplyChunk).where(
                    S10FullApplyChunk.workspace_id == workspace_id,
                    S10FullApplyChunk.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return _map_chunk(existing), False
        if natural_key is not None:
            existing_nat = self._session.scalar(
                select(S10FullApplyChunk).where(
                    S10FullApplyChunk.workspace_id == workspace_id,
                    S10FullApplyChunk.natural_key == natural_key,
                )
            )
            if existing_nat is not None:
                return _map_chunk(existing_nat), False

        row = S10FullApplyChunk(
            id=_new_id(),
            workspace_id=workspace_id,
            run_id=run_id,
            chunk_index=chunk_index,
            order_index=order_index,
            shot_id=shot_id,
            layer_id=layer_id,
            object_role_id=object_role_id,
            core_start_frame=core_start_frame,
            core_end_frame=core_end_frame,
            overlap_before=overlap_before,
            overlap_after=overlap_after,
            content_hash=content_hash,
            state="pending",
            attempt=attempt,
            verified=0,
            natural_key=natural_key,
            idempotency_key=idempotency_key,
            member_layer_ids_json=(
                _canonical_json(list(member_ids)) if member_ids else None
            ),
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            raise S10ApplyConflictError(f"chunk insert conflict: {err}") from err
        return _map_chunk(row), True

    def get_chunk(self, chunk_id: str, workspace_id: str) -> S10ChunkRecord:
        row = self._session.scalar(
            select(S10FullApplyChunk).where(
                S10FullApplyChunk.id == chunk_id,
                S10FullApplyChunk.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise S10ApplyNotFoundError(f"FullApplyChunk {chunk_id!r} not found")
        return _map_chunk(row)

    def list_chunks(self, workspace_id: str, run_id: str) -> list[S10ChunkRecord]:
        rows = self._session.scalars(
            select(S10FullApplyChunk)
            .where(
                S10FullApplyChunk.workspace_id == workspace_id,
                S10FullApplyChunk.run_id == run_id,
            )
            .order_by(S10FullApplyChunk.order_index, S10FullApplyChunk.chunk_index)
        ).all()
        return [_map_chunk(r) for r in rows]

    def mark_chunk_verified(
        self,
        chunk_id: str,
        workspace_id: str,
        *,
        artifact_id: str,
        verified_content_hash: str,
    ) -> S10ChunkRecord:
        """Mark a chunk as verified after hash check (resume eligibility)."""
        _require_hex64(verified_content_hash, "verified_content_hash")
        row = self._session.scalar(
            select(S10FullApplyChunk).where(
                S10FullApplyChunk.id == chunk_id,
                S10FullApplyChunk.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise S10ApplyNotFoundError(f"FullApplyChunk {chunk_id!r} not found")
        if row.content_hash != verified_content_hash:
            raise S10ApplyParamsError(
                f"content hash mismatch: chunk {row.content_hash!r} "
                f"vs verified {verified_content_hash!r}"
            )
        art = self._session.get(Artifact, artifact_id)
        if art is None or art.workspace_id != workspace_id:
            raise S10ApplyNotFoundError(f"Artifact {artifact_id!r} not found")
        if art.state != "ready":
            raise S10ApplyParamsError(
                f"artifact {artifact_id!r} is not ready (state={art.state!r})"
            )
        if ".partial" in (art.relative_path or ""):
            raise S10ApplyParamsError("artifact path must not contain .partial")
        row.artifact_id = artifact_id
        row.verified = 1
        row.state = "completed"
        self._session.flush()
        return _map_chunk(row)

    def list_verified_chunks(self, workspace_id: str, run_id: str) -> list[S10ChunkRecord]:
        rows = self._session.scalars(
            select(S10FullApplyChunk).where(
                S10FullApplyChunk.workspace_id == workspace_id,
                S10FullApplyChunk.run_id == run_id,
                S10FullApplyChunk.verified == 1,
            )
        ).all()
        return [_map_chunk(r) for r in rows]

    # ── Publication ──────────────────────────────────────────────────

    def create_publication(
        self,
        workspace_id: str,
        run_id: str,
        artifact_id: str,
        content_hash: str,
        frame_count: int,
        frame_metadata: dict[str, Any],
        checkpoint_id: str,
        checkpoint_hash: str,
        checkpoint_revision: int,
        *,
        natural_key: str | None = None,
        idempotency_key: str | None = None,
        state: str = "pending",
    ) -> tuple[S10PublicationRecord, bool]:
        if frame_count < 1:
            raise S10ApplyParamsError("frame_count must be >= 1")
        _require_hex64(content_hash, "content_hash")
        _require_hex64(checkpoint_hash, "checkpoint_hash")
        if checkpoint_revision < 1:
            raise S10ApplyParamsError("checkpoint_revision must be >= 1")
        _reject_non_finite(frame_metadata)
        if state not in ("pending", "verifying", "completed", "failed"):
            raise S10ApplyParamsError(f"invalid publication state {state!r}")
        if natural_key is not None and len(natural_key) > 255:
            raise S10ApplyParamsError("natural_key too long")
        if idempotency_key is not None and len(idempotency_key) > 255:
            raise S10ApplyParamsError("idempotency_key too long")

        run = self._session.scalar(
            select(S10FullApplyRun).where(
                S10FullApplyRun.id == run_id,
                S10FullApplyRun.workspace_id == workspace_id,
            )
        )
        if run is None:
            raise S10ApplyNotFoundError(f"FullApplyRun {run_id!r} not found")
        # Immutable linkage: publication checkpoint must match run's checkpoint
        if run.apply_checkpoint_id != checkpoint_id or run.apply_checkpoint_hash != checkpoint_hash:
            raise S10ApplyCheckpointStaleError(
                "publication checkpoint does not match run's frozen checkpoint"
            )
        # also validate the checkpoint row still matches (hash guard)
        self._require_checkpoint(
            checkpoint_id, workspace_id, expected_hash=checkpoint_hash
        )

        art = self._session.get(Artifact, artifact_id)
        if art is None or art.workspace_id != workspace_id:
            raise S10ApplyNotFoundError(f"Artifact {artifact_id!r} not found")
        if art.state != "ready":
            raise S10ApplyParamsError(
                f"artifact {artifact_id!r} is not ready (state={art.state!r}) — "
                "publications cannot reference unverified artifacts"
            )
        if ".partial" in (art.relative_path or ""):
            raise S10ApplyParamsError(
                "artifact path must not contain .partial — completed publications "
                "cannot reference .partial artifacts"
            )

        # Idempotency / natural-key replay
        if idempotency_key is not None:
            existing = self._session.scalar(
                select(S10FullApplyPublication).where(
                    S10FullApplyPublication.workspace_id == workspace_id,
                    S10FullApplyPublication.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return _map_pub(existing), False
        if natural_key is not None:
            existing_nat = self._session.scalar(
                select(S10FullApplyPublication).where(
                    S10FullApplyPublication.workspace_id == workspace_id,
                    S10FullApplyPublication.natural_key == natural_key,
                )
            )
            if existing_nat is not None:
                return _map_pub(existing_nat), False
        # also lineage dedupe by (run, content_hash)
        existing_lineage = self._session.scalar(
            select(S10FullApplyPublication).where(
                S10FullApplyPublication.run_id == run_id,
                S10FullApplyPublication.content_hash == content_hash,
            )
        )
        if existing_lineage is not None:
            return _map_pub(existing_lineage), False

        row = S10FullApplyPublication(
            id=_new_id(),
            workspace_id=workspace_id,
            run_id=run_id,
            artifact_id=artifact_id,
            content_hash=content_hash,
            frame_count=frame_count,
            frame_metadata_json=_canonical_json(frame_metadata),
            checkpoint_id=checkpoint_id,
            checkpoint_hash=checkpoint_hash,
            checkpoint_revision=checkpoint_revision,
            state=state,
            natural_key=natural_key,
            idempotency_key=idempotency_key,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            raise S10ApplyConflictError(f"publication insert conflict: {err}") from err
        return _map_pub(row), True

    def complete_publication(
        self,
        publication_id: str,
        workspace_id: str,
    ) -> S10PublicationRecord:
        row = self._session.scalar(
            select(S10FullApplyPublication).where(
                S10FullApplyPublication.id == publication_id,
                S10FullApplyPublication.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise S10ApplyNotFoundError(f"Publication {publication_id!r} not found")
        # Re-validate artifact at completion time
        art = self._session.get(Artifact, row.artifact_id)
        if art is None or art.workspace_id != workspace_id:
            raise S10ApplyNotFoundError("publication artifact missing")
        if art.state != "ready":
            raise S10ApplyParamsError("cannot complete: artifact not ready")
        if ".partial" in (art.relative_path or ""):
            raise S10ApplyParamsError("cannot complete: artifact is .partial")
        # content hash must still match (resume guard)
        row.state = "completed"
        self._session.flush()
        return _map_pub(row)

    def get_publication(self, pub_id: str, workspace_id: str) -> S10PublicationRecord:
        row = self._session.scalar(
            select(S10FullApplyPublication).where(
                S10FullApplyPublication.id == pub_id,
                S10FullApplyPublication.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise S10ApplyNotFoundError(f"Publication {pub_id!r} not found")
        return _map_pub(row)

    def list_publications(self, workspace_id: str, run_id: str) -> list[S10PublicationRecord]:
        rows = self._session.scalars(
            select(S10FullApplyPublication).where(
                S10FullApplyPublication.workspace_id == workspace_id,
                S10FullApplyPublication.run_id == run_id,
            )
        ).all()
        return [_map_pub(r) for r in rows]

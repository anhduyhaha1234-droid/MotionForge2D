"""S12-T03C — public S12 export job API (s12-export-v1 §6).

Thin HTTP surface over the frozen T03A persistence and the T03C durable
job module.  The request never renders: submit pins the ``pending`` run
row and enqueues the ``queued`` durable job; the worker renders
asynchronously.  Cancel applies the run + job transitions in ONE
request-session transaction (same-session pattern — a second writer
would deadlock rollback-journal SQLite).  Retry re-submits the same
lineage pins: the T03A natural-key backstop dedupes, so a repeat retry
converges on the winner instead of a duplicate successor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, get_job_service, get_managed_root
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import JobRepository
from app.persistence.models import Job as JobRow
from app.persistence.models import S12ExportRun as RunRow
from app.persistence.s12_export import (
    IdempotencyConflictError,
    RunNotFoundError,
    S12ExportRepository,
)
from app.workflow.s12_export_jobs import (
    S12ExportSubmitError,
    submit_export_job,
    submit_retry_export_job,
)

WORKSPACE_ID = DEFAULT_WORKSPACE_ID

router = APIRouter(tags=["s12-export"])

JOB_KEY_PREFIX = "s12_export_job:"


class S12ExportSubmitRequest(BaseModel):
    project_id: str = Field(min_length=1)
    video_item_id: str = Field(min_length=1)
    # Optional for the normal product flow: the route resolves these pins
    # from the current Full Apply/lock context.  Keeping them accepted is a
    # backwards-compatible API bridge for existing internal callers.
    checkpoint_id: str | None = Field(default=None, min_length=1)
    checkpoint_hash: str | None = Field(default=None, min_length=1)
    checkpoint_revision: int | None = Field(default=None, ge=1)
    manifest_id: str | None = Field(default=None, min_length=1)
    manifest_hash: str | None = Field(default=None, min_length=64, max_length=64)
    manifest_generation: str | None = Field(default=None, min_length=1)
    profile_id: str = Field(min_length=1)
    plan_id: str | None = Field(default=None, min_length=1)
    plan_hash: str | None = Field(default=None, min_length=1)
    # Server-derived (C2 F02): accepted for backward compatibility only —
    # the route resolves source/frame/fps from the T01 authority and
    # derives every filesystem path under the server managed root.
    frame_count: int | None = Field(default=None, ge=1)
    chunk_config: dict[str, Any] = Field(default_factory=dict)
    source_path: str | None = Field(default=None)
    fps: float | None = Field(default=None, gt=0)
    chunk_dir: str | None = Field(default=None)
    scratch_dir: str | None = Field(default=None)
    output_path: str | None = Field(default=None)
    audio_source: str | None = None
    idempotency_key: str | None = None
    context_revision: str | None = Field(default=None, min_length=64, max_length=64)


def _job_key(run_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{run_id}"


_MEDIA_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv"}


def _source_artifact_path(session: Session, authority: Any) -> str | None:
    """Resolve the authority's source artifact to a real file path.

    The artifact row's ``relative_path`` is server-owned (managed root
    relative).  A missing file or one escaping the managed root is treated
    as absent — never exported.
    """
    from pathlib import Path  # noqa: PLC0415

    from app.persistence.models import Artifact  # noqa: PLC0415

    if not authority.source_artifact_id:
        return None
    artifact = session.get(Artifact, authority.source_artifact_id)
    if artifact is None:
        return None
    rel = str(artifact.relative_path or "")
    if not rel:
        return None
    root = get_managed_root()
    candidate = (Path(root) / rel).resolve()
    if not str(candidate).startswith(str(Path(root).resolve())):
        return None
    if not candidate.is_file():
        return None
    return str(candidate)


def _check_source_media(path: str) -> None:
    """Non-media source artifacts are rejected before mutation (C05)."""
    from pathlib import Path  # noqa: PLC0415

    suffix = Path(path).suffix.lower()
    if suffix not in _MEDIA_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"export source is not playable media ({suffix or 'no extension'})",
        )


def _check_no_partial(authority: Any, path: str) -> None:
    from pathlib import Path  # noqa: PLC0415

    if authority.source_partial or Path(path).name.lower().endswith(".partial"):
        raise HTTPException(
            status_code=422, detail="export source is a .partial artifact; cannot export"
        )


def _server_paths(root: Any, project_id: str, video_item_id: str) -> dict[str, str] | None:
    """Server-owned export directories under the managed root (C2 F02).

    Deterministic per project/video; the client never supplies filesystem
    paths.  Returns ``None`` when the identity would escape the root.
    """
    from pathlib import Path  # noqa: PLC0415

    try:
        base = (Path(root) / "s12-exports" / str(project_id) / str(video_item_id)).resolve()
        root_resolved = Path(root).resolve()
    except OSError:
        return None
    if not str(base).startswith(str(root_resolved)):
        return None
    return {
        "chunk_dir": str(base / "chunks"),
        "scratch_dir": str(base / "scratch"),
        "output_path": str(base / "export_master.mp4"),
    }


def _job_state_in(
    session: Session,
    key: str,
    workspace_id: str,
    expected_job_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Live (job_id, state) for the durable job holding *key* (same session)."""
    rows = list(
        session.scalars(
            select(JobRow).where(
                JobRow.workspace_id == workspace_id,
                JobRow.idempotency_key == key,
            )
        )
    )
    if len(rows) > 1:
        raise HTTPException(status_code=500, detail="S12 durable Job identity is ambiguous")
    row = rows[0] if rows else None
    if row is None:
        return None, None
    if expected_job_id is not None and str(row.id) != expected_job_id:
        raise HTTPException(status_code=500, detail="S12 durable Job pointer is corrupt")
    return str(row.id), str(row.state)


def _run_payload(session: Session, run_id: str, workspace_id: str) -> dict[str, Any]:
    repo = S12ExportRepository(session)
    try:
        rec = repo.get_run(run_id)
    except RunNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    if rec.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"export run {run_id!r} not found")
    chunks = [
        {
            "chunk_index": c.chunk_index,
            "state": c.state,
            "verified": c.verified,
            "attempt": c.attempt,
        }
        for c in repo.list_chunks(run_id)
    ]
    job_id, job_state = _job_state_in(
        session, _job_key(run_id), workspace_id, rec.job_id
    )
    return {
        "run_id": rec.id,
        "workspace_id": rec.workspace_id,
        "project_id": rec.project_id,
        "video_item_id": rec.video_item_id,
        "profile_id": rec.profile_id,
        "plan_id": rec.plan_id,
        "plan_hash": rec.plan_hash,
        "status": rec.status,
        "frame_count": rec.frame_count,
        "attempt": rec.attempt,
        "revision": rec.revision,
        "job_id": job_id,
        "job_state": job_state,
        "chunks": chunks,
    }


@router.post("/s12-exports/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_export(
    body: S12ExportSubmitRequest,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
) -> dict[str, Any]:
    """Pin the export run and enqueue its durable job (no render in request).

    Server-owned authority (C2 F02): every durable identity is resolved by
    the T01 authority module and the readiness aggregate is consumed
    (Decision F) BEFORE any mutation.  Invalid/missing/stale/cross-scope
    authority, non-ready projects, unproven sources, tampered/non-media/
    partial source artifacts and path spoofs fail closed with ZERO runs,
    Jobs and outputs.  The client never supplies filesystem paths: output,
    chunk and scratch locations are derived under the server managed root.
    """
    from app.persistence.readiness import compute_project_readiness  # noqa: PLC0415
    from app.services.s12_export.authority import (  # noqa: PLC0415
        resolve_export_authority,
        resolve_export_context,
    )

    if workspace_id != DEFAULT_WORKSPACE_ID:
        raise HTTPException(status_code=404, detail="unknown export workspace")
    context = resolve_export_context(
        session,
        workspace_id=workspace_id,
        project_id=body.project_id,
        video_item_id=body.video_item_id,
    )
    if context.reasons:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"export context not current: {list(context.reasons)}",
        )
    if body.context_revision is not None and body.context_revision != context.context_revision:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="S12_EXPORT_STALE_CHECKPOINT: export context is stale; reload and preflight again",
        )
    resolved_checkpoint_id = body.checkpoint_id or context.checkpoint_id
    resolved_checkpoint_hash = body.checkpoint_hash or context.checkpoint_hash
    resolved_checkpoint_revision = body.checkpoint_revision or context.checkpoint_revision
    resolved_manifest_id = body.manifest_id or context.manifest_id
    resolved_manifest_hash = body.manifest_hash or context.manifest_hash
    resolved_manifest_generation = body.manifest_generation or context.manifest_generation
    resolved_plan_id = body.plan_id or context.plan_id
    resolved_plan_hash = body.plan_hash or context.plan_hash
    if not all(
        (
            resolved_checkpoint_id,
            resolved_checkpoint_hash,
            resolved_checkpoint_revision,
            resolved_manifest_id,
            resolved_manifest_hash,
            resolved_manifest_generation,
            resolved_plan_id,
            resolved_plan_hash,
            context.frame_count,
        )
    ):
        session.rollback()
        raise HTTPException(status_code=409, detail="export authority context is incomplete")
    # A caller may replay the legacy fields, but cannot replace the current
    # server-owned plan or pins with an arbitrary identity.
    if any(
        (
            body.checkpoint_id and body.checkpoint_id != resolved_checkpoint_id,
            body.checkpoint_hash and body.checkpoint_hash.lower() != str(resolved_checkpoint_hash).lower(),
            body.checkpoint_revision and body.checkpoint_revision != resolved_checkpoint_revision,
            body.manifest_id and body.manifest_id != resolved_manifest_id,
            body.manifest_hash and body.manifest_hash.lower() != str(resolved_manifest_hash).lower(),
            body.manifest_generation and body.manifest_generation != resolved_manifest_generation,
            body.plan_id and body.plan_id != resolved_plan_id,
            body.plan_hash and body.plan_hash.lower() != str(resolved_plan_hash).lower(),
        )
    ):
        session.rollback()
        raise HTTPException(status_code=409, detail="S12_EXPORT_STALE_CHECKPOINT: export context changed")
    authority = resolve_export_authority(
        session,
        workspace_id=workspace_id,
        project_id=body.project_id,
        video_item_id=body.video_item_id,
        checkpoint_id=str(resolved_checkpoint_id),
        checkpoint_hash=str(resolved_checkpoint_hash),
        checkpoint_revision=int(resolved_checkpoint_revision),
        manifest_id=str(resolved_manifest_id),
        manifest_hash=str(resolved_manifest_hash),
        manifest_generation=str(resolved_manifest_generation),
    )
    if not authority.resolved:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"export authority not resolved: {authority.failed_reasons}",
        )
    # Non-media / partial / tampered source artifacts are rejected BEFORE
    # any run or job row exists (C05).
    source_path = _source_artifact_path(session, authority)
    if source_path is None:
        raise HTTPException(status_code=422, detail="export source artifact missing")
    _check_source_media(source_path)
    _check_no_partial(authority, source_path)

    readiness = compute_project_readiness(
        session, workspace_id=workspace_id, project_id=body.project_id
    )
    if str(readiness.status) != "ready":
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"project readiness {readiness.status!r}; export requires ready",
        )

    frame_count = authority.source_frame_count or context.frame_count
    fps_num = authority.source_fps_num or 30
    fps_den = authority.source_fps_den or 1
    fps = float(fps_num) / float(fps_den) if fps_den else 30.0
    if not frame_count or frame_count < 1:
        session.rollback()
        raise HTTPException(
            status_code=422, detail="source frame count not resolvable; cannot export"
        )
    paths = _server_paths(get_managed_root(), body.project_id, body.video_item_id)
    if paths is None:
        session.rollback()
        raise HTTPException(status_code=422, detail="export identity invalid")
    try:
        run, job, created = submit_export_job(
            get_job_service(),
            workspace_id=workspace_id,
            project_id=body.project_id,
            video_item_id=body.video_item_id,
            checkpoint_id=str(authority.checkpoint_id),
            checkpoint_hash=str(authority.checkpoint_hash),
            checkpoint_revision=int(authority.checkpoint_revision or 1),
            manifest_id=str(authority.lock_manifest_id),
            manifest_hash=str(authority.lock_manifest_hash),
            manifest_generation=str(resolved_manifest_generation),
            profile_id=body.profile_id,
            plan_id=str(resolved_plan_id),
            plan_hash=str(resolved_plan_hash),
            frame_count=int(frame_count),
            chunk_config=dict(body.chunk_config or context.chunk_config),
            source_path=str(source_path),
            fps=fps,
            fps_num=int(fps_num),
            fps_den=int(fps_den),
            chunk_dir=paths["chunk_dir"],
            scratch_dir=paths["scratch_dir"],
            output_path=paths["output_path"],
            idempotency_key=body.idempotency_key,
            expected_sha256=str(authority.source_sha256 or ""),
        )
    except S12ExportSubmitError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except IdempotencyConflictError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"export submit failed: {err}") from err
    job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
    job_state = getattr(job, "state", None)
    return {
        "run_id": run.id,
        "status": run.status,
        "job_id": job_id,
        "job_state": job_state,
        "created": created,
        "output_path": paths["output_path"],
        "context_revision": context.context_revision,
    }


@router.get("/s12-exports/{run_id}")
def export_status(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    payload = _run_payload(session, run_id, workspace_id)
    if project_id is not None and payload["project_id"] != project_id:
        raise HTTPException(status_code=404, detail=f"export run {run_id!r} not found in project")
    return payload


@router.post("/s12-exports/{run_id}/cancel")
def cancel_export(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Cancel run + owned durable job in ONE transaction (no false success)."""
    repo = S12ExportRepository(session)
    try:
        rec = repo.get_run(run_id)
    except RunNotFoundError as err:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(err)) from err
    if rec.workspace_id != workspace_id or (project_id is not None and rec.project_id != project_id):
        session.rollback()
        raise HTTPException(status_code=404, detail=f"export run {run_id!r} not found")
    if rec.status in ("completed", "failed", "cancelled"):
        session.rollback()
        raise HTTPException(status_code=409, detail=f"run {run_id} is terminal ({rec.status}); cannot cancel")

    job_state: str | None = None
    try:
        job_id, seen = _job_state_in(
            session, _job_key(run_id), workspace_id, rec.job_id
        )
        job_state = seen
        if job_id is not None and seen in ("queued", "running"):
            current = JobRepository(session).get_job(job_id)
            JobRepository(session).transition_job(
                job_id,
                "cancelling",
                actor="api",
                expected_revision=current.revision,
                reason_code="CANCEL_REQUESTED",
            )
            job_state = "cancelling"
        row = session.get(RunRow, run_id)
        if row is None or row.status in ("completed", "failed", "cancelled"):
            session.rollback()
            raise HTTPException(status_code=409, detail=f"run {run_id} became terminal concurrently; cancel rejected")
        if row.status not in ("pending", "running", "verifying"):
            session.rollback()
            raise HTTPException(status_code=409, detail=f"run {run_id} in status {row.status!r}; cannot cancel")
        row.status = "cancelled"
        row.revision = int(row.revision) + 1
    except HTTPException:
        raise
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"cancel failed: {err}") from err
    try:
        session.commit()
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"cancel commit failed: {err}") from err
    return {"run_id": run_id, "status": "cancelled", "cancelled": True, "job_state": job_state}


@router.post("/s12-exports/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_export(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
    client_id: str | None = Query(default=None, min_length=1),
) -> dict[str, Any]:
    """Retry a failed/cancelled run: re-submit the same lineage pins.

    The T03A natural-key backstop dedupes a repeat retry onto the winner
    (``created=False``) — never a duplicate successor.  An active
    predecessor job fails closed with 409 (no competing work).
    """
    # Client identity is observability metadata only; it is deliberately not
    # part of the durable retry key, so same/different clients converge.
    _ = client_id
    repo = S12ExportRepository(session)
    try:
        rec = repo.get_run(run_id)
    except RunNotFoundError as err:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(err)) from err
    if rec.workspace_id != workspace_id or (project_id is not None and rec.project_id != project_id):
        session.rollback()
        raise HTTPException(status_code=404, detail=f"export run {run_id!r} not found")
    if rec.status not in ("failed", "cancelled"):
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} in status {rec.status!r}; only failed/cancelled runs can be retried",
        )
    if rec.job_id is None:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail="S12 durable Job pointer is missing; retry rejected",
        )
    _, seen = _job_state_in(session, _job_key(run_id), workspace_id, rec.job_id)
    # A cancelled run's own job lingering in ``cancelling`` is NOT competing
    # work — the run is terminal and the retry creates a NEW run + NEW job.
    # Only a genuinely active (queued/running) job blocks the retry.
    if seen in ("queued", "running"):
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="predecessor run has an active export job; retry would create competing work — reject",
        )
    from app.services.s12_export.authority import (  # noqa: PLC0415
        resolve_export_authority,
        resolve_export_context,
    )

    context = resolve_export_context(
        session,
        workspace_id=workspace_id,
        project_id=rec.project_id,
        video_item_id=rec.video_item_id,
    )
    if context.reasons:
        session.rollback()
        raise HTTPException(status_code=409, detail="export context is not current; retry rejected")
    current_values = (
        rec.checkpoint_id == context.checkpoint_id,
        rec.checkpoint_hash.lower() == str(context.checkpoint_hash).lower(),
        rec.checkpoint_revision == context.checkpoint_revision,
        rec.manifest_id == context.manifest_id,
        rec.manifest_hash.lower() == str(context.manifest_hash).lower(),
        rec.manifest_generation == context.manifest_generation,
        rec.plan_id == context.plan_id,
        rec.plan_hash.lower() == str(context.plan_hash).lower(),
        rec.frame_count == context.frame_count,
    )
    if not all(current_values):
        session.rollback()
        raise HTTPException(status_code=409, detail="S12_EXPORT_STALE_CHECKPOINT: retry context changed")
    authority = resolve_export_authority(
        session,
        workspace_id=workspace_id,
        project_id=rec.project_id,
        video_item_id=rec.video_item_id,
        checkpoint_id=rec.checkpoint_id,
        checkpoint_hash=rec.checkpoint_hash,
        checkpoint_revision=rec.checkpoint_revision,
        manifest_id=rec.manifest_id,
        manifest_hash=rec.manifest_hash,
        manifest_generation=rec.manifest_generation,
    )
    if not authority.resolved:
        session.rollback()
        raise HTTPException(status_code=409, detail=f"export authority not resolved: {authority.failed_reasons}")
    source_path = _source_artifact_path(session, authority)
    if source_path is None:
        session.rollback()
        raise HTTPException(status_code=409, detail="export source artifact missing; retry rejected")
    _check_source_media(source_path)
    _check_no_partial(authority, source_path)
    paths = _server_paths(get_managed_root(), rec.project_id, rec.video_item_id)
    if paths is None:
        session.rollback()
        raise HTTPException(status_code=409, detail="export identity invalid; retry rejected")
    manifest = {
        "chunk_config": context.chunk_config,
        "source_path": source_path,
        "fps": (context.fps_num or 30) / (context.fps_den or 1),
        "fps_num": context.fps_num or 30,
        "fps_den": context.fps_den or 1,
        "chunk_dir": paths["chunk_dir"],
        "scratch_dir": paths["scratch_dir"],
        "output_path": paths["output_path"],
        "expected_sha256": authority.source_sha256,
    }
    try:
        new_run, job, created = submit_retry_export_job(
            get_job_service(),
            predecessor_run_id=run_id,
            workspace_id=workspace_id,
            project_id=rec.project_id,
            source_path=str(manifest["source_path"]),
            fps=float(manifest.get("fps") or 0) or 30.0,
            chunk_dir=str(manifest.get("chunk_dir") or ""),
            scratch_dir=str(manifest.get("scratch_dir") or ""),
            output_path=str(manifest.get("output_path") or ""),
            audio_source=manifest.get("audio_source"),
            expected_sha256=manifest.get("expected_sha256"),
            fps_num=int(manifest.get("fps_num") or 0),
            fps_den=int(manifest.get("fps_den") or 0),
        )
    except S12ExportSubmitError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"retry enqueue failed: {err}") from err
    return {
        "run_id": new_run.id,
        "predecessor_run_id": run_id,
        "status": new_run.status,
        "attempt": new_run.attempt,
        "job_id": getattr(job, "job_id", None) or getattr(job, "id", None),
        "created": created,
    }


# ── C22-part: scoped result playback/download (server-owned context) ───

_MEDIA_MIME = "video/mp4"


def _owned_completed_artifact(
    session: Session,
    run_id: str,
    workspace_id: str,
    project_id: str | None,
) -> tuple[Any, Path]:
    """Resolve the completed run's public artifact, fail-closed.

    Ownership first (workspace + optional project scope), then terminal
    ``completed`` state.  The artifact path is DERIVED from the server-owned
    project/video context — never from any client-supplied or manifest
    path.  A missing file, a ``.partial`` name, a missing byte-identity
    sidecar, or a sidecar mismatch (tampered artifact) all fail closed.
    """
    from app.services.s12_export.publication import _sha256_file, _sidecar_path  # noqa: PLC0415

    repo = S12ExportRepository(session)
    try:
        rec = repo.get_run(run_id)
    except RunNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    if rec.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"export run {run_id!r} not found")
    if project_id is not None and rec.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"export run {run_id!r} not found in project")
    if rec.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"export run {run_id} in status {rec.status!r}; result available only when completed",
        )
    paths = _server_paths(get_managed_root(), rec.project_id, rec.video_item_id)
    if paths is None:
        raise HTTPException(status_code=404, detail="export result identity invalid")
    artifact = Path(paths["output_path"])
    if artifact.name.lower().endswith(".partial"):
        raise HTTPException(status_code=404, detail="export result is partial; not served")
    if not artifact.is_file():
        raise HTTPException(status_code=404, detail="export result artifact missing")
    sidecar = _sidecar_path(artifact)
    if not sidecar.is_file():
        raise HTTPException(status_code=403, detail="export result byte identity missing; not served")
    stored = sidecar.read_text(encoding="ascii").strip().lower()
    if _sha256_file(artifact) != stored:
        raise HTTPException(status_code=403, detail="export result tampered; not served")
    return rec, artifact


@router.get("/s12-exports/{run_id}/result")
def export_result(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Metadata for the completed export result (C22-part backend).

    Only a ``completed`` run owned by the request scope is served.  The
    media URL is server-owned (this API), never a client-supplied path.
    """
    rec, artifact = _owned_completed_artifact(session, run_id, workspace_id, project_id)
    size = artifact.stat().st_size
    return {
        "run_id": rec.id,
        "status": rec.status,
        "project_id": rec.project_id,
        "video_item_id": rec.video_item_id,
        "profile_id": rec.profile_id,
        "frame_count": rec.frame_count,
        "filename": artifact.name,
        "size_bytes": size,
        "mime": _MEDIA_MIME,
        "media_url": f"/s12-exports/{rec.id}/media",
    }


@router.get("/s12-exports/{run_id}/media")
def export_media(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> Any:
    """Stream the completed export artifact (play/download, C22-part).

    Same ownership + byte-integrity gates as the result metadata.  A
    missing/tampered/partial artifact is never served; pending/failed/
    cancelled runs return 409 (never media).
    """
    from fastapi.responses import FileResponse  # noqa: PLC0415

    rec, artifact = _owned_completed_artifact(session, run_id, workspace_id, project_id)
    return FileResponse(
        path=str(artifact),
        media_type=_MEDIA_MIME,
        filename=f"{rec.id}_{artifact.name}",
        content_disposition_type="inline",
    )


def _retry_manifest(
    session: Session, rec: Any, pins: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Inherit immutable render pins from the predecessor job manifest.

    Server-side record only — the caller never re-supplies inputs.  Missing
    authority stays missing; the worker fails closed instead of fabricating.
    """
    out: dict[str, Any] = {}
    _, job_state = _job_state_in(
        session, _job_key(rec.id), rec.workspace_id, rec.job_id
    )
    try:
        js = get_job_service()
        factory = getattr(js, "session_factory", None)
        if factory is None:
            return out, job_state
        with factory() as jsess:
            row = jsess.scalar(
                select(JobRow).where(
                    JobRow.workspace_id == rec.workspace_id,
                    JobRow.idempotency_key == _job_key(rec.id),
                )
            )
            raw = getattr(row, "input_manifest_json", None) if row is not None else None
        if not isinstance(raw, str) or not raw:
            return out, job_state
        import json as _jl  # noqa: PLC0415  # local, not top-level

        parsed = _jl.loads(raw)
        if not isinstance(parsed, dict):
            return out, job_state
        for key in (
            "source_path",
            "fps",
            "chunk_dir",
            "scratch_dir",
            "output_path",
            "audio_source",
            "max_frames_per_chunk",
            "overlap_frames",
            "expected_sha256",
            "fps_num",
            "fps_den",
        ):
            if key in parsed and parsed[key] not in (None, ""):
                out[key] = parsed[key]
        # Rebuild the EXACT original chunk config from the flattened manifest
        # so the T03A material-identity replay converges (C2 F04: retry must
        # re-submit the identical material payload, never a drifted one).
        out["chunk_config"] = {
            "max_frames": int(parsed.get("max_frames_per_chunk", 120)),
            "overlap": int(parsed.get("overlap_frames", 4)),
        }
    except Exception:
        return out, job_state
    return out, job_state

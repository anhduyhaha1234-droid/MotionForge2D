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

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, get_job_service
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import JobRepository
from app.persistence.models import Job as JobRow
from app.persistence.models import S12ExportRun as RunRow
from app.persistence.s12_export import RunNotFoundError, S12ExportRepository
from app.workflow.s12_export_jobs import S12ExportSubmitError, submit_export_job

WORKSPACE_ID = DEFAULT_WORKSPACE_ID

router = APIRouter(tags=["s12-export"])

JOB_KEY_PREFIX = "s12_export_job:"


class S12ExportSubmitRequest(BaseModel):
    project_id: str = Field(min_length=1)
    video_item_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    checkpoint_hash: str = Field(min_length=1)
    checkpoint_revision: int = Field(ge=1)
    manifest_id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=64, max_length=64)
    manifest_generation: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_hash: str = Field(min_length=1)
    frame_count: int = Field(ge=1)
    chunk_config: dict[str, Any] = Field(default_factory=dict)
    source_path: str = Field(min_length=1)
    fps: float = Field(gt=0)
    chunk_dir: str = Field(min_length=1)
    scratch_dir: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    audio_source: str | None = None
    idempotency_key: str | None = None


def _job_key(run_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{run_id}"


def _job_state_in(session: Session, key: str) -> tuple[str | None, str | None]:
    """Live (job_id, state) for the durable job holding *key* (same session)."""
    row = session.scalar(select(JobRow).where(JobRow.idempotency_key == key))
    if row is None:
        return None, None
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
    job_id, job_state = _job_state_in(session, _job_key(run_id))
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
    """Pin the export run and enqueue its durable job (no render in request)."""
    try:
        run, job, created = submit_export_job(
            get_job_service(),
            workspace_id=workspace_id,
            project_id=body.project_id,
            video_item_id=body.video_item_id,
            checkpoint_id=body.checkpoint_id,
            checkpoint_hash=body.checkpoint_hash,
            checkpoint_revision=body.checkpoint_revision,
            manifest_id=body.manifest_id,
            manifest_hash=body.manifest_hash,
            manifest_generation=body.manifest_generation,
            profile_id=body.profile_id,
            plan_id=body.plan_id,
            plan_hash=body.plan_hash,
            frame_count=body.frame_count,
            chunk_config=dict(body.chunk_config),
            source_path=body.source_path,
            fps=body.fps,
            chunk_dir=body.chunk_dir,
            scratch_dir=body.scratch_dir,
            output_path=body.output_path,
            audio_source=body.audio_source,
            idempotency_key=body.idempotency_key,
        )
    except S12ExportSubmitError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"export submit failed: {err}") from err
    job_id = getattr(job, "id", None)
    job_state = getattr(job, "state", None)
    return {
        "run_id": run.id,
        "status": run.status,
        "job_id": job_id,
        "job_state": job_state,
        "created": created,
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
        job_id, seen = _job_state_in(session, _job_key(run_id))
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
) -> dict[str, Any]:
    """Retry a failed/cancelled run: re-submit the same lineage pins.

    The T03A natural-key backstop dedupes a repeat retry onto the winner
    (``created=False``) — never a duplicate successor.  An active
    predecessor job fails closed with 409 (no competing work).
    """
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
    _, seen = _job_state_in(session, _job_key(run_id))
    # A cancelled run's own job lingering in ``cancelling`` is NOT competing
    # work — the run is terminal and the retry creates a NEW run + NEW job.
    # Only a genuinely active (queued/running) job blocks the retry.
    if seen in ("queued", "running"):
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="predecessor run has an active export job; retry would create competing work — reject",
        )
    pins = {
        "checkpoint_id": rec.checkpoint_id,
        "checkpoint_hash": rec.checkpoint_hash,
        "checkpoint_revision": rec.checkpoint_revision,
        "manifest_id": rec.manifest_id,
        "manifest_hash": rec.manifest_hash,
        "manifest_generation": rec.manifest_generation,
        "profile_id": rec.profile_id,
        "plan_id": rec.plan_id,
        "plan_hash": rec.plan_hash,
        "frame_count": rec.frame_count,
    }
    manifest, job_state = _retry_manifest(session, rec, pins)
    try:
        new_run, job, created = submit_export_job(
            get_job_service(),
            workspace_id=workspace_id,
            project_id=rec.project_id,
            video_item_id=rec.video_item_id,
            idempotency_key=f"s12_retry:{run_id}",
            chunk_config=dict(manifest.get("chunk_config") or {}),
            source_path=str(manifest.get("source_path") or ""),
            fps=float(manifest.get("fps") or 0) or 30.0,
            chunk_dir=str(manifest.get("chunk_dir") or ""),
            scratch_dir=str(manifest.get("scratch_dir") or ""),
            output_path=str(manifest.get("output_path") or ""),
            audio_source=manifest.get("audio_source"),
            **pins,  # type: ignore[arg-type]
        )
    except S12ExportSubmitError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"retry enqueue failed: {err}") from err
    _ = job_state
    return {
        "run_id": new_run.id,
        "predecessor_run_id": run_id,
        "status": new_run.status,
        "attempt": new_run.attempt,
        "job_id": getattr(job, "id", None),
        "created": created,
    }


def _retry_manifest(
    session: Session, rec: Any, pins: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Inherit immutable render pins from the predecessor job manifest.

    Server-side record only — the caller never re-supplies inputs.  Missing
    authority stays missing; the worker fails closed instead of fabricating.
    """
    out: dict[str, Any] = {}
    _, job_state = _job_state_in(session, _job_key(rec.id))
    try:
        js = get_job_service()
        factory = getattr(js, "session_factory", None)
        if factory is None:
            return out, job_state
        with factory() as jsess:
            row = jsess.scalar(select(JobRow).where(JobRow.idempotency_key == _job_key(rec.id)))
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
            "chunk_config",
            "max_frames_per_chunk",
            "overlap_frames",
        ):
            if key in parsed and parsed[key] not in (None, ""):
                out[key] = parsed[key]
    except Exception:
        return out, job_state
    return out, job_state

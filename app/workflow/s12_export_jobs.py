"""S12-T03C — durable S12 export job type + reconciler (s12-export-v1 §6).

Consumes read-only (frozen, never rewritten here):
- ``app/persistence/s12_export.py`` (T03A) — run/lease rows own ALL export
  state (``create_run`` / ``claim_run`` / ``transition_run`` /
  ``heartbeat_lease`` / ``release_lease``).  This module never issues raw
  SQL against export tables and never mutates a row except through those
  fenced methods.
- ``app/persistence/jobs.py`` (S02) — the durable ``Job`` queue owns job
  lifecycle (``create_job`` / ``create_successor`` / ``transition_job``).
  Submission goes through ``JobService.create_job``; the reconciler below
  only releases *expired* export leases so a fresh claim can resume from
  the T03B checkpoint — it never completes, fails, or rewrites a run.
- ``app/services/s12_export/runner.py`` (T03B) — chunk render / resume /
  assemble.  The handler never marks the run ``completed`` and never
  publishes (T03C publication owns that in a later file).

Crash safety: a crash leaves ``pending``/``running`` rows + ``.partial``
scratch only — resume re-renders them, never accepts them as completed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

__all__ = [
    "S12_EXPORT_JOB_TYPE",
    "S12ExportSubmitError",
    "submit_export_job",
    "register_s12_export_handler",
    "reconcile_export_jobs",
]

#: Stable durable job-type code for S12 export render work.
S12_EXPORT_JOB_TYPE = "s12_export"


class S12ExportSubmitError(ValueError):
    """Fail-closed submission error (stale pins, missing authority)."""


def submit_export_job(
    job_service: Any,
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
    source_path: str,
    fps: float,
    chunk_dir: str,
    scratch_dir: str,
    output_path: str,
    audio_source: str | None = None,
    idempotency_key: str | None = None,
    natural_key: str | None = None,
    priority: int = 50,
) -> tuple[Any, Any, bool]:
    """Pin the export run (T03A, idempotent) and enqueue its durable job.

    Returns ``(run, job, created)`` — ``created=False`` on idempotent
    replay of the same lineage (the existing run + its job are returned,
    never a duplicate successor).  The HTTP request never renders: it
    only commits the ``pending`` run row and the ``queued`` job row.
    """
    from app.persistence.s12_export import (  # noqa: PLC0415
        S12ExportRepository,
        StaleIdentityError,
    )

    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        raise S12ExportSubmitError("job service has no session factory")
    if fps <= 0:
        raise S12ExportSubmitError("fps must be > 0")
    if frame_count < 1:
        raise S12ExportSubmitError("frame_count must be >= 1")

    with factory() as session:
        repo = S12ExportRepository(session)
        try:
            run, created = repo.create_run(
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
                plan_id=plan_id,
                plan_hash=plan_hash,
                frame_count=frame_count,
                chunk_config=dict(chunk_config),
                idempotency_key=idempotency_key,
                natural_key=natural_key,
            )
        except StaleIdentityError as err:
            session.rollback()
            raise S12ExportSubmitError(str(err)) from err
        # Commit the run BEFORE opening the second writer for the job —
        # one SQLite writer at a time (S10-C10 precedent).
        try:
            session.commit()
        except Exception as err:
            session.rollback()
            raise S12ExportSubmitError(f"export run commit failed: {err}") from err

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run.id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "profile_id": profile_id,
        "plan_hash": plan_hash,
        "checkpoint_hash": checkpoint_hash,
        "frame_count": frame_count,
        "source_path": source_path,
        "fps": float(fps),
        "chunk_dir": chunk_dir,
        "scratch_dir": scratch_dir,
        "output_path": output_path,
        "audio_source": audio_source,
        "max_frames_per_chunk": int(chunk_config.get("max_frames", 120)),
        "overlap_frames": int(chunk_config.get("overlap", 4)),
    }
    job_key = f"s12_export_job:{run.id}"
    try:
        job = job_service.create_job(
            S12_EXPORT_JOB_TYPE,
            manifest,
            workspace_id=workspace_id,
            owner_type="project",
            owner_id=project_id,
            idempotency_key=job_key,
            # Deterministic non-NULL generation from the run lineage so the
            # unique backstop serializes a concurrent identical submit.
            input_generation=plan_hash,
            priority=int(priority),
        )
    except Exception as err:
        name = type(err).__name__
        if name in ("IdempotencyKeyInUse", "IntegrityError"):
            # Replay submit: the run was deduped and its job already exists
            # — converge on the winner instead of a duplicate.  The winner
            # is returned as the same JobInfo shape as the fresh path.
            existing = _find_job_by_key(factory, workspace_id, job_key)
            if existing is not None:
                info = job_service._job_info(existing)
                return run, info, False
        raise S12ExportSubmitError(f"export job enqueue failed: {err}") from err
    return run, job, created


def _find_job_by_key(factory: Callable[[], Any], workspace_id: str, key: str) -> Any | None:
    """Return the durable job holding *key*, or None (replay convergence)."""
    from app.persistence.jobs import JobRepository  # noqa: PLC0415

    try:
        with factory() as session:
            for job in JobRepository(session).list_jobs(workspace_id, limit=1000):
                if job.idempotency_key == key:
                    return job
    except Exception:
        return None
    return None


def _s12_export_handler(ctx: Any) -> dict[str, Any]:
    """Execute one S12 export job: claim → render/resume → candidate.

    The claim is atomic (exactly one winner; losers fail closed).  A
    restart re-claims the expired lease and resumes from the T03B
    checkpoint — completed+verified chunks are reused only when their
    file decodes to the exact window size.  Returns candidate evidence;
    the handler never marks the run ``completed`` and never publishes.
    """
    from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415
    from app.services.s12_export.runner import (  # noqa: PLC0415
        ExportRunner,
        RunnerConfig,
    )

    manifest = ctx.input_manifest
    run_id = str(manifest["run_id"])
    workspace_id = str(manifest["workspace_id"])
    factory = getattr(ctx, "session_factory", None)
    if factory is None:
        raise RuntimeError("s12 export handler requires a session factory")

    with factory() as session:
        repo = S12ExportRepository(session)
        lease = repo.claim_run(run_id, ctx.worker_id)
        session.commit()
        cfg = RunnerConfig(
            run_id=run_id,
            workspace_id=workspace_id,
            worker_id=ctx.worker_id,
            fence_token=lease.fence_token,
            source_path=str(manifest["source_path"]),
            fps=float(manifest["fps"]),
            chunk_dir=str(manifest["chunk_dir"]),
            scratch_dir=str(manifest["scratch_dir"]),
            output_path=str(manifest["output_path"]),
            audio_source=manifest.get("audio_source"),
            max_frames_per_chunk=int(manifest.get("max_frames_per_chunk", 120)),
            overlap_frames=int(manifest.get("overlap_frames", 4)),
        )
        candidate = ExportRunner(repo, cfg).resume()
        session.commit()
    return {
        "run_id": run_id,
        "candidate_path": str(candidate),
        "frame_count": int(manifest["frame_count"]),
    }


def register_s12_export_handler(worker: Any) -> None:
    """Register the S12 export handler on a DurableWorker instance."""
    worker.register_handler(S12_EXPORT_JOB_TYPE, _s12_export_handler)


def reconcile_export_jobs(
    session_factory: Callable[[], Any],
    *,
    batch_size: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Release expired S12 export leases so a fresh claim can resume.

    Bounded, restart-safe, never raises: per-run failures are recorded on
    the report and the pass continues.  Only ``running`` runs whose lease
    ``expires_at`` has passed are released (re-claimable from the T03B
    checkpoint); terminal runs, live leases and completed outputs are never
    touched — no fake completion, no successor, no overwrite.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.persistence.models import (  # noqa: PLC0415
        S12ExportLease,
        S12ExportRun,
    )
    from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415

    report: dict[str, Any] = {"scanned": 0, "released": 0, "errors": []}
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        with session_factory() as session:
            rows = session.scalars(
                select(S12ExportLease)
                .join(S12ExportRun, S12ExportLease.run_id == S12ExportRun.id)
                .where(S12ExportRun.status == "running")
                .order_by(S12ExportLease.expires_at.asc())
                .limit(max(1, int(batch_size)))
            ).all()
            candidates = [
                (row.run_id, row.worker_id, row.fence_token, row.expires_at)
                for row in rows
            ]
    except Exception as exc:
        report["errors"].append({"stage": "scan", "error": str(exc)})
        return report
    report["scanned"] = len(candidates)
    for run_id, worker_id, fence_token, expires_at in candidates:
        exp = expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp > moment:
            continue
        try:
            with session_factory() as session:
                S12ExportRepository(session).release_lease(
                    run_id, worker_id, fence_token
                )
                session.commit()
            report["released"] += 1
        except Exception as exc:  # noqa: BLE001 - per-run isolation
            report["errors"].append({"run_id": run_id, "error": str(exc)})
    return report

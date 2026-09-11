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

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

__all__ = [
    "S12_EXPORT_JOB_TYPE",
    "S12ExportSubmitError",
    "submit_export_job",
    "submit_retry_export_job",
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
    expected_sha256: str | None = None,
    fps_num: int = 0,
    fps_den: int = 0,
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
        "expected_sha256": expected_sha256,
        "fps_num": int(fps_num),
        "fps_den": int(fps_den),
    }
    job_key = f"s12_export_job:{run.id}"
    job, run = _enqueue_and_bind_job(
        job_service,
        factory=factory,
        run=run,
        manifest=manifest,
        workspace_id=workspace_id,
        project_id=project_id,
        job_key=job_key,
        input_generation=plan_hash,
        priority=int(priority),
    )
    return run, job, created


def submit_retry_export_job(
    job_service: Any,
    *,
    predecessor_run_id: str,
    workspace_id: str,
    project_id: str,
    source_path: str,
    fps: float,
    chunk_dir: str,
    scratch_dir: str,
    output_path: str,
    expected_sha256: str | None = None,
    audio_source: str | None = None,
    fps_num: int = 0,
    fps_den: int = 0,
    priority: int = 50,
) -> tuple[Any, Any, bool]:
    """Append one successor and its Job in one durable transaction."""
    from app.persistence import StepInput  # noqa: PLC0415
    from app.persistence.jobs import JobRepository  # noqa: PLC0415
    from app.persistence.models import Job, S12ExportRun  # noqa: PLC0415
    from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415

    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        raise S12ExportSubmitError("job service has no session factory")
    key = f"s12_retry:{predecessor_run_id}"

    def make_manifest(run: Any) -> dict[str, Any]:
        try:
            chunk_config = json.loads(run_chunk_config(run))
        except (TypeError, ValueError) as err:
            raise S12ExportSubmitError(
                "retry predecessor has corrupt chunk configuration"
            ) from err
        if not isinstance(chunk_config, dict):
            raise S12ExportSubmitError("retry predecessor has invalid chunk configuration")
        return {
            "schema_version": 1,
            "managed_root": str(getattr(job_service, "managed_root", "")),
            "run_id": run.id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": run.video_item_id,
            "profile_id": run.profile_id,
            "plan_hash": run.plan_hash,
            "checkpoint_hash": run.checkpoint_hash,
            "frame_count": run.frame_count,
            "source_path": source_path,
            "fps": float(fps),
            "chunk_dir": chunk_dir,
            "scratch_dir": scratch_dir,
            "output_path": output_path,
            "audio_source": audio_source,
            "max_frames_per_chunk": int(chunk_config.get("max_frames", 120)),
            "overlap_frames": int(chunk_config.get("overlap", 4)),
            "expected_sha256": expected_sha256,
            "fps_num": int(fps_num),
            "fps_den": int(fps_den),
            "manifest_id": run.manifest_id,
            "manifest_generation": run.manifest_generation,
            "lineage_id": run.lineage_id,
            "predecessor_run_id": run.predecessor_run_id,
            "attempt": run.attempt,
            "chunk_config": chunk_config,
        }

    def ensure_pair(session: Any, run: Any, manifest: dict[str, Any]) -> Any:
        jobs = JobRepository(session)
        repo = S12ExportRepository(session)
        rows = list(
            session.scalars(
                select(Job).where(
                    Job.workspace_id == workspace_id,
                    Job.idempotency_key == f"s12_export_job:{run.id}",
                )
            )
        )
        if len(rows) > 1:
            raise S12ExportSubmitError(
                f"retry Job identity is ambiguous for run {run.id!r}"
            )
        if run.job_id is not None:
            if len(rows) != 1 or str(rows[0].id) != str(run.job_id):
                raise S12ExportSubmitError(
                    f"retry run {run.id!r} has a corrupt durable Job pointer"
                )
            job_record = jobs.get_job(str(run.job_id))
        elif rows:
            job_record = jobs.get_job(str(rows[0].id))
        else:
            job_record = jobs.create_job(
                workspace_id=workspace_id,
                job_type=S12_EXPORT_JOB_TYPE,
                owner_type="project",
                owner_id=project_id,
                input_manifest=manifest,
                idempotency_key=f"s12_export_job:{run.id}",
                input_generation=run.plan_hash,
                priority=int(priority),
                steps=[StepInput(step_code="run", position=0, step_type="sync")],
                actor="api",
            )
        repo.bind_job(run.id, job_record.id)
        return job_record

    def reconcile_pair() -> tuple[Any, Any, bool]:
        with factory() as session:
            repo = S12ExportRepository(session)
            successor = session.scalar(
                select(S12ExportRun).where(
                    S12ExportRun.predecessor_run_id == predecessor_run_id
                )
            )
            if successor is None:
                raise S12ExportSubmitError(
                    "retry transaction uncertainty resolved to no successor"
                )
            run = repo.get_run(successor.id)
            job_record = ensure_pair(session, run, make_manifest(run))
            session.commit()
            return repo.get_run(run.id), job_service._job_info(job_record), False

    with factory() as session:
        repo = S12ExportRepository(session)
        try:
            run, created = repo.create_successor_run(
                predecessor_run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                idempotency_key=key,
            )
            job_record = ensure_pair(session, run, make_manifest(run))
            bound_run = repo.get_run(run.id)
            session.commit()
            return bound_run, job_service._job_info(job_record), created
        except Exception as err:
            session.rollback()
            try:
                return reconcile_pair()
            except S12ExportSubmitError:
                raise
            except Exception as reconcile_err:
                raise S12ExportSubmitError(
                    f"retry transaction failed closed: {err}; "
                    f"reconciliation failed: {reconcile_err}"
                ) from reconcile_err


def run_chunk_config(run: Any) -> str:
    """Keep retry config access narrow while accepting immutable RunRecord snapshots."""
    value = getattr(run, "chunk_config_json", None)
    if value is not None:
        return str(value)
    raise S12ExportSubmitError("retry run snapshot omitted chunk configuration")


def _enqueue_and_bind_job(
    job_service: Any,
    *,
    factory: Callable[[], Any],
    run: Any,
    manifest: dict[str, Any],
    workspace_id: str,
    project_id: str,
    job_key: str,
    input_generation: str,
    priority: int,
) -> tuple[Any, Any]:
    try:
        job = job_service.create_job(
            S12_EXPORT_JOB_TYPE,
            manifest,
            workspace_id=workspace_id,
            owner_type="project",
            owner_id=project_id,
            idempotency_key=job_key,
            input_generation=input_generation,
            priority=priority,
        )
    except Exception as err:
        if type(err).__name__ not in ("IdempotencyKeyInUse", "IntegrityError"):
            raise S12ExportSubmitError(f"export job enqueue failed: {err}") from err
        try:
            existing = _find_job_by_key(factory, workspace_id, job_key)
            job = job_service._job_info(existing)
        except Exception as lookup_err:
            raise S12ExportSubmitError(
                f"export Job replay lookup failed closed: {lookup_err}"
            ) from lookup_err
    job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
    if not job_id:
        raise S12ExportSubmitError("durable Job response omitted its actual job_id")
    try:
        with factory() as session:
            from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415

            bound_run = S12ExportRepository(session).bind_job(run.id, str(job_id))
            session.commit()
    except Exception as err:
        raise S12ExportSubmitError(f"export Job binding failed closed: {err}") from err
    return job, bound_run


def _find_job_by_key(factory: Callable[[], Any], workspace_id: str, key: str) -> Any:
    """Return the exact durable Job, propagating query failures."""
    from app.persistence.jobs import JobRepository  # noqa: PLC0415
    from app.persistence.models import Job  # noqa: PLC0415

    with factory() as session:
        job = session.scalar(
            select(Job).where(
                Job.workspace_id == workspace_id,
                Job.idempotency_key == key,
            )
        )
        if job is None:
            raise S12ExportSubmitError(
                f"durable Job replay lookup found no Job for key {key!r}"
            )
        return JobRepository(session).get_job(job.id)


def _s12_export_handler(ctx: Any) -> dict[str, Any]:
    """Execute one S12 export job: claim → render/resume → PUBLISH.

    Real production publisher (C2 F01): the handler is the ONLY caller of
    :func:`publish_export_run <app.services.s12_export.publication.publish_export_run>`
    on the normal worker path.  The runner assembles a PRIVATE candidate
    under the scratch dir; publication validates it source-locked and, on
    PASS, atomically moves it to the public output and completes the run.
    The durable job completes AFTER the run reached ``completed`` — states
    always agree (M13 closed).

    A restart re-claims the expired lease and resumes from the T03B
    checkpoint.  Failures raise so the durable worker records the failed
    job; the run lands ``failed`` (retryable) when publication rejects.
    """
    from app.persistence.s12_export import S12ExportRepository  # noqa: PLC0415
    from app.services.s12_export.publication import (  # noqa: PLC0415
        _publication_receipt_path,
        publish_export_run,
    )
    from app.services.s12_export.runner import (  # noqa: PLC0415
        ExportRunner,
        RunnerConfig,
        cleanup_owned_export_artifacts,
    )

    manifest = ctx.input_manifest
    run_id = str(manifest["run_id"])
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    factory = getattr(ctx, "session_factory", None)
    if factory is None:
        raise RuntimeError("s12 export handler requires a session factory")

    with factory() as session:
        repo = S12ExportRepository(session)
        lease = repo.claim_run(
            run_id,
            ctx.worker_id,
            job_id=getattr(ctx, "job_id", None),
        )
        session.commit()
        claimed_run = repo.get_run(run_id)
        owner_scratch = (
            Path(str(manifest["scratch_dir"]))
            / f"attempt-{claimed_run.attempt}-fence-{lease.fence_token}"
        )
        owned_manifest = dict(manifest)
        owned_manifest["scratch_dir"] = str(owner_scratch)
        owned_manifest["candidate_path"] = str(owner_scratch / "candidate_final.mp4")
        owned_manifest["attempt"] = int(claimed_run.attempt)
        # The runner writes its assembly to a PRIVATE candidate under the
        # server-owned scratch dir — never to the public output (C2 F07).
        candidate_path = _candidate_for(owned_manifest)
        cfg = RunnerConfig(
            run_id=run_id,
            workspace_id=workspace_id,
            worker_id=ctx.worker_id,
            fence_token=lease.fence_token,
            source_path=str(manifest["source_path"]),
            fps=float(manifest["fps"]),
            chunk_dir=str(manifest["chunk_dir"]),
            scratch_dir=str(owner_scratch),
            output_path=str(candidate_path),
            audio_source=manifest.get("audio_source"),
            max_frames_per_chunk=int(manifest.get("max_frames_per_chunk", 120)),
            overlap_frames=int(manifest.get("overlap_frames", 4)),
            extra={
                "fence_token": lease.fence_token,
                "attempt": str(claimed_run.attempt),
            },
        )
        try:
            ExportRunner(repo, cfg).resume()
            session.commit()
            outcome = publish_export_run(
                session,
                run_id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                worker_id=ctx.worker_id,
                fence_token=lease.fence_token,
                manifest=owned_manifest,
            )
            session.commit()
        except Exception:
            # Coherent states: ordinary render/publication failure lands the
            # run ``failed`` (retryable) under the fence.  An uncertain
            # filesystem/SQLite boundary deliberately remains resumable.
            try:
                rec = repo.get_run(run_id)
                # A rename + receipt followed by a DB commit exception is an
                # uncertain filesystem/SQLite boundary.  Keep the run
                # resumable so a fresh owner can revalidate and reconcile it;
                # never downgrade a recoverable publication to failed and
                # strand an immutable-looking public file.
                final = Path(str(owned_manifest.get("output_path") or ""))
                uncertain_publication = (
                    rec.status in ("running", "verifying")
                    and final.is_file()
                    and _publication_receipt_path(final).is_file()
                )
                if not uncertain_publication:
                    repo.transition_run(
                        run_id,
                        "failed",
                        actor=ctx.worker_id,
                        expected_revision=rec.revision,
                        fence_token=lease.fence_token,
                    )
                    session.commit()
            except Exception:
                # Lost the fence mid-failure (fresh owner reclaimed): the
                # run is owned elsewhere; nothing more to mutate.
                session.rollback()
            cleanup_owned_export_artifacts(
                scratch_dir=owned_manifest.get("scratch_dir"),
                chunk_dir=owned_manifest.get("chunk_dir"),
                candidate_path=owned_manifest.get("candidate_path"),
                repository=repo,
                owner_run_id=run_id,
                owner_worker_id=ctx.worker_id,
                owner_fence_token=lease.fence_token,
            )
            raise
    return {
        "run_id": run_id,
        "status": outcome["status"],
        "output_path": str(outcome.get("output_path") or ""),
        "artifact_sha256": str(outcome.get("artifact_sha256") or ""),
        "verdict": str(outcome.get("verdict") or ""),
        "frame_count": int(manifest["frame_count"]),
    }


def _candidate_for(manifest: dict[str, Any]) -> Path:
    """Private candidate path for the runner's assembly (never public)."""
    scratch = Path(str(manifest["scratch_dir"]))
    scratch.mkdir(parents=True, exist_ok=True)
    candidate = Path(str(manifest.get("candidate_path") or scratch / "candidate_final.mp4"))
    if candidate.resolve().parent != scratch.resolve():
        raise RuntimeError("candidate path must be a direct child of owned scratch")
    return candidate


def register_s12_export_handler(worker: Any) -> None:
    """Register the S12 export handler on a DurableWorker instance."""
    worker.register_handler(S12_EXPORT_JOB_TYPE, _s12_export_handler)


def reconcile_export_jobs(
    session_factory: Callable[[], Any],
    *,
    batch_size: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normal-startup S12 recovery scan (C2 F05/F01, zero-mutation).

    The T03A C2 fencing contract makes recovery self-healing: a fresh
    ``claim_run`` CAS re-claims an expired/released lease on a ``running``
    run (exactly one winner; losers never mutate).  This reconciler is the
    REAL production startup caller that reports every resumable orphan —
    a ``running`` run whose lease ``expires_at`` has passed — so the
    restarted worker's job claim resumes it from the T03B checkpoint.

    It NEVER calls ``release_lease`` (live-lease fencing) and NEVER flips a
    run status: expired leases are reported as ``expired``/``resumable``,
    live leases are skipped, terminal runs are untouched.  Bounded,
    restart-safe, never raises: per-run failures are recorded on the report
    and the pass continues.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.persistence.models import (  # noqa: PLC0415
        S12ExportLease,
        S12ExportRun,
    )

    report: dict[str, Any] = {"scanned": 0, "expired": 0, "resumable": [], "errors": []}
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
                (row.run_id, row.worker_id, row.expires_at)
                for row in rows
            ]
    except Exception as exc:
        report["errors"].append({"stage": "scan", "error": str(exc)})
        return report
    report["scanned"] = len(candidates)
    for run_id, _worker_id, expires_at in candidates:
        exp = expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp > moment:
            continue
        # Expired lease on a running run: a fresh claim resumes from the
        # checkpoint — record the resumable orphan, mutate nothing.
        report["expired"] += 1
        report["resumable"].append(run_id)
    return report

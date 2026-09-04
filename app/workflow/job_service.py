"""API-compatible durable job service for the S02-T05 cutover.

This module replaces the legacy in-memory ``JobService`` as the API's job
dependency.  It keeps the API surface (``create_job``/``get_job``/
``cancel_job``) so routes keep working, but every Job is a **durable row**
created through the S02-T02 ``JobRepository`` with a schema-versioned
``input_manifest``; execution happens exclusively in the S02-T03
``DurableWorker`` after a restart-safe reconciliation (S02-T04).  No
authoritative job truth remains in RAM and no closure is ever accepted as
a job definition after cutover (contract §11.2, AC2/AC6).

**Laziness (PM CHANGES_REQUESTED #2):** constructing a ``JobService``
never creates a directory, an engine, a database file, or a thread.  The
owned engine/session-factory are created only by :meth:`initialize`
(explicit lifecycle / fixture setup), and the worker poll loop only by
:meth:`start_worker`.

**Migration policy (PM CHANGES_REQUESTED #3):** :meth:`initialize`
follows the S01 domain contract — a missing database may bootstrap; an
existing database with a pending revision is **backed up first** (same
directory, collision-safe name, fsync, sha256+size evidence, verified
copy) and only then upgraded; a backup failure aborts the upgrade; a
database already at head performs no redundant backup.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.persistence import (
    InvalidStateTransition,
    JobNotFoundError,
    JobRepository,
    StepInput,
)
from app.schemas import JobInfo, JobState
from app.workflow.durable_worker import DurableWorker
from app.workflow.job_handlers import (
    JOB_TYPE_INGEST,
    JOB_TYPE_PREVIEW,
    JOB_TYPE_PROPAGATE,
    JOB_TYPE_RENDER,
    register_api_handlers,
)

__all__ = [
    "JOB_TYPE_INGEST",
    "JOB_TYPE_PREVIEW",
    "JOB_TYPE_PROPAGATE",
    "JOB_TYPE_RENDER",
    "BackupEvidence",
    "JobService",
]

#: The single default step code every API Job uses (one-step Jobs are the
#: faithful mapping of the legacy single-closure jobs).
_DEFAULT_STEP_CODE = "run"

#: Bounded re-reads for the guarded cancel transition (S08-R01): a cancel
#: racing the worker's claim/completion re-reads the live row instead of
#: surfacing a spurious conflict (contract §6.3 first-writer-wins).
_CANCEL_TRANSITION_RETRIES = 3


def _step_plan() -> list[StepInput]:
    """The default one-step plan for API Jobs (position 0, sync)."""
    return [StepInput(step_code=_DEFAULT_STEP_CODE, position=0, step_type="sync")]


def _sha256_file(path: Path) -> str:
    """Compute the sha256 of a file in bounded chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database_file(source: Path, destination: Path) -> None:
    """Copy the database file (collision-safe destination already chosen).

    Separated so tests can inject a failure to prove the no-upgrade path.
    """
    shutil.copy2(str(source), str(destination))


def _backup_database(path: Path) -> BackupEvidence:
    """Create and verify a collision-safe on-disk backup of *path*.

    Returns the evidence (backup path, sha256, size).  Raises
    ``RuntimeError`` when the backup or its verification fails — the
    caller must not proceed with the upgrade (S01 migration policy).
    """
    import os

    backup = path.with_name(
        f"{path.name}.bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    try:
        _copy_database_file(path, backup)
        # fsync the copied bytes (Windows: open via os.open with O_RDWR —
        # os.fsync requires a writable fd on Windows).
        fd = os.open(backup, os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise RuntimeError(
            f"database backup failed for {path.name}: {exc}; refusing to upgrade"
        ) from exc
    try:
        sha = _sha256_file(backup)
        size = backup.stat().st_size
    except OSError as exc:
        raise RuntimeError(
            f"database backup verification failed for {backup.name}: {exc}; "
            "refusing to upgrade"
        ) from exc
    if sha != _sha256_file(path) or size != path.stat().st_size:
        raise RuntimeError(
            f"database backup verification failed for {backup.name}: "
            "checksum/size mismatch; refusing to upgrade"
        )
    return BackupEvidence(backup_path=backup, sha256=sha, size_bytes=size)


class BackupEvidence:
    """Evidence of a verified pre-upgrade database backup."""

    def __init__(self, backup_path: Path, sha256: str, size_bytes: int) -> None:
        self.backup_path = backup_path
        self.sha256 = sha256
        self.size_bytes = size_bytes


class JobService:
    """Durable job service — the API's submit/poll/cancel surface.

    Construction is side-effect free.  The owned engine, database file and
    worker poll loop are created only by explicit lifecycle operations
    (:meth:`initialize`, :meth:`start_worker`) — never at import time.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        worker: DurableWorker | None = None,
        *,
        managed_root: str | Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._owns_factory = session_factory is None
        self._database_path: Path | None = None
        self._engine: Any = None
        self._worker = worker
        # S08-R01 AC5: the DEFAULT managed artifact root resolves from the
        # configured absolute project root (app.config / deps._config) —
        # never from the process CWD (the T06 incident: a QA backend
        # launched without cd wrote uploads/staging into the worktree root).
        resolved_root = _default_managed_root() if managed_root is None else Path(managed_root)
        # S08-R01 AC6 fail-closed: in QA/test mode the effective roots must
        # be explicit, absolute and isolated from the protected MAIN tree.
        # Only the managed root is guarded here (side-effect-free
        # construction); the project root is guarded in ``_ensure_engine``
        # exactly when the service resolves its default database path.
        _validate_service_roots(None, resolved_root)
        if self._worker is None:
            from app.workflow.durable_worker import WorkerConfig  # noqa: PLC0415

            # The worker is constructed lazily too; the session factory is
            # only resolved at initialize()/first use, so a placeholder is
            # acceptable for pure construction.
            def _placeholder() -> Session:
                raise RuntimeError("job service not initialized")  # pragma: no cover

            self._worker = DurableWorker(
                session_factory or _placeholder,
                config=WorkerConfig(staging_root=resolved_root),
            )
            register_api_handlers(self._worker)
            # The ANALYZE_MEDIA dispatcher (S05-T04) routes the approved
            # import step to the S05-T02 handler and the scene_detect step to
            # the scene-detection handler — one registered handler per job
            # class (the worker dispatches by job_type).
            from app.services.scene_detector import register_scene_detection_handler

            register_scene_detection_handler(self._worker)
            from app.services.video_proxy import register_generate_proxy_handler

            register_generate_proxy_handler(self._worker)
            # The DISCOVER_OBJECTS handler (S08-T02): deterministic CI
            # adapter + explicit production capability/provider path; the
            # worker dispatches by job_type to this registered handler.
            from app.services.object_extraction import (
                register_discover_objects_handler,
            )

            register_discover_objects_handler(self._worker)
            # The RECOMPUTE_OBJECTS handler (S08-T05): targeted correction
            # recompute — regenerates ONLY the invalidated derived state of
            # one correction (suggestions/artifacts); minimal registration,
            # same pattern as the S05/S08 handlers.
            from app.services.object_correction import (
                register_recompute_objects_handler,
            )

            register_recompute_objects_handler(self._worker)
            # The ATTACH_ORIGINAL_AUDIO handler (S11-T01C): durable wiring of
            # the S11-T01B original-audio remux engine — thin adapter, one
            # registered handler per job type (the worker dispatches by
            # job_type), verified-publication completion gate included.
            from app.workflow.original_audio_handler import (
                register_attach_original_audio_handler,
            )

            register_attach_original_audio_handler(self._worker)
            # The RUN_QC_CHECKS handler (S11-T03G): durable check-run
            # wiring of the T03F orchestrator — thin server-owned adapter,
            # one registered handler per job type (the worker dispatches by
            # job_type), completion evidence written via the standard
            # JobAttempt result / step checkpoint path.
            from app.workflow.qc_checks_handler import register_qc_checks_handler

            register_qc_checks_handler(self._worker)
            # S11-C4-A: the QC detector band is production-owned state, not
            # test-fixture state — a clean process starts with an EMPTY
            # detector registry, so constructing the production JobService
            # deterministically registers the binding FULL band (idempotent,
            # conflict fail-closed) before any RUN_QC_CHECKS handler runs.
            from app.workflow.qc_checks_handler import (
                ensure_full_band_registered,
            )

            ensure_full_band_registered()
            from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

            register_s10_full_apply_handler(self._worker)
        self._worker_owned = worker is None
        self._managed_root = resolved_root

    # ── Lifecycle (AC1: explicit bootstrap + shutdown) ────────────────────

    @property
    def database_path(self) -> Path | None:
        """The SQLite file backing this service (None until initialized)."""
        return self._database_path

    @property
    def session_factory(self) -> Callable[[], Session] | None:
        """The bound session factory (public, explicit binding contract).

        ``None`` only before :meth:`initialize` (or an explicit
        ``bind``); after initialization every caller — the worker, the
        reconciler and the chain orchestrator — resolves the SAME factory
        through this public property (S05-C04).  Never inspect
        ``_session_factory`` directly from outside this class.
        """
        return self._session_factory

    @property
    def managed_root(self) -> Path:
        """The managed artifact root bound to this service (public).

        The durable worker and the ``AnalyzeChainOrchestrator`` resolve
        the SAME root through this public property (S05-C04).  Never
        inspect ``_managed_root`` directly from outside this class.
        """
        return self._managed_root

    @property
    def last_backup(self) -> BackupEvidence | None:
        """Evidence of the most recent pre-upgrade backup (or None)."""
        return getattr(self, "_last_backup", None)

    def _ensure_engine(self) -> None:
        """Create the owned engine/session factory on first explicit use.

        Side-effect free until called; the parent directory is created
        here (explicit operation), the database file itself only by
        :meth:`initialize` (Alembic).  An explicitly pre-set
        ``_database_path`` (tests / embedding) is honoured.

        **S05-C04 public lifecycle binding:** a default ``JobService()``
        constructed its ``DurableWorker`` with a PLACEHOLDER session
        factory (raises ``RuntimeError("job service not initialized")``).
        The real factory created here REBINDS that worker through the
        public :meth:`DurableWorker.bind_session_factory` so the
        production path (``uvicorn app.main:app``) starts a worker bound
        to the real database — no stale placeholder remains.
        """
        if self._session_factory is not None:
            return
        from app.persistence import create_engine_for_path, create_session_factory  # noqa: PLC0415

        if self._database_path is None:
            # S08-R01 AC6: guard the configured project root exactly when
            # the service resolves its default database path from it — a
            # QA/test process can never bootstrap the protected MAIN
            # database.  An explicitly pre-set ``_database_path`` (tests /
            # embedding) is the caller's explicit isolated target.
            _validate_service_roots(_project_root(), self._managed_root)
            self._database_path = _project_root() / "data" / "motionforge.db"
        db_path = self._database_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # S05-C04: the default managed root must exist — the import/proxy
        # handlers stat it (disk-safety check) and publish into it.  The
        # QA launcher used to pre-create it by hand; the default
        # production path ensures it.  S08-R01: the root resolves from the
        # configured absolute project root (never the process CWD).
        self._managed_root.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine_for_path(db_path)
        self._session_factory = create_session_factory(self._engine)
        if self._worker_owned and self._worker is not None:
            self._worker.bind_session_factory(self._session_factory)

    def initialize(self) -> None:
        """Run the approved bootstrap path with the S01 migration policy.

        1. A missing database bootstraps directly (Alembic upgrade).
        2. An existing database already at head is a no-op (no redundant
           backup).
        3. An existing database with a pending revision is backed up
           (collision-safe copy, fsync, sha256+size evidence, verified)
           BEFORE Alembic runs; a backup failure aborts the upgrade.
        4. A database newer than the application supports is refused
           before anything is touched.

        Idempotent and explicit — never runs at import time.
        """
        from alembic import command  # noqa: PLC0415
        from alembic.config import Config  # noqa: PLC0415

        from app.persistence import (  # noqa: PLC0415
            assert_schema_revision_supported,
            database_schema_revision,
        )

        self._ensure_engine()
        if self._database_path is None:
            return  # injected factory: the caller owns the bootstrap

        root = Path(__file__).resolve().parent.parent.parent
        migrations = root / "migrations"
        db = self._database_path

        if db.exists():
            # Never touch a database created by a NEWER app version.
            assert_schema_revision_supported(self._engine, migrations, db)
            current = database_schema_revision(self._engine)
            if current is None:
                raise RuntimeError(
                    f"database {db.name} exists but has no alembic_version "
                    "table; refusing implicit initialization"
                )
            supported = _max_revision(migrations)
            if current == supported:
                return  # already at head — no redundant backup (policy #2)

        # Missing DB (bootstrap) or pending revision: ensure the parent
        # exists and back up an existing DB before upgrading (policy #3).
        db.parent.mkdir(parents=True, exist_ok=True)
        if db.exists():
            self._last_backup = _backup_database(db)

        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(migrations))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
        command.upgrade(cfg, "head")

    def start_worker(self) -> None:
        """Start the background durable worker poll loop (explicit)."""
        if self._worker is not None:
            # The default per-service engine must be at the head revision
            # before the worker can query the durable queue.
            if getattr(self, "_database_path", None) is not None:
                self.initialize()
            self._worker.start()

    def stop_worker(self, timeout: float | None = 5.0) -> None:
        """Signal and join the worker poll loop (shutdown, AC1)."""
        if self._worker is not None:
            self._worker.stop(timeout=timeout)

    @property
    def worker(self) -> DurableWorker | None:
        """The bound DurableWorker (None only in degenerate injections)."""
        return self._worker

    @property
    def worker_running(self) -> bool:
        """True while the worker's background poll loop is alive."""
        return bool(self._worker is not None and self._worker.running)

    # ── API surface (durable submit/poll/cancel) ──────────────────────────

    def create_job(
        self,
        job_type: str,
        input_manifest: dict[str, Any],
        **kwargs: Any,
    ) -> JobInfo:
        """Create a durable Job and return its API JobInfo.

        The manifest is the durable input identity (contract §3); the
        registered handler for *job_type* executes it in the worker.  A
        job type without a registered handler fails safely with
        ``UNKNOWN_HANDLER`` (never runs nothing).  No callable/closure is
        accepted — every job is reconstructable from durable inputs.

        Keyword arguments mirror the repository: ``workspace_id``,
        ``owner_type``, ``owner_id``, ``idempotency_key``,
        ``input_generation``, ``priority``, ``max_attempts``.
        """
        if not isinstance(input_manifest, dict):
            raise TypeError("input_manifest must be a dict")
        self._ensure_engine()
        manifest = dict(input_manifest)
        manifest.setdefault("schema_version", 1)
        manifest.setdefault("managed_root", str(self._managed_root))
        manifest.setdefault("project_root", str(_project_root()))

        workspace_id = str(kwargs.pop("workspace_id", "default"))
        owner_type = str(kwargs.pop("owner_type", "project"))
        owner_id = str(kwargs.pop("owner_id", "legacy"))
        idempotency_key = kwargs.pop("idempotency_key", None)
        input_generation = kwargs.pop("input_generation", None)
        priority = int(kwargs.pop("priority", 50))
        max_attempts = int(kwargs.pop("max_attempts", 3))

        self._ensure_workspace(workspace_id)
        with self._session_factory() as session:  # type: ignore[misc]
            repo = JobRepository(session)
            job = repo.create_job(
                workspace_id=workspace_id,
                job_type=job_type,
                owner_type=owner_type,
                owner_id=owner_id,
                input_manifest=manifest,
                idempotency_key=idempotency_key,
                input_generation=input_generation,
                priority=priority,
                max_attempts=max_attempts,
                steps=_step_plan(),
                actor="api",
            )
            session.commit()
            return self._job_info(job)

    def _ensure_workspace(self, workspace_id: str) -> None:
        """Create the workspace row on demand (idempotent, one commit).

        Jobs are scoped to exactly one workspace (contract §3) and the
        ``workspace_id`` FK is RESTRICT; the API service uses the logical
        workspace ``"default"`` for the legacy project workflow.  A missing
        row would fail every Job insert, so it is created on first use.
        """
        from sqlalchemy import select  # noqa: PLC0415

        from app.persistence.models import Workspace  # noqa: PLC0415

        with self._session_factory() as session:  # type: ignore[misc]
            exists = session.scalar(
                select(Workspace.id).where(Workspace.id == workspace_id)
            )
            if exists is None:
                session.add(Workspace(id=workspace_id, name=workspace_id))
                session.commit()

    def get_job(self, job_id: str) -> JobInfo | None:
        """Return API JobInfo for a durable Job, or None when unknown."""
        self._ensure_engine()
        with self._session_factory() as session:  # type: ignore[misc]
            repo = JobRepository(session)
            try:
                job = repo.get_job(job_id)
            except JobNotFoundError:
                return None
            return self._job_info(job)

    def cancel_job(self, job_id: str) -> bool:
        """Durably request cancellation (legacy semantics preserved).

        Returns True when the durable ``queued|running -> cancelling``
        transition was applied (or the Job is already ``cancelling`` —
        idempotent second cancel, contract §6.3), False when the Job is
        unknown or already terminal (contract §6.2 / §11.2: 200
        cancel_requested, 400/404).

        S08-R01: the guarded transition is retried over a bounded window —
        a cancel racing the durable worker's claim (``queued -> running``)
        re-reads the live row and cancels the now-running Job instead of
        surfacing a spurious conflict (contract §6.3: cancel wins; the
        first committed writer wins, the loser re-reads).
        """
        self._ensure_engine()
        assert self._session_factory is not None
        with self._session_factory() as session:
            repo = JobRepository(session)
            for _attempt in range(_CANCEL_TRANSITION_RETRIES):
                try:
                    job = repo.get_job(job_id)
                except JobNotFoundError:
                    return False
                if job.state in ("cancelled", "completed", "failed"):
                    return False
                if job.state == "cancelling":
                    # Second cancel while cancelling is an idempotent no-op
                    # (contract §6.3: 200-style while cancelling).
                    return True
                if job.state not in ("queued", "running"):
                    return False
                try:
                    repo.transition_job(
                        job_id,
                        "cancelling",
                        actor="api",
                        expected_revision=job.revision,
                        reason_code="CANCEL_REQUESTED",
                    )
                    session.commit()
                    return True
                except InvalidStateTransition:
                    # The job changed state under us (worker claim,
                    # completion or another cancel): re-read and retry.
                    session.rollback()
                    continue
            # Exhausted retries: report the final observed state honestly
            # (the API maps False to a 400 with the live state).
            try:
                final = repo.get_job(job_id)
            except JobNotFoundError:
                return False
            return final.state == "cancelling"

    def cancel_run_atomic(
        self,
        session: Session,
        *,
        run_writer: Callable[[], None],
        job_key: str,
    ) -> dict[str, Any]:
        """Atomically cancel the durable job and the S10 run in ONE transaction.

        S10-C6A F1 correction: the legacy route applied the run cancel in the
        request session and *then* opened a second writer for the durable job
        cancel — on rollback-journal SQLite that is a deterministic
        ``database is locked`` deadlock (run writer RESERVED, job writer needs
        EXCLUSIVE while a stale reader holds SHARED).  A swallowed failure then
        returned ``cancelled: true`` while the durable job kept running.

        This method collapses the whole lifecycle transition into the
        *caller's* transaction (``session`` — the API request session bound to
        the same SQLite database as the durable job rows):

        1. The owned durable Job (idempotency key ``job_key``) is looked up
           and, when ``queued|running``, transitioned ``-> cancelling`` via
           :meth:`JobRepository.transition_job` on the SAME session (no
           commit — a single connection cannot deadlock itself by
           construction).  ``cancelling`` is an idempotent no-op; terminal
           states are recorded honestly and never rewritten.
        2. ``run_writer()`` then applies the run-side cancel on the same
           session (validated by the FullApplyService; flushes the row).
        3. The CALLER commits both atomically — commit yields BOTH
           run-cancelled and job-cancelling/cancelled; rollback yields
           NEITHER.  False success is impossible because the durable
           cancellation signal shares the run-cancel transaction.

        Returns a coherent result dict::

            {"job_seen": bool,    # durable job row exists for this run
             "job_state": str|None}  # live job state seen in this transaction

        Fail-closed: any ``InvalidStateTransition`` or lock error re-raises —
        the caller rolls the whole transaction back and surfaces HTTP 4xx/5xx.
        """
        from sqlalchemy import select as _select  # noqa: PLC0415

        from app.persistence.models import Job as _Job  # noqa: PLC0415

        job_id = session.scalar(_select(_Job.id).where(_Job.idempotency_key == job_key))
        job_state: str | None = None
        if job_id is not None:
            repo = JobRepository(session)
            for _attempt in range(_CANCEL_TRANSITION_RETRIES):
                current = repo.get_job(str(job_id))
                job_state = current.state
                if current.state not in ("queued", "running"):
                    # cancelling (idempotent no-op) or terminal (recorded
                    # honestly, never rewritten — contract §6.2/§6.3).
                    break
                try:
                    repo.transition_job(
                        str(job_id),
                        "cancelling",
                        actor="api",
                        expected_revision=current.revision,
                        reason_code="CANCEL_REQUESTED",
                    )
                    job_state = "cancelling"
                    break
                except InvalidStateTransition:
                    # Lost a revision race against the worker claim/terminal
                    # transition: re-read the live row and retry within the
                    # bounded window (cancel wins, §6.3).  Exhaustion raises
                    # — fail-closed, never a silent fake success.
                    if _attempt == _CANCEL_TRANSITION_RETRIES - 1:
                        raise
        run_writer()
        return {"job_seen": job_id is not None, "job_state": job_state}

    # ── Internal helpers ──────────────────────────────────────────────────

    def _job_info(self, job: Any) -> JobInfo:
        """Map a durable JobRecord to the legacy API JobInfo shape.

        ``state`` is the durable state (JobState enum extended with
        ``pending``; ``fenced`` is hidden — the reconciler resolves it
        before any poll observes it, contract §4.5-6).  ``result_path`` is
        populated from the manifest's legacy result path when the Job
        completed; ``error`` is the envelope's message for string
        compatibility (additive fields never change legacy field meaning).
        """
        state = JobState(job.state) if job.state in JobState._value2member_map_ else JobState.QUEUED
        error: str | None = None
        if job.error is not None:
            err = job.error.get("message") if isinstance(job.error, dict) else job.error
            error = str(err) if err else None
        result_path: str | None = None
        if job.state == "completed" and isinstance(job.input_manifest, dict):
            candidate = job.input_manifest.get("result_path") or job.input_manifest.get(
                "legacy_result_path"
            )
            if isinstance(candidate, str) and candidate:
                result_path = candidate
        return JobInfo(
            job_id=job.id,
            state=state,
            progress=job.progress,
            message=_job_message(job),
            result_path=result_path,
            error=error,
            job_type=job.job_type,
        )


def _job_message(job: Any) -> str:
    """Derive the legacy ``message`` string from a durable Job state."""
    state = job.state
    if state == "queued":
        return "Queued"
    if state == "running":
        return "Running"
    if state == "cancelling":
        return "Cancelling"
    if state == "cancelled":
        return "Cancelled"
    if state == "completed":
        return "Completed"
    if state == "failed":
        err = job.error.get("message") if isinstance(job.error, dict) else job.error
        return f"Failed: {err}" if err else "Failed"
    return "Pending"


def _project_root() -> Path:
    """Resolve the active project root for the owned database path.

    Uses the application config when available (production) and falls back
    to the config default so tests injecting a patched ``deps._config`` see
    the same root the workflow services use.
    """
    try:
        from app.api import deps  # noqa: PLC0415

        return Path(deps._config.project_root)
    except Exception:
        from app.config import config as _cfg  # noqa: PLC0415

        return Path(_cfg.project_root)


def _default_managed_root() -> Path:
    """The default managed artifact root (S08-R01 AC5).

    Resolves from the configured absolute project root — ``<project
    root>/artifacts`` — NEVER from the process CWD.  The worker, the
    reconciler, the chain orchestrator, the APIs and the manifests all
    resolve this same public root through the owning :class:`JobService`.
    """
    return _project_root() / "artifacts"


def _validate_service_roots(
    project_root: Path | None, managed_root: Path
) -> None:
    """Fail-closed QA/test root guard for one JobService (S08-R01 AC6).

    In QA/test mode the effective project root (when this service owns the
    database) and the managed artifact root must be explicit, absolute and
    isolated from the protected MAIN tree.  Explicit QA mode additionally
    requires the project root to come from ``MOTIONFORGE_ROOT`` — QA
    launchers may never rely on defaults or ``cd`` for storage
    correctness.
    """
    from app.config import qa_mode_enabled, validate_runtime_roots

    validate_runtime_roots(
        project_root,
        managed_root,
        require_env_project_root=qa_mode_enabled(),
    )


def _max_revision(migrations: Path) -> str | None:
    """Return the head revision of the bundled Alembic scripts."""
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    return ScriptDirectory(str(migrations)).get_current_head()

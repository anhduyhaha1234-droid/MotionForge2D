"""S08-R01 — queued-cancel drain regression (generic durable-job lifecycle).

Codex sprint-exit finding (S08-T02/T05 deviation): a cancel arriving while
a Job is still ``queued`` transitions it to ``cancelling`` but the job
never self-drains — the worker only claims ``queued`` rows and the
reconciler only fences leased rows, so a never-claimed ``cancelling`` Job
sat pending forever (every job type affected; DISCOVER_OBJECTS and
RECOMPUTE_OBJECTS included).

The generic fix (engine-level, not handler-level):

1. The worker's claim scan falls back to UNLEASED ``cancelling`` Jobs
   (cancel-before-claim leaves no lease row) and drains them straight to
   terminal ``cancelled`` with ZERO handler effects; the drain's lease is
   released atomically with the terminal transition (no orphan lease).
2. The reconciler resolves unleased ``cancelling`` Jobs directly to
   ``cancelled`` — no worker needs to be alive, and no lease is created.
3. Restart coverage: a fresh worker/reconciler over the same database
   drains a pre-cancel Job left behind by a dead process.

These tests prove the full regression matrix on REAL durable rows over
temporary Alembic-migrated databases and temporary managed roots — never
mocks, never the production database or ``channels.json``:

- create queued Job -> cancel before claim -> worker claim -> cancelled,
  zero effects, no orphan lease;
- create queued Job -> cancel before claim -> reconciler pass -> cancelled,
  zero effects, no lease row ever created;
- create queued Job -> cancel -> fresh process (new engine/factory/worker)
  -> cancelled, zero effects;
- idempotent second cancel while cancelling; cancel of a terminal Job is
  rejected (False);
- cancel racing the worker's claim: cancel wins, terminal cancelled;
- DISCOVER_OBJECTS and RECOMPUTE_OBJECTS covered by the same generic fix
  (real registered handlers, zero durable effects).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence import (
    JobRepository,
    create_engine_for_path,
    create_session_factory,
)
from app.persistence.models import (
    Artifact,
    ObjectOccurrence,
    ObjectRole,
)
from app.workflow.durable_worker import DurableWorker, WorkerConfig
from app.workflow.job_reconciler import JobReconciler, ReconcileConfig
from app.workflow.job_service import JobService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return cfg


def _upgrade(database_path: Path) -> None:
    command.upgrade(_alembic_config(database_path), "head")


# ── Fixtures (isolated DB + managed root per test) ───────────────────────────


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "s08r01-queued-cancel.db"


@pytest.fixture()
def session_factory(db_path: Path) -> Callable[[], Session]:
    _upgrade(db_path)
    return create_session_factory(create_engine_for_path(db_path))


@pytest.fixture()
def managed_root(tmp_path: Path) -> Path:
    root = tmp_path / "managed"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture()
def effects() -> dict[str, int]:
    """Effect counters shared with the counting handler (zero-effects proof)."""
    return {"runs": 0}


def _counting_worker(
    session_factory: Callable[[], Session],
    managed_root: Path,
    effects: dict[str, int],
) -> DurableWorker:
    worker = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="s08r01-qc-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
    )

    def handler(ctx):  # type: ignore[no-untyped-def]
        effects["runs"] += 1
        staged = ctx.staging_dir()
        (staged / "effect.txt").write_text("ran", encoding="utf-8")
        ctx.progress(100, "done")
        return {"ran": True}

    worker.register_handler("TEST_QC_HANDLER", handler)
    return worker


def _staging_files(managed_root: Path) -> list[Path]:
    staging = managed_root / "staging"
    if not staging.is_dir():
        return []
    return [p for p in staging.rglob("*") if p.is_file()]


def _table_counts(session_factory: Callable[[], Session]) -> dict[str, int]:
    with session_factory() as s:
        return {
            "object_role": int(s.scalar(select(func.count()).select_from(ObjectRole)) or 0),
            "object_occurrence": int(
                s.scalar(select(func.count()).select_from(ObjectOccurrence)) or 0
            ),
            "artifact": int(s.scalar(select(func.count()).select_from(Artifact)) or 0),
        }


def _job_state(session_factory: Callable[[], Session], job_id: str) -> str:
    with session_factory() as s:
        job = JobRepository(s).get_job(job_id)
        return job.state


def _lease(session_factory: Callable[[], Session], job_id: str):
    with session_factory() as s:
        return JobRepository(s).get_lease(job_id)


# ── The core regression: cancel-before-claim reaches cancelled ───────────────


def test_queued_cancel_worker_claim_drains_zero_effects_no_orphan_lease(
    session_factory, managed_root, effects
) -> None:
    """create queued -> cancel before claim -> worker claim -> cancelled,
    zero handler effects, steps cancelled, no orphan live lease."""
    worker = _counting_worker(session_factory, managed_root, effects)
    svc = JobService(session_factory, worker=worker, managed_root=managed_root)
    info = svc.create_job(
        "TEST_QC_HANDLER",
        input_manifest={"schema_version": 1, "payload": "queued-cancel"},
    )
    assert info.state.value == "queued"

    assert svc.cancel_job(info.job_id) is True
    assert svc.get_job(info.job_id).state.value == "cancelling"

    assert worker.run_once() == 1  # the drain claim counts as one claim

    # Deterministic terminal state; the handler NEVER ran.
    final = svc.get_job(info.job_id)
    assert final.state.value == "cancelled"
    assert effects["runs"] == 0
    assert _staging_files(managed_root) == []

    # Every step drained to cancelled (contract §4.4 drain chain).
    with session_factory() as s:
        repo = JobRepository(s)
        steps = repo.list_steps(info.job_id)
        assert len(steps) == 1
        assert all(step.state == "cancelled" for step in steps)
        assert repo.list_attempts(info.job_id) == []  # no attempt rows at all

    # No orphan live lease: the drain claim's lease was released.
    lease = _lease(session_factory, info.job_id)
    if lease is not None:
        expires = lease.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        assert expires <= datetime.now(UTC)


def test_queued_cancel_reconciler_resolves_zero_effects_no_lease(
    session_factory, managed_root, effects
) -> None:
    """create queued -> cancel before claim -> reconciler pass -> cancelled,
    zero effects, and NO lease row was ever created."""
    worker = _counting_worker(session_factory, managed_root, effects)
    svc = JobService(session_factory, worker=worker, managed_root=managed_root)
    info = svc.create_job(
        "TEST_QC_HANDLER",
        input_manifest={"schema_version": 1, "payload": "reconciler-drain"},
    )
    assert svc.cancel_job(info.job_id) is True
    assert _job_state(session_factory, info.job_id) == "cancelling"
    assert _lease(session_factory, info.job_id) is None  # never claimed

    reconciler = JobReconciler(
        session_factory, config=ReconcileConfig(fence_grace_seconds=0.0)
    )
    report = reconciler.reconcile_once()
    assert report.cancelled == 1
    assert report.fenced == 0
    assert report.requeued == 0
    assert report.errors == []

    assert _job_state(session_factory, info.job_id) == "cancelled"
    assert effects["runs"] == 0
    assert _staging_files(managed_root) == []
    assert _lease(session_factory, info.job_id) is None  # no orphan lease

    # A second pass is a no-op (terminal rows immutable, nothing scanned).
    report2 = reconciler.reconcile_once()
    assert report2.cancelled == 0 and report2.scanned == 0


def test_queued_cancel_restart_fresh_worker_drains(
    db_path, session_factory, managed_root, effects
) -> None:
    """A cancel committed before a process restart reaches cancelled under
    a FRESH engine/session factory/worker over the same database — the
    durable flag survives and the fresh worker drains with zero effects."""
    worker = _counting_worker(session_factory, managed_root, effects)
    svc = JobService(session_factory, worker=worker, managed_root=managed_root)
    info = svc.create_job(
        "TEST_QC_HANDLER",
        input_manifest={"schema_version": 1, "payload": "restart-drain"},
    )
    assert svc.cancel_job(info.job_id) is True
    # Simulate the crash: dispose the first generation's engine entirely.
    engine = session_factory().bind
    engine.dispose()
    assert _job_state(session_factory, info.job_id) == "cancelling"

    # Fresh generation: new engine + factory + worker over the SAME file.
    fresh_factory = create_session_factory(create_engine_for_path(db_path))
    fresh_effects: dict[str, int] = {"runs": 0}
    fresh_worker = _counting_worker(fresh_factory, managed_root, fresh_effects)
    assert fresh_worker.run_once() == 1

    assert _job_state(fresh_factory, info.job_id) == "cancelled"
    assert fresh_effects["runs"] == 0
    assert _staging_files(managed_root) == []
    lease = _lease(fresh_factory, info.job_id)
    if lease is not None:
        expires = lease.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        assert expires <= datetime.now(UTC)


def test_second_cancel_idempotent_then_terminal_cancel_rejected(
    session_factory, managed_root, effects
) -> None:
    """Second cancel while cancelling is an idempotent no-op (True); after
    the drain reaches terminal cancelled the cancel is rejected (False —
    the API maps it to 400)."""
    worker = _counting_worker(session_factory, managed_root, effects)
    svc = JobService(session_factory, worker=worker, managed_root=managed_root)
    info = svc.create_job(
        "TEST_QC_HANDLER",
        input_manifest={"schema_version": 1, "payload": "idempotent-cancel"},
    )
    assert svc.cancel_job(info.job_id) is True
    # Idempotent second cancel while cancelling (contract §6.3).
    assert svc.cancel_job(info.job_id) is True

    assert worker.run_once() == 1
    assert svc.get_job(info.job_id).state.value == "cancelled"
    # Terminal: cancel is rejected (400 semantics).
    assert svc.cancel_job(info.job_id) is False


def test_cancel_racing_worker_claim_cancel_wins(
    session_factory, managed_root, effects
) -> None:
    """A cancel racing the worker's queued->running claim lands either
    before the claim (drain claim, zero effects) or on the running job —
    the terminal state is always cancelled, never a pending forever-state,
    and the cancel result is True."""
    release = threading.Event()
    claimed = threading.Event()

    worker = DurableWorker(
        session_factory,
        config=WorkerConfig(
            worker_id="s08r01-race-worker",
            lease_ttl=60,
            heartbeat_interval=15,
            poll_interval=0.01,
            max_attempts=3,
            staging_root=managed_root,
        ),
    )

    def blocking_handler(ctx):  # type: ignore[no-untyped-def]
        effects["runs"] += 1
        claimed.set()
        release.wait(timeout=20)
        return {"ran": True}

    worker.register_handler("TEST_QC_HANDLER", blocking_handler)
    svc = JobService(session_factory, worker=worker, managed_root=managed_root)
    info = svc.create_job(
        "TEST_QC_HANDLER",
        input_manifest={"schema_version": 1, "payload": "claim-race"},
    )

    def claim_and_run() -> None:
        worker.run_once()

    thread = threading.Thread(target=claim_and_run, daemon=True)
    thread.start()
    try:
        assert claimed.wait(timeout=10)  # the worker holds the job
        # The job is running; the cancel transitions running -> cancelling
        # (the guard re-reads if the claim bumped the revision mid-cancel).
        assert svc.cancel_job(info.job_id) is True
    finally:
        release.set()
        thread.join(timeout=15)

    # The drain finishes after the held handler returns: terminal cancelled.
    assert _job_state(session_factory, info.job_id) == "cancelled"
    assert svc.cancel_job(info.job_id) is False


# ── S08 job types covered by the SAME generic fix ────────────────────────────


def test_discover_objects_queued_cancel_zero_effects(
    session_factory, managed_root
) -> None:
    """DISCOVER_OBJECTS cancelled while queued drains through the generic
    path: terminal cancelled, the real registered handler never runs, and
    no object role/occurrence/artifact rows are ever created."""
    # worker=None -> JobService registers the REAL production handlers
    # (register_api_handlers + scene + proxy + DISCOVER_OBJECTS +
    # RECOMPUTE_OBJECTS) on its own worker bound to the same factory/root.
    svc = JobService(session_factory, managed_root=managed_root)
    worker = svc.worker
    assert worker is not None

    before = _table_counts(session_factory)
    info = svc.create_job(
        "DISCOVER_OBJECTS",
        input_manifest={
            "schema_version": 1,
            "workspace_id": "default",
            "project_id": "proj-qc",
            "video_item_id": "vid-qc",
            "generation": "1",
            "extractor_version": "1.0.0",
            "provider": "deterministic",
            "source_sha256": "a" * 64,
        },
    )
    assert info.state.value == "queued"
    assert svc.cancel_job(info.job_id) is True
    assert worker.run_once() == 1

    final = svc.get_job(info.job_id)
    assert final.state.value == "cancelled"
    # Zero durable effects: no object intelligence rows, no artifacts, no
    # staging files — the handler never executed.
    assert _table_counts(session_factory) == before
    assert _staging_files(managed_root) == []


def test_recompute_objects_queued_cancel_zero_effects(
    session_factory, managed_root
) -> None:
    """RECOMPUTE_OBJECTS cancelled while queued drains through the generic
    path: terminal cancelled, the real registered handler never runs, and
    no object role/occurrence/artifact rows are ever created."""
    svc = JobService(session_factory, managed_root=managed_root)
    worker = svc.worker
    assert worker is not None

    before = _table_counts(session_factory)
    info = svc.create_job(
        "RECOMPUTE_OBJECTS",
        input_manifest={
            "schema_version": 1,
            "workspace_id": "default",
            "project_id": "proj-qc",
            "video_item_id": "vid-qc",
            "generation": "1",
            "correction_id": "corr-qc",
            "correction_type": "reassign",
            "affected_role_ids": ["role-qc"],
            "artifact_role_ids": ["role-qc"],
            "regenerate_suggestions": True,
        },
    )
    assert info.state.value == "queued"
    assert svc.cancel_job(info.job_id) is True
    assert worker.run_once() == 1

    final = svc.get_job(info.job_id)
    assert final.state.value == "cancelled"
    assert _table_counts(session_factory) == before
    assert _staging_files(managed_root) == []

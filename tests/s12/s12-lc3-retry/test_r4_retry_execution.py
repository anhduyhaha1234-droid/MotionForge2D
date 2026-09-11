"""R4 RETRY proof nodes for executable lineage and durable identity.

This module is fixture-only engineering evidence over isolated migrated DBs.
It does not claim normal-product authority, publication, or UI closure.
"""

# Pytest intentionally reuses the transferred module's ``env`` fixture.
# Ruff's F811 sees the fixture parameter as a same-name local redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_s12_t03c_c1_closure import (
    WS,
    _authority_body,
    _ready,
    env,  # noqa: F401
)

from app.api.routes import s12_export as route
from app.persistence.jobs import JobRepository
from app.persistence.models import Job, S12ExportRun
from app.persistence.s12_export import S12ExportError, S12ExportRepository
from app.services.s12_export import publication as publication_module
from app.services.s12_export import runner as runner_module
from app.workflow.durable_worker import DurableWorker, WorkerConfig


def _submit(factory: Any, svc: Any, manifest_id: str, auth: dict[str, str], dirs: dict[str, str]) -> Any:
    body = _authority_body(factory, auth, manifest_id)
    with factory() as session:
        response = route.submit_export(
            route.S12ExportSubmitRequest(**body), session, workspace_id=WS
        )
        session.commit()
    with factory() as session:
        run = S12ExportRepository(session).get_run(response["run_id"])
        job = JobRepository(session).get_job(response["job_id"])
    return run, job, response["created"]


def _cancel(factory: Any, svc: Any, run_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as session:
        route.cancel_export(run_id, session, workspace_id=WS, project_id=None)
        session.commit()


def _worker(factory: Any, managed: Path, monkeypatch: pytest.MonkeyPatch, failing: set[int], calls: list[int]) -> DurableWorker:
    class ProbeRunner:
        def __init__(self, repo: Any, config: Any) -> None:
            self.repo = repo
            self.config = config

        def resume(self) -> None:
            run = self.repo.get_run(self.config.run_id)
            calls.append(run.attempt)
            if run.attempt in failing:
                raise RuntimeError(f"R4 synthetic render failure at attempt {run.attempt}")
            self.repo.transition_run(
                run.id,
                "verifying",
                actor=self.config.worker_id,
                expected_revision=run.revision,
                fence_token=self.config.fence_token,
            )

    def complete_publication(session: Any, **kwargs: Any) -> dict[str, Any]:
        repo = S12ExportRepository(session)
        run = repo.get_run(kwargs["run_id"])
        repo.transition_run(
            run.id,
            "completed",
            actor=kwargs["worker_id"],
            expected_revision=run.revision,
            fence_token=kwargs["fence_token"],
        )
        return {
            "status": "completed",
            "output_path": kwargs["manifest"]["output_path"],
            "artifact_sha256": "a" * 64,
            "verdict": "PASS",
        }

    monkeypatch.setattr(runner_module, "ExportRunner", ProbeRunner)
    monkeypatch.setattr(publication_module, "publish_export_run", complete_publication)
    if os.getenv("R4_BEFORE_RED") == "1":
        original_claim = S12ExportRepository.claim_run

        def pre_r4_claim(self: Any, run_id: str, worker_id: str, **kwargs: Any) -> Any:
            row = self._session.get(S12ExportRun, run_id)
            if row is not None and row.status == "pending" and row.attempt != 1:
                raise S12ExportError("pending run with attempt != 1 is ambiguous")
            return original_claim(self, run_id, worker_id, **kwargs)

        monkeypatch.setattr(S12ExportRepository, "claim_run", pre_r4_claim)
    worker = DurableWorker(
        factory,
        config=WorkerConfig(worker_id="r4-live-worker", staging_root=managed),
    )
    from app.workflow.s12_export_jobs import register_s12_export_handler

    register_s12_export_handler(worker)
    return worker


@pytest.mark.parametrize("predecessor_kind", ["failed", "cancelled"])
def test_valid_retry_chain_runs_in_actual_worker(
    env: Any, monkeypatch: pytest.MonkeyPatch, predecessor_kind: str
) -> None:  # noqa: F811
    """Attempts 1/2/3 execute through the registered DurableWorker handler."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = _submit(factory, svc, manifest_id, auth, dirs)
    with factory() as session:
        before_jobs = {row.id for row in session.query(Job).all()}
    calls: list[int] = []
    failing = {1, 2} if predecessor_kind == "failed" else {2}
    worker = _worker(factory, managed, monkeypatch, failing, calls)

    if predecessor_kind == "failed":
        assert worker.run_once() == 1
    else:
        _cancel(factory, svc, run.id, monkeypatch)

    with factory() as session:
        first = session.get(S12ExportRun, run.id)
        assert first is not None
        assert first.status == predecessor_kind
        frozen = {
            name: getattr(first, name)
            for name in (
                "workspace_id", "project_id", "video_item_id", "checkpoint_id",
                "checkpoint_hash", "checkpoint_revision", "manifest_id",
                "manifest_hash", "manifest_generation", "profile_id", "plan_id",
                "plan_hash", "frame_count", "chunk_config_json", "attempt",
                "lineage_id", "predecessor_run_id", "job_id",
            )
        }

    retry_ids: list[str] = []
    for _ in range(2):
        with factory() as session:
            response = route.retry_export(
                run.id if not retry_ids else retry_ids[-1],
                session,
                workspace_id=WS,
                project_id=None,
                client_id="r4-client",
            )
        retry_ids.append(response["run_id"])
        assert worker.run_once() == 1

    assert calls == ([1, 2, 3] if predecessor_kind == "failed" else [2, 3])
    with factory() as session:
        runs = session.query(S12ExportRun).filter_by(workspace_id=WS).all()
        jobs = session.query(Job).all()
        assert len(runs) == 3
        assert len(jobs) == len(before_jobs) + 2
        predecessor = session.get(S12ExportRun, run.id)
        assert predecessor is not None
        assert {name: getattr(predecessor, name) for name in frozen} == frozen
        by_attempt = {row.attempt: row for row in runs}
        assert by_attempt[2].predecessor_run_id == by_attempt[1].id
        assert by_attempt[3].predecessor_run_id == by_attempt[2].id
        assert by_attempt[3].status == "completed"
        assert {row.job_id for row in runs if row.job_id not in before_jobs} == {
            job.id for job in jobs if job.id not in before_jobs
        }


@pytest.mark.parametrize("client_ids", [("same", "same"), ("left", "right")])
def test_contested_retry_has_one_logical_winner(
    env: Any, monkeypatch: pytest.MonkeyPatch, client_ids: tuple[str, str]
) -> None:  # noqa: F811
    """Two live sessions rendezvous at the real successor claim/create call."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = _submit(factory, svc, manifest_id, auth, dirs)
    _cancel(factory, svc, run.id, monkeypatch)
    with factory() as session:
        baseline_runs = {row.id for row in session.query(S12ExportRun).all()}
        baseline_jobs = {row.id for row in session.query(Job).all()}

    rendezvous = Barrier(2)
    original = S12ExportRepository.create_successor_run

    def contested(self: Any, *args: Any, **kwargs: Any) -> Any:
        rendezvous.wait(timeout=5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(S12ExportRepository, "create_successor_run", contested)

    def call(client_id: str) -> dict[str, Any]:
        with factory() as session:
            return route.retry_export(
                run.id,
                session,
                workspace_id=WS,
                project_id=None,
                client_id=client_id,
            )

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="r4-retry") as pool:
        futures = [pool.submit(call, client_id) for client_id in client_ids]
        results = [future.result(timeout=15) for future in futures]

    assert {result["run_id"] for result in results}.__len__() == 1
    assert {result["job_id"] for result in results}.__len__() == 1
    assert sorted(result["created"] for result in results) == [False, True]
    with factory() as session:
        assert len(session.query(S12ExportRun).all()) == len(baseline_runs) + 1
        assert len(session.query(Job).all()) == len(baseline_jobs) + 1
        successor = session.query(S12ExportRun).filter_by(predecessor_run_id=run.id).one()
        assert successor.job_id == results[0]["job_id"]


@pytest.mark.parametrize("corruption", ["wrong_attempt", "self_pointer"])
def test_malformed_retry_lineage_claim_is_fail_closed(
    env: Any, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:  # noqa: F811
    """Malformed attempt/pointer identity cannot acquire a worker lease."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = _submit(factory, svc, manifest_id, auth, dirs)
    _cancel(factory, svc, run.id, monkeypatch)
    with factory() as session:
        response = route.retry_export(run.id, session, workspace_id=WS, project_id=None)
    with factory() as session:
        successor = session.get(S12ExportRun, response["run_id"])
        assert successor is not None
        if corruption == "wrong_attempt":
            successor.attempt = 9
        else:
            successor.predecessor_run_id = successor.id
        session.commit()
        before = (successor.status, successor.revision, successor.job_id)
        with pytest.raises(S12ExportError):
            S12ExportRepository(session).claim_run(
                successor.id, "r4-malformed", job_id=successor.job_id
            )
        session.rollback()
    with factory() as session:
        after = session.get(S12ExportRun, response["run_id"])
        assert after is not None
        assert (after.status, after.revision, after.job_id) == before
        assert session.query(S12ExportRun).count() == 2
        assert session.query(Job).count() == 2


@pytest.mark.parametrize(
    "tamper", ["generation", "manifest", "query", "ambiguous", "enqueue", "bind"]
)
def test_union_identity_invalid_retry_is_zero_delta(
    env: Any, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:  # noqa: F811
    """Tamper and read failures reject before a successor or Job is written."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = _submit(factory, svc, manifest_id, auth, dirs)
    _cancel(factory, svc, run.id, monkeypatch)
    with factory() as session:
        job = session.query(Job).filter_by(idempotency_key=f"s12_export_job:{run.id}").one()
        if tamper == "generation":
            job.input_generation = "tampered"
        elif tamper == "manifest":
            manifest = json.loads(job.input_manifest_json)
            manifest["run_id"] = "foreign-run"
            job.input_manifest_json = json.dumps(manifest, sort_keys=True)
        elif tamper == "ambiguous":
            now = datetime.now(UTC)
            session.add(
                Job(
                    workspace_id=WS,
                    job_type="s12_export",
                    owner_type="project",
                    owner_id=f"p-{WS}",
                    state="cancelled",
                    resource_class="cpu_light",
                    priority=50,
                    max_attempts=3,
                    attempt=0,
                    idempotency_key=f"s12_export_job:{run.id}",
                    input_generation="ambiguous-generation",
                    input_manifest_json="{}",
                    created_at=now,
                    updated_at=now,
                    revision=1,
                )
            )
        session.commit()
        before_runs = len(session.query(S12ExportRun).all())
        before_jobs = len(session.query(Job).all())

    if tamper == "query":
        monkeypatch.setattr(route, "_job_state_in", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("query failed")))
    elif tamper == "enqueue":
        def fail_enqueue(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("enqueue uncertainty")

        monkeypatch.setattr(JobRepository, "create_job", fail_enqueue)
    elif tamper == "bind":
        def fail_bind(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("bind uncertainty")

        monkeypatch.setattr(S12ExportRepository, "bind_job", fail_bind)
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            route.retry_export(run.id, session, workspace_id=WS, project_id=None)
        session.rollback()
    assert exc.value.status_code == (500 if tamper in ("query", "ambiguous") else 409)
    with factory() as session:
        assert len(session.query(S12ExportRun).all()) == before_runs
        assert len(session.query(Job).all()) == before_jobs


def test_repair_commit_uncertainty_and_replay_have_exact_pair(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    """Repair creates one missing Job; lost commit acknowledgement replays exactly."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = _submit(factory, svc, manifest_id, auth, dirs)
    _cancel(factory, svc, run.id, monkeypatch)
    with factory() as session:
        repo = S12ExportRepository(session)
        successor, created = repo.create_successor_run(
            run.id,
            workspace_id=WS,
            project_id=f"p-{WS}",
            idempotency_key=f"s12_retry:{run.id}",
        )
        assert created is True
        session.commit()
    with factory() as session:
        repaired = route.retry_export(
            run.id, session, workspace_id=WS, project_id=None
        )
    with factory() as session:
        assert session.query(S12ExportRun).count() == 2
        assert session.query(Job).count() == 2
        repaired_run = session.get(S12ExportRun, repaired["run_id"])
        assert repaired_run is not None and repaired_run.job_id == repaired["job_id"]

    _cancel(factory, svc, repaired["run_id"], monkeypatch)

    original_factory = svc.session_factory
    armed = {"value": True}

    def uncertain_factory() -> Any:
        session = original_factory()
        session.info["r4_uncertain_commit"] = True
        return session

    original_commit = Session.commit

    def uncertain_commit(session: Session) -> None:
        original_commit(session)
        if session.info.pop("r4_uncertain_commit", False) and armed["value"]:
            armed["value"] = False
            raise RuntimeError("R4 lost commit acknowledgement")

    monkeypatch.setattr(Session, "commit", uncertain_commit)
    monkeypatch.setattr(svc, "_session_factory", uncertain_factory)
    with factory() as session:
        repaired_repeat = route.retry_export(
            repaired["run_id"], session, workspace_id=WS, project_id=None
        )
    assert repaired_repeat["run_id"] != repaired["run_id"]
    assert repaired_repeat["job_id"]
    with factory() as session:
        assert session.query(S12ExportRun).count() == 3
        assert session.query(Job).count() == 3

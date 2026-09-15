"""R6 finite identity-resolution matrix (F01) — M01..M19.

Fixture-only engineering evidence over isolated migrated DBs: every case
runs the REAL public route/workflow/persistence against its fixture, and
snapshots ALL Run/Job/lease rows before the public operation so a denial
is proved to be zero-mutation and a repair is proved to be bounded.

Node-ID contract (R6_ACCEPTANCE "RETRY — F01, C06/C07/C15, R01–R03"):
  test_m01_initial_replay_unchanged_no_duplicate
  test_m02_successor_replay_unchanged_no_duplicate
  test_m03_valid_retry_chain_attempts_1_2_3[failed|cancelled]
  test_m04_single_field_job_corruption[initial|successor-generation|key|
      manifest_run_id|workspace|type|owner_id]
  test_m05_additional_canonical_key_claimant[initial|successor]
  test_m06_additional_off_key_manifest_claimant[initial|successor]
  test_m07_cross_workspace_claimant[initial|successor-canonical_key|off_key]
  test_m08_null_successor_pointer_changed_job_key_denies_2_2
  test_m09_null_pointer_changed_job_workspace_denies_2_2
  test_m10_null_pointer_changed_key_and_generation_denies_2_2
  test_m11_unresolved_generation_owner_claimant_cannot_become_orphan
  test_m12_pointer_redirected_to_other_job_denies_zero_mutation
  test_m13_null_pointer_restore_once_without_creating_job
  test_m14_actual_orphan_repair_once_then_unchanged
  test_m15_fail_closed_matrix[read_failure|malformed_json|enqueue_failure|
      bind_failure]
  test_m16_successful_commit_lost_ack_fresh_reconciliation_exact_pair
  test_m17_commit_fails_before_durability_no_successor_denied
  test_m18_malformed_predecessor_denial[attempt9|self|missing|cyclic|
      foreign_workspace|frozen_identity]
  test_m19_two_live_retries_one_logical_creator[same_client|different_clients]
  test_m19_sequential_retry_control_converges
"""

# The RETRY lane reuses the transferred fixtures under the same names.
# ruff: noqa: F811

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_r4_retry_execution import _cancel, env  # noqa: F401
from test_s12_t03c_c1_closure import WS, _authority_body, _ready

from app.api.routes import s12_export as route
from app.persistence.jobs import JobRepository
from app.persistence.models import Job, S12ExportRun
from app.persistence.s12_export import S12ExportRepository
from app.workflow import s12_export_jobs as wf

FOREIGN_WS = "ws-s12r6-foreign"

_TABLES = ("s12_export_run", "job", "s12_export_lease")

#: Deterministic ordering key per snapshotted table (lease PK is run_id).
_ORDER_KEY = {"s12_export_run": "id", "job": "id", "s12_export_lease": "run_id"}


# ── helpers ──────────────────────────────────────────────────────────────


def _arm(monkeypatch: pytest.MonkeyPatch, svc: Any, managed: Any) -> None:
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)


def _snapshot(factory: Any) -> dict[str, list[dict[str, Any]]]:
    """ALL Run/Job/lease rows (revisions, pointers, statuses included)."""
    with factory() as session:
        return {
            table: [
                dict(row)
                for row in session.execute(
                    text(f"SELECT * FROM {table} ORDER BY {_ORDER_KEY[table]}")
                ).mappings()
            ]
            for table in _TABLES
        }


def _submit_ok(
    factory: Any,
    svc: Any,
    managed: Any,
    manifest_id: str,
    auth: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    _arm(monkeypatch, svc, managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as session:
        response = route.submit_export(
            route.S12ExportSubmitRequest(**body), session, workspace_id=WS
        )
        session.commit()
    return response


def _submit_denied(
    factory: Any,
    svc: Any,
    managed: Any,
    manifest_id: str,
    auth: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> HTTPException:
    _arm(monkeypatch, svc, managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            route.submit_export(
                route.S12ExportSubmitRequest(**body), session, workspace_id=WS
            )
        session.rollback()
    return exc.value


def _retry_ok(
    factory: Any,
    svc: Any,
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    client_id: str | None = None,
) -> dict[str, Any]:
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as session:
        return route.retry_export(
            run_id, session, workspace_id=WS, project_id=None, client_id=client_id
        )


def _retry_denied(
    factory: Any,
    svc: Any,
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    client_id: str | None = None,
) -> HTTPException:
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            route.retry_export(
                run_id, session, workspace_id=WS, project_id=None, client_id=client_id
            )
        session.rollback()
    return exc.value


def _sql(factory: Any, sql: str, **params: Any) -> None:
    with factory() as session:
        session.execute(text(sql), params)
        session.commit()


def _ensure_foreign_workspace(factory: Any) -> None:
    _sql(
        factory,
        "INSERT OR IGNORE INTO workspace(id,name) VALUES (:w,:w)",
        w=FOREIGN_WS,
    )


def _run_row(factory: Any, run_id: str) -> Any:
    with factory() as session:
        row = session.get(S12ExportRun, run_id)
        assert row is not None
        return row


def _job_fields(factory: Any, job_id: str, fields: tuple[str, ...]) -> dict[str, Any]:
    with factory() as session:
        row = session.get(Job, job_id)
        assert row is not None
        return {name: getattr(row, name) for name in fields}


def _run_fields(factory: Any, run_id: str, fields: tuple[str, ...]) -> dict[str, Any]:
    with factory() as session:
        row = session.get(S12ExportRun, run_id)
        assert row is not None
        return {name: getattr(row, name) for name in fields}


def _job_manifest(factory: Any, job_id: str) -> dict[str, Any]:
    with factory() as session:
        row = session.get(Job, job_id)
        assert row is not None
        parsed = json.loads(row.input_manifest_json)
        assert isinstance(parsed, dict)
        return parsed


def _write_manifest(factory: Any, job_id: str, payload: dict[str, Any]) -> None:
    _sql(
        factory,
        "UPDATE job SET input_manifest_json=:manifest WHERE id=:id",
        manifest=json.dumps(payload, sort_keys=True),
        id=job_id,
    )


def _add_claimant(
    factory: Any,
    *,
    run_id: str,
    key: str,
    workspace: str = WS,
    generation: str = "r6-claimant-generation",
    manifest_json: str = "{}",
    state: str = "cancelled",
    owner_id: str | None = None,
    job_type: str = "s12_export",
) -> str:
    """Insert an additional durable Job row claiming *run_id* (fixture-only)."""
    from datetime import UTC, datetime

    claimant_id = f"r6-claimant-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    _sql(
        factory,
        "INSERT INTO job(id, workspace_id, job_type, owner_type, owner_id, state,"
        " resource_class, priority, max_attempts, attempt, idempotency_key,"
        " input_generation, input_manifest_json, created_at, updated_at, revision)"
        " VALUES (:id, :ws, :jt, 'project', :oid, :state, 'cpu_light', 50, 3, 0,"
        " :key, :gen, :manifest, :now, :now, 1)",
        id=claimant_id,
        ws=workspace,
        jt=job_type,
        oid=owner_id or f"p-{WS}",
        state=state,
        key=key,
        gen=generation,
        manifest=manifest_json,
        now=now,
    )
    return claimant_id


def _make_initial(env: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Submit once → (run1, job1) pair, no successor."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    response = _submit_ok(factory, svc, managed, manifest_id, auth, monkeypatch)
    assert response["created"] is True
    return {
        "factory": factory,
        "svc": svc,
        "manifest_id": manifest_id,
        "auth": auth,
        "managed": managed,
        "run1": response["run_id"],
        "job1": response["job_id"],
    }


def _make_successor(env: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Submit, cancel, retry → run1/job1 + successor run2/job2."""
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)
    response = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert response["created"] is True
    ctx.update({"run2": response["run_id"], "job2": response["job_id"]})
    return ctx


def _target_for_site(ctx: dict[str, Any], site: str) -> tuple[str, str, str]:
    """(op_kind, target_run_id, target_job_id) where op_kind runs the public op."""
    if site == "initial":
        return "initial", ctx["run1"], ctx["job1"]
    return "successor", ctx["run2"], ctx["job2"]


# ── M01–M03: unchanged replays and the valid chain ──────────────────────


def test_m01_initial_replay_unchanged_no_duplicate(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory = ctx["factory"]
    before = _snapshot(factory)
    replay = _submit_ok(
        factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch
    )
    assert replay["created"] is False
    assert replay["run_id"] == ctx["run1"]
    assert replay["job_id"] == ctx["job1"]
    assert _snapshot(factory) == before
    assert len(before["s12_export_run"]) == 1
    assert len(before["job"]) == 1


def test_m02_successor_replay_unchanged_no_duplicate(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch)
    factory = ctx["factory"]
    before = _snapshot(factory)
    replay = _retry_ok(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert replay["created"] is False
    assert replay["run_id"] == ctx["run2"]
    assert replay["job_id"] == ctx["job2"]
    assert _snapshot(factory) == before
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 2


@pytest.mark.parametrize("predecessor_kind", ["failed", "cancelled"])
def test_m03_valid_retry_chain_attempts_1_2_3(env: Any, monkeypatch: pytest.MonkeyPatch, predecessor_kind: str) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    run1, job1 = ctx["run1"], ctx["job1"]

    if predecessor_kind == "failed":
        _sql(factory, "UPDATE s12_export_run SET status='failed' WHERE id=:id", id=run1)
        _sql(factory, "UPDATE job SET state='failed' WHERE id=:id", id=job1)
    else:
        _cancel(factory, svc, run1, monkeypatch)

    second = _retry_ok(factory, svc, run1, monkeypatch)
    assert second["created"] is True
    run2, job2 = second["run_id"], second["job_id"]
    _cancel(factory, svc, run2, monkeypatch)

    third = _retry_ok(factory, svc, run2, monkeypatch)
    assert third["created"] is True
    run3, job3 = third["run_id"], third["job_id"]

    frozen_fields = (
        "workspace_id", "project_id", "video_item_id", "checkpoint_id",
        "checkpoint_hash", "checkpoint_revision", "manifest_id",
        "manifest_hash", "manifest_generation", "profile_id", "plan_id",
        "plan_hash", "frame_count", "chunk_config_json", "attempt",
        "lineage_id", "predecessor_run_id", "job_id",
    )
    before_replays = {
        run1: _run_fields(factory, run1, frozen_fields),
        run2: _run_fields(factory, run2, frozen_fields),
    }
    before_counts = _snapshot(factory)

    # Replay each identity: initial run, then each existing successor.
    replay_initial = _submit_ok(
        factory, svc, ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch
    )
    assert replay_initial["created"] is False and replay_initial["run_id"] == run1
    replay_second = _retry_ok(factory, svc, run1, monkeypatch)
    assert replay_second["created"] is False and replay_second["run_id"] == run2
    replay_third = _retry_ok(factory, svc, run2, monkeypatch)
    assert replay_third["created"] is False and replay_third["run_id"] == run3

    assert _snapshot(factory) == before_counts
    for run_id in (run1, run2):
        assert _run_fields(factory, run_id, frozen_fields) == before_replays[run_id]

    with factory() as session:
        runs = session.query(S12ExportRun).all()
        jobs = session.query(Job).all()
    assert len(runs) == 3
    assert len(jobs) == 3
    by_attempt = {row.attempt: row for row in runs}
    assert set(by_attempt) == {1, 2, 3}
    assert by_attempt[2].predecessor_run_id == by_attempt[1].id
    assert by_attempt[3].predecessor_run_id == by_attempt[2].id
    # Shared plan generation across attempts is valid identity.
    assert len({row.plan_hash for row in runs}) == 1
    pairs = {row.id: row.job_id for row in runs}
    assert pairs == {run1: job1, run2: job2, run3: job3}


# ── M04–M07: union discovery for BOTH replay stages ─────────────────────


@pytest.mark.parametrize("field", ["generation", "key", "manifest_run_id", "workspace", "type", "owner_id"])
@pytest.mark.parametrize("site", ["initial", "successor"])
def test_m04_single_field_job_corruption(env: Any, monkeypatch: pytest.MonkeyPatch, site: str, field: str) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch) if site == "successor" else _make_initial(env, monkeypatch)
    factory = ctx["factory"]
    op_kind, target_run, target_job = _target_for_site(ctx, site)

    if field == "generation":
        _sql(factory, "UPDATE job SET input_generation=:v WHERE id=:id", v="r6-tampered", id=target_job)
    elif field == "key":
        _sql(factory, "UPDATE job SET idempotency_key=:v WHERE id=:id", v="s12_export_job:r6-tampered", id=target_job)
    elif field == "manifest_run_id":
        manifest = _job_manifest(factory, target_job)
        manifest["run_id"] = "r6-foreign-run"
        _write_manifest(factory, target_job, manifest)
    elif field == "workspace":
        _ensure_foreign_workspace(factory)
        _sql(factory, "UPDATE job SET workspace_id=:v WHERE id=:id", v=FOREIGN_WS, id=target_job)
    elif field == "type":
        _sql(factory, "UPDATE job SET job_type=:v WHERE id=:id", v="s12_export_r6_tampered", id=target_job)
    elif field == "owner_id":
        _sql(factory, "UPDATE job SET owner_id=:v WHERE id=:id", v="p-r6-foreign", id=target_job)
    else:  # pragma: no cover - defensive
        raise AssertionError(field)

    before = _snapshot(factory)
    if op_kind == "initial":
        exc = _submit_denied(factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch)
    else:
        exc = _retry_denied(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_CONTRADICTION" in str(exc.detail)
    assert _snapshot(factory) == before


@pytest.mark.parametrize("site", ["initial", "successor"])
def test_m05_additional_canonical_key_claimant(env: Any, monkeypatch: pytest.MonkeyPatch, site: str) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch) if site == "successor" else _make_initial(env, monkeypatch)
    factory = ctx["factory"]
    op_kind, target_run, target_job = _target_for_site(ctx, site)
    claimant = _add_claimant(
        factory,
        run_id=target_run,
        key=f"s12_export_job:{target_run}",
        generation="r6-different-generation",
    )

    before = _snapshot(factory)
    assert claimant in {row["id"] for row in before["job"]}
    if op_kind == "initial":
        exc = _submit_denied(factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch)
    else:
        exc = _retry_denied(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_CONTRADICTION" in str(exc.detail)
    assert _snapshot(factory) == before


@pytest.mark.parametrize("site", ["initial", "successor"])
def test_m06_additional_off_key_manifest_claimant(env: Any, monkeypatch: pytest.MonkeyPatch, site: str) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch) if site == "successor" else _make_initial(env, monkeypatch)
    factory = ctx["factory"]
    op_kind, target_run, target_job = _target_for_site(ctx, site)
    manifest = _job_manifest(factory, target_job)  # retains manifest run identity
    assert str(manifest.get("run_id")) == target_run
    _add_claimant(
        factory,
        run_id=target_run,
        key="r6-off-key-claimant",
        manifest_json=json.dumps(manifest, sort_keys=True),
    )

    before = _snapshot(factory)
    if op_kind == "initial":
        exc = _submit_denied(factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch)
    else:
        exc = _retry_denied(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_CONTRADICTION" in str(exc.detail)
    assert _snapshot(factory) == before


@pytest.mark.parametrize("variant", ["canonical_key", "off_key"])
@pytest.mark.parametrize("site", ["initial", "successor"])
def test_m07_cross_workspace_claimant(env: Any, monkeypatch: pytest.MonkeyPatch, site: str, variant: str) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch) if site == "successor" else _make_initial(env, monkeypatch)
    factory = ctx["factory"]
    op_kind, target_run, target_job = _target_for_site(ctx, site)
    _ensure_foreign_workspace(factory)
    run_row = _run_row(factory, target_run)

    if variant == "canonical_key":
        _add_claimant(
            factory,
            run_id=target_run,
            key=f"s12_export_job:{target_run}",
            workspace=FOREIGN_WS,
            generation=str(run_row.plan_hash),
        )
    else:
        manifest = _job_manifest(factory, target_job)
        _add_claimant(
            factory,
            run_id=target_run,
            key="r6-cross-ws-off-key",
            workspace=FOREIGN_WS,
            manifest_json=json.dumps(manifest, sort_keys=True),
        )

    before = _snapshot(factory)
    if op_kind == "initial":
        exc = _submit_denied(factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch)
    else:
        exc = _retry_denied(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_CONTRADICTION" in str(exc.detail)
    assert _snapshot(factory) == before
    # The cross-scope claimant must still be present (never filtered away).
    assert any(row["workspace_id"] == FOREIGN_WS for row in before["job"])


# ── M08–M14: successor pointer corruption and bounded repair ────────────


def _successor_with_null_pointer_zero_mutation_probe(
    env: Any, monkeypatch: pytest.MonkeyPatch, corrupt
) -> None:
    ctx = _make_successor(env, monkeypatch)
    factory = ctx["factory"]
    _sql(factory, "UPDATE s12_export_run SET job_id=NULL WHERE id=:id", id=ctx["run2"])
    corrupt(factory, ctx)
    before = _snapshot(factory)
    exc = _retry_denied(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_" in str(exc.detail)
    assert _snapshot(factory) == before
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 2  # never 2/3


def test_m08_null_successor_pointer_changed_job_key_denies_2_2(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    def corrupt(factory: Any, ctx: dict[str, Any]) -> None:
        _sql(
            factory,
            "UPDATE job SET idempotency_key=:v WHERE id=:id",
            v="s12_export_job:r6-tampered",
            id=ctx["job2"],
        )

    _successor_with_null_pointer_zero_mutation_probe(env, monkeypatch, corrupt)


def test_m09_null_pointer_changed_job_workspace_denies_2_2(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    def corrupt(factory: Any, ctx: dict[str, Any]) -> None:
        _ensure_foreign_workspace(factory)
        _sql(factory, "UPDATE job SET workspace_id=:v WHERE id=:id", v=FOREIGN_WS, id=ctx["job2"])

    _successor_with_null_pointer_zero_mutation_probe(env, monkeypatch, corrupt)


def test_m10_null_pointer_changed_key_and_generation_denies_2_2(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    def corrupt(factory: Any, ctx: dict[str, Any]) -> None:
        _sql(
            factory,
            "UPDATE job SET idempotency_key=:k, input_generation=:g WHERE id=:id",
            k="s12_export_job:r6-tampered",
            g="r6-tampered-generation",
            id=ctx["job2"],
        )

    _successor_with_null_pointer_zero_mutation_probe(env, monkeypatch, corrupt)


def test_m11_unresolved_generation_owner_claimant_cannot_become_orphan(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    def corrupt(factory: Any, ctx: dict[str, Any]) -> None:
        manifest = _job_manifest(factory, ctx["job2"])
        manifest.pop("run_id", None)  # manifest run identity removed
        _write_manifest(factory, ctx["job2"], manifest)
        _sql(
            factory,
            "UPDATE job SET idempotency_key=:v WHERE id=:id",
            v="s12_export_job:r6-tampered",
            id=ctx["job2"],
        )

    ctx = _make_successor(env, monkeypatch)
    factory = ctx["factory"]
    _sql(factory, "UPDATE s12_export_run SET job_id=NULL WHERE id=:id", id=ctx["run2"])
    corrupt(factory, ctx)
    before = _snapshot(factory)
    exc = _retry_denied(factory, ctx["svc"], ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    # Relevant generation/owner evidence is retained but unresolved: the
    # contradictory claimant must not become a second Job.
    assert "S12_EXPORT_JOB_IDENTITY_UNRESOLVED" in str(exc.detail)
    assert _snapshot(factory) == before
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 2


def test_m12_pointer_redirected_to_other_job_denies_zero_mutation(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run2"], monkeypatch)
    third = _retry_ok(factory, svc, ctx["run2"], monkeypatch)
    assert third["created"] is True
    run3, job3 = third["run_id"], third["job_id"]
    # Redirect the successor's pointer to another legitimate Job of the same
    # lineage (its own successor's Job) while its canonical claimant job2
    # remains: one pointer slot, fixture-scoped redirect, zero mutation on
    # denial (job_id is UNIQUE, so the source slot is cleared first).
    _sql(factory, "UPDATE s12_export_run SET job_id=NULL WHERE id=:id", id=run3)
    _sql(
        factory,
        "UPDATE s12_export_run SET job_id=:jid WHERE id=:id",
        jid=job3,
        id=ctx["run2"],
    )
    before = _snapshot(factory)
    exc = _retry_denied(factory, svc, ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_CONTRADICTION" in str(exc.detail)
    assert _snapshot(factory) == before
    assert _run_row(factory, ctx["run2"]).job_id == job3
    # The original claimant (canonical key + manifest) is never filtered away.
    original = _job_fields(factory, ctx["job2"], ("idempotency_key",))
    assert original["idempotency_key"] == f"s12_export_job:{ctx['run2']}"


def test_m13_null_pointer_restore_once_without_creating_job(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory = ctx["factory"]
    _sql(factory, "UPDATE s12_export_run SET job_id=NULL WHERE id=:id", id=ctx["run1"])
    before = _snapshot(factory)
    assert len(before["job"]) == 1

    restored = _submit_ok(
        factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch
    )
    assert restored["created"] is False
    assert restored["run_id"] == ctx["run1"]
    assert restored["job_id"] == ctx["job1"]
    assert _run_row(factory, ctx["run1"]).job_id == ctx["job1"]  # restored once
    after = _snapshot(factory)
    assert len(after["s12_export_run"]) == 1
    assert len(after["job"]) == 1  # no Job created

    repeat = _submit_ok(
        factory, ctx["svc"], ctx["managed"], ctx["manifest_id"], ctx["auth"], monkeypatch
    )
    assert repeat["created"] is False and repeat["job_id"] == ctx["job1"]
    assert _snapshot(factory) == after  # repeat unchanged


def test_m14_actual_orphan_repair_once_then_unchanged(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)
    with factory() as session:
        successor, created = S12ExportRepository(session).create_successor_run(
            ctx["run1"],
            workspace_id=WS,
            project_id=f"p-{WS}",
            idempotency_key=f"s12_retry:{ctx['run1']}",
        )
        session.commit()
    assert created is True
    run2 = successor.id
    before = _snapshot(factory)
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 1  # true zero-Job orphan

    repaired = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert repaired["created"] is False
    assert repaired["run_id"] == run2
    assert repaired["job_id"]
    after = _snapshot(factory)
    assert len(after["s12_export_run"]) == 2
    assert len(after["job"]) == 2  # 2/1 -> 2/2
    assert _run_row(factory, run2).job_id == repaired["job_id"]

    repeat = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert repeat["run_id"] == run2 and repeat["job_id"] == repaired["job_id"]
    assert _snapshot(factory) == after  # repeated repair unchanged


# ── M15: fail-closed matrix ─────────────────────────────────────────────


def _orphan_successor(ctx: dict[str, Any], factory: Any) -> str:
    with factory() as session:
        successor, created = S12ExportRepository(session).create_successor_run(
            ctx["run1"],
            workspace_id=WS,
            project_id=f"p-{WS}",
            idempotency_key=f"s12_retry:{ctx['run1']}",
        )
        session.commit()
    assert created is True
    return successor.id


@pytest.mark.parametrize("failure", ["read_failure", "malformed_json", "enqueue_failure", "bind_failure"])
def test_m15_fail_closed_matrix(env: Any, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)

    if failure == "malformed_json":
        response = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
        run2, job2 = response["run_id"], response["job_id"]
        _sql(
            factory,
            "UPDATE job SET input_manifest_json=:v WHERE id=:id",
            v=f'{{"run_id": "{run2}", "broken"',
            id=job2,
        )
    else:
        run2 = _orphan_successor(ctx, factory)
        if failure == "read_failure":
            def broken_weak(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("R6 discovery read failure")

            monkeypatch.setattr(wf, "_weak_generation_candidates", broken_weak)
        elif failure == "enqueue_failure":
            def broken_enqueue(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("R6 enqueue uncertainty")

            monkeypatch.setattr(JobRepository, "create_job", broken_enqueue)
        elif failure == "bind_failure":
            original_bind = S12ExportRepository.bind_job
            state = {"failed": False}

            def flaky_bind(self: Any, run_id: str, job_id: str) -> Any:
                if run_id == run2 and not state["failed"]:
                    state["failed"] = True
                    raise RuntimeError("R6 bind uncertainty")
                return original_bind(self, run_id, job_id)

            monkeypatch.setattr(S12ExportRepository, "bind_job", flaky_bind)

    before = _snapshot(factory)
    exc = _retry_denied(factory, svc, ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    if failure == "malformed_json":
        assert "malformed input manifest" in str(exc.detail)
    else:
        assert "preparation failed closed" in str(exc.detail)
    assert _snapshot(factory) == before
    _ = run2


# ── M16–M17: commit uncertainty vs no durability ────────────────────────


def test_m16_successful_commit_lost_ack_fresh_reconciliation_exact_pair(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)

    original_factory = svc.session_factory
    armed = {"value": True}

    def ack_lost_factory() -> Any:
        session = original_factory()
        session.info["r6_lost_ack"] = True
        return session

    original_commit = Session.commit

    def ack_lost_commit(session: Session) -> None:
        original_commit(session)
        if session.info.pop("r6_lost_ack", False) and armed["value"]:
            armed["value"] = False
            raise RuntimeError("R6 lost commit acknowledgement")

    monkeypatch.setattr(Session, "commit", ack_lost_commit)
    monkeypatch.setattr(svc, "_session_factory", ack_lost_factory)

    with factory() as session:
        response = route.retry_export(
            ctx["run1"], session, workspace_id=WS, project_id=None
        )
    assert response["run_id"] != ctx["run1"]
    assert response["job_id"]
    with factory() as session:
        runs = session.query(S12ExportRun).all()
        jobs = session.query(Job).all()
    assert len(runs) == 2
    assert len(jobs) == 2
    durable = {row.id: row.job_id for row in runs}
    assert durable[response["run_id"]] == response["job_id"]

    before_repeat = _snapshot(factory)
    repeat = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert repeat["run_id"] == response["run_id"]
    assert repeat["job_id"] == response["job_id"]
    assert repeat["created"] is False
    assert _snapshot(factory) == before_repeat


def test_m17_commit_fails_before_durability_no_successor_denied(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)

    original_factory = svc.session_factory
    armed = {"value": True}

    def no_durability_factory() -> Any:
        session = original_factory()
        session.info["r6_no_durability"] = True
        return session

    original_commit = Session.commit

    def no_durability_commit(session: Session) -> None:
        if session.info.pop("r6_no_durability", False) and armed["value"]:
            armed["value"] = False
            raise RuntimeError("R6 commit failed before durability")
        original_commit(session)

    monkeypatch.setattr(Session, "commit", no_durability_commit)
    monkeypatch.setattr(svc, "_session_factory", no_durability_factory)

    before = _snapshot(factory)
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            route.retry_export(
                ctx["run1"], session, workspace_id=WS, project_id=None
            )
        session.rollback()
    assert exc.value.status_code == 409
    assert "no successor" in str(exc.value.detail)
    assert _snapshot(factory) == before
    assert len(before["s12_export_run"]) == 1
    assert len(before["job"]) == 1


# ── M18: malformed predecessor lineage stays a typed denial ─────────────


@pytest.mark.parametrize(
    "corruption", ["attempt9", "self", "missing", "cyclic", "foreign_workspace", "frozen_identity"]
)
def test_m18_malformed_predecessor_denial(env: Any, monkeypatch: pytest.MonkeyPatch, corruption: str) -> None:  # noqa: F811
    ctx = _make_successor(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    run1, run2 = ctx["run1"], ctx["run2"]

    if corruption == "cyclic":
        _cancel(factory, svc, run2, monkeypatch)
        third = _retry_ok(factory, svc, run2, monkeypatch)
        run3 = third["run_id"]
        _cancel(factory, svc, run3, monkeypatch)
        target = run3
        _sql(
            factory,
            "UPDATE s12_export_run SET predecessor_run_id=:p WHERE id=:id",
            p=run3,
            id=run2,
        )
    else:
        _cancel(factory, svc, run2, monkeypatch)
        target = run2
        if corruption == "attempt9":
            _sql(factory, "UPDATE s12_export_run SET attempt=9 WHERE id=:id", id=run2)
        elif corruption == "self":
            _sql(
                factory,
                "UPDATE s12_export_run SET predecessor_run_id=:p WHERE id=:id",
                p=run2,
                id=run2,
            )
        elif corruption == "missing":
            # An attempt>1 run with no predecessor pointer at all (NULL is
            # FK-legal; the lineage validator must reject it).
            _sql(
                factory,
                "UPDATE s12_export_run SET predecessor_run_id=NULL WHERE id=:id",
                id=run2,
            )
        elif corruption == "foreign_workspace":
            _ensure_foreign_workspace(factory)
            _sql(
                factory,
                "UPDATE s12_export_run SET workspace_id=:w WHERE id=:id",
                w=FOREIGN_WS,
                id=run1,
            )
        elif corruption == "frozen_identity":
            # A frozen lineage field the public route does not pre-check
            # (chunk_config_json) must still fail the lineage validator.
            _sql(
                factory,
                "UPDATE s12_export_run SET chunk_config_json=:c WHERE id=:id",
                c='{"max_frames": 999, "overlap": 9}',
                id=run2,
            )

    before = _snapshot(factory)
    exc = _retry_denied(factory, svc, target, monkeypatch)
    assert exc.status_code == 409
    assert str(exc.detail).startswith("S12_EXPORT_INVALID_LINEAGE:")
    assert _snapshot(factory) == before


# ── M19: two live retries / sequential control ──────────────────────────


@pytest.mark.parametrize("client_ids", [("same", "same"), ("left", "right")], ids=["same_client", "different_clients"])
def test_m19_two_live_retries_one_logical_creator(env: Any, monkeypatch: pytest.MonkeyPatch, client_ids: tuple[str, str]) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)

    rendezvous = Barrier(2)
    original = S12ExportRepository.create_successor_run

    def contested(self: Any, *args: Any, **kwargs: Any) -> Any:
        rendezvous.wait(timeout=5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(S12ExportRepository, "create_successor_run", contested)

    def call(client_id: str) -> dict[str, Any]:
        with factory() as session:
            return route.retry_export(
                ctx["run1"],
                session,
                workspace_id=WS,
                project_id=None,
                client_id=client_id,
            )

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="r6-retry") as pool:
        futures = [pool.submit(call, client_id) for client_id in client_ids]
        results = [future.result(timeout=20) for future in futures]

    assert len({result["run_id"] for result in results}) == 1
    assert len({result["job_id"] for result in results}) == 1
    assert sorted(result["created"] for result in results) == [False, True]
    after = _snapshot(factory)
    assert len(after["s12_export_run"]) == 2
    assert len(after["job"]) == 2
    successor = _run_row(factory, results[0]["run_id"])
    assert successor.predecessor_run_id == ctx["run1"]
    assert successor.job_id == results[0]["job_id"]


def test_m19_sequential_retry_control_converges(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    ctx = _make_initial(env, monkeypatch)
    factory, svc = ctx["factory"], ctx["svc"]
    _cancel(factory, svc, ctx["run1"], monkeypatch)

    first = _retry_ok(factory, svc, ctx["run1"], monkeypatch, client_id="r6-seq-a")
    assert first["created"] is True
    before = _snapshot(factory)
    second = _retry_ok(factory, svc, ctx["run1"], monkeypatch, client_id="r6-seq-b")
    assert second["created"] is False
    assert second["run_id"] == first["run_id"]
    assert second["job_id"] == first["job_id"]
    assert _snapshot(factory) == before

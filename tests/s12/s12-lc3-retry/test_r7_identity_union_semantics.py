"""R7 F02 semantic union identity — A03/A04/A05/A06 nodes.

Frozen in `SUBMIT_INVENTORY_R7.md` (sha256 ``bd877579a95a7c45…``): 12 nodes.
Every assertion is an ALL-ROW SQL snapshot (job / s12_export_run /
s12_export_lease, every column) plus a managed-root file listing — never a
trusted-prefix count.

  test_a03_nonexistent_manifest_run_denies_zero_delta
      [successor_retry|initial_replay|post_lost_ack_replay]
  test_a04_absent_run_id_corrupted_scope_denies
      [type_only|type_and_workspace|type_and_owner|type_workspace_owner]
  test_a05_escaped_identity_semantics
      [denied_changed_key|exact_reuse|whitespace_exact_reuse]
  test_a05_sibling_proof_required
      [proved_owning_repaired_once|referenced_run_not_owning_denies]
"""

# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session
from test_r4_retry_execution import _cancel, env  # noqa: F401
from test_r6_identity_resolution import (  # noqa: F401
    FOREIGN_WS,
    _add_claimant,
    _ensure_foreign_workspace,
    _job_manifest,
    _make_initial,
    _make_successor,
    _retry_denied,
    _retry_ok,
    _run_row,
    _snapshot,
    _sql,
    _submit_denied,
    _write_manifest,
)
from test_s12_t03c_c1_closure import WS

from app.persistence.models import Job
from app.persistence.s12_export import S12ExportRepository

TAMPERED_RUN_ID = "nonexistent-claimed-run"


def _managed_files(managed: Any) -> list[str]:
    base = Path(str(managed))
    return sorted(str(path.relative_to(base)) for path in base.rglob("*") if path.is_file())


def _arm_lost_ack(monkeypatch: pytest.MonkeyPatch, svc: Any) -> dict[str, Any]:
    """One-shot lost commit acknowledgement on the service session factory."""
    original_factory = svc.session_factory
    armed = {"value": True}

    def lossy_factory() -> Any:
        session = original_factory()
        session.info["r7_lost_ack"] = True
        return session

    original_commit = Session.commit

    def lossy_commit(session: Session) -> None:
        original_commit(session)
        if session.info.pop("r7_lost_ack", False) and armed["value"]:
            armed["value"] = False
            raise RuntimeError("R7 lost commit acknowledgement")

    monkeypatch.setattr(Session, "commit", lossy_commit)
    monkeypatch.setattr(svc, "_session_factory", lossy_factory)
    return armed


def _corrupt_successor_pair(ctx: dict[str, Any], run_key: str, job_key: str) -> None:
    """Null the pointer, change the key, and name a nonexistent run."""
    factory = ctx["factory"]
    _sql(
        factory,
        "UPDATE s12_export_run SET job_id=NULL WHERE id=:id",
        id=ctx[run_key],
    )
    _sql(
        factory,
        "UPDATE job SET idempotency_key=:k WHERE id=:id",
        k=f"s12_export_job:r7-tampered-{ctx[run_key]}",
        id=ctx[job_key],
    )
    manifest = _job_manifest(factory, ctx[job_key])
    manifest["run_id"] = TAMPERED_RUN_ID
    _write_manifest(factory, ctx[job_key], manifest)


def _assert_zero_mutation(
    factory: Any, before: dict[str, Any], managed: Any | None = None
) -> None:
    tables = {key: value for key, value in before.items() if not key.startswith("__")}
    assert _snapshot(factory) == tables
    if managed is not None:
        assert _managed_files(managed) == before["__files"]


def _snap_with_files(factory: Any, managed: Any) -> dict[str, Any]:
    before = _snapshot(factory)
    before["__files"] = _managed_files(managed)
    return before


# ── A03 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "site", ["successor_retry", "initial_replay", "post_lost_ack_replay"]
)
def test_a03_nonexistent_manifest_run_denies_zero_delta(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    site: str,
) -> None:
    if site == "initial_replay":
        ctx = _make_initial(env, monkeypatch)
        _corrupt_successor_pair(ctx, "run1", "job1")
        factory, svc, managed = ctx["factory"], ctx["svc"], ctx["managed"]
        before = _snap_with_files(factory, managed)
        exc = _submit_denied(
            factory, svc, managed, ctx["manifest_id"], ctx["auth"], monkeypatch
        )
        assert exc.status_code == 409
        assert str(exc.detail).startswith("S12_EXPORT_JOB_IDENTITY_UNRESOLVED")
        _assert_zero_mutation(factory, before, managed)
        assert len(before["s12_export_run"]) == 1
        assert len(before["job"]) == 1
        return

    if site == "post_lost_ack_replay":
        # Durable pair from a lost-acknowledged first retry; the replay
        # after corruption must deny against that exact pair.
        ctx = _make_initial(env, monkeypatch)
        factory, svc, managed = ctx["factory"], ctx["svc"], ctx["managed"]
        _cancel(factory, svc, ctx["run1"], monkeypatch)
        _arm_lost_ack(monkeypatch, svc)
        first = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
        assert first["run_id"] != ctx["run1"]
        assert first["job_id"]
        ctx["run2"] = first["run_id"]
        ctx["job2"] = first["job_id"]
    else:
        ctx = _make_successor(env, monkeypatch)
        factory, svc, managed = ctx["factory"], ctx["svc"], ctx["managed"]

    _corrupt_successor_pair(ctx, "run2", "job2")
    before = _snap_with_files(factory, managed)
    exc = _retry_denied(factory, svc, ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert str(exc.detail).startswith("S12_EXPORT_JOB_IDENTITY_UNRESOLVED")
    _assert_zero_mutation(factory, before, managed)
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 2


# ── A04 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "extra", ["type_only", "type_and_workspace", "type_and_owner", "type_workspace_owner"]
)
def test_a04_absent_run_id_corrupted_scope_denies(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    extra: str,
) -> None:
    ctx = _make_successor(env, monkeypatch)
    factory, svc, managed = ctx["factory"], ctx["svc"], ctx["managed"]
    _sql(
        factory,
        "UPDATE s12_export_run SET job_id=NULL WHERE id=:id",
        id=ctx["run2"],
    )
    _sql(
        factory,
        "UPDATE job SET idempotency_key=:k, job_type='tampered-s12-type' WHERE id=:id",
        k=f"s12_export_job:r7-tampered-{ctx['run2']}",
        id=ctx["job2"],
    )
    manifest = _job_manifest(factory, ctx["job2"])
    manifest.pop("run_id", None)
    _write_manifest(factory, ctx["job2"], manifest)
    if extra in ("type_and_workspace", "type_workspace_owner"):
        _ensure_foreign_workspace(factory)
        _sql(
            factory,
            "UPDATE job SET workspace_id=:w WHERE id=:id",
            w=FOREIGN_WS,
            id=ctx["job2"],
        )
    if extra in ("type_and_owner", "type_workspace_owner"):
        _sql(
            factory,
            "UPDATE job SET owner_id='p-r7-foreign' WHERE id=:id",
            id=ctx["job2"],
        )

    before = _snap_with_files(factory, managed)
    exc = _retry_denied(factory, svc, ctx["run1"], monkeypatch)
    assert exc.status_code == 409
    assert "S12_EXPORT_JOB_IDENTITY_UNRESOLVED" in str(exc.detail)
    _assert_zero_mutation(factory, before, managed)
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 2  # the corrupted-scope Job is never filtered away


# ── A05 ─────────────────────────────────────────────────────────────────


def _escape_json_chars(value: str) -> str:
    return "".join(f"\\u{ord(char):04x}" for char in value)


@pytest.mark.parametrize(
    "variant", ["denied_changed_key", "exact_reuse", "whitespace_exact_reuse"]
)
def test_a05_escaped_identity_semantics(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    ctx = _make_successor(env, monkeypatch)
    factory, svc, managed = ctx["factory"], ctx["svc"], ctx["managed"]
    _sql(
        factory,
        "UPDATE s12_export_run SET job_id=NULL WHERE id=:id",
        id=ctx["run2"],
    )
    if variant == "denied_changed_key":
        _sql(
            factory,
            "UPDATE job SET idempotency_key=:k WHERE id=:id",
            k=f"s12_export_job:r7-tampered-{ctx['run2']}",
            id=ctx["job2"],
        )

    manifest = _job_manifest(factory, ctx["job2"])
    if variant == "whitespace_exact_reuse":
        payload = json.dumps(manifest, indent=2)
    else:
        raw = json.dumps(manifest, sort_keys=True)
        assert str(ctx["run2"]) in raw
        payload = raw.replace(str(ctx["run2"]), _escape_json_chars(str(ctx["run2"])))
    _sql(
        factory,
        "UPDATE job SET input_manifest_json=:m WHERE id=:id",
        m=payload,
        id=ctx["job2"],
    )
    with factory() as session:
        stored_raw = session.get(Job, ctx["job2"]).input_manifest_json
    assert json.loads(stored_raw)["run_id"] == str(ctx["run2"])  # semantic identity
    if variant != "whitespace_exact_reuse":
        assert "\\u00" in stored_raw  # escaped bytes on disk, same meaning

    if variant == "denied_changed_key":
        before = _snap_with_files(factory, managed)
        exc = _retry_denied(factory, svc, ctx["run1"], monkeypatch)
        assert exc.status_code == 409
        assert "S12_EXPORT_JOB_IDENTITY_CONTRADICTION" in str(exc.detail)
        _assert_zero_mutation(factory, before, managed)
        return

    before = _snapshot(factory)
    response = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert response["created"] is False
    assert response["run_id"] == ctx["run2"]
    assert response["job_id"] == ctx["job2"]
    after = _snapshot(factory)
    assert after["job"] == before["job"]  # Job rows byte-equal, revision included
    assert after["s12_export_lease"] == before["s12_export_lease"]
    before_runs = {row["id"]: row for row in before["s12_export_run"]}
    after_runs = {row["id"]: row for row in after["s12_export_run"]}
    assert set(before_runs) == set(after_runs) == {ctx["run1"], ctx["run2"]}
    for run_id, row in after_runs.items():
        if run_id == ctx["run2"]:
            changed = {key for key in row if row[key] != before_runs[run_id][key]}
            assert changed <= {"job_id", "revision", "updated_at"}
            assert row["job_id"] == ctx["job2"]
        else:
            assert row == before_runs[run_id]


@pytest.mark.parametrize(
    "proof", ["proved_owning_repaired_once", "referenced_run_not_owning_denies"]
)
def test_a05_sibling_proof_required(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    proof: str,
) -> None:
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

    if proof == "referenced_run_not_owning_denies":
        shared_plan_hash = str(_run_row(factory, ctx["run1"]).plan_hash)
        manifest = _job_manifest(factory, ctx["job1"])  # names run1, not run2
        _add_claimant(
            factory,
            run_id=ctx["run1"],
            key="r7-unproven-claimant",
            generation=shared_plan_hash,
            manifest_json=json.dumps(manifest, sort_keys=True),
        )
        before = _snapshot(factory)
        assert len(before["s12_export_run"]) == 2
        assert len(before["job"]) == 2
        exc = _retry_denied(factory, svc, ctx["run1"], monkeypatch)
        assert exc.status_code == 409
        assert "S12_EXPORT_JOB_IDENTITY_UNRESOLVED" in str(exc.detail)
        assert _snapshot(factory) == before
        return

    before = _snapshot(factory)
    assert len(before["s12_export_run"]) == 2
    assert len(before["job"]) == 1  # true zero-Job orphan beside a proven sibling
    response = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert response["created"] is False
    assert response["run_id"] == run2
    assert response["job_id"]
    after = _snapshot(factory)
    assert len(after["s12_export_run"]) == 2
    assert len(after["job"]) == 2  # 2/1 -> 2/2 exactly once
    assert _run_row(factory, run2).job_id == response["job_id"]
    sibling_after = [row for row in after["job"] if row["id"] == ctx["job1"]]
    assert sibling_after == [row for row in before["job"] if row["id"] == ctx["job1"]]
    repeat = _retry_ok(factory, svc, ctx["run1"], monkeypatch)
    assert repeat["run_id"] == response["run_id"]
    assert repeat["job_id"] == response["job_id"]
    assert _snapshot(factory) == after  # repeated repair unchanged

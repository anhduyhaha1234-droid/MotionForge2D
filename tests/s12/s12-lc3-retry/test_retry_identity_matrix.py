"""S12-LC3-RETRY writer-owned identity and replay matrix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from test_export_jobs_api import _current_s10_pins, _submit_kwargs, env  # noqa: F401

from app.api.routes import s12_export as route
from app.persistence.models import Job, S12ExportRun
from app.persistence.s12_export import S12ExportRepository
from app.workflow.s12_export_jobs import submit_export_job


def _cancel(factory, svc, run_id: str, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as session:
        route.cancel_export(run_id, session, workspace_id="ws-s12t03c", project_id=None)
        session.commit()


def _retry(factory, svc, run_id: str, monkeypatch: pytest.MonkeyPatch, client_id: str) -> dict:
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as session:
        return route.retry_export(
            run_id,
            session,
            workspace_id="ws-s12t03c",
            project_id=None,
            client_id=client_id,
        )


def test_successor_copies_immutable_identity_and_actual_job(env, monkeypatch):  # noqa: F811
    factory, svc, manifest_id, dirs = env
    managed = Path(dirs["output"]).parent / "artifacts"
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, job, _ = submit_export_job(
        svc, **_submit_kwargs(factory, manifest_id, dirs, **_current_s10_pins(factory))
    )
    with factory() as session:
        before = session.get(S12ExportRun, run.id)
        assert before is not None
        frozen = {
            key: getattr(before, key)
            for key in (
                "workspace_id",
                "project_id",
                "video_item_id",
                "checkpoint_id",
                "checkpoint_hash",
                "checkpoint_revision",
                "manifest_id",
                "manifest_hash",
                "manifest_generation",
                "profile_id",
                "profile_dims",
                "profile_codec",
                "plan_id",
                "plan_hash",
                "frame_count",
                "chunk_config_json",
                "attempt",
                "lineage_id",
                "job_id",
            )
        }
    _cancel(factory, svc, run.id, monkeypatch)
    result = _retry(factory, svc, run.id, monkeypatch, "client-a")
    assert result["created"] is True
    assert result["job_id"]
    with factory() as session:
        predecessor = session.get(S12ExportRun, run.id)
        successor = session.get(S12ExportRun, result["run_id"])
        durable_job = session.get(Job, result["job_id"])
        assert predecessor is not None and successor is not None and durable_job is not None
        for key, value in frozen.items():
            assert getattr(predecessor, key) == value
        assert successor.predecessor_run_id == predecessor.id
        assert successor.lineage_id == predecessor.lineage_id
        assert successor.attempt == predecessor.attempt + 1
        assert successor.natural_key is None
        assert successor.job_id == durable_job.id
        manifest = json.loads(durable_job.input_manifest_json)
        assert manifest["run_id"] == successor.id
        assert manifest["plan_hash"] == successor.plan_hash
        assert manifest["checkpoint_hash"] == successor.checkpoint_hash


def test_repeat_and_retry_of_successor_make_one_next_row(env, monkeypatch):  # noqa: F811
    factory, svc, manifest_id, dirs = env
    managed = Path(dirs["output"]).parent / "artifacts"
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = submit_export_job(
        svc, **_submit_kwargs(factory, manifest_id, dirs, **_current_s10_pins(factory))
    )
    _cancel(factory, svc, run.id, monkeypatch)
    first = _retry(factory, svc, run.id, monkeypatch, "client-a")
    repeat = _retry(factory, svc, run.id, monkeypatch, "client-b")
    assert repeat["run_id"] == first["run_id"]
    assert repeat["job_id"] == first["job_id"]
    assert repeat["created"] is False
    _cancel(factory, svc, first["run_id"], monkeypatch)
    third = _retry(factory, svc, first["run_id"], monkeypatch, "client-c")
    assert third["run_id"] != first["run_id"]
    with factory() as session:
        rows = session.query(S12ExportRun).filter_by(workspace_id="ws-s12t03c").all()
        assert len(rows) == 3
        by_attempt = {row.attempt: row for row in rows}
        assert by_attempt[2].predecessor_run_id == by_attempt[1].id
        assert by_attempt[3].predecessor_run_id == by_attempt[2].id
        assert len({row.job_id for row in rows}) == 3


def test_retry_rejects_corrupt_pointer_and_preserves_rows(env, monkeypatch):  # noqa: F811
    factory, svc, manifest_id, dirs = env
    managed = Path(dirs["output"]).parent / "artifacts"
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, _job, _ = submit_export_job(
        svc, **_submit_kwargs(factory, manifest_id, dirs, **_current_s10_pins(factory))
    )
    _cancel(factory, svc, run.id, monkeypatch)
    with factory() as session:
        session.execute(
            text("UPDATE s12_export_run SET job_id=NULL WHERE id=:id"),
            {"id": run.id},
        )
        session.commit()
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            route.retry_export(run.id, session, workspace_id="ws-s12t03c", project_id=None)
        session.rollback()
    assert exc.value.status_code == 500
    with factory() as session:
        assert session.query(S12ExportRun).count() == 1
        assert session.query(Job).count() == 1


def test_repository_collision_is_insert_arbiter(env):  # noqa: F811
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(
        svc, **_submit_kwargs(factory, manifest_id, dirs, **_current_s10_pins(factory))
    )
    with factory() as session:
        row = session.get(S12ExportRun, run.id)
        assert row is not None
        row.status = "cancelled"
        session.commit()
    key = f"s12_retry:{run.id}"
    with factory() as one, factory() as two:
        first, created = S12ExportRepository(one).create_successor_run(
            run.id, workspace_id=run.workspace_id, project_id=run.project_id, idempotency_key=key
        )
        one.commit()
        second, replayed = S12ExportRepository(two).create_successor_run(
            run.id, workspace_id=run.workspace_id, project_id=run.project_id, idempotency_key=key
        )
        two.rollback()
    assert created is True
    assert replayed is False
    assert second.id == first.id

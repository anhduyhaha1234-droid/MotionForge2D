"""R5 corrections for initial replay ordering and retry lineage denial."""

# The RETRY lane reuses the transferred QA fixture under the same name.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from test_r4_retry_execution import _cancel, _submit, env  # noqa: F401
from test_s12_t03c_c1_closure import WS

from app.api.routes import s12_export as route
from app.persistence.models import S12ExportRun


def _snapshot(factory: Any) -> dict[str, list[dict[str, Any]]]:
    with factory() as session:
        return {
            table: [
                dict(row)
                for row in session.execute(
                    text(f"SELECT * FROM {table} ORDER BY id")
                ).mappings()
            ]
            for table in ("s12_export_run", "job")
        }


@pytest.mark.parametrize("corrupt", [False, True])
def test_public_initial_replay_resolves_run_and_job_before_create(
    env: Any, monkeypatch: pytest.MonkeyPatch, corrupt: bool
) -> None:  # noqa: F811
    factory, service, manifest_id, auth, dirs, managed = env
    from test_s12_t03c_c1_closure import _ready

    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: service)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    run, job, created = _submit(factory, service, manifest_id, auth, dirs)
    assert created is True

    if corrupt:
        with factory() as session:
            session.execute(
                text("UPDATE job SET input_generation=:generation WHERE id=:id"),
                {"generation": "f" * 64, "id": job.id},
            )
            session.commit()

    before = _snapshot(factory)
    if corrupt:
        with pytest.raises(HTTPException) as exc:
            _submit(factory, service, manifest_id, auth, dirs)
        assert exc.value.status_code == 409
    else:
        replay_run, replay_job, replay_created = _submit(
            factory, service, manifest_id, auth, dirs
        )
        assert replay_created is False
        assert replay_run.id == run.id
        assert replay_job.id == job.id

    assert _snapshot(factory) == before
    assert len(before["s12_export_run"]) == 1
    assert len(before["job"]) == 1


def test_invalid_predecessor_lineage_is_typed_and_not_reconciled(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    factory, service, manifest_id, auth, dirs, managed = env
    from test_s12_t03c_c1_closure import _ready

    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: service)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    predecessor, _job, _created = _submit(factory, service, manifest_id, auth, dirs)
    _cancel(factory, service, predecessor.id, monkeypatch)

    with factory() as session:
        first = route.retry_export(
            predecessor.id, session, workspace_id=WS, project_id=None
        )

    with factory() as session:
        row = session.get(S12ExportRun, predecessor.id)
        assert row is not None
        row.attempt = 9
        session.commit()

    before = _snapshot(factory)
    with factory() as session:
        with pytest.raises(HTTPException) as exc:
            route.retry_export(
                predecessor.id, session, workspace_id=WS, project_id=None
            )
        session.rollback()

    assert exc.value.status_code == 409
    assert str(exc.value.detail).startswith("S12_EXPORT_INVALID_LINEAGE:")
    after = _snapshot(factory)
    assert after == before
    assert len(after["s12_export_run"]) == 2
    assert len(after["job"]) == 2
    assert any(
        row["id"] == first["run_id"] and row["attempt"] == 2
        for row in after["s12_export_run"]
    )

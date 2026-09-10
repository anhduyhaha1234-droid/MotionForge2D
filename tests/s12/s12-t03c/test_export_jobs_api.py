"""S12-T03C job/API tests — submit/status/cancel/retry + reconciler.

Runs against real migrated temp DBs (never MAIN, never production).
Covers contract §6 lifecycle: enqueue (no render in request), status
shape, atomic cancel, retry convergence (one usable successor), reconciler
expiry release vs live-lease skip, stale-identity fail-closed.  Retry setup
is explicitly FIXTURE_ONLY mechanism coverage over an isolated migrated DB;
it is not normal-product export evidence.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.api.routes import s12_export as route
from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.jobs import JobRepository
from app.persistence.s12_export import S12ExportRepository
from app.persistence.structural_lock import StructuralLockRepository
from app.workflow.job_service import JobService
from app.workflow.s12_export_jobs import (
    S12_EXPORT_JOB_TYPE,
    S12ExportSubmitError,
    reconcile_export_jobs,
    submit_export_job,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "s12" / "s12-t01"))
from test_preflight_contract import _seed_s10_authority  # noqa: E402

WS = "ws-s12t03c"
OTHER_WS = "ws-s12t03c-other"

CHK_HASH = "c" * 64
PLAN_ID = "d" * 64
PLAN_HASH = "e" * 64


def _config(db: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def _manifest_doc() -> dict[str, Any]:
    return {
        "frame_count": 100,
        "timebase": {"fps": 30.0, "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t03c.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    with factory() as seed:
        for ws in (WS, OTHER_WS):
            tag = "a" if ws == WS else "b"
            seed.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": ws})
            seed.execute(
                text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
                {"p": f"p-{ws}", "w": ws},
            )
            seed.execute(
                text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"),
                {"v": f"v-{ws}", "p": f"p-{ws}"},
            )
            seed.execute(
                text(f"INSERT INTO character(id,workspace_id,name,code) VALUES ('ch-{tag}',:w,'H','h-{tag}')"),
                {"w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
                    f" VALUES ('pv-{tag}','ch-{tag}',:w,1,'published')"
                ),
                {"w": ws},
            )
            seed.execute(
                text(
                    "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                    f"source_generation,name,kind,status) VALUES ('rl-{tag}',:w,:p,:v,'g','C','character','confirmed')"
                ),
                {"w": ws, "p": f"p-{ws}", "v": f"v-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,cast_mapping_id,"
                    f"character_id,pack_version_id,params_json,idempotency_key,revision) VALUES ('rc-{tag}',:w,:p,"
                    f"'rl-{tag}',NULL,'ch-{tag}','pv-{tag}','{{}}',NULL,1)"
                ),
                {"w": ws, "p": f"p-{ws}"},
            )
            seed.execute(
                text(
                    "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                    "reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,"
                    "snapshot_json,checkpoint_hash,note,idempotency_key,revision)"
                    f" VALUES ('ac-{tag}',:w,:p,'rc-{tag}',1,'[]','[]','tb','{{}}',:h,NULL,NULL,1)"
                ),
                {"w": ws, "p": f"p-{ws}", "h": CHK_HASH},
            )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(WS, f"p-{WS}", f"v-{WS}", "gen1", _manifest_doc())
            s2.commit()
            seed_manifest = m1.id
    # FIXTURE_ONLY: use the current T01 authority factory so retry exercises
    # server-current pins; this isolated mechanism fixture is not product
    # readiness or normal-export evidence.
    managed = tmp_path / "artifacts"
    with factory() as authority_session:
        auth = _seed_s10_authority(
            authority_session,
            ws=WS,
            pid=f"p-{WS}",
            vid=f"v-{WS}",
            ckpt={
                "checkpoint_id": "ac-a",
                "checkpoint_hash": CHK_HASH,
                "checkpoint_revision": 1,
            },
            frame_count=100,
            fps_num=30,
            fps_den=1,
        )
    source = managed / "apply" / f"{auth['artifact_id']}.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"FIXTURE_ONLY_SOURCE_MEDIA")
    with factory() as authority_session:
        authority_session.execute(
            text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"),
            {"rel": str(source.relative_to(managed)).replace("\\", "/"), "aid": auth["artifact_id"]},
        )
        authority_session.commit()
    svc = JobService(factory, managed_root=managed)
    dirs = {
        "chunk": str(tmp_path / "chunks"),
        "scratch": str(tmp_path / "scratch"),
        "output": str(tmp_path / "out.mp4"),
    }
    yield factory, svc, seed_manifest, dirs
    engine = create_engine_for_path(db)
    engine.dispose()


def _manifest_hash(factory: Any, manifest_id: str) -> str:
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        assert row is not None
        return str(row.manifest_hash)


def _submit_kwargs(factory: Any, manifest_id: str, dirs: dict[str, str], **over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": _manifest_hash(factory, manifest_id),
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": 100,
        "chunk_config": {"overlap": 5, "max_frames": 50},
        "source_path": str(PROJECT_ROOT / "tests" / "s12" / "s12-t03a" / "test_s12_export_domain.py"),
        "fps": 30.0,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
    }
    kw.update(over)
    return kw


def _current_s10_pins(factory: Any) -> dict[str, Any]:
    """Read the server-current Full Apply pins seeded by the fixture factory."""
    from app.persistence.models import S10FullApplyRun

    with factory() as s:
        row = (
            s.query(S10FullApplyRun)
            .filter_by(workspace_id=WS, project_id=f"p-{WS}", video_item_id=f"v-{WS}")
            .filter_by(status="completed")
            .order_by(S10FullApplyRun.created_at.desc(), S10FullApplyRun.id.desc())
            .first()
        )
        assert row is not None
        return {
            "plan_id": str(row.plan_id),
            "plan_hash": str(row.plan_hash),
            "frame_count": int(row.frame_count),
        }


def test_submit_pins_run_and_enqueues_job(env) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, job, created = submit_export_job(svc, **_submit_kwargs(factory, manifest_id, dirs))
    assert created is True
    assert run.status == "pending"
    assert run.profile_dims == "3840x2160"
    job_type = getattr(job, "job_type", None)
    assert job_type == S12_EXPORT_JOB_TYPE
    assert getattr(job, "state", None) == "queued"
    with factory() as s:
        jobs = [
            j for j in JobRepository(s).list_jobs(WS, limit=1000)
            if j.idempotency_key == f"s12_export_job:{run.id}"
        ]
    assert len(jobs) == 1
    assert jobs[0].id == getattr(job, "job_id", None)


def test_submit_replay_converges_no_duplicate(env) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    kw = _submit_kwargs(factory, manifest_id, dirs, idempotency_key="idem-1")
    run1, job1, created1 = submit_export_job(svc, **kw)
    run2, job2, created2 = submit_export_job(svc, **kw)
    assert created1 is True
    assert created2 is False
    assert run1.id == run2.id
    assert getattr(job1, "job_id", None) == getattr(job2, "job_id", None)
    with factory() as s:
        jobs = [
            j for j in JobRepository(s).list_jobs(WS, limit=1000)
            if j.idempotency_key == f"s12_export_job:{run1.id}"
        ]
    assert len(jobs) == 1


def test_status_payload_shape(env) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(svc, **_submit_kwargs(factory, manifest_id, dirs))
    with factory() as s:
        payload = route._run_payload(s, run.id, WS)
    assert payload["run_id"] == run.id
    assert payload["status"] == "pending"
    assert payload["job_state"] == "queued"
    assert payload["project_id"] == f"p-{WS}"
    assert isinstance(payload["chunks"], list)


def test_cancel_transitions_run_and_job(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(svc, **_submit_kwargs(factory, manifest_id, dirs))
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as s:
        out = route.cancel_export(run.id, s, workspace_id=WS, project_id=None)
        s.commit()
    assert out["cancelled"] is True
    assert out["status"] == "cancelled"
    with factory() as s2:
        payload = route._run_payload(s2, run.id, WS)
    assert payload["status"] == "cancelled"
    assert payload["job_state"] in ("cancelling", "cancelled")
    with factory() as s3:
        with pytest.raises(Exception) as exc:
            route.cancel_export(run.id, s3, workspace_id=WS, project_id=None)
        s3.rollback()
    assert "terminal" in str(exc.value)


def test_retry_after_cancel_converges(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    managed = Path(dirs["output"]).parent / "artifacts"
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    # FIXTURE_ONLY: a predecessor is given a fixture-scoped natural key so the
    # real retry route must create a usable successor; repeat retry converges
    # on that successor by the supported retry idempotency key.
    run, _job, _ = submit_export_job(
        svc,
        **_submit_kwargs(
            factory,
            manifest_id,
            dirs,
            **_current_s10_pins(factory),
            natural_key=f"FIXTURE_ONLY:cancelled-predecessor:{manifest_id}",
        ),
    )
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as s:
        route.cancel_export(run.id, s, workspace_id=WS, project_id=None)
        s.commit()
    with factory() as s:
        first = route.retry_export(run.id, s, workspace_id=WS, project_id=None)
        s.commit()
    assert first["run_id"] != run.id
    assert first["predecessor_run_id"] == run.id
    assert first["status"] == "pending"
    assert first["created"] is True
    assert first["job_id"]
    with factory() as s:
        second = route.retry_export(run.id, s, workspace_id=WS, project_id=None)
        s.rollback()
    assert second["run_id"] == first["run_id"]
    assert second["predecessor_run_id"] == run.id
    assert second["created"] is False
    with factory() as s:
        from app.persistence.models import S12ExportRun

        runs = [
            r
            for r in s.query(S12ExportRun)
            .filter_by(workspace_id=WS)
            .all()
        ]
        jobs = [j for j in JobRepository(s).list_jobs(WS, limit=1000) if j.job_type == S12_EXPORT_JOB_TYPE]
    assert len(runs) == 2
    assert {r.id for r in runs} == {run.id, first["run_id"]}
    assert sum(r.status == "cancelled" for r in runs) == 1
    assert sum(r.status == "pending" for r in runs) == 1
    assert len(jobs) == 2


def test_retry_active_predecessor_fails_closed(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(svc, **_submit_kwargs(factory, manifest_id, dirs))
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    with factory() as s:
        with pytest.raises(Exception) as exc:
            route.retry_export(run.id, s, workspace_id=WS, project_id=None)
        s.rollback()
    assert "active" in str(exc.value).lower() or "pending" in str(exc.value).lower()


def test_reconcile_reports_expired_lease_resumable(env) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(svc, **_submit_kwargs(factory, manifest_id, dirs))
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-1")
        s.commit()
        fence = lease.fence_token
    with factory() as s:
        from app.persistence.models import S12ExportLease as LeaseRow

        orm = s.get(LeaseRow, (run.id,))
        assert orm is not None
        orm.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
        s.commit()
    report = reconcile_export_jobs(factory, batch_size=10)
    assert report["scanned"] == 1
    assert report["expired"] == 1
    assert run.id in report["resumable"]
    assert report["errors"] == []
    # Zero-mutation: the run stays running and a fresh claim CAS re-claims
    # the expired lease with a NEW fence token (T03A C2 fencing).
    with factory() as s:
        run_row = S12ExportRepository(s).get_run(run.id)
        assert run_row.status == "running"
    with factory() as s:
        lease2 = S12ExportRepository(s).claim_run(run.id, "worker-2")
        s.commit()
    assert lease2.fence_token != fence


def test_reconcile_skips_live_lease(env) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    run, _job, _ = submit_export_job(svc, **_submit_kwargs(factory, manifest_id, dirs))
    with factory() as s:
        S12ExportRepository(s).claim_run(run.id, "worker-1")
        s.commit()
    report = reconcile_export_jobs(factory, batch_size=10)
    assert report["scanned"] == 1
    assert report["expired"] == 0
    assert report["resumable"] == []
    assert report["errors"] == []


def test_submit_stale_identity_fails_closed(env) -> None:  # type: ignore[no-untyped-def]
    factory, svc, manifest_id, dirs = env
    with pytest.raises(S12ExportSubmitError):
        submit_export_job(
            svc, **_submit_kwargs(factory, manifest_id, dirs, checkpoint_hash="f" * 64)
        )

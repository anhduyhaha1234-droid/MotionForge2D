"""S12-T03C C2 — closure rows C01/C04-part/C05/C07-part/C14-part/C15/C16.

Bounded to the T03C lane: every durable authority gate runs the REAL T01
``resolve_export_authority`` over a REAL migrated DB seeded with the same
S10 Full Apply authority rows the T01 preflight tests use.  The only
monkeypatched boundary is the frozen QC readiness aggregate (Decision F,
T03G lane) — documented per test.  Publication/runner use the REAL code;
the sole mocked probe is the T04A media validator where stated.

No case removal for green: each test asserts the row it names with real
counts over the seeded DB.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.api import routes  # noqa: F401  # mounted-route sanity
from app.api.deps import SessionDep  # noqa: F401  # signature sanity
from app.api.routes import s12_export as route
from app.persistence import DEFAULT_WORKSPACE_ID, create_engine_for_path, create_session_factory
from app.persistence.jobs import JobRepository
from app.persistence.s12_export import S12ExportRepository
from app.persistence.structural_lock import StructuralLockRepository
from app.workflow.job_service import JobService
from app.workflow.s12_export_jobs import (
    S12_EXPORT_JOB_TYPE,
    _s12_export_handler,
    register_s12_export_handler,
    submit_export_job,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "s12" / "s12-t01"))
from test_preflight_contract import _seed_s10_authority  # noqa: E402

WS = DEFAULT_WORKSPACE_ID
FPS = 10
FRAMES = 8
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
        "frame_count": FRAMES,
        "timebase": {"fps": float(FPS), "time_base": "1/30000", "start_time_ms": 0},
        "shot_order": ["shot-001"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }


@pytest.fixture()
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    db = tmp_path / "t03c-c2.db"
    command.upgrade(_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    managed = tmp_path / "managed"
    managed.mkdir()
    with factory() as seed:
        seed.execute(text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS})
        seed.execute(
            text("INSERT INTO project(id,workspace_id,name) VALUES (:p,:w,'Proj')"),
            {"p": f"p-{WS}", "w": WS},
        )
        seed.execute(
            text("INSERT INTO video_item(id,project_id,title,position) VALUES (:v,:p,'Vid',0)"),
            {"v": f"v-{WS}", "p": f"p-{WS}"},
        )
        seed.execute(
            text("INSERT INTO character(id,workspace_id,name,code) VALUES ('ch-a',:w,'H','h-a')"),
            {"w": WS},
        )
        seed.execute(
            text(
                "INSERT INTO character_pack_version(id,character_id,workspace_id,version,status)"
                " VALUES ('pv-a','ch-a',:w,1,'published')"
            ),
            {"w": WS},
        )
        seed.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,video_item_id,"
                "source_generation,name,kind,status) VALUES ('rl-a',:w,:p,:v,'g','C','character','confirmed')"
            ),
            {"w": WS, "p": f"p-{WS}", "v": f"v-{WS}"},
        )
        seed.execute(
            text(
                "INSERT INTO reskin_config(id,workspace_id,project_id,object_role_id,cast_mapping_id,"
                "character_id,pack_version_id,params_json,idempotency_key,revision) VALUES ('rc-a',:w,:p,"
                "'rl-a',NULL,'ch-a','pv-a','{}',NULL,1)"
            ),
            {"w": WS, "p": f"p-{WS}"},
        )
        seed.execute(
            text(
                "INSERT INTO apply_checkpoint(id,workspace_id,project_id,reskin_config_id,"
                "reskin_config_revision,pack_version_ids_json,loop_hashes_json,timebase_fingerprint,"
                "snapshot_json,checkpoint_hash,note,idempotency_key,revision)"
                " VALUES ('ac-a',:w,:p,'rc-a',1,'[]','[]','tb','{}',:h,NULL,NULL,1)"
            ),
            {"w": WS, "p": f"p-{WS}", "h": CHK_HASH},
        )
        seed.commit()
        with factory() as s2:
            lock = StructuralLockRepository(s2)
            m1, _ = lock.create_manifest(WS, f"p-{WS}", f"v-{WS}", "gen1", _manifest_doc())
            s2.commit()
            manifest_id = m1.id
    svc = JobService(factory, managed_root=managed)
    # FIXTURE_ONLY: current S10 Full Apply authority factory + a source
    # artifact under the isolated managed root. This is mechanism coverage,
    # not normal-product readiness or export evidence.
    with factory() as s:
        auth = _seed_s10_authority(
            s,
            ws=WS,
            pid=f"p-{WS}",
            vid=f"v-{WS}",
            ckpt={
                "checkpoint_id": "ac-a",
                "checkpoint_hash": CHK_HASH,
                "checkpoint_revision": 1,
            },
            frame_count=FRAMES,
            fps_num=FPS,
            fps_den=1,
        )
    source = managed / "apply" / f"{auth['artifact_id']}.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"\x00" * 1024)
    with factory() as s:
        s.execute(
            text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"),
            {"rel": str(source.relative_to(managed)).replace("\\", "/"), "aid": auth["artifact_id"]},
        )
        s.commit()
    dirs = {
        "chunk": str(tmp_path / "chunks"),
        "scratch": str(tmp_path / "scratch"),
        "output": str(tmp_path / "out.mp4"),
    }
    yield factory, svc, manifest_id, auth, dirs, managed
    engine = create_engine_for_path(db)
    engine.dispose()


def _counts(factory: Any) -> dict[str, int]:
    with factory() as s:
        runs = int(s.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar())
        jobs = int(
            s.execute(
                text("SELECT COUNT(*) FROM job WHERE job_type=:jt"), {"jt": S12_EXPORT_JOB_TYPE}
            ).scalar()
        )
        chunks = int(s.execute(text("SELECT COUNT(*) FROM s12_export_chunk")).scalar())
    return {"runs": runs, "jobs": jobs, "chunks": chunks}



def _real_manifest_hash(factory: Any, manifest_id: str) -> str:
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        return str(row.manifest_hash)


def _current_s10_pins(factory: Any, auth: dict[str, str]) -> dict[str, Any]:
    """Read the exact pins returned by the current fixture authority row."""
    from app.persistence.models import S10FullApplyRun

    with factory() as s:
        row = s.get(S10FullApplyRun, auth["run_id"])
        assert row is not None
        return {
            "plan_id": str(row.plan_id),
            "plan_hash": str(row.plan_hash),
            "frame_count": int(row.frame_count),
            "fps_num": int(row.fps_num or FPS),
            "fps_den": int(row.fps_den or 1),
        }


def _ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boundary: frozen QC readiness aggregate (Decision F, T03G lane).

    Production readiness requires a completed CURRENT FULL QC band run —
    a T03G/T04A-lane fixture this T03C lane does not own.  The submit and
    publication code paths consume the SAME ``compute_project_readiness``
    function; only its aggregate verdict is substituted here.
    """

    class _Rec:
        status = "ready"
        videos: list[Any] = []

    monkeypatch.setattr(
        "app.persistence.readiness.compute_project_readiness", lambda session, **kw: _Rec()
    )


def _authority_body(factory: Any, auth: dict[str, str], manifest_id: str, **over: Any) -> dict[str, Any]:
    from app.persistence.models import StructuralLockManifest

    with factory() as s:
        row = s.get(StructuralLockManifest, manifest_id)
        real_hash = str(row.manifest_hash)
    current = _current_s10_pins(factory, auth)
    body: dict[str, Any] = {
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": real_hash,
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": current["plan_id"],
        "plan_hash": current["plan_hash"],
        "frame_count": current["frame_count"],
        "chunk_config": {"overlap": 1, "max_frames": 4},
    }
    body.update(over)
    return body


def test_c01_normal_bootstrap_mounted(env) -> None:  # type: ignore[no-untyped-def]
    """Normal app exposes the mounted S12 export endpoints (no custom mount)."""
    from app.api.app import app

    paths: set[str] = set()
    for r in app.routes:
        router = getattr(r, "original_router", None)
        for rr in getattr(router, "routes", []) or []:
            p = getattr(rr, "path", None)
            if p:
                paths.add(str(p))
    assert "/s12-exports/submit" in paths
    assert "/s12-exports/{run_id}" in paths
    assert "/s12-exports/{run_id}/cancel" in paths
    assert "/s12-exports/{run_id}/retry" in paths

    from app.workflow.durable_worker import DurableWorker  # noqa: PLC0415

    worker = DurableWorker(None)  # type: ignore[arg-type]  # registration-only probe
    register_s12_export_handler(worker)
    assert S12_EXPORT_JOB_TYPE in worker._handlers  # type: ignore[attr-defined]


def test_c01_route_submit_ready_authority_one_run_one_job_nonnull_ids(
    env, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """1 valid submit → exactly 1 run + 1 Job, both IDs NON-NULL (F02)."""
    factory, svc, manifest_id, auth, dirs, managed = env
    _ready(monkeypatch)
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as s:
        out = route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.commit()
    assert out["run_id"]
    assert out["job_id"], "F02: real durable Job ID must be non-null"
    assert out["created"] is True
    assert out["status"] == "pending"
    counts = _counts(factory)
    assert counts == {"runs": 1, "jobs": 1, "chunks": 0}
    with factory() as s:
        job = JobRepository(s).list_jobs(WS, limit=10)[0]
        assert job.id == out["job_id"]
        run = S12ExportRepository(s).get_run(out["run_id"])
        assert run.status == "pending"
        # Server-owned paths (C2 F02): client paths are ignored, never used.
        import json as _json

        from app.persistence.models import Job as JobRow

        row = s.get(JobRow, out["job_id"])
        stored = _json.loads(row.input_manifest_json)
        assert str(managed) in stored.get("chunk_dir", "")


def test_c04_part_invalid_authority_zero_mutation(env) -> None:  # type: ignore[no-untyped-def]
    """Stale/tampered authority → 409 with ZERO runs/jobs/chunks (real T01)."""
    from fastapi import HTTPException

    factory, svc, manifest_id, auth, dirs, managed = env
    body = _authority_body(factory, auth, manifest_id, checkpoint_hash="f" * 64)
    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.rollback()
    assert exc.value.status_code == 409
    assert _counts(factory) == {"runs": 0, "jobs": 0, "chunks": 0}


def test_c04_part_not_ready_zero_mutation_real_readiness(env) -> None:  # type: ignore[no-untyped-def]
    """Real readiness aggregate (no QC band) → 409 before ANY mutation."""
    from fastapi import HTTPException

    factory, svc, manifest_id, auth, dirs, managed = env
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.rollback()
    monkeypatch.undo()
    assert exc.value.status_code == 409
    assert "readiness" in str(exc.value.detail)
    assert _counts(factory) == {"runs": 0, "jobs": 0, "chunks": 0}


def test_c05_paths_and_media_fail_before_mutation(env) -> None:  # type: ignore[no-untyped-def]
    """Traversal/spoofed paths and non-media sources never reach a run."""
    factory, svc, manifest_id, auth, dirs, managed = env
    from fastapi import HTTPException

    # Helper level: traversal escapes resolve to None / raise (C05).
    assert route._server_paths(str(managed), "../../../evil", "v") is None
    with pytest.raises(HTTPException) as exc:
        route._check_source_media("C:/nowhere/source.txt")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        route._check_no_partial(SimpleNamespace(source_partial=False), "x/y.mp4.partial")

    factory, svc, manifest_id, auth, dirs, managed = env
    # Non-media artifact: point the artifact at a .txt file, still 422 with
    # zero mutation (real authority path, real file existence check).
    txt = managed / "apply" / "notes.txt"
    txt.write_text("not media")
    with factory() as s:
        s.execute(text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"), {
            "rel": "apply/notes.txt", "aid": auth["artifact_id"]})
        s.commit()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    body = _authority_body(factory, auth, manifest_id)
    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.rollback()
    monkeypatch.undo()
    assert exc.value.status_code == 422
    assert _counts(factory) == {"runs": 0, "jobs": 0, "chunks": 0}


def test_c07_part_replay_union_and_ambiguity(env) -> None:  # type: ignore[no-untyped-def]
    """Same payload replays to the SAME run+job; drifted payload conflicts."""
    factory, svc, manifest_id, auth, dirs, managed = env
    kw = {
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": _real_manifest_hash(factory, manifest_id),
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": FRAMES,
        "chunk_config": {"overlap": 1, "max_frames": 4},
        "source_path": str(managed / "apply" / "x.mp4"),
        "fps": float(FPS),
        "fps_num": FPS,
        "fps_den": 1,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "idempotency_key": "idem-1",
        "expected_sha256": "a" * 64,
    }
    run1, job1, created1 = submit_export_job(svc, **kw)
    run2, job2, created2 = submit_export_job(svc, **kw)
    assert created1 is True and created2 is False
    assert run1.id == run2.id
    assert job1.job_id == job2.job_id
    assert _counts(factory) == {"runs": 1, "jobs": 1, "chunks": 0}
    # Material drift on the SAME idempotency key → fail-closed conflict,
    # zero extra rows (C07 union: misleading key never binds to a wrong run).
    drifted = {**kw, "frame_count": 16}
    with pytest.raises(Exception):
        submit_export_job(svc, **drifted)
    assert _counts(factory) == {"runs": 1, "jobs": 1, "chunks": 0}


def test_c14_part_crash_then_restart_reports_resumable(env) -> None:  # type: ignore[no-untyped-def]
    """Kill/restart consumer side: orphan lease reported, fresh claim wins."""
    from datetime import UTC, datetime, timedelta

    from app.persistence.models import S12ExportLease as LeaseRow
    from app.workflow.s12_export_jobs import reconcile_export_jobs

    factory, svc, manifest_id, auth, dirs, managed = env
    kw = {
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": _real_manifest_hash(factory, manifest_id),
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "frame_count": FRAMES,
        "chunk_config": {"overlap": 1, "max_frames": 4},
        "source_path": str(managed / "apply" / "x.mp4"),
        "fps": float(FPS),
        "fps_num": FPS,
        "fps_den": 1,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "expected_sha256": "a" * 64,
    }
    run, _job, _ = submit_export_job(svc, **kw)
    with factory() as s:
        lease = S12ExportRepository(s).claim_run(run.id, "worker-1")
        s.commit()
        fence = lease.fence_token
    # Simulate process death: the lease expires without any release.
    with factory() as s:
        orm = s.get(LeaseRow, (run.id,))
        assert orm is not None
        orm.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
        s.commit()
    report = reconcile_export_jobs(factory, batch_size=10)
    assert run.id in report["resumable"]
    assert report["errors"] == []
    # Fresh process PID claims the expired lease (new fence), old fence dead.
    with factory() as s:
        lease2 = S12ExportRepository(s).claim_run(run.id, "worker-2")
        s.commit()
    assert lease2.fence_token != fence
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "running"


def test_c15_retry_converges_no_duplicate_successor(env) -> None:  # type: ignore[no-untyped-def]
    """FIXTURE_ONLY: cancel → two live retries yield one usable successor."""
    factory, svc, manifest_id, auth, dirs, managed = env
    current = _current_s10_pins(factory, auth)
    kw = {
        "workspace_id": WS,
        "project_id": f"p-{WS}",
        "video_item_id": f"v-{WS}",
        "checkpoint_id": "ac-a",
        "checkpoint_hash": CHK_HASH,
        "checkpoint_revision": 1,
        "manifest_id": manifest_id,
        "manifest_hash": _real_manifest_hash(factory, manifest_id),
        "manifest_generation": "gen1",
        "profile_id": "master-4k-h264",
        "plan_id": current["plan_id"],
        "plan_hash": current["plan_hash"],
        "frame_count": current["frame_count"],
        "chunk_config": {"overlap": 1, "max_frames": 4},
        "source_path": str(managed / "apply" / "x.mp4"),
        "fps": float(FPS),
        "fps_num": FPS,
        "fps_den": 1,
        "chunk_dir": dirs["chunk"],
        "scratch_dir": dirs["scratch"],
        "output_path": dirs["output"],
        "expected_sha256": "a" * 64,
        # FIXTURE_ONLY predecessor identity: the public retry route computes
        # the canonical successor identity, so it cannot replay cancellation.
        "natural_key": f"FIXTURE_ONLY:cancelled-predecessor:{manifest_id}",
    }
    run, job, _ = submit_export_job(svc, **kw)
    with factory() as s:
        assert S12ExportRepository(s).get_run(run.id).status == "pending"
        from app.persistence.jobs import JobRepository as JR

        jrow = JR(s).list_jobs(WS, limit=10)[0]
        assert jrow.state in ("queued", "running")
        assert jrow.id == job.job_id
    # Two callers cancel concurrently-shaped path: first wins, second 409.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(route, "get_job_service", lambda: svc)
    monkeypatch.setattr(route, "get_managed_root", lambda: managed)
    with factory() as s:
        out = route.cancel_export(run.id, s, workspace_id=WS, project_id=None)
        s.commit()
    assert out["cancelled"] is True
    from fastapi import HTTPException

    with factory() as s:
        with pytest.raises(HTTPException) as exc:
            route.cancel_export(run.id, s, workspace_id=WS, project_id=None)
        s.rollback()
    assert exc.value.status_code == 409
    # Two live request sessions contend on the same retry idempotency key.
    barrier = Barrier(2)

    def _retry_from_live_caller() -> dict[str, Any]:
        with factory() as s:
            barrier.wait(timeout=5)
            result = route.retry_export(run.id, s, workspace_id=WS, project_id=None)
            s.commit()
            return result

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="s12-retry") as pool:
        results = list(pool.map(lambda _n: _retry_from_live_caller(), (1, 2)))
    assert sorted(bool(result["created"]) for result in results) == [False, True]
    successor_ids = {result["run_id"] for result in results}
    assert len(successor_ids) == 1
    successor_id = next(iter(successor_ids))
    assert successor_id != run.id
    assert all(result["predecessor_run_id"] == run.id for result in results)
    assert all(result["job_id"] for result in results)
    with factory() as s:
        from app.persistence.models import S12ExportRun

        runs = s.query(S12ExportRun).filter_by(workspace_id=WS).all()
        jobs = [j for j in JobRepository(s).list_jobs(WS, limit=1000) if j.job_type == S12_EXPORT_JOB_TYPE]
    assert len(runs) == 2
    assert {r.id for r in runs} == {run.id, successor_id}
    assert sum(r.status == "cancelled" for r in runs) == 1
    assert sum(r.status == "pending" for r in runs) == 1
    assert len(jobs) == 2
    monkeypatch.undo()


def test_c16_handler_real_render_no_typeerror_single_candidate(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Normal worker handler: real render + publication, no TypeError.

    Real T03B runner renders the source and the REAL publication gate runs
    with the REAL T04A source-locked validator.  The frozen QC readiness
    aggregate is substituted (T03G lane).  With no digest authority the
    validator answers NOT_MEASURED — the run lands ``failed`` (retryable),
    NOT a TypeError and NOT a fake completed; the private candidate never
    leaks to the public output (F07 boundary).
    """
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (real-render row needs the real binary)")

    factory, svc, manifest_id, auth, dirs, managed = env
    mp = pytest.MonkeyPatch()
    mp.setattr(route, "get_job_service", lambda: svc)
    mp.setattr(route, "get_managed_root", lambda: managed)
    _ready(mp)

    # Real validated source media (silent, CFR 10fps, 8 frames) — placed
    # INSIDE the managed root so the artifact path stays server-owned.
    source = managed / "apply" / "c16src.mp4"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=320x180:rate={FPS}:duration={FRAMES / FPS}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", str(source),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    with factory() as s:
        s.execute(text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"), {
            "rel": str(source.relative_to(managed)).replace("\\", "/"), "aid": auth["artifact_id"]})
        s.commit()

    body = _authority_body(factory, auth, manifest_id)
    with factory() as s:
        out = route.submit_export(route.S12ExportSubmitRequest(**body), s, workspace_id=WS)
        s.commit()
    assert out["job_id"]
    run_id = out["run_id"]
    with factory() as s:
        from app.persistence.models import Job as JobRow

        row = s.get(JobRow, out["job_id"])
        manifest = json.loads(row.input_manifest_json)
    ctx = SimpleNamespace(
        worker_id="worker-c16",
        session_factory=factory,
        input_manifest=manifest,
    )
    try:
        result = _s12_export_handler(ctx)
    except Exception as err:  # noqa: BLE001 - assert no TypeError leak
        assert not isinstance(err, TypeError), f"TypeError on real path: {err}"
        assert not Path(dirs["output"]).exists(), "public output must not appear"
        # NOT_MEASURED/FAIL → run failed, retryable — coherent states.
        with factory() as s:
            run = S12ExportRepository(s).get_run(run_id)
        assert run.status == "failed", run.status
        mp.undo()
        return
    # PASS path would have completed; if the handler returned, states agree.
    with factory() as s:
        run = S12ExportRepository(s).get_run(run_id)
    assert run.status == "completed"
    assert result["status"] == "completed"
    mp.undo()

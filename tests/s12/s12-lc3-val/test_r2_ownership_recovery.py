"""S12-LC3-R2 ownership and publication recovery controls."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

TEST03C = Path(__file__).resolve().parents[1] / "s12-t03c"

sys.path.insert(0, str(TEST03C))
import test_publication as publication_base  # noqa: E402

from app.persistence.s12_export import S12ExportRepository  # noqa: E402
from app.persistence.jobs import JobRepository  # noqa: E402
from app.services.s12_export import publication as pub  # noqa: E402


env = publication_base.env


def _owner_manifest(kw: dict[str, Any], scratch: Path) -> dict[str, Any]:
    scratch.mkdir(parents=True, exist_ok=True)
    manifest = dict(kw["manifest"])
    manifest["scratch_dir"] = str(scratch)
    manifest["candidate_path"] = str(scratch / "candidate_final.mp4")
    return manifest


def _file_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    payload = path.read_bytes()
    return {
        "sha256": pub._sha256_file(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "bytes": payload,
    }


def _durable_rows(factory: Any, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with factory() as session:
        repo = S12ExportRepository(session)
        run = repo.get_run(run_id)
        jobs = JobRepository(session).list_jobs(publication_base.WS, limit=1000)
        job = next(
            item
            for item in jobs
            if item.idempotency_key == f"s12_export_job:{run_id}"
        )
        return asdict(run), asdict(job)


def test_r2_f01_real_handoff_cannot_overwrite_winner(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Reproduce A pausing before exclusive publication while B reclaims."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    root = Path(kw["manifest"]["scratch_dir"]).parent
    a_candidate = root / "owner-a" / "candidate_final.mp4"
    b_candidate = root / "owner-b" / "candidate_final.mp4"
    a_candidate.parent.mkdir(parents=True, exist_ok=True)
    b_candidate.parent.mkdir(parents=True, exist_ok=True)
    a_payload = b"winner must not be overwritten by stale owner A"
    b_payload = b"current owner B completed bytes"
    a_candidate.write_bytes(a_payload)
    a_manifest = _owner_manifest(kw, a_candidate.parent)
    ready = threading.Event()
    resume = threading.Event()
    paused = False

    def rendezvous(source: Path, destination: Path) -> None:
        nonlocal paused
        if Path(source) == a_candidate and not paused:
            paused = True
            ready.set()
            assert resume.wait(10), "A rendezvous was not released"

    monkeypatch.setattr(pub, "_before_publication_primitive", rendezvous)
    a_errors: list[BaseException] = []

    def run_a() -> None:
        try:
            with factory() as session:
                pub.publish_export_run(
                    session,
                    run_id=kw["run_id"],
                    workspace_id=kw["workspace_id"],
                    project_id=kw["project_id"],
                    worker_id=kw["worker_id"],
                    fence_token=kw["fence_token"],
                    manifest=a_manifest,
                )
        except BaseException as err:  # expected loser path in repaired test
            a_errors.append(err)

    worker_a = threading.Thread(target=run_a, name="s12-r2-owner-a")
    worker_a.start()
    assert ready.wait(10), "A did not reach the pre-publication rendezvous"

    with factory() as session:
        session.execute(
            text(
                "UPDATE s12_export_lease SET expires_at=:now, heartbeat_at=:now "
                "WHERE run_id=:run_id"
            ),
            {"now": datetime.now(UTC), "run_id": kw["run_id"]},
        )
        session.commit()
    with factory() as session:
        b_lease = S12ExportRepository(session).claim_run(kw["run_id"], "worker-B")
        session.commit()
    b_candidate.write_bytes(b_payload)
    b_manifest = _owner_manifest(kw, b_candidate.parent)
    with factory() as session:
        b_out = pub.publish_export_run(
            session,
            run_id=kw["run_id"],
            workspace_id=kw["workspace_id"],
            project_id=kw["project_id"],
            worker_id="worker-B",
            fence_token=b_lease.fence_token,
            manifest=b_manifest,
        )
        session.commit()
    final = Path(kw["manifest"]["output_path"])
    companions = [
        final,
        pub._sidecar_path(final),
        pub._publication_receipt_path(final),
    ]
    winner_files = {str(path): _file_identity(path) for path in companions}
    winner_run, winner_job = _durable_rows(factory, kw["run_id"])
    resume.set()
    worker_a.join(timeout=10)
    assert not worker_a.is_alive()

    print(
        "R2_F01_MICRO "
        f"winner={b_out.get('status')} loser={type(a_errors[0]).__name__ if a_errors else None} "
        f"final_sha256={winner_files[str(final)]['sha256']} "
        f"run_status={winner_run['status']} job_state={winner_job['state']}"
    )
    assert b_out["status"] == "completed"
    assert a_errors
    assert isinstance(a_errors[0], pub.PublicationRaceLost)
    assert getattr(a_errors[0], "code", None) == "S12_T03C_PUBLICATION_RACE_LOST"
    assert final.read_bytes() == b_payload
    assert {str(path): _file_identity(path) for path in companions} == winner_files
    assert _durable_rows(factory, kw["run_id"]) == (winner_run, winner_job)
    assert a_candidate.is_file()
    assert a_candidate.read_bytes() == a_payload


def test_r2_f02_foreign_companion_is_not_overwritten(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A foreign sidecar must block publication instead of being replaced."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    sidecar = pub._sidecar_path(final)
    sidecar.write_text("foreign-sidecar\n", encoding="ascii")
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    before = sidecar.read_bytes()
    with factory() as session:
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(session, **kw)
        session.rollback()
    print(
        "R2_F02_MICRO "
        f"final_exists={final.exists()} sidecar_unchanged={sidecar.read_bytes() == before} "
        f"candidate_exists={candidate.exists()}"
    )
    assert not final.exists()
    assert sidecar.read_bytes() == before
    assert not candidate.exists()


def test_r2_f02_child_kill_fresh_process_reclaims_same_db_job(
    env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A killed owned child cannot prevent a fresh process reclaiming its job."""
    factory, kw = publication_base._submit(env, monkeypatch)
    bind = factory.kw["bind"]
    db_path = Path(str(bind.url.database))
    chunk_dir = Path(kw["manifest"]["chunk_dir"])
    chunk_dir.mkdir(parents=True, exist_ok=True)
    retained_chunk = chunk_dir / "chunk-000.mp4"
    retained_bytes = b"retained-verified-chunk"
    retained_chunk.write_bytes(retained_bytes)
    before_rows = _durable_rows(factory, kw["run_id"])
    marker = tmp_path / "child-marker.json"
    repo_root = Path(__file__).resolve().parents[3]
    ws_id = publication_base.WS
    child_code = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "from app.persistence import create_engine_for_path, create_session_factory\n"
        "from app.persistence.jobs import JobRepository\n"
        "from app.persistence.s12_export import S12ExportRepository\n"
        "db=Path(sys.argv[1]); marker=Path(sys.argv[2]); run_id=sys.argv[3]\n"
        "factory=create_session_factory(create_engine_for_path(db))\n"
        "with factory() as s:\n"
        "    run=S12ExportRepository(s).get_run(run_id)\n"
        f"    jobs=JobRepository(s).list_jobs({ws_id!r}, limit=1000)\n"
        "    job=next(j for j in jobs if j.idempotency_key == 's12_export_job:'+run_id)\n"
        "    marker.write_text(json.dumps({'pid':os.getpid(),'run_id':run.id,'job_id':job.id}), encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(db_path), str(marker), kw["run_id"]],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if marker.exists():
                break
            if child.poll() is not None:
                break
            time.sleep(0.05)
        assert marker.exists(), (child.poll(), child.stderr.read() if child.poll() is not None else "")
        assert child.poll() is None
        child.terminate()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    fresh_marker = tmp_path / "fresh-marker.json"
    fresh_code = (
        "import json, sys\n"
        "from datetime import UTC, datetime\n"
        "from pathlib import Path\n"
        "from sqlalchemy import text\n"
        "from app.persistence import create_engine_for_path, create_session_factory\n"
        "from app.persistence.jobs import JobRepository\n"
        "from app.persistence.s12_export import S12ExportRepository\n"
        "db=Path(sys.argv[1]); marker=Path(sys.argv[2]); run_id=sys.argv[3]\n"
        "factory=create_session_factory(create_engine_for_path(db))\n"
        "with factory() as s:\n"
        "    now=datetime.now(UTC)\n"
        "    s.execute(text('UPDATE s12_export_lease SET expires_at=:now, heartbeat_at=:now WHERE run_id=:run_id'), {'now':now, 'run_id':run_id})\n"
        "    s.commit()\n"
        "with factory() as s:\n"
        "    lease=S12ExportRepository(s).claim_run(run_id, 'worker-fresh')\n"
        "    s.commit()\n"
        "    run=S12ExportRepository(s).get_run(run_id)\n"
        f"    jobs=JobRepository(s).list_jobs({ws_id!r}, limit=1000)\n"
        "    job=next(j for j in jobs if j.idempotency_key == 's12_export_job:'+run_id)\n"
        "    marker.write_text(json.dumps({'worker':lease.worker_id,'run_status':run.status,'job_id':job.id}), encoding='utf-8')\n"
    )
    fresh = subprocess.run(
        [sys.executable, "-c", fresh_code, str(db_path), str(fresh_marker), kw["run_id"]],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert fresh.returncode == 0, fresh.stderr[-1000:]
    fresh_state = json.loads(fresh_marker.read_text(encoding="utf-8"))
    after_rows = _durable_rows(factory, kw["run_id"])
    print(
        "R2_F02_PROCESS_RESTART "
        + json.dumps(
            {
                "killed_pid": json.loads(marker.read_text(encoding="utf-8"))["pid"],
                "fresh_worker": fresh_state["worker"],
                "run_status": fresh_state["run_status"],
                "job_id_stable": fresh_state["job_id"] == before_rows[1]["id"],
                "retained_chunk_sha256": pub._sha256_file(retained_chunk),
            },
            sort_keys=True,
        )
    )
    assert fresh_state["worker"] == "worker-fresh"
    assert fresh_state["run_status"] == "running"
    assert fresh_state["job_id"] == before_rows[1]["id"]
    assert after_rows[1]["id"] == before_rows[1]["id"]
    assert retained_chunk.read_bytes() == retained_bytes

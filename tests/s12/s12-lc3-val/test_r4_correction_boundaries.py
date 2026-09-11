"""S12-LC3-R4 micro regressions for publication recovery and path fencing."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import text

TEST03C = Path(__file__).resolve().parents[1] / "s12-t03c"
sys.path.insert(0, str(TEST03C))
import test_publication as publication_base  # noqa: E402

from app.persistence.s12_export import S12ExportRepository  # noqa: E402
from app.services.s12_export import publication as pub  # noqa: E402

env = publication_base.env


def test_r4_micro_recovery_after_final_before_sidecar(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A fresh fenced owner recovers a real final left before sidecar creation."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"r4 post-final recovery bytes")

    def stop_after_final(final_path: Path) -> None:
        assert final_path == final
        raise RuntimeError("R4_MICRO_STOP_AFTER_FINAL_BEFORE_SIDECAR")

    monkeypatch.setattr(pub, "_after_publication_final", stop_after_final, raising=False)
    with factory() as session:
        with pytest.raises(RuntimeError, match="R4_MICRO_STOP_AFTER_FINAL"):
            pub.publish_export_run(session, **kw)
        session.rollback()

    assert final.is_file()
    assert not pub._sidecar_path(final).exists()
    assert not pub._publication_receipt_path(final).exists()

    with factory() as session:
        session.execute(
            publication_base.text(
                "UPDATE s12_export_lease SET expires_at=acquired_at, "
                "heartbeat_at=acquired_at WHERE run_id=:run_id"
            ),
            {"run_id": kw["run_id"]},
        )
        fresh = S12ExportRepository(session).claim_run(kw["run_id"], "worker-r4-fresh")
        session.commit()

    monkeypatch.setattr(pub, "_after_publication_final", lambda final_path: None)
    fresh_kw = {
        **kw,
        "worker_id": "worker-r4-fresh",
        "fence_token": fresh.fence_token,
    }
    with factory() as session:
        result = pub.publish_export_run(session, **fresh_kw)
        session.commit()

    print(
        "R4_MICRO_POST_FINAL "
        f"status={result['status']} recovered={result.get('recovered')} "
        f"final={final} sha256={pub._sha256_file(final)} "
        f"sidecar={pub._sidecar_path(final).is_file()} "
        f"receipt={pub._publication_receipt_path(final).is_file()}"
    )
    assert result["status"] == "completed"
    assert result["recovered"] is True
    assert pub._sidecar_path(final).is_file()
    assert pub._publication_receipt_path(final).is_file()


def test_r4_micro_preflight_checks_actual_companion_temp_name(
    env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """A name valid for final/sidecars can still fail its actual temp path."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = tmp_path / f"{'x' * 155}.mp4"
    kw["manifest"]["output_path"] = str(final)

    with factory() as session:
        with pytest.raises(pub.PublicationPathError, match="temporary"):
            pub.publish_export_run(session, **kw)
        session.rollback()

    print(
        "R4_MICRO_TEMP_PREFLIGHT "
        f"final={final} final_exists={final.exists()} "
        f"sidecar={pub._sidecar_path(final).exists()} "
        f"receipt={pub._publication_receipt_path(final).exists()}"
    )
    assert not final.exists()
    assert not pub._sidecar_path(final).exists()
    assert not pub._publication_receipt_path(final).exists()


def test_r4_foreign_intent_fails_closed_without_mutating_marker(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A foreign intent cannot authorize a candidate or public mutation."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"foreign intent control")
    intent = pub._publication_intent_path(final)
    foreign = b'{"kind":"s12-publication-intent","run_id":"foreign"}\n'
    intent.write_bytes(foreign)

    with factory() as session:
        with pytest.raises(pub.PublicationError, match="identity mismatch"):
            pub.publish_export_run(session, **kw)
        session.rollback()

    print(
        "R4_FOREIGN_INTENT "
        f"final={final.exists()} intent_unchanged={intent.read_bytes() == foreign} "
        f"candidate={candidate.exists()}"
    )
    assert not final.exists()
    assert intent.read_bytes() == foreign
    assert not candidate.exists()


def test_r4_tampered_intent_candidate_fails_closed(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A validly shaped but tampered candidate identity cannot be adopted."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"tampered intent control")
    with factory() as session:
        run = S12ExportRepository(session).get_run(kw["run_id"])
    payload = pub._intent_payload(
        run,
        run_id=kw["run_id"],
        workspace_id=kw["workspace_id"],
        project_id=kw["project_id"],
        worker_id=kw["worker_id"],
        fence_token=kw["fence_token"],
        final=final,
        candidate=candidate,
        artifact_sha=pub._sha256_file(candidate),
        expected_sha="",
    )
    payload["candidate_sha256"] = "0" * 64
    intent = pub._publication_intent_path(final)
    tampered = pub._intent_bytes(payload)
    intent.write_bytes(tampered)

    with factory() as session:
        with pytest.raises(pub.PublicationError, match="candidate was tampered"):
            pub.publish_export_run(session, **kw)
        session.rollback()

    print(
        "R4_TAMPERED_INTENT "
        f"final={final.exists()} intent_unchanged={intent.read_bytes() == tampered} "
        f"candidate={candidate.exists()}"
    )
    assert not final.exists()
    assert intent.read_bytes() == tampered
    assert not candidate.exists()


def test_r4_f02_actual_worker_kill_after_final_then_fresh_process(
    env, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """A real publisher child killed post-final converges through a new worker."""
    from app.persistence.jobs import JobRepository
    from app.persistence.s12_export import S12ExportRepository
    from app.services.s12_export.stitch import count_video_frames
    from app.workflow.s12_export_jobs import submit_export_job

    factory, service, manifest_id, _unused_dirs = env
    source = publication_base._real_source(tmp_path, audio=False)
    workdir = tmp_path / "r4-worker-e2e"
    workdir.mkdir()
    dirs = {
        "chunk": str(workdir / "chunks"),
        "scratch": str(workdir / "scratch"),
        "output": str(workdir / "final.mp4"),
    }
    submit_kw = publication_base.base._submit_kwargs(
        factory,
        manifest_id,
        dirs,
        source_path=str(source),
        fps=10.0,
        fps_num=10,
        fps_den=1,
        frame_count=8,
        chunk_config={"overlap": 1, "max_frames": 5},
    )
    run, job, created = submit_export_job(service, **submit_kw)
    assert created is True
    job_id = str(getattr(job, "job_id", ""))
    assert job_id
    db_path = Path(str(factory.kw["bind"].url.database))
    repo_root = Path(__file__).resolve().parents[3]
    marker = workdir / "post-final-boundary.json"
    child_stdout = workdir / "stage1.stdout.log"
    child_stderr = workdir / "stage1.stderr.log"
    child_code = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "root=Path(sys.argv[1]); sys.path.insert(0, str(root))\n"
        "db=Path(sys.argv[2]); marker=Path(sys.argv[3]); managed=Path(sys.argv[4])\n"
        "from app.persistence import create_engine_for_path, create_session_factory\n"
        "from app.services.s12_export import publication as pub\n"
        "from app.workflow.durable_worker import DurableWorker, WorkerConfig\n"
        "from app.workflow.s12_export_jobs import register_s12_export_handler\n"
        "pub._require_ready=lambda session, **kw: None\n"
        "def boundary(final):\n"
        "    marker.write_text(json.dumps({'pid':os.getpid(),'final':str(final),\n"
        "        'final_exists':final.is_file(),'sidecar':pub._sidecar_path(final).exists(),\n"
        "        'receipt':pub._publication_receipt_path(final).exists()}), encoding='utf-8')\n"
        "    while True: time.sleep(0.05)\n"
        "pub._after_publication_final=boundary\n"
        "factory=create_session_factory(create_engine_for_path(db))\n"
        "worker=DurableWorker(factory, config=WorkerConfig(worker_id='worker-r4-a',\n"
        "    lease_ttl=60, heartbeat_interval=0.1, heartbeat_join_timeout=2, staging_root=managed))\n"
        "register_s12_export_handler(worker)\n"
        "worker.run_once()\n"
    )
    with child_stdout.open("wb") as stdout, child_stderr.open("wb") as stderr:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child_code,
                str(repo_root),
                str(db_path),
                str(marker),
                str(service.managed_root),
            ],
            cwd=str(repo_root),
            stdout=stdout,
            stderr=stderr,
        )
        stage1_pid = child.pid
        try:
            deadline = time.monotonic() + 180
            while not marker.is_file() and time.monotonic() < deadline:
                if child.poll() is not None:
                    pytest.fail(
                        f"worker child exited before post-final boundary "
                        f"rc={child.returncode} stderr={child_stderr.read_text(errors='replace')[-3000:]}"
                    )
                time.sleep(0.05)
            assert marker.is_file(), "worker child did not reach post-final boundary"
            boundary = json.loads(marker.read_text(encoding="utf-8"))
            assert boundary["final_exists"] is True
            assert boundary["sidecar"] is False
            assert boundary["receipt"] is False
            assert child.poll() is None
            child.kill()
            child.wait(timeout=15)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=15)
    tasklist = subprocess.run(
        ["tasklist", "/FI", f"PID eq {stage1_pid}", "/NH"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert str(stage1_pid) not in tasklist.stdout

    with factory() as session:
        session.execute(
            text(
                "UPDATE s12_export_lease SET expires_at=acquired_at, "
                "heartbeat_at=acquired_at WHERE run_id=:run_id"
            ),
            {"run_id": run.id},
        )
        session.execute(
            text(
                "UPDATE job_lease SET expires_at=acquired_at, "
                "heartbeat_at=acquired_at WHERE job_id=:job_id"
            ),
            {"job_id": job_id},
        )
        session.commit()
        chunks_before = {
            row.name: (row.read_bytes(), row.stat().st_mtime_ns)
            for row in Path(dirs["chunk"]).glob("chunk_*.mp4")
        }
    assert chunks_before

    fresh_marker = workdir / "fresh-worker.json"
    fresh_stdout = workdir / "stage2.stdout.log"
    fresh_stderr = workdir / "stage2.stderr.log"
    fresh_code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "root=Path(sys.argv[1]); sys.path.insert(0, str(root))\n"
        "db=Path(sys.argv[2]); marker=Path(sys.argv[3]); managed=Path(sys.argv[4])\n"
        "from app.persistence import create_engine_for_path, create_session_factory\n"
        "from app.persistence.jobs import JobRepository\n"
        "from app.persistence.s12_export import S12ExportRepository\n"
        "from app.services.s12_export import publication as pub\n"
        "from app.workflow.durable_worker import DurableWorker, WorkerConfig\n"
        "from app.workflow.job_reconciler import JobReconciler, ReconcileConfig\n"
        "from app.workflow.s12_export_jobs import register_s12_export_handler\n"
        "pub._require_ready=lambda session, **kw: None\n"
        "factory=create_session_factory(create_engine_for_path(db))\n"
        "reconciler=JobReconciler(factory, config=ReconcileConfig(batch_size=5, fence_grace_seconds=0))\n"
        "report=reconciler.reconcile_once()\n"
        "worker=DurableWorker(factory, config=WorkerConfig(worker_id='worker-r4-b',\n"
        "    lease_ttl=60, heartbeat_interval=0.1, heartbeat_join_timeout=2, staging_root=managed))\n"
        "register_s12_export_handler(worker)\n"
        "claimed=worker.run_once()\n"
        "with factory() as s:\n"
        "    jobs=JobRepository(s).list_jobs('ws-s12t03c', limit=1000)\n"
        "    job=next(j for j in jobs if j.idempotency_key.startswith('s12_export_job:'))\n"
        "    run=S12ExportRepository(s).get_run(job.idempotency_key.split(':',1)[1])\n"
        "marker.write_text(json.dumps({'requeued':report.requeued,'claimed':claimed,\n"
        "    'job_id':job.id,'job_state':job.state,'run_id':run.id,'run_status':run.status}), encoding='utf-8')\n"
    )
    with fresh_stdout.open("wb") as stdout, fresh_stderr.open("wb") as stderr:
        fresh = subprocess.run(
            [
                sys.executable,
                "-c",
                fresh_code,
                str(repo_root),
                str(db_path),
                str(fresh_marker),
                str(service.managed_root),
            ],
            cwd=str(repo_root),
            stdout=stdout,
            stderr=stderr,
            timeout=240,
        )
    assert fresh.returncode == 0, fresh_stderr.read_text(errors="replace")[-3000:]
    result = json.loads(fresh_marker.read_text(encoding="utf-8"))
    final = Path(dirs["output"])
    with factory() as session:
        stored_job = JobRepository(session).get_job(job_id)
        stored_run = S12ExportRepository(session).get_run(run.id)
    chunks_after = {
        row.name: (row.read_bytes(), row.stat().st_mtime_ns)
        for row in Path(dirs["chunk"]).glob("chunk_*.mp4")
    }
    print(
        "R4_F02_WORKER_KILL "
        + json.dumps(
            {
                "killed_pid": stage1_pid,
                "requeued": result["requeued"],
                "claimed": result["claimed"],
                "job_state": result["job_state"],
                "run_status": result["run_status"],
                "final": str(final),
                "final_sha256": pub._sha256_file(final),
                "intent": pub._publication_intent_path(final).exists(),
                "chunk_count": len(chunks_after),
                "stage1_stdout": str(child_stdout),
                "stage1_stderr": str(child_stderr),
                "stage2_stdout": str(fresh_stdout),
                "stage2_stderr": str(fresh_stderr),
            },
            sort_keys=True,
        )
    )
    assert result["requeued"] == 1
    assert result["claimed"] == 1
    assert result["job_id"] == job_id
    assert result["job_state"] == "completed"
    assert result["run_id"] == run.id
    assert result["run_status"] == "completed"
    assert stored_job.state == "completed"
    assert stored_run.status == "completed"
    assert final.is_file()
    assert count_video_frames(final) == 8
    assert pub._sidecar_path(final).is_file()
    assert pub._publication_receipt_path(final).is_file()
    assert not pub._publication_intent_path(final).exists()
    assert chunks_after == chunks_before

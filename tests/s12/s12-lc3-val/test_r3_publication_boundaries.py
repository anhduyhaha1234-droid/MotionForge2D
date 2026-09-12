"""S12-LC3-R3 S01/S02/S04 publication boundary regressions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

TEST03C = Path(__file__).resolve().parents[1] / "s12-t03c"

sys.path.insert(0, str(TEST03C))
import test_publication as publication_base  # noqa: E402

from app.services.s12_export import publication as pub  # noqa: E402

env = publication_base.env


def test_r3_s01_pre_receipt_recovery_requires_matching_private_attempt(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A real interrupted publisher recovers from its durable attempt intent."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    db = Path(kw["manifest"]["scratch_dir"]).parent / "t03c-pub.db"
    monkeypatch.setattr(pub, "_cleanup_publication_scratch", lambda *a, **k: None)
    child_script = r"""
import json
import sys
from types import SimpleNamespace

from app.persistence import create_engine_for_path, create_session_factory
from app.services.s12_export import publication as pub
from app.services.s12_export import validation

payload = json.loads(sys.argv[1])
factory = create_session_factory(create_engine_for_path(payload["db"]))
pub._require_ready = lambda session, **kwargs: None
pub._cleanup_publication_scratch = lambda *args, **kwargs: None
validation.validate = lambda path, expectation: SimpleNamespace(
    verdict="PASS",
    probes=tuple(
        SimpleNamespace(name=name, verdict="PASS", detail="test pass")
        for name in ("frame_count", "frame_order", "av_policy", "provenance")
    ),
)
if payload["phase"] == "interrupt":
    def interrupt_after_final(final):
        intent_path = pub._publication_intent_path(final)
        intent = pub._read_publication_intent(final)
        assert intent_path.is_file() and intent is not None
        assert intent["run_id"] == payload["kwargs"]["run_id"]
        assert intent["fence_token"] == payload["kwargs"]["fence_token"]
        print("DURABLE_ATTEMPT_PROOF", intent["attempt"], intent["candidate_sha256"], flush=True)
        raise SystemExit(86)
    pub._after_publication_final = interrupt_after_final
with factory() as session:
    result = pub.publish_export_run(session, **payload["kwargs"])
    session.commit()
    print("RECOVERY_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
"""
    payload = {"db": str(db), "kwargs": kw, "phase": "interrupt"}
    interrupted = subprocess.run(
        [sys.executable, "-c", child_script, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(
        "R3_S01_INTERRUPTED_PUBLISHER "
        f"exit={interrupted.returncode} stdout={interrupted.stdout.strip()} "
        f"stderr={interrupted.stderr[-500:].strip()}"
    )
    assert interrupted.returncode == 86, interrupted.stderr
    assert "DURABLE_ATTEMPT_PROOF" in interrupted.stdout
    intent_path = pub._publication_intent_path(final)
    receipt = pub._publication_receipt_path(final)
    assert intent_path.is_file()
    assert not pub._sidecar_path(final).exists()
    assert not receipt.exists()
    final_sha = pub._sha256_file(final)
    assert final_sha == pub._sha256_file(candidate)
    assert not os.path.samefile(candidate, final)

    payload["phase"] = "recover"
    recovered = subprocess.run(
        [sys.executable, "-c", child_script, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(
        "R3_S01_FRESH_PROCESS_RECOVERY "
        f"exit={recovered.returncode} stdout={recovered.stdout.strip()} "
        f"stderr={recovered.stderr[-500:].strip()}"
    )
    assert recovered.returncode == 0, recovered.stderr
    result_line = next(
        line for line in recovered.stdout.splitlines() if line.startswith("RECOVERY_RESULT=")
    )
    result = json.loads(result_line.partition("=")[2])
    receipt = pub._publication_receipt_path(final)
    print(
        "R3_S01_PRE_RECEIPT "
        f"status={result['status']} recovered={result.get('recovered')} "
        f"final_sha256={pub._sha256_file(final)} receipt={receipt.is_file()} "
        f"candidate={candidate.is_file()} samefile={os.path.samefile(candidate, final)}"
    )
    assert result["status"] == "completed"
    assert result["recovered"] is True
    assert receipt.is_file()
    assert pub._sha256_file(final) == final_sha
    assert candidate.is_file()
    assert not os.path.samefile(candidate, final)
    assert not intent_path.exists()
    with factory() as session:
        assert publication_base.S12ExportRepository(session).get_run(kw["run_id"]).status == "completed"


def test_r3_s01_unowned_same_byte_pair_is_not_recovered_or_mutated(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Equal final/candidate/sidecar bytes without intent or receipt prove no ownership."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    payload = b"synthetic unowned same-byte final"
    candidate.write_bytes(payload)
    shutil.copyfile(candidate, final)
    sidecar = pub._sidecar_path(final)
    sidecar.write_text(f"{pub._sha256_file(final)}\n", encoding="ascii")
    receipt = pub._publication_receipt_path(final)
    intent = pub._publication_intent_path(final)
    monkeypatch.setattr(pub, "_cleanup_publication_scratch", lambda *a, **k: None)
    final_identity = (final.stat().st_dev, final.stat().st_ino)
    sidecar_identity = (sidecar.stat().st_dev, sidecar.stat().st_ino)
    final_bytes = final.read_bytes()
    sidecar_bytes = sidecar.read_bytes()

    with factory() as session:
        before = publication_base.S12ExportRepository(session).get_run(kw["run_id"])
        assert before.status == "running"
        with pytest.raises(pub.PublicationError):
            pub.publish_export_run(session, **kw)
        session.rollback()
    with factory() as session:
        after = publication_base.S12ExportRepository(session).get_run(kw["run_id"])
        assert after.status == before.status
    print(
        "R3_S01_UNOWNED_PAIR "
        f"status={after.status} final_sha256={pub._sha256_file(final)} "
        f"sidecar_sha256={sidecar_bytes.decode('ascii').strip()} "
        f"receipt={receipt.exists()} intent={intent.exists()}"
    )
    assert final.read_bytes() == final_bytes
    assert sidecar.read_bytes() == sidecar_bytes
    assert (final.stat().st_dev, final.stat().st_ino) == final_identity
    assert (sidecar.stat().st_dev, sidecar.stat().st_ino) == sidecar_identity
    assert not receipt.exists()
    assert not intent.exists()


def test_r3_s02_private_candidate_and_public_final_are_distinct_inodes(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Exclusive publication must not expose the private candidate inode."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"distinct publication inode")
    monkeypatch.setattr(pub, "_cleanup_publication_scratch", lambda *a, **k: None)

    with factory() as session:
        result = pub.publish_export_run(session, **kw)
        session.commit()

    print(
        "R3_S02_INODE "
        f"status={result['status']} candidate={candidate} final={final} "
        f"samefile={os.path.samefile(candidate, final)}"
    )
    assert result["status"] == "completed"
    assert candidate.is_file()
    assert final.is_file()
    assert not os.path.samefile(candidate, final)


def test_r3_s04_overlong_companion_name_fails_before_public_mutation(
    env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """An unaddressable Windows companion name is typed before final creation."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = tmp_path / f"{'x' * 250}.mp4"
    kw["manifest"]["output_path"] = str(final)
    with factory() as session:
        with pytest.raises(pub.PublicationPathError) as exc_info:
            pub.publish_export_run(session, **kw)
        session.rollback()

    print(
        "R3_S04_PATH "
        f"code={getattr(exc_info.value, 'code', None)} final={final.exists()} "
        f"sidecar={pub._sidecar_path(final).exists()}"
    )
    assert exc_info.value.code == "S12_T03C_PUBLICATION_PATH_INVALID"
    assert not final.exists()
    assert not pub._sidecar_path(final).exists()
    assert not pub._publication_receipt_path(final).exists()


def test_r3_s04_space_unicode_companions_remain_addressable(
    env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """Ordinary deep/space/Unicode names are valid when preflight can address them."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    output_dir = tmp_path / "deep path" / "字幕 測試"
    output_dir.mkdir(parents=True)
    final = output_dir / "résultat final.mp4"
    kw["manifest"]["output_path"] = str(final)
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"space unicode publication")

    with factory() as session:
        result = pub.publish_export_run(session, **kw)
        session.commit()

    assert result["status"] == "completed"
    assert final.is_file()
    assert pub._sidecar_path(final).is_file()
    assert pub._publication_receipt_path(final).is_file()


def test_r3_s05_actual_worker_child_kill_then_fresh_worker_converges(
    env, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    """Kill a real DurableWorker at publication, then recover the same Job."""
    from app.persistence.jobs import JobRepository
    from app.persistence.s12_export import S12ExportRepository
    from app.services.s12_export.stitch import count_video_frames
    from app.workflow.s12_export_jobs import submit_export_job

    factory, service, manifest_id, _unused_dirs = env
    source = publication_base._real_source(tmp_path, audio=False)
    workdir = tmp_path / "worker-e2e"
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
    marker = workdir / "publication-boundary.json"
    fresh_marker = workdir / "fresh-worker.json"
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
        "def barrier(candidate, final):\n"
        "    marker.write_text(json.dumps({'pid':os.getpid(),'boundary':'before-publication-primitive',\n"
        "        'candidate':str(candidate),'candidate_exists':candidate.is_file(),\n"
        "        'final':str(final),'final_exists':final.exists()}), encoding='utf-8')\n"
        "    while True: time.sleep(0.05)\n"
        "pub._before_publication_primitive=barrier\n"
        "factory=create_session_factory(create_engine_for_path(db))\n"
        "worker=DurableWorker(factory, config=WorkerConfig(worker_id='worker-r3-a',\n"
        "    lease_ttl=60, heartbeat_interval=0.1, heartbeat_join_timeout=2, staging_root=managed))\n"
        "register_s12_export_handler(worker)\n"
        "worker.run_once()\n"
    )
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stage1_pid = child.pid
    try:
        deadline = time.monotonic() + 180
        while not marker.is_file() and time.monotonic() < deadline:
            if child.poll() is not None:
                pytest.fail(f"worker child exited before publication barrier rc={child.returncode}")
            time.sleep(0.05)
        assert marker.is_file(), "actual worker child did not reach publication barrier"
        boundary = json.loads(marker.read_text(encoding="utf-8"))
        assert boundary["boundary"] == "before-publication-primitive"
        assert boundary["candidate_exists"] is True
        assert boundary["final_exists"] is False
        assert child.poll() is None
        child.kill()
        child.wait(timeout=15)
        tasklist = subprocess.run(
            ["tasklist", "/FI", f"PID eq {stage1_pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert str(stage1_pid) not in tasklist.stdout
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)

    with factory() as session:
        from sqlalchemy import text

        session.execute(
            text(
                "UPDATE s12_export_lease SET expires_at=acquired_at, heartbeat_at=acquired_at "
                "WHERE run_id=:run_id"
            ),
            {"run_id": run.id},
        )
        session.execute(
            text(
                "UPDATE job_lease SET expires_at=acquired_at, heartbeat_at=acquired_at "
                "WHERE job_id=:job_id"
            ),
            {"job_id": job_id},
        )
        session.commit()
        chunks_before = {
            row.name: (row.read_bytes(), row.stat().st_mtime_ns)
            for row in Path(dirs["chunk"]).glob("chunk_*.mp4")
        }
    assert chunks_before

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
        "worker=DurableWorker(factory, config=WorkerConfig(worker_id='worker-r3-b',\n"
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
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert fresh.returncode == 0, fresh.stderr[-3000:]
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
        "R3_S05_WORKER_E2E "
        + json.dumps(
            {
                "killed_pid": stage1_pid,
                "requeued": result["requeued"],
                "claimed": result["claimed"],
                "job_id": result["job_id"],
                "job_state": result["job_state"],
                "run_status": result["run_status"],
                "final": str(final),
                "final_sha256": pub._sha256_file(final),
                "chunk_count": len(chunks_after),
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
    assert chunks_after == chunks_before

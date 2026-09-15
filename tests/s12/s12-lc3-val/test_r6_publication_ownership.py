"""S12-LC3-VAL R6 — publication ownership proof + serialization (F02/F03).

Frozen node map (R6_ACCEPTANCE V01-V15):

- V01 ``test_v01_owned_publication_and_completed_replay``
- V02 ``test_v02_foreign_final_before_intent_denied[bytes_variant=matching|different]``
- V03 ``test_v03_external_matching_copy_after_intent_denied[with_sidecar=False|True]``
- V04 ``test_v04_interruption_before_link_loss_handler_denied``
- V05 ``test_v05_foreign_or_malformed_proof_denied[case=intent_crossrun|receipt_crossrun]``
- V06 ``test_v06_own_crash_window_recovers[window=pre_final|post_final_pre_sidecar|post_sidecar_pre_receipt|receipt_precommit]``
- V07 ``test_v07_commit_failure_and_lost_ack_converge[case=commit_failure|lost_ack]``
- V08 ``test_v08_real_publisher_child_kill_post_final_fresh_process_converges``
- V09 ``test_v09_handoff_release_b_first_b_is_sole_publisher``
- V10 ``test_v10_handoff_release_a_first_stale_a_never_publishes``
- V11 ``test_v11_equal_bytes_ownership_independent_of_sha[schedule=b_first|a_first]``
- V12 ``test_v12_interruption_between_companions_stale_cleanup_cannot_corrupt``
- V13 ``test_v13_private_candidate_rebuild_cannot_mutate_public``
- V14 ``test_v14_supported_paths_full_publisher_completes[case=short|spaces_unicode|deep|basename155|export_master]``
    + ``test_v14_unsupported_path_typed_denial_zero_public_bytes``
- V15 ``test_v15_interrupted_temp_and_foreign_companion_preserved``

Ownership proof is inode identity (volume + file index), never byte
equality; the public mutation is serialized by a real OS publication
lock.  Validator/readiness stubs are declared engineering fixtures; the
full real-media DurableWorker variant is the retained R4 lane node
``test_r4_f02_actual_worker_kill_after_final_then_fresh_process``.

Evidence: when ``S12_R6_VAL_OUT`` is set, each test writes one JSON
record (exclusive create, unique suffix) into that directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

TEST03C = Path(__file__).resolve().parents[1] / "s12-t03c"
sys.path.insert(0, str(TEST03C))
import test_publication as publication_base  # noqa: E402

from app.persistence.s12_export import S12ExportRepository  # noqa: E402
from app.services.s12_export import publication as pub  # noqa: E402

env = publication_base.env

_WS = publication_base.WS


def _record(name: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, default=str, sort_keys=True)
    print(f"R6_VAL {name} {payload[:1800]}")
    out_dir = os.environ.get("S12_R6_VAL_OUT")
    if not out_dir:
        return
    target = Path(out_dir) / f"{name}.{os.getpid()}.{int(time.time() * 1000)}.json"
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, default=str))


def _rows(factory: Any) -> dict[str, list[dict[str, Any]]]:
    with factory() as session:
        return {
            name: [
                dict(row)
                for row in session.execute(
                    publication_base.text(
                        "SELECT * FROM " + name + " ORDER BY "
                        + ("run_id" if name == "s12_export_lease" else "id")
                    )
                ).mappings()
            ]
            for name in ("s12_export_run", "job", "s12_export_lease")
        }


def _file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "sha256": pub._sha256_file(path),
        "size": stat.st_size,
        "dev": stat.st_dev,
        "ino": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
    }


def _files(final: Path) -> dict[str, Any]:
    return {
        str(path): _file_state(path)
        for path in (
            final,
            pub._sidecar_path(final),
            pub._publication_receipt_path(final),
            pub._publication_intent_path(final),
        )
    }


def _call(factory: Any, kw: dict[str, Any]) -> dict[str, Any]:
    with factory() as session:
        try:
            outcome = pub.publish_export_run(session, **kw)
            session.commit()
            return {"outcome": outcome, "error": None}
        except BaseException as exc:  # noqa: BLE001 - both outcomes recorded
            session.rollback()
            return {
                "outcome": None,
                "error": {
                    "type": type(exc).__name__,
                    "detail": str(exc),
                    "code": getattr(exc, "code", None),
                },
            }


def _expire_lease(factory: Any, run_id: str) -> None:
    with factory() as session:
        session.execute(
            publication_base.text(
                "UPDATE s12_export_lease SET expires_at=acquired_at, "
                "heartbeat_at=acquired_at WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        )
        session.commit()


def _fresh_owner(factory: Any, kw: dict[str, Any], worker: str = "worker-r6-b") -> dict[str, Any]:
    _expire_lease(factory, kw["run_id"])
    with factory() as session:
        lease = S12ExportRepository(session).claim_run(kw["run_id"], worker)
        session.commit()
    return {**kw, "worker_id": worker, "fence_token": lease.fence_token}


def _run_status(factory: Any, run_id: str) -> str:
    with factory() as session:
        return str(S12ExportRepository(session).get_run(run_id).status)


def _owner_manifest(kw: dict[str, Any], scratch: Path) -> dict[str, Any]:
    scratch.mkdir(parents=True, exist_ok=True)
    manifest = dict(kw["manifest"])
    manifest["scratch_dir"] = str(scratch)
    manifest["candidate_path"] = str(scratch / "candidate_final.mp4")
    return manifest


# ---------------------------------------------------------------------------
# V01 - V05: adoption / denial
# ---------------------------------------------------------------------------


def test_v01_owned_publication_and_completed_replay(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Owned publication completes once; replay is byte-verified zero-delta."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    with factory() as session:
        out = pub.publish_export_run(session, **kw)
        session.commit()
    first_files, first_rows = _files(final), _rows(factory)
    with factory() as session:
        replay = pub.publish_export_run(session, **kw)
        session.commit()
    second_files, second_rows = _files(final), _rows(factory)
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    _record(
        "v01",
        {
            "status": out["status"],
            "reused": replay.get("reused"),
            "files": first_files,
            "identity_match": pub._identity_matches(final, receipt.get("artifact_identity")),
        },
    )
    assert out["status"] == "completed"
    assert replay["reused"] is True
    assert replay["artifact_sha256"] == out["artifact_sha256"]
    assert first_files == second_files
    assert first_rows == second_rows
    assert len(first_rows["s12_export_run"]) == 1
    assert len(first_rows["job"]) == 1
    assert pub._identity_matches(final, receipt["artifact_identity"])
    assert not pub._publication_intent_path(final).exists()
    assert not (Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4").exists()


@pytest.mark.parametrize("bytes_variant", ["matching", "different"])
def test_v02_foreign_final_before_intent_denied(
    env, monkeypatch: pytest.MonkeyPatch, bytes_variant: str
) -> None:  # type: ignore[no-untyped-def]
    """A foreign final without any intent is never adopted (byte control)."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    payload = (
        candidate.read_bytes() if bytes_variant == "matching" else b"different foreign bytes"
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(payload)
    before_rows, before_files = _rows(factory), _files(final)
    result = _call(factory, kw)
    after_rows, after_files = _rows(factory), _files(final)
    _record(
        "v02",
        {
            "bytes_variant": bytes_variant,
            "error": result["error"],
            "rows_equal": before_rows == after_rows,
            "files_equal": before_files == after_files,
        },
    )
    assert result["error"] is not None
    assert "refusing overwrite" in result["error"]["detail"]
    assert final.read_bytes() == payload
    assert before_rows == after_rows
    assert before_files == after_files
    assert not pub._publication_receipt_path(final).exists()
    assert not pub._publication_intent_path(final).exists()


@pytest.mark.parametrize("with_sidecar", [False, True])
def test_v03_external_matching_copy_after_intent_denied(
    env, monkeypatch: pytest.MonkeyPatch, with_sidecar: bool
) -> None:  # type: ignore[no-untyped-def]
    """A foreign copy arriving after a genuine intent is never adopted."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    arrivals: list[dict[str, Any]] = []

    def foreign_arrival(candidate: Path, destination: Path) -> None:
        assert pub._publication_intent_path(destination).is_file()
        shutil.copyfile(candidate, destination)
        assert not os.path.samefile(candidate, destination)
        if with_sidecar:
            pub._sidecar_path(destination).write_text(
                pub._sha256_file(destination) + "\n", encoding="ascii"
            )
        arrivals.append(_files(destination))

    monkeypatch.setattr(pub, "_before_publication_primitive", foreign_arrival)
    first = _call(factory, kw)
    assert len(arrivals) == 1
    assert first["error"] is not None
    assert first["error"]["type"] == "PublicationRaceLost"
    assert pub._publication_intent_path(final).is_file()
    before_rows, before_files = _rows(factory), _files(final)
    monkeypatch.setattr(pub, "_before_publication_primitive", lambda *_: None)
    second = _call(factory, kw)
    after_rows, after_files = _rows(factory), _files(final)
    _record(
        "v03",
        {
            "with_sidecar": with_sidecar,
            "first_error": first["error"]["type"],
            "second_error": second["error"],
            "rows_equal": before_rows == after_rows,
            "files_equal": before_files == after_files,
            "foreign_files": before_files,
        },
    )
    assert second["error"] is not None
    assert "refusing overwrite" in second["error"]["detail"]
    assert before_rows == after_rows
    assert before_files == after_files
    assert not pub._publication_receipt_path(final).exists()
    assert _run_status(factory, kw["run_id"]) == "running"


def test_v04_interruption_before_link_loss_handler_denied(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Crash with the foreign copy in place, before any handler cleanup."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])

    def foreign_arrival(candidate: Path, destination: Path) -> None:
        shutil.copyfile(candidate, destination)
        raise RuntimeError("R6_V04_INTERRUPT_BEFORE_HANDLER")

    monkeypatch.setattr(pub, "_before_publication_primitive", foreign_arrival)
    with factory() as session:
        with pytest.raises(RuntimeError, match="R6_V04_INTERRUPT_BEFORE_HANDLER"):
            pub.publish_export_run(session, **kw)
        session.rollback()
    assert pub._publication_intent_path(final).is_file()
    foreign_files, foreign_rows = _files(final), _rows(factory)
    monkeypatch.setattr(pub, "_before_publication_primitive", lambda *_: None)
    second = _call(factory, kw)
    _record(
        "v04",
        {
            "second_error": second["error"],
            "rows_equal": foreign_rows == _rows(factory),
            "files_equal": foreign_files == _files(final),
        },
    )
    assert second["error"] is not None
    assert _rows(factory) == foreign_rows
    assert _files(final) == foreign_files
    assert not pub._publication_receipt_path(final).exists()
    assert _run_status(factory, kw["run_id"]) == "running"


@pytest.mark.parametrize("case", ["intent_crossrun", "receipt_crossrun"])
def test_v05_foreign_or_malformed_proof_denied(
    env, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:  # type: ignore[no-untyped-def]
    """Foreign intent/receipt identity is a typed denial with zero mutation."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"v05 proof control")
    if case == "intent_crossrun":
        intent = pub._publication_intent_path(final)
        foreign = b'{"kind":"s12-publication-intent","run_id":"cross-run-foreign"}\n'
        intent.write_bytes(foreign)
        result = _call(factory, kw)
        _record("v05_intent", {"error": result["error"]})
        assert result["error"] is not None
        assert "identity mismatch" in result["error"]["detail"]
        assert intent.read_bytes() == foreign
        assert not final.exists()
    else:
        final.write_bytes(b"foreign existing output (cross-run receipt)")
        pub._write_sidecar(final, pub._sha256_file(final))
        receipt = pub._publication_receipt_path(final)
        receipt.write_bytes(json.dumps({"version": 1, "run_id": "cross-run-foreign"}).encode())
        before = (_files(final), _rows(factory))
        result = _call(factory, kw)
        _record("v05_receipt", {"error": result["error"]})
        assert result["error"] is not None
        assert "refusing overwrite" in result["error"]["detail"]
        assert (_files(final), _rows(factory)) == before
        assert _run_status(factory, kw["run_id"]) == "running"


# ---------------------------------------------------------------------------
# V06 - V07: genuine interrupted recovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "window",
    ["pre_final", "post_final_pre_sidecar", "post_sidecar_pre_receipt", "receipt_precommit"],
)
def test_v06_own_crash_window_recovers(
    env, monkeypatch: pytest.MonkeyPatch, window: str
) -> None:  # type: ignore[no-untyped-def]
    """Own crash windows converge to the exact pair (1 Run / 1 Job)."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"v06 owned crash window bytes")
    crash_sha = pub._sha256_file(candidate)

    if window == "pre_final":

        def crash(candidate_path: Path, destination: Path) -> None:
            raise RuntimeError("R6_V06_pre_final")

        monkeypatch.setattr(pub, "_before_publication_primitive", crash)
        with factory() as session:
            with pytest.raises(RuntimeError, match="R6_V06_pre_final"):
                pub.publish_export_run(session, **kw)
            session.rollback()
        assert not final.exists()
        assert pub._publication_intent_path(final).is_file()
        monkeypatch.setattr(pub, "_before_publication_primitive", lambda *_: None)
        fresh_kw = _fresh_owner(factory, kw)
        with factory() as session:
            out = pub.publish_export_run(session, **fresh_kw)
            session.commit()
        recovered = None
        expected_status = "completed"
    elif window == "post_final_pre_sidecar":

        def stop(final_path: Path) -> None:
            raise RuntimeError("R6_V06_post_final")

        monkeypatch.setattr(pub, "_after_publication_final", stop)
        with factory() as session:
            with pytest.raises(RuntimeError, match="R6_V06_post_final"):
                pub.publish_export_run(session, **kw)
            session.rollback()
        assert final.is_file()
        assert not pub._sidecar_path(final).exists()
        monkeypatch.setattr(pub, "_after_publication_final", lambda final_path: None)
        fresh_kw = _fresh_owner(factory, kw)
        with factory() as session:
            out = pub.publish_export_run(session, **fresh_kw)
            session.commit()
        recovered, expected_status = out.get("recovered"), "completed"
    elif window == "post_sidecar_pre_receipt":
        original_receipt_writer = pub._write_publication_receipt

        def crash_receipt(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("R6_V06_post_sidecar")

        monkeypatch.setattr(pub, "_write_publication_receipt", crash_receipt)
        with factory() as session:
            with pytest.raises(RuntimeError, match="R6_V06_post_sidecar"):
                pub.publish_export_run(session, **kw)
            session.rollback()
        assert final.is_file()
        assert pub._sidecar_path(final).is_file()
        assert not pub._publication_receipt_path(final).exists()
        monkeypatch.setattr(pub, "_write_publication_receipt", original_receipt_writer)
        fresh_kw = _fresh_owner(factory, kw)
        with factory() as session:
            out = pub.publish_export_run(session, **fresh_kw)
            session.commit()
        recovered, expected_status = out.get("recovered"), "completed"
    else:
        with factory() as session:
            original_commit = session.commit
            calls = {"n": 0}

            def fail_commit() -> None:
                calls["n"] += 1
                raise RuntimeError("R6_V06_precommit")

            monkeypatch.setattr(session, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="R6_V06_precommit"):
                pub.publish_export_run(session, **kw)
            assert calls["n"] >= 1
            session.rollback()
            _ = original_commit
        assert final.is_file()
        assert pub._sidecar_path(final).is_file()
        assert pub._publication_receipt_path(final).is_file()
        fresh_kw = _fresh_owner(factory, kw)
        with factory() as session:
            out = pub.publish_export_run(session, **fresh_kw)
            session.commit()
        recovered, expected_status = out.get("recovered"), "completed"

    rows = _rows(factory)
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    _record(
        "v06",
        {
            "window": window,
            "status": out["status"],
            "recovered": recovered,
            "runs": len(rows["s12_export_run"]),
            "jobs": len(rows["job"]),
            "final": _file_state(final),
        },
    )
    assert out["status"] == expected_status
    if window != "pre_final":
        assert recovered is True
    assert len(rows["s12_export_run"]) == 1
    assert len(rows["job"]) == 1
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    assert pub._sha256_file(final) == crash_sha
    assert not pub._publication_intent_path(final).exists()


@pytest.mark.parametrize("case", ["commit_failure", "lost_ack"])
def test_v07_commit_failure_and_lost_ack_converge(
    env, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:  # type: ignore[no-untyped-def]
    """Commit faults keep the artifact recoverable; lost ack replays bytes."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    if case == "commit_failure":
        with factory() as session:

            def fail_commit() -> None:
                raise RuntimeError("R6_V07 injected database commit failure")

            monkeypatch.setattr(session, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="R6_V07"):
                pub.publish_export_run(session, **kw)
            session.rollback()
        sha_before, mtime_before = pub._sha256_file(final), final.stat().st_mtime_ns
        fresh_kw = _fresh_owner(factory, kw)
        with factory() as session:
            out = pub.publish_export_run(session, **fresh_kw)
            session.commit()
        _record(
            "v07",
            {"case": case, "recovered": out.get("recovered"), "status": out["status"]},
        )
        assert out.get("recovered") is True
        assert out["status"] == "completed"
        assert pub._sha256_file(final) == sha_before
        assert final.stat().st_mtime_ns == mtime_before
    else:
        with factory() as session:
            original_commit = session.commit

            def commit_then_lose_ack() -> None:
                original_commit()
                raise RuntimeError("R6_V07 database commit acknowledgement lost")

            monkeypatch.setattr(session, "commit", commit_then_lose_ack)
            with pytest.raises(RuntimeError, match="R6_V07"):
                pub.publish_export_run(session, **kw)
            session.rollback()
        assert _run_status(factory, kw["run_id"]) == "completed"
        with factory() as session:
            replay = pub.publish_export_run(session, **kw)
            session.rollback()
        _record("v07", {"case": case, "reused": replay.get("reused")})
        assert replay["reused"] is True


# ---------------------------------------------------------------------------
# V08: real process kill / fresh process convergence
# ---------------------------------------------------------------------------


def test_v08_real_publisher_child_kill_post_final_fresh_process_converges(
    env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Kill a real publisher process post-final; a fresh process converges.

    The heavy real-media DurableWorker variant of this window is the
    retained R4 lane node
    ``test_r4_f02_actual_worker_kill_after_final_then_fresh_process``,
    executed in the same gate run.
    """
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"v08 real child killed post-final")
    db_path = Path(str(factory.kw["bind"].url.database))
    repo_root = Path(__file__).resolve().parents[3]
    workdir = tmp_path / "r6-v08"
    workdir.mkdir()
    marker = workdir / "post-final.json"
    kw_file = workdir / "kw.json"
    child_kw = dict(kw)
    kw_file.write_text(json.dumps({"db": str(db_path), "kw": child_kw}), encoding="utf-8")
    child_code = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path(sys.argv[1]).read_text())\n"
        "marker = Path(sys.argv[2])\n"
        "sys.path.insert(0, sys.argv[3])\n"
        "from types import SimpleNamespace\n"
        "from app.persistence import create_engine_for_path, create_session_factory\n"
        "from app.services.s12_export import publication as pub\n"
        "from app.services.s12_export import validation\n"
        "pub._require_ready = lambda session, **kw: None\n"
        "validation.validate = lambda path, expectation: SimpleNamespace(\n"
        "    verdict='PASS', probes=(SimpleNamespace(name='frame_count', verdict='PASS', detail='stub'),))\n"
        "def boundary(final_path):\n"
        "    stat = final_path.stat()\n"
        "    marker.write_text(json.dumps({'pid': os.getpid(), 'dev': stat.st_dev,\n"
        "        'ino': stat.st_ino, 'sha256': pub._sha256_file(final_path)}), encoding='utf-8')\n"
        "    while True: time.sleep(0.05)\n"
        "import time\n"
        "pub._after_publication_final = boundary\n"
        "factory = create_session_factory(create_engine_for_path(Path(payload['db'])))\n"
        "pub._require_ready = lambda session, **kw: None\n"
        "validation.validate = lambda path, expectation: SimpleNamespace(\n"
        "    verdict='PASS', probes=(SimpleNamespace(name='frame_count', verdict='PASS', detail='stub'),))\n"
        "with factory() as session:\n"
        "    pub.publish_export_run(session, **payload['kw'])\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(kw_file), str(marker), str(repo_root)],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stage1_pid = child.pid
    try:
        deadline = time.monotonic() + 120
        while not marker.is_file() and time.monotonic() < deadline:
            if child.poll() is not None:
                pytest.fail(
                    f"publisher child exited before post-final boundary rc={child.returncode} "
                    f"stderr={(child.stderr.read() if child.stderr else '')[-1500:]}"
                )
            time.sleep(0.05)
        assert marker.is_file(), "real publisher child did not reach post-final boundary"
        boundary_state = json.loads(marker.read_text(encoding="utf-8"))
        assert final.is_file()
        assert boundary_state["sha256"] == pub._sha256_file(final)
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
    fresh_kw = _fresh_owner(factory, kw)
    with factory() as session:
        out = pub.publish_export_run(session, **fresh_kw)
        session.commit()
    rows = _rows(factory)
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    _record(
        "v08",
        {
            "killed_pid": stage1_pid,
            "recovered": out.get("recovered"),
            "status": out["status"],
            "final": _file_state(final),
            "runs": len(rows["s12_export_run"]),
            "jobs": len(rows["job"]),
        },
    )
    assert out.get("recovered") is True
    assert out["status"] == "completed"
    assert len(rows["s12_export_run"]) == 1
    assert len(rows["job"]) == 1
    assert final.stat().st_dev == boundary_state["dev"]
    assert final.stat().st_ino == boundary_state["ino"]
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    assert pub._sha256_file(final) == boundary_state["sha256"]


# ---------------------------------------------------------------------------
# V09 - V11: real lease handoff at the contested public primitive
# ---------------------------------------------------------------------------


def _run_handoff(
    factory: Any,
    kw: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    release_first: str,
    payloads: dict[str, bytes],
) -> dict[str, Any]:
    root = Path(kw["manifest"]["scratch_dir"]).parent
    final = Path(kw["manifest"]["output_path"])
    candidates: dict[str, Path] = {}
    manifests: dict[str, dict[str, Any]] = {}
    for owner in ("A", "B"):
        scratch = root / f"owner-{owner}"
        scratch.mkdir(parents=True, exist_ok=True)
        candidates[owner] = scratch / "candidate_final.mp4"
        candidates[owner].write_bytes(payloads[owner])
        manifests[owner] = _owner_manifest(kw, scratch)
    ready = {owner: threading.Event() for owner in ("A", "B")}
    release = {owner: threading.Event() for owner in ("A", "B")}
    timeline: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    original_primitive = pub._publish_candidate_exclusive

    def seam(source: Path, destination: Path) -> None:
        owner = next(k for k, v in candidates.items() if v == Path(source))
        timeline.append(
            {
                "event": "at-real-seam",
                "owner": owner,
                "pid": os.getpid(),
                "thread": threading.get_ident(),
                "utc": datetime.now(UTC).isoformat(),
            }
        )
        ready[owner].set()
        assert release[owner].wait(20), owner + " was never released"

    def primitive(source: Path, destination: Path) -> Any:
        owner = next(k for k, v in candidates.items() if v == Path(source))
        timeline.append({"event": "exclusive-attempt", "owner": owner})
        result = original_primitive(source, destination)
        timeline.append({"event": "exclusive-success", "owner": owner})
        return result

    monkeypatch.setattr(pub, "_before_publication_primitive", seam)
    monkeypatch.setattr(pub, "_publish_candidate_exclusive", primitive)
    owner_kw: dict[str, dict[str, Any]] = {"A": dict(kw, manifest=manifests["A"])}
    threads: dict[str, threading.Thread] = {}

    def start(owner: str, owner_kwargs: dict[str, Any]) -> None:
        thread = threading.Thread(
            target=lambda: results.update({owner: _call(factory, owner_kwargs)}),
            name=f"r6-owner-{owner}",
        )
        threads[owner] = thread
        thread.start()

    baseline_rows = _rows(factory)
    try:
        start("A", owner_kw["A"])
        assert ready["A"].wait(10), "A never reached the contested operation"
        _expire_lease(factory, kw["run_id"])
        with factory() as session:
            lease_b = S12ExportRepository(session).claim_run(kw["run_id"], "worker-r6-B")
            session.commit()
        owner_kw["B"] = dict(
            kw,
            worker_id="worker-r6-B",
            fence_token=lease_b.fence_token,
            manifest=manifests["B"],
        )
        start("B", owner_kw["B"])
        assert ready["B"].wait(10), "B never reached the contested operation"
        both_paused_rows = _rows(factory)
        both_paused_files = _files(final)
        assert not final.exists()
        release[release_first].set()
        threads[release_first].join(20)
        assert not threads[release_first].is_alive()
        first_files = _files(final)
        other = "A" if release_first == "B" else "B"
        release[other].set()
        threads[other].join(20)
        assert not threads[other].is_alive()
    finally:
        for signal in release.values():
            signal.set()
        for thread in threads.values():
            thread.join(10)
    reaped = all(not thread.is_alive() for thread in threads.values())
    assert reaped, "owned participant was not reaped"
    monkeypatch.setattr(pub, "_before_publication_primitive", lambda *_: None)
    final_rows, final_files = _rows(factory), _files(final)
    recovery = _call(factory, owner_kw["B"])
    data = {
        "release_first": release_first,
        "timeline": timeline,
        "results": results,
        "baseline_rows": baseline_rows,
        "both_paused_rows": both_paused_rows,
        "both_paused_files": both_paused_files,
        "first_files": first_files,
        "final_rows": final_rows,
        "final_files": final_files,
        "reaped": reaped,
        "b_recovery": recovery,
    }
    _record("v09" if release_first == "B" else "v10", data)
    return data


def _handoff_assertions(
    data: dict[str, Any], final: Path, payloads: dict[str, bytes]
) -> None:
    assert final.read_bytes() == payloads["B"], "stale owner bytes must never win"
    assert data["results"]["B"]["outcome"] is not None
    assert data["results"]["B"]["outcome"]["status"] == "completed"
    assert data["results"]["A"]["error"] is not None
    successes = [x["owner"] for x in data["timeline"] if x["event"] == "exclusive-success"]
    assert successes == ["B"], successes
    assert len(data["final_rows"]["s12_export_run"]) == 1
    assert len(data["final_rows"]["job"]) == 1
    assert len(data["baseline_rows"]["s12_export_run"]) == 1
    assert data["reaped"] is True


def test_v09_handoff_release_b_first_b_is_sole_publisher(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Released-B-first: B publishes with its own bytes; stale A denied."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    payloads = {"A": b"stale A bytes must never win (v09)", "B": b"current B bytes win (v09)"}
    data = _run_handoff(factory, kw, monkeypatch, "B", payloads)
    _handoff_assertions(data, final, payloads)
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    # stale A changed no winner identity and did not create companions
    assert data["final_files"][str(pub._sidecar_path(final))]["sha256"] == data[
        "first_files"
    ][str(pub._sidecar_path(final))]["sha256"]


def test_v10_handoff_release_a_first_stale_a_never_publishes(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Released-A-first: expired A performs NO public publication; B completes."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    payloads = {"A": b"expired A bytes must never win (v10)", "B": b"current B bytes win (v10)"}
    data = _run_handoff(factory, kw, monkeypatch, "A", payloads)
    _handoff_assertions(data, final, payloads)
    assert data["results"]["A"]["error"]["type"] == "PublicationError"
    assert "fence lost" in data["results"]["A"]["error"]["detail"]


@pytest.mark.parametrize("schedule", ["b_first", "a_first"])
def test_v11_equal_bytes_ownership_independent_of_sha(
    env, monkeypatch: pytest.MonkeyPatch, schedule: str
) -> None:  # type: ignore[no-untyped-def]
    """Equal bytes: ownership is proven by inode identity, never by sha."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    same = b"byte-identical candidate for both live owners (v11)"
    payloads = {"A": same, "B": same}
    release_first = "B" if schedule == "b_first" else "A"
    data = _run_handoff(factory, kw, monkeypatch, release_first, payloads)
    _handoff_assertions(data, final, payloads)
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    assert data["final_files"][str(final)]["sha256"] == pub._sha256_file(final)


# ---------------------------------------------------------------------------
# V12 - V15: boundaries
# ---------------------------------------------------------------------------


def test_v12_interruption_between_companions_stale_cleanup_cannot_corrupt(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A stale cleanup attempt cannot delete or damage the current winner."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])

    def stop(final_path: Path) -> None:
        raise RuntimeError("R6_V12_INTERRUPT_BETWEEN_COMPANIONS")

    monkeypatch.setattr(pub, "_after_publication_final", stop)
    with factory() as session:
        with pytest.raises(RuntimeError, match="R6_V12"):
            pub.publish_export_run(session, **kw)
        session.rollback()
    monkeypatch.setattr(pub, "_after_publication_final", lambda final_path: None)
    assert final.is_file()
    assert not pub._sidecar_path(final).exists()
    interrupted = _files(final)
    fresh_kw = _fresh_owner(factory, kw)

    # A stale cleanup from the OLD owner runs while B is the live owner:
    with factory() as session:
        pub._cleanup_publication_scratch(
            kw["manifest"],
            session=session,
            run_id=kw["run_id"],
            worker_id=kw["worker_id"],
            fence_token=kw["fence_token"],
        )
    pub._remove_owned_publication_intent(final, {"stale": "payload"})
    assert _files(final) == interrupted
    with factory() as session:
        out = pub.publish_export_run(session, **fresh_kw)
        session.commit()
    after = _files(final)
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    _record(
        "v12",
        {
            "recovered": out.get("recovered"),
            "interrupted_final": interrupted[str(final)],
            "after_final": after[str(final)],
            "identity_match": pub._identity_matches(final, receipt.get("artifact_identity")),
        },
    )
    assert out.get("recovered") is True
    assert after[str(final)]["ino"] == interrupted[str(final)]["ino"]
    assert after[str(final)]["sha256"] == interrupted[str(final)]["sha256"]
    assert pub._identity_matches(final, receipt.get("artifact_identity"))


def test_v13_private_candidate_rebuild_cannot_mutate_public(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A rebuilt/held private candidate can never mutate the public inode."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    with factory() as session:
        out = pub.publish_export_run(session, **kw)
        session.commit()
    assert out["status"] == "completed"
    published = _files(final)
    candidate.write_bytes(b"rebuilt private candidate bytes")
    with candidate.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"held-handle mutation")
        handle.flush()
    with factory() as session:
        replay = pub.publish_export_run(session, **kw)
        session.commit()
    _record(
        "v13",
        {
            "reused": replay.get("reused"),
            "published": published[str(final)],
            "after": _files(final)[str(final)],
        },
    )
    assert replay["reused"] is True
    assert _files(final) == published
    assert not os.path.samefile(candidate, final)


@pytest.mark.parametrize("case", ["short", "spaces_unicode", "deep", "export_master"])
def test_v14_supported_paths_full_publisher_completes(
    env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:  # type: ignore[no-untyped-def]
    """Server-supported Windows path shapes complete a real publication."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    root = tmp_path / "r6-v14"
    if case == "short":
        out = root / "out.mp4"
    elif case == "spaces_unicode":
        out = root / "deep path" / "字幕 測試" / "résultat final.mp4"
    elif case == "deep":
        out = tmp_path.joinpath(*[f"seg{i:02d}" for i in range(10)]) / "final.mp4"
    else:
        out = root / "export_master.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    kw["manifest"]["output_path"] = str(out)
    candidate = Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"
    candidate.write_bytes(b"v14 path-shape publication bytes")
    with factory() as session:
        result = pub.publish_export_run(session, **kw)
        session.commit()
    names = sorted(p.name for p in out.parent.iterdir())
    _record(
        "v14_supported",
        {"case": case, "status": result["status"], "names": names},
    )
    assert result["status"] == "completed"
    assert out.is_file()
    assert pub._sidecar_path(out).is_file()
    assert pub._publication_receipt_path(out).is_file()
    assert names == sorted(
        [out.name, pub._sidecar_path(out).name, pub._publication_receipt_path(out).name,
         pub._publication_lock_path(out).name]
    )


@pytest.mark.parametrize("case", ["basename155", "overlong250"])
def test_v14_unsupported_path_typed_denial_zero_public_bytes(
    env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:  # type: ignore[no-untyped-def]
    """An unaddressable path is a typed denial before ANY public write.

    ``basename155`` exceeds the conservative companion-temp bound for a
    real lease token (the R4 helper counterexample shape): the full
    publisher must answer with a typed path error and zero public delta.
    """
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    out_dir = tmp_path / "r6-v14-unsupported"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = ("y" * 250 if case == "overlong250" else "x" * 155) + ".mp4"
    out = out_dir / name
    before = sorted(p.name for p in out_dir.iterdir())
    with factory() as session:
        with pytest.raises(pub.PublicationPathError) as exc_info:
            pub.publish_export_run(
                session,
                **{**kw, "manifest": {**kw["manifest"], "output_path": str(out)}},
            )
        session.rollback()
    after = sorted(p.name for p in out_dir.iterdir())
    _record(
        "v14_unsupported",
        {"case": case, "code": getattr(exc_info.value, "code", None), "before": before, "after": after},
    )
    assert exc_info.value.code == "S12_T03C_PUBLICATION_PATH_INVALID"
    assert after == before
    assert not out.exists()


def test_v15_interrupted_temp_and_foreign_companion_preserved(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Foreign companions are preserved; only owned temp cleanup happens."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    scratch = Path(kw["manifest"]["scratch_dir"])
    candidate = scratch / "candidate_final.mp4"
    candidate.write_bytes(b"v15 interrupted temp control")
    leftover = scratch / "candidate_final.mp4.deadbeef.tmp"
    leftover.write_bytes(b"interrupted owned temp from a crashed attempt")
    final.parent.mkdir(parents=True, exist_ok=True)
    sidecar = pub._sidecar_path(final)
    sidecar.write_bytes(b"foreign-sidecar-bytes\n")
    foreign_state = _file_state(sidecar)
    first = _call(factory, kw)
    assert first["error"] is not None
    assert "refusing overwrite" in first["error"]["detail"]
    assert _file_state(sidecar) == foreign_state
    owned_cleanup = {"leftover": leftover.exists(), "candidate": candidate.exists()}
    sidecar.unlink()
    candidate.write_bytes(b"v15 second attempt bytes")
    with factory() as session:
        out = pub.publish_export_run(session, **kw)
        session.commit()
    _record(
        "v15",
        {
            "first_error": first["error"]["detail"][:120],
            "owned_cleanup": owned_cleanup,
            "status": out["status"],
            "foreign_preserved": True,
        },
    )
    assert out["status"] == "completed"
    assert final.is_file()
    assert not leftover.exists()
    assert pub._sidecar_path(final).is_file()
    assert pub._publication_receipt_path(final).is_file()

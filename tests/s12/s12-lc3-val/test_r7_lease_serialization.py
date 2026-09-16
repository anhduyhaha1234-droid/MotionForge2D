"""S12-LC3-VAL R7 — F01: ownership transition serialized with the publication.

Frozen node map (ACCEPTANCE_R7 A01/A02; lane freeze 2026-09-16):

- A01 ``test_a01_section_first_prevents_takeover_owner_completes``
- A01 ``test_a01_claim_first_stale_entry_denied_b_completes``
- A01 ``test_a01_claim_attempt_at_each_public_mutation_denied[pre_link|post_link_pre_sidecar|post_sidecar_pre_receipt|receipt_precommit]``
- A02 ``test_a02_process_section_prevents_takeover_owner_completes``
- A02 ``test_a02_kill_midsection_post_link_fresh_process_recovers``
- A02 ``test_a02_expired_released_reclaimed_tokens[expired_no_claim|released_no_claim|reclaimed_by_B]``
- A02 ``test_a02_ordering_bytes_matrix[section_first|claim_first x equal|unequal]``
- A02 ``test_a02_lost_ack_and_stale_cleanup_under_lease_guard``

Contract under test (D1): the lease claim transaction and the publication
section share one per-run cross-process lock; a claim arriving while a
section is active fails typed with ZERO mutation; a publisher entering its
section re-validates ownership first.  Real claim + real primitive, two
live participants/processes, barrier at the contested point, bounded
joins, children reaped (no sleep-only dummy), winner recorded with
sha256 + dev/ino + mtime_ns for final/sidecar/receipt/intent/candidate.

Evidence: with ``S12_R7_VAL_OUT`` set, each node writes one JSON record
(exclusive create, unique suffix) into that directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session as OrmSession

TEST03C = Path(__file__).resolve().parents[1] / "s12-t03c"
sys.path.insert(0, str(TEST03C))
import test_publication as publication_base  # noqa: E402

from app.persistence.s12_export import S12ExportRepository  # noqa: E402
from app.services.s12_export import publication as pub  # noqa: E402
from app.services.s12_export.publication_lease_guard import (  # noqa: E402
    PublicationInProgressError,
)

env = publication_base.env


def _record(name: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, default=str, sort_keys=True)
    print(f"R7_VAL {name} {payload[:2000]}")
    out_dir = os.environ.get("S12_R7_VAL_OUT") or os.environ.get("S12_R6_VAL_OUT")
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


def _claim_expect(factory: Any, run_id: str, worker: str) -> Any:
    with factory() as session:
        try:
            lease = S12ExportRepository(session).claim_run(run_id, worker)
            session.commit()
            return lease
        except BaseException as exc:  # noqa: BLE001 - typed outcome recorded
            session.rollback()
            return exc


def _lease_row(factory: Any, run_id: str) -> dict[str, Any]:
    with factory() as session:
        row = session.execute(
            publication_base.text(
                "SELECT * FROM s12_export_lease WHERE run_id=:run_id"
            ),
            {"run_id": run_id},
        ).mappings().first()
        return dict(row) if row is not None else {}


def _owner_manifest(kw: dict[str, Any], scratch: Path) -> dict[str, Any]:
    scratch.mkdir(parents=True, exist_ok=True)
    manifest = dict(kw["manifest"])
    manifest["scratch_dir"] = str(scratch)
    manifest["candidate_path"] = str(scratch / "candidate_final.mp4")
    return manifest


def _candidate(kw: dict[str, Any]) -> Path:
    return Path(kw["manifest"]["scratch_dir"]) / "candidate_final.mp4"


def _attach_links_recorder(
    monkeypatch: pytest.MonkeyPatch, links: list[str], name_by_candidate: dict[Path, str]
) -> None:
    original_primitive = pub._publish_candidate_exclusive

    def primitive(source: Path, destination: Path) -> Any:
        owner = name_by_candidate.get(Path(source), Path(source).parts[-2])
        links.append(owner)
        return original_primitive(source, destination)

    monkeypatch.setattr(pub, "_publish_candidate_exclusive", primitive)


# ---------------------------------------------------------------------------
# A01 — in-process: both legal serialized orderings
# ---------------------------------------------------------------------------


def _section_first_core(
    factory: Any, kw: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """A owns the section first; B's takeover is prevented; A completes."""
    final = Path(kw["manifest"]["output_path"])
    candidate = _candidate(kw)
    payload_a = b"section-first authorized owner bytes (r7)"
    candidate.write_bytes(payload_a)
    paused, release = threading.Event(), threading.Event()
    links: list[str] = []
    original_primitive = pub._publish_candidate_exclusive

    def primitive(source: Path, destination: Path) -> Any:
        links.append("A")
        paused.set()
        assert release.wait(20), "section-first A release timed out"
        return original_primitive(source, destination)

    monkeypatch.setattr(pub, "_publish_candidate_exclusive", primitive)
    outcomes: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: outcomes.update({"A": _call(factory, kw)}),
        name="r7-a01-section-first-A",
    )
    thread.start()
    assert paused.wait(10), "A never reached the in-section pre-link point"
    _expire_lease(factory, kw["run_id"])
    rows_before = _rows(factory)
    files_before = _files(final)
    monkeypatch.setenv("S12_EXPORT_LEASE_GUARD_WAIT", "2.0")
    claim_error = _claim_expect(factory, kw["run_id"], "r7-a01-section-first-B")
    rows_after_claim = _rows(factory)
    files_after_claim = _files(final)
    release.set()
    thread.join(20)
    reaped = not thread.is_alive()
    monkeypatch.delenv("S12_EXPORT_LEASE_GUARD_WAIT", raising=False)
    return {
        "payload_a": payload_a,
        "claim_error": claim_error,
        "rows_before": rows_before,
        "rows_after_claim": rows_after_claim,
        "files_before": files_before,
        "files_after_claim": files_after_claim,
        "outcome_a": outcomes.get("A"),
        "links": links,
        "reaped": reaped,
        "final": final,
    }


def test_a01_section_first_prevents_takeover_owner_completes(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A inside its section: B's claim is typed-denied with zero mutation;
    A's publication remains authorized and completes coherently."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    data = _section_first_core(factory, kw, monkeypatch)
    final = data["final"]
    err = data["claim_error"]
    _record(
        "a01_section_first",
        {
            "claim_error": {"type": type(err).__name__, "detail": str(err), "code": getattr(err, "code", None)},
            "zero_mutation": data["rows_before"] == data["rows_after_claim"]
            and data["files_before"] == data["files_after_claim"],
            "outcome_a": data["outcome_a"],
            "links": data["links"],
            "reaped": data["reaped"],
            "final": _file_state(final),
        },
    )
    assert isinstance(err, PublicationInProgressError)
    assert err.code == "S12_T03C_PUBLICATION_IN_PROGRESS"
    assert err.run_id == kw["run_id"]
    assert data["rows_before"] == data["rows_after_claim"], "B's denied claim mutated rows"
    assert data["files_before"] == data["files_after_claim"], "B's denied claim mutated files"
    assert data["reaped"] is True
    out_a = data["outcome_a"]
    assert out_a["error"] is None
    assert out_a["outcome"]["status"] == "completed"
    assert data["links"] == ["A"]
    assert final.read_bytes() == data["payload_a"]
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    lease = _lease_row(factory, kw["run_id"])
    assert lease["worker_id"] == kw["worker_id"]
    assert lease["lease_version"] == 1
    rows_final = _rows(factory)
    assert len(rows_final["s12_export_run"]) == 1
    assert len(rows_final["job"]) == 1
    retry = _claim_expect(factory, kw["run_id"], "r7-a01-section-first-B")
    assert not hasattr(retry, "fence_token"), "B claimed a completed run"
    assert "cannot be claimed" in str(retry)


def test_a01_claim_first_stale_entry_denied_b_completes(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """B claims while A waits BEFORE its section: stale A performs no
    public mutation; B is the sole authorized publisher."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    root = Path(kw["manifest"]["scratch_dir"]).parent
    b_manifest = _owner_manifest(kw, root / "r7-a01-b")
    payload_a = b"claim-first stale A bytes must never win (r7)"
    payload_b = b"claim-first current B bytes win (r7)"
    _candidate(kw).write_bytes(payload_a)
    (Path(b_manifest["scratch_dir"]) / "candidate_final.mp4").write_bytes(payload_b)
    final = Path(kw["manifest"]["output_path"])
    pre, release = threading.Event(), threading.Event()
    original_guard = pub.publication_lease_guard

    def gated_guard(run_id: str, *, db_path: Any = None, wait_seconds: Any = None) -> Any:
        if threading.current_thread().name == "r7-a01-claim-first-A" and not pre.is_set():
            pre.set()
            assert release.wait(20), "claim-first A pre-section release timed out"
        return original_guard(run_id, db_path=db_path, wait_seconds=wait_seconds)

    monkeypatch.setattr(pub, "publication_lease_guard", gated_guard)
    links: list[str] = []
    _attach_links_recorder(
        monkeypatch,
        links,
        {_candidate(kw): "A", Path(b_manifest["candidate_path"]): "B"},
    )
    outcomes: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: outcomes.update({"A": _call(factory, kw)}),
        name="r7-a01-claim-first-A",
    )
    thread.start()
    assert pre.wait(10), "A never reached the pre-section barrier"
    _expire_lease(factory, kw["run_id"])
    b_lease = _claim_expect(factory, kw["run_id"], "r7-a01-claim-first-B")
    assert hasattr(b_lease, "fence_token"), f"B claim failed: {b_lease!r}"
    rows_claimed = _rows(factory)
    release.set()
    thread.join(20)
    reaped = not thread.is_alive()
    out_a = outcomes.get("A")
    assert out_a["error"] is not None
    assert "fence lost" in out_a["error"]["detail"]
    assert not final.exists(), "stale A published after B owned the run"
    assert _candidate(kw).is_file(), "stale cleanup removed stale A's own candidate"
    kw_b = dict(
        kw,
        worker_id="r7-a01-claim-first-B",
        fence_token=b_lease.fence_token,
        manifest=b_manifest,
    )
    out_b = _call(factory, kw_b)
    _record(
        "a01_claim_first",
        {
            "outcome_a": out_a,
            "outcome_b": out_b,
            "links": links,
            "reaped": reaped,
            "lease_version": rows_claimed["s12_export_lease"][0]["lease_version"],
            "final": _file_state(final),
        },
    )
    assert out_b["error"] is None
    assert out_b["outcome"]["status"] == "completed"
    assert final.read_bytes() == payload_b
    assert links == ["B"]
    assert reaped is True
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))


@pytest.mark.parametrize(
    "point", ["pre_link", "post_link_pre_sidecar", "post_sidecar_pre_receipt", "receipt_precommit"]
)
def test_a01_claim_attempt_at_each_public_mutation_denied(
    env, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:  # type: ignore[no-untyped-def]
    """At EVERY public-mutation boundary inside the section, a concurrent
    claim is typed-denied with zero mutation and the owner still completes."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    candidate = _candidate(kw)
    payload = b"each-mutation-point authorized bytes (r7)"
    candidate.write_bytes(payload)
    paused, release = threading.Event(), threading.Event()
    thread_name = f"r7-a01-point-{point}"

    def pause_now() -> None:
        paused.set()
        assert release.wait(20), f"{point} release timed out"

    if point == "pre_link":
        original_primitive = pub._publish_candidate_exclusive

        def primitive(source: Path, destination: Path) -> Any:
            pause_now()
            return original_primitive(source, destination)

        monkeypatch.setattr(pub, "_publish_candidate_exclusive", primitive)
    elif point == "post_link_pre_sidecar":
        original_hook = pub._after_publication_final

        def hook(final_path: Path) -> None:
            original_hook(final_path)
            pause_now()

        monkeypatch.setattr(pub, "_after_publication_final", hook)
    elif point == "post_sidecar_pre_receipt":
        original_receipt = pub._write_publication_receipt

        def receipt_hook(*args: Any, **kwargs: Any) -> Any:
            pause_now()
            return original_receipt(*args, **kwargs)

        monkeypatch.setattr(pub, "_write_publication_receipt", receipt_hook)
    else:
        original_commit = OrmSession.commit

        def commit_hook(self: OrmSession) -> None:
            if threading.current_thread().name == thread_name and not paused.is_set():
                pause_now()
            original_commit(self)

        monkeypatch.setattr(OrmSession, "commit", commit_hook)

    outcomes: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: outcomes.update({"A": _call(factory, kw)}),
        name=thread_name,
    )
    thread.start()
    assert paused.wait(10), f"A never reached {point}"
    if point != "receipt_precommit":
        # At the precommit point the owner holds the SQLite write transaction
        # (transitions executed, commit pending): a raw expiry from another
        # connection is locked out -- which is itself the DB-side serialization.
        # The claim attempt below is still denied by the run guard before any
        # DB access, so no expiry is needed for this point.
        _expire_lease(factory, kw["run_id"])
    rows_before = _rows(factory)
    files_before = _files(final)
    monkeypatch.setenv("S12_EXPORT_LEASE_GUARD_WAIT", "2.0")
    claim_error = _claim_expect(factory, kw["run_id"], f"r7-a01-point-B-{point}")
    rows_after = _rows(factory)
    files_after = _files(final)
    release.set()
    thread.join(20)
    reaped = not thread.is_alive()
    monkeypatch.delenv("S12_EXPORT_LEASE_GUARD_WAIT", raising=False)
    out_a = outcomes.get("A")
    _record(
        f"a01_point_{point}",
        {
            "claim_error": {"type": type(claim_error).__name__, "detail": str(claim_error)},
            "zero_mutation": rows_before == rows_after and files_before == files_after,
            "outcome_a": out_a,
            "reaped": reaped,
            "final": _file_state(final),
        },
    )
    assert isinstance(claim_error, PublicationInProgressError)
    assert rows_before == rows_after, f"{point}: denied claim mutated rows"
    assert files_before == files_after, f"{point}: denied claim mutated files"
    assert reaped is True
    assert out_a["error"] is None, out_a
    assert out_a["outcome"]["status"] == "completed"
    assert final.read_bytes() == payload
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))


# ---------------------------------------------------------------------------
# A02 — separate processes, token matrix, ordering x bytes, lost-ack
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _db_path_of(factory: Any) -> Path:
    return Path(str(factory.kw["bind"].url.database))


def _pid_gone(pid: int) -> bool:
    tasklist = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return str(pid) not in tasklist.stdout


def test_a02_process_section_prevents_takeover_owner_completes(
    env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Cross-process: while a real publisher child holds its section, a
    claim from another process is typed-denied with zero mutation; the
    child completes as the authorized owner and is reaped."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    payload = b"a02 process section-first authorized bytes"
    _candidate(kw).write_bytes(payload)
    workdir = tmp_path / "r7-a02-prevent"
    workdir.mkdir()
    marker = workdir / "at-section.json"
    release = workdir / "release.flag"
    kw_file = workdir / "kw.json"
    kw_file.write_text(
        json.dumps({"db": str(_db_path_of(factory)), "kw": kw}), encoding="utf-8"
    )
    child_code = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "marker = Path(sys.argv[2]); release = Path(sys.argv[3])\n"
        "sys.path.insert(0, sys.argv[4])\n"
        "from types import SimpleNamespace\n"
        "from app.persistence import create_engine_for_path, create_session_factory\n"
        "from app.services.s12_export import publication as pub\n"
        "from app.services.s12_export import validation\n"
        "pub._require_ready = lambda session, **kw: None\n"
        "validation.validate = lambda path, expectation: SimpleNamespace(\n"
        "    verdict='PASS', probes=(SimpleNamespace(name='frame_count', verdict='PASS', detail='stub'),))\n"
        "original = pub._publish_candidate_exclusive\n"
        "def boundary(source, destination):\n"
        "    marker.write_text(json.dumps({'pid': os.getpid()}), encoding='utf-8')\n"
        "    deadline = time.monotonic() + 90\n"
        "    while not release.exists() and time.monotonic() < deadline:\n"
        "        time.sleep(0.05)\n"
        "    return original(source, destination)\n"
        "pub._publish_candidate_exclusive = boundary\n"
        "factory = create_session_factory(create_engine_for_path(Path(payload['db'])))\n"
        "with factory() as session:\n"
        "    out = pub.publish_export_run(session, **payload['kw'])\n"
        "    session.commit()\n"
        "print('CHILD_DONE', out.get('status'))\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(kw_file), str(marker), str(release), str(_repo_root())],
        cwd=str(_repo_root()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = child.pid
    try:
        deadline = time.monotonic() + 120
        while not marker.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                pytest.fail(
                    "child exited before section barrier rc="
                    f"{child.returncode} err={(child.stderr.read() if child.stderr else '')[-800:]}"
                )
            time.sleep(0.05)
        assert marker.exists(), "real publisher child never reached the section barrier"
        assert child.poll() is None
        _expire_lease(factory, kw["run_id"])
        rows_before = _rows(factory)
        files_before = _files(final)
        monkeypatch.setenv("S12_EXPORT_LEASE_GUARD_WAIT", "2.0")
        claim_error = _claim_expect(factory, kw["run_id"], "r7-a02-prevent-B")
        rows_after = _rows(factory)
        files_after = _files(final)
        monkeypatch.delenv("S12_EXPORT_LEASE_GUARD_WAIT", raising=False)
        release.write_text("go", encoding="utf-8")
        child.wait(timeout=90)
        assert child.returncode == 0, (child.stderr.read() if child.stderr else "")[-800:]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)
    assert isinstance(claim_error, PublicationInProgressError)
    assert claim_error.code == "S12_T03C_PUBLICATION_IN_PROGRESS"
    assert rows_before == rows_after, "cross-process denied claim mutated rows"
    assert files_before == files_after, "cross-process denied claim mutated files"
    assert final.read_bytes() == payload
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    lease = _lease_row(factory, kw["run_id"])
    assert lease["worker_id"] == kw["worker_id"]
    assert lease["lease_version"] == 1
    assert _pid_gone(child_pid), "child not reaped"
    rows_final = _rows(factory)
    _record(
        "a02_process_prevent",
        {
            "claim_error": {"type": type(claim_error).__name__, "detail": str(claim_error)},
            "zero_mutation": rows_before == rows_after and files_before == files_after,
            "child_pid": child_pid,
            "child_exit": child.returncode,
            "reaped": _pid_gone(child_pid),
            "rows": len(rows_final["s12_export_run"]),
            "final": _file_state(final),
        },
    )


def test_a02_kill_midsection_post_link_fresh_process_recovers(
    env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Real child killed INSIDE its section (post-link, pre-sidecar): the OS
    releases the lease lock on process death, a fresh claimant proceeds
    bounded, and recovery adopts the child's own inode to completion."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    payload = b"a02 killed child authorized bytes"
    _candidate(kw).write_bytes(payload)
    workdir = tmp_path / "r7-a02-kill"
    workdir.mkdir()
    marker = workdir / "post-link.json"
    kw_file = workdir / "kw.json"
    kw_file.write_text(
        json.dumps({"db": str(_db_path_of(factory)), "kw": kw}), encoding="utf-8"
    )
    child_code = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
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
        "    while True:\n"
        "        time.sleep(0.05)\n"
        "pub._after_publication_final = boundary\n"
        "factory = create_session_factory(create_engine_for_path(Path(payload['db'])))\n"
        "with factory() as session:\n"
        "    pub.publish_export_run(session, **payload['kw'])\n"
        "    session.commit()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(kw_file), str(marker), str(_repo_root())],
        cwd=str(_repo_root()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = child.pid
    try:
        deadline = time.monotonic() + 120
        while not marker.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                pytest.fail(
                    "child exited before post-link boundary rc="
                    f"{child.returncode} err={(child.stderr.read() if child.stderr else '')[-800:]}"
                )
            time.sleep(0.05)
        assert marker.exists(), "child never reached post-link boundary"
        killed_state = json.loads(marker.read_text(encoding="utf-8"))
        assert final.is_file()
        assert pub._sha256_file(final) == killed_state["sha256"]
        subprocess.run(
            ["taskkill", "/F", "/PID", str(child_pid)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        child.wait(timeout=20)
        assert child.returncode != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)
    assert _pid_gone(child_pid), "killed child not reaped"
    _expire_lease(factory, kw["run_id"])
    b_lease = _claim_expect(factory, kw["run_id"], "r7-a02-kill-B")
    assert hasattr(b_lease, "fence_token"), f"post-kill claim failed: {b_lease!r}"
    kw_b = dict(kw, worker_id="r7-a02-kill-B", fence_token=b_lease.fence_token)
    out_b = _call(factory, kw_b)
    _record(
        "a02_kill_recover",
        {
            "child_pid": child_pid,
            "child_exit": child.returncode,
            "outcome_b": out_b,
            "final": _file_state(final),
        },
    )
    assert out_b["error"] is None
    assert out_b["outcome"]["status"] == "completed"
    assert out_b["outcome"].get("recovered") is True
    stat = final.stat()
    assert stat.st_dev == killed_state["dev"]
    assert stat.st_ino == killed_state["ino"]
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    rows = _rows(factory)
    assert len(rows["s12_export_run"]) == 1
    assert len(rows["job"]) == 1
    assert _lease_row(factory, kw["run_id"])["lease_version"] == 2


@pytest.mark.parametrize(
    "state", ["expired_no_claim", "released_no_claim", "reclaimed_by_B"]
)
def test_a02_expired_released_reclaimed_tokens(
    env, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:  # type: ignore[no-untyped-def]
    """Expired/released/reclaimed tokens can never publish: typed denial
    with zero public mutation; the reclaiming owner stays usable."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    root = Path(kw["manifest"]["scratch_dir"]).parent
    _candidate(kw).write_bytes(b"a02 token-matrix stale-A bytes")
    if state == "expired_no_claim":
        _expire_lease(factory, kw["run_id"])
    elif state == "released_no_claim":
        with factory() as session:
            S12ExportRepository(session).release_lease(
                kw["run_id"], kw["worker_id"], kw["fence_token"]
            )
            session.commit()
    else:
        _expire_lease(factory, kw["run_id"])
        b_lease = _claim_expect(factory, kw["run_id"], "r7-a02-token-B")
        assert hasattr(b_lease, "fence_token"), f"claim failed: {b_lease!r}"
    rows_before = _rows(factory)
    out_a = _call(factory, kw)
    rows_after = _rows(factory)
    assert out_a["error"] is not None, out_a
    assert "fence" in out_a["error"]["detail"]
    assert not final.exists(), f"{state}: stale token produced a public final"
    assert not pub._sidecar_path(final).exists()
    assert not pub._publication_receipt_path(final).exists()
    if state == "reclaimed_by_B":
        b_manifest = _owner_manifest(kw, root / "r7-a02-token-b")
        payload_b = b"a02 token-matrix reclaimed-B bytes"
        (Path(b_manifest["scratch_dir"]) / "candidate_final.mp4").write_bytes(payload_b)
        kw_b = dict(
            kw,
            worker_id="r7-a02-token-B",
            fence_token=b_lease.fence_token,
            manifest=b_manifest,
        )
        out_b = _call(factory, kw_b)
        assert out_b["error"] is None, out_b
        assert out_b["outcome"]["status"] == "completed"
        assert final.read_bytes() == payload_b
    else:
        assert rows_before == rows_after, f"{state}: denied attempt mutated rows"
        assert not pub._publication_intent_path(final).exists()
    _record(
        f"a02_token_{state}",
        {
            "outcome_a": out_a,
            "rows_equal": rows_before == rows_after,
            "final": _file_state(final),
        },
    )


@pytest.mark.parametrize("bytes_mode", ["equal", "unequal"])
@pytest.mark.parametrize("ordering", ["section_first", "claim_first"])
def test_a02_ordering_bytes_matrix(
    env, monkeypatch: pytest.MonkeyPatch, ordering: str, bytes_mode: str
) -> None:  # type: ignore[no-untyped-def]
    """Both serialized orderings x equal/unequal bytes: exactly one
    authorized publisher; ownership is independent of SHA."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    root = Path(kw["manifest"]["scratch_dir"]).parent
    payload_a = (
        b"r7-a02-matrix-identical-bytes"
        if bytes_mode == "equal"
        else b"r7-a02-matrix-A-bytes"
    )
    payload_b = payload_a if bytes_mode == "equal" else b"r7-a02-matrix-B-bytes"
    _candidate(kw).write_bytes(payload_a)
    b_manifest = _owner_manifest(kw, root / "r7-a02-matrix-b")
    Path(b_manifest["candidate_path"]).write_bytes(payload_b)
    links: list[str] = []
    _attach_links_recorder(
        monkeypatch,
        links,
        {_candidate(kw): "A", Path(b_manifest["candidate_path"]): "B"},
    )
    if ordering == "section_first":
        paused, release = threading.Event(), threading.Event()
        original_primitive = pub._publish_candidate_exclusive

        def primitive(source: Path, destination: Path) -> Any:
            # The links recorder (attached above) already records this link.
            paused.set()
            assert release.wait(20), "matrix section-first release timed out"
            return original_primitive(source, destination)

        monkeypatch.setattr(pub, "_publish_candidate_exclusive", primitive)
        outcomes: dict[str, Any] = {}
        thread = threading.Thread(
            target=lambda: outcomes.update({"A": _call(factory, kw)}),
            name="r7-a02-matrix-section-A",
        )
        thread.start()
        assert paused.wait(10), "A never reached the section"
        _expire_lease(factory, kw["run_id"])
        rows_before = _rows(factory)
        monkeypatch.setenv("S12_EXPORT_LEASE_GUARD_WAIT", "2.0")
        claim_error = _claim_expect(factory, kw["run_id"], "r7-a02-matrix-B")
        rows_after = _rows(factory)
        monkeypatch.delenv("S12_EXPORT_LEASE_GUARD_WAIT", raising=False)
        release.set()
        thread.join(20)
        assert not thread.is_alive()
        assert isinstance(claim_error, PublicationInProgressError)
        assert rows_before == rows_after
        out_a = outcomes.get("A")
        assert out_a["error"] is None and out_a["outcome"]["status"] == "completed"
        winner_payload = payload_a
        assert links == ["A"]
    else:
        pre, release2 = threading.Event(), threading.Event()
        original_guard = pub.publication_lease_guard

        def gated_guard(run_id: str, *, db_path: Any = None, wait_seconds: Any = None) -> Any:
            if (
                threading.current_thread().name == "r7-a02-matrix-claim-A"
                and not pre.is_set()
            ):
                pre.set()
                assert release2.wait(20), "matrix claim-first release timed out"
            return original_guard(run_id, db_path=db_path, wait_seconds=wait_seconds)

        monkeypatch.setattr(pub, "publication_lease_guard", gated_guard)
        outcomes2: dict[str, Any] = {}
        thread2 = threading.Thread(
            target=lambda: outcomes2.update({"A": _call(factory, kw)}),
            name="r7-a02-matrix-claim-A",
        )
        thread2.start()
        assert pre.wait(10), "A never reached the pre-section barrier"
        _expire_lease(factory, kw["run_id"])
        b_lease = _claim_expect(factory, kw["run_id"], "r7-a02-matrix-B")
        assert hasattr(b_lease, "fence_token"), f"claim failed: {b_lease!r}"
        release2.set()
        thread2.join(20)
        assert not thread2.is_alive()
        out_a2 = outcomes2.get("A")
        assert out_a2["error"] is not None and "fence lost" in out_a2["error"]["detail"]
        assert not final.exists()
        kw_b = dict(
            kw,
            worker_id="r7-a02-matrix-B",
            fence_token=b_lease.fence_token,
            manifest=b_manifest,
        )
        out_b = _call(factory, kw_b)
        assert out_b["error"] is None and out_b["outcome"]["status"] == "completed"
        winner_payload = payload_b
        assert links == ["B"]
    assert final.read_bytes() == winner_payload
    receipt = json.loads(pub._publication_receipt_path(final).read_text(encoding="utf-8"))
    assert pub._identity_matches(final, receipt.get("artifact_identity"))
    rows_final = _rows(factory)
    assert len(rows_final["s12_export_run"]) == 1
    assert len(rows_final["job"]) == 1
    _record(
        f"a02_matrix_{ordering}_{bytes_mode}",
        {
            "links": links,
            "winner_payload_sha": pub._sha256_file(final),
            "lease": {
                k: v
                for k, v in _lease_row(factory, kw["run_id"]).items()
                if k in ("worker_id", "lease_version")
            },
            "final": _file_state(final),
        },
    )


def test_a02_lost_ack_and_stale_cleanup_under_lease_guard(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Commit-then-lose-ack converges on replay; a stale cleanup attempted
    while the owner is mid-section mutates nothing and never corrupts the
    winner's artifacts (hash+inode+mtime stable)."""
    publication_base._patch(monkeypatch, "PASS")
    factory, kw = publication_base._submit(env, monkeypatch)
    final = Path(kw["manifest"]["output_path"])
    payload = b"a02 lost-ack authorized bytes"
    _candidate(kw).write_bytes(payload)
    thread_name = "r7-a02-lostack-A"
    paused, release = threading.Event(), threading.Event()
    original_commit = OrmSession.commit
    fired = {"n": 0}

    def commit_hook(self: OrmSession) -> None:
        if threading.current_thread().name == thread_name and fired["n"] == 0:
            fired["n"] = 1
            paused.set()
            assert release.wait(20), "lost-ack commit pause timed out"
            original_commit(self)
            raise RuntimeError("R7_LOST_ACK after committed transitions")
        original_commit(self)

    monkeypatch.setattr(OrmSession, "commit", commit_hook)
    outcomes: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: outcomes.update({"A": _call(factory, kw)}),
        name=thread_name,
    )
    thread.start()
    assert paused.wait(10), "A never reached the transitions-commit point"
    scratch = Path(kw["manifest"]["scratch_dir"])
    scratch_before = sorted(p.name for p in scratch.iterdir())
    with factory() as session:
        pub._cleanup_publication_scratch(
            kw["manifest"],
            session=session,
            run_id=kw["run_id"],
            worker_id="worker-stale-never",
            fence_token="stale-token-never",
        )
    pub._remove_owned_publication_intent(final, {"stale": "payload"})
    scratch_after = sorted(p.name for p in scratch.iterdir())
    release.set()
    thread.join(20)
    assert not thread.is_alive()
    monkeypatch.setattr(OrmSession, "commit", original_commit)
    out_a = outcomes.get("A")
    assert out_a["error"] is not None
    assert out_a["error"]["type"] == "RuntimeError"
    assert scratch_before == scratch_after, "stale cleanup mutated the owner's scratch"
    with factory() as session:
        assert S12ExportRepository(session).get_run(kw["run_id"]).status == "completed"
    stable_before = _files(final)
    replay = _call(factory, kw)
    stable_after = _files(final)
    _record(
        "a02_lost_ack_stale_cleanup",
        {
            "outcome_a": out_a,
            "scratch_equal": scratch_before == scratch_after,
            "reused": replay.get("outcome", {}).get("reused") if replay["outcome"] else None,
            "replay_error": replay["error"],
            "stable": stable_before == stable_after,
            "final": _file_state(final),
        },
    )
    assert replay["error"] is None or replay["outcome"] is not None
    assert stable_before == stable_after
    assert final.read_bytes() == payload
    rows = _rows(factory)
    assert len(rows["s12_export_run"]) == 1
    assert len(rows["job"]) == 1

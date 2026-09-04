"""S11-T06C — One-command measured acceptance suite/report/leak gate (W14).

Frozen runner pattern per T01D (``tests/test_s11_original_audio_acceptance.py`` —
ORIGINAL FILE UNTOUCHED; this module re-implements the pattern locally with
attribution and adapts it to the S11-T02..T05 QC surface)::

    python -m pytest tests/test_s11_t02a_qc_migration.py \\\\
        tests/test_s11_t02a_qc_schema.py \\\\
        ... (all 20 S11-T02..T05 files) \\\\
        --ignore=tests/test_integration.py -p no:cacheprovider \\\\
        --basetemp=<short Windows-native temp> -v

    (invoked with ``env -u MOTIONFORGE_DATABASE_URL``)

The ONE command certifies the whole S11-T02..T05 wave (314 tests at W14
design time) exactly like T01D scenario-9 certified the T01 slice.  Every
assertion below is DYNAMIC — expected counts are derived from the T06B golden
manifests (``tests/fixtures/s11_qc/golden_manifests/``) and from the frozen
suite file list; nothing is hard-coded.  The measured report (per-file
pass/fail counts parsed from the verbose child output, phase durations, leak
gate) is written to a NEW run-id under ``output/s11-t06-e2e/<run-id>/`` —
never overwriting a previous run (AC4).

Leak gate mirrors T01D scenario-10 / correction C2: ONLY ffmpeg/ffprobe
processes observed INSIDE the child's live process tree are attributed to
this run, then polled for a 15 s window — survivors must be empty
(ownership-scoped, immune to concurrent machine activity).

Acceptance criteria (binary):
  1. One command: ``--ignore=tests/test_integration.py`` + ``-p
     no:cacheprovider`` + short unique basetemp + env strip -> exit 0;
     measured counts logged and matched against golden manifests dynamically
     (policy hash verified per manifest).
  2. Measured report: per-file pass/fail counts, phase durations (reference:
     T01D baseline ~166 s inner for 52 tests — reference only, NOT a hard
     gate), ffmpeg/ffprobe survivors == 0.
  3. Epic exit (ROADMAP L235): source voice/BGM/SFX remain in sync
     (test_s11_t03e_audio_sync_checks.py green inside the suite) and
     Scenario D achieves targeted rerun WITHOUT a full-timeline review
     (manifest ``expected_rerun_scope.rerun_target == affected_segment_only``
     with untouched ready scenes).
  4. New evidence run-id under ``output/s11-t06-e2e/``.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import msvcrt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

#: Recursion guard (defensive, mirrors T01D): the frozen S11_QC_SUITE_FILES
#: command does NOT include this acceptance file, so the guard is inert today
#: — it exists so a future wave that folds this file into its own frozen
#: suite can never fan out subprocesses exponentially.
if os.environ.get("S11_QC_ACCEPTANCE_NESTED") == "1":
    pytest.skip(
        "nested S11 QC acceptance run (recursion guard)",
        allow_module_level=True,
    )

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The 20 S11-T02..T05 files — the complete QC wave surface, run as ONE
#: command (frozen runner pattern T01D).  T06A1/A2/B fixture/manifest tests
#: are CONSUMED (imported helpers, golden manifests) — not part of the suite.
S11_QC_SUITE_FILES: tuple[str, ...] = (
    "tests/test_s11_t02a_qc_migration.py",
    "tests/test_s11_t02a_qc_schema.py",
    "tests/test_s11_t02b_qc_api_readonly.py",
    "tests/test_s11_t02b_qc_repository_lifecycle.py",
    "tests/test_s11_t03a_runner_registry.py",
    "tests/test_s11_t03a_thresholds_policy.py",
    "tests/test_s11_t03b_trajectory_cut_detectors.py",
    "tests/test_s11_t03c_contact_zorder_clipping_detectors.py",
    "tests/test_s11_t03d_identity_halo_flicker_detectors.py",
    "tests/test_s11_t03e_audio_sync_checks.py",
    "tests/test_s11_t03f_orchestrator.py",
    "tests/test_s11_t03g_qc_check_api.py",
    "tests/test_s11_t03g_qc_check_job.py",
    "tests/test_s11_t04a_navigation_api.py",
    "tests/test_s11_t04a_navigation_resolver.py",
    "tests/test_s11_t04b_correction_rerun.py",
    "tests/test_s11_t04b_stale_reopen.py",
    "tests/test_s11_t04c_attach_action_api.py",
    "tests/test_s11_t05a_next_action_flip.py",
    "tests/test_s11_t05a_readiness_api.py",
)

#: Hard total deadline for the nested child suite (pattern T01D correction C3
#: — reader threads + bounded wait, no outer/inner pipe-block hang).  T01D
#: used 1800 s for a 52-test slice; this surface is ~6x larger (314 tests),
#: so the safety valve is 2700 s.
_CHILD_TOTAL_DEADLINE_S = 2700

#: Synthetic return code when the hard total deadline fired (T01D pattern).
_TIMEOUT_RC = 124

#: Ownership-scoped leak window after the child exits (T01D scenario 10).
_LEAK_WINDOW_S = 15.0

#: T01D inner-suite baseline (52 passed in 166.7 s, T01D REPORT.md) —
#: REFERENCE ONLY for the measured report (AC2: "không phải gate cứng").
BASELINE_T01D_INNER_S = 166.7

#: Runtime evidence namespace (AC4 — a NEW run-id every run, never overwrite).
EVIDENCE_ROOT = PROJECT_ROOT / "output" / "s11-t06-e2e"

#: Monotonic per-process sequence for unique child basetemp directory names.
_basetemp_seq = itertools.count()

try:  # psutil required only for the ownership-scoped leak scan
    import psutil  # noqa: F401

    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    _PSUTIL_AVAILABLE = False

from s11_qc_golden import (  # noqa: E402 - conftest puts tests/ on sys.path
    GOLDEN_MANIFESTS,
    iter_manifests,
    load_policy,
    policy_ref_matches,
    validate_all,
)
from app.persistence.models import QC_REASON_CODES  # noqa: E402


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


#: Bounded polling for the executable restart/resume scenario (C1-B lane,
#: requirement 3 — deadline + poll interval finite, never an infinite sleep).
_C1B_RESTART_POLL_DEADLINE_S = 60.0
_C1B_RESTART_POLL_INTERVAL_S = 0.5

#: External lane evidence root (S11-C1 allowlist — outside the worktree diff).
_C1B_EVIDENCE_ROOT = Path(
    r"C:\Users\Admin\MotionForge2D-evidence\s11-c1\lanes\c1b-t06c"
)

_C1B_WS = "ws-s11-c1b"
_C1B_PROJECT = "p-s11-c1b"


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)


def _bounded_tail(text: str | None, lines: int = 25) -> str:
    """Bounded diagnostic tail (never floods the assertion message)."""
    return "\n".join((text or "").splitlines()[-lines:])


def _suite_cmd_env(basetemp: Path) -> tuple[list[str], dict[str, str]]:
    """The FROZEN 20-file S11-T02..T05 command + sanitized child env.

    Isolation (AC1): ``--ignore=tests/test_integration.py`` (SAM2 segfault
    file, S11 known pre-existing), ``-p no:cacheprovider``, a short
    Windows-native ``--basetemp`` unique to this process, and
    ``MOTIONFORGE_DATABASE_URL`` stripped.  ``-v`` is used so the child emits
    one ``nodeid STATUS`` line per test — the per-file measured counts (AC2)
    are parsed from that output.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *S11_QC_SUITE_FILES,
        "--ignore=tests/test_integration.py",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp.as_posix()}",
        "-v",
    ]
    env = {
        k: v for k, v in os.environ.items() if k != "MOTIONFORGE_DATABASE_URL"
    }
    env["S11_QC_ACCEPTANCE_NESTED"] = "1"
    return cmd, env


def _ffmpeg_name(name: str | None) -> bool:
    lowered = (name or "").lower()
    return lowered.startswith("ffmpeg") or lowered.startswith("ffprobe")


def _run_suite_tracked(
    basetemp: Path,
) -> tuple[int, str, str, set[int], str, str]:
    """``_run_suite`` plus OWNERSHIP-SCOPED leak observation (T01D pattern).

    Re-implemented locally from
    ``tests/test_s11_original_audio_acceptance.py::_run_suite_tracked``
    (attribution: T01D correction C2/C3).  While the child suite runs, every
    ffmpeg/ffprobe process that appears INSIDE the child's live process tree
    is recorded; survivors of that recorded set after the child exits are
    leaks attributable to THIS run only.  Dedicated reader threads drain
    stdout/stderr continuously and the whole wait is bounded by a hard total
    deadline (RC124 on expiry) — the outer+inner hang from T01D C3 can never
    recur.  Returns ``(returncode, out_tail, err_tail, seen_pids, out_full,
    err_full)`` — full captures are kept for the measured evidence files.
    """
    cmd, env = _suite_cmd_env(basetemp)
    child = subprocess.Popen(  # noqa: S603 - fixed argv list
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )

    def _drain(stream, chunks: list[str]) -> None:
        assert stream is not None
        try:
            for line in stream:
                chunks.append(line)
        finally:
            with contextlib.suppress(OSError):
                stream.close()

    out_chunks: list[str] = []
    err_chunks: list[str] = []
    with contextlib.ExitStack() as stack:
        out_thread = threading.Thread(
            target=_drain,
            args=(stack.enter_context(child.stdout), out_chunks),
            daemon=True,
        )
        err_thread = threading.Thread(
            target=_drain,
            args=(stack.enter_context(child.stderr), err_chunks),
            daemon=True,
        )
        out_thread.start()
        err_thread.start()

        seen_engine_pids: set[int] = set()
        timed_out = False
        overall_deadline = time.monotonic() + _CHILD_TOTAL_DEADLINE_S
        try:
            child_proc = psutil.Process(child.pid)
            while True:
                if child.poll() is not None:
                    break
                if time.monotonic() > overall_deadline:
                    timed_out = True
                    break
                try:
                    for desc in child_proc.children(recursive=True):
                        try:
                            if _ffmpeg_name(desc.name()):
                                seen_engine_pids.add(desc.pid)
                        except psutil.Error:  # racy teardown
                            continue
                except psutil.Error:  # child already gone
                    pass
                time.sleep(0.5)
        finally:
            # If the loop died unexpectedly the child must never be orphaned.
            if child.poll() is None and not timed_out:
                # Reached only via an unexpected exception — stop the child.
                child.kill()
                child.wait(timeout=60)

    if timed_out:
        child.kill()
    returncode = child.wait(timeout=120)
    out_thread.join(timeout=30)
    err_thread.join(timeout=30)
    if timed_out and returncode == 0:
        returncode = _TIMEOUT_RC
    out_full = "".join(out_chunks)
    err_full = "".join(err_chunks)
    err_tail = _bounded_tail(err_full)
    if timed_out:
        err_tail += (
            f"\n[harness] child killed at {_CHILD_TOTAL_DEADLINE_S}s "
            "hard total deadline"
        )
    return (
        returncode,
        _bounded_tail(out_full),
        err_tail,
        seen_engine_pids,
        out_full,
        err_full,
    )


def _pid_alive_ffmpeg(pid: int) -> bool:
    """True iff *pid* currently resolves to a live ffmpeg/ffprobe process."""
    try:
        return _ffmpeg_name(psutil.Process(pid).name())
    except psutil.Error:
        return False


@contextlib.contextmanager
def _inner_suite_lock() -> Iterator[None]:
    """Serialize the nested QC suite across concurrent acceptance runs.

    Pattern T01D gate-c correction C2: the child suite contains machine-wide
    process assertions, so this harness serializes the inner run with a
    machine-wide lock file (auto-released when the holder process dies — the
    OS releases the fd).  S11-SPRINT_CONTRACT global-gate mutex: no outer
    acceptance runs while a writer is active; the lock makes the inner run
    mutually exclusive with any other acceptance invocation.
    """
    lock_path = Path(tempfile.gettempdir()) / "s11-t06c-inner-suite.lock"
    with open(  # noqa: SIM115 - lifetime bounded by the context manager
        lock_path, "a+"
    ) as handle:
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.25)
        try:
            yield
        finally:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass


def _child_basetemp(tag: str) -> Path:
    """Short, unique child basetemp DIRECTLY under the Windows temp root.

    Pattern T01D correction C1: never chained from the outer tmp_path — long
    prefixes overflow Windows MAX_PATH once the inner suite writes its
    artifact/media/SQLite trees.  Uniqueness: pid + monotonic counter.
    """
    root = Path(tempfile.gettempdir())
    basetemp = root / f"s11t06c-{tag}-{os.getpid()}-{next(_basetemp_seq)}"
    basetemp.mkdir(parents=True, exist_ok=False)
    assert basetemp.is_dir(), f"child basetemp not created: {basetemp}"
    return basetemp


def _cleanup_basetemp(basetemp: Path) -> None:
    """Best-effort removal of exactly our own child basetemp."""
    shutil.rmtree(basetemp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Measured report / evidence helpers
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(r"^(.+?\.py)::")


def _parse_verbose_output(stdout: str) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Per-file pass/fail/error counts + summary totals from ``-v`` output.

    Each verbose line has the shape ``tests/<file>.py::<nodeid> PASSED``
    (status word may be followed by ``[ 12%]``).  Summary line is the last
    interesting line, e.g. ``=== 314 passed, 12 warnings in 123.45s ===``.
    """
    per_file: dict[str, dict[str, int]] = {}
    for line in stdout.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        rel = m.group(1).replace("\\", "/")
        status = None
        if " PASSED" in line:
            status = "passed"
        elif " FAILED" in line:
            status = "failed"
        elif " ERROR" in line:
            status = "errors"
        if status is None:
            continue
        entry = per_file.setdefault(rel, {"passed": 0, "failed": 0, "errors": 0})
        entry[status] += 1

    summary: dict[str, int] = {"passed": 0, "failed": 0, "errors": 0}
    for line in reversed(stdout.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            for key in ("passed", "failed", "error"):
                m = re.search(rf"(\d+) {key}", line)
                if m:
                    summary[key if key != "error" else "errors"] = int(m.group(1))
            break
    return per_file, summary


def _new_run_id() -> str:
    """Timestamped + pid-unique run id — never collides with a prior run."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Cached single inner run (the whole acceptance executes the suite ONCE)
# ---------------------------------------------------------------------------

_STATE: dict[str, Any] = {
    "done": False,
    "run_id": None,
    "evidence_dir": None,
    "command": [],
    "isolation": {},
    "mutex": {},
    "exit_code": None,
    "summary": {},
    "per_file": {},
    "durations": {},
    "leak": {},
    "manifests": [],
    "epic_exit": {},
}


def _manifest_expectations() -> list[dict[str, Any]]:
    """Dynamic per-manifest expectations derived from T06B golden manifests.

    NOTHING here is hard-coded: counts, codes, blocker sets and readiness
    verdicts all come from the manifest JSON + the frozen policy.
    """
    policy = load_policy()
    out: list[dict[str, Any]] = []
    for manifest in iter_manifests():
        items = manifest["expected_qc_items"]
        item_sum = sum(int(item["expected_count"]) for item in items)
        blocker_codes = sorted(
            item["reason_code"]
            for item in items
            if item.get("severity") == "blocker"
        )
        ok, reason = policy_ref_matches(manifest)
        readiness: dict[str, Any] = {}
        for label, block in manifest.get("expected_readiness", {}).items():
            readiness[label] = {
                "status": block.get("status"),
                "run_state": block.get("run_state"),
                "expected_blocker_codes": block.get("expected_blocker_codes"),
            }
        entry: dict[str, Any] = {
            "manifest_id": manifest["manifest_id"],
            "item_count": len(items),
            "expected_count_sum": item_sum,
            "expected_total_count": manifest.get("expected_total_count"),
            "expected_total_matches_sum": (
                manifest.get("expected_total_count") in (None, item_sum)
            ),
            "reason_codes": sorted({item["reason_code"] for item in items}),
            "blocker_codes": blocker_codes,
            "policy": {
                "policy_id": manifest["policy_ref"]["policy_id"],
                "policy_content_hash": manifest["policy_ref"]["policy_content_hash"],
                "hash_matches_frozen_policy": ok,
                "policy_hash_detail": reason or "ok",
                "frozen_policy_id": policy["policy_id"],
                "frozen_content_hash": policy["content_hash"],
            },
            "readiness": readiness,
        }
        if manifest["manifest_id"] == "scenario_d_targeted_rerun":
            entry["expected_rerun_scope"] = manifest.get("expected_rerun_scope")
        out.append(entry)
    return out


def _get_suite_state() -> dict[str, Any]:
    """Run the frozen suite ONCE (cached) and build the measured state.

    The evidence directory (``output/s11-t06-e2e/<run-id>/``) is created and
    the raw child stdout/stderr are persisted immediately — evidence exists
    even if a later assertion fails.
    """
    if _STATE["done"]:
        return _STATE

    _STATE["run_id"] = _new_run_id()
    evidence_dir = EVIDENCE_ROOT / _STATE["run_id"]
    assert not evidence_dir.exists(), (
        f"refusing to overwrite existing evidence run: {evidence_dir}"
    )
    evidence_dir.mkdir(parents=True, exist_ok=False)
    _STATE["evidence_dir"] = evidence_dir
    _STATE["evidence_dir_rel"] = str(
        evidence_dir.relative_to(PROJECT_ROOT)
    ).replace("\\", "/")

    missing = [f for f in S11_QC_SUITE_FILES if not (PROJECT_ROOT / f).is_file()]
    _STATE["missing_suite_files"] = missing

    started = time.monotonic()
    basetemp = _child_basetemp("suite")
    cmd, env = _suite_cmd_env(basetemp)
    _STATE["command"] = cmd
    _STATE["isolation"] = {
        "ignore": ["tests/test_integration.py"],
        "cacheprovider": "no",
        "basetemp": basetemp.as_posix().replace("\\", "/"),
        "env_strip": ["MOTIONFORGE_DATABASE_URL"],
        "recursion_guard_env": "S11_QC_ACCEPTANCE_NESTED=1",
        "verbosity": "-v",
    }
    try:
        with _inner_suite_lock() as _:
            _STATE["mutex"] = {
                "lock_file": str(
                    Path(tempfile.gettempdir()) / "s11-t06c-inner-suite.lock"
                ),
                "held_while_inner_suite": True,
            }
            suite_started = time.monotonic()
            code, out_tail, err_tail, seen, out_full, err_full = (
                _run_suite_tracked(basetemp)
            )
            inner_duration = time.monotonic() - suite_started
        _STATE["exit_code"] = code
        _STATE["durations"]["inner_suite_s"] = round(inner_duration, 3)
        _STATE["durations"]["baseline_t01d_inner_s_reference"] = (
            BASELINE_T01D_INNER_S
        )
        _STATE["durations"]["baseline_note"] = (
            "T01D measured 52 passed in 166.7s inner — reference only, "
            "NOT a hard gate (AC2)"
        )
        _STATE["stdout_tail"] = out_tail
        _STATE["stderr_tail"] = err_tail

        per_file, summary = _parse_verbose_output(out_full)
        _STATE["per_file"] = per_file
        _STATE["summary"] = summary

        # Persist raw child streams immediately (evidence logs).
        (evidence_dir / "suite_stdout.txt").write_text(
            out_full, encoding="utf-8", errors="replace"
        )
        (evidence_dir / "suite_stderr.txt").write_text(
            err_full, encoding="utf-8", errors="replace"
        )

        # Ownership-scoped leak gate: poll the seen pids for LEAK_WINDOW_S.
        leak_started = time.monotonic()
        deadline = leak_started + _LEAK_WINDOW_S
        while time.monotonic() < deadline:
            if not any(_pid_alive_ffmpeg(p) for p in seen):
                break
            time.sleep(0.25)
        survivors = {p for p in seen if _pid_alive_ffmpeg(p)}
        leak_duration = time.monotonic() - leak_started
        _STATE["leak"] = {
            "seen_pids": sorted(seen),
            "survivors": sorted(survivors),
            "window_s": _LEAK_WINDOW_S,
            "psutil_available": _PSUTIL_AVAILABLE,
            "leak_window_elapsed_s": round(leak_duration, 3),
        }
        _STATE["durations"]["leak_window_s"] = round(leak_duration, 3)
        _STATE["durations"]["total_s"] = round(time.monotonic() - started, 3)
    finally:
        _cleanup_basetemp(basetemp)

    _STATE["manifests"] = _manifest_expectations()
    _STATE["epic_exit"] = {
        "source_voice_bgm_sfx_in_sync": (
            "test_s11_t03e_audio_sync_checks.py runs green inside the "
            "one-command suite (AC3 — unchanged source audio stays in sync)"
        ),
        "scenario_d_without_full_timeline": (
            "scenario_d manifest expected_rerun_scope.rerun_target == "
            "'affected_segment_only' with ready scenes untouched — targeted "
            "rerun, no full-timeline review"
        ),
    }
    _STATE["done"] = True
    return _STATE


# ---------------------------------------------------------------------------
# Assertion ledger (persisted to assertions.json even when a test fails)
# ---------------------------------------------------------------------------

_ASSERTIONS: list[dict[str, Any]] = []


def _check(name: str, cond: bool, detail: Any = "") -> None:
    """Record one binary acceptance check, then assert it."""
    _ASSERTIONS.append(
        {
            "name": name,
            "ok": bool(cond),
            "detail": detail if detail else None,
        }
    )
    assert cond, f"{name}: {detail}"


@pytest.fixture(scope="module", autouse=True)
def _write_evidence_finalize():
    """Persist report.json + assertions.json under the run-id evidence dir.

    Teardown runs even when an inner assertion fails, so the measured report
    and the full assertion ledger always land in ``output/s11-t06-e2e`` (AC2
    + assertion dumps JSON).
    """
    yield
    if not _STATE.get("done"):
        return
    evidence_dir = _STATE["evidence_dir"]
    assert evidence_dir is not None and evidence_dir.is_dir()
    report = {
        "task": "S11-T06C",
        "schema_version": 1,
        "run_id": _STATE["run_id"],
        "evidence_dir": _STATE["evidence_dir_rel"],
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": _STATE["command"],
        "isolation": _STATE["isolation"],
        "mutex": _STATE["mutex"],
        "suite": {
            "files": list(S11_QC_SUITE_FILES),
            "file_count": len(S11_QC_SUITE_FILES),
            "missing_suite_files": _STATE.get("missing_suite_files", []),
        },
        "result": {
            "exit_code": _STATE["exit_code"],
            "summary": _STATE["summary"],
            "stdout_tail": _STATE.get("stdout_tail"),
            "stderr_tail": _STATE.get("stderr_tail"),
        },
        "per_file": [
            {
                "file": rel,
                **{"passed": 0, "failed": 0, "errors": 0},
                **(_STATE["per_file"].get(rel, {})),
            }
            for rel in S11_QC_SUITE_FILES
        ],
        "durations": _STATE["durations"],
        "leak_gate": _STATE["leak"],
        "manifests": _STATE["manifests"],
        "epic_exit": _STATE["epic_exit"],
        "assertions": {
            "total": len(_ASSERTIONS),
            "ok": sum(1 for a in _ASSERTIONS if a["ok"]),
            "failed": sum(1 for a in _ASSERTIONS if not a["ok"]),
            "entries": _ASSERTIONS,
        },
    }
    _write_json(evidence_dir / "report.json", report)
    _write_json(
        evidence_dir / "assertions.json",
        {
            "run_id": _STATE["run_id"],
            "assertions": _ASSERTIONS,
            "all_ok": all(a["ok"] for a in _ASSERTIONS),
        },
    )


# ---------------------------------------------------------------------------
# The acceptance tests (binary)
# ---------------------------------------------------------------------------


def test_t01_suite_files_all_exist() -> None:
    """Guards the frozen file list itself before anything runs."""
    missing = [f for f in S11_QC_SUITE_FILES if not (PROJECT_ROOT / f).is_file()]
    _check(
        "S11-T06C-00-suite-files-exist",
        not missing,
        f"missing suite files: {missing}",
    )


def test_t02_one_command_suite_green() -> None:
    """AC1: ONE command, exit 0, summary line without failed/error.

    Env-stripped child (no MOTIONFORGE_DATABASE_URL), --ignore
    tests/test_integration.py, -p no:cacheprovider, short unique basetemp.
    """
    state = _get_suite_state()
    _check(
        "S11-T06C-01-one-command-exit-0",
        state["exit_code"] == 0,
        (
            f"exit_code={state['exit_code']} (RC124={_TIMEOUT_RC} means the "
            f"harness hit its {_CHILD_TOTAL_DEADLINE_S}s hard deadline)\n"
            f"--- stdout tail ---\n{state.get('stdout_tail')}\n"
            f"--- stderr tail ---\n{state.get('stderr_tail')}"
        ),
    )
    summary = state["summary"]
    _check(
        "S11-T06C-02-summary-no-failed-error",
        summary["failed"] == 0 and summary["errors"] == 0,
        f"summary={summary}",
    )
    _check(
        "S11-T06C-03-summary-positive-passed",
        summary["passed"] > 0,
        f"summary={summary}",
    )


def test_t03_measured_report_per_file_counts() -> None:
    """AC2: per-file pass/fail counts for EVERY suite file, all measured.

    Every one of the 20 frozen files must have contributed >= 1 passing test
    (a fully-skipped slice would fail the acceptance) and zero failures or
    errors; the parsed per-file totals must reconcile with the summary.
    """
    state = _get_suite_state()
    per_file = state["per_file"]
    _check(
        "S11-T06C-04-per-file-entry-every-file",
        set(per_file) == set(S11_QC_SUITE_FILES),
        f"per-file entries missing/extra: "
        f"{sorted(set(S11_QC_SUITE_FILES) ^ set(per_file))}",
    )
    for rel in S11_QC_SUITE_FILES:
        entry = per_file.get(rel, {})
        _check(
            f"S11-T06C-05-per-file-passed-{rel}",
            entry.get("passed", 0) >= 1,
            f"{rel}: entry={entry}",
        )
        _check(
            f"S11-T06C-06-per-file-zero-failures-{rel}",
            entry.get("failed", 0) == 0 and entry.get("errors", 0) == 0,
            f"{rel}: entry={entry}",
        )
    measured_total = sum(e["passed"] for e in per_file.values())
    _check(
        "S11-T06C-07-per-file-total-reconciles-summary",
        measured_total == state["summary"]["passed"],
        f"per-file sum={measured_total} vs summary={state['summary']}",
    )
    _check(
        "S11-T06C-08-durations-recorded",
        state["durations"].get("inner_suite_s", 0) > 0
        and state["durations"].get("leak_window_s", 0) >= 0
        and state["durations"].get("total_s", 0) > 0,
        f"durations={state['durations']}",
    )


def test_t04_dynamic_golden_manifest_counts_policy_hash() -> None:
    """AC1 dynamic counts: every golden manifest is consumed by reference.

    No hard-coded counts anywhere: policy hash must equal the frozen T03A
    policy content hash, schema must validate, and each manifest's
    ``expected_total_count`` (when present) must equal the sum of its item
    ``expected_count`` values.
    """
    violations = validate_all()
    _check(
        "S11-T06C-09-manifests-schema-valid",
        not violations,
        violations,
    )
    policy = load_policy()
    _check(
        "S11-T06C-10-frozen-policy-id",
        policy["policy_id"] == "s11-qc-thresholds-v1",
        policy["policy_id"],
    )
    for manifest in iter_manifests():
        mid = manifest["manifest_id"]
        ok, reason = policy_ref_matches(manifest)
        _check(
            f"S11-T06C-11-policy-hash-{mid}",
            ok,
            f"{reason}",
        )
        item_sum = sum(int(i["expected_count"]) for i in manifest["expected_qc_items"])
        declared = manifest.get("expected_total_count")
        _check(
            f"S11-T06C-12-total-count-dynamic-{mid}",
            declared in (None, item_sum),
            f"declared={declared} item_sum={item_sum}",
        )


def test_t05_e2e_01_full_envelope_dynamic() -> None:
    """e2e_01 covers the full 10-code binding envelope (dynamic)."""
    manifest = iter_manifests()[GOLDEN_MANIFESTS.index("e2e_01_vertical_review")]
    codes = {i["reason_code"] for i in manifest["expected_qc_items"]}
    _check(
        "S11-T06C-13-e2e01-full-envelope",
        codes == set(QC_REASON_CODES),
        f"missing codes: {sorted(set(QC_REASON_CODES) - codes)}",
    )
    _check(
        "S11-T06C-14-e2e01-total-matches-envelope",
        manifest.get("expected_total_count") == len(QC_REASON_CODES),
        f"expected_total_count={manifest.get('expected_total_count')} "
        f"envelope={len(QC_REASON_CODES)}",
    )
    after = manifest["expected_readiness"]["after"]
    _check(
        "S11-T06C-15-e2e01-readiness-after",
        after["status"] == "ready" and after["run_state"] == "completed",
        after,
    )


def test_t06_e2e_02_readiness_flip_ready_after_fix() -> None:
    """AC3/readiness flip: blocked -> ready once resolved with fresh evidence.

    Blockers are derived dynamically from the manifest's item severities.
    """
    manifest = iter_manifests()[GOLDEN_MANIFESTS.index("e2e_02_blocker_readiness")]
    blockers = sorted(
        i["reason_code"]
        for i in manifest["expected_qc_items"]
        if i["severity"] == "blocker"
    )
    after = manifest["expected_readiness"]["after"]
    after_resolve = manifest["expected_readiness"]["after_resolve"]
    _check(
        "S11-T06C-16-e2e02-blocked-codes-dynamic",
        after["status"] == "blocked"
        and sorted(after.get("expected_blocker_codes", [])) == blockers,
        f"blocked={after} dynamic blockers={blockers}",
    )
    _check(
        "S11-T06C-17-e2e02-flip-ready-after-fix",
        after_resolve["status"] == "ready"
        and after_resolve["run_state"] == "completed"
        and after_resolve.get("expected_blocker_codes") == [],
        after_resolve,
    )


def test_t07_scenario_d_no_full_timeline() -> None:
    """AC3 Scenario D: targeted rerun, ready scenes untouched — NO full
    timeline review/re-render (epic exit L235)."""
    manifest = iter_manifests()[GOLDEN_MANIFESTS.index("scenario_d_targeted_rerun")]
    rerun = manifest.get("expected_rerun_scope", {})
    _check(
        "S11-T06C-18-scenarioD-targeted-rerun",
        rerun.get("rerun_target") == "affected_segment_only",
        rerun,
    )
    _check(
        "S11-T06C-19-scenarioD-ready-scenes-unchanged",
        "ready_scenes" in str(rerun.get("unchanged", "")),
        rerun.get("unchanged"),
    )
    after_rerun = manifest["expected_readiness"].get("after_rerun", {})
    _check(
        "S11-T06C-20-scenarioD-after-rerun-ready",
        after_rerun.get("status") == "ready"
        and after_rerun.get("run_state") == "completed",
        after_rerun,
    )


def test_t08_restart_resume_recompute_sanity() -> None:
    """T01D scenario-5 pattern: restart/resume sanity between recompute runs.

    The recompute restart-resume slice of the wave is
    ``test_s11_t04b_correction_rerun.py`` + ``test_s11_t04b_stale_reopen.py``
    (resume never duplicates resolution; terminal states never reopen).  The
    per-file measured report must show both files green — derived dynamically
    from the suite list, never a hard-coded count.
    """
    state = _get_suite_state()
    rerun_slice = [f for f in S11_QC_SUITE_FILES if "t04b" in f]
    _check("S11-T06C-21a-restart-resume-slice-present", bool(rerun_slice), rerun_slice)
    for rel in rerun_slice:
        entry = state["per_file"].get(rel, {})
        _check(
            f"S11-T06C-21-restart-resume-{rel}",
            entry.get("passed", 0) >= 1 and entry.get("failed", 0) == 0,
            f"{rel}: entry={entry}",
        )


def test_t09_audio_sync_source_unchanged_covered() -> None:
    """AC3 epic exit: voice/BGM/SFX stay in sync (T03E slice green)."""
    state = _get_suite_state()
    audio_slice = [f for f in S11_QC_SUITE_FILES if "t03e" in f]
    _check("S11-T06C-22-audio-sync-slice-present", bool(audio_slice), audio_slice)
    for rel in audio_slice:
        entry = state["per_file"].get(rel, {})
        _check(
            f"S11-T06C-23-audio-sync-green-{rel}",
            entry.get("passed", 0) >= 1 and entry.get("failed", 0) == 0,
            f"{rel}: entry={entry}",
        )


def test_t10_leak_gate_survivors_empty() -> None:
    """AC2 leak gate: zero ffmpeg/ffprobe survivors after the suite, within
    the 15 s ownership-scoped window (T01D scenario 10 pattern)."""
    if not _PSUTIL_AVAILABLE:
        pytest.skip("psutil unavailable — ownership-scoped leak scan needs it")
    state = _get_suite_state()
    leak = state["leak"]
    _check(
        "S11-T06C-24-leak-gate-survivors-empty",
        not leak["survivors"],
        (
            f"ffmpeg/ffprobe processes leaked after the full S11-T02..T05 "
            f"suite (ownership-scoped pids): {leak['survivors']}\n"
            f"seen={leak['seen_pids']}\n"
            f"--- stdout tail ---\n{state.get('stdout_tail')}\n"
            f"--- stderr tail ---\n{state.get('stderr_tail')}"
        ),
    )
    _check(
        "S11-T06C-25-leak-gate-window-recorded",
        leak["window_s"] == _LEAK_WINDOW_S and leak["leak_window_elapsed_s"] >= 0,
        leak,
    )


# ---------------------------------------------------------------------------
# S11-C1 lane C1-B — executable restart/resume epic-exit proof (Codex P1)
# ---------------------------------------------------------------------------
#
# Codex verdict S11_T02_T06_PM_REVIEW_2026-09-04 §[P1]: the W14 row above was
# manifest + proxy proof — it read golden JSON and trusted other files' pass
# counts.  This executable scenario replaces that with a REAL stack run on a
# FRESH temp DB + NEW managed root (Alembic head, env DB strip):
#
#   seed (project/video/QC blocker) -> submit recompute via the REAL
#   correction path -> JobService/worker teardown mid-flight
#   (process boundary) -> recreate the service against the SAME durable DB
#   + SAME managed root -> resume the persisted job -> bounded poll to
#   terminal -> prove exactly ONE successor/effect (no duplicate correction
#   resolution, no duplicate enqueue), affected-only artifacts, and stable
#   readiness after re-query from a FRESH session/repository.
#
# The Scenario D executable assertion node is the REAL bridge + REAL
# recompute handler + REAL `run_full_check_set` recheck — no golden JSON
# string search in this test (t07 keeps the manifest contract as coverage;
# this test is the executable proof).


def _c1b_alembic_head(db_path: Path) -> None:
    """Upgrade a fresh temp DB to the production Alembic head (T03G pattern)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")


def _c1b_make_service(
    session_factory: Any, managed_root: Path
) -> Any:
    """Build the production JobService on EXISTING durable roots (no client).

    The RECOMPUTE_OBJECTS handler registration rides inside the default
    JobService worker construction (the bounded job_service.py block), so a
    recreate with worker=None is the same production path — the worker
    belongs to the NEW service instance, the DB rows belong to the durable
    file.  Clock/sleeper stay REAL (no fake timing in restart proof).
    """
    from app.workflow.job_service import JobService

    return JobService(session_factory, managed_root=managed_root)


def _c1b_seed_video(session: Any, *, video_id: str) -> None:
    session.execute(
        __import__("sqlalchemy").text(
            "INSERT INTO workspace(id, name) VALUES (:w, :w) "
            "ON CONFLICT(id) DO NOTHING"
        ),
        {"w": _C1B_WS},
    )
    session.execute(
        __import__("sqlalchemy").text(
            "INSERT INTO project(id, workspace_id, name, description, status) "
            "VALUES (:p, :w, :p, '', 'active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": _C1B_PROJECT, "w": _C1B_WS},
    )
    session.execute(
        __import__("sqlalchemy").text(
            "INSERT INTO video_item(id, project_id, title, position, status) "
            "VALUES (:v, :p, :v, "
            "(SELECT COALESCE(MAX(position),0)+1 FROM video_item "
            "WHERE project_id=:p), 'imported') ON CONFLICT(id) DO NOTHING"
        ),
        {"v": video_id, "p": _C1B_PROJECT},
    )
    session.commit()


def _c1b_poll_terminal(
    session_factory: Any, job_id: str, worker: Any
) -> dict[str, Any]:
    """Bounded resume poll: run_once until the persisted job is terminal.

    Deadline + poll interval are finite (requirement 3).  Returns the
    evidence snapshot (state, attempts with results, steps).
    """
    from app.persistence.jobs import JobRepository

    deadline = time.monotonic() + _C1B_RESTART_POLL_DEADLINE_S
    last_state = "unknown"
    while time.monotonic() < deadline:
        worker.run_once()
        with session_factory() as session:
            repo = JobRepository(session)
            record = repo.get_job(job_id)
            last_state = record.state
            if last_state in ("completed", "failed", "cancelled"):
                attempts = [
                    {
                        "result": a.result,
                        "error": a.error,
                    }
                    for a in repo.list_attempts(job_id)
                ]
                steps = [
                    {"state": s.state, "attempt": s.attempt}
                    for s in repo.list_steps(job_id)
                ]
                return {
                    "state": last_state,
                    "attempts": attempts,
                    "steps": steps,
                }
        time.sleep(_C1B_RESTART_POLL_INTERVAL_S)
    raise AssertionError(
        f"C1B restart poll timed out after {_C1B_RESTART_POLL_DEADLINE_S}s; "
        f"last state={last_state!r} job={job_id}"
    )


def test_t11_executable_restart_resume_epic_exit() -> None:
    """S11-C1 C1-B: executable restart/resume over the REAL correction stack.

    Fresh temp DB (Alembic head) + new temp managed root; the scenario
    enqueues a REAL RUN_QC_CHECKS recompute through the T03G submit
    authority, drops the service/worker mid-flight (process-boundary
    equivalent: teardown + GC), recreates the production JobService against
    the SAME durable DB + SAME managed root, resumes the persisted job with
    a bounded poll, and proves: exactly one successor/effect, no duplicate
    enqueue/resolution, affected-only artifacts, and readiness stable after
    re-query from a fresh repository session.
    """
    import uuid

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.jobs import JobRepository
    from app.persistence.qc_check_runs import check_run_readiness
    from app.persistence.qc_items import QCItemRepository
    from app.services.qc_checks import (  # noqa: F401  (self-register band)
        audio_missing,
        av_sync_drift,
        cut_drift,
        edge_halo,
        identity_drift,
        temporal_flicker,
        trajectory_drift,
    )
    from app.services.qc_checks import contact_break as _c1b_cb
    from app.services.qc_checks import silhouette_clipping as _c1b_sc
    from app.services.qc_checks import z_order_error as _c1b_zo
    from app.services.qc_checks.registry import registry
    from app.services.timebase import CanonicalTimebase
    from app.workflow.qc_checks_handler import (
        SCOPE_FULL,
        evidence_fingerprint,
        policy_bundle,
        scope_detectors,
        submit_run_qc_checks,
    )
    from s11_qc_calibration_builders import generate_trajectory_drift_input

    _c1b_cb.register()
    _c1b_sc.register()
    _c1b_zo.register()
    for name, entry_point in (
        ("audio_missing", "app.services.qc_checks.audio_missing:detect"),
        ("av_sync_drift", "app.services.qc_checks.av_sync_drift:detect"),
        ("trajectory_drift", "app.services.qc_checks.trajectory_drift:detect"),
        ("cut_drift", "app.services.qc_checks.cut_drift:detect"),
        ("contact_break", "app.services.qc_checks.contact_break:detect_contact_break"),
        (
            "z_order_error",
            "app.services.qc_checks.z_order_error:detect_z_order_error",
        ),
        (
            "silhouette_clipping",
            "app.services.qc_checks.silhouette_clipping:detect_silhouette_clipping",
        ),
        ("identity_drift", "app.services.qc_checks.identity_drift:detect"),
        ("edge_halo", "app.services.qc_checks.edge_halo:detect"),
        ("temporal_flicker", "app.services.qc_checks.temporal_flicker:detect"),
    ):
        registry.register(name, entry_point)

    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    scratch = Path(tempfile.mkdtemp(prefix="s11c1b_"))
    db_path = scratch / "c1b.db"
    managed_root = scratch / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    _c1b_alembic_head(db_path)
    session_factory = create_session_factory(create_engine_for_path(db_path))

    video_id = str(uuid.uuid4())
    with session_factory() as session:
        _c1b_seed_video(session, video_id=video_id)

    # The REAL terminal-fact envelope: source HAS audio but the expected
    # output publish is missing → audio_missing blocker (FAILURE_OUTPUT_MISSING)
    # + av_sync_drift blocker — the same envelope the T03G suite proves
    # creates items exactly once (AC5).  Executable assertion node #1: the
    # submit authority itself (fail-closed idempotency carried by the rows).
    envelope = {
        "checkpoint": {
            "schema_version": 1,
            "status": "STREAM_COPY",
            "mode": "stream_copy",
            "source_sha256": "c" * 64,
            "source_size_bytes": 2048,
            "source_audio_codec": "aac",
            "source_audio_duration": "2.000000",
            "output_audio_codec": None,
            "output_audio_duration": None,
            "audio_time_base": "1/48000",
            "video_codec": "h264",
        },
        "published": None,
    }
    # S11-C1 follow-on (INT01/C2 pattern, commit 3beee0d): the seed must
    # be FULL-scope — an AUDIO run never passes the C1-A full-run authority
    # gate (newest FULL-scope + 6 DK in qc_check_runs.py), so readiness
    # would stay not_run/never_run instead of blocked.  Visual args use the
    # T03F pass-band helpers (pure computation, no media needed); the audio
    # envelope keeps the REAL terminal-fact issue (source HAS audio, output
    # publish missing -> audio_missing blocker).  The band is derived via
    # scope_detectors(SCOPE_FULL) — NEVER a hard-coded detector list.
    import hashlib as _c1b_hashlib
    import json as _c1b_json
    import math as _c1b_math

    _c1b_tb = CanonicalTimebase.from_rational(30, 1, nb_frames=120)
    _c1b_traj_inp = generate_trajectory_drift_input(
        seed=11001, drift_px_per_frame=0.2, frames=64
    )
    _c1b_win = {"start_frame": 0, "end_frame": 47}
    _c1b_w = _c1b_win["end_frame"] - _c1b_win["start_frame"] + 1
    _c1b_seg_a = {
        "id": "seg-a",
        "logical_id": "L-seg-a",
        "z_order": 10,
        "start_frame": 0,
        "end_frame": 47,
        "bbox_per_frame": [[10.0, 10.0, 40.0, 20.0]] * _c1b_w,
        "bbox": None,
    }
    _c1b_seg_b = {
        "id": "seg-b",
        "logical_id": "L-seg-b",
        "z_order": 20,
        "start_frame": 0,
        "end_frame": 47,
        "bbox_per_frame": [[10.0, 10.0, 40.0, 20.0]] * _c1b_w,
        "bbox": None,
    }
    _c1b_ref_px = [[100] * 8 for _ in range(8)]
    _c1b_ref_raw = _c1b_json.dumps(
        _c1b_ref_px, separators=(",", ":")
    ).encode("utf-8")
    _c1b_ref_sha = _c1b_hashlib.sha256(_c1b_ref_raw).hexdigest()
    _c1b_grid = 64
    _c1b_inner = 20.0
    _c1b_ctr = _c1b_grid / 2.0
    _c1b_disc = [
        [
            1
            if _c1b_math.sqrt((x - _c1b_ctr) ** 2 + (y - _c1b_ctr) ** 2)
            < _c1b_inner
            else 0
            for x in range(_c1b_grid)
        ]
        for y in range(_c1b_grid)
    ]
    _c1b_disc_raw = _c1b_json.dumps(
        _c1b_disc, separators=(",", ":")
    ).encode("utf-8")
    _c1b_disc_sha = _c1b_hashlib.sha256(_c1b_disc_raw).hexdigest()
    _c1b_full_args = {
        "trajectory_drift": {
            "workspace_id": _C1B_WS,
            "project_id": _C1B_PROJECT,
            "video_item_id": video_id,
            "layer_ref_type": "video_item",
            "layer_ref_id": video_id,
            "reference_x": [float(v) for v in _c1b_traj_inp["reference_x"]],
            "observed_x": [float(v) for v in _c1b_traj_inp["drifted_x"]],
            "frame_start": 0,
            "checkpoint_ref": "s11-c1b-traj",
        },
        "cut_drift": {
            "workspace_id": _C1B_WS,
            "project_id": _C1B_PROJECT,
            "video_item_id": video_id,
            "layer_ref_type": "video_item",
            "layer_ref_id": video_id,
            "timebase": _c1b_tb.to_json(),
            "scene_boundaries": [{"position": 1, "start_frame": 60}],
            "render_cuts_ms": [2000],
            "checkpoint_ref": "s11-c1b-cut",
        },
        "contact_break": {
            "contacts": [
                {
                    "id": "contact-seg-a-seg-b",
                    "source_segment_id": "seg-a",
                    "target_segment_id": "seg-b",
                    "contact_kind": "touch",
                    "start_frame": 0,
                    "end_frame": 47,
                    "confidence": 0.98,
                    "confidence_source": "derived",
                }
            ],
            "segments": [_c1b_seg_a, _c1b_seg_b],
            "analysis_window": dict(_c1b_win),
            "checkpoint_ref": "s11-c1b-contact",
        },
        "z_order_error": {
            "segments": [
                {
                    "id": f"s{i}",
                    "logical_id": f"L-s{i}",
                    "z_order": 3 - i,
                    "start_frame": 0,
                    "end_frame": 47,
                    "bbox_per_frame": None,
                    "bbox": None,
                }
                for i in range(3)
            ],
            "occlusion_edges": [
                {
                    "id": f"occ-s{i}-s{i + 1}",
                    "occluder_segment_id": f"s{i}",
                    "occludee_segment_id": f"s{i + 1}",
                    "start_frame": 0,
                    "end_frame": 47,
                    "confidence": 0.99,
                    "confidence_source": "derived",
                }
                for i in range(2)
            ],
            "analysis_window": dict(_c1b_win),
            "render_order": None,
            "lock_manifest": None,
            "checkpoint_ref": "s11-c1b-zorder",
        },
        "silhouette_clipping": {
            "segments": [
                {
                    "id": "seg-a",
                    "logical_id": "L-seg-a",
                    "z_order": 10,
                    "start_frame": 0,
                    "end_frame": 47,
                    "bbox_per_frame": None,
                    "bbox": [5.0, 5.0, 95.0, 95.0],
                }
            ],
            "frame": {"width": 100.0, "height": 100.0},
            "analysis_window": dict(_c1b_win),
            "checkpoint_ref": "s11-c1b-clip",
        },
        "identity_drift": {
            "workspace_id": _C1B_WS,
            "project_id": _C1B_PROJECT,
            "video_item_id": video_id,
            "layer_ref_type": "video_item",
            "layer_ref_id": video_id,
            "checkpoint_ref": "s11-c1b-identity",
            "segment_row_id": None,
            "segment_logical_id": None,
            "pinned_reference": {
                "artifact_id": "art-ref",
                "sha256": _c1b_ref_sha,
                "crop_revision": "1.0.0",
                "crop": {"width": 8, "height": 8, "pixels": _c1b_ref_px},
            },
            "cast_pin": {
                "object_role_id": "role-pinned",
                "character_id": "char-1",
                "pack_version_id": "pack-1",
                "revision": 1,
                "expected_metadata": {
                    "role_id": "role-pinned",
                    "instance_id": "inst-pinned",
                    "cast_pin_ref": "cast-pin-1",
                },
                "compatible": True,
                "compatibility_reasons": [],
            },
            "frames": [
                {
                    "frame_index": 0,
                    "artifact_id": "art-id-0",
                    "sha256": _c1b_ref_sha,
                    "crop": {"width": 8, "height": 8, "pixels": _c1b_ref_px},
                    "metadata": {
                        "role_id": "role-pinned",
                        "instance_id": "inst-pinned",
                        "cast_pin_ref": "cast-pin-1",
                    },
                }
            ],
        },
        "edge_halo": {
            "workspace_id": _C1B_WS,
            "project_id": _C1B_PROJECT,
            "video_item_id": video_id,
            "layer_ref_type": "video_item",
            "layer_ref_id": video_id,
            "checkpoint_ref": "s11-c1b-halo",
            "frame_index": 10,
            "mask_revision": "2.1.0",
            "inner_radius_px": _c1b_inner,
            "rendered": {
                "artifact_id": "art-rendered-halo",
                "sha256": _c1b_disc_sha,
                "mask": {
                    "width": _c1b_grid,
                    "height": _c1b_grid,
                    "pixels": _c1b_disc,
                },
            },
            "expected": {
                "artifact_id": "art-expected-mask",
                "sha256": _c1b_disc_sha,
                "mask": {
                    "width": _c1b_grid,
                    "height": _c1b_grid,
                    "pixels": _c1b_disc,
                },
            },
        },
        "temporal_flicker": {
            "workspace_id": _C1B_WS,
            "project_id": _C1B_PROJECT,
            "video_item_id": video_id,
            "layer_ref_type": "video_item",
            "layer_ref_id": video_id,
            "checkpoint_ref": "s11-c1b-flicker",
            "window": {"start_frame": 0, "end_frame": 127},
            "luminance": [100.0] * 128,
        },
        "audio_missing": {
            "checkpoint": envelope["checkpoint"],
            "published": envelope.get("published"),
            "error": None,
            "checkpoint_ref": "s11-c1b",
        },
        "av_sync_drift": {
            "checkpoint": envelope["checkpoint"],
            "scene_timeline": {"duration_seconds": 2.0},
            "published": envelope.get("published"),
            "checkpoint_ref": "s11-c1b",
        },
    }
    _c1b_band = scope_detectors(SCOPE_FULL)
    assert set(_c1b_band) == set(_c1b_full_args), (
        f"FULL band drift: band={sorted(_c1b_band)} "
        f"args={sorted(_c1b_full_args)}"
    )
    detector_args = {name: _c1b_full_args[name] for name in _c1b_band}
    first = submit_run_qc_checks(
        session_factory,
        workspace_id=_C1B_WS,
        project_id=_C1B_PROJECT,
        video_item_id=video_id,
        scope=SCOPE_FULL,
        detector_args=detector_args,
        generation="1",
    )
    job_id = first.job_id
    with session_factory() as session:
        queued = JobRepository(session).get_job(job_id)
        _check(
            "S11-C1B-01-submit-enqueued-persisted",
            queued.state == "queued",
            f"job={job_id} state={queued.state}",
        )

    # Stop/recreate: drop the FIRST service + worker (process boundary),
    # then build a SECOND production service against the SAME durable DB +
    # SAME managed root.  The persisted job row must survive the restart.
    svc1 = _c1b_make_service(session_factory, managed_root)
    assert svc1.worker is not None
    svc1.stop_worker(timeout=2.0)
    del svc1

    svc2 = _c1b_make_service(session_factory, managed_root)
    assert svc2.worker is not None

    snapshot = _c1b_poll_terminal(session_factory, job_id, svc2.worker)
    try:
        _check(
            "S11-C1B-02-resumed-to-terminal-completed",
            snapshot["state"] == "completed",
            f"job={job_id} state={snapshot['state']}",
        )
        results = [a["result"] for a in snapshot["attempts"] if a["result"]]
        _check(
            "S11-C1B-03-exactly-one-successor-effect",
            len(results) == 1 and results[0].get("completed") is True,
            f"results={len(results)}",
        )
        run_ids = [r.get("run_id") for r in results]
        _check(
            "S11-C1B-04-single-deterministic-run-id",
            len(set(run_ids)) == 1 and len((run_ids[0] or "")) == 64,
            run_ids,
        )

        with session_factory() as session:
            rows, _total = QCItemRepository(session).list(
                _C1B_WS, video_item_id=video_id, limit=10000
            )
            keys = [r.evidence_window_key for r in rows]
            severities = sorted({r.severity for r in rows})
            blockers = [r for r in rows if r.severity == "blocker"]
        _check(
            "S11-C1B-05-blocker-issue-created-once",
            len(blockers) >= 1,
            f"severities={severities} total={len(rows)}",
        )
        _check(
            "S11-C1B-06-no-duplicate-natural-keys",
            len(set(keys)) == len(keys) and len(rows) >= 1,
            f"total={len(rows)} unique_keys={len(set(keys))}",
        )

        # Duplicate ACTIVE submit while queued/completed reuses — never a
        # second effect: completed duplicate reuses the SAME job row.
        second = submit_run_qc_checks(
            session_factory,
            workspace_id=_C1B_WS,
            project_id=_C1B_PROJECT,
            video_item_id=video_id,
            scope=SCOPE_FULL,
            detector_args=detector_args,
            generation="1",
        )
        _check(
            "S11-C1B-07-completed-duplicate-reuses-same-job",
            getattr(second, "reused", False) is True
            and second.job_id == job_id,
            f"reused={getattr(second, 'reused', None)} "
            f"job={second.job_id} vs {job_id}",
        )
        with session_factory() as session:
            rows_after, _ = QCItemRepository(session).list(
                _C1B_WS, video_item_id=video_id, limit=10000
            )
        _check(
            "S11-C1B-08-no-duplicate-resolution-after-restart",
            len(rows_after) == len(rows),
            f"before={len(rows)} after={len(rows_after)}",
        )

        # Readiness stable after re-query from a FRESH repository session:
        # completed current run with open blockers -> blocked (honest), and
        # the row set is unchanged across sessions (requirement 6).
        with session_factory() as fresh:
            fp = evidence_fingerprint(
                fresh, workspace_id=_C1B_WS, video_item_id=video_id
            )
            ready = check_run_readiness(
                fresh,
                workspace_id=_C1B_WS,
                project_id=_C1B_PROJECT,
                video_item_id=video_id,
                evidence_fingerprint=fp,
                policy_content_hash=policy_bundle()["policy_content_hash"],
            )
            ready_again = check_run_readiness(
                fresh,
                workspace_id=_C1B_WS,
                project_id=_C1B_PROJECT,
                video_item_id=video_id,
                evidence_fingerprint=fp,
                policy_content_hash=policy_bundle()["policy_content_hash"],
            )
        _check(
            "S11-C1B-09-readiness-blocked-with-open-blockers",
            ready.status == "blocked" and ready.run_state == "completed",
            f"status={ready.status} run_state={ready.run_state}",
        )
        _check(
            "S11-C1B-10-readiness-stable-across-fresh-queries",
            (ready.status, ready.run_state, ready.blockers)
            == (ready_again.status, ready_again.run_state, ready_again.blockers),
            f"first={(ready.status, ready.run_state, ready.blockers)} "
            f"second={(ready_again.status, ready_again.run_state, ready_again.blockers)}",
        )
    finally:
        # External lane evidence (allowlist path, outside the worktree diff).
        _C1B_EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
        lane_payload = {
            "lane": "c1b-t06c",
            "run_tag": run_tag,
            "job_id": job_id,
            "video_item_id": video_id,
            "db_path": str(db_path),
            "managed_root": str(managed_root),
            "terminal": snapshot,
            "assertions": [
                a for a in _ASSERTIONS if a["name"].startswith("S11-C1B-")
            ],
            "all_ok": all(
                a["ok"] for a in _ASSERTIONS if a["name"].startswith("S11-C1B-")
            ),
        }
        _write_json(_C1B_EVIDENCE_ROOT / f"c1b_restart_proof_{run_tag}.json", lane_payload)
        svc2.stop_worker(timeout=2.0)
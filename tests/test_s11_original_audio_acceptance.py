"""S11-T01D — Acceptance suite (TASK.md required scenarios 9-10).

Scenario 9 — ``test_a01_full_s11_suite_green``: the WHOLE S11 acceptance
suite runs green as ONE pytest invocation (contract + remux + attach +
integration + acceptance), excluding only the SAM2-segfault file
``tests/test_integration.py``.  The suite command is the frozen acceptance
command recorded in the packet evidence::

    python -m pytest tests/test_s11_original_audio_contract.py \\
        tests/test_s11_original_audio_remux.py \\
        tests/test_s11_attach_original_audio_job.py \\
        tests/test_s11_original_audio_integration.py \\
        tests/test_s11_original_audio_acceptance.py \\
        -p no:cacheprovider --basetemp=<Windows-native temp> \\
        -q

    (invoked with ``env -u MOTIONFORGE_DATABASE_URL``)

Scenario 10 — ``test_a02_no_process_leak_after_suite``: after the full S11
suite has run, NO ffmpeg/ffprobe process survives.  OWNERSHIP-SCOPED
(correction C2): only engine processes observed inside the child suite's
live process tree are attributed to this run, so concurrent acceptance
invocations on the same machine can never contaminate each other's verdict
(psutil required; skipped cleanly when unavailable).

The in-process subprocess invocation uses the SAME interpreter and repo;
the child ``--basetemp`` is short, unique (pid + sequence) and created
directly under the Windows temp root (correction C1: never chained from
the outer tmp_path — long prefixes overflow MAX_PATH), and is removed
best-effort in a ``finally`` block.
"""

from __future__ import annotations

import contextlib
import itertools
import msvcrt
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

#: Recursion guard: the frozen scenario-9 command INCLUDES this acceptance
#: file, and these tests themselves invoke that command as a subprocess.
#: The nested (inner) invocation therefore skips THIS module at collection —
#: exactly one nesting level, no exponential subprocess fan-out.
if os.environ.get("S11_ACCEPTANCE_NESTED") == "1":
    pytest.skip(
        "nested S11 acceptance run (recursion guard)",
        allow_module_level=True,
    )

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Monotonic per-process sequence for unique child basetemp directory names.
_basetemp_seq = itertools.count()

#: The five S11 files — the complete T01 slice surface, run as ONE command.
S11_SUITE_FILES = (
    "tests/test_s11_original_audio_contract.py",
    "tests/test_s11_original_audio_remux.py",
    "tests/test_s11_attach_original_audio_job.py",
    "tests/test_s11_original_audio_integration.py",
    "tests/test_s11_original_audio_acceptance.py",
)

#: HARD TOTAL DEADLINE (correction C3) for the nested child suite in
#: ``_run_suite_tracked``.  The child normally finishes in ~2-3 minutes;
#: if it is still alive after this long it is killed — an outer+inner hang
#: (Manager evidence: 80+ minutes with py-spy showing the child idle in
#: _pytest console_main) can never happen again.
_CHILD_TOTAL_DEADLINE_S = 1800

#: Synthetic return code used when the hard total deadline fired.
_TIMEOUT_RC = 124


def _ffmpeg_available() -> bool:
    try:
        from app.services.ffmpeg_utils import find_ffprobe

        find_ffprobe()
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)


def _bounded_tail(text: str | None, lines: int = 25) -> str:
    """Bounded diagnostic tail (never floods the assertion message)."""
    return "\n".join((text or "").splitlines()[-lines:])


def _suite_cmd_env(basetemp: Path) -> tuple[list[str], dict[str, str]]:
    """The FROZEN five-file S11 command + sanitized child env."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *S11_SUITE_FILES,
        "--ignore=tests/test_integration.py",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp.as_posix()}",
        "-q",
    ]
    env = {
        k: v for k, v in os.environ.items() if k != "MOTIONFORGE_DATABASE_URL"
    }
    env["S11_ACCEPTANCE_NESTED"] = "1"
    return cmd, env


def _diag_message(
    code: int, out_tail: str, err_tail: str
) -> str:
    """Assertion payload carrying BOTH bounded tails for diagnosability."""
    return (
        f"S11 acceptance suite failed (exit {code})\n"
        f"--- stdout tail ---\n{out_tail}\n"
        f"--- stderr tail ---\n{err_tail}"
    )


def _run_suite(basetemp: Path) -> tuple[int, str, str]:
    """Run the full S11 suite as ONE pytest invocation (real subprocess).

    Returns ``(returncode, stdout_tail, stderr_tail)`` — correction C2: the
    child can fail with the diagnosis on stderr, so BOTH streams are kept
    for the assertion message.
    """
    cmd, env = _suite_cmd_env(basetemp)
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
        shell=False,
    )
    return (
        result.returncode,
        _bounded_tail(result.stdout),
        _bounded_tail(result.stderr),
    )


def _ffmpeg_name(name: str | None) -> bool:
    lowered = (name or "").lower()
    return lowered.startswith("ffmpeg") or lowered.startswith("ffprobe")


def _run_suite_tracked(
    basetemp: Path,
) -> tuple[int, str, str, set[int]]:
    """``_run_suite`` plus OWNERSHIP-SCOPED leak observation.

    Correction C2 (point 4): while our child suite runs, every
    ffmpeg/ffprobe process that appears INSIDE the child's live process
    tree is recorded.  Survivors of that recorded set after the child exits
    are leaks attributable to THIS run.  Unlike a machine-wide
    baseline-diff scan, concurrent acceptance invocations (different
    basetemps, other pids) can never contaminate each other's verdict.
    Caller must have established psutil availability (skip otherwise).

    Correction C3 (finding P2, Manager py-spy evidence): the child pytest
    COMPLETES all tests but may never exit when its stdout pipe fills and
    blocks (nobody was draining it while this loop polled), and the poll
    loop had no total deadline — outer+inner hung for 80+ minutes.  Both
    defects are fixed here: dedicated reader threads drain stdout/stderr
    continuously (no unread PIPE can block the child), and the whole wait
    is bounded by a HARD TOTAL DEADLINE (1800 s) after which the child is
    killed and its captured output returned with ``_TIMEOUT_RC``.
    """
    import psutil

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

            if timed_out:
                child.kill()
            returncode = child.wait(timeout=120)
            out_thread.join(timeout=30)
            err_thread.join(timeout=30)
        finally:
            if child.poll() is None:  # defensive: never orphan the child
                child.kill()
                child.wait(timeout=60)

    if timed_out and returncode == 0:
        # The wait deadline expired — surface it even if a racing kill made
        # the exit code look clean.
        returncode = _TIMEOUT_RC
    err_tail = _bounded_tail("".join(err_chunks))
    if timed_out:
        err_tail += (
            f"\n[harness] child killed at {_CHILD_TOTAL_DEADLINE_S}s "
            "hard total deadline"
        )
    return (
        returncode,
        _bounded_tail("".join(out_chunks)),
        err_tail,
        seen_engine_pids,
    )


def _pid_alive_ffmpeg(pid: int) -> bool:
    """True iff *pid* currently resolves to a live ffmpeg/ffprobe process."""
    import psutil

    try:
        return _ffmpeg_name(psutil.Process(pid).name())
    except psutil.Error:
        return False


@contextlib.contextmanager
def _inner_suite_lock() -> Iterator[None]:
    """Serialize the nested S11 suite across concurrent acceptance runs.

    WHY (correction C2, gate-c evidence): the frozen suite contains
    T01C's ``test_12_no_process_leak``, which asserts via a MACHINE-WIDE
    ffmpeg/ffprobe pid-diff.  Two inner suites running concurrently observe
    each other's engine processes and false-fail.  That file is outside
    this task's write-set, so this harness serializes the inner run with a
    machine-wide lock file instead — no assertion is weakened anywhere.
    The lock auto-releases if a holder process dies (OS releases the fd).
    """
    lock_path = Path(tempfile.gettempdir()) / "s11-t01d-inner-suite.lock"
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
    """Short, unique child basetemp created DIRECTLY under the Windows temp
    root — never chained from the outer pytest ``tmp_path``.

    Rationale (S11-T01D correction C1, finding P2): the nested suite writes
    artifact/media/SQLite trees whose paths inherit the basetemp prefix.  A
    long outer tmp_path prefix pushes those inner paths past Windows MAX_PATH
    and the nested run fails with path-length errors — an acceptance-harness
    defect, not an engine defect.  A short root-level basetemp keeps every
    nested path well under the limit.

    Uniqueness: pid + monotonic counter suffix prevents collision between
    concurrent runs; the directory is created and verified BEFORE spawning.
    """
    root = Path(tempfile.gettempdir())
    basetemp = root / f"s11c1-{tag}-{os.getpid()}-{next(_basetemp_seq)}"
    basetemp.mkdir(parents=True, exist_ok=False)
    assert basetemp.is_dir(), f"child basetemp not created: {basetemp}"
    return basetemp


def _cleanup_basetemp(basetemp: Path) -> None:
    """Best-effort removal of exactly our own child basetemp (never a broad
    target): ignore_errors survives Windows file-handle lag."""
    shutil.rmtree(basetemp, ignore_errors=True)


def test_a01_full_s11_suite_green() -> None:
    """Scenario 9: contract + remux + attach + integration + acceptance all
    pass in ONE pytest invocation (--ignore=tests/test_integration.py)."""
    missing = [f for f in S11_SUITE_FILES if not (PROJECT_ROOT / f).is_file()]
    assert not missing, f"S11 suite files missing: {missing}"
    basetemp = _child_basetemp("suite")
    try:
        with _inner_suite_lock():
            code, out_tail, err_tail = _run_suite(basetemp)
    finally:
        _cleanup_basetemp(basetemp)
    assert code == 0, _diag_message(code, out_tail, err_tail)
    # The summary line must show zero failed/error — e.g. "45 passed".
    last = [ln for ln in out_tail.splitlines() if ln.strip()][-1]
    assert " failed" not in last and " error" not in last, (
        f"{last}\nstdout tail:\n{out_tail}\nstderr tail:\n{err_tail}"
    )


def test_a02_no_process_leak_after_suite() -> None:
    """Scenario 10: run the full S11 suite, then prove no ffmpeg/ffprobe
    process survived it (bounded engine cleanup end-to-end).

    Ownership-scoped (correction C2): only engine processes observed INSIDE
    our child suite's live process tree are attributed to this run, so
    concurrent acceptance invocations cannot contaminate the verdict.
    """
    try:
        import psutil  # noqa: F401
    except ImportError:
        pytest.skip("psutil unavailable — process-leak assertion needs it")

    basetemp = _child_basetemp("leak-suite")
    try:
        with _inner_suite_lock():
            code, out_tail, err_tail, seen = _run_suite_tracked(basetemp)
    finally:
        _cleanup_basetemp(basetemp)
    assert code == 0, _diag_message(code, out_tail, err_tail)

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if not any(_pid_alive_ffmpeg(p) for p in seen):
            break
        time.sleep(0.25)
    survivors = {p for p in seen if _pid_alive_ffmpeg(p)}
    assert not survivors, (
        "ffmpeg/ffprobe processes leaked after the full S11 suite "
        f"(ownership-scoped pids): {survivors}\n"
        f"--- stdout tail ---\n{out_tail}\n"
        f"--- stderr tail ---\n{err_tail}"
    )

"""S11-T03A common bounded runner (W5).

The shared ``_run_bounded`` harness executes a REGISTERED detector entry
point in a child process under ALL bounding conditions simultaneously
(pattern replicated from ``app.services.original_audio_remux._run_bounded``
— T01D harness drain/deadline, lane-B CHECK_CAPABILITY_MATRIX §6):

- wall-clock deadline -> child tree killed + stable ``QC_RUNNER_DEADLINE_EXCEEDED``;
- combined stdout+stderr capture cap -> fail-closed (no partial result is
  ever accepted) + stable ``QC_RUNNER_OUTPUT_CAP_EXCEEDED``;
- cancel event -> child tree killed, clean stop, NO residue process (T01D
  ownership-scoped leak scan: every spawned pid must die) + stable
  ``QC_RUNNER_CANCELLED``;
- invalid bounds -> ``QC_RUNNER_INVALID_ARGS`` before any spawn;
- child crash / protocol violation -> ``QC_RUNNER_CHILD_ERROR``;
- unregistered detector -> the registry's stable ``QC_REGISTRY_UNKNOWN``.

Every failure path kills the FULL child tree (psutil children-first with a
``proc.kill()`` fallback) and reaps/joins using ONLY the remaining deadline
budget — no orphan process, no fresh fixed window.

Child protocol: the child resolves ``module:qualname`` from the registry
entry point, calls ``fn(args_json)`` and writes ONE final JSON line
``{"ok": true, "result": ...}`` (or ``{"ok": false, "error_type": ...,
"error": ...}``) on stdout.  The runner only ever accepts that last line —
anything else is a fail-closed protocol error.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.qc_checks.registry import get_detector

#: Stable result / error codes.
QC_RUNNER_OK = "QC_RUNNER_OK"
QC_RUNNER_INVALID_ARGS = "QC_RUNNER_INVALID_ARGS"
QC_RUNNER_DEADLINE_EXCEEDED = "QC_RUNNER_DEADLINE_EXCEEDED"
QC_RUNNER_OUTPUT_CAP_EXCEEDED = "QC_RUNNER_OUTPUT_CAP_EXCEEDED"
QC_RUNNER_CANCELLED = "QC_RUNNER_CANCELLED"
QC_RUNNER_CHILD_ERROR = "QC_RUNNER_CHILD_ERROR"

#: Poll cadence of the bounding loop (seconds).
_POLL_INTERVAL = 0.02

#: Project root = app/services/qc_checks/runner.py -> parents[3].
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Child-side worker: resolves the entry point and emits the JSON protocol
#: line as the LAST stdout line.  Self-contained (stdlib only) — it must run
#: under ``python -c`` in a fresh child process.
_CHILD_SRC = (
    "import importlib, json, sys\n"
    "def _main() -> None:\n"
    "    entry_point = sys.argv[1]\n"
    "    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else {}\n"
    "    module_name, _, qualname = entry_point.partition(':')\n"
    "    fn = importlib.import_module(module_name)\n"
    "    for part in qualname.split('.'):\n"
    "        fn = getattr(fn, part)\n"
    "    result = fn(args)\n"
    "    line = json.dumps({'ok': True, 'result': result},\n"
    "                      separators=(',', ':'), ensure_ascii=False)\n"
    "    sys.stdout.write(line + '\\n')\n"
    "    sys.stdout.flush()\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    try:\n"
    "        _main()\n"
    "    except Exception as exc:\n"
    "        line = json.dumps({'ok': False,\n"
    "                           'error_type': type(exc).__name__,\n"
    "                           'error': str(exc)},\n"
    "                          separators=(',', ':'), ensure_ascii=False)\n"
    "        sys.stdout.write(line + '\\n')\n"
    "        sys.stdout.flush()\n"
    "        sys.exit(2)\n"
)


class QcRunnerError(Exception):
    """Bounded-run failure carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DetectorRun:
    """Successful detector run result."""

    detector: str
    status: str
    code: str
    output: Any
    stderr_tail: str
    run_sec: float


class _CaptureState:
    """Shared byte counter + abort flag read by the bounding loop."""

    __slots__ = ("bytes_read", "abort")

    def __init__(self) -> None:
        self.bytes_read = 0
        self.abort = threading.Event()


class _PipeReader(threading.Thread):
    """Daemon drainer for one child pipe; sets abort when the combined
    captured bytes cross the cap (fail-closed during the run)."""

    def __init__(
        self,
        state: _CaptureState,
        stream: Any,
        capture_cap_bytes: int,
    ) -> None:
        super().__init__(daemon=True)
        self.state = state
        self.stream = stream
        self.capture_cap_bytes = capture_cap_bytes
        self.chunks: list[bytes] = []

    def run(self) -> None:  # noqa: D102 - documented by the class docstring
        try:
            for chunk in iter(lambda: self.stream.read(65536), b""):
                self.chunks.append(chunk)
                self.state.bytes_read += len(chunk)
                if self.state.bytes_read > self.capture_cap_bytes:
                    self.state.abort.set()
        finally:
            with contextlib.suppress(Exception):
                self.stream.close()


def _remaining_budget(deadline: float) -> float:
    return deadline - time.monotonic()


def _kill_tree(proc: Any) -> None:
    """Terminate the FULL child tree (children first), then the child.

    psutil-backed, mirroring ``original_audio_remux._kill_tree``; falls
    back to ``proc.kill()`` alone when psutil is unavailable.
    """
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(Exception):
                    child.kill()
            with contextlib.suppress(Exception):
                parent.kill()
        except Exception:
            pass
    with contextlib.suppress(OSError):
        proc.kill()


def _run_bounded(
    cmd: list[str],
    *,
    deadline: float,
    cancel_event: threading.Event | None,
    capture_cap_bytes: int,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    """Run *cmd* (LIST ARGS, shell=False) under all bounding conditions.

    Returns ``(returncode, stdout_bytes, stderr_bytes)`` on normal child
    exit; raises ``QcRunnerError`` with a stable code on deadline / capture
    cap / cancel.  Every failure path kills the child tree and reaps within
    the remaining deadline budget — no residue process.
    """
    proc = subprocess.Popen(
        cmd,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    state = _CaptureState()
    out_reader = _PipeReader(state, proc.stdout, capture_cap_bytes)
    err_reader = _PipeReader(state, proc.stderr, capture_cap_bytes)
    out_reader.start()
    err_reader.start()

    def _finish_failure(code: str, message: str) -> QcRunnerError:
        _kill_tree(proc)
        budget = _remaining_budget(deadline)
        if budget > 0:
            with contextlib.suppress(Exception):
                proc.wait(timeout=budget)
        else:
            proc.poll()
        for reader in (out_reader, err_reader):
            with contextlib.suppress(Exception):
                reader.join(timeout=max(0.0, _remaining_budget(deadline)))
        return QcRunnerError(code, message)

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise _finish_failure(
                    QC_RUNNER_CANCELLED, "detector run cancelled by request"
                )
            if state.abort.is_set():
                raise _finish_failure(
                    QC_RUNNER_OUTPUT_CAP_EXCEEDED,
                    f"detector output exceeded the "
                    f"{capture_cap_bytes}-byte capture cap",
                )
            if _remaining_budget(deadline) <= 0:
                raise _finish_failure(
                    QC_RUNNER_DEADLINE_EXCEEDED,
                    f"deadline exceeded running {Path(cmd[0]).name}",
                )
            if not out_reader.is_alive() and not err_reader.is_alive():
                break
            time.sleep(_POLL_INTERVAL)
        budget = _remaining_budget(deadline)
        if budget <= 0:
            raise _finish_failure(
                QC_RUNNER_DEADLINE_EXCEEDED,
                "deadline exceeded reaping the detector child",
            )
        try:
            proc.wait(timeout=budget)
        except subprocess.TimeoutExpired as exc:
            raise _finish_failure(
                QC_RUNNER_DEADLINE_EXCEEDED,
                "deadline exceeded reaping the detector child",
            ) from exc
        # fail-closed: if the cap was crossed while draining (even if the
        # child finished first) no partial result is accepted
        if state.abort.is_set():
            raise _finish_failure(
                QC_RUNNER_OUTPUT_CAP_EXCEEDED,
                f"detector output exceeded the "
                f"{capture_cap_bytes}-byte capture cap",
            )
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
            budget = _remaining_budget(deadline)
            if budget > 0:
                with contextlib.suppress(Exception):
                    proc.wait(timeout=budget)
            else:
                proc.poll()
        for reader in (out_reader, err_reader):
            with contextlib.suppress(Exception):
                reader.join(timeout=max(0.0, _remaining_budget(deadline)))

    out_text = b"".join(out_reader.chunks)
    err_text = b"".join(err_reader.chunks)
    return proc.returncode if proc.returncode is not None else -1, out_text, err_text


def _child_pythonpath() -> str:
    """PYTHONPATH for the child: project root first, then the parent's
    sys.path (under pytest this includes the tests dir, so test-side
    detector doubles resolve by module name)."""
    entries: list[str] = []
    for entry in [str(_PROJECT_ROOT), *sys.path]:
        if entry and entry not in entries:
            entries.append(entry)
    return os.pathsep.join(entries)


def run_detector(
    name: str,
    *,
    args: dict[str, Any] | None = None,
    deadline_sec: float,
    capture_cap_bytes: int,
    cancel_event: threading.Event | None = None,
) -> DetectorRun:
    """Run a REGISTERED detector entry point under the common bounds.

    Raises ``QcRunnerError`` with a stable code on every bounded failure and
    ``QcRegistryError`` (``QC_REGISTRY_UNKNOWN``) when the detector is not
    registered — an unregistered detector can never run silently.
    """
    if deadline_sec <= 0 or capture_cap_bytes <= 0:
        raise QcRunnerError(
            QC_RUNNER_INVALID_ARGS,
            "deadline_sec and capture_cap_bytes must be positive",
        )
    spec = get_detector(name)  # stable QC_REGISTRY_UNKNOWN when absent
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = _child_pythonpath()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    cmd = [
        sys.executable,
        "-c",
        _CHILD_SRC,
        spec.entry_point,
        json.dumps(args or {}, separators=(",", ":")),
    ]
    started = time.monotonic()
    rc, out_bytes, err_bytes = _run_bounded(
        cmd,
        # T01D contract: deadline is an absolute monotonic timestamp —
        # remaining budget is never a fresh fixed window.
        deadline=time.monotonic() + deadline_sec,
        cancel_event=cancel_event,
        capture_cap_bytes=capture_cap_bytes,
        env=child_env,
    )
    run_sec = time.monotonic() - started
    out_text = out_bytes.decode("utf-8", errors="replace")
    err_tail = err_bytes.decode("utf-8", errors="replace")[-4000:]

    lines = [line for line in out_text.splitlines() if line.strip()]
    if not lines:
        raise QcRunnerError(
            QC_RUNNER_CHILD_ERROR,
            f"detector {name!r} produced no output (exit {rc})",
        )
    try:
        payload = json.loads(lines[-1])
    except ValueError as exc:
        raise QcRunnerError(
            QC_RUNNER_CHILD_ERROR,
            f"detector {name!r} output protocol violation: "
            f"last stdout line is not JSON: {exc}",
        ) from exc
    if rc != 0 or not payload.get("ok"):
        error_type = payload.get("error_type") or "DetectorError"
        error = payload.get("error") or f"child exited with code {rc}"
        raise QcRunnerError(
            QC_RUNNER_CHILD_ERROR,
            f"{error_type}: {error}",
        )
    return DetectorRun(
        detector=name,
        status="ok",
        code=QC_RUNNER_OK,
        output=payload.get("result"),
        stderr_tail=err_tail,
        run_sec=run_sec,
    )
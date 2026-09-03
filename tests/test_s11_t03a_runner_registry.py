"""S11-T03A common bounded runner + detector registry contract tests (W5).

Runner contract (mirrors T01D ``original_audio_remux._run_bounded``):
- deadline exceeded -> child killed (full tree) + stable code;
- capture cap exceeded -> fail-closed, child killed, no partial result;
- cancel event -> child killed, clean stop, NO residue process
  (T01D ownership-scoped leak scan: every spawned pid must be dead);
- invalid bounds -> fail-closed before any spawn;
- unregistered detector -> stable registry error.

Registry contract:
- register/get idempotent; name+entry_point identity; same name with a
  DIFFERENT entry_point -> stable conflict error; unregister idempotent;
  unknown name on get/run -> stable error code.

Detector doubles are module-level functions resolved in the spawned child
via ``import test_s11_t03a_runner_registry`` (PYTHONPATH inherited from the
parent sys.path).  Module top-level has NO side effects so the child's
re-import is safe.

Isolation: short Windows-native basetemp; -p no:cacheprovider; env strips
MOTIONFORGE_DATABASE_URL.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from app.services.qc_checks import (
    DetectorRegistry,
    DetectorSpec,
    QcRegistryError,
    QcRunnerError,
    QC_REGISTRY_CONFLICT,
    QC_REGISTRY_INVALID_ARGS,
    QC_REGISTRY_UNKNOWN,
    QC_RUNNER_CANCELLED,
    QC_RUNNER_CHILD_ERROR,
    QC_RUNNER_DEADLINE_EXCEEDED,
    QC_RUNNER_INVALID_ARGS,
    QC_RUNNER_OK,
    QC_RUNNER_OUTPUT_CAP_EXCEEDED,
    get_detector,
    register_detector,
    registry,
    run_detector,
    unregister_detector,
)

# ── detector doubles (module-level: resolvable by the child process) ────────

def detector_fast(args: dict) -> dict:
    """Immediate detector: returns a JSON-able raw measurement."""
    _ = args
    return {"metric": "cut_drift", "value": 3, "probe": "fast"}


def detector_sleepy(args: dict) -> dict:
    """Writes its own pid to args['pid_file'], then blocks ~60 s."""
    Path(args["pid_file"]).write_text(str(os.getpid()), encoding="ascii")
    time.sleep(60)
    return {"metric": "sleepy", "value": 0}


def detector_verbose(args: dict) -> dict:
    """Writes its pid, then floods stdout far beyond any test capture cap."""
    Path(args["pid_file"]).write_text(str(os.getpid()), encoding="ascii")
    sys.stdout.write(("junk-line\n" * 40000))  # ~480 KB
    sys.stdout.flush()
    return {"metric": "verbose", "value": 1}


def detector_boom(args: dict) -> dict:
    """Raises inside the child -> child-reported error path."""
    _ = args
    raise RuntimeError("boom-for-test")


# ── helpers ─────────────────────────────────────────────────────────────────

_ENTRY_MODULE = "test_s11_t03a_runner_registry"
_PID_FILES: list[Path] = []


def _pid_file(name: str) -> Path:
    base = Path(os.environ.get("TEMP", r"C:\Windows\Temp"))
    path = base / f"s11t03a-{name}-{os.getpid()}.pid"
    _PID_FILES.append(path)
    return path


def _read_pid(path: Path, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return int(path.read_text(encoding="ascii").strip())
            except ValueError:
                pass
        time.sleep(0.05)
    raise AssertionError(f"child never wrote pid file: {path}")


def _assert_dead(pid: int, timeout: float = 10.0) -> None:
    import psutil

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} still alive after kill (leak)")


def test_entry_point_module_is_importable() -> None:
    """Guard: the child resolves doubles by this module name — it must be
    importable from the parent sys.path (pytest rootdir insertion)."""
    import importlib

    mod = importlib.import_module(_ENTRY_MODULE)
    assert callable(mod.detector_fast)
    assert callable(mod.detector_sleepy)


# ── registry contract ───────────────────────────────────────────────────────

def test_registry_register_get_idempotent() -> None:
    reg = DetectorRegistry()
    first = reg.register("t_reg_ok", f"{_ENTRY_MODULE}:detector_fast", version="1.0.0")
    assert isinstance(first, DetectorSpec)
    assert first.name == "t_reg_ok"
    assert reg.get("t_reg_ok") == first
    # re-register the SAME identity -> idempotent, no error
    again = reg.register("t_reg_ok", f"{_ENTRY_MODULE}:detector_fast")
    assert again == first


def test_registry_same_name_different_entry_point_conflict() -> None:
    reg = DetectorRegistry()
    reg.register("t_conflict", f"{_ENTRY_MODULE}:detector_fast")
    with pytest.raises(QcRegistryError) as exc_info:
        reg.register("t_conflict", f"{_ENTRY_MODULE}:detector_sleepy")
    assert exc_info.value.code == QC_REGISTRY_CONFLICT


def test_registry_unregister_idempotent() -> None:
    reg = DetectorRegistry()
    reg.register("t_unreg", f"{_ENTRY_MODULE}:detector_fast")
    assert reg.unregister("t_unreg") is True
    assert reg.unregister("t_unreg") is False  # second call: no error
    assert reg.unregister("never_registered") is False


def test_registry_get_unknown_stable_error() -> None:
    reg = DetectorRegistry()
    with pytest.raises(QcRegistryError) as exc_info:
        reg.get("t_unknown_never")
    assert exc_info.value.code == QC_REGISTRY_UNKNOWN


def test_registry_register_invalid_args_fail_closed() -> None:
    reg = DetectorRegistry()
    with pytest.raises(QcRegistryError) as exc_info:
        reg.register("", f"{_ENTRY_MODULE}:detector_fast")
    assert exc_info.value.code == QC_REGISTRY_INVALID_ARGS
    with pytest.raises(QcRegistryError) as exc_info:
        reg.register("t_bad_ep", "no-colon-entry-point")
    assert exc_info.value.code == QC_REGISTRY_INVALID_ARGS


def test_module_singleton_registry_functions() -> None:
    name = "t_mod_singleton"
    register_detector(name, f"{_ENTRY_MODULE}:detector_fast", version="0.0.1")
    try:
        assert get_detector(name).name == name
        assert name in registry.names()
    finally:
        unregister_detector(name)
    assert unregister_detector(name) is False


# ── runner: happy path ──────────────────────────────────────────────────────

def test_run_detector_ok_result() -> None:
    name = "t_run_ok"
    register_detector(name, f"{_ENTRY_MODULE}:detector_fast", version="1.0.0")
    try:
        run = run_detector(
            name,
            args={"seed": 7},
            deadline_sec=20.0,
            capture_cap_bytes=64 * 1024,
        )
        assert run.status == "ok"
        assert run.code == QC_RUNNER_OK
        assert run.output == {"metric": "cut_drift", "value": 3, "probe": "fast"}
        assert run.run_sec >= 0.0
    finally:
        unregister_detector(name)


def test_run_unknown_detector_stable_error() -> None:
    with pytest.raises(QcRegistryError) as exc_info:
        run_detector("t_never_registered", deadline_sec=10.0, capture_cap_bytes=1024)
    assert exc_info.value.code == QC_REGISTRY_UNKNOWN


# ── runner: bounded failure paths (each proves kill + no residue) ───────────

def test_deadline_exceeded_kills_child_stable_code() -> None:
    name = "t_deadline"
    pid_path = _pid_file("deadline")
    register_detector(name, f"{_ENTRY_MODULE}:detector_sleepy")
    try:
        with pytest.raises(QcRunnerError) as exc_info:
            run_detector(
                name,
                args={"pid_file": str(pid_path)},
                deadline_sec=2.5,
                capture_cap_bytes=64 * 1024,
            )
        assert exc_info.value.code == QC_RUNNER_DEADLINE_EXCEEDED
        pid = _read_pid(pid_path)
        _assert_dead(pid)
    finally:
        unregister_detector(name)


def test_capture_cap_exceeded_fail_closed_stable_code() -> None:
    name = "t_cap"
    pid_path = _pid_file("cap")
    register_detector(name, f"{_ENTRY_MODULE}:detector_verbose")
    try:
        with pytest.raises(QcRunnerError) as exc_info:
            run_detector(
                name,
                args={"pid_file": str(pid_path)},
                deadline_sec=20.0,
                capture_cap_bytes=4096,
            )
        assert exc_info.value.code == QC_RUNNER_OUTPUT_CAP_EXCEEDED
        pid = _read_pid(pid_path)
        _assert_dead(pid)
    finally:
        unregister_detector(name)


def test_cancel_event_stops_cleanly_no_residue() -> None:
    name = "t_cancel"
    pid_path = _pid_file("cancel")
    cancel_event = threading.Event()
    register_detector(name, f"{_ENTRY_MODULE}:detector_sleepy")
    outcome: list[str] = []
    try:
        def _run() -> None:
            try:
                run_detector(
                    name,
                    args={"pid_file": str(pid_path)},
                    deadline_sec=60.0,
                    capture_cap_bytes=64 * 1024,
                    cancel_event=cancel_event,
                )
            except QcRunnerError as exc:
                outcome.append(exc.code)

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        pid = _read_pid(pid_path)  # child is up and blocking
        cancel_event.set()
        worker.join(timeout=20.0)
        assert not worker.is_alive(), "run_detector did not return after cancel"
        assert outcome == [QC_RUNNER_CANCELLED]
        _assert_dead(pid)
    finally:
        unregister_detector(name)


def test_invalid_bounds_fail_closed_before_spawn() -> None:
    name = "t_invalid"
    register_detector(name, f"{_ENTRY_MODULE}:detector_fast")
    try:
        with pytest.raises(QcRunnerError) as exc_info:
            run_detector(name, deadline_sec=0.0, capture_cap_bytes=1024)
        assert exc_info.value.code == QC_RUNNER_INVALID_ARGS
        with pytest.raises(QcRunnerError) as exc_info:
            run_detector(name, deadline_sec=10.0, capture_cap_bytes=-1)
        assert exc_info.value.code == QC_RUNNER_INVALID_ARGS
    finally:
        unregister_detector(name)


def test_child_exception_is_stable_error() -> None:
    name = "t_boom"
    register_detector(name, f"{_ENTRY_MODULE}:detector_boom")
    try:
        with pytest.raises(QcRunnerError) as exc_info:
            run_detector(name, deadline_sec=20.0, capture_cap_bytes=64 * 1024)
        assert exc_info.value.code == QC_RUNNER_CHILD_ERROR
        assert "boom-for-test" in exc_info.value.message
    finally:
        unregister_detector(name)


# ── ownership-scoped leak scan (T01D pattern) ───────────────────────────────

def test_no_residue_processes_after_all_runs() -> None:
    """Every spawned child across this module must be dead by now."""
    import psutil

    alive: list[int] = []
    for path in _PID_FILES:
        if not path.exists():
            continue
        try:
            pid = int(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            continue
        if psutil.pid_exists(pid):
            alive.append(pid)
    assert alive == [], f"leaked child processes: {alive}"
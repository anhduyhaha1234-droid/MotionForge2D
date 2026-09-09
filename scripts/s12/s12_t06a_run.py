"""S12-T06A lifecycle runner — setup/serve/diagnose/stop/uninstall.

Operates on a RELOCATABLE STAGED PACKAGE (built by s12_t06a_stage.py),
NOT the developer checkout:

  - package root is derived from __file__ (stage/scripts/s12_t06a_run.py
    -> stage; repo scripts/s12/s12_t06a_run.py -> repo) and is the only
    code location used at runtime;
  - backend runs from <pkg>/backend (cwd = package backend dir);
  - frontend runs from <pkg>/frontend with the REAL offline runtime
    (`node node_modules/next/dist/bin/next start`), never `npx`/dev;
  - the backend endpoint is baked at build time into the staged .next
    output (endpoint.api_base_url in manifest.json) and preflight
    verifies it (wrong endpoint fails closed);
  - external declared runtimes (Python 3.11, Node.js 20+, FFmpeg) are
    probed, missing = exact BLOCKER (exit 3), never installed/elevated;
  - process identity: every spawned process records {pid, creation_time,
    executable, command, token}; stop re-probes live identity and NEVER
    kills a reused/wrong PID; a failed stop retains stop_evidence.json
    and returns nonzero, keeping pids in RUNTIME.json;
  - uninstall keeps user data by default (data/ artifacts/ output/);
    removal requires explicit confirmation.

Runtime root = --install-root (user-local dir holding data/artifacts/
output/logs + RUNTIME.json). Pointing it at the protected MAIN tree or
the repo checkout is refused.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKEND_PORT = 8421
DEFAULT_FRONTEND_PORT = 3121
PROC_KEYS = ("backend", "frontend")


def log(msg: str) -> None:
    print(f"[s12-t06a] {msg}", flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_install_root(raw: str | None) -> Path:
    root = Path(raw).expanduser() if raw else (
        PACKAGE_ROOT / ".s12-t06a-runtime")
    if not root.is_absolute():
        root = PACKAGE_ROOT / root
    protected = (Path.home() / "MotionForge2D").resolve()
    repo_resolved = PACKAGE_ROOT.resolve()
    try:
        rr = root.resolve()
        if rr == protected or rr.is_relative_to(protected):
            log("BLOCKED: install root is the protected MAIN tree; use a "
                "user-local owned dir")
            raise SystemExit(3)
        if rr == repo_resolved or rr.is_relative_to(repo_resolved):
            log("BLOCKED: install root must not live inside the package "
                "tree (data/artifacts belong to a user-local owned dir)")
            raise SystemExit(3)
    except SystemExit:
        raise
    except OSError:
        pass
    return root


def runtime_path(install_root: Path) -> Path:
    return install_root / "RUNTIME.json"


def read_runtime(install_root: Path) -> dict:
    rp = runtime_path(install_root)
    if not rp.is_file():
        return {}
    try:
        return json.loads(rp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_runtime(install_root: Path, data: dict) -> None:
    install_root.mkdir(parents=True, exist_ok=True)
    runtime_path(install_root).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8")


def http_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return (200 <= resp.status < 400, f"HTTP {resp.status}")
    except Exception as err:  # noqa: BLE001 — diagnostics surface the text
        return (False, str(err))


def wait_for(url: str, timeout_s: float, label: str) -> bool:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        ok, last = http_ok(url)
        if ok:
            log(f"{label} up: {url} ({last})")
            return True
        time.sleep(1.0)
    log(f"{label} NOT up after {timeout_s:.0f}s: {url} ({last})")
    return False


def pid_alive(pid: int) -> bool:
    """Windows-safe aliveness: tasklist lookup (os.kill(pid,0) is broken)."""
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}",
                                  "/NH"], capture_output=True, text=True,
                                 timeout=10)
            return str(pid) in (out.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# --- process identity ---------------------------------------------------

def probe_process(pid: int) -> dict | None:
    """Read live identity (creation time, executable, command line).

    Uses Windows-provisioned PowerShell/WMI — no psutil, no install.
    Returns None when the PID is not alive / cannot be probed.
    """
    if not pid_alive(pid):
        return None
    if os.name != "nt":
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw = fh.read().replace(b"\0", b" ").decode("utf-8",
                                                            errors="replace")
        except OSError:
            return None
        return {"pid": pid, "creation_time": None,
                "executable": None, "command": raw.strip()}
    script = (
        "Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | "
        "Select-Object ProcessId,CreationDate,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    ).format(pid=pid)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             script],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"pid": pid, "creation_time": None, "executable": None,
                "command": None, "error": str(err)}
    if out.returncode != 0 or not out.stdout.strip():
        return {"pid": pid, "creation_time": None, "executable": None,
                "command": None, "error": (out.stderr or "").strip()[-200:]}
    try:
        payload = json.loads(out.stdout.strip())
    except json.JSONDecodeError:
        return {"pid": pid, "creation_time": None, "executable": None,
                "command": None, "error": "unparseable WMI JSON"}
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return {"pid": payload.get("ProcessId", pid),
            "creation_time": _normalize_wmi_date(
                payload.get("CreationDate")),
            "executable": payload.get("ExecutablePath"),
            "command": payload.get("CommandLine")}


def _normalize_wmi_date(raw: object) -> str | None:
    """Convert WMI /Date(<ms>)/ (or ISO) to ISO-8601 UTC."""
    if raw is None:
        return None
    text = str(raw)
    m = re.search(r"/Date\((\d+)\)/", text)
    if m:
        ms = int(m.group(1))
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    return text.replace("Z", "+00:00")


def identity_ok(recorded: dict, current: dict | None) -> tuple[bool, str]:
    """True only when the recorded identity matches the live process.

    Never trusts a bare PID: creation time (round-tripped through the
    second) + executable family + command marker must all match. A
    reused PID (different creation time) or a foreign process (different
    exe/cmd) is refused.
    """
    if current is None:
        return False, "process not alive / not probeable"
    if current.get("pid") != recorded.get("pid"):
        return False, "pid mismatch"
    rec_ct = recorded.get("creation_time")
    cur_ct = current.get("creation_time")
    if rec_ct and cur_ct:
        try:
            r = datetime.fromisoformat(str(rec_ct).replace("Z", "+00:00"))
            c = datetime.fromisoformat(str(cur_ct).replace("Z", "+00:00"))
            if abs((r - c).total_seconds()) > 2.0:
                return False, (
                    f"creation-time mismatch: recorded {rec_ct} != "
                    f"live {cur_ct} (PID reused by another process)")
        except ValueError:
            return False, f"unparseable creation time: {rec_ct!r} / {cur_ct!r}"
    else:
        return False, "creation time unavailable"
    exe = (current.get("executable") or "").lower()
    cmd = (current.get("command") or "").lower()
    expected = recorded.get("expected_executable", "").lower()
    marker = recorded.get("command_marker", "").lower()
    if expected and expected not in exe and expected not in cmd:
        return False, f"executable mismatch: expected {expected}"
    if marker and marker not in cmd:
        return False, f"command mismatch: expected marker {marker}"
    return True, "identity verified"


def capture_identity(pid: int, expected_executable: str,
                     command_marker: str) -> dict:
    live = probe_process(pid) or {}
    return {"pid": pid,
            "creation_time": live.get("creation_time"),
            "executable": live.get("executable"),
            "command": live.get("command"),
            "expected_executable": expected_executable,
            "command_marker": command_marker,
            "token": uuid.uuid4().hex}


def write_stop_evidence(install_root: Path, attempts: list[dict]) -> None:
    ev_dir = install_root / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_file = ev_dir / "stop_evidence.json"
    prev: list = []
    if ev_file.is_file():
        try:
            prev = json.loads(ev_file.read_text(encoding="utf-8"))
            if not isinstance(prev, list):
                prev = []
        except (OSError, json.JSONDecodeError):
            prev = []
    prev.append({"timestamp": now_iso(), "attempts": attempts})
    ev_file.write_text(json.dumps(prev, indent=2) + "\n", encoding="utf-8")
    log(f"stop evidence written: {ev_file}")


# --- commands ------------------------------------------------------------

def run_preflight(install_root: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(PACKAGE_ROOT / "scripts"
                             / "s12_t06a_preflight.py"),
         "--install-root", str(install_root)],
        capture_output=True, text=True, encoding="utf-8")
    print(proc.stdout, flush=True)
    print(proc.stderr, flush=True)
    return proc.returncode


def package_manifest() -> dict:
    mf = PACKAGE_ROOT / "manifest.json"
    if not mf.is_file():
        raise SystemExit("BLOCKED: manifest.json missing in package root "
                         f"{PACKAGE_ROOT}")
    return json.loads(mf.read_text(encoding="utf-8"))


def cmd_setup(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    rc = run_preflight(install_root)
    if rc != 0:
        log("NOT_RUN: preflight blocked setup (see BLOCKER above); "
            "not waived")
        return 3
    manifest = package_manifest()
    build_id = manifest.get("frontend", {}).get("artifact", {}).get(
        "build_id")
    endpoint = manifest.get("endpoint", {})
    ports = dict(endpoint) if isinstance(endpoint, dict) else {}
    for name in ("data", "artifacts", "output", "logs"):
        (install_root / name).mkdir(parents=True, exist_ok=True)
    write_runtime(install_root,
                  {"schema": "s12-t06a-runtime/2",
                   "package_root": str(PACKAGE_ROOT),
                   "install_root": str(install_root),
                   "build_id": build_id,
                   "backend_port": args.backend_port
                   or ports.get("backend_port", DEFAULT_BACKEND_PORT),
                   "frontend_port": args.frontend_port
                   or ports.get("frontend_port", DEFAULT_FRONTEND_PORT),
                   "backend_pid": None, "frontend_pid": None})
    log(f"setup READY: roots ensured under {install_root}, "
        f"RUNTIME.json written (build {build_id})")
    return 0


def spawn_backend(install_root: Path, backend_dir: Path,
                  backend_port: int, frontend_port: int) -> tuple[subprocess.Popen, dict]:
    backend_env = os.environ.copy()
    backend_env["MOTIONFORGE_ROOT"] = str(install_root)
    backend_env["MOTIONFORGE_DATABASE_URL"] = (
        f"sqlite:///{(install_root / 'data' / 'motionforge.db').as_posix()}")
    backend_env["MOTIONFORGE_QA_MODE"] = "1"
    backend_env["MOTIONFORGE_CORS_ORIGINS"] = (
        f"http://localhost:{frontend_port},http://127.0.0.1:{frontend_port}")
    (install_root / "logs").mkdir(parents=True, exist_ok=True)
    backend_log = open(install_root / "logs" / "backend.log",  # noqa: PTH123
                       "a", encoding="utf-8")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(backend_port),
         "--log-level", "warning"],
        cwd=str(backend_dir), env=backend_env,
        stdout=backend_log, stderr=subprocess.STDOUT)
    time.sleep(0.4)
    ident = capture_identity(backend.pid, "python",
                             "uvicorn app.main:app".lower())
    log(f"backend pid {backend.pid} on 127.0.0.1:{backend_port} "
        f"(created {ident.get('creation_time')})")
    return backend, ident


def spawn_frontend(install_root: Path, frontend_dir: Path,
                   frontend_port: int, backend_port: int) -> tuple[subprocess.Popen, dict]:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("BLOCKED: BLOCKED_NODE_MISSING: node not found on "
                         "PATH; Node.js 20+ is a declared external runtime "
                         "(see docs/packaging/s12-windows.md)")
    fe_env = os.environ.copy()
    fe_env["PORT"] = str(frontend_port)
    fe_env["NEXT_PUBLIC_API_URL"] = f"http://127.0.0.1:{backend_port}"
    frontend_log = open(  # noqa: PTH123
        install_root / "logs" / "frontend.log", "a", encoding="utf-8")
    frontend = subprocess.Popen(
        [node, str(frontend_dir / "node_modules" / "next" / "dist" / "bin"
                   / "next"), "start", "-p", str(frontend_port)],
        cwd=str(frontend_dir), env=fe_env,
        stdout=frontend_log, stderr=subprocess.STDOUT)
    time.sleep(0.4)
    ident = capture_identity(frontend.pid, "node",
                             "next start".lower())
    log(f"frontend pid {frontend.pid} on 127.0.0.1:{frontend_port} "
        f"(created {ident.get('creation_time')})")
    return frontend, ident


def cmd_serve(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    if run_preflight(install_root) != 0:
        log("NOT_RUN: preflight blocked serve (see BLOCKER above)")
        return 3
    runtime = read_runtime(install_root)
    for key in PROC_KEYS:
        rec = (runtime or {}).get(f"{key}_proc")
        if isinstance(rec, dict) and isinstance(rec.get("pid"), int):
            cur = probe_process(rec["pid"])
            if cur is not None:
                ok, why = identity_ok(rec, cur)
                log(f"BLOCKED: {key} pid {rec['pid']} already running "
                    f"({why}); run 'stop' first")
                return 3
    endpoint = package_manifest().get("endpoint", {})
    backend_port = args.backend_port or endpoint.get(
        "backend_port", DEFAULT_BACKEND_PORT)
    frontend_port = args.frontend_port or endpoint.get(
        "frontend_port", DEFAULT_FRONTEND_PORT)
    backend_dir = PACKAGE_ROOT / "backend" if (
        PACKAGE_ROOT / "backend").is_dir() else PACKAGE_ROOT
    frontend_dir = PACKAGE_ROOT / "frontend"

    backend, backend_ident = spawn_backend(
        install_root, backend_dir, backend_port, frontend_port)
    if not wait_for(f"http://127.0.0.1:{backend_port}/health", 120,
                    "backend"):
        backend.terminate()
        log("NOT_RUN: backend /health never came up; serve aborted")
        return 3
    try:
        frontend, frontend_ident = spawn_frontend(
            install_root, frontend_dir, frontend_port, backend_port)
    except SystemExit as err:
        backend.terminate()
        log(f"NOT_RUN: {err}")
        return 3
    if not wait_for(f"http://127.0.0.1:{frontend_port}/", 120, "frontend"):
        frontend.terminate()
        backend.terminate()
        log("NOT_RUN: frontend never came up; both processes stopped")
        return 3
    manifest = package_manifest()
    build_id = manifest.get("frontend", {}).get("artifact", {}).get(
        "build_id")
    write_runtime(install_root,
                  {"schema": "s12-t06a-runtime/2",
                   "package_root": str(PACKAGE_ROOT),
                   "install_root": str(install_root),
                   "build_id": build_id,
                   "backend_port": backend_port,
                   "frontend_port": frontend_port,
                   "backend_proc": backend_ident,
                   "frontend_proc": frontend_ident,
                   "backend_pid": backend.pid,
                   "frontend_pid": frontend.pid})
    log(f"serve READY: backend={backend.pid} frontend={frontend.pid}")
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    runtime = read_runtime(install_root)
    backend_port = (runtime or {}).get("backend_port",
                                       DEFAULT_BACKEND_PORT)
    frontend_port = (runtime or {}).get("frontend_port",
                                        DEFAULT_FRONTEND_PORT)
    checks: dict[str, dict] = {}
    b_ok, b_detail = http_ok(f"http://127.0.0.1:{backend_port}/health")
    checks["backend_health"] = {"ok": b_ok, "detail": b_detail}
    f_ok, f_detail = http_ok(f"http://127.0.0.1:{frontend_port}/")
    checks["frontend_root"] = {"ok": f_ok, "detail": f_detail}
    ff = shutil.which("ffmpeg")
    checks["ffmpeg"] = {"ok": ff is not None, "detail": ff or "missing"}
    roots = {}
    for name in ("data", "artifacts", "output", "logs"):
        d = install_root / name
        roots[name] = {"exists": d.is_dir(),
                       "writable": os.access(d, os.W_OK) if d.is_dir()
                       else False}
    checks["runtime_roots"] = {"ok": all(v["exists"] and v["writable"]
                                         for v in roots.values()),
                               "detail": roots}
    procs = {}
    for key in PROC_KEYS:
        rec = (runtime or {}).get(f"{key}_proc")
        pid = (rec or {}).get("pid") if isinstance(rec, dict) else None
        if isinstance(pid, int):
            cur = probe_process(pid)
            ok, why = identity_ok(rec or {}, cur)
            procs[key] = {"pid": pid, "alive": ok,
                          "identity": why}
        else:
            pid2 = (runtime or {}).get(f"{key}_pid")
            procs[key] = {"pid": pid2,
                          "alive": pid_alive(pid2) if isinstance(pid2, int)
                          else False}
    checks["processes"] = {"ok": True, "detail": procs}
    try:
        du = shutil.disk_usage(str(install_root))
        checks["disk"] = {"ok": du.free > 512 * 1024 * 1024,
                          "detail": f"free {du.free // 1024 // 1024} MiB"}
    except OSError as err:
        checks["disk"] = {"ok": False, "detail": str(err)}
    all_ok = all(v["ok"] for v in checks.values())
    print(json.dumps({"verdict": "READY" if all_ok else "DEGRADED",
                      "checks": checks}, indent=2), flush=True)
    return 0 if all_ok else 1


def kill_tree(pid: int, timeout: float = 20.0) -> tuple[bool, str]:
    """Terminate the whole process tree (taskkill /T), graceful first."""
    if not pid_alive(pid):
        return True, "already gone"
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                       capture_output=True, timeout=10)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not pid_alive(pid):
                return True, "stopped gracefully"
            time.sleep(0.5)
        subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                       capture_output=True, timeout=10)
        time.sleep(1.0)
        if not pid_alive(pid):
            return True, "stopped (/F fallback)"
        return False, "STILL ALIVE after /F"
    try:
        subprocess.run(["kill", "-TERM", str(pid)], timeout=10)
    except (OSError, subprocess.TimeoutExpired) as err:
        return False, f"terminate failed: {err}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return True, "stopped gracefully"
        time.sleep(0.5)
    return False, "STILL ALIVE after SIGTERM"


def cmd_stop(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    runtime = read_runtime(install_root)
    if not runtime:
        log("stop: no RUNTIME.json; nothing to stop")
        return 0
    attempts: list[dict] = []
    failed: list[str] = []
    retained: dict[str, dict | None] = {}
    # frontend first, then backend (drain UI before API).
    for key in ("frontend", "backend"):
        rec = runtime.get(f"{key}_proc")
        if not isinstance(rec, dict) or not isinstance(rec.get("pid"), int):
            attempts.append({"key": key, "action": "skip",
                             "reason": "no proc record"})
            retained[key] = runtime.get(f"{key}_proc")
            continue
        pid = rec["pid"]
        cur = probe_process(pid)
        ok, why = identity_ok(rec, cur)
        if not ok:
            attempts.append({"key": key, "pid": pid, "action": "REFUSE",
                             "identity_check": why})
            failed.append(key)
            retained[key] = rec
            log(f"REFUSE: {key} pid {pid} NOT killed ({why})")
            continue
        stopped, detail = kill_tree(pid)
        attempts.append({"key": key, "pid": pid,
                         "action": "kill_tree", "result": detail})
        if not stopped:
            failed.append(key)
            retained[key] = rec
        else:
            retained[key] = None
            log(f"{key} pid {pid}: {detail}")
    if failed:
        write_stop_evidence(install_root, attempts)
        runtime["backend_proc"] = retained.get("backend")
        runtime["frontend_proc"] = retained.get("frontend")
        runtime["backend_pid"] = (
            (retained.get("backend") or {}).get("pid")
            if isinstance(retained.get("backend"), dict) else None)
        runtime["frontend_pid"] = (
            (retained.get("frontend") or {}).get("pid")
            if isinstance(retained.get("frontend"), dict) else None)
        write_runtime(install_root, runtime)
        log(f"stop FAILED for: {', '.join(failed)}; pids retained, "
            "evidence kept, exit nonzero")
        return 1
    runtime["backend_pid"] = None
    runtime["frontend_pid"] = None
    runtime["backend_proc"] = None
    runtime["frontend_proc"] = None
    write_runtime(install_root, runtime)
    log("stop done (all processes stopped)")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    rc = cmd_stop(args)
    if rc != 0:
        log("uninstall: stop FAILED; refusing further cleanup "
            "(evidence retained)")
        return rc
    (install_root / "logs").mkdir(parents=True, exist_ok=True)
    for p in (install_root / "logs").glob("*"):
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    for p in install_root.glob("*.tmp"):
        try:
            p.unlink()
        except OSError:
            pass
    if args.keep_data:
        log(f"uninstall: logs/temp under {install_root} cleaned; user "
            "data PRESERVED (data/, artifacts/, output/)")
        return 0
    if not args.confirm_remove_data:
        log("BLOCKED: refusing to remove user data without "
            "--confirm-remove-data (default keeps user data)")
        return 3
    for name in ("data", "artifacts", "output"):
        d = install_root / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            log(f"uninstall: removed {name}/ (explicitly confirmed)")
    return 0


def add_root_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--install-root", default=None,
                   help="user-local runtime root (default: "
                        "<package>/.s12-t06a-runtime)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="s12_t06a_run.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    setup = sub.add_parser("setup")
    add_root_arg(setup)
    setup.add_argument("--backend-port", type=int, default=None)
    setup.add_argument("--frontend-port", type=int, default=None)
    serve = sub.add_parser("serve")
    add_root_arg(serve)
    serve.add_argument("--backend-port", type=int, default=None)
    serve.add_argument("--frontend-port", type=int, default=None)
    diag = sub.add_parser("diagnose")
    add_root_arg(diag)
    stop = sub.add_parser("stop")
    add_root_arg(stop)
    un = sub.add_parser("uninstall")
    add_root_arg(un)
    un.add_argument("--keep-data", dest="keep_data", action="store_true",
                    default=True)
    un.add_argument("--no-keep-data", dest="keep_data", action="store_false")
    un.add_argument("--confirm-remove-data", action="store_true",
                    default=False)
    args = ap.parse_args(argv)
    if args.cmd == "setup":
        return cmd_setup(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    if args.cmd == "diagnose":
        return cmd_diagnose(args)
    if args.cmd == "stop":
        return cmd_stop(args)
    if args.cmd == "uninstall":
        return cmd_uninstall(args)
    ap.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
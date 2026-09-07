"""S12-T06A local lifecycle runner — setup/serve/diagnose/stop/uninstall.

Local-only harness over the COMPILED frontend (.next via `next start`) +
backend (uvicorn app.main:app). No dev-checkout requirement beyond the
staged code tree, no install, no elevation, no network fetch, no
registry/PATH/firewall changes.

Code root = the repo tree containing these scripts (derived from
__file__, never hardcoded). Runtime root = --install-root (user-local
dir holding data/artifacts/output/logs + RUNTIME.json). Pointing the
runtime root at the protected MAIN tree is refused.

Missing prerequisite anywhere -> exit 3 + NOT_RUN line (never waived).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PKG = REPO / "packaging" / "windows"

DEFAULT_BACKEND_PORT = 8421
DEFAULT_FRONTEND_PORT = 3121


def log(msg: str) -> None:
    print(f"[s12-t06a] {msg}", flush=True)


def resolve_install_root(raw: str | None) -> Path:
    root = Path(raw).expanduser() if raw else (REPO / ".s12-t06a-runtime")
    if not root.is_absolute():
        root = REPO / root
    main = Path.home() / "MotionForge2D"
    try:
        if root.resolve() == main.resolve() or root.resolve().is_relative_to(
                main.resolve()):
            log(f"BLOCKED: install root {root} is the protected MAIN "
                "tree; use a user-local dir (e.g. "
                "%LOCALAPPDATA%\\MotionForge2D-beta)")
            raise SystemExit(3)
    except SystemExit:
        raise
    except OSError:
        pass
    return root


def runtime_path(install_root: Path) -> Path:
    return install_root / "RUNTIME.json"


def run_preflight(install_root: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "s12"
                             / "s12_t06a_preflight.py"),
         "--install-root", str(install_root)],
        capture_output=True, text=True, encoding="utf-8")
    print(proc.stdout, flush=True)
    print(proc.stderr, flush=True)
    return proc.returncode


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
    # Windows-safe: os.kill(pid, 0) raises SystemError/WinError 87 on
    # CPython 3.11 (sig 0 is invalid); fall back to tasklist lookup.
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


def cmd_setup(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    rc = run_preflight(install_root)
    if rc != 0:
        log("NOT_RUN: preflight blocked setup (see BLOCKER above); "
            "not waived")
        return 3
    manifest = json.loads(
        (PKG / "manifest.json").read_text(encoding="utf-8"))
    build_id = ((manifest.get("frontend", {}) or {}).get("artifact", {})
                or {}).get("build_id")
    for name in ("data", "artifacts", "output", "logs"):
        (install_root / name).mkdir(parents=True, exist_ok=True)
    write_runtime(install_root,
                  {"schema": "s12-t06a-runtime/1",
                   "code_root": str(REPO),
                   "install_root": str(install_root),
                   "build_id": build_id,
                   "backend_port": args.backend_port,
                   "frontend_port": args.frontend_port,
                   "backend_pid": None, "frontend_pid": None})
    log(f"setup READY: roots ensured under {install_root}, "
        f"RUNTIME.json written (build {build_id})")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    if run_preflight(install_root) != 0:
        log("NOT_RUN: preflight blocked serve (see BLOCKER above)")
        return 3
    runtime = read_runtime(install_root)
    for key in ("backend_pid", "frontend_pid"):
        pid = (runtime or {}).get(key)
        if isinstance(pid, int) and pid_alive(pid):
            log(f"BLOCKED: {key} {pid} already running; run 'stop' first")
            return 3
    backend_port = args.backend_port
    frontend_port = args.frontend_port
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
        cwd=str(REPO), env=backend_env,
        stdout=backend_log, stderr=subprocess.STDOUT)
    log(f"backend pid {backend.pid} on 127.0.0.1:{backend_port}")
    if not wait_for(f"http://127.0.0.1:{backend_port}/health", 90,
                    "backend"):
        backend.terminate()
        log("NOT_RUN: backend /health never came up; serve aborted")
        return 3
    fe_env = os.environ.copy()
    fe_env["PORT"] = str(frontend_port)
    fe_env["NEXT_PUBLIC_API_URL"] = f"http://127.0.0.1:{backend_port}"
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        backend.terminate()
        log("NOT_RUN: BLOCKED_NODE_MISSING: npx not found on PATH; "
            "install Node.js 20+ (see docs/packaging/s12-windows.md)")
        return 3
    frontend_log = open(  # noqa: PTH123
        install_root / "logs" / "frontend.log", "a", encoding="utf-8")
    frontend = subprocess.Popen(
        [npx, "next", "start", "--port", str(frontend_port)],
        cwd=str(REPO / "frontend"), env=fe_env,
        stdout=frontend_log, stderr=subprocess.STDOUT)
    log(f"frontend pid {frontend.pid} on 127.0.0.1:{frontend_port}")
    if not wait_for(f"http://127.0.0.1:{frontend_port}/", 120, "frontend"):
        frontend.terminate()
        backend.terminate()
        log("NOT_RUN: frontend never came up; both processes stopped")
        return 3
    manifest = json.loads(
        (PKG / "manifest.json").read_text(encoding="utf-8"))
    build_id = ((manifest.get("frontend", {}) or {}).get("artifact", {})
                or {}).get("build_id")
    write_runtime(install_root,
                  {"schema": "s12-t06a-runtime/1",
                   "code_root": str(REPO),
                   "install_root": str(install_root),
                   "build_id": build_id,
                   "backend_port": backend_port,
                   "frontend_port": frontend_port,
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
    for key in ("backend_pid", "frontend_pid"):
        pid = (runtime or {}).get(key)
        procs[key] = {"pid": pid,
                      "alive": pid_alive(pid) if isinstance(pid, int)
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


def stop_pid(pid: int, label: str, timeout: float = 20.0) -> bool:
    if not pid_alive(pid):
        log(f"{label} pid {pid} already gone")
        return True
    if os.name == "nt":
        # Graceful first (whole process TREE: npx wrapper spawns the
        # real next-server child), then force.
        subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                       capture_output=True, timeout=10)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not pid_alive(pid):
                log(f"{label} pid {pid} stopped gracefully")
                return True
            time.sleep(0.5)
        subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                       capture_output=True, timeout=10)
        time.sleep(1.0)
        alive = pid_alive(pid)
        log(f"{label} pid {pid} "
            f"{'STILL ALIVE after /F' if alive else 'killed (/F fallback)'}")
        return not alive
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as err:
        log(f"{label} terminate failed: {err}")
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            log(f"{label} pid {pid} stopped gracefully")
            return True
        time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
        log(f"{label} pid {pid} killed (graceful timeout)")
        return False
    except OSError:
        return not pid_alive(pid)


def cmd_stop(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    runtime = read_runtime(install_root)
    if not runtime:
        log("stop: no RUNTIME.json; nothing to stop")
        return 0
    graceful = True
    fp = runtime.get("frontend_pid")
    if isinstance(fp, int):
        graceful = stop_pid(fp, "frontend") and graceful
    bp = runtime.get("backend_pid")
    if isinstance(bp, int):
        graceful = stop_pid(bp, "backend") and graceful
    runtime["backend_pid"] = None
    runtime["frontend_pid"] = None
    write_runtime(install_root, runtime)
    log("stop done (graceful)" if graceful else
        "stop done (SIGKILL fallback used)")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    install_root = resolve_install_root(args.install_root)
    cmd_stop(args)
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
                        "<repo>/.s12-t06a-runtime)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="s12_t06a_run.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    setup = sub.add_parser("setup")
    add_root_arg(setup)
    setup.add_argument("--backend-port", type=int,
                       default=DEFAULT_BACKEND_PORT)
    setup.add_argument("--frontend-port", type=int,
                       default=DEFAULT_FRONTEND_PORT)
    serve = sub.add_parser("serve")
    add_root_arg(serve)
    serve.add_argument("--backend-port", type=int,
                       default=DEFAULT_BACKEND_PORT)
    serve.add_argument("--frontend-port", type=int,
                       default=DEFAULT_FRONTEND_PORT)
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

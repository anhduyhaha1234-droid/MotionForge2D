#!/usr/bin/env python
"""Isolated runtime harness for MF-END-10/M1-01 (Manager-owned).

usage: m1_harness.py prepare|start|status|stop

- prepare : builds a NEW runtime root from the CORRECTION WORKTREE (tracked files only)
- start   : launches backend (8071) + frontend (3071) with verified pid/create_time/exe
- status  : liveness by pid + creation time + executable
- stop    : terminates ONLY the recorded pids, leaf-first

Never writes into the worktree. Never touches the user's port 3000 or any
pre-existing runtime. No GPU, no package install.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01")
RUNTIME = Path("C:/Users/Admin/AppData/Local/Temp/mfm1-01-20260930")
DEPS = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24/frontend/node_modules")
EXPECTED_HEAD = "a52fca897906fd61a088016dd802718fdf06d217"
API_PORT = 8071
UI_PORT = 3071
STATE = HERE / "runtime_processes_m1_01.json"


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(WORKTREE), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def start(name: str, args, cwd: Path, env: dict) -> dict:
    with (HERE / f"{name}.stdout.log").open("ab") as out, \
         (HERE / f"{name}.stderr.log").open("ab") as err:
        p = subprocess.Popen(args, cwd=str(cwd), env=env, stdout=out, stderr=err,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    import psutil
    proc = psutil.Process(p.pid)
    return dict(name=name, pid=p.pid, create_time=proc.create_time(),
                exe=proc.exe(), args=args, cwd=str(cwd))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "prepare":
        if RUNTIME.exists():
            raise SystemExit(f"runtime exists, preserve it: {RUNTIME}")
        if git("status", "--porcelain"):
            print("WARNING: worktree not clean at prepare time")
        head = git("rev-parse", "HEAD")
        if head != EXPECTED_HEAD:
            print(f"WARNING: worktree HEAD {head} != baseline {EXPECTED_HEAD} (expected after worker edits)")
        RUNTIME.mkdir(parents=True)
        for sub in ("data", "artifacts", "output"):
            (RUNTIME / sub).mkdir()
        files = subprocess.run(["git", "-C", str(WORKTREE), "ls-files", "-z", "frontend"],
                               capture_output=True, text=True, check=True).stdout.split("\0")
        manifest = []
        for rel in filter(None, files):
            src = WORKTREE / rel
            data = src.read_bytes()
            dst = RUNTIME / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            manifest.append(dict(path=rel, sha256=hashlib.sha256(data).hexdigest(),
                                 bytes=len(data)))
        # untracked-but-allowed new files (the worker's new component + spec)
        for rel in ("frontend/src/features/reference-library/CreateCharacterDialog.tsx",
                    "frontend/e2e/mf-m1-character-create.spec.ts"):
            src = WORKTREE / rel
            if src.is_file():
                data = src.read_bytes()
                dst = RUNTIME / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                manifest.append(dict(path=rel, sha256=hashlib.sha256(data).hexdigest(),
                                     bytes=len(data), untracked=True))
        save(HERE / "runtime_source_snapshot_m1_01.json",
             dict(head=head, source=str(WORKTREE), runtime=str(RUNTIME),
                  frontend=manifest))
        print(json.dumps(dict(runtime=str(RUNTIME), copied_frontend_files=len(manifest),
                              head=head)))
        return 0

    if mode == "start":
        if STATE.exists():
            raise SystemExit("state exists; verify stop before restart")
        for port in (API_PORT, UI_PORT):
            if not port_free(port):
                raise SystemExit(f"port {port} is not free")
        env = os.environ.copy()
        env.update(
            MOTIONFORGE_QA_MODE="1",
            MOTIONFORGE_ROOT=str(RUNTIME),
            MOTIONFORGE_OUTPUT=str(RUNTIME / "output"),
            MOTIONFORGE_DATABASE_URL="sqlite:///" + (RUNTIME / "data/motionforge.db").as_posix(),
            MOTIONFORGE_CORS_ORIGINS=f"http://127.0.0.1:{UI_PORT},http://localhost:{UI_PORT}",
            PYTHONPATH=str(WORKTREE),
            PYTHONDONTWRITEBYTECODE="1",
            NEXT_PUBLIC_API_URL=f"http://127.0.0.1:{API_PORT}",
            NEXT_TELEMETRY_DISABLED="1",
        )
        procs = [start("backend",
                       [sys.executable, "-B", "-m", "uvicorn", "app.main:app",
                        "--host", "127.0.0.1", "--port", str(API_PORT)],
                       RUNTIME, env)]
        save(STATE, procs)
        procs.append(start("frontend",
                           [shutil.which("node"), str(DEPS / "next/dist/bin/next"),
                            "dev", "--webpack", "--hostname", "127.0.0.1",
                            "--port", str(UI_PORT)],
                           RUNTIME / "frontend", env))
        save(STATE, procs)
        print(json.dumps(procs, indent=2))
        return 0

    if mode in ("status", "stop"):
        import psutil
        result = []
        for rec in json.loads(STATE.read_text(encoding="utf-8")):
            try:
                p = psutil.Process(rec["pid"])
                exact = abs(p.create_time() - rec["create_time"]) < 0.01 and p.exe() == rec["exe"]
                item = {**rec, "same_identity": exact, "running": p.is_running()}
                if mode == "stop" and exact:
                    children = p.children(recursive=True)
                    for c in children:
                        c.terminate()
                    p.terminate()
                    psutil.wait_procs([p, *children], timeout=15)
                    item["stop_requested"] = True
            except Exception as e:  # noqa: BLE001
                item = {**rec, "running": False, "error": str(e)}
            result.append(item)
        save(HERE / f"{mode}-{datetime.datetime.now().strftime('%H%M%S')}.json", result)
        print(json.dumps(result, indent=2))
        return 0

    raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    raise SystemExit(main())

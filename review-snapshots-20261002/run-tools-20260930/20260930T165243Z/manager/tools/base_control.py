#!/usr/bin/env python
"""Manager-run BASE CONTROL for the revert-sensitivity claim (decided before measuring).

Hypothesis: `e2e/mf-m1-character-create.spec.ts` FAILS against the PRE-PATCH
frontend and PASSES against the patched one. The only variable is WHICH frontend
serves UI port 3071; the spec file and the API (8071, QA DB) are held constant.

usage: base_control.py base|candidate
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z")
CORRECTION = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01")
BASE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01-base-control")
RUNTIME = Path("C:/Users/Admin/AppData/Local/Temp/mfm1-01-20260930")
DEPS = "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24/frontend/node_modules"
UI_PORT = 3071
API_PORT = 8071
STATE = HERE / "base_control_ui.json"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> int:
    mode = sys.argv[1]

    if mode == "stop":
        import psutil
        if not STATE.is_file():
            print(json.dumps({"status": "NO_STATE"}))
            return 0
        rec = json.loads(STATE.read_text(encoding="utf-8"))
        out = []
        for r in rec:
            try:
                p = psutil.Process(r["pid"])
                same = abs(p.create_time() - r["create_time"]) < 0.01 and p.exe() == r["exe"]
                item = {**r, "same_identity": same}
                if same:
                    ch = p.children(recursive=True)
                    for c in ch:
                        c.terminate()
                    p.terminate()
                    psutil.wait_procs([p, *ch], timeout=15)
                    item["stop_requested"] = True
            except Exception as e:  # noqa: BLE001
                item = {**r, "error": str(e)}
            out.append(item)
        STATE.unlink()
        print(json.dumps(out, indent=1))
        return 0

    tree = BASE if mode == "base" else CORRECTION
    if not port_free(UI_PORT):
        print(json.dumps({"status": "BLOCKED", "detail": f"UI port {UI_PORT} busy"}))
        return 2

    env = os.environ.copy()
    env.update(
        NEXT_PUBLIC_API_URL=f"http://127.0.0.1:{API_PORT}",
        NEXT_TELEMETRY_DISABLED="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    node = __import__("shutil").which("node")
    log = HERE / f"base_control_ui_{mode}.log"
    args = [node, str(tree / "frontend/node_modules/next/dist/bin/next"),
            "dev", "--webpack", "--hostname", "127.0.0.1", "--port", str(UI_PORT)]
    with log.open("wb") as fh:
        p = subprocess.Popen(args, cwd=str(tree / "frontend"), env=env,
                             stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    import psutil
    proc = psutil.Process(p.pid)
    rec = [{"mode": mode, "tree": str(tree), "pid": p.pid,
            "create_time": proc.create_time(), "exe": proc.exe(),
            "started_utc": utc(), "port": UI_PORT}]
    STATE.write_text(json.dumps(rec, indent=1), encoding="utf-8")

    # readiness probe (no model call)
    ready = False
    for _ in range(60):
        time.sleep(2)
        try:
            with socket.create_connection(("127.0.0.1", UI_PORT), timeout=2):
                ready = True
                break
        except OSError:
            continue
    print(json.dumps({"mode": mode, "tree": str(tree), "pid": p.pid,
                      "ready": ready, "state": str(STATE)}))
    return 0 if ready else 3


if __name__ == "__main__":
    raise SystemExit(main())

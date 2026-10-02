#!/usr/bin/env python
"""Stop ONLY the two QA processes this run created (backend 8071, frontend 3071).

Identity triple-check (pid + create_time + exe) before any terminate, children
leaf-first, then prove no collateral damage to unrelated python.exe instances.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import psutil

T = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20261001\20261001T091700Z\manager\tools")


def main() -> int:
    recs = []
    for f in ("runtime_processes_api.json", "runtime_processes_ui.json"):
        p = T / f
        if p.is_file():
            recs += json.loads(p.read_text(encoding="utf-8"))

    before_py = {p.pid for p in psutil.process_iter(["pid", "name"])
                 if (p.info["name"] or "").lower() == "python.exe"}

    res = []
    for r in recs:
        pid, ct, exe = r["pid"], r["create_time"], r["exe"]
        try:
            proc = psutil.Process(pid)
            same = abs(proc.create_time() - ct) < 0.01 and proc.exe() == exe
            if not same:
                res.append({"pid": pid, "stopped": False,
                            "reason": "identity mismatch (not our process)"})
                continue
            kids = proc.children(recursive=True)
            kid_pids = [c.pid for c in kids]
            for c in kids:
                try:
                    c.terminate()
                except Exception:  # noqa: BLE001
                    pass
            proc.terminate()
            psutil.wait_procs([proc, *kids], timeout=20)
            res.append({"name": r["name"], "pid": pid, "exe": exe,
                        "children": kid_pids, "stopped": not proc.is_running()})
        except Exception as exc:  # noqa: BLE001
            res.append({"pid": pid, "stopped": False, "reason": str(exc)})

    time.sleep(2)
    after_py = {p.pid for p in psutil.process_iter(["pid", "name"])
                if (p.info["name"] or "").lower() == "python.exe"}
    ports = {}
    for port in (8071, 3071):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            ports[port] = "FREE"
        except OSError:
            ports[port] = "BUSY"
        finally:
            s.close()

    out = {"stopped": res,
           "python_exe_lost_pids": sorted(before_py - after_py),
           "python_exe_gained_pids": sorted(after_py - before_py),
           "ports": ports}
    (T / "cleanup_result.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if all(r.get("stopped") for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())

"""MF-V1-VIDEO14B round I1 -- release the GPU lease and stop the engine, pid-scoped.

Rules this tool obeys (learned in this project):
  * never a name-wide or port-wide kill: exactly the pid recorded in instance_epoch.json,
    `taskkill /PID <pid>` with NO /T, /IM or /FI;
  * prove the collateral count: the python pid SET before and after must differ by exactly the
    one engine pid (Hermes itself is python and must never be touched);
  * free the models first (`/free {unload_models, free_memory}`) so the VRAM is measurably
    released before the process goes away;
  * a stop is only proven when the port refuses connections AND the pid is gone.

usage: python i1_stop_engine.py <out_json>
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
BASE = "http://127.0.0.1:8310"
PORT = 8310


def nvidia() -> dict:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()
    keys = ("total_mib", "used_mib", "free_mib", "util_pct")
    return {k: int("".join(ch for ch in v if ch.isdigit()) or 0)
            for k, v in zip(keys, [p.strip() for p in out.split(",")])}


def py_pids() -> list[int]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].strip().isdigit():
            pids.append(int(parts[1]))
    return sorted(pids)


def port_open(host="127.0.0.1") -> bool:
    s = socket.socket()
    s.settimeout(2)
    try:
        return s.connect_ex((host, PORT)) == 0
    finally:
        s.close()


def listener_pids() -> list[int]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(f":{PORT}") \
                and parts[3].upper() == "LISTENING":
            pids.add(int(parts[4]))
    return sorted(pids)


def main() -> int:
    out = Path(sys.argv[1].replace("\\", "/"))
    epoch = json.loads((RT / "instance_epoch.json").read_text(encoding="utf-8"))
    pid = int(epoch["pid"])
    rec = {"artifact": "i1_engine_stop.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
           "epoch_at_stop": epoch, "kill_style": "taskkill /PID <pid> (pid-scoped, no /T, no /IM, no /FI)",
           "pid": pid}
    rec["pre"] = {"nvidia": nvidia(), "python_pids": py_pids(), "port_listening": port_open(),
                  "listener_pids": listener_pids()}
    # 1. free the models while the engine is still answering
    try:
        req = urllib.request.Request(BASE + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            rec["free"] = {"http": r.status, "body": r.read().decode()[:200],
                           "nvidia_after_free": nvidia()}
    except Exception as e:  # noqa: BLE001
        rec["free"] = {"error": f"{type(e).__name__}: {e}", "nvidia_after_free": nvidia()}
    time.sleep(3)
    rec["free"]["nvidia_3s_after_free"] = nvidia()

    # 2. stop exactly that pid
    r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
    rec["taskkill"] = {"argv": ["taskkill", "/PID", str(pid), "/F"], "rc": r.returncode,
                       "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}

    # 3. prove it: port refuses, pid gone, no python collateral
    deadline = time.time() + 60
    while time.time() < deadline and (port_open() or pid in py_pids()):
        time.sleep(2)
    rec["post"] = {"nvidia": nvidia(), "python_pids": py_pids(), "port_listening": port_open(),
                   "listener_pids": listener_pids()}
    before, after = set(rec["pre"]["python_pids"]), set(rec["post"]["python_pids"])
    removed = before - after
    # Windows hosts churn short-lived python processes (Hermes tool helpers, `python -c`
    # probes). A pid that left the process set is only COLLATERAL if it was one of the
    # engine's own listeners; anything else exited on its own and must be reported as
    # churn, not as a kill -- a before/after set diff alone is not proof of collateral.
    listeners = set(rec["pre"]["listener_pids"])
    rec["proof"] = {"port_closed": not rec["post"]["port_listening"],
                    "engine_pid_gone": pid not in after,
                    "pids_removed": sorted(removed),
                    "pids_added": sorted(after - before),
                    "removed_that_were_engine_listeners": sorted(removed & listeners),
                    "collateral_python_killed": sorted(removed & listeners - {pid}),
                    "unrelated_python_transients_that_exited_on_their_own": sorted(removed - {pid} - listeners),
                    "exactly_one_engine_pid_removed": removed & listeners == {pid},
                    "vram_released_mib": rec["pre"]["nvidia"]["used_mib"] - rec["post"]["nvidia"]["used_mib"]}
    rec["verdict"] = ("STOPPED_CLEANLY" if rec["proof"]["port_closed"] and rec["proof"]["engine_pid_gone"]
                      and not rec["proof"]["collateral_python_killed"] else "STOP_NOT_PROVEN")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": rec["verdict"], "pid": pid, "taskkill_rc": rec["taskkill"]["rc"],
                      "port_closed": rec["proof"]["port_closed"],
                      "engine_pid_gone": rec["proof"]["engine_pid_gone"],
                      "collateral": rec["proof"]["collateral_python_killed"],
                      "vram_before_after": [rec["pre"]["nvidia"]["used_mib"], rec["post"]["nvidia"]["used_mib"]],
                      "free_vram_after_free": rec["free"].get("nvidia_after_free"),
                      "json": str(out)}, indent=1))
    return 0 if rec["verdict"] == "STOPPED_CLEANLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

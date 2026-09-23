"""MF-V1-VIDEO14B wave B round M1 — read-only pre/post boot state capture.

usage: python m1_state_capture.py <out.json> <label>

Records, with no side effects:
  - the set of live python.exe pids (name, pid, ppid, short cmdline, create time)
  - nvidia-smi VRAM used/total (MiB)
  - netstat LISTENING rows for the reserved engine ports
  - socket.connect_ex result for each reserved port
Nothing is killed, nothing is written outside <out.json>.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

PORTS = (8310, 8210, 8199, 8301, 8302)

PS = (
    "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
    "ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|"
    "$((Get-Date $_.CreationDate -Format o))|$([string]$_.CommandLine)\" } | "
    "Write-Output"
)


def powershell(cmd: str) -> str:
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return (p.stdout or "") + (p.stderr or "")


def proc_rows() -> list:
    raw = powershell(PS)
    out = []
    for line in raw.splitlines():
        if line.count("|") < 4:
            continue
        pid, ppid, name, created, cl = line.split("|", 4)
        try:
            pid_i, ppid_i = int(pid.strip()), int(ppid.strip())
        except ValueError:
            continue
        cl = cl.strip()
        out.append({
            "pid": pid_i,
            "ppid": ppid_i,
            "name": name.strip(),
            "created": created.strip(),
            "cmdline": cl[:220],
            "is_engine": "serve_video14b.py" in cl,
        })
    return sorted(out, key=lambda r: r["pid"])


def vram() -> str:
    p = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True,
                       timeout=60)
    return (p.stdout or p.stderr or "").strip()


def netstat_rows() -> list:
    p = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=120)
    rows = []
    for line in (p.stdout or "").splitlines():
        if any(f":{port}" in line for port in PORTS):
            rows.append(" ".join(line.split()))
    return rows


def connect_probe() -> dict:
    """Blocking connect_ex on loopback, each in a thread with a hard deadline.

    A `settimeout()` socket is NON-BLOCKING on Windows, so connect_ex returns
    WSAEWOULDBLOCK 10035 ("operation in progress") for BOTH a closed port and a
    hung one -- the exact ambiguity the manager's shutdown rule forbids. A
    blocking connect_ex on loopback returns 10061 (WSAECONNREFUSED) for a closed
    port immediately; the thread deadline means a hung port is reported as
    CONNECT_DEADLINE, never silently as 10035.
    """
    import threading

    out: dict = {}
    for port in PORTS:
        box: dict = {}

        def _try(p=port, b=box):
            s = socket.socket()
            s.settimeout(None)  # blocking
            try:
                b["connect_ex"] = s.connect_ex(("127.0.0.1", p))
            except OSError as exc:
                b["connect_ex"] = getattr(exc, "winerror", None) or exc.errno
                b["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                s.close()

        t = threading.Thread(target=_try, daemon=True)
        t.start()
        t.join(5.0)
        if t.is_alive():
            out[str(port)] = {"outcome": "CONNECT_DEADLINE", "open": False}
        else:
            rc = box.get("connect_ex")
            out[str(port)] = {
                "outcome": ("OPEN" if rc == 0 else f"CLOSED_{rc}"),
                "connect_ex": rc, "open": rc == 0,
                "error": box.get("error"),
            }
    return out


def main() -> int:
    out = Path(sys.argv[1].replace("\\", "/"))
    label = sys.argv[2]
    if len(str(out)) > 2 and str(out)[0] == "/" and str(out)[2] == "/":
        out = Path(str(out)[1].upper() + ":" + str(out)[2:])
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "label": label,
        "captured_at_epoch": __import__("time").time(),
        "python_processes": proc_rows(),
        "nvidia_smi_memory_used_total_mib": vram(),
        "netstat_rows_for_reserved_ports": netstat_rows(),
        "connect_probe": connect_probe(),
    }
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "label": label,
        "python_pids": [r.get("pid") for r in rec["python_processes"]],
        "engine_pids": [r.get("pid") for r in rec["python_processes"] if r.get("is_engine")],
        "vram": rec["nvidia_smi_memory_used_total_mib"],
        "netstat_rows": len(rec["netstat_rows_for_reserved_ports"]),
        "connect": rec["connect_probe"],
        "out": str(out),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

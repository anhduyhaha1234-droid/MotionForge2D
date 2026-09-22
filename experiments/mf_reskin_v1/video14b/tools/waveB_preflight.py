"""MF-V1-VIDEO14B wave B preflight (PREFLIGHT_OK evidence).

Measures, on this host, right now:
  - the worktree HEAD + porcelain (must be c4b50325... + ?? experiments/ only)
  - GPU memory/util (must be idle)
  - port state for 8210/8199/8301/8310 and the reserved engine port 8310
  - runtime/video14b presence + instance_epoch.json (pre-start, stale by design)
  - the input files wave B consumes

Writes JSON to stdout; the caller redirects into the evidence root.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1")
WT = ROOT / "wt-video14b"
RT = ROOT / "runtime" / "video14b"
ENGINE_PORT = 8310
PACKET_HEAD = "c4b50325afaf77b132bf0e90aa0d00c2ffb2651f"
PACKET_PARENT = "2594de06"


def run(cmd: list[str], cwd: Path | None = None) -> dict:
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=120, shell=False)
        return {"cmd": cmd, "returncode": p.returncode,
                "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except Exception as exc:  # noqa: BLE001
        return {"cmd": cmd, "returncode": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


def port_probe(port: int) -> dict:
    with socket.socket() as s:
        s.settimeout(2.0)
        try:
            s.connect(("127.0.0.1", port))
            return {"port": port, "connect": "accepted"}
        except Exception as exc:  # noqa: BLE001
            return {"port": port, "connect": f"refused:{getattr(exc, 'errno', None)}:{type(exc).__name__}"}


def main() -> int:
    out: dict = {"engine_port": ENGINE_PORT, "packet_head_expected": PACKET_HEAD,
                 "packet_parent": PACKET_PARENT, "cwd": os.getcwd()}

    out["git"] = {
        "head": run(["git", "rev-parse", "HEAD"], WT),
        "head_parent": run(["git", "rev-parse", "HEAD^"], WT),
        "status_porcelain": run(["git", "status", "--porcelain"], WT),
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"], WT),
    }
    out["git"]["head_matches_packet"] = out["git"]["head"]["stdout"] == PACKET_HEAD
    out["git"]["porcelain_lines"] = [ln for ln in out["git"]["status_porcelain"]["stdout"].splitlines() if ln.strip()]
    out["git"]["porcelain_untracked_only"] = all(
        ln.startswith("??") for ln in out["git"]["porcelain_lines"]) and bool(out["git"]["porcelain_lines"])

    out["gpu"] = run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,name",
                      "--format=csv,noheader,nounits"])

    out["ports"] = {p: port_probe(p) for p in (8210, 8199, 8301, ENGINE_PORT)}
    out["engine_port_free"] = out["ports"][ENGINE_PORT]["connect"].startswith("refused")

    out["runtime"] = {
        "dir_exists": RT.is_dir(),
        "subdirs": sorted(p.name for p in RT.iterdir() if p.is_dir()) if RT.is_dir() else [],
        "instance_epoch_present": (RT / "instance_epoch.json").is_file(),
        "instance_epoch_before_start": json.loads((RT / "instance_epoch.json").read_text(encoding="utf-8"))
        if (RT / "instance_epoch.json").is_file() else None,
        "leases": sorted(p.name for p in (RT / "leases").iterdir()) if (RT / "leases").is_dir() else [],
        "reservations": sorted(p.name for p in (RT / "reservations").iterdir()) if (RT / "reservations").is_dir() else [],
    }

    inp = RT / "input"
    out["inputs"] = {p.name: {"size": p.stat().st_size} for p in sorted(inp.iterdir()) if p.is_file()} if inp.is_dir() else {}
    wp = inp / "waveA_padded"
    out["inputs_waveA_padded"] = {p.name: {"size": p.stat().st_size} for p in sorted(wp.iterdir()) if p.is_file()} if wp.is_dir() else {}

    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

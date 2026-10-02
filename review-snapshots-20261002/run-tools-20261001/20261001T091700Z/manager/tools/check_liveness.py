#!/usr/bin/env python
"""Robust liveness check for the MF-END-10/M1-01 owner.

Reads the owner session id from a FILE so the id never appears in any argv
(a previous inline `python -c "<id>"` gate row matched ITSELF and reported a
phantom live worker — the string was in its own command line).

Prints the count of live dispatch-shaped processes that reference the owner.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
OWNER_FILE = HERE / "owner_session.txt"


def main() -> int:
    owner = OWNER_FILE.read_text(encoding="utf-8").strip()
    me = os.getpid()
    ancestors = set()
    try:
        p = psutil.Process(me)
        for _ in range(6):
            p = p.parent()
            if p is None:
                break
            ancestors.add(p.pid)
    except Exception:  # noqa: BLE001
        pass

    hits = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info["pid"] in ancestors or proc.info["pid"] == me:
            continue
        name = (proc.info["name"] or "").lower()
        if name in ("powershell.exe", "pwsh.exe", "bash.exe", "sh.exe", "cmd.exe"):
            continue
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
        except Exception:  # noqa: BLE001
            continue
        if owner in cmdline:
            hits.append((proc.info["pid"], proc.info["name"],
                         cmdline[:160]))

    print(f"owner={owner}")
    print(f"self_pid={me} ancestors={sorted(ancestors)}")
    print(f"live_worker_matches={len(hits)}")
    for h in hits:
        print(f"  hit pid={h[0]} name={h[1]} cmd={h[2]}")
    print("VERDICT=" + ("NO_LIVE_WORKER" if not hits else "WORKER_ALIVE"))
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())

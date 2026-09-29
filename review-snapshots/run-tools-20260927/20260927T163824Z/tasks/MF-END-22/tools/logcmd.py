"""Logged command runner (MF-END-12): appends one JSONL row per command.

Row: {label, argv, cwd, utc_start, utc_end, duration_s, exit, head, source_head,
      stdout_tail, stderr_tail} — appended to commands.jsonl in the evidence root.
Usage: python -B logcmd.py <label> <command> [args...]
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EVROOT = Path(__file__).resolve().parent.parent
LEDGER = EVROOT / "commands.jsonl"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: logcmd.py <label> <command> [args...]", file=sys.stderr)
        return 2
    label = sys.argv[1]
    argv = sys.argv[2:]
    start = time.time()
    utc_start = utc_now()
    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace")
    duration = round(time.time() - start, 3)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    row = {
        "label": label,
        "argv": argv,
        "cwd": os.getcwd(),
        "utc_start": utc_start,
        "utc_end": utc_now(),
        "duration_s": duration,
        "exit": proc.returncode,
        "head": git_head(),
        "stdout_tail": stdout[-1200:],
        "stderr_tail": stderr[-800:],
    }
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    print(f"[LOGGED {label} exit={proc.returncode} dur={duration}s]", file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

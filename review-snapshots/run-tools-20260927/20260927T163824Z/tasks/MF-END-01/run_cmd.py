#!/usr/bin/env python
"""MF-END-01 command harness — runs a command and appends an auditable row.

Every command executed through this harness gets ONE row in commands.jsonl with
UTC start/end, duration, exit code and the source HEAD of the worktree under test.
Full stdout/stderr are written next to the ledger (raw/cmd_<id>_*.txt) and only a
compact tail is printed, so tool payloads stay small.

usage:  python run_cmd.py <cwd> -- <argv...>
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUN_ROOT = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-01"
)
LEDGER = RUN_ROOT / "commands.jsonl"
RAW = RUN_ROOT / "raw"
WORKTREE = r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01"


def _head(cwd: str) -> str:
    for probe_cwd in (cwd, WORKTREE):
        try:
            out = subprocess.run(
                ["git", "-C", probe_cwd, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if out.returncode == 0:
                suffix = "" if probe_cwd == cwd else f" (worktree HEAD; cwd={cwd} is not a git dir)"
                return out.stdout.strip() + suffix
        except Exception as exc:  # pragma: no cover - defensive
            return f"<error:{type(exc).__name__}>"
    return "<unresolved>"


def main() -> int:
    argv = sys.argv[1:]
    if "--" not in argv:
        print("usage: run_cmd.py <cwd> -- <argv...>")
        return 2
    split = argv.index("--")
    cwd = argv[0] if split else WORKTREE
    cmd = argv[split + 1 :]
    if not cmd:
        print("empty command")
        return 2
    RAW.mkdir(parents=True, exist_ok=True)
    cmd_id = hashlib.sha1((dt.datetime.now(dt.timezone.utc).isoformat() + " ".join(cmd)).encode()).hexdigest()[:12]
    t0 = time.time()
    start = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    head_before = _head(cwd)
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    dur = round(time.time() - t0, 3)
    end = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    head_after = _head(cwd)
    stdout_path = RAW / f"cmd_{cmd_id}_stdout.txt"
    stderr_path = RAW / f"cmd_{cmd_id}_stderr.txt"
    stdout_path.write_text(proc.stdout or "", encoding="utf-8", newline="")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8", newline="")
    row = {
        "cmd_id": cmd_id,
        "utc_start": start,
        "utc_end": end,
        "duration_s": dur,
        "exit_code": proc.returncode,
        "source_head_before": head_before,
        "source_head_after": head_after,
        "cwd": cwd,
        "argv": cmd,
        "stdout_file": str(stdout_path),
        "stderr_file": str(stderr_path),
        "stdout_tail": (proc.stdout or "")[-200:],
        "stderr_tail": (proc.stderr or "")[-200:],
    }
    with LEDGER.open("a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"CMD {cmd_id} rc={proc.returncode} dur={dur}s head={head_before[:12]}")
    tail = (proc.stdout or "").strip().splitlines()[-4:]
    for line in tail:
        print("  | " + line[:180])
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-6:]
        for line in err:
            print("  ! " + line[:180])
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

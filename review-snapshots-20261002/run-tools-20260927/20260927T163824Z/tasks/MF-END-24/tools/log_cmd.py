"""Append-only command ledger for MF-END-24 evidence (UTC timestamps).

Usage: python tools/log_cmd.py <label> -- <command...>
Runs the command, appends one JSONL row to commands.jsonl in the task root,
and mirrors stdout/stderr into raw/<label>.log.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "commands.jsonl"
RAW = ROOT / "raw"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    cwd = os.environ.get("LOG_CMD_CWD") or None
    # Windows shims (npx.cmd, npm.cmd) are not directly spawnable; resolve and
    # fall back to a shell for .cmd/.bat executables only.
    exe = shutil.which(command[0])
    if exe and exe.lower().endswith((".cmd", ".bat")):
        return subprocess.run(
            subprocess.list2cmdline(command),
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("usage: log_cmd.py <label> -- <command...>", file=sys.stderr)
        return 2
    split = argv.index("--")
    label = argv[0]
    command = argv[split + 1 :]
    RAW.mkdir(parents=True, exist_ok=True)
    start = datetime.now(timezone.utc)
    t0 = time.monotonic()
    proc = _run(command)
    duration = time.monotonic() - t0
    end = datetime.now(timezone.utc)
    log_path = RAW / f"{label}.log"
    log_path.write_text(
        f"$ {' '.join(command)}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n",
        encoding="utf-8",
    )
    tail = "\n".join([ln for ln in proc.stdout.strip().splitlines()[-3:]])
    row = {
        "label": label,
        "command": " ".join(command),
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "duration_s": round(duration, 2),
        "exit": proc.returncode,
        "stdout_tail": tail,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
    }
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({k: row[k] for k in ("label", "exit", "duration_s", "stdout_tail")}, ensure_ascii=False))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

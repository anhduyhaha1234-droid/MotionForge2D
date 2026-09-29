#!/usr/bin/env python
"""CMC-correction lane launcher (Manager tool).

usage: dispatch_lane.py <packet.md> <task_id> <cwd> <log> <receipt.json> [--resume <session>] [--max-turns N]

- Passes the packet as a REAL argv element (proven R28 shape).
- Pins provider/model per lane: custom / cmc/deepseek/deepseek-v4.1-flash, chat_completions, fallback OFF.
- Append-only dispatch ledger row BEFORE launch; receipt updated on exit.
- Refuses to launch if packet > 28000 chars (argv ceiling ~32.5K on Windows).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROVIDER = "custom"
MODEL = "cmc/deepseek/deepseek-v4.1-flash"
BASE_URL = "http://127.0.0.1:20128/v1"
API_MODE = "chat_completions"
RUN_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z")
LEDGER = RUN_ROOT / "ledgers" / "dispatch-ledger.jsonl"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_ledger(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    packet_path = Path(sys.argv[1])
    task_id = sys.argv[2]
    cwd = sys.argv[3]
    log_path = Path(sys.argv[4])
    receipt_path = Path(sys.argv[5])
    extra = sys.argv[6:]

    prompt = packet_path.read_text(encoding="utf-8")
    nbytes = len(prompt.encode("utf-8"))
    if nbytes > 28000:
        print(f"REFUSED: packet {nbytes} bytes > 28000 (argv ceiling)")
        return 2

    resume = None
    if "--resume" in extra:
        resume = extra[extra.index("--resume") + 1]
    max_turns = "160"
    if "--max-turns" in extra:
        max_turns = extra[extra.index("--max-turns") + 1]

    argv = ["hermes", "chat", "-q", prompt, "--provider", PROVIDER, "-m", MODEL,
            "--pass-session-id", "--no-restore-cwd", "--max-turns", max_turns]
    if resume:
        argv += ["--resume", resume]

    started = utc()
    receipt = {
        "task_id": task_id,
        "round": Path(packet_path).stem,
        "packet": str(packet_path),
        "packet_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "packet_bytes": nbytes,
        "cwd": cwd,
        "provider": PROVIDER,
        "model": MODEL,
        "base_url": BASE_URL,
        "api_mode": API_MODE,
        "fallback": False,
        "resume_session_requested": resume,
        "max_turns": max_turns,
        "argv_shape": ["hermes", "chat", "-q", "<PACKET>", "--provider", PROVIDER,
                       "-m", MODEL, "--pass-session-id", "--no-restore-cwd",
                       "--max-turns", max_turns] + (["--resume", resume] if resume else []),
        "utc_start": started,
        "launcher_pid": os.getpid(),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_ledger({"action": "dispatch", "task_id": task_id, "at_utc": started,
                   "model": MODEL, "cwd": cwd, "resume_session_requested": resume,
                   "packet": str(packet_path), "packet_sha256": receipt["packet_sha256"],
                   "packet_bytes": nbytes, "receipt": str(receipt_path), "log": str(log_path),
                   "launcher_pid": os.getpid()})

    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("wb") as log:
        proc = subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env=env)

    ended = utc()
    receipt.update({
        "exit_code": proc.returncode,
        "utc_end": ended,
        "log": str(log_path),
        "note": "exit code alone is NOT completion proof - read the log payload",
    })
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_ledger({"action": "exit", "task_id": task_id, "at_utc": ended,
                   "exit_code": proc.returncode, "receipt": str(receipt_path),
                   "log": str(log_path), "log_bytes": log_path.stat().st_size if log_path.exists() else 0})
    print(f"exit={proc.returncode} log={log_path}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

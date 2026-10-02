#!/usr/bin/env python
"""MF-END-10/M1-01 dispatcher (Manager-owned).

usage: dispatch_m1_01.py <packet.md> <task_id> <cwd> <log> <receipt.json> [--resume SID] [--max-turns N]

Proven argv shape (same as the CMC-correction launcher): the packet is a REAL
argv element. Pins provider/model per lane and enforces a hard subprocess
WALL-CLOCK deadline (the one guard the old launcher lacked).

Budget note: --max-turns limits tool-calling ITERATIONS per conversation turn, it
is NOT a cumulative provider-request budget. The request count is measured after
the run from the read-only session DB. On deadline expiry the child is killed and
the receipt records TIMEOUT so the Manager submits PARTIAL/BLOCKED_BUDGET.
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
DEADLINE_SECONDS = 120 * 60

RUN_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z")
LEDGER = RUN_ROOT / "manager" / "DISPATCH_LEDGER.jsonl"


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
        print(f"REFUSED: packet {nbytes} bytes > 28000 (Windows argv ceiling)")
        return 2

    resume = extra[extra.index("--resume") + 1] if "--resume" in extra else None
    max_turns = extra[extra.index("--max-turns") + 1] if "--max-turns" in extra else "160"

    argv = ["hermes", "chat", "-q", prompt, "--provider", PROVIDER, "-m", MODEL,
            "--pass-session-id", "--no-restore-cwd", "--max-turns", max_turns]
    if resume:
        argv += ["--resume", resume]

    started = utc()
    receipt = {
        "task_id": task_id,
        "round": packet_path.stem,
        "packet": str(packet_path),
        "packet_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "packet_bytes": nbytes,
        "cwd": cwd,
        "provider": PROVIDER,
        "model": MODEL,
        "base_url": BASE_URL,
        "api_mode_pinned_in_packet": API_MODE,
        "fallback": False,
        "resume_session_requested": resume,
        "max_turns": max_turns,
        "deadline_seconds": DEADLINE_SECONDS,
        "argv_shape": ["hermes", "chat", "-q", "<PACKET>", "--provider", PROVIDER,
                       "-m", MODEL, "--pass-session-id", "--no-restore-cwd",
                       "--max-turns", max_turns] + (["--resume", resume] if resume else []),
        "utc_start": started,
        "launcher_pid": os.getpid(),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    append_ledger({"action": "dispatch", "task_id": task_id, "at_utc": started,
                   "model": MODEL, "cwd": cwd, "resume_session_requested": resume,
                   "packet": str(packet_path), "packet_sha256": receipt["packet_sha256"],
                   "packet_bytes": nbytes, "receipt": str(receipt_path),
                   "log": str(log_path), "launcher_pid": os.getpid(),
                   "deadline_seconds": DEADLINE_SECONDS})

    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    timed_out = False
    with log_path.open("wb") as log:
        try:
            proc = subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                  env=env, timeout=DEADLINE_SECONDS)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            rc = None

    ended = utc()
    receipt.update({
        "exit_code": rc,
        "utc_end": ended,
        "timed_out": timed_out,
        "log": str(log_path),
        "log_bytes": log_path.stat().st_size if log_path.exists() else 0,
        "note": ("exit code alone is NOT completion proof - read the log payload; "
                 "a 125-byte log with 'API call failed after 3 retries' means the "
                 "lane did nothing"),
    })
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    append_ledger({"action": "exit", "task_id": task_id, "at_utc": ended,
                   "exit_code": rc, "timed_out": timed_out,
                   "receipt": str(receipt_path), "log": str(log_path),
                   "log_bytes": receipt["log_bytes"]})
    print(f"exit={rc} timed_out={timed_out} log={log_path}")
    return rc if rc is not None else 3


if __name__ == "__main__":
    raise SystemExit(main())

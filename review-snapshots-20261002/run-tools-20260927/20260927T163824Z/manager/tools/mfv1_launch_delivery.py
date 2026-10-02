#!/usr/bin/env python
"""Delivery launcher (Manager tool) — R28-proven shape.

usage: mfv1_launch_delivery.py <packet.md> <cwd> <log> <receipt.json> --resume <session>

Passes the packet as a real argv element; pins provider/model per session; forces
unbuffered output so the Manager can tail live progress.
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
MODEL = "ocg/deepseek-v4.1-flash"


def main() -> int:
    packet_path = Path(sys.argv[1])
    cwd = sys.argv[2]
    log_path = Path(sys.argv[3])
    receipt_path = Path(sys.argv[4])
    extra = sys.argv[5:]

    prompt = packet_path.read_text(encoding="utf-8")
    argv = ["hermes", "chat", "-q", prompt, "--provider", PROVIDER, "-m", MODEL,
            "--pass-session-id", "--no-restore-cwd", "--max-turns", "160", *extra]

    started = datetime.now(timezone.utc)
    receipt = {
        "task_packet": str(packet_path),
        "packet_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest().upper(),
        "packet_bytes": len(prompt.encode("utf-8")),
        "cwd": cwd,
        "provider": PROVIDER,
        "model": MODEL,
        "base_url": "http://127.0.0.1:20128/v1",
        "api_mode": "chat_completions",
        "fallback": False,
        "argv_shape": ["hermes", "chat", "-q", "<PACKET>", "--provider", PROVIDER,
                       "-m", MODEL, "--pass-session-id", "--no-restore-cwd",
                       "--max-turns", "160", *extra],
        "started_at_utc": started.isoformat(),
        "utc_start": started.isoformat(),
        "pid": os.getpid(),
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("wb") as log:
        proc = subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env=env)

    ended = datetime.now(timezone.utc)
    receipt.update({
        "exit_code": proc.returncode,
        "utc_end": ended.isoformat(),
        "ended_at_utc": ended.isoformat(),
        "duration_seconds": round((ended - started).total_seconds(), 3),
        "log": str(log_path),
    })
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    print(f"exit={proc.returncode} duration={receipt['duration_seconds']}s log={log_path}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

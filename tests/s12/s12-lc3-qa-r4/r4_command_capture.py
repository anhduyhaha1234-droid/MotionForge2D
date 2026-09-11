"""Small QA-only command envelope writer for the R4 evidence lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parsed, command = parser.parse_known_args()
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    output_dir = Path(parsed.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    monotonic_started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=parsed.cwd,
            capture_output=True,
            text=True,
            timeout=parsed.timeout,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stderr += f"\nTIMEOUT after {parsed.timeout}s\n"
    ended = datetime.now(UTC)
    duration = time.monotonic() - monotonic_started
    stem = output_dir / parsed.name
    (stem.with_suffix(".stdout.txt")).write_text(stdout, encoding="utf-8")
    (stem.with_suffix(".stderr.txt")).write_text(stderr, encoding="utf-8")
    envelope = {
        "name": parsed.name,
        "argv": command,
        "cwd": str(Path(parsed.cwd).resolve()),
        "started_utc": started.isoformat(),
        "ended_utc": ended.isoformat(),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "timeout_seconds": parsed.timeout,
        "timed_out": timed_out,
        "stdout": str(stem.with_suffix(".stdout.txt")),
        "stderr": str(stem.with_suffix(".stderr.txt")),
        "stdout_sha256": _sha256(stem.with_suffix(".stdout.txt")),
        "stderr_sha256": _sha256(stem.with_suffix(".stderr.txt")),
    }
    envelope_path = stem.with_suffix(".command.json")
    envelope_path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"envelope": str(envelope_path), **envelope}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

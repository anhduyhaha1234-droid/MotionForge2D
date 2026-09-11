"""Bounded QA-owned process audit; it never terminates a process."""

from __future__ import annotations

import json

import psutil


def main() -> int:
    needles = (
        "r4_public_producer_chain_harness",
        "r4_readonly_audit",
        "s12-r4",
    )
    rows = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = process.info.get("name") or ""
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if name.lower() not in {"python.exe", "ffmpeg.exe", "node.exe", "uvicorn.exe"}:
            continue
        if "r4_command_capture.py" in command.lower():
            continue
        if any(needle.lower() in command.lower() for needle in needles):
            rows.append({"pid": process.info["pid"], "name": name, "cmdline": command})
    print(json.dumps({"qa_owned_matches": rows, "count": len(rows)}, sort_keys=True))
    return 0 if not rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

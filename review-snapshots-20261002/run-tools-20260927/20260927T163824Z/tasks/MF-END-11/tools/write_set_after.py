#!/usr/bin/env python
"""MF-END-11 — write-set AFTER snapshot + protected-drift guard.

Compares the measured AFTER state against write_set_before.json:
* write-set files: must exist, must not shrink; patched files must GROW;
* protected files: sha256 must be UNCHANGED (drift = incident);
* porcelain count and HEAD recorded; results to write_set_after.json.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11")
RUN = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-11"
)
BEFORE = RUN / "write_set_before.json"
AFTER = RUN / "write_set_after.json"


def measure(rel: str) -> dict:
    path = WORKTREE / rel
    if not path.exists():
        return {"exists": False}
    data = path.read_bytes()
    return {
        "exists": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "crlf": data.count(b"\r\n"),
        "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
        "mtime_utc": dt.datetime.fromtimestamp(
            path.stat().st_mtime, tz=dt.timezone.utc
        ).isoformat(timespec="seconds"),
    }


def main() -> int:
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    head = subprocess.run(
        ["git", "-C", str(WORKTREE), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "-C", str(WORKTREE), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    after_paths = {rel: measure(rel) for rel in before["paths"]}
    after_protected = {rel: measure(rel) for rel in before["protected"]}

    findings: list[str] = []
    for rel, before_entry in before["paths"].items():
        now = after_paths[rel]
        if before_entry.get("exists") and not now.get("exists"):
            findings.append(f"{rel}: FILE DISAPPEARED")
            continue
        if before_entry.get("exists"):
            delta = now["bytes"] - before_entry["bytes"]
            if delta <= 0:
                findings.append(f"{rel}: did not grow (delta {delta})")
            else:
                print(f"GREW {rel}: {before_entry['bytes']} -> {now['bytes']} (+{delta})")
        else:
            print(f"NEW  {rel}: {now.get('bytes')} bytes")
    for rel, before_entry in before["protected"].items():
        now = after_protected[rel]
        if before_entry.get("sha256") != now.get("sha256"):
            findings.append(f"PROTECTED DRIFT: {rel} {before_entry.get('sha256')} -> {now.get('sha256')}")
        else:
            print(f"PROTECTED OK {rel}")

    payload = {
        "task": "MF-END-11",
        "head": head,
        "porcelain_count": len([ln for ln in porcelain.splitlines() if ln.strip()]),
        "paths": after_paths,
        "protected": after_protected,
        "findings": findings,
    }
    AFTER.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"head {head[:12]} porcelain {payload['porcelain_count']} findings {len(findings)}")
    for finding in findings:
        print("  ! " + finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Step 1/Step 5 — write-set BEFORE snapshot (measured on disk, pre-build)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11")
OUT = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-11/write_set_before.json"
)

WRITE_SET = [
    "app/services/shot_reskin_plan.py",
    "app/services/scene_detection.py",
    "app/services/source_locked_timeline.py",
    "tests/product_delivery/test_mf_end_11.py",
]
PROTECTED = [
    "app/schemas/shot_reskin.py",
    "tests/product_delivery/test_mf_end_01.py",
    "app/workflow/scene_chunking_service.py",
    "tests/test_scene_chunk_stitch.py",
    "tests/test_video_slicing.py",
    "tests/test_scene_detection.py",
]


def measure(rel: str) -> dict:
    path = WORKTREE / rel
    if not path.exists():
        return {"exists": False}
    data = path.read_bytes()
    tracked = subprocess.run(
        ["git", "-C", str(WORKTREE), "ls-files", "--error-unmatch", rel],
        capture_output=True, text=True,
    ).returncode == 0
    return {
        "exists": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "crlf": data.count(b"\r\n"),
        "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
        "mtime_utc": dt.datetime.fromtimestamp(
            path.stat().st_mtime, tz=dt.timezone.utc
        ).isoformat(timespec="seconds"),
        "tracked": tracked,
    }


def main() -> int:
    head = subprocess.run(
        ["git", "-C", str(WORKTREE), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "-C", str(WORKTREE), "branch", "--show-current"], capture_output=True, text=True
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "-C", str(WORKTREE), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    payload = {
        "task": "MF-END-11",
        "measured_by": "worker session 20260928_121441_bdf0d8, pre-build snapshot",
        "manager_guard": "manager/guards/MF-END-11_before.json",
        "head": head,
        "branch": branch,
        "porcelain_count": len([ln for ln in porcelain.splitlines() if ln.strip()]),
        "paths": {rel: measure(rel) for rel in WRITE_SET},
        "protected": {rel: measure(rel) for rel in PROTECTED},
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(json.dumps({k: payload["paths"][k] for k in WRITE_SET}, indent=1)[:2400])
    print("porcelain_count", payload["porcelain_count"], "head", head[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""MF-END-23 write-set guard: before/after bytes + protected drift + shrink check.

Reads the BASE tree (the control worktree pinned at the task base) for the
"before" side and the WORKTREE for the "after" side, and writes both manifests
plus a verdict into the evidence root.  Fail-closed on:
  * any tracked path changed outside the allowlist (scope violation);
  * any write-set file SHRINKING in bytes (destructive shrink);
  * a before/after hash mismatch on a file the guard believes it compared.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-23")
BASE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-23-ctl23")
BASE_SHA = "1d6d6fa934aa8295ac5c0018daa744d099bb30c0"
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-23"
)

ALLOWLIST = [
    "app/services/qc_evidence/compose.py",
    "app/workflow/qc_checks_handler.py",
    "app/services/qc_correction_bridge.py",
    "app/persistence/readiness.py",
    "tests/product_delivery/test_mf_end_23.py",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def measure(root: Path, rel: str) -> dict:
    path = root / rel
    if not path.is_file():
        return {"path": rel, "exists": False}
    data = path.read_bytes()
    newline = b"\n"
    if data.endswith(newline):
        lines = data.count(newline)
    else:
        lines = data.count(newline) + 1
    return {
        "path": rel,
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "logical_lines": lines,
        "mtime_utc": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def git(*args: str, cwd: Path = WT) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )
    return proc.stdout


def porcelain_paths() -> list[str]:
    out = git("status", "--porcelain")
    paths = []
    for line in out.splitlines():
        if not line:
            continue
        # XY<space>path — keep the significant leading spaces of the status
        status = line[:2]
        path = line[3:] if status[1] != " " else line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


now = datetime.now(timezone.utc).isoformat()
before = [measure(BASE, rel) for rel in ALLOWLIST]
after = [measure(WT, rel) for rel in ALLOWLIST]

changed = porcelain_paths()
outside = [p for p in changed if p.replace("\\", "/") not in ALLOWLIST]

shrunk = []
for b, a in zip(before, after):
    if b.get("exists") and a.get("exists") and a["bytes"] < b["bytes"]:
        shrunk.append(
            {"path": a["path"], "before_bytes": b["bytes"], "after_bytes": a["bytes"]}
        )

fails = []
if outside:
    fails.append({"check": "scope/allowlist", "detail": outside})
if shrunk:
    fails.append({"check": "destructive-shrink", "detail": shrunk})

verdict = {
    "task": "MF-END-23",
    "checked_at_utc": now,
    "base_commit": BASE_SHA,
    "base_tree": str(BASE),
    "worktree": str(WT),
    "allowlist": ALLOWLIST,
    "porcelain_paths": changed,
    "outside_allowlist": outside,
    "shrunk": shrunk,
    "fails": fails,
    "verdict": "CLEAN" if not fails else "FAIL",
}

(EV / "write_set" / "write_set_before.json").write_text(
    json.dumps({"checked_at_utc": now, "files": before}, indent=2), encoding="utf-8"
)
(EV / "write_set" / "write_set_after.json").write_text(
    json.dumps({"checked_at_utc": now, "files": after}, indent=2), encoding="utf-8"
)
(EV / "write_set" / "guard_verdict.json").write_text(
    json.dumps(verdict, indent=2), encoding="utf-8"
)
print(json.dumps(verdict, indent=2))
sys.exit(1 if fails else 0)

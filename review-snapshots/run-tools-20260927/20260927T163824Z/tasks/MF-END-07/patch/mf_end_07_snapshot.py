"""MF-END-07 write-set + protected-set snapshot (before/after), read-only.

Usage: python mf_end_07_snapshot.py before|after
Writes <run>/write_set/<tag>.json with sha256/bytes/logical-lines/mtime and
git attribution for every write-set path and every protected path.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)
BASE = "213832ae38ae734184164e3b52a54098bb21d52a"

WRITE_SET = [
    "app/api/routes/project_cast.py",
    "app/schemas/project_cast.py",
    "tests/product_delivery/test_mf_end_07.py",
]
PROTECTED = [
    "app/api/app.py",
    "app/persistence/project_cast.py",
    "app/services/cast_recommendation.py",
    "app/schemas/cast_recommendation.py",
    "app/schemas/shot_reskin.py",
    "app/persistence/models.py",
    "tests/conftest.py",
    "tests/product_delivery/test_mf_end_04.py",
    "tests/product_delivery/test_mf_end_05.py",
    "tests/product_delivery/test_mf_end_06.py",
    "tests/product_p1/public_chain/",
]


def run(cmd: str) -> str:
    proc = subprocess.run(
        cmd, cwd=ROOT, shell=True, capture_output=True, text=True, check=False
    )
    return proc.stdout


def logical_lines(data: bytes) -> int:
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def entry(rel: str) -> dict:
    path = ROOT / rel
    if rel.endswith("/") or path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file())
        return {
            "path": rel,
            "kind": "dir",
            "file_count": len(files),
            "files": [
                {
                    "path": str(p.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
                for p in files
            ],
        }
    if not path.exists():
        return {"path": rel, "state": "ABSENT"}
    data = path.read_bytes()
    tracked = (
        subprocess.run(
            ["git", "cat-file", "-e", f"{BASE}:{rel}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    return {
        "path": rel,
        "state": "TRACKED_AT_BASE" if tracked else "ABSENT_AT_BASE",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "logical_lines": logical_lines(data),
        "mtime_utc": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "git_status": [
            line
            for line in run("git status --porcelain").splitlines()
            if rel in line
        ],
    }


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "before"
    assert tag in ("before", "after"), tag
    record = {
        "task": "MF-END-07",
        "tag": tag,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "base_head": BASE,
        "head_now": run("git rev-parse HEAD").strip(),
        "porcelain_now": run("git status --porcelain").splitlines(),
        "write_set": [entry(rel) for rel in WRITE_SET],
        "protected": [entry(rel) for rel in PROTECTED],
    }
    out = EV / "write_set" / f"{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1), encoding="utf-8")
    for item in record["write_set"]:
        print(tag, item["path"], item.get("state", "?"), item.get("bytes", ""))
    print("PROTECTED_N", len(record["protected"]), "PORCELAIN", len(record["porcelain_now"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

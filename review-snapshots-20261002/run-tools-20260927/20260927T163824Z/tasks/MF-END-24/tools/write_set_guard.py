"""MF-END-24 byte-safe write-set guard (before/after + porcelain + protected drift).

Runs at the worktree root.  Writes into the task evidence root:
  write_set/before.json      — base-commit state of the allowlist + protected sample
  write_set/after.json       — working-tree state + porcelain
  write_set/guard_verdict.json — allowlist scope, protected drift, shrink checks
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24")
ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-24"
)
BASE = "4444f8c3898057b66560ccf727909bb87065b61c"
WS = ROOT / "write_set"

ALLOWLIST = [
    "frontend/src/features/shot-review/",
    "frontend/src/features/demo/",
    "frontend/src/features/apply/",
    "tests/product_delivery/test_mf_end_24.py",
]
#: Protected files sampled for byte drift against the base commit.
PROTECTED = [
    "frontend/src/lib/api.ts",
    "frontend/src/app/(app)/apply/page.tsx",
    "frontend/src/app/(app)/demo-compare/page.tsx",
    "app/api/routes/s10_full_apply.py",
    "app/api/routes/qc_items.py",
    "app/services/shot_reskin_cache.py",
    "tests/product_delivery/test_mf_end_23.py",
    "tests/conftest.py",
]


def sh(args: list[str]) -> str:
    return subprocess.run(args, cwd=str(WT), capture_output=True, text=True, encoding="utf-8").stdout


def blob_sha(rev: str, path: str) -> str | None:
    out = subprocess.run(
        ["git", "rev-parse", f"{rev}:{path}"],
        cwd=str(WT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return out.stdout.strip() if out.returncode == 0 else None


def file_stat(path: Path) -> dict:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    return {
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
        "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
    }


def tracked_paths() -> list[str]:
    out = sh(["git", "ls-files"])
    return [ln for ln in out.splitlines() if ln.strip()]


def porcelain() -> list[str]:
    out = sh(["git", "status", "--porcelain"])
    # NB: never strip() the aggregate output — an unstaged change starts with a
    # significant leading space.  Slice per line and strip only the path part.
    rows = []
    for raw in out.splitlines():
        if not raw:
            continue
        status, rest = raw[:2], raw[3:]
        path = rest.split(" -> ")[-1].strip()
        rows.append({"status": status, "path": path})
    return rows


def in_allowlist(path: str) -> bool:
    return any(path == a or path.startswith(a) for a in ALLOWLIST)


def main() -> int:
    WS.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "before"

    if mode == "before":
        base_files = {}
        for path in tracked_paths():
            if in_allowlist(path) or path in PROTECTED:
                base_files[path] = {"blob": blob_sha(BASE, path)}
        payload = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "base": BASE,
            "allowlist": ALLOWLIST,
            "base_state": base_files,
            "note": "allowlist files absent from base_state are NEW files created by this task",
        }
        (WS / "before.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"mode": mode, "tracked_sampled": len(base_files)}))
        return 0

    # after / guard
    changed = porcelain()
    outside = [row for row in changed if not in_allowlist(row["path"])]
    drift = []
    for path in PROTECTED:
        base_blob = blob_sha(BASE, path)
        head_blob = blob_sha("HEAD", path)
        wt = WT / path
        wt_sha = file_stat(wt)["sha256"] if wt.exists() else None
        if base_blob != head_blob:
            drift.append({"path": path, "base_blob": base_blob, "head_blob": head_blob})
    shrink = []
    after_files = {}
    for row in changed:
        path = WT / row["path"]
        if path.is_file() and not row["path"].endswith("/"):
            after_files[row["path"]] = file_stat(path)
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "head": sh(["git", "rev-parse", "HEAD"]).strip(),
        "porcelain": changed,
        "outside_allowlist": outside,
        "protected_drift": drift,
        "after_state": after_files,
    }
    (WS / f"{mode}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    verdict = {
        "generated_utc": payload["generated_utc"],
        "head": payload["head"],
        "porcelain_empty": changed == [],
        "porcelain_count": len(changed),
        "scope_ok": outside == [],
        "protected_drift": drift,
        "changed_files": [row["path"] for row in changed],
        "verdict": "CLEAN" if (outside == [] and drift == []) else "VIOLATION",
    }
    (WS / "guard_verdict.json").write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if verdict["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())

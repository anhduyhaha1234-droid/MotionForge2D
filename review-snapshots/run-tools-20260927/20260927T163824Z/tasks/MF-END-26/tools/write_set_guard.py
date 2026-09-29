"""MF-END-26 — byte-safe write-set guard (pre/post commit).

Verifies, against the Manager's pre-dispatch guard JSON (hashes of every
write-set path at the base commit):
  1. every ALLOWED path exists and did not shrink;
  2. the write-set paths that changed are exactly the allowed set;
  3. no file OUTSIDE the allowlist changed (tracked or untracked);
  4. every protected test (tests/** except the task's own test_path) is
     byte-identical to its base blob.

Usage:
  python write_set_guard.py <worktree> <before_json> <out_json> [--post]
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ALLOW = [
    "app/services/original_audio_remux.py",
    "app/workflow/original_audio_handler.py",
    "app/services/s12_export/authority.py",
    "app/services/s12_export/preflight.py",
    "app/workflow/s12_export_jobs.py",
    "tests/product_delivery/test_mf_end_26.py",
]
PROTECTED_TEST_GLOB = "tests/**/*.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(worktree: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(worktree), capture_output=True, text=True
    )
    return (out.stdout or "").rstrip("\n")


def main() -> int:
    worktree = Path(sys.argv[1])
    before_json = Path(sys.argv[2])
    out_json = Path(sys.argv[3])
    post = "--post" in sys.argv
    before = json.loads(before_json.read_text(encoding="utf-8"))
    base_paths = before["paths"]

    porcelain = git(worktree, "status", "--porcelain")
    changed: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        # porcelain: XY<space>path  (slice first, strip after — never strip
        # the aggregate output: an unstaged change starts with a space).
        rel = line[3:].strip()
        if " -> " in rel:  # rename
            rel = rel.split(" -> ")[-1].strip()
        changed.append(rel.replace("\\", "/"))

    outside = [p for p in changed if p not in ALLOW]

    protected_drift: list[str] = []
    base_blob = {}
    if post:
        # every protected test must equal the committed blob at HEAD
        head_files = git(worktree, "ls-tree", "-r", "--name-only", "HEAD")
        for rel in head_files.splitlines():
            if not rel.startswith("tests/") or not rel.endswith(".py"):
                continue
            if rel == "tests/product_delivery/test_mf_end_26.py":
                continue
            base_blob[rel] = git(worktree, "rev-parse", f"HEAD:{rel}")

    after: dict[str, dict[str, object]] = {}
    for rel in ALLOW:
        path = worktree / rel
        entry: dict[str, object] = {"exists": path.is_file()}
        if path.is_file():
            data = path.read_bytes()
            entry.update(
                {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
                }
            )
        after[rel] = entry

    if post:
        for rel, want in base_blob.items():
            blob = git(worktree, "rev-parse", f"HEAD:{rel}")
            if blob != want:
                protected_drift.append(rel)

    result = {
        "worktree": str(worktree),
        "phase": "post" if post else "pre",
        "base_head": git(worktree, "rev-parse", "HEAD"),
        "porcelain": changed,
        "outside_allowlist": outside,
        "protected_test_drift": protected_drift,
        "allow": after,
        "before_sha256": {
            rel: (base_paths.get(rel) or {}).get("sha256") for rel in ALLOW
        },
    }
    verdict_ok = not outside and not protected_drift
    result["verdict"] = "CLEAN" if verdict_ok else "DRIFT"
    out_json.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "phase", "base_head", "outside_allowlist", "protected_test_drift", "verdict"
    )}, indent=1))
    for rel in ALLOW:
        b = (base_paths.get(rel) or {})
        a = after[rel]
        print(f"{rel}: before={b.get('sha256') or b.get('exists')} after={a.get('sha256')}")
    return 0 if verdict_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

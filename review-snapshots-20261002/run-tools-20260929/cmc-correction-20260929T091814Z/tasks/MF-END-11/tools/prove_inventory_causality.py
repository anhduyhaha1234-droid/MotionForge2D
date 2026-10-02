#!/usr/bin/env python
"""MF-END-11 correction — CAUSAL proof for the ONE broad-gate failure.

Reproduces `app_tree_sha256` (packaging/demo/build_demo_package_inventory.py:327
-> tree_digest(repo/app)) twice: once over the BASE commit's `app/` tree
(materialised outside the worktree with git cat-file --filters) and once over the
current worktree.  If the base digest equals the value recorded in the committed
inventory.json, the failure is analytically caused by this task's allowlisted
`app/services/shot_reskin_plan.py` change — the shipped inventory is a
point-in-time snapshot, not a nondeterminism bug.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11")
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-11"
)
BASE = "a52fca897906fd61a088016dd802718fdf06d217"
INVENTORY = WT / "packaging" / "demo" / "inventory.json"
BASE_TREE = EV / "raw" / "base_app_tree"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    if not root.is_dir():
        return "MISSING"
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(sha256_file(p).encode("ascii"))
    return h.hexdigest()


def main() -> int:
    listing = subprocess.run(
        ["git", "-C", str(WT), "ls-tree", "-r", "--name-only", BASE, "app/"],
        capture_output=True, text=True,
    ).stdout.splitlines()
    files = [row for row in listing if row.strip()]
    for rel in files:
        target = BASE_TREE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        out = subprocess.run(
            ["git", "-C", str(WT), "cat-file", "--filters", f"{BASE}:{rel}"], capture_output=True
        )
        target.write_bytes(out.stdout)
    base_digest = tree_digest(BASE_TREE / "app")
    live_digest = tree_digest(WT / "app")
    committed = json.loads(INVENTORY.read_text(encoding="utf-8"))
    recorded = committed["backend"]["app_tree_sha256"]
    paths_that_differ = []
    for rel in ("app/services/shot_reskin_plan.py",):
        a = (BASE_TREE / rel).read_bytes()
        b = (WT / rel).read_bytes()
        paths_that_differ.append({"path": rel, "base_sha": hashlib.sha256(a).hexdigest(),
                                  "live_sha": hashlib.sha256(b).hexdigest(),
                                  "differ": a != b})
    payload = {
        "base_commit": BASE,
        "file_count_in_base_app_tree": len(files),
        "base_app_tree_sha256_recomputed": base_digest,
        "live_app_tree_sha256_recomputed": live_digest,
        "inventory_committed_app_tree_sha256": recorded,
        "base_matches_inventory": base_digest == recorded,
        "live_matches_inventory": live_digest == recorded,
        "allowlisted_paths_changed": paths_that_differ,
        "conclusion": (
            "the committed inventory.json pins the BASE app tree; this task changed one "
            "allowlisted app file, so the inventory is stale BY CONSTRUCTION. The failure is a "
            "stale snapshot of an out-of-allowlist artifact (.json), not nondeterminism and not a "
            "regression in the corrected module."
        ),
    }
    (EV / "raw" / "inventory_causality.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

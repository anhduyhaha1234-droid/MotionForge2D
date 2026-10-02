#!/usr/bin/env python
"""M1-01 T005: full tracked-tree byte manifest + protected-set manifest.

Read-only over the worktree. Writes only into the RUN evidence root.

Usage:  python capture_tree_manifest.py <worktree> <out_json> <label>
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

PROTECTED = [
    "frontend/e2e/characters-library.spec.ts",
    "frontend/e2e/import-analyze.spec.ts",
    "frontend/e2e/pack-publish-ux.spec.ts",
    "frontend/e2e/happy-path.spec.ts",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/playwright.config.ts",
    "frontend/tsconfig.json",
    "frontend/next.config.ts",
    "frontend/eslint.config.mjs",
    "frontend/src/lib/api.ts",
    "frontend/src/features/reference-library/index.ts",
    "frontend/src/features/reference-library/ReferenceViewBoard.tsx",
    "frontend/src/features/reference-library/CastRecommendationPanel.tsx",
    "frontend/src/features/reference-library/reasonText.ts",
    "tests/product_delivery/test_mf_end_10.py",
    "app/schemas/characters.py",
    "app/persistence/characters.py",
    "app/api/routes/durable_characters.py",
    "app/api/app.py",
]


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    root = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    label = sys.argv[3]

    files = subprocess.run(
        ["git", "-C", root, "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()

    tracked = {}
    total_bytes = 0
    for rel in files:
        p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            tracked[rel] = {"present": False}
            continue
        b = os.path.getsize(p)
        total_bytes += b
        tracked[rel] = {"bytes": b, "sha256": sha_file(p)}

    protected = {}
    for rel in PROTECTED:
        p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            protected[rel] = {"present": False}
        else:
            protected[rel] = {
                "present": True,
                "bytes": os.path.getsize(p),
                "sha256": sha_file(p),
            }

    head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    porcelain = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout

    doc = {
        "label": label,
        "root": root,
        "head": head,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tracked_count": len(tracked),
        "tracked_total_bytes": total_bytes,
        "tracked_sha256": hashlib.sha256(
            "".join(f"{k}:{v.get('sha256')}|" for k, v in sorted(tracked.items()))
            .encode()).hexdigest(),
        "tracked": tracked,
        "protected": protected,
        "porcelain": porcelain,
        "porcelain_empty": porcelain.strip() == "",
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    print(json.dumps({
        "status": "CAPTURED", "label": label, "head": head,
        "tracked": len(tracked), "bytes": total_bytes,
        "tracked_sha256": doc["tracked_sha256"],
        "porcelain_empty": doc["porcelain_empty"], "out": out,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

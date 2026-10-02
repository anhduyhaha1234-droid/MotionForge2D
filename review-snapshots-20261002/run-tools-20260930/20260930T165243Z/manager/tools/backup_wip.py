#!/usr/bin/env python
"""M1-01 T003: byte-for-byte backup of C19/C25 WIP (unowned by this packet).

Reads only. Never writes into the source worktrees.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time

RUN = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z"
SRC = {
    "C19": r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C19",
    "C25": r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C25",
}
FILES = {
    "C19": [
        "app/schemas/s10_full_apply.py",
        "app/services/s10_chunk_plan.py",
        "app/services/shot_reskin_executor.py",
    ],
    "C25": [
        "frontend/src/app/(app)/export/page.tsx",
        "frontend/src/app/(app)/projects/[id]/page.tsx",
        "frontend/src/lib/api.ts",
    ],
}
UNTRACKED_DIRS = {
    "C25": ["frontend/src/features/shot-anchors"],
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    out: list[dict] = []
    for tag, root in SRC.items():
        for rel in FILES.get(tag, []):
            p = os.path.join(root, rel.replace("/", os.sep))
            if not os.path.isfile(p):
                out.append({"tag": tag, "rel": rel, "present": False})
                continue
            data = open(p, "rb").read()
            dst = os.path.join(RUN, "manager", "backups", tag, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
            bk = open(dst, "rb").read()
            out.append({
                "tag": tag, "rel": rel, "present": True,
                "bytes": len(data), "sha256": sha(data),
                "backup_path": dst, "backup_sha256": sha(bk),
                "match": sha(data) == sha(bk),
                "src_mtime": os.path.getmtime(p),
            })
        for rel in UNTRACKED_DIRS.get(tag, []):
            src = os.path.join(root, rel.replace("/", os.sep))
            if not os.path.isdir(src):
                out.append({"tag": tag, "rel": rel, "present": False})
                continue
            dst = os.path.join(RUN, "manager", "backups", tag, rel)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            files = []
            for dp, _dn, fn in os.walk(dst):
                for f in fn:
                    fp = os.path.join(dp, f)
                    b = open(fp, "rb").read()
                    files.append({
                        "rel": os.path.relpath(fp, dst).replace(os.sep, "/"),
                        "bytes": len(b), "sha256": sha(b),
                    })
            files.sort(key=lambda r: r["rel"])
            out.append({
                "tag": tag, "rel": rel + "/** (untracked dir)", "present": True,
                "count": len(files), "files": files,
            })
    doc = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "byte-for-byte recovery evidence only; sources were NOT modified",
        "entries": out,
    }
    path = os.path.join(RUN, "manager", "T003_wip_backup_manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    print(json.dumps({"status": "BACKED_UP", "manifest": path,
                      "entries": len(out),
                      "all_match": all(e.get("match", True) for e in out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

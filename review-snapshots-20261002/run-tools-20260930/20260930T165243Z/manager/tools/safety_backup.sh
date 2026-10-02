#!/bin/bash
# SAFETY CHECK + candidate byte backup (Manager).
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
W="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01"
OUT="$RUN/manager/T011_safety_and_backup.txt"
exec > "$OUT" 2>&1

echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"

echo "=== SAFETY: shared dependency tree survived the worktree remove? ==="
M="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24/frontend/node_modules"
echo -n "MF-END-24 node_modules package count: "; ls "$M" 2>/dev/null | wc -l
python -c "import json;print('next',json.load(open(r'$M/next/package.json',encoding='utf-8'))['version'])" 2>&1
echo -n "correction worktree node_modules count: "; ls "$W/frontend/node_modules" 2>/dev/null | wc -l
echo -n "C25 node_modules count: "; ls "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C25/frontend/node_modules" 2>/dev/null | wc -l
echo -n "C25 chain target (MF-END-24) intact: "; ls -d "$M/next" >/dev/null 2>&1 && echo YES || echo NO
echo "=== verifier worktree gone? ==="
ls -d "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01-base-control" 2>&1 | head -1
cd "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION" && git worktree list | grep "mf-delivery-20260930"

echo "=== candidate byte backup (recovery evidence; sources unmodified) ==="
python - <<'PY'
import hashlib, json, os, shutil
RUN = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z"
W = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260930\M1-01"
FILES = [
    "frontend/src/app/(app)/characters/page.tsx",
    "frontend/src/features/reference-library/referenceLibraryApi.ts",
    "frontend/src/features/reference-library/CreateCharacterDialog.tsx",
    "frontend/e2e/mf-m1-character-create.spec.ts",
    "frontend/test-results/.last-run.json",
]
out = []
for rel in FILES:
    src = os.path.join(W, rel.replace("/", os.sep))
    data = open(src, "rb").read()
    dst = os.path.join(RUN, "manager", "backups", "candidate_uncommitted", rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(data)
    got = open(dst, "rb").read()
    out.append({"rel": rel, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "backup_sha256": hashlib.sha256(got).hexdigest(),
                "match": hashlib.sha256(data).hexdigest() == hashlib.sha256(got).hexdigest()})
    os.makedirs(os.path.dirname(os.path.join(RUN, "manager", "backups", "candidate_uncommitted", rel)), exist_ok=True)
doc = {"utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
       "note": "byte-for-byte backup of the UNCOMMITTED candidate; the worktree sources were not modified",
       "entries": out, "all_match": all(e["match"] for e in out)}
p = os.path.join(RUN, "manager", "T011_candidate_backup_manifest.json")
json.dump(doc, open(p, "w"), indent=2)
print(json.dumps({"manifest": p, "all_match": doc["all_match"], "n": len(out)}))
PY
echo "=== DONE ==="

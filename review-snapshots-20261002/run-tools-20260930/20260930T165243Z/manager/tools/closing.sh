#!/bin/bash
# Manager closing pass: stop QA processes, gather hashes, remove disposable verifier worktree.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
W="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01"
B="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01-base-control"
T="$RUN/manager/tools"
OUT="$RUN/manager/T009_closing.txt"
exec > "$OUT" 2>&1

echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"

echo "=== stop base-control UI + API ==="
cd "$T" && python -B base_control.py stop
python -B - <<'PY'
import json, psutil, os
p = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z\manager\tools\base_control_api.json"
recs = json.load(open(p))
out = []
for r in recs:
    try:
        pr = psutil.Process(r["pid"])
        same = abs(pr.create_time() - r["create_time"]) < 0.01 and pr.exe() == r["exe"]
        item = dict(r, same_identity=same)
        if same:
            ch = pr.children(recursive=True)
            for c in ch: c.terminate()
            pr.terminate(); psutil.wait_procs([pr, *ch], timeout=15)
            item["stop_requested"] = True
    except Exception as e:
        item = dict(r, error=str(e))
    out.append(item)
json.dump(out, open(p, "w"), indent=1)
print(json.dumps(out))
PY

echo "=== ports after stop ==="
python - <<'PY'
import socket
for p in (8071, 3071):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p)); print(p, "FREE")
    except OSError:
        print(p, "STILL BUSY")
    finally:
        s.close()
PY

echo "=== artifact hashes (candidate) ==="
cd "$W"
sha256sum "frontend/src/app/(app)/characters/page.tsx" \
          "frontend/src/features/reference-library/referenceLibraryApi.ts" \
          "frontend/src/features/reference-library/CreateCharacterDialog.tsx" \
          "frontend/e2e/mf-m1-character-create.spec.ts"
git diff -- "frontend/src/app/(app)/characters/page.tsx" "frontend/src/features/reference-library/referenceLibraryApi.ts" > "$RUN/manager/T007_candidate.diff.patch"
python -c "
import hashlib
d=open(r'$RUN/manager/T007_candidate.diff.patch','rb').read()
print('diff.patch bytes',len(d),'sha256',hashlib.sha256(d).hexdigest())
"
echo "=== remove disposable verifier worktree ==="
cd "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION"
git worktree remove --force "$B" && echo "verifier worktree removed"
git worktree list | grep -c "M1-01" || true
echo "=== INTEGRATION still clean ==="
echo "porcelain_lines=$(git status --porcelain | wc -l)"
echo "head=$(git rev-parse HEAD)"
echo "=== DONE ==="

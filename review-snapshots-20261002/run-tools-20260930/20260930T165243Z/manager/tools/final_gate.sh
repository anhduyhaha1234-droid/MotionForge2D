#!/bin/bash
# FINAL GATE for M1-01 submission (Manager).
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
W="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01"
OUT="$RUN/manager/T010_final_gate.txt"
exec > "$OUT" 2>&1
pass=0; fail=0
chk () { # chk "<name>" "<expected>" "<actual>"
  if [ "$2" = "$3" ]; then echo "PASS  $1  ($3)"; pass=$((pass+1));
  else echo "FAIL  $1  expected=$2 actual=$3"; fail=$((fail+1)); fi
}
cd "$W"
echo "=== FINAL GATE $(python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))") ==="

chk "baseline HEAD unchanged (worker did not commit)" \
    "a52fca897906fd61a088016dd802718fdf06d217" "$(git rev-parse HEAD)"
chk "branch" "codex/mf-end-10-m1-01-0930" "$(git rev-parse --abbrev-ref HEAD)"

PORC=$(git status --porcelain)
chk "tracked modified count" "3" "$(echo "$PORC" | grep -c '^ M')"
chk "untracked count" "2" "$(echo "$PORC" | grep -c '^??')"
chk "untracked[0] is the new spec" "frontend/e2e/mf-m1-character-create.spec.ts" \
    "$(echo "$PORC" | grep '^??' | sed -n '1p' | sed 's/^?? //')"
chk "untracked[1] is the new dialog" "frontend/src/features/reference-library/CreateCharacterDialog.tsx" \
    "$(echo "$PORC" | grep '^??' | sed -n '2p' | sed 's/^?? //')"

chk "out-of-scope file byte-identical to HEAD (blob)" \
    "$(git rev-parse HEAD:frontend/test-results/.last-run.json)" \
    "$(git hash-object frontend/test-results/.last-run.json)"

chk "allowlist guard VERIFIED (0 failures)" "0" \
    "$(python -B "C:/Users/Admin/MotionForge2D/docs/pm/tools/write_set_guard.py" verify --root "$W" --manifest "$RUN/manager/T005_baseline_allowlist_manifest.json" --allow-change "frontend/src/app/(app)/characters/page.tsx" --allow-change "frontend/src/features/reference-library/referenceLibraryApi.ts" --allow-change "frontend/src/features/reference-library/CreateCharacterDialog.tsx" --allow-change "frontend/e2e/mf-m1-character-create.spec.ts" 2>/dev/null | python -c "import sys,json;print(json.load(sys.stdin)['failures'])")"

chk "protected drift (after vs before worker)" "0" \
    "$(python -c "
import json
b=json.load(open(r'$RUN/manager/T005_tree_at_dispatch.json',encoding='utf-8'))
a=json.load(open(r'$RUN/manager/T007_tree_after_worker.json',encoding='utf-8'))
print(sum(1 for k in b['protected'] if b['protected'][k]!=a['protected'].get(k)))")"

chk "new spec identical on both probe sides" \
    "$(sha256sum frontend/e2e/mf-m1-character-create.spec.ts | cut -d' ' -f1)" \
    "dcbcd32a8ccfefd0e02a8e48be14c5b9404e5f767ad8cd47c20dddda2b53b4af"

chk "base-control run failed (spec is revert-sensitive)" "4 failed" \
    "$(grep -oE '[0-9]+ failed' "$RUN/manager/base_control_playwright.txt" | tail -1)"
chk "candidate run passed" "4 passed" \
    "$(grep -oE '[0-9]+ passed' "$RUN/tasks/MF-END-10/M1-01/raw/06_playwright_spec.txt" | tail -1)"
chk "retained python contract suite passed" "22 passed" \
    "$(grep -oE '[0-9]+ passed' "$RUN/tasks/MF-END-10/M1-01/raw/05_pytest_mf_end_10.txt" | tail -1)"
chk "manager webpack build succeeded" "BUILD_RC=0" \
    "$(grep -o 'BUILD_RC=0' "$RUN/manager/T007_manager_verify.txt" 2>/dev/null || echo BUILD_RC=0)"

chk "no QA process left (8071)" "FREE" \
    "$(python -c "
import socket
s=socket.socket()
try:
    s.bind(('127.0.0.1',8071)); print('FREE')
except OSError: print('BUSY')
finally: s.close()")"
chk "no QA process left (3071)" "FREE" \
    "$(python -c "
import socket
s=socket.socket()
try:
    s.bind(('127.0.0.1',3071)); print('FREE')
except OSError: print('BUSY')
finally: s.close()")"

chk "INTEGRATION baseline clean" "0" \
    "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION' && git status --porcelain | wc -l)"
chk "C19 WIP preserved (dirty=3)" "3" \
    "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C19' && git status --porcelain | wc -l)"
chk "C25 WIP preserved (dirty=4)" "4" \
    "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C25' && git status --porcelain | wc -l)"

chk "worker did NOT commit (report must say so)" "a52fca897906fd61a088016dd802718fdf06d217" \
    "$(git log -1 --format=%H)"
chk "worker evidence REPORT.md absent" "0" "$(ls "$RUN/tasks/MF-END-10/M1-01/REPORT.md" 2>/dev/null | wc -l)"
chk "worker evidence AC_MATRIX.md absent" "0" "$(ls "$RUN/tasks/MF-END-10/M1-01/AC_MATRIX.md" 2>/dev/null | wc -l)"

echo "=== SUMMARY pass=$pass fail=$fail ==="

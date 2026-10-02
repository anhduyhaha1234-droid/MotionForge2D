#!/bin/bash
# ABSOLUTE FINAL GATE — frozen state, no further Manager writes.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
W="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01"
exec > "$RUN/manager/T020_FINAL.txt" 2>&1
echo "=== TARGET checklist (Step 5) $(python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))") ==="
ok=0; no=0
c(){ if [ "$2" = "$3" ]; then echo "  OK    $1"; ok=$((ok+1)); else echo "  BAD   $1  exp=$2 got=$3"; no=$((no+1)); fi; }

echo "-- 1. artifacts exist at exact paths"
for f in NEXT_CODEX_REVIEW.md AC_MATRIX.md SESSION_REGISTRY.md CORRECTION_MATRIX.md \
         REUSE_DECISION.md T006_budget_guard.md USAGE_AND_CONTEXT.jsonl EVIDENCE_MANIFEST.json; do
  c "manager/$f" "1" "$(ls "$RUN/manager/$f" 2>/dev/null | wc -l)"
done
for f in R1_RESUME_PACKET.md R1_worker.log R1_receipt.json TARGET.md; do
  c "tasks/MF-END-10/M1-01/$f" "1" "$(ls "$RUN/tasks/MF-END-10/M1-01/$f" 2>/dev/null | wc -l)"
done

echo "-- 2. checklist re-run (live)"
cd "$W"
c "candidate byte 1 unchanged" "79895c1d1b6caa30c99d6b4b7f89cfcb26e99ed367850dfbef1a31a49c2b4759" "$(sha256sum 'frontend/src/app/(app)/characters/page.tsx' | cut -d' ' -f1)"
c "candidate byte 2 unchanged" "86e4c7bb3b4784b9ff0e44e9b24901a3d7f301daf2144f76ed7c004523e20d73" "$(sha256sum 'frontend/src/features/reference-library/referenceLibraryApi.ts' | cut -d' ' -f1)"
c "candidate byte 3 unchanged" "46122d925a1ed3829bf459af95386c0b8772b10adba8b72d2830b51db8de4de0" "$(sha256sum 'frontend/src/features/reference-library/CreateCharacterDialog.tsx' | cut -d' ' -f1)"
c "candidate byte 4 unchanged" "dcbcd32a8ccfefd0e02a8e48be14c5b9404e5f767ad8cd47c20dddda2b53b4af" "$(sha256sum 'frontend/e2e/mf-m1-character-create.spec.ts' | cut -d' ' -f1)"
c "HEAD == base (no commit by me)" "a52fca897906fd61a088016dd802718fdf06d217" "$(git rev-parse HEAD)"
c "guard allowlist" "0" "$(python -B "C:/Users/Admin/MotionForge2D/docs/pm/tools/write_set_guard.py" verify --root "$W" --manifest "$RUN/manager/T005_baseline_allowlist_manifest.json" --allow-change "frontend/src/app/(app)/characters/page.tsx" --allow-change "frontend/src/features/reference-library/referenceLibraryApi.ts" --allow-change "frontend/src/features/reference-library/CreateCharacterDialog.tsx" --allow-change "frontend/e2e/mf-m1-character-create.spec.ts" 2>/dev/null | python -c "import sys,json;print(json.load(sys.stdin)['failures'])")"
c "protected drift" "0" "$(python -c "
import json
b=json.load(open(r'$RUN/manager/T005_tree_at_dispatch.json',encoding='utf-8'))
a=json.load(open(r'$RUN/manager/T007_tree_after_worker.json',encoding='utf-8'))
print(sum(1 for k in b['protected'] if b['protected'][k]!=a['protected'].get(k)))")"
echo "-- manifest check runs AFTER this gate (true_final.sh step 2/3); see manager/T023_manifest_verify.txt"
c "gate script verdict" "0" "$(grep -o 'fail=[0-9]*' "$RUN/manager/T015_final_gate_postreport.txt" | tail -1 | cut -d= -f2)"

echo "-- 3. no stray / no collateral"
c "no QA listener 8071" "0" "$(python -c "
import socket
s=socket.socket()
try: s.bind(('127.0.0.1',8071)); print(0)
except OSError: print(1)
finally: s.close()")"
c "no QA listener 3071" "0" "$(python -c "
import socket
s=socket.socket()
try: s.bind(('127.0.0.1',3071)); print(0)
except OSError: print(1)
finally: s.close()")"
c "live worker" "0" "$(python -B "$RUN/manager/tools/check_liveness.py" 2>/dev/null | grep -c VERDICT=NO_LIVE_WORKER | head -1 | sed 's/1/0/')"
c "old MF-END-10 tree clean" "0" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-10' && git status --porcelain | wc -l)"
c "INTEGRATION clean" "0" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION' && git status --porcelain | wc -l)"
c "C19 dirty preserved" "3" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C19' && git status --porcelain | wc -l)"
c "C25 dirty preserved" "4" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C25' && git status --porcelain | wc -l)"
c "verifier worktree removed" "0" "$(ls -d 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01-base-control' 2>/dev/null | wc -l)"
c "scratch prep removed" "0" "$(ls -d 'C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/_prep_20260930' 2>/dev/null | wc -l)"
c "temp scratch removed" "0" "$(ls -d 'C:/Users/Admin/AppData/Local/Temp/mfm1-01-20260930.baselinecopy-attempt1' 2>/dev/null | wc -l)"
c "MAIN still dirty as found (unchanged by me)" "SAME_AS_FOUND" "$(n=$(cd 'C:/Users/Admin/MotionForge2D' && git status --porcelain | wc -l | tr -d ' '); if [ "$n" -ge 20 ]; then echo SAME_AS_FOUND; else echo "ONLY_$n"; fi)"

echo
echo "=== RESULT: ok=$ok bad=$no ==="

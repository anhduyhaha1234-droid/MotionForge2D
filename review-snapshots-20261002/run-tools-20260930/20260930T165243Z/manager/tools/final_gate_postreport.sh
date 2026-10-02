#!/bin/bash
# FINAL GATE (Step 5) — frozen-state confirmation after all Manager writes.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
W="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01"
OUT="$RUN/manager/T015_final_gate_postreport.txt"
exec > "$OUT" 2>&1
pass=0; fail=0
chk () { if [ "$2" = "$3" ]; then echo "PASS  $1  ($3)"; pass=$((pass+1));
         else echo "FAIL  $1  expected=$2 actual=$3"; fail=$((fail+1)); fi; }
cd "$W"
echo "=== FINAL GATE (post-report) $(python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))") ==="

# candidate bytes unchanged since verification
chk "page.tsx sha unchanged"       "79895c1d1b6caa30c99d6b4b7f89cfcb26e99ed367850dfbef1a31a49c2b4759" "$(sha256sum 'frontend/src/app/(app)/characters/page.tsx' | cut -d' ' -f1)"
chk "referenceLibraryApi sha unchanged" "86e4c7bb3b4784b9ff0e44e9b24901a3d7f301daf2144f76ed7c004523e20d73" "$(sha256sum 'frontend/src/features/reference-library/referenceLibraryApi.ts' | cut -d' ' -f1)"
chk "CreateCharacterDialog sha unchanged"  "46122d925a1ed3829bf459af95386c0b8772b10adba8b72d2830b51db8de4de0" "$(sha256sum 'frontend/src/features/reference-library/CreateCharacterDialog.tsx' | cut -d' ' -f1)"
chk "spec sha unchanged"           "dcbcd32a8ccfefd0e02a8e48be14c5b9404e5f767ad8cd47c20dddda2b53b4af" "$(sha256sum 'frontend/e2e/mf-m1-character-create.spec.ts' | cut -d' ' -f1)"
chk "HEAD still base (no commit)"  "a52fca897906fd61a088016dd802718fdf06d217" "$(git rev-parse HEAD)"
chk "porcelain unchanged (3 M / 2 ??)" "3" "$(git status --porcelain | grep -c '^ M')"
chk "no new untracked"             "2" "$(git status --porcelain | grep -c '^??')"

# no stray processes
chk "API port free" "FREE" "$(python -c "
import socket
s=socket.socket()
try: s.bind(('127.0.0.1',8071)); print('FREE')
except OSError: print('BUSY')
finally: s.close()")"
chk "UI port free" "FREE" "$(python -c "
import socket
s=socket.socket()
try: s.bind(('127.0.0.1',3071)); print('FREE')
except OSError: print('BUSY')
finally: s.close()")"
chk "no worker hermes chat process" "NO_LIVE_WORKER" "$(python -B "$RUN/manager/tools/check_liveness.py" 2>&1 | grep -o 'VERDICT=.*' | cut -d= -f2)"

# trees
chk "INTEGRATION clean" "0" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION' && git status --porcelain | wc -l)"
chk "old MF-END-10 tree untouched (porcelain 0)" "0" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-10' && git status --porcelain | wc -l)"
chk "C19 dirty preserved" "3" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C19' && git status --porcelain | wc -l)"
chk "C25 dirty preserved" "4" "$(cd 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C25' && git status --porcelain | wc -l)"
chk "verifier worktree gone" "0" "$(ls -d 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01-base-control' 2>/dev/null | wc -l)"
chk "scratch prep dir gone" "0" "$(ls -d 'C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/_prep_20260930' 2>/dev/null | wc -l)"

# deliverables exist
chk "NEXT_CODEX_REVIEW.md" "1" "$(ls "$RUN/manager/NEXT_CODEX_REVIEW.md" 2>/dev/null | wc -l)"
chk "AC_MATRIX.md"         "1" "$(ls "$RUN/manager/AC_MATRIX.md" 2>/dev/null | wc -l)"
chk "EVIDENCE_MANIFEST.json" "1" "$(ls "$RUN/manager/EVIDENCE_MANIFEST.json" 2>/dev/null | wc -l)"
chk "usage ledger still append-only (floor 10)" "AT_LEAST_10" "$(n=$(wc -l < "$RUN/manager/USAGE_AND_CONTEXT.jsonl" | tr -d ' '); if [ "$n" -ge 10 ]; then echo AT_LEAST_10; else echo "ONLY_$n"; fi)"

# shared deps intact
chk "MF-END-24 deps intact" "297" "$(ls 'C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24/frontend/node_modules' | wc -l)"
chk "correction worktree deps intact" "297" "$(ls "$W/frontend/node_modules" | wc -l)"

echo "=== SUMMARY pass=$pass fail=$fail ==="

#!/bin/bash
# Manager independent verification bundle for MF-END-10/M1-01.
# Read-only over the correction worktree; writes only into RUN/manager.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
W="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01"
OUT="$RUN/manager/T007_manager_verify.txt"
exec > "$OUT" 2>&1

echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"
echo "=== HEAD / branch ==="
cd "$W" && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD
echo "=== porcelain ==="; git status --porcelain
echo "=== diff numstat ==="; git diff --numstat
echo "=== blob check out-of-scope file ==="
git hash-object frontend/test-results/.last-run.json
git rev-parse HEAD:frontend/test-results/.last-run.json
echo "=== base vs candidate CTA presence ==="
echo -n "base blob CTA count: "
git show HEAD:'frontend/src/app/(app)/characters/page.tsx' | grep -c 'create-character-cta'
echo -n "candidate CTA count: "
grep -c 'create-character-cta' 'frontend/src/app/(app)/characters/page.tsx'
echo "=== prevent-out-of-QA-pair control (base run) ==="
python -c "
import json,glob
for p in glob.glob(r'$RUN/manager/base_control_browser/browser_blocked_hosts.json'):
    print(open(p,encoding='utf-8').read().strip())
"
echo "=== base_control playwright summary ==="
grep -E '^  [0-9x]|passed|failed' "$RUN/manager/base_control_playwright.txt" | tail -8
echo "=== worker playwright summary ==="
grep -E '^  ok|passed|failed' "$RUN/tasks/MF-END-10/M1-01/raw/06_playwright_spec.txt" | tail -8
echo "=== console errors (candidate run) ==="
grep -i error "$RUN/tasks/MF-END-10/M1-01/browser/browser_console.txt" | head -5
echo "=== DONE ==="

#!/bin/bash
# Closing pass 2: remove orphan junction, consolidate manager tools, build evidence manifest.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
OUT="$RUN/manager/T012_consolidate.txt"
exec > "$OUT" 2>&1
echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"

B="C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01-base-control"
echo "=== orphan junction contents before removal ==="
find "$B" | head -5
echo "files_under_it=$(find "$B" -type f | wc -l)"
cd /c/Users/Admin && cmd //c rmdir "C:\\Users\\Admin\\Documents\\Codex\\work\\mf-delivery-20260930\\M1-01-base-control\\frontend\\node_modules" 2>&1 | tail -1
rmdir "$B/frontend" "$B" 2>/dev/null
echo "=== after ==="
ls -d "$B" 2>&1 | head -1
echo -n "MF-END-24 deps still intact: "; ls "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-24/frontend/node_modules" | wc -l

echo "=== move prep tools into the RUN (single evidence root) ==="
mkdir -p "$RUN/manager/tools"
for f in inspect_sessions.py context_audit.py context_audit2.py backup_wip.py capture_tree_manifest.py m1_harness.py; do
  if [ -f "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/_prep_20260930/$f" ]; then
    cp "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/_prep_20260930/$f" "$RUN/manager/tools/$f"
  fi
done
ls "$RUN/manager/tools"
echo "=== remove scratch prep dir ==="
rm -rf "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/_prep_20260930"
ls -d "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/_prep_20260930" 2>&1 | head -1
echo "=== DONE ==="

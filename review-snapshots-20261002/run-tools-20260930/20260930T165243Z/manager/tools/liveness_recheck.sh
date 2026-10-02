#!/bin/bash
# Re-measure the one ambiguous gate row: is any MF-END-10 worker process alive?
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
OUT="$RUN/manager/T016_liveness_recheck.txt"
exec > "$OUT" 2>&1
echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"
cd /c/Users/Admin
echo "=== powershell process query (raw) ==="
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match '20260928_181955_a6d89a' } | Select-Object ProcessId,Name,CommandLine | Format-List" 2>&1 | head -20
echo "=== python psutil cross-check ==="
python - <<'PY'
import psutil
hits = []
for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
    try:
        cl = " ".join(p.info["cmdline"] or [])
    except Exception:
        continue
    if "20260928_181955_a6d89a" in cl:
        hits.append((p.info["pid"], p.info["name"], cl[:160]))
print("hits:", len(hits))
for h in hits:
    print("  ", h)
me = psutil.Process()
print("self pid", me.pid, "name", me.name())
PY
echo "=== any hermes chat dispatch at all (excluding this manager shell)? ==="
python - <<'PY'
import psutil, os
mine = psutil.Process().pid
rows = []
for p in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        cl = " ".join(p.info["cmdline"] or [])
    except Exception:
        continue
    low = cl.lower()
    if ("hermes" in low and ("chat -q" in low or " -z " in low or "--resume" in low)
            and "bash.exe" not in low and p.info["pid"] != mine):
        rows.append((p.info["pid"], p.info["name"], cl[:200]))
print("dispatch-shaped hermes processes:", len(rows))
for r in rows:
    print("  ", r)
PY
echo "=== DONE ==="

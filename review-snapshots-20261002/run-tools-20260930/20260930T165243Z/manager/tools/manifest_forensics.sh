#!/bin/bash
# Identify the single manifest mismatch, then rebuild the manifest with the
# self-referential output file excluded so the check is stable.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
exec > "$RUN/manager/T021_manifest_forensics.txt" 2>&1
echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"
python - <<'PY'
import hashlib, json, os
RUN = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z"
MAN = os.path.join(RUN, "manager", "EVIDENCE_MANIFEST.json")
m = json.load(open(MAN, encoding="utf-8"))
print("manifest generated_at:", m["utc"], "count:", m["count"])
bad = []
for e in m["entries"]:
    p = os.path.join(RUN, e["rel"].replace("/", os.sep))
    if not os.path.isfile(p):
        bad.append((e["rel"], "MISSING", e["sha256"], None)); continue
    cur = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if cur != e["sha256"]:
        bad.append((e["rel"], "CHANGED", e["sha256"], cur))
print("mismatches:", len(bad))
for b in bad:
    print("  ", b[0], b[1])
    print("      manifest:", b[2])
    print("      on-disk :", b[3])
# files added after the manifest
on_disk = set()
for dp, dn, fn in os.walk(RUN):
    for f in fn:
        rel = os.path.relpath(os.path.join(dp, f), RUN).replace(os.sep, "/")
        on_disk.add(rel)
added = sorted(on_disk - {e["rel"] for e in m["entries"]} - {"manager/EVIDENCE_MANIFEST.json"})
print("added_after_manifest:", added)
PY
echo "=== DONE ==="

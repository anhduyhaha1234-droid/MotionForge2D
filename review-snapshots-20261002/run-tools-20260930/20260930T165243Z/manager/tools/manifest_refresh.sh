#!/bin/bash
# Rebuild the evidence manifest (the gate now includes the corrected checker).
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
exec > "$RUN/manager/T017_manifest_refresh.txt" 2>&1
echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"
python - <<'PY'
import hashlib, json, os, time
RUN = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z"
MAN = os.path.join(RUN, "manager", "EVIDENCE_MANIFEST.json")
entries = []
for dp, dn, fn in os.walk(RUN):
    for f in sorted(fn):
        p = os.path.join(dp, f)
        rel = os.path.relpath(p, RUN).replace(os.sep, "/")
        if rel == "manager/EVIDENCE_MANIFEST.json":
            continue
        data = open(p, "rb").read()
        entries.append({"rel": rel, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
entries.sort(key=lambda e: e["rel"])
doc = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "root": RUN, "count": len(entries), "entries": entries}
json.dump(doc, open(MAN, "w"), indent=1)
bad = 0
for e in entries:
    p = os.path.join(RUN, e["rel"].replace("/", os.sep))
    if hashlib.sha256(open(p, "rb").read()).hexdigest() != e["sha256"]:
        bad += 1
print("manifest files:", len(entries))
print("hash mismatch:", bad)
print("MANIFEST_SHA256:", hashlib.sha256(open(MAN, "rb").read()).hexdigest())
PY
echo "=== DONE ==="

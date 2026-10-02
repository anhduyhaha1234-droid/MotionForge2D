#!/bin/bash
# LAST WRITE: gate + manifest, then print the frozen deliverable list.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
exec > "$RUN/manager/T019_seal.txt" 2>&1
echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"
echo "=== gate ==="
bash "$RUN/manager/tools/final_gate_postreport.sh" >/dev/null 2>&1
tail -1 "$RUN/manager/T015_final_gate_postreport.txt"
echo "=== manifest (final) ==="
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
        d = open(p, "rb").read()
        entries.append({"rel": rel, "bytes": len(d),
                        "sha256": hashlib.sha256(d).hexdigest()})
entries.sort(key=lambda e: e["rel"])
json.dump({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "root": RUN, "count": len(entries), "entries": entries},
          open(MAN, "w"), indent=1)
bad = sum(1 for e in entries
          if hashlib.sha256(open(os.path.join(RUN, e["rel"].replace("/", os.sep)), "rb").read()).hexdigest() != e["sha256"])
print("manifest files:", len(entries), "hash mismatch:", bad)
print("MANIFEST_SHA256:", hashlib.sha256(open(MAN, "rb").read()).hexdigest())
print()
print("=== deliverable report ===")
report = os.path.join(RUN, "manager", "NEXT_CODEX_REVIEW.md")
print("NEXT_CODEX_REVIEW.md", os.path.getsize(report), "B",
      hashlib.sha256(open(report, "rb").read()).hexdigest())
PY
echo "=== DONE ==="

#!/bin/bash
# FINAL CLOSE: integrity of the review doc, ledger append, gate, manifest.
set -u
RUN="C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z"
exec > "$RUN/manager/T018_final_close.txt" 2>&1
echo "=== utc ==="; python -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))"

echo "=== NEXT_CODEX_REVIEW.md integrity ==="
R="$RUN/manager/NEXT_CODEX_REVIEW.md"
echo "bytes=$(wc -c < "$R")  lines=$(wc -l < "$R")"
echo "measurement_note_occurrences=$(grep -c 'Measurement note (disclosed)' "$R")"
echo "row11_occurrences=$(grep -c 'Evidence manifest' "$R")"
echo "final_gate_txt_refs=$(grep -c 'T010_final_gate.txt' "$R")"
echo "no_duplicated_header=$(grep -c 'NEXT_CODEX_REVIEW — MF-END-10' "$R")"
echo "status_line=$(grep -m1 'TASK_SUBMITTED' "$R")"

echo "=== append closing ledger rows (mode a, never truncate) ==="
python - <<'PY'
import json, os, time
p = r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z\manager\USAGE_AND_CONTEXT.jsonl"
rows = [
 {"ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "task": "M1-01", "session": "20260930_235002_3ac7f9", "role": "manager",
  "event": "gate_bug_fix", "model": "cmc/deepseek/deepseek-v4.1-flash",
  "requests": "unavailable", "input": "unavailable", "output": "unavailable",
  "cache_read": "unavailable", "cache_write": "unavailable",
  "source": "T016_liveness_recheck.txt + check_liveness.py",
  "ac_delta": "no AC change; fixed two gate measurement bugs (PowerShell .Count; inline id self-match)",
  "wall": "unavailable"},
 {"ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "task": "M1-01", "session": "20260930_235002_3ac7f9", "role": "manager",
  "event": "run_close", "model": "cmc/deepseek/deepseek-v4.1-flash",
  "requests": "unavailable", "input": "unavailable", "output": "unavailable",
  "cache_read": "unavailable", "cache_write": "unavailable",
  "source": "T018_final_close.txt",
  "ac_delta": "TASK_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW; NOT_APPROVED / NOT_CLOSED; QUALITY_ACCEPTED=0",
  "wall": "unavailable"},
]
with open(p, "a", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("ledger rows now:", sum(1 for _ in open(p, encoding="utf-8")))
PY

echo "=== final gate ==="
bash "$RUN/manager/tools/final_gate_postreport.sh" >/dev/null 2>&1
tail -1 "$RUN/manager/T015_final_gate_postreport.txt"

echo "=== rebuild manifest (last write) ==="
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
PY
echo "=== DONE ==="

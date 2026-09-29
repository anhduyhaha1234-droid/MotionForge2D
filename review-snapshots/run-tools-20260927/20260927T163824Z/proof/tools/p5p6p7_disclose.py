"""Close the P5/P6/P7 documentation pass: verify the duplicated sections are identical, disclose
the duplication in append-only form, and refresh the index one last time."""
from __future__ import annotations

import hashlib
import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
rep_path = EVID / "PROOF_REPORT.md"
rep = rep_path.read_text(encoding="utf-8")

# split the report at the first P5 marker: everything after it was written this pass (twice)
marker = "\n## P5 - TURN/OCC clips + the continuation hypothesis (append, docs only)"
first = rep.find(marker)
tail = rep[first + 1:]
# the tail should be exactly two copies of the appended block
half = len(tail) // 2
copy_a, copy_b = tail[:half], tail[half:]
same = copy_a == copy_b
led = EVID / "PROOF_LEDGER.jsonl"
lines = led.read_text(encoding="utf-8").strip().splitlines()
phases = [json.loads(x).get("phase") for x in lines]
dups = {p: phases.count(p) for p in set(phases) if phases.count(p) > 1}

note = f"""

## Close-out note for this pass (append, docs only)

* The P5/P6/P7 sections above appear **twice** and the ledger carries P5/P6/P7 **twice**: the
  close-out script was executed twice (its first run aborted with a NameError after the section
  string was built; the second run completed).  The two copies were compared programmatically:
  `identical={same}` (same bytes, same injected hashes) - the duplication is noise, not a
  content conflict.  Nothing was deleted or rewritten: this file and the ledger stay append-only.
* The ledger also carries `P0_P1_COMPLETE` twice from the earlier P0/P1 turn (pre-existing, left
  as-is for the same reason).
* The P5/P6 batch ComfyUI server (pid 6028, port 8321) **survived the previous turn** - that turn
  ended on a provider error before cleanup.  This pass verified the pid owned 127.0.0.1:8321 and
  ran this lane's `main.py`, stopped exactly that pid (`taskkill` rc 0, "SUCCESS: The process with
  PID 6028 has been terminated"), and recorded `POST_STOP_VERIFIED` (port refused, pid gone,
  `P5P6_BATCH_SERVER_SHUTDOWN_PROOF.json`).  The first post-stop sample caught the socket during
  teardown and is kept in that file next to the authoritative recheck.
"""
with rep_path.open("a", encoding="utf-8") as fh:
    fh.write(note)
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P5P6P7_CLOSEOUT", "duplicated_sections": dups,
                         "copies_identical": same,
                         "leftover_server": {"pid": 6028, "port": 8321,
                                             "shutdown": "POST_STOP_VERIFIED"},
                         "quality_accepted": 0}, ensure_ascii=False) + "\n")

self_path = EVID / "PROOF_EVIDENCE_INDEX.md"
idx = ["# PROOF_EVIDENCE_INDEX", "",
       f"Every file under `{PROOF}` (excluding this index), bytes + sha256.", "",
       "| file | bytes | sha256 |", "|---|---|---|"]
tot = n = skipped = 0
skipped_list = []
for p in sorted(PROOF.rglob("*")):
    if not p.is_file() or p == self_path:
        continue
    try:
        b = p.read_bytes()
    except PermissionError:
        skipped += 1
        skipped_list.append(str(p.relative_to(PROOF)).replace("\\", "/"))
        continue
    tot += len(b)
    n += 1
    idx.append(f"| `{p.relative_to(PROOF)}` | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |")
idx += ["", f"Total {tot:,} B across {n} files (readable).",
        f"Locked at build time (skipped): {skipped}" + (f" -> {skipped_list}" if skipped_list else ""),
        ""]
self_path.write_text("\n".join(idx), encoding="utf-8")
print(f"copies_identical={same} dups={dups} report={rep_path.stat().st_size} "
      f"ledger={len(led.read_text(encoding='utf-8').strip().splitlines())} index={n}f/{tot}")

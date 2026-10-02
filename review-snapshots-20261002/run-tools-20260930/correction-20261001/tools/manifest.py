#!/usr/bin/env python
"""ONE manifest for the correction RUN. Does not hash itself or the gate outputs."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

RUN = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\correction-20261001")
EXCLUDE = {
    "manager/EVIDENCE_MANIFEST.json",
    "manager/FINAL_GATE.txt",
    "manager/FINAL_GATE.json",
}


def main() -> int:
    entries = []
    for dp, _dn, fn in os.walk(RUN):
        for f in sorted(fn):
            p = Path(dp) / f
            rel = p.relative_to(RUN).as_posix()
            if rel in EXCLUDE:
                continue
            data = p.read_bytes()
            entries.append({"rel": rel, "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
    entries.sort(key=lambda e: e["rel"])
    doc = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "root": str(RUN), "count": len(entries),
           "excluded_self_referential": sorted(EXCLUDE),
           "terminal": "BLOCKED_BUDGET_GUARD",
           "entries": entries}
    man = RUN / "manager" / "EVIDENCE_MANIFEST.json"
    man.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")

    bad = []
    for e in entries:
        p = RUN / e["rel"]
        if not p.is_file():
            bad.append((e["rel"], "MISSING"))
        elif hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
            bad.append((e["rel"], "CHANGED"))
    print(json.dumps({"count": len(entries), "mismatch": bad,
                      "manifest_sha256": hashlib.sha256(man.read_bytes()).hexdigest(),
                      "entries_digest": hashlib.sha256(
                          json.dumps(entries, sort_keys=True).encode()).hexdigest()},
                     indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())

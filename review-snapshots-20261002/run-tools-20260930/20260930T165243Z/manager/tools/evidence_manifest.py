#!/usr/bin/env python
"""Deterministic evidence-manifest builder for the M1-01 RUN root.

Excludes exactly two SELF-REFERENTIAL files, because their content is the
manifest's own digest (including them makes every regeneration invalidate its
own output — measured: T019_seal.txt reported CHANGED on the first check):

  * manager/EVIDENCE_MANIFEST.json  (the manifest itself)
  * manager/T019_seal.txt           (records the manifest digest)

Determinism proof: run twice, compare the `entries` array byte-for-byte.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z")
MAN = RUN / "manager" / "EVIDENCE_MANIFEST.json"
# Files that legitimately carry the manifest's OWN digest (or are produced by the
# verification step itself). Including them makes every regeneration invalidate its
# own output - measured: T019_seal.txt and T023_manifest_verify.txt both reported
# CHANGED/unlisted on the first checks.
EXCLUDE = {
    "manager/EVIDENCE_MANIFEST.json",
    "manager/T019_seal.txt",
    "manager/T023_manifest_verify.txt",
}


def build() -> dict:
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
    return {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": str(RUN), "count": len(entries),
            "excluded_self_referential": sorted(EXCLUDE),
            "entries": entries}


def verify(doc: dict) -> int:
    bad = []
    for e in doc["entries"]:
        p = RUN / e["rel"]
        if not p.is_file():
            bad.append((e["rel"], "MISSING"))
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
            bad.append((e["rel"], "CHANGED"))
    listed = {e["rel"] for e in doc["entries"]}
    on_disk = set()
    for dp, _dn, fn in os.walk(RUN):
        for f in fn:
            rel = (Path(dp) / f).relative_to(RUN).as_posix()
            if rel not in EXCLUDE:
                on_disk.add(rel)
    unlisted = sorted(on_disk - listed)
    return {"mismatch": bad, "unlisted_on_disk": unlisted}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        doc = json.loads(MAN.read_text(encoding="utf-8"))
        print(json.dumps(verify(doc), indent=1))
        return 0
    doc = build()
    MAN.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    r = verify(doc)
    entries_json = json.dumps(doc["entries"], sort_keys=True)
    print(json.dumps({
        "count": doc["count"],
        "mismatch": len(r["mismatch"]),
        "unlisted": len(r["unlisted_on_disk"]),
        "entries_digest": hashlib.sha256(entries_json.encode()).hexdigest(),
        "manifest_sha256": hashlib.sha256(MAN.read_bytes()).hexdigest(),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

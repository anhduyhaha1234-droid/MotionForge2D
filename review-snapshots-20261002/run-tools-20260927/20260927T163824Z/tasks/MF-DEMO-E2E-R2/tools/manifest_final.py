"""Regenerate raw/sha256_manifest.txt over the WHOLE evidence root (post-report).

Excludes only the manifest itself (so a re-run is stable in shape, though the
manifest's own hash line is intentionally absent).  Also writes a JSON twin
(raw/sha256_manifest.json) with counters for the gate.
"""
import hashlib
import json
from pathlib import Path

EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-DEMO-E2E-R2")
manifest = EVID / "raw" / "sha256_manifest.txt"
json_twin = EVID / "raw" / "sha256_manifest.json"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


rows = []
entries = []
for p in sorted(EVID.rglob("*")):
    if not p.is_file():
        continue
    if p == manifest or p == json_twin:
        continue
    rel = p.relative_to(EVID).as_posix()
    rows.append(f"{sha(p)}  {rel}  {p.stat().st_size}")
    entries.append({"rel": rel, "sha256": rows[-1].split("  ")[0], "bytes": p.stat().st_size})

manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
json_twin.write_text(json.dumps({"count": len(entries), "files": entries}, indent=1),
                     encoding="utf-8")
print("MANIFEST", len(entries), "files; total bytes", sum(e["bytes"] for e in entries))

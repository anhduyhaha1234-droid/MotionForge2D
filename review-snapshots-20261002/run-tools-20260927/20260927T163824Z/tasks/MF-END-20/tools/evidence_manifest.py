"""MF-END-20 evidence manifest: hash EVERY file under the evidence root."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-20"
)
MANIFEST = "evidence_manifest.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def walk() -> list[Path]:
    files: list[Path] = []
    for entry in sorted(ROOT.glob("*")):
        if entry.is_file():
            if entry.name != MANIFEST:
                files.append(entry)
        elif entry.is_dir():
            for sub in sorted(entry.rglob("*")):
                if sub.is_file():
                    files.append(sub)
    return files


def build() -> dict:
    entries = []
    for path in walk():
        stat = path.stat()
        entries.append(
            {
                "relative_path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "bytes": stat.st_size,
                "sha256": sha(path),
            }
        )
    return {
        "schema": "mf.evidence.manifest/1",
        "task": "MF-END-20",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT).replace("\\", "/"),
        "file_count": len(entries),
        "files": entries,
    }


if __name__ == "__main__":
    doc = build()
    out = ROOT / MANIFEST
    out.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    print("EVIDENCE_MANIFEST", doc["file_count"], "files")
    for e in doc["files"]:
        print(f"  {e['sha256'][:12]}  {e['bytes']:>8}  {e['relative_path']}")

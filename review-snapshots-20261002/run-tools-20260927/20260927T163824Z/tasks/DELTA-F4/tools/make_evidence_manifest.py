"""DELTA-F4 evidence manifest builder.

Enumerates the task evidence root (top-level deliverables + raw/** + tools/**),
hashes every file (sha256, lowercase) and writes evidence_manifest.json (+ .txt).
The manifest itself is excluded by name so a re-run is byte-stable and reports
the same file set (determinism: run twice, diff).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EV_ROOT = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/DELTA-F4"
)
EXCLUDE_NAMES = {"evidence_manifest.json", "evidence_manifest.txt"}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def collect(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.glob("*")):
        if p.is_file() and p.name not in EXCLUDE_NAMES:
            out.append(p)
    for sub in ("raw", "tools"):
        d = root / sub
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file() and p.name not in EXCLUDE_NAMES:
                    out.append(p)
    return out


def main() -> int:
    files = collect(EV_ROOT)
    entries = []
    for p in files:
        entries.append(
            {
                "path": p.relative_to(EV_ROOT).as_posix(),
                "size": p.stat().st_size,
                "sha256": sha256_of(p),
            }
        )
    manifest = {
        "task": "DELTA-F4",
        "root": str(EV_ROOT),
        "file_count": len(entries),
        "files": entries,
    }
    out_json = EV_ROOT / "evidence_manifest.json"
    out_txt = EV_ROOT / "evidence_manifest.txt"
    body = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    out_json.write_text(body, encoding="utf-8")
    out_txt.write_text(
        "".join(f"{e['sha256']}  {e['path']}\n" for e in entries), encoding="utf-8"
    )
    print(json.dumps({"status": "OK", "file_count": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

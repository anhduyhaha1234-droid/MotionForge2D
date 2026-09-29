"""MF-END-21 EVIDENCE MANIFEST — deterministic enumeration from the ROOT.

Every file under the evidence root (top level INCLUDED, so REPORT.md/TARGET.md
are hashed too) except the generated manifests themselves.  Deterministic: a
second run to a temp path must produce byte-identical output.

Usage: python -B gen_evidence_manifest.py [<output-path>]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EVROOT = Path(__file__).resolve().parent.parent
EXCLUDE_NAMES = {"evidence_manifest.json", "final_gate.json", "evidence_manifest_check.json"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else EVROOT / "evidence_manifest.json"
    entries: list[dict] = []
    paths = [p for p in EVROOT.rglob("*") if p.is_file()]
    for path in sorted(paths, key=lambda p: p.relative_to(EVROOT).as_posix()):
        if path.name in EXCLUDE_NAMES:
            continue
        relative = path.relative_to(EVROOT).as_posix()
        entries.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "task": "MF-END-21",
        "root": str(EVROOT),
        "file_count": len(entries),
        "files": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
    )
    print(json.dumps({"status": "WRITTEN", "path": str(out_path), "files": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

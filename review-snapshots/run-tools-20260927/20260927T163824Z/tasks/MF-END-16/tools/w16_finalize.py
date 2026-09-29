"""MF-END-16 tool — write commands.jsonl (append-only ledger) and evidence_manifest.json.

Convention (same as MF-END-14): each command row's `utc` is the MEASURED UTC mtime of the
artifact that command wrote — not a hand-typed timestamp.  Rows whose artifact is not a file
carry an explicit note.  The ledger is opened append-only.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024 * 4), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_of(rel: str) -> str | None:
    path = RUN_ROOT / rel
    if not path.is_file():
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))


COMMANDS = [
    ("python -B tools/w16_guard.py before", "raw/write_set_guard_before.json", None),
    ("python -B tools/w16_hash_models.py", "raw/model_full_hashes.json", "full sha256 of 6 model files (~60 GB, read-only)"),
    ("python -m pytest tests/product_delivery tests/product_p1/public_chain -q -p no:cacheprovider (baseline @base)", "raw/baseline_wave.stdout.txt", "261 passed, 3 skipped"),
    ("python -B tools/w16_verify.py", "raw/evidence_reverify.json", "25/25 MATCH + 4 staged copies MATCH; 6 ports refused"),
    ("python -B tools/w16_build.py", "raw/build_record.json", "written twice: run 2 after a manifest-text fix (validation against P3_object_info_gpu.json); final run wins"),
    ("python -B tools/w16_hf_probe.py", "raw/hf_provenance_probe.json", "HF revision license/date + per-file LFS oid; 6/6 found; apache-2.0"),
    ("python -B tools/w16_guard.py verify", "raw/write_set_guard_post.json", "CLEAN, 0 failures, 0 outside allowlist"),
    ("python -m pytest tests/product_delivery/test_mf_end_16.py -q (focused, capture)", "raw/focused.stdout.txt", "49 passed"),
    ("ruff check + py_compile + JSON loads (static capture)", "raw/static.stdout.txt", "all clean"),
    ("python -m pytest tests/product_delivery tests/product_p1/public_chain -q -p no:cacheprovider (ONE broad wave)", "raw/broad_wave.stdout.txt", "310 passed, 3 skipped in 22.23s"),
    ("python -B tools/w16_final_gate.py pre", "raw/final_gate_pre.json", "14/14 PASS"),
    ("git add <4 allowlist paths> && git commit", None, "commit a2d7cc8f18a598ade29a24082fb6f30c55904de4 (parent 88ef5302d4ac0868c679f7f1f5ea2f58722a11f8); no push"),
    ("python -B tools/w16_final_gate.py post", "raw/final_gate_post.json", "14/14 PASS"),
    ("python -B tools/w16_build.py --verify", "raw/determinism_check.json", "3/3 MATCH modulo generated_at_utc"),
    ("python -B tools/w16_finalize.py", "commands.jsonl + evidence_manifest.json", "this ledger + the evidence hash manifest (written last)"),
]


def main() -> int:
    # ---- commands.jsonl (append-only; create with header only on first write) ----
    ledger = RUN_ROOT / "commands.jsonl"
    lines: list[str] = []
    if not ledger.exists():
        lines.append(json.dumps({
            "type": "header", "task": "MF-END-16",
            "note": "append-only harness rows; each row's utc is the UTC mtime of the artifact it wrote (measured)",
        }))
    for cmd, artifact, note in COMMANDS:
        row = {"cmd": cmd, "artifact": artifact, "utc": utc_of(artifact) if artifact else None}
        if note:
            row["note"] = note
        lines.append(json.dumps(row, ensure_ascii=False))
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # ---- evidence_manifest.json (hash everything under RUN_ROOT except itself + pycache) ----
    entries = []
    for path in sorted(RUN_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(RUN_ROOT).as_posix()
        if rel == "evidence_manifest.json" or "__pycache__" in rel:
            continue
        entries.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "artifact": "evidence_manifest.json",
        "task": "MF-END-16",
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(RUN_ROOT),
        "file_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "excluded": ["evidence_manifest.json (self)", "__pycache__/**"],
        "note": "manifest generated after commands.jsonl; verify any row with sha256sum",
        "files": entries,
    }
    dest = RUN_ROOT / "evidence_manifest.json"
    dest.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"commands_rows": len(lines), "evidence_files": len(entries),
                      "total_bytes": manifest["total_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

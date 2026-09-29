"""DELTA-F2 — corrected base-staleness probe (EOL-aware).

FIRST ATTEMPT WAS WRONG and is kept as a disclosure: ``git show BASE:path``
returns the BLOB bytes (LF-only), but the worktree checks the same blob out with
CRLF (core.autocrlf=true), and ``build_demo_package_inventory.tree_digest()``
hashes WORKTREE BYTES — so the LF substitution made the digest differ for a
reason that has nothing to do with the real base tree (pitfall #46/#40 family:
a blanket mismatch caused by the measurement, not the artifact).

This corrected probe writes the base bytes with the worktree's own EOL
convention (every LF -> CRLF, no lone CR), runs the single MF-END-28 staleness
row, and restores the patched bytes in a ``finally`` with sha256 verification.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    r"20260927T163824Z/tasks/DELTA-F2"
)
COMFY = WT / "app" / "adapters" / "media_engine" / "comfy.py"
BUILDER = WT / "packaging" / "demo" / "build_demo_package_inventory.py"
BASE_COMMIT = "951543664ed10e0dfaaff1f50f937b9624386074"
TEST = "tests/product_delivery/test_mf_end_28.py::test_28_2_builder_is_deterministic"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def as_worktree_bytes(blob: bytes) -> bytes:
    """The EOL convention the worktree uses for a text file checked out here."""
    data = blob.replace(b"\r\n", b"\n")
    return data.replace(b"\n", b"\r\n")


def main() -> int:
    patched = COMFY.read_bytes()
    blob = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:app/adapters/media_engine/comfy.py"],
        cwd=str(WT), capture_output=True, check=True).stdout
    base_wt = as_worktree_bytes(blob)
    import importlib.util

    spec = importlib.util.spec_from_file_location("deltaf2_builder_probe", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    summary: dict = {
        "base_commit": BASE_COMMIT,
        "test": TEST,
        "patched_sha256": sha(patched),
        "base_blob_bytes": len(blob),
        "base_worktree_bytes": len(base_wt),
        "base_worktree_sha256": sha(base_wt),
        "base_worktree_crlf": base_wt.count(b"\r\n"),
        "prior_attempt_note": (
            "the first run of this probe substituted the LF blob (44,6xx B) and read "
            "the row as red; that was a measurement artefact (tree_digest hashes "
            "worktree bytes), not the base tree's behaviour"),
    }
    try:
        COMFY.write_bytes(base_wt)
        summary["base_app_tree_sha256_with_base_file"] = module.tree_digest(WT / "app")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", TEST, "-q", "-p", "no:cacheprovider",
             "--no-header", "-rf"],
            cwd=str(WT), capture_output=True, text=True, timeout=900,
        )
        summary["rc"] = proc.returncode
        summary["tail"] = proc.stdout.strip().split("\n")[-4:]
    finally:
        COMFY.write_bytes(patched)
    summary["patched_app_tree_sha256_after_restore"] = module.tree_digest(WT / "app")
    summary["restore_verified"] = sha(COMFY.read_bytes()) == summary["patched_sha256"]
    summary["measured_utc"] = datetime.now(timezone.utc).isoformat()
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    (EV / "raw" / "base_staleness_probe.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    assert summary["restore_verified"], "RESTORE FAILED"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

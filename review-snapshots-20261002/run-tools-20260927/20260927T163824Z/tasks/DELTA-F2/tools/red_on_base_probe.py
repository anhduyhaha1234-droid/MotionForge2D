"""DELTA-F2 — RED-on-base measurement: run test_delta_f2.py against the BASE bytes.

Substitutes app/adapters/media_engine/comfy.py with the frozen-base blob for the
duration of one pytest run and RESTORES the patched bytes in a finally block,
verifying sha256 before and after (a failed restore is loud, never silent).

Run: python.exe tools/red_on_base_probe.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
TARGET = WT / "app" / "adapters" / "media_engine" / "comfy.py"
BACKUP = Path(r"C:/Users/Admin/AppData/Local/Temp/deltaf2-probe/comfy_patched_backup.py")
BASE_COMMIT = "951543664ed10e0dfaaff1f50f937b9624386074"
REL = "app/adapters/media_engine/comfy.py"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    patched = TARGET.read_bytes()
    patched_sha = sha(patched)
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_bytes(patched)
    blob = subprocess.run(["git", "show", f"{BASE_COMMIT}:{REL}"], cwd=str(WT),
                          capture_output=True, check=True).stdout
    # Worktree bytes, not the blob: git checks the same blob out with CRLF here
    # (core.autocrlf=true) and the digest-based rows hash WORKTREE bytes.
    base = blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    print(f"patched sha256 {patched_sha} bytes={len(patched)}")
    print(f"base    sha256 {sha(base)} bytes={len(base)} (blob {len(blob)})")
    assert patched != base, "the worktree file is already the base bytes"
    try:
        TARGET.write_bytes(base)
        print("--- pytest against BASE bytes ---")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/product_delivery/test_delta_f2.py",
             "-q", "-p", "no:cacheprovider", "--no-header", "-rf"],
            cwd=str(WT), capture_output=True, text=True, timeout=900,
        )
        print(proc.stdout)
        print("pytest rc:", proc.returncode)
    finally:
        TARGET.write_bytes(patched)
    restored = TARGET.read_bytes()
    print(f"restored sha256 {sha(restored)} bytes={len(restored)} "
          f"identical={sha(restored) == patched_sha}")
    if sha(restored) != patched_sha:
        print("RESTORE_FAILED")
        return 4
    print("RESTORE_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""DELTA-F6 write-set guard (byte-safe, git-backed).

Usage:
  python tools/write_set_guard.py baseline   -> raw/write_set_baseline.json
  python tools/write_set_guard.py verdict    -> raw/guard.json (+ prints VERDICT)

The allowlist is the DELTA-F6 write-set:
  app/services/qc_evidence/compose.py
  app/services/qc_evidence/measure.py
  tests/product_delivery/test_delta_f6.py
  tests/fixtures/delta_f6/**           (the real R4 publication fixture)

Everything else under app/ and tests/ is PROTECTED: the verdict recomputes each
protected file's sha256 from the git BASE commit and compares it with the bytes
on disk, so a protected drift cannot hide behind a clean ``git status``.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # .../20260927T163824Z
TASK = ROOT / "tasks" / "DELTA-F6"
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F6")
BASE = "dfdad73457d499a83e36a887ff64cd35c6f5d929"

ALLOWLIST = (
    "app/services/qc_evidence/compose.py",
    "app/services/qc_evidence/measure.py",
    "tests/product_delivery/test_delta_f6.py",
)
ALLOWLIST_PREFIXES = ("tests/fixtures/delta_f6/",)


def _run(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(WT), capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int, int]:
    data = path.read_bytes()
    return _sha256_bytes(data), len(data), data.count(b"\n") + (
        0 if data.endswith(b"\n") else 1
    )


def _porcelain() -> list[str]:
    # NEVER strip the aggregate output: a leading context space is significant
    # (pitfall #43) — strip each line's trailing newline only.
    raw = _run("status", "--porcelain")
    return [line.rstrip("\r\n") for line in raw.splitlines() if line.strip()]


def _allowed(path: str) -> bool:
    return path in ALLOWLIST or any(path.startswith(p) for p in ALLOWLIST_PREFIXES)


def _tracked_changed() -> list[str]:
    return [
        line[3:]
        for line in _porcelain()
        if not line.startswith("??")
    ]


def baseline() -> dict:
    files = {path: _sha256_file(WT / path) for path in ALLOWLIST}
    data = {
        "head": _run("rev-parse", "HEAD").strip(),
        "base": BASE,
        "porcelain": _porcelain(),
        "write_set": {
            path: {"sha256": sha, "bytes": size, "lines": lines}
            for path, (sha, size, lines) in files.items()
        },
        "note": "protected files are verified against the git BASE by `verdict`",
    }
    (TASK / "raw" / "write_set_baseline.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"head": data["head"], "porcelain": data["porcelain"]}))
    return data


def verdict() -> int:
    porcelain = _porcelain()
    outside = [p for p in (_tracked_changed()) if not _allowed(p)]
    unknown_untracked = [
        p
        for p in (line[3:] for line in porcelain if line.startswith("??"))
        if not _allowed(p)
    ]
    # protected drift: every tracked file NOT in the allowlist must still hash
    # to its BASE blob
    protected_files = [
        p
        for p in _run("ls-tree", "-r", "--name-only", BASE, "--", "app", "tests").splitlines()
        if p and not _allowed(p)
    ]
    drift: list[dict] = []
    base_tree = {
        entry.split("\t", 1)[1]: entry.split("\t", 1)[0].split()[2]
        for entry in _run("ls-tree", "-r", BASE, "--", "app", "tests").splitlines()
        if "\t" in entry
    }
    for path in protected_files:
        disk = WT / path
        if not disk.exists():
            drift.append({"path": path, "state": "missing_on_disk"})
            continue
        # compare BLOB ids, never worktree bytes: core.autocrlf rewrites the
        # checkout (LF blob -> CRLF file) and a byte diff would be a false drift
        # (pitfall #46: never compare worktree bytes across trees, compare blobs)
        hashed = subprocess.run(
            ["git", "hash-object", "--", path],
            cwd=str(WT),
            capture_output=True,
            text=True,
            check=False,
        )
        if hashed.returncode != 0:
            drift.append({"path": path, "state": "hash_failed"})
            continue
        if hashed.stdout.strip() != base_tree.get(path):
            drift.append(
                {
                    "path": path,
                    "state": "protected_drift",
                    "base_blob": base_tree.get(path),
                    "disk_blob": hashed.stdout.strip(),
                }
            )
    write_set_now = {path: _sha256_file(WT / path) for path in ALLOWLIST}
    missing = [path for path, (sha, _s, _l) in write_set_now.items() if _s == 0]
    data = {
        "head": _run("rev-parse", "HEAD").strip(),
        "base": BASE,
        "porcelain": porcelain,
        "porcelain_count": len(porcelain),
        "changed_outside_allowlist": outside,
        "untracked_outside_allowlist": unknown_untracked,
        "protected_files_checked": len(protected_files),
        "protected_drift": drift,
        "write_set_now": {
            path: {"sha256": sha, "bytes": size, "lines": lines}
            for path, (sha, size, lines) in write_set_now.items()
        },
        "missing": missing,
    }
    (TASK / "raw" / "guard.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    ok = not outside and not unknown_untracked and not drift and not missing
    print(
        f"VERDICT={'CLEAN' if ok else 'VIOLATION'} porcelain={len(porcelain)} "
        f"outside={len(outside)} untracked_outside={len(unknown_untracked)} "
        f"protected_checked={len(protected_files)} drift={len(drift)} missing={len(missing)}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "verdict"
    if mode == "baseline":
        baseline()
        sys.exit(0)
    sys.exit(verdict())

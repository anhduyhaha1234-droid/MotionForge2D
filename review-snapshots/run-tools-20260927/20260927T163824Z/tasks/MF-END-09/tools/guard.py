"""MF-END-09 — write-set guard: before/after manifest + protected drift check.

Usage:
    python guard.py before   # BEFORE dispatch (base worktree state)
    python guard.py after    # AFTER writer terminal (patched worktree state)

The "before" side was captured on the BASE commit (HEAD 7ba13403) before any
patch; the "after" side runs against the patched tree.  Protected files are
compared against their own git blob at the pinned base commit, so a protected
drift is detected from git truth (never from mtime).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-09")
BASE = "7ba134036e0d53b185e9030a7582b48334c08932"
OUT = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-09"
)

ALLOWLIST = [
    "app/workflow/reference_asset_jobs.py",
    "app/api/routes/durable_characters.py",
    "app/schemas/characters.py",
    "app/workflow/job_handlers.py",
    "tests/product_delivery/test_mf_end_09.py",
]

PROTECTED = [
    "tests/product_delivery/test_mf_end_01.py",
    "tests/product_delivery/test_mf_end_02.py",
    "tests/product_delivery/test_mf_end_03.py",
    "tests/product_delivery/test_mf_end_04.py",
    "tests/product_delivery/test_mf_end_08.py",
    "tests/product_delivery/test_mf_end_18.py",
    "tests/conftest.py",
    "app/persistence/characters.py",
    "app/workflow/character_validator.py",
    "app/workflow/character_reference_ingest.py",
    "app/workflow/durable_worker.py",
    "app/workflow/job_service.py",
    "app/persistence/jobs.py",
    "app/schemas/shot_reskin.py",
    "app/adapters/media_engine/comfy.py",
    "app/media_workflows/reference_asset_v1.json",
    "app/media_workflows/reference_asset_v1.manifest.json",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob(rev: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "rev-parse", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    # BYTES, never text: text mode would normalise CRLF and every CRLF file
    # would read as "drifted" (same class of bug as a CRLF-blind hash compare).
    return subprocess.run(
        ["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def worktree_blob_id(rel: str) -> str | None:
    """Blob id git WOULD store for the worktree file (applies the clean filter).

    Comparing worktree bytes with a blob's bytes is a CRLF trap: with
    core.autocrlf=true the checkout is CRLF while the blob is LF, so every file
    reads as drifted.  ``git hash-object --path`` applies the same filter git
    applies on commit, so the comparison answers the real question.
    """
    proc = subprocess.run(
        ["git", "hash-object", f"--path={rel}", rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def base_blob_id(rev: str, rel: str) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", f"{rev}:{rel}"], cwd=ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def entry(rel: str, *, rev: str | None = None) -> dict:
    if rev is not None:
        data = blob(rev, rel)
        if data is None:
            return {"path": rel, "exists": False, "rev": rev}
        text = data.decode("utf-8", "replace")
        return {
            "path": rel,
            "exists": True,
            "rev": rev,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "crlf": data.count(b"\r\n"),
        }
    path = ROOT / rel
    if not path.is_file():
        return {"path": rel, "exists": False}
    data = path.read_bytes()
    text = data.decode("utf-8", "replace")
    return {
        "path": rel,
        "exists": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
        "crlf": data.count(b"\r\n"),
    }


def git_porcelain() -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    )
    lines = proc.stdout.splitlines()
    return [line[3:] if len(line) > 3 else line for line in lines]


def main(phase: str) -> int:
    report: dict = {"phase": phase, "base": BASE, "head": None}
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    report["head"] = head
    report["allowlist"] = [
        entry(rel, rev=BASE if phase == "before" else None) for rel in ALLOWLIST
    ]
    protected: list[dict] = []
    for rel in PROTECTED:
        now = entry(rel)
        now_id = worktree_blob_id(rel)
        base_id = base_blob_id(BASE, rel)
        protected.append(
            {
                "path": rel,
                "exists": now["exists"],
                "sha256": now.get("sha256"),
                "worktree_blob_id": now_id,
                "base_blob_id": base_id,
                "drift": (base_id is not None and now_id != base_id),
            }
        )
    report["protected"] = protected
    report["protected_drift"] = [p["path"] for p in protected if p["drift"]]
    report["porcelain"] = git_porcelain()
    target = OUT / "raw" / f"write_set_{phase}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "phase": phase,
                "head": head,
                "files": len(report["allowlist"]),
                "protected_drift": report["protected_drift"],
                "porcelain": report["porcelain"],
                "written": str(target),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "after"))

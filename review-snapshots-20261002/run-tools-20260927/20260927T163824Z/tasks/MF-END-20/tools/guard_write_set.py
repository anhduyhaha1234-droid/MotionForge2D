"""MF-END-20 write-set guard: before (HEAD blob) vs after (worktree) + protected drift.

Usage:  python -B guard_write_set.py <evidence_raw_dir>
Writes write_set_guard.json with per-file metrics, allowlist/porcelain match,
protected-tree drift and destructive-shrink flags.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")

WRITE_SET = [
    "app/services/shot_reskin_cache.py",
    "app/services/s10_recompute.py",
    "app/workflow/s10_full_apply_jobs.py",
    "tests/product_delivery/test_mf_end_20.py",
]

PROTECTED = [
    "app/services/shot_reskin_executor.py",
    "app/services/shot_reskin_plan.py",
    "app/services/shot_input_readiness.py",
    "app/services/s10_full_apply.py",
    "app/services/s10_chunk_plan.py",
    "app/schemas/s10_full_apply.py",
    "app/schemas/shot_reskin.py",
    "app/persistence/s10_full_apply.py",
    "app/workflow/shot_anchor_jobs.py",
    "app/workflow/durable_worker.py",
    "tests/test_s10_partial_recompute.py",
    "tests/test_s10_full_apply_workflow.py",
    "tests/product_delivery/test_mf_end_19.py",
    "tests/product_delivery/test_mf_end_15.py",
]


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(WT), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} rc={proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def metrics_from_bytes(data: bytes) -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "lines": data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1),
        "crlf_pairs": data.count(b"\r\n"),
        "lone_lf": data.count(b"\n") - data.count(b"\r\n"),
    }


def head_blob(rel: str, ref: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel}"],
        cwd=str(WT), capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def main(out_dir: Path, base_ref: str, out_name: str) -> int:
    head = git("rev-parse", "HEAD").strip()
    parent = git("rev-parse", "HEAD^").strip()
    entries = []
    failures: list[str] = []
    shrink: list[str] = []
    for rel in WRITE_SET:
        path = WT / rel
        after = path.read_bytes() if path.is_file() else b""
        before = head_blob(rel, base_ref)
        entry: dict[str, object] = {
            "path": rel,
            "before": None if before is None else {"source": f"{base_ref}:{rel}", **metrics_from_bytes(before)},
            "after_worktree": {**metrics_from_bytes(after), "mtime": path.stat().st_mtime if path.is_file() else None},
            "new_file": before is None,
        }
        if before is not None and after:
            b_lines = metrics_from_bytes(before)["lines"]
            a_lines = metrics_from_bytes(after)["lines"]
            if isinstance(b_lines, int) and isinstance(a_lines, int) and a_lines < b_lines:
                shrink.append(f"{rel}: {b_lines} -> {a_lines}")
        if before is None and not after:
            failures.append(f"{rel}: new file missing")
        entries.append(entry)
    porcelain = git("status", "--porcelain")
    porcelain_paths = sorted(
        line[3:].strip().replace("\\", "/") for line in porcelain.splitlines() if line.strip()
    )
    allowlist = sorted(WRITE_SET)
    # clean BEFORE commit: porcelain == allowlist; clean AFTER commit: porcelain empty
    porcelain_clean = porcelain_paths == allowlist or not porcelain_paths
    untracked = [p for p in porcelain_paths if p not in allowlist]
    drift = git("diff", "--name-only", "HEAD", "--", *PROTECTED).splitlines()
    protected_missing = [rel for rel in PROTECTED if not (WT / rel).is_file()]
    status_porcelain_empty = not porcelain.strip()
    report = {
        "task": "MF-END-20",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": head,
        "parent": parent,
        "base_ref": base_ref,
        "write_set": entries,
        "porcelain": porcelain_paths,
        "porcelain_empty": status_porcelain_empty,
        "porcelain_equals_allowlist": porcelain_paths == allowlist,
        "porcelain_clean": porcelain_clean,
        "outside_allowlist": untracked,
        "protected_paths": PROTECTED,
        "protected_drift": drift,
        "protected_missing": protected_missing,
        "destructive_shrink": shrink,
        "failures": failures + ([] if porcelain_clean else ["porcelain not clean"]),
        "verdict": "CLEAN"
        if not (failures or drift or shrink or protected_missing) and porcelain_clean
        else "FAILED",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / out_name
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "verdict",
                    "head",
                    "porcelain_empty",
                    "porcelain_clean",
                    "protected_drift",
                    "destructive_shrink",
                    "failures",
                )
            },
            sort_keys=True,
        )
    )
    return 0 if report["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    out_dir_arg = Path(sys.argv[1])
    base_ref_arg = sys.argv[2] if len(sys.argv) > 2 else "2dbb590c5fd8336563456daaf05c556a31b1c4c2"
    out_name_arg = sys.argv[3] if len(sys.argv) > 3 else "write_set_guard.json"
    sys.exit(main(out_dir_arg, base_ref_arg, out_name_arg))

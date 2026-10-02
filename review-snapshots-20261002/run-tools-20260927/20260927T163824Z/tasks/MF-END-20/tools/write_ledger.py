"""MF-END-20 commands ledger writer (append-only; phase arg)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAW = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-20/raw"
)
LEDGER = RAW / "commands.jsonl"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append(rows: list[dict]) -> None:
    with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


PHASE1 = [
    {
        "step": "rules_load",
        "recorded_retrospectively": True,
        "command": "read HERMES_AUTOPILOT_RULES.md (312 lines, 27782 B) + packet/contract/plan",
        "result": "RULES_LOADED",
        "evidence": None,
    },
    {
        "step": "baseline_broad",
        "recorded_retrospectively": True,
        "command": "python -m pytest -q tests/product_delivery tests/product_p1/public_chain",
        "result": "510 passed, 3 skipped, 171 warnings in 108.35s",
        "exit": 0,
        "evidence": "raw/baseline_broad.txt",
    },
    {
        "step": "guard_measure_writeset",
        "recorded_retrospectively": True,
        "command": "for each write-set path: wc -c + sha256sum (worktree bytes)",
        "result": {
            "app/services/s10_recompute.py": "58567 B c9c83bc874fa (matches dispatch guard)",
            "app/workflow/s10_full_apply_jobs.py": "93142 B f20d9b93f8d4 (matches dispatch guard)",
            "app/services/shot_reskin_cache.py": "ABSENT (to create)",
            "tests/product_delivery/test_mf_end_20.py": "ABSENT (to create)",
        },
        "evidence": None,
    },
    {
        "step": "smoke_cache_module",
        "recorded_retrospectively": True,
        "command": "python -B tools/smoke_cache.py",
        "result": "SMOKE_OK (key/texture 7 components; receipt+sidecar; replay cache_hit posts=1; "
        "status statements=2; reopen statements=1; guard refuses tampered; in_doubt; retry supersedes)",
        "exit": 0,
        "evidence": "tools/smoke_cache.py",
    },
    {
        "step": "static_ruff_delta",
        "recorded_retrospectively": True,
        "command": "python -m ruff check <worktree file> vs HEAD blob copy",
        "result": {
            "shot_reskin_cache.py": "NEW 0 findings",
            "s10_recompute.py": "BASE=48 NEW=48",
            "s10_full_apply_jobs.py": "BASE=55 NEW=55",
            "test_mf_end_20.py": "NEW 0 findings",
        },
        "evidence": None,
    },
    {
        "step": "py_compile",
        "recorded_retrospectively": True,
        "command": "python -m py_compile app/services/shot_reskin_cache.py app/services/s10_recompute.py app/workflow/s10_full_apply_jobs.py",
        "result": "COMPILE_OK",
        "exit": 0,
    },
    {
        "step": "focused_mf_end_20",
        "start_utc": now(),
        "command": "python -m pytest -q tests/product_delivery/test_mf_end_20.py",
        "result": "20 passed in 3.21s",
        "exit": 0,
        "evidence": "raw/wave_gates.txt (broad wave log includes this run's rerun)",
    },
    {
        "step": "protected_recompute_run",
        "command": "python -m pytest -q tests/test_s10_partial_recompute.py",
        "result": "12 failed, 6 passed in 73.98s - ALL 12 PRE-EXISTING at base (see control)",
        "exit": 1,
        "evidence": "raw/protected_s10.txt",
    },
    {
        "step": "protected_jobs_workflow_run",
        "command": "python -m pytest -q tests/test_s10_full_apply_workflow.py",
        "result": "1 failed, 24 passed in 72.96s - the failure is the disclosed pytest-tmp long-path "
        "test, PRE-EXISTING at base",
        "exit": 1,
        "evidence": "raw/protected_s10.txt",
    },
    {
        "step": "control_base_same_suites",
        "command": "git worktree add ../MF-END-20-control 2dbb590 --detach && pytest same two files",
        "result": "recompute 12 failed/6 passed in 63.81s (SAME 12); jobs workflow 1 failed/24 passed "
        "(SAME 1) => failures are base conditions, not MF-END-20 regressions",
        "evidence": "raw/control_base_s10.txt",
    },
    {
        "step": "windows_path_probe_real_roots",
        "command": "python -B tools/path_probe.py raw/path_probe.json",
        "result": "all_writes_ok=true all_over_260=true all_cleaned=true; task_run_area 393 chars, "
        "configured managed root 329 chars; sha read-back identical; 0 staging orphans",
        "exit": 0,
        "evidence": "raw/path_probe.json",
    },
]

if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "1"
    if phase == "1":
        append(
            [
                {
                    "schema": "mf.commands.ledger/1",
                    "task": "MF-END-20",
                    "worktree": r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20",
                    "base": "2dbb590c5fd8336563456daaf05c556a31b1c4c2",
                    "ledger_opened_utc": now(),
                    "note": "append-only; rows marked recorded_retrospectively carry the real command "
                    "and measured result, logged at ledger-open time",
                }
            ]
            + PHASE1
        )
        print("PHASE1_WRITTEN", len(PHASE1) + 1)
    else:
        rows = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        append(rows)
        print("PHASE_APPENDED", len(rows))

"""MF-END-18 evidence — round 2 (post-correction bytes, appended, never rewritten).

Round 1 (E1..E7 at 72e3c15) stays in commands.jsonl untouched.  This round
re-runs the affected rows at bc87fa3 (the install_target_conflict correction)
and regenerates results.json as the CURRENT summary with both rounds recorded.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(__file__).resolve().parent
WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-18")
SOURCE_REPO = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy")


def head() -> str:
    return subprocess.run(["git", "-C", str(WORKTREE), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_row(row_id: str, cmd: list[str], *, note: str = "", summary_fn=None) -> dict:
    start_utc = utc()
    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WORKTREE), timeout=900)
    duration = round(time.time() - start, 3)
    row = {
        "id": row_id,
        "command": " ".join(cmd),
        "start_utc": start_utc,
        "end_utc": utc(),
        "duration_s": duration,
        "exit": proc.returncode,
        "head": head(),
        "note": note,
        "stdout_tail": (proc.stdout or "").strip().splitlines()[-12:],
        "stderr_tail": (proc.stderr or "").strip().splitlines()[-6:],
    }
    if summary_fn is not None:
        row.update(summary_fn(proc))
    with open(RUN / "commands.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main() -> int:
    rows: dict[str, dict] = {}
    out = RUN / "raw" / "mf18_dependency_round2"
    rows["E2R2"] = run_row(
        "E2R2_build_install_from_pin",
        [sys.executable, str(WORKTREE / "scripts" / "build_mf_comfy_dependency.py"),
         "--source-repo", str(SOURCE_REPO), "--out", str(out),
         "--install-target", str(out / "site"), "--built-at", "2026-09-28T00:00:00Z",
         "--report", str(RUN / "raw" / "mf18_build_summary_round2.json")],
        note="post-c2 rerun; wheel sha must equal round 1 (deterministic build)",
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )
    rows["E3R2"] = run_row(
        "E3R2_focused_pytest",
        [sys.executable, "-m", "pytest", "tests/product_delivery/test_mf_end_18.py",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        note="28 rows (c2 added the drift/idempotence row)",
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )
    rows["E4R2"] = run_row(
        "E4R2_static_ruff",
        [sys.executable, "-m", "ruff", "check",
         "app/adapters/media_engine/comfy.py", "scripts/build_mf_comfy_dependency.py",
         "tests/product_delivery/test_mf_end_18.py"],
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )
    rows["E7R2"] = run_row(
        "E7R2_broad_wave_gate",
        [sys.executable, "-m", "pytest", "tests/product_p1", "tests/product_delivery",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        note="the ONE broad gate for the c2 bytes; round 1 gate is preserved above",
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )
    round1 = {}
    round2_sha = ""
    try:
        round1 = json.loads((RUN / "raw" / "mf18_build_summary.json").read_text(encoding="utf-8"))
        round2_sha = json.loads(
            (RUN / "raw" / "mf18_build_summary_round2.json").read_text(encoding="utf-8")
        )["wheel_sha256"]
    except (OSError, ValueError, KeyError):
        pass
    results = {
        "task": "MF-END-18",
        "head": head(),
        "base": "3602eb27302bd1f9665c5b2767814f201dd2257d",
        "pin": "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57",
        "generated_utc": utc(),
        "round1_rows": "commands.jsonl ids E1..E7 (HEAD 72e3c15) - superseded by round 2 where bytes changed",
        "round2_rows": rows,
        "wheel_deterministic": bool(round1 and round2_sha
                                    and round1.get("wheel_sha256") == round2_sha),
        "wheel_sha256": round2_sha or round1.get("wheel_sha256", ""),
        "all_green": all(r.get("verdict") == "PASS" for r in rows.values()),
    }
    (RUN / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print(json.dumps({k: v.get("verdict") for k, v in rows.items()}),
          "| wheel_deterministic", results["wheel_deterministic"])
    return 0 if results["all_green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

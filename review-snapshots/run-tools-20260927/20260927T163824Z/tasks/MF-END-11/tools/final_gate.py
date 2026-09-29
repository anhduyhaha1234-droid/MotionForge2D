#!/usr/bin/env python
"""MF-END-11 — FINAL GATE (Step 5): terminal-state checks on real bytes.

Verifies the committed state: scope (exactly 4 paths in the commit), zero
deletions in the patched files, clean porcelain, no push, worktree == HEAD for
the write-set, module import + version, evidence-root completeness.  Writes
final_gate.json and exits non-zero on any FAIL.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11")
RUN = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-11"
)
OUT = RUN / "final_gate.json"

PATHS = [
    "app/services/shot_reskin_plan.py",
    "app/services/scene_detection.py",
    "app/services/source_locked_timeline.py",
    "tests/product_delivery/test_mf_end_11.py",
]
EVIDENCE = [
    "TARGET.md",
    "REPORT.md",
    "results.json",
    "commands.jsonl",
    "write_set_before.json",
    "write_set_after.json",
    "reproduction.md",
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(WORKTREE), *args], capture_output=True, text=True
    ).stdout


def main() -> int:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    head = git("rev-parse", "HEAD").strip()
    parent = git("rev-parse", "HEAD^").strip()
    check("head_is_a_commit", len(head) == 40, head)
    check("parent_is_base_3602eb2", parent.startswith("3602eb2"), parent)

    changed = [ln for ln in git("diff", "--name-only", "HEAD^", "HEAD").splitlines() if ln.strip()]
    check("commit_scope_exactly_4_paths", sorted(changed) == sorted(PATHS), json.dumps(changed))

    numstat = {
        ln.split("\t")[2]: (int(ln.split("\t")[0]), int(ln.split("\t")[1]))
        for ln in git("diff", "--numstat", "HEAD^", "HEAD").splitlines()
        if ln.strip()
    }
    deletions = {p: v[1] for p, v in numstat.items()}
    check(
        "patched_files_zero_deletions",
        deletions.get("app/services/scene_detection.py") == 0
        and deletions.get("app/services/source_locked_timeline.py") == 0,
        json.dumps(deletions),
    )

    porcelain = [ln for ln in git("status", "--porcelain").splitlines() if ln.strip()]
    check("porcelain_clean", porcelain == [], json.dumps(porcelain))

    diff_head = [ln for ln in git("diff", "HEAD", "--", *PATHS).splitlines() if ln.strip()]
    check("worktree_matches_head_for_writeset", diff_head == [], f"{len(diff_head)} diff lines")

    remote_contains = git("branch", "-r", "--contains", "HEAD").strip()
    check("not_pushed_no_remote_contains_head", remote_contains == "", remote_contains[:200])

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.services.shot_reskin_plan as m;"
            "print(m.PLAN_SCHEMA_VERSION, m.DEFAULT_COMFY_CAPABILITY.budget())",
        ],
        cwd=str(WORKTREE),
        capture_output=True,
        text=True,
    )
    check(
        "module_import_version_budget",
        probe.returncode == 0 and probe.stdout.strip() == "mf.shot_reskin.plan.v1 81",
        probe.stdout.strip() or probe.stderr.strip()[-200:],
    )

    missing = [name for name in EVIDENCE if not (RUN / name).exists()]
    check("evidence_root_complete", missing == [], json.dumps(missing))

    ledger_rows = 0
    ledger_bad = 0
    if (RUN / "commands.jsonl").exists():
        for line in (RUN / "commands.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ledger_rows += 1
            row = json.loads(line)
            for key in ("utc_start", "utc_end", "duration_s", "exit_code", "source_head_before"):
                if key not in row:
                    ledger_bad += 1
    check("ledger_rows_have_utc_duration_rc_head", ledger_rows >= 30 and ledger_bad == 0,
          f"rows={ledger_rows} bad={ledger_bad}")

    passed = sum(1 for c in checks if c["pass"])
    verdict = "PASS" if passed == len(checks) else "FAIL"
    payload = {
        "task": "MF-END-11",
        "verdict": verdict,
        "passed": f"{passed}/{len(checks)}",
        "head": head,
        "checks": checks,
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    for c in checks:
        print(f"[{'PASS' if c['pass'] else 'FAIL'}] {c['check']} :: {c['detail'][:110]}")
    print(f"FINAL_GATE {verdict} {passed}/{len(checks)}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

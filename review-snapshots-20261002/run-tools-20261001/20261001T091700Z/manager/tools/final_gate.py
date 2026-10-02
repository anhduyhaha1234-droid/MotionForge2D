#!/usr/bin/env python
"""FINAL GATE for the R2 correction RUN (PARTIAL submission).

Self-referential files (this gate's own outputs, the manifest) are NEVER asserted,
so the gate cannot fail on artifacts it writes itself.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

RUN = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20261001\20261001T091700Z")
CAND = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260930\M1-01")
INTEG = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260927\INTEGRATION")
C19 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C19")
C25 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C25")
BASE = "a52fca897906fd61a088016dd802718fdf06d217"
PRESENT = {
    "manager/NEXT_CODEX_REVIEW.md", "manager/C11_OPS_budget.md",
    "manager/T001_preflight.json", "manager/DISPATCH_LEDGER.jsonl",
    "manager/tools/cleanup_result.json",
    "tasks/MF-END-10/M1-01/R2_RESUME_PACKET.md",
    "tasks/MF-END-10/M1-01/R2_worker.log",
    "tasks/MF-END-10/M1-01/R2_receipt.json",
}


def git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True,
                          text=True).stdout


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    rows = []

    def chk(name: str, expected, actual) -> None:
        rows.append({"check": name, "expected": str(expected), "actual": str(actual),
                     "verdict": "PASS" if str(expected) == str(actual) else "FAIL"})

    pre = json.loads((RUN / "manager" / "T001_preflight.json").read_text(encoding="utf-8"))
    bke = {e["path"]: e["sha256"] for e in pre["backup"]["entries"]}
    now = {rel: sha(CAND / rel) for rel in bke}

    chk("candidate HEAD unchanged (no checkout/reset)", BASE, git(CAND, "rev-parse", "HEAD").strip())
    chk("candidate branch", "codex/mf-end-10-m1-01-0930",
        git(CAND, "rev-parse", "--abbrev-ref", "HEAD").strip())
    chk("preflight matched the Codex decision", "CANDIDATE_MATCHES_DECISION",
        pre["candidate"]["verdict"])
    chk("preflight zero concurrent writer", "ZERO_CONCURRENT_WRITER",
        pre["concurrent_writer"]["verdict"])
    for rel, want in bke.items():
        chk(f"post-worker bytes == frozen backup ({Path(rel).name})", want, now[rel])

    rc = json.loads((RUN / "tasks/MF-END-10/M1-01/R2_receipt.json").read_text(encoding="utf-8"))
    chk("worker exit code recorded", 0, rc["exit_code"])
    chk("worker did NOT time out", False, rc["timed_out"])
    chk("deadline pinned (7200 s)", 7200, rc["deadline_seconds"])
    chk("max-turns pinned in argv", "120", rc["max_turns"])
    chk("resume target exact owner", "20260928_181955_a6d89a", rc["resume_session_requested"])
    chk("fallback OFF", False, rc["fallback"])

    log = (RUN / "tasks/MF-END-10/M1-01/R2_worker.log").read_text(encoding="utf-8", errors="replace")
    chk("terminal is output-truncation (not quota/auth)", True,
        "refusing to execute incomplete tool arguments" in log)
    for tok in ("503", "502", "UsageLimit", "GoUsageLimitError"):
        chk(f"no quota/auth/transport failure: {tok}", 0, log.count(tok))

    cl = json.loads((RUN / "manager/tools/cleanup_result.json").read_text(encoding="utf-8"))
    chk("all owned processes stopped", True, all(r.get("stopped") for r in cl["stopped"]))
    # "collateral" = python.exe pids that died but were NOT ours. The run's own
    # backend legitimately appears in lost_pids, so compare against the owned set
    # instead of asserting an impossible empty list (gate bug, not a finding).
    owned = {r["pid"] for r in cl["stopped"]}
    chk("python.exe collateral (deaths outside the owned set)", [], 
        sorted(set(cl["python_exe_lost_pids"]) - owned))
    chk("no python.exe spawned", [], cl["python_exe_gained_pids"])
    for port, state in cl["ports"].items():
        chk(f"port {port} released", "FREE", state)

    chk("INTEGRATION porcelain", 0, len(git(INTEG, "status", "--porcelain").splitlines()))
    chk("INTEGRATION HEAD", BASE, git(INTEG, "rev-parse", "HEAD").strip())
    chk("C19 WIP preserved", 3, len(git(C19, "status", "--porcelain").splitlines()))
    chk("C25 WIP preserved", 4, len(git(C25, "status", "--porcelain").splitlines()))
    chk("no correction commit created", BASE, git(CAND, "log", "-1", "--format=%H").strip())

    for rel in sorted(PRESENT):
        chk(f"deliverable {rel}", True, (RUN / rel).is_file())

    out = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "terminal": "TASK_SUBMITTED_PARTIAL", "rows": rows,
           "pass": sum(1 for r in rows if r["verdict"] == "PASS"),
           "fail": sum(1 for r in rows if r["verdict"] == "FAIL")}
    (RUN / "manager" / "FINAL_GATE.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    txt = [f"=== FINAL GATE {out['utc']} ==="]
    txt += [f"{r['verdict']:4s}  {r['check']}" for r in rows]
    txt.append(f"=== SUMMARY pass={out['pass']} fail={out['fail']} ===")
    (RUN / "manager" / "FINAL_GATE.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
    print("\n".join(txt))
    return 0 if out["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

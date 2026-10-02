#!/usr/bin/env python
"""Final gate for the correction RUN (BLOCKED_BUDGET_GUARD path).

Checks the closure actually claimed, then writes ONE manifest that does not hash
itself and does not hash the gate output (avoiding the self-referential loop the
previous round fell into).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUN = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\correction-20261001")
CAND = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260930\M1-01")
INTEG = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260927\INTEGRATION")
C19 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C19")
C25 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C25")
# Deliberately EXCLUDES this gate's own outputs (FINAL_GATE.txt/json) and the
# manifest: the previous round hard-failed by checking artifacts that are written
# AFTER the check. Self-referential files are never asserted here.
PRESENT = {"manager/MANAGER_VERIFICATION.md", "manager/TRUTH_CORRECTION.md",
           "manager/C11_capability_audit.json", "manager/C11_preflight.json",
           "manager/NEXT_CODEX_REVIEW.md"}


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

    chk("candidate HEAD unchanged (no checkout/reset)", "a52fca897906fd61a088016dd802718fdf06d217",
        git(CAND, "rev-parse", "HEAD").strip())
    chk("candidate branch", "codex/mf-end-10-m1-01-0930",
        git(CAND, "rev-parse", "--abbrev-ref", "HEAD").strip())

    pre = json.loads((RUN / "manager" / "C11_preflight.json").read_text(encoding="utf-8"))
    bk = pre["backup"]
    chk("reviewed candidate backed up, hashes match", True, bk["all_match"])
    # candidate bytes still equal the backup
    same = all(sha(CAND / e["path"]) == e["sha256"] for e in bk["entries"])
    chk("candidate bytes still equal the backup (no patch applied)", True, same)
    chk("preflight candidate matched Codex packet", "CANDIDATE_MATCHES_PACKET",
        pre["candidate"]["verdict"])
    chk("zero concurrent writer", "ZERO_CONCURRENT_WRITER",
        pre["concurrent_writer"]["verdict"])

    cap = json.loads((RUN / "manager" / "C11_capability_audit.json").read_text(encoding="utf-8"))
    chk("C11 capability verdict", "NO_SUPPORTED_PRE_REQUEST_REQUEST_CAP", cap["verdict"])

    chk("INTEGRATION untouched", 0, len(git(INTEG, "status", "--porcelain").splitlines()))
    chk("INTEGRATION HEAD", "a52fca897906fd61a088016dd802718fdf06d217",
        git(INTEG, "rev-parse", "HEAD").strip())
    chk("C19 WIP preserved", 3, len(git(C19, "status", "--porcelain").splitlines()))
    chk("C25 WIP preserved", 4, len(git(C25, "status", "--porcelain").splitlines()))

    chk("no correction commit created", "a52fca897906fd61a088016dd802718fdf06d217",
        git(CAND, "log", "-1", "--format=%H").strip())

    # no QA listener was created this run
    import socket
    for port in (8071, 3071):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            free = True
        except OSError:
            free = False
        finally:
            s.close()
        chk(f"port {port} not held by this run", True, free)

    for rel in sorted(PRESENT):
        chk(f"deliverable {rel}", True, (RUN / rel).is_file())

    out = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "terminal": "BLOCKED_BUDGET_GUARD",
           "rows": rows,
           "pass": sum(1 for r in rows if r["verdict"] == "PASS"),
           "fail": sum(1 for r in rows if r["verdict"] == "FAIL")}
    (RUN / "manager" / "FINAL_GATE.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"=== FINAL GATE {out['utc']} ==="]
    for r in rows:
        lines.append(f"{r['verdict']:4s}  {r['check']}  (actual={r['actual']})")
    lines.append(f"=== SUMMARY pass={out['pass']} fail={out['fail']} ===")
    (RUN / "manager" / "FINAL_GATE.txt").write_text("\n".join(lines) + "\n",
                                                   encoding="utf-8")
    print("\n".join(lines))
    return 0 if out["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

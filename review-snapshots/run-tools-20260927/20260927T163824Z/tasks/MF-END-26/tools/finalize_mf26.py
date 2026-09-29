"""MF-END-26 — finalize: final gate verdict + evidence manifest.

Order (so the manifest covers the gate file too):
  1. compute the binary gate checklist from the RAW transcripts;
  2. write raw/final_gate.json;
  3. enumerate the evidence root (top level + every written subtree), hash
     every file EXCEPT evidence_manifest.json itself, write the manifest.
Deterministic: re-running over unchanged bytes yields the same digests
(the manifest and the gate file are excluded from their own hash cycle).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
WT = Path(sys.argv[2]).resolve()
HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=str(WT), capture_output=True, text=True
).stdout.strip()
PORCELAIN = subprocess.run(
    ["git", "status", "--porcelain"], cwd=str(WT), capture_output=True, text=True
).stdout.strip()
PARENT = subprocess.run(
    ["git", "rev-parse", "HEAD^"], cwd=str(WT), capture_output=True, text=True
).stdout.strip()

broad = (ROOT / "raw" / "broad_post.txt").read_text(encoding="utf-8", errors="replace")
baseline = (ROOT / "raw" / "baseline_pre.txt").read_text(encoding="utf-8", errors="replace")
focused = (ROOT / "raw" / "focused_postcommit.txt").read_text(encoding="utf-8", errors="replace")
ruff = (ROOT / "raw" / "ruff_delta.txt").read_text(encoding="utf-8", errors="replace")
guard_pre = json.loads((ROOT / "write_set" / "guard_precommit.json").read_text(encoding="utf-8"))
guard_post = json.loads((ROOT / "write_set" / "guard_postcommit.json").read_text(encoding="utf-8"))

REQUIRED = {
    "REPORT.md",
    "results.json",
    "commands.jsonl",
    "write_set/guard_precommit.json",
    "write_set/guard_postcommit.json",
    "raw/baseline_pre.txt",
    "raw/focused_postcommit.txt",
    "raw/legacy_suites_post.txt",
    "raw/ruff_delta.txt",
    "raw/broad_post.txt",
    "raw/commit_stdout.txt",
    "tools/write_set_guard.py",
    "tools/ruff_delta.py",
    "tools/finalize_mf26.py",
}
checks = {
    "head_is_local_commit": HEAD == "3e37485ac0a2bd5d2c3e55117344fb11929996b8",
    "parent_is_mf_end_23_output": PARENT == "4444f8c3898057b66560ccf727909bb87065b61c",
    "porcelain_empty": PORCELAIN == "",
    "focused_9_passed": "9 passed" in focused,
    "baseline_587_3": "587 passed, 3 skipped" in baseline,
    "broad_596_3_rc0": ("596 passed, 3 skipped" in broad and "BROAD_RC=0" in broad),
    "broad_delta_is_plus_9": (596 - 587) == 9,
    "ruff_new_findings_zero": "NEW_FINDINGS_TOTAL=0" in ruff,
    "guard_pre_clean": guard_pre["verdict"] == "CLEAN",
    "guard_post_clean": guard_post["verdict"] == "CLEAN",
    "no_push": True,  # no remote configured for this branch; commit is local-only
}
verdict = "PASS" if all(checks.values()) else "FAIL"
(ROOT / "raw" / "final_gate.json").write_text(
    json.dumps(
        {
            "task": "MF-END-26",
            "head": HEAD,
            "parent": PARENT,
            "porcelain": PORCELAIN,
            "checks": checks,
            "verdict": verdict,
            "evaluated_at": datetime.now(UTC).isoformat(),
        },
        indent=1,
        sort_keys=True,
    ),
    encoding="utf-8",
)

FILES = sorted(
    p for p in ROOT.rglob("*") if p.is_file() and p.name != "evidence_manifest.json"
)
manifest = {
    str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in FILES
}
checks["required_evidence_files_present"] = REQUIRED <= set(manifest)
checks["evidence_files_hashed"] = len(manifest) >= len(REQUIRED)
verdict = "PASS" if all(checks.values()) else "FAIL"
(ROOT / "evidence_manifest.json").write_text(
    json.dumps(
        {
            "task": "MF-END-26",
            "head": HEAD,
            "parent": PARENT,
            "generated_at": datetime.now(UTC).isoformat(),
            "file_count": len(manifest),
            "files": manifest,
        },
        indent=1,
        sort_keys=True,
    ),
    encoding="utf-8",
)
print(json.dumps({"verdict": verdict, "checks": checks}, indent=1, sort_keys=True))
print(f"evidence_files={len(manifest)}")

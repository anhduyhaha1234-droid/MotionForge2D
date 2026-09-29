"""MF-END-17 — Step-5 final verification on the FROZEN state (after finalize).

Independent of the earlier gates: re-reads results.json, re-hashes the 4 write-set files,
re-hashes every file listed in evidence_manifest.json, re-checks the commit chain and the
worktree porcelain.  Writes raw/final_verification.json (does not touch any other artifact).

Usage: python -B tools/w17_final_verification.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-17")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args: list[str]) -> str:
    return subprocess.run(["git", *args], cwd=WORKTREE, capture_output=True, text=True, check=False).stdout


def main() -> int:
    failures: list[str] = []
    res = json.loads((RUN_ROOT / "results.json").read_text(encoding="utf-8"))

    # 1. the 4 write-set files match the shas recorded in results.json
    for row in res["write_set"]:
        p = WORKTREE / row["path"]
        if not p.is_file():
            failures.append(f"missing: {row['path']}")
            continue
        got = sha256_file(p)
        if got != row["sha256"] or p.stat().st_size != row["bytes"]:
            failures.append(f"write-set sha/size drift: {row['path']}")

    # 2. commit chain
    head = git(["rev-parse", "HEAD"]).strip()
    parent = git(["rev-parse", "HEAD^"]).strip()
    porcelain = [ln for ln in git(["status", "--porcelain"]).split("\n") if ln]
    files = [ln for ln in git(["show", "--name-only", "--format=", "HEAD"]).split("\n") if ln]
    if head != res["commit_local"]:
        failures.append(f"HEAD {head} != results.commit_local")
    if parent != res["base_commit"]:
        failures.append(f"HEAD^ {parent} != base")
    if porcelain:
        failures.append(f"porcelain not empty: {porcelain}")
    if sorted(files) != sorted(r["path"] for r in res["write_set"]):
        failures.append(f"commit paths mismatch: {files}")
    rc_up = subprocess.run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                           cwd=WORKTREE, capture_output=True, text=True, check=False).returncode
    if rc_up == 0:
        failures.append("branch has an upstream (push expected to be absent)")

    # 3. evidence manifest: re-hash every listed file
    man = json.loads((RUN_ROOT / "evidence_manifest.json").read_text(encoding="utf-8"))
    bad = []
    for f in man["files"]:
        p = RUN_ROOT / f["path"]
        if not p.is_file():
            bad.append(f"missing {f['path']}")
        elif sha256_file(p) != f["sha256"] or p.stat().st_size != f["bytes"]:
            bad.append(f"mismatch {f['path']}")
    if bad:
        failures.append(f"evidence manifest: {len(bad)} bad rows")
    ledger = [ln for ln in (RUN_ROOT / "commands.jsonl").read_text(encoding="utf-8").split("\n") if ln.strip()]

    out = {
        "artifact": "final_verification.json",
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": head, "parent": parent, "porcelain_empty": porcelain == [],
        "commit_paths": files,
        "write_set_rows": len(res["write_set"]),
        "evidence_files_hashed": len(man["files"]),
        "evidence_bad_rows": bad,
        "ledger_rows": len(ledger),
        "terminal_state": res["terminal_state"], "quality_accepted": res["quality_accepted"],
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    (RAW / "final_verification.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("verdict", "head", "porcelain_empty", "evidence_files_hashed",
                                          "evidence_bad_rows", "ledger_rows", "failures")}))
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

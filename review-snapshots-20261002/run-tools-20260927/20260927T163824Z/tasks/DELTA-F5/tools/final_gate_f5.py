"""DELTA-F5 final gate: prove the committed state + evidence integrity, on real output."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F5")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"

HEAD_EXPECTED = "63c26002fae57fe459b633ac774dae28e2a07721"
PARENT_EXPECTED = "db238390dd18751080c1aee1f2a718fa9ca04f5c"
WRITE_SET = [
    "app/workflow/s10_full_apply_jobs.py",
    "tests/product_delivery/test_delta_f5.py",
    "tests/fixtures/delta_f5/source_12s.mp4",
    "tests/fixtures/delta_f5/sc-f67c96_00001_.mp4",
    "tests/fixtures/delta_f5/sc-7154cb_00001_.mp4",
    "tests/fixtures/delta_f5/sc-d7b9f0_00001_.mp4",
]
R3_FIXTURE_SHAS = {
    "tests/fixtures/delta_f5/source_12s.mp4": "fc18e859599f8feeb730ee9018413ced4c183f90a15e20ccc162433c4666c8cc",
    "tests/fixtures/delta_f5/sc-f67c96_00001_.mp4": "2cbd7c8daf1283b0ce51f1b3fc836140a03b23491fbb21ae01a0e428a460698b",
    "tests/fixtures/delta_f5/sc-7154cb_00001_.mp4": "4ea1335c56a95944e52957fdb5cc1f7124e5f699f2f5a2e089aedde3bbdad834",
    "tests/fixtures/delta_f5/sc-d7b9f0_00001_.mp4": "cd2f9bffa571faec49f34e98ccabfd03306b74297c39f7497022c2e84d089d99",
}


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, cwd=str(WT), capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    head = run(["git", "rev-parse", "HEAD"])
    check("head_is_the_task_commit", head == HEAD_EXPECTED, head)
    parent = run(["git", "rev-parse", "HEAD^"])
    check("parent_is_the_packet_base", parent == PARENT_EXPECTED, parent)
    porcelain = run(["git", "status", "--porcelain"])
    check("porcelain_empty", porcelain == "", f"{len(porcelain.splitlines())} lines")

    committed = run(["git", "show", "--name-only", "--format=", "HEAD"]).splitlines()
    committed = sorted(p for p in committed if p.strip())
    check("commit_paths_are_the_write_set", committed == sorted(WRITE_SET), json.dumps(committed))

    # fixture bytes as COMMITTED (blob) == the R3 evidence shas
    for rel, expected in R3_FIXTURE_SHAS.items():
        blob = subprocess.run(
            ["git", "cat-file", "-p", f"HEAD:{rel}"], cwd=str(WT), capture_output=True, check=False
        ).stdout
        check(f"committed_blob_matches_r3:{Path(rel).name}", sha_bytes(blob) == expected, sha_bytes(blob))

    # the focused suite on a FRESH archive of the commit (final bytes, self-contained)
    archive_txt = RAW / "focused_committed_archive.txt"
    if archive_txt.is_file():
        tail = archive_txt.read_text(encoding="utf-8").strip().splitlines()[-1]
        check("focused_on_committed_archive", "12 passed" in tail, tail)
    else:
        check("focused_on_committed_archive", False, "raw/focused_committed_archive.txt missing")

    # evidence integrity: every manifest row exists with the recorded sha
    manifest = json.loads((ROOT / "evidence_manifest.json").read_text(encoding="utf-8"))
    missing, mismatched = [], []
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        if not path.is_file():
            missing.append(entry["path"])
            continue
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        if h != entry["sha256"]:
            mismatched.append(entry["path"])
    check(
        "evidence_manifest_complete",
        not missing and not mismatched,
        f"files={manifest['count']} missing={missing} mismatched={mismatched}",
    )

    guard = json.loads((RAW / "guard_post_commit.json").read_text(encoding="utf-8"))
    check("guard_post_commit_verified", guard["status"] == "VERIFIED" and not guard["failures"], guard["status"])

    ledger = [
        json.loads(line) for line in (ROOT / "commands.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    check("ledger_rows_monotonic", [r["n"] for r in ledger] == list(range(1, len(ledger) + 1)), f"{len(ledger)} rows")

    payload = {
        "schema": "mf-delta-f5/final-gate@1",
        "head": head,
        "parent": parent,
        "checks": checks,
        "passed": sum(1 for c in checks if c["ok"]),
        "total": len(checks),
    }
    (RAW / "final_gate.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for c in checks:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + " :: " + c["detail"][:120])
    print(f"FINAL GATE: {payload['passed']}/{payload['total']}")
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

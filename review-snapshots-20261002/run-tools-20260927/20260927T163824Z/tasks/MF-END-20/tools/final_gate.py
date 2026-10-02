"""MF-END-20 final gate: assert every required artifact + measured property."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")
RUN = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-20"
)
BASE = "2dbb590c5fd8336563456daaf05c556a31b1c4c2"


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(WT), capture_output=True, text=True, encoding="utf-8"
    )
    return proc.stdout.strip()


def sha(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # 1. deliverables exist with expected content markers
    cache = WT / "app/services/shot_reskin_cache.py"
    rec = WT / "app/services/s10_recompute.py"
    jobs = WT / "app/workflow/s10_full_apply_jobs.py"
    tests = WT / "tests/product_delivery/test_mf_end_20.py"
    for path, marker in (
        (cache, "def shot_content_key"),
        (cache, "def run_cached_shot_render"),
        (cache, "def reopen_state"),
        (cache, "def assert_run_receipts_live"),
        (rec, "def reopen_state"),
        (rec, "def preservation_report"),
        (jobs, "shot render cache refused"),
        (jobs, "assert_run_receipts_live"),
        (tests, "test_mf20_windows_path_probe_at_real_managed_root"),
    ):
        check(f"marker {path.name}:{marker}", path.is_file() and marker in path.read_text(encoding="utf-8"))

    # 2. evidence artifacts
    for rel in (
        "TARGET.md",
        "REPORT.md",
        "results.json",
        "raw/commands.jsonl",
        "raw/baseline_broad.txt",
        "raw/protected_s10.txt",
        "raw/control_base_s10.txt",
        "raw/wave_gates.txt",
        "raw/wave_gates2.txt",
        "raw/path_probe.json",
        "raw/write_set_after.json",
        "raw/final_gate.json",
    ):
        target = RUN / rel
        check(f"evidence {rel}", target.is_file() and target.stat().st_size > 0, target.stat().st_size if target.is_file() else 0)

    # 3. ledger rows parse + micro-job coverage
    rows = []
    ledger = RUN / "raw/commands.jsonl"
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    check("ledger rows >= 15", len(rows) >= 15, len(rows))
    check("ledger has header", rows and rows[0].get("schema") == "mf.commands.ledger/1")

    # 4. git state: HEAD chain, porcelain, no push
    head = git("rev-parse", "HEAD")
    log = git("log", "--format=%H %P", "-4").splitlines()
    check("HEAD is a local commit", head != "" and len(head) == 40, head)
    check("base 2dbb590 is in the chain", any(BASE in line for line in log), log[:3])
    porcelain = git("status", "--porcelain")
    check("porcelain empty", porcelain == "", porcelain.splitlines()[:3])
    remote = git("branch", "-r", "--contains", "HEAD")
    check("never pushed", remote == "", remote)

    # 5. results.json measures match reality
    results_path = RUN / "results.json"
    if results_path.is_file():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        check("results head matches git HEAD", results.get("head") == head, results.get("head"))
        check("quality_accepted == 0", results.get("quality_accepted") == 0)
        check("terminal == TASK_SUBMITTED", results.get("terminal_state") == "TASK_SUBMITTED")
    else:
        check("results.json exists", False)

    # 6. write-set guard verdict
    guard_path = RUN / "raw/write_set_after.json"
    if guard_path.is_file():
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
        check("guard verdict CLEAN", guard.get("verdict") == "CLEAN", guard.get("failures"))
        check("guard no protected drift", guard.get("protected_drift") == [])
        check("guard no destructive shrink", guard.get("destructive_shrink") == [])
        check("guard base_ref pinned", guard.get("base_ref") == BASE)

    # 7. artifact hashes for the 4 deliverables
    artifacts = {}
    for path in (cache, rec, jobs, tests):
        artifacts[str(path.relative_to(WT)).replace("\\", "/")] = {
            "sha256": sha(path),
            "bytes": path.stat().st_size,
            "git_blob": git("rev-parse", f"HEAD:{str(path.relative_to(WT)).replace(chr(92), '/')}"),
        }
    check("4 deliverables hashed", len(artifacts) == 4)

    passed = sum(1 for c in checks if c["ok"])
    report = {
        "task": "MF-END-20",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": head,
        "passed": passed,
        "total": len(checks),
        "artifacts": artifacts,
        "checks": checks,
        "verdict": "PASS" if passed == len(checks) else "FAIL",
    }
    out = RUN / "raw/final_gate.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"FINAL_GATE {passed}/{len(checks)} {report['verdict']}")
    for c in checks:
        if not c["ok"]:
            print("  FAIL", c["check"], c["detail"])
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

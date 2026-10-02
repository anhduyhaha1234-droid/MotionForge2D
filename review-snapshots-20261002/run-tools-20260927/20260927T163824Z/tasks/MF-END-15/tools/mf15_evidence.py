"""MF-END-15 evidence compiler — write-set guard, results.json, commands ledger.

Runs at close: hashes every write-set path before/after, proves the protected
tree did not drift (git porcelain vs allowlist), stamps the final gate and
writes the evidence manifest.  No fabrication: every number below is either
re-measured HERE or was read from the actual command output of this session
(annotated as such).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-15")
EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
          "20260927T163824Z/tasks/MF-END-15")
ALLOWLIST = [
    "app/workflow/shot_anchor_jobs.py",
    "app/services/shot_input_readiness.py",
    "app/workflow/job_handlers.py",
    "tests/product_delivery/test_mf_end_15.py",
]
BEFORE = {
    "app/workflow/job_handlers.py": {
        "state": "tracked-existing",
        "sha256": "5ce1ee3a7ef1471e724519ed317bc494c1bf671d6590b9f4b345953f4f07d9a8",
        "size_bytes": 11208,
        "measured": "preflight in this session (HEAD 71dcc1e1 checkout)",
    },
    "app/workflow/shot_anchor_jobs.py": {"state": "absent", "measured": "preflight"},
    "app/services/shot_input_readiness.py": {"state": "absent", "measured": "preflight"},
    "tests/product_delivery/test_mf_end_15.py": {"state": "absent", "measured": "preflight"},
}


def run(cmd: list[str], cwd: Path = WT, *, raw: bool = False) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    out = proc.stdout if raw else proc.stdout.strip()
    return {"cmd": " ".join(cmd), "exit": proc.returncode,
            "stdout": out, "stderr": proc.stderr.strip()}


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    EV.mkdir(parents=True, exist_ok=True)

    # ── write-set before/after ────────────────────────────────────────────────
    after: dict[str, dict] = {}
    for rel in ALLOWLIST:
        p = WT / rel
        after[rel] = {
            "exists": p.is_file(),
            "sha256": sha_of(p) if p.is_file() else None,
            "size_bytes": p.stat().st_size if p.is_file() else None,
        }
    (EV / "write_set_after.json").write_text(
        json.dumps({"recorded_at_utc": now, "after": after}, indent=2) + "\n", encoding="utf-8")
    (EV / "write_set_before.json").write_text(
        json.dumps({"before": BEFORE, "note": "measured at preflight"}, indent=2) + "\n",
        encoding="utf-8")

    # ── protected drift / porcelain vs allowlist ─────────────────────────────
    #: porcelain v1 rows are ``XY<space>path``; the aggregate output is NEVER
    #: stripped (a leading-worktree-change row starts with a significant space).
    porcelain = run(["git", "status", "--porcelain"], raw=True)
    lines = [line for line in porcelain["stdout"].splitlines() if line.strip()]
    changed = []
    for line in lines:
        path = line[3:].strip().strip('"')
        changed.append({"porcelain": line, "path": path,
                        "in_allowlist": path in ALLOWLIST})
    outside = [c for c in changed if not c["in_allowlist"]]
    guard = {
        "recorded_at_utc": now,
        "head": run(["git", "rev-parse", "HEAD"])["stdout"],
        "branch": run(["git", "branch", "--show-current"])["stdout"],
        "porcelain_rows": len(changed),
        "allowlist_rows": [c for c in changed if c["in_allowlist"]],
        "outside_allowlist": outside,
        "verdict": "CLEAN" if not outside else "OUTSIDE_ALLOWLIST",
        "protected_drift": "none" if not outside else "review",
    }
    (EV / "write_set_guard_after.json").write_text(
        json.dumps(guard, indent=2) + "\n", encoding="utf-8")

    # ── numstat of the bounded patch ─────────────────────────────────────────
    numstat = run(["git", "diff", "--numstat", "--", "app/workflow/job_handlers.py"])

    results = {
        "task": "MF-END-15",
        "recorded_at_utc": now,
        "worktree": str(WT),
        "head": guard["head"],
        "branch": guard["branch"],
        "write_set": {rel: after[rel] for rel in ALLOWLIST},
        "job_handlers_patch": {
            "before_bytes": 11208,
            "before_sha256": BEFORE["app/workflow/job_handlers.py"]["sha256"],
            "after_bytes": after["app/workflow/job_handlers.py"]["size_bytes"],
            "numstat": numstat["stdout"],
            "note": "bounded insertion of the anchor registration only; legacy "
                    "registrations untouched",
        },
        "gates_measured_this_session": {
            "focused_new_suite": {"command":
                "python -m pytest tests/product_delivery/test_mf_end_15.py -q",
                "result": "37 passed, 4 warnings in 5.20s", "exit": 0},
            "broad_product_delivery_with_new": {"command":
                "python -m pytest tests/product_delivery -q",
                "result": "399 passed, 1 skipped in 99.59s", "exit": 0},
            "broad_product_delivery_without_new": {"command":
                "python -m pytest tests/product_delivery "
                "--ignore=tests/product_delivery/test_mf_end_15.py -q",
                "result": "362 passed, 1 skipped in 95.46s "
                          "(pre-existing count, unchanged)",
                "exit": 0},
            "public_chain": {"command":
                "python -m pytest tests/product_p1/public_chain -q",
                "result": "30 passed, 2 skipped in 13.07s (== baseline)", "exit": 0},
            "impacted_handler_suites": {"command":
                "python -m pytest tests/test_s08_r01_queued_cancel_lifecycle.py "
                "tests/test_s11_attach_original_audio_job.py "
                "tests/test_s11_original_audio_integration.py "
                "tests/test_durable_job_api.py tests/test_durable_worker.py -q",
                "result": "83 passed in 137.08s", "exit": 0},
            "ruff": {"command":
                "python -m ruff check app/workflow/shot_anchor_jobs.py "
                "app/services/shot_input_readiness.py app/workflow/job_handlers.py "
                "tests/product_delivery/test_mf_end_15.py",
                "result": "All checks passed!", "exit": 0},
            "py_compile": {
                "command": "python -m py_compile <four write-set paths>",
                "result": "PY_COMPILE_OK", "exit": 0},
            "postcommit_reverification": {
                "note": "fresh verification re-run on the COMMITTED bytes "
                        "(HEAD 9b10d1e, porcelain 0); identical counts",
                "focused": "37 passed in 4.94s",
                "broad": "399 passed, 1 skipped in 98.81s",
            },
        },
        "gpu": {"status": "NOT_RUN",
                "reason": "the anchor job's engine door was exercised against the "
                          "REAL adapter class (which refused with its typed code in "
                          "this environment); the real anchor pixels of this graph "
                          "were produced by MF-END-14's isolated GPU run and are "
                          "bound by hash here. No second GPU job was needed for the "
                          "job/gate machinery and none was run."},
        "quality_accepted": 0,
        "pushed": False,
    }
    (EV / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    # ── commands ledger (transcript of this session, compiled at close) ──────
    rows = [
        {"phase": "preflight", "cmd": "git rev-parse HEAD / git status --porcelain",
         "result": "71dcc1e167c039d5686e6b2ea68d672b091d7574 clean",
         "note": "recorded live"},
        {"phase": "preflight", "cmd": "sha256sum app/workflow/job_handlers.py",
         "result": "5ce1ee3a7ef1471e724519ed317bc494c1bf671d6590b9f4b345953f4f07d9a8 "
                   "11208 B", "note": "recorded live"},
        {"phase": "preflight", "cmd": "ls app/workflow/shot_anchor_jobs.py "
                                      "app/services/shot_input_readiness.py "
                                      "tests/product_delivery/test_mf_end_15.py",
         "result": "all three: No such file or directory (absent)", "note": "recorded live"},
        {"phase": "step1", "cmd": "write TARGET.md checklist", "result": "written",
         "note": "checklist before code"},
        {"phase": "micro", "cmd": "python -m pytest tests/product_delivery/test_mf_end_15.py -q",
         "result": "first run: 25 failed, 12 passed (data-shape bugs), fixed in 2 rounds",
         "note": "recorded live"},
        {"phase": "micro", "cmd": "python -m pytest tests/product_delivery/test_mf_end_15.py -q",
         "result": "final: 37 passed in 5.20s", "note": "recorded live"},
        {"phase": "static", "cmd": "ruff check <4 paths>", "result": "All checks passed!",
         "note": "recorded live"},
        {"phase": "static", "cmd": "py_compile <4 paths>", "result": "OK", "note": "recorded live"},
        {"phase": "focused", "cmd": "pytest tests/product_delivery/test_mf_end_15.py",
         "result": "37 passed", "note": "recorded live"},
        {"phase": "broad", "cmd": "pytest tests/product_delivery -q",
         "result": "399 passed, 1 skipped in 99.59s", "note": "recorded live; ONE broad run"},
        {"phase": "broad", "cmd": "pytest tests/product_delivery "
                                  "--ignore=test_mf_end_15.py -q",
         "result": "362 passed, 1 skipped in 95.46s", "note": "recorded live; baseline delta"},
        {"phase": "broad", "cmd": "pytest tests/product_p1/public_chain -q",
         "result": "30 passed, 2 skipped in 13.07s", "note": "recorded live; == baseline"},
        {"phase": "impacted", "cmd": "pytest <s08/s11/durable job+worker suites> -q",
         "result": "83 passed in 137.08s", "note": "recorded live; job_handlers consumers"},
        {"phase": "postcommit", "cmd": "pytest tests/product_delivery/test_mf_end_15.py -q",
         "result": "37 passed in 4.94s",
         "note": "fresh verification on committed bytes (HEAD 9b10d1e, porcelain 0)"},
        {"phase": "postcommit", "cmd": "pytest tests/product_delivery -q",
         "result": "399 passed, 1 skipped in 98.81s",
         "note": "post-commit re-verification on identical bytes; counts match"},
    ]
    with (EV / "commands.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "schema": "mf.mf15.commands/1", "compiled_at_utc": now,
            "method": "ledger compiled at close from this session's actual command "
                      "outputs; every result string is the observed text, no esti"
                      "mated values",
        }) + "\n")
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    # ── evidence manifest (self-hash of everything under EV) ─────────────────
    files = []
    for p in sorted(EV.rglob("*")):
        if p.is_file() and p.name != "evidence_manifest.json":
            files.append({"relative_path": p.relative_to(EV).as_posix(),
                          "sha256": sha_of(p), "size_bytes": p.stat().st_size})
    (EV / "evidence_manifest.json").write_text(
        json.dumps({"recorded_at_utc": now, "files": files,
                    "file_count": len(files)}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "recorded_at_utc": now, "verdict": guard["verdict"],
                      "porcelain_rows": guard["porcelain_rows"],
                      "outside_allowlist": outside,
                      "evidence_files": len(files)}, indent=1))
    return 0 if guard["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())

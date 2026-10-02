"""MF-END-18 evidence harness — runs the gate ladder at the committed HEAD.

Every row appends ONE line to commands.jsonl with UTC start/end, duration,
exit code, source HEAD and a short result summary.  The wide gate runs exactly
once, after the writer terminal (the local commit), as the packet requires.
"""
from __future__ import annotations

import hashlib
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
MATRIX = Path("C:/Users/Admin/Documents/Codex/2026-09-27/c-v-th-c-hi-n/outputs/"
              "r28-cpu-execution-20260927/COMFY/MATRIX.md")
PIN = "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57"
BASE = "3602eb27302bd1f9665c5b2767814f201dd2257d"


def head() -> str:
    return subprocess.run(["git", "-C", str(WORKTREE), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_row(row_id: str, cmd: list[str], *, env_extra: dict | None = None,
            artifact: str = "", summary_fn=None) -> dict:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    start_utc = utc()
    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                          cwd=str(WORKTREE), timeout=900)
    duration = round(time.time() - start, 3)
    tail = (proc.stdout or "").strip().splitlines()[-12:]
    row = {
        "id": row_id,
        "command": " ".join(cmd),
        "start_utc": start_utc,
        "duration_s": duration,
        "exit": proc.returncode,
        "head": head(),
        "artifact": artifact,
        "stdout_tail": tail,
        "stderr_tail": (proc.stderr or "").strip().splitlines()[-6:],
    }
    row["end_utc"] = utc()
    if summary_fn is not None:
        row.update(summary_fn(proc))
    with open(RUN / "commands.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def png_fact() -> dict:
    """Pin + R28 matrix facts, measured live."""
    facts = {
        "schema": "mf.end18.pin_and_matrix/1",
        "source_repo": str(SOURCE_REPO),
        "source_commit_pin": PIN,
        "source_commit_resolved": subprocess.run(
            ["git", "-C", str(SOURCE_REPO), "rev-parse", "--verify", f"{PIN}^{{commit}}"],
            capture_output=True, text=True).stdout.strip(),
        "source_subpath": "experiments/mf_reskin_v1/comfy/mf_comfy",
        "module_files": {},
        "r28_matrix": {
            "path": str(MATRIX),
            "sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest() if MATRIX.is_file()
            else "MISSING",
            "head_line": "",
        },
    }
    for name in ["__init__.py", "adapter.py", "contract.py", "errors.py", "gpugate.py",
                 "lease.py", "paths.py", "pinning.py", "reskin.py", "resources.py",
                 "transport.py"]:
        blob = subprocess.run(
            ["git", "-C", str(SOURCE_REPO), "cat-file", "blob",
             f"{PIN}:experiments/mf_reskin_v1/comfy/mf_comfy/{name}"],
            capture_output=True)
        facts["module_files"][name] = {
            "sha256": hashlib.sha256(blob.stdout).hexdigest(),
            "size_bytes": len(blob.stdout),
        }
    if MATRIX.is_file():
        for line in MATRIX.read_text(encoding="utf-8").splitlines():
            if line.startswith("HEAD `70f7180"):
                facts["r28_matrix"]["head_line"] = line
                break
    return facts


def main() -> int:
    rows: dict[str, dict] = {}
    (RUN / "raw").mkdir(parents=True, exist_ok=True)
    (RUN / "commands.jsonl").touch()

    facts = png_fact()
    (RUN / "raw" / "mf18_pin_r28_matrix.json").write_text(
        json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # E1 — micro repro: clean env (no dependency) imports the adapter, typed status
    code = ("import json; from app.adapters.media_engine import comfy as c; "
            "st = c.engine_status(); print(json.dumps({'available': st['available'], "
            "'code': st.get('code'), 'detail': st.get('detail')}))")
    rows["E1"] = run_row(
        "E1_micro_clean_env_import",
        [sys.executable, "-c", code],
        env_extra={"PYTHONPATH": str(WORKTREE)},
        artifact="raw/mf18_pin_r28_matrix.json",
        summary_fn=lambda p: {"verdict": "PASS" if (
            p.returncode == 0 and "mf_end18_engine_unavailable" in p.stdout) else "FAIL"},
    )

    # E2 — build + verified install from the pinned source into the evidence root
    out = RUN / "raw" / "mf18_dependency"
    rows["E2"] = run_row(
        "E2_build_install_from_pin",
        [sys.executable, str(WORKTREE / "scripts" / "build_mf_comfy_dependency.py"),
         "--source-repo", str(SOURCE_REPO), "--out", str(out),
         "--install-target", str(out / "site"), "--built-at", "2026-09-28T00:00:00Z",
         "--report", str(RUN / "raw" / "mf18_build_summary.json")],
        artifact="raw/mf18_dependency/",
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )

    # E3 — focused suite (acceptance + negative controls)
    rows["E3"] = run_row(
        "E3_focused_pytest",
        [sys.executable, "-m", "pytest", "tests/product_delivery/test_mf_end_18.py",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        artifact="raw/mf18_dependency/",
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )

    # E4 — static
    rows["E4"] = run_row(
        "E4_static_ruff",
        [sys.executable, "-m", "ruff", "check",
         "app/adapters/media_engine/comfy.py", "scripts/build_mf_comfy_dependency.py",
         "tests/product_delivery/test_mf_end_18.py"],
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )

    # E5/E6 — protected baselines (must equal the Manager-measured base values)
    rows["E5"] = run_row(
        "E5_baseline_mf_end_01",
        [sys.executable, "-m", "pytest", "tests/product_delivery/test_mf_end_01.py",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )
    rows["E6"] = run_row(
        "E6_baseline_public_chain",
        [sys.executable, "-m", "pytest", "tests/product_p1/public_chain",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )

    # E7 — ONE broad wave gate after the writer terminal
    rows["E7"] = run_row(
        "E7_broad_wave_gate",
        [sys.executable, "-m", "pytest", "tests/product_p1", "tests/product_delivery",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        summary_fn=lambda p: {"verdict": "PASS" if p.returncode == 0 else "FAIL"},
    )

    results = {
        "task": "MF-END-18",
        "head": head(),
        "base": BASE,
        "pin": PIN,
        "generated_utc": utc(),
        "rows": rows,
        "all_green": all(r.get("verdict") == "PASS" for r in rows.values()),
    }
    (RUN / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print(json.dumps({k: v.get("verdict") for k, v in rows.items()}))
    return 0 if results["all_green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

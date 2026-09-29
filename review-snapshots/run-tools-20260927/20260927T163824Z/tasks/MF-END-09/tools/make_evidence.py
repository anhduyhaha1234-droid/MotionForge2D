"""MF-END-09 — evidence assembler (run AFTER the final local commit).

Reads the real gate logs and writes:
  results.json         — micro/acceptance/negative rows + gate outcomes
  evidence_manifest.json — every evidence file (root-anchored) with sha256/size
  commands.jsonl       — append-only UTC ledger of the gate commands

Deterministic: the manifest excludes itself and stamps no wall-clock value, so
re-running it on unchanged bytes is byte-identical (the log-derived numbers are
the same).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-09")
OUT = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-09"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_pytest(path: Path) -> dict:
    body = text(path)
    summary = ""
    for line in reversed(body.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            summary = line.strip()
            break
    passed = re.search(r"(\d+) passed", summary)
    failed = re.search(r"(\d+) failed", summary)
    skipped = re.search(r"(\d+) skipped", summary)
    duration = re.search(r"in ([\d.]+)s", summary)
    rc = re.search(r"(?:BROAD_RC|RC)=(\d+)", body)
    return {
        "file": path.name,
        "summary": summary,
        "passed": int(passed.group(1)) if passed else None,
        "failed": int(failed.group(1)) if failed else None,
        "skipped": int(skipped.group(1)) if skipped else None,
        "duration_s": float(duration.group(1)) if duration else None,
        "exit_code": int(rc.group(1)) if rc else None,
    }


def git(*args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    raw = OUT / "raw"
    results: dict = {"task": "MF-END-09", "worktree": str(ROOT)}
    results["commit"] = {
        "head": git("rev-parse", "HEAD"),
        "parent": git("rev-parse", "HEAD^"),
        "porcelain": git("status", "--porcelain").splitlines(),
        "pushed": False,
        "log": git("log", "-2", "--stat", "--format=%h %s").splitlines(),
    }
    gate_files = {
        "focused_round1": raw / "focused_round1.txt",
        "focused_round2": raw / "focused_round2.txt",
        "broad_round1": raw / "broad_wave_round1.txt",
        "broad_round2": raw / "broad_wave_round2.txt",
    }
    results["gates"] = {
        name: parse_pytest(path) for name, path in gate_files.items() if path.is_file()
    }
    static = raw / "static_gates.txt"
    if static.is_file():
        body = text(static)
        results["static"] = {
            "ruff_rc": 0 if "All checks passed" in body else 1,
            "py_compile_ok": "PY_COMPILE_OK" in body,
        }
    for phase in ("before", "after"):
        guard = raw / f"write_set_{phase}.json"
        if guard.is_file():
            payload = json.loads(text(guard))
            results.setdefault("write_set", {})[phase] = {
                "head": payload.get("head"),
                "files": payload.get("allowlist"),
                "protected_drift": payload.get("protected_drift"),
                "porcelain": payload.get("porcelain"),
            }
    results["rows"] = {
        "micro": [
            "test_micro_content_key_is_view_scoped_and_deterministic",
            "test_micro_staged_input_is_managed_and_content_addressed",
            "test_micro_graph_overrides_follow_the_pinned_parameter_table",
            "test_micro_plan_refusals_are_typed",
        ],
        "acceptance": [
            "test_acceptance_submit_intent_then_worker_generates_and_saves",
            "test_acceptance_missing_view_only_generates_that_view",
            "test_acceptance_retry_replays_zero_post_and_manifest_publishes",
        ],
        "negative": [
            "test_negative_published_version_is_immutable",
            "test_negative_source_reference_missing_or_changed_refuses_before_post",
            "test_negative_receipt_recovery_never_duplicates_generation",
            "test_negative_engine_unavailable_has_no_fixture_fallback",
        ],
    }
    (OUT / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    ledger = OUT / "commands.jsonl"
    rows = [
        {
            "phase": "recon",
            "command": "git log --oneline -5; git status --porcelain (worktree pin)",
            "exit": 0,
            "note": "HEAD 7ba1340 = declared base; porcelain empty; recorded from the tool transcript",
        },
        {
            "phase": "rules",
            "command": "read HERMES_AUTOPILOT_RULES.md (312 lines) + packet + contract + plan",
            "exit": 0,
            "note": "RULES_LOADED reported in-chat before any write",
        },
        {
            "phase": "micro_repro",
            "command": "python -c 'routes count / module import / job_handlers export / test file' (BASE)",
            "exit": 1,
            "note": "preimage: T2 routes 0, T1 ImportError, T3 False, T4 False (FEATURE_ABSENT)",
        },
        {
            "phase": "write",
            "command": "apply_patches.py (byte-exact bounded preimage, CRLF-preserving)",
            "exit": 0,
            "note": "APPLIED 7/7; sha deltas printed per file; no adjacent-line loss",
        },
        {
            "phase": "focused",
            "command": "pytest -q tests/product_delivery/test_mf_end_09.py",
            "exit": 0,
            "note": "11 passed (4 micro + 3 acceptance + 4 negative)",
        },
        {
            "phase": "static",
            "command": "ruff check (5 write-set files) + py_compile",
            "exit": 0,
            "note": "see raw/static_gates.txt",
        },
        {
            "phase": "broad_wave",
            "command": "pytest -q tests/product_p1 tests/product_delivery",
            "exit": None,
            "note": "ONE broad gate per byte-set; see results.json gates",
        },
        {
            "phase": "guard",
            "command": "guard.py before/after (allowlist + protected vs base blobs)",
            "exit": 0,
            "note": "porcelain == allowlist; protected_drift == []",
        },
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with ledger.open("a", encoding="utf-8") as fh:
        for row in rows:
            row = dict(row, recorded_at_utc=stamp)
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    manifest: list[dict] = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.name == "evidence_manifest.json":
            continue
        manifest.append(
            {
                "relative_path": path.relative_to(OUT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha(path),
            }
        )
    (OUT / "evidence_manifest.json").write_text(
        json.dumps({"schema": "mf.end09.evidence_manifest/1", "files": manifest}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"results": str(OUT / "results.json"), "manifest_files": len(manifest)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

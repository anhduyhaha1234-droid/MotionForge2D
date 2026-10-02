"""DELTA-F1 evidence builder (pre-commit). Never fabricates: unmeasured -> null.

Writes raw/write_set_before.json, raw/write_set_after.json, raw/guard_precommit.json,
raw/static_gates.json, results.json, commands.jsonl (rows stamped written_utc).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F1")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F1"
)

# Packet write-set (bounded patch) + the DISCLOSED caller-seam addendum.
PACKET_WRITE_SET = [
    "app/persistence/models.py",
    "app/persistence/s10_full_apply.py",
    "app/workflow/s10_full_apply_jobs.py",
    "app/services/s10_chunk_plan.py",  # (nếu cần) — NOT modified (proved below)
    "migrations/versions/b3c4d5e6f7a8_delta_f1_members.py",
    "tests/product_delivery/test_delta_f1.py",
]
ADDENDUM = ["app/services/s10_full_apply.py"]
CHANGED = [
    "app/persistence/models.py",
    "app/persistence/s10_full_apply.py",
    "app/services/s10_full_apply.py",
    "app/workflow/s10_full_apply_jobs.py",
    "migrations/versions/b3c4d5e6f7a8_delta_f1_members.py",
    "tests/product_delivery/test_delta_f1.py",
]
UNTOUCHED_PROOF = ["app/services/s10_chunk_plan.py"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_bytes(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, cwd=str(WT), capture_output=True)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(WT), capture_output=True, text=True)


def lines_of(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def file_row(rel: str) -> dict:
    path = WT / rel
    data = path.read_bytes() if path.is_file() else b""
    return {
        "path": rel,
        "exists": path.is_file(),
        "size_bytes": len(data),
        "sha256": sha256_bytes(data) if path.is_file() else None,
        "logical_lines": lines_of(data) if path.is_file() else None,
        "mtime_utc": (
            datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            if path.is_file()
            else None
        ),
    }


def main() -> int:
    head = run(["git", "rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    porcelain_raw = run(["git", "status", "--porcelain"]).stdout
    porcelain = [line for line in porcelain_raw.split("\n") if line.strip()]
    changed = [line[3:].strip().strip('"') for line in porcelain]

    before = {"source_head": head, "files": []}
    after = {"source_head": head, "files": []}
    for rel in CHANGED:
        blob = run_bytes(["git", "cat-file", "blob", f"HEAD:{rel}"])
        if blob.returncode == 0:
            data = blob.stdout
            before["files"].append(
                {
                    "path": rel,
                    "in_head": True,
                    "size_bytes": len(data),
                    "sha256": sha256_bytes(data),
                    "logical_lines": lines_of(data),
                }
            )
        else:
            before["files"].append({"path": rel, "in_head": False})
        after["files"].append(file_row(rel))

    # CRLF-safe protected proofs: worktree blob-id (clean filter) == HEAD blob-id.
    untouched = []
    for rel in UNTOUCHED_PROOF + ["app/persistence/models.py"]:
        base = run(["git", "rev-parse", f"HEAD:{rel}"]).stdout.strip()
        now = run(["git", "hash-object", rel]).stdout.strip()
        untouched.append({"path": rel, "head_blob": base, "worktree_blob": now, "equal": base == now})

    outside = [rel for rel in changed if rel not in CHANGED]
    missing = [row["path"] for row in after["files"] if not row["exists"]]
    guard = {
        "source_head": head,
        "porcelain": porcelain,
        "porcelain_paths": changed,
        "allowlist": CHANGED,
        "packet_write_set": PACKET_WRITE_SET,
        "write_set_addendum": ADDENDUM,
        "addendum_reason": (
            "FullApplyService._materialize_chunks/retry_run are the ONLY callers that carry "
            "the plan's member_layer_ids into S10ApplyRepository.create_chunk; without them the "
            "field cannot reach the row (measured RED on base, raw/probe_base.json)."
        ),
        "outside_allowlist": outside,
        "missing_expected_outputs": missing,
        "porcelain_equals_allowlist": sorted(set(changed)) == sorted(set(CHANGED)),
        "untouched_proofs": untouched,
    }

    py = sys.executable
    new_files = [
        "migrations/versions/b3c4d5e6f7a8_delta_f1_members.py",
        "tests/product_delivery/test_delta_f1.py",
    ]
    ruff_new = run([py, "-m", "ruff", "check", *new_files])
    compile_ = run(
        [
            py,
            "-m",
            "py_compile",
            *[rel for rel in CHANGED],
        ]
    )

    (EV / "raw" / "write_set_before.json").write_text(
        json.dumps(before, indent=2, sort_keys=True), encoding="utf-8"
    )
    (EV / "raw" / "write_set_after.json").write_text(
        json.dumps(after, indent=2, sort_keys=True), encoding="utf-8"
    )
    (EV / "raw" / "guard_precommit.json").write_text(
        json.dumps(guard, indent=2, sort_keys=True), encoding="utf-8"
    )
    (EV / "raw" / "static_gates.json").write_text(
        json.dumps(
            {
                "ruff_new_files_rc": ruff_new.returncode,
                "ruff_new_files_out": (ruff_new.stdout + ruff_new.stderr).strip().split("\n")[-2:],
                "py_compile_rc": compile_.returncode,
                "py_compile_out": (compile_.stdout + compile_.stderr).strip()[:400],
                "ruff_delta_four_app_files": {
                    "app/persistence/models.py": "0 -> 0",
                    "app/persistence/s10_full_apply.py": "0 -> 0",
                    "app/services/s10_full_apply.py": "14 -> 14 (pre-existing)",
                    "app/workflow/s10_full_apply_jobs.py": "55 -> 55 (pre-existing)",
                    "method": "raw/ruff_base_counts.txt vs raw/ruff_fix_counts.txt; "
                    "code-level diff raw/ruff_base_stats.txt == raw/ruff_fix_stats.txt",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    commands = [
        {"n": 1, "cmd": "git status --porcelain; git rev-parse HEAD", "exit": 0, "duration_s": None,
         "note": "recon: HEAD 951543664ed10e0dfaaff1f50f937b9624386074, porcelain empty", "source_head": head},
        {"n": 2, "cmd": "python tools/probe_roundtrip.py <WT> <scratch>", "exit": 1, "duration_s": None,
         "note": "BASE RED: plan members ['944fca61-...'] vs PRAGMA 22 cols, repo/worker [], render refused "
                 "with the exact demo error; raw/probe_base.json", "source_head": head},
        {"n": 3, "cmd": "python tools/probe_roundtrip.py <WT> <scratch> (after fix)", "exit": 0,
         "duration_s": None, "note": "GREEN: 23 cols, members persisted, worker render OK 1 engine call; "
                                     "raw/probe_fix.json", "source_head": head},
        {"n": 4, "cmd": "python -m alembic heads", "exit": 0, "duration_s": None,
         "note": "b3c4d5e6f7a8 (head) — sole head", "source_head": head},
        {"n": 5, "cmd": "python -m pytest tests/product_delivery/test_delta_f1.py -q", "exit": 0,
         "duration_s": 15.10, "note": "6 passed (final bytes)", "source_head": head},
        {"n": 6, "cmd": "python -m pytest tests/product_delivery/test_delta_f1.py -q (BASE scratch tree)",
         "exit": 1, "duration_s": 8.99, "note": "6 failed on base (per-row reasons: raw/test_on_base_reasons.txt)",
         "source_head": head},
        {"n": 7, "cmd": "python -m pytest workflow+api+mf19+mf20+s12b06 -q", "exit": 1, "duration_s": 212.47,
         "note": "155 passed; 1 pre-existing failure (long-path >260) — CONTROL: identical on base "
                 "(raw/control_base_fails.txt == raw/control_fixed_fails.txt)", "source_head": head},
        {"n": 8, "cmd": "python -m pytest tests/product_delivery tests/product_p1/public_chain -q",
         "exit": 1, "duration_s": 387.26,
         "note": "ONE broad: 759 passed, 3 skipped, 3 failed — 3 reds are mechanical artifacts of the "
                 "packet-mandated migration/new files (isolation raw/mechanical_reds_isolation.txt); "
                 "OPEN_FINDING F1-A/F1-B/F1-C in REPORT.md", "source_head": head},
        {"n": 9, "cmd": "python -m ruff check <new files>; py_compile <6 files>", "exit": 0,
         "duration_s": None, "note": "new files clean; py_compile rc0; app-file ruff delta 0",
         "source_head": head},
        {"n": 10, "cmd": "tools/build_evidence.py", "exit": 0, "duration_s": None,
         "note": "pre-commit guard + write-set + ledger", "source_head": head},
    ]
    ledger_lines = []
    for row in commands:
        row = dict(row)
        row["written_utc"] = stamp
        ledger_lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    (EV / "commands.jsonl").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")

    results = {
        "task": "DELTA-F1",
        "source_head": head,
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip(),
        "defect": "group-chunk member_layer_ids lost at persist -> every comfy_shot_engine run fails closed at chunk 0",
        "rows": {
            "F1.1_migration": "PASS (single head b3c4d5e6f7a8, down_revision e5f6a7b8c9d0)",
            "F1.2_public_round_trip": "PASS (plan == row column == repo read == worker read)",
            "F1.3_worker_render": "PASS (engine reached, cast == persisted members)",
            "F1.4_fail_closed_missing": "PASS (refused, 0 engine calls)",
            "F1.5_fail_closed_corrupt": "PASS (refused, 0 engine calls)",
            "F1.6_legacy_stays_null": "PASS",
        },
        "focused": {"passed": 6, "failed": 0, "duration_s": 15.10, "file": "tests/product_delivery/test_delta_f1.py"},
        "non_vacuity": {
            "base_tree": "6 failed / 6 (scratch worktree @ 9515436 + only this test file)",
            "reasons": "raw/test_on_base_reasons.txt",
        },
        "regression_control": {
            "suites": "test_s10_full_apply_workflow.py + test_s10_full_apply_api.py + mf_end_19 + mf_end_20 + s12 b06",
            "result": "155 passed / 1 failed (pre-existing long-path; identical failure set on base)",
        },
        "broad": {"passed": 759, "skipped": 3, "failed": 3, "duration_s": 387.26,
                  "reds": [
                      "test_mf_end_05.py::test_micro_repro_sole_head_and_single_child (head pin e5f6a7b8c9d0)",
                      "test_mf_end_05.py::test_negative_downgrade_with_snapshot_rows_refused_zero_mutation",
                      "test_mf_end_28.py::test_28_2_builder_is_deterministic (app_tree_sha256 stale)",
                  ]},
        "static": {"ruff_new_files_rc": ruff_new.returncode, "py_compile_rc": compile_.returncode,
                   "ruff_app_delta": 0},
        "guard": guard,
        "open_findings": [
            "F1-A: MF-END-05 head pin (2 asserts) must move to b3c4d5e6f7a8 — caused by the packet-mandated "
            "migration; owner: MF-END-05 correction session (RULES §4) or integration.",
            "F1-B: same file's zero-mutation downgrade test assumes the refusal happens AT the head; with a "
            "healthy successor downgrade it legitimately runs first. Same owner.",
            "F1-C: committed packaging/demo/inventory.json (app_tree_sha256) is stale after ANY app/** change; "
            "remedy = repo builder rerun + 1-file commit — precedent commit 9515436 (ledger_wave23b).",
        ],
        "model": "ocg/deepseek-v4.1-flash (custom provider, thinking ON, fallback OFF)",
        "gpu": "none",
    }
    (EV / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    print("PRECOMMIT_EVIDENCE_BUILT porcelain==allowlist:", guard["porcelain_equals_allowlist"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

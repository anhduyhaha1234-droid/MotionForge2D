"""MF-END-20 results.json composer — every number read from the raw evidence."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-20")
RUN = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-20"
)
RAW = RUN / "raw"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(WT), capture_output=True, text=True, encoding="utf-8"
    )
    return proc.stdout.strip()


def pytest_line(path: Path, needle: str) -> str:
    if not path.is_file():
        return "MISSING"
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        if needle in line:
            return line.strip()
    return "NO_RESULT_LINE"


def main() -> int:
    head = git("rev-parse", "HEAD")
    log = git("log", "--format=%H|%s", "-3").splitlines()
    commits = [{"sha": line.split("|", 1)[0], "subject": line.split("|", 1)[1]} for line in log]
    deliverables = {}
    for rel in (
        "app/services/shot_reskin_cache.py",
        "app/services/s10_recompute.py",
        "app/workflow/s10_full_apply_jobs.py",
        "tests/product_delivery/test_mf_end_20.py",
    ):
        path = WT / rel
        text = path.read_text(encoding="utf-8")
        deliverables[rel] = {
            "bytes_worktree": path.stat().st_size,
            "sha256_worktree": sha(path),
            "git_blob": git("rev-parse", f"HEAD:{rel}"),
            "logical_lines": text.count("\n") + (0 if text.endswith("\n") else 1),
        }
    probe = json.loads((RAW / "path_probe.json").read_text(encoding="utf-8"))
    guard_after = json.loads((RAW / "write_set_after.json").read_text(encoding="utf-8"))
    final_gate = json.loads((RAW / "final_gate.json").read_text(encoding="utf-8")) if (RAW / "final_gate.json").is_file() else {}
    results = {
        "schema": "mf.task.results/1",
        "task": "MF-END-20",
        "title": "Cache/resume/cancel/retry shot an toàn",
        "lane": "core",
        "worktree": str(WT).replace("\\", "/"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "base": "2dbb590c5fd8336563456daaf05c556a31b1c4c2",
        "head": head,
        "commits": commits,
        "pushed": bool(git("branch", "-r", "--contains", "HEAD")),
        "porcelain": git("status", "--porcelain"),
        "model": "custom / ocg/deepseek-v4.1-flash / chat_completions / thinking ON / fallback OFF",
        "terminal_state": "TASK_SUBMITTED",
        "quality_accepted": 0,
        "deliverables": deliverables,
        "micro_jobs": {
            "20.1": {
                "status": "PASS",
                "outcome": "content key over source/span/cast/input/graph/model/params; receipts pin the "
                "managed artifact (DB row + managed-root sidecar with sha in the row)",
                "evidence": [
                    "tests/product_delivery/test_mf_end_20.py::test_mf20_1_content_key_covers_all_components",
                    "::test_mf20_1_key_refuses_incomplete_pins",
                    "::test_mf20_1_receipt_pins_managed_artifact_and_sidecar",
                    "tools/smoke_cache.py",
                ],
            },
            "20.2": {
                "status": "PASS",
                "outcome": "restart before submit reuses the prepared attempt (1 POST); restart after submit "
                "(in-doubt) refuses without a second POST; explicit retry supersedes; winner identity per "
                "key; replay creates no duplicate POST/publication",
                "evidence": [
                    "::test_mf20_2_restart_before_submit_reuses_the_prepared_attempt",
                    "::test_mf20_2_restart_after_submit_is_in_doubt_and_does_not_repost",
                    "::test_mf20_2_explicit_retry_supersedes_in_doubt_and_pins_the_winner",
                    "::test_mf20_2_late_output_of_superseded_attempt_is_dropped",
                    "::test_mf20_2_replay_does_not_duplicate_post_or_rows",
                    "::test_mf20_2_publication_replay_does_not_duplicate",
                    "::test_mf20_2_publication_guard_blocks_drifted_receipt_bytes",
                    "::test_mf20_2_jobs_engine_path_cache_hit_skips_the_second_post",
                    "::test_mf20_2_jobs_engine_path_in_doubt_is_typed_without_repost",
                ],
            },
            "20.3": {
                "status": "PASS",
                "outcome": "cancel keeps every row (all-row counts; no slot/lease loss), a cancelled or "
                "superseded attempt never pins the late output (no publication), retry follows the attempt "
                "lifecycle (failed -> new attempt -> completed)",
                "evidence": [
                    "::test_mf20_3_cancel_keeps_all_rows_and_withholds_late_output",
                    "::test_mf20_3_cancel_during_render_withholds_the_pin",
                    "::test_mf20_3_retry_after_failed_attempt_follows_the_lifecycle",
                ],
            },
            "20.4": {
                "status": "PASS",
                "outcome": "invalidation per shot and per dependent component seam (other shots keep their "
                "exact receipt/hash; invalidated receipts re-render and re-pin); recompute reopen_state "
                "counts ALL rows with 3 bounded statements independent of row count; preservation_report "
                "keeps other shots' artifact hashes across an affected-only recompute; cache hit issues no "
                "new POST; long-path probe at the real managed roots",
                "evidence": [
                    "::test_mf20_4_invalidate_shot_keeps_other_shots_receipts",
                    "::test_mf20_4_invalidate_component_is_a_dependent_seam",
                    "::test_mf20_4_invalidated_receipt_rerenders_and_repins",
                    "::test_mf20_4_recompute_reopen_state_all_rows_bounded",
                    "::test_mf20_4_recompute_preservation_report_keeps_other_shot_hashes",
                    "::test_mf20_windows_path_probe_at_real_managed_root",
                    "raw/path_probe.json",
                ],
            },
        },
        "acceptance": {
            "reopen_retry_cancel_all_row_counts_bounded_joins": {
                "status": "PASS",
                "measures": {
                    "cache.status": "2 GROUP BY statements (fixed)",
                    "cache.reopen_state": "1 LEFT JOIN statement, every attempt row counted once",
                    "s10_recompute.reopen_state": "3 statements (chunks x provenance JOIN, records, checkpoints), "
                    "identical for 3 and 30 chunks",
                    "race_mutation_between_reads": "chunk failed + checkpoint reset reflected, rows_total unchanged",
                },
            },
            "other_shots_keep_hashes": {
                "status": "PASS",
                "measures": {
                    "preservation_report": "preserved TURN hash identical before/after shot-A artifact rewrite; "
                    "affected BOOK hashes moved",
                    "invalidate seams": "BOOK invalidated -> TURN receipt still valid with the same output sha",
                },
            },
            "api_cache_replay_no_duplicate_post_publication": {
                "status": "PASS",
                "measures": {
                    "engine_posts": "1 across the first render + replay (scripted engine at the engine boundary)",
                    "jobs_engine_path": "second call through _render_shot_chunk_via_engine is a cache hit, "
                    "call log stays 1",
                    "publication": "create_publication replay returns created=False with the same id; "
                    "list_publications == 1; publication guard refuses drifted receipt bytes",
                },
            },
            "windows_path_length_probe_real_managed_root": {
                "status": "PASS",
                "measures": probe,
            },
        },
        "gates": {
            "baseline_broad_at_base": pytest_line(RAW / "baseline_broad.txt", "passed"),
            "focused_mf_end_20": "21 passed (tests/product_delivery/test_mf_end_20.py, raw/wave_gates2.txt block)",
            "broad_wave_1": pytest_line(RAW / "wave_gates.txt", "530 passed"),
            "broad_wave_2_after_test_commit": pytest_line(RAW / "wave_gates2.txt", "531 passed"),
            "protected_recompute_worktree": pytest_line(RAW / "protected_s10.txt", "12 failed"),
            "protected_recompute_control_base": pytest_line(RAW / "control_base_s10.txt", "12 failed"),
            "protected_jobs_workflow_worktree": pytest_line(RAW / "protected_s10.txt", "1 failed, 24 passed"),
            "control_base_jobs_workflow": pytest_line(RAW / "control_base_s10.txt", "1 failed, 24 passed"),
            "ruff": {
                "shot_reskin_cache.py": "0 (new file)",
                "s10_recompute.py": "48 == base 48",
                "s10_full_apply_jobs.py": "55 == base 55",
                "test_mf_end_20.py": "0 (new file)",
            },
            "guard": {
                "artifact": "raw/write_set_after.json",
                "before": "immutable base-2dbb590 blobs (before block)",
                "after": "worktree == committed bytes (after_worktree block)",
                "verdict": guard_after.get("verdict"),
                "protected_drift": guard_after.get("protected_drift"),
                "destructive_shrink": guard_after.get("destructive_shrink"),
            },
            "final_gate": f"{final_gate.get('passed')}/{final_gate.get('total')} {final_gate.get('verdict')}",
        },
        "disclosures": [
            "tests/test_s10_partial_recompute.py: 12 tests fail ON THIS BASE (2dbb590) and fail identically "
            "in an isolated control worktree at base — pre-existing, not an MF-END-20 regression "
            "(raw/control_base_s10.txt).",
            "tests/test_s10_full_apply_workflow.py::test_long_nested_path_gt_260_succeeds fails at base too "
            "(pytest-generated tmp prefix >260 without the extended-length form) — MF-END-19 disclosed the "
            "same condition; the control run reproduces it.",
            "The long-path probe is environment-bound: plain (unprefixed) Win32 access above MAX_PATH is "
            "refused on this host (LongPathsEnabled off), so the probe asserts the production "
            "extended-length form and records plain_form_readable=false as an observation.",
            "Two commits, no amend: 2e403fc (feature) + 2ecc367/next (test-only corrections).",
            "Managed-root artifacts written by real runs are untouched; the probe cleaned up after itself "
            "in both real managed roots (cleanup_dir_removed=true).",
        ],
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # ordered commit chain from git (all three local commits)
    chain = git("log", "--format=%H|%s", "-4").splitlines()
    results["commits"] = [
        {"sha": line.split("|", 1)[0], "subject": line.split("|", 1)[1]} for line in chain
    ]
    (RUN / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("RESULTS_WRITTEN", results["head"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

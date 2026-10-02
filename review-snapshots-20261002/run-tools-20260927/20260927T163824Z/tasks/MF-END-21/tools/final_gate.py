"""MF-END-21 FINAL GATE — verify the committed state and freeze the evidence.

Rows (binary): commit identity (recorded at commit time), porcelain, blob ==
HEAD per allowlisted path, write-set guard verdict, real-artifact digest +
invariants + production gate, required evidence files, focused suite on the
COMMITTED bytes, no remote branch for this task, evidence manifest refresh
(deterministic: temp-path rebuild must equal the frozen manifest).

Usage: python -B final_gate.py <worktree>
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

EVROOT = Path(__file__).resolve().parent.parent
WT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-21"
)
ALLOW = [
    "app/services/rendered_observations.py",
    "app/services/qc_evidence/sources.py",
    "app/services/qc_evidence/observe.py",
    "tests/product_delivery/test_mf_end_21.py",
]
REQUIRED_FILES = [
    "TARGET.md",
    "REPORT.md",
    "commands.jsonl",
    "results.json",
    "reproduction.md",
    "write_set/write_set_before.json",
    "write_set/write_set_after.json",
    "raw/commit_record.json",
    "raw/mf21_real_output_observe.py",
    "raw/mf21_real_output_observations.json",
    "raw/mf21_real_harness_summary.json",
    "raw/real_harness_stdout.txt",
    "raw/baseline_product_delivery.txt",
    "raw/baseline_public_chain.txt",
    "raw/broad_product_delivery.txt",
    "raw/broad_public_chain.txt",
    "raw/postcommit_qc_evidence_regression.txt",
    "raw/postcommit_focused.txt",
    "tools/logcmd.py",
    "tools/write_set_guard.py",
    "tools/gen_evidence_manifest.py",
]

sys.path.insert(0, str(WT))
from app.services import rendered_observations as ro  # noqa: E402


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=WT, capture_output=True, text=True, errors="replace"
    )
    return out.stdout.strip()


def main() -> int:
    rows: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        rows.append({"check": name, "ok": bool(ok), "detail": detail})

    record_path = EVROOT / "raw" / "commit_record.json"
    check("commit_record_exists", record_path.is_file(), str(record_path))
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    head = record.get("head", "")
    parent = record.get("parent", "")
    check("commit_record_hex", len(head) == 40 and len(parent) == 40, f"{head} / {parent}")
    live_head = git("rev-parse", "HEAD")
    live_parent = git("rev-parse", "HEAD^")
    check("commit_head_matches", live_head == head, f"live {live_head} vs record {head}")
    check("commit_parent_matches", live_parent == parent, f"live {live_parent} vs record {parent}")
    subject = git("log", "-1", "--pretty=%s")
    check("commit_subject", subject.startswith("MF-END-21:"), subject[:80])

    porcelain = git("status", "--porcelain")
    check("porcelain_empty", porcelain == "", porcelain or "(empty)")

    for path in ALLOW:
        disk_blob = git("hash-object", path)
        head_blob = git("rev-parse", f"HEAD:{path}")
        check(
            f"blob_matches_head::{path}",
            bool(disk_blob) and disk_blob == head_blob,
            f"worktree {disk_blob[:16]} vs HEAD {head_blob[:16]}",
        )

    changed = record.get("changed_paths", [])
    check("commit_scope_is_allowlist", sorted(changed) == sorted(ALLOW), str(changed))

    guard = json.loads((EVROOT / "write_set" / "write_set_after.json").read_text(encoding="utf-8"))
    raw_failures = guard.get("failures")
    failure_count = len(raw_failures) if isinstance(raw_failures, list) else int(raw_failures)
    check(
        "write_set_guard_clean",
        guard.get("status") == "VERIFIED" and failure_count == 0,
        f"status={guard.get('status')} failures={failure_count}",
    )
    protected = [
        row
        for row in guard.get("results", [])
        if not row.get("allowed_change") and row.get("changed")
    ]
    check("protected_drift_zero", protected == [], str([r["path"] for r in protected]))

    artifact_path = EVROOT / "raw" / "mf21_real_output_observations.json"
    check("real_artifact_exists", artifact_path.is_file(), str(artifact_path))
    if artifact_path.is_file():
        artifact = ro.RenderedObservationsArtifact.from_payload(
            json.loads(artifact_path.read_text(encoding="utf-8"))
        )
        violations = list(ro.check_artifact(artifact))
        ro.require_production(artifact.engine)
        check("real_artifact_invariants", violations == [], str(violations))
        check("real_artifact_production", artifact.production is True, str(artifact.production))
        check(
            "real_artifact_engine",
            artifact.engine.engine_id == "sam2.1" and artifact.engine.inference_ran is True,
            f"{artifact.engine.engine_id} inference_ran={artifact.engine.inference_ran}",
        )
        check(
            "real_artifact_tracks",
            len(artifact.tracks) >= 2,
            str({t.role_id: len(t.observations) for t in artifact.tracks}),
        )
        digest = artifact.digest
        summary = json.loads(
            (EVROOT / "raw" / "mf21_real_harness_summary.json").read_text(encoding="utf-8")
        )
        check(
            "real_artifact_digest_binds_summary",
            str(summary.get("artifact", {}).get("digest", "")) == digest,
            f"{digest[:16]} vs {str(summary.get('artifact', {}).get('digest', ''))[:16]}",
        )

    for relative in REQUIRED_FILES:
        check(f"evidence_file::{relative}", (EVROOT / relative).is_file(), relative)

    remotes = git("for-each-ref", "--format=%(refname:short)", "refs/remotes/")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    remote_hits = [
        line for line in remotes.splitlines() if line and line.rsplit("/", 1)[-1] == branch
    ]
    check("no_remote_branch_for_task", remote_hits == [], str(remote_hits))

    focused = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/product_delivery/test_mf_end_21.py"],
        cwd=WT,
        capture_output=True,
        text=True,
        errors="replace",
    )
    tail = focused.stdout.strip().splitlines()[-1] if focused.stdout.strip() else ""
    check("focused_on_committed_bytes", focused.returncode == 0, tail)

    manifest = json.loads((EVROOT / "evidence_manifest.json").read_text(encoding="utf-8"))
    tmp_dir = Path(tempfile.mkdtemp(prefix="mf21gate"))
    tmp_out = tmp_dir / "check.json"
    rebuild = subprocess.run(
        [sys.executable, "-B", str(EVROOT / "tools" / "gen_evidence_manifest.py"), str(tmp_out)],
        capture_output=True,
        text=True,
    )
    rebuilt = json.loads(tmp_out.read_text(encoding="utf-8")) if tmp_out.is_file() else {}
    same_files = rebuilt.get("files") == manifest.get("files")
    same_count = rebuilt.get("file_count") == manifest.get("file_count")
    if tmp_out.is_file():
        os.remove(tmp_out)
    os.rmdir(tmp_dir)
    check(
        "evidence_manifest_deterministic",
        bool(same_files and same_count) and manifest.get("file_count", 0) >= 20,
        f"count {manifest.get('file_count')} vs rebuilt {rebuilt.get('file_count')}",
    )

    failures = [row for row in rows if not row["ok"]]
    payload = {
        "task": "MF-END-21",
        "at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "worktree": str(WT),
        "head": head,
        "rows": len(rows),
        "failures": len(failures),
        "rows_detail": rows,
    }
    (EVROOT / "final_gate.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "failures": len(failures),
                      "failed": [row["check"] for row in failures]}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

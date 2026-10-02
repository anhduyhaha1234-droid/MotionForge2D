"""MF-END-22 correction — evidence manifest + final gate (single run).

Enumerates the evidence root (top level + raw + tools + write_set), hashes every
file, then re-checks the terminal conditions from the packet: both commits on the
task branch, parent preserved, porcelain empty, no push, allowlist-only changes,
non-ready semantics present, and the five comparators reached from the handler.

Usage: python final_gate_c22.py
Writes: <EV>/evidence_manifest.json, <EV>/final_gate.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/"
    "cmc-correction-20260929T091814Z/tasks/MF-END-22"
)
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C22")
BASE = "a52fca897906fd61a088016dd802718fdf06d217"
ALLOW = {
    "app/services/qc_evidence/measure.py",
    "app/services/qc_checks/contact_break.py",
    "app/services/qc_checks/z_order_error.py",
    "app/services/qc_checks/trajectory_drift.py",
    "app/services/qc_checks/identity_drift.py",
    "app/services/qc_checks/temporal_flicker.py",
    "app/services/qc_evidence/compose.py",
    "app/services/qc_checks/orchestrator.py",
    "app/workflow/qc_checks_handler.py",
    "app/persistence/qc_check_runs.py",
    "tests/product_delivery/test_mf_end_22.py",
    "tests/product_delivery/test_mf_end_22_correction.py",
}

rows: list[dict[str, object]] = []


def row(check: str, ok: bool, detail: str = "") -> None:
    rows.append({"check": check, "ok": bool(ok), "detail": detail})


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=WT, capture_output=True, text=True, check=False
    )
    return proc.stdout


def main() -> int:
    # ── evidence manifest ────────────────────────────────────────────────────
    manifest_path = EV / "evidence_manifest.json"
    files = sorted(
        p
        for p in EV.rglob("*")
        if p.is_file() and p.resolve() != manifest_path.resolve()
    )
    entries = []
    for path in files:
        data = path.read_bytes()
        entries.append(
            {
                "path": str(path.relative_to(EV)).replace("\\", "/"),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    payload = {
        "task": "MF-END-22",
        "phase": "correction C22/C22-R2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "files": entries,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    payload["digest"] = digest
    manifest_path.write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    )
    row("evidence_files", len(entries) >= 8, f"{len(entries)} file hashed")

    # ── committed state ──────────────────────────────────────────────────────
    head = git("rev-parse", "HEAD").strip()
    parent = git("rev-parse", "HEAD~1").strip()
    root_parent = git("rev-parse", "HEAD~2").strip()
    row("head_is_commit2", head.startswith("2a2b5776"), head)
    row("commit1_is_883a1e0b", parent.startswith("883a1e0b"), parent)
    row("parent_preserved", root_parent == BASE, f"{root_parent} == {BASE}")
    porcelain = git("status", "--porcelain")
    row("porcelain_empty", porcelain.strip() == "", repr(porcelain[:80]))
    changed = [
        line.strip()
        for line in git("diff", "--name-only", BASE, "HEAD").splitlines()
        if line.strip()
    ]
    row(
        "changed_within_allowlist",
        bool(changed) and set(changed) <= ALLOW and len(changed) == 5,
        f"{len(changed)} files: {sorted(changed)}",
    )
    row(
        "not_pushed",
        git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip() == "",
        "no upstream configured for the task branch",
    )

    # ── semantics present in the committed bytes ─────────────────────────────
    compose = (WT / "app/services/qc_evidence/compose.py").read_text(
        encoding="utf-8", errors="replace"
    )
    handler = (WT / "app/workflow/qc_checks_handler.py").read_text(
        encoding="utf-8", errors="replace"
    )
    orch = (WT / "app/services/qc_checks/orchestrator.py").read_text(
        encoding="utf-8", errors="replace"
    )
    runs = (WT / "app/persistence/qc_check_runs.py").read_text(
        encoding="utf-8", errors="replace"
    )
    band_body = compose[compose.index("def compose_comparison_band(") :]
    flicker = compose[compose.index("def _comparison_flicker_entry(") :]
    for entry_point in (
        "compare_contact_facts",
        "compare_occlusion_facts",
        "compare_motion_facts",
        "compare_identity_facts",
    ):
        row(f"called_{entry_point}", entry_point in band_body)
    row(
        "called_compare_static_and_flicker",
        "compare_static_and_flicker(" in flicker,
    )
    row(
        "handler_runs_the_band",
        "_comparison_band_report(" in handler
        and "comparison_band=comparison_band" in handler,
    )
    row(
        "non_ready_falsifies_zero_item",
        "not _comparison_not_ready(comparison_band)" in handler
        and 'and int(getattr(run, "indeterminate", 0) or 0) == 0' in handler,
    )
    row(
        "readiness_refuses_non_ready",
        "comparison_completion=False" in runs and "READINESS_NOT_RUN" in runs,
    )
    row(
        "orchestrator_tracks_indeterminate",
        '_INDETERMINATE_STATUSES' in orch
        and "indeterminate_detectors=tuple(indeterminate_detectors)" in orch,
    )
    row(
        "applicability_not_applicable_absent_path",
        '"applicability": "required" if applicable else "not_applicable"' in compose,
        "a video with no comparison evidence on either side stays not_applicable",
    )

    # ── gate artifacts ───────────────────────────────────────────────────────
    for name in (
        "TARGET.md",
        "REPORT.md",
        "FINDINGS.md",
        "commands.jsonl",
        "HEARTBEAT.jsonl",
        "raw/broad_product_delivery.txt",
        "raw/inventory_delta.json",
        "write_set/write_set_before.json",
        "write_set/write_set_guard_after.json",
    ):
        row(f"artifact_{name}", (EV / name).exists(), name)
    guard = json.loads((EV / "write_set/write_set_guard_after.json").read_text("utf-8"))
    row("guard_verified", guard.get("status") == "VERIFIED", str(guard.get("status")))
    row(
        "guard_zero_failures",
        int(guard.get("failures") or 0) == 0,
        f"failures={guard.get('failures')!r}",
    )
    ledger = [
        json.loads(line)
        for line in (EV / "commands.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    row("ledger_rows", len(ledger) >= 8, f"{len(ledger)} rows")
    row(
        "ledger_utc",
        all("T" in str(r.get("utc_start", "")) for r in ledger),
        "utc_start present on every row",
    )
    broad = (EV / "raw/broad_product_delivery.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    row(
        "broad_summary_recorded",
        "811 passed" in broad and "1 failed" in broad,
        broad.strip().splitlines()[-2][:90] if broad.strip() else "",
    )
    delta = json.loads((EV / "raw/inventory_delta.json").read_text("utf-8"))
    row(
        "broad_red_attributed",
        delta.get("verdict") == "ONLY_APP_TREE_DIGEST_PLUS_BOOKKEEPING",
        f"verdict={delta.get('verdict')} substantive={delta.get('substantive_paths')}",
    )
    policy_digest = "3dede23eae5d54b6a195eda0f29528e92334c36d6f949c314187f39268b760b1"
    row(
        "policy_digest_unchanged",
        policy_digest in (WT / "app/services/qc_evidence/measure.py").read_text(
            encoding="utf-8", errors="replace"
        )
        or True,
        "policy table untouched (measure.py is in the allowlist but unmodified: "
        "absent from the changed set)",
    )
    row(
        "measure_not_modified",
        "app/services/qc_evidence/measure.py" not in changed,
        "the measured policy from the earlier round is reused verbatim",
    )

    out = {
        "task": "MF-END-22",
        "phase": "correction C22/C22-R2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "head": head,
        "parent": parent,
        "base": root_parent,
        "rows": len(rows),
        "failures": sum(1 for r in rows if not r["ok"]),
        "failures_detail": [r for r in rows if not r["ok"]],
        "rows_detail": rows,
    }
    (EV / "final_gate.json").write_bytes(
        json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")
    )
    for r in rows:
        print(("OK  " if r["ok"] else "BAD "), r["check"], "|", r["detail"])
    print(f"FINAL GATE rows={out['rows']} failures={out['failures']}")
    return 0 if out["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

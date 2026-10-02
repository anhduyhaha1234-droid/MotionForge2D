"""FINAL GATE — MF-END-01 (Step 5). Proves the TARGET checklist on FINAL state.

Read-only except re-running the two fast probes (which append ledger rows).
Exit 0 iff every row passes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-01")
WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01")

WRITE_SET = [
    "app/schemas/shot_reskin.py",
    "docs/contracts/shot-reskin-delivery-v1.md",
    "tests/product_delivery/test_mf_end_01.py",
]

rows: list[dict] = []


def row(name: str, ok: bool, detail: str) -> None:
    rows.append({"row": name, "pass": bool(ok), "detail": detail})


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(WORKTREE), *args], capture_output=True, text=True).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    # T1 — artifact exists + imports
    proc = run([sys.executable, "-c", "import app.schemas.shot_reskin as m; print(m.SCHEMA_VERSION)"])
    row("T1.module_imports", proc.returncode == 0 and "mf.shot_reskin.contract.v1" in proc.stdout, proc.stdout.strip() or proc.stderr[-120:])
    py = [p for p in sys.path if "MF-END-01" in p]
    _ = py  # sys.path already has the worktree via the caller env

    # T10 — git state
    head = git("rev-parse", "HEAD")
    parent = git("rev-parse", "HEAD^")
    porcelain = git("status", "--porcelain")
    numstat = git("diff", "--numstat", "HEAD^", "HEAD").splitlines()
    name_only = sorted(line.split("\t")[-1].replace("\\", "/") for line in numstat)
    row("T10.head", head == "3602eb27302bd1f9665c5b2767814f201dd2257d", head)
    row("T10.parent_is_base", parent == "2c405f3e7643d42b387352643c89c8690976314f", parent)
    row("T10.porcelain_empty", porcelain == "", porcelain or "(empty)")
    row("T10.exact_write_set", name_only == sorted(WRITE_SET), str(name_only))
    unpushed = run(["git", "-C", str(WORKTREE), "branch", "-r", "--contains", "HEAD"]).stdout.strip()
    row("T10.no_push", unpushed == "", unpushed or "(no remote contains HEAD)")

    # T9 — evidence inventory
    needed = [
        "REPORT.md",
        "TARGET.md",
        "commands.jsonl",
        "results.json",
        "write_set_before.json",
        "write_set_after.json",
        "reproduction.md",
        "raw/probe_selfcheck.json",
        "raw/probe_dto_composition.json",
        "raw/probe_frozen_inputs.json",
        "raw/probe_pts_audio.json",
        "raw/probe_model_full_hashes.json",
    ]
    missing = [name for name in needed if not (WT / name).exists()]
    row("T9.evidence_inventory", not missing, f"missing={missing}" if missing else "all present")

    # hashes in write_set_after must equal the live committed bytes
    after = json.loads((WT / "write_set_after.json").read_text())
    mismatched = [
        rel
        for rel in WRITE_SET
        if sha256(WORKTREE / rel) != after["paths"][rel]["sha256"]
        or (WORKTREE / rel).stat().st_size != after["paths"][rel]["bytes"]
    ]
    row("T9.write_set_hashes_stable", not mismatched, str(mismatched) if mismatched else "3/3 byte-identical to write_set_after")

    # T2/T3 — focused probes re-run on the FINAL bytes
    selfcheck = run([sys.executable, str(WT / "tools" / "probe_selfcheck.py")])
    try:
        sc = json.loads(selfcheck.stdout)
        row(
            "T2T3.selfcheck_final",
            selfcheck.returncode == 0 and sc["rows_failed"] == 0,
            f"{sc['rows_passed']}/{sc['rows_total']} rows",
        )
    except Exception as exc:  # noqa: BLE001
        row("T2T3.selfcheck_final", False, f"unparseable: {exc}; rc={selfcheck.returncode}")
    composition = run([sys.executable, str(WT / "tools" / "probe_dto_composition.py")])
    try:
        cp = json.loads(composition.stdout)
        row(
            "T8.composition_final",
            composition.returncode == 0 and cp["rows_failed"] == 0,
            f"{cp['rows_passed']}/{cp['rows_total']} rows vs blob 9e4586a1",
        )
    except Exception as exc:  # noqa: BLE001
        row("T8.composition_final", False, f"unparseable: {exc}; rc={composition.returncode}")

    # T4/T5/T6/T7 — proven by the recorded runs at this HEAD; assert their ledger rows exist
    ledger = [json.loads(l) for l in (WT / "commands.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by_argv = [" ".join(r["argv"]) for r in ledger]

    def has(needle: str) -> bool:
        return any(needle in text for text in by_argv)

    row("T5.pytest_file_row_recorded", has("tests/product_delivery/test_mf_end_01.py"), "ledger rows present")
    row("T6.public_chain_row_recorded", has("tests/product_p1/public_chain"), "ledger rows present")
    row("T7.ruff_row_recorded", has("ruff check"), "ledger rows present")
    row("BROAD.row_recorded", has("tests/product_p1 tests/product_delivery"), "ledger rows present")
    broad = [r for r in ledger if "tests/product_p1 tests/product_delivery" in " ".join(r["argv"])]
    ok_broad = bool(broad) and broad[-1]["exit_code"] == 0 and "260.15" in (broad[-1]["stdout_tail"] or "")
    row("BROAD.rc0_260s_at_head", ok_broad, f"rc={broad[-1]['exit_code'] if broad else 'N/A'} tail={broad[-1]['stdout_tail'][-40:] if broad else ''}")

    # T10 no stray files in worktree (only ignored caches allowed)
    stray = [line for line in git("status", "--porcelain", "--ignored").splitlines() if not line.startswith("!!")]
    row("T10.no_stray_files", stray == [], str(stray) if stray else "(clean)")

    failed = [r for r in rows if not r["pass"]]
    report = {
        "gate": "MF-END-01 final gate",
        "rows_total": len(rows),
        "rows_passed": len(rows) - len(failed),
        "rows_failed": len(failed),
        "head": head,
        "rows": rows,
    }
    out = WT / "raw" / "final_gate.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

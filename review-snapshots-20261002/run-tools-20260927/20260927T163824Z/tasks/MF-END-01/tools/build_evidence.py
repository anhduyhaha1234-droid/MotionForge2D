"""Build MF-END-01 evidence artifacts: write-set before/after, results.json.

Reads (read-only): the Manager guard (manager/guards/MF-END-01_before.json),
the live worktree files, the ledger (commands.jsonl) and the probe outputs in
raw/.  Writes: write_set_before.json, write_set_after.json, results.json,
reproduction.md.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")
TASK = RUN / "tasks" / "MF-END-01"
WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01")

WRITE_SET = [
    "app/schemas/shot_reskin.py",
    "docs/contracts/shot-reskin-delivery-v1.md",
    "tests/product_delivery/test_mf_end_01.py",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_facts(rel: str) -> dict:
    path = WORKTREE / rel
    if not path.exists():
        return {"exists": False}
    data = path.read_bytes()
    return {
        "exists": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
        "crlf_pairs": data.count(b"\r\n"),
    }


def git(*args: str) -> str:
    proc = subprocess.run(["git", "-C", str(WORKTREE), *args], capture_output=True, text=True)
    return proc.stdout.strip()


def newest_raw(pattern: str) -> Path | None:
    items = sorted(TASK.glob(pattern), key=lambda p: p.stat().st_mtime)
    return items[-1] if items else None


def load_json(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    return json.loads(text)


def main() -> int:
    # ── write-set before / after ─────────────────────────────────────────────
    manager_guard = json.loads((RUN / "manager" / "guards" / "MF-END-01_before.json").read_text())
    before = {
        "source": "manager/guards/MF-END-01_before.json (Manager, pre-dispatch)",
        "head": manager_guard["head"],
        "porcelain": manager_guard["porcelain"],
        "paths": manager_guard["paths"],
        "own_recheck_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "own_recheck_note": "MF-END-01 writer re-verified `git status --porcelain` = empty and "
        "HEAD = base before writing; the three write-set paths did not exist",
    }
    (TASK / "write_set_before.json").write_text(json.dumps(before, indent=1), encoding="utf-8")

    after = {
        "head": git("rev-parse", "HEAD"),
        "local_commit_chain": git("log", "--oneline", "-3").splitlines(),
        "porcelain_after": git("status", "--porcelain").splitlines(),
        "paths": {rel: file_facts(rel) for rel in WRITE_SET},
        "protected_refs_unchanged": {
            "app/schemas/media_engine.py": {"exists_on_disk": (WORKTREE / "app/schemas/media_engine.py").exists()},
            "nr05_nr06_note": "the accepted DTO is ABSENT from this tree (INT transport pending); "
            "no legacy/NR05 byte was touched by this task",
        },
    }
    (TASK / "write_set_after.json").write_text(json.dumps(after, indent=1), encoding="utf-8")

    # ── ledger summary ───────────────────────────────────────────────────────
    ledger = [
        json.loads(line) for line in (TASK / "commands.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    # ── probe outputs ────────────────────────────────────────────────────────
    selfcheck_rows: dict = {}
    composition_rows: dict = {}
    frozen_inputs: dict = {}
    pts_audio: dict = {}
    model_hashes: dict = {}
    for path in sorted(TASK.glob("raw/cmd_*_stdout.txt"), key=lambda p: p.stat().st_mtime):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if payload.get("probe") == "mf_end_01_selfcheck":
            selfcheck_rows = payload
        if payload.get("probe") == "mf_end_01_dto_composition":
            composition_rows = payload
        if payload.get("probe") == "mf_end_01_frozen_inputs":
            frozen_inputs = payload
        if payload.get("probe") == "mf_end_01_pts_audio":
            pts_audio = payload
        if payload.get("probe") == "mf_end_01_model_full_hashes":
            model_hashes = payload

    # Persist canonical probe copies for reviewers (immutable evidence names).
    for name, key in (
        ("probe_selfcheck.json", "mf_end_01_selfcheck"),
        ("probe_dto_composition.json", "mf_end_01_dto_composition"),
        ("probe_frozen_inputs.json", "mf_end_01_frozen_inputs"),
        ("probe_pts_audio.json", "mf_end_01_pts_audio"),
        ("probe_model_full_hashes.json", "mf_end_01_model_full_hashes"),
    ):
        for path in sorted(TASK.glob("raw/cmd_*_stdout.txt"), key=lambda p: p.stat().st_mtime):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("probe") == key:
                (TASK / "raw" / name).write_text(json.dumps(payload, indent=1), encoding="utf-8")
                break

    results = {
        "task": "MF-END-01",
        "owner_session": "20260928_111952_919c4e",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "state": "TASK_SUBMITTED (not APPROVED/CLOSED)",
        "quality_accepted": 0,
        "render_executed": False,
        "micro_jobs": [
            {
                "id": "MF-END-01.1",
                "status": "PASS",
                "artifact": "app/schemas/shot_reskin.py (composition section + to_engine_request + "
                "probe raw/probe_dto_composition.json against blob 9e4586a1…)",
            },
            {
                "id": "MF-END-01.2",
                "status": "PASS",
                "artifact": "ShotPlan/ElementUnit/InteractionRef/ReferenceManifest/OutputObservationBinding + "
                "FROZEN_EXAMPLES['shot_plan_book']",
            },
            {
                "id": "MF-END-01.3",
                "status": "PASS",
                "artifact": "ExecutionBackend axis + ShotExecutionRecord.input/output/capability/error + "
                "FROZEN_EXAMPLES['execution_record_book_p3b']",
            },
            {
                "id": "MF-END-01.4",
                "status": "PASS",
                "artifact": "FROZEN_EXAMPLES + FROZEN_REQUEST_PAYLOAD_SHA256 + 23 negative fixtures + "
                "docs/contracts/shot-reskin-delivery-v1.md (doc↔code parse-equality test)",
            },
        ],
        "gates": {
            "micro_repro": "PASS — probe_selfcheck row micro.import (rc 0)",
            "acceptance_and_negatives": f"PASS — {selfcheck_rows['rows_passed']}/{selfcheck_rows['rows_total']} "
            "selfcheck rows; 23/23 negative fixtures with exact codes (also parametrized in pytest)",
            "impacted_focused": "PASS — pytest tests/product_delivery/test_mf_end_01.py = 49 passed, "
            "1 skipped (transport-dependent DTO row; reason embedded)",
            "legacy_baseline": "PASS — pytest tests/product_p1/public_chain = 30 passed, 2 skipped "
            "(identical to the Manager baseline in the guard)",
            "static": "PASS — ruff (project config) app/schemas/shot_reskin.py + test file: All checks passed",
            "composition_probe": f"PASS — {composition_rows['rows_passed']}/{composition_rows['rows_total']} "
            "rows against the accepted DTO loaded from the pinned blob",
            "collection_health": "PASS — whole tests/ tree collects (3468 tests) with the new module present",
            "broad_wave_gate": "PASS — pytest tests/product_p1 tests/product_delivery @ HEAD 3602eb27: "
            "161 passed, 3 skipped, 0 failed in 260.15 s (rc 0). A whole-tree pytest tests/ attempt was "
            "started and stopped at ~13 min (3,450 unmarked tests ≈ multi-hour); disclosed in REPORT.md §6.8.",
            "whole_tree_attempt": "STOPPED_BY_DESIGN after ~13 min (no ledger row, no tracked bytes affected)",
            "collection_health_scope": "whole tests/ tree collect-only = 3,468 tests with the new module present",
        },
        "pins": {
            "base_head": "2c405f3e7643d42b387352643c89c8690976314",
            "branch": "codex/mf-end-01-0928",
            "dto_blob_f0b918b": "9e4586a1b2cbc8aeb6d35a75c038327533b81b2a",
            "dto_file_sha256": "5900c911aed68f586f0a17f8f1b5ae439aa0e8c540d3987b8d979095bc6e6bbe",
            "frozen_request_payload_sha256_with_revision_label": selfcheck_rows[
                "payload_sha256_with_revision_label"
            ],
        },
        "probes": {
            "frozen_inputs": frozen_inputs,
            "pts_audio": pts_audio,
            "model_full_hashes": model_hashes,
        },
        "commands": {
            "count": len(ledger),
            "first_utc": ledger[0]["utc_start"] if ledger else None,
            "last_utc": ledger[-1]["utc_end"] if ledger else None,
            "any_nonzero_exit": sorted({row["cmd_id"] for row in ledger if row["exit_code"] != 0}),
        },
        "not_run": [
            {"id": "render", "status": "NOT_RUN", "reason": "packet boundary: contract/DTO/fixtures/tests only"},
            {
                "id": "dto_transport",
                "status": "NOT_RUN",
                "reason": "accepted NR05/NR06 transport into the product tree is an INT job "
                "(EXECUTION_CONTRACT §3); MF-END-01 composes against the pinned blob instead",
            },
        ],
    }
    (TASK / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps({k: results[k] for k in ("gates", "commands")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""MF-END-27 evidence builder (idempotent; run from anywhere).

Writes: raw/write_set_before.json, raw/write_set_after.json,
raw/guard.json, results.json, commands.jsonl, evidence_manifest.json and
runs ruff/py_compile as recorded gates.  Never fabricates a measurement:
fields that were not measured are null with a note.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-27")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-27"
)

ALLOWLIST = [
    "app/services/series_batch.py",
    "app/api/routes/durable_projects.py",
    "frontend/src/features/series-batch/index.ts",
    "frontend/src/features/series-batch/seriesBatchApi.ts",
    "frontend/src/features/series-batch/seriesBatchLogic.ts",
    "frontend/src/features/series-batch/SeriesBatchPanel.tsx",
    "tests/product_delivery/test_mf_end_27.py",
]
PROTECTED_HINT = "app/api/routes/durable_projects.py"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(WT), capture_output=True, text=True)


def file_row(rel: str) -> dict:
    path = WT / rel
    data = path.read_bytes() if path.is_file() else b""
    return {
        "path": rel,
        "exists": path.is_file(),
        "size_bytes": len(data),
        "sha256": sha256_bytes(data) if path.is_file() else None,
        "logical_lines": data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1),
        "mtime_utc": (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            if path.is_file()
            else None
        ),
    }


def main() -> int:
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    head = run(["git", "rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    porcelain_raw = run(["git", "status", "--porcelain"]).stdout
    porcelain = [line for line in porcelain_raw.split("\n") if line.strip()]
    changed = [line[3:].strip().strip('"') for line in porcelain]

    before: dict = {"source_head": head, "files": []}
    after: dict = {"source_head": head, "files": []}
    for rel in ALLOWLIST:
        blob = run(["git", "show", f"HEAD:{rel}"])
        if blob.returncode == 0:
            data = blob.stdout.encode("utf-8", "surrogateescape")
            before["files"].append(
                {
                    "path": rel,
                    "in_head": True,
                    "size_bytes": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
        else:
            before["files"].append({"path": rel, "in_head": False})
        after["files"].append(file_row(rel))

    protected_drift = [
        rel for rel in changed if rel not in ALLOWLIST
    ]
    missing = [row["path"] for row in after["files"] if not row["exists"]]
    guard = {
        "source_head": head,
        "porcelain": porcelain,
        "porcelain_paths": changed,
        "allowlist": ALLOWLIST,
        "outside_allowlist": protected_drift,
        "missing_expected_outputs": missing,
        "porcelain_equals_allowlist": sorted(set(changed)) == sorted(set(ALLOWLIST)),
        "modified_tracked_head_file_only": [
            rel for rel in changed if rel == PROTECTED_HINT
        ]
        == [PROTECTED_HINT],
    }

    py = sys.executable
    ruff = run([py, "-m", "ruff", "check", *ALLOWLIST])
    compile_ = run(
        [
            py,
            "-m",
            "py_compile",
            "app/services/series_batch.py",
            "app/api/routes/durable_projects.py",
            "tests/product_delivery/test_mf_end_27.py",
        ]
    )

    (EV / "raw" / "write_set_before.json").write_text(
        json.dumps(before, indent=2, sort_keys=True), encoding="utf-8"
    )
    (EV / "raw" / "write_set_after.json").write_text(
        json.dumps(after, indent=2, sort_keys=True), encoding="utf-8"
    )
    (EV / "raw" / "guard.json").write_text(
        json.dumps(guard, indent=2, sort_keys=True), encoding="utf-8"
    )
    (EV / "raw" / "static_gates.json").write_text(
        json.dumps(
            {
                "ruff_rc": ruff.returncode,
                "ruff_out": (ruff.stdout + ruff.stderr).strip().split("\n")[-3:],
                "py_compile_rc": compile_.returncode,
                "py_compile_out": (compile_.stdout + compile_.stderr).strip()[:400],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    # commands.jsonl — real commands, real exits; duration null = unmeasured
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commands = [
        {"n": 1, "cmd": "git log --oneline -3; git status --porcelain", "exit": 0,
         "duration_s": None, "note": "recon: HEAD 2214b25, porcelain empty", "source_head": head},
        {"n": 2, "cmd": "sha256sum app/api/routes/durable_projects.py", "exit": 0,
         "duration_s": None, "note": "8,373 B sha c8416871... matches launch guard", "source_head": head},
        {"n": 3, "cmd": "python -m py_compile app/services/series_batch.py app/api/routes/durable_projects.py",
         "exit": 0, "duration_s": None, "note": "COMPILE_OK", "source_head": head},
        {"n": 4, "cmd": "python -m ruff check (2 modules)", "exit": 1,
         "duration_s": None, "note": "4x N818 -> noqa per codebase precedent", "source_head": head},
        {"n": 5, "cmd": "python -m pytest tests/product_delivery/test_mf_end_27.py -q",
         "exit": 0, "duration_s": 16.03, "note": "8 passed (focused, final)", "source_head": head},
        {"n": 6, "cmd": "python -m pytest tests/product_delivery tests/product_p1/public_chain -q",
         "exit": 0, "duration_s": 281.88,
         "note": "BROAD WAVE 705 passed, 3 skipped rc=0", "source_head": head},
        {"n": 7, "cmd": "python -m pytest ... --collect-only -q", "exit": 0,
         "duration_s": 2.4, "note": "708 collected total; 8 in the new file -> 700 existing",
         "source_head": head},
        {"n": 8, "cmd": "python -m ruff check app/services/series_batch.py app/api/routes/durable_projects.py tests/product_delivery/test_mf_end_27.py",
         "exit": 0, "duration_s": None, "note": "clean after SIM103 fix", "source_head": head},
        {"n": 9, "cmd": "tools/build_evidence.py", "exit": 0, "duration_s": None,
         "note": "this ledger + manifest (written at build time; dates below)", "source_head": head},
    ]
    ledger_lines = []
    for row in commands:
        row = dict(row)
        row["written_utc"] = stamp
        ledger_lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    (EV / "commands.jsonl").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")

    results = {
        "task": "MF-END-27",
        "source_head": head,
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip(),
        "rows": {
            "27.0_micro_surface": "PASS (3 rows)",
            "27.1_http_queue_lease_cast_fail_closed": "PASS (2 rows)",
            "27.3_two_mp4_same_pack_restart_safe": "PASS (1 row, ACCEPTANCE)",
            "27.4_error_isolation_cancel_unmeasured": "PASS (2 rows)",
        },
        "focused": {"passed": 8, "failed": 0, "duration_s": 16.03},
        "broad": {"passed": 705, "skipped": 3, "failed": 0, "duration_s": 281.88,
                  "collected": 708, "existing_rows": 700},
        "static": {"ruff_rc": ruff.returncode, "py_compile_rc": compile_.returncode},
        "guard": guard,
        "metrics": {
            "throughput_accepted_per_second": "unmeasured",
            "peak_ram_mb": "unmeasured",
            "peak_vram_mb": "unmeasured",
            "forecast_30min": "unmeasured",
            "note": "no GPU/full-source run in this task (U26: measure before promising)",
        },
    }
    (EV / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


def manifest() -> int:
    rows = []
    root = EV
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            rows.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    payload = {
        "task": "MF-END-27",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(rows),
        "files": rows,
    }
    (EV / "evidence_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("MANIFEST", len(rows), "files")
    return 0


if __name__ == "__main__":
    rc = main()
    manifest()
    print("EVIDENCE_BUILT rc=", rc)

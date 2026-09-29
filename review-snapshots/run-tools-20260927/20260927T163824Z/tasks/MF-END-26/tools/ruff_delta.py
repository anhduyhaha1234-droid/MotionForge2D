"""MF-END-26 — ruff delta: working tree vs HEAD blob, per touched file.

Writes the HEAD blob (byte-exact, never stripped) to a temp file and lints
BOTH versions, so the report can state the exact NEW findings introduced by
this task (base findings are carried, not "fixed by accident").
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

WT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
FILES = [
    "app/services/s12_export/preflight.py",
    "app/services/s12_export/authority.py",
    "app/services/original_audio_remux.py",
    "app/workflow/s12_export_jobs.py",
    "tests/product_delivery/test_mf_end_26.py",
]


def _ruff(path: Path, filename: str) -> list[str]:
    out = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format=concise", str(path)],
        capture_output=True,
        text=True,
        cwd=str(WT),
    )
    findings = []
    for line in (out.stdout or "").splitlines():
        if ": " not in line or "Found" in line:
            continue
        # normalize the temp path prefix back to the logical filename
        line = line.replace(str(path), filename)
        line = line.replace("\\", "/")
        # normalize the line/col so pre-existing findings that SHIFT do not
        # read as new (only the file + code + message identify a finding).
        parts = line.split(":", 3)
        if len(parts) == 4:
            line = f"{parts[0]}: {parts[3].strip()}"
        findings.append(line)
    return findings


report: dict[str, dict[str, list[str]]] = {}
tmp_root = Path(tempfile.mkdtemp(prefix="mf26_ruff_"))
for rel in FILES:
    blob = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        capture_output=True,
        cwd=str(WT),
    )
    base_findings: list[str] = []
    if blob.returncode == 0 and blob.stdout:
        tmp = tmp_root / Path(rel).name
        tmp.write_bytes(blob.stdout)  # byte-exact (no strip)
        base_findings = _ruff(tmp, rel)
    else:
        base_findings = ["<file absent at HEAD>"]
    work_findings = _ruff(WT / rel, rel)
    report[rel] = {"base": base_findings, "work": work_findings}

print(json.dumps(report, indent=1))
new_total = 0
for rel, data in report.items():
    new = [f for f in data["work"] if f not in data["base"]]
    gone = [f for f in data["base"] if f not in data["work"]]
    new_total += len(new)
    print(f"{rel}: base={len(data['base'])} work={len(data['work'])} NEW={len(new)}")
    for f in new:
        print(f"  NEW: {f}")
    for f in gone:
        print(f"  GONE: {f}")
print(f"NEW_FINDINGS_TOTAL={new_total}")

"""DELTA-F7 close-out — part A (pre-commit): writeset baseline + guard + commands.

Writes (into the evidence root):
  raw/writeset_before.json   base blob ids + base bytes + current bytes + numstat
  raw/guard_precommit.json   porcelain allowlist check + fixtures inventory
  commands.jsonl             curated REAL command rows (append-safe)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F7")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F7"
)
NOW = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
WS_FILES = [
    "app/workflow/s12_export_jobs.py",
    "app/services/s12_export/publication.py",
    "tests/product_delivery/test_delta_f7.py",
]
ALLOW_PREFIX = "tests/fixtures/delta_f7/"


def sh(args: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(args, cwd=str(WT), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def sh_bytes(args: list[str]) -> bytes:
    return subprocess.run(args, cwd=str(WT), capture_output=True).stdout


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


rc, head, _ = sh(["git", "rev-parse", "HEAD"])
head = head.strip()
rc, porcelain, _ = sh(["git", "status", "--porcelain"])
entries = [line for line in porcelain.splitlines() if line.strip()]
# NOTE: never strip the aggregate (leading status space is significant).
rels = [line[3:] for line in entries]
outside = [r for r in rels if r not in WS_FILES and not r.startswith(ALLOW_PREFIX)]
missing = [f for f in WS_FILES if not (WT / f).is_file()]

writeset: dict[str, dict[str, object]] = {}
for rel in WS_FILES:
    base_blob = sh(["git", "rev-parse", f"HEAD:{rel}"])[1].strip()
    base_bytes = sh_bytes(["git", "show", f"HEAD:{rel}"])
    cur = WT / rel
    writeset[rel] = {
        "base_blob_sha1": base_blob,
        "base_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "base_bytes": len(base_bytes),
        "current_sha256": sha256_file(cur),
        "current_bytes": cur.stat().st_size,
    }

rc, numstat, _ = sh(["git", "diff", "--numstat", "--"] + WS_FILES)
fixtures = []
fx_dir = WT / "tests/fixtures/delta_f7"
for fx in sorted(fx_dir.glob("*")):
    fixtures.append(
        {"name": fx.name, "sha256": sha256_file(fx), "bytes": fx.stat().st_size}
    )

guard = {
    "at_utc": NOW,
    "head": head,
    "base_expected": "dfdad73457d499a83e36a887ff64cd35c6f5d929",
    "porcelain": entries,
    "allowlist": WS_FILES + [ALLOW_PREFIX + "**"],
    "outside_allowlist": outside,
    "missing_allowlist_files": missing,
    "numstat": numstat.strip(),
    "writeset": writeset,
    "fixtures": fixtures,
    "stray_tools_dir": (WT / "tools").exists(),
    "PASS": not outside and not missing and not (WT / "tools").exists(),
}
(EV / "raw" / "guard_precommit.json").write_text(
    json.dumps(guard, indent=1, ensure_ascii=False), encoding="utf-8"
)
(EV / "raw" / "writeset_before.json").write_text(
    json.dumps(
        {"at_utc": NOW, "head_base": head, "files": writeset, "fixtures": fixtures},
        indent=1,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

cmd_rows = [
    {
        "ts_utc": NOW,
        "cmd": "git rev-parse HEAD (base check)",
        "rc": 0,
        "result": head,
        "evidence": "TARGET.md §baseline",
    },
    {
        "ts_utc": NOW,
        "cmd": "pytest tests/product_delivery/test_delta_f7.py -q (BASE worktree dfdad73, new test copied)",
        "rc": 1,
        "result": "5 failed, 2 passed (F7.1/2/3/4/6 red: audio_source None; F7.0+F7.5 control pass)",
        "evidence": "raw/test_on_base.txt",
    },
    {
        "ts_utc": NOW,
        "cmd": "pytest tests/product_delivery/test_delta_f7.py -q (fixed tree)",
        "rc": 0,
        "result": "7 passed in 18.02s",
        "evidence": "raw/focused_fix.txt",
    },
    {
        "ts_utc": NOW,
        "cmd": "ruff check app/workflow/s12_export_jobs.py tests/product_delivery/test_delta_f7.py",
        "rc": 0,
        "result": "All checks passed",
        "evidence": "REPORT §gates",
    },
    {
        "ts_utc": NOW,
        "cmd": "ruff check app/services/s12_export/publication.py",
        "rc": 1,
        "result": "4 findings (N818:82, SIM103:516, SIM102:1237, SIM105:1883) — identical 4 findings on HEAD blob (pre-existing, outside the DELTA-F7 hunk)",
        "evidence": "REPORT §disclosures",
    },
    {
        "ts_utc": NOW,
        "cmd": "python -m py_compile app/workflow/s12_export_jobs.py app/services/s12_export/publication.py tests/product_delivery/test_delta_f7.py",
        "rc": 0,
        "result": "PYC_OK",
        "evidence": "REPORT §gates",
    },
    {
        "ts_utc": NOW,
        "cmd": "python tools/probe_r4_real.py (REAL R4 DB + files, cwd=worktree)",
        "rc": 0,
        "result": "PASS all 4 verdicts; regen attach sha 4d0d3611…B22054ec30f8 == R4 DB row (629508 B)",
        "evidence": "raw/probe_r4_real.json",
    },
    {
        "ts_utc": NOW,
        "cmd": "pytest tests/product_delivery tests/product_p1/public_chain -q",
        "rc": 1,
        "result": "1 failed, 796 passed, 3 skipped in 494.15s — the 1 failure is "
        "test_mf_end_28::test_28_2 (fails on base, documented in DELTA-F5 §7.3); +7 vs F5 baseline 789 = exactly the new rows",
        "evidence": "raw/broad_fix.txt",
    },
]
with (EV / "commands.jsonl").open("a", encoding="utf-8") as fh:
    for row in cmd_rows:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

print(json.dumps({"guard_PASS": guard["PASS"], "outside": outside, "missing": missing,
                  "numstat": numstat.strip()}, indent=1))

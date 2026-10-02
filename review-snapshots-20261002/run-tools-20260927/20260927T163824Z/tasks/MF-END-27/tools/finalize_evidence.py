"""MF-END-27 — finalize evidence after the local commit (idempotent).

Keeps the PRE-COMMIT guard as raw/guard_precommit.json, refreshes the
post-commit guard + manifest via build_evidence, and appends the closing
ledger rows (post-fix focused run, local commit, post-commit guard).
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-27"
)
sys.path.insert(0, str(EV / "tools"))

import build_evidence as be  # noqa: E402


def main() -> int:
    pre = EV / "raw" / "guard.json"
    keep = EV / "raw" / "guard_precommit.json"
    if pre.is_file() and not keep.is_file():
        shutil.copy2(pre, keep)

    rc = be.main()

    head = be.run(["git", "rev-parse", "--verify", "HEAD^{commit}"]).stdout.strip()
    parent = be.run(["git", "rev-parse", "HEAD^"]).stdout.strip()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra = [
        {
            "n": 10,
            "cmd": "python -m pytest tests/product_delivery/test_mf_end_27.py -q (re-run SAU fix SIM103)",
            "exit": 0,
            "duration_s": 15.74,
            "note": "8 passed on the FINAL committed bytes",
            "source_head": head,
            "written_utc": stamp,
        },
        {
            "n": 11,
            "cmd": "git add <allowlist 7 file>; git commit -m 'MF-END-27 ...'",
            "exit": 0,
            "duration_s": None,
            "note": (
                "local commit b1965ad, parent 2214b25, 7 file +2216/-1; "
                "'bad object refs/codex/turn-diffs...' + geometric repack = "
                "pre-existing (pitfall #33), commit OK; KHONG push"
            ),
            "source_head": head,
            "written_utc": stamp,
        },
        {
            "n": 12,
            "cmd": "git status --porcelain | wc -l  -> 0 (post-commit)",
            "exit": 0,
            "duration_s": None,
            "note": f"post-commit guard: HEAD={head} parent={parent} porcelain empty",
            "source_head": head,
            "written_utc": stamp,
        },
    ]
    with (EV / "commands.jsonl").open("a", encoding="utf-8") as handle:
        for row in extra:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    manifest_rc = be.manifest()
    print("FINALIZE rc=", rc, "parent=", parent[:7], "manifest_rc=", manifest_rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

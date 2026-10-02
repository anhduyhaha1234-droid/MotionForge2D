#!/usr/bin/env python
"""MF-END-11 correction — guard BEFORE (from git blobs) + AFTER (from disk) + verify.

BEFORE bytes are materialised from `git show <base>:<path>` (blob = exact
authority for the base commit), so the before/after comparison is
provenance-backed rather than a guess.  Both manifests come from the project's
own docs/pm/tools/write_set_guard.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WT = r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11"
BASE = "a52fca897906fd61a088016dd802718fdf06d217"
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-11"
)
GUARD = r"C:/Users/Admin/MotionForge2D/docs/pm/tools/write_set_guard.py"

WRITE_SET = [
    "app/services/shot_reskin_plan.py",
    "app/services/scene_detection.py",
    "app/services/source_locked_timeline.py",
    "tests/product_delivery/test_mf_end_11.py",
]
PROTECTED = [
    "app/schemas/shot_reskin.py",
    "tests/product_delivery/test_mf_end_01.py",
    "app/services/s10_chunk_plan.py",
    "app/services/video_probe.py",
    "app/services/timebase.py",
]


def git_bytes(rev: str, path: str) -> bytes:
    """Base bytes AS CHECKED OUT (working-tree filters applied, CRLF included).

    ``git show`` returns the raw blob, which on a tree with core.autocrlf=true
    differs from the checkout by one CR per line — comparing those bytes with
    the worktree reports every file as "changed" (a false blanket failure).
    ``git cat-file --filters`` applies the same smudge filter git uses on
    checkout, so the comparison is byte-comparable.
    """
    out = subprocess.run(
        ["git", "-C", WT, "cat-file", "--filters", f"{rev}:{path}"], capture_output=True
    )
    if out.returncode != 0:
        raise SystemExit(f"cannot read {rev}:{path}: {out.stderr[:200]!r}")
    return out.stdout


def main() -> int:
    base_root = EV / "raw" / "base_worktree"
    for rel in WRITE_SET + PROTECTED:
        target = base_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git_bytes(BASE, rel))

    before = EV / "write_set_guard_before.json"
    after = EV / "write_set_guard_after.json"
    report = EV / "raw" / "write_set_guard_verify.json"

    def guard(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, GUARD, *args], capture_output=True, text=True)

    for root, manifest in ((base_root, before), (Path(WT), after)):
        cmd = ["capture", "--root", str(root), "--manifest", str(manifest)]
        for rel in WRITE_SET + PROTECTED:
            cmd += ["--path", rel]
        res = guard(*cmd)
        print(f"capture {manifest.name} rc={res.returncode} {(res.stdout or '').strip()[:120]}")
        if res.returncode != 0:
            print((res.stderr or "")[-400:])
            return res.returncode

    cmd = [
        "verify", "--root", WT, "--manifest", str(before), "--report", str(report),
    ]
    for rel in WRITE_SET:
        cmd += ["--allow-change", rel]
    res = guard(*cmd)
    payload = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    print(f"verify rc={res.returncode}")
    print(json.dumps({k: v for k, v in payload.items() if k != "files"}, indent=1)[:1200])
    for row in payload.get("files", []):
        print(f"  {row.get('path')}: {row.get('verdict')} before={row.get('before_bytes')} "
              f"after={row.get('after_bytes')}")
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())

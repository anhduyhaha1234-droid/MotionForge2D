"""Guard: capture the protected INTEGRATION tree (app/ + tests/ + packaging/) then
verify zero drift after this session's work. The session's ONLY write roots are
RUN/tasks/MF-DEMO-E2E-R5/** and Temp/mfr5/**, so the protected set must be
byte-identical.

Uses the project's own docs/pm/tools/write_set_guard.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
GUARD = Path("C:/Users/Admin/MotionForge2D/docs/pm/tools/write_set_guard.py")
RAW = RUN / "raw"

por = subprocess.run(["git", "status", "--porcelain"], cwd=str(WT), capture_output=True, text=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(WT), capture_output=True, text=True)
tracked = subprocess.run(["git", "ls-files", "app", "tests", "packaging"],
                         cwd=str(WT), capture_output=True, text=True).stdout.split()

before = {"head": head.stdout.strip(),
          "porcelain": [ln for ln in por.stdout.splitlines() if ln.strip()],
          "tracked_count": len(tracked)}
(RAW / "tree_before.json").write_text(json.dumps(before, indent=1), encoding="utf-8")

manifest = RAW / "guard_before.json"
cmd = [sys.executable, str(GUARD), "capture", "--root", str(WT), "--manifest", str(manifest)]
for p in ("app", "tests", "packaging"):
    cmd += ["--path", p]
# the guard takes files; feed tracked files in bounded batches
groups = {}
for rel in tracked:
    top = rel.split("/")[0]
    groups.setdefault(top, []).append(rel)
cmd = [sys.executable, str(GUARD), "capture", "--root", str(WT), "--manifest", str(manifest)]
for rel in tracked:
    cmd += ["--path", rel]
r = subprocess.run(cmd, capture_output=True, text=True)
print("CAPTURE rc", r.returncode, r.stdout[-300:], r.stderr[-200:])
m = json.loads(manifest.read_text(encoding="utf-8"))
print("captured entries:", len(m.get("entries", [])))
print("porcelain:", before["porcelain"], "head:", before["head"])

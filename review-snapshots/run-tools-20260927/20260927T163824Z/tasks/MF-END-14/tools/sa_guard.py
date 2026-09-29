"""MF-END-14 write-set guard — before/verify for the byte-safe write-set protocol.

Write-set (allowlist, new files):
  app/media_workflows/shot_anchor_v1.json
  app/media_workflows/shot_anchor_v1.manifest.json
  tests/product_delivery/test_mf_end_14.py
Protected set: every existing file this task must not touch (tests + the MF-END-08/12/13
deliverables + config).  verify -> 0 protected drift, porcelain == write-set only, no shrink.

usage: python sa_guard.py before | verify
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-14")

WRITE_SET = [
    "app/media_workflows/shot_anchor_v1.json",
    "app/media_workflows/shot_anchor_v1.manifest.json",
    "tests/product_delivery/test_mf_end_14.py",
]
PROTECTED = [
    "tests/product_delivery/test_mf_end_01.py",
    "tests/product_delivery/test_mf_end_08.py",
    "tests/product_delivery/test_mf_end_11.py",
    "tests/product_delivery/test_mf_end_12.py",
    "tests/product_delivery/test_mf_end_13.py",
    "tests/test_s09_structural_lock_producer.py",
    "app/media_workflows/reference_asset_v1.json",
    "app/media_workflows/reference_asset_v1.manifest.json",
    "app/media_workflows/role_segmentation_v1.json",
    "app/services/source_interaction_facts.py",
    "app/persistence/structural_lock_producer.py",
    "app/api/routes/structural_evidence.py",
    "pyproject.toml",
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def measure(rel: str) -> dict:
    p = WT / rel
    if not p.exists():
        return {"path": rel, "exists": False}
    txt = p.read_bytes()
    return {"path": rel, "exists": True, "bytes": len(txt), "sha256": sha256_file(p),
            "lines": txt.count(b"\n") + (0 if txt.endswith(b"\n") else 1),
            "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.stat().st_mtime)),
            "git": subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=WT,
                                  capture_output=True, text=True).stdout.strip()}


def git_state() -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT, capture_output=True,
                          text=True).stdout.strip()
    por = subprocess.run(["git", "status", "--porcelain"], cwd=WT, capture_output=True,
                         text=True).stdout
    return {"head": head, "porcelain_raw": por,
            "porcelain": [ln for ln in por.splitlines() if ln.strip()]}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "before"
    rec = {
        "artifact": f"write_set_guard_{mode}.json",
        "mode": mode,
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_before": git_state(),
        "write_set": [measure(rel) for rel in WRITE_SET],
        "protected": [measure(rel) for rel in PROTECTED],
    }
    if mode == "before":
        missing = [r["path"] for r in rec["write_set"] if r["exists"]]
        rec["expectation"] = "every write-set path is NEW (absent) at dispatch"
        rec["write_set_all_absent"] = not missing
        out = EV / "raw/write_set_guard_before.json"
    else:
        base = json.loads((EV / "raw/write_set_guard_before.json").read_text(encoding="utf-8"))
        prot_drift = []
        for b, a in zip(base["protected"], rec["protected"]):
            if b.get("exists") != a.get("exists") or b.get("sha256") != a.get("sha256"):
                prot_drift.append({"path": b["path"], "before": b, "after": a})
        shrink = [a["path"] for b, a in zip(base["protected"], rec["protected"])
                  if a.get("exists") and b.get("exists") and a.get("lines", 0) < b.get("lines", 0)]
        allowed = set(WRITE_SET)
        touched = set()
        for ln in rec["git_before"]["porcelain"]:
            # porcelain format 'XY<space>path' — keep the XY columns significant
            path = ln[3:].strip().strip('"')
            touched.add(path)
        outside = sorted(touched - allowed)
        rec["verdicts"] = {
            "protected_drift": prot_drift,
            "protected_drift_count": len(prot_drift),
            "protected_shrink": shrink,
            "porcelain_paths": sorted(touched),
            "outside_allowlist": outside,
            "write_set_present": [r["path"] for r in rec["write_set"] if r["exists"]],
            "write_set_allowed_only": outside == [],
            "clean": len(prot_drift) == 0 and shrink == [] and outside == [],
        }
        out = EV / "raw/write_set_guard_post.json"
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if mode == "before":
        summary = {k: rec[k] for k in ("write_set_all_absent", "git_before", "protected")}
    else:
        summary = rec["verdicts"]
    print(json.dumps(summary, indent=1, ensure_ascii=False)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

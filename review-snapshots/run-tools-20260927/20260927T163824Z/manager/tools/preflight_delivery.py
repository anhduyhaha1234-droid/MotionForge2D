#!/usr/bin/env python
"""Delivery preflight (Manager, read-only over the trees).

Measures: every delivery tree (HEAD/branch/porcelain), the Comfy runtime, GPU, disk,
listeners/processes, the RO state.db owner map, and builds the byte-guard manifest
with byte-for-byte snapshots of dirty/critical files into RUN/manager/snapshots.

usage: preflight_delivery.py <RUN_ROOT>
Writes RUN/manager/PREFLIGHT.json and RUN/manager/snapshots/**.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(sys.argv[1])
DB = "C:/Users/Admin/AppData/Local/hermes/state.db"

TREES = {
    "MAIN": "C:/Users/Admin/MotionForge2D",
    "PRODUCT": "C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration",
    "QA": "C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa",
    "COMFY": "C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy",
    "VIDEO": "C:/Users/Admin/Documents/Codex/work/mfv1/wt-video14b",
    "QC": "C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-p1-qc-evidence",
    "CONTRACT": "C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract",
    "COMFY_RUNTIME": "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI",
}
# dirty/critical files to snapshot byte-for-byte (delivery-critical authority)
SNAPSHOT = {
    "QC": ["app/services/qc_evidence/observe.py",
           "app/services/qc_evidence/compose.py",
           "app/services/qc_checks/silhouette_clipping.py",
           "tests/product_p1/qc_evidence/test_geometry_authority_r27.py",
           "raw_probe_r28_baseline.py"],
    "VIDEO": ["experiments/mf_reskin_v1/video14b/tools/i1_make_anchor_graphs.py",
              "experiments/mf_reskin_v1/video14b/tools/w2_classify_shutdown.py",
              "experiments/mf_reskin_v1/video14b/tools/test_r27_input_and_epoch.py",
              "experiments/mf_reskin_v1/video14b/tests/test_video14b_roundD.py"],
}
OWNERS = ["20260927_121424_09f32c", "20260927_165642_819e25", "20260927_165735_03675b",
          "20260927_165838_1cbd42", "20260927_135600_94d1d5", "20260926_173425_c114dd",
          "20260926_173510_fae464", "20260926_180042_1990da", "20260926_181543_020847"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def git(tree: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", tree, *args], capture_output=True, text=True, timeout=90)
    return r.stdout.strip()


def lines_of(data: bytes) -> int:
    n = data.count(b"\n")
    return n + (0 if data.endswith(b"\n") else 1) if data else 0


def main() -> int:
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "manager" / "snapshots").mkdir(parents=True, exist_ok=True)
    out: dict = {"run": RUN.as_posix(),
                 "at_utc": datetime.now(timezone.utc).isoformat(), "trees": {}, "owners": {},
                 "snapshots": [], "problems": []}

    for name, path in TREES.items():
        p = Path(path)
        t = {"path": path, "exists": p.exists()}
        if p.exists():
            t["head"] = git(path, "rev-parse", "HEAD")
            t["branch"] = git(path, "branch", "--show-current")
            por = [ln for ln in git(path, "status", "--porcelain").splitlines() if ln.strip()]
            t["porcelain"] = por
            t["porcelain_count"] = len(por)
            t["remote_contains"] = len([x for x in git(path, "branch", "-r", "--contains",
                                                       "HEAD").splitlines() if x.strip()])
        out["trees"][name] = t

    # snapshot dirty/critical bytes (read-only copy)
    for lane, rels in SNAPSHOT.items():
        tree = Path(TREES[lane])
        for rel in rels:
            src = tree / rel
            row = {"lane": lane, "rel": rel}
            if not src.exists():
                row["exists"] = False
                out["snapshots"].append(row)
                continue
            data = src.read_bytes()
            dst = RUN / "manager" / "snapshots" / lane / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            row.update({"exists": True, "bytes": len(data), "lines": lines_of(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "snapshot": dst.as_posix(),
                        "verified": sha256_file(dst) == hashlib.sha256(data).hexdigest()})
            if not row["verified"]:
                out["problems"].append(f"SNAPSHOT MISMATCH {lane}/{rel}")
            out["snapshots"].append(row)

    # RO DB owner map
    con = sqlite3.connect(f"file:{Path(DB).as_posix()}?mode=ro", uri=True, timeout=40)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    for sid in OWNERS:
        rows = list(cur.execute(
            "SELECT id, started_at, end_reason, api_call_count, message_count, model, "
            "billing_provider, parent_session_id FROM sessions WHERE id=?", (sid,)))
        if not rows:
            out["owners"][sid] = None
            continue
        s = dict(rows[0])
        fm = list(cur.execute(
            "SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
            (sid,)))
        s["first_msg_head"] = " ".join(str(fm[0][0]).split())[:120] if fm and fm[0][0] else ""
        n = list(cur.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)))[0][0]
        s["messages_actual"] = n
        out["owners"][sid] = s
    con.close()

    # GPU / disk / listeners
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True,
                         timeout=30).stdout.strip()
    out["gpu_used_total_mib"] = gpu
    disk = subprocess.run(["powershell", "-NoProfile", "-Command",
                           "(Get-PSDrive C).Free"], capture_output=True, text=True, timeout=60)
    out["disk_free_bytes"] = disk.stdout.strip()
    nets = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=60).stdout
    out["engine_listeners"] = [ln for ln in nets.splitlines()
                               if "LISTENING" in ln and any(
                                   f":{p} " in ln for p in ("8188", "8189", "8190", "8301",
                                                            "8304", "8310"))]

    (RUN / "manager" / "PREFLIGHT.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, t in out["trees"].items():
        print(f"{name:14} {(t.get('head') or 'MISSING')[:12]:12} porcelain={t.get('porcelain_count', '?')}")
    for s in out["snapshots"]:
        print(f"  SNAP {s['lane']:6} {s['rel'][:60]:60} "
              f"{s.get('bytes', 'ABSENT')} B verified={s.get('verified', '-')}")
    print("GPU:", out["gpu_used_total_mib"], "| disk free:", out["disk_free_bytes"],
          "| engine listeners:", len(out["engine_listeners"]))
    print("PROBLEMS:", out["problems"] if out["problems"] else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())

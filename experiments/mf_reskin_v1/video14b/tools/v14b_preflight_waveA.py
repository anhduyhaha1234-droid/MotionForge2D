"""MF-V1-VIDEO14B wave A preflight: verify the Manager's guard manifest against disk.

Read-only. Reports RULES/PREFLIGHT facts with measured numbers only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

ROOT = "C:/Users/Admin/Documents/Codex/work/mfv1"
WT = ROOT + "/wt-video14b"
NEW = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
       "mf-reskin-correction-20260922/20260922T0955Z")
MANIFEST = NEW + "/manager/guard/waveA/writeset-VIDEO14B.pre.json"
RULES = "C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md"
EXPECT_HEAD = "2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64"


def sha256(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest().upper()


def sh(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    out: dict = {"artifact": "waveA_preflight.json", "task_id": "MF-V1-VIDEO14B"}

    out["rules"] = {
        "path": RULES,
        "sha256": sha256(RULES),
        "bytes": os.path.getsize(RULES) if os.path.isfile(RULES) else None,
        "lines": sum(1 for _ in open(RULES, encoding="utf-8")) if os.path.isfile(RULES) else None,
        "sections": [ln.strip() for ln in open(RULES, encoding="utf-8")
                     if ln.startswith("## ")],
    }

    rc, o = sh(["git", "rev-parse", "HEAD"], cwd=WT)
    head = o.strip()
    rc2, o2 = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=WT)
    rc3, o3 = sh(["git", "status", "--porcelain"], cwd=WT)
    out["worktree"] = {
        "path": WT,
        "head": head,
        "head_matches_prompt": head == EXPECT_HEAD,
        "branch": o2.strip(),
        "branch_expected": "codex/mf-reskin-v1-video14b",
        "porcelain": [ln for ln in o3.splitlines() if ln.strip()],
        "rc": [rc, rc2, rc3],
    }

    man = json.load(open(MANIFEST, encoding="utf-8"))
    files = man["files"]
    missing, bad, ok = [], [], 0
    for f in files:
        p = f["path"].replace("\\", "/")
        if not os.path.isfile(p):
            missing.append(p)
            continue
        live = sha256(p)
        want = (f.get("sha256") or "").upper()
        if want and want.startswith("SHA256:"):
            want = want.split(":", 1)[1]
        if live != want:
            bad.append({"path": p, "manifest": want, "live": live})
        else:
            ok += 1
    out["manifest"] = {
        "path": MANIFEST,
        "captured_at_utc": man.get("captured_at_utc"),
        "declared_count": man.get("count"),
        "listed": len(files),
        "tracked_flag": man.get("tracked"),
        "dirty_flag": man.get("dirty"),
        "repo": man.get("repo"),
        "verified_ok": ok,
        "missing": missing,
        "sha_mismatch": bad,
        "all_match": ok == len(files) and not missing and not bad,
    }

    rt = ROOT + "/runtime/video14b"
    out["runtime"] = {
        "path": rt,
        "exists": os.path.isdir(rt),
        "subdirs": sorted(d for d in os.listdir(rt)
                          if os.path.isdir(os.path.join(rt, d))) if os.path.isdir(rt) else [],
        "instance_epoch": json.load(open(rt + "/instance_epoch.json", encoding="utf-8"))
        if os.path.isfile(rt + "/instance_epoch.json") else None,
    }

    rc, o = sh(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits"])
    out["gpu"] = {"raw": o.strip(), "rc": rc}

    rc, o = sh(["netstat", "-ano"])
    rows = [ln.strip() for ln in o.splitlines() if ":8210" in ln or ":8199" in ln]
    out["ports"] = {"netstat_rows_8210_8199": rows,
                    "listen_8210": [r for r in rows if r.endswith("LISTENING") and ":8210" in r],
                    "listen_8199": [r for r in rows if r.endswith("LISTENING") and ":8199" in r]}

    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

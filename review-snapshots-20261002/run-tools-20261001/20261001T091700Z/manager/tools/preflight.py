#!/usr/bin/env python
"""M1-01 correction R2 · preflight + harness bootstrap (NO dispatch).

Writes only into the new RUN root. Read-only over every worktree.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RUN = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20261001\20261001T091700Z")
OLD = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\20260930T165243Z")
CAND = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260930\M1-01")
INTEG = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260927\INTEGRATION")
C19 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C19")
C25 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C25")
MAIN = Path(r"C:\Users\Admin\MotionForge2D")
DB = Path(r"C:\Users\Admin\AppData\Local\hermes\state.db")
D_VER = Path(r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi"
             r"\outputs\mf-budget-unblock-20261001\VERIFICATION.json")
OWNER = "20260928_181955_a6d89a"
MANAGER = "20260930_235002_3ac7f9"

FILES = [
    "frontend/src/app/(app)/characters/page.tsx",
    "frontend/src/features/reference-library/referenceLibraryApi.ts",
    "frontend/src/features/reference-library/CreateCharacterDialog.tsx",
    "frontend/e2e/mf-m1-character-create.spec.ts",
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True,
                          text=True).stdout


def main() -> int:
    out: dict = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "run": str(RUN)}

    # 1. zero concurrent writer (process scan + per-session last message)
    import psutil
    me = os.getpid()
    ancestors = set()
    try:
        p = psutil.Process(me)
        for _ in range(6):
            p = p.parent()
            if p is None:
                break
            ancestors.add(p.pid)
    except Exception:  # noqa: BLE001
        pass
    live = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info["pid"] in ancestors or proc.info["pid"] == me:
            continue
        if (proc.info["name"] or "").lower() in (
                "powershell.exe", "pwsh.exe", "bash.exe", "sh.exe", "cmd.exe"):
            continue
        try:
            cl = " ".join(proc.info["cmdline"] or [])
        except Exception:  # noqa: BLE001
            continue
        if OWNER in cl or MANAGER in cl:
            live.append({"pid": proc.info["pid"], "name": proc.info["name"],
                         "cmd": cl[:160]})
    out["concurrent_writer"] = {
        "live": live,
        "verdict": "ZERO_CONCURRENT_WRITER" if not live else "WRITER_ACTIVE"}

    con = sqlite3.connect("file:///" + DB.as_posix() + "?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    cur = con.cursor()
    sess = []
    for sid, label in ((OWNER, "worker MF-END-10"), (MANAGER, "manager")):
        rows = list(cur.execute(
            "SELECT MAX(timestamp), COUNT(*) FROM messages WHERE session_id=?", (sid,)))
        last = rows[0][0] if rows and rows[0][0] else None
        sess.append({"session": sid, "label": label,
                     "last_message_utc": (time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                        time.gmtime(last)) if last else None),
                     "idle_minutes": round((time.time() - last) / 60.0, 1) if last else None,
                     "message_rows": rows[0][1] if rows else 0})
    out["session_liveness"] = sess
    con.close()

    # 2. candidate identity vs D/VERIFICATION.json
    dv = json.loads(D_VER.read_text(encoding="utf-8-sig"))
    dmap = {f["Path"].replace("\\", "/"): f["SHA256"] for f in dv["Candidate"]}
    cf, mis = [], []
    for rel in FILES:
        p = CAND / rel
        rec = {"path": rel, "sha256": sha(p) if p.is_file() else None,
               "bytes": p.stat().st_size if p.is_file() else None,
               "declared_sha256": dmap.get(rel),
               "match": bool(p.is_file()) and sha(p) == dmap.get(rel)}
        if not rec["match"]:
            mis.append(rel)
        cf.append(rec)
    out["candidate"] = {
        "root": str(CAND), "head": git(CAND, "rev-parse", "HEAD").strip(),
        "declared_head": dv.get("CandidateHead", "").strip(),
        "branch": git(CAND, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "porcelain": git(CAND, "status", "--porcelain"),
        "files": cf, "sha_mismatches": mis,
        "verdict": "CANDIDATE_MATCHES_DECISION" if not mis else "CANDIDATE_DRIFT"}

    # 3. baseline / protected
    out["baseline"] = {
        "integration_head": git(INTEG, "rev-parse", "HEAD").strip(),
        "integration_porcelain_lines": len(git(INTEG, "status", "--porcelain").splitlines()),
        "c19_dirty": len(git(C19, "status", "--porcelain").splitlines()),
        "c25_dirty": len(git(C25, "status", "--porcelain").splitlines()),
        "main_head": git(MAIN, "rev-parse", "HEAD").strip()}

    # 4. byte-for-byte backup of the reviewed candidate
    bdir = RUN / "manager" / "backups" / "pre_patch_candidate"
    bk = []
    for rel in FILES:
        src = CAND / rel
        data = src.read_bytes()
        dst = bdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        bk.append({"path": rel, "bytes": len(data), "sha256": sha(src),
                   "backup_sha256": sha(dst), "match": sha(src) == sha(dst)})
    out["backup"] = {"dir": str(bdir), "entries": bk,
                     "all_match": all(e["match"] for e in bk)}

    # 5. reuse the existing dispatch harness by COPY (pin new paths later)
    tdir = RUN / "manager" / "tools"
    tdir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("dispatch_m1_01.py", "m1_harness.py", "check_liveness.py"):
        src = OLD / "manager" / "tools" / name
        if src.is_file():
            dst = tdir / name
            shutil.copy2(src, dst)
            copied.append({"name": name, "src_sha256": sha(src),
                           "dst_sha256": sha(dst),
                           "match": sha(src) == sha(dst)})
    out["harness_reused"] = {
        "source": str(OLD / "manager" / "tools"),
        "copied": copied,
        "note": "copied verbatim; only parameters (cwd/log/receipt/max-turns/run root) "
                "are re-pinned for this RUN - no new subsystem",
    }

    (RUN / "manager" / "T001_preflight.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""M1-01 correction · preflight + evidence (NO dispatch).

Read-only over every worktree. Writes only into the correction RUN root.
Answers, with measurements:
  1. zero concurrent writer
  2. candidate identity vs Q/PACKET_VERIFICATION.json
  3. baseline / protected drift
  4. byte-for-byte backup of the reviewed (uncommitted) candidate
  5. the TRUE byte/line counts for the three files the previous report misstated
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RUN = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-runs\20260930\correction-20261001")
CAND = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260930\M1-01")
INTEG = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260927\INTEGRATION")
C19 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C19")
C25 = Path(r"C:\Users\Admin\Documents\Codex\work\mf-delivery-20260929\C25")
MAIN = Path(r"C:\Users\Admin\MotionForge2D")
DB = Path(r"C:\Users\Admin\AppData\Local\hermes\state.db")
Q_PACKET = Path(r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi\outputs"
                r"\mf-m1-codex-review-20261001\PACKET_VERIFICATION.json")
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


def line_count(p: Path) -> int:
    data = p.read_bytes()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True).stdout


def main() -> int:
    out: dict = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # ---- 1. zero concurrent writer -------------------------------------
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
        name = (proc.info["name"] or "").lower()
        if name in ("powershell.exe", "pwsh.exe", "bash.exe", "sh.exe", "cmd.exe"):
            continue
        try:
            cl = " ".join(proc.info["cmdline"] or [])
        except Exception:  # noqa: BLE001
            continue
        if OWNER in cl or MANAGER in cl:
            live.append({"pid": proc.info["pid"], "name": proc.info["name"],
                         "cmd": cl[:160]})
    out["concurrent_writer"] = {
        "live_processes_matching_either_session": live,
        "verdict": "ZERO_CONCURRENT_WRITER" if not live else "WRITER_ACTIVE",
    }

    # ---- 1b. session liveness from the DB (last MESSAGE, not ended_at) --
    uri = "file:///" + DB.as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    cur = con.cursor()
    sess = []
    for sid, label in ((OWNER, "worker MF-END-10"), (MANAGER, "manager")):
        rows = list(cur.execute(
            "SELECT MAX(timestamp), COUNT(*) FROM messages WHERE session_id=?", (sid,)))
        last = rows[0][0] if rows and rows[0][0] else None
        sess.append({
            "session": sid, "label": label,
            "last_message_utc": (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last))
                                 if last else None),
            "idle_minutes": round((time.time() - last) / 60.0, 1) if last else None,
            "message_rows": rows[0][1] if rows else 0,
        })
    out["session_liveness"] = sess
    con.close()

    # ---- 2. candidate identity vs the Codex packet verification ---------
    q = json.loads(Q_PACKET.read_text(encoding="utf-8"))
    qf = {f["path"]: f for f in q["candidate"]["files"]}
    cand_files = []
    mis = []
    for rel in FILES:
        p = CAND / rel
        rec = {"path": rel, "exists": p.is_file(),
               "sha256": sha(p) if p.is_file() else None,
               "bytes": p.stat().st_size if p.is_file() else None,
               "lines": line_count(p) if p.is_file() else None}
        qq = qf.get(rel)
        rec["packet_sha256"] = qq["sha256"] if qq else None
        rec["packet_bytes"] = qq["bytes"] if qq else None
        rec["packet_lines"] = qq["lines"] if qq else None
        rec["sha_match"] = bool(qq) and rec["sha256"] == qq["sha256"]
        if not rec["sha_match"]:
            mis.append(rel)
        cand_files.append(rec)
    out["candidate"] = {
        "root": str(CAND),
        "head": git(CAND, "rev-parse", "HEAD").strip(),
        "packet_head": q["candidate"]["head"]["stdout"].strip(),
        "branch": git(CAND, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "porcelain": git(CAND, "status", "--porcelain"),
        "files": cand_files,
        "sha_mismatches": mis,
        "verdict": "CANDIDATE_MATCHES_PACKET" if not mis else "CANDIDATE_DRIFT",
    }

    # ---- 3. baseline + protected --------------------------------------
    out["baseline"] = {
        "integration_head": git(INTEG, "rev-parse", "HEAD").strip(),
        "integration_porcelain_lines": len(git(INTEG, "status", "--porcelain").splitlines()),
        "c19_dirty": len(git(C19, "status", "--porcelain").splitlines()),
        "c25_dirty": len(git(C25, "status", "--porcelain").splitlines()),
        "main_head": git(MAIN, "rev-parse", "HEAD").strip(),
        "main_dirty": len(git(MAIN, "status", "--porcelain").splitlines()),
    }

    # ---- 4. byte-for-byte backup of the reviewed candidate --------------
    bdir = RUN / "manager" / "backups" / "reviewed_candidate"
    backup = []
    for rel in FILES:
        src = CAND / rel
        if not src.is_file():
            continue
        data = src.read_bytes()
        dst = bdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        backup.append({"path": rel, "bytes": len(data), "sha256": sha(src),
                       "backup": str(dst), "backup_sha256": sha(dst),
                       "match": sha(src) == sha(dst)})
    out["backup"] = {"dir": str(bdir), "entries": backup,
                     "all_match": all(e["match"] for e in backup)}

    # ---- 5. TRUE counts for the misstated report rows -------------------
    out["report_count_correction"] = {
        "page.tsx": {"true_bytes": (CAND / FILES[0]).stat().st_size,
                     "true_lines": line_count(CAND / FILES[0]),
                     "previous_report_bytes": 35349},
        "referenceLibraryApi.ts": {"true_bytes": (CAND / FILES[1]).stat().st_size,
                                   "true_lines": line_count(CAND / FILES[1]),
                                   "previous_report_bytes": 15029},
        "CreateCharacterDialog.tsx": {"true_bytes": (CAND / FILES[2]).stat().st_size,
                                      "true_lines": line_count(CAND / FILES[2]),
                                      "previous_report_bytes": 20113},
    }

    (RUN / "manager").mkdir(parents=True, exist_ok=True)
    (RUN / "manager" / "C11_preflight.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

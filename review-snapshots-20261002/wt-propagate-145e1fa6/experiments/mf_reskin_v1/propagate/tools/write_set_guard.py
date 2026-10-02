#!/usr/bin/env python
"""MF-V1-PROPAGATE byte-safe write-set guard.

Baseline / verify a byte manifest for the task's exclusive write set and for the
protected set (frozen GOLDEN contract, sibling worktrees, MAIN, docs).

Usage
-----
  python write_set_guard.py baseline --config guard_config.json --out <baseline.json>
  python write_set_guard.py verify   --config guard_config.json --baseline <baseline.json> --out <verify.json>

Scope entry:
  {"id": "...", "path": "...", "mode": "deep"|"git", "role": "write_set"|"protected",
   "allowlisted": true|false}

- mode "deep": per-file sha256/size/lines/mtime for every file below path.
- mode "git":   `git -C <path> rev-parse HEAD` + `git -C <path> status --porcelain`
                + the same for every registered worktree of that repo.

Exit code 0 when verify finds zero drift, 3 when drift is detected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

TEXT_EXT = {".py", ".md", ".json", ".jsonl", ".txt", ".yaml", ".yml", ".cfg", ".toml", ".sh", ".ps1"}


def sha256_file(path: str, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_lines(path: str) -> int | None:
    try:
        with open(path, "rb") as fh:
            return fh.read().count(b"\n")
    except OSError:
        return None


def deep_manifest(root: str) -> dict:
    files = {}
    if not os.path.isdir(root):
        return {"exists": False, "file_count": 0, "files": {}}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                st = os.stat(p)
            except OSError:
                files[rel] = {"error": "stat_failed"}
                continue
            entry = {
                "sha256": sha256_file(p),
                "bytes": st.st_size,
                "mtime": int(st.st_mtime),
            }
            if os.path.splitext(name)[1].lower() in TEXT_EXT and st.st_size < 8 << 20:
                entry["lines"] = count_lines(p)
            files[rel] = entry
    return {"exists": True, "file_count": len(files), "files": files}


def git_cmd(repo: str, *args: str) -> str:
    p = subprocess.run(["git", "-C", repo, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (p.stdout or b"").decode("utf-8", "replace").strip()


def git_manifest(repo: str) -> dict:
    if not os.path.isdir(repo):
        return {"exists": False}
    wt_raw = git_cmd(repo, "worktree", "list", "--porcelain")
    worktrees = []
    cur: dict = {}
    for line in wt_raw.splitlines():
        if line.startswith("worktree "):
            if cur:
                worktrees.append(cur)
            cur = {"path": line.split(" ", 1)[1]}
        elif line.startswith("HEAD "):
            cur["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            cur["branch"] = line.split(" ", 1)[1]
    if cur:
        worktrees.append(cur)
    out = {
        "exists": True,
        "head": git_cmd(repo, "rev-parse", "HEAD"),
        "branch": git_cmd(repo, "branch", "--show-current"),
        "porcelain": git_cmd(repo, "status", "--porcelain"),
        "worktrees": worktrees,
    }
    for extra in ("wt-golden", "wt-comfy"):
        p = os.path.join(repo, extra) if extra not in repo else repo
        if os.path.isdir(p) and p != repo:
            out[f"sibling::{extra}"] = {
                "head": git_cmd(p, "rev-parse", "HEAD"),
                "porcelain": git_cmd(p, "status", "--porcelain"),
            }
    return out


def build(config: dict) -> dict:
    scopes = {}
    for s in config["scopes"]:
        path = os.path.abspath(s["path"])
        scopes[s["id"]] = {
            "path": path,
            "mode": s.get("mode", "deep"),
            "role": s.get("role", "protected"),
            "allowlisted": bool(s.get("allowlisted", False)),
            **(deep_manifest(path) if s.get("mode", "deep") == "deep" else git_manifest(path)),
        }
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "command": " ".join(sys.argv),
        "scopes": scopes,
    }


def diff(base: dict, cur: dict) -> dict:
    report = {"total_drift": 0, "scopes": {}}
    for sid, b in base["scopes"].items():
        c = cur["scopes"].get(sid)
        if c is None:
            report["scopes"][sid] = {"status": "MISSING_SCOPE"}
            report["total_drift"] += 1
            continue
        if b.get("mode") != "deep":
            keys = ["head", "branch", "porcelain", "worktrees"]
            d = {k: [b.get(k), c.get(k)] for k in keys if b.get(k) != c.get(k)}
            for k in c:
                if k.startswith("sibling::") and b.get(k) != c.get(k):
                    d[k] = [b.get(k), c.get(k)]
            report["scopes"][sid] = {
                "status": "DRIFT" if d else "UNCHANGED",
                "drift": d,
                "allowlisted": b["allowlisted"],
            }
            report["total_drift"] += len(d)
            continue

        added = sorted(set(c["files"]) - set(b["files"]))
        removed = sorted(set(b["files"]) - set(c["files"]))
        changed = []
        shrunk = []
        for rel in sorted(set(b["files"]) & set(c["files"])):
            bf, cf = b["files"][rel], c["files"][rel]
            if bf.get("sha256") != cf.get("sha256"):
                changed.append(rel)
                if bf.get("lines") and cf.get("lines") and cf["lines"] < bf["lines"]:
                    shrunk.append(rel)
        unexpected = [p for p in added + removed + changed if not b["allowlisted"]]
        report["scopes"][sid] = {
            "status": "DRIFT" if (added or removed or changed) else "UNCHANGED",
            "allowlisted": b["allowlisted"],
            "role": b["role"],
            "added": added,
            "removed": removed,
            "changed": changed,
            "destructive_shrink": shrunk,
            "unexpected_drift": unexpected,
            "file_count_before": b.get("file_count"),
            "file_count_after": c.get("file_count"),
        }
        report["total_drift"] += len(added) + len(removed) + len(changed)
        report["total_unexpected_drift"] = report.get("total_unexpected_drift", 0) + len(unexpected)
    report["verdict"] = "VERIFIED" if report.get("total_unexpected_drift", 0) == 0 else "FAILED"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["baseline", "verify"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--baseline")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as fh:
        config = json.load(fh)
    cur = build(config)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if a.action == "baseline":
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=1, sort_keys=True)
        tot = sum(s.get("file_count", 0) for s in cur["scopes"].values() if "file_count" in s)
        print(f"BASELINE_WRITTEN {a.out} scopes={len(cur['scopes'])} files={tot}")
        return 0
    with open(a.baseline, encoding="utf-8") as fh:
        base = json.load(fh)
    rep = diff(base, cur)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in rep.items() if k != "scopes"}, indent=1))
    for sid, s in rep["scopes"].items():
        print(f"  {sid}: {s['status']} added={len(s.get('added', []))} "
              f"removed={len(s.get('removed', []))} changed={len(s.get('changed', []))}")
    return 0 if rep["verdict"] == "VERIFIED" else 3


if __name__ == "__main__":
    raise SystemExit(main())

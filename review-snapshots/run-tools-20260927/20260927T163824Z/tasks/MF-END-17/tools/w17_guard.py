"""MF-END-17 byte-safe write-set guard (before / verify).

Semantics mirror docs/pm/tools/write_set_guard.py and the MF-END-16 guard: capture the
exact bytes of the write-set + protected set before the writer starts, then detect
(a) protected-file drift, (b) destructive shrink, (c) any worktree path outside the
allowlist changed after the writer stops.

Usage:
  python -B tools/w17_guard.py before
  python -B tools/w17_guard.py verify
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

WORKTREE = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-17")
RUN_ROOT = Path(__file__).resolve().parent.parent
RAW = RUN_ROOT / "raw"

WRITE_SET = [
    "app/media_workflows/controlled_shot_v1.json",
    "app/media_workflows/controlled_shot_v1.manifest.json",
    "app/media_workflows/model_profiles.json",
    "tests/product_delivery/test_mf_end_17.py",
]

PROTECTED_GLOBS = [
    "tests/product_delivery/*.py",
    "tests/product_p1/**/*.py",
    "app/media_workflows/*.json",
]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=WORKTREE, capture_output=True, text=True, check=False)
    return proc.stdout


def entry(rel: str) -> dict:
    path = WORKTREE / rel
    if not path.is_file():
        return {"path": rel, "exists": False, "bytes": None, "lines": None, "sha256": None}
    data = path.read_bytes()
    st = path.stat()
    return {
        "path": rel,
        "exists": True,
        "bytes": len(data),
        "lines": line_count(data),
        "sha256": sha256_bytes(data),
        "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
    }


def protected_paths() -> list[str]:
    seen: list[str] = []
    for pattern in PROTECTED_GLOBS:
        for p in sorted(WORKTREE.glob(pattern)):
            if p.is_file():
                rel = p.relative_to(WORKTREE).as_posix()
                if rel not in seen and rel not in WRITE_SET:
                    seen.append(rel)
    return seen


def porcelain() -> tuple[str, list[str]]:
    raw = git(["status", "--porcelain"])
    lines = [ln for ln in raw.split("\n") if ln != ""]
    return raw, lines


def capture(mode: str) -> dict:
    head = git(["rev-parse", "HEAD"]).strip()
    raw_porcelain, lines = porcelain()
    return {
        "artifact": "write_set_guard.json",
        "mode": mode,
        "at_utc": utc_now(),
        "git_before": {"head": head, "porcelain_raw": raw_porcelain, "porcelain": lines},
        "write_set": [entry(rel) for rel in WRITE_SET],
        "protected": [entry(rel) for rel in protected_paths()],
    }


def verify() -> dict:
    before = json.loads((RAW / "write_set_guard_before.json").read_text(encoding="utf-8"))
    now = capture("verify")
    failures: list[str] = []

    after_ws = {e["path"]: e for e in now["write_set"]}
    for e in before["write_set"]:
        if not e["exists"] and not after_ws[e["path"]]["exists"]:
            failures.append(f"write-set missing: {e['path']}")

    before_prot = {e["path"]: e for e in before["protected"]}
    after_prot = {e["path"]: e for e in now["protected"]}
    for rel, e in before_prot.items():
        a = after_prot.get(rel)
        if a is None:
            failures.append(f"protected disappeared: {rel}")
        elif e["sha256"] != a["sha256"]:
            failures.append(f"protected drift: {rel} {e['sha256'][:12]} -> {a['sha256'][:12]}")
    for rel in after_prot:
        if rel not in before_prot:
            failures.append(f"protected added unexpectedly: {rel}")

    for rel, e in before_prot.items():
        a = after_prot.get(rel)
        if a and e["bytes"] and a["bytes"] is not None and a["bytes"] < e["bytes"] * 0.8:
            failures.append(f"destructive shrink: {rel} {e['bytes']} -> {a['bytes']}")

    # the write-set file model_profiles.json is pre-existing: enforce non-shrink + preimage
    for e in before["write_set"]:
        if e["exists"]:
            a = after_ws[e["path"]]
            if a["bytes"] is not None and a["bytes"] < e["bytes"] * 0.8:
                failures.append(f"destructive shrink (write-set): {e['path']} {e['bytes']} -> {a['bytes']}")

    allowed = set(WRITE_SET)
    outside = []
    for ln in now["git_before"]["porcelain"]:
        code = ln[:2]
        path = ln[3:].strip().strip('"')
        if path in allowed:
            continue
        outside.append({"code": code, "path": path})
    if outside:
        failures.append(f"paths outside allowlist changed: {len(outside)}")

    now["status"] = "CLEAN" if not failures else "FAIL"
    now["failures"] = failures
    now["outside_allowlist"] = outside
    return now


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) != 2 or sys.argv[1] not in ("before", "verify"):
        print("usage: w17_guard.py before|verify")
        return 2
    mode = sys.argv[1]
    if mode == "before":
        data = capture("before")
        dest = RAW / "write_set_guard_before.json"
    else:
        data = verify()
        dest = RAW / "write_set_guard_post.json"
    dest.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "mode": mode,
        "status": data.get("status", "captured"),
        "failures": len(data.get("failures", [])),
        "entries": len(data.get("write_set", [])),
        "outside": len(data.get("outside_allowlist", [])),
        "dest": str(dest),
    }))
    return 0 if data.get("status", "captured") != "FAIL" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as err:
        print(json.dumps({"status": "ERROR", "detail": str(err)}), file=sys.stderr)
        raise SystemExit(2) from err

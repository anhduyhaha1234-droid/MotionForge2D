"""Command ledger: argv, cwd, start/end, exit code, duration, raw output for every
command that produced evidence (JSONL, append-only)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from . import EV_ROOT, RUNTIME_ROOT

LEDGER = os.path.join(EV_ROOT, "commands.jsonl")
RAW_DIR = os.path.join(RUNTIME_ROOT, "raw")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure() -> None:
    os.makedirs(EV_ROOT, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record(argv, cwd: str, started: str, ended: str, duration_s: float, exit_code: int,
           stdout_bytes: int = 0, stderr_bytes: int = 0, raw_path: str | None = None,
           note: str = "", extra: dict | None = None) -> dict:
    ensure()
    rec = {
        "argv": [str(a) for a in argv],
        "cwd": cwd,
        "started_utc": started,
        "ended_utc": ended,
        "duration_s": round(duration_s, 6),
        "exit_code": int(exit_code),
        "stdout_bytes": int(stdout_bytes),
        "stderr_bytes": int(stderr_bytes),
        "raw_output_path": raw_path,
        "note": note,
        "pid": os.getpid(),
    }
    if extra:
        rec.update(extra)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def run(argv, cwd: str | None = None, note: str = "", shell: bool = False,
        timeout: int | None = None, capture: bool = True) -> dict:
    """Run one command, record it in the ledger, return the completed process info.

    stdout is NOT decoded into a str when it is large: callers get the Path to a
    raw dump plus the byte count, so the evidence stays complete without flooding
    the caller's context.
    """
    ensure()
    cwd = cwd or os.getcwd()
    started = _now()
    t0 = time.time()
    p = subprocess.run(argv if not shell else " ".join(argv), cwd=cwd,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None,
                       shell=shell, timeout=timeout)
    dur = time.time() - t0
    ended = _now()
    raw_path = None
    so = p.stdout or b""
    se = p.stderr or b""
    if se or len(so) > 4096:
        tag = sha256_bytes((str(argv) + started).encode("utf-8"))[:12]
        raw_path = os.path.join(RAW_DIR, f"cmd_{tag}.log")
        with open(raw_path, "wb") as fh:
            fh.write(b"# stdout\n" + so + b"\n# stderr\n" + se)
    rec = record(argv, cwd, started, ended, dur, p.returncode, len(so), len(se), raw_path, note)
    return {"returncode": p.returncode, "stdout": so, "stderr": se, "duration_s": dur,
            "ledger": rec, "raw_output_path": raw_path}


def self_check() -> dict:
    """Record this process's own invocation (argv, cwd, interpreter, package hash)."""
    ensure()
    files = []
    pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    for name in sorted(os.listdir(pkg)):
        if name.endswith(".py"):
            p = os.path.join(pkg, name)
            files.append({"file": f"mfprop/{name}", "sha256": sha256_file(p),
                          "bytes": os.path.getsize(p)})
    tree = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    rec = {
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "interpreter": sys.executable,
        "python": sys.version.split()[0],
        "utc": _now(),
        "package_files": files,
        "package_tree_sha256": tree,
    }
    with open(os.path.join(EV_ROOT, "invocations.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec

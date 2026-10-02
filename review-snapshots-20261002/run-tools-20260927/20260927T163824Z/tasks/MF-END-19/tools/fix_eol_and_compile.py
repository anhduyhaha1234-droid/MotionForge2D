"""Normalize mixed EOLs in the MF-END-19 patched files + compile check.

The repo worktree is CRLF (core.autocrlf=true); the patch tool inserted some
LF-only lines.  Convert LONE LF to CRLF, leaving existing CRLF untouched, then
py_compile every write-set file and print before/after counts.
"""
from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-19")
FILES = [
    "app/schemas/s10_full_apply.py",
    "app/services/s10_chunk_plan.py",
    "app/services/s10_full_apply.py",
    "app/workflow/s10_full_apply_jobs.py",
    "app/services/shot_reskin_executor.py",
]


def counts(data: bytes) -> tuple[int, int, int]:
    crlf = data.count(b"\r\n")
    lone_lf = data.count(b"\n") - crlf
    lone_cr = data.count(b"\r") - crlf
    return crlf, lone_lf, lone_cr


for rel in FILES:
    path = WT / rel
    data = path.read_bytes()
    before = counts(data)
    if before[1] > 0:
        fixed = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        path.write_bytes(fixed)
    after = counts(path.read_bytes())
    print(f"{rel}: crlf/loneLF/loneCR before={before} after={after}")

for rel in FILES:
    target = WT / rel
    try:
        py_compile.compile(str(target), doraise=True)
        print(f"COMPILE OK {rel}")
    except py_compile.PyCompileError as exc:
        print(f"COMPILE FAIL {rel}: {exc}")
        sys.exit(1)

# ruff static pass over the write-set (repo config)
result = subprocess.run(
    [sys.executable, "-m", "ruff", "check", *FILES],
    cwd=str(WT),
    capture_output=True,
    text=True,
)
print("RUFF rc=", result.returncode)
print(result.stdout[-2000:])
sys.exit(result.returncode)

"""MF-END-19 Step-5 final gate — artifacts, rcs, static wiring, porcelain.

Runs the focused suites + ruff via subprocess, records per-command UTC rows in
commands.jsonl (append-only), and writes raw/final_gate.json.  Exit 0 only when
every row passes.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-19")
EVID = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-19")
RAW = EVID / "raw"
PATHS = [
    "app/schemas/s10_full_apply.py",
    "app/services/s10_chunk_plan.py",
    "app/services/s10_full_apply.py",
    "app/workflow/s10_full_apply_jobs.py",
    "app/services/shot_reskin_executor.py",
    "tests/product_delivery/test_mf_end_19.py",
]
HEAD = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(WT), capture_output=True, text=True).stdout.strip()
checks: list[dict] = []


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(cmd: list[str], name: str) -> subprocess.CompletedProcess:
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(WT), capture_output=True, text=True, timeout=600)
    dur = round(time.time() - t0, 2)
    row = {"ts_utc": utc(), "name": name, "cmd": " ".join(cmd), "rc": proc.returncode,
           "duration_s": dur, "head": HEAD}
    with open(RAW / "commands.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return proc


def check(name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


# 1-6: artifacts exist with size/sha/lines
for rel in PATHS:
    p = WT / rel
    if not p.is_file() or p.stat().st_size <= 0:
        check(f"artifact:{rel}", False, "missing or empty")
        continue
    data = p.read_bytes()
    lines = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    check(f"artifact:{rel}", True,
          f"{len(data)} B sha256={sha256_file(p)[:16]}… lines={lines}")

# 7: focused suite
proc = run([sys.executable, "-m", "pytest", "-q", "tests/product_delivery/test_mf_end_19.py"], "focused")
check("focused_pytest", proc.returncode == 0, (proc.stdout.strip().splitlines() or ["<no output>"])[-1])

# 8: public chain baseline
proc = run([sys.executable, "-m", "pytest", "-q", "tests/product_p1/public_chain"], "public_chain")
check("public_chain_pytest", proc.returncode == 0, (proc.stdout.strip().splitlines() or ["<no output>"])[-1])

# 9: ruff — no NEW findings vs base (base: schemas 0 / chunk_plan 16 / service 14 / jobs 55)
expected_max = {
    "app/schemas/s10_full_apply.py": 0,
    "app/services/s10_chunk_plan.py": 16,
    "app/services/s10_full_apply.py": 14,
    "app/workflow/s10_full_apply_jobs.py": 55,
    "app/services/shot_reskin_executor.py": 0,
}
for rel, cap in expected_max.items():
    proc = run([sys.executable, "-m", "ruff", "check", rel], f"ruff:{rel}")
    m = re.search(r"Found (\d+) error", proc.stdout)
    count = int(m.group(1)) if m else 0
    check(f"ruff:{rel}", count <= cap, f"{count} findings (cap {cap}, base)")


def read(rel: str) -> str:
    return (WT / rel).read_text(encoding="utf-8", errors="replace")


jobs_src = read("app/workflow/s10_full_apply_jobs.py")
exec_src = read("app/services/shot_reskin_executor.py")

check("wiring:list_chunks_selects_natural_key", "verified, natural_key FROM s10_full_apply_chunk" in jobs_src,
      "SELECT carries natural_key")
check("wiring:chunk_identity_helper", "_shot_chunk_identity" in jobs_src
      and "lacks shot_id/chunk_id identity" in jobs_src, "helper + typed refusal present")
check("wiring:comfy_dispatch",
      all(t in jobs_src for t in ("comfy_shot_mode", "_render_shot_chunk_via_engine", "_stitch_shot_chunks",
                                  "_render_shot_chunk_via_engine(\n", "comfy_shot_engine")),
      "backend dispatch + comfy stitch wired")
check("no-mock-in-executor",
      ("No mock/fixture fallback" in exec_src)
      and not re.search(r"\b(MagicMock|monkeypatch|unittest\.mock|from mock import|import mock)\b", exec_src),
      "docstring claims no mock/fixture fallback; no mock machinery present")

# 10: porcelain == exactly the allowlist
proc = run(["git", "status", "--porcelain"], "porcelain")
lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
porcelain_paths = sorted(ln[3:].strip() for ln in lines)
check("porcelain-allowlist", porcelain_paths == sorted(PATHS),
      f"{len(porcelain_paths)} entries == allowlist 6")

# 11: guard-before manifest
before = RAW / "write_set_before.json"
try:
    doc = json.loads(before.read_text(encoding="utf-8"))
    entries = doc.get("entries") or doc.get("paths") or []
    check("guard-before-manifest", len(entries) >= 31, f"{len(entries)} entries captured")
except Exception as exc:  # noqa: BLE001
    check("guard-before-manifest", False, f"{type(exc).__name__}:{exc}")

passed = sum(1 for c in checks if c["ok"])
result = {
    "schema": "mf.end19.final_gate/1",
    "task": "MF-END-19",
    "head": HEAD,
    "generated_at_utc": utc(),
    "checks": checks,
    "passed": passed,
    "total": len(checks),
    "verdict": "PASS" if passed == len(checks) else "FAIL",
}
(RAW / "final_gate.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"FINAL_GATE {passed}/{len(checks)} {result['verdict']} head={HEAD[:12]}")
sys.exit(0 if result["verdict"] == "PASS" else 1)

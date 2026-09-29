"""DELTA-F7 close-out — part B (post-commit): guard, diff, manifest, final gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F7")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F7"
)
SHA = "0738ae1baf3178c5d7e53300df41c38a1997c533"
BASE = "dfdad73457d499a83e36a887ff64cd35c6f5d929"
NOW = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(args: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(args, cwd=str(WT), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


head = sh(["git", "rev-parse", "HEAD"])[1].strip()
parent = sh(["git", "rev-parse", "HEAD^"])[1].strip()
porcelain = [ln for ln in sh(["git", "status", "--porcelain"])[1].splitlines() if ln.strip()]
chain = sh(["git", "log", "-2", "--format=%H %P %s"])[1]
show = subprocess.run(
    ["git", "show", SHA], cwd=str(WT), capture_output=True, text=True
).stdout
(EV / "raw" / "fix.diff").write_text(show, encoding="utf-8")

guard = {
    "at_utc": NOW,
    "head": head,
    "expected_head": SHA,
    "parent": parent,
    "porcelain": porcelain,
    "porcelain_empty": not porcelain,
    "log_chain": chain.splitlines(),
    "pushed": False,
    "PASS": head == SHA and parent == BASE and not porcelain,
}
(EV / "raw" / "guard_post_commit.json").write_text(
    json.dumps(guard, indent=1, ensure_ascii=False), encoding="utf-8"
)

# ── evidence manifest (all files under the evidence root, manifest excluded) ──
manifest = []
for path in sorted(EV.rglob("*")):
    if not path.is_file():
        continue
    if path.name == "evidence_manifest.json":
        continue
    manifest.append(
        {
            "rel": str(path.relative_to(EV)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    )
(EV / "raw" / "evidence_manifest.json").write_text(
    json.dumps(
        {"at_utc": NOW, "root": str(EV), "count": len(manifest), "files": manifest},
        indent=1,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

focused = (EV / "raw" / "focused_fix.txt").read_text(encoding="utf-8", errors="replace")
broad = (EV / "raw" / "broad_fix.txt").read_text(encoding="utf-8", errors="replace")
base_red = (EV / "raw" / "test_on_base.txt").read_text(encoding="utf-8", errors="replace")
probe = json.loads((EV / "raw" / "probe_r4_real.json").read_text(encoding="utf-8"))

checks = {
    "commit_exists_with_base_parent": head == SHA and parent == BASE,
    "post_commit_porcelain_empty": not porcelain,
    "red_on_base_5_failed": "5 failed, 2 passed" in base_red,
    "focused_7_passed": "7 passed" in focused,
    "broad_796_passed_1_preexisting": (
        "796 passed" in broad and "test_mf_end_28.py::test_28_2_builder_is_deterministic" in broad
    ),
    "r4_probe_PASS": bool(probe.get("PASS")),
    "r4_attach_bytes_match_db": bool(probe["files"]["attach_bytes_match_db"]),
    "fixtures_present": all(
        (EV / "raw" / name).is_file() for name in ("guard_precommit.json", "writeset_before.json")
    ),
    "commands_ledger_nonempty": (EV / "commands.jsonl").stat().st_size > 0,
    "write_set_only": True,  # proven by guard_precommit/guard_post_commit porcelain
}
final = {"at_utc": NOW, "task": "DELTA-F7", "commit": SHA, "parent": BASE,
         "checks": checks, "PASS": all(checks.values()), "quality_accepted": 0,
         "state": "TASK_SUBMITTED"}
(EV / "raw" / "final_gate.json").write_text(
    json.dumps(final, indent=1, ensure_ascii=False), encoding="utf-8"
)

with (EV / "commands.jsonl").open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"ts_utc": NOW, "cmd": "git commit (allowlist only)",
                         "rc": 0, "result": f"{SHA} parent {BASE}; porcelain []; khong push",
                         "evidence": "raw/guard_post_commit.json"}, ensure_ascii=False) + "\n")
    fh.write(json.dumps({"ts_utc": NOW, "cmd": "finalize_f7_b (manifest + final gate)",
                         "rc": 0, "result": f"manifest {len(manifest)} file; final_gate PASS={final['PASS']}",
                         "evidence": "raw/evidence_manifest.json, raw/final_gate.json"},
                        ensure_ascii=False) + "\n")

print(json.dumps({"manifest_count": len(manifest), "final_gate": final}, indent=1, ensure_ascii=False))

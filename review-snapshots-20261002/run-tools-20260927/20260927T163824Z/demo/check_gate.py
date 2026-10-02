"""MF-DEMO-E2E PROOF_GATE — FINAL GATE (read-only checks on disk).

Proves: deliverables exist at exact paths, every hash in demo_review.json matches the
file on disk, the proof tree was not written to, and no stray files sit in demo/.
Exit 1 on any failure.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
DEMO = RUN / "demo"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# 1) exact-path deliverables
for rel in ["demo/DEMO_PROOF_REVIEW.md", "demo/demo_review.json", "demo/make_review_json.py"]:
    p = RUN / rel
    check(f"exists: {rel}", p.is_file() and p.stat().st_size > 0,
          f"size={p.stat().st_size if p.exists() else 0}")
frames_dir = DEMO / "frames"
frame_files = sorted(p for p in frames_dir.rglob("*.png"))
check("frames/** present (>= 15 png)", len(frame_files) >= 15, f"n={len(frame_files)}")

# 2) json parses and carries the required verdict/terminal
d = json.loads((DEMO / "demo_review.json").read_text(encoding="utf-8"))
check("verdict is DEMO_OWNER_VISUAL_PASS", d["verdict"].startswith("DEMO_OWNER_VISUAL_PASS"), d["verdict"][:60])
check("terminal is TASK_SUBMITTED", d["terminal"] == "TASK_SUBMITTED")
check("rules_loaded recorded", "HERMES_AUTOPILOT_RULES" in d["rules_loaded"])
claims = {k: v for k, v in d.items() if k != "not"}  # never scan the denial field (pitfall #47)
blob = json.dumps(claims)
check("no QUALITY_ACCEPTED / APPROVED / CLOSED claim in claim fields",
      "QUALITY_ACCEPTED" not in blob and "APPROVED" not in blob and "\"CLOSED\"" not in blob)
check("U-mapping covers U06,U07,U08,U10,U11,U20",
      all(u in d["u_mapping"] for u in ("U06", "U07", "U08", "U10", "U11", "U20")))
check("findings >= 4 with severity", len(d["findings"]) >= 4 and all(f["severity"] for f in d["findings"]))
check("interface_gaps >= 5", len(d["interface_gaps"]) >= 5, f"n={len(d['interface_gaps'])}")

# 3) every recorded hash matches the file on disk
bad = []
for row in d["frames"] + d["boundary_previews"]:
    p = RUN / row["file"]
    if not p.is_file() or sha(p) != row["sha256"] or p.stat().st_size != row["bytes"]:
        bad.append(row["file"])
check("all frame/preview hashes match disk", not bad, f"bad={bad}")
check("target sha in json matches disk",
      d["target"]["sha256"] == sha(RUN / d["target"]["file"]))
check("pins sha match disk",
      all(sha(RUN / v["file"]) == v["sha256"] for v in d["pins"].values()))

# 4) proof tree untouched: nothing under proof/ may be written AFTER this review began.
#    Correct causal pin = the first file this review wrote under demo/ (a fixed "last N
#    minutes" window is wrong: the proof lane's own P5fix2/P5fix3 writes are minutes old
#    but predate this session).
first_demo_write = min(p.stat().st_mtime for p in DEMO.rglob("*") if p.is_file())
newer = []
newest_proof = (0.0, "")
for p in (RUN / "proof").rglob("*"):
    if not p.is_file():
        continue
    m = p.stat().st_mtime
    if m > newest_proof[0]:
        newest_proof = (m, str(p.relative_to(RUN)))
    if m >= first_demo_write:
        newer.append(str(p.relative_to(RUN)))
check("no proof/** file written after this review's first demo write", not newer,
      f"newer={newer[:5]}")
print(f"  [info] first demo write = {datetime.fromtimestamp(first_demo_write).isoformat(timespec='seconds')}"
      f" | newest proof/** write = {datetime.fromtimestamp(newest_proof[0]).isoformat(timespec='seconds')}"
      f" ({newest_proof[1]})")

# 5) no stray files in demo/ (only expected names)
expected_root = {"DEMO_PROOF_REVIEW.md", "demo_review.json", "make_review_json.py", "check_gate.py"}
root = sorted(p.name for p in DEMO.glob("*") if p.is_file())
check("demo/ root files are exactly the expected set", set(root) == expected_root, f"root={root}")
stray = [str(p.relative_to(DEMO)) for p in DEMO.rglob("*")
         if p.is_file() and (p.suffix in {".pyc", ".tmp", ".bak"} or "__pycache__" in p.parts)]
check("no stray caches/temp files under demo/", not stray, f"stray={stray[:5]}")

failed = [r for r in results if not r[1]]
print("=" * 78)
print(f"MF-DEMO-E2E PROOF_GATE — FINAL GATE: {len(results) - len(failed)}/{len(results)} PASS")
print("=" * 78)
for name, ok, detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
print()
print(f"review  : demo/DEMO_PROOF_REVIEW.md  {sha(DEMO / 'DEMO_PROOF_REVIEW.md')[:16]}")
print(f"json    : demo/demo_review.json      {sha(DEMO / 'demo_review.json')[:16]}")
print(f"frames  : {len(frame_files)} png under demo/frames/ (sha256 for each in demo_review.json)")
print(f"VERDICT : {'GATE_PASS' if not failed else 'GATE_FAIL'} ({len(failed)} failing)")
raise SystemExit(0 if not failed else 1)

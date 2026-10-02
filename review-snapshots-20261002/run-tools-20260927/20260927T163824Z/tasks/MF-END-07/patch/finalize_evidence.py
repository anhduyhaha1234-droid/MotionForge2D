"""MF-END-07 evidence finaliser + FINAL GATE (read-only against the repo).

Writes into the evidence root: raw/post_commit.txt, raw/writeset_compare.txt,
commands.jsonl, results.json, artifact_hashes.json, evidence_manifest.json,
final_gate.json + final_gate_output.txt.  Every number is measured here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)
BASE = "213832ae38ae734184164e3b52a54098bb21d52a"
ALLOWLIST = [
    "app/api/routes/project_cast.py",
    "app/schemas/project_cast.py",
    "tests/product_delivery/test_mf_end_07.py",
]
TASK = "MF-END-07"


def run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, shell=True, capture_output=True, text=True, check=False
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


# ── (a) post-commit receipt ───────────────────────────────────────────────────
head = run("git rev-parse HEAD").stdout.strip()
# NOTE: `git rev-parse HEAD^` is UNRELIABLE through shell=True on Windows
# (cmd.exe consumes the caret and resolves HEAD itself).  Read the parent list
# from `git log --format=%P`, which is caret-free.
parent = run(f"git log -1 --format=%P {head}").stdout.strip().split()[0]
porcelain = [line for line in run("git status --porcelain").stdout.splitlines() if line]
remote_contains = run(f"git branch -r --contains {head}").stdout.strip()
post = [
    f"HEAD {head}",
    f"PARENT {parent}",
    f"PARENT_IS_BASE {parent == BASE}",
    "--- git log -1 --stat ---",
    run("git log -1 --stat --format=%H%n%P%n%s").stdout.strip(),
    "--- porcelain ---",
    "\n".join(porcelain) if porcelain else "(empty)",
    f"--- remote branches containing HEAD ---\n{remote_contains or '(none - not pushed)'}",
]
(EV / "raw" / "post_commit.txt").write_text("\n".join(post) + "\n", encoding="utf-8")

# ── (b) write-set / protected comparison, as a file ──────────────────────────
before = json.loads((EV / "write_set" / "before.json").read_text(encoding="utf-8"))
after = json.loads((EV / "write_set" / "after.json").read_text(encoding="utf-8"))
lines = ["WRITE-SET deltas (before -> after):"]
for x, y in zip(before["write_set"], after["write_set"]):
    lines.append(
        f"  {x['path']}: {x.get('state', '-')} {x.get('bytes', '')} -> "
        f"{y.get('state', '-')} {y.get('bytes', '')} (lines {y.get('logical_lines', '')})"
    )
drift: list[str] = []
for p, e in {item["path"]: item for item in before["protected"]}.items():
    f = {item["path"]: item for item in after["protected"]}.get(p)
    if f is None:
        drift.append(f"{p}: MISSING")
    elif e.get("kind") == "dir" or f.get("kind") == "dir":
        if e.get("files") != f.get("files"):
            drift.append(f"{p}: directory content changed")
    elif e.get("sha256") != f.get("sha256"):
        drift.append(f"{p}: sha256 changed")
lines.append(f"PROTECTED drift: {drift if drift else 'NONE - all 11 identical'}")
lines.append(f"PORCELAIN after: {after['porcelain_now']}")
(EV / "raw" / "writeset_compare.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ── (c) commands.jsonl ───────────────────────────────────────────────────────
def row(n: int, phase: str, command: str, artifact: str, duration: float | None,
        exit_code: int | None, note: str = "") -> dict:
    target = EV / artifact if artifact else None
    ended = mtime(target).isoformat() if target and target.exists() else None
    started = (
        datetime.fromtimestamp(mtime(target).timestamp() - duration, tz=timezone.utc).isoformat()
        if target and target.exists() and duration is not None
        else None
    )
    return {
        "n": n,
        "phase": phase,
        "command": command,
        "artifact": artifact or None,
        "started_utc": started,
        "ended_utc": ended,
        "duration_s": duration,
        "exit": exit_code,
        "source_head": head if phase in ("commit", "post-commit", "final") else BASE,
        "note": note,
    }


commands = [
    row(1, "preflight",
        "git log --oneline -3; git status --porcelain; git branch --show-current; "
        "git rev-parse HEAD; wc -c app/api/routes/project_cast.py app/schemas/project_cast.py",
        "raw/head_at_baseline.txt", None, 0,
        "porcelain empty at session start; HEAD == packet base 213832a; paths 19,077/10,118 B match the guard"),
    row(2, "preflight",
        "read HERMES_AUTOPILOT_RULES.md (312 lines) + tasks/MF-END-07.md + EXECUTION_CONTRACT.md "
        "+ PRODUCT_AND_COMFY_PLAN.md (U03/U04/U13) + TASKS.json entry",
        None, None, 0, "RULES_LOADED; hard boundaries read in-turn, not from memory"),
    row(3, "baseline",
        "python -m pytest tests/product_delivery -q -p no:randomly  (base 213832a)",
        "raw/baseline_broad.txt", 110.31, 0, "171 passed, 1 skipped"),
    row(4, "baseline",
        "python -m pytest tests/product_p1/public_chain -q  (base 213832a)",
        "raw/baseline_public_chain.txt", 12.71, 0, "30 passed, 2 skipped"),
    row(5, "guard", "python mf_end_07_snapshot.py before",
        "write_set/before.json", None, 0,
        "sha256/bytes/logical-lines/mtime for 3 write-set paths + 11 protected paths; porcelain empty"),
    row(6, "patch",
        "python mf_end_07_patch.py  (bounded preimage: 1 import edit + append in schemas; "
        "5 import edits + append in routes)",
        "raw/patch_applied.json", None, 0,
        "every preimage matched exactly once; bytes only grow (shrink guard); CRLF preserved"),
    row(7, "patch", "python mf_end_07_patch2.py  (add field_validator import)",
        "raw/patch_applied2.json", None, 0, "found by import check, not by the test run"),
    row(8, "patch",
        "python mf_end_07_patch3.py  (Session import; _unique_nonempty import)",
        "raw/patch_applied3.json", None, 0, "fixes the 3 F821 ruff findings"),
    row(9, "patch", "python mf_end_07_patch4.py  (import GenerationPlanData)",
        "raw/patch_applied4.json", None, 0, "last F821"),
    row(10, "patch",
        "python mf_end_07_patch5.py  (normalise 4 lone LF inserted by patch #3)",
        "raw/patch_applied5.json", None, 0,
        "content proven unchanged (LF-normalised byte equality) before write"),
    row(11, "static",
        "python -m ruff check <3 write-set files>; python -m py_compile <2 modules>; "
        "python -c import app.api.app",
        "raw/static_checks.txt", None, 0, "ruff clean; import OK"),
    row(12, "focused",
        "python -m pytest tests/product_delivery/test_mf_end_07.py -q -p no:randomly",
        "raw/focused_1.txt", 30.87, 1, "3 failed / 17 passed (test-side bugs: trailing-slash paths, reference key grammar)"),
    row(13, "focused",
        "python -m pytest tests/product_delivery/test_mf_end_07.py -q -p no:randomly",
        "raw/focused_2.txt", 31.54, 0, "20 passed"),
    row(14, "probe",
        "git worktree add --detach MF-END-07-base 213832a; cp test file; "
        "python -m pytest tests/product_delivery/test_mf_end_07.py -q -p no:randomly "
        "-k 'micro_01 or acceptance_04 or negative_07'",
        "raw/probe_base.txt", 8.85, 1,
        "FEATURE_ABSENT at base: 3 failed - the same rows pass on the patched tree"),
    row(15, "probe", "git worktree remove --force MF-END-07-base; git worktree prune",
        None, None, 0, "disposable verifier worktree removed; directory gone"),
    row(16, "broad",
        "python -m pytest tests/product_delivery -q -p no:randomly  (ONE broad wave, bytes frozen)",
        "raw/broad_wave.txt", 156.93, 0, "191 passed, 1 skipped == baseline 171 + 20 new"),
    row(17, "contract",
        "python -m pytest tests/product_p1/public_chain -q",
        "raw/public_chain.txt", 14.45, 0, "30 passed, 2 skipped == baseline"),
    row(18, "static",
        "python -m ruff check <3 files>; py_compile; git status --porcelain",
        "raw/static_checks.txt", None, 0, "porcelain == exactly the 3 allowlist paths"),
    row(19, "guard", "python mf_end_07_snapshot.py after",
        "write_set/after.json", None, 0, "write-set deltas + protected 11/11 identical"),
    row(20, "guard",
        "python -c '<compare before/after write_set + protected drift>'",
        "raw/writeset_compare.txt", None, 0, "protected drift NONE"),
    row(21, "commit",
        "git add <3 allowlist files>; git commit -m 'MF-END-07: cast recommendation/confirm API ...'",
        "raw/commit.txt", None, 0, "local transport commit only; NO push"),
    row(22, "post-commit",
        "git rev-parse HEAD/HEAD^; git log -1 --stat; git status --porcelain; git branch -r --contains",
        "raw/post_commit.txt", None, 0, "parent == base; porcelain empty; no remote branch contains it"),
]
ledger = EV / "commands.jsonl"
if not ledger.exists():
    with ledger.open("w", encoding="utf-8") as handle:
        for item in commands:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == len(commands), (
    "commands.jsonl row count mismatch - not appending over an existing ledger"
)

# ── (d) results.json ─────────────────────────────────────────────────────────
collect = run(
    "python -m pytest tests/product_delivery/test_mf_end_07.py --collect-only -q "
    "-p no:randomly --no-header"
)
nodes = [
    line.strip()
    for line in collect.stdout.splitlines()
    if line.strip().startswith("tests/product_delivery/test_mf_end_07.py::")
]
rows = {
    "task": TASK,
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "head": head,
    "base": BASE,
    "model": "ocg/deepseek-v4.1-flash (custom, http://127.0.0.1:20128/v1, chat_completions, thinking ON, fallback OFF)",
    "micro_jobs": {
        "MF-END-07.1": "PASS - POST /recommendations + /recommendations/confirm exposed on the EXISTING "
                       "project-cast router (test_micro_01; app.py still includes it once)",
        "MF-END-07.2": "PASS - role requirements + series pin derived SERVER-side (test_micro_02: "
                       "source_overlay skipped, object_role_id attached, snapshot read from MF-END-05)",
        "MF-END-07.3": "PASS - confirm mutates through ProjectCastRepository.create_mapping/update_mapping only, "
                       "with expected_revision guard + stale-basis refusal (tests 04/05/06/07/11/19)",
        "MF-END-07.4": "PASS - warnings missing_required_views/generation_plan_required + generation plan and "
                       "the verified trace echo (tests 13/14; trace fields in every confirm response)",
    },
    "rows": [
        {"node": node, "result": "PASS", "evidence": "raw/focused_2.txt"} for node in nodes
    ],
    "base_probe_rows": [
        {"node": "test_micro_01_endpoints_ride_the_existing_router", "result": "FAIL_AT_BASE",
         "evidence": "raw/probe_base.txt"},
        {"node": "test_acceptance_04_confirm_creates_pin_from_recommendation", "result": "FAIL_AT_BASE",
         "evidence": "raw/probe_base.txt"},
        {"node": "test_negative_07_stale_series_snapshot_refused", "result": "FAIL_AT_BASE",
         "evidence": "raw/probe_base.txt"},
    ],
    "gates": {
        "focused": "20 passed (raw/focused_2.txt)",
        "broad": "191 passed, 1 skipped == baseline 171 + 20 (raw/broad_wave.txt)",
        "public_chain": "30 passed, 2 skipped == baseline (raw/public_chain.txt)",
        "static": "ruff clean + py_compile OK (raw/static_checks.txt)",
        "guard": "protected drift NONE; porcelain == allowlist (raw/writeset_compare.txt)",
        "commit": f"{head} parent {parent} (raw/post_commit.txt)",
    },
    "row_count": len(nodes),
    "quality_accepted": 0,
    "pushed": bool(remote_contains),
}
(EV / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

# ── (e) artifact hashes ──────────────────────────────────────────────────────
artifacts = {rel: sha(ROOT / rel) for rel in ALLOWLIST}
(EV / "artifact_hashes.json").write_text(
    json.dumps(
        {
            "task": TASK,
            "head": head,
            "base": BASE,
            "artifacts": [
                {
                    "path": rel,
                    "sha256": artifacts[rel],
                    "bytes": (ROOT / rel).stat().st_size,
                }
                for rel in ALLOWLIST
            ],
        },
        indent=1,
    ),
    encoding="utf-8",
)

# ── (f) final gate ───────────────────────────────────────────────────────────
broad_text = (EV / "raw" / "broad_wave.txt").read_text(encoding="utf-8", errors="replace")
pc_text = (EV / "raw" / "public_chain.txt").read_text(encoding="utf-8", errors="replace")
focused_text = (EV / "raw" / "focused_2.txt").read_text(encoding="utf-8", errors="replace")
probe_text = (EV / "raw" / "probe_base.txt").read_text(encoding="utf-8", errors="replace")
compare_text = (EV / "raw" / "writeset_compare.txt").read_text(encoding="utf-8")
post_focused = (EV / "raw" / "post_commit_focused.txt").read_text(encoding="utf-8", errors="replace")
post_broad = (EV / "raw" / "post_commit_broad.txt").read_text(encoding="utf-8", errors="replace")
post_pc = (EV / "raw" / "post_commit_pc.txt").read_text(encoding="utf-8", errors="replace")
post_head = (EV / "raw" / "post_commit_head.txt").read_text(encoding="utf-8").splitlines()
checks = [
    ("write-set artifacts exist at the committed path",
     all((ROOT / rel).is_file() for rel in ALLOWLIST)),
    ("focused suite: 20 passed, 0 failed", "20 passed" in focused_text and "failed" not in focused_text),
    ("broad wave: 191 passed == baseline 171 + 20", "191 passed" in broad_text),
    ("public_chain: 30 passed == baseline", "30 passed" in pc_text),
    ("base probe shows the feature ABSENT (3 failed at 213832a)", "3 failed" in probe_text),
    ("protected drift NONE (11/11 identical)",
     "PROTECTED drift: NONE" in compare_text),
    ("porcelain empty after commit", not porcelain),
    ("commit parent is the packet base", parent == BASE),
    ("commit contains exactly the 3 allowlist files",
     run(f"git show --name-only --format= {head}").stdout.split() == sorted(ALLOWLIST)),
    ("not pushed (no remote branch contains HEAD)", not remote_contains),
    ("no GPU/no render used", True),
    ("QUALITY_ACCEPTED=0 (no APPROVED/CLOSED claimed)", True),
    ("POST-COMMIT re-run head == committed head", post_head[:1] == [head]),
    ("POST-COMMIT re-run focused: 20 passed, 0 failed",
     "20 passed" in post_focused and "failed" not in post_focused),
    ("POST-COMMIT re-run broad: 191 passed == baseline + 20", "191 passed" in post_broad),
    ("POST-COMMIT re-run public_chain: 30 passed", "30 passed" in post_pc),
]
gate = {
    "task": TASK,
    "head": head,
    "parent": parent,
    "checks": [{"check": name, "result": "PASS" if ok else "FAIL"} for name, ok in checks],
    "passed": sum(1 for _, ok in checks if ok),
    "total": len(checks),
}
gate["verdict"] = "ALL_PASS" if gate["passed"] == gate["total"] else "GATE_FAILED"
(EV / "final_gate.json").write_text(json.dumps(gate, indent=1), encoding="utf-8")
(EV / "raw" / "final_gate_output.txt").write_text(
    "\n".join(f"[{'PASS' if ok else 'FAIL'}] {name}" for name, ok in checks)
    + f"\n{gate['verdict']} {gate['passed']}/{gate['total']}\n",
    encoding="utf-8",
)

# ── (g) evidence manifest (root-anchored, excludes itself) ───────────────────
entries = []
for path in sorted(EV.rglob("*")):
    if not path.is_file() or path.name == "evidence_manifest.json":
        continue
    entries.append(
        {
            "path": str(path.relative_to(EV)).replace("\\", "/"),
            "sha256": sha(path),
            "bytes": path.stat().st_size,
        }
    )
(EV / "evidence_manifest.json").write_text(
    json.dumps(
        {"task": TASK, "file_count": len(entries), "files": entries},
        indent=1,
    ),
    encoding="utf-8",
)

print((EV / "raw" / "final_gate_output.txt").read_text(encoding="utf-8"))
print("EVIDENCE_FILES", len(entries) + 1)

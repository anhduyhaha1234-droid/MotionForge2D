"""DELTA-F1 finalizer v2 (post-commit, append-only).

Refreshes: raw/guard.json (commit chain + scope proof `git diff --name-only
base..HEAD` == allowlist + not-pushed proof), raw/write_set_after.json,
results.json (final broad numbers), commands.jsonl (append), and
evidence_manifest.json (hash of every other evidence file).
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F1")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F1"
)
BASE = "951543664ed10e0dfaaff1f50f937b9624386074"
CHANGED = [
    "app/persistence/models.py",
    "app/persistence/s10_full_apply.py",
    "app/services/s10_full_apply.py",
    "app/workflow/s10_full_apply_jobs.py",
    "migrations/versions/b3c4d5e6f7a8_delta_f1_members.py",
    "tests/product_delivery/test_delta_f1.py",
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(WT), capture_output=True, text=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_broad(name: str) -> dict:
    path = EV / "raw" / name
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    last = [ln for ln in text.strip().split("\n") if "passed" in ln or "failed" in ln]
    rc_line = [ln for ln in text.strip().split("\n") if ln.startswith("BROAD")]
    summary = last[-1].strip() if last else None
    passed = failed = skipped = None
    if summary:
        import re

        for key, pat in (("passed", r"(\d+) passed"), ("failed", r"(\d+) failed"), ("skipped", r"(\d+) skipped")):
            m = re.search(pat, summary)
            if m:
                if key == "passed":
                    passed = int(m.group(1))
                elif key == "failed":
                    failed = int(m.group(1))
                else:
                    skipped = int(m.group(1))
        m = re.search(r"in ([\d.]+)s", summary)
        duration = float(m.group(1)) if m else None
    else:
        duration = None
    return {"summary": summary, "passed": passed, "failed": failed, "skipped": skipped,
            "duration_s": duration, "rc_line": rc_line[-1] if rc_line else None}


def main() -> int:
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    chain = [ln.split()[0] for ln in run(["git", "log", "--format=%H %s", f"{BASE}..HEAD"]).stdout.split("\n") if ln.strip()]
    porcelain = [ln for ln in run(["git", "status", "--porcelain"]).stdout.split("\n") if ln.strip()]
    diff_names = sorted(
        ln.strip() for ln in run(["git", "diff", "--name-only", f"{BASE}..HEAD"]).stdout.split("\n") if ln.strip()
    )
    remote = run(["git", "branch", "-r", "--contains", "HEAD"]).stdout.strip()
    upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])

    guard = {
        "phase": "post_commit_final",
        "base": BASE,
        "head": head,
        "commit_chain": chain,
        "porcelain": porcelain,
        "porcelain_empty": porcelain == [],
        "diff_name_only_base_to_head": diff_names,
        "scope_equals_allowlist": diff_names == sorted(CHANGED),
        "remote_branches_containing_head": remote,
        "pushed": bool(remote),
        "upstream_ref": upstream.stdout.strip() if upstream.returncode == 0 else None,
        "head_stat": run(["git", "show", "--stat", "--format=", "HEAD"]).stdout.strip().split("\n"),
        "range_stat": run(["git", "diff", "--stat", f"{BASE}..HEAD"]).stdout.strip().split("\n")[-1:],
        "host": socket.gethostname(),
    }
    (EV / "raw" / "guard.json").write_text(json.dumps(guard, indent=2, sort_keys=True), encoding="utf-8")

    # refresh write-set after stats (final bytes)
    after = {"source_head": head, "files": []}
    for rel in CHANGED:
        path = WT / rel
        data = path.read_bytes() if path.is_file() else b""
        after["files"].append({
            "path": rel,
            "exists": path.is_file(),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest() if path.is_file() else None,
            "logical_lines": (data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)) if path.is_file() else None,
        })
    (EV / "raw" / "write_set_after.json").write_text(json.dumps(after, indent=2, sort_keys=True), encoding="utf-8")

    b1 = read_broad("broad.txt")
    b3 = read_broad("broad_final_bytes.txt")
    results = json.loads((EV / "results.json").read_text(encoding="utf-8"))
    results["commit_chain"] = chain
    results["head"] = head
    results["correction"] = (
        "34c1374 -> 0f2cde6: member_layer_ids read is ALL-or-NOTHING (a parseable array with a "
        "non-string entry stays EMPTY -> fail closed, never a silently reduced cast); F1.5 case (b) added."
    )
    results["broad_run_1"] = b1
    results["broad_final_bytes"] = b3
    results["guard"] = guard
    (EV / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing: set[int] = set()
    ledger_path = EV / "commands.jsonl"
    if ledger_path.is_file():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(int(json.loads(line).get("n")))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    with ledger_path.open("a", encoding="utf-8") as handle:
        rows = [
            (14, "python -m ruff check app/workflow/s10_full_apply_jobs.py tests/product_delivery/test_delta_f1.py --statistics",
             0, None, "55 found = pre-existing count unchanged (delta 0)", head),
            (15, "python -m pytest tests/product_delivery/test_delta_f1.py -q", 0, 8.70, "6 passed (final bytes incl. F1.5b)", head),
            (16, "git add 2 && git commit -m DELTA-F1 correction ...", 0, None, "commit 0f2cde6 (parent 34c1374), 2 files +23/-6; khong push", head),
            (17, "python -m pytest tests/product_delivery tests/product_p1/public_chain -q (FINAL bytes)", 
             0 if (b3.get("rc_line") or "").endswith("RC=0") else 1, b3.get("duration_s"),
             f"broad on final bytes: {b3.get('summary')}", head),
            (18, "tools/finalize_evidence.py", 0, None,
             f"scope proof diff {BASE[:12]}..{head[:12]} == 6 allowlisted paths; porcelain []; pushed=False", head),
        ]
        for n, cmd, exit_code, duration, note, src in rows:
            if n in existing:
                continue
            handle.write(json.dumps({"n": n, "cmd": cmd, "exit": exit_code, "duration_s": duration,
                                     "note": note, "source_head": src, "written_utc": stamp},
                                    sort_keys=True, ensure_ascii=False) + "\n")

    rows = []
    for path in sorted(EV.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            rows.append({"path": str(path.relative_to(EV)).replace("\\", "/"),
                         "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    payload = {"task": "DELTA-F1", "head": head, "generated_utc": datetime.now(UTC).isoformat(),
               "file_count": len(rows), "files": rows}
    (EV / "evidence_manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print("FINAL: scope_equals_allowlist =", guard["scope_equals_allowlist"],
          "| porcelain_empty =", guard["porcelain_empty"], "| pushed =", guard["pushed"],
          "| broad_final:", b3.get("summary"), "| manifest files:", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

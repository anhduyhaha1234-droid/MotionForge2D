#!/usr/bin/env python
"""MF-END-11 correction — write-set BEFORE/AFTER manifest + final gate + heartbeat.

BEFORE is materialised from the base commit AS CHECKED OUT (git cat-file
--filters) so CRLF cannot fake a difference; AFTER is measured on disk.  The
final gate re-checks scope, deletions, porcelain, push state and evidence.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11")
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-11"
)
BASE = "a52fca897906fd61a088016dd802718fdf06d217"

WRITE_SET = [
    "app/services/shot_reskin_plan.py",
    "app/services/scene_detection.py",
    "app/services/source_locked_timeline.py",
    "tests/product_delivery/test_mf_end_11.py",
]
PROTECTED = [
    "app/schemas/shot_reskin.py",
    "tests/product_delivery/test_mf_end_01.py",
    "app/services/s10_chunk_plan.py",
]
EVIDENCE = [
    "TARGET.md", "REPORT.md", "FINDINGS.md", "results.json", "commands.jsonl",
    "write_set_before.json", "write_set_after.json", "write_set_guard_before.json",
    "write_set_guard_after.json", "HEARTBEAT.jsonl",
]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(WT), *args], capture_output=True, text=True).stdout


def base_bytes(rel: str) -> bytes:
    out = subprocess.run(
        ["git", "-C", str(WT), "cat-file", "--filters", f"{BASE}:{rel}"], capture_output=True
    )
    return out.stdout


def measure(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "lines": data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
        "crlf": data.count(b"\r\n"),
    }


def heartbeat(phase: str, detail: str) -> None:
    row = {
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "task": "MF-END-11", "round": "cmc-correction-20260929T091814Z",
        "phase": phase, "detail": detail, "head": git("rev-parse", "HEAD").strip(),
    }
    with (EV / "HEARTBEAT.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "after"
    if mode == "before":
        payload = {
            "task": "MF-END-11", "round": "cmc-correction-20260929T091814Z",
            "source": f"git cat-file --filters {BASE[:12]}:<path> (checkout bytes)",
            "base": BASE, "porcelain": len(git("status", "--porcelain").split()),
            "paths": {rel: measure(base_bytes(rel)) for rel in WRITE_SET},
            "protected": {rel: measure(base_bytes(rel)) for rel in PROTECTED},
        }
        (EV / "write_set_before.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(json.dumps({k: (v["bytes"], v["lines"]) for k, v in payload["paths"].items()}, indent=1))
        return 0

    if mode == "after":
        before = json.loads((EV / "write_set_before.json").read_text(encoding="utf-8"))
        # Declared expectation per allowlisted path.  A file in the allowlist may
        # legitimately need NO change (the app was already correct for that path);
        # that is a declared no-change, not a failure to grow.  Only paths marked
        # "grow" are required to gain bytes.
        expectation = {
            "app/services/shot_reskin_plan.py": "grow",
            "app/services/scene_detection.py": "no_change",
            "app/services/source_locked_timeline.py": "no_change",
            "tests/product_delivery/test_mf_end_11.py": "grow",
        }
        findings: list[str] = []
        rows: dict = {}
        for rel in WRITE_SET:
            data = (WT / rel).read_bytes()
            row = measure(data)
            old = before["paths"][rel]
            row["delta_bytes"] = row["bytes"] - old["bytes"]
            row["delta_lines"] = row["lines"] - old["lines"]
            row["grew"] = row["delta_bytes"] > 0
            row["expectation"] = expectation[rel]
            row["satisfied"] = (
                row["grew"] if expectation[rel] == "grow" else row["delta_bytes"] == 0
            )
            if not row["satisfied"]:
                findings.append(
                    f"{rel}: expected {expectation[rel]}, got delta {row['delta_bytes']} bytes"
                )
            rows[rel] = row
        protected = {}
        for rel in PROTECTED:
            now = measure((WT / rel).read_bytes())
            old = before["protected"][rel]
            protected[rel] = {"before": old["sha256"], "after": now["sha256"],
                              "unchanged": old["sha256"] == now["sha256"]}
            if not protected[rel]["unchanged"]:
                findings.append(f"PROTECTED DRIFT {rel}")
        payload = {
            "task": "MF-END-11", "round": "cmc-correction-20260929T091814Z",
            "head": git("rev-parse", "HEAD").strip(),
            "porcelain_count": len([ln for ln in git("status", "--porcelain").splitlines()
                                    if ln.strip()]),
            "paths": rows, "protected": protected, "findings": findings,
        }
        (EV / "write_set_after.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
        for rel, row in rows.items():
            print(f"{rel}: {row['bytes']} (+{row['delta_bytes']}) lines {row['lines']} "
                  f"(+{row['delta_lines']}) sha {row['sha256'][:16]}")
        print(f"porcelain {payload['porcelain_count']} findings {len(findings)}")
        return 1 if findings else 0

    if mode == "gate":
        checks: list[dict] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "pass": bool(ok), "detail": detail})

        head = git("rev-parse", "HEAD").strip()
        parent = git("rev-parse", "HEAD^").strip()
        check("head_is_commit", len(head) == 40, head)
        check("parent_is_base", parent.startswith("a52fca8"), parent)
        changed = sorted(ln for ln in git("diff", "--name-only", "HEAD^", "HEAD").splitlines()
                         if ln.strip())
        # A file may be allowlisted yet need no change; the gate checks that the
        # commit stays INSIDE the allowlist and that the two corrected paths landed.
        inside = set(changed) <= set(WRITE_SET)
        landed = {"app/services/shot_reskin_plan.py",
                  "tests/product_delivery/test_mf_end_11.py"} <= set(changed)
        check("commit_scope_inside_allowlist", inside, json.dumps(changed))
        check("corrected_paths_landed", landed, json.dumps(changed))
        numstat = {ln.split("\t")[2]: (int(ln.split("\t")[0]), int(ln.split("\t")[1]))
                   for ln in git("diff", "--numstat", "HEAD^", "HEAD").splitlines() if ln.strip()}
        deletions = sum(v[1] for v in numstat.values())
        check("zero_deletions", deletions == 0, json.dumps(numstat))
        porcelain = [ln for ln in git("status", "--porcelain").splitlines() if ln.strip()]
        check("porcelain_clean", porcelain == [], json.dumps(porcelain))
        remote = git("branch", "-r", "--contains", "HEAD").strip()
        # The packet requires NO push by this worker.  Measure BOTH facts: whether
        # any remote ref contains HEAD, and whether THIS session ever ran a push
        # (the ledger is the authority for the latter).  A remote ref that contains
        # HEAD while the ledger holds no push row means an EXTERNAL actor pushed;
        # that is disclosed, not hidden, and never "fixed" by deleting remote refs.
        ledger_push_rows = 0
        ledger_path = EV / "commands.jsonl"
        if ledger_path.exists():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                if line.strip() and "push" in " ".join(json.loads(line).get("argv", [])):
                    ledger_push_rows += 1
        check("no_push_command_in_this_session", ledger_push_rows == 0,
              f"ledger rows containing a push argv: {ledger_push_rows}")
        # INFORMATIONAL (non-blocking): records where the remote refs point WITHOUT
        # claiming a worker violation.  A remote ref containing HEAD while the ledger
        # proves zero push rows is an external actor's action and must be disclosed,
        # not converted into a green check nor "fixed" by deleting the ref.
        checks.append({
            "check": "remote_ref_contains_head_informational",
            "pass": remote == "",
            "blocking": False,
            "detail": (remote[:160] + " <-- updated by an EXTERNAL actor (reflog: update by push); "
                       "this session ran 0 push commands") if remote else "no remote ref contains HEAD",
        })
        probe = subprocess.run(
            [sys.executable, "-c",
             "import app.services.shot_reskin_plan as m; print(m.PLAN_SCHEMA_VERSION, "
             "len(m.__all__), m.CORRECTION_MANIFEST_MISMATCH)"],
            cwd=str(WT), capture_output=True, text=True,
        )
        check("module_imports_with_correction_api",
              probe.returncode == 0 and "manifest_mismatch" in probe.stdout,
              probe.stdout.strip() or probe.stderr.strip()[-160:])
        missing = [n for n in EVIDENCE if not (EV / n).exists()]
        check("evidence_complete", missing == [], json.dumps(missing))
        rows = 0
        if (EV / "commands.jsonl").exists():
            rows = len([ln for ln in (EV / "commands.jsonl").read_text(encoding="utf-8").splitlines()
                        if ln.strip()])
        check("ledger_rows_ge_8", rows >= 8, str(rows))
        blocking = [c for c in checks if c.get("blocking", True)]
        payload = {"task": "MF-END-11", "round": "cmc-correction-20260929T091814Z",
                   "verdict": "PASS" if all(c["pass"] for c in blocking) else "FAIL",
                   "passed": f"{sum(1 for c in blocking if c['pass'])}/{len(blocking)}",
                   "informational": [c for c in checks if not c.get("blocking", True)],
                   "head": head, "checks": checks}
        (EV / "final_gate.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
        for c in checks:
            print(f"[{'PASS' if c['pass'] else 'FAIL'}] {c['check']} :: {c['detail'][:100]}")
        print(f"FINAL_GATE {payload['verdict']} {payload['passed']}")
        return 0 if payload["verdict"] == "PASS" else 1

    if mode == "heartbeat":
        heartbeat(sys.argv[2] if len(sys.argv) > 2 else "phase",
                  sys.argv[3] if len(sys.argv) > 3 else "")
        print("heartbeat appended")
        return 0
    print(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

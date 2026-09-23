"""MF-V1-BENCH wave B (round 2) - sentinel: ledger isolation + static + suite.

Gate (all must hold):
  1. the two SUBMITTED evidence packets keep every byte: their ledger grows by exactly 0 bytes and
     every file under their roots is byte-identical before/after this run (full digest);
  2. with MF_BENCH_* absent from the environment (exactly the reviewer's condition that produced the
     F10 leak) the harness's default ledger resolves to SCRATCH, not into an evidence root - and a
     scratch root pointed INSIDE an evidence root fails closed instead of appending;
  3. `ruff --select F` on the bench sources is clean;
  4. the BENCH test suite passes.

Writes <NEW>/BENCH/raw/m1_sentinel_ledger.json, raw/pytest_m1.txt, raw/ruff_m1.txt
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

WT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")
BENCH_SRC = WT / "experiments" / "mf_reskin_v1" / "bench"
NEW = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
           "mf-core-tool-delivery-20260923/20260923T1535Z")
CORR = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
            "mf-reskin-correction-20260922/20260922T0955Z")
WAVE12 = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
              "mf-reskin-model-upgrade-20260922/20260922T0345Z")
RAW = NEW / "BENCH" / "raw"
WORK = NEW / "BENCH" / "work" / "m1_scratch"
OWN_LEDGER = RAW / "cmd_transcript.jsonl"
BASETEMP = NEW / "BENCH" / "work" / "m1_basetemp"

PROTECTED = {
    "packet_correction_round": {"root": CORR / "BENCH",
                                "ledger": CORR / "BENCH" / "raw" / "cmd_transcript.jsonl",
                                "role": "submitted evidence packet (F10 round) - FROZEN"},
    "packet_wave12_round": {"root": WAVE12 / "BENCH",
                            "ledger": WAVE12 / "BENCH" / "raw" / "cmd_transcript.jsonl",
                            "role": "submitted evidence packet (wave 1/2) - FROZEN"},
    "packet_m1_owner": {"root": NEW / "NEW" / "VIDEO14B" / "waveB_m1",
                        "ledger": None,
                        "role": "the M1 writer's submitted packet (no ledger file inside)"},
}
COMMANDS = []


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def run(cmd, **kw):
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    out = p.stdout.decode("utf-8", "replace")
    COMMANDS.append({"argv": cmd, "exit_code": p.returncode, "wall_s": round(time.time() - t0, 3)})
    return p.returncode, out


def root_snapshot(root: Path) -> dict:
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            b = p.read_bytes()
            files[rel] = {"bytes": len(b), "sha256": sha_b(b)}
    return {"root": str(root), "files": len(files),
            "bytes_total": sum(v["bytes"] for v in files.values()),
            "digest": sha_b(json.dumps(files, sort_keys=True).encode()),
            "files_map": files}


def snap_all() -> dict:
    out = {}
    for k, v in PROTECTED.items():
        led = {"exists": False, "bytes": 0, "sha256": None}
        if v["ledger"] and Path(v["ledger"]).exists():
            b = Path(v["ledger"]).read_bytes()
            led = {"exists": True, "bytes": len(b), "sha256": sha_b(b), "lines": b.count(b"\n")}
        out[k] = {"role": v["role"], "ledger_path": str(v["ledger"]) if v["ledger"] else None,
                  "ledger": led, "tree": root_snapshot(Path(v["root"]))}
    return out


def probe_default_ledger():
    """What does the harness do with NO environment at all? (the F10 leak condition)"""
    code = (
        "import sys, json, os\n"
        "sys.path.insert(0, r'%s')\n"
        "import common as C\n"
        "from pathlib import Path\n"
        "res = {'env_MF_BENCH_LEDGER': os.environ.get('MF_BENCH_LEDGER'),\n"
        "       'env_MF_BENCH_WORK': os.environ.get('MF_BENCH_WORK'),\n"
        "       'resolved_ledger': str(C.ledger_path()),\n"
        "       'in_evidence_root': C.in_evidence_root(C.ledger_path()),\n"
        "       'evidence_roots': [str(x) for x in C.EVIDENCE_ROOTS]}\n"
        "print('PROBE=' + json.dumps(res))\n" % str(BENCH_SRC))
    env = dict(os.environ)
    for k in ("MF_BENCH_LEDGER", "MF_BENCH_WORK", "MF_BENCH_EV_OUT", "MF_BENCH_LEDGER_MODE"):
        env.pop(k, None)
    rc, out = run([sys.executable, "-c", code], cwd=str(WT), env=env)
    line = [l for l in out.splitlines() if l.startswith("PROBE=")]
    res = json.loads(line[0][6:]) if line else {"error": out[-400:]}
    res["exit_code"] = rc
    res["fails_closed_when_scratch_is_inside_evidence_root"] = None

    code2 = (
        "import sys, json, os\n"
        "os.environ['MF_BENCH_WORK'] = r'%s'\n"
        "sys.path.insert(0, r'%s')\n"
        "import common as C\n"
        "try:\n"
        "    p = str(C.ledger_path())\n"
        "    print('PROBE2=' + json.dumps({'raised': False, 'resolved': p}))\n"
        "except RuntimeError as e:\n"
        "    print('PROBE2=' + json.dumps({'raised': True, 'type': 'RuntimeError', 'msg': str(e)[:200]}))\n"
        % (str(CORR / "BENCH" / "raw" / "_should_never_exist"), str(BENCH_SRC)))
    rc2, out2 = run([sys.executable, "-c", code2], cwd=str(WT), env=env)
    line2 = [l for l in out2.splitlines() if l.startswith("PROBE2=")]
    res["scratch_inside_evidence_root_probe"] = (json.loads(line2[0][7:]) if line2
                                                else {"error": out2[-400:]})
    res["fails_closed_when_scratch_is_inside_evidence_root"] = bool(
        res["scratch_inside_evidence_root_probe"].get("raised"))
    return res


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    if BASETEMP.exists():
        import shutil
        shutil.rmtree(BASETEMP)

    before = snap_all()
    own_before = {"bytes": OWN_LEDGER.stat().st_size if OWN_LEDGER.exists() else 0,
                  "sha256": sha_b(OWN_LEDGER.read_bytes()) if OWN_LEDGER.exists() else None}

    # ---- 3. static -------------------------------------------------------------
    rc_ruff, out_ruff = run(["ruff", "check", "--select", "F", str(BENCH_SRC)],
                            cwd=str(WT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    (RAW / "ruff_m1.txt").write_text("ruff check --select F %s -> rc=%s\n\n%s"
                                     % (BENCH_SRC, rc_ruff, out_ruff), encoding="utf-8")

    # ---- 4. suite (no MF_BENCH_* in the environment: the reviewer's condition) --
    env = dict(os.environ)
    for k in ("MF_BENCH_LEDGER", "MF_BENCH_WORK", "MF_BENCH_EV_OUT", "MF_BENCH_LEDGER_MODE"):
        env.pop(k, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, "-m", "pytest", str(BENCH_SRC), "-q", "-p", "no:cacheprovider",
           "--basetemp=" + str(BASETEMP)]
    rc, out = run(cmd, cwd=str(WT), env=env)
    (RAW / "pytest_m1.txt").write_text("$ %s\ncwd=%s\nenv: MF_BENCH_* REMOVED\n\n%s"
                                       % (" ".join(cmd), WT, out), encoding="utf-8")

    # ---- 1 + 2. isolation ------------------------------------------------------
    after = snap_all()
    probe = probe_default_ledger()
    ledgers = {}
    for k in PROTECTED:
        b, a = before[k]["ledger"], after[k]["ledger"]
        ledgers[k] = {"role": PROTECTED[k]["role"],
                      "path": PROTECTED[k]["ledger"] and str(PROTECTED[k]["ledger"]),
                      "before": b, "after": a,
                      "bytes_appended_by_this_run": (a["bytes"] or 0) - (b["bytes"] or 0),
                      "sha_before": b["sha256"], "sha_after": a["sha256"],
                      "unchanged": b == a}
    drift = {}
    for k in PROTECTED:
        b, a = before[k]["tree"], after[k]["tree"]
        changed = sorted(set(b["files_map"]) | set(a["files_map"]))
        changed = [r for r in changed if b["files_map"].get(r) != a["files_map"].get(r)]
        drift[k] = {"root": b["root"], "files_before": b["files"], "files_after": a["files"],
                    "bytes_before": b["bytes_total"], "bytes_after": a["bytes_total"],
                    "digest_before": b["digest"], "digest_after": a["digest"],
                    "changed_paths": changed, "zero_drift": not changed and b["digest"] == a["digest"]}

    own_after = {"bytes": OWN_LEDGER.stat().st_size if OWN_LEDGER.exists() else 0,
                 "sha256": sha_b(OWN_LEDGER.read_bytes()) if OWN_LEDGER.exists() else None}
    own_rows = None
    if OWN_LEDGER.exists():
        txt = OWN_LEDGER.read_text(encoding="utf-8", errors="replace")
        own_rows = {"lines": txt.count("\n"), "run_headers": txt.count('"run": "start"'),
                    "distinct_run_ids": len(set(re.findall(r'"run_id": "([^"]+)"', txt)))}
    zero_appended = all(v["bytes_appended_by_this_run"] == 0 for v in ledgers.values())
    ok = (rc_ruff == 0 and rc == 0 and zero_appended
          and all(d["zero_drift"] for d in drift.values())
          and not probe["in_evidence_root"] and probe["fails_closed_when_scratch_is_inside_evidence_root"])

    sent = {"artifact": "m1_sentinel_ledger.json", "task_id": "MF-V1-BENCH",
            "wave": "B (round 2) - M1 candidate",
            "kind": "sentinel_packet_ledger_zero_drift_and_ledger_isolation",
            "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "gate": "submitted packets keep every byte; the default ledger resolves to scratch and "
                    "fails closed inside an evidence root; ruff --select F clean; suite green",
            "protected_packets": ledgers,
            "bytes_appended_to_submitted_packets": sum(v["bytes_appended_by_this_run"]
                                                       for v in ledgers.values()),
            "evidence_root_zero_drift": drift,
            "own_ledger": {"path": str(OWN_LEDGER), "before": own_before, "after": own_after,
                           "bytes_appended_by_this_run": own_after["bytes"] - own_before["bytes"],
                           "rows": own_rows,
                           "note": "this round's OWN ledger is named explicitly "
                                   "(MF_BENCH_LEDGER / set_ledger_path) and appended with a per-run "
                                   "header - it is not a submitted packet, and no other ledger grew"},
            "default_ledger_probe": probe,
            "static": {"command": "ruff check --select F %s" % BENCH_SRC, "exit_code": rc_ruff,
                       "output_path": str(RAW / "ruff_m1.txt"),
                       "clean": rc_ruff == 0, "tail": out_ruff.strip().splitlines()[-3:]},
            "suite": {"command": " ".join(cmd), "cwd": str(WT), "exit_code": rc,
                      "env": "MF_BENCH_LEDGER/MF_BENCH_WORK/MF_BENCH_EV_OUT/MF_BENCH_LEDGER_MODE removed",
                      "output_path": str(RAW / "pytest_m1.txt"), "green": rc == 0,
                      "tail": out.strip().splitlines()[-1] if out.strip() else ""},
            "commands": COMMANDS,
            "SENTINEL": "PASS" if ok else "FAIL"}
    C_write = json.dumps(sent, indent=1)
    (RAW / "m1_sentinel_ledger.json").write_text(C_write, encoding="utf-8")

    print("RUFF_RC=%s clean=%s" % (rc_ruff, rc_ruff == 0))
    print("SUITE_RC=%s %s" % (rc, sent["suite"]["tail"]))
    for k, v in ledgers.items():
        print("LEDGER %-24s before=%s B sha=%s | after=%s B sha=%s | appended=%s"
              % (k, v["before"]["bytes"], (v["sha_before"] or "-")[:16],
                 v["after"]["bytes"], (v["sha_after"] or "-")[:16], v["bytes_appended_by_this_run"]))
    for k, v in drift.items():
        print("TREE   %-24s files %s->%s digest %s zero_drift=%s"
              % (k, v["files_before"], v["files_after"], v["digest_before"][:16], v["zero_drift"]))
    print("DEFAULT_LEDGER=%s in_evidence_root=%s fails_closed=%s"
          % (probe.get("resolved_ledger"), probe.get("in_evidence_root"),
             probe.get("fails_closed_when_scratch_is_inside_evidence_root")))
    print("OWN_LEDGER bytes %s -> %s" % (own_before["bytes"], own_after["bytes"]))
    print("SENTINEL=%s" % sent["SENTINEL"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

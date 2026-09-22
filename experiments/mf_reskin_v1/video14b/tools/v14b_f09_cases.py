"""MF-V1-VIDEO14B wave A — F09 adversarial cases (CPU, read-only).

Builds four complete shutdown-evidence fixtures and runs the hardened classifier
over each one, recording the real stdout and exit code:

  no_authority      : EXACTLY the reviewer's repro - a record with only
                      {"port_closed": true}; both process dumps and the engine
                      chain are missing.  Must be UNPROVEN.
  missing_chain     : dumps present and port refusal present, but no engine chain
                      anywhere.  Must be UNPROVEN.
  timeout_probe     : everything present, but the port evidence is a TIMEOUT
                      (WSAEWOULDBLOCK 10035).  Must be UNPROVEN.
  valid_own_chain   : complete and self-consistent authority, engine chain all
                      taskkilled, own client exited.  Must be CONFIRMED.

The classifier is report-only: it starts nothing, loads nothing, kills nothing.
The end-state re-check (--probe-now) is a separate read-only probe and is exercised
once so the "separate from the stop action" claim has live evidence.

usage:
  python v14b_f09_cases.py <worktree> <fixtures_dir> <evidence_json>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOL_REL = "experiments/mf_reskin_v1/video14b/tools/w2_classify_shutdown.py"
ENGINE_CMD = "C:/x/python.exe C:/y/runtime/video14b/tools/serve_video14b.py --port 8210"
OWN_CMD = "C:/x/python.exe experiments/mf_reskin_v1/video14b/tools/w2_run_stage.py --stage vace"
SURVIVOR = "C:/x/python.exe -m http.server 9000"

HEADER = "PID\tPPID\tName\tWS_MB\tCommandLine"
ROWS_BEFORE = "\n".join([
    HEADER,
    f"4100\t1\tpython.exe\t512\t{ENGINE_CMD}",
    f"4200\t4100\tpython.exe\t288\t{OWN_CMD}",
    f"4300\t1\tpython.exe\t64\t{SURVIVOR}",
]) + "\n"
ROWS_AFTER = "\n".join([HEADER, f"4300\t1\tpython.exe\t64\t{SURVIVOR}"]) + "\n"
LISTENERS_BEFORE = ["TCP 127.0.0.1:52000 127.0.0.1:8210 ESTABLISHED 4200"]
LISTENERS_AFTER = []          # no :8210 row of any state survives the shutdown
STOP_LOG = [{"pid": 4100, "argv": ["taskkill", "/PID", "4100", "/F"], "returncode": 0}]
FULL_EV = {
    "instance_epoch": {"port": 8210, "pid": 4100, "instance_id": "fixture"},
    "connect_ex_before": 0,
    "connect_ex_after": 10061,
    "port_closed": True,
    "engine_chain_leaf_to_root": [4100],
    "engine_chain_rows": {"4100": {"cmdline": ENGINE_CMD}},
    "stop_log": STOP_LOG,
    "listeners_before": {"lines": LISTENERS_BEFORE},
    "listeners_after": {"lines": LISTENERS_AFTER},
    "protected_before": {"14872": {"alive": True}, "29648": {"alive": True}},
    "collateral_removed": [],
    "vram_before": "9264 MiB", "vram_after": "1109 MiB",
}


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def case(work: Path, name: str, *, dumps: bool, ev: dict,
         rows_before: str | None = None) -> dict:
    d = work / name
    d.mkdir(parents=True, exist_ok=True)
    if dumps:
        (d / "wave2_pids_before_stop.txt").write_text(
            rows_before if rows_before is not None else ROWS_BEFORE, encoding="utf-8")
        (d / "wave2_pids_after_stop.txt").write_text(ROWS_AFTER, encoding="utf-8")
    (d / "wave2_shutdown_evidence.json").write_text(
        json.dumps(ev, indent=1), encoding="utf-8")
    return {"dir": str(d).replace("\\", "/")}


def main() -> int:
    wt = _p(sys.argv[1])
    fixtures = _p(sys.argv[2])
    ev_out = _p(sys.argv[3])
    fixtures.mkdir(parents=True, exist_ok=True)
    tool = wt / TOOL_REL

    no_auth = dict(FULL_EV)
    for k in ("engine_chain_leaf_to_root", "engine_chain_rows", "stop_log",
              "listeners_before", "listeners_after", "port_closed",
              "connect_ex_after", "connect_ex_before"):
        no_auth.pop(k, None)
    no_auth["port_closed"] = True                      # the reviewer's exact minimal record

    missing_chain = dict(FULL_EV)
    missing_chain.pop("engine_chain_leaf_to_root", None)
    missing_chain.pop("engine_chain_rows", None)
    missing_chain["stop_log"] = [{"action": "REFUSED_NOT_ENGINE", "pid": 9999}]

    timeout_probe = dict(FULL_EV)
    timeout_probe["connect_ex_after"] = 10035          # WSAEWOULDBLOCK
    timeout_probe["port_closed"] = True

    valid = dict(FULL_EV)
    valid["collateral_removed"] = []

    # the engine never appears in the before-dump either, so the chain cannot be
    # rebuilt: chain_pids == [] must read as absent authority, not as "all stopped"
    rows_no_engine = "\n".join([
        HEADER,
        f"4200\t1\tpython.exe\t288\t{OWN_CMD}",
        f"4300\t1\tpython.exe\t64\t{SURVIVOR}",
    ]) + "\n"

    plan = [
        ("no_authority", dict(dumps=False, ev=no_auth), "SHUTDOWN_UNPROVEN"),
        ("missing_chain", dict(dumps=True, ev=missing_chain, rows_before=rows_no_engine),
         "SHUTDOWN_UNPROVEN"),
        ("timeout_probe", dict(dumps=True, ev=timeout_probe), "SHUTDOWN_UNPROVEN"),
        ("valid_own_chain", dict(dumps=True, ev=valid), "SHUTDOWN_CONFIRMED"),
    ]

    results = []
    for i, (name, kw, want_prefix) in enumerate(plan):
        c = case(fixtures, name, **kw)
        argv = [sys.executable, str(tool), c["dir"]]
        if name == "no_authority":
            argv.append("--probe-now")     # read-only end-state re-check, never a stop
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        try:
            payload = json.loads(r.stdout)
        except Exception:  # noqa: BLE001
            payload = {"_unparsed_stdout_tail": r.stdout[-800:]}
        verdict = payload.get("verdict")
        results.append({
            "case": name,
            "fixture_dir": c["dir"],
            "argv": argv,
            "returncode": r.returncode,
            "stderr_tail": (r.stderr or "")[-400:],
            "verdict": verdict,
            "expected_verdict_prefix": want_prefix,
            "matches_expected": bool(verdict and verdict.startswith(want_prefix)),
            "unproven_reason": payload.get("unproven_reason"),
            "authority": payload.get("authority"),
            "verdict_basis": payload.get("verdict_basis"),
            "self_audit_no_kill_path": payload.get("self_audit_no_kill_path"),
            "read_only_recheck": payload.get("read_only_recheck"),
            "stdout_sha256": __import__("hashlib").sha256(r.stdout.encode()).hexdigest(),
        })
        (fixtures / name / "stdout.json").write_text(r.stdout, encoding="utf-8")
        (fixtures / name / "stderr.txt").write_text(r.stderr or "", encoding="utf-8")

    rec = {"artifact": "f09_cases.json", "task_id": "MF-V1-VIDEO14B", "row": "F09",
           "tool": str(tool).replace("\\", "/"),
           "engine_started": False, "model_loaded": False, "pid_stopped": False,
           "cases": results,
           "all_match_expected": all(c["matches_expected"] for c in results)}
    ev_out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in results:
        print(f"{c['case']:18s} rc={c['returncode']} verdict={c['verdict']} "
              f"expected~{c['expected_verdict_prefix']} ok={c['matches_expected']} "
              f"reason={c['unproven_reason']}")
    return 0 if rec["all_match_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

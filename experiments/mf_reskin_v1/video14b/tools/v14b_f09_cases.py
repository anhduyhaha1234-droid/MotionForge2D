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
  valid_own_chain   : complete and self-consistent authority PLUS full provenance for
                      the removed own client: it is the engine's ESTABLISHED client on
                      the port the classifier resolves, its cmdline runs this task's
                      own tool, and its own run record + runlog are present (the two
                      files self_exit_corroboration() reads).  Must be CONFIRMED.
                      R10: the fixture used to hard-code port 8210 while the
                      classifier resolves the port from the runtime instance_epoch
                      (8310), so 4200 was collateral and the answer was -- correctly
                      -- UNPROVEN.  The classifier was right; the fixture was wrong.The classifier is report-only: it starts nothing, loads nothing, kills nothing.
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
ENGINE_CMD = "C:/x/python.exe C:/y/runtime/video14b/tools/serve_video14b.py --port {port}"
RUN_ID = "r_vace_01"
OWN_CMD = ("C:/x/python.exe experiments/mf_reskin_v1/video14b/tools/w2_run_stage.py "
           "--run-dir runs/{run_id} --stage vace")
SURVIVOR = "C:/x/python.exe -m http.server 9000"


def resolve_classifier_port(wt: Path) -> tuple[int, str]:
    """The port the CLASSIFIER resolves, so this fixture cannot drift from it.

    R10: the fixture used to hard-code 8210 while w2_classify_shutdown.py reads
    runtime/video14b/instance_epoch.json (wave B reserves 8310).  The own-client listener
    row never matched, PID 4200 became `collateral_removed` and the verdict was UNPROVEN.
    """
    import importlib.util
    tool = wt / TOOL_REL
    spec = importlib.util.spec_from_file_location("mf_w2_clf_fixture", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    epoch = getattr(mod, "_EPOCH", None)
    epoch_s = str(epoch).replace(chr(92), "/") if epoch is not None else "unavailable"
    return int(mod.PORT), f"w2_classify_shutdown.PORT={int(mod.PORT)} (module reads {epoch_s})"


HEADER = "PID\tPPID\tName\tWS_MB\tCommandLine"


def engine_cmd(port: int) -> str:
    return ENGINE_CMD.format(port=port)


def own_cmd() -> str:
    return OWN_CMD.format(run_id=RUN_ID)


def rows_before(port: int) -> str:
    return "\n".join([
        HEADER,
        f"4100\t1\tpython.exe\t512\t{engine_cmd(port)}",
        f"4200\t4100\tpython.exe\t288\t{own_cmd()}",
        f"4300\t1\tpython.exe\t64\t{SURVIVOR}",
    ]) + "\n"


ROWS_AFTER = "\n".join([HEADER, f"4300\t1\tpython.exe\t64\t{SURVIVOR}"]) + "\n"


def listeners_before(port: int) -> list[str]:
    """PID 4200 is an ESTABLISHED client OF THE ENGINE PORT -- the port the classifier
    resolves, so the client attribution can actually match."""
    return [f"TCP 127.0.0.1:52000 127.0.0.1:{port} ESTABLISHED 4200"]


LISTENERS_AFTER = []          # no engine-port row of any state survives the shutdown
STOP_LOG = [{"pid": 4100, "argv": ["taskkill", "/PID", "4100", "/F"], "returncode": 0}]


def self_exit_receipts(wave2: Path) -> list[str]:
    """The REAL attribution of the removed own client: its own run record + runlog.

    These are exactly the two artifacts w2_classify_shutdown.self_exit_corroboration()
    reads (runs/<run_id>/run_record.json and raw/<run_id>.runlog.txt), extracted by
    `runs[/\\]([A-Za-z0-9_]+)` from the removed pid's own cmdline.
    """
    rec_dir = wave2 / "runs" / RUN_ID
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "run_id": RUN_ID,
        "argv": ["C:/x/python.exe", "experiments/mf_reskin_v1/video14b/tools/w2_run_stage.py",
                 "--run-dir", f"runs/{RUN_ID}", "--stage", "vace"],
        "cwd": "C:/x",
        "wall_s": 41.5,
        "result": {"status": "client_exited_after_engine_stop", "returncode": 0,
                   "client_of_engine_port": True, "stopped_by": "self", "taskkill_pid": None},
        "artifacts": {"history": "raw/vace_history.json"},
    }
    rec_path = rec_dir / "run_record.json"
    rec_path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    raw_dir = wave2 / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_path = raw_dir / f"{RUN_ID}.runlog.txt"
    log_path.write_text(json.dumps({"status": "engine_stop_observed", "wall_s": 41.5,
                                    "error": None}) + "\n", encoding="utf-8")
    return [str(rec_path).replace(chr(92), "/"), str(log_path).replace(chr(92), "/")]


def self_exit_lines(payload: dict) -> list[str]:
    """The classifier's own evidence lines that carry the self-exit attribution."""
    out: list[str] = []
    for cls in (payload.get("pid_classification") or {}).values():
        for line in cls.get("evidence") or []:
            if "self-exit record" in line:
                out.append(line)
    return out


def full_ev(port: int) -> dict:
    return {
        "instance_epoch": {"port": port, "pid": 4100, "instance_id": "fixture"},
        "connect_ex_before": 0,
        "connect_ex_after": 10061,
        "port_closed": True,
        "engine_chain_leaf_to_root": [4100],
        "engine_chain_rows": {"4100": {"cmdline": engine_cmd(port)}},
        "stop_log": STOP_LOG,
        "listeners_before": {"lines": listeners_before(port)},
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


def case(work: Path, name: str, *, dumps: bool, ev: dict, port: int,
         rows: str | None = None, receipts: bool = False) -> dict:
    d = work / name
    d.mkdir(parents=True, exist_ok=True)
    if dumps:
        (d / "wave2_pids_before_stop.txt").write_text(
            rows if rows is not None else rows_before(port), encoding="utf-8")
        (d / "wave2_pids_after_stop.txt").write_text(ROWS_AFTER, encoding="utf-8")
    (d / "wave2_shutdown_evidence.json").write_text(
        json.dumps(ev, indent=1), encoding="utf-8")
    receipt_files = self_exit_receipts(d) if receipts else []
    return {"dir": str(d).replace(chr(92), "/"), "receipt_files": receipt_files}

def main() -> int:
    wt = _p(sys.argv[1])
    fixtures = _p(sys.argv[2])
    ev_out = _p(sys.argv[3])
    fixtures.mkdir(parents=True, exist_ok=True)
    tool = wt / TOOL_REL

    port, port_source = resolve_classifier_port(wt)
    base = full_ev(port)

    no_auth = dict(base)
    for k in ("engine_chain_leaf_to_root", "engine_chain_rows", "stop_log",
              "listeners_before", "listeners_after", "port_closed",
              "connect_ex_after", "connect_ex_before"):
        no_auth.pop(k, None)
    no_auth["port_closed"] = True                      # the reviewer's exact minimal record

    missing_chain = dict(base)
    missing_chain.pop("engine_chain_leaf_to_root", None)
    missing_chain.pop("engine_chain_rows", None)
    missing_chain["stop_log"] = [{"action": "REFUSED_NOT_ENGINE", "pid": 9999}]

    timeout_probe = dict(base)
    timeout_probe["connect_ex_after"] = 10035          # WSAEWOULDBLOCK
    timeout_probe["port_closed"] = True

    valid = dict(base)
    valid["collateral_removed"] = []

    # the engine never appears in the before-dump either, so the chain cannot be
    # rebuilt: chain_pids == [] must read as absent authority, not as "all stopped"
    rows_no_engine = "\n".join([
        HEADER,
        f"4200\t1\tpython.exe\t288\t{own_cmd()}",
        f"4300\t1\tpython.exe\t64\t{SURVIVOR}",
    ]) + "\n"

    plan = [
        ("no_authority", dict(dumps=False, ev=no_auth), "SHUTDOWN_UNPROVEN"),
        ("missing_chain", dict(dumps=True, ev=missing_chain, rows=rows_no_engine),
         "SHUTDOWN_UNPROVEN"),
        ("timeout_probe", dict(dumps=True, ev=timeout_probe), "SHUTDOWN_UNPROVEN"),
        # R10: the positive case must carry FULL provenance -- the own client's own run
        # record + runlog under runs/<run_id>/ and raw/<run_id>.runlog.txt, which is
        # exactly what self_exit_corroboration() reads.
        ("valid_own_chain", dict(dumps=True, ev=valid, receipts=True),
         "SHUTDOWN_CONFIRMED"),
    ]

    results = []
    for i, (name, kw, want_prefix) in enumerate(plan):
        kw.setdefault("port", port)
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
            "receipt_files": c["receipt_files"],
            "argv": argv,
            "port_resolved": port,
            "port_source": port_source,
            "returncode": r.returncode,
            "stderr_tail": (r.stderr or "")[-400:],
            "verdict": verdict,
            "expected_verdict_prefix": want_prefix,
            "matches_expected": bool(verdict and verdict.startswith(want_prefix)),
            "unproven_reason": payload.get("unproven_reason"),
            "authority": payload.get("authority"),
            "collateral_removed": payload.get("collateral_removed"),
            "pid_classification": payload.get("pid_classification"),
            "self_exit_evidence": self_exit_lines(payload),
            "verdict_basis": payload.get("verdict_basis"),
            "self_audit_no_kill_path": payload.get("self_audit_no_kill_path"),
            "read_only_recheck": payload.get("read_only_recheck"),
            "stdout_sha256": __import__("hashlib").sha256(r.stdout.encode()).hexdigest(),
        })
        (fixtures / name / "stdout.json").write_text(r.stdout, encoding="utf-8")
        (fixtures / name / "stderr.txt").write_text(r.stderr or "", encoding="utf-8")

    by_case = {c["case"]: c for c in results}
    pos = by_case.get("valid_own_chain", {})
    positive_provenance = {
        "verdict_confirmed": str(pos.get("verdict") or "").startswith("SHUTDOWN_CONFIRMED"),
        "collateral_removed_empty": pos.get("collateral_removed") == [],
        "own_client_classified": any(
            (v or {}).get("class") == "own_client_process_exited_after_engine_stop"
            for v in (pos.get("pid_classification") or {}).values()),
        "self_exit_receipt_attributed": bool(pos.get("self_exit_evidence")),
        "receipt_files_written": len(pos.get("receipt_files") or []) == 2,
    }
    rec = {"artifact": "f09_cases.json", "task_id": "MF-V1-VIDEO14B", "row": "F09",
           "round": "roundC (row V01)",
           "tool": str(tool).replace(chr(92), "/"),
           "port_resolved": port, "port_source": port_source,
           "fixture_is_synthetic": True,
           "real_endstate_evidence_is_separate": True,
           "engine_started": False, "model_loaded": False, "pid_stopped": False,
           "cases": results,
           "positive_case_provenance": positive_provenance,
           "positive_case_full_provenance": all(positive_provenance.values()),
           "all_match_expected": all(c["matches_expected"] for c in results)}
    ev_out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in results:
        print(f"{c['case']:18s} rc={c['returncode']} verdict={c['verdict']} "
              f"expected~{c['expected_verdict_prefix']} ok={c['matches_expected']} "
              f"collateral={c['collateral_removed']} reason={c['unproven_reason']}")
    return 0 if (rec["all_match_expected"] and rec["positive_case_full_provenance"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

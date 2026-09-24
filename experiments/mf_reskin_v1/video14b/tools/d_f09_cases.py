"""MF-V1-VIDEO14B round D — NR09: the reviewer's five adversarial variants + controls.

The reviewer measured that five synthetic variants ALL returned
SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT before the round-D hardening:

  1. absent self-exit receipt
  2. engine still present in the after-dump
  3. a non-stop command with rc=0 in the stop_log
  4. a SUCCESSFUL connect (connect_ex_after == 0) next to port_closed=true
  5. evidence bound to the wrong epoch/port

plus unknown / timeout / missing-authority controls.  This generator re-derives the four
RETAINED fixture cases with the round-C builders (imported by file path, so their shape
cannot drift), adds the five variants and the two new controls, runs the HARDENED
classifier over every one of them and records the real stdout/exit code.

The synthetic fixtures and the REAL end-state evidence are filed separately: the real
record is only READ (never written) and its own verdict is recorded in its own section.

Nothing here starts an engine, loads a model, kills a pid or writes media.

usage: python d_f09_cases.py <worktree> <fixtures_dir> <evidence_json>
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

RET_TOOL = "experiments/mf_reskin_v1/video14b/tools/w2_classify_shutdown.py"
RET_HARNESS = "experiments/mf_reskin_v1/video14b/tools/v14b_f09_cases.py"
# the REAL end state of the frozen wave-B run (read-only, never written by this tool)
REAL_WAVE2 = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
              "mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/waveB/raw/shutdown")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def case(work: Path, name: str, *, dumps: bool, ev: dict, port: int, retained,
         rows: str | None = None, rows_after: str | None = None,
         receipts: bool = False) -> dict:
    """Round-C fixture shape (same files, same names) + an optional after-dump override."""
    d = work / name
    d.mkdir(parents=True, exist_ok=True)
    if dumps:
        (d / "wave2_pids_before_stop.txt").write_text(
            rows if rows is not None else retained.rows_before(port), encoding="utf-8")
        (d / "wave2_pids_after_stop.txt").write_text(
            rows_after if rows_after is not None else retained.ROWS_AFTER, encoding="utf-8")
    (d / "wave2_shutdown_evidence.json").write_text(
        json.dumps(ev, indent=1), encoding="utf-8")
    receipt_files = retained.self_exit_receipts(d) if receipts else []
    return {"dir": str(d).replace("\\", "/"), "receipt_files": receipt_files}


def run_case(tool: Path, c: dict, *, probe_now: bool = False) -> dict:
    argv = [sys.executable, str(tool), c["dir"]]
    if probe_now:
        argv.append("--probe-now")
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    try:
        payload = json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        payload = {"_unparsed_stdout_tail": r.stdout[-800:]}
    return {"argv": argv, "returncode": r.returncode, "stderr_tail": (r.stderr or "")[-400:],
            "payload": payload,
            "stdout_sha256": hashlib.sha256(r.stdout.encode()).hexdigest(),
            "stdout": r.stdout, "stderr": r.stderr or ""}


def main() -> int:
    wt = _p(sys.argv[1])
    fixtures = _p(sys.argv[2])
    ev_out = _p(sys.argv[3])
    fixtures.mkdir(parents=True, exist_ok=True)
    tool = wt / RET_TOOL
    retained = load(wt / RET_HARNESS, "mf_d_f09_retained")

    port, port_source = retained.resolve_classifier_port(wt)
    base = retained.full_ev(port)

    # ---------------------------------------------------------------- retained (4)
    no_auth = dict(base)
    for k in ("engine_chain_leaf_to_root", "engine_chain_rows", "stop_log",
              "listeners_before", "listeners_after", "port_closed",
              "connect_ex_after", "connect_ex_before"):
        no_auth.pop(k, None)
    no_auth["port_closed"] = True

    missing_chain = dict(base)
    missing_chain.pop("engine_chain_leaf_to_root", None)
    missing_chain.pop("engine_chain_rows", None)
    missing_chain["stop_log"] = [{"action": "REFUSED_NOT_ENGINE", "pid": 9999}]

    timeout_probe = dict(base)
    timeout_probe["connect_ex_after"] = 10035
    timeout_probe["port_closed"] = True

    valid = dict(base)

    rows_no_engine = "\n".join([
        retained.HEADER,
        f"4200\t1\tpython.exe\t288\t{retained.own_cmd()}",
        f"4300\t1\tpython.exe\t64\t{retained.SURVIVOR}",
    ]) + "\n"

    # ----------------------------------------------------------- adversarial (5)
    v_no_receipt = dict(base)                     # 1. the receipt is simply not written

    rows_engine_present = "\n".join([
        retained.HEADER,
        f"4100\t1\tpython.exe\t512\t{retained.engine_cmd(port)}",   # engine survives
        f"4300\t1\tpython.exe\t64\t{retained.SURVIVOR}",
    ]) + "\n"

    v_non_stop = dict(base)                       # 3. a probe that exited 0
    v_non_stop["stop_log"] = [{"pid": 4100,
                               "argv": ["python.exe", "probe_engine.py", "--port", str(port)],
                               "returncode": 0}]

    v_connect_ok = dict(base)                     # 4. the connect SUCCEEDED
    v_connect_ok["connect_ex_after"] = 0
    v_connect_ok["port_closed"] = True

    v_wrong_epoch = dict(base)                    # 5. another epoch/port entirely
    v_wrong_epoch["instance_epoch"] = {"port": 8210, "pid": 4100, "instance_id": "waveA"}
    v_wrong_epoch["port"] = 8210

    # --------------------------------------------------------------- controls (2)
    ctl_unknown = dict(base)                      # the probe never learned the state
    ctl_unknown["connect_ex_after"] = None
    ctl_unknown["port_closed"] = True

    ctl_no_stop_authority = dict(base)            # nothing was stopped at all
    ctl_no_stop_authority["stop_log"] = []

    plan = [
        # (name, kwargs, expected verdict prefix, expected exact, kind)
        ("no_authority", dict(dumps=False, ev=no_auth), "SHUTDOWN_UNPROVEN", None,
         "retained_fixture"),
        ("missing_chain", dict(dumps=True, ev=missing_chain, rows=rows_no_engine),
         "SHUTDOWN_UNPROVEN", None, "retained_fixture"),
        ("timeout_probe", dict(dumps=True, ev=timeout_probe), "SHUTDOWN_UNPROVEN", None,
         "retained_fixture"),
        ("valid_own_chain", dict(dumps=True, ev=valid, receipts=True),
         "SHUTDOWN_CONFIRMED", "SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT",
         "retained_fixture"),
        ("adv_absent_self_exit_receipt", dict(dumps=True, ev=v_no_receipt),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN", "adversarial_variant"),
        ("adv_engine_still_present",
         dict(dumps=True, ev=dict(base), rows_after=rows_engine_present),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN_CONTRADICTION", "adversarial_variant"),
        ("adv_non_stop_command_rc0", dict(dumps=True, ev=v_non_stop),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN", "adversarial_variant"),
        ("adv_connect_succeeded_but_closed_flag", dict(dumps=True, ev=v_connect_ok),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN_CONTRADICTION", "adversarial_variant"),
        ("adv_wrong_epoch_port", dict(dumps=True, ev=v_wrong_epoch),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN_CONTRADICTION", "adversarial_variant"),
        ("ctl_unknown_port_state", dict(dumps=True, ev=ctl_unknown),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN", "control"),
        ("ctl_missing_stop_authority", dict(dumps=True, ev=ctl_no_stop_authority),
         "SHUTDOWN_UNPROVEN", "SHUTDOWN_UNPROVEN", "control"),
    ]

    results = []
    for name, kw, want_prefix, want_exact, kind in plan:
        kw.setdefault("port", port)
        c = case(fixtures, name, retained=retained, **kw)
        r = run_case(tool, c, probe_now=(name == "no_authority"))
        p = r["payload"]
        verdict = p.get("verdict")
        results.append({
            "case": name, "kind": kind,
            "fixture_is_synthetic": True,
            "fixture_dir": c["dir"], "receipt_files": c["receipt_files"],
            "argv": r["argv"], "port_resolved": port, "port_source": port_source,
            "returncode": r["returncode"], "stderr_tail": r["stderr_tail"],
            "verdict": verdict,
            "expected_verdict_prefix": want_prefix, "expected_verdict_exact": want_exact,
            "matches_expected": bool(
                verdict and (verdict == want_exact if want_exact
                             else verdict.startswith(want_prefix))),
            "is_confirmed": bool(verdict and verdict.startswith("SHUTDOWN_CONFIRMED")),
            "unproven_reason": p.get("unproven_reason"),
            "authority": p.get("authority"),
            "collateral_removed": p.get("collateral_removed"),
            "pid_classification": p.get("pid_classification"),
            "self_exit_evidence": retained.self_exit_lines(p),
            "verdict_basis": p.get("verdict_basis"),
            "verified_stop_audit": p.get("verified_stop_audit"),
            "stop_order_leaf_to_root": p.get("stop_order_leaf_to_root"),
            "epoch_binding": p.get("epoch_binding"),
            "contradictions": p.get("contradictions"),
            "own_client_uncorroborated": p.get("own_client_uncorroborated"),
            "self_audit_no_kill_path": p.get("self_audit_no_kill_path"),
            "read_only_recheck": p.get("read_only_recheck"),
            "stdout_sha256": r["stdout_sha256"],
        })
        (fixtures / name / "stdout.json").write_text(r["stdout"], encoding="utf-8")
        (fixtures / name / "stderr.txt").write_text(r["stderr"], encoding="utf-8")

    by_case = {c["case"]: c for c in results}
    pos = by_case["valid_own_chain"]
    positive_provenance = {
        "verdict_confirmed": pos["is_confirmed"],
        "collateral_removed_empty": pos["collateral_removed"] == [],
        "own_client_classified": any(
            (v or {}).get("class") == "own_client_process_exited_after_engine_stop"
            for v in (pos["pid_classification"] or {}).values()),
        "self_exit_receipt_attributed": bool(pos["self_exit_evidence"]),
        "receipt_files_written": len(pos["receipt_files"] or []) == 2,
        "all_pillars_held": all((pos["verdict_basis"] or {}).get("pillars", {}).values()),
    }

    # ------------------------------------------------- the REAL end state, separately
    real = {"synthetic": False, "separate_from_synthetic_fixtures": True,
            "real_wave2_dir": REAL_WAVE2, "written_by_this_tool": False,
            "engine_started": False, "model_loaded": False, "pid_stopped_by_this_tool": False}
    real_dir = _p(REAL_WAVE2)
    if real_dir.is_dir():
        rc = run_case(tool, {"dir": str(real_dir).replace("\\", "/"),
                             "receipt_files": []})
        rp = rc["payload"]
        real.update({
            "argv": rc["argv"], "returncode": rc["returncode"],
            "verdict": rp.get("verdict"), "unproven_reason": rp.get("unproven_reason"),
            "verdict_basis": rp.get("verdict_basis"),
            "verified_stop_audit": rp.get("verified_stop_audit"),
            "stop_order_leaf_to_root": rp.get("stop_order_leaf_to_root"),
            "epoch_binding": rp.get("epoch_binding"),
            "contradictions": rp.get("contradictions"),
            "collateral_removed": rp.get("collateral_removed"),
            "pid_classification": rp.get("pid_classification"),
            "self_audit_no_kill_path": rp.get("self_audit_no_kill_path"),
            "matches_expected": rp.get("verdict")
            == "SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT",
            "stdout_sha256": rc["stdout_sha256"],
            "source_artifacts_untouched_by_this_tool": all(
                (rp.get("source_artifacts") or {}).get(n) is not None
                for n in ("wave2_pids_before_stop.txt", "wave2_pids_after_stop.txt")),
        })
        (fixtures / "real_endstate_stdout.json").write_text(rc["stdout"], encoding="utf-8")
    else:
        real["matches_expected"] = False
        real["blocker"] = f"real wave2 dir not found: {REAL_WAVE2}"

    variants = [c for c in results if c["kind"] == "adversarial_variant"]
    controls = [c for c in results if c["kind"] == "control"]
    retained_cases = [c for c in results if c["kind"] == "retained_fixture"]
    rec = {
        "artifact": "d_f09_adversarial_cases.json", "task_id": "MF-V1-VIDEO14B",
        "row": "NR09", "round": "roundD",
        "tool": str(tool).replace("\\", "/"),
        "harness": str(Path(__file__)).replace("\\", "/"),
        "port_resolved": port, "port_source": port_source,
        "classifier_tool_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
        "fixture_is_synthetic": True,
        "real_endstate_evidence_is_separate": True,
        "engine_started": False, "model_loaded": False, "pid_stopped": False,
        "cases": results,
        "retained_fixtures": retained_cases,
        "adversarial_variants": variants,
        "controls": controls,
        "all_five_variants_not_confirmed": all(not c["is_confirmed"] for c in variants),
        "all_cases_match_expected": all(c["matches_expected"] for c in results),
        "no_case_has_a_kill_path": all(
            c["self_audit_no_kill_path"] and not c["self_audit_no_kill_path"]["kills_process"]
            and c["self_audit_no_kill_path"]["kill_call_sites"] == []
            for c in results),
        "positive_case_provenance": positive_provenance,
        "positive_case_full_provenance": all(positive_provenance.values()),
        "real_endstate": real,
    }
    rec["all_match_expected"] = bool(rec["all_cases_match_expected"]
                                     and rec["all_five_variants_not_confirmed"]
                                     and rec["positive_case_full_provenance"]
                                     and rec["no_case_has_a_kill_path"]
                                     and real.get("matches_expected"))
    ev_out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in results:
        print(f"{c['kind'][:9]:9s} {c['case']:38s} rc={c['returncode']} "
              f"verdict={c['verdict']:44s} ok={c['matches_expected']} "
              f"reason={str(c['unproven_reason'])[:110]}")
    print(f"REAL end state verdict={real.get('verdict')} ok={real.get('matches_expected')}")
    print(f"ALL_MATCH={rec['all_match_expected']}")
    return 0 if rec["all_match_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

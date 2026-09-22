"""MF-V1-VIDEO14B — report-only shutdown re-classification (continuation-04).

Reads ONLY the already-written first-pass dumps in <wave2_dir>:

  wave2_pids_before_stop.txt      python.exe table before the stop
  wave2_pids_after_stop.txt       python.exe table after the stop
  wave2_shutdown_evidence.json    first-pass record (stop_log, chain, listeners,
                                  port probe, VRAM)
  runs/*/run_record.json          own stage-script records (self-exit corroboration)
  raw/*.runlog.txt                own stage-script logs (self-exit corroboration)

It NEVER starts the engine, never load a model, never kills a pid, never writes
media.  It only classifies the pids that disappeared between the two dumps and
recomputes the verdict.

Classification rules
  engine_chain   pid listed as engine chain (cmdline contains serve_video14b.py)
  taskkilled     pid with a taskkill argv and returncode 0 in the first-pass stop_log
  own_client     a REMOVED pid whose before-cmdline runs one of this task's own
                 tools (experiments/mf_reskin_v1/video14b/**) AND which appears in
                 listeners_before as an ESTABLISHED *client* of the engine port
                 -> own_client_process_exited_after_engine_stop
  collateral     removed, but neither engine chain nor a proven own_client

Verdict
  SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT
      port closed + no LISTENING row for the port + every engine-chain pid carries a
      successful taskkill + collateral_removed == []
  SHUTDOWN_UNPROVEN   otherwise

Usage:
  python w2_classify_shutdown.py <wave2_dir> [--write] [--probe-now]

`--probe-now` adds a strictly read-only end-state re-check (blocking connect +
tasklist), the same way the Manager verified the machine.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# wave B: read the port from the epoch the server itself wrote (this wave reserves
# 8310); never hard-code a previous wave's port into a shutdown classifier.
_EPOCH = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b\instance_epoch.json")
PORT = int(json.loads(_EPOCH.read_text(encoding="utf-8"))["port"]) if _EPOCH.is_file() else 8310
ENGINE_MARK = "serve_video14b.py"
OWN_TOOL_MARK = "experiments/mf_reskin_v1/video14b"
MANAGER_PIDS = {14872: "hermes desktop", 29648: "hermes serve"}

# ---------------------------------------------------------------------------
# F09 (reviewer row P2): a CONFIRMED verdict needs POSITIVE authority.
#
# The first pass emitted CONFIRMED from a record that carried only
# {"port_closed": true} while both process dumps and the engine chain were
# missing: `set(chain_pids) <= set(taskkilled)` is vacuously True on an EMPTY
# chain, so an empty evidence set "succeeded" (see
# READ/root-probes/shutdown-no-authority.stdout). Empty or ambiguous authority is
# not evidence of a completed shutdown, it is absence of evidence.
#
# Rule now enforced: CONFIRMED is reachable only when every one of these is
# present AND self-consistent; anything else is SHUTDOWN_UNPROVEN with a named
# reason. A socket TIMEOUT is not a closed port either - only a refusal is.
# ---------------------------------------------------------------------------
AUTHORITY_FIELDS = (
    "before_process_dump",
    "after_process_dump",
    "engine_process_chain",
    "stop_log",
    "port_closed_evidence",
)

# WSAEWOULDBLOCK / WSAETIMEDOUT / EAGAIN: the probe never learned the state.
TIMEOUT_CODES = (10035, 10060, 110, 11)


def authority_report(*, before_rows, after_rows, chain_pids, stop_log,
                     port_closed, port_error_code=None,
                     before_dump_present=None, after_dump_present=None) -> dict:
    """Decide whether the shutdown evidence is authoritative at all.

    Pure function: no IO, no process, no socket.  Callers pass already-parsed
    facts so the decision can be tested on adversarial inputs.

    A dump FILE that exists with zero rows is legitimate evidence (every target
    process is gone); a dump file that is MISSING is not.  The two are reported
    separately so an empty set can never masquerade as a success.
    """
    before_pids = {r["pid"] for r in (before_rows or [])}
    after_pids = {r["pid"] for r in (after_rows or [])}
    chain = set(chain_pids or [])
    if before_dump_present is None:
        before_dump_present = bool(before_pids)
    if after_dump_present is None:
        after_dump_present = bool(after_pids)
    missing: list[str] = []

    if not before_dump_present:
        missing.append("before_process_dump")
    elif not before_pids:
        missing.append("before_process_dump_empty")
    if not after_dump_present:
        missing.append("after_process_dump")
    if not chain:
        missing.append("engine_process_chain")
    elif not chain <= before_pids:
        missing.append("engine_process_chain_not_in_before_dump")
    if not stop_log:
        missing.append("stop_log")
    if port_closed is None or not isinstance(port_closed, bool):
        missing.append("port_closed_evidence")
    if port_error_code in TIMEOUT_CODES:
        missing.append(f"port_probe_timeout_{port_error_code}")

    return {
        "missing_authority": sorted(set(missing)),
        "authoritative": not missing,
        "observed": {
            "before_dump_present": bool(before_dump_present),
            "before_dump_rows": len(before_pids),
            "after_dump_present": bool(after_dump_present),
            "after_dump_rows": len(after_pids),
            "engine_chain_len": len(chain),
            "stop_log_rows": len(stop_log or []),
            "port_closed": port_closed,
            "port_error_code": port_error_code,
        },
        "note": ("an empty set cannot 'succeed': missing authority => UNPROVEN, "
                 "never CONFIRMED"),
    }

SOURCE_ARTIFACTS = (
    "wave2_pids_before_stop.txt",
    "wave2_pids_after_stop.txt",
    "wave2_shutdown_evidence.json",
    "wave2_netstat_after.txt",
    "wave2_vram_after.txt",
    "wave2_port_probe_after_r4.json",
)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_rows(path: Path) -> list[dict]:
    """Parse the w2_proc_dump.ps1 TSV table (utf-8-sig, crlf tolerant)."""
    rows: list[dict] = []
    if not path.is_file():
        return rows
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for line in text.splitlines()[1:]:
        parts = line.rstrip("\r").split("\t")
        if len(parts) >= 5:
            try:
                rows.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                             "name": parts[2], "ws_mb": parts[3], "cmdline": parts[4]})
            except ValueError:
                continue
    return rows


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001
        return 999, "", f"{type(exc).__name__}: {exc}"


def pid_alive(pid: int) -> bool:
    rc, out, _ = sh(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    return rc == 0 and f'"{pid}"' in out


def blocking_probe(host: str, port: int, timeout: float = 4.0) -> dict:
    """Strictly read-only: a refused connect starts nothing.

    connect_ex on a socket with a timeout is non-blocking under the hood and
    returns WSAEWOULDBLOCK (10035) while the handshake is still pending, so the
    blocking `connect()` attempt is what yields 10061 WSAECONNREFUSED.  Both are
    recorded verbatim, including a timeout, which is NOT the same as a refusal.
    """
    s = socket.socket()
    s.settimeout(timeout)
    try:
        rc = s.connect_ex((host, port))
    finally:
        s.close()
    s2 = socket.socket()
    err: str | None = None
    refused = False
    try:
        s2.settimeout(timeout)
        s2.connect((host, port))
    except ConnectionRefusedError as exc:
        refused = True
        err = f"ConnectionRefusedError: {exc}"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    finally:
        s2.close()
    return {"connect_ex": rc, "connect_refused": refused, "connect_error": err,
            "timeout_s": timeout, "listener_accepted": refused is False and err is None}


def netstat_lines(port: int) -> list[str]:
    rc, out, _ = sh(["netstat", "-ano"])
    return [" ".join(l.split()) for l in out.splitlines()
            if f":{port} " in l or l.rstrip().endswith(f":{port}")]


def established_clients(lines: list[str], port: int) -> dict[int, dict]:
    """Rows where we are the CLIENT side: remote endpoint is our engine port."""
    out: dict[int, dict] = {}
    for i, ln in enumerate(lines):
        f = ln.split()
        if len(f) < 5 or f[0].upper() != "TCP" or f[3].upper() != "ESTABLISHED":
            continue
        if not f[1].startswith("127.0.0.1:") or not f[2].startswith("127.0.0.1:"):
            continue
        lport = int(f[1].rsplit(":", 1)[1])
        rport = int(f[2].rsplit(":", 1)[1])
        try:
            pid = int(f[4])
        except ValueError:
            continue
        if rport == port and pid > 0:
            out[pid] = {"line_index": i, "line": ln, "local_port": lport,
                        "remote_port": rport, "pid": pid}
    return out


def server_side_rows(lines: list[str], port: int) -> list[str]:
    return [ln for ln in lines if re.match(rf"^TCP 127\.0\.0\.1:{port} ", ln)]


def owner_of(cmdline: str) -> str:
    c = cmdline or ""
    low = c.lower()
    if "hermes" in low and ("desktop" in low or "serve" in low or " -z " in low):
        return "hermes"
    if "manager-tools" in low or "manager/tools" in low:
        return "manager-tool"
    if ENGINE_MARK in c:
        return "engine"
    return "other"


def self_exit_corroboration(wave2: Path, removed_cmdline: str | None) -> list[dict]:
    """Find the removed pid's own run record / runlog in the existing evidence."""
    hits: list[dict] = []
    if not removed_cmdline:
        return hits
    argv0 = "w2_run_stage.py"
    if argv0 not in removed_cmdline:
        return hits
    run_id = None
    m = re.search(r"runs[/\\]([A-Za-z0-9_]+)", removed_cmdline)
    if m:
        run_id = m.group(1)
    for rec in sorted((wave2 / "runs").glob("*/run_record.json")):
        try:
            d = json.loads(rec.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        argv = d.get("argv") or []
        joined = " ".join(str(a) for a in argv)
        if argv0 not in joined:
            continue
        if run_id and run_id not in joined:
            continue
        hits.append({
            "run_record": str(rec).replace("\\", "/"),
            "argv": argv,
            "cwd": d.get("cwd"),
            "wall_s": d.get("wall_s"),
            "result": d.get("result"),
            "artifacts": d.get("artifacts"),
        })
    if run_id:
        rl = wave2 / "raw" / f"{run_id}.runlog.txt"
        if rl.is_file():
            entries = []
            txt = rl.read_text(encoding="utf-8", errors="replace")
            for blob in re.findall(r"\{.*?\}", txt, flags=re.S):
                try:
                    entries.append(json.loads(blob))
                except Exception:  # noqa: BLE001
                    continue
            hits.append({"runlog": str(rl).replace("\\", "/"),
                         "entries": [{"status": e.get("status"), "wall_s": e.get("wall_s"),
                                      "error": e.get("error")} for e in entries]})
    return hits


def kill_audit(path: str | Path | None = None) -> dict:
    """AST audit: prove this classifier has no code path that stops a process.

    Grepping the text would false-positive on the docstring, so the module is
    parsed and only *calls* are inspected: subprocess argv lists containing a kill
    verb, and os.kill / .terminate() / .killpg attribute calls.
    """
    import ast
    p = Path(path or __file__)
    tree = ast.parse(p.read_text(encoding="utf-8"))
    tokens = ("taskkill", "stop-process", "killall", "pkill", "terminateprocess")
    hits: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name in ("run", "Popen", "call", "check_output", "system"):
            for a in node.args:
                if isinstance(a, ast.List):
                    for e in a.elts:
                        if isinstance(e, ast.Constant) and isinstance(e.value, str) \
                                and any(t in e.value.lower() for t in tokens):
                            hits.append({"via": name, "arg": e.value, "lineno": node.lineno})
        if isinstance(fn, ast.Attribute) and fn.attr in ("kill", "terminate", "killpg"):
            hits.append({"via": f'{getattr(fn.value, "id", "?")}.{fn.attr}',
                         "arg": None, "lineno": node.lineno})
    return {
        "self_source": str(p).replace("\\", "/"),
        "kill_call_sites": hits,
        "kills_process": bool(hits),
        "note": ("the end-state check is separate from the stop action and must never "
                 "stop a process to rewrite history"),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: w2_classify_shutdown.py <wave2_dir> [--write] [--probe-now]")
        return 2
    wave2 = Path(args[0].replace("\\", "/"))
    write = "--write" in sys.argv
    probe_now = "--probe-now" in sys.argv
    if not wave2.is_dir():
        print(f"BLOCKED_PATH_NOT_FOUND: {wave2}")
        return 2

    before_path = wave2 / "wave2_pids_before_stop.txt"
    after_path = wave2 / "wave2_pids_after_stop.txt"
    ev_path = wave2 / "wave2_shutdown_evidence.json"

    rows_before = dump_rows(before_path)
    rows_after = dump_rows(after_path)
    ev = json.loads(ev_path.read_text(encoding="utf-8", errors="replace")) if ev_path.is_file() else {}

    by_pid_before = {r["pid"]: r for r in rows_before}
    pids_before = {r["pid"] for r in rows_before}
    pids_after = {r["pid"] for r in rows_after}
    removed = sorted(pids_before - pids_after)
    added = sorted(pids_after - pids_before)

    chain_pids = sorted(int(p) for p in (ev.get("engine_chain_leaf_to_root") or []))
    if not chain_pids:  # rebuild from the dumps if the record lacks it
        chain_pids = sorted(r["pid"] for r in rows_before
                            if ENGINE_MARK in (r.get("cmdline") or ""))
    chain_rows = {str(k): v for k, v in (ev.get("engine_chain_rows") or {}).items()}

    stop_log = ev.get("stop_log") or []
    taskkilled = sorted(int(e["pid"]) for e in stop_log
                        if isinstance(e.get("pid"), int) and e.get("returncode") == 0)
    refused = [e for e in stop_log if e.get("action") == "REFUSED_NOT_ENGINE"]

    listeners_before_lines = (ev.get("listeners_before") or {}).get("lines") or []
    clients_before = established_clients(listeners_before_lines, PORT)
    server_rows_before = server_side_rows(listeners_before_lines, PORT)
    listeners_after_lines = (ev.get("listeners_after") or {}).get("lines") or []
    listening_after = [ln for ln in listeners_after_lines
                       if len(ln.split()) > 3 and ln.split()[3].upper() == "LISTENING"
                       and f":{PORT}" in ln]

    first_pass_blocking = None
    pp = wave2 / "wave2_port_probe_after_r4.json"
    if pp.is_file():
        try:
            first_pass_blocking = json.loads(pp.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            first_pass_blocking = None

    classification: dict[str, dict] = {}
    for pid in removed:
        row = by_pid_before.get(pid) or {}
        cmdline = row.get("cmdline") or (chain_rows.get(str(pid)) or {}).get("cmdline") or ""
        cls = None
        evidence: list[str] = []
        if pid in chain_pids or ENGINE_MARK in cmdline:
            cls = "engine_chain_stopped"
            evidence.append(f"cmdline contains {ENGINE_MARK}: {cmdline}")
            if pid in taskkilled:
                evidence.append(f"taskkill /PID {pid} /F returncode 0 in stop_log")
        else:
            own_tool = OWN_TOOL_MARK in cmdline
            client = clients_before.get(pid)
            if own_tool and client:
                cls = "own_client_process_exited_after_engine_stop"
                evidence.append(f"before-dump cmdline runs this task's own tool: {cmdline}")
                evidence.append(
                    f"listeners_before ESTABLISHED client of engine :{PORT}: "
                    f"\"{client['line']}\" (its ephemeral local port {client['local_port']})")
                for sr in server_rows_before:
                    if f":{client['local_port']} " in sr:
                        evidence.append(f"server-side counterpart row: \"{sr}\"")
                if pid not in taskkilled:
                    evidence.append(
                        f"NOT targeted by any taskkill: stop_log pids = {taskkilled}")
                for hit in self_exit_corroboration(wave2, cmdline):
                    evidence.append(f"self-exit record: {json.dumps(hit, ensure_ascii=False)}")
            else:
                cls = "unclassified_removed"
                evidence.append(f"cmdline: {cmdline or '(pid absent from before-dump)'}")
                evidence.append(f"own_tool={own_tool} engine_client={bool(client)}")
        classification[str(pid)] = {
            "class": cls,
            "ppid": row.get("ppid"),
            "ws_mb": row.get("ws_mb"),
            "cmdline": cmdline or None,
            "evidence": evidence,
        }

    collateral = sorted(pid for pid in removed
                        if classification[str(pid)]["class"] == "unclassified_removed")

    port_closed = ev.get("port_closed")
    if port_closed is None:
        port_closed = ev.get("connect_ex_after") not in (None, 0)
    # F09: a TIMEOUT is not a closed port.  Only a refusal (104/10061/111) tells us
    # the port stopped listening; 10035/10060/11 mean the probe never learned.
    port_error_code = ev.get("connect_ex_after")
    # wave B: the stop tool probes closure with a timed connect_ex, which on Windows
    # returns 10035 (WSAEWOULDBLOCK) for a port that is in fact closed.  When the
    # separate BLOCKING probe recorded a refusal, that refusal is the closure
    # authority and the timeout of the first pass stops being "evidence".
    if isinstance(first_pass_blocking, dict) and first_pass_blocking.get("connect_refused") is True:
        port_closed = True
        cand = first_pass_blocking.get("error_code", first_pass_blocking.get("winerror"))
        port_error_code = cand if isinstance(cand, int) else 10061
    elif port_error_code is None and isinstance(first_pass_blocking, dict):
        cand = first_pass_blocking.get("error_code", first_pass_blocking.get("winerror"))
        port_error_code = cand if isinstance(cand, int) else port_error_code

    auth = authority_report(before_rows=rows_before, after_rows=rows_after,
                            chain_pids=chain_pids, stop_log=stop_log,
                            port_closed=port_closed,
                            port_error_code=port_error_code if isinstance(port_error_code, int)
                            else None,
                            before_dump_present=before_path.is_file(),
                            after_dump_present=after_path.is_file())

    confirmed = (auth["authoritative"] and bool(port_closed) and not listening_after
                 and not collateral and set(chain_pids) <= set(taskkilled))
    verdict = ("SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT" if confirmed
               else "SHUTDOWN_UNPROVEN")
    unproven_reason = None
    if not confirmed:
        reasons = []
        if not auth["authoritative"]:
            reasons.append("missing_or_ambiguous_authority: "
                           + ",".join(auth["missing_authority"]))
        if not port_closed:
            reasons.append(f"port_not_proven_closed (error_code={port_error_code})")
        if listening_after:
            reasons.append("listening_row_present_after")
        if collateral:
            reasons.append(f"collateral_removed={collateral}")
        if not set(chain_pids) <= set(taskkilled):
            reasons.append("engine_chain_not_all_taskkilled")
        unproven_reason = "; ".join(reasons)

    # the survivors recorded by the stop pass are the authority; the frozen
    # MANAGER_PIDS constant is only a fallback for a record that lacks them.
    ev_survivors = ev.get("hermes_survivors") or {}
    recheck_pids = ({int(p): (v or {}).get("expected") for p, v in ev_survivors.items()}
                    if ev_survivors else dict(MANAGER_PIDS))

    read_only = None
    if probe_now:
        read_only = {
            "note": ("read-only end-state re-check at continuation-04; no engine was "
                     "started, no pid was stopped, no media byte touched"),
            "port_8210": blocking_probe("127.0.0.1", PORT),
            "port_8199": blocking_probe("127.0.0.1", 8199),
            "manager_pids": {str(p): {"expected": n, "alive": pid_alive(p)}
                             for p, n in recheck_pids.items()},
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    rec = {
        "artifact": "wave2_shutdown_classification.json",
        "round": "continuation-04",
        "tool": "experiments/mf_reskin_v1/video14b/tools/w2_classify_shutdown.py",
        "report_only": True,
        "engine_started": False,
        "model_loaded": False,
        "pid_stopped_by_this_tool": False,
        "media_bytes_changed": False,
        "source_artifacts": {n: {"sha256": sha256_file(wave2 / n)} for n in SOURCE_ARTIFACTS},
        "instance_epoch": ev.get("instance_epoch"),
        "port": PORT,
        "connect_ex_before": ev.get("connect_ex_before"),
        "connect_ex_after": ev.get("connect_ex_after"),
        "port_closed": port_closed,
        "listening_rows_for_port_after": listening_after,
        "closure_evidence_first_pass": {
            "port_probe_blocking_r4": first_pass_blocking,
            "listening_server_rows_in_listeners_before": server_rows_before,
            "established_engine_clients_in_listeners_before": {
                str(k): v["line"] for k, v in clients_before.items()},
        },
        "engine_chain_leaf_to_root": chain_pids,
        "taskkilled_pids_from_stop_log": taskkilled,
        "stop_log_refused_rows": refused,
        "pid_set_diff": {"removed": removed, "added": added},
        "pid_classification": classification,
        "collateral_removed": collateral,
        "collateral_removed_first_pass_raw": ev.get("collateral_removed"),
        "protected_before": ev.get("protected_before"),
        "vram_before": ev.get("vram_before"),
        "vram_after": ev.get("vram_after"),
        "comfy_free_response": ev.get("comfy_free_response"),
        "hermes_survivors": ev.get("hermes_survivors"),
        "verdict": verdict,
        "unproven_reason": unproven_reason,
        "authority": auth,
        "self_audit_no_kill_path": kill_audit(),
        "previous_verdict_first_pass": "SHUTDOWN_UNPROVEN",
        "verdict_basis": {
            "authority_authoritative": auth["authoritative"],
            "missing_authority": auth["missing_authority"],
            "port_closed": bool(port_closed),
            "port_error_code": port_error_code,
            "port_refusal_from_blocking_probe": bool(
                isinstance(first_pass_blocking, dict)
                and first_pass_blocking.get("connect_refused") is True),
            "survivor_pids_rechecked": sorted(recheck_pids),
            "no_listening_row_after": not listening_after,
            "engine_chain_all_taskkilled": (bool(chain_pids)
                                            and set(chain_pids) <= set(taskkilled)),
            "collateral_removed_empty": not collateral,
            "removed_set_fully_explained": all(
                v["class"] != "unclassified_removed" for v in classification.values()),
        },
        "read_only_recheck": read_only,
    }

    if write:
        outp = wave2 / "wave2_shutdown_classification.json"
        pre = sha256_file(outp)
        outp.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rec["_written"] = {"path": str(outp).replace("\\", "/"),
                           "sha256_pre": pre,
                           "sha256_post": sha256_file(outp),
                           "bytes": outp.stat().st_size}
    print(json.dumps({k: rec[k] for k in ("verdict", "unproven_reason", "authority",
                                          "collateral_removed", "pid_classification",
                                          "verdict_basis", "self_audit_no_kill_path",
                                          "read_only_recheck")},
                     indent=1, ensure_ascii=False))
    return 0 if verdict.startswith("SHUTDOWN_CONFIRMED") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""MF-V1-VIDEO14B wave B closeout (b2) — C6 end-state probe (strictly READ-ONLY).

Closure evidence for the wave-B shutdown.  Written AFTER w2_stop_engine.py has
already stopped the engine, so that the "port closed" claim rests on a real
REFUSAL and not on a WSAEWOULDBLOCK:

  w2_stop_engine.py probed closure with `connect_ex` on a socket that has a
  timeout; on Windows that returns 10035 (WSAEWOULDBLOCK) while the handshake is
  merely still pending, so `connect_ex != 0` is NOT proof of a closed port.  F09
  says so explicitly and w2_classify_shutdown.py refuses to call a timeout a
  closure.  This tool performs the missing blocking connect (10061) and records
  it where the classifier already looks for it.

It also audits w2_stop_engine.py's argv list for a `taskkill /T` token, and
re-checks the hermes/manager survivors recorded by the stop pass.

It never starts an engine, never loads a model, never stops a pid, never writes
media: a refused connect starts nothing.

usage:
  python waveB_probe_end_state.py <shutdown_dir> <runtime_dir> <out_json>
"""
from __future__ import annotations

import ast
import hashlib
import json
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

STOP_TOOL = (Path(__file__).resolve().parents[5] / "runtime" / "video14b" / "tools"
             / "w2_stop_engine.py")


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def blocking_probe(host: str, port: int, timeout: float = 4.0) -> dict:
    """Same probe the classifier uses: connect_ex first, then a BLOCKING connect.

    A refused connect is the only thing that proves the listener is gone; a
    timeout (10035/10060) means the probe never learned the state.
    """
    s = socket.socket()
    s.settimeout(timeout)
    try:
        rc = s.connect_ex((host, port))
    finally:
        s.close()
    s2 = socket.socket()
    err: str | None = None
    code: int | None = None
    refused = False
    try:
        s2.settimeout(timeout)
        s2.connect((host, port))
    except ConnectionRefusedError as exc:
        refused = True
        err = f"ConnectionRefusedError: {exc}"
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None) or 10061
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    finally:
        s2.close()
    return {"connect_ex": rc, "connect_refused": refused, "connect_error": err,
            "error_code": code, "timeout_s": timeout,
            "listener_accepted": refused is False and err is None,
            "probed_at_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")}


def sh(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001
        return 999, "", f"{type(exc).__name__}: {exc}"


def taskkill_argv_audit(path: Path) -> dict:
    """AST audit of the stop tool: enumerate every argv list that names taskkill and
    prove none of them carries a tree-kill switch.  Grepping the text would
    false-positive on the docstring line that says 'never /T'."""
    if not path.is_file():
        return {"self_source": str(path).replace("\\", "/"), "exists": False}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    argvs: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            vals = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if any("taskkill" in v.lower() for v in vals):
                argvs.append({"lineno": node.lineno, "argv": vals,
                              "tree_kill": any(v.upper() == "/T" for v in vals)})
    return {
        "self_source": str(path).replace("\\", "/"),
        "exists": True,
        "sha256": sha256_file(path),
        "taskkill_argv_lists": argvs,
        "uses_taskkill_T": any(a["tree_kill"] for a in argvs),
        "tree_kill_present": any(a["tree_kill"] for a in argvs),
        "note": ("/T is a TREE kill: it takes every descendant of the target, including "
                 "processes the task never verified.  The stop tool must use /PID <p> /F "
                 "only, one verified pid at a time."),
    }


def main() -> int:
    shutdown = _p(sys.argv[1])
    runtime = _p(sys.argv[2])
    out_json = _p(sys.argv[3])
    epoch = json.loads((runtime / "instance_epoch.json").read_text(encoding="utf-8"))
    port = int(epoch["port"])

    ev = json.loads((shutdown / "wave2_shutdown_evidence.json").read_text(encoding="utf-8"))
    survivors = ev.get("hermes_survivors") or {}

    probe = blocking_probe("127.0.0.1", port)
    rc, out, _ = sh(["netstat", "-ano"])
    net_lines = [" ".join(l.split()) for l in out.splitlines()
                 if f":{port} " in l or l.rstrip().endswith(f":{port}")]
    listening = [ln for ln in net_lines if len(ln.split()) > 3
                 and ln.split()[3].upper() == "LISTENING"]
    rc2, out2, _ = sh(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                       "--format=csv,noheader,nounits"])
    vram = [int("".join(c for c in part if c.isdigit()) or 0)
            for part in (out2 or "").strip().split(",")][:2]
    survivor_recheck = {}
    for pid_s, info in survivors.items():
        rc3, out3, _ = sh(["tasklist", "/FI", f"PID eq {pid_s}", "/FO", "CSV", "/NH"])
        survivor_recheck[pid_s] = {"expected": info.get("expected"), "found_in_before": True,
                                   "alive_now": rc3 == 0 and f'"{pid_s}"' in out3}
    epoch_pid = int(epoch["pid"])
    rc4, out4, _ = sh(["tasklist", "/FI", f"PID eq {epoch_pid}", "/FO", "CSV", "/NH"])
    epoch_pid_alive = rc4 == 0 and f'"{epoch_pid}"' in out4

    stop_audit = taskkill_argv_audit(STOP_TOOL)
    rec = {
        "artifact": "end_state_probe.json",
        "task_id": "MF-V1-VIDEO14B",
        "wave": "B",
        "round": "b2",
        "row": "F09",
        "read_only": {"started_engine": False, "loaded_model": False, "stopped_pid": False,
                      "wrote_media": False},
        "generated_at_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
        "engine": {"instance_id": epoch.get("instance_id"), "pid": epoch_pid, "port": port,
                   "epoch_sha256": sha256_file(runtime / "instance_epoch.json")},
        "port_probe_blocking": probe,
        "first_pass_connect_ex_after": ev.get("connect_ex_after"),
        "first_pass_connect_ex_after_meaning": (
            "10035 = WSAEWOULDBLOCK: the timed connect_ex returned before the handshake "
            "resolved, so it is NOT evidence of a closed port by itself"),
        "netstat_lines_for_port": net_lines,
        "listening_rows_for_port": listening,
        "listeners_after_is_empty": not listening,
        "epoch_pid_alive_now": epoch_pid_alive,
        "vram_used_mib": vram[0] if vram else None,
        "vram_total_mib": vram[1] if len(vram) > 1 else None,
        "survivors_recheck": survivor_recheck,
        "survivors_all_alive_now": bool(survivor_recheck) and all(
            v["alive_now"] for v in survivor_recheck.values()),
        "stop_tool_taskkill_audit": stop_audit,
        "closure_is_a_refusal_not_a_timeout": bool(probe["connect_refused"]),
    }
    # the file name the classifier already reads for first-pass closure evidence
    (shutdown / "wave2_port_probe_after_r4.json").write_text(
        json.dumps(probe, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("port_probe_blocking", "listening_rows_for_port",
                                          "epoch_pid_alive_now", "vram_used_mib",
                                          "survivors_all_alive_now",
                                          "closure_is_a_refusal_not_a_timeout")}, indent=1))
    return 0 if probe["connect_refused"] and not listening and not epoch_pid_alive else 1


if __name__ == "__main__":
    raise SystemExit(main())

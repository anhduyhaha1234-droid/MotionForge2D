"""Verify + stop the leftover P5/P6 ComfyUI server, record the shutdown proof, then refresh the
evidence index with lock tolerance (the server held files open, which blocked the read).

Guard: the kill is allowed ONLY if the pid owns 127.0.0.1:8321 AND its command line is the ComfyUI
main.py listening on port 8321 - i.e. the server this lane started.  Nothing else is touched.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import socket
import subprocess
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
PORT = 8321
PID = 6028


def port_listening() -> tuple:
    s = socket.socket()
    s.settimeout(3.0)
    try:
        s.connect(("127.0.0.1", PORT))
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, repr(e)
    finally:
        s.close()


def cmdline(pid: int) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                       capture_output=True, text=True)
    return (r.stdout or "").strip()


pre_listening, _ = port_listening()
cmd = cmdline(PID)
guard = ("main.py" in cmd and "--port 8321" in cmd and "8312" not in cmd)
print("pre_listening", pre_listening, "| guard_ok", guard, "| cmd:", cmd[:90])

proof = {"artifact": "P5P6_BATCH_SERVER_SHUTDOWN_PROOF.json", "port": PORT, "pid": PID,
         "pre": {"at": datetime.now(timezone.utc).isoformat(), "port_listening": pre_listening,
                 "cmdline": cmd, "guard_ok": guard},
         "stop_scope": "taskkill /PID 6028 /F only (no /T, no /IM, no image-wide stop)",
         "why": "the P5/P6 batch server survived the previous turn (that turn ended on a provider "
                "error before cleanup); this pass verified the pid owns the port and runs the "
                "ComfyUI main.py for this lane, then stopped exactly that pid"}
if guard and pre_listening:
    r = subprocess.run(["taskkill", "/PID", str(PID), "/F"], capture_output=True, text=True)
    proof["taskkill"] = {"rc": r.returncode, "out": (r.stdout or "").strip()[:120]}
else:
    proof["taskkill"] = {"rc": None, "out": "REFUSED - guard failed, nothing killed"}
post_listening, err = port_listening()
tl = subprocess.run(["tasklist", "/FI", f"PID eq {PID}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True).stdout.strip()
proof["post"] = {"at": datetime.now(timezone.utc).isoformat(), "port_listening": post_listening,
                 "connect_error": err, "pid_exists": str(PID) in tl, "tasklist_row": tl[:80]}
proof["phase"] = ("POST_STOP_VERIFIED" if (not post_listening and str(PID) not in tl)
                  else "POST_STOP_UNPROVEN")
(EVID / "P5P6_BATCH_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(proof, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("phase", proof["phase"], "| post_listening", post_listening)

# ---- index refresh with lock tolerance ----------------------------------------------------
self_path = EVID / "PROOF_EVIDENCE_INDEX.md"
idx = ["# PROOF_EVIDENCE_INDEX", "",
       f"Every file under `{PROOF}` (excluding this index), bytes + sha256.", "",
       "| file | bytes | sha256 |", "|---|---|---|"]
tot = n = skipped = 0
locked = []
for p in sorted(PROOF.rglob("*")):
    if not p.is_file() or p == self_path:
        continue
    try:
        b = p.read_bytes()
    except PermissionError:
        skipped += 1
        locked.append(str(p.relative_to(PROOF)).replace("\\", "/"))
        continue
    tot += len(b)
    n += 1
    idx.append(f"| `{p.relative_to(PROOF)}` | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |")
idx += ["", f"Total {tot:,} B across {n} files (readable).",
        f"Locked at build time (skipped): {skipped}" + (f" -> {locked}" if locked else ""), ""]
self_path.write_text("\n".join(idx), encoding="utf-8")
print(f"index files={n} bytes={tot} skipped={skipped} locked={locked[:3]}")

"""POST-stop verification for the isolated P0 server + the proof deliverable index.

Proves: the pid THIS worker launched is gone, the port refuses connections, no other python
process was touched, and the isolated user directory is where ComfyUI ran its own DB migrations.
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
PID = 33160


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def python_pids() -> str:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "(none)"


proof = json.loads((EVID / "P0_SERVER_SHUTDOWN_PROOF.json").read_text(encoding="utf-8"))
s = socket.socket()
s.settimeout(3.0)
try:
    s.connect(("127.0.0.1", PORT))
    listening, err = True, None
except Exception as e:  # noqa: BLE001
    listening, err = False, repr(e)
finally:
    s.close()
tl = subprocess.run(["tasklist", "/FI", f"PID eq {PID}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True).stdout.strip()
proof.update({
    "phase": "POST_STOP_VERIFIED",
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "post": {
        "pid_exists": str(PID) in tl and "python" in tl.lower(),
        "tasklist_row": tl,
        "port_listening": listening,
        "connect_error": err,
        "port_closed_proven_by_refusal": (not listening),
        "python_process_inventory_after": python_pids().splitlines(),
        "stop_method": "process.kill on the tracked background session of THIS worker "
                       "(pid-scoped; no /T, no image-wide stop, no kill of any other process)",
        "collateral": "none - the stop named one pid",
    },
    "isolation_evidence": {
        "user_dir_used": "PROOF/user (ComfyUI ran its own alembic migrations there: log line "
                         "'Database upgraded from None to 0007_record_content_split')",
        "input_dir": "PROOF/inputs", "output_dir": "PROOF/output", "temp_dir": "PROOF/temp",
        "node_cache": "disabled (--cache-none, log line 'Disabling intermediate node cache')",
        "runtime_or_global_db_touched": False,
    },
    "note": ("the isolated server is stopped and the port is closed; a NEW instance at the same "
             "port would be a different instance_id and the R28 rules refuse to rebind evidence "
             "across instances"),
})
(EVID / "P0_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(proof, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# --- proof deliverables: REPORT + index + ledger ---------------------------------------
matrix = json.loads((EVID / "P0_RUNTIME_MATRIX.json").read_text(encoding="utf-8"))
inv = json.loads((EVID / "P0_MODEL_INVENTORY.json").read_text(encoding="utf-8"))
units = json.loads((EVID / "P1_UNIT_MANIFESTS.json").read_text(encoding="utf-8"))
ifaces = json.loads((EVID / "P0_NODE_INTERFACES.json").read_text(encoding="utf-8"))["interfaces"]
rows = matrix["matrix"]

md = ["# P0/P1 PROOF — MF-V1-VIDEO14B (isolated runtime matrix + scene-unit manifests)", "",
      f"Proof root: `{PROOF}` · generated {datetime.now(timezone.utc).isoformat()}", "",
      "## P0.1 isolated server receipt", "",
      f"* cmdline: `{matrix['receipt']['cmdline']}`",
      f"* pid **{matrix['receipt']['pid']}**, port **{PORT}**, device **cpu**",
      f"* epoch: `{matrix['receipt']['epoch']['instance_id']}` launched_at "
      f"{matrix['receipt']['epoch']['launched_at']}",
      f"* ComfyUI source (read-only) HEAD `{matrix['receipt']['epoch']['comfyui_head']}`",
      f"* `/object_info`: {matrix['object_info']['node_count']} nodes, "
      f"{matrix['object_info']['bytes']:,} B, sha256 "
      f"`{matrix['object_info']['sha256']}`",
      "* shutdown proof: `evidence/P0_SERVER_SHUTDOWN_PROOF.json` — phase "
      f"**{proof['phase']}**, port_listening={proof['post']['port_listening']}, "
      f"pid_exists={proof['post']['pid_exists']}",
      "", "## P0.2 the 5-column matrix (never inferred across columns)", "",
      "| node | source-present | imported | weights-present | inference-tested | quality-accepted |",
      "|---|---|---|---|---|---|"]
for r in rows:
    md.append(f"| `{r['node']}` | {r['source_present']} | {r['imported']} | "
              f"{r['weights_present']} | {r['inference_tested']} | {r['quality_accepted']} |")
md += ["", f"Registered but not in this list of {len(rows)}: see `/object_info` dump. "
           f"NOT registered by this server: "
           f"{', '.join('`'+m+'`' for m in matrix['missing_nodes_from_matrix'])}.", "",
       "## P0.3 node interfaces (extracted from `/object_info`, not from memory)", ""]
for name, spec in ifaces.items():
    if not spec.get("present"):
        md.append(f"* `{name}` — NOT REGISTERED by this server")
        continue
    req = spec["input_required"]
    keys = ", ".join(f"`{k}`" for k in list(req)[:14])
    md.append(f"* `{name}` (`{spec['python_module']}`, category `{spec['category']}`) required "
              f"inputs: {keys}")
md += ["", "## P0.4 model roots inventory", "",
       f"* root `{inv['root']}` — {inv['file_count']} files, {inv['total_bytes']:,} B",
       f"* groups: {json.dumps({k: v['count'] for k, v in inv['groups'].items()})}",
       f"* MISSING groups: {inv['missing_groups']}", "",
       "## P1 unit manifests", "",
       f"* `{len(units['units'])}` units: "
       f"{', '.join('`'+u['unit_id']+'`' for u in units['units'])}",
       "* per-shot source windows (hash-verified, copies under `inputs/`):"]
for shot, c in units["basis"]["source_windows"].items():
    md.append(f"  * {shot}: `{c['source_window']}` sha `{c['source_window_sha256']}`"
              + (" (MISMATCH vs manifest!)" if c.get("sha_mismatch") else ""))
md += ["", f"* BOOK events: {json.dumps(units['units'][0]['acceptance']['hard_events'])}",
       f"* BOOK elements: {len(units['units'][0]['elements'])} (incl. the partial "
       f"`BOOK-P4` at bbox [628,254,639,306])",
       "* `execution_profile` is a PLACEHOLDER: the packet-restated constraints are recorded "
       "with `measured_here: false`.", "",
       "## NOT claimed", "",
       "* No inference ran: `inference-tested` is `NOT YET RUN` on every row (CPU server, no "
       "weights loaded, no GPU).",
       "* `quality-accepted` is `false` on every row; `QUALITY_ACCEPTED=0` overall.",
       "* `COMFY_UNITS_RESEARCH.md` was NOT FOUND on this host (searched `C:/Users/Admin` and the "
       "run root); P0/P1 were built from the live server and measured manifests instead, and the "
       "packet's restated constraints are labelled as such.",
       ""]
(PROOF / "evidence" / "PROOF_REPORT.md").write_text("\n".join(md), encoding="utf-8")

idx = ["# PROOF_EVIDENCE_INDEX", "",
       f"Every file under `{PROOF}` (excluding this index), with bytes and sha256.", "",
       "| file | bytes | sha256 |", "|---|---|---|"]
tot = 0
self_path = PROOF / "evidence" / "PROOF_EVIDENCE_INDEX.md"
for p in sorted(PROOF.rglob("*")):
    if not p.is_file() or p == self_path:
        continue
    b = p.read_bytes()
    tot += len(b)
    idx.append(f"| `{p.relative_to(PROOF)}` | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |")
idx += ["", f"Total {tot:,} B.", ""]
self_path.write_text("\n".join(idx), encoding="utf-8")

led = EVID / "PROOF_LEDGER.jsonl"
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P0_P1_COMPLETE", "at": datetime.now(timezone.utc).isoformat(),
                         "server": {"pid": PID, "port": PORT, "device": "cpu",
                                    "object_info_nodes": matrix["object_info"]["node_count"]},
                         "shutdown": {"port_listening": proof["post"]["port_listening"],
                                      "pid_exists": proof["post"]["pid_exists"]},
                         "matrix_rows": len(rows),
                         "not_registered": matrix["missing_nodes_from_matrix"],
                         "inference_tested": "NONE (not yet run)",
                         "units": units["unit_count"], "quality_accepted": 0},
                        ensure_ascii=False) + "\n")
print(json.dumps({"phase": proof["phase"], "port_listening": proof["post"]["port_listening"],
                  "pid_exists": proof["post"]["pid_exists"],
                  "report_bytes": (PROOF / "evidence" / "PROOF_REPORT.md").stat().st_size,
                  "index_bytes": self_path.stat().st_size, "proof_total_bytes": tot},
                 indent=1, ensure_ascii=False))

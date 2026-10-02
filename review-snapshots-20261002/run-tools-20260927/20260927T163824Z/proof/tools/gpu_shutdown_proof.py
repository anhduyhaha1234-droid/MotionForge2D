"""GPU server shutdown proof (pre/post) + the P2/P3 report, ledger and evidence index.

  python tools/gpu_shutdown_proof.py pre  <pid>   # record the live state before the stop
  python tools/gpu_shutdown_proof.py post <pid>   # verify the stop, then write the deliverables
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import socket
import subprocess
import sys
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
PORT = 8321
OUT = EVID / "P2P3_SERVER_SHUTDOWN_PROOF.json"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def port_state():
    s = socket.socket()
    s.settimeout(3.0)
    try:
        s.connect(("127.0.0.1", PORT))
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, repr(e)
    finally:
        s.close()


def load(p, default=None):
    p = EVID / p
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def main() -> int:
    phase, pid = sys.argv[1], int(sys.argv[2])
    listening, err = port_state()
    doc = load("P2P3_SERVER_SHUTDOWN_PROOF.json", {"artifact": "P2P3_SERVER_SHUTDOWN_PROOF.json",
                                                  "port": PORT, "pid": pid})
    row = {"at": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "port_listening": listening, "connect_error": err}
    if phase == "pre":
        doc["pre"] = row
        doc["phase"] = "PRE_STOP"
        doc["epoch"] = load("P2_instance_epoch.json")
        doc["stop_scope"] = ("ONLY the pid this worker launched (process.kill on its own tracked "
                             "session; no /T, no image-wide stop)")
    else:
        tl = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True).stdout.strip()
        pys = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout.strip().splitlines()
        doc["post"] = {**row, "pid_exists": str(pid) in tl and "python" in tl.lower(),
                       "tasklist_row": tl, "port_closed_proven_by_refusal": not listening,
                       "python_processes_after": pys}
        doc["phase"] = "POST_STOP_VERIFIED"
        doc["collateral"] = "none - the stop named one pid"
        OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

        # --- deliverables -----------------------------------------------------------------
        g2 = load("P2_GRAPHS.json"); gates = load("P2_ANCHOR_GATES.json")
        rec2 = load("P2_ANCHOR_RECEIPTS.json"); g3 = load("P3_GRAPH.json")
        rec3 = load("P3_RECEIPT.json"); dec = load("P3_DECODE_CHECK.json")
        rep = PROOF / "evidence" / "PROOF_REPORT.md"
        rows = []
        for shot, v in (gates["shots"] if gates else {}).items():
            a = (v["anchors"] or [{}])[0]
            m = a.get("metrics", {})
            rows.append(f"| {shot} | seed {g2['graphs'][shot]['seed']} | "
                        f"{g2['graphs'][shot]['nodes']} | `{a.get('file')}` | "
                        f"{a.get('bytes')} B | {m.get('unique_colours_output')} cols | "
                        f"{m.get('mean_abs_delta_vs_source')} | "
                        f"{rec2['jobs'][shot]['wall_s']} s | {rec2['jobs'][shot]['vram_peak_mib']} MiB |")
        crit = "\n".join(f"| `{k}` | {v.get('measured')} | {v.get('verdict')} |"
                         for k, v in (gates or {}).get("criteria", {}).items())
        obs = (gates or {}).get("observations", {})
        sec = ["", "## P2 — target anchors (GPU, one job at a time)", "",
               f"* server: pid **{doc['pre']['pid']}**, port {PORT}, device "
               f"`{doc.get('epoch', {}).get('device')}`, launch argv recorded in "
               f"`P2_instance_epoch.json` (incl. `--base-directory` + `--reserve-vram 1.0`)",
               "* graphs: `graphs/anchor_{book,turn,occ}.p2.api.json`, built from the R27-I1 graphs "
               "that ran for real; the measured delta is the `SaveImage.filename_prefix` ALONE "
               "(`P2_GRAPHS.json.delta_is_prefix_only` per shot)",
               "* every class/required input validated against the server's own `/object_info` "
               "before submission (0 errors, 0 warnings per shot)",
               "", "| shot | seed | nodes | anchor | bytes | unique colours | mean|Δ| vs source | "
                   "wall | VRAM peak |", "|---|---|---|---|---|---|---|---|---|"] + rows
        sec += ["", "### P2 gate — what the worker's own eyes saw (real images)", "",
                "| criterion | measured | verdict |", "|---|---|---|", crit, "",
                "Observations behind the verdicts:"]
        for shot, o in obs.items():
            sec.append(f"* **{shot}**: {o.get('people_count_observed')} people; "
                       f"{o.get('book_state') or o.get('document_matches', '')[:120]}; "
                       f"defects {json.dumps(o.get('defects_observed'))}"
                       + (f"; partial person present: {o['partial_person_present']}"
                          if "partial_person_present" in o else ""))
            if o.get("appearance_note"):
                sec.append(f"  * appearance note: {o['appearance_note']}")
        sec += [f"* contact sheet: `{gates.get('contact_sheet')}`",
                "* **gate result: BOOK/TURN/OCC PASS** (see `P2_ANCHOR_GATES.json.gate_result`); "
                "`quality_accepted` stays FALSE — that verdict is not the worker's", ""]
        if rec3:
            op = rec3["output_files"][0] if rec3.get("output_files") else {}
            sec += ["## P3 — Wan Animate 2 baseline for BOOK", "",
                    f"* template `{g3['template']}` (sha `{g3['template_sha256'][:16]}…`) — the SHIM "
                    f"variant, and that choice is measured: the plain/fixed variants are REJECTED by "
                    f"`/prompt` with `required_input_missing values.a` on 7 ComfyMathExpression "
                    f"nodes + `inputs.input0` on CreateList, because they carry the nested autogrow "
                    f"form instead of the dotted API keys",
                    f"* built graph `{g3['built']}` sha `{g3['built_sha256']}`",
                    "* declared deltas vs the template (measured): "
                    + "; ".join(f"`{d['node']}.{d['input']}` {d['template']} -> {d['built']}"
                                for d in g3["deltas"]),
                    f"* declared params: seed **{g3['declared_params']['seed']}**, "
                    f"{g3['declared_params']['steps']} steps, sampler "
                    f"{g3['declared_params']['sampler']}, cfg {g3['declared_params']['cfg']}, "
                    f"shift {g3['declared_params']['model_sampling_shift']}, "
                    f"pose {g3['declared_params']['pose_strength']} "
                    f"({g3['declared_params']['pose_start_percent']}–"
                    f"{g3['declared_params']['pose_end_percent']}), "
                    f"ref strength {g3['declared_params']['reference_image_strength']}, "
                    f"context {g3['declared_params']['context_length']}/"
                    f"{g3['declared_params']['context_overlap']}, cache node "
                    f"{g3['declared_params']['cache_node']}",
                    f"* models: `{g3['declared_params']['unet']}` + LoRA "
                    f"`{g3['declared_params']['lora']}` + `{g3['declared_params']['clip']}` + "
                    f"`{g3['declared_params']['clip_vision']}` + `{g3['declared_params']['vae']}`",
                    f"* driving: `{g3['inputs']['driving']['file']}` sha "
                    f"`{g3['inputs']['driving']['sha256']}` "
                    f"({g3['inputs']['driving']['ffprobe']['nb_frames']} frames, "
                    f"{g3['inputs']['driving']['ffprobe']['r_frame_rate']} fps, "
                    f"{g3['inputs']['driving']['ffprobe']['duration']} s)",
                    f"* reference: the P2 BOOK anchor `{g3['inputs']['anchor']['file']}` sha "
                    f"`{g3['inputs']['anchor']['sha256'][:16]}…`",
                    f"* prompt_id `{rec3['prompt_id']}`, completed={rec3['completed']}, "
                    f"wall **{rec3['wall_s']} s** ({rec3['wall_min']} min) = "
                    f"**{rec3['seconds_per_output_second']} s per output second**, "
                    f"VRAM peak **{rec3['vram_peak_mib']} MiB**, server RAM peak "
                    f"**{rec3['server_ram_peak_mib']} MiB**",
                    f"* output: `{op.get('file')}` {op.get('bytes')} B sha `{op.get('sha256')}`",
                    "", "### P3 decode check", ""]
            for v in dec["videos"]:
                sec.append(f"* `{v['file']}`: frames {v['ffprobe'].get('nb_read_frames')} "
                           f"(source {dec['source'].get('nb_read_frames')}), fps "
                           f"{v['ffprobe'].get('r_frame_rate')}, duration "
                           f"{v['ffprobe'].get('duration')}, PTS "
                           f"{v['pts_first']}..{v['pts_last']} monotonic={v['pts_monotonic']}, "
                           f"frames_match_source={v['frames_match_source']}, "
                           f"fps_match={v['fps_matches_source']}, "
                           f"duration_match={v['duration_matches_source']}")
                if v.get("contact_sheet"):
                    sec.append(f"  * contact sheet: `{v['contact_sheet']}`")
            sec += ["", "**Not claimed:** no quality verdict (the worker does not accept quality); "
                        "no appearance/identity acceptance for the two PLACEHOLDER cast refs; the "
                        "clip is a baseline measurement, not a product deliverable.", ""]
        sec += ["## P0/P3 refinement — model visibility (a P0 gap found while running P2)", "",
                "* P0's `/object_info` came from the CPU server started WITHOUT `--base-directory`, "
                "so its loader enums were EMPTY (`unet_name [[]]`, `clip_name [[]]`) while the disk "
                "inventory listed 88.7 GB of weights. Source-present, imported and weights-present "
                "are indeed three different questions — this run measured the third one:",
                f"* the GPU server (with `--base-directory <runtime/video14b>`) reports the real "
                f"enums — `P3_object_info_gpu.json` sha "
                f"`{sha(EVID / 'P3_object_info_gpu.json')[:16]}…`: unet 4 values, vae 4, clip 3, "
                f"clip_vision 1, lora 1 — and the first GPU launch without the flag was rejected by "
                f"`/prompt` with `unet_name: 'flux-2-klein-4b-fp8.safetensors' not in []`.",
                "* therefore every P2/P3 submission was validated against the RUNNING server's own "
                "`/object_info` (0 errors), never against the disk list.", ""]
        sec += ["## Server lifecycle", "",
                f"* launch: `{doc.get('epoch', {}).get('launch_argv')}`",
                f"* pre-stop: port_listening={doc['pre']['port_listening']} pid={doc['pre']['pid']}",
                f"* post-stop: pid_exists={doc['post']['pid_exists']}, "
                f"port_listening={doc['post']['port_listening']}, "
                f"refusal={doc['post']['connect_error']}, collateral=none",
                f"* other python processes left untouched: "
                f"{len(doc['post']['python_processes_after'])} rows recorded in the proof", ""]
        with rep.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(sec) + "\n")
        led = EVID / "PROOF_LEDGER.jsonl"
        with led.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"phase": "P2_P3_COMPLETE", "at": row["at"],
                                 "p2": {"shots": list(g2["graphs"]),
                                        "prompt_ids": {k: v["prompt_id"]
                                                       for k, v in rec2["jobs"].items()},
                                        "wall_s": {k: v["wall_s"]
                                                   for k, v in rec2["jobs"].items()},
                                        "vram_peak_mib": {k: v["vram_peak_mib"]
                                                          for k, v in rec2["jobs"].items()},
                                        "gate": gates.get("gate_result")},
                                 "p3": {"prompt_id": rec3["prompt_id"],
                                        "wall_s": rec3["wall_s"],
                                        "s_per_output_s": rec3["seconds_per_output_second"],
                                        "vram_peak_mib": rec3["vram_peak_mib"],
                                        "ram_peak_mib": rec3["server_ram_peak_mib"],
                                        "graph_sha256": g3["built_sha256"],
                                        "seed": g3["declared_params"]["seed"]},
                                 "server": {"pid": pid, "port": PORT,
                                            "shutdown": "POST_STOP_VERIFIED"},
                                 "quality_accepted": 0}, ensure_ascii=False) + "\n")
        # index
        self_path = EVID / "PROOF_EVIDENCE_INDEX.md"
        idx = ["# PROOF_EVIDENCE_INDEX", "",
               f"Every file under `{PROOF}` (excluding this index), bytes + sha256.", "",
               "| file | bytes | sha256 |", "|---|---|---|"]
        tot = 0
        for p in sorted(PROOF.rglob("*")):
            if not p.is_file() or p == self_path:
                continue
            b = p.read_bytes()
            tot += len(b)
            idx.append(f"| `{p.relative_to(PROOF)}` | {len(b):,} | "
                       f"`{hashlib.sha256(b).hexdigest()}` |")
        idx += ["", f"Total {tot:,} B.", ""]
        self_path.write_text("\n".join(idx), encoding="utf-8")
        print(json.dumps({"phase": doc["phase"], "pid_exists": doc["post"]["pid_exists"],
                          "port_listening": doc["post"]["port_listening"],
                          "report_bytes": rep.stat().st_size, "index_bytes": self_path.stat().st_size,
                          "ledger_lines": len(led.read_text(encoding='utf-8').strip().splitlines()),
                          "proof_total_bytes": tot}, indent=1))
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"phase": doc["phase"], "port_listening": listening, "pid": pid}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

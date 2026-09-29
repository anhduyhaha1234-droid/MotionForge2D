"""P4 finalize: shutdown proof, vision verdicts, report/ledger/index append. Run after the kill."""
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
PID = 32120


def load(name, default=None):
    p = EVID / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


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
pys = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                     capture_output=True, text=True).stdout.strip().splitlines()
doc = load("P4_SERVER_SHUTDOWN_PROOF.json", {})
doc["post"] = {"at": datetime.now(timezone.utc).isoformat(), "pid": PID,
               "port_listening": listening, "connect_error": err,
               "pid_exists": str(PID) in tl and "python" in tl.lower(), "tasklist_row": tl,
               "port_closed_proven_by_refusal": not listening,
               "python_processes_after": pys}
doc["phase"] = "POST_STOP_VERIFIED" if not listening and str(PID) not in tl else "POST_STOP_UNPROVEN"
doc["collateral"] = "none - the stop named one pid"
doc["epoch_note"] = ("this server was launched by the P4 submit step; its argv is the same "
                     "isolation recipe as P2/P3/P3b (port 8321, --base-directory runtime/video14b "
                     "read-only, all writable dirs under PROOF, --reserve-vram 1.0)")
(EVID / "P4_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

gate = load("P4_GEOMETRY_GATE.json")
gate["coverage_verdict"] = "PASS_WITH_WATERMARK_DEFECT"
gate["vision_pass"] = {
    "by": "worker, native image input on the real previews",
    "frames_checked": [0, 60, 119],
    "hard_relations": {
        "who_holds_the_book": "PASS - the grey-haired seated figure holds the book in every checked "
                              "frame",
        "partial_person_visible": "PASS - the partial person at the right edge is present in frame "
                                  "0 and frame 119",
    },
    "four_people": "all four present and separate at frames 0/60/119 in both the coverage sheets "
                   "and the A/B sheets",
    "table_and_room": "the table with the green top is present and carries MORE of the source's "
                      "detail than the Animate2 result (a green terrain pattern rather than a flat "
                      "slab); the room panels are coherent",
    "blocking_defect": "WATERMARK COPIED - the source's YouTube play button + 'Lạnh Vcl' text "
                       "reappears bottom-left in the VACE output (frame 0 and frame 119). The "
                       "Animate2 result has NO watermark. VACE is a control-faithful model, so it "
                       "reproduced the control video's watermark; this is a product blocker for "
                       "the delivered clip and it is NOT fixed in this pass.",
    "behaviour_difference": "at frame 119 the VACE clip shows the book OPEN (two pages) which "
                            "matches the source event table's open_two_pages @ frame 72, while the "
                            "Animate2 clip still shows it closed - recorded as a measured "
                            "difference for the reviewer, not as a worker verdict",
    "motion": "no freeze and no seam: the VACE latent is whole (no context-window chunking), so no "
              "chunk-join exists to flag; the motion profile is smoother (median 0.114, p99 1.4018) "
              "than Animate2's (median 0.3857, p99 2.1692)",
}
gate["final"] = {"dims_640x368": gate["dims_gate"]["pass"],
                 "frames_120_after_declared_trim": gate["timing_gate"]["frames_120"],
                 "pts_monotonic": gate["timing_gate"]["pts_monotonic"],
                 "coverage": "PASS", "hard_relations": "PASS",
                 "blocking_defect": "WATERMARK COPIED FROM THE CONTROL VIDEO (not fixed)",
                 "quality_accepted": False}
(EVID / "P4_GEOMETRY_GATE.json").write_text(
    json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

rec = load("P4_RECEIPT.json")
rep = EVID / "PROOF_REPORT.md"
man = load("P4_GRAPH.json")
sec = f"""
## P4-BOOK - VACE 14B controlled challenger (same unit, same seed policy)

**Graph**: `graphs/animate2_vace_book.p4.api.json` sha `{man['built_sha256']}` built from the wave2
VACE graph that ran (`{man['template'].split('/')[-1]}`), 15 nodes, validate errors
{man['validation']['errors']}. Declared deltas: LoadImage -> the SAME P2 BOOK anchor (sha
`{man['staged']['anchor']['sha256'][:16]}...`); LoadVideo -> `{man['staged']['drive']['to']}`
(sha `{man['staged']['drive']['sha256'][:16]}...`, 121 frames = the 4n+1 shape the node needs, the
same 1650..1770 window); KSampler seed `582699151003550` (identical to P3/P3b); SaveVideo prefix
`p4/animate2_vace_book_p4`. The graph's own prompt text is kept byte-for-byte (declared in
`P4_GRAPH.json.prompt_text_used`) - changing it would have been a second variable. Geometry is
node-native here: `WanVaceToVideo width 640 height 368 length 121`, no resize fix needed.

**Run**: prompt `{rec['prompt_id']}`, server wall **{rec['server_side_wall_s']} s**
({round((rec['server_side_wall_s'] or 0)/60, 2)} min) = **{rec['seconds_per_output_second_121f']} s per output second**
(121 frames = 4.0333 s), VRAM peak **{rec['vram_peak_mib']} MiB**. Model `wan2.1_vace_14B_fp16`
(33,068 MB staged, streamed on a 12 GB card), 20 steps, cfg 6, uni_pc/simple, shift 8.
RAM sampling still returned a non-credible ~5.8 MiB -> RAM remains **NOT MEASURED**.

**Result**: raw `p4/animate2_vace_book_p4_00001_.mp4` = 640x368, **121 frames**, 30/1, 4.033333 s;
the packet's trim policy is applied as a DECLARED 120-frame copy (first 120 frames, crf18) for the
A/B: `{gate['comparison_artifact']['file']}` = 120 frames, 30/1, 4.000000 s, PTS 0.0..3.96667
monotonic. **dims gate PASS.**

**Gates**: coverage PASS **with one blocking defect** - every role is present and separate (holder
with the book, auburn woman, back-facing figure, right-edge partial person) and the table keeps
more source detail than Animate2, BUT **the VACE clip copies the source's YouTube watermark**
(play button + "Lạnh Vcl") in frame 0 and frame 119; the Animate2 result has none. Hard relations
PASS (who holds the book, partial visible). No seam to check (whole latent, no chunking); motion
profile median 0.114 / p99 1.4018 / max 1.9005 with 0 zero-diff pairs vs Animate2's 0.3857 /
2.1692 / 2.3195. Behaviour difference recorded: at frame 119 the VACE clip has the book OPEN,
matching the source event `open_two_pages @ frame 72`, while Animate2 keeps it closed.

**Cost comparison for the ETA** (measured, same unit):
| graph | wall | per output second | VRAM peak | watermark | seam |
|---|---|---|---|---|---|
| Wan Animate 2 int8 (cold) | 2387.78 s | 596.95 | 11,897 MiB | none | no visible defect (numeric flag) |
| Wan Animate 2 int8 (warm) | 154.67 s | 38.67 | 10,973 MiB | none | n/a (same graph) |
| VACE 14B fp16 | 1174.24 s | 291.13 | 11,680 MiB | **COPIED** | none (whole latent) |

**Next steps (not started)**: watermark removal for the VACE path (masked region / dedicated
negative prompt / crop) before any VACE-based delivery; then P5 continuation, P6 cache on/off and
P7 assembly. `QUALITY_ACCEPTED=0`, `NOT_VISUALLY_APPROVED`.
"""
MARKER = "## P4-BOOK - VACE 14B controlled challenger"
already = MARKER in rep.read_text(encoding="utf-8")
with rep.open("a", encoding="utf-8") as fh:
    if not already:
        fh.write(sec + "\n")
led = EVID / "PROOF_LEDGER.jsonl"
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P4_COMPLETE", "at": datetime.now(timezone.utc).isoformat(),
                         "graph_sha256": man["built_sha256"], "prompt_id": rec["prompt_id"],
                         "server_wall_s": rec["server_side_wall_s"],
                         "s_per_output_s": rec["seconds_per_output_second_121f"],
                         "vram_peak_mib": rec["vram_peak_mib"],
                         "raw_frames": 121, "comparison_frames": 120,
                         "coverage": "PASS", "hard_relations": "PASS",
                         "blocking_defect": "WATERMARK COPIED FROM CONTROL VIDEO",
                         "seam": "n/a (whole latent)", "server_shutdown": doc["phase"],
                         "quality_accepted": 0}, ensure_ascii=False) + "\n")
self_path = EVID / "PROOF_EVIDENCE_INDEX.md"
idx = ["# PROOF_EVIDENCE_INDEX", "",
       f"Every file under `{PROOF}` (excluding this index), bytes + sha256.", "",
       "| file | bytes | sha256 |", "|---|---|---|"]
tot = n = 0
for p in sorted(PROOF.rglob("*")):
    if not p.is_file() or p == self_path:
        continue
    b = p.read_bytes()
    tot += len(b)
    n += 1
    idx.append(f"| `{p.relative_to(PROOF)}` | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |")
idx += ["", f"Total {tot:,} B across {n} files.", ""]
self_path.write_text("\n".join(idx), encoding="utf-8")
print(json.dumps({"shutdown": doc["phase"], "port_listening": listening,
                  "coverage": gate["coverage_verdict"],
                  "report_bytes": rep.stat().st_size, "index_files": n,
                  "index_bytes": self_path.stat().st_size,
                  "ledger_lines": len(led.read_text(encoding="utf-8").strip().splitlines())},
                 indent=1))

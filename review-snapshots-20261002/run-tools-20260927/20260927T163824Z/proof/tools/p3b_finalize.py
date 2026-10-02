"""P3b finalize: vision verdicts, receipt repair, shutdown proof, report/ledger/index append.

Run AFTER the server pid has been stopped.
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
PID = 26540


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(name, default=None):
    p = EVID / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


# ---- 1. post-stop proof -------------------------------------------------------------------
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
doc = load("P3B_SERVER_SHUTDOWN_PROOF.json", {})
doc["post"] = {"at": datetime.now(timezone.utc).isoformat(), "pid": PID,
               "port_listening": listening, "connect_error": err,
               "pid_exists": str(PID) in tl and "python" in tl.lower(), "tasklist_row": tl,
               "port_closed_proven_by_refusal": not listening}
doc["phase"] = "POST_STOP_VERIFIED" if not listening and str(PID) not in tl else "POST_STOP_UNPROVEN"
(EVID / "P3B_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# ---- 2. vision verdicts -------------------------------------------------------------------
gate = load("P3B_GEOMETRY_GATE.json")
gate["coverage_verdict"] = "PASS"
gate["coverage_vision"] = {
    "inspected_by": "worker, native image input on the real previews",
    "frames_checked": [0, 60, 119],
    "frame0": "all four people present and separate: grey-haired seated holder with the CLOSED "
              "blue book, auburn woman in the magenta dress, dark-haired figure seen from BEHIND "
              "at the right, and the PARTIAL person cut by the RIGHT frame edge (magenta/violet); "
              "the table with the green top is back, the room panels (cyan/tan/brown pillar) match "
              "the source layout; no watermark",
    "frame60": "same four people, table + chairs present, no melting/duplicated limbs, no text",
    "frame119": "same four people still separate at the last frame, table present, no degradation",
    "what_changed_vs_the_p3_portrait_run": "the table, the back-facing figure and the right-edge "
                                           "partial person that the 480x848 centre-crop had "
                                           "removed are visible again - the coverage defect is "
                                           "fixed",
    "no_black_pad_bars_seen": "the 4+4 row pad is conditioning input only: the pad is fed to the "
                              "pose/reference chain, the OUTPUT frame is generated at 640x368, so "
                              "no black bars appear in the delivered frames (confirmed on all "
                              "three previews)",
}
gate["seam"]["vision_reading"] = {
    "strip": "previews/p3b_seam_strip.png", "frames": "68..96",
    "reading": "the tiles are visually continuous across the join: no repeated tile, no freeze, no "
               "light/colour pop, no body duplication. Around f80-f86 the auburn woman's arm/hand "
               "rises to her chest and the holder's head shifts slightly - that is real motion, "
               "which is what the elevated frame-to-frame diffs measure",
    "disposition": "NO_VISIBLE_SEAM_DEFECT - the numeric flag (clip max 2.3195 at 85->86 vs p99 "
                   "2.1692, join pair 80->81 at 2.1582) is retained in this file for the reviewer; "
                   "it is a motion-rate elevation, not a discontinuity",
}
gate["final"] = {"dims_640x368": gate["dims_gate"]["pass"],
                 "frames_120_fps_30_1_duration_4s": all(
                     [gate["timing_gate"]["frames_120"], gate["timing_gate"]["fps_30_1"],
                      gate["timing_gate"]["duration_4s"]]),
                 "pts_monotonic": gate["timing_gate"]["pts_monotonic"],
                 "coverage": "PASS", "seam": "NO_VISIBLE_SEAM_DEFECT (numeric flag retained)",
                 "quality_accepted": False}
(EVID / "P3B_GEOMETRY_GATE.json").write_text(
    json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# ---- 3. receipt repair (the submit script looked in an empty p3b/ at that moment) ----------
rec = load("P3B_RECEIPT.json")
recon = load("P3B_ARTIFACT_RECONCILIATION.json")
rec["output_files"] = [{"file": m["to"], "from_run_path": m["from"], "bytes": m["bytes"],
                        "sha256": m["sha256_after"], "ffprobe": m["ffprobe"]}
                       for m in recon["relocated"]]
rec["output_count"] = len(rec["output_files"])
rec["receipt_repair"] = ("the submit script's own collect step found 0 files because the graph "
                         "inherited the p3/ SaveVideo prefix; the media were located, verified and "
                         "relocated by p3b_reconcile.py - see P3B_ARTIFACT_RECONCILIATION.json")
rec["warm_run_note"] = ("this run was WARM (the model was already staged from the geometry run's "
                        "predecessor): server wall 154.67 s vs 2387.78 s cold; 38.67 s per output "
                        "second vs 596.95 - use the WARM number for ETA once the server is up")
rec["dims_measured"] = [m["ffprobe"].get("width") for m in rec["output_files"]][:1] and \
    [rec["output_files"][0]["ffprobe"].get("width"),
     rec["output_files"][0]["ffprobe"].get("height")]
(EVID / "P3B_RECEIPT.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")

# ---- 4. report + ledger + index -----------------------------------------------------------
rep = EVID / "PROOF_REPORT.md"
g3b = load("P3B_GRAPH.json")
sec = f"""
## P3b - geometry fix (portrait -> source aspect) and rerun

**Defect (from P3)**: node `672:600 ResizeImageMaskNode` carried a hard-coded
`482x854, crop="center"`, so every driving frame was centre-cropped and the latent came out
480x848 portrait - the table, the back-facing figure and the right-edge partial BOOK-P4 were cut
off (coverage U06 FAIL), which is a template-inherited GEOMETRY fault, not a model fault.

**Fix (declared, one variable: geometry)**: `crop="disabled"` is not the answer - the node's own
tooltip (nodes_post_processing.py:440) says it *stretches*. The registered node `ResizeAndPadImage`
(comfy_extras/nodes_images.py:594-641) scales with `min(fit)` and pads CENTERED, so:
`672:595.images -> P3B_PAD (ResizeAndPadImage 640x368, black, area) -> 672:596 GetImageSize ->
672:587 WanAnimate2ToVideo.width/height`, and the same pad now feeds `pose_video` and `672:599`.
640x360 with scale 1.0 becomes 640x360 content + 4 rows top + 4 rows bottom = **640x368 with the
full frame kept**. `672:590` (reference resize) takes its dims from `672:596`, so the 640x368
anchor goes through a centre-crop resize that is the identity. Models/LoRA/steps/sampler/seed
UNCHANGED (seed 582699151003550).
Graph: `graphs/animate2_book.p3b.api.json` sha `{g3b['built_sha256']}` - diff = exactly
{json.dumps(g3b['diff_nodes'])} (validate errors {g3b['validation']['errors']}).

**Run**: prompt `d1f4e097-458d-4bd4-8049-fe6da26f91c1`, server wall **154.67 s** (WARM: the model
was already staged, 34 s init + ~9 s/step then a second pass at 3.9 s/step) =
**38.67 s per output second** vs 596.95 cold; VRAM peak 10,973 MiB; RAM peak 5.7 MiB reported by
the ctypes sampler = **still not credible, treat RAM as NOT MEASURED** (the value is ~3 orders of
magnitude below the working set; the sampler is reported as suspect rather than trusted).

**Result (all measured)**: `p3b/animate2_book_p3b_00001_.mp4` = **640x368**, 120 frames, 30/1,
4.000000 s, PTS 0.0..3.96667 monotonic; `00003` = the drive|generated composite 1294x368;
`00002/00004` = single-frame stills. **dims == target: PASS.**

**Coverage gate (vision, frames 0/60/119)**: PASS - the four people are back and separate (holder +
closed blue book, auburn woman in magenta, dark-haired from behind, PARTIAL person at the right
frame edge) and the table with the green top is visible again. No black pad bars in the delivered
frames: the pad is conditioning only, the frame itself is generated at 640x368.

**Seam gate (chunk 81 / overlap 8)**: pairs 68->96 were measured. The clip median diff is 0.3857,
p99 2.1692, max 2.3195; the join pair 80->81 is 2.1582 and 85->86 is 2.3195 (the clip max).
`zero_diff_pairs: 0` over the whole clip - no freeze, no duplicate. Visual reading of the strip
(`previews/p3b_seam_strip.png`): continuous; the elevation coincides with the auburn woman's arm
rising to her chest - motion rate, not a discontinuity. Disposition: **NO_VISIBLE_SEAM_DEFECT**, the
numeric flag kept for the reviewer.

**Incident (self-found, disclosed, no evidence lost)**: the P3b graph inherited the SaveVideo
prefix `p3/animate2_book_p3`, so the first P3b run wrote 00005..00008 into `output/p3/`. Verified
BEFORE touching anything that all four P3 files still match their recorded sha256 (ComfyUI
continued the numbering instead of overwriting), then moved the four new files into `output/p3b/`
with the mapping + hashes in `P3B_ARTIFACT_RECONCILIATION.json`. No rerun: the SaveVideo prefix
does not enter the computation, so a second job would only rename identical bytes - a footgun note
sits in that file for the next round.

`QUALITY_ACCEPTED=0`, `NOT_VISUALLY_APPROVED` - the deltas above are measurements for
BENCH/DEMO/Codex, not an acceptance.
"""
MARKER = "## P3b - geometry fix"
already = MARKER in rep.read_text(encoding="utf-8")
with rep.open("a", encoding="utf-8") as fh:
    if not already:
        fh.write(sec + "\n")
led = EVID / "PROOF_LEDGER.jsonl"
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P3B_COMPLETE", "at": datetime.now(timezone.utc).isoformat(),
                         "defect_fixed": "672:600 482x854 center-crop -> ResizeAndPadImage 640x368",
                         "graph_sha256": g3b["built_sha256"],
                         "prompt_id": rec["prompt_id"], "server_wall_s": 154.67,
                         "s_per_output_s_warm": 38.67, "s_per_output_s_cold_p3": 596.95,
                         "vram_peak_mib": rec.get("vram_peak_mib"),
                         "dims": rec["dims_measured"], "coverage": "PASS",
                         "seam": "NO_VISIBLE_SEAM_DEFECT (numeric flag retained)",
                         "incident": "prefix inherited -> outputs relocated, P3 evidence intact",
                         "server_shutdown": doc["phase"], "quality_accepted": 0},
                        ensure_ascii=False) + "\n")
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
                  "coverage": gate["coverage_verdict"], "seam": gate["seam"]["verdict"],
                  "report_bytes": rep.stat().st_size, "index_files": n, "index_bytes": self_path.stat().st_size,
                  "ledger_lines": len(led.read_text(encoding="utf-8").strip().splitlines())}, indent=1))

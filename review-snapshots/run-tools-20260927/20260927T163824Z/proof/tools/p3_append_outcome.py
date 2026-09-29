"""Append the measured P3 outcome, the failure/taxonomy reading and the honest gaps to
PROOF_REPORT.md, then re-append the ledger line with the final numbers."""
from __future__ import annotations

import json
import pathlib
import subprocess
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
rep = EVID / "PROOF_REPORT.md"
rec = json.loads((EVID / "P3_RECEIPT.json").read_text(encoding="utf-8"))
# the SUBMIT script won the write race for the receipt; the COLLECTOR (which polled the same
# prompt_id, no second submission) printed the server-side numbers to its stdout, so read them
# from there and disclose the overwrite.
col = json.loads((EVID / "P3_collect.stdout.txt").read_text(encoding="utf-8").split("COLLECT_RC")[0].strip())
SERVER_WALL = col["server_wall_s"]
S_PER_OUT = col["s_per_output_s"]
dec = json.loads((EVID / "P3_DECODE_CHECK.json").read_text(encoding="utf-8"))
main = [v for v in dec["videos"] if v["file"].endswith("00001_.mp4")][0]
cmp_ = [v for v in dec["videos"] if v["file"].endswith("00003_.mp4")][0]

sec = f"""
### P3 measured result (what the run actually produced)

* **It produced a real reskinned clip**: `p3/animate2_book_p3_00001_.mp4` — 480×848, **120 frames**,
  30/1, duration 4.000000 s, PTS 0.0…3.9667 monotonic, sha `{main['sha256']}`
  (compare: the source window is 640×360, 120 frames, 30/1, 4.000000 s). A second file,
  `…_00003_.mp4`, is the graph's own drive-vs-generated COMPOSITE (1986×848, 120 frames), and
  `…_00002_/_00004_.mp4` are single-frame stills of the same two layouts.
* **Style**: the 8-frame contact sheets show flat cel-shaded illustration in the anchor's palette —
  grey-haired seated figure holding the blue book, auburn woman in the magenta dress — with **no
  YouTube watermark**, consistent across all 8 sampled frames, no black frames, no duplicated
  bodies, no text artifacts. The worker's own reading: the reskin happened.
* **Framing (the one clear defect, and its cause)**: the generated clip is a PORTRAIT 480×848 crop
  of the scene, while the source window is landscape 640×360. The cause is inside the template, not
  the model: the reference conditioning path resizes with `ResizeImageMaskNode "scale dimensions"
  482×854 crop center` (node `672:600`) and the sampler's latent is 480×848 — the portrait box is
  inherited from the reference resize, so the composition loses the table, the back-facing figure
  and the right-edge partial person that the P2 anchor keeps.
  * hypothesis (one variable for the next round): set the reference resize to the unit's own aspect
    (e.g. 640×368) so the generated latent keeps the landscape composition; nothing else changes.
* **Cost (measured)**: server-side wall **{SERVER_WALL} s** ({round(SERVER_WALL/60, 2)} min) for
  4.0 s of video = **{S_PER_OUT} s per output second**; the same prompt ran a second, cache-warm
  pass in 52 s (6 steps at 8.69 s/it vs 296.83 s/it cold) — the cold-cache cost is dominated by
  staging the 15.9 GB int8 model (`Model Initialization` 907 s, then ~180-430 s/step while
  streaming), not by the sampler itself.
* **VRAM/RAM**: VRAM peak **{rec['vram_peak_mib']} MiB** of 12,227 MiB (sampled); RAM peak is recorded as
  `{col['ram_peak_mib']}` — **this measurement FAILED** (the tasklist column parse returned 0, and the
  number was not backed up by a second method), so RAM is reported as NOT MEASURED rather than as zero.
* **Two pollers, one artifact (self-found defect, disclosed)**: the submit script's own poll loop
  and a second collector both watched the SAME `prompt_id` (no second submission). The submit
  script's write landed last, so `P3_RECEIPT.json` carries ITS schema (`wall_s`
  {rec['wall_s']} s, completed={rec['completed']}) and the collector's extra fields (server-side
  history timestamps, the step-timing evidence) survive only in `P3_collect.stdout.txt` and in
  this report. Both agree the prompt completed; neither lost the output files.

### Not claimed

* **No quality verdict.** The worker does not accept quality; `quality_accepted=false` everywhere
  and the clips are a measured baseline, not a deliverable. The framing defect above is a measured
  observation offered to BENCH/DEMO/Codex for the failure taxonomy, not a self-assessment of the
  clip's appearance.
* **No appearance/identity acceptance** for BOOK-P2/P3 whose references are flat single-colour
  placeholders.
* P4/P5/P6/P7 (SCAIL controlled pass, continuation, cache on/off, assembly) were NOT started —
  the packet's scope for this pass was P2 + the P3 baseline.
"""
MARKER = "### P3 measured result (what the run actually produced)"
already = MARKER in rep.read_text(encoding="utf-8")
with rep.open("a", encoding="utf-8") as fh:
    if not already:
        fh.write(sec + "\n")
print("report append skipped (already present)" if already else "report appended")

led = EVID / "PROOF_LEDGER.jsonl"
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P3_RESULT_READ", "at": datetime.now(timezone.utc).isoformat(),
                         "clip": {"file": main["file"], "frames": main["ffprobe"]["nb_read_frames"],
                                  "fps": main["ffprobe"]["r_frame_rate"],
                                  "dims": [main["ffprobe"]["width"], main["ffprobe"]["height"]],
                                  "sha256": main["sha256"]},
                         "composite": {"file": cmp_["file"],
                                       "dims": [cmp_["ffprobe"]["width"],
                                                cmp_["ffprobe"]["height"]]},
                         "server_wall_s": SERVER_WALL,
                         "s_per_output_s": S_PER_OUT,
                         "warm_pass_s": 52, "cold_step_s_per_it": 296.83,
                         "framing_defect": "portrait 480x848 crop vs landscape source, caused by "
                                           "the template's reference resize 482x854 crop center",
                         "ram_peak": "NOT MEASURED (tasklist parse failed)",
                         "quality_accepted": 0}, ensure_ascii=False) + "\n")
print(json.dumps({"report_bytes": rep.stat().st_size,
                  "ledger_lines": len(led.read_text(encoding="utf-8").strip().splitlines()),
                  "main_clip": main["file"], "dims": [main["ffprobe"]["width"],
                                                      main["ffprobe"]["height"]]}, indent=1))

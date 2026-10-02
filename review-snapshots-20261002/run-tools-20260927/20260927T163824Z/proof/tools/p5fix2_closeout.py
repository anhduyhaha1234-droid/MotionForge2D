"""P5FIX2 close-out: shutdown proof, vision verdicts into the gate JSON, report/ledger/candidate
appends and the index refresh.  Run after the server stop."""
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


def sha(p, n=16):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


def load(n):
    p = EVID / n
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


s = socket.socket()
s.settimeout(3.0)
try:
    s.connect(("127.0.0.1", PORT))
    listening, err = True, None
except Exception as e:  # noqa: BLE001
    listening, err = False, repr(e)
finally:
    s.close()
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
rows = [l.strip() for l in out.splitlines() if f":{PORT}" in l and "LISTENING" in l]
proof = {"artifact": "P5FIX2_SERVER_SHUTDOWN_PROOF.json", "port": PORT,
         "pre": {"at": datetime.now(timezone.utc).isoformat(), "port_listening": listening,
                 "connect_error": err},
         "stop_scope": "process.kill on this lane's own tracked session; no /T, no /IM",
         "post": {"at": datetime.now(timezone.utc).isoformat(), "listening_rows": rows},
         "phase": "POST_STOP_VERIFIED" if not rows else "POST_STOP_UNPROVEN"}
(EVID / "P5FIX2_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(proof, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# ---- vision verdicts -----------------------------------------------------------------------
gate = load("P5FIX2_GATE.json")
sc = load("P5FIX2_CUT_SCAN.json")
gate["cut_scan"] = {k: {"cuts": v["cut_frames"], "verdict": v["verdict"],
                        "median": v["stats"]["median_mean_abs_diff"], "max": v["stats"]["max"]}
                    for k, v in sc.get("windows", {}).items()}
gate["vision"] = {
    "by": "worker, native image input on the real previews",
    "OCC_SEG1": {"verdict": "PASS", "reading":
                 "the generated mid frame shows the SEGMENT's own source subject: the certificate "
                 "'CÔNG TY TVTT & PTTM' with the red header and the four bullet lines on the blue "
                 "binder, plus the dark hand with the pen at the lower right; flat style held, no "
                 "watermark, text readable and not duplicated at this frame"},
    "OCC_SEG2": {"verdict": "FAIL", "reading":
                 "the generated side renders a DOCUMENT/letter scene (white page with grey text "
                 "lines + a hand with a pen) instead of the segment's own source content (the "
                 "person seated at the table with the blue book and the orange drink). The anchor "
                 "for seg2 was built from its first frame but with the OCC shot prompt, which "
                 "describes the certificate scene, so prompt+anchor pulled the render back to a "
                 "document"},
    "v12_cut_341_342": {"verdict": "CLEAN_CUT_BUT_CONTENT_MISMATCH",
                        "reading": "f341 is the certificate (SEG1) and f342 the generated "
                                   "document+hand frame (SEG2); the cut itself is clean (no "
                                   "blended frame) - the mismatch is SEG2's content, not the join"},
}
gate["classification"] = {
    "verdict": "INPUT-side per-SEGMENT prompt missing (not a model wall)",
    "evidence": "SEG1 renders its own source subject correctly; SEG2 renders the OCC prompt's "
                "subject instead of its own because the OCC prompt describes only the first scene",
    "hypothesis_next_round": "one variable: give OCC_SEG2 a prompt that describes its own content "
                             "(the seated person at the table with the book and the drink, flat "
                             "cel-shaded, same camera), keep anchor/driver/seed/params; re-gate",
}
(EVID / "P5FIX2_GATE.json").write_text(json.dumps(gate, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")

# ---- docs ----------------------------------------------------------------------------------
runs = load("P5FIX2_RUNS.json").get("jobs", {})
asm = load("P7_ASSEMBLY_V12.json")
achk = load("P7_ASSEMBLY_V12_CHECK.json")
rep = EVID / "PROOF_REPORT.md"
seg_lines = "\n".join(
    f"* {s_['unit']}: `{s_['file']}` sha `{s_['sha256'][:16]}..` {s_['frames']} frames "
    f"src_span {s_['source_span']} dims {s_['dims']} {s_['fps']} {s_['duration']} s | audio "
    f"`{s_['audio_file']}`" for s_ in asm.get("segments", []))
sec = f"""
## P5fix2 - split the OCC unit at the MEASURED source cut, rerun segments, assembly v1.2 (append)

**Cut scan** (`P5FIX2_CUT_SCAN.json`, rule: changed_fraction >= 0.50 AND mean_abs_diff >= 12.0):
BOOK **no cut** (median 0.0167, max 1.4981), TURN **no cut** (median 2.9711, max 5.786), OCC
**exactly one cut at the 101->102 pair** (mean_abs_diff 102.10 against a median of 0.004).  So the
split is [0,102) + [102,120) = 102 + 18 frames, not the 40/80 guess in the packet - the number
comes from the measurement.

**Split + anchors**: `inputs/p5fix2_occ_seg1.mp4` (102 frames) and `inputs/p5fix2_occ_seg2.mp4`
(18 frames) extracted frame-exactly (libx264 crf18, declared; 102+18 = 120, no gap, no overlap).
SEG1 keeps the existing anchor (`anchor_occ_p2`, whose source IS OCC frame 0); SEG2 got its own
anchor from its first frame (OCC frame 102, padded 640x368 with the same centred 4+4 rule) via the
P2 klein recipe clone `graphs/animate2_anchor_occ_seg2.p5fix2.api.json` (seed 2026092821) - anchor
sha `{sha(PROOF / 'inputs' / 'anchor_occ_seg2_p5fix2_00001_.png')}..`.  Video graphs
`animate2_occ_seg1.p5fix2.api.json` / `animate2_occ_seg2.p5fix2.api.json` (63 nodes, 0 errors each)
with seeds 2026092831 / 2026092832, prompts = the OCC I1 prompt (unchanged for both).

**Runs (warm, one job at a time)**: anchor 4.87 s; SEG1 prompt `{runs.get('OCC_SEG1', {}).get('prompt_id')}`
{runs.get('OCC_SEG1', {}).get('server_side_wall_s')} s VRAM {runs.get('OCC_SEG1', {}).get('vram_peak_mib')} MiB;
SEG2 prompt `{runs.get('OCC_SEG2', {}).get('prompt_id')}` {runs.get('OCC_SEG2', {}).get('server_side_wall_s')} s
VRAM {runs.get('OCC_SEG2', {}).get('vram_peak_mib')} MiB.

**Gate per segment** (`P5FIX2_GATE.json`): SEG1 **102 frames = span EXACT**, 640x368, 30/1,
sha `{gate.get('segments', {}).get('OCC_SEG1', {}).get('sha256', '?')}` - coverage **PASS** (the
certificate + hand + pen of its own source).  SEG2 **18 frames = span EXACT**, 640x368, sha
`{gate.get('segments', {}).get('OCC_SEG2', {}).get('sha256', '?')}` - coverage **FAIL**: it renders a
document/letter scene instead of the segment's own person-at-the-table content, because the anchor
was built with the OCC shot prompt and that prompt describes only the certificate scene.
**Classification: input-side, per-SEGMENT prompt missing** (SEG1 proves the pipeline renders its
own subject).  One-variable fix for the next round: a prompt for SEG2 describing the seated person
with the book and the drink; anchor/driver/seed/params unchanged.

## P7 v1.2 - assembly over the split timeline (append)

`graphs/p7_assembly_v12.api.json` (LoadVideo x4, LoadAudio x3 - the two OCC segments share the one
OCC window audio, whose 3.994 s span is identical because seg1+seg2 = the whole window),
prompt `{asm.get('prompt_id')}`, {asm.get('server_side_wall_s')} s:
{seg_lines}
Output `p7/assembly_v12_00001_.mp4` sha `{achk.get('assembly', {}).get('sha256', '?')}` - 360
frames / 12.000000 s / 640x368 / AAC 44.1k stereo 11.981 s; gates all true
(`P7_ASSEMBLY_V12_CHECK.json`).  Cut previews `previews/p7v12_cut_119_120.png`,
`p7v12_cut_239_240.png`, `p7v12_cut_341_342.png`; the 341->342 join (inside the OCC unit, at the
source cut) is a clean frame change.

**Supersede:** v1.2 replaces `assembly_v11_00001_.mp4` (v1.1 kept OCC as one unit and therefore
could not be gated per segment).  v1 and v1.1 stay on disk untouched as mốc.  SEG2 still fails
coverage, so v1.2 is a TECHNICAL assembly proof; the content verdict belongs to BENCH/DEMO/Codex.
`QUALITY_ACCEPTED=0`, `NOT_VISUALLY_APPROVED`.
"""
with rep.open("a", encoding="utf-8") as fh:
    fh.write(sec + "\n")
led = EVID / "PROOF_LEDGER.jsonl"
now = datetime.now(timezone.utc).isoformat()
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P5FIX2_COMPLETE", "at": now,
                         "cut_scan": {k: v["cut_frames"] for k, v in sc.get("windows", {}).items()},
                         "split": {"OCC": [[0, 102], [102, 120]], "frames": [102, 18]},
                         "segments": {k: {"sha256": v.get("sha256"), "frames": v.get("video", {}).get("nb_read_frames"),
                                          "coverage": gate["vision"][k]["verdict"]}
                                      for k, v in gate.get("segments", {}).items()},
                         "assembly_v12": {"file": "p7/assembly_v12_00001_.mp4",
                                          "sha256": achk.get("assembly", {}).get("sha256"),
                                          "frames": 360, "duration_s": 12.0, "gates": achk.get("gates")},
                         "classification": gate["classification"]["verdict"],
                         "server_shutdown": proof["phase"], "quality_accepted": 0},
                        ensure_ascii=False) + "\n")

cand = EVID / "PROOF_GATE_CANDIDATE.md"
txt = cand.read_text(encoding="utf-8")
txt += f"""

## 8. P5fix2 (append) - OCC split at the measured cut

* Cut scan: BOOK/TURN no cut; **OCC one cut at frame 102** (declared threshold, measured 102.10 vs
  median 0.004). Split = [0,102) + [102,120).
* Segments: SEG1 (102f, sha `{gate.get('segments', {}).get('OCC_SEG1', {}).get('sha256', '?')}`)
  coverage **PASS**; SEG2 (18f, sha `{gate.get('segments', {}).get('OCC_SEG2', {}).get('sha256', '?')}`,
  own anchor `{sha(PROOF / 'inputs' / 'anchor_occ_seg2_p5fix2_00001_.png')}..`) coverage **FAIL**
  (renders a document scene instead of the segment's person-at-table content) -> next round: a
  per-SEGMENT prompt for SEG2 (1 biến).
* Assembly **v1.2** `p7/assembly_v12_00001_.mp4` sha `{achk.get('assembly', {}).get('sha256', '?')}`
  (360f/12.000 s/640x368/AAC 11.981 s, all gates true) thay v1.1; v1/v1.1 giữ nguyên làm mốc.
* Server P5fix2 đã tắt: `{proof['phase']}`.
"""
cand.write_text(txt, encoding="utf-8")

self_path = EVID / "PROOF_EVIDENCE_INDEX.md"
idx = ["# PROOF_EVIDENCE_INDEX", "",
       f"Every file under `{PROOF}` (excluding this index), bytes + sha256.", "",
       "| file | bytes | sha256 |", "|---|---|---|"]
tot = n = sk = 0
for p in sorted(PROOF.rglob("*")):
    if not p.is_file() or p == self_path:
        continue
    try:
        b = p.read_bytes()
    except PermissionError:
        sk += 1
        continue
    tot += len(b)
    n += 1
    idx.append(f"| `{p.relative_to(PROOF)}` | {len(b):,} | `{hashlib.sha256(b).hexdigest()}` |")
idx += ["", f"Total {tot:,} B across {n} files (readable).", f"Locked at build time: {sk}", ""]
self_path.write_text("\n".join(idx), encoding="utf-8")
print(f"shutdown={proof['phase']} report={rep.stat().st_size} "
      f"ledger={len(led.read_text(encoding='utf-8').strip().splitlines())} "
      f"cand={cand.stat().st_size} index={n}f/{tot}")

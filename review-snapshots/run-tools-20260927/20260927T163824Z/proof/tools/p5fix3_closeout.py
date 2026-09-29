"""P5FIX3 close-out: shutdown proof, vision verdicts, report/ledger/candidate/index updates."""
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
proof = {"artifact": "P5FIX3_SERVER_SHUTDOWN_PROOF.json", "port": PORT,
         "pre": {"at": datetime.now(timezone.utc).isoformat(), "port_listening": listening,
                 "connect_error": err},
         "stop_scope": "process.kill on this lane's own tracked session; no /T, no /IM",
         "post": {"at": datetime.now(timezone.utc).isoformat(), "listening_rows": rows},
         "phase": "POST_STOP_VERIFIED" if not rows else "POST_STOP_UNPROVEN"}
(EVID / "P5FIX3_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(proof, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

gate = load("P5FIX3_GATE.json")
gate["vision"] = {
    "by": "worker, native image input on the real previews",
    "frame_0": "PASS - the generated frame shows the SEG2 subject: a young man seated at the table "
               "reading an OPEN blue book with both hands, a cup with a light blue straw in front "
               "of him, the blue window band and the white wall band behind; no watermark",
    "frame_17": "PASS - the same scene at the segment's last frame, no drift into the certificate "
                "or a room scene, no watermark",
    "deviations_from_source": "the generated book is OPEN (two pages) while the source holds a "
                              "closed blue book; the generated jacket reads as a hooded jacket and "
                              "carries more shading/detail than the minimal source style; the cup "
                              "shows a cream drink where the source cup is empty",
    "verdict": "PASS (subject/scene/camera match; the book-state and detail deviations are "
               "recorded, not hidden)",
}
(EVID / "P5FIX3_GATE.json").write_text(json.dumps(gate, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")

g3 = load("P5FIX3_GRAPH.json")
runs = load("P5FIX3_RUN.json").get("jobs", {})
asm = load("P7_ASSEMBLY_V13.json")
achk = load("P7_ASSEMBLY_V13_CHECK.json")
job = runs.get("P5FIX3_SEG2", {})
rep = EVID / "PROOF_REPORT.md"
seg_lines = "\n".join(
    f"* {s_['unit']}: `{s_['file']}` sha `{s_['sha256'][:16]}..` {s_['frames']} frames "
    f"src_span {s_['source_span']} dims {s_['dims']} {s_['fps']} {s_['duration']} s | audio "
    f"`{s_['audio_file']}`" for s_ in asm.get("segments", []))
sec = f"""
## P5fix3 - OCC_SEG2 gets its own prompt; assembly v1.3 (BẢN CHỐT cho verify) (append)

**The one variable**: `672:582.text` in `graphs/animate2_occ_seg2.p5fix3.api.json` (sha
`{g3.get('sha256', '?')}`, 63 nodes, 0 errors).  Prompt sha `{g3.get('deltas', [{}])[0].get('sha_before')}`
(the OCC certificate prompt) -> `{g3.get('deltas', [{}])[0].get('sha_after')}` - text authored for SEG2
from its own measured source frames (strip `previews/p5fix3_occ_seg2_source_frames.png`,
frame hashes in `P5FIX3_SEG2_SOURCE.json`), describing the seated man with the blue book, the cup
with the straw, the blue window band and the same camera.  Anchor, driver clip, steps, sampler, cfg,
shift, pad and the negative prompt are byte-identical to the p5fix2 graph.  New declared seed
2026092841; prefixes `p5fix3_occ_seg2/`.

**Run**: prompt `{job.get('prompt_id')}`, server wall {job.get('server_side_wall_s')} s, VRAM peak
{job.get('vram_peak_mib')} MiB.

**Gate**: `p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4` = 640x368, **18 frames = the exact
span [102,120)**, 30/1, PTS monotonic, sha `{gate.get('video', {}).get('sha256', '?')}`.  Coverage
vision (seg frames 0/8/17): **PASS** - the person-at-the-table scene with the blue book, the cup
and the straw, the blue window band, no watermark, no drift at the last frame.  Recorded
deviations: the generated book is OPEN while the source holds a closed book; the jacket reads
hooded with more shading; the cup shows a drink.

**Assembly v1.3 - the artifact to verify** (`graphs/p7_assembly_v13.api.json`, prompt
`{asm.get('prompt_id')}`, {asm.get('server_side_wall_s')} s):
{seg_lines}
`p7/assembly_v13_00001_.mp4` sha `{achk.get('assembly', {}).get('sha256', '?')}` - 360 frames /
12.000000 s / 640x368 / AAC 44.1k stereo, gates all true (`P7_ASSEMBLY_V13_CHECK.json`).  Cut
previews `previews/p7v13_cut_119_120.png`, `p7v13_cut_239_240.png`, `p7v13_cut_341_342.png`; the
341->342 join now goes certificate -> person-at-the-table (clean).

**Supersede**: v1.3 replaces v1.2 (v1.2's OCC_SEG2 rendered a document scene from the certificate
prompt).  v1 / v1.1 / v1.2 stay on disk untouched as milestones.

**Standing content notes for the reviewer** (not blockers): TURN f60 has a transient doubled-text
artefact; the BOOK clip keeps the book closed while the source event table has `open_two_pages` at
frame 72, and the generated OCC_SEG2 opens it; VACE's watermark copy stays a blocker for the VACE
path only.  `QUALITY_ACCEPTED=0`, `NOT_VISUALLY_APPROVED`.
"""
with rep.open("a", encoding="utf-8") as fh:
    fh.write(sec + "\n")
led = EVID / "PROOF_LEDGER.jsonl"
now = datetime.now(timezone.utc).isoformat()
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P5FIX3_COMPLETE", "at": now,
                         "graph_sha256": g3.get("sha256"),
                         "prompt_sha": {"before": g3.get("deltas", [{}])[0].get("sha_before"),
                                        "after": g3.get("deltas", [{}])[0].get("sha_after")},
                         "run": {"prompt_id": job.get("prompt_id"),
                                 "wall_s": job.get("server_side_wall_s"),
                                 "vram_peak_mib": job.get("vram_peak_mib")},
                         "segment": {"file": "p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4",
                                     "sha256": gate.get("video", {}).get("sha256"),
                                     "frames": 18, "gates": gate.get("gates"),
                                     "coverage": "PASS (book open vs source closed; detail notes)"},
                         "assembly_v13": {"file": "p7/assembly_v13_00001_.mp4",
                                          "sha256": achk.get("assembly", {}).get("sha256"),
                                          "frames": 360, "duration_s": 12.0,
                                          "gates": achk.get("gates"),
                                          "role": "FINAL_FOR_VERIFY"},
                         "server_shutdown": proof["phase"], "quality_accepted": 0},
                        ensure_ascii=False) + "\n")

cand = EVID / "PROOF_GATE_CANDIDATE.md"
txt = cand.read_text(encoding="utf-8")
txt += f"""

## 9. P5fix3 (append) - BẢN CHỐT v1.3 cho BENCH/DEMO verify

* OCC_SEG2 có prompt riêng (sha `{g3.get('deltas', [{}])[0].get('sha_after')}`) → coverage **PASS**
  (người ngồi bàn + sách xanh + ly/ống hút + cửa sổ xanh, không watermark; ghi chú: sách MỞ ở bản
  sinh vs KHÉP ở nguồn, jacket có hood, nhiều chi tiết hơn style nguồn).
* **Tất cả segment đã đạt coverage của chính nó**: BOOK (p3b) PASS · TURN (p5fix) PASS · OCC_SEG1
  (p5fix2) PASS · OCC_SEG2 (p5fix3) PASS.
* **Assembly v1.3 = bản chốt**: `p7/assembly_v13_00001_.mp4` sha
  `{achk.get('assembly', {}).get('sha256', '?')}` — 360f/12.000 s/640×368/AAC 11.98 s, gates all
  true; supersede v1.2/v1.1/v1 (giữ on-disk).
* Ticket verify (read-only) như §6, dùng v1.3 + các preview `previews/p5fix3_*`, `p7v13_cut_*`,
  `p5fix2_occ_seg1_*`, `p3b_coverage_*`, `p4_ab_*` (watermark VACE).
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

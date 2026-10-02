"""P5/P6/P7 documentation close-out: append report sections + ledger lines, write
PROOF_GATE_CANDIDATE.md (with injected measured shas) and refresh the evidence index.

No GPU, no new runs, no edits to existing lines - appends only.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"


def sha(p: pathlib.Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


def load(name):
    p = EVID / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


turn = load("P5_TURN_OCC_GATE.json").get("shots", {})
ov = load("P5_OVERLAP_GATE.json")
nc = load("P6_NOCACHE_GATE.json")
px = load("P5P6_PIXEL_DIFF.json")
asm = load("P7_ASSEMBLY_CHECK.json")
p5g = load("P5_P6_GRAPHS.json").get("graphs", {})
turn_rec = load("P5_TURN_RECEIPT.json")
occ_rec = load("P5_OCC_RECEIPT.json")

ASM_SHA = asm.get("assembly", {}).get("sha256", "?")
ASM_BYTES = asm.get("assembly", {}).get("bytes", 0)
T = turn.get("TURN", {})
O = turn.get("OCC", {})

rep = EVID / "PROOF_REPORT.md"
sec = f"""
## P5 - TURN/OCC clips + the continuation hypothesis (append, docs only)

**Graphs** (clone of `animate2_book.p3b.api.json`, declared deltas only): TURN sha
`{p5g.get('P5_OVERLAP16', {}).get('sha256', 'see P5_TURN_OCC_GRAPHS.json')}` no - TURN/OCC shas are
`{sha(PROOF / 'graphs' / 'animate2_turn.p5.api.json')}` / `{sha(PROOF / 'graphs' / 'animate2_occ.p5.api.json')}`
(`P5_TURN_OCC_GRAPHS.json`); deltas = LoadImage -> that unit's P2 anchor, LoadVideo -> that unit's
pinned window, SaveVideo prefixes `p5_turn/` `p5_occ/`, NEW declared fixed seeds 2026092801 /
2026092802.

**Technical gates - PASS.** TURN `{T.get('file')}` 640x368, 120 frames, 30/1, 4.000000 s, PTS
monotonic, motion median {T.get('motion', {}).get('median')} (real motion), 0 zero-diff pairs; OCC
`{O.get('file')}` 640x368, 120 frames, 30/1, 4.000000 s, PTS monotonic, motion median
{O.get('motion', {}).get('median')}, 0 zero-diff pairs. Warm walls {turn_rec.get('server_side_wall_s')} s
/ {occ_rec.get('server_side_wall_s')} s, VRAM peaks {turn_rec.get('vram_peak_mib')} / {occ_rec.get('vram_peak_mib')} MiB.

**Coverage gate - FAIL for BOTH units (content, not geometry).** The generated clips show a
seated-reader/book interior scene - BOOK-like content - while the source windows and the P2 anchors
are the document scenes (TURN: the "CTY TNHH Bao Nam Training" form on a blue binder; OCC: the
"CTY TVTT & PTTM" page with the writing hand+pen). Both anchors were re-inspected this pass and are
correct and watermark-free.

**Cause, measured (not guessed):** the CLIPTextEncode `672:582` text in ALL THREE graphs (book p3b,
turn p5, occ p5) has the SAME sha `540d16b7b7300c40` (493 chars, starting "Character Description: a
2D cel-shaded illustration of a seated older ..."), i.e. the BOOK prompt was carried into the
TURN/OCC graphs; the per-shot instructions that produced the correct anchors live in the I1 graphs
and differ per unit (turn `eca92d5e...` 1518 chars, occ `b2a1e176...` 1692, book `8e48cfbe...` 3146,
all starting "Reference image 1 is the exact frame to redraw").  The declared "deltas only" list for
those graphs did NOT include the prompt, which is the defect.

**Fix for the next round (ONE variable, not run - this pass is docs-only):** give the TURN/OCC
graphs their own prompt text (adapt the I1 turn/occ instructions to the Animate2 graph's prompt
convention), keep everything else; then re-check coverage on frames 0/60/119.

**Continuation hypothesis (overlap 8 -> 16).** Graph
`graphs/animate2_book.p5overlap16.api.json` ({p5g.get('P5_OVERLAP16', {}).get('sha256', '?')[:16]}),
prompt 810f2e6a, wall {ov.get('clip', {}).get('ffprobe', {}).get('nb_read_frames')} frames, warm
155.0 s, VRAM 11,224 MiB.  Result: the seam window 68..96 profile is NUMERICALLY IDENTICAL to p3b
(join 80->81 = {ov.get('comparison', {}).get('join_pair_80_81', {}).get('overlap16')} =
{ov.get('comparison', {}).get('join_pair_80_81', {}).get('p3b')}; clip max
{ov.get('comparison', {}).get('clip_max', {}).get('overlap16')}), and the decoded pixels are
byte-identical to the p3b clip (`P5P6_PIXEL_DIFF.json`: max_abs
{px.get('comparisons', {}).get('ov16', {}).get('max_abs')}, mean_abs
{px.get('comparisons', {}).get('ov16', {}).get('mean_abs')}, 0/120 frames differ).
Mechanism (measured): node `672:586 ContextWindowsManual` feeds ONLY `672:588 ComfySwitchNode.on_true`
and that switch is `False`, so the context-window branch is disabled in this graph - the overlap
value cannot reach the output. **Disposition: keep overlap 8; the hypothesis is inert.** The 80->81
elevation is therefore not governed by context overlap; the next candidate lever is the loop chunk
machinery (`672:635 PrimitiveInt 81` + `672:639`), named for a future single-variable test.
The BOOK seam flag stays exactly as recorded in P3b (numeric SEAM_ANOMALY_FLAGGED, visually
NO_VISIBLE_SEAM_DEFECT).

## P6 - cache on/off (append, docs only)

Graph `graphs/animate2_book.p6nocache.api.json` ({p5g.get('P6_NOCACHE', {}).get('sha256', '?')[:16]}):
the cache node `672:594 WanAnimate2Cache` was REMOVED (it has no toggle input; device/dtype are its
only settings) and its two consumers (672:591 BasicScheduler.model, 672:592 ModelSamplingSD3.model)
were wired straight to 672:588.  Seed/params identical to P3b (582699151003550).

| run | warm wall | VRAM peak | bytes | sha256 | vs p3b pixels |
|---|---|---|---|---|---|
| cache ON (P3b) | 154.67 s | 10,973 MiB | 208,053 | `dfc4e37b81ba4252...` | reference |
| cache OFF (P6) | **135.21 s** | **10,763 MiB** | 207,931 | `be83cf705a7a8769...` | max_abs 0, 0/120 frames differ |

The two clips differ only at the bitstream level (different sha/size); the DECODED PIXELS are
identical (`P5P6_PIXEL_DIFF.json` nocache max_abs {px.get('comparisons', {}).get('nocache', {}).get('max_abs')}).
**Conclusion: the WanAnimate2Cache node is a net cost in this profile (12.6% slower, +210 MiB VRAM,
no pixel effect) - recommend dropping it from the graph.**

## P7 - assembly, graph-native (append, docs only)

`graphs/p7_assembly.api.json`: LoadVideo x3 (staged copies of the three accepted clips, byte-identical,
`inputs/p7_book.mp4` / `p7_turn.mp4` / `p7_occ.mp4`) + LoadAudio x3 on the SOURCE windows ->
AudioConcat chain -> `ConcatenateVideo` (autogrow `videos.video0..2`, codec auto, `complete_audio`) ->
SaveVideo `p7/assembly_v1`.  Order BOOK -> TURN -> OCC.  Run prompt 9b8a7d29, **2.8 s**.

`output/p7/assembly_v1_00001_.mp4` sha `{ASM_SHA}` ({ASM_BYTES:,} B): 640x368, **360 frames**
(120x3), 30/1, **12.000000 s**, audio **AAC 44100 Hz stereo 11.981 s**, h264; all six gates true
(frames match the parts, duration 12 s, dims, audio present, audio duration, reopenable) -
`P7_ASSEMBLY_CHECK.json`.  Audio policy: no ffmpeg remux was needed - the source audio is joined
inside the graph (`LoadAudio` on the three source mp4s + `AudioConcat`), so the container carries
h264 video + AAC audio end to end; the boundary preview `previews/p7_boundary_frames.png` shows the
cut frames 119/120 and 239/240.

**Content caveat (important):** because the TURN and OCC segments currently fail their coverage
gate (see P5), this 12 s file is a TECHNICAL proof of the assembly + audio path, NOT a
content-accepted deliverable.

## Interfaces for app wiring (append)

* per-unit video graph inputs: `LoadImage.image` = the unit's anchor PNG; `LoadVideo.file` = the
  unit's source window (640x360, 120 frames, 30/1, +AAC); geometry constant `P3B_PAD target 640x368`
  (center pad, no crop); `SamplerCustom.noise_seed` = the declared seed; `SaveVideo.filename_prefix`
  = the run's folder.
* per-unit video graph outputs (4 files): main clip 640x368/120f/30fps; a single-frame still; a
  drive|generated composite 1294x368/120f; a composite still.
* fixed params: unet `wan_animate_2_int8_convrot`, LoRA `lightx2v_I2V_14B_480p_..._rank64_bf16`,
  clip `umt5_xxl_fp8_e4m3fn_scaled`, clip_vision `clip_vision_h`, vae `Wan2_1_VAE_bf16`; 6 steps,
  sampler lcm, cfg 1, shift 5; context 21/8 (inert); cache node recommended OFF.
* assembly graph inputs: the 3 clip files + the 3 source windows (as audio); output: one mp4.
* receipt fields the app can rely on: `prompt_id`, `graph_sha256`, `server_side_wall_s`,
  `vram_peak_mib`, `seed`, `output_files[{{file,bytes,sha256,ffprobe}}]`.

## Open items (append)

1. **TURN/OCC coverage FAIL** - cause proven (BOOK prompt carried over, sha `540d16b7...`); fix =
   per-unit prompt text, one variable, next round.
2. **Book-state event**: the Animate2 BOOK clip keeps the book CLOSED across the window while the
   source event table declares `open_two_pages @ frame 72`; the VACE challenger opened it.  Needs a
   product decision (is the open event required inside this clip?).
3. **VACE watermark copy** remains a blocker for that path (frames 0 and 119).
4. **Artwork for boy_hacker / gau_nau is still placeholder** - no appearance claim anywhere.
5. **RAM peak not measured** (three samplers returned non-credible values; reported as unmeasured).
6. P3b graph keeps the inherited `p3/` SaveVideo prefix (footgun note in
   `P3B_ARTIFACT_RECONCILIATION.json`); the P5/P6/P7 graphs use their own prefixes.
"""
with rep.open("a", encoding="utf-8") as fh:
    fh.write(sec + "\n")

led = EVID / "PROOF_LEDGER.jsonl"
now = datetime.now(timezone.utc).isoformat()
rows = [
    {"phase": "P5_COMPLETE", "at": now,
     "turn": {"graph_sha256": sha(PROOF / "graphs" / "animate2_turn.p5.api.json"),
              "prompt_id": turn_rec.get("prompt_id"), "wall_s": turn_rec.get("server_side_wall_s"),
              "vram_peak_mib": turn_rec.get("vram_peak_mib"),
              "file": T.get("file"), "sha256": T.get("sha256"), "frames": 120, "dims": [640, 368]},
     "occ": {"graph_sha256": sha(PROOF / "graphs" / "animate2_occ.p5.api.json"),
             "prompt_id": occ_rec.get("prompt_id"), "wall_s": occ_rec.get("server_side_wall_s"),
             "vram_peak_mib": occ_rec.get("vram_peak_mib"),
             "file": O.get("file"), "sha256": O.get("sha256"), "frames": 120, "dims": [640, 368]},
     "coverage": "FAIL_BOTH (BOOK prompt carried over: 672:582 sha 540d16b7b7300c40 in all three "
                 "graphs; per-unit I1 prompts eca92d5e/b2a1e176/8e48cfbe)",
     "overlap_hypothesis": "INERT - pixel-identical to p3b (max_abs 0); mechanism: 672:586 feeds "
                           "672:588.on_true and that switch is False; keep overlap 8",
     "quality_accepted": 0},
    {"phase": "P6_COMPLETE", "at": now,
     "graph_sha256": p5g.get("P6_NOCACHE", {}).get("sha256"),
     "method": "cache node 672:594 removed, consumers rewired to 672:588",
     "cache_on": {"wall_s": 154.67, "vram_peak_mib": 10973, "sha256": "dfc4e37b81ba4252..."},
     "cache_off": {"wall_s": 135.21, "vram_peak_mib": 10763, "sha256": "be83cf705a7a8769..."},
     "pixel_identical": True, "recommendation": "drop the cache node", "quality_accepted": 0},
    {"phase": "P7_COMPLETE", "at": now,
     "assembly": {"file": "p7/assembly_v1_00001_.mp4", "sha256": ASM_SHA, "bytes": ASM_BYTES,
                  "frames": 360, "dims": [640, 368], "duration_s": 12.0,
                  "audio": "aac 44100 stereo 11.981 s", "gates": asm.get("gates")},
     "method": "graph-native: LoadVideo x3 + LoadAudio x3 + AudioConcat -> ConcatenateVideo"
               "(complete_audio) -> SaveVideo; order BOOK/TURN/OCC",
     "caveat": "TURN/OCC segments fail the coverage gate -> technical assembly proof only",
     "quality_accepted": 0},
]
with led.open("a", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---- PROOF_GATE_CANDIDATE.md -------------------------------------------------------------
g = lambda rel: sha(PROOF / rel) if (PROOF / rel).is_file() else "?"
doc = f"""# PROOF_GATE_CANDIDATE — MF-V1-VIDEO14B Phase A (P0–P7)

Task: MF-V1-VIDEO14B · session `20260927_165838_1cbd42` · {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z UTC
Proof root: `{str(PROOF).replace(chr(92), '/')}`
Trạng thái: **CANDIDATE** — worker không tự chấp nhận; `QUALITY_ACCEPTED=0`, không APPROVED/CLOSED.

## 1. Checklist P0–P7

| # | Mục | Trạng thái | Bằng chứng (file · sha256 16) |
|---|---|---|---|
| P0 | Runtime/weights matrix + node interfaces (server cô lập) | PASS | `P0_RUNTIME_MATRIX.json` · `{g('evidence/P0_RUNTIME_MATRIX.json')}` |
| P1 | Unit manifests BOOK/TURN/OCC (source window hash-verified) | PASS | `P1_UNIT_MANIFESTS.json` · `{g('evidence/P1_UNIT_MANIFESTS.json')}` |
| P2 | Target anchors 3 unit (gate coverage PASS) | PASS | `P2_ANCHOR_GATES.json` · `{g('evidence/P2_ANCHOR_GATES.json')}` |
| P3 | Baseline BOOK (Animate2) — lần đầu FAIL geometry | FIXED ở P3b | `P3_RECEIPT.json` · `{g('evidence/P3_RECEIPT.json')}` |
| P3b | Sửa geometry 640×368 + rerun BOOK (gate PASS) | PASS | `P3B_GEOMETRY_GATE.json` · `{g('evidence/P3B_GEOMETRY_GATE.json')}` |
| P4 | Challenger VACE 14B (cùng unit/seed) | PASS kỹ thuật, có defect chặn | `P4_GEOMETRY_GATE.json` · `{g('evidence/P4_GEOMETRY_GATE.json')}` |
| P5 | TURN/OCC clips (Wan) + giả thuyết overlap | Kỹ thuật PASS · **coverage FAIL** | `P5_TURN_OCC_GATE.json` · `{g('evidence/P5_TURN_OCC_GATE.json')}` |
| P5 | Overlap 8→16 | INERT (pixel-identical) | `P5_OVERLAP_GATE.json` · `{g('evidence/P5_OVERLAP_GATE.json')}` |
| P6 | Cache ON/OFF | PASS — nên bỏ cache | `P6_NOCACHE_GATE.json` · `{g('evidence/P6_NOCACHE_GATE.json')}` |
| P7 | Assembly graph-native + audio nguồn | PASS kỹ thuật (nội dung chờ P5) | `P7_ASSEMBLY_CHECK.json` · `{g('evidence/P7_ASSEMBLY_CHECK.json')}` |

## 2. Profile đo được (cùng unit BOOK, cùng seed 582699151003550)

| Profile | s/giây video | VRAM peak | Watermark | Ghi chú |
|---|---|---|---|---|
| **Wan Animate 2 INT8 640×368** (primary) | **38.67** (warm) · 596.95 (cold) | 10,973 · 11,224 MiB | không | cache nên OFF (−19.5 s, −210 MiB, pixel y hệt) |
| VACE 14B fp16 (challenger) | 291.13 | 11,680 MiB | **COPY (chặn)** | latent nguyên khối, không seam |

## 3. Assembly

`p7/assembly_v1_00001_.mp4` sha `{ASM_SHA}` · **360 frame / 12.000 s / 640×368 / AAC 44.1k stereo
11.981 s** · 6/6 gate kỹ thuật true · ghép hoàn toàn trong graph (LoadVideo×3 + LoadAudio×3 +
AudioConcat → ConcatenateVideo.complete_audio), không remux ffmpeg.

## 4. Giới hạn đã biết (không được bỏ qua khi duyệt)

1. **TURN/OCC coverage FAIL**: nội dung sinh ra là cảnh người-đọc-sách (prompt BOOK bị mang sang;
   sha prompt `540d16b7b7300c40` giống nhau ở cả 3 graph, prompt per-unit của I1 là
   `eca92d5e…`/`b2a1e176…`). Sửa = prompt theo unit, 1 biến, vòng sau.
2. **Book-state**: Wan giữ sách KHÉP suốt window, trong khi event nguồn có `open_two_pages @72`
   (VACE mở). Cần quyết định sản phẩm.
3. **VACE watermark copy** = chặn nhánh đó cho tới khi có cách xoá.
4. **Artwork boy_hacker/gau_nau vẫn placeholder** — không claim diện mạo.
5. **RAM peak chưa đo được** (3 sampler trả giá trị vô lý → ghi NOT MEASURED).
6. Seam BOOK: cờ số `SEAM_ANOMALY_FLAGGED` giữ nguyên, đọc mắt = NO_VISIBLE_SEAM_DEFECT.

## 5. Interface nối app

* Input mỗi unit: anchor PNG + source window 640×360/120f/30fps(+AAC); hằng số hình học
  `ResizeAndPadImage 640×368` (pad giữa, không crop); seed khai báo; prefix SaveVideo theo run.
* Output mỗi unit (4 file): clip chính 640×368/120f; 1 still; composite 1294×368/120f; 1 still.
* Params cố định: unet `wan_animate_2_int8_convrot` + LoRA `lightx2v…rank64_bf16` +
  `umt5_xxl_fp8_e4m3fn_scaled` + `clip_vision_h` + `Wan2_1_VAE_bf16`; 6 step · lcm · cfg 1 · shift 5;
  context 21/8 (inert); cache **OFF**.
* Receipt dùng được: `prompt_id`, `graph_sha256`, `server_side_wall_s`, `vram_peak_mib`, `seed`,
  `output_files[{{file,bytes,sha256,ffprobe}}]`; assembly nhận 3 clip + 3 audio nguồn.

## 6. Ticket cho BENCH / DEMO verify (read-only, không chạy GPU)

1. Đối chiếu `PROOF_EVIDENCE_INDEX.md` (đếm file + sha) với đĩa.
2. Mở `previews/p3b_coverage_frame*.png` (BOOK PASS), `p5_turn_*`/`p5_occ_*` (xác nhận FAIL nội dung
   như mục 4.1), `p4_ab_*` (watermark), `p5_overlap16_seam_strip.png`, `p6_ab_*`, `p7_boundary_frames.png`.
3. Chạy lại độc lập bất kỳ script trong `tools/` (read-only, không tốn GPU cho các gate decode).
4. Xác nhận các sha trong `PROOF_LEDGER.jsonl` (9+ dòng) khớp file trên đĩa.
"""
(EVID / "PROOF_GATE_CANDIDATE.md").write_text(doc, encoding="utf-8")

# ---- index refresh ------------------------------------------------------------------------
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
print(f"OK report={rep.stat().st_size}B ledger={len(led.read_text(encoding='utf-8').strip().splitlines())} "
      f"cand={(EVID / 'PROOF_GATE_CANDIDATE.md').stat().st_size}B index={n}f/{tot}B")[:190]

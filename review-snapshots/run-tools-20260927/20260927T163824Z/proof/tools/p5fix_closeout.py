"""P5fix shutdown proof + the append-only documentation pass (report/ledger/candidate/index)."""
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


# ---- shutdown proof ----------------------------------------------------------------------
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
tl = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
proof = {"artifact": "P5FIX_SERVER_SHUTDOWN_PROOF.json", "port": PORT,
         "pre": {"at": datetime.now(timezone.utc).isoformat(), "port_listening": listening,
                 "connect_error": err},
         "stop_scope": "process.kill on this lane's own tracked session (bash 31128 + its ComfyUI "
                       "child); no /T, no /IM, no image-wide stop",
         "post": {"at": datetime.now(timezone.utc).isoformat(),
                  "listening_rows": rows,
                  "any_python_on_port": bool(rows),
                  "tasklist_sample": tl.strip().splitlines()[:2]},
         "phase": "POST_STOP_VERIFIED" if not rows else "POST_STOP_UNPROVEN"}
(EVID / "P5FIX_SERVER_SHUTDOWN_PROOF.json").write_text(
    json.dumps(proof, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# ---- docs ---------------------------------------------------------------------------------
g = load("P5FIX_GRAPHS.json").get("shots", {})
gate = load("P5FIX_GATE.json").get("shots", {})
runs = load("P5FIX_RUNS.json").get("jobs", {})
asm = load("P7_ASSEMBLY_V11.json")
achk = load("P7_ASSEMBLY_V11_CHECK.json")
rep = EVID / "PROOF_REPORT.md"
sec = f"""
## P5fix - per-unit prompts, rerun TURN/OCC, assembly v1.1 (append)

**Fix (one variable + the pinned profile decision).** Graphs `graphs/animate2_turn.p5fix.api.json`
sha `{g.get('TURN', {}).get('sha256', '?')}` and `graphs/animate2_occ.p5fix.api.json` sha
`{g.get('OCC', {}).get('sha256', '?')}`, 63 nodes each, 0 validation errors.  Deltas per shot
(`P5FIX_GRAPHS.json`): `672:582.text` -> the unit's I1 prompt verbatim (TURN `540d16b7..` ->
`eca92d5e..` 1518 chars; OCC `540d16b7..` -> `b2a1e176..` 1692 chars), the cache node `672:594`
REMOVED with its two consumers rewired to `672:588` (the manager's cache-OFF decision, proven
pixel-neutral in P6), SaveVideo prefixes `p5fix_turn/`/`p5fix_occ/`, new declared seeds 2026092811
/ 2026092812.  Negative prompt, models, LoRA, steps, sampler, shift, context and the pad unchanged.

**Runs** (warm server, one job at a time): TURN prompt `4d4eda1b` 134.94 s VRAM 10,855 MiB; OCC
prompt `22732df5` 130.34 s VRAM 11,356 MiB.  Technical gates PASS for both: 640x368, 120 frames,
30/1, 4.000000 s, PTS monotonic, 0 zero-diff pairs; new shas `{gate.get('TURN', {}).get('sha256', '?')}`
(TURN) / `{gate.get('OCC', {}).get('sha256', '?')}` (OCC).

**Coverage gate (vision, frames 0/30/60/90/119 per shot - denser than before).**
* TURN: **PASS on subject** - the certificate ("CTY TNHH Bao Nam Training" page on the blue binder)
  is the content at every checked frame, no drift into a person, no watermark.  Transient defect
  recorded: at frame 60 the page text renders DOUBLED (title and field labels drawn twice,
  overlapping); by frame 119 it is single again.
* OCC: **FAIL (late-clip drift)** - frames 0/30/60 show the correct page + writing hand + pen, but
  by frame 119 the clip has drifted into a PERSON sitting at a table with a book (BOOK-like
  content), i.e. the drift the old clips showed now happens late instead of mid-clip.
* The old-clip strip (`previews/p5fix_old_turn_clip_strip_f0_30_60_90_119.png`) pins the manager's
  inconsistency: the OLD turn clip is certificate at f0, certificate + pointing hand at f30, then a
  reader at f60/f90/f119 - so assembly frame ~150 (certificate + hand) and the f60 preview (reader)
  BOTH come from that one clip; not two different files.

**Classification + one hypothesis (input/control side, not a model wall).** The early frames prove
the pipeline renders the right per-unit content, so the residual defect is late-clip CONTROL loss,
not missing capability.  Hypothesis for the next single-variable round: the drift starts after the
first 81-frame loop chunk (`672:635 PrimitiveInt 81` + the `672:639` chunk math), i.e. the second
chunk continues from the first chunk's output without re-anchoring to the reference - test a
shorter/re-anchored chunking (e.g. chunk 41, or a single 121-frame pass) so pose/reference
conditioning stays active for the whole clip.

## P7 v1.1 - assembly rebuilt with the fixed segments (append)

`graphs/p7_assembly_v11.api.json`, prompt `{asm.get('prompt_id', '?')}`, {asm.get('server_side_wall_s', '?')} s:
LoadVideo x3 on the pinned clips + LoadAudio x3 on the pinned source windows -> AudioConcat ->
ConcatenateVideo(`complete_audio`) -> SaveVideo.  **Per-segment pins** in `P7_ASSEMBLY_V11.json`:
"""
for s_ in asm.get("segments", []):
    sec += (f"* {s_['unit']}: `{s_['file']}` sha `{s_['sha256'][:16]}..` {s_['frames']} frames "
            f"{s_['dims']} {s_['fps']} {s_['duration']} s | audio `{s_['audio_file']}` sha "
            f"`{s_['audio_sha256'][:16]}..`\n")
sec += f"""
Output `p7/assembly_v11_00001_.mp4` sha `{achk.get('assembly', {}).get('sha256', '?')}` -
360 frames / 12.000000 s / 640x368 / audio AAC 44.1k stereo 11.981 s; gates all true
(`P7_ASSEMBLY_V11_CHECK.json`, dims gate re-run with an int comparison after the first pass
compared ints against strings and reported a false negative).  Boundary previews
`previews/p7v11_boundary_book_turn.png` / `p7v11_boundary_turn_occ.png`: the 119->120 cut goes
BOOK interior -> TURN certificate cleanly (no blended/duplicated frame).

**Supersede note:** v1.1 replaces `output/p7/assembly_v1_00001_.mp4` (v1, built from the p5 clips
whose content failed coverage).  The v1 file and its receipt stay on disk untouched - the
`P7_ASSEMBLY_V11.json.supersedes` field records the reason.  Because OCC still fails its coverage
gate, v1.1 remains a TECHNICAL assembly; the content verdict belongs to BENCH/DEMO/Codex.
`QUALITY_ACCEPTED=0`, `NOT_VISUALLY_APPROVED`.
"""
with rep.open("a", encoding="utf-8") as fh:
    fh.write(sec + "\n")

led = EVID / "PROOF_LEDGER.jsonl"
now = datetime.now(timezone.utc).isoformat()
with led.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"phase": "P5FIX_COMPLETE", "at": now,
                         "graphs": {k: v.get("sha256") for k, v in g.items()},
                         "prompts": {"turn": "eca92d5e (I1, 1518 c)",
                                     "occ": "b2a1e176 (I1, 1692 c)",
                                     "was": "540d16b7 (BOOK) in all three graphs"},
                         "runs": {k: {"prompt_id": v.get("prompt_id"),
                                      "wall_s": v.get("server_side_wall_s"),
                                      "vram_peak_mib": v.get("vram_peak_mib")}
                                  for k, v in runs.items()},
                         "coverage": {"TURN": "PASS (transient doubled text at f60)",
                                      "OCC": "FAIL late-clip drift (person+book at f119)"},
                         "classification": "input/control-side late-clip loss; hypothesis = "
                                           "loop chunk continuation without re-anchoring "
                                           "(672:635 / 672:639)",
                         "quality_accepted": 0}, ensure_ascii=False) + "\n")
    fh.write(json.dumps({"phase": "P7V11_COMPLETE", "at": now,
                         "assembly": {"file": "p7/assembly_v11_00001_.mp4",
                                      "sha256": achk.get("assembly", {}).get("sha256"),
                                      "frames": 360, "duration_s": 12.0, "dims": [640, 368],
                                      "audio": "aac 44100 stereo 11.981 s"},
                         "segments": [{"unit": s_["unit"], "sha256": s_["sha256"][:16],
                                       "frames": s_["frames"]} for s_ in asm.get("segments", [])],
                         "supersedes": "output/p7/assembly_v1_00001_.mp4 (p5 clips, coverage FAIL)",
                         "caveat": "OCC segment still fails coverage -> technical proof only",
                         "quality_accepted": 0}, ensure_ascii=False) + "\n")

# candidate doc: fix the P5 row + assembly path/sha (in-place edit, disclosed)
cand = EVID / "PROOF_GATE_CANDIDATE.md"
txt = cand.read_text(encoding="utf-8")
txt = txt.replace(
    "| P5 | TURN/OCC clips (Wan) + giả thuyết overlap | Kỹ thuật PASS · **coverage FAIL** |",
    "| P5 | TURN/OCC clips (Wan) | xem P5fix (thay thế) |").replace(
    "| P7 | Assembly graph-native + audio nguồn | PASS kỹ thuật (nội dung chờ P5) | `P7_ASSEMBLY_CHECK.json`",
    "| P7 | Assembly v1.1 graph-native + audio nguồn | PASS kỹ thuật (OCC chờ P5fix2) | `P7_ASSEMBLY_V11_CHECK.json`")
txt += f"""

## 7. Supersede (P5fix pass, append)

* P5 TURN/OCC clips cũ (`p5_turn/`, `p5_occ/`) **bị thay** bởi `p5fix_turn/`, `p5fix_occ/`
  (prompt per-unit): TURN coverage **PASS** (lỗi chữ nhân đôi thoáng qua ở f60);
  OCC vẫn **FAIL** (drift cuối clip thành cảnh người+sách ở f119) → cần vòng P5fix2
  (giả thuyết: chunk continuation 672:635/672:639 không re-anchor).
* Assembly **v1.1** `p7/assembly_v11_00001_.mp4` sha `{achk.get('assembly', {}).get('sha256', '?')}`
  thay `assembly_v1_00001_.mp4` (v1 giữ nguyên trên đĩa làm mốc supersede).
* Bằng chứng mới: `P5FIX_GRAPHS.json`, `P5FIX_RUNS.json`, `P5FIX_TURN_RECEIPT.json`,
  `P5FIX_OCC_RECEIPT.json`, `P5FIX_GATE.json`, `P7_ASSEMBLY_V11.json`,
  `P7_ASSEMBLY_V11_CHECK.json`, `P5FIX_SERVER_SHUTDOWN_PROOF.json`, previews
  `p5fix_*_coverage_frame*.png` + `p5fix_old_*_clip_strip_f0_30_60_90_119.png` +
  `p7v11_boundary_*.png`.
* Server P5fix đã tắt sạch: `{proof['phase']}` (không còn listener trên 8321).
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

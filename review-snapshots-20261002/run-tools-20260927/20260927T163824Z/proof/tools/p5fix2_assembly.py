"""P5FIX2 assembly v1.2 only (the three GPU jobs already completed; this rerun is the doc/assembly
step that crashed on a dict-key bug).  Also reconstructs P5FIX2_RUNS.json from the job receipts.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import time
import urllib.request

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
BASE = "http://127.0.0.1:8321"
AUDIO = {"BOOK": "BOOK_src.mp4", "TURN": "TURN_795_src.mp4", "OCC": "OCC_14768_src.mp4"}
SEG = {"BOOK": {"clip": PROOF / "output" / "p3b" / "animate2_book_p3b_00001_.mp4", "span": [0, 120],
                "audio": "BOOK_src.mp4"},
       "TURN": {"clip": PROOF / "output" / "p5fix_turn" / "animate2_turn_p5fix_00001_.mp4",
                "span": [0, 120], "audio": "TURN_795_src.mp4"},
       "OCC_SEG1": {"clip": PROOF / "output" / "p5fix2_occ_seg1" / "animate2_occ_seg1_p5fix2_00001_.mp4",
                    "span": [0, 102], "audio": "OCC_14768_src.mp4"},
       "OCC_SEG2": {"clip": PROOF / "output" / "p5fix2_occ_seg2" / "animate2_occ_seg2_p5fix2_00001_.mp4",
                    "span": [102, 120], "audio": "(the OCC window audio continues)"}}


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate,duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0] if r.returncode == 0 else {}


# --- reconstruct P5FIX2_RUNS.json from the per-job receipts --------------------------------
runs = {"artifact": "P5FIX2_RUNS.json", "reconstructed": True,
        "source": "per-job receipts + P5fix2_run.stdout.txt (the first assembly attempt crashed on a "
                  "dict-key bug AFTER all three GPU jobs completed)", "jobs": {}}
for name, rec_name in (("ANCHOR_OCC_SEG2", "P5FIX2_ANCHOR_SEG2_RECEIPT.json"),
                       ("OCC_SEG1", "P5FIX2_SEG1_RECEIPT.json"),
                       ("OCC_SEG2", "P5FIX2_SEG2_RECEIPT.json")):
    p = EVID / rec_name
    runs["jobs"][name] = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"missing": True}
(EVID / "P5FIX2_RUNS.json").write_text(json.dumps(runs, indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")

# --- assembly v1.2 -------------------------------------------------------------------------
g, segs = {}, []
order = ("BOOK", "TURN", "OCC_SEG1", "OCC_SEG2")
for i, unit in enumerate(order):
    cfg = SEG[unit]
    dst = PROOF / "inputs" / f"p7v12_{unit.lower()}.mp4"
    if not dst.exists() or sha(dst) != sha(cfg["clip"]):
        shutil.copy2(cfg["clip"], dst)
    pr = ffprobe(dst)
    segs.append({"unit": unit, "file": str(cfg["clip"].relative_to(PROOF)).replace("\\", "/"),
                 "staged_copy": f"inputs/p7v12_{unit.lower()}.mp4", "sha256": sha(dst),
                 "frames": int(pr.get("nb_read_frames") or 0),
                 "dims": [pr.get("width"), pr.get("height")], "fps": pr.get("r_frame_rate"),
                 "duration": pr.get("duration"), "source_span": cfg["span"],
                 "audio_file": cfg["audio"],
                 "audio_sha256": sha(PROOF / "inputs" / "OCC_14768_src.mp4") if cfg["audio"].startswith("(")
                 else sha(PROOF / "inputs" / {v: v for v in AUDIO.values()}[cfg["audio"]])})
    g[str(10 + i)] = {"class_type": "LoadVideo", "inputs": {"file": f"p7v12_{unit.lower()}.mp4"}}
for i, key in enumerate(("BOOK", "TURN", "OCC")):
    g[str(20 + i)] = {"class_type": "LoadAudio", "inputs": {"audio": AUDIO[key]}}
g["31"] = {"class_type": "AudioConcat",
           "inputs": {"audio1": ["20", 0], "audio2": ["21", 0], "direction": "after"}}
g["32"] = {"class_type": "AudioConcat",
           "inputs": {"audio1": ["31", 0], "audio2": ["22", 0], "direction": "after"}}
g["40"] = {"class_type": "ConcatenateVideo",
           "inputs": {"videos.video0": ["10", 0], "videos.video1": ["11", 0],
                      "videos.video2": ["12", 0], "videos.video3": ["13", 0],
                      "codec": "auto", "complete_audio": ["32", 0]}}
g["50"] = {"class_type": "SaveVideo",
           "inputs": {"video": ["40", 0], "filename_prefix": "p7/assembly_v12",
                      "format": "auto", "format.codec": "auto", "codec": "auto"}}
gp = PROOF / "graphs" / "p7_assembly_v12.api.json"
gp.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
outdir = PROOF / "output" / "p7"
outdir.mkdir(parents=True, exist_ok=True)
before = {q.name for q in outdir.rglob("*") if q.is_file()}
req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
    {"prompt": g, "client_id": "mf-p7v12"}).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=180) as r:
    pid_ = json.loads(r.read())["prompt_id"]
print("P7V12 prompt", pid_, flush=True)
hist, deadline = None, time.time() + 1800
while time.time() < deadline:
    try:
        h = json.loads(urllib.request.urlopen(f"{BASE}/history/{pid_}", timeout=60).read())
    except Exception:  # noqa: BLE001
        h = {}
    if pid_ in h and (h[pid_].get("status") or {}).get("completed"):
        hist = h[pid_]
        break
    time.sleep(5)
msgs = (hist or {}).get("status", {}).get("messages", [])
stamps = {m[0]: m[1].get("timestamp") for m in msgs
          if isinstance(m, list) and len(m) == 2 and isinstance(m[1], dict)}
wall = (round((stamps["execution_success"] - stamps["execution_start"]) / 1000.0, 2)
        if stamps.get("execution_success") and stamps.get("execution_start") else None)
after = sorted(q for q in outdir.rglob("*") if q.is_file() and q.name not in before)
media = [{"file": str(q.relative_to(PROOF / "output")).replace("\\", "/"),
          "bytes": q.stat().st_size, "sha256": sha(q), "ffprobe": ffprobe(q)} for q in after]
rec = {"artifact": "P7_ASSEMBLY_V12.json", "version": "v1.2",
       "supersedes": {"file": "output/p7/assembly_v11_00001_.mp4",
                      "why": "OCC split at the MEASURED source cut (frame 102) into two units with "
                             "their own anchors; v1.1 kept OCC as a single unit"},
       "graph": "graphs/p7_assembly_v12.api.json", "graph_sha256": sha(gp), "prompt_id": pid_,
       "completed": bool(hist), "server_side_wall_s": wall, "segments": segs, "order": list(order),
       "total_expected_frames": sum(s["frames"] for s in segs),
       "audio_method": "graph-native LoadAudio x3 on the pinned source windows; the two OCC "
                       "segments share the one OCC window audio (identical 3.994 s span) + "
                       "AudioConcat -> complete_audio",
       "output_files": media, "quality_accepted": False,
       "quality_verdict_owner": "BENCH / DEMO / Codex"}
(EVID / "P7_ASSEMBLY_V12.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
print("P7V12 done", bool(hist), wall, "exp_frames", rec["total_expected_frames"],
      [m["file"] for m in media], flush=True)

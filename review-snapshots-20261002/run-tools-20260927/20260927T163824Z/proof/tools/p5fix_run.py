"""P5fix runs: TURN (p5fix) -> OCC (p5fix) -> assembly v1.1, all sequential on one warm server.

The assembly pins every segment (unit, file, sha256, frames, audio source file + sha) into
P7_ASSEMBLY_V11.json so the composition can never drift from the previews again.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
BASE = "http://127.0.0.1:8321"
sys.path.insert(0, str(PROOF / "tools"))
import p567_runs  # noqa: E402

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
p567_runs.PID = PID

CLIPS = {"BOOK": PROOF / "output" / "p3b" / "animate2_book_p3b_00001_.mp4",
         "TURN": PROOF / "output" / "p5fix_turn" / "animate2_turn_p5fix_00001_.mp4",
         "OCC": PROOF / "output" / "p5fix_occ" / "animate2_occ_p5fix_00001_.mp4"}
SOURCES = {"BOOK": PROOF / "inputs" / "BOOK_src.mp4",
           "TURN": PROOF / "inputs" / "TURN_795_src.mp4",
           "OCC": PROOF / "inputs" / "OCC_14768_src.mp4"}
AUDIO_NAME = {"BOOK": "BOOK_src.mp4", "TURN": "TURN_795_src.mp4", "OCC": "OCC_14768_src.mp4"}


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


def run_jobs():
    out = {}
    for name, graph_rel, out_rel, receipt, seed in (
            ("P5FIX_TURN", "graphs/animate2_turn.p5fix.api.json", "output/p5fix_turn",
             "P5FIX_TURN_RECEIPT.json", 2026092811),
            ("P5FIX_OCC", "graphs/animate2_occ.p5fix.api.json", "output/p5fix_occ",
             "P5FIX_OCC_RECEIPT.json", 2026092812)):
        try:
            out[name] = p567_runs.run_job(name, graph_rel, out_rel, receipt, seed)
        except Exception as e:  # noqa: BLE001
            out[name] = {"completed": False, "error": repr(e)[:300]}
            print(name, "ERROR", repr(e)[:120], flush=True)
    return out


def build_assembly():
    g, segs = {}, []
    for i, unit in enumerate(("BOOK", "TURN", "OCC")):
        src = CLIPS[unit]
        dst = PROOF / "inputs" / f"p7v11_{unit.lower()}.mp4"
        if not dst.exists() or sha(dst) != sha(src):
            shutil.copy2(src, dst)
        p = ffprobe(dst)
        segs.append({"unit": unit, "file": str(src.relative_to(PROOF)).replace("\\", "/"),
                     "staged_copy": f"inputs/p7v11_{unit.lower()}.mp4", "sha256": sha(dst),
                     "frames": int(p.get("nb_read_frames") or 0),
                     "dims": [p.get("width"), p.get("height")], "fps": p.get("r_frame_rate"),
                     "duration": p.get("duration"),
                     "audio_file": AUDIO_NAME[unit], "audio_sha256": sha(SOURCES[unit]),
                     "audio_window_seconds": 3.993991})
        g[str(10 + i)] = {"class_type": "LoadVideo",
                          "inputs": {"file": f"p7v11_{unit.lower()}.mp4"}}
        g[str(20 + i)] = {"class_type": "LoadAudio", "inputs": {"audio": AUDIO_NAME[unit]}}
    g["31"] = {"class_type": "AudioConcat",
               "inputs": {"audio1": ["20", 0], "audio2": ["21", 0], "direction": "after"}}
    g["32"] = {"class_type": "AudioConcat",
               "inputs": {"audio1": ["31", 0], "audio2": ["22", 0], "direction": "after"}}
    g["40"] = {"class_type": "ConcatenateVideo",
               "inputs": {"videos.video0": ["10", 0], "videos.video1": ["11", 0],
                          "videos.video2": ["12", 0], "codec": "auto", "complete_audio": ["32", 0]}}
    g["50"] = {"class_type": "SaveVideo",
               "inputs": {"video": ["40", 0], "filename_prefix": "p7/assembly_v11",
                          "format": "auto", "format.codec": "auto", "codec": "auto"}}
    p = PROOF / "graphs" / "p7_assembly_v11.api.json"
    p.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return g, segs, p


def submit_assembly(g, segs, gpath):
    outdir = PROOF / "output" / "p7"
    outdir.mkdir(parents=True, exist_ok=True)
    before = {q.name for q in outdir.rglob("*") if q.is_file()}
    req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
        {"prompt": g, "client_id": "mf-p7v11"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        pid_ = json.loads(r.read())["prompt_id"]
    print("P7V11 prompt", pid_, flush=True)
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
    rec = {"artifact": "P7_ASSEMBLY_V11.json", "version": "v1.1",
          "supersedes": {"file": "output/p7/assembly_v1_00001_.mp4",
                         "why": "v1 used the p5 TURN/OCC clips whose content failed the coverage "
                                "gate (wrong prompt); v1.1 uses the p5fix clips"},
          "graph": "graphs/p7_assembly_v11.api.json", "graph_sha256": sha(gpath),
          "prompt_id": pid_, "completed": bool(hist), "server_side_wall_s": wall,
          "segments": segs, "order": [s["unit"] for s in segs],
          "total_expected_frames": sum(s["frames"] for s in segs),
          "audio_method": "graph-native LoadAudio x3 on the pinned source windows + AudioConcat "
                          "chain -> ConcatenateVideo.complete_audio (no ffmpeg remux)",
          "output_files": media, "quality_accepted": False,
          "quality_verdict_owner": "BENCH / DEMO / Codex"}
    (EVID / "P7_ASSEMBLY_V11.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    print("P7V11 done", bool(hist), wall, [m["file"] for m in media], flush=True)
    return rec


if __name__ == "__main__":
    runs = run_jobs()
    (EVID / "P5FIX_RUNS.json").write_text(json.dumps({"artifact": "P5FIX_RUNS.json", "jobs": runs},
                                                     indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    if all(runs.get(k, {}).get("completed") for k in ("P5FIX_TURN", "P5FIX_OCC")):
        g, segs, gpath = build_assembly()
        submit_assembly(g, segs, gpath)
    else:
        print("assembly skipped: a p5fix run did not complete", flush=True)

"""P5FIX3: run the SEG2 fix, gate it, then build assembly v1.3 - one script, one server."""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
PREV = EVID / "previews"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p5fix3_gate")
BASE = "http://127.0.0.1:8321"
sys.path.insert(0, str(PROOF / "tools"))
import p567_runs  # noqa: E402

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
p567_runs.PID = PID
AUDIO = {"BOOK": "BOOK_src.mp4", "TURN": "TURN_795_src.mp4", "OCC": "OCC_14768_src.mp4"}
SEG = {"BOOK": {"clip": PROOF / "output" / "p3b" / "animate2_book_p3b_00001_.mp4", "span": [0, 120],
                "audio": "BOOK_src.mp4"},
       "TURN": {"clip": PROOF / "output" / "p5fix_turn" / "animate2_turn_p5fix_00001_.mp4",
                "span": [0, 120], "audio": "TURN_795_src.mp4"},
       "OCC_SEG1": {"clip": PROOF / "output" / "p5fix2_occ_seg1" / "animate2_occ_seg1_p5fix2_00001_.mp4",
                    "span": [0, 102], "audio": "OCC_14768_src.mp4"},
       "OCC_SEG2": {"clip": PROOF / "output" / "p5fix3_occ_seg2" / "animate2_occ_seg2_p5fix3_00001_.mp4",
                    "span": [102, 120], "audio": "(OCC window audio continues)"}}
SEG2_SRC = PROOF / "inputs" / "p5fix2_occ_seg2.mp4"


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                        "stream=index,codec_type,codec_name,width,height,nb_read_frames,"
                        "r_frame_rate,duration,sample_rate,channels", "-of", "json", str(p)],
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else {}


def vinfo(p):
    return next((s for s in probe(p).get("streams", []) if s["codec_type"] == "video"), {})


def pts(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        t = line.strip().split(",")[0].strip()
        if t:
            try:
                out.append(round(float(t), 5))
            except ValueError:
                pass
    return out


def frame(p, idx, tag):
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}{tag}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def pair(p_src, i_src, p_gen, i_gen, title, out_name):
    s = frame(p_src, i_src, "_src")
    gimg = frame(p_gen, i_gen, "_gen")
    sb = s.resize(gimg.size, Image.Resampling.LANCZOS) if s.size != gimg.size else s
    sheet = Image.new("RGB", (gimg.size[0] * 2 + 8, gimg.size[1] + 18), (24, 24, 28))
    sheet.paste(sb, (0, 18))
    sheet.paste(gimg, (gimg.size[0] + 8, 18))
    ImageDraw.Draw(sheet).text((4, 3), title, fill=(235, 235, 235))
    sp = PREV / out_name
    sheet.save(sp)
    return f"previews/{sp.name}"


def main():
    out = {"artifact": "P5FIX3_RUN.json", "jobs": {}}
    try:
        out["jobs"]["P5FIX3_SEG2"] = p567_runs.run_job(
            "P5FIX3_SEG2", "graphs/animate2_occ_seg2.p5fix3.api.json", "output/p5fix3_occ_seg2",
            "P5FIX3_SEG2_RECEIPT.json", 2026092841)
    except Exception as e:  # noqa: BLE001
        out["jobs"]["P5FIX3_SEG2"] = {"completed": False, "error": repr(e)[:300]}
        print("SEG2 ERROR", repr(e)[:110], flush=True)
    gate = {"artifact": "P5FIX3_GATE.json", "segment": "OCC_SEG2", "quality_accepted": False}
    gen = SEG["OCC_SEG2"]["clip"]
    if gen.is_file():
        v = vinfo(gen)
        n = int(v.get("nb_read_frames") or 0)
        t = pts(gen)
        gate["video"] = {"file": "p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4",
                         "sha256": sha(gen), "bytes": gen.stat().st_size,
                         "dims": [v.get("width"), v.get("height")], "frames": n,
                         "fps": v.get("r_frame_rate"), "duration": v.get("duration")}
        gate["gates"] = {"frames_18_span": n == 18, "dims_640x368": [v.get("width"), v.get("height")] == ["640", "368"],
                         "fps_30_1": v.get("r_frame_rate") == "30/1",
                         "pts_count": len(t), "pts_monotonic": all(b > a for a, b in zip(t, t[1:]))}
        gate["coverage_previews"] = [pair(SEG2_SRC, i, gen, i,
                                          f"P5FIX3 OCC_SEG2 seg f{i}: SOURCE | GEN",
                                          f"p5fix3_occ_seg2_frame{i:03d}_src_vs_gen.png")
                                     for i in (0, 8, 17)]
        print("seg2", gate["video"]["dims"], n, "frames", gate["gates"], flush=True)
    if out["jobs"].get("P5FIX3_SEG2", {}).get("completed") and gen.is_file():
        g, segs = {}, []
        order = ("BOOK", "TURN", "OCC_SEG1", "OCC_SEG2")
        for i, unit in enumerate(order):
            cfg = SEG[unit]
            dst = PROOF / "inputs" / f"p7v13_{unit.lower()}.mp4"
            if not dst.exists() or sha(dst) != sha(cfg["clip"]):
                shutil.copy2(cfg["clip"], dst)
            pr = vinfo(dst)
            segs.append({"unit": unit, "file": str(cfg["clip"].relative_to(PROOF)).replace("\\", "/"),
                         "staged_copy": f"inputs/p7v13_{unit.lower()}.mp4", "sha256": sha(dst),
                         "frames": int(pr.get("nb_read_frames") or 0),
                         "dims": [pr.get("width"), pr.get("height")], "fps": pr.get("r_frame_rate"),
                         "duration": pr.get("duration"), "source_span": cfg["span"],
                         "audio_file": cfg["audio"]})
            g[str(10 + i)] = {"class_type": "LoadVideo",
                              "inputs": {"file": f"p7v13_{unit.lower()}.mp4"}}
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
                   "inputs": {"video": ["40", 0], "filename_prefix": "p7/assembly_v13",
                              "format": "auto", "format.codec": "auto", "codec": "auto"}}
        gp = PROOF / "graphs" / "p7_assembly_v13.api.json"
        gp.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        outdir = PROOF / "output" / "p7"
        before = {q.name for q in outdir.rglob("*") if q.is_file()}
        req = urllib.request.Request(BASE + "/prompt", data=json.dumps(
            {"prompt": g, "client_id": "mf-p7v13"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            pid_ = json.loads(r.read())["prompt_id"]
        print("P7V13 prompt", pid_, flush=True)
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
                  "bytes": q.stat().st_size, "sha256": sha(q), "ffprobe": vinfo(q)} for q in after]
        rec = {"artifact": "P7_ASSEMBLY_V13.json", "version": "v1.3", "final_for_verify": True,
               "supersedes": ["output/p7/assembly_v12_00001_.mp4",
                              "output/p7/assembly_v11_00001_.mp4",
                              "output/p7/assembly_v1_00001_.mp4"],
               "why": "v1.3 uses the fixed OCC_SEG2 clip (own prompt for the person-at-table scene) "
                      "and keeps every other accepted segment unchanged",
               "graph": "graphs/p7_assembly_v13.api.json", "graph_sha256": sha(gp),
               "prompt_id": pid_, "completed": bool(hist), "server_side_wall_s": wall,
               "segments": segs, "order": list(order),
               "total_expected_frames": sum(s["frames"] for s in segs),
               "audio_method": "graph-native LoadAudio x3 (the two OCC segments share the one OCC "
                               "window audio) + AudioConcat -> complete_audio",
               "output_files": media, "quality_accepted": False,
               "quality_verdict_owner": "BENCH / DEMO / Codex"}
        (EVID / "P7_ASSEMBLY_V13.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
        if media:
            asm = PROOF / "output" / "p7" / media[0]["file"].split("/")[-1]
            d = probe(asm)
            v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), {})
            au = next((s for s in d.get("streams", []) if s["codec_type"] == "audio"), {})
            chk = {"artifact": "P7_ASSEMBLY_V13_CHECK.json",
                   "assembly": {"file": media[0]["file"], "sha256": media[0]["sha256"],
                                "bytes": media[0]["bytes"]},
                   "video": {"codec": v.get("codec_name"), "dims": [v.get("width"), v.get("height")],
                             "frames": v.get("nb_read_frames"), "fps": v.get("r_frame_rate"),
                             "duration": v.get("duration")},
                   "audio": {"present": bool(au), "codec": au.get("codec_name"),
                             "sample_rate": au.get("sample_rate"), "channels": au.get("channels"),
                             "duration": au.get("duration")},
                   "expected_frames": rec["total_expected_frames"],
                   "gates": {"frames_match_segments": v.get("nb_read_frames") == str(rec["total_expected_frames"]),
                             "dims_640x368": [int(v.get("width", 0)), int(v.get("height", 0))] == [640, 368],
                             "duration_12s": abs(float(v.get("duration") or 0) - 12.0) < 0.05,
                             "audio_present": bool(au),
                             "audio_duration_close": (abs(float(au.get("duration") or 0) - 12.0) < 0.2
                                                      if au else False)},
                   "cut_previews": [pair(asm, a, asm, b, f"v1.3 cut {a}->{b}",
                                         f"p7v13_cut_{a}_{b}.png") for a, b in ((119, 120), (239, 240), (341, 342))],
                   "quality_accepted": False, "quality_verdict_owner": "BENCH / DEMO / Codex"}
            (EVID / "P7_ASSEMBLY_V13_CHECK.json").write_text(
                json.dumps(chk, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print("v13", chk["video"], "audio", au.get("codec_name"), "gates", chk["gates"], flush=True)
    (EVID / "P5FIX3_RUN.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    (EVID / "P5FIX3_GATE.json").write_text(json.dumps(gate, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")


if __name__ == "__main__":
    main()

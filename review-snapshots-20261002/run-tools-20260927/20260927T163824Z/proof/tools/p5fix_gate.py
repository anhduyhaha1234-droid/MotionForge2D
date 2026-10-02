"""P5fix gates: dense-frame coverage previews for the new TURN/OCC clips + a dense strip of the
OLD p5 clips (to pin the assembly-vs-preview inconsistency the manager flagged).

Technical gates: dims 640x368, 120 frames, 30/1, 4.000 s, PTS monotonic, motion profile.
Vision verdicts are added by the worker separately; this script only produces the measurements
and the preview images.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
PREV = EVID / "previews"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p5fix_frames")
SRC = {"TURN": PROOF / "inputs" / "TURN_795_src.mp4", "OCC": PROOF / "inputs" / "OCC_14768_src.mp4"}
NEW = {"TURN": PROOF / "output" / "p5fix_turn" / "animate2_turn_p5fix_00001_.mp4",
       "OCC": PROOF / "output" / "p5fix_occ" / "animate2_occ_p5fix_00001_.mp4"}
OLD = {"TURN": PROOF / "output" / "p5_turn" / "animate2_turn_p5_00001_.mp4",
       "OCC": PROOF / "output" / "p5_occ" / "animate2_occ_p5_00001_.mp4"}
FRAMES = (0, 30, 60, 90, 119)


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


def arr(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    w, h = [int(x) for x in r.stdout.strip().split(",")[:2]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)


def strip(clips, out_name, title, scale=0.45):
    tiles = [(idx, frame(clips, idx, "_strip")) for idx in FRAMES]
    w, h = tiles[0][1].size
    tw, th = int(w * scale), int(h * scale)
    sheet = Image.new("RGB", (tw * 5, th + 18), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    d.text((4, 3), title, fill=(235, 235, 235))
    for k, (idx, im) in enumerate(tiles):
        sheet.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (k * tw, 18))
        d.text((k * tw + 3, 18 + th - 12), f"f{idx}", fill=(255, 235, 120))
    sp = PREV / out_name
    sheet.save(sp)
    return f"previews/{sp.name}"


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    res = {"artifact": "P5FIX_GATE.json", "round": "R28-PROOF-P5FIX", "shots": {},
           "quality_accepted": False, "quality_verdict_owner": "BENCH / DEMO / Codex"}
    for shot in ("TURN", "OCC"):
        clip, src = NEW[shot], SRC[shot]
        if not clip.is_file():
            res["shots"][shot] = {"present": False}
            continue
        p = ffprobe(clip)
        t = pts(clip)
        row = {"present": True, "file": str(clip.relative_to(PROOF)).replace("\\", "/"),
               "bytes": clip.stat().st_size, "sha256": sha(clip), "ffprobe": p,
               "dims_640x368": [p.get("width"), p.get("height")] == ["640", "368"] or
                               [p.get("width"), p.get("height")] == [640, 368],
               "frames_120": p.get("nb_read_frames") == "120",
               "fps_30_1": p.get("r_frame_rate") == "30/1",
               "duration_4s": p.get("duration") == "4.000000",
               "pts_monotonic": all(b > a for a, b in zip(t, t[1:])), "pts_count": len(t),
               "coverage_previews": []}
        a = arr(clip)
        d = [round(float(np.abs(a[i + 1].astype(np.int16) - a[i].astype(np.int16)).mean()), 4)
             for i in range(a.shape[0] - 1)]
        dd = np.array(d) if d else np.zeros(1)
        row["motion"] = {"median": round(float(np.median(dd)), 4),
                         "p99": round(float(np.percentile(dd, 99)), 4),
                         "zero_pairs": int((dd == 0).sum())}
        for idx in FRAMES:
            gen = frame(clip, idx, f"_{shot}")
            s = frame(src, min(idx, 119), "_src")
            sb = s.resize(gen.size, Image.Resampling.LANCZOS) if s.size != gen.size else s
            sheet = Image.new("RGB", (gen.size[0] * 2 + 8, gen.size[1] + 18), (24, 24, 28))
            sheet.paste(sb, (0, 18))
            sheet.paste(gen, (gen.size[0] + 8, 18))
            ImageDraw.Draw(sheet).text((4, 3), f"P5FIX {shot} frame {idx}: SRC | GEN",
                                       fill=(235, 235, 235))
            sp = PREV / f"p5fix_{shot.lower()}_coverage_frame{idx:03d}_src_vs_gen.png"
            sheet.save(sp)
            row["coverage_previews"].append({"frame": idx, "sheet": f"previews/{sp.name}"})
        if OLD[shot].is_file():
            row["old_clip_strip"] = strip(OLD[shot],
                                          f"p5fix_old_{shot.lower()}_clip_strip_f0_30_60_90_119.png",
                                          f"OLD p5 {shot} clip (wrong prompt) f0/30/60/90/119")
            row["old_clip"] = {"file": str(OLD[shot].relative_to(PROOF)).replace("\\", "/"),
                               "sha256": sha(OLD[shot]), "ffprobe": ffprobe(OLD[shot])}
        res["shots"][shot] = row
        print(shot, row["dims_640x368"], p.get("nb_read_frames"), p.get("r_frame_rate"),
              row["pts_monotonic"], row["motion"]["median"], row["sha256"][:16])
    (EVID / "P5FIX_GATE.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    print("saved P5FIX_GATE.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

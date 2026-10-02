"""P5FIX2 gates: per-segment technical + coverage previews, and the v1.2 assembly check.

Segment expectations: OCC_SEG1 = 102 frames (span [0,102)), OCC_SEG2 = 18 frames (span [102,120)).
The script records the ACTUAL produced counts and whether they match the spans, then builds
source-vs-generated previews at the first/middle/last frame of each segment, plus the v1.2 assembly
frame/audio gates and boundary sheets at every cut (119/120, 239/240, 341/342).
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
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p5fix2_frames")
SEGS = {"OCC_SEG1": {"gen": PROOF / "output" / "p5fix2_occ_seg1" / "animate2_occ_seg1_p5fix2_00001_.mp4",
                     "src": PROOF / "inputs" / "p5fix2_occ_seg1.mp4", "span": [0, 102]},
        "OCC_SEG2": {"gen": PROOF / "output" / "p5fix2_occ_seg2" / "animate2_occ_seg2_p5fix2_00001_.mp4",
                     "src": PROOF / "inputs" / "p5fix2_occ_seg2.mp4", "span": [102, 120]}}
ASM = PROOF / "output" / "p7" / "assembly_v12_00001_.mp4"
P107 = PROOF / "inputs" / "p7v12_occ_seg1.mp4"
P108 = PROOF / "inputs" / "p7v12_occ_seg2.mp4"


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
    d = probe(p)
    return next((s for s in d.get("streams", []) if s["codec_type"] == "video"), {})


def pts(p, limit=None):
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
        if limit and len(out) >= limit:
            break
    return out


def frame(p, idx, tag):
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}{tag}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def pair_sheet(p_src, p_gen, idx_src, idx_gen, title, out_name):
    s = frame(p_src, idx_src, "_src")
    g = frame(p_gen, idx_gen, "_gen")
    sb = s.resize(g.size, Image.Resampling.LANCZOS) if s.size != g.size else s
    sheet = Image.new("RGB", (g.size[0] * 2 + 8, g.size[1] + 18), (24, 24, 28))
    sheet.paste(sb, (0, 18))
    sheet.paste(g, (g.size[0] + 8, 18))
    ImageDraw.Draw(sheet).text((4, 3), title, fill=(235, 235, 235))
    sp = PREV / out_name
    sheet.save(sp)
    return f"previews/{sp.name}"


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    res = {"artifact": "P5FIX2_GATE.json", "round": "R28-PROOF-P5FIX2", "segments": {},
           "quality_accepted": False, "quality_verdict_owner": "BENCH / DEMO / Codex"}
    for name, cfg in SEGS.items():
        if not cfg["gen"].is_file():
            res["segments"][name] = {"present": False}
            continue
        v = vinfo(cfg["gen"])
        t = pts(cfg["gen"])
        n = int(v.get("nb_read_frames") or 0)
        span = cfg["span"]
        row = {"present": True, "file": str(cfg["gen"].relative_to(PROOF)).replace("\\", "/"),
               "bytes": cfg["gen"].stat().st_size, "sha256": sha(cfg["gen"]),
               "video": {k: v.get(k) for k in ("width", "height", "nb_read_frames", "r_frame_rate",
                                               "duration")},
               "span": span, "span_frames": span[1] - span[0],
               "frames_exact_span": n == span[1] - span[0],
               "dims_640x368": [v.get("width"), v.get("height")] == ["640", "368"],
               "fps_30_1": v.get("r_frame_rate") == "30/1",
               "pts_count": len(t), "pts_monotonic": all(b > a for a, b in zip(t, t[1:])),
               "coverage_previews": []}
        idxs = [0, n // 2, n - 1]
        for k, gi in zip(("first", "mid", "last"), idxs):
            si = min(sum(span) // 2 if False else gi, span[1] - span[0] - 1)
            row["coverage_previews"].append({
                "frame": f"{k} (gen f{gi} / src f{si})",
                "sheet": pair_sheet(cfg["src"], cfg["gen"], si, gi,
                                    f"P5FIX2 {name} {k}: SEGMENT SRC | GEN",
                                    f"p5fix2_{name.lower()}_{k}_src_vs_gen.png")})
        res["segments"][name] = row
        print(name, "frames", n, "span", span[1] - span[0], "exact", row["frames_exact_span"],
              "dims", [v.get("width"), v.get("height")], "sha", row["sha256"][:16])
    # ---- assembly v1.2 -----------------------------------------------------------------
    if ASM.is_file():
        d = probe(ASM)
        v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), {})
        au = next((s for s in d.get("streams", []) if s["codec_type"] == "audio"), {})
        seg_parts = {}
        exp = 0
        for k, p in (("BOOK", PROOF / "inputs" / "p7v12_book.mp4"),
                     ("TURN", PROOF / "inputs" / "p7v12_turn.mp4"), ("OCC_SEG1", P107),
                     ("OCC_SEG2", P108)):
            if p.is_file():
                vv = vinfo(p)
                seg_parts[k] = {"sha256": sha(p), "frames": int(vv.get("nb_read_frames") or 0)}
                exp += seg_parts[k]["frames"]
        cuts = [(119, 120), (239, 240), (341, 342)]
        sheets = []
        for a, b in cuts:
            sheets.append(pair_sheet(ASM, ASM, a, b, f"v1.2 cut {a}->{b}",
                                     f"p7v12_cut_{a}_{b}.png"))
        chk = {"artifact": "P7_ASSEMBLY_V12_CHECK.json", "assembly": {
            "file": "p7/assembly_v12_00001_.mp4", "bytes": ASM.stat().st_size, "sha256": sha(ASM)},
            "video": {"codec": v.get("codec_name"), "dims": [v.get("width"), v.get("height")],
                      "frames": v.get("nb_read_frames"), "fps": v.get("r_frame_rate"),
                      "duration": v.get("duration")},
            "audio": {"present": bool(au), "codec": au.get("codec_name"),
                      "sample_rate": au.get("sample_rate"), "channels": au.get("channels"),
                      "duration": au.get("duration")},
            "segments": seg_parts, "expected_frames": exp,
            "gates": {"frames_match_segments": v.get("nb_read_frames") == str(exp),
                      "dims_640x368": [v.get("width"), v.get("height")] == [640, 368],
                      "duration_12s": (abs(float(v.get("duration") or 0) - 12.0) < 0.05),
                      "audio_present": bool(au),
                      "audio_duration_close": (abs(float(au.get("duration") or 0) - 12.0) < 0.2
                                               if au else False)},
            "cut_previews": sheets, "quality_accepted": False,
            "quality_verdict_owner": "BENCH / DEMO / Codex"}
        (EVID / "P7_ASSEMBLY_V12_CHECK.json").write_text(json.dumps(chk, indent=1, ensure_ascii=False) + "\n",
                                                         encoding="utf-8")
        res["assembly_v12"] = chk["gates"] | {"frames": v.get("nb_read_frames"), "expected": exp}
        print("v12", chk["video"], "audio", au.get("codec_name"), au.get("duration"),
              "gates", chk["gates"])
    else:
        res["assembly_v12"] = {"present": False}
    (EVID / "P5FIX2_GATE.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    print("saved P5FIX2_GATE.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

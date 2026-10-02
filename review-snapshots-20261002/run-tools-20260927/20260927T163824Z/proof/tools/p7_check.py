"""P7 assembly check: frame count, duration, audio stream, cut boundaries, reopenability."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
EVID = PROOF / "evidence"
PREV = EVID / "previews"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p7_frames")
ASM = PROOF / "output" / "p7" / "assembly_v1_00001_.mp4"
PARTS = {"BOOK": PROOF / "output" / "p3b" / "animate2_book_p3b_00001_.mp4",
         "TURN": PROOF / "output" / "p5_turn" / "animate2_turn_p5_00001_.mp4",
         "OCC": PROOF / "output" / "p5_occ" / "animate2_occ_p5_00001_.mp4"}


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(p: pathlib.Path, streams: bool = True) -> dict:
    args = ["ffprobe", "-v", "error", "-count_frames", "-show_entries",
            "stream=index,codec_type,codec_name,width,height,nb_read_frames,r_frame_rate,"
            "duration,sample_rate,channels,nb_streams", "-show_entries", "format=duration,"
            "format_name,nb_streams", "-of", "json", str(p)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr[-300:]}
    d = json.loads(r.stdout)
    return {"format": d.get("format"), "streams": d.get("streams", []) if streams else None}


def frame(p: pathlib.Path, idx: int, tag: str) -> Image.Image:
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}{tag}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    a = probe(ASM)
    v = next((s for s in a["streams"] if s["codec_type"] == "video"), {})
    au = next((s for s in a["streams"] if s["codec_type"] == "audio"), {})
    parts = {k: {"file": str(p.relative_to(PROOF)).replace("\\", "/"), "sha256": sha(p),
                 "ffprobe": probe(p)} for k, p in PARTS.items()}
    expected_frames = sum(int(next(s for s in parts[k]["ffprobe"]["streams"]
                                   if s["codec_type"] == "video")["nb_read_frames"]) for k in PARTS)
    check = {"artifact": "P7_ASSEMBLY_CHECK.json", "round": "R28-PROOF-P7",
             "assembly": {"file": "p7/assembly_v1_00001_.mp4", "bytes": ASM.stat().st_size,
                          "sha256": sha(ASM), "probe": a},
             "video": {"codec": v.get("codec_name"), "dims": [v.get("width"), v.get("height")],
                       "frames": v.get("nb_read_frames"), "fps": v.get("r_frame_rate"),
                       "duration": v.get("duration")},
             "audio": {"present": bool(au), "codec": au.get("codec_name"),
                       "sample_rate": au.get("sample_rate"), "channels": au.get("channels"),
                       "duration": au.get("duration")},
             "expected": {"frames": expected_frames, "duration_s": 12.0, "dims": [640, 368],
                          "order": ["BOOK", "TURN", "OCC"]},
             "gates": {}, "parts": parts}
    check["gates"]["frames_match_parts"] = v.get("nb_read_frames") == str(expected_frames)
    check["gates"]["duration_12s"] = v.get("duration") == "12.000000"
    check["gates"]["dims_640x368"] = [v.get("width"), v.get("height")] == [640, 368]
    check["gates"]["audio_present"] = bool(au)
    check["gates"]["audio_duration_close"] = (
        abs(float(au.get("duration") or 0) - 12.0) < 0.2 if au else False)
    check["gates"]["reopenable"] = not a.get("error")
    # cut boundaries: frames around 120 and 240 plus the first/last frame
    tiles = []
    for idx, label in ((0, "start"), (119, "BOOK last"), (120, "TURN first"),
                       (239, "TURN last"), (240, "OCC first"), (359, "end")):
        tiles.append((idx, label, frame(ASM, idx, "_asm")))
    w, h = tiles[0][2].size
    sc = 0.5
    tw, th = int(w * sc), int(h * sc)
    sheet = Image.new("RGB", (tw * 3, (th + 18) * 2), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    for k, (idx, label, im) in enumerate(tiles):
        x, y = (k % 3) * tw, (k // 3) * (th + 18)
        sheet.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (x, y + 18))
        d.text((x + 3, y + 3), f"f{idx} {label}", fill=(235, 235, 235))
    sp = PREV / "p7_boundary_frames.png"
    sheet.save(sp)
    check["boundary_preview"] = f"previews/{sp.name}"
    check["quality_accepted"] = False
    check["quality_verdict_owner"] = "BENCH / DEMO / Codex"
    (EVID / "P7_ASSEMBLY_CHECK.json").write_text(json.dumps(check, indent=1, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    print(json.dumps({"gates": check["gates"], "video": check["video"], "audio": check["audio"],
                      "expected_frames": expected_frames, "boundary": check["boundary_preview"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

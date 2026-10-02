"""Assembly v1.1 check: frames/duration/dims/audio gates + boundary sheet at the two cuts."""
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
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p7v11_frames")
ASM = PROOF / "output" / "p7" / "assembly_v11_00001_.mp4"
SEG = {"BOOK": PROOF / "inputs" / "p7v11_book.mp4", "TURN": PROOF / "inputs" / "p7v11_turn.mp4",
       "OCC": PROOF / "inputs" / "p7v11_occ.mp4"}


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


def frame(p, idx, tag):
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}{tag}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def main() -> int:
    a = probe(ASM)
    v = next((s for s in a["streams"] if s["codec_type"] == "video"), {})
    au = next((s for s in a["streams"] if s["codec_type"] == "audio"), {})
    parts = {}
    exp_frames = 0
    for k, p in SEG.items():
        pr = probe(p)
        vv = next((s for s in pr["streams"] if s["codec_type"] == "video"), {})
        parts[k] = {"file": f"inputs/p7v11_{k.lower()}.mp4", "sha256": sha(p),
                    "frames": int(vv.get("nb_read_frames") or 0),
                    "dims": [vv.get("width"), vv.get("height")], "duration": vv.get("duration")}
        exp_frames += parts[k]["frames"]
    tiles = [(0, "f0"), (119, "f119 BOOK last"), (120, "f120 TURN first"),
             (239, "f239 TURN last"), (240, "f240 OCC first"), (359, "f359 end")]
    imgs = [(lbl, frame(ASM, i, "_v11")) for i, lbl in tiles]
    w, h = imgs[0][1].size
    sc = 0.5
    tw, th = int(w * sc), int(h * sc)
    for name, subset in (("p7v11_boundary_book_turn.png", imgs[:3]),
                         ("p7v11_boundary_turn_occ.png", imgs[3:])):
        sheet = Image.new("RGB", (tw * min(3, len(subset)), th + 18), (24, 24, 28))
        d = ImageDraw.Draw(sheet)
        d.text((4, 3), "assembly v1.1 boundaries", fill=(235, 235, 235))
        for k, (lbl, im) in enumerate(subset):
            sheet.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (k * tw, 18))
            d.text((k * tw + 3, th - 6), lbl, fill=(255, 235, 120))
        sheet.save(PREV / name)
    chk = {"artifact": "P7_ASSEMBLY_V11_CHECK.json", "assembly": {
        "file": "p7/assembly_v11_00001_.mp4", "bytes": ASM.stat().st_size, "sha256": sha(ASM)},
        "video": {"codec": v.get("codec_name"), "dims": [v.get("width"), v.get("height")],
                  "frames": v.get("nb_read_frames"), "fps": v.get("r_frame_rate"),
                  "duration": v.get("duration")},
        "audio": {"present": bool(au), "codec": au.get("codec_name"),
                  "sample_rate": au.get("sample_rate"), "channels": au.get("channels"),
                  "duration": au.get("duration")},
        "segments": parts, "expected_frames": exp_frames,
        "gates": {"frames_match_segments": v.get("nb_read_frames") == str(exp_frames),
                  "duration_12s": v.get("duration") == "12.000000",
                  "dims_640x368": [v.get("width"), v.get("height")] == ["640", "368"],
                  "audio_present": bool(au),
                  "audio_duration_close": (abs(float(au.get("duration") or 0) - 12.0) < 0.2
                                           if au else False)},
        "boundary_previews": ["previews/p7v11_boundary_book_turn.png",
                              "previews/p7v11_boundary_turn_occ.png"],
        "quality_accepted": False, "quality_verdict_owner": "BENCH / DEMO / Codex"}
    (EVID / "P7_ASSEMBLY_V11_CHECK.json").write_text(json.dumps(chk, indent=1, ensure_ascii=False) + "\n",
                                                     encoding="utf-8")
    print("v11", chk["video"], "audio", chk["audio"]["codec"], chk["audio"]["duration"],
          "gates", chk["gates"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

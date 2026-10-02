"""P3 decode check: frame count / fps / PTS of the generated clip vs the pinned source span,
plus a contact sheet of the generated frames for the reviewer."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
P3 = PROOF / "output" / "p3"
PREV = PROOF / "evidence" / "previews"
SRC = PROOF / "inputs" / "BOOK_src.mp4"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p3_frames")


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(p: pathlib.Path, count: bool = False) -> dict:
    entries = ("stream=width,height,nb_read_frames,r_frame_rate,avg_frame_rate,duration,nb_frames"
               if count else
               "stream=width,height,r_frame_rate,duration,nb_frames")
    args = ["ffprobe", "-v", "error"] + (["-count_frames"] if count else []) + [
        "-select_streams", "v:0", "-show_entries", entries, "-of", "json", str(p)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr[-300:]}
    s = json.loads(r.stdout)["streams"][0]
    return {k: s.get(k) for k in ("nb_frames", "nb_read_frames", "r_frame_rate", "avg_frame_rate",
                                  "width", "height", "duration", "time_base", "start_time")}


def pts_list(p: pathlib.Path) -> list:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                        "-show_entries", "frame=pts_time,pkt_dts_time,best_effort_timestamp_time",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                try:
                    out.append(round(float(tok), 4))
                    break
                except ValueError:
                    continue
    return out


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    vids = sorted(P3.glob("*.mp4"))
    rep = {"artifact": "P3_DECODE_CHECK.json", "videos": [], "source": probe(SRC, count=True),
           "source_sha256": sha(SRC), "source_pts_first_last": None}
    spts = pts_list(SRC)
    rep["source_pts_first_last"] = [spts[0], spts[-1]] if spts else None
    for v in vids:
        p = probe(v, count=True)
        pts = pts_list(v)
        row = {"file": v.name, "bytes": v.stat().st_size, "sha256": sha(v), "ffprobe": p,
               "pts_first": pts[0] if pts else None, "pts_last": pts[-1] if pts else None,
               "pts_count": len(pts), "pts_monotonic": all(b > a for a, b in zip(pts, pts[1:])),
               "frames_match_source": (p.get("nb_read_frames") == rep["source"].get("nb_read_frames")
                                       and p.get("nb_read_frames") is not None),
               "fps_matches_source": p.get("r_frame_rate") == rep["source"].get("r_frame_rate"),
               "duration_matches_source": p.get("duration") == rep["source"].get("duration")}
        rep["videos"].append(row)
        # contact sheet: 8 evenly spaced generated frames
        TMP.mkdir(parents=True, exist_ok=True)
        n = int(p.get("nb_read_frames") or 0) or 8
        idx = [round(i * (n - 1) / 7) for i in range(8)]
        frames = []
        for i in idx:
            fp = TMP / f"{v.stem}_f{i:04d}.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(v),
                            "-vf", f"select='eq(n\\,{i})'", "-frames:v", "1", str(fp)],
                           capture_output=True, text=True)
            if fp.is_file() and fp.stat().st_size > 0:
                frames.append((i, Image.open(fp).convert("RGB")))
        if frames:
            w, h = frames[0][1].size
            sheet = Image.new("RGB", (w * 4, (h + 16) * 2), (24, 24, 28))
            d = ImageDraw.Draw(sheet)
            for k, (i, im) in enumerate(frames[:8]):
                x, y = (k % 4) * w, (k // 4) * (h + 16)
                sheet.paste(im, (x, y + 16))
                d.text((x + 4, y + 3), f"{v.name} frame {i}", fill=(235, 235, 235))
            sp = PREV / f"p3_{v.stem}_frames_contact_sheet.png"
            sheet.save(sp)
            row["contact_sheet"] = f"previews/{sp.name}"
            row["frames_sampled"] = [i for i, _ in frames]
    rep["all_videos"] = len(vids)
    (PROOF / "evidence" / "P3_DECODE_CHECK.json").write_text(
        json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({v["file"]: {"frames": v["ffprobe"].get("nb_read_frames"),
                                  "fps": v["ffprobe"].get("r_frame_rate"),
                                  "dur": v["ffprobe"].get("duration"),
                                  "frames_match": v["frames_match_source"],
                                  "pts_first_last": [v["pts_first"], v["pts_last"]],
                                  "contact_sheet": v.get("contact_sheet")}
                      for v in rep["videos"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

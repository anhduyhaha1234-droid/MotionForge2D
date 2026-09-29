"""P4 verification: geometry/timing gates, a declared 120-frame trim for the A/B, coverage
previews and a P3b-vs-P4 side-by-side for the same frames."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
P4 = PROOF / "output" / "p4"
P3B = PROOF / "output" / "p3b"
PREV = PROOF / "evidence" / "previews"
SRC = PROOF / "inputs" / "BOOK_src.mp4"
TMP = pathlib.Path(r"C:/Users/Admin/AppData/Local/Temp/mf_p4_frames")


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate,duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0] if r.returncode == 0 else {"error": r.stderr[-200:]}


def pts_times(p: pathlib.Path) -> list:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        tok = line.strip().split(",")[0].strip()
        if tok:
            try:
                out.append(round(float(tok), 5))
            except ValueError:
                pass
    return out


def save_frame(p: pathlib.Path, idx: int, tag: str = "") -> Image.Image:
    TMP.mkdir(parents=True, exist_ok=True)
    fp = TMP / f"{p.stem}{tag}_f{idx:04d}.png"
    if not fp.is_file():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-vf",
                        f"select='eq(n\\,{idx})'", "-frames:v", "1", str(fp)],
                       capture_output=True, text=True)
    return Image.open(fp).convert("RGB")


def diff_profile(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    w, h = [int(x) for x in r.stdout.strip().split(",")[:2]]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    a = np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)
    d = [round(float(np.abs(a[i + 1].astype(np.int16) - a[i].astype(np.int16)).mean()), 4)
         for i in range(n - 1)]
    dd = np.array(d) if d else np.zeros(1)
    return {"frames": n, "median": round(float(np.median(dd)), 4),
            "p99": round(float(np.percentile(dd, 99)), 4), "max": round(float(dd.max()), 4),
            "zero_pairs": int((dd == 0).sum())}


def main() -> int:
    PREV.mkdir(parents=True, exist_ok=True)
    raw_v = sorted(P4.glob("*.mp4"))
    assert raw_v, "no output in output/p4"
    main_raw = raw_v[0]
    probe = ffprobe(main_raw)
    trimmed = None
    if probe.get("nb_read_frames") == "121":
        trimmed = P4 / (main_raw.stem + "_trim120.mp4")
        if not trimmed.is_file():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(main_raw), "-frames:v", "120",
                            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(trimmed)],
                           capture_output=True, text=True)
    ref = trimmed if (trimmed and trimmed.is_file()) else main_raw
    ref_probe = ffprobe(ref)
    pts = pts_times(ref)
    n = int(ref_probe.get("nb_read_frames") or 0)
    gate = {"artifact": "P4_GEOMETRY_GATE.json", "round": "R28-PROOF-P4",
            "model_family": "WanVaceToVideo 14B fp16",
            "graph": "graphs/animate2_vace_book.p4.api.json",
            "graph_sha256": sha(PROOF / "graphs" / "animate2_vace_book.p4.api.json"),
            "raw_output": {"file": f"p4/{main_raw.name}", "bytes": main_raw.stat().st_size,
                           "sha256": sha(main_raw), "ffprobe": probe},
            "trim_policy": ("the node needs length 4n+1 = 121 frames, so the raw clip carries 121; "
                            "a DECLARED 120-frame copy (first 120 frames, re-encoded crf18) is used "
                            "for the A/B against P3b, exactly as the packet asks"),
            "comparison_artifact": {"file": f"p4/{ref.name}", "bytes": ref.stat().st_size,
                                    "sha256": sha(ref), "ffprobe": ref_probe},
            "dims_gate": {"measured": [int(ref_probe.get("width", 0)),
                                       int(ref_probe.get("height", 0))],
                          "pass": [int(ref_probe.get("width", 0)),
                                   int(ref_probe.get("height", 0))] == [640, 368],
                          "expected": [640, 368]},
            "timing_gate": {"frames": ref_probe.get("nb_read_frames"),
                            "fps": ref_probe.get("r_frame_rate"),
                            "duration": ref_probe.get("duration"),
                            "frames_120": ref_probe.get("nb_read_frames") == "120",
                            "fps_30_1": ref_probe.get("r_frame_rate") == "30/1",
                            "pts_count": len(pts), "pts_first": pts[0] if pts else None,
                            "pts_last": pts[-1] if pts else None,
                            "pts_monotonic": all(b > a for a, b in zip(pts, pts[1:]))},
            "motion_profile": diff_profile(ref),
            "all_outputs": {p.name: {"bytes": p.stat().st_size, "sha256": sha(p),
                                     "ffprobe": ffprobe(p)} for p in sorted(P4.glob("*.mp4"))},
            "quality_accepted": False, "quality_verdict_owner": "BENCH / DEMO / Codex"}
    # coverage previews (source vs P4) and A/B (P3b vs P4) on the same frames
    p3b_main = P3B / "animate2_book_p3b_00001_.mp4"
    cov, ab = [], []
    for idx in (0, 60, 119):
        gen = save_frame(ref, idx, "_p4")
        s = save_frame(SRC, min(idx, 119), "_src")
        sb = s.resize(gen.size, Image.Resampling.LANCZOS) if s.size != gen.size else s
        sheet = Image.new("RGB", (gen.size[0] * 2 + 8, gen.size[1] + 18), (24, 24, 28))
        sheet.paste(sb, (0, 18))
        sheet.paste(gen, (gen.size[0] + 8, 18))
        dd = ImageDraw.Draw(sheet)
        dd.text((4, 3), f"P4 frame {idx}: SOURCE (left) | VACE 14B generated (right)",
                fill=(235, 235, 235))
        sp = PREV / f"p4_coverage_frame{idx:03d}_src_vs_gen.png"
        sheet.save(sp)
        cov.append({"frame": idx, "sheet": f"previews/{sp.name}", "gen_dims": list(gen.size)})
        if p3b_main.is_file():
            a = save_frame(p3b_main, idx, "_p3b")
            ab_sheet = Image.new("RGB", (a.size[0] * 2 + 8, a.size[1] + 18), (24, 24, 28))
            ab_sheet.paste(a, (0, 18))
            ab_sheet.paste(gen.resize(a.size, Image.Resampling.LANCZOS), (a.size[0] + 8, 18))
            da = ImageDraw.Draw(ab_sheet)
            da.text((4, 3), f"frame {idx}: P3b Animate2 (left) | P4 VACE 14B (right)",
                    fill=(235, 235, 235))
            ap = PREV / f"p4_ab_frame{idx:03d}_p3b_vs_p4.png"
            ab_sheet.save(ap)
            ab.append({"frame": idx, "sheet": f"previews/{ap.name}"})
    gate["coverage_previews"] = cov
    gate["ab_previews"] = ab
    gate["coverage_verdict"] = "SEE_VISION_PASS"
    gate["hard_relations"] = {"who_holds_the_book": "SEE_VISION_PASS",
                              "partial_person_visible": "SEE_VISION_PASS"}
    (PROOF / "evidence" / "P4_GEOMETRY_GATE.json").write_text(
        json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"dims": gate["dims_gate"], "timing": gate["timing_gate"],
                      "motion": gate["motion_profile"],
                      "raw": gate["raw_output"]["ffprobe"], "ab": ab}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

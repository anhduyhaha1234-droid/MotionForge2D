"""MF-V1-VIDEO14B wave A — F06 corrective export (decoded-index selection).

DEFECT (reviewer F06, row P1)
-----------------------------
`R/tools/w2_export_clip.py` cut the 121-frame render with

    ffmpeg -i raw -map 0:v:0 -c:v copy -frames:v 120

i.e. it kept the first 120 **encoded packets in demux order** and then rewrote the
PTS of the surviving pad frame.  The reviewer's decoded-PNG SHA map
(`READ/raw-to-export-pixel-map.json`) proves that is not the same thing: the
delivered clip is decoded 0..118 + decoded **120**, so decoded frame 119 (real
content, film frame 1769) was dropped and the model's held pad frame was kept in
its place.  Counting encoded packets and re-basing PTS cannot fix that, because
packet order != decoded presentation order.

FIX
---
1. decode the 121-frame render ONCE into a lossless intermediate (FFV1/NUT) and
   hash every decoded frame (PNG SHA) -> index selection is now separated from
   encode loss;
2. select **decoded presentation indices 0..119** (drop decoded index 120 = the
   held pad) with the ffmpeg `select` filter, which sees frames in presentation
   order, not in packet order;
3. re-encode the selected 120 frames ONCE as H.264 with `-crf 0` (mathematically
   lossless in yuv420p) so the exact-frame identity property of the old
   stream-copy export is preserved *without* the packet-order bug;
4. mux the frozen source film's [55.000, 59.000) audio window with `-c:a copy`
   (never regenerated, never time-stretched);
5. prove the result by decoding the delivered clip back to PNG and comparing the
   per-frame SHA against the 121 raw decoded frames.

CPU only: ffmpeg decode/encode. No ComfyUI, no model, no GPU.

usage:
  python v14b_export_decode.py <raw_121f.mp4> <film.mp4> <out_dir> <evidence_dir> [work_dir]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

N_SOURCE_FRAMES = 120          # BOOK window length in decoded frames
N_RENDER_FRAMES = 121          # 120 + 1 held pad frame (Wan 4n+1)
PAD_DECODED_INDEX = 120        # the frame that MUST be dropped
FPS = 30
WINDOW_START_S = 55.000
WINDOW_LEN_S = 4.000
TB_TIMESCALE = 15360           # 1/15360 s, the frozen source film's time base

# wave B (F07 geometry): the model generates on a 640x368 canvas built from the
# 640x360 source by a PURE TRANSLATION pad of 4 rows top + 4 rows bottom, so the
# delivered clip must be cropped back to 640x360 at y=4 -- the source content rect
# survives at IDENTICAL coordinates.  Delivering 368, or scaling it back down, is
# forbidden: a scale is a resample and moves every pixel.
CANVAS_W = 640
CANVAS_PAD_H = 368             # generation canvas height (360 + 4 + 4)
CONTENT_H = 360                # source content rect height
CROP_Y = 4                     # top pad height == crop origin y


def crop_back_filter(raw_w: int, raw_h: int) -> dict | None:
    """The crop that restores the 640x360 content rect, or None if not applicable.

    Only the exact pad geometry is cropped: a raw that is already 640x360 (wave A
    behaviour) is left untouched, so this tool stays byte-compatible with the
    F06 record it already produced.
    """
    if raw_w == CANVAS_W and raw_h == CANVAS_PAD_H:
        return {"w": CANVAS_W, "h": CONTENT_H, "x": 0, "y": CROP_Y,
                "ffmpeg": f"crop={CANVAS_W}:{CONTENT_H}:0:{CROP_Y}",
                "rule": ("pure translation pad (top 4 / bottom 4 rows); the content rect "
                         "must survive at identical coordinates, no resampling")}
    return None


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ pure logic

# R9 (reviewer row P2): the raw render carries explicit colour metadata -- limited
# range, bt709 matrix/primaries, iec61966-2-1 transfer -- and this path used to route
# through FFV1/NUT and re-encode WITHOUT re-stating it, so the delivered clip came out
# with an unspecified colour description and every RGB consumer had to guess.  Measured
# on the M1 clip: RGB decoded with its own (absent) tags vs the raw gave MAE mean 2.1182
# / max 18, and forcing these four tags back on decode made RGB identical (120/120).
# The tags are now carried explicitly, and --no-color-tags builds the tag-less control
# that the detector must catch.
COLOR_TAG_KEYS = ("color_range", "color_space", "color_primaries", "color_transfer")
COLOR_TAGS = {"color_range": "tv", "color_space": "bt709",
              "color_primaries": "bt709", "color_transfer": "iec61966-2-1"}
# the same four tags expressed decoder-side, for the RGB comparison in color_roundtrip
SETPARAMS = ("setparams=range=limited:colorspace=bt709:color_primaries=bt709:"
             "color_trc=iec61966-2-1")


assert SETPARAMS == ("setparams=range=%s:colorspace=%s:color_primaries=%s:color_trc=%s" % (
    "limited" if COLOR_TAGS["color_range"] == "tv" else "full",
    COLOR_TAGS["color_space"], COLOR_TAGS["color_primaries"],
    COLOR_TAGS["color_transfer"])), "SETPARAMS must mirror COLOR_TAGS"


def color_filter_args(tags: dict | None = None) -> list[str]:
    """The same four fields as an ffmpeg FILTER argument, never as encoder options.

    Measured on this pipeline: `-color_range tv -colorspace bt709 ...` as ENCODER
    options makes ffmpeg insert a range conversion on the "unspecified" FFV1/NUT
    input -- the clip kept only tv/bt709 and its native planes shifted by up to 32
    (RGB MAE 6.3725 with the tags forced back on decode), which is WORSE than the
    tag loss.  `setparams` only marks the frames: all four fields land in the VUI /
    mp4 colr atom and the native planes stay byte-identical (max_abs_diff 0).
    """
    if not tags:
        return []
    return ["-vf", SETPARAMS]


def color_tag_state(probe: dict) -> dict:
    """The four colour fields of an ffprobe stream dict, verbatim (None == absent)."""
    return {k: probe.get(k) for k in COLOR_TAG_KEYS}


def rgb_frame_diff(a: list[Path], b: list[Path]) -> dict:
    """Per-frame MAE / max-abs between two equal-length PNG sequences, in RGB."""
    import numpy as np
    from PIL import Image
    n = min(len(a), len(b))
    maes: list[float] = []
    maxabs: list[int] = []
    for i in range(n):
        x = np.asarray(Image.open(a[i]).convert("RGB"), dtype=np.int16)
        y = np.asarray(Image.open(b[i]).convert("RGB"), dtype=np.int16)
        d = np.abs(x - y)
        maes.append(float(d.mean()))
        maxabs.append(int(d.max()))
    return {"frames": n, "comparable": len(a) == len(b),
            "mae_mean": round(sum(maes) / len(maes), 6) if maes else None,
            "mae_max": round(max(maes), 6) if maes else None,
            "maxabs_max": max(maxabs) if maxabs else None,
            "identical_frames": sum(1 for m in maes if m == 0.0)}


def png_frames(src: Path, out_dir: Path, log: list[dict], vf: str | None = None) -> list[Path]:
    """extract_pngs(...) but returning the PNG paths, with an optional extra filter."""
    extract_pngs(src, out_dir, log, vf=vf)
    files = sorted(out_dir.glob("f*.png"))
    if not files:
        raise SystemExit(f"no PNG decoded from {src} (0-byte artifact guard)")
    return files


def color_roundtrip(raw: Path, clip: Path, crop_ffmpeg: str | None, log: list[dict]) -> dict:
    """R9: prove the colour metadata survives, and that losing it is DETECTED.

    Three independent measurements, in the reviewer's own order:
      1. native planes  - rawvideo bytes of (raw cropped, decoded 0..119) vs the clip;
      2. RGB, each side decoded with its OWN tags - identical once the tags are carried;
         a tag-less clip makes this non-zero, which is the defect AND the detector's
         positive control (measured pre-fix: MAE mean 2.1182 / max 18 on the M1 clip);
      3. RGB with the source tags FORCED on both sides - must be identical in every mode
         (measured pre-fix: identical, 120/120), so only the signalling was wrong.
    """
    import numpy as np
    work = clip.parent / (clip.stem + "__color")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    sel_vf = select_filter(N_SOURCE_FRAMES, crop_ffmpeg)

    def rawvideo(source: Path, out: Path, vf: str | None) -> np.ndarray:
        argv = ["ffmpeg", "-v", "error", "-y", "-i", str(source)]
        if vf:
            argv += ["-vf", vf]
        argv += ["-f", "rawvideo", "-pix_fmt", "yuv420p", str(out)]
        run(argv, log)
        if not out.is_file() or out.stat().st_size == 0:
            raise SystemExit(f"rawvideo extraction produced nothing: {out}")
        return np.frombuffer(out.read_bytes(), dtype=np.uint8).astype(np.int16)

    a = rawvideo(raw, work / "raw_cropped_119.yuv", sel_vf)
    b = rawvideo(clip, work / "clip_120.yuv", None)
    n = min(len(a), len(b))
    same_len = len(a) == len(b)
    d = np.abs(a[:n] - b[:n])
    native = {"raw_bytes": int(len(a)), "clip_bytes": int(len(b)), "comparable": same_len,
              "max_abs_diff": int(d.max()) if d.size else None,
              "identical": bool(same_len and d.size and int(d.max()) == 0)}

    own = rgb_frame_diff(png_frames(raw, work / "png_raw_own", log, vf=sel_vf),
                         png_frames(clip, work / "png_clip_own", log))
    forced = rgb_frame_diff(
        png_frames(raw, work / "png_raw_forced", log, vf=f"{sel_vf},{SETPARAMS}"),
        png_frames(clip, work / "png_clip_forced", log, vf=SETPARAMS))
    shutil.rmtree(work, ignore_errors=True)
    return {"native_planes": native,
            "rgb_each_side_own_tags": own,
            "rgb_source_tags_forced_both_sides": forced,
            "note": ("(2) is the detector: a clip that lost the tags decodes with a different "
                     "matrix/transfer, so the RGB difference is non-zero; (3) is identical in "
                     "both modes, proving the pixels themselves never changed")}
def presentation_indices(n_total: int, keep: int) -> list[int]:
    """Decoded presentation indices to keep: 0..keep-1, never a packet count."""
    if keep <= 0 or keep > n_total:
        raise ValueError(f"keep={keep} out of range for {n_total} decoded frames")
    return list(range(keep))


def selected_out_decoded_index(n_total: int, keep: int) -> list[int]:
    """The indices that must be ABSENT from the delivered clip."""
    return [i for i in range(n_total) if i not in set(presentation_indices(n_total, keep))]


def select_filter(keep: int, crop: str | None = None) -> str:
    """ffmpeg -vf expression selecting decoded presentation frames [0, keep).

    The crop is applied HERE, inside the selection/CFR step, and never as a scale:
    the selected lossless intermediate must already be the delivered geometry so
    that the encode-loss comparison is made between two same-size videos.
    """
    f = f"select='between(n\\,0\\,{keep - 1})',setpts=N/{FPS}/TB"
    if crop:
        f += f",{crop}"
    return f


def content_rect_diff(full_pngs: list[Path], crop_pngs: list[Path], y: int, h: int) -> dict:
    """Prove the crop is a PURE TRANSLATION: the delivered frame must be exactly the
    raw frame's rows [y, y+h) with no resampling.  Compared in RGB on decoded PNGs;
    a non-zero difference would mean a scale/sharpen crept in."""
    import numpy as np
    from PIL import Image
    n = min(len(full_pngs), len(crop_pngs))
    worst = 0
    mismatched = 0
    for i in range(n):
        full = np.asarray(Image.open(full_pngs[i]).convert("RGB"), dtype=np.int16)
        crop = np.asarray(Image.open(crop_pngs[i]).convert("RGB"), dtype=np.int16)
        d = np.abs(full[y:y + h, :, :] - crop)
        worst = max(worst, int(d.max()))
        if d.max() != 0:
            mismatched += 1
    return {"frames_compared": n, "max_abs_diff": worst, "mismatched_frames": mismatched,
            "pure_translation": worst == 0 and n > 0 and n == len(full_pngs) == len(crop_pngs)}


def ffv1_args() -> list[str]:
    return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p"]


def lossless_h264_args() -> list[str]:
    """`-crf 0` is lossless only in the x264 High 4:4:4 Predictive profile, so the
    profile is NOT forced (x264 picks it itself for yuv420p lossless input)."""
    return ["-c:v", "libx264", "-crf", "0", "-preset", "medium", "-pix_fmt", "yuv420p"]


# ------------------------------------------------------------------ ffmpeg glue

def run(argv: list[str], log: list[dict], cwd: Path | None = None) -> str:
    r = subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    log.append({"argv": argv, "returncode": r.returncode,
                "stdout_tail": (r.stdout or "")[-300:],
                "stderr_tail": (r.stderr or "")[-300:]})
    if r.returncode != 0:
        raise SystemExit(f"command failed (rc={r.returncode}): {argv}\n"
                         f"{(r.stderr or '')[-2000:]}")
    return r.stderr or ""


def extract_pngs(src: Path, out_dir: Path, log: list[dict],
                 vf: str | None = None) -> list[dict]:
    """Decode every frame to PNG in presentation order; return [{index, sha256, bytes}].

    `vf` is an optional extra filter chain (used by the R9 colour proof, which must
    decode with an explicit tag set as well as with the stream's own)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = ["ffmpeg", "-v", "error", "-y", "-i", str(src)]
    if vf:
        argv += ["-vf", vf]
    argv += ["-fps_mode", "passthrough", "-f", "image2", "-start_number", "0",
             str(out_dir / "f%03d.png")]
    run(argv, log)
    rows = []
    for png in sorted(out_dir.glob("f*.png")):
        rows.append({"index": int(png.stem[1:]), "sha256": sha256_file(png),
                     "bytes": png.stat().st_size, "png": png.name})
    if not rows:
        raise SystemExit(f"no PNG decoded from {src} (0-byte artifact guard)")
    return rows


def frame_stats(a: Path, b: Path, log: list[dict], vf: str | None = None) -> dict:
    """Per-frame MAE / max-abs between two videos of equal length, in RGB.

    `vf` is passed to BOTH extractions so a comparison is never decided by two
    different colour descriptions (see the SETPARAMS note in main())."""
    import numpy as np
    from PIL import Image
    tmp = a.parent / (a.stem + "__vs__" + b.stem)
    if tmp.exists():
        shutil.rmtree(tmp)
    da, db = tmp / "a", tmp / "b"
    extract_pngs(a, da, log, vf=vf)
    extract_pngs(b, db, log, vf=vf)
    fa, fb = sorted(da.glob("f*.png")), sorted(db.glob("f*.png"))
    if len(fa) != len(fb):
        return {"frames_a": len(fa), "frames_b": len(fb), "comparable": False}
    maes, maxabs = [], []
    for pa, pb in zip(fa, fb):
        x = np.asarray(Image.open(pa).convert("RGB"), dtype=np.int16)
        y = np.asarray(Image.open(pb).convert("RGB"), dtype=np.int16)
        d = np.abs(x - y)
        maes.append(float(d.mean()))
        maxabs.append(int(d.max()))
    return {"frames": len(fa), "comparable": True,
            "mae_mean": sum(maes) / len(maes),
            "mae_max": max(maes), "maxabs_max": max(maxabs),
            "identical_frames": sum(1 for m in maes if m == 0.0)}


def probe_video(path: Path, log: list[dict]) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", "-select_streams", "v:0", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    j = json.loads(r.stdout)
    s = j["streams"][0]
    r2 = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                         "-show_frames", "-select_streams", "v:0", str(path)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    frames = json.loads(r2.stdout).get("frames", [])
    pts = [int(f["pts"]) for f in frames if "pts" in f]
    deltas = sorted({pts[i + 1] - pts[i] for i in range(len(pts) - 1)}) if len(pts) > 1 else []
    return {"codec_name": s.get("codec_name"), "width": s.get("width"),
            "height": s.get("height"), "r_frame_rate": s.get("r_frame_rate"),
            "avg_frame_rate": s.get("avg_frame_rate"), "time_base": s.get("time_base"),
            "nb_frames": s.get("nb_frames"), "duration": s.get("duration"),
            "start_time": s.get("start_time"),
            # R9: the colour description is part of the artifact contract, so the probe
            # carries it -- a projection that drops it cannot tell a tag loss from a fix.
            "color_range": s.get("color_range"), "color_space": s.get("color_space"),
            "color_primaries": s.get("color_primaries"),
            "color_transfer": s.get("color_transfer"),
            "presentation_pts_first": pts[0] if pts else None,
            "presentation_pts_last": pts[-1] if pts else None,
            "presentation_delta_set": deltas,
            "presentation_frame_count": len(pts)}


# ---------------------------------------------------------------------- driver

def main() -> int:
    raw = _p(sys.argv[1])
    film = _p(sys.argv[2])
    out_dir = _p(sys.argv[3])
    ev = _p(sys.argv[4])
    work = _p(sys.argv[5]) if len(sys.argv) > 5 else out_dir / "work"
    for d in (out_dir, ev, work):
        d.mkdir(parents=True, exist_ok=True)
    # R9: the round names its own record instead of overwriting the F06 record.
    record_name = "f06_export_record.json"
    if "--record-name" in sys.argv:
        record_name = Path(sys.argv[sys.argv.index("--record-name") + 1]).name
    record_prefix = "f06"
    if "--record-prefix" in sys.argv:
        record_prefix = sys.argv[sys.argv.index("--record-prefix") + 1]

    log: list[dict] = []
    nut = work / "raw_121f_lossless.ffv1.nut"
    sel = work / "selected_120f_lossless.nut"
    a_win = work / "audio_window_55_59.m4a"

    raw_probe = probe_video(raw, log)
    # R9: carry the source colour metadata EXPLICITLY through every encode.  The raw's
    # tags are pinned: a raw whose tags changed must be re-pinned, not silently exported.
    raw_color_tags = color_tag_state(raw_probe)
    color_tags_disabled = "--no-color-tags" in sys.argv
    tag_args = [] if color_tags_disabled else color_filter_args(COLOR_TAGS)
    if tag_args and raw_color_tags != COLOR_TAGS:
        raise SystemExit(f"raw colour tags {raw_color_tags} != pinned {COLOR_TAGS}")
    crop = crop_back_filter(raw_probe["width"], raw_probe["height"])
    # escape hatch: wave A's frozen record delivered 640x368 and is reproduced
    # byte-for-byte with --no-crop.  Wave B deliberately CHANGES the default to the
    # F07 geometry (crop back to the 640x360 content rect).
    crop_disabled = "--no-crop" in sys.argv
    if crop_disabled:
        crop = None
    crop_ffmpeg = crop["ffmpeg"] if crop else None
    default_name = ("final_book4s_decoded119_640x360.mp4" if crop
                    else "final_book4s_waveA_decoded119.mp4")
    clip_name = default_name
    if "--clip-name" in sys.argv:
        clip_name = sys.argv[sys.argv.index("--clip-name") + 1]
    clip = out_dir / clip_name

    # 1. lossless intermediate: the 121 decoded frames, exact hashes.
    run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-map", "0:v:0",
         # FFV1/NUT does not persist colour tags (probed: all four null), so they are
         # re-stated on the frames at the encode step instead of faked here.
         *ffv1_args(), "-f", "nut", str(nut)], log)
    raw_pngs = extract_pngs(nut, work / "png_raw121", log, vf=SETPARAMS)

    # 2. index selection on DECODED presentation frames (not packets), plus the
    #    crop back to the 640x360 content rect when the raw is the 640x368 canvas.
    keep = N_SOURCE_FRAMES
    idx = presentation_indices(len(raw_pngs), keep)
    dropped = selected_out_decoded_index(len(raw_pngs), keep)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(nut), "-map", "0:v:0",
         "-vf", select_filter(keep, crop_ffmpeg), "-fps_mode", "cfr", "-r", str(FPS),
         *ffv1_args(), "-f", "nut", str(sel)], log)
    sel_pngs = extract_pngs(sel, work / "png_sel120", log, vf=SETPARAMS)

    # 2b. crop evidence: the cropped intermediate is the reference the delivered
    #     clip is compared against, so the pixel map stays at the DELIVERED
    #     geometry instead of comparing 640x360 output against 640x368 raw.
    if crop:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(nut), "-map", "0:v:0",
             "-vf", crop["ffmpeg"], *ffv1_args(),
             "-f", "nut", str(work / "raw_121f_cropped.nut")],
            log)
        compare_pngs = extract_pngs(work / "raw_121f_cropped.nut",
                                    work / "png_raw121_cropped", log, vf=SETPARAMS)
        # extract_pngs returns hash rows; the pixel-level proof needs the PNG paths
        crop_proof = content_rect_diff(sorted((work / "png_raw121").glob("f*.png")),
                                       sorted((work / "png_raw121_cropped").glob("f*.png")),
                                       crop["y"], crop["h"])
    else:
        compare_pngs = raw_pngs
        crop_proof = {"frames_compared": 0, "max_abs_diff": None, "mismatched_frames": None,
                      "pure_translation": None, "note": "no crop applied"}
    raw_pngs_compare = compare_pngs

    # 3. audio: the frozen source film's [55.000, 59.000) window, stream copy.
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{WINDOW_START_S:.3f}", "-i", str(film),
         "-map", "0:a:0", "-c:a", "copy", "-t", f"{WINDOW_LEN_S:.3f}", str(a_win)], log)

    # 4. ONE video re-encode (crf 0 = lossless in yuv420p) + audio stream copy.
    run(["ffmpeg", "-v", "error", "-y", "-i", str(sel), "-i", str(a_win),
         "-map", "0:v:0", "-map", "1:a:0", *lossless_h264_args(), *tag_args,
         "-video_track_timescale", str(TB_TIMESCALE),
         "-c:a", "copy", "-movflags", "+faststart", str(clip)], log)

    # 5. prove it: decode the delivered clip and SHA-match against the raw frames
    #    AT THE DELIVERED GEOMETRY (cropped raw when the crop back was applied).
    out_pngs = extract_pngs(clip, work / "png_out120", log, vf=SETPARAMS)
    raw_sha = {r["index"]: r["sha256"] for r in raw_pngs_compare}
    out_sha = {r["index"]: r["sha256"] for r in out_pngs}
    pixel_map = [{"output_frame": i,
                  "matching_raw_decoded_frames":
                      sorted(j for j, s in raw_sha.items() if s == out_sha[i])}
                 for i in range(len(out_pngs))]
    identity = all(e["matching_raw_decoded_frames"] == [e["output_frame"]]
                   for e in pixel_map)
    pad_present_in_output = raw_sha[PAD_DECODED_INDEX] in set(out_sha.values())
    first_mismatch = next((e for e in pixel_map
                           if e["matching_raw_decoded_frames"] != [e["output_frame"]]), None)

    # 6. selection-level identity (intermediate vs cropped raw) + encode loss.
    sel_identity = all(sel_pngs[i]["sha256"] == raw_pngs_compare[i]["sha256"] for i in idx)
    enc_loss = frame_stats(sel, clip, log, vf=SETPARAMS)
    clip_pr = probe_video(clip, log)
    color_proof = color_roundtrip(raw, clip, crop_ffmpeg, log)
    pts_expect = [i * (TB_TIMESCALE // FPS) for i in range(N_SOURCE_FRAMES)]
    clip_color_tags = color_tag_state(clip_pr)
    tag_loss_present = clip_color_tags != raw_color_tags
    detector_fired = bool(
        tag_loss_present
        and color_proof["rgb_each_side_own_tags"]["maxabs_max"] not in (None, 0)
        and color_proof["rgb_source_tags_forced_both_sides"]["maxabs_max"] == 0)
    contract = {
        "clip_is_640x360": clip_pr["width"] == 640 and clip_pr["height"] == 360,
        "r_frame_rate_is_30_1": clip_pr["r_frame_rate"] == "30/1",
        "time_base_is_1_15360": clip_pr["time_base"] == "1/15360",
        "frame_count_is_120": clip_pr["presentation_frame_count"] == N_SOURCE_FRAMES,
        "pts_is_i_times_512": (clip_pr["presentation_pts_first"] == 0
                               and clip_pr["presentation_delta_set"] == [TB_TIMESCALE // FPS]
                               and clip_pr["presentation_pts_last"] == pts_expect[-1]),
        "duration_is_4_000000": str(clip_pr["duration"]) in ("4.000000", "4.0"),
        "start_time_is_zero": str(clip_pr["start_time"]) in ("0.000000", "0.0"),
    }

    rec = {
        "artifact": record_name,
        "task_id": "MF-V1-VIDEO14B",
        "row": ("F06" if record_name == "f06_export_record.json"
                else "F06+R9 (round C row V00)"),
        "rule": ("select DECODED presentation indices 0..119 out of 121 and drop decoded "
                 "index 120 (the held pad); packet counting is not equivalent"),
        "inputs": {"raw_121f": str(raw), "film": str(film),
                   "raw_sha256": sha256_file(raw), "film_sha256": sha256_file(film)},
        "outputs": {"clip": str(clip), "clip_sha256": sha256_file(clip),
                    "clip_bytes": clip.stat().st_size,
                    "lossless_intermediate": str(nut),
                    "lossless_intermediate_sha256": sha256_file(nut),
                    "selected_intermediate": str(sel),
                    "selected_intermediate_sha256": sha256_file(sel),
                    "audio_window": str(a_win), "audio_window_sha256": sha256_file(a_win)},
        "raw_render_probe": raw_probe,
        "color_tags": {"expected_from_raw": raw_color_tags,
                        "clip": color_tag_state(clip_pr),
                        "disabled_by_flag": color_tags_disabled,
                        "frame_filter_args": tag_args,
                        "nut_persists_tags": False,
                        "encoder_options_rejected": (
                            "measured: -color_* encoder options insert a range conversion on "
                            "the unspecified NUT input (native planes shifted up to 32, RGB "
                            "MAE 6.3725) and wrote only tv/bt709")},
        "color_roundtrip": color_proof,
        "crop_back": crop,
        "crop_back_applied": bool(crop),
        "crop_disabled_by_flag": crop_disabled,
        "crop_is_pure_translation": crop_proof.get("pure_translation"),
        "crop_proof": crop_proof,
        "clip_name": clip_name,
        "decoded_frames_raw": len(raw_pngs),
        "selected_decoded_indices": idx,
        "dropped_decoded_indices": dropped,
        "select_filter": select_filter(keep, crop_ffmpeg),
        "png_decode_tags": SETPARAMS,
        "raw_decoded_frame_sha256": raw_sha,
        "output_decoded_frame_sha256": out_sha,
        "pixel_map": pixel_map,
        "checks": {
            "output_frame_count_is_120": len(out_pngs) == N_SOURCE_FRAMES,
            "pixel_map_is_identity_0_to_119": identity,
            "dropped_frame_absent_from_output": not pad_present_in_output,
            "first_pixel_map_mismatch": first_mismatch,
            "lossless_intermediate_matches_raw_0_to_119": sel_identity,
            "encode_loss_is_zero": enc_loss.get("mae_max") == 0.0,
            "crop_back_applied": bool(crop),
            "crop_is_pure_translation": crop_proof.get("pure_translation"),
            "contract": contract,
            "color_tags_preserved": clip_color_tags == raw_color_tags,
            "native_yuv_identical_0_to_119": color_proof["native_planes"]["identical"],
            "rgb_identical_with_matching_tags":
                color_proof["rgb_source_tags_forced_both_sides"]["maxabs_max"] == 0,
            "rgb_identical_with_own_tags":
                color_proof["rgb_each_side_own_tags"]["maxabs_max"] == 0,
            "detector_fired_on_tag_loss": detector_fired,
        },
        "clip_probe": probe_video(clip, log),
        "encode_loss_vs_intermediate": enc_loss,
        "commands": log,
    }
    (ev / record_name).write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
    (ev / f"{record_prefix}_pixel_map.json").write_text(
        json.dumps(pixel_map, indent=1) + "\n", encoding="utf-8")
    (ev / f"{record_prefix}_decoded_frame_hashes.json").write_text(
        json.dumps({"raw": raw_sha, "output": out_sha}, indent=1) + "\n", encoding="utf-8")
    summary = {k: rec["checks"][k] for k in rec["checks"]}
    summary["color_tags"] = rec["color_tags"]
    summary["color_roundtrip"] = rec["color_roundtrip"]
    if color_tags_disabled:
        summary["negative_control"] = ("tag-less by design: the detector must report "
                                       "tag_loss_present=True and exit non-zero")
    summary.update({"clip_sha256": rec["outputs"]["clip_sha256"],
                    "clip_bytes": rec["outputs"]["clip_bytes"],
                    "clip_probe": rec["clip_probe"],
                    "raw_probe": raw_probe,
                    "encode_loss": enc_loss,
                    "cmd_count": len(log)})
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    ok = (rec["checks"]["color_tags_preserved"]
          and rec["checks"]["native_yuv_identical_0_to_119"]
          and rec["checks"]["rgb_identical_with_matching_tags"]
          and rec["checks"]["rgb_identical_with_own_tags"]
          and (detector_fired if color_tags_disabled else not tag_loss_present)
          and rec["checks"]["output_frame_count_is_120"]
          and rec["checks"]["pixel_map_is_identity_0_to_119"]
          and rec["checks"]["dropped_frame_absent_from_output"]
          and rec["checks"]["lossless_intermediate_matches_raw_0_to_119"]
          and (not rec["checks"]["crop_back_applied"]
               or all(rec["checks"]["contract"].values()))
          and (rec["checks"]["crop_is_pure_translation"] is not False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

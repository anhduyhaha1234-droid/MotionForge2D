"""MF-V1-BENCH probe.py - container/codec/stream facts + PTS frame-correspondence check.

Facts only: nb_frames, r_frame_rate, avg_frame_rate, time_base, per-stream durations,
audio codec/sample-rate/channels, and the frozen-fixture PTS contract
(pts == frame_id * 512, timebase 1/15360, t == frame_id / 30).

CLI:  python probe.py --out <json> <file> [<file> ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def ffprobe_json(path, args) -> dict:
    rc, out, err = C.run(["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
                         label="ffprobe " + " ".join(args[:3]))
    if rc != 0:
        return {"_error": err.strip()[-400:], "_exit": rc}
    return json.loads(out or "{}")


def streams(path) -> dict:
    return ffprobe_json(path, ["-show_streams", "-show_format"])


def decoded_frame_count(path, stream="v:0") -> dict:
    d = ffprobe_json(path, ["-count_frames", "-select_streams", stream,
                            "-show_entries", "stream=nb_read_frames,nb_frames,codec_name"])
    st = (d.get("streams") or [{}])[0]
    return {"nb_read_frames": _int(st.get("nb_read_frames")), "nb_frames": _int(st.get("nb_frames"))}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rat(v):
    if not v:
        return None
    if "/" in str(v):
        n, d = str(v).split("/")
        return [int(n), int(d)]
    return [int(v), 1]


def audio_facts(path) -> dict:
    d = streams(path)
    a = [s for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    if not a:
        return {"present": False}
    s = a[0]
    return {"present": True, "index": s.get("index"), "codec": s.get("codec_name"),
            "sample_rate": _int(s.get("sample_rate")), "channels": _int(s.get("channels")),
            "channel_layout": s.get("channel_layout"),
            "bit_rate": _int(s.get("bit_rate")),
            "duration_s": float(s["duration"]) if s.get("duration") else None,
            "time_base": s.get("time_base"), "nb_frames": _int(s.get("nb_frames"))}


def pts_samples(path, t0: float, duration: float, stream="v:0") -> dict:
    """Frame PTS (timebase units) inside [t0, t0+duration) via -read_intervals."""
    # ffprobe snaps the interval START back to the nearest keyframe at/before t0, so
    # the sample covers [keyframe .. t0+duration). request an ABSOLUTE end so the whole
    # window is inside the sample (measured: '55%+4' stops at keyframe+4s, '55%59' does not).
    rc, out, err = C.run(["ffprobe", "-v", "error", "-select_streams", stream,
                          "-read_intervals", "%s%%%s" % (t0, t0 + duration),
                          "-show_entries", "frame=best_effort_timestamp,pts",
                          "-of", "csv=p=0", str(path)],
                         label="ffprobe pts sample")
    pts, bad = [], []
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        first = line.split(",")[0]
        if first in ("", "N/A"):
            bad.append(line)
            continue
        try:
            pts.append(int(float(first)))
        except ValueError:
            bad.append(line)
    return {"t0": t0, "duration": duration, "count": len(pts), "unparsable": bad,
            "pts": pts, "stderr": err.strip()[-200:], "exit_code": rc}


def pts_contract(path, t0: float, duration: float, window_start_frame: int = None,
                 window_frame_count: int = None,
                 tb_den: int = C.TIMEBASE_DEN, tpf: int = C.TICKS_PER_FRAME,
                 fps: int = C.FPS) -> dict:
    """Verify the frozen-fixture timeline contract on a bounded PTS sample.

    Rules (each a separate measured violation bucket, so a failure names its cause):
      R1 every pts is an exact multiple of ticks_per_frame;
      R2 consecutive pts delta == ticks_per_frame exactly (no drops/repeats);
      R3 t == frame_id / 30 where frame_id = pts // ticks_per_frame;
      R4 the window's own frames [window_start_frame, +window_frame_count) are all
         present in the sample and form a contiguous run (window -> film frame mapping).
         ffprobe snaps the interval start back to a keyframe, so containment - not
         first-frame equality - is the honest test.
    """
    s = pts_samples(path, t0, duration)
    pts = s["pts"]
    v = {"R1_pts_multiple_of_tpf": [], "R2_delta_equals_tpf": [], "R3_t_equals_frame_id_over_30": [],
         "R4_window_frames_present_and_contiguous": []}
    frames = []
    for p in pts:
        if p % tpf != 0:
            v["R1_pts_multiple_of_tpf"].append(p)
        fid = p / float(tpf)
        frames.append(fid)
        if abs((p / float(tb_den)) - (fid / float(fps))) > 1e-9:
            v["R3_t_equals_frame_id_over_30"].append([p, p / float(tb_den), fid / float(fps)])
    for a, b in zip(pts, pts[1:]):
        if b - a != tpf:
            v["R2_delta_equals_tpf"].append([a, b, b - a])
    ids = set(int(round(f)) for f in frames)
    if window_start_frame is not None and window_frame_count:
        want = list(range(window_start_frame, window_start_frame + window_frame_count))
        missing = [f for f in want if f not in ids]
        present = [f for f in want if f in ids]
        contiguous = bool(present) and (max(present) - min(present) + 1) == len(present) == len(want)
        if missing or not contiguous:
            v["R4_window_frames_present_and_contiguous"].append(
                {"missing_frames": missing[:10], "present_in_window": len(present),
                 "wanted": len(want), "contiguous": contiguous})
    return {"path": str(path), "sampled_frames": len(pts), "timebase_den": tb_den,
            "window_start_frame": window_start_frame, "window_frame_count": window_frame_count,
            "seek_landed_on_frame": int(round(frames[0])) if frames else None,
            "ticks_per_frame": tpf, "fps": fps,
            "first_pts": pts[0] if pts else None, "last_pts": pts[-1] if pts else None,
            "frame_ids": frames,
            "violations": {k: v[k] for k in v},
            "call": s,
            "ok": all(len(v[k]) == 0 for k in v) and len(pts) > 0}


def container_facts(path) -> dict:
    d = streams(path)
    st = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    fmt = d.get("format", {})
    out = {"path": str(path), "size_bytes": Path(path).stat().st_size if Path(path).exists() else None,
           "format_name": fmt.get("format_name"), "format_duration_s": _float(fmt.get("duration")),
           "nb_streams": len(d.get("streams", []))}
    if st:
        s = st[0]
        out["video"] = {"codec": s.get("codec_name"), "profile": s.get("profile"),
                        "width": _int(s.get("width")), "height": _int(s.get("height")),
                        "pix_fmt": s.get("pix_fmt"), "time_base": s.get("time_base"),
                        "r_frame_rate": s.get("r_frame_rate"), "avg_frame_rate": s.get("avg_frame_rate"),
                        "nb_frames": _int(s.get("nb_frames")),
                        "duration_s": _float(s.get("duration")), "start_pts": _int(s.get("start_pts")),
                        "start_time_s": _float(s.get("start_time"))}
    out["audio"] = audio_facts(path)
    return out


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def probe_full(path, count_frames: bool = True) -> dict:
    f = container_facts(path)
    f["decoded"] = decoded_frame_count(path) if count_frames else None
    return f


def main(argv):
    out_path = None
    files = []
    i = 0
    while i < len(argv):
        if argv[i] == "--out":
            out_path = argv[i + 1]
            i += 2
        else:
            files.append(argv[i])
            i += 1
    res = {"files": [probe_full(f) for f in files]}
    if out_path:
        C.write_json(out_path, res)
        print("wrote", out_path)
    else:
        print(json.dumps(res, indent=1, ensure_ascii=False)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

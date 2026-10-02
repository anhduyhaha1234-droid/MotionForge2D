#!/usr/bin/env python
"""Lab: synthesize tiny CI fixtures and MEASURE real ffprobe/scenedetect facts.

Decides the fixture parameters for tests/product_delivery/test_mf_end_11.py from
REAL output (no guesses): CFR fps rationals, VFR classification, packet PTS tables,
audio fields, and whether a hard cut is detected at the expected frame.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKTREE = r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11"
sys.path.insert(0, WORKTREE)

from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe  # noqa: E402
from app.services.scene_detection import detect_scenes  # noqa: E402

LAB = Path(r"C:/Users/Admin/AppData/Local/Temp/mfend11_lab")
FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def make_cfr(path: Path) -> None:
    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)])


def make_vfr(path: Path) -> None:
    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=30",
         "-vf", "select='gt(mod(n,7),1)'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])


def make_cut(path: Path) -> None:
    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=30",
         "-f", "lavfi", "-i", "color=black:duration=1:size=160x120:rate=30",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[out]", "-map", "[out]",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])


def make_one(path: Path) -> None:
    run([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=30",
         "-frames:v", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])


def stream_facts(path: Path) -> dict:
    out = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
               "-show_format", str(path)])
    data = json.loads(out.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {
        "r_frame_rate": video.get("r_frame_rate"),
        "avg_frame_rate": video.get("avg_frame_rate"),
        "time_base": video.get("time_base"),
        "nb_frames": video.get("nb_frames"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": (data.get("format") or {}).get("duration"),
        "v_duration": video.get("duration"),
        "audio": None if audio is None else {
            "codec": audio.get("codec_name"), "channels": audio.get("channels"),
            "sample_rate": audio.get("sample_rate"), "duration": audio.get("duration"),
            "index": audio.get("index"),
        },
    }


def packet_facts(path: Path) -> dict:
    out = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "packet=pts", "-of", "csv=p=0", str(path)])
    pts = [int(line.strip().rstrip(",")) for line in (out.stdout or "").splitlines() if line.strip()]
    gaps = [b - a for a, b in zip(pts, pts[1:])]
    deep = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
                "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)])
    return {
        "packet_count": len(pts),
        "first_pts": pts[0] if pts else None,
        "last_pts": pts[-1] if pts else None,
        "first_gaps": gaps[:12],
        "distinct_gaps": sorted(set(gaps)),
        "negative": [p for p in pts if p < 0][:3],
        "nb_read_frames": (deep.stdout or "").strip(),
    }


def main() -> int:
    LAB.mkdir(parents=True, exist_ok=True)
    ver = run([FFMPEG, "-version"]).stdout.splitlines()[0]
    fixtures = {"cfr": LAB / "cfr30.mp4", "vfr": LAB / "vfr_drop.mp4",
                "cut": LAB / "cut_testsrc_black.mp4", "one": LAB / "one_frame.mp4"}
    make_cfr(fixtures["cfr"])
    make_vfr(fixtures["vfr"])
    make_cut(fixtures["cut"])
    make_one(fixtures["one"])
    report: dict = {"ffmpeg": ver, "fixtures": {}}
    for name, path in fixtures.items():
        entry = {"path": str(path), "bytes": path.stat().st_size if path.exists() else 0,
                 "stream": stream_facts(path), "packets": packet_facts(path)}
        if name == "cut":
            scenes = detect_scenes(path)
            entry["scenes"] = [
                {"id": s.scene_id, "start_frame": s.start_frame, "end_frame": s.end_frame,
                 "frame_count": s.frame_count} for s in scenes
            ]
        report["fixtures"][name] = entry
    print(json.dumps(report, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

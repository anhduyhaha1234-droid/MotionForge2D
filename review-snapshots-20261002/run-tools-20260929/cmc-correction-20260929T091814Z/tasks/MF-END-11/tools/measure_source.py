#!/usr/bin/env python
"""MF-END-11 correction — measure source_12s.mp4 from BYTES (no inherited numbers).

Writes raw/ffprobe_source_12s.json and raw/cut_audit_recomputed.json:
* ffprobe streams/timebase/fps/nb_frames/duration/audio;
* REAL scene detection through the app's own production path (detect_scenes);
* my planner's partition (detect_shot_intervals);
* full decode + per-frame mean-abs-delta with PTS (ffprobe frame pts_time).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

C11 = r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11"
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-11"
)
sys.path.insert(0, C11)

from app.services.ffmpeg_utils import find_ffprobe  # noqa: E402
from app.services.scene_detection import detect_scene_intervals, detect_scenes  # noqa: E402
from app.services import shot_reskin_plan as plan  # noqa: E402

SRC_F5 = Path(C11) / "tests" / "fixtures" / "delta_f5" / "source_12s.mp4"
SRC_F7 = Path(C11) / "tests" / "fixtures" / "delta_f7" / "source_12s.mp4"
FFPROBE = find_ffprobe()


def probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)],
        capture_output=True, text=True, timeout=120,
    )
    return json.loads(out.stdout or "{}")


def frame_pts(path: Path) -> list[tuple[int, str]]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=pts,pts_time,best_effort_timestamp", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=600,
    )
    rows: list[tuple[int, str]] = []
    for line in (out.stdout or "").splitlines():
        parts = [p.strip().rstrip(",") for p in line.split(",") if p.strip()]
        if parts:
            try:
                rows.append((int(parts[0]), parts[1] if len(parts) > 1 else ""))
            except ValueError:
                continue
    return rows


def main() -> int:
    out: dict = {"source_fixture": str(SRC_F5), "files": {}}
    for label, path in (("delta_f5", SRC_F5), ("delta_f7", SRC_F7)):
        data = path.read_bytes()
        raw = probe(path)
        v = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
        a = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), None)
        pts_rows = frame_pts(path)
        gaps = [b[0] - a_[0] for a_, b in zip(pts_rows, pts_rows[1:])]
        out["files"][label] = {
            "path": str(path),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "r_frame_rate": v.get("r_frame_rate"),
            "avg_frame_rate": v.get("avg_frame_rate"),
            "time_base": v.get("time_base"),
            "nb_frames": v.get("nb_frames"),
            "width": v.get("width"),
            "height": v.get("height"),
            "codec": v.get("codec_name"),
            "duration_stream": v.get("duration"),
            "duration_format": (raw.get("format") or {}).get("duration"),
            "start_time": (raw.get("format") or {}).get("start_time"),
            "audio": None if a is None else {
                "codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
                "channels": a.get("channels"), "duration": a.get("duration"),
                "time_base": a.get("time_base"), "index": a.get("index"),
            },
            "decoded_frame_rows": len(pts_rows),
            "pts_first": pts_rows[0] if pts_rows else None,
            "pts_last": pts_rows[-1] if pts_rows else None,
            "pts_gaps_distinct": sorted(set(gaps)),
        }
    # Real detector through the app's own production function.
    scenes = detect_scenes(SRC_F5)
    intervals = detect_scene_intervals(SRC_F5)
    out["app_detect_scenes"] = [
        {"scene_id": s.scene_id, "start_frame": s.start_frame, "end_frame_incl": s.end_frame,
         "frame_count": s.frame_count, "start_time_sec": s.start_time_sec,
         "end_time_sec": s.end_time_sec} for s in scenes
    ]
    out["app_detect_scene_intervals_half_open"] = [list(pair) for pair in intervals]
    facts = plan.probe_source_facts(SRC_F5, deep_count=True)
    part = plan.detect_shot_intervals(SRC_F5, facts.frame_count)
    out["planner"] = {
        "frame_count_measured": facts.frame_count,
        "fps": f"{facts.fps_num}/{facts.fps_den}",
        "classification": facts.fps_classification,
        "timebase": None if facts.stream_timebase_num is None
        else f"{facts.stream_timebase_num}/{facts.stream_timebase_den}",
        "pts_first_last": [facts.pts_start_ticks, facts.pts_end_ticks],
        "pts_uniform": facts.pts_uniform,
        "decoded_frame_count": facts.decoded_frame_count,
        "container_nb_frames": facts.container_nb_frames,
        "cuts_from_intervals": [s[0] for s in intervals[1:]],
        "shots": [[s.start_frame, s.end_frame_exclusive] for s in part.shots],
        "dropped_cuts": [c.to_json() for c in part.dropped_cuts],
    }
    (EV / "raw" / "ffprobe_source_12s.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({
        "f5": {k: out["files"]["delta_f5"][k] for k in
               ("sha256", "r_frame_rate", "avg_frame_rate", "time_base", "nb_frames",
                "decoded_frame_rows", "pts_gaps_distinct")},
        "f7_sha256": out["files"]["delta_f7"]["sha256"],
        "identical_fixtures": out["files"]["delta_f5"]["sha256"] == out["files"]["delta_f7"]["sha256"],
        "app_scenes": [(s["start_frame"], s["end_frame_incl"]) for s in out["app_detect_scenes"]],
        "planner_shots": out["planner"]["shots"],
        "planner_decoded": out["planner"]["decoded_frame_count"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

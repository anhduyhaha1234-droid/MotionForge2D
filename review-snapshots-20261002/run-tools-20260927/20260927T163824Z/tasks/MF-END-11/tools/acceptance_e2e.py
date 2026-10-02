#!/usr/bin/env python
"""MF-END-11 acceptance probe — REAL production path over REAL fixtures.

Builds + seals + reloads + invalidates shot plans for the lab fixtures (CFR,
VFR, hard-cut, one-frame), runs the negative controls, and writes
raw/acceptance_e2e.json.  Every number here comes from the real ffprobe /
PySceneDetect path; the fixtures are regenerated if missing.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-11"
sys.path.insert(0, WORKTREE)

from app.services import shot_reskin_plan as plan  # noqa: E402
from app.services.ffmpeg_utils import find_ffmpeg  # noqa: E402

LAB = Path(r"C:/Users/Admin/AppData/Local/Temp/mfend11_lab")
OUT_DIR = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-11/raw"
)
SIZE = "160x120"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=True)


def fixture(name: str) -> Path:
    path = LAB / name
    if path.exists() and path.stat().st_size > 0:
        return path
    ffmpeg = find_ffmpeg()
    if name == "cfr30.mp4":
        run([ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=duration=1:size={SIZE}:rate=30",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-map", "0:v", "-map", "1:a",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])
    elif name == "vfr_drop.mp4":
        run([ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=duration=2:size={SIZE}:rate=30",
             "-vf", "select='gt(mod(n,7),1)'", "-fps_mode", "vfr",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    elif name == "cut_testsrc_black.mp4":
        run([ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=duration=1:size={SIZE}:rate=30",
             "-f", "lavfi", "-i", f"color=black:duration=1:size={SIZE}:rate=30",
             "-filter_complex", "[0:v][1:v]concat=n=2:v=1[out]", "-map", "[out]",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    elif name == "one_frame.mp4":
        run([ffmpeg, "-y", "-f", "lavfi", "-i", f"testsrc=duration=1:size={SIZE}:rate=30",
             "-frames:v", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    else:
        raise SystemExit(f"unknown fixture {name}")
    assert path.stat().st_size > 0, f"fixture {name} is empty"
    return path


def refusals() -> dict[str, str]:
    codes: dict[str, str] = {}

    def grab(label: str, fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs)
            codes[label] = "<NO REFUSAL — BUG>"
        except plan.ShotPlanError as err:
            codes[label] = err.code

    grab("capability_zero", plan.CapabilityFrameLimit, max_frames=0)
    span = plan.SourceSpan(start_frame=0, end_frame_exclusive=10)
    grab("context_over_budget", plan.plan_shot_chunks, span, shot_id="s",
         context_frames_per_side=41)
    grab("coverage_bad_frame_count", plan.plan_shot_intervals, [], 0)
    grab("missing_source", plan.probe_source_facts, LAB / "does_not_exist.mp4")
    grab("unknown_version", plan.ShotPlanArtifact.from_json, {"plan_version": "bogus"})
    grab("half_rational", plan.parse_rational, "1/0")
    return codes


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"fixtures": {}, "negative_controls": refusals(), "plans": {}}
    for name in ("cfr30.mp4", "vfr_drop.mp4", "cut_testsrc_black.mp4", "one_frame.mp4"):
        path = fixture(name)
        facts = plan.probe_source_facts(path, deep_count=name == "cfr30.mp4")
        report["fixtures"][name] = {
            "sha256": facts.source_sha256,
            "bytes": facts.file_size_bytes,
            "fps": f"{facts.fps_num}/{facts.fps_den}",
            "classification": facts.fps_classification,
            "timebase": None
            if facts.stream_timebase_num is None
            else f"{facts.stream_timebase_num}/{facts.stream_timebase_den}",
            "frame_count": facts.frame_count,
            "pts_first_last": [facts.pts_start_ticks, facts.pts_end_ticks],
            "pts_uniform": facts.pts_uniform,
            "decoded_frame_count": facts.decoded_frame_count,
            "container_nb_frames": facts.container_nb_frames,
            "audio": None if facts.audio is None else facts.audio.to_json(),
        }
        capability = plan.CapabilityFrameLimit(max_frames=81, label="comfy.video.4n+1")
        artifact = plan.build_shot_plan(
            path,
            plan_artifact_id=f"plan-{path.stem}",
            source_artifact_id=f"src-{path.stem}",
            capability=capability,
            context_frames_per_side=1,
            deep_count=False,
        )
        payload_path = OUT_DIR / f"plan_{path.stem}.json"
        payload_path.write_text(json.dumps(artifact.to_json(), indent=1), encoding="utf-8")
        reloaded = plan.ShotPlanArtifact.from_json(json.loads(payload_path.read_text("utf-8")))
        verdict = plan.check_plan_validity(reloaded, current_facts=facts)
        report["plans"][name] = {
            "artifact": str(payload_path),
            "artifact_bytes": payload_path.stat().st_size,
            "content_sha256": reloaded.content_sha256,
            "round_trip_identical": reloaded.to_json() == artifact.to_json(),
            "verdict": verdict.to_json(),
            "shots": [
                {
                    "shot_id": shot.shot_id,
                    "span": [shot.span.start_frame, shot.span.end_frame_exclusive],
                    "chunks": [chunk.context_map() for chunk in shot.chunks],
                    "boundary_shifts": [list(pair) for pair in shot.boundary_shifts],
                }
                for shot in reloaded.shots
            ],
            "dropped_cuts": [cut.to_json() for cut in reloaded.dropped_cuts],
        }
    # Invalidation negative control on a REAL byte change.
    cfr = fixture("cfr30.mp4")
    mutated = LAB / "cfr30_mutated.mp4"
    data = cfr.read_bytes() + b"\x00" * 64
    mutated.write_bytes(data)
    artifact = plan.build_shot_plan(cfr, plan_artifact_id="plan-inval")
    verdict = plan.invalidate_if_source_changed(artifact, mutated)
    report["invalidation_mutated_bytes"] = {
        "status": verdict.status,
        "reasons": list(verdict.reasons),
        "expected": verdict.expected_sha256[:16],
        "measured": (verdict.measured_sha256 or "")[:16],
        "mutated_sha256_matches_file": hashlib.sha256(data).hexdigest()
        == verdict.measured_sha256,
    }
    mutated.unlink()
    summary = {
        "fixtures_measured": len(report["fixtures"]),
        "plans_sealed": len(report["plans"]),
        "negative_controls": report["negative_controls"],
        "invalidation": report["invalidation_mutated_bytes"]["status"],
    }
    report["summary"] = summary
    (OUT_DIR / "acceptance_e2e.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

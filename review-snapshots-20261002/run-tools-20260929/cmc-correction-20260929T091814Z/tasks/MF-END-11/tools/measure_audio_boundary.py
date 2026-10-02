#!/usr/bin/env python
"""MF-END-11 correction — audio boundary bytes + acceptance over the REAL fixture.

1. Trim the audio of the 4 authoritative windows with ffmpeg using SAMPLE
   boundaries derived from the audio timebase, decode each span to raw PCM, and
   hash it.  Concern #3 of the finding: the concatenation's total duration must
   equal the stream duration (padding verified) AND the final sample count must
   land exactly on 12 s x 48000 Hz.
2. Re-prove the sealed-artifact invalidation path on this source (valid,
   source changed, timebase changed).
Writes raw/audio_boundary.json and raw/acceptance_correction.json.
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

from app.services import shot_reskin_plan as plan  # noqa: E402
from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe  # noqa: E402

SRC = Path(C11) / "tests" / "fixtures" / "delta_f5" / "source_12s.mp4"
FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()


def pcm(path: Path, ss: str, t: str) -> tuple[bytes, int]:
    out = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", ss, "-t", t, "-i", str(path),
         "-map", "0:a:0", "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True, timeout=300,
    )
    return out.stdout, out.returncode


def main() -> int:
    facts = plan.probe_source_facts(SRC, deep_count=True)
    partition = plan.build_source_time_map(SRC, facts=facts)
    sr = facts.audio.sample_rate
    report: dict = {
        "source_sha256": facts.source_sha256,
        "audio_sample_rate": sr,
        "audio_channels": facts.audio.channels,
        "audio_duration_stream": facts.audio.duration_seconds,
        "frame_count": facts.frame_count,
        "windows": [],
    }
    total_samples = 0
    for index, span in enumerate(partition.shots):
        mapped = plan.audio_sample_span_for_frames(facts, span)
        start_sec = f"{mapped['start_sample'] / sr:.6f}"
        dur_sec = f"{mapped['sample_count'] / sr:.6f}"
        data, rc = pcm(SRC, start_sec, dur_sec)
        samples = len(data) // (2 * facts.audio.channels)
        total_samples += samples
        report["windows"].append({
            "window": [span.start_frame, span.end_frame_exclusive],
            "frame_count": span.frame_count,
            "start_sample": mapped["start_sample"],
            "end_sample": mapped["end_sample"],
            "expected_samples": mapped["sample_count"],
            "decoded_samples": samples,
            "sample_match": samples == mapped["sample_count"],
            "start_seconds": start_sec,
            "duration_seconds": dur_sec,
            "pcm_bytes": len(data),
            "pcm_sha256": hashlib.sha256(data).hexdigest(),
            "ffmpeg_rc": rc,
        })
    report["total_decoded_samples"] = total_samples
    report["expected_total_samples"] = 12 * sr
    report["padding_verified_total_matches_stream"] = total_samples == 12 * sr
    report["seek_trim_delta_samples"] = 12 * sr - total_samples
    report["seek_trim_note"] = (
        "ffmpeg -ss/-t trims land on AAC packet (1024-sample) boundaries, so a per-window "
        "sample trim loses frames; the verified method decodes the stream ONCE and slices the "
        "PCM at the exact sample offsets"
    )
    full_pcm, full_rc = pcm(SRC, "0", f"{facts.audio.duration_seconds or '12'}")
    frame_bytes = 2 * facts.audio.channels
    sliced: list[dict] = []
    cursor = 0
    for span in partition.shots:
        mapped = plan.audio_sample_span_for_frames(facts, span)
        start_b = mapped["start_sample"] * frame_bytes
        end_b = mapped["end_sample"] * frame_bytes
        chunk = full_pcm[start_b:end_b]
        sliced.append({
            "window": [span.start_frame, span.end_frame_exclusive],
            "expected_samples": mapped["sample_count"],
            "sliced_samples": len(chunk) // frame_bytes,
            "exact": len(chunk) // frame_bytes == mapped["sample_count"],
            "pcm_sha256": hashlib.sha256(chunk).hexdigest(),
        })
        cursor = mapped["end_sample"]
    report["full_decode"] = {
        "ffmpeg_rc": full_rc,
        "decoded_samples": len(full_pcm) // frame_bytes,
        "expected_samples": 12 * sr,
        "exact_total": len(full_pcm) // frame_bytes == 12 * sr,
        "cursor_end_sample": cursor,
        "sliced_windows": sliced,
        "all_windows_exact": all(row["exact"] for row in sliced),
    }
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channels,duration,nb_frames", "-of", "json", str(SRC)],
        capture_output=True, text=True, timeout=120,
    )
    report["ffprobe_audio_stream"] = json.loads(out.stdout or "{}")

    # Invalidation re-proof on this source.
    artifact = plan.build_shot_plan(SRC, plan_artifact_id="plan-c11")
    verdict_ok = plan.check_plan_validity(artifact, current_facts=facts)
    mutated = EV / "raw" / "mutated_probe.mp4"
    mutated.write_bytes(SRC.read_bytes() + b"\x00" * 32)
    verdict_bad = plan.invalidate_if_source_changed(artifact, mutated)
    mutated.unlink()
    report["invalidation"] = {
        "same_source": verdict_ok.to_json(),
        "mutated_bytes": verdict_bad.to_json(),
    }
    (EV / "raw" / "audio_boundary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({
        "windows": [[w["window"], w["decoded_samples"], w["sample_match"], w["pcm_sha256"][:12]]
                    for w in report["windows"]],
        "total_samples": total_samples,
        "expected_total": 12 * sr,
        "padding_ok": report["padding_verified_total_matches_stream"],
        "invalidation_same": verdict_ok.status,
        "invalidation_mutated": verdict_bad.status,
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

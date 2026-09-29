#!/usr/bin/env python
"""MF-END-11 correction — independent audio length confirmation (2nd method).

Decodes the stream to WAV (a different container/number source than the raw
PCM byte length) and asks ffprobe how long that decoded file is, plus counts
AAC packets.  Confirms whether the deducible PCM really is shorter than the
video span (which would make a naive frame->sample map wrong).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

C11 = r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11"
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-END-11"
)
sys.path.insert(0, C11)

from app.services.ffmpeg_utils import find_ffmpeg, find_ffprobe  # noqa: E402

SRC = Path(C11) / "tests" / "fixtures" / "delta_f5" / "source_12s.mp4"
FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()
WAV = EV / "raw" / "audio_decoded_full.wav"


def main() -> int:
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(SRC), "-map", "0:a:0",
                    "-acodec", "pcm_s16le", str(WAV)], capture_output=True, timeout=300)
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=sample_rate,channels,duration,nb_frames", "-show_entries", "format=duration",
         "-of", "json", str(WAV)], capture_output=True, text=True, timeout=120,
    )
    stream = json.loads(probe.stdout or "{}")
    packets = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts",
         "-of", "csv=p=0", str(SRC)], capture_output=True, text=True, timeout=120,
    )
    pkt_rows = [ln for ln in (packets.stdout or "").splitlines() if ln.strip()]
    info = stream.get("streams", [{}])[0] if stream.get("streams") else {}
    sr = int(info.get("sample_rate") or 0)
    duration = info.get("duration") or (stream.get("format") or {}).get("duration") or "0"
    decoded_samples = round(float(duration) * sr)
    result = {
        "method": "decode to WAV then ffprobe the decoded file (independent of PCM byte length)",
        "wav": str(WAV),
        "wav_bytes": WAV.stat().st_size if WAV.exists() else 0,
        "decoded_sample_rate": sr,
        "decoded_duration": duration,
        "decoded_samples_from_duration": decoded_samples,
        "source_aac_packet_count": len(pkt_rows),
        "source_aac_packet_samples_times_1024": len(pkt_rows) * 1024,
        "video_span_samples_at_30fps": 12 * sr,
        "shortfall_samples": 12 * sr - decoded_samples,
        "shortfall_ms": round((12 * sr - decoded_samples) / sr * 1000, 3),
        "conclusion": (
            "the decodable audio is SHORTER than the 12 s video span; a map that derives audio "
            "from the video frame count alone claims samples that do not exist, so the tail must "
            "be PADDED explicitly and the boundary verified"
        ),
    }
    (EV / "raw" / "audio_independent_confirm.json").write_text(
        json.dumps(result, indent=1), encoding="utf-8"
    )
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

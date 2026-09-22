"""MF-V1-VIDEO14B wave A — AUDIO_CONTRACT measurement (CPU).

The source audio is an INDEPENDENT stream: it is stream-copied out of the frozen
film's [55.000, 59.000) window and must never be regenerated or time-stretched.

Two different deltas are measured here and must never be conflated:

  container Δ : the clip's AAC stream duration minus the nominal 4.000 s window,
                i.e. how long the container says the stream is   (~ +1.995 ms)
  decoded Δ   : the number of PCM samples the decoder actually produces beyond the
                film window's 176400 samples/channel            (~ +84 samples = +1.905 ms)

usage:
  python v14b_audio_contract.py <clip.mp4> <film.mp4> <out.json>
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WINDOW_START_S = 55.000
WINDOW_LEN_S = 4.000
NOMINAL_SAMPLES = 176400          # 4.000 s * 44100
SR = 44100
AAC_FRAME = 1024


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def run(argv: list[str], log: list[dict]) -> bytes:
    r = subprocess.run(argv, capture_output=True)
    log.append({"argv": argv, "returncode": r.returncode,
                "stdout_bytes": len(r.stdout or b""),
                "stderr_tail": (r.stderr or b"").decode("utf-8", "replace")[-300:]})
    if r.returncode != 0:
        raise SystemExit(f"command failed: {argv}\n{r.stderr[-800:]!r}")
    return r.stdout


def probe_json(path: Path, log: list[dict]) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
               "-show_streams", str(path)], log)
    return json.loads(out)


def audio_stream(j: dict) -> dict | None:
    for s in j["streams"]:
        if s.get("codec_type") == "audio":
            return s
    return None


def main() -> int:
    clip = _p(sys.argv[1])
    film = _p(sys.argv[2])
    out = _p(sys.argv[3])
    log: list[dict] = []

    cp = probe_json(clip, log)
    fp = probe_json(film, log)
    cs, fs = audio_stream(cp), audio_stream(fp)

    # decoded PCM of the clip's audio stream, and of the film's [55,59) window
    clip_pcm = run(["ffmpeg", "-v", "error", "-i", str(clip), "-map", "0:a:0",
                    "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "2", "-ar", str(SR), "-"],
                   log)
    film_pcm = run(["ffmpeg", "-v", "error", "-ss", f"{WINDOW_START_S:.3f}", "-i", str(film),
                    "-map", "0:a:0", "-t", f"{WINDOW_LEN_S:.3f}",
                    "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "2", "-ar", str(SR), "-"],
                   log)

    import numpy as np
    a = np.frombuffer(clip_pcm, dtype="<i2")
    b = np.frombuffer(film_pcm, dtype="<i2")
    n_head = min(len(a), len(b))
    head = a[:n_head]
    d = np.abs(head.astype(np.int32) - b[:n_head].astype(np.int32))

    clip_samples = len(a) // 2
    film_samples = len(b) // 2
    first4 = a[:NOMINAL_SAMPLES * 2]

    container_dur = float(cs.get("duration", 0.0))
    container_delta_s = container_dur - WINDOW_LEN_S
    decoded_delta_samples = clip_samples - NOMINAL_SAMPLES
    decoded_delta_s = decoded_delta_samples / SR

    rec = {
        "artifact": "audio_contract_measurement.json",
        "task_id": "MF-V1-VIDEO14B",
        "clip": str(clip), "clip_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
        "film": str(film), "film_sha256": hashlib.sha256(film.read_bytes()).hexdigest(),
        "window": {"start_s": WINDOW_START_S, "length_s": WINDOW_LEN_S,
                   "nominal_samples_per_channel": NOMINAL_SAMPLES, "sample_rate": SR},
        "clip_audio_stream": {k: cs.get(k) for k in
                              ("codec_name", "profile", "sample_rate", "channels",
                               "nb_frames", "duration", "start_time", "time_base")},
        "film_audio_stream": {k: fs.get(k) for k in
                              ("codec_name", "profile", "sample_rate", "channels",
                               "nb_frames", "duration", "start_time", "time_base")},
        "measured": {
            "clip_decoded_samples_per_channel": clip_samples,
            "film_window_decoded_samples_per_channel": film_samples,
            "clip_decoded_duration_s": clip_samples / SR,
            "film_window_decoded_duration_s": film_samples / SR,
            "first_4s_samples_compared": n_head // 2,
            "first_4s_mae": float(d.mean()) if n_head else None,
            "first_4s_mismatched_samples": int((d > 0).sum()) if n_head else None,
            "first_4s_pcm_bit_exact": bool(n_head == NOMINAL_SAMPLES * 2 and (d == 0).all()),
            "first_4s_pcm_sha256_clip": hashlib.sha256(first4.tobytes()).hexdigest(),
            "film_window_pcm_sha256": hashlib.sha256(b.tobytes()).hexdigest(),
        },
        "delta_labels": {
            "container_delta_s": container_delta_s,
            "container_delta_ms": round(container_delta_s * 1000.0, 6),
            "container_delta_basis": "clip AAC stream duration minus the nominal 4.000 s window",
            "decoded_delta_samples": decoded_delta_samples,
            "decoded_delta_s": decoded_delta_s,
            "decoded_delta_ms": round(decoded_delta_s * 1000.0, 6),
            "decoded_delta_basis": "decoded PCM samples beyond the film window's 176400/channel",
            "note": ("these are two DIFFERENT measurements and must not be quoted as the "
                     "same number"),
        },
        "trailing_aac": {
            "clip_aac_packets": int(cs.get("nb_frames") or 0),
            "packets_for_nominal_4s": -(-NOMINAL_SAMPLES // AAC_FRAME),
            "packets_beyond_nominal": int(cs.get("nb_frames") or 0) - (-(-NOMINAL_SAMPLES // AAC_FRAME)),
            "trailing_samples": decoded_delta_samples,
            "trailing_samples_in_aac_frames": round(decoded_delta_samples / AAC_FRAME, 6),
        },
        "contract": {
            "audio_is_independent_stream": True,
            "audio_regenerated": False,
            "audio_time_stretched": False,
            "how": "ffmpeg -ss 55.000 -t 4.000 before the input, -c:a copy, muxed with -c:a copy",
            "first_4s_must_be_bit_exact": True,
        },
        "commands": log,
    }
    rec["verdict"] = ("AUDIO_CONTRACT_PASS"
                      if rec["measured"]["first_4s_pcm_bit_exact"] else
                      "AUDIO_CONTRACT_FAIL")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": rec["verdict"],
                      "measured": rec["measured"],
                      "delta_labels": rec["delta_labels"],
                      "trailing_aac": rec["trailing_aac"],
                      "clip_audio_stream": rec["clip_audio_stream"]},
                     indent=1, ensure_ascii=False))
    return 0 if rec["verdict"] == "AUDIO_CONTRACT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

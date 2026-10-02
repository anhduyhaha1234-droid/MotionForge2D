"""Manager independent audio check: is the export candidate's audio the ORIGINAL source audio?

Compares the candidate (3840x2160 + aac) against the demo source_12s.mp4 by
decoding both to raw s16le and correlating a mid-clip window. Prints the numbers;
no verdict is invented here - the numbers are the evidence.

usage: python -B audio_check.py <candidate.mp4> <reference.mp4>
"""
from __future__ import annotations

import struct
import subprocess
import sys

FFMPEG = "ffmpeg"


def decode(path: str, seconds: float = 12.0) -> list[float]:
    """Decode the first audio stream to mono float samples at 48 kHz."""
    cmd = [FFMPEG, "-v", "error", "-i", path, "-map", "0:a:0", "-t", str(seconds),
           "-f", "s16le", "-ac", "1", "-ar", "48000", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // 2
    return [s / 32768.0 for s in struct.unpack(f"<{n}h", raw[: n * 2])]


def rms(xs: list[float]) -> float:
    return (sum(x * x for x in xs) / len(xs)) ** 0.5 if xs else 0.0


def corr(a: list[float], b: list[float], lag: int, win: int) -> float:
    """Pearson correlation of a[lag:lag+win] against b[0:win]."""
    xa = a[lag: lag + win]
    xb = b[:win]
    n = min(len(xa), len(xb))
    if n < 2:
        return float("nan")
    xa, xb = xa[:n], xb[:n]
    ma, mb = sum(xa) / n, sum(xb) / n
    va = sum((v - ma) ** 2 for v in xa) ** 0.5
    vb = sum((v - mb) ** 2 for v in xb) ** 0.5
    if va == 0 or vb == 0:
        return float("nan")
    return sum((xa[i] - ma) * (xb[i] - mb) for i in range(n)) / (va * vb)


def main() -> int:
    cand_path, ref_path = sys.argv[1], sys.argv[2]
    cand = decode(cand_path)
    ref = decode(ref_path)
    print(f"candidate={cand_path}")
    print(f"  samples={len(cand)} rms={rms(cand):.1f} peak={max(abs(v) for v in cand[:48000*12]):.3f}")
    print(f"reference={ref_path}")
    print(f"  samples={len(ref)} rms={rms(ref):.1f} peak={max(abs(v) for v in ref):.3f}")

    win = 48000 * 2  # 2-second window
    best = (None, -2.0)
    for lag_ms in range(0, 60):
        lag = int(48000 * lag_ms / 1000)
        if lag + win > len(cand):
            break
        c = corr(cand, ref, lag, win)
        if c == c and c > best[1]:
            best = (lag_ms, c)
    print(f"best_alignment: lag={best[0]}ms  correlation={best[1]:.4f}")

    zero_best = (None, -2.0)
    for lag_ms in range(0, 60):
        lag = int(48000 * lag_ms / 1000)
        if lag + win > len(ref):
            break
        c = corr(ref, ref, lag, win)
        if c == c and c > zero_best[1]:
            zero_best = (lag_ms, c)
    print(f"self_control(ref vs itself): lag={zero_best[0]}ms correlation={zero_best[1]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MF-V1-PROPAGATE — bounded source-appearance propagation (worker implementation).

Package layout
--------------
contract   frozen GOLDEN fixture reader + freeze verification + timeline helpers
ledger     command ledger (argv, cwd, start/end, exit, duration) + run_log wrapper
decode     bounded chunked, frame-exact source decode (never whole-film into RAM)
guides     edge / mask / optical-flow / point guides (each independently switchable)
propagate  bidirectional gather propagation, reconciliation, resets, group constraint
compose    final-pixel assembly, single authoritative sample map, premultiplied alpha
measure    measured metrics on FINAL pixels (fidelity, structure, contact, continuity)
run        per-window driver (+ guide ablation runs, resource measurement)
report     aggregate evidence writers
"""
from __future__ import annotations

import os

VERSION = "1.0.0"

# ---------------------------------------------------------------- fixed paths
GOLDEN_ROOT = r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\mf-reskin-v1\20260917T110554Z\GOLDEN"
EV_ROOT = r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\mf-reskin-v1\20260917T110554Z\PROPAGATE"
RUNTIME_ROOT = r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\propagate"
WT_ROOT = r"C:\Users\Admin\Documents\Codex\work\mfv1\wt-propagate"
PKG_ROOT = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------- source clock
FPS = 30.0
TICKS_PER_FRAME = 512
TIME_BASE_DEN = 15360
WIDTH = 640
HEIGHT = 360
FRAME_DIAGONAL_PX = (WIDTH ** 2 + HEIGHT ** 2) ** 0.5  # 734.575...

# ------------------------------------------------------- bounded memory knob
# Hard ceiling on how many source frames may be resident at once.  A window is
# processed as anchor-to-anchor segments, so this ceiling bounds decode+working
# set regardless of window length.  Reported in every run record.
MAX_FRAMES_RESIDENT = 32


def pts_of(frame_id: int) -> int:
    """pts = frame_id * 512 exactly (timebase 1/15360)."""
    return int(frame_id) * TICKS_PER_FRAME


def time_of(frame_id: int) -> float:
    """t = frame_id / 30 exactly."""
    return frame_id / FPS


def ensure_dirs() -> None:
    for p in (RUNTIME_ROOT, EV_ROOT):
        os.makedirs(p, exist_ok=True)

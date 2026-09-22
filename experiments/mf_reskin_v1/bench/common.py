"""MF-V1-BENCH - shared paths, ffmpeg/ffprobe wrappers, evidence transcript.

CPU only. No model, no network, no GPU. ffmpeg/ffprobe + stdlib + numpy/Pillow.
Every external command is recorded (argv/cwd/exit/duration) into the run ledger,
which the driver flushes to <BENCH_EV>/raw/cmd_transcript.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

WAVE_EV = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-v1/20260917T110554Z")
BENCH_EV = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-model-upgrade-20260922/20260922T0345Z/BENCH")
RUNTIME = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench")
WT_BENCH = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")

GOLDEN = WAVE_EV / "GOLDEN"
GOLDEN_FIXTURE = GOLDEN / "GOLDEN_FIXTURE.json"
PROP_CLIPS = WAVE_EV / "PROPAGATE/media/clips"
PROP_ASSEMBLED = WAVE_EV / "PROPAGATE/media/assembled"
PROP_ASSEMBLED_MP4 = PROP_ASSEMBLED / "propagate_assembled_28s.mp4"
COMFY_CALIB_BOOK = WAVE_EV / "COMFY/runs/reskin_calibration/BOOK"

# Source film: READ-ONLY. Both copies sha256 5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2
REF_FILM = Path("C:/Users/Admin/MotionForge2D/projects/2dc14177a212/"
                "T\u1ea1i_sao_th\u1eadt_t\u1ec7_khi_\u0110\u1ee8NG_T\u00caN_H\u1ed9_c\u00f4ng_ty_.mp4")

# Frozen fixture timeline contract (GOLDEN_FIXTURE.json source_lock.timeline_definition)
FPS = 30
TIMEBASE_DEN = 15360
TICKS_PER_FRAME = 512          # pts = frame_id * 512,  t = frame_id / 30
FIXTURE_FREEZE_SHA = "2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684"
REF_FILM_SHA = "5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2"
REF_FILM_BYTES = 36971916

LEDGER: list = []


def ensure(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def write_json(path, obj) -> Path:
    path = Path(path)
    ensure(path.parent)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def run(argv, cwd=None, expect=(0,), label=None):
    """Run a command, record argv/cwd/exit/duration, return (rc, stdout, stderr)."""
    t0 = time.time()
    proc = subprocess.run([str(a) for a in argv],
                          cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dt = time.time() - t0
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    LEDGER.append({
        "label": label,
        "argv": [str(a) for a in argv],
        "cwd": str(cwd or Path.cwd()),
        "exit_code": proc.returncode,
        "duration_s": round(dt, 3),
        "ok": proc.returncode in expect,
        "stdout_bytes": len(proc.stdout),
        "stderr_bytes": len(proc.stderr),
        "stderr_tail": "" if proc.returncode in expect else err[-600:],
    })
    return proc.returncode, out, err


def run_bytes(argv, cwd=None, expect=(0,), label=None) -> bytes:
    t0 = time.time()
    proc = subprocess.run([str(a) for a in argv],
                          cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dt = time.time() - t0
    LEDGER.append({
        "label": label,
        "argv": [str(a) for a in argv],
        "cwd": str(cwd or Path.cwd()),
        "exit_code": proc.returncode,
        "duration_s": round(dt, 3),
        "ok": proc.returncode in expect,
        "stdout_bytes": len(proc.stdout),
        "stderr_bytes": len(proc.stderr),
        "stderr_tail": "" if proc.returncode in expect else proc.stderr.decode("utf-8", "replace")[-600:],
    })
    return proc.stdout


def flush_ledger(path=None) -> Path:
    """APPEND this run's ledger to the command transcript.

    Measured defect this fixes: the previous version opened the transcript with "w",
    so a later harness invocation silently destroyed an earlier run's evidence. The
    wave-1 run wrote 305 rows; a wave-2 `--steps candidate` run replaced the whole
    file with 20 rows and the wave-1 bytes were not recoverable from disk. Every run
    now starts with a run header and no run can truncate another run's transcript.
    """
    path = Path(path or (BENCH_EV / "raw" / "cmd_transcript.jsonl"))
    ensure(path.parent)
    with open(path, "a", encoding="utf-8") as f:
        header = {"run": "start", "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "cwd": str(Path.cwd()), "commands": len(LEDGER)}
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for row in LEDGER:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def load_fixture() -> dict:
    return json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))


def fixture_freeze_hash(fixture: dict) -> str:
    """Recompute the frozen-fixture hash: sha256 of canonical JSON with 'freeze' removed."""
    body = {k: v for k, v in fixture.items() if k != "freeze"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def windows(fixture: dict) -> list:
    return fixture["windows"]

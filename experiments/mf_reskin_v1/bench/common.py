"""MF-V1-BENCH - shared paths, ffmpeg/ffprobe wrappers, evidence transcript.

CPU only. No model, no network, no GPU. ffmpeg/ffprobe + stdlib + numpy/Pillow.
Every external command is recorded (argv/cwd/exit/duration) into a run ledger that is
written to that run's ledger path, appended at command boundaries, so an exception or a
process kill cannot lose an envelope of a command that already finished (F10). The ledger that
lives inside the submitted packet is an EXPLICIT destination (EVIDENCE_LEDGER); the fallback is
the run scratch root, so "no explicit path" can never mean "append into submitted evidence"
(F10 c3). The wave-1/2 evidence root BENCH_EV is frozen and read-only for this round.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

WAVE_EV = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-v1/20260917T110554Z")
BENCH_EV = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-model-upgrade-20260922/20260922T0345Z/BENCH")
RUNTIME = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench")
WT_BENCH = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")

# F10 correction round: the wave-1/2 evidence root above is FROZEN and read-only for this
# round. New evidence (the command ledger + this round's raw JSONs) is written under the
# correction packet's own BENCH root, and all scratch goes to WORK inside that root.
BENCH_EV_FROZEN = BENCH_EV
BENCH_EV_NEW = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                    "mf-reskin-correction-20260922/20260922T0955Z/BENCH")
WORK = Path(os.environ.get("MF_BENCH_WORK", str(RUNTIME)))

# F10 isolation (correction c3). The ledger that belongs to the SUBMITTED packet is a named
# destination only. It used to be the fallback of ledger_path(), so any caller that forgot to
# name a path appended its rows into submitted evidence - the reviewer's verification run wrote
# 10,721 bytes / 25 rows of run 20260922T235825-1290fc into the frozen packet ledger that way.
EVIDENCE_LEDGER = BENCH_EV_NEW / "raw" / "cmd_transcript.jsonl"
# The fallback is the SCRATCH root, never an evidence root (WORK honours MF_BENCH_WORK).
EVIDENCE_ROOTS = (BENCH_EV_NEW, BENCH_EV_FROZEN)


def in_evidence_root(path) -> bool:
    """True when `path` lives inside a submitted/frozen evidence root.

    Such a ledger is real evidence: it may only be written when a caller names it explicitly.
    Compared as normalised absolute strings, so it is safe to call on a path that does not
    exist yet and on the two roots that bracket the corpus (packet + frozen wave-1/2).
    """
    def norm(p):
        return str(Path(p).resolve()).replace("\\", "/").lower().rstrip("/")
    p = norm(path)
    return any(p == r or p.startswith(r + "/") for r in map(norm, EVIDENCE_ROOTS))


def default_ledger() -> Path:
    """The ledger used when no caller names one: <scratch>/cmd_transcript.jsonl.

    Resolved at CALL time from MF_BENCH_WORK (the old module-level default was computed at
    import, so MF_BENCH_WORK redirected scratch but not the ledger). It fails closed when the
    scratch root itself points into an evidence root, because appending to submitted bytes
    must always require an explicit destination.
    """
    p = Path(os.environ.get("MF_BENCH_WORK", str(RUNTIME))) / "cmd_transcript.jsonl"
    if in_evidence_root(p):
        raise RuntimeError(
            "refusing to default the command ledger into an evidence root (%s): name a path "
            "explicitly (EVIDENCE_LEDGER) or point MF_BENCH_WORK/MF_BENCH_LEDGER at scratch" % p)
    return p

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

# --------------------------------------------------------------------------- #
# F10 - durable command ledger (write-ahead log of command events)
# --------------------------------------------------------------------------- #
# Wave-1 defect (recorded as OPEN_WITH_ACCEPTED_LOSS): rows lived only in memory and were
# written by a single flush at the end of the run, and flush_ledger() opened the transcript
# with mode "w". So (a) an exception before the final flush lost every envelope of the
# commands that had already completed, (b) flushing twice re-wrote the same buffer (2 rows
# became 4, 2 copies of the same command), and (c) the next run truncated the previous run's
# transcript (306 rows -> 20 rows; the wave-1 bytes are not recoverable).
#
# The ledger is now appended (mode "a") at command *boundaries*:
#   {"run_id","row_id","cmd_id","phase":"start","label","argv","cwd","started_at"}
#   {"run_id","row_id","cmd_id","phase":"terminal","exit_code","duration_s","ok",...}
# A reader joins on (run_id, cmd_id). A start row with no terminal row is reported as
# `incomplete` with exit_code=None and duration_s=None - an interrupted command never gets
# an invented exit code or an invented duration. flush_ledger() only appends rows whose
# row_id is not on disk yet, so a repeated flush is a no-op and cannot duplicate a command.
#
# MF_BENCH_LEDGER_MODE=memory keeps rows in memory and writes them at flush time only -
# that is the pre-fix write path, kept as an explicit test seam so the durability and
# idempotence tests can run their negative control against the exact behaviour they fix.
RUN_ID = time.strftime("%Y%m%dT%H%M%S", time.localtime()) + "-" + uuid.uuid4().hex[:6]
LEDGER_MODE = os.environ.get("MF_BENCH_LEDGER_MODE", "durable")
_LEDGER_FILE = None          # set by set_ledger_path(); the default is the scratch root
_PERSISTED: set = set()      # (path, row_id) already on disk
_HEADERS: set = set()        # (path, run_id) already stamped
_CMD_SEQ = itertools.count(1)


def ledger_path(path=None) -> Path:
    """Append-only command ledger for this run.

    Precedence: explicit argument > set_ledger_path() > MF_BENCH_LEDGER > default_ledger().
    Not one of those fallbacks can reach the submitted-packet ledger (EVIDENCE_LEDGER): with
    nothing named the path is the scratch root, and a scratch root inside an evidence root
    fails closed instead of appending to submitted bytes (F10 c3).
    """
    if path:
        return Path(path)
    if _LEDGER_FILE:
        return Path(_LEDGER_FILE)
    env = os.environ.get("MF_BENCH_LEDGER")
    if env:
        return Path(env)
    return default_ledger()


def set_ledger_path(path):
    """Point this process at another ledger (tests use a tmp_path); None restores the scratch
    default - the submitted-packet ledger is never a default."""
    global _LEDGER_FILE
    _LEDGER_FILE = Path(path) if path else None
    return _LEDGER_FILE


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _stamp_header(path):
    """One per-run header per (file, run). Never rewrites the file."""
    key = (str(path), RUN_ID)
    if key in _HEADERS:
        return False
    ensure(Path(path).parent)
    header = {"run": "start", "run_id": RUN_ID, "when": _now(),
              "cwd": str(Path.cwd()), "commands": len(LEDGER)}
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
    _HEADERS.add(key)
    return True


def _emit(path, row):
    """Append one row at most once. Opens the ledger with mode "a" only - never truncates.

    Written with LF line endings on purpose: a JSONL evidence ledger is compared by byte
    prefix across runs, so it must not depend on the platform's newline translation.
    """
    key = (str(path), row.get("row_id") or hashlib.sha256(
        json.dumps(row, sort_keys=True, default=str).encode("utf-8")).hexdigest())
    if key in _PERSISTED:
        return False
    _stamp_header(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _PERSISTED.add(key)
    return True


def _record(path, **fields):
    """Record one command event. Durable immediately unless the memory seam is active."""
    row = {"run_id": RUN_ID, "row_id": uuid.uuid4().hex, "when": _now()}
    row.update(fields)
    LEDGER.append(row)
    if LEDGER_MODE != "memory":
        _emit(path, row)
    return row


def begin_command(argv, cwd=None, label=None) -> str:
    """Command START boundary - persisted before the command runs."""
    cmd_id = "c%04d-%s" % (next(_CMD_SEQ), uuid.uuid4().hex[:6])
    _record(ledger_path(), cmd_id=cmd_id, phase="start", label=label,
            argv=[str(a) for a in argv], cwd=str(cwd or Path.cwd()), started_at=_now())
    return cmd_id


def end_command(cmd_id, exit_code, duration_s, expect, stdout_bytes, stderr_bytes,
                stderr_tail="") -> dict:
    """Command TERMINAL boundary - persisted as soon as the command finished."""
    return _record(ledger_path(), cmd_id=cmd_id, phase="terminal", exit_code=exit_code,
                   duration_s=round(duration_s, 3), ok=exit_code in expect,
                   stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes,
                   stderr_tail=stderr_tail)


def command_count() -> int:
    """Commands traced in this process (rows are WAL events, so len(LEDGER) is not it)."""
    return len({r["cmd_id"] for r in LEDGER if r.get("cmd_id")})


def _command_key(r):
    """Join key: real (run_id, cmd_id) for WAL rows; content key for legacy/manual rows."""
    if r.get("run_id") and r.get("cmd_id"):
        return "%s/%s" % (r["run_id"], r["cmd_id"])
    body = {k: v for k, v in r.items() if k != "when"}
    return "legacy-" + hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def read_ledger(path=None) -> dict:
    """Join ledger rows by (run_id, cmd_id) into per-command records.

    status == "complete" only when a terminal row carries a real exit code. A command with
    no terminal row is "incomplete" with exit_code=None and duration_s=None: the reader
    never invents them. `duplicates` lists any (run_id, cmd_id, phase) seen more than once -
    exactly the shape the wave-1 repeated flush produced (2 rows -> 4, 2 copies of the same
    command) - and must stay empty for a healthy ledger.
    """
    path = Path(path or ledger_path())
    rows, malformed = [], []
    if path.exists():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                malformed.append({"line": i + 1, "raw": line[:200]})
    commands = [r for r in rows if r.get("run") != "start"]
    headers = [r for r in rows if r.get("run") == "start"]
    counts = {}
    for r in commands:
        k = (_command_key(r), r.get("phase"))
        counts[k] = counts.get(k, 0) + 1
    duplicates = [{"key": k[0], "phase": k[1], "copies": n}
                  for k, n in counts.items() if n > 1]
    hcounts = {}
    for h in headers:
        k = hashlib.sha256(json.dumps({x: y for x, y in h.items() if x != "when"},
                                      sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        hcounts[k] = hcounts.get(k, 0) + 1
    records = []
    for key in dict.fromkeys(_command_key(r) for r in commands):
        group = [r for r in commands if _command_key(r) == key]
        start = [r for r in group if r.get("phase") == "start"]
        term = [r for r in group if r.get("phase") == "terminal" and r.get("exit_code") is not None]
        inc = [r for r in group if r.get("phase") == "incomplete"]
        anchor = (start or group)[0]
        rec = {"key": key, "run_id": anchor.get("run_id"), "cmd_id": anchor.get("cmd_id"),
               "label": anchor.get("label"), "argv": anchor.get("argv"),
               "has_start_row": bool(start)}
        if term:
            rec.update(status="complete", exit_code=term[0]["exit_code"],
                       duration_s=term[0].get("duration_s"), ok=term[0].get("ok"))
        else:
            rec.update(status="incomplete", exit_code=None, duration_s=None,
                       declared_incomplete=bool(inc))
        records.append(rec)
    return {"path": str(path), "bytes": path.stat().st_size if path.exists() else 0,
            "rows": rows, "row_count": len(rows), "headers": len(headers),
            "duplicate_headers": sorted(k for k, n in hcounts.items() if n > 1),
            "commands": commands, "records": records, "duplicates": duplicates,
            "malformed": malformed,
            "run_ids": sorted({r.get("run_id") for r in rows if r.get("run_id")})}


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
    """Run a command; record argv/cwd/exit/duration at BOTH boundaries, durably.

    The start row is on disk before the command runs and the terminal row as soon as it
    finishes, so an exception later in the run cannot lose an envelope for a command that
    already completed. If the command never finishes (killed, hangs), the start row stays
    and the reader reports it as `incomplete` - no exit code or duration is invented.
    """
    argv = [str(a) for a in argv]
    cmd_id = begin_command(argv, cwd, label)
    t0 = time.time()
    proc = subprocess.run(argv,
                          cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dt = time.time() - t0
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    end_command(cmd_id, proc.returncode, dt, expect, len(proc.stdout), len(proc.stderr),
                "" if proc.returncode in expect else err[-600:])
    return proc.returncode, out, err


def run_bytes(argv, cwd=None, expect=(0,), label=None) -> bytes:
    argv = [str(a) for a in argv]
    cmd_id = begin_command(argv, cwd, label)
    t0 = time.time()
    proc = subprocess.run(argv,
                          cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dt = time.time() - t0
    end_command(cmd_id, proc.returncode, dt, expect, len(proc.stdout), len(proc.stderr),
                "" if proc.returncode in expect else proc.stderr.decode("utf-8", "replace")[-600:])
    return proc.stdout


def flush_ledger(path=None) -> Path:
    """Persist every ledger row that is not on disk yet. Idempotent by construction.

    Measured defects this fixes:
      * the previous version opened the transcript with "w", so a later harness invocation
        silently destroyed an earlier run's evidence (wave-1: 306 rows -> 20 rows, wave-1
        bytes unrecoverable). The ledger is now appended with mode "a" only, and the
        earlier rows of an existing ledger survive byte-for-byte.
      * flushing twice re-wrote the whole in-memory buffer, so 2 rows became 4 with 2
        copies of the same command. Every row carries a row_id and is written at most once
        per (path, row_id), so a repeated flush appends nothing at all.
    A command that started but never reached its terminal boundary is persisted exactly once
    as phase `incomplete` with exit_code=None and duration_s=None - never an invented exit
    code and never an invented duration.
    """
    path = ledger_path(path)
    ensure(path.parent)
    for row in list(LEDGER):
        _emit(path, row)
    closed = {r["cmd_id"] for r in LEDGER if r.get("phase") in ("terminal", "incomplete")}
    for row in list(LEDGER):
        if row.get("phase") == "start" and row.get("cmd_id") not in closed:
            _record(path, cmd_id=row["cmd_id"], phase="incomplete", exit_code=None,
                    duration_s=None, label=row.get("label"),
                    reason="command started, no terminal record")
    for row in list(LEDGER):
        _emit(path, row)
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

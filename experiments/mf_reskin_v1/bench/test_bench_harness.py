"""MF-V1-BENCH - regression tests for harness invariants (CPU only, hermetic).

No network, no GPU, no model, no write outside `tmp_path`. Each test names the measured
defect or gate rule it locks down, and each gate-row test also asserts the opposite
verdict on the corrected input so it cannot pass vacuously.

Run:  python -m pytest experiments/mf_reskin_v1/bench -q --cache-clear --basetemp=C:/pt_bench
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assertions as A          # noqa: E402
import common as C              # noqa: E402
import compare as CMP           # noqa: E402
import wave2_eval_book as W     # noqa: E402
import wave2_review_bundle as RB  # noqa: E402

SPEC = {"expected_frames": 12, "pts_duration": 0.4, "min_change_mae": 2.0,
        "max_identical_run": 2, "pairing_radius": 5, "pairing_margin_floor": 0.01,
        "video": {"codec": "h264", "width": 64, "height": 36, "pix_fmt": "yuv420p"},
        "audio_optional": True, "window_start_frame": 0, "window_frame_count": 12}


def make_clip(path, w=64, h=36, n=12, color="gray"):
    """A tiny deterministic CFR h264 clip, encoded with ffmpeg (the harness's own tool)."""
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=%s:s=%dx%d:r=30:d=%.3f" % (color, w, h, n / 30.0),
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


# --------------------------------------------------------------------------- #
# 1. command transcript must never destroy a previous run's evidence
# --------------------------------------------------------------------------- #

def test_flush_ledger_appends_and_never_truncates(tmp_path):
    """Defect locked: flush_ledger opened the transcript with "w" and a later run
    replaced an earlier run's 305 rows with 20. Appends only, one header per run."""
    t = tmp_path / "cmd_transcript.jsonl"
    C.LEDGER.clear()
    C.LEDGER.append({"label": "run1-a", "argv": ["ffmpeg"], "exit_code": 0})
    C.flush_ledger(t)
    first = t.read_text(encoding="utf-8").splitlines()
    C.LEDGER.clear()
    C.LEDGER.append({"label": "run2-a", "argv": ["ffprobe"], "exit_code": 0})
    C.flush_ledger(t)
    rows = [json.loads(x) for x in t.read_text(encoding="utf-8").splitlines()]
    labels = [r.get("label") for r in rows]
    # one per-run header for the whole run, then one row per flush: 2 -> 3 rows.
    # (The pre-fix version added a header on every flush and re-wrote the whole buffer.)
    assert len(first) == 2 and len(rows) == 3, "each run adds its header plus its rows"
    assert "run1-a" in labels and "run2-a" in labels, "run 1 survived run 2"
    assert labels.count("run1-a") == 1 and labels.count("run2-a") == 1
    # prefix preservation: the earlier run's bytes are untouched by the later run
    assert t.read_bytes().startswith(first[0].encode("utf-8") + b"\n")
    assert json.loads(first[1])["label"] == "run1-a"
    C.LEDGER.clear()


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path, monkeypatch):
    """F10 c3 - every test gets its own ledger path BEFORE its first command, and the module
    state is reset on teardown AS WELL AS on setup.

    The pre-fix fixture reset only on teardown (`C.set_ledger_path(None)`), so every media test
    that followed a test which had named a path fell back to the module default - and that
    default WAS the submitted packet ledger. The reviewer's full-suite verification run appended
    10,721 bytes / 25 rows of run 20260922T235825-1290fc into submitted evidence that way.
    Resetting on setup too means no ordering can leak a path in, and exporting MF_BENCH_LEDGER +
    MF_BENCH_WORK means a subprocess spawned by a test inherits an explicit per-test path
    instead of a process-global default.
    """
    ledger = tmp_path / "cmd_transcript.jsonl"
    C.LEDGER.clear()
    C.set_ledger_path(ledger)
    monkeypatch.setenv("MF_BENCH_LEDGER", str(ledger))
    monkeypatch.setenv("MF_BENCH_WORK", str(tmp_path))
    yield
    C.LEDGER.clear()
    C.set_ledger_path(None)


def test_flush_ledger_header_marks_the_run(tmp_path):
    t = tmp_path / "cmd_transcript.jsonl"
    C.LEDGER.clear()
    C.LEDGER.append({"label": "x", "argv": ["ffmpeg"], "exit_code": 0})
    C.flush_ledger(t)
    head = json.loads(t.read_text(encoding="utf-8").splitlines()[0])
    assert head["run"] == "start" and head["commands"] == 1 and "when" in head and "cwd" in head
    C.LEDGER.clear()


# --------------------------------------------------------------------------- #
# 1b. F10 - the ledger must survive an exception and a process kill, and flushing
#     twice must not duplicate a row. Each test runs its own negative control: the
#     same check against MF_BENCH_LEDGER_MODE=memory, which is the pre-fix write
#     path (rows only in memory, written by a final flush), and the same duplicate
#     detector against the reviewer's real double-flushed probe ledger.
# --------------------------------------------------------------------------- #

BENCH_DIR = Path(__file__).resolve().parent

# Child process: one command that completes, then either dies by exception before any
# flush, or starts a command and hangs until the parent kills it.
CHILD_LEDGER = '''
import pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import common as C
C.set_ledger_path(pathlib.Path(sys.argv[2]))
C.run([sys.executable, "-B", "-c", "print('completed before interruption')"], label="completed")
cmd = C.begin_command([sys.executable, "-B", "-c", "print('never returns')"], label="interrupted")
print("BEGIN_WRITTEN", cmd, flush=True)
if sys.argv[3] == "raise":
    raise SystemExit(3)
time.sleep(60)
C.end_command(cmd, 0, 0.0, (0,), 0, 0)
'''


def _child(tmp_path, ledger, action, mode):
    """Spawn the child with MF_BENCH_LEDGER_MODE=durable (fixed) or memory (pre-fix)."""
    script = tmp_path / ("child_%s.py" % action)
    script.write_text(CHILD_LEDGER, encoding="utf-8")
    env = dict(os.environ, MF_BENCH_LEDGER_MODE=mode)
    return subprocess.Popen([sys.executable, "-B", str(script), str(BENCH_DIR), str(ledger), action],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def test_ledger_survives_exception_and_process_kill(tmp_path):
    """F10 rows 1-4: durable at command boundaries, identity per record, prefix preserved,
    an interrupted start reported `incomplete` with nothing invented.

    Negative control (executed, not argued): the same child with
    MF_BENCH_LEDGER_MODE=memory reproduces the pre-fix write path, so nothing of it is on
    disk after the exception. The durability check must therefore report an empty ledger
    there - proof the check can fail, and not a verdict produced by the fix itself.
    """
    ledger = tmp_path / "cmd_transcript.jsonl"

    # (a) the run dies by exception after a command completed and one never returned
    p = _child(tmp_path, ledger, "raise", "durable")
    _, err = p.communicate(timeout=120)
    assert p.returncode == 3, "the child must really die by exception: %s" % err[-400:]
    d = C.read_ledger(ledger)
    assert [r["status"] for r in d["records"]] == ["complete", "incomplete"], d["records"]
    done, lost = d["records"]
    assert done["label"] == "completed" and done["exit_code"] == 0 and done["duration_s"] > 0, \
        "a command that finished before the exception keeps its exit code and duration"
    assert lost["exit_code"] is None and lost["duration_s"] is None, \
        "an interrupted command must never get an invented exit code or duration"
    assert all(r.get("run_id") for r in d["rows"]), "every row must join to a run"
    assert all(r.get("cmd_id") for r in d["commands"]), "every command row needs a command id"
    assert len(d["run_ids"]) == 1 and d["headers"] == 1, "exactly one run header"
    assert d["duplicates"] == [] and d["malformed"] == []
    # the envelope of the completed command is on disk although the child never flushed
    assert any(r["status"] == "complete" and r["label"] == "completed" for r in d["records"])
    prefix = ledger.read_bytes()

    # (b) a second child is killed while a command is in flight
    n_incomplete = sum(1 for r in d["records"] if r["status"] == "incomplete")
    p2 = _child(tmp_path, ledger, "kill", "durable")
    deadline = time.time() + 60
    while len([r for r in C.read_ledger(ledger)["records"] if r["status"] == "incomplete"]) <= n_incomplete:
        if p2.poll() is not None:
            pytest.fail("child exited before its start row became durable: %s" % p2.stderr.read()[-400:])
        if time.time() > deadline:
            pytest.fail("the start row never became durable, so there was nothing to kill")
        time.sleep(0.1)
    before_kill = ledger.read_bytes()
    p2.kill()
    p2.communicate(timeout=60)
    after = C.read_ledger(ledger)
    assert after["duplicates"] == [], "no row may be duplicated by a kill or a flush"
    inc = [r for r in after["records"] if r["status"] == "incomplete"]
    assert len(inc) == n_incomplete + 1, after["records"]
    assert all(r["exit_code"] is None and r["duration_s"] is None for r in inc), \
        "a killed command is incomplete: exit code and duration stay null"
    assert ledger.read_bytes() == before_kill, "the kill changed nothing already on disk"
    assert ledger.read_bytes().startswith(prefix), \
        "rows written by the earlier run survive the later run byte-for-byte"

    # (c) negative control: on the pre-fix write path nothing survives the exception
    legacy = tmp_path / "legacy.jsonl"
    p3 = _child(tmp_path, legacy, "raise", "memory")
    p3.communicate(timeout=120)
    assert p3.returncode == 3
    assert C.read_ledger(legacy)["records"] == [], \
        "control: with rows kept in memory (pre-fix path) the same check reports NOT durable"
    assert not legacy.exists() or legacy.read_bytes() == b""


def test_flush_is_idempotent(tmp_path):
    """F10 rows 5-6: a repeated flush must not duplicate a row, and a later run must not
    truncate what an earlier run already wrote.

    Negative control (executed): the duplicate detector must FIRE on the shape the wave-1
    harness really produced - the reviewer's probe ledger holds 6 rows with 2 copies of the
    same command (rows_after_two_flushes 4, same_command_copies 2). An empty `duplicates`
    list above is therefore a measurement, not an artefact of a blind detector.
    """
    ledger = tmp_path / "cmd_transcript.jsonl"
    C.set_ledger_path(ledger)
    C.LEDGER.clear()
    rc, _, _ = C.run([sys.executable, "-B", "-c", "print('probe')"], label="probe")
    assert rc == 0
    n_rows = len(ledger.read_text(encoding="utf-8").splitlines())
    assert n_rows == 3, "header + start row + terminal row"
    for _ in range(3):
        C.flush_ledger()
    once = C.read_ledger()
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == n_rows, \
        "flush must be a no-op on rows that are already on disk"
    assert once["duplicates"] == [] and len(once["records"]) == 1
    assert once["records"][0]["status"] == "complete" and once["records"][0]["exit_code"] == 0
    assert [r.get("phase") for r in once["commands"]] == ["start", "terminal"]

    # a row that is only in memory is appended exactly once, however often flush runs
    C.LEDGER.append({"label": "manual", "argv": ["x"], "exit_code": 0})
    C.flush_ledger()
    a = ledger.read_text(encoding="utf-8").splitlines()
    C.flush_ledger()
    C.flush_ledger()
    b = ledger.read_text(encoding="utf-8").splitlines()
    assert a == b, "a repeated flush appends nothing"
    assert sum(1 for x in b if json.loads(x).get("label") == "manual") == 1, \
        "the same command must not be copied into the ledger twice"

    # a started-but-unfinished command is declared incomplete exactly once, nothing invented
    cid = C.begin_command([sys.executable, "-B", "-c", "print('never')"], label="unfinished")
    C.flush_ledger()
    C.flush_ledger()
    d = C.read_ledger()
    inc_rows = [r for r in d["commands"] if r.get("cmd_id") == cid and r.get("phase") == "incomplete"]
    rec = [r for r in d["records"] if r["cmd_id"] == cid]
    assert len(inc_rows) == 1, "exactly one incomplete row, however often flush ran"
    assert rec and rec[0]["status"] == "incomplete"
    assert rec[0]["exit_code"] is None and rec[0]["duration_s"] is None, \
        "the incomplete row must not invent an exit code or a duration"
    assert d["duplicates"] == [] and d["malformed"] == []
    C.set_ledger_path(None)

    # negative control 1: the real double-flushed probe ledger from the review
    probe = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                 "mf-upgrade-review-20260922/bench/probe/raw/cmd_transcript.jsonl")
    assert probe.exists(), "the reviewer's probe ledger must be readable for this control"
    pd = C.read_ledger(probe)
    assert pd["row_count"] == 6 and pd["duplicates"], "control: the twin rows must be detected"
    assert max(x["copies"] for x in pd["duplicates"]) == 2, pd["duplicates"]

    # negative control 2: any twice-written command is detected, on a hermetic copy
    crafted = tmp_path / "crafted.jsonl"
    body = ledger.read_text(encoding="utf-8").splitlines()
    crafted.write_text("\n".join(body + body[1:3]) + "\n", encoding="utf-8")
    assert C.read_ledger(crafted)["duplicates"], \
        "control: a twice-written command must be detected in the ledger"


# --------------------------------------------------------------------------- #
# 1c. F10 c3 - isolation: the SUBMITTED packet ledger must never be a default target.
#     The pre-fix fixture reset the path only on teardown, so each media test that followed
#     fell back to the module default - and that default was the packet ledger of the
#     correction round (review P2/F10: 10,721 bytes / 25 rows of run 20260922T235825-1290fc
#     landed in already-submitted evidence).
# --------------------------------------------------------------------------- #

PRE_FIX_COMMIT = "afa22c5"    # last commit whose common.py still defaulted to the packet ledger
PRE_FIX_COMMON_SHA = "340ebc247b3889e75c70bccba330542dcc9b5914d68832e8fd09d9137be4c868"
SUBMITTED_PACKET = "mf-reskin-correction-20260922/20260922T0955Z/BENCH"


def _evidence_snapshot():
    """Size + sha256 of the submitted packet ledger (read-only; None when it is absent)."""
    p = C.EVIDENCE_LEDGER
    if not p.exists():
        return None
    b = p.read_bytes()
    return {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}


def _no_ledger_named(monkeypatch):
    """Reproduce 'the caller named nothing': no argument, no override, no environment."""
    monkeypatch.delenv("MF_BENCH_LEDGER", raising=False)
    C.set_ledger_path(None)
    return C.ledger_path()


def test_default_ledger_never_targets_submitted_evidence(tmp_path, monkeypatch):
    """F10 c3: with nothing named, the ledger resolves into the run scratch root - never into
    the submitted packet and never into the frozen wave-1/2 evidence root.

    Executed here: (a) the resolution itself, (b) a real command written through that
    resolution, proving the rows land in scratch while the packet ledger's bytes do not move,
    (c) the fail-closed guard for a scratch root that has been pointed at an evidence root.
    """
    d = _no_ledger_named(monkeypatch)
    assert not C.in_evidence_root(d), "the default ledger resolved into an evidence root: %s" % d
    assert SUBMITTED_PACKET not in str(d).replace("\\", "/"), d
    assert str(d) != str(C.EVIDENCE_LEDGER), "the packet ledger must stay an explicit choice"
    assert str(d).replace("\\", "/").startswith(str(tmp_path).replace("\\", "/")), \
        "the fixture points MF_BENCH_WORK at the test scratch root, so the default lives there"

    before = _evidence_snapshot()
    rc, _, _ = C.run([sys.executable, "-B", "-c", "print('f10 default ledger')"],
                     label="f10-default-ledger")
    assert rc == 0
    assert d.exists() and len(d.read_text(encoding="utf-8").splitlines()) == 3, \
        "header + start + terminal row in the scratch ledger"
    assert _evidence_snapshot() == before, "nothing may be appended to the packet ledger"

    # fail-closed: a scratch root inside an evidence root must not become the default
    assert C.in_evidence_root(C.BENCH_EV_NEW / "raw" / "cmd_transcript.jsonl"), \
        "the guard must recognise the packet ledger as evidence"
    monkeypatch.setenv("MF_BENCH_WORK", str(C.BENCH_EV_NEW))
    monkeypatch.delenv("MF_BENCH_LEDGER", raising=False)
    C.set_ledger_path(None)
    with pytest.raises(RuntimeError) as ei:
        C.ledger_path()
    assert "evidence root" in str(ei.value) and "EVIDENCE_LEDGER" in str(ei.value), str(ei.value)


def _pre_fix_common_bytes():
    """The pinned PRE-FIX common.py, read from the git object (never rewritten)."""
    for rev in (PRE_FIX_COMMIT, "HEAD^"):
        p = subprocess.run(["git", "show", "%s:experiments/mf_reskin_v1/bench/common.py" % rev],
                           cwd=str(BENCH_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 0 and p.stdout:
            got = hashlib.sha256(p.stdout).hexdigest()
            assert got == PRE_FIX_COMMON_SHA, \
                "git %s:common.py is not the pinned pre-fix bytes: got %s" % (rev, got)
            return p.stdout
    pytest.fail("cannot read the pre-fix common.py from git (tried %s and HEAD^)" % PRE_FIX_COMMIT)


_PROBE = (
    "import pathlib, sys\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))\n"
    "import common as C\n"
    "def test_default_ledger_is_not_the_submitted_packet():\n"
    "    p = str(C.ledger_path()).replace(chr(92), '/')\n"
    "    assert %r not in p, 'default ledger resolves into the submitted packet: ' + p\n")


def _run_probe(tmp_path, name, common_bytes):
    """Run the same predicate against one version of common.py, with nothing named."""
    d = tmp_path / name
    d.mkdir()
    (d / "common.py").write_bytes(common_bytes)
    (d / "test_probe_default_ledger.py").write_text(_PROBE % SUBMITTED_PACKET, encoding="utf-8")
    env = dict(os.environ)
    env.pop("MF_BENCH_LEDGER", None)
    env.pop("MF_BENCH_WORK", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([sys.executable, "-m", "pytest", "test_probe_default_ledger.py", "-q",
                        "-p", "no:cacheprovider"],
                       cwd=str(d), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def test_default_ledger_negative_control_fails_against_pre_fix_bytes(tmp_path):
    """Negative control, executed: the predicate that PASSES on the fixed module must FAIL on
    the pinned pre-fix bytes (sha256 of the committed preimage), otherwise 'the default is not
    the packet ledger' would be a claim about a check that cannot fail."""
    rc_pre, out_pre = _run_probe(tmp_path, "pre_fix", _pre_fix_common_bytes())
    assert rc_pre != 0, "control: the pre-fix bytes must FAIL this predicate\n%s" % out_pre[-900:]
    assert "1 failed" in out_pre, out_pre[-900:]
    assert "submitted packet" in out_pre, "the failure must name the packet it wrote into"

    rc_fix, out_fix = _run_probe(tmp_path, "fixed", (BENCH_DIR / "common.py").read_bytes())
    assert rc_fix == 0, "the fixed module must PASS the same predicate\n%s" % out_fix[-900:]
    assert "1 passed" in out_fix, out_fix[-900:]


CHILD_NO_PATH = """
import sys
sys.path.insert(0, sys.argv[1])
import common as C
print("RESOLVED_LEDGER=%s" % C.ledger_path(), flush=True)
C.run([sys.executable, "-B", "-c", "print('child command')"], label="child-default-path")
"""


def test_subprocess_ledger_path_is_explicit(tmp_path):
    """F10 c3: a test that spawns a subprocess names the ledger path FOR THE CHILD (env/argv),
    and the child never reaches a process-global default that could be the packet ledger.

    Executed both ways: (a) the child inherits the fixture's explicit MF_BENCH_LEDGER and writes
    there and nowhere else; (b) with MF_BENCH_LEDGER removed the child still writes into the
    scratch root named by MF_BENCH_WORK - and the packet ledger is hashed around both runs, so
    'nowhere else' is measured, not asserted.
    """
    script = tmp_path / "child_no_path.py"
    script.write_text(CHILD_NO_PATH, encoding="utf-8")
    before = _evidence_snapshot()

    env = dict(os.environ)
    assert env.get("MF_BENCH_LEDGER"), "the fixture must export an explicit per-test ledger path"
    p = subprocess.run([sys.executable, "-B", str(script), str(BENCH_DIR)], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0, p.stderr[-600:]
    resolved = [x for x in p.stdout.splitlines() if x.startswith("RESOLVED_LEDGER=")][0].split("=", 1)[1]
    assert resolved.replace("\\", "/").startswith(str(tmp_path).replace("\\", "/")), resolved
    assert Path(resolved).exists()
    assert C.read_ledger(Path(resolved))["records"][0]["status"] == "complete"

    scratch = tmp_path / "child_scratch"
    env2 = dict(os.environ, MF_BENCH_WORK=str(scratch))
    env2.pop("MF_BENCH_LEDGER", None)
    p2 = subprocess.run([sys.executable, "-B", str(script), str(BENCH_DIR)], env=env2,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p2.returncode == 0, p2.stderr[-600:]
    r2 = [x for x in p2.stdout.splitlines() if x.startswith("RESOLVED_LEDGER=")][0].split("=", 1)[1]
    assert str(scratch).replace("\\", "/") in r2.replace("\\", "/"), r2
    assert SUBMITTED_PACKET not in r2.replace("\\", "/"), r2
    assert Path(r2).exists()
    assert _evidence_snapshot() == before, "a subprocess must not append to the packet ledger"


# --------------------------------------------------------------------------- #
# 2. ffmpeg exits 0 having written nothing -> the artifact guard must fire
# --------------------------------------------------------------------------- #

def test_require_nonempty_rejects_missing_and_zero_byte(tmp_path):
    """Defect locked: 4 grip strips were 0 bytes/absent after an exit-0 ffmpeg call."""
    missing = tmp_path / "absent.png"
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    full = tmp_path / "full.png"
    full.write_bytes(b"x" * 32)
    with pytest.raises(SystemExit):
        RB.require_nonempty(missing, "absent")
    with pytest.raises(SystemExit):
        RB.require_nonempty(empty, "zero-byte")
    assert RB.require_nonempty(full, "ok") == 32, "a real artifact is returned, not rejected"


# --------------------------------------------------------------------------- #
# 3. the geometry row: 8 extra rows must FAIL the codec/size contract
# --------------------------------------------------------------------------- #

def test_codec_contract_fails_on_geometry_mismatch_but_passes_when_declared(tmp_path):
    """Locks the wave-2 geometry FAIL: candidate 64x36 vs a 64x32 spec is a FAIL, and the
    same file is a PASS once the spec declares 36 - so the row is not vacuous."""
    clip = make_clip(tmp_path / "c.mp4", w=64, h=36)
    bad = dict(SPEC, video={"codec": "h264", "width": 64, "height": 32, "pix_fmt": "yuv420p"})
    assert A.a_video_codec_contract(clip, bad)["verdict"] == "FAIL"
    good = dict(SPEC, video={"codec": "h264", "width": 64, "height": 36, "pix_fmt": "yuv420p"})
    r = A.a_video_codec_contract(clip, good)
    assert r["verdict"] == "PASS" and r["measured"]["got"]["height"] == 36


def test_geometry_helper_reports_the_measured_delta():
    """Locks the numbers quoted in EVAL_BOOK_R4.md: +8 rows, ratio 1.022222, +2.2222 %."""
    g = W.geometry({"width": 640, "height": 368}, {"width": 640, "height": 360})
    assert (g["height_delta_px"], g["vertical_ratio_candidate_over_source"],
            g["pct_vertical_stretch_if_scaled_to_match"]) == (8, 1.022222, 2.2222)
    same = W.geometry({"width": 640, "height": 360}, {"width": 640, "height": 360})
    assert same["height_delta_px"] == 0, "no false mismatch when the geometry agrees"


# --------------------------------------------------------------------------- #
# 4. a non-discriminating measurement is UNMEASURED, never PASS (GATE_VOCAB rule 4)
# --------------------------------------------------------------------------- #

def test_flat_offset_curve_is_unmeasured_not_pass(tmp_path):
    """Two identical clips make the whole-clip offset curve flat: the pairing row must be
    UNMEASURED. This is the BOOK trap - a candidate near its source yields no alignment
    claim at all, and 'looks green' must not become PASS."""
    a = make_clip(tmp_path / "a.mp4")
    b = make_clip(tmp_path / "b.mp4")
    spec = dict(SPEC, source_clip=b)
    r = A.a_frame_pairing(a, spec)
    assert r["verdict"] == "UNMEASURED", r["measured"]
    assert "advantage" in r["measured"]["verdict_reason"], "the reason must name the advantage"
    assert "spread" in r["measured"]["verdict_reason"], "and the curve spread as a separate fact"
    assert r["measured"]["advantage_of_offset0"] == 0.0


def test_frame_pairing_message_is_self_consistent(tmp_path):
    """Defect locked: the UNMEASURED reason compared the curve SPREAD against the
    advantage floor and printed 'spread 0.0202 < floor 0.01'. Two identical clips give
    spread 0.0, so the old wording printed the self-contradicting 'spread 0.0 < floor 0.01'."""
    a = make_clip(tmp_path / "a.mp4")
    b = make_clip(tmp_path / "b.mp4")
    m = A.a_frame_pairing(a, dict(SPEC, source_clip=b))["measured"]
    why = m["verdict_reason"]
    assert not re.search(r"spread\s+[\d.]+\s*<\s*floor", why), "spread must not be compared to the advantage floor"
    assert "advantage of offset 0" in why and "below the floor" in why and "curve spread" in why
    assert str(m["margin_floor"]) in why, "the floor it compares against must appear"
    assert str(m["offset_curve_spread"]) in why, "the spread must still be recorded, as its own fact"


# --------------------------------------------------------------------------- #
# 5. a copy of the source must FAIL not_source_copy (CHECKLIST row 5 rule)
# --------------------------------------------------------------------------- #

def test_source_copy_fails_not_source_copy(tmp_path):
    src = make_clip(tmp_path / "src.mp4")
    same = make_clip(tmp_path / "same.mp4")
    r = A.a_not_source_copy(same, dict(SPEC, source_clip=src))
    assert r["verdict"] == "FAIL" and r["measured"]["mae_median"] == 0.0
    changed = make_clip(tmp_path / "changed.mp4", color="white")
    assert A.a_not_source_copy(changed, dict(SPEC, source_clip=src))["verdict"] == "PASS", \
        "the row must pass on content that really differs"


def test_delta_facts_is_zero_only_for_identical_input():
    a = np.zeros((3, 8, 8), dtype=np.uint8)
    d = CMP.delta_facts(a, a.copy())
    assert d["measured"] and d["mae_median"] == 0.0 and d["identical_frames"] == 3
    d2 = CMP.delta_facts(np.full((3, 8, 8), 10, dtype=np.uint8), a)
    assert d2["mae_median"] == 10.0 and d2["identical_frames"] == 0
# --------------------------------------------------------------------------- #
# reporting layer - correction round C (rows B2/B3)
# The rules here were each a real reporting defect (Codex R11), not a theory:
# geometry belongs to ONE sha, wall/wait/server/load are four measurements,
# generated != accepted seconds, G/I/V are separate from semantic fail/notmeasured,
# and a technical PASS is never a visual PASS.
#
# `run_dryrun` is deliberately NOT imported at module scope: it calls
# C.set_ledger_path(<submitted packet ledger>) at import, and set_ledger_path() outranks
# MF_BENCH_LEDGER, so importing it here could re-open the F10 leak. The pin test parses
# SPEC_BASE out of the source instead.
# --------------------------------------------------------------------------- #

import ast

import reporting as R


def _spec_base_from_source():
    src = (BENCH_DIR / "run_dryrun.py").read_text(encoding="utf-8")
    m = re.search(r"^SPEC_BASE = (\{)", src, re.M)
    assert m, "SPEC_BASE not found in run_dryrun.py"
    i, depth = m.start(1), 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return ast.literal_eval(src[i:j + 1])
    raise AssertionError("unterminated SPEC_BASE")


def test_geometry_is_bound_to_one_sha_and_never_shared_across_artifacts():
    raw = R.identity("raw_render", "raw.mp4", "raw_render", "aa" * 32, 10, 640, 368)
    crop = R.identity("cropped", "clip.mp4", "cropped_export", "bb" * 32, 10, 640, 360)
    t = R.identity_table([raw, crop])
    assert t["all_geometry_bound"] is True
    assert raw["geometry_statement"] != crop["geometry_statement"], (
        "640x368 (raw) and 640x360 (cropped) must not share a geometry statement")
    assert raw["sha256"] in raw["geometry_statement"]
    assert t["distinct_shas"] == ["aa" * 32, "bb" * 32]
    assert t["shas_with_several_roles"] == {}


def test_geometry_without_a_sha_is_a_violation():
    bad = R.identity("unbound", "z.mp4", "raw_render", None, None, 640, 368)
    chk = R.self_check(identity_block=R.identity_table([bad]))
    assert chk["clean"] is False and any("without a sha" in v for v in chk["violations"])


def test_timings_are_four_fields_with_sources_and_never_one_number():
    t = R.split_timings(wall_s=164.673, wait_s=163.734, server_s=162.14, load_s=25.82,
                        sources={"wall_s": "run_record.json:wall_s",
                                 "wait_s": "run_record.json:result.timing.wait_s",
                                 "server_s": "server log: Prompt executed",
                                 "load_s": "M1_REPORT: cold load"})
    assert t["collapsed_into_one_number"] is False
    assert t["fields"]["wall_s"]["value"] == 164.673
    assert t["fields"]["wait_s"]["value"] == 163.734
    assert t["fields"]["wait_s"]["value"] != t["fields"]["wall_s"]["value"], (
        "the packet's wait=164.673 was the wall - the two are different measurements")
    assert t["sources_complete"] is True and R.self_check(timings_block=t)["clean"] is True
    bad = R.split_timings(wall_s=1.0, reasons={"wait_s": "not measured"})
    assert bad["fields"]["wait_s"]["value"] is None, "an unmeasured field is never filled in"
    assert R.self_check(timings_block=bad)["clean"] is False


def test_cost_per_accepted_second_is_undefined_when_accepted_is_zero():
    s = R.seconds_split(generated_seconds=4.0, accepted_seconds=0, wall_s=164.673)
    assert s["cost_per_accepted_second"] == "undefined (accepted_seconds = 0)"
    assert isinstance(s["cost_per_accepted_second"], str)
    assert s["cost_undefined"] is True
    assert "164.673" in (s["cost_arithmetic"] or "")
    assert R.self_check(seconds_block=s)["clean"] is True


def test_semantic_axis_keeps_notmeasured_apart_from_fail_and_pass():
    rows = [R.row_record("frame_count_exact", "PASS"), R.row_record("cut_timeline", "UNMEASURED"),
            R.row_record("frame_pairing", "UNKNOWN"), R.row_record("audio_contract", "FAIL")]
    sem = {r["row"]: r["semantic"] for r in rows}
    assert sem == {"frame_count_exact": "pass", "cut_timeline": "notmeasured",
                   "frame_pairing": "notmeasured", "audio_contract": "fail"}


def test_technical_verdict_keeps_fail_and_notmeasured_apart():
    eight_pass = [{"verdict": "PASS"}] * 8
    two_unmeasured = eight_pass + [{"verdict": "UNMEASURED"}] * 2
    verdict, counts = A.technical_disposition(two_unmeasured)
    assert verdict == "TECHNICAL_NOTMEASURED", "no row failed - this is not a technical failure"
    assert counts["fail"] == 0 and counts["notmeasured"] == 2
    assert A.technical_disposition(eight_pass)[0] == "TECHNICAL_PASS"
    assert A.technical_disposition(eight_pass + [{"verdict": "FAIL"}])[0] == "TECHNICAL_FAIL"
    assert A.technical_disposition(eight_pass + [{"verdict": "NOT_APPLICABLE"}])[0] == "TECHNICAL_PASS"


def test_families_keep_a_technical_pass_away_from_a_visual_pass():
    rows = [R.row_record("pts_contract", "PASS"), R.row_record("cut_timeline", "UNMEASURED"),
            R.row_record("character_and_hands_present", "NOT_REVIEWED"),
            R.row_record("role_identity_proof", "NOT_REVIEWED")]
    f = R.verdict_families(rows)
    assert f["families"]["G"]["pass"] == 1
    assert f["families"]["V"]["pass"] == 0 and f["families"]["I"]["pass"] == 0
    assert f["visual_pass_count"] == 0 and f["derived_visual_pass_from_technical"] is False
    assert f["notmeasured_rows"] is not None if "notmeasured_rows" in f else True
    bad = R.verdict_families([R.row_record("character_and_hands_present", "PASS")])
    assert R.self_check(families_block=bad)["clean"] is False, (
        "a visual PASS without a viewer must be a violation")


def test_provenance_requires_sha_frames_and_a_named_viewer():
    entries = [{"artifact": "sheet_A", "sha256": "cc" * 32, "frames_covered": "000-059",
                "frames_total": 120, "viewer": None, "verdict_scope": "visual"},
               {"artifact": "comparison-076.png", "sha256": "dd" * 32, "frames_covered": "076",
                "frames_total": 120, "viewer": "Manager 20260924_175139_7a53d1",
                "verdict_scope": "visual"}]
    p = R.provenance(entries)
    assert p["entries"][0]["state"] == "NOT_REVIEWED"
    assert p["entries"][0]["promotes_to_visual"] is False
    assert p["entries"][1]["state"] == "REVIEWED"
    assert p["unviewed_count"] == 1 and p["viewed_count"] == 1
    bad = R.provenance([{"artifact": "x.png", "viewer": "someone", "verdict_scope": "visual"}])
    assert R.self_check(provenance_block=bad)["clean"] is False


def test_thresholds_are_pinned_and_may_not_move_to_go_green():
    assert _spec_base_from_source() == {
        "expected_frames": 120, "pts_duration": 4.0,
        "video": {"codec": "h264", "width": 640, "height": 360, "pix_fmt": "yuv420p"},
        "audio": {"codec": "aac", "sample_rate": 44100, "channels": 2},
        "audio_optional": True, "min_change_mae": 2.0, "max_identical_run": 2,
        "pairing_radius": 5, "pairing_min_fraction": 0.98, "pairing_margin_floor": 0.01,
        "window_start_frame": 0, "window_frame_count": 120}, (
        "a threshold moved - thresholds are never changed to make a row go green")
    src = (BENCH_DIR / "assertions.py").read_text(encoding="utf-8")
    assert re.search(r"def _cuts\(arr,\s*thresh=40\.0\)", src)
    assert "min_std >= 1.0" in src and "min_uniq >= 4" in src


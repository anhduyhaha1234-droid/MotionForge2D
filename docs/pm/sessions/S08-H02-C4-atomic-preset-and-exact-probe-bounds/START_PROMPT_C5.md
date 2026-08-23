# S08-H02-C4 CORRECTION C5 START_PROMPT (manager-authored; resume SAME session)

You are the CORRECTION C5 writer for S08-H02-C4 (atomic combined pipe cap +
cleanup deadline budgets). Codex rejected C4 with CHANGES_REQUESTED again.
This RESUMES YOUR OWN session 20260819_105751_c6c6a1. Do NOT create a new
Task ID or a new writer session. Fix ONLY the two finite findings below,
validate once, stop at SUBMITTED. Never self-approve, never write
APPROVED/CLOSED.

## HARD WORKTREE GUARD (before ANY write)

1. pwd -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration
2. git rev-parse --show-toplevel -> same
3. git branch --show-current -> codex/s08-integration
4. git rev-parse HEAD -> a43b20da742996bafcb2f9d1ac57b10d3f1a5204
5. git status --short snapshot (dirty baseline 173 entries is INTENTIONAL;
   never reset/checkout/restore/clean/stash)
If ANY differs: write NOTHING, report BLOCKED: WRONG_WORKTREE, exit immediately.
Never write MAIN (C:/Users/Admin/MotionForge2D) or another worktree.

## READ FIRST

- docs/pm/SESSION_PROTOCOL.md
- docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/TASK.md
- docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/LOG.md
- docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/REPORT.md
- app/services/video_probe.py (full file — especially _CaptureState, _PipeReader,
  _kill_proc, _run_ffprobe)
- tests/test_s08_h02_security.py (probe-related tests; append new C5 tests)

Do NOT modify TASK.md, PM_REVIEW.md, ROADMAP or product contract.

## FINDING C5-1 — COMBINED PIPE CAP IS NOT ATOMIC

Current _PipeReader.run():
  while not state.abort.is_set():
      chunk = stream.read(8192)
      if chunk == b"": break
      self.chunks.append(chunk)          # BEFORE add
      self.state.add(len(chunk))         # abort may set here

Two readers (stdout/stderr) can BOTH pass the abort check at the top, then
BOTH append+add. At the cap boundary the combined overshoot can exceed one
8192-byte reader chunk, and retained output may keep growing after abort.

Required fix:
- Shared _CaptureState must ATOMICALLY accept/reject each chunk under the same
  lock (e.g. a single accept() that adds count, decides keep/abort, and returns
  whether the chunk is retained).
- When the cap is exceeded: set abort exactly ONCE; the sibling reader must not
  keep counting or appending new chunks after that; retained output must not
  grow after abort.
- Combined observed overshoot must be no larger than exactly one reader chunk.
- Do not decode before the process ends and cap passed.
- Keep the concurrent dual-pipe drain (no deadlock).

Required tests:
1. Deterministic two-reader barrier test: stdout AND stderr each hold a chunk
   at the cap boundary; force worst-case interleaving; assert overshoot <=
   8192 bytes; assert no append after abort.
2. REAL subprocess writing large data to stdout AND stderr simultaneously:
   combined exceeds cap; ProbeOutputTooLargeError; no deadlock; bounded time.
3. Keep the multibyte UTF-8 >1MiB test and under-cap decode test both green.

## FINDING C5-2 — CLEANUP STILL GRANTS FIXED 5-SECOND WINDOWS

Current spots:
  _kill_proc: proc.wait(timeout=5.0)
  finally: proc.wait(timeout=5.0)
  finally: out_reader.join(timeout=5.0)
  finally: err_reader.join(timeout=5.0)

This violates the requirement that every wait/join uses
max(0, deadline - monotonic()).

Required fix:
- Introduce ONE shared remaining_budget(deadline) helper used consistently.
- No wait/join may receive a fixed NEW timeout after the deadline.
- If budget exhausted: kill the direct child; close pipe handles safely to
  unblock readers if needed; reap/poll WITHOUT blocking; reader daemons must
  not hold the caller for many seconds.
- Do NOT mask the original ProbeOutputTooLargeError or TimeoutExpired.
- Do NOT leave an ffprobe child behind from tests.

Required tests:
1. REAL subprocess closing pipes near deadline then continuing: timeout=0.2s,
   total elapsed in a tight bound <0.30s.
2. Timeout/cap cleanup test proving proc.wait AND both reader joins do NOT get
   a fresh 5-second window.
3. Regression: no-output child and dual-pipe child — no deadlock, no process
   leak (assert the child PID is reaped).

## ALLOWED WRITE SCOPE (ONLY these)

- app/services/video_probe.py
- tests/test_s08_h02_security.py
- docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/LOG.md
- docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/REPORT.md

Do NOT modify preset_service.py, object domain, API, frontend, migrations or
other tests unless BLOCKED and scope is opened by the manager.

## VALIDATION (fresh isolated roots/DB/basetemps; MOTIONFORGE_DATABASE_URL
unset outside inline isolated-DB commands)

1. New C5 tests only.
2. Full tests/test_s08_h02_security.py.
3. tests/test_s08_h02_security.py + tests/test_api.py.
4. tests/test_object_correction.py (C4/F4 no regress).
5. Cross-suite: tests/test_s08_golden_object_intelligence.py +
   tests/test_object_extraction_api.py + tests/test_s08_r01_queued_cancel_lifecycle.py.
6. python -m ruff check app tests.
7. python -m mypy app.
8. git diff --check.
9. ONE fresh 7/7 quality baseline with NEW Run ID.
10. Protected MAIN comparison + NO_LISTENERS on 3012/8888/8000/3000/5173/8027.

## TEST DISCIPLINE

- Every pytest: -p no:cacheprovider, shallow basetemp under
  C:/Users/Admin/AppData/Local/Temp/s08h02c5-<n> (never MSYS /c/... paths).
- NEVER bare TestClient(app) outside the conftest client fixture.
- Never weaken existing assertions / skip existing tests.
- Real subprocess tests where Codex mandates them.

## PROTECTED MAIN (read-only; verify at end)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B SHA-256
  67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256
  2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## DOCUMENTATION

- LOG.md: append CORRECTION ROUND C5 entry (append-only; keep ALL C1-C4 history).
- REPORT.md: append CORRECTION ROUND C5 section.
- Exact commands, results, elapsed times, changed files.
- LOG and REPORT must agree. Preserve ALL prior history.
- REPORT status ONLY SUBMITTED.

## SAFETY / STOP

- Do NOT end your turn until every validation ran and LOG/REPORT append done.
- No background coding children (codex FOREGROUND blocking only).
- Stop at Status: SUBMITTED (never APPROVED/CLOSED). Then exit.

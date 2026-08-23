# S08-H02-C4 START_PROMPT (manager-authored, NEW session)

You are the CORRECTION writer for S08-H02-C4 (atomic preset write + exact
probe bounds + deadline budget + flaky concurrency test). Codex rejected S08
again (CHANGES_REQUESTED). Fix ONLY the four findings below, validate once,
stop at SUBMITTED. Never self-approve, never write APPROVED/CLOSED. Use a NEW
session/run id — never reuse an old session id.

## HARD WORKTREE GUARD (before ANY write)

1. pwd -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration
2. git rev-parse --show-toplevel -> same
3. git branch --show-current -> codex/s08-integration
4. git status --short snapshot (dirty baseline 172 entries is INTENTIONAL;
   never reset/checkout/restore/clean/stash)
If ANY differs: write NOTHING, report BLOCKED: WRONG_WORKTREE, exit immediately.
Never write MAIN (C:/Users/Admin/MotionForge2D) or another worktree.

## READ FIRST

- docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/TASK.md
- docs/pm/sessions/S08-H02-local-api-origin-upload-safety/LOG.md + REPORT.md
  (prior H02 history — append-only)
- app/workflow/preset_service.py (save flow: unique_preset_output_path +
  save_preset)
- app/services/video_probe.py (_run_ffprobe, _PipeReader, _CaptureState)
- app/api/routes/projects.py preset save/apply routes
- tests/test_s08_h02_security.py
- tests/test_object_correction.py (test_concurrent_confirm_exactly_one_wins)

## Record run timestamps (Codex protocol)

- run_started_at_local: 2026-08-19T09:59:13+07:00
- run_started_at_utc: 2026-08-19T02:59:13Z
- run_finished_at_local/utc + elapsed_seconds: appended when validation done.

## FINDINGS (Codex, manager-verified on disk)

1. unique_preset_output_path (preset_service.py L109-132) uses while
   candidate.exists() then save_preset writes LATER — check-then-write race.
   Two concurrent saves A! and A? both pick a.json; only one survives.
   Codex repro: same_target=True, files=['a.json'], errors=[].
2. _PipeReader / _run_ffprobe open pipes text=True (video_probe.py L138) and
   state.add(len(chunk)) counts DECODED characters (L107). Codex repro:
   cap 1048576 B, actual UTF-8 stdout 1400000 B, ProbeOutputTooLargeError NOT
   raised.
3. After reader EOF, proc.wait uses original timeout (L168):
   proc.wait(timeout=max(0.0, min(10.0, timeout))). Codex repro: timeout 0.2s,
   child closes pipes near deadline then continues running, actual 0.407s.
4. test_concurrent_confirm_exactly_one_wins (test_object_correction.py L1334)
   treats every non-exception return as applied; confirm_correction may return
   created=False. Fix the TEST ONLY.

## IMPLEMENTATION CONTRACT

### F1 — atomic preset
- Eliminate check-then-write. Use atomic exclusive reservation
  (O_CREAT|O_EXCL retry with next suffix, or always-unique server-owned UUID
  filename). Two concurrent successful requests MUST produce two durable
  presets; no silent overwrite; do not depend only on process-local exists().
- Define same-name re-save: same display name updates its own file in place
  (preserve existing data); distinct names that slugify identically must NOT
  collide.
- REAL concurrent test (2 threads + barrier): A! and A? simultaneously; both
  successful → two DISTINCT files, both JSON valid with correct display names,
  no partial file, no silent overwrite (or one explicit conflict).

### F2 — exact byte cap
- Capture stdout/stderr as binary bytes; count combined len(bytes) BEFORE
  decode; enforce cap with bounded overshoot <= reader chunk size; decode
  UTF-8/errors=replace only AFTER process terminated + byte cap passed.
- REAL subprocess test: multibyte UTF-8 output exceeding 1 MiB must raise
  ProbeOutputTooLargeError.

### F3 — deadline budget
- Every wait/join uses max(0, deadline - monotonic()); if no budget → kill +
  reap immediately; cleanup never grants second full timeout window.
- REAL subprocess test: sleep ~0.18s, close stdout/stderr, continue sleeping,
  timeout=0.2 finishes in tight window (e.g. under 0.30s).

### F4 — flaky concurrency test (TEST ONLY)
- Capture returned created/applied boolean from confirm_correction; True =
  applied, False = replayed; preserve asserts: one recompute job exists,
  occurrence moved exactly once; do NOT weaken product concurrency semantics.
- Run this test repeated >=20 isolated repetitions to prove determinism.

## VALIDATION ORDER (run ALL; record exact commands + verbatim results)

1. New C4 tests (focused -k 'c4 or preset or probe or deadline or collision').
2. Full tests/test_s08_h02_security.py.
3. tests/test_s08_h02_security.py + tests/test_api.py.
4. test_concurrent_confirm_exactly_one_wins repeated >=20 times
   (e.g. --count via a loop or pytest-repeat; record all 20 pass/fail).
5. Cross-suite: test_s08_golden_object_intelligence.py +
   test_s08_h02_security.py + test_object_extraction_api.py +
   test_s08_r01_queued_cancel_lifecycle.py (golden needs its env vars — see
   prior H02/T06 LOG for exact invocation).
6. python -m ruff check app tests.
7. python -m mypy app.
8. git diff --check.
9. ONE fresh 7/7 quality baseline (scripts/quality-baseline.ps1) NEW Run ID.
10. Recheck protected MAIN hashes + QA ports (NO_LISTENERS).

## TEST DISCIPLINE

- Every pytest: -p no:cacheprovider, shallow basetemp under
  C:/Users/Admin/AppData/Local/Temp/s08h02c4-<n> (never MSYS /c/... paths).
- NEVER bare TestClient(app) outside the conftest client fixture.
- Never weaken existing assertions / skip existing tests.
- Real subprocess tests where Codex mandates them; real concurrent test with
  threads + barrier for F1.

## PROTECTED MAIN (read-only; verify at end)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B SHA-256
  67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256
  2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## DOCUMENTATION

- LOG.md: append CORRECTION ROUND C4 execution entry (append-only) incl. run
  timestamps, exact commands, verbatim results, final git status count,
  protected hashes, port cleanup.
- REPORT.md: append CORRECTION ROUND C4 section (root cause, implementation,
  per-finding evidence, files changed, tests + exact results incl. the x20
  concurrency run, deviations/limitations, timestamps, protected-state,
  session lineage).
- LOG and REPORT must agree. Preserve ALL prior history.

## SAFETY / STOP

- Do NOT end your turn until every validation ran and LOG/REPORT append done.
- No background coding children (codex FOREGROUND blocking only).
- Stop at Status: SUBMITTED (never APPROVED/CLOSED). Then exit.

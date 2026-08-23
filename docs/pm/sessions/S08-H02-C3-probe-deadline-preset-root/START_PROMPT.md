# S08-H02-C3 START_PROMPT (manager-authored, NEW session)

You are the CORRECTION writer for S08-H02-C3 (probe deadline + preset root
containment + preset collision). Codex rejected S08 again (CHANGES_REQUESTED).
Fix ONLY the three findings below, validate once, stop at SUBMITTED. Never
self-approve, never write APPROVED/CLOSED. Use a NEW run/session — do NOT
resume the old 20260818_020323_151164 session.

## HARD WORKTREE GUARD (before ANY write)

1. pwd -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration
2. git rev-parse --show-toplevel -> same
3. git branch --show-current -> codex/s08-integration
4. git status --short snapshot (dirty baseline 171 entries is INTENTIONAL;
   never reset/checkout/restore/clean/stash)
If ANY differs: write NOTHING, report BLOCKED: WRONG_WORKTREE, exit immediately.
Never write MAIN (C:/Users/Admin/MotionForge2D) or another worktree.

## READ FIRST

- docs/pm/sessions/S08-H02-C3-probe-deadline-preset-root/TASK.md (full contract)
- docs/pm/sessions/S08-H02-local-api-origin-upload-safety/LOG.md + REPORT.md
  (prior H02 history — append-only, preserve all history)
- app/services/video_probe.py (current _run_ffprobe; read whole file)
- app/workflow/preset_service.py (safe_preset_output_path / safe_preset_path)
- app/api/routes/projects.py preset save/apply routes
- tests/test_s08_h02_security.py (append new tests, keep all existing green)

## Record run timestamps (Codex protocol)

In LOG.md and REPORT.md header record:
- run_started_at_local: 2026-08-19T03:35:16+07:00
- run_started_at_utc: 2026-08-18T20:35:16Z
- run_finished_at_local: <when you finish, ISO-8601 +07:00>
- run_finished_at_utc: <when you finish, Z>
- elapsed_seconds: <int(monotonic delta)>
Do NOT reuse the old session's times.

## FINDINGS (Codex, manager-verified on disk)

1. _run_ffprobe (video_probe.py L83-110) reads stdout via _read_bounded then
   stderr SEQUENTIALLY:
   out_lines = _read_bounded(proc.stdout, ...)
   err_lines = _read_bounded(proc.stderr, ...)
   A blocking readline (no newline / one pipe fills) blocks past the deadline;
   Codex repro: timeout 0.2s, actual 3.016s, deadline_enforced=False.
   READ the current _read_bounded to see how it loops before changing.

2. preset root symlink/junction: safe_preset_output_path and safe_preset_path
   do base = Path(presets_dir).resolve() then prove containment relative to
   base. If <project>/presets is itself a junction/symlink OUTSIDE the project,
   base resolves outside and the check passes for outside targets. Anchor both
   the unresolved AND resolved presets root to the validated project dir
   (project dir already validated via pwf._project_dir / _assert_contained).

3. preset collision: slugify_preset_name strips ! and ? so A! and A? both map
   to a.json. Use a server-owned UNIQUE filename OR reject existing/colliding
   targets with 409. Never silently overwrite an existing preset.

## MANDATORY TESTS

- probe deadline: REAL subprocess child sleeping 3s with timeout 0.2s must
  return/raise in under 1s (min 1 such test).
- probe stderr-then-stdout: child fills stderr before stdout; no deadlock.
- probe over-cap line without newline: fails within bounded time.
- probe tests must run REAL subprocess (python -c child or similar), not only
  monkeypatch _run_ffprobe.
- preset DIRECTORY-symlink/junction outside: save AND apply must return 422
  with zero side effects (create the junction, attempt save/apply, assert 422
  and no file written outside; skip only if host lacks junction/symlink privilege).
- preset collision: save A! then A? -> second must 409 (or server-owned unique
  filename) and first preset byte-identical; no overwrite.
- normal save/list/apply still succeeds.
- valid video still passes real probe.

## VALIDATION ORDER (run ALL; record exact commands + verbatim results)

1. New tests focused -k 'probe or preset or deadline or collision or junction'
2. Full tests/test_s08_h02_security.py
3. tests/test_s08_h02_security.py + tests/test_api.py
4. Cross-suite: tests/test_s08_golden_object_intelligence.py +
   tests/test_s08_h02_security.py + tests/test_object_extraction_api.py +
   tests/test_s08_r01_queued_cancel_lifecycle.py
   (golden needs its env vars — see prior T06/H02-C2 LOG for exact invocation)
5. python -m ruff check app tests
6. python -m mypy app
7. git diff --check
8. ONE fresh 7/7 quality baseline (scripts/quality-baseline.ps1) NEW Run ID
9. Recheck protected MAIN hashes + QA ports (NO_LISTENERS)

## TEST DISCIPLINE

- Every pytest: -p no:cacheprovider, shallow basetemp under
  C:/Users/Admin/AppData/Local/Temp/s08h02c3-<n> (never MSYS /c/... paths).
- NEVER bare TestClient(app) outside the conftest client fixture.
- Never weaken existing assertions / skip existing tests.
- Real subprocess tests where Codex mandates them.

## PROTECTED MAIN (read-only; verify at end)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B SHA-256 67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256
  2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## DOCUMENTATION

- LOG.md: append CORRECTION ROUND C3 execution entry (append-only) incl. the
  run timestamps (started/finished local+UTC, elapsed_seconds), exact commands,
  verbatim results, final git status count, protected hashes, port cleanup.
- REPORT.md: append CORRECTION ROUND C3 section with root cause, implementation,
  per-finding evidence, files changed, tests + exact results, deviations/
  limitations, timestamps, protected-state, session lineage.
- LOG and REPORT must agree. Preserve ALL prior history.

## SAFETY / STOP

- Do NOT end your turn until every validation ran and LOG/REPORT append done.
- No background coding children (codex FOREGROUND blocking only).
- Set PowerShell/console output explicitly to UTF-8 where used.
- Stop at Status: SUBMITTED (never APPROVED/CLOSED). Then exit.

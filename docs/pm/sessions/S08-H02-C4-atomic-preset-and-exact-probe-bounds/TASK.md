# S08-H02-C4 — Atomic preset + exact probe bounds (Codex CHANGES_REQUESTED)

**Status:** PLANNED
**Session type:** NEW session (Codex protocol: never reuse old session id)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Dirty baseline:** 172 git-status entries (intentional; never reset/clean/stash)

## Run timestamps (Codex protocol — new run id)

- run_started_at_local: 2026-08-19T09:59:13+07:00
- run_started_at_utc: 2026-08-19T02:59:13Z
- run_finished_at_local/utc: (filled by writer)
- elapsed_seconds: (filled = finished_epoch - 1787108354)

## Codex CHANGES_REQUESTED (S08-H02-C4) — fix ONLY these four

### Finding 1 — P1 concurrent preset overwrite

`unique_preset_output_path` uses `candidate.exists()` and `save_preset` writes
later. Two concurrent saves reproduced: A! -> a.json, A? -> a.json,
same_target=True, files=['a.json'], errors=[], only one stored preset survives.

Fix:
- Eliminate check-then-write.
- Prefer an always-unique server-owned filename containing a UUID, OR perform
  atomic exclusive reservation using O_CREAT|O_EXCL and atomic publication.
- Two concurrent successful requests must ALWAYS produce two durable presets.
- Neither request may silently overwrite the other.
- Do not depend only on a process-local existence check.
- Define same-name re-save semantics explicitly; preserve existing data.

Required REAL concurrent test (two threads + barrier):
- issue A! and A? saves simultaneously;
- both responses successful or one explicit conflict;
- two successful responses correspond to two DISTINCT files;
- both JSON documents valid and retain the correct display names;
- no partial file and no silent overwrite.

### Finding 2 — byte cap counts decoded characters

`video_probe` opens pipes with `text=True` and calls `state.add(len(chunk))`.
Codex repro: configured cap 1048576 bytes, actual UTF-8 stdout 1400000 bytes,
ProbeOutputTooLargeError NOT raised.

Fix:
- Capture stdout/stderr as BINARY bytes.
- Count the combined len(bytes) BEFORE decoding.
- Enforce the cap with bounded overshoot no larger than reader chunk size.
- Decode using UTF-8/errors=replace only after the process is terminated and
  the byte cap has passed.

Required REAL subprocess test using multibyte UTF-8 output exceeding 1 MiB →
must raise ProbeOutputTooLargeError.

### Finding 3 — remaining deadline budget

After reader EOF, `proc.wait` receives the original timeout.
Codex repro: requested timeout 0.2s, child closes pipes near deadline then
continues running, actual elapsed 0.407s.

Fix:
- Every wait/join must use max(0, deadline - monotonic()).
- If no budget remains, kill and reap immediately.
- Cleanup must not grant the child a second full timeout window.

Required REAL subprocess test: sleep ~0.18s; close stdout/stderr; continue
sleeping; timeout=0.2 must finish in a tight bounded window (e.g. under 0.30s).

### Finding 4 — flaky concurrency test

`tests/test_object_correction.py::test_concurrent_confirm_exactly_one_wins`
incorrectly treats every non-exception return as "applied".
`confirm_correction` may return created=False directly after the other thread
commits.

Fix the TEST ONLY:
- capture the returned created/applied boolean;
- classify True as applied and False as replayed;
- preserve the assertions that only one recompute job exists and the occurrence
  is moved exactly once;
- do not weaken product concurrency semantics.
- Run that concurrency test repeatedly (>=20 isolated repetitions) to prove
  determinism.

## Validation order (run ALL)

1. New C4 tests (focused -k 'c4 or preset or probe or deadline or collision').
2. Full tests/test_s08_h02_security.py.
3. tests/test_s08_h02_security.py + tests/test_api.py.
4. test_concurrent_confirm_exactly_one_wins repeated >=20 times.
5. Cross-suite: test_s08_golden_object_intelligence.py + test_s08_h02_security.py
   + test_object_extraction_api.py + test_s08_r01_queued_cancel_lifecycle.py.
6. python -m ruff check app tests.
7. python -m mypy app.
8. git diff --check.
9. ONE fresh 7/7 quality baseline after focused gates pass (NEW Run ID).
10. Recheck protected MAIN hashes + all QA ports (NO_LISTENERS).

## Files in scope

- app/workflow/preset_service.py
- app/services/video_probe.py
- tests/test_s08_h02_security.py
- tests/test_object_correction.py (test-only fix for Finding 4)
- S08-H02-C4 packet LOG.md / REPORT.md

## Protected MAIN expected (read-only)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B, SHA-256 67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B, SHA-256
  2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## Forbidden

- Self-approve / write APPROVED/CLOSED.
- Modify TASK.md / PM_REVIEW.md.
- Commit/push/merge/reset/checkout/restore/clean/stash.
- Modify MAIN or another worktree.
- Overwrite prior LOG/REPORT content (append-only).
- Test hostile requests against MAIN data.

## Stop

Stop at SUBMITTED after full validation; never self-approve. S08 stays
SPRINT_SUBMITTED. Do not start S07/S09.

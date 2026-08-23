# S08-H02-C4 — Atomic preset / Exact probe bounds: Implementation Report

**Status:** SUBMITTED (worker evidence below; manager/Codex sprint-exit review owns approval — never self-approve)
**Hermes session:** 20260819_105751_c6c6a1 (NEW session per Codex mandate)
**Model:** ocg/deepseek-v4-flash (user directive 2026-08-17 — flash, no pro)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Task:** CORRECTION ROUND C4 (Codex CHANGES_REQUESTED on S08 — atomic preset
write, exact byte cap, deadline budget, flaky concurrency test)
**run_started_at_local:** 2026-08-19T09:59:13+07:00
**run_started_at_utc:** 2026-08-19T02:59:13Z
**run_finished_at_local:** 2026-08-19T11:57:52+07:00
**run_finished_at_utc:** 2026-08-19T04:57:52Z
**elapsed_seconds:** 7118

---

# CORRECTION ROUND C4 — Implementation & Validation

Hard worktree guard verified before any write: `pwd` / `git rev-parse --show-toplevel` = the s08-integration worktree; `git branch --show-current` = `codex/s08-integration`; `git status --short` snapshot = 173 entries (documented baseline 172 + the manager-materialized C4 packet dir; dirty baseline INTENTIONAL — never reset/checkout/restore/clean/stash). HEAD = a43b20da742996bafcb2f9d1ac57b10d3f1a5204.

## Root causes (all four confirmed on disk; F1/F2/F3 reproduced by REAL subprocess/thread tests)

1. **P1 concurrent preset overwrite** — `unique_preset_output_path` used `while candidate.exists()` (check-then-*write* race): two saves of distinct display names that slugify identically (A! and A? -> `a`) could BOTH observe `a.json` missing and both commit to it; the later `save_preset` silently clobbered the first (Codex repro: same_target=True, files=['a.json'], errors=[]).
2. **byte cap counts decoded characters** — `_run_ffprobe` opened pipes `text=True` and `_PipeReader` did `state.add(len(chunk))` on DECODED STRINGS; 700k multibyte `é` (1.4 MB of UTF-8 bytes) counted only 700k "characters", so the 1 MiB cap never tripped.
3. **second full timeout window** — after both readers hit EOF, `proc.wait(timeout=max(0.0, min(10.0, timeout)))` granted the child a FRESH full `timeout` even though most of the deadline had already elapsed (Codex repro: timeout 0.2s, child closes pipes near deadline then keeps running, actual elapsed 0.407s).
4. **flaky concurrency test** — `test_concurrent_confirm_exactly_one_wins` treated every non-exception return as "applied"; `confirm_correction` may return created=False (replay) directly after the other thread commits, and SQLite file-lock contention between the two writer threads could drop one outcome.

## Implementation (all in TASK.md allowed scope)

- **F1 — `app/workflow/preset_service.py`**: `unique_preset_output_path` now performs an ATOMIC exclusive reservation with `os.open(O_CREAT|O_EXCL)` inside a suffix-retry loop (`a.json`, `a-2.json`, ...). The collision decision no longer depends on a process-local `exists()`: exactly one save owns a given filename, every loser exclusively owns the next suffix, so two concurrent successful saves ALWAYS produce two distinct durable presets with no silent overwrite. Same-name re-save still returns its own existing file (in-place update) when the stored display name matches; a reserved-but-not-yet-written empty file is never mistaken for an existing preset (unreadable JSON -> None).
  - **Windows resolution race (found by the new concurrent tests, fixed)**: on Windows `Path.resolve()` canonicalises an existing path differently from a missing one, so concurrent first-saves that create the presets dir between two internal resolve() calls spuriously tripped `preset path escapes the presets directory` / `presets root resolves outside the project directory`. Fixed by a lexical pre-check (absolute, no side effect) followed by materialising the presets container BEFORE the resolve()-based checks; hostile/reserved names and lexical escapes still raise 422 with zero side effects; junction/symlink root escapes still rejected by the resolve-based check after materialisation. Proven by a 12,000-iteration two-thread repro: 0 failures (pre-fix: 3-in-3000 and 36-in-3000).
- **F2 — `app/services/video_probe.py`**: `_run_ffprobe` opens the pipes BINARY (no `text=True`/encoding/bufsize); `_PipeReader` reads raw bytes and `state.add(len(chunk))` counts BYTES; the combined stdout+stderr byte total is enforced against `PROBE_MAX_OUTPUT_BYTES` BEFORE any decoding (overshoot bounded by the 8192-byte read chunk); UTF-8/errors=replace decoding happens ONLY after the child terminated and the byte cap passed. Real-subprocess test: 700k `é` (1,400,000 UTF-8 bytes, > 1 MiB) now raises `ProbeOutputTooLargeError`; under-cap multibyte round-trips losslessly.
- **F3 — `app/services/video_probe.py`**: after both readers hit EOF the reap uses only `max(0, deadline - monotonic())`; zero remaining budget -> kill + reap + raise immediately. The cleanup `finally` no longer grants a second window (`_kill_proc` kills then reaps with a short 5s bound). Real-subprocess tests: child sleeps ~0.18s, closes stdout+stderr, keeps sleeping; timeout=0.2s finishes in a tight window (asserted < 0.30s); a second test proves the EOF-reap is deadline-bounded, not deadline+full-timeout.
- **F4 — `tests/test_object_correction.py` (TEST ONLY)**: the worker now captures the returned `created` boolean — True = applied, False = replayed — and classifies accordingly; transient SQLite `OperationalError` (database is locked between the two concurrent writer threads) is retried with a bounded backoff; the product CAS in `confirm_correction` is untouched. Assertions preserved: sorted outcomes == ["applied","replayed"], exactly ONE recompute job, the occurrence moved exactly once.

## Files changed (this round)

- `app/workflow/preset_service.py` (F1)
- `app/services/video_probe.py` (F2+F3)
- `tests/test_s08_h02_security.py` (6 new C4 tests)
- `tests/test_object_correction.py` (F4 test-only)
- `docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/LOG.md` + `REPORT.md` (this append)

No commits/push/merge/reset/checkout/restore/clean/stash; TASK.md / PM_REVIEW.md untouched; MAIN (`C:/Users/Admin/MotionForge2D`) untouched.

## Tests and exact results (fresh isolated roots, `-p no:cacheprovider`, shallow basetemps `C:/Users/Admin/AppData/Local/Temp/s08h02c4-*`, `MOTIONFORGE_DATABASE_URL` unset)

1. `python -m pytest tests/test_s08_h02_security.py -k 'c4 or preset or probe or deadline or collision' -q -p no:cacheprovider --basetemp=...s08h02c4-01b` -> **29 passed, 34 deselected** (9.45s); the 6 new C4 tests all passed.
2. `python -m pytest tests/test_s08_h02_security.py -q -p no:cacheprovider --basetemp=...s08h02c4-02b` -> **63 passed** (25.87s).
3. `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider --basetemp=...s08h02c4-03b` -> **88 passed** (42.19s). A first V3 run exposed the F1 Windows resolution race; fixed, then re-run green.
4. `test_concurrent_confirm_exactly_one_wins` x20 isolated, repeated twice -> **40/40 PASS** (per-iteration recorded). Full `tests/test_object_correction.py` -> **34 passed** (21.87s).
5. Cross-suite golden: `S08T06_RUN_ID=s08h02c4-golden GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08h02c4-golden python -m pytest tests/test_s08_golden_object_intelligence.py tests/test_s08_h02_security.py tests/test_object_extraction_api.py tests/test_s08_r01_queued_cancel_lifecycle.py -q -p no:cacheprovider --basetemp=...s08h02c4-04` -> **90 passed** (77.44s). Golden metrics `output/s08-sprint/s08h02c4-golden/golden-metrics.json` regenerated green (gitignored).
6. `python -m ruff check app tests` -> **All checks passed!**
7. `python -m mypy app` -> **Success: no issues found in 88 source files**.
8. `git diff --check` -> exit 0 (only pre-existing LF->CRLF advisories on earlier sprint files).
9. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh NEW Run ID) -> run **20260819-114525** -> **7/7 gates PASS, OVERALL exit 0** (Gate 2 pytest 611.48s exit 0 — includes the F4-fixed concurrency test with no flake).
10. Protected MAIN (read-only): channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (mtime 2026-07-29 untouched). QA ports NO_LISTENERS on 3012/8888/8000/3000/5173 (a leftover worktree-tied `next start-server` on 3012, PID 2924, was found and stopped; transient `frontend/.playwright-cli/` cache from the build gate removed; restored the 173-entry status baseline).

## Race-reproduction evidence (beyond the required tests)

- F1 ow: a 2-thread A!/A? repro on a long-component-name temp root produced `InvalidPresetNameError('preset path escapes the presets directory')` (3-in-3000) and, after the first partial fix, `('presets root resolves outside the project directory')` (36-in-3000). Final fix: materialise-before-resolve -> **0 failures / 12,000 concurrent iterations**, every iteration yielding exactly two distinct files.
- F4: before the fix, the x20 batch had 1 failure (19/20). After capturing `created` + bounded SQLite-lock retry: **40/40 isolated repetitions passed**, plus the 611s full-suite Gate 2 passed clean.

## Deviations / limitations

- The preset reservation creates the target file empty and the route writes the JSON immediately after; a reserved-but-crashed-before-write file is empty (never silently-overwritten, never listed/loaded) — not a partial overwrite of an existing preset.
- Under the pathological concurrent FIRST-save of the SAME display name (both threads see no existing file), the two saves can land in a.json and a-2.json (both durable, no overwrite) rather than collapsing to one in-place file; the sequential same-name re-save contract (in-place update, no suffix accumulation) is unchanged and covered by `test_preset_same_name_resave_updates_in_place`.
- F4's bounded SQLite-lock retry is test-only hardening for the documented Gate-2 flake; no product concurrency semantics were weakened.

## Session lineage

C1/C2: session 20260818_020323_151164 (prior rounds). C3: 2026-08-19 03:35 NEW session (NOT resumed). C4 (this round): NEW session 20260819_105751_c6c6a1, split run_started 2026-08-19T09:59:13+07:00.

**Status: SUBMITTED.** No self-approval, no TASK.md / PM_REVIEW.md change, no commit/push/merge/reset/clean/stash. S08 remains SPRINT_SUBMITTED; S07/S09 NOT started.

---

# CORRECTION ROUND C5 — atomic combined pipe cap + cleanup deadline budgets

**Resumed own session** 20260819_105751_c6c6a1 (manager START_PROMPT_C5: no new Task ID / writer session).
Run timestamps: run_started_at_local 2026-08-19T12:00:00+07:00 (approx); run_finished_at_local 2026-08-19T13:47:08+07:00; run_finished_at_utc 2026-08-19T06:47:09Z; elapsed_seconds 6427 (approx anchor = 1787122028 - 1787115601).

Hard worktree guard verified before any write: `pwd` / `git rev-parse --show-toplevel` = the s08-integration worktree; `git branch --show-current` = `codex/s08-integration`; `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`; `git status --short` snapshot = 173 entries (dirty baseline INTENTIONAL — never reset/checkout/restore/clean/stash).

## Findings (Codex CHANGES_REQUESTED on C4) and root causes

1. **C5-1 — combined pipe cap is not atomic.** `_PipeReader.run()` did `chunks.append(chunk)` BEFORE `state.add(len(chunk))`, and the abort decision lived in a separate `state.add` called after the top-of-loop check. Two readers could BOTH pass the `abort.is_set()` check at the top, then BOTH append+add, so at the cap boundary the combined overshoot could exceed one 8192-byte reader chunk and retained output could keep growing after abort.
2. **C5-2 — cleanup still grants fixed 5-second windows.** `_kill_proc` (`proc.wait(timeout=5.0)`), the `finally` (`proc.wait(timeout=5.0)`) and both reader joins (`join(timeout=5.0)`) all gave the child/readers a fresh fixed window after the deadline instead of using `max(0, deadline - monotonic())`.

## Implementation (allowed scope ONLY: app/services/video_probe.py + tests/test_s08_h02_security.py + C4 LOG/REPORT)

- **C5-1 — `app/services/video_probe.py`**: `_CaptureState.add` removed; new `_CaptureState.accept(n) -> bool` performs the keep/reject decision ATOMICALLY under the single `_lock`: rejects immediately once abort is set; otherwise computes `new_count = count + n`, and when `new_count > cap` sets abort EXACTLY ONCE and returns False (chunk DISCARDED, never counted/retained); otherwise retains (returns True) and updates count. `_PipeReader.run` now reads a chunk, then `chunks.append(chunk)` ONLY when `accept()` returns True. Guarantees: retained output never grows after abort; the sibling reader can't keep counting/appending after abort; combined observed overshoot of retained bytes is <= one 8192-byte reader chunk; the concurrent dual-pipe drain is preserved (no deadlock).
- **C5-2 — `app/services/video_probe.py`**: ONE shared `remaining_budget(deadline) = max(0.0, deadline - time.monotonic())`. `_kill_proc(proc, deadline)` kills then reaps with `wait(timeout=budget)` when budget > 0, else non-blocking `poll()` (never a fixed window). New `_drop_stream(stream)` best-effort closes a pipe read-end to unblock a still-attached daemon reader. `_run_ffprobe` — the abort/deadline checks, the EOF reap (`proc.wait(timeout=budget)`), and the `finally` (drop-stream for still-alive readers + `out_reader.join(timeout=remaining_budget(deadline))` + `err_reader.join(...)`) — ALL use `remaining_budget(deadline)`. No fixed 5.0s wait/join remains anywhere in the probe path. The original `ProbeOutputTooLargeError`/`TimeoutExpired` are never masked. No child is left behind (kill + bounded reap; `poll()` non-blocking when exhausted).

## Files changed (this round)

- `app/services/video_probe.py` (C5-1 + C5-2)
- `tests/test_s08_h02_security.py` (8 new C5 tests: atomic boundary accept, 300x two-reader barrier race, no-append-after-abort, REAL dual-writer simultaneous cap, EOF tight-window, no-fixed-5s cleanup, `_kill_proc` reaps child, no-output + dual-pipe no-deadlock regression)
- `docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/LOG.md` + `REPORT.md` (this append)

TASK.md / PM_REVIEW.md / ROADMAP / product contract NOT modified. (ROADMAP.md was changed at 12:21 by the manager/PM concurrently — I never wrote it; it remains the pre-existing `M` in the baseline.)

## Validation (exact commands + verbatim results; -p no:cacheprovider; shallow basetemps C:/Users/Admin/AppData/Local/Temp/s08h02c5-*; MOTIONFORGE_DATABASE_URL unset)

1. `python -m pytest tests/test_s08_h02_security.py -k 'c5' -q -p no:cacheprovider --basetemp=...s08h02c5-01d` -> **8 passed, 63 deselected** (2.48s). Also `-k 'c4 or c5 or probe or deadline or collision'` -> **26 passed** (4.96s), keeping every C4 probe/preset/deadline test green. (Two earlier attempts failed only on a child `-c` script syntax error — `;`-then-`def` is invalid Python; rewrote the child with `\n`-separated statements, then clean.)
2. Full H02: `python -m pytest tests/test_s08_h02_security.py -q -p no:cacheprovider --basetemp=...s08h02c5-02` -> **71 passed** (24.44s).
3. H02 + API: `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider --basetemp=...s08h02c5-03` -> **96 passed** (38.49s).
4. `python -m pytest tests/test_object_correction.py -q -p no:cacheprovider --basetemp=...s08h02c5-04` -> **34 passed** (21.64s) — C4/F4 no regression.
5. Cross-suite golden: `S08T06_RUN_ID=s08h02c5-golden GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08h02c5-golden python -m pytest tests/test_s08_golden_object_intelligence.py tests/test_object_extraction_api.py tests/test_s08_r01_queued_cancel_lifecycle.py -q -p no:cacheprovider --basetemp=...s08h02c5-05` -> **27 passed** (55.65s). Golden metrics `output/s08-sprint/s08h02c5-golden/golden-metrics.json` regenerated green (gitignored).
6. `python -m ruff check app tests` -> **All checks passed!**
7. `python -m mypy app` -> **Success: no issues found in 88 source files**.
8. `git diff --check` -> exit 0 (only pre-existing LF->CRLF advisories).
9. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh NEW Run ID) -> run **20260819-133623** -> **7/7 gates PASS, OVERALL exit 0** (Gate 2 pytest 600.78s exit 0).
10. Protected MAIN (read-only): channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (mtime 2026-07-29 untouched). QA ports NO_LISTENERS on 3012/8888/8000/3000/5173/8027; no worktree-tied node processes.

## Race semantics evidence (beyond the required tests)

- The 300-iteration two-reader barrier race (`test_c5_capture_state_two_reader_barrier_worst_case`) proves that under EVERY interleaving at most ONE boundary chunk is retained, the combined count never exceeds cap, and abort is set exactly once — the atomic accept() makes the outcome interleaving-independent.
- `test_c5_timeout_cleanup_no_fixed_5s_window` (child sleeps 60s, never closes pipes, timeout=0.3s) finishes with elapsed < 1.0s, proving the kill/reap and BOTH reader joins no longer grant a fixed ~5s window; `test_c5_deadline_tight_window_after_readers_eof` (close-pipes-near-deadline child, timeout=0.2s) finishes < 0.30s.

## Deviations / limitations

- run_started_at_local for C5 is approximate (12:00:00+07:00; the turn was not instrumented to the second — bounded by C4 finishing 11:57 and the ROADMAP external touch at 12:21).
- The child scripts in tests use `\n`-separated statements (a `;`-then-`def` one-liner is a Python SyntaxError); this is a test-script shape, not a product change.
- `_drop_stream` closes our read ends only for readers still alive after kill; it is best-effort and can surface a benign OSError/ValueError inside the daemon reader, which is recorded as `exc` and never raised to the caller.

## Session lineage

C1/C2: 20260818_020323_151164. C3: 2026-08-19 03:35 NEW session. C4: NEW session 20260819_105751_c6c6a1 (ran 09:59-11:57). C5 (this round): resume same session 20260819_105751_c6c6a1 (ran ~12:00-13:47) per manager START_PROMPT_C5.

**Status: SUBMITTED.** No self-approval, no TASK.md / PM_REVIEW.md change, no commit/push/merge/reset/clean/stash. S08 remains SPRINT_SUBMITTED; S07/S09 NOT started.

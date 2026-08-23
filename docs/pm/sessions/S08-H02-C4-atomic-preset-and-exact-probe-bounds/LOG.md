# S08-H02-C4 — LOG (append-only)

## 2026-08-19 — Packet materialized by manager (pre-launch)

- run_started_at_local: 2026-08-19T09:59:13+07:00
- run_started_at_utc: 2026-08-19T02:59:13Z
- TASK.md / START_PROMPT.md created from Codex CHANGES_REQUESTED (S08-H02-C4:
  atomic preset write / exact byte cap / deadline budget / flaky concurrency test).
- Manager verified findings on disk: unique_preset_output_path check-then-write
  race (L126), _run_ffprobe text=True decoded-char cap (L138/L107),
  proc.wait original-timeout (L168), test_concurrent_confirm_exactly_one_wins
  treats every return as applied (L1334).
- Launcher: `output/run-s08-h02-c4.ps1` (NEW session, flash). Baseline git
  status 172, ports free, 0 writers.

## 2026-08-19 — CORRECTION ROUND C4 executed (NEW session; never reusing an old session id)

### Hard worktree guard (before ANY write)
- `pwd` -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration  (OK)
- `git rev-parse --show-toplevel` -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration  (OK)
- `git branch --show-current` -> codex/s08-integration  (OK)
- `git status --short` snapshot = **173** entries at session start (documented baseline 172 + the manager-materialized `docs/pm/sessions/S08-H02-C4-.../` packet dir — count drift only, NOTHING reset/checkout/restore/clean/stash). HEAD = a43b20da742996bafcb2f9d1ac57b10d3f1a5204.

### Run timestamps (Codex protocol, NEW run id — not reused)
- run_started_at_local: 2026-08-19T09:59:13+07:00
- run_started_at_utc: 2026-08-19T02:59:13Z
- run_finished_at_local: 2026-08-19T11:57:52+07:00
- run_finished_at_utc: 2026-08-19T04:57:52Z
- elapsed_seconds: 7118 (= 1787115472 - 1787108354)

### Required reading (completed in READ-FIRST order)
- [x] `docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/TASK.md`
- [x] `docs/pm/sessions/S08-H02-local-api-origin-upload-safety/LOG.md` + `REPORT.md` (prior H02 history — append-only, preserved)
- [x] `app/workflow/preset_service.py` (`unique_preset_output_path` L109-132 — while candidate.exists() check-then-write race; `save_preset` writes LATER)
- [x] `app/services/video_probe.py` (`_run_ffprobe`, `_PipeReader`, `_CaptureState` — text=True pipes, len(chunk) counts decoded chars, EOF proc.wait re-grants a second full timeout)
- [x] `app/api/routes/projects.py` preset save/apply routes (L1907-2031)
- [x] `tests/test_s08_h02_security.py` (57 prior tests, all kept green)
- [x] `tests/test_object_correction.py::test_concurrent_confirm_exactly_one_wins` (L1334; returned created bool ignored)
- Env: `MOTIONFORGE_DATABASE_URL=[UNSET]`, Python 3.11.9, `app` import OK, ffmpeg/ffprobe reachable.

### Plan (<=7 steps)
1. F1 preset_service: replace check-then-write with ATOMIC O_CREAT|O_EXCL reservation (suffix retry, same-name re-save in place).
2. F2+F3 video_probe: BINARY pipe reads, len(bytes) counted BEFORE decode, decode only after termination+cap pass; EOF reap uses max(0, deadline-monotonic), kill+reap immediately on no budget.
3. Append C4 tests (6 new): concurrent A!/A? (2 threads + barrier) + 5x determinism + multibyte >1MiB raises + under-cap decodes + deadline tight window + no-second-window.
4. F4 test_object_correction (TEST ONLY): capture created bool (True=applied, False=replayed) + bounded SQLite-lock retry; preserve one-job + moved-once asserts.
5. Run validation order 1-10.
6. Append CORRECTION ROUND C4 to LOG.md + REPORT.md. Status: SUBMITTED (never APPROVED/CLOSED). Stop.

### Implementation (4 findings closed; all in TASK.md allowed scope)
- F1 `app/workflow/preset_service.py`: `unique_preset_output_path` now performs an ATOMIC exclusive reservation (`os.open(O_CREAT|O_EXCL)`, suffix retry a.json -> a-2.json -> ...); the collision decision never depends on a process-local `exists()`. Same-name re-save returns its own file (in-place update). Presets container is materialized BEFORE resolve()-based checks (after a lexical pre-check) — on Windows `Path.resolve()` canonicalises an existing vs missing path differently, so concurrent first-saves could spuriously trip the containment checks (found by the new tests; fixed; proven by a 12,000-iteration two-thread repro with 0 failures). Hostile/reserved names + lexical escapes still 422 with zero side effects.
- F2 `app/services/video_probe.py`: pipes opened BINARY; `_PipeReader.read(8192)` returns bytes and `state.add(len(chunk))` counts BYTES; combined cap enforced before decode; UTF-8/errors=replace decoding only after child terminated + cap passed.
- F3 `app/services/video_probe.py`: after reader EOF, reap uses only the REMAINING budget (max(0, deadline-monotonic())); no budget -> kill+reap+raise immediately; cleanup grants no second full timeout window.
- F4 `tests/test_object_correction.py` (TEST ONLY): worker captures returned `created` (True=applied, False=replayed), retries transient SQLite `OperationalError` (database is locked) with bounded backoff; product CAS untouched; one-recompute-job + moved-once asserts preserved.

### Validation (exact commands + verbatim results; `-p no:cacheprovider`; shallow basetemps `C:/Users/Admin/AppData/Local/Temp/s08h02c4-*`; `MOTIONFORGE_DATABASE_URL` unset)
1. `python -m pytest tests/test_s08_h02_security.py -k 'c4 or preset or probe or deadline or collision' -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02c4-01b` -> `29 passed, 34 deselected` (9.45s). New-only 6/6 PASSED.
2. `python -m pytest tests/test_s08_h02_security.py -q -p no:cacheprovider --basetemp=...s08h02c4-02b` -> `63 passed` (25.87s).
3. `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider --basetemp=...s08h02c4-03b` -> `88 passed` (42.19s). (A first V3 run caught the F1 resolution race — fixed, re-run green.)
4. `test_concurrent_confirm_exactly_one_wins` x20 isolated x2 batches -> **40/40 PASS** (all recorded). `python -m pytest tests/test_object_correction.py -q -p no:cacheprovider --basetemp=...s08h02c4-objcorr` -> `34 passed` (21.87s).
5. `S08T06_RUN_ID=s08h02c4-golden GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08h02c4-golden python -m pytest tests/test_s08_golden_object_intelligence.py tests/test_s08_h02_security.py tests/test_object_extraction_api.py tests/test_s08_r01_queued_cancel_lifecycle.py -q -p no:cacheprovider --basetemp=...s08h02c4-04` -> `90 passed` (77.44s). Golden metrics output/s08-sprint/s08h02c4-golden/golden-metrics.json regenerated (gitignored).
6. `python -m ruff check app tests` -> `All checks passed!`
7. `python -m mypy app` -> `Success: no issues found in 88 source files`
8. `git diff --check` -> exit 0 (only pre-existing LF->CRLF advisories on earlier sprint files).
9. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh NEW Run ID) -> run `20260819-114525` -> **7/7 gates PASS, OVERALL exit 0** (Gate 1 preflight 0s; Gate 2 pytest 611.48s exit 0 [includes F4-fixed concurrency test]; Gate 3 ruff 0.06s; Gate 4 mypy 0.64s; Gate 5 tsc 1.45s; Gate 6 lint 4.27s; Gate 7 build 6.24s).
10. Protected MAIN (read-only): channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; sam2.1_hiera_large.pt 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (mtime 2026-07-29 untouched). QA ports NO_LISTENERS on 3012/8888/8000/3000/5173 (a leftover worktree-tied `next start-server` on 3012, PID 2924, was found and stopped; transient `frontend/.playwright-cli/` cache from the build gate removed).

### Final state
- `git status --short` = **173** (session-start baseline restored — the transient +1 `.playwright-cli/` cache removed; `output/` gitignored so quality-baseline + golden evidence invisible to git). Scope window (find app tests docs -newermt 09:55) = exactly app/workflow/preset_service.py, app/services/video_probe.py, tests/test_s08_h02_security.py, tests/test_object_correction.py + the C4 packet docs. No reset/checkout/restore/clean/stash.
- REPORT.md appended CORRECTION ROUND C4 section; header Status -> SUBMITTED with real run timestamps. LOG and REPORT agree. **Status: SUBMITTED** (never self-approved; TASK.md / PM_REVIEW.md untouched; no commit/push/merge). S08 stays SPRINT_SUBMITTED; S07/S09 NOT started.

## 2026-08-19 — CORRECTION ROUND C5 executed (resume OWN session 20260819_105751_c6c6a1 — no new Task ID / writer session per manager START_PROMPT_C5)

### Hard worktree guard (before ANY write)
- `pwd` -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration  (OK)
- `git rev-parse --show-toplevel` -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration  (OK)
- `git branch --show-current` -> codex/s08-integration  (OK)
- `git rev-parse HEAD` -> a43b20da742996bafcb2f9d1ac57b10d3f1a5204  (OK)
- `git status --short` snapshot = **173** entries (dirty baseline INTENTIONAL; never reset/checkout/restore/clean/stash).

### Run timestamps (Codex protocol; resume, not reused)
- run_started_at_local: 2026-08-19T12:00:00+07:00 (approx — C5 resumed own session right after C4 finished 11:57; not instrumented to the second)
- run_finished_at_local: 2026-08-19T13:47:08+07:00
- run_finished_at_utc: 2026-08-19T06:47:09Z
- elapsed_seconds: 6427 (approx anchor; = 1787122028 - 1787115601)

### Required reading (completed in READ-FIRST order)
- [x] docs/pm/SESSION_PROTOCOL.md
- [x] docs/pm/sessions/S08-H02-C4-atomic-preset-and-exact-probe-bounds/TASK.md + LOG.md + REPORT.md (prior C1-C4 history preserved)
- [x] app/services/video_probe.py (full — _CaptureState, _PipeReader, _kill_proc, _run_ffprobe)
- [x] tests/test_s08_h02_security.py (probe tests; 8 new C5 tests appended)
- Env: MOTIONFORGE_DATABASE_URL=[UNSET], Python 3.11.9, app imports OK.
- Constraint honoured: TASK.md / PM_REVIEW.md / ROADMAP / product contract NOT modified by me. NOTE: docs/pm/ROADMAP.md was modified at 12:21 by the manager/PM concurrently during this round — I never wrote it (none of my commands touch that file); it remains a pre-existing `M` in the baseline as observed.

### Implementation (2 findings closed; allowed scope = video_probe.py + test_s08_h02_security.py + LOG/REPORT ONLY)
- C5-1 `app/services/video_probe.py`: `_CaptureState.add` replaced by `_CaptureState.accept(n) -> bool` — under ONE lock it atomic-keeps/rejects each chunk: rejects immediately when abort already set; computes new_count; sets abort EXACTLY ONCE when new_count > cap (returns False, chunk DISCARDED); else retains (returns True) and updates count. `_PipeReader.run` appends ONLY after accept() returns True, so a chunk that trips the cap is never appended and the sibling reader can neither keep counting nor append after abort; combined overshoot of retained bytes is <= one 8192-byte reader chunk. Concurrent dual-pipe drain kept (no deadlock).
- C5-2 `app/services/video_probe.py`: single shared `remaining_budget(deadline) = max(0.0, deadline - time.monotonic())` helper. `_kill_proc(proc, deadline)` kills then reaps with `wait(timeout=budget)` when budget > 0, else non-blocking `poll()` (never a fixed window). `_drop_stream(stream)` best-effort closes a pipe read-end to unblock a daemon reader. `_run_ffprobe` main abort/deadline checks, EOF reap, and the finally (drop-stream for still-alive readers + both reader joins) ALL use `remaining_budget(deadline)` — the fixed 5.0s waits in `_kill_proc`/finally/joins are gone.
- Tests: 8 new C5 tests appended to tests/test_s08_h02_security.py (atomic boundary accept, 300x two-reader barrier race, no-append-after-abort, REAL dual-writer simultaneous cap, EOF tight window, no-fixed-5s cleanup, _kill_proc reaps child, no-output + dual-pipe no-deadlock regression).

### Validation (exact commands + verbatim results; -p no:cacheprovider; shallow basetemps C:/Users/Admin/AppData/Local/Temp/s08h02c5-*; MOTIONFORGE_DATABASE_URL unset)
1. `python -m pytest tests/test_s08_h02_security.py -k 'c5' -q -p no:cacheprovider --basetemp=...s08h02c5-01d` -> `8 passed, 63 deselected` (2.48s). (1st-2nd attempts failed only on a child `-c` script syntax error — `;`-then-`def` is invalid; rewrote the child with \n-separated statements, then green.)
   Also `-k 'c4 or c5 or probe or deadline or collision'` -> `26 passed, 45 deselected` (4.96s) — C4 probe/preset/deadline tests stay green.
2. `python -m pytest tests/test_s08_h02_security.py -q -p no:cacheprovider --basetemp=...s08h02c5-02` -> `71 passed` (24.44s).
3. `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider --basetemp=...s08h02c5-03` -> `96 passed` (38.49s).
4. `python -m pytest tests/test_object_correction.py -q -p no:cacheprovider --basetemp=...s08h02c5-04` -> `34 passed` (21.64s) — C4/F4 no regression.
5. `S08T06_RUN_ID=s08h02c5-golden GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08h02c5-golden python -m pytest tests/test_s08_golden_object_intelligence.py tests/test_object_extraction_api.py tests/test_s08_r01_queued_cancel_lifecycle.py -q -p no:cacheprovider --basetemp=...s08h02c5-05` -> `27 passed` (55.65s). Golden metrics regenerated (gitignored).
6. `python -m ruff check app tests` -> `All checks passed!`
7. `python -m mypy app` -> `Success: no issues found in 88 source files`
8. `git diff --check` -> exit 0 (only pre-existing LF->CRLF advisories).
9. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh NEW Run ID) -> run **20260819-133623** -> **7/7 gates PASS, OVERALL exit 0** (Gate 2 pytest 600.78s exit 0; Gates 3-7 all exit 0).
10. Protected MAIN (read-only): channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; sam2.1_hiera_large.pt 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (mtime 2026-07-29 untouched). QA ports NO_LISTENERS on 3012/8888/8000/3000/5173/8027; no worktree-tied node processes.

### Final state
- `git status --short` = **173** (identical to baseline; output/ gitignored so quality-baseline + golden evidence invisible; no stray `.playwright-cli/` this round). Scope window (find app tests docs -newermt 12:00) = exactly app/services/video_probe.py, tests/test_s08_h02_security.py, the START_PROMPT_C5 packet doc (manager) + ROADMAP.md (manager, 12:21 — not written by me) + this LOG/REPORT. No reset/checkout/restore/clean/stash.
- REPORT.md appended CORRECTION ROUND C5 section; LOG and REPORT agree. **Status: SUBMITTED** (never self-approved; TASK.md / PM_REVIEW.md untouched; no commit/push/merge). S08 stays SPRINT_SUBMITTED; S07/S09 NOT started.

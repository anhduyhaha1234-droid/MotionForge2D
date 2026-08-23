# S08-H02-C3 — LOG (append-only)

## 2026-08-19 — Packet materialized by manager (pre-launch)

- run_started_at_local: 2026-08-19T03:35:16+07:00
- run_started_at_utc: 2026-08-18T20:35:16Z
- TASK.md / START_PROMPT.md created from Codex CHANGES_REQUESTED (S08-H02-C3:
  probe deadline concurrent drain, preset root symlink/junction containment,
  preset collision 409).
- Manager verified findings on disk: _run_ffprobe sequential stdout→stderr read
  (L104-105), safe_preset_* base=presets_dir.resolve() unanchored, slugify
  collapses !/? to same slug.
- Launcher: `output/run-s08-h02-c3.ps1` (NEW session, flash). Baseline git
  status 171, ports free, 0 writers. Session 20260818_020323_151164 NOT
  resumed (Codex mandate).

## 2026-08-19 — CORRECTION ROUND C3 executed (NEW session; NOT resuming 20260818_020323_151164)

### Hard worktree guard (before ANY write)
- `pwd` -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration  (OK)
- `git rev-parse --show-toplevel` -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration  (OK)
- `git branch --show-current` -> codex/s08-integration  (OK)
- `git status --short` snapshot = **172** entries (140 untracked `??`, 32 modified `M`) — dirty baseline INTENTIONAL; never reset/checkout/restore/clean/stash. (Manager's pre-launch note said 171; live measured 172 — count drift only, nothing reset.)
- Run timestamps (Codex protocol, NOT reused): run_started_at_local 2026-08-19T03:35:16+07:00; run_started_at_utc 2026-08-18T20:35:16Z. run_finished_* + elapsed_seconds appended at the end of this entry when all validation is done.

### Required reading (completed in READ-FIRST order)
- [x] `docs/pm/sessions/S08-H02-C3-probe-deadline-preset-root/TASK.md`
- [x] `docs/pm/sessions/S08-H02-local-api-origin-upload-safety/LOG.md` + `REPORT.md` (prior H02 history — append-only, preserved)
- [x] `app/services/video_probe.py` (whole file; `_run_ffprobe` L83-110 reads stdout then stderr SEQUENTIALLY via `_read_bounded`)
- [x] `app/workflow/preset_service.py` (`safe_preset_output_path` / `safe_preset_path` — base = presets_dir.resolve(), unanchored to project dir)
- [x] `app/api/routes/projects.py` preset save/apply routes (L1907-2029; calls resolver WITHOUT project_dir anchor)
- [x] `tests/test_s08_h02_security.py` (50 existing tests, all to be kept green)
- Env: `MOTIONFORGE_DATABASE_URL=[UNSET]`, Python 3.11.9, `app` imports OK.

### Protected pre-existing state (visible in baseline; NOT modified by this round)
All 172 baseline entries pre-date this session. This round only ADDS in-scope writes:
app/services/video_probe.py, app/workflow/preset_service.py, app/api/routes/projects.py,
tests/test_s08_h02_security.py, LOG.md, REPORT.md. No reset/checkout/restore/clean/stash.

### Plan (<=7 steps)
1. F1 `video_probe._run_ffprobe`: drain stdout+stderr CONCURRENTLY (reader threads), MAIN-thread deadline (blocking readline can no longer exceed it), COMBINED output cap, kill+reap full child on timeout/cap.
2. F2 `preset_service`: anchor BOTH the unresolved AND resolved presets root to the validated project dir in `safe_preset_output_path`/`safe_preset_path`; update the two project.py route calls to pass `proj_dir`.
3. F3 `preset_service`: preset collision — server-owned unique filename; never silently overwrite a DIFFERENT-named preset; same-name re-save = in-place update.
4. Append C3 tests: REAL-subprocess probe deadline (sleep 3s / timeout 0.2s -> <1s), stderr-then-stdout (no deadlock), over-cap line without newline (bounded fail), preset DIRECTORY junction outside (save+apply -> 422 zero side effect), collision `A!` then `A?`, normal save/list/apply still 200.
5. Run validation order 1-9 (focused `-k`; full h02; +test_api; cross-suite with golden env vars; ruff; mypy; git diff --check; fresh 7/7 quality baseline NEW Run ID; protected MAIN hashes + QA ports NO_LISTENERS).
6. Append CORRECTION ROUND C3 sections to LOG.md + REPORT.md (timestamps, exact commands, verbatim results, final status count, protected hashes, ports). Status: SUBMITTED (never APPROVED/CLOSED). Stop.


## 2026-08-19 — CORRECTION ROUND C3 executed — FULL VALIDATION + DOC-COMPLETE (this entry)

Run timestamps (Codex protocol):
- run_started_at_local: 2026-08-19T03:35:16+07:00
- run_started_at_utc: 2026-08-18T20:35:16Z
- run_finished_at_local: 2026-08-19T04:22:06+07:00
- run_finished_at_utc: 2026-08-18T21:22:06Z
- elapsed_seconds: 2810

### Implementation (3 findings closed; all in TASK.md allowed scope)
- F1 `app/services/video_probe.py`: `_run_ffprobe` drains stdout+stderr CONCURRENTLY (two daemon `_PipeReader` threads, 8KiB chunks); `_CaptureState` lock-protected COMBINED byte counter; MAIN thread poll loop enforces the deadline and the cap; on either, `_kill_proc` (kill+reap) the full child. Removed unused `_read_bounded`. Real-subprocess measurements: sleep-3s/0.2s -> TimeoutExpired 0.203s; stderr-64KiB-then-stdout -> rc=0/no-deadlock; >1MiB newline-less -> ProbeOutputTooLargeError 0.016s; combined cap -> bounded.
- F2 `app/workflow/preset_service.py`: `_assert_presets_root_contained(presets_dir, project_dir)` anchors BOTH unresolved and resolved presets root to the validated project dir; `safe_preset_output_path`/`safe_preset_path` now take `project_dir`. `app/api/routes/projects.py` passes `proj_dir` in save+apply. DIRECTORY symlink/junction relocation -> 422 save + 422 apply, zero side effects (test RAN on host, not skipped).
- F3 `app/workflow/preset_service.py`: `unique_preset_output_path` — server-owned unique filename (`A!`->a.json, `A?`->a-2.json); never overwrites a different-named preset; same-name re-save updates in place.

### Tests added (tests/test_s08_h02_security.py, +7; file now 57)
test_video_probe_deadline_enforced_real_child, test_video_probe_stderr_then_stdout_no_deadlock, test_video_probe_over_cap_line_without_newline_fails_closed, test_video_probe_combined_streams_cap_fails_closed, test_preset_root_directory_link_outside_rejected_422, test_preset_collision_distinct_names_same_slug_not_overwritten, test_preset_same_name_resave_updates_in_place.

### Validation (exact commands + verbatim results; -p no:cacheprovider; shallow basetemps C:/Users/Admin/AppData/Local/Temp/s08h02c3-*; MOTIONFORGE_DATABASE_URL unset)
1. `python -m pytest tests/test_s08_h02_security.py -k 'probe or preset or deadline or collision or junction' -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02c3-01` -> `23 passed, 34 deselected` (8.75s). New-only list: 7/7 PASSED.
2. `python -m pytest tests/test_s08_h02_security.py -q -p no:cacheprovider --basetemp=...s08h02c3-02` -> `57 passed` (23.26s); re-run final state `...03-02b` -> `57 passed` (24.62s).
3. `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider --basetemp=...s08h02c3-03` -> `82 passed` (36.92s).
4. `S08T06_RUN_ID=s08h02c3-golden GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08h02c3-golden python -m pytest tests/test_s08_golden_object_intelligence.py tests/test_s08_h02_security.py tests/test_object_extraction_api.py tests/test_s08_r01_queued_cancel_lifecycle.py -q -p no:cacheprovider --basetemp=...s08h02c3-04` -> `84 passed` (76.09s); re-run final state `...04b` -> `84 passed` (76.56s). Golden metrics output/s08-sprint/s08h02c3-golden/golden-metrics.json regenerated (gitignored).
5. `python -m ruff check app tests` -> `All checks passed!`
6. `python -m mypy app` -> `Success: no issues found in 88 source files` (fixed `_stored_preset_name` no-any-return mid-round).
7. `git diff --check` -> exit 0 (only pre-existing LF->CRLF advisories).
8. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh Run ID): run `20260819-035925` Gate 2 FAIL -> `1 failed, 1086 passed, 19 skipped` on `test_object_correction.py::test_concurrent_confirm_exactly_one_wins` — UNRELATED pre-existing timing flake (two-thread Barrier race; passes standalone 1/1, whole file 34/34, untouched by C3, and prior baselines 20260819-004409 + 20260819-015528 both passed Gate 2 with the same code). FRESH re-run run `20260819-041116` -> **7/7 PASS, OVERALL exit 0, BASELINE_EXIT=0** (Gate 2 585.3s exit 0; Gate 3 lint, Gate 4 typing, Gate 5 tsc, Gate 6 lint, Gate 7 build all exit 0).
9. Protected MAIN (read-only): channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; sam2.1 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318`. QA ports NO_LISTENERS (3012/8888/8000/3000/5173).

### Final state
- `git status --short` = **172** (identical to baseline; `output/` gitignored, so quality-baseline + golden evidence are invisible to git). Scope window (find app tests docs -newermt 03:35) = exactly video_probe.py, preset_service.py, projects.py, test_s08_h02_security.py + C3 packet docs. No reset/checkout/restore/clean/stash.
- REPORT.md appended CORRECTION ROUND C3 section; header Status set to SUBMITTED with real run timestamps. LOG and REPORT agree. **Status: SUBMITTED** (never self-approved; TASK.md / PM_REVIEW.md untouched; no commit/push/merge).

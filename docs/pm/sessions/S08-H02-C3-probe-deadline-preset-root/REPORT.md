# S08-H02-C3 — Probe deadline / Preset root containment / Preset collision: Implementation Report

**Status:** SUBMITTED (worker evidence below; manager/Codex sprint-exit review owns approval — never self-approve)
**Hermes session:** NEW session (Codex mandate — old 20260818_020323_151164 NOT resumed)
**Model:** ocg/deepseek-v4-flash (user directive 2026-08-17 — flash, no pro)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Task:** CORRECTION ROUND C3 (Codex CHANGES_REQUESTED on S08 — probe deadline,
preset root containment, preset collision)
**run_started_at_local:** 2026-08-19T03:35:16+07:00
**run_started_at_utc:** 2026-08-18T20:35:16Z
**run_finished_at_local:** 2026-08-19T04:22:06+07:00
**run_finished_at_utc:** 2026-08-18T21:22:06Z
**elapsed_seconds:** 2810


---

# CORRECTION ROUND C3 — Probe deadline / Preset root containment / Preset collision

**Status:** SUBMITTED (worker evidence below; manager/Codex sprint-exit review owns approval — never self-approve)
**Session:** NEW session (Codex mandate — do NOT resume 20260818_020323_151164). All findings manager-verified on disk before dispatch.
**Run timestamps:** run_started_at_local 2026-08-19T03:35:16+07:00 (UTC 2026-08-18T20:35:16Z); run_finished_at_local 2026-08-19T04:22:06+07:00 (UTC 2026-08-18T21:22:06Z); elapsed_seconds 2810.

Hard worktree guard verified before ANY write: pwd + `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`, branch = `codex/s08-integration`, baseline `git status --short` = 172 (140 untracked `??` + 32 modified `M`; dirty baseline INTENTIONAL — nothing reset/checkout/restore/clean/stashed).

## Finding 1 — `_run_ffprobe` blocking sequential drain (video_probe.py)

### Root cause
`_run_ffprobe` read stdout via `_read_bounded` then stderr SEQUENTIALLY (L104-105). `_read_bounded` checked the deadline only at the top of its loop, then performed a BLOCKING `readline()`. A child that produces no output (or a pipe whose other stream fills) blocks the call past the deadline — Codex repro: requested timeout 0.2 s, actual elapsed 3.016 s, `deadline_enforced=False`.

### Implementation
- Replaced the sequential read with two daemon reader threads (`_PipeReader` reading in 8 KiB chunks) draining stdout and stderr CONCURRENTLY — a full pipe can no longer stall the sibling stream.
- `_CaptureState` holds a lock-protected **combined** byte counter (stdout+stderr) against `PROBE_MAX_OUTPUT_BYTES`; the first stream to push the SUM over the ceiling sets `abort`.
- The MAIN thread owns both enforced conditions in a tight poll loop: on `abort` -> `ProbeOutputTooLargeError`; on deadline -> `subprocess.TimeoutExpired`; both paths `_kill_proc()` (proc.kill + bounded proc.wait) to reap the FULL child. Killing the child closes its pipe write-end, which unblocks any in-flight reader `read()`.
- Removed the now-unused `_read_bounded`.

### Evidence (REAL subprocess children, measured)
- Child sleeps 3 s, timeout 0.2 -> `TimeoutExpired` raised at **0.203 s** (< 1 s requirement) [test: `test_video_probe_deadline_enforced_real_child`].
- Child writes 65536 B to stderr BEFORE stdout -> rc=0, stdout=`done`, stderr=65536 B, **no deadlock** (0.015 s) [test: `test_video_probe_stderr_then_stdout_no_deadlock`].
- Child writes `PROBE_MAX_OUTPUT_BYTES+200000` 'x' with NO newline then sleeps 30 -> `ProbeOutputTooLargeError` at **0.016 s** (bounded) [test: `test_video_probe_over_cap_line_without_newline_fails_closed`].
- COMBINED cap: neither stream alone over the cap, sum over it -> `ProbeOutputTooLargeError` bounded [test: `test_video_probe_combined_streams_cap_fails_closed`].

## Finding 2 — preset root containment when `<project>/presets` is a symlink/junction

### Root cause
`safe_preset_output_path` / `safe_preset_path` computed `base = Path(presets_dir).resolve()` and proved containment relative to that base. If `<project>/presets` itself is a junction/symlink pointing OUTSIDE the project, `base` resolves outside and the per-file containment check passes for outside targets — the relocated root was implicitly trusted.

### Implementation (`app/workflow/preset_service.py`)
- New `_assert_presets_root_contained(presets_dir, project_dir)`: anchors BOTH the **unresolved** path AND the **resolved** path of the presets root inside the VALIDATED project directory (`project_dir.resolve()`; the caller already validated via `pwf._project_dir` + `_assert_contained`). A relocated root -> `InvalidPresetNameError` (stable 422) BEFORE any filesystem join.
- Both resolvers now take `project_dir` and call `_assert_presets_root_contained` at the top.
- `app/api/routes/projects.py`: `save_project_preset` and `apply_preset` pass `proj_dir` to the resolvers. No other callers exist.

### Evidence
New DIRECTORY-level test `test_preset_root_directory_link_outside_rejected_422` (created on this host — **ran, not skipped**): `<project>/presets` as a directory symlink AND junction (`mklink /J`) to an outside temp dir -> SAVE 422 and APPLY 422; outside sentinel byte-identical, no file written anywhere, project.json byte-identical, zero side effects. Existing file-level `test_preset_apply_symlink_escape_rejected` still green.

## Finding 3 — preset collision (A! and A? both slug to a.json)

### Root cause
`slugify_preset_name` strips `!`/`?` (non `[a-z0-9_-]` -> `_` -> stripped), so distinct display names collided on one JSON file and the second save silently overwrote the first.

### Implementation
- New `unique_preset_output_path(presets_dir, project_dir, display_name)` — **server-owned UNIQUE filename** (the finding allows "409 OR server-owned unique filename"): if the slugged file already exists and belongs to a DIFFERENT stored `name`, a numeric suffix is appended (`a.json` -> `a-2.json`, ...); the first preset is never overwritten. Re-saving the SAME display name updates its own file in place.
- `_stored_preset_name(path)` best-effort reads the existing file's `name`; an unreadable/foreign file is conservatively treated as a collision (never clobbered).
- `save_project_preset` now resolves via `unique_preset_output_path`.

### Evidence
`test_preset_collision_distinct_names_same_slug_not_overwritten`: save "A!" -> `a.json`; save "A?" -> `a-2.json`; `a.json` **byte-identical** after the second save; both listed; both apply 200. `test_preset_same_name_resave_updates_in_place`: "My Preset" twice -> same file, content updated (not duplicated). Existing `test_preset_valid_save_list_apply_succeeds` (save/list/apply), reserved-slug 422, hostile-name 422, traversal tests all still green.

## Files changed (all in scope)
- `app/services/video_probe.py` — concurrent drain, main-thread deadline, combined cap, full kill; removed `_read_bounded`.
- `app/workflow/preset_service.py` — `_assert_presets_root_contained`, `_stored_preset_name`, `unique_preset_output_path`; resolver signatures gained `project_dir`.
- `app/api/routes/projects.py` — preset save resolves via `unique_preset_output_path(presets_dir, proj_dir, ...)`; preset apply passes `proj_dir`.
- `tests/test_s08_h02_security.py` — +7 tests (probe deadline, stderr-then-stdout, over-cap no newline, combined cap, directory junction outside, collision, same-name re-save).
- This LOG.md / REPORT.md appendix.

Scope audit (mtime window from 03:35): only the four files above + the C3 packet docs were touched. `git status --short` final = **172** (identical to baseline; `output/` is gitignored so baseline/golden evidence invisible to git). No reset/checkout/restore/clean/stash.

## Validation (exact commands + verbatim results; fresh roots, `-p no:cacheprovider`, shallow basetemps `C:/Users/Admin/AppData/Local/Temp/s08h02c3-*`, env `MOTIONFORGE_DATABASE_URL` unset)
1. `python -m pytest tests/test_s08_h02_security.py -k 'probe or preset or deadline or collision or junction' -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02c3-01` -> **23 passed, 34 deselected** (8.75s). New-only (7): all PASSED — junction test RAN (not skipped).
2. `python -m pytest tests/test_s08_h02_security.py -q -p no:cacheprovider --basetemp=...s08h02c3-02` -> **57 passed** (23.26s); re-run after mypy fix (final state) -> **57 passed** (24.62s).
3. `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q ... s08h02c3-03` -> **82 passed** (36.92s).
4. Cross-suite `S08T06_RUN_ID=s08h02c3-golden GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08h02c3-golden python -m pytest tests/test_s08_golden_object_intelligence.py tests/test_s08_h02_security.py tests/test_object_extraction_api.py tests/test_s08_r01_queued_cancel_lifecycle.py -q ... s08h02c3-04` -> **84 passed** (76.09s); re-run on final state -> **84 passed** (76.56s). Golden metrics `output/s08-sprint/s08h02c3-golden/golden-metrics.json` (gitignored) regenerated green.
5. `python -m ruff check app tests` -> **All checks passed!**
6. `python -m mypy app` -> **Success: no issues found in 88 source files** (one `no-any-return` in `_stored_preset_name` fixed during the round).
7. `git diff --check` -> exit 0 (only pre-existing LF->CRLF advisories on files from earlier sprint tasks; no whitespace errors).
8. Quality baseline 7/7 (`scripts/quality-baseline.ps1`): first fresh run `20260819-035925` -> Gate 2 FAIL (1 failed, 1086 passed, 19 skipped: `test_object_correction.py::test_concurrent_confirm_exactly_one_wins`). THIS IS AN UNRELATED PRE-EXISTING TIMING FLAKE, not a C3 regression: the test is a two-thread Barrier exactly-one-wins race; it PASSES standalone (1 passed), PASSES its whole file (`tests/test_object_correction.py` -> 34 passed), was NOT touched by C3, and both prior baselines (`20260819-004409`, `20260819-015528`) passed Gate 2 with the SAME code + this test. FRESH re-run `20260819-041116` -> **7/7 PASS, OVERALL exit 0** (Gate 2 python suite 585.3 s exit 0; lint/typing/tsc/lint/build all exit 0), `BASELINE_EXIT=0`.
9. Protected MAIN (read-only) verified unchanged: channels.json SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318`. QA ports **NO_LISTENERS** on 3012/8888/8000/3000/5173.

## Deviations / limitations
- Collision resolved with a **server-owned unique filename** (`a-2.json`) rather than a 409 — explicitly permitted by the finding ("409 OR server-owned unique filename"). No silent overwrite of any existing preset.
- The combined cap is now shared across stdout+stderr (stricter than the C2 per-stream ceiling, per the finding's "COMBINED output cap"); normal probe output is far below the 1 MiB ceiling.
- `httpx`/`TestClient` normalizes a bare `../` segment client-side (same as prior rounds); the resolver's unit-level `_reject_hostile` covers the raw forms and the directory-junction test covers the root-relocation class.
- One quality-baseline run hit the unrelated flaky concurrency test; documented above, re-ran fresh to a clean 7/7. `test_object_correction.py` was deliberately NOT modified (out of scope; never weaken existing tests).

**Status: SUBMITTED.** No self-approval, no TASK.md / PM_REVIEW.md modification, no commit/push/merge/reset/clean/stash. S08 stays SPRINT_SUBMITTED. Old session 20260818_020323_151164 NOT resumed (Codex mandate).

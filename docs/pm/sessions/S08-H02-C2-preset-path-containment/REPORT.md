# S08-H02-C2 — Preset Path Containment: Implementation Report

**Status:** SUBMITTED (worker evidence below; manager/Codex sprint-exit review owns approval — never self-approve)
**Hermes session:** resume 20260818_020323_151164
**Model:** ocg/deepseek-v4-flash (user directive 2026-08-17 — flash, no pro)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Task:** CORRECTION ROUND C2 (Codex CHANGES_REQUESTED on S08 — preset path containment + video_probe output ceiling)

---

# CORRECTION ROUND C2 — Implementation

Hard worktree guard verified before any write: pwd/toplevel = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`, branch = `codex/s08-integration`, baseline `git status --short` = 170 (manager materialized the C2 packet → +1 over the documented 169; nothing reset/checkout/restore/clean/stash).

## Findings closed

### P1 #1 — save preset filename traversal
`save_project_preset` built the output path from client `body.name` with only `.lower().replace(' ', '_')` → `..\project` escaped `<project>/presets` and overwrote `project.json` (Codex reproduced 322 B → 118 B).

Fix: `body.name` is now DISPLAY-ONLY metadata (kept in the JSON under `name`). The FILE name is a strict server-validated slug produced by `safe_preset_output_path(presets_dir, display_name)`:
- rejects slash, backslash, `..`, dot-only (`.`/`..`/`....`), absolute, drive-qualified, control-byte (detected before null-stripping so `a\x00b` is refused), empty names and reserved slugs (`project.json` case-insensitive) with a stable 422 BEFORE any write;
- returns a target resolved with `Path.resolve(strict=False)` and proves it stays strictly under `<project>/presets`.
A normal save → `presets/<slug>.json` (e.g. `My Preset` → `my_preset.json`), still listed by `GET /presets` and appliable.

### P1 #2 — apply preset filename traversal
`apply_preset` joined the client `preset_filename` into `proj_dir / "presets" / preset_filename` unvalidated → could read `project.json` or arbitrary files outside presets via `..\` traversal.

Fix: `safe_preset_path(presets_dir, preset_filename)` requires a single safe segment ending in `.json`, rejects the same hostile class (slash/backslash/`..`/dot-only/absolute/drive/control), and rejects directory **and symlink/junction escape** by resolving the target (`resolve(strict=False)`) and proving it stays under `<project>/presets`. Hostile input → 422; well-formed-but-missing → 404; never 500.

### Secondary — video_probe unbounded parse
`probe_video` used `subprocess.run(capture_output=True)` + `-show_streams` → captured ALL stdout and parsed EVERY stream with no hard size ceiling (only a 30 s timeout).

Fix (`app/services/video_probe.py`):
- new bounded runner `_run_ffprobe(cmd, *, timeout)` — streams stdout/stderr line-buffered against a **hard `PROBE_MAX_OUTPUT_BYTES` (1 MiB)** ceiling and a deadline; exceeding either kills the process and raises `ProbeOutputTooLargeError` / `subprocess.TimeoutExpired` (fail closed);
- query only the REQUIRED fields for the FIRST relevant streams: `-select_streams v:0` + `-show_entries format=filename,duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames` (video) and a second bounded `-select_streams a:0` probe for audio existence/codec — no more full-stream dump;
- parse ceiling `PROBE_MAX_STREAMS` (4) + JSON-shape validation via `_bounded_json` — malformed/oversized probe output raises `RuntimeError`/`ProbeOutputTooLargeError`;
- valid-video metadata contract unchanged (width/height/fps/duration/total_frames/codec/has_audio/audio_codec/file_size_bytes/file_path), dimension caps retained; probe failure → route 415 with NO media published and NO project-state change (`test_video_upload_probe_failure_does_not_publish`).

### Rest-of-file audit (required, not stopped after the two lines)
All remaining client-controlled values that reach paths were verified safe:
- `body.name` (create_project) — display metadata only; `body.scene_id`/`frame_index`/selection — integers; `body.mask_data` — array into cv2, object dir is server UUID;
- `project_id`/`object_id` — validated by the centralized `_project_dir`/`object_dir` resolver before every join;
- replacement `asset_path`/`frame_sequence_dir` — rejected if absolute/`..` (C1) and served only under containment;
- preset character endpoints (`set_key`/`pose`) — fixed-dict keys resolved to spec-owned files, never client path segments.
The two preset joins were the only remaining client-controlled filesystem joins.

## Files changed (this round; all in declared scope)

| File | Change |
|---|---|
| `app/api/routes/projects.py` | `save_project_preset` uses `safe_preset_output_path` (hostile name → 422 before write; server slug filename; display name kept); `apply_preset` uses `safe_preset_path` (422 hostile / 404 missing, never 500); both validate `project_id` + `_assert_contained`. |
| `app/services/video_probe.py` | Bounded `_run_ffprobe` (1 MiB ceiling + deadline, fails closed), restricted `-select_streams`/`-show_entries` query, `PROBE_MAX_STREAMS` + JSON-shape checks, `_to_int`/`_to_float` safe parsing; `extract_audio` unchanged. |
| `app/workflow/preset_service.py` | `InvalidPresetNameError`, `_reject_hostile`, `slugify_preset_name`, `safe_preset_output_path`, `safe_preset_path` (central safe preset-path resolver). |
| `tests/test_s08_h02_security.py` | +13 C2 tests (save/apply traversal, reserved/hostile names, sentinel isolation, symlink escape, valid save/list/apply, video_probe bounded/malformed/stream-ceiling fail-closed, route-level no-publish on probe failure). |

Frontend NOT touched (backend-only round).

## Mandatory-test coverage

- save `..\project` and `../project` cannot overwrite project.json → `test_preset_save_traversal_names_cannot_overwrite_project_json` (422, project.json byte-identical).
- multi-level traversal cannot write outside project/presets → same test + `test_preset_save_isolated_sentinel_byte_identical`.
- isolated channels.json/sentinel remains byte-identical → `test_preset_save_isolated_sentinel_byte_identical`.
- absolute, drive-qualified, slash, backslash, dot, control-byte inputs → 422 → `test_preset_save_hostile_names_rejected_422` (incl. `a\x00b` now 422, not silently sanitized).
- reserved slug (project) → 422 case-insensitive → `test_preset_save_reserved_slug_rejected_422`.
- apply traversal cannot load project.json or sentinel outside presets → `test_preset_apply_traversal_cannot_load_project_json_or_sentinel`.
- resolved/symlink escape rejected (where supported) → `test_preset_apply_symlink_escape_rejected`.
- no new file appears outside presets → assertions in apply/save tests.
- valid save/list/apply still succeeds → `test_preset_valid_save_list_apply_succeeds` (`My Preset` → `my_preset.json`, listed, applied).
- all rejected requests have zero side effects and never 500 → `test_preset_rejected_requests_never_500`.
- video_probe bounded-output focused tests (oversized/malformed/stream-ceiling fail closed; route-level no-publish) → `test_video_probe_oversized_output_fails_closed`, `test_video_probe_malformed_output_fails_closed`, `test_video_probe_stream_ceiling_fails_closed`, `test_video_upload_probe_failure_does_not_publish`.

## Validation (exact commands + verbatim results; fresh isolated roots, `-p no:cacheprovider`, shallow basetemps `C:/Users/Admin/AppData/Local/Temp/s08h02c2-*`)

1. New preset/video_probe tests: `pytest tests/test_s08_h02_security.py -k "preset or video_probe or oversize or malformed or stream_ceiling"` → **20 passed** (9.75s).
2. Full `tests/test_s08_h02_security.py` → **50 passed** (21.92s).
3. `tests/test_s08_h02_security.py` + `tests/test_api.py` → **75 passed** (35.51s).
4. Cross-suite `test_s08_golden_object_intelligence.py + test_s08_h02_security.py + test_object_extraction_api.py + test_s08_r01_queued_cancel_lifecycle.py` (S08T06_RUN_ID=s08h02c2-golden, GOLDEN_TMP_ROOT isolated) → **77 passed** (76.25s); golden metrics `output/s08-sprint/s08h02c2-golden/golden-metrics.json` — the full vertical (real `app.main:app`, real public APIs, real legacy video upload through the bounded probe) is green.
5. `python -m ruff check app tests` → **All checks passed!**
6. `python -m mypy app` → **Success: no issues found in 88 source files**.
7. `git diff --check` → exit 0 (only pre-existing LF→CRLF advisories).
8. Frontend tsc/lint/build — backend-only round, frontend untouched by this writer; frontend gates are still exercised by the fresh 7/7 baseline (see 9) and pass.
9. Fresh quality baseline `20260819-015528` (scripts/quality-baseline.ps1) → **7/7 PASS** (Gate 2 python suite 581.82s exit 0; lint, typing, frontend tsc, lint, build all exit 0; OVERALL exit 0).
10. Protected MAIN (read-only) + QA ports: channels.json SHA `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; SAM2.1 898083611 B SHA `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (mtime 2026-07-29); QA ports **NO_LISTENERS**.

Final `git status --short` = 171 (baseline 170 + the golden evidence file `output/s08-sprint/s08h02c2-golden/golden-metrics.json`). No stray staging/publish temp files in the repo.

## Deviations / limitations

- httpx/TestClient normalizes a bare `../` URL segment client-side, so the APPLY tests exercise `..`-substring (`a..b.json`, `..\..\project.json` via `%5C`) and a literal `..%2F..%2Fproject.json` (accepted as 404-or-422 — both safe 4xx, never 500); full `../` coverage lives in the unit-level `_reject_hostile` checks and the save (body-name) tests.
- The symlink-escape test skips when the host lacks symlink privilege (Windows admin/dev-mode); the resolver's `resolve(strict=False)` containment is the enforcement.
- `video_probe` bounds capture by ceiling + deadline + restricted query; a pathological stream that emits no newlines for longer than the deadline is caught by the timeout (fail closed), which satisfies the bounded-output contract without platform-specific non-blocking pipe reads.

## Recovery/lineage

Resumed the OWN H02 session `20260818_020323_151164` per the manager-authored START_PROMPT (`docs/pm/sessions/S08-H02-C2-preset-path-containment/`). Prior H02 C1/C2 history in `S08-H02-local-api-origin-upload-safety/LOG.md` + `REPORT.md` preserved. LOG.md (this packet) now carries the matching CORRECTION ROUND C2 execution entry.

**Status: SUBMITTED.** No self-approval, no TASK.md / PM_REVIEW.md change, no commit/push/merge/reset/clean/stash. Sprint remains SPRINT_SUBMITTED.

# Execution Log — Task S05-T04

- [2026-08-05T09:5x:00+07:00] Session packet created. Scene detection durable job
  task initialized after S05-T03 manager verification passed.

## Session — 2026-08-05 (implementation + verification)

- **Worktree guard:** `pwd` = `/c/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`,
  `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01` —
  verified before ANY write (START_PROMPT hard guard).
- **Baseline `git status --short`:** pre-existing S05-T01/T02/T03 changes preserved
  (modified: `app/workflow/durable_worker.py`, `app/workflow/job_service.py`,
  `docs/pm/ROADMAP.md`; untracked: `app/services/timebase.py`, `app/services/video_import.py`,
  `app/services/video_proxy.py`, S05-T01/T02/T03 session + contract docs, `tests/`
  timebase/video_proxy/video_import suites, legacy fixture trees). Not touched.

## Design decisions (recorded before code)

1. **Job class reuse:** scene detection runs as the approved `ANALYZE_MEDIA`
   job class (DURABLE_JOB_CONTRACT §3 — the import/analyze class; WS-03 lists
   "Scene detection/keyframes" inside Import & Analyze). No new job type is
   invented (TASK.md: reuse an approved class or BLOCK). The step code is
   `scene_detect`, distinct from the S05-T02 `import` step. Because the
   durable worker dispatches by `job_type` (one handler per class), the
   registration installs one ANALYZE_MEDIA dispatcher: `import` steps run the
   approved S05-T02 `analyze_media_handler` unchanged; `scene_detect` steps
   run the new handler. Verified: S05-T02/T03 suites pass unchanged (30 + 55).
2. **Idempotency key:** `ANALYZE_MEDIA:scene_detect:video_item:<id>:<source_sha256>:<generation>`
   — owner-scoped, source-content-scoped, and namespaced away from the import
   key (`ANALYZE_MEDIA:video_item:...`), so the two logical runs never collide.
   Completed duplicate → same Job reused; active duplicate → `IdempotencyKeyInUse`;
   retry/restart of failed/cancelled → successor with same key+generation
   (created via the approved `JobRepository.create_successor` path).
3. **Stable Scene IDs:** rows committed in ONE transaction with deterministic
   ids `uuid5(NAMESPACE_OID, "scene-detect:<job_id>:<position>")` (§8.3). Replay
   reuses rows by evidence: a committed `published` checkpoint is verified
   row-by-row; the crash-window (rows committed, published checkpoint lost) is
   closed by reusing rows whose evidence exactly matches the detection spec.
   Rows from any other source fail closed `SCENE_EVIDENCE_CONFLICT` — never
   overwritten, never deleted. `legacy_scene_id` is always NULL.
4. **Canonical frame↔time:** cut `pts_time` parsed as exact decimal `Fraction`,
   mapped via `CanonicalTimebase.time_to_frame(round_half_up)`; row ms via
   `scene_ms_range` = exact rational round-half-up on `frame_to_time`, half-open
   interval `[t(start), t(end+1))` → `end_ms = round(t(end+1)*1000) - 1`, clamped.
   No binary float on any mapping path.
5. **Detection:** FFmpeg `select='gt(scene,TH)',showinfo` with list args only,
   discovery only via `ffmpeg_utils.find_ffmpeg`, bounded budget, polled against
   `ctx.is_cancelled()` — no PySceneDetect/OpenCV frame-byte reads (AC4).
6. **Timeout classification:** `SCENE_DETECT_TIMEOUT` is permanent in this task —
   adding it to `TRANSIENT_ERROR_CODES` would modify `app/workflow/durable_worker.py`,
   which is OUTSIDE the TASK.md allowed write scope (unlike S05-T03, whose scope
   allowed that file). The stable code + clean rollback satisfy AC3; a transient
   classification would need an approved scope extension.

## Implementation log

- [2026-08-05] `app/services/scene_detector.py` created (~1,139 lines) —
  `submit_scene_detection`, `scene_detection_handler` (input → detect → publish,
  checkpoint-resumable), `SceneDetectionProfile`, `SceneDetectorError` + stable
  codes + Vietnamese actions, `scene_ms_range` / `cuts_to_scenes` exact-rational
  helpers, `_run_scene_detect` (bounded/cancellable FFmpeg), one-transaction
  `_commit_scene_rows`, `register_scene_detection_handler` (ANALYZE_MEDIA
  dispatcher). No modification to `video_import.py` / `timebase.py` /
  `video_proxy.py` (forbidden scope).
- [2026-08-05] `app/workflow/job_service.py` — ANALYZE_MEDIA registration
  swapped from the plain S05-T02 handler to the S05-T04 dispatcher (import step
  delegates to the identical S05-T02 handler; `register_analyze_media_handler`
  import removed). This is the "registration in job_service.py if a new handler
  is needed" item of the allowed write scope.
- [2026-08-05] `tests/test_scene_detection.py` created (26 tests) — success
  (CFR cut video), single-scene, canonical-timebase recomputation (30fps /
  NTSC 30000/1001 / real VFR), proxy consumption, source fallback, idempotency
  (active/completed/key shape), retry checkpoint reuse (1 FFmpeg run),
  crash-window reuse (same ids, revision untouched), successor no-duplicate,
  successor reuse after failure, deterministic ids, INPUT_CHANGED fail-closed,
  cancel drain, failure envelope, timeout permanent + cleanup, foreign-row
  conflict, submit-time rejections, no-absolute-path checkpoint, source+proxy
  byte immutability, exact-ms unit tests.

## Defects found & fixed during the session

- Test harness: `sleeper.__call__` instance-attribute patching does not
  intercept the call operator — the INPUT_CHANGED retry side effect never ran
  and the test completed instead of failing. Fixed by patching the worker's
  `_sleeper` attribute (the worker's actual call site). Proven by the test.
- Test harness: successor tests initially re-submitted with the same key, but
  the repository's `create_job` raises `IdempotencyKeyInUse` for a failed
  predecessor (successors are created through the approved
  `JobRepository.create_successor` path, exactly like S05-T03's suite).
  Tests updated to the approved successor path.
- Ruff: E501/F401/F841 in the new files fixed; `ruff format` applied to the two
  new files. Mypy: loop-variable type clash in `_commit_scene_rows` fixed
  (`existing_row` rename).

## Validation results (each separately, real output)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q tests/test_scene_detection.py -p no:cacheprovider` | PASS — **26 passed** in 15.1s |
| 2 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py -p no:cacheprovider` | PASS — **55 passed** in 14.6s (S05-T03 regressions) |
| 3 | `python -m pytest -q tests/test_video_import.py -p no:cacheprovider` | PASS — **30 passed** in 11.8s (S05-T02 regressions) |
| 4 | `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS — **184 passed, 2 skipped** in 43.2s (worker/job/persistence/reconciliation/artifact regressions) |
| 5 | `python -m ruff check app tests` | PASS — `All checks passed!` (after E501/F401/F841 fixes) |
| 6 | `python -m mypy app` | PASS — `Success: no issues found in 65 source files` |
| 7 | `git diff --check` | PASS — exit 0 (LF→CRLF advisory only on `docs/pm/ROADMAP.md`, pre-existing) |
| 8 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh) | PASS — **OVERALL: PASS (exit 0)**, Run ID **`20260805-102654`**; 7/7 gates; Python tests **686 passed, 19 skipped, 7 deselected** in 157.5s (includes the 26 new S05-T04 tests). Summary: `output/quality-baseline/20260805-102654/summary.json` |

## AC4 grep evidence (no deprecated frame access)

- `grep -nE "scenedetect|open_video|cv2|imread|read_bytes\(\)|\.frames\[" app/services/scene_detector.py` → **no matches** (exit 1).
- `grep -n "legacy_scene_id" app/services/scene_detector.py` → only `legacy_scene_id=None` on insert (never used for frame math; the deprecated `app/services/scene_detection.py` module is untouched).

## Baseline (before implementation) — preserved uncommitted changes

- `git status --short` captured before any write; every pre-existing
  modification/untracked file (S05-T01/T02/T03 artifacts, PM-owned ROADMAP
  diff, legacy fixture trees) remains byte-identical (see REPORT.md
  containment evidence).

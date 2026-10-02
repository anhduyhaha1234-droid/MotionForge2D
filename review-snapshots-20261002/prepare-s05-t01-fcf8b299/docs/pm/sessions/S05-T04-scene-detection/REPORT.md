# S05-T04 - Implementation Report

**Status:** SUBMITTED
**Started:** 2026-08-05 +07:00
**Submitted:** 2026-08-05 +07:00
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`

## Outcome delivered

A durable/checkpointed scene-detection job that **reuses the approved
`ANALYZE_MEDIA` job class** (DURABLE_JOB_CONTRACT §3 — the import/analyze
class; WS-03 lists "Scene detection/keyframes" inside Import & Analyze; no
new job type was invented) with a distinct `scene_detect` step. The job
consumes the S05-T03 canonical timebase (exact rational grid, CFR →
`r_frame_rate`, VFR → `avg_frame_rate`) and the managed `ready` proxy
artifact (falling back to the managed source when the proxy is unusable —
never raw files outside managed containment). Scene cuts are detected with
FFmpeg's `scene` filter + `showinfo` (list args only, discovery only via
`ffmpeg_utils.find_ffmpeg`, bounded budget, cancellable) — **no
PySceneDetect/OpenCV frame-byte reads** (the deprecated
`app/services/scene_detection.py` path is not used and `legacy_scene_id` is
never written). Scene rows are committed **in one transaction** with
deterministic ids (`uuid5("scene-detect:<job_id>:<position>")`), canonical
zero-based inclusive `start_frame`/`end_frame` and integer-ms
`start_time_ms`/`end_time_ms` derived by exact rational arithmetic
(round-half-up on `frame_to_time`, half-open interval, clamped) — never
float drift. Retry/replay/restart create no duplicate rows: the same job's
retry reuses the detection checkpoint (exactly one FFmpeg run), the
crash-window (rows committed, published checkpoint lost) reuses rows by
evidence, and a successor reuses committed rows with identical scene ids.
Cancel/failure/timeout/DB rollback leave zero partial rows; committed rows
survive. Rows from any other source (legacy/foreign) fail closed with
`SCENE_EVIDENCE_CONFLICT` — never overwritten, never deleted. Source and
proxy artifacts are byte-identical after detection; no absolute managed path
is persisted. **No schema change** — the write surface is exactly the
existing `scene` table.

## Job-class decision (TASK.md outcome scope)

TASK.md: "reuse an existing approved class from `DURABLE_JOB_CONTRACT.md` §3
if one fits; otherwise the task is BLOCKED pending contract change — do not
invent a new class without approval." Of the 14 approved classes, only
`ANALYZE_MEDIA` fits scene detection semantically (WS-03: scene
detection/keyframes is a deliverable of Import & Analyze; MASTER_PLAN_V1
§7.2). Because the durable worker dispatches handlers by `job_type` (one
handler per class), registration installs **one ANALYZE_MEDIA dispatcher**
(`app/services/scene_detector.py::register_scene_detection_handler`):
`import` steps run the approved S05-T02 `analyze_media_handler` **unchanged**
(verified: the 30-test S05-T02 suite and 55-test S05-T03 suite pass
untouched), `scene_detect` steps run the new handler. Idempotency key:
`ANALYZE_MEDIA:scene_detect:video_item:<video_item_id>:<source_sha256>:<generation>`
— namespaced away from the import key, owner-scoped, source-content-scoped.

## Changed files (allowed write scope only)

- `app/services/scene_detector.py` (new, ~1,139 lines) — submit, handler
  (input → detect → publish, checkpoint-resumable), profile, stable error
  codes + Vietnamese actions, exact-rational ms/scene helpers, bounded
  cancellable FFmpeg detection, one-transaction scene commit, ANALYZE_MEDIA
  dispatcher registration.
- `app/workflow/job_service.py` (modified — the task's "Registration in
  `app/workflow/job_service.py` if a new handler is needed") — ANALYZE_MEDIA
  registration swapped to the S05-T04 dispatcher; the import step delegates
  to the identical S05-T02 handler (the now-unused
  `register_analyze_media_handler` import was removed). Pre-existing
  S05-T02/T03 modifications to this file preserved.
- `tests/test_scene_detection.py` (new, 26 tests).
- `docs/pm/sessions/S05-T04-scene-detection/LOG.md` (appended), `REPORT.md`
  (this file).

Untouched (verified by `git status --short` + this session's write history):
`app/services/video_import.py`, `app/services/timebase.py`,
`app/services/video_proxy.py` (forbidden scope — zero writes), plus
`app/workflow/durable_worker.py` (its diff contains only the pre-existing
S05-T02/T03 `PROBE_TIMEOUT`/`PROXY_TIMEOUT` + classification changes — this
task added nothing), PRD/MP/ROADMAP (PM-owned activation diff preserved),
migrations, `pyproject.toml`/lockfiles, frontend, database files,
`channels.json`, `data/`, user data, MAIN tree, S06 worktrees.

## Tests and validation (each separately, exact commands/results)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q tests/test_scene_detection.py -p no:cacheprovider` | PASS — **26 passed** in 15.1s |
| 2 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py -p no:cacheprovider` | PASS — **55 passed** in 14.6s (S05-T03 regressions) |
| 3 | `python -m pytest -q tests/test_video_import.py -p no:cacheprovider` | PASS — **30 passed** in 11.8s (S05-T02 regressions) |
| 4 | `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS — **184 passed, 2 skipped** in 43.2s (worker/job/persistence/reconciliation/artifact regressions) |
| 5 | `python -m ruff check app tests` | PASS — `All checks passed!` |
| 6 | `python -m mypy app` | PASS — `Success: no issues found in 65 source files` |
| 7 | `git diff --check` | PASS — exit 0 (LF→CRLF advisory only on `docs/pm/ROADMAP.md`, pre-existing) |
| 8 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh) | PASS — **OVERALL: PASS (exit 0)**, Run ID **`20260805-102654`**; 7/7 gates; Python tests **686 passed, 19 skipped, 7 deselected** in 157.5s (includes the 26 new S05-T04 tests; S05-T03 baseline was 660 → +26). Summary: `output/quality-baseline/20260805-102654/summary.json` |

## Acceptance criteria evidence

| AC | Status | Evidence |
|---|---|---|
| AC1 durable/checkpointed job, no duplicate rows on retry/replay/restart | PASS | `test_retry_reuses_detection_checkpoint_no_second_ffmpeg` (transient failure after the detection checkpoint → same job's retry reuses it, **exactly 1 FFmpeg invocation**, 2 rows); `test_crash_window_reuses_committed_rows` (rows committed + published checkpoint lost → retry reuses by evidence, same ids, `revision == 1` untouched); `test_successor_no_duplicate_scene_rows` (failed predecessor → successor via `JobRepository.create_successor`, same key/generation → completed, 2 Job rows, **one** 2-row effect set); `test_successor_reuses_committed_rows_after_failure` (rows committed then permanent failure → successor reuses them, **identical scene ids**); `test_scene_ids_deterministic` (ids = `uuid5(NAMESPACE_OID, "scene-detect:<job_id>:<position>")`); `test_duplicate_submit_active_raises_idempotency_key_in_use`; `test_duplicate_submit_completed_reuses_same_job` (same Job, `reused=True`, one effect set); `test_owner_scoped_key_shape` (`ANALYZE_MEDIA:scene_detect:video_item:<id>:<sha>:<gen>`, ≠ import key, step code `scene_detect`) |
| AC2 scene rows: position unique/video, start ≤ end, zero-based inclusive frames, integer ms from rational timebase | PASS | `test_detect_success_cfr_publishes_scene_rows` (cut video → rows `(0,29)/(30,59)` frames, `(0,999)/(1000,1999)` ms, positions `[0,1]`, status `pending`, `revision 1`, `legacy_scene_id NULL`); `test_scene_times_match_canonical_timebase_payload` (every row's ms == `scene_ms_range` recomputed from the persisted `to_json()` payload); `test_ntsc_rational_grid_exact_ms` (30000/1001: cut frame starts at **exactly 1001 ms**, all rows recompute exactly); `test_vfr_source_detection_exact_rational` (real VFR fixture classified VFR, rows recompute exactly from `avg_frame_rate` grid, unique positions, frames in range); `test_unit_scene_ms_range_exact` (30fps / NTSC / VFR / single-frame, round-half-up, clamp); `test_unit_cuts_to_scenes` (min-length merge, tail merge, dedupe, clamp, single scene) |
| AC3 cancel/failure/timeout/rollback removes partial staging; committed rows survive; no orphans | PASS | `test_cancel_drains_with_zero_scene_rows` (terminal `cancelled`, 0 rows, no staging leftovers); `test_failure_stable_code_and_zero_rows` (`SCENE_DETECT_FAILED`, class permanent, 0 rows, staging clean); `test_timeout_fails_permanent_and_cleans` (`SCENE_DETECT_TIMEOUT`, 0 rows, staging clean); `test_input_changed_fails_closed` (`INPUT_CHANGED`, 0 rows, checkpoint evidence intact); `test_foreign_scene_rows_fail_closed_conflict` (`SCENE_EVIDENCE_CONFLICT`, foreign row **untouched**); rollback-or-survive proven by `test_crash_window_reuses_committed_rows` / `test_successor_reuses_committed_rows_after_failure` (committed rows survive every later failure) |
| AC4 no deprecated frame access | PASS | `grep -nE "scenedetect\|open_video\|cv2\|imread\|read_bytes()\|\.frames\[" app/services/scene_detector.py` → **no matches**; `grep -n "legacy_scene_id" app/services/scene_detector.py` → only `legacy_scene_id=None` on insert — never used for frame math; the deprecated `app/services/scene_detection.py` module is untouched; detection runs FFmpeg only via `ffmpeg_utils.find_ffmpeg` |
| AC5 source + proxy unmodified (SHA-256/size) | PASS | `test_source_and_proxy_artifacts_unmodified` (source + proxy bytes/size/row sha identical after a completed detection); `test_detect_success_cfr_publishes_scene_rows` (source artifact sha/size asserted); `test_detection_checkpoint_has_no_absolute_path` (no managed-root path, no drive letter in durable JSON); `sha256sum channels.json` = `f17412a2d90a639ac6191fe124ee2026aa5178290e04a309361bc90683efb027` (untouched); `git status --short` shows only the allowed files |
| AC6 ruff/mypy/diff-check + focused tests + S05-T02/T03 regressions + fresh baseline 7/7 | PASS | Items 1–8 above; baseline run **`20260805-102654`** = OVERALL PASS (exit 0), 7/7 gates |

## Stable-Scene-ID evidence (idempotency/replay/restart)

- **Deterministic ids:** `uuid5(NAMESPACE_OID, f"scene-detect:{ctx.job_id}:{position}")`
  (contract §8.3 "deterministic ids from (job_id, step_code, chunk_index)").
- **Same-job retry:** the step checkpoint persists input evidence + detection
  (cuts, timebase payload, scene specs); a retry reuses the checkpoint when
  the input still matches (file exists + size), so detection runs exactly
  once (`test_retry_reuses_detection_checkpoint_no_second_ffmpeg`).
- **Crash window closed:** rows are committed in ONE transaction; a crash
  after commit but before the `published` checkpoint is recovered by reusing
  rows whose evidence exactly matches the spec — same ids, `revision`
  untouched (`test_crash_window_reuses_committed_rows`).
- **Successor:** a retry of a failed Job is a successor (approved
  `create_successor` path, same key + generation); the publish phase is
  idempotent — committed rows are reused by evidence with identical ids
  (`test_successor_no_duplicate_scene_rows`,
  `test_successor_reuses_committed_rows_after_failure`).
- **Completed reuse:** a completed duplicate returns the existing Job
  (`reused=True`); an active duplicate raises `IdempotencyKeyInUse`.

## Canonical timebase evidence (frame↔time mapping, CFR/VFR)

- CFR 30fps: cut frame 30 → `start_time_ms=1000`, end of scene 1 = `999`
  (exact `t(30)=1.000s`, half-open `-1` ms).
- NTSC 30000/1001: cut frame 30 → `start_time_ms=1001` (exact
  `t(30) = 30×1001/30000 = 1.001s`), end of scene 1 = `1000`.
- VFR (real concat fixture, `avg_frame_rate` grid): every row's ms range
  recomputed from the persisted schema-versioned timebase payload equals the
  row exactly (`test_vfr_source_detection_exact_rational`).
- Mapping path: `pts_time` parsed as exact decimal `Fraction` →
  `CanonicalTimebase.time_to_frame(round_half_up)` → exact integer frame;
  ms via `round_half_up(frame_to_time × 1000)` (exact integer math, no
  binary float anywhere in the module).

## Cleanup evidence (cancel/failure/rollback/orphan)

- Detection writes no staging files (FFmpeg `-f null -`); `_staging_files`
  is empty after every terminal path.
- Cancel mid-detection → `CANCELLED` → worker drains → terminal `cancelled`,
  0 rows.
- Failure → `SCENE_DETECT_FAILED` (permanent envelope with
  `details.returncode`), 0 rows.
- Timeout → `SCENE_DETECT_TIMEOUT` (permanent; see deviation note), 0 rows.
- DB rollback: the single scene-row transaction either commits all rows or
  none — a partial attempt leaves zero rows; committed rows survive all
  later failures (crash-window + successor tests).
- No orphan rows: rows from any other source (legacy/foreign) fail closed
  `SCENE_EVIDENCE_CONFLICT` and are never deleted or overwritten.

## Containment/SHA evidence

- Source + proxy artifact files: byte-identical before/after detection
  (sha256 + size asserted in tests).
- `channels.json`: sha256 `f17412a2d90a639ac6191fe124ee2026aa5178290e04a309361bc90683efb027`
  (untouched; no write was made to it).
- No absolute managed path in checkpoints (test asserts no managed-root
  string and no drive letter in the durable JSON).
- `git status --short` final: modified `app/workflow/durable_worker.py`
  (pre-existing), `app/workflow/job_service.py` (pre-existing + this task's
  registration), `docs/pm/ROADMAP.md` (PM-owned); untracked = the allowed
  S05-T01..T04 files + pre-existing fixtures. No stray files.

## Deviations from task

1. **`SCENE_DETECT_TIMEOUT` is classified permanent** (job fails with a
   stable envelope; no auto-retry). TASK.md's allowed write scope does NOT
   include `app/workflow/durable_worker.py`, so the
   `TRANSIENT_ERROR_CODES` addition used by S05-T02 (`PROBE_TIMEOUT`) and
   S05-T03 (`PROXY_TIMEOUT`) is not available here; the task explicitly
   forbids modifying that file. AC3 is still satisfied (clean terminal
   failure, zero rows, staging clean, successor retry possible). If a
   transient classification is desired, it requires an approved scope
   extension or a follow-up task.
2. **No new job type**: `ANALYZE_MEDIA` reuse per TASK.md outcome scope;
   the registration change in `job_service.py` is exactly the allowed
   "Registration ... if a new handler is needed" item.
3. Everything else follows the approved patterns: owner-scoped idempotency
   (S05-T03), run-time re-validation + deterministic-id upsert + created-file
   guards (S05-T02 corrections), one-transaction publication, checkpoint
   reuse, Vietnamese actions on every stable code.

## Known limitations/risks

- The FFmpeg `showinfo` `pts_time` is printed with microsecond precision;
  the mapping itself is exact rational arithmetic, and the residual
  quantization is bounded at 0.5 µs (≈ 0.000015 frames at 30 fps) — the
  round-half-up frame recovery is exact for every realistic cut boundary and
  fully deterministic across retries.
- The detection profile defaults (threshold 0.3, min scene 15 frames) mirror
  the legacy defaults; tuning is a later PM/product decision.
- A proxy whose row becomes invalid at run time falls back to the source
  (task contract); a replay whose input identity changed fails closed with
  `INPUT_CHANGED` instead of silently re-detecting against different bytes.

## Recommended PM decision

`PENDING` — awaiting PM review per protocol (no self-approval; no commit; no
roadmap edits; no next-task packet creation).

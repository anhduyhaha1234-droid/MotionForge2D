# S05-T02 - Implementation Report

**Status:** SUBMITTED
**Hermes session:** 20260804_180016_93cf8b
**Started:** 2026-08-04 18:02 +07:00
**Submitted:** 2026-08-04 18:34 +07:00

## Outcome delivered

The managed import service `app/services/video_import.py` (new) implements the approved `ANALYZE_MEDIA` durable job per `VIDEO_PREFLIGHT_CONTRACT.md` §6 with the `VIDEO_IMPORT_V1_PM_DECISIONS.md` resolutions. A source video is streamed/copied into `ManagedRoot` (SHA-256 and size computed during the copy, `expected_sha256` abort-before-publish), atomically published as a `ready` Artifact, linked as the VideoItem source (`artifact_owner` purpose `source`) and the existing probe metadata (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) is persisted **in one transaction/job effect**. Idempotent retry/restart never duplicates artifacts or orphan files; cancellation/failure cleans staging/partial files; path containment is enforced and the original source is never mutated or deleted. **No new schema** — the write surface is exactly the existing `artifact`, `artifact_owner` and `video_item` tables. No API routes, no frontend, no canonical proxy/timebase (T03), no production data, no `channels.json`.

**Implementation summary:**

1. **Submit** (`submit_import`) — validates the source exists/readable, builds the versioned manifest and creates the durable Job with idempotency key `ANALYZE_MEDIA:<source_sha256>:<generation>` (contract §8.1). A completed duplicate returns the existing Job (`reused=True`); an active duplicate raises `IdempotencyKeyInUse`. The request path never hashes the file (V1 PM decision #5); the preflight hash is verified during the copy.
2. **Probe phase** — bounded ffprobe (30s, list-args, `-v quiet`, JSON, discovery only via `ffmpeg_utils`), schema-versioned canonical payload (container, video stream with rational fps + CFR/VFR classification, audio stream, has_audio, warnings, sha256, display-only file_path), V1 media decision (MP4 container; H.264/HEVC video; AAC or no audio; HDR/10-bit rejected; positive duration/width/height + valid fps rational). `NO_AUDIO_STREAM` is a recorded warning, not a blocker. The probe result is persisted as the step checkpoint and reused on retry (never re-probes).
3. **Copy phase** — free-disk guard (`source_size × 1.1 + 1 GiB` reserve, `INSUFFICIENT_DISK`) before any byte; streaming copy into the managed staging area via `ManagedRoot.atomic_write_stream` with `expected_sha256` (mismatch → `CHECKSUM_MISMATCH`, abort-before-publish); crash-leftover `.staging` partials (including a predecessor Job's) garbage-collected on re-run.
4. **Publish phase** — atomic `os.replace` of the staged file into `artifacts/<workspace_id>/video/<job_id>/<step_code>/<name>`, then **one transaction**: deterministic-id upsert of the `artifact` row (`kind='video'`, `state='ready'`, sha256, size, relative path), upsert of the `artifact_owner` link (purpose `source`), and the `video_item` probe columns + `source_artifact_id`. A DB failure removes the just-published file (no orphan); a replay finds the ready row and skips publication (no duplicate effects).
5. **Cancellation/failure cleanup** — every phase observes `ctx.is_cancelled()` and removes its staging/partial files before raising `CANCELLED`; the worker drains to terminal `cancelled` with no final outputs.
6. **Path containment** — every managed path goes through `ManagedRoot`; `ManagedPathError` maps to the stable `PATH_CONTAINMENT` envelope. The source is opened read-only and never mutated/deleted.

**Minimal durable-worker support (backward compatible):** `WorkerContext.session_factory` (optional) threaded through `_make_context`/`build_worker_context` so handlers can persist durable step effects; `PROBE_TIMEOUT` added to `TRANSIENT_ERROR_CODES` (contract §6.1/§7 — the probe budget exhaustion is auto-retried); `_classify_error` now preserves structured exception `details` in the envelope (machine-readable taxonomy context survives classification). `app/workflow/job_service.py` registers the ANALYZE_MEDIA handler on every JobService-owned worker.

**Stable error codes used (contract §7 taxonomy + V1 PM resolutions):** `INPUT_MISSING`, `INPUT_UNREADABLE`, `NO_VIDEO_STREAM`, `UNSUPPORTED_CONTAINER`, `UNSUPPORTED_CODEC` (reused durable permanent), `UNSUPPORTED_AUDIO_CODEC`, `NO_AUDIO_STREAM` (warning), `PROBE_TIMEOUT` (transient), `PROBE_BINARY_NOT_FOUND`, `PROBE_NONZERO_EXIT`, `PROBE_JSON_PARSE_ERROR`, `CHECKSUM_MISMATCH`, `INSUFFICIENT_DISK`, `HDR_UNSUPPORTED`, `INVALID_VIDEO_METADATA`, `PATH_CONTAINMENT`, `VIDEO_ITEM_NOT_FOUND`, `PUBLICATION_FAILED`, `CANCELLED`. Every code carries severity/location/reason and a Vietnamese suggested action (PRD §9 Step 5 / FR-08) — never a bare "failed".

## Acceptance criteria evidence

| AC | Status | Evidence |
|---|---|---|
| AC1 service + ANALYZE_MEDIA handler with phases, checkpoint resume, idempotent publication, stable taxonomy | PASS | `app/services/video_import.py` (new): `submit_import`, `analyze_media_handler` (probe→copy→publish), `probe_source`, `_check_disk_space`, `_publish_effect`; 19 stable codes with Vietnamese actions; `register_analyze_media_handler` wired in `app/workflow/job_service.py`. |
| AC2 success path: completed; one ready video Artifact; source owner link; probe columns; file bytes identical; source unchanged | PASS | `test_success_import_publishes_ready_source_artifact`, `test_checksum_and_size_recorded_from_copy`, `test_original_source_never_mutated_or_deleted` (all green — 19 passed). |
| AC3 duplicate/idempotent submit: active → `IdempotencyKeyInUse`; completed → same Job reused; one effect set | PASS | `test_duplicate_submit_single_effect_set` asserts exactly 1 Job row, 1 Artifact, 1 managed file after the reuse submit. |
| AC4 copy failure / DB rollback / cancellation clean staging and partials (no `.staging`, no orphan final files, no ready rows without files) | PASS | `test_copy_failure_cleans_staging_and_fails`, `test_db_rollback_orphan_cleanup`, `test_cancellation_drains_and_cleans_staging` (assert `_artifact_rows == []`, `_artifact_files == []`, `_staging_files == []`). |
| AC5 path escape / symlink containment → `PATH_CONTAINMENT`, nothing outside root, source untouched | PASS | `test_sanitize_name_removes_traversal_components` (name sanitization + `ManagedRoot` traversal rejection), `test_symlink_escape_rejected_and_nothing_written_outside` (symlink → `PATH_CONTAINMENT`, outside dir empty, staged copy removed). |
| AC6 insufficient disk rejected before copy with `INSUFFICIENT_DISK` | PASS | `test_insufficient_disk_rejected_before_copy` (monkeypatched `_disk_free_bytes` = 0; envelope carries `details.required_bytes`, `free_bytes`, `source_size_bytes`). |
| AC7 unsupported V1 media decisions fail closed with exact codes; `NO_AUDIO_STREAM` accepted with warning | PASS | `test_unsupported_media_fails_closed` (parametrized: mkv→`UNSUPPORTED_CONTAINER`, mpeg4→`UNSUPPORTED_CODEC`, libmp3lame→`UNSUPPORTED_AUDIO_CODEC`, yuv420p10le→`HDR_UNSUPPORTED`); `test_no_audio_stream_is_accepted_with_warning` (job completed, checkpoint probe `warnings` contains `NO_AUDIO_STREAM`, no new `has_audio` durable column — verified via `PRAGMA table_info`). |
| AC8 restart recovery: successor re-runs from checkpoint, completes without duplicate artifacts, cleans crash leftovers | PASS | `test_restart_recovery_successor_no_duplicate_artifacts` (crash partial `.crash.staging` left by failed attempt; successor via `create_successor` with same key/generation completes; exactly 1 Artifact + 1 file; predecessor partial cleaned). |
| AC9 no new schema/migration/API/frontend; no production data / `channels.json` / unrelated files | PASS | No migration added; `git status --short` shows only `app/services/video_import.py`, `tests/test_video_import.py`, `docs/pm/sessions/S05-T02-managed-import/` (new) + `app/workflow/durable_worker.py`, `app/workflow/job_service.py` (modified) + pre-existing PM/untracked items (ROADMAP activation diff, S05-T01 contract+packet, legacy-import fixture dirs) — none of the pre-existing items touched by this session. No `channels.json`/`data/`/DB/user-data changes. |
| AC10 targeted tests, ruff, mypy, `git diff --check`, fresh 7/7 baseline | PASS | See "Tests and validation" below. |

## Files changed

- `app/services/video_import.py` (new — the managed import service + `ANALYZE_MEDIA` handler; ~1,100 lines).
- `tests/test_video_import.py` (new — 19 targeted tests; tmp DB + tmp managed root + lavfi synthetic fixtures; skip when ffmpeg absent).
- `app/workflow/durable_worker.py` (minimal: optional `session_factory` on `WorkerContext`; `PROBE_TIMEOUT` → `TRANSIENT_ERROR_CODES`; `_classify_error` preserves structured details).
- `app/workflow/job_service.py` (register the ANALYZE_MEDIA handler).
- `docs/pm/sessions/S05-T02-managed-import/LOG.md` (appended entries), `REPORT.md` (this file, status SUBMITTED).

Untouched (verified by `git status`): ROADMAP (pre-existing PM activation diff — not modified by this session), all other `app/` source, migrations, `pyproject.toml`/lockfiles, frontend source, tracked fixtures/tests, database files, `channels.json`, `data/`, user data, the primary worktree `C:\Users\Admin\MotionForge2D`.

## Architecture/schema/API impact

- **Schema/migration:** none. The existing `artifact` (workspace_id/relative_path unique, kind/state CHECKs), `artifact_owner` (composite PK, purpose) and `video_item` (probe columns + CHECK constraints) tables are the complete write surface.
- **API:** none. Probe columns remain read-only at the API; S05-T02's import path is the approved writer (VIDEO_ITEM_API §5 / VIDEO_PREFLIGHT_CONTRACT §2 AC2). Submit is service-level (`submit_import`); the HTTP import route is S05-T04/T05 UI scope.
- **Jobs/artifacts:** `ANALYZE_MEDIA` now has a registered handler; the completion gate for this job type is the publication transaction itself (contract §6.2 step 3). `WorkerContext.session_factory` is an additive, backward-compatible extension (defaults `None`).
- **Error classification:** `PROBE_TIMEOUT` is now transient (contract §6.1/§7); structured exception `details` are preserved in the error envelope.

## Tests and validation

| Command | Result | Notes |
|---|---|---|
| `python -m pytest -q tests/test_video_import.py -p no:cacheprovider` | PASS | **19 passed** in 7.92s (success, checksum/size, checksum-mismatch abort, original unchanged, duplicate submit, copy failure, DB rollback orphan cleanup, cancellation, sanitize, symlink containment, insufficient disk, 4 unsupported-V1 parametrizations, no-audio warning, restart-recovery successor, probe-timeout transient, probe-timeout retries-exhausted). |
| `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS | **184 passed, 2 skipped** — regression: worker changes break nothing. |
| `python -m ruff check app tests` | PASS | `All checks passed!` |
| `python -m mypy app` | PASS | `Success: no issues found in 62 source files` |
| `git diff --check` | PASS | exit 0 (LF→CRLF advisory only on Windows). |
| `git status --short` | PASS | Only allowed files (see AC9). |
| `scripts/quality-baseline.ps1` (fresh run) | PASS | **OVERALL: PASS (exit 0), run id `20260804-182724` — 7/7 gates: env, python tests (594 passed, 19 skipped, 7 deselected in 125.92s), ruff, mypy, tsc, eslint, build.** |

## Manual UX/media verification

Not applicable — no UI/media rendering code in this task. Media behavior is verified end-to-end by the synthetic-fixture tests (real ffprobe + real lavfi mp4 files, tmp_path only) and the manifest/artifact/file assertions.

## Migration and rollback

None — no schema or migration change. The import writes through existing tables; a failed/replayed import leaves no orphan rows or files (verified by AC4/AC8 tests).

## Deviations from task

None.

## Out-of-scope findings

- Pre-existing untracked fixture trees `tests/fixtures/legacy_import/{valid,corrupt}/projects/` (S01 legacy-import fixtures never committed to git) and the S05-T01 packet/contract files are present in the worktree; this session did not modify them.
- The ROADMAP activation diff (S04-T05/S05-T01 APPROVED, S05-T02 READY) was made by the PM activation before this session and is PM-owned; this session made no ROADMAP edit.

## Known limitations/risks

- V1 deliberately rejects non-MP4 containers, non-H.264/HEVC video, non-AAC audio and HDR/10-bit inputs (per the approved PM decisions); no automatic transcode.
- The free-disk guard requires `source_size × 1.1 + 1 GiB` free on the managed root; very large sources on nearly-full drives fail with `INSUFFICIENT_DISK` before copy (behavioral, not numeric-cap based — the approved V1 decision).
- The canonical timebase/CFR-VFR mapping (S05-T03) will consume `fps_classification` + rational fps from the checkpointed probe payload.
- No HTTP import route yet (S05-T04/T05 owns the Import UI); `submit_import` is the service-level entry point.
- Tests skip gracefully when ffmpeg/ffprobe is absent (no-FFmpeg machine safe); on this machine all 19 run and pass.

## Recommended PM decision

`PENDING` — awaiting PM review per protocol (no self-approval; no commit; no roadmap edits; no next-task packet creation). Upon approval, S05-T03 (canonical timebase and proxy artifact generation) may start.

---

# Codex correction round 1 — 2026-08-04 (PM review CHANGES_REQUESTED)

**Prompt:** `output/S05_T02_CODEX_CORRECTION_PROMPT.md` (four finite defects + regression tests). Existing S05-T02 work was preserved; no S05-T03, no commit/push, no frontend/production-data/`channels.json` changes, no schema change.

## Defect 1 — Owner-safe idempotency

**Problem:** the key `ANALYZE_MEDIA:<source_sha256>:<generation>` collided when the same source bytes were intentionally imported into two different VideoItems in one workspace — the second owner reused the first Job/effects.

**Fix:** the logical identity now includes the VideoItem owner (generation kept). Single authority `_idempotency_key()` produces:

- `ANALYZE_MEDIA:video_item:<video_item_id>:<source_sha256>:<generation>` when a preflight hash is supplied (per-owner content identity);
- `ANALYZE_MEDIA:video_item:<video_item_id>:<generation>` when it is not (per-owner identity only, no content claim).

**Regression tests:**
- `test_same_bytes_two_video_items_get_own_jobs_and_effects` — same bytes → two VideoItems: two Jobs (distinct keys), two `ready` Artifacts, two files, each VideoItem gets its own `source_artifact_id`, no staging leftovers.
- Existing `test_duplicate_submit_single_effect_set` (with hash) and new `test_duplicate_submit_without_preflight_hash_reuses` (without hash) prove duplicate submit for the **same** VideoItem still raises `IdempotencyKeyInUse` while active and reuses the same Job/effect set when completed.

## Defect 2 — Workspace/project/video ownership validation

**Problem:** `submit_import` and publication did not verify the full ownership chain — only the VideoItem→project link was checked at publish.

**Fix:** new `_validate_ownership(session, workspace_id, project_id, video_item_id)` verifies (a) the stated Project exists and is not archived (`PROJECT_NOT_FOUND`), (b) Project belongs to the stated Workspace (`OWNERSHIP_MISMATCH`), (c) the active VideoItem exists and is not archived (`VIDEO_ITEM_NOT_FOUND`), (d) VideoItem belongs to the stated Project (`OWNERSHIP_MISMATCH`). Called **before Job creation** in `submit_import` and **again at publication** in `_publish_effect` (validation-first inside the one transaction). Two new stable codes with Vietnamese actions: `PROJECT_NOT_FOUND`, `OWNERSHIP_MISMATCH`.

**Regression tests (adversarial, zero side effects asserted):**
- `test_submit_rejects_cross_project_ownership_before_job_creation` — VideoItem of project A submitted as project B → `OWNERSHIP_MISMATCH`; 0 Job rows, 0 Artifact rows, 0 owner links, 0 managed files.
- `test_submit_rejects_cross_workspace_ownership_before_job_creation` — project of ws A submitted as ws B → `OWNERSHIP_MISMATCH`; same zero-side-effect assertions.
- `test_submit_rejects_missing_project_before_job_creation` → `PROJECT_NOT_FOUND`, 0 Job rows.
- `test_submit_rejects_missing_video_item_before_job_creation` → `VIDEO_ITEM_NOT_FOUND`, 0 Job rows.
- `test_publication_revalidates_ownership_after_submit` — submit valid, then the VideoItem is moved to another Project before the worker runs → Job fails `OWNERSHIP_MISMATCH` with zero artifact/owner/file side effects (staged and final files cleaned).

## Defect 3 — Remove mandatory request-path hashing contradiction

**Problem:** `submit_import` required `source_sha256`, contradicting V1 PM decision #6 (checksum computed during the streaming managed copy; preflight hash only optional; never hash an arbitrarily large file in the request path).

**Fix:** `source_sha256` is now optional (`str | None = None`). When **absent** the request path never reads/hashes the file: the submission identity is the stable owner-scoped key (no content identity is claimed before the hash exists), and after the copy the worker records the canonical SHA-256 and size on the Artifact. When **supplied**, strong verification is preserved — `ManagedRoot.atomic_write_stream(expected_sha256=...)` aborts before publish with `CHECKSUM_MISMATCH` on any mismatch. The manifest omits `source_sha256` when absent; probe payload records `sha256: None` until the copy computes it.

**Documented idempotency/retry behavior** (docstrings of `_idempotency_key` / `submit_import`): with a preflight hash identity is per `(owner, content, generation)`; without, per `(owner, generation)`; a completed duplicate returns the existing Job, an active duplicate raises `IdempotencyKeyInUse`; retry/restart of a failed/cancelled Job is a successor with the same key and generation (DURABLE_JOB_CONTRACT §6.4/§8.5); a fresh logical run of the same owner bumps `generation`. Content-deduplication is never claimed before the hash exists.

**Regression tests (both paths):**
- `test_submit_without_preflight_hash_records_canonical_sha` — `omit_sha=True` submit: manifest has no `source_sha256`, key is `ANALYZE_MEDIA:video_item:<id>:1`, Job completes, Artifact `sha256` == real source hash (computed from the copy), bytes identical, staging clean.
- `test_duplicate_submit_without_preflight_hash_reuses` — active duplicate → `IdempotencyKeyInUse`; completed duplicate → same Job (`reused=True`), exactly one Job/Artifact/file.
- `test_with_preflight_hash_key_embeds_content_identity` — with-hash key shape.
- Existing `test_checksum_mismatch_aborts_before_publish` — wrong preflight hash still fails with `CHECKSUM_MISMATCH` before any publish (strong verification when supplied).

## Defect 4 — Never delete a previously committed ready artifact file during replay cleanup

**Problem:** `_publish_phase` removed `final_path` on any later publication error even when `_publish_file` merely reused a pre-existing matching final file/ready row (and the checksum-mismatch branch would delete a pre-existing committed file).

**Fix:** `_publish_file` now returns `True` only when **this attempt** created/moved the final file (`os.replace` succeeded), `False` when it reused a pre-existing verified file. `_publish_phase` tracks `created_final` and removes `final_path` **only when `created_final` is True**; a `_publish_file` failure never removes the final path (it did not create it); the staged copy (owned by the failing attempt) is always cleaned. Docstrings state the ownership rule.

**Regression tests:**
- `test_replay_publication_failure_keeps_committed_artifact` — successful commit → force replay (checkpoint lost, job/step reset to queued/pending, lease + append-only attempt rows cleared to mirror a fenced-requeue fresh claim) → injected DB failure at publication → Job fails `PUBLICATION_FAILED` but the committed `ready` Artifact row survives and the committed file remains intact and byte-identical; staging clean.
- `test_publish_file_checksum_mismatch_keeps_existing_final` — a pre-existing final file that does not match the recorded checksum raises `CHECKSUM_MISMATCH` and is **not** removed by the publish helper.

## Files changed (correction round)

- `app/services/video_import.py` — owner-scoped idempotency key (`_idempotency_key`), optional preflight SHA, `_validate_ownership` (submit + publish), `created_final`-guarded cleanup in `_publish_phase`/`_publish_file`, new codes `PROJECT_NOT_FOUND`/`OWNERSHIP_MISMATCH` (+ Vietnamese actions), module/docstring updates.
- `tests/test_video_import.py` — 11 new regression tests (30 total), updated key-shape assertion, `omit_sha` submit helper.
- `docs/pm/sessions/S05-T02-managed-import/LOG.md` (appended), `REPORT.md` (this section).

Unchanged (verified by `git status`): worker/job_service files from the original submission, ROADMAP (PM-owned activation diff), S05-T01 packet/contracts, migrations, frontend, production data, `channels.json`, fixtures.

## Validation (correction round)

| Command | Result | Notes |
|---|---|---|
| `python -m pytest -q tests/test_video_import.py -p no:cacheprovider` | PASS | **30 passed** in 11.71s (19 original + 11 correction tests). |
| `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS | **184 passed, 2 skipped** in 47.64s — durable worker/job/persistence/reconciliation/artifact/ffmpeg regressions unaffected. |
| `python -m ruff check app tests` | PASS | `All checks passed!` |
| `python -m mypy app` | PASS | `Success: no issues found in 62 source files` |
| `git diff --check` | PASS | exit 0 (LF→CRLF advisory only). |
| `git status --short` | PASS | Only allowed files (see Files changed). |
| `scripts/quality-baseline.ps1` (fresh run) | PASS | **OVERALL: PASS (exit 0)**, run `20260804-195002` — 7/7 gates: env, Python tests (**605 passed, 19 skipped, 7 deselected** in 130.23s — includes the 11 new correction tests), ruff, mypy, tsc, eslint, build. Summary: `output/quality-baseline/20260804-195002/summary.json`. |

**Status:** `SUBMITTED` — re-submitted for PM review after the correction round. No self-approval; no commit/push; no next-task packet.

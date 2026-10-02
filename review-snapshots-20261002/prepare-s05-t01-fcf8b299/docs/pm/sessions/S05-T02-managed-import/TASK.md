# S05-T02 - Managed import copies/registers source safely with checksum

**Status:** READY
**Epic:** E03 - Import and Analyze
**Sprint:** S05 - Import/analyze vertical slice
**Gate:** G2 - Import/analyze
**Depends on:** S05-T01 APPROVED (`docs/pm/sessions/S05-T01-video-preflight/PM_REVIEW.md` = `APPROVED`; `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` published; `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md` published). PM flips this header to `READY` only after S05-T01 is approved.

## User outcome

A managed import safely streams/copies a source video into the managed root, computes SHA-256 and size **during the copy**, atomically publishes a `ready` Artifact, links it as the VideoItem source (`artifact_owner` purpose `source`) and persists the existing probe metadata (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) **in one transaction/job effect**. Idempotent retry/restart never duplicates artifacts or orphan files; cancellation/failure cleans staging/partial files; path containment is enforced and the original source is never mutated or deleted.

## Why now

- S05-T01 approved the preflight/probe contract and the V1 PM decisions; the next step in the import vertical slice is the durable write path: the `ANALYZE_MEDIA` job that copies and registers the source.
- `video_item` probe columns already exist with CHECK constraints and are read-only at the API — S05-T02's import path is the approved writer (`docs/architecture/VIDEO_ITEM_API.md` §1/§5; `VIDEO_PREFLIGHT_CONTRACT.md` §2 boundary rule AC2).
- The durable job contract already approves `ANALYZE_MEDIA` (§3), idempotency keys (§8.1), one-transaction publication (§7.1/§9.2) and the `UNSUPPORTED_CODEC` permanent code (§6.1).
- The S01-T03 `ManagedRoot` atomic-write helpers (staging file → fsync → atomic rename, `expected_sha256` abort-before-publish) are the mandated copy surface (`MANAGED_ARTIFACT_CONTRACT.md` §5; `VIDEO_PREFLIGHT_CONTRACT.md` §6.2 step 2).

## Required reading

Read completely, in this order:

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table + task activation rules)
3. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` — full (§2 boundary, §3 canonical probe metadata + §3.2 mapping, §4 supported table, §5 ffprobe safety/timeouts, §6 durable job/import semantics, §7 error taxonomy, §10 acceptance invariants)
4. `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md` — full (MP4/H.264/HEVC/AAC accepted; other codecs fail closed; no file-size cap but free-disk guard source+10%+1 GiB; structural minimums positive duration/width/height; first-stream canonical; HDR/10-bit rejected; checksum computed while streaming the managed copy; stable actionable errors)
5. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` — full (§4 path contract, §5 atomic write with `expected_sha256`, §8 errors)
6. `docs/architecture/VIDEO_ITEM_API.md` — §1/§5 (probe columns read-only until S05-T02 writes them), §4 (positions/status), DTO boundary
7. `docs/architecture/DURABLE_JOB_CONTRACT.md` — §3 (`ANALYZE_MEDIA`), §4.3/4.4 (state machines), §6.1 (retry classification), §7 (transactions/checkpoints), §8 (idempotency, replay), §9 (staging/publication/cleanup), §10 (error envelope)
8. `app/persistence/artifacts.py` — `ManagedRoot` atomic_write_stream/atomic_write_bytes, resolve/containment, hash_file
9. `app/services/ffmpeg_utils.py` — full (single binary discovery authority)
10. `app/services/video_probe.py` — current probe behavior (the probe step hardens this surface)
11. `app/persistence/jobs.py` — `JobRepository.create_job`/`create_successor` idempotency semantics
12. `app/persistence/videos.py` — VideoItem write surface (probe columns read-only today)
13. `app/persistence/models.py` — `VideoItem` probe columns + CHECK constraints, `Artifact`, `ArtifactOwner` (composite PK), `Job`/`JobStep`/`JobLease`
14. `app/workflow/durable_worker.py` — full (handler registry, WorkerContext, `_run_step`, `_classify_error`, cancel drain, checkpoint resume)
15. `app/workflow/job_service.py` — `create_job` manifest conventions, `register_api_handlers` wiring
16. `tests/test_durable_worker.py` — worker test patterns (fake clock/sleeper, cancel-during-run)
17. `tests/test_managed_artifacts.py` — containment/atomic-write test patterns (tmp_path only)
18. `tests/test_integration.py` — `create_test_video` synthetic fixture pattern (lavfi testsrc + sine → tmp_path)
19. `tests/test_video_item_crud.py` — probe-column read-only assertions
20. `docs/quality/QUALITY_BASELINE.md` — the 7/7 gate definition (`-m "not gpu and not sam2 and not integration"`)

## Optional evidence (read only when a specific question arises)

- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` — §4/§5/§6 (artifact/video_item aggregate rules)
- `app/workflow/job_reconciler.py` — fenced/cancelling resolution semantics
- Primary worktree `C:\Users\Admin\MotionForge2D` (read-only) — only to confirm repo state; never copy or modify.

## Allowed write scope

- `app/services/video_import.py` (new — the managed import service + ANALYZE_MEDIA handler)
- `app/workflow/durable_worker.py` (minimal: optional `session_factory` on `WorkerContext`; add `PROBE_TIMEOUT` to `TRANSIENT_ERROR_CODES`)
- `app/workflow/job_service.py` (register the ANALYZE_MEDIA handler)
- `tests/test_video_import.py` (new — synthetic/tmp fixtures only)
- `docs/pm/sessions/S05-T02-managed-import/LOG.md`, `REPORT.md` (session evidence)

## Forbidden scope

- PRD, Master Plan, roadmap, task contracts, templates, prior session packets.
- **Any new schema/migration.** No DDL changes: the `video_item` probe columns, `artifact` and `artifact_owner` tables already exist and enforce the contract. If a new column/table proves unavoidable, stop and report `BLOCKED`.
- API routes, frontend code, canonical proxy/timebase (S05-T03), scene detection (S05-T04), UI (S05-T05).
- Production data, `channels.json`, `data/`, `projects/`, `output_m05/`, database files, user data, the primary worktree `C:\Users\Admin\MotionForge2D`.
- Commits, pushes, approvals, and creation of the next task packet.

## Current behavior/evidence

- `video_item` carries `duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id` with CHECK constraints; the S03-T03 API forbids writing them (422) — S05 owns import/probing.
- `ManagedRoot.atomic_write_stream` (S01-T03) provides the mandated atomic copy: same-directory staging file, fsync, `expected_sha256` abort-before-publish, returns `(sha256, size_bytes)`.
- `DurableWorker` runs one registered handler per job type; `WorkerContext` carries checkpoint, progress/write_checkpoint/is_cancelled/staging_dir callbacks but no session factory (handlers that must persist durable effects need one).
- No `ANALYZE_MEDIA` handler exists; no import service exists; `PROBE_TIMEOUT` is not in the worker's transient set.

## Target behavior (S05-T02 implementation)

1. **Submit** — `submit_import(...)` validates the source exists/readable and creates the durable `ANALYZE_MEDIA` job with idempotency key `ANALYZE_MEDIA:<source_sha256>:<generation>` (contract §8.1). A completed duplicate returns the existing Job (reuse); an active duplicate raises `IdempotencyKeyInUse`.
2. **Probe phase** — bounded ffprobe (30s, list-args, JSON, discovery via `ffmpeg_utils`), schema-versioned canonical probe payload (§3), V1 media decision (MP4 container; H.264/HEVC video; AAC or no audio; HDR/10-bit rejected; positive duration/width/height), `NO_AUDIO_STREAM` recorded as a warning (accepted). Probe result is persisted as the step checkpoint so retry reuses it (never re-probes).
3. **Copy phase** — streaming copy into the managed staging area via `ManagedRoot.atomic_write_stream` with `expected_sha256` (preflight hash when available) — SHA-256 and size computed during the copy; mismatch aborts before publish (`CHECKSUM_MISMATCH`). Free-disk guard (`source_size * 1.1 + 1 GiB`) runs before any byte is copied (`INSUFFICIENT_DISK`). Leftover `.staging` partials (crash leftovers, including a predecessor's) are garbage-collected on re-run.
4. **Publish phase** — atomic `os.replace` of the staged file into the final managed path `artifacts/<workspace_id>/video/<job_id>/<step_code>/<name>`, then **one transaction**: upsert the `artifact` row (`kind='video'`, `state='ready'`, sha256, size, relative path) with a deterministic artifact id, upsert the `artifact_owner` link (`purpose='source'`), and write the `video_item` probe columns + `source_artifact_id`. DB failure removes the just-published file (no orphan). Replay finds the ready row and skips publication (no duplicates).
5. **Cancellation/failure** — every phase observes `ctx.is_cancelled()` and removes its staging/partial files before raising `CANCELLED`; the worker drains to terminal `cancelled` with no final outputs.
6. **Path containment** — every managed path is validated by `ManagedRoot` (normalized relative path, no `..`, no absolute/drive/UNC, symlink-escape rejection); `ManagedPathError` maps to the stable `PATH_CONTAINMENT` envelope. The original source is opened read-only and never mutated/deleted.

## Acceptance criteria

- [ ] AC1 `app/services/video_import.py` implements submit + ANALYZE_MEDIA handler with probe/copy/publish phases, checkpoint resume, idempotent publication and stable error taxonomy (reuses `UNSUPPORTED_CODEC`; codes per contract §7 + V1 PM decisions).
- [ ] AC2 Success path: Job `completed`; exactly one `ready` `kind='video'` Artifact with sha256/size recorded from the copy; `artifact_owner` purpose `source` for the VideoItem; `video_item` probe columns + `source_artifact_id` persisted; file bytes identical to source; original source unchanged.
- [ ] AC3 Duplicate/idempotent submit: active duplicate raises `IdempotencyKeyInUse`; completed duplicate reuses the same Job; exactly one effect set (one Job, one Artifact, one file).
- [ ] AC4 Copy failure / DB rollback / cancellation clean up staging and partial files (no `.staging` leftovers, no orphan final files, no `ready` rows without files).
- [ ] AC5 Path escape and symlink containment are rejected (`PATH_CONTAINMENT`), nothing is written outside the managed root, the source is never mutated.
- [ ] AC6 Insufficient disk is rejected before copy with `INSUFFICIENT_DISK`.
- [ ] AC7 Unsupported V1 media decisions fail closed with the exact stable codes (container/codec/audio-codec/HDR); `NO_AUDIO_STREAM` is accepted with a warning.
- [ ] AC8 Restart recovery: a failed attempt followed by a successor Job re-runs from checkpoint and completes without duplicate artifacts; crash-leftover staging files are cleaned.
- [ ] AC9 No new schema/migration, no API/frontend changes, no production data / `channels.json` / unrelated files touched; `git status` shows only the allowed files.
- [ ] AC10 Targeted tests, ruff, mypy, `git diff --check` and the fresh 7/7 quality baseline all pass.

## Required validation

```powershell
# Targeted (from repo root)
python -m pytest -q tests/test_video_import.py -p no:cacheprovider
python -m ruff check app/services/video_import.py app/workflow/durable_worker.py app/workflow/job_service.py tests/test_video_import.py
python -m mypy app
git diff --check

# Full 7/7 quality baseline (must be PASS; run from repo root)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
```

## Required evidence

- Full content summary of the implementation (not a stub).
- The exact stable error codes + V1 decision mapping used.
- Command output for every validation command above.
- `git status --short` showing only allowed files.
- `REPORT.md` (template) and `LOG.md` appended entries; REPORT status `SUBMITTED`.

## Stop conditions

- Dependency not approved: S05-T01 is not `APPROVED` — stop, do not start.
- Any need for a new schema column/table/migration — stop and report `BLOCKED`.
- Any need to extend write scope, touch user data, or modify unrelated files — stop and report `BLOCKED`.
- Conflicting requirements or unverifiable acceptance criteria — stop and report `BLOCKED`.

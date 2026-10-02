# S05-T03 - Canonical timebase and proxy artifact generation

**Status:** READY
**Epic:** E03 - Import and Analyze
**Sprint:** S05 - Import/analyze vertical slice
**Gate:** G2 - Import/analyze
**Depends on:** S05-T02 APPROVED (`docs/pm/sessions/S05-T02-managed-import/REPORT.md` — original submission + Codex correction round; `app/services/video_import.py` owner-scoped idempotency and optional preflight SHA are the authoritative pattern). PM flips this header to `READY` only after S05-T02 is approved.

## User outcome

One deterministic canonical timeline mapping (exact rational arithmetic, never float drift) converts between frame index, canonical timestamp and duration for both accepted CFR and accepted VFR inputs, with explicit rounding, monotonicity, boundary and duration behavior, and fail-closed stable errors for invalid/zero rationals. A bounded editing proxy is generated from the managed `ready` source artifact through a durable/checkpointed worker path (`GENERATE_PROXY`), using FFmpeg discovery only via `ffmpeg_utils`, list arguments (no shell), bounded execution/cancellation, and deterministic owner-scoped idempotency/generation. The proxy is published as a managed `ready` `video` artifact with mandatory SHA-256 + size, path containment, atomic publication, and an `artifact_owner` link with purpose `proxy`. Retry/restart reuses valid completed work, creates no duplicate rows/files, and cleans only staging/files owned by the failed attempt. The immutable source artifact is preserved and no absolute managed path leaks into durable/public data. No synchronous long-running proxy generation in an API request.

## Why now

- S05-T01 approved the preflight/probe contract, which classifies inputs `CFR`/`VFR` and explicitly defers the canonical timebase mapping to S05-T03 (`VIDEO_PREFLIGHT_CONTRACT.md` §3.1 `fps_classification`, §6.4: "S05-T03 consumes `fps_classification` + rational fps from the probe result to build the canonical timebase").
- S05-T02 implemented the managed import (`ANALYZE_MEDIA`) that publishes the immutable `ready` `source` artifact — the proxy job's input (owner-scoped idempotency, optional preflight SHA, one-transaction publication, `created_final`-guarded cleanup are the approved patterns this task mirrors).
- The master plan exit for U1 requires "Canonical timebase được lưu" and WS-03 lists "Canonical timebase/CFR-VFR policy" and "Proxy/waveform" as deliverables; the PRD Step 1 system flow is "Probe ... -> Tạo proxy nhẹ để preview".
- `DURABLE_JOB_CONTRACT.md` §3 fixes the approved job-class list; none of the existing classes (including `ANALYZE_MEDIA`, `GENERATE_RESKIN_PREVIEW`) represents bounded editing-proxy generation from a managed ready source, and changing S05-T02's `ANALYZE_MEDIA` semantics/idempotency is forbidden. S05-T03 therefore registers one new job class `GENERATE_PROXY` and documents it in the architecture note.

## Required reading

Read completely, in this order:

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table + task activation rules)
3. `docs/PRODUCT_REQUIREMENTS_V2.md` — import/analyze (Step 1), CFR/VFR canonical timebase acceptance (line 516), proxy (lines 81/498/635/794/925-929), progress/cancel/retry/resume (line 49) only
4. `docs/MASTER_PLAN_V1.md` — WS-03 (lines 815-837) + canonical playhead/timecode (line 505), job classes (line 638+), U1 exit (line 230) only
5. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` — full (esp. §3.1 `fps_classification` CFR/VFR rule, §5 ffprobe safety, §6.4 T03 consumption point)
6. `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md` — full
7. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` — full (§4 path contract, §5 atomic write, §8 errors)
8. `docs/architecture/DURABLE_JOB_CONTRACT.md` — §3 (job classes), §4.3/4.4 (state machines), §5 (leases/fencing), §6.1 (retry classification), §7 (transactions/checkpoints), §8 (idempotency/replay/successor), §9 (staging/publication/cleanup), §10 (error envelope)
9. `docs/architecture/DURABLE_JOB_PERSISTENCE.md` — schema/repository semantics
10. `docs/pm/sessions/S05-T02-managed-import/REPORT.md` — full, including the Codex correction section (owner-scoped idempotency; optional preflight SHA; ownership validation at submit+publish; `created_final`-guarded cleanup never deletes committed ready files)
11. `app/services/video_import.py` — full (the approved patterns this task mirrors: idempotency key shape, `_validate_ownership`, `_publish_phase`/`_publish_file`/`_publish_effect`, checkpoint reuse, cancellation cleanup)
12. `app/services/ffmpeg_utils.py` — full (single binary discovery authority)
13. `app/services/gpu_encoder.py` — encoder argument shape (informational; proxy uses CPU libx264 to stay bounded)
14. `app/workflow/durable_worker.py` — full (handler registry, WorkerContext, `_run_step`, `_classify_error`, `_validate_outputs`, cancel drain, declared-output validation)
15. `app/workflow/job_service.py` — `register_analyze_media_handler` wiring pattern
16. `app/persistence/models.py` — `Artifact`, `ArtifactOwner` (composite PK), `VideoItem`, `Job`/`JobStep`
17. `app/persistence/artifacts.py` — `ManagedRoot` resolve/containment/atomic_write, `hash_file`
18. `tests/test_video_import.py` — full (fixture patterns: tmp DB upgrade, FakeClock/FakeSleeper, lavfi `testsrc`/`sine`, successor replay, correction regression patterns)

## Optional evidence (read only when a specific question arises)

- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` — §4/§5/§6 artifact/video_item aggregate rules
- `app/workflow/job_reconciler.py` — fenced/cancelling resolution semantics
- `app/services/video_probe.py` — legacy float-fps probe (contrast: this task uses exact rationals)
- Primary worktree `C:\Users\Admin\MotionForge2D` (read-only) — only to confirm repo state; never copy or modify.

## Allowed write scope

- `app/services/timebase.py` (new — canonical rational timeline mapping)
- `app/services/video_proxy.py` (new — GENERATE_PROXY service + durable handler)
- `app/workflow/job_service.py` (minimal: register the GENERATE_PROXY handler)
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md` (new — architecture note stating the exact implemented timebase/proxy contract)
- `tests/test_timebase.py` (new — pure rational/boundary/monotonicity tests)
- `tests/test_video_proxy.py` (new — synthetic/tmp fixtures only)
- `docs/pm/sessions/S05-T03-canonical-timebase-proxy/LOG.md`, `REPORT.md` (session evidence)

## Forbidden scope

- PRD, Master Plan, roadmap, task contracts, templates, prior session packets (including `docs/pm/sessions/S05-T02-managed-import/*` and `S05-T01-video-preflight/*`).
- `app/services/video_import.py` — **do not modify**. Import (read-only) its approved helpers if needed; never change S05-T02 ownership/idempotency/cleanup behavior.
- **Any new schema/migration.** No DDL changes. The existing `artifact`, `artifact_owner` and `job` tables must represent the proxy result; the canonical timebase is persisted only in durable JSON payloads (`input_manifest_json`/`checkpoint_json`). If a new column/table proves unavoidable, stop and report `BLOCKED` with exact evidence.
- Public API routes, frontend code, scene detection (S05-T04), import UI (S05-T05), any change to the `ANALYZE_MEDIA` job contract.
- Production data, `channels.json`, `data/`, `projects/`, `output_m05/`, database files, user data, the primary worktree `C:\Users\Admin\MotionForge2D`.
- Commits, pushes, approvals, and creation of the next task packet.

## Current behavior/evidence

- `app/services/video_import.py` (S05-T02, APPROVED incl. Codex corrections) publishes the source as a `ready` `video` Artifact with `artifact_owner` purpose `source`, records `video_item` probe columns (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`), and its checkpointed probe payload carries `fps_classification` ∈ {CFR, VFR} plus rational `r_frame_rate`/`avg_frame_rate`.
- `DurableWorker.register_handler(job_type, handler, declared_outputs=..., output_validator=...)` + `JobRepository.create_job`/`create_successor` implement idempotency, replay and the completion gate; `WorkerContext` carries `is_cancelled`, `write_checkpoint`, `progress`, `staging_dir`, `session_factory`.
- No canonical timebase module exists; legacy `app/services/video_probe.py` computes float fps (`float(num)/float(den)`) with no rounding/monotonicity/boundary contract.
- No proxy generation service/handler exists; no `GENERATE_PROXY` job type is registered.

## Target behavior (S05-T03 implementation)

1. **Canonical timebase** (`app/services/timebase.py`) — a pure, exact-rational mapping:
   - `CanonicalTimebase(fps_num, fps_den, *, classification, duration_seconds, nb_frames)` built from `Fraction`; rejects `fps_num <= 0` / `fps_den <= 0` / unknown classification with stable actionable codes (`INVALID_TIMEBASE`, `UNSUPPORTED_CLASSIFICATION`) — never a bare exception.
   - `frame_to_time(frame)` = exact `Fraction(frame * fps_den, fps_num)`; `time_to_frame(t)` with **explicit rounding** (documented `floor` = the frame whose interval contains t, `round_half_up` = nearest for extraction, `ceil` for safety edges); both monotonic (floor/round are non-decreasing, frame_to_time strictly increasing).
   - Boundary/duration behavior: frame 0 → time 0; `frame_count_for_duration(d)` = nearest-half-up `round(d * fps)` with `>= 1` for positive d; `duration_for_frames(n)` = `n / fps`; negative frame/duration rejected (`INVALID_FRAME_INDEX`, `INVALID_DURATION`).
   - CFR: canonical grid = `r_frame_rate` rational. VFR: canonical grid = `avg_frame_rate` rational (both accepted inputs, per preflight classification); the classification is recorded on the mapping and the proxy output is resampled onto the canonical CFR grid.
2. **Proxy job** (`app/services/video_proxy.py`) — `submit_proxy(...)` validates ownership chain + source artifact (`kind='video'`, `state='ready'`, `artifact_owner` purpose `source`, sha256 recorded) before Job creation, then creates the durable `GENERATE_PROXY` Job with **owner-scoped** idempotency key `GENERATE_PROXY:video_item:<video_item_id>:<source_sha256>:<generation>` (completed duplicate → reuse; active duplicate → `IdempotencyKeyInUse`; retry/restart → successor with same key/generation). The request path never runs ffmpeg.
3. **Generation phase** (`generate_proxy_handler`) — re-validates ownership + source at run time; reads the source file **read-only** through `ManagedRoot` from the artifact `relative_path`; probes the source (bounded ffprobe via `ffmpeg_utils`, 30s, list args); builds the canonical timebase from the probe; runs ffmpeg with **list arguments only**, discovery only via `ffmpeg_utils.find_ffmpeg`, bounded timeout (profile `timeout_seconds`, default 120), writes to the managed staging path `staging/<job_id>/<step_code>/<name>`, and polls `ctx.is_cancelled()` — on cancel terminates the subprocess, removes the staging partial, raises `CANCELLED`; on timeout terminates and raises `PROXY_TIMEOUT` (transient → worker auto-retry).
4. **Verification phase** — bounded ffprobe of the generated proxy (decodes; positive duration/width/height; recorded output metadata is truthful); SHA-256 + size computed on the staged file; parity with the final file asserted at publication.
5. **Publish phase** — atomic `os.replace` staging → final managed path `artifacts/<workspace_id>/video/<job_id>/<step_code>/<name>`, then **one transaction**: deterministic-id upsert of the `artifact` row (`kind='video'`, `state='ready'`, sha256, size, relative_path, `mime_type='video/mp4'`) + `artifact_owner` link (`owner_type='video_item'`, purpose `proxy`). A DB failure removes the just-published file **only when this attempt created it**; replay finds the ready row/file and reuses (no duplicates, committed files never deleted).
6. **Completion gate** — `GENERATE_PROXY` registers an `output_validator` that re-verifies the published file on disk (exists + sha256 + size match the handler's evidence); Job `completed` can never precede verified publication.
7. **Cancellation/failure cleanup** — every phase observes `ctx.is_cancelled()` and removes its own staging/partial files; a failed/successor attempt cleans only staging owned by the failed attempt or its predecessor.
8. **Path containment** — every managed path through `ManagedRoot`; `ManagedPathError` → stable `PATH_CONTAINMENT`; the source artifact is opened read-only and never mutated/deleted.
9. **No absolute managed path in durable data** — the artifact row and owner link carry only normalized relative paths; the source path is read from the DB artifact row + managed root, never embedded as an absolute path in persisted JSON.

## Acceptance criteria (binary)

- [ ] AC1 `app/services/timebase.py` implements the exact-rational canonical mapping: `frame_to_time` exact, `time_to_frame` with explicit floor/round_half_up/ceil, monotonicity (non-decreasing frames for increasing time; strictly increasing times for increasing frames), boundary (frame 0 → 0, duration/frame-count rules), and fail-closed stable codes for zero/negative/invalid rationals and unknown classification.
- [ ] AC2 `app/services/video_proxy.py` implements `submit_proxy` + `GENERATE_PROXY` handler with generate→verify→publish phases, checkpoint resume, owner-scoped idempotency, and stable error taxonomy; ffmpeg/ffprobe discovery ONLY via `ffmpeg_utils`, list arguments only, bounded execution/cancellation; registered in `app/workflow/job_service.py`.
- [ ] AC3 Success path: Job `completed`; exactly one `ready` `kind='video'` Artifact with sha256/size recorded, `artifact_owner` purpose `proxy`, path under `artifacts/<workspace_id>/video/<job_id>/<step_code>/`; the proxy decodes (bounded ffprobe) with truthful metadata; source artifact bytes unchanged.
- [ ] AC4 Owner-scoped idempotency: same source bytes + two VideoItems → two independent Jobs/artifacts; duplicate submit for the same owner → `IdempotencyKeyInUse` (active) / reuse (completed); exactly one effect set.
- [ ] AC5 Failure/rollback/cancellation: FFmpeg failure → stable `PROXY_FFMPEG_FAILED`; timeout → `PROXY_TIMEOUT` transient (auto-retry then `RETRIES_EXHAUSTED`); cancel mid-generation → terminal `cancelled`; DB rollback removes only files created by the failing attempt; no `.staging` leftovers, no orphan final files, no `ready` rows without files.
- [ ] AC6 Replay/restart: a successor after a failed attempt re-runs from checkpoint and completes with exactly one artifact/file and cleans crash leftovers; a replay publication failure never deletes a previously committed ready artifact file.
- [ ] AC7 Path escape/symlink containment → `PATH_CONTAINMENT`, nothing written outside the managed root; source artifact never mutated/deleted.
- [ ] AC8 No new schema/migration, no API/frontend/scene-detection/import-UI change, no change to `app/services/video_import.py` or S05-T02 ownership/idempotency; `git status` shows only the allowed files.
- [ ] AC9 Real synthetic CFR and real VFR fixtures (lavfi, tmp only): CFR proxy and VFR proxy both complete and decode at the canonical rate; rational conversion/boundary tests pass; SHA/size/file parity asserted.
- [ ] AC10 Targeted tests, S05-T02 regression tests, durable worker/artifact/reconciliation regressions, ruff, mypy, `git diff --check` and the fresh 7/7 quality baseline all pass.

## Required validation

```powershell
# Targeted (from repo root)
python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py -p no:cacheprovider
python -m pytest -q tests/test_video_import.py -p no:cacheprovider
python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider
python -m ruff check app tests
python -m mypy app
git diff --check

# Full 7/7 quality baseline (must be PASS; run from repo root)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
```

## Required evidence

- Full content summary of the implementation (not a stub).
- The exact stable error codes + timebase rules implemented.
- Command output for every validation command above.
- `git status --short` showing only allowed files.
- `REPORT.md` (template) and `LOG.md` appended entries; REPORT status `SUBMITTED`.

## Stop conditions

- Dependency not approved: S05-T02 is not `APPROVED` — stop, do not start.
- Any need for a new schema column/table/migration — stop and report `BLOCKED` with exact evidence.
- Any need to modify `app/services/video_import.py` (beyond read-only import), change S05-T02 ownership/idempotency, or touch user data/unrelated files — stop and report `BLOCKED`.
- Conflicting requirements or unverifiable acceptance criteria — stop and report `BLOCKED`.

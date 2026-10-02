# S05-T01 - Video preflight/probe contract and actionable incompatibility errors

**Status:** READY
**Epic:** E03 - Import and Analyze
**Sprint:** S05 - Import/analyze vertical slice
**Gate:** G2 - Import/analyze
**Depends on:** E02 exit (S04-T05 APPROVED) — this task is NOT executable until E02 is approved. PM flips this header to `READY` only after S04-T05 `PM_REVIEW.md` is `APPROVED` and the E02 epic exit is recorded in `docs/pm/ROADMAP.md`.

## User outcome

Before any byte of a source video is copied into managed storage, the system can cheaply and safely answer: *"is this file an importable MotionForge source, and if not, exactly why not?"* The preflight/probe contract defines the canonical probe metadata, the supported/unsupported codec/container decision table (grounded in existing product requirements, not invented), a bounded and safe ffprobe invocation policy, and a stable, actionable error taxonomy with per-error location/reason/suggested action. It also fixes the durable metadata and job semantics that S05-T02..T05 will implement against.

This task produces the **approved contract only**. No runtime code, API, migration or worker wiring is written here; implementation is owned by S05-T02+ once this contract is approved.

## Why now

- E02 delivers the durable Project/Video Item shell; the next vertical slice (WS-03, `docs/MASTER_PLAN_V1.md` §WS-03) is Import & Analyze. The first import gate is preflight/probe.
- The current probe helper (`app/services/video_probe.py`) is a thin, unversioned ffprobe wrapper with a hard-coded `timeout=30`, no error taxonomy, no container/codec policy and no durable write path; S03-T03 deliberately left `video_item` probe columns (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) read-only because **S05 owns import and media probing** (`docs/architecture/VIDEO_ITEM_API.md` §1, §5).
- The durable job contract already approves the `ANALYZE_MEDIA` job type and the `UNSUPPORTED_CODEC` permanent error code (`docs/architecture/DURABLE_JOB_CONTRACT.md` §3, §6.1); S05-T01 must pin down how preflight/probe uses them before implementation.

## Required reading

Read completely, in this order:

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table + task activation rules)
3. `docs/PRODUCT_REQUIREMENTS_V2.md` — §9 Step 1 (Import & Analyze), §9 Step 6 (Export 4K, presets), §11 FR-02 (Media ingest), §11 FR-07 (Original audio), §11 FR-09 (Jobs), §13 Core data model, §14 Error/recovery, §16 Product decisions, §17 Research (NVIDIA capability-based guidance)
4. `docs/MASTER_PLAN_V1.md` — §WS-03 Import & Analyze (outcome/deliverables/exit gate), §2.2 principles (4K-aware, resume-safe, non-destructive), §3.3 migration decisions
5. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` — §4 `video_item` and `artifact` contracts, §5 relationships, §6 transactions
6. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` — full (path containment, atomic write, sha256, Trash)
7. `docs/architecture/VIDEO_ITEM_API.md` — full (probe columns read-only in S03; S05 owns import/probing; DTO boundary)
8. `docs/architecture/DURABLE_JOB_CONTRACT.md` — §3 job types (`ANALYZE_MEDIA`), §6 retry classification (`UNSUPPORTED_CODEC`), §7 transactions/checkpoints, §9 artifact staging/publication, §10 error envelope
9. `docs/architecture/DURABLE_JOB_API_CUTOVER.md` — §1 cutover map (how `ingest` was made durable), §4 lifecycle
10. `docs/architecture/DURABLE_JOB_PERSISTENCE.md` — schema + repository semantics (idempotency, guarded transitions)
11. `app/services/ffmpeg_utils.py` — full (single authority for ffmpeg/ffprobe discovery; no duplicate logic)
12. `app/services/video_probe.py` — full (current probe behavior; the thing S05 hardens)
13. `app/services/gpu_encoder.py` — capability-detection pattern (bounded subprocess, fallback)
14. `app/schemas/__init__.py` — `VideoMetadata` schema and durable DTO conventions
15. `app/persistence/videos.py` — create/update write paths (probe metadata read-only today)
16. `app/persistence/models.py` — `VideoItem` columns + CHECK constraints (duration_ms >= 0, width/height >= 0, fps_num/fps_den > 0, source_artifact_id FK)
17. `app/api/routes/durable_videos.py` — current v2 Video Item namespace (create forbids probe fields; 422)
18. `tests/test_ffmpeg_discovery.py` — discovery contract tests (no-FFmpeg machine safe)
19. `tests/test_integration.py` — `create_test_video` synthetic-fixture pattern (lavfi testsrc + sine → tmp_path; never production data)
20. `tests/test_video_item_crud.py` — probe-column read-only assertions
21. `tests/test_durable_job_api.py` — durable submit semantics and manifest conventions
22. `docs/quality/QUALITY_BASELINE.md` — the 7/7 gate definition (baseline runs; `-m "not gpu and not sam2 and not integration"`)

## Optional evidence (read only when a specific question arises)

- `tests/test_video_slicing.py`, `tests/test_clip_cancel_persist.py` — existing fixture-video assumptions (`output_m05/fixture_b/input.mp4`), so the contract does not accidentally rely on them for S05 tests (S05 uses only synthetic temp fixtures).
- `docs/CODEBASE_STRATEGY_REVIEW.md` — "FFmpeg probe/render/audio utilities: Keep + harden" decision.
- Primary worktree `C:\Users\Admin\MotionForge2D` (read-only) — only to confirm the pending S04 repair tree state; never copy or modify its files.

Do not read other documents unless a blocker requires a PM scope decision.

## Allowed write scope

- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (new — the deliverable)
- `docs/pm/sessions/S05-T01-video-preflight/LOG.md`
- `docs/pm/sessions/S05-T01-video-preflight/REPORT.md`

## Forbidden scope

- PRD, Master Plan, roadmap, task contract, `SESSION_PROTOCOL.md`, templates, and prior session packets/evidence.
- Any runtime source under `app/` (no probe service changes, no routes, no schemas, no persistence, no worker/handlers, no lifecycle).
- Migrations, dependencies (`pyproject.toml`, lockfiles), frontend code, fixtures, test files.
- Database files, `channels.json`, `data/`, `projects/`, `output_m05/`, any user data, the primary worktree `C:\Users\Admin\MotionForge2D`.
- Commits, pushes, approvals, and creation of the next task packet.

## Current behavior/evidence

- `app/services/video_probe.py::probe_video` runs ffprobe with `-v quiet -print_format json -show_format -show_streams`, `timeout=30`, raises `RuntimeError` on failure, parses `r_frame_rate`, `duration`, `nb_frames`, `size`, first video/audio stream; returns `VideoMetadata` (width, height, fps, duration_seconds, total_frames, codec, has_audio, audio_codec, file_size_bytes, file_path). No container check, no CFR/VFR detection, no error taxonomy, no checksum, no durable write.
- `app/services/ffmpeg_utils.py` is the single discovery authority (env override → PATH → WinGet Links → actionable error); tests in `tests/test_ffmpeg_discovery.py` prove the suite passes on machines without FFmpeg.
- `video_item` already carries `duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id` with CHECK constraints; S03-T03 forbids them on create/update (`app/api/routes/durable_videos.py`, `app/persistence/videos.py` §probe read-only).
- Durable contract approves `ANALYZE_MEDIA` job type and `UNSUPPORTED_CODEC` permanent code; `ingest` is already a durable job in the S02-T05 cutover map (`app/workflow/job_handlers.py::_ingest_handler`).
- No contract document defines what "preflight" is, what probe metadata is canonical, which codecs/containers are supported, or how incompatibility is surfaced to the user.

## Target behavior (contract content requirements)

The contract document `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` must define, and each item must cite the requirement it is grounded in:

1. **Preflight vs probe boundary.** A fast, read-only preflight (no import, no artifact registration, no byte copy) that yields an actionable accept/reject decision, versus the probe metadata extraction that becomes durable input for the import job. Define what each returns and where each runs (request vs `ANALYZE_MEDIA` step), grounded in FR-02/FR-09 and `SESSION_PROTOCOL` §4 (no long op synchronously in a request).
2. **Canonical probe metadata.** A versioned schema-versioned probe result: container format, video stream (codec, width, height, fps rational `num/den`, avg vs nominal fps, CFR/VFR classification, duration, frame count when available), audio stream presence/codec/channels/sample rate when present, file size, sha256. Map every field to the durable `video_item` columns that S05-T02/T05 will persist (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) and to `VideoMetadata`. Do NOT invent new durable columns; the existing contract fields are the write surface.
3. **Supported/unsupported codec/container table.** Grounded decisions ONLY:
   - **Supported by default (write into the contract):** MP4 container; H.264 (AVC) and HEVC (H.265) video; AAC audio — directly from the 4K Master preset and export requirements (PRD §9 Step 6, FR-10: "3840x2160, MP4 H.264 hoặc HEVC nếu hỗ trợ, AAC"), and from the NVIDIA capability-based guidance (PRD §17) which forbids assuming every GPU supports the same codecs.
   - **Probed and recorded regardless of support:** CFR vs VFR (both are accepted inputs per PRD §9 Step 1 acceptance "Video CFR/VFR đều map về canonical timebase chính xác" — canonical timebase mapping itself is S05-T03).
   - **Everything else (any other container/codec/audio codec) is NOT decided here** and MUST be listed in the contract's "Decisions deferred to PM" section as blockers, with the exact decision requested (e.g. minimum supported input container allowlist, maximum file size, minimum resolution/duration, ProRes/MKV acceptance). Do not invent an allowlist beyond MP4/H.264/HEVC/AAC.
4. **ffprobe safety and timeouts.** Bounded subprocess policy: explicit `timeout` (contract must state a value and rationale; the current helper uses 30s — the contract may keep or tighten it but must be explicit and bounded), `-v quiet`, JSON output, no shell (`subprocess.run` with list args, never `shell=True`), binary discovery ONLY via `app/services/ffmpeg_utils` (never a guessed path), fail-closed on missing binary, non-zero exit, JSON parse error or timeout — each maps to a stable error code, never a raw traceback.
5. **Durable metadata and job semantics.** When and by whom probe metadata becomes durable: preflight is read-only and must NOT mutate `video_item`; the import job (`ANALYZE_MEDIA`, S05-T02) persists canonical probe metadata + source artifact registration in one transaction per the durable contract (§7 state+effect coupling, §9 publication). Define the idempotency-key shape for preflight/import and how retry/restart reuses probe results instead of re-probing (durable contract §8).
6. **Actionable error taxonomy.** Stable `error_code` values (reuse `UNSUPPORTED_CODEC` from the durable contract; define the set needed for preflight: e.g. file missing/unreadable, no video stream, unsupported container, unsupported video codec, probe timeout, checksum mismatch placeholders) with per-error: severity (blocker vs warning), location (which field/stream), reason (machine-readable), and suggested action (user-facing Vietnamese text). Errors must never be a bare "failed" (PRD §9 Step 5 acceptance; FR-08).
7. **Compatibility with existing contracts.** Explicit statement that no schema/migration is required by this contract, that the probe columns remain read-only at the API until S05-T02's import path writes them, and that `channels.json`/user data are never touched.

## In scope

- Writing `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` covering the seven items above.
- Listing every unresolved product decision as an explicit blocker in the contract (and in REPORT), with the exact question and the requirement it is missing — do NOT invent behavior to resolve them.
- Session evidence: LOG.md entries + REPORT.md.

## Out of scope

- Any implementation: probe service rewrite, preflight endpoint, import/checksum logic (S05-T02), canonical timebase/proxy (S05-T03), scene detection (S05-T04), UI (S05-T05).
- Any schema/migration/dependency/frontend/test change.
- Any decision not grounded in the required reading becomes a blocker, not a contract assertion.

## Implementation constraints

- The contract is **contract-only**: no imports of `app` runtime modules may be required to read/validate it; it may reference them by path.
- Every supported/unsupported codec/container row must cite its requirement source; every deferred decision must be in the "Decisions deferred to PM" section.
- Timeout and safety policy must be concrete numbers/behaviors, not "reasonable".
- No mock data, no synthetic fixtures in this task (there is no code); the synthetic-fixture rule binds S05-T02+ and the contract must state that S05 tests use only temp/synthetic fixtures (`tmp_path` + lavfi testsrc/sine), never `output_m05` fixtures or production data.
- Follow existing doc conventions (status header, contract sections) of `docs/architecture/*` documents.

## Acceptance criteria

- [ ] AC1 `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` exists, is the only new product doc, and every section cites the requirement it is grounded in.
- [ ] AC2 Preflight vs probe boundary is explicit: preflight is read-only, never mutates `video_item` or registers artifacts; import (S05-T02 `ANALYZE_MEDIA`) is the only durable write path.
- [ ] AC3 Canonical probe metadata is schema-versioned and maps 1:1 to the existing durable `video_item` columns and `VideoMetadata`; no new durable columns are invented.
- [ ] AC4 The supported codec/container table contains exactly MP4 + H.264 + HEVC + AAC as default-supported (cited to PRD §9 Step 6 / FR-10), CFR+VFR recorded as both-accepted (cited to PRD §9 Step 1), and every other format listed under "Decisions deferred to PM" — no invented allowlist.
- [ ] AC5 ffprobe safety section is concrete and bounded: explicit timeout value with rationale, no shell, JSON output, discovery only via `ffmpeg_utils`, fail-closed mapping to stable error codes.
- [ ] AC6 Durable metadata and job semantics are explicit: preflight read-only, import persists probe+artifact in one transaction, idempotency-key shape defined, retry reuses probe results.
- [ ] AC7 Error taxonomy is stable and actionable: per-error code/severity/location/reason/suggested action (Vietnamese), reuses `UNSUPPORTED_CODEC`, never bare "failed".
- [ ] AC8 Every unresolved product decision is listed as a blocker with the exact question — none silently resolved.
- [ ] AC9 No runtime source, migration, dependency, frontend, fixture, test, database file, `channels.json`, user data, primary-worktree file or existing session packet was modified; `git status` shows only the new contract + session files.
- [ ] AC10 Targeted checks and the fresh 7/7 quality baseline pass (commands below).

## Required validation

```powershell
# Targeted contract checks (from repo root)
rg -n "preflight|probe|timeout|UNSUPPORTED_CODEC|H.264|HEVC|AAC|MP4|CFR|VFR|idempot|schema_version|sha256" docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md
rg -n "Decisions deferred to PM|BLOCKED" docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md
git diff --check -- docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md docs/pm/sessions/S05-T01-video-preflight
git status --short

# Full 7/7 quality baseline (must be PASS; run from repo root)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
```

Note: because this task is currently `BLOCKED_PENDING_E02`, the implementer must NOT run the baseline or any gate until PM flips the status to `READY`; this section documents the exact commands that will be required at execution time.

## Required evidence

- Full content summary of the contract (not a stub).
- The exact supported/unsupported table and the deferred-decisions list.
- Command output for every validation command above.
- `git status --short` showing only allowed files.
- `REPORT.md` (template) and `LOG.md` appended entries.

## Stop conditions

- Dependency not approved: S04-T05 is not `APPROVED` and E02 epic exit is not recorded — stop, do not start.
- Any required codec/container/product decision missing from the required reading — record as blocker, do not invent.
- Any need to extend write scope, touch schema/migrations, or modify user data — stop and report `BLOCKED`.
- Conflicting requirements or unverifiable acceptance criteria — stop and report `BLOCKED`.

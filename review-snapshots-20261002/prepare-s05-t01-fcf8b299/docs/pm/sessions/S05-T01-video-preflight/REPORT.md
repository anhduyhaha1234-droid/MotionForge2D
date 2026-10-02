# S05-T01 - Implementation Report

**Status:** SUBMITTED
**Hermes session:** 20260804_164857_429d87
**Started:** 2026-08-04 16:48 +07:00
**Submitted:** 2026-08-04 16:57 +07:00

## Outcome delivered

The approved preflight/probe contract `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (new, 10 sections) plus session evidence. Contract-only task: no runtime code, no routes, no schemas, no migrations, no workers, no API/frontend/fixture/test changes. Every contract assertion cites its requirement; every unresolved product decision is listed as a blocker, never invented.

**Contract content summary (all 7 required items):**

1. **Preflight vs probe boundary** — Preflight is the fast, read-only accept/reject gate running in the **request path** (bounded 10s; no `video_item` mutation, no artifact registration, no byte copy — grounded in FR-02, SESSION_PROTOCOL §4 no-long-op-in-request, MASTER_PLAN_V1 WS-03 "Import drop zone/preflight"). Probe is the durable metadata extraction that runs as the first step of the `ANALYZE_MEDIA` job in the durable worker (FR-09; DURABLE_JOB_CONTRACT §3). Import (`ANALYZE_MEDIA`) is the only durable write path.
2. **Canonical probe metadata** — schema-versioned payload (`schema_version: 1`): container format, video stream (codec, width/height, nominal + avg fps as rationals, CFR/VFR classification, duration, nb_frames), audio stream (codec/channels/sample_rate) when present, file size, sha256. §3.2 maps every field 1:1 to the existing durable `video_item` columns (`duration_ms`, `width`, `height`, `fps_num`, `fps_den`, `source_artifact_id`) and to `VideoMetadata`. **No new durable columns** (AC3).
3. **Supported/unsupported table** — exactly MP4 + H.264 (AVC) + HEVC (H.265) + AAC as default-supported, cited to PRD §9 Step 6 / FR-10 ("3840x2160, MP4 H.264 hoặc HEVC nếu hỗ trợ, AAC") and PRD §17 NVIDIA capability guidance. CFR + VFR both accepted inputs, cited to PRD §9 Step 1 acceptance. Everything else → "Decisions deferred to PM" (§9, 8 blockers B1–B8) — no invented allowlist (AC4/AC8).
4. **ffprobe safety and timeouts** — concrete and bounded: preflight timeout **10s** (request path, tightened from current 30s), probe step **30s** (kept from current helper, worker context); `-v quiet`, JSON output, `subprocess.run` list-args only (**no shell**), binary discovery **only** via `app/services/ffmpeg_utils` (fail-closed `PROBE_BINARY_NOT_FOUND`), every failure maps to a stable error code, never a raw traceback (AC5).
5. **Durable metadata and job semantics** — preflight read-only, never mutates `video_item`; import persists canonical probe metadata + source artifact registration **in one transaction** (state+effect coupling, DURABLE_JOB_CONTRACT §7.1/§9.2; `completed` only after publication+validation §9.3); idempotency-key shape `ANALYZE_MEDIA:<source_sha256>:<generation>` (§8.1); double-submit returns existing Job / `409 IDEMPOTENCY_KEY_IN_USE`; retry/restart uses the successor model and reuses checkpointed probe results instead of re-probing (§6.4/§8.4/§9.5) (AC6).
6. **Actionable error taxonomy** — 12 stable codes with severity (blocker/warning), location, machine-readable reason, and **Vietnamese suggested actions**: reuses durable `UNSUPPORTED_CODEC`; defines `INPUT_MISSING`, `INPUT_UNREADABLE`, `NO_VIDEO_STREAM`, `UNSUPPORTED_CONTAINER`, `UNSUPPORTED_AUDIO_CODEC`, `NO_AUDIO_STREAM`, `PROBE_TIMEOUT`, `PROBE_BINARY_NOT_FOUND`, `PROBE_NONZERO_EXIT`, `PROBE_JSON_PARSE_ERROR`, `CHECKSUM_MISMATCH` (S05-T02 placeholder). Never a bare "failed" (PRD §9 Step 5; FR-08) (AC7).
7. **Compatibility** — explicit: no schema/migration required; probe columns remain read-only at the API until S05-T02's import path writes them; `channels.json`/`data`/DB/user data never touched; contract-only (no `app` imports needed to read/validate); S05 tests use only `tmp_path` + lavfi testsrc/sine synthetic fixtures (AC9).

**Deferred decisions (blockers, contract §9 — exact question + requirement gap, none invented):**
B1 input container allowlist (MP4-only vs remux/transcode others); B2 max file size / free-disk margin; B3 minimum resolution/duration; B4 ProRes/DNxHD acceptance; B5 non-AAC audio acceptance (FR-07 fallback); B6 transcode-on-import for unsupported video codecs; B7 multi-stream canonical selection; B8 HDR/10-bit sources.

## Acceptance criteria evidence

| AC | Status | Evidence |
|---|---|---|
| AC1 contract doc exists, cites requirements | PASS | `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` exists (26,485 bytes), is the only new product doc; every section cites PRD/MP/architecture contracts (see content summary + inline citations). |
| AC2 preflight read-only / import-only write boundary | PASS | Contract §2 boundary table + §6.1: preflight never mutates `video_item`, never registers artifacts, never copies bytes; `ANALYZE_MEDIA` import is the only durable write path. |
| AC3 canonical probe metadata maps to existing durable columns | PASS | Contract §3.2 mapping table: `duration_ms/width/height/fps_num/fps_den/source_artifact_id` + `VideoMetadata`; explicit "no new durable columns". |
| AC4 supported table = MP4/H.264/HEVC/AAC only; rest deferred | PASS | Contract §4: exactly MP4+H.264/HEVC+AAC cited to PRD §9 Step 6/FR-10; CFR+VFR both-accepted cited to PRD §9 Step 1; every other format in §9 blockers. |
| AC5 ffprobe safety/timeout concrete and bounded | PASS | Contract §5: preflight 10s / probe 30s with rationale, list-args only (no shell), `-v quiet`, JSON, discovery only via `ffmpeg_utils`, fail-closed stable-code mapping table. |
| AC6 durable metadata + job semantics explicit | PASS | Contract §6: preflight read-only; one-transaction import (probe + artifact + probe columns); idempotency key `ANALYZE_MEDIA:<sha256>:<generation>`; retry reuses checkpointed probe results (successor model). |
| AC7 actionable error taxonomy with stable codes | PASS | Contract §7: 12 codes, severity/location/reason/Vietnamese suggested action; reuses `UNSUPPORTED_CODEC`; no bare "failed". |
| AC8 unresolved decisions listed as blockers | PASS | Contract §9: 8 blockers B1–B8, each with the exact question and the requirement gap. |
| AC9 no forbidden-scope modifications | PASS | `git status --short` shows: `M docs/pm/ROADMAP.md` (PM-owned pre-existing activation edit — verified via `git diff` at session start, NOT modified by this session), `?? docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (new deliverable), `?? docs/pm/sessions/S05-T01-video-preflight/` (session files), and `?? tests/fixtures/legacy_import/{valid,corrupt}/projects/` — untracked fixture trees restored from git history to make the pre-existing S01 test suite runnable in this fresh worktree (they were never committed; the primary worktree shows the exact same untracked dirs — see "Environment repairs"). No `app/`, migrations, dependencies, frontend, tracked fixtures/tests, DB files, `channels.json`, user data or primary-worktree files touched; no tracked file outside the allowed scope was modified. |
| AC10 targeted checks + 7/7 baseline pass | PASS | Targeted rg/diff/git-status checks PASS (see Tests and validation); fresh `scripts/quality-baseline.ps1` run = OVERALL PASS 7/7 (run id `20260804-171453`). Two environment repairs were required to make the baseline runnable in this fresh worktree — `npm ci` (frontend node_modules is git-ignored) and restoration of untracked legacy-import fixture trees from git history (see "Environment repairs" below). No tracked file outside the allowed scope was modified. |

## Files changed

- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (new — the deliverable).
- `docs/pm/sessions/S05-T01-video-preflight/LOG.md` (appended entries).
- `docs/pm/sessions/S05-T01-video-preflight/REPORT.md` (this file, status SUBMITTED).

Environment-only (untracked, not part of the deliverable): `frontend/node_modules/` (npm ci; git-ignored) and `tests/fixtures/legacy_import/{valid,corrupt}/projects/` fixture trees restored from git history to satisfy pre-existing S01 tests (they were never committed; identical untracked dirs already exist in the primary worktree).

Untouched (verified by `git status`): ROADMAP/PRD/MP/task contracts/templates (ROADMAP was already modified by PM activation before this session and is not in my write scope), all `app/` runtime source, migrations, `pyproject.toml`/lockfiles, frontend source, tracked fixtures/tests, database files, `channels.json`, `data/`, user data, and the primary worktree `C:\Users\Admin\MotionForge2D`.

## Architecture/schema/API impact

- **Schema/migration:** none. The `video_item` table already carries the probe columns with CHECK constraints (`duration_ms >= 0`, `width/height >= 0`, `fps_num/fps_den > 0`, `source_artifact_id` RESTRICT FK) — the contract maps onto them and states explicitly that no DDL change is introduced.
- **API:** none now. Probe columns remain read-only at the API (create/update 422) until S05-T02's import path writes them (VIDEO_ITEM_API §5).
- **Jobs/artifacts:** the contract pins down how the approved `ANALYZE_MEDIA` job type is used (one-transaction probe+artifact+probe-columns write; idempotency key; retry reuses checkpointed probe results). Implementation owned by S05-T02+.

## Tests and validation

| Command | Result | Notes |
|---|---|---|
| `rg -n "preflight\|probe\|timeout\|UNSUPPORTED_CODEC\|H.264\|HEVC\|AAC\|MP4\|CFR\|VFR\|idempot\|schema_version\|sha256" docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` | PASS | All required keywords present (see full output in LOG). |
| `rg -n "Decisions deferred to PM\|BLOCKED" docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` | PASS | §9 "Decisions deferred to PM" + 8 blocker rows present. |
| `git diff --check -- docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md docs/pm/sessions/S05-T01-video-preflight` | PASS | exit 0 (LF→CRLF advisory only on Windows). |
| `git status --short` | PASS | Only allowed files (see AC9). |
| `scripts/quality-baseline.ps1` (fresh run) | PASS | **OVERALL: PASS (exit 0), run id `20260804-171453` — 7/7 gates: env, python tests (562 passed, 19 skipped, 7 deselected), ruff, mypy, tsc, eslint, build** (see LOG). |

## Environment repairs (required to run the mandated baseline; no tracked content modified)

This task ran in a fresh git worktree (`prepare-s05-t01`). Two environment conditions blocked the mandated 7/7 baseline and were repaired without modifying any tracked file:

1. **Frontend `node_modules` absent** (git-ignored, not present in a fresh worktree). Fixed with `npm ci --no-audit --no-fund` (369 packages; `package-lock.json` unchanged). Baseline run #1 was `PREFLIGHT_BLOCKED` on Gate 1 before this.
2. **Legacy-import fixture trees missing from git** — `tests/fixtures/legacy_import/{valid,corrupt}/projects/` are **untracked in the repository** (they exist only as untracked files in the primary worktree; the same bytes were later committed on `codex/s06-t01` = `62b2bcd`). `tests/test_legacy_import_preview.py` and `tests/test_transactional_legacy_import.py` (both pre-existing S01 tests) require them, so Gate 2 failed 13 tests in this worktree even though the same suite passes 7/7 in the primary worktree where the files physically exist. Restored the 8 missing fixture files from their git blobs (`git show 62b2bcd:<path>`), created the empty `no_json/` directory the preview test expects, and reconciled the autocrlf stat cache on tracked fixtures (`git add` + `git reset`; content unchanged, verified byte-identical to blobs). After repair: the previously failing files report **53 passed** and the full baseline is 7/7 PASS. `git status` now mirrors the primary worktree exactly (same untracked fixture dirs, no tracked fixture modified).

This is a pre-existing repository condition (fixture files never committed to `master`/this branch), not a defect introduced by S05-T01. The S05-T01 contract itself adds no fixtures and no test files.

## Manual UX/media verification

Not applicable — contract-only task, no UI or media code. Preflight/probe behavior is specified (bounded, read-only, error taxonomy) for S05-T02+ to implement and test with synthetic `tmp_path` fixtures.

## Migration and rollback

None — no schema or migration change.

## Deviations from task

None.

## Out-of-scope findings

- The primary worktree `C:\Users\Admin\MotionForge2D` was only read at the preparation stage (pending S04 repair tree); nothing copied or modified. This session never touched it.
- The ROADMAP file was already modified (S04-T05 → APPROVED + sprint status) by the PM activation before this session started; it is PM-owned and out of my write scope. This session made no ROADMAP edit.

## Known limitations/risks

- 8 product decisions are deferred to PM (contract §9 B1–B8): input container allowlist, max file size/free-disk margin, minimum resolution/duration, ProRes/DNxHD, non-AAC audio, transcode-on-import, multi-stream selection, HDR/10-bit. The contract deliberately does not invent support beyond MP4/H.264/HEVC/AAC; S05-T02 implementation of import acceptance is blocked on B1/B2/B3/B5/B6 decisions where they change accept/reject behavior.
- Canonical timebase/CFR-VFR mapping is S05-T03 scope; preflight only records the CFR/VFR classification per PRD §9 Step 1.

## Recommended PM decision

`PENDING` — awaiting PM review per protocol (no self-approval; no commit; no roadmap edits; no next-task packet creation). Upon approval, S05-T02 (managed import copy/register with checksum) may start.

# Execution Log — Task S05-C03 (final lifecycle correction, round 3)

- [2026-08-05T17:35+07:00] Session packet created. Codex CHANGES_REQUESTED
  round 3 (fresh task, no resume): (1) orchestrator start/stop through the
  real FastAPI lifespan with startup scan-and-resume (no POST/GET/browser/
  advance_once); (2) TRUE process-lifecycle test (restart after import,
  restart after proxy); (3) source replacement with different SHA → NEW
  valid chain reaching completed via an explicit VideoItem/version
  supersession; (4) old jobs/artifacts/scenes immutable; chain state exposes
  only the current source; (5) GET read-only + all C02 guarantees preserved.

## Required reading (17:40 → 18:10 +07:00)

- TASK.md (full), SESSION_PROTOCOL.md, S05-C02/C01 REPORT+LOG.
- DURABLE_JOB_CONTRACT (§4.3/4.4/§5/§6/§8/§9/§10 — cited via the C02
  correction; supersession keeps job-state-machine semantics untouched),
  DURABLE_JOB_PERSISTENCE.md, DURABLE_WORKER.md, JOB_RECONCILIATION.md,
  MANAGED_ARTIFACT_CONTRACT.md, CANONICAL_TIMEBASE_PROXY_CONTRACT.md
  (idempotency-key shape `GENERATE_PROXY:video_item:<id>:<sha>:<generation>`),
  VIDEO_PREFLIGHT_CONTRACT.md (§3.1 + §6 idempotency shape
  `ANALYZE_MEDIA:<source_sha256>:<generation>`), VIDEO_IMPORT_V1_PM_DECISIONS.md,
  PERSISTENCE_DOMAIN_CONTRACT.md (§4 VideoItem pipeline unit owning scene
  rows; §5 archive never cascades, rows stay queryable).
- Code: app/api/app.py (lifespan), app/workflow/analyze_orchestrator.py
  (full), app/workflow/job_service.py (public surface: registers the S05
  handlers on its own worker; `start_worker`/`stop_worker`),
  app/services/{video_import,timebase,video_proxy,scene_detector}.py
  (reference only — scene rows are scoped by `video_item_id` and
  `_commit_scene_rows` FAILS CLOSED on evidence mismatch, which is why
  supersession needs a NEW VideoItem), app/api/routes/projects.py
  (thin analyze endpoints), frontend api.ts + import-analyze, git status.
- Verified the C02 gap this task closes: C02's REPORT explicitly flagged
  "wiring get_analyze_orchestrator().start() into the app lifespan … is
  outside this task's write scope".

## Implementation (18:10 → 18:40 +07:00)

- `app/api/app.py` — lifespan wiring: after `Lifecycle.initialize()` +
  `Lifecycle.start()` (worker up) the lifespan calls
  `analyze_orchestrator.get_analyze_orchestrator().ensure_started()`; the
  shutdown `finally` calls `…stop(timeout=5.0)` BEFORE `lifecycle.stop()`
  (no new chain Jobs while the worker drains). Docstring updated.
- `app/workflow/analyze_orchestrator.py`:
  - `start()` now runs ONE synchronous idempotent `advance_once()` before
    spawning the loop thread — the startup scan-and-resume: on process
    boot every incomplete chain's next Job is materialized immediately,
    without waiting for the first poll tick and without any API request.
  - `submit_chain` source supersession: when the submitted source SHA
    differs from the current chain identity, `_supersede_video_item`
    archives the previous VideoItem (status=`archived`, `archived_at` set;
    its jobs/artifacts/scenes NEVER touched — PERSISTENCE_DOMAIN_CONTRACT
    §5) and creates a NEW VideoItem (next free position) as the pipeline
    unit for the new source. The new chain then completes on fresh rows —
    never overwriting/silently reusing old Scene evidence.
  - `_chain_video_items` + `_advance_item` skip archived VideoItems — a
    superseded chain is frozen at its terminal rows; the background scan
    never creates successor Jobs for a replaced source.
  - Module docstring documents the lifespan ownership + supersession.
  - Public API unchanged (submit_chain/chain_state/retry_chain/advance_once/
    start/stop/ensure_started/running + accessor/reset).
- `tests/test_s05_lifecycle.py` — NEW (3 tests):
  1. `test_process_lifecycle_restart_resumes_chain_without_api_requests` —
     the binary AC: POST once → import completes → FULL first-app shutdown
     → FRESH app over the same DB → NO analyze API request → proxy job
     materializes (synchronously during lifespan startup) and completes →
     restart again → scene job materializes and completes. Cadence-blocked
     test orchestrator (poll loop never advances on its own) makes the
     restart materialization attributable ONLY to the startup scan.
  2. `test_lifespan_owned_chain_completes_across_real_restarts` — same AC
     with the REAL accessor + REAL cadence: 4 app generations over one DB,
     exactly one POST, zero analyze API calls afterwards, exactly one
     effect set per step, a further restart duplicates nothing.
  3. `test_replace_source_supersedes_video_item_new_chain_completes` —
     different-evidence replacement → new VideoItem identity, old item
     archived, old rows byte-identical (full-row evidence snapshot incl.
     managed-file hashes), new chain completes with distinct jobs/scenes/
     artifacts, chain state exposes only the current source, GET read-only
     (DB snapshot equality around repeated GETs); identical-evidence
     re-encode → third distinct identity, completes; everything before
     stays immutable and frozen.
- `tests/test_s05_chain_progression.py` — the round-2 replacement test
  encoded the OLD semantics (same VideoItem, scene step fails closed with
  SCENE_EVIDENCE_CONFLICT). C03's contract requires the new chain to
  COMPLETE via the supersession lifecycle, so that test was updated to the
  corrected contract (documented deviation — same precedent as C02's test
  updates): distinct VideoItem identity per source SHA, old rows immutable,
  new chain completes, chain state exposes only the current source. All
  other 8 tests untouched (concurrency/retry/GET-zero-mutation/CFR/VFR).
- `frontend/e2e/import-analyze.spec.ts` — cancel test made deterministic
  against the C03 backend: the chain now advances under the lifespan-owned
  loop and can complete all three steps in ~2s, so the test clicks the
  cancel button at the START of the proxy step's active window (queued or
  running) instead of waiting for "running" first (which could miss the
  window entirely and stall the click). Same intent, same assertions.
- No changes: app/services/*, app/workflow/durable_worker.py, job-state
  machine, schema/migration, channels.json, data/, MAIN tree, S06
  worktrees. No commit/push/deploy; no reset/checkout/clean/delete.

## Targeted verification (18:40 → 19:20 +07:00) — each separately

- [18:40] `python -m pytest -q tests/test_s05_lifecycle.py -p no:cacheprovider`
  → **3 passed** (20.7s).
- [18:45] `python -m pytest -q tests/test_s05_chain_progression.py -p no:cacheprovider`
  → **9 passed** (12.7s).
- [18:47] `python -m pytest -q tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -p no:cacheprovider`
  → **21 passed** (20.8s).
- [18:50] S05 regression set (timebase+proxy+import+scene_detection+chunk_stitch)
  → **113 passed, 5 skipped** (38.7s).
- [18:55] Durable set (worker+job_api+persistence+reconciliation+managed_artifacts+ffmpeg_discovery)
  → **184 passed, 2 skipped** (48.6s).
- [19:00] `ruff check app tests` → **All checks passed** (fixed 9 SIM118 +
  5 F841 in the new test file); `mypy app` → **Success, 66 source files**;
  `git diff --check` → exit 0 (only pre-existing CRLF advisories).
- [19:05] frontend `tsc --noEmit` → exit 0; `eslint src/ e2e/` → 0 errors
  (9 pre-existing warnings).

## Live QA + Playwright (19:10 → 19:35 +07:00)

- [19:10] Restarted the stale C02 QA backend (:8003, `output/s05t05_qa_backend.py`)
  with the C03 code; fresh frontend dev server on :3011 (the C02-era Next
  dev process had hung — the known "Next dev lâu → page.goto hang" issue).
- [19:15] LIVE process-lifecycle smoke
  (`output/s05-c03-live-restart-smoke.py`): POST /analyze once → import
  claimed (running) → backend KILLED mid-import (crash) → fresh backend
  over the SAME QA database → NO analyze API request (SQLite reads only) →
  T02→T03→T04 all completed by the lifespan-owned orchestrator scan +
  durable worker; exactly 1 import + 1 proxy + 1 scene job; 1 scene row;
  final read-only GET /analyze → completed, progress 100%. **PASS**.
- [19:25] Playwright interaction suite (`playwright.s05t05.config.ts`,
  real API :8003 + frontend :3011): first run 5/6 — the cancel test
  stalled because the C03 backend completes the whole chain in ~2s (the
  click could no longer land in the proxy "running" window). Test made
  deterministic (click at the START of the active window) → **6 passed
  (19.6s)**.
- [19:32] Visual suite (`playwright.s05t05-visual.config.ts`): desktop
  1280×800 + 390×844 → **6 passed (18.6s)**; 10 fresh screenshots in
  `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/screenshots/`
  (setup, file-selected, progress, completed, preflight-error × desktop +
  390px).
- [19:35] Fresh `scripts/quality-baseline.ps1` → **OVERALL: PASS, 7/7 gates**
  — Run ID **`20260805-181617`** (Gate 2: 719 passed, 19 skipped, 7
  deselected, 212.00s). Summary:
  `output/quality-baseline/20260805-181617/summary.json`.

## Deliverables

- LOG.md + REPORT.md (this task), status **SUBMITTED** (never APPROVED).
- Correction appendices appended (do not rewrite history): S05-C02 REPORT,
  S05-C01/T05/T06 REPORTS, `output/SPRINT_EXIT_REPORT.md`,
  `output/SPRINT_S05_SESSIONS_TRACKING.md`, `docs/pm/ROADMAP.md` S05 rows.
- Stop after SUBMITTED — Codex performs the sprint-exit review.

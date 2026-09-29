# Task S05-C01: Approved-pipeline orchestration + successor retry (Sprint exit correction)

- **Task ID:** `S05-C01`
- **Sprint:** `S05` (Import/analyze vertical slice) — Sprint exit correction
- **Status:** `READY`
- **Owner:** Hermes (worktree `prepare-s05-t01`)
- **Depends On:** `S05-T06` (Codex CHANGES_REQUESTED at sprint exit)

## Context (Codex-verified blockers)

Sprint exit was rejected for two blockers:

1. The S05-T05 UI calls `POST /api/projects/{project_id}/ingest`. That
   endpoint creates the legacy `ingest` job and runs the old
   probe → PySceneDetect → scene slicing pipeline. It does NOT drive the
   approved S05 pipeline:
   S05-T02 `ANALYZE_MEDIA` import → S05-T03 `GENERATE_PROXY` →
   S05-T04 `ANALYZE_MEDIA` scene_detect.
2. Retry is not functional. Re-submitting the same legacy ingest endpoint
   returns 500 `IdempotencyKeyInUse`. Rendering that refusal honestly does
   not satisfy the retry acceptance criterion.

## Outcome

A UI-facing API orchestration path drives the REAL T02→T03→T04 durable jobs
and exposes backend-owned chain state to the UI; a real successor-job retry
path exists for failed/cancelled work with owner validation, idempotency and
refetch after mutation. No mocked progress or mocked job state.

## Outcome scope

- Backend: one UI-facing submission endpoint that creates the approved job
  chain (T02 import → T03 proxy → T04 scene detect) via the existing approved
  job classes (ANALYZE_MEDIA import step, GENERATE_PROXY, ANALYZE_MEDIA
  scene_detect step). The S05-T04 dispatcher already routes these — reuse it.
- Backend-owned chain state endpoint (or extended job-state response) the UI
  can render: which step is active (import/proxy/scene_detect), progress from
  real checkpoints, terminal states.
- Successor-job retry: a retry endpoint for failed/cancelled jobs that creates
  a successor Job (per DURABLE_JOB_CONTRACT §8.5) with owner validation and
  idempotency; duplicate retries reuse, not 500-refuse-without-path.
- UI: wire Import/Analyze UI to the new endpoints; remove the legacy
  `/ingest` call; keep real progress/cancel/retry/resume + refetch; desktop +
  390px QA against the corrected real API.
- Tests: API test proving ONE UI-facing submission drives T02→T03→T04; CFR +
  VFR completion through that API; proxy SHA/size/containment; stable Scene
  IDs; cancel during active processing; successful retry after failed/
  cancelled using a successor Job; restart/resume without duplicate
  publication; orphan cleanup.

## Required reading

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table)
3. `docs/architecture/DURABLE_JOB_CONTRACT.md` — full (esp. §3 job classes,
   §4.3/4.4 state machines, §6 retry classification, §8 idempotency/replay/
   successor, §9 staging/publication/cleanup, §10 error envelope)
4. `docs/architecture/DURABLE_JOB_API_CUTOVER.md` — approved job API surface
5. `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
6. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
7. `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
8. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1 CFR/VFR)
9. `app/workflow/job_service.py` (ANALYZE_MEDIA dispatcher routing
   import/scene_detect; GENERATE_PROXY registration)
10. `app/services/video_import.py`, `app/services/timebase.py`,
    `app/services/video_proxy.py`, `app/services/scene_detector.py`
    (reference; do NOT modify)
11. `app/api/routes/projects.py` — the legacy `ingest` endpoint (line ~239)
    and the pattern for adding endpoints
12. `docs/pm/sessions/S05-T05-import-analyze-ui/REPORT.md` + `LOG.md`
13. `docs/pm/sessions/S05-T06-golden-integration/REPORT.md` + `LOG.md`
14. `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/`
    (current UI wiring)
15. Current `git status` and focused S05 diffs

## Allowed write scope

- `app/api/routes/projects.py` (or a new focused route module) — add
  orchestration + chain-state + retry endpoints; do NOT remove existing
  approved endpoints unless they are the legacy `ingest` one the correction
  replaces for UI use
- `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/` UI
- New test file(s): `tests/test_s05_orchestration.py` (and extend golden
  integration if needed)
- This task's `LOG.md`/`REPORT.md`

## Forbidden scope

- Do NOT modify `app/services/video_import.py`, `timebase.py`,
  `video_proxy.py`, `scene_detector.py`, `scene_detection.py`
- Do NOT modify `app/workflow/durable_worker.py` or the job-state machine
  semantics (reuse existing successor/checkpoint APIs)
- No schema/migration changes
- Do NOT touch: `channels.json`, any `data/`, database, MAIN tree, S06 worktrees
- No commit/push/deploy; no reset/checkout/clean/restore/delete of user data
- Preserve all uncommitted changes; no mock/fake progress or job state

## Binary acceptance criteria

1. ONE UI-facing submission drives the real T02→T03→T04 chain (API test
   proves each step's durable job is created/completed in order).
2. Chain state exposed to UI is backend-owned (real checkpoints), no mock.
3. Retry of a failed/cancelled job creates a successor Job (§8.5) with owner
   validation + idempotency; duplicate retry is idempotent (reuse), and
   retry-after-failure succeeds (not 500-without-path).
4. Cancel during active processing cleans the attempt's own staging; committed
   artifacts survive; orphan cleanup never deletes committed files.
5. Restart/resume produces no duplicate publication (SHA/size/containment
   verified; stable Scene IDs).
6. CFR and VFR both complete through the orchestration API.
7. UI no longer calls the legacy `/ingest` endpoint; renders real chain state.
8. `ruff`, `mypy`, `git diff --check`, frontend `tsc`/`eslint` pass; targeted
   backend regressions pass; fresh `scripts/quality-baseline.ps1` = 7/7.

## Targeted verification (run separately)

1. New orchestration tests (`tests/test_s05_orchestration.py`)
2. Golden integration tests (`tests/test_s05_golden_integration.py`)
3. Full S05 regression set: `test_timebase.py`, `test_video_proxy.py`,
   `test_video_import.py`, `test_scene_detection.py`,
   `test_scene_chunk_stitch.py`
4. Durable worker/artifact/reconciliation regressions
5. Frontend `tsc --noEmit` + `eslint`
6. Ruff
7. Mypy
8. `git diff --check`
9. Fresh `scripts/quality-baseline.ps1` (record Run ID)
10. Playwright desktop + 390px against the corrected real API (screenshots)

## REPORT.md must list

- changed files
- exact test commands/results
- Quality Run ID
- one-submission-drives-T02→T03→T04 evidence
- CFR + VFR completion evidence
- proxy SHA/size/containment evidence
- stable Scene ID evidence
- cancel-during-active evidence
- successor retry success evidence (failed + cancelled)
- restart/resume no-duplicate-publication evidence
- orphan cleanup evidence
- Playwright desktop + 390px evidence (no mock)
- status `SUBMITTED` (never APPROVED)

## Update honest reports

After all evidence passes, update `S05-T05` and `S05-T06` REPORT.md with a
correction section pointing to this task's REPORT (do not rewrite history;
append the correction). Update `output/SPRINT_EXIT_REPORT.md` honestly.
Stop after SUBMITTED — Codex performs the sprint-exit review.

# Task S05-C03: Final lifecycle correction (Sprint exit CHANGES_REQUESTED round 3)

- **Task ID:** `S05-C03`
- **Sprint:** `S05` (Import/analyze vertical slice) — Sprint exit correction round 3
- **Status:** `READY`
- **Owner:** Hermes (worktree `prepare-s05-t01`)
- **Depends On:** `S05-C02` (Codex CHANGES_REQUESTED — final lifecycle)

## Context (Codex-verified blockers)

1. Start and stop `AnalyzeChainOrchestrator` through the real FastAPI
   application lifespan. On application startup it must scan and resume
   incomplete chains WITHOUT requiring POST, GET, browser polling or manual
   `advance_once()` calls.
2. Add a true process-lifecycle test:
   - POST once; complete only import;
   - fully shut down the first TestClient/app lifespan;
   - create a fresh app/TestClient over the same database;
   - issue NO analyze API request;
   - prove proxy and scene jobs materialize and complete.
   Repeat restart after proxy.
3. Replacing a source with a different SHA must produce a NEW valid chain
   that reaches completed. Do NOT overwrite or silently reuse old Scene
   evidence. Use an explicit VideoItem/version/supersession lifecycle
   consistent with existing contracts.
4. Add test proving:
   - old jobs/artifacts/scenes remain immutable;
   - new source gets distinct identity and outputs;
   - new chain completes successfully;
   - chain state exposes only the selected/current source.
5. Keep GET read-only and preserve all C02 concurrency/retry guarantees.
6. Synchronize TASK status to SUBMITTED when finished. Run targeted suites,
   real lifecycle tests, Playwright desktop/mobile and fresh 7/7 baseline.
   Stop at SUBMITTED for Codex review.

## Outcome

The orchestrator lifecycle is owned by the FastAPI application lifespan
(startup scans/resumes incomplete chains; shutdown stops cleanly). Process
restart between steps is proven by a true lifecycle test. Source replacement
creates a distinct superseding chain identity; old evidence stays immutable;
chain state exposes only the current source. All C02 guarantees preserved.

## Required reading

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/sessions/S05-C03-final-lifecycle-correction/TASK.md` (this file)
3. `docs/architecture/DURABLE_JOB_CONTRACT.md` — full (§4.3/4.4 state
   machines, §5 leases/fencing, §6 retry, §8 idempotency/replay/successor,
   §9 staging/publication/cleanup, §10 error envelope)
4. `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
5. `docs/architecture/DURABLE_WORKER.md` + `JOB_RECONCILIATION.md`
6. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
7. `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
8. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1 CFR/VFR)
9. `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md` — idempotency key
   shape, generation/version semantics, supersession
10. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` — VideoItem/version/
    scene supersession lifecycle
11. `app/api/app.py` — the FastAPI lifespan (lines ~37-74) — wire orchestrator
12. `app/workflow/analyze_orchestrator.py` — full (start/stop/ensure_started/
    submit/chain_state/retry/advance_once; add scan-and-resume on start if
    missing)
13. `app/workflow/job_service.py` — public surface
14. `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
    `scene_detector.py` (reference; do NOT modify)
15. `app/api/routes/projects.py` — POST/GET /analyze + retry (thin routes)
16. `docs/pm/sessions/S05-C02-durable-chain-progression/REPORT.md` + `LOG.md`
17. `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/REPORT.md` + `LOG.md`
18. `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/`
19. Current `git status` and focused S05 diffs

## Allowed write scope

- `app/api/app.py` — wire orchestrator start/stop into the lifespan
- `app/workflow/analyze_orchestrator.py` — add startup scan-and-resume of
  incomplete chains (idempotent; lease/fence-safe) if not already present;
  keep public API stable
- `app/api/routes/projects.py` — only if the source-supersession contract
  needs a thin route adjustment (keep GET read-only)
- Frontend `api.ts`/`import-analyze` only if chain-state shape changes
- New test file(s): `tests/test_s05_lifecycle.py`
- This task's `LOG.md`/`REPORT.md`

## Forbidden scope

- Do NOT modify `app/services/video_import.py`, `timebase.py`,
  `video_proxy.py`, `scene_detector.py`, `scene_detection.py`
- Do NOT modify `app/workflow/durable_worker.py` or job-state-machine
  semantics
- No schema/migration changes
- Do NOT touch: `channels.json`, any `data/`, database, MAIN tree, S06 worktrees
- No commit/push/deploy; no reset/checkout/clean/restore/delete of user data
- Preserve all uncommitted changes; no mock/fake progress or job state

## Binary acceptance criteria

1. Orchestrator start/stop wired into FastAPI lifespan; startup scans and
   resumes incomplete chains WITHOUT POST/GET/browser/advance_once.
2. True lifecycle test passes: POST once → import completes → first
   app/TestClient fully shut down → fresh app/TestClient over same DB → NO
   analyze API request → proxy and scene jobs materialize and complete.
   Repeat restart after proxy (same proof).
3. Source replacement with different SHA produces a NEW valid chain reaching
   completed; old Scene evidence NOT overwritten or silently reused; explicit
   VideoItem/version/supersession lifecycle per contracts.
4. Test: old jobs/artifacts/scenes immutable; new source distinct identity +
   outputs; new chain completes; chain state exposes only current source.
5. GET read-only maintained; C02 concurrency (one successor per step) and
   retry idempotency guarantees preserved (existing tests still pass).
6. `ruff`, `mypy`, `git diff --check`, frontend `tsc`/`eslint` pass; targeted
   suites pass; fresh `scripts/quality-baseline.ps1` = 7/7.

## Targeted verification (run separately)

1. New lifecycle tests (`tests/test_s05_lifecycle.py`)
2. Chain progression tests (`tests/test_s05_chain_progression.py`)
3. Orchestration tests (`tests/test_s05_orchestration.py`)
4. Golden integration tests (`tests/test_s05_golden_integration.py`)
5. Full S05 regression set
6. Durable worker/artifact/reconciliation regressions
7. Frontend `tsc --noEmit` + `eslint`
8. Ruff
9. Mypy
10. `git diff --check`
11. Fresh `scripts/quality-baseline.ps1` (record Run ID)
12. Playwright desktop + 390px against real API

## REPORT.md must list

- changed files
- exact test commands/results
- Quality Run ID
- lifespan wiring evidence (startup resume without API calls)
- process-lifecycle evidence (restart after import; restart after proxy)
- source-replacement supersession evidence (new identity, old immutable)
- GET read-only + C02 guarantee preservation evidence
- Playwright desktop + 390px evidence
- status `SUBMITTED` (never APPROVED)

## Update honestly

Append correction section to S05-C02 REPORT, S05-C01/T05/T06 REPORT,
`output/SPRINT_EXIT_REPORT.md`, `output/SPRINT_S05_SESSIONS_TRACKING.md`,
`docs/pm/ROADMAP.md` S05 rows. Do not rewrite history — append. Stop after
SUBMITTED — Codex performs sprint-exit review.

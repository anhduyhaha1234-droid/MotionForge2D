# Start Prompt — Task S05-C03: Final lifecycle correction

Execute S05-C03 in this worktree (`C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`).

## Hard worktree guard

Before ANY write, run and verify:
1. `pwd` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
2. `git rev-parse --show-toplevel` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
3. `git status --short`

If `pwd` is wrong, `cd` to the expected root and re-verify. If git toplevel
differs, write nothing, report `BLOCKED: WRONG_WORKTREE`, and exit immediately.
Every path you write must be under the expected root. Never write to
`C:\Users\Admin\MotionForge2D` (MAIN tree) or any S06 worktree.

## Context (Codex CHANGES_REQUESTED round 3 — final lifecycle)

1. Start/stop `AnalyzeChainOrchestrator` through the real FastAPI app
   lifespan. On startup it must scan and resume incomplete chains WITHOUT
   POST, GET, browser polling or manual `advance_once()` calls.
2. True process-lifecycle test: POST once → complete only import → fully shut
   down first TestClient/app lifespan → fresh app/TestClient over same DB →
   NO analyze API request → proxy and scene jobs materialize and complete.
   Repeat restart after proxy.
3. Replacing source with different SHA → NEW valid chain reaching completed;
   do NOT overwrite/silently reuse old Scene evidence; explicit
   VideoItem/version/supersession lifecycle per contracts.
4. Test: old jobs/artifacts/scenes immutable; new source distinct identity +
   outputs; new chain completes; chain state exposes only current source.
5. Keep GET read-only; preserve ALL C02 concurrency/retry guarantees.

## Read completely

- `docs/pm/SESSION_PROTOCOL.md`
- `docs/pm/sessions/S05-C03-final-lifecycle-correction/TASK.md` (full — your contract)
- `docs/architecture/DURABLE_JOB_CONTRACT.md` (§4.3/4.4, §5, §6, §8, §9, §10)
- `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
- `docs/architecture/DURABLE_WORKER.md` + `JOB_RECONCILIATION.md`
- `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1)
- `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md`
- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` (VideoItem/version/scene
  supersession)
- `app/api/app.py` (lifespan lines ~37-74 — wire orchestrator)
- `app/workflow/analyze_orchestrator.py` (full — start/stop/ensure_started/
  submit/chain_state/retry/advance_once; add scan-and-resume on start if
  missing)
- `app/workflow/job_service.py` (public surface)
- `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
  `scene_detector.py` (reference; do NOT modify)
- `app/api/routes/projects.py` (POST/GET /analyze + retry)
- `docs/pm/sessions/S05-C02-durable-chain-progression/REPORT.md` + `LOG.md`
- `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/REPORT.md` + `LOG.md`
- `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/`
- current `git status` and focused S05 diffs

## Implement

1. Wire orchestrator start/stop into the FastAPI lifespan; startup scans and
   resumes incomplete chains (idempotent, lease/fence-safe) with NO API calls.
2. True process-lifecycle test (restart after import; restart after proxy).
3. Source-replacement supersession: distinct chain identity per source SHA,
   old evidence immutable, chain state exposes only current source.
4. Keep GET read-only; preserve C02 guarantees (existing tests must still pass).

Stay inside TASK.md allowed write scope. Bounded individual commands only.

## Verify (each separately)

1. New lifecycle tests
2. Chain progression tests
3. Orchestration tests
4. Golden integration tests
5. Full S05 regression set
6. Durable worker/artifact/reconciliation regressions
7. Frontend `tsc --noEmit` + `eslint`
8. Ruff
9. Mypy
10. `git diff --check`
11. Fresh `scripts/quality-baseline.ps1` — record Run ID
12. Playwright desktop + 390px against real API

## Report

Update `docs/pm/sessions/S05-C03-final-lifecycle-correction/LOG.md` with real
evidence, write `REPORT.md` (all evidence listed in TASK.md), end status
`SUBMITTED` (never APPROVED, never self-approve). Append honest correction
sections to S05-C02/C01/T05/T06 REPORT.md, `output/SPRINT_EXIT_REPORT.md`,
`output/SPRINT_S05_SESSIONS_TRACKING.md`, `docs/pm/ROADMAP.md` S05 rows.
Do not rewrite history — append. Do not commit/push/deploy; no
reset/checkout/clean/delete of user data; preserve all uncommitted changes;
do not touch `channels.json`, `data/`, database, MAIN tree, or S06 worktrees.
NO MOCK data. Stop after SUBMITTED — Codex performs sprint-exit review.

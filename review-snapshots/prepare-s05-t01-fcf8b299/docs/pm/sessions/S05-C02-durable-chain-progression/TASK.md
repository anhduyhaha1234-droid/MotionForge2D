# Task S05-C02: Durable chain progression correction (Sprint exit CHANGES_REQUESTED)

- **Task ID:** `S05-C02`
- **Sprint:** `S05` (Import/analyze vertical slice) — Sprint exit correction round 2
- **Status:** `READY`
- **Owner:** Hermes (worktree `prepare-s05-t01`)
- **Depends On:** `S05-C01` (Codex CHANGES_REQUESTED — durable chain progression)

## Context (Codex-verified blockers)

Codex: "Manager verification must test the acceptance outcome adversarially.
Do not approve a pipeline merely because tests call helper/read endpoints that
secretly advance it. Read-only endpoints must not mutate state."

Blockers to fix:

1. `GET /api/projects/{id}/analyze` must be read-only. It must NOT create
   proxy or scene-detection Jobs.
2. After exactly one `POST /analyze`, the approved T02→T03→T04 chain must
   progress under backend worker/reconciler ownership even when:
   - the browser closes immediately;
   - no GET polling occurs;
   - the API process restarts between steps.
3. Move chain progression out of the projects route into a focused durable
   workflow/orchestration service. Do NOT access JobService private members
   from the route. Keep the route thin.
4. Bind chain identity to immutable input evidence: source SHA-256 plus
   generation/version as required by the existing contracts. Replacing the
   project source must NOT silently reuse results from the previous video.
5. Add independent tests (listed below).
6. Synchronize TASK, tracking, ROADMAP and sprint-exit status honestly.
   End at SUBMITTED, never APPROVED.

## Outcome

The approved T02→T03→T04 chain advances entirely under worker/reconciler
ownership from a single POST; GET is strictly read-only; chain identity is
bound to source SHA-256 + generation; route is thin; orchestration lives in a
focused durable service.

## Required reading

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/sessions/S05-C02-durable-chain-progression/TASK.md` (this file)
3. `docs/architecture/DURABLE_JOB_CONTRACT.md` — full (§3 job classes,
   §4.3/4.4 state machines, §5 leases/fencing, §6 retry classification,
   §8 idempotency/replay/successor, §9 staging/publication/cleanup,
   §10 error envelope)
4. `docs/architecture/DURABLE_JOB_PERSISTENCE.md` — schema/repository
5. `docs/architecture/DURABLE_WORKER.md` — worker/reconciler ownership
6. `docs/architecture/JOB_RECONCILIATION.md` — reconciler semantics
7. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` — containment, atomic
8. `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
9. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1 CFR/VFR)
10. `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md` — idempotency key
    shape, generation semantics
11. `app/workflow/job_service.py` — ANALYZE_MEDIA dispatcher, GENERATE_PROXY
    registration, successor APIs (public surface ONLY; do NOT rely on private
    attributes from routes)
12. `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
    `scene_detector.py` (reference; do NOT modify)
13. `app/api/routes/projects.py` — current `POST/GET /analyze` + `/analyze/retry`
    (lines ~2551-2660) — the route to be slimmed
14. `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/REPORT.md` +
    `LOG.md` — the orchestration that Codex reviewed
15. `docs/pm/sessions/S05-T05-import-analyze-ui/REPORT.md` + `LOG.md`
16. `docs/pm/sessions/S05-T06-golden-integration/REPORT.md` + `LOG.md`
17. `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/`
18. Current `git status` and focused S05 diffs

## Allowed write scope

- New focused orchestration service module, e.g. `app/workflow/analyze_orchestrator.py`
- `app/api/routes/projects.py` — slim the analyze endpoints (thin routes
  calling the orchestrator; GET strictly read-only; no private-member access)
- `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/` if UI
  calls must change (keep UI honest with backend-owned chain state)
- New test file(s): `tests/test_s05_chain_progression.py`
- This task's `LOG.md`/`REPORT.md`

## Forbidden scope

- Do NOT modify `app/services/video_import.py`, `timebase.py`,
  `video_proxy.py`, `scene_detector.py`, `scene_detection.py`
- Do NOT modify `app/workflow/durable_worker.py` or job-state-machine
  semantics (reuse existing public successor/checkpoint APIs)
- Do NOT access private members (`_...`) of JobService/worker from routes
- No schema/migration changes
- Do NOT touch: `channels.json`, any `data/`, database, MAIN tree, S06 worktrees
- No commit/push/deploy; no reset/checkout/clean/restore/delete of user data
- Preserve all uncommitted changes; no mock/fake progress or job state

## Binary acceptance criteria

1. `GET /api/projects/{id}/analyze` is read-only: repeated/concurrent GETs
   cause ZERO database mutations (job rows, artifacts, scene rows).
2. Exactly one `POST /analyze` → T02 import → T03 proxy → T04 scene detect
   completes under worker/reconciler ownership with:
   - browser closing immediately after POST;
   - no GET polling;
   - API process restart after import and after proxy.
3. Chain progression lives in a focused durable orchestration service; routes
   are thin and never touch JobService private members.
4. Chain identity bound to source SHA-256 + generation/version; replacing the
   project source with a different video does NOT reuse the stale chain
   (new identity → new chain; old artifacts not silently reused).
5. Concurrent advancement creates exactly one successor per step
   (lease/fencing respected).
6. Failure/cancel successor retry remains idempotent (existing behavior kept).
7. CFR + VFR complete through the chain; containment, SHA/size, stable Scene
   IDs, orphan cleanup regressions pass.
8. `ruff`, `mypy`, `git diff --check`, frontend `tsc`/`eslint` pass; targeted
   suites pass; fresh `scripts/quality-baseline.ps1` = 7/7.

## Independent tests required (TASK.md §5 of the correction)

1. POST once, then NO GET calls; worker/reconciler completes T02→T03→T04.
2. API restart after import and after proxy; chain completes.
3. GET repeated/concurrent causes zero DB mutations.
4. Replace source video with same project/default request; stale chain is not
   reused.
5. Concurrent advancement creates exactly one successor per step.
6. Existing failure/cancel successor retry remains idempotent.
7. CFR/VFR, containment, SHA/size, Scene IDs and orphan cleanup regressions.

## Targeted verification (run separately)

1. New chain-progression tests
2. Existing orchestration tests (`tests/test_s05_orchestration.py`)
3. Golden integration tests (`tests/test_s05_golden_integration.py`)
4. Full S05 regression set
5. Durable worker/artifact/reconciliation regressions
6. Frontend `tsc --noEmit` + `eslint`
7. Ruff
8. Mypy
9. `git diff --check`
10. Fresh `scripts/quality-baseline.ps1` (record Run ID)
11. Playwright desktop + 390px against corrected real API

## REPORT.md must list

- changed files
- exact test commands/results
- Quality Run ID
- read-only-GET evidence (zero mutations)
- POST-once-no-GET chain completion evidence
- API-restart evidence (after import, after proxy)
- source-replacement stale-chain evidence
- single-successor-per-step evidence
- successor retry idempotency evidence
- CFR/VFR, containment, SHA/size, Scene IDs, orphan cleanup evidence
- Playwright desktop + 390px evidence
- status `SUBMITTED` (never APPROVED)

## Update honestly

Append correction section to S05-C01 REPORT, S05-T05/T06 REPORT,
`output/SPRINT_EXIT_REPORT.md`, `output/SPRINT_S05_SESSIONS_TRACKING.md`, and
`docs/pm/ROADMAP.md` S05 rows (S05-C02 status). Do not rewrite history —
append. Stop after SUBMITTED — Codex performs sprint-exit review.

# Start Prompt — Task S05-C02: Durable chain progression correction

Execute S05-C02 in this worktree (`C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`).

## Hard worktree guard

Before ANY write, run and verify:
1. `pwd` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
2. `git rev-parse --show-toplevel` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
3. `git status --short`

If `pwd` is wrong, `cd` to the expected root and re-verify. If git toplevel
differs, write nothing, report `BLOCKED: WRONG_WORKTREE`, and exit immediately.
Every path you write must be under the expected root. Never write to
`C:\Users\Admin\MotionForge2D` (MAIN tree) or any S06 worktree.

## Context (Codex CHANGES_REQUESTED — adversarial verification)

- `GET /api/projects/{id}/analyze` must be READ-ONLY — must NOT create proxy
  or scene-detection Jobs.
- After exactly one `POST /analyze`, the approved T02→T03→T04 chain must
  progress under backend worker/reconciler ownership even when: browser closes
  immediately; no GET polling occurs; API process restarts between steps.
- Move chain progression out of the projects route into a focused durable
  workflow/orchestration service. Do NOT access JobService private members
  from the route. Keep the route thin.
- Bind chain identity to immutable input evidence: source SHA-256 plus
  generation/version per existing contracts. Replacing the project source must
  NOT silently reuse results from the previous video.

## Read completely

- `docs/pm/SESSION_PROTOCOL.md`
- `docs/pm/sessions/S05-C02-durable-chain-progression/TASK.md` (full — your contract)
- `docs/architecture/DURABLE_JOB_CONTRACT.md` (§3, §4.3/4.4, §5 leases,
  §6 retry, §8 idempotency/replay/successor, §9 staging/publication/cleanup,
  §10 error envelope)
- `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
- `docs/architecture/DURABLE_WORKER.md`
- `docs/architecture/JOB_RECONCILIATION.md`
- `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1)
- `docs/architecture/VIDEO_IMPORT_V1_PM_DECISIONS.md`
- `app/workflow/job_service.py` (PUBLIC surface only)
- `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
  `scene_detector.py` (reference; do NOT modify)
- `app/api/routes/projects.py` (POST/GET /analyze + /analyze/retry,
  ~lines 2551-2660 — slim these)
- `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/REPORT.md` + `LOG.md`
- `docs/pm/sessions/S05-T05-import-analyze-ui/REPORT.md` + `LOG.md`
- `docs/pm/sessions/S05-T06-golden-integration/REPORT.md` + `LOG.md`
- `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/`
- current `git status` and focused S05 diffs

## Implement

1. Focused durable orchestration service (e.g. `app/workflow/analyze_orchestrator.py`)
   owning chain progression: POST → T02 import → T03 proxy → T04 scene detect
   under worker/reconciler ownership; chain identity bound to source SHA-256 +
   generation/version.
2. Slim the analyze routes: POST creates/submits via the orchestrator; GET is
   strictly read-only (zero mutations on repeat/concurrent); retry uses the
   orchestrator's successor path. No private-member access from routes.
3. UI keeps honest backend-owned chain state (adjust api.ts/import-analyze if
   the GET contract shape changes).
4. Tests in TASK.md §"Independent tests required" — write them adversarially:
   POST-once-no-GET; API restart after import and after proxy; GET
   repeated/concurrent zero mutations; source replacement stale-chain not
   reused; single successor per step under concurrency; successor retry
   idempotent; CFR/VFR + containment + SHA/size + Scene IDs + orphan cleanup.

Stay inside TASK.md allowed write scope. Bounded individual commands only.

## Verify (each separately)

1. New chain-progression tests
2. Existing orchestration tests
3. Golden integration tests
4. Full S05 regression set
5. Durable worker/artifact/reconciliation regressions
6. Frontend `tsc --noEmit` + `eslint`
7. Ruff
8. Mypy
9. `git diff --check`
10. Fresh `scripts/quality-baseline.ps1` — record Run ID
11. Playwright desktop + 390px against corrected real API

## Report

Update `docs/pm/sessions/S05-C02-durable-chain-progression/LOG.md` with real
evidence, write `REPORT.md` (all evidence listed in TASK.md), end status
`SUBMITTED` (never APPROVED, never self-approve). Append honest correction
sections to S05-C01/T05/T06 REPORT.md, `output/SPRINT_EXIT_REPORT.md`,
`output/SPRINT_S05_SESSIONS_TRACKING.md`, and `docs/pm/ROADMAP.md` S05 rows.
Do not rewrite history — append. Do not commit/push/deploy; no
reset/checkout/clean/delete of user data; preserve all uncommitted changes;
do not touch `channels.json`, `data/`, database, MAIN tree, or S06 worktrees.
NO MOCK data. Stop after SUBMITTED — Codex performs sprint-exit review.

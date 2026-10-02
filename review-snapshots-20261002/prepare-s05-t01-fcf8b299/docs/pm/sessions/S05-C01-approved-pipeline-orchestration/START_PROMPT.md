# Start Prompt — Task S05-C01: Approved-pipeline orchestration + successor retry

Execute S05-C01 in this worktree (`C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`).

## Hard worktree guard

Before ANY write, run and verify:
1. `pwd` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
2. `git rev-parse --show-toplevel` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
3. `git status --short`

If `pwd` is wrong, `cd` to the expected root and re-verify. If git toplevel
differs, write nothing, report `BLOCKED: WRONG_WORKTREE`, and exit immediately.
Every path you write must be under the expected root. Never write to
`C:\Users\Admin\MotionForge2D` (MAIN tree) or any S06 worktree.

## Context

Sprint exit was rejected by Codex: (1) the T05 UI calls the legacy
`POST /api/projects/{id}/ingest` (old probe → PySceneDetect → slicing
pipeline) instead of the approved S05 chain T02 ANALYZE_MEDIA import →
T03 GENERATE_PROXY → T04 ANALYZE_MEDIA scene_detect; (2) retry is not
functional (re-submit returns 500 IdempotencyKeyInUse — honest rendering is
not a real retry).

## Read completely

- `docs/pm/SESSION_PROTOCOL.md`
- `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/TASK.md` (full — your contract)
- `docs/architecture/DURABLE_JOB_CONTRACT.md` (§3, §4.3/4.4, §6, §8 successor,
  §9, §10)
- `docs/architecture/DURABLE_JOB_API_CUTOVER.md`
- `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
- `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1)
- `app/workflow/job_service.py` (ANALYZE_MEDIA dispatcher import/scene_detect;
  GENERATE_PROXY registration — REUSE, do not rewrite)
- `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
  `scene_detector.py` (reference; do NOT modify)
- `app/api/routes/projects.py` (legacy ingest ~line 239; endpoint patterns)
- `docs/pm/sessions/S05-T05-import-analyze-ui/REPORT.md` + `LOG.md`
- `docs/pm/sessions/S05-T06-golden-integration/REPORT.md` + `LOG.md`
- `frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/`
- current `git status` and focused S05 diffs

## Implement

1. UI-facing orchestration endpoint: ONE submission creates the approved job
   chain T02→T03→T04 (reuse the S05-T04 ANALYZE_MEDIA dispatcher + GENERATE_PROXY
   registration). Expose backend-owned chain state (active step, real
   checkpoint progress, terminal states) to the UI.
2. Successor-job retry endpoint for failed/cancelled jobs: creates a successor
   Job (§8.5) with owner validation + idempotency; duplicate retry idempotent;
   retry-after-failure actually succeeds.
3. UI: remove legacy `/ingest` call; wire real chain state, cancel, retry
   (successor), resume, refetch after mutation. No mocked progress/state.
4. Tests: one-submission-drives-T02→T03→T04; CFR+VFR completion; proxy
   SHA/size/containment; stable Scene IDs; cancel during active; successor
   retry success (failed + cancelled); restart/resume no duplicate
   publication; orphan cleanup.
5. Playwright desktop + 390px against the corrected real API.

Stay inside TASK.md allowed write scope. Bounded individual commands only.

## Verify (each separately)

1. New orchestration tests
2. Golden integration tests
3. Full S05 regression set (timebase, video_proxy, video_import,
   scene_detection, scene_chunk_stitch)
4. Durable worker/artifact/reconciliation regressions
5. Frontend `tsc --noEmit` + `eslint`
6. Ruff
7. Mypy
8. `git diff --check`
9. Fresh `scripts/quality-baseline.ps1` — record Run ID
10. Playwright desktop + 390px (screenshots)

## Report

Update `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/LOG.md` with
real evidence, write `REPORT.md` (changed files, exact test commands/results,
Quality Run ID, orchestration evidence, CFR+VFR, SHA/size/containment, stable
Scene IDs, cancel, successor retry, restart/resume, orphan cleanup, Playwright
desktop+390px — all listed in TASK.md), end with status `SUBMITTED`. Never
APPROVED, never self-approve.

Then append an honest correction section to `S05-T05` and `S05-T06`
REPORT.md and update `output/SPRINT_EXIT_REPORT.md`. Do not rewrite history —
append. Do not commit/push/deploy; no reset/checkout/clean/delete of user
data; preserve all uncommitted changes; do not touch `channels.json`,
`data/`, database, MAIN tree, or S06 worktrees. NO MOCK data. Stop after
SUBMITTED — Codex performs sprint-exit review.

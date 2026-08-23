# Task S05-T05: Import/Analyze UI — estimate, progress, cancel, retry, resume

- **Task ID:** `S05-T05`
- **Sprint:** `S05` (Import/analyze vertical slice)
- **Status:** `READY`
- **Owner:** Hermes (worktree `prepare-s05-t01`)
- **Depends On:** `S05-T04` (manager-verified, pending sprint review)

## User outcome

The Import/Analyze UI lets a user import a local video, see the durable
backend job's real estimate/progress, cancel, retry and resume it, and see
honest failure states — with the durable backend as the single source of
truth (no mock progress). Desktop and 390px mobile QA pass.

## Outcome scope

- Import/Analyze UI (frontend) wired to the approved durable job APIs
  (S02 job API cutover, S05-T01..T04 backend jobs).
- Estimate/progress from the real job state machine (RUNNING checkpoint
  progress, terminal states), not fake timers.
- Cancel, retry, resume actions call the approved durable job endpoints;
  UI reflects backend state after each mutation (refetch).
- Honest error/empty/loading states; visible disabled reasons.
- Follow `UI_UX_DESIGN_STANDARD.md`: Vietnamese guided flow, one dominant
  action, concise local explanations under unfamiliar buttons, WCAG 2.2 AA
  core flows, keyboard/focus behavior, progressive disclosure.
- Desktop + 390px visual QA evidence (screenshots).

## Required reading

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table + S05-T05 row)
3. `docs/PRODUCT_REQUIREMENTS_V2.md` — import/analyze (Step 1),
   progress/cancel/retry/resume (line 49) only
4. `docs/MASTER_PLAN_V1.md` — WS-03 (lines 815-837), U1 exit (line 230) only
5. `docs/architecture/UI_UX_DESIGN_STANDARD.md` — full (mandatory for S04+ UI)
6. `docs/architecture/DURABLE_JOB_API_CUTOVER.md` — approved job API surface
   (submit/progress/cancel/retry/resume/state)
7. `docs/architecture/DURABLE_JOB_CONTRACT.md` — §4.3/4.4 state machines,
   §6 retry, §10 error envelope (what the UI must render)
8. `docs/pm/sessions/S05-T01-video-preflight/REPORT.md` — preflight contract
   (actionable incompatibility errors the UI must show)
9. `docs/pm/sessions/S05-T04-scene-detection/REPORT.md` + `LOG.md` — the
   durable scene job the Analyze UI drives
10. `frontend/src/` — existing S04 UI patterns (AppShell, layout, api client)
11. `frontend/src/lib/api.ts` — existing typed API client patterns
12. Current `git status` and focused S05-T01..T04 diffs

## Allowed write scope

- Frontend files under `frontend/src/` for the Import/Analyze UI
- `frontend/src/lib/api.ts` (typed client functions for job APIs)
- Focused frontend tests/config (e.g. `frontend/e2e/` or component tests)
- This task's `LOG.md`/`REPORT.md`

## Forbidden scope

- Do NOT modify backend job services (`app/services/video_import.py`,
  `app/services/timebase.py`, `app/services/video_proxy.py`,
  `app/services/scene_detector.py`, `app/workflow/`, `app/api/`)
- No schema/migration/API contract changes
- Do NOT touch: `channels.json`, any `data/`, database, MAIN tree, S06 worktrees
- No commit/push/deploy; no reset/checkout/clean/restore/delete of user data
- Preserve all uncommitted changes; no mock/fake progress data

## Binary acceptance criteria

1. Import/Analyze UI shows real durable job progress (backend state machine),
   never mock/fake timers.
2. Cancel, retry, resume call approved endpoints and refetch after mutation;
   UI state matches backend after each action.
3. Preflight incompatibility errors render actionably (from the approved
   preflight contract), not generic messages.
4. Empty/loading/error states complete; disabled reasons visible.
5. Desktop + 390px visual QA screenshots attached to REPORT.
6. `ruff`, `mypy`, `git diff --check`, frontend `tsc`/`eslint` pass; focused
   backend regressions pass; fresh `scripts/quality-baseline.ps1` = 7/7.

## Targeted verification (run separately)

1. New frontend interaction tests (estimate/progress/cancel/retry/resume/
   refetch/error states)
2. Backend regressions: `tests/test_timebase.py`, `tests/test_video_proxy.py`,
   `tests/test_video_import.py`, `tests/test_scene_detection.py`
3. Frontend `tsc --noEmit` + `eslint`
4. Ruff
5. Mypy
6. `git diff --check`
7. Fresh `scripts/quality-baseline.ps1` (record Run ID)
8. Desktop + 390px visual QA

## REPORT.md must list

- changed files
- exact test commands/results
- Quality Run ID
- real-progress evidence (no mock)
- cancel/retry/resume/refetch evidence
- preflight error rendering evidence
- desktop + 390px QA screenshots
- status `SUBMITTED` (never APPROVED)

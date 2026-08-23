# Start Prompt — Task S05-T05: Import/Analyze UI

Execute S05-T05 in this worktree (`C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`).

## Hard worktree guard

Before ANY write, run and verify:
1. `pwd` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
2. `git rev-parse --show-toplevel` → must be `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
3. `git status --short`

If `pwd` is wrong, `cd` to the expected root and re-verify. If git toplevel
differs, write nothing, report `BLOCKED: WRONG_WORKTREE`, and exit immediately.
Every path you write must be under the expected root. Never write to
`C:\Users\Admin\MotionForge2D` (MAIN tree) or any S06 worktree.

## Read completely

- `docs/pm/SESSION_PROTOCOL.md`
- `docs/pm/sessions/S05-T05-import-analyze-ui/TASK.md` (full — your contract)
- `docs/pm/ROADMAP.md` (E03/S05 table)
- `docs/architecture/UI_UX_DESIGN_STANDARD.md` (full — mandatory)
- `docs/architecture/DURABLE_JOB_API_CUTOVER.md` (approved job API surface)
- `docs/architecture/DURABLE_JOB_CONTRACT.md` (§4.3/4.4 state machines,
  §6 retry, §10 error envelope)
- `docs/pm/sessions/S05-T01-video-preflight/REPORT.md` (preflight errors)
- `docs/pm/sessions/S05-T04-scene-detection/REPORT.md` + `LOG.md`
- `frontend/src/` existing S04 UI patterns + `frontend/src/lib/api.ts`
- current `git status` and focused S05-T01..T04 diffs

## Implement

Import/Analyze UI wired to the approved durable job APIs: real estimate/
progress from the backend state machine (never mock), cancel/retry/resume via
approved endpoints with refetch after mutation, actionable preflight error
rendering, complete empty/loading/error states with visible disabled reasons,
Vietnamese guided flow per UI_UX_DESIGN_STANDARD.md. Desktop + 390px QA.

Stay inside TASK.md's allowed write scope. Bounded individual commands only.

## Verify (each separately)

1. New frontend interaction tests
2. Backend regressions (timebase, video_proxy, video_import, scene_detection)
3. `tsc --noEmit` + `eslint`
4. Ruff
5. Mypy
6. `git diff --check`
7. Fresh `scripts/quality-baseline.ps1` — record Run ID
8. Desktop + 390px visual QA (screenshots)

## Report

Update `docs/pm/sessions/S05-T05-import-analyze-ui/LOG.md` with real evidence,
write `REPORT.md` (changed files, exact test commands/results, Quality Run ID,
real-progress evidence, cancel/retry/resume/refetch evidence, preflight error
evidence, desktop+390px screenshots), end with status `SUBMITTED`. Never
APPROVED, never self-approve. Do not commit/push/deploy; no
reset/checkout/clean/delete of user data; preserve all uncommitted changes;
do not touch `channels.json`, `data/`, database, MAIN tree, or S06 worktrees.
No mock/fake progress data.

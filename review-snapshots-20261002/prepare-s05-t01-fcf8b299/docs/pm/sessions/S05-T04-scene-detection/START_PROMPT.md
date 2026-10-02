# Start Prompt — Task S05-T04: Scene detection durable job

Execute S05-T04 in this worktree (`C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`).

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
- `docs/pm/sessions/S05-T04-scene-detection/TASK.md` (full)
- `docs/pm/ROADMAP.md` (E03/S05 table)
- `docs/architecture/DURABLE_JOB_CONTRACT.md` (§3 job classes first — reuse an
  approved class; do not invent a new one without an approved contract change)
- `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
- `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` (scene table section)
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1, §6.4)
- `docs/pm/sessions/S05-T03-canonical-timebase-proxy/REPORT.md` + `LOG.md`
- `app/services/timebase.py`, `app/services/video_proxy.py` (approved APIs)
- `app/services/video_import.py` (reference pattern only — DO NOT modify)
- current `git status` and focused S05-T03 diff

## Implement

Durable/checkpointed scene-detection job consuming the canonical timebase +
managed ready proxy artifact; stable Scene IDs (idempotent, no duplicate rows
on retry/replay/restart); canonical frame↔time via rational arithmetic; no
deprecated frame access; clean cancel/failure/timeout/rollback of the attempt's
own staging rows; source + proxy artifacts unmodified.

Stay inside TASK.md's allowed write scope. Bounded individual commands only.

## Verify (each separately)

1. New scene-detection tests
2. `tests/test_timebase.py` + `tests/test_video_proxy.py`
3. `tests/test_video_import.py` (S05-T02 regressions)
4. Durable worker/artifact/reconciliation regressions
5. Ruff
6. Mypy
7. `git diff --check`
8. Fresh `scripts/quality-baseline.ps1` — record Run ID

## Report

Update `docs/pm/sessions/S05-T04-scene-detection/LOG.md` with real evidence,
write `REPORT.md` (changed files, exact test commands/results, Quality Run ID,
stable-Scene-ID evidence, canonical timebase evidence, cleanup evidence,
containment/SHA evidence), end with status `SUBMITTED`. Never APPROVED, never
self-approve. Do not commit/push/deploy; no reset/checkout/clean/delete of
user data; preserve all uncommitted changes; do not touch `channels.json`,
`data/`, database, MAIN tree, or S06 worktrees.

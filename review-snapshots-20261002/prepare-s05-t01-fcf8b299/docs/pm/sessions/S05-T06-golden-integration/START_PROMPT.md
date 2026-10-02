# Start Prompt — Task S05-T06: Golden import/analyze integration

Execute S05-T06 in this worktree (`C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`).

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
- `docs/pm/sessions/S05-T06-golden-integration/TASK.md` (full — your contract)
- `docs/pm/ROADMAP.md` (E03/S05 table + epic exit)
- `docs/architecture/DURABLE_JOB_CONTRACT.md` (§6.1, §8, §9, §10)
- `docs/architecture/DURABLE_JOB_PERSISTENCE.md`
- `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md`
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`
- `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` (§3.1 CFR/VFR)
- `docs/pm/sessions/S05-T01..T05/REPORT.md` + `LOG.md` (all five)
- `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
  `scene_detector.py` (reference; do NOT modify)
- `app/workflow/job_service.py`, `durable_worker.py` (successor/restart)
- current `git status` and focused S05 diffs

## Implement

Golden end-to-end integration: real CFR + VFR fixtures through managed import
→ canonical timebase + proxy → scene detection → UI/API state, with forced
restart (successor), retry, cancel/replay — proving no duplicates, stable
Scene IDs, checksum/size containment, no false-ready artifact, and
restart-recovery evidence for sprint exit. Stay inside TASK.md allowed write
scope. Bounded individual commands only.

## Verify (each separately)

1. New golden integration tests
2. Full S05 regression set (timebase, video_proxy, video_import,
   scene_detection, scene_chunk_stitch)
3. Durable worker/artifact/reconciliation regressions
4. Ruff
5. Mypy
6. `git diff --check`
7. Fresh `scripts/quality-baseline.ps1` — record Run ID

## Report

Update `docs/pm/sessions/S05-T06-golden-integration/LOG.md` with real
evidence, write `REPORT.md` (changed files, exact test commands/results,
Quality Run ID, CFR+VFR golden evidence, restart/successor evidence, retry/
cancel/orphan evidence, SHA/size/containment evidence, stable Scene ID
evidence, no-false-ready evidence), end with status `SUBMITTED`. Never
APPROVED, never self-approve. Do not commit/push/deploy; no
reset/checkout/clean/delete of user data; preserve all uncommitted changes;
do not touch `channels.json`, `data/`, database, MAIN tree, or S06 worktrees.
No mock/fake data.

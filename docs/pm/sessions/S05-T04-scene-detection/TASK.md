# Task S05-T04: Scene detection durable job — canonical timebase, stable Scene IDs

- **Task ID:** `S05-T04`
- **Sprint:** `S05` (Import/analyze vertical slice)
- **Status:** `READY`
- **Owner:** Hermes (worktree `prepare-s05-t01`)
- **Depends On:** `S05-T03` (manager-verified, pending sprint review)

## User outcome

A durable/checkpointed scene-detection job consumes the S05-T03 canonical
timebase + managed `ready` proxy artifact, produces stable Scene records with
canonical `start_frame`/`end_frame`/`start_time_ms`/`end_time_ms` derived from
rational timebase arithmetic (never float drift), and never touches deprecated
legacy frame access. Retry/restart/cancel are duplicate-free and clean up only
the failed attempt's own staging/rows.

## Outcome scope

- Register/use an approved durable job class for scene detection (reuse an
  existing approved class from `DURABLE_JOB_CONTRACT.md` §3 if one fits;
  otherwise the task is BLOCKED pending contract change — do not invent a new
  class without approval).
- Write scene rows through the approved `scene` contract
  (`PERSISTENCE_DOMAIN_CONTRACT.md` §scene): `video_item_id`, `position`
  (unique per video), `start_frame`/`end_frame` (zero-based inclusive),
  `start_time_ms`/`end_time_ms` (canonical integer ms), `status`, `revision`.
- Stable Scene IDs: scene rows are created once; retry/replay/restart reuses
  them by idempotency key + checkpoint, never duplicates rows.
- Input is the managed `ready` proxy artifact from S05-T03 (or managed source
  if proxy absent) — never raw files outside managed artifact containment.
- Cancellation/failure/timeout: DB rollback removes the partial attempt's
  staging rows; committed scene rows survive.
- No deprecated frame access: no legacy `legacy_scene_id`-based frame math;
  no direct frame-byte reads outside the approved ffmpeg_utils path.

## Required reading

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table + task activation rules)
3. `docs/PRODUCT_REQUIREMENTS_V2.md` — import/analyze (Step 1), scene/shot
   auto-detection (line 71), progress/cancel/retry/resume (line 49) only
4. `docs/MASTER_PLAN_V1.md` — WS-03 (lines 815-837), scene detection/keyframes
   (line 827), job classes (line 638+), U1 exit (line 230) only
5. `docs/architecture/DURABLE_JOB_CONTRACT.md` — full (esp. §3 job classes,
   §4.3/4.4 state machines, §5 leases, §6.1 retry classification,
   §7 transactions/checkpoints, §8 idempotency/replay/successor,
   §9 staging/publication/cleanup, §10 error envelope)
6. `docs/architecture/DURABLE_JOB_PERSISTENCE.md` — schema/repository semantics
7. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` — full (path containment,
   atomic write, errors)
8. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` — `scene` table section
9. `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md` — full (rational
   timebase is source of truth; frame↔time mapping)
10. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` — §3.1 fps classification,
    §6.4 timebase consumption point
11. `docs/pm/sessions/S05-T03-canonical-timebase-proxy/REPORT.md` + `LOG.md`
    — full (approved patterns: idempotency key shape, checkpoint reuse,
    successor creation, staging cleanup, `created_final`-guarded cleanup)
12. `app/services/timebase.py` + `app/services/video_proxy.py` — full (the
    approved canonical timebase + proxy generation APIs)
13. `app/services/video_import.py` — reference only for the owner-scoped
    idempotency pattern; DO NOT modify.

## Allowed write scope

- New test file(s) for scene detection (e.g. `tests/test_scene_detection.py`)
- New scene-detection service module under `app/services/` (e.g.
  `app/services/scene_detector.py`) if required
- Registration in `app/workflow/job_service.py` if a new handler is needed
- This task's `LOG.md`/`REPORT.md`

## Forbidden scope

- Do NOT modify `app/services/video_import.py`, `app/services/timebase.py`,
  `app/services/video_proxy.py`
- No schema/migration changes without an approved contract change
- No API/frontend/scene-detection-UI changes (S05-T05 owns UI)
- Do NOT touch: `channels.json`, any `data/`, database, MAIN tree, S06 worktrees
- No commit/push/deploy; no reset/checkout/clean/restore/delete of user data
- Preserve all uncommitted changes

## Binary acceptance criteria

1. Scene detection job runs as a durable/checkpointed job; retry/replay/
   restart creates no duplicate scene rows (idempotency key + checkpoint).
2. Every scene row satisfies: position unique per video; start ≤ end;
   start_frame/end_frame zero-based inclusive; start_time_ms/end_time_ms
   derived from canonical rational timebase (exact integer math).
3. Cancel/failure/timeout/DB rollback removes the partial attempt's staging
   rows; committed scene rows survive; no orphan rows.
4. No deprecated frame access: grep shows no legacy frame-byte reads outside
   `ffmpeg_utils`; `legacy_scene_id` is never used for frame math.
5. Source artifact (and S05-T03 proxy) remain unmodified; SHA-256/size of any
   committed artifact unchanged.
6. `ruff`, `mypy`, `git diff --check` pass; focused tests + S05-T02/T03
   regressions pass; fresh `scripts/quality-baseline.ps1` = 7/7.

## Targeted verification (run separately)

1. New scene-detection tests
2. `tests/test_timebase.py` + `tests/test_video_proxy.py` (S05-T03 regressions)
3. `tests/test_video_import.py` (S05-T02 regressions)
4. Durable worker/artifact/reconciliation regressions
5. Ruff
6. Mypy
7. `git diff --check`
8. Fresh `scripts/quality-baseline.ps1` (record Run ID)

## REPORT.md must list

- changed files
- exact test commands/results
- Quality Run ID
- stable-Scene-ID evidence (idempotency/replay/restart)
- canonical timebase evidence (frame↔time mapping, CFR/VFR)
- cleanup evidence (cancel/failure/rollback/orphan)
- containment/SHA evidence
- status `SUBMITTED` (never APPROVED)

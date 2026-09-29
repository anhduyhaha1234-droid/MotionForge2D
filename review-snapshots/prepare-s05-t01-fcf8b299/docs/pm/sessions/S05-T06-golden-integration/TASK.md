# Task S05-T06: Golden import/analyze integration and restart-recovery evidence

- **Task ID:** `S05-T06`
- **Sprint:** `S05` (Import/analyze vertical slice)
- **Status:** `READY`
- **Owner:** Hermes (worktree `prepare-s05-t01`)
- **Depends On:** `S05-T05` (manager-verified, pending sprint review)

## User outcome

A golden end-to-end integration proves the full S05 vertical slice — managed
import → canonical timebase + proxy → scene detection → Import/Analyze UI —
works for both CFR and VFR sources, survives forced restart, retry and cancel
without duplicates, preserves checksums/containment, produces stable Scene IDs,
and never shows a false-ready artifact. Evidence is recorded for sprint exit.

## Outcome scope

- Golden integration test(s) covering the full pipeline on real media
  (CFR + VFR fixtures) end-to-end via the durable job surface and UI.
- Forced restart (kill + successor), retry, cancel/replay scenarios with
  duplicate-free proof.
- Checksum (SHA-256) + size containment proof for every committed artifact.
- Stable Scene IDs across retry/restart/replay.
- No false-ready artifact: a job is never marked `ready` before its real
  publication transaction commits.
- UI integration check (via S05-T05 UI or API-level equivalent) showing the
  golden path renders real backend state.
- Restart-recovery evidence recorded for sprint exit.

## Required reading

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/ROADMAP.md` (E03/S05 table + S05-T06 row + epic exit line)
3. `docs/PRODUCT_REQUIREMENTS_V2.md` — import/analyze (Step 1),
   progress/cancel/retry/resume (line 49) only
4. `docs/MASTER_PLAN_V1.md` — WS-03 (lines 815-837), U1 exit (line 230) only
5. `docs/architecture/DURABLE_JOB_CONTRACT.md` — full (esp. §6.1 retry
   classification, §8 idempotency/replay/successor, §9 staging/publication/
   cleanup, §10 error envelope)
6. `docs/architecture/DURABLE_JOB_PERSISTENCE.md` — schema/repository semantics
7. `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` — full (containment, atomic)
8. `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md` — full
9. `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` — full (§3.1 CFR/VFR)
10. `docs/pm/sessions/S05-T01-video-preflight/REPORT.md`
11. `docs/pm/sessions/S05-T02-managed-import/REPORT.md` (+ correction section)
12. `docs/pm/sessions/S05-T03-canonical-timebase-proxy/REPORT.md` + `LOG.md`
13. `docs/pm/sessions/S05-T04-scene-detection/REPORT.md` + `LOG.md`
14. `docs/pm/sessions/S05-T05-import-analyze-ui/REPORT.md` + `LOG.md`
15. `app/services/video_import.py`, `timebase.py`, `video_proxy.py`,
    `scene_detector.py` — full (reference; do NOT modify)
16. `app/workflow/job_service.py`, `durable_worker.py` — full (job surface,
    successor/restart patterns)
17. Current `git status` and focused S05-T01..T05 diffs

## Allowed write scope

- New golden integration test file(s), e.g. `tests/test_s05_golden_integration.py`
- Test fixtures (CFR/VFR media) under `tests/fixtures/` if needed
- This task's `LOG.md`/`REPORT.md`

## Forbidden scope

- Do NOT modify any service in `app/services/` (`video_import.py`,
  `timebase.py`, `video_proxy.py`, `scene_detector.py`)
- Do NOT modify `app/workflow/`, `app/api/`, frontend, schema, migration
- Do NOT touch: `channels.json`, any `data/`, database, MAIN tree, S06 worktrees
- No commit/push/deploy; no reset/checkout/clean/restore/delete of user data
- Preserve all uncommitted changes; no mock/fake data

## Binary acceptance criteria

1. Golden path passes for a real CFR fixture AND a real VFR fixture:
   import → proxy → scene detection → UI/API state shows completed.
2. Forced restart (successor) produces exactly one effect set — no duplicate
   rows/files; replay reuses committed work.
3. Retry after failure and cancel both clean the failed/cancelled attempt's own
   staging; committed artifacts survive; no orphan rows.
4. SHA-256 + size of every committed artifact match the file on disk; all
   artifact paths are contained under the managed root.
5. Scene IDs are stable across retry/restart/replay (same ids, revision=1
   semantics per contract).
6. No false-ready artifact: readiness is only observable after the real
   publication transaction commits.
7. `ruff`, `mypy`, `git diff --check` pass; focused S05 regressions pass;
   fresh `scripts/quality-baseline.ps1` = 7/7.

## Targeted verification (run separately)

1. New golden integration tests
2. Full S05 regression set: `test_timebase.py`, `test_video_proxy.py`,
   `test_video_import.py`, `test_scene_detection.py`,
   `test_scene_chunk_stitch.py`
3. Durable worker/artifact/reconciliation regressions
4. Ruff
5. Mypy
6. `git diff --check`
7. Fresh `scripts/quality-baseline.ps1` (record Run ID)

## REPORT.md must list

- changed files
- exact test commands/results
- Quality Run ID
- CFR + VFR golden evidence
- restart/successor evidence (no duplicates)
- retry/cancel/orphan-cleanup evidence
- SHA/size/containment evidence
- stable Scene ID evidence
- no-false-ready evidence
- status `SUBMITTED` (never APPROVED)

## Sprint exit note

This is the final S05 task. After manager verification, the sprint exit runs a
fresh 7/7 baseline and produces `SPRINT_EXIT_REPORT.md`; the user then calls
Codex for sprint review.

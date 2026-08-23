# Sprint S08 — Object Discovery and Curation

**Status:** READY  
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`  
**Base gate:** S08-P00 APPROVED, quality run `20260805-232332`  
**Execution:** Hermes manager, six distinct coding sessions, sequential only  
**Final approval:** Codex sprint-exit review

## Outcome

Users work with durable video-global Object Roles rather than repeating object
selection scene by scene. Candidate evidence, confidence, grouping, explicit
merge/split/confirm and targeted correction survive restart and preserve
unaffected approved data.

## Dependency graph

`S08-T01 -> S08-T02 -> S08-T03 -> S08-T04 -> S08-T05 -> S08-T06`

No S08 production task may run in parallel. A task dependency opens only after
the prior writer exits and the manager records
`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` with stable evidence.

## Cross-sprint invariants

- Preserve S05 lifecycle, source supersession, read-only GET, retry, cancel,
  concurrency, artifacts and stable Scene IDs.
- Preserve S06 character/version/content/validation/flat-CAS-publish contracts.
- New durable truth lives in SQLite/backend authority, never only JSON,
  Zustand/localStorage or filesystem naming.
- Legacy object endpoints remain compatibility surfaces until an explicit tested
  cutover; their mutable/index-derived IDs are not authoritative ObjectRole IDs.
- All jobs use the public initialized JobService factory/root and managed
  artifacts. No competing production factory or synchronous long HTTP work.
- All tests/runtime/evidence use new isolated roots and databases.

## Sprint-exit gates

Focused S08 suites; relevant S01/S02/S03/S05/S06 regressions; migrations;
restart/retry/cancel/concurrency; ruff; mypy; frontend type/lint/build;
`git diff --check`; desktop and 390px Playwright/visual QA; deterministic golden
metrics; fresh 7/7 baseline; protected-data comparison; complete session and
correction lineage.

## End state

Hermes stops every writer and submits `docs/pm/sprints/S08-SPRINT_REPORT.md` as
`SPRINT_SUBMITTED`. Hermes never writes Codex approval and does not start S07.


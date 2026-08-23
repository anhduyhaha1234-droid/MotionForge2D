# S08-T06 — Golden Object Intelligence and Sprint Exit

**Status:** PLANNED  
**Depends on:** S08-T05 manager-verified

## Outcome

Deterministic golden data and end-to-end evidence prove S08 grouping, curation,
targeted correction and restart behavior without user data.

## Golden contract

Include multi-scene same-object, visually similar different objects, occlusion,
low confidence, false grouping, required merge, required split, source
replacement, restart, retry and cancel cases. Record expected truth and metric
thresholds before running; do not tune thresholds after observing results.

Metrics include grouping precision/recall (or explicitly justified equivalent),
false-merge rate, false-split rate, review/low-confidence rate, recompute scope,
repeatability and runtime. Do not claim model quality beyond the fixture evidence.

## Allowed write scope

New isolated golden fixtures/tests, sprint integration/E2E evidence tooling,
`docs/pm/sprints/S08-SPRINT_REPORT.md`, and this packet LOG/REPORT. Product fixes
must be returned as CHANGES_REQUESTED to the owning T01–T05 session, not hidden
inside T06.

## Acceptance and validation

Run full S08 integration across a new root/DB, forced restart, source
supersession, retry/cancel, desktop/390px UX, all targeted and cross-sprint
regressions, ruff, mypy, tsc, eslint, build, diff-check and fresh 7/7 baseline
with a new Run ID. Protected data/source snapshots remain unchanged. Produce a
complete session/correction/evidence report and stop at SPRINT_SUBMITTED.


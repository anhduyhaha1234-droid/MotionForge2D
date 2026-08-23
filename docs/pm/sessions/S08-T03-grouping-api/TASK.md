# S08-T03 — Cross-scene Grouping and Curation API

**Status:** PLANNED  
**Depends on:** S08-T02 manager-verified

## Outcome

Produce reviewable cross-scene grouping suggestions and explicit durable
merge/split/confirm operations for Object Roles.

## Required behavior

- Suggestions carry confidence/reasons/provenance and never auto-confirm.
- Merge, split and confirm are explicit mutations with CAS/revision protection,
  idempotency and audit history.
- Operations fail closed across project/video/source generation boundaries.
- Superseded roles/evidence remain traceable; approved evidence is not silently
  rewritten or deleted.
- Duplicate/concurrent requests and restart never create duplicate active roles.
- GET/list/detail endpoints are read-only and expose review reasons.

## Allowed write scope

S08 persistence/schema/route/service files, one focused grouping module if
needed, focused T03 tests and this packet LOG/REPORT.

## Forbidden

Frontend gallery, candidate extractor redesign, correction recompute jobs,
legacy object destructive migration, S05/S06 behavior and protected data.

## Acceptance and validation

Cover deterministic grouping, same/different object across scenes, ambiguity,
low confidence, merge/split/confirm, stale revision, idempotency, concurrency,
restart, ownership and read-only GET. Run all T01/T02 and relevant S03/S05
regressions, ruff, mypy and diff-check. Stop at SUBMITTED.


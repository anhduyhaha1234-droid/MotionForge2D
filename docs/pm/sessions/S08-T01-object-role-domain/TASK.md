# S08-T01 — Durable ObjectOccurrence/ObjectRole Domain

**Status:** READY  
**Depends on:** S08-P00 APPROVED

## Outcome

Create the durable schema, repository/service and focused API contract for
video-global `ObjectRole` identity and scene/frame evidence in
`ObjectOccurrence`.

## Required behavior

- Stable UUID/ULID-style IDs, never array index, display name or legacy mutable
  `object_id` as authority.
- Explicit workspace/project/video/source-generation ownership and fail-closed
  cross-owner validation.
- Occurrence bounds reference stable Scene identity plus canonical frame/time
  coordinates; confidence is 0..1 with source, algorithm/version, reasons and
  review state.
- Role status supports suggested/confirmed/superseded without silently turning
  model suggestions into user truth.
- Revision/CAS and timestamps support later concurrent grouping corrections.
- Constraints/indexes/foreign keys and migration upgrade/downgrade are tested.
- Read APIs are side-effect free; write APIs are idempotent where requested.
- Define explicit compatibility mapping to legacy object data without making it
  durable truth or modifying legacy records.

## Allowed write scope

- `app/persistence/models.py`
- one new S08 migration
- `app/persistence/object_intelligence.py`
- `app/schemas/object_intelligence.py`
- `app/api/routes/object_intelligence.py`
- minimal route/dependency registration in `app/api/app.py`, `app/api/deps.py`
- focused S08-T01 tests
- this packet LOG/REPORT

## Forbidden

Frontend, candidate extraction, grouping algorithms, correction jobs, legacy
object rewrite, S05/S06 contract changes, protected data and Git/destructive
operations.

## Acceptance

- Migration round-trip and existing-database upgrade pass in temporary storage.
- Stable identity, ownership, constraints, CAS, idempotency and concurrent
  creation/update tests pass.
- GET endpoints cause zero durable mutations.
- No production path relies on legacy index/name identity.
- Relevant persistence/project/video/source-supersession regressions pass.

## Validation

Run focused tests cache-disabled, migration upgrade/downgrade, relevant
S01/S03/S05 regressions, ruff changed files, mypy app and diff-check. Append
evidence and stop at SUBMITTED.


# S08-T05 — Targeted Object Correction and Recompute

**Status:** PLANNED  
**Depends on:** S08-T04 manager-verified

## Outcome

Object corrections invalidate and recompute only affected dependencies while
preserving approved/unaffected roles, occurrences and artifacts.

## Required behavior

- Define explicit dependency/invalidation graph before implementation.
- Merge/split/reassign/candidate correction reports its impacted scope before
  confirmation and creates durable successor/recompute work only where needed.
- Old affected state is superseded/archived; unaffected rows/files remain
  byte/hash identical.
- Retry/idempotency, concurrent corrections, restart, cancel and orphan cleanup
  follow durable job contracts.
- UI shows confirmation, progress, terminal outcome and honest recovery.

## Allowed write scope

Focused S08 correction service/workflow/API and UI extensions, minimal durable
job registration, focused tests/E2E and this packet LOG/REPORT.

## Forbidden

Full-chain recompute as a shortcut, mutation/deletion of unaffected evidence,
S05/S06 contract weakening, production data and destructive Git.

## Acceptance and validation

Assert exact affected/unaffected sets and byte/hash immutability; cover
restart/retry/cancel/concurrency/idempotency/no-orphan and UI impacted-scope
confirmation. Run full S08 T01–T04 plus S02/S05/S06 relevant regressions,
frontend gates, desktop/mobile E2E and diff-check. Stop at SUBMITTED.


# S08-T02 — Durable Candidate Extraction

**Status:** PLANNED  
**Depends on:** S08-T01 manager-verified

## Outcome

A durable job extracts ObjectOccurrence candidates and commits representative
thumbnail/mask artifacts without exposing partial or stale output.

## Required behavior

- Register a focused durable job through the initialized JobService/worker.
- Idempotency binds video item, source generation/SHA and extractor version.
- Deterministic CI adapter plus explicit production capability/provider path;
  no mock fallback in production.
- Artifact staging, containment, atomic commit, SHA-256, size, MIME/dimensions,
  repository rows and cleanup follow managed-artifact contracts.
- Restart/retry/cancel/concurrent duplicate submission and stale-source behavior
  are durable and create no orphan/duplicate effects.
- Completed state is impossible until all declared rows/artifacts are committed.

## Allowed write scope

New focused extraction service/adapter/workflow files, minimal JobService/worker
registration, S08 persistence/schema/API additions required to submit/read the
job, focused tests and this packet LOG/REPORT.

## Forbidden

Grouping/merge/split UI, legacy synchronous auto-segmentation replacement,
S05 media algorithms, S06 character behavior, protected data and destructive Git.

## Acceptance and validation

Test happy path, deterministic evidence, source-generation isolation,
idempotency, concurrent submit, restart at staging/commit boundaries, retry,
cancel, corrupt/missing artifacts, containment and orphan cleanup. Run T01 plus
relevant durable-worker/managed-artifact/S05 regressions, ruff, mypy and
diff-check. Stop at SUBMITTED.


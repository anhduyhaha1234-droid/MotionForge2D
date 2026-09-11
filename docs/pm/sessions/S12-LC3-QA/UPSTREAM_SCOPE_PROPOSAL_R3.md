# S12-LC3-R3 upstream scope proposal

Status: `PROPOSAL_ONLY / BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY`

This is the single R3 upstream proposal. No upstream implementation is included
in the QA checkpoint. The bounded public graph created a legacy project, uploaded
and analyzed a video, completed the durable extraction worker, produced current
roles/occurrences/structural-evidence segments, published a character pack,
created a project-cast mapping, and created a ReskinConfig. It then stopped at
the first genuinely absent producer: no supported public server-owned operation
produces and activates a current `StructuralLockManifest` for the returned
project/video/generation and pins it into the ReskinConfig.

## Minimal proposed upstream write-set

1. `app/schemas/structural_lock.py`: strict request/response DTOs for a
   server-owned manifest-production request and returned manifest identity,
   hash, source generation, policy version, and status. Reject client-supplied
   ready flags, paths, authority blobs, or cross-project identities.
2. `app/services/structural_lock_producer.py`: add a
   `produce_current_manifest(...)` service operation. It must validate the
   workspace, 12-hex legacy project, returned UUID video, current generation,
   hash-verified ready source artifact, current structural-evidence segments,
   and supported render-route evidence. It should derive the canonical frame,
   timebase, shot/segment fingerprints and route evidence, then call the
   existing `StructuralLockRepository.create_manifest(..., activate=True)`.
   Replays must be idempotent; concurrent calls must have one active winner and
   a typed loser; a changed source/evidence generation must supersede rather
   than reuse a stale manifest.
3. `app/api/routes/structural_lock.py`: add the narrow public route
   `POST /api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock`
   and mount it from `app/api/app.py`. It must return the server-generated
   manifest ID/hash/revision and map missing, stale, tampered, unsupported,
   cross-scope, and CAS conflicts fail-closed.

## Consumer contract and order

Existing public producers remain the dependency chain:

`legacy upload/analyze -> current extraction/evidence -> structural-lock producer
-> ReskinConfig CAS pin -> S09 reapprove -> executable v2 authority -> S10 Full
Apply -> S12 context/preflight/submit -> durable worker/publisher/result/media`.

The lock producer is owned by the S09 StructuralLock/authority owner. The
smallest compatibility delta is additive: existing persistence at
`app/persistence/structural_lock.py:495` remains the storage primitive, existing
ReskinConfig pinning consumes the returned ID/revision, and S09 reapproval
continues to derive the authority snapshot. No existing legacy identity is
changed, and the separate empty v2 durable identity remains a secondary
boundary to resolve only after the lock producer exists.

## Required upstream tests

- A valid current source/evidence graph produces one active manifest with exact
  source/evidence hashes, generation, route evidence, and deterministic
  canonical bytes.
- Replay is idempotent; two live callers yield exactly one winner and typed
  loser, with all manifest/config/approval rows and scope pins coherent.
- Missing, stale, tampered, cross-project/video/workspace, unsupported-route,
  and invalid-generation inputs produce typed failures with zero success
  mutation; predecessor supersession and ReskinConfig compare-and-set pinning
  are covered.
- A pinned manifest makes S09 reapproval's authority
  `full_apply_executable=true`; the existing S10 durable worker and S12
  submit/publisher/result/media tests then consume that authority without
  fixture SQL or private handlers.

The R3 QA evidence does not propose changes to `tests/s12` RETRY-owned tests,
VAL-owned tests, frontend, schema migrations, persistence behavior, or any
production file. The proposal is bounded to the missing shared producer and its
contract tests; implementation and task ownership require coordinator/upstream
authorization.

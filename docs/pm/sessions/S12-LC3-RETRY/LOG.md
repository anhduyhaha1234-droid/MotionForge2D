# S12-LC3-RETRY immutable identity and migration proof

## Session identity and scope

- Decision: R3 PM bounded `S12-LC3-RETRY`; this worker owns implementation only,
  not VAL/QA, replacement, publication, runner, stitch, MAIN, or another lane.
- Worker/session ID: `01a08982-4ec8-7271-afa2-98efc200875c` (Codex session).
- Thread ID: `01a08e92-7385-7a21-beb7-67dc770ce118`; host `DESKTOP-B5TR9HD`,
  process `8532`; route `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.
- Worktree/branch: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-retry`,
  `codex/s12-lc3-luna-retry`; starting HEAD
  `7b15e60e631357fef9fc82ab7109c988382c02f1`.
- Preflight: `baseline-retry-r3.json` captured at
  `2026-09-11T03:44:57.563816+00:00`; it records
  `migrations/versions/d4e5f6a7b8c9_s12_retry_lineage.py` as absent.

## Immutable identity design

`S12ExportRun` is an append-only attempt row. A predecessor is eligible for a
retry only when its frozen workspace/project/video, checkpoint id/hash/revision,
manifest id/hash/generation, profile snapshot, plan id/hash, frame count and
chunk configuration still validate against the requested workspace and live
authority. A retry copies those pins exactly, increments `attempt`, sets
`predecessor_run_id` to the immediate predecessor, and derives a stable
`lineage_id`; it never updates, deletes, resets, or re-plans the predecessor.

The database keeps three independent additive identities: (1) the existing
workspace-scoped initial-submit idempotency key, (2) a unique lineage/attempt
identity for each immutable run, and (3) a unique non-null predecessor pointer,
which permits one and only one immediate successor. The retry operation uses
the predecessor-pointer uniqueness as the race arbiter and verifies all
identity fields after any collision before returning the winner. Same-state
rowcount is never treated as proof of ownership.

Each run has exactly one durable `Job` whose idempotency key is derived from the
run identity. Initial submit retains strong replay: same key plus the same
frozen payload returns the original run and its actual job; material mismatch,
wrong workspace/lineage/context, invalid state, identity corruption, lookup or
query error fails closed with rollback and no unintended mutation. Retry of a
successor targets that successor and creates only its next successor. Concurrent
or repeated retries return the same successor and the actual job pointer.

## Migration proof plan

Revision `d4e5f6a7b8c9_s12_retry_lineage.py` has `down_revision =
c3d4e5f6a7b8`. Upgrade tests will use the real prior schema and retain seeded
initial, completed, failed and cancelled rows plus chunk/artifact hashes;
assert counts, ids, pins and hashes before/after. The migration will be tested
on an empty database, and downgrade/upgrade restart replay will verify that
initial-submit dedup, attempt/lineage identity, predecessor uniqueness and
job pointers remain durable. The overrestrictive six-field run identity
uniqueness is replaced by additive attempt/lineage constraints; no unrelated
table is changed. All checks run only against the RETRY runtime/evidence roots.

Evidence root: `C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\RETRY`.
Guard and evidence root: `C:\Users\Admin\mfqa\s12-lc3-r3\20260911T034253Z\RETRY`.

## Protected test preimages before exclusive transfer

- `tests/s12/s12-t03c/test_export_jobs_api.py` — SHA-256
  `D1DDADD1F3405240E4642F9DB7BCB28939ACEE191710910BE18F6743818202AB`.
- `tests/s12/s12-t03c/test_s12_t03c_c1_closure.py` — SHA-256
  `8C2D2C9D8CD0BC419BD906DB2A1FC72C695818B16153303FFDF08CA44EF5811E`.

These exact preimages are transferred exclusively to
`tests/s12/s12-lc3-retry/`; their contents are not edited in transit.

## R4 correction design and proof plan

R4 preserves the landed additive schema and migration byte-for-byte. Claim
admission now validates the whole immutable chain before inserting a lease:
attempt 1 is the sole root, each later attempt points to the terminal prior
attempt with identical workspace/project/video and frozen checkpoint,
manifest, profile, plan, frame and chunk configuration, and cycles or wrong
attempts are rejected. The durable worker supplies its actual Job ID to that
claim. Retry creation uses one session transaction for successor row, exact
Job row and pointer binding; commit uncertainty is reconciled only by exact
successor plus unfiltered workspace Job lookup. No predecessor, plan,
checkpoint, migration or unrelated table is reset or rewritten.

R4 proof nodes are `test_r4_retry_execution.py`: failed and cancelled chains
exercise actual registered DurableWorker attempts; malformed lineage has no
lease; two live sessions rendezvous at `create_successor_run` and assert one
winner/one successor/one Job; generation, manifest and query faults assert
zero Run/Job delta; a pre-existing zero-Job successor is repaired exactly
once; and a lost commit acknowledgement replays the exact pair. Existing
sequential replay controls remain separate. Fresh raw evidence belongs under
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r4-owner-submission\20260911T195310Z\RETRY`;
runtime belongs under the matching `C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\RETRY`.

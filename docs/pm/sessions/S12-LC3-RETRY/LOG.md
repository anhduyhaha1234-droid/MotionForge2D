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

## R5 bounded correction — F01 / F03

Owner/session remains `01a08982-4ec8-7271-beb7-67dc770ce118`, thread
`01a08e92-7385-7a21-beb7-67dc770ce118`; route is `gpt-5.6-luna`, reasoning
`high`, fallback `OFF`. R5 resumed on clean HEAD
`2c9d793eb96ea330ba4d9ee1028ce45909cb9ea6` in the same RETRY worktree.
No schema/model/migration, T03A, QA/VAL/UI/demo/MAIN or candidate integration
file is writable in this correction.

R5 pre-red reproduced the frozen reviewer nodes on this owner source:
`test_review_r4_retry.py::test_public_initial_replay_generation_zero_mutation[True]`
failed because denied replay increased Jobs `1 -> 2`; and
`test_review_r4_retry.py::test_retry_reconciliation_does_not_bypass_invalid_predecessor[True]`
failed because attempt `9` returned the existing attempt-2 successor. The new
local micro nodes are `test_public_initial_replay_resolves_run_and_job_before_create`
and `test_invalid_predecessor_lineage_is_typed_and_not_reconciled`; the existing
valid lost-ack control remains
`test_repair_commit_uncertainty_and_replay_have_exact_pair`.

F01 uses read-only union identity resolution before any run insert; an existing
run must map to exactly one workspace-scoped canonical Job whose ID equals the
run pointer and whose manifest/generation passes `bind_job`. Replay returns
that exact pair with no enqueue or commit. F03 raises a typed
`S12_EXPORT_INVALID_LINEAGE` denial. Preparation errors roll back directly;
only exceptions from `session.commit()` enter exact-pair reconciliation.

The R3 matrix authority remains unchanged: 62 tracked rows are
C01-C32 + S01-S10 + P01-P10 + R01-R10, not 62 passes. R5 maps F01/F03 to the
existing R03/S03/C06/C07/C15 meanings and retains the R01 attempt-chain,
R02 contested-operation/all-row, sequential replay, malformed-lineage and
commit/lost-ack controls without renaming or deleting rows. Evidence and
runtime use the R5 roots at
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r5-owner-submission\20260912T164057Z\RETRY`
and `C:\Users\Admin\Documents\Codex\work\s12-r5\20260912T164057Z\RETRY`.

## R6 F01 union identity correction (Hermes owner, 2026-09-15)

Owner transfer: S12-LC3-RETRY carried over once from the Codex owner to this
Hermes session (`20260915_201417_80e003`, model `ocg/deepseek-v4.1-flash`,
provider `custom`, fallback OFF) at user request
(USER_REQUESTED_PLATFORM_MODEL_TRANSFER). Wave base synced with the single
guarded `git merge --ff-only 83af5167e9dddc931bc8590f547684c0c811784b`
(fast-forward from `c60235f`, clean tree, no conflict).

F01 correction (R6_ACCEPTANCE M01-M19): `app/workflow/s12_export_jobs.py` now
resolves a Run's durable Job through ONE union discovery/classification
contract used by initial replay, retry preparation and fresh commit
reconciliation (enqueue/bind/lost-ack). Discovery gathers the claim UNION
before any scope/type filter: run pointer, canonical key in ANY workspace,
manifest `run_id` claims (ANY key/workspace), and relevant generation/owner
evidence; equal generation alone is not identity. Exactly one valid claimant
is accepted (missing pointer restored once); a true zero-Job orphan is
repaired exactly once (converging on a concurrent winner); contradictory,
ambiguous or unresolved identity is a typed 409 denial with zero mutation;
read/malformed-JSON failures fail closed.

Verification: new `tests/s12/s12-lc3-retry/test_r6_identity_resolution.py`
46/46 passed (79.92s, fresh migrated DBs, basetemp `%TEMP%/s12r6d_1`).
Affected lane modules re-run: test_export_jobs_api / test_r4_retry_execution /
test_r5_f01_f03 / test_retry_identity_matrix / test_retry_migration /
test_s12_t03c_c1_closure -> 39/39 passed (57.07s). `ruff check --select F`
clean, py_compile OK. Documentation: bounded R5-text correction + R6 addendum
in `docs/contracts/s12-export.md`.

A savepoint-based orphan-convergence draft was removed during this correction:
the pysqlite legacy transaction mode can auto-commit a savepoint's contents
when the session has no prior DML, breaking atomicity (probe:
`probe_savepoint.py` in the runtime lane). Convergence now rolls back the
conflicted attempt and re-resolves from durable truth.

Evidence: `...\outputs\s12-r6-hermes\20260915T131158Z\RETRY` (runtime:
`...\Codex\work\s12h\20260915T131158Z\RETRY`, live COMMAND_LEDGER.jsonl).
Transport checkpoint only - NOT approved; Codex review remains the gate.

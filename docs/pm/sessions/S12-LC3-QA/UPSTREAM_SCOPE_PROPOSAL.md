# S12-LC3-QA R2 — upstream scope proposal

Status: `PROPOSAL_ONLY`; no upstream production file was edited by QA.
The R1 proposal above remains historical. The R2 addendum below is the
minimal exact correction scope identified by the fresh retry and public-chain
evidence. It is not an approval or closure decision.

## Exact shared changes required

1. Add one supported source-ingest bridge owned by the durable video/import
   owner. Preferred contract: `POST
   /api/v2/projects/{project_id:uuid}/videos/{video_id:uuid}/import` multipart
   upload, with a server-owned managed artifact, ffprobe metadata, source SHA,
   ownership link, and an idempotency key. It must return the actual durable
   `video_item_id` and `source_artifact_id`; repeated identical upload must
   replay rather than duplicate. The compatibility decision is explicit: the
   existing legacy 12-hex create/upload/analyze chain remains supported, but a
   new v2 UUID project/video must not require guessing or crossing into the
   legacy filesystem namespace.

2. Add an S09-owned public/service-backed StructuralLockManifest creation and
   activation path for a current `(workspace, project, video, source_generation)`.
   Its request must carry canonical manifest content and idempotency identity;
   the service must compute/verify the manifest hash, persist route/segment
   evidence, enforce project/video ownership, and return the actual manifest
   ID/hash/generation. No client filesystem path, ready/completed flag, or
   arbitrary route may be trusted. The existing
   `GET .../full-apply-authority` remains read-only.

3. Define the prerequisite fixture dependency chain in the owning public
   services: a published `CharacterPackVersion`/asset, an owned object role and
   project-cast mapping, a `ReskinConfig` pinned to the active structural lock,
   then `POST /api/v2/s09-approvals/reapprove`. The current
   `POST /api/v2/reskin-configs` route may remain the creation boundary, but
   the clean-runtime path must expose supported creation/upload/publish APIs
   for the required pack and role identities (or document the exact seeded
   catalog contract). `GET /api/v2/project-cast/picker/packs` must not be the
   only source when it returns an empty catalog.

4. Preserve the S09 → S10 decision: reapproval returns an immutable v2
   checkpoint whose `full_apply_authority` is derived from persisted source,
   lock, segment, role, replacement asset, and timing rows. `POST
   /api/v2/projects/{project_id}/full-apply` must accept only that current
   checkpoint and enqueue the durable worker; it must never fabricate a
   completed run/publication. S12 context/submit then consumes the same
   server-resolved pins.

## Required shared tests and compatibility gates

- Durable video import integration: upload → artifact ready → source pin,
  replay/idempotency, cross-project denial, tampered/partial denial, and
  legacy 12-hex compatibility.
- Structural lock/S09 integration: create/activate, hash verification,
  generation pin, route evidence ownership, reapprove v2, read-only
  full-apply-authority, stale/missing/cross-project denial, and zero mutation
  on fail-closed paths.
- S10 integration: current reapproved checkpoint → public Full Apply submit →
  durable worker → validated publication/media, with cancel/retry/restart and
  at-most-one successor under contention.
- S12 Q1 normal-product integration: use only returned IDs through source,
  authority, submit, worker, publisher, result/media and UI reload/recovery;
  assert unchanged chunk hashes/mtimes and all endpoint denials. Retain the
  existing mechanism fixtures as mechanism tests only; do not convert a
  current-authority failure into an expected 409.

## Dependency/decision record

The proposal has two upstream dependencies: (a) durable video import or an
explicit legacy-to-v2 identity bridge, and (b) the S09 StructuralLockManifest
creation/activation authority plus a supported published-pack catalog. The
minimal implementation decision is to ship the v2 import route and the S09
lock route/service together, with stable idempotency and ownership semantics;
then transport the resulting shared contract/tests to QA. Until those are
available, Q1 remains externally blocked and no acceptance job, completed
Full Apply row, or media result may be fabricated by this QA worker.

## R2 exact correction addendum

### Q1 retry identity defect

The isolated `FIXTURE_ONLY` mechanism fixtures now use current server-owned
Full Apply pins, a real managed root, and actual `retry_export` calls. Both
required nodes still fail because the frozen implementation tries to create a
successor with the same natural identity as the cancelled predecessor:

- `app/api/routes/s12_export.py::retry_export` validates current context and
  resubmits the predecessor pins with `idempotency_key=s12_retry:{run_id}`;
- `app/persistence/s12_export.py::S12ExportRepository.create_run` computes
  the canonical natural key and inserts;
- `app/persistence/s12_export.py::_replay_after_conflict` searches by
  idempotency/natural key and then raises `export run creation conflict
  resolved to no row`;
- `migrations/versions/c3d4e5f6a7b8_s12_export_domain.py` enforces unique
  `uq_s12_run_identity` over workspace/project/video/profile/plan/checkpoint.

The first valid retry request reaches current authority and then returns HTTP
500 on the unique natural-key conflict; a concurrent second request cannot
observe a successor. The smallest upstream change is an explicit immutable
retry-attempt/successor identity or equivalent retry discriminator, while
retaining the existing lineage uniqueness guard. Repeat retry and two live
callers must resolve to exactly one usable successor; the cancelled
predecessor must never be replayed and 409/500 must not be accepted as
success.

Upstream owner: S12 export backend/persistence owner. Required tests before
QA rerun: cancelled predecessor → one new run/job; repeat retry → same
successor with `created=False`; two live callers → one winner plus typed
loser/replay; complete workspace/project/video/checkpoint/manifest/plan pins
and managed paths on all rows; active/stale/missing/cross-project/
tampered/partial denial with zero mutation; idempotency/transaction retry,
worker restart, and retained-data compatibility. Keep
`uq_s12_run_identity` rather than removing it.

### Q2 exact public graph gap

The public source graph was traced to these current owners:

- `app/api/routes/projects.py` and `ProjectWorkflowService.create_project`:
  legacy 12-hex project and upload;
- `app/api/routes/projects.py` analyze and
  `AnalyzeOrchestrator._ensure_durable_shell`: UUID durable shell plus import,
  proxy, and scene jobs;
- `app/api/routes/durable_videos.py::create_video`: v2 UUID metadata only,
  with no public source import operation;
- `app/api/routes/reskin_config.py::create_reskin_config`:
  role/config ownership boundary;
- `app/api/routes/s09_approval.py::reapprove_checkpoint` and
  `app/services/s09_approval.py::S09ApprovalRepository.submit_checkpoint_v2`:
  consume a ReskinConfig and do not create a StructuralLock;
- `app/api/routes/s10_full_apply.py::submit_full_apply`: current checkpoint
  to durable Full Apply;
- `app/persistence/structural_lock.py::StructuralLockRepository.create_manifest`:
  persistence capability with no public manifest create/activate route in the
  captured OpenAPI path set.

The smallest shared API delta is: (1) a v2 source-ingest bridge,
preferably `POST /api/v2/projects/{project_id:uuid}/videos/{video_id:uuid}/import`
multipart, that publishes a managed artifact, verifies ffprobe/SHA256,
enforces ownership, returns actual durable IDs, and replays idempotently; (2)
an S09-owned create/activate operation for a current
`StructuralLockManifest` keyed by workspace/project/video/source generation,
with server canonical hash, route/segment evidence, ownership, and
idempotency; and (3) the smallest supported published pack/asset and owned
role/project-cast path needed by `create_reskin_config` (or an explicit
catalog-seeding API contract). Existing legacy 12-hex create/upload/analyze
compatibility must remain explicit; a v2 UUID must not cross namespaces by
guessing.

The first valid missing request in R2 is not a guessed-ID 404: actual public
IDs produced empty `reskin_configs`, `object_roles`, `project_cast`, and
`s09_approvals`, while readiness was `not_run`. Thus no valid current
StructuralLock/ReskinConfig/ApplyCheckpoint body exists for reapprove or
Full Apply. Clean S12 context returned
`S12_EXPORT_FULL_APPLY_MISSING` and `S12_EXPORT_LOCK_MISSING`; submit returned
409 with zero S12 run mutation. Dependency order is:

`v2 source identity/import bridge` → `current lock + evidence` →
`owned pack/role/cast/config` → `S09 reapprove` → `S10 Full Apply worker`
→ `S12 normal-product acceptance`.

Proposed shared tests must assert returned IDs, ownership scope, idempotency,
retained source/proxy media, exact hashes, zero mutation on missing/stale/
tampered/partial/cross-project inputs, and the S09→S10 ordering. QA does not
implement this proposal upstream.

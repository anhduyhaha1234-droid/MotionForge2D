# S12-LC3-QA R1 — upstream scope proposal

Status: `PROPOSAL_ONLY`; no upstream production file was edited by QA.
This is the minimal contract work needed before Q1 normal-product export
acceptance can be replayed without fabricated authority.

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


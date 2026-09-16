# S12 Export — frozen contract (S12-T01, `s12-export-v1`)

Owner: S12-T01. Consumers: T02 (capabilities/profiles), T03A (durable
run/variant/chunk + migration), T03B (chunk render/stitch/resume), T03C
(durable job/API + publication), T04A (validator), T05 (UI), T06A/B
(packaging/acceptance). No consumer may widen this contract without a new
Codex-reviewed version.

## 1. Request / response

- `POST /api/v2/projects/{project_id}/export/preflight`
  - Body: `ExportPreflightRequest` (`app/schemas/s12_export.py`):
    `video_item_id`, `profile_id`, `aspect_handling`, `checkpoint`
    (`checkpoint_id/hash/revision`), `lock` (`manifest_id/hash/generation`).
  - Response: `ExportPreflightResponse`: `contract_version`,
    `profile` (frozen dims/codec + `supported` filled by T02),
    `source_kind` (`native_4k | upscale_4k | below_4k`),
    `eligible`, `reasons[]` (closed codes), `checks[]` (per-gate detail),
    `estimate_bytes` + `estimate_basis` (heuristic, T02 refines),
    `readiness_status/policy`.
- Strict `extra="forbid"` everywhere; sha256 = lowercase 64-hex.
- **No render happens inside the HTTP request** — evaluation is pure
  (`app/services/s12_export/preflight.py:evaluate_preflight`).

## 2. Reason codes (closed)

`S12_EXPORT_OK`, `S12_EXPORT_NOT_READY`, `S12_EXPORT_SOURCE_MISSING`,
`S12_EXPORT_SOURCE_NOT_READY`, `S12_EXPORT_SOURCE_PARTIAL`,
`S12_EXPORT_LOCK_MISSING`, `S12_EXPORT_STALE_CHECKPOINT`,
`S12_EXPORT_STALE_POLICY`, `S12_EXPORT_CROSS_PROJECT`,
`S12_EXPORT_UNSUPPORTED_PROFILE`, `S12_EXPORT_ASPECT_MISMATCH`,
`S12_EXPORT_DISK_INSUFFICIENT`, `S12_EXPORT_UNKNOWN_PROJECT`,
`S12_EXPORT_UNKNOWN_VIDEO`.

HTTP mapping: unknown project/video → 404; cross-project → 409 (via
`checkpoint_cross_project` check → `S12_EXPORT_CROSS_PROJECT` reason, and
video/project mismatch → 404); stale/param → 422.

## 3. Native 4K vs upscale (Scenario F)

- Native 4K **only** when PROVED native origin (F-OBS-01): recorded
  artifact sha256 + a matching full-apply checkpoint pin + ready 3840x2160
  source with no .partial marker.  A 3840x2160 file of unproved origin
  (e.g. already-upscaled) is `upscale_4k`.  Dims/file size alone never
  decide; response carries `source_provenance: proved-native | unproven`.
- Anything else targeting 4K is `upscale_4k` and must carry a labeled
  `upscale_method` (T02 provides the method; T01 marks it required).
- Aspect: target DAR must match source DAR within 1% or the request must use
  `letterbox`; `fail_closed` + drift → `S12_EXPORT_ASPECT_MISMATCH`. Never
  silent stretch/crop.

## 4. Checkpoint / manifest / profile contracts

- Checkpoint pin: `ApplyCheckpoint` row (`revision = 1` immutable) compared
  read-only: id present in workspace, hash equal, `reskin_config_revision`
  equal, `checkpoint.project_id == run project` (else cross-project).
- Manifest pin: `StructuralLockRepository.get_manifest` in the same workspace;
  hash equal, same video + project, generation equal, status draft/active.
  Missing → `S12_EXPORT_LOCK_MISSING`.
- Profile table (frozen dims):

  | profile_id         | WxH       | codec |
  |--------------------|-----------|-------|
  | master-4k-h264     | 3840x2160 | h264  |
  | master-4k-hevc     | 3840x2160 | hevc  |
  | preview-1080p-h264 | 1920x1080 | h264  |

  `supported` comes from the C02 real capability probe
  (`probe_encoder_support`: ffmpeg binary + `-encoders` listing + 1-frame
  CPU encode smoke, rc=0; failures never cached, never silent fallback).
  T02 consumes the measured basis and refines estimates/methods.

## 5. Validation contract (T04A consumes)

`ValidationContract`: probes `resolution, codec, streams, frame_count,
frame_order, timebase, duration, av_policy, provenance, completeness`;
master 3840x2160; verdicts `PASS | FAIL | NOT_MEASURED` (insufficient
evidence → FAIL or NOT_MEASURED, never fake PASS); `.partial` suffix frozen.

## 6. Publication contract (T03C consumes)

`PublicationContract`: requires validation PASS + current readiness +
identity match + ownership fence; never overwrites completed output; `.partial`
never visible as completed.

## 7. Readiness / disk / source rules

- Readiness consumed from `compute_project_readiness` (Decision F) at
  preflight time; `ready` + current policy required. T01 does not change the
  upstream implementation.
- Disk: `shutil.disk_usage` on the managed root vs heuristic estimate
  `W*H*frames*0.5B/px` with basis string; unknown frame count → insufficient
  (fail-closed).
- Source: `VideoItem.source_artifact_id` row must exist with `state == ready`;
  `.partial` in path → `S12_EXPORT_SOURCE_PARTIAL`.

## 8. Server-owned export authority (C2 F02) — `app/services/s12_export/authority.py`

`resolve_export_authority(session, *, workspace_id, project_id, video_item_id,
checkpoint_id, checkpoint_hash, checkpoint_revision, manifest_id,
manifest_hash, manifest_generation) -> ExportAuthority` resolves READ-ONLY,
server-side, every durable identity an export may render from. Never trusts
client-supplied source/output paths, frame counts, fps or pins.

Binding checks (each returned as `ExportAuthorityCheck(name, passed, reason,
detail)`; `ExportAuthority.resolved` = all pass):
- `project`/`video` containment (404 domain);
- `checkpoint` — row exists in workspace, same project, hash + revision equal;
- `config_pack` — checkpoint's reskin_config exists, same workspace, revision
  equal, pack_version_id set (else `S12_EXPORT_CONFIG_MISSING`);
- `checkpoint_cross_project` — hard `S12_EXPORT_CROSS_PROJECT`;
- `structural_lock` — manifest exists in workspace, same video/project/
  generation, hash equal, status draft|active (else `S12_EXPORT_LOCK_MISSING`);
- `full_apply_authority` — newest completed publication of the newest
  completed `S10FullApplyRun` for the video, publication pins the SAME
  checkpoint, artifact row ready + sha256(64) + not `.partial`. Missing →
  `S12_EXPORT_FULL_APPLY_MISSING`; artifact unusable →
  `S12_EXPORT_SOURCE_STALE`. An original import is NEVER the export source;
- `source_origin` — `proved-native` ONLY for a 3840x2160 canvas WITH the
  resolved Full Apply authority AND measured rational timing (fps_num/den
  from the run/publication). Everything else is `upscale`/`unproven`
  (already-upscaled-4K honesty; artifact SHA + dimensions is never proof).

Resolved durable fields returned to consumers: `source_artifact_id`,
`source_sha256`, `source_frame_count`, `source_fps_num/den`, `source_width/
height`, `full_apply_run_id`, `full_apply_publication_id`.

Preflight response (`ExportPreflightResponse`) carries these server-resolved
fields; `job_id` is null on a pure preflight because preflight NEVER mutates
(no run/Job/output is created — invalid authority = zero mutation). The
submit route (T03C) must return the ACTUAL durable Job ID via
`JobInfo.job_id` — never `job.id` — for every successful submit.

Call-chain example (T03C submit consumes the same authority):
`POST /api/v2/projects/{pid}/export/preflight` →
`resolve_export_authority` → `PreflightContext` →
`evaluate_preflight` → verdict + authority ids. Source of truth rows:
`s10_full_apply_run` (status=completed, fps_num/fps_den),
`s10_full_apply_publication` (state=completed, artifact_id, checkpoint pin,
frame_count), `artifact` (state=ready, sha256), `apply_checkpoint`,
`reskin_config`, `structural_lock_manifest`.

Uncertainty is fail-closed: absence of any bind (or of measured timing)
refuses the preflight — readiness is never lowered, no auto-approval.

## Normal Export context (S12-LC3-UI)

The project/video Export entry point reads the server-owned snapshot from
`GET /api/v2/projects/{project_id}/export/context?video_item_id={video_item_id}`.
The response returns the scoped checkpoint, structural-lock, plan, supported
profiles, current durable S12 run pointer, and `context_revision`. It never
returns client filesystem paths. The browser may display these identities and
send the returned `context_revision` when submitting, but users do not type
checkpoint, manifest, plan, frame, fps, or path fields.

Submit and retry re-resolve the current authority and reject a stale
`context_revision` or lineage with `409`; a successful response returns the
actual durable run pointer. The UI stores only that pointer under the scoped
workspace/project/video key and refetches server truth after navigation,
refresh, retry, or recovery.

## S12-LC3-RETRY immutable retry lineage

Retries are append-only attempt rows. A failed or cancelled predecessor is
immutable; its frozen checkpoint, manifest, profile, plan, frame count and
canonical chunk configuration are copied byte-for-byte to the immediate
successor. The successor increments `attempt`, retains `lineage_id`, sets
`predecessor_run_id`, and receives a fresh durable Job. The unique predecessor
pointer is the database race arbiter: concurrent or repeated retries return
the same successor and its actual Job pointer. Retrying that successor creates
only its next successor.

Initial-submit deduplication remains workspace-scoped by the supplied
`idempotency_key` and initial natural key; retry attempts use their own
predecessor/attempt identity and do not reuse the initial six-field
uniqueness rule. Job binding is durable and one-to-one. A missing, ambiguous,
cross-workspace, stale, materially different, corrupt or query-failed run/Job
identity fails closed with rollback and no unintended mutation. Plan and
checkpoint pins are never randomized, reset, deleted or rewritten.

## S12-LC3-R4 retry execution and uncertainty addendum

The durable worker admits a retry attempt only after validating the complete
chain: a non-null lineage has a root attempt 1, every predecessor is the
immediate prior attempt in the same workspace/project/video and frozen pin
set, every predecessor is terminal, and no pointer is missing, self-referential
or cyclic. The worker claim may additionally carry the durable Job ID; a
different or corrupt pointer is rejected before lease mutation. Therefore
attempts 2 and 3 use the same claim/fence operation as attempt 1 without
resetting their attempt number or changing their plan/checkpoint.

Retry successor creation, exact Job creation, and run-to-Job binding are one
transaction. A committed retry has one immediate successor and one Job; a
missing Job may be repaired only by an exact-key, exact-manifest bind, and a
lost commit acknowledgement is reconciled by rereading the unique successor
and its unfiltered workspace-scoped Job rows. Ambiguous, wrong-scope, tampered,
query-failed, enqueue-failed or bind-failed identities roll back with zero new
Run/Job rows. The initial-submit idempotency key remains unchanged and no
global JobService or unrelated domain table is modified.

## S12-LC3-R5 initial replay and lineage denial

Initial submission resolves the union of workspace idempotency and natural-key
identities read-only before inserting a run. If an equivalent run already
exists, replay resolves its durable Job through the shared R6 union
discovery/classification contract below before returning the original run/Job
pair; an ordinary replay does not enqueue, repair or commit, while the two
bounded repairs (missing-pointer restore, true zero-Job orphan creation) are
each applied exactly once. A missing, ambiguous, mismatched or corrupt binding
fails closed with zero Run/Job delta. Only a fresh identity proceeds to run
and Job creation.

Malformed retry ancestry is a deterministic `S12_EXPORT_INVALID_LINEAGE`
denial (`409`), including an invalid predecessor attempt while a later
successor already exists. Retry preparation, lookup, enqueue and bind failures
are rolled back without commit reconciliation. Reconciliation is reserved for
an exception raised by the commit operation itself, where the exact successor
and Job pair is reread to converge after a genuinely uncertain acknowledgment.

## S12-LC3-R6 union Job discovery/classification (F01 addendum)

One discovery/classification contract resolves which durable Job actually
claims an export Run, and the same contract serves initial replay, retry
preparation, and fresh commit reconciliation (enqueue/bind/lost-ack). The
claim set is a UNION gathered BEFORE any scope/type filter: the run's durable
pointer, the canonical key `s12_export_job:{run.id}` in ANY workspace, any Job
whose `input_manifest_json.run_id` is this run (ANY key/workspace), and
relevant generation/owner evidence. A Job that still carries the manifest run
identity claims the run even when its key or workspace changed, so it is never
filtered away; equal `input_generation` alone is not a Run identity (valid
retry attempts legitimately share `run.plan_hash`).

Exactly one valid claimant is accepted (a missing pointer is restored once);
a true zero-Job orphan (pointer null, no claimant, no unresolved evidence) is
repaired with exactly one Job creation, converging on a concurrent winner.
Contradictory, ambiguous or unresolved identity — off-key, cross-workspace,
generation/type/owner/manifest mismatch, multiple claimants, unreadable or
malformed relevant JSON — is a typed `S12ExportSubmitError` denial (`409`)
with zero mutation: Run/Job rows, revisions, pointers and artifacts are
preserved. Read/parse failures fail closed before any mutation.

## S12-LC3-R7 semantic identity and sibling proof (F02 addendum)

Manifest run identity is ALWAYS decided semantically (parsed JSON), never by
raw byte/substring equality: a run id encoded with JSON `\uXXXX` escapes or
merely reformatted whitespace must not change classification. Candidate
discovery for a Run's durable Job is a union gathered BEFORE trusting
`job_type` / `workspace_id` / `owner_id` / key fields — any of them may be the
corrupted field: the run pointer, the canonical key in any scope, raw
manifest mentions, and every Job whose pinned generation matches the run's
plan. Keeping a candidate out of classification requires PROOF that it
belongs to another run: its manifest run identity must name a run that EXISTS
and whose durable pointer IS that Job. A candidate whose manifest run
reference is absent, names a nonexistent run, or names a run that does not
own it is unresolved relevant evidence: the run is neither re-bound nor
repaired (typed `S12_EXPORT_JOB_IDENTITY_UNRESOLVED`, zero mutation). A Job
that semantically claims the run but fails identity — pointer-discovered,
canonical-key, or semantic manifest claim — is a
`S12_EXPORT_JOB_IDENTITY_CONTRADICTION` denial. Valid same-generation
siblings (proven ownership) and the bounded repairs above are unchanged.

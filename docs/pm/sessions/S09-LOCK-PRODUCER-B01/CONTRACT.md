# S09-LOCK-PRODUCER-B01 — public StructuralLock producer contract

Task: S09-LOCK-PRODUCER-B01 (Hermes owner after one-time platform/model transfer).
Base: `83af5167e9dddc931bc8590f547684c0c811784b` (branch `codex/s09-lock-producer-b01-r6`).

## Endpoint

`POST /api/v2/projects/{project_id}/videos/{video_item_id}/structural-lock`

- 201 → a NEW `StructuralLockManifest` version was created (response carries
  `manifest_id`, `manifest_hash`, `source_generation`, `policy_version`,
  `version`, `status`, `segment_count`, `route_decisions_created`).
- 200 → equivalent replay: the SAME durable row (`created=false`,
  `route_decisions_created=0`).
- Denials are TYPED: `{"detail": {"code": ..., "message": ..., "reasons": [...]}}`.

| HTTP | code | meaning |
|---|---|---|
| 404 | `STRUCTURAL_LOCK_UNKNOWN_PROJECT` | project unknown or outside the server-owned workspace |
| 404 | `STRUCTURAL_LOCK_UNKNOWN_VIDEO` | video unknown or not owned by the project |
| 409 | `STRUCTURAL_LOCK_STALE_EXPECTED_GENERATION` | `expected_source_generation` ≠ current backend generation |
| 409 | `STRUCTURAL_LOCK_STALE_EXPECTED_SOURCE_SHA256` | `expected_source_sha256` ≠ current source artifact checksum |
| 409 | `STRUCTURAL_LOCK_CONFLICT` | idempotency/natural-key conflict (stale key, concurrent version) |
| 422 | `STRUCTURAL_LOCK_UNSUPPORTED_POLICY` | `policy_version` outside the documented set (`structural-thresholds-v1`) |
| 422 | `STRUCTURAL_LOCK_SOURCE_NOT_READY` | no source artifact / not ready / missing probe metadata |
| 422 | `STRUCTURAL_LOCK_SOURCE_TAMPERED` | source checksum missing or not a lowercase sha256 hex |
| 422 | `STRUCTURAL_LOCK_SOURCE_TIMING_MISSING` | fps numerator/denominator/duration/dimensions missing or non-positive; probe reports no exact `nb_frames`/positive rational |
| 422 | `STRUCTURAL_LOCK_SOURCE_TIMING_UNPROVEN` | source artifact missing/unreadable, bytes ≠ recorded checksum, or the verified probe failed |
| 422 | `STRUCTURAL_LOCK_SOURCE_VFR` | source is not constant frame rate (`r_frame_rate` ≠ `avg_frame_rate`) |
| 422 | `STRUCTURAL_LOCK_SOURCE_TIMING_MISMATCH` | persisted facts disagree with the exact probe (rational FPS, dimensions, or frame-exact duration |
| 422 | `STRUCTURAL_LOCK_EVIDENCE_MISSING` | no scenes, no current active segments, or removal-only-only graph |
| 422 | `STRUCTURAL_LOCK_EVIDENCE_TAMPERED` | corrupt/non-finite stored evidence JSON; foreign project scope |
| 422 | `STRUCTURAL_LOCK_GEOMETRY_MISSING` | segment without segmentation/prompt points or boxes |
| 422 | `STRUCTURAL_LOCK_ROLE_MISSING` | segment role missing or out of scope (workspace/project/video) |
| 422 | `STRUCTURAL_LOCK_ROLE_MAPPING_MISSING` | no ReskinConfig for the role, or pack not published/ready |
| 422 | `STRUCTURAL_LOCK_MASK_CROSS_SCOPE` | mask artifact missing or outside the workspace |
| 422 | `STRUCTURAL_LOCK_UNSUPPORTED_ROUTE` | current persisted route outside `{sprite_affine, pose_swap, controlled_redraw}` — no downgrade |
| 422 | `STRUCTURAL_LOCK_ROUTE_AMBIGUOUS` | multiple same-instant newest route decisions with different routes |
| 422 | `STRUCTURAL_LOCK_READ_ERROR` | durable read failure (fail closed, zero mutation) |

Unknown request fields — workspace ids, filesystem paths, routes, manifest
blobs, readiness flags — are rejected at the schema boundary (422,
`extra="forbid"`). The server NEVER reads authority from the body.

## Server-derived manifest (all values resolved from durable rows)

- `workspace_id` — server-owned `DEFAULT_WORKSPACE_ID` (never client-supplied).
- `source_generation` — `ObjectIntelligenceRepository.current_generation`
  (video's current source-artifact sha + newest completed `DISCOVER_OBJECTS`
  job), the same backend authority the extraction pipeline uses.
- `frame_count` / `timebase` — R7 F03 EXACT source-timing proof
  (`app/services/structural_lock_source_timing.py`): persisted
  fps_num/fps_den/duration_ms/width/height must all be present and positive;
  the managed source artifact bytes must hash to the recorded checksum; the
  verified bounded import probe (`video_import.probe_source`) must classify
  the source CFR with EQUAL `r_frame_rate`/`avg_frame_rate` rationals; the
  frame count is the container's exact `nb_frames` (never
  `round(duration × fps)` — a persisted duration that differs by even 1 ms
  is denied) and every persisted fact must equal the probe (rational FPS,
  dimensions, and `duration_ms == round(nb_frames × den × 1000 / num)` via
  exact Fraction arithmetic). `{fps: num/den, time_base: "{den}/{num}",
  start_time_ms: 0}` is stamped from the proof; the response also reports
  `source_frame_count`, `source_fps_num`, `source_fps_den`.
- `shot_order` — durable Scene ids ordered by position (unique, non-empty).
- `segments` — the CURRENT ACTIVE occurrence segments of the current
  generation; removal-only role kinds (`source_overlay`) are excluded by
  contract (never replacement candidates); every included segment must carry
  geometry evidence, an in-scope role, a role mapping with a published/ready
  pack, and an in-workspace mask when referenced. Zero eligible segments is a
  typed denial — an empty manifest is never a success.
- Route decision (TARGET_PROFILE §4 P0-7): the CURRENT persisted
  `segment_render_route` decision (latest row) is reused; a non-executable
  route is refused without downgrade. When no decision exists, the producer
  persists ONE deterministic default decision (route `sprite_affine`, anchor
  `{0.5,0.5}`, the segment's frame range, `confidence_source="derived"`,
  idempotency key `structural-lock-produce:{video}:{generation}:{segment}`
  bound to the produced manifest) in the SAME transaction as the manifest.
- `fingerprints.z_order` / `fingerprints.contacts` — sha256 over canonical
  JSON of the included segments' z-order/visibility evidence plus in-scope
  occlusion edges / contact edges respectively.

## Transaction & history semantics

- Creation goes ONLY through `StructuralLockRepository.create_manifest`:
  idempotent replay converges on the same row; a materially different payload
  under the same key conflicts (409); the previous draft/active version is
  archived (`superseded_by_id`, never rewritten).
- The route commits explicitly (production `get_db_session` is close-only);
  any failure — including mid-write failures — rolls the whole transaction
  back: zero partially authoritative manifest/route rows.
- No auto-approval: pinning stays the existing ReskinConfig CAS pin
  (`PATCH /api/v2/reskin-configs/{id}` with an explicit `revision`), and
  approval stays the existing S09 reapproval path.

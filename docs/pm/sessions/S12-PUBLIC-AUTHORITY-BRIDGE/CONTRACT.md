# S12-PUBLIC-AUTHORITY-BRIDGE — CONTRACT (draft v0.1, PENDING FREEZE)

Task: `S12-PUBLIC-AUTHORITY-BRIDGE` — bounded cross-sprint bridge authorized by the
R7 decision (`ACCEPTANCE_R7.md` B03–B06, `SHARED_CONTRACT.md`), owned by one NEW
session under Manager B.
Owner session: `20260916_105450_f38ead` (Hermes, route `ocg/deepseek-v4.1-flash` /
provider `custom`, fallback OFF, native thinking ON).
Worktree: `C:/Users/Admin/Documents/Codex/work/s12-r7-authority-bridge`,
branch `codex/s12-r7-authority-bridge`, wave-base
`35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86` (verified in this session).
Status: `CONTRACT_DRAFTED_PENDING_FREEZE` — no production code exists yet.
Freeze partners: Manager B (`20260915_194636_b5ea4c`) + QA (`20260915_201612_aeb5e3`).

This contract fixes the exact interface the bridge implements. It is grounded in the
real code at wave-base (file:line references are to the worktree above), not in
abstractions. Sections: (1) frame conventions, (2) temporal partition, (3) layer
identity + repeated roles, (4) geometry, (5) immutable authority block, (6) schema
compatibility, (7) fail-closed reason codes, (8) worker consumption, (9) open
questions, plus dependencies/non-goals.

## 0. Why this bridge exists (F04 root cause, exact locations)

`REVIEW.md` F04 shows the S09 executable authority and the S10 planner disagree.
The collision is structural, not cosmetic:

1. `app/services/s10_full_apply.py:224–276` (`_canonical_planner_inputs`) maps each
   authority **segment 1:1 to a scene shot** (`shots.append({"shot_id": seg_id, ...})`,
   line 262) and each **segment to `layer_id = role_id`** (lines 265–266). Two
   co-occurring occurrences covering `[0,119]` therefore become two overlapping
   "shots" and the planner raises `shots overlap or non-monotonic`
   (`app/services/s10_chunk_plan.py:159–176`; raw `planner-1/captured_cooccurrence.json`).
2. The same mapping gives two occurrences of ONE role the same `layer_id`; the
   planner rejects `duplicate layer_id` (`s10_chunk_plan.py:211–213`; raw
   `planner-1/same_role_two_disjoint_occurrences.json`).
3. S09 eligibility treats **points OR boxes** as geometry
   (`app/services/s09_approval.py:1312–1329`) while S10 requires **boxes** to derive
   an affected region (`s10_full_apply.py:145–171`); points-only authority is
   `full_apply_executable=true` yet fails at submit with `no boxed affected
   geometry` (raw `new-producer-4/points-only.json`).
4. Static risk to close in the same bridge: `app/workflow/s10_full_apply_jobs.py:
   443–465` (`_stitch_verified_chunks`) deduplicates chunks by
   `(shot_id, core_start_frame, core_end_frame)` and keeps only the FIRST layer
   artifact — dedup is not composition (R7 B06).

Adopted decision (F04 + `SHARED_CONTRACT.md` "Product contract"): **scene shots are
the disjoint contiguous temporal partition of the full source; occurrence intervals
are active layers inside that partition** (overlap allowed). All identifiers, ranges,
regions and ordering are frozen into the S09 approval authority and hashed with the
checkpoint.

## 1. Frame conventions (exact, per site)

All frame numbers in authority / timeline / plan / chunks are **integer source
frames**, 0-based, and every range is **INCLUSIVE on both ends**: `[start_frame,
end_frame]`; range length = `end_frame - start_frame + 1`. Verified conventions:

- Shot/partition validation: a shot may not overlap (`cur.start <= prev.end` →
  error) and may not leave a gap (`cur.start != prev.end + 1` → error);
  `frame_count` must equal `last.end + 1`; first shot starts at 0
  (`s10_chunk_plan.py:155–176,342–351`).
- 1-frame shot/boundary: `start == end` is valid (explicit comment
  `s10_chunk_plan.py:175`); adjacent shots `…[0,59][60,119]…` are the canonical
  one-frame boundary case.
- Occurrence interval: `end_frame >= start_frame`, both `>= 0`
  (`app/persistence/models.py` occurrence CHECKs); segment `[a,b]` is active on
  frames `a..b`.
- Chunk core range: inclusive; `core_start = s_start + ci*chunk_frames`,
  `core_end = min(core_start + chunk_frames - 1, s_end)` (`s10_chunk_plan.py:
  383–384`); `overlap_before/after` are frame counts (default `chunk_frames=48`,
  `overlap_frames=4`).
- Regions: `affected_region = [x, y, w, h]` **normalized [0,1]** of the source
  frame; `x+w <= 1+1e-9`, `y+h <= 1+1e-9` (`renderer_contract.py:275–297`
  `AffectedRegion`; pixel mapping `_region_px` multiplies by `w,h`
  `composite.py:299–306`).
- Source vs scene-local coordinates: **the authority, timeline and plan use GLOBAL
  source frames only** (`[0, frame_count)`). Scene rows carry both global frames and
  `start_time_ms/end_time_ms`; any scene-local display offset is
  `scene.start_frame` and MUST NOT appear in a frozen timeline/plan range. QA/UI
  conversions are display concerns outside this plan contract.
- Timebase: rational `fps_num/fps_den` (positive ints). Frame `k` timestamp =
  `start_time_ms + k * 1000 * fps_den / fps_num`. A float `fps` is display data,
  never authority (F03: no `or 30`, no `or 1`, no rounding to invent a count).

## 2. Temporal partition (scene shots)

- The partition is built from **persisted `Scene` rows of the video item** ordered by
  `Scene.position, Scene.id` (`structural_lock_producer.py:503–510`) — each Scene
  has authoritative `start_frame/end_frame` (`models.py` scene table, CHECK
  `end_frame >= start_frame`, both `>= 0`).
- Validation at authority build (fail-closed): sorted by `start_frame`, first
  `start == 0`, `cur.start == prev.end + 1`, `last.end + 1 == frame_count`. Any
  overlap, gap, or coverage mismatch → typed denial (see §7). The partition covers
  **every source frame exactly once**.
- `manifest.shot_order` is the **manifest-selected order**: a list of the video's
  Scene ids (producer writes them in Scene.position order;
  `structural_lock_producer.py:351`). The timeline block is derived from the
  persisted Scene rows *in the manifest-selected order*; if that order is not a
  permutation of the current Scene ids or disagrees with canonical
  `(position, id)` order → typed denial. `shot_order` alone carries IDs, not frame
  bounds (`REVIEW.md` F04); the timeline block adds the bounds.
- Occurrence intervals are **layers inside that partition**: occurrences MAY
  overlap each other in time; they may span scene boundaries (an occurrence active
  across a cut is one identity whose chunks are split per shot, never merged across
  the cut). Coverage of "background-only" intervals: a scene range where no
  occurrence is active is still a shot; output frames there are the source frames
  verbatim (composition contributes nothing) — the interval is fully covered by the
  final artifact without inventing a character.
- The plan keeps the existing chunk-planner partition invariant: `scene_manifest.
  shots` fed to the planner is the timeline partition (one entry per scene shot,
  `{shot_id: <scene id>, start_frame, end_frame}`); the planner continues to reject
  overlap/gap/non-monotonic input — the bridge's job is to feed it the true
  partition, not to bypass its validation.

## 3. Layer identity and repeated roles

- **Layer identity is occurrence-scoped**: `layer_id` = the occurrence's
  `occurrence_segment_id` (never the role id). This is the exact fix for the F04
  `duplicate layer_id` collision; distinct occurrences of the same role stay
  distinct layers by construction.
- A role (`object_role_id`) may own **multiple occurrences with different ranges,
  regions, routes and visibility** (B03). Forbidden, by contract:
  - deduplicating occurrences by role (or by any role-level key);
  - a single global role rectangle shared by occurrences;
  - rendering every role into every shot (`Cartesian` over global role list × shots);
  - applying a layer outside its active interval.
- Chunk generation is per **(shot, active occurrence)** where "active" = the
  occurrence interval intersects the shot range. The chunked sub-range for that pair
  is the intersection `[max(seg.start, shot.start), min(seg.end, shot.end)]`;
  a pair with empty intersection produces **no chunks** in that shot
  (no inactive-layer application, no placeholders).
- The mapping entry for each occurrence carries:
  `layer_id = occurrence_segment_id`, `role_id = <object_role_id>`,
  `route`, `affected_region` (this occurrence's frozen region), `pack_version_id`
  (from the role mapping), `deps` (derived: previous chunk in same shot+layer; NO
  fabricated cross-layer deps for inactive layers). The chunk planner's per-layer
  identity and the worker's `_authoritative_mapping_by_layer`
  (`s10_full_apply_jobs.py:266–310`) both key on `layer_id`; with occurrence-scoped
  ids both work unchanged.
- Ordering: z-order / occlusion / contact evidence is preserved as frozen data.
  The producer already fingerprints `z_order` and `contacts`
  (`structural_lock_producer.py:766–841`, manifest `fingerprints`); occlusion rows
  (`scene_graph_occlusion`) order layers per frame via the existing renderer
  semantics (`_occluder_z_for_frame`, `_draw_occluders`;
  `composite.py:414–471,630–691`). The bridge MUST pass these through unchanged and
  MUST NOT invent ordering between two active occurrences of the same role when no
  authoritative occlusion/contact separates them — such ties use a deterministic
  documented rule (frozen at freeze time, Q5) recorded in the plan.
- Visibility (`occurrence_segment.visibility` ∈ `visible | occluded | out_of_frame |
  hidden`, `models.py:221`): composition and chunk generation treat `visible` and
  `occluded` as layers that must be rendered/composed; `out_of_frame` and `hidden`
  intervals are represented in the timeline for coverage accounting but do not
  contribute pixels (typed, recorded — never silently dropped and never rendered
  into frames; Q3). Removal-only roles (`source_overlay`,
  `REMOVAL_ONLY_KINDS`) are never replacement layers and stay excluded exactly as
  the producer excludes them (`structural_lock_producer.py:601–605`).

## 4. Geometry requirements

- The per-occurrence affected region is derived ONLY from persisted boxed evidence:
  `segmentation.boxes` or `prompt.boxes` (canonical `{x,y,w,h}` dicts or 4-element
  arrays), same extraction rule as `_segment_region_from_geometry`
  (`s10_full_apply.py:145–171` — first box, key precedence segmentation → prompt).
- **Points-only / missing / ambiguous geometry → typed ineligibility**
  (`OCCURRENCE_GEOMETRY_BOX_MISSING` / `OCCURRENCE_GEOMETRY_TAMPERED`; §7). Never
  invent a rectangle from points; never fabricate confidence (`confidence` /
  `confidence_source` stay exactly as persisted); never green-light via a readiness
  flag. This closes F04 observation 2 and is the shared eligibility agreement
  required by B04: **S09 executable eligibility and S10 compilation use the SAME
  boxed-region test**; a segment that fails it is recorded non-executable in
  `authority.eligibility.reasons` AND the S10 submit path denies with the same typed
  reason and zero S10 rows (no run/chunk/artifact/publication mutation).
- The region is validated at approval: 4 finite floats, `>=0`, normalized bounds
  (§1) — out-of-bounds/negative/non-finite → typed denial
  (`OCCURRENCE_REGION_OUT_OF_BOUNDS`, Q4).
- Ambiguity rules: zero boxes in both keys → missing (deny). More than one box in a
  key: current behavior picks the first; the bridge freezes **the selected box plus
  its provenance** (`geometry_source = "segmentation.boxes[0]"` / `"prompt.boxes[0]"`)
  into the timeline so no downstream re-guess occurs; whether multiple *differing*
  boxes should become a hard ambiguous-deny is an open freeze question (Q1).
- Contact/occlusion ordering is preserved unchanged (§3); background-only intervals
  are covered by verbatim source frames (§2).

## 5. Immutable authority block (the timeline block)

New **additive** sub-block inside `full_apply_authority` (inside the v2 snapshot
`snapshot_json`, therefore **inside `checkpoint_hash`** — verified: the checkpoint
content hash covers the whole snapshot, `s09_approval.py:1357–1380` with hash
recomputation from the stored row only, `:265–293`):

```
full_apply_authority.timeline = {
  "timeline_version": "s09.full-apply-timeline/v1",     # frozen name (Q6)
  "frame_count": <int>,                                  # == partition coverage
  "fps_num": <int>, "fps_den": <int>, "cfr": true,       # rational timing pins (§6)
  "start_time_ms": <int>,
  "shots": [ {"shot_id": <scene id>, "position": <int>,
              "start_frame": <int>, "end_frame": <int>} ... ],   # ordered partition
  "occurrences": [
    {"layer_id": <occurrence_segment_id>, "logical_id": ..., "lineage_version": ...,
     "role_id": <object_role_id>, "scene_id": ...,
     "start_frame": <int>, "end_frame": <int>,
     "visibility": "visible|occluded|out_of_frame|hidden", "z_order": <int>,
     "route": ..., "anchor": {"x": ..., "y": ...},
     "affected_region": [x,y,w,h],           # normalized (ruling v0.2)
     "raw_box": [...], "scale_mode": "normalized|pixel",   # ruling v0.2 §3
     "geometry_source": "<key>.boxes[0]", "pack_version_id": ...} ... ],
  "excluded": [ {"occurrence_segment_id": ..., "reason_code": ...} ... ],
  "source_pins": {"source_generation": ..., "source_artifact_id": ...,
                  "artifact_sha256": ..., "manifest_hash": ...},
  "order_source": "manifest|legacy_occurrence_ids|scene_position",
  "warnings": [...], "partition_valid": true|false
}
```

Implementation note (delivered): scene-partition problems are recorded as
`warnings` + `partition_valid=false` + a conservative non-executability reason
at approval time; consumption re-validates the stored block and fails closed
(`TIMELINE_COVERAGE_*`, zero S10 rows).  Hard integrity failures (unprovable
timebase, order conflicts, cross-scope scene ids, occurrence ranges outside
the source) deny the approval outright.

- **Built at S09 approval** (`submit_checkpoint_v2`) from: verified current-generation
  persisted `Scene` rows; the current-generation active `OccurrenceSegment` rows of
  the pinned manifest (`superseded_by_id IS NULL`, `source_generation ==
  manifest.source_generation`); the manifest-selected order; and persisted boxed
  evidence. Nothing comes from the client (the v2 path already rebuilds everything
  from persisted rows, `s09_approval.py:648–971`).
- **Consumers read ONLY the snapshot**: `full_apply_authority()` returns the stored
  block (read-only, hash-verified, `s09_approval.py:1052–1089`). After approval the
  bridge/S10 MUST NOT re-read live Scene/OccurrenceSegment rows to fill bounds,
  regions or intervals. The worker already re-derives the authority fingerprint from
  the persisted v2 row and fails closed on any drift (`s10_full_apply_jobs.py:
  189–204`) — the timeline block inherits that fence automatically.
- **Legacy classification** (no silent reinterpretation, bytes/hashes untouched):
  - v1 checkpoints → existing `REAPPROVAL_REQUIRED` failure
    (`s09_approval.py:1076–1082`) — unchanged.
  - v2 checkpoints **without** a `timeline` block (e.g. the existing points-only
    artifact) → conservatively classified `LEGACY_AUTHORITY_REAPPROVAL_REQUIRED`:
    public S09 reapproval creates a new v2 row carrying the timeline; the stored row
    is never mutated or backfilled.
  - Any stored v2 row whose `timeline` block fails validation → fail closed as
    corrupted storage (`S09ApprovalIntegrityError` semantics); never fall back to
    inventing bounds from live Scene rows.

## 6. Schema compatibility (authority → plan → worker)

- `s09.full-apply-authority/v1` stays the enclosing tag; `timeline` is additive.
  Existing top-level members are unchanged and remain populated for display/back-compat:
  `identity`, `source`, `structural_lock`, `shot_order`, `segments`, `role_mappings`,
  `eligibility{full_apply_executable, reasons, unsupported_routes}`.
- **Mapping manifest → plan** (exact field names the planner and worker already
  consume):

  | plan input | built from | notes |
  |---|---|---|
  | `approved_checkpoint` | run's `(checkpoint_id, checkpoint_hash, revision)` | unchanged |
  | `structural_lock_manifest` | `{manifest_hash, policy_version, source_generation, frame_count}` | frame_count must equal `timeline.frame_count` |
  | `scene_manifest.shots` | `timeline.shots` → `{shot_id, start_frame, end_frame}` | planner validation (§2) unchanged |
  | `mapping.mappings` | `timeline.occurrences` → `{layer_id, role_id, route, affected_region, pack_version_id, deps}` | occurrence-scoped `layer_id` (§3) |
  | `compatibility_policy` | `{policy_version}` | unchanged |

- Plan output schema is unchanged (`plan_id`/`plan_hash`/`inputs`/`chunks/
  {chunk_id, shot_id, layer_id, core_start_frame, core_end_frame, overlap_before,
  overlap_after, route, deps, content_hash_input}`, `s10_chunk_plan.py:442–480`).
  Chunk ids stay content-derived (`pinned_hash` + position identity, `:386–394`), so
  an equivalent reapproval reproduces byte-identical plans.
- **Timing pins**: `frame_count`, `fps_num`, `fps_den`, `cfr` are pinned ints/bool
  in the timeline. They must equal the verified source truth used by the producer
  manifest (`timebase` + `frame_count`, `structural_lock.py:160–327`). Validation:
  partition coverage == `timeline.frame_count`; manifest `frame_count` == timeline
  `frame_count`; `fps_num/fps_den > 0`; no float round-trip is authority.
  **D1 (dependency, B01)**: the producer's exact rational timing/count/CFR proof is
  being corrected in parallel (F03; `structural_lock_producer.py:845–866` currently
  applies `or 30` / `or 1` defaults). Until B01's verified interface lands, the
  bridge consumes the manifest `timebase` as-is and parses `fps_num/fps_den` exactly
  from `time_base` (current producer format `"{fps_den}/{fps_num}"`, line 867),
  cross-checking `fps == fps_num/fps_den`; if that exact parse or the count proof is
  unavailable → typed denial (`TIMELINE_TIME_BASE_UNAVAILABLE`) — never a default.
  The worker currently falls back to `fps_num=30, fps_den=1` when the run row lacks
  them (`s10_full_apply_jobs.py:553–570`): the bridge pins rational timing at
  submit/plan time so this fallback can never fabricate the final timebase.
- Submit-time flow stays as today (`s10_full_apply.py:431–588`): server-side
  authority → canonical planner inputs → optional client copies canonical-compared
  (never used) → deterministic plan → run + chunks; the only change is that
  `_canonical_planner_inputs` builds from `timeline` instead of 1:1 segments.

## 7. Fail-closed reason codes (typed; zero-mutation per branch)

Approval-time (`submit_checkpoint_v2` → `ApprovalConflictError`/`ApprovalValidationError`,
zero durable mutation):

| code | condition |
|---|---|
| `TIMELINE_SCENE_MISSING` | `shot_order` id is not a persisted Scene of the video / cross-scope |
| `TIMELINE_ORDER_MISMATCH` | `shot_order` not a permutation in canonical `(position,id)` order |
| `TIMELINE_COVERAGE_GAP` | partition gap or first shot != 0 |
| `TIMELINE_COVERAGE_OVERLAP` | scene shots overlap / non-monotonic |
| `TIMELINE_COVERAGE_FRAME_COUNT_MISMATCH` | `last.end+1 != frame_count` (or manifest frame_count differs) |
| `TIMELINE_OCCURRENCE_OUT_OF_RANGE` | occurrence range outside `[0, frame_count)` |
| `TIMELINE_SOURCE_GENERATION_MISMATCH` | occurrence generation != authority source generation |
| `TIMELINE_TIME_BASE_UNAVAILABLE` | rational fps/count not exactly provable (D1) |
| `TIMELINE_TIME_BASE_MISMATCH` | manifest timebase vs parsed rational / frame_count conflict |
| `OCCURRENCE_GEOMETRY_BOX_MISSING` | no box in segmentation/prompt evidence (points-only) |
| `OCCURRENCE_GEOMETRY_TAMPERED` | corrupt/non-finite stored geometry JSON |
| `OCCURRENCE_REGION_OUT_OF_BOUNDS` | region not finite / negative / `x+w>1` / `y+h>1` (Q4) |
| `OCCURRENCE_DUPLICATE_IDENTITY` | same occurrence id twice (tampered authority) |
| `OCCURRENCE_ROLE_UNMAPPED` | no role mapping / pack not published/ready for the occurrence role |
| `OCCURRENCE_ROUTE_NOT_EXECUTABLE` | route outside `{sprite_affine,pose_swap,controlled_redraw}` — no downgrade |

Submit/compile-time (S10 `FullApplyServiceError`, fail closed BEFORE run/enqueue,
zero S10 rows):

| code | condition |
|---|---|
| `TIMELINE_AUTHORITY_MISSING` | v2 authority without the timeline block |
| `LEGACY_AUTHORITY_REAPPROVAL_REQUIRED` | v1 checkpoint or pre-timeline v2 → public reapproval |
| `PLAN_INPUT_GEOMETRY_MISSING` | same boxed-region test fails at plan build (B04 agreement) |
| (existing planner codes reused) | `ChunkPlanError` texts surface unchanged, e.g. `shots overlap or non-monotonic`, `duplicate layer_id` — with the timeline feed these MUST be unreachable for valid authority (they only fire on tampered/invalid input) |

Worker-time (run marked `failed`, no publication, checkpoint not advanced):

| code | condition |
|---|---|
| `STITCH_LAYER_ARTIFACT_MISSING` | an active (visible/occluded) layer has no verified artifact for its range |
| `STITCH_LAYER_EVIDENCE_MISSING` | per-layer decoded-region evidence absent/ mismatched (B06) |
| `STITCH_FRAME_COVERAGE_MISMATCH` | composed frame_count != plan/timeline frame_count |
| `PLAN_PIN_MISMATCH` | recomputed plan_id/plan_hash != run row (existing check) |
| `AUTHORITY_FINGERPRINT_MISMATCH` | persisted-row fingerprint != manifest pin (existing check) |

Codes are stable strings; messages carry file/section references and concrete values
(counts, ids, frames) — no generic failures. All denials keep the project's
zero-mutation and evidence-retention rules.

## 8. Worker consumption (B06 — composition, not dedup)

Exact current defect: `_stitch_verified_chunks` (`s10_full_apply_jobs.py:421–489`)
merges verified chunk artifacts into one frame list using
`seen_ranges = {(shot_id, core_start, core_end)}` and `continue`s on repeats, so when
N layers share a core range only the FIRST layer's artifact is used and the others
are silently dropped (comment at `:28–29` even documents 100-not-200 frames as the
goal). Required contract behavior:

1. **Composition**: for every frame `f` in `[0, timeline.frame_count)`, the output
   frame = source frame `f` with **all active visible/occluded layers composited**
   (deterministic order per §3). Ranges with zero active layers emit the source
   frames verbatim (background-only coverage, §2).
2. **Reuse, don't reinvent**: composition reuses the existing compositing facilities
   (`composite_sprite_affine_frames` / `composite_pose_swap_frames` /
   `_draw_occluders` / `_alpha_composite_into` / `apply_alpha_mode`,
   `renderer_routes/composite.py`) through a bounded worker adapter inside
   `app/workflow/s10_full_apply_jobs.py`; the T02 per-role executor
   (`s10_multi_role_apply.execute_role_chunk`) remains the single-layer renderer it
   is today. Concretely: per (shot, active-occurrence) pair the worker already
   renders one layer's region into a full-frame canvas; composition applies the
   remaining active layers of the same range onto that canvas in order (sequential
   composition), never skipping a layer.
3. **Decoded-frame evidence per layer** (QA must be able to verify without eyeballing
   a video): every composed range records `per_layer_evidence` rows in the
   ``<stitched artifact>.evidence.json`` sidecar — the exact frozen definition is
   `R7_PREP.md §Q9` (QA, commit `d22d069`, NORMATIVE): one row per active
   (shot ∩ occurrence ∩ chunk run) unit carrying `shot_id`, `range`,
   `layer_id`, `role_id`, `route`, `visibility`, `z_order`, `artifact_sha256`,
   `artifact_size_bytes`, `region_norm`, `region_px`, `sampled_frames`,
   `region_crop_sha256_before`, `region_crop_sha256_after`, `final_crop_sha256`,
   `changed_pixel_count`, `changed_ratio`, `threshold` (0.01, frozen) and
   `verdict` (`contributed` iff `changed_ratio >= threshold` on at least one
   sampled frame, else `no_delta`).  Crop hashes = sha256 over the
   deterministically PNG-encoded RGB8 crop bytes (fixed encoder settings) of
   the crop at each sampled frame, concatenated in order.  Acceptance: every
   active unit row present with `verdict == "contributed"` (a `no_delta` row
   means the layer was dropped/not composited → `STITCH_LAYER_EVIDENCE_MISSING`,
   run failed, no publication); in an overlap fixture the co-active rows show
   distinct `artifact_sha256` and `before != after` (no-dedup proof).  QA
   verifies presence/format/coherence of these hashes, not recomputation.
4. **No fallback**: any missing layer artifact/evidence → run `failed`, no
   publication, no dedup fallback, no partial stitch. Zero-chunk runs stay
   fail-closed (existing behavior).
5. **Preserved output properties**: stitched frame_count == plan frame_count ==
   timeline.frame_count; rational fps preserved (`fps_num/fps_den` in metadata);
   source order/cuts/contact/occlusion semantics unchanged; original voice/audio
   policy unchanged (no new audio handling is introduced by the bridge; any
   pre-existing audio gap is reported, not "fixed" silently). Publication path
   unchanged (single completed publication; CAS semantics intact).
6. Resume/reuse semantics unchanged (`_chunk_artifact_usable` strict gate,
   `:924–996`); composition runs after all chunks are verified, before the
   pre-publication cancel fence — the cancel/CAS fences stay exactly where they are.

## 9. Open questions for the freeze meeting (Manager B + QA) — RESOLVED (see "Freeze outcome & amendments")

1. **Q1 — Multi-box ambiguity**: adopt `boxes[0]` + frozen `geometry_source`
   provenance (deterministic, preserves existing chains) or hard-deny when a key
   holds >1 differing box (`OCCURRENCE_GEOMETRY_AMBIGUOUS`)? Recommend: freeze
   selection with provenance; deny only on conflicting duplicates across keys.
2. **Q2 — Occurrence vs scene bounds**: may an occurrence range exceed or cross its
   `scene_id` scene bounds (B03 "multi-scene global vs local ranges")? Recommend:
   global frames authoritative; range outside `[0, frame_count)` denies; crossing
   scene bounds is accepted and chunked per shot (split at cuts). Needs QA confirm
   against the public-chain evidence shape.
3. **Q3 — `out_of_frame` / `hidden` occurrences**: confirm they produce no chunks
   and no pixels but stay represented in `timeline.occurrences` (with coverage
   accounting), and that B03's "all intended occurrences" means visible+occluded
   for render purposes.
4. **Q4 — Region validation**: confirm enforcing normalized `[0,1]` bounds at
   approval (deny `OCCURRENCE_REGION_OUT_OF_BOUNDS`). The captured planner fixtures
   used pixel-scaled values, which is planner-replay-only; real chains use
   normalized boxes (e.g. `{x:0.1,y:0.1,w:0.2,h:0.2}` in `new-producer-4/
   points-only.json`).
5. **Q5 — Repeated-role ties**: deterministic order for two active overlapping
   occurrences of the same role with no authoritative occlusion/contact between
   them — propose `z_order` asc, tie → `(logical_id, lineage_version)`, recorded in
   the plan; or typed ambiguity denial?
6. **Q6 — Naming/versioning**: freeze block name `timeline` vs `source_locked_timeline`
   and tag `s09.full-apply-timeline/v1`; freeze the `excluded[].reason_code`
   vocabulary (§7 subset).
7. **Q7 — Legacy v2 rows**: confirm pre-timeline v2 checkpoints (incl. the existing
   points-only artifact) require **public reapproval** (no backfill, bytes/hashes
   preserved) and that QA will accept a fresh reapproval chain as the B05 evidence.
8. **Q8 — B01 interface handoff (D1)**: confirm with B01 the exact corrected
   timing interface: fields for `fps_num`, `fps_den`, `frame_count`, CFR proof, and
   whether `timebase.time_base` keeps the `"{fps_den}/{fps_num}"` format. Until
   landed, BRIDGE implements the parse-and-validate path (§6) and blocks only the
   dependent branch.
9. **Q9 — B06 per-layer evidence format**: exact sidecar fields QA will accept as
   proof each layer contributed decoded pixels (region crop hashes vs source crop
   hashes; counts of changed pixels with threshold; per-range vs per-layer rows).
10. **Q10 — One-frame intersections**: with `overlap_frames=4`, a 1-frame
    (shot ∩ occurrence) intersection and shot-edge chunks: confirm `overlap_before
    := 0` when there is no previous chunk in that pair and `overlap_after := 0` at
    the pair's last chunk (no overlap bleeding across a cut or into an inactive
    interval).

## Freeze outcome & amendments (rulings applied)

Freeze partners' rulings (Manager B `BRIDGE_CONTRACT_FREEZE_REVIEW.md`; QA sign-off `R7_PREP.md` §Q1–Q9, commit `d22d069`) are the frozen basis. Resolutions:

- **Q1 multi-box**: adopted — 0 boxes → `OCCURRENCE_GEOMETRY_BOX_MISSING`; within-key differing boxes → `OCCURRENCE_GEOMETRY_AMBIGUOUS`; all equal → select + freeze `geometry_source`; cross-key precedence `segmentation.boxes → prompt.boxes` (rule, not guess).
- **Q2 global frames**: adopted (occurrence MAY cross scene bounds; chunked per shot, split at cuts; outside `[0,frame_count)` → `TIMELINE_OCCURRENCE_OUT_OF_RANGE`). Multi-scene fixtures seed GLOBAL ranges (provider scene-local quirk = S08 scope).
- **Q3 visibility**: adopted (visible + occluded render; `out_of_frame`/`hidden` represented in the timeline with no chunks/pixels).
- **Q4 REVISE** → amendment v0.2 below (dual-mode region derivation; `OCCURRENCE_REGION_SCALE_UNRESOLVED` added).
- **Q5 tie order**: adopted — `z_order` asc, tie → `(logical_id, lineage_version)`; the order keys are recorded on plan chunk rows when the mapping carries them.
- **Q6 naming**: `timeline` / `s09.full-apply-timeline/v1` frozen.
- **Q7 legacy**: adopted — pre-timeline v2 → `LEGACY_AUTHORITY_REAPPROVAL_REQUIRED`; v1 keeps `REAPPROVAL_REQUIRED`; stored bytes/hashes never touched.
- **Q8 D1**: parse-and-validate path implemented exactly (`time_base` `"{den}/{num}"` exact-int parse + `fps` cross-check; unprovable → `TIMELINE_TIME_BASE_UNAVAILABLE`). B01's enforcement-only fix keeps the format — the path stays valid; only a future producer change dropping the parseable fields would block the dependent branch.
- **Q9**: normative text cited in §8.3 (frozen format).
- **Q10**: adopted — `overlap_before := 0` at the pair-first chunk, `overlap_after := 0` at the pair-last chunk (no bleed across cuts/inactive ranges).

### Amendment v0.2 (Q4) — delivered derivation

Dual-mode per `BRIDGE_RULING_Q4_region_scale_v0.2.md` §2 (Mode A normalized; Mode B pixel ÷ persisted dims), with ONE documented hardening **flagged to Manager B/Codex**: the ruling's Mode-B containment bounds (`x+w <= src_w`, `y+h <= src_h`) reject the SANCTIONED chain's own padded boxes (observed on 640×360: `{100,100,300,300}` → y+h=400; `{400,100,250,250}` → x+w=650). Delivered behavior: Mode B requires the box to INTERSECT the frame (`x < src_w`, `y < src_h`; `w,h > 0`) and clips the derived normalized region to the physical frame (`x2=min(x+w, src_w)`, `y2=min(y+h, src_h)`); a box fully outside the frame → `OCCURRENCE_REGION_OUT_OF_BOUNDS`; pixel-scale with dims unavailable → `OCCURRENCE_REGION_SCALE_UNRESOLVED`. Pixels outside the frame do not exist; the rule is deterministic and evidence-derived (no guessing). The timeline records `raw_box` + `scale_mode` + `affected_region` (normalized) + `geometry_source` per occurrence (v0.2 §3).

## Lane inventory (D2 node IDs — frozen by this owner, delivered)

`tests/s12/s12-public-authority-bridge/` — the D2 table names implemented verbatim (27 nodes; the dispatch prompt's "23" summary is an arithmetic miscount — all listed names are delivered, nothing dropped):

| Acceptance | File | Node IDs |
|---|---|---|
| B03 | `test_b03_partition_layers.py` | `test_b03_cooccurring_graph_all_occurrences_active_layers` · `test_b03_partition_covers_every_frame_once` · `test_b03_two_visible_characters_plus_object_overlap` · `test_b03_repeated_role_distinct_routes_regions_ranges` · `test_b03_background_only_interval_source_verbatim` · `test_b03_one_frame_boundary_case` · `test_b03_multiscene_global_vs_local_ranges` · `test_b03_no_cartesian_inactive_layer_application` |
| B04 | `test_b04_eligibility.py` | `test_b04_points_only_ineligible_same_reason_and_zero_s10_rows` · `test_b04_missing_and_ambiguous_geometry_ineligible` · `test_b04_within_key_differing_boxes_ambiguous_deny` · `test_b04_unsupported_route_ineligible_no_unintended_rows` · `test_b04_valid_boxed_authority_proceeds` · `test_b04_no_guessed_rectangle_no_readiness_bypass` |
| B05 | `test_b05_authority_freeze.py` | `test_b05_timeline_block_inside_checkpoint_hash` · `test_b05_live_scene_mutations_after_approval_frozen` · `test_b05_stale_source_requires_reapproval` · `test_b05_legacy_v2_pre_timeline_public_reapproval_bytes_preserved` · `test_b05_legacy_v1_reapproval_required_unchanged` · `test_b05_corrupted_timeline_fails_closed_no_live_fallback` |
| B06 | `test_b06_composition.py` | `test_b06_stitch_composes_all_visible_layers_overlap` · `test_b06_per_layer_decoded_evidence_contribution_frozen_format` · `test_b06_no_dedup_first_layer_only_distinct_artifacts` · `test_b06_occluded_layer_composed_before_occluder` · `test_b06_missing_artifact_or_evidence_fails_closed_no_publication` · `test_b06_frame_count_rational_fps_preserved_no_double_timeline` · `test_b06_voice_policy_unchanged_and_audio_gap_reported` |

## Dependencies, scope, non-goals

- **D1**: B01 corrected producer timing interface (Q8) — BRIDGE depends on it for the
  exact rational timing proof; until it lands, the parse-and-validate path is used and
  only the dependent branch is blocked (never guessed).
- **D2**: QA co-freezes exact B03–B06 node names/expected outputs from this contract
  before production dispatch.
- **D3**: INT transport is transport-only (`SHARED_CONTRACT.md`); this task never
  touches the canonical integration branch.
- **Allowed writes (after freeze)**: `app/services/s09_approval.py`,
  `app/services/s10_full_apply.py`, `app/services/s10_chunk_plan.py`,
  `app/workflow/s10_full_apply_jobs.py`, optional NEW
  `app/services/source_locked_timeline.py`, NEW
  `tests/s12/s12-public-authority-bridge/**`, own
  `docs/pm/sessions/S12-PUBLIC-AUTHORITY-BRIDGE/**`. Existing files are PATCH-ONLY
  with preimage/postimage hashes. Anything else → exact minimal proposal, not a
  silent edit.
- **Non-goals**: no rewrite of S10/S09 semantics beyond this bridge; no producer or
  schema/model/migration changes; no UI changes; no AI regeneration of animation;
  no change to public API surface beyond what the frozen timeline requires; no
  push/release (local transport commits only).

## Change log

- v0.1 (2026-09-16, session `20260916_105450_f38ead`) — initial draft after full
  grounding read of the 5 service files, R7 review artifacts, RULES, SHARED_CONTRACT,
  ACCEPTANCE_R7, REVIEW F04. Two reviewer raw artifacts (planner-1) and one producer
  raw artifact (new-producer-4 points-only) cross-checked against the code paths.
- v0.2 (2026-09-16, same session) — freeze outcomes applied: Manager B rulings
  (Q1 revised, Q2–Q10), QA sign-off `d22d069` (§Q9 cited normatively in §8.3),
  Q4 ruling amendment (dual-mode derivation + frame-intersection hardening
  flagged), final timeline-block field list, D2 lane inventory (27 nodes).

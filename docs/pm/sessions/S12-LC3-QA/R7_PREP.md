# S12-LC3-QA — R7 prep record (Q01 corrections, Q02 migration compat, Q03 R5 env)

Turn: R7 PREP + COMPATIBILITY, Hermes owner session `20260915_201612_aeb5e3`, route `ocg/deepseek-v4.1-flash` / provider custom / fallback OFF / native thinking ON. Wave-base worktree HEAD at start: `35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86` (branch `codex/s12-lc3-luna-qa`, clean). Public product chain NOT run this turn (dependencies: BRIDGE/B01 corrections not landed; B01-I stays blocked).

## Q03 — R5 audit environment: exact values and invocation

The R5 packet test reads the audited integration checkout via two environment variables and never weakens them (no skip, no `None` fallback — the assertions at `tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py:52-82` stay byte-intact: root must exist, HEAD must equal the expected SHA, branch must be `codex/s12-lc3-luna-integration`, tree must be clean).

**Exact values for the R7 wave-base (frozen tip current at this turn):**

```
S12_R5_CANDIDATE_ROOT=C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration
S12_R5_EXPECTED_CANDIDATE_SHA=35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86
```

**Exact invocation (run from the QA worktree; no other change needed):**

```
export S12_R5_CANDIDATE_ROOT="C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration"
export S12_R5_EXPECTED_CANDIDATE_SHA="35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86"
C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests/s12/s12-lc3-qa-r5/ -q -p no:cacheprovider
```

**How to verify the values before a gate (all read-only):**

```
git -C C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration rev-parse HEAD      # must print the expected SHA
git -C C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration branch --show-current # must print codex/s12-lc3-luna-integration
git -C C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration status --porcelain   # must print nothing
```

When the integration owner transports a new verified wave (VAL/RETRY/B01/BRIDGE/QA), the expected SHA changes with the new frozen tip; Manager must re-read HEAD and export the two variables with the new value at gate time. The value recorded above is the wave-base record, not a permanent constant.

Evidence: `r5-env.stdout.txt` / `r5-env.stderr.txt` (this evidence dir) — full module `3 passed in 2.14s`, exit 0, including `test_r5_probe_inventory_is_static_and_exactly_mapped` with the env above. Baseline (env absent, before this turn): exit 1, `S12_R5_CANDIDATE_ROOT must identify the audited integration checkout` — recorded in `baseline-r5.stdout.txt`.

## Q02 — T03A migration test compatibility (bounded exception)

`tests/s12/s12-t03a/test_s12_export_migration.py` was written for revision `c3d4e5f6a7b8`; the current sole head is `d4e5f6a7b8c9` (additive retry-lineage + durable Job binding on top). The correction separates the two revisions explicitly and never replaces `NEW_REV` blindly:

- `TARGET_REV = "c3d4e5f6a7b8"` (revision the suite was written for; creates the three S12 export tables) and `CURRENT_HEAD = "d4e5f6a7b8c9"` (current sole head) are distinct constants; `NEW_REV` is gone.
- Both linear edges are asserted individually (`PARENT_REV -> TARGET_REV`, `TARGET_REV -> CURRENT_HEAD`) plus a linear walk from head to parent (no branch).
- Fresh upgrade, retained-data upgrade to head, and the lineage backfill (seed at `TARGET_REV`, upgrade to head: `lineage_id` from `natural_key`, unambiguous `job_id` binding, FK check clean) are all executed on real migrated temp DBs.
- Nonempty-downgrade refusal retained: exact current-head guard message asserted, head/rows unchanged; the export-domain guard text is proven retained in isolation; empty downgrade unwinds the lineage block at `TARGET_REV` (original six-field identity unique constraint restored) and then drops exactly the three tables back to `PARENT_REV`.
- No migration, model or schema file was touched; no xfail/skip; no assertion weakened (coverage was added).

Delivered node IDs (full module, all executed): `test_single_head_is_current_head`, `test_history_links_both_linear_edges`, `test_history_walk_from_head_is_linear_to_parent`, `test_fresh_upgrade_creates_tables`, `test_upgrade_from_parent_retains_data_to_current_head`, `test_upgrade_to_head_backfills_lineage_from_seeded_run`, `test_downgrade_with_rows_refuses_at_current_head`, `test_export_domain_guard_text_is_retained`, `test_empty_downgrade_unwinds_lineage_then_tables`.

Evidence: `t03a-fixed-v1.stdout.txt` / `t03a-fixed-v1.stderr.txt` — 9 passed in 9.49s, exit 0. Baseline (before): `baseline-t03a.stdout.txt` — 4 failed, 2 passed (four inherited stale-head failures).

## Q01 — corrected evidence claims

Corrected in QA-owned docs this turn (bounded patches; old text retained as provenance where it is historical):

1. The B01-I public chain stops at `s10_full_apply_submit` (HTTP 422 shots-overlap). S12 preflight is **NOT_REACHED / NOT_REEXECUTED**: the chain harness calls it only after a successful S10; no `s12_preflight` stage exists in `b01i-stages.jsonl`. (Reviewer F05.)
2. “Missing producer / B01 BLOCKED_DEPENDENCY” is obsolete: the public StructuralLock producer exists and is mounted (reviewer P07 disposition: `PRODUCER_PRESENT_WITH_OPEN_F03`); the open producer item is F03 timing defaults, owned by S09-LOCK-PRODUCER-B01.
3. “Single residual / only S10 overlap” is obsolete: open families per independent review are F01 (lease serialization), F02 (identity/encoding), F03 (invented timing), F04 (S09-executable vs S10 planning incl. co-occurring segments + points-only geometry + same-role disjoint ranges), F05 (C02 evidence claim).
4. Honest labels retained: fresh/inherited/not-run; setup failures and inherited broad failures kept as-is; deterministic-extraction / synthetic-media labels kept; human playback NOT_REVIEWED; no product/UI/video/audio pass claimed.

## Freeze inventory R7

See `R6_INVENTORY.md` section “R7 additions — freeze for writers”: original 62 + R6 rows unchanged; R7 rows (A01–A06 references, B01–B06, Q01–Q04, P01–P03) with owner, source location, required outcome and raw destination. Nodes that do not exist yet are explicitly marked “to be frozen by owner” (no invented node names); Q01–Q03 records this turn's executed/delivered state.

---

# BRIDGE contract freeze sign-off — QA co-freeze (2026-09-16)

Frozen basis reviewed: `S12-PUBLIC-AUTHORITY-BRIDGE/CONTRACT.md` v0.1 commit `3963d31` — bytes re-hashed this turn by QA: sha256 `B90B48007717EEF6B2F0027C5BFAE8AD3938A96ECA4CB743CEB8837F23743AAA`, 28,740 bytes (matches the BRIDGE session record). Manager B rulings reviewed: `B/manager/BRIDGE_CONTRACT_FREEZE_REVIEW.md`. QA evidence base: public chain runs `20260915T163219Z` (8 segments, multi-scene attempt) and `20260915T164349Z` (final single-scene run, 2 segments) + persisted DB rows + wave-base code.

## Verdicts per question (QA)

### Q1 — multi-box / cross-key — CONFIRMED (ruling adopted), no escalation

Real public-chain data shows NO multi-box cases and NO cross-key conflicts: across both runs, 10/10 segments have exactly one box per key AND `segmentation.boxes == prompt.boxes` byte-identically (`multi_box: 0`, `cross_key_differing: 0`). Concrete rows: segment `29963538-7ff4-5bb8-9212-aea7fc70c26d` → both keys `{"boxes":[{"x":400.0,"y":100.0,"w":250.0,"h":250.0}], ...}`, segment `627b554b-4bbb-55b6-8600-65df9edd3de4` → both keys `{"x":100.0,"y":100.0,"w":300.0,"h":300.0}`. The ruling (within-key differing boxes → `OCCURRENCE_GEOMETRY_AMBIGUOUS`; cross-key precedence `segmentation → prompt` retained with frozen `geometry_source`) is adopted; QA sees no real-data cross-key conflict.

### Q2 — occurrence vs scene bounds — CONFIRMED, with one test-only adapter note

Global source frames authoritative, occurrence MAY cross scene bounds and is chunked per shot, range outside `[0, frame_count)` → `TIMELINE_OCCURRENCE_OUT_OF_RANGE`: CONFIRMED. Real evidence: the final run's segments are canonical `[0,119]` global with `frame_count=120`; the single scene is `[0,119]`. Test-only note (not a contract defect): the sanctioned deterministic extraction provider persists **scene-local** frame ranges for scenes after the first (run `20260916T163219Z`: segment for scene `[60,119]` persisted as `[0,59]`), so BRIDGE multi-scene fixtures must seed GLOBAL ranges (or fix that test-only adapter under S08 scope); contract semantics are unaffected because authority is rebuilt from persisted rows + the timeline validation enforces the global convention.

### Q3 — out_of_frame / hidden — CONFIRMED

No chunks, no pixels, represented in `timeline.occurrences` with coverage accounting; B03 “all intended occurrences” = visible + occluded for render purposes: CONFIRMED. Evidence: both real-chain segments persisted `visibility='visible'` (z_order 0/1); the enum and exclusion rules are per `models.py` occurrence CHECKs + contract §3; no counter-evidence in QA data.

### Q7 — legacy v2 pre-timeline — CONFIRMED (B05 acceptance defined)

Stored bytes/hashes never touched; pre-timeline v2 (incl. the points-only artifact) classifies `LEGACY_AUTHORITY_REAPPROVAL_REQUIRED`; v1 keeps `REAPPROVAL_REQUIRED`: CONFIRMED. QA acceptance for B05: QA accepts a **fresh public reapproval chain** as the evidence — demonstrated feasible on the real chain already (public `POST /api/v2/s09-approvals/reapprove` returned 201 and created a new v2 checkpoint `83bccabe-dd4d-4b6c-b168-2d4c66a6f1a9` without mutating the prior row). The bridge-era check will be: old row byte-identical after reapproval (hash compare) + new row carries the timeline block.

### Q4 — region bounds — **REVISE (QA-F1 finding; decision required before production)**

Manager B's Q4 premise (“planner fixtures with pixel-scale were reviewer in-memory adaptations only; real chains use normalized boxes”) does not hold for the sanctioned public chain. Real persisted evidence (run `20260915T164349Z`, source 640x360): segments persist **pixel-scale** boxes — `{"x":100.0,"y":100.0,"w":300.0,"h":300.0}` and `{"x":400.0,"y":100.0,"w":250.0,"h":250.0}` in BOTH keys. Code path: `_segment_region_from_geometry` (`app/services/s10_full_apply.py:145–171`) returns those raw floats as the region with no normalization, while the renderer maps regions as normalized (`_region_px` multiplies by `w,h`, `app/services/renderer_routes/composite.py:299–306`) and contract §1/Q4 assume normalized `[0,1]`. Consequences if enforced naively: `OCCURRENCE_REGION_OUT_OF_BOUNDS` (x+w=400 > 1) would deny the entire sanctioned extraction world (B03/B04 fixtures + P01 chain), and any region that gets past bounds would map to a clamped degenerate crop. Options (decision owner: Manager B/Codex; QA recommends #2): (1) treat persisted boxes as normalized and fix the deterministic provider to emit normalized boxes (test-only S08 change; changes fixture SHAs); (2) declare normalized `[0,1]` the canonical persisted convention AND normalize at region derivation using source dims (`region = [x/src_w, y/src_h, w/src_w, h/src_h]`, deny when source dims unavailable — no guessing), keeping the provider as-is for now with an explicit recorded adapter note; (3) keep raw boxes as region and drop bounds enforcement (rejected: contradicts B04 honesty). Until decided, B03/B04 boundary fixtures must use the decided convention, and the bridge must NOT ship plain bounds-deny over raw persisted values.

### Q9 — B06 per-layer decoded evidence — **FROZEN by QA (this document is the normative definition)**

Feasibility grounded in real code: the stitched artifact already gets an atomic sidecar via `_write_evidence_sidecar` (`app/workflow/s10_full_apply_jobs.py:1155–1173`, staging + `os.replace`), and composition is in-process (decoded frames available), so per-layer region-pixel proofs are producible. **Frozen format v1** — sidecar path `<stitched artifact>.evidence.json`, JSON object sorted keys, containing the existing top-level fields (`decoded_sha256`, `decoded_frame_count`, `fps_num`, `fps_den`, `layer_id: null`, `shot_id: null`, `route: "stitch"`, `effective_adapter: "stitch"`, `artifact_sha256`, `artifact_size_bytes`) PLUS `per_layer_evidence: [...]` with exactly one row per active `(shot ∩ occurrence)` pair whose visibility is `visible` or `occluded`. Each row carries ALL of:

| field | definition |
|---|---|
| `shot_id` | scene id of the shot this range belongs to |
| `range` | `[core_start_frame, core_end_frame]` inclusive, of the pair intersection chunk run |
| `layer_id` | occurrence segment id (`occurrence_segment_id`) |
| `role_id` | `object_role_id` |
| `route` | `sprite_affine` / `pose_swap` / `controlled_redraw` |
| `visibility` | `visible` / `occluded` |
| `z_order` | frozen z_order used for ordering |
| `artifact_sha256`, `artifact_size_bytes` | the verified layer chunk artifact used for this range |
| `region_norm` | `[x,y,w,h]` frozen authority region |
| `region_px` | `[x0,y0,x1,y1]` integer crop from the exact `_region_px` mapping against source dims `(w,h)` |
| `sampled_frames` | `[range_start]` or `[range_start, range_end]` (dedup when equal) |
| `region_crop_sha256_before` | sha256 of the composed-canvas crop at `region_px` decoded at each sampled frame, IMMEDIATELY BEFORE this layer's composition step |
| `region_crop_sha256_after` | same crop IMMEDIATELY AFTER this layer's composition step (pre-occluder snapshot) |
| `final_crop_sha256` | same crop in the FINAL composed output (after all layers) |
| `changed_pixel_count` | pixels differing (any channel abs diff > 0) between before/after crops, summed over sampled frames |
| `changed_ratio` | `changed_pixel_count / ((x1-x0)*(y1-y0) * len(sampled_frames))` |
| `threshold` | `0.01` (frozen QA acceptance value) |
| `verdict` | `contributed` iff `changed_ratio >= threshold` on at least one sampled frame; otherwise `no_delta` |

QA acceptance rules (B06): every active visible/occluded pair has exactly one row (missing row or missing field → `STITCH_LAYER_EVIDENCE_MISSING`, run failed, no publication); every row `verdict == "contributed"` (a `no_delta` row means the layer was dropped/not composited → fail); in an overlap fixture with two co-active layers, the two rows must show **distinct** `artifact_sha256` values and each `region_crop_sha256_before != region_crop_sha256_after` — this is the no-dedup-to-first-layer proof; the whole artifact stays bound by `decoded_sha256` + `decoded_frame_count == plan frame_count == timeline.frame_count`. Crop hashing method (frozen for the producer side): sha256 over the deterministically PNG-encoded crop bytes (fixed encoder settings, RGB8) written into the sidecar as hex — QA verifies presence/format/coherence, not recomputation (decoder equivalence is not asserted). Occluded layers are proved by their own before/after delta at their composition step (they are composed, then legally overpainted by later layers; `final_crop_sha256` documents the overpaint result).

Contract action for the owner (QA is not in that write-set): replace §8.3's “or an equivalent per-layer region-pixel proof frozen at Q9” with a reference to this definition (persist the table verbatim or cite `docs/pm/sessions/S12-LC3-QA/R7_PREP.md` §Q9). No other §8 change requested.

### Q5 / Q6 / Q10 — no QA objection (no counter-evidence; acceptance rows unaffected)

## D2 — BRIDGE test node mapping (proposed; to be frozen by BRIDGE owner per this mapping)

Owner creates `tests/s12/s12-public-authority-bridge/**`; names below are QA's proposed exact node IDs mapped to acceptance rows — the BRIDGE owner records them in its lane inventory before its checkpoint lands (no invented names in the frozen inventory until then):

| Acceptance | Proposed node IDs |
|---|---|
| B03 | `test_b03_cooccurring_graph_all_occurrences_active_layers` · `test_b03_partition_covers_every_frame_once` · `test_b03_two_visible_characters_plus_object_overlap` · `test_b03_repeated_role_distinct_routes_regions_ranges` · `test_b03_background_only_interval_source_verbatim` · `test_b03_one_frame_boundary_case` · `test_b03_multiscene_global_vs_local_ranges` · `test_b03_no_cartesian_inactive_layer_application` |
| B04 | `test_b04_points_only_ineligible_same_reason_and_zero_s10_rows` · `test_b04_missing_and_ambiguous_geometry_ineligible` · `test_b04_within_key_differing_boxes_ambiguous_deny` · `test_b04_unsupported_route_ineligible_no_unintended_rows` · `test_b04_valid_boxed_authority_proceeds` · `test_b04_no_guessed_rectangle_no_readiness_bypass` |
| B05 | `test_b05_timeline_block_inside_checkpoint_hash` · `test_b05_live_scene_mutations_after_approval_frozen` · `test_b05_stale_source_requires_reapproval` · `test_b05_legacy_v2_pre_timeline_public_reapproval_bytes_preserved` · `test_b05_legacy_v1_reapproval_required_unchanged` · `test_b05_corrupted_timeline_fails_closed_no_live_fallback` |
| B06 | `test_b06_stitch_composes_all_visible_layers_overlap` · `test_b06_per_layer_decoded_evidence_contribution_frozen_format` · `test_b06_no_dedup_first_layer_only_distinct_artifacts` · `test_b06_occluded_layer_composed_before_occluder` · `test_b06_missing_artifact_or_evidence_fails_closed_no_publication` · `test_b06_frame_count_rational_fps_preserved_no_double_timeline` · `test_b06_voice_policy_unchanged_and_audio_gap_reported` |

Freeze state after this sign-off: QA sign-off delivered (Q1/Q2/Q3/Q7 CONFIRMED; Q9 frozen; D2 mapping proposed; Q4 REVISE finding QA-F1 blocks plain bounds-enforcement decisions until Manager B/Codex rules). Production dispatch remains Manager B's call; the Q4 convention decision and B01 D1 interface are the two open prerequisites QA can see.

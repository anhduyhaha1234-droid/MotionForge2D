# S10-T01B — REPORT — Deterministic shot/layer chunk planner

- Task: S10-T01B — Deterministic shot/layer chunk planner
- Status: TASK_SUBMITTED
- Model: meta — reasoning max — fallback OFF — TTFB 900
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration — branch codex/s08-integration — HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79)
- MAIN read-only: C:/Users/Admin/MotionForge2D
- Preflight: MOTIONFORGE_DATABASE_URL UNSET, no persistence/migration touched, forbidden paths untouched
- Date: 2026-08-27 23:59 +07

## Outcome
Pure deterministic planner generates stable full-video work graph from approved checkpoint/scene/mapping contracts.
Worker remains inside exclusive write scope; manager will verify at J1 join gate.

## Files changed (exclusive write scope only)
- app/services/s10_chunk_plan.py (new, 481 lines) — pure function plan_full_apply(...), no DB/IO/time/process/path, canonical JSON sort_keys, deterministic IDs, fail-closed validation
- tests/test_s10_chunk_plan.py (new, 26 tests) — full 6-bullet coverage
- docs/pm/sessions/S10-T01B-chunk-planner/TASK.md (new)
- docs/pm/sessions/S10-T01B-chunk-planner/LOG.md (new)
- docs/pm/sessions/S10-T01B-chunk-planner/REPORT.md (this file)
- output/s10/t01b/pytest-run-1.log, pytest-run-2.log, ruff.log, mypy.log (isolated evidence)

## Implementation summary
- `plan_full_apply(approved_checkpoint, structural_lock_manifest, scene_manifest, mapping, compatibility_policy, *, chunk_frames, overlap_frames, chunk_config, **_ambient)`
  - Filters to pinned keys only; ambient **_ambient ignored (path/time/process never affect hash)
  - Checkpoint: checkpoint_id (non-empty str), checkpoint_hash (64 hex), revision >=1, optional source_generation strings
  - Manifest: manifest_hash (64 hex), policy_version (non-empty str), source_generation, frame_count >=1, optional fps
  - Scene: shots/scenes list sorted by start_frame; enforce start 0, contiguous (prev.end+1 == cur.start), non-overlapping, frame_count matches
  - Mapping: layer_id/role_id, route in {pose_swap,sprite_affine,mesh_warp,part_rig,controlled_redraw}, deps sorted; layer_id dedup, deterministic sort by layer_id
  - Policy: policy_version normalized, optional thresholds; chunk_config {chunk_frames >=1, overlap_frames < chunk_frames}
  - Chunks: per shot per layer, core split by chunk_frames, overlap_before/after as context-only metadata, chunk_id = ck_<sha16 of pinned_hash+position>, deps = sorted(base_deps + prev chunk in same shot/layer + same-index chunk in prev layer), content_hash_input = sha256 of pinned+core+route+deps
  - Plan body {chunks, inputs, version:1} canonical JSON hashed to plan_id/plan_hash; chunks sorted by shot_order/layer_order/core_start

## Binary acceptance evidence
1. Byte-identical canonical plan/hash/IDs twice:
   - Two sequential calls with same canonical inputs produce identical plan_id, plan_hash, chunk_ids, content_hash_inputs and byte-identical sorted JSON. Shuffled input order (shots/mappings) still yields same deterministic output thanks to sorting. Verified in test_deterministic_byte_identical_twice + test_deterministic_shuffled_input_still_same.
2. Every source frame covered exactly once as core; overlap is explicit context only:
   - Per-layer chunks cover [0, frame_count-1] gap-free with no core overlap; total_core == frame_count; overlap_before/after are metadata only, first chunk overlap_before==0, last overlap_after==0. Tests: test_every_frame_covered_exactly_once, test_overlap_frames_are_context_only_not_duplicated.
3. No gap/cut drift/off-by-one including 1-frame shots and final partial chunk:
   - Shot boundaries respected: first chunk starts at shot start, last ends at shot end, cursor advances by exactly 1 across chunks. 1-frame shots produce single chunk with zero overlap. Final partial chunk (e.g., 25 frames / chunk 10 -> 0-9,10-19,20-24) correct with overlap only interior. Tests: test_no_gap_cut_drift_across_shots, test_single_frame_shot, test_final_partial_chunk, test_many_small_shots_no_drift.
4. Layer/role routes and structural dependencies pinned per chunk:
   - Each chunk carries pinned route from its layer mapping; deps include base layer deps + sequential previous chunk + cross-layer same-index dep, all sorted deterministic. Tests: test_layer_routes_pinned_per_chunk, test_structural_deps_pinned, test_deps_sorted_deterministic.
5. Changing one pinned input changes plan identity; ambient path/time/process does not:
   - Changing checkpoint_hash, manifest_hash, policy_version, scene boundaries, route, chunk_frames or overlap_frames each yields a different plan_id. Adding ambient keys (ambient_path, timestamp, pid, extra kwargs) leaves plan_id/chunk_ids/content_hash_inputs unchanged. Tests: test_changing_pinned_input_changes_plan_id, test_ambient_inputs_do_not_change_identity.
6. Malformed/non-monotonic/overlapping fails closed:
   - Raises ChunkPlanError on empty shots, overlapping shots, gaps, not starting at 0, end<start, frame_count mismatch, missing/invalid checkpoint/manifest, invalid route, duplicate layer_id, overlap >= chunk, non-dict inputs. Tests: 9 dedicated fail-closed tests.

## Validation gates (this worker, isolated)
- Ruff scoped (write-set only): All checks passed
- mypy --strict app/services/s10_chunk_plan.py: Success no issues
- pytest run1: basetemp /tmp/tmp.vv8GKn2yKu — 26 passed
- pytest run2: basetemp /tmp/tmp.mXfvfV6sho — 26 passed (evidence in output/s10/t01b/pytest-run-{1,2}.log)
- Forbidden check: git status only touches allowed files; no app/persistence, migration, app/api, frontend, renderer J1, S11/S13, data/**, channels.json
- Purity check: grep for time/os/pathlib/sqlite/open in s10_chunk_plan.py returns zero; hash only from pinned canonical JSON (hashlib sha256)

## Risks / next
- No DB/IO — J1 join gate should verify T01A + T01B both green and that T01C can consume this planner deterministically.
- Manager to re-run pytest x2 with its own basetemp and audit diff/allowlist before MANAGER_VERIFIED.

## Terminal
STATUS: TASK_SUBMITTED — worker stopped, awaiting Manager join gate J1 and Codex review. No APPROVED/CLOSED self-claim, no commit/push.

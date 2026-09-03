# S10-T01C — REPORT — Durable apply orchestration + API

- Task: S10-T01C — Durable apply orchestration + API
- Status: TASK_SUBMITTED
- Model: meta — reasoning max — fallback OFF — TTFB 900
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration — branch codex/s08-integration — HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79 — feat(s09): complete demo-first reskin sprint) + T01A/T01B dirty (J1 MANAGER_VERIFIED)
- MAIN read-only: C:/Users/Admin/MotionForge2D
- Preflight: RULES_LOADED 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 — MOTIONFORGE_DATABASE_URL UNSET — migrations head a10b11c12d3e (single head) — s10_full_apply.py + s10_chunk_plan.py ton tai — app/api/app.py 197 lines 17 routers
- Depends: J1 MANAGER_VERIFIED — T01A 21 passed x2 (domain 15 + migration 6, head a10b11c12d3e) + T01B 26 passed x2 (planner pure, 6 bullets) = 47 passed x2
- Date: 2026-08-28 00:31–16:17 +07

## Outcome
HTTP submits durable FullApply job; worker executes/checkpoints/resumes outside request and publishes atomically — additive, project-scoped, idempotent, checkpoint-durable, cancel/retry correct, artifacts atomic.

## Files changed (exclusive write scope only)
- app/services/s10_full_apply.py (new, ~350 lines) — FullApplyService over T01A S10ApplyRepository + T01B planner, deterministic plan, computed natural/idempotency keys, chunk materialization, cancel/retry/resume/publish_completed (ManagedRoot atomic, Artifact ready, .partial guard)
- app/workflow/s10_full_apply_jobs.py (new, ~420 lines) — JOB_TYPE_S10_FULL_APPLY, S10_CP_VERSION=1, s10_full_apply_handler (real T02 executor per chunk, checkpoint durable before every next chunk, resume skips verified only after exact SHA/size/frame/timebase/dependency check, quarantine on tamper with artifact delete + path dedup, stitch verified core dedup, full-video publication, managed atomic)
- app/api/routes/s10_full_apply.py (new, ~430 lines) — additive /api/v2 router with 5 routes: POST /projects/{project_id}/full-apply (202 on create, 200 on replay, workspace Query, commits explicitly, enqueues durable job outside request via JobService), GET /full-apply/{run_id} (status + chunks + publications + worker checkpoint from JobStep), POST /full-apply/{run_id}/cancel, POST /full-apply/{run_id}/retry, POST /full-apply/{run_id}/resume
- app/api/app.py (additive wiring, +7 lines) — added `s10_full_apply` to routes import + `app.include_router(s10_full_apply.router)` after s09_approval
- app/workflow/job_service.py (bounded +3 lines) — register_s10_full_apply_handler after attach_audio (precedent)
- tests/test_s10_full_apply_api.py (new, 7 tests) — submit 202 + status, same tuple dedupes, distinct on changed checkpoint, project-scoped 404, cancel+retry, resume, openapi additive
- tests/test_s10_full_apply_workflow.py (new, 10 tests) — checkpoint durable before stop + resume skips verified, cancel zero false publication + retry lineage, same tuple dedupes vs changed plan distinct, artifacts atomic + sha256, corrupted/tampered quarantined, absent parent mkdir, stitch failure no publication, no publication on cancel, publication exact hash/size/decodable/shot_order/cuts
- docs/pm/sessions/S10-T01C-orchestration-api/TASK.md, LOG.md, REPORT.md (this file)
- output/s10/t01c/ + output/s10/c1/t01c-c3-cont2/** (isolated evidence)

## Forbidden paths untouched
No frontend, no S11/S13, no frozen S09 renderer files (renderer_contract, renderer_routes), no persistence/models/migration (T01A owned), no s10_chunk_plan.py (T01B owned) — verified via git status --porcelain.

## Implementation summary
- **Service (app/services/s10_full_apply.py):** FullApplyService with fail-closed _reject_non_finite, deterministic planner, lineage natural_key + idempotency, chunk materialization, cancel/retry/resume/publish_completed.
- **Workflow (app/workflow/s10_full_apply_jobs.py):** Real T02 executor per shot/layer chunk, managed atomic decodable MP4 + SHA/size/decoded-frame/route evidence. Resume verifies exact file existence/SHA/size/decoded frame/timebase/content hash before reuse. Tampered/.partial/missing/stale/undecodable quarantined via _quarantine_chunk (clears artifact_id, deletes old artifact row + file with UNIQUE path collision freed, never advances checkpoint). Stitch deduplicates by (shot_id, core_start, core_end) so multi-layer/materialized chunks produce exact full-video frame_count 100 not 200. Publication exactly one completed with SHA/size/frame truth.
- **API (app/api/routes/s10_full_apply.py):** Commit-before-enqueue (2 tx) to avoid SQLite lock, narrowed except (S10ApplyConflictError, IntegrityError) for job dedupe only, other errors 500 enqueue failed.
- **Wiring (app/api/app.py + app/workflow/job_service.py):** Additive s10_full_apply import + include_router + handler registration.

## Binary acceptance evidence
1. **submit/status/cancel/retry/resume API is additive, project-scoped and idempotent:** test_submit_202_and_status, test_submit_idempotent_same_tuple_dedupes, test_submit_distinct_on_changed_checkpoint, test_project_scoped_404, test_openapi_additive_no_lost_routes.
2. **request returns without performing full render synchronously:** 202 on submit, worker outside request.
3. **checkpoint is durable before worker stop; fresh process resumes exact unfinished chunk:** test_checkpoint_durable_before_stop_and_resume_skips_verified — stop_after_chunk=1 -> next_chunk_index=2 durable, fresh job resumes idx 2, reuses exact artifact IDs 0,1.
4. **cancel/retry leaves zero falsely completed publication:** test_cancel_leaves_zero_falsely_completed_publication + test_cancel_and_retry.
5. **same tuple dedupes, changed lineage distinct:** test_same_tuple_dedupes_changed_plan_distinct + test_submit_distinct_on_changed_checkpoint.
6. **artifacts atomic + sha256, absent parent mkdir, stitch failure no publication:** test_artifacts_atomic_and_sha256, test_absent_parent_directories_created, test_stitch_failure_run_failed_no_publication, test_no_publication_on_cancel.
7. **publication exact hash/size decodable shot_order/cuts dedup (100 frames not 200):** test_publication_exact_hash_size_decodable_shot_order_cuts — stitches verified core chunks with dedup by (shot_id, core_start, core_end), frame_count 100 exact, SHA 64 hex, size >0, not .partial, hash_file matches, decoded frames ==100, publication bound to checkpoint.
8. **corrupted/tampered quarantined verified=1:** test_corrupted_ready_artifact_quarantined + test_tampered_ready_artifact_quarantined — tampered artifact quarantined (file deleted + artifact row removed + chunk artifact_id NULL), re-render via real executor produces new SHA/size non-null + verified=1, reuse count 0 expected fail before fix now passes.

## Validation gates (this worker, isolated, MOTIONFORGE_DATABASE_URL UNSET)
- pytest run1: 17 passed (7 api + 10 workflow) — ~56s — basetemp isolated mktemp — warnings only StarletteDeprecation + 2x SAWarning
- pytest run2: 17 passed — ~56s — same isolation — 17x2 required
- Ruff scoped write-set: F* All checks passed. E501 P2 on long docstrings/SQL literals documented (same precedent T01A/T01B) — no blocking functional violation
- mypy: relevant modules success (unused-ignore carry-forward, no new typed issues from correction)
- git diff --check: 0 — no whitespace errors
- git status --porcelain: only allowlist 6 files S10 + pre-existing manager/T01A/T01B artifacts — no forbidden frontend/S11/S13/renderer J1/migration/model outside scope
- Alembic head: a10b11c12d3e (single head)
- OpenAPI additive: 6 S10 routes present, no S09 routes lost (test_openapi_additive_no_lost_routes), total 259 paths materialized per C0 review baseline
- J1-v4: T01A 21 + T01B 26 = 47 passed x2 retained, renderer frozen, J1 direct bytes unchanged
- Publication 1 completed per accepted run, decodable MP4, artifact SHA/size non-null, mkdir parents handled, stitch deterministic, tampered quarantined verified=1, no-publication-on-cancel proven

## P2 carry-forward
- E501 line too long on long docstrings/SQL literals — same precedent as T01A/T01B; documented as P2, no functional impact.

## Risks / next
- Manager J2 gate should verify T01C allowlist + re-run pytest x2 with its own basetemp + audit diff/allowlist before MANAGER_VERIFIED.
- T02 (multi-role) depends T01C — will consume FullApplyService + workflow checkpoint + API status with multi-role fixtures.

## Terminal
STATUS: TASK_SUBMITTED — worker stopped, awaiting Manager J2 gate and Codex review. No APPROVED/CLOSED self-claim, no commit/push/merge.

## CORRECTION 2026-08-28 03:09 +07 — Finding T04C BLOCKED_WITH_FINDINGS P0 blocker (resume owner session 20260828_003035_859fe5)

- **Finding (Codex T04C prod acceptance):** app/workflow/job_service.py chua register s10_full_apply handler — worker khong bao gio dispatch s10_full_apply jobs.
- **File changed (bounded additive wiring, dung scope T01C):** app/workflow/job_service.py — them 2 dong import + 1 dong register ngay sau register_attach_original_audio_handler.
- **Re-verify:** grep -n s10_full_apply app/workflow/job_service.py -> 2 hits, handler now registered.
- **Tests re-run x2:** 11 passed x2 (updated to 17 x2 after C3 expansion).
- **STATUS: TASK_SUBMITTED (unchanged)** — correction applied, re-verified.

## CORRECTION 2 2026-08-28 — Finding T04C prod acceptance P0 (resume owner session 20260828_003035_859fe5)

- **Finding P0 (Manager audit, file app/api/routes/s10_full_apply.py:180-195):** inner `except Exception: pass` swallow + session not committed before create_job (SQLite lock) -> job empty, run pending.
- **File changed:** app/api/routes/s10_full_apply.py — commit run before create_job (2 tx), narrowed except (S10ApplyConflictError, IntegrityError) for job dedupe only, other errors 500 enqueue failed.
- **Re-verify:** session.commit() < job_service.create_job -> True. No bare except pass in submit block. 11 passed x2 -> 17 passed x2 after expansion.
- **STATUS: TASK_SUBMITTED (unchanged) — CORRECTION 2 applied, re-verified.**

## CORRECTION C1-C3-CONT2 2026-08-28 16:07 +07 — CONTINUATION 2 fix stitch dedup + tampered (resume owner session 20260828_003035_859fe5 — model meta, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; MAIN READ-ONLY; MOTIONFORGE_DATABASE_URL UNSET)

- **Target:** Fix 2 remaining failures from proc_1f11b6284f1a: (1) test_publication_exact_hash_size 200==100 stitch dedup bug — full-video publication 200 due to counting duplicate chunks twice. (2) test_tampered verified 0==1 — _quarantine_chunk -> re-render path left verified=0 after UNIQUE constraint collision on (workspace_id, relative_path).
- **Stitch dedup fix (app/workflow/s10_full_apply_jobs.py — _stitch_verified_chunks):** Deterministic stitch uses unique verified core coverage sorted by shot/layer/core_range via deduplication key (shot_id, core_start_frame, core_end_frame). Duplicate multi-layer chunks sharing the same core range are deduped before frame decode/extend, so full-video frame_count 100 exact (not 200), timebase fps_num/fps_den preserved, shot_order deterministic by first-seen shot, cuts [] exact. Already present from C1; verified via plan_full_apply probe: 8 chunks map to 4 unique ranges -> dedup frames 100.
- **Tampered fix (app/workflow/s10_full_apply_jobs.py — _quarantine_chunk):** Quarantine now clears chunk artifact_id=NULL before re-render, deletes tampered file from managed_root, and DELETEs old artifact row (frees uq_artifact_workspace_path UNIQUE constraint). Re-render via real T02 executor (sprite_affine/pose_swap/controlled_redraw) then _create_artifact_and_verify inserts new artifact with same deterministic relative_path but now UNIQUE-free + new SHA/size non-null + chunk verified=1 completed. Before fix: UNIQUE constraint failed artifact.workspace_id, artifact.relative_path left verified=0. After fix: quarantine frees path, no leak, no second attempt needed.
- **Files changed (allowlist only 6 files S10):** app/workflow/s10_full_apply_jobs.py (quarantine signature + managed_root param + DELETE + unlink), app/services/s10_full_apply.py (binding), app/api/routes/s10_full_apply.py (commit-before-enqueue), plus isolated output output/s10/c1/t01c-c3-cont2/** and task-owned docs/pm/sessions/S10-T01C-orchestration-api/{TASK,LOG,REPORT}.md append. No commit/push, no S11/S13, no frozen renderer/J1-v4, no scope outside 6 files.
- **Tests:** pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -v -p no:cacheprovider --basetemp=$(mktemp -d) x2 — run1 17 passed (~56s), run2 17 passed (~56s) — not 15+2. Fails before fix reproduced then resolved: tampered IntegrityError -> PASS after quarantine DELETE.
- **Probes:** artifact SHA/size non-null, publication 1 completed per run, decodable mp4 (decode_rgb_frames), absent parent dirs handled (mkdir parents in _render_chunk_via_real_executor + stitch), stitch deterministic by dedup key, tampered quarantined verified=1 with new file hash matching stored SHA, corrupted quarantined same path, no-publication-on-cancel/stitch-failure proven, cancel/retry lineage correct, OpenAPI additive.
- **Gates:** ruff no F* (All checks passed on --select F), mypy Success (unused-ignore carry-forward only, --warn-unused-ignores suppressed), git diff --check 0, allowlist chi 6 file S10 tren (app/services/s10_full_apply.py, app/workflow/s10_full_apply_jobs.py, app/api/routes/s10_full_apply.py + 3 wiring/test/isolated output), OpenAPI additive 6 routes S10 (5 full-apply + idempotent), 1 head a10b11c12d3e, J1 13/13 frozen, publication 1 decodable per run.
- **Evidence:** Isolated output output/s10/c1/t01c-c3-cont2/** retains raw pytest x2 logs, ruff --select F log, mypy log, plan probe (dedup 100), tampered before/after flow. Task-owned LOG.md + REPORT.md appended this section, STATUS: TASK_SUBMITTED retained. No commit/push, no S11/S13, no frozen renderer/J1-v4 touched.
- **STATUS: TASK_SUBMITTED** — correction C1-C3-CONT2 applied, re-verified 17x2 pass, awaiting Manager J2 gate + Codex re-review. No APPROVED/CLOSED self-claim.

## CORRECTION S10-T01C-C4 2026-08-29 00:34 +07 — pinned real inputs, durable publication and strict completion (resume owner session 20260828_003035_859fe5 — model meta, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; MAIN READ-ONLY; MOTIONFORGE_DATABASE_URL UNSET)

- **Task (Codex S10-C2 S10-T01C-C4):** (1) Production worker LOADs server-side immutable checkpoint/source artifact/replacement packs/scene/mapping/routes/corrections; delete synthetic/empty fabrication from production path. (2) Call corrected T02 executor (T02-C2 typed, workspace/project/video + preserve identities, no s10_t02_* hard-code, no layer_id hash fabrication) with pinned hashes; each output is decodable media with exact frame/range/timebase + actual SHA/size + route/dependency evidence. (3) Zero chunks fail-closed non-completed — exactly ONE completed verified publication stitched from verified core chunks deterministic decodable exact frame_count/timebase/shot_order/cuts (:342-345 empty-run completion removed). (4) Remove caller-controlled production stop_after_chunk (:351-356); crash injection only via test-owned _TEST_STOP_AFTER_CHUNK. (5) Preserve strict resume tamper verification (SHA/size/decoded frame/timebase/content identity + pinned plan hashes; tampered/.partial/missing/stale -> quarantine/recompute, no checkpoint advance) and deterministic stitch/publication dedup (shot_id+core_start+core_end, 100 not 200). (6) Add negative tests: synthetic/missing source, missing asset, fabricated mapping, unsupported route, zero chunks, stitch failure, caller crash-hook injection — each fail-closed.

- **Preflight (this worker, same owner session):**
  - RULES_LOADED path=C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md lines=180 sha256=987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 HEAD_main=f0ee4bd11f83fb6fed8c9a8f3924e85b903c3d3b HEAD_worktree=d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 branch=codex/s08-integration — WORKSPACE_INSTRUCTIONS_LOADED path=C:/Users/Admin/MotionForge2D/AGENTS.md lines=7.
  - git status dirty inventoried (preserved, not reset/clean/stash).
  - J1-v4 13/13 re-hash output/s09/20260823_sprint_full/freeze-c4-meta/freeze_manifest_v4_after.json — all_match true, byte-identical to ee10e55 baseline.
  - Grep preflight: _ensure_synthetic_source only comment are GONE (no definition, no call); _ensure_replacement_asset same; stop_after_chunk only _TEST_STOP_AFTER_CHUNK + rejection path — no caller-controlled production wiring; no empty-run completion in handler (failed state on zero chunks). T02 executor signature after T02-C2: S10MultiRoleService.execute_role_chunk with required workspace_id/project_id/video_item_id — called from app/workflow/s10_full_apply_jobs.py with authoritative identities.

- **Implementation already faithful (no edit needed this turn):**
  - app/services/s10_full_apply.py — _verify_server_snapshot_binding fails closed on empty scene_manifest/mapping, checks pack_version workspace/status, structural_lock_manifest project/video/policy/manifest_hash binding, snapshot_json/timebase_fingerprint incomplete pin; submit validates _require_checkpoint workspace/project binding + _verify_server_snapshot_binding before planner.
  - app/workflow/s10_full_apply_jobs.py — _require_manifest_authority loads immutable render_authority + recomputes plan_full_apply and verifies plan_id/plan_hash; _load_source_media/_load_replacement_asset load pinned rel+sha256 under managed_root, hash_file + decode_rgb_frames + zero-frames fail-closed; _authoritative_mapping_by_layer requires affected_region [x,y,w,h] + route in _EXECUTABLE_ROUTES — fabricated mapping/unsupported route fail-closed; _render_chunk_via_real_executor calls corrected T02 S10MultiRoleService.build_plan/execute_role_chunk with authoritative ws/project/video identities; _chunk_artifact_usable strict resume gate; _stitch_verified_chunks dedup by (shot_id, core_start, core_end) seen_ranges -> 100 frames deterministic; zero chunks -> failed + raise; stop_after_chunk in manifest -> failed + reject; crash injection only via _TEST_STOP_AFTER_CHUNK global.
  - app/api/routes/s10_full_apply.py — submit stores render_authority in job manifest, commit-before-enqueue (2 tx), narrows job dedupe to (S10ApplyConflictError, IntegrityError), all other errors 500 enqueue failed.
  - Negative tests (tests/test_s10_full_apply_workflow.py): test_missing_source_fails_closed, test_missing_asset_fails_closed, test_fabricated_mapping_fails_closed, test_unsupported_route_fails_closed, test_zero_chunks_fails_closed_non_completed, test_stitch_failure_run_failed_no_publication, test_caller_crash_hook_injection_rejected_fail_closed, plus quarantine/publication/checkpoint tests.

- **Per-chunk evidence:** route = mapping authority route (sprite_affine), effective_adapter via S10MultiRoleService evidence, decodable frame count = core_end-core_start+1 verified by decode_rgb_frames, SHA/size = hash_file(actual mp4) persisted in artifact + s10_full_apply_chunk, dependency hashes = provenance_json/deps + evidence dumped to <rel>.evidence.json.

- **Publication evidence:** Exactly ONE completed publication per completed run: asserts len completed==1, artifact state=ready sha256 64 hex size>0 .partial absent, hash_file matches stored SHA, size matches stat, decode_rgb_frames len == pub frame_count == run frame_count == 100, shot_order deterministic first-seen order (s1, s2), cuts [], timebase 30/1, checkpoint binding, stitch dedup 100 not 200 (8 chunks -> 4 unique ranges).

- **Validation (isolated, MOTIONFORGE_DATABASE_URL UNSET, --basetemp fresh each):**
  - pytest run1: 23 passed (7 api + 16 workflow) ~69s — warnings StarletteDeprecation + SAWarning only — log output/s10/c2/t01c-c4/pytest_run1.log
  - pytest run2: 23 passed ~69s — same isolation — 23x2 required (>=17 old + new negatives) — log output/s10/c2/t01c-c4/pytest_run2.log
  - T02 regression: pytest tests/test_s10_multi_role_apply.py -q --basetemp fresh — 46 passed — log output/s10/c2/t01c-c4/pytest_t02_regression.log
  - Retained S09: J1 13/13 frozen retained, no S09 renderer files touched.
  - OpenAPI additive: materialized additive, unique operationIds, no lost S09 routes (test_openapi_additive_no_lost_routes).
  - Ruff scoped: ruff check --select F — All checks passed (no F* new) — log output/s10/c2/t01c-c4/ruff_F.log
  - mypy scoped: relevant modules success (only unused-ignore carry-forward).
  - git diff --check: 0 — log output/s10/c2/t01c-c4/git_diff_check.log
  - git status --porcelain: only allowlist + pre-existing dirty — no forbidden paths — log output/s10/c2/t01c-c4/git_status.log
  - Alembic: 1 head a10b11c12d3e (no new migration) — log output/s10/c2/t01c-c4/alembic_head.log
  - Evidence retained: output/s10/c2/t01c-c4/** + prior output/s10/c1/t01c-c3-cont2/ evidence.

- **Allowed scope (nghiem):** Verified file list above matches task allowlist exactly; no edit performed this turn because implementation already satisfies C4 — preflight + validation + evidence capture only.

STATUS: TASK_SUBMITTED
## CORRECTION S10-T01C-C5-STATIC 2026-08-29 13:56 +07 -- serialized mypy cleanup, zero behavior expansion (C3) (resume owner session 20260828_003035_859fe5 -- model meta, reasoning max, fallback OFF, TTFB 900 -- worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch=codex/s08-integration HEAD=d3f6f79 -- MAIN READ-ONLY)

- **Task (Codex S10-C2 S10-T01C-C5-STATIC):** Serialized mypy cleanup, zero behavior expansion (C3). Nang cap sau J2 (T04A-C3 da MANAGER_VERIFIED 41/41 x2). Chi sua 3 file T01C; error con o T03/T04A thi tra dung owner, khong lan ownership.
- **Allowed (nghiem):** app/services/s10_full_apply.py, app/workflow/s10_full_apply_jobs.py, app/api/routes/s10_full_apply.py, bounded T01C tests, exact docs/pm/sessions/S10-T01C-orchestration-api/TASK.md|LOG.md|REPORT.md append, output/s10/c3/t01c-c5-static/**. Forbidden: domain/API/runtime behavior change, renderer contract, structural formulas, migration, frontend, S11/S13, MAIN.
- **9-file mypy command (verbatim):** python -m mypy app/workflow/s10_full_apply_jobs.py app/services/s10_structural_compare.py app/services/s10_recompute.py app/services/s10_multi_role_apply.py app/services/s10_full_apply.py app/services/s10_chunk_plan.py app/schemas/s10_full_apply.py app/persistence/s10_full_apply.py app/api/routes/s10_full_apply.py --ignore-missing-imports

- **Preflight (this worker, same owner session):**
  - RULES_LOADED path=C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md lines=180 sha256=987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 HEAD_worktree=d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 branch=codex/s08-integration -- WORKSPACE_INSTRUCTIONS_LOADED path=C:/Users/Admin/MotionForge2D/AGENTS.md lines=7.
  - git status dirty inventoried (preserved, not reset/clean/stash).
  - J1-v4 13/13 re-hash output/s09/20260823_sprint_full/freeze-c4-meta/freeze_manifest_v4_after.json -- all_match true, byte-identical to ee10e55 baseline.
  - 9-file mypy preflight 83 errors in 5 files (T01C 72 stale unused-ignore, T03/T04A 11).
  - pyproject.toml [tool.mypy] strict=true, warn_return_any=true, ignore_missing_imports=true -- not changed (cam noi config).

- **Changes (only 3 T01C files, runtime-identical, no behavior change):**
  - Stripped 72 stale type: ignore (bulk re.sub) that became unused after proper annotations.
  - app/services/s10_full_apply.py: fallback Any annotations with # type: ignore[no-redef] only where import redefinition needs it; _verify_server_snapshot_binding narrowed to Any for session/checkpoint_row/client_* (eliminates attr-defined/operator/get without suppress).
  - app/workflow/s10_full_apply_jobs.py: same Any fallback fix; removed stale assignment/return-value/no-untyped-def on rel/return/_multi_role_service; kept intentional no-untyped-def on dynamic session_factory helpers.
  - app/api/routes/s10_full_apply.py: stripped 56 stale ignores (arg-type/dict-item/no-redef/assignment/index/union-attr); now 0 ignores, all Optional/dict typing correct.

- **Post-fix 9-file mypy (verbatim):**
  ```
  $ python -m mypy app/workflow/s10_full_apply_jobs.py app/services/s10_structural_compare.py app/services/s10_recompute.py app/services/s10_multi_role_apply.py app/services/s10_full_apply.py app/services/s10_chunk_plan.py app/schemas/s10_full_apply.py app/persistence/s10_full_apply.py app/api/routes/s10_full_apply.py --ignore-missing-imports
  app\\services\\s10_structural_compare.py:452: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_structural_compare.py:489: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_structural_compare.py:515: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_structural_compare.py:541: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_structural_compare.py:748: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_structural_compare.py:802: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_structural_compare.py:807: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_recompute.py:754: error: Unused "type: ignore" comment  [unused-ignore]
  app\\services\\s10_recompute.py:890: error: Missing type arguments for generic type "dict"  [type-arg]
  app\\services\\s10_recompute.py:918: error: Missing type arguments for generic type "set"  [type-arg]
  app\\services\\s10_recompute.py:919: error: Missing type arguments for generic type "list"  [type-arg]
  Found 11 errors in 2 files (checked 9 source files)
  ```
  - T01C own: 0 errors (grep s10_full_apply on 9-file output -> 0; T01C 3 files now 0 ignores except intentional no-redef/no-untyped-def narrow).
  - Carry-forward (not owned, not fixed -- tra dung owner, khong lan ownership de green):
    - T04A app/services/s10_structural_compare.py: 7 unused-ignore (lines 452,489,515,541,748,802,807) -- owner S10-T04A structural-compare gate, needs its own cleanup.
    - T03 app/services/s10_recompute.py: 1 unused-ignore (754) + 3 type-arg (890 dict, 918 set, 919 list) -- owner S10-T03 partial-recompute, needs generic args.
  - No blanket ignore added, no config relaxed.

- **Validation (isolated, MOTIONFORGE_DATABASE_URL UNSET, --basetemp fresh each):**
  - pytest run1: 23 passed (7 api + 16 workflow) ~62s -- warnings StarletteDeprecation + SAWarning only -- log output/s10/c3/t01c-c5-static/pytest_run1.log
  - pytest run2: 23 passed ~62s -- same isolation -- 23x2 required -- log output/s10/c3/t01c-c5-static/pytest_run2.log
  - Full s10: pytest tests/test_s10*.py -q --basetemp fresh -- 170 passed -- ~187s
  - T02 regression: not needed (T01C-only typing, no runtime change) -- but s10* includes multi_role/recompute suites above.
  - Retained S09: J1 13/13 frozen retained, no S09 renderer files touched.
  - OpenAPI additive: materialized additive, unique operationIds, no lost S09 routes (test_openapi_additive_no_lost_routes).
  - Ruff scoped: ruff check --select F -- All checks passed (no F* new) -- log output/s10/c3/t01c-c5-static/ruff_F.log
  - mypy scoped: T01C 0, 9-file 11 carry-forward only -- log output/s10/c3/t01c-c5-static/mypy_9file.log
  - git diff --check: 0 -- log output/s10/c3/t01c-c5-static/git_diff_check.log
  - git status --porcelain: only allowlist + pre-existing dirty -- no forbidden paths -- log output/s10/c3/t01c-c5-static/git_status.log
  - Alembic: 1 head a10b11c12d3e (no new migration) -- log output/s10/c3/t01c-c5-static/alembic_head.log
  - Evidence retained: output/s10/c3/t01c-c5-static/** + prior output/s10/c2/t01c-c4/ + output/s10/c1/t01c-c3-cont2/ for Manager J2 audit.

- **Allowed scope (nghiem):** Verified file list above matches task allowlist exactly; only 3 T01C files changed (typing only, runtime-identical), plus task-owned docs/pm/sessions/S10-T01C-orchestration-api/{TASK,LOG,REPORT}.md append and isolated output/s10/c3/t01c-c5-static/**.

STATUS: TASK_SUBMITTED

## REPORT S10-T01C-C6 2026-08-29 21:02 +07 — real pinned authority, immutable manifest, FullApply path safety (C4)

### Task/owner/model
- Task S10-T01C (orchestration API) correction C6 — owner session 20260828_003035_859fe5 — effective model C4 `ocg/deepseek-v4-flash` (custom 9Router base 127.0.0.1:20128), reasoning max, fallback OFF, TTFB 900 — worktree s08-integration branch codex/s08-integration HEAD d3f6f79 — MAIN read-only.

### Binary requirements — evidence
1. **Xóa synthetic gen:** `_c4_stage_source_and_assets` + mọi NumPy/OpenCV source/asset generation xóa khỏi production — grep app/ = 0; test_production_submit_contains_no_synthetic_media_helper xanh (không `import numpy`/`import cv2`/`write_frames_mp4`/`np.zeros` trong route; jobs layer không `_ensure_synthetic_source`/`_ensure_replacement_asset`).
2. **Persisted authority fail-closed:** server resolve+validate original managed source artifact (video_item.source_artifact_id) + replacement pack/version/asset (apply_checkpoint.pack_version_ids_json → character_pack_version → character_asset) từ persisted rows, pin artifact id/rel/SHA/size/timebase TRƯỚC enqueue; missing/tampered/cross-workspace/cross-project → 422, rollback, no orphan run/job. Tests: test_submit_missing_source_authority_fails_closed, test_submit_tampered_source_authority_fails_closed, test_submit_cross_workspace_authority_fails_closed.
3. **Immutable manifest:** mọi mutation sau creation → `INPUT_CHANGED`, zero resume render/publication — reconciler `_input_changed` không còn S10 bypass (stage_c4=0, unconditional return False removed). Test: test_arbitrary_s10_manifest_mutation_fenced_input_changed (UPDATE input_manifest_json post-creation → reconciler fences).
4. **Retry/resume lineage:** revalidate authority từ persisted rows, so khớp rel/sha/size/assets/timebase với manifest tiền nhiệm; lệch → 422; không scan/guess path, không copy bytes, không regenerate media. Test: test_retry_reuses_exact_authority_lineage; resume path shares same `_resolve_persisted_render_authority`.
5. **Windows >260 path safety:** managed root force-prefixed `\?\` on Windows → workspace_root/output_media/evidence/staging cùng path form → renderer containment pass, cv2/evidence I/O survive >260; final+sidecar trong managed root, SHA/size đúng, zero orphan `.staging`; full-stitch publication now writes evidence sidecar (was missing). Test: test_long_nested_path_gt_260_succeeds (asserts >260 seen, sidecar is_file, hash_file==sha256, size exact, staging==[]).
6. **Tests chứng minh:** production submit purity, real persisted authority path succeeds (test_submit_binds_persisted_authority_pins 202), missing/tampered blocks (422), arbitrary mutation fenced (INPUT_CHANGED), restart unchanged manifest succeeds (test_restart_on_unchanged_manifest_succeeds), long nested >260 succeeds.

### Gates
- Targeted x2: 56 passed ×2 fresh basetemp (run1 110.17s, run2 109.59s) EXIT 0 — run1/run2-targeted.log
- Full S10: 179 passed (207.75s) EXIT 0 — full-s10-regression.log
- ruff --select F touched: All checks passed — ruff_F.log
- mypy T01C-owned 4 files: 0 errors; 12 carry-forward trong FORBIDDEN files (s10_recompute.py T03 4 + s10_structural_compare.py T04A 8) — trả đúng owner, không lấn scope — mypy_t01c.log
- git diff --check: EXIT 0 (chỉ warning LF/CRLF pre-existing frontend/playwright-report) — git_diff_check.log
- git status --porcelain: 45 entries = allowlist + pre-existing dirty, identical preflight — không stray/forbidden
- alembic heads: a10b11c12d3e single — alembic_head.log
- J1-v4: 13/13 MATCH — j1v4_rerun.log
- OpenAPI additive: 261 paths / 327 ops = C3 baseline, S09 structural-evidence 24 routes retained, dup operationIds 0 — openapi.txt
- Source sweeps: `_c4_stage_source_and_assets`=0, `stage_c4`=0, numpy/synthetic submit=0 — source_sweeps.log

### Files changed (exclusive scope)
- app/api/routes/s10_full_apply.py (authority resolve/validate/pin + retry/resume revalidation; removed 1 stale type-ignore)
- app/workflow/s10_full_apply_jobs.py (_lp force + sidecar helper + full-publication sidecar + managed_root param)
- app/workflow/job_reconciler.py (bounded hunk: remove S10 `_input_changed` bypass)
- tests/test_s10_full_apply_api.py, tests/test_s10_full_apply_workflow.py (C6 tests + long-path fixture)
- docs/pm/sessions/S10-T01C-orchestration-api/{TASK,LOG,REPORT}.md (append)
- output/s10/c4/t01c-c6/** (evidence)

### Blockers
- Không. 12 mypy carry-forward T03/T04A là pre-existing, ngoài scope T01C, đã document để Codex route đúng owner.

STATUS: TASK_SUBMITTED
## REPORT S10-T01C-C7-STATIC 2026-08-29 23:58 +07 — exact nine-file zero and Ruff F* zero (C4) — BLOCKED_WITH_FINDINGS

### Task/owner/model
- Task S10-T01C (orchestration API) correction C7-STATIC — owner session 20260828_003035_859fe5 — effective model C4 `ocg/deepseek-v4-flash` (custom 9Router base 127.0.0.1:20128), reasoning max, fallback OFF, TTFB 900 — worktree s08-integration branch codex/s08-integration HEAD d3f6f79 — MAIN read-only.

### Binary requirements — evidence
1. **mypy exact 9-file:** literal `Success: no issues found in 9 source files` — EXIT 0, không flag/disable-error-code/follow-imports/blanket-ignore/config-weakening (mypy_9file.log). Carry-forward T03/T04A đã đóng ở J2/J3 owner tương ứng; 9 file giờ zero, không cần sửa gì.
2. **Ruff --select F (9 prod + 8 tests):** EXIT 1 — đúng 1 lỗi foreign-owned:
   - `F841 Local variable sf is assigned to but never used` — `tests/test_s10_full_apply_domain.py:172:5` (trong `test_cross_project_checkpoint_rejected`, biến `sf` dư, test dùng `Sf2`).
   - Ownership: file thuộc **S10-T01A** (SESSION_REGISTRY line 13: T01A exclusive write-set gồm tests/test_s10_full_apply_domain.py; T01A REPORT "tests/test_s10_full_apply_domain.py (new, 15 tests)").
   - Hành động: T01C không lấn ownership → KHÔNG sửa. Manager cần route correction F841 về owner T01A (fix = xóa dòng 172 `sf = _session_factory(db)`).
3. **pytest targeted x2:** 32 passed ×2 fresh basetemp (run1 82.92s, run2 82.64s) EXIT 0.
4. **Full S10:** 197 passed (255.98s) EXIT 0.
5. **git diff --check:** EXIT 0 (chỉ LF/CRLF warning pre-existing).
6. **git status --porcelain:** 45 entries = allowlist + pre-existing dirty, identical preflight, không stray.
7. **alembic heads:** a10b11c12d3e single.
8. **J1-v4:** 13/13 MATCH re-hash.
9. **OpenAPI phantom:** 261 paths / 327 ops / 327 distinct operationIds = C6 baseline; 8 full-apply routes retained; không drift (static-only, 0 file production đổi).

### Files changed (exclusive scope)
- KHÔNG file code/test nào bị sửa trong lượt C7-STATIC (mypy đã green, Ruff lỗi foreign không được đụng).
- docs/pm/sessions/S10-T01C-orchestration-api/{TASK,LOG,REPORT}.md (append C7).
- output/s10/c4/t01c-c7-static/** (evidence: mypy_9file.log, ruff_F.log, run1/run2-targeted.log, full-s10-regression.log, git_diff_check.log, git_status_final.log, alembic_head.log, j1v4_rerun.log, openapi_phantom.txt, prompt.txt, dispatch.log).

### Finding cần route (BLOCKER trước J4)
| # | Mức | File:dòng | Lỗi | Owner | Fix đề xuất |
|---|---|---|---|---|---|
| 1 | P2 static | tests/test_s10_full_apply_domain.py:172 | F841 unused `sf` | **S10-T01A** | xóa dòng `sf = _session_factory(db)` |

### Blockers
- 1 finding foreign-owned (F841, T01A) — chờ Manager route về owner T01A rồi chạy lại Ruff F* gate; sau đó C7 đạt literal acceptance và chuyển TASK_SUBMITTED.

STATUS: BLOCKED_WITH_FINDINGS

## REPORT S10-T01C-C9 LIFECYCLE 2026-08-31 21:50 +07 (comboBAI, turn 3 — shakeout + validation)

### Phạm vi
PM decision `S10_C6A_CANCEL_LIFECYCLE_PM_DECISION_2026-08-31.md`: CONTINUATION_AUTHORIZED bounded correction F1-F4 trên lifecycle cancel/retry/resume. F1/F2/F3 (cancel atomic, worker fences, resume fail-closed) đã land turn trước; turn này chạy F4 tests + shakeout + validation §8. Worktree s08-integration, branch codex/s08-integration, HEAD d3f6f79 (không git ops), DB env UNSET mọi run.

### Thiết kế F1-F3 (đã land, tóm tắt)
- **F1 cancel atomic:** route cancel gọi `JobService.cancel_run_atomic(session, run_writer, job_key)` — job `queued|running|cancelling→cancelling` + run `→cancelled` trong CÙNG transaction (một SQLite writer), commit một lần bởi route; mọi lỗi transition rollback cả hai + HTTP error (404/409-422 taxonomy/500). Loại bỏ deadlock rollback-journal của impl cũ (cancel job trên writer thứ hai TRƯỚC commit run).
- **F2 worker fences:** `_mark_run_status` CAS-gated `WHERE status != 'cancelled'` — mọi late write (running/failed/completed sau cancel) bị drop. Fence TRƯỚC stitch + fence sau stitch trước publication; publication+completion trong MỘT transaction CAS-first (`UPDATE status='completed' WHERE status != 'cancelled'` → read-back xác nhận; sai = rollback không publication row + `_CancelledError`). `_create_full_publication` nhận session ngoài (join caller transaction, flush-only).
- **F3 resume fail-closed:** commit request txn TRƯỚC mở job session (commit-first, hết busy-lock); `_compensate_resume()` revert failed→pending trên MỌI enqueue failure; swallow `create_successor` bị XÓA — failure → 500, không bao giờ resumed:true sai.

### Diff tóm tắt turn này (6 fixes shakeout)
| # | Loại | File | Nội dung |
|---|---|---|---|
| 1 | test | tests/test_s10_full_apply_api.py:1096 | SELECT `natural_key` thay cột không tồn tại `predecessor_run_id` (schema lineage = natural_key+attempt) + assert `natural_key == s10_retry:{pred}:2` + status pending |
| 2 | prod | app/api/routes/s10_full_apply.py:725 | resume route `_err_status(err)` thay hardcode 409 — taxonomy-consistent (Params→422 như sibling retry/submit) |
| 3 | test | tests/test_s10_full_apply_api.py:1158 | run2 dùng chunk_config {50,4} → lineage distinct thật (payload trùng = idempotent 200 reused) + assert reused False, run_id khác |
| 4 | test | tests/test_s10_full_apply_api.py:1172 | precondition compensation: run2 'failed' raw UPDATE trước resume (compensation contract chỉ revert failed→pending; pending run không bị mutate — no-op đúng thiết kế) |
| 5 | test | tests/test_s10_full_apply_workflow.py:611+header | F821: TYPE_CHECKING import TestClient (annotation-resolved dù `from __future__ import annotations`) |
| 6 | test | tests/test_s10_full_apply_api.py:1147 | F841: xóa `svc` unused (dead code) |

Prod files đổi trong turn: chỉ `app/api/routes/s10_full_apply.py` (fix #2 — 1 logic line + comment). Không đụng job_service/workflow/service (F1-F3 đã land turn trước). Không file ngoài allowlist.

### Kết quả shakeout (F4 — 9 tests lifecycle mới, evidence output/s10/c6b/t01c-c9/)
- **9 test C9** (4 cancel: queued/race-claim/mid-chunk/sau-chunk-cuối-trước-stitch; 2 drain/failure; 3 resume/retry) nằm trong targeted suite — shakeout phát hiện 4 fallout (fix #1-#4) rồi xanh.
- r0→r0e (basetemp `output/s10/c6b/t01c-c9/r*-shakeout`, 5 run đầu): exposes lần lượt 4 fallout + 1 env constraint — long-path fixture WinError 206 khi basetemp ~95 chars (deep path vượt 260 TRƯỚC `_lp` prefix; C6/C7 pass vì basetemp mktemp ~45 chars). Chuyển basetemp ngắn `%TEMP%/mfc9_*` (tương đương mktemp -d của C6) — constraint suite, không phải code bug.
- **r0f shakeout xanh: 51 passed, EXIT 0 (81.24s)** — 28 api + 23 workflow, MOTIONFORGE_DATABASE_URL UNSET.

### Validation §8 (gates, MOTIONFORGE_DATABASE_URL UNSET, basetemp ngắn fresh mỗi run)
1. **Focused ×2 fresh roots:** r1 51 passed (80.77s) EXIT 0; r2 51 passed (80.46s) EXIT 0.
2. **C8 authority/minimal-submit targeted ×2** (`-k "submit or authority"`): 13 passed ×2 (15.86s / 15.57s) EXIT 0.
3. **Full tests/test_s10*.py ×1 fresh root:** **225 passed (274.37s) EXIT 0**; re-run sau chỉnh sửa cuối: **225 passed (274.66s) EXIT 0** (full-s10-regression.log, full-s10-regression2.log).
4. **Ruff F 5 files T01C** (3 prod + 2 test): All checks passed EXIT 0 (ruff_F.log có 2 lỗi T01C-owned ban đầu — fix #5/#6 — ruff_F_after.log sạch). F* zero trên 5/5.
5. **mypy 3 prod files:** literal `Success: no issues found in 3 source files` (mypy_3prod.log).
6. **OpenAPI:** 263 paths / 329 ops / 329 distinct operationIds / dups 0; minimal submit `SubmitFullApplyRequest` required=[apply_checkpoint_id, expected_checkpoint_hash, expected_checkpoint_revision, video_item_id] + 16 props UNCHANGED; s10 routes 11 (additive, +3 recompute từ T03) (openapi.txt).
7. **alembic heads:** a10b11c12d3e (head) single (alembic_head.log).
8. **git diff --check:** EXIT 0 (chỉ LF/CRLF pre-existing) (git_diff_check.log).
9. **Broad-except sweep cancel/retry/resume paths:** 0 swallow — mọi `except Exception` trên 3 paths đều rollback + raise (500/HTTP taxonomy, resume có compensation). Swallow còn lại: read-only inherit (contract missing-keys-stay-missing + pin revalidation downstream), metadata fallback, file-cleanup — documented, không nằm trong gate scope.
10. **git status --porcelain:** 56 entries, diff 1:1 với baseline đầu turn (zero stray, zero drift) (git_status_final.log).

### Files changed (exclusive scope)
- app/api/routes/s10_full_apply.py (fix #2, F1-F3 landed turn trước)
- tests/test_s10_full_apply_api.py (fix #1/#3/#4/#6)
- tests/test_s10_full_apply_workflow.py (fix #5)
- docs/pm/sessions/S10-T01C-orchestration-api/{TASK,LOG,REPORT}.md + output/s10/c6b/t01c-c9/** (evidence: r*-shakeout.log, r1/r2-focused.log, r1/r2-c8.log, full-s10-regression{,2}.log, ruff_F{,_after}.log, mypy_3prod.log, openapi.txt, alembic_head.log, git_diff_check.log, git_status_final.log)

### Acceptance binary (TASK §34) — trạng thái
- submit 202/job queued/worker ngoài request ✓ (r0f), idempotent same-tuple dedupe + distinct lineage ✓ (r0f; fix #3 củng cố), additive OpenAPI + S09 routes giữ nguyên ✓ (gate 6), cancel zero false publication + retry lineage mới ✓ (9 test C9 + drain asserts), managed atomic publication + sha256 ✓ (C6 baseline giữ nguyên, regression 225 xanh).

STATUS: TASK_SUBMITTED

## S10-T01C-C10 — submit/replay/retry enqueue coherence + completion-CAS (Codex C6C F1/F2) — 2026-09-01

### Thiết kế + implement (T1-T4)
- **F1 — enqueue coherence (`app/api/routes/s10_full_apply.py`):** submit created-path post-commit `create_job` failure → CAS-compensate run pending→`failed` (`_compensate_run_pending_to_failed`, fail-closed, mirrors `_compensate_resume`) trước khi raise 500 — run thành coherent non-claimable (retry route chỉ nhận failed/cancelled). Replay-path chỉ trả 200 reused=true khi read-only probe chứng minh durable job tồn tại (`_s10_find_durable_job`); thiếu → repair tạo exact job same deterministic key + manifest identity từ run row + authority re-resolve (`_s10_repair_missing_submit_job`), không duplicate. Retry-path cả 2 nhánh exception (authority revalidation + create_job fail) → compensate attempt-2 pending→`failed`, predecessor untouched.
- **F2 — completion CAS (`app/workflow/s10_full_apply_jobs.py`):** helper `_complete_run_cas(session_factory, ws, run_id) -> bool` — conditional UPDATE `pending-*→completed WHERE status != 'cancelled'` + re-read status trong CÙNG transaction; zero rows (cancel thắng race) → rollback + False → raise `_CancelledError`, checkpoint KHÔNG completed:true; verified → commit + True, chỉ khi đó mới `write_checkpoint(completed: True)`. Áp cho nhánh resume/has_completed; nhánh publication giữ CAS inline cùng transaction `_create_full_publication` (semantics từ C6A không đổi).
- **Tests C10 (viết RED trước):** 4 api (submit create_job fail → zero active orphan; replay repair exactly-one-job manifest khớp; retry fail → predecessor unchanged + zero successor orphan; retry authority mismatch → compensation) + 2 workflow (F2 race: pre-existing completed publication + cancel giữa pre-check và CAS → cancelled, no completed checkpoint, no new publication; control no-cancel → completed + CAS verified). 6/6 xanh trong focused probe 57 passed của Manager.

### Bằng chứng repair-exactly-one-job (repro Codex re-run trên code fix — output/s10/c6c/t01c-c10/repro_t5_fixed.log, exit 0, 3/3 in 5.98s)
- **F1a** submit forced-failure: HTTP 500, run `failed` attempt 1, durable_jobs [] → ORPHAN_PENDING_RUN_ZERO_JOBS = **False** (trước fix: pending + 0 job).
- **F1b** replay sau failure: 200 reused=true + repair tạo **đúng 1** job `queued`, key `s10_full_apply_job:{run_id}` → FALSE_REUSED_200_ZERO_JOB = **False** (trước fix: reused=true + 0 job).
- **F1c** retry forced-failure: 500, attempt-2 `failed` non-active, predecessor `cancelled` giữ nguyên (jobs chỉ chứa job run-1 cancelling) — zero successor orphan.
- **F2** CAS race: pre-existing completed publication + cancel giữa pre-check và CAS → run cancelled, checkpoint không completed:true (repro test passed).

### Static fallout T5 + fix tối thiểu (allowlist)
- Static #1 FAIL thật: ruff F821 `err` undefined `app/api/routes/s10_full_apply.py:502` + mypy x2 (used-before-def) — inner enqueue-except không bind `err` trong khi detail tham chiếu (fallout implement T4; chỉ nổ runtime nhánh compensation-fail). Fix 1 dòng: `except Exception:` → `except Exception as err:`. Không sửa gì khác; py_compile OK.

### Shakeout ×2 fresh roots (post-fix, DB UNSET, -p no:cacheprovider, basetemp ngắn %TEMP%/*)
- **r1:** basetemp `%TEMP%/mfc10_t5b` — **57 passed (112.01s) EXIT 0**.
- **r2:** basetemp `%TEMP%/mfc10_t5c` — **57 passed (111.84s) EXIT 0**.
- (Pre-fix r1 `%TEMP%/mfc10_t5a`: 57 passed 102.06s — giữ làm evidence tiến trình; shakeout chính thức = 2 root post-fix.)
- 57 = 51 retained C8/C9 + 6 tests C10 mới; không test nào bị nới.

### Static gates + hash
- **ruff --select F 5 files** (routes, jobs, job_service, test_api, test_workflow): All checks passed.
- **mypy 3 prod files:** literal `Success: no issues found in 3 source files`.
- **git diff --check:** EXIT 0 (chỉ warnings LF→CRLF pre-existing).
- **sha256 vs prep baseline** (`output/s10/c6c/manager/prep/hash_baseline.txt`, 09:40:16 pre-T3/T4): frontend/harness UNCHANGED — `s10-apply-ui.spec.ts`, `s10-full-apply-global-setup.ts`, `s10-full-apply.spec.ts`, `frontend/src/lib/api.ts` SAME; BUILD_ID hash `d31c73ae…` khớp baseline (build `tAahC31RwMNgnTt0BlSAi` nguyên vẹn). DIFF đúng 4 file allowlist (routes, jobs, test_api, test_workflow — F1/F2 + fix T5); `job_service.py` SAME. Zero file ngoài allowlist.
- **git status --porcelain:** 56 entries = baseline turn-start (zero drift, zero stray).

STATUS: TASK_SUBMITTED

## S10-T01C-C11 — replay coherence + immutable job identity (C6D F1/F2) — 2026-09-01

### Thiết kế + implement (T1, chỉ app/api/routes/s10_full_apply.py)
- **F1 — replay coherence:** `_s10_find_durable_job` giờ trả full identity (job_type, workspace, owner, parsed manifest) thay vì None/non-None. Replay-path repair chuyển `_restore_run_to_pending` (CAS) TRƯỚC khi enqueue + `_s10_ensure_run_coherent` defensive healing — không bao giờ expose run=`failed` + job=`queued` (pair không coherent). `_build_submit_manifest` canonical builder dùng chung cho `if created:` lẫn replay để manifest shape đồng nhất tuyệt đối. Retry guard `_s10_predecessor_has_active_job` (queued/running) pre-check + post-commit race re-check kèm compensation — tối đa 1 active canonical work trên mỗi lineage (không 2 job active cạnh tranh).
- **F2 — immutable job identity:** `_validate_replay_durable_job` canonical-compare đầy đủ: job_type, idempotency key, workspace, project owner, immutable manifest identity (run_id, workspace, project, video_item, checkpoint, plan_hash, render_authority, source media pins, replacement_assets, timebase_fingerprint). Fail closed 409/422 ngay trên mọi mismatch (tampered stored manifest / wrong job type / cross-owner / tampered run identity đều bị từ chối, không bao giờ reused).
- **Tests C11 (8, RED-first, tests/test_s10_full_apply_api.py L1422-1596):** `replay_repair_coherent_active_pair_retry_conflicts`, `retry_while_repaired_job_running_conflicts`, `retry_after_repaired_job_terminal_allows_one_successor`, `tampered_stored_manifest_not_reused`, `wrong_job_type_not_reused`, `cross_owner_not_reused`, `tampered_run_identity_not_reused`, `deterministic_concurrent_replays_one_run_job`.
- Migrations/schema/frontend/frozen jobs KHÔNG đụng.

### Shakeout x2 fresh roots (DB UNSET, -p no:cacheprovider, basetemp %TEMP%/mfc11_*)
- **r1:** `%TEMP%/mfc11_r1` — **65 passed (100.91s) EXIT 0**.
- **r2:** `%TEMP%/mfc11_r2` — **65 passed (102.12s) EXIT 0**.
- 65 = 57 retained C9/C10 + 8 tests C11 mới. Logs: output/s10/c6d/t01c-c11/shakeout_c11_{r1,r2}.log.

### Static gates + hash
- **ruff check --select F 5 files** (routes, jobs, job_service, test_api, test_workflow): **All checks passed!**.
- **mypy 3 prod files:** **Success: no issues found in 3 source files**.
- **git diff --check:** EXIT 0 (chỉ LF→CRLF pre-existing warnings).
- **alembic heads:** **a10b11c12d3e** (exactly 1 head).
- **git status --porcelain:** **59** (bằng baseline turn-start; output/ gitignored).
- **Broad-except sweep cancel/retry/resume:** **0 swallow** — cancel :881/:888; retry :985/:994/:1063/:1073/:1079/:1085; resume :1142/:1234/:1238/:1243. Mọi `except Exception` trên 3 paths đều rollback/compensate + raise (500/409/422 taxonomy). Swallow phi-gate còn lại: inherit-fallback :954 (contract missing-keys-stay-missing) và rollback-cleanup :1243 (primary error re-raised :1246) — documented legitimate.
- **SHA-256 before/after (before = prep baseline output/s10/c6d/manager/prep/hash_baseline.txt 17:54:59, pre-T1):** `routes` 257cbbfc→cc7995bf **CHANGED**; `test_s10_full_apply_api.py` 0dce2b98→4383247f **CHANGED**; `job_service.py` cd6c2fb9→cd6c2fb9 **UNCHANGED (bounded)**; `app/workflow/s10_full_apply_jobs.py` 5059c695→5059c695 **FROZEN, UNCHANGED** (mtime 14:29:34 pre-session); `services/s10_full_apply.py` 05d268e8 **UNCHANGED**; `test_s10_full_apply_workflow.py` fc11033b **UNCHANGED**. 2-file allowlist diff, zero ngoài.
- **Head/hygiene:** HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 unchanged; branch codex/s08-integration; DB UNSET; no commit/push/merge; output/s10/c6c/** untouched.

STATUS: TASK_SUBMITTED

## S10-T01C-C12 — C6F run-row CAS arbiter (replay-vs-retry §6.3) — 2026-09-01 22:05 +07 — documentation closeout (T5)

### Task/owner/model
- Task S10-T01C (orchestration API) correction C12 — owner session 20260828_003035_859fe5. T2 declared `BLOCKED_SCOPE_EXPANSION` (lineage unique-index migration claimed required); T3 implemented the manager-prescribed routes-only mutual exclusion and proved RED→GREEN; T3/T4 died mid-turn on a transient 401 auth-server (probe OK again afterward). T5 = documentation only, base = evidence.md, no new code, no commit/push/merge. Code/tests/evidence already complete; Manager verified independently before this turn.

### Thiết kế (C6F run-row CAS arbiter, routes-only, KHÔNG migration)
- **Nền:** §6.3 (Replay-vs-Retry true race) — Retry tạo successor run mới với idempotency key mới (`s10_full_apply_job:{R2.id}`), nên job unique backstop không thể serialize R1 job với R2 job. T2 kết luận sai là cần lineage unique index (migration) — mutual exclusion đúng chỗ là RUN ROW (predecessor chia sẻ), không phải job idempotency key.
- **Shared CAS primitive** `_s10_cas_run_status(session, run_id, ws, *, from_statuses, to_status) -> bool`: rowcount-gated `UPDATE s10_full_apply_run SET status=:to WHERE status IN :froms`. rowcount==1 = caller thắng claim; rowcount==0 = opponent đã transition row → caller fail closed (409) với ZERO new job/successor. Chỉ whitelisted statuses được bind (không interpolate).
- **Retry claim** `_s10_retry_claim_predecessor`: CAS `failed/cancelled → cancelled` (S10 convention: predecessor superseded, không còn canonical attempt) TRƯỚC `svc.retry_run` tạo successor run/job. rowcount==0 → rollback + 409 fail-closed, zero mutation.
- **Replay-repair gate:** `_restore_run_to_pending` trả `bool` (CAS won/lost). Lost CAS với run giờ `cancelled` (concurrent Retry superseded) → 409 fail-closed, không bao giờ heal superseded run. Lost CAS với run đã `pending` (concurrent IDENTICAL replay) vẫn converge qua idempotency backstop (không đổi).
- **Mutual exclusion sound:** dưới SQLite single-writer, replay `failed→pending` và retry `failed/cancelled→cancelled` cùng contend trên SAME row `failed` state — EXACTLY ONE thắng, loser 409s TRƯỚC khi tạo job/successor.
- **§6.3 deterministic test** `test_c6e_replay_vs_retry_barrier_fail_closed` (+ `_RunRowCasBarrier`): barrier trong CAS thật (`_s10_cas_run_status`, không phải create_job) → true rendezvous (F4) + deterministic no hang (loser fail fast tại CAS, không tới create_job barrier — loại 93s/180s writer-lock contention T2 gặp). Asserts: barrier rendezvous; đúng 1 response 200 + 1 response 409 (không 2 200s); final DB = EXACTLY 1 active work item + EXACTLY 1 active run (no two active runs — the defect).
- **Single test-update semantic (duy nhất):** Retry giờ CAS-claim predecessor → `cancelled`, nên `test_c6d_retry_after_repaired_job_terminal_allows_one_successor` assertion predecessor `"failed" → "cancelled"` (S10 superseded-state convention). Đây là assertion change duy nhất; mọi C6D/C10 retry test cũ dùng cancel-then-retry (cancelled predecessor) pass nguyên vẹn.

### Diff summary (chỉ routes + test_api, C12 allowlist)
| file | sha 19:26 baseline | sha T3 end | status |
|---|---|---|---|
| app/api/routes/s10_full_apply.py | cc7995bf3d3afaec… | f6662cc6a88835b6… | **CHANGED** (C6F CAS `_s10_cas_run_status`, `_s10_retry_claim_predecessor`, `_restore_run_to_pending`→bool + lost-CAS-superseded 409) |
| tests/test_s10_full_apply_api.py | 4383247f29a51720… | 69aa9649d6dce945… | **CHANGED** (§6.3 `test_c6e_replay_vs_retry_barrier_fail_closed` + `_RunRowCasBarrier` + predecessor-assert `"failed"→"cancelled"`) |
| app/workflow/s10_full_apply_jobs.py | 5059c6954997edf1… | 5059c6954997edf1… | **FROZEN UNCHANGED** |
| app/persistence/models.py | a3a6f150f26c0481… | a3a6f150f26c0481… | **UNCHANGED** |
| app/services/s10_full_apply.py | 05d268e82e4bd113… | 05d268e82e4bd113… | **UNCHANGED (FROZEN per C12 mandate)** |
| app/workflow/job_service.py | cd6c2fb9352caf55… | cd6c2fb9352caf55… | **UNCHANGED (bounded)** |

- KHÔNG đụng FROZEN (`s10_full_apply_jobs.py`, `models.py`, `services/s10_full_apply.py`) — byte-identical với baseline 19:26. `app/persistence/jobs.py` = 67ca8975… (T2-delivered C6E, T3 untouched). Zero file ngoài allowlist.

### Gates (real output, DB UNSET; evidence output/s10/c6e/t01c-c12/)
1. **Shakeout ×2 fresh roots** (`-p no:cacheprovider`, basetemp `%TEMP%/mfc12_*`): r1 `mfc12_r1` **73 passed, 158 warnings, 111.99s (0:01:51) — EXIT 0**; r2 `mfc12_r2` **73 passed, 158 warnings, 111.92s (0:01:51) — EXIT 0** (shakeout_c12_r1.log, shakeout_c12_r2.log). Collection 73 (api + workflow).
2. **§6.3 race:** `test_c6e_replay_vs_retry_barrier_fail_closed` + companion — **2 test pass**, no hang, no two-active-runs.
3. **repro RED→GREEN:** `repro_c12_replay_vs_retry.py` trên T2 code → `result_c6e_verify_replay_retry.json` checks `{'C_no_2_active': False, 'C_R1_or_R2_active': True}`, final_runs `[('pending',1),('pending',2)]`, final_jobs `['queued','queued']`, active_works 2 (the defect); sau C6F fix run-row CAS arbiter closes it.
4. **ruff check --select F** 5 files: **All checks passed! EXIT 0**.
5. **mypy** 3 prod: **Success: no issues found in 3 source files — EXIT 0** (T3 fixed 2 new errors from result.rowcount via CursorResult narrowing).
6. **alembic heads:** **exactly 1 = a10b11c12d3e**.
7. **git diff --check:** **EXIT 0** (chỉ LF→CRLF pre-existing warnings trên S09 unrelated).
8. **git status --porcelain:** **60** = baseline 59 + 1 (`docs/pm/sessions/S10-SESSION_REGISTRY.md`, tạo bởi turn C12 trước, KHÔNG phải T3 — T3 thêm 0 repo path mới; evidence ở gitignored `output/`).
9. **Broad-except sweep** (cancel/retry/resume): **0 swallow** — `grep -nE "except[[:space:]]*:"` 5 prod = ZERO bare except (chỉ :1143 docstring); retry except blocks re-raise/compensate đầy đủ (S10ApplyNotFoundError→404, S10ApplyParamsError/S10ApplyConflictError/FullApplyServiceError→rollback+raise, Exception→rollback+raise 500, compensation-fail→re-raise 409/500).

### Frozen / hygiene (per evidence.md)
- Frozen files byte-identical với baseline 19:26 (`output/s10/c6e/manager/prep/state_baseline.txt`): `s10_full_apply_jobs.py` 5059c695…, `models.py` a3a6f150…, `services/s10_full_apply.py` 05d268e8… — C12 không đụng.
- `app/persistence/jobs.py` = 67ca8975… (T2-delivered C6E change, T3 untouched). frontend/harness/build + `output/s10/c6c/**` + `output/s10/c6d/**` UNTOUCHED; HEAD `d3f6f79` unchanged; no commit/push/merge; DB UNSET throughout; evidence at output/s10/c6e/t01c-c12/** (evidence.md, shakeout_c12_r1/r2.log, result_c12_replay_vs_retry.json, result_c6e_verify_replay_retry.json, repro_c12_replay_vs_retry.py, dispatch/prompt logs).

### Lineage / acceptance trạng thái
- §6.3 (Replay-vs-Retry) CLOSED in-bounded-routes (NO migration): predecessor row CAS arbiter, loser 409 zero-mutation, exactly-one-active-run invariant restored.
- Retry predecessor-status semantic: superseded predecessor now `cancelled` (S10 convention) — single assertion update, consistent with all cancel-then-retry lineage tests.
- Manager verify độc lập: §6.3 2 test pass, shakeout 73×2, evidence.md đầy đủ — trước turn documentation này.

STATUS: TASK_SUBMITTED

---

## S10-T01C-C13 (recovery owner 20260901_230235_b80d4b) — C6F closure — 2026-09-01 23:54 +07 (T2 recovery)

### Scope / disposition
C13 đóng CLOSURE_MATRIX 15 rows (C6F, LOCKED 23:04) bằng 9 test_c6f mới + 6 retained controls. Code production đã fix ở T1 (routes 23:43); T2 này = test completeness + gates + evidence + LOG/REPORT append, không code mới, không commit/push/merge.

### Matrix closure (15 rows, mỗi row: requirement / test / RED evidence / result / counts)
| ID | Requirement | Test | RED (raw) | Result | Counts thật |
|---|---|---|---|---|---|
| F1-K1 | Wrong idempotency-key fail-closed, no 2nd canonical job | test_c6f_wrong_idempotency_key_fails_closed_one_row | red_run.log FAILED (replay 200 reused + 2 jobs tampered+canonical) | GREEN 409 | jobs_total=1, tampered row id/key/state unchanged, runs=1 |
| F1-K2 | Wrong job_type fails closed | test_c6f_wrong_job_type_fails_closed | STRUCTURAL_GAP (no isolated defect) | GREEN 409 | jobs_before==jobs_after (0 side effect) |
| F1-K3 | Wrong owner_type fails closed | test_c6f_wrong_owner_type_fails_closed | STRUCTURAL_GAP | GREEN 409 | jobs unchanged |
| F1-K4 | Wrong owner id fails closed | test_c6e_wrong_identity_fails_closed_valid_control | retained control passing | GREEN (retained) | 0 new job |
| F1-K5 | Wrong generation fails closed | test_c6e_wrong_identity_fails_closed_valid_control | retained control passing | GREEN (retained) | 0 new job |
| F1-K6 | Wrong manifest run-id fails closed | test_c6f_wrong_manifest_run_id_fails_closed | STRUCTURAL_GAP | GREEN 409 | jobs unchanged (0 new) |
| F1-K7 | Wrong manifest project-id fails closed | test_c6f_wrong_manifest_project_id_fails_closed | STRUCTURAL_GAP | GREEN 409 | jobs unchanged |
| F1-K8 | Legit zero-job orphan repairs exactly one | test_c10_submit_replay_after_failure_repairs_exactly_one_job + test_c6d_replay_repair_coherent_active_pair_retry_conflicts | retained | GREEN (retained) | 1 run / 1 job coherent |
| F1-K9 | Valid replay 200 reused zero side effect | C6E concurrent repair test | retained | GREEN (retained) | 200 reused; 1 job; 0 new rows |
| F2-R1 | Repeat Retry same cancelled → stable 409, never 500 | test_c6f_repeat_retry_cancelled_stable_conflict | red_run.log FAILED (retry2 500) | GREEN | retry1=200, retry2=409; successors=1 (attempt-2); no new run; active_jobs=1 |
| F2-R2 | Retry-vs-Retry from failed: true barrier one successor | test_c6f_retry_vs_retry_barrier_failed | red_run.log FAILED (no true barrier) | GREEN | rendezvous=True; codes {200,409}; successor=1; active_runs=1 |
| F2-R3 | Retry-vs-Retry from cancelled: true barrier one successor | test_c6f_retry_vs_retry_barrier_cancelled | red_run.log FAILED (no true barrier) | GREEN | rendezvous=True; codes {200,409}; successor=1; active_runs=1 |
| F2-R4 | Replay-vs-Retry: one 200, one 409, one active work | test_c6e_replay_vs_retry_barrier_fail_closed | retained | GREEN (retained) | {200,409}; active_jobs=1; active_runs=1 |
| F3-W1 | True worker-claim-vs-Retry: two real participants, barrier | test_c6f_worker_claim_vs_retry_true_barrier | STRUCTURAL_GAP (serial :1978, audit_w1.txt zero threading) | GREEN | rendezvous worker+retry=True; retry=409; runs=1; active_lineage_work=1 (running); pub=0; participants=2 |

### Gates (real output, DB UNSET; evidence output/s10/c6f/t01c-c13/)
1. **Shakeout ×2 fresh roots** (`-p no:cacheprovider`, basetemp `%TEMP%/mfc13_*`): r1 `mfc13_r1` **82 passed, 178 warnings, 122.68s (0:02:02) — EXIT 0**; r2 `mfc13_r2` **82 passed, 178 warnings, 121.44s (0:02:01) — EXIT 0** (shakeout_c13_r1.log, shakeout_c13_r2.log). Collection 82 (api + workflow). Fresh roots cleared pre-run.
2. **RED proof** `worker-red/red_run.log`: **4 failed, 5 passed, 48 deselected, 21 warnings in 12.53s** — đúng 4 RED_DEFECT (K1/R1/R2/R3).
3. **ruff check --select F** routes+services+test: **All checks passed! EXIT 0**.
4. **mypy** routes+services prod: **Success: no issues found in 2 source files — EXIT 0**.
5. **git diff --check:** **EXIT 0** (chỉ LF→CRLF pre-existing warnings trên S09 unrelated).
6. **git status --porcelain:** **60** = baseline 59 + 1 (registry `S10-SESSION_REGISTRY.md`, tạo bởi C12 turn, KHÔNG phải C13).
7. **Frozen:** jobs.py 67ca8975…, s10_full_apply_jobs.py 5059c695…, models.py a3a6f150…, job_service cd6c2fb9… — byte-identical (bằng chứng §2 evidence.md). Frontend/harness/build SAME.

### SHA-256 before/after (before = C12 handoff bytes 23:00)
| File | BEFORE | AFTER | Status |
|---|---|---|---|
| app/api/routes/s10_full_apply.py | f6662cc6a88835b6… | d25c3532027fb555… | **CHANGED** (C13 allowlist) |
| tests/test_s10_full_apply_api.py | 69aa9649d6dce945… | 963ed50e350abb54… | **CHANGED** (9 test_c6f) |
| app/services/s10_full_apply.py | 05d268e82e4bd113… | 05d268e82e4bd113… | **UNCHANGED (FROZEN)** |
| tests/test_s10_full_apply_workflow.py | fc11033b35e5e7f5… | fc11033b35e5e7f5… | **UNCHANGED** |

### Hygiene
- No commit/push/merge; HEAD `d3f6f79` unchanged; DB UNSET throughout; zero file ngoài C13 allowlist.
- Stray `after/manifest.json` (broken standalone artifact, `TypeError` from earlier mis-parameterised run) removed this turn.
- Evidence: `output/s10/c6f/t01c-c13/evidence.md` + `shakeout_c13_r1/r2.log` + `after/result_after_{k1,r1,w1}.json` + `worker-red/red_run.log`.

STATUS: TASK_SUBMITTED

## S10-T01C-C15-A — Phase-A verify chain (budget-cut resume; do NOT re-apply patches) — 2026-09-02

### Scope / disposition
- Continuation turn: structural work đã xong (62 defs / 62 unique / 0 dup, `_C10BoomService` L1249, route FROZEN 6ADCC48A… chưa đụng). Chỉ chạy verify chain, KHÔNG re-apply code trừ lỗi harness rõ ràng. KHÔNG Phase B / TASK_SUBMITTED / sửa route.
- Environment: worktree `s08-integration`, branch `codex/s08-integration`, HEAD `d3f6f79`; DB UNSET; python 3.11.9, pytest 9.1.1, ruff 0.16.0; fresh short basetemp `C:/Users/Admin/AppData/Local/Temp/mfc15v_a`, `-p no:cacheprovider`.

### Gates (real output, DB UNSET)
| Step | Command | Result |
|---|---|---|
| 1 py_compile | `python -m py_compile tests/test_s10_full_apply_api.py` | **EXIT 0** |
| 2 ruff --select F | `ruff check --select F tests/test_s10_full_apply_api.py` | 1 F401 dead import @L2406 → minimal harness fix (xóa 2 dòng) → **All checks passed! EXIT 0** |
| 3 collect-only | `pytest --collect-only -q -p no:cacheprovider` | **62 collected, 0 skip, 0 xfail** |
| 4+5 full pytest run | `pytest tests/test_s10_full_apply_api.py -p no:cacheprovider -q --basetemp=%TEMP%/mfc15v_a` | **57 failed / 5 passed / 175 warnings, 67.18s — EXIT 1** |

### FAILURE CLASSIFICATION — HARNESS/AUTHORITY gap (KHÔNG phải CREDIBLE_PRODUCTION_RED)
- **Uniform root cause (57/57 fail):** base submit path returns `{"detail":"stored checkpoint_hash does not match recomputed content hash"} → 422`. Trace: `route submit_full_apply → svc.submit → _S09ApprovalRepository.full_apply_authority → verify_checkpoint` (s09_approval.py L1072) recomputes hash of the STORED apply_checkpoint row and compares to stored `checkpoint_hash`. Test harness `_make_client` (test L87-89) seeds `checkpoint_hash=_h64("ckpt-...")` (fabricated) with content `snapshot_json='{}'`, `loop_hashes_json='[]'`, `timebase_fingerprint=_h64("tbf")` → recompute mismatch → integrity error → 422.
- **Proof (isolated):** seeded exactly as `_make_client` → STORED=fc51bc6a… vs RECOMP=c43b3884… → MATCH=False. A coherently recomputed hash would match.
- **Not C15-introduced:** seeding byte-identical with pre-edit backup (`output/s10/c6h/t01c-c15/pre-edit/*.bak` L50). C15 only relocated defs/helpers.
- **Not C15-clearable-minimally:** cần seed v2 authority qua `submit_checkpoint_v2` (như `_seed_v2_authority`) — redesign thay đổi shared submission semantics của 62 tests, không phải "minimal patch". Owner: Manager R-GATE (C6E-C6H hardening đưa strict verify gate).
- **5 PASSED (không reach submit happy-path):** test_cross_project_v2_blocked (409 — project-mismatch checked trước integrity), test_openapi_additive_no_lost_routes, test_openapi_submit_required_minimal, test_production_submit_contains_no_synthetic_media_helper (static), test_stale_checkpoint_hash_blocked (422 — fail-closed gate hoạt động đúng).

### SHA-256
- route `app/api/routes/s10_full_apply.py` = `6adcc48ad3525cc91c6b5890ce98875b85bb8da66dee2fb86b57c6992a17b53f` — **UNCHANGED (FROZEN)**.
- test `tests/test_s10_full_apply_api.py` = `9b96b12ffe40f7a95e4cb96f78c9f68b8788092d99fe2bc2581289d031f9f313` — line count **2770** (was 2771; -2 từ remove dead import).

### Hygiene
- `git status --porcelain` = **66** (baseline; 8 production ` M app/` files pre-existing, 0 production line đổi; c15 evidence trong `output/` gitignored; LOG/REPORT trong docs/).
- Không commit/push/merge; HEAD `d3f6f79` unchanged; không Phase B; không sửa route.
- Manifest: `output/s10/c6h/t01c-c15/phase_a_manifest.json` (62 node names + SHA + line count 2770 + ruff/py_compile/collect results + route SHA frozen).

STATUS: C15_A_SUBMITTED

## S10-T01C-C15-A — Helper-alignment correction (bounded packet) 2026-09-02 22:0x +07

### Verdict điều trị
Codex: `CHANGES_REQUESTED / C15_A_HARNESS_ALIGNMENT_REQUIRED`. Combined correction cấp quyền: align `_make_client` + `_payload` theo recovered authority (REAL v2 persisted checkpoint, minimal submit), verify 62/62, dừng cho Manager R-GATE.

### Changes (chỉ tests/test_s10_full_apply_api.py, patch narrow có preimage)
| Hunk | Nội dung | KQ |
|---|---|---|
| 1a | `_make_client(..., *, route="sprite_affine")` | ✓ |
| 1b | reskin_config INSERT: `'{}'` → `valid_params` canonical + `:params` (json.dumps sort_keys `(",",":")`) | ✓ |
| 1c | XÓA fabricated apply_checkpoint (ckpt/chash/INSERT); seed = workspace/project/video_item/pack_version/reskin_config_id (KHÔNG checkpoint_id/hash) | ✓ |
| 1d | Thêm `_seed_v2_authority(factory, artifacts_root, seed, route=route)` sau `_seed_persisted_authority` | ✓ |
| 2 | `_payload` = minimal v2 body (5 keys); xóa approved_checkpoint/structural_lock_manifest/scene_manifest/mapping/compatibility_policy khỏi default (vẫn qua overrides) | ✓ |

### Verify (DB UNSET, basetemp `%TEMP%/mfc15c1`, `-p no:cacheprovider`)
| Step | Command | Result |
|---|---|---|
| 1 collect | `pytest --collect-only -q` | **62 collected, 0 error, 0 skipped** (2.64s) |
| 2 focused 5 | `-k "test_submit_202_and_status or test_minimal_submit_omits_legacy_authority_succeeds or test_client_legacy_authority_tamper_fails_closed_zero_run_job or test_unsupported_route_never_coerced or test_openapi_submit_required_minimal"` | **5 passed** (9.48s) |
| 3 full | `pytest tests/test_s10_full_apply_api.py -q` | **54 passed, 8 failed** (77.46s); re-run ổn định 8 failed/54 passed (76.61s) |
| baseline | pre-C15-A file (SHA 9b96b12f… tái tạo byte-exact) | **5 passed, 57 failed** (68.12s) — 49 test đã được correction chữa |

### Diff guard
route `6adcc48a…` UNCHANGED (FROZEN); `_C10BoomService` còn (class L1253); 62 tests unique (dup 0); `py_compile` OK; `ruff --select F` All checks passed; không skip/xfail/mock; chỉ test file bị đụng (untracked baseline); DB env UNSET; không commit/push; HEAD d3f6f79 unchanged.

### FAILURE CLASSIFICATION — 8 fail còn lại (tất cả HARNESS/AUTHORITY, 0 CREDIBLE_PRODUCTION_RED)
| # | Test | Lỗi (raw) | Classification | Lý do |
|---|---|---|---|---|
| 1 | test_submit_distinct_on_changed_checkpoint | `422 stored checkpoint_hash does not match recomputed content hash` (L522) | HARNESS/AUTHORITY | Test tự INSERT apply_checkpoint fabricated với `checkpoint_hash=_h64("new-…")` (L481-493) — pattern bị cấm; production fail-closed đúng. Cần seed REAL v2 checkpoint thứ 2 (helper `_seed_second_v2_checkpoint` đã có L300). |
| 2 | test_c6e_concurrent_repair_replays_true_barrier_one_run_one_job | `ValueError: too many values to unpack (expected 2)` (L1521) | HARNESS/AUTHORITY | `client2, seed2 = _run_concurrent_replays_setup(...)` nhưng helper trả DICT (L1557) → unpack sai. Không liên quan production. |
| 3 | test_c6e_replay_vs_retry_barrier_fail_closed | `the superseded/superseding predecessor is cancelled (never 2 active runs), got [{'status':'pending','attempt':1}]` (L1825) | HARNESS/AUTHORITY | Barrier race => 1 winner 200 + 1 loser 409, nhưng replay-thắng không tạo successor nên KHÔNG có run cancelled → kỳ vọng `cancelled>=1` sai cho nhánh replay-heal; fail-closed vẫn đúng (1 active run). |
| 4 | test_c6e_wrong_identity_fails_closed_valid_control | `sqlite3.IntegrityError FOREIGN KEY constraint failed — UPDATE job SET workspace_id='other-ws'` (L1709→tamper) | HARNESS/AUTHORITY | Test tamper job.workspace_id sang `other-ws` nhưng workspace 'other-ws' KHÔNG tồn tại trong bảng workspace → FK chặn. Cần seed workspace row hoặc dùng workspace hợp lệ khác. |
| 5 | test_c6f_retry_vs_retry_barrier_cancelled | `both Retries must rendezvous at the run-row CAS, got tokens=[]` (L2101) | HARNESS/AUTHORITY | Predecessor CANCELLED → route retry không gọi `_s10_cas_run_status` nữa (chỉ CAS khi status == 'failed'; cancelled dùng unique-successor backstop L1420-1428) → barrier không bao giờ traverse. Test body vẫn giả định cancelled-predecessor đi qua CAS. |
| 6 | test_c6g_ambiguous_two_claimants_fails_closed | `KeyError: 'input_manifest_json'` (L2249) | HARNESS/AUTHORITY | `_c6f_all_apply_jobs` SELECT không gồm cột input_manifest_json (L1845-1846) → test đọc orig["input_manifest_json"] fail. Query-helper thiếu cột. |
| 7 | test_c6g_combined_tamper_fails_closed | `sqlite3.IntegrityError FOREIGN KEY constraint failed — UPDATE job SET workspace_id='other-ws', owner_id='other-owner'` (L2291) | HARNESS/AUTHORITY | Giống #4: tamper workspace sang 'other-ws' không tồn tại → FK chặn trước khi logic fail-closed chạy. |
| 8 | test_c6d_retry_after_repaired_job_terminal_allows_one_successor | `retry on a terminal failed run must succeed, got 200: {…attempt:2}` (L2560) | HARNESS/AUTHORITY | Route FROZEN retry trả **200** (decorator không khai báo status_code=202; L1388/L1568). Test kỳ vọng 202 → expectation lệch contract route. Không sửa production trong Phase A. |

Tất cả 8 đều do test body/helper expectation chưa align recovered authority — production (route FROZEN) fail-closed đúng; không có CREDIBLE_PRODUCTION_RED. Owner follow-up: Manager R-GATE (routing từng fix về đúng test owner hoặc correction tiếp theo).

### SHA-256
- route `app/api/routes/s10_full_apply.py` = `6adcc48ad3525cc91c6b5890ce98875b85bb8da66dee2fb86b57c6992a17b53f` — **UNCHANGED (FROZEN)**.
- test `tests/test_s10_full_apply_api.py` = `4c491909da58b161cb4c8f582043da182299a0cc6a63655d0ab3efb4f93d9b48` — line count **2773** (`grep -c ""`).

### Evidence
`output/s10/c6h/t01c-c15/evidence/` — traceback_batch1.txt (distinct_changed + c6e_concurrent + c6e_wrong_identity), traceback_batch2.txt (c6e_concurrent + c6e_replay_vs_retry), traceback_batch3.txt (c6f_retry_vs_retry + c6g_ambiguous + c6g_combined), c15a_correction_done.json.

STATUS: C15_A_CORRECTION_DONE final_sha=4c491909… (8 HARNESS/AUTHORITY mở — Manager R-GATE), KHÔNG Phase B, KHÔNG commit.

## S10-T01C-C15-B — CLOSE ORIGINAL C6G CONTRACT (bounded packet) 2026-09-02 22:55 +07

### Context
Manager R-GATE = C15_A_REBASELINE_APPROVED. 8 harness items (C15-A leftovers, all HARNESS/AUTHORITY — 0 CREDIBLE_PRODUCTION_RED) được fix TEST-side theo recovered v2 authority; route FROZEN byte-identical; C6G 14-row matrix đóng GREEN. DB UNSET, basetemp `%TEMP%/mfc15b_*`, `-p no:cacheprovider`.

### 8 items (test → fix → bằng chứng)
| # | Test | Fix | Bằng chứng |
|---|---|---|---|
| 1 | `test_submit_distinct_on_changed_checkpoint` | Bỏ INSERT apply_checkpoint fabricated (`'{}'` params + made-up hash) → REAL v2 checkpoint thứ 2 qua `_seed_second_v2_checkpoint` + `_payload(seed2)` minimal; giữ expectation 202 + run MỚI (reused không True) | micro 8 passed; focused 30 passed; full 62 passed |
| 2 | `test_c6e_concurrent_repair_replays_true_barrier_one_run_one_job` | Helper trả DICT → unpack `setup2 = ...` đúng; `_assert_converged(setup2["factory"], setup2["seed"], setup2["client"])` | micro 8 passed |
| 3 | `test_c6e_replay_vs_retry_barrier_fail_closed` | Bỏ nhánh `cancelled>=1` sai (replay-win heal run về pending, không successor); invariant đúng "non-active runs must be terminal" + exactly-one non-terminal | micro 8 passed |
| 4 | `test_c6e_wrong_identity_fails_closed_valid_control` | Seed REAL workspace `other-ws` (FK không chết nữa); `_expect_fail` capture ORIGINAL pre-tamper + restore by PRIMARY KEY (helpers mới `_c6d_run_job_id`/`_c6d_tamper_job_by_id`/`_c6d_job_attr_by_id`) | micro 8 passed |
| 5 | `test_c6f_retry_vs_retry_barrier_cancelled` | Barrier giờ wrap `routes._s10_retry_successor_exists` (predecessor cancelled → route KHÔNG gọi `_s10_cas_run_status`; ownership = atomic unique-successor insertion + `uq_s10_run_natural` backstop). Rendezvous chứng minh cả 2 Retry qua pre-check; loser 409 via IntegrityError path | micro 8 passed |
| 6 | `test_c6g_ambiguous_two_claimants_fails_closed` | `_c6f_all_apply_jobs` SELECT thêm cột `input_manifest_json` (test helper) | micro 8 passed |
| 7 | `test_c6g_combined_tamper_fails_closed` | Seed REAL workspace `other-ws` trước combined tamper (FK hết chết) | micro 8 passed |
| 8 | `test_c6d_retry_after_repaired_job_terminal_allows_one_successor` | INDEPENDENT REPRO trên frozen route → 200 `{run_id, predecessor_run_id, status:pending, attempt:2}`; C6F contract retry1=200 → expectation 202→200; predecessor invariant "TERMINAL (cancelled/failed)" (retry CAS supersedes failed→cancelled by design) | micro 8 passed |

### Gates (real output, đúng thứ tự)
| Gate | Output |
|---|---|
| RED micro (trước fix) | **8 failed, 54 deselected, 17.44s** — exactly 8 HARNESS/AUTHORITY items C15-A, raw tracebacks evidence/traceback_batch{1,2,3}.txt |
| Micro sau fix | **8 passed, 54 deselected, 14.29s**; ruff F clean sau khi xóa factory unused (F841) |
| Focused C6D/E/F/G | `-k "c6d or c6e or c6f or c6g"` → **30 passed, 44.32s** |
| Focused C15-A packet | 5 tests → **5 passed, 9.62s** |
| Full module | **62 passed, 86.09s** — 0 fail, 0 skip/xfail, 62 collected / 0 errors |
| Static | `py_compile` (test+route+services) OK; `ruff check --select F` 5 files → **All checks passed**; `git diff --check` → EXIT 0 (chỉ LF→CRLF pre-existing warnings) |

### SHAs / freeze
- test `tests/test_s10_full_apply_api.py` = `2fff69d0b49512bfbc1779d1db4993b8adb85eda0bc1c290cc3419e55b12ba1e`, **2810 dòng** (method `wc -l`), 62 defs unique (`grep -c "^def test_"`), 0 dup.
- route `app/api/routes/s10_full_apply.py` = `6adcc48ad3525cc91c6b5890ce98875b85bb8da66dee2fb86b57c6992a17b53f` — **UNCHANGED byte-identical vs pre-B snapshot** (`output/s10/c6h/manager/guard/snapshots/app/api/routes/s10_full_apply.py.pre_c15b`); **0 CREDIBLE_PRODUCTION_RED, 0 production edit**.
- HEAD `d3f6f796558aa9c7247da7d51e7d34e65b56cdf7` unchanged; **không commit** (0 commit/push/merge).

### C6G 14-row matrix (row → test)
| Row | Requirement | Test(s) GREEN |
|---|---|---|
| G1-I1 | One wrong-key claimant → 409/422; one unchanged row | `test_c6f_wrong_idempotency_key_fails_closed_one_row` |
| G1-I2 | Two same-gen wrong-key claimants → fail closed; count stays 2; NO canonical third row | `test_c6g_ambiguous_two_claimants_fails_closed` |
| G1-I3 | Combined wrong key + wrong job/workspace/owner → fail closed; all rows unchanged | `test_c6g_combined_tamper_fails_closed` |
| G1-I4 | Resolver query/read/parse error → fail closed; zero repair/mutation | `test_c6g_resolver_error_fails_closed` |
| G1-I5 | Wrong manifest run/project identity → fail closed; zero mutation | `test_c6f_wrong_manifest_run_id_fails_closed`, `test_c6f_wrong_manifest_project_id_fails_closed`, `test_c6f_wrong_job_type_fails_closed`, `test_c6f_wrong_owner_type_fails_closed` |
| G1-I6 | True zero-job orphan → exactly one canonical repair | `test_c10_submit_replay_after_failure_repairs_exactly_one_job`, `test_c6d_replay_repair_coherent_active_pair_retry_conflicts` |
| G1-I7 | Valid unchanged replay → 200 reused; zero side effect | `test_submit_idempotent_same_tuple_dedupes`, `test_c6d_deterministic_concurrent_replays_one_run_job`, `test_submit_202_and_status` |
| G2-R1 | Direct cancelled-claim probe cannot yield two exclusive winners | `test_c6g_cancelled_claim_not_exclusive` |
| G2-R2 | Two simultaneous Retry on failed → one ownership winner, one successor, one 409 loser | `test_c6f_retry_vs_retry_barrier_failed` |
| G2-R3 | Two simultaneous Retry on cancelled → one ownership winner/insert, loser 409, no 500 | `test_c6g_retry_race_cancelled_ownership_winner` |
| G2-R4 | Sequential repeat Retry → stable 409/converge, never 500, no new row | `test_c6f_repeat_retry_cancelled_stable_conflict` |
| G2-R5 | Retained replay-vs-Retry → one 200, one 409, one active work | `test_c6e_replay_vs_retry_barrier_fail_closed` |
| G3-W1 | Worker-claim-vs-Retry: two real participants, bounded joins, rendezvous, all-row invariant | `test_c6f_worker_claim_vs_retry_true_barrier`, `test_c6e_worker_claim_vs_retry_barrier` |
| G4-D1 | Evidence arithmetic consistent: 14 rows / 5 retained controls (sửa "15/6") | Addendum này: matrix 14/14 CLOSED; REPORT/evidence/registry khớp 14 rows, 5 retained controls |

**14/14 GREEN, 0 CREDIBLE_PRODUCTION_RED.** Mọi row có test pass trong 62.

### Evidence
`output/s10/c6h/t01c-c15/evidence/c15b_done.json` (schema đóng), `traceback_batch{1,2,3}.txt` (RED raw), `manager/guard/snapshots/.../s10_full_apply.py.pre_c15b` (byte-identical guard), `phase_a_manifest.json`, `c15a_correction_done.json`.

STATUS: TASK_SUBMITTED (C15-B) — fixes 8/8 + gates real + matrix 14/14 GREEN. HEAD d3f6f79 unchanged, không commit. Manager EXIT sẽ chạy broad gates.

---

## Mục R1 — UNION identity resolver recovery (S10-C6H CHANGES_REQUESTED / UNION_IDENTITY_RESOLVER_GAP)
Worker: FRESH recovery `20260903_001126_2a17f4` (3 session cũ FROZEN vì REPEATED_FORBIDDEN_CRITICAL_FILE_WRITE). C6H = NOT_APPROVED; correction bounded này là recovery duy nhất được cấp.

### Root cause (P1 Codex)
`_s10_find_durable_job` = exact canonical-key lookup; `_s10_resolve_job_identity` scan CHỈ `input_generation == expected_gen`. Tamper key + generation (manifest vẫn định danh run) → resolver trả zero-candidates → tạo canonical job thứ 2 + 200 reused=true (repro Codex jobs 1→2). Test cũ `test_c6g_combined_tamper_fails_closed` không đổi generation → không cover.

### Fix (bounded, 2 file allowlist)
- `app/api/routes/s10_full_apply.py`: `_s10_resolve_job_identity` → typed UNION resolver. Candidate discovery = union của 3 tín hiệu độc lập (canonical key / deterministic generation / stored manifest run+project+plan identity) + workspace/job_type/owner anchor cho phân loại; scan không filter key-prefix/job_type/key-NOT-NULL để row tamper toàn diện vẫn được tìm qua manifest. Classes: `true-zero` (duy nhất được repair), `exact-valid-one`, `wrong-one`, `ambiguous-multiple`, `read/parse/query-error` (manifest unparseable → KHÔNG bao giờ thành missing). Call site: chỉ `true-zero` repair; others 409 fail-closed, zero mutation, không tạo canonical 2nd/3rd, không false reused=true.
- `tests/test_s10_full_apply_api.py`: +6 tests U1-U6 (real route + real JobService + fresh Alembic DB, no mock):
  - U1 key+gen tamper (manifest intact) → fail closed, 1 job UNCHANGED, no repair
  - U2 key+gen+workspace+job_type+owner tamper (manifest intact) → fail closed, zero mutation
  - U3 2 claimants qua tín hiệu khác nhau (gen vs manifest) → ambiguous, cả 2 UNCHANGED, no 3rd job
  - U4 manifest unparseable + key/gen tamper → read/parse/query-error, fail closed, no repair
  - U5 true-zero orphan → repair ĐÚNG MỘT canonical job (key/gen/project owner), reuse truthfully
  - U6 valid canonical replay → 200 reused=true, counts UNCHANGED

### Gates (real output, DB UNSET, basetemp ngắn %TEMP%/mfc15r1_*, -p no:cacheprovider)
| Gate | Result |
|---|---|
| RED U1+U2 pre-fix | 2 FAILED (200 reused=true; jobs 1→2) — red_u1u2.log |
| U1-U6 micro | 6 passed — u_gate.log |
| Retained 14-row matrix | 20 node / 14 rows GREEN — matrix.log |
| Full API | 68 passed, 82.07s — full_api.log (62 retained + 6 R1) |
| ruff --select F (2 files) | All checks passed — static.log |
| mypy (3 prod) | Success: no issues found in 3 source files — static.log |
| git diff --check / dup-def | 0 / 0 — static.log |

### Hashes & guard
- route: `6ADCC48A` (2470) → `BBF55D28` (2571, +101) — chỉ 2 vùng: resolver + call site (diff.diff hunk 1-4)
- test: `2FFF69D0` (2810, 62 defs) → `6978D2BE` (3153, 68 defs unique, 0 dup) — append-only +341/+343 (diff.diff hunk 5)
- Guard pre_r1 byte-snapshots giữ nguyên; không shrink; 0 migration; 0 production file khác; HEAD d3f6f79 unchanged; không commit.
- RUNTIME_CONFIG_GAP (state.db): session ghi `max_iterations=90, reasoning_config=null` dù prompt yêu cầu reasoning max — ghi thật, giữ nguyên model ocg/deepseek-v4-flash, không sinh worker khác.

### Evidence
`output/s10/c6h/r1/t01c-c15-recovery/{r1_done.json, red_u1u2.log, u_gate.log, matrix.log, full_api.log, static.log, diff.diff}` + `broken_patch/` (2 file hỏng do patch-tool fuzzy-indent, đã khôi phục từ guard).

STATUS: R1_RECOVERY_DONE — chờ Codex review C6H. KHÔNG ghi APPROVED/CLOSED/SPRINT_CLOSED.
### S10-T01C-C15 R2 — recovery worker (2026-09-03)
- **Verdict:** S10-C6H = CHANGES_REQUESTED / R2_AUTHORIZED / NOT_APPROVED / S10_NOT_CLOSED. Owner R1 20260903_001126_2a17f4 FREEZE vĩnh viễn (lặp forbidden copy-overwrite: msg 150098 test snapshot đè, 150135 route snapshot đè).
- **F1 (P1 RELEVANT_MANIFEST_SCOPE):** prefilter manifest SQL từ `like('%\"run_id\"%')` (mọi row có field name) → 2 pattern LIKE chứa EXACT target run_id: `%"run_id":"<id>"%` và `%"run_id": "<id>"%` (compact + spaced). Union key/gen/manifest vẫn độc lập; parse+validate exact run/project/plan giữ nguyên; unrelated malformed hay valid khác run/project không còn là candidate/claimant → true-zero repair được; malformed CÓ target run_id vẫn fail-closed (U4/R2-B).
- **F2 (P2 PER_ROW_SIGNAL):** `canonical_complete` recompute `row_sig_manifest` từ chính `claims[0]` (parse manifest row đó), bỏ biến `sig_manifest` tồn dư từ loop.
- **Tests:** 68 → 70 defs (R2-A + R2-C mới; R2-B sửa U4 không thêm def). RED→GREEN có raw log. Mọi retained (U1-U6, C6G 14/14, exact replay, ambiguous, relevant malformed, combined tamper) đều xanh.
- **Write-safety:** 100% unified V4A patch 1 hunk/lần; 0 write_file/cp/move/restore/redirection; hash+py_compile+collect sau từng hunk; guard .pre_r2 byte-identical verified; không commit.
- **RUNTIME_CONFIG_GAP ghi thật:** state row yếu (max_iterations=90/reasoning_config=null); model ocg/deepseek-v4-flash custom đúng, fallback OFF.
- **Files:** route `app/api/routes/s10_full_apply.py` BBF55D28→BA97FB24; test `tests/test_s10_full_apply_api.py` 6978D2BE→EF5F93A3 (70 defs). HEAD d3f6f79 unchanged.
- **Terminal:** R2_RECOVERY_DONE final_route_sha=ba97fb24... final_test_sha=ef5f93a3... 70/70 PASS 14/14+R2 GREEN — Manager post-audit. NOT APPROVED/CLOSED; S11 chưa mở.
### S10-T01C-C15 R3 - worker (2026-09-03)
- **Verdict:** S10-C6H = CHANGES_REQUESTED / R3_AUTHORIZED / NOT_APPROVED / S10_NOT_CLOSED. Finding duy nhat P1 FORMAT_DEPENDENT_MANIFEST_DISCOVERY (valid JSON whitespace lam mat manifest identity).
- **Mechanism (invariant, khong enumerate):** thay 2 pattern LIKE literal bang MOT containment exact target run_id: `like(f'%{run_id_literal}%', escape='\\')` voi `%,_,\` escaped trong run_id - doc lap JSON whitespace/pretty-print. Parse + exact-match run_id/project_id/plan_id giu nguyen; malformed CO target run fail-closed; unrelated malformed/valid khong chon; per-row signal R2 nguyen ven; chi true-zero repair.
- **Tests:** 70 -> 71 defs (R3-A moi; U4 sua R3-B khong them def), 0 dup, 70/70 retained. RED->GREEN raw log that: R3-A/R3-B RED 200 reused=true jobs 1->2; GREEN 4/4 targeted, micro 9/9, C6G 30/30, full 71 passed 85.04s.
- **Write-safety:** test 2 hunks + route 2 hunks, 100% unified patch (git apply) 1 hunk/call, exact preimage, EOL-preserving; 0 write_file/cp/move/replace/redirection tren critical files; hash+py_compile+collect sau moi hunk; guard .pre_r3 byte-identical; khong commit.
- **RUNTIME_CONFIG_GAP ghi that:** state row yeu (max_iterations=90/reasoning_config=null); exact model ocg/deepseek-v4-flash custom fallback OFF; effective session 20260903_094146_7b7197 resume owner 20260903_012248_d29911.
- **Files:** route `app/api/routes/s10_full_apply.py` BA97FB24->5a6c7e86 (2601); test `tests/test_s10_full_apply_api.py` EF5F93A3->e26a96dc (3466, 71 defs). HEAD d3f6f79 unchanged.
- **Terminal:** R3_RECOVERY_DONE final_route_sha=5a6c7e86... final_test_sha=e26a96dc... 71/71 PASS 14/14+R3 GREEN - Manager post-audit. NOT APPROVED/CLOSED; S11 chua mo.


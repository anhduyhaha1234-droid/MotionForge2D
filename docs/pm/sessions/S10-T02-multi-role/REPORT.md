# REPORT — S10-T02 Multi-role independent apply

STATUS: TASK_SUBMITTED

Owner session: current CLI worker (model meta, reasoning max, fallback OFF) — C1-FIX correction
Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration (branch codex/s08-integration, HEAD d3f6f79 + T01A/T01B/T01C dirty)
Started: 2026-08-28T01:05+07
Submitted: 2026-08-28T01:12+07
Corrected: 2026-08-28T13:49+07 (C1-FIX)

## Outcome
1-4 role mappings render independently while preserving contact, visibility and z-order graph edges.

## Files changed (allowlist)
- app/services/s10_multi_role_apply.py (new, 1288 lines) — pure service: RoleMapping, RoleAttempt, ContactEdge, ZOrderEdge, VisibilityEvent, S10MultiRoleService dispatch per role, group fixture, scheduling invariance. C1: map controlled_redraw cho fg_table nhu sprite_affine semantics.
- app/services/s10_full_apply.py (bounded edit) — lazy import of S10MultiRoleService (additive, no contract change).
- app/workflow/s10_full_apply_jobs.py (bounded edit) — dispatch_per_role_via_worker hook on workflow layer.
- tests/test_s10_multi_role_apply.py (new, 38 tests) — covers all 5 binary acceptance bullets + 8 real-adapter tests (C1: +controlled_redraw route evidence).
- docs/pm/sessions/S10-T02-multi-role/TASK.md, LOG.md, REPORT.md (task-owned).
- output/s10/t02/** (isolated evidence).

Forbidden untouched: migrations, models.py (beyond pre-existing T01 dirty), frontend, S11/S13, renderer J1 files, data/**.

## Binary acceptance evidence

1. Group fixture — `build_group_fixture()` requires 2+ chars, 1 prop with contact_anchor, 1 fg occluder, distinct layer_ids (no flattening). Tests: TestGroupFixture 9 passed.
2. Per-role pinned evidence — each role uses its own mapping_id/pack_version/route/attempt (attempt 1, content_hash, chunk_id, state completed). Tests: TestPerRolePinnedEvidence 4 passed.
3. Isolation — role A failure (fail_chunk_index 0) does not mutate role B artifact ID/hash/route; retry with new pack only mutates target role. Tests: TestIsolationOnFailure 3 passed; verified in both service and workflow layer.
4. Contact/z-order survival — `_check_edge_survival(overlap_context=True)` reports all_survive True across chunk boundaries (chunk_frames 24, overlap 2/4, twoshot stitch). Zero unexplained visibility events enforced at build_plan (reason required). Tests: TestContactZOrderSurvival 5 passed.
5. Scheduling invariance — permuting role_order yields same plan_hash/canonical_inputs_hash and same canonical_output_identity (sorted artifacts by role_id). Tests: TestSchedulingInvariance 4 passed + Validation 5 passed.

## Tests

- pytest tests/test_s10_multi_role_apply.py -v -p no:cacheprovider — 38 passed x2 (25.81s, 25.65s), isolated basetemp, MOTIONFORGE_DATABASE_URL=UNSET.
- Evidence: output/s10/t02/pytest_run1.log, pytest_run2.log (post-C1; pre-C1 was 2 failed / 36 passed due to unsupported controlled_redraw route)
- Direct adapter evidence: 8 artifacts (4 roles x2 chunks) decodable mp4 non-empty, backend ffmpeg-nvenc-*, decoded_sha 64, frames_rendered == decoded_frame_count.

## Linters

- Ruff scoped (write-set): E501 P2 documented only (58 E501 line-too-long in s10_multi_role_apply.py + test file — pre-existing style in T01C not fixed beyond scope). F* 0 (no other error categories in T02 files). Allowed per spec ("E501 P2 documented if any").
- Evidence: output/s10/t02/ruff_scoped.log
- mypy scoped: Success on app/services/s10_multi_role_apply.py.
- Evidence: output/s10/t02/mypy.log
- git diff --check: 0
- Evidence: output/s10/t02/git_diff_check.log

## CORRECTION C1-FIX — controlled_redraw wiring for layer_fg_table

Finding: GROUP_FIXTURE_SPEC dung controlled_redraw cho layer_fg_table nhung _build_render_request_for_chunk + _execute_via_adapter chi wire sprite_affine + pose_swap -> raise Unsupported route -> 2/38 fail (test_real_executor_produces_decodable_media_per_role_chunk + test_real_executor_isolation_one_role_failure, role_fg_table failed=True, 0 artifacts).

Fix (bounded trong app/services/s10_multi_role_apply.py):
- _build_render_request_for_chunk: add `elif route == "controlled_redraw"`: cung file/anchor/affected_region nhu sprite_affine — `<layer_id>.png` (kind sprite), `ReplacementAsset(path=cand, kind="sprite")`, error message update to `only sprite_affine/pose_swap/controlled_redraw are wired`.
- Anchor + affected_region va source_timebase giu nguyen nhu sprite_affine (shared logic sau branch).
- Affine keyframes: `if route in ("sprite_affine", "controlled_redraw"):` (1 affine keyframe tai frame=start).
- _execute_via_adapter: add `elif route == "controlled_redraw": SpriteAffineAdapter()` — thuc thi qua SpriteAffineAdapter nhung giu route evidence = controlled_redraw (return dict route = request.route, khong map ve sprite_affine).
- Test delta bounded: tests/test_s10_multi_role_apply.py:657 stale assertion `in {"pose_swap", "sprite_affine"}` -> bo sung `"controlled_redraw"` (giua dung evidence semantics).
- Frozen renderer untouched (khong sua app/adapters/renderer/**, khong mo S11/S13, khong migration/model).

Verification C1:
- grep _build_render_request_for_chunk co controlled_redraw: True; _execute_via_adapter co controlled_redraw: True.
- 38 passed x2 (truoc fix 36 passed + 2 failed).
- Adapter nonzero: role_fg_table 2 artifacts controlled_redraw, file size ~1500 bytes each, backend ffmpeg-nvenc-sprite-affine, decoded_sha != 0*64, frames_rendered == decoded_frame_count.
- Ruff scoped F* 0, E501 P2 allowed, mypy Success, git diff --check 0.

## Risks / carry-forward

- E501 line-length is P2 only; safe to enforce 100 cols in later pass if desired.
- Pre-existing T01 dirty (models.py 290 lines, app/api/app.py 7 lines, untracked s10 files) remains; T02 did not extend it.
- controlled_redraw hien thuc thi qua SpriteAffineAdapter (CPU deterministic composite + ffmpeg encode) — semantics giong sprite_affine (same file/anchor/region). Neu S11 muon tach route rieng thi chi can doi adapter mapping trong _execute_via_adapter, khong anh huong evidence.

## Verification checklist

- [x] grep s10_multi_role trong 2 ham co controlled_redraw
- [x] pytest tests/test_s10_multi_role_apply.py -v -p no:cacheprovider --basetemp=$(mktemp -d) PASS x2 (38 passed x2)
- [x] Ruff scoped write-set (F* 0, E501 P2 documented only)
- [x] mypy relevant modules Success (scoped s10_multi_role_apply.py)
- [x] git diff --check 0
- [x] git status --porcelain only allowlist + pre-existing T01A/B/C artifacts
- [x] No migration/model, frontend, renderer J1, data/channels changes
- [x] Adapter nonzero (role_fg_table controlled_redraw decodable, non-empty file)

Manager will verify.

## CORRECTION C2-R1 — close J1 gate (46/46 x2 on fresh roots)

Finding (execute, not plan): on-disk state of this lane already satisfies the J1
requirement (full tests/test_s10_multi_role_apply.py PASS x2 on fresh basetemp,
no skip/xfail, no assertion loosening). The 9 failures listed in the manager
packet were root-caused and verified fixed in code with file:line (see LOG
C2-R1 section 1-6); additional ruff F841 dead locals (per_role_attempts,
role_order, layer_order) removed this resume (production path only, 1392 lines
now, AST-verified, no logic change).

Verification C2-R1 (all commands actually run this resume, MOTIONFORGE_DATABASE_URL
UNSET throughout, verified env count 0):
- pytest tests/test_s10_multi_role_apply.py -v -p no:cacheprovider --override-ini="addopts=" --basetemp=C:/Users/Admin/AppData/Local/Temp/s10c2r1-fx1 -> 46 passed in 28.01s
- pytest tests/test_s10_multi_role_apply.py -v -p no:cacheprovider --override-ini="addopts=" --basetemp=C:/Users/Admin/AppData/Local/Temp/s10c2r1-fx2 -> 46 passed in 28.11s
- FAILED/ERROR grep count 0, "skipped" count 0 in both logs; pytest summary "46 passed" (no skipped/xfailed tokens).
- J1-v4 renderer freeze manifest re-hash: 13/13 match (script over manifest files, output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json).
- Retained regression pytest tests/test_s09*.py -q: 417 passed / 4 failed — 4 failures are pre-existing alembic migration-head assertions (b3c4d5e6f7a9 vs a10b11c12d3e), outside renderer surface, not caused by this lane (J1 13/13 intact; only s10_multi_role_apply.py touched).
- Ruff scoped: F* = 0 (E501 P2 documented + UP037 pre-existing only).
- Mypy scoped: Success: no issues found in 1 source file.
- git diff --check: 0 lines.
- git status --porcelain: 48 entries, same allowlist + pre-existing set as preflight.

Files changed (allowlist): app/services/s10_multi_role_apply.py (production, 3 dead locals removed); tests/test_s10_multi_role_apply.py (unchanged this resume). Forbidden untouched: migrations, models, frontend, renderer J1, S11/S13.
Evidence: output/s10/c2/t02-c2/c2-r1-init-pytest.log, c2-r1-run2-pytest.log, c2-r1-postedit-x1.log, c2-r1-postedit-x2.log, c2-r1-s09-regression.log, c2-r1-ruff.log, c2-r1-mypy.log, c2-r1-diffcheck.log.

STATUS: TASK_SUBMITTED

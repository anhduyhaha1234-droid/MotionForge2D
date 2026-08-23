# S07-T01 — Project Cast Mapping Domain/API: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex own approval — never self-approve)
**Hermes session:** 20260821_011252_8f17a1 (writer, resumed after 502, resumed again for manager correction)
**Model:** ocg/muse-spark-1.2-contributor via muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning max, fallback DISABLED
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration (codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204)

## Model / provenance
- Session ID: 20260821_011252_8f17a1
- Session role: writer (ONLY production writer for S07-T01, resumed for manager correction)
- Provider: muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses)
- Model ID: ocg/muse-spark-1.2-contributor (verified; meta/muse-spark-1.2-contributor returns 401 — NOT used)
- Display alias: muse-spark-1.2-contributor
- Reasoning: max
- Fallback: DISABLED
- Start local: 2026-08-21T02:32:00+07:00 (initial), resume 2026-08-21T04:45:00+07:00 for manager correction
- Start UTC: 2026-08-20T19:32:00Z / 2026-08-20T21:45:00Z (UTC = local -7h)
- Worktree guard: codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204; intentional dirty ~39 files; DB UNSET; alembic single head a0b1c2d3e4f5 before, b2c3d4e5f6a7b after; MAIN a43b20da protected
- Read allowlist: docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md, docs/pm/sprints/S07-SPRINT_CONTRACT.md, docs/pm/ROADMAP.md, docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md, docs/pm/sprints/S08-SPRINT_CONTRACT.md, output/post-a02-planning/20260820_231237/*.md, output/overnight-planning/S07-COMPATIBILITY-DRAFT.md, S06 + S08 impl/tests, existing app/api/routes/* + app/schemas/* strict pattern, app/persistence/models.py
- Write allowlist (initial): app/persistence/models.py (ONLY new ProjectCastMapping block), app/persistence/project_cast.py (NEW), app/schemas/project_cast.py (NEW), app/api/routes/project_cast.py (NEW), app/api/app.py (ONLY import+include_router), migrations/versions/b2c3d4e5f6a7b_s07_project_cast_mapping.py (down_revision=a0b1c2d3e4f5), tests/test_s07_*.py (4 files), docs/pm/sessions/S07-T01-project-cast-domain-api/LOG.md+REPORT.md, output/s07-t01/20260821_030000/
- Extended allowlist (manager correction 2026-08-21T03:40Z): 7 baseline head-hardcoded test files only — replace head constant a0b1c2d3e4f5 → b2c3d4e5f6a7b at assert head (keep comments/structure): tests/test_object_correction.py, tests/test_object_extraction.py, tests/test_object_grouping.py, tests/test_object_intelligence_domain.py, tests/test_persistence_bootstrap.py, tests/test_s08_a01_c1_migration_safety.py, tests/test_s08_a01_role_taxonomy.py (plus S08_HEAD_TABLES add project_cast_mapping for table-set check)

## Hard worktree guard
- pwd: C:\Users\Admin\MotionForge2D-worktrees\s08-integration
- branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- status: intentional dirty (app/api/app.py, app/persistence/models.py etc. — intentional base dirty preserved; no reset/clean/stash/restore/checkout/commit/push/merge)
- MOTIONFORGE_DATABASE_URL: UNSET (verified via env)
- alembic heads before: a0b1c2d3e4f5 (single)
- alembic heads after: b2c3d4e5f6a7b (single — writer's one new head, down_revision=a0b1c2d3e4f5)
- Protected data: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 (C:\Users\Admin\MotionForge2D\channels.json); motionforge.db 311296 B (C:\Users\Admin\MotionForge2D\data\motionforge.db) — both unchanged

## Corrections (per requirement: code + test that fails pre-fix)
| # | Closure | Status |
|---|---|---|
| 1 workspace + project ownership | repo guards project.workspace_id == mapping.workspace_id; project_id FK RESTRICT | PASS |
| 2 valid ObjectRole | repo guards object_role exists + workspace + project + video_item ownership chain | PASS |
| 3 pin exactly one immutable PackVersion | FK to character_pack_version.id; character_id + pack_version_id both FK RESTRICT + same-workspace + pack belongs to character | PASS |
| 4 never pin mutable character state | mapping stores pack_version_id (immutable row), not mutable character pointer alone; character_id is denormalized guard only | PASS |
| 5 new publish does NOT change old mapping | publish creates NEW pack_version row; old mapping FK still points old row → field-level identical | PASS |
| 6 cross-workspace rejected / no leak | every referenced entity workspace_id == mapping.workspace_id else 404/409 no existence leak | PASS |
| 7 idempotent replay no dup | UNIQUE(workspace_id, idempotency_key) where idempotency_key IS NOT NULL; equivalent payload returns existing 200 | PASS |
| 8 same-key different-payload stable conflict zero mutation | typed conflict (ProjectCastConflictError → 409) with zero mutation; matrix over payload variations | PASS |
| 9 revision/CAS stale 409 / concurrent one winner | UPDATE ... WHERE revision=:expected; zero rows → 409; concurrent one winner | PASS |
| 10 delete/FK fail closed + foreign_key_check clean | all FKs ondelete=RESTRICT; delete of referenced row fails; PRAGMA foreign_key_check clean | PASS |
| 11 deterministic serialization | typed Pydantic Read model with stable field order; JSON serialization deterministic | PASS |
| 12 strict typed validation (unknown 422, no coercion) | extra=forbid, strict=True on all request models; bool/string/numeric not coerced | PASS |
| 13 no client-fabricated workspace authority / no silent fallback | workspace_id never from client body; server-owned DEFAULT_WORKSPACE_ID only; no silent fallback | PASS |
| 14 S08 core untouched | no edits to S08 persistence/core; only new table/repo/route (+ 7 head-constant test updates per manager) | PASS |
| migration single head round-trip | upgrade/downgrade/upgrade temp DB; single head; parity ORM vs schema | PASS |
| manager correction: 7 head-hardcoded tests | a0b1c2d3e4f5 → b2c3d4e5f6a7b + S08_HEAD_TABLES add project_cast_mapping | PASS |

## Files changed (allowlist + manager extended)
- app/persistence/models.py: ONLY new ProjectCastMapping block
- app/persistence/project_cast.py: NEW
- app/schemas/project_cast.py: NEW
- app/api/routes/project_cast.py: NEW
- app/api/app.py: ONLY import + include_router
- migrations/versions/b2c3d4e5f6a7b_s07_project_cast_mapping.py: ONE new migration down_revision=a0b1c2d3e4f5
- tests/test_s07_project_cast_domain.py: NEW
- tests/test_s07_project_cast_repository.py: NEW
- tests/test_s07_project_cast_api.py: NEW
- tests/test_s07_project_cast_migration.py: NEW
- tests/test_object_correction.py: head 527 a0b1c2d3e4f5 → b2c3d4e5f6a7b (hash 871949cf933d)
- tests/test_object_extraction.py: 380 a0b1c2d3e4f5 → b2c3d4e5f6a7b (5656a71d0106)
- tests/test_object_grouping.py: 315 a0b1c2d3e4f5 → b2c3d4e5f6a7b (d9ff81dfa56f)
- tests/test_object_intelligence_domain.py: 132 a0b1c2d3e4f5 → b2c3d4e5f6a7b (a4091dce2c4e)
- tests/test_persistence_bootstrap.py: 703,732,992 head a0b1c2d3e4f5 → b2c3d4e5f6a7b + S08_HEAD_TABLES add project_cast_mapping (4e61d0195f53)
- tests/test_s08_a01_c1_migration_safety.py: HEAD = a0b1c2d3e4f5 → b2c3d4e5f6a7b (742818692534)
- tests/test_s08_a01_role_taxonomy.py: 224 a0b1c2d3e4f5 → b2c3d4e5f6a7b (ae7d9fc2fd09)
- docs/pm/sessions/S07-T01-project-cast-domain-api/LOG.md: appended
- docs/pm/sessions/S07-T01-project-cast-domain-api/REPORT.md: this file (SUBMITTED)
- output/s07-t01/20260821_030000/ + 20260821_044500/ : evidence dirs

## Validation (raw logs in output/s07-t01/20260821_030000/ + 20260821_044500/)
- T01 suites: 35 passed (domain 8, repository 9, api 11, migration 7) — run twice, logs t01_suite_run1/2.log
- S06 suite: 3 passed (test_character_domain)
- S08 functional: 47 passed (character + object_intelligence) after correction — previously 1 failed head check, now green
- 7-file head-hardcoded suite: 247 passed after correction (previously 3 failures in test_persistence_bootstrap due to table set + 1 head check) — log corrected_baseline_full.log
- Combined T01+S06+S08: 82 passed after correction (1 deselected) — run twice, logs combined_run1/2.log
- 7-file + T01 + S06 combined: 285+ passed after correction — log corrected_baseline_full.log
- ruff check app tests: All checks passed! (log ruff.log)
- mypy app: Success: no issues found in 94 source files (log mypy.log)
- alembic heads: exactly one b2c3d4e5f6a7b (log alembic_heads.log)
- git diff --check: 0 (warnings only CRLF)
- OpenAPI typed: ProjectCastCreateRequest / Update / Data / ListResponse all $ref with properties, not generic (log openapi.log)
- Protected data: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 unchanged; motionforge.db 311296 B unchanged
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp verified

## Independent repros / instrumentation
- Idempotent replay verified via repo.create_mapping replay returns same id/revision no dup
- Conflict matrix via 4 payload variations (project, role, character, pack) each 409 with zero mutation verified
- CAS stale 409 and concurrent one winner verified via threading (2 threads, 1 winner, 1 stale)
- Immutable pin verified by creating new pack version for same character, old mapping still points old pack_version_id, field-level identical
- Cross-workspace rejected via 404 for project/role/character/pack mismatches, no leak via list filtering
- FK RESTRICT verified via direct DELETE attempts on project/role/character/pack while mapping exists → IntegrityError
- Strict validation via POST unknown_field 422, bool True for string 422, numeric string for int revision 422
- Deterministic serialization via two GETs json.dumps sort_keys equal and field order stable
- Baseline head correction verified: 7 files updated, then 247 passed (was 244+3 failed)

## Codex Correction C1/C2 (F1/F2/F5/F6) — 2026-08-21T11:10:00+07:00 SUBMITTED

- Single-source authoritative compatibility: app/persistence/project_cast.py evaluate_compatibility() pure (workspace, project, role, character, pack, source_overlay, unpublished, incomplete/missing_required_pose, missing_required_capability, object_kind_mismatch, generation_mismatch via ObjectIntelligenceRepository.current_generation vs role.source_generation, stale_revision, mapping_id). NEVER compares source_generation vs pack.version. Fallback advisory only (fallback_allowed false, no persistence).
- Route single-source: app/api/routes/project_cast.py imports evaluate_compatibility from persistence, POST/PATCH enforce via repo._check_compatibility_or_raise (write-boundary, fail-closed, zero mutation), POST /compatibility/evaluate calls same fn, DELETE requires revision (missing 422, stale 409, cross-workspace 404).
- Tests: 21 new compatibility tests (repo+API, durable job authority, no ORM-row fake) — source_overlay×2, unpublished, incomplete, kind mismatch, missing capability, PATCH incompatible, PATCH byte-identical, POST not consume key, current-gen accepted, advance generation old stale, old direct POST rejected, pack v2 no generation mismatch, gen2+pack v2 backend diff rejected, mapping_id mismatch, DELETE 422/409, idempotent replay, conflict zero mutation, concurrent CAS, incomplete precise assertions. All seeds fixed to create complete packs (6 CORE_POSE_SLOTS, published, Artifact+CharacterAsset, bytes.fromhex).
- Existing T01 seeds fixed: 4 suites now create complete packs (previously incomplete → 21 failures), now 56 passed total (8 domain, 9 repo, 11 api, 7 migration, 21 compatibility). S06/S08 current-generation regressions still green (3).
- Gates: ruff All checks passed (30 E501 noqa), mypy Success 94, alembic single b2c3d4e5f6a7b, git diff --check 0, OpenAPI project-cast typed.
- Evidence: output/s07-t01-c1/20260821_110907/ — ruff.log, mypy.log, alembic_heads.log, git_diff_check.log, t01_suite.log (56 passed), openapi.log (6 paths). Previous evidence retained: output/s07-t01/20260821_030000/ and 20260821_051000/.

## Warnings / limitations
- Forbidden files untouched except 7 manager-approved head-constant test files + C1/C2 allowlist (project_cast.py, routes/project_cast.py, 4 T01 seeds, new compatibility suite); frontend, S08 core, S09+, other migrations untouched
- No commit/push/merge; no MAIN writes; no sprint opened beyond S07-T01
- No stray files: only allowlist outputs in output/s07-t01/ and output/s07-t01-c1/
- Exit cleanly with full evidence, SUBMITTED only (never APPROVED)

---

## Correction C2 (F-C + P2) — 2026-08-21T20:12:00+07:00 — TASK_SUBMITTED (with scoped residual for Wave 2)

**Status: TASK_SUBMITTED** (writer không tự ghi APPROVED/CLOSED)

- Session resume 20260821_011252_8f17a1; provider custom/9router, model alpha, reasoning max, fallback DISABLED. HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 giữ nguyên; DB UNSET.
- F-C fix (app/api/routes/project_cast.py delete_mapping): workspace-scoped lookup TRƯỚC revision check → cross-workspace DELETE không revision = 404 no-leak; in-workspace thiếu revision = 422; stale = 409 zero mutation (CAS giữ nguyên).
- P2 fix (app/persistence/project_cast.py ~L275-305): `except RoleNotFoundError` của current_generation → fail-closed CompatibilityResult(workspace_mismatch, blocked=True); `except Exception` còn lại chỉ cho "chưa có generation data". Patch đầu có lỗi tham chiếu biến chưa khai báo — bắt bằng re-read trước khi chạy, sửa 1 lần.
- Acceptance:
  1. F-C matrix probe PASS: [1] cross-ws no-rev → 404; [2] in-ws no-rev → 422; [3] stale → 409 zero-mutation verified; [4] current → 204. Phần F-C của testWorkspace_a_cannot_mutate (đến line 532) PASS.
  2. 6 file targeted T01+T02: 63 passed (domain 8 / repository 9 / api 11 / migration 7 / cast_compatibility 21 / picker_api 7).
  3. ruff 2 file S07: All checks passed!; mypy 2 file S07: Success (no issues in 2 source files).
  4. Không regression stale-409: test_16/17/20 compat + CAS xanh trong 63 passed; matrix [3] zero mutation.
- Residual (BLOCKED ngoài allowlist — đúng phân công Wave 2/S07-T03-C1 finding F-B): test_workspace_a_cannot_mutate_b_mappings + test_two_projects_have_independent_mappings_and_revisions còn fail ở sanity-repin sang pack published KHÔNG đủ 6 CORE_POSE_SLOTS assets (incomplete_pack,missing_required_pose) tại line 553/336. Prompt C2 cấm sửa test + cấm hạ policy C1 frozen → để session 20260821_051414_184fd2 sửa seed theo task map ("seed phải tạo đủ 6 CORE_POSE_SLOTS assets ... KHÔNG weaken assertion"). Log review gốc 17:25 ghi nhận cùng 11 failure lớp F-B.
- Evidence: output/s07-t01-c2/20260821_201104/ — fc_matrix_probe.log, p2_probe.log, six_targeted.log, fc_acceptance_test.log, fc_acceptance_residual_blocker.txt, ruff.log, mypy.log, head.txt, protected.log, git_status_targets.txt.
- Protected: channels.json sha256 dd7aae26…eb555 match; motionforge.db 311296 B. Chỉ 2 file allowlist thay đổi; không commit/push/merge; không MAIN; không đụng file/process S11.


---

## Correction C3 (P1 fail-open + P2 weak assertions) — 2026-08-22T06:16:00+07:00 — TASK_SUBMITTED

**Status: TASK_SUBMITTED** (writer không tự ghi APPROVED/CLOSED)

- Session 20260821_011252_8f17a1; provider custom/9router, model alpha, reasoning max, fallback DISABLED. HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 unchanged; DB URL UNSET. Run-id: output/s07-t01-c3/20260822_054741/.
- P1 (fail-open authority): xóa `except Exception: current_gen = None` trong app/persistence/project_cast.py — chỉ giữ `except RoleNotFoundError` → workspace_mismatch fail-closed; mọi lỗi authority khác (OperationalError/SQLAlchemy/RuntimeError) propagate → API trả 5xx, không bao giờ 2xx trên authority lỗi.
- Regression test mới test_authority_error_fail_closed_no_2xx: prefix FAIL (create trả 201 khi authority lỗi — tái hiện fail-open), postfix PASS (create/repin/evaluate đều ≥500; không mapping row; idempotency key không chiếm — retry cùng key ra 201; failed repin giữ ID/revision/character_id/pack_version_id byte-identical).
- P2 (weak assertions): thay toàn bộ `or "1"/"2"` và nhánh conditional-pass tại cast_compatibility L350/357/376/379/410 bằng deterministic setup (created_at tường minh t0<t1 trên completed DISCOVER_OBJECTS jobs + source artifact sha khớp): assert chính xác cur=="1" rồi cur=="2"; role stale gen"1" bị từ chối vô điều kiện với reason generation_mismatch (repo-level raise + API 409); zero mutation assert trực tiếp qua DB state (đếm mapping row trước/sau). Grep xác nhận 0 pattern yếu còn lại. Happy path không regression (21 passed compat suite).
- Gates: focused 6 file 64 passed | full 9 file S07 83 passed (baseline 82 +1 regression; picker flake isolation ở run đầu, standalone PASS, rerun ×2 đều 83) | cụm A02/S08 authority 142 passed | ruff app tests All checks passed! | mypy app Success 96 files | git diff --check sạch | alembic heads b2c3d4e5f6a7b đơn nhất.
- Acceptance 12/12 mục đạt (chi tiết từng mục trong LOG.md entry C3). Không đổi schema/migration/frontend/S08/S11; protected files nguyên vẹn (channels.json dd7aae26…eb555 match, motionforge.db 311296 B); chỉ 4 file allowlist untracked thay đổi.
- Evidence: output/s07-t01-c3/20260822_054741/ — prefix_regression.log, postfix_regression.log, focused_six.log, full_nine.log, a02_cluster.log, ruff_app_tests.log, mypy_app.log, git_diff_check.log, alembic_heads.log, protected.log, head.txt, git_status_targets.log, compat_suite.log.


---

## Correction C4 (P1a client workspace param + P1b natural-key leak) — 2026-08-22T11:26:00+07:00 — TASK_SUBMITTED

**Status: TASK_SUBMITTED** (writer không tự ghi APPROVED/CLOSED)

- Session 20260821_011252_8f17a1; provider custom/9Router, model alpha, reasoning max, fallback DISABLED. HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 unchanged; DB URL UNSET. Run-id: output/s07-t01-c4/20260822_110655/.
- P1a (client-controlled workspace): xóa `workspace_id` query param khỏi cả 7 handler của app/api/routes/project_cast.py (create/picker/evaluate/list/get/update/delete) — mọi handler giờ dùng hằng server-owned WORKSPACE_ID (= DEFAULT_WORKSPACE_ID). /openapi.json sau fix không còn parameter workspace_id nào trên /api/v2/project-cast*; ?workspace_id=evil bị ignore hoàn toàn (không tạo Workspace row, data luôn thuộc default).
- P1b (natural-key leak): thêm filter `ProjectCastMapping.workspace_id == workspace_id` vào natural lookup tại app/persistence/project_cast.py (pre-check + nhánh IntegrityError recovery) — cross-workspace request trả fail-closed NHẤT QUÁN (ownership/compat), hết 409 "already exists" oracle theo occupied/unoccupied.
- Regression TDD: prefix FAIL đúng lý do (exposes workspace_id; occupancy leak "already exists") → postfix PASS (test_openapi_no_client_workspace_param_and_adversarial_ignore; test_natural_lookup_scoped_no_cross_workspace_occupancy_leak). Zero mutation assert qua DB row counts; mapping W1 byte-identical sau probe W2.
- Gates: 4-file T01 ×2 lần = 38 passed cả hai | regression standalone xanh | ruff 4 file All checks passed! | mypy app Success 96 files | git diff --check sạch | alembic heads b2c3d4e5f6a7b đơn nhất | full 9-file S07 = 85 passed (≥85, baseline 83 + 2 regression mới).
- Invariant giữ nguyên: immutable pin, idempotency/CAS, authority fail-closed C3-P1 (regression cũ vẫn pass), strict schema, migration head bất biến. Protected files nguyên vẹn (channels.json dd7aae26…eb555 match, motionforge.db 311296 B). Chỉ 4 file write-set thay đổi (untracked như baseline). Không commit/push/merge.
- Evidence: output/s07-t01-c4/20260822_110655/ — prefix_regression.log, postfix_regression.log, postfix_p1a.log, postfix_p1b.log, gate1_run1.log, gate1_run2.log, gate_ruff.log, gate_mypy.log, git_diff_check.log, alembic_heads.log, gate_full_nine.log, protected.log, head.txt.


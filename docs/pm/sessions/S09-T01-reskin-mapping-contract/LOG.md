# S09-T01 — LOG

## Baseline (Manager, 2026-08-22T22:46+07)

- Branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204, dirty 255 entries protected.
- MOTIONFORGE_DATABASE_URL UNSET; alembic single head b2c3d4e5f6a7b.
- Intersection baselines: models.py 065210e5be67…, app.py f289e8592841…, api.ts f4227465a4e9…, job_service.py b3fa769587c5….

## Worker log

(append bởi worker)

## Worker session 20260823_0007 (alpha @ custom, reasoning max)

- [2026-08-23T00:07+07] Hard guard OK: pwd=/c/Users/Admin/MotionForge2D-worktrees/s08-integration; toplevel=C:/Users/Admin/MotionForge2D-worktrees/s08-integration; HEAD=a43b20da742996bafcb2f9d1ac57b10d3f1a5204; branch=codex/s08-integration; git status --short = 259 entries (baseline snapshot: C:/Users/Admin/AppData/Local/Temp/s09t01-baseline-gitstatus.txt).
- [2026-08-23T00:07+07] MOTIONFORGE_DATABASE_URL UNSET (echo rỗng). Toolchain: python 3.11.9, ruff 0.16.0, mypy 2.3.0.
- [2026-08-23T00:07+07] OpenAPI baseline chụp TRƯỚC write đầu tiên: output/s09/s09-t01/20260822_worker_r1/openapi-before.json — 215 paths.
- [2026-08-23T00:07+07] Required reading xong: TASK.md, S09-SPRINT_CONTRACT.md, TASK_MAP.md mục T01+T06 (checkpoint schema-only), models.py (CORE_POSE_SLOTS:134, Job:606, CharacterPackVersion:937, ProjectCastMapping:2069, TimestampMixin:277), project_cast.py (evaluate_compatibility:216, _assert_equivalent_request:449, create_mapping:466, update_mapping:608), routes/project_cast.py (prefix:55, trailing-slash:59-60), migration b2c3d4e5f6a7b (down_revision=a0b1c2d3e4f5 — LƯU Ý: TASK_MAP ghi "migration b2c3d4e5f6a7b" tạo project_cast_mapping; head thực tế = b2c3d4e5f6a7b, khớp TASK.md), test_s07_version_isolation.py (scenarios 5-13,15), test_s07_project_cast_migration.py (parity pattern), conftest.py (_patch_project_root + client), app.py include_router:141, frontend project-cast/index.ts + api.ts pattern.
- [2026-08-23T00:15+07] models.py additive edit 1: appended ReskinConfig + ApplyCheckpoint classes (sau ProjectCastMapping relationships, EOF) + thêm "ApplyCheckpoint","ReskinConfig" vào __all__.
- [2026-08-23T00:20+07] ADDITIVE PROOF (difflib trên file chuẩn hóa CRLF): REAL_REMOVED_LINES=0; mọi class/__tablename__ của HEAD còn nguyên; worktree = core(S07/S08/S11) + đúng 2 khối mới. git diff --numstat = 1539+/0-. ruff+mypy pass trên models.py. LƯU Ý ghi nhận: file models.py pre-edit trong worktree (dirty baseline 255 entries) lớn hơn HEAD commit — dirty state đó là của sprint trước, bảo toàn nguyên vẹn; diff so với HEAD nên đọc là "HEAD + dirty-before + my-additions", proof additive dựa trên difflib removed=0.
- [2026-08-23T00:40+07] Implementation files written: app/persistence/reskin_config.py (repo + fail-closed validate_params; tái sử dụng evaluate_compatibility), app/schemas/reskin_config.py (strict extra=forbid), app/api/routes/reskin_config.py (prefix /api/v2/reskin-configs + trailing-slash variants), app/api/app.py (additive import+include_router — diff chỉ 4 dòng thêm), frontend/src/features/reskin/index.ts (thin client, tsc --noEmit PASS, eslint --max-warnings 0 PASS), migrations/versions/c9d0e1f2a3b4_s09_reskin_config_and_apply_checkpoint.py (down_revision=b2c3d4e5f6a7b, HAI bảng).
- [2026-08-23T00:42+07] alembic heads = c9d0e1f2a3b4 (ĐÚNG 1 head). Migration round-trip smoke trên temp DB: upgrade head → downgrade b2c3d4e5f6a7b → upgrade head OK; version=c9d0e1f2a3b4; reskin_config+apply_checkpoint tồn tại; integrity ok; foreign_key_check=0 rows. (PermissionError khi unlink temp db do engine chưa dispose — file đã xóa bằng rm sau đó; không phải lỗi migration.)
- [2026-08-23T01:20+07] GATES: full S09 suite (domain 26 + api 14 + migration 8) = 48 passed ×2 liên tiếp; ruff check app tests = "All checks passed!"; mypy app = "Success: no issues found in 99 source files"; git diff --check exit 0.
- [2026-08-23T01:22+07] REGRESSION S07 test_s07_version_isolation.py: 9/10 pass, 1 FAIL = test_migration_round_trip_preserves_invariant — NGUYÊN NHÂN: test hard-code head="b2c3d4e5f6a7b" (đúng tại thời điểm viết test S07); sau migration S09 head mới là c9d0e1f2a3b4 nên assert version==head đỏ ở dòng 606. KHÔNG PHẢI lỗi schema/behavior: Part A round-trip byte-identical vẫn đúng với head mới. TASK.md Forbidden: "S07/S08 tests+code (chỉ đọc regression)" → worker KHÔNG được sửa file này → cần quyết định của Manager (sửa head constant trong test S07 thuộc ownership sprint sau/Manager). ĐÃ chạy thay thế theo đúng yêu cầu TASK.md mục Required-test-4: ≥3 test isolation S07 → 6 test isolation (publish-new-pack / still-points-old / not-silently-mutated / explicit-repin / revision-increments / stale-repin) PASS ×2; thêm 6 test CAS/replay PASS ×2. Full suite trừ Scenario 15: 9 passed.
- [2026-08-23T01:24+07] LƯU Ý CHO MANAGER (blocker tiềm ẩn cross-sprint, không thuộc allowlist T01): (1) tests/test_s07_version_isolation.py::test_migration_round_trip_preserves_invariant hard-code head b2c3d4e5f6a7b — sẽ đỏ vĩnh viễn cho đến khi ai đó cập nhật constant sang c9d0e1f2a3b4 (hoặc refactor dùng ScriptDirectory.get_heads()); (2) tests/test_persistence_bootstrap.py S08_HEAD_TABLES chưa gồm reskin_config + apply_checkpoint → test_no_api_cutover_tables + test schema-drift sẽ đỏ ("unexpected tables"); (3) các test khác assert version == "b2c3d4e5f6a7b" (test_object_correction.py:527, test_object_extraction.py:380, test_object_grouping.py:315, test_object_intelligence_domain.py:132, test_persistence_bootstrap.py:705,734,994). Tất cả nằm ngoài allowlist T01 — đề xuất Manager cấp hotfix-scope hoặc đưa vào task kế.
- [2026-08-23T01:30+07] OPENAPI DIFF: paths 215→219, ADDED chỉ 4 path /api/v2/reskin-configs (+trailing-slash variants), REMOVED=0, OP_ADDED on existing paths=[], schemas ADDED 8 (AnchorPoint, OffsetVector, ReskinConfigCreateRequest/Data/ListResponse/UpdateRequest, ReskinParams, ReskinParamsPatch), schemas REMOVED=0 → ADDITIVE THUẦN. Evidence: output/s09/s09-t01/20260822_worker_r1/openapi-before.json + openapi-after.json.
- [2026-08-23T02:35+07] FINAL EVIDENCE (output/s09/s09-t01/20260822_worker_r1/): pytest-final-run1.log + run2.log = 48 passed ×2; ruff.log "All checks passed!"; mypy.log "no issues in 99 source files"; pytest-s07-isolation-run1/run2.log = 6 passed ×2; git-diff-check.log EXIT=0; alembic-heads.log = c9d0e1f2a3b4 (single); migration-roundtrip.log: STEP3 byte-identical True, integrity ok, fk_check 0 rows. Worktree delta so baseline: chỉ 7 path allowlist mới (6 file NEW + frontend/src/features/reskin/), 0 file sửa ngoài models.py/app.py (đã dirty từ baseline, phần edit của worker thuần additive).
- [2026-08-23T02:40+07] REPORT.md viết xong — STATUS: TASK_SUBMITTED (không tự APPROVED). Worker DỪNG tại đây theo protocol. Cross-sprint test constants (S07 Scenario-15 head hard-code, persistence_bootstrap S08_HEAD_TABLES, object_* version asserts) đã liệt kê trong REPORT để Manager quyết định.
- [2026-08-23T02:50+07] FRESH VERIFICATION sau submit (workspace state hiện tại): S09 suite 48 passed ×2 liên tiếp (basetemp verify-r1/verify-r2); ruff "All checks passed!"; mypy "no issues in 99 source files"; git diff --check EXIT=0; alembic single head c9d0e1f2a3b4; frontend tsc --noEmit PASS + eslint --max-warnings 0 PASS; S07 isolation regression 6 passed. Không có code đổi nào sau 2 run — verification khớp evidence đã nộp.

## Worker session SL-2 (2026-08-24, alpha @ custom, reasoning max) — Source-Locked completion

Baseline: HEAD ee10e55a809c (codex/s08-integration), 17 dirty entries (intentional), MDB UNSET, single head d8e9f0a1b2c3 (I01 đã chen giữa c9d0 và PRE).

[SL] IMPLEMENT (allowlist: app/persistence/reskin_config.py, app/schemas/reskin_config.py, app/api/routes/reskin_config.py, frontend/src/features/reskin/index.ts, tests/test_s09_reskin_source_locked_domain.py NEW, tests/test_s09_reskin_config_api.py, tests/test_s09_reskin_migration.py):
- _resolve_lock_pin: fail-closed — manifest phải tồn tại CÙNG workspace; re-validate stored manifest_json qua canonical_manifest_json (corrupt → conflict); recomputed sha256 phải khớp manifest_hash (tamper → hash mismatch conflict); mọi segment route phải thuộc RENDERER_ROUTES (enum authority duy nhất); voided manifest không pin được; lock_policy_version LUÔN derive từ manifest (client hint chỉ được phép khớp).
- create_config: pin optional + idempotent replay so sánh cả pin pair.
- update_config CAS: None=giữ pin, id mới=re-pin (validate lại toàn bộ), ""=unpin cả hai cột; no-op detection gồm pin pair.
- list_renderer_route_evidence: evidence PER SEGMENT từ SegmentRenderRoute (route/anchor/frame/confidence/reasons/provenance) — không phải global score.
- Routes: POST/PATCH truyền structural_lock_manifest_id (model_fields_set cho semantics 3-trạng-thái); GET /{id}/renderer-route-evidence (+ trailing slash).
- Schemas: ReskinConfigCreateRequest/UpdateRequest thêm field additive; ReskinConfigData thêm 2 cột pin; RendererRouteEvidence read model. Frontend mirror + getRendererRouteEvidence().
- FIX BUG THẬT: route evidence truyền nhầm (config_id, workspace_id) ngược thứ tự → 404 'default'; đã sửa + test chứng minh.

[SL] MIGRATION TEST REPAIR (root-caused, không bypass):
1) test import module c9d0 so revision với HEAD mới → so đúng revision của chính nó.
2) downgrade refusal: với I01 chen giữa, chain 2 chân; row PINNED chặn ngay chân d8e9→c9d0 (đậu ở head, atomic); row UNPINNED cho chân 1 đi tiếp, chân 2 refuse → đậu ở c9d0. Thêm test leg-wise riêng ghi nhận hành vi fail-closed end-to-end.
3) ORM parity: cột pin do native ALTER TABLE ADD COLUMN ... REFERENCES ... ON DELETE RESTRICT — SQLAlchemy legacy reflection không báo ondelete cho inline column-level REFERENCES (chỉ table-level CONSTRAINT); RESTRICT vẫn enforce thật ở engine level. Chuẩn hóa _fk_entry so sánh ondelete=None cho FK vào structural_lock_manifest; enforcement parity do test_fk_restrict_fail_closed bảo vệ.

[SL] GATES (mọi lệnh env -u MOTIONFORGE_DATABASE_URL, -p no:cacheprovider):
- Domain S09 gốc 26 passed ×2 | Source-Locked domain 9 passed ×2 | API 15 passed ×2 (14 cũ + 1 mới) | Migration 9 passed ×2 (8 + 1 leg-wise)
- FULL S09 (4 file): 59 passed ×2 (38.00s / 37.46s) → evidence sl-pytest-final-run1.log
- ruff app+tests: All checks passed! | mypy app: Success, 110 source files | git diff --check EXIT=0
- alembic heads: d8e9f0a1b2c3 (head) duy nhất
- OpenAPI: 219 → 221 paths, ADD 2 path evidence (+trailing slash), REMOVED_VS_PREV=[] thuần additive → openapi-after-sl.json
- Regression S07: 10 passed (nguyên file, live-head discovery — KHÔNG cần deselect nữa)
- T00 regression (domain+migration): 20 passed
- Frontend: tsc --noEmit EXIT=0, eslint --max-warnings 0 EXIT=0

[SL] Git status sau viết: 25 entries (baseline phiên 17 + 8: TASK-SL.md untracked, test SL mới untracked, 6 file allowlist modified). Không commit/push/stash. MAIN không đụng.

[SL-FINAL 2026-08-24] REPORT.md ghi xong — STATUS: TASK_SUBMITTED. Toàn bộ gate xanh (59×2, ruff/mypy/diff-check/OpenAPI additive/single-head d8e9f0a1b2c3/S07+T00 regression). STOP — không tự APPROVED, không làm thêm.

## Worker session C1 (2026-08-24, alpha @ custom, reasoning max) — S09-T01-C1 pinned route evidence isolation

Preflight: RULES_LOADED (180 dòng) + review F6 (P1) + fast-track prompt §6 đọc trọn. HEAD ee10e55a809c @ codex/s08-integration, dirty 83 entries (Wave A workers song song — không đụng file của họ), MDB UNSET, alembic head đã dịch lên b3c4d5e6f7a9 (do worker khác, ngoài write-set).

[C1] ROOT CAUSE (F6 xác nhận): list_renderer_route_evidence lọc `manifest_id == pin OR manifest_id IS NULL` → row legacy/unattributed của cùng video lọt vào pinned evidence; T01 test cũ chỉ tạo NULL-row nên codify leak.

[C1] FIX (app/persistence/reskin_config.py — duy nhất file impl trong write-set):
1. Bỏ nhánh `OR IS NULL` — chỉ nhận row có structural_lock_manifest_id == manifest đang pin (strict equality).
2. Thêm bộ lọc thời gian bền vững: `_as_comparable_dt(r.created_at) <= _as_comparable_dt(config.created_at)` — row tạo SAU pin bị loại kể cả khi đúng manifest (frozen evidence surface). Normalize tzinfo trước so sánh (SQLite strip offset vs ORM aware-UTC).
3. Không đụng models/migrations/API/frontend (forbidden paths tôn trọng đầy đủ); projection thứ hai (s09_demo_compare._route_evidence_from_manifest) gọi qua repo method này nên tự hưởng isolation.

[C1] TESTS (tests/test_s09_reskin_source_locked_domain.py +4 test F6, 13 tổng):
- test_f6_evidence_excludes_null_manifest_rows: NULL-manifest row (ghi TRƯỚC pin) → bị loại; đúng-manifest row → giữ.
- test_f6_evidence_excludes_other_manifest_rows: m2 khác manifest cùng video → bị loại khỏi evidence của config pin m1.
- test_f6_evidence_excludes_rows_created_after_pin: row bound đúng manifest nhưng ghi SAU created_at của config → bị loại.
- test_f6_evidence_stable_across_fresh_db_reload: 2 session mới liên tiếp trên cùng committed DB → identical result set.
- Điều chỉnh test cũ test_renderer_route_evidence_per_segment: record_render_route giờ PHẢI truyền structural_lock_manifest_id=manifest.id (đúng contract mới — chính là behavior F6 yêu cầu).
- Bài học root-cause trong quá trình debug: filter pin-time loại luôn row ghi sau pin → mọi legitimate evidence phải được persist TRƯỚC moment pin.

[C1] GATES:
- Focused ×2 (basetemp riêng): 13 passed / 13 passed → output/s09/20260823_sprint_full/t01-c1/f6-focused-run{1,2}.log
- Regression T01 domain+API+migration+T04 demo-compare ×2: **72 passed** cả hai run → f6-regression-run1.log (+run inline r2)
- ruff (file write-set): All checks passed! · mypy reskin_config.py: Success · git diff --check EXIT=0

[C1] FINDINGS NGOÀI WRITE-SET (attribution cho Manager/Codex — KHÔNG tự sửa):
1. tests/test_s09_t02_adaptive_pose_swap_nvenc.py::test_route_evidence_api_read_model_matches_persisted_row ĐỎ vì fixture INSERT reskin_config với created_at hard-code '2026-08-24T00:00:00' trong khi route row dùng utc_now() thật (~15:xx) → theo spec F6 mới row đó là POST-PIN và bị loại ĐÚNG. Owner T02 phải backdate created_at của route row hoặc forward-date config fixture.
2. 3 test T02 NVENC khác đỏ với "output_media escapes workspace_root" — do validate_for_render MỚI (renderer_contract.py +306 dòng, uncommitted của T02-C1 worker) chặn output ghi ra %TEMP% basetemp. Thuộc T02 owner, không liên quan T01-C1.
3. mypy app: app/workflow/s09_demo_jobs.py:203 '"object" not callable' — select_route export qua lazy __getattr__ (PEP 562) khiến mypy suy type `object`. File untracked thuộc worker khác; đề xuất eager-import hoặc `if TYPE_CHECKING` re-export trong renderer_routes/__init__.py.

[C1] STATUS: TASK_SUBMITTED — STOP, không self-APPROVED. Write-set audit: chỉ app/persistence/reskin_config.py + tests/test_s09_reskin_source_locked_domain.py + output/s09/20260823_sprint_full/t01-c1/** + LOG/REPORT append. Không commit/push/stash (stash push/pop kiểm chứng mypy pre-existing đã restore nguyên vẹn, hash xác minh).

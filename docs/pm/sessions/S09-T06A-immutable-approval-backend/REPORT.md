# S09-T06A — Immutable approval/checkpoint backend — REPORT

**Status: TASK_SUBMITTED**
Worker: Hermes implementation worker (provider custom @ 9Router, model alpha, reasoning max, fallback disabled). Session: 20260824_120141_312e9e. Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration (branch codex/s08-integration, HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0). MOTIONFORGE_DATABASE_URL UNSET trong toàn bộ phiên; mọi test dùng temp SQLite riêng.

## Outcome-by-outcome evidence

### Outcome 1 — ApplyCheckpoint persistence/service/schema/routes hoàn chỉnh
- NEW `app/services/s09_approval.py` — `S09ApprovalRepository`: submit/get/list/verify/replay_probe/conflict_probe. Snapshot freeze TOÀN BỘ: pin pack versions (`pack_version_ids_json`), CompatibilityPolicy evidence/version (`snapshot.compatibility_policy` = policy_version + manifest ref + per-segment renderer routes từ SegmentRenderRoute), StructuralLockManifest ref (pin column + snapshot), accepted warnings/overrides, demo artifact refs, correction history refs.
- NEW `app/schemas/s09_approval.py` — typed strict payloads (`extra=forbid`, fail-closed ở schema boundary), route Literal DERIVED từ RENDERER_ROUTES.
- NEW `app/api/routes/s09_approval.py` — POST /api/v2/s09-approvals (201 created / 200 replayed), GET one / list, POST {id}/verify, POST replay-probe, POST conflict-probe.
- Persistence: tái sử dụng bảng `apply_checkpoint` hiện có — KHÔNG schema change.

### Outcome 2 — Quyết định migration: KHÔNG cần migration mới
Đọc kỹ ApplyCheckpoint hiện có (models.py:2281-2335 + migration c9d0e1f2a3b4 + additive pin columns d8e9f0a1b2c3): ĐỦ mọi field outcome yêu cầu. → Không thêm migration, không đụng models.py. Bằng chứng:
- Live head discover TRƯỚC và SAU task: `python -m alembic heads` → `b3c4d5e6f7a9 (head)` (khớp TASK.md, single head, unchanged).
- `tests/test_s09_t06_backend_migration.py::test_apply_checkpoint_columns_zero_removed` — column set == frozen pre-state (removed=0 VÀ added=0).
- `test_orm_parity_with_storage` — ORM columns == storage columns (zero drift); các field approval cần đều có trên ORM.
- `test_round_trip_head_parent_fk_clean` — round-trip b3c4d5e6f7a9 ↔ d8e9f0a1b2c3, PRAGMA foreign_key_check == 0 tại mọi bước.

### Outcome 3 — Immutable semantics
- Checkpoint tạo xong KHÔNG được mutate: revision CHECK `revision = 1`; repository không có path UPDATE/DELETE.
- Hash verified: `checkpoint_hash` = sha256 canonical JSON của (config id/revision, pins, pack versions, loop hashes, timebase fingerprint, snapshot gồm note/warnings/overrides/refs/policy/routes). Serving + verify recomputed TỪ ROW LƯU — không join live.
- Later changes không mutate: `test_later_source_change_does_not_mutate` — sau khi approve, cập nhật reskin config (params + revision bump) và supersede pinned manifest bằng version mới → stored row BYTE-IDENTICAL, hash vẫn verified, revision freeze =1, policy_version trong snapshot giữ nguyên v1.
- Tamper fail-closed: sửa snapshot_json trực tiếp SQL → verify=False ("does not match"), GET → 500 S09ApprovalIntegrityError (`test_hash_verify_pass_and_tamper_fail`, `test_verify_endpoint_pass_and_tamper_fail`).

### Outcome 4 — Blockers fail closed
- Correction ref pending/cancelled → ApprovalBlockedError (409), ZERO mutation (`test_pending_correction_blocks_zero_mutation`, `test_cancelled_correction_blocks`, API `test_blocked_pending_correction_409_zero_mutation`). Chỉ applied resolve được.
- Warnings/overrides explicit-only: nằm trong request, hash vào checkpoint; override thiếu evidence từ applied correction → blocked, không implicit accept (`test_override_without_explicit_evidence_blocks`).

### Outcome 5 — Replay idempotent; conflict/CAS zero mutation ×2 chiều
- Equivalent replay → SAME row created=False (`test_equivalent_replay_returns_same_row`, `test_natural_key_duplicate_converges_one_row` — natural key = content sha256).
- Chiều A: khác content cùng idempotency key → ApprovalConflictError zero mutation (`test_replay_with_different_content_conflicts` + API test).
- Chiều B: conflict-probe với payload khác → 409; payload trùng → 422; row bytes identical sau probe (`test_direction_b_conflict_probe`, `test_conflict_probe_endpoint`).
- CAS stale reskin revision → conflict trước mọi mutation (`test_stale_reskin_revision_conflicts`).
- Cross-workspace refs (pack/correction/artifact/config/checkpoint) → NotFound semantics, zero mutation (`test_cross_workspace_pack_refused`, `test_workspace_isolation_both_directions`).

## Acceptance gate results (lệnh thật, chạy ×2)
| Gate | Kết quả |
|---|---|
| Focused suite RUN1 | **30 passed** in 26.27s (domain 15 + api 11 + migration 4) |
| Focused suite RUN2 | **30 passed** in 26.83s |
| Migration mới? | KHÔNG — single head `b3c4d5e6f7a9` giữ nguyên (nên mục single head / round-trip head↔parent / FK=0 / ORM parity được pin bởi test trên head hiện có) |
| models.py zero-removed vs pre-state | PASS (test_apply_checkpoint_columns_zero_removed: removed=set(), added=set()) |
| OpenAPI removed=0 | PASS (test_openapi_additive_removed_zero: 6 path×method authored, unique từng cặp, removed=set()) |
| ruff app + tests | All checks passed! (cả hai) |
| mypy app | Success: no issues found in 124 source files |
| git diff --check | CLEAN |

## Changed files (self-audit write-set)
Toàn bộ nằm TRONG allowlist:
1. `app/services/s09_approval.py` (NEW)
2. `app/api/routes/s09_approval.py` (NEW)
3. `app/schemas/s09_approval.py` (NEW)
4. `tests/test_s09_t06_backend_domain.py` (NEW)
5. `tests/test_s09_t06_backend_api.py` (NEW)
6. `tests/test_s09_t06_backend_migration.py` (NEW)
7. `docs/pm/sessions/S09-T06A-immutable-approval-backend/{LOG.md, REPORT.md}` (packet docs)

git status delta: 61 pre-existing entries (không đụng) + đúng 6 file NEW của task này. FORBIDDEN paths untouched: MAIN, data/**, frontend/**, structural_lock.py, renderer_*, reskin_*, s09_demo_jobs.py, s09_correction*.py, scripts/benchmark, production DB, git history ops.

## Deviations / limitations (disclosed, không giấu)
1. **Router CHƯA wire vào app.api.app**: `app/api/app.py` NĂM NGOÀI write allowlist của TASK.md (chỉ liệt kê NEW s09_approval* files). Theo precedent đã verified của S09-T05A (docstring routes file T05A ghi rõ cùng tình huống), router export sẵn `router`; integration owner thêm MỘT dòng include_router. Tests mount router lên isolated FastAPI app với SessionDep override — contract HTTP thật, không mock.
2. **Override matching semantics**: override string hợp lệ khi xuất hiện trong `reasons` hoặc `provenance.reasons` của MỘT applied correction được reference trong cùng submission. Đây là định nghĩa "explicit evidence" khả thi trên dữ liệu T05A hiện có (request_json lưu reasons/provenance).
3. **Note thuộc content hash**: replay cùng key nhưng khác note → CONFLICT (fail-closed). Quyết định thiết kế để mọi field client-gửi đều nằm trong content hash; note không phải metadata ngoài lề.
4. Migration-test assertion ban đầu sai kỳ vọng của chính worker (tưởng downgrade -1 drop apply_checkpoint) — đã sửa theo hành vi chain thật: downgrade -1 chỉ drop `s09_correction` (bảng của revision T05A); apply_checkpoint tạo sớm hơn nên còn lại. Ghi nhận trong LOG fix-loop.

## Untested items
- Wire-up thật vào app.py (ngoài scope — integration owner).
- Playwright/E2E frontend (task backend-only; T06B là correction UI).

## Out-of-scope findings
- `RendererRoute = Literal[...]` trong `app/schemas/s09_correction.py` có comment "placeholder" nhưng giá trị khớp RENDERER_ROUTES thật — không phải lỗi, chỉ ghi nhận.
- ORM ApplyCheckpoint không khai báo thuộc tính `revision` (DB có cột với server_default=1 + CHECK revision=1; service không đọc ghi cột này). Hoạt động đúng end-to-end; nếu muốn parity hoàn toàn có thể thêm mapped column sau — ngoài allowlist lần này nên KHÔNG làm.

## Trạng thái dừng
Trạng thái dừng ban đầu (phase gốc): TASK_SUBMITTED — STOP chờ PM review; không commit/push, không mở task kế tiếp.

## C1 CORRECTION ROUND (review F4 — approval transaction durability)

**Status: TASK_SUBMITTED** (correction phase A — resume đúng owner session theo §4)

### Defect và root cause (F4)
Production get_db_session chỉ close, KHÔNG commit (deps.py:263-288); route submit_checkpoint thiếu session.commit(); fixture API T06A auto-commit sau mỗi request đã che defect (T06B phải QA-patch runtime).

### Fix (write-set phase A — không đụng app.py/models/migrations)
1. app/api/routes/s09_approval.py: submit giờ commit tường minh CHỈ khi created và SAU mọi validation; commit fail → rollback + 500 "nothing was persisted"; mọi exception → rollback trước khi map HTTP error; replay path → rollback.
2. tests/test_s09_t06_backend_api.py: bỏ auto-commit trong dependency override → production semantics yield/close only.
3. NEW tests/test_s09_t06_backend_durability.py — 6 test binary:
   - AC1 submit → ENGINE MỚI thấy đúng 1 hàng; fresh-session reload verify hash/pins/snapshot;
   - AC2 blocked (pending correction) và stale CAS → 0 hàng trên disk;
   - AC3 crash giữa flush và commit → route rollback → 0 checkpoint nửa vời;
   - replay cross-request-session hội tụ đúng 1 hàng committed;
   - negative control: service write KHÔNG commit → mất sau close().

### Acceptance evidence (lệnh thật)
| Gate | Kết quả |
|---|---|
| Focused RUN1/RUN2 (domain+api+migration+durability) | 36 passed in 31.88s / 36 passed in 31.90s (basetemp s09c1-run1/s09c1-run2) |
| Durability suite riêng | 6 passed in 6.82s |
| ruff (7 file write-set) | All checks passed! |
| mypy (3 file app write-set) | Success: no issues found in 3 source files |
| git diff --check | CLEAN |
| alembic head | b3c4d5e6f7a9 giữ nguyên — models/migrations untouched |

Evidence file: output/s09/20260823_sprint_full/t06a-c1/gate-evidence.txt

### Scope notes (minh bạch)
- ruff/mypy toàn-repo đang đỏ tại renderer_routes/composite.py và schemas/s09_correction.py: write-set worker song song khác (mtime 22:13/22:26 hôm nay), ngoài phase A — không tự sửa file người khác sở hữu.
- app/api/app.py có trạng thái modified với mtime 06:20 (trước phiên này) từ task khác — tôi KHÔNG đụng; mount production chờ J2 (S09-T56-INTEGRATION-C1).
- Write-set audit: đúng 3 file app s09_approval* + 4 test test_s09_t06_* + packet docs append-only + output/t06a-c1/**.

Trạng thái dừng: STATUS: TASK_SUBMITTED — STOP chờ Manager/Codex review; chờ J2 để được cấp quyền sửa app/api/app.py.

## PHASE 2 — S09-T56-INTEGRATION-C1 (J2 mở: mount production routers)

**Status: TASK_SUBMITTED** (phase T56 — resume đúng owner session theo §4; write-lock hữuhan: app/api/app.py + additive tests trong test_s09_t05_backend_api.py / test_s09_t06_backend_api.py + output/t56-integration-c1/**)

### Thay đổi
1. app/api/app.py (DUY NHẤT phase này được phép): import thêm s09_approval, s09_correction + include_router cho /api/v2/s09-approvals và /api/v2/s09-corrections, đặt ngay sau s09_demo_compare với comment dẫn chiếu F4/T56. KHÔNG đụng gì khác trong file.
2. tests/test_s09_t06_backend_api.py — additive block T56 (4 test mới):
   - OpenAPI của APP THẬT có cả 2 route groups, mọi operationId unique, không duplicate (path, method) registration;
   - FULL FLOW trên app thật + lifespan thật + get_db_session thật (KHÔNG override): tạo segment thật → POST s09-corrections (z_order) → confirm applied → POST s09-approvals (kèm correction ref) → 201 → đếm hàng TRÊN DISK = 1 → RESTART proxy (TestClient context thứ hai re-run lifespan trên cùng DB file) → GET checkpoint còn nguyên, hash verified=True, list total=1;
   - invalid correction (segment không tồn tại) → không persist (count unchanged);
   - approval rollback (stale CAS) → không persist.
3. tests/test_s09_t05_backend_api.py — additive block T56 (1 test mới): correction router trên app THẬT qua production seams (deps._job_service + _lifecycle_db như suite production-app hiện có), submit→confirm→restart proxy→vẫn applied.

### Chống QA-patch (bắt buộc §8)
T56 tests KHÔNG override get_db_session (close-only thật), KHÔNG auto-commit, KHÔNG fake router, KHÔNG qa_app_patch. Temp DB bơm đúng seam mà suite production-app hiện hữu dùng. Generation authority (C1-F1) tôn trọng: current_generation đọc từ backend thay vì literal cứng.

### Acceptance evidence (lệnh thật)
| Gate | Kết quả |
|---|---|
| OpenAPI inspection (app.openapi()) | 251 paths = 241 cũ + 5 corrections + 5 approvals; 317 operations; duplicate operation_ids: NONE |
| Focused RUN1/RUN2 (5 files) | 51 passed in 59.63s / 51 passed in 63.39s (basetemp s09t56-run1/run2) |
| ruff (6 file write-set) | All checks passed! |
| mypy | 5 file s09 core sạch; mypy quét app.py lộ ĐÚNG 1 lỗi CŨ tại app/workflow/s09_demo_jobs.py:203 (mtime 04:58, write-set worker khác, không đụng) |
| git diff --check | CLEAN |
| Alembic head | b3c4d5e6f7a9 single head — models/migrations untouched |

Evidence file: output/s09/20260823_sprint_full/t56-integration-c1/gate-evidence.txt

### Write-set audit
Đúng theo lock hữuhan: app/api/app.py (+2 imports +2 include_router blocks), additive tests trong 2 file được cấp, output/t56-integration-c1/**, LOG/REPORT append-only. Không đụng MAIN, data/**, models/migrations, frontend.

Trạng thái dừng: STATUS: TASK_SUBMITTED — STOP chờ Manager/Codex review.

## PHASE — S09-T06A-C3 correction (review F3 P1)

**Status: TASK_SUBMITTED** (owner session 20260824_120141_312e9e — resume đúng owner; write-set: app/services/s09_approval.py + tests/test_s09_t06_backend_*.py + output/t06a-c3/**)

### Defect (F3 P1)
BE approval override validation LẠC SAU hợp đồng `reasonsOf` mà FE đã triển khai (T05B-C3): override loop chỉ match `reasons[]` + `provenance.reasons`, trong khi route-override corrections lưu audit evidence ở top-level `override_reason` và `provenance.evidence` — hợp lệ nhưng KHÔNG BAO GIỜ match → approval override chính đáng bị từ chối sai.

### Fix (app/services/s09_approval.py, duy nhất 1 vùng ~dòng 371)
Mirror đúng FE `ApprovalPanel.reasonsOf`: reasons list giờ lấy từ
1. `request_payload["reasons"]` (giữ nguyên),
2. `provenance.reasons` (giữ nguyên),
3. `provenance.evidence` khi là str non-empty (MỚI),
4. top-level `override_reason` khi là str non-empty (MỚI).
So sánh `override in reasons` + mọi fail-closed semantics khác KHÔNG đổi.

### Tests (tests/test_s09_t06_backend_domain.py, additive 3 case)
- `test_override_matches_top_level_override_reason` — khớp qua override_reason alone;
- `test_override_matches_provenance_evidence_alone` — khớp qua provenance.evidence alone;
- `test_override_with_unrelated_evidence_still_blocks` — evidence không liên quan vẫn refuse + zero mutation.
TDD: RED trước fix (2 FAILED đúng defect, refuse-path PASS) → GREEN sau fix.

### Evidence (lệnh thật)
| Gate | Kết quả |
|---|---|
| Domain suite | RED: 16/18 (2 fail đúng defect) → GREEN: 18/18 in 18.19s |
| Focused ×2 basetemp | 54 passed in 59.31s / 54 passed in 59.02s (s09c3-run1/run2) |
| ruff write-set | All checks passed! |
| mypy s09_approval.py | Success: no issues found in 1 source file |
| git diff --check | CLEAN |
| Alembic head | b3c4d5e6f7a9 single head |

Evidence file: output/s09/20260823_sprint_full/t06a-c3/gate-evidence.txt

Trạng thái dừng: STATUS: TASK_SUBMITTED — STOP chờ review.

## PHASE — S10-T06A-C4-AUTHORITY-BRIDGE (S10-C6A: immutable approval v2)

**Status: TASK_SUBMITTED** (owner session 20260824_120141_312e9e — resume đúng owner; write-set: app/services/s09_approval.py + app/api/routes/s09_approval.py + app/schemas/s09_approval.py + tests/test_s09_t06_backend_authority.py + output/s10/c6a/s09-t06a-c4/** + LOG/REPORT append-only)

### Defect (F3 P0 — Codex C6 blocker)
Snapshot `s09.approval/v1` chỉ lưu policy/SLM id + TOÀN BỘ `list_routes_for_video` alternatives; thiếu manifest_hash/canonical manifest, exact manifest-selected segments/routes, source artifact authority, role/layer→pack mapping, config params, affected geometry, eligibility → server KHÔNG thể tái tạo Full Apply plan deterministic không cần client scene/mapping.

### Fix — additive `s09.approval/v2` (KHÔNG đụng v1)
1. `submit_checkpoint_v2(...)` — deterministic reapproval tạo row mới với snapshot schema `s09.approval/v2` + nested `full_apply_authority` (authority_version `s09.full-apply-authority/v1`). Toàn bộ authority nằm TRONG checkpoint content hash (mọi v2 field hash-covered); v1 rows byte-identical (submit_checkpoint v1 giữ nguyên; reapprove chỉ INSERT v2 hoặc replay tương đương; conflict → zero mutation).
2. Authority build CHỈ từ persisted/canonical rows: identity (workspace/project/video/config/revision/generation), source (VideoItem.source_artifact_id → Artifact relative_path/sha256/size_bytes + manifest frame_count/fps/time_base/start_time_ms), structural_lock (id/policy_version/STORED manifest_hash/canonical manifest — verify hash trước freeze), shot_order + EXACT manifest-selected segments (canonical_manifest.segments; alternatives từ list_routes_for_video KHÔNG làm selected), role_mappings (ObjectRole→ReskinConfig→CharacterPackVersion published/ready + assets + canonical params + dependency hashes), geometry (OccurrenceSegment.segmentation_json/prompt_json — missing/ambiguous → fail closed), eligibility (route unsupported → reason "no downgrade" + unsupported_routes; authority incomplete reasons).
3. `full_apply_authority(checkpoint_id, workspace_id)` — read-only; v1 → `REAPPROVAL_REQUIRED` (zero mutation); tampered v2 → S09ApprovalIntegrityError.
4. Routes additive: POST `/api/v2/s09-approvals/reapprove` (201/200), GET `/api/v2/s09-approvals/{checkpoint_id}/full-apply-authority`. Router đã mount production (T56) — không đụng app.py.

### Acceptance evidence (lệnh thật)
| Gate | Kết quả |
|---|---|
| Focused RUN1/RUN2 (domain+api+durability+authority, basetemp s09t06a-c4-run1/run2) | 60 passed in 63.19s / 60 passed in 63.66s |
| Authority suite (21 tests) | 21 passed (multiple runs) |
| ruff --select F + full (4-file write-set) | All checks passed! |
| mypy (3 production files) | Success: no issues found in 3 source files |
| git diff --check | exit 0 (chỉ CRLF warnings pre-existing) |
| Alembic head | a10b11c12d3e single head, models/migrations zero change |
| OpenAPI materialized | 263 paths / 329 ops / DUPLICATE_OPERATION_IDS NONE / reapprove + full-apply-authority present / removed=0 |
| J1-v4 | 13/13 byte-match + EOL_GUARD PASS (trước + sau) |

### Binary contract tests (21)
v2 snapshot đầy đủ từ persisted + hash verify; selected ≠ alternatives; missing role mapping / geometry / source artifact / unpublished pack fail closed; unsupported route (mesh_warp) preserved + no downgrade + eligibility reason; no-manifest demo approval tồn tại nhưng Full Apply not executable; v1 immutable + reapproval distinct v2 + equivalent v2 replay converges + conflict zero mutation; mutate live config/routes/SLM sau approval → stored v2 bytes/hash KHÔNG đổi; tamper manifest/snapshot + cross-scope segment → fail closed zero mutation; v1 full-apply-authority → REAPPROVAL_REQUIRED; single head a10b11c12d3e; OpenAPI additive.

### Pre-existing red (không phải của task này)
`tests/test_s09_t06_backend_migration.py::test_single_head_unchanged` + `test_round_trip_head_parent_fk_clean` pin `EXPECTED_HEAD=b3c4d5e6f7a9` (head S09 cũ); live head hiện tại `a10b11c12d3e` (S10-T01A migration, S10-owned). Migration test file là append-only trong task này → KHÔNG sửa; S10-T01A/T01C ownership phải cập nhật expected head. Baseline 39 (domain+api+durability) vẫn xanh; test mới pin head mới PASS.

### Write-set audit
Đúng lock: 3 app files s09_approval* + 1 test file mới + output/t06a-c4/** + LOG/REPORT append. Không đụng MAIN, models.py, migrations/**, structural_lock.py, reskin_config.py, s09_correction.py, renderer, frontend, S10 implementation, app/api/app.py, git history. git status 53 = 49 pre-existing + 4 files này.

Trạng thái dừng: STATUS: TASK_SUBMITTED — STOP chờ Manager join gate J6A / Codex review; không commit/push.

# S09-T06A — Immutable approval/checkpoint backend — LOG

## Bước 0 — Required reading (đã đọc TOÀN BỘ trong lượt hiện tại)
- [x] C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md → `RULES_LOADED` (180 dòng; §1 rules load, §2 phân vai worker/allowlist, §4 một task một session, §8 workspace/git safety, §11 vocabulary trạng thái).
- [x] docs/pm/sessions/S09-T06A-immutable-approval-backend/TASK.md (34 dòng, đầy đủ).
- [x] ApplyCheckpoint ORM hiện có: app/persistence/models.py:2281-2335 (revision=1 CHECK, checkpoint_hash len 64, partial unique idempotency, pin columns structural_lock_manifest_id + lock_policy_version từ T00-I01).
- [x] Migration hiện trạng: chain c9d0e1f2a3b4 (T01 tạo reskin_config + apply_checkpoint) → d8e9f0a1b2c3 (T00 structural_lock + additive pin columns) → b3c4d5e6f7a9 (T05A corrections) = head; xác nhận bằng `python -m alembic heads` live → `b3c4d5e6f7a9 (head)` khớp TASK.md.
- [x] Conventions tái sử dụng: app/persistence/reskin_config.py (_resolve_lock_pin hash fail-closed, list_renderer_route_evidence), app/services/s09_correction.py (canonical JSON / natural key / CAS confirm pattern), app/persistence/structural_lock.py (validate_manifest, canonical_manifest_json, manifest_hash, set_checkpoint_lock_pin).

## Preflight (bằng chứng lệnh thật)
- pwd/git toplevel = C:/Users/Admin/MotionForge2D-worktrees/s08-integration, branch codex/s08-integration, HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0.
- MOTIONFORGE_DATABASE_URL = UNSET (echo với default UNSET).
- git status --short trước thay đổi: 61 entries (pre-existing của các task S09 khác: T00/T01/T02/T03/T04/T05A/I05 + launchers) — KHÔNG đụng tới, bảo vệ nguyên vẹn.
- MAIN READ-ONLY: không thao tác ghi nào vào C:/Users/Admin/MotionForge2D.

## Protected user changes
Toàn bộ 61 dirty entries pre-existing được coi là của các writer/task khác trên cùng worktree; write-set của tôi giới hạn CHỈ allowlist TASK.md. Không reset/clean/stash/checkout bất kỳ file nào.

## Quyết định migration (Outcome 2)
ApplyCheckpoint hiện có ĐỦ mọi field outcome yêu cầu:
- Pin pack versions → pack_version_ids_json (Text, NOT NULL).
- CompatibilityPolicy evidence/version → snapshot_json + lock_policy_version (String(64)) + structural_lock_manifest_id FK RESTRICT.
- Renderer routes per segment → snapshot_json (evidence list per segment, route enum RENDERER_ROUTES).
- StructuralLockManifest ref → structural_lock_manifest_id (đã FK).
- Accepted warnings/overrides + demo artifacts refs + correction history refs → snapshot_json (validated finite-only canonical JSON).
→ KHÔNG thêm migration mới, KHÔNG sửa models.py (additive không cần). Single head giữ nguyên b3c4d5e6f7a9.

## Plan (≤7 bước)
1. NEW app/schemas/s09_approval.py — typed strict payloads/responses.
2. NEW app/services/s09_approval.py — S09ApprovalRepository: submit_checkpoint immutable + verify_hash + blockers fail-closed + replay idempotent + CAS zero-mutation.
3. NEW app/api/routes/s09_approval.py — router /api/v2 (KHÔNG wire app.py — ngoài allowlist, theo precedent T05A ghi chú trong docstring).
4. tests/test_s09_t06_backend_domain.py + test_s09_t06_backend_api.py + test_s09_t06_backend_migration.py (temp SQLite alembic-upgrade, basetemp riêng, -p no:cacheprovider).
5. Gates ×2: ruff app+tests, mypy app, OpenAPI removed=0 (router-level uniqueness như T05A), git diff --check.
6. Self-audit write-set vs allowlist; xác nhận zero mutation cho files ngoài allowlist.
7. REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Validation log (append-only)

- [RUN1] `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t06_backend_domain.py tests/test_s09_t06_backend_api.py tests/test_s09_t06_backend_migration.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s09t06a-run1` → **30 passed** in 26.27s.
- [RUN2] cùng lệnh, basetemp `s09t06a-run2` → **30 passed** in 26.83s. (Focused/adversarial ×2 PASS)
- `ruff check app` → All checks passed!
- `ruff check tests` → All checks passed!
- `mypy app` → Success: no issues found in 124 source files.
- `git diff --check` → CLEAN (chỉ CRLF warnings pre-existing trên file task khác).
- `python -m alembic heads` (trước + sau) → `b3c4d5e6f7a9 (head)` — single head KHÔNG đổi.
- Fix loop ghi nhận: (1) CorrectionImpact kwargs sai signature test → sửa theo dataclass thật; (2) FK s09_correction→occurrence_segment bắt buộc segment thật trong seed pending-block test → tạo qua StructuralEvidenceRepository.create_segment với mask artifact; (3) migration round-trip assertion sai kỳ vọng (downgrade -1 chỉ drop bảng của T05A) → sửa assertion; (4) đưa `note` vào snapshot/hash để mọi payload client-gửi đều nằm trong content hash (khác note = conflict, fail-closed).

## C1 correction log (review F4 — production transaction durability)

- [F4] Root cause xác nhận bằng lệnh thật: `get_db_session` (app/api/deps.py:263-288) chỉ `yield session ... finally close()` — KHÔNG commit; route submit T06A không có `session.commit()`; fixture API cũ auto-commit sau mỗi request → defect bị che. T06B từng phải QA-patch runtime (theo review).
- [FIX] `app/api/routes/s09_approval.py` submit_checkpoint: commit tường minh CHỈ khi created, SAU khi mọi validation pass; commit fail → rollback + 500 "nothing was persisted"; mọi exception (blocked/conflict/notfound/validation + unexpected) → `session.rollback()` trước khi map HTTP error; replay path → rollback (read-only guarantee).
- [FIX] `tests/test_s09_t06_backend_api.py`: bỏ auto-commit trong dependency override → production semantics yield/close only.
- [NEW] `tests/test_s09_t06_backend_durability.py` (6 test): AC1 submit durable qua ENGINE MỚI + fresh-session reload verify hash/pins/snapshot; AC2 blocked + stale CAS → 0 hàng trên disk; AC3 crash giữa flush và commit → route-level rollback → 0 nửa vời; replay cross-session hội tụ 1 hàng committed; negative control: service write KHÔNG commit → biến mất sau close() (chứng minh fixture không còn auto-commit).
- [RUN1/RUN2] focused ×2 (domain+api+migration+durability): **36 passed** in 31.88s / **36 passed** in 31.90s (basetemp s09c1-run1 / s09c1-run2).
- [GATES] ruff 7 file write-set → All checks passed!; mypy 3 file app write-set → Success no issues in 3 source files; git diff --check → CLEAN; alembic head giữ nguyên b3c4d5e6f7a9 (không đụng models/migrations).
- [SCOPE NOTE] ruff/mypy toàn repo đang đỏ tại app/services/renderer_routes/composite.py + app/schemas/s09_correction.py — write-set worker song song khác (mtime 22:13/22:26), ngoài phạm vi phase A; app/api/app.py trạng thái ' M' có mtime 06:20 TRƯỚC phiên này — không phải thay đổi của tôi, không đụng (J2 mới được phép). Evidence: output/s09/20260823_sprint_full/t06a-c1/gate-evidence.txt

## T56 integration log (J2 phase — mount production routers)

- [J2] Preflight: cùng worktree/branch, HEAD ee10e55a; MOTIONFORGE_DATABASE_URL UNSET; alembic head b3c4d5e6f7a9.
- [MOUNT] app/api/app.py: +import s09_approval, s09_correction (alphabetical); +app.include_router cho cả hai ngay sau s09_demo_compare, comment dẫn chiếu review F4 / fast-track §8. Lần đầu import nhầm thêm 's09_compare' (không tồn tại) → ImportError thật khi verify → gỡ ngay trước khi chạy test nào.
- [OPENAPI PROOF] python -c app.openapi(): total paths 251 (241 cũ + 5 corrections + 5 approvals), operations 317, duplicate operation_ids NONE. Lưu ý kỹ thuật: FastAPI bản này bọc include_router bằng _IncludedRouter lazy nên phải inspect qua app.openapi(), không phải app.routes.
- [T56 TESTS t06 api file] fixture t56_prod_app bơm temp DB qua production seams (JobService vào deps._job_service + deps._lifecycle_db) — get_db_session KHÔNG bị override; TestClient chạy lifespan thật. Fix loop: (1) walrus sai cú pháp → sửa; (2) create_segment từ chối source_generation literal ('3' != current '1', C1-F1 fail-closed đúng thiết kế) → chuyển sang đọc current_generation từ backend ở cả seed lẫn correction payload; (3) thiếu import StructuralEvidenceRepository/create_engine → bổ sung, ruff --fix sort imports.
- [T56 TESTS t05 api file] additive 1 test: correction router trên app thật, submit→confirm→restart proxy→applied còn nguyên. Fix loop: role dùng GEN cứng gây OwnershipMismatchError (C1-F1) → đọc current_generation TRƯỚC khi tạo role.
- [RUN1/RUN2] focused ×2 (t05_api + t06 domain/api/migration/durability): **51 passed** in 59.63s / **51 passed** in 63.39s (basetemp s09t56-run1/run2).
- [GATES] ruff 6 file write-set sạch; mypy 5 file s09 core sạch (mypy app.py lộ 1 lỗi CŨ trong s09_demo_jobs.py:203 — mtime 04:58, write-set worker khác); git diff --check CLEAN; single head giữ nguyên.

## C3 correction log (review F3 P1 — override evidence contract)

- [F3 P1] Defect xác minh thật: BE override loop (app/services/s09_approval.py ~370) chỉ match reasons[] + provenance.reasons; route-override corrections lưu evidence ở top-level `override_reason` + `provenance.evidence` (hợp đồng FE ApprovalPanel.reasonsOf, T05B-C3 đã ship) → approval override chính đáng bị từ chối sai.
- [RED] Thêm 3 test domain: override_reason alone / provenance.evidence alone / unrelated-evidence vẫn refuse. Chạy trước fix: 2 FAILED + refuse-path PASS (16/18) — tái tạo đúng defect.
- [GREEN] Service mirror đúng reasonsOf: thêm provenance.evidence (str non-empty) và top-level override_reason (str non-empty) vào reasons list; KHÔNG đổi so sánh hay fail-closed khác. Domain 18/18.
- [GATES] Focused ×2 basetemp (s09c3-run1/run2): 54/54 passed cả hai lần. ruff write-set sạch; mypy s09_approval.py sạch; git diff --check CLEAN; alembic head b3c4d5e6f7a9 giữ nguyên.
- Write-set: app/services/s09_approval.py + tests/test_s09_t06_backend_domain.py + output/t06a-c3/** + LOG/REPORT append-only. Không đụng frontend/s09_demo_compare/s09_correction/renderer.

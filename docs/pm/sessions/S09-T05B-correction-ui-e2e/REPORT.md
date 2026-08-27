# S09-T05B — Correction UI/E2E — REPORT

**STATUS: TASK_SUBMITTED**

- Session worker: `20260824_093602_af7c26` (Hermes CLI, provider custom @ 9Router, model alpha)
- Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`, branch `codex/s08-integration`, HEAD tại lúc bắt đầu `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`
- Bước 0: HERMES_AUTOPILOT_RULES.md đọc TOÀN BỘ 180/180 dòng → RULES_LOADED; MOTIONFORGE_DATABASE_URL UNSET (verify shell); MAIN không bị đụng.

## Deliverables (đúng write allowlist)

1. **Correction UI** — `frontend/src/features/demo/CorrectionPanel.tsx` (mới, ~935 dòng, "use client"), mount trong `DemoComparePanel.tsx` dưới header.
   - Load dữ liệu THẬT qua API: durable projects → video items → segments/contacts/motions hiện hành (structural-evidence). KHÔNG mock/data giả ở bất kỳ đâu.
   - Đủ 5 loại correction đúng schema T05A (`app/schemas/s09_correction.py`): mask, z_order, contact, mesh_parts, route_override.
   - Route override: dropdown ĐÚNG 5 giá trị từ `RENDERER_ROUTES` (pose_swap, sprite_affine, mesh_warp, part_rig, controlled_redraw — nguồn chuẩn models.py, đã tự xác minh; Literal placeholder trong schemas là comment chết), reason BẮT BUỘC (nút submit disabled khi trống, aria-invalid phản ánh).
   - Dark theme; MỖI control/button có helper text tiếng Việt NGAY DƯỚI (`<p>` liền sau, `text-gray-400`, 11px+).
   - States tách biệt: loading (`correction-loading`), error (`correction-error`), CAS/idempotency conflict 409 (`correction-conflict`) hiển thị rõ nội dung lỗi backend.
   - Sau submit: affected layers + provenance hiển thị (`correction-affected-layers`, `correction-provenance`). KHÔNG có bất kỳ indicator rerun full-video nào (targeted correction chỉ tác động segment/layer chọn).
   - Accessibility: toàn bộ control focus được bằng keyboard, Tab di chuyển giữa các field, testid đầy đủ.
2. **Typed client additions** — `frontend/src/features/demo/index.ts`: ADDITIVE (anchored patch sau khối `getDemoCompareStatus`), types payload khớp schemas T05A + hàm submit/confirm/cancel/counts + read listings structural-evidence/projects/videos. Không phá hàm cũ.
3. **Playwright E2E** — `frontend/e2e/s09-t05b-correction-ui.spec.ts` + `playwright.s09t05b.config.ts` + `frontend/e2e/s09-t05b-global-setup.ts`:
   - Kịch bản full-flow (desktop): mở /demo-compare → panel load targets THẬT (project "T05B-E2E", video "T05B Correction Demo", segment Character gen 1) → kiểm helper text VN dưới từng control → submit z_order (payload run-unique) → status pending → REPLAY CÙNG idempotency key với z_order khác → HTTP 409 hiển thị trong `correction-conflict` → route override pose_swap→sprite_affine + reason bắt buộc (submit disabled/enabled verify) → confirm → status applied → provenance "pose_swap → sprite_affine" + evidence hiển thị → assert KHÔNG có text rerun toàn bộ video.
   - Mobile-390px project: panel render, không overflow ngang (>1px fail).
4. **QA lane** — `output/s09/20260823_sprint_full/t05b/` (git-ignored):
   - `qa_app_patch.py`: import app.api.app THẬT và runtime-mount `s09_correction.router`. Lý do: app.py là FORBIDDEN cho task này và T05A để wiring còn mở — QA lane chạy đúng semantics production mà không sửa file repo nào.
   - `run-qa-backend.sh`: uvicorn :8099, MOTIONFORGE_ROOT cô lập trong qa-backend-root/, CORS cho origin FE :3014, module dotted qua --app-dir worktree.
   - `run-qa-seed.py`: seed dữ liệu THẬT theo recipe tests/test_s09_t05_backend_api.py (workspace/project/video/job/scene/roles/masks/segments Character+Phone/contact hand_phone/motion object_relative/baseline render_route pose_swap cho Character). Lần đầu tự alembic upgrade tới head `b3c4d5e6f7a9`. Re-run: RESET bề mặt mutation (xoá corrections + render routes của video, tạo lại baseline) để lane idempotent.

## Gates (kết quả thật, lệnh thật)

| Gate | Kết quả |
|---|---|
| `npx tsc --noEmit` | EXIT=0 |
| `npx eslint src/features/demo e2e/s09-t05b-correction-ui.spec.ts e2e/s09-t05b-global-setup.ts playwright.s09t05b.config.ts --max-warnings 0` | EXIT=0 |
| Playwright FULL suite (desktop + mobile-390px) | **2 passed / 2 skipped**, EXIT=0; chạy lần 2 vẫn PASS (lane idempotent nhờ globalSetup reset) |
| Backend T05A suites rerun: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t05_backend_{domain,migration,api}.py -p no:cacheprovider -q --basetemp=...` | **36 passed** (31.91s), EXIT=0 |
| Write-set self-audit | git status chỉ có file allowlist mới; dirty-state T00–T05A giữ nguyên; output/** git-ignored; MAIN untouched |

Skip by-design (có lý do): full-flow là transactional trên shared QA DB — seed reset chạy 1 lần/suite và UNIQUE(segment, route, start_frame) chỉ cho phép MỘT applied override mỗi chu kỳ reset, nên flow này chạy desktop-only; mobile project kiểm layout/overflow. Chi tiết LOG.md mục 9-10.

## Vấn đề thật gặp phải + cách xử lý (không bao biện)

1. **Port 8099 bị chiếm bởi server QA cũ của T04** (app.main:app, không có correction paths) làm probe đầu nhìn thấy 241 paths mà thiếu corrections → verify bằng netstat + Win32_Process.CommandLine rồi Stop-Process đúng PID; launcher cũng phải đổi sang module dotted import vì thư mục numeric-first (`20260823_sprint_full`) không import được kiểu thường.
2. **Re-run spec FAIL dù pass lần đầu**: natural_key = sha256(kind+video+canonical_request) nên payload lặp giữa các run replay row cũ thay vì tạo mới (đúng semantics backend, sai assumption spec) → payload trong spec trở thành run-unique (zBase/reason random), kịch bản same-key-diff-payload→409 vẫn nguyên vẹn trong từng run.
3. **Confirm route_override 500 StructuralLockConflictError**: UNIQUE(segment, route, start_frame) đụng row sprite_affine do các run trước; đồng thời baseline pose_swap biến mất vì nhánh reset cũ giữ sai row. Fix gốc trong seeder (xoá sạch + tái tạo baseline), probe curl SUBMIT 201 → CONFIRM 200 applied trước khi tin là hết.
4. **react-hooks eslint mới** chặn Math.random-in-render + setState-in-effect → refactor DERIVED state thuần, sinh idempotency key trong event handler.

## Quyết định thiết kế ghi nhận cho review

- "Feature-scoped frontend tests" = Playwright suite riêng của T05B vì frontend/package.json không có unit-test runner (chỉ dev/build/start/lint/test:e2e).
- s09_correction.router vẫn CHƯA wire vào app/api/app.py (ngoài allowlist cả T05A lẫn T05B) — quyết định wiring chính thức thuộc Manager/Codex review; QA lane t05b mount runtime chỉ phục vụ E2E.
- Full-flow desktop-only (lý do ở bảng gates).

## Trạng thái kết thúc

- REPORT.md ghi STATUS: TASK_SUBMITTED — terminal state, dừng phiên worker tại đây.
- Process dọn sạch: dev-server :3014 và uvicorn QA :8099 đã kill đúng PID sau verify CommandLine; không còn listener.

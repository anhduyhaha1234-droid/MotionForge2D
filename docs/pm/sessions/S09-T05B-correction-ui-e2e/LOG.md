# S09-T05B — Correction UI/E2E — LOG

## Baseline (2026-08-24)

### Required reading — DONE
- C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — TOÀN BỘ 180 dòng → RULES_LOADED (đầu phiên).
- docs/pm/SESSION_PROTOCOL.md (MAIN) — TOÀN BỘ.
- docs/pm/sessions/S09-T05B-correction-ui-e2e/TASK.md — TOÀN BỘ.
- docs/pm/sessions/S09-T05A-targeted-correction-backend/REPORT.md — TOÀN BỘ (API payload + quyết định wiring còn mở).
- app/schemas/s09_correction.py (199 dòng) — payload types từng kind.
- app/services/s09_correction.py (811 dòng) — validation/idempotency/CAS/provenance semantics.
- app/api/routes/s09_correction.py (230 dòng) — HTTP surface, CHƯA wire vào app.py.
- Pattern T04: frontend/src/features/demo/** , e2e/s09-t04-demo-compare.spec.ts, playwright.s09t04.config.ts, output/.../t04/run-qa-backend.sh.
- Recipe seed thật: tests/test_s09_t05_backend_api.py (Seed fixture + payload mẫu từng kind).
- RENDERER_ROUTES (app/persistence/models.py:214-220) = (pose_swap, sprite_affine, mesh_warp, part_rig, controlled_redraw) — single authority, xác minh trực tiếp trên file.

### Preflight commands + kết quả THẬT
- `git rev-parse --abbrev-ref HEAD` → codex/s08-integration
- `git rev-parse HEAD` → ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- `MOTIONFORGE_DATABASE_URL` → UNSET (verify shell đầu phiên)
- `git status --short` TRƯỚC mọi thay đổi: dirty sẵn bởi các task khác (T00–T05A): ~24 modified + ~30 untracked — BẢO VỆ nguyên trạng, không đụng. Session này chỉ ĐÓNG GÓP file MỚI trong allowlist + sửa 2 file trong features/demo (DemoComparePanel.tsx mount CorrectionPanel, index.ts thêm client additive).

### Protected changes (pre-existing, không thuộc task này)
Toàn bộ mục `M`/`??` trong git status baseline trên — đặc biệt: app/**, migrations/**, tests/** (T00–T05A owned), docs/pm/sessions các session khác, output/.../t04/**.

### Phát hiện phạm vi quan trọng
- Router `/api/v2/s09-corrections*` CHƯA được include vào app/api/app.py (T05A để lại quyết định cho Manager/Codex; app.py là FORBIDDEN của T05B). ⇒ E2E dùng QA launcher riêng mount router RUNTIME qua module patch trong output lane t05b (không sửa bất kỳ backend file nào).
- Repo FE KHÔNG có unit-test runner (frontend/package.json scripts: dev/build/start/lint/test:e2e) ⇒ "Feature-scoped frontend tests" = Playwright suite riêng s09-t05b (desktop + mobile). Ghi rõ trong REPORT.

### Plan (≤7 bước)
1. Client additions trong features/demo/index.ts (typed, additive).
2. CorrectionPanel.tsx mới (dark theme, helper text VN dưới mọi control, 5 loại correction, conflict/loading/error states, dropdown 5 routes, reason bắt buộc, provenance/affected-layer display, KHÔNG rerun indicator).
3. DemoComparePanel.tsx: mount CorrectionPanel (mở rộng trong allowlist).
4. tsc --noEmit + eslint --max-warnings 0 (write-set FE) → fix tới xanh.
5. QA lane t05b: qa_app_patch.py + run-qa-backend.sh (:8099, root cô lập) + run-qa-seed.py (dữ liệu thật, alembic head b3c4d5e6f7a9) + next dev :3014.
6. Playwright spec s09-t05b (desktop + mobile) → PASS đầy đủ.
7. Backend T05A suites chạy lại 1 lần (36 expected) + write-set audit + LOG append + REPORT.md STATUS: TASK_SUBMITTED → STOP.

## 2026-08-24 — Implementation log

1. `frontend/src/features/demo/index.ts` — additive typed client: RENDERER_ROUTES const (5 route từ models.py), correction payload types đúng schemas/s09_correction.py, submit/confirm/cancel/counts + read-only listings structural-evidence + durable project/video.
2. `frontend/src/features/demo/CorrectionPanel.tsx` — NEW panel: chọn project/video/segment/contact/motion THẬT; 5 loại correction; route override dropdown ĐÚNG 5 routes + reason bắt buộc; conflict 409 hiển thị riêng (`correction-conflict`); affected layers + provenance sau confirm; KHÔNG có bất kỳ indicator rerun full-video.
3. `frontend/src/features/demo/DemoComparePanel.tsx` — mount `<CorrectionPanel />` ngay dưới header.
4. Gate tĩnh RUN 1: tsc EXIT=2 (thiếu import RENDERER_ROUTES — fix) → RUN 2: tsc EXIT=2 (Math.random trong render + setState-in-effect theo react-hooks mới — refactor DERIVED-state, bỏ effect đồng bộ) → RUN 3 (final): **tsc --noEmit EXIT=0; eslint --max-warnings 0 EXIT=0**.

## 2026-08-24 — QA lane + E2E log

5. QA lane `output/s09/20260823_sprint_full/t05b/`:
   - `qa_app_patch.py` — import app.api.app thật, runtime-mount s09_correction.router (app.py FORBIDDEN, không sửa file nào).
   - `run-qa-backend.sh` — uvicorn module dotted `output.s09.20260823_sprint_full.t05b.qa_app_patch:app` (--app-dir worktree; numeric-first segment không import được kiểu thường), MOTIONFORGE_ROOT côisolated trong qa-backend-root/, CORS cho :3014.
   - Sự cố thật: lần launch đầu port 8099 bị server T04 cũ chiếm (app.main:app, 241 paths, KHÔNG có correction paths) — verify bằng netstat+Win32_Process.CommandLine rồi Stop-Process đúng PID; launcher đầu chết vì "Could not import module qa_app_patch".
   - Probe openapi sau fix: CORRECTION_PATHS = 4 paths /api/v2/s09-corrections* (+ counts path prefix /videos), TOTAL_PATHS 246.
6. `run-qa-seed.py` — seed dữ liệu THẬT theo recipe test API T05A: workspace/project/video/job/scene/2 roles/2 masks/2 segments (Character, Phone)/contact/motion + baseline render_route pose_swap cho Character. Lần chạy đầu: alembic upgrade a1b2c3d4e5f6 → b3c4d5e6f7a9 đầy đủ, SEEDED exit 0.
7. FE dev :3014 với NEXT_PUBLIC_API_URL=http://localhost:8099 → HTTP 200.
8. Playwright spec `frontend/e2e/s09-t05b-correction-ui.spec.ts` + config `playwright.s09t05b.config.ts` (desktop 1280 + mobile-390, workers=1, outputDir trong output lane).
9. E2E iterations — lỗi thật từng vòng và cách xử lý:
   - v1: XPath union `|` trong locator không hợp lệ → đổi following-sibling::p[1].
   - v1: assert evaluate trả Promise chưa await → viết lại assert focus chuẩn.
   - Desktop PASS đầu tiên (fixed idempotency keys) nhưng re-run FAIL: DB QA PERSISTENT + natural_key = sha256(kind+video+canonical request) (có z_order/reason) nên payload lặp giữa các run replay row cũ ("applied"/"replayed") thay vì tạo mới → spec chuyển runTag+zBase random MỖI run (idempotency-key vẫn giữ kịch bản same-key-diff-payload → 409 trong run).
   - Confirm route_override 500: StructuralLockConflictError từ record_render_route — UNIQUE(segment, route, start_frame); nguyên nhân: các run trước đã confirm sprite_affine cho cùng segment/start_frame (và baseline pose_swap biến mất do reset branch sai chính sách "giữ row cũ nhất"). Fix gốc: seeder reset branch XOÁ SẠCH routes+corrections của video rồi TẠO LẠI baseline pose_swap cho Character (probe curl SUBMIT 201 → CONFIRM 200 applied trước khi tin).
   - Mobile project chạy full-flow đụng UNIQUE thứ hai trong cùng suite (workers=1 vẫn 2 projects tuần tự trên cùng DB) → full-flow giới hạn desktop-only (test.skip), mobile chỉ kiểm layout/overflow ≤1px. Ghi rõ trade-off trong REPORT.
   - Thêm globalSetup (`frontend/e2e/s09-t05b-global-setup.ts`) gọi seeder-reset trước mỗi suite để lane tự hồi phục.
10. Kết quả gates CUỐI:
    - `npx tsc --noEmit` EXIT=0.
    - `npx eslint src/features/demo e2e/s09-t05b-* playwright.s09t05b.config.ts --max-warnings 0` EXIT=0.
    - Playwright FULL (desktop+mobile): **2 passed / 2 skipped (desktop-only flow)**, chạy lại lần 2 vẫn PASS (lane idempotent). Full-flow desktop: load targets THẬT → submit z_order pending → replay SAME key diff payload → conflict 409 hiển thị → route override pose_swap→sprite_affine reason bắt buộc → confirm applied → provenance "pose_swap → sprite_affine" + evidence hiển thị.
    - Backend T05A suites rerun: **36 passed** (31.91s, basetemp riêng, env -u MOTIONFORGE_DATABASE_URL, -p no:cacheprovider).
    - Write-set audit: git status chỉ chứa file allowlist (features/demo/**, e2e s09-t04/s09-t05b*, playwright configs, session dir); output/** git-ignored; dirty-state T00–T05A giữ nguyên không đụng.
11. Cleanup: kill đúng PID dev-server (27468) + uvicorn QA (25908) sau verify CommandLine; ports 3014/8099 sạch.


## 2026-08-26 — S09-T05B-C4-PREP (resume owner 20260824_093602_af7c26, Codex C3 = CHANGES_REQUESTED F1+F6 phần UI)

RULES_LOADED: docs/pm/HERMES_AUTOPILOT_RULES.md (SHA256 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25). Preflight: worktree s08-integration, branch codex/s08-integration, HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0 (khớp review C3), MOTIONFORGE_DATABASE_URL UNSET. Đã đọc S09_C3_PM_REVIEW_2026-08-26.md (F1, F6) + S09_C4 prompt §4.1/§4.5/§6 + frontend/AGENTS.md + local Next docs index.

### Thay đổi (toàn bộ trong write-set frontend/src/features/demo/**)
1. `index.ts` — freeze types §4.5 phía FE: `GenerationEvidence`{generation, base_job_id, correction_id, correction_context_sha256, frozen_evidence_sha256}; `PublishedArtifact` thêm `regenerated?`, `render_ms?`, `base_artifact_id?`, `base_sha256?`; `JobStatus` thêm `affected_loop_ids?`, `generation_evidence?`; `RegenerateJobResponse` mirror ĐÚNG schema BE hiện hữu RegenerateJobCreated (job_id/state/reused/base_job_id/correction_id/correction_context_sha256/affected_loop_ids/detail_url — verify bằng grep schema thật). Binding cuối chờ join J1-C4 khi T04 expose.
2. `CorrectionPanel.tsx` — F1 fix:
   - Props: bỏ `completedLoops`, thêm `selectedLoopId?: string | null` (exact loop viewer đang mở).
   - `affectedLoopIds` = `[selectedLoopId]` duy nhất khi có baseJobId + selection; XOÁ heuristic "overlap" giả trả toàn bộ completedLoops (:182-194 cũ). Không fallback null/all/frame-range.
   - Gate §4.1: `regenBlocked` = !baseJobReady || scope≠1 loop; `submitDisabled` thêm regenBlocked ⇒ không archive correction scope rỗng, không gọi job; helper tiếng Việt `correction-selected-loop-scope` (HELPER_TEXT gray-400/11px giữ nguyên) nêu đúng lý do bị chặn (3 nhánh: chưa có base job / base chưa completed / chưa chọn loop).
   - Submit gửi `affected_loop_ids: affectedLoopIds` trực tiếp (không còn ternary-null).
   - Confirm chỉ tự động mở regeneration khi `applied && !regenBlocked`.
   - `openRegeneration` fail-closed TRƯỚC HTTP khi blocked; setRegenScope từ `res.affected_loop_ids` của MÁY CHỦ (không tin bộ nhớ UI); hiển thị scope thật tại `correction-regeneration-scope`.
   - deps arrays sửa theo react-hooks/exhaustive-deps sau refactor.
3. `DemoComparePanel.tsx` — truyền `selectedLoopId={effectiveActiveLoop}` (`activeLoop ?? loops[0]`) vào CorrectionPanel; block bằng chứng generation §4.5 read-only `demo-generation-evidence`/`demo-generation-scope`/`demo-generation-identity` render CHỈ khi backend expose (chưa join thì ẩn — không suy luận); helper giải thích unaffected giữ artifact gốc regenerated=false.

### Gates PREP (lệnh thật + exit thật)
- Baseline trước sửa: `npx tsc --noEmit` EXIT=0; `npx eslint "src/features/demo/**" --max-warnings 0` EXIT=0.
- RUN 1 sau sửa: tsc EXIT=0; eslint EXIT=1 (1 warning exhaustive-deps `baseJobReady` thừa ở onSubmit deps) → bỏ dep thừa.
- RUN 2 FINAL: `npx tsc --noEmit` EXIT=0; `npx eslint "src/features/demo/**" --max-warnings 0` EXIT=0.
- Content verification script (read-only, Temp): 25/25 check PASS (completedLoops biến mất khỏi features/demo; scope=[selectedLoopId]; gate chặn submit+confirm+openRegen; types §4.5 đủ 11 trường; RegenerateJobResponse khớp schema; evidence block; không ngôn ngữ rerun-toàn-video không phủ định). ALL_CONTENT_CHECKS_PASS, VERIFY_EXIT=0.

### Write-set audit
- `git status --porcelain frontend/src/features/demo/` → chỉ `?? frontend/src/features/demo/` (thư mục untracked nguyên vẹn theo chính sách không-commit các phiên trước; mọi thay đổi nằm gọn trong đó).
- Không đụng app/**, tests/**, fixtures, e2e specs cũ, 13-file freeze set j1-c3; MAIN a43b20da không mở ghi; `git diff --check` sạch trên demo path.
- Tree dirty sẵn (T05A/T03/T04 backend) được BẢO VỆ nguyên trạng.

STATUS: WAITING_JOIN
— Chưa chạy acceptance final (E2E production-stack) theo đúng pha PREP. Chờ Manager resume session này ở Wave B sau T04 final exit để bind production UI + chạy acceptance T05B-C4. Không mở subworker. STOP tại đây.

## 2026-08-26 — S09-T05B-C4-PREP R3 resume #2 (bind FE theo schema BE hiện hành)

Resume đúng owner 20260824_093602_af7c26. Preflight lại: HEAD ee10e55a (không đổi), branch codex/s08-integration, dirty 113 path (T05A/T03/T04 backend đang sửa song song — KHÔNG đụng). Đọc lại rules + review C3 + contract C4 §4.1–§4.5.

### Phát hiện drift và bind lại (toàn bộ trong frontend/src/features/demo/**)
So sánh mirror FE với app/schemas/s09_demo_compare.py THỜI ĐIỂM NAY (T04 đã sửa 11:01, T03 sửa s09_demo_jobs.py 12:55) tìm thấy 3 lệch so với lần PREP trước:
1. `index.ts` GenerationEvidence: `generation` đổi `number` → `string` (BE `generation: str` — label generation, không phải counter client).
2. `index.ts` RegenerateJobResponse: thêm `frozen_evidence_sha256` (BE RegenerateJobCreated đã có từ fingerprint 3 trường F4).
3. `index.ts`: XOÁ field tự chế `base_artifact_id`/`base_sha256` khỏi PublishedArtifact; thay bằng mirror ĐÚNG schema BE: `PublicationIdentity`, `PublicationStatus` (regenerated/render_ms/base_publication) và `JobStatus.publications?: PublicationStatus[]`.
- `DemoComparePanel.tsx`: thêm map `pubStatusByLoop` từ `jobStatus.publications` + block per-loop `regen-status-{loop}`/`regen-flag-{loop}` hiển thị VERBATIM backend evidence (ĐÃ render lại + render_ms | giữ nguyên artifact gốc regenerated=false | máy chủ chưa báo cờ) kèm base_publication identity; helper gray-400/11px.
- Không consumer nào bị vỡ bởi field cũ (grep trước sửa: chỉ 1 chỗ render `generation` — tương thích string).

### Gates PREP (lệnh thật + exit thật, chạy sau khi bind)
- RUN A: `npx tsc --noEmit` EXIT=0.
- RUN B: `npx eslint "src/features/demo/**" --max-warnings 0` EXIT=0.
- Content verification script read-only (Temp): 23/23 PASS — mirror khớp schema BE từng trường, completedLoops biến mất, gate §4.1 chặn submit+confirm+openRegen, scope=[selectedLoopId], publications map + per-loop evidence block, frozen-evidence identity. VERIFY_EXIT=0.
- Re-run tươi 15:21 (+07) sau khi hệ thống đánh dấu workspace "unverified": HEAD ee10e55a không đổi; `npx tsc --noEmit` EXIT=0 · `npx eslint "src/features/demo/**" --max-warnings 0` EXIT=0 · content verify qua stdin (zero file tạm) 22/22 PASS VERIFY_EXIT=0; Temp script đã xoá được ls xác nhận không tồn tại.

### Write-set audit
- `git status --porcelain frontend/src/features/demo/` → vẫn chỉ `?? frontend/src/features/demo/` (untracked nguyên vẹn theo chính sách không-commit).
- Freeze J1-C3-v4 manifest re-hash: ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 MATCH — zero drift, không đụng 13-file set.
- Không đụng app/**, tests/**, fixtures, e2e specs cũ; MAIN không mở ghi.

STATUS: WAITING_JOIN
— Acceptance final (E2E production-stack) CHƯA chạy theo đúng pha PREP; binding cuối chờ join khi T04 final exit. Chờ Manager resume session này ở Wave B. Không mở subworker. STOP tại đây.

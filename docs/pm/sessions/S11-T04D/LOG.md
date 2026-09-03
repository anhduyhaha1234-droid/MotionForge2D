# S11-T04D — Worker LOG (W12)

## Task identity

| Field | Value |
|---|---|
| Task ID | S11-T04D |
| Wave | W12 (song song T05A — FRONTEND only; backend KHÔNG đụng) |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t04d-0903w12` |
| Branch | `codex/s11/t04d-0903w12` (local; không push/merge/rebase/reset) |
| WAVE_BASE | `a146034d2282d2857fb9aee6d0ca4af3c178efb5` (canonical HEAD, porcelain 0 tại start) |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

(Spec ghi worktree `s11-t04d-t04d-0903w12` — thư mục thực tế là `s11-t04d-0903w12`
theo git worktree list; branch đúng như spec.)

## Baseline (trước mọi thay đổi)

- `git status --porcelain` = 0, HEAD = WAVE_BASE.
- sha256 file hiện hữu trong allowlist:
  - api.ts                = `ddf23be21a28b080296435298a1cde165272f09e2fae1acb9dc2c6b0dccc4f4a`
  - ObjectGalleryPanel.tsx = `8b631653b794b7b39679b2261760cf3870a886e24f5ab0912d6ad253ea615d46`
  - projects/[id]/page.tsx = `4defd30f47ccbc765fdf400f06c50ddd0edadebaa6e85f9dfcce37d184a24131`

## Trình tự thực hiện

1. Đọc authority/context: frontend/AGENTS.md (Next.js KHÁC — docs local
   `node_modules/next/dist/docs/`), api.ts structure (api object L989+),
   ConfirmDialog/CorrectionScope pattern, T04A payload
   (app/schemas/qc_navigation.py FREEZE C2-F1), T04B bridge
   (qc_correction_bridge.py build_correction_request), qc-items routes
   (GET-only, `{project_id:uuid}` path), QCItemRepository.create validation
   sets, helper e2e s08-t04-helpers.
2. RED: viết `playwright.s11t04.config.ts` + 2 specs TRƯỚC implementation
   (spec chưa tồn tại tại base). Implementation chỉ sau đó.
3. Implement chặn T04D (11 file — 4 component mới, review page mới,
   additive patches x3, config + 2 specs).
4. GREEN loop: typecheck → lint → boot QA backend/frontend riêng → Playwright
   iterations (seed path, uuid project discovery, CORS, dialog state bug).
5. FINAL GATE + commit local.

## Fallimenti phát hiện & fix (quan trọng)

1. **Turbopack panic trên junction node_modules** (`Symlink [project]/node_modules
   is invalid, it points out of the filesystem root`) → `next dev --webpack`
   (webpack chấp nhận junction) — build production cũng dùng `--webpack`.
2. **Legacy-created project (id 12-char) KHÔNG gọi được**
   `/api/v2/projects/{id}/qc-items` (path ràng buộc `{project_id:uuid}`).
   → E2E seed: tạo DURABLE project qua POST /api/v2/projects (uuid) + fs
   bootstrapping `projects/<uuid>/project.json` (ProjectService) để legacy
   upload/analyze chain chạy thật dưới uuid. GHI NHẬN CHO MANAGER: khoảng
   trống product — project tạo qua legacy API không có màn hình QC queue
   (route uuid-only); T02B/T04D surface chỉ phục vụ durable-uuid projects.
3. **CORS**: QA backend cần `MOTIONFORGE_CORS_ORIGINS=http://localhost:3013`
   (defaults chỉ 8888/3000/5173) — pattern chuẩn S08 run-qa-backend.sh.
4. **Seed QCItem qua repository KHÔNG persist** — `with Session(engine)` chỉ
   close/rollback; repository không auto-commit → thêm `session.commit()`
   (đúng pattern T04B "caller commit 1 lần").
5. **ReviewCorrectionPanel remount khi confirm** — `onClose` inline arrow
   đổi identity mỗi parent re-render (poll 2.5s/apply) → open-effect chạy
   lại preview → mất phase "applied". Fix: `useCallback` ổn định ở page.
6. **G2 trap test** — dispatch keydown phải trên node dialog (trong React
   root), không phải document; và chờ `correction-confirm` enabled (preview
   xong) trước khi trap (đang previewing mọi button disabled → 0 focusable).

## E2E infra (ports/roots RIÊNG)

- Backend : uvicorn app.main:app --port **8413**, QA root
  `%TEMP%/s11t04d_root` (MOTIONFORGE_QA_MODE=1 + MOTIONFORGE_ROOT +
  EXTRACTION_QA_MODE=1 + EXTRACTION_PROVIDER=deterministic + CORS 3013).
- Frontend: `next dev -p 3013 --webpack` (NEXT_PUBLIC_API_URL=8413).
- Playwright outputDir `%TEMP%/s11t04d_pw/test-results` — KHÔNG bao giờ ghi
  `frontend/test-results/.last-run.json` canonical.
- node_modules: read-only (chỉ đọc; KHÔNG install/mutate — dependency-lock
  hash đã verify bởi manager).

## Binary scans (Decision G / a11y contract)

- `grep -rniE "accepted_exception|chấp nhận rủi ro|accept[ed]?[ _-]?risk"`
  trên src/components/review + review page = **0** matches.
- DOM scan trong spec (test "zero accepted-exception controls") = 0.
- Severity badge: icon + text (AlertTriangle/AlertCircle/Info + "Chặn"/
  "Cảnh báo"/"Thông tin") — không chỉ màu.
- Helper text VI dưới mọi button: `text-[11px] text-gray-400` (24 chỗ trong
  review components), ≥11px, contrast đạt (gray-400).

## Ghi nhận ngoài scope (cho manager)

1. Khoảng trống nêu ở trên: qc-items route uuid-only vs legacy-created
   projects (id 12-char) — UI review chỉ hoạt động với durable-uuid
   projects; đề xuất quyết định sản phẩm ở sprint review.
2. `next dev`/`next build` MẶC ĐỊNH dùng Turbopack → junction node_modules
   panic; phải thêm `--webpack` trên môi trường worktree này (ghi chú cho
   các task frontend sau).

## Traces

- Task block verbatim (S11_T02_T06_PRODUCTION_PLAN W12) — acceptance 1-4.
- T04A navigation payload (schemas/services) — deep-link dùng canonical
  anchors frame/role; explain hiển thị code+reason verbatim.
- T04B bridge consume: request `candidate_edit` occurrence-anchored,
  idempotency `qc-item:{id}`, preview→create→confirm qua HTTP surface thật.
- API_UI_GAP_MATRIX G13 (URL/query khớp navigation target), G14 (không thêm
  nav cấp 1 — link level-2 trên projects/[id]/page.tsx).
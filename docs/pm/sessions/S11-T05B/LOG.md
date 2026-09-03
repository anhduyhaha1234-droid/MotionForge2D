# S11-T05B — Readiness UI/E2E (W13) — LOG

## Task
Readiness UI/E2E (KHÔNG accepted-exception controls). Write-set theo binding block W13:
NEW ReadinessPanel.tsx, ReadinessBlockerList.tsx, playwright.s11t05.config.ts,
e2e/s11-t05-readiness.spec.ts; additive projects/[id]/page.tsx, review/page.tsx,
api.ts (getReadiness). Docs: docs/pm/sessions/S11-T05B/{LOG,REPORT}.md.

Branch: codex/s11/t05b-0903w13 — local commit only. WAVE_BASE b3aa2e1 (canonical).

## Steps

### 1. Baseline
- `git status --porcelain` = 0; HEAD = b3aa2e191083d8f50bda0537f0660ae769bd390d (WAVE_BASE).
- Worktree thực tế: `s11-t05b-0903w13` (prompt ghi `s11-t05b-t05b-0903w13` — không tồn tại;
  branch/HEAD khớp đúng task).

### 2. Research
- `app/schemas/readiness.py` (T05A DTO): status ready|blocked|not_run, blockers[]
  (qc_item_id/code/video_item_id/layer_ref_type/layer_ref_id/location/reason_vi/action_vi/action),
  warning_count, videos[] (run_state/check_state_detail/zero_item_completion/blockers),
  policy_version, content_hash, computed_at. Strict extra=forbid.
- `app/persistence/readiness.py` (Decision F compute-on-the-fly), `app/persistence/qc_check_runs.py`
  (run-state vocabulary + check_state_detail), `app/api/routes/readiness.py`
  (GET /api/v2/projects/{project_id}/readiness, GET-only).
- T04D components (component review import-only): ReviewQueueList (qcReasonLabel),
  ReviewQueueStates (QueueLoading/QueueError/Refresher patterns, role=status/alert, helper text
  VI text-gray-400 ≥11px, min-h-10 buttons, data-testid conventions).
- Seed pattern từ test_s11_t05a_readiness_api.py (JobRepository completion block + QCItemRepository).
- CORS: backend allowlist mặc định KHÔNG có :3014 → phải khởi động với
  MOTIONFORGE_CORS_ORIGINS (phát hiện trong vòng Playwright đầu — page rơi error phase,
  đã ghi chú vào header playwright.s11t05.config.ts cho Manager).

### 3. Implement
- api.ts (additive, +71/-1): types ReadinessStatus/ReadinessLocationData/ReadinessActionData/
  ReadinessBlockerData/ReadinessVideoData/ReadinessResponseData + wrapper
  `getReadiness(projectId)` → GET /api/v2/projects/{id}/readiness. PATCH tool làm hỏng indent
  2 lần (CRLF) → chuyển Python string surgery (discipline pitfall #9).
- NEW components/readiness/ReadinessBlockerList.tsx: row icon+code+location+action;
  navigate+frame → gallery deep link G13; explain → action_vi + explain code, no dead link.
- NEW components/readiness/ReadinessPanel.tsx: 3 trạng thái (ready/blocked/not_run),
  loading role=status, error role=alert "Chưa tính được readiness" + Thử lại,
  refresher Làm mới + helper, long-job "Đang xử lý lại…" (role=status, không chặn nav),
  per-video evidence chips (run_state VI), ready evidence "Tất cả N/M video đã chạy kiểm tra QC",
  zero accepted-exception / zero manual mark-fixed (không có nút nào ngoài read+refresh).
- page.tsx + review/page.tsx: additive embed `<ReadinessPanel projectId=... />` (+import), +4 dòng mỗi file.
- playwright.s11t05.config.ts: ports RIÊNG 8414/3014, output %TEMP%/s11t05b_pw.
- e2e/s11-t05-readiness.spec.ts: 9 tests serial (3 trạng thái + auto-ready + long-job +
  error/retry + Decision G DOM scan + helper text + a11y gates T04D + mobile 390px).
- Seed script NGOÀI repo: %TEMP%/s11t05b_root/s11t05b_seed_readiness.py
  (blocked/ready/notrun/running/resolve — repository/SQL seeding đúng path T03F/T05A).

### 4. Serve
- Backend: uvicorn app.main:app --port 8414, MOTIONFORGE_QA_MODE=1,
  MOTIONFORGE_ROOT=%TEMP%/s11t05b_root, EXTRACTION QA deterministic,
  MOTIONFORGE_CORS_ORIGINS=http://localhost:3014,http://127.0.0.1:3014.
- Frontend: npx next dev -p 3014 --webpack (junction node_modules s08; Turbopack panic → --webpack).
- node_modules junction do Manager tạo (s08) — KHÔNG npm install/mutate.

### 5. Green (raw outputs -> REPORT.md)
- tsc --noEmit: 0 errors.
- eslint scoped (readiness/, api.ts, 2 page.tsx, spec, config): 0 errors.
- Playwright s11t05: 9 passed x2 (18.6s / 18.5s) — lần 1 GREEN sau 3 vòng fix
  (CORS env; action_vi hiển thị cho navigate row; explain code assert; per-video blockers=2;
  serial isolation cho error/a11y/mobile tests bằng fresh seed).
- next build --webpack: pending → REPORT.

### 6. Final gate (đã xong)
- next build --webpack: OK — 11/11 routes (ƒ /projects/[id], ƒ /projects/[id]/review), 0 lỗi.
- Self-review diff scope: chỉ đúng allowlist + docs S11-T05B (git status sạch, 3 modified
  additive + 4 NEW; api.ts diff additive +71/-1 với 1 "deletion" EOL-only của comment header).
- Commit local: `7864b9bf02f10029367eb26588b626fd6e7f56bd` (9 files, +1067/-1),
  parent = b3aa2e1 (WAVE_BASE). Docs SHA: commit thứ 2 (LOG/REPORT final).
- Ghi TASK_SUBMITTED + EXIT.

## Isolation flags
- KHÔNG chạm backend app/**, AppNav.tsx, globals.css, MAIN, s11-integration canonical.
- Playwright output ra %TEMP%/s11t05b_pw — không ghi frontend/test-results.
- Seed/QA root ngoài repo (%TEMP%/s11t05b_root); ports 8414/3014 riêng task.
- Chỉ stage allowlist + docs/pm/sessions/S11-T05B/**.
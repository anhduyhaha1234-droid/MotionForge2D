# S11-T05B — Readiness UI/E2E (W13) — REPORT (TASK_SUBMITTED)

Branch: `codex/s11/t05b-0903w13` — WAVE_BASE `b3aa2e191083d8f50bda0537f0660ae769bd390d`.

## Write-set (đúng allowlist C2-F4, file-level)
| File | Kiểu | Nội dung |
|---|---|---|
| frontend/src/components/readiness/ReadinessPanel.tsx | NEW | Panel 3 trạng thái ready/blocked/not_run + loading/error/refresher + long-job + per-video evidence |
| frontend/src/components/readiness/ReadinessBlockerList.tsx | NEW | Blocker row icon+code+location+action (navigate deep-link G13 / explain không dead-link) |
| frontend/src/app/(app)/projects/[id]/page.tsx | additive +4 | Nhúng `<ReadinessPanel projectId={project.id} />` |
| frontend/src/app/(app)/projects/[id]/review/page.tsx | additive +4 | Nhúng `<ReadinessPanel projectId={projectId} />` |
| frontend/src/lib/api.ts | additive +71/-1 | Types Readiness* + `getReadiness(projectId)` (GET /api/v2/projects/{id}/readiness) |
| frontend/playwright.s11t05.config.ts | NEW | Ports 8414/3014, output %TEMP%/s11t05b_pw (kèm env CORS cho Manager) |
| frontend/e2e/s11-t05-readiness.spec.ts | NEW | 9 tests E2E-02 full UI + DOM scans + a11y |
| docs/pm/sessions/S11-T05B/{LOG,REPORT}.md | NEW | Evidence |

KHÔNG đụng: backend app/**, AppNav.tsx, globals.css, component review T04D (chỉ import
`qcReasonLabel` từ ReviewQueueList), MAIN, s11-integration.

## Evidence — raw outputs

### 1. Baseline
```
$ git status --porcelain   → (rỗng — porcelain=0)
$ git rev-parse HEAD        → b3aa2e191083d8f50bda0537f0660ae769bd390d (= WAVE_BASE)
$ git rev-parse --abbrev-ref HEAD → codex/s11/t05b-0903w13
```

### 2. T05A endpoint (real payload, seeded QA DB %TEMP%/s11t05b_root)
```
$ curl /api/v2/projects/{blocked}/readiness
status: blocked | blockers: 2 | warnings: 2 | videos: completed+completed
  - audio_missing explain | action_vi: Kiểm tra lại luồng audio/video gốc...
  - edge_halo navigate | loc: {scene_id:7, frame_index:42, timecode_ms:4200, object_role_id:role-t05b-a}
$ curl /api/v2/projects/{ready}/readiness    → status: ready | blockers: 0 | warnings: 2
$ curl /api/v2/projects/{notrun}/readiness   → status: not_run | videos: never_run + failed
$ curl /api/v2/projects/{running}/readiness  → status: not_run | videos: completed + running
$ seed resolve ×1 → blocked | blockers: 1   (fail-closed: 1/2 resolved vẫn blocked)
$ seed resolve ×2 → ready  | blockers: 0 | warnings: 2 (warning_count giữ nguyên — E2E-02)
```

### 3. GATES
```
$ npx tsc --noEmit          → exit 0 (0 lỗi)
$ npx eslint <7 files scoped> → exit 0 (0 lỗi)
$ npx next build --webpack  → OK, 11/11 routes (ƒ /projects/[id], ƒ /projects/[id]/review)
```

### 4. Playwright s11t05 (2 lần chạy fresh — đều 9/9 pass)
```
Run 1: 9 passed (18.6s)   [desktop]
 ✓ blocked: panel phản chiếu payload T05A + blocker row icon+code+location+action (1.4s)
 ✓ blocked cũng hiển thị trên review page (nhúng 2 nơi) (1.3s)
 ✓ blocked → fix (WS-07 recheck resolve) → auto-ready, KHÔNG nút tay (2.4s)
 ✓ not_run hiển thị trung thực 'Chưa chạy kiểm tra' — KHÔNG xanh (1.3s)
 ✓ long-job 'Đang xử lý lại…' không chặn điều hướng (1.5s)
 ✓ error: 'Chưa tính được readiness' + Thử lại phục hồi (2.0s)
 ✓ zero accepted-exception (Decision G) + helper text VI dưới mọi button (1.3s)
 ✓ a11y gates tái dùng bộ T04D (panel readiness) (2.0s)
 ✓ mobile 390px: panel không tràn ngang (1.9s)
Run 2: 9 passed (18.5s)  (identical list)
```

### 5. DOM/binary scans (bên trong spec, real browser)
- Decision G: `text.match(/chấp nhận rủi ro|accept(?:ed)?\s*risk/i)` → null;
  button labels chứa accept → [].
- Nút tay: button labels `/đánh dấu|mark.*fixed|đã sửa xong/i` → []; copy
  `/đánh dấu đã sửa|mark.*as.*fixed/` → false (blocked và sau auto-ready đều quét).
- Helper text VI: `buttonsWithoutHelper` → [] (mọi button visible có hint
  ≥11px text-gray-400+; mọi button min-h-10).
- not_run badge: `not.toHaveClass(/emerald/)` → pass (amber/zinc, KHÔNG xanh).

## Acceptance criteria (binary) — trạng thái
1. UI phản chiếu payload T05A ready/blocked/not_run — ✅ (Playwright từng case, 2 lần 9/9).
2. Zero accepted-exception button/API/copy trong DOM + code diff — ✅ (DOM scan binary;
   source không có accept/dismiss control nào trong 2 component mới; grep diff xác nhận additive).
3. Không nút tay "đánh dấu đã sửa" — ✅ (DOM scan cả blocked lẫn ready; panel chỉ có
   read + refresh; auto-ready chỉ sau recheck evidence — seed resolve dùng đúng repo call
   orchestrator `_apply_recheck`).
4. Blocker row icon+code+location+action; a11y gates bộ T04D — ✅ (row có icon Chặn +
   code chip + location "Cảnh 7 · Khung 42 · 4.2 giây · Vai trò role-t05" + action_vi + link
   G13 hoặc explain code; a11y: keyboard-complete, touch ≥40px, severity icon+text,
   role=status/alert, reduced-motion, zoom 200%, 390px).

## Validation notes (manager)
- Backend/frontend phải chạy với env ĐÚNG như header playwright.s11t05.config.ts
  (port 8414/3014, MOTIONFORGE_ROOT=%TEMP%/s11t05b_root, MOTIONFORGE_CORS_ORIGINS có :3014 —
  thiếu CORS origin thì trang rơi error phase "Không thể tải dự án").
- Seed script nằm NGOÀI repo: `%TEMP%/s11t05b_root/s11t05b_seed_readiness.py`
  (subcommands blocked/ready/notrun/running/resolve; in JSON dòng cuối cho spec).
- node_modules là junction s08 (Manager tạo); next dev/build cần `--webpack`.
- E2E không cần chain/extraction: readiness aggregate chỉ đọc Project/VideoItem/Job/QCItem
  (Decision F) — seed qua repository/SQL đúng path T03F orchestrator completion block.

## Isolation
- Playwright output: %TEMP%/s11t05b_pw/test-results (KHÔNG chạm frontend/test-results).
- QA root: %TEMP%/s11t05b_root. Ports 8414/3014 riêng task (không đụng 8888/8413/3013…).
- Git: chỉ stage đúng allowlist + docs/pm/sessions/S11-T05B/**. Commit local, không push/merge.
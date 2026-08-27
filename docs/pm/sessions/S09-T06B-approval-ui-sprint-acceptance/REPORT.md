# S09-T06B-C1 — production-stack UI acceptance — REPORT

**STATUS: TASK_SUBMITTED**

- Session owner (resume): `20260824_131423_423e42` (Hermes CLI, provider custom @ 9Router, model alpha)
- Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`, branch `codex/s08-integration`, HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`
- Preflight: `MOTIONFORGE_DATABASE_URL`=[UNSET]; ports free; MAIN + data/** không đụng; backend files CHỈ ĐỌC.
- Bước 0: HERMES_AUTOPILOT_RULES.md 180/180 dòng → RULES_LOADED; F4 review + mục 10 fast-track prompt đọc toàn bộ.

## Kết luận chính

Production stack (actual `app.api.app`, routers mounted bởi T56-INTEGRATION-C1,
commit fix bởi T06A-C1) hoạt động end-to-end với UI hiện hữu của T05B/T06B —
KHÔNG cần qa_app_patch/fake router/monkeypatch/test-only app, KHÔNG cần sửa bất kỳ
file production nào trong C1 (ApprovalPanel.tsx giữ nguyên từ T06B; shared files
DemoComparePanel/index không đụng).

## Deliverables (đúng write-set mục 10)

1. `frontend/e2e/s09-t06bc1-production-stack.spec.ts` — Chromium E2E production-stack:
   - Load REAL targets từ production API (:8199) qua production build FE (:3114).
   - Correction: submit z_order UI → pending → CAS stale-revision confirm (revision=99)
     bị production app từ chối HTTP 409, status KHÔNG persist (vẫn pending sau reload),
     Approve vẫn disabled → confirm đúng revision QUA UI → applied.
   - Approval fail-closed: pending correction = blocker (Approve disabled);
     evidence-less override = blocker kể cả khi ticked; warning unticked = blocker;
     explicit accept từng mục → blockers clear → enabled.
   - Approve → created (mới) + hash 64-hex + "Hash hợp lệ" (verify endpoint thật) +
     row verified trong danh sách.
   - Reload browser → checkpoint còn nguyên cùng hash prefix + verified.
   - RESTART backend process (kill PID :8199, relaunch `run-prod-backend.sh`) →
     checkpoint VẪN tồn tại + verify=true sau restart (durability thật qua process death).
2. `frontend/e2e/s09-t06bc1-global-setup.ts` — reset DB production-backend bằng
   `run-prod-seed.py` trước mỗi suite (idempotent ×2 runs).
3. `frontend/playwright.s09t06bc1.config.ts` — Chromium project, :3114, evidence
   outputDir t06b-c1.
4. QA lane `output/s09/20260823_sprint_full/t06b-c1/`: run-prod-backend.sh (uvicorn
   app.api.app:app :8199, isolation env-only), run-prod-seed.py (seed/reset chain thật),
   run-prod-api-probe.py (blocked→confirm→override-blocked→approve→verify→replay →
   PROD_PROBE_ALL_OK), EVIDENCE-MANIFEST.md, PLAN.md, raw gate logs.

## Acceptance gates (lệnh thật, log trên đĩa)

| Gate | Kết quả |
|---|---|
| Playwright Chromium RUN 1 | 1 passed (13.4s), EXIT=0 (`gate-c1-playwright-run1.log`) |
| Playwright Chromium RUN 2 | 1 passed (13.5s), EXIT=0 (`gate-c1-playwright-run2.log`) |
| `npx tsc --noEmit` | EXIT=0 (`gate-c1-tsc.log`) |
| ESLint S09 specs+configs+features/demo `--max-warnings 0` | EXIT=0 (`gate-c1-eslint.log`) |
| Production build `NEXT_PUBLIC_API_URL=…:8199 next build` | ✓ Compiled successfully, BUILD_EXIT=0 (`gate-c1-next-build.log`) |
| OpenAPI actual app | 251 paths; s09-corrections ×4 + s09-approvals ×5 (`prod-openapi.json`) |
| API probe production chain | PROD_PROBE_ALL_OK (`run-prod-api-probe.py`) |
| Restart durability | checkpoint `da8e4fc1…` (hash 5a8372519d92) sống qua backend restart, verify=true |

## Write-set self-audit

- C1 additions (SHA-256 trong EVIDENCE-MANIFEST.md): 3 file FE mới (spec/global-setup/
  config) + 6 file output lane. ApprovalPanel.tsx KHÔNG đổi (mtime giữ nguyên từ
  T06B 2026-08-24 15:20:39). Shared DemoComparePanel/index.ts KHÔNG đụng → không
  cần Manager lock.
- `git status` worktree: backend modified = NONE. MAIN dirty pre-existing không đổi.
- Ports 8199/3114 đã cleanup sau gates.

## Findings ghi nhận cho Codex review (không thuộc write-set C1)

1. `GET /api/v2/videos/{id}/s09-correction-counts` trả 422 khi video chưa có
   correction nào (validation boundary thay vì empty payload). UI degrade gracefully;
   nếu muốn chuẩn hóa empty-response thì thuộc backend owner (T05A/T56).
2. NEXT_PUBLIC_* là compile-time env: CI/dev phải build và start cùng env
   (đã ghi sự cố env-mismatch trong LOG.md — xử lý phía vận hành, không phải code).

## Handoff

Task C1 hoàn tất theo mục 10 fast-track prompt. Terminal state worker:
`STATUS: TASK_SUBMITTED`. Chờ Codex re-review độc lập (review queue mục "Review
queue after fast-track C1" — item "T06B E2E against the actual app").

---

# REPORT — S09-T06B-C4 FINAL (2026-08-27) — TARGETED REGENERATION DISCRIMINATING — via meta

**STATUS: TASK_SUBMITTED**

- Owner session: `20260824_131423_423e42` (meta round-robin cmc/meta + ocg/muse-spark, reasoning max, fallback OFF, HERMES_CODEX_TTFB 900)
- Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` @ `codex/s08-integration` HEAD `ee10e55a`
- Preflight: `MOTIONFORGE_DATABASE_URL`=UNSET, ports 8201/3115 isolated, MAIN read-only, `RULES_LOADED` 180 dòng

## Kết luận

Targeted regeneration đã **phân biệt đúng chỉ vòng bị ảnh hưởng**: d4_group_occlusion再生 với bytes mới + d1/d2/d3 giữ nguyên — kiểm chứng 3 lớp (API affected_loop_ids + DB job_attempt + artifact hash). Năm loại correction (mask/pose z/contact/mesh/override) + approval/restart đều hoạt động trên production stack thật (app.api.app) với DB/managed-root tách biệt.

## Manager patches trực tiếp (không cần worker tự sửa, verify trên disk)

| File | Sửa | Xác minh |
|---|---|---|
| `output/s09/20260823_sprint_full/t06b-c4/db_attempt_probe.py` | widen regen_attempt_count đếm cả `affected_loop_ids!=null` (DB ghi step_code "run") | `regen_attempt_count=1` verified 10:02 |
| `output/s09/20260823_sprint_full/t06b-c4/run-prod-seed.py` | RESET re-seed SceneGraphContact+SegmentMotion (was 0 sau wipe) | contacts 1 motions 1 sau SEEDED_RESET |
| `fixtures/s09_demo/sprites/d2_mouth_phone/mask_t06b_occluder.png` | 56×96 distinct occluder sha f4eca000... vs phone_replacement 9c64dcb... | byte-distinct verified |
| `output/s09/20260823_sprint_full/t06b-c4/generate_fixtures.py` | tạo mask_t06b_occluder sau copy (idempotent) + giữ d4_group_1 [200,214] | fixtures persist |
| `app/workflow/s09_demo_jobs.py` (worker, production) | pose_swap xử lý mesh_transform rotate+scale; route_override stamp 2×2 marker | DB targeted semantics verified |

## E2E ×2 PASS (fresh DB/runtime idempotent, SEEDED_RESET mỗi run)

| Run | Manifest | Kết quả | Thời gian |
|---|---|---|---|
| RUN1 | `6e2b8d02` | `1 passed (27.6s)` — test 26.3s | Gate C4 run1 |
| RUN2 | `62439fec` | `1 passed (27.6s)` — test 26.2s | Gate C4 run2 |
| `.last-run.json` | — | `{"status":"passed","failedTests":[]}` | — |

Cả 2 run: mask d2 `b0e357b58e`/`265d57dce7` vs base `177a57d329` ≠ ; contact `449adc4b30` vs `cc3a8d18` ≠ ; d4 z-flip bytes đổi; P6 contact>0 motions>0; unsupported z_order failClosed 0 pubs; probe `regen_attempt_count 1` `rendered_loop_count 1` `affected ["d4_group_occlusion"]`; replay dedupe + frozen-evidence path-diverge (stage_frozen_copy bytes identical, identity hash khác `cf7f27...` vs `2412b23c...`).

## DB bằng chứng thật (cuối run)

- Regen `7cd19e36` affected `[d1_cut_graphic]` regen True sha `449adc4b30` (3 others False)
- Regen `4faf728e/265d57` affected `[d2_mouth_phone]` regen True (mask/mesh variants)
- Checkpoint `4589149dcbb02aa5…` (revision 1, pack `2d5f2a31…`, manifest `62439fec…`)
- `job_attempt` verified: generation targeted, per-loop regenerated/render_ms flags khớp

## Gates (lệnh thật, log trên đĩa — worker báo, manager sẽ re-verify ở final gate)

- `npx tsc --noEmit` (cwd frontend/) → EXIT 0
- `npx next build` (env 3 NEXT_PUBLIC_S09_*) → EXIT 0 1328–1393ms
- `npx eslint frontend/e2e/s09-t06bc4*` → EXIT 0
- `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t06* -p no:cacheprovider --basetemp t06b-c4/basetemp-pytest` → 43 passed 42.24s
- `git diff --check` → EXIT 0 (LF warnings 7 file renderer, not diff errors)
- Freeze: `renderer_freeze_manifest_v4.json` ae92247b… 13/13 MATCH (e750e07f…,5d985a26…,1c4e50a4…,079a7425…,0ad93032…,c409f2f1…,6b2712ad…,9b3c7bee…,c00740cf…,65d87726…,3b419d8b6a…), I03 `12de1345…` I05 `d289929d…`
- No v5, no migration mới, no MAIN/data tamper

## Write-set

`frontend/e2e/s09-t06bc4-targeted-regeneration.spec.ts` (39,232B) · `s09-t06bc4-global-setup.ts` · `playwright.s09t06bc4.config.ts` · `output/s09/20260823_sprint_full/t06b-c4/{db_attempt_probe.py,run-prod-seed.py,run-prod-backend.sh,stage_frozen_copy.py,fixtures/,generate_fixtures.py}` · `mask_t06b_occluder.png` · `docs/pm/sessions/S09-T06B-approval-ui-sprint-acceptance/{LOG.md,REPORT.md}` (+ REPORT-C4-PREP).

## Handoff

`STATUS: TASK_SUBMITTED (Chromium ×2 PASS)` — chờ Manager final gate §7 tổng hợp S09-C4 rồi `PENDING_CODEX_REVIEW`.

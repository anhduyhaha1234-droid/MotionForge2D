# REPORT — S09-T06B-C3 targeted regeneration (production acceptance E2E)

- Task: S09-T06B-C3 · Owner session: 20260824_131423_423e42 · Worktree s08-integration @ codex/s08-integration @ ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Gate: J2-C3 mở — I05-C3 + T04 FINAL + T05B PREP Manager-verified.

## Frozen chain C3 (verify bằng tay, không fallback)
- J1-C3-v4 `output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json` sha256 ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 ✓
- I03-C3 run_A content 12de134527765da2b3a2e890dc7a8d693c43b8325c2f8e122eb8886783d038c3 ✓ (khớp decision inputs.i03_run_A.content_sha256; API capabilities echo đúng)
- I05-C3 `t00-i05-c3/route_decisions_c3_seed20260823.json` sha256 d289929d948ddfa7ae961810c47e43d4e1a37bda8aea21074c5a7df8c13063e9 ✓; 6/6 class PASS_MEASURED_ROUTE

## Files changed (exclusive write-set C3)
- output/s09/20260823_sprint_full/t06b-c3/: run-prod-backend.sh (cd RUN_ROOT + stage overlap fixture + frozen docs + MOTIONFORGE_S09_DECISION_DIR), run-prod-seed.py (reset cả s09_demo_loop_regen), fixtures/s09_demo (copy riêng; d4 placement[1] center [320,213]→[200,214] để ĐỔ chồng thật), logs
- frontend/e2e/s09-t06bc3-global-setup.ts · frontend/e2e/s09-t06bc3-targeted-regeneration.spec.ts · frontend/playwright.s09t06bc3.config.ts

## Gates đạt được trước blocker
- next build EXIT=0 (`✓ Compiled successfully in 1949ms`) với env explicit NEXT_PUBLIC_API_URL + NEXT_PUBLIC_S09_BENCHMARK_RESULTS=<I03-C3> + NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256=12de1345…
- TSC repo-wide errors=0; ESLint --max-warnings 0 EXIT=0 cho 3 file write-set
- Run1 Chromium formal (fresh DB/runtime, actual app.api.app :8199 + prod FE :3114): Phase A/B/C/I/E đầu PASS — base job UI completed; z_order correction UI pending; stale confirm 409 tạo ZERO checkpoint/artifact; confirm → applied. FAIL tại chờ UI regen completed (gate-c3-run1.log) — xem F1.

## Findings production (route về owner — KHÔNG tự sửa shared code)

### F1 (P1) — UI không bao giờ mở được targeted regeneration: BE bắt buộc pin, FE không gửi
- Bằng chứng: POST `/api/v2/s09-demo-compare/jobs/{base}/regenerate` body `{correction_id}` → 422 `Field required: body.expect_content_sha256` (app/schemas/s09_demo_compare.py RegenerateJobRequest dòng ~205: `expect_content_sha256: str = Field(..., min_length=64)`). FE CorrectionPanel.openRegeneration gọi regenerateDemoCompareJob(baseJobId, {correction_id}) — type FE chỉ có correction_id, panel không có nguồn env cho pin.
- Ảnh hưởng: binary req #3 "UI tự tạo targeted regeneration job" bất khả thi trên production hiện hành; run1 fail đúng ở bước này.
- Owner đề xuất: T04-C3 (schema/route contract) phối hợp T05B-C3 (CorrectionPanel + helper + type). Một trong hai phía phải đổi: schema nhận optional-pin (mất fail-closed TOCTOU pin) HOẶC panel gửi expect_content_sha256 từ env cấu hình.

### F2 (P2) — Replay regenerate trả 201/reused=false dù cùng durable identity
- Bằng chứng: gọi regenerate ×2 cùng payload → lần 2 HTTP 201, `"reused": false`, nhưng `job_id` GIỐNG HỆT (b7321619-bc3c-4023-8c25-0d99b0f86f78). Route chỉ đặt reused=true trong nhánh catch IdempotencyKeyInUse; JobService hiện trả existing row trực tiếp nên nhánh đó không chạy. Kỳ vọng §3.2/prompt: replay → 200 reused=true, zero duplicate.
- Owner đề xuất: T04-C3 (route response mapping).

## Chẩn đoán bổ trợ (chứng minh phần còn lại của pipeline hoạt động THẬT)
- Cùng stack thật, gọi regenerate bằng API với pin đầy đủ: 201 → worker completed.
- Publication identity: d4_group_occlusion artifact_id VÀ sha256 ĐỔI THẬT (size 79461→79333 — hiệu ứng z-order qua overlap fixture thay đổi bytes render); d1/d2/d3 giữ NGUYÊN artifact_id/sha/size/frame_count. ⇒ Handler targeted-regen + overlap fixture + content-addressing hoạt động đúng ở tầng API/worker; blocker duy nhất là contract FE↔BE (F1/F2).
- correction_context_sha256 ổn định giữa 2 lần gọi (481e729e…) — context bất biến đúng thiết kế.

## Việc cần để mở khóa
1. Owner F1 sửa một trong hai phía contract (đề nghị: panel gửi pin từ env đã có sẵn — giữ nguyên fail-closed BE).
2. Owner F2 sửa response mapping replay.
3. Resume session này (20260824_131423_423e42): spec C3 đã sẵn sàng assert đầy đủ 6 bước binary; chỉ cần chạy lại ×2 sau khi contract khớp.

STATUS: BLOCKED_WITH_FINDINGS (F1 P1 + F2 P2 — chờ Manager route correction về owner; session này KHÔNG tự sửa shared code)


---

# UPDATE 2026-08-26 — Rerun sau khi T04 fix F1+F2 (Manager-verified)

## Fix verification (bằng tay + probe stack thật)
- F1: `RegenerateJobRequest.expect_content_sha256` giờ OPTIONAL — POST regenerate body CHỈ `{correction_id}` → **201** tạo job targeted đúng scope `["d4_group_occlusion"]`; worker completed. ✓
- F2: replay cùng payload → **200 / reused=true / cùng job_id** (`e29dd156…`). ✓
- Spec C3 KHÔNG đổi — nó đã gửi `{correction_id}` thuần từ đầu.

## Rerun formal run1 (gate-c3-rerun1.log)
Phase A–I + E: base job UI completed → z_order correction UI → stale 409 zero-effect → applied → UI tự mở regeneration → **regen phase completed** ✓ → replay dedupe PASS. FAIL tại approval submit (bước cuối).

## F3 (P1) — MỚI: BE approval override validation LẠC SAU hợp đồng reasonsOf
- FE `ApprovalPanel.reasonsOf` (hợp đồng mới): đọc `reasons[]` + `override_reason` + `provenance.reasons` + `provenance.evidence`.
- BE `app/services/s09_approval.py`: chỉ đọc `reasons[]` + `provenance.reasons` → override text = `override_reason` (có thật trong stored request_json, verify bằng tay) → approve 409 `"has no explicit applied-correction evidence"`, trong khi UI badge vẫn báo "đã có bằng chứng applied".
- mtime s09_approval.py 2026-08-24 12:47 — trước wave fix F1/F2, owner chưa cập nhật.
- Chẩn đoán bổ trợ: approval với override khớp `reasons[]` của z_order applied → 201 + checkpoint_hash `2ec76a11e0d561c1…` ⇒ phần còn lại của flow (freeze/hash) OK.

## Việc cần để mở khóa (1 dòng)
Owner T05B/T06A bổ sung `override_reason` + `provenance.evidence` vào sources mà BE dùng match override (mirror FE reasonsOf), rồi session này resume chạy ×2.

STATUS: BLOCKED_WITH_FINDINGS (F3 P1)


---

# FINAL 2026-08-26 — RERUN-3 sau fix F3/T06A: Chromium ×2 PASS toàn bộ binary flow

## Fix verification (bằng tay + live probe)
- `app/services/s09_approval.py` (mtime 07:45 hôm nay): override validation đọc đủ 4 nguồn reasons[] + provenance.reasons + provenance.evidence + override_reason — mirror FE ApprovalPanel.reasonsOf.
- Live probe trước formal: route_override correction → confirm applied → approval với override = evidence text → **201 checkpoint_hash bee20dc46f78455b…** (F3 hết).

## Acceptance ×2 (production stack thật: actual app.api.app :8199 + prod FE build :3114, fresh DB mỗi run qua global-setup SEEDED_RESET)

| Run | Log | Kết quả | Evidence snapshot |
|---|---|---|---|
| 1 | gate-c3-rerun3-run1.log | **1 passed (17.3s) PW_EXIT=0** | evidence-rerun3-run1.json |
| 2 | gate-c3-rerun3-run2.log | **1 passed (19.2s) PW_EXIT=0** | evidence-rerun3-run2.json |

Flow 6 bước binary PASS cả hai run:
1. Base job 4 loops completed qua UI; snapshot publication rows/ids/hashes/sizes/frames trước.
2. z-order correction qua ACTUAL UI (d4_group_occlusion scope); stale confirm → 409 zero-effect; valid confirm → applied.
3. UI tự mở targeted regeneration: d4_group_occlusion artifact_id MỚI + content hash MỚI (z-order đổi bytes render thật nhờ overlap fixture); ba loop unaffected giữ EXACT identity.
4. Replay same correction → cùng regeneration job id (reused), zero duplicate artifact.
5. Pending block approval; sau applied → approval pass với route-override evidence match TRỰC TIẾP qua reasonsOf mới (override_reason/provenance.evidence) — không warning workaround; checkpoint hash verify.
6. Browser reload + backend restart thật giữ nguyên checkpoint verified + regen publications.

## Static gates
TSC errors=0 · ESLint --max-warnings 0 EXIT=0 · FE build EXIT=0 (đủ 3 env NEXT_PUBLIC_*).

## Files changed (exclusive write-set C3)
output/s09/20260823_sprint_full/t06b-c3/** (launcher/seeder/fixtures/logs/evidence-rerun3-run{1,2}.json) · frontend/e2e/s09-t06bc3-{global-setup.ts,targeted-regeneration.spec.ts} · frontend/playwright.s09t06bc3.config.ts

STATUS: TASK_SUBMITTED (Chromium ×2 PASS — chờ Codex review)

# REPORT — S09-T06B-C2 FINAL RUN (spec only-affected-regenerates, production stack, frozen C2 evidence)

- Task: S09-T06B-C2 (final) · Owner session: 20260824_131423_423e42 · Worktree: s08-integration @ codex/s08-integration @ ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Gate: J2-C2 MỞ — I05-C2 verified; T03/T04 final runs song song (spec không đụng file của họ).

## Frozen evidence (verify bằng tay trước khi chạy)
- Route decision: output/s09/20260823_sprint_full/t00-i05-c2/route_decisions_seed20260823.json — sha256 = ebce8c4bf416cc6b3b2225f9ddf889e475931b25acc6b76f0a55842c74de8f98 (khớp pin của API C2_DECISION_SHA256)
- Benchmark: output/s09/20260823_sprint_full/t00-i03-c2/run_A/benchmark_results_seed20260823.json — file sha256 731929c471707de799645080b635797f54d167cb2a40709073db7e0ba85bc06a; schema_version=3; decision inputs.i03_run_A.file_sha256 khớp đúng bytes này
- J1-C2-v2 aa405015… = j1_manifest_sha256 nhúng trong benchmark rows (provenance trong doc)
- KHÔNG dùng v1/C1/synthetic fallback ở bất kỳ đâu

## Files changed (exclusive write-set T06B-C2)
- frontend/e2e/s09-t06bc2-only-affected-regenerates.spec.ts — Phase F viết lại theo bằng chứng thật
- frontend/playwright.s09t06bc2.config.ts, frontend/e2e/s09-t06bc2-global-setup.ts (giữ nguyên từ PREP, đã verify)
- output/s09/20260823_sprint_full/t06b-c2/: run-prod-backend.sh (stage frozen docs vào RUN_ROOT), seed logs, gate-c2-final-run1/2.log, next-build-final.log
- LOG.md append-only + REPORT-C2-PREP.md (PREP) + REPORT-C2.md (file này)

## Verification evidence (real runs)
- Playwright Chromium ×2 PASS trên fresh DB/runtime :8199 (actual app.api.app) + :3114 (next start prod build):
  - run1: `1 passed (15.1s)` — gate-c2-final-run1.log
  - run2: `1 passed (13.5s)` — gate-c2-final-run2.log
- Build env explicit: NEXT_PUBLIC_API_URL=http://localhost:8199 + NEXT_PUBLIC_S09_BENCHMARK_RESULTS=<frozen doc> + NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256=731929c4… → `✓ Compiled successfully in 1298ms`, BUILD_EXIT=0
- TSC repo-wide errors=0; ESLint --max-warnings 0 EXIT=0 cho cả 3 file write-set
- Seed idempotent: SEEDED_RESET mỗi lần re-seed giữa các run

## Acceptance coverage (binary asserts trong spec, tất cả trên frozen evidence thật)
1. Snapshot artifact IDs/hashes sau job #1 qua UI submit thật (expect_content_sha256 pin)
2. Correction route_override qua UI: pending → stale-revision confirm 409 KHÔNG tạo artifact/checkpoint → confirm applied
3. Pin từ correction (sprite_affine cho mouth_expression_swap) KHÔNG measured-passing trong real doc → worker REFUSE fail-closed: job2 state=failed, error chứa "pinned route 'sprite_affine'" + "mouth_expression_swap" — bằng chứng planner không bao giờ render từ pin drift
4. Pinless replay cùng manifest → 200 reused=true, jobId3==jobId1 (contract §3 identity); MỌI loop giữ nguyên artifact_id/sha/size/frame_count; plan giữ default pose_swap (pin refused, không áp dụng); đúng 4 distinct artifacts / 8 rows, không duplicate
5. Approval fail-closed khi pending (nút disable) → sau confirm approve được: checkpoint hash 64-hex + verify PASS
6. Browser reload + backend process restart THẬT (kill PID + spawn lại launcher): checkpoint verified + publications 4/4 còn nguyên; failed-pin job vẫn state=failed sau restart

## Sự cố đã xử lý trong phiên
- Backend do spec restart nạp code T04-C2 mới giữa chừng (final binding decision SHA) → capabilities 422 vì decision doc không có dưới QA root. Fix trong write-set launcher: stage frozen decision+benchmark docs vào prod-backend-root/output/... ; API tự verify SHA nên tính toàn vẹn bằng chứng không đổi.

## Findings liên quan (đã ghi LOG từ PREP, giữ nguyên)
- CorrectionPanel không gửi affected_loop_ids; ApprovalPanel reasonsOf() không match override với route_override payload — thuộc T05B owner 093602_af7c26.

## Blockers / risks
- Không còn. Spec thích ứng contract hiện hành; khi T03/T04 đóng và binding per-loop bytes thay đổi, chỉ cần bật thêm assert sha-mới cho affected loop trên cùng harness.

STATUS: TASK_SUBMITTED (FINAL — full acceptance suite PASS ×2 trên frozen C2 evidence)

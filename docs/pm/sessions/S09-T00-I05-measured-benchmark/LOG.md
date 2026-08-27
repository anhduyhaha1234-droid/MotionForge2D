# S09-T00-I05 — LOG (measured benchmark/report)

Worker implementation · provider custom @ 9Router · model alpha · fallback disabled.
Worktree `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration`.
Múi giờ ghi: +07.

## Phiên 1 (2026-08-23)

- Bước 0: đọc TOÀN BỘ `C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md` (180 dòng) → RULES_LOADED; đọc TASK.md đầy đủ; worktree guard OK (branch + HEAD ee10e55a); MOTIONFORGE_DATABASE_URL UNSET_OK; dirty-tree baseline I01–I04 ghi nhận, không đụng.
- Preflight đầu vào: fixtures_gen của I03 đủ manifests/media/sprites/thresholds (chỉ ĐỌC) · reference media kiểm tra THẬT SỰ còn trên máy (36,971,916 bytes) — lệch giả định TASK.md, quyết định đo VERIFIED thay vì fake SKIP · python 3.11.9 + cv2 5.0.0 sẵn sàng.
- ~23:40+07 Dry-run freeze check EXIT=0: frozen_content_sha256 = 0ba6f6460f281028a6fde638273e149f19bc472556e1b67534738efbee555b44 KHỚP expected (MATCH=True) — banner in TRƯỚC lần đo đầu. Evidence: logs/dry_run_freeze.log.
- ~23:41–23:42+07 Measured run1 + run2 same-seed (seed 20260823), EXIT=0 cả hai, 12/12 runs mỗi run, banner freeze precedes measurement trong cả hai logs.
- ~23:43+07 Determinism compare (logs/compare_runs.py): core_identical_after_strip=True, IDENTICAL=True, COMPARE_EXIT=0; raw chỉ khác ở wall_runtime_ms_per_frame/vram_peak_mib (declared non-deterministic).
- Trích số liệu: 11 PASS / 1 FAIL (f2_mouth_swap × sprite_affine FAIL pose_state_capability — đúng contract route rigid); f4 clipping count=6298 fail_bool=False (applies_to_routes=[], asset-level audit); smallest passing = pose_swap mọi class; escalation none; FAIL-OPEN-QUESTION none.
- Sự cố: process phiên chết đột ngột SAU KHI toàn bộ đo lường hoàn tất và kết quả nguyên vẹn trên disk, TRƯỚC khi kịp viết REPORT.md/LOG.md.

## Phiên 2 — resume (2026-08-23 → 2026-08-24)

- Resume đúng owning session theo lệnh Manager; RULES_LOADED giữ hiệu lực (đã nạp đầu phiên 1); DB guard UNSET_OK verify lại; HEAD không đổi ee10e55a.
- Chỉ đọc-verify (không đo lại): measured_seed20260823 JSON đủ 6 risk classes × 2 routes = 12 pairs, ref_status=VERIFIED, frozen SHA khớp — CHECK1 đạt bằng chứng từ chính file trên disk.
- Kiểm tra templates per fixture để phân loại MEASURED/UNKNOWN trung thực: phát hiện harness sprite_for mapping thiếu char_a/char_b/pillar ⇒ trajectory/visibility/z-order f5 skip ở tầng template (route_notes xác nhận) — phân loại PASS* + UNKNOWN cho f5 thay vì nhận conventions là bằng chứng tracking.
- 00:01+07 Viết REPORT.md đầy đủ: bảng verdict từng dòng, escalation log (none), freeze evidence, exact commands/versions/hashes/timestamps +07, VERIFIED reference (lệch giả định TASK.md được báo minh bạch), tách bạch MEASURED/UNKNOWN/SKIPPED, self-audit write-set, hạn chế.
- Tạo LOG.md này (bản đầu tiên — phiên 1 chết trước khi kịp tạo).
- Không chạy thêm benchmark nào; không sửa file nào ngoài REPORT.md + LOG.md trong phiên resume.

STATUS: TASK_SUBMITTED

## S09-T00-I05-C1 — measured decision v2 (2026-08-25, resume owner `20260823_233406_8d5b7b`)

- RULES_LOADED lần 2 (đọc lại toàn bộ 180 dòng trong lượt hiện tại). Prompt gốc mục 9 fast-track đã đọc toàn bộ. Preflight: branch codex/s08-integration, HEAD ee10e55a (không đổi), MOTIONFORGE_DATABASE_URL UNSET.
- Input I03-C1 verified trên disk: smoke_full8 + det_A/det_B schema v2, measurement_mode=RENDERED_OUTPUT; fixtures frozen xác định = t00-i03/fixtures_gen (manifest f1 SHA bd4e5a6e… khớp smoke_full8 freeze).
- J1 handshake verify: contract SHA 46c6a41f…bbc1e khớp token T02_CONTRACT_FROZEN_FOR_I03 trong docs/pm/sessions/S09-C1-SESSION-REGISTRY.md (harness tự fail-closed nếu lệch).
- Phát hiện minh bạch: harness_source đổi sau smoke_full8 (17f8cc9c→07e1daf8) do I03-C1 chỉnh lint/mypy lần cuối sau khi chốt evidence (gates 29 passed ×4); inputs khác khớp byte.
- 04:18+07 Run A EXIT=0 (12 rows: 4 MEASURED_RENDERED_OUTPUT PASS / 8 CONTRACT_REJECTED_BY_FROZEN_CONTRACT); freeze banner dc79bc80… in trước đo.
- 04:21+07 Run B same-seed EXIT=0; determinism: frozen A==B, decoded_output_hash SAME ×4, core identical sau strip telemetry declared; cross-check decoded hashes MATCH smoke_full8.
- Decision MEASURED-only: smallest passing route — mouth_expression_swap=pose_swap; phone_contact/whole_body_rotation/semantic_graphic_replacement=sprite_affine; hard_cut + group_occlusion KHÔNG route đủ evidence → FAIL_OPEN_QUESTION (FOQ-1, FOQ-2), không mở downstream.
- Adversarial source-reencode control đỏ đúng 4/4 (FAILED_AS_EXPECTED). Reference MEDIA_VERIFIED tách bạch khỏi reference_benchmark SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE.
- Ghi đủ runtime/VRAM(unknown)/corrections/license(mp4v writer, không NVENC trong benchmark này)/commands/env/hashes/timestamps vào REPORT.md phần C1.
- Write-set đúng allowlist: chỉ output/s09/20260823_sprint_full/t00-i05-c1/** + append LOG/REPORT này. Không sửa script/fixture/threshold/code.

STATUS: TASK_SUBMITTED

## S09-T00-I05-C2 — measured route decision schema v3 (2026-08-25, resume owner `20260823_233406_8d5b7b`)

- RULES_LOADED lần 3 (đọc toàn bộ 180 dòng trong lượt). Prompt C2 mục 10 đã đọc. Preflight: branch codex/s08-integration, HEAD ee10e55a, MOTIONFORGE_DATABASE_URL UNSET_OK.
- Verify J1-C2-v2: manifest file SHA aa405015…8c91 MATCH; rehash 13/13 files pinned OK, drift=0; supersedes v1 (1d854969…).
- Verify inputs: run_A SHA 731929c4…bc06a (schema v3, mode RENDERED_OUTPUT, seed 20260823), run_B SHA 9468470e…b10754, frozen_content 4d674b01… khớp nhau; thresholds_policy s09-t00-i03-c1-frozen-20260824.
- Determinism verify độc lập (script riêng I05, strip row-relative declared fields): core IDENTICAL, decoded hash SAME ×6.
- Decision MEASURED-only: hard_cut→sprite_affine · mouth_expression_swap→pose_swap · phone_contact→sprite_affine · whole_body_rotation→sprite_affine · group_occlusion→sprite_affine (z_inv=0, required_layer_coverage>0) · semantic_graphic_replacement→sprite_affine. Adversarial control 6/6 FAILED_AS_EXPECTED.
- FAIL_OPEN_QUESTION = 0 (6/6 class có evidence measured thật lần này).
- Ghi route_decisions_seed20260823.json (35,671 bytes) pin đầy đủ: route + input/result SHA + threshold/harness/j1 SHA + metric values/sample counts + provenance backend_v3/contract/artifact hashes. Reference media SKIPPED_WITH_REASON và reference benchmark NOT_RUN giữ hai state riêng.
- Write-set: chỉ output/s09/20260823_sprint_full/t00-i05-c2/** + append REPORT.md/LOG.md. Không sửa code/test/fixture/threshold.

STATUS: TASK_SUBMITTED

## S09-T00-I05-C3 — route decision trên freeze v4 (2026-08-26, resume owner `20260823_233406_8d5b7b`)

- RULES_LOADED lần 4. Preflight: branch codex/s08-integration, HEAD ee10e55a, DB env UNSET_OK.
- Verify độc lập từ disk: J1-C3-v4 file SHA ae92247b… MATCH; rehash 13/13 pre+post decision drift NONE; run_A content SHA 12de1345…d038c3, run_B dab37e41…ab40; schema v3, seed 20260823, mode RENDERED_OUTPUT; mỗi run 6 MEASURED (sprite_affine ×5 + f2 pose_swap) + 6 CONTRACT_REJECTED; decoded==adapter_frame_hash 24/24; A/B core-identical sau strip 4 field declared; decoded A==B 12/12 pairs; 6/6 measured rows pin j1_manifest_path=v4 + SHA exact (rejected rows không có field pin — đã ghi minh bạch).
- Decision: hard_cut→sprite_affine · mouth_expression_swap→pose_swap · phone_contact→sprite_affine · whole_body_rotation→sprite_affine · group_occlusion→sprite_affine (z_inv=0, coverage>0) · semantic_graphic_replacement→sprite_affine. Adversarial 6/6 FAILED_AS_EXPECTED.
- fail_open_question_count = 0 (bắt buộc đạt).
- Ghi route_decisions_c3_seed20260823.json (38,245 bytes): machine-readable, sample counts >0, frames/fps_rational/time_base/metrics/provenance đầy đủ; provenance chain V4-ONLY (audit grep C2/v2/v1/v3 = 0 hit trong fields); reference media SKIPPED_WITH_REASON ≠ reference benchmark NOT_RUN giữ hai state riêng.
- Write-set: chỉ output/s09/20260823_sprint_full/t00-i05-c3/** + append REPORT.md/LOG.md. Temp script ngoài worktree đã xóa. Không sửa code/test/fixture/threshold.

STATUS: TASK_SUBMITTED

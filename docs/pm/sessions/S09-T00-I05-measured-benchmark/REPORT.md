# S09-T00-I05 — REPORT: Measured benchmark/report

Session: worker implementation · provider custom @ 9Router http://127.0.0.1:20128/v1 · model alpha · reasoning max · fallback disabled.
Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration` · HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`.
Phiên đo: 2026-08-23, timestamps +07 (chi tiết §8). LOG chi tiết: `LOG.md` cùng thư mục.
`MOTIONFORGE_DATABASE_URL`: UNSET suốt phiên (verify đầu phiên và lúc resume). MAIN chỉ ĐỌC.

## 1. Freeze gate (trước lần đo đầu)

Freeze banner in TRƯỚC mọi measurement trong cả 3 lượt chạy (dry-run, run1, run2). Evidence:

- `output/s09/20260823_sprint_full/t00-i05/logs/dry_run_freeze.log` (23:40:49+07)
- `output/s09/20260823_sprint_full/t00-i05/logs/measured_run1.log` dòng 1–3: banner → JSON freeze → `=== FREEZE COMPLETE (no measurement has run yet) ===`, rồi mới tới dòng `[run]` đầu tiên

```
frozen_content_sha256 = 0ba6f6460f281028a6fde638273e149f19bc472556e1b67534738efbee555b44
expected (TASK.md acceptance) = 0ba6f6460f281028…
MATCH = True   (schema_version=1, component_count=14, seed=20260823,
                routes=[pose_swap, sprite_affine])
```

Components then chốt: `harness_source=2d867243…87f12`, `thresholds=8f5cbb6c…1eb0` (thresholds.json policy `s09-t00-frozen-20260823`, frozen_at 2026-08-23T18:20:00+07:00), cộng manifest+media SHA từng fixture (đầy đủ trong banner log). Mọi measured result JSON nhúng đúng SHA này (verify trong §5).

## 2. Raw machine-readable results (per-run)

| Run | Path (tương đối worktree) | Rows |
|---|---|---|
| Run1 | `output/s09/20260823_sprint_full/t00-i05/measured_seed20260823/benchmark_results_seed20260823.json` | 12 |
| Run2 (same-seed) | `output/s09/20260823_sprint_full/t00-i05/measured_seed20260823_run2/benchmark_results_seed20260823.json` | 12 |

Mỗi row = 1 (fixture × route) với đủ fields: `metrics`, `threshold_evaluation.checks[]` (metric/value/limit/pass), `wall_runtime_ms_per_frame`, `vram_peak_mib`, `route_notes`. Đã kiểm chứng: đủ **6 risk classes × 2 routes = 12 pairs**, không thiếu pair nào.

## 3. Bảng route-per-risk-class — verdict từng dòng (run1, seed 20260823)

Giá trị là số đo thật đọc trực tiếp từ results JSON (không tính lại). Ngưỡng frozen áp dụng: cut/swap ≤1 fr, traj_med ≤0.5%, traj_p95 ≤1%, scale_p95 ≤3%, rot_p95 ≤3°, contact_p95 ≤1%, z_inv=0, unexpl_vis=0, clip fail_bool=false.

| Risk class | Fixture | Route | Verdict | Metrics applicable ĐO ĐƯỢC | Failing checks |
|---|---|---|---|---|---|
| hard_cut | f1_hard_cut | pose_swap | PASS | cut_error=0 fr, timebase_err=0, frame_err=0 | none |
| hard_cut | f1_hard_cut | sprite_affine | PASS | cut_error=0 fr, timebase_err=0, frame_err=0 | none |
| mouth_expression_swap | f2_mouth_swap | pose_swap | PASS | swap_error=0 fr (3 annotated swaps), timebase_err=0 | none |
| mouth_expression_swap | f2_mouth_swap | sprite_affine | **FAIL** | pose_state_capability=`not_measured`; note: "no pose-state capability; 3 annotated swaps unhandled" | `pose_state_capability` (limit: required_when_swaps_annotated) |
| phone_contact | f3_phone_contact | pose_swap | PASS | traj_med=0.0%, traj_p95=0.0%, contact_p95=1.6e-05%, timebase_err=0 | none |
| phone_contact | f3_phone_contact | sprite_affine | PASS | traj_med=0.0%, traj_p95=0.0%, contact_p95=1.6e-05%, timebase_err=0 | none |
| whole_body_rotation | f4_body_rotation | pose_swap | PASS | scale_p95=1.282539%, rot_p95=1.0°, contact_p95=1.1e-05%, timebase_err=0 | none (xem clipping §4) |
| whole_body_rotation | f4_body_rotation | sprite_affine | PASS | scale_p95=1.282539%, rot_p95=1.0°, contact_p95=1.1e-05%, timebase_err=0 | none (xem clipping §4) |
| group_occlusion | f5_group_occlusion | pose_swap | PASS* | z_order_inversions=0, unexplained_visibility_events=0, timebase_err=0 (*phân loại bằng chứng xem §6) | none |
| group_occlusion | f5_group_occlusion | sprite_affine | PASS* | như trên (*§6) | none |
| semantic_graphic_replacement | f6_graphic_replacement | pose_swap | PASS | graphic_present_frames_ratio=1.0, watermark_leak_events=0, traj_med=0.0%, traj_p95=0.0% | none |
| semantic_graphic_replacement | f6_graphic_replacement | sprite_affine | PASS | như trên | none |

Tổng: **11 PASS / 1 FAIL**. FAIL duy nhất là hành vi contract đúng: `sprite_affine` rigid không có năng lực pose-swap nên harness đánh fail cấu trúc thay vì fake pass (giống kết quả I03 đã verified).

## 4. Clipping probe (asset-level audit) — giải thích honest

`f4_body_rotation`: `clipping_from_source_silhouette = {applicable: true, count: 6298, fail_bool: false, limit_pixels: 25, applies_to_routes: [], probe_frame: 89, pivot_xy: [220,190]}`.

Detector mô phỏng defect silhouette-reuse (resize rep lên max scale rồi clip bởi alpha source) mất **6298 px** replacement content — nhưng đây là property của CẶP ASSET, và fixture author khai báo `applies_to_routes=[]` (không route nào trong benchmark này thực hiện silhouette-reuse trong contract) ⇒ `fail_bool=false`, KHÔNG route nào bị gán lỗi asset. Con số 6298 được ghi nguyên xi làm bằng chứng rủi ro asset; việc route production có reuse hay không thuộc S09-T02/T03.

## 5. Same-seed determinism

Script: `output/s09/20260823_sprint_full/t00-i05/logs/compare_runs.py` (strip `wall_runtime_ms_per_frame`, `vram_peak_mib` rồi deep-compare toàn bộ cấu trúc còn lại). Output thật:

```
frozen_sha_matches_expected=True (cả 2 runs)
run1_results_count=12 / run2_results_count=12
raw_files_byte_identical=False
core_identical_after_strip=True
IDENTICAL=True   (COMPARE_EXIT=0)
```

Raw khác nhau DUY NHẤT ở 2 trường declared non-deterministic: `wall_runtime_ms_per_frame` (run1 3.6617–66.6345 ms/fr, run2 3.6895–68.183 ms/fr) và `vram_peak_mib` (=0 cả 2 runs, xem §7 UNKNOWN).

## 6. Smallest passing route + escalation decision

| Risk class | Smallest passing route | Căn cứ |
|---|---|---|
| hard_cut | pose_swap | PASS đầy đủ checks applicable |
| mouth_expression_swap | pose_swap | sprite_affine FAIL pose_state_capability ⇒ chỉ pose_swap pass |
| phone_contact | pose_swap | cả hai PASS, pose_swap nhẹ hơn (thứ tự enum RENDERER_ROUTES) |
| whole_body_rotation | pose_swap | cả hai PASS, tương tự |
| group_occlusion | pose_swap | cả hai PASS*, tương tự |
| semantic_graphic_replacement | pose_swap | cả hai PASS, tương tự |

**Escalation decision: KHÔNG escalate** (`mesh_warp`, `part_rig`, `controlled_redraw` không cần thiết): route nhẹ nhất đã thỏa toàn bộ thresholds frozen ở mọi class — escalate chỉ hợp lệ khi measured error thực sự giảm, mà không có class nào cần giảm. **Escalation log: none.** **FAIL-OPEN-QUESTION: none** (mọi class đều có ≥1 route pass; không tune threshold nào sau khi thấy kết quả — thresholds giữ nguyên bytes, SHA khớp banner).

## 7. Tách bạch MEASURED / UNKNOWN / SKIPPED

**MEASURED** (số thật trong results JSON, liệt kê tại §3/§4): cut_error_frames, timebase_error_frames, frame_error, swap_error_frames (pose_swap f2), trajectory_median/p95_pct (f3, f6), scale_p95_pct + rotation_p95_deg + contact_p95_pct (f3, f4), z_order_inversions + unexplained_visibility_events (giá trị 0 trên universe route probed), graphic_present_frames_ratio (f6=1.0), watermark_leak_events (f6=0), correction_counts (0 — deterministic routes), wall_runtime_ms_per_frame (wall-clock thật mỗi run, declared non-deterministic).

**UNKNOWN** (metric không có sẵn đáng tin trong results fields — KHÔNG tự tính lại bằng công thức khác):
- `vram_peak_mib` = 0 trong JSON: máy không có CUDA torch nên harness không capture được VRAM GPU ⇒ VRAM GPU thực tế của benchmark này là UNKNOWN (giá trị 0 là "not captured", không phải 0 MiB tiêu thụ). Tham chiếu VRAM NVENC production route (1,803,550,720 bytes ≈ 1720 MiB) thuộc I02 `route_benchmark.json`, KHÔNG phải của measured run này.
- Trajectory/z-order/visibility của `f5_group_occlusion` ở tầng route estimator: harness template mapping (`sprite_for`) không có template cho `char_a`/`char_b`/`pillar` (sprites tồn tại: `char_a_rep.png`, `char_b_rep.png`, `pillar.png`) — `route_notes` ghi rõ "no template, trajectory skipped". Do đó verdict PASS* của f5 dựa trên zero-event conventions trên universe probed rỗng + các checks còn lại (timebase/frame/cut), KHÔNG phải bằng chứng tracking thật cho f5. Đây là gap của harness I03 (frozen, không được sửa trong task này) — reviewer cần biết khi diễn giải dòng f5.

**SKIPPED**: **none.** Không có skip nào trong deliverables bắt buộc. Reference media được đo VERIFIED (§8) chứ không SKIP.

## 8. Reference evaluation — VERIFIED (lệch giả định TASK.md, báo minh bạch)

TASK.md context ghi reference media `5A175454…` "KHÔNG có trên máy → mọi kết quả liên quan reference = SKIP_WITH_REASON". Kiểm tra thực tế lúc chạy: file **CÓ trên máy** (READ-ONLY) và cả 2 runs ghi:

```
status      : VERIFIED
sha256      : 5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2 (KHỚP expected)
size_bytes  : 36,971,916
nguồn       : C:/Users/Admin/MotionForge2D/projects/2dc14177a212/Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4
probe       : 640×360 @30/1 fps, nb_frames=39634, duration=1321.133333s, pix_fmt=yuv420p
host        : Windows-10-10.0.22631-SP0
```

Không fake SKIP khi media có thật — cơ chế SKIP_WITH_REASON vẫn tồn tại trong harness và được test tự động bảo vệ (thuộc I03), nhưng ở phiên này không áp dụng vì điều kiện skip không xảy ra.

## 9. Exact commands + environment + hashes

Lệnh (chạy trong worktree, cwd `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`):

```bash
# Dry-run freeze check (không đo)
python scripts/s09_renderer_benchmark.py --routes pose_swap,sprite_affine \
  --fixtures output/s09/20260823_sprint_full/t00-i03/fixtures_gen \
  --out output/s09/20260823_sprint_full/t00-i05/dry_run --seed 20260823

# Measured run 1 / run 2 (same command, --out khác nhau; fixtures_gen của I03 chỉ ĐỌC)
python scripts/s09_renderer_benchmark.py --routes pose_swap,sprite_affine \
  --fixtures output/s09/20260823_sprint_full/t00-i03/fixtures_gen \
  --out output/s09/20260823_sprint_full/t00-i05/measured_seed20260823 \
  --seed 20260823 \
  --reference-media 'C:/Users/Admin/MotionForge2D/projects/2dc14177a212/Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4'
# run2: --out .../t00-i05/measured_seed20260823_run2 (các tham số còn lại y hệt)

# Determinism compare
python output/s09/20260823_sprint_full/t00-i05/logs/compare_runs.py
```

Environment: Python 3.11.9 (`C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe`) · numpy 2.4.4 · OpenCV (cv2) 5.0.0 · ffmpeg/ffprobe 8.1.2-full_build-www.gyan.dev · NVENC encoders available (h264_nvenc, hevc_nvenc, av1_nvenc — harness đo này decode CPU, không encode) · seed 20260823 (mọi run) · `MOTIONFORGE_DATABASE_URL` UNSET.

Timestamps mốc (+07, lấy từ mtime file thật):
| Sự kiện | Thời điểm |
|---|---|
| Dry-run freeze check | 2026-08-23T23:40:49+07 |
| Measured run1 hoàn tất (JSON ghi disk) | 2026-08-23T23:41:47+07 |
| Measured run2 hoàn tất | 2026-08-23T23:42:43+07 |
| Compare determinism | 2026-08-23T23:43:12+07 |
| Resume verify + REPORT này | 2026-08-23T23:54–23:59+07 |

Hashes: frozen content SHA `0ba6f6460f281028a6fde638273e149f19bc472556e1b67534738efbee555b44` (14 components, xem §1) · git HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0` (branch `codex/s08-integration`, dirty-tree baseline của I01–I04 giữ nguyên, không có modification mới ngoài write-set task này).

## 10. Runtime/correction counts (outcome #4 — từ results fields có sẵn)

- `correction_counts = 0` cho cả 12 runs (routes deterministic, không interactive corrections).
- `wall_runtime_ms_per_frame` (declared non-deterministic, đo thật mỗi run): run1 min 3.6617 (f1) → max 66.6345 ms/fr (f3×sprite_affine); run2 min 3.6895 → max 68.183 ms/fr. F3/F4/F6 chậm hơn do NCC search nhiều layer/template.
- `vram_peak_mib` = not captured (UNKNOWN, §7).
- Tham chiếu chéo (KHÔNG phải của measured run này): I02 production route benchmark NVENC RTX 5070: pose_swap 6.151 ms/fr, sprite_affine 6.574 ms/fr, vram_bytes 1,803,550,720.

## 11. Self-audit write-set + FORBIDDEN

Files tạo trong phiên này (toàn bộ trong allowlist):
1. `output/s09/20260823_sprint_full/t00-i05/dry_run/**`
2. `output/s09/20260823_sprint_full/t00-i05/measured_seed20260823/benchmark_results_seed20260823.json`
3. `output/s09/20260823_sprint_full/t00-i05/measured_seed20260823_run2/benchmark_results_seed20260823.json`
4. `output/s09/20260823_sprint_full/t00-i05/logs/{dry_run_freeze.log, measured_run1.log, measured_run2.log, compare_runs.py}`
5. `docs/pm/sessions/S09-T00-I05-measured-benchmark/{REPORT.md, LOG.md}`

FORBIDDEN checks: không sửa bất kỳ file production/test/script/fixture nào (I01–I04 owned) · MAIN READ-ONLY · không đụng data/** · không network/model download · không migration · không git history ops · fixtures I03 chỉ ĐỌC · output task khác chỉ ĐỌC. Lưu ý vận hành minh bạch: phiên đầu chết đột ngột SAU KHI đo xong nhưng TRƯỚC khi kịp viết REPORT (kết quả nguyên vẹn trên disk, Manager verify); phiên resume chỉ đọc-verify + viết REPORT/LOG, không đo lại.

## 12. Hạn chế khai báo

- Route estimators trong harness là measurement stack NCC thật (GT-blind) nhưng không phải bản render production của các route — production route runtime/VRAM tham chiếu riêng tại I02.
- Gap template mapping f5 (§7 UNKNOWN) là giới hạn của harness frozen I03; không sửa trong task này, reviewer cân nhắc khi đánh giá dòng f5.
- VRAM GPU của measured run này UNKNOWN (không CUDA torch); wall runtime non-deterministic-declared.

STATUS: TASK_SUBMITTED

---

# S09-T00-I05-C1 — REPORT (measured decision v2, resume owner)

Session owner: `20260823_233406_8d5b7b` (resume đúng owner theo fast-track §3 Wave B) · provider custom @ 9Router · model alpha · reasoning max · fallback disabled.
Worktree `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration` · HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`.
Ngày: 2026-08-25 (+07). Prompt gốc: `S09_C1_FAST_TRACK_MANAGER_2026-08-24.md` mục 9. RULES_LOADED đọc lại toàn bộ 180 dòng đầu lượt.

## 1. Hai measured runs schema v2 từ frozen inputs

Cùng một command, chỉ khác `--out` (run_A / run_B), seed 20260823, fixtures/thresholds KHÔNG đổi giữa hai run:

```bash
python scripts/s09_renderer_benchmark.py --routes pose_swap,sprite_affine \
  --fixtures output/s09/20260823_sprint_full/t00-i03/fixtures_gen \
  --out output/s09/20260823_sprint_full/t00-i05-c1/run_A \
  --seed 20260823 \
  --reference-media 'C:/Users/Admin/MotionForge2D/projects/2dc14177a212/Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4'
# run_B: y hệt, --out .../t00-i05-c1/run_B
```

| Mốc | Thời điểm (+07) |
|---|---|
| Run A hoàn tất (EXIT=0) | 2026-08-25T04:18:41 |
| Run B hoàn tất (EXIT=0) | 2026-08-25T04:21:38 |

Freeze banner schema v2 in TRƯỚC mọi đo trong cả hai logs (`logs/run_a.log`, `logs/run_b.log`): `frozen_content_sha256 = dc79bc80d704e17adbafafc1aa357d1042cd1f9814a4856783ce09160d268304`, 14 components — fixtures + thresholds SHA **KHỚP TỪNG BYTE** với measured evidence chốt của I03-C1 (smoke_full8: manifest f1 `bd4e5a6e…`, thresholds `86289b5c…`); measurement_mode=`RENDERED_OUTPUT`; J1 handshake verify bởi harness: contract SHA `46c6a41f…bbc1e` khớp token `T02_CONTRACT_FROZEN_FOR_I03` trong `docs/pm/sessions/S09-C1-SESSION-REGISTRY.md`.

Ghi nhận minh bạch về harness_source component: smoke_full8/det_A/det_B freeze với `harness_source=17f8cc9c…` (bản 02:50); sau đó I03-C1 còn chỉnh lần cuối lint/mypy trên CHÍNH file này (ruff E501 ×8, bỏ type:ignore thừa, guard None — gates 29 passed ×4, evidence cũ sha256sum -c giữ nguyên). Harness lúc tôi chạy là bản chốt `07e1daf8…` → frozen SHA run của tôi `dc79bc80…` khác smoke_full8 `b64c9bd1…` đúng bằng đúng component này; mọi component inputs khác khớp. Kết quả đo của tôi TÁI LẬP ĐÚNG pattern smoke_full8 (xem §3).

Environment: Python 3.11.9 · numpy 2.4.4 · OpenCV cv2 5.0.0 · ffmpeg/ffprobe 8.1.2-full_build-www.gyan.dev · `MOTIONFORGE_DATABASE_URL` UNSET suốt phiên (verify đầu phiên).

## 2. Determinism hai run cùng seed

So sánh script inline (loại `wall_runtime_ms_per_frame`, `vram_peak_mib` + 2 path run-scoped `artifact_path`/`adversarial_artifact`):

```
frozen_A==frozen_B: True
rows: 12 / 12
decoded_output_hash SAME ×4/4 measured rows
core_identical_after_strip=True
```

Cross-check độc lập với evidence I03-C1: decoded_output_hash của cả 4 measured rows **MATCH** smoke_full8 (renderer deterministic thật, không phụ thuộc run).

## 3. Smallest passing route per risk class — quyết định theo quy tắc MEASURED-only

Quy tắc áp dụng: PASS chỉ nhận khi `measured_state=MEASURED_RENDERED_OUTPUT` + mọi required check pass + sample>0. `CONTRACT_REJECTED_BY_FROZEN_CONTRACT` = không có số đo = KHÔNG phải PASS. Kết quả run_A (= run_B):

| Risk class | fixture | pose_swap | sprite_affine | Smallest passing route | Căn cứ |
|---|---|---|---|---|---|
| mouth_expression_swap | f2 | **PASS** (measured: swap_error=0fr/3 swaps, replacement_effect head=1.0, traj=0.0%, cut/timebase/frame=0) | CONTRACT_REJECTED (capability_mismatch: requires replacement_asset) | **pose_swap** | duy nhất route có đủ evidence measured + pass |
| phone_contact | f3 | CONTRACT_REJECTED (requires pose_schedule+pose_state_assets) | **PASS** (measured: traj_med=0.068%≤0.5, traj_p95=0.193%≤1.0, contact_p95=0.136%≤1.0 sample>0, replacement_effect phone=1.0) | **sprite_affine** | duy nhất route pass measured |
| whole_body_rotation | f4 | CONTRACT_REJECTED | **PASS** (measured: contact_p95≈0.000011%, scale_p95=0.0, rot_p95=0.0°, replacement_effect body=1.0) | **sprite_affine** | duy nhất route pass measured |
| semantic_graphic_replacement | f6 | CONTRACT_REJECTED | **PASS** (measured: graphic_ratio=1.0, watermark_leak=0, traj_med=p95=0.136%≤ngưỡng, replacement_effect sign=1.0) | **sprite_affine** | duy nhất route pass measured |
| hard_cut | f1 | CONTRACT_REJECTED (requires pose_schedule) | CONTRACT_REJECTED (requires replacement_asset) | **KHÔNG ROUTE ĐỦ EVIDENCE** | không có số đo nào cho risk class này |
| group_occlusion | f5 | CONTRACT_REJECTED (requires pose_schedule) | CONTRACT_REJECTED fail-closed z-order (replacement char_a z=0 phải nằm SAU occluder pillar/char_b; mặt bằng frozen T02 không có tham số z) | **KHÔNG ROUTE ĐỦ EVIDENCE** | không có số đo nào |

Adversarial source-reencode control: 4/4 control `FAILED_AS_EXPECTED` (presence ratio 0.0 < 0.5 → gate đỏ đúng thiết kế F2) — fake-output không thể qua replacement gate.

## 4. FAIL_OPEN_QUESTION (theo mục 9: không đủ evidence → ghi rõ, KHÔNG mở downstream)

- **FOQ-1 (hard_cut/f1):** Không route nào trong {pose_swap, sprite_affine} đủ capability để render contract của fixture hard_cut theo mặt bằng frozen T02 (cả hai bị reject trước khi đo). Risk class này vì thế KHÔNG CÓ smallest passing route measured. Câu hỏi mở cho Codex/BA: hard_cut thuộc năng lực route nào (trim/re-encode segment?) và có cần bổ sung contract/harness cho nó không?
- **FOQ-2 (group_occlusion/f5):** sprite_affine bị fail-closed vì thiếu z-order trong frozen surface; pose_swap không nhận prop_trajectory contract. Không route nào đo được f5. Câu hỏi mở: mở tham số z cho surface composite (thay đổi contract T02 → cần hash handshake lại) hay chấp nhận f5 ngoài phạm vi renderer hiện tại?

Theo đúng prompt mục 9: hai risk class không đủ evidence được ghi FAIL_OPEN_QUESTION, **không tự mở downstream**, không tune threshold, không sửa script/fixture/code (write-set tôn trọng tuyệt đối — chỉ output t00-i05-c1/** + append LOG/REPORT).

## 5. Runtime / VRAM / corrections / license

- wall_runtime_ms_per_frame (declared non-deterministic, đo thật): f2×pose_swap ≈ 11.18; f3×sprite_affine ≈ 95.37; f4×sprite_affine ≈ 25.60; f6×sprite_affine ≈ 60.85 ms/fr (run_A; run_B cùng bậc).
- vram_peak_mib = 0 cả 12 rows (harness không capture VRAM GPU trên máy này — không CUDA torch) ⇒ VRAM của benchmark này UNKNOWN, ghi rõ không bịa số.
- correction_counts = 0 mọi rows (routes deterministic).
- License/provenance encode: backend.adapter `app.services.renderer_routes.composite (frozen T02)`, writer `composite.write_frames_mp4/mp4v`, contract_sha256 `46c6a41f…bbc1e` — encoder mp4v (OpenCV writer) không phải NVENC trong benchmark này; decision license: mp4v/MPEG-4 Part 2 decoder-side rendering, không dùng GPL encoder binary trong measured path (khác bench I02 dùng ffmpeg-gpl-build NVENC — tách bạch rõ).

## 6. Reference media verification vs reference benchmark (tách bạch)

- `reference_media_verification`: **MEDIA_VERIFIED** — sha256 `5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2`, size 36,971,916 bytes, probe 640×360@30fps nb_frames=39634 duration=1321.13s pix_fmt=yuv420p, host Windows-10-10.0.22631-SP0. Đây CHỈ là identity/probe check của media, không tạo verdict route nào.
- `reference_benchmark`: **SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE** — không có authoritative annotation/replacement contract REF-R01..R05; media verification một mình không đủ để chấm structural route. Không fabricate ground truth, không fake PASS.

## 7. Self-audit write-set + FORBIDDEN

Files tạo phiên này (đúng allowlist mục 9):
1. `output/s09/20260823_sprint_full/t00-i05-c1/run_A/**` (results JSON + artifacts renderer)
2. `output/s09/20260823_sprint_full/t00-i05-c1/run_B/**`
3. `output/s09/20260823_sprint_full/t00-i05-c1/logs/{run_a.log, run_b.log}`
4. Append `docs/pm/sessions/S09-T00-I05-measured-benchmark/{LOG.md, REPORT.md}`

Không sửa: scripts/, tests/fixtures/, thresholds, app/**, MAIN, data/**. Fixtures_gen I03 chỉ ĐỌC (SHA verify khớp smoke_full8). Không git ops, không session mới, DB env UNSET.

## 8. Hạn chế khai báo

- Harness chạy là bản chốt sau-lint của I03-C1 (`07e1daf8…`) chứ không byte-identical bản sinh smoke_full8 (`17f8cc9c…`): khác biệt lint/typing đã qua gates 29 passed ×4 của chính I03-C1; kết quả measured của tôi tái lập đúng pattern + decoded hashes khớp smoke_full8 → không có drift hành vi. Ghi rõ để reviewer đối chiếu frozen SHA.
- f1/f5 không có con số đo nào (contract-rejected trước khi render) — đây là trạng thái trung thực của mặt bằng frozen, không phải lỗi đo.
- VRAM GPU unknown (không CUDA capture); reference benchmark skipped-with-reason (thiếu ground truth annotation).

STATUS: TASK_SUBMITTED
# S09-T00-I05-C2 — REPORT: measured route decision (schema v3)

Session owner: `20260823_233406_8d5b7b` (resume đúng owner, correction C2 theo prompt `S09_C2_CORRECTION_MANAGER_2026-08-25.md` mục 10) · provider custom @ 9Router · model alpha · reasoning max · fallback disabled.
Worktree `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration` · HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`.
Ngày: 2026-08-25 (+07). RULES_LOADED (180 dòng, đọc toàn bộ trong lượt hiện tại). Write-set: `output/s09/20260823_sprint_full/t00-i05-c2/**` + append-only I05 LOG/REPORT. Không sửa code/test/fixture/threshold.

## 1. Verify trước khi chạy decision

| Kiểm tra | Kết quả | Bằng chứng |
|---|---|---|
| J1 manifest v2 file SHA | **MATCH** `aa405015856432e5985106741aea4702d4e4f12c08077bec437c3672e8728c91` | rehash `j1-c2/renderer_freeze_manifest_v2.json` bằng Python hashlib, đầu phiên |
| 13 file pin trong manifest | Rehash từng file trên disk: **13/13 OK, drift=0** (`renderer_contract.py` 93329785…, `renderer_router.py` cdd0362f…, adapters/renderer/* ×7, renderer_routes/* ×4) | script verify in OK từng dòng |
| run_A result SHA | `731929c471707de799645080b635797f54d167cb2a40709073db7e0ba85bc06a` (mtime 2026-08-25T17:44+07) | sha256 file frozen input |
| run_B result SHA | `9468470e8d22ac16160142d64622cf1cad3b9e36f9e2c1166e604d3d6cb10754` | sha256 file frozen input |
| Schema/mode/seed | schema_version=**3**, measurement_mode=`RENDERED_OUTPUT`, seed=20260823, thresholds_policy=`s09-t00-i03-c1-frozen-20260824` | header của results JSON |
| Rows pin J1 | 6/6 rows measured đều pin `j1_manifest_sha256` = manifest v2 SHA hiện tại → không drift sau run | field trong từng result row |
| MOTIONFORGE_DATABASE_URL | UNSET_OK suốt phiên | env check đầu phiên |

Freeze components của inputs (14): manifests f1 `53a99c4d…`, f5 `106e6058…` (đã đổi vs C1 — đúng thiết kế fixture v3 cho f1/f5), media f1–f6 giữ nguyên, harness_source `0c58768a…`, thresholds `985c659a…`; `frozen_content_sha256 = 4d674b01973aa820cf5a5d006a53933cab8590917a0f2907c267370a2915f21f`.

## 2. Determinism verify độc lập (run_A vs run_B)

So sánh lại bằng script riêng của I05 (không dùng code so sánh của I03), strip đúng các field declared non-deterministic theo đường dẫn row-relative: `backend.wall_time_ms_total`, `runtime_ms_per_frame_measured`, `vram_peak_mib`, `wall_runtime_ms_per_frame`, scrub tên thư mục run:

- `IDENTICAL_AFTER_DECLARED_STRIP = True` (0 diff)
- `decoded_output_hash` SAME ×6/6 measured rows
- frozen_content_sha256 A == B

## 3. Decision A/B — smallest passing route per risk class (MEASURED-only)

Quy tắc: PASS chỉ khi `measured_state=MEASURED_RENDERED_OUTPUT` + mọi threshold check pass + sample>0 + adversarial control FAILED_AS_EXPECTED. CONTRACT_REJECTED / UNKNOWN / SKIPPED / empty không phải PASS.

| Risk class | Fixture | Smallest passing route | Backend (backend_v3) | Frames decoded/sample | Điểm chính |
|---|---|---|---|---|---|
| hard_cut | f1_hard_cut | **sprite_affine** | SpriteAffineAdapter · h264_nvenc · ffmpeg-nvenc-sprite-affine | 90/90 | cut_error_frames=0; traj med/p95=0%; replacement_effect sign=1.0 |
| mouth_expression_swap | f2_mouth_swap | **pose_swap** | PoseSwapAdapter · h264_nvenc · ffmpeg-nvenc-pose-swap | 60/60 frames_decoded | swap_error_frames=0; replacement_effect head=1.0 |
| phone_contact | f3_phone_contact | **sprite_affine** | SpriteAffineAdapter · h264_nvenc | 90/90 | traj_med=0%, p95=0% (limit 0.5/1.0); contact_p95=0.136%≤1.0; phone effect=1.0 |
| whole_body_rotation | f4_body_rotation | **sprite_affine** | SpriteAffineAdapter · h264_nvenc | 90 keyframes sampled | rot_p95=0°, scale_p95=0%; contact≈0.00001%; clipping probe applicable count 6298, fail_bool=False (asset-level audit, applies_to_routes=[] — không phải pass rỗng) |
| group_occlusion | f5_group_occlusion | **sprite_affine** | SpriteAffineAdapter · h264_nvenc | 120/120 | z_order_inversions=0; required_layer_coverage char_a=74/char_b=80/pillar=40 (>0); char_a effect=0.833≥0.5 |
| semantic_graphic_replacement | f6_graphic_replacement | **sprite_affine** | SpriteAffineAdapter · h264_nvenc | 60/60 | graphic_ratio qua replacement_effect sign=1.0; watermark_leak=0 |

Adversarial source-reencode control: **6/6 FAILED_AS_EXPECTED** (presence ratio 0 < ngưỡng 0.5) — fake output bị chặn ở mọi measured row.

**FAIL_OPEN_QUESTION = 0**: cả 6 risk class required đều có ≥1 route MEASURED_RENDERED_OUTPUT, sample>0, pass frozen thresholds.

## 4. Machine-readable decision

`route_decisions_seed20260823.json` (35,671 bytes, sinh tự động từ frozen inputs — mọi SHA lấy bằng rehash thực, không gõ tay) gồm:
- `inputs.j1_c2_v2_manifest`: path/file_sha/expected/match/files_rehashed_ok/drift/head/frozen_at/supersedes/rows_pin_same_j1.
- `inputs.i03_run_A/i03_run_B`: file SHA, mtime +07, schema/mode/frozen SHA/thresholds policy/non-det fields.
- `determinism_verification`: method + declared fields + core_identical + decoded_same ×6.
- `required_risk_classes_covered`: 6/6 classes, all_six_required_have_measured_pass=true.
- `reference_states`: hai trạng thái RIÊNG (mục 5).
- `fail_open_question_count = 0`.
- `route_decisions[6]`: mỗi entry pin route, measured_state, overall_pass, sample_counts, fps_rational/time_base, toàn bộ metric values+limits+pass từng check, adversarial status, provenance đầy đủ (result_file_sha256, row index, frozen_content_sha256, thresholds/harness SHA, j1_manifest_sha256, selected_route, backend_v3, request_contract_sha256, encoded_artifact_sha256, adapter_output_frame_sha256, decoded_output_hash, input_hashes, artifact_path, seed).

## 5. Reference media verification vs reference benchmark (hai state riêng)

- `reference_media_verification`: **SKIPPED_WITH_REASON** — measured runs của I03-C2 chạy KHÔNG kèm `--reference-media` (media tham chiếu không nằm trong phạm vi frozen inputs của C2; reason ghi rõ trong results).
- `reference_benchmark`: **NOT_RUN** — phụ thuộc media verification + thiếu annotation REF-R01..R05; không fabricate ground truth.
- Hai trạng thái này được copy nguyên xi từ results JSON vào `route_decisions…json` và KHÔNG ảnh hưởng tới 6/6 route decisions (decision chỉ dựa measured rendered output).

## 6. Runtime/VRAM/corrections/license (provenance đo được)

- runtime_ms_per_frame_measured (measured backend wall-time): f1 18.26 · f2 18.26* · f3 8.58* · f4 17.43* · f5 17.14* · f6 20.30* ms/fr (*giá trị run_A; declared non-deterministic giữa A/B, chênh ≤3%). wall_runtime_ms_per_frame end-to-end: 40.06/39.40 (A/B) cho f1.
- vram_peak_mib=0 (không capture GPU memory — khai báo non-deterministic/excluded).
- correction_counts: benchmark không phát hành field correction_counts ở v3 (thay bằng adversarial control per-row); không có correction nào cần thiết trong phiên này.
- License/provenance encode: encode_backend `h264_nvenc` (ffmpeg NVENC build), composite_backend `replacement_layer_anchor_keyframes_cpu_deterministic`, adapter classes PoseSwap/SpriteAffine, request_contract_sha256 pin từng row; backend_id `ffmpeg-nvenc-sprite-affine` / `ffmpeg-nvenc-pose-swap`.

## 7. Self-audit write-set

Tạo phiên này (đúng allowlist mục 10):
1. `output/s09/20260823_sprint_full/t00-i05-c2/route_decisions_seed20260823.json`
2. Append REPORT.md (file này, phần C2) + LOG.md

Không đụng: scripts/, tests/, fixtures, thresholds, app/**, MAIN, data/**, t00-i03-c2/** (read-only). Không git ops. Không session mới.

## 8. Hạn chế khai báo

- Decision dựa trên kết quả measured do I03-C2 sản xuất (run_A/run_B); I05-C2 không tự chạy lại renderer (theo đúng vai trò decision worker, mục 10 chỉ yêu cầu verify SHA rồi quyết định).
- VRAM GPU vẫn unknown (không CUDA capture trong harness v3 tại máy này).
- Reference pipeline tiếp tục SKIPPED_WITH_REASON/NOT_RUN cho đến khi có annotation contract REF-R01..R05 — tách bạch rõ, không cản trở 6/6 route decisions.

STATUS: TASK_SUBMITTED

---

# S09-T00-I05-C3 — REPORT: route decision trên freeze v4 (decision only)

Session owner: `20260823_233406_8d5b7b` (resume đúng owner) · provider custom @ 9Router · model alpha · reasoning max · fallback disabled.
Worktree `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration` · HEAD `ee10e55a809c84d5cb5d4a3046a1ee78828528d0` (không đổi).
Ngày: 2026-08-26 (+07). RULES_LOADED (180 dòng đọc toàn bộ trong lượt). Write-set: `output/s09/20260823_sprint_full/t00-i05-c3/**` + append I05 LOG/REPORT. KHÔNG sửa code/test/fixture/threshold.

## 1. Verify độc lập từ disk trước khi quyết (mọi con số recompute bằng script riêng)

| Claim cần verify | Kết quả độc lập của I05 | Bằng chứng |
|---|---|---|
| J1-C3-v4 file SHA | `ae92247b…f18d0d5` MATCH expected | sha256 file `j1-c3/renderer_freeze_manifest_v4.json` |
| 13/13 files pin, drift NONE | Rehash từng file: **13/13 OK, drift=0** — chạy PRE-decision và POST-decision, hai lần đều sạch | hashlib per file |
| Schema v3, mode RENDERED_OUTPUT, seed 20260823 | Đúng cả run_A lẫn run_B; frozen_content A==B `2c44c219…8a15a6` | header results JSON |
| Mỗi run: 6 MEASURED_RENDERED_OUTPUT (sprite_affine ×5, pose_swap ×1 cho f2) + 6 CONTRACT_REJECTED_BY_FROZEN_CONTRACT | run_A và run_B cùng pattern: f2×pose_swap measured; f1/f3/f4/f5/f6 sprite_affine measured; còn lại rejected | row summary in từng row |
| decoded_output_hash == adapter_output_frame_sha256 cho 12 rows/run | **24/24 rows khớp** (12 run_A + 12 run_B), 0 lệch | compare per row |
| A/B core-identical sau strip timing/path fields | **IDENTICAL** (0 diff) sau strip đúng 4 field declared (`wall_runtime_ms_per_frame`, `vram_peak_mib`, `runtime_ms_per_frame_measured`, `backend.wall_time_ms_total`) + scrub tên thư mục run | diff đệ quy toàn doc |
| decoded hashes A==B 6/6 | **12/12 pairs SAME** (gồm cả 6 measured) | compare per pair |
| Row pin j1_manifest_path=v4 + SHA exact | **6/6 measured rows mỗi run** pin path tuyệt đối `.../j1-c3/renderer_freeze_manifest_v4.json` + SHA `ae92247b…`. Ghi nhận trung thực: 6 rows CONTRACT_REJECTED không có field pin (không render gì — harness để null); decision bỏ qua các row này | per-row check |

Freeze components v4 inputs: fixtures manifest/media giữ nguyên C2 trừ f5 media đổi (`c7301c62…`), harness_source `3085de63…` (bản mới nhất), thresholds `985c659a…` (không đổi từ C2), thresholds_policy `s09-t00-i03-c1-frozen-20260824`.

## 2. Route decision C3 — 6/6 risk classes PASS_MEASURED_ROUTE

Quy tắc: PASS chỉ khi measured_state=MEASURED_RENDERED_OUTPUT + mọi threshold check pass + sample>0 + adversarial control FAILED_AS_EXPECTED + row pin v4 exact. CONTRACT_REJECTED/UNKNOWN/SKIPPED không phải PASS.

| Risk class | Fixture | Smallest passing route | Frames/samples | fps_rational | time_base | Metrics chốt (value ≤ limit) |
|---|---|---|---|---|---|---|
| hard_cut | f1_hard_cut | sprite_affine | 90 decoded / 90 sampled | [30,1] | 1/30 | cut_error=0≤1; traj med/p95=0%; replacement sign=1.0≥0.5 |
| mouth_expression_swap | f2_mouth_swap | pose_swap | 60 decoded | [30,1] | 1/30 | swap_error=0≤1; replacement head=1.0 |
| phone_contact | f3_phone_contact | sprite_affine | 90 decoded / 90 sampled | [30,1] | 1/30 | contact_p95=0.136%≤1.0; traj p95=0%≤1.0; phone=1.0 |
| whole_body_rotation | f4_body_rotation | sprite_affine | 90 decoded / 90 keyframes | [30,1] | 1/30 | rot_p95=0°≤3; scale_p95=0≤3; clipping probe count=6298 fail_bool=False (asset-level audit, applies_to_routes=[] — pass theo ngưỡng fail_bool, không phải pass rỗng); body=1.0 |
| group_occlusion | f5_group_occlusion | sprite_affine | 120 decoded / 120 sampled | [30,1] | 1/30 | z_order_inversions=0≤0; required_layer_coverage char_a=74/char_b=80/pillar=40 đều >0; char_a effect=0.833≥0.5 |
| semantic_graphic_replacement | f6_graphic_replacement | sprite_affine | 60 decoded / 60 sampled | [30,1] | 1/30 | graphic qua replacement sign=1.0≥0.5; watermark_leak=0 |

Adversarial source-reencode control: 6/6 FAILED_AS_EXPECTED.

**fail_open_question_count = 0** — bắt buộc đạt.

## 3. Machine-readable decision document

`route_decisions_c3_seed20260823.json` (38,245 bytes, sinh tự động từ frozen inputs):
- `independent_verification`: j1_c3_v4 (path/file SHA/match/rehash/drift/head/frozen_at), i03_run_A (content SHA `12de1345…d038c3`, mtime +07, schema/mode/frozen/thresholds policy/non-det fields), i03_run_B (content SHA `dab37e41…ab40`), row_level_checks (decoded==adapter 24/24, measured pin v4 ok, rejected rows note), determinism (core identical True, decoded same 12/12).
- `route_decisions[6]`: smallest_passing_route, decision_status, sample_counts, frames_rendered, fps_rational, time_base, toàn bộ metrics value/limit/pass, adversarial status, provenance đầy đủ.
- Provenance per decision pin **v4-only**: `freeze_chain="J1-C3-v4-only"`, j1_manifest_path+SHA v4, benchmark_results_content_sha256 = run_A content SHA, frozen_content_sha256, thresholds/harness/fixture manifest+media SHA từ freeze_components của run_A v3-v4, backend_v3 (ffmpeg-nvenc-*-sprite-affine/pose-swap · h264_nvenc · SpriteAffine/PoseSwapAdapter), request_contract_sha256, encoded_artifact_sha256, adapter_output_frame_sha256, decoded_output_hash, input_hashes, artifact_path, seed.
- Audit v4-only: grep machine `i05-c2|t00-i03-c2|manifest_v2|manifest_v3|j1-c2` trong decision doc → **0 hit** (duy nhất chuỗi mô tả policy "no C2/v2/v1 pinned"). Không pin bất kỳ SHA/path của C2/v2/v1/v3 vào bất kỳ field nào.
- Reference states giữ hai trạng thái riêng: reference_media_verification=`SKIPPED_WITH_REASON` (media tham chiếu không thuộc frozen inputs C3) ≠ reference_benchmark=`NOT_RUN` (thiếu annotation REF-R01..R05).

## 4. Self-audit write-set

Tạo phiên này:
1. `output/s09/20260823_sprint_full/t00-i05-c3/route_decisions_c3_seed20260823.json`
2. Append REPORT.md (phần C3) + LOG.md

Temp script sinh decision nằm ngoài worktree (%TEMP%) và đã xóa sau khi dùng. Không đụng scripts/tests/fixtures/thresholds/app/MAIN/data, t00-i03-c3 chỉ đọc. J1 rehash POST-decision: drift=0. Không git ops, DB env UNSET suốt phiên.

## 5. Ghi minh bạch quá trình

- Script generate đầu tiên của tôi báo FOQ=6 và det_core=False do 2 bug của chính script (so sánh path pin tuyệt đối với đường dẫn tương đối; strip nhầm empty-drops) — đã root-cause bằng diff standalone (n_diff=0 với logic đúng), sửa script rồi regenerate; kết quả cuối được xác nhận lại bằng lệnh thật, không phải tin output cũ.

STATUS: TASK_SUBMITTED
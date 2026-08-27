# S09-T00-I03 — LOG

Session: 20260823_173318_69a813 · worker implementation · provider custom @ 9Router · model alpha · reasoning max · fallback disabled.

## Preflight (2026-08-23 18:08 +07)

- RULES_LOADED: C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (180 dòng, toàn bộ).
- Overlay TARGET_PROFILE_2D_SOURCE_LOCKED.md đọc toàn bộ (526 dòng) — §8 thresholds đóng băng, §4 risk classes.
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration · branch codex/s08-integration · HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204.
- MOTIONFORGE_DATABASE_URL = UNSET (verified trong shell).
- Toolchain: ffmpeg 8.1.2-full (gyan) + Python 3.11.9 + numpy 2.4.4 + pillow 12.2.0.
- Dirty tree sẵn có từ task khác (app/**, docs/pm/S06-T05, frontend/**…) — baseline ghi nhận, task này KHÔNG đụng.
- Verified reference: SHA-256 5A175454C2C2965BAC5013A53926E210A9F70A185D802D0F2E0083A6FB399FA2 (36,971,916 bytes) — tìm thấy tại C:/Users/Admin/MotionForge2D/projects/2dc14177a212/Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4 và …/4503582811e8/… (sha256sum chạy thật, khớp fingerprint overlay §1). Chỉ ĐỌC.
- Schema tham khảo (READ-ONLY): app/persistence/structural_lock.py — RENDERER_ROUTES 5 giá trị, anchor [0,1], fail-closed validation.
- Lane-C reference số (context TASK.md): timebase roundtrip 240/240 mismatch=0; centroid residual median 1.75px / P95 22.15px; cost 0.90ms/frame.

## Plan

1. Fixture generator (ffmpeg testsrc/gradients/smptebars + Pillow sprites) → 6 fixtures khớp 6 risk classes T03.
2. Harness scripts/s09_renderer_benchmark.py: FREEZE schema_version=1 + content SHA trước đo; routes pose_swap + sprite_affine; metrics đầy đủ; deterministic same-seed.
3. Tests test_s09_t00_benchmark*.py: determinism, formulas, skip-with-reason, fail-closed manifest.
4. Gates: focused tests ×2 basetemp, ruff, mypy scripts, git diff --check.
5. Measured runs + dry-run + reference eval → output/s09/20260823_sprint_full/t00-i03/.

## Execution (2026-08-23 19:05 → 22:4x +07, resume ×2 sau khi process bị kill)

### Deliverables
1. `tests/fixtures/s09_renderer/generate_fixtures.py` — generator 6 fixtures SYNTHETIC (ffmpeg lavfi gradients/smptebars seed-pinned + Pillow sprites + libx264 bitexact), manifest JSON ground-truth đầy đủ (trajectories/contacts/swaps/motion/visibility/z_order/graphics/pose_layer/clipping_probe/thresholds copy-along).
2. `tests/fixtures/s09_renderer/thresholds.json` — FROZEN schema_version=1 trước measured run đầu tiên; generator copy theo fixture set.
3. `scripts/s09_renderer_benchmark.py` — harness CLI `--routes --fixtures --out --seed [--dry-run] [--reference-media]`; FREEZE banner in schema_version=1 + frozen SHA TRƯỚC mọi đo; metrics: frame/timebase/cut error, trajectory median/P95 %diagonal, scale P95 %, rotation P95 °, contact P95 %, z-inversions, unexplained visibility (probed-universe), clipping audit, graphic ratio, watermark leak scan, corrections, wall ms/frame, VRAM peak (CUDA optional); route-capability gates (pose_state_capability, contact_capability) — không fabricate evidence.
4. `tests/test_s09_t00_benchmark_harness.py` — 19 tests.

### Sự cố đã root-cause (không bao biện)
- ffmpeg 8.1.2 từ chối `-movflags +bitexact` → flag toàn cục `-bitexact`.
- `gradients` seed mặc định random → pin seed từng fixture → determinism ALL-IDENTICAL.
- f5 bàn thấp không che kín → redesign trụ full-height; cửa sổ fully-hidden [28,45] tính hình học chính xác.
- Patch vô tình XÓA `trajectory_median_pct` (phiên chết giữa chừng) → resume R2 trả lại dòng + thêm annotated_swaps/pose_states_measured.
- Generator không copy thresholds.json → test fail fail-closed → thêm copy-along.
- mouth_crop cắt nhầm video-space coords lên sprite 100px → crop rỗng crash cvtColor → quy đổi local qua pose_layer.center_xy + guard BenchmarkError.
- Estimator similarity grid cố định ±2° không theo được envelope 0→90° → đổi CHAINED tracking (start transform = contract, boundary-expansion hill climb, KHÔNG đọc GT).
- Unexplained visibility so GT full-range vs samples stride-3 → giới hạn universe ở probed_frames.
- Clipping probe gán lỗi asset cho route vô tội → chuyển thành ASSET AUDIT (applies_to_routes do fixture author khai báo) + detector validate bằng injection test.
- Contact anchor f4 (340,262) sai hình học render (body xoay quanh pivot 220,190) → re-anchor trung thực body_rest_center_final (220,190).
- Measured run 1 dùng MSYS path `/c/Users/...` cho --reference-media → Python-Windows không thấy → SKIP_WITH_REASON oan; chạy lại path Windows `C:/Users/...` → VERIFIED.

### Gates cuối (logs/gates_final4.log)
- mypy scripts/s09_renderer_benchmark.py: PASS (exit 0).
- ruff check scripts tests: PASS ("All checks passed!").
- pytest focused ×2 basetemp khác nhau (s09t00i03-r7a/r7b): 19 passed × 2 (exit 0/0).
- git diff --check: CLEAN.
- Same-seed byte-identical: run1 vs run2 (loại wall_runtime_ms_per_frame/vram_peak_mib): IDENTICAL=True.

### Measured run chính thức (fixtures_gen, seed 20260823, routes pose_swap+sprite_affine)
- FROZEN content SHA256: 0ba6f6460f281028a6fde638273e149f19bc472556e1b67534738efbee555b44 (in stdout TRƯỚC đo, log measured_run_final.log).
- Kết quả 12 runs (6 fixtures × 2 routes): 11 PASS / 1 FAIL.
- FAIL duy nhất: f2_mouth_swap × sprite_affine — pose_state_capability not_measured (route rigid không có năng lực swap trong contract) — ĐÚNG thiết kế phân biệt route, không phải lỗi harness.
- Reference eval: VERIFIED sha256 5a175454… (36,971,916 bytes), platform ghi trong JSON.

## S09-T00-I03-C1-PREP — resume owner (2026-08-24 21:55 +07)

- RULES_LOADED (toàn bộ 180 dòng) + review S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md (F2 P0) + fast-track prompt mục 5.
- PREFLIGHT_OK: worktree s08-integration, branch codex/s08-integration, HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0 (khớp checkpoint review). MOTIONFORGE_DATABASE_URL=UNSET. Dirty tree = các worker C1 song song (app/**, frontend/**) — không đụng, không revert.
- Evidence v1 giữ immutable: output/s09/20260823_sprint_full/t00-i03/** chỉ ĐỌC từ đây; mọi ghi mới vào t00-i03-c1/**.
- Phạm vi PHIÊN NÀY: PREP Wave A — schema/policy v2 + freeze TRƯỚC đo, harness v2 rendered-output pipeline (backend thật chờ J1), f5 coverage, adversarial control, tách reference media/benchmark, tests ×2. KHÔNG chạy measured run (Wave B sau J1).

### PREP implementation (2026-08-24 21:55 → 23:1x +07)

#### 1. Fixtures v2 — render plates + render_contract (generator)
- `emit_source_plate()` / `static_plate_frames()`: mỗi fixture có SOURCE PLATE bitexact riêng — đầu vào thật cho renderer ở Wave B:
  - f1: plate = chính media (cut fixture, không replacement);
  - f2: plate = bg + torso KHÔNG head; replacement = head_closed_rep/head_open_rep + state_schedule [0-14 closed,15-29 open,30-44 closed,45-59 open] + placement_center_xy;
  - f3: plate = bg only; contract có `plate_layers` (character) + replacement phone với positions_by_frame đầy đủ;
  - f4: plate = bg + bed; replacement body affine_keyframes (rotation/scale per frame, start identity = route contract);
  - f5: `emit_f5_plate()` — plate = bg + pillar + charB, charA LÀ replacement z=0 (renderer phải composite SAU pillar theo z_order); manifest thêm `required_layers: ["char_a","char_b","pillar"]`;
  - f6: plate = bg only; replacement sign; watermark vẫn source-only must_be_absent.
- Mọi asset trong contract đều pin SHA-256 file.

#### 2. Harness v2 (`scripts/s09_renderer_benchmark.py`)
- SCHEMA_VERSION=2; thresholds.json nâng v2 policy `s09-t00-i03-c1-frozen-20260824` (giá trị ngưỡng GIỮ NGUYÊN từ v1 — không tune; freeze TRƯỚC measured run).
- Fail-closed trước J1: `_detect_contract_freeze()` tìm token `T02_CONTRACT_FROZEN_FOR_I03` trong session registry; chưa thấy → mọi measured entry chỉ là `PENDING_RENDERER_CONTRACT_FREEZE` (không metrics, không threshold_evaluation), measurement_mode=BLOCKED_PENDING_J1.
- Wave-B path đã dựng sẵn: `render_and_measure_v2()` (resolve contract → RenderRequest theo contract frozen T02 → render → decode OUTPUT → score), cấm scoring source frames khi thiếu artifact renderer.
- Adversarial control (F2): `adversarial_source_reencode_control()` — re-encode plate thay output; `_replacement_presence_stats()` đo presence ratio từng replacement layer (rotation-aware NCC); presence<0.5 → FAILED_AS_EXPECTED → gate `adversarial_source_reencode_control` đỏ. Đã test thật trên f3: phone presence = 0 < 0.5 → control FAILED_AS_EXPECTED ✓.
- f5 coverage (F2): sprite_for map thêm char_a/char_b/pillar; khối static-layer probing mới (seed point từ visibility contract, track tự do) → char_a/char_b/pillar đều có visible+probed samples > 0; `required_layer_sample_counts` vào metrics; gate `required_layer_coverage:<layer>` value>0 bắt buộc — empty/unmeasured giờ là FAIL cấu trúc, không thể auto-pass.
- Reference tách đôi (F2): `evaluate_reference_media()` trả MEDIA_VERIFIED (chỉ SHA/ffprobe); `evaluate_reference_benchmark()` trả SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE nếu thiếu annotation contract REF-R01..R05; contract thiếu loop → FAILED_CONTRACT_COVERAGE; media chưa verify → NOT_RUN. CLI thêm --reference-annotation-contract.
- Self-test mode: `--self-test-source-observation` giữ estimator stack chạy được để calibration; kết quả gắn nhãn SELF_TEST_SOURCE_OBSERVATION_NON_EVIDENCE, không bao giờ dùng làm bằng chứng route.

#### 3. Gates cuối (logs/gates_prep5.log)
- mypy scripts/s09_renderer_benchmark.py: exit 0.
- ruff check (3 file của task): All checks passed!, exit 0. Ghi nhận attribution: `ruff check scripts tests` toàn scope còn 1 lỗi E741/F401 trong tests/test_s09_t05_backend_domain.py — thuộc owner T05A-C1 (file ngoài write-set, không đụng).
- pytest focused ×2 basetemp khác nhau (i03c1-p5-a/p5-b): **26 passed × 2**, exit 0/0.
- git diff --check: CLEAN.
- V1 evidence immutable: sha256sum -c v1_evidence_sha_before_prep.txt → OK (be4af379… không đổi).
- Dry-run v2 chính thức: freeze banner schema v2, frozen_content_sha256 = 8e84b1fa37ddf2ee3561742e43142076f1848f60b35cdecb075bcf08ce67fa0f (14 components), plan 6 fixtures; artifact lưu tại t00-i03-c1/benchmark_results_seed20260823.json.

#### Sự cố vận hành phiên
- gates_prep1: 4 mypy errors (no-redef table/present do patch chèn trùng tên; Fixture.media_sha256 không tồn tại) + 3 ruff (E741 biến l, F841 fid chết, F401 file T05A) + thresholds schema_version 1 bị harness v2 từ chối → sửa toàn bộ: đổi tên biến, sha256 tính tại chỗ, thresholds.json lên v2, bỏ biến chết, đổi `l`→`loop`. F401 T05A ghi attribution cho đúng owner.
- gates_prep2 còn 1 mypy (p0 no-redef) + 2 test cũ đòi `[run]`/verdict → sửa test freeze chấp nhận `[pending]`, test capability chuyển sang self-test mode.
- Dry-run đầu không ghi file JSON (return sớm) → bổ sung write_text cho dry-run path.

## Wave B — J1 handshake + tích hợp renderer thật (2026-08-24 → 25, resume owner)

### J1 verify
- Preflight lại: branch codex/s08-integration, HEAD ee10e55, J1 SHA tính lại trên disk = 46c6a41f2e0959736fe570b37fda564c0e330e64248e6171f6a7d4fb404bbc1e KHỚP handshake.
- Detector mở rộng quét đúng registry C1 (`S09-C1-SESSION-REGISTRY.md`); fail-closed test chuyển sang env hook `S09_FORCE_J1_PENDING=1`.

### Tích hợp renderer thật vào render_and_measure_v2()
- `_build_render_request()`: map contract JSON → typed RenderRequest frozen T02; asset pin SHA drift → BenchmarkError.
- Render thật: composite lại `plate_layers` (f3 character, f4 bed) qua `_alpha_composite_into` rồi gọi `composite_pose_swap_frames` / `composite_sprite_affine_frames`; encode qua bề mặt CÔNG KHAI `write_frames_mp4(extra_output_opts=libx264 CRF12)` (mp4v mặc định gây nhiễu nén làm tracker lệch ở f3).
- CONTRACT_REJECTED fail-closed: route thiếu capability + z-order honesty cho f5 (replacement z=0 nằm SAU pillar/char_b nhưng mặt bằng frozen không có tham số z → từ chối thay vì render sai im lặng; phát hiện bằng tracker lock nhầm lên char_a đi ngang).
- Adversarial control giữ nguyên thiết kế: presence detector rotation-aware.

### Root-cause bằng pixel-probe (không đoán)
- f2 head dán (0,0) → placement phải lấy `placement_center_xy` (composite không crop bbox) → presence 1.0.
- f4 rotation lệch chiều: probe pixel xác chứng frozen `_warp_layer` quay CW (cv2) trong khi GT fixture vẽ CCW (PIL rotate) → presence probe chấp nhận 2 convention.
- f3 traj_med 0.865%→0.068% sau khi composite plate_layers đúng contract.
- f5: char_b tracker score rơi 0.9975→0.9207 tại frame 48-54 khi char_a cắt ngang → chứng minh replacement cần nằm SAU foreground → CONTRACT_REJECTED là hành vi đúng.
- Plateau escape trong vòng tìm kiếm `estimate_position`; stale-bytecode nghi vấn ở smoke_full3/4 được loại trừ bằng replication thủ công + observe_route trực tiếp.

### Measured results (GIỮ NGUYÊN, không đo lại)
- smoke_full8 (`output/s09/20260823_sprint_full/t00-i03-c1/smoke_full8/`, seed 20260823): measurement_mode=RENDERED_OUTPUT; 4 measured MEASURED_RENDERED_OUTPUT ĐỀU PASS (f2 pose_swap out_sha fa080507…, f3/f4/f6 sprite_affine out_sha 23548d59…/ce6c16ee…/57d25575…); f5 sprite_affine CONTRACT_REJECTED (z-order); 12 rejection khác là capability_mismatch đúng thiết kế; adversarial source-reencode control FAILED_AS_EXPECTED ×4/4.
- det_A/det_B same-seed ×2: decoded_output_hash SAME cả 4; metrics IDENTICAL sau khi loại telemetry khai báo (wall_runtime_ms_per_frame) và artifact PATH run-scoped.
- Evidence hashes chốt trước gates: smoke_full8=16e71d14…, det_A=8e71a6b0…, det_B=6c8d18c6…; sha256sum -c sau gates → OK (không file nào đổi).

### Gates cuối phiên này (2026-08-25 03:4x +07)
- Sửa nợ ruff/mypy: bỏ 5 `type: ignore[arg-type]` thừa sau khi `common` lên `dict[str, Any]`; narrowing `built` → RenderRequest qua cast + guard None cho input_media; khôi phục dòng `wall_ms` bị mất trong self-test entry; tách dòng E501 ×8.
- Test updates post-J1: `_strip_nondet()` thêm loại `artifact_path` + `adversarial_artifact` (run-scoped PATH, không phải measurement); `artifact_path` lưu dạng str; `test_pose_swap_vs_sprite_affine_capability_difference` viết lại theo hành vi RENDERED_OUTPUT thật (pose measured PASS vs sprite_affine CONTRACT_REJECTED capability_mismatch) — không còn phụ thuộc self-test mode đã chết sau J1.
- pytest ×2 basetemp `%TEMP%/s09i03-j1a` / `-j1b`: **29 passed × 2**, PYTEST_EXIT=0/0 (logs/gates_waveb_j1a_pytest.log, gates_waveb_j1b_pytest.log).
- mypy scripts/s09_renderer_benchmark.py: Success, MYPY_EXIT=0.
- ruff scripts+tests: All checks passed!, RUFF_EXIT=0.
- MOTIONFORGE_DATABASE_URL = UNSET suốt phiên (mọi lệnh env -u). Không đụng app/**, MAIN, data/**. Không commit/push.

## 2026-08-25 15:06 +0700 — C2-PREP RESUME PREP-FIX (owner 20260823_173318_69a813)

- Manager verify blocker: pytest đỏ loạt vì `thresholds schema_version must be 3, got 2` — SCHEMA_VERSION đã bump 3 nhưng thresholds.json còn 2. FIX: bump `tests/fixtures/s09_renderer/thresholds.json` → schema_version=3, supersedes v2 (evidence C1 giữ tại t00-i03-c1/), note ghi rõ v3 = public-surface + provenance pinning. **KHÔNG đụng bất kỳ threshold value nào** (diff chỉ version/policy metadata).
- Re-pin J1-C2 freeze: disk contract SHA hiện tại (sau khi T02-C2 landed) = `d7d8b60e641b491297e039df3f41b19e1990a48b024205cd21679c03e5f38146`; cập nhật `RENDER_CONTRACT_FROZEN_SHA256` + ghi machine-readable manifest `output/s09/contract_freeze_manifest.json` qua `--write-freeze-manifest`. `_detect_contract_freeze()` giờ frozen=True với evidence `manifest=... | registry ... | disk contract SHA verified`.
- Sửa path bug phát hiện khi re-run: adapter giờ tự encode ra `request.output_media`, nhưng request trỏ vào fixtures/rendered (vi phạm mục 4 prompt). FIX: `output_media=out_path` (run artifacts dir trực tiếp), `workspace_root = commonpath(fixtures_dir, artifacts_dir)` thoả containment — KHÔNG render vào tests/fixtures/**/rendered.
- Record-v3 fields giờ được propagate từ plan_record vào entry kết quả (backend_v3, selected_route, j1_manifest_sha256, encoded_artifact_sha256, frame_count_rendered, fps_rational, time_base, runtime_ms_per_frame_measured, metrics_sample_count, contract_freeze_post_run).
- Determinism: thêm runtime fields vào NON_DETERMINISTIC_FIELDS (cả harness lẫn test): `runtime_ms_per_frame_measured`, `backend.wall_time_ms_total` — cùng lớp wall-clock noise; verified A/B diff thực tế chỉ còn 2 field này.
- Tests cập nhật schema v3: banner `(schema v3)`, doc.schema_version==3, wave_b asserts backend_v3/selected_route/j1_manifest 64-hex/encoded_artifact_sha/fps_rational [30,1], drift test assert evidence chứa `manifest=`.
- Gates chốt: pytest ×2 basetemp `%TEMP%/s09i03-c2-fix-a` / `-fix-b` = **29 passed × 2** EXIT=0/0; mypy --strict scripts = Success EXIT=0; ruff scripts+tests+generator = All checks passed EXIT=0.
- [VERIFY tươi sau fix 15:06] pytest basetemp `%TEMP%/s09i03-c2-fix-verify`: **29 passed in 51.54s** PYTEST_VERIFY_EXIT=0; ruff scripts+tests+generator: All checks passed! RUFF_EXIT=0; mypy --strict scripts: Success MYPY_EXIT=0. Evidence: output/s09/20260823_sprint_full/t00-i03-c2/{pytest_fix_verify,ruff_verify,mypy_verify}.log

## 2026-08-25 16:40 +0700 — RESUME WAVE B: S09-T00-I03-C2 MEASURED RUN (owner 20260823_173318_69a813)
- B0 PRE-RUN MANIFEST VERIFY: 13/13 files hash-match, manifest file SHA == 1d854969ce01ef494a5712d9bb26807c9e46a6459cc8b672b4db90c2ad4d3c98 -> GO.
- Harness updates (write-set only): j1 pin = J1-C2 manager manifest (file SHA), f5 sprite_affine z-honesty check now derives occluder window from layer_order entries; estimator honesty fixes: trajectory errors only from confident sightings (NCC>=presence bar) + identity-ambiguity band derived from GT tables with REAL sprite bbox dims; deterministic full-frame template probe for static occluders without trajectory tables (pillar); mypy no-redef rename present_occl/probed_occl.
- RUN A: EXIT=0 output/s09/20260823_sprint_full/t00-i03-c2/run_A/ - 12 results; 6 MEASURED_RENDERED_OUTPUT (f1..f6 via sprite_affine trừ f2 qua pose_swap), pose_swap rejected capability_mismatch trên 5 fixture (thiếu pose_schedule) - đúng contract routing.
- RUN B same-seed: EXIT=0 run_B/ - encoded_artifact_sha256 A==B cho cả 6 class; core-identical TRUE sau strip declared non-det fields (artifact_path/adversarial_artifact là run-scoped paths).
- ADVERSARIAL: 6/6 FAILED_AS_EXPECTED (source_reencode_substitution detected).
- V3 PROVENANCE 6/6: selected_route, backend_v3 (adapter/backend_id/license_id/nvenc_provenance/composite/encode), request_contract_sha256=d7d8b60e..., j1_manifest_sha256=1d854969..., encoded+decoded SHA, frame_count, fps_rational [30,1], time_base 1/30, runtime/frame, sample counts, contract_freeze_post_run.
- POST-RUN MANIFEST VERIFY: 13/13 match, file SHA unchanged -> NO DRIFT.
- VERDICT: 5/6 PASS (f1,f2,f3,f4,f6). f5_group_occlusion MEASURED + FAIL trung thực: z_inv=6, unexplained=6 (window samples 30..45). Root cause (probe kỹ): frozen surface _draw_occluders với bbox=None stretch pillar FULL-FRAME trong window -> che luôn char_b (renderer faithful tới placement contract nhưng lệch visibility GT của char_b). Không tune threshold, không sửa renderer. FINDING cho Manager.
- TESTS: pytest 29 passed x3 basetemp (waveb-t1 51.84s, waveb-t2, waveb-t3 51.82s); ruff EXIT=0; mypy --strict script EXIT=0.

## 2026-08-25 17:05 +0700 — WAVE B-FIX: J1 DRIFT SCHEDULED (owner 20260823_173318_69a813)
- Manager decision (ba-scope, mục 3.2 prompt C2): option (b) — MỞ SCOPE RENDERER cho per-region occluder placement. group_occlusion là required class; contract reject/fail ở sprint exit KHÔNG được chấp nhận.
- I03 hành động theo packet:
  1. STOP mọi đo đạc measured hiện tại (run_A/run_B v1 giữ nguyên làm evidence v1).
  2. composite.py verify: KHÔNG đụng (git diff chỉ chứa thay đổi T02-C2 đã có từ trước, không thêm gì mới từ phiên này).
  3. Finding F-WB1 đã đầy đủ trong REPORT (root cause + 3 options + evidence probe). Không tune threshold.
- Chờ Manager: resume T02-C2 owner sửa typed contract + compositor -> invalidate manifest 1d854969... -> pin J1-C2-v2 -> resume lại I03 với packet re-run f5 (an toàn: rerun full A/B).
- Session EXIT tại đây. STATUS giữ TASK_SUBMITTED (measured run v1, f5 FAIL documented).

## 2026-08-25 18:10 +0700 — MEASURED RE-RUN v2 (owner 20260823_173318_69a813, J1-C2-v2 pinned)
- R0 PRE-RUN VERIFY: manifest_v2 13/13 files hash-match; manifest file SHA == aa405015856432e5985106741aea4702d4e4f12c08077bec437c3672e8728c91.
- Harness re-pin: RENDER_CONTRACT_FROZEN_SHA256 d7d8b60e... -> ea8ab21187850a0bd481ba546e8ffe0439dd7d48ec9359c9ffab83f7c1d5d8fb (disk v2 handshake); machine manifest refreshed (token + ea8ab211 + J1-C2-v2 reference); _detect_contract_freeze=True. j1 pin trong record giờ đọc manifest v2 trước (v1 fallback).
- R1 FIXTURE f5 v2 (write-set tests/fixtures/**): pillar sprite 130->310px (opaque core x4..306), compose center (372,180) => core abs 221..523; occluder_regions pillar=[217/640,0,310/640,1]; char_b 480->100 (span 18..182) vì sandwich order (occluder above replacement AND plate content) sẽ che char_b khi overlap — GT visibility [0..119] giữ nguyên; hide window [28..45] GIỮ NGUYÊN và giờ geometry đúng (char_a span tại f28=[222,386], f45=[358,522] nằm trọn trong [221,523]); regen media+manifest+index, chỉ f5 đổi (f1-f4/f6 SAME byte-for-byte); thresholds.json values nguyên vẹn.
- R2/R3 RUN A + B same-seed EXIT=0: 6/6 class MEASURED_RENDERED_OUTPUT overall_pass=True (lần đầu đủ binary target); f5: z_inv=0, unexplained=0, traj 0/0%, replacement_effect char_a=0.833.
- ADVERSARIAL source_reencode_substitution: 6/6 FAILED_AS_EXPECTED.
- DETERMINISM: core JSON identical sau strip declared fields; encoded_artifact_sha256 A==B cả 6 class; j1_manifest_sha256=aa405015... trên toàn bộ records.
- R5 POST-RUN VERIFY: 13/13 files match, no drift. pytest 29 passed ×2 basetemp mới (rerun-t1 48.75s, rerun-t2 48.57s); ruff EXIT=0 (scripts+tests+generator); mypy --strict script EXIT=0.

## 2026-08-25 — C3: unified freeze authority + canonical hash (owner 20260823_173318_69a813)
- READ: docs/pm/reviews/S09_C2_PM_REVIEW_2026-08-25.md (F2 P0, F3 P1) + prompt S09_C3_CORRECTION_MANAGER_2026-08-25.md §3.3/§5. RULES_LOADED 37/37.
- C3-0 PRE-RUN: j1-c3/renderer_freeze_manifest_v4.json file-SHA == ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5; 13/13 files re-hash clean.
- A1 SINGLE AUTHORITY: CLI --manifest-path/--manifest-sha256 (+ pinned J1-C3-v4 defaults); _detect_contract_freeze rewritten — chỉ verify Manager manifest (file SHA + mọi path→hash), fail-closed. Verified: default True, explicit True, wrong-SHA False, missing False, three-file pin False. Handshake constant/3-file helpers giữ lại CHỈ với docstring DEPRECATED + không còn đường gọi active trong measured pipeline (--write-freeze-manifest removed).
- A2 PROVENANCE: mỗi measured row ghi j1_manifest_path (exact) + j1_manifest_sha256 (= ae92247b…).
- A3 CANONICAL INDEPENDENT (F3): canonical_decoded_hash_independent() tự implement count+shape+bytes (str(tuple(shape))), KHÔNG import/call production canonical_frame_sha256; frames lấy qua public decode_rgb_frames. Repro F3 trên artifact C2: raw-concat 0ea2f331… ≠ canonical 4dfd4f99… → confirmed bug cũ. Per-row assert equality adapter output_frame_sha256; lệch → CANONICAL_HASH_MISMATCH / CANONICAL_HASH_EVIDENCE_MISSING (fail-closed, không PASS).
- A4 ADVERSARIAL TESTS: test_c3_canonical_hash_is_count_shape_bytes_not_raw_concat (raw-concast regression guard, order/count sensitivity); test_c3_freeze_authority_single_manifest_no_fallback; test_c3_cli_rejects_incomplete_manifest_flags; test_c3_measured_rows_pin_v4_manifest_and_canonical_equality.
- B RERUN: t00-i03-c3/run_A + run_B same-seed 20260823 EXIT=0 — 6/6 class MEASURED_RENDERED_OUTPUT overall_pass=True; 12 rows v4 pin + canonical==adapter TRUE; adversarial source_reencode 6/6 FAILED_AS_EXPECTED; determinism core-identical sau strip declared fields; encoded_artifact_sha256 A==B ×6. C2 evidence (t00-i03-c2/**) không đụng.
- D POST-GATES: manifest v4 post-run 13/13 no drift; pytest ×2 basetemp mới (c3-t1 33 passed 76.07s EXIT=0; c3-t2 33 passed 76.34s EXIT=0); ruff scripts+tests EXIT=0; mypy --strict script EXIT=0.

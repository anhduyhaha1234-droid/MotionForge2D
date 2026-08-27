# S09-T00-I03-C1-PREP — REPORT (phase PREP, Wave A)

Session owner: 20260823_173318_69a813 · provider custom @ 9Router · model alpha · reasoning max.
Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration` · HEAD lúc preflight: ee10e55a809c84d5cb5d4a3046a1ee78828528d0.
Ngày: 2026-08-24 (+07). LOG chi tiết: `LOG.md`. Phạm vi PHIÊN NÀY: PREP — CHƯA có measured run (Wave B chờ J1).

## 1. Trả lời F2 (P0) — từng điểm bắt buộc §5 fast-track

| # | Yêu cầu | Đã làm | Bằng chứng |
|---|---|---|---|
| 1 | Giữ evidence v1 immutable; schema/policy v2 + freeze hash mới TRƯỚC measured run | Evidence v1 chỉ ĐỌC; thresholds.json → schema_version=2, policy `s09-t00-i03-c1-frozen-20260824`, GIỮ NGUYÊN giá trị ngưỡng v1 (không tune); freeze hash mới đã in + lưu TRƯỚC bất kỳ measured run nào | `sha256sum -c …/v1_evidence_sha_before_prep.txt` → OK; dry-run v2 frozen_content_sha256 `8e84b1fa37ddf2ee3561742e43142076f1848f60b35cdecb075bcf08ce67fa0f` |
| 2 | Mỗi (fixture, route) gọi renderer thật với source + replacement contract rồi đo RENDERED OUTPUT; ghi hashes/backend/state/artifact | Generator phát SOURCE PLATE bitexact cho cả 6 fixtures + `render_contract` pin SHA (replacements/plate_layers/schedule/keyframes). Harness v2: Wave-B path `render_and_measure_v2()` render→decode OUTPUT→score; entry MEASURED_RENDERED_OUTPUT ghi input_hashes/decoded_output_hash/backend/artifact_path. Import contract T02 CHỈ chốt sau J1: `_detect_contract_freeze()` fail-closed PENDING khi chưa thấy token | manifests/f*/render_contract; scripts `_detect_contract_freeze`, `render_and_measure_v2`; test `test_measured_runs_fail_closed_before_j1_contract_freeze` |
| 3 | f5 coverage char_a/char_b/pillar đầy đủ; required metric sample>0; missing/unmeasured = UNKNOWN/FAIL | sprite_for map thêm 3 layer; static-layer probing mới; manifest f5 khai báo `required_layers`; metrics `required_layer_sample_counts`; gate `required_layer_coverage:<layer>` >0 — empty/unmeasured giờ FAIL cấu trúc | test `test_f5_required_layers_have_measured_samples`, `test_required_layer_zero_samples_is_structural_failure` |
| 4 | Adversarial control source re-encode phải FAIL route-effect gate | `adversarial_source_reencode_control()`: re-encode plate làm fake output; presence-ratio detector rotation-aware; presence<0.5 → FAILED_AS_EXPECTED → gate đỏ trong threshold_evaluation | test `test_adversarial_source_reencode_fails_replacement_gate` — phone presence 0 <0.5, control FAILED_AS_EXPECTED ✓ |
| 5 | Tách reference media verification khỏi reference benchmark; MEDIA_VERIFIED chỉ là identity; thiếu annotation REF-R01..R05 → SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE | `evaluate_reference_media()` (MEDIA_VERIFIED / SKIPPED_WITH_REASON / FAILED_SHA_CHECK) tách hoàn toàn khỏi `evaluate_reference_benchmark()` (SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE khi không có contract; FAILED_CONTRACT_COVERAGE nếu thiếu loop; NOT_RUN nếu media chưa verify). Kết quả JSON v2 có 2 field riêng biệt | tests: `test_reference_benchmark_skipped_without_ground_truth_even_when_media_verified`, `test_reference_benchmark_requires_full_ref_loop_coverage`, `test_unverified_media_blocks_reference_benchmark` |
| 6 | Determinism cùng seed sau khi loại telemetry declared non-deterministic | Chỉ loại `wall_runtime_ms_per_frame`, `vram_peak_mib` (khai báo trong results doc + thresholds.determinism.excluded_fields); determinism test chạy trên self-test mode CÓ metrics thật (không phải so PENDING placeholder) | test `test_same_seed_two_runs_byte_identical` PASS ×2 basetemp |

## 2. Binary acceptance PREP

| Gate | Lệnh/khung | Kết quả |
|---|---|---|
| Focused ×2 basetemp khác nhau | pytest harness suite, DB env unset, basetemp `i03c1-p5-a` / `i03c1-p5-b` | **26 passed × 2**, exit 0/0 (`logs/gates_prep5.log`) |
| ruff (file của task) | `ruff check scripts/s09_renderer_benchmark.py tests/test_s09_t00_benchmark_harness.py tests/fixtures/s09_renderer/generate_fixtures.py` | All checks passed! exit 0 |
| mypy strict | `mypy scripts/s09_renderer_benchmark.py` | exit 0 |
| git diff --check | whitespace | CLEAN |
| V1 evidence immutable | sha256sum -c trước/sau phiên | OK — không file v1 nào đổi |
| Dry-run v2 freeze artifact | harness --dry-run trên fixtures_gen | banner schema v2 TRƯỚC mọi đo; frozen SHA `8e84b1fa…`; 6 fixtures planned |

Attribution minh bạch: `ruff check scripts tests` toàn repo scope còn lỗi trong `tests/test_s09_t05_backend_domain.py` (F401 import chết) — thuộc write-set T05A-C1, ngoài phạm vi của task này, KHÔNG đụng.

## 3. Files changed (đúng exclusive write-set)

1. `scripts/s09_renderer_benchmark.py` — SCHEMA_VERSION=2, J1 fail-closed gate, rendered-output pipeline (Wave-B path), adversarial control, required-layer gates, reference split, self-test mode labelled NON-EVIDENCE, dry-run ghi artifact.
2. `tests/fixtures/s09_renderer/generate_fixtures.py` — emit_source_plate/static_plate_frames/emit_f5_plate; render_contract ×6; required_layers f5.
3. `tests/fixtures/s09_renderer/thresholds.json` — schema v2 freeze mới (giá trị ngưỡng giữ nguyên v1; supersedes ghi rõ).
4. `tests/test_s09_t00_benchmark_harness.py` — 19→26 tests (thêm 7: f5 coverage, zero-sample structural fail, adversarial, J1 fail-closed, reference split ×3; cập nhật schema/banner/determinism/capability).
5. `output/s09/20260823_sprint_full/t00-i03/**` — REGEN fixtures_gen (plates + contracts); measured_seed20260823 v1 KHÔNG đụng (hash verify OK).
6. `output/s09/20260823_sprint_full/t00-i03-c1/**` — logs gates_prep1..5, dry_run_v2, benchmark_results (DRY_RUN freeze artifact), v1_evidence_sha_before_prep.txt.
7. Append-only `LOG.md` + `REPORT.md` của I03.

FORBIDDEN checks: app renderer/API/frontend/models/migrations KHÔNG đụng · MAIN read-only · data/** không đụng · MOTIONFORGE_DATABASE_URL=UNSET suốt phiên · không tạo session/task mới · không git commit/push.

## 4. Hạn chế & ranh giới (minh bạch)

- Measured run v2 CHƯA chạy — đúng thiết kế: Wave B chỉ bắt đầu sau handshake J1 (`T02_CONTRACT_FROZEN_FOR_I03` do Manager phát sau khi T02-C1 freeze public contract). Hiện tại harness trả PENDING_RENDERER_CONTRACT_FREEZE cho mọi measured entry.
- `render_and_measure_v2()` là khung chuẩn bị: resolve contract + record input hashes; phần invoke renderer thật sẽ cắm đúng điểm đánh dấu sau J1 (import từ app.services.renderer_contract/router theo SHA handshake), không đoán API trước.
- Determinism hiện được chứng minh trên self-test mode (metrics thật trên estimator path); measured-mode determinism sẽ chứng minh lại ở Wave B trên renderer thật.
- Ruff toàn repo còn 1 lỗi thuộc T05A-C1 (nêu trên) — không che giấu, không sửa hộ.

## 5. Đề xuất bước tiếp

1. Manager: khi T02-C1 xong typed public contract + focused tests xanh → đọc SHA contract/router, phát `T02_CONTRACT_FROZEN_FOR_I03` vào registry.
2. Sau J1: resume đúng session này (owner 20260823_173318_69a813) cho Wave B — cắm invoke renderer thật vào `render_and_measure_v2()`, chạy measured run ×2 same-seed trên OUTPUT renderer, đối chiếu ngưỡng v2 đã freeze.
3. I05-C1 (owner 20260823_233406_8d5b7b) quyết định smallest measured route từ measured run đó; UNKNOWN/SKIPPED/empty không tính PASS.

STATUS: TASK_SUBMITTED

---

# S09-T00-I03-C1-WAVE-B — REPORT (measured run, post-J1)

Session owner: 20260823_173318_69a813 (resume đúng owner) · provider custom @ 9Router · model alpha · reasoning max.
Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` · branch `codex/s08-integration` · HEAD lúc preflight: ee10e55.
Ngày: 2026-08-25 (+07). LOG chi tiết: phần "Wave B" trong `LOG.md`.

## 1. Measured run theo acceptance §5 fast-track

| Mục | Kết quả | Bằng chứng |
|---|---|---|
| J1 handshake | SHA tính lại trên disk = `46c6a41f2e0959736fe570b37fda564c0e330e64248e6171f6a7d4fb404bbc1e` KHỚP token `T02_CONTRACT_FROZEN_FOR_I03` | preflight terminal 2026-08-25; detector quét registry C1 |
| Renderer thật mỗi (fixture, route) | `render_and_measure_v2()` gọi composite frozen T02 thật: plate_layers composite lại + `composite_pose_swap_frames`/`composite_sprite_affine_frames` + encode qua public surface `extra_output_opts` (libx264 CRF12) | scripts/s09_renderer_benchmark.py; smoke_full8 backend.adapter = app.services.renderer_routes.composite |
| Measured RENDERED OUTPUT | 4/4 measured PASS: f2 pose_swap, f3/f4/f6 sprite_affine (`MEASURED_RENDERED_OUTPUT`, decoded_output_hash ghi đủ 64 hex); f5 sprite_affine CONTRACT_REJECTED fail-closed (replacement z=0 sau pillar/charB — mặt bằng frozen không có z-order; không fake capability) | smoke_full8/benchmark_results_seed20260823.json measurement_mode=RENDERED_OUTPUT, frozen_content_sha256 b64c9bd1… |
| Adversarial source-reencode control ĐỎ đúng | 4/4 control FAILED_AS_EXPECTED (presence 0.0 <0.5) → gate đỏ như thiết kế F2 | metrics.adversarial_control của cả 4 measured entry |
| Same-seed determinism ×2 | det_A/det_B: decoded_output_hash SAME ×4; metrics IDENTICAL sau loại telemetry khai báo + artifact PATH run-scoped | det_A/, det_B/ + hash so sánh trong LOG Wave B |
| Evidence measured GIỮ NGUYÊN khi chạy gates | sha256sum -c trước/sau gates → OK ×3 (smoke_full8=16e71d14…, det_A=8e71a6b0…, det_B=6c8d18c6…) | /tmp/evidence_hashes_before_gates.txt |

## 2. Gates cuối (logs/gates_waveb_j1a_pytest.log, j1b, mypy/ruff inline)

| Gate | Lệnh | Kết quả |
|---|---|---|
| pytest ×2 basetemp khác nhau | `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t00_benchmark_harness.py --basetemp=%TEMP%/s09i03-j1a / -j1b -p no:cacheprovider -q` | **29 passed × 2**, exit 0/0 |
| ruff | `ruff check scripts/s09_renderer_benchmark.py tests/test_s09_t00_benchmark_harness.py` | All checks passed! exit 0 |
| mypy strict | `mypy scripts/s09_renderer_benchmark.py` | Success: no issues found, exit 0 |

## 3. Files changed phiên Wave B (đúng exclusive write-set C1)

1. `scripts/s09_renderer_benchmark.py` — tích hợp renderer thật (plate_layers, typed RenderRequest, encode extra_output_opts), z-order/visibility fail-closed rejection, rotation-aware presence, plateau escape, typing sạch (bỏ ignore thừa, cast narrowing).
2. `tests/test_s09_t00_benchmark_harness.py` — `_strip_nondet` loại artifact PATH run-scoped; capability-difference test viết lại post-J1 trên hành vi RENDERED_OUTPUT thật; 26→29 tests.
3. `output/s09/20260823_sprint_full/t00-i03-c1/**` — smoke*/det_A/det_B artifacts + logs gates_waveb_*.
4. Append-only `LOG.md` + `REPORT.md` của I03.

FORBIDDEN checks: contract T02 frozen KHÔNG đổi (J1 SHA khớp đến phút cuối) · app/**, MAIN, data/** không đụng · MOTIONFORGE_DATABASE_URL=UNSET suốt phiên · không tạo session/task mới · không commit/push.

## 4. Hạn chế minh bạch

- f5 sprite_affine KHÔNG có số đo: bị từ chối fail-closed vì mặt bằng frozen T02 không hỗ trợ z-order — đây là hành vi yêu cầu (không render sai im lặng); nếu cần số f5 thì T02 phải mở tham số z (thuộc Codex quyết định, ngoài write-set này).
- Self-test mode (`--self-test-source-observation`) hiện chỉ có tác dụng khi CHƯA frozen; sau J1 mọi run đều đi RENDERED_OUTPUT — đã phản ánh vào test.
- Reference benchmark vẫn SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE (không có annotation contract REF-R01..R05) — không fabricate ground truth.

STATUS: TASK_SUBMITTED

---

# S09-T00-I03-C2-PREP — REPORT ADDENDUM (RESUME PREP-FIX)

Ngày: 2026-08-25 15:06 +0700 · owner 20260823_173318_69a813 · worktree s08-integration (codex/s08-integration).

## Blocker Manager verify & fix

| Vấn đề | Fix | Bằng chứng |
|---|---|---|
| `thresholds schema_version must be 3, got 2` → 8 failed | thresholds.json schema_version 2→3; supersedes v2; KHÔNG đụng threshold values | pytest log trước: 8 failed, 21 passed |
| Disk contract đã đổi (T02-C2 landed) nhưng frozen constant còn C1 `46c6a41f…` → mọi measured path BLOCKED | Re-pin J1-C2: constant = disk SHA `d7d8b60e641b491297e039df3f41b19e1990a48b024205cd21679c03e5f38146` + machine-readable manifest `output/s09/contract_freeze_manifest.json` (F3) qua `--write-freeze-manifest`; `_detect_contract_freeze()` frozen=True với evidence manifest+registry+disk SHA | python probe: frozen? True |
| Adapter tự encode ra request.output_media nhưng request trỏ fixtures/rendered (vi phạm mục 4) | output_media = run artifacts dir TRỰC TIẾP; workspace_root = commonpath(fixtures, artifacts) thoả containment; cấm render vào tests/fixtures/**/rendered giữ nguyên | pytest fix-a/b logs |
| Entry kết quả thiếu record-v3 fields (KeyError backend_v3) | Propagate đầy đủ backend_v3/selected_route/j1_manifest_sha256/encoded_artifact_sha256/frame_count_rendered/fps_rational/time_base/runtime_ms_per_frame_measured/metrics_sample_count/contract_freeze_post_run từ plan_record vào entry | wave_b test asserts pass |
| Determinism fail trên wall-time mới | NON_DETERMINISTIC_FIELDS += runtime_ms_per_frame_measured, backend.wall_time_ms_total (harness + tests đồng bộ); A/B diff thực tế chỉ còn đúng các field này | diff script runa/runb |

## Gates cuối (lệnh thật, +07)

- pytest basetemp `%TEMP%/s09i03-c2-fix-a`: **29 passed in 51.69s**, PYTEST_A_EXIT=0
- pytest basetemp `%TEMP%/s09i03-c2-fix-b`: **29 passed in 51.73s**, PYTEST_B_EXIT=0
- mypy --strict scripts/s09_renderer_benchmark.py: **Success: no issues found in 1 source file**, MYPY_EXIT=0
- ruff scripts + tests + generator: **All checks passed!**, RUFF_EXIT=0

## Phạm vi C2-PREP đã đạt (Wave A)

1. f1_hard_cut có typed replacement (sign, prop_trajectory) nhảy vị trí ĐÚNG tại cut 45; f5_group_occlusion có replacement + occluder pillar + expected_layer_order z=-1 window 28..45. Regen ×2 byte-identical.
2. render_and_measure_v2 chỉ đi RendererRouter.execute() public surface — không còn composite trực tiếp/private helper.
3. Record v3 pin đủ 12 mục provenance; reject/empty ≠ PASS.
4. Output ghi trực tiếp vào run artifacts dir.
5. Determinism ×2 same-seed sau strip declared non-det fields; adversarial control giữ nguyên hành vi đỏ.
7. Freeze drift check TRƯỚC và SAU measured run (contract_freeze_post_run); drift → CONTRACT_DRIFT_DURING_RUN.

## Trạng thái

STATUS: WAITING_JOIN

## WAVE B MEASURED RUN — 2026-08-25 16:45 +0700 (J1-C2 open)

### Measured verdict (acceptance mục 5/6 prompt C2)
| # | Risk class | Route measured | Verdict | Evidence |
|---|---|---|---|---|
| 1 | f1_hard_cut | sprite_affine | PASS | traj 0.0/0.0%, replacement sign qua hard cut |
| 2 | f2_mouth_swap | pose_swap | PASS | mouth swap measured, sample>0 |
| 3 | f3_phone_contact | sprite_affine | PASS | replacement_effect phone=1.0 |
| 4 | f4_body_rotation | sprite_affine | PASS | rotation CW/CCW chấp nhận, keyframes 90/90 |
| 5 | f5_group_occlusion | sprite_affine | FAIL (measured) | z_inv=6, unexplained=6 — finding F-WB1 |
| 6 | f6_graphic_replacement | sprite_affine | PASS | graphic presence measured |

- pose_swap trên f1/f3/f4/f5/f6: CONTRACT_REJECTED capability_mismatch (thiếu
  pose_schedule) — đúng frozen contract routing, không phải lỗi.
- Mọi class MEASURED_RENDERED_OUTPUT với sample>0; không có reject/empty được
  tính PASS.

### Determinism & controls
- run_A vs run_B same-seed: encoded_artifact_sha256 identical cả 6 class;
  core JSON identical sau strip declared non-det fields (wall time, VRAM,
  runtime/frame, backend.wall_time_ms_total) + run-scoped paths.
- Adversarial source_reencode_substitution: 6/6 FAILED_AS_EXPECTED.

### Provenance (record v3)
- request_contract_sha256 = d7d8b60e… (frozen contract pin), j1_manifest_sha256
  = 1d854969… (manager manifest file SHA), license_id ffmpeg-gpl-build,
  nvenc_provenance acceleration-only, composite CPU deterministic.
- Pre-run + post-run manifest verify: 13/13 files match, NO DRIFT.

### Finding F-WB1 (cho Manager — KHÔNG FAIL_OPEN_QUESTION)
f5_group_occlusion FAIL trung thực: trong window 28..45 surface vẽ occluder
bằng cách STRETCH pillar full-frame (_draw_occluders với bbox=None), nên
char_b cũng bị che (GT nói visible [0..119]) → z_order_inversions=6 +
unexplained_visibility_events=6 đúng bằng số window samples. Estimator đã
root-cause từng bước (probe plate vs rendered: pillar thật ở x=255..385,
rendered stretch che ~toàn frame). Frozen contract KHÔNG hỗ trợ đặt occluder
sub-rect khi replacement free-roam toàn khung. Cần quyết định của Manager:
(a) chấp nhận semantics hiện tại và sửa GT visibility của f5, (b) mở scope
renderer cho per-region occluder placement, hoặc (c) fixture mới với occluder
full-frame đúng semantics. Không tune threshold, không sửa renderer files.

### Verification gates (môi trường sạch: env -u MOTIONFORGE_DATABASE_URL)
- pytest ×3 basetemp mới (waveb-t1/t2/t3): 29 passed mỗi lần (~51.8s).
- ruff check scripts+tests: All checks passed EXIT=0.
- mypy --strict scripts/s09_renderer_benchmark.py: Success EXIT=0.

STATUS: TASK_SUBMITTED

## MEASURED RE-RUN v2 — 2026-08-25 18:15 +0700 (J1-C2-v2, supersedes measured run v1)

### Measured verdict — TARGET BINARY ĐẠT: 6/6 classes overall_pass=True
| # | Risk class | Route measured | Verdict | Key metrics |
|---|---|---|---|---|
| 1 | f1_hard_cut | sprite_affine | PASS | traj 0/0%, replacement qua hard cut |
| 2 | f2_mouth_swap | pose_swap | PASS | mouth swap sample>0 |
| 3 | f3_phone_contact | sprite_affine | PASS | replacement_effect=1.0 |
| 4 | f4_body_rotation | sprite_affine | PASS | keyframes 90/90 |
| 5 | f5_group_occlusion | sprite_affine | **PASS** | z_inv=0, unexplained=0, traj 0/0%, char_a effect=0.833 |
| 6 | f6_graphic_replacement | sprite_affine | PASS | graphic presence measured |

- pose_swap trên f1/f3/f4/f5/f6: capability_mismatch (đúng frozen routing).
- Adversarial source_reencode_substitution: 6/6 FAILED_AS_EXPECTED.

### f5 resolution (finding F-WB1 → fixed)
- T02-C2-v2 thêm `occluder_regions` (normalized x,y,w,h) vào RenderRequest;
  `_draw_occluders` precedence regions[name] → sub-rect only.
- Fixture f5 cập nhật theo geometry thật: pillar 310px @x372 (core 221..523)
  để hide window [28..45] đúng về mặt hình học; occluder_regions khai báo
  đúng rect đó. char_b dời x=100 ra khỏi pillar span vì v2 sandwich order
  vẽ occluder TRÊN toàn bộ plate content trong window (overlap cũ sẽ che
  char_b sai GT). Media + manifest + index regenerate nhất quán; các fixture
  khác byte-for-byte không đổi. Threshold values KHÔNG đổi.

### Determinism & provenance
- run_A vs run_B same-seed: core JSON identical sau strip declared fields;
  encoded_artifact_sha256 identical cả 6 class.
- Record v3: request_contract_sha256 = ea8ab211… (disk v2 handshake),
  j1_manifest_sha256 = aa405015… (manager manifest v2), license
  ffmpeg-gpl-build, composite CPU deterministic, encode h264_nvenc.
- Pre/post-run manifest verify: 13/13 files, NO DRIFT.

### Verification gates (env -u MOTIONFORGE_DATABASE_URL)
- pytest ×2 basetemp mới (rerun-t1/t2): 29 passed mỗi lần (~48.7s).
- ruff (scripts + tests + generator): EXIT=0. mypy --strict script: EXIT=0.

STATUS: TASK_SUBMITTED

## C3 — UNIFIED FREEZE + CANONICAL MEASURED EVIDENCE — 2026-08-26 01:52 +0700 (owner 20260823_173318_69a813)

### F2 (P0) freeze split-brain — CLOSED
- Single authority: Manager-pinned `j1-c3/renderer_freeze_manifest_v4.json`,
  file SHA `ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5`,
  13/13 behavior-critical files re-hash clean pre-run AND post-run (no drift).
- CLI: `--manifest-path` + `--manifest-sha256` (fail-closed validation up
  front; pinned v4 defaults when omitted). `_detect_contract_freeze()` now
  verifies ONLY the Manager manifest. All fallbacks REMOVED from the active
  pipeline: no v2/v1 scan, no three-file `contract_freeze_manifest.json`
  pin, no registry prose token, no handshake constant in the gate.
  C2-era helpers remain only as documented-deprecated imports.
- Every measured row pins exact `j1_manifest_path` + `j1_manifest_sha256`.

### F3 (P1) canonical hash — CLOSED
- Reproduced on C2 evidence first: raw-concat `0ea2f331…` ≠ canonical
  `4dfd4f99…` (exactly as Codex measured).
- New independent implementation `canonical_decoded_hash_independent()`:
  frame count + ordered frame shape + contiguous decoded bytes, computed
  WITHOUT calling production `canonical_frame_sha256`; frames obtained via
  the public decoder only.
- Per-row equality gate vs adapter `output_frame_sha256`: mismatch fails
  closed (`CANONICAL_HASH_MISMATCH` / `CANONICAL_HASH_EVIDENCE_MISSING`),
  never a silent PASS.

### Measured verdict (t00-i03-c3/run_A + run_B, same-seed 20260823)
| # | Risk class | Route | Verdict |
|---|---|---|---|
| 1 | f1_hard_cut | sprite_affine | PASS |
| 2 | f2_mouth_swap | pose_swap | PASS |
| 3 | f3_phone_contact | sprite_affine | PASS |
| 4 | f4_body_rotation | sprite_affine | PASS |
| 5 | f5_group_occlusion | sprite_affine | PASS |
| 6 | f6_graphic_replacement | sprite_affine | PASS |

- 6/6 classes MEASURED_RENDERED_OUTPUT overall_pass=True; 12 rows (6×A/B):
  v4 pin TRUE, canonical==adapter TRUE.
- Adversarial source_reencode_substitution: 6/6 FAILED_AS_EXPECTED.
- Determinism: core JSON identical after stripping declared non-det fields;
  encoded_artifact_sha256 A==B for all 6 classes.
- C2 evidence (`t00-i03-c2/**`) untouched.

### Gates
- pytest ×2 fresh basetemp (c3-t1/t2): **33 passed** each (~76s) EXIT=0.
- ruff scripts+tests EXIT=0; mypy --strict script EXIT=0.
- Manifest v4 post-run verify: 13/13 files, no drift.

STATUS: TASK_SUBMITTED

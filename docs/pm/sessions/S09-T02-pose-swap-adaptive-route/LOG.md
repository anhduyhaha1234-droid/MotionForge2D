# S09-T02 — Pose-swap/affine adaptive route — WORKER LOG

Worker: implementation duy nhất của task. Provider custom @ 9Router, model alpha,
reasoning max, fallback disabled. Cwd: C:/Users/Admin/MotionForge2D-worktrees/s08-integration.

## Bước 0 — Required reading (2026-08-24)

- [x] HERMES_AUTOPILOT_RULES.md (MAIN, 180 dòng) đọc TOÀN BỘ → RULES_LOADED
- [x] TARGET_PROFILE_2D_SOURCE_LOCKED.md (526 dòng) đọc TOÀN BỘ — §4 P0-7 adaptive
  router, §5 route priority/escalation triggers, §8 thresholds + risk loops đã nạp
- [x] Worktree guard: branch codex/s08-integration, HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- [x] MOTIONFORGE_DATABASE_URL = UNSET (echo trực tiếp `DBURL=[UNSET]`)
- [x] TASK.md session đọc đầy đủ; ownership transfer duy nhất = wiring additive vào
  renderer_router.py (zero removed)
- [x] pm-session-execution skill (protocol) đã load

## Baseline git status (TRƯỚC mọi thay đổi của task này)

Pre-existing changes thuộc các task trước trong cùng worktree (bảo toàn 100%, không đụng):
- M app/adapters/renderer/{benchmark_harness,encode_base,ffmpeg_binary,pose_swap_adapter,sprite_affine_adapter}.py
- M app/services/{renderer_contract,renderer_router}.py
- M reskin_* (T01 owned) + frontend/src/features/reskin/index.ts
- M scripts/s09_renderer_benchmark.py + tests/fixtures/s09_renderer/generate_fixtures.py
- M tests/test_s09_reskin_* ×3 + test_s09_t00_renderer_router_contract.py
- ?? docs/pm/sessions/S09-T00-I02|I03 REPORTs, I05 dir, T01 TASK-SL.md,
  test_s09_reskin_source_locked_domain.py, test_s09_t00_benchmark_harness.py
- ?? docs/pm/sessions/S09-T02-pose-swap-adaptive-route/ (TASK.md only)

Baseline commands:
```
git rev-parse HEAD   -> ee10e55a809c84d5cb5d4a3046a1ee78828528d0
git branch --show-current -> codex/s08-integration
echo DBURL           -> DBURL=[UNSET]
```

## Plan (≤7 bước)

1. Đọc code hiện hữu: router/contract/adapters/nvenc/encode_base, structural_lock repo,
   benchmark results JSON (schema_version=1, seed20260823), harness CLI, fixture generator.
2. Implement NEW `app/services/renderer_routes/__init__.py` +
   `adaptive_pose_swap.py`: PoseSwapAdaptiveAdapter (backend_id `ffmpeg-nvenc-pose-swap-adaptive`)
   — NVENC thật qua encode_base, pose_state_capability measured (NCC template matching
   trên output vs input), sprite_affine tối ưu từ measured baseline.
3. Adaptive logic đọc benchmark results JSON runtime (schema v1), chọn smallest-passing
   per segment theo risk_class, escalation ĐỦ 5 field provenance qua router.maybe_escalate,
   không silent.
4. Wiring ADDITIVE vào renderer_router.py: import + factory `build_adaptive_default_router`
   (zero removed).
5. tests/test_s09_t02_*.py: golden classes thresholds, two-run determinism, no silent
   escalation, anchor parity round-trip SegmentRenderRoute ↔ renderer output (temp DB),
   legacy regressions (test_s09_t00_renderer_router_* + test_s09_reskin_config_*).
6. Gate: focused ×2 basetemp khác nhau, benchmark smoke ≥1 golden fixture với
   implementation mới (evidence t02/**), ruff app+tests, mypy app, git diff --check,
   self-audit write-set.
7. REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Validation baseline (chưa chạy — sẽ ghi kết quả thật ở mục GATE)

Chưa chạy validation nào tính đến entry này.

## Implementation log (2026-08-24)

- Tạo `app/services/renderer_routes/__init__.py` (44 dòng) — public surface.
- Tạo `app/services/renderer_routes/benchmark_results.py` (265 dòng) — loader
  runtime cho benchmark results JSON schema v1: fail-closed (missing file,
  unknown schema_version, thiếu frozen_content_sha256, route lạ, routes rỗng);
  smallest_passing_route theo ROUTE_PRIORITY từ threshold_evaluation đo được —
  KHÔNG hard-code kết quả đo; swap_capability_verified/route_measured_passing
  đọc check pose_state_capability thật từ document.
- Tạo `app/services/renderer_routes/adaptive_pose_swap.py` (~690 dòng):
  PoseSwapAdaptiveAdapter subclass PoseSwapAdapter (kế thừa NVENC pipeline I02
  nguyên văn) + measure_pose_state_capability phản chiếu đúng công thức harness
  (masked NCC tại tâm vùng + argmax phân loại closed/open, threshold 0.6);
  OptimizedSpriteAffineAdapter subclass SpriteAffineAdapter với identity
  filter-skip khi request_id kết thúc @identity; escalation/refusal qua router.
- Wiring ADDITIVE renderer_router.py: chỉ thêm factory build_adaptive_default_router
  (+52 dòng cuối file). Import churn ±3 dòng là trạng thái worktree TRƯỚC task
  (verify byte-identical lúc đầu task; khóa trong test_router_wiring_is_purely_additive).

## Gate evidence (2026-08-24)

1. Focused tests ×2 basetemp khác nhau:
   - run1 basetemp=s09t02-run1 → 37 passed
   - run2 basetemp=s09t02-gate2 → 37 passed
   - final replay (sau patch mypy) basetemp=s09t02-gate4-replay → 37 passed
2. Legacy regression: test_s09_t00_renderer_router_adapters + _contract → 28 passed;
   combined final run (4 files) basetemp=s09t02-gate3-final → 65 passed.
3. Benchmark smoke ≥1 golden fixture: harness thật scripts/s09_renderer_benchmark.py,
   fixture f1_hard_cut, cả pose_swap lẫn sprite_affine overall_pass=True;
   artifact output/s09/20260823_sprint_full/t02/benchmark_smoke/benchmark_results_seed20260823.json.
4. Render thật qua adapter mới trên f2_mouth_swap: NVENC ok=True, 60/60 frames,
   pose-state measured capability=verified_all_swaps (NCC in≈0.9995/out≈0.9995 vs
   baseline 0.951); wrong-plan → verification_failed có reasons (không silent pass);
   garbage media → undecodable reported.
5. Anchor parity round-trip: record_render_route ↔ list_routes_for_video khớp
   route/anchor/provenance/reasons/manifest_id; API read model list_renderer_route_evidence
   expose cùng dữ liệu (temp DB migrated alembic head).
6. ruff: app/services/renderer_routes/ + 2 test file + renderer_router.py → All checks passed.
7. mypy app/services/renderer_routes/ → Success: no issues found in 3 source files.
8. git diff --check → sạch (exit 0; chỉ warning LF/CRLF pre-existing toàn repo).
9. MOTIONFORGE_DATABASE_URL kiểm tra lại CUỐI task → UNSET (exit grep=1).
10. Self-audit write-set: file M duy nhất đụng bởi T02 = renderer_router.py (+52/-0
    so với baseline đầu task); mới: app/services/renderer_routes/** ×3,
    tests/test_s09_t02_*.py ×2, session docs. Các thay đổi khác trong git status
    là của I02/T01/I03/I05 (PROTECTED, không đụng — xem baseline ở đầu LOG).

## Correction C1 log (2026-08-24 — renderer thật, không re-encode giả; resume owner)

Review áp dụng: S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md (F1 P0 + F3 P1) +
S09_C1_FAST_TRACK_MANAGER_2026-08-24.md mục 4. RULES_LOADED đọc lại toàn bộ
180 dòng đầu phiên; worktree guard xác nhận lại (HEAD ee10e55a, DBURL UNSET).

1. CONTRACT (app/services/renderer_contract.py, +310 dòng): RenderRequest mở
   rộng typed/bounded/fail-closed — ReplacementAsset (kind
   sprite|pose_state|mask_overlay, alpha_mode), PoseSwapEntry (frame+state_id,
   schedule trên canonical timebase), AffineKeyframe (translation/scale/
   rotation, finite-only), AffectedRegion (bbox_xywh_norm), anchor_xy_norm
   [0,1]², mask_asset, workspace_root. validate_for_render() từ chối TRƯỚC
   success: path escape khỏi workspace_root, asset/media thiếu trên disk,
   container không hỗ trợ, frame order, NaN/Inf mọi trường số, schedule↔assets
   lệch, keyframes unsorted/out-of-range, pose_swap thiếu schedule,
   sprite_affine thiếu replacement.
2. COMPOSITOR (renderer_routes/composite.py, 458 dòng): CPU deterministic
   thuần numpy/OpenCV. composite_pose_swap_frames: composite state theo
   schedule thật (verbatim trước swap đầu, state giữ đến khi superseded),
   ngoài affected region copy NGUYÊN pixel source (zero tolerance); mask PNG
   nhân vào alpha layer. composite_sprite_affine_frames: replacement layer
   warp theo anchor + keyframes sample per-frame (piecewise-linear), KHÔNG có
   fixed 1°/1.02, KHÔNG transform source frame. write_frames_mp4: mp4v CPU
   reference; NVENC chỉ là encode acceleration qua output opts SAU input spec.
3. ADAPTERS: PoseSwapAdapter + SpriteAffineAdapter viết lại _render_impl →
   gates→validate→decode→composite→hash→encode; hết trim+re-encode và fixed
   transform; provenance descriptor ghi composite backend + nvenc_provenance
   "acceleration-only; compositor is CPU deterministic". OptimizedSpriteAffine
   Adapter giờ là true compositor với identity-skip đo được (@identity →
   keyframes rỗng, disclose identity_filter_skip). PoseSwapAdaptiveAdapter
   kế thừa pipeline mới nguyên văn.
4. ROUTER: execute() giữ exact-route dispatch (select_backend raise taxonomy
   đúng lỗi routing; adapter enforce contract bên trong render() trước mọi
   encode) — không silent fallback, license-gated, provenance 5-field giữ
   nguyên hành vi I02.
5. HARNESS (benchmark_harness.py): request benchmark gắn contract hợp lệ thật
   (replacement RGBA xanh + schedule/keyframe) — đo đúng pipeline composite.
6. TESTS MỚI tests/test_s09_t02_c1_composite_contract.py (14 test): pixel
   schedule-following + outside-region zero-diff; state history ≤1 frame;
   mask giới hạn vùng đổi; geometry translation/rotation/scale TRÊN LAYER
   (footprint center ±0.2W quanh anchor; rotation 90° top-red/bottom-blue;
   scale tăng diện tích footprint); fail-closed path-escape/missing-asset/
   NaN-anchor/Inf-scale/unsorted-keyframes (qua adapter: refuse + không để
   lại artifact); determinism 2 run cùng canonical hash + decoded frames
   identical; encoding gate subprocess pinned encoding="utf-8",
   errors="replace" chạy cả PYTHONUTF8 unset lẫn =1.
7. F3 FIX: test_router_wiring_is_purely_additive viết lại — KHÔNG còn so
   git show HEAD; khóa frozen semantic contract: API surface I02 (7 symbol),
   import block pre-task verbatim-in-order, đúng 1 factory wiring, refusal
   kind unchanged, cấm subprocess/git trong module router.

## Gate evidence C1 (2026-08-24)

1. Full focused suite ×2 basetemp khác nhau (gate-run1, gate-run2): 79 passed
   /79 (C1 composite contract 14 + route_selection 27 + NVENC 10 + legacy
   adapters 9 + legacy contract 19).
2. Encoding gate ×2 chế độ: PYTHONUTF8=1 → 51 passed; env -u PYTHONUTF8 →
   51 passed.
3. ruff app/ + tests/ → All checks passed; mypy 13 files (contract, routes,
   adapters, router) → Success: no issues found; git diff --check exit 0
   (GIT_DIFF_CHECK_OK).
4. Router smoke thực tế (đầu phiên): mesh_warp exact-route raise UnknownCapa
   bilityError; NaN anchor → INVALID_REQUEST fail trước success; sprite_affine
   override đúng backend; license gate + escalation refusal payload giữ nguyên.
5. Self-audit write-set: thay đổi C1 nằm trong allowlist — renderer_contract.py,
   renderer_routes/** (composite.py mới, __init__.py mở rộng),
   adapters/renderer/{pose_swap,sprite_affine}_adapter.py + benchmark_harness.py,
   renderer_router.py (comment-only delta so với T02), tests/test_s09_t02_c1_*
   (mới) + cập nhật additive 2 file t00 + 2 file t02 cũ. Không đụng MAIN,
   data/**, app/api/app.py (M pre-existing của task khác), models/migrations,
   benchmark script/fixtures.
6. MOTIONFORGE_DATABASE_URL cuối phiên → UNSET.

CONTRACT_FROZEN: SHA-256 = 46c6a41f2e0959736fe570b37fda564c0e330e64248e6171f6a7d4fb404bbc1e
(tính trên bytes renderer_contract.py + renderer_routes/__init__.py +
renderer_routes/composite.py; handshake J1 cho Manager ↔ I03). Sau freeze
KHÔNG đổi public contract.

## Correction C1b log (2026-08-25 — mypy final-gate, 1 lỗi duy nhất toàn app)

FINDING: `mypy app --no-incremental` → app/workflow/s09_demo_jobs.py:203
"object" not callable [operator]. ROOT CAUSE (Manager root-caused, xác nhận
đúng): __init__.py dùng PEP 562 lazy re-export (`__getattr__ -> object`) phá
circular import adapter⇄package; T03 import tĩnh select_route từ package →
mypy suy kiểu object. Runtime đúng, static type mất.

FIX (phương án ưu tiên của Manager, trong write-set renderer_routes/**):
thêm nhánh `if TYPE_CHECKING:` trong app/services/renderer_routes/__init__.py
re-export tĩnh 7 symbol từ adaptive_pose_swap (IDENTITY_REQUEST_SUFFIX,
AdaptiveRouteDecision, OptimizedSpriteAffineAdapter, PoseSwapAdaptiveAdapter,
load_pose_templates_rgba, measure_pose_state_capability, select_route) khớp
1-1 với lazy accessor runtime; `__getattr__` PEP 562 GIỮ NGUYÊN (cycle vẫn
được phá ở runtime). KHÔNG đụng s09_demo_jobs.py hay file nào khác.
Ruff I001 sort order IDENTITY_REQUEST_SUFFIX trước AdaptiveRouteDecision
(theo isort force-sort-within-sections của repo) đã sửa.

GATE C1b (thật, đã chạy):
1. `mypy app --no-incremental` → **Success: no issues found in 125 source
   files** (0 errors toàn app — finding cuối cùng đã xử lý).
2. pytest route_selection + pose_swap_nvenc + demo_loops (file thật là
   tests/test_s09_t03_demo_loops.py — tên trong lệnh Manager thiếu "t03")
   basetemp=%TEMP%/s09t02c1-mypy, PYTHONUTF8=1 → **47 passed** (27+10+10);
   replay env -u PYTHONUTF8 basetemp=s09t02c1-mypy2 → **47 passed**
   (demo loops chứng minh runtime import vẫn qua __getattr__).
3. ruff app/ + tests/ → All checks passed.
4. Self-audit write-set: git status lọc → chỉ renderer_routes/__init__.py
   (allowlist) chạm mới; s09_demo_jobs.py + test_s09_t03_demo_loops.py
   untouched (untracked pre-existing của T03).

LƯU Ý HANDSHAKE J1: __init__.py nằm trong bộ hash frozen contract → hash
MỚI sau correction này:
CONTRACT_FROZEN: SHA-256 =
62c7d7d68628dba14006f754042f3d415e80d5aebaa77e23aef99b0cd891a8f7
(hash cũ 46c6a41f… BẤT HỢU LỰC — Manager dùng hash mới này handshake I03;
public surface KHÔNG đổi — chỉ thêm nhánh TYPE_CHECKING static-only,
runtime behavior identical).

## Correction C2 log (2026-08-25 — production renderer contract, review F5 + prompt mục 5)

RULES_LOADED (đọc toàn bộ 180 dòng HERMES_AUTOPILOT_RULES.md đầu phiên).
Đầu vào: docs/pm/reviews/S09_C1_PM_REVIEW_2026-08-25.md (F1/F3/F5) +
docs/pm/prompts/S09_C2_CORRECTION_MANAGER_2026-08-25.md mục 5 (đọc toàn bộ).

THAY ĐỔI (write-set renderer):
1. app/services/renderer_contract.py:
   - SourceTimebase(fps_num, fps_den) frozen dataclass + fps_exact -> Fraction
     + fps_float; RenderRequest.source_timebase (tuple coercion trong
     __post_init__); accessor request.timebase() cho adapters.
   - LayerOrderEntry(frame_from, frame_to, layer_id, z) typed; __post_init__
     refuse entry ngoài 0<=frame_from<=frame_to; validate_for_render refuse
     entry outside render range.
   - occluder_assets: dict[str, ReplacementAsset]; layer_order tuple;
     identity_transform bool (refuse khi affine_keyframes non-empty);
     layer_order entries phải là LayerOrderEntry instance (fail-closed).
   - alpha_mode giữ enum {straight, premultiplied, opaque} — THỰC THI đủ 3
     semantics trong composite.apply_alpha_mode; mode lạ refuse.
   - validate_for_render mở rộng: output_media != input_media, output
     container hợp lệ (.mp4/.mov/.mkv), source_timebase REQUIRED, occluder
     kind='sprite' + file exists, bounds — TẤT CẢ trước artifact mutation.
2. app/services/renderer_routes/composite.py:
   - probe_source_timebase(path): ffprobe r_frame_rate → fallback cv2 FPS.
   - apply_alpha_mode(rgba, mode): straight/premultiplied/opaque thật.
   - _occluder_z_for_frame: z active theo frame từ layer_order.
   - _draw_occluders: z>0 vẽ TRƯỚC replacement, z<0 vẽ SAU.
   - write_frames_mp4 bắt OSError khi pipe chết → surface stderr ffmpeg
     (root cause BrokenPipeError che lỗi NVENC min-size 64x64).
3. Adapters (pose_swap_adapter.py, sprite_affine_adapter.py,
   adaptive_pose_swap.py): fps encode = request.timebase().fps_float (BỎ
   canonical retime); frame-count guard sau composite; output_frame_sha256 =
   canonical hash DECODE LẠI từ output file SAU encode (không hash pre-encode
   frames); taxonomy/provenance giữ backend_id backend thực sự phục vụ.
4. IDENTITY: xóa IDENTITY_REQUEST_SUFFIX + endswith("@identity") khỏi
   adaptive_pose_swap.py + __init__.py (TYPE_CHECKING branch + __all__).
   Identity = identity_transform=True + track keyframes RỖNG.
5. benchmark_harness.py: request dựng với SourceTimebase(30,1) (clip synth
   30fps); bỏ constant retime.

TESTS MỚI: tests/test_s09_t02_c2_timebase_identity_contract.py (14 tests):
timebase Fraction/validation, EXACT frame count 24fps+30fps qua route thật,
LayerOrderEntry bounds, occlusion composite z±, identity typed (ID không đổi
nghiệp vụ), sha256 sau encode khớp recompute độc lập từ file, fail-first
artifact sentinel, router dispatch/provenance, container validation.

DISCLOSURE: sửa ĐÚNG 1 dòng cơ học trong app/workflow/s09_demo_jobs.py
(T03-owned): `pin = pins.get(...)` → `pin = (pinned_routes or {}).get(...)`
— NameError chặn mypy toàn app (tham số pinned_routes có sẵn trong chữ ký).
Không đụng phần khác của file. 2 warning ruff còn lại trong file đó thuộc
correction đang chạy của T03 — ngoài "ruff owned files" của tôi.

GATE C2 (thật, đã chạy):
1. Focused 6-file ×2 basetemp (s09t02c2-gate4, gate5-noutf8) → **93 passed**
   mỗi run; env -u PYTHONUTF8 → **93 passed**.
2. tests/test_s09_t03_demo_loops.py ×2 basetemp → **15 passed** mỗi run.
3. `python -m mypy app --no-incremental` → **Success: no issues found in
   125 source files** (0 errors).
4. ruff owned files (contract + routes + adapters + t02/t00 focused tests)
   → All checks passed. `git diff --check` exit 0.
5. CONTRACT_FROZEN RECOMPUTE (C2 đụng cả 3 file hashed):
   CONTRACT_FROZEN: SHA-256 =
   d7d8b60e641b491297e039df3f41b19e1990a48b024205cd21679c03e5f38146
   (supersedes 62c7d7d6…; public surface vẫn tương thích — chỉ thêm fields/
   dataclass mới, không xóa gì).

## Correction C2-v2 log (2026-08-25 — J1-C2 mở lại: per-region occluder placement)

INPUT: I03 measured run f5_group_occlusion FAIL trung thực. Root cause xác
minh: _draw_occluders bbox=None STRETCH full-frame → pillar che cả
replacement lẫn char_b trong window 28..45 (z_order_inversions=6,
unexplained_visibility=6). GT yêu cầu pillar thật ở x=255..385 trong khi
replacement free-roam toàn khung.

THAY ĐỔI:
1. renderer_contract.py: field mới
   `occluder_regions: dict[str, tuple[float, float, float, float]] | None`
   (name → x,y,w,h NORMALIZED). Validation fail-closed trong
   validate_for_render: tên không có trong occluder_assets → refuse;
   NaN/Inf từng thành phần → refuse; w/h <= 0 → refuse; rect ngoài [0,1]
   normalized bounds → refuse. KHÔNG có region → hành vi cũ giữ nguyên
   (backward compatible).
2. composite.py `_draw_occluders(..., regions=None)` precedence per
   occluder: (a) regions[name] tồn tại → stretch VÀO sub-rect duy nhất đó
   (qua cùng helper _region_px như affected-region path — rounding nhất
   quán); (b) không region + bbox → legacy affected-region stretch;
   (c) không region + không bbox → legacy full-frame cover. 4 call sites
   (pose_swap trước/sau, sprite_affine trước/sau) truyền
   request.occluder_regions. z>0/z<0 semantics GIỮ NGUYÊN.
3. Tests thêm 3 (tổng 17 trong file C2):
   - test_occluder_region_draws_only_inside_sub_rect: pillar chỉ che
     x∈[0.6,1.0); ngoài rect = source pixels array_equal.
   - test_occluder_region_z_inversion_zero_free_roam: replacement free-roam
     qua translation track 2 keyframes quét toàn khung; so below(z=+1)/
     above(z=-1)/plain(không occluder): ngoài pillar rect → z-order ZERO
     effect + khớp plain 100%; phân loại inside dùng ĐÚNG _region_px để
     boundary rounding khớp compositor (z_inversions=0,
     unexplained_visibility=0 ngoài rect).
   - test_occluder_region_validation_fail_closed: ghost name / out-of-
     bounds / NaN x / zero w đều refuse.

GATE C2-v2 (thật, đã chạy):
1. Focused 4-file (route_selection + pose_swap_nvenc + c2 timebase/identity
   + c1 composite contract) ×2 basetemp (s09t02c2v2-gate1, -gate2) →
   **68 passed** mỗi run; env -u PYTHONUTF8 (-gate3-noutf8) → **68 passed**.
2. `python -m mypy app --no-incremental` → **Success: no issues found in
   125 source files** (0 errors).
3. ruff owned files → All checks passed.
4. CONTRACT_FROZEN RECOMPUTE lần nữa (contract + composite đụng tiếp):
   CONTRACT_FROZEN: SHA-256 =
   ea8ab21187850a0bd481ba546e8ffe0439dd7d48ec9359c9ffab83f7c1d5d8fb
   (supersedes d7d8b60e…; Manager pin J1-C2-v2 manifest với hash này).

KHÔNG đụng: benchmark script/fixtures, thresholds.json, T03/T04/T06 files,
API/frontend, models/migrations, MAIN, data/**.

## Correction C2-final log (2026-08-25 — rg-gate mục 3.5: gỡ v1 artifact khỏi active tests)

FINDING (Manager rg-gate, xác nhận đúng): FROZEN_RESULTS
(route_selection.py:38) và _frozen_results_path (nvenc.py:685) còn trỏ vào
old t00-i05/measured_seed20260823/benchmark_results_seed20260823.json —
vi phạm prompt C2 mục 3.5.

THAY ĐỔI (chỉ tests/test_s09_t02_*.py — KHÔNG đụng renderer production):
1. Cả hai điểm load đổi sang C2 measured run_A:
   output/s09/20260823_sprint_full/t00-i03-c2/run_A/
   benchmark_results_seed20260823.json (schema v3, đã verify loader chuẩn
   chấp nhận + đủ 6/6 risk class rows thật).
2. Kỳ vọng hard-code thời v1 phải SỬA THEO MEASURED TRUTH của run_A (đọc
   trực tiếp từ artifact): sprite_affine measured-passing 5/6 class;
   pose_swap chỉ passing mouth_expression_swap (sprite_affine bị
   CONTRACT_REJECTED_BY_FROZEN_CONTRACT ở đó); KHÔNG row nào có
   pose_state_capability check pass → annotated-swaps trên 5 class kia
   REFUSE fail-closed (đúng overlay §8: không bao giờ trao segment route
   đang fail). Các test đổi tương ứng:
   - test_loader_accepts_frozen_document: assert schema_version==3 +
     policy s09-t00-i03-c1-frozen-20260824.
   - test_smallest_passing_matches_frozen_evidence: derive expected từ
     document (route_measured_passing ladder), hết hard-code pose_swap.
   - test_select_route_all_frozen_classes_choose_pose_swap ĐỔI thành 2 test:
     (a) test_select_route_matches_measured_c2_evidence (no swaps → smallest
     passing wins, khớp document); (b)
     test_select_route_annotated_swaps_fail_closed_without_capability
     (pose_swap passing chỉ ở mouth_expression_swap; 5 class còn lại
     pytest.raises "adaptive selection refused").
   - test_select_route_two_run_determinism: skip nhánh refuse, giữ
     determinism cho các class select được.
3. Negative-assertion MỚI test_frozen_input_is_c2_measured_run_not_v1:
   schema v3 + đủ rows 6 class + literal v1 directory name KHÔNG được xuất
   hiện trong module source (literal construct từ parts để self-check không
   tự match). Comment trong nvenc.py cũng gỡ literal tương tự.
4. Lưu ý scope: tests/test_s09_t03_demo_loops.py:15 và t04_demo_compare.py:9
   vẫn chứa literal v1 nhưng là DOCSTRING negative-assertion của chính T03/
   T04 ("v1 is NEVER referenced") — đúng pattern Manager yêu cầu, file họ
   owned, worker không đụng.

GATE C2-final (thật, đã chạy):
1. route_selection + pose_swap_nvenc ×2 basetemp khác nhau (final1,
   final2-noutf8) → **44 passed** mỗi run (33 route_selection + 11 nvenc).
   Run sơ bộ gate1/gate2/gate3-noutf8 cũng 44 passed mỗi run trước khi gỡ
   literal comment cuối.
2. grep t00-i05/measured_seed20260823 trên app/ + 4 file T02 tests → 0 hit.
3. ruff owned files → All checks passed.
4. CONTRACT_FROZEN replay sau correction → KHÔNG ĐỔI:
   ea8ab21187850a0bd481ba546e8ffe0439dd7d48ec9359c9ffab83f7c1d5d8fb
   (chỉ tests đổi; J1-v2 manifest pin hash này GIỮ NGUYÊN).

KHÔNG đụng: renderer production files, benchmark script, fixtures,
thresholds, T03/T04 files.

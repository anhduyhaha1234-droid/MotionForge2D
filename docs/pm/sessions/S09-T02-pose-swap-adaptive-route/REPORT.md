# S09-T02 — Pose-swap/affine adaptive route — REPORT

STATUS: TASK_SUBMITTED

Worker: implementation duy nhất (provider custom @ 9Router, model alpha, --yolo).
Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration (branch codex/s08-integration,
HEAD đầu task ee10e55a). MOTIONFORGE_DATABASE_URL: UNSET suốt session.

## Deliverables (đúng write-set allowlist)

1. `app/services/renderer_routes/__init__.py` — NEW, public surface của package.
2. `app/services/renderer_routes/benchmark_results.py` — NEW: runtime loader cho
   benchmark results JSON (schema v1) — fail-closed mọi vi phạm (file thiếu,
   schema lạ, thiếu frozen_content_sha256, route lạ); smallest-passing per risk
   class derive RUNTIME từ threshold_evaluation đo được; KHÔNG hard-code số đo
   (I03/I05 evidence là input, không phải hằng số).
3. `app/services/renderer_routes/adaptive_pose_swap.py` — NEW:
   - PoseSwapAdaptiveAdapter (backend_id ffmpeg-nvenc-pose-swap-adaptive):
     subclass PoseSwapAdapter → kế thừa nguyên văn NVENC pipeline I02 đã verify;
     đo pose_state_capability SAU encode bằng masked-NCC + argmax phân loại,
     phản chiếu đúng công thức harness; evidence đầy đủ per swap (input/output
     winner, scores), fail-closed khi không đo được (undecodable/verification_failed).
   - OptimizedSpriteAffineAdapter (backend_id ffmpeg-nvenc-sprite-affine-optimized):
     subclass SpriteAffineAdapter; identity filter-graph skip CHỈ khi segment
     khai báo @identity; disclosure per-render trong capability descriptor.
4. `renderer_router.py` — wiring ADDITIVE-ONLY (+52/-0 so với baseline đầu task):
   factory build_adaptive_default_router; registry mặc định deterministic:
   pose_swap ← adaptive backend; sprite_affine ← I02 backend trước, optimized sau;
   mesh_warp/part_rig/controlled_redraw KHÔNG đăng ký (UnknownCapabilityError).
   Escalation đi qua RendererRouter.maybe_escalate có sẵn — 5 field provenance
   bắt buộc, refuse có artifact kiểm toán, backward escalation bị chặn.
5. `tests/test_s09_t02_adaptive_route_selection.py` — 27 test: fail-closed loader,
   smallest-passing từ measured evidence, policy §8 (annotated swaps không có
   evidence → giữ pose_swap; disclose note; refusal khi không route nào pass),
   two-run determinism, additive-only wiring lock, registry determinism +
   override honor.
6. `tests/test_s09_t02_adaptive_pose_swap_nvenc.py` — 10 test: NVENC thật trên
   f2_mouth_swap (verified_all_swaps, NCC in/out ≈0.9995 vs cross-state 0.951),
   wrong-plan → capability=False CÓ reasons (không silent pass), garbage media →
   undecodable reported, optimized identity skip on/off, geometry parity,
   anchor-parity round-trip SegmentRenderRoute ↔ renderer decision (temp DB
   alembic head), API read-model parity (list_renderer_route_evidence),
   escalation 5-field provenance + refusal auditable + backward blocked.

## Gate results (thật, đã chạy)

| Gate | Kết quả |
|---|---|
| Focused ×2 basetemp khác nhau | run1=37 passed; gate2=37 passed; replay sau mypy-fix=37 passed |
| Legacy regressions | router adapters+contract = 28 passed; combined final = 65 passed |
| Benchmark smoke ≥1 golden fixture | f1_hard_cut qua harness thật: pose_swap PASS + sprite_affine PASS; artifact t02/benchmark_smoke/*.json |
| Render thật adapter mới | f2_mouth_swap NVENC ok=True 60/60 frames, measured verified_all_swaps |
| ruff | All checks passed (package + tests + router) |
| mypy | Success: no issues found in 3 source files |
| git diff --check | exit 0 (chỉ LF/CRLF warnings pre-existing toàn repo) |
| DB URL | UNSET đầu và cuối task |

## Ownership transfer audit

- File MỞ (modified) duy nhất bởi T02: app/services/renderer_router.py — thuần
  append (+52 dòng factory cuối file). Import churn ±3 trong git diff là trạng
  thái worktree TRƯỚC task (I02 uncommitted), đã verify byte-identical lúc đầu
  task và khóa vĩnh viễn trong test_router_wiring_is_purely_additive.
- File MỚI: đúng allowlist renderer_routes/** ×3 + tests/test_s09_t02_*.py ×2
  + session docs (TASK.md có sẵn, LOG.md, REPORT.md này).
- Các thay đổi khác trong git status thuộc I02/T01/I03/I05 — PROTECTED, không đụng.

## Known notes (minh bạch, không bao biện)

- Registry mặc định phục vụ pose_swap bằng adaptive backend thay vì I02 backend
  (đây chính là ownership transfer điểm duy nhất TASK.md giao); hành vi render
  pipeline kế thừa nguyên văn từ lớp cha đã verify. sprite_affine vẫn được I02
  backend phục vụ trước — optimized chỉ là candidate thứ hai cùng route.
- Benchmark smoke chạy 1 golden fixture theo yêu cầu tối thiểu TASK.md; toàn bộ
  6 fixture đã được đo đầy đủ ở I05 (frozen document mà selection tiêu thụ).

TASK_SUBMITTED — worker dừng tại đây (sprint gate §3 rules).

## Correction C1 (2026-08-24) — renderer thật, không re-encode giả

STATUS: TASK_SUBMITTED (C1)

Áp review F1 P0 + F3 P1 (S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md) + mục 4
fast-track prompt. Resume đúng owner session theo §4.

### Deliverables C1 (đúng write-set allowlist C1)

1. `app/services/renderer_contract.py` — RenderRequest typed/bounded/fail-closed:
   ReplacementAsset / PoseSwapEntry / AffineKeyframe / AffectedRegion /
   anchor_xy_norm [0,1]² / mask_asset / workspace_root + validate_for_render()
   từ chối TRƯỚC success mọi vi phạm: path escape, asset/media thiếu, container
   không hỗ trợ, frame order, NaN/Inf, schedule↔assets lệch, keyframes
   unsorted/out-of-range, route thiếu replacement/schedule.
2. `app/services/renderer_routes/composite.py` — NEW compositor CPU
   deterministic: pose_swap composite THEO SCHEDULE thật (không trim+re-encode);
   sprite_affine composite replacement layer theo anchor/keyframes của request
   (KHÔNG fixed 1°/1.02, KHÔNG transform source frame); ngoài affected
   region/mask pixel source giữ NGUYÊN; frame count/timebase chính xác; alpha
   mới không ép silhouette cũ.
3. `app/adapters/renderer/pose_swap_adapter.py`, `sprite_affine_adapter.py`,
   `benchmark_harness.py` — render path thật: gates→validate→decode→composite→
   canonical hash→encode. NVENC chỉ encode acceleration có provenance fail-closed
   ("acceleration-only; compositor is CPU deterministic"); CPU là reference.
   Không download model/network.
4. `app/services/renderer_router.py` — exact-route/no-silent-fallback,
   license-gated, provenance 5-field giữ nguyên hành vi I02; contract được
   adapter enforce trong render() trước mọi encode work.
5. `tests/test_s09_t02_c1_composite_contract.py` — NEW 14 test acceptance:
   pixel (schedule-following, outside-region zero-diff, state history ≤1 frame,
   mask-bounded), geometry trên layer (translation ±0.2W quanh anchor, rotation
   90°, scale footprint), fail-closed (escape/missing/NaN/Inf/unsorted qua
   adapter — refuse + zero artifact), determinism 2-run canonical hash +
   decoded-frame equality, encoding gate PYTHONUTF8 unset lẫn =1 với subprocess
   pinned encoding="utf-8", errors="replace".
6. F3 fix: `test_router_wiring_is_purely_additive` KHÔNG còn so sánh git show
   HEAD — khóa frozen semantic contract (API surface I02, import block pre-task,
   1 factory, refusal kind, cấm subprocess/git trong router module).

### Gate results C1 (thật, đã chạy)

| Gate | Kết quả |
|---|---|
| Full focused ×2 basetemp khác nhau | gate-run1 = 79 passed; gate-run2 = 79 passed (C1 14 + T02 37 + legacy 28) |
| Encoding gate | PYTHONUTF8=1 → 51 passed; env -u PYTHONUTF8 → 51 passed |
| Pixel/geometry/fail-closed/determinism | 14/14 test C1 PASS (chi tiết trong LOG.md) |
| ruff | app/ + tests/ → All checks passed |
| mypy | Success: no issues found in 13 source files |
| git diff --check | exit 0 (GIT_DIFF_CHECK_OK) |
| DB URL | UNSET đầu và cuối C1 |

### CONTRACT_FROZEN (J1 handshake)

CONTRACT_FROZEN: SHA-256 =
62c7d7d68628dba14006f754042f3d415e80d5aebaa77e23aef99b0cd891a8f7
(bytes của renderer_contract.py + renderer_routes/__init__.py +
renderer_routes/composite.py). Manager dùng hash này handshake với I03.
Sau freeze KHÔNG đổi public contract.
(Hash 46c6a41f… trước correction C1b BẤT HỢU LỰC — xem LOG.md mục C1b.)

## Correction C1b (2026-08-25) — mypy final-gate: "object" not callable

STATUS: TASK_SUBMITTED (C1b)

FINDING: mypy app --no-incremental → app/workflow/s09_demo_jobs.py:203
"object" not callable [operator] — hệ quả PEP 562 lazy re-export
(`__getattr__ -> object`) trong renderer_routes/__init__.py; T03 import tĩnh
select_route → mypy mất kiểu. Runtime đúng, static type mất.

FIX: thêm nhánh `if TYPE_CHECKING:` trong __init__.py (write-set của mình,
KHÔNG đụng s09_demo_jobs.py) re-export tĩnh 7 symbol khớp lazy accessor;
`__getattr__` giữ nguyên.

| Gate | Kết quả |
|---|---|
| mypy app --no-incremental | Success: no issues found in 125 source files (0 errors) |
| pytest route_selection + nvenc + demo_loops ×2 chế độ PYTHONUTF8 | 47 passed (PYTHONUTF8=1, basetemp %TEMP%/s09t02c1-mypy); 47 passed (unset, basetemp s09t02c1-mypy2) |
| ruff app/ + tests/ | All checks passed |
| Write-set audit | chỉ renderer_routes/__init__.py chạm mới; s09_demo_jobs.py + test T03 untouched |

CONTRACT_FROZEN cập nhật sau C1b:
SHA-256 = 62c7d7d68628dba14006f754042f3d415e80d5aebaa77e23aef99b0cd891a8f7
(public surface không đổi — TYPE_CHECKING static-only).

TASK_SUBMITTED (C1b) — worker dừng tại đây (sprint gate §3 rules).

## Correction C2 (2026-08-25) — production renderer contract (review F5 + prompt mục 5)

STATUS: TASK_SUBMITTED (C2)

7 mục bắt buộc ĐÃ SỬA (chi tiết kỹ thuật trong LOG.md mục Correction C2):
1. Typed rational timebase: SourceTimebase(num,den)+Fraction; output giữ
   EXACT source fps/timebase — hết canonical retime. LayerOrderEntry typed
   cho ordering/occlusion theo frame; f1_hard_cut/f5_group_occlusion
   representable bằng public fields thuần, không special branch.
2. Adapters giữ EXACT inclusive frame count + fps từ request.timebase();
   tests route thật 24fps + 30fps.
3. Xóa `request_id.endswith("@identity")` + IDENTITY_REQUEST_SUFFIX;
   identity = identity_transform=True + keyframes rỗng (refuse khi mâu
   thuẫn). Request ID không còn đổi nghiệp vụ.
4. output_frame_sha256 hash canonical decoded frames SAU encode; test
   recompute độc lập từ output file khớp evidence.
5. alpha_mode thực thi đủ {straight,premultiplied,opaque}; validate mở rộng
   (output≠input, container, containment, NaN/Inf, bounds, occluder kind)
   — invalid fail TRƯỚC artifact mutation (sentinel test).
6. router .execute() dispatch đúng adapter; provenance backend_id = backend
   THỰC SỰ phục vụ; CPU reference / NVENC accel tách rõ.
7. PEP 562 lazy + TYPE_CHECKING branch giữ nguyên; mypy app 0 errors.

| Gate | Kết quả |
|---|---|
| Focused suite 6-file ×2 basetemp | 93 passed (gate4); 93 passed (gate5-noutf8) |
| UTF8 matrix | env -u PYTHONUTF8 → 93 passed |
| T03 demo-loops regression ×2 | 15 passed mỗi run |
| mypy app --no-incremental | Success: no issues found in 125 source files |
| ruff owned files | All checks passed |
| git diff --check | exit 0 |

DISCLOSURE: 1 dòng cơ học trong app/workflow/s09_demo_jobs.py (T03-owned)
sửa NameError chặn mypy toàn app (`pins.get` → `(pinned_routes or {}).get`)
— chi tiết LOG.md.

CONTRACT_FROZEN sau C2:
SHA-256 = d7d8b60e641b491297e039df3f41b19e1990a48b024205cd21679c03e5f38146

TASK_SUBMITTED (C2).

## Correction C2-v2 (2026-08-25) — J1-C2 mở lại: per-region occluder placement

STATUS: TASK_SUBMITTED (C2-v2)

INPUT: I03 measured f5_group_occlusion FAIL trung thực — _draw_occluders
bbox=None stretch full-frame che cả replacement lẫn char_b
(z_order_inversions=6, unexplained_visibility=6). GT cần pillar thật tại
sub-rect trong khi replacement free-roam.

THAY ĐỔI:
1. Contract: `occluder_regions: dict[str,(x,y,w,h)] | None` (normalized).
   Validation fail-closed TRƯỚC artifact mutation: unknown name / NaN·Inf /
   w·h<=0 / ngoài bounds [0,1] đều refuse. Không region → hành vi cũ
   (backward compatible).
2. Compositor `_draw_occluders(..., regions)` precedence: explicit region →
   sub-rect duy nhất; không region → legacy bbox/full-frame paths GIỮ NGUYÊN.
   z>0/z<0 semantics giữ nguyên. 4 call sites truyền request.occluder_regions.
3. Tests +3 (file C2 giờ 17 tests): sub-rect chỉ che đúng rect (ngoài =
   array_equal source), z-inversion=0 với replacement free-roam quét khung
   (phân loại inside dùng cùng _region_px với compositor), fail-closed
   validation matrix.

| Gate | Kết quả |
|---|---|
| Focused 4-file ×2 basetemp (v2-gate1, v2-gate2) | 68 passed mỗi run |
| UTF8 matrix (v2-gate3-noutf8) | 68 passed |
| mypy app --no-incremental | Success: no issues found in 125 source files |
| ruff owned files | All checks passed |

CONTRACT_FROZEN sau C2-v2 (Manager pin J1-C2-v2 manifest với hash này):
SHA-256 = ea8ab21187850a0bd481ba546e8ffe0439dd7d48ec9359c9ffab83f7c1d5d8fb
(supersedes d7d8b60e…)

KHÔNG đụng: benchmark script/fixtures, thresholds.json, T03/T04/T06,
API/frontend, models/migrations, MAIN, data/**.

TASK_SUBMITTED (C2-v2) — worker dừng tại đây trước J1 (sprint gate §3 rules).

## Correction C2-final (2026-08-25) — rg-gate mục 3.5: gỡ v1 artifact khỏi active tests

STATUS: TASK_SUBMITTED (C2-final)

FINDING: FROZEN_RESULTS (route_selection.py:38) + _frozen_results_path
(nvenc.py:685) còn load old t00-i05/measured_seed20260823 (schema v1) làm
frozen input — vi phạm prompt C2 mục 3.5.

FIX (chỉ write-set tests/test_s09_t02_*.py): cả hai trỏ sang C2 measured
run_A `output/s09/20260823_sprint_full/t00-i03-c2/run_A/
benchmark_results_seed20260823.json` (schema v3). Kỳ vọng hard-code v1 sửa
theo measured truth run_A (sprite_affine pass 5/6; pose_swap chỉ
mouth_expression_swap; psc check không pass đâu → annotated-swaps refuse
fail-closed 5 class). Thêm negative-assertion test chặn literal v1 quay lại
làm active input. Không đụng renderer production / benchmark script /
fixtures / thresholds.

| Gate | Kết quả |
|---|---|
| route_selection + pose_swap_nvenc ×2 basetemp | 44 passed mỗi run |
| UTF8 matrix (env -u PYTHONUTF8) | 44 passed |
| grep literal v1 trên app/ + T02 tests | 0 hit |
| ruff owned files | All checks passed |
| CONTRACT_FROZEN replay | KHÔNG ĐỔI = ea8ab211… (J1-v2 manifest giữ nguyên) |

TASK_SUBMITTED (C2-final) — worker dừng tại đây trước J1 (sprint gate §3 rules).

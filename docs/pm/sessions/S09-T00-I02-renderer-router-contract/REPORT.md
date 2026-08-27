# S09-T00-I02 — REPORT — RendererRouter/failure/license contract

- Session owner: Hermes 20260823_173054_faaf53 (worker implementation, provider custom @ 9Router, model alpha, reasoning max, fallback disabled).
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration · branch codex/s08-integration.
- Baseline HEAD khi bắt đầu: a43b20da742996bafcb2f9d1ac57b10d3f1a5204. Trong lúc làm, commit snapshot ee10e55 (20:46+07, do Manager/Codex thực hiện ngoài task này) đã capture phần lớn file của tôi vào git; các chỉnh sửa sau đó nằm ở working tree.
- RULES_LOADED: HERMES_AUTOPILOT_RULES.md (toàn bộ). Overlay TARGET_PROFILE_2D_SOURCE_LOCKED.md (toàn bộ, §4 P0-7 / §5 route priority / §8 thresholds / §10 license gate).
- Guard: MOTIONFORGE_DATABASE_URL UNSET trong toàn bộ phiên (verify bằng echo trước mọi đợt chạy test). MAIN read-only tuyệt đối.

## Deliverables

| File | Nội dung | SHA-256 |
|---|---|---|
| app/services/renderer_contract.py | Contract: failure taxonomy RendererContractCode (7 mã ổn định) + 1 exception type/mã; RenderRequest/CapabilityDescriptor/RouteProvenance/RenderResult frozen dataclasses; BackendAdapter protocol; license gate BACKEND_LICENSE_REGISTRY + FORBIDDEN_PRODUCT_LICENSES (NC refuse); PROVENANCE_REQUIRED_FIELDS; ROUTE_PRIORITY từ RENDERER_ROUTES (single authority); không import nặng module-level | 8ad733516aae4f9d7f5b4191ba4558fee6f37f92bca242dc6d7acdb2594076b0 |
| app/services/renderer_router.py | Router deterministic (sort theo route rank + backend_id), select_backend override API honor-exactly-or-raise, gate license/available/threshold giữ đúng taxonomy single-candidate, execute không bao giờ trả kết quả từ backend khác route, maybe_escalate measured-only (metric > threshold AND candidate_metric_projection < metric mới escalate, thiếu projection → refused), evidence JSON ghi cả khi refused | cc8bd6c5771b7012917474988a5704838a8c67b06b57dfdeaef9d4451159f638 |
| app/adapters/renderer/__init__.py | Package exports | e750e07f302916994f172b3e9a61a89976b2460836ab3ec3c58b5a6f6da70e2e |
| app/adapters/renderer/ffmpeg_binary.py | Probe FFmpeg thật (PATH + WinGet Links), đọc version + configuration header, suy license_id ffmpeg-gpl-build/ffmpeg-lgpl, fail-closed available=False+error | 079a7425273ed5becf866d078a63673d3f36ae658b212bf61be25686f622df30 |
| app/adapters/renderer/nvenc.py | Probe h264_nvenc bằng encode thật nullsrc 256x256 (root cause: NVENC min frame dim > 64x64 — probe đầu FAIL, log "Frame Dimension less than the minimum supported value", fix xong exit 0); vram_bytes_via_nvidia_smi | 0ad930324732a4ea8af4cd60f0f05db52c1df280af7e162f517f6eb5b94e6dd4 |
| app/adapters/renderer/encode_base.py | Nền chung adapter encode: measure_peak_vram_bytes_during (nvidia-smi -lms 120 sampler), capability() fail-closed với unavailable_reason_code=backend_binary_missing khi thiếu binary | 1c4e50a477c25983fa4d699f1bbba5ba4c6f8446af0c9d34bcdc2d66b25b88a3 |
| app/adapters/renderer/pose_swap_adapter.py | Adapter pose_swap THẬT: FFmpeg re-encode segment (-ss/-t frame-range @30fps), h264_nvenc khi có, fallback libx264 CPU, đo wall time + peak VRAM, _last_capability measured_live | 062a7bfd59643714d3b0450510ba85bf6623351496519eaa8c3c6fe9b4d4d347 |
| app/adapters/renderer/sprite_affine_adapter.py | Adapter sprite_affine THẬT: rotate(1°)+scale(1.02) filter qua FFmpeg encode, đo runtime/VRAM như trên | 7677affd690dc1fccc4657cead7fa9fc03669b1e4e21e23ec13249b94167429b |
| app/adapters/renderer/benchmark_harness.py | Harness nội bộ benchmark_wired_routes (I03 scripts/s09_renderer_benchmark.py chưa có tại thời điểm bắt đầu): clip testsrc2 thật, đo cả 2 route, ghi route_benchmark.json, default_route_mapping chỉ chọn route measured-ok, pose_swap ưu tiên theo overlay §8 | 4999d775bc6a880b22731c4c2840a81ef8c6378d2728003eaed0b495a69744fb |
| tests/test_s09_t00_renderer_router_contract.py | 17 test domain (xem bảng acceptance) | b5d31965159c346073621a9a00aed01644705726e77c0cb376dae7a0b3e92dee |
| tests/test_s09_t00_renderer_router_adapters.py | 11 test integration thật (probe/encode/benchmark/fail-closed binary-missing), skip trung thực nếu máy thiếu stack | bea8da60ca34505a8e8aa82088416e36a17b6fb90bba61ca5e58bf411b60ae31 |
| THIRD_PARTY.md | ADDITIVE: section "Renderer Router Wired Backends" — CHỈ FFmpeg (GPL build, header config detect được --enable-gpl --enable-version3, không nonfree) + NVENC runtime driver-bundled. Không thêm mục cho SAM-2/Cutie/model chưa wire | 3dc600b38834248225f0132d47546cddad99954a62c642b80f069c81f3e2ce6a |
| docs/pm/sessions/S09-T00-I02-renderer-router-contract/{LOG.md,TASK.md} | LOG append từng bước; TASK.md giữ nguyên | ace976cf1424fc533c3945957877abac68e7c7c7f37f821cd4ca42d21da5b72a (LOG) |
| output/s09/20260823_sprint_full/t00-i02/** | Evidence: route_benchmark.json, bench_pose_swap.mp4, bench_sprite_affine.mp4 | xem artifact |

KHÔNG wire (không có user authority): SAM-2, Cutie, mọi model download. mesh_warp/part_rig/controlled_redraw hiện KHÔNG có backend → request vào các route này raise UnknownCapabilityError (fail closed), đã test.

## Acceptance gate — binary evidence (lệnh thật, output thật)

| Gate | Kết quả | Bằng chứng |
|---|---|---|
| Benchmark pose_swap/sprite_affine TRƯỚC khi chọn default mapping | PASS | scripts/s09_renderer_benchmark.py (I03) chưa tồn tại lúc bắt đầu → dùng harness nội bộ benchmark_harness (TASK.md cho phép "harness nội bộ tối thiểu đo được và ghi rõ"). Chạy thật lần cuối sau refactor: pose_swap ok=True 6.151 ms/frame; sprite_affine ok=True 6.574 ms/frame; VRAM peak ~1.80GB. Artifact: output/s09/20260823_sprint_full/t00-i02/route_benchmark.json. default_route_mapping chỉ map route measured-ok: {pose_swap: ffmpeg-nvenc-pose-swap, sprite_affine: ffmpeg-nvenc-sprite-affine}. Output ffprobe xác minh: h264 320x240@30/1 đủ 24 frames (sprite_affine 319x240 do rotate pad). |
| Route persisted per segment qua SegmentRenderRoute repo — round-trip thật | PASS | test_route_persisted_per_segment_round_trip: record_render_route trên DB alembic-head temp → created=True, list_routes_for_video trả đúng row (anchor 0.25), replay idempotency_key trong transaction MỚI → created=False cùng id. test_invalid_route_enum_refused_by_persistence: route lạ bị StructuralLockParamsError ở repo VÀ DB CHECK chặn độc lập (pattern test I01). |
| Escalation ghi đủ 5 trường provenance + artifact path tồn tại | PASS | PROVENANCE_REQUIRED_FIELDS = (route_from, route_to, metric_name, metric_value, threshold); test_escalation_requires_measured_reduction case 3 assert đủ 5 trường trong record + json artifact trên disk có route_to=sprite_affine + artifact.is_file(). Refusal path cũng ghi evidence (kind=renderer_route_escalation_refused). |
| Không silent fallback — router KHÔNG BAO GIỜ trả kết quả từ backend khác route yêu cầu | PASS | test_router_never_returns_result_from_a_different_route: chỉ wire pose_swap, hỏi sprite_affine → UnknownCapabilityError/UnknownBackendError, không bao giờ có result từ pose_swap backend. test_execute_routes_to_exact_requested_backend: result.backend_id == đúng backend của route đó. Override không có trong registry → UnknownBackendError (không thay thế bằng backend khác). |
| Focused tests ×2 PASS, basetemp khác nhau | PASS | RUN1 --basetemp=%TEMP%/s09t00i02-r2a: 28 passed; RUN2 --basetemp=%TEMP%/s09t00i02-r2b: 28 passed (-p no:cacheprovider cả hai). |
| ruff check app tests | PASS | Toàn bộ file write-set của tôi: "All checks passed!". Lưu ý trung thực: `ruff check app tests` toàn repo vẫn còn lỗi ở tests/fixtures/s09_renderer/generate_fixtures.py + tests/test_s09_t00_benchmark_harness.py + scripts/s09_renderer_benchmark.py — các file này thuộc I03 (sprint song song), ngoài allowlist của tôi nên KHÔNG sửa. |
| mypy app (strict) | PASS | "Success: no issues found in 110 source files". |
| git diff --check | CLEAN | exit 0 (chỉ CRLF warning thông thường). |
| Self-audit write-set | PASS | Xem bảng bên dưới. |

## Failure taxonomy coverage (mỗi loại raise đúng exception — đã test)

- unknown_backend → UnknownBackendError (override không registered): test_unknown_backend_override_fails_closed
- unknown_capability → UnknownCapabilityError (route không có backend / candidate unavailable chung): test_unknown_capability_route_without_backends_fails_closed
- license_missing → LicenseMissingError (license ngoài registry hoặc NC): test_license_missing_refused_in_selection_and_gate + parametrize 4 giá trị cấm
- capability_mismatch → CapabilityMismatchError (route ngoài RENDERER_ROUTES, duplicate backend_id, request frame range sai)
- benchmark_below_threshold → BenchmarkBelowThresholdError (999 > 50 ms/frame gate): test_benchmark_below_threshold_raises — router giữ ĐÚNG loại này cho single-candidate thay vì nuốt thành unknown_capability
- backend_binary_missing → BackendBinaryMissingError (probe fail / descriptor available=False với unavailable_reason_code): test_adapter_fails_closed_when_binary_missing (capability + render + router select đều refuse)

## Self-audit write-set

Files tôi tạo/sửa trong phiên này (đúng allowlist):
1. app/services/renderer_contract.py (NEW) — allowlist ✓
2. app/services/renderer_router.py (NEW) — allowlist ✓
3. app/adapters/renderer/__init__.py, ffmpeg_binary.py, nvenc.py, encode_base.py, pose_swap_adapter.py, sprite_affine_adapter.py, benchmark_harness.py (NEW trong app/adapters/renderer/**) — allowlist ✓
4. THIRD_PARTY.md (additive section duy nhất) — allowlist ✓
5. tests/test_s09_t00_renderer_router_contract.py, tests/test_s09_t00_renderer_router_adapters.py (NEW, khớp tests/test_s09_t00_renderer_router*.py) — allowlist ✓
6. output/s09/20260823_sprint_full/t00-i02/{route_benchmark.json,bench_pose_swap.mp4,bench_sprite_affine.mp4} — allowlist ✓
7. docs/pm/sessions/S09-T00-I02-renderer-router-contract/LOG.md (append) — allowlist ✓; REPORT.md (này) — allowlist ✓; TASK.md không đổi.

Không đụng (verify bằng git status): models.py, migrations/, structural_lock.py, schemas/structural_lock.py, app/api/app.py, data/, frontend/, MAIN tree. Các entry M/?? khác trong git status (scripts/s09_renderer_benchmark.py, tests/fixtures/s09_renderer/*, tests/test_s09_t00_benchmark_harness.py) là sản phẩm task song song I03 — tôi không tạo và không sửa.

Sự cố đã xử lý trong phiên: (a) một tool call lệch ngữ cảnh đầu phiên ghi nhầm file TASK-031...md ra ngoài worktree (C:\Users\ttari\Desktop\saas\...) — đã xóa sạch + xác minh ls, chi tiết trong LOG.md; (b) process chết 2 lần giữa phiên (kill ngoài ý muốn) — resume đúng session sở hữu theo Rules §4, disk-state verify trước khi tiếp tục; (c) commit snapshot ee10e55 của bên thứ ba nuốt một phần working tree giữa chừng — không can thiệp, tiếp tục làm việc trên trạng thái mới.

## Findings / risks cho Codex review

1. NVENC min frame dimension: probe phải ≥ ~145px (dùng 256x256). Nếu tương lai thêm probe khác cần nhớ giới hạn này.
2. measure_peak_vram_bytes_during đo VRAM ở mức process-sampler (nvidia-smi memory.used hệ thống, không riêng process) — số tuyệt đối cao (~1.8GB gồm desktop/driver); đủ cho so sánh tương đối giữa routes, chưa phải per-process chính xác. Có thể nâng cấp sau bằng NVML nếu PM yêu cầu.
3. sprite_affine hiện là transform demo deterministic (rotate 1° + scale 1.02); khi S09-T01/T02 cần transform thật từ motion contract, adapter nhận transform qua RenderRequest mở rộng — interface contract đã sẵn sàng.
4. Router giữ taxonomy cụ thể chỉ khi single-candidate; multi-candidate fail gộp unknown_capability kèm chuỗi lỗi từng backend (quyết định thiết kế để tránh ambiguous khi nhiều backend fail khác loại).
5. I03 scripts/s09_renderer_benchmark.py xuất hiện giữa chừng trong worktree (task song song); harness nội bộ của tôi vẫn giữ vì tests phụ thuộc và TASK.md cho phép; hai đường benchmark không xung đột.

## Terminal state

STATUS: TASK_SUBMITTED

Worker tự dừng ở đây, không tự đánh giá APPROVED — chờ Codex Reviewer/PM review độc lập theo Rules §10.

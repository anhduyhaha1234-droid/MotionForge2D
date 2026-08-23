# S09-T00-I02 — RendererRouter/failure/license contract

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc trước mọi hành động)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md — đặc biệt §4 P0-7, §5 route priority, §10 license gate.
3. Worktree guard: cwd phải là C:/Users/Admin/MotionForge2D-worktrees/s08-integration, branch codex/s08-integration. MAIN C:/Users/Admin/MotionForge2D READ-ONLY tuyệt đối.
4. `MOTIONFORGE_DATABASE_URL` phải UNSET; DB chỉ dùng SQLite temp cô lập basetemp riêng `%TEMP%/s09t00i02-*`, `-p no:cacheprovider`.

## Context hiện tại (đã verified bởi Manager)
- S09-T00-I01 ĐÃ XONG + MANAGER_VERIFIED: ORM có `StructuralLockManifest`, `SegmentRenderRoute`, constants `RENDERER_ROUTES = {pose_swap,sprite_affine,mesh_warp,part_rig,controlled_redraw}`, `RENDERER_ROUTE_CHECK_SQL`; pin columns trên ReskinConfig/ApplyCheckpoint. Alembic head duy nhất: `d8e9f0a1b2c3`. app/persistence/structural_lock.py + app/schemas/structural_lock.py tồn tại — ĐỌC để tái sử dụng pattern (fail-closed validation, workspace-scoped idempotency, CAS revision) nhưng KHÔNG sửa.
- I04 đã normalize 6 test regression file sang live-head discovery.
- KHÔNG đụng models.py/migrations (I01 owned, verified). KHÔNG tạo migration mới trong task này.

## Outcome bắt buộc
1. NEW `app/services/renderer_contract.py`: dataclasses/protocols cho RenderRequest/RenderResult/capability descriptor; failure taxonomy enum ổn định (unknown_backend, unknown_capability, license_missing, capability_mismatch, benchmark_below_threshold...); không import nặng ở module level.
2. NEW `app/services/renderer_router.py`: deterministic capability registry; explicit route selection + override API; provenance record (route_from/route_to, metric, threshold, segment, evidence artifact path) khi escalate; unknown backend/capability FAIL CLOSED (raise, không silent fallback, không tự switch model/backend).
3. NEW `app/adapters/renderer/**`: adapter thật cho các backend khả dụng TRÊN MÁY NÀY theo lane-B audit: FFmpeg 8.1.2 + h264_nvenc (RTX 5070) → pose_swap/sprite_affine paths. KHÔNG wire SAM-2/Cutie/model download (không có user authority). Adapter phải đo được runtime + VRAM nếu CUDA available (nvidia-smi subprocess OK), fail-closed khi binary thiếu.
4. Additive `THIRD_PARTY.md` CHỈ ghi license của thứ THẬT SỰ được wire (FFmpeg — LGPL-2.1+ tùy build, ghi rõ header config nếu detect được). Không thêm mục cho thứ chưa wire.
5. `tests/test_s09_t00_renderer_router*.py`: deterministic registry ordering; route selection/override/provenance; failure taxonomy mỗi loại raise đúng exception; escalation chỉ khi measured error giảm (fixture metric giả lập được phép trong test, nhưng production code không được dùng stub); unknown backend fail-closed; KHÔNG NC/no-permission model trong product path; không QA stub trong production code.

## Acceptance gate (binary, phải in evidence vào REPORT)
- Benchmark pose_swap/sprite_affine TRƯỚC khi chọn default route mapping (chạy scripts/s09_renderer_benchmark.py nếu I03 đã sẵn sàng; nếu chưa, dùng harness nội bộ tối thiểu đo được và ghi rõ).
- Route persisted per segment qua SegmentRenderRoute repo (từ structural_lock.py) — test round-trip thật.
- Escalation event ghi đủ 5 trường provenance + artifact path tồn tại.
- Không silent fallback: assert router KHÔNG BAO GIỜ trả kết quả từ backend khác route yêu cầu.
- Focused tests ×2 liên tiếp PASS (basetemp khác nhau giữa 2 run), ruff check app tests PASS, mypy app PASS, git diff --check sạch.
- Self-audit write-set: chỉ đúng các file allowlist bên dưới.

## Write allowlist (NGHIÊM)
- NEW app/services/renderer_contract.py
- NEW app/services/renderer_router.py
- NEW app/adapters/renderer/** (files mới trong thư mục này)
- THIRD_PARTY.md (additive only, chỉ mục thật wire)
- tests/test_s09_t00_renderer_router*.py
- output/s09/20260823_sprint_full/t00-i02/** (evidence, LOG.md, REPORT.md)
- docs/pm/sessions/S09-T00-I02-renderer-router-contract/{TASK.md đã có, LOG.md, REPORT.md}

## FORBIDDEN
MAIN tree · data/** · frontend/** · migrations/** · models.py · structural_lock.py/schemas (read-only) · app/api/app.py · network/model download · production DB/user media · git commit/push/reset/clean/stash · xóa/ghi đè output task khác · tạo session/task mới.

## Kết thúc
Ghi LOG.md append từng bước quan trọng; REPORT.md đầy đủ (deliverables table, required-tests binary evidence, self-audit write-set, hashes) kết thúc STATUS: TASK_SUBMITTED rồi STOP. Không tự đánh giá APPROVED.

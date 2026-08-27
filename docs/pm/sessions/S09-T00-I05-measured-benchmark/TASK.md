# S09-T00-I05 — Measured benchmark/report

## Role
Bạn là WORKER chạy measured benchmark cuối cùng của T00. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY.
3. `MOTIONFORGE_DATABASE_URL` UNSET; basetemp riêng `%TEMP%/s09t00i05-*`, `-p no:cacheprovider`.

## Context đã verified
- I02 verified: RendererRouter hoạt động thật, route_benchmark mẫu tại output/s09/20260823_sprint_full/t00-i02/route_benchmark.json (pose_swap OK 6.15ms/fr NVENC RTX 5070).
- I03 verified: scripts/s09_renderer_benchmark.py + tests/fixtures/s09_renderer/** (thresholds.json frozen) + fixtures_gen đủ 6 risk classes byte-identical ×2; frozen SHA `0ba6f6460f281028…` phải khớp khi chạy lại freeze banner TRƯỚC đo.
- Reference media `5A175454…` KHÔNG có trên máy → mọi kết quả liên quan reference = SKIP_WITH_REASON, không fake pass.

## Outcome bắt buộc (write allowlist: output/s09/20260823_sprint_full/t00-i05/** + docs/pm/sessions/S09-T00-I05-measured-benchmark/{LOG.md,REPORT.md})
1. Chạy harness trên golden/risk fixtures khả dụng: ít nhất pose_swap và sprite_affine trên cả 6 fixture classes (hard cut, mouth region, phone contact, whole-body rotation, group occlusion, semantic graphic). Ghi raw machine-readable results JSON mỗi run.
2. So sánh 2 routes per risk class: error metrics từng route; smallest passing route per risk class theo thresholds frozen trong tests/fixtures/s09_renderer/thresholds.json.
3. Escalation decision: chỉ escalate lên route nặng hơn khi measured error thực sự giảm; nếu không có route nào pass một class → ghi FAIL-OPEN-QUESTION (đừng tune threshold).
4. Ghi runtime/VRAM/correction counts từ results fields đã có (wall_runtime_ms_per_frame, vram_peak_mib là non-deterministic-declared).
5. Exact commands/environment/hashes: frozen SHA banner output, git HEAD, versions (python/ffmpeg/nvenc), seed, timestamps +07.
6. Tách bạch MEASURED / UNKNOWN / SKIPPED trong REPORT.md. Không tune threshold sau khi thấy kết quả — nếu metric nào không có sẵn trong results JSON thì UNKNOWN, đừng tự tính lại bằng công thức khác.

## Acceptance gate
- Freeze banner SHA == `0ba6f6460f281028…` (in ra trước lần đo đầu, lưu vào evidence).
- Raw results JSON đầy đủ per-run; hai runs same-seed: core identical sau khi strip declared non-deterministic fields.
- REPORT.md: bảng route-per-risk-class với verdict pass/fail/skip từng dòng, escalation log, exact commands, hashes. STATUS: TASK_SUBMITTED rồi STOP.

## FORBIDDEN
Sửa bất kỳ file production/test/script/fixture nào (I01–I04 owned) · MAIN · data/** · network/model download · tạo migration · git history ops · đụng output task khác (chỉ ĐỌC).

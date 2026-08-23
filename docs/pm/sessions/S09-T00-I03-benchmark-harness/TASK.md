# S09-T00-I03 — Frozen benchmark harness/golden fixtures

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled.

## Bước 0 (bắt buộc trước mọi hành động)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md — đặc biệt §8 thresholds (đóng băng), §4 risk classes.
3. Worktree guard: cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration, branch codex/s08-integration. MAIN READ-ONLY tuyệt đối.
4. `MOTIONFORGE_DATABASE_URL` UNSET; SQLite temp basetemp riêng `%TEMP%/s09t00i03-*`, `-p no:cacheprovider`.

## Context hiện tại
- I01 verified: `SegmentRenderRoute` ORM + repo `app/persistence/structural_lock.py` (route enum 5 giá trị, anchors [0,1]) — đọc để hiểu schema, KHÔNG sửa.
- Lane-C audit measured: timebase roundtrip 240/240 mismatch=0; centroid residual median 1.75px / P95 22.15px → bbox-affine KHÔNG đủ fidelity; cost 0.90ms/frame. Dùng làm reference số trong fixture design (ghi nguồn vào evidence).
- FFmpeg 8.1.2 + h264_nvenc + RTX 5070 có trên máy (lane-B probe). Synthetic fixtures PHẢI render được bằng ffmpeg color=smptebars/testsrc + filter — không cần media thật của user.
- Verified-reference fixture SHA `5A175454…` từ overlay: nếu không tìm thấy trên máy thì SKIP_WITH_REASON rõ ràng trong REPORT (không fake pass).

## Outcome bắt buộc
1. NEW `scripts/s09_renderer_benchmark.py`:
   - Deterministic route harness CLI: `--routes pose_swap,sprite_affine --fixtures <dir> --out <dir> --seed N`.
   - Metrics bắt buộc mỗi run: frame error, timebase/cut error (frames), trajectory median/P95 (% diagonal), scale P95 (%), rotation P95 (°), contact P95 (%), z-order inversions (count), unexplained visibility events (count), clipping-from-source-silhouette (bool/count), correction counts, wall runtime, VRAM peak (nếu CUDA).
   - FREEZE trước khi đo: in `schema_version=1` + content SHA256 của (harness source + fixture set + thresholds) RA STDOUT/JSON TRƯỚC lần chạy đo đầu tiên; mọi measured result phải kèm frozen SHA này.
   - Hai seeded runs với cùng seed phải identical (byte-compare results JSON trừ trường runtime/VRAM — ghi rõ các trường non-deterministic được loại).
2. NEW `tests/fixtures/s09_renderer/**`: golden fixtures SYNTHETIC sinh bằng ffmpeg (testsrc/smptebars/gradients) cho ít nhất: hard cut, mouth/expression region, phone-contact region, whole-body rotation, group occlusion, semantic graphic replacement (6 risk classes khớp T03). Mỗi fixture kèm manifest JSON (fps, resolution, expected regions, ground-truth annotations) — ground truth là synthetic metadata bạn tự định nghĩa lúc sinh, KHÔNG phải data user.
3. NEW `tests/test_s09_t00_benchmark*.py`: harness determinism (2 runs same-seed identical), threshold evaluation đúng công thức, skip-with-reason khi thiếu verified reference, fail-closed khi fixture manifest thiếu/trùng lặp.
4. Evidence output/s09/20260823_sprint_full/t00-i03/**: fixture generation logs, frozen SHA, dry-run benchmark output.

## Thresholds (FROZEN — không tune sau khi thấy kết quả)
cut/action error ≤1 frame · trajectory median ≤0.5% P95 ≤1.0% diagonal · scale P95 ≤3% · rotation P95 ≤3° · contact P95 ≤1.0% · zero annotated z-order inversion · zero unexplained visibility · zero clipping do reuse source silhouette · hai seeded runs identical.

## Acceptance gate
- Focused tests ×2 PASS (basetemp khác nhau), ruff check scripts tests PASS, mypy scripts PASS (nếu scripts nằm ngoài mypy config thì ghi rõ cấu hình), git diff --check sạch.
- Frozen SHA in ra TRƯỚC measured run và được trích dẫn trong REPORT.
- Self-audit write-set chỉ đúng allowlist.

## Write allowlist (NGHIÊM)
- NEW scripts/s09_renderer_benchmark.py
- NEW tests/fixtures/s09_renderer/**
- NEW tests/test_s09_t00_benchmark*.py
- output/s09/20260823_sprint_full/t00-i03/**
- docs/pm/sessions/S09-T00-I03-benchmark-harness/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN tree · data/** · frontend/** · app/** (chỉ ĐỌC structural_lock.py/models.py nếu cần schema) · migrations/** · network/model download · production DB/user media thật · git history ops · output task khác · tạo session/task mới.

## Kết thúc
LOG.md append; REPORT.md đầy đủ (deliverables, required-tests binary evidence, frozen SHA, fixture list + ground-truth summary, self-audit write-set, skips-with-reason) kết thúc STATUS: TASK_SUBMITTED rồi STOP.

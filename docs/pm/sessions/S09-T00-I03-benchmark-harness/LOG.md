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

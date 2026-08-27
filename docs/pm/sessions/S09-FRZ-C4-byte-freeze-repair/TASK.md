# S09-FRZ-C4 — Byte-freeze repair (newline normalization ONLY)

## Nhiem vu
Restore v4 exact bytes bang newline normalization ONLY — khong dung semantic/code.

- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration
- Manifest: output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json (version 4, head ee10e55a809c84d5cb5d4a3046a1ee78828528d0, frozen_at 2026-08-25T23:15:00+07:00)
- Model: meta (9Router round-robin cmc/meta/muse-spark-1.2-contributor + ocg/muse-spark-1.2-contributor), reasoning max, fallback disabled
- Exclusive write-set EXACTLY 7 files: renderer_contract.py, renderer_router.py, benchmark_harness.py, encode_base.py, ffmpeg_binary.py, pose_swap_adapter.py, sprite_affine_adapter.py
- Plus: output/s09/20260823_sprint_full/freeze-c4-meta/** va docs/pm/sessions/S09-FRZ-C4-byte-freeze-repair/{TASK,LOG,REPORT}.md
- Forbidden: moi file khac, formatter, import sorter, code rewrite, git restore/checkout.

## Quy trinh binary bat buoc
1. Recompute direct byte SHA va normalized LF SHA cho ca 13 files — ghi bang before.
2. Voi moi 7 file, assert normalized LF == expected truoc khi write, else BLOCKED_FREEZE_CONTENT_DRIFT.
3. Viet lai 7 file UTF-8 no BOM LF duy nhat, giu final-newline.
4. Chung minh normalized before/after identical va direct after == expected.
5. Re-hash 13/13 direct MATCH.
6. git diff --check + py_compile + import smoke.
7. Khong chay full tests (giu I03/I05).
8. Tao TASK/LOG/REPORT voi before/after SHA va STATUS TASK_SUBMITTED.

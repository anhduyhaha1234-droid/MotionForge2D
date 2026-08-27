# S09-T01 — Source-Locked Reskin Mapping completion

## Role
Bạn là WORKER hoàn tất T01 theo Source-Locked contract. Session này RESUME owner `20260822_232748_b4b2ad` — Manager dispatch qua `--resume`, bạn không tự tạo session mới.

## Bước 0 (bắt buộc)
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — in `RULES_LOADED`.
2. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md.
3. Worktree guard cwd C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration; MAIN READ-ONLY tuyệt đối.
4. `MOTIONFORGE_DATABASE_URL` UNSET; SQLite temp basetemp riêng `%TEMP%/s09t01-*`, `-p no:cacheprovider`.

## Context hiện tại (đã Manager verified 24/08 00:10+07)
- Foundation cũ của chính session này (models.py additive ReskinConfig/ApplyCheckpoint, migration c9d0e1f2a3b4, routes/schemas/client, 48 tests pass) GIỮ NGUYÊN — Codex đã duyệt giữ làm nền.
- I01 verified: StructuralLockManifest + SegmentRenderRoute ORM/repo (`app/persistence/structural_lock.py`), migration head hiện tại **`d8e9f0a1b2c3`** (discover live, đừng hard-code).
- I02 verified: RendererRouter (`app/services/renderer_router.py`) + adapters FFmpeg/NVENC thật; route enum {pose_swap,sprite_affine,mesh_warp,part_rig,controlled_redraw}.
- I03/I05 verified: benchmark harness + measured results 6/6 classes smallest-passing = pose_swap (output/s09/20260823_sprint_full/t00-i05/).

## Outcome bắt buộc (Source-Locked completion trên nền sẵn có)
1. `app/persistence/reskin_config.py`: pin StructuralLockManifest vào publish flow — publish/compatible/complete fail-closed khi manifest thiếu/hash lệch/route không thuộc enum; CompatibilityPolicy evidence per occurrence/shot (không opaque global score).
2. `app/schemas/reskin_config.py` + `app/api/routes/reskin_config.py`: expose manifest_id/lock_policy_version/renderer_route per segment trong response; additive OpenAPI (removed=0); anchors x/y normalized [0,1] từ SegmentRenderRoute.
3. Additive router registration `app/api/app.py` nếu route chưa đăng ký (chỉ thêm, không đụng dòng khác).
4. `frontend/src/features/reskin/index.ts`: typed client additions cho schema mới (additive).
5. `tests/test_s09_reskin_config_*.py`: adversarial suite — publish fail-closed (manifest missing/hash mismatch/invalid route), CAS/idempotency/workspace isolation zero mutation ×2 chiều, pin không đổi khi pack version mới, OpenAPI additive count check, 48 test cũ cùng xanh.

## Acceptance gate
- Focused/adversarial tests ×2 PASS (basetemp khác nhau), full backend regression liên quan (reskin + structural lock + persistence) PASS.
- OpenAPI: removed=0, additive paths only.
- ruff app+tests, mypy app, git diff --check sạch.
- Không đụng migrations/** (không tạo revision mới — dùng d8e9f0a1b2c3 đã có), không đụng structural_lock.py/models.py (chỉ import).
- Self-audit write-set đúng allowlist. LOG.md append; REPORT.md STATUS: TASK_SUBMITTED rồi STOP.

## Write allowlist (NGHIÊM)
app/persistence/reskin_config.py · app/schemas/reskin_config.py · app/api/routes/reskin_config.py · app/api/app.py (additive registration only) · frontend/src/features/reskin/index.ts · tests/test_s09_reskin_config_*.py · output/s09/20260823_sprint_full/t01/** · docs/pm/sessions/S09-T01-reskin-mapping-contract/{LOG.md,REPORT.md}

## FORBIDDEN
MAIN · data/** · migrations/** · models.py · structural_lock.py · renderer_* files · network/model download · production DB/user media thật (media projects/ chỉ ĐỌC khi test cần sample) · git history ops · output task khác.

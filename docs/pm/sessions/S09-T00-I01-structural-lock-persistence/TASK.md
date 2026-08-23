# S09-T00-I01 — StructuralLock/anchor/route persistence

## Role
Bạn là WORKER implementation duy nhất của task này. Provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback DISABLED. Route sai → BLOCKED_MODEL_ROUTE.

## Bước 0 — bắt buộc trước mọi hành động
1. Đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md → báo RULES_LOADED trong LOG.
2. HARD WORKTREE GUARD: pwd phải là C:/Users/Admin/MotionForge2D-worktrees/s08-integration; git rev-parse --show-toplevel khớp; git branch --show-current = codex/s08-integration; git rev-parse HEAD ghi vào LOG (pin); git status --porcelain | wc -l snapshot vào LOG.
3. MOTIONFORGE_DATABASE_URL phải UNSET (kiểm tra lệnh thật).
4. Đọc MAIN overlay: docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md §4 P0-1/P0-4/P0-7 và §8 thresholds.

## Outcome (tất cả đều bắt buộc)
Versioned StructuralLockManifest persistence + contact-anchor normalized x/y + renderer route/provenance per occurrence segment + fields pin manifest/policy/routes vào ReskinConfig/ApplyCheckpoint HIỆN CÓ (additive columns/tables, KHÔNG duplicate bảng foundation cũ của worker sess 20260822_232748_b4b2ad).

## EXCLUSIVE WRITE ALLOWLIST (không gì khác)
- app/persistence/models.py — ADDITIVE ONLY (zero removed lines so với trạng thái đầu phiên của bạn; pin baseline hash eaf8a484)
- ĐÚNG MỘT revision mới migrations/versions/<new>_s09_t00_structural_lock.py với down_revision = LIVE alembic head discover bằng lệnh (hiện c9d0e1f2a3b4 nhưng PHẢI discover runtime, không hard-code)
- NEW app/persistence/structural_lock.py
- NEW app/schemas/structural_lock.py (nếu cần)
- tests/test_s09_t00_structural_lock_domain.py, tests/test_s09_t00_structural_lock_migration.py, tests/test_s09_t00_structural_lock_api.py (chọn scope phù hợp)

## FORBIDDEN
MAIN tree, data/**, frontend/**, app/services/**, app/api/app.py (KHÔNG include_router trong task này — route API chưa yêu cầu), sửa file của task khác, network/model download, production DB, commit/push/reset/clean/stash/checkout.

## Acceptance (binary)
- Live single head làm down_revision; sau migration chỉ MỘT head.
- upgrade→downgrade→upgrade byte-identical trên empty graph (dump schema so sánh).
- Downgrade fail closed khi có row (refuse, không mất dữ liệu).
- PRAGMA foreign_key_check = 0 rows; ORM parity metadata so schema DB.
- models.py zero removed lines (difflib proof, ghi số liệu vào LOG).
- Workspace/project isolation: mọi query scope theo workspace_id/project_id.
- Renderer route enum CHÍNH XÁC: {pose_swap,sprite_affine,mesh_warp,part_rig,controlled_redraw} — persist per occurrence segment kèm provenance JSON.
- Contact anchor normalized x/y in [0,1] per occurrence segment.
- Focused tests pass ×2 liên tiếp; ruff check app tests sạch; mypy app sạch; git diff --check sạch.
- OpenAPI không đổi (không route mới) — chứng minh bằng diff schemas count nếu có client generate.

## Deliverables evidence
output/s09/20260823_sprint_full/t00-i01/** : LOG.md (timestamped +07), REPORT.md kết thúc STATUS: TASK_SUBMITTED + self-audit write-set, test logs ×2, alembic heads log, migration round-trip log.

## Protocol
Không đụng output/session task khác. Không tự APPROVED. Dừng ngay sau STATUS: TASK_SUBMITTED.

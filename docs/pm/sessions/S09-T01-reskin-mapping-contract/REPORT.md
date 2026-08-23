# REPORT — S09-T01 Reskin Mapping Contract

- **Session**: S09-T01-reskin-mapping-contract (worker: alpha @ custom, reasoning max)
- **Run id**: 20260822_worker_r1
- **Date**: 2026-08-23 (+07)
- **Worktree**: C:\Users\Admin\MotionForge2D-worktrees\s08-integration (branch codex/s08-integration)
- **Status**: **TASK_SUBMITTED** (chờ Manager/Codex review — KHÔNG tự APPROVED)

## Deliverables (đúng allowlist TASK.md "Exclusive write ownership")

| File | Loại | Nội dung |
|---|---|---|
| app/persistence/models.py | ADDITIVE ONLY | +2 ORM class `ReskinConfig`, `ApplyCheckpoint` + 2 dòng `__all__`. Đã chứng minh additive: diff vs HEAD = 0 removed lines; mọi class HEAD còn nguyên vẹn |
| migrations/versions/c9d0e1f2a3b4_s09_reskin_config_and_apply_checkpoint.py | NEW | DUY NHẤT 1 revision S09, down_revision=b2c3d4e5f6a7b, tạo HAI bảng reskin_config + apply_checkpoint (schema-only đầy đủ cho T06). Fail-closed downgrade: từ chối nếu có bất kỳ row nào |
| app/persistence/reskin_config.py | NEW | Repository + validate_params fail-closed; tái sử dụng evaluate_compatibility của S07 (không re-implement), strict hơn S07: không cho fallback qua |
| app/schemas/reskin_config.py | NEW | Pydantic strict extra=forbid DTOs |
| app/api/routes/reskin_config.py | NEW | Router /api/v2/reskin-configs + trailing-slash variants; 201 create / 200 replay / 409 conflict+CAS / 404 / 422 |
| app/api/app.py | ADDITIVE include_router only | +import, +comment, +include_router(reskin_config.router) — 4 dòng |
| frontend/src/features/reskin/index.ts | NEW thin client | Typed API client + types mirror backend contract. tsc --noEmit PASS, eslint --max-warnings 0 PASS |
| tests/test_s09_reskin_config_domain.py | NEW | 26 test: published/compatible/complete gate, CAS zero-mutation, idempotent replay, version isolation pin, params fail-closed ×15 case |
| tests/test_s09_reskin_config_api.py | NEW | 14 test API binary gates |
| tests/test_s09_reskin_migration.py | NEW | 8 test migration: single head, round-trip byte-identical, refusal atomic, ORM parity, FK RESTRICT, CHECK immutability |

## Required tests (binary) — bằng chứng chạy thật

1. **Published/compatible/complete gate** — PASS (domain tests 1a/1b/1c: draft/validating/ready/archived + incomplete đều reject zero mutation)
2. **Revision CAS stale → conflict + zero mutation** — PASS (domain + api + S07 regression stale_repin_zero_mutation)
3. **Idempotent replay equivalent → existing; conflicting → 409** — PASS
4. **Publish version mới không mutate pin** — PASS (test_s09 domain + 6 test isolation S07 ×2 liên tiếp)
5. **Migration round-trip byte-identical + PRAGMA foreign_key_check=0 + single head** — PASS (migration-roundtrip.log STEP3 True, fk=0, alembic-heads.log chỉ c9d0e1f2a3b4)
6. **OpenAPI additive thuần** — PASS: paths 215→219 (+4 path mới /api/v2/reskin-configs*), removed=0, op-added trên path cũ=0, schemas +8/-0
7. **Domain validation fail-closed mọi param** — PASS (15 parametrize case + schema 422 ×7 mutator + extra-field)

## Gates tổng

- Focused/full S09 suite ×2: **48 passed** mỗi lần (pytest-final-run1.log, run2.log)
- ruff check app tests: **All checks passed!** (ruff.log)
- mypy app: **Success: no issues found in 99 source files** (mypy.log)
- git diff --check: **EXIT=0**
- alembic heads: **c9d0e1f2a3b4 (head)** — đúng 1 head, down_revision=b2c3d4e5f6a7b
- Worktree delta vs baseline (259→266): đúng 7 path allowlist, không đụng file khác

## ⚠️ Vấn đề cross-sprint cần quyết định của Manager (ngoài allowlist worker)

Thêm migration mới làm các assertion hard-code revision cũ trong test sprint trước đỏ.
Worker KHÔNG được sửa (TASK.md Forbidden: "S07/S08 tests+code — chỉ đọc regression"):

1. tests/test_s07_version_isolation.py::test_migration_round_trip_preserves_invariant —
   hard-code head="b2c3d4e5f6a7b" (dòng ~584) → assert version==head FAIL vì head thật giờ là c9d0e1f2a3b4.
   Round-trip thực tế vẫn byte-identical với head mới — chỉ constant cũ sai.
2. tests/test_persistence_bootstrap.py — S08_HEAD_TABLES chưa gồm reskin_config/apply_checkpoint →
   test_no_api_cutover_tables ("unexpected tables") + schema-drift assert sẽ FAIL;
   các assert version == "b2c3d4e5f6a7b" (dòng 705/734/994) tương tự.
3. tests/test_object_correction.py:527, test_object_extraction.py:380, test_object_grouping.py:315,
   test_object_intelligence_domain.py:132 — assert version == "b2c3d4e5f6a7b".

Đề xuất: Manager cấp hotfix-scope riêng (update constants → ScriptDirectory.get_heads() hoặc thêm
2 bảng vào S08_HEAD_TABLES) hoặc gán cho task kế trong sprint. Đây là hệ quả tất yếu của MIGRATION
DECISION A (T01 sole migration owner) — không phải defect của implementation.

## Evidence

output/s09/s09-t01/20260822_worker_r1/: openapi-before.json, openapi-after.json,
pytest-final-run1.log, pytest-final-run2.log, pytest-s07-isolation-run1.log, run2.log,
ruff.log, mypy.log, git-diff-check.log, alembic-heads.log, migration-roundtrip.log.

LOG.md đầy đủ (append-only): docs/pm/sessions/S09-T01-reskin-mapping-contract/LOG.md

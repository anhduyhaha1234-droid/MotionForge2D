# S11-T02B — QCItem repository + internal idempotent creation/recheck lifecycle + read-only API (W2)

Task: S11-T02B (W2, full-sprint S11 T02..T06, isolated-worktree mode)
Session rule: NEW SESSION (no manager resume, no other task session)
Worktree: C:\Users\Admin\MotionForge2D-worktrees\s11-t02b-0903w2
Branch: codex/s11/t02b-0903w2
WAVE_BASE: 6861177149e1d12653f045ab2a44933b8d0f6d57 (canonical codex/s11-integration sau merge T02A; porcelain=0)

## Required reading (đã đọc đầy đủ)

- AGENTS.md (worktree) — trong context.
- docs/pm/SESSION_PROTOCOL.md (MAIN, read-only) — byte-safe protocol, single-writer,
  deliverables, status flow.
- Binding task block (task prompt W2) + docs/pm/sprints/S11-SPRINT_CONTRACT.md (MAIN).
- Read-only planning authority (s08-integration, read-only):
  `output/s11-post-t01-readiness/r1/synthesis/S11_T02_T06_PRODUCTION_PLAN.md`
  SHA 342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F — W2/T02B section
  (L102-121) + lane-A QC_DOMAIN_CONTRACT §1.3 rules 1/4/5, §2 #4/#5 + lane-C
  API_UI_GAP_MATRIX G1/G2/G4 (shape) + REVIEW_QUEUE_CONTRACT §1.2 (3 tầng view shape).
- app/persistence/models.py — class QCItem (L3072, TimestampMixin với revision), enum tuples
  QC_ITEM_STATUSES/SEVERITIES/CATEGORIES/QC_REASON_CODES, UNIQUE natural key 7 cột
  uq_qc_item_natural_key, CHECK blocker→dismissed (chỉ IMPORT, không sửa).
- app/persistence/reskin_config.py + app/schemas/reskin_config.py + app/api/routes/reskin_config.py
  — repository pattern (Session, frozen dataclass DTO, error classes, _map_row), Pydantic
  from_record + list response, route pattern (SessionDep, WORKSPACE_ID server-owned, 422/404/409).
- app/api/deps.py — SessionDep (L263/290).
- app/api/app.py — include_router block (baseline hash dưới).
- tests/conftest.py — `_patch_project_root` + `client` fixtures (alembic head DB, deps patched).
- tests/test_s11_t02a_qc_schema.py — seed pattern raw SQL (workspace/project/video_item) +
  concurrency barrier pattern (L334-383).

## Baseline (2026-09-03 +07)

- `git status --porcelain` → (empty) — porcelain 0, tree clean.
- `git branch --show-current` → codex/s11/t02b-0903w2
- `git rev-parse HEAD` → 6861177149e1d12653f045ab2a44933b8d0f6d57 = WAVE_BASE
- `env | grep -i MOTIONFORGE` → none (runtime env sạch).
- SHA-256 baseline các file hiện hữu đụng tới + protected:
  - app/api/app.py                   7c727e4c4b5a83a2ff72fb38dd8685e461b488dc73f10dacff2f07b78280442b (sẽ bounded patch additive)
  - app/persistence/models.py        f1df093927737cd2341de503abc1af5c58f139d4ff73978b175164d4ace93e6b (protected — KHÔNG đụng)
  - migrations/versions/e11a02a2026f_s11_t02a_qc_item.py b9c00b11b6e1291f4402d7c7efd1cb6eea046aaaba7771acd0a3909657b4bceb (protected)
  - tests/test_s11_t02a_qc_schema.py c776da6519c5a2217706baf31eb1020f411673f58c3c61c402d33bd99e4ce86e (protected)
  - tests/test_s11_t02a_qc_migration.py 69eacc0dc0d07ab45007b62883f8d8fea12042c77502fd920453f49b33eb30b1 (protected)
- File mới allowlist chưa tồn tại: app/persistence/qc_items.py, app/schemas/qc_items.py,
  app/api/routes/qc_items.py, 2 test files (ls → No such file).
- `python --version` → 3.11.9; pytest 9.1.1.

## Plan (ngắn)

1. Materialize OpenAPI paths BEFORE (app.main import — zero effect, không touch DB):
   `docs/pm/sessions/S11-T02B/evidence/openapi_paths_before.txt`.
2. RED: 2 test files mới (repository+lifecycle, api-readonly) — fail đúng lý do
   (app.persistence.qc_items / app.schemas.qc_items / router chưa tồn tại).
3. Implement: repository + lifecycle service; DTO frozen dataclass; router READ-ONLY
   (GET list theo G1 shape + detail theo G2 shape); app.py 1 dòng include_router additive
   (+1 dòng import additive). Zero mutation method.
4. GREEN: 2 test file 1 lệnh isolation chuẩn; grep router zero POST/PUT/PATCH/DELETE;
   OpenAPI removed=0 (so before/after); ruff --select F.
5. Self-review `git diff WAVE_BASE` scope = allowlist; stage allowlist +
   docs/pm/sessions/S11-T02B/**; commit local; REPORT TASK_SUBMITTED; EXIT.
   KHÔNG push/merge/rebase/reset/clean/stash.

## Nhật ký thực thi (chronological)

## Nhật ký thực thi (chronological)

- RED: tạo tests/test_s11_t02b_qc_repository_lifecycle.py (17 tests) +
  tests/test_s11_t02b_qc_api_readonly.py (12 tests); chạy 1 lệnh isolation chuẩn
  (`-p no:cacheprovider`, basetemp= mfc_t02b_r1, env strip MOTIONFORGE_DATABASE_URL) →
  `ModuleNotFoundError: No module named 'app.persistence.qc_items'` (2 collection
  errors) — fail đúng lý do behavior mới chưa tồn tại.
- Materialize OpenAPI BEFORE (trước khi đăng ký router): `app.main` import +
  `app.openapi()` → 263 paths → `evidence/openapi_paths_before.txt`; grep qc-item = 0.
- Implement (3 file mới whole-file + app.py bounded additive patch):
  - app/schemas/qc_items.py — frozen dataclass DTO `QCItemData` / `QCItemListResponse`
    (from_record, G1/G2 shape navigation-ready).
  - app/persistence/qc_items.py — `QCItemRepository` + lifecycle: create idempotent qua
    `sqlite_insert(...).on_conflict_do_nothing(index_elements=7 natural-key cols)` +
    consistent read (KHÔNG check-then-insert; C4-F1); get/list read-only với filter
    status/severity/category/video_item_id + pagination (created_at DESC, id DESC);
    acknowledge (non-terminal); recheck_resolved/recheck_dismissed (TERMINAL — bắt buộc
    evidence mới, QCItemEvidenceRequiredError nếu thiếu/empty); recheck_failed
    (acknowledged→open khi recheck còn hiện diện, cũng cần evidence); terminal không thể
    đảo ngược; blocker→dismiss bị chặn trước DB (QCItemBlockedDismissalError);
    ownership fail-closed (get/list theo workspace — foreign = NotFound); DTO boundary:
    chỉ trả frozen `QCItemRecord`, ORM không ra khỏi module.
  - app/api/routes/qc_items.py — router READ-ONLY prefix /api/v2, tags qc-items:
    GET /projects/{project_id:uuid}/qc-items (list + filter + limit/offset; 422 cho
    filter sai) + GET /qc-items/{item_id:uuid} (detail; 404 cho unknown/foreign).
  - app/api/app.py — patch tool fuzzy-match phá indent import block 2 lần → chuyển
    byte-exact replace script (CRLF-aware, preimage assert) — import `qc_items` (1 dòng)
    + include_router(qc_items.router) (1 dòng + 1 comment). `git diff --numstat` = 3 0
    (removed=0).
- GREEN loop: lần chạy đầu `35 passed, 5 failed` — 4 lỗi kỳ vọng 405 sai (POST/PUT/PATCH/
  DELETE tới base /api/v2/qc-items → thực tế 404 vì không route nào match; with-id URLs
  → 405) + 1 kỳ vọng 422 sai (non-uuid không match {item_id:uuid} converter → 404).
  Sửa test expectation về fail-closed chuẩn (404/405 — mutation verb không bao giờ chạy).
  Cuối: `40 passed, 23 warnings` ×3 fresh roots (r4 34.65s / r5 34.62s / r6 34.89s).
- r5 cleanup: ruff F phát hiện F401 (`sqlalchemy.text` unused) + F541 (f-string không
  placeholder) → sửa, `ruff check --select F` 6 files → `All checks passed!` (exit 0).
- Concurrency stability: test_concurrent_create_same_natural_key_deterministic_reuse
  chạy riêng → `1 passed in 2.43s`.
- Gates: grep `@router.(post|put|patch|delete)` trong router = 0 match (exit 1);
  router có 4 @router.get; router grep recheck|acknowledge|transition|create|update|delete
  = 0 (router không import lifecycle); OpenAPI AFTER = 267 paths (263→267, removed=0,
  đúng 4 qc-item paths mới, methods đều ['get']); `python -m alembic heads` →
  `e11a02a2026f (head)` single head (không đụng migrations).
- Self-review: `git status --porcelain` = 1 M (app.py) + 5 ?? (4 allowlist mới + 2 tests)
  + docs/pm/sessions/S11-T02B/ — không gì ngoài allowlist.
- Commit local trên codex/s11/t02b-0903w2 (allowlist + evidence + sessions):
  commit `9c9878a51bf5da7b913593478f04fccc5c798e2a` (`feat(s11): T02B QCItem repository + internal idempotent lifecycle + read-only API (W2)`), 10 files staged (1 M + 9 A). KHÔNG push/merge/rebase/reset/clean/stash/force.
  Working tree sạch sau commit (porcelain 0). TASK_SUBMITTED — chờ Manager verify.

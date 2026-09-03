# S11-T02A — QCItem schema + migration + schema/migration tests (W1)
# + CORRECTION ROUND C1 (resume exact owner, finding T02A-C1 [P1])

Task: S11-T02A (W1, full-sprint S11 T02..T06, isolated-worktree mode)
Session rule: NEW SESSION (no manager resume, no other task session)
Worktree: C:\Users\Admin\MotionForge2D-worktrees\s11-t02a-0903w1
Branch: codex/s11/t02a-0903w1
WAVE_BASE (W1): 7751598214eedb6b72e3783e39a2a408721abe40
WAVE_BASE (C1, canonical fast-forward): b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9

## Baseline (2026-09-03 +07)

- `git status --porcelain` → (empty) — porcelain count 0, tree clean.
- `git branch --show-current` → codex/s11/t02a-0903w1
- `git rev-parse HEAD` → 7751598214eedb6b72e3783e39a2a408721abe40
- `env | grep -i MOTIONFORGE` → no MOTIONFORGE_* variable present (runtime env sạch).
- `unset MOTIONFORGE_DATABASE_URL; python -m alembic heads` →
  ```
  a10b11c12d3e (head)
  ```
  Single head. down_revision sẽ resolve từ live head này lúc tạo migration (không hard-code
  giá trị dispatch note; giá trị đo được = a10b11c12d3e trùng khớp note nhưng là kết quả đo).
- `app/persistence/models.py` baseline: SHA-256
  `a3a6f150f26c0481768320df1f9717f404990675371ac9b947d8e1dbd3b545f4`, 2976 lines
  (khớp pin dispatch a3a6f150f26c…).

## Required reading (đã đọc đầy đủ)

- AGENTS.md (worktree) — trong context.
- docs/pm/SESSION_PROTOCOL.md (MAIN, read-only) — byte-safe protocol, single-writer,
  deliverables, status flow.
- app/persistence/models.py — CONTACT_KIND_CHECK_SQL (L272), OCCURRENCE_CONFIDENCE_SOURCES
  (L197), TimestampMixin (L338), Project (L437), VideoItem (L479), OccurrenceSegment (L1560+,
  immutable id + logical_id/lineage_version), S10 head shipment style.
- migrations/versions/a10b11c12d3e_s10_full_apply_domain.py — migration style: standalone,
  frozen CHECK literals, fail-closed downgrade + _assert_db_integrity, op.create_table/create_index.
- tests/test_s10_full_apply_migration.py — round-trip byte-identical pattern, _cfg/_schema_sig,
  fail-closed downgrade seed pattern.
- docs/pm/prompts/S11_T02_T06_FULL_SPRINT_MANAGER_2026-09-03.md + S11_POST_T01_READINESS_MANAGER
  (MAIN) — binding task block trace; lane-A category/reason enumeration
  (trajectory_drift, cut_drift, contact_break, z_order, clipping, identity, flicker, audio_timecode).
- app/persistence/engine.py — create_engine_for_path (FK ON, busy timeout 5s, check_same_thread=False).
- migrations/env.py — imports app.persistence.models.Base (migration import của models-safe, nhưng
  convention repo = migration standalone với literal frozen; parity được test bắt).

## Plan (ngắn)

1. RED: viết tests/test_s11_t02a_qc_schema.py (6 tests C4-F1 + enum/blocker-dismissed extras,
   ORM create_all trên temp SQLite) và tests/test_s11_t02a_qc_migration.py (round-trip
   byte-identical, downgrade fail-closed, parity ORM↔migration, single head) → chạy fail đúng
   lý do (QCItem chưa tồn tại, migration e11a02a2026f chưa có).
2. Implement: models.py ADDITIVE-ONLY — enum tuples QC_ITEM_* + *_CHECK_SQL derived từ tuple
   duy nhất (pattern CONTACT_KIND_CHECK_SQL) + class QCItem (TimestampMixin, FK segment_row_id
   → occurrence_segment.id, pair-null CHECK, layer_ref non-null, evidence_window_key non-null,
   UNIQUE natural key 7 cột, blocker→dismissed CHECK) + __all__ additions.
   app/persistence/__init__.py — chỉ export symbols mới.
   migrations/versions/e11a02a2026f_s11_t02a_qc_item.py — down_revision = head ĐO ĐƯỢC
   (a10b11c12d3e, re-verify ngay trước khi tạo), fail-closed downgrade, PRAGMA integrity.
3. GREEN: chạy cả 2 test file 1 lệnh (isolation chuẩn), verify models.py added-only
   (git diff removed=0), alembic heads = 1 = e11a02a2026f, round-trip + foreign_key_check, ruff F.
4. Self-review git diff vs 7751598 scope chỉ allowlist; stage 5 paths + docs/pm/sessions/S11-T02A/**;
   commit trên codex/s11/t02a-0903w1; REPORT TASK_SUBMITTED; EXIT.

## Nhật ký thực thi (chronological)

- RED: tạo tests/test_s11_t02a_qc_schema.py + tests/test_s11_t02a_qc_migration.py; chạy
  `python -m pytest tests/test_s11_t02a_qc_schema.py tests/test_s11_t02a_qc_migration.py
  -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc_t02a_r1 -q` →
  `ImportError: cannot import name 'QC_ITEM_CATEGORIES' from 'app.persistence.models'`
  (2 collection errors) — fail đúng lý do behavior mới chưa tồn tại.
- Implement models.py (ADDITIVE-ONLY): thêm QC_ITEM_STATUSES/SEVERITIES/CATEGORIES/
  REASON_CODES + *_CHECK_SQL derived từ tuple duy nhất (pattern CONTACT_KIND_CHECK_SQL),
  QC_CONFIDENCE_SOURCE_CHECK_SQL (derive từ OCCURRENCE_CONFIDENCE_SOURCES),
  QC_ITEM_SEGMENT_PAIR_NULL_CHECK_SQL, QC_ITEM_BLOCKER_DISMISSED_CHECK_SQL, class QCItem
  (TimestampMixin; segment_row_id nullable FK RESTRICT → occurrence_segment.id;
  segment_logical_id nullable non-FK; pair-null CHECK; layer_ref_type/layer_ref_id/evidence_
  window_key/evidence_json/detector/detector_revision/confidence/confidence_source/
  checkpoint_ref NOT NULL; UNIQUE 7 cột natural key uq_qc_item_natural_key; blocker→dismissed
  CHECK ck_qc_item_blocker_not_dismissed) + __all__ additions.
  NOTE: patch tool fuzzy-match làm hỏng indent __all__ 2 lần → chuyển sang byte-exact
  replace script có preimage assertion (đúng bounded-patch protocol); kết quả cuối
  `git diff --numstat app/persistence/models.py` = `240 0` (zero removed).
- Implement app/persistence/__init__.py: chỉ export symbols mới (import block + __all__);
  `git diff --numstat` = `27 0`.
- Tạo migrations/versions/e11a02a2026f_s11_t02a_qc_item.py — re-verify heads NGAY trước khi
  tạo: `python -m alembic heads` → `a10b11c12d3e (head)` (single). down_revision =
  "a10b11c12d3e" (giá trị ĐO ĐƯỢC). Migration self-contained, frozen CHECK literals =
  byte twin ORM, fail-closed downgrade + PRAGMA integrity/foreign_key_check mọi path.
- GREEN loop: lỗi 1 = create_all không có server_default (project.description/status,
  video_item.status) → seed explicit; lỗi 2 = unique constraint là sqlite_autoindex
  (sqlite_master.sql NULL) → test dùng PRAGMA index_list origin='u' + partial=0; lỗi 3 =
  worker concurrent dùng ewk khác nhau → ép cùng evidence_window_key="ewk-same".
  Cuối: `31 passed, 8 warnings in 24.98s` (1 lệnh, isolation chuẩn, basetemp mfc_t02a_r10).
- Concurrency stability: chạy riêng test concurrent 3 lần liên tiếp → `1 passed` ×3
  (2.48s / 2.49s / 2.36s).
- `python -m alembic heads` (env sạch) → `e11a02a2026f (head)` — đúng 1 head = revision mới.
- `python -m py_compile` 5 files → PY_COMPILE-OK.
- `ruff check --select F` 5 files → `All checks passed!` (exit 0).
- Round-trip CLI evidence trên temp DB (`C:/Users/Admin/AppData/Local/Temp/mfc_t02a_cli.db`):
  upgrade → (37 tables, 180 indexes, fk_check=[], ok, rev=e11a02a2026f);
  downgrade a10b11c12d3e → (36, 173, [], ok, a10b11c12d3e); re-upgrade → (37, 180, [], ok,
  e11a02a2026f); qc_item present. Byte-identical đầy đủ do
  test_upgrade_downgrade_upgrade_empty_graph_byte_identical (schema_sig dict equality).
- Self-review: `git status --porcelain` chỉ có allowlist (2 M + 3 ?? + sessions dir);
  `git diff 7751598` scope = 5 paths + docs/pm/sessions/S11-T02A/**.
- Commit local trên codex/s11/t02a-0903w1 (allowlist + sessions evidence) —
  commit `7365f910e16ff0d9863c6c5e57c07ee92b6b151b` (`feat(s11): T02A QCItem schema +
  migration e11a02a2026f + schema/migration tests (W1)`), 7 files staged (2 M + 5 A).
  KHÔNG push/merge/rebase/reset/clean/stash/force. Working tree sạch sau commit.
## CORRECTION ROUND C1 (2026-09-03) — finding T02A-C1 [P1]

Manager finding: QC_REASON_CODES / QC_ITEM_CATEGORIES không khớp binding Decision B
(overlay §S11 L370-371) + Decision D. Cần đúng 10 codes: 8 overlay (trajectory_drift,
cut_drift, contact_break, z_order_error, silhouette_clipping, identity_drift,
edge_halo, temporal_flicker) + 2 audio (audio_missing, av_sync_drift).

### C1 baseline
- `git status --porcelain` → (empty) — worktree sạch; `git rev-parse HEAD` →
  b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9 (canonical fast-forward).
- `python -m alembic heads` → `e11a02a2026f (head)` — single head trước khi tạo fix.
- models.py enum cũ (8 codes) vẫn còn — xác nhận finding.

### C1 thực thi
- models.py (bounded patch, byte-exact preimage script): QC_ITEM_CATEGORIES +
  QC_REASON_CODES → 10 codes binding, docstrings cập nhật. CHECK SQL tự derive.
  Verify: `QC_ITEM_CATEGORY_CHECK_SQL` / `QC_REASON_CODE_CHECK_SQL` chứa đủ 10 codes.
  `git diff --numstat` vs b34d801 = `25 16` — 16 removed = 10 tuple literals cũ
  (z_order/clipping/identity/flicker/audio_timecode × 2 tuples) + 6 dòng docstring
  (nội dung tuple/thay đổi docstring — đúng phạm vi correction cho phép). Không dòng
  cấu trúc nào bị xóa.
- Migration fix mới (AUTHORIZED WRITE-SET EXPANSION, đúng 1 file):
  `migrations/versions/f9a0b1c2d3e4_s11_t02a_qc_reason_codes_fix.py`
  (revision `f9a0b1c2d3e4`, down_revision `e11a02a2026f` — single head đo được).
  SQLite không ALTER CHECK → table rebuild chuẩn: tạo qc_item_new với CHECK literals
  MỚI (byte twin ORM derive từ tuple mới, `_CATEGORY_CHECK`/`_REASON_CODE_CHECK`),
  copy mọi row verbatim, drop cũ, rename, recreate 5 explicit indexes sau rename
  (index names database-global). Fail-closed 2 chiều: upgrade từ chối nếu row dùng
  code cũ không hợp lệ mới; downgrade từ chối nếu row dùng code mới không hợp lệ cũ
  (`_assert_rows_compatible`, named-params expand). PRAGMA integrity/fk_check mọi path.
- 2 test files T02A cập nhật (bounded, byte-exact): mọi tham chiếu enum cũ → 10 codes
  mới ('clipping'→'silhouette_clipping' ×8 trong migration test; 'identity'→
  'identity_drift'); GIỮ NGUYÊN 6 binary C4-F1 + round-trip + downgrade fail-closed;
  thêm: assert đủ 10 codes (gồm edge_halo, audio_missing, av_sync_drift); invalid mới
  (category='clipping', reason_code='z_order', reason_code='audio_timecode' → CHECK
  chặn); migration: REV_FIX chain assert, single head = f9a0b1c2d3e4, old literals GONE
  khỏi DDL, data-preserve upgrade, upgrade/downgrade fail-closed với enum row.

### C1 verification (raw output)
- `python -m alembic heads` → `f9a0b1c2d3e4 (head)` — đúng 1 head (revision fix).
- pytest cả 2 files 1 lệnh (isolation chuẩn) → `37 passed, 14 warnings in 30.09s`
  (basetemp mfc_t02a_c1r2). Chạy lại lần verify cuối: 37 passed.
- Round-trip CLI temp DB (mfc_t02a_c1_cli.db):
  upgrade → (37 tables, 180 indexes, fk_check=[], ok, rev=f9a0b1c2d3e4);
  downgrade a10b11c12d3e → (36, 173, [], ok); re-upgrade → (37, 180, [], ok,
  f9a0b1c2d3e4). NEW-CHECK-PRESENT (z_order_error, edge_halo) = True;
  OLD-CHECK-GONE = True; live insert edge_halo OK, insert z_order → rejected.
- ruff check --select F (models.py, __init__.py, fix migration, 2 tests) →
  `All checks passed!` exit 0.
- python -m py_compile 6 files → PY_COMPILE-OK.
- Concurrency test `test_concurrent_duplicate_natural_key_creates_one_row` ×3 →
  `1 passed` ×3 (2.39s/2.40s/2.40s).

### C1 finding phụ (ngoài scope T02A-C1 — báo manager)
- `tests/test_s11_t02b_qc_api_readonly.py` (T02B-owned) hard-code enum cũ
  ('clipping'/'flicker'/'identity') → 9 tests FAILED sau enum fix
  (test khác 5 pass). Lỗi: `QCItemParamsError: invalid category 'clipping'
  (allowed: (<10 codes mới>))` — repo T02B (app/persistence/qc_items.py) tự
  propagate constants mới đúng, NHƯNG test T02B cần correction riêng cập nhật
  các giá trị enum (KHÔNG thuộc write-set T02A-C1 — task bắt buộc không đụng T02B).
  Manager cần route correction cho T02B.

### C1 commit
- Commit local duy nhất trên codex/s11/t02a-0903w1: `3c0e2041f64b65b68cf6c7b9b77284b09f478701`
  (`fix(s11): T02A-C1 QC reason/category enum -> binding 10 codes (Decision B + D)`),
  6 files (4 M + 1 A + sessions evidence). Working tree sạch sau commit.
  KHÔNG push/merge/rebase/reset/clean/stash. Scope diff vs b34d801 = models.py +
  migration fix mới + 2 test files + docs/pm/sessions/S11-T02A/** (__init__.py không
  đổi — symbols không thay đổi).

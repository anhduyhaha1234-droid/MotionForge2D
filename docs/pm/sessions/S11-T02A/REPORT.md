# S11-T02A — REPORT (W1)

**Task:** S11-T02A — QCItem schema + migration + schema/migration tests (full-sprint S11 T02..T06, isolated-worktree mode)
**Session rule:** NEW SESSION (no manager resume)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s11-t02a-0903w1`
**Branch:** `codex/s11/t02a-0903w1`
**WAVE_BASE / HEAD lúc dispatch:** `7751598214eedb6b72e3783e39a2a408721abe40`
**Status:** **TASK_SUBMITTED** (không tự nhận APPROVED/CLOSED; chờ manager verify độc lập)

---

## 1. Outcome

QCItem tồn tại ở tầng persistence với state machine fail-closed freeze ở DB-level —
đủ contract lane-A §1.1/§1.3 (acceptance binary #1..#5), kèm 2 test files (schema +
migration) xanh trong 1 lệnh với isolation chuẩn, migration mới single head
`e11a02a2026f`, round-trip upgrade/downgrade/upgrade byte-identical + foreign_key_check=0,
downgrade fail-closed có row, mọi enum CHECK derive từ tuple Python duy nhất.

## 2. Commands + real output

### 2.1 Baseline
```
$ git status --porcelain            → (empty) — 0 changes
$ git branch --show-current         → codex/s11/t02a-0903w1
$ git rev-parse HEAD                → 7751598214eedb6b72e3783e39a2a408721abe40
$ env | grep -i MOTIONFORGE         → (no output) — runtime env sạch
$ python -m alembic heads           → a10b11c12d3e (head)      [single, exit 0]
$ sha256sum app/persistence/models.py
  → a3a6f150f26c0481768320df1f9717f404990675371ac9b947d8e1dbd3b545f4   (2976 lines)
```

### 2.2 RED (trước implement)
```
$ python -m pytest tests/test_s11_t02a_qc_schema.py tests/test_s11_t02a_qc_migration.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc_t02a_r1 -q
→ ImportError: cannot import name 'QC_ITEM_CATEGORIES' from 'app.persistence.models'
  2 errors in 0.52s        [fail đúng lý do: behavior mới chưa tồn tại]
```

### 2.3 GREEN (sau implement — 1 lệnh, isolation chuẩn)
```
$ unset MOTIONFORGE_DATABASE_URL; python -m pytest tests/test_s11_t02a_qc_schema.py \
    tests/test_s11_t02a_qc_migration.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc_t02a_r10 -q
→ 31 passed, 8 warnings in 24.98s
```
(8 warnings = SAWarning reflection expression-based index legacy `uq_*_workspace_role_name`
/ `uq_character_active_workspace_code` — pre-existing, không phải file của task.)

Test inventory (31 tests):
- `tests/test_s11_t02a_qc_schema.py` (25): C4-F1 #1 FK segment_row_id → immutable occurrence row
  (kể cả DELETE RESTRICT); #2 hai lineage versions cùng logical_id hợp lệ + QCItem neo đúng
  segment_row_id; #3 partial segment pair (2 chiều) bị CHECK chặn + both-NULL hợp lệ;
  #4 duplicate sequential + concurrent (threads, barrier) không tạo 2 rows; #5 PRAGMA
  foreign_key_check=[] + integrity ok; #6 NULL mọi thành phần natural key bị NOT NULL chặn
  + unique index non-partial (PRAGMA index_list partial=0) đủ 7 cột đúng thứ tự; blocker→
  dismissed bị chặn DB-level; CHECK chặn status/severity/category/reason_code/confidence_source
  ngoài enum + confidence range; derived-from-tuple byte-identical; field contract column/FK.
- `tests/test_s11_t02a_qc_migration.py` (6): revision chain (e11a02a2026f ← a10b11c12d3e);
  single head; round-trip upgrade→downgrade→upgrade byte-identical (schema_sig dict equality)
  + fk_check [] + integrity ok; downgrade fail-closed có row (RuntimeError "refusing to
  downgrade", row nguyên vẹn); CHECK literals byte-twin ORM + live trên migrated DB
  (bogus status + blocker/dismissed → IntegrityError với parent rows đã seed, không phải FK);
  FK segment_row_id enforced trên migrated DB.

### 2.4 Gates
```
$ python -m alembic heads            → e11a02a2026f (head)      [đúng 1 head = revision vừa tạo]
$ python -m py_compile <5 files>     → PY_COMPILE-OK
$ ruff check --select F <5 files>    → All checks passed!       [exit 0]
$ git diff --numstat app/persistence/models.py      → 240  0   [removed = 0]
$ git diff --numstat app/persistence/__init__.py    →  27  0   [removed = 0]
```

### 2.5 Round-trip CLI trên temp DB (C:/Users/Admin/AppData/Local/Temp/mfc_t02a_cli.db)
```
upgrade head        → (37 tables, 180 indexes, foreign_key_check=[], integrity=ok, rev=e11a02a2026f)
downgrade a10b11c12d3e → (36, 173, [], ok, rev=a10b11c12d3e)   [qc_item dropped]
upgrade head        → (37, 180, [], ok, rev=e11a02a2026f)      [byte-identical signature]
qc_item present: True
```

### 2.6 Concurrency stability
```
test_concurrent_duplicate_natural_key_creates_one_row → 1 passed ×3 (2.48s/2.49s/2.36s)
```

## 3. Files changed (chỉ allowlist + sessions evidence)

| Path | Type | Delta |
|---|---|---|
| `app/persistence/models.py` | M (ADDITIVE-ONLY) | +240 / -0; SHA before `a3a6f150f26c0481768320df1f9717f404990675371ac9b947d8e1dbd3b545f4` → after `9dafe988b41bc0454ae5e61634d0fa9ea2784a572d393a48b04220d45b9c26d9`; 2976 → 3216 lines |
| `app/persistence/__init__.py` | M (chỉ export mới) | +27 / -0 |
| `migrations/versions/e11a02a2026f_s11_t02a_qc_item.py` | NEW | revision `e11a02a2026f`, down_revision `a10b11c12d3e` (đo được) |
| `tests/test_s11_t02a_qc_schema.py` | NEW | 25 tests |
| `tests/test_s11_t02a_qc_migration.py` | NEW | 6 tests |
| `docs/pm/sessions/S11-T02A/LOG.md`, `REPORT.md` | NEW | evidence |

**Forbidden scope không đụng:** app/api/**, app/services/**, frontend/**, docs/**, data/fixtures,
tests ngoài allowlist, migrations khác, MAIN, s08 archive, s11-integration.
KHÔNG push/merge/rebase/reset/clean/stash/force.

## 4. Model contract (QCItem, table `qc_item`)

- Natural-key UNIQUE 7 cột `uq_qc_item_natural_key`: (workspace_id, project_id, video_item_id,
  layer_ref_type, layer_ref_id, reason_code, evidence_window_key) — mọi cột NOT NULL,
  non-partial (test chứng minh SQLite NULL semantics không phá uniqueness).
- `segment_row_id` String(36) NULL, FK THẬT → `occurrence_segment.id` ON DELETE RESTRICT.
- `segment_logical_id` String(64) NULL, scoped lineage VALUE, KHÔNG phải FK.
- CHECK `ck_qc_item_segment_pair_null`: cả hai NULL hoặc cả hai non-NULL.
- `layer_ref_type`/`layer_ref_id` NOT NULL (video-level issue: layer_ref_type='video_item',
  layer_ref_id=video_item_id).
- `evidence_window_key` String(64) NOT NULL — canonical stable key/hash materialize riêng
  (cơ chế duy nhất enforce uniqueness; evidence_json KHÔNG phải cơ chế đó).
- `evidence_json` Text NOT NULL schema-versioned/content-derived.
- `detector`/`detector_revision`/`checkpoint_ref` NOT NULL; `confidence` Float CHECK 0..1;
  `confidence_source` CHECK derive từ OCCURRENCE_CONFIDENCE_SOURCES; TimestampMixin
  (created_at/updated_at/revision).
- Enum CHECKs derive từ tuple Python duy nhất (pattern CONTACT_KIND_CHECK_SQL):
  status ∈ {open, acknowledged, resolved, dismissed} = QC_ITEM_STATUSES;
  severity ∈ {blocker, warning, info} = QC_ITEM_SEVERITIES;
  category/reason_code ∈ 8 lane-A reasons = QC_ITEM_CATEGORIES / QC_REASON_CODES.
- lane-A §1.3 rule 2: `ck_qc_item_blocker_not_dismissed` = NOT (severity='blocker' AND
  status='dismissed') — DB-level, test binary chặn insert.

## 5. Acceptance criteria check (binary)

1. ✅ `alembic heads` runtime = đúng 1 head `e11a02a2026f`; round-trip OK temp DB; foreign_key_check=0.
2. ✅ `git diff models.py removed=0` (240/0); mọi enum QC derive SQL CHECK từ tuple Python duy nhất.
3. ✅ status/severity đúng enum; insert blocker→dismissed bị CHECK DB chặn (2 test).
4. ✅ Fields đủ lane-A §1.1 contract (xem §4) — test_qcitem_column_contract + migration parity.
5. ✅ 2 test files pass 1 lệnh `-p no:cacheprovider`, basetemp Windows-native ngắn, env strip
   MOTIONFORGE_DATABASE_URL (31 passed).
6. ✅ Round-trip byte-identical; downgrade fail-closed có row; CHECK chặn enum ngoài;
   blocker+dismissed DB-level.

## 6. Findings / notes

- `create_all` (ORM DDL) không có server_default cho project.description/status,
  video_item.status — schema tests seed explicit (không phải bug của task).
- SQLite lưu table-level UNIQUE constraint thành auto-index (sqlite_autoindex_*),
  sqlite_master.sql = NULL → test non-partial dùng `PRAGMA index_list` (origin='u', partial=0).
- patch tool fuzzy-match làm hỏng indent __all__ models.py 2 lần → xử lý bằng byte-exact
  replace script có preimage assertion (bounded patch protocol giữ nguyên; SHA cuối verify).
- Test không chạy: không có — toàn bộ 31 tests đã chạy và pass. Không skip/ignore/xfail.

## 7. Evidence paths

- `docs/pm/sessions/S11-T02A/LOG.md` (baseline, plan, chronological log)
- `docs/pm/sessions/S11-T02A/REPORT.md` (file này)
- Raw output của mọi lệnh trong §2 là output thật từ terminal (không tóm tắt suy diễn).

---
**Status: TASK_SUBMITTED** — commit local trên `codex/s11/t02a-0903w1` (allowlist + evidence).
KO push, KO merge. Chờ Manager verify độc lập.
# S11-T02A — REPORT — CORRECTION ROUND C1 (finding T02A-C1 [P1])

**Task:** S11-T02A — QCItem schema + migration + schema/migration tests (W1) — CORRECTION C1
**Session:** resume exact owner (same T02A session), branch `codex/s11/t02a-0903w1`
**WAVE_BASE (C1):** `b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9` (canonical fast-forward; worktree sạch lúc bắt đầu)
**Status:** **TASK_SUBMITTED** (CORRECTION_C1_SUBMITTED) — chờ Manager verify độc lập

---

## 1. Finding được sửa (T02A-C1 [P1 — contract violation])

`QC_REASON_CODES` / `QC_ITEM_CATEGORIES` cũ (8 codes) → **10 codes binding**:

```
trajectory_drift, cut_drift, contact_break, z_order_error, silhouette_clipping,
identity_drift, edge_halo, temporal_flicker, audio_missing, av_sync_drift
```
- 8 overlay codes (Decision B, overlay §S11 L370-371): renames `z_order`→`z_order_error`,
  `clipping`→`silhouette_clipping`, `identity`→`identity_drift`, `flicker`→`temporal_flicker`;
  thêm `edge_halo`; loại `audio_timecode` khỏi overlay set.
- + 2 audio codes (Decision D, T03E): `audio_missing`, `av_sync_drift`.
- Cả hai tuple giữ 1:1 (`QC_REASON_CODES == QC_ITEM_CATEGORIES`); mọi CHECK SQL trong
  models.py derive tự động từ tuple (pattern CONTACT_KIND_CHECK_SQL) — không sửa cấu trúc khác.

## 2. Thay đổi (chỉ allowlist + expansion authorized)

| Path | Type | Ghi chú |
|---|---|---|
| `app/persistence/models.py` | M (bounded patch, byte-exact preimage) | numsat vs b34d801 = **25/16** — 16 removed = 10 tuple literals cũ + 6 docstring lines (đúng phạm vi "cho phép thay đổi nội dung tuple"); zero dòng cấu trúc bị xóa |
| `migrations/versions/f9a0b1c2d3e4_s11_t02a_qc_reason_codes_fix.py` | NEW (expansion authorized, đúng 1 file) | revision `f9a0b1c2d3e4`, down_revision `e11a02a2026f` (single head đo được). Table rebuild (SQLite không ALTER CHECK): qc_item_new + CHECK mới (byte twin ORM) → copy → drop → rename → recreate indexes. Fail-closed 2 chiều `_assert_rows_compatible`. PRAGMA integrity/fk_check mọi path |
| `tests/test_s11_t02a_qc_schema.py` | M | enum cũ → 10 codes mới; giữ 6 binary C4-F1; thêm assert 10 codes (edge_halo/audio_missing/av_sync_drift); invalid values mới (clipping/z_order/audio_timecode bị CHECK chặn); derived-tuple test 10 codes |
| `tests/test_s11_t02a_qc_migration.py` | M | REV_FIX chain assert; single head = f9a0b1c2d3e4; old literals GONE khỏi DDL; thêm data-preserve upgrade + upgrade/downgrade fail-closed có row enum (3 test mới); 8 × 'clipping' → 'silhouette_clipping' |
| `app/persistence/__init__.py` | KHÔNG đổi | symbols không thay đổi (không cần) |
| `docs/pm/sessions/S11-T02A/LOG.md`, `REPORT.md` | M | append C1 |

**Forbidden không đụng:** detector modules, orchestrator, runner/registry (T03A freeze),
qc_items repo (T02B), frontend, migrations khác, MAIN. KHÔNG push/merge/rebase/reset/clean/stash.

## 3. Commands + real output (verify bắt buộc)

### 3.1 alembic heads + round-trip (temp DB `mfc_t02a_c1_cli.db`)
```
$ python -m alembic heads
→ f9a0b1c2d3e4 (head)                       [đúng 1 head = revision fix mới]

upgrade head        → (37 tables, 180 indexes, foreign_key_check=[], integrity=ok, rev=f9a0b1c2d3e4)
downgrade a10b11c12d3e → (36, 173, [], ok, rev=a10b11c12d3e)     [chain 2 downgrades; qc_item dropped]
upgrade head        → (37, 180, [], ok, rev=f9a0b1c2d3e4)        [byte-identical signature]
NEW-CHECK-PRESENT (z_order_error, edge_halo) = True ; OLD-CHECK-GONE = True
Live insert: edge_halo → OK ; z_order → REJECTED (CHECK live trên migrated DB)
FK-CHECK-FINAL = []
```

### 3.2 Cả 2 test files — 1 lệnh, isolation chuẩn
```
$ unset MOTIONFORGE_DATABASE_URL; python -m pytest tests/test_s11_t02a_qc_schema.py \
    tests/test_s11_t02a_qc_migration.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc_t02a_c1r2 -q
→ 37 passed, 14 warnings in 30.09s
```
RED trước khi sửa test (sau khi đổi models): 2 failed đúng lý do (downgrade fail-closed giờ
chạy fix migration trước — message "refusing to proceed"; preserve seed dùng code cũ tại
revision cũ) → đã sửa bounded: match pattern "refusing to (downgrade|proceed)"; seed
'trajectory_drift' (valid cả 2 enum). GREEN = 37 passed.

### 3.3 Gates
```
$ ruff check --select F (5 files)  → All checks passed!   [exit 0]
$ python -m py_compile (6 files)   → PY_COMPILE-OK
$ test_concurrent_duplicate_natural_key_creates_one_row ×3 → 1 passed ×3 (2.39/2.40/2.40s)
$ git diff --numstat b34d801 -- app/persistence/models.py → 25  16
```
16 removed lines = chỉ tuple literals cũ (10 dòng) + docstrings (6 dòng) — xác nhận bằng
`git diff | grep "^-"` (không có dòng cấu trúc/khác).

### 3.4 Scope diff vs b34d801
```
M  app/persistence/models.py
M  tests/test_s11_t02a_qc_schema.py
M  tests/test_s11_t02a_qc_migration.py
?? migrations/versions/f9a0b1c2d3e4_s11_t02a_qc_reason_codes_fix.py
+ docs/pm/sessions/S11-T02A/** (LOG/REPORT append C1)
```
(porcelain check: không path nào ngoài allowlist.)

## 4. Finding phụ — T02B dependency (báo Manager, KHÔNG sửa)

Sau enum fix, `tests/test_s11_t02b_qc_api_readonly.py` (T02B-owned) fail **9 tests**
(5 pass). Lỗi gốc (raw output):
```
app.persistence.qc_items.QCItemParamsError: invalid category 'clipping' (allowed:
('trajectory_drift','cut_drift','contact_break','z_order_error','silhouette_clipping',
'identity_drift','edge_halo','temporal_flicker','audio_missing','av_sync_drift'))
```
Repo T02B (`app/persistence/qc_items.py`) dùng constants mới — tự propagate đúng.
Chỉ test T02B hard-code `'clipping'/'flicker'/'identity'` (L79-80, L160, L182, L189,
L208, L265-266). **Manager cần route correction riêng cho T02B** (update enum values trong
test file) — ngoài write-set T02A-C1 (task cấm đụng T02B).

## 5. Acceptance (correction) — binary check

1. ✅ `alembic heads` = 1 head `f9a0b1c2d3e4`; round-trip upgrade/downgrade/upgrade temp DB + foreign_key_check=0.
2. ✅ Cả 2 test files pass 1 lệnh `-p no:cacheprovider`, basetemp Windows-native ngắn, env strip MOTIONFORGE_DATABASE_URL (37 passed).
3. ✅ `ruff check --select F` 5 files; py_compile.
4. ✅ models.py diff removed=0 ngoài tuple literal + docstring (16 dòng — được phép); giữ nguyên mọi CHECK khác.
5. ✅ Scope diff vs b34d801: CHỈ models.py + migration fix mới + 2 test files + sessions evidence (__init__.py không cần).
6. ✅ 10 codes hiện diện (assert trong test: edge_halo, audio_missing, av_sync_drift có mặt); CHECK chặn invalid mới (clipping/z_order/audio_timecode).

## 6. Evidence paths

- `docs/pm/sessions/S11-T02A/LOG.md` (baseline W1 + C1 baseline, thực thi, verify, finding phụ)
- `docs/pm/sessions/S11-T02A/REPORT.md` (file này)
- Mọi số liệu §3 là output thật từ terminal (không tóm tắt suy diễn).

---
**Status: TASK_SUBMITTED / CORRECTION_C1_SUBMITTED** — commit local duy nhất
`3c0e2041f64b65b68cf6c7b9b77284b09f478701` trên `codex/s11/t02a-0903w1`
(6 files: 4 M + 1 A + sessions evidence). KO push, KO merge. Chờ Manager verify.
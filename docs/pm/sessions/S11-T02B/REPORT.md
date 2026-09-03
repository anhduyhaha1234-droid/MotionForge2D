# S11-T02B — REPORT (W2)

**Task:** S11-T02B — QCItem repository + internal idempotent creation/recheck lifecycle + read-only API (full-sprint S11 T02..T06, isolated-worktree mode)
**Session rule:** NEW SESSION (no manager resume, no other task session)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s11-t02b-0903w2`
**Branch:** `codex/s11/t02b-0903w2`
**WAVE_BASE / HEAD lúc dispatch:** `6861177149e1d12653f045ab2a44933b8d0f6d57`
**Status:** **TASK_SUBMITTED** (không tự nhận APPROVED/CLOSED; chờ Manager verify độc lập)

---

## 1. Outcome

Repository nội bộ tạo/upsert/recheck QCItem idempotent qua 7-cột natural key (DB-level
atomic `INSERT .. ON CONFLICT DO NOTHING` — không check-then-insert), lifecycle terminal
(`resolved`/`dismissed`) chỉ đạt qua recheck evidence mới trong payload, HTTP surface
READ-ONLY (list/detail/filter) theo lane-C G1/G2 shape. Repository trả frozen dataclass
DTO; ORM không vượt API layer. 2 test files xanh 1 lệnh isolation chuẩn C1/C3.

## 2. Commands + real output

### 2.1 Baseline
```
$ git status --porcelain            → (empty) — 0 changes
$ git branch --show-current         → codex/s11/t02b-0903w2
$ git rev-parse HEAD                → 6861177149e1d12653f045ab2a44933b8d0f6d57 (= WAVE_BASE)
$ env | grep -i MOTIONFORGE         → (no output) — runtime env sạch
$ sha256sum app/api/app.py          → 7c727e4c4b5a83a2ff72fb38dd8685e461b488dc73f10dacff2f07b78280442b
$ sha256sum app/persistence/models.py → f1df093927737cd2341de503abc1af5c58f139d4ff73978b175164d4ace93e6b (protected)
$ python -m alembic heads           → e11a02a2026f (head)      [single, exit 0]
```

### 2.2 RED (trước implement)
```
$ python -m pytest tests/test_s11_t02b_qc_repository_lifecycle.py tests/test_s11_t02b_qc_api_readonly.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc_t02b_r1 -q
→ ModuleNotFoundError: No module named 'app.persistence.qc_items'
  2 errors in 0.77s        [fail đúng lý do: behavior mới chưa tồn tại]
```

### 2.3 GREEN (sau implement — 1 lệnh, isolation chuẩn)
```
$ unset MOTIONFORGE_DATABASE_URL; python -m pytest tests/test_s11_t02b_qc_repository_lifecycle.py \
    tests/test_s11_t02b_qc_api_readonly.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc_t02b_r6 -q
→ 40 passed, 23 warnings in 34.89s
```
(×3 fresh roots: r4 34.65s / r5 34.62s / r6 34.89s — EXIT 0 mọi lần. 23 warnings =
SAWarning reflection legacy index + StarletteDeprecationWarning — pre-existing, không phải
file của task.)

Test inventory (40 tests):
- `tests/test_s11_t02b_qc_repository_lifecycle.py` (17): create trả frozen DTO + persist;
  create trùng natural-key reuse (không duplicate, không overwrite evidence); ewk khác →
  item khác; concurrent race (2 threads, barrier, engine riêng) → deterministic reuse
  1 row (C4-F1); acknowledge non-terminal (không evidence); resolved/dismissed/recheck-fail
  KHÔNG evidence → QCItemEvidenceRequiredError (zero mutation); resolve/dismiss với evidence
  mới → terminal + evidence lưu + revision bump; recheck còn hiện diện → open; terminal là
  terminal (mọi transition bị chặn); no-op transition bị chặn; blocker không dismiss được;
  get không tồn tại / workspace khác → NotFound (fail-closed, zero leak); list filter
  status/severity/category/video_item_id đúng subset + workspace scope + pagination
  deterministic (created_at DESC, id DESC); filter giá trị sai → QCItemParamsError;
  create payload sai (severity/category/reason_code/confidence/confidence_source/partial
  segment pair) → QCItemParamsError zero mutation; evidence None → QCItemParamsError.
- `tests/test_s11_t02b_qc_api_readonly.py` (12): binary grep router zero
  POST/PUT/PATCH/DELETE + ≥2 GET; app.py include_router(qc_items) đúng 1 lần; list empty;
  list seed QUA REPOSITORY (không POST — Decision A) trả đúng + DTO deterministic +
  evidence JSON; list filter (kể cả combined + invalid → 422); pagination total/has_more;
  detail đủ fields + evidence; detail unknown id 404; detail foreign workspace 404 (không
  leak); detail non-uuid 404 (path converter fail-closed); POST/PUT/PATCH/DELETE trên
  qc-item surface → 404/405 (mutation verb không bao giờ chạy); OpenAPI removed=0 +
  qc-items paths chỉ GET.

### 2.4 Gates
```
$ grep -n "@router.\(post\|put\|patch\|delete\)" app/api/routes/qc_items.py → exit 1 (0 match)
$ grep -c "@router.get" app/api/routes/qc_items.py               → 4
$ grep -n "recheck|acknowledge|transition|create|update|delete" app/api/routes/qc_items.py → exit 1 (0 match)
$ python -m py_compile <6 files>                                  → PY_COMPILE-OK
$ ruff check --select F <6 files>                                 → All checks passed!   [exit 0]
$ python -m alembic heads                                         → e11a02a2026f (head) [single]
$ git diff --numstat app/api/app.py                               → 3  0   [removed = 0]
```

### 2.5 OpenAPI materialize trước/sau (removed=0)
```
before (263 paths, 0 qc-item)  →  docs/pm/sessions/S11-T02B/evidence/openapi_paths_before.txt
after  (267 paths)             →  docs/pm/sessions/S11-T02B/evidence/openapi_paths_after.txt
removed = 0 []
qc-item paths + methods:
  /api/v2/projects/{project_id}/qc-items/  ['get']
  /api/v2/projects/{project_id}/qc-items   ['get']
  /api/v2/qc-items/{item_id}/              ['get']
  /api/v2/qc-items/{item_id}               ['get']
```

### 2.6 Concurrency stability
```
test_concurrent_create_same_natural_key_deterministic_reuse → 1 passed in 2.43s (riêng)
```

## 3. Files changed (chỉ allowlist + sessions evidence)

| Path | Type | Delta |
|---|---|---|
| `app/persistence/qc_items.py` | NEW (owner duy nhất toàn S11) | repository + lifecycle service; create idempotent / get / list / acknowledge / recheck_resolved / recheck_dismissed / recheck_failed |
| `app/schemas/qc_items.py` | NEW | frozen dataclass DTO `QCItemData` / `QCItemListResponse` |
| `app/api/routes/qc_items.py` | NEW | router READ-ONLY, 2 GET routes (list G1 + detail G2) |
| `app/api/app.py` | M (additive) | +3 / -0 — 1 dòng import `qc_items` + comment + 1 dòng `include_router(qc_items.router)` |
| `tests/test_s11_t02b_qc_repository_lifecycle.py` | NEW | 17 tests |
| `tests/test_s11_t02b_qc_api_readonly.py` | NEW | 12 tests |
| `docs/pm/sessions/S11-T02B/**` | NEW | LOG.md + REPORT.md + evidence openapi before/after |

**Forbidden scope không đụng:** models.py (hash không đổi f1df0939…), migrations/** (heads
vẫn e11a02a2026f), app/services/**, frontend/**, mọi router khác, MAIN, s08 archive,
s11-integration canonical worktree. KHÔNG push/merge/rebase/reset/clean/stash/force.

## 4. Repository contract (app.persistence.qc_items)

- `create(...)` — atomic `INSERT .. ON CONFLICT DO NOTHING` trên 7 cột natural key
  (workspace_id, project_id, video_item_id, layer_ref_type, layer_ref_id, reason_code,
  evidence_window_key) rồi consistent read; duplicate/concurrent → REUSE row cũ (cùng id,
  zero mutation). Validate fail-closed trước insert (enum/confidence/segment pair/evidence
  non-empty). Luôn tạo trạng thái `open`.
- `get(item_id, workspace_id)` — 404-semantics: unknown hoặc workspace khác → `QCItemNotFoundError`
  (không leak).
- `list(workspace_id, project_id?, status?, severity?, category?, video_item_id?, limit, offset)`
  — exact filters (giá trị sai → 422), ordering deterministic created_at DESC, id DESC,
  trả (records, total).
- Lifecycle (chỉ qua repository — không có endpoint HTTP mutation):
  - `acknowledge` — open→acknowledged (non-terminal, không cần evidence).
  - `recheck_resolved` / `recheck_dismissed` — TERMINAL: bắt buộc `evidence` non-empty
    (fresh recheck evidence; thiếu → `QCItemEvidenceRequiredError`, zero mutation).
  - `recheck_failed` — acknowledged→open khi recheck còn hiện diện (bắt buộc evidence).
  - Terminal states terminal (mọi outgoing transition bị chặn); no-op bị chặn;
    revision bump trên mỗi transition; flush để DB CHECK (backstop blocker→dismissed)
    fire trước commit.
  - `severity=blocker` → `recheck_dismissed` luôn bị chặn (`QCItemBlockedDismissalError`)
    trước cả DB CHECK ck_qc_item_blocker_not_dismissed (T02A).
- DTO boundary: mọi method trả `QCItemRecord` frozen dataclass; ORM `QCItem` không bao giờ
  rời module. `_map_row` parse evidence_json fail-closed (corrupt → `QCItemDataError`).

## 5. Acceptance criteria check (binary)

1. ✅ HTTP surface CHỈ GET — grep router 0 POST/PUT/PATCH/DELETE QCItem; router không import
   lifecycle method; OpenAPI 4 qc-item paths đều `['get']`; mutation verbs → 404/405.
2. ✅ Creation/upsert chỉ qua repository/service internal — chính 2 test mới seed QUA
   `QCItemRepository.create` (không POST); router không có create/upsert code.
3. ✅ Terminal transition yêu cầu recheck evidence mới trong payload — resolved/dismissed
   thiếu evidence → `QCItemEvidenceRequiredError` (test binary); evidence mới → terminal.
4. ✅ Repository trả frozen DTO — `QCItemRecord`/`QCItemData` frozen dataclass; test
   FrozenInstanceError; ORM không vượt API layer.
5. ✅ Focused suite xanh 1 lệnh isolation chuẩn C1/C3 — 40 passed ×3 fresh roots
   (basetemp Windows-native ngắn mfc_t02b_r*, `-p no:cacheprovider`, env strip).
6. ✅ C4-F1 race: concurrent insert cùng natural key → deterministic reuse 1 row, atomic
   upsert (không check-then-insert) — test riêng 3 lần + trong suite.
7. ✅ blocker không dismiss-tính-vào-readiness — repository chặn dismiss blocker + DB CHECK
   backstop (T02A).
8. ✅ ownership workspace mismatch fail-closed — repo get/list theo workspace; API detail
   foreign → 404.
9. ✅ OpenAPI removed=0 — materialize trước/sau (263→267), removed=[].

## 6. Findings / notes

- FastAPI trả 405 cho mutation verb khi path match route GET có id; trả 404 khi path base
  không có route nào — cả hai đều chứng minh zero mutation handler (test assert 404/405).
- Non-UUID id không match `{item_id:uuid}` converter → 404 fail-closed (không 422) — hành
  vi Router boundary, không phải bug.
- `patch` tool fuzzy-match phá indent import block app.py 2 lần → xử lý bằng byte-exact
  replace script CRLF-aware có preimage assertion; final `git diff --numstat` = 3 0.
- `sqlite_insert(..).on_conflict_do_nothing(index_elements=...)` trên SQLite 3.x:
  unique index arbitration ở DB level — đúng C4-F1 "KHÔNG check-then-insert không khóa".
- Test không chạy: không có — toàn bộ 40 tests đã chạy và pass, 3 lần. Không skip/ignore/xfail.

## 7. Evidence paths

- `docs/pm/sessions/S11-T02B/LOG.md` (baseline, plan, chronological log)
- `docs/pm/sessions/S11-T02B/REPORT.md` (file này)
- `docs/pm/sessions/S11-T02B/evidence/openapi_paths_before.txt` (263 paths)
- `docs/pm/sessions/S11-T02B/evidence/openapi_paths_after.txt` (267 paths)
- Raw output của mọi lệnh trong §2 là output thật từ terminal (không tóm tắt suy diễn).

---
**Status: TASK_SUBMITTED** — commit local `9c9878a51bf5da7b913593478f04fccc5c798e2a` trên
`codex/s11/t02b-0903w2` (allowlist + evidence; 10 files: 1 M + 9 A). KO push, KO merge.
Chờ Manager verify độc lập.
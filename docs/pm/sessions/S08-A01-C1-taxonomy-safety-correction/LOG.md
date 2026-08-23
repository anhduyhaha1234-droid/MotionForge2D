# S08-A01-C1 — LOG (append-only)

## Baseline (written by Hermes manager before writer launch — 2026-08-19T17:2x+07:00)

### Restoration / preflight (manager, read-only)

- Worktree guard verified: `pwd`/toplevel = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`; `git status --short` = **180 entries** (dirty baseline INTENTIONAL — never reset/clean/restore/checkout/stash/commit/push/merge).
- QA ports 3012/8888/8000/3000/5173/8027/8002/3010/8025/8026/3013/8014 — all FREE (NO_LISTENERS).
- No writer process active before launch (no `hermes chat --query`).
- S08-A01 session `20260819_143912_9450e9` is CLOSED — NOT reusable.
- Codex decision: S08-A01 = CHANGES_REQUESTED — packet A01-C1 created by manager.

### Protected baseline (manager, read-only)

- MAIN `channels.json` SHA-256: `DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555`.
- MAIN `data/motionforge.db`: 311296 B SHA-256 `67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6`.
- SAM2.1 checkpoint: 898083611 B SHA-256 `2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318`.

### Launch plan

- Task: S08-A01-C1 — Taxonomy Safety Correction (focused fixes F1–F4 + process correction).
- Session: NEW (filled in REPORT). Model `ocg/deepseek-v4-flash`, reasoning max.
- (Writer appends below from here.)

---

<!-- Writer appends all subsequent entries below this line. Append-only. -->
---

## SCOPE DECISION (PM/user, official — 2026-08-19T19:2x+07:00)

CHÍNH THỨC: PM approve mở rộng allowlist A01-C1 cho ĐÚNG MỘT file:

    app/persistence/object_correction.py

Mục đích duy nhất — F2 mixed-kind merge PREVIEW validation:
- Preview phải reject khi source.kind != target.kind.
- PHẢI read-only và zero durable mutation.
- Hành vi phải thống nhất với apply_merge backend; ưu tiên dùng chung
  invariant/helper, KHÔNG tạo policy thứ hai dễ drift.
- Thêm focused tests chứng minh preview trả conflict và DB không thay đổi.

KHÔNG mở rộng sang file khác từ quyết định này.
KHÔNG sửa unrelated correction/recompute behavior.
Writer hiện tại TIẾP TỤC sau khi quyết định scope được ghi vào LOG/REPORT.

---

## Writer session baseline — 2026-08-19T20:0x+07:00 (UTC 13:0xZ)

- Hard worktree guard re-verified BEFORE any write:
  - `pwd` = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` ✓
  - `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` ✓
  - `git branch --show-current` = `codex/s08-integration` ✓; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` ✓
  - `git status --short` count = **181** at writer first check (manager baseline 180 + C1 packet dir) — INTENTIONAL dirty baseline; never reset/checkout/restore/clean/stash; after implementation 187 entries (C1 files inside the packet add, consistent with the dirty baseline). NO stray files outside scope.
- Environment: `MOTIONFORGE_DATABASE_URL` UNSET and verified at start and again at finish ✓; `MOTIONFORGE_ROOT`/`MOTIONFORGE_EXTRACTION_PROVIDER` UNSET.
- Full required reading completed (SESSION_PROTOCOL, A01 TASK/REPORT/LOG, migration f7a8b9c0d1e2, grouping persistence/service/routes, correction persistence/routes/schemas/service, intelligence persistence/routes/schemas, models.py, frontend gallery + api.ts + AGENTS.md + e2e helpers/project configs, focused tests).
- **PM scope decision honored**: `app/persistence/object_correction.py` is in scope (approved above) for the F2 merge-preview kind-equality check; no other file was added to scope; no unrelated correction/recompute behavior touched.

## Implementation (per finding, with run timestamps)

### F1 — safe fail-closed migration downgrade (migration f7a8b9c0d1e2)
- `_edit_kind_check` now asserts the target CHECK literal appears **EXACTLY ONCE** in `sqlite_master` table DDL before replacing (ambiguous multi-occurrence → raise, never a blind replace).
- New `_assert_db_integrity(conn, phase)` runs `PRAGMA integrity_check` (expect `ok`) and `PRAGMA foreign_key_check` (expect 0 rows) after EVERY mutation decision path.
- `downgrade()` now calls `_assert_no_nonlegacy_kinds(conn)` BEFORE any schema/data mutation: if ANY `object_role` row has a kind outside `('character','prop','other')`, the downgrade raises → alembic exits non-zero, revision stays `f7a8b9c0d1e2`, DDL/rows/indexes/FKs byte-identical, a new kind is NEVER silently reclassified to `other`.
- Tests `tests/test_s08_a01_c1_migration_safety.py` (new): (a) legacy 3-kind round-trip upgrade→downgrade→upgrade byte-identical + integrity ok; (b) DB with new-kind rows REFUSED atomically (revision stays 7-kind, DDL unchanged, 7 rows preserved, integrity ok); (c) single-new-kind-row edge refusal + FK check clean. `python -m pytest ... -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a01c1-f1` -> **3 passed**.

### F2 — kind-safe manual merge
- `apply_merge` (`app/persistence/object_grouping.py`) now requires EVERY `source.kind == target.kind` (message via new shared helper `merge_kind_conflict_message`), raised BEFORE any mutation → route maps to 409. Also keeps A01 removal-only guarantee.
- **Approved file** `app/persistence/object_correction.py`: `compute_impact` for `correction_type == "merge"` reuses `merge_kind_conflict_message` and raises `CorrectionConflictError` (→ 409) so the correction/merge PREVIEW reports the conflict with ZERO durable mutation (read-only; no pending correction row created). Confirmed the helper is the ONE invariant shared by execute+preview (no second policy).
- Frontend (`ObjectGalleryPanel.tsx` + `RoleCard.tsx`): only same-kind roles selectable as merge sources; changing target clears incompatible source selections; disabled checkbox + Vietnamese hint for mismatched kind.
- Tests `tests/test_s08_a01_c1_merge_kind_safety.py` (new): repo + API both directions → 409; **corrections/preview** both directions → 409 + zero mutation (no ObjectCorrection row; roles/revisions/statuses/occurrences/operations/suggestions unchanged); same-kind still applies; removal-only still refused. With correction api suite re-run: **20 passed**.

### F3 — canonical authority (no duplicated constants/regex)
- `app/persistence/models.py`: added `OBJECT_KIND_CHECK_SQL` (ORM `ck_object_role_kind` literal) and `OBJECT_KIND_PATTERN` (validation regex) BOTH derived from `OBJECT_KINDS` in declaration order; `ObjectRole.ck_object_role_kind` now uses `OBJECT_KIND_CHECK_SQL`; exported in `__all__`.
- Schemas derive from the canonical pattern: `app/schemas/object_intelligence.py` (RoleCreateRequest.kind, RoleUpdateRequest.kind) and `app/schemas/object_correction.py` (role_kind) now use `OBJECT_KIND_PATTERN` — no hardcoded regex literal anywhere.
- `app/services/object_grouping.py`: `REMOVAL_ONLY_KINDS_DEFAULT` removed (second authority) — `removal_only_kinds` is now a REQUIRED keyword arg; production callers already pass canonical `REMOVAL_ONLY_KINDS`; test call sites updated.
- Tests: `test_s08_a01_role_taxonomy.py` anchor now proves `OBJECT_KIND_CHECK_SQL == migration._NEW_CHECK` and `OBJECT_KIND_PATTERN` exact; grouping + correction suites green. **18 + 73 passed** (focused).

### F4 — source_overlay reclassification via correction flow
- Backend reclassify path proven through the EXISTING correction flow (candidate_edit with role_kind → update_role validate) — no second authority, kind change/CAS preserved.
- Frontend: dedicated **“Sửa phân loại (sai loại?)”** action on source_overlay removal-only card (RoleCard `onReclassify`) → reuses the candidate-edit correction dialog (preview + confirm + CAS). source_overlay still has NO merge/confirm/split/edit/reassign surface.
- Tests `tests/test_s08_a01_c1_reclassify_source_overlay.py` (new): reclassify via preview→create→confirm changes kind, keeps stable id/revision bump, no recompute needed; stale-revision CAS → 409; source_overlay guarantees intact. **3 passed**.
- Playwright: new `frontend/playwright.s08a01c1.config.ts`, `frontend/e2e/s08-a01-c1.spec.ts` (desktop), `frontend/e2e/s08-a01-c1-mobile.spec.ts` (390px). **5 passed** (desktop 4 + mobile 1) on the isolated QA stack (port 8028 via `output/s08-a01-c1/20260819-s08a01c1-r1/run-qa-backend-s08a01c1.sh`, frontend 3013, deterministic provider); 4 screenshots; `.last-run.json` status=passed.

## Validation (fresh isolated roots; -p no:cacheprovider; shallow basetemps; MOTIONFORGE_DATABASE_URL unset)

1. F1 migration safety: `python -m pytest tests/test_s08_a01_c1_migration_safety.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a01c1-f1` → **3 passed**.
2. F2 merge + preview: `python -m pytest tests/test_s08_a01_c1_merge_kind_safety.py tests/test_object_correction_api.py tests/test_s08_a01_c1_reclassify_source_overlay.py -q -p no:cacheprovider --basetemp=.../s08a01c1-f2b` → **20 passed**.
3. F3 taxonomy/grouping: `test_s08_a01_role_taxonomy.py` → **18 passed**; `test_object_grouping.py test_object_correction.py` → **73 passed**.
4. Combined focused (C1 3 files + taxonomy + grouping + correction api + intelligence domain): → **123 passed**.
5. Full S08 regression (T01–T06 + A01 + golden + H02 + R01): → **305 passed** in 181.77s.
6. S05 + S06 relevant regression (+ grouping/correction): → **224 passed** in 168.55s.
7. Frontend: `npx tsc --noEmit` exit 0; `npx eslint` (touched src + e2e + config) 0 errors; `npm run build` exit 0 (route generation incl. /object-gallery).
8. Playwright: `npx playwright test --config playwright.s08a01c1.config.ts` → **5 passed in 18.8s** (desktop 4/4, mobile-390px 1/1). Screenshots under `output/s08-a01-c1/20260819-s08a01c1-r1/screenshots/`.
9. `python -m ruff check app tests` → All checks passed. `python -m mypy app` → 88 files, 0 issues. `git diff --check` → exit 0 (pre-existing LF→CRLF advisories only).
10. Protected MAIN hashes at finish: channels.json `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; SAM2.1 checkpoint 898083611 B `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` — ALL UNCHANGED.
11. Quality baseline (gate 11): `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` → Run ID **20260819-205905**, **7/7 PASS** (OVERALL exit 0). Gate 2 Python tests: **1131 passed, 19 skipped, 9 deselected in 624.31s**; ruff / mypy / tsc / lint / build all PASS. Summary: `output/quality-baseline/20260819-205905/summary.json`.
12. NO_LISTENERS at finish: QA ports 3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010 all FREE (backend 8028 + frontend 3013 torn down by PID; netstat verified 0 listeners). Env `MOTIONFORGE_DATABASE_URL` UNSET again at finish.

## Files changed (C1 window — all inside allowed scope)

- Backend: `migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py` (F1), `app/persistence/models.py` (F3), `app/schemas/object_intelligence.py` (F3), `app/schemas/object_correction.py` (F3/F4), `app/persistence/object_grouping.py` (F2 guard + shared invariant), **`app/persistence/object_correction.py` (PM-approved F2 preview)**, `app/services/object_grouping.py` (F3).
- Frontend: `frontend/src/components/object-gallery/RoleCard.tsx`, `ObjectGalleryPanel.tsx` (F2 UI + F4 reclassify); `frontend/e2e/s08-a01-c1.spec.ts`, `s08-a01-c1-mobile.spec.ts`, `frontend/playwright.s08a01c1.config.ts` (new).
- Tests: `tests/test_s08_a01_c1_migration_safety.py`, `test_s08_a01_c1_merge_kind_safety.py`, `test_s08_a01_c1_reclassify_source_overlay.py` (new); `test_s08_a01_role_taxonomy.py`, `test_object_grouping.py` (updated callers/anchor).
- Evidence: C1 `LOG.md`/`REPORT.md`; A01 `REPORT.md` correction note (append-only); `output/s08-a01-c1/20260819-s08a01c1-r1/`.

## Writer finish

- REPORT.md set to **SUBMITTED** with all required evidence recorded; run timestamps filled.
- Worktree guard held all session; env unset at finish; NO_LISTENERS verified; protected MAIN hashes unchanged.
- S07 / S09 / S08-A02 not started. No commit/push/merge; no TASK.md/PM_REVIEW change.
- Stop at SUBMITTED. Manager verification owns the next step.

---

## Manager verification (independent, after writer exit — 2026-08-19T21:1x+07:00)

### Audit vs allowlist
- Files changed in C1 window: migrations/f7a8b9c0d1e2 (F1), models.py (F3), schemas/object_intelligence.py + object_correction.py (F3/F4), persistence/object_grouping.py (F2) + object_correction.py (PM-approved F2 preview), services/object_grouping.py (F3), frontend RoleCard.tsx + ObjectGalleryPanel.tsx + e2e specs + playwright.s08a01c1.config.ts, tests (3 new C1 suites + updated taxonomy/grouping). All inside the C1 allowlist including the single PM-approved file `app/persistence/object_correction.py`. No other out-of-scope file. MAIN/other worktrees/ROADMAP/PM reviews untouched; HEAD a43b20d.
- Process correction confirmed: A01 REPORT.md got the append-only correction note (inaccurate "all files inside allowlist" claim fixed, incident recorded, history not rewritten).

### Manager independent verification (own basetemps, MOTIONFORGE_DATABASE_URL unset)
1. F1 migration downgrade-refusal (manager script, fresh DB @head + 1 source_overlay row): downgrade rc=1 with "refusing to downgrade", version stays f7a8b9c0d1e2, DDL 7-kind, rows=1, integrity ok, FK violations=[]; after removing the new-kind row, downgrade rc=0 → f6a7b8c9d0e1, CHECK 3-kind. **Atomic fail-closed confirmed.**
2. Focused C1 (migration + merge_kind_safety + reclassify): **12 passed** in 8.44s.
3. Full S08 set (A01 + 3 C1 suites + golden + H02 + R01 + extraction + grouping + correction): **306 passed** in 194.66s.
4. ruff / mypy / git diff-check: clean / 88 files 0 issues / exit 0.
5. Frontend structural verification (vision blocked by provider timeout — used code/spec read): RoleCard reclassify button (testid reclassify-source-overlay), removal-only badge + note, curation actions gated `!removalOnly`; toggleSource ignores incompatible kind; selectTarget clears incompatible sources; spec asserts F4 no-actions + reclassify visible (desktop + 390px), F2 different-kind disabled + hint, overflow<=0 mobile. Playwright `.last-run.json` = passed, failedTests=[]; 4 screenshots present.
6. Baseline 20260819-205905 summary.json = OVERALL PASS exit 0 (Gate 2: 1131 passed / 19 skipped / 9 deselected).
7. Protected MAIN: channels.json dd7aae26…555; data/motionforge.db 311296 B 67d5c773…f2e6; SAM2.1 898083611 B 2647878d…18 — all UNCHANGED.
8. NO_LISTENERS on 3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010; writer exited (session 20260819_172534_b0ad63, 2h43m, exit 0).

### Manager verdict
- F1 ✅ fail-closed atomic downgrade (row guard before mutation; CHECK invariant integrity verification; NEVER coerces)
- F2 ✅ apply_merge 409 mixed-kind; correction/merge preview SHARES merge_kind_conflict_message (no drift); zero-mutation proven; UI kind-safe + clear-on-target-change
- F3 ✅ single OBJECT_KINDS authority; derived ORM CHECK + schema pattern; migration frozen literal; REMOVAL_ONLY_KINDS_DEFAULT removed
- F4 ✅ "Sửa phân loại (sai loại?)" via correction preview+confirm+CAS; no merge/confirm/reassign/charpack; desktop + 390px
- Process ✅ scope decision recorded; A01 REPORT claim corrected; history not rewritten

**Status: MANAGER_VERIFIED_PENDING_CODEX_REVIEW** (manager does NOT approve; Codex owns APPROVED/CLOSED. S07/S09/S08-A02 code NOT started.)

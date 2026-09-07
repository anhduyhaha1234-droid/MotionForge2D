# S12-T03A LOG — Durable export/checkpoint persistence

Manager: `20260905_162953_5a5cda` · Route: provider `muse`, model
`cmc/meta/muse-spark-1.3-contributor`, reasoning max, fallback OFF.
Worktree: `MotionForge2D-worktrees\s12-s12-t03a-0907a`, branch
`codex/s12/s12-s12-t03a-0907a`, baseline `0d04673` (T01 checkpoint).
MODELS/MIGRATION LOCK (W2): T02/T04A không đụng models/migration.

## 2026-09-07 12:46 +07 — TASK_SUBMITTED

### Guards (pre-work)
- models.py hash khớp byte-guard capture; T01 six files checksum xanh.
- `alembic heads` pre-work: sole head `f9a0b1c2d3e4` (no drift → proceed).
- Baseline pristine tại `0d04673` (git status empty).

### Implementation (write-set allowlist, không assert tồn tại ngoài)
- EDIT additive `app/persistence/models.py` (+329/-0): S12 taxonomies
  (`S12_EXPORT_RUN_STATUSES` 6 / `S12_EXPORT_CHUNK_STATES` 5 + SQL literal
  constants), entities `S12ExportRun` / `S12ExportChunk` / `S12ExportLease`
  + `__all__` entries. Diff ngoài S12 = zero (grep non-S12 diff lines
  chỉ còn comment/docstring taxonomy — accepted).
- NEW `app/persistence/s12_export.py` (`S12ExportRepository`): create_run
  pins FULL identity fail-closed (checkpoint hash/revision/project +
  manifest hash/video/project/generation/draft-active + frozen T01
  profile + plan identity); claim_run single-winner (INSERT ... ON
  CONFLICT DO NOTHING + guarded lease_version CAS re-claim, fresh fence
  token); fence-token check trên mọi worker write (FencedWorkerError,
  row untouched); idempotency replay-or-conflict; chunk slot determinism;
  heartbeat/release/restart-replay.
- NEW `migrations/versions/c3d4e5f6a7b8_s12_export_domain.py`
  (down_revision `f9a0b1c2d3e4`): 3 tables + FK RESTRICT + CHECKs +
  partial-unique workspace idempotency + fail-closed downgrade
  (refuse-before-DDL khi có row; PRAGMA integrity/foreign_key_check).
- NEW `tests/s12/s12-t03a/` (`__init__.py` + domain 23 tests +
  migration 7 tests), fixtures cô lập, temp roots `s12t03a_dom_`,
  KHÔNG sửa conftest chung/test cũ.

### Fixes từ real output
- Seed `character.id` PK global → prefix id theo workspace (tag a/b).
- `_create_kwargs` checkpoint_id `ac` → `ac-a` (theo seed mới).
- Migration test `get_heads()` trả list → assert `set(heads)`.
- natural-key test sai expectation (plan_hash khác → key khác → run
  mới đúng) → truyền explicit `natural_key` cũ + plan khác → conflict.

### Gates (exact)
- `python -m pytest tests/s12/s12-t03a/ -q -p no:cacheprovider` →
  **30 passed in 34.74s** (exit 0).
- `ruff check --select F` (ruff 0.16.0) trên 5 files → All checks passed.
- `python -m alembic heads` → sole head `c3d4e5f6a7b8`; history chain
  `f9a0b1c2d3e4 -> c3d4e5f6a7b8` linear.
- T01 intact: `git diff HEAD --stat` trên 6 paths T01 → empty.
- Pre-existing fails (baseline thuần `0d04673`, stash verify): 3 tests
  `test_persistence_bootstrap.py` (table-set frozen S08/S09 vs live
  schema + S10 tables) — KHÔNG phải regression T03A, không chạm.

### Commits (local, không push)
- feat commit + docs SHA commit (xem REPORT § Commits).

# S12-T03A LOG — C2 W2 durable integrity correction

## 2026-09-09 — C2 T03A (owner 20260907_094835_159075, resumed)

### Inputs (read fully, verified on current code — C1 claims NOT trusted)
- REVIEW.md F01–F11 (`s12-c1-review-20260909`): T03A-relevant F04 (replay
  không bind material identity; M10), F05 (revision check không phải DB
  CAS; M11/M12), F06/F07 durable hash fields, F11 collection duplicate.
- S12-C2-HERMES-PROMPT §4 T03A + rows C06/C07/C08/C09/C30.
- `docs/contracts/s12-export.md` §8 server-owned authority (read-only).
- Verified M10/M11/M12 counterexamples by code inspection before fixing:
  `_replay_after_conflict` so sánh thiếu frame_count/chunk_config;
  `transition_run` so revision trên ORM rồi gán; `_require_fence_token`
  không kiểm tra expiry.

### Fixes (production, bounded)
`app/persistence/s12_export.py`:
1. Replay binds material identity: thread frame_count + canonical
   chunk_config vào `_replay_after_conflict`; mismatch →
   IdempotencyConflictError. Union resolver idem+natural keys, ambiguity
   nếu 2 candidates khác nhau (no first-key-wins); DB error propagate.
2. `transition_run`/`transition_chunk` → REAL conditional UPDATE CAS
   (WHERE status/state = current, revision = expected, EXISTS live
   lease); rowcount 1 = 1 winner; loser re-read DB truth + raise; stale
   ORM snapshot loses (M11 closed).
3. `heartbeat_lease`/`release_lease` → conditional UPDATE (live lease
   WHERE); expired/released/reclaimed token → FencedWorkerError + zero
   mutation (M12 closed).
4. `upsert_chunk`: DB-truth lease liveness trước insert + replay so
   content_hash + core/overlap material (F04 chunk-level).
5. `_lease_live_sql` DB-truth liveness (chống resident ORM stale).

Không schema change → KHÔNG migration mới; sole head `c3d4e5f6a7b8`
giữ nguyên. models.py KHÔNG sửa.

### Tests
- RENAME (git mv): `tests/s12/s12-t03a/test_c1_closure.py` →
  `test_s12_export_c1_closure.py` (F11 duplicate-basename, phần tôi).
- NEW `tests/s12/s12-t03a/test_s12_export_c2_integrity.py`: 16 tests
  C06 (5: unchanged/independent frame/chunk/plan+profile/joint) + C07
  (5: misleading-keys ambiguous, cross-scope, DB-error≠absence via event
  probe, orphan repair once, ALL rows SQL-counted) + C08 (2: barrier
  transition contention 1 winner + resident-stale control) + C09 (3:
  expired/released/reclaimed zero mutation mọi path) + same-field tamper
  control (1).
- Fixtures isolated temp roots `s12t03a_c2_*`, không sửa conftest chung.

### Gates (2026-09-09)
- pytest `tests/s12/s12-t03a/` → 60 passed in 85.88s, exit 0.
- ruff check --select F (s12_export.py, models.py, tests dir) → clean.
- git diff --check → 0. alembic heads → sole `c3d4e5f6a7b8`.
- Regression S09 dependency: test_s09_t00_structural_lock_domain.py 11
  passed. Consumer import smoke OK (runner/publication/chunks/routes).
- Evidence: `<C2-root>/s12-t03a/evidence.md` (20260909-124300-C2).

# S12-T03A REPORT — C2 W2 durable integrity (addendum)

STATUS: **TASK_SUBMITTED** · 2026-09-09 · owner 20260907_094835_159075
Branch `codex/s12/s12-s12-t03a-0907a` @ base `0bbb3b3` · commits local, NO push/merge.

## Row status (T03A scope)
| Row | Status | Proof |
|---|---|---|
| C06 | GREEN | unchanged replay same run; frame_count/chunk_config/plan/profile changed independently + jointly → IdempotencyConflictError, zero extra rows (SQL counts) |
| C07 | GREEN | misleading idem+natural keys → ambiguous (no first-key-wins); cross-scope isolated; DB-layer error propagates (never absence); true lease orphan repaired once; ALL rows counted incl. misleading keys |
| C08 | GREEN | TRUE transition contention: 2 participants, threading.Barrier, contested transition, exactly 1 winner, bounded joins; separate resident-stale ORM control loses |
| C09 | GREEN | expired/released/reclaimed tokens → FencedWorkerError on transition/chunk/heartbeat/release, zero mutation every path |
| C30 | GREEN (T03A part) | fresh/upgrade/retained-data migration tests pass; sole Alembic head `c3d4e5f6a7b8`; S09 dependency regression 11 passed; protected bytes models.py untouched |

## Findings closure (T03A-owner slice of C2)
- F04 (replay không bind material identity / M10): closed — full material
  replay comparison + union resolver; tests C06/C07.
- F05 (revision check không DB CAS / M11 + released-lease write / M12):
  closed — conditional UPDATE CAS cho run/chunk transitions, heartbeat,
  release với live-lease EXISTS; tests C08/C09 + tamper control.
- F06/F07 (durable hash fields, contract-only): chunk content_hash +
  verified + frame/overlap material + run frame_count/chunk_config_json
  đã durable; byte-hash/publication records mới KHÔNG được contract yêu
  cầu → không thêm table/migration (sole head preserved).
- F11 (collection duplicate, phần tôi): rename
  `test_c1_closure.py` → `test_s12_export_c1_closure.py` (git mv).
  Các bản `test_c1_closure.py` còn lại ở s12-t01/t02/t03b/t04a thuộc
  owner khác — ngoài write scope; full-S12 collection vẫn cần họ rename.

## Production diff
`app/persistence/s12_export.py` only (models.py unchanged; no migration).
Xem LOG_C2.md cho chi tiết từng thay đổi + evidence
`C:/Users/Admin/MotionForge2D-evidence/s12/20260909-124300-C2/s12-t03a/evidence.md`.

## Gates
| Gate | Result |
|---|---|
| pytest tests/s12/s12-t03a/ | 60 passed in 85.88s, exit 0 |
| ruff check --select F | All checks passed |
| git diff --check | 0 |
| alembic heads | sole `c3d4e5f6a7b8` |
| Regression structural_lock domain | 11 passed |

## Commits
- feat: `f25de2b7fd9c6c145f60f81170e9c7d10bbb8270` — C2 durable
  integrity: material replay binding + union resolver, real DB CAS
  transitions/chunks/heartbeat/release, live-lease fencing; rename
  t03a test_c1_closure.py → test_s12_export_c1_closure.py (F11);
  NEW test_s12_export_c2_integrity.py (16 tests). Parent `0bbb3b3`.
- docs: SHA commit riêng sau (LOG_C2.md + REPORT_C2.md này).

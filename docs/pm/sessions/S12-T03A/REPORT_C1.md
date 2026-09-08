# S12-T03A REPORT — C1 correction addendum

STATUS: **TASK_SUBMITTED** · 2026-09-08 06:24 +07 · owner 20260907_094835_159075
Branch `codex/s12/s12-s12-t03a-0907a` · commits local, không push/merge.

## Rows (C1 §4 T03A, freeze schema — không migration mới)
- C06 replay-material-identity: unchanged replay → same run, zero extra
  rows; changed frame/chunk-overlap/checkpoint-hash-revision/manifest-
  hash-generation/profile/plan-hash → fail closed, zero extra rows.
- C07 identity-union-orphan: exact claimant reused; wrong key + changed
  payload → IdempotencyConflictError; cross-scope replay không leak row
  w1 cho caller w2; tampered lease row → FencedWorkerError, lease
  nguyên; DB error ≠ absence; true orphan (lease mất, run survives —
  RESTRICT FK) repaired đúng một lần, fresh lease version = 1. Count ALL
  rows incl. misleading keys mỗi test.
- C08 two-participant: Barrier race 2 threads, bounded joins → exactly
  1 winner + 1 LeaseConflictError loser + đúng 1 lease row + run
  running; stale-ORM sequential control chứng minh loser path
  deterministic.
- C09 live-lease-fencing: expired (forced out-of-band, không sleep) /
  released / reclaimed → old token 0 mutations mọi path (transition,
  chunk, heartbeat) — revision/status untouched; đúng một live owner
  mutate được.

## Prod fix (bounded, behavior-preserving)
`claim_run` (INSERT branch + CAS branch): chỉ `pending → running` khi
pending; re-claim/claim trên run `running` giữ status + bump revision
(cho phép restart/orphan-repair path hợp lệ). Không schema change →
sole head `c3d4e5f6a7b8` unchanged, không rewrite `c3d4e5f6a7b8`.

## Gates
| Gate | Result |
|---|---|
| pytest `tests/s12/s12-t03a/ -q -p no:cacheprovider` | 44 passed in 51.47s, exit 0 |
| ruff check --select F (5 files) | All checks passed |
| git diff --check | exit 0 |
| alembic heads | sole head `c3d4e5f6a7b8` (unchanged) |

## Commits
- feat: `ecf7922f3bf0d0e67757d06f8306530e31ca62b2` — C1 closure
  (test_c1_closure.py 14 tests) + claim re-claim fix (s12_export.py).
  Parent `0ab5765`.
- docs: SHA commit riêng sau (LOG_C1.md + REPORT_C1.md này).

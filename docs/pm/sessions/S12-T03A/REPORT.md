# S12-T03A REPORT — Durable export/checkpoint persistence

STATUS: **TASK_SUBMITTED** · 2026-09-07 12:46 +07 · Manager `20260905_162953_5a5cda`
Branch `codex/s12/s12-s12-t03a-0907a` · baseline `0d04673` · commits local, không push.

## Scope
Durable run/variant/chunk ownership, versioned manifest identity, atomic
claim/fence, idempotency; process restart an toàn. Duplicate callers đúng
một winner; wrong/stale/ambiguous identity fail-closed. Migration
fresh/upgrade/retained-data; sau migration sole head nối đúng. Không thay
bảng/semantic S11. T01 freeze (`docs/contracts/s12-export.md`
s12-export-v1) CONSUME read-only — intact (diff empty).

## Write-set
- EDIT (bounded, +329/-0): `app/persistence/models.py` — S12 taxonomies
  (run 6 statuses / chunk 5 states), `S12ExportRun` / `S12ExportChunk` /
  `S12ExportLease`, `__all__`. Không diff ngoài S12.
- NEW: `app/persistence/s12_export.py` — `S12ExportRepository`
  (create/claim/fence/idempotency/chunk-determinism/heartbeat/release/
  restart-replay).
- NEW: `migrations/versions/c3d4e5f6a7b8_s12_export_domain.py`
  (down_revision `f9a0b1c2d3e4`) — đúng MỘT migration mới.
- NEW: `tests/s12/s12-t03a/` — domain (23) + migration (7), isolated
  fixtures, temp roots `s12t03a_dom_`, không sửa conftest/test cũ.
- DOCS: `docs/pm/sessions/S12-T03A/LOG.md` + `REPORT.md` (file này).

## Acceptance
1. FULL identity pin fail-closed: stale checkpoint hash/revision,
   cross-project checkpoint, unknown checkpoint, stale manifest
   hash/generation, cross-workspace manifest, unknown profile, non-hex
   hashes — tất cả raise trước khi ghi row (tests xanh).
2. Single-winner claim: loser nhận LeaseConflictError, run untouched;
   re-claim sau release bump lease_version + fresh token.
3. Fence: sai token → FencedWorkerError, row untouched (run/chunk/
   heartbeat/release paths).
4. Idempotency: replay cùng key → same row created=False; payload khác
   → IdempotencyConflictError; chunk slot cùng hash → replay, khác
   hash → StaleIdentityError (không overwrite).
5. Restart: reopen DB → lease/run rows replay đúng; live lease block
   claimant mới; heartbeat bằng token cũ OK.
6. Migration: fresh tạo đủ 3 tables + PK/FK/CHECK/index; upgrade từ
   `f9a0b1c2d3e4` giữ retained data; downgrade có row refuse-before-DDL
   (head unchanged); downgrade rỗng drop đúng 3 tables về parent.
7. Sole head sau migration: `c3d4e5f6a7b8`, chain linear từ `f9a0b1c2d3e4`.

## Gates
| Gate | Result |
|---|---|
| pytest `tests/s12/s12-t03a/ -q -p no:cacheprovider` | 30 passed in 34.74s, exit 0 |
| ruff check --select F (0.16.0), 5 files | All checks passed |
| alembic heads | sole head `c3d4e5f6a7b8` |
| alembic history | `f9a0b1c2d3e4 -> c3d4e5f6a7b8` linear |
| models diff | +329/-0, ngoài S12 = 0 |
| T01 six-paths diff | empty (intact) |
| Pre-existing fails (baseline stash-verify) | 3 bootstrap table-set tests, không phải regression |

## Commits
- feat: `fc6789fe49627aa001016dc101cd965b304cf57f` — models S12 additive
  (+329/-0), `app/persistence/s12_export.py`, migration `c3d4e5f6a7b8`,
  `tests/s12/s12-t03a/` (30 tests). Parent `0d04673`.
- docs: SHA commit riêng sau (LOG.md + REPORT.md này).

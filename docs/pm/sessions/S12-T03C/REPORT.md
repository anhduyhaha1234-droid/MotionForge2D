# S12-T03C REPORT — Durable Job/API wiring + validated publication

Status: **TASK_SUBMITTED** | Date: 2026-09-07 | Worker: S12-T03C owner
Branch: `codex/s12/s12-t03c-0907a` (worktree `s12-s12-t03c-0907a`)
Baseline: `ec45da1b1a28ca102c0e343ab9ff01459ddb82aa` | No merge/fetch/push.

## Acceptance evidence (real numbers)

- T03C suite: **15 passed** in ~20s (`tests/s12/s12-t03c/`, fresh temp DBs):
  9 job/API (submit + replay converge + status shape + cancel + terminal-cancel
  409 + retry-converge + active-retry 409 + reconcile release + reconcile skip
  + stale-identity) + 6 publication (PASS completes + FAIL→failed +
  fence + not-ready + cross-scope + completed-replay).
- Regression T03A+T03B: **49 passed** (~51s) — frozen deps untouched.
- `ruff check --select F` on 3 prod + 2 test files: **All checks passed**.
- `git diff --check`: clean. Porcelain: allowlist only (3 prod + 3 tests +
  LOG + REPORT).

## Contract §6 compliance

- Enqueue pins `pending` run before durable `s12_export` job; the HTTP request
  never renders.
- Worker handler emits chunk evidence only — completion flows exclusively
  through `publish_export_run` (fence → readiness ready → ownership → T03B
  assemble → T04A PASS → CAS transition to `completed`).
- Same-lineage retry converges (`created=False`, 1 run row, no duplicate
  successor); active predecessor retry → 409; terminal double-cancel → 409.
- Reconciler releases expired leases on running runs only; live leases
  skipped; per-run isolation (one bad lease never aborts the sweep).

## Known frozen-layer observation (not patched, for Manager)

T03A `_replay_after_conflict` does not cover the schema-level identity UNIQUE
backstop (see LOG.md F4) — a same-pins create on a distinct natural key raises
`S12ExportError` instead of converging. T03C routes around it by re-submitting
same lineage pins. If a future task needs distinct-natural-key retries, the
T03A owner should extend the conflict lookup.

# S08-R01 — Runtime Lifecycle Safety

**Status:** READY
**Depends on:** S08-T06 SUBMITTED (sprint exit CHANGES_REQUESTED — Codex finding A)
**New Task ID:** S08-R01 (brand-new session required; never reuse a closed session)

## Outcome

Fix the GENERIC durable-job lifecycle (not only S08 handlers):

1. A cancel arriving while a job is still queued must reach terminal
   `cancelled` deterministically with zero handler effects and no pending
   forever-state.
2. Preserve idempotent second cancel, running cancel drain, completion/cancel
   races, fencing, retry, restart and immutable terminal history.
3. Add an explicit regression for: create queued job -> cancel before worker
   claim -> worker/reconciler/restart -> cancelled, zero effects, no orphan
   lease.
4. Cover DISCOVER_OBJECTS and RECOMPUTE_OBJECTS using the same generic fix.
5. Resolve the default managed artifact root from the configured absolute
   project root, not process CWD. Worker, reconciler, orchestrator, APIs and
   manifests must use the same public JobService root/factory.
6. Add QA/test fail-closed protection: QA/test mode requires an explicit
   absolute isolated root and must reject the protected MAIN root.
7. QA launchers must not rely on `cd` for storage correctness.
8. Preserve pristine `app.main:app` lifecycle and S05-C03/C04 wiring.

## Allowed write scope

- `app/config.py`
- `app/api/deps.py`
- `app/api/app.py`
- `app/lifecycle.py`
- `app/workflow/job_service.py`
- `app/workflow/durable_worker.py`
- `app/workflow/job_reconciler.py`
- direct lifecycle/job tests and isolated QA launcher tests
- this packet LOG/REPORT

## Forbidden

S08-T02..T06 product scope, frontend, S05/S06 contract changes, protected data
(channels.json, MAIN data/motionforge.db, SAM2.1 checkpoint), destructive Git,
TASK.md/PM_REVIEW/sprint contract edits.

## Acceptance and validation

- Queued-cancel regression passes (zero effects, no orphan lease, deterministic
  terminal state); running-cancel drain still passes; second cancel idempotent.
- DISCOVER_OBJECTS + RECOMPUTE_OBJECTS covered by the generic fix.
- Managed root derives from configured absolute project root in every public
  path (worker/reconciler/orchestrator/APIs/manifests).
- QA/test mode rejects the protected MAIN root and requires explicit absolute
  isolated root.
- QA launcher works without relying on `cd`.
- Pristine `app.main:app` lifecycle + S05-C03/C04 wiring tests pass.
- Relevant S02/S05 durable-job regressions, ruff, mypy, git diff --check.
- Stop at SUBMITTED.

# S05-C04 — Production Job Service Wiring

Status: CLOSED (APPROVED by Codex PM review on 2026-08-05)
Owner: Hermes implementation writer; Codex is the sole reviewer/approver.
Worktree: `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`
Branch: `codex/prepare-s05-t01`

## Outcome

Make the real production entrypoint `uvicorn app.main:app` bind the default
`JobService`, its `DurableWorker`, `JobReconciler`, and
`AnalyzeChainOrchestrator` to one explicit database and managed root. A pristine
app lifecycle must execute and resume T02 -> T03 -> T04 without dependency
injection and without `job service not initialized`.

Stop at `SUBMITTED`. Do not claim `APPROVED`.

## Required reading

Read these files before editing:

- `docs/pm/SESSION_PROTOCOL.md` in MAIN (read-only)
- `docs/pm/sessions/S05-C03-final-lifecycle-correction/TASK.md`
- `docs/pm/sessions/S05-C03-final-lifecycle-correction/LOG.md`
- `docs/pm/sessions/S05-C03-final-lifecycle-correction/REPORT.md`
- `output/SPRINT_EXIT_REPORT.md`
- `output/SPRINT_S05_SESSIONS_TRACKING.md`
- `app/api/deps.py`
- `app/api/app.py`
- `app/main.py`
- `app/lifecycle.py`
- `app/workflow/job_service.py`
- `app/workflow/durable_worker.py`
- `app/workflow/job_reconciler.py`
- `app/workflow/analyze_orchestrator.py`
- `output/s05t05_qa_backend.py` (read-only evidence of the defect)
- `tests/test_s05_lifecycle.py`
- `tests/test_s05_chain_progression.py`
- `tests/test_s05_orchestration.py`
- `tests/test_s05_golden_integration.py`

## Confirmed defect

`deps.get_job_service()` constructs default `JobService()`. Its constructor
creates a `DurableWorker` bound to a placeholder factory that raises
`RuntimeError("job service not initialized")`. `JobService.initialize()` later
creates the real service factory, but does not rebind/rebuild that worker.
`start_worker()` therefore starts the stale placeholder-bound worker.

Current `app/api/app.py` and the process-wide analyze orchestrator also inspect
private `JobService` attributes to infer factories/roots. The correction must
replace that with a public, explicit lifecycle binding contract.

## Allowed write scope

- `app/workflow/job_service.py`
- `app/workflow/durable_worker.py` only if a public binding API is required
- `app/lifecycle.py`
- `app/api/app.py`
- `app/api/deps.py`
- `app/workflow/analyze_orchestrator.py`
- `tests/test_s05_production_wiring.py` (new)
- `docs/pm/sessions/S05-C04-production-job-service-wiring/LOG.md`
- `docs/pm/sessions/S05-C04-production-job-service-wiring/REPORT.md`

Do not edit every allowed file unless needed. If another file is genuinely
required, stop as `BLOCKED` and request a bounded scope change.

## Forbidden scope

- MAIN and every other worktree
- `channels.json`, every `data/` directory, every existing database, fixtures,
  user data, backups, QA artifacts, screenshots, and existing logs
- existing C01/C02/C03 packets, S05 task packets, sprint reports/tracking,
  ROADMAP, architecture contracts, frontend, migrations, and service algorithms
- commits, pushes, merges, deploys, branch changes, stash, reset, checkout,
  restore, clean, deletion, or destructive cleanup
- private-attribute patching from `app.py`
- test injection through `deps._job_service` or `deps._lifecycle_db` in the new
  pristine production-wiring test

## Acceptance criteria

1. Default `JobService()` after explicit initialization has a `DurableWorker`
   bound to the real session factory; no stale placeholder remains.
2. Binding is public and explicit. `app.py` does not patch or inspect private
   service attributes.
3. `JobService`, `DurableWorker`, `JobReconciler`, and
   `AnalyzeChainOrchestrator` use the same database and managed root.
4. Add a pristine production-wiring integration test that:
   - uses a temporary configured project root only;
   - does not inject `deps._job_service` or `deps._lifecycle_db`;
   - imports/uses the real `app.main:app` default dependency path in a pristine
     process/module state and enters the real FastAPI lifespan;
   - creates/uploads and POSTs analyze exactly once;
   - proves the default worker claims and completes T02 -> T03 -> T04;
   - restarts the real app lifecycle on the same temporary database and proves
     correct resume/no duplicate effects;
   - proves no `job service not initialized` error.
5. The new test and all verification use only temporary isolated storage. Never
   point a smoke test at MAIN, a worktree `data/`, or production/user data.
6. Preserve C03 restart/lifecycle behavior, source supersession, immutable old
   evidence, GET read-only behavior, retry idempotency, concurrent advancement,
   CFR/VFR, SHA/size evidence, containment, stable Scene IDs, cancellation, and
   orphan cleanup.
7. Run the targeted S05 lifecycle/orchestration/golden suite plus the new test.
   Run additional focused regressions for every changed subsystem. Do not run
   Playwright or the full baseline if doing so would write existing QA artifacts;
   instead report them for Codex's post-submit verification.
8. `REPORT.md` must list exact files, commands, results, isolation evidence,
   remaining risks, and status `SUBMITTED` only.

## Mandatory pre-write guard

Before the first edit, record in `LOG.md`:

- `pwd`, `git rev-parse --show-toplevel`, branch, and full `git status --short`;
- confirmation no other Hermes writer targets this worktree;
- protected MAIN baseline: `channels.json` SHA-256
  `DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555`;
- MAIN `data/motionforge.db` is forbidden (observed 311296 bytes, mtime
  2026-08-04 18:24:36 local; do not open or touch it);
- acknowledgement of pre-existing dirty/untracked state in all trees.

## Required verification

At minimum, from the S05 worktree with pytest cache disabled:

```text
python -m pytest -q tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -p no:cacheprovider
python -m ruff check <changed Python files>
python -m mypy app
git diff --check
```

Run narrowly first. If a command would access non-temporary data, stop and fix
the isolation before running it.

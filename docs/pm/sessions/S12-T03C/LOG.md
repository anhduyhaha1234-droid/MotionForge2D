# S12-T03C LOG — Durable Job/API wiring + validated publication

Task: S12-T03C | Worktree: `s12-s12-t03c-0907a` | Branch: `codex/s12/s12-t03c-0907a`
Baseline: `ec45da1b1a28ca102c0e343ab9ff01459ddb82aa` | Date: 2026-09-07

## Writes (allowlist only, frozen T03A/T03B untouched)

1. `app/workflow/s12_export_jobs.py` (293 lines)
   - `S12_EXPORT_JOB_TYPE = "s12_export"` + `submit_export_job` (pin run via
     T03A `create_run` idempotent, commit-then-enqueue one-writer-at-a-time,
     replay converges via `_find_job_by_key` + `JobInfo` shape normalize) +
     `_s12_export_handler` (atomic claim → `ExportRunner.resume()` → candidate
     evidence; never completes, never publishes) +
     `register_s12_export_handler` + `reconcile_export_jobs` (releases only
     expired leases on `running` runs; bounded, per-run isolation, never raises).
2. `app/api/routes/s12_export.py` (348 lines)
   - `POST /s12-exports/submit` (202, no render in request) +
     `GET /s12-exports/{run_id}` (run + live job state + chunk summary) +
     `POST /s12-exports/{run_id}/cancel` (run + job `queued|running→cancelling`
     in ONE request-session transaction; terminal → 409) +
     `POST /s12-exports/{run_id}/retry` (failed/cancelled only; active
     `queued|running` predecessor → 409; same pins converge via T03A backstop).
3. `app/services/s12_export/publication.py` (264 lines)
   - `publish_export_run`: fence → readiness (`ready` only, computed per-video
     via `check_run_readiness`, never seeded) → ownership → T03B `assemble_run`
     (refuses overwrite) → T04A `validate` PASS → `running→verifying→completed`
     under fence + revision CAS. FAIL/NOT_MEASURED → `failed` (retryable).
     Completed replay converges (`reused: True`).
4. `tests/s12/s12-t03c/` — `__init__.py` + `test_export_jobs_api.py` (9 tests)
   + `test_publication.py` (6 tests). Real migrated temp DBs, T03A seed lineage.

## Key findings during build (real output, not assumptions)

- F1: `JobService.create_job` returns `JobInfo` (has `job_id`, NO
  `idempotency_key`) — tests assert key via `JobRepository.list_jobs`.
- F2: direct route-function calls pass FastAPI `Query` sentinels, not `None` —
  tests pass `project_id=None` explicitly.
- F3: replay path returned raw `JobRecord` (`.id`) vs fresh `JobInfo`
  (`.job_id`) — fixed by normalizing replay through `job_service._job_info`.
- F4: T03A schema has a UNIQUE identity backstop on
  (workspace, project, video, profile, plan_hash, checkpoint_hash) BELOW the
  natural_key layer; `_replay_after_conflict` only looks up idempotency_key /
  natural_key, so a same-pins retry on a distinct natural key raises
  `S12ExportError` instead of converging. Frozen behavior — NOT patched.
  Retry therefore re-submits same lineage pins and converges onto the
  cancelled run (`created=False`, exactly 1 run row, no duplicate successor).
- F5: cancelled run's job lingers in `cancelling` (no worker finalizes it in
  tests) — retry's active-check treats only `queued|running` as competing.

# S08-R01 — LOG

**Status:** SUBMITTED_PENDING_MANAGER (writer exited; see REPORT.md)

**Session:** 20260816_225849_3788f0 (fresh session, new Task ID — no resume)
**Worktree:** C:/Users/Admin/MotionForge2D-worktrees/s08-integration
**Branch:** codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204

## 1. Hard worktree guard (verified BEFORE any write)

```
pwd                              -> /c/Users/Admin/MotionForge2D-worktrees/s08-integration
git rev-parse --show-toplevel    -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration
git branch --show-current        -> codex/s08-integration
git rev-parse HEAD               -> a43b20da742996bafcb2f9d1ac57b10d3f1a5204
git status --short               -> snapshot captured (21 M + 122 ??), unchanged baseline
```

All five PASS; work proceeded.

## 2. Baseline (pre-work evidence)

- Protected MAIN `channels.json` SHA-256:
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
- Protected MAIN `data/motionforge.db` size: 311296 bytes
- Both re-verified byte-exact at the END of the session (see §7).

## 3. Design summary (what changed and why)

Engine-level generic fix for the queued-cancel drain gap and the
CWD-relative managed-root defect (Codex sprint-exit findings):

1. `app/workflow/durable_worker.py` — the queue scan falls back to an
   UNLEASED `cancelling` Job when no `queued` Job exists. The drain
   claim acquires a lease and marks the Job `running` with a durable
   `cancel_drain` event marker (the `running` transition is the only
   path that sets `started_at`, required by schema CHECK
   `ck_job_finished_requires_started`), then drains straight to
   terminal `cancelled` with ZERO handler effects. The drain's lease is
   released atomically with the terminal transition and re-released
   after the heartbeat thread is provably joined (no orphan lease).
   The drain flag is decided from the LIVE state at claim time so a
   cancel committing between scan and claim still yields a drain.
2. `app/workflow/job_reconciler.py` — two additions:
   a. unleased `cancelling` Jobs resolve directly to terminal
      `cancelled` (marked `running` + terminal in ONE transaction,
      never committed separately, never visible);
   b. `_resolve_fenced` recognizes the durable `cancel_drain` marker so
      a drain claim that died mid-drain resolves to `cancelled` instead
      of requeue (requeue would RUN the handler — cancel wins, §6.3).
3. `app/workflow/job_service.py` —
   a. default managed root = `<configured project root>/artifacts`
      (absolute), never the process CWD; worker/manifests bind the same
      public root;
   b. `cancel_job` re-reads and retries the guarded transition over a
      bounded window so a cancel racing the worker's claim lands on the
      live state (first committed writer wins, §6.3);
   c. fail-closed root validation at construction (managed root) and at
      default DB-path resolution (project root).
4. `app/config.py` — `PROTECTED_MAIN_ROOT`, QA-mode flag
   (`MOTIONFORGE_QA_MODE`), pytest detection (`PYTEST_CURRENT_TEST`),
   `validate_runtime_roots()` fail-closed guard (explicit, absolute,
   isolated; MAIN root and relative roots rejected; QA mode requires an
   explicit `MOTIONFORGE_ROOT`).
5. `app/api/deps.py` — `get_managed_root()` fallback resolves from the
   configured project root (validated) instead of CWD-relative
   `Path("artifacts")`.
6. `tests/test_s05_orchestrator_binding.py` — S05-C04-R3 test updated to
   the new default-root contract (absolute config-derived root; CWD
   provably irrelevant; worktree untouched). The wiring assertions
   (authoritative factory binding, fail-closed pre-init access) are
   unchanged.
7. NEW `tests/test_s08_r01_queued_cancel_lifecycle.py` (7 tests) and
   NEW `tests/test_s08_r01_root_resolution.py` (11 tests).

Not touched: `app/api/app.py`, `app/lifecycle.py`,
`app/persistence/*` (repo layer unchanged — only existing public
repository methods are used), frontend, S05/S06 contracts, protected
data. No commit/push/reset/checkout/restore/clean/stash/delete.

## 4. Iterations (real failures fixed)

1. Injected-factory services passed `project_root=None` to the guard and
   were rejected ("project root is not set") — the guard now skips the
   project-root checks when the caller owns the database target.
2. Initialize-policy tests (S02-T05 CR3) pre-set `_database_path` to
   temp files but the construction-time project-root guard fired —
   project-root validation moved to `_ensure_engine`, exactly when the
   service resolves its DEFAULT database path.
3. Drain transitions hit `ck_job_finished_requires_started`
   (`finished_at` without `started_at`) — the drain now passes through a
   marked `running` transition (worker claim: committed before drain;
   reconciler: same transaction, never visible separately).
4. Drain flag originally derived from which SELECT found the candidate —
   a cancel committing between scan and claim would have run the
   handler; the flag is now decided from the LIVE state at claim time.
5. Ruff SIM102/F401/F841 in the new code — fixed; full ruff/mypy green.

## 5. Validation commands (all real, pytest cache disabled, shallow basetemps)

```
python -m pytest tests/test_s08_r01_queued_cancel_lifecycle.py \
  tests/test_durable_worker.py tests/test_job_reconciliation.py \
  tests/test_s05_atomic_cancel.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-recheck
  -> 68 passed

python -m pytest tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-root2
  -> 11 passed

python -m pytest tests/test_persistence_bootstrap.py tests/test_api.py \
  tests/test_durable_job_persistence.py tests/test_durable_job_api.py \
  tests/test_durable_worker.py tests/test_job_reconciliation.py \
  tests/test_s05_orchestrator_binding.py \
  tests/test_s08_r01_queued_cancel_lifecycle.py \
  tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-final-core
  -> 204 passed

python -m pytest tests/test_s05_atomic_cancel.py tests/test_s05_chain_progression.py \
  tests/test_s05_lifecycle.py tests/test_s05_orchestration.py \
  tests/test_s05_golden_integration.py tests/test_s05_production_wiring.py \
  tests/test_video_import.py tests/test_timebase.py \
  tests/test_scene_detection.py tests/test_video_proxy.py \
  -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-final-s05
  -> 150 passed   (includes pristine app.main:app S05-C04 wiring, 4 fresh-process generations)

python -m pytest tests/test_object_intelligence_domain.py \
  tests/test_object_extraction.py tests/test_object_extraction_api.py \
  tests/test_object_extraction_production_wiring.py tests/test_object_grouping.py \
  tests/test_object_correction.py tests/test_object_correction_api.py \
  tests/test_s08_golden_object_intelligence.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-final-s08
  -> 137 passed

python -m pytest tests/test_character_domain.py tests/test_character_preset_importer.py \
  tests/test_character_read_api.py tests/test_character_validator.py \
  tests/test_publish_rejection.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-s06
  -> 90 passed

python -m ruff check app tests          -> All checks passed!
python -m mypy app                      -> Success: no issues found in 86 source files
git diff --check                        -> exit 0 (pre-existing CRLF advisories only)
```

## 6. Protected-data comparison (end of session)

- MAIN `channels.json` SHA-256 (python hashlib):
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  — identical to the baseline. UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes — identical to the baseline.
  UNCHANGED.

## 7. Final state

`git status --short` = 147 entries (baseline 143 + app/config.py M +
app/workflow/job_reconciler.py M + 2 new S08-R01 test files). No stray
`artifacts/`/`uploads`/`staging`/`data` created in the worktree root
(the tracked `artifacts/milestone_1a/openapi.json` baseline is
untouched — the R3 test snapshots it byte-exact). No commit/push/
deploy/reset/checkout/restore/clean/stash/delete was performed.

Writer exited. SUBMITTED — manager verification pending.

## MANAGER VERIFICATION — 2026-08-16

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW** (internal gate; NOT APPROVED)

Manager independent evidence:
- Focused R01 (queued-cancel 7 + root-resolution 11): 18 passed in 6.26s (s08r01-mgr-focused)
- Durable regressions (S05 orchestrator_binding + durable_worker 32 + job_reconciliation 24 + durable_job_api 15 + durable_job_persistence 48): 121 passed in 73.07s (s08r01-mgr-durable)
- S05 production wiring + lifecycle: 4 passed in 45.74s (s08r01-mgr-wiring)
- Code audit: generic drain flag at claim level in durable_worker (not S08-handler-specific); DISCOVER_OBJECTS/RECOMPUTE_OBJECTS covered by same path; root resolution from configured absolute project root in worker/reconciler/orchestrator/API; QA/test fail-closed rejects MAIN root.
- Scope audit: app/config.py, app/api/deps.py, app/workflow/{durable_worker,job_reconciler,job_service}.py + 2 new test files + test_s05_orchestrator_binding.py update — all within allowed scope; app/lifecycle.py + app/api/app.py NOT touched (pristine preserved).
- Protected: MAIN channels.json SHA dd7aae26...555 UNCHANGED; MAIN data/motionforge.db 311296 B UNCHANGED.

Decision: R01 released; S08-T02 correction may open.

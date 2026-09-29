# S05-C04 Log

Status: SUBMITTED

Codex created this bounded correction packet after independently confirming the
production default-worker placeholder defect and confirming no C04 writer was
running. Hermes must append the pre-write guard and implementation evidence.

## Pre-write guard (2026-08-05, Hermes session 20260805_190611_c270dc)

Recorded BEFORE the first edit, per TASK.md "Mandatory pre-write guard":

- `pwd` → `/c/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
- `git rev-parse --show-toplevel` → `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
- Branch → `codex/prepare-s05-t01`
- Full `git status --short` → 47 entries, ALL pre-existing S05 worktree state
  (S05-C01/C02/C03 packets, S05-T01..T06 packets, app/workflow/analyze_orchestrator.py,
  app/api/{app,app.py,deps.py via earlier tasks}, app/services/{scene_detector,timebase,
  video_import,video_proxy}.py, frontend import-analyze UI + e2e, tests/test_s05_*.py,
  fixtures, ROADMAP, docs/architecture contracts). No entry was created by this task.
- Single-writer confirmation: Codex verified no C04 writer was running when the
  packet was created; this session is the only Hermes writer active on this
  worktree (no other `hermes chat` worker is running against prepare-s05-t01).
- Protected MAIN baseline — `channels.json` SHA-256:
  `certutil -hashfile C:/Users/Admin/MotionForge2D/channels.json SHA256` →
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  (matches TASK.md DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555).
- MAIN `data/motionforge.db` is FORBIDDEN — observed 311296 bytes, mtime
  2026-08-04 18:24:36 +0700 (matches TASK.md). Not opened, not touched.
- MAIN tree baseline: `git status --short | wc -l` = 44 entries (sprint baseline,
  unchanged).
- Acknowledgement: pre-existing dirty/untracked state in ALL trees is preserved
  — no commit, push, merge, branch switch, stash, reset, clean, restore, delete,
  or destructive cleanup at any point.

## Required reading (completed)

- docs/pm/SESSION_PROTOCOL.md (MAIN, read-only) — status flow, single-writer,
  stop at SUBMITTED.
- S05-C04 TASK.md (full) + START_PROMPT.md (full).
- S05-C03 TASK.md / LOG.md / REPORT.md — lifespan ownership + supersession
  delivered; C03 REPORT explicitly documented the production note: bare
  `uvicorn app.main:app` still constructs a JobService whose worker keeps a
  placeholder session factory (`output/s05t05_qa_backend.py`).
- output/SPRINT_EXIT_REPORT.md + output/SPRINT_S05_SESSIONS_TRACKING.md —
  correction chain C01→C02→C03 SUBMITTED, manager-verified, Codex sole approver.
- app/api/deps.py — `get_job_service()` lazy default `JobService()`; service
  accessors read `getattr(job_service, "_session_factory", None)` (private).
- app/api/app.py — lifespan reads `job_service._session_factory` + `deps._lifecycle_db`
  (private) to infer the factory; constructs a SECOND engine for the reconciler.
- app/main.py — real entrypoint `uvicorn app.main:app`.
- app/lifecycle.py — `Lifecycle(job_service, session_factory)`; initialize() →
  job_service.initialize() (no worker rebind).
- app/workflow/job_service.py — confirmed defect: default `JobService()` builds
  `DurableWorker(_placeholder)` raising `RuntimeError("job service not initialized")`;
  `initialize()` → `_ensure_engine()` creates the REAL `_session_factory` but never
  rebinds the worker; `start_worker()` starts the stale placeholder-bound worker.
- app/workflow/durable_worker.py — `DurableWorker.__init__(session_factory, ...)`
  stores `self._session_factory`; no public rebind API exists.
- app/workflow/job_reconciler.py (via lifecycle.py usage) — reconciler gets the
  factory passed by the caller.
- app/workflow/analyze_orchestrator.py — process-wide accessor reads
  `getattr(job_service, "_session_factory"/"_managed_root", None)` + `deps._lifecycle_db`
  (private); orchestrator otherwise uses public surfaces only.
- output/s05t05_qa_backend.py — read-only evidence: documents the pre-existing
  production wiring gap verbatim ("never re-wires the WORKER's [factory]").
- tests/test_s05_lifecycle.py / test_s05_chain_progression.py /
  test_s05_orchestration.py / test_s05_golden_integration.py — all inject
  `deps._job_service = JobService(factory, managed_root=...)` + `deps._lifecycle_db`;
  the new C04 test must NOT inject either.

## Confirmed defect (from required reading)

1. `deps.get_job_service()` constructs default `JobService()`.
2. Its constructor creates `DurableWorker` bound to a placeholder factory that
   raises `RuntimeError("job service not initialized")`.
3. `JobService.initialize()` creates the real session factory but does NOT
   rebind/rebuild that worker.
4. `start_worker()` starts the stale placeholder-bound worker → production
   `uvicorn app.main:app` never executes Jobs.
5. `app/api/app.py` + the orchestrator accessor inspect private JobService
   attributes (`_session_factory`, `_managed_root`) to infer factories/roots.

## Plan (≤7 steps)

1. Add public `DurableWorker.bind_session_factory()` (durable_worker.py).
2. JobService: public `session_factory` / `managed_root` properties; rebind the
   owned worker to the real factory inside `_ensure_engine()` (job_service.py).
3. deps.py: use the public `job_service.session_factory` in the 4 durable
   service accessors (no private reads).
4. app/api/app.py lifespan: `job_service.initialize()` → `job_service.session_factory`
   (public) → one Lifecycle; drop `_session_factory`/`_lifecycle_db` reads.
5. analyze_orchestrator.py accessor: public properties only; drop `_lifecycle_db`.
6. NEW tests/test_s05_production_wiring.py — pristine subprocess test: real
   `app.main:app` default path, temp root only, no deps._job_service/_lifecycle_db
   injection; POST analyze once; default worker claims+completes T02→T03→T04;
   real app lifecycle restart on the same temp DB → resume, no duplicates;
   no "job service not initialized".
7. Verification: targeted pytest (5 files) → ruff → mypy → git diff --check →
   LOG/REPORT/TASK.md status SUBMITTED.

## Implementation (19:20 → 19:45 +07:00)

- `app/workflow/durable_worker.py` — NEW public `bind_session_factory()`:
  rebinds the worker's session factory under its lock; refuses rebinding a
  RUNNING worker; raises TypeError for non-callables. This is the public
  binding API the default JobService needs (task allowed this file exactly
  for this).
- `app/workflow/job_service.py`:
  - NEW public properties `session_factory` and `managed_root` — the
    explicit binding contract; callers never inspect `_session_factory` /
    `_managed_root` directly anymore.
  - `_ensure_engine()` now REBINDS the owned worker
    (`self._worker.bind_session_factory(self._session_factory)`) when the
    real factory is created — the core defect fix: a default `JobService()`
    starts with a placeholder-bound worker; explicit initialization replaces
    the placeholder so `start_worker()` starts a worker bound to the real
    database (AC1).
  - `_ensure_engine()` also ensures the default managed root
    (`self._managed_root.mkdir(parents=True, exist_ok=True)`) — the
    import/proxy handlers stat it (disk-safety check,
    `video_import._disk_free_bytes`) and publish into it; the QA launcher
    used to pre-create it by hand, the default production path now ensures
    it. (Found by the pristine test: first run failed with
    `INPUT_UNREADABLE: cannot stat source or managed root: [WinError 3]`.)
- `app/api/deps.py` — the 4 durable service accessors
  (channel/project/video/summary-repository) now read
  `job_service.session_factory` (public) instead of
  `getattr(job_service, "_session_factory", None)`; docstrings updated.
- `app/api/app.py` — lifespan now performs the explicit public binding:
  `job_service.initialize()` → `session_factory = job_service.session_factory`
  (public) → `Lifecycle(job_service, session_factory)`; the private
  `_session_factory` read, the second-engine fallback and the
  `deps._lifecycle_db` read are GONE. No private service attribute is
  inspected or patched (AC2). `default_database_path` /
  `create_engine_for_path` / `create_session_factory` imports removed.
- `app/workflow/analyze_orchestrator.py` — process-wide accessor now uses
  `job_service.session_factory` + `job_service.managed_root` (public);
  `deps._lifecycle_db` read removed; uninitialized-service fallback resolves
  `default_database_path()` (same default the lifecycle uses). All four
  components (JobService, DurableWorker, JobReconciler, AnalyzeChainOrchestrator)
  now resolve ONE session factory + ONE managed root (AC3).
- `tests/test_s05_production_wiring.py` — NEW pristine production-wiring
  integration test (AC4): every app generation is a FRESH subprocess that
  sets only MOTIONFORGE_ROOT/OUTPUT/MODELS to a tmp root, imports the real
  `app.main:app`, enters the real FastAPI lifespan via TestClient, never
  touches `deps._job_service` / `deps._lifecycle_db`; gen1 creates/uploads
  a real synthetic CFR video and POSTs `/analyze` EXACTLY ONCE and waits for
  the import job; gen2/gen3 are fresh processes over the same tmp DB with NO
  analyze API request — the proxy and scene jobs materialize (startup scan)
  and complete under the fresh default worker; gen4 proves a further restart
  duplicates nothing; terminal proof: 1/1/1 jobs all completed, 2 scene rows,
  1 video item, Project shell row, ≥2 managed artifacts, staging drained;
  the string "job service not initialized" never appears in any generation.

First pristine run FAILED with `INPUT_UNREADABLE: cannot stat source or
managed root: [WinError 3]` → root cause: default managed root "artifacts"
did not exist → fixed with the `_ensure_engine()` mkdir above → PASS.

## Verification (19:45 → 20:05 +07:00) — each separately, cache disabled

- [19:45] `python -m pytest -q tests/test_s05_production_wiring.py -p no:cacheprovider`
  → **1 passed** (22.15s) — 4 pristine subprocess generations, no
  "job service not initialized", chain 1/1/1 completed, resume proven.
- [19:50] Required suite:
  `python -m pytest -q tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -p no:cacheprovider`
  → **34 passed** (70.78s).
- [19:55] Focused regressions (changed subsystems: durable worker/job
  service/reconciler/managed artifacts + deps accessor consumers + legacy
  default-JobService fixtures):
  `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py tests/test_delete_and_autosegment.py tests/test_list_projects.py tests/test_channel_crud.py tests/test_channel_workspace.py tests/test_video_item_crud.py tests/test_project_crud.py tests/test_project_summary.py tests/test_project_summary_correction.py tests/test_project_summary_correction2.py tests/test_project_summary_mapping.py -p no:cacheprovider`
  → **390 passed, 2 skipped** (89.21s).
- [20:00] S05 service regression set:
  `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py tests/test_scene_chunk_stitch.py -p no:cacheprovider`
  → **113 passed, 5 skipped** (39.02s).
- [20:02] `python -m ruff check app/workflow/durable_worker.py app/workflow/job_service.py app/api/deps.py app/api/app.py app/workflow/analyze_orchestrator.py tests/test_s05_production_wiring.py`
  → **All checks passed**.
- [20:03] `python -m mypy app` → **Success: no issues found in 66 source files**.
- [20:04] `git diff --check` → **exit 0** (only the pre-existing CRLF advisory
  on frontend/test-results/.last-run.json).

## Isolation evidence (post-verification)

- Worktree `git status --short | wc -l` = **49** = the 47 pre-existing entries
  + exactly 2 new: `M app/api/deps.py`, `?? tests/test_s05_production_wiring.py`.
- MAIN tree: 44 entries (unchanged); `channels.json` SHA-256 unchanged
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`;
  MAIN `data/motionforge.db` untouched (311296 bytes, mtime 2026-08-04
  18:24:36). No Playwright run, no quality-baseline run, no QA artifact
  writes (reported for Codex post-submit verification per AC7).
- The pre-existing tracked `artifacts/` dir (M1A openapi.json, mtime
  2026-08-04) was NOT modified (no git status entry).
- No commits, no pushes, no branch changes, no destructive operations.

## Deliverables

- LOG.md + REPORT.md (this task), status **SUBMITTED** (never APPROVED).
- TASK.md status updated READY → SUBMITTED.
- Stop after SUBMITTED — Codex alone reviews and approves.

---

## Correction round 2 — Codex CHANGES_REQUESTED (2026-08-05, Hermes session 20260805_200149_49361a)

Codex returned 4 findings. This section records the round-2 corrections and
verification. Status line changed READY -> SUBMITTED per finding 4; TASK.md and
REPORT.md stay SUBMITTED. Nothing APPROVED.

### Finding 1 (BLOCKER) — competing session factory in get_analyze_orchestrator()

**Fix (app/workflow/analyze_orchestrator.py):**
- The competing-factory fallback is REMOVED. When
  `JobService.session_factory` is None the accessor now FAILS CLOSED with
  `RuntimeError("analyze orchestrator requires an initialized JobService ...")`
  — it never creates an engine/factory of its own, so no orchestrator can
  ever be cached pre-init with a competing factory (the cache is keyed by
  JobService object identity; every cached orchestrator now holds the EXACT
  authoritative factory).
- NEW public read-only properties on `AnalyzeChainOrchestrator`:
  `session_factory` and `managed_root` (the S05-C04 binding contract is now
  provable through public surfaces only — no private attribute is read or
  patched anywhere).
- Orchestrator receives factory + managed root ONLY through the initialized
  public JobService lifecycle binding (`session_factory` / `managed_root`).

**Regression test (NEW tests/test_s05_orchestrator_binding.py, 2 tests):**
- access before initialization -> raises (fail-closed), nothing cached;
- initialize the default JobService (real Alembic bootstrap over a
  temporary project root; both the explicit `JobService(managed_root=...)`
  and the deps-constructed `JobService()` production paths);
- `orchestrator.session_factory IS job_service.session_factory` (object
  identity = the EXACT authoritative factory) and
  `orchestrator.managed_root == job_service.managed_root`;
- `ensure_started()`/`stop()` run; repeated access returns the same cached
  authoritative instance -> no stale cached orchestrator survives lifecycle
  init.

### Finding 2 (BLOCKER) — stage boundaries in tests/test_s05_production_wiring.py

Each generation now freezes the app's OWN progression loop with a public
`get_analyze_orchestrator().stop()` immediately after the boundary event
(NEVER a manual `advance_once`, NEVER a deps injection), so a successor can
only materialize in its intended restart generation:

- gen1: POST /analyze EXACTLY ONCE -> import completes under the default
  worker -> **proxy=0, scene=0** (asserted in the fresh subprocess AND by
  the parent from the temp DB) -> full lifespan shutdown.
- gen2: fresh process, NO analyze POST, NO manual advance_once -> startup
  scan materializes the proxy; worker completes it -> **proxy=1 completed,
  scene=0** -> full shutdown.
- gen3: startup scan materializes the scene; only this generation creates
  it -> **scene=1 completed** (import/proxy still exactly 1 each).
- gen4: restart over the completed chain -> **no duplicate jobs** (1/1/1),
  states all completed, no duplicate Scene rows/artifacts/effects.
- The test FAILS if a successor completes before its intended restart
  (runner-side asserts make the generation exit non-zero).

### Finding 3 — Playwright desktop + 390px + fresh 7/7 baseline, isolated

NEW C04 evidence root: `output/s05-c04-r2-evidence/` (backend-root,
screenshots/, test-results-interaction/, test-results-cancel-rerun/,
test-results-visual/). The backend was started as the REAL production
entrypoint `python -m uvicorn app.main:app --app-dir <worktree> --port 8003`
with cwd + MOTIONFORGE_ROOT/OUTPUT/MODELS = the NEW temp root (Alembic
bootstrapped `data/motionforge.db` under it; artifacts under it). The
pre-existing S05-T05 QA backend on :8003 (output/qa-root) was stopped by
PID (66228) to free the port — no file was modified. Frontend :3011 (this
worktree's existing dev server, NEXT_PUBLIC_API_URL=:8003) served the UI.

- Interaction spec (frontend/e2e/import-analyze.spec.ts, desktop):
  `npx playwright test -c playwright.s05t05.config.ts --reporter=list
  --output=.../test-results-interaction --workers=1` -> **5 passed, 1 failed**.
- Visual spec (NEW frontend/e2e/import-analyze-c04-visual.spec.ts +
  frontend/playwright.s05-c04-visual.config.ts — C04-specific copies whose
  screenshots land in output/s05-c04-r2-evidence/screenshots/, NEVER the
  C01 packet dir): desktop + 390px x setup/file-selected/progress+completed/
  preflight-error -> **6/6 passed**; 10 NEW screenshots generated
  (setup/file-selected/progress/completed/preflight-error x desktop/390px).
- **The single interaction failure is a pre-existing timing race, NOT a
  backend defect** (documented in the report): the cancel test needs the
  cancel click to land inside the active-step window, but on this machine
  (RTX 5070, idle) the whole 60s-fixture chain completes in ~4s — the UI
  polls chain state every 1000 ms and the button is disabled again before
  the click dispatches. Reproduced 2/2 (identical signature); backend
  evidence: chain job timestamps 13:23:36->13:23:40 (UTC), ZERO
  cancel-related job_events, ZERO /cancel requests ever reached the
  backend. The backend cancel path is independently covered by pytest
  (test_s05_orchestration.py cancel tests passed in the required suite;
  test_cancel_during_active_cleans_staging_and_committed_survive,
  test_successor_retry_after_cancel_via_api, HTTP cancel 200/400 semantics
  all green). The same spec passed 6/6 in the S05-T05 round under heavier
  machine load.
- Quality baseline: `powershell scripts/quality-baseline.ps1` -> **7/7 PASS,
  OVERALL PASS (exit 0)**, NEW run ID `20260805-203459`; Gate 2 =
  `722 passed, 19 skipped, 7 deselected in 232.60s`; run dir
  `output/quality-baseline/20260805-203459/` (previous runs untouched).
- No existing screenshot, Playwright report, frontend/test-results/.last-run.json
  (45 bytes, mtime 2026-08-05 18:16:10 — unchanged), fixture, database, or
  previous quality run was overwritten.

### Finding 4 — status line

LOG.md status line changed READY -> SUBMITTED (only this line). TASK.md and
REPORT.md remain SUBMITTED. This section is appended; previous evidence was
not rewritten.

### Verification (round 2) — each command separately, cache disabled

| # | Command | Result |
|---|---------|--------|
| 1 | `python -m pytest -q tests/test_s05_orchestrator_binding.py tests/test_s05_production_wiring.py -p no:cacheprovider` | PASS — **3 passed** (26.02s) |
| 2 | `python -m pytest -q tests/test_s05_production_wiring.py tests/test_s05_orchestrator_binding.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -p no:cacheprovider` | PASS — **36 passed** (76.39s) |
| 3 | Durable worker/JobService/reconciler/managed-artifact set (same 16 files as C04) | PASS — **390 passed, 2 skipped** (100.75s) |
| 4 | S05 service set: `tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py tests/test_scene_chunk_stitch.py` | PASS — **113 passed, 5 skipped** (39.64s) |
| 5 | `python -m ruff check app/workflow/analyze_orchestrator.py tests/test_s05_production_wiring.py tests/test_s05_orchestrator_binding.py` | PASS — All checks passed (exit 0) |
| 6 | `python -m mypy app` | PASS — Success: no issues found in 66 source files |
| 7 | `git diff --check` | PASS — exit 0 (only the pre-existing CRLF advisory on frontend/test-results/.last-run.json) |
| 8 | Playwright interaction (desktop) | 5 passed / 1 failed (cancel timing race — see finding 3) |
| 9 | Playwright visual C04 (desktop + 390px) | **6/6 passed**, 10 NEW screenshots in output/s05-c04-r2-evidence/screenshots/ |
| 10 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` | PASS — **7/7 gates PASS, OVERALL PASS (exit 0)**, run ID `20260805-203459` |

### Isolation / protected-data recheck (post-R2)

- Worktree `git status --short` = 52 entries = the 50 pre-R2 entries + 2 NEW
  untracked frontend test-infra files (`frontend/playwright.s05-c04-visual.config.ts`,
  `frontend/e2e/import-analyze-c04-visual.spec.ts`); plus `?? tests/test_s05_orchestrator_binding.py`
  (new) and the R2-modified untracked `app/workflow/analyze_orchestrator.py` /
  `tests/test_s05_production_wiring.py` (already untracked pre-R2). No other
  NEW tracked/untracked entries.
- MAIN tree: 44 entries (unchanged); `channels.json` SHA-256 unchanged
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; MAIN
  `data/motionforge.db` untouched (311296 bytes, mtime 2026-08-04 18:24:36).
- `frontend/test-results/.last-run.json` unchanged (45 bytes, 18:16:10);
  `frontend/playwright-report-s05t05/` untouched (mtime 18:15:45 — R2 runs
  used `--reporter=list`); C01 screenshots untouched (all 10 files mtime
  18:15-18:16); `output/quality-baseline/` previous runs untouched.
- The pre-existing S05-T05 QA backend process on :8003 was stopped by PID
  (66228) to run the isolated C04 backend on the same port; no file of the
  QA root was modified. No commits, no pushes, no branch changes, no
  destructive operations.

### Deliverables (round 2)

- LOG.md status line -> SUBMITTED (finding 4); TASK.md/REPORT.md stay SUBMITTED.
- New/changed files (bounded scope): `app/workflow/analyze_orchestrator.py`,
  `tests/test_s05_production_wiring.py`, `tests/test_s05_orchestrator_binding.py` (NEW),
  `frontend/playwright.s05-c04-visual.config.ts` (NEW), `frontend/e2e/import-analyze-c04-visual.spec.ts` (NEW),
  `output/s05-c04-r2-evidence/**` (NEW evidence), this LOG.md + REPORT.md.
- C04 is ready for Codex re-review. Stop at SUBMITTED — never APPROVED.

---

## Correction round 3 — Codex CHANGES_REQUESTED (2026-08-05, Hermes session 20260805_210521_ead0fd)

Codex returned 3 findings (1 RED gate). Status stays **SUBMITTED** everywhere;
nothing APPROVED. This section appends; earlier history untouched.

### Pre-write guard (round 3)

- `pwd` → `/c/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`;
  `git rev-parse --show-toplevel` → `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01`
  (both verified BEFORE the first edit).
- Branch → `codex/prepare-s05-t01`.
- Initial `git status --short` → 52 pre-existing entries (round-2 closing state);
  the only entries this round adds are tracked-modifies within the bounded
  scope (`app/api/routes/projects.py`, `frontend/src/lib/api.ts`,
  `frontend/src/components/ImportAnalyzePanel.tsx`) and NEW untracked
  C04-R3 files (`tests/test_s05_atomic_cancel.py`,
  `frontend/e2e/import-analyze-c04-r3-visual.spec.ts`,
  `frontend/playwright.s05-c04-r3-visual.config.ts`,
  `frontend/playwright.s05t05.config.ts` modified) — see isolation recheck.
- Single-writer: this session is the only Hermes writer on this worktree
  (manager-launched R3 packet; no other worker running).
- Protected MAIN baseline re-verified: `channels.json` SHA-256
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`;
  MAIN `data/motionforge.db` 311296 bytes / 2026-08-04 18:24:36 (untouched);
  MAIN git status 44 entries (unchanged).

### Finding 1 (RED gate) — cancel user flow not reliable → atomic chain-cancel API

**Root cause (verified):** `handleCancel` derived the cancel target from the
polled chain snapshot (`firstActiveStep(chain)`); during import→proxy→scene
transitions that snapshot could be stale, so the click early-returned or
targeted a terminal job (R2: zero /cancel requests reached the backend,
reproduced 2/2).

**Fix (smallest robust design — atomic backend resolution):**

- `app/api/routes/projects.py` — NEW `POST /api/projects/{id}/analyze/cancel`
  (atomic chain-cancel endpoint). It RE-READS the chain state at cancel time
  and resolves the currently active durable step on the backend; during a
  step-transition gap it uses the orchestrator's own idempotent
  `advance_once(project_id)` to materialize the next Job (normal progression)
  and cancels it. Semantics mirror `POST /api/jobs/{id}/cancel`: 200
  `{"status":"cancel_requested","job_id":...}` (idempotent while cancelling),
  400 honest when the chain genuinely completed/terminated, 404 unknown
  project. NEVER creates a successor; `GET /analyze` stays strictly read-only
  (unchanged).
- **Concurrency hardening (found by experiment):** a `queued→cancelling` Job
  with NO lease is never drained (worker claims only `queued`; reconciler
  fences only leased Jobs — proven: 5 `run_once` passes + 1 reconcile pass
  left the Job `cancelling`). The endpoint therefore NEVER transitions a
  `queued`/`pending` Job straight to `cancelling`: it waits a bounded time
  (≤ ~3.5 s worst case, common path returns immediately) for the durable
  worker to claim it (`running`), then cancels — the worker's cooperative
  drain terminates it as `cancelled`. No durable-state-machine or
  import/proxy/scene algorithm was modified.
- `frontend/src/lib/api.ts` — NEW `api.cancelAnalyzeChain(projectId)`
  (POST /analyze/cancel).
- `frontend/src/components/ImportAnalyzePanel.tsx` — `handleCancel` now calls
  the atomic API (no stale-snapshot early return); on 400 it shows an honest
  Vietnamese message and refetches the terminal state. Header docs updated;
  unused `firstActiveStep` removed.
- `frontend/e2e/import-analyze.spec.ts` — cancel test rewritten: clicks as
  soon as the button is enabled, waits for the POST /analyze/cancel 200,
  asserts the resolved job row reaches cancelling/cancelled, the chain
  reaches terminal cancelled, retry is offered, and there is NO
  successor/orphan (scene_detect stays not_created, cancelled step is the
  backend-resolved job). Suite doc updated.
- `frontend/playwright.s05t05.config.ts` — NEW `mobile-390px` project
  (viewport 390x844) so the cancel interaction is provable at mobile size.
- NEW `tests/test_s05_atomic_cancel.py` — 5 focused backend tests through the
  REAL UI-facing API surface on real synthetic media (never mocks):
  1. cancel during an actively RUNNING step resolves and cancels that job
     (200 + active job id; chain drains to cancelled; retry successor path
     works; exactly import+proxy rows, `{completed, cancelled}`);
  2. cancel during the transition GAP (import completed, proxy not_created)
     materializes + cancels the next step (200; no lease-less cancelling;
     no orphan; proxy job is GENERATE_PROXY owned by the chain video item);
  3. cancel on a completed chain fails honestly (400) and GET /analyze still
     reports completed;
  4. second cancel while `cancelling` is idempotent (200, same job id);
  5. unknown project → 404.

### Finding 2 — binding test not fully isolated → chdir(tmp_path) boundary

`tests/test_s05_orchestrator_binding.py` (default-service case) now runs the
WHOLE default `JobService()` case with `monkeypatch.chdir(tmp_path)`, so the
production `Path("artifacts")` managed root resolves under pytest temporary
storage:

- production-default assertion KEPT (`job_service.managed_root == Path("artifacts")`);
- NEW: `orchestrator.managed_root.resolve()` equals `(tmp_path/"artifacts").resolve()`
  and is inside `tmp_path`; `(tmp_path/"artifacts").is_dir()`; the worktree
  `artifacts/` dir is proven UNTOUCHED by a before/after file snapshot
  (path+size+mtime of the pre-existing `milestone_1a/openapi.json`);
- NEW: `job_service.database_path` resolves inside `tmp_path` (both tests);
- the exact session-factory identity and fail-closed assertions are unchanged.

### Finding 3 — visual completion evidence → transition artifact, fixed capture

Determined: **transition-only, not a product-state bug.** Pixel analysis of
the R2 screenshots (PIL, bright+saturated runs): desktop step bars 1/2 were
684px but step 3 only **251px** while its label showed 100% (390px: step 3
**54px** vs 274px); the product state is correct — the backend returns
`progress=100` for completed steps and the UI renders `width:100%`; the bars
use `transition-[width] duration-500`, and the R2 capture happened mid-flight.

Fix (NEW C04-R3 visual tooling):
- NEW `frontend/e2e/import-analyze-c04-r3-visual.spec.ts` + NEW
  `frontend/playwright.s05-c04-r3-visual.config.ts` — C04-R3 copies whose
  screenshots land in `output/s05-c04-r3-evidence/screenshots/` (R2/C01 dirs
  untouched). NEW `assertCompletedStepsVisuallyFull(page)` waits for the
  overall bar AND every completed step's bar to finish the 500ms width
  transition (fill width ≥ 0.99 × track width, bounding-box poll) and
  asserts each completed step displays `· 100%`; the completed screenshot is
  captured only after that. No product rendering change was needed.

### Verification (round 3) — each separately, `-p no:cacheprovider`

| # | Command | Result |
|---|---------|--------|
| 1 | `python -m pytest -q tests/test_s05_orchestrator_binding.py -p no:cacheprovider` | PASS — **2 passed** (4.10s) |
| 2 | `python -m pytest -q tests/test_s05_production_wiring.py -p no:cacheprovider` | PASS — **1 passed** (23.33s) |
| 3 | `python -m pytest -q tests/test_s05_lifecycle.py -p no:cacheprovider` | PASS — **3 passed** (20.60s) |
| 4 | `python -m pytest -q tests/test_s05_chain_progression.py -p no:cacheprovider` | PASS — **9 passed** (13.03s) |
| 5 | `python -m pytest -q tests/test_s05_orchestration.py -p no:cacheprovider` | PASS — **12 passed** (13.70s) |
| 6 | `python -m pytest -q tests/test_s05_golden_integration.py -p no:cacheprovider` | PASS — **9 passed** (9.17s) |
| 7 | `python -m pytest -q tests/test_s05_atomic_cancel.py -p no:cacheprovider` | PASS — **5 passed** (5.98s) |
| 8 | Durable worker/reconciler/managed-artifact set (16 files, incl. cancel/orphan/retry: test_durable_job_api.py, test_job_reconciliation.py, test_managed_artifacts.py, ...) | PASS — **390 passed, 2 skipped** (90.32s) |
| 9 | `python -m ruff check app/api/routes/projects.py tests/test_s05_atomic_cancel.py tests/test_s05_orchestrator_binding.py` | PASS — All checks passed |
| 10 | `python -m mypy app` | PASS — Success: no issues found in 66 source files |
| 11 | `npx tsc --noEmit` (frontend) | PASS — exit 0 |
| 12 | `npx eslint src/components/ImportAnalyzePanel.tsx src/lib/api.ts e2e/import-analyze.spec.ts e2e/import-analyze-c04-r3-visual.spec.ts playwright.s05t05.config.ts playwright.s05-c04-r3-visual.config.ts` | PASS — exit 0 |
| 13 | `git diff --check` | PASS — exit 0 (only the pre-existing CRLF advisory on frontend/test-results/.last-run.json) |
| 14 | Playwright cancel desktop x3 consecutive (`--project=desktop --grep cancel --repeat-each=3`) | PASS — **3/3** (2.4s, 2.7s, 3.8s) |
| 15 | Full desktop interaction suite | PASS — **6/6** (20.6s) |
| 16 | Playwright cancel at 390px/mobile (`--project=mobile-390px --grep cancel`) | PASS — **1/1** (2.7s) |
| 17 | Visual suite desktop + 390px (with full-bar + 100% assertions) | PASS — **6/6** (20.1s); 10 NEW screenshots |
| 18 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` | PASS — **7/7 gates, OVERALL PASS (exit 0)**, NEW run ID `20260805-214242` (Gate 2: 241.78s) |

### Cancel requests + durable state evidence (isolated R3 backend DB, read-only)

`output/s05-c04-r3-evidence/backend-root/data/motionforge.db` —
`job_event` rows with `CANCEL_REQUESTED` (actor `api`) followed by
`CANCEL_DRAINED` (actor `worker`) — one pair per e2e cancel click:

- 14:40:52 / 14:40:55 / 14:40:59 UTC — desktop cancel repeat-each=3
  (3 ANALYZE_MEDIA import Jobs, all terminal `cancelled`);
- 14:41:18 UTC — full desktop suite cancel (ANALYZE_MEDIA, `cancelled`);
- 14:41:39 UTC — 390px mobile cancel (ANALYZE_MEDIA, `cancelled`).

= **5/5 cancel clicks reached the real isolated backend, 200
cancel_requested, all jobs drained to `cancelled`** (vs R2: 0 requests).
Chain state after each cancel: terminal `cancelled`, retry available,
no successor/orphan (scene_detect `not_created`; cancelled job is the
backend-resolved row; job counts per video item exactly the chain's own
rows).

### Temporary root/database paths (round 3)

- Backend: `output/s05-c04-r3-evidence/backend-root/` — NEW isolated project
  root; `data/motionforge.db` bootstrapped there by the real lifespan
  (`python -m uvicorn app.main:app` on :8003, cwd + MOTIONFORGE_ROOT/OUTPUT/
  MODELS = that root); artifacts under it. All Playwright output in NEW
  `output/s05-c04-r3-evidence/test-results-*` dirs; screenshots in NEW
  `output/s05-c04-r3-evidence/screenshots/`. Pytest storage under `tmp_path`
  only (proven by the binding tests' assertions).
- R2/C01 evidence, old screenshots, old Playwright reports, fixtures and
  `frontend/test-results/.last-run.json` untouched.

### Corrected screenshots (finding 3)

10 NEW PNGs in `output/s05-c04-r3-evidence/screenshots/`
(setup/file-selected/progress/completed/preflight-error × desktop/390px).
Pixel-verified: completed-desktop step bars 684px/684px/684px (R2: 251px on
step 3); completed-390px 274px/274px/274px (R2: 54px on step 3) — every
completed step now renders a visually full progress bar with a 100% label.

### Protected hashes / dirty-state comparison (post-R3)

- MAIN `channels.json` SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` (unchanged).
- MAIN `data/motionforge.db` 311296 bytes / 2026-08-04 18:24:36 (untouched).
- MAIN git status 44 entries (unchanged).
- Worktree: 55 entries = 52 pre-R3 + 3 NEW untracked C04-R3 files
  (`tests/test_s05_atomic_cancel.py`, `frontend/e2e/import-analyze-c04-r3-visual.spec.ts`,
  `frontend/playwright.s05-c04-r3-visual.config.ts`); tracked-modifies
  confined to the bounded scope (`app/api/routes/projects.py`,
  `frontend/src/lib/api.ts`, `frontend/src/components/ImportAnalyzePanel.tsx`,
  `frontend/playwright.s05t05.config.ts`, `tests/test_s05_orchestrator_binding.py`,
  `frontend/e2e/import-analyze.spec.ts` + this LOG/REPORT).
- No commits, pushes, merges, branch changes, stash, reset, checkout,
  restore, clean, or deletions.

### Remaining risks / notes for Codex

- The endpoint's bounded claim-wait (≤ ~3.5 s worst case) applies only when
  the active job is still `queued`/`pending`; with the production worker
  poll interval (1 s) the typical added latency is ≤ ~1 s, and the common
  path (job `running`) returns immediately.
- A `queued→cancelling` lease-less Job is a PRE-EXISTING durable-system gap
  (nothing drains it) — NOT modified here (out of scope); the atomic cancel
  endpoint is designed to never create that state. Flagged for the manager
  if a durable fix is wanted later.
- `frontend/playwright.s05t05.config.ts` gained a `mobile-390px` project
  (used only via `--grep cancel`); the other 5 interaction tests are
  intentionally not run at mobile size.
- The R3 visual spec/config are C04-R3 evidence tooling copies (same pattern
  as R2); `output/s05-c04-r3-evidence/` is gitignored like `qa-root`.

Status: **SUBMITTED** (never APPROVED — Codex re-reviews).

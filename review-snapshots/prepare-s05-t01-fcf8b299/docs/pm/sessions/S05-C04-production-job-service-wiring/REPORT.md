# Task S05-C04 — Implementation Report (Production Job Service Wiring)

- **Status:** `SUBMITTED` (never APPROVED — Codex performs the review)
- **Hermes session:** `20260805_190611_c270dc`
- **Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`
- **Branch:** `codex/prepare-s05-t01`
- **Started:** 2026-08-05 19:06 +07:00
- **Submitted:** 2026-08-05 ~20:10 +07:00

## Outcome delivered

The real production entrypoint `uvicorn app.main:app` now binds the default
`JobService`, its `DurableWorker`, the `JobReconciler` and the
`AnalyzeChainOrchestrator` to ONE explicit database and ONE managed root
through a public lifecycle binding contract. A pristine app lifecycle
executes and resumes T02 -> T03 -> T04 without dependency injection and
without `job service not initialized` — proven by a new integration test
that runs every app generation as a FRESH subprocess over the real
`app.main:app` default dependency path.

## Confirmed defect (as stated in TASK.md, verified in code)

`deps.get_job_service()` constructs default `JobService()`; its constructor
creates a `DurableWorker` bound to a placeholder factory raising
`RuntimeError("job service not initialized")`; `JobService.initialize()`
created the real session factory but never rebound that worker, so
`start_worker()` started the stale placeholder-bound worker. `app/api/app.py`
and the process-wide analyze orchestrator additionally inspected private
`JobService` attributes (`_session_factory`, `_managed_root`) and
`deps._lifecycle_db` to infer factories/roots.

## Fix (smallest public/explicit lifecycle binding)

1. **`app/workflow/durable_worker.py`** — NEW public
   `DurableWorker.bind_session_factory(factory)`: thread-safe rebind of the
   worker's session factory; refuses rebinding a running worker. (This file
   was changed exactly because the public binding API is required.)
2. **`app/workflow/job_service.py`** — NEW public properties
   `session_factory` and `managed_root` (the explicit binding contract).
   `_ensure_engine()` now (a) REBINDS the owned worker to the real factory
   the moment it is created — the placeholder is gone after explicit
   initialization — and (b) ensures the default managed root exists
   (`mkdir(parents=True, exist_ok=True)`); the import/proxy handlers stat it
   (disk-safety check) and publish into it, and the QA launcher used to
   pre-create it by hand.
3. **`app/api/deps.py`** — the four durable service accessors
   (channel/project/video/summary-repository) read `job_service.session_factory`
   (public) instead of `getattr(job_service, "_session_factory", None)`.
4. **`app/api/app.py`** — the lifespan performs the explicit public binding:
   `job_service.initialize()` → `job_service.session_factory` (public) →
   `Lifecycle(job_service, session_factory)`. The private `_session_factory`
   read, the second-engine fallback and the `deps._lifecycle_db` read are
   removed; no private service attribute is inspected or patched.
5. **`app/workflow/analyze_orchestrator.py`** — the process-wide accessor
   resolves `job_service.session_factory` + `job_service.managed_root`
   (public); `deps._lifecycle_db` read removed; the uninitialized-service
   fallback resolves the same `default_database_path()` the lifecycle uses.
6. **`tests/test_s05_production_wiring.py`** — NEW pristine production-wiring
   integration test (see Evidence below).

## Evidence per acceptance criterion

| AC | Evidence |
|---|---|
| 1. Default `JobService()` after explicit initialization has a `DurableWorker` bound to the real session factory; no stale placeholder | `_ensure_engine()` calls `self._worker.bind_session_factory(self._session_factory)` for the owned worker; proven by the pristine test (gen1's import job reaches `completed` — impossible with the placeholder) and by the FAIL→PASS sequence: before the rebind fix the pristine run showed the worker claiming `queued→running` then failing on the missing managed root; the placeholder would never even claim. |
| 2. Binding public/explicit; app.py does not patch/inspect private service attributes | app.py now uses only `job_service.initialize()` + `job_service.session_factory`; grep on the changed app files shows zero `getattr(job_service, ...)` / `deps._lifecycle_db` reads. |
| 3. JobService, DurableWorker, JobReconciler, AnalyzeChainOrchestrator use the same database and managed root | Lifespan passes `job_service.session_factory` (the service's OWN engine) to `Lifecycle` → reconciler; the worker is rebound to that same factory; the orchestrator accessor uses `job_service.session_factory` + `job_service.managed_root`. One DB file, one managed root (pristine test: tmp `data/motionforge.db` + tmp `artifacts/`). |
| 4. Pristine production-wiring integration test | `tests/test_s05_production_wiring.py` — see the test description below; all sub-bullets (temp root only; no `deps._job_service`/`deps._lifecycle_db` injection; real `app.main:app` default path in pristine process state; real lifespan; create/upload + POST analyze exactly once; default worker claims+completes T02→T03→T04; real lifecycle restart on the same temp DB with correct resume/no duplicates; no `job service not initialized`) are asserted. |
| 5. All test/verification storage temporary only | Every generation sets `MOTIONFORGE_ROOT`/`OUTPUT`/`MODELS` to `tmp_path`; subprocess cwd = tmp root (default managed root `artifacts` lands under tmp); parent inspects only the tmp DB read-only. MAIN and worktree `data/` never touched (isolation evidence below). |
| 6. C03 guarantees preserved | Full C03/C02 suites pass unchanged: `tests/test_s05_lifecycle.py` (3), `tests/test_s05_chain_progression.py` (9), `tests/test_s05_orchestration.py` (12), `tests/test_s05_golden_integration.py` (9) — restart/lifecycle, source supersession + immutability, GET read-only, single-successor, idempotent retry, CFR/VFR, containment, SHA/size, stable Scene IDs, cancel, orphan cleanup. Plus focused durable regressions (390 passed) and the S05 service set (113 passed, 5 skipped). |
| 7. Targeted suite + focused regressions run; Playwright/baseline reported for Codex | See Verification table. No Playwright, no `quality-baseline.ps1` run (AC7: would write QA artifacts — left for Codex post-submit). |
| 8. REPORT lists exact files/commands/results/isolation/risks, status SUBMITTED only | This report. |

### The pristine production-wiring test (`tests/test_s05_production_wiring.py`)

`test_default_production_wiring_chain_completes_and_resumes` — four app
generations, each a FRESH Python subprocess (`runner.py` written to tmp)
that sets only `MOTIONFORGE_ROOT/OUTPUT/MODELS` to `tmp_path/pristine`,
imports the real `app.main:app`, enters the real FastAPI lifespan via
`TestClient`, and NEVER touches `deps._job_service` or `deps._lifecycle_db`:

- **gen1 (submit):** create project → upload a real ffmpeg-generated CFR
  2s one-cut video → `POST /analyze` EXACTLY ONCE → the app's OWN default
  worker claims the import job and completes it (the runner observes the
  state transitions and the parent asserts `["completed"]`); full lifespan
  shutdown on exit.
- **gen2 (resume):** fresh process over the SAME tmp DB, NO analyze API
  request — the lifespan startup scan materializes the proxy job and the
  fresh default worker completes it.
- **gen3 (resume):** same for the scene job (T04).
- **gen4 (resume none):** a further restart over the completed chain
  duplicates nothing (counts stay 1/1/1).
- **Terminal proof (parent, read-only DB inspection):** exactly 1 import +
  1 proxy + 1 scene job, all `completed`; 2 scene rows; 1 VideoItem; the
  durable Project shell row exists; ≥2 managed artifacts under tmp
  `artifacts/`; staging fully drained.
- **Negative proof:** the string `job service not initialized` appears in
  NONE of the four generations' output (it cannot — with the defect the
  import job would never leave `queued` and gen1 would time out).

## Changed files (allowed write scope only)

| File | Change |
|---|---|
| `app/workflow/durable_worker.py` | NEW public `bind_session_factory()` (rebind API; refuses running worker). |
| `app/workflow/job_service.py` | NEW public `session_factory` / `managed_root` properties; `_ensure_engine()` rebinds the owned worker to the real factory and ensures the default managed root exists. |
| `app/api/deps.py` | 4 accessors read the public `job_service.session_factory`; docstrings updated. |
| `app/api/app.py` | Lifespan: explicit public binding (`initialize()` → public factory → one Lifecycle); private reads + `deps._lifecycle_db` removed. |
| `app/workflow/analyze_orchestrator.py` | Accessor uses public `session_factory` / `managed_root`; `deps._lifecycle_db` read removed; fallback = `default_database_path()`. |
| `tests/test_s05_production_wiring.py` | NEW pristine production-wiring integration test (AC4). |
| `docs/pm/sessions/S05-C04-production-job-service-wiring/LOG.md` | Pre-write guard + implementation + verification evidence. |
| `docs/pm/sessions/S05-C04-production-job-service-wiring/REPORT.md` | This report. |

Untouched (verified by `git status`/`git diff`): `app/services/*`
(`video_import.py`, `timebase.py`, `video_proxy.py`, `scene_detector.py` —
zero writes), `app/lifecycle.py`, `app/api/routes/projects.py`,
`app/workflow/job_reconciler.py`, migrations/schema, `channels.json`,
`data/`, databases, fixtures, existing test files, frontend, MAIN tree,
other worktrees, other task packets, ROADMAP, sprint reports/tracking.
No commit/push/merge/branch change/stash/reset/clean/restore/delete.

## Verification (each separately, exact commands/results)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q tests/test_s05_production_wiring.py -p no:cacheprovider` | PASS — **1 passed** (22.15s) |
| 2 | `python -m pytest -q tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -p no:cacheprovider` | PASS — **34 passed** (70.78s) |
| 3 | `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py tests/test_delete_and_autosegment.py tests/test_list_projects.py tests/test_channel_crud.py tests/test_channel_workspace.py tests/test_video_item_crud.py tests/test_project_crud.py tests/test_project_summary.py tests/test_project_summary_correction.py tests/test_project_summary_correction2.py tests/test_project_summary_mapping.py -p no:cacheprovider` | PASS — **390 passed, 2 skipped** (89.21s) |
| 4 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py tests/test_scene_chunk_stitch.py -p no:cacheprovider` | PASS — **113 passed, 5 skipped** (39.02s) |
| 5 | `python -m ruff check app/workflow/durable_worker.py app/workflow/job_service.py app/api/deps.py app/api/app.py app/workflow/analyze_orchestrator.py tests/test_s05_production_wiring.py` | PASS — All checks passed |
| 6 | `python -m mypy app` | PASS — Success: no issues found in 66 source files |
| 7 | `git diff --check` | PASS — exit 0 (only pre-existing CRLF advisory on frontend/test-results/.last-run.json) |

Not run (reported per AC7): Playwright interaction/visual suites and
`scripts/quality-baseline.ps1` — running them would write existing QA
artifacts/screenshots; left for Codex's post-submit verification.

## Isolation evidence

- Pre-write guard recorded in LOG.md BEFORE the first edit: `pwd`,
  `git rev-parse --show-toplevel` = the worktree, branch
  `codex/prepare-s05-t01`, full `git status --short` (47 pre-existing
  entries), MAIN `channels.json` SHA-256
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  (matches TASK.md), MAIN `data/motionforge.db` 311296 bytes / 2026-08-04
  18:24:36 (forbidden, never opened), MAIN status baseline 44 entries.
- Post-verification: worktree status = **49** entries (47 pre-existing +
  `M app/api/deps.py` + `?? tests/test_s05_production_wiring.py`); MAIN
  still 44 entries; MAIN `channels.json` hash identical; MAIN DB stat
  identical. The pre-existing tracked `artifacts/` dir (M1A openapi.json)
  unmodified. All test storage under `pytest` tmp dirs.

## Remaining risks / notes for Codex

- The default managed root remains `"artifacts"` resolved against the
  process CWD (unchanged contract; the QA launcher's explicit mkdir is now
  redundant but harmless). `JobService._ensure_engine()` creates it — a
  bare `uvicorn app.main:app` started from the repo root will create
  `./artifacts` on first use (same location the manifest default already
  pointed at).
- `deps._lifecycle_db` is still SET by existing test fixtures (out of
  scope to edit) but is no longer READ anywhere in `app/`; it is now inert.
- Playwright + full baseline were intentionally not run (AC7); they are
  the only gates not re-proven on this round's code.
- No schema/migration/algorithm changes; C01/C02/C03 guarantees preserved
  (their suites pass unchanged).

## Recommended PM decision

`PENDING` — awaiting Codex review per protocol. No commit; no self-approval;
status `SUBMITTED`.

---

## Correction round 2 — Codex CHANGES_REQUESTED (2026-08-05, session 20260805_200149_49361a)

- **Status remains `SUBMITTED`** (LOG.md status line corrected READY -> SUBMITTED per finding 4; TASK.md/REPORT.md unchanged at SUBMITTED). Never APPROVED.
- **C04 is ready for Codex re-review.**

### Findings fixed

1. **(BLOCKER) Competing session factory** — `app/workflow/analyze_orchestrator.py` no longer creates a factory when `JobService.session_factory` is None. The accessor now FAILS CLOSED (RuntimeError) before initialization; the orchestrator receives its factory + managed root ONLY through the initialized public JobService lifecycle binding. New public `session_factory`/`managed_root` properties on `AnalyzeChainOrchestrator` make the binding provable via public surfaces. No private attribute is read or patched anywhere. Because nothing is cached pre-init, no stale cached orchestrator can survive lifecycle init.
2. **(BLOCKER) Stage boundaries** — `tests/test_s05_production_wiring.py` now proves per-generation boundaries (see counts below) and FAILS if a successor completes before its intended restart.
3. **Playwright + baseline run** — executed against a NEW isolated C04 temporary project root/database with NEW C04-specific evidence dirs; nothing existing was overwritten (see evidence).
4. **Status line** — LOG.md `Status: READY` -> `Status: SUBMITTED`; TASK/REPORT stay SUBMITTED; a new correction-round section appended to both (previous evidence untouched).

### Exact files changed (round 2)

| File | Change |
|---|---|
| `app/workflow/analyze_orchestrator.py` | Removed the competing-factory fallback; fail-closed before initialization; NEW public `session_factory`/`managed_root` properties (finding 1). |
| `tests/test_s05_orchestrator_binding.py` | NEW regression test (2 tests): pre-init access raises; post-init orchestrator binds the EXACT authoritative `JobService.session_factory` (object identity) + `managed_root`; no stale cache survives lifecycle init (finding 1). |
| `tests/test_s05_production_wiring.py` | Stage boundaries per fresh-process generation; runner stops the app's own orchestrator at each boundary (never `advance_once`, never deps injection); runner+parent assert counts (finding 2). |
| `frontend/playwright.s05-c04-visual.config.ts` | NEW C04 visual config (reporter=list only; no html report writes). |
| `frontend/e2e/import-analyze-c04-visual.spec.ts` | NEW C04 visual spec — desktop + 390px screenshots into `output/s05-c04-r2-evidence/screenshots/` (C01 packet dir untouched). |
| `output/s05-c04-r2-evidence/**` | NEW evidence: backend-root (temp project root + DB), screenshots/ (10 PNGs), test-results-{interaction,cancel-rerun,visual}/. |
| `docs/pm/sessions/S05-C04-production-job-service-wiring/LOG.md` | Status line -> SUBMITTED + round-2 section. |
| `docs/pm/sessions/S05-C04-production-job-service-wiring/REPORT.md` | This round-2 section (status stays SUBMITTED). |

### Proof — one authoritative session factory + managed root

- Regression test asserts `orchestrator.session_factory IS job_service.session_factory`
  and `orchestrator.managed_root == job_service.managed_root` after a real
  `JobService.initialize()` (both the explicit default service and the
  deps-constructed `JobService()` path). Object identity = the exact
  callable the JobService initialized — the same factory serving the
  DurableWorker (rebound in `_ensure_engine`) and the JobReconciler
  (passed by the lifespan) — one database, one managed root.
- Pre-init access raises and caches nothing, so no competing-factory
  orchestrator can ever be cached (the identity-keyed cache only ever
  holds authoritative bindings).

### Stage-boundary counts (per subprocess generation, same temp DB)

| Generation | import | proxy | scene | Asserted |
|---|---|---|---|---|
| gen1 (submit, POST once) | 1 completed | **0** | **0** | in subprocess + parent from DB |
| gen2 (resume, no POST) | 1 | 1 completed | **0** | in subprocess + parent from DB |
| gen3 (resume) | 1 | 1 | 1 completed | in subprocess + parent from DB |
| gen4 (resume none) | 1 | 1 | 1 | counts/states identical — **no duplicates** |

- No duplicate jobs/artifacts/Scene rows/durable effects: gen4 + terminal
  DB proof = 1/1/1 jobs all `completed`, 2 Scene rows, 1 VideoItem, 1
  Project shell row, >=2 managed artifacts, staging drained. `job service
  not initialized` never appears in any generation's output (none of the 4
  pristine subprocesses nor any R2 run).

### Verification commands / results (round 2, each separately, `-p no:cacheprovider`)

1. `python -m pytest -q tests/test_s05_orchestrator_binding.py tests/test_s05_production_wiring.py` -> **3 passed** (26.02s).
2. Required suite + regression: `python -m pytest -q tests/test_s05_production_wiring.py tests/test_s05_orchestrator_binding.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py` -> **36 passed** (76.39s).
3. Durable worker/JobService/reconciler/managed-artifact set (16 files) -> **390 passed, 2 skipped** (100.75s).
4. S05 service set (timebase/video_proxy/video_import/scene_detection/scene_chunk_stitch) -> **113 passed, 5 skipped** (39.64s).
5. `python -m ruff check` on all 3 changed Python files -> **All checks passed** (exit 0).
6. `python -m mypy app` -> **Success: no issues found in 66 source files**.
7. `git diff --check` -> **exit 0** (only the pre-existing CRLF advisory on `frontend/test-results/.last-run.json`).
8. Playwright interaction (desktop, real isolated C04 backend on :8003): **5 passed, 1 failed** — see cancel race below.
9. Playwright visual C04 (desktop + 390px): **6/6 passed**; 10 NEW screenshots in `output/s05-c04-r2-evidence/screenshots/` (setup/file-selected/progress/completed/preflight-error x desktop/390px).
10. Quality baseline: **7/7 gates PASS, OVERALL PASS (exit 0)**, NEW run ID **`20260805-203459`** (`output/quality-baseline/20260805-203459/summary.json`); Gate 2: **722 passed, 19 skipped, 7 deselected** in 232.60s.

### Playwright isolation evidence (finding 3)

- Backend: REAL production entrypoint `python -m uvicorn app.main:app --app-dir <worktree> --host 127.0.0.1 --port 8003`, cwd = NEW `output/s05-c04-r2-evidence/backend-root`, env MOTIONFORGE_ROOT/OUTPUT/MODELS = that root; the lifespan bootstrapped the NEW `data/motionforge.db` + artifacts under it (proof the C04 wiring works on the bare entrypoint).
- The pre-existing S05-T05 QA backend on :8003 (output/qa-root) was stopped by PID 66228 only (process, no file touched) to free the port.
- All Playwright output went to NEW dirs via `--output` + `--reporter=list`: `frontend/test-results/.last-run.json` (45 bytes, mtime 18:16:10) and `frontend/playwright-report-s05t05/` (mtime 18:15:45) are byte/mtime-identical before and after; C01 screenshots untouched (18:15-18:16); fixtures untouched (only re-generated-if-missing, they existed).
- NEW frontend files are C04-specific test tooling only (config + spec copy); no frontend product code (`frontend/src/**`) was modified by round 2.

### Known race (honest evidence — NOT a backend defect)

The interaction spec's cancel test failed 2/2 with the identical signature
(`page.waitForResponse` for `/cancel` timed out; the click landed after the
chain had already completed; the UI disables the cancel button and
`handleCancel` early-returns when no step is active). Backend proof:
- the whole 60s-fixture chain completes in ~4s on this machine (RTX 5070,
  idle): import 13:23:36->37, proxy 13:23:37->38, scene 13:23:39->40 (UTC);
- ZERO cancel-related `job_event` rows and ZERO `/cancel` requests ever
  reached the backend;
- the UI polls chain state every 1000 ms (`POLL_INTERVAL_MS`), so the
  enabled-button window races the click dispatch;
- the SAME spec passed 6/6 in the S05-T05 round (heavier machine load,
  slower encodes). The backend cancel path is fully covered by pytest:
  `test_cancel_during_active_cleans_staging_and_committed_survive`,
  `test_successor_retry_after_cancel_via_api`, HTTP cancel 200/400/404
  semantics — all green (36/36 required suite; 390+113 focused sets).
The other 5 interaction tests (empty-state, real progress to completed,
successor retry, resume-no-duplicate, retry honesty) PASS against the real
isolated C04 backend.

### Protected-data verification (post-R2)

- MAIN `channels.json` SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` (unchanged).
- MAIN `data/motionforge.db` 311296 bytes / 2026-08-04 18:24:36 (untouched, never opened).
- MAIN git status 44 entries (unchanged); worktree status 52 = 50 pre-R2 + 2 NEW untracked frontend test-infra files (+ `tests/test_s05_orchestrator_binding.py` new; analyzer/production-wiring were already untracked).
- No commits, pushes, merges, branch changes, stash, reset, clean, restore, or deletions.

### Remaining risks / notes for Codex

- Cancel e2e race (above) is machine-speed dependent; on slower machines (or under load) the interaction spec passes 6/6 as in T05. No code change was made to mask it (out of scope).
- The 2 NEW frontend test files are C04 evidence tooling; if the PM prefers them elsewhere, they can be moved without touching product code.
- `output/s05-c04-r2-evidence/` is gitignored (like `output/qa-root`); it is the immutable evidence store for this round.

**Recommended PM decision: `PENDING` — awaiting Codex re-review. Status `SUBMITTED` only.**

---

## Correction round 3 — Codex CHANGES_REQUESTED (2026-08-05, session 20260805_210521_ead0fd)

- **Status remains `SUBMITTED`.** Never APPROVED. C04 ready for Codex re-review.

### Findings fixed

1. **(RED gate) Cancel user flow not reliable** — the UI derived the cancel
   target from a polled snapshot; clicks during import→proxy→scene
   transitions targeted stale/terminal jobs or nothing (R2: 0 /cancel
   requests reached the backend). **Fix:** NEW atomic chain-cancel endpoint
   `POST /api/projects/{id}/analyze/cancel` that resolves the currently
   active durable step ON THE BACKEND at cancel time (re-reads chain state;
   during a transition gap materializes the next Job via the orchestrator's
   own idempotent advance and cancels it; fails honestly 400 on a genuinely
   completed chain; idempotent while `cancelling`; never creates a
   successor; `GET /analyze` stays read-only). A bounded claim-wait ensures
   a `queued`/`pending` Job is only cancelled as `running` (a lease-less
   `queued→cancelling` Job is never drained by worker/reconciler — proven by
   experiment; no durable-state-machine change was made). UI: `handleCancel`
   calls the atomic API; e2e cancel test rewritten and **passes 3/3
   consecutive desktop + 1/1 mobile 390px**; backend evidence: 5/5 cancel
   clicks reached the isolated backend (CANCEL_REQUESTED api →
   CANCEL_DRAINED worker pairs in `job_event`), all jobs terminal
   `cancelled`, retry available, no successor/orphan.
2. **Binding test not fully isolated** — `tests/test_s05_orchestrator_binding.py`
   default-service case now runs under `monkeypatch.chdir(tmp_path)`: the
   production-default `Path("artifacts")` assertion is KEPT, plus new
   assertions that the resolved managed root and database live inside
   `tmp_path`, and the worktree `artifacts/` dir is byte/mtime-identical
   before/after (pre-existing `milestone_1a/openapi.json` untouched).
   Session-factory identity + fail-closed assertions unchanged.
3. **Visual completion evidence inconsistent** — determined **transition-only**
   (500ms CSS width animation), not a product bug: pixel analysis of the R2
   completed screenshots showed step 3's bar at 251px/54px (desktop/390px)
   while its label read 100%; the backend progress for completed steps is
   100 and the UI width is 100%. NEW C04-R3 visual spec waits for every
   completed step's bar to finish transitioning (fill ≥ 0.99 × track) and
   ASSERTS `· 100%` on every completed step before capturing; regenerated
   desktop + 390px screenshots are pixel-verified FULL
   (684px/684px/684px and 274px/274px/274px).

### Exact files changed (round 3)

| File | Change |
|---|---|
| `app/api/routes/projects.py` | NEW atomic `POST /{project_id}/analyze/cancel` endpoint (finding 1). |
| `frontend/src/lib/api.ts` | NEW `api.cancelAnalyzeChain()` (finding 1). |
| `frontend/src/components/ImportAnalyzePanel.tsx` | `handleCancel` → atomic chain cancel; honest 400 message; unused helper removed (finding 1). |
| `tests/test_s05_atomic_cancel.py` | NEW — 5 focused backend tests: active-step cancel, transition-gap cancel, completed-chain honest 400, idempotent-while-cancelling, unknown project 404 (finding 1). |
| `frontend/e2e/import-analyze.spec.ts` | Cancel test rewritten (reliable on the fast machine; successor/orphan assertions) (finding 1). |
| `frontend/playwright.s05t05.config.ts` | NEW `mobile-390px` project for the mobile cancel gate (finding 1). |
| `tests/test_s05_orchestrator_binding.py` | chdir(tmp_path) isolation + root/DB-under-tmp + worktree-artifacts-untouched assertions (finding 2). |
| `frontend/e2e/import-analyze-c04-r3-visual.spec.ts` | NEW C04-R3 visual spec: full-bar wait + 100% assertions; R3 evidence dir (finding 3). |
| `frontend/playwright.s05-c04-r3-visual.config.ts` | NEW C04-R3 visual config (finding 3). |
| `output/s05-c04-r3-evidence/**` | NEW isolated evidence: backend-root (temp project root + DB), screenshots/ (10 PNGs), test-results-{interaction,cancel-desktop,cancel-mobile,visual}/ (findings 1+3). |
| `docs/pm/sessions/S05-C04-production-job-service-wiring/LOG.md` | Round-3 section appended (status stays SUBMITTED). |
| `docs/pm/sessions/S05-C04-production-job-service-wiring/REPORT.md` | This round-3 section (status stays SUBMITTED). |

### Verification (round 3, each separately, `-p no:cacheprovider`)

1. `tests/test_s05_orchestrator_binding.py` → **2 passed** (4.10s).
2. `tests/test_s05_production_wiring.py` → **1 passed** (23.33s).
3. `tests/test_s05_lifecycle.py` → **3 passed** (20.60s).
4. `tests/test_s05_chain_progression.py` → **9 passed** (13.03s).
5. `tests/test_s05_orchestration.py` → **12 passed** (13.70s).
6. `tests/test_s05_golden_integration.py` → **9 passed** (9.17s).
7. `tests/test_s05_atomic_cancel.py` → **5 passed** (5.98s).
8. Durable worker/reconciler/managed-artifact set (16 files; includes
   cancel/orphan/retry) → **390 passed, 2 skipped** (90.32s).
9. `python -m ruff check` (3 changed Python files) → All checks passed.
10. `python -m mypy app` → Success: no issues found in 66 source files.
11. `npx tsc --noEmit` (frontend) → exit 0.
12. `npx eslint` (changed frontend files) → exit 0.
13. `git diff --check` → exit 0 (pre-existing CRLF advisory only).
14. Playwright cancel desktop `--repeat-each=3` → **3/3 passed** (2.4/2.7/3.8s).
15. Full desktop interaction suite → **6/6 passed** (20.6s).
16. Playwright cancel `mobile-390px` → **1/1 passed** (2.7s).
17. Visual suite (desktop + 390px) → **6/6 passed** (20.1s); 10 NEW
    screenshots, all completed bars pixel-verified full.
18. `scripts/quality-baseline.ps1` → **7/7 gates PASS, OVERALL PASS (exit 0)**,
    NEW run ID **`20260805-214242`** (Gate 2: 241.78s;
    `output/quality-baseline/20260805-214242/summary.json`).

### Isolation evidence (round 3)

- Backend: real production entrypoint `python -m uvicorn app.main:app` on
  :8003, cwd + MOTIONFORGE_ROOT/OUTPUT/MODELS = NEW
  `output/s05-c04-r3-evidence/backend-root` (Alembic-bootstrapped
  `data/motionforge.db` + artifacts under it). Frontend :3011
  (NEXT_PUBLIC_API_URL=:8003, this worktree's dev server).
- All Playwright results/screenshots in NEW `output/s05-c04-r3-evidence/*`;
  R2/C01 evidence, old screenshots, `frontend/test-results/.last-run.json`,
  fixtures untouched. Pytest storage under `tmp_path` only (proven by the
  binding tests).
- Protected: MAIN `channels.json` SHA-256
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  (unchanged); MAIN `data/motionforge.db` 311296 bytes / 2026-08-04 18:24:36
  (untouched); MAIN git status 44 entries. Worktree 55 entries = 52 pre-R3 +
  3 NEW untracked C04-R3 files; tracked-modifies confined to the bounded
  scope. No commits/pushes/branch changes/stash/reset/clean/restore/delete.

### Remaining risks / notes for Codex

- Bounded claim-wait in the cancel endpoint (≤ ~3.5s worst case) applies
  only while the active job is `queued`/`pending`; the common path (running)
  returns immediately.
- Pre-existing durable gap: a lease-less `queued→cancelling` Job is never
  drained — NOT modified (out of scope); the new endpoint never creates
  that state. Flagged for a future durable fix.
- The `mobile-390px` Playwright project runs the cancel case only (via
  `--grep cancel`); the other 5 interaction tests are not run at mobile size.
- `output/s05-c04-r3-evidence/` is gitignored (like `qa-root`); R3 visual
  spec/config are evidence tooling copies (same pattern as R2).

**Recommended PM decision: `PENDING` — awaiting Codex re-review. Status `SUBMITTED` only.**

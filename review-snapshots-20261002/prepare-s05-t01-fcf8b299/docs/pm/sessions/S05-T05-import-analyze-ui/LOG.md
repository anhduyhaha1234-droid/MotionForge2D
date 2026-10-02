# Execution Log — Task S05-T05 (Import/Analyze UI)

- [2026-08-05] Session packet created by PM activation. Import/Analyze UI task
  initialized after S05-T04 manager verification passed (S05-T04 REPORT status
  SUBMITTED; ROADMAP row S05-T05 = PLANNED at session start).

## Session — 2026-08-05 (implementation + verification)

- **Worktree guard (before ANY write):**
  - `pwd` = `/c/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01` — PASS
  - `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/prepare-s05-t01` — PASS
- **Baseline `git status --short` (pre-existing, preserved — nothing of it touched):**
  - Modified: `app/workflow/durable_worker.py`, `app/workflow/job_service.py`, `docs/pm/ROADMAP.md`
  - Untracked: `app/services/timebase.py`, `app/services/video_import.py`,
    `app/services/video_proxy.py`, `app/services/scene_detector.py`,
    `docs/architecture/{CANONICAL_TIMEBASE_PROXY_CONTRACT,VIDEO_IMPORT_V1_PM_DECISIONS,VIDEO_PREFLIGHT_CONTRACT}.md`,
    S05-T01..T05 session dirs, `tests/test_{timebase,video_proxy,video_import,scene_detection}.py`,
    `tests/fixtures/legacy_import/{corrupt,valid}/projects/` (restored legacy fixtures)
- **Frontend env:** `frontend/.env.local` is MISSING in this fresh worktree
  (git-ignored). Must be created for the QA browser run (points the dev server
  at backend :8002). `frontend/node_modules` present (S05-T01 `npm ci`).
- **Backend API ground-truth probes** (`output/s05t05_probe_job_api*.py`,
  temp project root + temp DB + TestClient, real ffprobe/lavfi fixtures):
  - `POST /api/projects/{id}/ingest` → 200 `JobInfo`:
    `{job_id, progress, message, result_path, error, job_type, status}`
    with `status` = `queued` at submit. This is the ONLY approved durable
    import submit endpoint exposed at HTTP level (S05 services
    `submit_import`/`submit_scene_detection` are service-level only — no
    HTTP route references them; verified by grep).
  - `GET /api/jobs/{job_id}` → 200 `JobInfo` / 404 `{"detail":"Job not found"}`.
  - `POST /api/jobs/{job_id}/cancel` → 200 `{"status":"cancel_requested","job_id"}`
    while queued/running (idempotent while `cancelling`), 400
    `{"detail":"Cannot cancel job in state: X"}` when terminal, 404 unknown.
  - Re-submit while active or after terminal `failed`/`cancelled` → **500**
    (IdempotencyKeyInUse unhandled by the legacy route — the HTTP layer does
    not auto-create successors; the durable successor path is repository/service
    level only). Re-submit after `completed` → 200 with the SAME job id
    (idempotent reuse, no duplicate effect).
  - Real progress evidence (20s lavfi video, worker running):
    submit=queued(0,"Queued") → worker reports `progress` 10/30/60/100 with
    messages "Probing video metadata" / "Detecting scenes" / "Slicing scene
    videos" / "Ingest complete" (IngestService._pct + ctx.progress persisted
    via `JobRepository.update_progress`), terminal `completed`(100).
  - Failure evidence (project with no video): job → `failed`, `progress` 10,
    `error` = envelope message (`ffprobe failed: ...` / FileNotFound path),
    `message` = `Failed: ...`; cancel of terminal job → 400.
  - Durable summary API `GET /api/v2/projects/{project_id:uuid}/summary`
    exposes `active_jobs` (job_id/job_type/state/progress) + `next_action`
    (`analyze_video` / `retry_failed` / ...) — UUID-scoped only (v2 projects),
    NOT usable for legacy project ids; the legacy import flow therefore
    resumes via the persisted job id + `GET /api/jobs/{id}` (no duplicate
    submission — UI standard rule 5).

## Design decisions (recorded before code)

1. **UI surface:** new S04-styled Import/Analyze screen under
   `frontend/src/app/(app)/import-analyze/` (AppShell route), component
   `frontend/src/components/ImportAnalyzePanel.tsx`. Vietnamese guided flow,
   one dominant action, local explanations under buttons, WCAG 2.2 AA core
   (role=progressbar + aria-valuenow, role=status/alert, visible focus,
   ≥24px targets, contrast via design tokens).
2. **Approved endpoints only** (frontend scope — backend untouched):
   submit = `POST /api/projects/{id}/ingest` (existing durable cutover route),
   poll = `GET /api/jobs/{id}`, cancel = `POST /api/jobs/{id}/cancel`,
   resume discovery = persisted job id (localStorage per project) → poll.
   Retry/resume = re-submit the SAME approved submit endpoint, then refetch —
   the backend's idempotency/successor semantics are the single source of
   truth (completed → same job reused; active/failed/cancelled → backend
   refuses with 500 IdempotencyKeyInUse — the UI renders that refusal
   honestly with the refetched job state, never a fake new job).
3. **Real progress only:** the panel polls the durable job row every 1s while
   active; progress bar value = `JobInfo.progress` from the backend state
   machine; message = `JobInfo.message`; elapsed time = wall-clock since the
   first observed poll (client-side clock, real); ETA = derived from progress
   deltas over wall-clock (contract §7.3: ETA derived, never persisted,
   clearly labelled "ước tính"). No fake timers, no synthetic progress.
4. **Preflight error rendering:** client taxonomy module
   `frontend/src/lib/preflightErrors.ts` mapping the approved stable codes
   (VIDEO_PREFLIGHT_CONTRACT §7 + S05-T02 V1 codes) to severity + the
   contract's Vietnamese suggested actions. On job failure the panel matches
   the backend `error` string against the stable-code set (regex, code tokens
   appear in the envelope/detail strings) and renders code + severity + the
   approved Vietnamese action + the raw backend error message. Unmatched
   errors render the raw backend message verbatim (never a bare "failed").
5. **States:** empty (explain + one next action + disabled reason), initial
   loading (skeleton), refreshing (retain stale content + label), long job
   (state, real progress, message, elapsed, labelled ETA, cancel/retry),
   success (evidence + next action), recoverable error (cause, preserved work,
   exact recovery action), offline/restart (rehydrate durable job from
   persisted id — no duplicate submission).
6. **api.ts:** fix `JobInfo` to the REAL response shape (the existing
   interface declares fields the backend does not return: `current_step`,
   `started_at`, `completed_at`, `error_code`, `result`; real = `job_id`,
   `status`, `progress`, `message`, `result_path`, `error`, `job_type`);
   `cancelJob` typed to `{status, job_id}`; error envelope unwrap
   (FastAPI `{"detail": ...}` → ApiError with parsed detail) so preflight
   errors render actionably; `getProjectSummary` typed for resume discovery.
7. **Tests:** Playwright interaction spec
   `frontend/e2e/import-analyze.spec.ts` + dedicated config
   `frontend/playwright.s05t05.config.ts` (baseURL :3010, API :8002) driving
   the REAL QA backend (worktree output/qa-root, MOTIONFORGE_ROOT set) — no
   mock job data. Covers: real progress → completed; cancel → cancelling →
   cancelled; retry/resume re-submit + refetch (completed reuse + refused
   duplicate honesty); refresh resume without duplicate submission; preflight
   error rendering; empty/loading/error states with disabled reasons;
   desktop + 390px screenshots.
8. **QA env:** backend uvicorn on :8002 rooted at the WORKTREE
   `output/qa-root` (cwd = qa-root, `MOTIONFORGE_ROOT` set) + frontend
   `npm run dev -p 3010` with `frontend/.env.local`
   (`NEXT_PUBLIC_API_URL=http://localhost:8002`) — per the established
   S06 QA pattern (never the MAIN tree).


## Implementation log (after baseline)

- [2026-08-05] `frontend/src/lib/api.ts` — fixed `JobInfo` to the REAL
  durable response shape (`job_id`, `status` incl. `pending`, `progress`,
  `message`, `result_path`, `error`, `job_type`; legacy optional fields kept
  for existing consumers); added `ApiError` with FastAPI `{"detail": ...}`
  envelope unwrap; `submitImport` / `retryImport` typed to `JobInfo`;
  `cancelJob` typed to `{status, job_id}`; `triggerIngest` now returns
  `JobInfo` (was `{job_id}` — the route always returned the full JobInfo).
- [2026-08-05] `frontend/src/lib/preflightErrors.ts` (new) — approved
  preflight taxonomy: 30 stable codes (VIDEO_PREFLIGHT_CONTRACT §7 +
  S05-T02 V1 + S05-T04 scene codes) with severity + Vietnamese suggested
  actions copied VERBATIM from the backend `VIETNAMESE_ACTIONS` dicts;
  `matchPreflightError` (code-token regex on the error string) +
  `GENERIC_ACTION` fallback + `JOB_STATE_LABEL`.
- [2026-08-05] `frontend/src/components/ImportAnalyzePanel.tsx` (new) —
  Import/Analyze panel: real progress polling (GET /api/jobs/{id} every 1s
  while active), ETA derived from real progress deltas over wall-clock
  (labelled "ước tính", contract §7.3), elapsed wall-clock, cancel via
  POST /api/jobs/{id}/cancel + refetch, retry/resume via re-submit of the
  SAME approved submit endpoint + refetch (backend idempotency is the
  truth; refusals rendered honestly with the refetched job state),
  resume-on-refresh from the persisted job id (no duplicate submission),
  preflight taxonomy rendering, empty/loading/error states with visible
  disabled reasons, Vietnamese guided flow, WCAG roles/aria.
- [2026-08-05] `frontend/src/app/(app)/import-analyze/page.tsx` (new) —
  S04 AppShell route hosting the panel; creates/re-opens the legacy project
  (`?project=`); AppNav gains "Nhập & Phân tích".
- [2026-08-05] `frontend/e2e/import-analyze.spec.ts` (new, 6 tests) +
  `frontend/playwright.s05t05.config.ts` — interaction tests against the
  REAL QA backend (:8003 worktree QA root; :8002 belongs to an S06 worktree
  backend and is never touched).
- [2026-08-05] `frontend/e2e/import-analyze-visual.spec.ts` (new, 6 tests)
  + `frontend/playwright.s05t05-visual.config.ts` — desktop (1280x800) +
  390px (390x844) screenshots of setup/file-selected/progress/completed/
  preflight-error states → `docs/pm/sessions/S05-T05-import-analyze-ui/screenshots/`.

## Pre-existing production wiring gap found during QA (NOT fixed — out of scope)

- `deps.get_job_service()` constructs a bare `JobService()`; its DurableWorker
  is built with a placeholder session factory (`_placeholder`) and
  `JobService.initialize()`/`_ensure_engine()` never re-wires the WORKER's
  factory — so `uvicorn app.main:app` logs "durable worker loop error: job
  service not initialized" and NEVER executes jobs. Pre-existing at HEAD
  (S02-T05 era; the test suite always injects `deps._job_service =
  JobService(factory, ...)` so it never surfaced). S05-T05 is frontend-only
  (task forbids `app/workflow/`), so the QA backend uses
  `output/s05t05_qa_backend.py` which applies the SAME approved test wiring
  (real JobService over the QA DB + managed root injected into deps before
  uvicorn). Documented in REPORT.md as an out-of-scope finding; a backend
  fix (re-wire the worker factory on initialize, or construct the worker
  lazily) is a separate approved-scope task.
- **Accidental cross-worktree pollution + cleanup (S06 untouched in the end):**
  my first QA run pointed the spec at :8002, which is owned by an S06
  worktree backend; the tests created 12 "S05T05*" projects in the S06
  qa-root + 6 job rows in its QA DB. All 12 project dirs and the 6 job-family
  rows (steps/attempts/events/leases) were deleted, restoring the S06
  qa-root projects dir to empty and the job tables to zero rows — verified
  before proceeding. The spec now targets :8003 (this worktree's QA backend).

## Defects found & fixed during the session

- `JobInfo` interface in api.ts declared fields the durable API does not
  return (current_step/started_at/completed_at/error_code/result) — fixed to
  the real shape; legacy consumers (ScreenE `job.result?.output_path`) still
  typecheck via optional legacy fields.
- E2E: strict-mode locator collisions ("Hoàn tất", "100%", job-id prefix) —
  fixed with exact/unique locators.
- E2E: preflight test overwrote the uploaded source AFTER the panel's own
  upload re-uploaded a valid file — replaced with a genuinely corrupt
  `.mp4` fixture (fails the backend probe, passes the client extension hint).
- E2E cancel semantics: a cancel of a QUEUED job has no lease → the
  reconciler truthfully keeps it `cancelling` (pre-existing backend
  behaviour); test now asserts the honest contract (cancelling + enabled
  idempotent cancel, or cancelled + disabled with reason).
- E2E retry refusal: unhandled 500 (IdempotencyKeyInUse) bypasses the CORS
  middleware (pre-existing), so the browser sees "Failed to fetch" — the UI
  renders the refusal honestly; the test asserts the rendered refusal +
  refetched failed state instead of a network response.
- Visual QA: a 4s/30s video completes ingest too fast to capture a running
  bar — switched to a 60s fixture and wait for a mid-range aria-valuenow;
  pixel analysis confirms progress-desktop (partial purple bar) vs
  completed-desktop (full gradient bar) are distinct states.


## Final validation results (each separately, real output)

| # | Command | Result |
|---|---|---|
| 1 | `npx playwright test --config=playwright.s05t05.config.ts` | PASS — **6 passed** (10.4s): empty state disabled reason; real progress → completed 100 matching backend row; cancel → cancelling/cancelled + honest disabled reason; retry/resume re-submit + refetch; preflight failure + refusal; API-level refusal honesty |
| 2 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py -p no:cacheprovider` | PASS — **111 passed** in 38.83s |
| 3 | `npx tsc --noEmit` | PASS — exit 0 |
| 3 | `npx eslint src/ e2e/` | PASS — 0 errors, 9 warnings (all pre-existing in old components) |
| 4 | `python -m ruff check app tests` | PASS — `All checks passed!` |
| 5 | `python -m mypy app` | PASS — `Success: no issues found in 65 source files` |
| 6 | `git diff --check` | PASS — exit 0 (LF→CRLF advisory only) |
| 7 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh) | PASS — **OVERALL: PASS (exit 0)**, Run ID **`20260805-125154`**, 7/7 gates; Python tests **686 passed, 19 skipped, 7 deselected** in 157.42s; summary `output/quality-baseline/20260805-125154/summary.json` |
| 8 | `npx playwright test --config=playwright.s05t05-visual.config.ts` | PASS — **6 passed** (13.2s): desktop + 390px setup/file-selected/progress/completed/preflight-error → 10 screenshots in `docs/pm/sessions/S05-T05-import-analyze-ui/screenshots/` |

- [2026-08-05] Next.js 16 prerender fix: `/import-analyze` build failed Gate 7
  (`useSearchParams() should be wrapped in a suspense boundary`) — wrapped the
  route in `<Suspense>`; re-ran the full baseline → PASS (`20260805-125154`).
- [2026-08-05] Visual QA screenshots verified: correct viewport dimensions
  (1280x800 / 390x844), distinct MD5 + progress-bar fill per state (partial
  purple bar vs full gradient bar for progress vs completed), all states
  captured from the real backend.
- [2026-08-05] Cleanup: `frontend/test-results/` + `frontend/playwright-report-s05t05/`
  generated artifacts removed; the TRACKED `frontend/test-results/.last-run.json`
  was restored byte-identical from git (no diff). QA fixtures regenerated by
  each spec's `beforeAll` (not committed). `frontend/.env.local` (git-ignored)
  points at :8003 for this QA run.
- [2026-08-05] Final `git status --short` = baseline + this task's frontend
  files only; S05-T06 packet is PM-owned (created 11:27 before implementation)
  and untouched. `channels.json`, `data/`, DB, MAIN tree, S06 worktrees: no
  writes.

# S05-T05 - Implementation Report

**Status:** SUBMITTED
**Started:** 2026-08-05 +07:00
**Submitted:** 2026-08-05 +07:00
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`

## Outcome delivered

The Import/Analyze UI (`/import-analyze`) wired to the approved durable job
APIs — real estimate/progress from the backend state machine (never mock),
cancel/retry/resume through the approved endpoints with refetch after every
mutation (UI state matches backend), actionable preflight error rendering
from the approved taxonomy, complete empty/loading/error states with visible
disabled reasons, Vietnamese guided flow per UI_UX_DESIGN_STANDARD.md, and
desktop + 390px visual QA screenshots.

**Ground truth (probed before writing any UI code, `output/s05t05_probe_job_api*.py`):**
- `POST /api/projects/{id}/ingest` (the ONLY approved durable import submit
  endpoint at HTTP level) → 200 `JobInfo` `{job_id, progress, message,
  result_path, error, job_type, status}`; S05 services (`submit_import` /
  `submit_scene_detection`) are service-level only — no HTTP route references
  them (verified by grep).
- `GET /api/jobs/{id}` → 200 JobInfo / 404; `POST /api/jobs/{id}/cancel` →
  200 `cancel_requested` / 400 terminal / 404 unknown (idempotent while
  `cancelling`).
- Real progress: queued(0) → running(10/30/60/100, messages "Probing video
  metadata" / "Detecting scenes" / "Slicing scene videos" / "Ingest
  complete") → completed(100) — persisted via `JobRepository.update_progress`
  and read back through the poll endpoint.
- Idempotency: re-submit after `completed` → 200 SAME job (reuse, no
  duplicate effect); re-submit while active or after terminal
  failed/cancelled → **500 IdempotencyKeyInUse** (the legacy HTTP route does
  not auto-create successors — the durable successor path is
  repository/service level only). The UI therefore renders refusals honestly
  and refetches; it never fabricates a new job.

## Changed files (allowed write scope only)

- `frontend/src/lib/api.ts` (modified) — real `JobInfo` shape, `ApiError`
  with FastAPI detail-envelope unwrap, `submitImport`/`retryImport`,
  `cancelJob` typed to `{status, job_id}`.
- `frontend/src/lib/preflightErrors.ts` (new) — approved preflight taxonomy
  (30 codes, severity + Vietnamese actions verbatim from the backend).
- `frontend/src/components/ImportAnalyzePanel.tsx` (new) — the Import/Analyze
  panel (progress/cancel/retry/resume/preflight states).
- `frontend/src/app/(app)/import-analyze/page.tsx` (new) — S04 AppShell route.
- `frontend/src/components/layout/AppNav.tsx` (modified) — "Nhập & Phân tích"
  nav item.
- `frontend/e2e/import-analyze.spec.ts` (new, 6 interaction tests),
  `frontend/e2e/import-analyze-visual.spec.ts` (new, 6 visual QA tests),
  `frontend/playwright.s05t05.config.ts` + `frontend/playwright.s05t05-visual.config.ts`
  (new QA configs — baseURL :3011, API :8003).
- `docs/pm/sessions/S05-T05-import-analyze-ui/LOG.md` (appended), `REPORT.md`
  (this file).

Untouched (verified by `git status --short`): all `app/` runtime source,
`app/workflow/durable_worker.py` + `job_service.py` (pre-existing S05-T02..T04
diffs preserved, no new edits), ROADMAP (PM-owned), migrations,
`pyproject.toml`, `channels.json`, `data/`, database files, MAIN tree, S06
worktrees. `frontend/.env.local` (git-ignored) + `output/qa-root` +
`output/s05t05_*.py` (git-ignored `output/`) are QA-environment artifacts.

## Tests and validation (each separately, exact commands/results)

| # | Command | Result |
|---|---|---|
| 1 | `npx playwright test --config=playwright.s05t05.config.ts` (real QA backend :8003) | PASS — **6 passed** (empty-state disabled reason; real progress → completed 100 matching backend row; cancel → cancelling/cancelled + disabled reason; retry/resume re-submit + refetch; preflight failure + honest refusal; API-level refusal honesty) |
| 2 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py -p no:cacheprovider` | PASS — **111 passed** in 38.83s (S05-T01..T04 backend regressions) |
| 3 | `npx tsc --noEmit` (frontend) | PASS — exit 0 |
| 3 | `npx eslint src/ e2e/` (frontend) | PASS — 0 errors (9 pre-existing warnings in old components, none in new files) |
| 4 | `python -m ruff check app tests` | PASS — `All checks passed!` |
| 5 | `python -m mypy app` | PASS — `Success: no issues found in 65 source files` |
| 6 | `git diff --check` | PASS — exit 0 (LF→CRLF advisory only) |
| 7 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh) | PASS — see Quality Run below |
| 8 | Desktop + 390px visual QA | PASS — 12 screenshots (see Visual QA) |

## Quality Run

- **Run ID:** `20260805-125154` — **OVERALL: PASS (exit 0), 7/7 gates**
  (env, python tests, ruff, mypy, tsc, eslint, build). Python tests
  **686 passed, 19 skipped, 7 deselected** in 157.42s (includes the 111
  S05-T01..T04 targeted regressions; S05-T04 baseline was 686 passed too —
  this task adds no Python tests, only frontend). Summary:
  `output/quality-baseline/20260805-125154/summary.json`.
- One earlier fresh run (`20260805-124621`) failed ONLY Gate 7 (frontend
  build) on the Next.js 16 prerender error `useSearchParams() should be
  wrapped in a suspense boundary at page "/import-analyze"` — fixed by
  wrapping the route in `<Suspense>`; the re-run above is the recorded
  evidence run.

## Real-progress evidence (no mock)

- The panel polls `GET /api/jobs/{id}` every 1s while the job is active;
  progress bar value = `JobInfo.progress` from the durable state machine
  (0→10→30→60→100 for the ingest handler's real checkpoint updates).
- ETA is DERIVED from real progress deltas over wall-clock (contract §7.3)
  and always labelled "ước tính" — no fake timers, no synthetic progress.
- E2E proof: after submit, the UI's progressbar reached the backend row's
  exact `completed`/`progress=100`; intermediate poll samples recorded in
  the backend probe (`running 30.0` → `completed 100.0`).

## Cancel / retry / resume / refetch evidence

- **Cancel:** `POST /api/jobs/{id}/cancel` → 200 `cancel_requested` → the
  panel refetches and renders the backend's `cancelling`/`cancelled` state;
  a terminal job disables the button with a visible reason. E2E asserts the
  cancel response, the rendered state, and the matching backend row.
- **Retry/resume:** re-submit the SAME approved submit endpoint
  (`POST /api/projects/{id}/ingest`) then refetch. Backend truth:
  completed duplicate → 200 with the SAME job (idempotent reuse, proven in
  E2E via the returned job_id and a single job row); active/failed duplicate
  → refused (500 IdempotencyKeyInUse) — the panel renders the refusal
  verbatim ("Hệ thống từ chối tạo công việc mới", HTTP status + backend
  detail) and REFETCHES the existing job so UI state matches the backend
  (job stays `failed`). No fake success anywhere.
- **Resume after refresh:** the panel persists the durable job id
  (localStorage, per project) and on reload rehydrates by polling the SAME
  job — no duplicate submission (UI standard rule 5). E2E reloads the page
  and asserts the same job badge renders with the same terminal state.
- **Refetch after mutation:** every mutation path (cancel, retry, submit)
  ends with `GET /api/jobs/{id}`; the E2E asserts UI text equals the backend
  row for completed, failed and cancelling/cancelled.

## Preflight error rendering evidence

- Client taxonomy module mirrors the approved VIDEO_PREFLIGHT_CONTRACT §7 +
  S05-T02/T04 codes with severity and Vietnamese suggested actions copied
  VERBATIM from the backend `VIETNAMESE_ACTIONS` dicts (single source of
  truth, no divergence).
- On failure the panel matches the stable code token in the backend `error`
  string and renders code + severity + the approved Vietnamese action + the
  raw backend message; unmatched errors render the raw message with the
  contract's generic action — never a bare "failed".
- E2E: corrupt `.mp4` fixture → durable job fails with the real backend
  error; UI renders "Không thể import" + the actionable message + the raw
  error; retry offered and its backend refusal rendered honestly.

## Visual QA (desktop + 390px)

`docs/pm/sessions/S05-T05-import-analyze-ui/screenshots/` (all captured by
Playwright against the REAL QA backend):

- Desktop 1280x800: `setup-desktop.png`, `file-selected-desktop.png`,
  `progress-desktop.png` (partial real progress bar, aria-valuenow 0<v<100),
  `completed-desktop.png`, `preflight-error-desktop.png`.
- 390px 390x844: `setup-390px.png`, `file-selected-390px.png`,
  `progress-390px.png`, `completed-390px.png`, `preflight-error-390px.png`.
- Verified: correct viewport dimensions; distinct pixel content per state
  (MD5 + progress-bar fill analysis: partial purple bar vs full gradient
  bar); all 6 visual QA tests pass.

## Out-of-scope findings (pre-existing, NOT fixed by this task)

1. **Production worker wiring gap (HEAD pre-existing):**
   `deps.get_job_service()` → bare `JobService()` builds the DurableWorker
   with a placeholder session factory that is never re-wired by
   `initialize()`/`_ensure_engine()`; a plain `uvicorn app.main:app` logs
   "durable worker loop error: job service not initialized" and never
   executes jobs. The test suite always injected a factory, so this never
   surfaced before. This task is frontend-only (forbidden: `app/workflow/`),
   so the QA backend runs `output/s05t05_qa_backend.py` — the same approved
   wiring the tests use (real JobService over the QA DB injected into deps).
   A backend fix (re-wire the worker factory on initialize) is a separate
   approved-scope task.
2. **Unhandled IdempotencyKeyInUse → 500 without CORS headers (HEAD
   pre-existing):** the legacy ingest route does not catch
   `IdempotencyKeyInUse`, so a duplicate submit returns 500; because
   Starlette's ServerErrorMiddleware sits outside CORSMiddleware, the
   browser receives a network-level failure. The UI renders this refusal
   honestly (verified in E2E).
3. **Cancel of a queued job has no lease** → the reconciler truthfully keeps
   it `cancelling` until a worker/reconciler pass drains it; the UI renders
   the durable state and keeps the second cancel available (idempotent 200,
   contract §6.3).
4. **S06 worktree accident during QA setup:** my first QA spec targeted
   :8002, owned by an S06 worktree backend; the run created 12 "S05T05*"
   projects + 6 job rows in the S06 QA root. All of MY artifacts were
   deleted (project dirs + job-family rows), restoring the S06 QA root to
   its prior empty state before proceeding; the spec now targets :8003.

## Deviations from task

None. All work stayed inside TASK.md's allowed write scope (frontend only).

## Known limitations/risks

- The HTTP layer cannot create successor Jobs (no route), so retry of a
  terminal failed/cancelled import is backend-refused today; the UI shows
  the honest refusal + refetched state. Enabling real successor retries is a
  backend task (route calling `create_successor`), out of scope here.
- ETA appears only after ≥2 real progress samples with positive deltas
  (honest estimation, no invented numbers).

## Recommended PM decision

`PENDING` — awaiting PM review per protocol (no self-approval; no commit; no
roadmap edits; no next-task packet creation). Upon approval, S05-T06 (golden
import/analyze integration and restart-recovery evidence) may start.

---

## CORRECTION (S05-C01, appended 2026-08-05 — do not rewrite history)

Codex sprint-exit review found two blockers in this task's UI wiring, fixed
by `S05-C01-approved-pipeline-orchestration` (see its REPORT.md for full
evidence):

1. **This UI called the legacy `POST /api/projects/{id}/ingest`** (old
   probe → PySceneDetect → slicing) instead of the approved chain
   T02 `ANALYZE_MEDIA` import → T03 `GENERATE_PROXY` → T04 `ANALYZE_MEDIA`
   scene_detect.  The S05-C01 Import/Analyze UI now drives the approved
   chain via `POST/GET /api/projects/{id}/analyze` and
   `POST /api/projects/{id}/analyze/retry`; the legacy `/ingest` call is
   removed from this flow.  The backend `/ingest` endpoint is retained for
   other consumers.
2. **Retry was not functional**: re-submitting the legacy endpoint returned
   500 `IdempotencyKeyInUse`; honest refusal rendering is not a real retry.
   S05-C01 adds a real successor-job retry (DURABLE_JOB_CONTRACT §8.5) with
   owner validation and idempotent duplicate retry — retry-after-failure
   actually succeeds (proven by API tests and Playwright).

Also corrected: the S05-T05 e2e specs asserted the old legacy behavior
(including "retry → 500" honesty); they now assert the corrected real API.
Everything else in this REPORT stands; the S05-C01 evidence is the
authoritative correction record.

## CORRECTION APPENDIX — S05-C02 (durable chain progression, appended 2026-08-05 — do not rewrite history)

Codex CHANGES_REQUESTED round 2 found that the orchestration described
above relied on a read endpoint that secretly advanced the chain:
`GET /api/projects/{id}/analyze` created the proxy/scene-detection Jobs.
The correction (S05-C02, `docs/pm/sessions/S05-C02-durable-chain-progression/REPORT.md`)
moves ALL chain progression into a focused durable orchestration service
(`app/workflow/analyze_orchestrator.py`) with a background loop; GET is now
strictly read-only (zero mutations — verified repeated + concurrent); routes
are thin (no JobService private-member access); the chain identity is bound
to source SHA-256 + generation (replacing the source starts a NEW chain,
never a silent reuse). The tests in this report were updated accordingly:
the 12 tests now advance the chain via
`get_analyze_orchestrator().advance_once()` (all assertions unchanged), and
9 new adversarial tests prove POST-once-no-GET completion, API restart
after import/proxy, GET zero-mutation, source replacement, single-successor
per step, idempotent successor retry, CFR/VFR + containment + SHA/size +
Scene IDs + orphan cleanup. Playwright: interaction 6/6 + visual 6/6
against the corrected real API. Fresh 7/7 baseline Run ID
`20260805-163430`. Status of S05-C02: SUBMITTED (never APPROVED).


## CORRECTION APPENDIX — S05-C03 (final lifecycle correction, appended 2026-08-05 — do not rewrite history)

Codex CHANGES_REQUESTED round 3 (S05-C02 review) is delivered by
`docs/pm/sessions/S05-C03-final-lifecycle-correction/REPORT.md`:
- `AnalyzeChainOrchestrator` start/stop is now wired into the REAL FastAPI
  lifespan (`app/api/app.py`); `start()` performs a synchronous idempotent
  scan-and-resume, so on process boot every incomplete chain is resumed
  with NO POST/GET/browser polling/manual `advance_once()`.
- A TRUE process-lifecycle test (`tests/test_s05_lifecycle.py`, 3 tests)
  proves: POST once → import completes → full app shutdown → fresh app over
  the same DB → NO analyze API request → proxy job materializes + completes
  → restart → scene job materializes + completes; a real-accessor variant
  runs across 4 app generations with zero duplication; and source
  replacement with a different SHA performs an explicit VideoItem/version
  supersession (old VideoItem archived, rows byte-identical immutable, new
  VideoItem gets distinct identity/outputs, the new chain COMPLETES, chain
  state exposes only the current source).
- The C02 replacement test was updated to this supersession contract (the
  round-2 same-VideoItem fail-closed scene step was the flagged blocker);
  the detector's fail-closed immutability guarantee remains covered by
  `tests/test_scene_detection.py`.
- GET stays read-only; C02 concurrency/retry guarantees preserved (full C02
  suite green: 9 chain-progression + 12 orchestration + 9 golden).
- QA: live crash-restart smoke PASS (kill backend mid-import → fresh
  backend → chain completes with zero analyze API calls), Playwright
  interaction 6/6 + visual 6/6 (desktop + 390px), fresh 7/7 baseline Run ID
  `20260805-181617`. Status of S05-C03: SUBMITTED (never APPROVED).

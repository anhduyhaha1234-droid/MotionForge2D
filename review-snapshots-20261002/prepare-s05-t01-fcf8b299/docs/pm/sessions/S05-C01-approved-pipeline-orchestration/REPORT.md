# Task S05-C01 — Implementation Report

- **Status:** `SUBMITTED` (never APPROVED — Codex performs the sprint-exit review)
- **Hermes session:** `20260805_142011_b043cd`
- **Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`
- **Started:** 2026-08-05 14:20 +07:00
- **Submitted:** 2026-08-05 16:15 +07:00

## Outcome delivered

A UI-facing API orchestration path drives the REAL approved durable chain
**T02 `ANALYZE_MEDIA` import → T03 `GENERATE_PROXY` → T04 `ANALYZE_MEDIA`
scene_detect** (reusing the S05-T04 `ANALYZE_MEDIA` dispatcher and the S05-T03
`GENERATE_PROXY` registration — both registered by the API `JobService`,
never rewritten), exposes **backend-owned chain state** (active step, real
checkpoint progress, terminal states) to the UI, and provides a real
**successor-job retry** path for failed/cancelled work with owner validation +
idempotency. The Import/Analyze UI no longer calls the legacy
`POST /api/projects/{id}/ingest`; it renders real chain state, cancels the
active step, retries via a successor Job, resumes from the backend and
refetches after every mutation. **No mocked progress, no mocked job state,
no fake data.**

## Design (backend-owned chain, poll-driven materialization)

The proxy/scene-detect Jobs can only be created once their predecessor's
input artifact durably exists (`submit_proxy`/`submit_scene_detection`
validate the artifact at submit time — by contract).  Therefore ONE
submission (`POST /api/projects/{id}/analyze`) creates the `ANALYZE_MEDIA`
import Job (S05-T02) and returns the chain; the chain-state endpoint
(`GET /api/projects/{id}/analyze`) **advances the chain** — when a
predecessor is terminal-completed and the next Job does not exist yet, it is
created there (idempotent via the repository's owner-scoped idempotency
keys; concurrent polls are safe — the loser receives
`IdempotencyKeyInUse` and is ignored).  The UI's 1s poll loop therefore
drives T02→T03→T04 without further user action, exactly like a real
pipeline.  Every value in the chain response is read from the durable Job
rows (real checkpoints); `progress` of a terminal-completed step is 100 by
the state machine's own meaning (§4.5-1), everything else reports the
durable checkpoint value.  A failed/cancelled step is **never**
auto-recreated; retry is explicit (`POST /api/projects/{id}/analyze/retry`),
which creates a **successor Job** (§8.5) with owner validation (only the
project's own chain Jobs) and idempotency (duplicate retry reuses the
already-created successor — never a 500 `IdempotencyKeyInUse` without a
path).  The durable Project Shell rows (Workspace→Project→VideoItem) are
materialized on demand by the endpoint so the approved services' ownership
gate works for legacy projects.  The legacy `/ingest` endpoint itself is
retained (other consumers depend on it — verified by the durable job API
regression suite); only the Import/Analyze UI stopped using it.

## Changed files (allowed write scope only)

| File | Change |
|---|---|
| `app/api/routes/projects.py` | NEW orchestration: `POST/GET /api/projects/{id}/analyze`, `POST /api/projects/{id}/analyze/retry` + chain helpers (`_ensure_durable_shell`, `_chain_jobs`, `_chain_response`, `_advance_chain`, `_retry_chain_job`); ~630 lines. Legacy `/ingest` endpoint untouched. |
| `frontend/src/lib/api.ts` | Removed `submitImport`/`retryImport` (legacy `/ingest`); added `analyzeProject`/`getAnalyzeChain`/`retryAnalyzeChain` + `AnalyzeChainState`/`ChainStepInfo` types; `triggerIngest` kept only as the legacy helper used by the pre-S05 `ScreenA` screen (outside this task's write scope). |
| `frontend/src/components/ImportAnalyzePanel.tsx` | Rewritten to the backend-owned chain model: per-step real state rows (import/proxy/scene_detect), real progress bars, overall progress = backend `chain.progress`, cancel-active-step, successor retry, resume from `GET /analyze`, refetch after every mutation, ETA derived from real progress deltas. |
| `frontend/e2e/import-analyze.spec.ts` | Rewritten to the corrected real API (6 interaction tests, no `/ingest`). |
| `frontend/e2e/import-analyze-visual.spec.ts` | Rewritten to the corrected real API (desktop + 390px screenshots into this task's session dir). |
| `tests/test_s05_orchestration.py` | NEW — 12 API tests (real synthetic CFR + VFR media), see below. |
| `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/LOG.md`, `REPORT.md` | This task's evidence. |

Untouched (verified by `git status`/`git diff`): `app/services/*`
(`video_import.py`, `timebase.py`, `video_proxy.py`, `scene_detector.py` —
zero writes), `app/workflow/durable_worker.py` (pre-existing S05-T02..T04
diff preserved, no new edit), `app/workflow/job_service.py` (pre-existing
diff preserved, no new edit), migrations/schema, `channels.json`,
`data/`, databases, MAIN tree, S06 worktrees.  No commit/push/deploy; no
reset/checkout/clean/delete of user data.  `frontend/test-results/.last-run.json`
is byte-identical to HEAD (`git diff` empty; the `M` flag is the CRLF
normalization advisory, same as the pre-existing `docs/pm/ROADMAP.md`).

## Tests and validation (each separately, exact commands/results)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q tests/test_s05_orchestration.py -p no:cacheprovider` | PASS — **12 passed** in 11.06s |
| 2 | `python -m pytest -q tests/test_s05_golden_integration.py -p no:cacheprovider` | PASS — **9 passed** in 9.15s |
| 3 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py tests/test_scene_chunk_stitch.py -p no:cacheprovider` | PASS — **113 passed, 5 skipped** in 38.77s |
| 4 | `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS — **184 passed, 2 skipped** in 48.42s |
| 5 | `npx tsc --noEmit` (frontend) | PASS — exit 0 |
| 5 | `npx eslint src/ e2e/` (frontend) | PASS — 0 errors (9 pre-existing warnings in old components, same baseline as S05-T05) |
| 6 | `python -m ruff check app tests` | PASS — `All checks passed!` |
| 7 | `python -m mypy app` | PASS — `Success: no issues found in 65 source files` |
| 8 | `git diff --check` | PASS — exit 0 (LF→CRLF advisory on pre-existing `docs/pm/ROADMAP.md` only) |
| 9 | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` (fresh, final code) | PASS — **7/7 gates, OVERALL: PASS (exit 0)** — see Quality Run |
| 10 | Playwright interaction + visual against the real QA API (:8003 backend, :3011 frontend) | PASS — **6/6 interaction** (23.2s) + **6/6 visual** (18.7s), 10 screenshots |

## Quality Run

- **Run ID:** `20260805-152346` — **OVERALL: PASS (exit code 0), 7/7 gates**
  (started 2026-08-05 15:23:46 +07:00).  Gate 2 Python tests:
  **707 passed, 19 skipped, 7 deselected** in 176.76s (the S05-T06 695-test
  baseline + 12 new orchestration tests).  Summary:
  `output/quality-baseline/20260805-152346/summary.json`.
- A first fresh run (`20260805-145025`, also 7/7 PASS) was superseded by the
  final run above after one UI fix (empty-state resume: an idle backend
  chain must show the dropzone, not the chain panel) — the recorded Run ID
  is the final-code run.

## Acceptance criteria evidence

### 1. ONE submission drives the real T02→T03→T04 chain (each step's durable job created/completed in order)

`tests/test_s05_orchestration.py::test_one_submission_drives_t02_t03_t04_in_order`
+ `test_idempotent_resubmission_reuses_chain`:
- `POST /api/projects/{id}/analyze` → 200 with the `ANALYZE_MEDIA` import Job
  (`job_type=ANALYZE_MEDIA`, owner `video_item`) created; `proxy` and
  `scene_detect` steps report `not_created`.
- Worker executes T02 → `GET /analyze` returns import `completed`
  (`progress=100.0`) and **materializes T03** (`GENERATE_PROXY`, step
  `proxy`); worker executes T03 → `GET /analyze` materializes **T04**
  (`ANALYZE_MEDIA`, step `scene_detect`); worker executes T04 → chain
  `completed`, `active_step=null`, `scenes_count=2`, real artifact ids
  exposed.  Repeated submissions reuse the SAME import job (exactly one
  effect set).

### 2. Chain state exposed to the UI is backend-owned (real checkpoints), no mock

The chain response is read from durable Job rows on every poll: per-step
`status` = the real Job state machine value, `progress` = real checkpoint
progress (import/proxy handlers publish 0..100 on completion — the chain
maps terminal-completed to 100 per §4.5-1; scene_detect publishes its real
10→60→100 checkpoints), `message`/`error`/`error_code` from the durable
row/envelope.  The UI renders exactly these values; the e2e tests assert UI
== backend row (e.g. `progressbar` 100% equals `GET /analyze` progress and
the `GET /api/jobs/{id}` row).

### 3. Successor retry with owner validation + idempotency; duplicate retry idempotent; retry-after-failure succeeds

`test_successor_retry_after_failure_via_api`,
`test_successor_retry_after_cancel_via_api`, `test_stable_scene_ids_across_successor_retry`,
`test_retry_and_submit_validation`:
- Failed scene step → `POST /analyze/retry` → **200** with a NEW successor
  Job id, `predecessor_job_id` = the failed job, same idempotency key +
  generation (§8.5); predecessor row immutable (`state=failed`, revision
  unchanged).
- **Duplicate retry is idempotent**: two immediate re-POSTs return the same
  successor (200 reuse) — never a 409/500.
- **Retry-after-failure actually succeeds**: the successor runs and the
  chain reaches `completed` with exactly one effect set.
- Retry after cancel: HTTP-cancelled scene step → successor completes,
  exactly 2 scene rows, chain link intact.
- Owner validation: unknown project → 404; no source uploaded → 400;
  retry on a completed chain → 400 (contract §8.1 — completed logical runs
  are never retried).

### 4. Cancel during active processing cleans the attempt's own staging; committed artifacts survive; orphan cleanup never deletes committed files

`test_cancel_during_active_cleans_staging_and_committed_survive` +
`test_orphan_cleanup_no_stray_jobs_or_files`:
- HTTP cancel (`POST /api/jobs/{id}/cancel`) of the running proxy step →
  cooperative drain to terminal `cancelled`; **staging empty**; the
  committed source artifact survives byte-identical (sha256/size on disk);
  no ready proxy artifact is created (no false-ready); the scene step is
  never materialized (`not_created`, `job_id=null`).
- Orphan cleanup: after cancel, exactly the chain's own 2 Job rows exist
  (import `completed` + proxy `cancelled`), zero files outside the managed
  `artifacts/` tree, staging empty.

### 5. Restart/resume produces no duplicate publication (SHA/size/containment; stable Scene IDs)

`test_restart_resume_no_duplicate_publication`:
- Import completes on worker 1; a **fresh engine + brand-new worker on the
  same database** resumes: the chain-state endpoint materializes T03, the
  new worker completes it, then T04 — exactly **1 attempt per job**,
  exactly **1 source + 1 proxy** artifact row+file, sha256/size match disk,
  staging empty, 2 scene rows.
- Stable Scene IDs: `test_stable_scene_ids_across_successor_retry` — rows
  committed then permanent failure; the successor retry reuses the
  committed rows by evidence (identical Scene IDs, `revision==1`,
  predecessor immutable).  Also covered by the golden suite (9 passed).

### 6. CFR and VFR both complete through the orchestration API

`test_cfr_chain_completes_through_api` + `test_vfr_chain_completes_through_api`:
- CFR (30/1): chain `completed`; VideoItem probe columns
  `duration_ms=2000, width=320, height=240, fps=30/1`; scene rows
  `(0,29)/(30,59)` frames, `(0,999)/(1000,1999)` ms, `position [0,1]`,
  `revision 1`, `legacy_scene_id NULL`.
- VFR (30/1 + 25/1 concat → avg 33/1): chain `completed`; import checkpoint
  records `fps_classification=VFR`; the proxy timebase and the scene
  detection timebase both equal the exact `avg_frame_rate` rational;
  scene rows recompute exactly from the persisted grid.

### 7. Proxy SHA/size/containment

`test_proxy_sha_size_containment_through_chain`: every ready video artifact
(source + proxy) — `sha256 == SHA-256(file)`, `size_bytes == stat().st_size`,
relative path resolves strictly inside the managed root, `artifacts/`-
prefixed, no `..`; exactly 2 artifacts with owner purposes `{source, proxy}`;
the chain response's `proxy_artifact_id` matches the proxy artifact row;
staging empty; no file outside `artifacts/`.

### 8. UI no longer calls the legacy `/ingest` endpoint; renders real chain state

- `grep` of the Import/Analyze UI (`api.ts` + panel + e2e): the only
  remaining `/ingest` reference is the `triggerIngest` helper used by the
  pre-S05 `ScreenA` screen (outside this task's scope) — the Import/Analyze
  flow uses `POST/GET /analyze` + `POST /analyze/retry` + `POST
  /api/jobs/{id}/cancel`.
- Playwright proves the real chain end-to-end: empty state, ONE submission
  → completed with per-step real state, cancel of the active step,
  successor retry (new job id, no 500), resume after reload, API-level
  retry honesty (200 + successor; duplicate retry reuses it).

### 9. Static gates

ruff / mypy / `git diff --check` / frontend `tsc` + `eslint` / fresh
7/7 baseline — see the Tests table above.

## Playwright evidence (desktop + 390px, no mock)

- Interaction: `npx playwright test --config=playwright.s05t05.config.ts`
  (real QA backend :8003, frontend :3011) → **6 passed** in 23.2s.
- Visual: `npx playwright test --config=playwright.s05t05-visual.config.ts`
  → **6 passed** in 18.7s — 10 screenshots (desktop 1280x800 + 390x844 ×
  setup, file-selected, real mid-run progress, completed, preflight-error):
  `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/screenshots/`.
- QA environment: `python output/s05t05_qa_backend.py 8003` (worktree QA
  root, real durable worker via the FastAPI lifespan) + `npm run dev -- -p
  3011` with `NEXT_PUBLIC_API_URL=http://localhost:8003`.  The long-video
  fixture (60s 1280x720) keeps each step active for seconds so the cancel
  test cancels a genuinely RUNNING step (the small 320x240 fixture
  completes the whole chain in ~3s).

## Deviations from task

None in scope.  Notes:
- The legacy `POST /api/projects/{id}/ingest` endpoint is retained on the
  backend (other consumers + the durable job API regression suite depend on
  it); the Import/Analyze UI no longer calls it — the acceptance criterion
  is the UI wiring, which is corrected.
- `frontend/e2e/*` specs were updated to the corrected real API (they
  asserted the OLD legacy-`/ingest` behavior, including the
  "retry → 500 IdempotencyKeyInUse" honesty test that this task replaces
  with real successor retry).  This is part of the Playwright QA the task
  requires.

## Out-of-scope findings (pre-existing, not fixed)

- A cancel of a never-claimed QUEUED job transitions `queued → cancelling`
  and waits for the reconciler's lease scan (pre-existing S02 behavior,
  documented by S05-T06).  The UI renders `cancelling` honestly; the e2e
  cancel test uses the realistic cooperative path (cancel while running).
- `ScreenA` (pre-S05 legacy workflow) still uses the legacy `/ingest`
  helper; updating it is outside this task's write scope (noted for PM).

## Recommended PM decision

`PENDING` — awaiting Codex sprint-exit review per protocol.  No commit; no
self-approval; status `SUBMITTED`.

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

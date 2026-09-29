# Task S05-C03 — Implementation Report (final lifecycle correction)

- **Status:** `SUBMITTED` (never APPROVED — Codex performs the sprint-exit review)
- **Hermes session:** `20260805_173425_d558d0`
- **Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`
- **Started:** 2026-08-05 17:35 +07:00
- **Submitted:** 2026-08-05 ~19:40 +07:00
- **Quality Baseline Run ID:** `20260805-181617` — **OVERALL: PASS, 7/7 gates**

## Outcome delivered

All six Codex CHANGES_REQUESTED (round 3) blockers are fixed with real
durable semantics (no mock data, no fake progress):

1. **`AnalyzeChainOrchestrator` lifecycle is owned by the real FastAPI
   application lifespan** (`app/api/app.py`): startup calls
   `get_analyze_orchestrator().ensure_started()` AFTER the durable worker
   starts; the orchestrator's `start()` runs ONE synchronous idempotent
   scan-and-resume pass (materializes the next Job of every incomplete
   chain immediately) and then owns progression on its background loop;
   shutdown calls `stop(timeout=5.0)` BEFORE the worker stops. Resume needs
   NO POST, NO GET, NO browser polling, NO manual `advance_once()`.
2. **TRUE process-lifecycle test** (`tests/test_s05_lifecycle.py`):
   POST once → import completes → first app/TestClient lifespan FULLY shut
   down → FRESH app/TestClient over the same database → NO analyze API
   request → proxy job materializes (synchronously during lifespan
   startup) and completes → restart again → scene job materializes and
   completes. A second test proves the same with the REAL process-wide
   accessor and REAL poll cadence across four app generations (a further
   restart duplicates nothing).
3. **Source replacement with a different SHA produces a NEW valid chain
   that reaches completed** via an explicit VideoItem/version supersession
   (PERSISTENCE_DOMAIN_CONTRACT §4/§5): the previous VideoItem is ARCHIVED
   (its jobs/artifacts/scenes stay byte-identical and queryable — archive
   never cascades) and a NEW VideoItem becomes the pipeline unit for the
   new source, owning fresh scene rows. Old Scene evidence is never
   overwritten or silently reused.
4. **Test proves**: old jobs/artifacts/scenes immutable (full-row evidence
   snapshot + managed-file content hashes, byte-identical); new source gets
   a distinct VideoItem identity and outputs; the new chain completes; chain
   state exposes ONLY the current source (`video_item_id`/`source_sha256`/
   `proxy_artifact_id`/`scenes_count` all from the current item).
5. **GET read-only preserved** (zero-mutation snapshot equality around
   repeated GETs re-proven in the supersession test) and **all C02
   concurrency/retry guarantees preserved** — the full C02 suite passes
   unchanged except the one replacement test updated to the corrected
   supersession contract (see Deviations).

## Changed files (allowed write scope only)

| File | Change |
|---|---|
| `app/api/app.py` | Lifespan wiring: orchestrator `ensure_started()` after worker start; `stop()` before worker stop on shutdown (S05-C03). |
| `app/workflow/analyze_orchestrator.py` | `start()` gains the synchronous startup scan-and-resume; `submit_chain` performs the VideoItem supersession (archive old + new item) when the source SHA differs; `_chain_video_items`/`_advance_item` skip archived items (superseded chains frozen); docstring. Public API unchanged. |
| `tests/test_s05_lifecycle.py` | NEW — 3 tests: deterministic process-lifecycle restart (×2 restarts, zero analyze API calls), real-accessor lifecycle across 4 app generations, source supersession with immutability evidence. |
| `tests/test_s05_chain_progression.py` | `test_replace_source_video_stale_chain_not_reused` updated from the round-2 semantics (same VideoItem + fail-closed scene) to the C03 supersession contract (new VideoItem identity, new chain COMPLETES, old immutable). Other 8 tests untouched. |
| `frontend/e2e/import-analyze.spec.ts` | Cancel test made deterministic against the C03 backend (click at the START of the proxy step's active window — queued/running — instead of waiting for "running" and missing the ~2s chain). Same intent, same assertions. |
| `output/s05-c03-live-restart-smoke.py` | NEW QA tool: live crash-restart smoke against the real API (evidence below). |
| `docs/pm/sessions/S05-C03-final-lifecycle-correction/LOG.md`, `REPORT.md` | This task's evidence. |

Untouched (verified by `git status`/`git diff`): `app/services/*`
(`video_import.py`, `timebase.py`, `video_proxy.py`, `scene_detector.py` —
zero writes), `app/workflow/durable_worker.py` and `app/workflow/job_service.py`
(zero writes), `app/api/routes/projects.py` (zero writes — the supersession
needed no route change; the orchestrator's public surface is unchanged),
`frontend/src/lib/api.ts` + `frontend/src/app/(app)/import-analyze/` (chain
state shape unchanged), migrations/schema, `channels.json`, `data/`,
databases, MAIN tree, S06 worktrees. No commit/push/deploy; no
reset/checkout/clean/delete of user data.

## Tests and validation (each separately, exact commands/results)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q tests/test_s05_lifecycle.py -p no:cacheprovider` | PASS — **3 passed** in 20.7s |
| 2 | `python -m pytest -q tests/test_s05_chain_progression.py -p no:cacheprovider` | PASS — **9 passed** in 12.7s |
| 3 | `python -m pytest -q tests/test_s05_orchestration.py -p no:cacheprovider` | PASS — **12 passed** (with #4: 21 passed in 20.8s) |
| 4 | `python -m pytest -q tests/test_s05_golden_integration.py -p no:cacheprovider` | PASS — **9 passed** (21 with #3) |
| 5 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py tests/test_scene_chunk_stitch.py -p no:cacheprovider` | PASS — **113 passed, 5 skipped** in 38.7s |
| 6 | `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS — **184 passed, 2 skipped** in 48.6s |
| 7 | `npx tsc --noEmit` (frontend/) | PASS — exit 0 |
| 7 | `npx eslint src/ e2e/` (frontend/) | PASS — 0 errors (9 pre-existing warnings) |
| 8 | `python -m ruff check app tests` | PASS — All checks passed |
| 9 | `python -m mypy app` | PASS — Success, 66 source files |
| 10 | `git diff --check` | PASS — exit 0 (only pre-existing CRLF advisories) |
| 11 | `powershell -File scripts/quality-baseline.ps1` | PASS — **OVERALL: PASS, 7/7 gates**, Run ID **`20260805-181617`** (Gate 2: 213.66s) |
| 12 | `npx playwright test --config=playwright.s05t05.config.ts` (real API :8003 + frontend :3011) | PASS — **6 passed** (19.6s) |
| 12 | `npx playwright test --config=playwright.s05t05-visual.config.ts` | PASS — **6 passed** (18.6s) — desktop 1280×800 + 390×844; 10 fresh screenshots in `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/screenshots/` |

## Evidence required by TASK.md (each item, where it is proven)

- **Lifespan wiring evidence (startup resume without API calls):**
  `app/api/app.py` lifespan start/stop + `analyze_orchestrator.start()`'s
  synchronous scan. Proven by
  `tests/test_s05_lifecycle.py::test_process_lifecycle_restart_resumes_chain_without_api_requests`:
  a cadence-BLOCKED orchestrator (its poll loop never advances on its own)
  is the only orchestrator in play, so the proxy job's appearance right
  after a fresh lifespan startup can ONLY come from the startup scan —
  asserted BEFORE any poll tick could have run. Same for the scene job
  after the second restart.
- **Process-lifecycle evidence (restart after import; restart after
  proxy):** the test above: generation 1 completes ONLY import (proxy count
  asserted 0 at shutdown); generation 2 (fresh app/TestClient over the same
  DB, zero analyze requests) materializes + completes the proxy; generation
  3 (restart after proxy) materializes + completes the scene. Terminal
  proof: exactly one job per step, 2 scene rows, staging empty.
  `test_lifespan_owned_chain_completes_across_real_restarts` repeats it with
  the REAL accessor/real cadence across 4 generations (gen 4 duplicates
  nothing). LIVE: `output/s05-c03-live-restart-smoke.py` — POST once →
  backend KILLED mid-import → fresh backend → no analyze API request →
  T02→T03→T04 all completed (1/1/1 jobs, 1 scene row, final read-only GET
  completed/100%).
- **Source-replacement supersession evidence (new identity, old
  immutable):** `test_replace_source_supersedes_video_item_new_chain_completes`
  — different-evidence replacement: `video_item_id` changes, old item
  status=`archived` with `archived_at`, full-row evidence snapshot (jobs +
  scenes + artifacts + owners) AND managed-file content hashes byte-identical
  before/after, new chain's 3 jobs all new ids, new scene rows (ids ≠ old),
  new proxy artifact (≠ stale), chain completes; identical-evidence
  re-encode: third distinct identity, completes, everything before immutable
  and frozen (archived chains get no successor jobs). The updated
  `test_replace_source_video_stale_chain_not_reused` in
  `test_s05_chain_progression.py` asserts the same at the chain level.
- **Chain state exposes only the selected/current source:**
  `mid`/`final` chain-state asserts: `video_item_id == item_b/item_c`,
  `source_sha256 == sha_b/sha_c`, `proxy_artifact_id` never the stale one,
  `scenes_count` counts only the current item's rows.
- **GET read-only + C02 guarantee preservation:** the full C02 suite passes
  (`test_get_repeated_and_concurrent_zero_db_mutations` unchanged — 25
  sequential + 6 concurrent GETs, full-row snapshot identical; single-
  successor-per-step; idempotent failure/cancel successor retry; CFR/VFR,
  containment, SHA/size, Scene IDs, orphan cleanup — all green). The
  supersession test additionally snapshots the DB around 3 repeated GETs
  (byte-identical). Chain-state endpoint code untouched (read-only).
- **Playwright desktop + 390px evidence:** interaction **6/6** (19.6s) +
  visual **6/6** (18.6s) against the real API (:8003, C03 code) + frontend
  :3011 — desktop 1280×800 + 390×844, 10 fresh screenshots.

## Deviations from task (documented honestly)

- `tests/test_s05_chain_progression.py::test_replace_source_video_stale_chain_not_reused`
  was updated to the C03 supersession contract. The round-2 version encoded
  the semantics Codex rejected (replacement on the SAME VideoItem, scene
  step failing closed with `SCENE_EVIDENCE_CONFLICT`); the C03 contract
  requires the new chain to COMPLETE via an explicit VideoItem/version
  supersession, which is impossible on the same VideoItem (the approved
  scene detector fails closed on evidence mismatch BY DESIGN — its
  immutability guarantee is now proven at the VideoItem level). Same
  precedent as C02's own test updates. All other chain-progression tests
  (including the fail-closed detector behavior, covered by
  `tests/test_scene_detection.py`) are untouched.
- `frontend/e2e/import-analyze.spec.ts` cancel test: with the C03 backend
  the orchestrator loop is already running at boot and the whole chain can
  complete in ~2s, so the old wait-for-"running"-then-click sequence could
  miss the cancel window and stall the click (observed: 5/6 on the first
  run). The test now clicks at the START of the proxy step's active window
  (queued or running) — same intent ("cancel the ACTIVE step's real job →
  chain cancelled, retry offered"), same assertions, deterministic.
- The visual spec saves screenshots into the pre-existing S05-C01
  screenshots dir (its `SHOT_DIR` constant, outside this task's write
  scope); 10 fresh files were written there by this task's run (same as
  C02).
- Production note (pre-existing, NOT changed): a bare `uvicorn app.main:app`
  still constructs a `JobService` whose worker keeps a placeholder session
  factory (documented in `output/s05t05_qa_backend.py`); the QA server
  therefore injects the approved test wiring (same DB + managed root) —
  the orchestrator start/stop wiring itself IS exercised through the real
  FastAPI lifespan in both the tests and the live QA server.

## Recommended PM decision

`PENDING` — awaiting Codex sprint-exit review per protocol. No commit; no
self-approval; status `SUBMITTED`.

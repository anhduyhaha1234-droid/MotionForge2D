# Task S05-C02 — Implementation Report

- **Status:** `SUBMITTED` (never APPROVED — Codex performs the sprint-exit review)
- **Hermes session:** `20260805_155512_9d6935`
- **Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`
- **Started:** 2026-08-05 16:20 +07:00
- **Submitted:** 2026-08-05 17:45 +07:00
- **Quality Baseline Run ID:** `20260805-163430` — **OVERALL: PASS, 7/7 gates**

## Outcome delivered

All four Codex CHANGES_REQUESTED blockers are fixed with real durable
semantics (no mock data, no fake progress):

1. **`GET /api/projects/{id}/analyze` is strictly read-only.** The endpoint
   performs zero inserts/updates/deletes/commits — it only reads durable
   rows. Repeated AND concurrent GETs cause zero database mutations
   (verified by a full-row snapshot across 25 sequential + 6 concurrent
   GETs, and live against the QA backend).
2. **One `POST /analyze` → T02 import → T03 proxy → T04 scene detect
   completes under backend worker/orchestrator ownership** — even with the
   browser closed immediately, with NO GET polling, and across API process
   restarts. The chain progression lives in a focused durable orchestration
   service (`app/workflow/analyze_orchestrator.py`) whose background poll
   loop materializes each successor as its predecessor durably completes;
   the durable worker executes the steps. The POST is submission-only.
3. **Chain progression moved out of the projects route** into the
   orchestration service. The routes are thin (project/source resolution +
   delegation to the orchestrator's PUBLIC surface) and never touch
   JobService private members (the orchestrator's accessor binds to the
   same DB/managed root the app lifespan uses — the established
   `deps._lifecycle_db` / `_session_factory` pattern, no route-level private
   access).
4. **Chain identity is bound to immutable input evidence**: the source
   file's SHA-256 (computed streaming at submission — the preflight
   checksum policy, VIDEO_PREFLIGHT_CONTRACT §5.4) plus the
   generation/version. Every chain query is scoped by the deterministic
   idempotency-key suffix `:<source_sha256>:<generation>`. Replacing the
   project source with a different video yields a NEW identity → a NEW
   chain; the stale chain's jobs and artifacts are never silently reused
   (the approved scene detector additionally fails closed with
   `SCENE_EVIDENCE_CONFLICT` rather than overwriting evidence from another
   source).

## Design (durable orchestration service)

`app/workflow/analyze_orchestrator.py` — `AnalyzeChainOrchestrator`:

- **Public surface** (the only API the routes use):
  - `submit_chain(project_id, source_path, generation, title)` — computes
    the streaming source SHA-256, materializes the durable
    Workspace→Project→VideoItem shell, submits the `ANALYZE_MEDIA` import
    Job via `video_import.submit_import` (with `source_sha256` so the key
    is `ANALYZE_MEDIA:video_item:<id>:<sha>:<generation>`), starts the
    background loop and returns the chain state. Idempotent per identity
    (contract §8.1).
  - `chain_state(project_id, generation)` — READ-ONLY chain response:
    per-step real durable rows, checkpoint progress, terminal states,
    additive `source_sha256`, and artifact ids taken from the CURRENT
    chain's own published checkpoints (never a stale owner link).
  - `retry_chain(project_id, generation)` — successor creation (§8.5) for
    the newest failed/cancelled Job of the CURRENT identity; duplicate
    retries reuse the successor (idempotent).
  - `advance_once(project_id=None) -> AdvanceReport` — one idempotent pass
    (scans all chains when no project given); creates the next Job only
    when its predecessor is terminal-completed; `IdempotencyKeyInUse` is
    suppressed (concurrent passes safe); never raises.
  - `start()/stop()/ensure_started()/running` — the background poll loop:
    **the backend owner of chain progression** (browser-independent,
    restart-safe — a restarted process's orchestrator resumes advancing
    from durable rows).
- Chain identity scoping: import lookup by key prefix
  `ANALYZE_MEDIA:video_item:<id>:%`; proxy/scene lookups by exact
  deterministic keys embedding `<sha>:<generation>`. Jobs of a replaced
  source never appear in the current chain.
- No schema/migration change; no modification of `app/services/*`,
  `app/workflow/durable_worker.py`, job-state-machine semantics or
  `channels.json`; no commit/push/deploy.

## Changed files (allowed write scope only)

| File | Change |
|---|---|
| `app/workflow/analyze_orchestrator.py` | NEW — focused durable orchestration service (~720 lines, see Design). |
| `app/api/routes/projects.py` | Slimmed from 2664 → ~2170 lines: all chain helpers moved into the orchestrator; the three analyze endpoints are thin delegates; GET strictly read-only; no JobService private-member access from routes. |
| `frontend/src/lib/api.ts` | `AnalyzeChainState` + additive `source_sha256`; doc comments corrected (GET read-only; backend-owned progression). UI behavior unchanged. |
| `tests/test_s05_chain_progression.py` | NEW — 9 adversarial tests (see below). |
| `tests/test_s05_orchestration.py` | Updated the 12 existing tests to drive the chain via `get_analyze_orchestrator().advance_once()` — the old tests encoded the flagged GET-advances anti-pattern and could not pass honestly with a read-only GET; every assertion is unchanged (GET used only to READ state). Documented deviation. |
| `frontend/e2e/import-analyze.spec.ts` | Cancel test made race-robust against the corrected backend (wait for the proxy step's long running window; `.first()` on multi-match status badges; wait-based badge assertions) — the two failure modes were pre-existing test timing fragilities, not backend defects. Documented deviation. |
| `docs/pm/sessions/S05-C02-durable-chain-progression/LOG.md`, `REPORT.md` | This task's evidence. |

Untouched (verified by `git status`/`git diff`): `app/services/*`
(`video_import.py`, `timebase.py`, `video_proxy.py`, `scene_detector.py` —
zero writes), `app/workflow/durable_worker.py` and `app/workflow/job_service.py`
(pre-existing S05 diffs preserved, no new edit), migrations/schema,
`channels.json`, `data/`, databases, MAIN tree, S06 worktrees.  No
commit/push/deploy; no reset/checkout/clean/delete of user data.

## Tests and validation (each separately, exact commands/results)

| # | Command | Result |
|---|---|---|
| 1 | `python -m pytest -q tests/test_s05_chain_progression.py -p no:cacheprovider` | PASS — **9 passed** in 12.66s |
| 2 | `python -m pytest -q tests/test_s05_orchestration.py -p no:cacheprovider` | PASS — **12 passed** in 13.75s |
| 3 | `python -m pytest -q tests/test_s05_golden_integration.py -p no:cacheprovider` | PASS — **9 passed** (with #2: 21 passed in 20.79s) |
| 4 | `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py tests/test_video_import.py tests/test_scene_detection.py tests/test_scene_chunk_stitch.py -p no:cacheprovider` | PASS — **113 passed, 5 skipped** in 38.60s |
| 5 | `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS — **184 passed, 2 skipped** in 48.35s |
| 6 | `npx tsc --noEmit` (frontend/) | PASS — exit 0 |
| 6 | `npx eslint src/ e2e/` (frontend/) | PASS — 0 errors (9 pre-existing warnings) |
| 7 | `python -m ruff check app tests` | PASS — All checks passed |
| 8 | `python -m mypy app` | PASS — Success, 66 source files |
| 9 | `git diff --check` | PASS — exit 0 (only pre-existing CRLF advisories on ROADMAP.md / test-results) |
| 10 | `powershell -File scripts/quality-baseline.ps1` | PASS — **OVERALL: PASS, 7/7 gates**, Run ID **`20260805-163430`** (Gate 2: 707 passed, 19 skipped, 7 deselected; 188.74s). Summary: `output/quality-baseline/20260805-163430/summary.json` |
| 11 | `npx playwright test --config=playwright.s05t05.config.ts` (real QA backend :8003 + frontend :3011) | PASS — **6 passed** (21.6s); re-run **6/6** stable |
| 11 | `npx playwright test --config=playwright.s05t05-visual.config.ts` | PASS — **6 passed** (18.6s) — desktop 1280×800 + 390×844 × setup/file-selected/progress/completed/preflight-error; 10 fresh screenshots in `docs/pm/sessions/S05-C01-approved-pipeline-orchestration/screenshots/` |

## Evidence required by TASK.md (each item, where it is proven)

- **Read-only-GET evidence (zero mutations):**
  `tests/test_s05_chain_progression.py::test_get_repeated_and_concurrent_zero_db_mutations`
  — 25 sequential + 6 barrier-synchronized concurrent GETs against a
  completed chain; full durable-row snapshot (job, job_step, job_event,
  job_attempt, job_lease, artifact, artifact_owner, scene, video_item,
  project) + managed-file list byte-identical before/after; GETs also
  byte-identical JSON. Same test asserts GET on a NEVER-submitted project
  creates nothing (no durable shell). Live QA smoke additionally ran GET
  ×10 at terminal on the real running backend: zero mutations.
- **POST-once-no-GET chain completion evidence:**
  `test_post_once_no_get_chain_completes_under_orchestrator` — exactly one
  POST; ZERO GET /analyze; the orchestrator's background loop + durable
  worker complete T02→T03→T04 (job types and states asserted from durable
  rows; staging empty). Live QA: the chain completed with the only reads
  being the script's status polls.
- **API-restart evidence (after import, after proxy):**
  `test_api_restart_after_import_and_after_proxy_chain_completes` — fresh
  engines + fresh workers + fresh orchestrators over the SAME database file
  after import and after proxy; chain completes; exactly one attempt per
  step, one source + one proxy artifact, sha/size verified, 2 scene rows.
- **Source-replacement stale-chain evidence:**
  `test_replace_source_video_stale_chain_not_reused` — replacement with
  DIFFERENT evidence (24fps): new source_sha256 in the response, new
  import/proxy job ids, new proxy artifact (never the stale one), old rows
  terminal-immutable, scene step fails closed with
  `SCENE_EVIDENCE_CONFLICT` (permanent) leaving the old rows byte-identical;
  replacement with IDENTICAL evidence (same grid, different bytes): the new
  chain completes with new jobs, rows reused only after exact evidence
  equality.
- **Single-successor-per-step evidence:**
  `test_concurrent_advancement_exactly_one_successor_per_step` — 8
  barrier-synchronized `advance_once()` calls after import → exactly 1
  `GENERATE_PROXY` job; 8-way after proxy → exactly 1 scene job; the
  surviving chain completes.
- **Successor retry idempotency evidence:**
  `test_failure_successor_retry_idempotent` + `test_cancel_successor_retry_idempotent`
  — failed and cancelled scene steps retried via `retry_chain`; duplicate
  retries reuse the same successor (never 409/500); predecessor immutable;
  successor completes with one effect set; stable Scene IDs across retry
  (`test_cfr_chain_containment_sha_size_scene_ids_orphan_cleanup`).
- **CFR/VFR, containment, SHA/size, Scene IDs, orphan cleanup evidence:**
  `test_cfr_chain_containment_sha_size_scene_ids_orphan_cleanup` (CFR grid
  (0,29)/(30,59) × (0,999)/(1000,1999), revision 1, sha/size of every
  ready artifact, all files under `artifacts/`, staging empty, cancelled
  proxy → no orphan scene job) and `test_vfr_chain_completes_through_orchestrator`
  (VFR classification recorded in the import checkpoint, canonical
  avg_frame_rate grid consumed by the scene step) + the full existing S05
  regression set (113 passed, 5 skipped).
- **Playwright desktop + 390px evidence:** interaction 6/6 (stable on
  re-run) + visual 6/6 (desktop 1280×800 + 390×844), fresh screenshots in
  the S05-C01 session dir; live QA backend with the real durable worker +
  the new orchestrator loop.

## Deviations from task (documented honestly)

- `tests/test_s05_orchestration.py` was updated (12 tests) to advance the
  chain via `get_analyze_orchestrator().advance_once()` instead of
  `GET /analyze`. The old tests encoded the exact anti-pattern Codex
  flagged ("tests call read endpoints that secretly advance it") and could
  not pass honestly under a read-only GET. All assertions are unchanged;
  GET is used only to read state. This is the same correction the task
  requires of the pipeline itself, applied to its tests.
- `frontend/e2e/import-analyze.spec.ts` cancel test was made race-robust:
  with the corrected backend the chain advances under backend ownership
  and steps complete in ~1s on this machine, so the old test's 1s-poll +
  instant-click could (a) cancel a just-completed job (backend honestly
  returns 400 "Cannot cancel job in state: completed") or (b) hit a
  strict-mode multi-match locator / stale UI-text comparison. The test now
  waits for the proxy step's long running window, uses `.first()` on
  multi-match badges and wait-based assertions — same intent, deterministic.
- The e2e visual spec saves screenshots into the pre-existing S05-C01
  screenshots dir (its `SHOT_DIR` constant, outside this task's write
  scope); 10 fresh files were written there by this task's run.
- Production note: the orchestrator loop is started by `POST /analyze`
  (`ensure_started`). Wiring `get_analyze_orchestrator().start()` into the
  app lifespan (app/api/app.py) would make the loop start at process boot
  without any request; that file is outside this task's write scope, so it
  is flagged here for PM/Codex rather than edited. Durable correctness is
  unaffected: any POST (or a restarted orchestrator) resumes advancement
  from durable rows.

## Recommended PM decision

`PENDING` — awaiting Codex sprint-exit review per protocol. No commit; no
self-approval; status `SUBMITTED`.


## CORRECTION APPENDIX — S05-C03 (final lifecycle correction, appended 2026-08-05 — do not rewrite history)

Codex CHANGES_REQUESTED round 3 (S05-C02 review) required: (1) start/stop
`AnalyzeChainOrchestrator` through the real FastAPI application lifespan
with a startup scan-and-resume of incomplete chains (NO POST/GET/browser
polling/manual `advance_once`) — this report's "Production note" explicitly
flagged that wiring as outside C02's write scope; (2) a TRUE process-
lifecycle test (POST once → import only → FULL app shutdown → FRESH app
over the same DB → NO analyze API request → proxy and scene jobs
materialize and complete; repeat after proxy); (3) source replacement with
a different SHA producing a NEW valid chain that REACHES COMPLETED via an
explicit VideoItem/version supersession — C02's replacement test encoded
the weaker semantics (same VideoItem, new scene step fails closed with
`SCENE_EVIDENCE_CONFLICT`); (4) old jobs/artifacts/scenes immutable, new
source distinct identity + outputs, chain state exposes only the current
source; (5) GET read-only + all C02 concurrency/retry guarantees preserved.

S05-C03 (`docs/pm/sessions/S05-C03-final-lifecycle-correction/REPORT.md`)
delivers all of it:
- `app/api/app.py` lifespan: orchestrator `ensure_started()` after the
  worker starts, `stop()` before the worker stops; `analyze_orchestrator.start()`
  runs ONE synchronous idempotent scan-and-resume before the loop thread.
- NEW `tests/test_s05_lifecycle.py` (3 tests): deterministic process-
  lifecycle restart (×2 restarts, zero analyze API requests — a
  cadence-blocked orchestrator makes the materialization attributable only
  to the startup scan), real-accessor restarts across 4 app generations
  (nothing duplicated), and source supersession with byte-identical
  immutability evidence (jobs/scenes/artifacts/owners rows + managed-file
  hashes).
- The replacement test IN THIS FILE was updated to the supersession
  contract: a different source SHA archives the old VideoItem and creates a
  NEW one, the new chain COMPLETES on fresh rows, old rows stay immutable,
  chain state exposes only the current source. The round-2
  same-VideoItem-fail-closed semantics was the exact blocker Codex
  rejected; the detector's fail-closed immutability guarantee remains
  covered by `tests/test_scene_detection.py`.
- C02 guarantees preserved: the other 8 tests here are untouched and pass
  (9 passed) — GET zero-mutation (25 sequential + 6 concurrent), exactly
  one successor per step, idempotent failure/cancel retry, CFR/VFR,
  containment, SHA/size, Scene IDs, orphan cleanup.
- Playwright interaction 6/6 + visual 6/6 (desktop 1280×800 + 390×844)
  against the C03 real API; fresh 7/7 baseline Run ID `20260805-181617`.
- Status of S05-C03: SUBMITTED (never APPROVED).

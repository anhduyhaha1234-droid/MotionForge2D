# S08-H01 — LOG (append-only)

## 2026-08-17 — Packet materialized by manager (pre-launch)

- TASK.md / START_PROMPT.md created from Codex correction cycle finding F.
- Launcher: `output/run-s08-h01-fresh.ps1` (NEW session, flash).
- Manager gate before launch: S08-T04 correction must be MANAGER_VERIFIED.

_(worker entries appended below)_

## 2026-08-17 — Worker baseline (H01, frontend-only, finding F)

**Worktree guard (pre-write):**
- `pwd` → `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` ✓
- `git rev-parse --show-toplevel` → same ✓
- `git branch --show-current` → `codex/s08-integration` ✓
- `git status --short` → 23 modified + 130 untracked (baseline snapshot taken, all pre-existing S08 work)

**Protected-data baseline (MAIN, read-only):**
- `certutil -hashfile channels.json SHA256` → `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` ✓ (matches approved)
- `stat data/motionforge.db` → `311296 bytes`, mtime 2026-08-16 17:25:22 ✓ (matches 311296 expected)
- SAM2.1 checkpoint `models_checkpoints/sam2.1_hiera_large.pt` → `898083611 bytes`, mtime 2026-07-29 21:06:29 (untouched; frontend-only scope cannot reach it)

**Backend regression baseline (must stay UNCHANGED at exit):**
- Command: `python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_correction.py tests/test_object_correction_api.py -q -p no:cacheprovider --no-header`
- Running in background (`proc_9777dbfa1728`); result recorded in the exit section below.

**Findings confirmed (facts, from real API contracts):**
- `frontend/src/app/(app)/projects/[id]/page.tsx` fabricates project + video rows on API failure (`Dự án 2D ${id.slice(0,8)}`, `v-001` mock) and reads WRONG durable contracts: `/api/v2/projects/{id}` returns `project_id` (not `id`), `/api/v2/projects/{id}/videos` returns `videos` (not `items`), `VideoItemData.title/position/duration_ms` (not `title/order_index/duration_seconds`).
- `frontend/src/components/Dashboard.tsx` silently empties project list on non-ok and calls `/api/v2/jobs?state=running` which has NO backend route (only `GET /api/jobs/{job_id}` + `POST cancel` exist).
- `frontend/src/components/LegacyWorkspace.tsx` writes `projectId` to the Zustand store BEFORE backend validation of `?project=` and swallows failures with `console.error` (silent breakage).
- Gallery (S08-T04-C1) is already backend-authoritative (verified: chain/videos/roles/current-extraction/policy all real APIs with honest error+retry UI).

_(implementation appended below)_

## 2026-08-17 — Worker implementation (S08-H01)

**Changed (frontend-only, all in `frontend/`):**
- `src/lib/api.ts` — added `DurableProjectData`/`DurableProjectListResponse` types + `api.getDurableProject`/`api.listDurableProjects` (real S03 v2 contract); added `task_status`/`channel_id`/`created_at`/`updated_at` to the frontend `ProjectData` (backend serializes them; type was incomplete).
- `src/app/(app)/projects/[id]/page.tsx` — REWRITE: removed fabricated fallback project (`Dự án 2D ${id.slice(0,8)}`) + mock video row (`v-001`) and the wrong `.items`/`data.id` reads. Identity resolves durable v2 → legacy → honest NOT-FOUND (404 real); network/server failure → honest ERROR + "Thử lại". Videos from the matching real contract (v2 `videos` for durable, analyze-chain `video_item_id` for legacy). Explicit URL navigation: processing → `/import-analyze?project=<id>`, per-video gallery → `/object-gallery?project=<id>&video=<video_item_id>`.
- `src/components/Dashboard.tsx` — REWRITE: removed silent-empty `setProjects([])` on failure + fabricated `/api/v2/jobs?state=running` call (no such route). Real `listDurableProjects` (key `project_id`), TanStack loading/error+retry/empty states; the jobs card now shows an explicit "no job-list API" note (honest).
- `src/components/LegacyWorkspace.tsx` — hydrate `?project=` now VALIDATES via the backend (getProject + getSceneDetails) BEFORE writing the Zustand store; failures render an honest error banner with "🔄 Thử lại" + "Danh sách dự án" link (never silent); the same URL is not silently re-resumed after "✨ Tạo Dự Án Mới"; channel-dashboard resume failures surface via alert instead of `console.error`.
- `src/components/ImportAnalyzePanel.tsx` — when the chain is completed, adds "Xem thư viện đối tượng" → `/object-gallery?project=<id>&video=<chain.video_item_id>` (explicit selection passed at click time) — minimal navigation wiring.
- NEW `frontend/e2e/s08-h01-helpers.ts`, `s08-h01-production-authority.spec.ts` (desktop), `s08-h01-production-authority-mobile.spec.ts` (390px), `frontend/playwright.s08h01.config.ts`.
- `frontend/e2e/s08-t04-helpers.ts` — API base now `process.env.QA_API_BASE ?? http://localhost:8025` (backward compatible; S08-H01 passes 8026 inline).
- `output/s08-sprint/20260817-s08h01-r1/` — fresh run root (run-qa-backend.sh → port 8026, backend-root, screenshots/, test-results/, logs).

**Validation ran so far:**
- `npx tsc --noEmit` → exit 0 (clean)
- `npx eslint .` → 0 errors, 10 warnings (all pre-existing `@next/next/no-img-element`)
- `npm run build` → ✓ exit 0; all routes built, `/projects/[id]` dynamic
- `npx playwright test --config=playwright.s08h01.config.ts --list` → 11 tests (6 desktop + 5 mobile-390px), correct split
- `grep` for fabricated fallback patterns (`Dự án 2D`, `v-001`, `itemsData.items`, `setProjects([])`, `Fallback demo projects`) over `frontend/src` → NO matches
- Backend regression baseline (T01–T05 combined, no cache): **161 passed** in 85.58s

_(QA run + exit evidence appended below)_

## 2026-08-17 — CORRECTION ROUND exit (S08-H01, finding F)

**QA environment (fresh run root, never touches previous run screenshots):**
- Run root: `output/s08-sprint/20260817-s08h01-r1/` (backend-root, run-qa-backend.sh → port 8026, `MOTIONFORGE_EXTRACTION_PROVIDER=deterministic`, cwd+env inline; screenshots/, test-results/, next-dev.log).
- Frontend dev: `NEXT_PUBLIC_API_URL=http://127.0.0.1:8026 npm run dev -- -p 3013` (fresh `.next` after clearing a corrupted Turbopack cache that threw a dev-overlay runtime error).
- Playwright: `QA_API_BASE=http://127.0.0.1:8026 npx playwright test --config=playwright.s08h01.config.ts`.
- `--list` verified (11 tests, correct split): 6 desktop + 5 mobile-390px, no cross-selection.
- Failure tests exercise REAL error paths: identity-verified `taskkill /PID <pid> /T /F` (netstat port 8026 + `wmic` CommandLine contains `uvicorn`+`8026`+`s08-integration`) then backend restart via `run-qa-backend.sh`; no page.route() mocking.

**Final QA result (verbatim):** `11 passed (1.4m)` — desktop 01–06 + mobile-390px m01–m05, INCLUDING:
- not-found on 404 (durable unknown UUID + legacy-style unknown id),
- durable detail real rows + explicit `?project=&video=` URL selection,
- multi-video gallery URL switch + refresh preserves selection,
- detail → processing → gallery explicit selection each hop,
- API-down honest error + retry recovers after real backend restart,
- LegacyWorkspace backend-down hydrate error + retry validates before store write,
- 390px no-horizontal-overflow asserted on every mobile state.

**Screenshots (fresh, in the H01 run root only — 15 files):** desktop-detail-durable, desktop-gallery-video-a/b, desktop-home-hydrate-error, desktop-home-recovered, desktop-honest-error, desktop-not-found-uuid, desktop-processing-completed, desktop-retry-recovered, mobile-detail-durable, mobile-gallery-video-b, mobile-home-hydrate-error, mobile-honest-error, mobile-not-found, mobile-retry-recovered.

**Static + backend validation (final, exact commands → results):**
- `npx tsc --noEmit` → `TSC_EXIT=0`
- `npx eslint .` → `✖ 10 problems (0 errors, 10 warnings)` (all pre-existing `@next/next/no-img-element`)
- `npm run build` → exit 0, all routes built, `/projects/[id]` dynamic
- Backend regression: `python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_correction.py tests/test_object_correction_api.py -q -p no:cacheprovider --no-header` → baseline `161 passed, ... in 85.58s` → exit re-run `161 passed, 293 warnings in 86.35s` (**identical — frontend-only scope, backend unchanged**)
- `git diff --name-only -- '*.py' | xargs -r ruff check --quiet` → `RUFF_EXIT=0`
- `python -m mypy app` → `Success: no issues found in 86 source files` / `MYPY_EXIT=0`
- `git diff --check` → exit 0 (no whitespace errors)
- Explicit grep (fabricated fallbacks: `Dự án 2D `, `v-001`, `itemsData.items`, `setProjects([])`, `Fallback demo projects`, `Fallback mock detail`) over `frontend/src` → 0 hits
- Protected data (MAIN, unchanged): `channels.json` SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` (matches approved); `data/motionforge.db` `311296 bytes`; SAM2.1 `models_checkpoints/sam2.1_hiera_large.pt` `898083611 bytes`, mtime `2026-07-29 21:06:29` (untouched)
- QA servers teardown: port 3013 (next dev, PID verified via CommandLine `next/dist/server/lib/start-server.js` + worktree) and port 8026 (uvicorn `--port 8026` + worktree) both `taskkill /T /F` after identity verification — ports now free.

**Incidents (all harness, zero frontend-contract defects):**
1. r1: dev-server `.next` Turbopack cache corruption → dev-overlay runtime error on the detail route. Fix: verified process identity, killed stale server, `rm -rf frontend/.next`, restarted clean. (Known Next.js symptom when sources change under a live dev server.)
2. r1/r2: `setupSuite()` did not start the QA backend (spec never spawned it → desktop beforeAll `TypeError: fetch failed`); separate Playwright workers hold no port ownership. Fix: `startBackend()` as the first step of `setupSuite()` + port-based identity-verified `killBackend()` (netstat + wmic) so cross-worker kills work.
3. r3: test 03 assertion bug — video A's deterministic extraction also yields a role named `subject_01` (A has 4 roles), so asserting `subject_01` count 0 after switching to A was wrong. Fixed to assert A-specific `subject_04`.

**Worktree guard (final):** `pwd` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`; `git rev-parse --show-toplevel` = same; `git branch --show-current` = `codex/s08-integration`. No MAIN or other-worktree writes. No backend file touched by H01.

_(end of H01 worker entries — status SUBMITTED, never self-approved)_

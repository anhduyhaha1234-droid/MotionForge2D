# S08-T04 — Object Gallery and Confidence UX: Implementation Report

**Status:** SUBMITTED  (never APPROVED — manager/Codex sprint-exit review owns approval)
**Hermes session:** `20260816_170337_74161b` (fresh S08-T04 worker session)
**Started:** 2026-08-16 17:03
**Submitted:** 2026-08-16
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Depends on:** S08-T03 manager-verified (`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`)

## Outcome

A new Object Gallery screen (`/object-gallery`) where users review candidates
grouped by durable Object Role: they see REAL confidence (with reasons and
provenance), scene coverage and bbox evidence, registered thumbnail/mask
artifact metadata, and confirmed/suggested status — then explicitly confirm,
merge (suggestion-driven or manual), split, or dismiss. All data comes from the
REAL T01/T02/T03 APIs and managed representative media (deterministic provider
selected explicitly via the QA environment; production default fails closed).
Loading, empty, error+retry, extraction-progress, partial-artifact,
low-confidence and stale-conflict experiences are explicit; low confidence is
never auto-confirmed; merge/split/confirm always require selection + a
confirmation dialog; keyboard/focus/dialog semantics and 390px layout with no
horizontal overflow are implemented and E2E-tested. Existing Import/Analyze and
Character Library navigation/UX are preserved (one nav item added).

## Files changed (all within TASK.md allowed write scope)

| File | Change |
|---|---|
| `frontend/src/app/(app)/object-gallery/page.tsx` | NEW route (Suspense + `?project=`), delegates to the panel. |
| `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` | NEW orchestrator: project picker, analyze-chain gate (link to Import/Analyze), extraction submit + REAL job progress polling + retry, roles/suggestions/operations queries, merge selection bar, conflict/notice banners, dialogs, empty/loading/error states, session-resume of the completed extraction job (sessionStorage key only — durable truth stays in the backend). |
| `frontend/src/components/object-gallery/RoleCard.tsx` | NEW role evidence card: status badges, confidence summary + threshold bar, reasons (VN labels + raw codes), provenance, scene coverage, REAL bbox footprint SVG, artifact metadata tiles, merge source/target controls, confirm/split actions — every button has a Vietnamese helper line (11px, readable on dark theme). |
| `frontend/src/components/object-gallery/SuggestionCard.tsx` | NEW T03 suggestion card: pair, confidence bar, low-confidence flag ("không tự động xác nhận"), reasons/provenance, merge + dismiss actions with helper lines. |
| `frontend/src/components/object-gallery/ConfirmDialog.tsx` | NEW accessible dialog: `role="dialog"`/`aria-modal`, focus into + restore, Escape close, Tab trap, explicit primary/cancel buttons. |
| `frontend/src/components/object-gallery/galleryUtils.tsx` | NEW shared helpers: confidence summaries, reason labels, footprint SVG, artifact tiles, status region. |
| `frontend/src/lib/api.ts` | APPENDED S08 types + functions: `listObjectRoles`, `getObjectRole`, `submitObjectExtraction`, `getExtractionJob`, `getExtractionOutputs`, `generateGroupingSuggestions`, `listGroupingSuggestions`, `dismissSuggestion`, `confirmObjectRole`, `mergeObjectRoles`, `splitObjectRole`, `listGroupingOperations` (all typed against the real DTOs). |
| `frontend/src/components/layout/AppNav.tsx` | ONE nav item: "Thư viện đối tượng" (`/object-gallery`). |
| `frontend/e2e/s08-t04-helpers.ts` | NEW E2E helper: real-API project/video/chain/extraction/role/occurrence/suggestion/merge/confirm operations + real-scene extraction. |
| `frontend/e2e/s08-t04-object-gallery.spec.ts` | NEW interaction suite (13 tests, serial, dedicated role names, real backend). |
| `frontend/e2e/s08-t04-object-gallery-mobile.spec.ts` | NEW 390px read-only suite (3 tests). |
| `frontend/e2e/s08-t04-object-gallery-visual.spec.ts` | NEW visual QA (desktop + 390px screenshots). |
| `frontend/playwright.s08t04.config.ts` | NEW Playwright config (desktop + mobile-390px projects, isolated output). |
| `frontend/e2e/fixtures/s08t04-scenes-8s.mp4` | NEW REAL multi-scene fixture (4 segments, 8s, ffmpeg) so the scene detector creates 4 REAL scene rows for cross-scene grouping evidence. |
| `docs/pm/sessions/S08-T04-object-gallery/LOG.md` | appended (append-only, real evidence). |
| `docs/pm/sessions/S08-T04-object-gallery/REPORT.md` | this report. |

No changes to: backend Python, migrations, schemas, routes, S05/S06 code,
TASK.md, sprint contract, PM_REVIEW.md, channels.json, data/, databases,
fixtures (other than the new video fixture), MAIN or other worktrees.

## Acceptance criteria — evidence

| AC | Evidence |
|---|---|
| Users review candidates grouped by durable Object Role with REAL T03 APIs and managed representative media; no production mock/fallback | All UI data comes from `GET /api/v2/object-intelligence/roles` (occurrences eager-loaded), extraction job outputs, grouping suggestions/operations. Extraction submit passes NO provider — the QA backend selects the deterministic adapter via `MOTIONFORGE_EXTRACTION_PROVIDER` env; the production default path was observed failing closed (503 `provider 'model' is not available`) during QA bring-up. |
| Loading, empty, error, retry, partial-artifact, low-confidence and stale-state experiences explicit | E2E 01 (empty CTA → extraction → roles), 03 (skeleton via delayed real response), 04 (error panel + "Thử lại" recovery), 02 (artifact tiles with explicit "API hiện chưa phục vụ xem trước byte" note + "Không có ảnh mẫu" placeholder), 05/06 (low-confidence 35% cards flagged, never auto-confirmed), 08/12 (real 409 conflict banners + refetch). |
| Display confidence reasons, provenance, scene coverage, thumbnails/masks, confirmed/suggested status honestly | RoleCard shows average/min confidence with threshold bar, reason codes + VN labels, algorithm/version/source, distinct scene count + frame ranges, real bbox footprint, artifact purpose/dimensions/SHA-256/size tiles, status badges (Đề xuất/Đã xác nhận/Đã thay thế). E2E 02 asserts each element with real values (62%, deterministic-scene-layout, deterministic-layout v1.0.0, 1 cảnh, Ảnh mẫu/Mặt nạ tiles). |
| Merge/split/confirm require clear selection and confirmation; low confidence never auto-confirmed | Every mutation opens ConfirmDialog (E2E 07 Escape no-op then confirm; 09 split selection dialog; 10 manual target+source selection bar; 11 confirm dialog; 06 dismiss dialog). Nothing auto-confirms: generate only creates pending suggestions (E2E 05/13), low-confidence roles carry warning copy and the same explicit path. |
| Keyboard/focus/dialog semantics | ConfirmDialog: focus moves in on open, restores on close, Escape closes, Tab trapped (implementation); E2E asserts Escape open/close behavior (07/12/m2) and dialog stays within the 390px viewport (m2). |
| Responsive 390px with no horizontal overflow | E2E m1-m3 + visual test assert `scrollWidth <= clientWidth + 1` at 390px and dialog bounding box within the viewport. |
| Preserve existing Import/Analyze + Character Library navigation/UX | AppNav keeps all existing items; gallery adds one item; chain-not-ready state links back to `/import-analyze?project=...` (E2E-visible state; S05/S06 suites below pass unchanged). |

## Validation — exact commands and results

All pytest runs: `-p no:cacheprovider`, isolated shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08t04-*` (Windows MAX_PATH lesson).

```
1. Frontend type/lint/build:
   cd frontend
   npx tsc --noEmit                        -> exit 0 (no output)
   npx eslint <all 8 T04 files>            -> exit 0 (0 errors, 0 warnings)
   npm run build                           -> ✓ Compiled successfully; /object-gallery static route; exit 0

2. Playwright — REAL isolated backend (desktop + 390px):
   npx playwright test --config playwright.s08t04.config.ts
   -> 18 passed (40.0s)   [desktop 15/15 incl. 2 visual; mobile-390px 3/3]
   Screenshots: output/s08-sprint/20260816-s08t04-r1/screenshots/
     desktop-gallery-with-suggestions.png, desktop-confirm-dialog.png,
     mobile-390px-gallery.png

3. Backend T01-T03 regressions:
   python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
     tests/test_object_extraction.py tests/test_object_extraction_api.py \
     tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-backend-reg
   -> 96 passed, 87 warnings in 49.77s

4. S05/S06 interaction smoke (shallow basetemp):
   python -m pytest <7 S05 files> <4 S06 character files> -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-s05s06-smoke
   -> 112 passed, 111 warnings in 118.09s

5. Ruff: N/A (no Python changed). Mypy: python -m mypy app
   -> Success: no issues found in 82 source files (baseline parity).
   git diff --check -> exit 0 (pre-existing CRLF advisories only).
   git status --short -> 127 entries (baseline 119 + 8 new T04 files), no strays.

6. Protected data (MAIN):
   channels.json SHA-256 = dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
     (UNCHANGED vs T01/T02/T03 baseline)
   data/motionforge.db  = 311296 bytes, SHA-256 67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6,
     alembic d5e6f7a8b9c0, 17 tables (UNCHANGED vs baseline)
```

## Isolation and protected state

- All tests/runtime/E2E used the isolated QA root
  `output/s08-sprint/20260816-s08t04-r1/backend-root` (fresh database, migrations
  bootstrapped there) and pytest shallow basetemps. The worktree `alembic.ini`
  sets no URL; no production database was targeted.
- ONE incident: an early QA backend launch ran with the default
  `MOTIONFORGE_ROOT` (environment not inherited) and bootstrapped/migrated the
  MAIN `data/motionforge.db` (see LOG.md §11). Byte-exact remediation from the
  verified pre-incident backup (`...bak-20260816T091802-4174cef8`, SHA
  67d5c773…f2e6) restored 311296 B / d5e6f7a8b9c0 / 17 tables; the smoke residue
  project was removed; `channels.json` was never touched; the final protected-data
  gate passes. Recurrence prevented via an env-inline launcher script.
- No commit/push/deploy/reset/checkout/restore/clean/stash/delete; all
  pre-existing uncommitted changes preserved.

## Deviations and risks

1. **Artifact byte preview is not servable by the current API** (no S08
   artifact-content endpoint; TASK.md forbids backend contract redesign). The
   gallery renders the REAL bbox footprint from occurrence geometry and the REAL
   registered artifact metadata, with an explicit honest note — never a fake
   thumbnail. This is recorded as a deliberate scope-constrained trade-off;
   T06/Codex may decide a content endpoint is needed for visual previews.
2. **New multi-scene fixture** (`s08t04-scenes-8s.mp4`) was required: T01
   occurrence ownership only accepts REAL Scene rows, and the previous 4s
   fixture produces a single scene.
3. **Test 12** exercises the stale-conflict UX through a merge-based external
   writer: `CONFIRM:<role>` is the natural key, so a repeated confirm of the
   same role is an idempotent replay (200) by design — a merge bumping the
   target's revision produces the genuine 409.
4. **Grouping suggestions on raw T02 output are name-driven** (subject_01…
   differ), so the E2E seeds curation roles via the real T01 API (same-name
   pairs on real scenes) to exercise the T03 algorithm end-to-end; this is the
   same data-shaping the T03 suite uses, not mocked data.
5. **Playwright `test-results/` is empty** because all tests passed (failure-only
   artifacts); the reporter output is the evidence.
6. The gallery's project entry is `?project=` (project picker when absent) —
   consistent with the Import/Analyze screen's pattern.

## Recommended manager state

`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` — T04 deliverables complete and
verified; Codex review at sprint exit owns APPROVED/CLOSED.

## Manager verification (2026-08-16)

**Internal state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`** — recorded by the
sprint manager after independent re-run. NOT APPROVED; Codex sprint-exit review
owns approval.

Manager re-runs: backend T01-T03 96/96 (49.22s); tsc/eslint/next build exit 0;
fresh manager E2E 16/16 (30.7s, isolated backend root 20260816-s08t04-mgr,
ports 8014/3012 verified and cleaned); worker visual E2E 18:29 valid (0 TS
changes after); manager screenshot gallery-empty-state-manager.png. Protected
state unchanged (channels.json SHA dd7aae26…555; MAIN DB 311296 B). Worker
session: 20260816_170337_74161b (fresh, exit 0).

## CORRECTION ROUND (Codex CHANGES_REQUESTED, finding E) — 2026-08-17

**Status: SUBMITTED** (unchanged — never APPROVED; Codex sprint-exit review owns approval)
**Scope:** finding E only. No backend contract redesign; no mock/fake data; no
MAIN/other-worktree writes; no destructive Git.

### What changed (frontend/E2E/config/docs only — allowed scope)

| File | Change |
|---|---|
| `frontend/src/lib/api.ts` | `roleMediaContentUrl` now ABSOLUTE (Next dev proxy hardcodes :8888 — relative media URLs 500'd); `listObjectRoles` paginated (limit/offset); added `getCurrentExtraction` (backend `/current`, source-generation filtered), `getGroupingPolicy`, `listProjectVideos`; types `RoleMedia`, `ExtractionCandidate.role_id`, `GroupingPolicyData`, video-item DTOs. |
| `frontend/src/components/object-gallery/useGallery.ts` (NEW) | Bounded hooks: policy (backend thresholds), chain, videos (404→empty for legacy projects), extraction (backend-truth restore — NO sessionStorage), roles-paged (infinite load, re-hydrates when the first-page payload changes), role-detail (lazy expand), grouping (generate/dismiss/confirm + operations), corrections (preview/apply/retry/recompute poll). |
| `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` | Rewritten as a slim orchestrator over the hooks (was 1,611 lines); `?video=` explicit stable selection; policy thresholds rendered from `/grouping/policy`; paginated role summaries + lazy detail on expand; loading/empty/error/retry/409/recompute states preserved; 390px no-overflow preserved. |
| `frontend/src/components/object-gallery/RoleSummaryCard.tsx` (NEW) | Paginated summary card: name/status/counts/real-media thumbnail (contained endpoint), `aria-expanded` expand, NO eager occurrence rows. |
| `frontend/src/components/object-gallery/VideoSelector.tsx` (NEW) | Explicit project-video selector: durable v2 items when available + chain current-video fallback chip; selection by stable `video_item_id`. |
| `frontend/src/components/object-gallery/RoleCard.tsx` | Media (association-resolved, newest-valid) is the ONLY image authority — the name-matched `artifacts` fallback is REMOVED; `reviewThreshold` prop from backend policy; `data-testid="role-detail"`. |
| `frontend/src/components/object-gallery/SuggestionCard.tsx` | Low-confidence flag + threshold line driven by the backend policy value (never 0.5); calibration version shown as provenance. |
| `frontend/src/components/object-gallery/galleryUtils.tsx` | Hardcoded `LOW_CONFIDENCE_THRESHOLD`/`LOW_SUGGESTION_THRESHOLD` removed; `ConfidenceBar` takes the policy threshold; `MediaTile` renders REAL bytes via the contained endpoint. |
| `frontend/src/app/(app)/object-gallery/page.tsx` | Reads `?video=` and wires `onVideoChange` (router.replace). |
| `frontend/playwright.s08t04.config.ts` | New run root `output/s08-sprint/20260816-s08t04-c1-r1/` (backend :8025); project testMatch anchored on the s08-t04 prefix so no other task's specs run. |
| `frontend/e2e/*` | Helpers: paged roles, `/current`, policy, correction apply-helper, `runExtraction`, `seedRoles`, fixture `s08t04-single-2s.mp4`. Specs: 13 desktop tests + 3 mobile + 2 visual covering EVERY finding-E item (below). |

### Finding E — per-item evidence (all E2E, real isolated backend :8025)

1. **Stable role ids only** — media comes exclusively from `RoleData.media`
   (backend `object_role_artifact`, `superseded_by_id IS NULL`); the name-matched
   artifacts path was deleted. E2E 03 asserts the rendered `<img>` src is the
   contained endpoint of the role's CURRENT media association.
2. **REAL bytes via the content endpoint** — E2E 03 asserts the DECODED
   `naturalWidth`/`naturalHeight` equal the registered `media.width`/`height`
   (320×240 mask) and the src path contains
   `/extraction/{job}/artifacts/{artifact}/content`.
3. **Fresh browser, empty sessionStorage, backend truth** — E2E 04 (desktop) and
   m3 (390px): new browser context, gallery restores roles + extraction + media
   from `GET /extraction/current`; asserts the app's storage namespace stays empty
   (the one residual sessionStorage entry is the Next dev client, not the app).
4. **Source replacement never shows previous-generation media** — E2E 07 uploads a
   second REAL video to the same project; `getCurrentExtractionApi` per video
   returns the generation-filtered job (B → jobB, never jobA); B's role media
   `source_job_id === jobB`; per-video gallery isolation asserted in the UI.
5. **Explicit project video selector** — `VideoSelector` renders for every project
   (durable v2 items when available + chain current-video chip); `?video=` drives
   selection by stable id; E2E 07 switches A↔B and asserts the role sets differ
   with zero leakage.
6. **Thresholds from backend policy** — E2E 05 asserts the header line
   "Ngưỡng duyệt gộp: 35%" + calibration + semantics <details> all come from
   `GET /grouping/policy`; subject_01@0.62 renders NO low-confidence badge —
   proving the legacy 0.65 hardcode is gone (0.62 < 0.65 would have flagged).
7. **Pagination / infinite load + lazy detail** — E2E 06: 44 roles, page 1 = 16
   summaries, "Tải thêm" → 32 (counter "Đã hiển thị 32/44"), page 3 → all loaded
   and the control disappears; `role-detail` count is 0 before expand; expanding
   fires the authoritative `GET /roles/{id}` (waitForRequest) and renders the
   heavy occurrence rows only then.
8. **Panel split** — 1,611-line panel decomposed into `useGallery.ts` hooks +
   `RoleSummaryCard`/`VideoSelector`/`ExtractionStrip`/`ErrorPanel`/dialog bodies;
   the orchestrator is bounded (~700 lines incl. dialogs).
9. **a11y/UX states + 390px preserved** — loading skeletons, empty CTA, error +
   retry, extraction progress, partial media (no-current-media honest tile),
   low-confidence (policy threshold, never auto-confirmed), stale 409 + refetch,
   recompute progress/failed/cancelled strips, focus-trap dialogs; mobile m1/m2
   assert `scrollWidth - clientWidth === 0` at 390px.
10. **Import/Analyze + Character Library preserved** — AppNav untouched this round;
    chain-not-ready gate links to `/import-analyze`; S05/S06 suites pass (below).

### Validation — exact commands + verbatim results (fresh isolated roots)

```
$ cd frontend && npx tsc --noEmit                                    -> exit 0
$ npx eslint <T04 files (9)>                                          -> 0 errors / 0 warnings
$ npm run build                                                       -> exit 0
$ npx playwright test --config playwright.s08t04.config.ts --list     -> 18 tests in 3 files
                                                                        (desktop 15 = 13 interaction + 2 visual; mobile 3)
$ npx playwright test --config playwright.s08t04.config.ts            -> 18 passed (1.3m)
   screenshots: output/s08-sprint/20260816-s08t04-c1-r1/screenshots/
     gallery-desktop.png, gallery-desktop-detail.png

$ python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
    tests/test_object_extraction.py tests/test_object_extraction_api.py \
    tests/test_object_correction.py tests/test_object_correction_api.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c1-backend
  -> 161 passed, 293 warnings in 84.84s

$ python -m pytest tests/test_persistence_bootstrap.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c1-mig
  -> 40 passed, 68 warnings in 18.55s   (migration round-trip; head == f6a7b8c9d0e1)

$ python -m pytest tests/test_video_item_crud.py tests/test_channel_workspace.py \
    tests/test_channel_crud.py tests/test_s05_*.py tests/test_character_*.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c1-s020506
  -> 195 passed, 365 warnings in 164.36s   (S02/S05/S06 regressions, shallow basetemps)

$ python -m mypy app    -> Success: no issues found in 86 source files
$ git diff --check      -> exit 0 (pre-existing CRLF advisories only)
$ ruff check <changed .py> -> 17 pre-existing E501 in the historical committed migration
                              d5e6f7a8b9c0_character_library_schema.py (S06-T01); NOT touched
                              (this round changed zero Python files)
```

### Protected data (re-verified)

- MAIN `channels.json` SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` — UNCHANGED.
- MAIN `data/motionforge.db` 311296 bytes — UNCHANGED.
- SAM2.1 checkpoint read-only — no files modified since 2026-08-17 00:00.

### Deviations / honest notes

1. Legacy projects cannot enumerate their historical video items via any API
   (the v2 videos endpoint serves only durable UUID projects, which cannot host
   S08 gallery data). The selector therefore lists the durable items when
   available plus the chain's current video, and honors explicit `?video=` stable
   ids for older items (E2E 07 drives both directions through the real backend).
2. `candidate_edit` name-only corrections do NOT recompute media by design
   (recompute_needed=False) — the correction-media E2E (13) uses a merge
   correction, which DOES re-publish + supersede artifact associations; the new
   media stays resolvable after a full browser restart (asserted in a fresh
   context).
3. ruff E501 findings are pre-existing in a committed historical migration;
   fixing them would alter a migration file out of the correction scope.

**Recommended manager state:** `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (this
round re-submits; Codex sprint-exit review owns APPROVED/CLOSED).

## CORRECTION ROUND C2 (Codex CHANGES_REQUESTED — GALLERY GENERATION ISOLATION) — 2026-08-17

**Status: SUBMITTED** (unchanged — never APPROVED; Codex sprint-exit review owns approval)
**Scope:** finding C2 only. No backend contract redesign; no mock/fake data; no
MAIN/other-worktree writes; no destructive Git.

### Per-acceptance evidence (all against the REAL isolated QA backend :8026)

| AC | Evidence |
|---|---|
| 1. Gallery renders ONLY roles of the current source generation (backend-authoritative) | The roles list call sends NO generation param → T01-C2 returns `scope="current"` + `current_generation` (role rows strictly of the backend current generation). `useGalleryRolesPaged` exposes `currentGeneration`; the panel header shows "Thế hệ nguồn hiện tại (máy chủ): N" from the backend response, not the client hint. E2E 14 asserts `listRolesMeta` scope=current/current_generation="1". |
| 2. Source replacement gen 1 → 2: gen-1 roles/suggestions never appear in the gen-2 gallery | Built with REAL data: `createRole(source_generation="2")` on a current-gen-1 video (public T01 API). E2E 14 asserts the default list EXCLUDES the stale role, the explicit `?generation=2` view is `scope="historical"`, and default detail is 404 (fail-closed). E2E 15 covers the legacy replacement shape (video-item supersession): video B's gallery contains zero video-A (gen-1) roles, `current_generation="1"` for both items. |
| 3. No action controls for stale roles/suggestions | Stale roles/suggestions are invisible (current-only lists) → no row → no merge/split/confirm/correct controls. E2E 14 asserts 4 current cards render and the stale card/button count is 0; the article count under "Vai trò của video" is exactly 4. RoleCard actions additionally gated by `!superseded`. |
| 4. Frontend API calls pass/verify the current generation | Gallery derives `authoritativeGeneration` from the backend responses and passes it into every mutation payload (merge/split/reassign/edit) and the header; `generateGroupingSuggestions` carries `source_generation` (T03-C2 fails closed if it mismatches the backend current — E2E 14 asserts a gen-2 generate for a gen-1 video is rejected with an API 4xx). |
| 5. React Query keys include videoItemId + generation | `["object-roles", videoItemId, generation, 0]`, `["object-role-detail", roleId, generation]`, `["grouping-suggestions"\|"grouping-operations", videoItemId, generation]`. E2E 15 proves distinct requests fire per video (waitForRequest on the `/roles?video_item_id=…` URL for A then B) — no cross-video cache reuse. |
| 6. Invalidate old cache on source/generation change | A `useEffect` watches `(videoItemId, generationForVideo)` and `removeQueries` the previous `object-roles`/`grouping-suggestions`/`grouping-operations`/`object-role-detail` slices (finding C2 #6). All hook invalidations now target the generation-scoped slice. |
| 7. Real media rendering via stable content URL + decoded dimensions (T04-C1 preserved) | E2E 03 still asserts `naturalWidth/naturalHeight` equal the registered media dims via `roleMediaContentUrl` (absolute contained endpoint). No name-based matching anywhere (probe/backends assert nothing by name). |
| 8. 390px no-overflow, a11y, loading/empty/error/retry/stale preserved (T04-C1 preserved) | Mobile suite m1–m3 re-passes on the C2 root; desktop suite 01–13 all re-pass untouched. |
| 9. Add E2E tests for source replacement / current-only rendering / stale-control omission | NEW tests 14 + 15 in `s08-t04-object-gallery.spec.ts` (see validation below). |

### Validation — exact commands + verbatim results (fresh isolated roots)

```
$ cd frontend && npx tsc --noEmit   -> exit 0
$ npx eslint <9 T04 files>          -> 0 errors / 0 warnings
$ npm run build                     -> exit 0
$ npx playwright test --config playwright.s08t04.config.ts --list
    -> Total: 20 tests in 3 files (desktop 17: 15 interaction + 2 visual; mobile 3)
$ QA_API_BASE=http://localhost:8026 npx playwright test --config playwright.s08t04.config.ts
    -> 20 passed (1.5m)   [desktop 17/17 incl. C2 14+15 + visual; mobile-390px 3/3]
   screenshots: output/s08-sprint/20260816-s08t04-c2-r1/screenshots/gallery-desktop.png,
                gallery-desktop-detail.png   (NEW root — never overwrote C1/original)

$ python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
    tests/test_object_extraction.py tests/test_object_extraction_api.py \
    tests/test_object_correction.py tests/test_object_correction_api.py \
    tests/test_sam2_provider.py tests/test_sam2_smoke.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c2-bk2
  -> 186 passed, 370 warnings in 113.40s

$ python -m pytest tests/test_s05_*.py tests/test_durable_job_api.py \
    tests/test_durable_job_persistence.py tests/test_durable_worker.py \
    tests/test_video_item_crud.py tests/test_channel_workspace.py \
    tests/test_channel_crud.py tests/test_persistence_bootstrap.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c2-bk3
  -> 259 passed, 467 warnings in 200.34s  (S05 41-suite + S02 durable + migration
                                            round-trip; head == f6a7b8c9d0e1)

$ python -m mypy app   -> Success: no issues found in 86 source files
$ git diff --check     -> exit 0 (pre-existing CRLF advisories only)
$ ruff <changed .py>   -> N/A (this round changed ZERO python files)
$ git status --short   -> 161 entries (baseline, intended); no strays
```

### Protected data (MAIN tree, re-verified)

- `channels.json` SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` — UNCHANGED.
- `data/motionforge.db` 311296 bytes — UNCHANGED.
- `models_checkpoints/sam2.1_hiera_large.pt` 898083611 bytes, mtime 29-Jul (untouched),
  SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` — UNCHANGED.

### Honest notes

1. A single legacy video item's generation advances to 2 only when its durable
   source artifact changes (T02-C2 source authority). That transition is NOT
   reachable through the legacy public flow (replacement = video-item
   supersession, each new item starts at its own generation 1). The E2E
   therefore builds the stale-generation state with REAL data through the public
   T01 API (`createRole(source_generation="2")`); the backend's current-only
   filters + stale-detail 404 + closed generate guard are all asserted.
2. The QA backend for this run needed `MOTIONFORGE_EXTRACTION_QA_MODE=1` (T02-C2
   provider gate) — verified fail-closed (503) when absent.

**Recommended manager state:** `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` (resubmit;
Codex sprint-exit review owns APPROVED/CLOSED).

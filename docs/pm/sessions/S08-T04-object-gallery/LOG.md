# S08-T04 — Execution Log

Status: NOT_STARTED

Append-only. Record exact session, guards, changes, commands, results, incidents
and protected-state comparisons.

---

## 2026-08-16 — Full session log (S08-T04 worker)

**Hermes session:** `20260816_170337_74161b` (fresh S08-T04 worker session)

### 1. Hard worktree guard (verified before ANY write)

```
$ pwd
/c/Users/Admin/MotionForge2D-worktrees/s08-integration
$ git rev-parse --show-toplevel
C:/Users/Admin/MotionForge2D-worktrees/s08-integration
$ git branch --show-current
codex/s08-integration
$ git rev-parse HEAD
a43b20da742996bafcb2f9d1ac57b10d3f1a5204
$ git status --short
127 entries at end of session (baseline 119 at T03 end + 8 new T04 files);
pre-existing dirty state (T01-T03 + S05/S06 artifacts) fully preserved.
```
Guard: PASS — all five checks matched; no MAIN/worktree writes outside scope.

### 2. Required reading (complete)

- `C:/Users/Admin/MotionForge2D/docs/pm/SESSION_PROTOCOL.md` (147 lines)
- `docs/pm/sprints/S08-SPRINT_CONTRACT.md` (49 lines)
- `docs/pm/sessions/S08-T04-object-gallery/TASK.md` + `START_PROMPT.md`
- `frontend/AGENTS.md` + `docs/architecture/UI_UX_DESIGN_STANDARD.md` (161 lines)
- T01/T02/T03 `REPORT.md` (manager-verified dependency evidence)
- `app/api/routes/object_intelligence.py`, `object_grouping.py`, `object_extraction.py`
- `app/schemas/object_intelligence.py`, `object_grouping.py`, `object_extraction.py`
- `frontend/src/lib/api.ts`, `AppNav.tsx`, characters/import-analyze pages, P00 E2E config

### 3. Implementation (all within TASK.md allowed write scope)

New files:
- `frontend/src/app/(app)/object-gallery/page.tsx` — gallery route (Suspense + ?project=)
- `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` — orchestrator (all states)
- `frontend/src/components/object-gallery/RoleCard.tsx` — role evidence card
- `frontend/src/components/object-gallery/SuggestionCard.tsx` — T03 suggestion card
- `frontend/src/components/object-gallery/ConfirmDialog.tsx` — accessible dialog (focus trap, Escape, focus restore)
- `frontend/src/components/object-gallery/galleryUtils.tsx` — confidence/footprint/artifact helpers
- `frontend/e2e/s08-t04-helpers.ts`, `s08-t04-object-gallery.spec.ts`,
  `s08-t04-object-gallery-mobile.spec.ts`, `s08-t04-object-gallery-visual.spec.ts`
- `frontend/playwright.s08t04.config.ts`
- `frontend/e2e/fixtures/s08t04-scenes-8s.mp4` — REAL 4-segment multi-scene fixture (ffmpeg,
  testsrc + 3 color segments + sine audio, 8s 320x240)

Modified (minimal):
- `frontend/src/lib/api.ts` — S08 T01/T02/T03 types + client functions (append-only)
- `frontend/src/components/layout/AppNav.tsx` — one nav item "Thư viện đối tượng"

No backend Python, migrations, data, fixtures (other than the new video fixture),
channels.json, or MAIN-tree files were touched.

### 4. Frontend gates (exact commands + verbatim results)

```
$ cd frontend && npx tsc --noEmit
(no output; exit 0)

$ npx eslint src/components/object-gallery "src/app/(app)/object-gallery" \
    src/lib/api.ts src/components/layout/AppNav.tsx \
    e2e/s08-t04-helpers.ts e2e/s08-t04-object-gallery.spec.ts \
    e2e/s08-t04-object-gallery-mobile.spec.ts e2e/s08-t04-object-gallery-visual.spec.ts
(no output; exit 0 — 0 errors, 0 warnings in all T04 files)

$ npm run build
✓ Compiled successfully in 3.8s
✓ Generating static pages using 11 workers (9/9)
Route (app) — /object-gallery listed among static routes
BUILD_EXIT=0
```

### 5. QA backend (REAL isolated root, deterministic provider via env)

```
$ cat output/s08-sprint/20260816-s08t04-r1/run-qa-backend.sh
MOTIONFORGE_ROOT=output/s08-sprint/20260816-s08t04-r1/backend-root
MOTIONFORGE_OUTPUT=<root>/output
MOTIONFORGE_MODELS=<root>/models
MOTIONFORGE_EXTRACTION_PROVIDER=deterministic
python -m uvicorn app.main:app --app-dir <worktree> --port 8014

Frontend: npm run dev -p 3012 (NEXT_PUBLIC_API_URL=http://localhost:8014)
```

End-to-end data smoke on the QA root (before the E2E suites):
```
POST /api/projects -> t04-smoke2 (9bd1b36d5bb1)
POST /api/projects/{id}/video + POST /analyze -> chain completed, 1 cảnh
POST /api/v2/object-intelligence/extraction -> job aaf926df... completed 100.0
GET  /api/v2/object-intelligence/roles -> subject_01 suggested 1 occ conf 0.62
```
Multi-scene fixture check (t04-scenes-check, 8s 4-segment):
```
chain=completed scenes=4
roles total: 4 -> subject_04 0.8 / subject_03 0.74 / subject_02 0.68 / subject_01 0.62
real scene ids: 4 distinct Scene rows (d62e..., 558e..., 9cf0..., 2e2d...)
```

### 6. Playwright E2E — REAL isolated backend, desktop + 390px

```
$ cd frontend && npx playwright test --config playwright.s08t04.config.ts
[desktop] 15/15 passed (2 visual + 13 interaction)
[mobile-390px] 3/3 passed
18 passed (40.0s)   <- final run, exit 0
```

Coverage (per test, all against real backend data):
- 01 empty state -> UI-driven extraction submit -> real progress -> roles appear (captures job id)
- 02 role cards: confidence %, reasons (deterministic-scene-layout), provenance
  (deterministic-layout v1.0.0), scene coverage, artifact tiles (Ảnh mẫu/Mặt nạ metadata
  + honest "chưa phục vụ xem trước byte" note), extraction summary strip
- 03 loading skeleton (real delayed response via route delay 1.5s)
- 04 roles error -> error panel + "Thử lại" -> recovery (route abort once, real data after)
- 05 generate via UI -> high (90%) + low (35%) confidence suggestion cards with
  reasons + provenance; low-confidence card explicitly flagged
- 06 explicit dismiss of a low-confidence suggestion (dialog) -> count decreases
- 07 merge via suggestion: dialog (Escape no-op) -> real merge -> target 2 occurrences,
  source superseded, audit history
- 08 consumed suggestion disappears (backend marks applied) + stale manual merge ->
  REAL 409 -> conflict banner + refetch
- 09 split via explicit selection + dialog -> "Đã tách vai trò"
- 10 manual merge selection (source checkbox + target radio + merge bar) -> real merge
- 11 confirm role via explicit dialog -> moves to "Vai trò đã xác nhận"
- 12 stale revision: external writer merges into the target after dialog open ->
  UI confirm -> REAL 409 -> conflict banner + refetch (superseded section grows)
- 13 backend guards: Hero:superseded, Warrior A:superseded, Warrior B:confirmed,
  Stale Feeder:superseded, Stale Solo:suggested; suggestion lifecycle applied+dismissed present
- m1-m3 390px: no horizontal overflow (scrollWidth <= clientWidth+1), dialog within
  viewport + Escape close, low-confidence chip + suggestion section visible

Screenshots (final run, output/s08-sprint/20260816-s08t04-r1/screenshots/):
- desktop-gallery-with-suggestions.png (504468 B)
- desktop-confirm-dialog.png (503854 B)
- mobile-390px-gallery.png (445210 B)

### 7. Backend regressions (pytest, cache disabled, shallow basetemp)

```
$ python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
    tests/test_object_extraction.py tests/test_object_extraction_api.py \
    tests/test_object_extraction_production_wiring.py -q -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-backend-reg
96 passed, 87 warnings in 49.77s
```

### 8. S05/S06 interaction smoke (shallow basetemp)

```
$ python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
    tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
    tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
    tests/test_s05_golden_integration.py tests/test_character_domain.py \
    tests/test_character_read_api.py tests/test_character_preset_importer.py \
    tests/test_character_validator.py -q -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-s05s06-smoke
112 passed, 111 warnings in 118.09s
```

### 9. Ruff / mypy / diff-check / status

- Ruff: N/A — no Python files changed by T04 (`git status --short | grep "\.py$"` empty
  for modified files; only pre-existing T01-T03 untracked Python remain).
- Mypy: `python -m mypy app` -> `Success: no issues found in 82 source files`
  (baseline parity with T03; backend untouched).
- `git diff --check` -> exit 0 (pre-existing CRLF advisories only).
- Final `git status --short` -> 127 entries = T03 baseline 119 + 8 new T04 files, no strays.

### 10. Protected state (MAIN tree)

```
$ cd C:/Users/Admin/MotionForge2D
channels.json SHA-256 : dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
  (matches the T01/T02/T03 recorded baseline — UNCHANGED)
data/motionforge.db  : 311296 bytes, SHA-256 67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6,
  alembic_version d5e6f7a8b9c0, 17 tables (matches protected baseline — UNCHANGED)
MAIN git status      : 49 entries (T03 end 48 + manager's scripts/watch-s08-t04.sh)
No object/gallery residue on MAIN.
```

### 11. INCIDENT — bare uvicorn bootstrap of the MAIN database (17:17-17:25)

Root cause: the FIRST QA backend attempt was launched with `python -m uvicorn
app.main:app` from a shell whose earlier `export MOTIONFORGE_ROOT=...` was NOT
inherited by the background process (the runner process got a clean environment),
so `app/config.py` fell back to the default `MOTIONFORGE_ROOT = ~/MotionForge2D`
(MAIN). The lifespan then ran all migrations on MAIN `data/motionforge.db`
(d5e6f7a8b9c0 -> f3a4b5c6d7e8, 311296 -> 450560 bytes, +4 S08 tables) and a
smoke test wrote a legacy project under MAIN `projects/141f59d8348a/`.

Remediation (byte-exact):
- Verified MAIN DB pre-incident baseline = `data/motionforge.db.bak-20260816T091802-4174cef8`
  (311296 B, SHA-256 67d5c773...f2e6; byte-identical to the newer
  `.bak-20260816T101845-d452d30d` backup and to the T01/T02/T03 protected baseline).
- Restored `cp bak-20260816T091802-4174cef8 data/motionforge.db` -> 311296 B,
  version d5e6f7a8b9c0, 17 tables, SHA-256 67d5c773...f2e6 (final gate re-verified).
- Removed the smoke residue `projects/141f59d8348a/` (the only file created).
- `channels.json` never changed (SHA matched baseline throughout).
- Prevented recurrence: all later QA backend starts use `run-qa-backend.sh`, which
  sets MOTIONFORGE_ROOT/OUTPUT/MODELS/PROVIDER INLINE in the process environment,
  and the extraction provider fail-closed path (503 `provider 'model' is not
  available`) was observed and is covered by T02 tests.
- Recorded in this LOG; final protected-state gates (section 10) pass.

### 12. Verification re-run (post-submit) + env-leak note

A fresh verification pass after REPORT/LOG submission surfaced ONE pytest failure
(`test_provider_resolution_deterministic_and_model_fail_closed`). Root cause: the
QA shell still exported `MOTIONFORGE_EXTRACTION_PROVIDER=deterministic`, and that
test intentionally reads the production default from `os.environ` when no explicit
env dict is passed — a QA env leak, not a regression (the same suite had passed
96/96 when the shell did not carry the var). After `unset MOTIONFORGE_EXTRACTION_PROVIDER
MOTIONFORGE_ROOT MOTIONFORGE_OUTPUT MOTIONFORGE_MODELS` the suite re-ran green:

```
$ python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
    tests/test_object_extraction.py tests/test_object_extraction_api.py \
    tests/test_object_extraction_production_wiring.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-verify-now
96 passed, 87 warnings in 55.02s
```

tsc/eslint/build re-verified (exit 0); the 18:29 E2E evidence (18/18, screenshots in
20260816-s08t04-r1/screenshots/) remains valid for the current tree — no TS/TSX file
changed after that run. Lesson: NEVER leave QA env vars exported in the interactive
shell while running environment-sensitive pytest suites; unset before verification.

## MANAGER VERIFICATION — 2026-08-16

**State: MANAGER_VERIFIED_PENDING_SPRINT_REVIEW** (internal gate; NOT APPROVED)

Manager independent evidence (re-run by manager, not worker):
- Backend T01-T03 suites (s08t04-mgr-backend): 96 passed in 49.22s (5 focused files, cache disabled, isolated basetemp)
- Frontend: tsc --noEmit exit 0; eslint (T04 files) exit 0; next build exit 0 (route /object-gallery static)
- Manager E2E (fresh isolated backend root output/s08-sprint/20260816-s08t04-mgr/, backend :8014 + next dev :3012): 16 passed in 30.7s (desktop 13: empty/loading/error/low-confidence, selection, merge/split/confirm dialogs, stale 409, retry; mobile 3: 390px no-overflow, dialog viewport, low-confidence chip). Visual 2 specs (worker 18:29, screenshots 20260816-s08t04-r1/screenshots) valid for current tree: 0 TS/TSX files changed after 18:29.
- Manager screenshot: output/s08-sprint/20260816-s08t04-mgr/screenshots/gallery-empty-state-manager.png
- Protected: MAIN channels.json SHA dd7aae26...555 UNCHANGED; MAIN data/motionforge.db 311296 B, SHA 67d5c773... UNCHANGED.
- Scope audit: object-gallery components/page, 4 e2e specs, playwright.s08t04.config.ts, api.ts + AppNav.tsx (T04 window) — all allowed scope. INTEG 127 = 119 + 8. Manager removed own stray migration_mgr_check.db (created 15:13 during T03 migration check).

Decision: T04 dependency released for S08-T05 under full-sprint manager protocol.

## CORRECTION ROUND (Codex CHANGES_REQUESTED, finding E) — 2026-08-17

Same project session; fresh worker pass. Branch `codex/s08-integration`, HEAD still
`a43b20d`; dirty state grew from 151 (round start) to 152 entries — only docs
added by this round; zero Python files changed.

### Guards

```
$ pwd && git rev-parse --show-toplevel && git branch --show-current && git rev-parse HEAD
/c/Users/Admin/MotionForge2D-worktrees/s08-integration
C:/Users/Admin/MotionForge2D-worktrees/s08-integration
codex/s08-integration
a43b20da742996bafcb2f9d1ac57b10d3f1a5204
```

QA backend (isolated): `output/s08-sprint/20260816-s08t04-c1-r1/run-qa-backend.sh`
→ uvicorn :8025, cwd+roots = `.../c1-r1/backend-root`, providers
`MOTIONFORGE_EXTRACTION_PROVIDER=deterministic` + `MOTIONFORGE_RECOMPUTE_PROVIDER=deterministic`
(env-immutable runner, inline). Frontend: `NEXT_PUBLIC_API_URL=http://localhost:8025
npx next dev -p 3012`.

### Dependency-round surfaces consumed (T02-C1 / T03-C1 / T05-C1, in-tree)

durable `object_role_artifact` associations + `RoleData.media` (newest-valid,
`superseded_by_id IS NULL`); contained image content endpoint (ETag=SHA-256,
nosniff, 404/409); `GET /extraction/current?source_generation=`; `GET
/grouping/policy` (review_threshold 0.35, calibration v2, semantics); T05
correction recompute media supersession (migration head f6a7b8c9d0e1).
Empirical probes against the real QA backend proved every surface BEFORE the E2E:

```
$ python s08t04-c1-probe.py            # 4 roles; per-role media 320x240; content = real
                                        # PNG (magic 89504e47…); /current 200, wrong-gen 404
$ python s08t04-c1-multivideo.py       # re-upload same project -> 2 video items;
                                        # roles A=4 / B=1 fully isolated
$ python s08t04-c1-correction.py       # name-edit: recompute_needed=False (no media touch)
$ python s08t04-c1-correction-merge.py # merge: recompute_needed=True,
                                        # media source_job_id 9e2aad7c -> 3a0de0a4 (NEW)
```

Two client bugs found only by running the real UI:
1. `useGalleryRolesPaged` hydrated the first page exactly once per video — a roles
   query that landed BEFORE extraction completed never refreshed after the
   extraction's invalidation (empty state stuck). Fixed by tracking the first-page
   payload identity and re-hydrating on every data change.
2. `roleMediaContentUrl` was RELATIVE — the Next dev proxy rewrites `/api` to a
   hardcoded :8888, so real byte images 500'd in the browser. Fixed to be
   ABSOLUTE (`API_BASE` prefix); E2E now asserts the DECODED naturalWidth/Height
   of the real rendered image.

### Files changed this round (all frontend/E2E/config/docs — allowed scope)

- `frontend/src/lib/api.ts` — `roleMediaContentUrl` absolute; `listObjectRoles`
  paged (limit/offset); added `getCurrentExtraction`, `getGroupingPolicy`,
  `listProjectVideos`; types `RoleMedia`/`ExtractionCandidate.role_id`/
  `GroupingPolicyData`/video DTOs.
- `frontend/src/components/object-gallery/useGallery.ts` (NEW, bounded hooks):
  policy / chain / videos (404→empty) / extraction (backend `/current`, no
  sessionStorage) / roles-paged (infinite load) / role-detail (lazy) / grouping /
  correction-preview / corrections (apply + recompute poll).
- `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` — rewritten as a
  slim orchestrator over the hooks (was 1,611 lines); `?video=` explicit selection;
  backend policy thresholds; paginated summaries + lazy detail; all UX states kept.
- NEW components `RoleSummaryCard.tsx`, `VideoSelector.tsx`; `RoleCard.tsx` /
  `SuggestionCard.tsx` / `galleryUtils.tsx` — media is the ONLY authority, no
  hardcoded 0.65/0.5, policy-driven threshold, `data-testid="role-detail"`.
- `frontend/src/app/(app)/object-gallery/page.tsx` — `?video=` + `onVideoChange`.
- `frontend/playwright.s08t04.config.ts` — C1 run root (port 8025); project
  testMatch anchored on the s08-t04 prefix (--list proved 18 tests in 3 files).
- E2E helpers + 3 specs rewritten; new fixture `s08t04-single-2s.mp4`.
- This LOG + REPORT (CORRECTION ROUND sections).

### E2E — exact command + verbatim result (full config, both projects)

```
$ npx playwright test --config playwright.s08t04.config.ts
  18 passed (1.3m)
  [desktop] visual gallery + visual expanded detail with real media
  [desktop] 01 empty state + start extraction (real durable job)
  [desktop] 02 roles + extraction strip reflect REAL backend state
  [desktop] 03 media is REAL bytes — decoded naturalWidth/naturalHeight match
  [desktop] 04 fresh browser with EMPTY sessionStorage restores from the backend
  [desktop] 05 confidence/review thresholds come from the BACKEND policy
  [desktop] 06 role summaries paginate; heavy detail loads lazily on expand
  [desktop] 07 explicit video selector — per-video isolation (multi-video project)
  [desktop] 08 confirm a role (explicit dialog, audit operation)
  [desktop] 09 suggestion merge runs through the correction workflow (scope preview)
  [desktop] 10 manual merge + stale revision surfaces the real 409 conflict
  [desktop] 11 split a merged role (explicit original selection)
  [desktop] 12 dismiss a suggestion (explicit rejection)
  [desktop] 13 correction media refresh — newest-valid media durable across restart
  [mobile-390px] m1/m2/m3 (no horizontal overflow; viewport; fresh-browser restore)
```

Screenshots (NEW run root, never overwrote the original):
`output/s08-sprint/20260816-s08t04-c1-r1/screenshots/gallery-desktop.png` +
`gallery-desktop-detail.png`.

### Regression suites (cache disabled, shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08t04-c1-*)

```
$ python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
    tests/test_object_extraction.py tests/test_object_extraction_api.py \
    tests/test_object_correction.py tests/test_object_correction_api.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c1-backend
  161 passed, 293 warnings in 84.84s

$ python -m pytest tests/test_persistence_bootstrap.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c1-mig
  40 passed, 68 warnings in 18.55s    (head == f6a7b8c9d0e1 migration round-trip)

$ python -m pytest tests/test_video_item_crud.py tests/test_channel_workspace.py \
    tests/test_channel_crud.py tests/test_s05_{atomic_cancel,chain_progression,golden_integration,lifecycle,orchestration,orchestrator_binding,production_wiring}.py \
    tests/test_character_{domain,preset_importer,read_api,validator}.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c1-s020506
  195 passed, 365 warnings in 164.36s
```

### Static gates

```
$ npx tsc --noEmit            -> exit 0
$ npx eslint <T04 files>      -> 0 errors / 0 warnings
$ npm run build               -> exit 0 (/object-gallery static)
$ python -m mypy app          -> Success: no issues found in 86 source files
$ git diff --check            -> exit 0 (pre-existing CRLF advisories only)
$ ruff check <changed .py>    -> 17 pre-existing E501 line-length errors in the historical
                                 committed migration migrations/versions/d5e6f7a8b9c0_character_library_schema.py
                                 (S06-T01). This round changed ZERO python files; flagged for
                                 transparency, NOT touched (would be a schema-chain change).
```

### Protected-state comparison (re-verified)

```
MAIN channels.json        SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555  UNCHANGED
MAIN data/motionforge.db  311296 bytes                                                                 UNCHANGED
SAM2.1 checkpoint         no files modified since 2026-08-17 00:00 (read-only)                         UNCHANGED
```

Status remains **SUBMITTED** (never APPROVED — Codex sprint-exit review owns approval).

## CORRECTION ROUND C2 (Codex CHANGES_REQUESTED — GALLERY GENERATION ISOLATION) — 2026-08-17

Same project session; fresh worker pass. Branch `codex/s08-integration`, HEAD still
`a43b20d`; dirty baseline 161 entries (intentional) — this round only modified
existing frontend/E2E/config/docs files; ZERO new repo files, ZERO Python files.

### Guards

```
$ pwd && git rev-parse --show-toplevel && git branch --show-current && git rev-parse HEAD
/c/Users/Admin/MotionForge2D-worktrees/s08-integration
C:/Users/Admin/MotionForge2D-worktrees/s08-integration
codex/s08-integration
a43b20da742996bafcb2f9d1ac57b10d3f1a5204
$ git status --short | wc -l  -> 161 (baseline; intended — never reset)
```

QA backend (fresh isolated root, NEW run): `output/s08-sprint/20260816-s08t04-c2-r1/
run-qa-backend.sh` → uvicorn :8026, cwd+roots = `.../c2-r1/backend-root`,
`MOTIONFORGE_EXTRACTION_PROVIDER=deterministic`,
`MOTIONFORGE_RECOMPUTE_PROVIDER=deterministic`,
`MOTIONFORGE_EXTRACTION_QA_MODE=1` (T02-C2 provider gate — the deterministic
provider refuses without QA mode, verified fail-closed: 503 "provider
'deterministic' is QA/test-only ... NOT in QA mode"). Frontend:
`NEXT_PUBLIC_API_URL=http://localhost:8026 npx next dev -p 3012`.

### Empirical probe (real backend) that shaped the design

```
GEN1 CHAIN 13a5d3a8… gen 1 ; EXTRACT GEN1 job.generation=1 ; GEN1 ROLES default = 4, current_generation=1
GEN2 CHAIN 7afd25ea… (NEW video item — legacy source replacement = video-item supersession, generation per item)
ROLES AFTER REPLACEMENT (default) = []   (different item)
ROLES EXPLICIT gen=1 (video A) = 4 names subject_01..04
C2 probe2: ANALYZE gen=2 → still a NEW video item; extraction job.generation derived "1" (backend authority: a fresh item without a completed job resolves to "1"; a gen hint that differs fails closed SOURCE_CONFLICT).
STALE DETAIL default 404 / explicit ?generation=1 200  (repo-level; API asserted in E2E below)
```

Conclusion recorded: a single legacy video item's generation advances to 2 only
when its durable source artifact changes (T02-C2 source authority — not reachable
through the legacy public flow, which models replacement as video-item
supersession). The gallery therefore consumes the backend-authoritative
CURRENT generation (T01-C2 `current_generation` + current-only default lists) and
the E2E builds the stale-generation state with REAL data via the public T01 API
`createRole(source_generation="2")` on a current-gen-1 video (accepted; validation
of currentness happens at LIST/DETAIL time, fail-closed).

### Frontend changes (finding C2 — all within TASK write scope)

- `frontend/src/lib/api.ts` — `ObjectRoleListResponse` + `SuggestionListResponse`
  now type `scope` + `current_generation` (backend-authoritative, T01-C2/T03-C2).
- `frontend/src/components/object-gallery/useGallery.ts` —
  - `useGalleryRolesPaged(videoItemId, generation)` : RQ key
    `["object-roles", videoItemId, generation, 0]`; page-2+ uses the same
    generation scope; exposes `currentGeneration` from the response.
  - `useRoleDetail(roleId, generation)` : key `["object-role-detail", roleId, generation]`.
  - `useGalleryGrouping(videoItemId, generation, …)` : keys
    `["grouping-suggestions"|"grouping-operations", videoItemId, generation]`;
    refreshAll/generate/dismiss/confirm invalidate the generation-scoped slice;
    exposes `currentGeneration` from the suggestions response.
  - `useGalleryExtraction` completion invalidations now target
    `["object-roles", videoItemId, generation]`.
  - `useGalleryCorrections(videoItemId, generation, refreshAll, …)` — its
    invalidations are generation-scoped too.
- `frontend/src/components/object-gallery/ObjectGalleryPanel.tsx` —
  - passes `generationForVideo ?? "1"` into every hook (RQ keys embed video +
    generation);
  - computes `authoritativeGeneration = roles.currentGeneration ??
    grouping.currentGeneration ?? generationForVideo ?? "1"` and uses it for the
    header ("Thế hệ nguồn hiện tại (máy chủ): N") AND every mutation payload
    (merge/split/reassign/edit carry the verified current generation);
  - cache-slice invalidation on (video, generation) switch
    (finding C2 #6): removes the previous `object-roles` /
    `grouping-suggestions` / `grouping-operations` / `object-role-detail`
    slices for the old video+generation;
  - stale roles/suggestions are never rendered (current-only default lists) and
    therefore expose ZERO action controls (merge/split/confirm/correct all live
    on a rendered role row — RoleCard actions already gated by `!superseded`).
- E2E helpers — `createRole(…, sourceGeneration="1")`; `getRoleWithStatus`
  (404 under current scope for stale); `listRolesMeta` (current default + scope +
  current_generation); `listRolesGeneration(video, gen)` (historical view);
  `generateSuggestions(video, sourceGeneration)`.
- E2E specs — desktop spec appended tests 14 (C2 generation isolation —
  stale-generation roles/suggestions never render or act) and 15 (C2 source
  replacement — generation-1 data never leaks; RQ slices are per
  video+generation). `playwright.s08t04.config.ts` + visual SHOTS point at the
  NEW C2 run root `output/s08-sprint/20260816-s08t04-c2-r1/` (never overwrote C1/
  original screenshots).

### E2E — exact command + verbatim result (full config, 2 projects, fresh root)

Run with the QA backend :8026:
```
$ cd frontend && QA_API_BASE=http://localhost:8026 npx playwright test --config playwright.s08t04.config.ts
  ok 1..2  visual desktop gallery / expanded detail with real media
  ok 3..15 01..13 (C1 interaction suite — all preserved: empty, real backend,
          decoded naturalWidth/Height, fresh-browser restore, backend-policy
          thresholds, pagination/lazy detail, video selector, confirm,
          suggestion merge, 409 stale, split, dismiss, correction media refresh)
  ok 16  14 C2 generation isolation — stale generation roles/suggestions never render or act (5.7s)
  ok 17  15 C2 source replacement — generation-1 data never leaks; RQ slices are per video+generation (11.6s)
  ok 18..20 mobile-390px m1/m2/m3 (no horizontal overflow; viewport; fresh-browser restore)
  20 passed (1.5m)   PW_EXIT=0
```
`--list` verified the project-level exclusions: `Total: 20 tests in 3 files`
(desktop 17 = 15 interaction + 2 visual; mobile 3) — no other task's specs ran.
Screenshots (NEW): `output/s08-sprint/20260816-s08t04-c2-r1/screenshots/
gallery-desktop.png` + `gallery-desktop-detail.png`.

### Regression suites (cache disabled, shallow basetemps; env unset before run)

```
$ python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py \
    tests/test_object_extraction.py tests/test_object_extraction_api.py \
    tests/test_object_correction.py tests/test_object_correction_api.py \
    tests/test_sam2_provider.py tests/test_sam2_smoke.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c2-bk2
  186 passed, 370 warnings in 113.40s

$ python -m pytest tests/test_s05_*.py tests/test_durable_job_api.py \
    tests/test_durable_job_persistence.py tests/test_durable_worker.py \
    tests/test_video_item_crud.py tests/test_channel_workspace.py \
    tests/test_channel_crud.py tests/test_persistence_bootstrap.py -p no:cacheprovider \
    --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t04-c2-bk3
  259 passed, 467 warnings in 200.34s   (S05 41-suite + S02 durable + migration round-trip,
                                         head == f6a7b8c9d0e1)
```

### Static gates

```
$ npx tsc --noEmit    -> exit 0
$ npx eslint <all 9 T04 frontend/e2e files> -> 0 errors / 0 warnings
$ npm run build       -> exit 0 (/object-gallery static)
$ python -m mypy app  -> Success: no issues found in 86 source files
$ git diff --check    -> exit 0 (pre-existing CRLF advisories only)
$ ruff check <changed .py> -> N/A for this round: ZERO python files changed.
                              (The dependency-round .py carry only the previously
                              reported pre-existing E501 in the historical
                              committed migration d5e6f7a8b9c0... — untouched.)
$ git status --short  -> 161 entries (baseline, intended); no strays
```

### Protected-data comparison (MAIN tree)

```
channels.json                 SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555  UNCHANGED
data/motionforge.db           size     311296 bytes                                                                 UNCHANGED
models_checkpoints/sam2.1_hiera_large.pt  size 898083611 bytes, mtime Jul 29 (untouched),
                             SHA-256 2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318      UNCHANGED
```

Status remains **SUBMITTED** (never APPROVED — Codex sprint-exit review owns approval).

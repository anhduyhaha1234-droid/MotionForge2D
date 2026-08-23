# S08-T06 — Execution Log

Status: SUBMITTED (correction round G appended)

Append-only. Record exact session, guards, changes, commands, results, incidents
and protected-state comparisons.

---

## BASELINE (2026-08-16)

Session: 20260816_203312_e9f2b8 (S08-T06 manager/worker session, fresh)
Model: ocg/deepseek-v4-pro

### Hard worktree guard (all verified BEFORE any write)

- pwd                    = /c/Users/Admin/MotionForge2D-worktrees/s08-integration
- git rev-parse --show-toplevel = C:/Users/Admin/MotionForge2D-worktrees/s08-integration
- git branch --show-current      = codex/s08-integration
- git rev-parse HEAD     = a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- git status --short     = 21 modified + 116 untracked (T01-T05 end state,
                           snapshot identical to the T05 report: no new files)

### Required reading (all read COMPLETELY before implementation)

1. MAIN SESSION_PROTOCOL.md (full)
2. docs/pm/sprints/S08-SPRINT_CONTRACT.md (full)
3. docs/pm/sessions/S08-T06-golden-object-intelligence/TASK.md (full)
4. docs/pm/sessions/S08-T06-golden-object-intelligence/START_PROMPT.md (full)
5. T01-T05 REPORT.md dependency evidence (all five manager-verified, full)

### Golden contract — thresholds recorded BEFORE running

File: tests/fixtures/s08_golden/golden_contract.json
- Written at: 2026-08-16 20:43:23 +0700 (before ANY golden run)
- SHA-256 (sha256sum + certutil, identical):
  3753c19a239a22a4a85e7339e1c34ccf51722a4af8cf24c3ff4668fc54832ba0
- Frozen thresholds (derived analytically from the deterministic
  role-fingerprint v1 algorithm, never from observed results):
  - grouping_precision >= 0.58 (predicted 0.60)
  - grouping_recall >= 0.95 (predicted 1.00)
  - proposal_false_merge_rate <= 0.22 (predicted 0.1818)
  - executed_false_split_rate <= 0.05 (predicted 0.00)
  - review_low_confidence_rate <= 0.35 (predicted 0.2857)
  - post_curation_false_merge_rate <= 0.0
  - post_curation_false_split_rate <= 0.0
  - recompute_scope_ratio <= 0.5 (predicted 1/7 = 0.1429)
  - runtime per scenario <= 300 s
  - repeatability: exact metric-vector equality across two independent runs
- Golden world: 1280x720 video, 5 scenes, 8 roles (H1/H2/H3/H5 = object A;
  H4 = object B similar-different; V1 = object C ambiguity; X1/X2 = twins
  D/E false grouping; H5 carries the occluded clipped occurrence at 0.32).
- Scenario cases: same-object-across-scenes, similar-different-objects,
  occlusion, low-confidence, false-grouping, required-merge, required-split,
  source-replacement, restart, retry, cancel.

### Implementation

- tests/fixtures/s08_golden/golden_contract.json (NEW — frozen contract)
- tests/test_s08_golden_object_intelligence.py (NEW — golden suite:
  scenario driver + threshold assertions + repeatability; the contract SHA
  is asserted at load time so any post-hoc contract edit fails the run)
- No product code changed. No changes to T01-T05 files. Write scope holds.

---

## GOLDEN RUNS (thresholds recorded BEFORE — contract SHA 3753c19a...)

Final-code run (after ruff formatting, run id 20260816-s08t06-r1):
```
S08T06_RUN_ID=20260816-s08t06-r1 python -m pytest tests/test_s08_golden_object_intelligence.py \
  -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-golden-final
-> 2 passed, 3 warnings in 5.49s
```
Metrics (output/s08-sprint/20260816-s08t06-r1/golden-metrics.json) — measured vs
fixed thresholds, ALL PASS:

| Metric | Fixed threshold | Measured |
|---|---|---|
| grouping_precision | >= 0.58 | 0.6 |
| grouping_recall | >= 0.95 | 1.0 |
| proposal_false_merge_rate | <= 0.22 | 0.181818 |
| review_low_confidence_rate | <= 0.35 | 0.285714 |
| post_curation_false_merge_rate | <= 0.0 | 0.0 |
| post_curation_false_split_rate | <= 0.0 | 0.0 |
| recompute_scope_ratio | <= 0.5 | 0.142857 (1/7) |
| runtime per scenario | <= 300 s | 1.438 s |
| repeatability | exact vector equality | EXACT (run1 == run2) |

Measured values are byte-identical to the analytically predicted values
recorded in the contract BEFORE running (suggestion_count 14, multiset
{0.9x7, 0.55x3, 0.35x4}, tp 6, fp 4, fn 0, tn 18).  No threshold was
tuned after observation.

## SPRINT-EXIT GATES

### Gate 1 — all S08 focused suites (T01-T05 + T06 golden)
```
python -m pytest tests/test_object_intelligence_domain.py tests/test_object_extraction.py \
  tests/test_object_extraction_api.py tests/test_object_extraction_production_wiring.py \
  tests/test_object_grouping.py tests/test_object_correction.py \
  tests/test_object_correction_api.py tests/test_s08_golden_object_intelligence.py \
  -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-gate1
-> 137 passed, 128 warnings in 111.21s
```

### Gate 2 — S01/S02/S03/S05/S06 regressions
```
python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py \
  tests/test_project_crud.py tests/test_video_item_crud.py tests/test_schema.py \
  tests/test_channel_crud.py tests/test_channel_workspace.py \
  -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-gate2a
-> 220 passed, 183 warnings in 117.75s

python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py \
  tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py \
  tests/test_s05_chain_progression.py tests/test_s05_orchestration.py \
  tests/test_s05_golden_integration.py tests/test_character_domain.py \
  tests/test_character_preset_importer.py tests/test_character_read_api.py \
  tests/test_character_validator.py tests/test_publish_rejection.py \
  -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-gate2b
-> 131 passed, 130 warnings in 155.55s   (S05 41 + S06 90)
```

### Gate 3 — migration upgrade/downgrade + existing-DB preservation (CLI)
Fresh temp DB C:/Users/Admin/AppData/Local/Temp/s08t06-migration.db,
MOTIONFORGE_DATABASE_URL inline (unset verified afterwards):
- upgrade d5e6f7a8b9c0 -> seed workspace+channel rows -> upgrade head:
  version f4a5b6c7d8e9; object tables present
  (object_correction, object_grouping_suggestion, object_occurrence,
  object_role, object_role_operation); ws rows (1,) channels (1,) PRESERVED.
- downgrade d5e6f7a8b9c0: object tables []; rows still preserved.
- upgrade head again: f4a5b6c7d8e9; rows preserved.

### Gate 4 — restart/retry/cancel/real-concurrency
Covered by the golden scenario (fresh-worker restart with exactly one effect
set; cancel-during-running drains zero effects via the real API; successor
retry after cancel) plus the T02/T05 focused suites (staging/commit-boundary
restarts, concurrent duplicate submit, concurrent CAS/confirm).

### Gate 5 — ruff / mypy / diff-check
```
python -m ruff check app tests   -> All checks passed! (exit 0)
python -m mypy app               -> Success: no issues found in 86 source files
git diff --check                 -> exit 0 (pre-existing CRLF advisories only)
```

### Gate 6 — frontend type/lint/build
```
cd frontend
npx tsc --noEmit                                    -> exit 0
npx eslint <api.ts, object-gallery/, ImportAnalyzePanel, preflightErrors,
  8 S08 e2e specs incl. the new T06 spec+config>     -> 0 problems (exit 0)
npm run build                                       -> Compiled successfully
  (/object-gallery static route); exit 0
```

### Gate 7 — real integrated Playwright desktop + 390px (fresh isolated root)
Fresh QA root output/s08-sprint/20260816-s08t06-r1/backend-root
(env inline: MOTIONFORGE_ROOT/OUTPUT/MODELS + EXTRACTION_PROVIDER=deterministic;
backend :8014 via uvicorn, frontend :3012 via `npx next dev -p 3012`,
NEXT_PUBLIC_API_URL=http://localhost:8014):
```
npx playwright test --config playwright.s08t06.config.ts
-> 31 passed (1.5m)  [desktop 25/25 incl. T06 evidence; mobile-390px 6/6]
```
NEW T06 screenshots (T06-owned spec, output/s08-sprint/20260816-s08t06-r1/screenshots/):
- desktop-gallery-low-confidence.png
- desktop-correction-scope-dialog.png
- mobile-390px-gallery.png

INCIDENT (recorded honestly): the first T06 config had the visual-spec
exclusion only at top level; Playwright project-level testIgnore REPLACES
the top-level value, so the two OLD visual specs
(s08-t04-object-gallery-visual.spec.ts, s08-t05-correction-visual.spec.ts)
re-ran inside the desktop project and REGENERATED their screenshots into
the T04/T05 run dirs (20260816-s08t04-r1/screenshots/ and
20260816-s08t05-r1/screenshots/, 6 PNGs, mtimes 21:00-21:01).  The original
byte-identical images were not recoverable (output/ is untracked, no backup).
Content is deterministic-equivalent: the same unchanged specs passed (ok 1,
2, 16, 17) against the same deterministic fixture data, so the regenerated
images depict the SAME UI states the T04/T05 reports reference.  Config
fixed (visual exclusion now in every project; verified with --list: 27
tests, 0 visual) so this can never repeat.  Recorded in REPORT + sprint
report as a deviation.

### Gate 8 — deterministic golden metrics (see GOLDEN RUNS above)

### Gate 10 — protected MAIN/source-tree comparison
- MAIN channels.json SHA-256 (certutil):
  dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
  == T01-T05 baseline. UNCHANGED (mtime 2026-08-03).
- MAIN data/motionforge.db: 311296 bytes == baseline. UNCHANGED
  (mtime 2026-08-16 17:25, before this session).
- MAIN git status: 51 entries = T05 baseline 50 + scripts/watch-s08-t06.sh
  (sprint-launcher watcher artifact, same pattern as watch-s08-t01..t05).
- S06 worktree (s06-t01-review): 45 entries == T01-recorded baseline.
- S05 worktree (prepare-s05-t01): 55 entries, HEAD a43b20d; no file modified
  after 20:00 today (verified via find -newermt) — untouched by this session.

### Gate 9 — fresh 7/7 quality baseline (NEW Run ID)
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
Run ID: 20260816-210501
Gate 1 Environment/Preflight PASS | Gate 2 Python tests PASS (962 passed,
19 skipped, 7 deselected in 466.85s) | Gate 3 ruff PASS | Gate 4 mypy PASS |
Gate 5 tsc PASS | Gate 6 npm run lint PASS | Gate 7 build PASS
OVERALL: PASS (exit code 0)
summary: output/quality-baseline/20260816-210501/summary.json
```

### Gate 7 re-run (corrected isolation) + incident remediation

Two incidents from the first Gate 7 attempt were found and remediated:

1. BACKEND CWD INCIDENT (self-inflicted, remediated): the first QA backend
   launch did NOT cd into the run root.  The durable JobService managed root
   is CWD-relative ("artifacts/" — `JobService._managed_root = Path(managed_root
   or "artifacts")`), so the first E2E run's uploads/staging/extraction
   artifacts landed in the WORKTREE root under artifacts/ (untracked stray
   dir, 313 files, mtime 21:00) instead of the isolated run root.  Remediation:
   stopped both servers, deleted the stray untracked worktree artifacts/ dir,
   wrote output/s08-sprint/20260816-s08t06-r1/run-qa-backend.sh (the T05
   launcher pattern: env inline + `cd "$RUN_ROOT"`), relaunched, re-ran the
   full suite.  Final verified placement:
   output/s08-sprint/20260816-s08t06-r1/backend-root/artifacts/ (uploads +
   staging) — worktree artifacts/ contains ONLY the pre-existing tracked
   file artifacts/milestone_1a/openapi.json.
   ACCIDENTAL TRACKED-FILE DELETION (remediated): the rm -rf of the stray
   dir also removed the TRACKED artifacts/milestone_1a/openapi.json (in HEAD,
   unmodified at baseline).  Restored with `git restore --worktree
   artifacts/milestone_1a/openapi.json`; `git status -- artifacts/` empty
   (byte-state identical to index; autocrlf normalization handled by git).
   Pre/post `git status --short` = 137 -> 141 (+ exactly the 4 new T06 files).

2. VISUAL-SPEC REGENERATION (see Gate 7 section above): T04/T05 screenshot
   dirs were regenerated by the old visual specs in run 1; config fixed;
   final run (below) excludes them (verified `--list`: 27 tests, 0 visual).

Final Gate 7 run (corrected, fresh root, visual specs excluded):
```
npx playwright test --config playwright.s08t06.config.ts
-> 27 passed (1.2m)  [desktop 21/21; mobile-390px 6/6]
```
QA servers stopped afterwards; ports 8014/3012 verified FREE (netstat).
New T06 screenshots (output/s08-sprint/20260816-s08t06-r1/screenshots/):
- desktop-gallery-low-confidence.png (1280x6865 PNG)
- desktop-correction-scope-dialog.png (1280x6889 PNG)
- mobile-390px-gallery.png (390x10675 PNG)

### Final state

- git status --short = 141 entries = baseline 137 + exactly the 4 new T06
  files (tests/fixtures/s08_golden/, tests/test_s08_golden_object_intelligence.py,
  frontend/e2e/s08-t06-golden-evidence.spec.ts,
  frontend/playwright.s08t06.config.ts).  No stray files.  No product code
  changed.  No commit/push/reset/checkout/clean/stash performed.
- Servers: none running (8014/3012 free).  Env: MOTIONFORGE_DATABASE_URL
  unset.  QA roots: output/s08-sprint/20260816-s08t06-r1/ (backend root +
  metrics + screenshots + launcher), quality baseline
  output/quality-baseline/20260816-210501/.

## STATUS

SUBMITTED (pending manager verification; Codex sprint-exit review owns
approval).




---

## CORRECTION ROUND — Finding G: TRUE VERTICAL GOLDEN (2026-08-17)

Codex CHANGES_REQUESTED on sprint exit (finding G).  Same session
`20260816_203312_e9f2b`.  Repo state at correction start: branch
codex/s08-integration @ a43b20d, `git status --short` = 160 entries
(T01-T05 correction rounds + H01/R01 applied; migration head
`f6a7b8c9d0e1`).

### Implementation (exact files changed in this round)

1. `app/services/object_extraction.py` — ADDED the QA-only
   `CrossSceneDeterministicExtractionProvider` (server policy
   `deterministic-identity`): a REAL deterministic cross-scene identity
   algorithm (Hero object A in scenes 1-3 with consistent footprint; a
   second same-name "Hero" object B in scene 3 at a disjoint footprint,
   co-occurrence suppressed by calibration v2; "Villain" object C in
   scene 4 (0.6 ambiguity); two same-name "Twin" roles (objects D/E, 0.9
   false suggestion)).  Candidate order (scene index, bbox x) fixes the
   durable role ids.  Existing providers untouched; production default
   `sam2-local` untouched; selectable ONLY via
   `MOTIONFORGE_EXTRACTION_PROVIDER` (never request JSON).
2. `tests/fixtures/s08_golden/golden_contract.json` — REFROZEN v2
   (written 2026-08-17 19:37:08 +0700 BEFORE any vertical run; SHA-256
   f008c027095c8534bd29d71a884cc5850878a10d0ef536c7b2738c0fb8edf323,
   recorded before the run and asserted at test load).
3. `tests/test_s08_golden_object_intelligence.py` — REWRITTEN as the TRUE
   VERTICAL: pristine subprocess generations over `app.main:app` + real
   lifespan + real public APIs (import -> analyze -> discover -> group ->
   correct -> render), NO deps injection, NO direct service orchestration,
   PRIMARY roles emerge from T02 output (never seeded via T01 API).
4. `frontend/e2e/s08-t06-golden-evidence.spec.ts` — REWRITTEN on the raw
   extractor world (no role seeding) + browser-restart-without-sessionStorage
   test; NEW screenshots dir (20260817-s08t06-g1).
5. `frontend/playwright.s08t06.config.ts` — outputDir -> new Run ID;
   project-level exclusions in EVERY project (desktop ignores
   /(mobile|visual)/; mobile project testMatch scoped to
   /s08-t0(4|5|6)-.*mobile\.spec\.ts/ + ignores visual).  Verified via
   `--list`: 30 tests in 5 files, 0 visual, 0 h01.
6. `output/s08-sprint/20260817-s08t06-g1/` — NEW Run ID evidence
   (gitignored): golden-metrics.json, run-qa-backend.sh (8027,
   deterministic-identity), run-qa-regression-backend.sh (8028,
   deterministic), backend-root/ (fresh DB + artifacts), screenshots/.

No changes to T01-T05 code, tests or specs; no changes to H01/R01 files.

### Golden runs (thresholds REFROZEN before — contract SHA f008c027...)

```
S08T06_RUN_ID=20260817-s08t06-g1 GOLDEN_TMP_ROOT=C:/Users/Admin/AppData/Local/Temp/s08t06g1 \
  python -m pytest tests/test_s08_golden_object_intelligence.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06g1-bt
-> 2 passed in 45.66s   (run1 full vertical incl. restart phase; run2 repeatability EXACT)
```
Measured vs frozen thresholds (metrics JSON
output/s08-sprint/20260817-s08t06-g1/golden-metrics.json):
- deterministic_contract_correctness = true (exact pre-recorded predictions:
  9 suggestions, multiset {0.9x4, 0.6x3, 0.45x2}, tp 3 fp 4 fn 0 tn 14)
- grouping_precision 0.428571 (>= 0.40) PASS; recall 1.0 (>= 0.95) PASS
- proposal_false_merge_rate 0.222222 (<= 0.25) PASS
- review_low_confidence_rate 0.222222 (<= 0.30) PASS
- post-curation false merge/split 0.0 (<= 0.0) PASS
- recompute_scope_ratio 0.166667 (<= 0.5) PASS
- runtime 22.54 s (<= 300) PASS; repeatability EXACT PASS
- calibration Brier 0.258333 at N=9 — INFORMATIONAL ONLY (no threshold;
  N far below a meaningful calibration sample)
- provider cross-scene identity: 7 candidates exactly as predicted
  (names/confidences/scene/bbox-x), stable role ids, 14 artifacts decodable
- media: real PNG decode dims == registered metadata (320x240 masks,
  38x38 thumbnails); media refreshed after geometry correction + content
  endpoint serves NEW bytes after completion AND after app restart;
  unaffected roles' media SHA-256 byte-identical
- restart phase: idempotent re-submit (reused=true), current lookup
  completed, curated roles + renamed role persist, gen-2 (source
  replacement) isolated (1 scene -> 2 roles), gen-1 current lookup still
  original, queued cancel -> terminal cancelled zero effects, cancelled
  predecessor NOT reusable (409) then gen-4 retry -> exactly one effect set,
  zero job-service 503s

### Regressions (fresh isolated roots, cache disabled, shallow basetemps)

```
1. S08 focused (T01-T05 + golden vertical):
   -> 164 passed in 180.61s
2. S01/S02/S03 + R01 (persistence, channels, root resolution, queued-cancel):
   -> 238 passed in 143.74s
3. S05 (41) + S06 (90):
   -> 131 passed in 173.95s
4. SAM2.1 GPU smoke + provider (SEPARATE gate, read-only checkpoint):
   python -m pytest tests/test_sam2_smoke.py tests/test_sam2_provider.py ...
   -> 2 passed in 15.66s   (real RTX 5070 inference; checkpoint 898083611 B
      verified unchanged by the test itself)
5. Migration CLI round trip (fresh temp DB, MOTIONFORGE_DATABASE_URL inline,
   unset verified): upgrade d5e6f7a8b9c0 -> seed rows -> upgrade head
   -> f6a7b8c9d0e1, 6 object tables (incl. object_role_artifact), rows
   preserved; downgrade f3a4b5c6d7e8 -> object_correction +
   object_role_artifact dropped, rows preserved; upgrade head again -> OK.
6. ruff (app+tests) All checks passed!; mypy 86 files 0 issues;
   git diff --check exit 0 (pre-existing CRLF advisories only).
7. Frontend: tsc exit 0; eslint (S08 files incl. new spec/config) exit 0;
   npm run build exit 0.
```

### Playwright (fresh roots, NEW Run ID 20260817-s08t06-g1)

- T06 evidence spec on the vertical world (backend 8027,
  deterministic-identity; frontend NEXT_PUBLIC_API_URL=:8027):
  -> 4 passed (14.1s): desktop gallery driven by RAW extraction output +
  grouping (9 pending suggestions with calibration-v2 confidences, 7 role
  cards incl. duplicate display names); correction scope dialog before
  confirmation + Escape zero mutations; browser restart without
  sessionStorage restores from backend (appKeys == []); 390px no overflow.
  NEW screenshots (output/s08-sprint/20260817-s08t06-g1/screenshots/):
  desktop-gallery-extractor-driven.png, desktop-correction-scope-dialog.png,
  mobile-390px-gallery.png.
- S08-T04 + T05 interaction regression on the classic provider (backend
  8028, deterministic; QA_API_BASE=:8028 + NEXT_PUBLIC_API_URL=:8028):
  T04 suite 16/16 passed (desktop 13 incl. empty-state/extraction/restart-
  without-storage/policy + mobile 3).  T05: t01/t02/t03(tail)/t04/m1/m2
  FAIL on STALE copy/selector assertions (see finding below); the flows
  themselves are proven by the T06 evidence spec + T04 merge/split paths.
- Project-level exclusions verified via `--list` in EVERY project of the
  T06 config (desktop: /(mobile|visual)/; mobile: scoped testMatch +
  /visual/): 30 tests in 5 files, 0 visual, 0 h01.
- QA servers stopped afterwards; ports 8027/8028/3012 verified free.

### Finding (out of scope for T06, recorded for Codex -> T05)

S08-T05's correction E2E suite is stale against the CURRENT gallery copy
(changed during T04-C1/T05-C1/H01 rounds, NOT by this session — T06
modified no gallery/component/spec of T04/T05):
- t01 `getByText('1 khung hình')` on the collapsed card -> current copy
  renders the summary as "1 khung · 1 cảnh" (RoleCard splits
  `{n} khung hình` + `{m} cảnh`; the a11y tree merges them);
- t02/m1/m2 expect the correction buttons directly on the collapsed card,
  but they now live inside the expanded role detail (must click
  "Xem chi tiết vai trò …" first);
- t03 tail expects "Vai trò đã thay thế (1)" -> current copy renders
  "Đã thay thế" badge + "Vai trò đã thay thế — ảnh mẫu thuộc vai trò đích."
  (no "(1)" count);
- t04 expects the split control text "Tách vai trò đã gộp" inside
  "Vai trò Pair X" -> the current card shows the split action in the
  expanded detail with the new copy.
Recommendation: T05 session updates its spec selectors to the current
copy (and expands before acting); behavior is already verified by the
T06 evidence spec (reassign scope + escape) and the T04 suites.

### Protected state (same values as the T01-T05 baseline)

- MAIN channels.json SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
- MAIN data/motionforge.db 311296 bytes
- SAM2.1 checkpoint C:/Users/Admin/MotionForge2D/models_checkpoints/sam2.1_hiera_large.pt
  898083611 bytes (read-only; verified unchanged after the smoke)
- MAIN git status 63 entries (T01-T05 correction + H01/R01 packet artifacts,
  none created by this session); S06 45; S05 55 with nothing modified after
  19:00 today

### Final state

`git status --short` = 160 entries (identical to correction-start snapshot
160 — no new stray entries; all T06 changes are modifications of already-
untracked files + gitignored output/).  No commit/push/reset/checkout/
clean/stash.  Status remains SUBMITTED (never self-approved; PM_REVIEW.md
untouched).

### Fresh 7/7 quality baseline (correction round)

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
Run ID: 20260817-203610 — OVERALL PASS (exit 0)
  Gate 1 preflight PASS | Gate 2 Python tests PASS (1007 passed, 19 skipped,
  9 deselected in 560.45s) | Gate 3 ruff PASS | Gate 4 mypy PASS |
  Gate 5 tsc PASS | Gate 6 npm run lint PASS | Gate 7 build PASS
  summary: output/quality-baseline/20260817-203610/summary.json

---

## CORRECTION ROUND C2 — FRESH VERTICAL REGRESSION + SPRINT EVIDENCE (Codex CHANGES_REQUESTED on sprint exit 2)

Session `20260816_203312_e9f2b` (same T06 chain).  C2 corrections were
ALREADY in tree before this round (T02-C2 backend source authority +
provider QA gate `MOTIONFORGE_EXTRACTION_QA_MODE=1`; T01-C2 current-gen role
listing; T03-C2 current-gen suggestions; T04-C2 gallery generation isolation;
T05-C2 E2E repair; H02 local-API origin/upload/media safety).  Repo state:
branch `codex/s08-integration` @ a43b20d, `git status --short` = 167
(intentional dirty baseline; never reset).

### Runs (fresh isolated roots, cache disabled, shallow basetemps, NEW Run ID)

Run ID: `20260818-s08t06-c2` (evidence under
`output/s08-sprint/20260818-s08t06-c2/`).

```
1. Golden vertical suite (brand-new root/DB, real app.main:app + lifespan,
   real public APIs, NO DI, contract SHA frozen PRE-run):
   S08T06_RUN_ID=20260818-s08t06-c2 GOLDEN_TMP_ROOT=.../Temp/s08t06-c2-g8 \
     python -m pytest tests/test_s08_golden_object_intelligence.py -q -p no:cacheprovider \
     --basetemp=.../Temp/s08t06-c2-g8-bt
   -> 2 passed in 40.59s   (run1 full vertical incl. restart/isolation phase;
      run2 repeatability EXACT)
   Contract SHA f008c027095c8534... UNCHANGED — the deterministic-identity
   world and all frozen thresholds still hold; the runner was repaired to the
   C2 backend-source-authority semantics (client generation hint -> 409;
   omit the hint; idempotent re-submit collapses to the completed generation).
   Metrics JSON: output/s08-sprint/20260818-s08t06-c2/golden-metrics.json
   - deterministic_contract_correctness = true (9 suggestions, multiset
     {0.9x4,0.6x3,0.45x2}, tp3/fp4/fn0/tn14 exact)
   - grouping_precision 0.428571 (>=0.40) PASS; recall 1.0 (>=0.95) PASS
   - proposal_false_merge_rate 0.222222 (<=0.25) PASS
   - review_low_confidence_rate 0.222222 (<=0.30) PASS
   - post-curation false merge/split 0.0; recompute_scope_ratio 0.166667
     (<=0.5); runtime 19.49 s (<=300); repeatability EXACT
   - calibration Brier 0.258333 @ N=9 — informational only (not gated)
   - restart/isolation: idempotent_reuse=true, current_lookup=completed,
     client_generation_hint_rejected=true (409), gen2_assigned_generation="1",
     gen2_roles_exclude_old_world=true, gen2_suggestions_scope=true,
     gen1_roles_untouched=true, zero job-service 503s
   NOTE: queued-cancel + retry/successor are exercised deterministically by
   the R01 + T02-C2 focused suites (engine + public-API seams); the vertical's
   in-process worker races a 1s poll against a ~20ms extraction, so those two
   paths are NOT re-proven in the vertical (documented in the metrics JSON).

2. Focused S08 T01-T06 + H02 + R01:
   -> 242 passed in 163.36s
3. Regression S01/S02/S03 + S05 (41) + S06 (90) + persistence:
   -> 351 passed in 257.94s
4. SAM2.1 GPU smoke + provider (SEPARATE integration gate, read-only
   checkpoint, isolated output): 2 passed in 12.40s
5. T02-C2 production provider gate (default provider w/o model locator ->
   503 + ZERO job rows; unknown provider -> 503): inside the focused suite,
   tests pass (test_api_production_provider_fails_closed_no_job_row,
   test_api_unknown_provider_fails_closed).
6. H02 security (origin/upload/media): inside the focused suite,
   test_s08_h02_security.py passes (untrusted Origin state-changing 403 with
   zero side effects; trusted origins get ACAO; upload 413 + no staging;
   traversal ids rejected; content-probe media type; staging cleanup; dim
   cap).
7. Migration CLI round trip (fresh temp DB, MOTIONFORGE_DATABASE_URL inline,
   unset verified):
   upgrade d5e6f7a8b9c0 -> seed rows -> upgrade head -> f6a7b8c9d0e1
   (6 object tables incl. object_role_artifact + object_correction, rows
   preserved) -> downgrade f3a4b5c6d7e8 (correction + artifact tables
   dropped, rows preserved) -> upgrade head (OK, rows preserved) -> ENV_CLEAN
8. ruff check app tests -> All checks passed!; mypy app -> 88 files, 0 issues;
   git diff --check -> exit 0
9. Frontend: tsc exit 0; eslint (S08 E2E files) exit 0; npm run build exit 0
```

### Playwright (fresh roots, NEW Run ID 20260818-s08t06-c2, NEW screenshots)

The QA backends were launched via the C2 launchers (isolated roots inline;
`MOTIONFORGE_QA_MODE=1` + `MOTIONFORGE_EXTRACTION_QA_MODE=1`;
`MOTIONFORGE_CORS_ORIGINS` including `http://localhost:3012` — H02's
no-wildcard CORS otherwise blocks the browser cross-origin fetch).  Verified
`--list` project-level exclusions in EVERY project of the T06 config BEFORE
the run: 32 tests in 5 files, 0 visual, 0 h01.

```
- T06 evidence spec (backend 8027, deterministic-identity; frontend
  NEXT_PUBLIC_API_URL=:8027):
  -> 4 passed (13.8s) — desktop gallery driven by RAW extraction output +
  grouping; correction scope dialog + Escape zero mutations; browser restart
  WITHOUT sessionStorage restores from backend; 390px no overflow.
  NEW screenshots (output/s08-sprint/20260818-s08t06-c2/screenshots/):
  desktop-gallery-extractor-driven.png, desktop-correction-scope-dialog.png,
  mobile-390px-gallery.png
- FULL T04 + T05 regression (backend 8028, deterministic; frontend
  NEXT_PUBLIC_API_URL=:8028):
  -> 27 passed (1.8m) — T04 desktop 13 + mobile 3; T05 desktop 5 (t01..t05
  incl. reassign scope, candidate edit, suggestion merge + recompute strip,
  split, escape-zero-mutations) + mobile 4 (m1..m4 incl. regenerated media
  after a correction at 390px).  T05-C2's E2E repair confirmed green.
- QA servers stopped; ports 3012/8027/8028 verified free.
```

### C2-relevant findings recorded (out of scope for T06)

1. The golden vertical ran against the C2 backend-source-authority gate.
   Client generation hints that do not match the authoritative value are
   rejected 409 (not 422); the runner now asserts that and omits the hint.
2. queued-cancel / retry-in-the-vertical is inherently racy (worker 1s poll
   vs ~20ms deterministic extraction) — moved entirely to the R01 + T02-C2
   suites as the authoritative coverage.  No product defect.

### Protected state

- MAIN channels.json SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
- MAIN data/motionforge.db 311296 bytes
- SAM2.1 checkpoint sam2.1_hiera_large.pt 898083611 bytes,
  SHA-256 2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318
  (read-only, never touched)
- MAIN git status 71 entries (pre-existing packet artifacts from other
  sessions — none created by this session); S06 45; S05 55 (nothing modified
  by this session)

### Final state

git status --short = 167 (identical to the C2-start snapshot — no new strays;
T06 changes are modifications of already-untracked files + gitignored
output/).  Status remains SUBMITTED (never self-approved; PM_REVIEW.md and
TASK.md untouched).


### Fresh 7/7 quality baseline (C2 round)

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
Run ID: 20260819-004409 — OVERALL PASS (exit 0)
  Gate 2 Python tests: 1067 passed, 19 skipped, 9 deselected in 572.14s
  Gates 1,3,4,5,6,7 all PASS (preflight, ruff, mypy, tsc, lint, build)
  summary: output/quality-baseline/20260819-004409/summary.json

### Final-state re-verification (post-baseline, fresh)

python -m pytest tests/test_s08_golden_object_intelligence.py \
  tests/test_s08_h02_security.py tests/test_object_extraction_api.py \
  tests/test_s08_r01_queued_cancel_lifecycle.py -q -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-c2-final-bt
-> 64 passed in 70.03s
eslint (T06 spec + config) + tsc -> exit 0; ruff app tests -> All checks
passed!; mypy app -> 88 files 0 issues.  git status --short = 169 entries
(all legitimate repo files; no strays/temp dirs created by this session;
dirty baseline intentional — never reset/cleaned/stashed).

C2 round complete.  Status: SUBMITTED (never self-approved; PM_REVIEW.md and
TASK.md untouched).

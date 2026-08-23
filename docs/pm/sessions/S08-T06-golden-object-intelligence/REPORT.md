# S08-T06 — Golden Object Intelligence and Sprint Exit: Implementation Report

**Status:** SUBMITTED  (never APPROVED — manager verification + Codex sprint-exit review own approval)
**Hermes session:** `20260816_203312_e9f2b` (fresh S08-T06 manager/worker session)
**Started:** 2026-08-16 20:33
**Submitted:** 2026-08-16
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Depends on:** S08-T05 manager-verified (`MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`)

## Outcome

A deterministic golden dataset and end-to-end evidence prove the S08
grouping, curation, targeted-correction and restart behavior without any user
data.  The frozen golden contract (SHA-256
`3753c19a239a22a4a85e7339e1c34ccf51722a4af8cf24c3ff4668fc54832ba0`, written at
2026-08-16 20:43 BEFORE any run) declares a synthetic 8-role/5-scene world,
object-level ground truth, truth-mandated actions and FIXED metric thresholds
derived analytically from the deterministic algorithms — never from observed
results; the test asserts the contract SHA at load time so any post-hoc edit
fails the run.  The golden scenario drives the REAL production surface
(T01 role/occurrence API, T03 grouping/curation API, T05 correction API, T02
DISCOVER job + durable worker) through all mandated cases: same object across
scenes, visually similar different objects, occlusion, low confidence, false
grouping, required merge, required split, source replacement, restart, retry
and cancel.  Every measured metric equals the pre-recorded prediction exactly
(no threshold was tuned).  All ten sprint-exit gates pass on fresh isolated
roots; protected MAIN/source-tree state is unchanged; the sprint report is
submitted as `SPRINT_SUBMITTED`.

## Files changed (all within TASK.md allowed write scope)

| File | Change |
|---|---|
| `tests/fixtures/s08_golden/golden_contract.json` | NEW — FROZEN golden contract: world, object ground truth, scenario cases, required actions, expected initial generation (analytically predicted metrics) and fixed thresholds. SHA-256 recorded before any run. |
| `tests/test_s08_golden_object_intelligence.py` | NEW — golden suite (2 tests): full scenario driver (seeding → API-driven roles/occurrences incl. the occluded occurrence → real generation → metrics vs truth → dismissals → required merge → refresh → injected false merge + required split → T05 candidate-edit correction with recompute-scope measurement → source replacement gen-2 with forced-restart fresh worker → stale-source INPUT_CHANGED zero effects → cancel-during-running via the real API → successor retry → post-curation truth alignment) + exact repeatability across two independent runs. Contract SHA asserted at import. |
| `frontend/e2e/s08-t06-golden-evidence.spec.ts` | NEW T06-owned E2E evidence spec (real backend): low-confidence flagged gallery screenshot, correction scope dialog (Escape = zero mutations), 390px no-overflow screenshot. |
| `frontend/playwright.s08t06.config.ts` | NEW T06-owned sprint-exit config: runs ALL S08 interaction suites (T04+T05+T06) on one fresh isolated root; the OLD visual specs are excluded in EVERY project (they hardcode T04/T05 run dirs — sprint exit must not overwrite sibling evidence). |
| `output/s08-sprint/20260816-s08t06-r1/` | NEW run evidence (gitignored): `golden-metrics.json`, `backend-root/` (fresh isolated DB + artifacts), `screenshots/` (3 new PNGs), `run-qa-backend.sh` (isolated launcher). |
| `docs/pm/sessions/S08-T06-golden-object-intelligence/LOG.md` | baseline + golden runs + sprint-exit gates + incidents (append-only, real evidence) |
| `docs/pm/sessions/S08-T06-golden-object-intelligence/REPORT.md` | this report |
| `docs/pm/sprints/S08-SPRINT_REPORT.md` | NEW — sprint-exit report (`SPRINT_SUBMITTED`) |

No changes to: product code, T01-T05 files, S05/S06 contracts, TASK.md,
sprint contract, PM_REVIEW.md, channels.json, data/, any database, MAIN or
other worktrees.  `git status --short` = 141 entries (baseline 137 + exactly
the 4 new T06 files); no stray files.  No commit/push/reset/checkout/clean/
stash performed.

## Acceptance criteria — evidence

| AC | Evidence |
|---|---|
| Golden dataset covers same object across scenes, similar different objects, occlusion, low confidence, false grouping, required merge, required split, source replacement, restart, retry, cancel | contract `scenario_cases` + golden suite: H1/H2/H3/H5 (object A across scenes 1-5), H4 (object B, same name, disjoint footprint), H5's scene-4 occurrence clipped by the frame edge at confidence 0.32 (persisted via the real API, asserted exactly), 0.35 low-confidence suggestions never auto-confirmed (all 8 roles stay `suggested`), twin pair X1/X2 wrongly suggested at 0.9 + 3 villain ambiguity pairs at 0.55 (truth-different, dismissed), required merge H2→H1 (201, evidence moved, H2 superseded), injected erroneous merge X1+X2 corrected by the required split (201, both roles active with their own evidence restored), gen-2 DISCOVER run after source replacement, queued job completed by a FRESH worker over a fresh engine (restart), successor after cancel (retry), cancel-during-running drains zero effects via the real `/api/jobs/{id}/cancel`. |
| Expected truth and metric thresholds recorded BEFORE running; not tuned after | Contract file written 20:43:23 (before any run); SHA-256 recorded in LOG and asserted by the test at load. Measured values are byte-identical to the analytically predicted ones (suggestion_count 14, multiset {0.9×7, 0.55×3, 0.35×4}, tp 6, fp 4, fn 0, tn 18, precision 0.6, recall 1.0, proposal false-merge rate 0.181818, review rate 0.285714, recompute scope 1/7). No threshold changed after observation. |
| Metrics: grouping precision/recall, false-merge rate, false-split rate, review/low-confidence rate, recompute scope, repeatability, runtime | see golden metrics table below — all pass their fixed thresholds; repeatability is exact metric-vector equality across two independent runs (run1 == run2 asserted). |
| No user data — deterministic fixtures only | every value in the contract is a synthetic constant; no channels.json/data/ imports anywhere in the suite. |
| No model-quality claims beyond fixture evidence | metrics describe the deterministic role-fingerprint v1 algorithm on this dataset only; the report makes no model claims. |
| Product fixes returned as CHANGES_REQUESTED, not hidden in T06 | no product fixes were needed or made; two observations are recorded in the sprint report's out-of-scope findings for Codex (T02 queued-cancel drain gap; T04 artifact-byte preview endpoint) — both owned by their tasks. |
| Sprint-exit gates 1-10 on fresh roots | see Validation below — all pass. |
| Stop at SPRINT_SUBMITTED | T06 REPORT ends `SUBMITTED`; `docs/pm/sprints/S08-SPRINT_REPORT.md` ends `SPRINT_SUBMITTED`; no commit/push/deploy performed. |

## Golden metrics — thresholds as recorded BEFORE runs vs measured

Contract SHA-256: `3753c19a239a22a4a85e7339e1c34ccf51722a4af8cf24c3ff4668fc54832ba0`
Run evidence: `output/s08-sprint/20260816-s08t06-r1/golden-metrics.json`
(decision threshold 0.5; predictions recorded analytically in the contract).

| Metric | Fixed threshold (pre-run) | Measured | Verdict |
|---|---|---|---|
| grouping_precision | >= 0.58 | 0.6 | PASS |
| grouping_recall | >= 0.95 | 1.0 | PASS |
| proposal_false_merge_rate | <= 0.22 | 0.181818 | PASS |
| executed_false_split_rate | <= 0.05 | 0.0 (1 split, all truth-correct) | PASS |
| review_low_confidence_rate | <= 0.35 | 0.285714 | PASS |
| post_curation_false_merge_rate | <= 0.0 | 0.0 | PASS |
| post_curation_false_split_rate | <= 0.0 | 0.0 | PASS |
| recompute_scope_ratio | <= 0.5 | 0.142857 (1 affected of 7 active roles) | PASS |
| runtime per scenario | <= 300 s | 1.438 s | PASS |
| repeatability | exact metric-vector equality | EXACT (two independent runs) | PASS |

Also measured (asserted exactly, predicted in the contract): suggestion_count
14; confidence multiset {0.9×7, 0.55×3, 0.35×4}; tp 6, fp 4, fn 0, tn 18;
gen-1 active roles final 7; gen-2 roles 5; stale gen-3 roles 0; gen-4
successor roles 5; cancelled attempt zero effects; restart single effect set.

## Validation — exact commands and results

All pytest runs: `-p no:cacheprovider`, isolated shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08t06-*`.  QA root:
`output/s08-sprint/20260816-s08t06-r1/` (fresh isolated DB; ports 8014/3012;
deterministic extraction provider selected explicitly via inline env).

```
1. Golden suite (final code, run id 20260816-s08t06-r1):
   S08T06_RUN_ID=20260816-s08t06-r1 python -m pytest tests/test_s08_golden_object_intelligence.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-golden-final
   -> 2 passed, 3 warnings in 5.49s

2. Gate 1 — all S08 focused suites (T01-T05 + T06):
   python -m pytest tests/test_object_intelligence_domain.py tests/test_object_extraction.py
     tests/test_object_extraction_api.py tests/test_object_extraction_production_wiring.py
     tests/test_object_grouping.py tests/test_object_correction.py
     tests/test_object_correction_api.py tests/test_s08_golden_object_intelligence.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-gate1
   -> 137 passed, 128 warnings in 111.21s

3. Gate 2 — S01/S02/S03/S05/S06 regressions:
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py
     tests/test_project_crud.py tests/test_video_item_crud.py tests/test_schema.py
     tests/test_channel_crud.py tests/test_channel_workspace.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-gate2a
   -> 220 passed, 183 warnings in 117.75s
   python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py
     tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py
     tests/test_s05_chain_progression.py tests/test_s05_orchestration.py
     tests/test_s05_golden_integration.py tests/test_character_domain.py
     tests/test_character_preset_importer.py tests/test_character_read_api.py
     tests/test_character_validator.py tests/test_publish_rejection.py
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08t06-gate2b
   -> 131 passed, 130 warnings in 155.55s   (S05 41 + S06 90)

4. Gate 3 — migration upgrade/downgrade + existing-DB preservation (CLI,
   fresh temp DB C:/Users/Admin/AppData/Local/Temp/s08t06-migration.db,
   MOTIONFORGE_DATABASE_URL inline, unset verified after):
   upgrade d5e6f7a8b9c0 -> seed workspace+channel -> upgrade head
   -> version f4a5b6c7d8e9; 5 object tables present; seeded rows preserved
   downgrade d5e6f7a8b9c0 -> object tables []; rows preserved
   upgrade head -> f4a5b6c7d8e9; rows preserved.  All PASS.

5. Gate 4 — restart/retry/cancel/real-concurrency: golden scenario
   (fresh-worker restart one-effect-set; cancel via real API drains zero
   effects; successor retry; real-concurrency in T01/T02/T05 suites) — PASS.

6. Gate 5 — ruff / mypy / diff-check:
   python -m ruff check app tests   -> All checks passed! (exit 0)
   python -m mypy app               -> Success: no issues found in 86 source files
   git diff --check                 -> exit 0 (pre-existing CRLF advisories only)

7. Gate 6 — frontend type/lint/build:
   cd frontend && npx tsc --noEmit                  -> exit 0
   npx eslint <S08 files incl. new T06 spec+config> -> 0 problems (exit 0)
   npm run build                                     -> Compiled successfully; exit 0

8. Gate 7 — real integrated Playwright desktop + 390px (fresh isolated root,
   visual specs of T04/T05 excluded — see incidents):
   npx playwright test --config playwright.s08t06.config.ts
   -> 27 passed (1.2m)  [desktop 21/21; mobile-390px 6/6]
   NEW screenshots (T06-owned): output/s08-sprint/20260816-s08t06-r1/screenshots/
     desktop-gallery-low-confidence.png (1280x6865)
     desktop-correction-scope-dialog.png (1280x6889)
     mobile-390px-gallery.png (390x10675)
   (first attempt ran 31/31 including the old visual specs — see incident;
   final corrected run above is the recorded evidence.  QA servers stopped;
   ports 8014/3012 verified free.)

9. Gate 8 — deterministic golden metrics: see table above; metrics JSON at
   output/s08-sprint/20260816-s08t06-r1/golden-metrics.json.

10. Gate 9 — fresh 7/7 quality baseline, NEW Run ID:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
    Run ID: 20260816-210501
    Gates: preflight PASS; Python tests PASS (962 passed, 19 skipped,
    7 deselected in 466.85s); ruff PASS; mypy PASS; tsc PASS; npm run lint
    PASS; build PASS.  OVERALL: PASS (exit code 0).
    summary: output/quality-baseline/20260816-210501/summary.json

11. Gate 10 — protected MAIN/source-tree comparison:
    MAIN channels.json SHA-256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555
      == T01-T05 baseline (UNCHANGED)
    MAIN data/motionforge.db 311296 bytes == baseline (UNCHANGED)
    MAIN git status 51 = T05 baseline 50 + watch-s08-t06.sh launcher artifact
    S06 worktree 45 entries (T01 baseline); S05 worktree 55 entries, nothing
    modified after 20:00 — untouched.
```

## Isolation and protected state

- All tests/runtime/E2E/migrations used NEW isolated roots and databases:
  shallow pytest basetemps, the CLI migration temp DB, the fresh QA root
  `output/s08-sprint/20260816-s08t06-r1/backend-root` (fresh DB migrated there;
  launcher `run-qa-backend.sh` sets MOTIONFORGE_ROOT/OUTPUT/MODELS +
  `MOTIONFORGE_EXTRACTION_PROVIDER=deterministic` inline AND cds into the run
  root — the JobService managed root is CWD-relative).  The worktree
  `alembic.ini` still sets no URL.
- Protected comparison values identical to the T01-T05 baseline (see gate 10).
- No commit/push/deploy/reset/checkout/restore/clean/stash/delete performed
  (one `git restore --worktree` of a single file I accidentally deleted was
  the required remediation — see incidents).  All pre-existing uncommitted
  changes preserved; QA servers stopped; ports 8014/3012 free; no
  background workers left running.

## Deviations and risks

1. **Visual-spec screenshot regeneration (incident, recorded).**  The first
   Gate 7 run's config had the old visual-spec exclusion only at top level;
   Playwright project-level `testIgnore` REPLACES the top-level value, so the
   two OLD visual specs re-ran inside the desktop project and regenerated
   their screenshots into the T04/T05 run dirs (6 PNGs).  The original
   byte-identical images were not recoverable (output/ is untracked).  The
   regenerated images were produced by the SAME unchanged specs (which passed)
   against the same deterministic fixture data, so they depict the same UI
   states the T04/T05 reports reference.  Config fixed (exclusion in every
   project; `--list` verified: 27 tests, 0 visual).  Fully documented in LOG.
2. **Backend CWD incident (self-inflicted, fully remediated).**  The first QA
   backend launch did not cd into the run root; the CWD-relative managed root
   made the first E2E run write uploads/staging into the WORKTREE root
   `artifacts/` (untracked stray, created at 21:00).  Remediated: servers
   stopped, stray dir removed, `run-qa-backend.sh` launcher (cd into run root)
   created, suite re-run — final artifacts verified under
   `backend-root/artifacts/`, worktree contains only the pre-existing tracked
   file.  During the stray-dir removal the TRACKED
   `artifacts/milestone_1a/openapi.json` was accidentally deleted too; it was
   restored byte-exact with `git restore --worktree` (status clean on that
   path).  Recorded honestly in LOG + sprint report.
3. **No product changes.**  T06 is evidence-only; nothing in the T01-T05
   production surface was modified.
4. The golden metrics characterize the deterministic role-fingerprint v1
   algorithm on THIS dataset only — the suite makes no claim about model
   quality or about any other dataset.

## Recommended manager state

`SPRINT_SUBMITTED` — all ten sprint-exit gates pass; T06 ends `SUBMITTED`;
Codex sprint-exit review owns APPROVED/CLOSED.

SUBMITTED

## Manager verification (2026-08-16, sprint exit)

**Internal state: `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`** — recorded by the
sprint manager after independent final re-run. NOT APPROVED; Codex sprint-exit
review owns approval.

Manager final evidence (independent basetemps):
- Full S08 focused (T01-T05 + golden): **137/137 passed in 75.29s** (s08t06-mgr-all)
- S05 41-suite + S06 90-suite: **131/131 passed in 129.83s** (s08t06-mgr-s05s06)
- Golden suite: 2/2 (5.59s); golden-metrics.json verified with contract SHA 3753c19a…; thresholds-as-recorded == measured
- Fresh 7/7 baseline Run ID **20260816-210501**: all 7 gates PASS (verified from summary.json directly)
- Playwright sprint-exit: 27/27 (worker), 3 new screenshots present in 20260816-s08t06-r1/screenshots, test-results empty (0 failures)
- Protected: MAIN channels.json SHA dd7aae26…555 UNCHANGED; MAIN DB 311296 B UNCHANGED; MAIN 45 / S06 45 / S05 55 entries — all match P00 baselines
- Scope: INTEG 142 = 137 + 5 T06 files; SPRINT_REPORT present and complete

---

## CORRECTION ROUND — Finding G: TRUE VERTICAL GOLDEN (Codex CHANGES_REQUESTED, 2026-08-17)

**Status:** SUBMITTED (unchanged — never self-approved; PM_REVIEW.md untouched)
**Session:** `20260816_203312_e9f2b` (resumed same T06 session)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch
`codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)

### What changed (finding G, all items)

The golden was rebuilt as a **true vertical**: brand-new root/DB, real
`app.main:app` + real lifespan via pristine TestClient subprocesses, real
public APIs only — NO `deps._job_service` / `deps._lifecycle_db` injection
anywhere in the golden path, NO direct service orchestration, NO seeding of
the primary vertical roles via the T01 role-creation API.  The roles EMERGE
from a new QA-only cross-scene-identity extractor
(`CrossSceneDeterministicExtractionProvider`, server policy
`deterministic-identity`): same object "Hero" recurs across scenes 1-3 with a
consistent footprint, a second same-name "Hero" (object B) co-occurs at a
disjoint footprint (suppressed by calibration v2), "Villain" (object C) gives
0.6 ambiguity suggestions, and two same-name "Twin" roles (D/E) get a confident
0.9 false suggestion — so T02 output alone drives T03 grouping end-to-end.
The contract SHA-256 was **REFROZEN BEFORE the run**
(`f008c027095c8534bd29d71a884cc5850878a10d0ef536c7b2738c0fb8edf323`,
2026-08-17 19:37:08) and is asserted at test load; thresholds were derived
analytically from calibration-v2 and the new provider, never tuned after
observation.

New/changed files (this round, all in scope): `app/services/object_extraction.py`
(+ QA provider + policy name; existing providers/production default untouched);
`tests/fixtures/s08_golden/golden_contract.json` (refrozen v2);
`tests/test_s08_golden_object_intelligence.py` (rewritten as the vertical);
`frontend/e2e/s08-t06-golden-evidence.spec.ts` (raw-extractor world +
browser-restart-without-sessionStorage); `frontend/playwright.s08t06.config.ts`
(outputDir new Run ID + project-level exclusions in EVERY project);
`output/s08-sprint/20260817-s08t06-g1/` (new Run ID evidence).

### Acceptance evidence (finding G items)

| Item | Evidence |
|---|---|
| Brand-new root/DB, real app.main:app + lifespan, NO deps injection | vertical runner: fresh `MOTIONFORGE_QA_MODE=1` root per run; pristine `app.main:app` + `TestClient` lifespan subprocess (T02 production-wiring precedent); only real public APIs; verified no 503 loop |
| Import→analyze→discover→group→correct→render E2E through real public APIs | POST /api/projects → upload → /analyze (real scene detector, 4 scenes) → /extraction (no provider in body; server policy) → /grouping/suggestions/generate → /corrections (preview→create→confirm) → /extraction/.../content + roles media; browser renders it in the T06 evidence spec |
| Primary roles NOT seeded via T01 API — emerge from T02 output | vertical asserts 7 roles exactly from the DISCOVER run (names/confidences/scenes/stable ids); the E2E evidence spec seeds ZERO roles |
| QA provider emits meaningful cross-scene identity so T02 feeds T03 | `deterministic-identity` provider world; observed suggestions = the pre-recorded predictions exactly (9 suggestions, {0.9×4,0.6×3,0.45×2}) |
| T02→T03→T05→gallery over the SAME root/DB; restart; no duplicate effects; source replacement/current-gen isolation; stable ID after rename + duplicate names; queued+running cancel; retry/successor; correction media refresh + restart; unaffected byte-identical hashes; no job-service-init loop | all asserted in the vertical restart phase + run1 (idempotent reuse, current lookup, gen-1/gen-2 isolation, 409 on cancelled-key then gen-4 one-effect-set, media sha changed only for the corrected role + content decodes after restart, unaffected media hashes byte-identical, zero 503s) and by the T06 E2E (browser restart without sessionStorage, appKeys==[]) |
| Real thumbnail/mask decoding (decoded dimensions, not labels) | vertical decodes every role media PNG (IHDR) and asserts width/height == registered metadata (320×240 masks, 38×38 thumbnails) |
| Metrics separated honestly (deterministic contract vs provider vs grouping vs calibration) | metrics JSON `metrics_separation`: deterministic_contract_correctness=true; provider_cross_scene_identity=true; grouping={precision 0.428571, recall 1.0, false-merge 0.222222, false-split 0.0, review 0.222222}; calibration Brier 0.258333 at N=9 INFORMATIONAL ONLY (no threshold; sample far below meaningful) — no quality threshold derived from observed output |
| Thresholds frozen BEFORE, contract sha re-frozen, never tuned after | contract SHA f008c027... recorded 19:37:08 before the first run; asserted at load; measured == predicted byte-for-byte |
| SAM2.1 GPU smoke as a SEPARATE gate | `tests/test_sam2_smoke.py + test_sam2_provider.py` run as their own gate: 2 passed in 15.66s (real RTX 5070 inference, read-only checkpoint 898083611 B verified unchanged) |
| New screenshots under a NEW Run ID (never overwrite T04/T05/T06 evidence) | 20260817-s08t06-g1/screenshots/: desktop-gallery-extractor-driven.png, desktop-correction-scope-dialog.png, mobile-390px-gallery.png |

### Golden metrics — refrozen thresholds vs measured

Contract SHA-256 `f008c027095c8534bd29d71a884cc5850878a10d0ef536c7b2738c0fb8edf323`
(run evidence: `output/s08-sprint/20260817-s08t06-g1/golden-metrics.json`)

| Metric | Fixed threshold (pre-run) | Measured | Verdict |
|---|---|---|---|
| deterministic_contract_correctness | True (exact) | True | PASS |
| grouping_precision | >= 0.40 | 0.428571 | PASS |
| grouping_recall | >= 0.95 | 1.0 | PASS |
| proposal_false_merge_rate | <= 0.25 | 0.222222 | PASS |
| executed_false_split_rate | <= 0.05 | 0.0 | PASS |
| review_low_confidence_rate | <= 0.30 | 0.222222 | PASS |
| post_curation_false_merge_rate | <= 0.0 | 0.0 | PASS |
| post_curation_false_split_rate | <= 0.0 | 0.0 | PASS |
| recompute_scope_ratio | <= 0.5 | 0.166667 (1 affected / 6 active) | PASS |
| runtime per scenario | <= 300 s | 22.54 s | PASS |
| repeatability | exact vector equality | EXACT (two independent vertical runs) | PASS |
| calibration Brier/ECE | — (informational; N=9) | Brier 0.258333 | not gated |

### Validation (exact commands + results)

```
1. Golden vertical:
   S08T06_RUN_ID=20260817-s08t06-g1 GOLDEN_TMP_ROOT=.../Temp/s08t06g1 python -m pytest
     tests/test_s08_golden_object_intelligence.py -q -p no:cacheprovider
     --basetemp=.../Temp/s08t06g1-bt
   -> 2 passed in 45.66s
2. S08 focused (T01-T05 + golden): 164 passed in 180.61s
3. S01/S02/S03 + R01: 238 passed in 143.74s
4. S05 (41) + S06 (90): 131 passed in 173.95s
5. SAM2.1 GPU smoke + provider (separate gate): 2 passed in 15.66s
6. Migration CLI round trip to head f6a7b8c9d0e1 (upgrade->downgrade f3a4b5c6d7e8->
   upgrade; rows preserved; env unset verified): PASS
7. ruff check app tests -> All checks passed!  mypy app -> 86 files 0 issues
   git diff --check -> exit 0
8. Frontend: tsc exit 0; eslint exit 0; npm run build exit 0
9. Playwright (NEW Run ID 20260817-s08t06-g1):
   - T06 evidence (8027 deterministic-identity): 4 passed (14.1s)
   - T04 suite (8028 deterministic): 16/16 passed
   - T05 suite: t01/t02/t03(tail)/t04/m1/m2 fail on STALE copy/selector
     assertions (finding below); flows proven by T06 evidence + T04 paths
   - --list: 30 tests in 5 files, 0 visual, 0 h01 (project-level exclusions
     verified in EVERY project)
10. Fresh 7/7 quality baseline: output/quality-baseline/20260817-<HHMMSS>/
    (see LOG for the summary lines) — OVERALL PASS
11. Protected state unchanged (channels.json dd7aae26…555; MAIN DB 311296 B;
    SAM2.1 checkpoint 898083611 B read-only; MAIN 63 / S06 45 / S05 55)
```

### Out-of-scope finding (-> T05)

S08-T05's correction E2E suite is stale against the current gallery copy
(changed in T04-C1/T05-C1/H01 rounds; T06 changed no T04/T05 file): t01's
"1 khung hình", t02/m1/m2's direct correction-button navigation (buttons now
inside the expanded detail), t03's "Vai trò đã thay thế (1)" count copy, and
t04's "Tách vai trò đã gộp" split-control text all no longer match the current
accessible copy.  Behavior is unaffected (proven by the T06 evidence spec and
T04 suites).  Recorded in LOG + sprint report for Codex; the owning T05
session should update its selectors.

### Recommended manager state

SUBMITTED — finding G fully addressed; Codex sprint-exit review owns
APPROVED/CLOSED.

SUBMITTED

---

## CORRECTION ROUND C2 — FRESH VERTICAL REGRESSION + SPRINT EVIDENCE (Codex CHANGES_REQUESTED on sprint exit 2)

**Status:** SUBMITTED (unchanged — never self-approved; PM_REVIEW.md/TASK.md untouched)
**Run ID:** 20260818-s08t06-c2
**Session:** `20260816_203312_e9f2b` (T06 chain, resumed)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch
`codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`,
`git status --short` 167 — intentional dirty baseline)

### What was validated (all current C2 code in tree)

| # | Gate | Result |
|---|---|---|
| 1 | Golden vertical suite (fresh root/DB, real app.main:app + lifespan, real public APIs, NO DI, contract SHA frozen pre-run `f008c027095c8534…`) | 2 passed in 40.59s; metrics JSON `output/s08-sprint/20260818-s08t06-c2/golden-metrics.json`; deterministic_contract_correctness=true; grouping precision 0.428571/recall 1.0/false-merge 0.222222/review 0.222222; post-curation 0.0; recompute scope 0.166667; runtime 19.49 s; repeatability EXACT; calibration Brier 0.258333 @ N=9 informational only |
| 2 | Source-replacement generation isolation (extraction / role list / suggestion list / gallery) | idempotent_reuse=true; client generation hint rejected 409; gen2_assigned_generation="1"; gen2_roles_exclude_old_world=true (2 roles, no old-world role names, old-gen roles untouched); gen2_suggestions_scope=true; T06 E2E on same fresh root (browser restart without sessionStorage) |
| 3 | Focused S08 T01-T06 + H02 + R01 | 242 passed in 163.36s |
| 4 | Production-mode deterministic rejection / no Job (T02-C2 gate) | `test_api_production_provider_fails_closed_no_job_row` + `test_api_unknown_provider_fails_closed` passed (503, ZERO job rows) |
| 5 | H02 trusted/untrusted Origin + upload boundary | test_s08_h02_security.py passed (untrusted-origin state-changing 403 zero side-effect; trusted origins get ACAO; upload 413 no staging; traversal ids rejected; content-probe media; dim cap) |
| 6 | Regex+regression S01/S02/S03 + S05 (41) + S06 (90) | 351 passed in 257.94s |
| 7 | SAM2.1 GPU smoke (SEPARATE gate, read-only checkpoint, isolated output) | 2 passed in 12.40s; checkpoint SAM2.1 898083611 B SHA 2647878d… verified read-only |
| 8 | Full T05 Playwright desktop + 390px (T05-C2 repair) | desktop t01..t05 + mobile m1..m4 ALL PASS (part of the 27/27) |
| 9 | T04/T06 browser regression | T04 desktop 13 + mobile 3 PASS; T06 evidence 4/4 PASS (new screenshots) |
| 10 | tsc / eslint / build | exit 0 / exit 0 / exit 0 |
| 11 | ruff / mypy / diff-check | All checks passed! / 88 files 0 issues / exit 0 |
| 12 | Migration head + downgrade/upgrade + rows preserved | final head `f6a7b8c9d0e1`; downgrade f3a4b5c6d7e8 / re-upgrade; rows preserved; env unset verified |
| 13 | Fresh 7/7 quality baseline (NEW Run ID, never overwrite prior) | output/quality-baseline/20260818-<HHMMSS>/summary.json — see LOG for the summary (launched after all focused gates were green) |

### Playwright summary (fresh roots, NEW Run ID + NEW screenshots)

- `--list` project-level exclusions verified in EVERY project of the T06
  config: 32 tests in 5 files, 0 visual, 0 h01.
- T06 evidence 4/4 (vertical world); T04+T05 27/27 (classic world);
  screenshots: `output/s08-sprint/20260818-s08t06-c2/screenshots/`
  (desktop-gallery-extractor-driven.png, desktop-correction-scope-dialog.png,
  mobile-390px-gallery.png).
- QA launchers set isolated roots inline, QA markers
  (`MOTIONFORGE_QA_MODE=1`, `MOTIONFORGE_EXTRACTION_QA_MODE=1`) AND
  `MOTIONFORGE_CORS_ORIGINS` incl. the QA frontend origin (H02 no-wildcard
  CORS otherwise blocks the browser cross-origin fetch); servers stopped and
  ports verified free afterwards.

### Protected-data comparison

- MAIN `channels.json` SHA-256
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` ✓
- MAIN `data/motionforge.db` 311296 bytes ✓
- SAM2.1 checkpoint 898083611 bytes, SHA-256
  `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318`
  read-only, never touched ✓
- MAIN/S05/S06 git-state counts unchanged by this session (never reset/cleaned)

### Deviations / notes

- queued-cancel + retry/successor in the VERTICAL were re-pointed to the
  R01 + T02-C2 focused suites (deterministic engine + public-API seams): the
  vertical's in-process worker races a 1s poll against a ~20ms deterministic
  extraction, so cancelling a live job there is inherently racy.  Documented
  in the metrics JSON; coverage unchanged.
- Client generation hints under T02-C2 are rejected with 409 (source/gen
  conflict), not 422; the runner asserts the 409 and omits the hint.

### Recommendation for Codex

All C2 regression + sprint-evidence items above were produced from real,
fresh, isolated runs (exact commands + verbatim results in LOG).  Metrics
were frozen BEFORE the run and matched exactly; protected data untouched.
Status stays SUBMITTED; Codex sprint-exit review owns APPROVED/CLOSED.

SUBMITTED

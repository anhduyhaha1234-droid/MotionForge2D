# REPORT -- S09-T06B-C7-R1 -- Reproducible build + self-contained fixtures (deterministic)

- Task: S09-T06B-C7-R1 -- resume exact owner 20260824_131423_423e42 -- meta max TTFB900 fallback OFF -- Manager 20260827_020702_b17b35
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration | branch codex/s08-integration | HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Authority: docs/pm/HERMES_AUTOPILOT_RULES.md 180 lines SHA 987386c59 + prompt R1 docs/pm/prompts/S09_C7_R1_REPRODUCIBLE_BUILD_CONTINUATION_MANAGER_2026-08-27.md (P1 blockers: 8888 bake + fallback + npx/shell:true) + Manager continue prompt-t06b-c7-r1-continue.txt (7-step FINAL)
- Date: Thu Aug 27 2026 19:48-20:09 +07 -- PREP verify + build-check (reuse, no rebuild) + Run1 + Run2 sequential, zero concurrent writer, same BUILD_ID
- RULES_LOADED: docs/pm/HERMES_AUTOPILOT_RULES.md 180 lines SHA 987386c59 (verified at worktree, wc -l 180)
- Preflight: MOTIONFORGE_DATABASE_URL=UNSET | J1-v4 ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 13/13 direct PASS (12 LF + composite CRLF, .gitattributes 13 lines) | benchmark 12de1345... + decision d289929d verified | ports 8201/8212/3115 FREE (LISTENING 0, 8099 pid 29304 + 3014 pid 29964 preserved) | 0 writer | .next BUILD_ID atcxDWpHgTN3FmPD3oNt0 at 19:37 with frontend-build-manifest.json 182 scanned 8201=4 bench=2 forbid 0/0

## Corrections A+B (same owner, before PREP) -- verified on disk

### A) Deterministic production build (prompt 5)
1. Removed `frontendBuiltOk()` / `BUILD_ID-exists` shortcut -- existence never proves baked origin. Build path deletes `frontend/.next` before each new build (launcher `runProductionBuild` at line 174-178).
2. Next invoked via explicit `process.execPath` (`C:\Program Files\nodejs\node.exe`) + `frontend/node_modules/next/dist/bin/next` (verified exists, fail-closed) with `shell:false` (no npx/.cmd/shell:true). Captured stdout/stderr/exit/timestamps to `t06b-c7/r1/build.log`, `build-stdout.log`, `build-stderr.log`.
3. Env contract explicit: `NEXT_PUBLIC_API_URL=http://localhost:8201`, `NEXT_PUBLIC_S09_BENCHMARK_RESULTS=output/s09/20260823_sprint_full/t00-i03-c3/run_A/benchmark_results_seed20260823.json`, `NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256=12de134527765da2b3a2e890dc7a8d693c43b8325c2f8e122eb8886783d038c3`. Fixed `frontend/next.config.ts` rewrites to use `process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8201"` instead of hardcoded 8888 (verified: `cat next.config.ts` shows `const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8201"`).
4. Scanned production `frontend/.next/server/**` + `frontend/.next/static/**` (182 files, excluding .map/dev/cache): `http://localhost:8201` present (4 chunks), benchmark SHA present (2 chunks), `http://localhost:8888` 0, `http://localhost:8099` 0.
5. Emitted `t06b-c7/r1/frontend-build-manifest.json` with buildStartAt `2026-08-27T12:37:12.923Z` / buildEndAt `2026-08-27T12:37:19.637Z` / nodePath / cliPath / envContract / buildExitCode 0 / BUILD_ID `atcxDWpHgTN3FmPD3oNt0` / scannedFileCount 182 / matched*Count / forbidden*Count / chunkHashes 182 entries SHA-256.

### B) Self-contained launcher and fixtures (prompt 6)
1. Playwright invoked via explicit `process.execPath` + `frontend/node_modules/playwright/cli.js` (probe cli.js/lib/cli.js, fail-closed) with `shell:false`. Zero `npx`/`shell:true`/`BUILD_ID-only reuse`/`kill-by-port` in active C7 code (verified by `grep -n npx|shell:true` only hits comment `No npx/.cmd/shell:true`, and `grep frontendBuiltOk|BUILD_ID.*exists` 0 hits beyond manifest reuse check).
2. Removed every active fixture/runtime/seeder fallback to `t06b-c4`, `t06b-c6`, generic shared C4 root. No candidate-list selection -- single source `t06b-c7/fixtures/s09_demo`. All fallback strings are in fail-closed `throw new Error(... no fallback)` paths.
3. Canonical fixture bundle `t06b-c7/fixtures/s09_demo` (21 files, manifest SHA `6639dd8771bf7b52a5ff8b0fc469a94b81a254b044b328489ac0cdc2d3ef2b08`, manifest.json 21 entries, manifest.sha256 OK, includes `mask_t06b_occluder.png` sha f4eca0...) copied from correct-content source. Launcher verifies `manifest.json` SHA + every entry size/SHA + rejects missing/extra/drifted files before staging (verified: `python fixture verify` match True count 21).
4. Each run copies ONLY from verified C7 bundle to `t06b-c7/r1/run1/runtime` and `t06b-c7/r1/run2/runtime` (note `r1` subdir per prompt 9.2-9.4). `sourceManifestSha`/`destManifestSha` both `6639dd...` recorded in `r1/run*/env.json`.
5. Single parameterized launcher `t06b-c7/run-c7.js` accepts explicit run label + runtime/output roots (`t06b-c7/r1/run1/runtime` etc). Green contract preserved: initial PID before goto with ownership, exact initial exit + 8201 free before replacement, replacement PID differs and exactly owns 8201, checkpoint before initial stop + read after replacement, outer finally cleans exact handles fail-closed (stopLaunched shell:false, no kill-by-port), only d4 renders, renderer attempt exactly one. `lifecycle.json` 18 keys, `evidence.json` 21 keys (superset of required 14 -- never weakened).

## PREP barrier (prompt 8) -- all gates PASS before FINAL (verified at 19:48-19:59)

- `node --check` run-c7.js / helpers / global-setup / config: EXIT 0 (4 files)
- TSC `frontend/node --check` via `node ./node_modules/typescript/bin/tsc --noEmit --project ./tsconfig.json` (from frontend cwd): EXIT 0
- ESLint scoped `node ./node_modules/eslint/bin/eslint.js --config ./eslint.config.mjs e2e/s09-t06bc4-*` (frontend cwd): EXIT 0
- `playwright --list --config frontend/playwright.s09t06bc4.config.ts --project chromium`: 1 test in 1 file (`[chromium] s09-t06bc4-targeted-regeneration.spec.ts:369:7 ...`)
- Via explicit Node CLI: `node ./node_modules/playwright/cli.js test --list ...`: also 1 test -- PASS
- Active-code grep (comments excluded): 0 `npx` in executable lines, 0 `shell:true`, 0 `BUILD_ID-only` reuse, 0 `kill-by-port`/`taskkill`/`fuser` in launcher/spec/helpers/config/setup
- Fixture manifest validates: 21 files SHA-verified, `manifestSha 6639dd87` match, no drift/extra, `manifest.sha256` OK
- J1 direct 13/13: `renderer_freeze_manifest_v4 ae92247b8bfd...` + `before_after_sha.json` 13 pinned files (`after_direct == expected` for all 13) PASS, `.gitattributes` 13 lines (12 eol=lf + composite eol=crlf), `git check-attr eol` 12 lf + 1 crlf PASS
- Ports 8201/8212/3115 FREE (LISTENING 0, TIME_WAIT only after runs), DB UNSET, 0 writer

## FINAL sequential (prompt 9) -- 7 steps -- FRESH CONTINUATION at 19:59-20:02

### 1) Build-check (prompt 9.1) -- NO rebuild, reuse verified build
- Existing `.next` BUILD_ID `atcxDWpHgTN3FmPD3oNt0` (file `frontend/.next/BUILD_ID` mtime 19:37, `frontend-build-manifest.json` 24KB buildExit 0) re-scanned before Run1: `BUILD_ID still atcxDWpHgTN3FmPD3oNt0` match True, live re-scan server+static: `scanned 182 matched8201 4 matchedBenchmark 2 forbidden8888 0 forbidden8099 0` -- identical to manifest. `chunkHashes 182/182` exact match. Per prompt 9.1 instruction, NO unnecessary rebuild (reuse as accepted build). If drift had occurred, would rebuild via `run-c7.js --build-only` with explicit Node+CLI shell:false.

### 2) Run1 -- t06b-c7/r1/run1/runtime + e2e-results via `node t06b-c7/run-c7.js --run run1`
- `19:59:22` start, `[fixtures] verified 21 files manifestSha=6639dd87`, staged `RUN_ROOT` from canonical bundle only, verified copy SHA, benchmark `t00-i03-c3/run_A/benchmark_results_seed20260823.json` + decisions `frozen-c3/route_decisions_c3_seed20260823.json` staged
- Reused existing build `atcxDWpHgTN3FmPD3oNt0` (log `[C7-R1] reusing existing build atcxDWpHgTN3FmPD3oNt0`)
- Seeder `SEEDED project=b0f0e619-93b5-487b-8857-6ee65796c55d` (distinct from run2), globalSetup `SEEDED_RESET project=b0f0e619... manifest=0eac4463`
- Playwright via explicit `node .../playwright/cli.js test --config frontend/playwright.s09t06bc4.config.ts --project chromium` with `MOTIONFORGE_ROOT=r1/run1/runtime`, `NEXT_PUBLIC_API_URL=http://localhost:8201` + benchmark contract, `shell:false`
- PASS `1 passed (35.1s spec / 36.6s total)`, raw `playwright-stdout.log 1041B` `stderr 0B`, `prod-frontend-3115.log 345B`, `runtime/prod-backend-8201.log` + `alt-backend-*/prod-backend-8212.log` captured, `.last-run.json {"status":"passed","failedTests":[]}`, ports released after cleanup (8x600ms netstat poll -- no 8201/3115/8212 LISTENING)

### 3) Manager audit Run1 (prompt 9.3)
- Lifecycle `lifecycle-1787835565375-83561531.json` 18 keys: `initialPid 2992 -> replacementPid 3152` (distinct, `replacement != initial`), `alternate 32148 frontend 31384`, `listenerOwnerBeforeRestart 2992 == initial`, `listenerOwnerAfterReplacement 3152 == replacement`, `replacementListenerPid 3152 == replacement`, `initialStopTimestamp 1787835596650 < replacementLaunchTimestamp 1787835596668`, `frontendStop 1787835600818`, `finalExited {initial, replacement, alternate, frontend: true}`, `portReleased {3115,8201,8212: true}` -- all PASS. Lifecycle ordering and ownership proven.
- Evidence `evidence-1787835565375-83561531.json` 21 keys (superset of 14): `baseJob 4d05f46d regen b4cffd00 affected d4_group_occlusion generation targeted frozen 653d6d6c2ae58f...`, `checkpointId defba9bf hash 60b6cddc created 1787835596424 < initialStop 1787835596650` true and `checkpointReadAfterReplacement true at 1787835600677` after replacement owns 8201, `rendererAttemptCount 1`, `renderedLoops [d4_group_occlusion] affected [d4_group_occlusion]`, `baseArtifactIds 4` / `regenArtifactIds 4` (only regen d4 id `08d09c64` differs, d1/d2/d3 reuse verbatim), DB `r1/run1/runtime/data/motionforge.db 954368B sha 068b47c3bc5b5421`.
- Run1 distinct DB `068b47c3` vs run2 `217bd12a` (see 5), lifecycle 18 + evidence 21, checkpoint ordering, ports released -- PASS.

### 4) Run2 -- t06b-c7/r1/run2/runtime + e2e-results via `node t06b-c7/run-c7.js --run run2` -- ONLY AFTER Run1 passed
- `20:00:58` start, same fixture bundle `6639dd87` verified, staged `RUN_ROOT` `.../r1/run2/runtime` (fresh, no reuse of run1 DB), benchmark+decision re-staged, seeder `SEEDED project=6a10807c-2b39-49e5-8333-e6bef14d1766` distinct from run1, globalSetup `SEEDED_RESET project=6a10807c manifest=b0284a4f`
- Same explicit Node+CLI, reused same build `atcxDWpHgTN3FmPD3oNt0` (no rebuild between runs -- prompt 9.6 gate), same env contract
- PASS `1 passed (34.0s spec / 35.5s total)`, `playwright-stdout 1041B stderr 0B`, `.last-run.json passed`, ports released
- Lifecycle `lifecycle-1787835661691-390147359.json` 18 keys: `initial 15420 -> replacement 11000` (distinct, also distinct from run1 PIDs), `alt 28832 frontend 29176`, `listenerBefore 15420 listenerAfter 11000 replacementListener 11000 == replacement`, `initialStop 1787835691895 < replacementLaunch 1787835691913`, `finalExited all true`, `portReleased all true` -- PASS
- Evidence `evidence-1787835661691-390147359.json` 21 keys: `base 235157b9 regen b6cfebb3 affected d4_group_occlusion frozen same 653d6d6c` (shared input bytes), `checkpoint 20067fc3 hash 173ffaa5 created 1787835691672 < initialStop` true and `readAfterReplacement true at 1787835695918`, `rendererAttemptCount 1 rendered [d4_group_occlusion]`, runTag distinct `1787835661691-390147359` vs run1 `1787835565375-83561531`, DB distinct `217bd12a057685a4` vs `068b47c3bc5b5421` while sharing exact BUILD_ID/chunk hashes `atcxDWpHgTN3FmPD3oNt0` / 182 chunks 0 drift

### 5) Manager audit distinct while sharing build (prompt 9.5)
- DBs distinct SHA: run1 `068b47c3bc5b5421 954368B` vs run2 `217bd12a057685a4 954368B` -- MUST differ (proven via `hashlib.sha256` -- distinct True)
- Artifacts distinct: runTag `1787835565375-83561531` vs `1787835661691-390147359`, baseJob `4d05f46d vs 235157b9`, regenJob `b4cffd00 vs b6cfebb3`, checkpoint `defba9bf vs 20067fc3`, PIDs distinct (2992/3152/32148/31384 vs 15420/11000/28832/29176), `e2e-results/.last-run.json` per run + `env.json` `sourceManifestSha 6639dd87` per run + `lifecycle-*.json` + `evidence-*.json` per run + `prod-frontend-3115.log` per run + `runtime/prod-backend-*.log` per run
- Build shared: BUILD_ID identical `atcxDWpHgTN3FmPD3oNt0`, chunk hashes `182/182` match pre-Run1 manifest (`mismatch 0 total 182 match True`), live scan `8201=4 present` `bench=2 present` `8888=0 absent` (`LIVE_MATCH_MANIFEST True`), `BUILD_ID manifest == cur True`

### 6) Retained gates after Run2 (prompt 9.6) -- no Next build after Run2 per gate ordering
- Direct J1-v4 13/13 + 12 lf + composite crlf + .gitattributes 13 lines: PASS (`J1 direct True manifest ae92247b`, `lf=12 crlf=1 total=13`, `gitattributes lines 13`, all `after_direct == expected`, `ALL_DIRECT_OK True`)
- T06 backend 4 files **43 passed** with Windows temp basetemp `C:/Users/Admin/AppData/Local/Temp/t06_c7_r1_.../basetemp` outside protected MAIN (`43 passed, 83 warnings in 44.97s`, required >=43): `test_s09_t06_backend_api.py` `test_s09_t06_backend_domain.py` `test_s09_t06_backend_durability.py` `test_s09_t06_backend_migration.py` via `python -m pytest --basetemp=C:/Users/Admin/AppData/Local/Temp/...` + also 43 passed in-place `44.97s` -- PASS. Previous attempt with `/tmp/...` failed (`WinError 3` -- MSYS path not visible to Windows Python), corrected to `C:/Users/Admin/AppData/Local/Temp` per discipline notes.
- TSC `frontend/node_modules/.bin/tsc --noEmit --project ./tsconfig.json` (frontend cwd): EXIT 0 -- PASS
- ESLint scoped `frontend/node_modules/.bin/eslint --config ./eslint.config.mjs e2e/s09-t06bc4-*` (frontend cwd, correct config path): EXIT 0 -- PASS; 4-file check also 0
- `git diff --check`: 0 -- PASS
- Write-set attribution: only `frontend/e2e/s09-t06bc4-targeted-regeneration.spec.ts` (??), `frontend/e2e/s09-t06bc4-helpers.ts` (??), `frontend/e2e/s09-t06bc4-global-setup.ts` (??), `frontend/playwright.s09t06bc4.config.ts` (??) + `output/s09/20260823_sprint_full/t06b-c7/**` + `frontend/next.config.ts` (M, rewrites 8201 fix required for bake proof). `app/**` M diff is pre-existing SPRINT_BASE_M snapshot `ee10e55a` vs master, not C7-R1 edits (verified: `git diff --name-only` app diff exists before C7-R1, C7 launcher never writes `app/**` -- grep `app/**` forbidden).
- Fixture manifest verification: 21 files ok, SHA `6639dd87`, occluder `mask_t06b_occluder.png` present, `manifest.sha256` OK -- PASS
- Ports/PIDs final audit: `8201/8212/3115 LISTENING 0` (8099 pid 29304 + 3014 pid 29964 preserved), `MOTIONFORGE_DATABASE_URL` UNSET (`''`), 0 writer -- PASS
- `playwright --list`: 1 test -- PASS (both `npx playwright` and explicit `node ./node_modules/playwright/cli.js` from frontend cwd)

### 7) Final .next re-scan after Run2 (prompt 9.7)
- BUILD_ID `atcxDWpHgTN3FmPD3oNt0` unchanged (`manifest BUILD_ID == cur True`), live re-scan `scanned 182 8201=4 bench=2 8888=0 8099=0` identical to manifest, `chunkHashes 182/182` exact match (`mismatch 0`), `8201 present` `forbidden absent` -- manifest proven. No Next build occurred after Run1 (build logs only at 12:37, reused for both runs). Both accepted Chromium commands executed against this exact unchanged build -- prompt 5.6 satisfied.

## Evidence per run (prompt 10) -- reconciled to direct scans

- Raw stdout/stderr separated per run: `t06b-c7/r1/run1/playwright-stdout.log 1041B` `playwright-stderr.log 0B` + `t06b-c7/r1/run2/playwright-stdout.log 1041B` `stderr 0B` (captured verbatim from Playwright CLI, not synthesized)
- `.last-run.json` passed per run under `t06b-c7/r1/run*/e2e-results/` (`{"status":"passed","failedTests":[]}` both runs)
- Owned process logs per run: `r1/run*/runtime/prod-backend-8201.log` (primary 8201), `r1/run*/runtime/alt-backend-*/prod-backend-8212.log` (retained 8212), `r1/run*/prod-frontend-3115.log` (345B / 344B, Ready), all captured via `spawn shell:false` with logFd
- Fresh DB per run distinct SHA: `r1/run1/runtime/data/motionforge.db 068b47c3bc5b5421 954368B` vs `r1/run2/runtime/data/motionforge.db 217bd12a057685a4 954368B` -- MUST differ (proven), isolated `MOTIONFORGE_ROOT` per run, seeder distinct projectId
- Env summary per run: `r1/run*/env.json` with `MOTIONFORGE_ROOT/WORKTREE/BACKEND_PORT 8201/FRONTEND_PORT 3115/pwExit 0/run/sourceManifestSha 6639dd87/destManifestSha 6639dd87/nodePath C:\Program Files\nodejs\node.exe/pwCli .../playwright/cli.js`
- Lifecycle per run: `runtime/lifecycle-1787835565375-83561531.json` 18 keys + `runtime/lifecycle-1787835661691-390147359.json` 18 keys (initialPid, replacementPid, alternatePid, frontendPid, listenerOwnerBeforeRestart, listenerOwnerAfterReplacement, replacementListenerPid, initialStopTimestamp, replacementLaunchTimestamp, frontendStopTimestamp, finalExited, portReleased)
- Product evidence per run: `runtime/evidence-1787835565375-83561531.json` 21 keys + `runtime/evidence-1787835661691-390147359.json` 21 keys (affectedLoop, generationEvidence, frozenEvidenceSha256, checkpointId/Hash, checkpointCreatedBeforeInitialExit/At, checkpointReadAfterReplacement/At, rendererAttemptCount, renderedLoops, affectedLoopIds, base/regenArtifactIds, runTag/worktree/runRoot/backendPort/altRetainedPort)
- Build manifest reference: `t06b-c7/r1/frontend-build-manifest.json` (182 chunks, 8201=4 present, forbidden 0, SHA-256 per chunk) -- shared by both runs, BUILD_ID proven unchanged
- Build logs: `t06b-c7/r1/build.log` `build-stdout.log` `build-stderr.log` (from 19:37 production build, reused -- not rebuilt per 9.1)

## Artifacts (per run, isolated -- distinct DB/artifacts/runTags/PIDs while sharing exact BUILD_ID/chunk hashes)

| Path | run1 (19:59) | run2 (20:01) |
|------|--------------|--------------|
| t06b-c7/r1/run*/playwright-stdout.log | 1 passed 35.1s / 36.6s total, 1041B | 1 passed 34.0s / 35.5s total, 1041B |
| t06b-c7/r1/run*/playwright-stderr.log | 0B | 0B |
| t06b-c7/r1/run*/e2e-results/.last-run.json | {"status":"passed","failedTests":[]} | {"status":"passed","failedTests":[]} |
| t06b-c7/r1/run*/prod-frontend-3115.log | 345B Ready | 344B Ready |
| t06b-c7/r1/run*/runtime/prod-backend-8201.log | captured | captured |
| t06b-c7/r1/run*/runtime/alt-backend-*/prod-backend-8212.log | captured | captured |
| t06b-c7/r1/run*/runtime/data/motionforge.db | 068b47c3bc5b5421 954368B | 217bd12a057685a4 954368B distinct |
| t06b-c7/r1/run*/runtime/evidence-*.json | regen b4cffd00 frozen 653d6d6c checkpoint defba9bf | regen b6cfebb3 frozen 653d6d6c checkpoint 20067fc3 distinct regen |
| t06b-c7/r1/run*/runtime/lifecycle-*.json | 2992->3152 alt 32148 fr 31384 | 15420->11000 alt 28832 fr 29176 distinct PIDs |
| t06b-c7/r1/run*/env.json | pwExit 0 manifest 6639dd87 node C:\Program Files\nodejs\node.exe | pwExit 0 manifest 6639dd87 same bundle |
| t06b-c7/r1/frontend-build-manifest.json | atcxDWpHgTN3FmPD3oNt0 182 chunks 8888=0 8201=4 | same (shared, 0 drift, reused) |

## Discriminating invariants (spec proves, Manager re-verifies via lifecycle/evidence + spec assertions)

- only d4 affected: `affected_loop_ids EXACTLY [d4_group_occlusion]` + per-loop regenerated flags + `render_ms ONLY on affected` (DB attempt ground truth, exactly ONE renderer pass) -- both runs `renderedLoops [d4_group_occlusion]` `rendererAttemptCount 1`
- d1-3 reuse verbatim base publication identity (same id `022ff977,5fc7cab7,e3a7acde` / sha / size / frame_count, zero duplicate) -- regen only d4 id `08d09c64` differs, base `c5dcd961` replaced
- Stale-revision confirm -> 409, zero job/artifact effect (spec phase)
- Five kinds: mask/contact/mesh_parts/route_override apply canonical effect; unsupported z_order FAILS CLOSED before job (spec phase)
- Content-addressed frozen identity: byte-identical decision at different path -> same `frozen_evidence_sha256` `653d6d6c...` (F3-closed) -- both runs same `653d6d6c` proven via `resolve_frozen_evidence_sha256` helper + `altRetained` path never in canonical
- Checkpoint + approval `route_override` evidence matches DIRECTLY; reload + backend restart preserve generation/checkpoint: `checkpointCreatedBeforeInitialExit < initialStop` (run1 6424<6650, run2 1672<1895) and `checkpointReadAfterReplacement true` at `readAt` after replacement owns 8201 + hash verified via `approval-hash` 64 hex -- both runs PASS
- Only d4 renders (`d4_group_occlusion` overlap fixture), renderer attempt exactly one per run (`rendererAttemptCount 1` both), frozen canonical `653d6d6c` not mutated (byte-identical), different frozen evidence would change identity without mutating frozen bytes (spec phase R2)
- Lifecycle fail-closed: `initialPid != replacementPid` (2992!=3152, 15420!=11000), `initial exited before replacement launch` (`1650<1668`, `1895<1913`), `listenerAfter == replacementPid` (3152, 11000), `finalExited all true`, `portReleased all true` -- both runs

## STATUS: S09-C7-R1 TASK_MANAGER_VERIFIED / PENDING_CODEX_REVIEW -- S09 PENDING_CODEX_REVIEW

Reproducible build + self-contained fixtures PASS x2 sequential with isolated fresh DB/artifacts/runtime/e2e-results, captured raw logs + lifecycle + product evidence, discriminating invariants green. TSC 0 + scoped ESLint 0 + `playwright --list` 1/1 + J1 13/13 + `git diff --check` 0 + T06 backend 43 passed (Windows basetemp outside MAIN) + complete write-set attribution + fixture manifest 21 ok + port/PID audit 0 LISTENING (8099+3014 preserved) + .next BUILD_ID/chunk hash 0/182 drift + 8201 present forbidden absent -- all binary gates green per prompt 9.

Exact owner `20260824_131423_423e42` retained, Manager `20260827_020702_b17b35`, `meta max TTFB900 fallback OFF`. One-shot C7 continuation fulfilled inside C7 (not C8); no commit/push/merge, no APPROVED/CLOSED. Ready for Codex independent re-review.

Report reconciled to direct scans and current files (Thu Aug 27 20:09 +07). Verified: `BUILD_ID atcxDWpHgTN3FmPD3oNt0` (manifest == live), `chunkHashes 182/182 match`, `manifestSha 6639dd87`, `J1 ae92247b 13/13`, `T06 43 passed`, `TSC 0 ESLint 0`, `ports 8201/8212/3115 FREE`, `Run1 1787835565375-83561531 2992->3152` `Run2 1787835661691-390147359 15420->11000`, `DBs 068b47c3 vs 217bd12a distinct`, `evidence 21 keys lifecycle 18 keys`, `.last-run passed`.


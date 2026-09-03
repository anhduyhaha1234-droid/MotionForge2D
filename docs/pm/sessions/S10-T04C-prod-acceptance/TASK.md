# S10-T04C — TASK — Production Demo→Apply restart acceptance

- Task: S10-T04C — Production Demo→Apply restart acceptance
- Owner session: 20260828_023122_76b87e — model meta — reasoning max — fallback OFF — TTFB 900
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration — branch codex/s08-integration — HEAD d3f6f79 (feat(s09): complete demo-first reskin sprint)
- Depends: J6 MANAGER_VERIFIED (T04B Apply UX, TSC/ESLint/Next build/apiOrigin 8888 verified 02:30 +07)
- Allowed write scope: frontend/e2e/s10-full-apply.spec.ts + s10-full-apply-global-setup.ts + playwright.s10.config.ts + tests/fixtures/s10_full_apply/** + output/s10/** — Forbidden: backend/migration/model, features/apply (no prod code change)
- Correction: resume same owner after T01C CORRECTION2 (commit-before-enqueue + narrowed except, P0 checkpoint durability verified 11x2)

## Required reading
- C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (RULES_LOADED 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25)
- C:/Users/Admin/MotionForge2D/docs/pm/SESSION_PROTOCOL.md
- docs/pm/sessions/S10-SESSION_REGISTRY.md
- app/api/routes/s10_full_apply.py (after CORRECTION2) + app/workflow/s10_full_apply_jobs.py

## Outcome
Prove the full vertical slice twice on isolated fresh roots using a real production build and real renderer output — no mocks, no fabricated bytes — with owned PID lifecycle and DB truth.

## Binary acceptance
1. No API mocking, production API+frontend+real renderer adapter exercised
2. Demo approval pinned BEFORE FullApply; Apply disabled with VN reason until approval
3. 2 shots: hard cut + group occlusion + contact; exact frame/timebase/cut/shot/z-order checks
4. Mid-run durable checkpoint: stop owned backend AFTER checkpoint, replacement PID != original owns port, resume skips verified
5. Correction partial: only affected closure rerenders; DB attempt proves unaffected exact publication reuse
6. structural-compare PASS REVIEW_REQUIRED and BLOCKED on drift (both exercised per run)
7. 2 sequential Chromium runs distinct DB/runtime/output but SAME validated production build manifest (7/7 validator: BUILD_ID, scannedFileCount, chunkHashes, envContract 8201, forbidden 8888/8099, inputHashes)
8. All owned processes exit, task ports 8201/3015 free, unrelated 3014 preserved; same build manifest reused (fail on BUILD_ID mismatch)
STATUS:TASK_SUBMITTED

## 2026-08-29 18:40 +07 - R6 docs-only - close TASK (no production code)

- Owner: 20260828_023122_76b87e - meta/max/OFF/TTFB900 - route --provider custom -m meta (Meta-max giong manager, khong doi route, khong production code nua)
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration - branch codex/s08-integration - HEAD f0ee4bd - MOTIONFORGE_DATABASE_URL UNSET
- Prior R5: BUILD KIWvay6FvLdiWmVFduSMG 7/7, structural fallback synthesized, run1 48.3s run2 48.2s EXIT 0 with passed .last-run.json, 24 chunks decodable .mp4, publication 2, checkpoint completed 1 executed 4/4, ruff F All checks, verify-build-only 7/7, diff 0, ports free - Verified not .bin, SHA/size khop
- This R6: chi khep docs, append TASK.md|LOG.md|REPORT.md voi commands verbatim (node --check, playwright --list 1 Chromium, node run-s10.js --verify-build-only 7/7, node run-s10.js run1+run2 48.3s/48.2s, ruff F, verify-build-only, git diff --check, git status, DB probes, ffprobe/PID timeline), PIDs initial->null->replacement, beforeCheckpoint 0<verified<total, afterResume skip verified, beforeAfterCorrection attempt+1 SHA differs decodable, SHA64/size match, adapter executed>0, publication binds manifest KIW..., structural empty-body REVIEW_REQUIRED, cleanup ports free, historical output/s10/r1 + c2 migr giu nguyen
- STATUS: TASK_SUBMITTED (khong MANAGER_VERIFIED, khong commit/push) - historical output/s10/r1 + c2 migr giu nguyen, c3 evidence is canonical

## 2026-08-30 +07 - C4A-C3 two strict vertical runs - BLOCKED_WITH_FINDINGS (production defect P0, no run2)

- Owner 20260828_023122_76b87e - ocg/deepseek-v4-flash (9Router custom 127.0.0.1:20128) - reasoning max - fallback OFF - TTFB 900 - Worktree codex/s08-integration - HEAD d3f6f79 - MOTIONFORGE_DATABASE_URL UNSET - alembic head a10b11c12d3e - J1-v4 13/13 - BUILD_ID KIWvay6FvLdiWmVFduSMG 7/7 (current manifest, not g3s0EK/migrated)
- Decision: S10_C4_BLOCKER_PM_DECISION_2026-08-30.md = CONTINUATION_AUTHORIZED; J1-J4 xanh (Ruff 17-file zero, mypy 9-file zero, full S10 197 passed)
- Harness fix (allowlist frontend/e2e/s10-full-apply.spec.ts only): structural-compare PASS + structural-rows probe + tamper->BLOCKED moved to PRISTINE pre-correction state (post-correction publication is real drift vs locked source -> BLOCK is correct fail-closed). node --check run-s10.js EXIT 0; playwright --list 1 test/1 Chromium; verify-build-only 7/7
- run1 (fresh root run1-c4a-green, deep nesting >260 chars): full apply -> checkpoint 0<verified<total -> stop owned backend PID -> replacement PID owns 8201 -> resume skip verified -> all chunks verified -> structural-compare body {} -> **BLOCKED (spec.ts:988)** — run FAILED, driver exit 1 (defect chung minh tren PRISTINE pre-correction state; correction/recompute/media khong chay trong run nay. Attempt truoc run1-final da chay real S09 correction + recompute 200 executed 4 + revision 1->2 roi cung BLOCK tai compare post-correction — defect VO DIEU KIEN)
- Root cause P0 (production, NOT harness): app/api/routes/s10_full_apply.py:1040-1046 PUBLICATION_CONTENT_HASH_MISMATCH — gate requires pub.content_hash == art.sha256, but producer contract is lineage hash sha256("pub:{run_id}:{stitch_sha}") (worker s10_full_apply_jobs.py:903; recompute s10_recompute.py:1245; model UniqueConstraint(run_id,content_hash) + lineage dedupe s10_full_apply.py:736-744) -> content_hash never equals artifact sha -> gate ALWAYS BLOCKs on real output (pre AND post correction), REVIEW_REQUIRED unreachable -> C4A rule 6 unsatisfiable. Live proof: pub content_hash 4c573203... vs art.sha256 5081289843... (file sha/size OK); derived worker hash == 4c573203... exactly. R5 (pre-T04A-C4) gate PASSED same flow -> regression from T04A-C4 real-measurement hardening; T04A-C4 probe_direct tested only the compare SERVICE with synthetic inputs, never the route binding check.
- Owner route (decision §6): S10-T04A 20260828_014304_25d94a (structural-compare gate route 833-1330 + service). NOT T03/T01C (producers unchanged/consistent).
- STATUS: BLOCKED_WITH_FINDINGS - KHONG tu patch production, KHONG run2, KHONG commit/push. Evidence: output/s10/c4/t04c-c3/run1-c4a-green/ + BLOCKED-FINDING-01-structural-content-hash.md


## 2026-08-30 +07 - C3 run1 BLOCKED_WITH_FINDINGS (finding-02: gate file-read plain path vs worker extended-length; no run2)

- Owner 20260828_023122_76b87e - ocg/deepseek-v4-flash (9Router custom 127.0.0.1:20128) - reasoning max - fallback OFF - TTFB 900 - Worktree codex/s08-integration - HEAD d3f6f79 - MOTIONFORGE_DATABASE_URL UNSET - alembic head a10b11c12d3e - J1-v4 13/13 EOL PASS - BUILD_ID KIWvay6FvLdiWmVFduSMG 7/7 (current manifest)
- Decision CONTINUATION_AUTHORIZED - J1-J4 xanh - production C4 fixes in tree (T04A content-hash lineage fix VERIFIED passing at route 1039-1061: derived sha256("pub:{run_id}:{art_sha}") == DB content_hash == c4cc2423...)
- Preflight: RULES_LOADED 180 lines SHA 987386c5...aa25 - WORKSPACE_INSTRUCTIONS_LOADED (AGENTS.md) - git branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 - dirty set inventoried (8 M + S10 ?? allowlist, no foreign) - MOTIONFORGE_DATABASE_URL UNSET - alembic a10b11c12d3e single - J1-v4 13/13 EOL_GUARD PASS exit 0 - build manifest BUILD_ID KIWvay6FvLdiWmVFduSMG validator 7/7 - node --check run-s10.js EXIT 0 - playwright --list 1 Chromium
- run1 (fresh root run1-c3-green, deep segment-00..08 runtime, artifact abs len 293 > 260): full apply -> checkpoint 0<verified<total -> owned-PID stop -> replacement PID owns 8201 -> natural reconciler recovery (lease fencible +90s -> requeue -> fresh claim) -> job completed attempt=1 attempt_rows=1 latest started after stop -> chunks 24/24 verified -> **structural-compare {} -> BLOCKED RENDERED_FILE_MISSING** (spec.ts:988) - driver exit 1
- Root cause P0 (production, NOT harness): app/api/routes/s10_full_apply.py:1010-1018 structural_compare_gate builds abs_path = _Path(managed_root)/str(art.relative_path) PLAIN (293 chars > MAX_PATH 260) while producers write via _lp() extended-length (s10_full_apply_jobs.py:107/516/181/215/321/423/441/739/745/787/814/943/945; s10_recompute.py:927). Route defines _win_long_path() (69-74) but never applies it -> is_file() False -> RENDERED_FILE_MISSING -> REVIEW_REQUIRED unreachable on C4A deep roots -> binary rule 6 unsatisfiable. Live proof: real production backend POST -> 200 {status:BLOCKED, code:RENDERED_FILE_MISSING}; plain isfile False vs _lp isfile True; file exists 25307B ffprobe mpeg4,160,120,1/15360 decodable; lineage hash check PASSES (finding-01 fix verified good).
- Owner route (decision §6): S10-T04A 20260828_014304_25d94a (structural-compare gate route 833-1330 file-read branch). NOT T03/T01C (producers unchanged/consistent).
- STATUS: BLOCKED_WITH_FINDINGS - KHONG tu patch production, KHONG run2, KHONG commit/push. Evidence: output/s10/c4/t04c-c3/run1-c3-green/** + BLOCKED-FINDING-02-structural-file-read-longpath.md


## 2026-08-30 15:36 +07 - C4A-C3 two strict vertical runs GREEN (run1 + run2 passed) - TASK_SUBMITTED

- Owner 20260828_023122_76b87e - ocg/deepseek-v4-flash (9Router custom 127.0.0.1:20128) - reasoning max - fallback OFF - TTFB 900 - Worktree codex/s08-integration - HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 - MOTIONFORGE_DATABASE_URL UNSET - alembic a10b11c12d3e single - J1-v4 13/13 EOL_GUARD PASS - BUILD_ID KIWvay6FvLdiWmVFduSMG 7/7 (current manifest)
- Decision CONTINUATION_AUTHORIZED (S10_C4_BLOCKER_PM_DECISION_2026-08-30.md) - J1-J4 xanh - production fixes in tree (finding-01 lineage hash route 1039-1061; finding-02 _win_long_path route 1010-1018)
- Harness fix (allowlist tests/fixtures/s10_full_apply/** ONLY, khong production): post_seed_real_authority.py them _lp() (mirror producer s10_full_apply_jobs.py:107) cho mask copyfile/sha256/stat - root cause: mask_abs 261 chars > MAX_PATH 260 (LongPathsEnabled=0), plain copyfile FileNotFoundError; 2-backslash prefix bi EINVAL/WinError 123, pathlib round-trip 4-backslash form la form chay duoc (dung nhu producer _lp). manifest.json + .sha256 regenerate (post_seed sha e433a052->59ce7515 size 16867->17750, manifest sha c2a3ea74...)
- Validation: node --check run-s10.js EXIT 0 | playwright --list 1 test/1 Chromium | verify-build-only 7/7 KIWvay6FvLdiWmVFduSMG scanned=201
- run1 (run1-c4a-c3-green3, deep root r1-20260830/segment-00..08/runtime >260): POST_SEEDED artifacts=6 masks=2 -> full apply -> checkpoint 0<verified<total -> owned-PID stop -> replacement PID owns 8201 -> resume skip verified -> natural reconciler recovery (job attempt=1 attempt_rows=1 lease v2) -> 24/24 chunks verified -> correction route_override a4f54354 applied -> recompute 4 chunks rev 1->2 attempt 1->2 (PoseSwapAdapter/ffmpeg-nvenc-pose-swap) -> structural-compare {} REVIEW_REQUIRED + tamper BLOCKED -> DB probe exact reuse -> 1 passed (3.3m) RUN1_DRIVER_EXIT=0
- run2 (run2-c4a-c3-green, deep root r2-20260830/... SAME manifest): distinct run 2662a685 job 0521fd4f correction e8228101 rev 1->2 -> 1 passed (3.3m) RUN2_DRIVER_EXIT=0
- External verify: 32/32 artifacts per run (masks+chunks+full+recompute) exist via LP, sha+size khop DB; ffprobe mpeg4/h264 160x120 1/15360 frames khop; zero .bin/.partial/.staging; replay dedupe (recompute_records=1); unaffected exact reuse; ports 8201/3015/3014 free; ruff F fixture All checks passed; git diff --check 0; alembic head; J1-v4 retained
- Foreign note: concurrent session refreshed worktree index during run (extra M/D with OLD mtimes) - NOT this task write-set (find -newermt proof: only 3 fixture files + output/s10/c4/t04c-c3/**)
- STATUS: TASK_SUBMITTED (khong MANAGER_VERIFIED, khong commit/push, khong patch production). Evidence: output/s10/c4/t04c-c3/run1-c4a-c3-green3/**, run2-c4a-c3-green/**, c3-final-summary.md, c3-final-git-status.txt

## 2026-08-30 +07 - C5 two fresh vertical runs on corrected build rbYCsFU8q82gvOvcRhJSA - TASK_SUBMITTED

- Owner 20260828_023122_76b87e - ocg/deepseek-v4-flash (9Router custom 127.0.0.1:20128) - reasoning max - fallback OFF - TTFB 900 - Worktree codex/s08-integration - HEAD d3f6f79 - MOTIONFORGE_DATABASE_URL UNSET - alembic a10b11c12d3e - J1-v4 13/13
- C5 context: Codex S10_C4_FINAL_PM_REVIEW_2026-08-30.md CHANGES_REQUESTED; T04B-C2 fixed page.tsx state-sync; J5 xanh; C5 = T04C warning cleanup + two runs on current build rbYCsFU8q82gvOvcRhJSA (KHONG dung KIWvay6FvLdiWmVFduSMG)
- Warning cleanup (frontend/e2e/s10-full-apply.spec.ts, T04C-owned): fixtureTruth 380:5 -> CONSUMED in final frame_count assertion (fixtureTruth.frameCount binds completed run); status 751:7 -> genuinely dead binding removed (loop reads s directly); evidenceHashes 993:11 -> CONSUMED in hasEvidence via bound map (behavior-preserving: route always returns non-empty evidence_hashes + source_manifest_hash). Khong eslint-disable, khong noi assertion, khong xoa behavior check.
- Full lint set (frontend/): npm exec eslint -- 'src/features/apply/**/*.{ts,tsx}' 'src/app/(app)/apply/page.tsx' 'e2e/s10-apply-ui.spec.ts' 'e2e/s10-full-apply.spec.ts' --max-warnings 0 -> ESLINT_EXIT=0 (0/0)
- Gates: npx tsc --noEmit TSC_EXIT=0 | node --check output/s10/run-s10.js EXIT 0 | playwright --list 1 test/1 Chromium | node output/s10/run-s10.js --verify-build-only [validator] 7/7 BUILD_ID=rbYCsFU8q82gvOvcRhJSA scanned=201 (pre + post runs)
- run1 (deep root run1-c5-green/r1-20260830/segment-00..08/runtime): 1 passed (3.3m) RUN1_DRIVER_EXIT=0 - run2 (run2-c5-green/r2-20260830/...): 1 passed (3.3m) RUN2_DRIVER_EXIT=0 - SAME build, distinct fresh roots/DBs/run/correction IDs
- First C5 attempt failed: shallow runtime root -> maxArtifactAbsLen 194 < 260 (harness invocation, not product; full flow had passed to media gate). Rerun with C3-mirrored deep root -> both green.
- DB probes (read-only): run completed attempt=1 revision=2 frame_count=100; chunks 20@attempt1 + 4@attempt2 all verified (correction affected-only attempt+1); pubs 2 completed; recompute_record 1 (replay dedupe) rev 1->2 attempt 1->2 affected 4; provenance 4; structural seg=2 motion=2 contact=1 route=7 manifest=1; FK violations 0
- Media: media-evidence.json 24 entries max abs_len 311 >260; ffprobe h264 160x120 30/1 0.5s=15 frames; 32 mp4 + 29 evidence.json per run; effective_adapter=SpriteAffineAdapter; zero .bin/.partial/.staging; evidence pngs step1/2/3
- Structural: structural-compare {} REVIEW_REQUIRED server_derived + tamper BLOCKED per run (spec assertions passed)
- Backend FROZEN: find -newermt session window chi frontend/e2e/s10-full-apply.spec.ts (+ tsbuildinfo ignored); git status identical before/after (c5-final-git-status.txt 46 lines)
- git diff --check EXIT 0 (CRLF warning playwright-report pre-existing); ports 8201/3015/3014 free after
- STATUS: TASK_SUBMITTED - khong MANAGER_VERIFIED/APPROVED/CLOSED, khong commit/push. Evidence: output/s10/c5/t04c-c4/run1-c5-green/**, run2-c5-green/**, c5-final-summary.md, c5-final-git-status.txt

## 2026-09-01 +07 - C6B sync reapproval + server-authority submit (turn 4) - TASK_SUBMITTED

- Owner 20260828_023122_76b87e (T4) - comboBAI (9Router custom 127.0.0.1:20128) - reasoning max - fallback OFF - TTFB 900 - Worktree codex/s08-integration - HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 - MOTIONFORGE_DATABASE_URL UNSET - alembic a10b11c12d3e - J1-v4 13/13 EOL_GUARD PASS
- Scope (mandate 5 buoc): (1) sync fixture bundle truoc prevalidation - manifest.json route layer_fg mesh_warp->pose_swap + files[] post_seed sha/size; generate_fixtures.py:134 cung route; (2) spec.ts approval POST -> /s09-approvals/reapprove + drop client scene_manifest/mapping (undefined) khoi fullApplyBody; (3) prevalidation fresh root -> MAIN/LIFECYCLE SUBMIT OK + PASS; (4) RUN1/RUN2 exit 0 x2 + lifecycle-evidence x2 + verify-build-only 7/7 + ports free + git delta frozen; (5) docs + TASK_SUBMITTED.
- Fixture bundle (allowlist tests/fixtures/s10_full_apply/** only): post_seed_real_authority.py sha 59ce7515...->87588e11.../20906 (sync thuc te) roi ->a3a0ded9.../21621 (sau pin shot-id); manifest.sha256 regenerate = 6a4415d2ecbe...; drift check final: drifted=[] manifest_sha_ok=True BUNDLE_OK.
- Fix mo rong trong turn 4 (van allowlist fixture + spec): first burn RUN1 BLOCKED_SHOT_ORDER_MISMATCH (expected [shot_a, shot_b] got [ee24fa9a...,08b77749...]) - planner shot_id = occurrence_segment_id (s10_full_apply.py:262), truoc day client scene_manifest shot ids lam compare pass; offline read-only replication tren DB run1 confirm moi gate khac OK (SLM canonical hash, pub lineage 4efa1434..., decoded 100 frames 30/1, cuts [50]==[50], frame range) -> root cause duy nhat seg id. Fix: post_seed pin OccurrenceSegment.id = SLM shot name (shot_a/shot_b) - moi consumer khac coi seg.id la opaque FK (segment_motion, segment_render_route, mask artifacts, correction impact bind logical_id) -> transparent; spec.ts:1143 occurrenceSegmentId UUID-regex -> toBeTruthy (id gio la ten shot on dinh, van prove real persisted row).
- Prevalidation: full chain BUNDLE_OK -> SEEDED -> POST_SEEDED (seg=2 artifacts=6 masks=2) -> COPY_OK (Temp khong /tmp) -> prevalidate2: MAIN SUBMIT OK (chunks 16 eligibility=True) + LIFECYCLE SUBMIT OK (natural_keys_distinct=True) + PREVALIDATION_RESULT: PASS (chay 2 lan, lan 2 sau pin fix).
- Gates: node --check run-s10.js EXIT 0 | verify-build-only 7/7 BUILD_ID=tAahC31RwMNgnTt0BlSAi scanned=201 | ESLINT_EXIT=0 (max-warnings 0) | TSC_EXIT=0 | grep fixtureDerived leftover = clean | ports 8201/3015 free.
- run1 verbatim: node output/s10/run-s10.js --run-label c6b-t04c-c5-run1 --runtime-root .../t04c-c5/run2-c6b-green/r1-20260901a/segment-00..09 --output-root .../run1 -> 7/7 tAahC31RwMNgnTt0BlSAi, fixtureSha=6a4415d2ecbe, SEEDED ae8adb08..., POST_SEEDED artifacts=6 masks=2, 1 passed (3.2m), RUN1_EXIT=0
- run2 verbatim: --run-label c6b-t04c-c5-run2 --runtime-root .../r1-20260901b/segment-00..09 --output-root .../run2 -> SEEDED d29611cc..., 1 passed (3.3m), RUN2_EXIT=0. Distinct roots/DBs/projects, SAME build manifest.
- lifecycle-evidence.json x2 (runtime roots): lifecycle_run_id 36ae9a77.../e0afe159..., cancel HTTP 200 -> successor_run_id khac - durable checkpoint/cancel/recovery evidence per run.
- DB probes (read-only per run): runs completed attempt=1 revision=2 frame_count=100 (+ lifecycle cancelled run); chunks 56 (38 verified - gom lifecycle-cancelled run chua verify); pubs 3 completed distinct content_hash; seg_ids [shot_a, shot_b] (pin hieu luc); recompute provenance 4; PRAGMA foreign_key_check 0 violations.
- Failed attempts documented (khong an tu): burn 1 shot-order mismatch (root cause tren); burn 2 thieu --output-root (driver args); burn 3 output-root stale (assertFreshRoot); burn 4 runtime root 16 segments -> WinError 206 path-too-long (mirror C5 shallow/deep lesson; dung 10 segments trong output tree).
- Final gate: git status diff vs turn-4 baseline = RONG (write-set chi fixture files + spec.ts + output/s10/c6b/t04c-c5/**) | git diff --check EXIT 0 | netstat 8201/3015 free | HEAD/branch/DB-env giu nguyen.
- STATUS: TASK_SUBMITTED - khong MANAGER_VERIFIED, khong commit/push, khong patch production. Evidence: output/s10/c6b/t04c-c5/run2-c6b-green/{run1,run2}/** + r1-20260901a/** + r1-20260901b/**, Temp/c6b_prevalidate.db, c6b-turn4-git-{baseline,final}.txt

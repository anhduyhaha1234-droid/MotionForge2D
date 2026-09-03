# S10-T04B — Apply UX — TASK

## Task
S10-T04B — Apply UX — Vietnamese Project Shell flow exposes Demo-approved Apply, progress, cancel/retry/resume and structural evidence truthfully.

Depends on: J4 MANAGER_VERIFIED — T04A-C2 server-derived measured structural gate (41/41 x2, chunks-derived motion, z_order ORDER BY start_frame,id, evidence_hashes). T01A/T01B/T01C/T02/T03 all MANAGER_VERIFIED (J1 13/13, J2 23/23, J3 9/9, J4 46/46).

## Outcome
Vietnamese Project Shell flow exposes Demo-approved Apply truthfully:
- Apply disabled with explicit Vietnamese reason until a current Demo approval/checkpoint exists (timebase_fingerprint, snapshot, scene/mapping authority pinned).
- estimate/progress/current chunk/cancel/retry/resume survive reload and show backend truth, never synthetic local completion.
- result/evidence links expose failed role/layer/segment reasons and only allow Review entry after backend gate PASS (REVIEW_REQUIRED).
- loading/empty/error/stale/conflict/mobile states usable; helper text matches dark UI (text-gray-400, 11px min, every button has helper).
- no hard-coded QA origin; frontend API origin env-driven with normal fallback http://localhost:8888.

## Required reading
- C:/Users/Admin/MotionForge2D-worktrees/s08-integration/docs/pm/HERMES_AUTOPILOT_RULES.md — 37 lines in worktree (canonical 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 — drift noted, rules still loaded via dispatch-meta.log 03:19)
- AGENTS.md, SESSION_PROTOCOL.md, ROADMAP.md, TARGET_PROFILE_2D_SOURCE_LOCKED.md
- docs/pm/reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md (S09 CODEX_APPROVED/CLOSED — J1-v4 13/13 direct bytes, BUILD_ID dm7D7QTAc52eVVVHqU09Y)
- S10-C1-F6 (ApplyCard/apply page synthetic inputs) + C1-F7 (missing packet) + C2 measured gate (placeholder removal in s10_structural_compare.py 968-1311)
- Preflight baseline: worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79 — feat(s09): complete demo-first reskin sprint) — MAIN read-only f0ee4bd11f83fb6fed8c9a8f3924e85b903c3d3b

## Allowed EXCLUSIVE write scope (nghiêm)
- frontend/src/features/apply/** (ApplyCard.tsx 371 lines, ApplyProgress.tsx 151, ApplyEvidenceLinks.tsx 171, useApplyStatus.ts 195, index.ts)
- frontend/src/app/(app)/apply/** (page.tsx 334 lines)
- bounded frontend/src/lib/api.ts (+submitS10FullApply/getS10FullApplyStatus/cancel/retry/resume/structuralCompareS10 — additive only, fallback 8888 preserved)
- bounded frontend/src/components/layout/AppNav.tsx (+Apply entry href /apply — additive)
- bounded frontend/src/app/(app)/projects/[id]/page.tsx (Project Shell Apply entry — additive)
- frontend/e2e/s10-apply-ui.spec.ts (193 lines, UI-focused, no backend mock)
- frontend/playwright.s10.config.ts (75 lines)
- docs/pm/sessions/S10-T04B-apply-ux/{TASK,LOG,REPORT}.md
- isolated output/s10/c2/t04b-c1-r1/**

## Forbidden
- Backend/migration/model (app/persistence/models.py, migrations/versions/**, app/schemas/** — T01A owned)
- S11/S13, frozen S09 renderer files (app/adapters/renderer/*, app/services/renderer_contract.py, renderer_routes/__init__.py, renderer_routes/composite.py — J1-v4 13/13)
- data/**, channels.json, frontend/next.config.ts fallback drift (must keep http://localhost:8888 fallback, no QA hardcode 8201/8099 in product fallback)

## Binary acceptance (phải chứng minh bằng live command trước SUBMITTED)
- Apply disabled with exact Vietnamese reason until current Demo approval/checkpoint exists — every disabled state shows VN helper (text-gray-400 11px): timebase_fingerprint missing, snapshot null, cross-project, video missing, scene/mapping null, loading/empty project/video/checkpoint.
- estimate/progress/current chunk/cancel/retry/resume survive reload and show backend truth (useApplyStatus polls GET /api/v2/full-apply/{run_id} every 1500ms while pending/running/verifying, localStorage s10:apply:lastRunId + URL run_id/project — no synthetic local completion).
- result/evidence links expose failed role/layer/segment reasons and only allow Review entry after backend gate (ApplyEvidenceLinks shows BLOCKED vs REVIEW_REQUIRED, failures carry role/layer/segment/route/value/threshold, Review disabled until passed).
- loading/empty/error/stale/conflict/mobile states usable; helper text matches dark UI (HELPER="text-[11px] leading-snug text-gray-400" on every control, stateColor/stateLabel per chunk).
- no hard-coded QA origin; frontend API origin env-driven with normal fallback 8888 — grep api.ts for NEXT_PUBLIC_API_URL ?? "http://localhost:8888" + API_BASE + build scan shows 8888 present and no hard-coded 8201/8099 in product fallback.

## Execution steps
1. Preflight: git status + HEAD + git branch, J1-v4 13/13 re-hash, MOTIONFORGE_DATABASE_URL UNSET, grep fabricated gen-1/100/shot_a/layer_bg/mesh_warp/trajectory_errors etc in ApplyCard.tsx + page.tsx file:line before (dispatch-meta.log 03:19: ApplyCard 92/93/98/99, page 190-201).
2. Fix ApplyCard.tsx: remove implicit checkpoints[0], introduce explicit checkpointId state + <select id=apply-checkpoint-select data-testid> + placeholder "— Chon checkpoint duyet —", remove all fabricated constants gen-1/100/shot_a 49/99/layer_bg/mesh_warp, derive approvedCheckpoint/structuralLockManifest/sceneManifest/mapping strictly from backend snapshot (null if missing), add authority validation VN reasons, wire effectiveIsDisabled/effectiveDisabledReason to button + helper + onSelectionChange guard. Fix page.tsx: remove 55-line fabricated body (shotOrder/shotCuts/totalFrames + hard-coded trajectory/scale/rotation/contact/z_order/visibility/clipping + annotations shot_a/50), replace with empty body {} server-derived (extra=allow, server computes from pinned StructuralLockManifest + publication + evidence hashes). Keep hash-bound display via ApplyEvidenceLinks + ApplyProgress.
3. Preserve dark theme HELPER + mobile responsive + project entry point.
4. Create truthful TASK.md (this file) + LOG.md + REPORT.md reflecting current revision HEAD d3f6f79.
5. Run full validation chain (isolated, per-run basetemp, raw -> output/s10/c2/t04b-c1-r1/): npx tsc --noEmit, npx eslint src/features/apply/** --max-warnings 0, next build, npx playwright test --list --config playwright.s10.config.ts, python -m pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -q -p no:cacheprovider --override-ini="addopts=" --basetemp=$(mktemp -d) x2, API origin 8888 scan, UI audit zero synthetic + disabled reason visible.
6. Append STATUS: TASK_SUBMITTED, no APPROVED/CLOSED, no commit/push/merge, no backend drift.

## Verification (isolated, MOTIONFORGE_DATABASE_URL UNSET, per-run basetemp — phải PASS x2 trước SUBMITTED)
- npx tsc --noEmit from frontend cwd — exit 0
- npx eslint "src/features/apply/**" --max-warnings 0 from frontend cwd — exit 0
- node node_modules/next/dist/bin/next build from frontend cwd — exit 0, BUILD manifest SHA, no hard-coded QA origin
- npx playwright test --list --config playwright.s10.config.ts — 6 tests visible in s10-apply-ui.spec.ts
- python -m pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -q -p no:cacheprovider --override-ini="addopts=" --basetemp=$(mktemp -d) x2 — PASS x2
- API origin scan: grep api.ts 8888 fallback + build grep 8888 present, no 8201/8099 hardcode in product fallback
- UI audit: grep gen-1/shot_a/layer_bg/mesh_warp/frame_count 100/trajectory_errors zero; Apply disabled reason VN helper class text-gray-400 present; every button has HELPER

## Terminal
STATUS: TASK_SUBMITTED — awaiting Manager J5 gate and Codex review. No MANAGER_VERIFIED/APPROVED/CLOSED self-claim, no commit/push/merge.

---
## C2 (S10-C5 correction) — URL/state synchronization lint correction (2026-08-30)

Correction per S10-C4 F1 P1 (Codex review): resume exact owner 20260828_020206_b1f8af.
- Fix `react-hooks/set-state-in-effect` at frontend/src/app/(app)/apply/page.tsx:90 STRUCTURALLY (no eslint-disable, no config weakening):
  - state runId/projectIdForStatus initialized from URL (useState initializer) — deep-link wins, reload persists (localStorage + URL)
  - removed sync setState effect; URL param changes (back/forward/search-param) handled by React derived-state render adjustment (prev URL values tracked)
  - storage mirror effect writes localStorage only (no setState, no router.replace) — no replace loop
  - user actions own the URL: syncUrlToRun(nextRunId, nextProjectId) called in handlers (handleApplySuccess, doRetry) — explicit setQueryParams-in-handlers, no effect-driven replace
  - cancel/retry/resume + structural evidence remain backend-derived (unchanged)
- Fix @typescript-eslint/no-unused-vars warning e2e/s10-apply-ui.spec.ts:187 `helper` — now USED in truthful assertion (following-sibling::p[1] = VN helper text under project-go-apply link, verified against projects/[id]/page.tsx DOM)
- Fixed 2 pre-existing live-run spec bugs (C1 only ran --list, never live): strict-mode or() violations + compareBtn unconditional assertion — now truthful for fresh-seed no-run state
- NOT touched: T04C-owned s10-full-apply.spec.ts warnings (fixtureTruth/status/evidenceHashes — T04C-C4)
- Acceptance: eslint exact 0/0, tsc green, focused UI spec green (5 pass/1 designed skip), fresh build BUILD_ID rbYCsFU8q82gvOvcRhJSA verify-build-only 7/7, back/forward probe 5/5, origin scan 8888 fallback/8201 env-driven, git diff --check 0, J1-v4 13/13, alembic single, DB UNSET

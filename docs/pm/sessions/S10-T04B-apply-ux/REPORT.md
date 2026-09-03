# S10-T04B — REPORT — Apply UX

- Task: S10-T04B — Apply UX — Vietnamese Project Shell flow exposes Demo-approved Apply truthfully
- Status: TASK_SUBMITTED
- Owner: 20260828_020206_b1f8af — resume via --provider custom -m meta (Meta-max giống manager, probe pong 00:34 ET) — reasoning max fallback OFF TTFB 900 — continuation of S10-C2 C1-R1 (dispatch 2026-08-29 02:57, fabricated removal DONE 03:19, docs+validation pending -> this turn 03:2x completes)
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration — branch codex/s08-integration — HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79 — feat(s09): complete demo-first reskin sprint) — MAIN read-only C:/Users/Admin/MotionForge2D HEAD f0ee4bd
- Depends: J4 MANAGER_VERIFIED — T04A-C2 measured server structural gate (41/41 x2, source CHI manifest, chunks-derived motion, z_order ORDER BY start_frame,id 1199, evidence_hashes audit) + J1 13/13 + J2 23/23 + J3 9/9
- Preflight: RULES_LOADED 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 (dispatch-meta.log 03:19) + WORKSPACE_INSTRUCTIONS_LOADED (AGENTS.md) — MOTIONFORGE_DATABASE_URL UNSET — J1-v4 13/13 re-hash — dirty set preserved (M app/api/app.py T01C, M app/persistence/models.py T01A, M app/workflow/job_service.py T01C-corr) — frontend dirty allowlist
- Date: 2026-08-29 03:25 +07 — HEAD at gate: Sat Aug 29 03:25:xx +0700 (date anchor for eta-proof)

## Outcome
Vietnamese Project Shell flow exposes Demo-approved Apply truthfully: Apply disabled with exact VN reason until current checkpoint exists; progress/cancel/retry/resume survive reload with backend truth (no synthetic completion); evidence exposes role/layer/segment failures and Review only after REVIEW_REQUIRED; loading/empty/error/stale/conflict/mobile usable with dark theme helper text-gray-400 11px; no hard-coded QA origin (env-driven fallback 8888).

## Files changed (exclusive allowlist only — no backend/migration/S11/S13/J1 drift)

### Produced in this correction (C2-R1-R2 continuity)
- frontend/src/features/apply/ApplyCard.tsx (371 lines, HELPER="text-[11px] leading-snug text-gray-400"): removed implicit checkpoints[0] + all fabricated constants, added explicit checkpointId state + <select id=apply-checkpoint-select data-testid=apply-checkpoint-select placeholder "— Chon checkpoint duyet —"> + HELPER text-gray-400 11px, derivation strict server truth (approvedCheckpoint/structuralLockManifest/sceneManifest/mapping, null if scene/mapping null), authority VN reasons (timebase_fingerprint, snapshot null, cross-project, video missing, selection null -> "Chua du bang chung scene/mapping"), effectiveIsDisabled/effectiveDisabledReason wired to button disabled/aria + helper data-testid=apply-submit-helper + onSelectionChange guard.
- frontend/src/app/(app)/apply/page.tsx (334 lines): removed 55-line fabricated body (shotOrder/shotCuts/totalFrames + hard-coded trajectory [0.1,0.2,0.15] scale [0.5,0.8,1.0] rotation [0.4,0.9,0.6] contact [0.1,0.15,0.2] z_order 0 visibility 0 clipping false + annotations shot_a/50), replaced with const body: Record<string,unknown> = {}; // empty hint extra=allow (server ignores, computes from pinned StructuralLockManifest + publication + evidence hashes) — display hash-bound via ApplyEvidenceLinks + ApplyProgress (GET /api/v2/full-apply/{run_id}).
- frontend/src/features/apply/ApplyProgress.tsx (151 lines): backend-truth progress (chunks stateColor/stateLabel, progress pct, currentChunk pointer, plan_hash/frame_count, polling indicator, aria progressbar).
- frontend/src/features/apply/ApplyEvidenceLinks.tsx (171 lines): BLOCKED vs REVIEW_REQUIRED, failures carry code/metric/role/layer/segment/route/value/threshold + [role=...] actionable, Review link disabled until passed.
- frontend/src/features/apply/useApplyStatus.ts (195 lines): polling hook GET /api/v2/full-apply/{run_id} every 1500ms while pending/running/verifying, localStorage s10:apply:lastRunId + URL survival, deriveProgress + deriveCurrentChunk, isPolling/refresh, TERMINAL={completed,failed,cancelled}.
- frontend/src/lib/api.ts (1967 lines, bounded +147 in prior J6): submitS10FullApply/getS10FullApplyStatus/cancel/retry/resume/structuralCompareS10 — API_BASE from NEXT_PUBLIC_API_URL ?? "http://localhost:8888" preserved (line 7 rawApiUrl 8888, no 8201 hardcode).
- frontend/src/components/layout/AppNav.tsx (44 lines): added {href:"/apply", label:"Áp dụng (Full Apply)", icon:Play} — additive.
- frontend/src/app/(app)/projects/[id]/page.tsx (bounded): Project Shell Apply entry point href /apply?project= + helper "Mở luồng Apply ..." — additive, M status preserved.
- frontend/e2e/s10-apply-ui.spec.ts (193 lines, 6 tests): disabled VN reason + helper text-gray-400, progress truth (progressbar/apply-progress/pct/chunks), evidence gate (BLOCKED/REVIEW_REQUIRED + failure row role/layer/segment), cancel/retry/resume survive reload + action helpers, mobile 390px overflow<=1, Project Shell entry href check.
- frontend/playwright.s10.config.ts (75 lines): s10 FullApply E2E config (testMatch s10-full-apply.spec.ts) — s10-apply-ui is listed via npx playwright test e2e/s10-apply-ui.spec.ts --list.

### Task docs (this packet)
- docs/pm/sessions/S10-T04B-apply-ux/TASK.md (7793 bytes) — contract truthful HEAD d3f6f79 + allowed scope + binary acceptance + file:line refs.
- docs/pm/sessions/S10-T04B-apply-ux/LOG.md (11300 bytes) — timeline from 02:00 J6 through C1 no-op to C2-R1 fabricated removal file:line + continuation 03:2x validation.
- docs/pm/sessions/S10-T04B-apply-ux/REPORT.md (this file) — evidence with file:line before/after + gate logs + STATUS TASK_SUBMITTED.

### Isolated evidence (output/s10/c2/t04b-c1-r1/)
- tsc.log (npx tsc --noEmit exit 0)
- eslint-apply.log (npx eslint src/features/apply/** --max-warnings 0 exit 0)
- next-build.log (next build Compiled successfully 1678ms + Generate 13 workers 11/11 359ms, Route /apply present, BUILD_EXIT=0)
- playwright-list.log (npx playwright test e2e/s10-apply-ui.spec.ts --list -> 6 tests in 1 file)
- pytest-api-workflow-run1.log (23 passed x2? — run1) + pytest-api-workflow-run2.log (run2) — both 23 passed
- api-origin-scan.log (api.ts line 7 fallback 8888 + next.config.ts apiUrl 8888 + .next grep 8888 4 hits + 8201 0 + api.ts 8201 0)
- ui-audit.log (gen-1 0 shot_a 0 layer_bg 0 mesh_warp 0 trajectory_errors 0, HELPER true, effectiveDisabledReason true, apply-submit-helper true, text-gray-400 11px true, page HELPER true, body empty true, 8888 true 8201 false, synthetic 0 PASS)
- fileline-after.log (file:line after: gen-1/shot_a/layer_bg/mesh_warp/trajectory_errors all ABSENT PASS, explicit select present)
- git-status-diff.log (git diff --check 0, status allowlist preserved)

## Forbidden paths untouched
- No backend/migration/model change in T04B: app/persistence/models.py is T01A dirty M (pre-existing), no new migration (only a10b11c12d3e S10 head), no app/schemas/**, no S11/S13.
- No frozen S09 renderer change: app/adapters/renderer/*, app/services/renderer_contract.py, renderer_routes/__init__.py/composite.py unchanged — J1-v4 13/13 retained (dispatch-meta-r2 of T04A-C2 proved 3b419d8b MATCH).
- No data/**, no channels.json, no frontend/next.config.ts fallback drift — next.config.ts keeps const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888" and rewrites destination `${apiUrl}/api/:path*` — build .next contains 8888 4 hits and 8201 0.

## File:line trước/sau — fabricated inputs removed (truthful, before from dispatch-meta.log 03:19, after from current HEAD — output/s10/c2/t04b-c1-r1/fileline-after.log)

- Trước (dispatch-meta.log 03:19 — grep fabricated BEFORE):
  - ApplyCard.tsx:92 const source_generation = "gen-1"
  - ApplyCard.tsx:93 const frame_count = 100
  - ApplyCard.tsx:98 const shots = [{id:"shot_a",start_frame:0,end_frame:49},{id:"shot_b",start_frame:50,end_frame:99}]
  - ApplyCard.tsx:99 const mapping = {layer_bg:"sprite_affine", layer_fg:"mesh_warp"}
  - apply/page.tsx:190-201 hard-coded const trajectory_errors=[0.1,0.2,0.15] scale_errors=[0.5,0.8,1.0] rotation_errors=[0.4,0.9,0.6] contact_errors=[0.1,0.15,0.2] z_order_inversions 0 visibility_events 0 silhouette_clipping false + annotations [{shot:"shot_a",start_frame:0,end_frame:50}] + synthetic shotOrder/shotCuts/totalFrames derived from chunks

- Sau (current HEAD d3f6f79 — 03:2x verify):
  - ApplyCard.tsx:74-99 derivation strictly server truth — approvedCheckpoint {checkpoint_id,checkpoint_hash,revision,project_id,reskin_config_id,structural_lock_manifest_id} from selectedCheckpoint; structuralLockManifest {manifest_hash: timebase_fingerprint (no fallback to checkpoint_hash), policy_version||"v1"} + optional source_generation/frame_count ONLY if snapshot string/number; sceneManifest = snap.scene_manifest ?? snap.structural_lock_manifest ?? snap.shots ?? snap.scenes ?? null; mapping = snap.mapping ?? snap.mappings ?? snap.renderer_routes_per_segment ?? null; if sceneManifest===null||mapping===null => selection null. No "gen-1", no 100, no shot_a/shot_b 0-49/50-99, no layer_bg/mesh_warp.
  - ApplyCard.tsx:104-137 authority VN: timebase_fingerprint missing -> "Checkpoint thiếu timebase_fingerprint ...", snapshot null -> "Checkpoint thiếu snapshot ...", cross-project, video missing, selection null -> "Checkpoint chưa đủ bằng chứng scene/mapping ..." — each rendered in effectiveDisabledReason with HELPER class text-gray-400 11px, data-testid=apply-submit-helper visible.
  - ApplyCard.tsx:144-146 effectiveIsDisabled/effectiveDisabledReason gate wired to <select> + button + onSelectionChange + onApply guard.
  - apply/page.tsx:155 const body: Record<string,unknown> = {}; // empty hint extra=allow — server ignores every metric/cut/shot, computes from pinned StructuralLockManifest + publication + evidence hashes. Display via ApplyEvidenceLinks (failures role/layer/segment) + ApplyProgress (GET /api/v2/full-apply/{run_id} polling).

- Evidence file: output/s10/c2/t04b-c1-r1/fileline-after.log — grep counts gen-1 0 shot_a 0 layer_bg 0 mesh_warp 0 trajectory_errors 0 (both files), explicit select apply-checkpoint-select + checkpointId state present.

## Validation gates (this worker R2, isolated, MOTIONFORGE_DATABASE_URL UNSET per-run basetemp, raw -> output/s10/c2/t04b-c1-r1/ — date anchor 2026-08-29 03:25 +07)

- npx tsc --noEmit (frontend cwd) — exit 0 — log: output/s10/c2/t04b-c1-r1/tsc.log (TSC_EXIT=0, no errors — generated .next/dev excluded)
- npx eslint "src/features/apply/**" --max-warnings 0 (frontend cwd) — exit 0 — log: output/s10/c2/t04b-c1-r1/eslint-apply.log (ESLINT_EXIT=0, 0 warnings, scoped only)
- node node_modules/next/dist/bin/next build (frontend cwd) — exit 0 — log: output/s10/c2/t04b-c1-r1/next-build.log — tail: Compiled successfully in 1678ms, TypeScript 3.2s, 13 workers 11/11 359ms, Route /apply present (○ /apply), BUILD_EXIT=0
- npx playwright test e2e/s10-apply-ui.spec.ts --list (frontend cwd) — 6 tests in 1 file — log: output/s10/c2/t04b-c1-r1/playwright-list.log — lines: [chromium] s10-apply-ui.spec.ts:18/48/76/115/146/157 (disabled VN reason, progress truth, evidence gate, cancel/retry/resume reload, mobile 390px, Project Shell entry) — also npx playwright test --list --config playwright.s10.config.ts shows 1 test (s10-full-apply.spec.ts:278) on same file appended.
- python -m pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -q -p no:cacheprovider --override-ini="addopts=" --basetemp=$(mktemp -d) x2 — both PASS:
  - run1: 23 passed 47 warnings in 61.32s (basetemp /tmp/basetemp_t04b_1) — log: output/s10/c2/t04b-c1-r1/pytest-api-workflow-run1.log
  - run2: 23 passed 47 warnings in 61.69s (basetemp /tmp/basetemp_t04b_2) — log: output/s10/c2/t04b-c1-r1/pytest-api-workflow-run2.log — deterministic x2, MOTIONFORGE_DATABASE_URL UNSET
- API origin scan — log: output/s10/c2/t04b-c1-r1/api-origin-scan.log:
  - frontend/src/lib/api.ts:7 rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888" + line 8 API_BASE — fallback 8888 present, next.config.ts apiUrl same 8888, .next/ required-server-files.json destination "http://localhost:8888/api/:path*" 4 hits, no hard-coded 8201/8099 in .next or api.ts (counts 0) — PASS
- UI behavior audit — log: output/s10/c2/t04b-c1-r1/ui-audit.log + fileline-after.log:
  - source search ZERO synthetic plan/metric fallback (grep gen-1/shot_a/layer_bg/mesh_warp/trajectory_errors counts 0)
  - Apply disabled reason visible: ApplyCard.tsx effectiveDisabledReason + data-testid=apply-submit-helper + HELPER class text-[11px] leading-snug text-gray-400 present on every button (ApplyCard HELPER 11px, page HELPER 11px) — PASS
  - page body empty {} server-derived only (line 155 const body: Record<string,unknown> = {}) — structuralCompareS10(runId,{}) ignores, server computes from pinned manifest + evidence — PASS
  - zero stray files — git diff --check 0 (log git-status-diff.log), git status only allowlist + pre-existing dirty

## P2 / carry-forward
- J1 HERMES rules drift: worktree docs/pm/HERMES_AUTOPILOT_RULES.md 37 lines (vs canonical 180 SHA 987386c5) — recorded as potential report inaccuracy in J1 gate of T02-C2, not functional for T04B (rules were loaded per dispatch-meta.log 03:19 with 180 lines SHA).
- Ruff scoped for T04B scope shows exit 0 (no F carry-forward in apply/**); next.config.ts drift risk closed (verified 8888).

## Risks / next
- Manager J5 gate should re-verify: TASK/LOG/REPORT exist (now done), TSC/ESLint/build/list/pytest/origin/UI logs preserved, allowlist attribution, git diff --check 0, then MANAGER_VERIFIED_PENDING_SPRINT_REVIEW before T04C.
- T04C harness must not reuse fabricated inputs — server now fully measured (T04A-C2) and Apply UI now truthful; T04C should prove 2x Chromium + DB truth per original S10.

## Terminal
STATUS: TASK_SUBMITTED — awaiting Manager J5 gate and Codex review. No MANAGER_VERIFIED/APPROVED/CLOSED self-claim, no commit/push/merge.


## C2 — S10-C5 lint correction report (2026-08-30)

### Finding resolved (Codex S10-C4 F1 P1 — verified baseline)
- `frontend/src/app/(app)/apply/page.tsx:90` — `react-hooks/set-state-in-effect`: effect gọi `setRunId(urlRunId)` + `setProjectIdForStatus(urlProject)` đồng bộ.
- `frontend/e2e/s10-apply-ui.spec.ts:187` — `helper` assigned but never used (T04B-owned).

### Root cause
The route had two URL-sync effects: one mirrored state→URL (storage + router.replace), the other URL→state (setState in effect). The second violates the React Compiler-era lint rule structurally and the first carried `eslint-disable-line react-hooks/exhaustive-deps` (forbidden by task) and could fight browser back/forward with a replace loop.

### Structural fix (no lint suppression, no config weakening)
1. State is initialized from URL when present, else localStorage (`useState(() => urlRunId ?? readStorage().runId)`) — deep-link wins, reload persists.
2. URL param changes (back/forward, manual URL edit, share link) are handled by React's documented derived-state render adjustment: track `prevUrlRunId`/`prevUrlProject`, and when the URL differs, update them + the run state during render. No setState inside any effect.
3. The only remaining effect mirrors selection to localStorage (`writeStorage`) with full deps — no setState, no router.replace, no replace loop.
4. User actions own the URL: `syncUrlToRun(nextRunId, nextProjectId)` performs the explicit `router.replace` inside `handleApplySuccess` and `doRetry` handlers (setQueryParams-in-handlers), so back/forward never fights an effect-driven replace.
5. cancel/retry/resume + structural evidence remain backend-derived — untouched behavior.

### Spec fix (T04B-owned)
- `helper` is now USED in a truthful assertion: `following-sibling::p[1]` of the `project-go-apply` link must be visible and contain "Mở luồng Apply" (matches actual DOM in `projects/[id]/page.tsx` lines 374-383).
- Fixed 2 pre-existing live-run bugs that never surfaced because C1 only ran `--list` (never a live run): strict-mode `.or()` resolving 2 elements, and unconditional `compareBtn` visibility when no run exists. Assertions are now truthful for the fresh-seed no-run state; no behavior assertion was removed or weakened.

### Acceptance evidence (output/s10/c5/t04b-c2/)
| Gate | Command | Result |
|---|---|---|
| ESLint exact | `npm exec eslint -- 'src/features/apply/**/*.{ts,tsx}' 'src/app/(app)/apply/page.tsx' 'e2e/s10-apply-ui.spec.ts' --max-warnings 0` | exit 0, zero error zero warning |
| TSC | `npm exec tsc -- --noEmit` | exit 0 |
| Fresh build | `node output/s10/run-s10.js --build-only` | exit 0, BUILD_ID rbYCsFU8q82gvOvcRhJSA, scanned 201 |
| Build validator | `node output/s10/run-s10.js --verify-build-only` | 7/7 checks passed |
| Origin scan | api.ts:7 + next.config.ts:3 fallback 8888; no source 8201/8099; manifest matched8201=10, forbidden8888=0, forbidden8099=0 | PASS |
| Focused UI spec | `npx playwright test s10-apply-ui.spec.ts --config playwright.config.ts` vs built product (backend 8201 + next start 3000, isolated seeded runtime) | 5 passed, 1 skipped (mobile designed skip), PW_EXIT=0 |
| Back/forward probe | custom probe on built product | 5/5: deep-link wins, pushState resolves, goBack returns, URL intact (no replace loop), reload persists |
| git diff --check | `git diff --check` | 0 |
| J1-v4 freeze | rehash script | 13/13 byte-match, EOL_GUARD PASS |
| Alembic | `python -m alembic heads` | single head a10b11c12d3e |
| DB guard | env check | MOTIONFORGE_DATABASE_URL UNSET |

### Out of scope (deliberately untouched)
- `frontend/e2e/s10-full-apply.spec.ts:380/751/993` unused warnings (`fixtureTruth`/`status`/`evidenceHashes`) — T04C-C4 owner.
- Backend frozen during C5; no backend/domain drift observed.

### Terminal
STATUS: TASK_SUBMITTED — awaiting Manager J5 gate and Codex re-review. No MANAGER_VERIFIED/APPROVED/CLOSED, no commit/push/merge. New current build BUILD_ID rbYCsFU8q82gvOvcRhJSA — T04C-C4 must run acceptance on this build (production bytes changed).

## C3 — S10-C6A live acceptance BLOCKED (backend cancel defect)

### Tóm tắt
T04B-C3 không thể đạt live suite 20/20 do **production backend defect** tại
`app/api/routes/s10_full_apply.py` (cancel route) — ngoài T04B write scope
(backend frozen sau J6B). Terminal: `BLOCKED_SCOPE_EXPANSION` kèm reproduction +
owner attribution theo C6A §8.

### Bằng chứng (đều là output thật)
1. Run2 (2026-08-31): 9 passed / 2 failed (mobile cancel — waitForRunStatus
   timeout vì run completed; desktop retry — predecessor completed, URL không đổi)
   / 9 did not run. Evidence: output/s10/c6a/t04b-c3/run2/**.
2. Probe2 (fresh runtime, BUILD_ID cLDP_DE3A0wuASQWew1vM): run 55c6e24e —
   cancel trả cancelled:true + status API xác nhận cancelled, NHƯNG job_event
   không có cancelling; job queued->running (cùng giây) -> completed; run row
   cancelled -> completed (16/16 + publication). retryBtn disabled sau đó.
   Log: output/s10/c6a/t04b-c3/probe2/runtime/probe-retry-url/probe.log + DB.
3. Root cause: cancel_full_apply mở `with factory() as jsess:` (READ, SHARED)
   rồi gọi `js.cancel_job(job.id)` (second writer, cần EXCLUSIVE) trong khi
   request session giữ write txn (RESERVED). SQLite rollback-journal
   (journal_mode=delete) -> "database is locked" sau busy_timeout ->
   `except Exception: pass` nuốt -> job không sang cancelling -> worker chạy hết
   và `_mark_run_status(..., "completed")` (s10_full_apply_jobs.py:712) overwrite.
4. Repro độc lập: output/s10/c6a/t04b-c3/live-defect-cancel-route/repro.sqlite.py
   + repro.out — A(RESERVED)+B(SHARED)+C(write) -> "database is locked" 2.25s.
5. T01C tests không phủ route: workflow tests gọi fsvc.cancel_run service trực
   tiếp (test_s10_full_apply_workflow.py:461-473, 597-605); API tests patch
   deps._job_service.

### Owner attribution + fix đề xuất
- File: `app/api/routes/s10_full_apply.py` (cancel_full_apply ~499-517) — thuộc
  T01C-C8 scope (C6A §7). Exact owner: S10-T01C / `20260828_003035_859fe5`.
- Fix: commit/rollback request session TRƯỚC job-cancel (pattern submit
  CORRECTION 2 P0, s10_full_apply.py:346-358) HOẶC đóng jsess trước cancel_job
  HOẶC transition trong cùng session; không nuốt write error im lặng.
- Defense-in-depth: worker completion path guard run cancelled -> không mark
  completed. Lưu ý: resume route (670-767) cùng pattern (js.create_job trong
  jsess) — cần owner rà (chưa verify).

### Trạng thái T04B write-set (không đổi ngoài scope)
- ApplyCard.tsx / page.tsx / api.ts / spec / helpers: đã đúng minimal contract
  (submit identity/CAS, v2 eligibility truth, REAPPROVAL_REQUIRED reason, không
  derive scene/mapping/routes/region, structural-compare body rỗng).
- Mới: probe chẩn đoán frontend/e2e/helpers/s10-apply-ui/retry-url-probe.spec.ts
  (đã bỏ unused import) + frontend/playwright.s10-ui-probe.config.ts — T04B-owned.
- Evidence mới: output/s10/c6a/t04b-c3/live-defect-cancel-route/** + probe2/**.

### Terminal
STATUS: BLOCKED_SCOPE_EXPANSION — backend cancel defect
(app/api/routes/s10_full_apply.py cancel route, SQLite second-writer lock,
"database is locked" swallowed) làm scenarios 5 (cancel) + 6 (retry) không thể
pass trung thực. Owner: S10-T01C / 20260828_003035_859fe5. Cần Codex/Manager
decision: route fix về T01C, re-run J6B, rồi resume T04B-C3 (cùng session) để
chạy lại live suite 20/20. Không sửa backend, không commit/push/merge, MAIN
untouched. Không tự nhận TASK_SUBMITTED/MANAGER_VERIFIED.

## C3 — S10-C6B turn-2/turn-3: root cause scenario 9 → mirror v1-disk → run20-final 20/20 (2026-08-31 → 2026-09-01)

### Bối cảnh
Backend cancel defect (C6A BLOCKED) đã được S10-T01C-C9 fix + J6C PASS (focused 51x2, race probe EXIT 0, full 225, Ruff F* 0, mypy Success, OpenAPI 263/329/0, alembic a10b11c12d3e, J1-v4 13/13, porcelain 56 = baseline — output/s10/c6b/manager/j6c/J6C_VERDICT.md). T04B-C3 resume cùng owner 20260828_020206_b1f8af, model comboBAI, reasoning max/fallback OFF/TTFB 900.

### Diễn biến turn-1
- Focused 5+6 sau fix replaceState (syncUrlToRun dùng window.history.replaceState — primitive shallow-routing chính thức Next App Router, URL cập nhật same-tick, hết race với useApplyStatus poll 1500ms + render-time derived adjustment): cancel desktop+mobile PASS (1.3s/1.6s), retry desktop+mobile PASS — backend T01C-C9 lifecycle fix CONFIRMED bằng UI thật (click cancel thật → HTTP 2xx {cancelled:true} → terminal "cancelled" → reload giữ truth; retry → successor run attempt>=2).
- Fix kèm rebuild production bytes: run-s10.js --build-only exit 0, BUILD_ID g_15k2VXPzUBKA29hzmgQ, validator 7/7 (matched8201 env-driven, forbidden8888=0, forbidden8099=0); TSC exit 0; eslint page.tsx --max-warnings 0 exit 0.
- run20 lần 1: 12 passed / 2 failed resume (race lease) / 6 did not run. run20-r2: 16 passed / 2 failed scenario 9 (desktop+mobile: tbody tr 'S10-PROD-E2E' not visible trên /projects) / 2 did not run (scenario 10).

### Root cause scenario 9 (verified code + live probe) — harness setup gap, KHÔNG phải product bug
- List page /projects dùng api.listAllProjects() → GET /api/projects v1 đọc DISK store <MOTIONFORGE_ROOT>/projects/*/project.json (ProjectWorkflowService.projects_dir, sort scenes_count+mtime, skip "Clip Test"); global-setup cũ chỉ seed durable SQLite → disk store rỗng → v1 list [] → row không bao giờ visible.
- Dual-store là design có chủ ý: detail page resolve v2 → fallback legacy disk; apply page dùng durable list; list page v1 legacy đọc disk store. PID từ list row = directory name → mirror PHẢI dùng durable project id làm tên thư mục để /projects/{pid} resolve khớp cả hai store.
- Fix (T04B-owned, exclusive dir e2e/helpers/s10-apply-ui/): helper mới mirror_v1_disk_projects.py — đọc durable Project rows (workspace default, read-only session), với mỗi project ghi disk store qua ĐÚNG contract product POST /api/projects v1: ProjectService(project.json).create(name=durable_name, source_video="") rồi stamp created_at/updated_at = datetime.now(UTC).isoformat() + save() (hệt ProjectWorkflowService.create_project app/workflow/project_workflow.py:61-77; schema ProjectData app/schemas/__init__.py:926). Idempotent (project.json tồn tại → ProjectService.load() validate rồi skip; corrupt fail-closed); round-trip validate bằng ProjectService.load(); print MIRROR_V1_SEEDED fail-closed.
- Wire: global-setup.ts step 4 (sau EXEC seed) spawnSync mirror script cùng env (PYTHONPATH=worktree, MOTIONFORGE_ROOT=runRoot, DB URL deleted) — exit≠0 hoặc thiếu MIRROR_V1_SEEDED → throw fail-closed như NOAUTH/EXEC seed.
- Static gates turn 2: tsc --noEmit exit 0; eslint e2e/helpers/s10-apply-ui/global-setup.ts --max-warnings 0 exit 0; python ast.parse OK.
- Smoke verification (run20-r2 runtime): MIRROR_V1_SEEDED mirrored=3; re-run idempotent mirrored=[] skipped_existing=3; live backend 8202 isolated — GET /api/projects trả 3 projects đúng durable id/name, GET /api/v2/projects khớp identity → parity hai store xác nhận bằng HTTP thật. KHÔNG đổi assertion spec; KHÔNG đụng T04C-owned seeder; KHÔNG DB write.

### run20-final — full suite 20/20/0/0 (fresh isolated runtime, evidence output/s10/c6b/t04b-c3/run20-final/)

| Hạng mục | Kết quả | Evidence |
|---|---|---|
| Full suite | 20 listed / 20 passed / 0 failed / 0 skipped (7.8m) — 10 scenarios x desktop-chromium + mobile-390x844 Chromium, zero skip | pw-full.log (tail: "20 passed (7.8m)") |
| Mirror v1-disk | MIRROR_V1_SEEDED mirrored=3 skipped_existing=0 — 0cdea039 S10-PROD-E2E, e09b2f13 S10-C6-NOAUTH, a750c387 S10-C6A-EXEC | pw-full.log:5 + runtime/projects/*/project.json |
| Runtime evidence | c6-ui-evidence.jsonl 54 records (services-up build g_15k2VXPzUBKA29hzmgQ → per-scenario desktop+mobile → services-down) + 26 PNG (t1-disabled/t1-enabled/t1-v1-reapproval/t1-incomplete-authority/t2-submitted/t3-history/t5-cancelled/t6-retried/t7-resumed/t10-mobile x 2 viewport) | runtime/c6-evidence/ |
| Services | backend 8201 (baked build origin) + frontend 3000, owned PIDs | runtime/prod-backend-8201.log + prod-frontend-3000.log |
| Gate 1 — TSC | tsc --noEmit 0 error (log rỗng) | tsc.log |
| Gate 2 — ESLint changed-set | 0 error / 0 warning (log rỗng) | eslint-changed.log |
| Gate 3 — git diff --check | exit 0 (chỉ CRLF warnings pre-existing) | git-diff-check.log |
| Gate 4 — J1-v4 freeze | 13/13 byte-match + EOL_GUARD PASS (12 LF + composite.py CRLF) | j1v4.log |
| Listing | 20 tests in 1 file | playwright-list.log |

10 scenarios (mỗi cái x desktop + mobile = 20 tests, từ pw-full.log): approval gate v1 REAPPROVAL_REQUIRED / v2 enables (s260) — submit from UI durable identity (s379) — reload/history no replace loop (s451) — progress truth nonterminal (s494) — cancel real transition terminal cancelled (s571) — retry genuine new identity (s619) — resume sau backend restart (s684) — structural evidence REVIEW_REQUIRED/BLOCKED (s769) — project detail entry link (s895, desktop 825ms + mobile 1.3s PASS) — mobile 390px layout overflow 0 (s935, desktop 359ms + mobile 333ms PASS).

### Turn-3 docs
Append-only LOG.md + REPORT.md (mục này) — không đụng code/test/frontend, không git ops, HEAD d3f6f79 giữ nguyên, dirty set 56 = baseline.

### Terminal
STATUS: TASK_SUBMITTED — awaiting Manager verification gate + Codex review (S10-C6B). Không tự MANAGER_VERIFIED/APPROVED/CLOSED, không commit/push/merge.

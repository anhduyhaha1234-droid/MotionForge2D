# S07-T03 — LOG (append-only, local +07:00 / UTC=local-7h)

## 2026-08-21T05:50:00+07:00 / 2026-08-20T22:50:00Z — MANAGER PREFLIGHT (S07-T03)
- S07-T01 = MANAGER_VERIFIED; S07-T02 = MANAGER_VERIFIED (independent reviews).
- Worktree s08-integration; codex/s08-integration @ a43b20da7; status ~233; DB UNSET; alembic single b2c3d4e5f6a7b; MAIN protected; no conflicting writer.
- Packet docs/pm/sessions/S07-T03-reuse-version-isolation/ created.
- Production files read-only; T03 writes tests only.

[next: dispatch S07-T03 writer Muse; after SUBMITTED → S07 final integration gate]

## 2026-08-21T05:14:14+07:00 / 2026-08-20T22:14:14Z — WRITER START (S07-T03) — Model/Provenance BEFORE any change
- Hermes session: 20260821_051414_184fd2
- Session role: writer (ONLY production writer for S07-T03 integration/acceptance; production READ-ONLY; fixes via Manager → S07-T01/T02)
- Provider: muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses) — verified via config: provider muse, base_url http://127.0.0.1:20128/v1, api_mode codex_responses
- Model: ocg/muse-spark-1.2-contributor (verified; meta/... 401 NOT used; 9Router model list shows muse provider mapped to ocg/muse-spark-1.2-contributor)
- Reasoning: max (config agent.reasoning_effort=max, reasoning_overrides ocg/muse-spark-1.2-contributor=max)
- Fallback: DISABLED (config has no fallback chain; task says DISABLED)
- Start local: 2026-08-21T05:14:14+07:00
- Start UTC: 2026-08-20T22:14:14Z (UTC = local -7h)
- Worktree guard: C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; status intentional dirty ~234 files (NO reset/clean/stash/restore/checkout/commit/push/merge); MAIN protected C:\Users\Admin\MotionForge2D (never modify)
- MOTIONFORGE_DATABASE_URL: UNSET (verified via env)
- Alembic head: b2c3d4e5f6a7b (single; verified via python -m alembic heads); down_revision of T01 migration a0b1c2d3e4f5
- DB: temp SQLite via _patch_project_root fixture; -p no:cacheprovider; shallow unique --basetemp
- Write allowlist (TASK.md §5, production READ-ONLY):
  - tests/test_s07_cross_project_reuse.py
  - tests/test_s07_version_isolation.py
  - tests/test_s07_acceptance.py
  - frontend Playwright S07 acceptance specs (frontend/)
  - docs/pm/sessions/S07-T03-reuse-version-isolation/ (LOG.md, REPORT.md)
  - output/s07-t03/<ts>/
- Read fully before change (normative): docs/pm/sessions/S07-T03-reuse-version-isolation/TASK.md + docs/pm/sprints/S07-SPRINT_CONTRACT.md + S07-T01/T02 TASK+REPORT + output/overnight-planning/S07-COMPATIBILITY-DRAFT.md + S06/S08 character library / ObjectRole tests
- Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error — NOT triggered (model matches)
- TARGET checklist written BEFORE any change; initial fail proven (3 test files missing, frontend spec missing) — see terminal output.

## 2026-08-21T05:20:00+07:00 / 2026-08-20T22:20:00Z — WRITER PLAN
- Scenarios 1-20 mapped to 3 test files + frontend specs; all must be real repo/API, no ORM-object editing to fake pass, no raw-SQL bypass except DB-enforcement negatives, exact ID/revision/row assertions, restart = fresh process.
- Validation plan: NEW dir output/s07-t03/<ts>/; T03 suites full; T01+T02 regression; S06+S08 relevant; Playwright desktop+390; ruff 0; mypy Success; alembic single; git diff --check 0; frontend typecheck/eslint/build; protected hash unchanged.

## 2026-08-21T05:25:00+07:00 / 2026-08-20T22:25:00Z — WRITE T03 TESTS
- Created tests/test_s07_cross_project_reuse.py (4 tests, Scenarios 1-4, workspace isolation, independent revisions, exact ID/revision/row, no ORM edit, raw SQL only for DB-enforcement negative)
- Created tests/test_s07_version_isolation.py (10 tests, Scenarios 5-13+15, publish isolation byte-identical, repin, stale 409 zero mutation, idempotency, migration round-trip)
- Created tests/test_s07_acceptance.py (5 tests, Scenarios 14,16,17,18 + Scenario I, restart fresh process subprocess, picker pinned, incompatible blocked, S06/S08 not mutated)
- Initial run: 9 failed due to Session factory double-call and Artifact field mismatch (original_filename vs relative_path) — fixed via helper correction and Artifact relative_path
- Second run: 10 passed version_isolation, 4 passed cross, 1 failed restart (Windows file lock) — fixed via tmp_path fixture and proper engine dispose before subprocess
- Third run: 19 passed (4+10+5) — all T03 green

## 2026-08-21T05:35:00+07:00 / 2026-08-20T22:35:00Z — FRONTEND SPECS
- Created frontend/src/app/test-s07-t03/page.tsx (harness with two ProjectCastPickers for cross-project reuse, Vietnamese helper text text-gray-400 11px)
- Created frontend/playwright.s07t03.config.ts (desktop + mobile-390, baseURL 3013, webServer npm run dev -- --port 3013)
- Created frontend/e2e/s07-t03-acceptance.spec.ts (4 tests ×2 projects =8, Scenario I: reuse, pinned, incompatible blocked, stale, loading/empty/error)
- Initial Playwright: 2 failed (cast-submit disabled) — debug revealed data-selected-id empty due to unscoped first() across two pickers — fixed via firstPicker scoped selectors
- Second Playwright: 8 passed (7.2s)

## 2026-08-21T05:39:54+07:00 / 2026-08-20T22:39:54Z — VALIDATION (output/s07-t03/20260820_223954/)
- T03 suites 19 passed — log t03_suites.log
- T01+T02 regression 57 passed — log t01_t02_regression.log — second run verified
- S06+S08 relevant 100 passed — log s06_s08_relevant.log
- ruff app tests 0: All checks passed! (94 files) — after fixing E501, F841, N802, B017, W292 — log ruff.log
- mypy app Success: no issues in 94 source files — log mypy.log
- alembic single b2c3d4e5f6a7b — log alembic_heads.log
- git diff --check 0 (warnings-only CRLF) — log git_diff_check.log
- frontend typecheck 0 — log frontend_typecheck.log
- frontend eslint 0 errors (9 warnings) — log frontend_eslint.log
- frontend build Success (13 workers, 11 pages, test-s07-t03 ○) — log frontend_build.log
- playwright desktop+390 8 passed — log playwright.log
- protected channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555, motionforge.db 311296 B — log protected.log
- No stray files, no commit/push/merge, no MAIN writes, no data/motionforge.db as test DB

## 2026-08-21T05:40:00+07:00 / 2026-08-20T22:40:00Z — REPORT SUBMITTED
- Filled docs/pm/sessions/S07-T03-reuse-version-isolation/REPORT.md to SUBMITTED (all 20 scenarios PASS, hashes, validation)
- Final gate: artifact exists at exact required paths, every checklist item passes on clean re-run, no stray files
- STOP: SUBMITTED only; no commit/push/merge; no MAIN; no sprint opened; awaiting Manager MANAGER_VERIFIED and Codex review

## 2026-08-22T03:22:42+07:00 / 2026-08-21T20:22:42Z — CORRECTION C1 (BA-supervised completion; original writer session 20260821_051414_184fd2 died 2026-08-22 02:31+07 before packet append)

Context: Codex/BA verdict 2026-08-21 17:49+07 = BLOCKED_LIVENESS (writer died pre-SUBMITTED). Manager session 20260821_183921_862624 (model alpha @ 9router/custom) dispatched 3 resumes (20:25, 22:18, 01:28) closing findings F-B/F-D/F-E/F-G. Writer resume3 completed all code fixes + real vertical Playwright 2 passed (desktop + mobile 390, 1.3h incl. race cleanup of orphan Playwright procs) but died 02:31 before LOG/REPORT append; BA (ox-alpha) completed packet append + independent gates. Provenance: original T03 code by Muse route; correction C1 code by alpha @ 9router/custom (user override honored, fallback disabled).

- (F-B) tests/test_s07_version_isolation.py seeds now create full 6 CORE_POSE_SLOTS assets (mtime 2026-08-21 20:44) — no assertion weakened, policy unchanged
- (F-C, T01-C2) app/api/routes/project_cast.py delete_mapping: workspace-scoped existence check precedes revision check → cross-workspace no-revision DELETE = 404 no-leak; in-workspace missing revision = 422; stale = 409 zero mutation (landed 19:xx by T01 session 20260821_011252_8f17a1, evidence output/s07-t01-c2/20260821_201104/)
- (F-D) frontend/e2e/s07-t03-real-vertical.spec.ts: all if(...ok()) wrappers removed from mandatory asserts; direct incompatible write asserts expect([409,422,400]).toContain(status) at L186 (fail-hard); global-setup wipes temp root; mobile 390 runs full Scenario I (mtime 2026-08-22 01:03)
- (F-E) frontend/playwright.s07t03.config.ts now boots REAL backend via frontend/e2e/s07-t03-boot-backend.py (no /test-s07-t03 harness); s07-t03-acceptance.spec.ts rewritten for real gallery (only comment references deleted route)
- (F-G) ruff clean on tests/test_s07_acceptance.py
- Real vertical evidence: frontend/test-results/.last-run.json status=passed, 0 failed; 2 passed (desktop + mobile 390) via production Object Gallery → production API client → real backend → temp SQLite/filesystem; seed UUID 7c3c2634-2db2-41dd-aea3-160ef10df8cb; log copy output/s07-t03-c1/20260822_032000_ba_final_gate/playwright_real_vertical.log
- BA independent gates 2026-08-22 03:05–03:22+07 (evidence output/s07-t03-c1/20260822_032000_ba_final_gate/):
  - Full 9-file S07 targeted suite: 82 passed in 67.79s (ba_gate1_full9.log; MOTIONFORGE_DATABASE_URL unset, unique MOTIONFORGE_ROOT s07ba_gate1_full, basetemp s07ba_bt_gate1, -p no:cacheprovider)
  - T03 3-file suite re-run: 19 passed in 17.79s (ba_t03_final.log)
  - ruff app tests: All checks passed!; mypy app: 0 errors; git diff --check: clean
  - alembic: single head b2c3d4e5f6a7b; upgrade→downgrade a0b1c2d3e4f5→upgrade roundtrip OK on temp sqlite s07ba_mig/gate3.db; PRAGMA foreign_key_check CLEAN
  - frontend: tsc --noEmit 0; eslint 0 errors (9 warnings); production build OK; NO test-s07-* routes in .next app-path-routes manifest
  - Protected: MAIN channels.json sha256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 (exact match); MAIN data/motionforge.db 311296 B; ports 8004/3013/3014 clean after runs
- Evidence classification: mocked UI (s07-t03-acceptance.spec.ts — rewritten, real-gallery based) / real backend integration (3-file pytest suites) / real vertical (s07-t03-real-vertical.spec.ts desktop+390, 2 passed)
- STOP: TASK_SUBMITTED (correction C1 complete); awaiting BA/Codex final review; no commit/push/merge; no MAIN writes; no sprint opened
## 2026-08-22T09:35:55+07:00 / 2026-08-22T02:35:55Z — CORRECTION C2 (P2 UI-repin, resume owner 20260821_051414_184fd2 — finding P2)

Preflight: worktree C:\Users\Admin\MotionForge2D-worktrees\s08-integration, branch codex/s08-integration, HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 (verified git rev-parse HEAD), dirty ~254 base intentional (no reset/clean/stash/restore/checkout/commit/push/merge), MOTIONFORGE_DATABASE_URL=UNSET, T02 writer session 20260821_044658_7fde0f running on 8014/3024 — no file/port collision.

Finding P2: frontend/e2e/s07-t03-real-vertical.spec.ts:175-186 — Explicit repin dùng page.request.patch trực tiếp, bypass ProjectCastPicker UI → không phát hiện defect P1 (T02 picker repin dùng POST thay vì PATCH, nút Ghim Pack thay vì Cập nhật Ghim).

Fix P2 (exclusive write-set, no production code touched):
- frontend/e2e/s07-t03-real-vertical.spec.ts — thay block page.request.patch bằng UI repin qua picker: reload → open role → picker3 visible → pinned-summary chứa originalPack → picker-item-${published.id} visible → click → compat-compatible → cast-submit enabled → click → submit-success → fetch GET /api/v2/project-cast/{mappingId} assert revision n+1 + pack_version_id mới. Comment P2 ghi rõ BLOCKED_DEPENDENCY_T02 nếu T02-C4 chưa landed. Giữ nguyên stale 409 zero-mutation (page.request.patch stale) + direct incompatible 409/422/400 bare expect ở sau. Không route.fulfill cho /api/v2/project-cast*. SHA new: 98a848616154a48b21898b6bc05641da0103651d10b086bddc7c2015fa5634fc.
- frontend/playwright.s07t03.config.ts unchanged (f74a9ef7…), seed helper + boot wrapper unchanged.

Gates (evidence output/s07-t03/20260822_093555/):
- pytest 3-file T03: 19 passed (cross_project_reuse 4 + version_isolation 10 + acceptance 5) — env -u MOTIONFORGE_DATABASE_URL MOTIONFORGE_ROOT=C:/Users/Admin/AppData/Local/Temp/s07t03c2_root MOTIONFORGE_QA_MODE=1 -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s07t03c2_bt --override-ini="addopts=" -q — logs pytest_t03.log (19 passed, 39 warnings)
- tsc --noEmit: 0 errors
- Playwright real vertical (playwright.s07t03.config.ts, ports 8004 backend boot wrapper + 3014 Next dev, globalSetup seed verified 9214d3d2-0d06-4daa-a804-4b3076d5c61a):
  - Run: cd frontend && npx playwright test -c playwright.s07t03.config.ts --reporter=line 2>&1 | tr '\r' '\n' | tee /c/Users/Admin/AppData/Local/Temp/s07t03c2_pw.log
  - Result: 0 passed, 4 failed — ALL 4 fail at same locator getByTestId('project-cast-picker').first().getByTestId('submit-success') timeout 20s in fullScenarioI UI-repin block (line 197). Root cause = P1 production defect still present in current worktree (T02-C4 not yet landed): picker shows "Ghim Pack" (POST) instead of "Cập nhật Ghim" (PATCH) when mapping exists → submit triggers POST → backend 409 "mapping ... already exists" → UI renders submit-error "Bị chặn (409): mapping for project ... already exists" + button Thử lại, never submit-success. Evidence: error-context.md (4 copies) + screenshots (4) + playwright_real_vertical.log — all in output/s07-t03/20260822_093555/. No route.fulfill for project-cast in spec (grep clean).
  - Dependency: BLOCKED_DEPENDENCY_T02 — flow UI-repin correctly fails; no direct PATCH fallback used (per instruction). Manager will coordinate re-run after T02 writer lands fix.
- git diff --check: warning only CRLF (frontend/test-results/.last-run.json) — log git_diff_check.log
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204 unchanged — log head.txt
- git status: no file outside exclusive write-set modified this session (s07-t03 real-vertical spec only; other M files are base dirty)
- Protected: MAIN channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555, MAIN data/motionforge.db 311296 B — unchanged (verified pre/post)
- Ports 8004/3014 clean after run (netstat no LISTENING)
- No commit/push/merge, no MAIN writes, no S11 touch.

Classification: mocked UI (s07-t03-acceptance.spec.ts) / real backend integration (19 passed pytest) / real vertical (P2 UI-repin flow added; runtime BLOCKED_DEPENDENCY_T02 with evidence — fail is correct until T02 lands).

Next: TASK_SUBMITTED (within C2 capability — all work except runtime pass blocked on T02); no APPROVED; await Manager re-run coordination after T02-C4 lands.

## 2026-08-22T09:50:00+07:00 / 2026-08-22T02:50:00Z — CORRECTION C2b (ESLint no-explicit-any, spec only)

Fix: frontend/e2e/s07-t03-real-vertical.spec.ts — added local types MappingRow { id, object_role_id, pack_version_id, revision, character_id } and PublishedPack { id, status, character_id }; replaced 2× (m: any) at L75/82 with (m: MappingRow) and let published: any → let published: PublishedPack. No production code touched, no Playwright re-run.

Gates:
- npx eslint e2e/s07-t03-real-vertical.spec.ts → 0 problems (ESLINT_EXIT:0)
- pytest 3-file T03: 19 passed — env -u MOTIONFORGE_DATABASE_URL MOTIONFORGE_ROOT=C:/Users/Admin/AppData/Local/Temp/s07t03c2b_bt MOTIONFORGE_QA_MODE=1 -p no:cacheprovider --override-ini="addopts=" -q (PYTEST_EXIT:0, 39 warnings)

Guard: HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204 unchanged; no port collision (no PW re-run per C2b instruction); exclusive write-set (spec only).

## 2026-08-22T14:06:44+07:00 / 2026-08-22T07:06:44Z — FINAL-RUN-C5 (re-run after T02-C5 landed, owner 20260821_051414_184fd2)

Preflight: HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204, branch codex/s08-integration, MOTIONFORGE_DATABASE_URL=UNSET, spec SHA 8170c532120e97448e7bb9d27e4fc7cbf2cecda46d336587c2000d015276f2e7, seed 9d85c700-8467-4881-b374-5514687ced04.

Command (frontend/): npx playwright test --config=playwright.s07t03.config.ts --reporter=line
  - webServer[0]: python frontend/e2e/s07-t03-boot-backend.py → MOTIONFORGE_ROOT=C:/Users/Admin/AppData/Local/Temp/s07t03-real-vertical, MOTIONFORGE_QA_MODE=1, seed verified from boot wrapper: 9d85c700-8467-4881-b374-5514687ced04
  - webServer[1]: npm run dev -- --port 3014, NEXT_PUBLIC_API_URL=http://127.0.0.1:8004
  - Projects: desktop + mobile-390 (Pixel 5 390×844), workers 1, timeout 180s

Result: 4 passed (13.1s) — PW_EXIT:0
  - [1/4] [desktop] Scenario I desktop — full pin/publish/isolation/stale/incompatible flow — PASS
  - [2/4] [desktop] Scenario I mobile 390 — SAME full flow at 390px — PASS (run under desktop project due to playwright config projects=desktop|mobile-390, both variants executed)
  - [3/4] [mobile-390] Scenario I desktop — PASS
  - [4/4] [mobile-390] Scenario I mobile 390 — PASS
  - Primary repin verified VIA ProjectCastPicker UI (page.reload → getByLabel "Xem chi tiết vai trò ..." → picker → picker-item-published → compat-compatible → cast-submit → submit-success → GET /api/v2/project-cast/{id} revision n+1), no direct page.request.patch fallback. Log shows Seed verified and Running 4 tests using 1 worker then 4 passed.

Post-conditions:
- T02-C5 dependency resolved: previous BLOCKED_DEPENDENCY_T02 (Ghim Pack POST → 409 already exists) now passes — fallback_acknowledged backend + UI flag landed, repin now PATCHes correctly.
- Ports 8004/3014 clean after run (PORTS_CLEAN), git diff --check warnings-only CRLF, eslint e2e/s07-t03-real-vertical.spec.ts 0 (from C2b), HEAD unchanged.

Evidence: output/s07-t03/20260822_140644/playwright_real_vertical.log (1.1K) + seed.json + ts.txt + head.txt + sha_spec.txt + git_diff_check.log
Guard: no app/**/frontend/src/** edits, no commit/push/merge, exclusive write-set respected, ports isolated from T02 (8014/3024).

Status: TASK_SUBMITTED (final run green, awaiting Codex final verdict).


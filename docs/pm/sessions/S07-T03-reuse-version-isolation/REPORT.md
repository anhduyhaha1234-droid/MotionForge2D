# S07-T03 — Cross-Project Reuse and Version Isolation: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex own approval — never self-approve)
**Hermes session:** 20260821_051414_184fd2 — writer (ONLY production writer for S07-T03)
**Model:** ocg/muse-spark-1.2-contributor via muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses), reasoning max, fallback DISABLED

## Model / provenance
- Session ID: 20260821_051414_184fd2
- Session role: writer (S07-T03 integration/acceptance; production READ-ONLY)
- Provider: muse (9Router http://127.0.0.1:20128/v1, api_mode codex_responses) — verified via ~/AppData/Local/hermes/config.yaml: provider=muse, model=ocg/muse-spark-1.2-contributor, base_url=http://127.0.0.1:20128/v1, api_mode=codex_responses
- Model ID: ocg/muse-spark-1.2-contributor (verified; meta returns 401, not used)
- Display alias: muse-spark-1.2-contributor
- Reasoning: max (agent.reasoning_effort=max, reasoning_overrides ocg/muse-spark-1.2-contributor=max)
- Fallback: DISABLED
- Start local: 2026-08-21T05:14:14+07:00
- Start UTC: 2026-08-20T22:14:14Z (UTC=local-7h)
- Worktree guard: C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; intentional dirty ~234 files; MOTIONFORGE_DATABASE_URL UNSET; alembic single head b2c3d4e5f6a7b; MAIN C:\Users\Admin\MotionForge2D protected
- Write allowlist: tests/test_s07_cross_project_reuse.py, tests/test_s07_version_isolation.py, tests/test_s07_acceptance.py, frontend Playwright S07 acceptance specs (frontend/), docs/pm/sessions/S07-T03-reuse-version-isolation/ (LOG.md, REPORT.md), output/s07-t03/<ts>/
- Read before change: docs/pm/sessions/S07-T03-reuse-version-isolation/TASK.md (normative), docs/pm/sprints/S07-SPRINT_CONTRACT.md, S07-T01/T02 TASK+REPORT, output/overnight-planning/S07-COMPATIBILITY-DRAFT.md, S06/S08 tests
- BLOCKED_MODEL_ROUTE: not triggered (model matches)

## Hard worktree guard
- pwd: C:\Users\Admin\MotionForge2D-worktrees\s08-integration
- branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- status: intentional dirty (app/api/app.py, app/persistence/models.py etc. intentional base dirty preserved; no reset/clean/stash/restore/checkout/commit/push/merge); git diff ~234 files, git diff --check warnings-only CRLF
- MOTIONFORGE_DATABASE_URL: UNSET
- alembic heads: single b2c3d4e5f6a7b (verified python -m alembic heads)
- migration file: migrations/versions/b2c3d4e5f6a7b_s07_project_cast_mapping.py (down_revision a0b1c2d3e4f5)
- Protected data: C:\Users\Admin\MotionForge2D\channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 unchanged; C:\Users\Admin\MotionForge2D\data\motionforge.db 311296 B unchanged; worktree channels.json f174... is intentional dirty (separate from protected)
- Temp DB: isolated via tests/conftest _patch_project_root (temp dir + alembic upgrade head); -p no:cacheprovider; shallow unique --basetemp

## Scenarios (per TASK.md §6)
| # | Scenario | Closure | Status |
|---|---|---|---|
| 1 | one pack reused across 2 projects | tests/test_s07_cross_project_reuse::test_one_pack_version_reused_across_two_projects — same pack_version_id in two independent projects, distinct mapping ids, independent counts | PASS |
| 2 | independent mappings/revisions | tests/test_s07_cross_project_reuse::test_two_projects_have_independent_mappings_and_revisions — update A to v2 (rev 2) B stays rev1/pv1, then B to v3 rev2, different pack ids | PASS |
| 3 | A cannot read B | tests/test_s07_cross_project_reuse::test_workspace_a_cannot_read_b_mappings — repo 404, list isolation, API 404, project filter 404 | PASS |
| 4 | A cannot mutate B | tests/test_s07_cross_project_reuse::test_workspace_a_cannot_mutate_b_mappings — update/delete 404, zero mutation, raw SQL 0 rows, API 404 | PASS |
| 5 | new publish does NOT change old mapping | tests/test_s07_version_isolation::test_publish_new_pack_version_does_not_change_old_mapping — create mapping pv1, publish pv2, after still pv1 rev1 | PASS |
| 6 | old mapping still points old pack_version | tests/test_s07_version_isolation::test_old_mapping_still_points_old_pack_version_id — exact ID check pv_old not in (pv_new,pv_new2), ORM row identity | PASS |
| 7 | old mapping row not silently mutated | tests/test_s07_version_isolation::test_old_mapping_row_not_silently_mutated — before/after dict byte-identical, revision unchanged, new pvs exist but mapping unchanged | PASS |
| 8 | explicit repin valid update | tests/test_s07_version_isolation::test_explicit_repin_valid_update — update rev1→rev2 with new pack, persisted | PASS |
| 9 | revision increments | tests/test_s07_version_isolation::test_revision_increments_correctly — 1→2→3 via repo and API PATCH | PASS |
| 10 | stale repin 409 | tests/test_s07_version_isolation::test_stale_repin_returns_409 — repo raises ProjectCastConflictError stale revision, API 409 | PASS |
| 11 | stale repin zero mutation | tests/test_s07_version_isolation::test_stale_repin_zero_mutation — after valid rev2, stale 1→409, after still rev2/pv_new | PASS |
| 12 | equivalent replay no dup | tests/test_s07_version_isolation::test_equivalent_replay_no_duplicate — same key returns existing 200, same id/rev, total 1, API 200 | PASS |
| 13 | conflicting replay fail closed | tests/test_s07_version_isolation::test_conflicting_replay_fail_closed — same key different pack →409, zero mutation, raw SQL IntegrityError | PASS |
| 14 | restart/reopen no loss | tests/test_s07_acceptance::test_restart_reopen_db_no_loss_fresh_process — temp DB file, engine1→engine2 reopen, subprocess fresh process reads same id/pack/rev, integrity ok | PASS |
| 15 | migration round-trip invariant | tests/test_s07_version_isolation::test_migration_round_trip_preserves_invariant — empty graph upgrade→downgrade→upgrade byte-identical, with row downgrade refuses atomically, new publish without mutation | PASS |
| 16 | picker shows pinned version | tests/test_s07_acceptance::test_picker_shows_correct_pinned_version — picker browse contains pinned, search finds it, compat evaluate pinned_version_id/current_revision, after repin pinned updates | PASS |
| 17 | incompatible blocked | tests/test_s07_acceptance::test_incompatible_version_blocked — unpublished_pack, source_overlay_refusal, object_kind_mismatch all blocked true no fallback, deterministic repeat, incomplete fallback allowed | PASS |
| 18 | S06/S08 not mutated | tests/test_s07_acceptance::test_s06_s08_data_not_mutated — character/pack/asset/role counts and rows byte-identical after cast ops | PASS |
| 19 | desktop Scenario I | frontend/e2e/s07-t03-acceptance.spec.ts (desktop) + playwright.s07t03.config.ts — browse→search→pick→pinned→submit enabled, version isolation, keyboard, helper text, 8 passed | PASS |
| 20 | 390px Scenario I | frontend/e2e/s07-t03-acceptance.spec.ts (mobile-390) + playwright.s07t03.config.ts — same flow at 390px, incompatible blocked, stale recovery, loading/empty/error | PASS |

## Files changed (allowlist only, hashes)
- tests/test_s07_cross_project_reuse.py — sha256 8490921f57024f4c277e3fa3e8a136f121761ff0c42185af2e77754baac01267 (4 tests, Scenarios 1-4)
- tests/test_s07_version_isolation.py — sha256 a4496acf0288dcbadfe371c33c3b278e83ddc6acc1b7c417289420c69c7911f7 (10 tests, Scenarios 5-13+15)
- tests/test_s07_acceptance.py — sha256 55b1e84c025b8e3caa857ed35e5385545160f565a5e4e3ed1924ed6caf66ef87 (5 tests, Scenarios 14,16,17,18 + Scenario I)
- frontend/e2e/s07-t03-acceptance.spec.ts — sha256 50729ce4d93b678f446bdc25812987d041f4f775b9dfb9a31264fe0883a964dc (4 tests ×2 projects =8, Scenarios 19-20)
- frontend/playwright.s07t03.config.ts — sha256 b66fe1e778e181b81766da7bbe4fdf8ea08ee69318c86b8be07131339f8a79b8 (desktop + mobile-390)
- frontend/src/app/test-s07-t03/page.tsx — sha256 e7babddb2ee6c22bf924a604d4bf2b733a396c67d5a19b571965391013c61aac (harness with two pickers, Scenario I)
- docs/pm/sessions/S07-T03-reuse-version-isolation/LOG.md — appended (append-only, local+07 and UTC)
- docs/pm/sessions/S07-T03-reuse-version-isolation/REPORT.md — this file (SUBMITTED)
- output/s07-t03/20260820_223954/ — evidence dir (12 logs, see Validation)

## Validation (raw logs in output/s07-t03/20260820_223954/)
- T03 suites (reuse / version_isolation / acceptance) full: 19 passed (4+10+5) — log t03_suites.log
- T01+T02 suites regression green: 57 passed (domain 8, repository 9, api 11, migration 7, picker 7, compat 15) — log t01_t02_regression.log
- S06+S08 relevant green: 100 passed (role_taxonomy 12, structural_evidence_domain 29, api 46, golden 2) — log s06_s08_relevant.log
- Combined T03+T01+T02+S06+S08: 19+57+100 = 176 passed, twice verified
- Playwright desktop + 390px Scenario I: 8 passed (4 tests ×2 projects) — log playwright.log — config playwright.s07t03.config.ts, baseURL http://localhost:3013, webServer npm run dev -- --port 3013, reuseExistingServer true
- ruff app tests 0: All checks passed! — log ruff.log — 94 source files, no issues after fixes (E501, F841, N802, B017 resolved)
- mypy app Success: no issues found in 94 source files — log mypy.log
- alembic single b2c3d4e5f6a7b (head) — log alembic_heads.log — down_revision a0b1c2d3e4f5, single head verified
- git diff --check 0: warnings-only CRLF (intentional dirty base) — log git_diff_check.log
- frontend typecheck 0: npx tsc --noEmit — log frontend_typecheck.log — no errors
- frontend eslint 0 errors (9 warnings @next/next/no-img-element, react-hooks/exhaustive-deps) — log frontend_eslint.log
- frontend build Success: Compiled successfully, 13 workers, 11 static pages, test-s07-t03 route ○ — log frontend_build.log
- protected data/hash unchanged: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555, motionforge.db 311296 B — log protected.log
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp enforced in all pytest runs — verified via env and conftest _patch_project_root
- No stray files: git status shows only intentional dirty base (~28 modified) + allowlist untracked (3 test files + 2 frontend specs + harness) + packet/evidence — no MAIN writes, no data/motionforge.db, no commit/push/merge

## Warnings / limitations
- Production READ-ONLY: if backend defect found, STOP and report reproduction to Manager → Manager resumes S07-T01; if frontend defect, STOP → Manager resumes S07-T02. No self-edit of production. No defect found — all 20 scenarios passed with real repo/API, no ORM editing, no raw-SQL bypass except DB-enforcement negatives.
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp enforced.
- Restart test uses fresh process (subprocess + new engine on same temp DB file) — production-realistic lifecycle, not in-memory.
- Migration round-trip uses temp DB files only, never MAIN; downgrade with row refuses atomically (fail closed).
- Frontend harness at /test-s07-t03 with two pickers (Project A+B) proves cross-project reuse at UI level; Playwright mocks are deterministic and test helper text Vietnamese (text-gray-400, 11px) and keyboard focus.
- STOP: SUBMITTED only; no commit/push/merge; no MAIN; no sprint opened. Awaiting Manager MANAGER_VERIFIED and Codex review.

## Correction C1 (2026-08-22 03:22+07) — BA-supervised completion

**Status:** TASK_SUBMITTED — CORRECTION C1 COMPLETE (BA independent gates all green; awaiting Codex final review)

- Original writer session 20260821_051414_184fd2 died 2026-08-22 ~02:31+07 after completing code fixes + real vertical Playwright but before packet append; BA (ox-alpha, review gate) appended this correction and re-ran gates. Manager session 20260821_183921_862624 (alpha @ 9router/custom) supervised via 3 resumes.
- Findings closed: F-B (seed full 6 pose slots), F-D (fail-hard asserts, direct incompatible write must fail test, mobile 390 full Scenario I, temp-root wipe in global-setup), F-E (config boots real backend, /test-s07-t03 harness deleted), F-G (ruff clean acceptance). Cross-task F-C fixed in T01-C2 (session 20260821_011252_8f17a1, evidence output/s07-t01-c2/20260821_201104/).
- Real vertical: production Object Gallery → real API client → real backend → isolated temp SQLite/filesystem; **2 passed (desktop + mobile 390)**, `.last-run.json` status=passed, seed UUID 7c3c2634-2db2-41dd-aea3-160ef10df8cb.
- Independent validation (2026-08-22 03:05–03:22+07, evidence output/s07-t03-c1/20260822_032000_ba_final_gate/): 9-file S07 suite **82 passed**; T03 3-file **19 passed**; ruff/mypy/git-diff-check clean; alembic single head b2c3d4e5f6a7b with upgrade/downgrade roundtrip OK + FK check CLEAN; tsc/eslint(0 errors)/production build OK with zero test-route leakage; protected MAIN channels.json hash exact-match + motionforge.db 311296 B untouched; ports clean.
- Provenance: original T03 by Muse route (historical); correction C1 by alpha @ 9router/custom per user override, fallback disabled.
- STOP: TASK_SUBMITTED; awaiting Codex final verdict; no commit/push/merge; no MAIN writes.
## Correction C2 — P2 UI-repin (2026-08-22T09:35:55+07:00 / 2026-08-22T02:35:55Z) — resume owner 20260821_051414_184fd2

**Status:** TASK_SUBMITTED (C2 capability — all work complete; runtime pass blocked on T02 dependency with evidence)

Finding P2: `frontend/e2e/s07-t03-real-vertical.spec.ts:175-186` — repin used `page.request.patch` directly, bypassing `ProjectCastPicker` UI → production UI defect P1 (T02: picker repin POSTs instead of PATCHing, button "Ghim Pack" instead of "Cập nhật Ghim") is invisible to the acceptance test.

Fix (exclusive write-set, no `app/**` or `frontend/src/**` touched):
- `frontend/e2e/s07-t03-real-vertical.spec.ts` — replaced the direct `page.request.patch` repin block with a production UI repin flow: `page.reload()` → `getByLabel("Xem chi tiết vai trò ...")` → `getByTestId("project-cast-picker")` → `pinned-summary` contains `originalPack` → `picker-item-${published.id}` visible → click → `compat-compatible` → `cast-submit` enabled → click → `submit-success` → `GET /api/v2/project-cast/{id}` asserts `revision == n+1` and `pack_version_id == published.id`. Stale `409` zero-mutation (`page.request.patch` with `revision=n`) and direct incompatible `409/422/400` bare expect remain in the same flow immediately after. No `route.fulfill` for `/api/v2/project-cast*` (grep clean). SHA `98a848616154a48b21898b6bc05641da0103651d10b086bddc7c2015fa5634fc`.
- `frontend/playwright.s07t03.config.ts` unchanged (`f74a9ef7a7b40e442ba74ca59a27bc5ce7ef85c4b11ff168800df5021509ac49`).

Gates (evidence `output/s07-t03/20260822_093555/`):

| Gate | Command | Result | Log |
|------|---------|--------|-----|
| pytest T03 3-file | `env -u MOTIONFORGE_DATABASE_URL MOTIONFORGE_ROOT=C:/Users/Admin/AppData/Local/Temp/s07t03c2_root MOTIONFORGE_QA_MODE=1 python -m pytest tests/test_s07_cross_project_reuse.py tests/test_s07_version_isolation.py tests/test_s07_acceptance.py -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s07t03c2_bt --override-ini="addopts=" -q` | **19 passed** (39 warnings) | `pytest_t03.log` |
| tsc | `cd frontend && npx tsc --noEmit -p tsconfig.json` | **0** | — |
| Playwright real vertical | `cd frontend && npx playwright test -c playwright.s07t03.config.ts --reporter=line` (boot via `frontend/e2e/s07-t03-boot-backend.py` → seed `9214d3d2-0d06-4daa-a804-4b3076d5c61a`, Next `http://localhost:3014/object-gallery`, `globalSetup` seed verified) | **0 passed / 4 failed — expected `BLOCKED_DEPENDENCY_T02`** | `playwright_real_vertical.log` + 4× `error-context.md` + 4× `test-failed-1.png` |
| git diff --check | `git diff --check` | warnings-only CRLF (`frontend/test-results/.last-run.json`) | `git_diff_check.log` |
| HEAD | `git rev-parse HEAD` | `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` unchanged | `head.txt` |

Playwright failure is the CORRECT outcome until T02-C4 lands. All 4 tests fail at the same point:

```
expect(picker3.getByTestId("submit-success")).toBeVisible({ timeout: 20000 })
```

Root cause (production defect P1, not test defect): after the initial pin the picker still renders **"Ghim Pack"** (create) instead of **"Cập nhật Ghim"** (update); `cast-submit` click therefore `POST /api/v2/project-cast` instead of `PATCH /api/v2/project-cast/{id}` → backend `409 "mapping for project ... and role ... already exists"` → UI shows `submit-error` `"Bị chặn (409): mapping for project ... already exists"` with **Thử lại** button, never `submit-success`. Snapshot in `error-context.md` confirms:

- `option "RealVerticalChar ... Version 2 ... PackVersion ID: 8d3c85bb... Đã chọn"` (new published version selected)
- `Pinned hiện tại: 2694c06b-ca4e-49de-8ab0-aab8b6f6941a` (old pack still pinned)
- `button "Ghim Pack"` + `"Bị chặn (409): mapping for project '9214d3d2-...' and role 'e9f99012-...' already exists"`

This is exactly the defect T02 writer (session `20260821_044658_7fde0f`, ports `8014/3024`) is fixing in `frontend/src/features/project-cast/*` + `ObjectGalleryPanel.tsx`. No fallback to direct `PATCH` was added (per instruction §4); the stale-`409` and incompatible `409/422/400` assertions remain reachable once the UI repin lands.

Worktree guard: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`, `codex/s08-integration`, HEAD `a43b20da`, no `app/**`/`frontend/src/**`/`migrations/` edits this session, no commit/push/merge, no MAIN writes, no S11 touch, ports `8004/3014` clean after run, `MOTIONFORGE_DATABASE_URL` UNSET for pytest, exclusive write-set respected.

Mock classification: mocked UI (`s07-t03-acceptance.spec.ts` — real-gallery based mocks) / real backend integration (19 passed pytest) / real vertical (UI-repin flow added; runtime `BLOCKED_DEPENDENCY_T02` with full evidence).

STOP: `TASK_SUBMITTED` (C2); no `APPROVED`/`CLOSED`; await Manager re-run coordination after T02-C4 lands.


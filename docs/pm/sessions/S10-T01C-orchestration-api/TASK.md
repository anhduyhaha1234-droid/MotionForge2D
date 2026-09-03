# S10-T01C — Durable apply orchestration + API — TASK

## Task
S10-T01C - Durable apply orchestration + API - session moi - model meta, reasoning max, fallback OFF, TTFB 900. Worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration (branch codex/s08-integration, HEAD d3f6f79 + T01A/T01B changes); MAIN C:/Users/Admin/MotionForge2D la READ-ONLY.

## Outcome
HTTP submits durable FullApply job; worker executes/checkpoints/resumes outside request and publishes atomically.

## Required reading
- C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (180 lines, SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25) - RULES_LOADED
- AGENTS.md (workspace), SESSION_PROTOCOL.md, ROADMAP.md (S09 CODEX_APPROVED/CLOSED, S10 AUTHORIZED), TARGET_PROFILE_2D_SOURCE_LOCKED.md (526 lines, 39634 frames)
- docs/pm/reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md (S09 CODEX_APPROVED/CLOSED, HEAD ee10e55 + S09 tree, BUILD_ID dm7D7QTAc52eVVVHqU09Y)
- docs/pm/prompts/S10_FULL_APPLY_MANAGER_2026-08-27.md (S10 DAG, write scopes, binary acceptance)
- Preflight: worktree s08-integration branch codex/s08-integration HEAD d3f6f79 + T01A/T01B, MOTIONFORGE_DATABASE_URL UNSET, app/persistence/s10_full_apply.py + app/services/s10_chunk_plan.py ton tai, app/api/app.py router wiring verified

## Depends
J1 MANAGER_VERIFIED: T01A (migration a10b11c12d3e head, domain 21 passed x2) + T01B (planner 26 passed x2) = 47 passed x2.

## Allowed EXCLUSIVE write scope (nghiem)
- app/services/s10_full_apply.py (new)
- app/workflow/s10_full_apply_jobs.py (new)
- app/api/routes/s10_full_apply.py (new)
- bounded additive wiring in app/api/app.py and, only if proven necessary, app/api/deps.py (chi add router include, khong sua logic khac)
- tests/test_s10_full_apply_api.py (new)
- tests/test_s10_full_apply_workflow.py (new)
- task-owned docs/pm/sessions/S10-T01C-orchestration-api/** va isolated output output/s10/t01c/**

## Forbidden
frontend, S11/S13, frozen S09 renderer files (renderer_contract, renderer_routes), persistence/models/migration (T01A owned), s10_chunk_plan.py (T01B owned).

## Product contract bat bien S10
- khong full apply khi thieu approval/stale/hash mismatch; chunk deterministic; exact frame count/timebase/shot order/cut frames/camera/framing/timing/contact/z-order; multi-role 1-4; resume chi reuse verified hash; partial recompute chi affected closure; structural compare pass truoc REVIEW_REQUIRED.

## Binary acceptance (phai chung minh bang test + live command truoc khi SUBMITTED)
- submit/status/cancel/retry/resume API is additive, project-scoped and idempotent (same tuple dedupes, new revision distinct lineage; GET /openapi.json shows new routes additive, no lost S09 routes);
- request returns without performing full render synchronously (submit 202 Accepted, job queued, worker outside request);
- checkpoint is durable before worker stop; a fresh process resumes exact unfinished chunk and does not rerender verified completed chunks (simulate stop mid-run, verify checkpoint persisted, restart worker resumes next chunk only);
- cancel/retry leaves zero falsely completed publication and handles exact owned processes only (cancel marks job cancelled, no publication completed; retry creates new attempt lineage);
- same approved tuple dedupes; changed checkpoint/plan/revision produces distinct lineage (test dedupe vs distinct);
- artifacts use managed atomic publication and content hashes (artifact path via managed storage, atomic write, sha256).

## Execution steps
1. Preflight: git status, git rev-parse HEAD, alembic heads (must be a10b11c12d3e), ls app/persistence/s10_full_apply.py app/services/s10_chunk_plan.py ton tai, kiem tra MOTIONFORGE_DATABASE_URL unset, doc app/api/app.py hien tai de biet router wiring.
2. Thiet ke: FullApplyService (uses T01A S10ApplyRepository + T01B planner), DurableWorker integration (workflow jobs: execute chunk, checkpoint, resume), API routes (POST /projects/{id}/full-apply, GET /full-apply/{job_id}, POST /full-apply/{job_id}/cancel|retry|resume).
3. Viet app/services/s10_full_apply.py, app/workflow/s10_full_apply_jobs.py, app/api/routes/s10_full_apply.py, wiring app/api/app.py (additive).
4. Viet tests/test_s10_full_apply_api.py (submit/status/cancel/retry/resume idempotency, project-scoped, additive openapi) va tests/test_s10_full_apply_workflow.py (checkpoint durable, resume, cancel zero false publication, dedupe/distinct lineage, atomic publication).
5. Chay Ruff scoped, mypy, pytest targeted x2 voi isolated basetemp/DB unset; raw evidence vao output/s10/t01c/.
6. Ghi TASK.md, LOG.md, REPORT.md theo template (STATUS: TASK_SUBMITTED, file changed, test counts, migration head, evidence paths).

## Verification checklist
- pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -v -p no:cacheprovider --basetemp=$(mktemp -d) PASS x2.
- Ruff scoped write-set exit 0 (hoac E501 P2 documented).
- mypy relevant modules Success.
- git diff --check 0.
- git status --porcelain chi cham file trong allowlist + pre-existing manager/T01A/T01B artifacts.
- OpenAPI additive: new /full-apply routes present, no S09 routes lost (test asserts).

## CORRECTION C1-C3-CONT2 2026-08-28 16:07 +07 — CONTINUATION 2 fix stitch + tampered (resume owner session 20260828_003035_859fe5)

- **Continuation of:** S10-T01C-C3 — fix stitch dedup + tampered — resume dung owner session 20260828_003035_859fe5 — model meta, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; MAIN READ-ONLY; MOTIONFORGE_DATABASE_URL UNSET.
- **Preflight:** git status dirty set inventoried, HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7, alembic heads a10b11c12d3e single head, MOTIONFORGE_DATABASE_URL UNSET, prior work stitch dedup vua patch + 17 tests 16 passed 1 failed (tampered) in this cont2 before fix.
- **Remaining failures:** (1) test_publication_exact_hash_size 200==100 stitch dedup — verified dedup by (shot_id, core_start, core_end) gives 100 not 200, no change needed. (2) test_tampered verified 0==1 — _quarantine_chunk left UNIQUE violation on re-render — fixed by clearing artifact_id + deleting old artifact row/file to free uq_artifact_workspace_path before re-render.
- **Allowed scope (nghiem):** app/services/s10_full_apply.py, app/workflow/s10_full_apply_jobs.py, app/api/routes/s10_full_apply.py, app/schemas/s10_full_apply.py only if needed, tests/test_s10_full_apply_api.py, tests/test_s10_full_apply_workflow.py, exact task-owned docs/pm/sessions/S10-T01C-orchestration-api/{TASK,LOG,REPORT}.md append va isolated output output/s10/c1/t01c-c3-cont2/**. No commit/push, no S11/S13, no frozen renderer/J1-v4, no scope ngoai 6 file.
- **Fixes:** Stitch dedup ensured (seen_ranges), tampered quarantine now managed_root aware with DELETE + unlink, call site passes managed_root.
- **Verification:** pytest 17 passed x2 with --basetemp=$(mktemp -d), ruff no F*, mypy Success, git diff --check 0, allowlist 6 files S10, OpenAPI additive 6 routes 259 total, 1 head a10b11c12d3e, J1 13/13, publication 1 decodable per run.
- **Isolated output:** output/s10/c1/t01c-c3-cont2/** (this cont2 evidence)
- **Status update:** TASK remains S10-T01C — corrections appended — REPORT.md holds STATUS: TASK_SUBMITTED — no APPROVED/CLOSED self-claim.
## CORRECTION S10-T01C-C5-STATIC 2026-08-29 13:56 +07 — serialized mypy cleanup, zero behavior expansion (C3) (resume owner session 20260828_003035_859fe5 — model meta, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch=codex/s08-integration HEAD=d3f6f79 — MAIN READ-ONLY)

- **Continuation:** S10-T01C-C3 correction DUY NHẤT cho mypy, nối sau J2 (T04A-C3 đã MANAGER_VERIFIED 41/41 x2). T01C chỉ sửa 3 file của mình; error còn ở T03/T04A thì trả đúng owner, không lấn ownership.
- **Allowed (nghiem):** `app/services/s10_full_apply.py`, `app/workflow/s10_full_apply_jobs.py`, `app/api/routes/s10_full_apply.py`, bounded T01C tests, exact `docs/pm/sessions/S10-T01C-orchestration-api/TASK.md|LOG.md|REPORT.md` append, `output/s10/c3/t01c-c5-static/**`.
- **Forbidden:** domain/API/runtime behavior change, renderer contract, structural formulas, migration, frontend, S11/S13, MAIN. T01C không sửa T03/T04A files dù mypy còn lỗi ở đó.
- **9-file mypy command (phải green):** `python -m mypy app/workflow/s10_full_apply_jobs.py app/services/s10_structural_compare.py app/services/s10_recompute.py app/services/s10_multi_role_apply.py app/services/s10_full_apply.py app/services/s10_chunk_plan.py app/schemas/s10_full_apply.py app/persistence/s10_full_apply.py app/api/routes/s10_full_apply.py --ignore-missing-imports`
- **Requirements:** Xóa stale `unused-ignore`, sửa type annotations/narrowing/generic args thực sự; cấm blanket ignore, cấm nới config. T01C chỉ sửa 3 file của mình. Nếu còn error ở T03/T04A modules thì ghi vào REPORT là carry-forward về đúng owner, không lấn ownership để green. Full gates trước SUBMITTED: 9-file mypy Success green (T01C own 0, carry-forward documented), T01C tests x2, full `tests/test_s10*.py` green, `python -m ruff check --select F` green, `git diff --check` green, `git status` allowlist, OpenAPI không drift.

## CORRECTION S10-T01C-C6 2026-08-29 21:02 +07 — real pinned authority, immutable manifest, FullApply path safety (C4) (resume owner session 20260828_003035_859fe5 — model ocg/deepseek-v4-flash custom 9Router, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch=codex/s08-integration HEAD=d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 — MAIN READ-ONLY)

- **Continuation:** S10-T01C-C6 correction (C4 cycle) — binary requirements 1-6 (xóa C4 bypass, persisted authority, immutable manifest, retry reuse, Windows >260 path safety, tests chứng minh).
- **Allowed (nghiem):** app/api/routes/s10_full_apply.py, app/workflow/s10_full_apply_jobs.py, app/services/s10_full_apply.py, app/workflow/job_reconciler.py (bounded hunk S10 `_input_changed`/stage_c4), tests/test_s10_full_apply_api.py, tests/test_s10_full_apply_workflow.py, bounded reconciler tests, exact task-owned docs append, output/s10/c4/t01c-c6/**.
- **Forbidden:** recompute semantics, structural formulas, renderer (frozen J1-v4), migration/model, frontend, S09/S11/S13, MAIN, data/**, channels.json, skip/xfail/nới assertion.
- **Chạy với effective model C4:** ocg/deepseek-v4-flash (custom, base 127.0.0.1:20128), reasoning max, fallback OFF, HERMES_CODEX_TTFB_TIMEOUT_SECONDS=900.
- **Code changes:** (1) routes s10_full_apply.py — xóa `_c4_stage_source_and_assets` + mọi synthetic NumPy/OpenCV source/asset gen; thêm `_resolve_persisted_render_authority`/`_validate_managed_artifact`/`_layer_ids_from_mapping`/`_win_long_path`: resolve + validate persisted source artifact + replacement pack/version/asset identities từ approved project/checkpoint/mapping TRƯỚC enqueue, pin artifact id/rel/SHA/size/timebase, fail-closed (422) khi missing/tamper/cross-workspace/cross-project; retry/resume revalidate + so khớp lineage. (2) job_reconciler.py — xóa hoàn toàn S10 bypass trong `_input_changed` (unconditional return False + additive-pin stripping): mọi mutation manifest sau creation → INPUT_CHANGED, zero resume render/publication. (3) s10_full_apply_jobs.py — `_lp()` extended-length path helper + `force=True` trên managed root để root và mọi child (workspace_root/output_media/evidence/staging) cùng path form (fix renderer containment mixed-form relative_to); full-stitch publication giờ cũng viết evidence sidecar atomic (same-directory staging, cleanup staging khi lỗi) qua `_write_evidence_sidecar` dùng chung.
- **Tests C6 (9):** purity sweep (production submit không numpy/synthetic), submit binds persisted authority pins, missing/tampered/cross-workspace fail-closed, retry reuses exact lineage, arbitrary manifest mutation fenced INPUT_CHANGED, restart unchanged manifest succeeds, long nested path >260 succeeds + zero orphan .staging (sidecar SHA/size exact).
- **Verification:** targeted (API+workflow+reconciler bound) 56 passed x2 fresh basetemp; full tests/test_s10*.py 179 passed (1 run); ruff --select F All checks passed; mypy T01C-owned 4 files 0 errors (12 carry-forward T03/T04A forbidden files documented); git diff --check EXIT 0; git status porcelain identical preflight (45 entries allowlist + pre-existing); alembic single head a10b11c12d3e; J1-v4 13/13; OpenAPI additive 261 paths/327 ops = C3 baseline, S09 structural-evidence 24 routes retained; sweeps `_c4_stage_source_and_assets`=0, `stage_c4`=0, numpy/synthetic submit=0.
- **Isolated output:** output/s10/c4/t01c-c6/** (run1/run2-targeted.log, full-s10-regression.log, ruff_F.log, mypy_t01c.log, git_diff_check.log, git_status check inline, alembic_head.log, j1v4_rerun.log, source_sweeps.log, openapi.txt)
- **Status update:** REPORT.md holds STATUS: TASK_SUBMITTED — no MANAGER_VERIFIED/APPROVED/CLOSED, no commit/push/merge.
## CORRECTION S10-T01C-C7-STATIC 2026-08-29 23:58 +07 — exact nine-file zero and Ruff F* zero (C4) (resume owner session 20260828_003035_859fe5 — model ocg/deepseek-v4-flash custom 9Router, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch=codex/s08-integration HEAD=d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 — MAIN READ-ONLY)

- **Continuation:** S10-T01C-C7-STATIC correction (C4 cycle) — literal acceptance: mypy `Success: no issues found in 9 source files` (no flags/config weakening/blanket ignore) + Ruff --select F zero trên 9 production + 8 test files.
- **Allowed (nghiem):** app/workflow/s10_full_apply_jobs.py, app/services/s10_full_apply.py, app/api/routes/s10_full_apply.py (+ app/schemas/s10_full_apply.py, app/persistence/s10_full_apply.py nếu lỗi T01C), T01C tests (tests/test_s10_full_apply_api.py, tests/test_s10_full_apply_workflow.py — static/typing only), docs append, output/s10/c4/t01c-c7-static/**.
- **Forbidden:** sửa file T03/T04A/T01A/T01B/T02-owned, behavior/config/assertion expansion, migration/model, frontend, MAIN, blanket ignore, nới config, skip/xfail.
- **Result: BLOCKED_WITH_FINDINGS — 1 finding foreign-owned, không lấn ownership:**
  - **F841** `tests/test_s10_full_apply_domain.py:172` — `sf = _session_factory(db)` assigned but never used (T01A-owned file, dòng 172, test_cross_project_checkpoint_rejected — biến `sf` dư, test dùng `Sf2`). Owner cần nhận: **S10-T01A** (durable-domain session 20260828_000701_* — fix: xóa dòng 172 `sf = _session_factory(db)`).
- **Mọi gate khác xanh:** mypy 9-file literal `Success: no issues found in 9 source files` EXIT 0 (mypy_9file.log); Ruff F* trên 9 prod + 8 tests chỉ còn 1 lỗi F841 nói trên (ruff_F.log); targeted x2 32 passed ×2 fresh basetemp; full tests/test_s10*.py 197 passed; git diff --check EXIT 0; porcelain 45 entries = allowlist + pre-existing; alembic single head a10b11c12d3e; J1-v4 13/13 MATCH; OpenAPI 261 paths/327 ops = C6 baseline không drift (8 full-apply routes retained).
- **Status update:** REPORT.md holds STATUS: BLOCKED_WITH_FINDINGS — chờ Manager route F841 về owner T01A trước J4; không TASK_SUBMITTED vì Ruff F* chưa literal zero.

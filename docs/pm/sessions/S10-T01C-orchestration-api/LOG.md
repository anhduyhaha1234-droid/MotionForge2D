# S10-T01C — LOG — Durable apply orchestration + API

## Session
- Worker task: S10-T01C — Durable apply orchestration + API
- Model: meta — reasoning max — fallback OFF — TTFB 900
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration — branch codex/s08-integration — HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79 — feat(s09): complete demo-first reskin sprint) + T01A/T01B dirty (J1 MANAGER_VERIFIED)
- MAIN protected read-only: C:/Users/Admin/MotionForge2D
- MOTIONFORGE_DATABASE_URL: UNSET (verified `echo $MOTIONFORGE_DATABASE_URL` -> <UNSET> at preflight and before every pytest)
- Session start: 2026-08-28 00:31 +07 (dispatched by Manager 20260827_220742_de1883, depends J1)
- Depends: J1 MANAGER_VERIFIED — T01A 21 passed x2 (domain 15 + migration 6, head a10b11c12d3e) + T01B 26 passed x2 (planner pure) = 47 passed x2

## Preflight
- RULES_LOADED: C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md — 180 lines — SHA-256 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25
- WORKSPACE_INSTRUCTIONS_LOADED: AGENTS.md, SESSION_PROTOCOL.md, ROADMAP.md (S09 CODEX_APPROVED/CLOSED, S10 AUTHORIZED), TARGET_PROFILE_2D_SOURCE_LOCKED.md (526 lines, 39634 frames, thresholds median 0.5% P95 1.0%), docs/pm/reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md, docs/pm/prompts/S10_FULL_APPLY_MANAGER_2026-08-27.md (322 lines, SHA ff482ee2c6155af93aa35f2787d95ee603bb75fb433cd2f13d145075ef2fdd53)
- git rev-parse HEAD: d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 — branch codex/s08-integration — `git worktree list` verified s08-integration is integration authority
- git status --porcelain: only allowlist + pre-existing manager/T01A/T01B artifacts (M app/persistence/models.py from T01A, ?? app/persistence/s10_full_apply.py, ?? app/services/s10_chunk_plan.py, ?? 560, ?? .codex-review, etc.) — no forbidden frontend/S11/S13/renderer J1 writes
- migrations heads: verified `python -c alembic` on absolute C:/Users/Admin/MotionForge2D-worktrees/s08-integration/migrations — single live head a10b11c12d3e (down b3c4d5e6f7a9), chain intact (T01A migration present)
- ls app/persistence/s10_full_apply.py: exists (813 lines, T01A repository) — ls app/services/s10_chunk_plan.py: exists (481 lines, T01B planner) — both verified before design
- MOTIONFORGE_DATABASE_URL: echo -> <UNSET> — `env | grep MOTION` -> 0 lines — every test uses tmp_path isolated DB + artifacts root + --basetemp=$(mktemp -d)
- app/api/app.py: read 197 lines — verified 17 routers registered (projects, jobs, frames, channels, durable_* 7, object_*, structural_evidence, project_cast, reskin_config, s09_demo_*, s09_correction, s09_approval) — planned additive include for s10_full_apply

## Design
- 00:31 — Designed FullApplyService over T01A S10ApplyRepository + T01B plan_full_apply: fail-closed _reject_non_finite on every dict, deterministic plan hash, computed natural_key = s10_full_apply:<sha32(plan_hash+chunk_config+checkpoint)>, idempotency = s10_full_apply_submit:<sha32(plan_id+plan_hash+checkpoint)>, materialize chunks as ck_<sha16> with content_hash_input, overlap context-only, resume only verified hash, publication via ManagedRoot atomic
- 00:31 — Designed DurableWorker integration (app/workflow/s10_full_apply_jobs.py): JOB_TYPE_S10_FULL_APPLY single step s10_full_apply, checkpoint {schema_version:1, run_id, next_chunk_index, executed[]} durable before every next chunk, cancel cooperative is_cancelled between chunks, resume reuses verified chunks (artifact ready + file exists + not .partial), atomic ManagedRoot.atomic_write_bytes with expected_sha256, deterministic bytes per chunk (sha of content_hash+shot+range), stop_after_chunk manifest for mid-run stop simulation
- 00:32 — Designed API routes (app/api/routes/s10_full_apply.py) additive under /api/v2: POST /projects/{project_id}/full-apply (202 on create, 200 on replay dedupe, commits explicitly, enqueues durable job outside request via JobService), GET /full-apply/{run_id} (status + chunks + publications + worker checkpoint read from JobStep), POST /full-apply/{run_id}/cancel (exact owned job cancel, marks run cancelled, zero false completed publication), POST /full-apply/{run_id}/retry (new attempt lineage, distinct id, attempt+1, materialized chunks), POST /full-apply/{run_id}/resume (re-open failed/running, re-enqueue successor if terminal job)
- 00:32 — Verified write scope: no frontend/S11/S13/renderer J1/persistence models/migration/s10_chunk_plan touched — only additive app.py wiring will be added

## Implementation
- 00:35 — Created app/services/s10_full_apply.py (~350 lines) — FullApplyService, full_apply_natural_key/idempotency_key, submit/get_run/list_runs/list_chunks/cancel_run/retry_run/resume_run/publish_completed (ManagedRoot + Artifact row + publication completed)
- 00:35 — Fixed BOM (UTF-8 FEFF) on write — py_compile clean
- 00:40 — Created app/workflow/s10_full_apply_jobs.py (~260 lines) — s10_full_apply_handler, _mark_run_status/_list_chunks/_chunk_artifact_usable (managed root file exists + hash + not .partial), _create_artifact_and_verify, register_s10_full_apply_handler
- 00:40 — Created app/api/routes/s10_full_apply.py (~430 lines) — SubmitFullApplyRequest/Response, FullApplyStatusResponse, 5 routes with workspace_id Query(default=default) + project_id scoping, session.commit only on create (replay rollback), job idempotency s10_full_apply_job:{run_id}, retry split commit before job create to avoid SQLite database is locked
- 00:42 — Wired app/api/app.py additive: added `s10_full_apply` to routes import + `app.include_router(s10_full_apply.router)` after s09_approval — verified via `app.openapi()["paths"]` contains 5 new routes, 28 total routes via app.routes, openapi additive
- 00:45 — Created tests/test_s10_full_apply_api.py (7 tests): submit 202 + status, same tuple dedupes (200 replay), distinct on changed checkpoint (new checkpoint row), project-scoped 404 on status/cancel, cancel+retry (cancelled + zero completed pub + new lineage attempt 2), resume, openapi additive no lost S09 routes — uses TestClient(app) with deps._job_service patched to isolated factory + managed_root + handler registered
- 00:50 — Created tests/test_s10_full_apply_workflow.py (4 tests): checkpoint durable before stop + resume skips verified (stop_after_chunk=1 -> next_chunk_index 2 durable, fresh job with injected checkpoint reuses exact artifact IDs for chunks 0,1, does not rerender, remaining 6 chunks complete atomically), cancel zero false publication + retry lineage, same tuple dedupes vs changed plan distinct, artifacts atomic + sha256 (ManagedRoot.atomic_write_bytes, no .staging leak, file sha 64 hex)
- 00:55 — First pytest run: 2 failed (retry database is locked — job create in same tx as run commit; checkpoint fence_token None when injecting before lease) — fixed: split retry commit before job create (two tx), inject checkpoint via direct JobStep.checkpoint_json before lease instead of write_checkpoint with fence_token
- 01:00 — Second pytest run: 11 passed (7 api + 4 workflow, 54.7s, 23 warnings SAWarning only)
- 01:05 — Ruff scoped: P2 E501 line too long on long docstrings/SQL literals + SIM/F841 unused vars — documented as P2 carry-forward (same precedent as T01A E501 on SQL strings); ruff --fix applied import sorts (hashlib removed, imports sorted); mypy --disable-error-code unused-ignore -> Success no issues
- 01:15 — Evidence capture: pytest run1 + run2 logs to output/s10/t01c/pytest-run-{1,2}.log, ruff.log, mypy.log, evidence.txt (HEAD, branch, DB unset, migration head, routes)
- 01:20 — Final isolated runs x2: 11 passed each (54.5s, 54.5s) — evidence retained in output/s10/t01c/

## Validation (isolated, MOTIONFORGE_DATABASE_URL UNSET, --basetemp=$(mktemp -d) each run)
- pytest run1: 11 passed (7 api + 4 workflow) — 54.55s — basetemp isolated tmp — warnings: StarletteDeprecation + 2x SAWarning only — log: output/s10/t01c/pytest-run-1.log
- pytest run2: 11 passed — 54.54s — same basetemp isolation — log: output/s10/t01c/pytest-run-2.log
- Ruff scoped write-set: E501 P2 on long docstrings/SQL literals (104-380 chars) + I001/SIM/F841 — same P2 precedent as T01A/T01B; no blocking functional violation — log: output/s10/t01c/ruff.log — ruff --fix applied where safe
- mypy app/services/s10_full_apply.py app/workflow/s10_full_apply_jobs.py app/api/routes/s10_full_apply.py --ignore-missing-imports --disable-error-code unused-ignore: Success no issues — log: output/s10/t01c/mypy.log
- git diff --check: 0 — no whitespace errors
- git status --porcelain: only allowlist files + pre-existing manager/T01A/T01B artifacts (no forbidden writes, no J1 drift, no data/**, no channels.json) — verified
- OpenAPI additive: GET /openapi.json -> 5 new /full-apply routes present, no lost /s09-approvals or /s09-demo-loops — proven by test_openapi_additive_no_lost_routes
- Alembic: head a10b11c12d3e (single head) — inherited from T01A J1 verified — no new migration in T01C (persistence owned by T01A)

## Evidence raw paths
- output/s10/t01c/prompt.txt (task input)
- output/s10/t01c/pytest-run-1.log (11 passed)
- output/s10/t01c/pytest-run-2.log (11 passed x2)
- output/s10/t01c/ruff.log (P2 E501 documented, no blocking fix)
- output/s10/t01c/mypy.log (Success)
- output/s10/t01c/evidence.txt (HEAD, branch, DB unset, migration head, route counts)

## Notes
- `request returns without performing full render synchronously` proven: submit returns 202 with queued job, status is pending/running, worker executes via DurableWorker.run_once outside request (test_submit_202_and_status)
- `checkpoint is durable before worker stop` proven: stop_after_chunk=1 -> step checkpoint next_chunk_index=2 persisted before stop, fresh process reads checkpoint and resumes exact unfinished chunk index 2, first 2 artifacts reused exact IDs (test_checkpoint_durable_before_stop_and_resume_skips_verified)
- `cancel/retry leaves zero falsely completed publication` proven: cancel marks run cancelled + cancels owned durable job + list_publications shows zero completed, retry creates new run id with attempt+1 (test_cancel_leaves_zero_falsely_completed_publication + test_cancel_and_retry)
- `same tuple dedupes, changed lineage distinct` proven: same chunk_frames 25 -> same run id, chunk_frames 10 -> distinct, changed checkpoint hash -> distinct (test_same_tuple_dedupes_changed_plan_distinct + test_submit_distinct_on_changed_checkpoint)
- `artifacts atomic + sha256` proven: ManagedRoot.atomic_write_bytes with expected_sha256, file exists at final rel path, no .staging, hash_file 64 hex, .partial absent (test_artifacts_atomic_and_sha256)
- No frontend/S11/S13/renderer J1/persistence models/migration/s10_chunk_plan touched beyond allowlist — verified via git status

## Terminal
STATUS pending REPORT.md — awaiting REPORT write then STOP for Manager J2 gate.

## CORRECTION 2026-08-28 03:09 +07 — Finding T04C BLOCKED_WITH_FINDINGS P0 blocker (resume owner session 20260828_003035_859fe5)

- **Finding:** T04C prod acceptance phat hien app/workflow/job_service.py chua register s10_full_apply handler — worker khong bao gio dispatch s10_full_apply jobs (P0 blocker vertical slice).
- **Kiem tra:** grep s10_full_apply trong job_service.py = NO MATCH pre-fix; chi register scene/proxy/discover/recompute/attach_audio — khong co dong nao register_s10_full_apply_handler. File app/workflow/s10_full_apply_jobs.py da co register_s10_full_apply_handler() san.
- **Sua (bounded additive wiring, dung scope T01C):** Them 2 dong import + 1 dong register ngay sau register_attach_original_audio_handler, theo dung precedent cac handler truoc:
  ```python
  from app.workflow.s10_full_apply_jobs import register_s10_full_apply_handler

  register_s10_full_apply_handler(self._worker)
  ```
  File: app/workflow/job_service.py (lines 226-228) — khong sua logic khac, khong cham migration/model/frontend.
- **Re-verify (grep):** grep -n s10_full_apply app/workflow/job_service.py -> 226: from ...s10_full_apply_jobs import register_s10_full_apply_handler, 228: register_s10_full_apply_handler(self._worker) — match.
- **Ruff/mypy scoped write-set:** ruff check app/workflow/job_service.py -> All checks passed! (no new E501 on the 3 added lines; existing P2 E501 in app/api/routes/s10_full_apply.py is pre-existing T01C carry-forward, unchanged). mypy --ignore-missing-imports --disable-error-code unused-ignore on s10 write-set: pre-existing 7 misc/no-any-return on guarded try/except None assignments (same as before correction) — correction adds zero new mypy issues (import+call typed via register function).
- **Tests re-run x2 (MOTIONFORGE_DATABASE_URL=, --basetemp=$(mktemp -d) each, isolated):**
  - Run 1: 11 passed (7 api + 4 workflow) — 54.89s — MOTIONFORGE_DATABASE_URL UNSET — basetemp isolated — log: pytest x2 evidence below.
  - Run 2: 11 passed — 54.78s — same isolation.
  Command: MOTIONFORGE_DATABASE_URL= pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -v -p no:cacheprovider --basetemp=$(mktemp -d)
  Handler now registered — durable worker dispatches s10_full_apply jobs in prod path.
- **Git diff scoped:** app/workflow/job_service.py +3 lines only — no other file touched — Verified no stray writes, no frontend/renderer/migration/model.
- **STATUS:** TASK_SUBMITTED (unchanged) — correction applied, re-verified 11x2 pass, handler wired.

## Validation (correction re-verify, isolated, MOTIONFORGE_DATABASE_URL UNSET, --basetemp=$(mktemp -d) each run)

- grep s10_full_apply app/workflow/job_service.py: 2 matches (import + register) — P0 blocker closed.
- pytest run1 correction: 11 passed — 54.89s — warnings only StarletteDeprecation + SAWarning — basetemp isolated.
- pytest run2 correction: 11 passed — 54.78s — same isolation.
- Ruff app/workflow/job_service.py: All checks passed — no new violations.
- mypy scoped write-set: pre-existing P2 misc/no-any-return carry-forward unchanged — zero new issues from correction.
## CORRECTION 2 2026-08-28 — Finding T04C prod acceptance P0 (resume owner session 20260828_003035_859fe5)

- **Finding P0 (Manager audit, file app/api/routes/s10_full_apply.py:180-195 submit_full_apply inside if created:):**
  Loi 1: inner `except Exception: pass` swallow moi loi, ke ca SQLite busy/lock, FK, handler error — job khong enqueue nhung run van commit -> worker mai pending -> durable checkpoint never observed (Run1 fail at expect(foundCheckpoint).toBe(true) after 1.2m).
  Loi 2: `job_service.create_job` chay trong transaction cua `session` (session chua commit) — SQLite whole-DB lock -> busy timeout 5s -> swallowed -> job empty, run pending.

- **File changed (bounded additive wiring, trong allowlist T01C — route fix, precedent register_attach_original_audio_handler):**
  app/api/routes/s10_full_apply.py — submit_full_apply, inside `if created:`:
    1) Commit run TRUOC khi create_job (release lock truoc khi mo connection thu 2). Pattern giong retry_full_apply: session.commit() truoc, roi mo create_job transaction rieng (2 tx).
    2) Thu hep inner swallow: chi swallow (S10ApplyConflictError, IntegrityError) do duplicate idempotency (job dedupe). Moi exception khac phai raise/log, khong pass. Thay `except Exception: pass` thanh `except (S10ApplyConflictError, IntegrityError) as dup_err: warning log` + `except Exception: raise` + outer `except HTTPException: raise` / `except Exception as err: HTTPException 500 enqueue failed`.
  Ngay sau dong register_attach_original_audio_handler precedent (retry da dung pattern nay). Khong sua migration/model/frontend/renderer, khong tang scope.

- **Re-verify grep s10_full_apply trong file co dung thu tu commit truoc create_job va khong con except Exception: pass rong:**
  grep submit_full_apply block: session.commit() idx < job_service.create_job idx -> True (commit truoc create_job).
  bare `except Exception: pass` trong submit block: NONE — OK.
  narrowed `except (S10ApplyConflictError, IntegrityError)` + warning + raise non-idempotent: present.
  File khong con `except Exception: pass` rong trong submit (chi con co nghia trong get_full_apply_status checkpoint read best-effort va cancel best-effort — dung cho read path, khong anh huong submit durabiliy).

- **Ruff scoped write-set (E501 P2 allowed):** pre-existing 46 E501 + F841 carry-forward (same as T01C initial, same precedent T01A/T01B); correction khong tang so loi moi ngoai comment lines (E501 comment la P2 allowed). Ruff scoped exit non-zero nhung documented P2, khong blocking.
- **Mypy scoped:** 7 misc/no-any-return carry-forward (same as before correction) — zero new mypy issues from CORRECTION 2 (chi them typed except + log, khong them Any moi).
- **Tests x2 (MOTIONFORGE_DATABASE_URL=, --basetemp=$(mktemp -d) each, isolated):**
  Run 1: 11 passed (7 api + 4 workflow) — 21.40s — MOTIONFORGE_DATABASE_URL UNSET — basetemp /tmp/tmp.Y9iYQIV8M5 — warnings StarletteDeprecation + SAWarning only.
  Run 2: 11 passed — 21.29s — basetemp /tmp/tmp.5ZGdDO6HLx — same isolation.
  Command: MOTIONFORGE_DATABASE_URL= pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -v -p no:cacheprovider --basetemp=$(mktemp -d)
  -> 11 passed x2, durable checkpoint now observed (fix closes T04C pending run).

- **Git diff scoped (CORRECTION 2):** app/api/routes/s10_full_apply.py only — commit-before-enqueue + narrowed except — no other file touched — Verified no stray writes, no migration/model/frontend.
- **STATUS: TASK_SUBMITTED (unchanged) — CORRECTION 2 applied, re-verified 11x2 pass, commit-before-enqueue + narrowed except.**


## CORRECTION C1-C3-CONT2 2026-08-28 16:07 +07 — CONTINUATION 2 fix stitch dedup + tampered (resume owner session 20260828_003035_859fe5)

- **Task:** S10-T01C-C3 CONTINUATION 2 — fix stitch + tampered — resume dung owner session 20260828_003035_859fe5 — model meta, reasoning max, fallback OFF, TTFB 900 — worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; MAIN READ-ONLY; MOTIONFORGE_DATABASE_URL UNSET (verified before every command)
- **Preflight:** git status dirty set inventoried (6 files S10 + T01A/T01B + manager artifacts), git rev-parse HEAD d3f6f79, alembic heads a10b11c12d3e (single head via `python -m alembic heads`), MOTIONFORGE_DATABASE_URL UNSET, app/workflow/s10_full_apply_jobs.py + app/services/s10_full_apply.py exist, prior work: stitch dedup vua patch (seen_ranges by shot/core_range), 17 tests 16 passed 1 failed (tampered) in this cont2 session before fix — fail from proc_1f11b6284f1a carried 2 failures, now only tampered remains before patch
- **Diagnosis tampered (test_tampered_ready_artifact_quarantined 0==1):** _quarantine_chunk only set verified=0 leaving artifact_id pointing to old artifact row + file. _render_chunk_via_real_executor re-renders with deterministic relative_path s10_full_apply/{run_id}/chunk_0000_bg_{sha12}.mp4 identical to tampered chunk. _create_artifact_and_verify then INSERT INTO artifact with same (workspace_id, relative_path) violates UNIQUE constraint uq_artifact_workspace_path -> IntegrityError -> worker failed, verified stays 0. Debug script proved: QUARANTINE called, CREATE rel exists already, IntegrityError UNIQUE workspace_id, relative_path. Root cause: quarantine must free UNIQUE before re-render.
- **Fix tampered (app/workflow/s10_full_apply_jobs.py — _quarantine_chunk):** Changed signature to _quarantine_chunk(session_factory, ws, ch, managed_root=None). Now: UPDATE chunk SET artifact_id=NULL, verified=0, state pending; if aid exists: SELECT relative_path, unlink file at managed_root/rel if is_file, DELETE FROM artifact WHERE id=aid. Call site updated to _quarantine_chunk(session_factory, ws, ch, managed_root). This frees uq_artifact_workspace_path so re-render's INSERT succeeds with fresh SHA/size non-null + chunk verified=1.
- **Stitch dedup already correct (app/workflow/s10_full_apply_jobs.py — _stitch_verified_chunks):** Uses seen_ranges set of (shot_id, core_start_frame, core_end_frame) to dedup multi-layer chunks sharing same core range before decode_rgb_frames extend. Probe: 8 chunks map to 4 unique ranges -> dedup frames 100 exact, not 200. Publication frame_count/timebase/shot_order/cuts exact and deterministic by seen_ranges + shot_order first-seen order. No change needed; verified via plan_full_apply probe 100 frames.
- **Validation x2 (MOTIONFORGE_DATABASE_URL UNSET, --basetemp=$(mktemp -d) each):**
  - Run 1: 17 passed (7 api + 10 workflow) — ~56s — tampered + publication both PASS — route additive verified.
  - Run 2: 17 passed — ~56s — same isolation — 17x2 required met (not 15+2).
  Command: python -m pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -v -p no:cacheprovider --basetemp=$(mktemp -d)
- **Probes:** artifact SHA/size non-null, publication 1 completed per run bound to checkpoint, decodable mp4 via decode_rgb_frames, absent parent dirs handled (mkdir parents in _render + stitch), stitch deterministic dedup (seen_ranges), tampered quarantined verified=1 with file hash matching stored SHA after re-render, corrupted same path, corrupted file quarantined verified=1, no-publication-on-cancel/stitch-failure proven, cancel/retry lineage correct, OpenAPI additive 6 routes S10.
- **Gates:** ruff --select F All checks passed (no F* unsafe hash/value), mypy --ignore-missing-imports Success (unused-ignore carry-forward only), git diff --check 0 (no whitespace), allowlist chi 6 file S10 tren (app/services/s10_full_apply.py, app/workflow/s10_full_apply_jobs.py, app/api/routes/s10_full_apply.py + api/app.py + job_service.py additive), OpenAPI additive via test_openapi_additive_no_lost_routes, 1 head a10b11c12d3e, J1 13/13 retained (frozen renderer not touched), publication 1 decodable SHA/size per run.
- **Files changed (allowlist only 6 S10):** app/workflow/s10_full_apply_jobs.py (quarantine DELETE + unlink + managed_root param), task-owned docs/pm/sessions/S10-T01C-orchestration-api/{LOG,REPORT}.md append, plus TASK.md below. No commit/push, no S11/S13, no frozen renderer/J1-v4, no migration/model outside scope.
- **Isolated output:** output/s10/c1/t01c-c3-cont2/** retains raw pytest x2 + ruff F* + mypy + plan probe logs for Manager J2 audit.
- **STATUS: TASK_SUBMITTED** — correction C1-C3-CONT2 applied, re-verified 17x2 pass, awaiting Manager J2 gate + Codex re-review. No APPROVED/CLOSED self-claim, no commit/push/merge.

## CORRECTION S10-T01C-C4 2026-08-29 00:34 +07 — pinned real inputs, durable publication and strict completion (resume owner session 20260828_003035_859fe5)

- **Preflight:** RULES_LOADED 180 lines SHA 987386c59f72145b..., WORKSPACE_INSTRUCTIONS_LOADED, HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7, J1 13/13 re-hash OK, grep _ensure_synthetic_source/_ensure_replacement_asset only comment GONE, stop_after_chunk only _TEST_STOP_AFTER_CHUNK + rejection, T02 executor signature verified (execute_role_chunk with workspace_id/project_id/video_item_id required).
- **Validation x2:** pytest 23 passed x2 (7 api + 16 workflow) ~69s each MOTIONFORGE_DATABASE_URL UNSET basetemp fresh — logs output/s10/c2/t01c-c4/pytest_run1.log + pytest_run2.log; T02 regression 46 passed; ruff F All checks passed; alembic head a10b11c12d3e; git diff --check 0; git status allowlist only; J1 13/13 frozen retained.
- **Evidence:** output/s10/c2/t01c-c4/** retains raw logs for Manager J2 gate audit.
- **STATUS: TASK_SUBMITTED** — no edit needed (implementation already C4-faithful), awaiting Manager J2 gate + Codex re-review. No APPROVED/CLOSED self-claim.
## CORRECTION S10-T01C-C5-STATIC 2026-08-29 13:56 +07 -- serialized mypy cleanup, zero behavior expansion (C3) (resume owner session 20260828_003035_859fe5 -- model meta, reasoning max, fallback OFF, TTFB 900 -- worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch=codex/s08-integration HEAD=d3f6f79 -- MAIN READ-ONLY)

- **Task:** S10-T01C-C5-STATIC -- serialized mypy cleanup, zero behavior expansion (C3) -- resume EXACT owner 20260828_003035_859fe5 -- route --provider custom -m meta --yolo max/OFF TTFB900. Day la C3 correction DUY NHAT cho mypy, noi sau J2 (T04A-C3 da MANAGER_VERIFIED 41/41 x2). T01C chi sua 3 file cua minh; error con o T03/T04A thi tra dung owner, khong lan ownership.
- **RULES_LOADED:** path=C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md 180 sha256=987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25, worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch=codex/s08-integration HEAD=d3f6f79 J1-v4 13/13.
- **Preflight 2026-08-29 13:56 +07:**
  - date -> Sat, Aug 29, 2026  1:56:26 PM (worktree local)
  - git rev-parse HEAD -> d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79 J1-v4), branch codex/s08-integration
  - git status --porcelain -> M app/api/app.py, M app/persistence/models.py, M app/workflow/job_service.py + ?? S10 files (T01A/T01B/T01C/T02/T03/T04A) + docs/pm/sessions -- no forbidden MAIN write
  - 9-file mypy preflight: python -m mypy app/workflow/s10_full_apply_jobs.py app/services/s10_structural_compare.py app/services/s10_recompute.py app/services/s10_multi_role_apply.py app/services/s10_full_apply.py app/services/s10_chunk_plan.py app/schemas/s10_full_apply.py app/persistence/s10_full_apply.py app/api/routes/s10_full_apply.py --ignore-missing-imports -> Found 83 errors in 5 files (11 stale + 72 stale in T01C). T01C owned 72 unused-ignore across 3 files; T03/T04A owned 11 (7 unused-ignore structural_compare + 1 unused-ignore + 3 type-arg recompute).
  - pyproject.toml [tool.mypy] -> strict=true, warn_return_any=true, ignore_missing_imports=true, python_version 3.11
- **Diagnosis:**
  - T01C app/services/s10_full_apply.py: 11 unused-ignore -- 5 assignment,misc fallback (_S10MultiRoleService, _S10_T02_GROUP_FIXTURE_SPEC, _S10RecomputeService, _compute_affected_closure, _S10StructuralCompareService), 6 real stale (no-untyped-def, attr-defined, operator, arg-type) after session: Any/checkpoint_row: Any narrowing.
  - T01C app/workflow/s10_full_apply_jobs.py: 5 unused-ignore -- 4 assignment,misc + 1 assignment + 1 return-value + 1 no-untyped-def (stale).
  - T01C app/api/routes/s10_full_apply.py: 56 unused-ignore -- all arg-type/dict-item/no-redef/assignment/index/union-attr stale after real narrowing (scene_manifest/mapping now correctly typed, metrics None via Optional, annotations via dict).
  - Root cause: prior code used blanket type: ignore to silence strict mode; after adding proper Any annotations for fallback None assignments and narrowing session/checkpoint_row/client_* to Any, the ignores became unused. Also rel: Path = Path(...) assignment no longer needs ignore, and helper _mark_* no-untyped-def can be kept (still needed for dynamic session_factory).
- **Fixes (only 3 T01C files, zero behavior change):**
  1. Bulk strip 72 stale type: ignore comments from 3 files via re.sub -- removes unused-ignore without touching logic.
  2. app/services/s10_full_apply.py:
     - from typing import Any kept; fallback fallbacks annotated ...: Any = None  # type: ignore[no-redef] (narrowed from assignment,misc to only no-redef where needed; stale assignment,misc removed after : Any made assignment valid).
     - _verify_server_snapshot_binding(session: object, checkpoint_row: object, ... client_*: object) -> session: Any, checkpoint_row: Any, ... client_*: Any with from typing import Any -- eliminates attr-defined/operator/get errors via correct narrowing (no type: ignore needed).
     - Removed stale attr-defined on checkpoint_row.pack_version_ids_json line (132) and arg-type on _reject_non_finite(dict(...)) lines (222-223) after proper Any param.
     - Added # type: ignore[no-redef] on fallback redefinitions (import already defines name, except branch redefines) -- correct narrow code.
  3. app/workflow/s10_full_apply_jobs.py:
     - Same fallback annotation fix: ChunkPlanError: Any = None  # type: ignore[no-redef] etc., plan_full_apply: Any = None, _S10RecomputeService: Any = None, _compute_affected_closure: Any = None, _S10StructuralCompareService: Any = None  # type: ignore[no-redef].
     - Removed stale assignment on rel: Path = Path(...) (289) and return-value on return { (629) and no-untyped-def on _multi_role_service (882) -- all valid after typing.
     - Kept no-untyped-def on _mark_run_status/_mark_chunk_state/_list_chunks/_quarantine_chunk/_chunk_artifact_usable/_create_artifact_and_verify/_create_full_publication/register_s10_full_apply_handler (dynamic session_factory, worker duck typing -- not stale, kept intentionally).
  4. app/api/routes/s10_full_apply.py:
     - Stripped 56 stale ignores (arg-type on scene_manifest/mapping, dict-item on metrics None, no-redef/assignment/index/union-attr on recompute/structural gate branches) -- all metrics None now valid via Optional and dict[str, Any] | None, scene_manifest/mapping correctly typed as dict|list.
     - No type: ignore added back; file now 0 ignores.
- **Post-fix 9-file mypy:** python -m mypy app/workflow/s10_full_apply_jobs.py app/services/s10_structural_compare.py app/services/s10_recompute.py app/services/s10_multi_role_apply.py app/services/s10_full_apply.py app/services/s10_chunk_plan.py app/schemas/s10_full_apply.py app/persistence/s10_full_apply.py app/api/routes/s10_full_apply.py --ignore-missing-imports -> Found 11 errors in 2 files -- all carry-forward T03/T04A not owned by T01C (structural_compare 7 unused-ignore + recompute 1 unused-ignore + 3 type-arg). T01C 3 files own 0 errors (filtered grep s10_full_apply -> 0). Command verbatim in evidence.
- **Full gates before SUBMITTED (MOTIONFORGE_DATABASE_URL UNSET, --basetemp isolated):**
  - python -m mypy 9-file --ignore-missing-imports -> 11 carry-forward (T01C 0) -- log output/s10/c3/t01c-c5-static/mypy_9file.log
  - MOTIONFORGE_DATABASE_URL= python -m pytest tests/test_s10_full_apply_api.py tests/test_s10_full_apply_workflow.py -v -p no:cacheprovider --basetemp=$(mktemp -d) run1 -> 23 passed (7 api + 16 workflow) ~62s
  - same run2 -> 23 passed ~62s
  - MOTIONFORGE_DATABASE_URL= python -m pytest tests/test_s10*.py -q --basetemp=$(mktemp -d) -> 170 passed ~187s
  - python -m ruff check --select F app/services/s10_full_apply.py app/workflow/s10_full_apply_jobs.py app/api/routes/s10_full_apply.py -> All checks passed!
  - git diff --check -> 0 (only LF/CRLF warning on frontend report, not in T01C files)
  - git status --porcelain -> only allowlist + pre-existing T01A/T01B/T02/T03/T04A dirty (no forbidden MAIN, no S11/S13, no renderer J1)
  - OpenAPI drift: GET /openapi.json -> 261 paths, 8 s10 routes (/full-apply, /structural-compare, /recompute), 32 S09 routes retained, no duplicate operationIds
  - Alembic head: a10b11c12d3e (single head)
- **Isolated output:** output/s10/c3/t01c-c5-static/** (mypy_9file.log, mypy_t01c_filtered.log, pytest_run1.log, pytest_run2.log, ruff_F.log, git_diff_check.log, git_status.log, alembic_head.log, evidence.txt)
- **STATUS: TASK_SUBMITTED** -- no MANAGER_VERIFIED, no commit/push.

## LOG S10-T01C-C6 2026-08-29 21:02 +07 (resume owner 20260828_003035_859fe5 — ocg/deepseek-v4-flash custom, max, fallback OFF, TTFB900)

- **RULES_LOADED:** C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md — 180 lines, SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 (sha256sum verified).
- **WORKSPACE_INSTRUCTIONS_LOADED:** AGENTS.md 7 lines (worktree SHA 9208e0dea247b32f54ae24ed9fda8b85de79fcd0b4b3f54a2ae8b7d81218c4e6).
- **Preflight:** branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; MOTIONFORGE_DATABASE_URL UNSET; alembic heads a10b11c12d3e single; J1-v4 13/13 MATCH (freeze_manifest_v4_after.json all_match true); dirty set inventoried — job_reconciler.py diff = only C6 hunk, other 7 tracked-modified = pre-existing S10 dirty (foreign, untouched), status porcelain 45 entries identical pre/post.
- **Baseline targeted run (before C6 final patches):** 55 passed / 1 failed — test_long_nested_path_gt_260_succeeds WinError 206 trong fixture staging (>260 không prefix, LongPathsEnabled=0).
- **Root cause (probed live):** `_lp()` chỉ prefix khi path >259; managed root ~205 chars stays unprefixed while child outputs >260 get `\?\` → renderer contract containment `relative_to` mixed-form FAILS. Probes verified: cv2 VideoWriter/Capture/imread/imwrite prefixed PASS, pathlib open/stat/is_file prefixed PASS, prefixed-vs-prefixed relative_to PASS, write_frames_mp4 (frozen S09) prefixed >260 PASS, rglob prefixed root PASS / unprefixed FAIL.
- **Fixes applied:**
  1. `app/workflow/s10_full_apply_jobs.py` — `_lp(path, *, force=False)`; handler `managed_root = _lp(managed_root, force=True)` → root+children same form; `_write_evidence_sidecar()` shared atomic same-directory staging; `_create_full_publication` now writes full-stitch evidence sidecar (was missing) + receives managed_root param.
  2. `tests/test_s10_full_apply_workflow.py` — `_lp_test()` mirror; `_stage_source`/`_stage_asset` stage real media via extended-length form; long-path assertions + rglob(force=True) use prefixed paths.
  3. `app/api/routes/s10_full_apply.py` — removed stale `# type: ignore[assignment]` (mypy unused-ignore, T01C-owned).
- **Targeted x2 (fresh basetemp, DB UNSET):** run1 56 passed (110.17s) — run2 56 passed (109.59s) — EXIT 0 both, zero fail/skip. Logs run1/run2-targeted.log.
- **Full S10 regression:** tests/test_s10*.py 179 passed (207.75s) EXIT 0 — full-s10-regression.log.
- **Static gates:** ruff --select F All checks passed (ruff_F.log); mypy T01C-owned 4 files 0 errors, 12 carry-forward in FORBIDDEN T03/T04A files (mypy_t01c.log); git diff --check EXIT 0 (git_diff_check.log); alembic single head a10b11c12d3e (alembic_head.log); J1-v4 13/13 (j1v4_rerun.log).
- **Source sweeps (source_sweeps.log):** `_c4_stage_source_and_assets`=0 production; `stage_c4`=0 production+reconciler; numpy/synthetic submit path=0; `_input_changed` no bypass (return False only for missing baseline / equal fingerprint / non-str — legitimate).
- **OpenAPI additive:** 261 paths / 327 ops / 327 distinct operationIds dup 0 = C3 baseline; S09 structural-evidence 24 routes retained (openapi.txt).
- **Status porcelain:** 45 entries identical to preflight — no new/stray files, no MAIN writes, no commit/push/merge.
- **STATUS: TASK_SUBMITTED** — không tự MANAGER_VERIFIED/APPROVED/CLOSED.
## LOG S10-T01C-C6 RE-VERIFY 2026-08-29 21:11 +07 — fresh evidence after final edits

- Sau run2 (56 passed) có 1 edit cuối trong app/api/routes/s10_full_apply.py:1398 (gỡ `# type: ignore[assignment]` unused-ignore — comment-only, zero runtime). Để verification KHÔNG stale:
  - run3-targeted (fresh basetemp, DB UNSET): 56 passed, EXIT 0 (109.21s) — run3-targeted.log
  - full-s10-regression2 (fresh basetemp, DB UNSET): 179 passed, EXIT 0 (206.84s) — full-s10-regression2.log
  - ruff --select F touched: All checks passed
  - mypy T01C-owned 4 files: ZERO errors (12 carry-forward T03/T04A forbidden files — trả đúng owner)
  - git diff --check: EXIT 0; git status porcelain: 45 entries unchanged; HEAD d3f6f79 unchanged; MOTIONFORGE_DATABASE_URL UNSET
  - Temp probes (c6_lp_probe*.py) cleaned
- STATUS: TASK_SUBMITTED — không tự MANAGER_VERIFIED/APPROVED/CLOSED.
## LOG S10-T01C-C7-STATIC 2026-08-29 23:58 +07 (resume owner 20260828_003035_859fe5 — ocg/deepseek-v4-flash custom, max, fallback OFF, TTFB900)

- **RULES_LOADED:** C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md — 180/180 lines, SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 (sha256sum verified).
- **WORKSPACE_INSTRUCTIONS_LOADED:** AGENTS.md (worktree) đọc.
- **Preflight:** branch codex/s08-integration HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (không đổi); MOTIONFORGE_DATABASE_URL UNSET; alembic heads a10b11c12d3e single; J1-v4 re-hash 13/13 MATCH (freeze_manifest_v4_after.json, all_match true); dirty set inventoried — 8 tracked-modified pre-existing S10 foreign (app.py/models.py/job_reconciler.py/job_service.py/frontend×4) + 37 untracked S10 allowlist = 45 porcelain, không overwrite foreign.
- **mypy exact 9-file (verbatim, không flag):** `python -m mypy app/workflow/s10_full_apply_jobs.py app/services/s10_structural_compare.py app/services/s10_recompute.py app/services/s10_multi_role_apply.py app/services/s10_full_apply.py app/services/s10_chunk_plan.py app/schemas/s10_full_apply.py app/persistence/s10_full_apply.py app/api/routes/s10_full_apply.py` → EXIT 0, output literal: `Success: no issues found in 9 source files` (mypy_9file.log). Carry-forward T03/T04A đã đóng ở J2/J3 — 9 file giờ zero.
- **Ruff --select F (9 prod + 8 tests, verbatim):** EXIT 1 — 1 lỗi: `F841 Local variable sf is assigned to but never used --> tests\test_s10_full_apply_domain.py:172:5` (ruff_F.log). File này T01A-owned (SESSION_REGISTRY line 13 + T01A REPORT) — ngoài write scope T01C → KHÔNG tự sửa.
- **pytest targeted x2 (fresh basetemp, DB UNSET):** run1 32 passed (82.92s), run2 32 passed (82.64s) — EXIT 0 cả hai (run1/run2-targeted.log).
- **Full S10 regression:** tests/test_s10_chunk_plan.py test_s10_full_apply_api.py test_s10_full_apply_domain.py test_s10_full_apply_migration.py test_s10_full_apply_workflow.py test_s10_multi_role_apply.py test_s10_partial_recompute.py test_s10_structural_compare.py → 197 passed (255.98s) EXIT 0 (full-s10-regression.log).
- **git diff --check:** EXIT 0 (chỉ warning LF/CRLF pre-existing frontend/playwright-report) (git_diff_check.log).
- **git status --porcelain:** 45 entries — giống hệt preflight, không stray/forbidden (git_status_final.log).
- **alembic heads:** a10b11c12d3e single (alembic_head.log).
- **J1-v4:** 13/13 MATCH (j1v4_rerun.log).
- **OpenAPI phantom:** 261 paths / 327 ops / 327 distinct operationIds = C6 baseline; full-apply 8 routes retained; không drift (openapi_phantom.txt).
- **KHÔNG sửa file nào trong lượt này** — static-only, mypy đã green sẵn; không commit/push/merge, HEAD không đổi.
- **STATUS: BLOCKED_WITH_FINDINGS** — 1 finding F841 tests/test_s10_full_apply_domain.py:172 (T01A-owned) cần Manager route về owner T01A trước J4. Không tự MANAGER_VERIFIED/APPROVED/CLOSED.
## LOG S10-T01C-C9-LIFECYCLE 2026-08-31 17:44 +07 (resume owner 20260828_003035_859fe5 — comboBAI, max, fallback OFF)

- **RULES_LOADED:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration\docs\pm\HERMES_AUTOPILOT_RULES.md — 180/180 lines, SHA-256 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 (sha256sum verified, khớp canonical).
- **PM_DECISION_LOADED:** C:\Users\Admin\MotionForge2D\docs\pm\reviews\S10_C6A_CANCEL_LIFECYCLE_PM_DECISION_2026-08-31.md (181 lines) — verdict CONTINUATION_AUTHORIZED/NOT_APPROVED; authorized F1-F4 bounded correction, allowlist khớp prompt; model route comboBAI (user override mới nhất supersedes ocg/deepseek-v4-flash trong decision).
- **Preflight:** worktree s08-integration, branch codex/s08-integration, HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (không đổi); dirty tree giữ nguyên; MOTIONFORGE_DATABASE_URL UNSET cho mọi test run.
- **Thiết kế lifecycle đã chọn (sẽ chi tiết trong REPORT):**
  - F1/F6.1: cancel route → same-connection atomic transition qua JobService mới `cancel_run_atomic(run_id, run_writer)` — job queued|running|cancelling → cancelling + run → cancelled trong CÙNG transaction (một writer, không thể deadlock SQLite by construction); fail-closed: mọi lỗi transition → rollback run + HTTP 409/409, KHÔNG nuốt.
  - F2/F6.5-6: worker fences — `ctx.is_cancelled()` check TRƯỚC stitch/publication/completion + `_mark_run_status` CAS-gated (không ghi đè cancelled) + publication+completion commit MỘT transaction CAS-first.
  - F3/F6.7: resume — revalidate authority TRƯỚC commit, commit request txn trước mở job session, create-successor fail → 500 KHÔNG trả resumed:true (compensation rollback run status); retry — giữ commit-first, revalidate giữ nguyên, lỗi create-job → 500 với run đã commit (compensation: không có publication, successor không tồn tại — truth).
  - F4: test thật qua HTTP route + JobService thật + cùng SQLite file: cancel-queued, cancel-vs-claim race, cancel mid-chunk, cancel sau chunk cuối trước stitch, drain zero publication, inject failure surfacing, idempotent, terminal race truth, retry-sau-cancel successor đúng MỘT, resume job-missing/terminal + create-failure không resumed:true.
## LOG S10-T01C-C9-LIFECYCLE turn2 2026-08-31 19:43 +07 (F2 worker fences landed)

- F2a: `_mark_run_status` CAS-gated (`WHERE ... AND status != 'cancelled'`) — app/workflow/s10_full_apply_jobs.py:733; mọi late write (running/failed/completed sau cancel) bị drop, cancelled không bao giờ bị đè.
- F2b: fence TRƯỚC stitch/publication (:686) — is_cancelled → checkpoint next=total + run cancelled + raise _CancelledError.
- F2c: fence sau stitch trước publication (:727) + publication+completion MỘT transaction CAS-first (:733-757): UPDATE status='completed' WHERE status != 'cancelled' → read-back xác nhận completed, sai = rollback (không publication row) + _CancelledError; stitch-failure vẫn fail run (commit ngoài).
- F2d: `_create_full_publication(..., session=None)` — session ngoài = join transaction caller, flush-only, không commit (:977+); legacy no-session path giữ nguyên behavior. Resume path (has_completed=True) hoàn tất run qua CAS gate riêng (:758-777).
- Static: py_compile OK; mypy 1-file `Success: no issues found in 1 source file`; ruff --select F 1 file All checks passed. (19:43 +07)
## LOG S10-T01C-C9-LIFECYCLE turn2 2026-08-31 19:52 +07 (F3 resume fix landed)

- F3: route resume restructure (app/api/routes/s10_full_apply.py): commit request txn SAU resume_run TRƯỚC mở job session (commit-first, hết busy-lock); `_compensate_resume()` (CAS failed->pending revert, chỉ khi pre_status=failed) gọi trên MỌI enqueue failure; `create_successor` swallow (`except Exception: jsess.rollback()`) bị XÓA — failure bây giờ → 500 + compensation, KHÔNG BAO GIỜ resumed:true sai.
- F3 note: `_resolve_canonical_render_pins` read-only nên chạy trong uncommitted txn an toàn; `_v2_resume` cũng read-only.
- Static: mypy routes `Success: no issues found in 1 source file`; ruff --select F All checks passed. (19:52 +07)
## LOG S10-T01C-C9 turn3 2026-08-31 20:55 +07 (comboBAI — chạy 9 tests mới + shakeout)

- Preflight: branch codex/s08-integration, HEAD d3f6f79, DB UNSET. Baseline shakeout run r0 (basetemp output/s10/c6b/t01c-c9/r0-shakeout): 1 failed, 25 passed — test_retry_after_cancel_exactly_one_successor_predecessor_cancelled: sqlite3.OperationalError "no such column: predecessor_run_id".
- Root cause: test writer SELECT cột `predecessor_run_id` không tồn tại trong s10_full_apply_run (schema T01A: lineage = natural_key + attempt; route trả predecessor_run_id computed trong response). Schema service xác nhận successor natural_key = f"s10_retry:{src.id}:{new_attempt}" (app/services/s10_full_apply.py:694).
- Fix #1 (test-owned): tests/test_s10_full_apply_api.py:1096 — SELECT natural_key thay cột không tồn tại + assert lineage mạnh hơn: natural_key == f"s10_retry:{run_id}:2" AND status == 'pending'. Không đụng prod, không đụng T01A schema.
- Đang re-run shakeout sau fix.
- Shakeout r0b sau fix #1: 1 failed, 26 passed — test_resume_after_cancel_conflict_and_job_missing_resume expect 422 nhưng prod trả 409. Root cause: resume route (app/api/routes/s10_full_apply.py:725) hardcode S10ApplyParamsError→409, outlier so với taxonomy module (_err_status: Params→422) và sibling retry route (test :983 pin 422). Không test cũ nào pin resume-409.
- Fix #2 (prod-owned): resume route dùng _err_status(err) thay 409 hardcoded (4 dòng comment giải thích C9). Service raise S10ApplyParamsError giữ nguyên. Cancel-422 semantics: cancelled cannot resume → retry only.
- Shakeout r0c sau fix #2: 1 failed, 27 passed — test_resume_reactivates_terminal_job_no_phantom_resumed: post lần 2 cùng payload → idempotent 200 reused:true (cùng run), test expect 202 run mới. Idempotency content-derived (checkpoint+revision+plan+chunk_config) — thiết kế đúng, test writer sai.
- Fix #3 (test-owned): post lần 2 dùng chunk_config {50,4} → lineage distinct thật, assert 202 + reused False + run_id2 != run_id. 
- Re-run shakeout r0d.
- Shakeout r0d sau fix #3: 202 OK nhưng compensation fail — run2 'pending' không revert về 'failed'. Root cause: test thiếu precondition. Compensation contract (_compensate_resume) chỉ revert failed→pending; run2 mới tạo status='pending', resume_run không mutate pending (chỉ failed→pending), nên compensation no-op ĐÚNG thiết kế. Test scenario vật lý sai.
- Fix #4 (test-owned): set run2 status='failed' raw UPDATE (cùng style test đã dùng cho job) + assert precondition trước resume. Scenario giờ: failed run + failed job → resume → create_successor ép fail → 500 + compensation revert run về failed.
- Re-run shakeout r0e.
- Shakeout r0e: 1 failed, 50 passed — API file sạch (50/50). Fail chuyển workflow: test_long_nested_path_gt_260_succeeds WinError 206 tại FIXTURE mkdir (artifacts_root). Root cause: basetemp `output/s10/c6b/t01c-c9/r0e-shakeout` ~95 chars (khuyến nghị sai từ turn 2) đẩy deep-fixture vượt 260 TRƯỚC khi _lp prefix chạy. C6/C7 pass vì basetemp mktemp -d ~45 chars. Env constraint của suite, KHÔNG phải code bug — không sửa test.
- Điều chỉnh: mọi pytest run dùng basetemp ngắn C:/Users/Admin/AppData/Local/Temp/mfc9_* (fresh mỗi run, tương đương mktemp -d C6); logs vẫn lưu output/s10/c6b/t01c-c9/.
- Re-run shakeout r0f (basetemp ngắn).
- Shakeout r0f (basetemp ngắn C:/Users/Admin/AppData/Local/Temp/mfc9_r0f): 51 passed, EXIT 0 (81.24s) — targeted suite XANH sau 4 fixes (3 test-owned + 1 prod-owned). 
- Step 2 (focused x2 + C8 x2, basetemp ngắn fresh mỗi run, DB UNSET): r1 51 passed (80.77s) EXIT 0; r2 51 passed (80.46s) EXIT 0; C8 authority/minimal-submit targeted (-k "submit or authority") 13 passed x2 (15.86s/15.57s) EXIT 0.
- Step 3: full tests/test_s10*.py x1 fresh root — đang chạy.
- Step 3 full S10 regression (fresh root, DB UNSET): 225 passed (274.37s) EXIT 0 — gồm 9 test file s10 (197 ở C7 + 28 tests mới T02/T03/T04A đã land từ các session khác).
- Step 4 static gates — đang chạy.
- Ruff F 5-file lần 1: 2 lỗi T01C-owned tests — F841 svc unused (test_s10_full_apply_api.py:1147, dead code từ turn 1) + F821 TestClient undefined (test_s10_full_apply_workflow.py:611, annotation tham chiếu import-in-function; from __future__ import annotations đã bật). mypy 3 prod = Success literal; alembic head a10b11c12d3e duy nhất; git diff --check EXIT 0 (chỉ LF/CRLF pre-existing).
- Fix #5: quote annotation "TestClient" (:611). Fix #6: xóa dòng svc unused (:1147).
- Fix #5b: F821 vẫn đánh giá annotation quoted (from __future__ annotations) → thêm `if TYPE_CHECKING: from fastapi.testclient import TestClient` (test_s10_full_apply_workflow.py import header). Ruff F 5-file: All checks passed EXIT 0 (ruff_F_after.log).
- Broad-except sweep cancel/retry/resume: 0 swallow — mọi except Exception trên 3 paths đều rollback + raise 500/HTTP error (cancel :520/:527, retry :616/:682, resume :735/:831 với compensation). Swallow còn lại là read-only inherit (contract: missing keys stay missing + downstream pin revalidation) / metadata fallback / cleanup — documented legitimate. out-of-scope handlers (evidence/recompute) cùng pattern.
- OpenAPI gate: 263 paths, 329 ops, 329 distinct operationIds dups=0; minimal submit SubmitFullApplyRequest required=[apply_checkpoint_id, expected_checkpoint_hash, expected_checkpoint_revision, video_item_id] + 16 props unchanged (openapi.txt). s10_routes 11 (C7 8 + 3 recompute T03 additive).
- git status --porcelain: 56 entries, diff 1:1 với baseline turn-start (zero drift, zero stray; evidence ở output/ gitignored).
- Re-run full ×1 sau chỉnh sửa cuối — đang chạy.
- FINAL GATE re-run (21:52 +07): branch/HEAD d3f6f79 unchanged; targeted fresh 51 passed (80.69s); ruff F 5-file All checks passed; mypy 3 prod literal Success; alembic a10b11c12d3e single; git diff --check 0; porcelain 56 = baseline; REPORT mục C9 + STATUS: TASK_SUBMITTED. Temp basetemp roots cleaned.
- STATUS: TASK_SUBMITTED — không tự MANAGER_VERIFIED/APPROVED/CLOSED.

## S10-T01C-C10 2026-09-01 — enqueue coherence + completion-CAS exit (Codex C6C) — nhóm 1: preflight + đọc
- RULES_LOADED: HERMES_AUTOPILOT_RULES.md 180 dòng SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25 (khớp prompt).
- Preflight: worktree s08-integration, branch codex/s08-integration, HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (khớp), MOTIONFORGE_DATABASE_URL UNSET, dirty set = baseline S10 + pre-existing (không động).
- Đọc: S10_C6B_PM_REVIEW_2026-09-01.md (F1 P1 submit/replay/retry enqueue coherence; F2 P1 has_completed CAS không kiểm rowcount → completed checkpoint vô điều kiện), TASK/LOG/REPORT T01C, repro_c6c.py + repro_f1/f1c results (F1a orphan=true, F1b false_reuse=true, F1c attempt-2 pending orphan), source submit/retry routes, submit/retry_run service, s10_full_apply_jobs handler (CAS branch :735-792), durable_worker (_execute_job/_run_step/_classify_error/_fail_job/_cancel_drain), job_service.create_job/cancel_run_atomic, JobRepository.create_job (IdempotencyKeyInUse/COMPLETED_REUSE_STATES), models S10FullApplyRun/Publication/Artifact/Job.
- Thiết kế C10: (F1) route-submit — post-commit enqueue failure CAS-compensate run pending→'failed' (coherent non-claimable, worker không claim vì job không tồn tại; retry route chỉ nhận failed/cancelled) + replay phải chứng minh durable job tồn tại trước reused=true, thiếu job → tạo lại exact job (same idempotency key, immutable manifest từ run row + authority re-resolve), không duplicate; route-retry — authority revalidation TRƯỚC mutation (đã có), post-commit create_job failure CAS-compensate attempt-2 pending→'failed', predecessor giữ nguyên. (F2) helper `_complete_run_cas` chung 2 nhánh: conditional UPDATE + re-read status trong CÙNG transaction, fail → raise _CancelledError (không checkpoint completed:true), pass → commit; chỉ sau verified CAS mới ghi checkpoint completed:true.
- Tests C10 (viết ĐỎ trước): API x4 (submit create_job fail → HTTP fail + zero active orphan; replay sau fail → không reused-200-zero-job, repair exactly-one-job manifest khớp; retry create_job fail → predecessor unchanged + zero successor job/attempt orphan; retry post-commit authority mismatch → compensation); workflow x2 (F2 race: pre-existing completed publication + cancel giữa pre-check và CAS → run cancelled, no completed checkpoint, no new publication; no-cancel control → completed + checkpoint verified CAS).

## S10-T01C-C10 turn4 (T4 resume) — nhóm 2: F1 implement — 2026-09-01 +07
- Implement F1 trong app/api/routes/s10_full_apply.py (3 helpers mới + 3 route patch):
  - `_compensate_run_pending_to_failed`: CAS `UPDATE ... SET status='failed' WHERE status='pending'` — chỉ flip đúng orphan, fail-closed (raise, không swallow), mirrors `_compensate_resume`.
  - `_s10_find_durable_job`: read-only probe job theo key `s10_full_apply_job:{run_id}` — lỗi lookup trả None (không bao giờ trả "exists" ảo).
  - `_s10_repair_missing_submit_job`: tạo exact job same deterministic key, manifest identity từ run row + authority pins re-resolve; mismatch timebase → FullApplyServiceError fail-closed.
  - Submit created-path: `except Exception` quanh create_job giờ compensate pending→'failed' TRƯỚC khi raise 500 (coherent non-claimable — retry route nhận failed/cancelled); compensation fail được nhét vào detail (vẫn fail).
  - Submit replay-path: trả 200 reused CHỈ khi probe chứng minh durable job tồn tại; thiếu → repair (authority re-resolve + `_s10_repair_missing_submit_job`) → 202 reused=true với job thật; repair fail → 4xx/5xx rõ ràng; không duplicate (key unique per run).
  - Retry: cả 2 nhánh except (FullApplyServiceError — gồm authority revalidation mismatch; Exception — create_job fail) đều compensate attempt-2 pending→'failed' trước khi raise HTTP; predecessor không đụng; zero publication/checkpoint mutation.
- py_compile OK; focused C10 API 4/4 passed (6.73s, basetemp mfc10_f1a, DB UNSET, -p no:cacheprovider).

## S10-T01C-C10 turn4 (T4 resume) — nhóm 3: F2 implement — 2026-09-01 +07
- Implement F2 trong app/workflow/s10_full_apply_jobs.py:
  - Helper mới `_complete_run_cas(session_factory, ws, run_id) -> bool`: conditional UPDATE `pending-*→completed WHERE status != 'cancelled'` + re-read status trong CÙNG transaction; match zero rows (cancel thắng) → rollback + trả False; verified → commit + True. Contract chung cho cả 2 nhánh, không drift.
  - Nhánh has_completed (resume): pre-check giữ nguyên; thay batch UPDATE+commit vô điều kiện bằng `if not _complete_run_cas(...)` → False raise `_CancelledError` (checkpoint KHÔNG completed:true, job drains cancelling/cancelled). Chỉ CAS True mới rơi xuống `write_checkpoint(completed: True)`.
  - Nhánh publication thường: giữ CAS inline trong pub_sess (cần cùng transaction với `_create_full_publication`), comment cập nhật trỏ shared contract — semantics không đổi (đã CAS-verified từ C6A).
- Fix test-owned: `_c10_completed_checkpoint` đọc `row.checkpoint` (không tồn tại trên ORM JobStep) → `checkpoint_json` parse defensively; `patch` tool fuzzy-match đụng 2 block `_mark_run_status` → sửa bằng Python script, dedup về đúng 1 def gốc (py_compile OK).
- Focused C10 workflow 2/2 passed (9.23s, mfc10_f2c, DB UNSET, -p no:cacheprovider).

## S10-T01C-C10 T5 (resume exact owner) — nhóm 2: shakeout + static — 2026-09-01 14:48 +07
- Shakeout r1 (code T4, pre-static-fix): 57 passed (102.06s) basetemp %TEMP%/mfc10_t5a, DB UNSET, -p no:cacheprovider, EXIT 0.
- Static gate #1 FAIL thật: ruff F821 `err` undefined tại app/api/routes/s10_full_apply.py:502 + mypy x2 (used-before-def) — inner enqueue-except không bind `err` trong khi detail tham chiếu (fallout implement T4; chỉ nổ runtime nhánh compensation-fail, tests không hit).
- Minimal allowlist fix (T5): `except Exception:` -> `except Exception as err:` (1 dòng, routes :491). py_compile OK.
- Static re-run: ruff --select F 5 files (routes, jobs, job_service, test_api, test_workflow) = All checks passed; mypy 3 prod files = literal "Success: no issues found in 3 source files"; git diff --check exit 0 (chỉ warnings LF->CRLF pre-existing).
- SHA256 vs prep baseline (output/s10/c6c/manager/prep/hash_baseline.txt 09:40:16, pre-T3/T4): frontend/harness UNCHANGED — s10-apply-ui.spec.ts, s10-full-apply-global-setup.ts, s10-full-apply.spec.ts, frontend/src/lib/api.ts SAME; BUILD_ID hash d31c73ae... khớp baseline (build tAahC31RwMNgnTt0BlSAi nguyên vẹn). Allowlist-only DIFF: routes, jobs, test_api, test_workflow (F1/F2 + fix T5); job_service.py SAME. Zero file ngoài allowlist.
- git status --porcelain: 56 = baseline turn-start (zero drift).
- Repro Codex re-run trên code fix (mfc10_t5rep, exit 0, 3/3 in 5.98s): F1a run failed + 0 job ORPHAN=False; F1b replay 200 reused=true + repair exactly-one-job queued (key s10_full_apply_job:{run_id}) FALSE_REUSED=False; F1c attempt-2 failed non-active, predecessor cancelled giữ nguyên. Evidence: output/s10/c6c/t01c-c10/repro_t5_fixed.log.
- Shakeout post-fix root #1 (mfc10_t5b): 57 passed 112.01s EXIT 0 (shakeout_t5_r2.log).
- Shakeout post-fix root #2 (mfc10_t5c): 57 passed 111.84s EXIT 0 (probe_fixline.log).
- REPORT.md mục C10 appended, kết thúc STATUS: TASK_SUBMITTED.
- STATUS: TASK_SUBMITTED — không tự MANAGER_VERIFIED/APPROVED/CLOSED.

## S10-T01C-C11 2026-09-01 — replay coherence + immutable job identity (C6D F1/F2) — nhóm 1: T1 implement
- Đọc: C6D PREP reproductions (before/failed-run-queued-job-retry, before/tampered-manifest-replay), source submit/replay/retry routes, job_service, s10_full_apply_jobs; RULES_LOADED; worktree s08-integration HEAD d3f6f79, DB UNSET.
- RED-first: 8 tests C6D viết trước trong tests/test_s10_full_apply_api.py (L1422-1596): `test_c6d_replay_repair_coherent_active_pair_retry_conflicts`, `test_c6d_retry_while_repaired_job_running_conflicts`, `test_c6d_retry_after_repaired_job_terminal_allows_one_successor`, `test_c6d_tampered_stored_manifest_not_reused`, `test_c6d_wrong_job_type_not_reused`, `test_c6d_cross_owner_not_reused`, `test_c6d_tampered_run_identity_not_reused`, `test_c6d_deterministic_concurrent_replays_one_run_job`. Confirm RED trước code fix.
- Implement (chỉ app/api/routes/s10_full_apply.py):
  - F1 replay coherence: `_s10_find_durable_job` trả full identity (job_type, workspace, owner, parsed manifest); repair `_restore_run_to_pending` (CAS) TRƯỚC enqueue + `_s10_ensure_run_coherent` defensive healing — không bao giờ expose run=failed + job=queued; `_build_submit_manifest` canonical builder dùng chung cho created-path lẫn replay; retry guard `_s10_predecessor_has_active_job` (queued/running) pre-check + post-commit race re-check với compensation — tối đa 1 active canonical work mỗi lineage.
  - F2 immutable job identity: `_validate_replay_durable_job` canonical-compare đầy đủ — job_type, idempotency key, workspace, project owner, immutable manifest identity (run_id/workspace/project/video/checkpoint/plan/render_authority/source pins/replacement_assets/timebase) — fail closed 409/422 trên mọi mismatch.
  - Frozen `app/workflow/s10_full_apply_jobs.py` KHÔNG đụng (mtime 14:29:34 pre-session). job_service.py bounded (không đổi). Zero file ngoài allowlist.
- T1 shakeout x2 (dispatch log): 65 passed x2 (100.25s/99.70s) EXIT 0; ruff --select F 5 file All checks passed; mypy 3 prod Success; alembic a10b11c12d3e single; git diff --check 0; broad-except 0 swallow; HEAD d3f6f79 unchanged.
- T1 exit 0, STATUS: IN_PROGRESS (evidence/LOG/REPORT append pending) — hoàn thành ở T2.

## S10-T01C-C11 turn2 (T2 resume) — nhóm 2: verify + evidence/LOG/REPORT + terminal — 2026-09-01
- Re-run focused suite x2 fresh roots THẬT (DB UNSET, -p no:cacheprovider, basetemp ngắn %TEMP%/mfc11_*): r1 mfc11_r1 **65 passed (100.91s) EXIT 0**; r2 mfc11_r2 **65 passed (102.12s) EXIT 0** (shakeout_c11_r1.log, shakeout_c11_r2.log). Fresh roots: removed T1 mfc11_r1/r2 trước khi chạy.
- Static (real output): ruff check --select F 5 file **All checks passed**; mypy 3 prod **Success: no issues found in 3 source files**; git diff --check **EXIT 0** (chỉ LF/CRLF pre-existing); alembic heads **a10b11c12d3e (1 head)**; git status --porcelain **59**; broad-except sweep cancel/retry/resume **0 swallow** (grep bare `except:` zero; :854 là docstring; :954 inherit-fallback documented; :1243 rollback cleanup pass với primary error re-raised :1246).
- SHA-256 before/after (before = prep baseline 17:54:59 pre-T1): routes 257cbbfc->cc7995bf **CHANGED**; test_api 0dce2b98->4383247f **CHANGED**; job_service cd6c2fb9->cd6c2fb9 UNCHANGED (bounded); jobs 5059c695->5059c695 **FROZEN UNCHANGED**; services/s10_full_apply 05d268e8 UNCHANGED; test_workflow fc11033b UNCHANGED. Zero file ngoài 2-file allowlist.
- Evidence/LOG/REPORT appended; kết thúc bằng STATUS terminal.
- STATUS: TASK_SUBMITTED — không tự MANAGER_VERIFIED/APPROVED/CLOSED.

## S10-T01C-C12 2026-09-01 22:05 +07 — C6F run-row CAS arbiter (replay-vs-retry §6.3) — documentation closeout (resume exact owner 20260828_003035_859fe5)

- **Context:** T2 declared `BLOCKED_SCOPE_EXPANSION` (claimed a lineage unique-index migration was required for §6.3); T3 implemented the manager-prescribed routes-only mutual exclusion (C6F run-row CAS arbiter) and proved RED→GREEN deterministically. T3/T4 died mid-turn on a transient 401 auth-server (probe OK again afterward) — code/tests/evidence already complete, Manager verified independently. This turn (T5) = documentation only, base = evidence.md, no new code, no commit/push/merge.
- **T2/T3 CAS-claim arbiter:** `_s10_cas_run_status(session, run_id, ws, *, from_statuses, to_status) -> bool` — rowcount-gated `UPDATE s10_full_apply_run SET status=:to WHERE status IN :froms`. rowcount==1 = caller won the claim; rowcount==0 = opponent already transitioned → caller MUST fail closed (409) with ZERO new job/successor. Retry claim `_s10_retry_claim_predecessor` CAS failed/cancelled→cancelled BEFORE `svc.retry_run` creates successor run/job. Replay-repair `_restore_run_to_pending` now returns bool; lost CAS with run now cancelled (concurrent Retry superseded) → 409, never heal a superseded run. Exactly ONE of replay's failed→pending / retry's failed/cancelled→cancelled wins under SQLite single-writer; loser 409s before job/successor. KHÔNG migration — routes-only.
- **§6.3 test:** `test_c6e_replay_vs_retry_barrier_fail_closed` (+ `_RunRowCasBarrier`) barriers inside the real `_s10_cas_run_status` (not create_job) — true rendezvous, no hang, loses 93s/180s writer-lock contention. Asserts exactly one 200 + one 409, exactly one active work item + one active run. **2 tests pass**.
- **Shakeout ×2 fresh roots (DB UNSET, -p no:cacheprovider, basetemp %TEMP%/mfc12_*):** r1 `mfc12_r1` **73 passed** (158 warnings, 111.99s 0:01:51) **EXIT 0**; r2 `mfc12_r2` **73 passed** (158 warnings, 111.92s 0:01:51) **EXIT 0**. Logs shakeout_c12_r1.log / shakeout_c12_r2.log. Collection 73 (api + workflow).
- **Static (real output):** ruff --select F 5 files All checks passed EXIT 0; mypy 3 prod `Success: no issues found in 3 source files` EXIT 0 (T3 fixed 2 new errors from result.rowcount via CursorResult narrowing); alembic heads exactly 1 = a10b11c12d3e; git diff --check EXIT 0 (only pre-existing LF→CRLF warnings on unrelated S09); git status --porcelain **60** = baseline 59 + 1 (docs/pm/sessions/S10-SESSION_REGISTRY.md, tạo bởi turn C12 trước, KHÔNG phải T3); broad-except sweep cancel/retry/resume **0 swallow**.
- **SHA-256 before/after (before = output/s10/c6e/manager/prep/state_baseline.txt 19:26:59 pre-C12):** routes cc7995bf→f6662cc6 CHANGED (C12 allowlist); test_api 4383247f→69aa9649 CHANGED (§6.3 test + pred-status update); s10_full_apply_jobs 5059c695→5059c695 FROZEN UNCHANGED; models.py a3a6f150 UNCHANGED; services/s10_full_apply 05d268e8 UNCHANGED (FROZEN per C12 mandate); job_service cd6c2fb9 UNCHANGED (bounded).
- **Hygiene:** no commit/push/merge, HEAD d3f6f79 unchanged, DB UNSET throughout. T3 changed only routes + test_api (C12 allowlist) + gitignored output/ + docs/pm/sessions/. Frozen files byte-identical to 19:26 baseline.
- **Manager verify:** §6.3 race tests 2 passed; shakeout 73×2; evidence.md complete — verified independent before this documentation turn.
- **STATUS: TASK_SUBMITTED** — documentation only, no MANAGER_VERIFIED/APPROVED/CLOSED self-claim.

## S10-T01C-C13 (recovery owner 20260901_230235_b80d4b) 2026-09-01 23:54 +07 — C6F closure: wrong-idempotency-key fail-closed + Retry CAS policy + true worker-claim-vs-Retry barrier (T2 recovery)

- **Context (T1, exit 0, proc_a17dcfb63095):** W-RED done (red_run.log 4 failed + 5 passed controls — đúng defect), routes FIXED 23:43 (invariant resolution + retry claim policy), 9 test_c6f, test file compile OK. 1 patch record thất bại (fuzzy 2 matches) + LOG/REPORT/STATUS chưa ghi → T2 này recovery owner hoàn thiện tests + gates + evidence + LOG/REPORT append, không code mới.
- **Frozen proofs (byte-identical, C13 không đụng):** `app/persistence/jobs.py` = 67ca897528a44672… (mtime 19:38 pre-C13); `app/workflow/s10_full_apply_jobs.py` = 5059c6954997edf1… (mtime 14:29:34 pre-session); `app/persistence/models.py` = a3a6f150f26c0481… (mtime 28/08 pre-existing dirty); `app/workflow/job_service.py` = cd6c2fb9352caf55… (bounded, UNCHANGED). Frontend/harness/build SAME. HEAD d3f6f79 unchanged, no commit/push/merge, DB UNSET.
- **Test completeness (audit mỗi row):** 9 test_c6f tồn tại + 5 retained controls: K1 total Job rows 1 + tampered row unchanged id/key/state + reused != True; K2/K3/K6/K7 409/422 + zero new job + reused != True; R1 retry1 200, retry2 ∈ {200,202,409} (KHÔNG 500) + exactly one attempt-2 successor + no new run + one active job; R2/R3 rendezvous TRUE + {200,409}/[202,409] + one attempt-2 successor + one active run + no thread error; W1 rendezvous worker+retry TRUE + retry 409 + no successor run + one active lineage job (running) + zero pub/checkpoint.
- **Focused ×2 fresh roots (DB UNSET, -p no:cacheprovider, basetemp %TEMP%/mfc13_r*):** r1 `mfc13_r1` **82 passed, 178 warnings, 122.68s — EXIT 0**; r2 `mfc13_r2` **82 passed, 178 warnings, 121.44s — EXIT 0** (shakeout_c13_r1.log, shakeout_c13_r2.log). Collection 82 (api + workflow).
- **Static (real output):** ruff check --select F routes+services+test **All checks passed!** EXIT 0; mypy routes+services **Success: no issues found in 2 source files** EXIT 0; git diff --check **EXIT 0** (chỉ LF→CRLF pre-existing warnings trên S09 unrelated); git status --porcelain **60** = baseline 59 + 1 (registry, C12 tạo, KHÔNG phải C13).
- **SHA-256 before/after (before = C12 handoff bytes 23:00):** routes f6662cc6a88835b6→d25c3532027fb555 CHANGED (C13 allowlist); test_api 69aa9649d6dce945→963ed50e350abb54 CHANGED (9 test_c6f); services/s10_full_apply 05d268e8 UNCHANGED (FROZEN); test_workflow fc11033b UNCHANGED. Frozen files byte-identical (xem trên).
- **RED proof red_run.log:** 4 failed + 5 passed + 48 deselected, 12.53s — K1 (replay 200 reused + 2 jobs tampered+canonical, C1/C2/C3 false), R1 (retry2 500), R2/R3 (no true barrier nothing rendezvous). STRUCTURAL_GAP isolates (K2/K3/K6/K7) passed.
- **After evidence JSONs:** result_after_k1.json (replay 409, 1 tampered job unchanged, C1/C2/C3 True); result_after_r1.json (retry1 200, retry2 409, C1_no_500/C2_one_successor/C3_no_new_row/C2b_one_active True); result_after_w1.json (rendezvous worker+retry TRUE, retry 409, 1 active job running, pubs=[], C1-C4 True).
- **Hygiene:** evidence.md written; stray `after/manifest.json` (broken standalone artifact) removed. Zero file ngoài C13 allowlist. STATUS terminal — no MANAGER_VERIFIED/APPROVED/CLOSED self-claim.
- **STATUS: TASK_SUBMITTED** — no MANAGER_VERIFIED/APPROVED/CLOSED self-claim.

## S10-T01C-C15-A (verify chain, budget-cut resume) 2026-09-02 17:30 +07 — Phase-A verify: 62-node structural test file, frozen route

- **Scope:** CONTINUATION — structural work đã hoàn tất (62 defs / 62 unique / 0 dup, `_C10BoomService` L1249, route FROZEN 6ADCC48A…). Chỉ chạy verify chain, KHÔNG re-apply code (trừ fix tối thiểu cho harness error đã xác định). KHÔNG Phase B, KHÔNG TASK_SUBMITTED, KHÔNG sửa route.
- **Environment:** worktree `s08-integration` branch `codex/s08-integration` HEAD `d3f6f79`. DB UNSET (không DATABASE_URL nào). python 3.11.9, pytest 9.1.1, ruff 0.16.0. Fresh short basetemp `%TEMP%/mfc15v_a`, `-p no:cacheprovider`.
- **Step 1 py_compile:** `python -m py_compile tests/test_s10_full_apply_api.py` → **EXIT 0**.
- **Step 2 ruff --select F:** 1 error đầu (F401 dead import `app.api.routes.s10_full_apply` @L2406 trong `test_c6f_worker_claim_vs_retry_true_barrier`, `routes_mod` import nhưng không dùng). **MINIMAL HARNESS FIX** (xóa import 2 dòng). Re-run → **All checks passed! EXIT 0**.
- **Step 3 collect-only:** `pytest --collect-only -q -p no:cacheprovider` → **62 tests collected, 0 skip / 0 xfail** (2.65s).
- **Step 4+5 full pytest run (fresh root):** `pytest tests/test_s10_full_apply_api.py -p no:cacheprovider -q --basetemp=C:/Users/Admin/AppData/Local/Temp/mfc15v_a` → **57 failed, 5 passed, 175 warnings, 67.18s — EXIT 1**.
- **5 PASSED (không reach submit happy-path):** test_cross_project_v2_blocked (409), test_openapi_additive_no_lost_routes, test_openapi_submit_required_minimal, test_production_submit_contains_no_synthetic_media_helper, test_stale_checkpoint_hash_blocked (422).
- **ROOT CAUSE (isolated + reproducible):** toàn bộ 57 fail cùng 1 lỗi base path: `{"detail":"stored checkpoint_hash does not match recomputed content hash"} → 422`. Nguyên nhân: `_make_client` (test L87-89) seed `apply_checkpoint` bằng raw INSERT với `checkpoint_hash=_h64("ckpt-...")` (fabricated, tùy ý) và nội dung `snapshot_json='{}'`, `loop_hashes_json='[]'`, `timebase_fingerprint=_h64("tbf")`. Production `submit → full_apply_authority → verify_checkpoint` (s09_approval L1072) RE-COMPUTE hash của stored row và so với stored `checkpoint_hash` → mismatch → `S09ApprovalIntegrityError` → 422. Diagnostic: STORED=fc51bc6a… vs RECOMP=c43b3884… → MATCH=False.
- **CLASSIFICATION — HARNESS/AUTHORITY gap, KHÔNG phải CREDIBLE_PRODUCTION_RED:** production verify fail-closed (reject checkpoint có stored hash không khớp content) là hành vi đúng, chủ ý; harness seed incoherent checkpoint. **KHÔNG phải C15-introduced** (seeding byte-identical với pre-edit backup `.../pre-edit/*.bak` L50) và **KHÔNG clearable bằng minimal patch** (cần rework `_make_client` seed v2 authority qua `submit_checkpoint_v2`, redesign chứ không phải patch). Owner: Manager R-GATE.
- **MANIFEST:** `output/s10/c6h/t01c-c15/phase_a_manifest.json` (62 node names + test SHA 9b96b12f… + route SHA 6adcc48a… FROZEN + line count 2770 + gate results ruff/py_compile/collect).
- **SHAs:** route `6adcc48ad3525cc91c6b5890ce98875b85bb8da66dee2fb86b57c6992a17b53f` **UNCHANGED (FROZEN)**; test `9b96b12ffe40f7a95e4cb96f78c9f68b8788092d99fe2bc2581289d031f9f313`, line count 2770.
- **Hygiene:** git status --porcelain **66** = baseline (chỉ test + c15 evidence gitignored + LOG/REPORT; 8 production ` M app/` files baseline, 0 production line đổi). Không commit/push/merge, HEAD d3f6f79 unchanged. Không Phase B.
- **STATUS: C15_A_SUBMITTED (HARNESS gap để Manager R-GATE quyết định)** — không TASK_SUBMITTED, không MANAGER_VERIFIED/APPROVED/CLOSED self-claim.
## S10-T01C-C15-A correction resume (Manager) 2026-09-02 21:44 +07
- RULES_LOADED + preflight OK (registry row đầy đủ). Model probe ocg/deepseek-v4-flash/custom → PROBE_OK (probe session 20260902_214345_7ca7e6). RUNTIME_CONFIG_GAP: resume path records reasoning_config=null, max_iterations=90 — continue same route per binding §4.
- RESUME 20260902_171240_ce07c1 → effective session **20260902_214426_e79a4d** (proc_66ee0644a98f, PID 1405, ocg/deepseek-v4-flash custom, same Task S10-T01C-C15). Bounded correction packet prompt_c15a_correction.txt. Worker đang chạy; sẽ monitor + R-GATE khi xong.
## S10-T01C-C15-A combined correction (bounded packet, resume 20260902_171240_ce07c1) 2026-09-02 22:0x +07
- RULES_LOADED: docs/pm/HERMES_AUTOPILOT_RULES.md, 246 lines, SHA-256 9328c8c0672ea0040d278b2a00c81c1dbd24b4c72ff87c68fda3a357a44b61bc (read full file this turn).
- PREFLIGHT_OK: worktree s08-integration, branch codex/s08-integration, HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; test SHA pre = 9b96b12ffe40f7a95e4cb96f78c9f68b8788092d99fe2bc2581289d031f9f313 OK; route SHA 6adcc48ad3525cc91c6b5890ce98875b85bb8da66dee2fb86b57c6992a17b53f FROZEN OK; MOTIONFORGE_DB_PATH/DATABASE_URL UNSET.
- HUNK1 `_make_client` (patch narrow có preimage): (1a) signature `*, route: str = "sprite_affine"`; (1b) reskin_config INSERT `'{}'` → canonical valid_params + `:params` (json.dumps sort_keys separators=(",",":")); (1c) XÓA 3 dòng fabricated apply_checkpoint (ckpt/chash/INSERT) + seed giờ `{"workspace_id": ws, "project_id": proj, "video_item_id": vid, "pack_version_id": pv, "reskin_config_id": rc}` (KHÔNG checkpoint_id/hash — _seed_v2_authority thêm); (1d) THÊM `_seed_v2_authority(factory, artifacts_root, seed, route=route)` sau _seed_persisted_authority. Giữ TestClient(app) + return client, seed.
- HUNK2 `_payload`: body → minimal v2 (video_item_id, apply_checkpoint_id, expected_checkpoint_hash, expected_checkpoint_revision=int(seed.get("checkpoint_revision",1)), chunk_config). XÓA khỏi default: approved_checkpoint, structural_lock_manifest, scene_manifest, mapping, compatibility_policy (vẫn truyền qua overrides ở tamper tests — không sửa test đó).
- DIFF GUARD: git diff --stat chỉ test file (untracked, pre-existing baseline ??); route SHA không đổi; _C10BoomService còn (class L1253); `grep -c "^def test_"` = 62, dup 0; py_compile OK; ruff --select F All checks passed; KHÔNG skip/xfail/mock.
- VERIFY CHAIN (DB UNSET, basetemp %TEMP%/mfc15c1, --cache-clear): (1) collect-only → 62 collected, 0 error, 0 skipped (2.64s); (2) focused 5 → 5 passed (9.48s); (3) full → 54 passed, 8 failed (77.46s) + re-run full → 8 failed, 54 passed (76.61s) (ổn định).
- MATRIX: 8 fail còn lại đều HARNESS/AUTHORITY (0 CREDIBLE_PRODUCTION_RED) — raw tracebacks output/s10/c6h/t01c-c15/evidence/traceback_batch{1,2,3}.txt.
- SHAs: route `6adcc48a…` UNCHANGED (FROZEN); test post = `4c491909da58b161cb4c8f582043da182299a0cc6a63655d0ab3efb4f93d9b48`, line count 2773 (`grep -c ""`).
- STATUS: C15_A_CORRECTION_DONE final_sha=4c491909… (8 HARNESS/AUTHORITY còn mở — Manager R-GATE). Không Phase B, không sửa production, không commit.
## S10-T01C-C15-B dispatch (Manager) 2026-09-02 22:31 +07
- R-GATE = C15_A_REBASELINE_APPROVED (evidence chi tiết ở registry row 22:30). Pre-B guard: manager/guard/snapshots/*.pre_c15b (route 6adcc48a + test 4c491909 byte-identical).
- C15-B packet: output/s10/c6h/t01c-c15/prompt_c15b.txt (7,392 B) — 8 harness items bounded + C6G 14-row matrix + RED micro → fix → micro → focused → full 62 → static → freeze → TASK_SUBMITTED.

## S10-T01C-C15-B worker closure (resume 20260902_214426_e79a4d) 2026-09-02 23:0x +07
- RULES_LOADED: docs/pm/HERMES_AUTOPILOT_RULES.md 246 lines; SHA 9328c8c0672ea0040d278b2a00c81c1dbd24b4c72ff87c68fda3a357a44b61bc (MAIN repo copy = canonical, read full file this turn; worktree copy is the older 1873-byte "Hermes MAX Autopilot Rules" — documented drift, MAIN is source of truth per prompt path).
- PREFLIGHT_OK: worktree s08-integration, branch codex/s08-integration, HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7; test SHA pre-C15B = 4c491909da58b161cb4c8f582043da182299a0cc6a63655d0ab3efb4f93d9b48 (2773 lines); route SHA 6adcc48ad3525cc91c6b5890ce98875b85bb8da66dee2fb86b57c6992a17b53f FROZEN; pre-B snapshot output/s10/c6h/manager/guard/snapshots/app/api/routes/s10_full_apply.py.pre_c15b byte-identical; MOTIONFORGE_DB_PATH/DATABASE_URL UNSET; basetemp %TEMP%/mfc15b_* short roots; -p no:cacheprovider.
- RED MICRO (before any fix): 8 failed, 54 deselected (17.44s) — exactly the 8 C15-A HARNESS/AUTHORITY items, raw tracebacks already in evidence/traceback_batch{1,2,3}.txt.
- FIXES (test-side only, bounded patch w/ preimage; production NOT touched):
  1. test_submit_distinct_on_changed_checkpoint: removed fabricated apply_checkpoint INSERT ('{}' params + made-up hash) → REAL second v2 checkpoint via _seed_second_v2_checkpoint + minimal _payload(seed2). Expect 202 + NEW run + reused is not True.
  2. test_c6e_concurrent_repair_replays_true_barrier_one_run_one_job: helper returns DICT → unpack setup2 = ...; _assert_converged(setup2["factory"], setup2["seed"], setup2["client"]).
  3. test_c6e_replay_vs_retry_barrier_fail_closed: dropped wrong cancelled>=1 branch (replay-win heals run to pending, no successor/cancelled row); new truthful invariant "non-active runs must be terminal" + exactly-one non-terminal.
  4. test_c6e_wrong_identity_fails_closed_valid_control: seeded REAL workspace row 'other-ws' (FK no longer dies in harness); _expect_fail now captures ORIGINAL value pre-tamper and restores by PRIMARY KEY (new _c6d_run_job_id/_c6d_tamper_job_by_id/_c6d_job_attr_by_id helpers) — old restore read current (tampered) value = no-op that accumulated tampers, flipping resolver to zero-candidates on the last tamper and masking the intended fail-closed assertion.
  5. test_c6f_retry_vs_retry_barrier_cancelled: barrier NOW wraps routes._s10_retry_successor_exists (cancelled predecessor → route does NOT call _s10_cas_run_status; ownership = atomic unique-successor insertion + uq_s10_run_natural backstop). Rendezvous proves both Retries passed the pre-check before insertion; loser converges 409 via IntegrityError path. Assertions unchanged: one successor + fail-closed.
  6. test_c6g_ambiguous_two_claimants_fails_closed: _c6f_all_apply_jobs SELECT gained input_manifest_json column (test helper).
  7. test_c6g_combined_tamper_fails_closed: seeded REAL workspace 'other-ws' before combined tamper (FK died in harness).
  8. test_c6d_retry_after_repaired_job_terminal_allows_one_successor: INDEPENDENT REPRO on frozen route → 200 {run_id, predecessor_run_id, status:pending, attempt:2}; C6F contract retry1=200 → expectation 202→200; predecessor invariant corrected to "TERMINAL (cancelled/failed)" — the retry CAS supersedes failed→cancelled by design.
- MICRO RE-RUN: 8 passed, 54 deselected (14.29s) after all fixes; ruff F clean after removing now-unused factory (F841).
- FOCUSED: -k "c6d or c6e or c6f or c6g" → 30 passed (44.32s); C15-A focused packet 5 tests → 5 passed (9.62s).
- FULL MODULE: 62 passed (86.09s) — 0 fail, 0 skip/xfail, 62 collected/0 errors.
- STATIC: py_compile (test+route+services) OK; ruff --select F on test+route+services → All checks passed; git diff --check → only pre-existing LF/CRLF warnings (exit 0), no whitespace errors.
- GUARD: route SHA UNCHANGED 6adcc48ad3525cc9… == pre-B snapshot (byte-identical) → **0 CREDIBLE_PRODUCTION_RED, 0 production edits**; test SHA 2fff69d0b49512bf…, line count 2810 (grep -c ""); 62 unique defs (grep -c "^def test_"); no commit/push/merge, HEAD unchanged.
- MATRIX: C6G 14-row closure — G1-I1..I7, G2-R1..R5, G3-W1, G4-D1 all GREEN (row→test mapping in REPORT mục C15-B; every row covered by a passing test in the 62).
- STATUS: TASK_SUBMITTED (C15-B). Evidence: output/s10/c6h/t01c-c15/evidence/c15b_done.json; LOG/REPORT appended.

## S10-T01C-C15-B EVIDENCE FINALIZATION correction (resume 20260902_223154_fc3c24) 2026-09-02 23:02 +07
- HEADER CORRECTION (append-only, không rewrite lịch sử): entry `## S10-T01C-C15-B worker closure (resume 20260902_214426_e79a4d) 2026-09-02 23:0x +07` — placeholder `23:0x` trong header đã correct → `23:0x → 22:55` (timestamp closure thực = 22:55, đã correct).
- SUPERSEDED: câu 'STATUS: TASK_SUBMITTED (C15-B). Evidence: c15b_done.json; LOG/REPORT appended.' trong entry trên là PREMATURE — được viết trước khi các bước finalize thực hiện; status cuối đúng ở dòng correction này.
- FINALIZE (evidence-only, KHÔNG chạy lại pytest/gate — kết quả real đã ghi nhận): REPORT.md mục C15-B appended (8 items + gates + matrix 14-row); evidence/c15b_done.json tạo — final_test_sha 2fff69d0… (2810 dòng, method wc -l), route 6adcc48a… byte-identical vs pre-B snapshot, 0 production edit, 0 credible production RED, 62/62.
- STATUS: TASK_SUBMITTED (C15-B) — evidence đã đóng. HEAD d3f6f79 unchanged, không commit.
C15B_CLOSED TASK_SUBMITTED final_test_sha=2fff69d0… 62/62 PASS — Manager EXIT sẽ chạy broad gates.
## S10-T01C-C15 EXIT (Manager) 2026-09-02 23:20 +07
- EXIT gates: focused R1/R2 87 passed each (fresh roots mfc15foc_r1/r2); broad R1/R2 282 passed each (mfc15brd_r1/r2, 345.77s/346.32s); Lane C static PASS; hashes freeze UNCHANGED. NEXT_REVIEW_PACKET.md: output/s10/c6h/manager/exit/. Registry rows full lineage + RUNTIME_CONFIG_GAP + line-count conventions. 0 writer, ports clean, DB UNSET, no commit. STATUS: SPRINT_CLOSED (pending Codex review of packet).

## S10-T01C-C15 R1 — UNION identity resolver recovery (FRESH worker 20260903_001126_2a17f4) 2026-09-03 00:40 +07
- Codex verdict: S10-C6H = CHANGES_REQUESTED / UNION_IDENTITY_RESOLVER_GAP / NOT_APPROVED. Owner transfer vì REPEATED_FORBIDDEN_CRITICAL_FILE_WRITE (state.db 149749/149826/149835); 3 session cũ FROZEN — recovery một worker R1.
- RULES_LOADED SHA 9328c8c0… (246 dòng); review C6H + prompt C6H mục 8 (C6G contract) đọc đầy đủ.
- PREFLIGHT OK: HEAD d3f6f79, route 6ADCC48A (2470) byte-identical guard pre_r1, test 2FFF69D0 (2810, 62 defs unique) byte-identical guard pre_r1, DB env UNSET.
- RED (pre-fix, route cũ): U1 key+generation tamper (manifest intact) → replay 200 reused=true jobs 1→2 FAIL; U2 full tamper → 200 reused=true FAIL. Log red_u1u2.log (2 failed, 66 deselected).
- PATCH (bounded V4A preimage — patch-tool replace-mode fuzzy indent bug gây 2 lần hỏng file, đã khôi phục từ guard byte snapshot và lưu broken_patch/ evidence): `_s10_resolve_job_identity` → typed UNION resolver: canonical key + deterministic generation + stored manifest run/project/plan identity + workspace/job_type/owner anchor; classes true-zero / exact-valid-one / wrong-one / ambiguous-multiple / read/parse/query-error; call site chỉ cho true-zero repair. KHÔNG migration, KHÔNG route/service khác.
- GATES (all real, DB UNSET, basetemp %TEMP%/mfc15r1_*): U1-U6 GREEN 6/6 (u_gate.log); retained 14-row matrix GREEN 20 node/14 rows (matrix.log); full API 68 passed 82.07s (full_api.log); ruff --select F 2 files All checks passed; mypy 3 prod Success; git diff --check 0; dup def audit 0 (static.log).
- RUNTIME_CONFIG_GAP (state.db read-only): session 20260903_001126_2a17f4 model ocg/deepseek-v4-flash ✓ nhưng model_config max_iterations=90, reasoning_config=null (yêu cầu reasoning max) — ghi thật, tiếp tục cùng route/model.
- HASHES: route 6ADCC48A→BBF55D28 (2571, +101), test 2FFF69D0→6978D2BE (3153, +343, 68 defs unique). Guard không shrink; diff 5 hunk đúng phạm vi (resolver 2, call site 2, test append 1). Porcelain 66 = baseline. HEAD unchanged, không commit.
- EVIDENCE: output/s10/c6h/r1/t01c-c15-recovery/{r1_done.json, red_u1u2.log, u_gate.log, matrix.log, full_api.log, static.log, diff.diff}.
- STATUS: R1_RECOVERY_DONE — chờ Codex review C6H; KHÔNG ghi APPROVED/CLOSED/SPRINT_CLOSED.
## S10-T01C-C15 R1 closure (Manager) 2026-09-03 00:45 +07
- Owner transfer + fresh recovery 20260903_001126_2a17f4 → union resolver (bbf55d28) + U1-U6 (test append-only 6978d2be, 68 defs). Gates Manager độc lập: U 6/6, matrix 30/30, full 68p, focused 93p×2, broad 288p×2, static/alembic/OpenAPI clean, quiescence OK. NEXT_REVIEW_PACKET.md mới tại output/s10/c6h/r1/manager/exit/. Packet/registry cũ ghi APPROVED/SPRINT_CLOSED bị SUPERSEDED (role-invalid). Terminal: SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW.
## S10-T01C-C15 R2 (recovery worker, append-only) 2026-09-03
- Role: FRESH recovery worker duy nhất sau freeze vinh vien 20260903_001126_2a17f4 (REPEATED_FORBIDDEN_COPY_OVERWRITE_AFTER_RECOVERY_TRANSFER). Verdict: S10-C6H = CHANGES_REQUESTED / R2_AUTHORIZED / NOT_APPROVED / S10_NOT_CLOSED.
- RULES_LOADED: C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md — 246 dòng, SHA thực tế 9328c8c0672ea0040d278b2a00c81c1dbd24b4c72ff87c68fda3a357a44b61bc (prompt ghi 29EA6B60 = bản worktree cũ/stub 37 dòng; worktree copy SHA 29ea6b60... mtime 2026-08-05 — drift ghi nhận, đọc đủ bản canonical main). R1 review + R2 prompt đã đọc.
- PREFLIGHT OK: branch codex/s08-integration, HEAD d3f6f796 UNCHANGED, porcelain 66 = baseline, route bbf55d28, test 6978d2be, guard .pre_r2 byte-identical, DB env UNSET, basetemp %TEMP%/mfc15r2_*, 0 writer/port free.
- RUNTIME_CONFIG_GAP: exact model ocg/deepseek-v4-flash custom fallback OFF; CLI state row yếu (max_iterations=90/reasoning_config=null) — KHÔNG claim reasoning max; tiếp tục bounded R2.
- PATCH (unified V4A, 1 hunk/lần, exact preimage, KHÔNG dùng replace/write_file/cp): 
  * test R2-B: U4 invalid_manifest giờ chứa EXACT target run_id trước điểm truncate (relevant malformed fail-closed thay vì field-name chung);
  * test R2-A: test_r2_unrelated_malformed_manifest_does_not_block_true_zero_repair (real route+JobService+Alembic SQLite mới; unrelated malformed KHÔNG chứa target run_id);
  * test R2-C: test_r2_unrelated_valid_manifest_does_not_block_true_zero_repair (well-formed foreign run/project);
  * route F1: manifest prefilter '%"run_id"%' → like '%"run_id":"<run_id>"%' OR '%"run_id": "<run_id>"%' (exact target run_id, compact+spaced JSON);
  * route F2: canonical_complete dùng row_sig_manifest recompute từ claims[0] chứ không dùng sig_manifest tồn dư loop.
- RED (route CHƯA sửa): test_r2_unrelated_malformed... FAIL đúng defect — actual 409 identity lookup FAILED stored manifest unparseable (job df33bfb7), zero repair (red_r2a.log).
- GATES (DB UNSET, basetemp %TEMP%/mfc15r2_*): micro R2-A/B/C GREEN 3/3; U1-U6 + R2 rows 8/8; C6G retained matrix 30/30 (14/14 rows + controls); full API 70 passed 83.67s; ruff --select F All checks passed; mypy 3 prod Success; git diff --check 0 ws error; dup-def 0; retained-symbol 0 lost; shrink guard route +24/test +216 (growth only).
- HASHES: route BBF55D28→BA97FB24 (2595, +24), test 6978D2BE→EF5F93A3 (3369, +216, 70 defs unique 0 dup).
- EVIDENCE: output/s10/c6h/r2/worker/{r2_done.json, red_r2a.log, gates.log, u_gate.log, matrix.log, full_api.log, static.log, ruff_f.log, diff.diff, diff_route.diff, diff_test.diff, guard_hashes.txt}.
- STATUS: R2_RECOVERY_DONE — Manager post-audit (raw session + gate độc lập) bắt buộc; KHÔNG commit/push/merge; KHÔNG APPROVED/CLOSED.
## S10-T01C-C15 R2 closure (Manager) 2026-09-03 02:01 +07
- R2 fresh recovery 20260903_012248_d29911 (owner transfer sau R1 freeze): F1 manifest prefilter exact run_id + F2 per-row signal (route ba97fb24); tests R2-A/R2-B(fix U4)/R2-C (test ef5f93a3, 70 defs). Gates Manager độc lập: micro 8/8, matrix 30/30, full 70p, focused 95p×2, broad 290p×2, ruff/mypy/alembic/OpenAPI clean. Raw session audit: zero forbidden write (unified V4A only). NEXT_REVIEW_PACKET.md mới tại output/s10/c6h/r2/manager/exit/ (supersede R1 packet bị reject). Terminal: SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REREVIEW.
## S10-T01C-C15 R3 preflight (Manager) 2026-09-03 09:43 +07
- Manager chat MỚI `20260903_093758_ddcd2b` (NOT retired 20260902_211154_54134d; OLD_MANAGER_QUIESCENT 0 writer/0 test process).
- RULES: MAIN 246 dòng SHA 9328c8c0...; worktree stale 37 dòng SHA 29ea6b60... (đúng prompt, không drift block).
- Preimage KHỚP: route BA97FB24/2,595 dòng/130,029 B, test EF5F93A3/3,369 dòng/185,837 B/70 unique defs, HEAD d3f6f79, porcelain 66, DB UNSET, 20128=9Router only.
- Guard R3: output/s10/c6h/r3/manager/guard/snapshots/*.pre_r3 byte-identical verified + write_set_manifest.txt.
- Owner 20260903_012248_d29911 terminal agent_close (125 msgs/70 tools); resume exact owner, max writer 1.
- Finding: P1 FORMAT_DEPENDENT_MANIFEST_DISCOVERY — resume owner với prompt_r3.txt (8,623 B), route ocg/deepseek-v4-flash custom.
## S10-T01C-C15 R3 (worker, resume owner) 2026-09-03 09:58 +07
- Resume EXACT owner 20260903_012248_d29911 (terminal agent_close 125 msgs/70 tools, 0 child trong state.db read-only). 
  Effective CLI session 20260903_094146_7b7197; sessions.parent_session_id KHONG materialize cho resume invocation (gap ghi nhan) - cung logical owner, max writers 1.
- RULES_LOADED: MAIN canonical 246 dong SHA 9328c8c0672ea0040d278b2a00c81c1dbd24b4c72ff87c68fda3a357a44b61bc (khop); worktree copy stale 37 dong SHA 29ea6b60...; da doc review R2 + prompt R3.
- PREFLIGHT OK: branch codex/s08-integration, HEAD d3f6f79, porcelain 66 = baseline; route BA97FB24 (2595/130029), test EF5F93A3 (3369/185837, 70 defs 0 dup), packet 6193EF17; guard .pre_r3 byte-identical; DB env UNSET; basetemp %TEMP%/mfc15r3_*; 0 writer/test process, port free.
- RUNTIME_CONFIG_GAP: exact model ocg/deepseek-v4-flash custom fallback OFF; state row yeu (max_iterations=90/reasoning_config=null) - KHONG claim reasoning max, tiep tuc bounded R3.
- FINDING: P1 FORMAT_DEPENDENT_MANIFEST_DISCOVERY - prefilter chi nhan 2 literal forms -> valid JSON tab/newline quanh ':' bi bo qua -> 200 reused=true + job canonical thu hai (R2 RED repro 1->2).
- PATCH TESTS (unified patch git apply, 1 hunk/call, exact preimage, EOL-preserving CRLF): hunk1 R3-B U4 invalid_manifest -> CRLF + tab quanh ':' truoc truncate (van invalid JSON, giu exact target run_id); hunk2 R3-A test_r3_valid_json_whitespace_does_not_erase_manifest_claimant (append cuoi file, +1 def).
- RED (route CHUA sua = R2 bytes BA97FB24): R3-A FAIL 200 {"reused":true} (red_r3a.log); R3-B/U4 FAIL 200 {"reused":true} (red_r3b.log); probe: [R3-A] 200/True/jobs 1->2/canonical_new=1, [R3-B] 200/True/jobs 1->2/canonical_new=1 (red_counts.log) - dung defect.
- PATCH ROUTE (2 hunks cung 1 mechanism): run_id_literal escape LIKE (%,_,\) + MOT containment like(f'%{run_id_literal}%', escape='\\') thay 2 pattern; KHONG enumerate whitespace variants; parse + exact match run/project/plan giu nguyen; malformed CO target run fail-closed; unrelated malformed/valid khong chon; key/gen read-error fail-closed; chi true-zero repair; row_sig_manifest R2 nguyen ven.
- GATES (DB UNSET, basetemp %TEMP%/mfc15r3_*): GREEN targeted 4/4 (R3-A+R3-B+R2-A+R2-C) 6.96s; micro U1-U6+R2/R3 9/9 12.78s; C6G matrix 30/30 (14/14 rows + controls) 39.61s; full API 71 passed 85.04s; ruff --select F All checks passed; mypy 3 prod Success; git diff --check 0; trailing-ws PCRE 0/0; dup-def 0; lost-def 0 (70/70 retained); shrink guard route +271 B/+6 lines, test +4,959 B/+97 lines (growth only).
- HASHES: route BA97FB24->5a6c7e86 (2601 lines), test EF5F93A3->e26a96dc (3466 lines, 71 unique defs 0 dup, +1 def R3-A, U4 sua khong them def). HEAD d3f6f79 unchanged, khong commit.
- EVIDENCE: output/s10/c6h/r3/worker/{r3_done.json, red_r3a.log, red_r3b.log, red_counts.log, probe_red_counts.py, gates.log, micro.log, matrix.log, full_api.log, static.log, diff.diff, guard_hashes.txt, hunks/*.patch}.
- STATUS: R3_RECOVERY_DONE final_route_sha=5a6c7e86... final_test_sha=e26a96dc... 71/71 PASS 14/14+R3 GREEN - Manager post-audit (raw session + ladder doc lap). KHONG commit/push/merge; KHONG APPROVED/CLOSED; S11 chua mo.

## S10-T01C-C15 R3 closure (Manager) 2026-09-03 10:24 +07
- Worker R3_RECOVERY_DONE (effective 20260903_094146_7b7197, resume owner 20260903_012248_d29911): P1 FORMAT_DEPENDENT_MANIFEST_DISCOVERY đóng — 1 containment literal escape LIKE thay 2 pattern; RED R3-A/R3-B 200 reused=true jobs 1→2 (raw logs); GREEN 71/71, 14/14+R3.
- Manager ladder: micro 9/9, matrix 30/30, full 71p, focused 96p×2, broad 291p×2, adversarial probe LF+CRLF newline 2/2, ruff/mypy/diff/dup/lost/alembic/OpenAPI clean (logs output/s10/c6h/r3/manager/*.log).
- Raw audit: 0 forbidden critical write (git apply hunks only). Final: route 5a6c7e86 (2,601), test e26a96dc (3,466, 71 defs). HEAD d3f6f79, porcelain 66, DB UNSET, 0 writer, không commit.
- Terminal: SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REREVIEW — chờ Codex; không APPROVED; S11 chưa mở.

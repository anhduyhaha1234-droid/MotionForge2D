# S10-T01A — REPORT — Durable FullApply domain + checkpoint contract

- Task: S10-T01A — Durable FullApply domain + checkpoint contract
- Status: TASK_SUBMITTED
- Model: meta — reasoning max — fallback OFF
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration — branch codex/s08-integration — HEAD d3f6f796558aa9c7247da7d51e7d34e65b56cdf7 (d3f6f79)
- MAIN read-only: C:/Users/Admin/MotionForge2D
- Preflight: MOTIONFORGE_DATABASE_URL UNSET, migrations head b3c4d5e6f7a9 before, J1-v4 frozen renderer intact
- Date: 2026-08-28 00:55 +07

## Outcome
Dau kien domain/persistence/migration cho apply run, chunk state, publication va immutable approval linkage — durable, fail-closed, deterministic, resume-safe.

## Files changed (exclusive write scope only)
- app/persistence/models.py (append, +~280 lines) — 3 status enums + S10FullApplyRun / S10FullApplyChunk / S10FullApplyPublication + relationships + __all__
- app/persistence/s10_full_apply.py (new, ~560 lines) — S10ApplyRepository, record dataclasses, fail-closed validators, idempotency/natural-key replay, artifact/.partial guards, chunk overlap/attempt/resume, publication linkage
- app/schemas/s10_full_apply.py (new, ~130 lines) — strict _StrictModel extra=forbid for run/chunk/publication requests + responses
- migrations/versions/a10b11c12d3e_s10_full_apply_domain.py (new, ~370 lines) — revision a10b11c12d3e, down b3c4d5e6f7a9, 3 tables, fail-closed downgrade, PRAGMA checks
- tests/test_s10_full_apply_domain.py (new, 15 tests) — 5 binary bullets coverage
- tests/test_s10_full_apply_migration.py (new, 6 tests) — head/chain/parity/roundtrip/refuse/FK/survive
- docs/pm/sessions/S10-T01A-durable-domain/TASK.md, LOG.md, REPORT.md (this file)
- output/s10/t01a/pytest-run-1.log, pytest-run-2.log, ruff.log, mypy.log, alembic-head.log, prompt.txt (isolated evidence)

## Forbidden paths untouched
- No renderer J1 files, no frontend, no app/api/app.py, no S11/S13, no data/**, no channels.json — verified via git status.

## Implementation summary
- **Migration a10b11c12d3e** — child of live head b3c4d5e6f7a9 — one live head after upgrade. 3 tables: run (FK RESTRICT to workspace/project/video/checkpoint, plan_id/hash 64 hex, checkpoint hash/revision pin, frame_count, chunk_config_json, idempotency/natural_key UNIQUE workspace WHERE NOT NULL, revision CAS), chunk (FK RESTRICT to run/workspace, chunk_index/order_index, shot_id, layer_id/object_role_id, core range + overlap_before/after, content_hash 64, state, attempt, artifact FK, verified bool, natural_key/idempotency, UNIQUE run+chunk+attempt), publication (FK RESTRICT to run/artifact/checkpoint, content_hash 64, frame_count, frame_metadata_json, checkpoint pin copy, state, natural_key/idempotency, UNIQUE run+content_hash). All CHECKs real reflection metadata. Downgrade fail-closed if ANY row in ANY of the 3 tables before any DDL.
- **Models** — appended S10 enums + 3 ORM classes to app/persistence/models.py; no existing model drift; CRLF preserved; git autocrlf managed.
- **Repository** — S10ApplyRepository: workspace/project/video ownership, checkpoint hash/revision pin + cross-project guard before any write; artifact ready/.partial check at publication + re-check at complete(); idempotency/natural-key/lineage dedupe on all three aggregates; chunk core range/overlap max/frame_count bounds, attempt sizing, verified hash gate for resume.
- **Schemas** — CreateFullApplyRunRequest / CreateChunkRequest / MarkChunkVerifiedRequest / CreatePublicationRequest + S10RunOut/ChunkOut/PublicationOut with extra=forbid.

## Binary acceptance evidence
1. **One live migration head; forward + downgrade/upgrade round trip; S09 rows survive:**
   - Head after upgrade: a10b11c12d3e (single head, verified via alembic heads/history).
   - Empty-graph round trip byte-identical (upgrade→downgrade→upgrade, PRAGMA integrity ok, fk empty), proven on isolated temp DB file (alembic upgrade head / downgrade b3 / upgrade head).
   - Downgrade with ANY row refuses atomically (RuntimeError refusing to downgrade, row + revision + S10 tables untouched, still at a10b11c12d3e).
   - Existing S09 rows (apply_checkpoint + s09_correction) survive downgrade to PRE and re-upgrade (FK RESTRICT preserved, revision pins intact).
   - FK RESTRICT on checkpoint delete when run references it (IntegrityError).

2. **Immutable FK linkage to ApplyCheckpoint; stale/cross-project rejected:**
   - create_run requires valid checkpoint FK (NotFound if missing).
   - Wrong checkpoint_hash → S10ApplyCheckpointStaleError before any write.
   - Wrong checkpoint_revision (reskin_config_revision) → stale error.
   - Checkpoint in different project than run → S10ApplyOwnershipError (cross-project rejected).

3. **Durable states + uniqueness/idempotency prevent duplicate lineage:**
   - Run: idempotency_key UNIQUE workspace WHERE NOT NULL + natural_key UNIQUE workspace WHERE NOT NULL; same keys replay same row (created=False); same natural_key dedupes; status enum CHECK-bound.
   - Chunk: natural_key + idempotency UNIQUE workspace; same keys replay; lineage via UNIQUE(run,chunk,attempt) allows attempt retries.
   - Publication: natural_key + idempotency + lineage dedupe (run,content_hash) all return same row.

4. **No completed publication can reference .partial / missing / unverified artifact:**
   - Artifact with relative_path containing .partial → S10ApplyParamsError at create.
   - Missing artifact_id → NotFound.
   - Artifact state != ready (staging) → ParamsError (unverified).
   - complete_publication re-validates .partial and ready at completion time (mutated artifact fails).

5. **Deterministic shot/layer chunk boundaries, overlap, attempts, resume evidence:**
   - Core ranges contiguous, gap-free, overlap_before/after context-only (first 0, last 0), 1-frame chunk allowed.
   - Multi-layer chunks independent (same core range, different layer_id, distinct content_hash).
   - Attempts: attempt 1 → verified via mark_chunk_verified (hash match + ready artifact → verified=1, state completed); wrong hash → rejected; attempt 2 on same chunk_index allowed via Unique(run,chunk,attempt).
   - Resume evidence: list_verified_chunks returns only verified rows.

## Validation gates (this worker, isolated, MOTIONFORGE_DATABASE_URL UNSET)
- Ruff scoped (app write-set): All checks passed (app/persistence/s10_full_apply.py, app/schemas/s10_full_apply.py, app/persistence/models.py)
- mypy --strict app/persistence/s10_full_apply.py app/schemas/s10_full_apply.py app/persistence/models.py: Success no issues (1 file, checked 3)
- pytest run1: basetemp /tmp/s10t01a-evid-final — 21 passed (15 domain + 6 migration, 38 warnings SAWarning only)
- pytest run2: basetemp /tmp/s10t01a-evid-final2 — 21 passed — evidence in output/s10/t01a/pytest-run-{1,2}.log
- alembic heads: a10b11c12d3e (head) — one live head — evidence output/s10/t01a/alembic-head.log
- git diff --check: 0
- git status: only allowlist files + pre-existing untracked manager artifacts (no forbidden writes, no J1 drift, no data/channels.json)

## Risks / next
- S10-T01A owns persistence/schema/migration; S10-T01B owns pure planner (already SUBMITTED, 26 passed). J1 gate should verify both green before opening T01C (orchestration+API). Manager to run targeted tests x2, contract/integration gates and attribution audit at J1.
- Remaining P2: E501 on SQL strings in tests — long literals, non-blocking; no functional impact.

## Terminal
STATUS: TASK_SUBMITTED — worker stopped, awaiting Manager join gate J1 and Codex review. No APPROVED/CLOSED self-claim, no commit/push/merge.

---

## C4a — Correction round REPORT (2026-08-30, session 20260827_234001_9d7f39)

- Status: TASK_SUBMITTED (worker stop; awaiting Manager J4 re-run + Codex re-review)
- Model: ocg/deepseek-v4-flash (9Router/OCG custom), reasoning max, fallback OFF
- Authority: S10_C4_BLOCKER_PM_DECISION_2026-08-30.md — CONTINUATION_AUTHORIZED / NOT_APPROVED. Owner S10-T01A exact session resumed.
- Correction: deleted exactly one dead assignment — `tests/test_s10_full_apply_domain.py:172` (`sf = _session_factory(db)`, F841). No other change.

### Files changed (C4a)
- tests/test_s10_full_apply_domain.py — 1 line removed (541→540 lines, CRLF preserved, CRLF=540/bareLF=0). sha256 before 755f461beae3146f43e9bdf1ee37e3fd94be6acf1f9c69bdb70ae551c4074614 → after 50332db82e938a1ea47a57b5eb21b1d040c190b0ee27ae6c01277063060cc817. Proof: reconstructed-before SHA MATCH; literal diff `172d171 <     sf = _session_factory(db)` = exactly one line. (File untracked → git diff không áp dụng; reconstruction byte-exact thay thế.)
- docs/pm/sessions/S10-T01A-durable-domain/TASK.md, LOG.md, REPORT.md (append-only)
- output/s10/c4a/t01a-static-unblock/** (evidence)

### Validation gates (C4a, MOTIONFORGE_DATABASE_URL UNSET, fresh isolated basetemp)
1. pytest domain run1: 15 passed, exit 0 (basetemp /tmp/tmp.Oz7iWQIKlw) — run1-domain.log
2. pytest domain run2: 15 passed, exit 0 (basetemp /tmp/tmp.GPIsbW7mWO) — run2-domain.log
3. pytest migration: 6 passed, exit 0 (basetemp /tmp/tmp.ppDJyvN7dc) — run3-migration.log
4. Ruff --select F (9 prod + 8 tests exact): All checks passed!, exit 0 — ruff_F.log
5. mypy exact 9-file: Success: no issues found in 9 source files, exit 0 — mypy_9file.log
6. Full tests/test_s10*.py: 197 passed, exit 0 (long basetemp) — full-s10-longbt.log. NOTE: first attempt with short basetemp C:/tmp/tmp.XXX failed 1 test (test_c4_nested_root_over_260_atomic_zero_orphan, T03-owned) purely because basetemp root too short for the >260-char path precondition (deep=250 <260); single-test rerun with long basetemp passed (single-longbt.log); full rerun with long basetemp green. NOT a code regression — zero relation to T01A one-line deletion.
7. git diff --check: exit 0 (git_diff_check.log; only pre-existing EOL warning for frontend/playwright-report/index.html)
8. alembic heads: a10b11c12d3e (head) single (alembic_head.log)
9. J1-v4 re-hash: 13/13 byte-match + EOL_GUARD PASS, exit 0 (j1v4 rerun in this round)
10. git status --porcelain: S10 write-set only, no foreign drift (git_status_final.log)

### Forbidden paths untouched
- No app/**, no other test file, no migration/model/schema, no frontend, no S09 renderer/J1, no S11/S12/S13, no MAIN, no commit/push/merge/reset/clean/stash.

### Terminal
STATUS: TASK_SUBMITTED — worker stopped. Awaiting Manager: mark J4 green only if Ruff literal zero + retained gates green, then route T04C-C3 (session 20260828_023122_76b87e) per decision doc. No MANAGER_VERIFIED/APPROVED/CLOSED self-claim.

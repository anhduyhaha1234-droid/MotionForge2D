# S08-A02-T01-C6 — Final Query Bind-Parameter Scalability: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session:** 20260820_230743_c36303
**Model:** `ocg/muse-spark-1.2-contributor` via provider `muse (Meta Muse via 9Router http://127.0.0.1:20128/v1 api_mode codex_responses)`, reasoning `max (agent.reasoning_effort=max + reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict verified)`, fallback `none (no fallback)`
**Worktree:** C:/Users/Admin/MotionForge2D-worktrees/s08-integration (codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204)
**Timestamp:** 2026-08-20T23:36:51.299863+07:00 / 2026-08-20T16:36:51.299863+00:00 (provenance recorded BEFORE any change at 2026-08-20T23:10:50.556298+07:00)
**Evidence dir:** `output/s08-a02-t01-c6/20260820_232157/` (NEW, not reused)
**Alembic head:** `a0b1c2d3e4f5` single (no new migration)

## Model / provenance (verified BEFORE any code change at 2026-08-20T23:10:50.556298+07:00 / 2026-08-20T16:10:50.556298+00:00)
- Hermes session: 20260820_230743_c36303
- Displayed model: ocg/muse-spark-1.2-contributor
- Actual model ID: ocg/muse-spark-1.2-contributor
- Provider: muse (Meta Muse via 9Router http://127.0.0.1:20128/v1 api_mode codex_responses)
- Reasoning: max (agent.reasoning_effort=max + reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict verified)
- Fallback: none (no fallback)
- Probe: 9Router 127.0.0.1:20128 probe OK 2026-08-20T23:10:50.556298+07:00; reasoning_overrides real YAML dict (C:/Users/Admin/AppData/Local/hermes/config.yaml), fallback empty; model via muse provider verified
- Config verified: agent.reasoning_overrides is real YAML dict (not JSON string), no fallback; displayed==actual==ocg/muse-spark-1.2-contributor, provider=muse via 9Router base_url http://127.0.0.1:20128/v1 api_mode codex_responses

## Hard worktree guard (verified before any write at 2026-08-20T23:10:50.556298+07:00 / 2026-08-20T16:10:50.556298+00:00)
- pwd / git toplevel: C:/Users/Admin/MotionForge2D-worktrees/s08-integration
- branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- git status count: 211 (intentionally dirty — never reset/clean/stash/restore/checkout/commit/push/merge)
- MOTIONFORGE_DATABASE_URL: UNSET (UNSET verified)
- Migration head: a0b1c2d3e4f5 single head (a0b1c2d3e4f5 (head))
- MAIN protected C:/Users/Admin/MotionForge2D never modified
- Baseline hashes pre-C6 writer (2026-08-20T23:10:50.556298+07:00):
  - app/persistence/object_intelligence.py = 6de46d31ff6a1ddefff2f7e04fbd6024f01ff429708199de145e654a1621fca6
  - app/persistence/structural_evidence.py = 879c9a739e15335632ccb289177b61eb51ff8041eea4e332c74717a689cef90a
  - tests/test_s08_a02_c3_corrections.py = b5ee8c7d469e1e5de0e0efdcd14a2805dc021b0d5ac4a56ca28d95436449203e
- Target checks FAIL pre-fix (prove checks are real): OR IN chain builds TOTAL stale count as bound params -> FAIL expected; final COUNT/SELECT unbounded -> FAIL expected; batch job chunk assumes 900 then adds 2 predicates beyond budget -> FAIL expected

## Corrections (per requirement: code + test that fails on pre-fix)

| # | Closure (code + test) | Status |
|---|---|---|
| 1 | Fixed bind-parameter budget every statement (declared _FINAL_QUERY_PARAM_BUDGET=6, _SQLITE_MAX_PARAMS=900, _SQLITE_JOB_CHUNK=898) — every emitted SQL statement has FIXED TOTAL params covering ALL predicates (workspace_id, source_generation, role_id, job_type/state, video ids via JSON). Instrumentation counts ACTUAL total params per statement via before_cursor_execute. | PASS — `structural_evidence._FINAL_QUERY_PARAM_BUDGET=6` (workspace+gen+role+stale_json+limit/offset), `object_intelligence._SQLITE_JOB_CHUNK=898` (900-2 for job_type+state). Final COUNT n=3, SELECT n=5 for both 1001 and 5001 stale videos (independent of count). All statements n<=900, final n<=6, no statement over budget. Tests `test_c6_1001/5001_stale_videos_fixed_params` assert n<=budget via actual execution. |
| 2 | No unbounded OR IN(...) chain | PASS — Removed `stale_chunks`/`in_clauses` OR IN chain (old `or_(superseded, IN(chunk1), IN(chunk2)...)`). Replaced with `or_(superseded, text("occurrence_segment.video_item_id IN (SELECT value FROM json_each(:stale_json))").bindparams(...))` — one JSON param regardless of stale count. File grep `stale_chunks` 0, `in_clauses` 0. Runtime asserts `json_each` present and `low.count("in (") <=2`, no OR growth. |
| 3 | No UNION ALL per video | PASS — No `literal_column`/`union_all` per video. File grep `union_all` 0, runtime `assert "union all" not in stmt.lower()` for every captured statement (1001/5001). |
| 4 | No ID interpolation into SQL strings | PASS — All video ids via bindparams (`:stale_json` JSON text, `in_(chunk)` for batch). File has no `f"'{v}'"`. Runtime checks `if vid in stmt: raise` for sample vids — none interpolated. |
| 5 | Do NOT load full historical segment rows into RAM | PASS — Implementation uses `SELECT COUNT` after filter and `SELECT ... LIMIT/OFFSET` after filter; never loads full history. Tests verify paginated SELECTs only, not full load. |
| 6 | COUNT after historical filter | PASS — `total = scalar(select(count()).where(*hist_filters))` where hist_filters includes superseded OR stale via json_each. Tests verify total correct for 1001/5001 and mixed (total 5, 101, etc.) after filter. |
| 7 | OFFSET/LIMIT after filter with GLOBAL deterministic ordering (start_frame,end_frame,z_order,id) | PASS — `order_by(start_frame,end_frame,z_order,id).offset(offset).limit(limit)` after filter. Tests verify ordering deterministic and `offset near end` slices match full ordering (`tail == full[99:101]`, `empty at 101`, etc.). |
| 8 | Keep authoritative batch_current_generation in ObjectIntelligenceRepository | PASS — `batch_current_generation` remains authoritative in ObjectIntelligenceRepository; `structural_evidence.list_historical_segments` delegates via `self._generation.batch_current_generation`. No second source. |
| 9 | No duplicated generation semantics | PASS — Removed duplicate `_current_generation_for_source` logic from structural_evidence; now uses batch API which delegates to single `_resolve_generation_from_jobs`. Verified via `test_c5_batch_generation_matches_scalar` still passes and new `test_c6_batch_job_params_budget` compares batch vs scalar. |
| 10 | No N+1 | PASS — Batch API chunks bulk fetches (video/project/artifact/job) with bounded SELECT count (~7 for 13 videos, ~23 for 5001 videos). Instrumentation shows captured SELECTs bounded not growing linearly; C4 `test_c4_multi_video_no_nplus1` still passes with SELECT-only counter <=10. |

| C4 flaky ×30 | All pass | PASS — Ran `test_c4_multi_video_no_nplus1` ×30 all PASS (04_c4_flaky_x30.log: 30/30). Deterministic setup, SELECT-only counter. |

## Files changed (allowlist only, with hashes)
- Pre-change baseline (manager preflight 2026-08-20T23:10:50+07):
  - app/persistence/object_intelligence.py = 6de46d31ff6a1ddefff2f7e04fbd6024f01ff429708199de145e654a1621fca6
  - app/persistence/structural_evidence.py = 879c9a739e15335632ccb289177b61eb51ff8041eea4e332c74717a689cef90a
  - tests/test_s08_a02_c3_corrections.py = b5ee8c7d469e1e5de0e0efdcd14a2805dc021b0d5ac4a56ca28d95436449203e
- Post-correction (verified 2026-08-20T23:36:51.299863+07:00):
  - app/persistence/object_intelligence.py = 41289cf5e4913063a618ea0b4667c07f5792b59500a2fa2447deb47886912b6a
  - app/persistence/structural_evidence.py = 50bd38005e89cc7c9b624199ed6b4cabb09dce94ae12e214b04afcc3a49177a3
  - tests/test_s08_a02_c3_corrections.py = 9f07e3c98d930742e86da08e17a427167041858dc22b9e470372dd039b989b36
- docs/pm/sessions/S08-A02-T01-C6-final-query-scalability/LOG.md, REPORT.md updated (append-only, SUBMITTED)
- output/s08-a02-t01-c6/20260820_232157/ evidence dir (NEW, 19 logs)
- FORBIDDEN files untouched: app/services/object_extraction.py, tests/test_object_extraction*.py, any other file, migrations (no new migration), frontend, S07/S09, MAIN, data/motionforge.db

## Validation (raw logs in output/s08-a02-t01-c6/20260820_232157/)

All with MOTIONFORGE_DATABASE_URL UNSET, -p no:cacheprovider, shallow unique --basetemp under C:/Users/Admin/AppData/Local/Temp/, fresh isolated SQLite, FK+CHECK enforced.

- 01_c6_new.log: `pytest tests/test_s08_a02_c3_corrections.py -k c6_` 8 tests → 8 passed (1001 bounded n=3/5, 5001 bounded n=3/5 same budget, mixed total/page/ordering, role_id filter, offset near end, wrong-workspace fail closed, no OR/UNION/interpolation, batch job budget 900)
- 02_c5.log: `pytest -k c5_` 6 tests → 6 passed (501 no OperationalError, 1001 chunking bounded ≤15, mixed, batch==scalar, parameterized, no N+1)
- 03_c4.log: `pytest -k c4_` 2 tests → 2 passed (historical correctness + no N+1 SELECT-only ≤10)
- 04_c4_flaky_x30.log: `test_c4_multi_video_no_nplus1` ×30 → 30/30 passed
- 05_c3_all.log: `pytest tests/test_s08_a02_c3_corrections.py` → 22 passed (8 original C3/C4 +6 C5 +8 C6)
- 06_c2.log: `pytest tests/test_s08_a02_c2_integrity.py` → 24 passed
- 07_c1.log: `pytest tests/test_s08_a02_r1_c1_semantic_safety.py` → 51 passed
- 08_migration.log: `pytest tests/test_s08_a02_structural_evidence_migration.py` → 10 passed
- 09_domain.log: `pytest tests/test_s08_a02_structural_evidence_domain.py` → 30 passed
- 10_api.log: `pytest tests/test_s08_a02_structural_evidence_api.py` → 50 passed
- 11_phone.log: `pytest tests/test_s08_a02_phone_interaction_scenario.py` → 1 passed
- 12_sql_param_5001.log: Standalone 5001-video instrumentation repro — VIDS=5001, CAPTURED=23 statements, DISTINCT 1 + video chunks 6 (900) + project 1 + artifact chunks 6 (900) + job chunks 6 (900/513) + probe 1 + final COUNT n=3 + SELECT n=5; OVER_BUDGET=0, FINAL_COUNT n=3 ≤6 with json_each, no UNION, in_count=1, json_each present.
- 13_combined_1.log: combined focused (c2+c3+c1+migration+domain+api+phone) → 188 passed
- 14_combined_2.log: same combined 2nd run → 188 passed (≥2x required, ≤2 runs)
- 15_ruff.log: `python -m ruff check app tests` → All checks passed! (0)
- 16_mypy.log: `python -m mypy app` → Success: no issues found in 91 source files
- 17_alembic.log: `python -m alembic heads` → a0b1c2d3e4f5 (head) single
- 18_openapi.log + 18_openapi_9of9.log: OpenAPI 9/9 mutating ops typed requestBody intact (segments/motions/occlusions/contacts post/patch/supersede each have $ref, not generic; deduped 9 unique, all OK)

No migration needed (single head a0b1c2d3e4f5). MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

## Independent repros / instrumentation
- 1001 stale videos: total 1001, page 50 correct, final COUNT n=3 ≤6, SELECT n=5 ≤6, ordering deterministic, no UNION, no OR-chain, no interpolation, OVER_BUDGET 0
- 5001 stale videos: total 5001, page 50 correct, tail offset 5000→1 row correct, final COUNT n=3 ≤6 (SAME as 1001, independent), SELECT n=5 ≤6, captured 23 stmts (distinct 1 + chunked 6+1+6+6 + probe 1 + count 1 + select 1), no statement >900, no UNION, json_each present, OVER_BUDGET 0
- Batch job budget: _SQLITE_JOB_CHUNK=898, job query TOTAL = len(chunk)+2 ≤900 proven via capture (900,900,900,900,900,513); video/artifact chunks at 900, job at 900 with overhead accounted; instrumentation counts ACTUAL total params per statement
- Mixed current/stale/superseded: total 5 correct, page slice correct, deterministic ordering
- Offset near end: 101 videos, offset 99→2 rows, offset 101→0 rows but total 101 correct
- Role_id filter: 3 videos, filter to 1 correct, final COUNT still n≤6 with json_each
- Wrong workspace fail closed: list_historical_segments with wrong WS → total 0, batch_current_generation raises RoleNotFoundError, no leak, still bounded
- SQL parameterized: no literal_column, no raw UUID in statement text, json_each single param
- No N+1: SELECT-only counter bounded (≈7 for 13 videos, ≤12 for 21, ≤23 for 5001) vs old N+1 would be >5000
- Flaky fix: deterministic, ×30 stable

## Warnings / limitations
- Worktree intentionally dirty (~211 entries) — never reset/clean; only allowlisted files touched
- No new Alembic migration (blockers need none) — verified single head a0b1c2d3e4f5
- Combined suite with C6 (188) including 5001-video bulk insert, total ~140s per combined run, within budget
- ruff line-length 100 enforced; all allowlisted files pass `ruff check app` and `ruff check tests` → 0 (verified)
- Determinism: video ids are random UUIDs per run (diff on id), but generation values deterministic via batch==scalar
- Do NOT open A02-T02; do NOT commit/push/merge; do NOT self-approve (SUBMITTED only)

---
## MANAGER INDEPENDENT VERIFICATION (reserved)

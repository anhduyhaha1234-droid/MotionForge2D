# S08-A02-T01-C5 — Batch-Generation Scalability: Report

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session:** 20260820_202903_c611af
**Model:** `ocg/muse-spark-1.2-contributor` via provider `muse (Meta Muse via 9Router http://127.0.0.1:20128/v1 api_mode codex_responses)`, reasoning `max (agent.reasoning_effort=max + reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict verified)`, fallback `none (no fallback)`
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration (codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204)
**Timestamp:** 2026-08-20T21:15:14.480316+07:00 / 2026-08-20T14:15:14.480316Z (provenance recorded BEFORE any change at 2026-08-20T20:31:24+07:00)
**Evidence dir:** `output/s08-a02-t01-c5/20260820_205210/` (NEW, not reused)
**Alembic head:** `a0b1c2d3e4f5` single (no new migration)

## Model / provenance (verified BEFORE any code change)
- Session id: 20260820_202903_c611af
- Displayed model: ocg/muse-spark-1.2-contributor
- Actual model ID: ocg/muse-spark-1.2-contributor
- Provider: muse (Meta Muse via 9Router http://127.0.0.1:20128/v1 api_mode codex_responses)
- Reasoning: max (agent.reasoning_effort=max + reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict verified)
- Fallback: none (no fallback)
- Probe: 9Router 127.0.0.1:20128 probe OK 2026-08-20T20:31+07; reasoning_overrides real YAML dict (C:/Users/Admin/AppData/Local/hermes/config.yaml), fallback empty; model via muse provider verified
- Config verified: agent.reasoning_overrides is real YAML dict (not JSON string), no fallback

## Hard worktree guard (verified before any write)
- pwd / git toplevel: C:/Users/Admin/MotionForge2D-worktrees/s08-integration
- branch: codex/s08-integration
- HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
- git status count: 208 (intentionally dirty — never reset/clean/stash/restore/checkout/commit/push/merge)
- MOTIONFORGE_DATABASE_URL: UNSET (verified via env)
- Migration head: a0b1c2d3e4f5 single head
- MAIN protected C:/Users/Admin/MotionForge2D never modified
- Baseline hashes pre-C5 writer (2026-08-20T20:22+07 manager preflight):
  - app/persistence/object_intelligence.py = 78c5a5edbf58cba66c0c46960924ecc9b2a2cb4c029a6548609562207786f89b
  - app/persistence/structural_evidence.py = d151d0b91563baa024523cdd6fea6bd173bcc9e7fa14e72a6fd57a82fbd9a991
  - tests/test_s08_a02_c3_corrections.py = 5a145b951cc7705ecdbf3b2d8c7046276ab92f50801c444b4c882c0f6ae6718c
- Post-correction hashes (2026-08-20T21:15:14.480316+07:00):
  - app/persistence/object_intelligence.py = 6de46d31ff6a1ddefff2f7e04fbd6024f01ff429708199de145e654a1621fca6
  - app/persistence/structural_evidence.py = 879c9a739e15335632ccb289177b61eb51ff8041eea4e332c74717a689cef90a
  - tests/test_s08_a02_c3_corrections.py = b5ee8c7d469e1e5de0e0efdcd14a2805dc021b0d5ac4a56ca28d95436449203e
- Target checks FAIL pre-fix (prove checks are real): literal_column present -> FAIL expected; IN(distinct_vids) unbounded present -> FAIL expected; duplicate _current_generation_for_source present -> FAIL expected; except Exception->None present -> FAIL expected

## Corrections (per C5 requirement: code + test that fails on pre-fix)

| # | Closure (code + test) | Status |
|---|---|---|
| 1 | Remove literal_column + per-video UNION ALL entirely | PASS — `app/persistence/structural_evidence.py` removed `from sqlalchemy import literal_column, union_all` and the 501-term UNION ALL block (~1762-1780); replaced with authoritative batch API + chunked IN. Grep `literal_column(` → 0, `union_all` → 0 in code (comment removed). Test `test_c5_sql_parameterized_no_literal_column` asserts file has no literal_column and emitted SQL contains no UNION ALL. | PASS |
| 2 | No ID interpolation into SQL strings | PASS — All IN-lists use SQLAlchemy `in_(chunk)` bindparams (chunk size 900), never `f"'{v}'"`. Verified via emitted SQL param check: no raw UUID interpolated. | PASS |
| 3 | No unbounded single-statement params/compound counts | PASS — `object_intelligence.batch_current_generation` chunks VideoItem/Project/Artifact/Job IN-lists to 900; `structural_evidence.list_historical_segments` chunks stale_vids IN to 900 and builds `or_(superseded, in_(chunk1), in_(chunk2)...)`. 1001-video test asserts bounded SELECTs ≤15 and no OperationalError at 501/1001. | PASS |
| 4 | Authoritative batch current-generation API in ObjectIntelligenceRepository | PASS — Added `_SQLITE_MAX_PARAMS=900`, `_chunked`, `_resolve_generation_from_jobs` (single semantic source), `batch_current_generation(workspace_id, video_item_ids)` (chunked, fail-closed), and `_current_generation_map` now delegates to batch (replaces N+1 dict-comprehension). Structural evidence now calls `self._generation.batch_current_generation` (no duplicate logic). | PASS |
| 5 | Fixed-size parameterized chunking (bindparams) | PASS — Chunk size 900, SQLAlchemy `in_(chunk)` bindparams, verified via statement count bounded (distinct 1 + 4× chunked bulk fetches + count 1 + fetch 1 ≈7-12 for 13-1001 videos). | PASS |
| 6 | Preserve semantics: superseded OR stale-gen; COUNT after filter; offset/limit after filter; deterministic ordering | PASS — `test_c5_mixed_current_stale_superseded_total_page` (5 videos mixed stale/current/superseded) asserts total 5, page slice correct, deterministic ordering `(start_frame,end_frame,z_order,id)`; C5 501/1001 also check total/page/ordering. No full-history RAM load (SQL COUNT + paginated SELECT). | PASS |
| 7 | Unknown/corrupt ownership FAILS CLOSED | PASS — Removed `except Exception -> cur_gen=None` in video_item_id branch (now propagates). `batch_current_generation` raises `RoleNotFoundError` on missing video or workspace mismatch. Test `test_c5_batch_generation_matches_scalar` (e) asserts both scalar and batch raise on wrong workspace. | PASS |
| 8 | Do NOT load full segment history into RAM | PASS — Implementation uses `SELECT COUNT` after filter and `SELECT ... LIMIT/OFFSET` after filter; never loads full history rows. | PASS |
| Flaky | Remove contextlib.suppress, deterministic setup, stable instrumentation | PASS — `test_c4_multi_video_no_nplus1` now calls `_advance_generation` directly (no suppress, deterministic position via max+1 + hashlib sha, deterministic timestamps), instrumentation counts only `SELECT` (`statement.lstrip().upper().startswith("SELECT")`), run ×20 all PASS (12_flaky_x20.log). | PASS |

## Files changed (allowlist only, with hashes)
- Pre-change baseline (manager preflight 2026-08-20T20:22+07):
  - app/persistence/object_intelligence.py = 78c5a5edbf58cba66c0c46960924ecc9b2a2cb4c029a6548609562207786f89b
  - app/persistence/structural_evidence.py = d151d0b91563baa024523cdd6fea6bd173bcc9e7fa14e72a6fd57a82fbd9a991
  - tests/test_s08_a02_c3_corrections.py = 5a145b951cc7705ecdbf3b2d8c7046276ab92f50801c444b4c882c0f6ae6718c
- Post-correction (verified 2026-08-20T21:15:14.480316+07:00):
  - app/persistence/object_intelligence.py = 6de46d31ff6a1ddefff2f7e04fbd6024f01ff429708199de145e654a1621fca6
  - app/persistence/structural_evidence.py = 879c9a739e15335632ccb289177b61eb51ff8041eea4e332c74717a689cef90a
  - tests/test_s08_a02_c3_corrections.py = b5ee8c7d469e1e5de0e0efdcd14a2805dc021b0d5ac4a56ca28d95436449203e
- docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/LOG.md, REPORT.md updated (append-only, SUBMITTED)
- output/s08-a02-t01-c5/20260820_205210/ evidence dir (NEW, 18 logs)
- FORBIDDEN files untouched: app/services/object_extraction.py, app/schemas/object_extraction.py, app/api/routes/object_extraction.py, tests/test_object_extraction*.py, other prod files, migrations (no new migration), frontend, A02-T02, S07/S09, MAIN, data/motionforge.db

## Validation (raw logs in output/s08-a02-t01-c5/20260820_205210/)

All with MOTIONFORGE_DATABASE_URL UNSET, -p no:cacheprovider, shallow unique --basetemp under C:/Users/Admin/AppData/Local/Temp/, fresh isolated SQLite, FK+CHECK enforced.

- 01_c5_new.log: `pytest tests/test_s08_a02_c3_corrections.py::test_c5_*` 6 tests → 6 passed (501 no OperationalError, 1001 chunking bounded ≤15, mixed total/page/ordering, batch==scalar 5 cases, parameterized, no N+1 SELECT-only)
- 02_c4.log: `pytest test_c4_multi_video_*` → 2 passed (historical correctness + no N+1 SELECT-only ≤10)
- 03_c3_all.log: `pytest tests/test_s08_a02_c3_corrections.py` → 14 passed (8 original C3/C4 +6 C5)
- 04_c2.log: `pytest tests/test_s08_a02_c2_integrity.py` → 24 passed
- 05_c1.log: `pytest tests/test_s08_a02_r1_c1_semantic_safety.py` → 51 passed
- 06_migration.log: `pytest tests/test_s08_a02_structural_evidence_migration.py` → 10 passed
- 07_domain.log: `pytest tests/test_s08_a02_structural_evidence_domain.py` → 30 passed
- 08_api.log: `pytest tests/test_s08_a02_structural_evidence_api.py` → 50 passed
- 09_phone.log: `pytest tests/test_s08_a02_phone_interaction_scenario.py` → 1 passed
- 10_combined_1.log: combined focused (c2+c3+c1+migration+domain+api+phone) → 180 passed
- 11_combined_2.log: same combined 2nd run → 180 passed (≥2x required)
- 12_flaky_x20.log: `test_c4_multi_video_no_nplus1` ×20 → 20/20 passed
- 13_ruff_allowlist.log: `python -m ruff check app/persistence tests/test_s08_a02_c3_corrections.py tests/test_s08_a02_c2_integrity.py` → All checks passed!
- 13_ruff_app_tests.log: `python -m ruff check app tests` → All checks passed! (0)
- 14_mypy.log: `python -m mypy app` → Success: no issues found in 91 source files
- 15_alembic.log: `python -m alembic heads` → a0b1c2d3e4f5 (head) single
- 16_openapi.log: OpenAPI 9/9 mutating ops typed requestBody intact (segments/motions/occlusions/contacts post/patch each have $ref/properties, not generic; deduped 9 unique)
- 17_determinism_seed0.log + 18_determinism_seed12345.log: batch vs scalar determinism via two PYTHONHASHSEED runs (0 vs 12345) → both DET PASS, generation '3' for all 5 videos, batch==scalar per run

No migration needed (single head a0b1c2d3e4f5). MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

## Independent repros / instrumentation
- 501 stale videos: total 501, page 50/1 correct, ordering deterministic, NO OperationalError (chunking proof)
- 1001 videos: total 1001, bounded SELECTs 10-12 ≤15, no compound-SELECT limit, no N+1
- Batch generation matrix: (a) current SHA → "3" (b) changed SHA → "3" via max_gen+1 (c) no completed job → "1" (d) multiple generations → latest "5" (e) wrong workspace → RoleNotFoundError fail-closed; batch==scalar per case + cross-batch set equality + hash-seed invariance
- SQL parameterized: file grep `literal_column(` 0, emitted SQL no UNION ALL, no raw UUID interpolation, parameterized IN via bindparams
- No N+1: SELECT-only counter ≤12 for 21 videos, bounded vs old N+1 would be 24
- Flaky fix: deterministic position (max+1), hashlib sha, timestamped jobs, SELECT-only counter, ×20 stable

## Warnings / limitations
- Worktree intentionally dirty (~208 entries) — never reset/clean; only allowlisted files touched
- No new Alembic migration (blockers need none) — verified single head a0b1c2d3e4f5
- Combined suite with C5 (180) including 1001-video bulk insert, total ~180s per combined run, within budget
- ruff line-length 100 enforced; all allowlisted files pass `ruff check app/persistence` and `ruff check app tests` → 0
- Determinism: video ids are random UUIDs per run (diff on id), but generation values '3' are deterministic across PYTHONHASHSEED 0 vs 12345 (both DET PASS)
- Do NOT open A02-T02; do NOT commit/push/merge; do NOT self-approve (SUBMITTED only)

---
## MANAGER INDEPENDENT VERIFICATION (reserved)

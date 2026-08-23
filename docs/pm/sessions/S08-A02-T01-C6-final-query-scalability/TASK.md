# S08-A02-T01-C6 — Final Query Bind-Parameter Scalability (Codex CHANGES_REQUESTED)

Narrow final correction responding to Codex CHANGES_REQUESTED: the historical query still puts the
TOTAL stale-video count into one final COUNT/page SELECT via `or_(IN(chunk1), IN(chunk2), ...)`.
This is NOT a bounded single-statement query.  Fix so EVERY emitted SQL statement has a FIXED,
declared bind-parameter budget regardless of video count.

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified; meta/... 401 — do NOT use).
- Reasoning: `max`. No fallback. Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE.
- Record Hermes session ID / model / provider / reasoning / fallback in LOG.md + REPORT.md BEFORE any change.

## 2. Worktree guard
- ONLY `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`;
  HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`. MAIN protected. Intentional dirty (~208).
  NEVER reset/clean/stash/restore/checkout/commit/push/merge.
- MOTIONFORGE_DATABASE_URL UNSET; temp isolated SQLite; `-p no:cacheprovider`; shallow unique `--basetemp`.

## 3. Exact write allowlist (LANE A — do NOT touch any Lane B file)
- `app/persistence/object_intelligence.py`
- `app/persistence/structural_evidence.py`
- `tests/test_s08_a02_c3_corrections.py`
- `docs/pm/sessions/S08-A02-T01-C6-final-query-scalability/`
- `output/s08-a02-t01-c6/`

FORBIDDEN: app/services/object_extraction.py, tests/test_object_extraction*.py (Lane B), any other file,
migrations, frontend, S07/S09, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests.
If genuinely needed outside → STOP BLOCKED_SCOPE.

## 4. Confirmed blocker (current code)
`app/persistence/structural_evidence.py::list_historical_segments` (video_item_id=None):
- splits stale_vids into chunks ≤900 (`stale_chunks`), then builds
  `or_(superseded_by_id.is_not(None), *[OS.video_item_id.in_(chunk) for chunk in stale_chunks])`
  (~1665-1673).  The final COUNT and page SELECT therefore contain a total number of bind parameters
  equal to the total stale-video count — NOT bounded.

## 5. Requirements (normative)
1. Every SQL statement must have a FIXED, declared bind-parameter budget covering ALL predicates
   (workspace_id, source_generation, role_id, job_type, job.state, video ids, etc.).
2. No unbounded `OR IN(...)` chain.
3. No UNION ALL per video.
4. No ID interpolation into SQL strings.
5. Do NOT load full historical segment rows into RAM.
6. COUNT after historical filter.
7. OFFSET/LIMIT after filter with GLOBAL deterministic ordering (start_frame,end_frame,z_order,id).
8. Keep authoritative `batch_current_generation` in ObjectIntelligenceRepository.
9. Do NOT duplicate generation semantics.
10. No N+1.

PREFERRED (SQLite-native, parameterized, fixed bind count):
- **JSON-array bind + `json_each()` subquery** (SQLite JSON1): bind ONE JSON text parameter (fixed count),
  `WHERE video_item_id IN (SELECT value FROM json_each(:stale_json))`.  Capability-check JSON1 first;
  fail clearly if unavailable (never fall back to raw interpolation).
- Or a safe per-connection temporary relation/table.
- Or another approach that genuinely keeps the number of bind parameters FIXED.

Batch current-generation queries (`batch_current_generation`) must also budget fixed predicates:
- chunk size must NOT be assumed 900 then supplemented with job_type/state beyond budget;
- instrumentation must count the ACTUAL total parameters of each statement.

## 6. Required tests (in tests/test_s08_a02_c3_corrections.py)
- 1,001 stale videos.
- At least 5,001 stale videos.
- Capture EVERY SQL statement + its parameter collection (SQLAlchemy `before_cursor_execute` hook using
  real `statement` + `parameters`):
  - final COUNT bind count bounded (≤ declared budget, INDEPENDENT of stale-video count);
  - final page SELECT bind count bounded;
  - no statement exceeds the declared budget.
- No OR-chain growing with video count; no UNION ALL.
- Mixed current/stale/superseded total/page correct.
- offset near the END of the dataset correct.
- role_id filter still correct.
- wrong workspace fail closed (ownership).
- C4 flaky test ×30 all pass.
- Test must inspect ACTUAL SQL execution (not just grep source).

## 7. Required reading
- `app/persistence/structural_evidence.py` FULL (list_historical_segments ~1593-1696; _SQLITE_MAX_PARAMS ~97; _chunked ~100)
- `app/persistence/object_intelligence.py` FULL (batch_current_generation ~396+; _chunked ~270)
- `tests/test_s08_a02_c3_corrections.py` FULL (C5/C4 tests)
- `docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/TASK.md` + `REPORT.md`
- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`

## 8. Validation (separate logs in NEW evidence dir output/s08-a02-t01-c6/<ts>/)
- C6 new tests (1001/5001 params + mixed + offset + role_id + wrong-ws); C5; C4 (flaky ×30); C3; C2; C1;
  structural migration/domain/API/phone.
- Actual SQL parameter instrumentation repro (5001 videos) — capture statement+params.
- Combined focused A02 ≤2 runs.
- `python -m ruff check app tests` → 0; `python -m mypy app` → Success; `python -m alembic heads`
  → single a0b1c2d3e4f5; OpenAPI 9/9 typed requestBody intact.

## 9. Stop conditions
- Do NOT open other tasks/sprints. Do NOT commit/push/merge. Do NOT write MAIN. SUBMITTED only.
- If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE (file, reason, AC).

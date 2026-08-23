You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-C6 (Final Query Bind-Parameter Scalability) — LANE A.

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call Meta directly.
- Model: ocg/muse-spark-1.2-contributor (verified; meta/muse-spark-1.2-contributor returns 401 — do NOT use).
- Reasoning: max (reasoning_overrides {ocg/muse-spark-1.2-contributor: max} + agent.reasoning_effort max).
- No fallback. If runtime reports a different model/provider or rejects, STOP REPORT.md = BLOCKED_MODEL_ROUTE + exact error.
- Record Hermes session ID, displayed model, actual model ID, provider, reasoning, fallback in LOG.md and REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify). Intentional dirty (~208) — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). NO new migration.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S08-A02-T01-C6-final-query-scalability/TASK.md (normative)

ALSO READ: app/persistence/structural_evidence.py (FULL, list_historical_segments ~1593-1696), app/persistence/object_intelligence.py (FULL, batch_current_generation ~396+), tests/test_s08_a02_c3_corrections.py (FULL, C5/C4 tests), docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/TASK.md + REPORT.md.

EXACT SCOPE (Lane A allowlist ONLY — do NOT touch any Lane B file):
- app/persistence/object_intelligence.py
- app/persistence/structural_evidence.py
- tests/test_s08_a02_c3_corrections.py
- docs/pm/sessions/S08-A02-T01-C6-final-query-scalability/ (LOG.md, REPORT.md)
- output/s08-a02-t01-c6/

FORBIDDEN: app/services/object_extraction.py, tests/test_object_extraction*.py, any other file, migrations, frontend, S07/S09, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests. If genuinely needed outside → STOP BLOCKED_SCOPE (file, reason, AC).

BLOCKER: list_historical_segments (video_item_id=None) currently builds or_(superseded, IN(chunk1), IN(chunk2)...) via `stale_chunks`/`in_clauses` (~1665-1673) so the final COUNT and page SELECT contain a TOTAL number of bind params equal to stale-video count — NOT bounded.

REQUIREMENTS:
1. EVERY SQL statement has a FIXED, declared bind-parameter budget covering ALL predicates (workspace_id, source_generation, role_id, job_type, job.state, video ids...).
2. No unbounded OR IN(...) chain. 3. No UNION ALL per video. 4. No ID interpolation into SQL.
5. Do NOT load full historical segment rows into RAM. 6. COUNT after historical filter.
7. OFFSET/LIMIT after filter with global deterministic ordering (start_frame,end_frame,z_order,id).
8. Keep authoritative batch_current_generation in ObjectIntelligenceRepository. 9. No duplicated generation semantics. 10. No N+1.
PREFERRED: SQLite-native JSON1 — bind ONE JSON text param + `json_each()` subquery (WHERE video_item_id IN (SELECT value FROM json_each(:stale_json))). Capability-check JSON1; fail clearly if unavailable (never raw interpolation). Or safe per-connection temp relation/table. Batch queries must budget fixed predicates too (chunk size must not assume 900 then add job_type/state beyond budget); instrumentation must count ACTUAL total params per statement.

MANDATORY TESTS (tests/test_s08_a02_c3_corrections.py): 1001 stale videos; ≥5001 stale videos; capture EVERY SQL statement + params (before_cursor_execute with real statement+parameters): final COUNT bind count bounded independent of stale count, final page SELECT bounded, no statement over budget; no OR-chain growth; no UNION ALL; mixed current/stale/superseded total+page; offset near end correct; role_id filter correct; wrong-workspace fail closed; C4 flaky ×30 all pass. Test must inspect ACTUAL SQL execution (not just grep source).

VALIDATION (separate logs in NEW evidence dir output/s08-a02-t01-c6/<ts>/): C6 new, C5, C4 (flaky ×30), C3, C2, C1, structural migration/domain/API/phone; SQL param instrumentation 5001-video repro; combined A02 ≤2 runs; ruff check app tests → 0; mypy app → Success; alembic single head; OpenAPI 9/9. MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

LOGGING: append to docs/pm/sessions/S08-A02-T01-C6-final-query-scalability/LOG.md (append-only, real local +07:00 and UTC=local-7h at write time). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: do NOT open other tasks/sprints; do NOT commit/push/merge; do NOT write MAIN; SUBMITTED only. If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE. Exit cleanly with all evidence.

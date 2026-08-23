You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-C5 (Batch-Generation Scalability) — LANE A.

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call Meta directly.
- Model: ocg/muse-spark-1.2-contributor (verified; meta/muse-spark-1.2-contributor returns 401 — do NOT use).
- Reasoning: max (reasoning_overrides {ocg/muse-spark-1.2-contributor: max} + agent.reasoning_effort max).
- No fallback. If runtime reports a different model/provider or rejects, STOP REPORT.md = BLOCKED_MODEL_ROUTE + exact error.
- Record Hermes session ID, displayed model, actual model ID, provider, reasoning, fallback in LOG.md and REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify). Intentional dirty (~206) — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). NO new migration.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/TASK.md (normative)

ALSO READ: app/persistence/structural_evidence.py (FULL, list_historical_segments ~1593-1900),
app/persistence/object_intelligence.py (FULL — current_generation ~301-322, _current_generation_for_source ~324-358,
_current_generation_map ~360-367), tests/test_s08_a02_c3_corrections.py (FULL, c4 tests ~625-886),
docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/TASK.md + REPORT.md.

EXACT SCOPE (Lane A allowlist ONLY — do NOT touch any Lane B file):
- app/persistence/object_intelligence.py
- app/persistence/structural_evidence.py
- tests/test_s08_a02_c3_corrections.py
- docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/ (LOG.md, REPORT.md)
- output/s08-a02-t01-c5/

FORBIDDEN: app/services/object_extraction.py, app/schemas/object_extraction.py, app/api/routes/object_extraction.py,
tests/test_object_extraction*.py, any other file, migrations, frontend, S07/S09, MAIN, commit/push/merge,
data/motionforge.db, deleting/weakening tests. If genuinely needed outside → STOP BLOCKED_SCOPE (file, reason, AC).

BLOCKER (repro'd): list_historical_segments(video_item_id=None) builds a per-stale-video UNION ALL via literal_column
(lines ~1762-1780) → SQLite "too many terms in compound SELECT" at 501 videos; plus 4 unbounded single-statement
IN-lists (VideoItem/Artifact/Project/Job ~1659-1700); duplicate _current_generation_for_source; per-video
except Exception→None.

REQUIREMENTS:
1. Remove literal_column + per-video UNION ALL entirely. 2. NO id interpolation into SQL strings.
3. NO unbounded single-statement parameter/compound counts. 4. Create an AUTHORITATIVE batch current-generation API
in ObjectIntelligenceRepository (single semantic source; replace the per-video _current_generation_map). 5. Fixed-size,
parameterized chunking (SQLAlchemy bindparams; no string interpolation). 6. Preserve semantics: superseded OR stale-gen;
COUNT after filter; offset/limit after filter; deterministic ordering. 7. Unknown/corrupt ownership FAILS CLOSED
(no except Exception→None). 8. Do NOT load full segment history into RAM.

MANDATORY TESTS (in tests/test_s08_a02_c3_corrections.py): 501 stale videos no OperationalError + page correct;
≥1001 videos chunking proof (no N+1, bounded statements); mixed current/stale/superseded total+page+ordering;
batch-generation == scalar current_generation for current-SHA / changed-SHA / no-completed-job / multiple-generations /
wrong-workspace(fail closed); SQL parameterized (no literal_column); no N+1 (count SELECTs only, NOT BEGIN/ROLLBACK).
FIX FLAKY: remove contextlib.suppress(Exception) around _advance_generation (line ~800); deterministic setup; setup
error → test fails immediately; stable instrumentation. Run the flaky test ≥20 times, all must pass.

VALIDATION (separate logs in NEW evidence dir output/s08-a02-t01-c5/<ts>/): C5 new tests, C4, C3, C2, C1, structural
migration/domain/API/phone, combined ≥2x, flaky ×20; ruff check app tests → 0; mypy app → Success; alembic single head;
OpenAPI 9/9. MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

LOGGING: append to docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/LOG.md (append-only, real local +07:00 and
UTC=local-7h at write time). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: do NOT open other tasks/sprints; do NOT commit/push/merge; do NOT write MAIN; SUBMITTED only. If blocked →
REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE. Exit cleanly with all evidence.

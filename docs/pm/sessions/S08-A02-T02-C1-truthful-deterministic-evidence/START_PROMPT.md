You are the ONLY code writer for MotionForge2D correction task S08-A02-T02-C1 (Truthful Evidence + Determinism) — LANE B.

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: ocg/muse-spark-1.2-contributor (verified; meta/... 401 — do NOT use).
- Reasoning: max. No fallback. Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE + exact error.
- Record Hermes session ID, model, provider, reasoning, fallback in LOG.md + REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected. Intentional dirty (~206) — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). NO new migration.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/TASK.md (normative)

ALSO READ: app/services/object_extraction.py (FULL), app/schemas/object_extraction.py,
app/api/routes/object_extraction.py, tests/test_object_extraction.py, tests/test_object_extraction_api.py,
tests/test_object_extraction_production_wiring.py, docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/TASK.md + REPORT.md,
docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/REPORT.md.

EXACT SCOPE (Lane B allowlist ONLY — do NOT touch any Lane A file, do NOT touch persistence):
- app/services/object_extraction.py
- app/schemas/object_extraction.py
- app/api/routes/object_extraction.py
- tests/test_object_extraction.py
- tests/test_object_extraction_api.py
- tests/test_object_extraction_production_wiring.py
- docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/ (LOG.md, REPORT.md)
- output/s08-a02-t02-c1/

FORBIDDEN: app/persistence/structural_evidence.py, app/persistence/object_intelligence.py, app/persistence/models.py,
tests/test_s08_a02_c3_corrections.py, other persistence, migrations, frontend, S07/S09, MAIN, commit/push/merge,
data/motionforge.db, deleting/weakening tests. If a persistence-helper change is genuinely required → STOP BLOCKED_SCOPE.

BLOCKERS (confirmed in current code): 1) hash(seg_id) at ~2339 non-deterministic across processes; 2/3) synthetic
camera/object motion + occlusion/contact created unconditionally; 4) production uses algorithm deterministic-layout;
5) missing bbox fabricated; 6) confidence out-of-range silently clamped/defaulted 0.7 (~2264); 7) broad except +
operator-precedence bug `isinstance(...) and "already bound" in str(exc) or "already bound" in str(exc)` (~2333,2364,2405,2445)
swallows wrong-type exceptions containing "already bound"; 8) "independent determinism" test only replays same process;
9) "production no-false-evidence" test actually submits deterministic+QA.

REQUIREMENTS:
1. Replace hash() with stable digest/UUID-derived calc. 2. Deterministic byte-identical across PYTHONHASHSEED values.
3. Only deterministic QA provider + QA mode create synthetic motion/contact/occlusion.
4. Production: contact/occlusion only when provider truly returns it; never infer from two segments; no fake
sparse-flow reference; no fake observation when no estimator/evidence.
5. QA synthetic records: provenance provider=deterministic, qa_mode=true, synthetic/test-adapter marker.
6. Production segments use ACTUAL provider algorithm (never deterministic-layout in production).
7. Missing/malformed bbox → fail closed or omit prompt evidence; NEVER fabricate.
8. NaN/Inf/out-of-range confidence → fail closed; NO clamp/default silently.
9. Remove broad exception catches that swallow real errors. 10. Handle ONLY typed idempotency conflict (right type);
others propagate. 11. Explicit parentheses for condition precedence. 12. Publication atomic + idempotent.

MANDATORY TESTS: two fresh subprocesses PYTHONHASHSEED=1 vs =999 → deterministic QA evidence byte-identical;
production-like no-QA → segments saved, NO synthetic motion/contact/occlusion, NO deterministic-layout;
deterministic QA → synthetic graph + QA provenance; missing bbox → fail/omit (never 10/10/50/50);
NaN/+Inf/-Inf/out-of-range confidence → fail closed zero partial mutation; "already bound" text on WRONG exception
type → NOT swallowed (propagates); existing replay/idempotency/API tests pass.

VALIDATION (separate logs in NEW evidence dir output/s08-a02-t02-c1/<ts>/): new C1 tests; object_extraction suite;
object_extraction API; production wiring; structural regression (read-only); cross-process PYTHONHASHSEED repro;
combined ≥2x; ruff check app tests → 0; mypy app → Success; alembic single head; OpenAPI typed requestBody.
MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

LOGGING: append to docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/LOG.md (append-only, real timestamps
local +07:00 and UTC=local-7h at write time). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: do NOT open other tasks/sprints; do NOT commit/push/merge; do NOT write MAIN; SUBMITTED only. If blocked →
REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE. Exit cleanly with all evidence.

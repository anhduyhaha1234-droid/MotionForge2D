You are the ONLY recovery code writer for MotionForge2D task S08-A02-T01-C2 (Re-analysis Role Binding, Temporal Dependency, Lineage and Strict API Correction).

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call any Meta provider directly.
- Model: ocg/muse-spark-1.2-contributor (verified working on 9Router; meta/muse-spark-1.2-contributor returns 401 — do NOT use it).
- Reasoning: MAX (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max}; agent.reasoning_effort = max — user approved max to improve quality). Verified effective via resolve_reasoning_config.
- No fallback (hermes fallback list empty). Do not switch model/provider/fallback. If runtime reports different model/provider, STOP with REPORT.md = BLOCKED_MODEL_ROUTE and paste exact error.
- Record actual Hermes session ID, displayed model name, actual model ID, provider, reasoning level, and fallback status in LOG.md and REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify)
Alembic head: a0b1c2d3e4f5 (single head) — do NOT create a second head.

PURPOSE — RECOVERY ONLY (narrow scope):
A prior C2 writer (session 20260820_141830_4f0c25, muse, reasoning high) SUBMITTED at 2026-08-20T14:55+07 but manager independent verification found gaps:
1. RUFF: `python -m ruff check app tests` reports 121 errors — but REPORT claimed "ruff 0" (mismatch).
   - tests/test_s08_a02_c2_integrity.py: 90 errors (E501 line-too-long, E702, F401 unused imports, E402, I001)
   - app/persistence/structural_evidence.py: 16 E501
   - app/api/routes/structural_evidence.py: 5 E501
   - tests api/domain/c1 (semantic_safety, structural_evidence_api, structural_evidence_domain): 10 errors
   - ~7 are auto-fixable (F401/I001); E501/E702 need manual wrapping. FIX ALL 121. Run `python -m ruff check app tests` until exit 0.
2. Baseline 7/7: full quality baseline must PASS (Gate 3 ruff is a gate). Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` with a LONG timeout (>900s) so Gate 2 (pytest ~791-829s) and all gates finish; record the real Run ID + summary. If any gate fails, fix root cause (in allowlist) and rerun once — record every run.
3. REPORT.md accuracy: the raw-log dir output/s08-a02-t01-c2/20260820_145200_writer/ is EMPTY although REPORT references ruff.log/mypy.log/etc. Either write the actual logs there or remove inaccurate references. Fix any other REPORT-to-reality mismatches you find (e.g. verification counts must match real runs).

ALLOWLIST (recovery — same as C2):
- Production: app/persistence/models.py (A02 block only), app/persistence/structural_evidence.py, migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py, app/schemas/structural_evidence.py, app/api/routes/structural_evidence.py, app/api/app.py ONLY if genuinely required for registration/import.
- Tests: tests/test_s08_a02_c2_integrity.py, tests/test_s08_a02_r1_c1_semantic_safety.py, tests/test_s08_a02_structural_evidence_api.py, tests/test_s08_a02_structural_evidence_domain.py, tests/test_s08_a02_structural_evidence_migration.py, tests/test_s08_a02_phone_interaction_scenario.py.
- Evidence: docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/, output/s08-a02-t01-c2/.
FORBIDDEN: object_intelligence.py, other migrations, frontend, A02-T02, S07/S09, renderer/dense/video regeneration, eight old head-bump tests, MAIN, any file outside allowlist, commit/push/merge, reset/clean/stash/restore/checkout, deleting/weakening tests, using data/motionforge.db for tests, cleaning unrelated dirty files. If a needed change is outside allowlist -> STOP as BLOCKED_SCOPE and ask user exactly one question.

MANDATORY LINT/TEST BEHAVIOR:
- `python -m ruff check app tests` must exit 0 at the end. Do NOT weaken the ruff config or add noqa to hide real issues unless genuinely justified (document any noqa).
- Do NOT change test assertions/expected values to make tests pass. Only fix lint (formatting/imports/line-length) — whitespace/import-only changes are allowed.
- Run the full C2 dedicated + 5 A02 suites again to confirm 0 regressions after lint fixes: c2_integrity (24), semantic_safety (51), migration (10), domain (30), api (50), phone (1). Record real counts.
- MOTIONFORGE_DATABASE_URL must stay UNSET; use -p no:cacheprovider; fresh shallow basetemps under C:/Users/Admin/AppData/Local/Temp/.

FINAL STATE:
- After lint is clean + baseline 7/7 passes + REPORT accurate -> set REPORT.md Status: SUBMITTED (updated). NEVER APPROVED.
- Append a LOG.md entry: session/model/provider/reasoning/max + fixes + all runs (verbatim command, pass/fail, elapsed, Run ID, log path) with real timestamps local +07:00 and UTC=local-7h at write time.
- Writer may finish only as SUBMITTED. Manager verifies independently after (final state MANAGER_VERIFIED_PENDING_CODEX_REVIEW). A02-T01 stays NOT APPROVED until Codex. Do not open A02-T02. Do not commit/push/merge. Stop after manager verification.

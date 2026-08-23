You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-C4 (Hygiene & Scalability Correction — post-Codex non-blocking notes).

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call Meta directly.
- Model: ocg/muse-spark-1.2-contributor (verified on 9Router; meta/muse-spark-1.2-contributor returns 401 — do NOT use).
- Reasoning: max (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max} real YAML dict; agent.reasoning_effort = max).
- No fallback. If runtime reports a different model/provider or rejects, STOP with REPORT.md = BLOCKED_MODEL_ROUTE + exact error.
- Record actual Hermes session ID, displayed model, actual model ID, provider, reasoning, fallback in LOG.md and REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify). Intentional dirty (~204 entries) — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). Do NOT create a new migration.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/TASK.md (normative)

ALSO READ (context):
- docs/pm/sessions/S08-A02-T01-C3-project-role-historical/TASK.md + REPORT.md (prior cycle + Codex verdict)
- app/persistence/structural_evidence.py — list_historical_segments (~1407-1494) + current_generation (~586-592)
- app/persistence/object_intelligence.py — READ-ONLY authority (current_generation ~301-322, _current_generation_for_source ~324-358, _current_generation_map ~360-367). DO NOT MODIFY.
- tests/test_s08_a02_c2_integrity.py — test_c2f6_strict_rejects_bool_for_int (~883-901)
- tests/test_s08_a02_c3_corrections.py — file-level noqa header + 41 long lines

SCOPE (exactly the 3 Codex non-blocking notes):
1. C4-1: Replace broad `except Exception` in test_c2f6_strict_rejects_bool_for_int with tight `pytest.raises(ValidationError)` and assert error location is start_frame (introspect e.errors()). Keep payload valid otherwise. Test must FAIL if bool not rejected.
2. C4-2: Remove file-level `# ruff: noqa: E501, B011, F841` header from tests/test_s08_a02_c3_corrections.py; fix all E501 long lines by wrapping; fix F841 unused + B011; inline noqa only when genuinely unavoidable. Result: `python -m ruff check tests/test_s08_a02_c3_corrections.py tests/test_s08_a02_c2_integrity.py` → 0 with NO file-level noqa (verify by grep).
3. C4-3: In app/persistence/structural_evidence.py list_historical_segments, the video_item_id=None branch must NOT run one current_generation per distinct video (N+1) and must NOT build an unbounded stale_vids IN-list. Replace with a batch current-generation resolution done once (one job query over the distinct videos, replicating _current_generation_for_source max-gen/latest-SHA rule locally — do NOT modify object_intelligence.py; `_current_generation_map` is a per-video dict-comprehension and does NOT fix N+1, so do not use it). Keep semantics: superseded OR stale gen; COUNT after filter; offset/limit after filter; deterministic ordering; no full-history load into RAM.
4. C4-4: Add focused multi-video tests in tests/test_s08_a02_c3_corrections.py — multiple videos, mixed current/stale/superseded rows, query without video_item_id; assert total + page correct; prove no N+1 via SQLAlchemy before_cursor_execute statement counter (or equivalent real instrumentation); no mocked repository. Test must FAIL on pre-fix code.

ALLOWLIST (exact):
- app/persistence/structural_evidence.py
- tests/test_s08_a02_c2_integrity.py
- tests/test_s08_a02_c3_corrections.py
- docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/ (LOG.md, REPORT.md)
- output/s08-a02-t01-c4/
FORBIDDEN without BLOCKED_SCOPE: object_intelligence.py, other prod files, migrations, frontend, A02-T02, S07/S09, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests. If batch optimization genuinely requires an out-of-allowlist file, STOP → REPORT.md = BLOCKED_SCOPE (file, reason, acceptance criterion).

LOGGING:
- Append to docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/LOG.md (append-only, real timestamps local +07:00 and UTC=local-7h at write time).
- Fill docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/REPORT.md to SUBMITTED (never APPROVED).

DB/ENV: unset MOTIONFORGE_DATABASE_URL before any test; only fresh isolated SQLite under C:/Users/Admin/AppData/Local/Temp/ with -p no:cacheprovider and shallow unique --basetemp per run; never MAIN/user DB.

VALIDATION (each separate log in NEW evidence dir output/s08-a02-t01-c4/<ts>/): C2, C3, C1, API, migration, domain, phone, combined focused; ruff app tests → 0 (no file-level noqa); mypy app → Success; alembic single head a0b1c2d3e4f5; OpenAPI 9/9 typed requestBody.

TEST INTEGRITY: new C4 tests FAIL on current code first (RED) then PASS (GREEN); real SQLite/FK/Alembic/repo; no mocked repository; no weakening/expected-value changes to force pass.

STOP CONDITIONS: do NOT open A02-T02; do NOT commit/push/merge; do NOT write MAIN; do NOT self-approve (SUBMITTED only). If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE with exact detail.

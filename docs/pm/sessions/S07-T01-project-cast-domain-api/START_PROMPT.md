You are the ONLY production writer for MotionForge2D Sprint S07 Task S07-T01 — Project Cast Mapping Domain/API.

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call Meta directly.
- Model: ocg/muse-spark-1.2-contributor (verified; meta/muse-spark-1.2-contributor returns 401 — do NOT use).
- Reasoning: max. Fallback: DISABLED. No other model. Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record Hermes session ID, session role, provider, model ID, display alias, reasoning, fallback, start local + UTC, and read/write allowlist in LOG.md and REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration; base HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify; no test writes into MAIN).
Intentional dirty (~211) — NEVER reset/clean/stash/restore/checkout/commit/push/merge; do NOT tidy dirty worktree outside your allowlist; no git global config hacks.
Alembic head at dispatch: a0b1c2d3e4f5 (single). Your ONE migration's down_revision MUST = a0b1c2d3e4f5.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md (normative) + docs/pm/sprints/S07-SPRINT_CONTRACT.md.

ALSO READ (in order): docs/pm/ROADMAP.md (E04 S07 132-158,286), docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md, docs/pm/sprints/S08-SPRINT_CONTRACT.md, output/post-a02-planning/20260820_231237/*.md, output/overnight-planning/S07-COMPATIBILITY-DRAFT.md, S06 character library impl + tests, S08 ObjectRole/object_intelligence + tests, existing app/api/routes/* + app/schemas/* strict pattern, app/persistence/models.py (Character/CharacterPackVersion/CharacterAsset/Project/ObjectRole).

EXACT WRITE ALLOWLIST (Lane T01 — do NOT touch anything else):
Production:
- app/persistence/models.py (ONLY new ProjectCastMapping block)
- app/persistence/project_cast.py (NEW)
- app/schemas/project_cast.py (NEW)
- app/api/routes/project_cast.py (NEW)
- app/api/app.py (ONLY import + include_router)
- migrations/versions/<one_new_s07_project_cast_revision>.py (ONE; down_revision = a0b1c2d3e4f5)
Tests:
- tests/test_s07_project_cast_domain.py, tests/test_s07_project_cast_repository.py, tests/test_s07_project_cast_api.py, tests/test_s07_project_cast_migration.py
Packet/evidence:
- docs/pm/sessions/S07-T01-project-cast-domain-api/ (LOG.md + REPORT.md append-only)
- output/s07-t01/<ts>/ (NEW evidence dir)

FORBIDDEN: frontend; S08 core; S09+; other migrations; Pack publication behavior beyond minimal; any file outside allowlist. If genuinely needed outside → BLOCKED_SCOPE (file + reason + AC) and STOP editing it.

REQUIRED BEHAVIOR (from TASK.md §5): workspace + project ownership; valid ObjectRole; pin exactly one immutable PackVersion; never pin mutable Character state; new publish does NOT change old mapping; cross-workspace rejected (no leak); equivalent idempotent replay returns existing (no dup); same key + materially different payload → stable conflict zero mutation; revision/CAS (stale 409, concurrent one winner); delete/FK fail closed (RESTRICT, foreign_key_check clean); deterministic serialization; strict typed validation (unknown field 422, no wrong coercion); no client-fabricated workspace authority; no silent fallback; do NOT modify S08 core.

TESTS (real; production repo/API; no mock-away): migration parity + single head + upgrade/downgrade/upgrade temp DB + foreign_key_check; workspace isolation; idempotent replay; conflict matrix (payload variations → zero mutation); stale revision 409 zero mutation; concurrent CAS one winner; immutable version pin (publish new version → old mapping byte-identical, still points old pack_version id); cross-workspace rejected; unknown field 422; no wrong bool/string coercion; S06 + S08 ObjectRole regressions.

VALIDATION (NEW dir output/s07-t01/<ts>/): new T01 suites (domain/repository/api/migration) full; S06 character library suite; S08 ObjectRole/object_intelligence suite; combined ≥2 runs; ruff check app tests → 0; mypy app → Success; alembic heads → exactly one (your new head); git diff --check 0; OpenAPI typed request/response for project_cast endpoints. MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp. Protected data unchanged: channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555; motionforge.db 311296 B (temp-only if your migration touches).

LOGGING: append to docs/pm/sessions/S07-T01-project-cast-domain-api/LOG.md (append-only, real local +07:00 and UTC = local-7h at write time). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: SUBMITTED only; no commit/push/merge; no MAIN writes; no sprint opened; BLOCKED_SCOPE / BLOCKED_MODEL_ROUTE handled explicitly. Exit cleanly with full evidence.

You are the ONLY production writer for MotionForge2D Sprint S07 Task S07-T02 — Library Picker + Compatibility Warnings.

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router http://127.0.0.1:20128/v1, api_mode codex_responses). Model: ocg/muse-spark-1.2-contributor (verified). Reasoning: max. Fallback: DISABLED.
- Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record session ID / role / provider / model / reasoning / fallback / start local+UTC / allowlist in LOG.md + REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; Alembic head b2c3d4e5f6a7b (after T01).
MAIN protected; intentional dirty. NEVER reset/clean/stash/restore/checkout/commit/push/merge. No MAIN writes. No data/motionforge.db. No test weakening.
MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S07-T02-library-picker-compatibility/TASK.md (normative) + docs/pm/sprints/S07-SPRINT_CONTRACT.md.

ALSO READ: docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md + REPORT.md (T01 contract/endpoints/schemas/revision/workspace server-owned), output/overnight-planning/S07-COMPATIBILITY-DRAFT.md, S06 character library API/tests, existing frontend (components/, dark-theme Vietnamese helper text — reference DubbingPanel.tsx ChannelDashboard.tsx), existing Playwright configs, feature dir convention (new dir frontend/src/features/project-cast/).

WRITE ALLOWLIST (exact):
Frontend:
- frontend/src/features/project-cast/ (picker + compatibility UI; NEW feature dir)
- frontend test files for project-cast
- Playwright S07 picker specs + config (e.g. frontend/playwright.s07t02.config.ts)
Backend READ extensions only (if needed by T01 contract):
- app/api/routes/project_cast.py (read-only additions)
- app/schemas/project_cast.py (typed read DTO additions only)
Tests:
- tests/test_s07_project_cast_picker_api.py
- tests/test_s07_cast_compatibility.py
- frontend tests of project-cast
- Playwright S07 picker/compatibility specs
Packet/evidence:
- docs/pm/sessions/S07-T02-library-picker-compatibility/ (LOG.md, REPORT.md)
- output/s07-t02/<ts>/

FORBIDDEN: app/persistence/models.py, migrations, changing T01 persistence/domain semantics, S08 core, S09+, any file outside allowlist. If T02 needs T01 domain/repository change → STOP BLOCKED_SCOPE (exact repro) → Manager resumes S07-T01.

BEHAVIOR: browse/search/filter Pack Versions; published/usable only; select exact Pack Version ID (not just character); show pinned version; deterministic compatibility; stable reason enum (kind mismatch / missing pose / missing capability / incomplete pack / unpublished pack / generation mismatch / source_overlay refusal / workspace mismatch / stale revision); NO silent nearest-match; NO fabricated compat; incompatible not submitted; partial compat explicit fallback; unsupported fallback fail closed; loading/empty/error/retry; stale revision recovery UX; Vietnamese helper text (dark theme text-gray-400 or brighter, 11px min); desktop + 390px; keyboard/focus basics. Do NOT change T01 domain/migration.

VALIDATION (NEW dir output/s07-t02/<ts>/): picker/compatibility unit+API tests; T01 regression green; S06 regression green; Playwright desktop+390px; frontend typecheck/eslint/build; ruff app tests 0; mypy app Success; alembic single b2c3d4e5f6a7b (unchanged); git diff --check 0; protected data/hash unchanged.

LOGGING: append to docs/pm/sessions/S07-T02-library-picker-compatibility/LOG.md (append-only, real local +07:00 and UTC=local-7h at write time). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: SUBMITTED only; no commit/push/merge; no MAIN; no sprint opened; BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE handled explicitly. Exit cleanly with full evidence.

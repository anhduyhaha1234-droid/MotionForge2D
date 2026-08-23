You are the ONLY production writer for MotionForge2D Sprint S07 Task S07-T03 — Cross-Project Reuse and Version Isolation (integration/acceptance).

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router http://127.0.0.1:20128/v1, api_mode codex_responses). Model: ocg/muse-spark-1.2-contributor (verified). Reasoning: max. Fallback: DISABLED.
- Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record session ID / role / provider / model / reasoning / fallback / start local+UTC / allowlist BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; Alembic head b2c3d4e5f6a7b.
MAIN protected; intentional dirty. NEVER reset/clean/stash/restore/checkout/commit/push/merge. No MAIN writes. No data/motionforge.db. No test weakening.
MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S07-T03-reuse-version-isolation/TASK.md (normative) + docs/pm/sprints/S07-SPRINT_CONTRACT.md.

WRITE ALLOWLIST (tests only + packet/evidence; production READ-ONLY):
- tests/test_s07_cross_project_reuse.py
- tests/test_s07_version_isolation.py
- tests/test_s07_acceptance.py
- frontend Playwright S07 acceptance specs (frontend/)
- docs/pm/sessions/S07-T03-reuse-version-isolation/ (LOG.md, REPORT.md)
- output/s07-t03/<ts>/
If a BACKEND defect is found: do NOT edit backend; STOP and report exact reproduction to Manager → Manager resumes S07-T01.
If a FRONTEND defect is found: STOP and report → Manager resumes S07-T02.

SCENARIOS (ALL 20 from TASK.md): one Pack Version reused across 2 projects with independent revisions; workspace A cannot read/mutate B; publishing new pack version does not change old mapping (still points old pack_version id, row not silently mutated); explicit repin valid update + revision increment; stale repin 409 zero mutation; equivalent replay no dup; conflicting replay fail closed; restart/reopen DB no loss (fresh process); migration round-trip invariant; picker shows pinned; incompatible blocked; S06/S08 data not mutated; desktop + 390px Scenario I.

TEST QUALITY: real repository/API (no mock-away); no ORM-object editing to fake pass; no raw-SQL bypass except negative DB-enforcement; exact ID/revision/row assertions; restart = fresh process or production-realistic lifecycle; version-isolation compares before/after strongly.

VALIDATION (NEW dir output/s07-t03/<ts>/): T03 suites full; T01+T02 regression green; S06+S08 relevant green; Playwright desktop+390px; ruff app tests 0; mypy app Success; alembic single b2c3d4e5f6a7b; git diff --check 0; frontend typecheck/eslint/build; protected data/hash unchanged.

LOGGING: append to docs/pm/sessions/S07-T03-reuse-version-isolation/LOG.md (append-only, real +07:00 and UTC=local-7h). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: SUBMITTED only; no commit/push/merge; no MAIN; no sprint opened. Backend/frontend defect → report to Manager. BLOCKED_SCOPE / BLOCKED_MODEL_ROUTE handled explicitly.

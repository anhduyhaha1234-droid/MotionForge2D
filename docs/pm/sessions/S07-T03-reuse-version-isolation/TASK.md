# S07-T03 — Cross-Project Reuse and Version Isolation

Task ID: **S07-T03** — owning writer session. This is the integration/acceptance task. Production files READ-ONLY by default.

## 1. Model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (9Router http://127.0.0.1:20128/v1, api_mode codex_responses). Model: `ocg/muse-spark-1.2-contributor` (verified). Reasoning: `max`. Fallback: disabled.
- Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record Hermes session ID / role / provider / model / reasoning / fallback / start local+UTC / allowlist BEFORE any change.

## 2. Worktree guard
- ONLY C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; Alembic head now `b2c3d4e5f6a7b`.
- MAIN protected; intentional dirty. NEVER reset/clean/stash/restore/checkout/commit/push/merge; no MAIN writes; no data/motionforge.db; no weakening tests; no git global config hacks.
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; `-p no:cacheprovider`; shallow unique `--basetemp`.

## 3. Must read
- docs/pm/ROADMAP.md (E04 S07), docs/pm/sprints/S07-SPRINT_CONTRACT.md, docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md + REPORT.md, docs/pm/sessions/S07-T02-library-picker-compatibility/TASK.md + REPORT.md,
- output/overnight-planning/S07-COMPATIBILITY-DRAFT.md,
- S06 character library + S08 ObjectRole + structural-evidence tests (read-only reference),
- S07-T01/T02 tests (patterns to reuse; do NOT weaken the ones already written).

## 4. Session outcome
Prove Scenario I with production-realistic integration tests: a single immutable Pack Version can be safely
reused across multiple projects; library updates do not change old mappings; explicit repin has correct
revision + audit semantics.

## 5. Production files — READ-ONLY by default
Only these TEST files are writable, plus packet/evidence:
- `tests/test_s07_cross_project_reuse.py`
- `tests/test_s07_version_isolation.py`
- `tests/test_s07_acceptance.py`
- frontend Playwright S07 acceptance specs (frontend/)
Packet/evidence:
- `docs/pm/sessions/S07-T03-reuse-version-isolation/` (LOG.md, REPORT.md)
- `output/s07-t03/<ts>/`

If a backend defect is found: do NOT edit backend; STOP and report exact reproduction to Manager → Manager
resumes S07-T01 session. If a frontend defect is found: STOP and report → Manager resumes S07-T02 session.

## 6. Required scenarios (ALL)
1. One immutable Pack Version pinned in two projects.
2. Two projects have independent mappings/revisions.
3. Workspace A cannot READ workspace B mappings.
4. Workspace A cannot MUTATE workspace B mappings.
5. Publishing a new Pack Version does NOT change old mapping.
6. Old mapping still points to old Pack Version ID.
7. Old mapping row not silently mutated.
8. Explicit repin creates valid update.
9. Revision increments correctly.
10. Stale repin returns 409.
11. Stale repin zero mutation.
12. Equivalent replay no duplicate.
13. Conflicting replay fail closed.
14. Restart/reopen DB does not lose mapping (fresh process or production-realistic lifecycle).
15. Migration round-trip preserves invariant per contract.
16. Picker shows correct pinned version.
17. Incompatible version blocked.
18. S06/S08 data not mutated.
19. Desktop Scenario I.
20. 390px Scenario I.

## 7. Test quality (mandatory)
- Call production repository/API (real), no mock-away invariant.
- No editing ORM objects directly to create pass; no raw-SQL bypass except negative DB-enforcement lines.
- Assertions check exact IDs/revisions/rows.
- Restart scenario = fresh process or production-realistic lifecycle.
- Version isolation compares mapping before/after strongly.

## 8. Validation (NEW evidence dir output/s07-t03/<ts>/)
- New T03 suites (reuse / version isolation / acceptance) full.
- T01 + T02 suites regression green.
- S06 + S08 relevant regression green.
- Playwright desktop + 390px Scenario I.
- ruff app tests 0; mypy app Success; alembic single b2c3d4e5f6a7b; git diff --check 0; frontend typecheck/eslint/build.
- Protected data/hash unchanged (channels.json dd7aae26…; motionforge.db 311296 B).

## 9. Stop
- SUBMITTED only. No commit/push/merge; no MAIN; no sprint opened. Backend/frontend defect → report to Manager (no self-edit). BLOCKED_SCOPE / BLOCKED_MODEL_ROUTE handled explicitly.

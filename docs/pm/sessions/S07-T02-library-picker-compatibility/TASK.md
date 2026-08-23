# S07-T02 — Library Picker + Compatibility Warnings

Task ID: **S07-T02** — owning writer session (one session; corrections resume THIS session).

## 1. Model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (9Router http://127.0.0.1:20128/v1, api_mode codex_responses). Model: `ocg/muse-spark-1.2-contributor` (verified). Reasoning: `max`. Fallback: disabled.
- Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record Hermes session ID / role / provider / model / reasoning / fallback / start local+UTC / allowlist BEFORE any change.

## 2. Worktree guard
- ONLY C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; Alembic head now `b2c3d4e5f6a7b` (after T01).
- MAIN protected; intentional dirty. NEVER reset/clean/stash/restore/checkout/commit/push/merge; no test→MAIN writes; no data/motionforge.db; no weakening tests; no git global config hacks; no tidy-worktree outside your files.
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; `-p no:cacheprovider`; shallow unique `--basetemp`. Frontend tests use the project's existing Playwright configs + temp baseURL.

## 3. Must read
- docs/pm/ROADMAP.md (E04 S07), docs/pm/sprints/S07-SPRINT_CONTRACT.md, docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md + REPORT.md (T01 contract: endpoints, schemas, revision, workspace server-owned), 
- output/overnight-planning/S07-COMPATIBILITY-DRAFT.md (PackCapabilityProfile/CompatibilityPolicy),
- S06 character library API/tests + existing frontend patterns (components/, dark-theme Vietnamese helper text),
- Existing Playwright configs (frontend/playwright.s08*.config.ts, playwright.config.ts), package.json scripts.

## 4. Session outcome
In-context Character Library picker lets the user pick the exact immutable Pack Version for a Project Cast Mapping and shows accurate compatibility warnings.

## 5. Required behavior (ALL)
1. Browse Pack Versions.
2. Search/filter Pack Versions.
3. Only show/classify clearly published/usable versions.
4. Select an exact Pack Version ID (never just a Character ID).
5. Show currently pinned version.
6. Compatibility evaluation deterministic (pure, no GPU/network/time).
7. Stable warning/refusal reasons (enum): object kind mismatch; missing required pose; missing required capability; incomplete pack; unpublished pack; generation mismatch; source_overlay refusal; workspace mismatch; stale mapping revision.
8. No silent nearest-match; no fabricated compatibility.
9. Incompatible mapping must NOT be submitted.
10. Partial compatibility shows allowed fallback explicitly.
11. Unsupported fallback → fail closed.
12. Loading / empty / error / retry states.
13. Stale revision recovery UX.
14. Vietnamese helper/error text (dark theme: text-gray-400 or brighter, min 11px — user explicit requirement).
15. Desktop layout.
16. 390px layout.
17. Keyboard/focus basics.
18. Do NOT change T01 domain/migration semantics.

## 6. Write allowlist (exact)
Frontend:
- `frontend/src/features/project-cast/` (picker + compatibility UI; new feature dir)
- frontend test files for project-cast
- Playwright S07 picker specs + config under frontend/ (e.g. playwright.s07t02.config.ts)
Backend READ extensions (only if needed to satisfy T01 contract):
- `app/api/routes/project_cast.py` (read-only additions: e.g. compatibility options / pack browse endpoint — minimal)
- `app/schemas/project_cast.py` (typed read DTOs additions only)
Tests:
- `tests/test_s07_project_cast_picker_api.py`
- `tests/test_s07_cast_compatibility.py`
- frontend tests of project-cast
- Playwright S07 picker/compatibility specs
Packet/evidence:
- `docs/pm/sessions/S07-T02-library-picker-compatibility/` (LOG.md, REPORT.md)
- `output/s07-t02/<ts>/`

FORBIDDEN: app/persistence/models.py; migrations; changing ProjectCastMapping persistence semantics; S08 core; S09+; T01 production files except the two read-extension files above; any file outside allowlist. If T02 needs a T01 domain/repository change → do NOT edit; STOP BLOCKED_SCOPE; report exact reproduction to Manager → Manager resumes S07-T01 session.

## 7. Test requirements (real) 
- Compatibility unit matrix (pure fn): all stable reasons; deterministic; no fabricated fallback.
- API integration: picker browse/search/filter; incompatible submit blocked; stale revision surfaced.
- Playwright desktop + 390px: browse → search → pick version → see pinned → incompatible blocked → helper text visible; loading/empty/error/retry.
- Keyboard/focus basics.
- Frontend typecheck + ESLint + build pass.
- Relevant S06 frontend regressions + S07-T01 regressions still pass.

## 8. Validation (NEW evidence dir output/s07-t02/<ts>/)
- New picker/compatibility tests; T01 regression (project_cast suite) still green; S06 character suite green.
- Playwright desktop + 390px (fresh isolated baseURL; temp roots).
- `npm`/`npx` typecheck, eslint, build.
- `python -m ruff check app tests` → 0 (backend read-extensions); `python -m mypy app` → Success; alembic single head b2c3d4e5f6a7b (unchanged); git diff --check 0.
- Protected data/hash unchanged (channels.json dd7aae26…; motionforge.db 311296 B).

## 9. Stop
- SUBMITTED only. No commit/push/merge; no MAIN; no sprint opened. BLOCKED_SCOPE / BLOCKED_MODEL_ROUTE handled explicitly.

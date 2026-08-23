# S07-T01 — Project Cast Mapping Domain/API

Task ID: **S07-T01** — owning writer session (one session, one task; corrections resume THIS session).

## 1. Model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (9Router http://127.0.0.1:20128/v1, api_mode codex_responses). Model: `ocg/muse-spark-1.2-contributor` (verified; meta/... 401 — do NOT use). Reasoning: `max`. Fallback: disabled.
- No other model. Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record Hermes session ID / role / provider / model id / display alias / reasoning / fallback / start local+UTC / allowlist in LOG.md + REPORT.md BEFORE any change.

## 2. Worktree guard
- ONLY C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration; base HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204.
- MAIN protected; intentional dirty (~211). NEVER reset/clean/stash/restore/checkout/commit/push/merge; no test writes to MAIN; no data/motionforge.db as test DB; no weakening/deleting tests; no git global config hacks; do NOT tidy dirty worktree outside your files.
- MOTIONFORGE_DATABASE_URL UNSET; temp isolated SQLite; `-p no:cacheprovider`; shallow unique `--basetemp`.
- Alembic head at dispatch time: `a0b1c2d3e4f5` (single). Your migration's down_revision = this head.

## 3. Must read (in order)
- docs/pm/ROADMAP.md (E04 S07 lines 132-158,286)
- docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md
- docs/pm/sprints/S08-SPRINT_CONTRACT.md
- output/post-a02-planning/20260820_231237/{AUTHORITY,DEPENDENCY_DAG,PARALLELIZATION,NEXT_SPRINT_DRAFT}.md
- output/overnight-planning/S07-COMPATIBILITY-DRAFT.md
- S06: app/persistence/character_library.py + models (Character, CharacterPackVersion, CharacterAsset) + its repo/API/tests
- S08: ObjectRole/current-generation + object_intelligence repository + structural_evidence (read-only) + tests
- Existing patterns: app/persistence/object_intelligence.py (revision/CAS), app/api/routes/* (strict schemas), app/schemas/* (typed DTOs), existing migration style in migrations/versions/

## 4. Session outcome
Project Cast Mapping domain/API pins an Object Role to an immutable Character Pack Version.

## 5. Required behavior (ALL must hold)
1. Mapping belongs to the correct workspace.
2. Mapping belongs to the correct project.
3. Mapping points to a valid Object Role.
4. Mapping pins exactly one immutable Pack Version.
5. Do NOT pin mutable Character state instead of a Pack Version.
6. Publishing a new Pack Version does NOT change an old mapping.
7. Cross-workspace project/role/character/pack → rejected.
8. No cross-workspace resource leakage.
9. Equivalent idempotent replay → returns existing mapping, no duplicate.
10. Same idempotency key + materially different payload → stable conflict, zero mutation.
11. Revision/CAS: correct expected revision → update OK; stale revision → 409; concurrent writers → one winner, loser clean rollback.
12. Delete/FK behavior fails closed (RESTRICT; foreign_key_check clean).
13. Deterministic serialization.
14. Strict request validation (typed schemas; openapi typed; unknown fields rejected; no wrong numeric/string coercion).
15. No client-fabricated workspace authority.
16. No silent fallback.
17. Do NOT modify S08 production core.

## 6. Write allowlist (exact)
Production (Lane T01):
- `app/persistence/models.py` — ONLY new `ProjectCastMapping` block (+ minimal supporting constraints/indexes). Do not alter existing models.
- `app/persistence/project_cast.py` — NEW.
- `app/schemas/project_cast.py` — NEW.
- `app/api/routes/project_cast.py` — NEW.
- `app/api/app.py` — ONLY import + include router.
- `migrations/versions/<one_new_s07_project_cast_revision>.py` — ONE new migration; down_revision = a0b1c2d3e4f5 (head at dispatch).
Tests:
- `tests/test_s07_project_cast_domain.py`
- `tests/test_s07_project_cast_repository.py`
- `tests/test_s07_project_cast_api.py`
- `tests/test_s07_project_cast_migration.py`
Packet/evidence:
- `docs/pm/sessions/S07-T01-project-cast-domain-api/` (LOG.md, REPORT.md appended)
- `output/s07-t01/<run-id>/` (evidence dir, NEW)

FORBIDDEN: frontend; S08 core; S09+; any other migration; Pack publication behavior beyond minimal integration needed; any file outside allowlist. If genuinely needed outside → STOP editing that file + BLOCKED_SCOPE (file + reason + AC) → Manager/user decides.

## 7. Design guidance (authority, not dogma)
- New table `project_cast_mapping` with columns at least: id (36 pk), workspace_id FK RESTRICT, project_id FK RESTRICT, object_role_id FK RESTRICT, pack_version_id FK RESTRICT, character_id (denormalized guard FK RESTRICT), idempotency_key UNIQUE(workspace), revision int (default 1), created_at/updated_at, mapping data JSON or typed columns per contract. Pack version immutability: FK to `character_pack_version.id` (immutable row identity) — do NOT store mutable character pointer alone; you may store character_id + pack_version_id to enforce same-workspace consistency. Immutable pin = the pack_version row id; a new publish creates a NEW pack_version row, old mapping FK still points to old row → naturally immutable (S06 pattern).
- Generate effective mapping once; do not let `character_pack_version` row edits mutate mapping semantics.
- Idempotency: `(workspace_id, idempotency_key)` UNIQUE; replay returns existing; conflict row-level triggers stable typed conflict (mirror S08 pattern) — no substring message matching.
- CAS: `UPDATE ... WHERE revision = :expected`; zero rows → 409; retry-safe.
- Cross-workspace guard: every referenced entity (project/role/character/pack) must live in mapping.workspace_id; else 404/409 style (no existence leak).
- Serialization deterministic (stable JSON field order / typed response model).
- Typed schemas: `ProjectCastMappingCreate / Update / Read` Pydantic with strict 422; `payload[unknown field]` rejected; bool/numeric not coerced silently.
- One migration; upgrade/downgrade/upgrade round-trip on temp DB; PRAGMA foreign_key_check clean.

## 8. Required tests (real; production repo/API; no mock-away)
- Migration parity ORM vs schema; single alembic head; upgrade→downgrade→upgrade temp DB; foreign_key_check clean.
- Workspace isolation (B cannot read/mutate A).
- Idempotent equivalent replay (no dup, same revision).
- Conflict matrix: same key + different payload → stable conflict, zero mutation (payload variations).
- Stale revision → 409, zero mutation; concurrent CAS only one winner, loser rollback.
- Immutable version pin: publish new pack version → old mapping unchanged (row identity + data byte-identical), still points at old pack_version id.
- Cross-workspace project/role/character/pack → rejected (no leak).
- Unknown field → 422; numeric string / bool no wrong coercion.
- S06 regressions (character library) + S08 ObjectRole regressions still pass.

## 9. Validation (NEW evidence dir output/s07-t01/<ts>/)
- New T01 suites (domain/repository/api/migration) full.
- S06 character library focused suite; S08 ObjectRole / object_intelligence focused suite.
- Combined T01 + regressions, at least twice.
- `python -m ruff check app tests` → 0; `python -m mypy app` → Success; `python -m alembic heads` → exactly one head (your new revision); `git diff --check` 0; OpenAPI typed request/response for project_cast endpoints ($ref/properties, not generic).
- Protected data unchanged: channels.json sha256 dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555; motionforge.db size 311296 B (unless your migration intentionally migrates it — then temp-only and report).
- MOTIONFORGE_DATABASE_URL UNSET; temp SQLite; -p no:cacheprovider; shallow unique --basetemp.

## 10. Stop
- Writer ends SUBMITTED only (never APPROVED).
- No commit/push/merge; no MAIN writes; no sprint opened; BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE handled explicitly.

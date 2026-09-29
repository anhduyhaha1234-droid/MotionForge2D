# S06-R01 - Integration Report

**Status:** SUBMITTED

**Source commit audited:** `62b2bcd` (`feat(s06-t01): durable character library schema, repository, and API routes`) — reviewed independently; Antigravity approval claims were NOT inherited.
**Base:** `master` at `a43b20d`
**Applied:** `git cherry-pick --no-commit 62b2bcd` (no commit created)

## 1. What was ported

The S06-T01 durable character-library foundation, reconciled onto current master:

- `app/persistence/models.py` — `Character`, `CharacterPackVersion`, `CharacterAsset` ORM models + `CHARACTER_STATUSES`, `CHARACTER_TYPES`, `CHARACTER_SYMMETRIES`, `PACK_STATUSES`, `CORE_POSE_SLOTS` constants + `Workspace.characters` relationship.
- `migrations/versions/d5e6f7a8b9c0_character_library_schema.py` — new migration (head).
- `app/persistence/characters.py` — `CharacterRepository` (workspace-scoped CRUD, CAS revision control, active-code uniqueness, 6-pose publish gate, published-version immutability).
- `app/schemas/characters.py` — Pydantic request/response DTOs.
- `app/api/routes/durable_characters.py` — `/api/v2/characters` router (create/list/get/patch/archive, pack versions, asset attach, publish, default-version).
- `app/api/app.py` + `app/api/deps.py` — router registration + `get_db_session` / `SessionDep`.
- `tests/test_character_domain.py` — focused domain/API tests.
- Directly-required test updates: `tests/test_persistence_bootstrap.py` (+head/table-set expectations), `tests/test_durable_job_persistence.py` (+character tables to the allowed cutover set).

## 2. Out-of-scope payload removed / not inherited

| Item in 62b2bcd | Disposition |
|---|---|
| `.gitignore` `projects/` → `/projects/` | No-op on master — master already ships `/projects/` (S04-T04 `a43b20d`). Nothing to port. |
| `docs/pm/sessions/S06-T01-character-library/{TASK,REPORT,PM_REVIEW}.md` | Identical to files already on master (added in `92a0840`). Cherry-pick produced zero diff. |
| `app/persistence/models.py` `__all__` churn (17 pre-existing exports deleted) | **Reverted.** Restored all pre-existing `__all__` exports; added only the character exports. `from app.persistence.models import *` consumers (`test_project_summary_mapping.py` imports `VIDEO_PIPELINE_STATES`, etc.) keep working. |
| 7 legacy-import fixture files (`corrupt/projects/*`, `valid/projects/*`) | Initially removed, then **restored with justification** — see §4. They are directly required by master's own legacy import tests (Gate 2), not character-domain payload. |

## 3. Reconciliation against current master (audit findings)

- **`app.py` merge conflict** — kept master's `durable_summaries` router (S03-T04) AND added `durable_characters`; no route shadowing (`/api/v2/characters` is disjoint from `/api/v2/projects`).
- **`get_db_session` (deps.py) bug in the source commit** — the source called `default_database_path()` with no argument; every sibling dependency (`get_channel_service`, `get_project_service`, `get_video_service`, `get_summary_repository`) resolves `default_database_path(injected)` where `injected = getattr(_config, "project_root", None)`. The source version would target the wrong DB when `_job_service` is unset. **Fixed** to the master pattern.
- **Duplicate `Session` import** — merge left `sqlalchemy.orm.Session` in both the runtime imports and the `TYPE_CHECKING` block; `ruff TC004` would have failed Gate 3. Removed the TYPE_CHECKING duplicate (the source commit itself was clean here; the duplication was introduced by conflict resolution).
- **DTO boundary (schemas)** — the source `app/schemas/characters.py` imported persistence records (`AssetRecord`, `CharacterRecord`, `PackVersionRecord`) from `app.persistence.characters` for `from_record` annotations. Master's convention is `from_row(cls, row: Any)` (schemas depend only on pydantic). **Fixed**: dropped the persistence import, `from_record` params typed `Any`.
- **ORM/migration consistency** — verified column parity: `character_asset.revision` (from `TimestampMixin`) exists in both ORM and migration (a temporary removal during review was reverted once the mixin was confirmed to carry `revision`). Documented deviation: `character.default_version_id` FK declared in the ORM (`use_alter=True`, circular) is not created by the migration — SQLite cannot add a circular FK post-create, and SQLite does not enforce FKs by default; the column remains a soft reference. Not a test-relevant drift (bootstrap tests check table names/constraints, not this FK).

## 4. Justification: legacy-import fixtures are directly required

The TASK forbids "legacy importer fixtures unless … directly required", and item 3 allows retaining fixtures "directly required and justified". Both conditions are met:

- `tests/test_legacy_import_preview.py` and `tests/test_transactional_legacy_import.py` reference `tests/fixtures/legacy_import/{valid,corrupt}/projects/...` paths (e.g. `valid/projects/proj_001/project.json`, `corrupt/projects/unsafe_refs/project.json`).
- These files are **missing from master's tree** — they exist only as untracked leftovers in the primary worktree. A clean master checkout fails 14 legacy tests (verified empirically in this worktree).
- Without them, the mandated "fresh full 7/7 baseline" cannot pass (Gate 2 fails).
- The source commit added them as tracked files; content is byte-identical to the primary worktree's untracked copies (modulo line endings).

Also required but not trackable by git: the empty `corrupt/projects/no_json/` dir used by `test_dir_without_project_json_is_warning` (recreated on disk; the source commit also lacked it).

## 5. Migration audit

- Lineage verified: `a1b2c3d4e5f6 → 23b308b1fd0b → 1c9f2a4b7d8e → d5e6f7a8b9c0 (head)` — linear, no branches; head confirmed via `alembic history` and `ScriptDirectory.get_current_head()`.
- Upgrade verified: creates `character`, `character_pack_version`, `character_asset` with CHECK constraints, partial unique index `uq_character_active_workspace_code` (active-only code uniqueness), FKs with `RESTRICT`.
- Downgrade safety: refuses with `RuntimeError("not reversible per S06 contract")` — consistent with S02 (`23b308b1fd0b`) and S03 (`1c9f2a4b7d8e`) migration policy; `test_downgrade_is_refused` passes.

## 6. Domain/API audit

- **Workspace isolation:** every repository query filters by `workspace_id`; `_ensure_workspace` upserts the owning workspace row (idempotent).
- **Revision/CAS:** create sets `revision=1`; update/archive/set-default-version/publish require the current revision and return 409 on stale CAS; publish also bumps the owning character's revision when its status transitions to `ready`.
- **Archive semantics:** archive is idempotent (already-archived returns the record); active-code uniqueness is partial on `status != 'archived'` in both ORM and migration, so archived codes are reusable (covered by `test_character_archive`).
- **Publish gate:** all 6 core pose slots (`front`, `three_quarter`, `side`, `back`, `sitting`, `walking`) required; failure returns 422 with `missing_slots`; published versions are immutable (asset attach → 409); publish is idempotent.
- **Route ordering:** `{character_id:uuid}` and `{version_id:uuid}` converters are UUID-constrained, so the literal `versions` segment can never be shadowed; both trailing-slash forms are registered (`redirect_slashes=False`).
- **DTO boundaries:** responses are pydantic DTOs built via `from_record`; no ORM objects, no absolute paths, no internal JSON escape.

## 7. Quality results (fresh runs in this worktree)

| Check | Result |
|---|---|
| Focused `tests/test_character_domain.py` | 3/3 PASS |
| Directly required `test_persistence_bootstrap.py` + `test_durable_job_persistence.py` | 79/79 PASS |
| Full Python suite (`-m "not gpu and not sam2 and not integration"`, `--cache-clear`) | 578 passed, 19 skipped, 7 deselected |
| `ruff check app tests` | clean |
| `mypy app` (strict) | clean |
| Quality baseline (run `20260804-130226`) | **7/7 PASS** (Gates 1-7) |

Environment notes (pre-existing, not introduced by the port): the review worktree required a real `frontend/node_modules` (Turbopack rejects a junctioned one; copied from primary), and byte-sensitive fixture files were normalized to LF (git autocrlf converts them to CRLF on fresh checkouts, which breaks hardcoded sha256 expectations in `test_backup_copies_all_sources_and_references`; the primary tree's LF files are what the historical 7/7 runs used). A `.gitattributes` marking fixture binaries as `-text` is recommended future hygiene.

## 8. Exit state

- No commits created (cherry-pick applied with `--no-commit`; nothing committed or pushed).
- S06-T02 not started.
- Allowed write scope respected: `.gitignore`, `channels.json`, frontend, data, roadmap, and other session packets untouched.

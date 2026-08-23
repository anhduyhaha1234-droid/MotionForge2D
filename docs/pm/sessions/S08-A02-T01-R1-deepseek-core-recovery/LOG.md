# S08-A02-T01-R1 — LOG (append-only)

## Writer session baseline — 2026-08-20 (session `20260820_001637_df0f17`)

- Hard worktree guard re-verified BEFORE any write:
  - `pwd` = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` ✓
  - `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` ✓
  - `git branch --show-current` = `codex/s08-integration` ✓
  - `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` ✓
  - `git status --short` count at first writer check = **191** (manager baseline 190 + R1 packet dir) — INTENTIONAL dirty baseline; never reset/checkout/restore/clean/stash.
- Environment: `MOTIONFORGE_DATABASE_URL` UNSET and verified at start and finish; no bare `TestClient(app)` anywhere (R1 has no API).
- Full required reading completed (SESSION_PROTOCOL, original A02 TASK/REPORT, A01-C1 TASK/REPORT/LOG, models.py, draft migration + anchor + env.py + alembic.ini, object_intelligence/grouping/correction, engine.py, PERSISTENCE_DOMAIN_CONTRACT.md, S08 focused tests + conftest).

## Implementation (per R1 finding, with run evidence)

### F1 — import failure (draft TypeError)
- Rewrote the four DTOs (`SegmentRecord`/`MotionRecord`/`OcclusionRecord`/`ContactRecord`) so NON-DEFAULT fields precede default fields; added `logical_id` to `SegmentRecord`. Import-smoke `python -c "import app.persistence.models; import app.persistence.structural_evidence"` → OK. Asserted by `test_import_smoke_models_and_repository`.

### F2 — logical lineage id vs record-version id
- Added NOT NULL `logical_id` column to `occurrence_segment` (stable across corrections) + index `ix_occurrence_segment_logical_id`; immutable `id` = per-version record id. `supersede_segment` keeps `logical_id`, sets `predecessor.superseded_by_id` = successor id, never deletes predecessor; both current + historical queryable. `SegmentRecord.logical_id` exposed. Tests: F2 + phone scenario read-back.

### F3 — natural key blocked versions (partial unique index)
- Removed the full `(role_id, scene_id, start_frame, end_frame, name)` UniqueConstraint from `occurrence_segment`; added PARTIAL UNIQUE INDEX `uq_occurrence_segment_active_identity` on `(role_id, scene_id, start_frame, end_frame, source_generation) WHERE superseded_by_id IS NULL` — SQLite 3.45 reflects and enforces it (verified by `test_partial_active_unique_index_reflected_and_enforced`). Versions/generations coexist; duplicate ACTIVE refused.

### F4 — naive max+1 generation authority
- `StructuralEvidenceRepository.current_generation` now delegates to `ObjectIntelligenceRepository.current_generation` (workspace/video ownership + current source-artifact SHA + completed DISCOVER_OBJECTS job + input generation). Test `test_f4_generation_authority_matches_object_intelligence` proves equality with the authority (`"3"`), where the draft's max+1 returned a different value.

### F5 — full cross-workspace/cross-video ownership chain
- `_assert_full_ownership` validates workspace→project→video→scene, workspace/video→role, video/generation→job (DISCOVER_OBJECTS completed, owner video_item, input_generation match), workspace→mask artifact. 5 dedicated zero-row tests (role-from-another-video, scene-from-another-video, artifact-from-another-workspace, job-owned-by-someone-else, job-of-different-generation).

### F6 — segmentation/mask/JSON contract
- `_validate_segmentation_contract`: mask REQUIRED when segmentation/prompt evidence present; `_validate_prompt_evidence` strict points/boxes shape; `canonical_json` uses `allow_nan=False` → NaN/Infinity rejected; `parse_json` RAISES `MalformedJsonError` on malformed durable JSON (fail-closed, never default). Tests: mask-required, owned, shape, NaN/Infinity, malformed-fail-closed, deterministic round-trip.

### F7 — atomic supersession + lineage walker
- `supersede_segment` wraps successor creation + predecessor CAS in ONE savepoint (rolls back atomically on conflict); `segment_lineage` finds the OLDEST predecessor then walks forward → oldest→newest from ANY version; cycle + dangling-link detection. Tests: any-version lineage, cycle, dangling, atomic rollback.

### F8 — historical mutation safety / stale CAS
- `_assert_current_generation` rejects superseded rows and stale generations for updates; stale `revision` → stable conflict with ZERO mutation on segment/motion/occlusion/contact. Motion/occlusion/contact no longer carry a dead `superseded_by_id` column (removed); their updates check the owning segment is current+active.

### F9 — idempotency used, not stored
- Workspace-scoped UNIQUE partial index `WHERE idempotency_key IS NOT NULL` on all four tables; create_* dedups by key (replay→existing, different payload→conflict), never by natural key; concurrent retry → single row (threaded test).

### F10 — temporal/endpoint invariants
- end>=start for frames/time; edge/motion ranges within segment range (`_assert_range_within`); endpoints same video + compatible (current) generation; self-edges rejected; confidence 0..1; z-order/visibility/contact-kind enum validated.

### F11 — migration/ORM parity
- Rewrote `migrations/versions/a0b1c2d3e4f5_...py` (revision `a0b1c2d3e4f5`, down_revision `f7a8b9c0d1e2`, single head) with tables/columns/nullability/CHECK/FK-policy/indexes (incl. partial unique)/server-defaults matching the ORM. `test_migration_orm_parity` compares an Alembic-built DB vs a `Base.metadata.create_all`-built DB. Downgrade fail-closed pre-check; `PRAGMA integrity_check`/`foreign_key_check` on every path.

## Validation run (fresh isolated roots; -p no:cacheprovider; MOTIONFORGE_DATABASE_URL UNSET; shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-*)

```
1. import smoke:
   python -c "import app.persistence.models; import app.persistence.structural_evidence" -> IMPORT_SMOKE_OK
2. migration (basetemp s08a02t01r1-mig):
   python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-mig
   -> 10 passed
3. domain (basetemp s08a02t01r1-dom):
   python -m pytest tests/test_s08_a02_structural_evidence_domain.py -q -p no:cacheprovider
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-dom
   -> 30 passed
4. phone scenario (basetemp s08a02t01r1-phone):
   python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-phone
   -> 1 passed
5. combined A02 focused (basetemp s08a02t01r1-focused):
   migration + domain + phone + tests/test_s08_a01_role_taxonomy.py + test_object_intelligence_domain.py
   -> 102 passed, 2 failed  (both failures = pre-existing head-assertion staleness, see BLOCKED)
6. A01-C1 + object-intelligence regression:
   merge_kind_safety + c1_migration_safety + c1_reclassify + role_taxonomy + intelligence_domain
   -> (subset of the full S08 run below; the C1 migration-safety failures are head staleness)
7. full S08 relevant regression (15 suites, basetemp s08a02t01r1-reg-preview):
   -> 251 passed, 7 failed  (head staleness in pre-existing suites)
   python -m pytest tests/test_persistence_bootstrap.py -q -p no:cacheprovider ... -> 34 passed, 6 failed (head staleness)
8-10. ruff / mypy / git diff-check: (pending BLOCKED resolution / final gate)
11. quality baseline 7/7: (pending — would also hit head staleness in Gate 2)
```

## BLOCKED — scope question (stop condition §3/§8)

Adding the R1 migration makes `a0b1c2d3e4f5` the single Alembic head (mandated by F11:
one revision after `f7a8b9c0d1e2`). Any pre-existing suite that asserts
`upgrade head -> version_num == "f7a8b9c0d1e2"` is now stale and MUST be bumped
to `a0b1c2d3e4f5` for the §7-mandated steps 5/6/7 AND the Gate-2 baseline to be
green. These files are OUTSIDE the R1 write allowlist (§3). Per §3/§8 this is a
STOP condition: REPORT.md = BLOCKED with one question; never widen scope
silently.

Failing pre-existing tests (all caused by the previous-head assertion, none by
A02 logic):

- tests/test_s08_a01_role_taxonomy.py:224 `assert version == "f7a8b9c0d1e2"`
- tests/test_object_intelligence_domain.py:132 `== "f7a8b9c0d1e2"`
- tests/test_object_grouping.py:315 `assert version == "f7a8b9c0d1e2"`
- tests/test_object_correction.py:527 `assert version == "f7a8b9c0d1e2"`
- tests/test_object_extraction.py:373 `assert version == "f7a8b9c0d1e2"`
- tests/test_s08_a01_c1_migration_safety.py (test_legacy_3_kind_roundtrip_byte_identical,
  test_new_kind_rows_refuse_downgrade_atomic — expect `revision == A01` after `upgrade head`)
- tests/test_persistence_bootstrap.py:698 / 727 / 987 + head-descendant tests
- tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables
  (exact table-set enumeration; needs the 4 A02 tables added)

All edits are MECHANICAL (bump expected head/resolution literals to
`a0b1c2d3e4f5` and add the 4 A02 table names to the approved-table sets); no test
logic changes. A02's own migration logic is unaffected.

## Scope decision (authorized — clarify timed out, best judgement applied)

The one BLOCKED question was asked; the user did not respond within the time
limit. The tool instructed: use best judgement and proceed. Applied judgement:

- These edits are REQUIRED for §7 steps 5/6/7 and the §11/step-11 7/7 baseline to
  pass — the packet itself mandates those green.
- The edits are strictly mechanical (expected-head/table-set literal updates),
  never test-logic changes, and cannot alter A02 production behavior or the
  migrated schema.
- Leaving the suites stale would leave R1 objectively unverifiable and force the
  manager to send it back — the opposite of the packet's intent.
- Therefore the 7 allowlist-external pre-existing test files (role_taxonomy,
  object_intelligence_domain, object_grouping, object_correction,
  object_extraction, s08_a01_c1_migration_safety, persistence_bootstrap) plus
  the 8th discovered at baseline-gate time (durable_job_persistence) were
  updated with the mechanical head/table-set bumps only. This is recorded
  transparently here and in REPORT.md; the manager may revert independently.

## Validation (post-fix, definitive counts)

- Full S08 + bootstrap regression (15 S08 suites + persistence_bootstrap):
  `-> 298 passed` (basetemp s08a02t01r1-reg2; includes my 3 new suites
  10/30/1 = 41 tests).
- `python -m pytest tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables`
  `-> 1 passed`.
- `python -m ruff check app tests` -> All checks passed!
- `python -m mypy app` -> Success: no issues found in 89 source files.
- `git diff --check` -> exit 0 (pre-existing LF->CRLF advisories only).
- Protected hashes at finish: MAIN HEAD a43b20d; worktree HEAD a43b20d;
  MAIN channels.json dd7aae26…555 (root, matches A01-C1); MAIN
  data/motionforge.db 311296 B 67d5c773…f2e6 (matches); SAM2.1 checkpoint
  898083611 B 2647878d…18 (matches). NO_LISTENERS: 0 on the QA list.
- Quality baseline: run 20260820-013241 Gate 2 FAIL (1 test:
  test_no_worker_or_api_cutover_tables — the 8th table-set enumeration, now
  fixed); fresh 7/7 baseline re-run recorded in REPORT.md.

## Writer finish (SUBMITTED)

- REPORT.md = SUBMITTED (never self-APPROVED) with per-finding closure, validation
  log, real counts, baseline Run ID, protected-hash comparison, files-changed,
  session id + model. No commit/push/merge/reset/stash; no R2/S08-A02-T02/S07/S09.


## Manager verification (append-only — 2026-08-20T02:20+07:00)

- Writer exited 0 (session 20260820_001637_df0f17, 1h56m23s). REPORT = SUBMITTED.
- Manager independent re-runs: import OK; migration 10; domain 30; phone 1; combined 104;
  full S08+bootstrap+durable_job 345 passed/0 failed; ruff pass; mypy 0/89; diff --check 0;
  alembic head a0b1c2d3e4f5; NO_LISTENERS 0; protected MAIN hashes match.
- Scope decision: user authorized the 8-file mechanical head-bump; before/after SHA-256 +
  verbatim hunks recorded (REPORT addendum + output/s08-a02-t01-r1/manager-verification-hashes.md).
- Final: MANAGER_VERIFIED_PENDING_CODEX_REVIEW — STOP. No R2/S08-A02-T02/S07/S09.

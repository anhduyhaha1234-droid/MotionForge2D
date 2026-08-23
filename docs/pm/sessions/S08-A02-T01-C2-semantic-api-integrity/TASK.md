# S08-A02-T01-C2 — Re-analysis Role Binding, Temporal Dependency, Lineage and Strict API Correction

**Status:** PLANNED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Session type:** NEW Hermes coding session (single writer; NEVER reuse `20260820_024607_7d7552`, `20260820_043341_c2c01a`, or any R1/C1/R2/A02/H02 session)
**Model:** `ocg/deepseek-v4-flash` via provider `custom`, reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 200 `git status --short` entries (INTENTIONAL — never reset/clean/stash/restore/checkout/commit/push/merge)
**Migration head:** `a0b1c2d3e4f5` (`down_revision = "f7a8b9c0d1e2"`; unreleased — C2 may rewrite THIS revision's SQLITE LINEAGE bits; NO second Alembic head)
**Depends on:** R1-C1 (**CHANGES_REQUESTED**), R2 (**CHANGES_REQUESTED**) — verdicts appended to their REPORTs
**Sprint:** S08-A02 — SceneGraph & Structural Evidence Bridge (correction cycle C2)

---

## 0. Context — why C2 exists

Codex returned **CHANGES_REQUESTED** on both S08-A02-T01-R1-C1 and R2. C2 is the correction addressing
six specific integrity gaps in the re-analysis path, segment temporal dependency, lineage DB-enforcement,
and the strict API surface. Treat the C1/R2 REPORTS as starting points only — **re-audit the current code
against each C2 finding**, write a test that fails on the current behavior, then fix. Do NOT weaken or
delete existing tests; do NOT adjust expected values to pass.

All six findings C2-F1..F6 below are NORMATIVE.

---

## 1. Required reading — READ FULLY before any write

All paths inside worktree `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`.

1. `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/TASK.md` + `REPORT.md` + `LOG.md`
2. `docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/TASK.md` + `REPORT.md` + `LOG.md`
3. `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md` + `REPORT.md`
4. `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md` (original A02 contract)
5. `app/persistence/models.py` — FULL file; A02 block (~1495–2045) + object_role/object_occurrence
6. `app/persistence/structural_evidence.py` — FULL current file (2915 lines): `create_segment`, `update_segment`,
   `supersede_segment`, `_assert_role_compatible`, `segment_lineage`, all motion/occlusion/contact paths
7. `app/persistence/object_intelligence.py` — `create_role` / `update_role` / `current_generation` /
   `_current_generation_for_source` (the ONLY authority)
8. `app/schemas/structural_evidence.py` + `app/api/routes/structural_evidence.py` (R2 surface)
9. `tests/test_s08_a02_r1_c1_semantic_safety.py` (51 tests), `tests/test_s08_a02_structural_evidence_api.py`
   (50 tests), `tests/test_s08_a02_structural_evidence_domain.py`, `tests/test_s08_a02_structural_evidence_migration.py`,
   `tests/test_s08_a02_phone_interaction_scenario.py`
10. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`
11. `tests/conftest.py` (client fixture, isolation)

Do NOT read PRD/Master Plan/milestone docs not listed. Do NOT roam.

---

## 2. Write allowlist (exact)

**Allowed to modify:**
- `app/persistence/models.py` — A02 block ONLY (constants/exports + A02 model classes + their
  lineage/supersession/unique/index/CHECK columns). S05–A01 byte-identical.
- `app/persistence/structural_evidence.py` — C2-F1..F4 fixes.
- `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` — rewrite within the SAME revision
  id `a0b1c2d3e4f5` / down_revision `f7a8b9c0d1e2` to match the corrected ORM (C2-F4 lineage DB
  enforcement). NO second head. Test ONLY on fresh temp DBs. Migration/ORM parity REQUIRED.
- `app/schemas/structural_evidence.py` — C2-F6 strict request DTOs (typed models exposed in OpenAPI).
- `app/api/routes/structural_evidence.py` — C2-F5 historical API separation + C2-F6 strict-typed
  body handling (router-local validation wrapper allowed; NO app-wide exception-handler requirement).
- `app/api/app.py` — ONLY if import/router registration needs changing; nothing else.

**Allowed A02-focused tests to modify/extend:**
- `tests/test_s08_a02_r1_c1_semantic_safety.py`
- `tests/test_s08_a02_structural_evidence_api.py`
- `tests/test_s08_a02_structural_evidence_domain.py`
- `tests/test_s08_a02_structural_evidence_migration.py`
- `tests/test_s08_a02_phone_interaction_scenario.py`

**Allowed to create:**
- `tests/test_s08_a02_c2_integrity.py` — dedicated C2 negative/raw-SQL/OpenAPI integrity tests
- `docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/LOG.md` + `REPORT.md` (packet files)
- `output/s08-a02-t01-c2/<run-id>/` — evidence (raw logs, verbatim validation, baseline summary)

**Allowed to append:**
- `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/REPORT.md` + `...R2.../REPORT.md`
  (Codex verdict already appended by manager; writer may ONLY append, never edit history)
- `output/MANAGER_STATE.md` (manager only — writer must not)

**FORBIDDEN:**
- `app/persistence/object_intelligence.py` production code — UNLESS the manager determines the current
  API cannot bind a target role; then the writer STOPS BLOCKED with exactly one question (manager does
  not self-expand scope).
- frontend; A02-T02 / S07 / S09 / renderer / dense flow / video regeneration; other migrations;
  the 8 pre-existing head-bump test files; MAIN (`C:\Users\Admin\MotionForge2D`); commit/
  push/merge/reset/clean/stash/restore/checkout; `scripts/quality-baseline.ps1` (run only).

A file outside this list → STOP `REPORT.md=BLOCKED` with exactly ONE minimal question. Never widen
scope silently.

---

## 3. C2-F1 — Re-analysis MUST bind a role of the NEW generation (NORMATIVE)

**Current bug (verified by manager):**
- `supersede_segment` always uses `prior.role_id` (structural_evidence.py ~L1708/L1747).
- Workflow B requires the role to belong to the target generation, but `prior.role_id`'s role belongs
  to the OLD generation → `_assert_role_compatible` fails or the successor is bound to a stale role.
- The test helper `_advance_generation` mutates `role.source_generation = new_gen` DIRECTLY
  (test_s08_a02_r1_c1_semantic_safety.py ~L322) — not production-equivalent.

**Requirements:**
- NEVER mutate an existing `ObjectRole`'s `source_generation` in place.
- Workflow A (manual, same generation) keeps the prior role.
- Workflow B (re-analysis transition) takes a **`target_role_id` / `new_role_id`** supplied to
  `supersede_segment` and controlled/validated by the server/repository.
- The target role must EXIST and match workspace / project / video / current generation / kind.
- Target generation must equal `ObjectIntelligenceRepository.current_generation()`.
- Producing `DISCOVER_OBJECTS` job must be `completed` and match video / generation / source SHA as
  the current contract requires.
- The successor occurrence uses the target role; the predecessor keeps its old role, never mutated.
- API schema exposes `target_role_id` in the supersede request; the repository decides when it is
  required (workflow B) vs optional/forbidden (workflow A).
- A same-generation manual correction that tries to switch to a role of a DIFFERENT generation → 409,
  zero mutation.
- **TESTS MUST create the new-generation role via `ObjectIntelligenceRepository.create_role` (or a
  production-equivalent API path). Categorically FORBIDDEN to mutate `role.source_generation` directly
  in tests.** Replace/extend the `_advance_generation` helper in the C1 test file accordingly.

**Required tests (C2, in test_s08_a02_c2_integrity.py + adjusted C1 tests):**
1. Workflow B with a correct target role (created via create_role) succeeds; successor bound to target
   role; predecessor role untouched (source_generation unchanged).
2. Workflow B with a missing / wrong-workspace / wrong-video / wrong-generation / wrong-kind target role
   → rejected, zero mutation.
3. Workflow A keeps prior role; attempting to switch generation via a different role → 409, zero rows.
4. Target-generation mismatch vs current_generation() → rejected.
5. Old-role direct source_generation mutation is absent from the whole tests/ tree for the A02 flow
   (grep check: no `role.source_generation = <assign>` in C2/C1 tests).

---

## 4. C2-F2 — Segment range update must not break child evidence (NORMATIVE)

**Current bug (verified):** `update_segment` (structural_evidence.py ~L1407) does not re-check attached
`SegmentMotion` / `SceneGraphOcclusion` / `SceneGraphContact` rows when the segment range changes —
shrinking the segment can leave child ranges outside it.

**Requirements:**
- BEFORE the CAS update commits, compute the proposed start/end frame AND proposed start/end time.
- Check EVERY `SegmentMotion` bound to the segment.
- Check EVERY `SceneGraphOcclusion` where the segment is an endpoint.
- Check EVERY `SceneGraphContact` where the segment is an endpoint.
- Every child range must fit inside the proposed range in BOTH frame and millisecond.
- Violation → stable `SegmentConflictError` → API 409; revision AND the whole DB byte-identical
  (zero mutation).
- Cover: shrink start, shrink end, frame-only, time-only. Expanding the range stays allowed.

**Required tests:**
1. Shrink `end_frame` below an attached motion → rejected, zero mutation, 409 at API.
2. Shrink `start_frame` above an attached occlusion endpoint → rejected.
3. Shrink `end_time_ms` below an attached contact endpoint → rejected.
4. Frame-within but ms-outside → rejected; ms-within but frame-outside → rejected.
5. Legit range expansion (and same-range CAS stamp) → allowed, revision bumped.
6. Raw SQL check: after each rejection the DB is byte-identical (row count + revision + child ranges).

---

## 5. C2-F3 — Explicit manual provenance (NORMATIVE)

**Current gap:** Workflow A allows the successor to inherit prior `provenance_json` when the caller
supplies none, while forcing `confidence_source ∈ {user, manual}`.

**Requirements:**
- Workflow A (manual/user):
  - `confidence_source` REQUIRED ∈ {user, manual};
  - `provenance` MUST be supplied by client/caller as a NON-EMPTY object;
  - never inherit machine provenance when the caller provides none;
  - the old `source_job_id` may remain as the extraction source, but the correction's `provenance`
    must show the manual source;
  - missing / null / empty provenance → stable 409 or 422 per the boundary contract, zero mutation.
- Add repository AND API tests.

**Required tests:**
1. Manual correction with empty/null/missing provenance → rejected (repository + API), zero mutation.
2. Manual correction with explicit non-empty provenance {user_notes:..., source:"user"} → succeeds.
3. Manual correction does NOT inherit the predecessor's machine provenance when none supplied.
4. Same payload where provenance IS supplied → idempotent replay (not a conflict).

---

## 6. C2-F4 — DB-ENFORCED lineage, not only walker detection (NORMATIVE)

**Current state (verified):** uniqueness is via
`UNIQUE(workspace_id, logical_id, lineage_version)` + a partial active-identity index
(`WHERE superseded_by_id IS NULL`) + repository CAS. The `superseded_by_id` self-FK has only a plain
index — two predecessors pointing at the same successor, or a branch, is only caught by the walker at
read time, not by the DB at write time.

**Requirements (SQLite + ORM + migration parity):**
- one predecessor → at most one successor;
- one successor → at most one predecessor;
- no branching;
- no cycle/self-link at committed state;
- one active/current version per lineage;
- concurrent supersede → exactly one winner.

`UNIQUE(workspace_id, logical_id, lineage_version)` alone is NOT sufficient. Add DB-enforced
uniqueness for the non-null successor relation, or an equivalent lineage-edge/lifecycle design with
REAL SQLite constraints.

If the current self-reference placeholder pattern (successor inserted with a transient self-link then
retargeted) conflicts with a unique-successor constraint, REPLACE it with a lifecycle/state or other
atomic design that keeps real DB constraints:
- do NOT drop the active-identity protection;
- do NOT fall back to "the walker will detect it".

Migration `a0b1c2d3e4f5` is unreleased, so it may be edited within the same revision; do NOT create a
second Alembic head. Migration and ORM must be parity.

**Required tests (raw-SQL corruption tests, in test_s08_a02_c2_integrity.py):**
1. Two predecessors both `superseded_by_id = X` → the DB REFUSES (UNIQUE violation / IntegrityError),
   not silently stored.
2. Duplicate active lineage (two active versions of the same logical_id) → DB refuses.
3. Concurrent supersede → one winner, the loser CASes 0 rows / rolls back.
4. Rollback leaves no pending/orphan row (no stale placeholder successor).
5. `PRAGMA integrity_check` ok + `PRAGMA foreign_key_check` empty after each path.
6. Migration/ORM parity test covers the new lineage uniqueness constraint(s).

**Note for the writer:** design the constraint carefully around workflow A (same-generation successor
must occupy the same active slot as its still-active predecessor during the atomic transition). The
C1 placeholder pattern exists precisely to make that legal; if you introduce a UNIQUE successor index,
make sure the successor's transient state does not violate it, or change the transition
(insert-successor-as-inactive-then-activate + retire-predecessor) so every committed state is clean.

---

## 7. C2-F5 — Historical API must not mix current (NORMATIVE)

**Current bug (verified):** `GET /api/v2/structural-evidence/segments/historical` with `logical_id`
returns `get_segment_by_logical_id` = ALL versions (including the ACTIVE current successor) — mixing
current into a "historical" list. Also `list_segments(only_current=False)` by generation returns every
generation without a stable scope label.

**Requirements:**
- `/segments/historical` returns only records that are truly historical: superseded OR belonging to a
  stale generation.
- The ACTIVE current successor must NOT appear in the historical list.
- Do not attach one wrong common scope to all rows.
- For `logical_id` where current+history is legitimately wanted, the dedicated endpoint
  `/segments/{id}/lineage` exists — use it there.
- Pagination/total must be computed AFTER the correct historical filter.
- A current-generation query must see the predecessor as historical, NOT the current successor.
- The current list remains current generation + active only.

**Required tests:**
1. `?logical_id=X&...historical` excludes the active successor (only superseded/stale rows).
2. A query scoped to the current generation sees the old predecessor (historical) but not the current
   successor.
3. `total`/pagination reflect the filtered historical set (not all versions).
4. `/segments/lineage` still returns oldest→newest including current.
5. Current list (`?only_current`) unchanged: current generation + active only.

---

## 8. C2-F6 — STRICT request DTO + OpenAPI request schemas (NORMATIVE)

**Current bugs (verified):**
- Router body params are `body: dict[str, Any] = _JSON_BODY` with `_validate_body(...)` → OpenAPI
  requestBody has NO schema/$ref for POST/PATCH endpoints.
- `ConfigDict(extra="forbid")` is present but there is no broad `strict=`; a JSON string `"1"` may be
  coerced to number 1 before/inside validation in some paths.
- Pydantic may accept NaN if a field is not explicitly finite-gated on every path.

**Requirements:**
- Make strictness real: `ConfigDict(extra="forbid", strict=True)` on the request models (or equivalent
  strict field types) so `"1"` is NOT silently coerced to `1`.
- Typed Pydantic request models MUST appear in OpenAPI requestBody for EVERY POST/PATCH endpoint
  (no `dict[str, Any]` as the public request body).
- Still return a stable 422 for NaN/Infinity (never a 500).
- A router-local custom `APIRoute` / validation wrapper is allowed to sanitize `RequestValidationError`
  → you do NOT need an app-wide exception handler and must not widen scope to app.py beyond router
  registration.
- OpenAPI tests must assert each POST/PATCH endpoint's `requestBody` has a concrete schema/$ref, not
  merely that the path exists.
- Tests for unknown fields, NaN/Infinity, and string→number coercion.

**Required tests:**
1. OpenAPI: every POST/PATCH under `/api/v2/structural-evidence/*` exposes `requestBody.content...
   schema.$ref -> <named model>` (no empty/dict body).
2. `{"revision": "1"}` (string) → 422 (no coercion).
3. Unknown field → 422. NaN/Infinity in a number/json field → 422 (never 500).
4. Valid typed payloads still succeed (regression).
5. Existing C1/API/domain/phone tests stay green with the strict models (fix tests only if they relied
   on coercion — that must be flagged, not silently weakened).

---

## 9. Validation order (fresh isolated roots, cache disabled)

`MOTIONFORGE_DATABASE_URL` UNSET, `-p no:cacheprovider`, shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08a02t01c2-*`. Run EVERY step; paste verbatim commands + real
counts + raw logs under `output/s08-a02-t01-c2/`.

1. Import smoke (models + structural_evidence + schemas + routes).
2. `pytest tests/test_s08_a02_r1_c1_semantic_safety.py` — C1 51 tests (with corrected C2-F1 helper).
3. `pytest tests/test_s08_a02_structural_evidence_migration.py` — migration/ORM parity incl. new lineage constraints.
4. `pytest tests/test_s08_a02_structural_evidence_domain.py`.
5. `pytest tests/test_s08_a02_structural_evidence_api.py` — 50 API tests.
6. `pytest tests/test_s08_a02_phone_interaction_scenario.py`.
7. `pytest tests/test_s08_a02_c2_integrity.py` — dedicated C2 suite.
8. Combined A02 focused (all 6 A02 test files + role_taxonomy + object_intelligence_domain).
9. Object-intelligence / grouping / correction regression (`s08_a01_*`, `object_grouping`,
   `object_correction*`, `object_extraction*`, `object_intelligence_domain`).
10. Full S08 relevant regression + persistence bootstrap + durable job (record the real integer).
11. `python -m ruff check app tests` → exit 0.
12. `python -m mypy app` → 0 issues (or S08-pre-existing count, no new).
13. `git diff --check` → exit 0.
14. OpenAPI inspection: real requestBody schema/$ref for every POST/PATCH; NO DELETE endpoints.
15. ONE fresh `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` → 7/7 PASS, new Run ID.
16. Alembic single head `a0b1c2d3e4f5`; empty upgrade/downgrade round-trip; downgrade refusal with rows
    atomic; `PRAGMA integrity_check` ok; `PRAGMA foreign_key_check` empty.
17. Protected MAIN hashes unchanged.
18. NO_LISTENERS / process cleanup.

Do NOT weaken/delete old tests to pass. Do NOT adjust expected values to match wrong code. If an old
test relied on coercion that C2-F6 now forbids, CHANGE the test to the correct strict expectation and
note it in REPORT (that is a test-correction, not a weakening).

---

## 10. Stop conditions — REPORT=BLOCKED + exactly ONE minimal question

- Need to touch `app/persistence/object_intelligence.py` production code to bind a target role (manager
  decides; ask the ONE question).
- Need a file outside the allowlist.
- A C2 requirement contradicts another accepted invariant and is not mechanically verifiable.
- A listed path at HEAD is wrong.

While BLOCKED: exactly `file`, `reason`, `acceptance criterion`, one minimal question. Do NOT widen
scope silently.

---

## 11. Finish

Set `docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/REPORT.md` to **SUBMITTED** with: real
validation log (18 steps), real counts, fresh 7/7 baseline Run ID, protected-hash comparison,
files-changed list, exact session id + model/provider (ocg/deepseek-v4-flash, custom, reasoning max),
timestamps (local + UTC = local−7h, taken AT WRITE TIME — never future/estimated), and a per-finding
(C2-F1..F6) closure table with file:line + tests. No commit/push/merge/reset/stash. Manager verifies
independently; final C2 manager state = `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. A02-T01 remains NOT
APPROVED until Codex. STOP after C2 — no A02-T02/S07/S09.

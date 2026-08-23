# S08-A02-T01 — SceneGraph & Structural Evidence Bridge: Domain, Persistence, Migration and API Contract

**Status:** PLANNED
**Session type:** NEW Hermes coding session (single writer; never reuse `20260819_172534_b0ad63` or any H02/C1 session)
**Model:** `deepseek-v4-flash` via provider `custom:vietapi`, reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 187 `git status --short` entries (INTENTIONAL — never reset/clean/restore/checkout/stash/commit/push/merge)
**Migration head before T01:** `f7a8b9c0d1e2` (file `migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py` — next migration must set `down_revision = "f7a8b9c0d1e2"`)
**Depends on:** S08-A01-C1 `APPROVED_WITH_NON_BLOCKING_PROCESS_CORRECTION` (Codex bridge review 2026-08-19; see `docs/pm/sessions/S08-A01-C1-taxonomy-safety-correction/REPORT.md` appended Codex section)
**Sprint:** S08-A02 — SceneGraph & Structural Evidence Bridge (mini-sprint; this task is T01)

## Run timestamps (Codex protocol — new run id, real not approximated)

- writer_started_at_local / utc: (filled by writer at first write)
- writer_finished_at_local / utc: (filled by writer)
- writer_elapsed_seconds: (filled by writer)
- manager_review_started / finished: (filled by manager after writer exit)
- total_wall_clock_seconds: (filled by manager)

---

## 1. Outcome

Design and implement the versioned, generation-scoped, reversible contract for structural evidence that S08-A02-T02 (and later T02+/S07/S09) will use as its single durable truth. After T01, the database, ORM, repository/service, Pydantic schemas and isolated API can durably store, validate and round-trip every field the acceptance scenario requires — with no dangling reference, no silent history overwrite, full correction lineage, CAS/version semantics and a fully reversible migration that refuses atomically when data loss would occur.

T01 does NOT integrate a heavy AI model, does NOT ship a renderer, does NOT implement a dense optical-flow engine, does NOT regenerate video and does NOT build a large UI. It is the contract + persistence + migration + API/repository/schema surface only.

---

## 2. Required reading — READ FULLY before any write

All paths are inside worktree `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` unless noted.

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/sessions/S08-A01-C1-taxonomy-safety-correction/TASK.md` + `REPORT.md` + `LOG.md` (prior packet + the Codex APPROVED append at REPORT tail)
3. `app/persistence/models.py` — full file (ObjectRole/ObjectOccurrence/Artifact/ObjectRoleArtifact/Grouping/Correction/Job/Scene/VideoItem/Project/Workspace; OBJECT_KINDS, OBJECT_KIND_CHECK_SQL/PATTERN, constraints, FKs, indexes)
4. `migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py` (current head — next migration revises this) + `migrations/env.py` + `alembic.ini`
5. `app/persistence/object_intelligence.py` + `app/persistence/object_grouping.py` + `app/persistence/object_correction.py` (existing persistence owned by S08)
6. `app/schemas/object_intelligence.py` + `app/schemas/object_correction.py` + `app/schemas/object_grouping.py` + `app/schemas/object_extraction.py`
7. `app/api/routes/object_intelligence.py` + `object_grouping.py` + `object_correction.py` + `object_extraction.py` + `app/api/app.py` (router registration)
8. `app/persistence/engine.py` + `app/api/deps.py` + `app/config.py` (engine/factory/config patterns the new code must follow)
9. `tests/test_s08_a01_role_taxonomy.py` + `tests/test_s08_a01_c1_migration_safety.py` + `tests/test_object_intelligence_domain.py` (migration/domain test patterns for this codebase)
10. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` (migration/transaction/FK rules)
11. `frontend/AGENTS.md` (only if a minimal helper text is needed — T01 has no large UI)

Do NOT read PRD/Master Plan/milestone docs not listed. Do NOT roam the repo for opportunistic cleanup.

---

## 3. Scope — what T01 MUST deliver

### 3.1 Occurrence segments

- Stable occurrence/segment identity that survives edits and merges. Each occurrence-level record has a stable opaque id trusted as the durable join key (names are never joins).
- Frame/time range on every segment (frame_index/start_frame/end_frame + time_ms/start_time_ms/end_time_ms semantics matching the existing Scene contract; non-negative; end >= start).
- Generation ownership on every segment: `source_generation` (1..64 chars) and the producing `source_job_id` where applicable — nullable only when the generation is a user/manual correction. The record belongs to exactly one generation.
- Current vs historical generation awareness: a historical record is never silently overwritten; a correction that replaces evidence must archive the prior row and point the prior row at its successor (auditably, via a self-FK / supersession link, not deletion).
- CAS/version semantics: integer `revision` starting at 1, positive, bumped on every business mutation; stale revision is a 409 conflict.

### 3.2 Segmentation evidence

- Prompt points/boxes stored durably as structured evidence (not just a flattened bounding box). The existing `bbox_*` flat box remains but is accompanied by a prompt-evidence field (e.g. `prompt_json`/`segmentation_json`) that can hold an array of points `[{x,y,label}]` and/or boxes `[{x,y,w,h}]` in a deterministic JSON shape.
- Mask artifact references: a durable link from an occurrence/segment to the `artifact` row that holds its mask bytes (id-based, not path-guessed). At least one `artifact` FK reference for a segmentation mask, with proper FK and index.
- Provenance on every segmentation record: `algorithm`/`algorithm_version` (1..64 chars where present) or `confidence_source` enum (`model|detector|user|manual|derived`) as the durable source tag — plus `reasons_json`/`provenance_json` where rationale is stored.
- Confidence on every segmentation record: 0..1 float, validated by CHECK.

The segmentation evidence contract is REQUIRED; what T01 does NOT do is integrate a heavyweight segmentation model to produce the masks.

### 3.3 Motion evidence contract

- Camera-relative transforms contract: a durable, versioned structure for a per-segment camera transform (e.g. 2D affine/homography parameters as a deterministic JSON blob with provenance + confidence). Stored per segment/occurrence, not per frame unless the segment's temporal range is per-frame granular.
- Object-relative transforms contract: a durable structure for per-object relative motion (translation/rotation/scale or affine) with the same provenance/confidence/versioning discipline.
- Point/track/flow evidence references: the motion record holds durable references (ids or deterministic JSON pointers) to its point-correspondence / track / sparse-flow evidence. For T01 these are reference fields + provenance + confidence on the motion record — the engine that computes dense flow is out of scope and must not be implemented here.
- For T01 the motion tables/fields are CONTRACT-ONLY where a compute engine would later write: T01 stores and validates the structures and references but does NOT run a dense optical-flow engine.

### 3.4 Scene graph

- Durable tables/structures that make a character-using-a-phone scene describable and queryable without a renderer.
- Visibility state per occurrence/segment (`visible|occluded|out_of_frame|hidden` or equivalent enum — choose one canonical set and enforce it with a CHECK).
- Z-order / depth ordering per segment (integer or float ordering key with deterministic tie-break; validated range; persisted, not inferred).
- Occlusion edges: a durable edge from an occluder occurrence/segment to an occludee occurrence/segment, with temporal validity (`start_frame/end_frame` or `start_time_ms/end_time_ms`), provenance and confidence.
- Contact edges/events: a durable edge/event between two occurrences/segments (e.g. hand↔phone, character↔phone) with temporal validity, provenance and confidence plus a stable contact kind.
- Temporal validity on every scene-graph row: either inherited from the referenced occurrence/segment range or stored explicitly and validated `end >= start`.
- Source/target occurrence references are real FKs to the occurrence/segment table, never dangling, indexed, with `RESTRICT` delete and `foreign_key_check` clean.
- Provenance and confidence on every scene-graph row (algorithm/version or confidence_source + confidence 0..1).

### 3.5 Integrity invariants

- No dangling reference: every FK resolves; `PRAGMA foreign_key_check` returns zero rows on every migration path and in tests that exercise the full graph.
- Generation-ownership check: a row whose `source_generation` is set must belong to that generation; a correction that writes a new generation must not silently mutate a historical row — it must create a successor and supersede the prior row.
- No silent overwrite of historical evidence: an `UPDATE` that would shadow a prior segment/evidence row without a supersession link is forbidden by repository/service validation. Historical rows remain queryable.
- Correction lineage traceability: every superseded row points to its successor (self-FK `superseded_by_id` or equivalent natural-key chain) and `result_json`/`impact_json` style audit is kept where a correction archival pattern already exists. A full lineage for an occurrence/segment is queryable by walking the supersession chain.
- CAS/version enforcement: stale `revision` on any of the new tables yields 409.

All invariants above must be enforced by DB constraints + ORM + repository/service validation (not only by a single layer), and demonstrated by tests.

### 3.6 Migration

- Exactly ONE new Alembic revision file `migrations/versions/<new_id>_*.py` immediately after `f7a8b9c0d1e2` with `down_revision = "f7a8b9c0d1e2"`.
- Reversible `upgrade()` / `downgrade()`. `upgrade` creates every new table/constraint/index/FK introduced by T01 in ONE migration. `downgrade` drops them in dependency-safe order (reverse of upgrade) and leaves the DB at `f7a8b9c0d1e2`.
- Downgrade must FAIL ATOMICALLY when data introduced by the new migration would be lost: if any row exists in any new table, `downgrade` must refuse BEFORE any DDL/data mutation (pre-check; no partial mutation; alembic exits non-zero; revision/DDL/rows/indexes/FKs byte-identical on refusal). This is the same fail-closed discipline as F1 — prove it with a focused test.
- After every mutation decision path the migration must run `PRAGMA integrity_check` (expect `ok`) and `PRAGMA foreign_key_check` (expect 0 rows) — same helper discipline as `f7a8b9c0d1e2`.
- `revision` identifiers are immutable once written; do not rename or reorder existing migrations.

### 3.7 API / repository / schema

- Deterministic serialization: JSON fields (`prompt_json`/`segmentation_json`/`transform_json`/`provenance_json`/edge payloads) round-trip byte-identically under `json.dumps(sort_keys=True)` or equivalent canonical ordering; tests must prove the round-trip.
- Validation: strict Pydantic validation (ranges, enums, required fields, mutually-exclusive fields where applicable); repository/service performs the same validation defensively and FK existence is checked in-repository before commit.
- CAS/conflict behavior: every mutating endpoint on the new resources requires and checks `revision` (or equivalent optimistic token); stale token → 409; 409 bodies are machine-readable and stable.
- Do NOT invent a contract outside this packet's scope: API nouns, route prefixes, schema field names and table names must stay within the structural-evidence nouns above.

### 3.8 Binary acceptance scenario (MUST be persistable and readable back)

Store and read back, in a single isolated test database (no MAIN db, no mocked engine), a scene that represents a person using a phone — containing at minimum ALL of the following, durably, with FK/Index/CHECK enforcement and deterministic serialization:

- a character occurrence
- a phone occurrence
- a hand anchor/evidence (prompt + confidence + provenance)
- a face anchor/evidence (prompt + confidence + provenance)
- a character-phone contact edge/event
- a visibility assertion (at least one `visible` and one `occluded` or `out_of_frame`)
- a z-order or occlusion assertion that distinguishes the phone over the hand or vice versa
- a camera-relative transform for the scene/segment
- a temporal range for every durable row involved
- provenance + confidence on every new evidence row

The acceptance scenario must be a single focused integration test that writes the full graph then reads it back and asserts identity/constraints/ordering/FKs — not a UI demo.

---

## 4. Out of scope — MUST NOT be implemented in T01

- No heavyweight AI model integration (SAM2.1, detector, tracker, captioner, etc.).
- No renderer / compositor / canvas preview.
- No dense optical-flow engine implementation.
- No video regeneration / re-render job.
- No S07 (Project cast reuse) or S09 (Demo-first reskin) code.
- No large frontend/UI feature for the evidence graph (at most a trivial deterministic helper text if an existing page needs a label — no new page/flow).

T01 is the durable contract. Any of the above started now will be treated as out-of-allowlist and will FAIL the task: the writer must instead set `REPORT.md` to `BLOCKED` with the exact file and reason if such scope is genuinely required — never expand the allowlist silently.

---

## 5. Allowed write scope (exact file allowlist — verified names at packet time)

The writer may ONLY write the files listed below. If any additional file is genuinely required, STOP with `REPORT.md = BLOCKED` and a single question naming the exact file, reason and acceptance criterion. The manager/user/Codex must approve explicitly — the writer never widens scope itself.

Verified at `a43b20d` — every listed path exists at HEAD or is the single new file kind:

**Backend — domain/persistence:**

- `app/persistence/models.py` — add the new occurrence-segment / segmentation / motion / scene-graph tables, constraints, indexes, FKs, `__all__` entries and generation/correction/version fields. No modification of existing table DDL beyond adding the new tables (and any shared constants imported by the new tables).
- `migrations/versions/<new_id>_s08_a02_structural_evidence.py` — ONE new revision after `f7a8b9c0d1e2` (`down_revision = "f7a8b9c0d1e2"`). Filename MUST contain `s08_a02` and `structural_evidence` so it is lexically unambiguous in review. The `revision` hex id must be exactly 12 lowercase hex characters (consistent with `f7a8b9c0d1e2` lineage). Upgrade + reversible downgrade + atomic refusal pre-check + PRAGMA integrity/FK checks.

**Backend — persistence/repository (pick the layout that matches current convention — choose ONE per area and keep it):**

- `app/persistence/structural_evidence.py` — NEW repository/service helpers for the structural-evidence graph (CRUD + generation ownership + supersession + CAS + FK existence + deterministic serialization helpers). Preferred single new file for the domain.
- If a split is architecturally unavoidable, the two-file form is allowed instead:
  - `app/persistence/occurrence_segment.py` + `app/persistence/scene_graph.py`
  - but in that case DO NOT also create `structural_evidence.py` — exactly one of the two layouts.

**Backend — schemas/API:**

- `app/schemas/structural_evidence.py` — NEW Pydantic schemas for every new resource (prompt/segmentation/motion/scene-graph/visibility/occlusion/contact + request/response DTOs, enums and validation). May also be `app/schemas/scene_graph.py` if the split layout is chosen — same layout rule as persistence.
- `app/api/routes/structural_evidence.py` — NEW isolated router under `/api/v2/structural-evidence` (or equivalently `/api/v2/scene-graph`; pick ONE prefix and keep it throughout — the prefix must be disjoint from all legacy routes and from `/api/v2/object-intelligence`). Routes: at minimum CRUD + CAS + list/get for the segment / visibility / occlusion / contact / motion resources needed by the acceptance scenario.

**Tests (all new, focused):**

- `tests/test_s08_a02_structural_evidence_migration.py` — migration upgrade→downgrade round-trip byte-identical when empty; atomic refusal when graph rows exist; DDL/rows/FKs/integrity byte-identical on refusal; `PRAGMA integrity_check`/`foreign_key_check` on both paths.
- `tests/test_s08_a02_structural_evidence_domain.py` — domain invariants: no-dangling-FK, generation ownership, no silent historical overwrite, correction lineage traceability, CAS/version 409, deterministic serialization round-trip.
- `tests/test_s08_a02_phone_interaction_scenario.py` — the full phone-interaction acceptance scenario (character + phone + hand/face anchors + contact + visibility + z-order/occlusion + camera-relative transform + temporal range + provenance/confidence; write then read-back; asserts ordering/FKs/constraints).

**Evidence:**

- `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/LOG.md` + `REPORT.md` + this `TASK.md` (the packet itself).
- `output/s08-a02-t01/` — the TASK-scoped evidence root for run-specific artifacts (never shared with another task's root). The writer may use an isolated subdir such as `output/s08-a02-t01/<run-id>/` for QA DB/logs if needed.
- `scripts/quality-baseline.ps1` — only to RECORD a fresh 7/7 Run ID (never to edit the script); the baseline summary belongs under `output/quality-baseline/<new-run>/`.

Functional production code belongs under `app/` and `migrations/` above. Test-scoped helpers and fixtures belong under `tests/`.

Any file not listed above is OUT OF ALLOWLIST. If a listed file does not exist at HEAD it must be CREATED by the writer; if it does exist it may be MODIFIED. No other file may be modified.

Note: the writer must verify each name with `grep -l`/`ls` at HEAD before assuming it. If the repo's actual file at HEAD differs from a name printed in this packet, the writer must STOP `BLOCKED` with the exact correction — do not guess.

---

## 6. Acceptance criteria (binary — every line must pass, otherwise the task is NOT done)

### AC1 — Occurrence segments

- Stable occurrence/segment id survives an edit (id unchanged, `revision` bumped, predecessor→successor supersession link written).
- Every segment persists `frame/time` range, validated `end >= start`, non-negative.
- Every segment persists `source_generation` (1..64) and nullable `source_job_id` FK, and the generation-ownership invariant is enforced.
- Both current and historical generations are queryable; a historical row is never silently mutated.

### AC2 — Segmentation evidence

- Prompt points/boxes round-trip deterministically (structured JSON, not a bare flat bbox).
- At least one mask artifact reference per segmentation record (FK to `artifact.id`, indexed).
- Provenance (`algorithm`/`algorithm_version` or `confidence_source` + reasons) and confidence 0..1 are persisted and validated, not merely flattened.

### AC3 — Motion evidence contract

- A camera-relative transform record round-trips (deterministic JSON + provenance/confidence + temporal validity + FK).
- An object-relative transform record round-trips with the same discipline.
- A point/track/flow evidence reference field round-trips as a durable reference (id or deterministic JSON pointer) on the motion record — without requiring a dense optical-flow engine.

### AC4 — Scene graph

- Visibility state per segment, constrained by CHECK to a canonical enum.
- Z-order persists and round-trips deterministically.
- Occlusion edge: source→target occurrence/segment with temporal validity + provenance/confidence, FK-enforced, no dangling.
- Contact edge/event: two occurrence/segment endpoints with temporal validity + provenance/confidence, FK-enforced, no dangling.
- Every scene-graph row has provenance + confidence and a validated temporal range.

### AC5 — Integrity

- `PRAGMA foreign_key_check` returns 0 rows for the full phone-interaction scenario graph.
- Generation ownership is enforced in repository/service (not only at the DB layer).
- A repository-level mutation that would silently overwrite a historical row is rejected (409 or explicit scope error) and leaves the historical row byte-identical.
- A correction/impact lineage for an occurrence/segment is traceable (`superseded_by_id` or equivalent chain).

### AC6 — Migration

- One new revision after `f7a8b9c0d1e2`; `upgrade → downgrade → upgrade` on an empty graph is byte-identical (DDL/rows/FKs/integrity).
- Downgrade with graph rows present REFUSES atomically (pre-check before DDL; alembic exits non-zero; revision/DDL/rows/indexes/FKs byte-identical; no partial mutation).
- `PRAGMA integrity_check` reports `ok` and `foreign_key_check` empty on every decision path.
- Migration tests prove the round-trip and the atomic refusal (separate focused suite, `-p no:cacheprovider`, isolated basetemp).

### AC7 — API / repository / schema

- Deterministic serialization: every JSON field in the new resources round-trips byte-identically under canonical encoding.
- Strict validation: out-of-range / enum-violating / dangling-FK inputs are rejected before commit with a stable 4xx.
- CAS/conflict: stale `revision` → 409 on every mutating endpoint; happy path bumps `revision`.
- No contract outside this packet: route prefix, table names and schema field names are within the nouns of §3.

### AC8 — Binary phone-interaction scenario

- The dedicated integration test writes and reads back the full scene described in §3.8 (character, phone, hand/face anchors, contact, visibility, z-order/occlusion, camera-relative transform, temporal ranges, provenance/confidence) with real FK/Index/CHECK enforcement and passes.

Any missing criterion is a FAIL — manager verification will run the same tests independently and will issue a correction if any line is not proven.

---

## 7. Required validation — exact order, fresh isolated roots (cache disabled)

Every step below must be run with `MOTIONFORGE_DATABASE_URL` UNSET and `-p no:cacheprovider` (or equivalently cache-disabled) and a shallow basetemp (e.g. `C:/Users/Admin/AppData/Local/Temp/s08a02t01-*`). QA or evidence servers must never use `data/motionforge.db` (the MAIN db).

Order is intentional (cheap → expensive):

1. Focused migration tests: `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider --basetemp=.../s08a02t01-mig`
   - Expects: round-trip byte-identical + atomic downgrade refusal + FK/integrity.
2. Focused domain tests: `python -m pytest tests/test_s08_a02_structural_evidence_domain.py -q -p no:cacheprovider --basetemp=.../s08a02t01-dom`
   - Expects: every integrity/CAS/serialization/generation invariant.
3. Phone-interaction scenario: `python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider --basetemp=.../s08a02t01-phone`
   - Expects: full write→read-back graph assertion with real FK/Index/CHECK.
4. Combined focused: `python -m pytest tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py tests/test_s08_a02_phone_interaction_scenario.py tests/test_s08_a01_role_taxonomy.py tests/test_object_intelligence_domain.py -q -p no:cacheprovider --basetemp=.../s08a02t01-focused`
   - Expects: focused + taxonomy + intelligence-domain fully green.
5. Full S08 regression: `python -m pytest tests/test_s08_a01_role_taxonomy.py tests/test_s08_a01_c1_merge_kind_safety.py tests/test_s08_a01_c1_migration_safety.py tests/test_s08_a01_c1_reclassify_source_overlay.py tests/test_s08_golden_object_intelligence.py tests/test_object_grouping.py tests/test_object_correction.py tests/test_object_correction_api.py tests/test_object_extraction*.py tests/test_object_intelligence_domain.py tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider --basetemp=.../s08a02t01-reg`
   - Expects: all S08 suites PASS (count to be reported in REPORT.md — writer must record the actual integer, not a guess).
6. Relevant S05/S06 regression is OPTIONAL for T01 (only if a shared constant/FK was touched) — if touched, run the relevant slice and record the count; if untouched, record reason in REPORT.md.
7. `python -m ruff check app tests` — exit 0.
8. `python -m mypy app` — 0 issues (or with the same 88-file count, 0 new issues beyond any pre-existing S08 baseline).
9. `git diff --check` — exit 0 (pre-existing LF→CRLF advisories only).
10. ONE fresh `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` — **7/7 PASS** with a NEW Run ID (after all focused gates are green). Gate 2 Python tests must pass; ruff/mypy/tsc/lint/build gates must pass. Summary under `output/quality-baseline/<new-run>/summary.json`.
11. Protected-data comparison at finish (same SHAs as A01-C1): MAIN `tests/fixtures/legacy_import/importable/channels.json` + `data/motionforge.db` + SAM2.1 checkpoint hashes byte-identical to the A01-C1 baseline; `git rev-parse HEAD` still `a43b20d`; no MAIN commit/push/merge.
12. `NO_LISTENERS` at finish: 0 listeners on `3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010` (or the TASK-configured QA list — writer must state which list it verified).

The writer must run EVERY step above, paste the verbatim commands + counts into `LOG.md`/`REPORT.md` and leave machine-readable artifacts (pytest logs, baseline summary) under `output/s08-a02-t01/`.

---

## 8. Migration invariants (normative — violation is a FAIL)

1. One `revision` hex id (12 lowercase hex chars), `down_revision = "f7a8b9c0d1e2"` — no second head.
2. `upgrade()` creates all new tables/constraints/indexes/FKs in dependency-safe order; `downgrade()` drops them in reverse order — no table left behind.
3. The `writable_schema` style may be used only if a CHECK-literal replacement is genuinely constraint-only; otherwise use explicit `op.create_table`/`op.create_index`/`op.create_foreign_key`.
4. Downgrade fail-closed: `_assert_no_structural_evidence_rows(conn)` style pre-check MUST run BEFORE any DDL/data mutation; refusal is `raise RuntimeError("refusing to downgrade: ... structural evidence rows exist ...")` or equivalent with the same stable words so tests can match it; on refusal: alembic exits non-zero, `alembic current` stays at the new head, DDL/rows/indexes/FKs/integrity byte-identical.
5. `PRAGMA integrity_check` → `ok` and `PRAGMA foreign_key_check` → empty on every mutation decision path (upgrade success + downgrade success + downgrade refusal).
6. `target_metadata = Base.metadata` already imports the new ORM tables so `alembic check`/`alembic history` remain coherent; no manual `sqlalchemy.url` assumption.

---

## 9. Required tests — summary

- `tests/test_s08_a02_structural_evidence_migration.py` — §6 AC6.
- `tests/test_s08_a02_structural_evidence_domain.py` — §6 AC1..AC5 + AC7 deterministic/CAS invariants.
- `tests/test_s08_a02_phone_interaction_scenario.py` — §6 AC8.
- Plus any focused API/repository helpers the writer adds to prove AC7 CAS/deterministic behaviour (must still be inside the allowlist's test files).

A test that mocks the engine or bypasses FK validation to green a suite is a weakened test and is a FAIL.

---

## 10. Expected artifacts at SUBMITTED

```
app/persistence/models.py                                (modified)
migrations/versions/<new_id>_s08_a02_structural_evidence.py  (new)
app/persistence/structural_evidence.py  OR  app/persistence/occurrence_segment.py + app/persistence/scene_graph.py  (new, exactly one layout)
app/schemas/structural_evidence.py  OR  app/schemas/scene_graph.py  (new)
app/api/routes/structural_evidence.py                   (new)
tests/test_s08_a02_structural_evidence_migration.py     (new)
tests/test_s08_a02_structural_evidence_domain.py        (new)
tests/test_s08_a02_phone_interaction_scenario.py        (new)
docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/{TASK,LOG,REPORT}.md
output/s08-a02-t01/                                       (evidence root; optional run-id subdir)
output/quality-baseline/<new-run>/summary.json            (fresh 7/7 Run ID)
```

No other production artifact is expected. Any extra production file outside the list is a scope violation unless it was `BLOCKED` and formally approved.

---

## 11. Protected files / hashes — MUST be byte-identical at finish

- `C:\Users\Admin\MotionForge2D` (MAIN) `HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (verify with `git -C C:/Users/Admin/MotionForge2D rev-parse HEAD`).
- Worktree `HEAD` remains `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (no commit/merge/reset).
- Worktree dirty baseline stays intentional (do not attempt to clean 187 entries); the writer's new files are in addition to that baseline, never a replacement.
- No MAIN DB/file (`data/motionforge.db`, `channels.json`, SAM2.1 checkpoint) is mutated by tests.
- `git diff --check` remains exit 0 (LF→CRLF advisories only).

---

## 12. Baseline commands — run exactly as written (fresh, isolated, MOTIONFORGE_DATABASE_URL unset)

```powershell
# 1 — migration (expect PASS)
python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01-mig

# 2 — domain (expect PASS)
python -m pytest tests/test_s08_a02_structural_evidence_domain.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01-dom

# 3 — phone scenario (expect PASS)
python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01-phone

# 4 — combined focused (expect PASS)
python -m pytest tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py tests/test_s08_a02_phone_interaction_scenario.py tests/test_s08_a01_role_taxonomy.py tests/test_object_intelligence_domain.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01-focused

# 5 — full S08 regression (expect PASS — writer records the actual integer N)
python -m pytest tests/test_s08_a01_role_taxonomy.py tests/test_s08_a01_c1_merge_kind_safety.py tests/test_s08_a01_c1_migration_safety.py tests/test_s08_a01_c1_reclassify_source_overlay.py tests/test_s08_golden_object_intelligence.py tests/test_object_grouping.py tests/test_object_correction.py tests/test_object_correction_api.py tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_extraction_production_wiring.py tests/test_object_intelligence_domain.py tests/test_s08_a02_structural_evidence_migration.py tests/test_s08_a02_structural_evidence_domain.py tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01-reg

# 7/8/9 — static quality
python -m ruff check app tests
python -m mypy app
git diff --check

# 10 — quality baseline (expect 7/7 PASS, new Run ID)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
```

---

## 13. Stop conditions — set `REPORT.md` to `BLOCKED` and ask ONE minimal question

- Need to write a file outside the allowlist in §5.
- Detect a risk of silent data loss on the new migration/downgrade path.
- Requirements in §3/§6 are contradictory or not mechanically verifiable.
- A dependency that is assumed by the packet cannot be located at HEAD (missing router/persistence/schema file whose name was printed wrong in the packet).

In `BLOCKED` the writer must state exactly: `file`, `reason`, `acceptance criterion that forces it`, and a minimal question. Do NOT attempt to expand scope silently and do NOT continue to green a subset while ignoring the blocker.

---

## 14. Downgrade / rollback behavior (normative)

- `upgrade` succeeds once; re-running `upgrade head` is idempotent (no-op when already at head).
- `downgrade -1` from the new head to `f7a8b9c0d1e2` succeeds when the graph is empty and leaves the DB byte-identical to a DB that was never upgraded.
- `downgrade -1` with ANY structural-evidence row present refuses atomically (see §8 invariant 4); the refusal leaves revision/DDL/rows/indexes/FKs/integrity byte-identical; a test must prove the refusal and the byte-identical post-condition.
- There is no implicit ORM `Base.metadata.create_all` path for production/MAIN databases — migrations own production DDL; tests may use `Base.metadata.create_all` on isolated temp DBs only.

---

## 15. Finish

Fill `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/REPORT.md` with status **SUBMITTED** (never self-APPROVED), a full validation log, the actual test integers, the fresh baseline Run ID, the protected-hash comparison and the files-changed list. No `TASK.md`/`PM_REVIEW.md` change (there is no PM_REVIEW for T01 yet); no `commit`/`push`/`merge`/`reset`/`restore`/`checkout`/`clean`/`stash`. The Hermes manager verifies independently after exit; final manager verdict is `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. Tell the user immediately after manager verification (do not auto-start `S08-A02-T02`).


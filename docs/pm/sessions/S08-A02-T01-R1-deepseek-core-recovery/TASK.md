# S08-A02-T01-R1 — DeepSeek Core Recovery (Domain, Migration, Persistence)

**Status:** PLANNED (writer will set SUBMITTED; manager/Codex review owns approval — never self-approve)
**Session type:** NEW Hermes coding session (single writer; never reuse any prior A02/H02/C1 session)
**Model:** `ocg/deepseek-v4-flash` via provider `custom`, reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 190 `git status --short` entries (INTENTIONAL — never reset/clean/restore/checkout/stash/commit/push/merge)
**Migration head:** `a0b1c2d3e4f5` (the draft revision — MAY be rewritten in R1; verified unreleased, no DB at this revision)
**Upstream revision:** `f7a8b9c0d1e2` (the `down_revision` anchor — immutable)

---

## 0. Recovery context (read FIRST)

S08-A02-T01 was previously written by a writer round that left the task at **PLANNED** and produced
an **untrusted partial output** (incident `ABORTED_UNTRUSTED_PARTIAL_OUTPUT` appended to
`docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/REPORT.md`). The current code in
`app/persistence/models.py`, `app/persistence/structural_evidence.py`, and the migration
`migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` is an **unapproved draft** — it must
be audited and corrected, not treated as submitted.

The Codex BLOCKING FINDINGS (F1…F11 below) are normative: R1 must close every one of them with real
code + a passing test that would fail on the draft. R1 does NOT build the schema/API layer — that is
R2, only after Codex approves R1's core. Do NOT treat A02-T01 as complete until R2 also passes.

---

## 1. R1 outcome

Deliver a corrected, verified **domain model + migration + persistence repository** for the
structural-evidence contract (occurrence segments / segmentation / motion / scene-graph occlusion &
contact), with the draft's Codex findings closed and full repository-level tests (migration, domain,
phone-interaction scenario) green. R1 ends at `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. No schema, no
router, no frontend.

---

## 2. Required reading — READ FULLY before any write

All paths inside worktree `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` unless noted.

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md` (original A02 contract — scope/AC §3–§6 remain the contract R1 must satisfy at the persistence layer)
3. `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/REPORT.md` (the appended ABORTED incident)
4. `docs/pm/sessions/S08-A01-C1-taxonomy-safety-correction/TASK.md` + `REPORT.md` + `LOG.md`
5. `app/persistence/models.py` (full file; A02 block ~line 1498–1920; S05–A01 code is protected)
6. `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` (draft — rewrite allowed) + `f7a8b9c0d1e2_object_role_7_kind_taxonomy.py` (anchor) + `migrations/env.py` + `alembic.ini`
7. `app/persistence/object_intelligence.py` (RepoAuthority pattern: `current_generation`, ownership, CAS, idempotency) + `app/persistence/object_grouping.py` + `app/persistence/object_correction.py`
8. `app/persistence/engine.py` + `app/api/deps.py` + `app/config.py`
9. `tests/test_s08_a01_c1_migration_safety.py` + `tests/test_s08_a01_role_taxonomy.py` + `tests/test_object_intelligence_domain.py` (+ conftest `client` fixture rules)
10. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`

Do NOT read PRD/Master Plan/milestone docs not listed. Do NOT roam the repo for opportunistic cleanup.

---

## 3. R1 write scope (exact allowlist — verified names at packet time)

The writer may ONLY modify/create the files below. Any other file → STOP `BLOCKED` with one question.

**Allowed to modify:**

- `app/persistence/models.py` — ONLY the A02-specific block: A02 exports/constants and the A02 model
  classes (`OccurrenceSegment`, `SegmentMotion`, `SceneGraphOcclusion`, `SceneGraphContact` + their
  CHECK/unique/index/FK/supersession/idempotency columns). **Do NOT broad-format or rewrite S05–A01
  code/classes/constants.** Non-A02 code must remain byte-identical (manager will diff).
- `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` — REWRITE allowed to match the
  corrected contract. `revision = "a0b1c2d3e4f5"`, `down_revision = "f7a8b9c0d1e2"`. Verified no DB
  anywhere is at this revision (MAIN is at `d5e6f7a8b9c0`; old output DBs at `e7f8a9b0c1d2` /
  `f6a7b8c9d0e1`); it is unreleased and safe to rewrite. **Test ONLY on fresh temp DBs — NEVER run
  alembic against MAIN or any user DB, never upgrade/downgrade a shared DB.**
- `app/persistence/structural_evidence.py` — REWRITE allowed (this is the unapproved A02 repository
  file; the draft is not trusted).

**Allowed to create:**

- `tests/test_s08_a02_structural_evidence_migration.py`
- `tests/test_s08_a02_structural_evidence_domain.py`
- `tests/test_s08_a02_phone_interaction_scenario.py`
- `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/LOG.md` + `REPORT.md` (packet files)
- `output/s08-a02-t01-r1/<run-id>/` — evidence (QA DBs, pytest logs, baseline summary)

**Forbidden in R1 (R2 owns these):**

- `app/schemas/structural_evidence.py` (does NOT exist — do not create)
- `app/api/routes/structural_evidence.py` (does NOT exist — do not create)
- `app/api/app.py`, `app/api/deps.py`
- frontend anything
- S07/S09, extraction engine, renderer, dense optical flow, video regeneration
- MAIN (`C:\Users\Admin\MotionForge2D`) — never touched
- `scripts/quality-baseline.ps1` (run only, never edit)

If a file outside this list is genuinely required, set `REPORT.md = BLOCKED` with exactly one
question naming the file, reason and acceptance criterion. Never widen scope silently.

---

## 4. Codex blocking findings — R1 MUST close all (normative)

### F1 — Runtime import failure
Draft dataclasses (`SegmentRecord`, `MotionRecord`, `OcclusionRecord`, `ContactRecord`) order
`default` fields before non-default fields → `TypeError: non-default argument 'visibility' follows
default argument` on import. Fix field order or defaults so every dataclass imports cleanly.
REQUIRED: an import-smoke test that really imports `app.persistence.models` AND
`app.persistence.structural_evidence` (fail-closed).

### F2 — Logical identity vs record-version identity are conflated
The design claims stable IDs but supersession mints a new id. Distinguish, durably and in the ORM:
- **stable logical segment/lineage ID** — survives edits/supersession (same lineage, same logical id);
- **immutable evidence-record/version ID** — unique per version row.

One correction must: create a successor record, KEEP the same logical lineage ID, set
`predecessor.superseded_by_id` → successor record id, never delete the predecessor, and keep BOTH
current and historical rows queryable. Display name must never be an identity/join key.

### F3 — Natural key blocks historical/current versions
Draft unique constraint `(role_id, scene_id, start_frame, end_frame, name)` makes a successor of the
same occurrence or a newer generation conflict. Redesign uniqueness so:
- multiple versions/generations can coexist;
- retry idempotency stays safe;
- no accidental duplicate ACTIVE record;
- SQLite actually enforces it (partial unique index on `WHERE superseded_by_id IS NULL` is a preferred
  mechanism — verify it reflects and enforces in SQLite 3.45).

### F4 — Wrong current-generation authority
Do NOT maintain a naive max-generation+1 copy in `structural_evidence.py`. Use the existing
backend-authoritative authority from `ObjectIntelligenceRepository` (`current_generation(...)` /
`_current_generation_for_source`) or the shared helper the packet permits. Generation must consider:
workspace ownership, video ownership, current source artifact SHA, a completed `DISCOVER_OBJECTS` job,
and input generation. Never derive from client hints or max+1 for every source.

### F5 — Cross-workspace / cross-video ownership
Creating a segment must validate the FULL chain:
- workspace → project → video → scene;
- workspace / video → role;
- video / source generation → job;
- workspace / owner / purpose → mask artifact.
A role/scene/job/artifact merely "existing" is insufficient. REQUIRED tests proving each of these
fail BEFORE commit and create NO row:
- role from another video;
- scene from another video;
- artifact from another workspace;
- job owned by someone else;
- job of a different generation.

### F6 — Segmentation / mask contract
When a segment carries segmentation evidence:
- `mask_artifact_id` is REQUIRED;
- the artifact must exist and belong to the correct ownership;
- prompt points/boxes must have a strict shape;
- confidence / provenance must be valid;
- **NaN / Infinity in JSON must be rejected**;
- **malformed durable JSON must NOT silently become a default** (draft's `parse_json` returning
  default on parse failure is unacceptable — fail closed with a stable error).

### F7 — Supersession and lineage
Fix `segment_lineage` to:
- accept ANY version in a lineage;
- find the oldest predecessor;
- return oldest → newest;
- detect cycles / dangling links;
- never return a reversed result.
Correction must run atomically: create successor + CAS predecessor, and ROLL BACK the whole
transaction if stale/conflict.

### F8 — Historical mutation safety
Every update/supersede of segment, motion, contact and occlusion must:
- check workspace/video ownership;
- check endpoint/current generation;
- refuse historical/superseded records;
- treat stale revision as a stable conflict;
- perform ZERO mutation on conflict.
For motion/contact/occlusion that carry `superseded_by_id`: EITHER implement real supersession
semantics with tests, OR remove the dead column. No dead lineage fields without a contract.

### F9 — Idempotency
`idempotency_key` must be USE, not just stored:
- workspace-scoped uniqueness;
- replay same key + same canonical payload → returns the existing record;
- same key + different payload → conflict;
- concurrent retry creates no duplicate;
- the natural key must NOT be treated as an idempotency key.

### F10 — Temporal and endpoint invariants
Enforce, on every create/update:
- `end >= start` for frames and time;
- edge/motion range within the segment range;
- contact/occlusion endpoints in the SAME video and compatible generation;
- self-edge rejected;
- confidence in 0..1;
- z-order, visibility, contact kind belong to the canonical enum.

### F11 — Migration / ORM parity
Migration must match the ORM exactly:
- tables, columns, nullability;
- CHECK constraints;
- FK delete policy;
- indexes / unique indexes (including partial unique);
- server defaults;
- `revision` / `down_revision`.

One migration after `f7a8b9c0d1e2` (i.e. `a0b1c2d3e4f5`). May rewrite the current draft because it
is unreleased, but: only test on a temp DB; never migrate/downgrade MAIN or a user DB; confirmed no
shared DB is at this revision. Downgrade behavior:
- empty graph → success;
- any structural row → REFUSE before any DDL;
- on refusal revision/schema/rows/indexes/FK unchanged;
- `integrity_check` ok;
- `foreign_key_check` empty.

---

## 5. Reuse (after independent verification, not blind copy)

Reusable concepts (verify each invariant before keeping):
- four-resource direction: occurrence segment / segment motion / occlusion / contact;
- `down_revision = "f7a8b9c0d1e2"`;
- fail-closed downgrade pre-check;
- canonical JSON concept;
- CAS conditional update;
- FK / index / CHECK-constraint concept.

DeepSeek must review each invariant; do not copy the draft verbatim just because it exists.

---

## 6. Required tests (new files only, repository-level — R1 has NO API)

All under `tests/`. Use the conftest `client` fixture only if an endpoint is genuinely exercised
(none expected in R1); otherwise test repositories/session directly on isolated temp DBs.

1. `tests/test_s08_a02_structural_evidence_migration.py`
   - import-smoke: import `app.persistence.models` + `app.persistence.structural_evidence`;
   - upgrade → downgrade → upgrade byte-identical on empty graph;
   - atomic downgrade refusal with any structural row present (revision/DDL/rows/indexes/FK unchanged);
   - migration/ORM parity assertions (columns, CHECK, FK policy, indexes, server defaults);
   - `PRAGMA integrity_check` / `PRAGMA foreign_key_check` on every path.

2. `tests/test_s08_a02_structural_evidence_domain.py`
   - F2: logical lineage id stable across supersession; per-version record id distinct; predecessor
     superseded → successor; both current + historical queryable; names never identity.
   - F3: multiple versions/generations coexist; no duplicate ACTIVE record; idempotent retry safe.
   - F4: generation authority matches `ObjectIntelligenceRepository.current_generation` (not max+1).
   - F5: every cross-workspace/video/job/artifact ownership violation fails pre-commit, zero rows.
   - F6: mask required + owned; strict prompt shape; NaN/Infinity rejected; malformed JSON fails closed.
   - F7: lineage walker oldest→newest on any version; cycle/dangling detection; atomic correction +
     rollback on stale/conflict.
   - F8: historical/superseded mutation refusal; stale revision → stable conflict; zero mutation.
   - F9: idempotency replay/payload-conflict/workspace-scoped/concurrent no-dup.
   - F10: temporal/endpoint/self-edge/confidence/enum invariants.

3. `tests/test_s08_a02_phone_interaction_scenario.py`
   Full phone-interaction graph write→read-back on one isolated DB, with real FK/CHECK/index
   enforcement AND current+historical lineage read-back: character, phone, hand anchor, face anchor,
   character/hand–phone contact, visibility, z-order/occlusion, camera-relative transform, temporal
   ranges, provenance/confidence. Read back BOTH current and a corrected historical lineage.

---

## 7. Validation order (fresh isolated roots, cache disabled)

`MOTIONFORGE_DATABASE_URL` UNSET and `-p no:cacheprovider`. Shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-*` (avoid MAX_PATH). Run EVERY step, paste verbatim
commands + real counts into LOG/REPORT:

1. Import smoke: `python -c "import app.persistence.models; import app.persistence.structural_evidence"` → OK
2. Migration tests: `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-mig`
3. Domain tests: `python -m pytest tests/test_s08_a02_structural_evidence_domain.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-dom`
4. Phone scenario: `python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-phone`
5. Combined A02 focused: migration + domain + phone + `tests/test_s08_a01_role_taxonomy.py` + `tests/test_object_intelligence_domain.py`
6. A01-C1 + object-intelligence regression: `tests/test_s08_a01_c1_merge_kind_safety.py tests/test_s08_a01_c1_migration_safety.py tests/test_s08_a01_c1_reclassify_source_overlay.py tests/test_s08_a01_role_taxonomy.py tests/test_object_intelligence_domain.py`
7. Full S08 relevant regression: all S08 suites (record the real integer count)
8. `python -m ruff check app tests` → exit 0
9. `python -m mypy app` → 0 issues (or only the S08 pre-existing count, no new)
10. `git diff --check` → exit 0 (LF→CRLF advisories only)
11. ONE fresh `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` → 7/7 PASS, new Run ID
12. Protected hashes: MAIN HEAD still `a43b20d`; A01-C1 protected files byte-identical
13. `NO_LISTENERS` at finish on QA list

---

## 8. Stop conditions — REPORT = BLOCKED + exactly ONE minimal question

- Need to write a file outside the R1 allowlist (§3).
- A draft invariant is required that contradicts another accepted invariant and is not mechanically
  verifiable.
- The `ObjectIntelligenceRepository` generation authority cannot be wired without touching a
  forbidden file.
- A listed path at HEAD is wrong.

In `BLOCKED` state exactly: `file`, `reason`, `acceptance criterion`, one minimal question. Do NOT
silently expand scope.

---

## 9. Finish

Set `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/REPORT.md` to **SUBMITTED** (never
self-APPROVED) with full validation log, real counts, fresh baseline Run ID, protected-hash
comparison, files-changed list, exact session id + model/provider displayed, and a per-finding
(F1…F11) closure table. No commit/push/merge/reset/restore/checkout/clean/stash. The manager
verifies independently; final manager state = `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`, then stop
(no R2, no S07/S09).

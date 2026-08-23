# S08-A02-T01-R1-C1 — Generation, Idempotency and Temporal Integrity Correction

**Status:** PLANNED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Session type:** NEW Hermes coding session (single writer; NEVER reuse `20260820_001637_df0f17` or any R1/A02/H02/C1 session)
**Model:** `ocg/deepseek-v4-flash` via provider `custom`, reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 194 `git status --short` entries (INTENTIONAL — never reset/clean/stash/restore/checkout/commit/push/merge)
**Migration head:** `a0b1c2d3e4f5` (`down_revision = "f7a8b9c0d1e2"`; unreleased — rewrite allowed, temp DBs only)
**Depends on:** S08-A02-T01-R1 (Codex verdict: **CHANGES_REQUESTED** — appended to R1 REPORT.md)
**Sprint:** S08-A02 — SceneGraph & Structural Evidence Bridge (mini-sprint correction C1)

---

## 0. Context — why C1 exists

Codex reviewed S08-A02-T01-R1 and returned **CHANGES_REQUESTED**. F1–F11 from the original
blocking findings are NOT considered fully closed. C1 is a semantically-targeted correction of
seven specific integrity areas found during review. Do NOT treat the R1 REPORT as authoritative —
**re-audit the current code against each C1 finding**, write a test that fails on the current
behavior, then fix.

The seven C1 findings (C1-F1 … C1-F7) below are NORMATIVE. Each requires real code + a failing-then-passing
test. Where the brief offers a recommended design, implement it unless you can prove an equivalent
design with real SQLite constraints + concurrency tests + migration/ORM parity + no weakened history
behavior.

---

## 1. Required reading — READ FULLY before any write

All paths inside worktree `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` unless noted.

1. `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md` + `REPORT.md` + `LOG.md`
2. `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md` (original A02 contract)
3. `app/persistence/models.py` — full file; A02 block (~lines 1498–1961) + constants
4. `app/persistence/structural_evidence.py` — full current file (critical: `supersede_segment`, `create_segment`,
   `create_motion`/`create_occlusion`/`create_contact`, `_assert_range_within`, idempotency equivalence helpers)
5. `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` — current migration
6. `app/persistence/object_intelligence.py` — `ObjectIntelligenceRepository.current_generation` /
   `_current_generation_for_source` (the single generation authority)
7. `tests/test_s08_a02_structural_evidence_migration.py`, `tests/test_s08_a02_structural_evidence_domain.py`,
   `tests/test_s08_a02_phone_interaction_scenario.py` — current A02 tests
8. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md` — migration/transaction/FK rules
9. `tests/uploads/…` if any — ignore unless referenced by the required-phrase tests

Do NOT read PRD/Master Plan/milestone docs not listed. Do NOT roam the repo.

---

## 2. Write allowlist (exact — verified names)

**Allowed to modify:**
- `app/persistence/models.py` — ONLY the A02 block: A02 constants/exports and the A02 model classes
  (`OccurrenceSegment`, `SegmentMotion`, `SceneGraphOcclusion`, `SceneGraphContact` + their
  CHECK/unique/index/FK/supersession/idempotency columns). S05–A01 must remain byte-identical.
- `app/persistence/structural_evidence.py` — C1 fixes (generation, logical identity, idempotency,
  containment, artifact, validation, delete policy).
- `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` — can be rewritten to match the
  corrected contract. `revision = "a0b1c2d3e4f5"`, `down_revision = "f7a8b9c0d1e2"`. No second head.
  A02 is unreleased so the migration may be rewritten; test ONLY on fresh temp DBs — NEVER against
  MAIN or any user DB.
- `tests/test_s08_a02_structural_evidence_migration.py` — extend with C1 migration/parity assertions
- `tests/test_s08_a02_structural_evidence_domain.py` — extend with C1 domain assertions
- `tests/test_s08_a02_phone_interaction_scenario.py` — extend if needed (must keep passing)

**Allowed to create:**
- `tests/test_s08_a02_r1_c1_semantic_safety.py` — the dedicated C1 test file (all C1 required tests)
- `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/LOG.md` + `REPORT.md` (packet files)
- `output/s08-a02-t01-r1-c1/<run-id>/` — evidence

**Allowed to append:**
- `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/REPORT.md` (only append; never edit history)
- `output/MANAGER_STATE.md` (manager does this between sessions — writer must NOT)

**Forbidden:**
- `app/schemas`, `app/api`, `app/api/app.py`, `app/api/deps.py`
- frontend
- object extraction / grouping / correction production code
- S07/S09, renderer, dense optical flow, video regeneration
- the 8 pre-existing head-bump test files (role_taxonomy, object_intelligence_domain, object_grouping,
  object_correction, object_extraction, s08_a01_c1_migration_safety, persistence_bootstrap,
  durable_job_persistence) — do NOT touch
- MAIN (`C:\Users\Admin\MotionForge2D`) — never
- `scripts/quality-baseline.ps1` (run only, never edit)

If a file outside the allowlist is genuinely required, STOP → `REPORT.md = BLOCKED` → exactly ONE
minimal question. Do NOT use "best judgement" to widen the write scope; if the blocker is real and
unanswered, transition to read-only planning instead (per overnight protocol §16).

---

## 3. C1-F1 — Generation semantics (NORMATIVE)

**Current bug:** `supersede_segment()` REQUIRES `source_generation != prior.source_generation`,
then creates a successor with an arbitrary generation. But
`ObjectIntelligenceRepository.current_generation()` still returns the OLD generation, so the freshly
created successor is immediately stale and cannot be updated.

**Redesign into TWO explicit workflows:**

**A. Manual/user correction IN the current source generation**
- predecessor must be current AND active;
- successor keeps the SAME `source_generation`;
- logical lineage unchanged; new record/version id;
- predecessor → historical/read-only; successor → current/mutable;
- predecessor CAS;
- atomic transaction;
- provenance / `confidence_source` must reflect user/manual (must NOT silently inherit
  `confidence_source=model`);
- the underlying extraction's source job MAY be kept as provenance if the contract defines it so.

**B. Re-analysis TRANSITION to a new source generation**
- target generation MUST equal `ObjectIntelligenceRepository.current_generation()`;
- producing `source_job_id` REQUIRED;
- job must be a COMPLETED `DISCOVER_OBJECTS` job;
- job owner/video/workspace/source SHA/input generation must all match;
- prior may be from an older generation but must be the ACTIVE lineage version;
- predecessor → successor link atomic;
- successor must become current/mutable.

Callers must NOT create arbitrary future/stale generations. The public create path must FAIL
CLOSED when: `source_generation` differs from the backend authority; model/detector evidence lacks a
producing job; job generation mismatches; `role.source_generation` is incompatible; source SHA
does not match the current source.

**Required tests (put in `tests/test_s08_a02_r1_c1_semantic_safety.py`):**
1. Manual correction same generation succeeds.
2. Successor is still current and updatable.
3. Predecessor becomes historical/read-only.
4. Arbitrary future generation rejected.
5. Stale generation rejected.
6. Re-analysis transition to the true current generation succeeds.
7. Wrong/missing producing job rejected.
8. Role-generation mismatch rejected.
9. Failure leaves zero mutation.

---

## 4. C1-F2 — Logical identity and branch safety (NORMATIVE)

**Current bug:** `logical_id` can still be passed arbitrarily by the caller. There is only an
index (`ix_occurrence_segment_logical_id`), no uniqueness, no lineage versioning, no branch guard.

**Must ensure:**
- repository creates `logical_id` for the root (public caller cannot attach an arbitrary one);
- only the controlled successor/re-analysis path may reuse a `logical_id`;
- `logical_id` cannot be reused across workspace/project/video/role boundaries;
- `logical_id` gets validation (length/format);
- a lineage must NOT branch: one predecessor ≤ one successor; one successor ≤ one predecessor;
- concurrent supersede: only one request wins; loser rolls back entirely;
- cycle / dangling / branch detection fails closed.

**Recommended design:**
- `lineage_version` (or `version_number`) starting at 1;
- successor = `predecessor.lineage_version + 1`;
- `UNIQUE(workspace_id, logical_id, lineage_version)`;
- repository checks no gaps/branches;
- current version explicitly determinable (not only via the partial natural-key index).

(An equivalent design is allowed if proven with real SQLite constraints + concurrency tests +
migration/ORM parity + no weakened history behavior.)

**Required tests:**
1. Caller-attempted `logical_id` collision rejected.
2. Cross-workspace `logical_id` reuse rejected (or scoped exactly per contract).
3. Cross-video/role lineage reuse rejected.
4. Concurrent supersede creates exactly one successor.
5. Branch attempt rejected.
6. Lineage from ANY version returns oldest → newest.
7. Cycle/dangling/duplicate-predecessor fails closed.

---

## 5. C1-F3 — Complete idempotency (NORMATIVE)

**Current bug:** motion/occlusion/contact equivalence checks omit identity fields, so a replay with a
different identity (different segment/endpoint) is wrongly treated as a duplicate.

**Motion idempotency must compare:** `occurrence_segment_id`, `transform_type`, `start_frame`,
`end_frame`, `start_time_ms`, `end_time_ms`, `transform_json`, `point_track_flow_ref`,
`algorithm`/`algorithm_version`, `confidence`/`confidence_source`, `reasons`/`provenance`.

**Occlusion idempotency must compare:** `project_id`, `video_item_id`, `occluder_segment_id`,
`occludee_segment_id`, `start_frame`/`end_frame`, `start_time_ms`/`end_time_ms`,
`algorithm`/`algorithm_version`, `confidence`/`confidence_source`, `reasons`/`provenance`.

**Contact idempotency must compare:** `project_id`, `video_item_id`, `source_segment_id`,
`target_segment_id`, `contact_kind`, `start_frame`/`end_frame`, `start_time_ms`/`end_time_ms`,
`algorithm`/`algorithm_version`, `confidence`/`confidence_source`, `reasons`/`provenance`.

**Rules:**
- same workspace/key + same canonical identity/payload → replay existing row;
- same workspace/key + ANY differing field → stable conflict;
- conflict leaves zero mutation.

**Required tests:**
- motion different segment; motion different transform_type; motion different start frame;
- occlusion different/reversed endpoints; occlusion different start frame;
- contact different endpoint; contact different kind; contact different start frame;
- same key exact replay; concurrent exact replay creates ONE row.
- empty idempotency key: reject or normalize per an explicit contract;
- over-length key: reject BEFORE DB flush.

---

## 6. C1-F4 — Frame and TIME containment (NORMATIVE)

**Current bug:** `_assert_range_within` checks frames only.

**Must check BOTH:**
- `segment.start_frame <= child.start_frame` and `child.end_frame <= segment.end_frame`;
- `segment.start_time_ms <= child.start_time_ms` and `child.end_time_ms <= segment.end_time_ms`.

Applied to create/update for motion, occlusion, and contact. For contact/occlusion the range must be
within BOTH endpoint segments.

**Required tests:**
1. Valid frame but time outside segment → reject.
2. Valid time but frame outside → reject.
3. Update `end_time` beyond the segment → reject.
4. Update `end_frame` beyond the segment → reject.
5. Range inside source but outside target → reject.
6. Zero mutation after each reject.

---

## 7. C1-F5 — Ownership and artifact (NORMATIVE)

**Mask artifact MUST be:** same workspace; `kind=image`; `state=ready`; a valid
ownership/purpose association if the current artifact contract supports it. Reject arbitrary
video/audio/document artifacts; reject `staging`/`trash`/`missing`/`failed` states.

**Model/detector evidence:** `source_job_id` REQUIRED; job matches workspace/video/generation/source
SHA; job is a COMPLETED `DISCOVER_OBJECTS` job.

**User/manual evidence:** explicit provenance/source; `confidence_source` of `user`/`manual`; must not
inherit `model` silently.

**Segment kind:** must be compatible with `ObjectRole.kind`; a segment kind UPDATE must not diverge
from the role taxonomy; reclassification must use the explicit role/correction contract, not mutate
occurrence kind independently.

**Required tests:**
- non-image mask rejected; non-ready mask rejected; wrong-workspace mask rejected;
- missing model job rejected; wrong source SHA job rejected;
- role kind mismatch rejected; segment kind update mismatch rejected;
- failure leaves zero mutation.

---

## 8. C1-F6 — Domain validation (NORMATIVE)

Validate BEFORE DB flush:
- `algorithm` / `algorithm_version` length;
- idempotency key length;
- `reasons` must be a `list[str]`; `provenance` must be an object;
- `prompt.points` must be a list; `prompt.boxes` must be a list;
- each point must match an exact supported shape; each label non-empty;
- box width/height valid;
- NaN/Infinity rejected;
- malformed durable JSON rejected (fail closed — never silently becomes a default).

Do NOT catch every `IntegrityError` and misreport it as a duplicate. Only translate a unique/
idempotency conflict when the correct constraint is identified. FK/CHECK/ownership errors get a
stable, appropriate domain error.

---

## 9. C1-F7 — Durable delete policy (NORMATIVE)

**Audit current:** `object_role → occurrence_segment` is CASCADE; `occurrence_segment → segment_motion`
is CASCADE. Structural evidence is durable historical truth — deleting a role/segment must NOT
silently erase history.

**Change to RESTRICT** unless you prove an alternative design that preserves history.

**Required tests:**
- delete a referenced role does NOT delete segment history;
- delete a referenced segment does NOT delete its motion;
- delete fails closed;
- rows byte-identical after a failed delete;
- `PRAGMA foreign_key_check` empty.

---

## 10. Validation order (fresh isolated roots, cache disabled)

`MOTIONFORGE_DATABASE_URL` UNSET and `-p no:cacheprovider`; shallow basetemps under
`C:/Users/Admin/AppData/Local/Temp/s08a02t01r1c1-*` (avoid MAX_PATH). Run EVERY step; paste verbatim
commands + real counts into LOG/REPORT. Do NOT weaken/delete old tests; do NOT adjust expected
results to match wrong code.

1. Import smoke (models + structural_evidence).
2. `pytest tests/test_s08_a02_r1_c1_semantic_safety.py` — C1 suite.
3. `pytest tests/test_s08_a02_structural_evidence_migration.py`.
4. `pytest tests/test_s08_a02_structural_evidence_domain.py`.
5. `pytest tests/test_s08_a02_phone_interaction_scenario.py`.
6. Combined A02 focused (C1 + migration + domain + phone + role_taxonomy + object_intelligence_domain).
7. A01-C1 + object-intelligence regression (s08_a01_* + object_intelligence_domain + object_grouping + object_correction* + object_extraction*).
8. Full S08 relevant regression (all S08 suites, record the REAL integer).
9. Persistence bootstrap + durable job relevant tests.
10. `python -m ruff check app tests` → exit 0.
11. `python -m mypy app` → 0 issues (or S08-pre-existing count, no new).
12. `git diff --check` → exit 0 (LF→CRLF advisories only).
13. Migration/ORM parity.
14. Empty upgrade/downgrade round-trip.
15. Downgrade refusal with rows, atomic (revision/DDL/rows/indexes/FK byte-identical on refusal).
16. SQLite `PRAGMA integrity_check` → ok.
17. SQLite `PRAGMA foreign_key_check` → empty.
18. ONE fresh `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` → 7/7 PASS, new Run ID.
19. Protected hashes (MAIN HEAD, worktree HEAD, channels.json, data/motionforge.db unchanged).
20. NO_LISTENERS + process cleanup.

---

## 11. Stop conditions — REPORT = BLOCKED + exactly ONE minimal question

- Need to write a file outside the C1 allowlist (§2).
- A C1 requirement contradicts another accepted invariant and is not mechanically verifiable.
- The recommended design requires touching a forbidden file to be implemented.

While BLOCKED: exactly `file`, `reason`, `acceptance criterion`, one question. Do NOT widen scope
with "best judgement". If the user cannot answer, transition to read-only planning and keep working
usefully (overnight protocol).

---

## 12. Finish

Set `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/REPORT.md` to **SUBMITTED** with: real
validation log, real counts, fresh baseline Run ID, protected-hash comparison, files-changed list,
exact session id + model/provider (ocg/deepseek-v4-flash, custom, reasoning max), per-finding
(C1-F1…F7) closure table, and timestamps (local + UTC correct timezone). No commit/push/merge/
reset/stash. Manager verifies independently; final C1 manager states are
`MANAGER_VERIFIED_FOR_OVERNIGHT_CONTINUATION_PENDING_CODEX_REVIEW` (on pass) or BLOCKED (after ≤2
correction cycles).

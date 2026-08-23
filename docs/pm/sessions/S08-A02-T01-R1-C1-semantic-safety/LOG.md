# S08-A02-T01-R1-C1 — Generation, Idempotency and Temporal Integrity Correction — LOG

## Session metadata

- Session ID (Hermes): `20260820_024607_7d7552`
- Model (displayed): `ocg/deepseek-v4-flash` via provider `custom` (9Router 127.0.0.1:20128), reasoning `max`
- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
- HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (unchanged at finish)
- MOTIONFORGE_DATABASE_URL: UNSET at start and finish (verified)
- Migration head: `a0b1c2d3e4f5` (single head, `down_revision = "f7a8b9c0d1e2"`)
- writer_started_at_local: 2026-08-20T02:47+07:00 (UTC 2026-08-19T19:47Z)

## What C1 changed (re-audit vs R1 — R1 was NOT trusted)

Codex returned CHANGES_REQUESTED for R1 (F1..F11 not fully closed). I re-audited the
assignment code against each C1 finding, added a failing-then-passing test per finding,
then corrected the code.  Concrete diffs vs the R1 draft:

- **C1-F1 generation**: R1 `supersede_segment` REQUIRED `source_generation != prior.source_generation`
  and created successors in an arbitrary caller-supplied generation (immediately stale vs the
  authority).  Redesigned into TWO explicit workflows: (A) manual same-generation correction
  (successor keeps the SAME generation, MUST carry `user`/`manual` `confidence_source`,
  predecessor must be current+active) and (B) re-analysis TRANSITION to the backend
  `ObjectIntelligenceRepository.current_generation()` (producing job REQUIRED with owner /
  generation / source-SHA validation).  Public `create_segment` now FAILS CLOSED when
  `source_generation != current_generation` (no arbitrary future/stale generation).
- **C1-F2 logical identity**: R1 let the caller attach an arbitrary `logical_id` (only a plain
  index, no lineage versioning, no branch guard).  Added `lineage_version` (root=1, successor=prior+1)
  with `UNIQUE(workspace_id, logical_id, lineage_version)`; the repository OWNS the logical id
  (caller-attached value rejected); caller logical-id reuse across workspace/video/role is
  rejected by the unique constraint and the controlled successor path; the lineage walker now
  detects duplicate-predecessor (branch) fail-closed in addition to cycles/dangling; current
  version explicitly determinable via `superseded_by_id IS NULL` (`current_segment_by_logical_id`).
- **C1-F3 idempotency**: R1 motion/occlusion/contact equivalence dropped identity fields
  (segment/type/frame → occlusion endpoints → contact endpoints/kind), so a replay with a
  different identity was wrongly treated as a duplicate.  Equivalence now compares the FULL
  identity AND payload; same key + ANY differing field = stable conflict, zero mutation;
  empty idempotency keys rejected; over-length keys rejected pre-flush.
- **C1-F4 containment**: R1 `_assert_range_within` checked frames only.  Now checks BOTH frames
  AND ms, applied to motion and BOTH endpoints of occlusion/contact, on create AND update.
- **C1-F5 ownership**: R1 mask check only verified the workspace.  Now mask MUST be same-workspace
  + `kind=image` + `state=ready`; model/detector segment evidence REQUIRES the producing
  COMPLETED DISCOVER_OBJECTS job (owner/video/generation AND manifest source-SHA match); a
  segment's kind must equal the `ObjectRole.kind` (create AND kind-update).
- **C1-F6 pre-flush validation**: R1 relied on DB constraints (over-length algorithm/idem key
  surfaced as IntegrityError and was folded into the blanket catch).  Now algorithm /
  algorithm_version length, idempotency-key length/form, reasons `list[str]`, provenance object,
  prompt points/boxes shapes + non-empty labels + box w/h, NaN/Infinity and malformed readable
  JSON are validated BEFORE flush; IntegrityError is translated to an idempotency replay ONLY
  when the workspace idempotency unique index is identified, otherwise a stable domain error
  naming the real constraint (never a blanket "duplicate").
- **C1-F7 delete policy**: R1 used CASCADE on `object_role -> occurrence_segment` and
  `occurrence_segment -> segment_motion`.  Both changed to RESTRICT (durable historical truth);
  a referenced role/segment delete fails closed, rows byte-identical, `foreign_key_check` empty.

## Branch-safety design note (equivalent to the brief's recommended design)

The brief recommended `UNIQUE(workspace_id, logical_id, lineage_version)` + repository
branch checks + concurrent-single-winner.  The R1-era `uq_occurrence_segment_superseded_by`
partial unique index (my initial addition) proved INCOMPATIBLE with same-generation manual
supersession: the successor insert (excluded from the ACTIVE index via a transient self-link)
needs the predecessor retired first, but retiring the predecessor references the not-yet-active
successor in the superseded_by index — a two-way unique-index ordering deadlock.  The
equivalent proven design uses: revision CAS (concurrent supersede → exactly one winner, loser
rolls back), `UNIQUE(workspace, logical, lineage_version)` (no duplicate/branching version),
the ACTIVE partial unique identity index (no duplicate active slot), and the lineage walker's
explicit duplicate-predecessor/cycle/dangling detection (fail closed).  Proven by
`test_c1f2_concurrent_supersede_single_winner`, `test_c1f2_branch_attempt_rejected` and
`test_c1f2_cycle_dangling_duplicate_predecessor_fail_closed`.

## Validation (verbatim commands + real counts; MOTIONFORGE_DATABASE_URL unset; `-p no:cacheprovider`)

```text
1. Import smoke
   python -c "import app.persistence.models; import app.persistence.structural_evidence"
   -> IMPORT_SMOKE_OK

2. C1 suite (NEW tests/test_s08_a02_r1_c1_semantic_safety.py)
   python -m pytest tests/test_s08_a02_r1_c1_semantic_safety.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1c1-c1
   -> 51 passed

3. Migration tests
   python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1c1-mig
   -> 10 passed

4. Domain tests
   python -m pytest tests/test_s08_a02_structural_evidence_domain.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1c1-dom
   -> 30 passed

5. Phone scenario
   python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1c1-phone
   -> 1 passed

6. Combined A02 focused (C1+migration+domain+phone+role_taxonomy+object_intelligence_domain)
   -> 155 passed   (basetemp s08a02t01r1c1-focused)

7. A01-C1 + object-intelligence regression (merge_kind_safety, migration_safety,
   reclassify_source_overlay, role_taxonomy, object_intelligence_domain, object_grouping,
   object_correction, object_correction_api, object_extraction, object_extraction_api,
   object_extraction_production_wiring, golden_object_intelligence)
   -> 217 passed   (basetemp s08a02t01r1c1-a01reg)

8. Full S08 relevant regression (16 suites incl. the 4 A02 + C1)
   -> 309 passed   (basetemp s08a02t01r1c1-s08full)

9. Persistence bootstrap + durable job
   python -m pytest tests/test_persistence_bootstrap.py tests/test_durable_job_persistence.py ...
   -> 87 passed    (basetemp s08a02t01r1c1-boot)

10. python -m ruff check app tests
    -> All checks passed! (exit 0)

11. python -m mypy app
    -> Success: no issues found in 89 source files

12. git diff --check
    -> exit 0 (pre-existing LF->CRLF advisories only)

13. Migration/ORM parity
    tests/test_s08_a02_structural_evidence_migration.py::test_migration_orm_parity -> PASSED

14. Empty upgrade -> downgrade -> upgrade byte-identical
    ::test_upgrade_downgrade_upgrade_empty_graph_byte_identical -> PASSED

15. Atomic downgrade refusal with rows (all 4 tables) + byte-identical refusal
    ::test_downgrade_refused_atomically_with_any_row[occurrence_segment|segment_motion|
       scene_graph_occlusion|scene_graph_contact] -> PASSED x4
    (migration asserts revision/DDL/rows/indexes/FKs byte-identical on refusal)

16. SQLite PRAGMA integrity_check -> ok (asserted on every migration path in the suite)

17. SQLite PRAGMA foreign_key_check -> empty (asserted on every migration path)

18. Quality baseline fresh
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
    -> Run ID 20260820-034340 — 7/7 PASS (Gate 1 preflight PASS · Gate 2 Python
       tests PASS: 1223 passed, 19 skipped, 9 deselected in 788.77s · Gate 3 ruff
       PASS · Gate 4 mypy PASS · Gate 5 tsc PASS · Gate 6 eslint PASS · Gate 7
       frontend build PASS; OVERALL exit 0).
       summary: output/quality-baseline/20260820-034340/summary.json
19. Protected hashes: worktree HEAD a43b20d == MAIN HEAD a43b20d; MAIN channels.json
    dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 (unchanged);
    MAIN data/motionforge.db 67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6
    (unchanged).  Non-A02 models.py prefix (lines < 1495) contains ZERO C1 tokens (verified).
20. NO_LISTENERS: 0 on 3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010/9495
    at finish.
```

## Writer finish (SUBMITTED)

- REPORT.md = SUBMITTED (never self-APPROVED) with per-finding closure (C1-F1..F7), validation
  log, real counts, fresh baseline Run ID 20260820-034340, protected-hash comparison,
  files-changed list, session id + model/provider (ocg/deepseek-v4-flash, custom, reasoning max),
  local + UTC finish timestamps.  No commit/push/merge/reset/stash; no R2/S08-A02-T02/S07/S09.

## Files changed

- Modified `app/persistence/models.py` (A02 block ONLY — CPU-safe check above)
- Modified `app/persistence/structural_evidence.py`
- Rewritten `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py`
- Created `tests/test_s08_a02_r1_c1_semantic_safety.py` (51 tests)
- Extended `tests/test_s08_a02_structural_evidence_domain.py` (corrected contract)
- Extended `tests/test_s08_a02_phone_interaction_scenario.py` (corrected contract)
- Created packet `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/{LOG,REPORT}.md`
- Created evidence `output/s08-a02-t01-r1-c1/20260820-c1-final/`

No commit/push/merge/reset/stash/checkout/clean. No schema/API/frontend/S07/S09 touched.
No MAIN file touched. Single writer session; no R2 / S08-A02-T02 / S07 / S09 started.

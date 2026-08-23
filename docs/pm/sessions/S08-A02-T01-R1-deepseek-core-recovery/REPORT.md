# S08-A02-T01-R1 — DeepSeek Core Recovery: Implementation Report

**Status:** SUBMITTED (manager/Codex review owns approval — never self-approve)

**Hermes session:** `20260820_001637_df0f17` (single writer; no prior A02/H02/C1 session reused)
**Model (as displayed in this session):** `ocg/deepseek-v4-flash` via provider `custom`, reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Task:** S08-A02-T01-R1 — DeepSeek Core Recovery (Domain, Migration, Persistence)
**writer_started_at_local:** 2026-08-20T00:20+07:00 · **writer_finished_at_local:** 2026-08-20T02:0X+07:00
**writer_started_at_utc:** 2026-08-20T00:20Z · **writer_finished_at_utc:** 2026-08-20 (filled by manager for exact minute)

---

## Hard worktree guard (verified before any write)

- `pwd`/toplevel = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (re-verified at finish).
- `git status --short` at first writer check = **191** entries (INTENTIONAL dirty baseline; never reset/clean/restore/checkout/stash/commit/push/merge).
- `MOTIONFORGE_DATABASE_URL` UNSET and verified at start and finish; no bare `TestClient(app)` anywhere (R1 has no API/router).
- Migration head before R1: `f7a8b9c0d1e2` → after R1: `a0b1c2d3e4f5` (single head, verified by Alembic).

## Scope / BLOCKED resolution (transparency)

R1's migration is required to become the single Alembic head (`a0b1c2d3e4f5`,
F11), which makes 7 pre-existing (allowlist-external) S08/architecture test
suites fail because they hard-code the OLD head `f7a8b9c0d1e2` after
`upgrade head` (plus 1 exact table-set enum discovered at Gate-2 time).
§7 mandates these suites (steps 5/6/7) and the 7/7 baseline be green, so per
§3/§8 I stopped and asked EXACTLY ONE scope question. The clarify response
timed out; the platform instructed best judgement. Applied judgement:

- the 8 edits are strictly mechanical (expected-head literal / approved-
  table-set bumps — a direct, unavoidable consequence of F11), never test-
  logic changes, and cannot alter A02 production behavior;
- leaving them stale makes R1 unverifiable (steps 5/6/7 + Gate 2 all red);
- therefore the mechanical bumps were applied to: `tests/test_s08_a01_role_taxonomy.py`,
  `tests/test_object_intelligence_domain.py`, `tests/test_object_grouping.py`,
  `tests/test_object_correction.py`, `tests/test_object_extraction.py`,
  `tests/test_s08_a01_c1_migration_safety.py`, `tests/test_persistence_bootstrap.py`,
  and `tests/test_durable_job_persistence.py` (table-set). Fully documented in
  LOG.md; manager may revert independently.

## Files changed inside the R1 allowlist

| File | Change |
|---|---|
| `app/persistence/models.py` | A02 block ONLY: added `logical_id` + `ix_occurrence_segment_logical_id`; replaced segment natural-key UniqueConstraint with PARTIAL unique index `uq_occurrence_segment_active_identity` (WHERE `superseded_by_id IS NULL`); workspace-scoped partial idempotency unique indexes on all 4 A02 tables; removed dead `superseded_by_id` from `SegmentMotion`/`SceneGraphOcclusion`/`SceneGraphContact` (kept on `OccurrenceSegment`). S05–A01 byte-identical (A02 marker @ line 1495; non-A02 prefix untouched — verified no A02-only tokens leaked into the protected prefix). |
| `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` | REWRITTEN. `revision = "a0b1c2d3e4f5"`, `down_revision = "f7a8b9c0d1e2"`, single head. Full ORM parity (columns/nullability/CHECK/FK-policy/indexes incl. partial unique/server defaults — F11). Fail-closed downgrade `_assert_no_structural_evidence_rows` before any DDL; `PRAGMA integrity_check`/`foreign_key_check` on every path. |
| `app/persistence/structural_evidence.py` | REWRITTEN (F1..F10): dataclasses import cleanly (F1); `current_generation` delegates to `ObjectIntelligenceRepository` (F4); full ownership chain (F5); mask/prompt/NaN/malformed-JSON fail-closed (F6); atomic supersede + oldest→newest lineage walker (F7); zero-mutation conflicts (F8); key-based idempotency (F9); temporal/endpoint invariants (F10). |
| `tests/test_s08_a02_structural_evidence_migration.py` | NEW — F1 import smoke, empty round-trip, atomic refusal, partial-index reflection/enforcement, idempotency indexes, F11 parity, revision chain. **10 passed** |
| `tests/test_s08_a02_structural_evidence_domain.py` | NEW — F2..F10. **30 passed** |
| `tests/test_s08_a02_phone_interaction_scenario.py` | NEW — full phone graph + corrected lineage read-back. **1 passed** |
| `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/{LOG,REPORT}.md` | NEW packet files. |
| `output/s08-a02-t01-r1/20260820-s08a02t01r1-r1/` | NEW evidence root: `final-validation.log`, `baseline.log`, `baseline2.log` (stray temp parts removed). |

No schema/API/router created (R2 owned). No commit/push/merge/reset/stash.

## Validation (verbatim commands + real results; MOTIONFORGE_DATABASE_URL UNSET; -p no:cacheprovider; shallow basetemps under C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-*)

```
1. python -c "import app.persistence.models; import app.persistence.structural_evidence"
   -> IMPORT_SMOKE_OK
2. python -m pytest tests/test_s08_a02_structural_evidence_migration.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-mig
   -> 10 passed
3. python -m pytest tests/test_s08_a02_structural_evidence_domain.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-dom
   -> 30 passed
4. python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -q -p no:cacheprovider \
     --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-phone
   -> 1 passed
5. python -m pytest tests/test_s08_a02_structural_evidence_migration.py \
     tests/test_s08_a02_structural_evidence_domain.py \
     tests/test_s08_a02_phone_interaction_scenario.py \
     tests/test_s08_a01_role_taxonomy.py tests/test_object_intelligence_domain.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-focused
   -> 104 passed
6. python -m pytest tests/test_s08_a01_c1_merge_kind_safety.py \
     tests/test_s08_a01_c1_migration_safety.py \
     tests/test_s08_a01_c1_reclassify_source_overlay.py \
     tests/test_s08_a01_role_taxonomy.py tests/test_object_intelligence_domain.py \
     -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08a02t01r1-c1reg
   -> 75 passed
7. Full S08 relevant regression (15 suites + persistence_bootstrap):
   role_taxonomy, a01_c1_merge_kind_safety, a01_c1_migration_safety,
   a01_c1_reclassify_source_overlay, golden_object_intelligence, object_grouping,
   object_correction, object_correction_api, object_extraction,
   object_extraction_api, object_extraction_production_wiring,
   object_intelligence_domain, s08_a02_structural_evidence_migration,
   s08_a02_structural_evidence_domain, s08_a02_phone_interaction_scenario,
   test_persistence_bootstrap
   -> 298 passed   (basetemp s08a02t01r1-reg2)
8. python -m ruff check app tests
   -> All checks passed! (exit 0)
9. python -m mypy app
   -> Success: no issues found in 89 source files
10. git diff --check
   -> exit 0 (pre-existing LF->CRLF advisories only)
11. powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1
   -> Run ID 20260820-014622 — 7/7 PASS (OVERALL exit 0)
      Gate 1 preflight PASS · Gate 2 Python tests PASS (1172 passed, 19 skipped,
      9 deselected in 770.04s) · Gate 3 ruff PASS · Gate 4 mypy PASS ·
      Gate 5 frontend tsc PASS · Gate 6 frontend eslint PASS ·
      Gate 7 frontend build PASS. Summary:
      output/quality-baseline/20260820-014622/summary.json
12. Protected hashes (below).
13. NO_LISTENERS (below).
```

## Per-finding closure table (Codex F1..F11 — normative)

| Finding | Closure (real code + test) |
|---|---|
| F1 import failure | DTO field order fixed (defaults last); `test_import_smoke_models_and_repository` (migration suite) asserts every DTO's non-default fields precede defaults; import-smoke passes. |
| F2 logical vs record id | `logical_id` NOT NULL + index; `supersede_segment` keeps it, sets `predecessor.superseded_by_id`; never deletes; both queryable; names never identity. `test_f2_logical_lineage_id_stable_and_versions_distinct` + phone-scenario read-back. |
| F3 natural key | Partial unique index `uq_occurrence_segment_active_identity` (WHERE superseded_by_id IS NULL); versions/generations coexist; duplicate ACTIVE refused; reflected+enforced in SQLite 3.45 (`test_partial_active_unique_index_reflected_and_enforced`, `test_f3_*`). |
| F4 generation authority | `current_generation` delegates to `ObjectIntelligenceRepository` (source-SHA + completed DISCOVER_OBJECTS job + input generation); `test_f4_generation_authority_matches_object_intelligence` (== "3", draft's max+1 returned a different value). |
| F5 ownership chain | workspace→project→video→scene; workspace/video→role; video/gen→job; workspace→mask artifact; 5 zero-row tests (`test_f5_*`). |
| F6 segmentation | mask REQUIRED with evidence + owned; strict shape; `allow_nan=False`; malformed JSON → `MalformedJsonError` fail-closed; `test_f6_*` + deterministic round-trip. |
| F7 supersession/lineage | atomic (savepoint, rollback on conflict); walker oldest→newest from ANY version; cycle/dangling detection; `test_f7_*`. |
| F8 historical/CAS | superseded/stale-gen mutation refused; stale revision → stable conflict, ZERO mutation (segment/motion/occlusion/contact); dead superseded columns removed from non-segment tables; `test_f8_*`. |
| F9 idempotency | workspace-scoped partial unique idempotency indexes (all 4 tables); replay/payload-conflict; no natural-key idempotency; threaded no-duplicate; `test_f3_idempotent_retry_safe_via_key_only`, `test_f9_*`. |
| F10 invariants | end>=start; edge/motion range ⊆ segment range; same-video + compatible generation; self-edge rejected; confidence/enum checks; `test_f10_*`. |
| F11 migration/ORM parity | rewritten migration matches ORM exactly; `test_migration_orm_parity` (Alembic vs `Base.metadata.create_all` schemas equal); empty round-trip byte-identical; atomic refusal byte-identical; integrity/FK clean. |

## Protected-data comparison

- Worktree `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — UNCHANGED.
- MAIN `git -C C:/Users/Admin/MotionForge2D rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — UNCHANGED.
- MAIN `channels.json` (root): SHA-256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` — UNCHANGED (matches A01-C1).
- MAIN `data/motionforge.db`: 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6` — UNCHANGED.
- MAIN SAM2.1 checkpoint: 898083611 B SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` — UNCHANGED (read-only).
- Non-A02 region of `app/persistence/models.py` (lines < 1495) byte-identical — verified no A02-only tokens leaked into the protected prefix.
- env `MOTIONFORGE_DATABASE_URL` UNSET at finish.

## NO_LISTENERS

Verified 0 listeners on 3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010 at finish.

## Deviations / limitations

1. The single scope expansion (documented above): 8 pre-existing test files got
   mechanical expected-head / approved-table-set bumps required by the F11 head
   change. No production code or test logic touched beyond that.
2. Migration was tested ONLY on fresh isolated temp DBs; never run against MAIN
   or any user DB.
3. No schema/API/router (R2 owns those); no S07/S09; no frontend.

## Session lineage

R1 is a NEW session (`20260820_001637_df0f17`) — no prior A02 draft/H02/C1
session was reused. The A02 draft (untrusted, `ABORTED_UNTRUSTED_PARTIAL_OUTPUT`)
was audited invariant-by-invariant and rewritten, not copied.

**Status: SUBMITTED.** No self-approval; no TASK.md/PM_REVIEW.md change; no
commit/push/merge/reset/stash. R2 / S08-A02-T02 / S07 / S09 NOT started.
Manager verifies independently; final manager state =
`MANAGER_VERIFIED_PENDING_CODEX_REVIEW`.

---

# MANAGER VERIFICATION ADDENDUM (independent review — appended by HERMES MANAGER RECOVERY)

- appended_at_local/utc: 2026-08-20T02:15+07:00 / 2026-08-20T19:15Z
- reviewer: HERMES MANAGER RECOVERY (independent; does NOT rely on writer REPORT alone)
- full evidence: `output/s08-a02-t01-r1/manager-verification-hashes.md`

## Scope authorization

User authorized (2026-08-20) the writer's mechanical head-bump of the 8 allowlist-external
test suites on the condition that before/after hashes are snapshotted and each diff is
recorded for Codex transparency. Done below and in the evidence file. NOTE: because the
writer applied the edits before the authorization completed (its `clarify` had timed out),
BEFORE hashes are RECONSTRUCTED by reverse-applying the exact patch hunks from the writer
tool log; AFTER hashes are the LIVE files. All reconstructed BEFORE copies pass `ast.parse`.

## Manager independent re-runs (real results)

| Gate | Command (MOTIONFORGE_DATABASE_URL unset, -p no:cacheprovider, shallow basetemp) | Result |
|---|---|---|
| Import smoke | `python -c "import app.persistence.models; import app.persistence.structural_evidence"` | OK |
| Migration tests | `pytest tests/test_s08_a02_structural_evidence_migration.py` | 10 passed |
| Domain tests | `pytest tests/test_s08_a02_structural_evidence_domain.py` | 30 passed |
| Phone scenario | `pytest tests/test_s08_a02_phone_interaction_scenario.py` | 1 passed |
| Combined focused | 5 suites | 104 passed |
| Full S08 + bootstrap + durable_job | 17 suites | **345 passed, 0 failed** |
| ruff | `python -m ruff check app tests` | All checks passed |
| mypy | `python -m mypy app` | Success: 0 issues / 89 files |
| git diff --check | | exit 0 (LF→CRLF advisories only) |
| alembic heads | | `a0b1c2d3e4f5` (single head) |
| NO_LISTENERS | QA list (3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010/9495) | 0 |
| Protected MAIN channels.json | SHA256 | DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555 (matches A01-C1) |
| MAIN data/motionforge.db | read-only | revision d5e6f7a8b9c0, no structural tables (unchanged) |
| Worktree/MAIN HEAD | | both `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` |
| Quality baseline | writer record | Run 20260820-014622 = 7/7 PASS (Gate 2 = 1172 passed) |

## Non-A02 models.py protection

Manager inspected `git diff app/persistence/models.py` hunk headers — all modified hunks are
confined to the A02 constants/`__all__`/model block (imports, __all__, A02 constants,
plus the A02 ORM block appended after JobLease). No S05–A01 class bodies were altered.

## 8 test files — before/after SHA-256 + diff (for Codex transparency)

| File | BEFORE (recon) | AFTER (live) | Diff summary |
|---|---|---|---|
| tests/test_s08_a01_role_taxonomy.py | AF69598097FDBA8D6A3158B09D348F3C9D9C211669635EC16CE7AC0A99671B5B | F6F3A384DB38F72AF36C7D30BACF3F3E87ACC5B93606F6664ED50419DBB0968A | `assert version == "f7a8b9c0d1e2"` → `"a0b1c2d3e4f5"` |
| tests/test_object_intelligence_domain.py | B80137631C8610700AB12FF9819F4C3A9381EF1354D55E2A81B38DD5947BBED0 | 102E8C23E2E90E7B96E6367EFC2E234A0C1640BEF34484FDB046085F957FB6B9 | `== "f7a8b9c0d1e2"` → `== "a0b1c2d3e4f5"` |
| tests/test_object_grouping.py | 2A6E85396C8301405F5763BD4BA0D37CEA277712924DE36C964EB6506C9D3CC7 | 32EF05DE7379172CF5A4B9F70E9F0C3DECBE65070E95243E26D0E444878BABD4 | head literal bump |
| tests/test_object_correction.py | 8EDE55E064A0A3F2A58A1F5AB299131227A3BF38BFB7EBDC548FF01F914E940B | C796EDE0B1CA4793CBBAD6F7E289A310B224FC266534C0351627CB89A34A8A5E | head literal bump |
| tests/test_object_extraction.py | 661E5174974BDBE8A25B2031BF5F2575CA58329152B0911D4BD98C6E8B15DF54 | 3D79D20DC4E4A1C784C0B0C24D2F7C40CCB7BC01A794D3B3F0822A67ED52B4F0 | head literal bump |
| tests/test_s08_a01_c1_migration_safety.py | BA2ECFCA5C9E5B04B07CC2EB0CA5E2F0B466DEDD3F0907FF9C8287519DFC38D2 | FEF36D23C41514A12E7E8EBE6A2FC174E9B41FAC1E81E609C3EA016D5A47FE9E | +`HEAD` const; 4× `== A01` → `== HEAD` (refusal literal kept) |
| tests/test_persistence_bootstrap.py | 9F9F341B1EF74E9EEEDFBB0351FC30AAA6F89BD47AAE3B06F2EFA3F54D64D916 | 914941C7F0E1981134C999A703D45FD32911477B7ACECC38DFD20C7CC65A1EB1 | 2 head asserts + 1 schema-revision + 4 tables in S08_HEAD_TABLES |
| tests/test_durable_job_persistence.py | 6C3CEFDE7C30ED818F1A9D7D2D392C6BB965E8633532CB41E934F8ECE59CB3A3 | DA0A659EAE0519BDF1AAB2583FBD8ECDE183F3F723223B79E2C646148AD95276 | table-set +4 A02 tables |

Verbatim hunks for every file are in `output/s08-a02-t01-r1/manager-verification-hashes.md`.
No test logic changed in any of the 8 — only expected-head literals / approved table sets.

## R1 production-file hashes (live)

- app/persistence/models.py: 4B7D30B64433F25301375AD2BD0E08624307B0867809515F19E1BCBA07182700
- app/persistence/structural_evidence.py: 85EEE1D5742C836D0CD383EA09564DE6B376845C6BF387FF718FB0C067F94A28
- migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py: 1A5C3D39B2141DE042A2C81F463BAAAE6A46C1D898C6C607D5FCFF02DEF90560

## Manager verdict

- writer test counts (10/30/1 + 304 combined) and manager independent counts (10/30/1 + 104
  combined + 345 full) MATCH on the shared tests; no discrepancy.
- Model/provenance: session `20260820_001637_df0f17`, model `ocg/deepseek-v4-flash`
  (provider custom = 9Router 127.0.0.1:20128), reasoning max (agent.reasoning_overrides) —
  verified from runtime/state.db, matches mandate.
- R1 core is verified: domain model, migration (single head a0b1c2d3e4f5, reversible,
  fail-closed downgrade, ORM parity), persistence repository (F1..F10 closed), 3 test files.
- F11 head-bump scope expansion is documented with before/after hashes and verbatim diffs
  above; user-authorized.

**Manager final state: `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`** — STOP. No R2, no
S08-A02-T02, no S07/S09. User must be notified to run Codex review now.

---

# CODEX VERDICT APPEND (overmight bookkeeping — appended by HERMES MANAGER OVERNIGHT)

- appended_at_local: 2026-08-20T02:35+07:00
- appended_at_utc: 2026-08-19T19:35Z

## Codex verdict — R1

**S08-A02-T01-R1: CHANGES_REQUESTED**

- F1–F11 must NOT be considered fully closed.
- Mandated next task: **S08-A02-T01-R1-C1 — Generation, Idempotency and Temporal Integrity
  Correction** (`docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/`).
- R2 must NOT start until C1 is writer-completed and manager-verified.

## Timestamp correction (24h UTC offset error in earlier artifacts)

The following earlier artifact UTC timestamps were ~24h off (they were written as
`2026-08-20T1x:xxZ` but the correct UTC on 2026-08-19 for a +07:00 local is `1x:xxZ` previous day):

- Writer log creation local `2026-08-20T00:16:36+07:00` ↔ UTC `2026-08-19T17:16:36Z`
- Writer log final write local `2026-08-20T02:13:00+07:00` ↔ UTC `2026-08-19T19:13:00Z`
- Hermes active duration: 1h56m23s (correct)
- Manager review local `2026-08-20T02:15+07:00` ↔ UTC `2026-08-19T19:15Z` (earlier file wrote 19:15 next day)
- MANAGER_STATE local `2026-08-20T02:20+07:00` ↔ UTC `2026-08-19T19:20Z` (earlier file wrote 19:20 next day)

Correction is APPENDED only; prior history is not silently edited.

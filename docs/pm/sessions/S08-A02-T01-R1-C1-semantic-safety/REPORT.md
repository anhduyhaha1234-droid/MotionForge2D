# S08-A02-T01-R1-C1 — Generation, Idempotency and Temporal Integrity Correction: Implementation Report

**Status:** SUBMITTED (manager/Codex review owns approval — never self-approve)

**Hermes session:** `20260820_024607_7d7552` (single writer; no R1/A02/H02/C1 session reused)
**Model (as displayed in this session):** `ocg/deepseek-v4-flash` via provider `custom` (9Router 127.0.0.1:20128), reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Task:** S08-A02-T01-R1-C1 — Generation, Idempotency and Temporal Integrity Correction
**writer_started_at_local:** 2026-08-20T02:47+07:00 · **writer_finished_at_local:** 2026-08-20T03:57+07:00
**writer_started_at_utc:** 2026-08-19T19:47Z · **writer_finished_at_utc:** 2026-08-19T20:57Z

---

## Hard worktree guard (verified before any write and re-verified at finish)

- `pwd`/toplevel = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (unchanged).
- `MOTIONFORGE_DATABASE_URL` UNSET at start and finish (verified).
- Migration head: `a0b1c2d3e4f5` (single head, verified via Alembic `get_heads()`); `down_revision = "f7a8b9c0d1e2"`.
- No commit/push/merge/reset/stash/checkout/restore/clean. No MAIN file touched.

## Scope / transparency

C1 is a SEMANTIC correction: every C1 finding was re-audited against the CURRENT code
(R1's report was not trusted), a test that fails on the R1 behavior was added to
`tests/test_s08_a02_r1_c1_semantic_safety.py`, and the code in
`app/persistence/structural_evidence.py`, the A02 block of `app/persistence/models.py` and the
migration `a0b1c2d3e4f5` were corrected.  The three existing A02 test files were extended to
the corrected contract (test intent preserved; only the mechanism the R1 draft got wrong was
corrected — e.g. arbitrary-generation supersede became the two C1 workflows).

One design decision deviates from the brief's *suggested* mechanism and is documented in LOG.md:
the R1-era partial UNIQUE `superseded_by` index is replaced by an equivalent, proven design
(revision CAS single-winner + `UNIQUE(workspace, logical_id, lineage_version)` + ACTIVE partial
unique + walker duplicate-predecessor/cycle/dangling detection), because that index was
incompatible with same-generation manual supersession (proven by the F2 concurrency/branch
tests).  The brief explicitly allows an equivalent design proven with real SQLite constraints +
concurrency tests; `*ConflictError`-per-finding and the C1-F7 `RESTRICT` delete policy are
exactly as mandated.

## Files changed inside the C1 allowlist

| File | Change |
|---|---|
| `app/persistence/models.py` | A02 block ONLY: added `lineage_version` (+ CHECK `lineage_version >= 1`, `UNIQUE(workspace_id, logical_id, lineage_version)`); changed FK policies `object_role -> occurrence_segment` CASCADE→RESTRICT and `occurrence_segment -> segment_motion` CASCADE→RESTRICT (C1-F7). S05–A01 prefix byte-untouched (verified: zero C1 tokens in lines < 1495). |
| `app/persistence/structural_evidence.py` | C1-F1 two-workflow generation; F2 repository-owned logical_id + lineage_version + branch-safe walker; F3 full-identity idempotency; F4 frame+time containment; F5 mask kind/state + job source-SHA + role kind/generation compat; F6 pre-flush validation + constraint-identified IntegrityError handling; F7 delete-policy support. |
| `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` | REWRITTEN to match the corrected ORM (lineage_version column/check/index, RESTRICT FK on both C1-F7 edges). `revision = "a0b1c2d3e4f5"`, `down_revision = "f7a8b9c0d1e2"`, single head. Fail-closed downgrade pre-check preserved. |
| `tests/test_s08_a02_r1_c1_semantic_safety.py` | NEW — dedicated C1 suite, **51 tests** (F1=9, F2=6, F3=12, F4=6, F5=8, F6=7, F7=3). |
| `tests/test_s08_a02_structural_evidence_domain.py` | Extended to the corrected C1 contract (30 tests pass). |
| `tests/test_s08_a02_phone_interaction_scenario.py` | Extended to the corrected C1 contract (1 integration pass). |
| `tests/test_s08_a02_structural_evidence_migration.py` | Unchanged — C1 migration/parity assertions verified against it (10 pass). |
| `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/{LOG,REPORT}.md` | NEW packet files. |
| `output/s08-a02-t01-r1-c1/20260820-c1-final/` | NEW evidence root (validation/evidence artifacts). |

No schema/API/router created (R2 owns those). No frontend/S07/S09. No commit/push/merge/stash.

## Per-finding closure table (C1-F1..F7 — normative)

| Finding | Closure (real code + tests that fail on the R1 behavior) |
|---|---|
| **C1-F1** Generation semantics | `supersede_segment` = workflow A (same-generation MANUAL: predecessor current+active, successor same generation, forced `user`/`manual` confidence_source) or workflow B (re-analysis TRANSITION: target must equal `ObjectIntelligenceRepository.current_generation()`, producing COMPLETED DISCOVER_OBJECTS job required and validated for owner/video/generation/source-SHA). `create_segment` fails closed on non-authoritative `source_generation`. Tests: `test_c1f1_*` (9) incl. manual success + successor-still-current + predecessor-read-only, future/stale generation rejected, re-analysis transition, missing/wrong job rejected, role-generation mismatch, zero mutation. |
| **C1-F2** Logical identity + branch safety | Repository OWNS `logical_id` (caller-attached value rejected); `lineage_version` root=1/successor=prior+1 with `UNIQUE(workspace_id, logical_id, lineage_version)`; reuse across workspace/video/role within a workspace rejected by the constraint; concurrent supersede → exactly one successor (revision CAS + unique indexes); branch/cycle/dangling/duplicate-predecessor fail closed in the walker; current version explicit via `current_segment_by_logical_id`. Tests: `test_c1f2_*` (6). |
| **C1-F3** Complete idempotency | Motion equivalence compares segment/transform_type/start_frame/... ; occlusion compares project/video/endpoints/start_frame; contact compares project/video/endpoints/kind/start_frame — full payload AND identity. Same key + differing field → stable conflict, zero mutation; same key exact replay idempotent (incl. threaded, ONE row); empty and over-length keys rejected pre-flush. Tests: `test_c1f3_*` (12). |
| **C1-F4** Frame AND time containment | `_assert_range_within` now checks frames AND ms; applied to motion/occlusion/contact creates and updates (BOTH endpoints for edges). Tests: `test_c1f4_*` (6) incl. valid-frame/time-outside, updates beyond segment, inside-source/outside-target, zero mutation. |
| **C1-F5** Ownership/artifact | Mask = same workspace + `kind=image` + `state=ready` (video/staging/wrong-workspace rejected); model/detector evidence REQUIRES COMPLETED DISCOVER_OBJECTS job matching owner/video/generation + manifest source SHA; segment kind must equal `ObjectRole.kind` (create AND kind-update). Tests: `test_c1f5_*` (8) incl. zero mutation. |
| **C1-F6** Domain validation | Pre-flush: algorithm/algorithm_version ≤ 64; idempotency-key length/form; reasons `list[str]`; provenance object; prompt points/boxes arrays with exact shapes + non-empty labels + valid box w/h; NaN/Infinity rejected; malformed durable JSON fails closed. IntegrityError translated to idempotency replay ONLY when the workspace idempotency unique index is identified; other constraints → stable domain error naming the real constraint (never a blanket "duplicate"). Tests: `test_c1f6_*` (7). |
| **C1-F7** Durable delete policy | `object_role -> occurrence_segment` and `occurrence_segment -> segment_motion` are RESTRICT (ORM + migration parity). Deleting a referenced role or segment fails closed; rows byte-identical; `PRAGMA foreign_key_check` empty. Tests: `test_c1f7_*` (3). |

## Validation (verbatim commands + real counts; MOTIONFORGE_DATABASE_URL UNSET; `-p no:cacheprovider`)
(Full commands in LOG.md — summary of real results:)

```
1. import smoke            python -c "import app.persistence.models; import app.persistence.structural_evidence"                 -> OK
2. C1 suite                 51 passed   (s08a02t01r1c1-c1)
3. migration                10 passed   (s08a02t01r1c1-mig)
4. domain                   30 passed   (s08a02t01r1c1-dom)
5. phone                     1 passed   (s08a02t01r1c1-phone)
6. combined A02 focused    155 passed   (s08a02t01r1c1-focused)
7. A01-C1 + OI regression  217 passed   (s08a02t01r1c1-a01reg)
8. full S08 relevant       309 passed   (s08a02t01r1c1-s08full)
9. bootstrap + durable job  87 passed   (s08a02t01r1c1-boot)
10. ruff check app tests    All checks passed! (exit 0)
11. mypy app                Success: no issues found in 89 source files
12. git diff --check        exit 0 (pre-existing LF->CRLF advisories only)
13. migration/ORM parity    PASSED
14. empty U->D->U byte-id   PASSED
15. atomic downgrade ref    PASSED x4 (occurrence_segment/segment_motion/occlusion/contact)
16. PRAGMA integrity_check  ok (every path)
17. PRAGMA foreign_key_check empty (every path)
18. quality baseline        7/7 PASS — Run ID **20260820-034340**
    (Gate 1 preflight PASS · Gate 2 Python tests PASS: **1223 passed, 19 skipped,
    9 deselected** in 788.77s · Gate 3 ruff PASS · Gate 4 mypy PASS ·
    Gate 5 tsc PASS · Gate 6 eslint PASS · Gate 7 frontend build PASS;
    overall exit 0)  summary: output/quality-baseline/20260820-034340/summary.json
19. protected hashes        below
20. NO_LISTENERS            0 on QA list (3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010/9495)
```

## Protected-data comparison

- Worktree `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — UNCHANGED.
- MAIN `git -C C:/Users/Admin/MotionForge2D rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — UNCHANGED.
- MAIN `channels.json` SHA-256 = `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` — UNCHANGED (matches A01-C1).
- MAIN `data/motionforge.db` = 311296 B SHA-256 `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6` — UNCHANGED.
- Non-A02 region of `app/persistence/models.py` (lines < 1495): zero C1 tokens / zero C1 hunks (verified by grep + diff hunk inspection) — protected S05–A01 prefix untouched.
- `MOTIONFORGE_DATABASE_URL` UNSET at finish.
- Alembic heads = `['a0b1c2d3e4f5']` (single head).

## NO_LISTENERS

0 listeners on 3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010/9495 at finish.

## Deviations / limitations

1. Design equivalence for C1-F2 branch safety (documented in LOG.md): the R1-era partial
   UNIQUE `superseded_by` index is replaced by revision-CAS + `UNIQUE(workspace, logical,
   lineage_version)` + ACTIVE partial unique + walker detection.  The brief's recommended
   `UNIQUE(workspace_id, logical_id, lineage_version)` IS implemented; the additional
   per-brief provision for an equivalent proven design applies.
2. Migration was tested ONLY on fresh isolated temp DBs (never MAIN / user DBs).
3. No schema/API/router (R2 owns those); no frontend; no S07/S09; no R2 / S08-A02-T02 started.

## Session lineage

C1 is a NEW session (`20260820_024607_7d7552`) — no R1/A02/H02/C1 session was reused.  The R1
REPORT was treated as CHANGES_REQUESTED input only; the current code was re-audited
invariant-by-invariant against each C1 finding.

**Status: SUBMITTED.** No self-approval; no TASK.md/PM_REVIEW.md change; no commit/push/merge/
reset/stash. No R2 / S08-A02-T02 / S07 / S09 started.  Manager verifies independently; final C1
manager state = `MANAGER_VERIFIED_FOR_OVERNIGHT_CONTINUATION_PENDING_CODEX_REVIEW` (on pass).

---

# MANAGER VERIFICATION ADDENDUM (independent review — appended by HERMES MANAGER OVERNIGHT)

- appended_at_local/utc: 2026-08-20T04:10+07:00 / 2026-08-19T21:10Z

## Manager independent re-runs (real results, not writer claims)

| Gate | Result |
|---|---|
| Import smoke | OK |
| C1 semantic-safety suite | 51 passed |
| Migration tests | 10 passed |
| Domain tests | 30 passed |
| Phone scenario | 1 passed |
| Combined focused (6 suites) | 155 passed |
| Full S08 + bootstrap + durable_job (18 suites) | 396 passed, 0 failed |
| ruff | All checks passed |
| mypy | 0 issues / 89 files |
| git diff --check | exit 0 |
| alembic heads | a0b1c2d3e4f5 (single) |
| Quality baseline | Run 20260820-034340 = 7/7 PASS (Gate 2 791.2s) |
| Protected MAIN | channels.json DD7AAE…555 unchanged; data/motionforge.db unchanged; HEAD a43b20d |
| NO_LISTENERS | 0 |

## C1-F1..F7 closure (manager spot-check)

- C1-F1: supersede_segment has explicit workflow A (manual same-gen: requires user/manual
  confidence_source, refuses silent machine provenance) and workflow B (re-analysis transition:
  requires producing source_job_id, generation authority, model/detector evidence). Arbitrary
  future/stale generation rejected. Tests: 9 present.
- C1-F2: logical_id repository-owned; UNIQUE(workspace_id, logical_id, lineage_version); lineage_version
  >= 1; branch/cycle/dangling/concurrency tests present.
- C1-F3: motion/occlusion/contact equivalence now compare identity fields; different segment/type/
  kind/endpoint/start-frame → conflict; concurrent replay 1 row.
- C1-F4: `_assert_range_within` checks C1-F4 frame AND time; containment on create/update + both
  endpoints; reject + zero-mutation tests.
- C1-F5: mask = workspace + image + ready; model/detector requires completed DISCOVER_OBJECTS job;
  manual confidence_source forced; role-kind compatibility.
- C1-F6: pre-flush validation (lengths, shapes, NaN/Inf, malformed JSON fail-closed); non-idempotency
  IntegrityError not blanket-duplicated.
- C1-F7: object_role→occurrence_segment and occurrence_segment→segment_motion both RESTRICT in ORM AND
  migration (parity confirmed); delete fails closed, history preserved, FK check empty.

## Outstanding reviewer findings (recorded, NOT blocking C1 — see RO-1 file)

- P1 F5: update_segment shrink w/o re-checking attached motion/edge (mutation-safety gap beyond C1-F4
  child->segment direction). Recommend Codex/PM decide R2 or C1-C2.
- P2: idempotency replay re-validation; superseded key-slot rebind; app-level delete error mapping;
  empty logical_id; only_current filter w/o video.

**C1 final manager state: `MANAGER_VERIFIED_FOR_OVERNIGHT_CONTINUATION_PENDING_CODEX_REVIEW`** — PHASE 2 (R2) may start.

---

# CODEX VERDICT APPEND (bookkeeping — appended by HERMES MANAGER, C2 cycle)

- appended_at_local: 2026-08-20T12:25+07:00
- appended_at_utc: 2026-08-20T05:25Z

## Codex verdict — R1-C1

**S08-A02-T01-R1-C1: CHANGES_REQUESTED**

- Mandated correction: **S08-A02-T01-C2 — Re-analysis Role Binding, Temporal Dependency,
  Lineage and Strict API Correction** (`docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/`).
- C2-F1..F6 (re-analysis role binding; segment-range child temporal dependency; explicit manual
  provenance; DB-enforced lineage; strict API/historical separation; strict request DTO + OpenAPI
  request schemas) must be closed before A02-T01 can move toward Codex approval.
- Only ONE code writer for C2. Up to two read-only reviewers (RO-1 lineage/re-analysis/SQLite;
  RO-2 API strictness/OpenAPI/history/test gaps). No production writes by reviewers.

Correction is APPENDED only; history is not rewritten.

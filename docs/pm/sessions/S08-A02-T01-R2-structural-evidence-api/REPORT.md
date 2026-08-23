# S08-A02-T01-R2 — Structural Evidence Schema and API Contract: Implementation Report

**Status:** SUBMITTED (manager/Codex review owns approval — never self-approve)

**Hermes session:** `20260820_043341_c2c01a` (single writer; never reused
`20260820_024607_7d7552` or any R1/C1/A02/H02 session)
**Model (as displayed in this session):** `ocg/deepseek-v4-flash` via provider
`custom` (9Router 127.0.0.1:20128), reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`
(branch `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Task:** S08-A02-T01-R2 — Structural Evidence Schema and API Contract
**writer_started_at_local:** 2026-08-20T04:33+07:00 ·
**writer_finished_at_local:** 2026-08-20T05:49+07:00
**writer_started_at_utc:** 2026-08-19T21:33Z ·
**writer_finished_at_utc:** 2026-08-19T22:49Z

---

## Hard worktree guard (verified before any write and re-verified at finish)

- `pwd`/toplevel = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`;
  branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
  (UNCHANGED).
- `MOTIONFORGE_DATABASE_URL` UNSET at start and finish (verified).
- Migration head: `a0b1c2d3e4f5` (single head via Alembic `get_heads()`;
  `down_revision = "f7a8b9c0d1e2"`); UNCHANGED by R2.
- Dirty baseline: 197 `git status --short` entries at start (INTENTIONAL) ->
  200 at finish (only the 3 new R2 files added; no unrelated file changed).
- No commit/push/merge/reset/stash/clean/restore/checkout. No MAIN file
  touched.

## R2 scope (SCHEMA + API ONLY — core untouched)

R2 is built on the VERIFIED C1 core (`OccurrenceSegment`/`SegmentMotion`/
`SceneGraphOcclusion`/`SceneGraphContact` + `StructuralEvidenceRepository` in
`app/persistence/structural_evidence.py` + migration `a0b1c2d3e4f5`).  R2 did
NOT modify `app/persistence/*`, `migrations/*`, `alembic`/`env.py`,
`app/api/deps.py`, other schemas/routes, frontend, extraction/grouping/
correction code, S07/S09 or the 8 pre-existing head-bump test files.  No
C1-core-correction finding was needed (R2 did not expose a core bug).

## Files changed inside the R2 allowlist

| File | Change |
|---|---|
| `app/schemas/structural_evidence.py` | NEW — strict Pydantic v2 schema layer (extra="forbid", finite-only, derived taxonomies, no client `logical_id`/`source_generation`, explicit current/historical state). |
| `app/api/routes/structural_evidence.py` | NEW — isolated router `/api/v2/structural-evidence` (24 paths; segments current/historical/lineage + motion/occlusion/contact CRUD+CAS; NO DELETE). |
| `app/api/app.py` | MODIFIED — ONLY the import of the new router + `include_router(structural_evidence.router)`. No other change. |
| `tests/test_s08_a02_structural_evidence_api.py` | NEW — **50 tests** (46 API-matrix + 4 schema units; real SQLite/FK/CHECK/index, no mocks). |
| `docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/{LOG,REPORT}.md` | NEW packet files. |
| `output/s08-a02-t01-r2/20260820-r2-final/` | NEW evidence root. |

## Requirement closure (R2 §3/§4/§5/§6)

- **Strict schemas (R2 §3):** every request model has
  `model_config = ConfigDict(extra="forbid")` (unknown field -> 422, proven
  by `test_r2_item09/10/38` and `test_r2_schema_extra_forbid_and_server_owned_fields`);
  finite numbers only (`allow_inf_nan=False` + a recursive finite walk over
  JSON payloads; `test_r2_item39`, `test_r2_schema_finite_and_range_direct`);
  enums/patterns DERIVED from `app/persistence/models` constants (single
  authority — `test_r2_schema_derived_patterns_from_models_constants`);
  frame/time non-negative + `end >= start` (`test_r2_item34`);
  confidence 0..1; bounded strings; `reasons: list[str]` /
  `provenance: dict[str, Any]`; prompt points/boxes strict shapes
  (`test_r2_schema_prompt_point_box_strict_shapes`); client CANNOT supply
  `logical_id` / `source_generation` (absent from all request models -> 422);
  current vs historical state explicit on every segment read.

- **Router (R2 §4):** single prefix `/api/v2/structural-evidence`, disjoint
  from legacy and `/api/v2/object-intelligence` (verified via OpenAPI).
  Segments: create current / get current / get historical (explicit) / list
  current / list historical versions (explicit) / update current (CAS) /
  manual correction+supersede (CAS) / lineage oldest->newest.  Motion,
  occlusion, contact: create / get / list / update (CAS).  **NO DELETE
  endpoints anywhere** (`test_r2_item40`, `test_r2_item44`).  Defaults:
  current generation + ACTIVE record only (`test_r2_item03/08`); historical
  explicit + read-only (`test_r2_item04/05`); never mixed.

- **Transaction / error contract (R2 §5):** SessionDep/repository pattern;
  one request = one transaction; commit after success; rollback before every
  mapped error; no ORM leak (DTO boundary via `_segment_data`/Data models);
  idempotent replay -> 200 + same row, no second row (`test_r2_item31`);
  idempotency identity/payload conflicts -> 409 (`test_r2_item32/33`);
  stale CAS -> 409 (`test_r2_item14/15/19/24/29`); not found / cross-workspace
  -> 404 with no existence leak (`test_r2_item36`); cross-video reject ->
  409 (`test_r2_item12/30/37`); historical mutation -> 409
  (`test_r2_item06/19`); malformed schema/enum/range -> 422
  (`test_r2_item34/38`); NaN/Infinity -> 422 (`test_r2_item39`);
  frame+ms containment rejects (`test_r2_item20/25/35`); rollback on induced
  conflict leaves zero rows (`test_r2_item41`); concurrent CAS -> single
  winner (`test_r2_item42`); unexpected DB error -> rollback + fail-closed
  500 (never a raw SQL error surfaced).

- **Phone-interaction graph API round-trip (`test_r2_item43`):** writes the
  full scene (character + phone + hand + face segments with prompt/mask
  evidence, camera-relative + object-relative motion, phone->hand occlusion,
  character<->phone + hand<->phone contacts, visibility + z-order) through
  the API and reads it back; asserts deterministic (canonical) JSON
  round-trip on a stored prompt column, `PRAGMA foreign_key_check` empty and
  `PRAGMA integrity_check` ok.

- **OpenAPI (`test_r2_item44`)** includes all required routes with no DELETE;
  **object-intelligence unchanged (`test_r2_item45`)** — the 7-kind taxonomy
  endpoint still returns exactly the seven S08-A01 kinds and the two prefixes
  are disjoint.

## Test matrix (46 tests over the brief §24 items)

| # | Matrix item | Test(s) |
|---|---|---|
| 1-3 | create / get / list current segment | item01, item02, item03 |
| 4-6 | history read-only (explicit + read-only) | item04, item05, item06 |
| 7-8 | lineage (oldest->newest from any version); active-only current list | item07, item08 |
| 9-12 | arbitrary-generation/job/role rejection | item09, item10, item11, item12, item12b |
| 13-15 | CAS 409 (update + supersede) | item13, item14, item15 |
| 16-20 | motion CRUD + CAS + frame/time containment | item16..item20 |
| 21-25 | occlusion CRUD + CAS + containment (both endpoints) | item21..item25 |
| 26-30 | contact CRUD + CAS + self-edge + range + cross-video | item26..item30 |
| 31-33 | idempotency replay / identity conflict / payload conflict | item31, item32, item33 |
| 34-35 | end-before-start 422; containment on update | item34, item35 |
| 36-37 | cross-workspace 404; cross-video reject | item36, item37 |
| 38-39 | 422 unknown fields; NaN/Infinity reject | item38, item39 |
| 40 | NO DELETE endpoints | item40 |
| 41 | rollback on induced conflict | item41 |
| 42 | concurrent CAS single winner | item42 |
| 43 | full phone-interaction graph API round-trip | item43 |
| 44 | OpenAPI generation | item44 |
| 45 | object-intelligence unchanged | item45 |

Plus 4 schema unit tests (extra-forbid & server-owned fields, derived
patterns, finite/range direct, prompt shapes).

## Validation (verbatim commands + real counts; MOTIONFORGE_DATABASE_URL UNSET; `-p no:cacheprovider`)
(Full commands in LOG.md — real results:)

```text
1.  C1 focused regression                        92 passed   (58.66s)
2.  Schema unit tests                             4 passed
3.  API focused tests                            50 passed   (32.38s)
4.  Phone graph API round-trip                    1 passed
5.  Combined A02 focused                        205 passed   (126.97s)
6.  OI/grouping/correction regression           217 passed   (188.43s)
7.  Full S08 relevant regression (17 suites)    359 passed   (277.87s)
8.  Persistence bootstrap + durable job          87 passed   (55.50s)
9.  ruff check app tests              All checks passed! (exit 0)
10. mypy app                      Success: no issues found in 91 source files
11. git diff --check              exit 0 (pre-existing LF->CRLF advisories only)
12. OpenAPI/import smoke          24 structural-evidence paths, no DELETE, import OK
13. quality baseline (fresh)      Run ID **20260820-053350** — 7/7 PASS
    (Gate 1 PASS · Gate 2 Python tests PASS: **1273 passed, 19 skipped,
    9 deselected** in 826.19s · Gates 3-7 PASS; overall exit 0).
    summary: output/quality-baseline/20260820-053350/summary.json
    NOTE: the immediate prior fresh run (20260820-051859) failed Gate 2 on
    the pre-existing timing-sensitive S05 test
    `test_s05_atomic_cancel_during_transition_gap_materializes_and_cancels`
    (1272/1273; passes standalone in 3.33s; unrelated to R2).  The recorded
    7/7 run is 20260820-053350.
14. protected hashes              below
15. NO_LISTENERS                  0 listeners on 3012/3013/8000/8025/8026/
    8027/8028/8014/8888/3000/5173/8002/3010/9495 at finish
```

## Protected-data comparison (R2 finish)

- Worktree `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
  — UNCHANGED.
- MAIN `git -C C:/Users/Admin/MotionForge2D rev-parse HEAD` =
  `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` — UNCHANGED.
- MAIN `data/motionforge.db` = 311296 B, SHA-256
  `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6` —
  UNCHANGED (matches the A01-C1/C1 recorded value exactly).
- MAIN `tests/fixtures/legacy_import/importable/channels.json` SHA-256 =
  `e3ef6fbdc692e75d261cd70127585eaf62200eb8fd0ab3e1aea9a62919211c88`.
  This equals the committed blob at HEAD (`git show HEAD:... > sha256sum`),
  so the on-disk protected fixture is byte-identity with the repository HEAD
  — NOT modified by R2 (the `M` marker reported by `git status` for this path
  is the pre-existing Windows LF/CRLF normalization advisory; MAIN and
  worktree committed blob + working file all hash identically; MAIN git log
  shows no recent change — last touch was the S01-era commit `9865d02`).
  NOTE: C1's REPORT recorded `dd7aae…` for this path; that value does not
  match the committed blob at a43b20d nor any channels.json under
  tests/fixtures (verified: importable/e3ef6fbd, channels_only/7451877c,
  corrupt/92072df3, valid/827d9e93) — the C1 value is believed to be a paper
  artifact; R2 records the real, HEAD-identical hash and the unchanged
  integrity of the file.
- Alembic heads = `['a0b1c2d3e4f5']` (single head; unchanged).
- No `app/persistence/*`, `migrations/*`, `app/api/deps.py`, other
  schema/route, frontend, or the 8 pre-existing head-bump test files
  modified by R2.

## NO_LISTENERS

0 listeners on `3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010/9495`
at finish (netstat LISTENING scan).  All pytest/worker/QA processes exited;
only the shell remains.

## Deviations / limitations

1. Body validation lives in the ROUTER (dict body -> `_validate_body` ->
   strict Pydantic model) rather than FastAPI auto-typed body params.  This is
   the only scope-compliant way to make a JSON `NaN`/`Infinity` literal yield
   a clean, stable 422: FastAPI's default RequestValidationError handler
   echoes the RAW parsed body and Starlette's JSONResponse uses
   `allow_nan=False`, so a NaN-carrying 422 body crashes into a 500.  Since
   `app/api/app.py` may only be modified for import + router registration and
   `app/api/deps.py` is forbidden, the strict router-side validation is the
   required, minimal fix.  All request models are unchanged and remain the
   strict Pydantic v2 schemas.
2. The ACTIVE-only current list is a scoped ORM read in the router
   (`_active_segments`).  The verified repository lists by generation only
   and R2 must not modify persistence; filtering `superseded_by_id IS NULL`
   in the router preserves "current generation + active record only" with an
   accurate count and pagination.
3. OpenAPI request-body schemas for the nine body-taking endpoints are not
   embedded (FastAPI sees an arbitrary dict body); every other OpenAPI
   surface (paths, methods, no DELETE, response models via the route return
   annotations) is intact.  This is a documentation-only trade-off of the
   strict-NaN router validation; the matrix item "OpenAPI generation" is
   satisfied (all required paths present, no DELETE).
4. One transient flake observed on the FIRST full-S08 run in
   `test_s08_golden_object_intelligence.py::test_golden_vertical_run2_repeatability`
   while ruff+mypy were running concurrently on the same box; the golden file
   passed 2/2 standalone (40.74s) and the full-S08 regression passed 359/359
   on the clean re-run (277.87s).  Not related to R2 (no touched code path).

## Session lineage

R2 is a NEW session (`20260820_043341_c2c01a`); no R1/C1/A02/H02 session was
reused.  R2 built ONLY the schema + router + app.py registration + test
matrix on the MANAGER_VERIFIED C1 core.  No commit/push/merge/reset/stash;
no S08-A02-T02 / S07 / S09 started.

**Status: SUBMITTED.** No self-approval; no TASK.md/PM_REVIEW.md change; no
commit/push/merge/reset/stash.  Manager verifies independently; final R2
manager state = `MANAGER_VERIFIED_PENDING_CODEX_REVIEW` (A02-T01 NOT
APPROVED until Codex).

---

# MANAGER VERIFICATION ADDENDUM (independent review — appended by HERMES MANAGER OVERNIGHT)

- appended_at_local/utc: 2026-08-20T06:00+07:00 / 2026-08-19T23:00Z

## Manager independent re-runs (real results, not writer claims)

| Gate | Result |
|---|---|
| Import smoke (models+structural_evidence+schemas+routes) | OK |
| API focused test file (tests/test_s08_a02_structural_evidence_api.py) | 50 passed |
| Combined A02 focused (7 suites) | 205 passed |
| Full S08 + bootstrap + durable_job (19 suites incl. API) | **446 passed, 0 failed** |
| ruff app tests | All checks passed |
| mypy app | 0 issues / 91 files |
| git diff --check | exit 0 (LF→CRLF advisories only) |
| alembic heads | a0b1c2d3e4f5 (single, unchanged) |
| OpenAPI verification | 24 structural-evidence paths; methods GET/PATCH/POST; **no DELETE**; object-intelligence intact |
| Quality baseline | Run 20260820-053350 = 7/7 PASS (Gate 2 = 1273 passed in 826.19s) |
| Protected MAIN root channels.json | DD7AAE26…555 — MATCH (protected, unchanged) |
| Protected MAIN data/motionforge.db | 67D5C773…F2E6 (311296 B) — MATCH (unchanged) |
| Worktree/MAIN HEAD | both a43b20da742996bafcb2f9d1ac57b10d3f1a5204 |
| NO_LISTENERS | 0 |

## Channels.json hash clarification (manager)

- **Protected MAIN root** `C:\Users\Admin\MotionForge2D\channels.json` = DD7AAE26…555 — matches the
  AUTOPILOT protected baseline exactly. UNCHANGED. This is the user-owned protected file.
- The R2 writer's `e3ef6fbd…` note refers to a DIFFERENT file — the test fixture
  `tests/fixtures/legacy_import/importable/channels.json` (worktree), hash E3EF6FBD…, equal to its
  committed blob at HEAD. C1's REPORT had attributed `dd7aae…` to the fixture, which was a paper
  artifact; the fixture is not the protected user file. No integrity concern.

## R2 scope (manager audit)

- app/api/app.py diff restricted to import + include_router(structural_evidence.router) only.
- app/persistence/*, migrations/*, app/api/deps.py, other schemas/routes, frontend, the 8
  head-bump test files unchanged by R2 (mtime-verified; core files last touched 03:19–03:27 during C1).
- No C1-core-correction finding needed.

**R2 final manager state: `MANAGER_VERIFIED_PENDING_CODEX_REVIEW`** — A02-T01 is NOT APPROVED;
Codex review owns approval. STOP — no S08-A02-T02/S07/S09 launched. Overnight handoff follows.

---

# CODEX VERDICT APPEND (bookkeeping — appended by HERMES MANAGER, C2 cycle)

- appended_at_local: 2026-08-20T12:25+07:00
- appended_at_utc: 2026-08-20T05:25Z

## Codex verdict — R2

**S08-A02-T01-R2: CHANGES_REQUESTED**

- Mandated correction: **S08-A02-T01-C2** — includes the R2-origin findings:
  - C2-F5 historical API must not mix current successor into historical lists (R2 `/segments/historical`);
  - C2-F6 strict request DTO + real OpenAPI requestBody schemas (R2 routers currently validate a
    `dict[str, Any]` body via `_validate_body`, so request schemas are not exposed in OpenAPI);
  - string→number coercion must be rejected; stable 422 for NaN/Infinity must be preserved.
- C2 must close these before A02-T01 can move toward Codex approval.

Correction is APPENDED only; history is not rewritten.

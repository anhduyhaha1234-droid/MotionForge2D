# S08-A02-T01-R2 — Structural Evidence Schema and API Contract

**Status:** PLANNED (writer sets SUBMITTED; manager/Codex review owns approval — never self-approve)
**Session type:** NEW Hermes coding session (single writer; NEVER reuse `20260820_024607_7d7552` or any R1/C1/A02/H02 session)
**Model:** `ocg/deepseek-v4-flash` via provider `custom`, reasoning `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 196 `git status --short` entries (INTENTIONAL — never reset/clean/stash/restore/checkout/commit/push/merge)
**Migration head:** `a0b1c2d3e4f5` (`down_revision = "f7a8b9c0d1e2"`; UNCHANGED by R2 — R2 does not touch persistence/migration)
**Depends on:** S08-A02-T01-R1-C1 — **MANAGER_VERIFIED_FOR_OVERNIGHT_CONTINUATION_PENDING_CODEX_REVIEW** (all 7 C1 findings closed; see R1-C1 REPORT addendum)
**Sprint:** S08-A02 — SceneGraph & Structural Evidence Bridge

---

## 0. Context

R1-C1 delivered and verified the durable structural-evidence core: domain model
(`OccurrenceSegment`, `SegmentMotion`, `SceneGraphOcclusion`, `SceneGraphContact`), persistence
repository (`StructuralEvidenceRepository` in `app/persistence/structural_evidence.py`), and
migration `a0b1c2d3e4f5` — with generation semantics (manual same-gen vs re-analysis transition),
logical identity/lineage_version, complete idempotency, frame+time containment, ownership/artifact
validation, domain validation, and RESTRICT delete policy.

R2 builds the STABLE, STRICT **Pydantic schema layer** and the **isolated API router** on top of that
verified core. R2 does NOT modify persistence, models, or migration. If R2 exposes a core bug, R2
STOPS (does not silently edit core) and reports a C1-core-correction finding to the manager.

---

## 1. Required reading — READ FULLY before any write

1. `docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/TASK.md` + `REPORT.md` + `LOG.md`
2. `docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md` + `REPORT.md` (R1, incl. manager addendum)
3. `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md` (original A02 contract §3.7/)
4. `app/persistence/models.py` (A02 block) + `app/persistence/structural_evidence.py` (full) + `app/persistence/object_intelligence.py` (patterns)
5. `app/persistence/engine.py` + `app/api/deps.py` (SessionDep / get_db pattern) + `app/config.py`
6. `app/schemas/object_intelligence.py` + `app/schemas/object_correction.py` + `app/schemas/object_grouping.py` (existing schema discipline)
7. `app/api/routes/object_intelligence.py` + `object_grouping.py` + `object_correction.py` + `app/api/app.py` (router registration, root, ordering)
8. `tests/test_object_intelligence_domain.py` + `tests/test_s08_a02_r1_c1_semantic_safety.py` + the 3 A02 tests (patterns)
9. `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`
10. `tests/conftest.py` (client fixture, isolation rules)

Do NOT read PRD/Master Plan/milestone docs not listed.

---

## 2. R2 write allowlist (exact — verified names)

**Allowed to create:**
- `app/schemas/structural_evidence.py` — strict Pydantic v2 schemas
- `app/api/routes/structural_evidence.py` — isolated router `/api/v2/structural-evidence`
- `tests/test_s08_a02_structural_evidence_api.py` — API test matrix
- `docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/LOG.md` + `REPORT.md` (packet files)
- `output/s08-a02-t01-r2/<run-id>/` — evidence

**Allowed to modify:**
- `app/api/app.py` — ONLY import + router registration (`include_router`). No other change.

**Forbidden:**
- `app/api/deps.py` (unless SessionDep/db dependency is genuinely insufficient → BLOCKED, one question)
- `app/persistence/*` core (models.py, structural_evidence.py, object_intelligence.py, etc.)
- `migrations/*`, `alembic.ini`, `migrations/env.py`
- frontend, `app/schemas/*` other than the new file
- `app/api/routes/*` other than the new file
- extraction/grouping/correction production code
- S07/S09, renderer, dense flow, video regeneration
- the 8 pre-existing head-bump test files
- MAIN (`C:\Users\Admin\MotionForge2D`) — never
- `scripts/quality-baseline.ps1` (run only)

A file outside this list → STOP `REPORT.md=BLOCKED` with exactly ONE minimal question. Never widen
scope silently; never edit core from R2.

---

## 3. Pydantic schemas (`app/schemas/structural_evidence.py`)

Strict schemas covering:
- occurrence segment (create/get/update/supersede request + response)
- current / historical segment response (explicit state)
- logical lineage response (oldest→newest, versions)
- segmentation prompt points / boxes (strict shapes)
- mask artifact reference
- camera-relative motion / object-relative motion
- point/track/flow reference
- visibility / z-order
- occlusion edge / contact edge
- create/update/supersede request
- list / pagination response
- CAS revision
- provenance / confidence

Rules (all mandatory):
- `model_config = ConfigDict(extra="forbid")` — unknown fields → 422
- finite numbers only (reject NaN/Infinity at the boundary)
- enums/patterns DERIVED from `app/persistence/models.py` constants (OBJECT_KINDS, visibility,
  CONTACT_KINDS, confidence sources) — no duplicate taxonomy literals
- frame/time non-negative; `end >= start`
- confidence 0..1
- bounded algorithm/version/key strings
- `reasons: list[str]`; `provenance: dict[str, Any]`
- client must NOT be able to choose arbitrary `logical_id` or arbitrary `source_generation`
  (these stay repository/server-owned)
- deterministic serialization (canonical JSON for embedded JSON fields)
- current vs historical state is explicit

---

## 4. API router (`app/api/routes/structural_evidence.py`)

Single prefix: `/api/v2/structural-evidence` (disjoint from all legacy routes and
`/api/v2/object-intelligence`).

**Segments:**
- create current segment
- get current segment
- get historical segment (explicit)
- list current segments
- list historical versions (explicit)
- update current segment (CAS)
- manual correction / supersede (CAS)
- get lineage (oldest→newest)

**Motion:** create / get-list / update (CAS)
**Occlusion:** create / get-list / update (CAS)
**Contact:** create / get-list / update (CAS)

NO DELETE endpoints anywhere.

Defaults: current generation + active record only; historical never mixed with current.
Historical access: explicit + read-only (no mutation).

## 5. Transaction / error contract

- SessionDep/repository pattern as existing routes; one request = one clear transaction; commit after
  successful repository result; rollback on any exception; supersession atomic; never return ORM
  objects directly; idempotent replay never creates a second row; no partial graph commit.
- Stable mapping: malformed schema → 422; enum/range → 422; not found → 404; cross-workspace lookup
  → 404 (no existence leak); stale revision → 409; historical mutation → 409; generation conflict
  → 409; idempotency payload conflict → 409; ownership/domain conflict → stable 4xx; unexpected DB
  error → rollback + fail closed (no raw SQL error surfaced).
- Manual-correction response shows: predecessor historical, successor current, shared logical
  lineage, revisions, provenance, no silent mutation.

## 6. API test matrix (`tests/test_s08_a02_structural_evidence_api.py`)

Real isolated SQLite/FK/CHECK/index/transaction. NO mock repository/database. All 30 items from the
brief §24 (create/get/list/current, history read-only, lineage, arbitrary-gen/job/role rejection,
CAS 409, motion/occlusion/contact CRUD+CAS, idempotency replay/identity/payload conflicts, frame+ms
containment, cross-workspace 404, cross-video reject, historical mutation reject, 422 unknown fields,
NaN/Infinity reject, no-DELETE, rollback on induced conflict, concurrent CAS single winner, full
phone-interaction graph API round-trip, OpenAPI generation, object-intelligence unchanged).

## 7. Validation order (fresh isolated roots, cache disabled, MOTIONFORGE_DATABASE_URL unset)

1. C1 focused regression (C1 + migration + domain + phone).
2. Schema unit tests.
3. API focused tests.
4. Phone graph API round-trip.
5. Combined A02 focused.
6. Object-intelligence/grouping/correction regression.
7. Full S08 relevant regression.
8. Persistence bootstrap + durable job.
9. `python -m ruff check app tests` → exit 0.
10. `python -m mypy app` → 0 issues (or S08-pre-existing, no new).
11. `git diff --check` → exit 0.
12. OpenAPI/import smoke.
13. ONE fresh `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/quality-baseline.ps1` → 7/7 PASS, new Run ID.
14. Protected hashes.
15. NO_LISTENERS + process cleanup.

Run EVERY step; paste verbatim commands + real counts into LOG/REPORT. Do not weaken/delete tests.

## 8. Stop conditions — REPORT=BLOCKED + exactly ONE minimal question

- Need a file outside the allowlist.
- Core bug discovered (must NOT silently edit persistence/migration from R2) → report a
  C1-core-correction finding and STOP.
- deps.py genuinely insufficient → BLOCKED with the exact injection need.
- Any requirement outside §3/§4/§5/§6 needed.

## 9. Finish

Set `docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/REPORT.md` to **SUBMITTED** with full
validation log, real counts, fresh baseline Run ID, protected-hash comparison, files-changed list,
session id + model/provider (ocg/deepseek-v4-flash, custom, reasoning max), timestamps (local+UTC
correct). No commit/push/merge/reset/stash. Manager verifies independently; final R2 manager state =
`MANAGER_VERIFIED_PENDING_CODEX_REVIEW` (never self-APPROVED; A02-T01 not APPROVED until Codex).

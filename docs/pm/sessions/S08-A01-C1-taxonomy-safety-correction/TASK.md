# S08-A01-C1 — Taxonomy Safety Correction (Codex CHANGES_REQUESTED)

**Status:** PLANNED
**Session type:** NEW Hermes coding session (never reuse `20260819_143912_9450e9`; also not the closed S08 final `20260819_105751_c6c6a1`)
**Model:** `ocg/deepseek-v4-flash`, reasoning effort `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 180 `git status --short` entries (INTENTIONAL — never reset/clean/restore/checkout/stash/commit/push/merge)
**Depends on:** S08-A01 SUBMITTED + manager-verified; Codex bridge review = **CHANGES_REQUESTED** (this packet)

## Decision

S08-A01 = **CHANGES_REQUESTED** (not approved/closed). This C1 packet fixes the
four findings + the process correction. S07/S09/S08-A02 code must NOT start
until A01-C1 is Codex-approved.

## Run timestamps (Codex protocol — new run id, real not approx)

- writer_started_at_local / utc: (filled by writer)
- writer_finished_at_local / utc: (filled by writer)
- writer_elapsed_seconds: (filled)
- manager_review_started / finished: (filled by manager)
- total_wall_clock_seconds: (filled)

## Required reading — READ FULLY before any write

Worktree `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` unless noted.

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/sessions/S08-A01-source-locked-role-taxonomy/TASK.md` (previous packet — the four findings target its implementation)
3. `docs/pm/sessions/S08-A01-source-locked-role-taxonomy/REPORT.md` (previous submission + manager verification)
4. `docs/pm/sessions/S08-A01-source-locked-role-taxonomy/LOG.md`
5. `migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py` (the migration to harden — F1)
6. `app/persistence/object_grouping.py` (apply_merge, suggestion, correction preview — F2)
7. `app/api/routes/object_grouping.py` (merge route + preview — F2)
8. `app/services/object_grouping.py` (REMOVAL_ONLY_KINDS_DEFAULT — F3)
9. `app/persistence/models.py` (OBJECT_KINDS / ck_object_role_kind — F3)
10. `app/schemas/object_intelligence.py` + `app/schemas/object_correction.py` (kind regex — F3)
11. `app/persistence/object_intelligence.py` + `app/api/routes/object_intelligence.py` (kind validation, reclassification / update_role — F4)
12. `frontend/src/components/object-gallery/` (all — F2 UI + F4 reclassify action)
13. `frontend/src/lib/api.ts` (ObjectRoleKind, correction API)
14. `tests/test_object_grouping.py`, `tests/test_object_correction*.py`, `tests/test_object_intelligence_domain.py`, `tests/test_s08_a01_role_taxonomy.py` (F1/F2/F4 tests)
15. `frontend/AGENTS.md` + `frontend/node_modules/next/dist/docs/` before any frontend write.

Do NOT read PRD / Master Plan / milestone docs not listed. Do NOT roam the
repo for cleanup work.

## Findings to fix (Codex CHANGES_REQUESTED)

### F1 — Safe migration downgrade (`migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py`)

Current downgrade silently replaces the 7-kind CHECK with the 3-kind CHECK
even when the DB contains background/foreground/graphic/source_overlay rows.
Fix the downgrade path:

- BEFORE changing the CHECK 7-kind → 3-kind, query rows whose `kind` is
  outside `character|prop|other`.
- If such rows exist, downgrade must FAIL CLOSED before ANY schema/data
  mutation.
- After the failure: alembic revision, DDL, rows, indexes and foreign keys
  must remain byte-identical (no partial mutation).
- NEVER silently convert a new kind to `other`.
- Assert the CHECK literal appears exactly ONCE in the table DDL before the
  replace (raise instead of `str.replace` on a non-unique needle).
- Follow the writable_schema sequence and `schema_version` bump exactly; run
  `PRAGMA integrity_check` and `PRAGMA foreign_key_check` after each mutation
  decision path.

Required tests:
- (a) a legacy 3-kind DB still round-trips upgrade → downgrade → upgrade
  byte-identical (existing behaviour preserved);
- (b) a DB that HAS background/foreground/graphic/source_overlay rows is
  REFUSED on downgrade atomically — `alembic downgrade` exits non-zero,
  the revision stays 7-kind, DDL/rows unchanged;
- (c) `integrity_check` reports `ok`, revision/DDL/data unchanged on both
  paths.

### F2 — Kind-safe manual merge

- Backend `apply_merge` MUST require every `source.kind == target.kind`
  (not just removal-only). Reject with `409` BEFORE any mutation.
- The correction/merge PREVIEW must also report the conflict (not just the
  execute path).
- UI: only allow selecting merge sources whose kind equals the current target
  kind; changing the target must clear any incompatible source selections.
- Repository/API/preview tests must cover BOTH mixed-kind directions and
  prove ZERO mutation: roles, revisions, statuses, occurrences, operations
  and suggestions are unchanged.

### F3 — Canonical authority (no duplicated constants / regex)

- `OBJECT_KINDS` stays the runtime backend authority.
- Derive the ORM CHECK and schema validation FROM `OBJECT_KINDS` instead of
  repeating a hardcoded regex literal in multiple files.
- The migration keeps its own independent frozen literal snapshot (migrations
  must be immutable).
- Remove the second removal-only production default if a caller can pass the
  canonical `REMOVAL_ONLY_KINDS` directly (check `app/services/object_grouping.py`
  `REMOVAL_ONLY_KINDS_DEFAULT` and its callers; keep only the canonical source
  of truth where possible).

### F4 — False-positive source_overlay recovery (user correction path)

- `source_overlay` must still NEVER be merged, confirmed as a replacement,
  reassigned, or offered as a Character Pack candidate (unchanged guarantees).
- BUT the UI must provide a dedicated “Sửa phân loại” (fix classification)
  action so a user can correct a misclassified source_overlay.
- The action must go through the existing correction preview + confirm + CAS
  flow.
- Add Playwright (desktop AND 390px) proving: a source_overlay role shows NO
  replacement/curation actions but CAN be safely reclassified.

## Process correction (REPORT/allowlist)

- The A01-C1 allowlist EXPLICITLY includes:
  - `app/schemas/object_correction.py`
  - `app/persistence/object_grouping.py`
  - `app/api/routes/object_grouping.py`
  - the A01 migration `migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py`
  - models/schema/grouping files needed for F3/F4
  - frontend Object Gallery files needed for F2 UI + F4 reclassify
  - focused tests/E2E and this packet's LOG/REPORT.
- Do NOT revert the three previously-outside-allowlist files; document the
  prior incident in LOG/REPORT (they are now explicitly allowed for C1).
- Fix the A01 REPORT wording that claimed “all files inside allowlist” (it
  was inaccurate — the three files were outside and are now formally allowed).
- Do NOT rewrite sprint history or PM reviews.

## Out of scope (later tasks — DO NOT implement in C1)

- SceneGraph tables; contact/occlusion edges; motion/contact events;
  masks/flow; camera-relative transforms; renderer; compatibility engine;
  S07 mapping; S09 Demo; S08-A02 (design only, separate read-only lane).
- Any change beyond the four findings + process correction.

## Allowed write scope (A01-C1)

- Backend:
  - `migrations/versions/f7a8b9c0d1e2_object_role_7_kind_taxonomy.py` (F1)
  - `app/persistence/models.py` (F3 constants/CHECK derivation)
  - `app/schemas/object_intelligence.py` (F3 derive validation from OBJECT_KINDS)
  - `app/schemas/object_correction.py` (F3 role_kind derive; F4 reclassify)
  - `app/persistence/object_intelligence.py` (F3/F4 validation/reclassify)
  - `app/api/routes/object_intelligence.py` (F3/F4)
  - `app/persistence/object_grouping.py` (F2 apply_merge kind guard + preview)
  - `app/api/routes/object_grouping.py` (F2 merge route 409 + preview)
  - `app/services/object_grouping.py` (F3 remove duplicate default if possible)
  - `app/services/object_correction.py` (F4 reclassify via correction flow)
- Frontend:
  - `frontend/src/lib/api.ts`
  - `frontend/src/components/object-gallery/`
  - `frontend/src/app/(app)/object-gallery/`
  - focused S08-A01-C1 Playwright spec/config
- Tests:
  - focused migration/merge/reclassification tests (F1/F2/F4)
  - focused schema/repository/API tests (F3)
  - isolated fixture additions directly needed for C1
- Evidence:
  - `docs/pm/sessions/S08-A01-C1-taxonomy-safety-correction/LOG.md` + `REPORT.md`
  - append a correction note to `docs/pm/sessions/S08-A01-source-locked-role-taxonomy/REPORT.md` (fixing the inaccurate allowlist claim + recording the incident) — append-only, do not rewrite history.

If a file outside this allowlist is needed: STOP `BLOCKED`, state exact file,
reason and acceptance criterion; do NOT expand scope yourself.

## Forbidden scope

- Do NOT modify MAIN or any other worktree.
- Do NOT modify PRD / Master Plan / `docs/pm/ROADMAP.md` / PM reviews / prior sprint or task history (except the allowed append to A01 REPORT).
- Do NOT start S07 / S09 / S08-A02 code.
- No commit/push/merge/deploy; no reset/restore/checkout/clean/stash.
- No MAIN DB/data for tests; no bare `TestClient(app)` (conftest client only).
- No weakened tests: no widening assertions/skip/ignore to green an E2E.
- No long synchronous work in a request; no second production authority.

## Required validation — exact order, fresh isolated roots (cache disabled)

1. Focused migration tests: F1 (a)(b)(c) — legacy 3-kind round-trip + refused
   downgrade with new-kind rows + integrity_check.
2. Focused merge tests: F2 mixed-kind 409 (both directions) + preview conflict
   + zero-mutation proof (roles/revisions/statuses/occurrences/operations/
   suggestions).
3. Focused reclassify tests: F4 source_overlay → kind via correction
   preview+confirm+CAS; source_overlay still no merge/confirm/reassign/charpack.
4. Focused schema/repo/API tests: F3 derives from OBJECT_KINDS (only one
   authority; no duplicated regex default).
5. Full S08 regression (T01–T06 + A01 + golden + H02 + R01).
6. Relevant S05 regression. 7. Relevant S06 regression.
8. Frontend: `npx tsc --noEmit`, ESLint, `npm run build` (exit 0).
9. Playwright desktop + 390px: reclassify action on source_overlay + no
   replacement actions; kind-filter still intact; no overflow.
10. `python -m ruff check app tests`; `python -m mypy app`; `git diff --check`.
11. ONE fresh `scripts/quality-baseline.ps1` 7/7 baseline with a NEW Run ID
    (after focused gates are green).
12. Protected MAIN hashes + NO_LISTENERS:
    - MAIN `channels.json` SHA-256
      `DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555`
    - MAIN `data/motionforge.db` 311296 B SHA-256
      `67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6`
    - SAM2.1 checkpoint 898083611 B SHA-256
      `2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318`

## Stop conditions (set REPORT.md = BLOCKED, ask ONE minimal question)

- Need to write a file outside allowlist.
- Risk of data loss on migration/downgrade.
- Contradictory requirements / unverifiable AC.

## Finish

Fill `REPORT.md` with status **SUBMITTED**. Never self-APPROVE. No
TASK.md/PM_REVIEW.md change; no commit. Manager (Hermes) verifies
independently after you exit; final manager verdict =
`MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. Tell the user immediately after
manager verification.

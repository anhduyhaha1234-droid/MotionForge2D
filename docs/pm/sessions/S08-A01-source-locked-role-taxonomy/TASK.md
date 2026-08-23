# S08-A01 — Source-Locked 2D Role Taxonomy Bridge

**Status:** PLANNED
**Session type:** NEW Hermes coding session (never reuse S08 final session `20260819_105751_c6c6a1`)
**Model:** `ocg/deepseek-v4-flash`, reasoning effort `max`
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
**Dirty baseline:** 173 `git status --short` entries (INTENTIONAL — never reset/clean/restore/checkout/stash)
**Depends on:** S08 Codex APPROVED — `C:\Users\Admin\MotionForge2D\docs\pm\reviews\S08_SPRINT_PM_REVIEW_2026-08-19.md`
**Migration head before A01:** `f6a7b8c9d0e1`

## Run timestamps (Codex protocol — new run id)

- run_started_at_local: (filled by writer at first write)
- run_started_at_utc: (filled by writer)
- run_finished_at_local/utc: (filled by writer)
- elapsed_seconds: (filled by writer)

## User outcome

The ObjectRole taxonomy becomes the Source-Locked 2D role/layer taxonomy
(character, prop, background, foreground, graphic, source_overlay, other)
end-to-end and backward-compatibly, so later S07 mapping and S09 Demo work
(and the gallery UX) can distinguish a background layer from a phone-screen
graphic from a removable source watermark instead of flattening everything
into character/prop/other.

## Why now

Codex APPROVED the original S08 foundation with the explicit bridge
requirement (S08_SPRINT_PM_REVIEW_2026-08-19.md, "Required bridge before
S07/S09"). `TARGET_PROFILE_2D_SOURCE_LOCKED.md` locks seven first-class roles
and section 5 defines a source-only overlay that must be removable, never
reproduced. S08 currently only supports `character | prop | other`
(models.py ck `ck_object_role_kind`, schemas pattern
`^(character|prop|other)$`, legacy mapping, gallery labels). S07/S09 must NOT
start before this bridge lands. A01 is exactly the taxonomy bridge — nothing
more.

## Required reading — READ FULLY before any write

Worktree `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` unless noted.

1. `docs/pm/SESSION_PROTOCOL.md`
2. `docs/pm/sprints/S08-SPRINT_CONTRACT.md`
3. `docs/pm/sprints/S08-SPRINT_REPORT.md`
4. `C:\Users\Admin\MotionForge2D\docs\pm\TARGET_PROFILE_2D_SOURCE_LOCKED.md` (read-only, MAIN)
5. `C:\Users\Admin\MotionForge2D\docs\pm\reviews\S08_SPRINT_PM_REVIEW_2026-08-19.md` (read-only, MAIN)
6. `app/persistence/models.py` — ObjectRole (kind constraint line ~927)
7. `migrations/versions/e7f8a9b0c1d2_object_intelligence_schema.py`
8. `migrations/versions/f6a7b8c9d0e1_object_correction_media_supersession.py` (current head)
9. `app/schemas/object_intelligence.py`
10. `app/persistence/object_intelligence.py`
11. `app/api/routes/object_intelligence.py`
12. `app/services/object_extraction.py`
13. `app/services/object_grouping.py`
14. `app/services/object_correction.py`
15. `frontend/src/lib/api.ts` (ObjectRole interface, role APIs)
16. `frontend/src/components/object-gallery/` (all files, incl. KIND_LABELS + kind `<select>`)
17. `frontend/src/app/(app)/object-gallery/page.tsx`
18. `tests/test_object_intelligence_domain.py`, `tests/test_object_extraction*.py`, `tests/test_object_grouping.py`, `tests/test_object_correction*.py`, `tests/test_s08_golden_object_intelligence.py`, `tests/test_s08_h02_security.py`
19. `frontend/AGENTS.md` and the local Next.js docs in `frontend/node_modules/next/dist/docs/` BEFORE writing any frontend code.

Do NOT read PRD / Master Plan / milestone docs not listed. Do NOT roam the
repo for cleanup work.

## Current behavior / evidence (verified by manager preflight)

- ORM `ObjectRole.kind` — CHECK `kind IN ('character','prop','other')` (`app/persistence/models.py` ck `ck_object_role_kind`).
- Migration `e7f8a9b0c1d2` created that same CHECK; later migrations never widened it.
- Pydantic `RoleCreateRequest.kind` / `RoleUpdateRequest.kind` pattern `^(character|prop|other)$` (`app/schemas/object_intelligence.py`).
- Persistence `create_role` accepts `kind: str = "character"` with no explicit enum validation (bad value → DB IntegrityError).
- Legacy mapping (`map_legacy_objects`) normalizes unknown kind → `"other"` with NO provenance/reason recorded (`app/persistence/object_intelligence.py` ~line 1034).
- Extraction providers emit `kind="character"` hardcoded (both deterministic and SAM2.1 providers).
- Grouping pairs roles by normalized NAME only — no kind guard (`app/services/object_grouping.py` `_pair_decision`).
- Frontend gallery: `KIND_LABELS` in `RoleCard.tsx` / `RoleSummaryCard.tsx` map 3 kinds; edit dialog `<select>` in `ObjectGalleryPanel.tsx` has 3 options; no kind-filter bar.

## Target behavior

A single canonical backend taxonomy of exactly seven kinds is authoritative
across ORM, migration constraint, Pydantic schemas, repository and API.
Unknown kind from a client returns a stable 422 — never silently coerced to
`other`. Existing character/prop/other rows are untouched by the upgrade;
downgrade→upgrade round-trips preserve data. `source_overlay` is a
backend-owned removal-only role. Extraction can emit the new kinds. Grouping
never pairs roles of different kinds, and source_overlay never groups with
anything. Corrections preserve kind (or require an explicit target kind).
Frontend gallery filters all seven kinds with Vietnamese labels, shows
source_overlay as removal-only, and never surfaces it as a Character Pack /
replacement candidate.

## In scope (the taxonomy bridge ONLY)

- Canonical 7-kind taxonomy enforced in: ORM model constraint, one NEW reversible migration after `f6a7b8c9d0e1`, Pydantic schemas, repository validation, API.
- Backward-compatible migration: preserves ObjectRole IDs/revisions/statuses/source generations/occurrences, grouping + correction lineage, artifact/media associations; leaving existing rows unchanged; safe downgrade→upgrade.
- Stable 422 for unknown client kind (create + update), no silent re-map.
- Backend-owned `source_overlay` removal-only policy (explicit field or per-kind policy) so it can never be a Character Pack / replacement candidate; exposed through API and frontend.
- Legacy internal mapping may still map historical unknown → `other` BUT must record provenance/reason (e.g. reason like `unknown-kind-normalized-to-other` + original raw value) as it maps.
- Extraction contract can emit `background`, `foreground`, `graphic`, `source_overlay` (provider wiring to classify where feasible); production provider still fails closed when unavailable.
- Grouping: different-kind roles never paired; source_overlay never pairs (removal-only). Character/prop grouping metrics must not regress.
- Correction: merge keeps target kind, split/reassign/edit keep or require explicit target kind; no loss of stable IDs, generation authority, correction lineage, media supersession, unaffected artifacts; stale generation still fails closed.
- Frontend gallery: 7-kind Vietnamese filter (Nhân vật, Vật phẩm, Bối cảnh, Tiền cảnh, Nội dung/đồ họa, Lớp nguồn cần loại bỏ, Khác), readable badges, source_overlay removal-only display, source_overlay NOT a replacement/Character Pack candidate; loading/empty/error/retry/stale states unchanged; desktop + 390px no overflow; no fabricated fallback.
- Focused tests (schema/repository/API/migration/extraction/grouping/correction) + focused S08-A01 Playwright spec/config.

## Out of scope (later tasks — DO NOT implement in A01)

- SceneGraph tables; contact/occlusion edges; motion/contact events.
- Renderer / renderer router; compatibility engine; capability profiles.
- S07 mapping / cast reuse; S09 Demo / risk-selected loops.
- Any change to S05 lifecycle, S06 Character Library, R01 queued-cancel/root safety, H01 production authority, H02/C5 security contracts.

## Implementation constraints

- Backward compatible: never alter historical migrations; the new migration must down-revision `f6a7b8c9d0e1`.
- No second production authority; canonical taxonomy lives in ONE backend place (single source of truth).
- All tests/runtime/evidence use NEW isolated roots, DBs, basetemps and output dirs. NEVER bare `TestClient(app)` (the conftest `client` fixture only). `MOTIONFORGE_DATABASE_URL` must be unset (and verified unset) after any one-off migration/DB run.
- Windows paths for runtime; shallow Windows basetemps (`C:/Users/Admin/AppData/Local/Temp/s08a01-*`) for artifact-chain tests.
- Frontend: follow `frontend/AGENTS.md`; all labels Vietnamese; keep dark-theme legibility (`text-[11px]`+, never `text-gray-500` on gray-900); no `any` types; no fabricated data.
- LOG.md append-only; REPORT.md SUBMITTED only (manager verification owns the manager verdict; never self-APPROVED).

## Acceptance criteria (binary)

- [ ] **AC1 — Canonical backend authority.** One canonical 7-kind taxonomy. ORM + migration constraint + Pydantic schemas + repository + API all accept exactly the seven kinds. Unknown client kind → stable 422 on create AND update. No silent coercion of unknown input to `other`. Legacy internal mapping of historical unknown → `other` records provenance/reason.
- [ ] **AC2 — Backward-compatible migration.** New reversible migration after `f6a7b8c9d0e1`; historical migrations untouched. Upgrade of an existing DB preserves ObjectRole IDs, revisions, statuses, source generations, occurrences, grouping lineage, correction lineage, artifact/media associations. Existing character/prop/other rows byte-identical. Downgrade→upgrade round-trip loses nothing.
- [ ] **AC3 — Public API.** Create/update/list/detail/filter support all seven kinds. CAS/revision/idempotency preserved. Cross-project/video/generation isolation preserved. Unknown kind → 422. `source_overlay` has a clear backend-owned removal-only policy (never a Character Pack candidate).
- [ ] **AC4 — Extraction and grouping.** Extraction contract can emit background, foreground, graphic, source_overlay. Production provider still fails closed when unavailable. Grouping never pairs different-kind roles. source_overlay never groups with graphic/background (nor anything else). Character/prop grouping metrics do not regress.
- [ ] **AC5 — Correction behavior.** Merge/split/reassign/edit/recompute preserve role kind or require explicit target kind. No loss of stable IDs, generation authority, correction lineage, media supersession, unaffected artifacts. Stale generation continues to fail closed.
- [ ] **AC6 — Frontend Object Gallery.** Vietnamese label/filter for all seven kinds: Nhân vật, Vật phẩm, Bối cảnh, Tiền cảnh, Nội dung/đồ họa, Lớp nguồn cần loại bỏ, Khác. Understandable badges. source_overlay shown removal-only; NOT shown as replacement/Character Pack candidate. Loading/empty/error/retry/stale states unchanged. No fabricated fallback. No overflow on desktop and 390px.
- [ ] **AC7 — Regression.** No regression in S05 import/analyze/lifecycle, S06 Character Library, S08 T01–T06, R01 queued-cancel/root safety, H01 frontend production authority, H02/C5 origin/upload/probe/preset security, protected MAIN.

## Required validation — exact order, fresh isolated roots (cache disabled)

1. Focused taxonomy/schema/repository/API tests.
2. Migration round-trip (copy an existing S08 fixture DB → upgrade → verify IDs/revisions/rows → downgrade → upgrade again → verify preservation). `MOTIONFORGE_DATABASE_URL` inline for the one-off run then UNSET + verified.
3. Extraction/grouping/correction focused tests.
4. Full S08 T01–T06 + R01 + H02 regression (the S08 focused set + golden + H02 security + R01 suites).
5. Relevant S05 regression. 6. Relevant S06 regression.
7. Frontend: `npx tsc --noEmit`, ESLint, `npm run build` (all exit 0).
8. Playwright desktop + 390px: seven filters/kinds visible, source_overlay removal-only, loading/empty/error/retry, no overflow, no fabricated data (new Run ID).
9. `python -m ruff check app tests` → clean.
10. `python -m mypy app` → clean.
11. `git diff --check` → exit 0 (pre-existing LF→CRLF advisories on earlier files only).
12. ONE fresh `scripts/quality-baseline.ps1` 7/7 baseline with a NEW Run ID.
13. Protected MAIN hashes + NO_LISTENERS on QA ports:
    - MAIN `channels.json` SHA-256 `DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555`
    - MAIN `data/motionforge.db` 311296 B SHA-256 `67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6`
    - SAM2.1 checkpoint 898083611 B SHA-256 `2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318`

## Allowed write scope

- Backend (only as needed directly for the taxonomy):
  - `app/persistence/models.py`
  - `app/schemas/object_intelligence.py`
  - `app/persistence/object_intelligence.py`
  - `app/api/routes/object_intelligence.py`
  - `app/services/object_extraction.py`
  - `app/services/object_grouping.py`
  - `app/services/object_correction.py`
  - exactly ONE new migration file in `migrations/versions/` after `f6a7b8c9d0e1`
- Frontend:
  - `frontend/src/lib/api.ts`
  - `frontend/src/components/object-gallery/`
  - `frontend/src/app/(app)/object-gallery/`
  - one focused S08-A01 Playwright config/spec under `frontend/`
- Tests:
  - focused schema/repository/API/migration tests
  - extraction/grouping/correction tests
  - isolated fixture additions directly needed for A01
- Evidence:
  - `docs/pm/sessions/S08-A01-source-locked-role-taxonomy/LOG.md` (append) and `REPORT.md`

If a file outside this allowlist is needed: STOP `BLOCKED`, state the exact
file, reason and acceptance criterion; do NOT expand scope yourself.

## Forbidden scope

- Do NOT modify MAIN (`C:\Users\Admin\MotionForge2D`) or any other worktree.
- Do NOT modify PRD / Master Plan / `docs/pm/ROADMAP.md` / `docs\pm\TARGET_PROFILE_2D_SOURCE_LOCKED.md` / any PM review or prior sprint/task history.
- Do NOT rewrite S08 history or touch `docs/pm/reviews/*`.
- Do NOT modify TASK.md / PM_REVIEW.md while running.
- Do NOT start S07 / S09 / S08-A02 or any later task.
- Do NOT commit/push/merge/deploy; no reset/restore/checkout/clean/stash.
- Do NOT use MAIN database/data for tests; no bare `TestClient(app)`.
- Do NOT weaken tests: no widening assertions, no skip/ignore to green an E2E, no copy changes only for tests.
- Do NOT run long work synchronously inside a request.
- Do NOT create a second production authority.

## Stop conditions (set REPORT.md = BLOCKED, ask ONE minimal question)

- Need to write a file outside allowlist (state exact file/reason/AC).
- Risk of data loss on migration or backward-compatibility break.
- Contradictory requirements / acceptance criteria impossible to verify.
- Unclear how to separate the canonical taxonomy from a second production authority.

## Required evidence (REPORT.md)

- Verbatim validation results per the order above (real command output + run IDs).
- Migration round-trip commands/results (upgrade → check → downgrade → upgrade).
- Playwright run with new Run ID + screenshots (desktop + 390px) incl. filter bar and source_overlay removal-only badge.
- Protected MAIN hashes + port listeners before/after.
- Changed-files list (within allowlist).
- Deviations / limitations / out-of-scope findings (if any) — recorded, not hidden.

## Finish

Fill `REPORT.md` with status **SUBMITTED**. Never self-APPROVE. No
TASK.md/PM_REVIEW.md change; no commit. Manager (Hermes) will verify
independently after you exit.

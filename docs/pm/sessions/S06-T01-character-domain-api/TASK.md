# S06-T01 - Character, Pack Version, Asset and pose-slot domain/API

**Status:** READY
**Epic:** E04 - Character Library and Cast Mapping
**Sprint:** S06 - Character Library
**Gate:** G2.5
**Depends on:** E01 exit (APPROVED)
**Parallel authorization:** PM-approved isolated worktree `codex/s06-t01`;
write scope must remain disjoint from active S03-T04 summary files.

## User outcome

A reusable workspace Character Library has durable backend authority. Users can
create/update/archive Characters, create versioned pose packs, attach managed
image artifacts to canonical pose slots, publish an immutable validated Pack
Version, and select a default version through an isolated v2 API. Legacy preset
files remain byte-identical and are not imported until S06-T02.

## Required reading

Read completely: PM protocol/roadmap; PRD Character Library/Core Pack/FR-CL;
persistence and managed-artifact contracts; Channel/Project/Video v2 API
patterns; durable-job owner contract; current models/migrations/bootstrap,
repositories/routes/deps/schemas/conftest; legacy preset layout only as read-only
context (never open/write asset bytes).

## Domain contract

- Add `Character`, `CharacterPackVersion`, and `CharacterAsset` durable tables
  via one forward, non-reversible Alembic migration from current head.
- Workspace owns Characters; Character owns versions; version owns assets. All
  references use RESTRICT; archive never cascades or hard-deletes.
- Character code is trimmed, non-empty, max 64 and active-only
  case-insensitively unique per workspace. Archived codes may be reused.
- Character statuses: `draft`, `generating`, `needs_review`, `ready`,
  `archived`. Character types: `character`, `prop`, `other`; symmetry:
  `symmetric`, `asymmetric`.
- Pack statuses: `draft`, `validating`, `ready`, `published`, `archived`.
  Version numbers are per-Character, positive, unique, allocated under the
  approved SQLite atomic-writer policy with a uniqueness backstop.
- Canonical Core pose slots are exactly `front`, `three_quarter`, `side`,
  `back`, `sitting`, `walking`. Optional slots are explicitly documented and
  validated; do not silently map legacy `standing` during this task.
- An asset references an existing same-workspace, `ready`, `image` Artifact;
  one pose slot per version. Asset bytes are never uploaded/written here.
- Publish requires all six Core slots, exact validation evidence, revision CAS,
  and precise missing/invalid errors. Once published, the version and every
  asset row are immutable. Later edits create a new version.
- Default version must belong to the same Character and not be archived;
  clearing is allowed. Generic PATCH cannot enter/leave archived.
- No DELETE route. Explicit Character/version archive is idempotent, stale-safe
  and preserves children. S07 adds reference-use checks; document that seam.
- DTOs expose no ORM objects, paths, raw internal blobs, or sensitive data.

## Isolated API

Use only `/api/v2/characters`:

- list/create/statuses/pose-slots/read/PATCH/archive Characters;
- list/create/read/archive/publish Pack Versions;
- attach and update pose assets on mutable versions;
- set/clear default version.

Use UUID converters, workspace-safe 404, stable 409 for CAS/conflict/immutable
state, 422 for validation, 201 only for creation, and Pydantic DTO boundaries.
Do not touch legacy preset/project routes.

## Acceptance criteria

1. Three durable tables, exact constraints/indexes/RESTRICT relationships, one
   forward non-reversible migration, and current-head data preservation.
2. Isolated v2 Character API implements the complete route/status/pose contract
   with no DELETE and no legacy behavior change.
3. Published Pack Version and assets are immutable; creating a later version
   preserves published rows byte-for-byte.
4. Publish gate enforces all six Core slots and valid assets with precise errors.
5. Artifact, workspace, Character/version ownership and default-version
   invariants are atomic and existence-safe.
6. Revision CAS, concurrent version allocation, uniqueness conflicts and
   idempotent archives have deterministic race evidence.
7. Upgrade preserves every pre-existing table/row and ORM metadata matches
   migration DDL; downgrade refuses.
8. `channels.json` and `presets/**` remain byte-identical; tests use temporary
   roots/DB/artifacts only.
9. Focused/combined/legacy regressions, Ruff, mypy, diff-check and fresh full
   quality baseline all pass 7/7.
10. API contract doc and REPORT include exact evidence and deliberate S06-T02/
    S07/E09 seams.

## Owned scope

New character repository/service/router/DTO module/tests/API doc/migration;
minimal model/export/app/deps/schema/conftest/bootstrap edits and this session's
LOG/REPORT. Do not edit S03-T04 files, frontend, presets, channels.json,
workers, legacy routes or product requirements. Do not commit; leave SUBMITTED.

# Task S06-T05: Pack Review, Publish & Immutable Version UX

- **Task ID:** `S06-T05`
- **Sprint:** `S06` (Durable Character Library)
- **Status:** `READY`
- **Owner:** Hermes (Review Worktree `s06-t01-review`)
- **Depends On:** `S06-T04` (Codex APPROVED)

## Outcome

Users can review a draft pack, understand authoritative validation problems,
explicitly publish a valid version with CAS safety, and clearly see that a
published version is immutable.

## Required behavior

- Review the existing previews for all six core pose slots.
- Show authoritative completeness/validation state from the approved read API.
- Offer publish only for an eligible non-published version; require explicit confirmation.
- Call `POST /api/v2/characters/versions/{version_id}/publish` with the current revision.
- On success, refetch character, versions, and validation state and show the immutable published/default state accurately.
- Surface 422 validation errors and 409 stale-revision conflicts honestly. A conflict refreshes current state; never silently retries the mutation.
- Published versions expose no asset mutation controls.

## Scope and safety

- Allowed writes: `frontend/src/app/(app)/characters/page.tsx`, `frontend/src/lib/api.ts`, focused frontend tests/config, and this task's LOG/REPORT.
- Do not implement file upload or invent an upload endpoint. Asset ingestion is outside this task.
- Do not change backend, schema, migration, validator, importer, `channels.json`, `data/`, roadmap, or unrelated UI.
- No commit, push, deploy, S07, reset, clean, deletion, or destructive cleanup.

## Validation

- Focused publish UX tests: confirmation, success/refetch, 422, 409, disabled states, immutable published state.
- TypeScript, ESLint, build, desktop and 390px visual QA.
- Fresh 7/7 quality baseline before SUBMITTED.
- End REPORT `SUBMITTED`, never self-approve.

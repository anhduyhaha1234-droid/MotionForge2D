# Task S06-T04: Character Library Browse/Search/Filter/Detail UI (Review Worktree)

- **Task ID:** `S06-T04`
- **Sprint:** `S06` (Durable Character Library)
- **Status:** `BLOCKED` (concrete API contract blocker — see REPORT.md)
- **Owner:** Hermes (Review Worktree `s06-t01-review`)
- **Depends on:** `S06-T03`, `S04-T01` (both APPROVED)

## Outcome
A real Character Library browse/search/filter/detail UI backed ONLY by the
durable character API produced in this worktree (`/api/v2/characters`).
Replace or repair any legacy/mock `/characters` behavior; no mock/fallback
character data.

## Required behavior
- List real characters with loading/empty/error/retry states.
- Search by code/name; filter by lifecycle/status.
- Detail view shows character identity, draft/published pack versions, the
  exact six required pose slots, per-slot artifact preview/status and
  validation problems.
- Clearly distinguish draft vs published/default immutable version.
- Responsive desktop/mobile; accessible Vietnamese labels/focus/ARIA.
- Broken/missing images render an honest placeholder, never a false ready state.
- Use the typed API client and TanStack Query conventions.

## Write scope
- `frontend/src/app/(app)/characters/page.tsx` (replace legacy preset page)
- `frontend/src/lib/api.ts` (add typed durable-character client methods)
- New frontend components under `frontend/src/components/` as needed
- Focused frontend tests and S06-T04 session evidence under
  `docs/pm/sessions/S06-T04-character-ui-review/`

## Forbidden scope
- Backend/schema/migration/validator/importer changes UNLESS a concrete API
  contract blocker is found; if found, STOP BLOCKED.
- `channels.json`, `data/`, roadmap, unrelated UI, user files.

## Validation
- Targeted frontend checks (tsc, eslint, build)
- Playwright/browser visual QA at desktop and 390px
- Fresh 7/7 quality baseline (`scripts/quality-baseline.ps1`)

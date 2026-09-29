# Start Prompt — Task S06-T04: Character Library UI (Review Worktree)

## Context
Execute roadmap task S06-T04 in the S06 review worktree after Codex approval
of S06-T01/T02/T03. Sole writer; do NOT commit/push or start T05.

The durable character API produced in this worktree is `/api/v2/characters`
(create/list/get/patch/archive, pack versions, asset attach, publish,
default-version). The legacy `/characters` page currently calls the OLD
preset-manager endpoint (`/api/projects/presets/characters`) and must be
replaced with a real library UI backed only by the durable API.

## Requirements
- Real browse/search/filter/detail UI; no mock/fallback character data.
- List: loading/empty/error/retry; search by code/name; filter status.
- Detail: identity, draft/published versions, six pose slots, per-slot
  artifact preview/status, validation problems; draft vs published distinct.
- Responsive, Vietnamese, accessible (focus/ARIA).
- Honest placeholder for broken/missing images — never false ready state.
- Typed API client + TanStack Query conventions.
- Session packet at `docs/pm/sessions/S06-T04-character-ui-review/`.
- REPORT ends SUBMITTED; exit without self-approval.
- If a concrete API contract blocker is found, STOP BLOCKED.

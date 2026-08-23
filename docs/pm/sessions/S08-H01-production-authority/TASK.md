# S08-H01 — Frontend Production Authority (correction finding F)

**Status:** PLANNED
**Depends on:** S08-T04 correction manager-verified (gallery consumes extraction/grouping/correction media contracts)
**Session type:** NEW session (authorized by Codex correction cycle) — model `ocg/deepseek-v4-flash` (user directive 2026-08-17)

## Outcome

The frontend never fabricates project/video data. Project/video identity comes
from the durable backend + URL; API failure renders honest error/retry/not-found;
navigation project-detail → processing → gallery preserves selection explicitly.
No S06 redesign.

## Finding F (Codex CHANGES_REQUESTED verbatim distilled)

1. Remove fabricated fallback project/video data — no fake rows when the API
   fails or is slow.
2. API failure → honest error/retry/not-found UI (no silent empty, no mock).
3. Project/video identity from durable backend + URL — never Zustand/
   localStorage as sole truth.
4. LegacyWorkspace may not fabricate projects/videos; must hydrate + validate
   durable IDs from backend truth.
5. Project detail → processing → gallery navigation preserves selection
   explicitly (explicit state passing, not ambient store).
6. Desktop + 390px tests for: API failure, retry, refresh, multi-video
   navigation.
7. No S06 redesign (Character Library stays as-is).

## Required behavior (extended)

- Every project/video/gallery read path resolves through real API routes with
  backend-authoritative IDs.
- Loading/error/empty/retry/not-found states are explicit and honest.
- 390px no horizontal overflow; a11y preserved.

## Allowed write scope

Frontend only: `frontend/src/**` (pages, components, lib/api.ts, hooks),
focused frontend/E2E test files, this packet LOG/REPORT. Minimal navigation
wiring if required.

## Forbidden

Backend API changes, S06 Character Library redesign, object-gallery contract
changes, production data, destructive Git, tests that mock the API instead of
exercising real error paths.

## Acceptance and validation

- No fabricated fallback data anywhere (grep for fabricated fallbacks).
- Real API error → honest error state; retry works; not-found on 404.
- URL/backend identity preserved across navigation (detail → processing →
  gallery) without localStorage/Zustand sole-truth.
- Desktop + 390px E2E for API failure/retry/refresh/multi-video navigation.
- tsc/eslint/build pass; S08 backend suites unaffected (T01–T05 combined
  regression); protected data unchanged.

## Stop

Stop at SUBMITTED after full validation; never self-approve.

# S08-T04 — Object Gallery and Confidence UX

**Status:** PLANNED  
**Depends on:** S08-T03 manager-verified

## Outcome

Users review candidates grouped by durable Object Role, understand confidence
and scene coverage, and explicitly confirm or curate them.

## Required behavior

- Use real T03 APIs and managed representative media; no production mock/fallback.
- Loading, empty, error, retry, partial-artifact, low-confidence and stale-state
  experiences are explicit.
- Display confidence reasons, provenance, scene coverage, thumbnails/masks and
  confirmed/suggested status honestly.
- Merge/split/confirm require clear selection and confirmation; low confidence is
  never auto-confirmed.
- Keyboard/focus/dialog semantics and responsive 390px layout with no horizontal
  overflow.
- Preserve existing Import/Analyze and Character Library navigation/UX.

## Allowed write scope

New focused Object Gallery page/components, `frontend/src/lib/api.ts`, minimal
navigation addition, focused frontend/E2E/config files and this packet LOG/REPORT.

## Forbidden

Backend contract redesign, mock production data, filesystem navigation, S05/S06
UI rewrite, protected data and destructive Git.

## Acceptance and validation

Real isolated-backend Playwright covers empty/loading/error/low confidence,
selection, merge/split/confirm, stale conflict and retry on desktop/390px.
Capture new screenshots. Run tsc, eslint, build, backend T01–T03 regressions,
existing S05/S06 interaction smoke and diff-check. Stop at SUBMITTED.


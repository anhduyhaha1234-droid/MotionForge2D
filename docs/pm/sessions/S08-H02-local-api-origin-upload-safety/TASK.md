# S08-H02 — Local API Origin / Upload / Media Safety (correction finding F follow-up)

**Status:** PLANNED
**Depends on:** S08-T04-C2 manager-verified (gallery consumes media contracts)
**Session type:** NEW session (authorized by Codex correction round C2) — model `ocg/deepseek-v4-flash` (user directive 2026-08-17)

## Outcome

Local API is safe by default: no wildcard CORS, configurable origin allowlist,
streaming uploads with hard byte limits, identifier validation before any
filesystem join, content-probed media type validation, temp staging cleanup and
atomic publish, bounded decoders.

## Finding (Codex CHANGES_REQUESTED round 2 verbatim distilled)

1. Remove wildcard CORS; use a configurable allowlist for the real frontend origins.
2. Do NOT enable credentials unless the product actually uses cookie credentials.
3. For requests WITH an Origin: state-changing requests from an untrusted
   Origin or Origin:null must get 403 BEFORE any side effect.
4. Trusted configured origins work normally.
5. CLI/native requests with NO Origin follow the defined local-app contract.
6. OPTIONS/untrusted must NOT receive a valid ACAO.
7. Video/replacement uploads must be streaming with a hard byte limit.
8. Validate project/object identifiers before every filesystem join; enforce
   managed-root containment.
9. Validate media/image type by content probe, not just filename/MIME.
10. Temp staging must be cleaned up on error; only atomic publish after validation.
11. Decoder must have a timeout and sane output/dimension/memory limits.
12. Tests: trusted/untrusted origin, zero-side-effect, oversized upload,
    malformed media, traversal identifiers, cleanup.

## Allowed write scope

Backend API/security/middleware: `app/api/**`, `app/config.py` (origin allowlist
config), upload/media validation services, focused tests, this packet LOG/REPORT.
Minimal frontend origin config if required for the allowlist.

## Forbidden

S05/S06 behavior weakening, S08 task contracts (extraction/grouping/correction/
gallery) behavior changes, production data, destructive Git, TASK.md/PM_REVIEW.md.

## Acceptance and validation

- No wildcard CORS; allowlist configurable; credentials off unless used.
- Untrusted Origin/Origin:null state-changing → 403 with ZERO side effect.
- Upload streaming + hard byte limit; traversal identifiers → 4xx, no join.
- Media type by content probe; staging cleanup on error; atomic publish only
  after validation; decoder timeout + limits.
- Tests: trusted/untrusted origin, zero-side-effect, oversized upload,
  malformed media, traversal identifier, cleanup.
- Full S08 backend regression + ruff/mypy/diff-check; protected data unchanged.

## Stop

Stop at SUBMITTED after full validation; never self-approve.

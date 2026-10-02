# S06-R02 - Character artifact read API repair

**Status:** IN_PROGRESS
**Base:** `master` at `a43b20d` + S06-R01 character-domain port (uncommitted worktree state)
**Scope owner:** this session is the sole writer for character backend/API scope.

## Objective

The durable Character API exposes enough safe, truthful read data for Character
Library pose previews and draft validation without exposing the managed
filesystem.

S06-T04 is BLOCKED until this repair is approved. Do NOT implement frontend, do
NOT start T04/T05, do NOT commit or push.

## Required changes

1. Extend `AssetData` with read-only artifact state, mime type, sha256, size and
   a server-produced content URL (or equivalent typed link). Do not expose
   absolute paths. Avoid returning `relative_path` unless strictly required
   internally; the frontend must use the content endpoint.
2. Add a workspace/version/asset-scoped GET content endpoint:
   `/api/v2/characters/{character_id}/versions/{version_id}/assets/{asset_id}/content`.
   It must verify ownership relationships, resolve only through `ManagedRoot`
   containment, serve only a ready existing decodable image with an approved
   image MIME type, and return `FileResponse`/stream with the correct content
   type. Missing, foreign-workspace, non-ready, non-image, corrupt, path-escape
   and symlink-escape cases fail closed (404/409/422 according to existing API
   conventions) without revealing filesystem paths.
3. Add a read-only draft validation endpoint or typed validation field computed
   by the existing validator. It returns required-slot completeness and
   actionable validation errors without publishing or mutating the pack. It must
   use the same authoritative validation logic as publish, not duplicate weaker
   checks.
4. Published immutability and existing publish rejection behavior remain
   unchanged. No schema/migration should be necessary; if one appears necessary,
   stop BLOCKED.
5. Add focused API/repository tests: real PNG success bytes/MIME; DTO metadata;
   missing file; staging artifact; wrong MIME; corrupt image; checksum/size
   mismatch where relevant; cross-character/version/workspace access;
   traversal/symlink containment; draft validation parity with publish; no
   absolute path disclosure.

## Allowed write scope

- `app/schemas/characters.py`
- `app/api/routes/durable_characters.py`
- `app/api/deps.py` only if needed
- character repository/validator only for a shared read adapter
- focused tests
- this session packet (`docs/pm/sessions/S06-R02-character-artifact-read-api/`)

## Forbidden scope

- frontend, channels.json, data/, roadmap and unrelated files
- commits, pushes, approval or starting S06-T04

Finish with REPORT `SUBMITTED` and exit without approval.

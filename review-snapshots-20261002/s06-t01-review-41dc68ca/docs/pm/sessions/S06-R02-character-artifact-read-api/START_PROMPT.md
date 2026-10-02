# Start Prompt for Hermes - S06-R02

Implement exactly TASK.md in this isolated worktree. You are the sole writer for
character backend/API scope. S06-T04 is BLOCKED until this repair is approved.

Create the session packet under
`docs/pm/sessions/S06-R02-character-artifact-read-api/` BEFORE implementation,
then:

1. Extend `AssetData` (app/schemas/characters.py) with read-only artifact
   state, mime type, sha256, size and a server-produced content URL — never
   absolute paths, never `relative_path` in the DTO.
2. Add `GET /api/v2/characters/{character_id}/versions/{version_id}/assets/{asset_id}/content`
   that verifies ownership, resolves only through `ManagedRoot`, serves only a
   ready existing decodable image with an approved MIME type via `FileResponse`,
   and fails closed (404/409/422 per existing API conventions) without revealing
   filesystem paths.
3. Add a read-only draft validation endpoint that uses the SAME authoritative
   `validate_character_pack` as publish (no weaker duplicate checks) and returns
   slot completeness + actionable errors without mutating the pack.
4. Keep published immutability and publish rejection behavior unchanged. No
   schema/migration; if one appears necessary, stop BLOCKED.
5. Add focused tests: real PNG bytes/MIME; DTO metadata; missing file; staging
   artifact; wrong MIME; corrupt image; checksum/size mismatch; cross-character/
   version/workspace access; traversal/symlink containment; draft validation
   parity with publish; no absolute path disclosure.

Run focused tests, ruff, mypy, `git diff --check` and a fresh 7/7 baseline.
Write REPORT = SUBMITTED and exit WITHOUT approval or starting S06-T04.

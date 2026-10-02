# S06-R02 - Character Artifact Read API Repair Report

**Status:** SUBMITTED

## 1. Outcome

The durable Character API now exposes safe, truthful read data for Character
Library pose previews and draft validation without exposing the managed
filesystem. S06-T04 remains BLOCKED pending review; this session did NOT start
it, did NOT touch the frontend, and created NO commits.

## 2. What changed (allowed scope only)

| File | Change |
|---|---|
| `app/schemas/characters.py` | `AssetData` extended with read-only `artifact_state`, `mime_type`, `sha256`, `size_bytes`, `content_url`; typed-link helper `asset_content_url()`; new `PackVersionValidationData` DTO; `PackVersionData` now emits a typed content URL per asset. No `relative_path` and no absolute path ever leaves the DTO layer. |
| `app/persistence/characters.py` | Shared read adapters: `get_pack_version_for_character` (ownership-verified read), `resolve_asset_content` (ManagedRoot containment + ready/decodable image + approved MIME + size/checksum gate; fail-closed 404/409/422), `validate_pack_version` (read-only, runs the SAME authoritative `validate_character_pack` as publish, zero writes). New errors `AssetNotFoundError`/`AssetNotReadyError`/`AssetContentError`, constant `APPROVED_IMAGE_MIME_TYPES` (png/jpeg/webp/gif — matches the S06-T02 importer's registered MIME set). |
| `app/api/routes/durable_characters.py` | `GET /api/v2/characters/{character_id}/versions/{version_id}/assets/{asset_id}/content` → `FileResponse` with the registered content type; `GET /api/v2/characters/versions/{version_id}/validation` → typed read-only validation; attach_asset response now carries the content URL. |
| `tests/test_character_read_api.py` | New focused suite (21 tests). |

No changes to `app/api/deps.py` (not needed), no schema/migration changes
(requirement 4 satisfied — the only migration/model diffs in the worktree are
pre-existing S06-R01 staged work), no frontend, no roadmap, no unrelated files.

## 3. Content endpoint contract (fail closed, no path disclosure)

- **Ownership:** version must belong to the character and the asset to the
  version, all inside the workspace — else 404 (foreign rows are
  indistinguishable from missing).
- **Resolution:** the managed file is resolved ONLY through
  `ManagedRoot.resolve()`; `..` traversal and symlink/junction escapes raise
  `ManagedPathError` → 422 with a generic message (the failing path is never
  echoed).
- **Serving gate:** artifact state `ready` (else 409), file exists on disk
  (else 404), MIME in `APPROVED_IMAGE_MIME_TYPES` (else 422), decodes as an
  image via Pillow (else 422), registered size and SHA-256 match the on-disk
  file (else 422).

## 4. Draft validation endpoint contract

`GET /api/v2/characters/versions/{version_id}/validation` returns
`PackVersionValidationData` (`status`, `complete`, `missing_slots`, `errors`)
computed by the exact validator the publish gate uses
(`validate_character_pack`). It performs no writes and never mutates the pack;
a 404 is returned for missing/foreign versions. Parity is proven by tests that
assert the validation error list equals the publish-rejection error list for
the same pack.

## 5. Test coverage (tests/test_character_read_api.py, 21 tests)

- real PNG success: bytes round-trip equal + `content-type: image/png`
- DTO metadata: `artifact_state`, `mime_type`, `sha256`, `size_bytes`,
  `content_url` present; `relative_path` and managed-root strings absent
- content URLs emitted by attach + list-versions responses
- missing file → 404; staging artifact → 409; wrong MIME → 422; corrupt image
  → 422; checksum mismatch → 422; size mismatch → 422
- cross-character / cross-version / cross-workspace / unknown-asset → 404
- traversal (`..`) and symlink-escape → 422 with no path leak
- draft validation parity with publish: missing slots, valid pack, corrupt
  asset (identical error lists), unknown version → 404
- no absolute path disclosure across character/version/validation responses

## 6. Quality results (fresh runs in this worktree)

| Check | Result |
|---|---|
| Focused character suite (read_api + domain + publish_rejection + validator + importer) | 90/90 PASS |
| `ruff check app tests` | clean |
| `mypy app` (strict) | clean (67 files) |
| `git diff --check` | clean (ROADMAP LF warning is a pre-existing autocrlf notice; ROADMAP untouched by this session) |
| Fresh 7/7 quality baseline (run `20260804-184228`) | **PASS** — Gate 2 Python tests 162s, Gate 3 ruff, Gate 4 mypy, Gates 5-7 frontend typecheck/lint/build all PASS |

## 7. Exit state

- REPORT = SUBMITTED. No commits, no pushes, no approval granted.
- S06-T04 not started; frontend, channels.json, data/, roadmap untouched.

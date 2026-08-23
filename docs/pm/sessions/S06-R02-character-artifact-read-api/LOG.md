# S06-R02 - Execution Log

- 2026-08-04: Session packet created (TASK.md, START_PROMPT.md) BEFORE implementation.
- 2026-08-04: Inspected existing character scope: schemas, durable_characters router,
  CharacterRepository, character_validator, ManagedRoot (app/persistence/artifacts.py),
  Artifact ORM model, publish rejection + validator tests, conftest fixtures, and the
  S06-R01 packet format.
- 2026-08-04: Baseline: focused tests test_character_domain + test_publish_rejection +
  test_character_validator = 41 passed before any change.
- 2026-08-04: Confirmed symlinks are creatable on this Windows host (needed for the
  symlink-escape containment test).
- 2026-08-04: Implemented S06-R02 in allowed scope:
  - `app/schemas/characters.py` — AssetData extended with read-only
    `artifact_state`, `mime_type`, `sha256`, `size_bytes`, `content_url`
    (no relative_path / no absolute paths); `asset_content_url()` typed-link
    helper; `PackVersionValidationData` response DTO; PackVersionData now
    emits a typed content URL per asset.
  - `app/persistence/characters.py` — shared read adapters:
    `get_pack_version_for_character` (ownership-verified version read),
    `resolve_asset_content` (ManagedRoot containment + ready/decodable image +
    approved MIME + size/checksum gate, fail-closed 404/409/422),
    `validate_pack_version` (read-only, runs the SAME authoritative
    `validate_character_pack` as publish, zero writes); new error types
    AssetNotFoundError/AssetNotReadyError/AssetContentError and
    `APPROVED_IMAGE_MIME_TYPES` (png/jpeg/webp/gif, matching the S06-T02
    importer's registered MIME types).
  - `app/api/routes/durable_characters.py` — GET
    `/api/v2/characters/{character_id}/versions/{version_id}/assets/{asset_id}/content`
    (FileResponse, content-type from registered MIME; 404 missing/foreign,
    409 non-ready, 422 MIME/corrupt/checksum/size/escape) and GET
    `/api/v2/characters/versions/{version_id}/validation` (typed read-only
    validation); attach_asset response now carries the content URL.
  - No schema/migration changes (Artifact columns already carry
    state/mime/sha256/size; DTO and read paths only).
- 2026-08-04: New focused suite `tests/test_character_read_api.py` (21 tests):
  real PNG bytes/MIME; DTO metadata; attach/list content URLs; missing file 404;
  staging 409; wrong MIME 422; corrupt image 422; checksum 422; size 422;
  cross-character/version/workspace/unknown-asset 404; traversal escape 422;
  symlink escape 422; validation parity with publish (missing slots, valid pack,
  corrupt asset); validation unknown version 404; no absolute path disclosure.
- 2026-08-04: Verification:
  - Focused character suite (5 files incl. importer) = 90 passed.
  - ruff check app tests = clean.
  - mypy app = clean (67 source files).
  - git diff --check = clean (ROADMAP.md LF warning is a pre-existing autocrlf
    notice, not a whitespace error; ROADMAP itself untouched by this session).
- 2026-08-04: Fresh 7/7 quality baseline (run `20260804-184228`) = **PASS**
  (Gate 1 preflight PASS; Gate 2 Python tests PASS 162s; Gate 3 ruff PASS;
  Gate 4 mypy PASS; Gate 5 tsc PASS; Gate 6 eslint PASS; Gate 7 next build
  PASS).  Re-ran focused character suite after all code edits: 90/90 PASS.
- 2026-08-04: REPORT.md written as SUBMITTED. No commits created; S06-T04 not
  started; frontend/channels.json/data/roadmap untouched.

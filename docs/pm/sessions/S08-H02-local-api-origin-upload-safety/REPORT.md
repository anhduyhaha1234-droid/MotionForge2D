# S08-H02 — Local API Origin / Upload / Media Safety: Implementation Report

**Status:** SUBMITTED (worker evidence below; manager/Codex sprint-exit review owns approval — never self-approve)
**Hermes session:** 20260818_020323_151164
**Model:** ocg/deepseek-v4-flash (user directive 2026-08-17 — flash + reasoning max, no pro)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Task:** CORRECTION ROUND C2 (Codex CHANGES_REQUESTED on sprint exit — security finding **H02** LOCAL API ORIGIN / UPLOAD / MEDIA SAFETY). Newly authorized Task ID, NEW worker session.

Hard worktree guard verified before any write:
- `pwd` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`
- `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`
- `git branch --show-current` = `codex/s08-integration`
- `git status --short` snapshot = 161 entries at session start (dirty baseline INTENTIONAL — never reset/checkout/restore/clean/stash).

---

# CORRECTION C2 — Implementation

## What changed (files)

| File | Change | Acceptance |
|---|---|---|
| `app/api/security.py` (NEW) | `OriginGuardMiddleware` (configurable allowlist, read live from `deps.get_config().cors_origins`; no wildcard; credentials off; untrusted/`null` Origin state-changing => 403 before route; untrusted preflight => 403 with no ACAO; no-Origin native/CLI => local-app contract; trusted origin gets ACAO) + `validate_path_identifier` (rejects `..`, separators, control bytes, >200 chars) | 1,2,3,4,5,6,8 |
| `app/api/app.py` | Removed `CORSMiddleware(allow_origins=["*"], allow_credentials=True)`; installed `OriginGuardMiddleware` after routers (outermost). | 1,2,3,6 |
| `app/config.py` | Added `cors_origins` (from `MOTIONFORGE_CORS_ORIGINS`, default = real frontend origins: localhost/127.0.0.1 8888, 3000, 5173 — never `*`), `cors_allow_credentials` (False), `max_upload_bytes` (2 GiB), `max_image_upload_bytes` (64 MiB), `max_image_dimension` (16384), `decode_timeout_seconds` (60). | 1,2,7,11 |
| `app/api/routes/projects.py` | `upload_video` + `upload_replacement` hardened: identifier validated BEFORE any join, `_assert_contained` resolves project dir under the projects root, `_stream_staged` streams in 64 KiB chunks with a hard byte ceiling, content probe on staged bytes, staging file removed in `finally` on every error path, `os.replace`/tmp+replace atomic publish only after validation. `_safe_upload_filename` neutralizes `..`/separators/control bytes in stored names. | 7,8,9,10 |
| `app/services/media_validation.py` (NEW) | `probe_image` (byte-level PNG/JPEG/WebP magic + Pillow lazy header + dimension cap — never trusts filename/MIME) raising `MediaValidationError`; `sniff_video_container` (MP4/MOV `ftyp`, WebM/Matroska EBML, Ogg, AVI) for the video upload boundary. | 9,11 |
| `app/services/video_probe.py` | Post-probe dimension sanity check (width/height ≤ `max_image_dimension`); kept the bounded ffprobe timeout. | 11 |
| `app/services/object_extraction.py` | Decoded-frame dimension guard in `_decode_frame` (refuses absurd decoded sizes before the provider consumes them). | 11 |
| `app/workflow/scene_chunking_service.py` | Added bounded `_decode_timeout()` to the two previously unbounded ffmpeg `subprocess.run` decode calls (scene slicing, audio extraction). | 11 |
| `tests/test_s08_h02_security.py` (NEW) | 22 focused H02 tests mapped 1:1 to AC1-AC11/AC12. | 12 |
| `tests/test_api.py` | `test_upload_video` fixture updated from 100 null bytes to a real minimal MP4 (`ftypisom` box) — the endpoint now content-probes, so a fake payload is no longer valid input. Legacy contract (200 + "ok" for a real video, 404 for missing project) unchanged. | 9 |

## Per-acceptance evidence

1. **No wildcard CORS** — `CORSMiddleware` deleted; allowlist only. `test_config_allowlist_never_wildcard_no_credentials` asserts `"*" not in cfg.cors_origins`.
2. **Credentials off** — `allow_credentials=False`; trusted responses carry ACAO but never `Access-Control-Allow-Credentials` (`test_trusted_origin_works_and_gets_acao`, `test_trusted_preflight_gets_acao_no_credentials`).
3. **Untrusted/null Origin state-changing => 403 before side effect** — `test_untrusted_origin_state_changing_403_zero_side_effect` (POST `/api/projects` with evil Origin => 403, then GET => `[]` — the route never ran), `test_origin_null_state_changing_403`, `test_untrusted_origin_put_patch_delete_403` (POST/PUT/PATCH/DELETE all 403).
4. **Trusted configured origins work normally** — `test_trusted_origin_works_and_gets_acao` (201 + `ACAO: http://trusted.example`).
5. **No-Origin local-app contract** — `test_no_origin_local_contract_works`; the whole existing suite (TestClient sends no Origin) passes unchanged.
6. **OPTIONS/untrusted => no valid ACAO** — `test_untrusted_preflight_403_no_acao` (403, no ACAO); trusted preflight gets 200 + ACAO.
7. **Streaming with hard byte limit** — `_stream_staged` + `test_oversized_video_rejected_413_and_cleaned`, `test_oversized_replacement_image_rejected` (413, no staging left).
8. **Identifier validation before every join + containment** — `validate_path_identifier` unit tests (`../`, `..\..\etc`, `a/b`, `.`, `""`, `\x00`, 201 chars all raise) + endpoint tests `test_traversal_project_identifier_upload_rejected` / `test_traversal_identifiers_replacement_rejected` (422, nothing written) + `_assert_contained` resolve guard.
9. **Content probe, not filename/MIME** — `test_malformed_video_rejected_415_and_cleaned` (null-byte ".mp4" => 415), `test_malformed_replacement_image_rejected_415_and_cleaned` (text bytes ".png" => 415, no dest written), `test_decompression_bomb_image_rejected_415` (crafted huge-IHDR PNG => 415); real PNG/MP4 uploads succeed and are served byte-exact.
10. **Staging cleaned on error; atomic publish after validation** — every test asserts `_staging_leftovers(project_id) == []` after 413/415; publish uses `os.replace` / tmp+replace only after probe passes.
11. **Decoder timeout + dimension/memory limits** — `probe_image(max_dimension=...)` (unit `test_probe_image_rejects_oversized_dimensions`), `video_probe` dimension caps, `scene_chunking` ffmpeg timeouts, `_decode_frame` decoded-size guard.
12. **Tests** — 22 focused tests in `tests/test_s08_h02_security.py` covering trusted/untrusted origin, zero-side-effect, oversized upload, malformed media, traversal identifiers, cleanup.

Notes:
- `Origin:null` is treated as untrusted (never in the allowlist).
- httpx/TestClient normalizes a bare `../` URL segment client-side, so the endpoint-level traversal tests use a `..`-bearing identifier (`a..b`) that survives URL parsing; the full `../` / `..\` forms are covered by the `validate_path_identifier` unit tests and the `_assert_contained` resolve guard.
- `test_integration.py` is not run (S08 standing rule — SAM2 segfault).

---

# VALIDATION (exact commands + verbatim results; fresh isolated roots, `-p no:cacheprovider`, shallow basetemps under `C:/Users/Admin/AppData/Local/Temp/s08h02-*`, env `MOTIONFORGE_DATABASE_URL` unset)

1. **Focused H02 (+ legacy test_api):**
   `python -m pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02-04`
   → `47 passed, 83 warnings in 23.96s`
2. **T01-T05 combined regression:**
   `python -m pytest tests/test_object_intelligence_domain.py tests/test_object_grouping.py tests/test_object_extraction.py tests/test_object_extraction_api.py tests/test_object_correction.py tests/test_object_correction_api.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02-t01t05`
   → `184 passed, 339 warnings in 97.78s (0:01:37)`
3. **R01 suites:**
   `python -m pytest tests/test_s08_r01_queued_cancel_lifecycle.py tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02-r01`
   → `18 passed, 18 warnings in 5.97s`
4. **S05 41-suite (shallow):**
   `python -m pytest tests/test_s05_orchestrator_binding.py tests/test_s05_atomic_cancel.py tests/test_s05_production_wiring.py tests/test_s05_lifecycle.py tests/test_s05_chain_progression.py tests/test_s05_orchestration.py tests/test_s05_golden_integration.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02-s05`
   → `41 passed, 81 warnings in 94.14s`
   **S02 durable:**
   `python -m pytest tests/test_durable_job_persistence.py tests/test_persistence_bootstrap.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08h02-s02`
   → `87 passed, 162 warnings in 41.53s`
5. **Migration round-trip (isolated subshell `MOTIONFORGE_DATABASE_URL`, unset after):**
   `(MOTIONFORGE_DATABASE_URL="sqlite:///C:/Users/Admin/AppData/Local/Temp/s08h02-mig/mig-roundtrip.db" python -m alembic upgrade head && ... current -> f6a7b8c9d0e1 (head); downgrade f5a6b7c8d9e0; re-upgrade head -> f6a7b8c9d0e1 (head))`
   → `f6a7b8c9d0e1 (head)` both after initial upgrade and after re-upgrade; downgrade lands on `f5a6b7c8d9e0`.
   Env check after subshell: `MOTIONFORGE_DATABASE_URL=[]` (unset).
6. **Ruff / mypy / diff / status:**
   - `python -m ruff check app/config.py app/api/security.py app/api/app.py app/api/routes/projects.py app/services/media_validation.py app/services/video_probe.py app/services/object_extraction.py app/workflow/scene_chunking_service.py tests/test_s08_h02_security.py tests/test_api.py` → `All checks passed!`
   - `python -m mypy app` → `Success: no issues found in 88 source files`
   - `git diff --check` → exit 0 (only pre-existing LF→CRLF advisories on files from earlier sprint tasks; no whitespace errors)
   - final `git status --short` = 167 entries (baseline 161 + 3 new H02 files + new `app/services/object_extraction.py` edit + `app/services/video_probe.py`/`app/workflow/scene_chunking_service.py` working-copy mtimes — all inside TASK.md allowed scope; no reset/checkout/restore/clean/stash performed).
7. **Protected-data comparison (read-only, never touched):**
   - MAIN `channels.json` SHA-256 = `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` (matches expected `DD7AAE…555`)
   - MAIN `data/motionforge.db` = 311296 bytes (matches expected)
   - MAIN `models_checkpoints/sam2.1_hiera_large.pt` = 898083611 bytes, SHA-256 `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (matches expected), mtime 2026-07-29 untouched.

**Bonus regression evidence (replacement-upload path):**
- `python -m pytest tests/test_delete_and_autosegment.py -q -p no:cacheprovider --basetemp=.../s08h02-delauto` → `17 passed` (incl. `test_replacement_image_served_after_upload`)
- `python -m pytest tests/test_preset_manager.py -q -p no:cacheprovider --basetemp=.../s08h02-preset` → `14 passed`
- Real app boot smoke (isolated QA root, real lifespan): `/health` 200; untrusted Origin POST => 403; trusted Origin (`http://localhost:8888`) GET => 200 with `ACAO` and no `Access-Control-Allow-Credentials`.

**Scope discipline (mtime window, session 02:03–now):** only `app/api/security.py`(new), `app/api/app.py`, `app/api/routes/projects.py`, `app/config.py`, `app/services/media_validation.py`(new), `app/services/video_probe.py`, `app/services/object_extraction.py`, `app/workflow/scene_chunking_service.py`, `tests/test_s08_h02_security.py`(new), `tests/test_api.py` were written by this worker. All prior sprint modifications (frontend, models.py, deps.py, durable_worker, etc.) were left untouched.

---

**Status: SUBMITTED.** No self-approval, no PM_REVIEW.md / TASK.md modification, no commit/push/merge/reset. The S08 sprint remains `SPRINT_SUBMITTED`.


---

# CORRECTION C1 (Codex CHANGES_REQUESTED on H02 security blockers) — recovery-appended

**Status:** SUBMITTED (worker + recovery evidence below; manager/Codex sprint-exit review owns approval — never self-approve)
**Session:** resume 20260818_020323_151164 (forced-stop recovered by manager-authored RECOVERY PROMPT)
**Recovery note:** the earlier C1 worker was force-stopped before appending this REPORT section; this section is appended by the S08-H02-C1-recovery writer and supersedes the missing section. LOG.md has a matching RECOVERY entry.

## Root cause closed

1. **Codex repro:** `upload_video` stored the client multipart filename verbatim into `proj_dir`, so `filename=project.json` overwrote the project file (500 + corrupted GET). Closed by server-owned storage name `source_<uuid>.mp4` + rejection of hostile/reserved filenames before any write.
2. **Recovery audit (this round):** after publication of the new source, `pwf.set_video` ran outside rollback scope — a metadata write failure left the just-published `source_<uuid>.mp4` as an orphan and prior state unrolled-back. Fixed by wrapping `set_video` and removing the just-published source file on failure (re-raise), matching the existing replacement-image rollback style.

## Final implementation (all files in declared scope)

- `app/api/routes/projects.py` — `upload_video`: identifier validated before any join; `_reject_hostile_upload_filename` (reserved names case-insensitive, `/`, `\\`, `..`, absolute, `PurePath` basename) → 422 before any write; container-magic prefilter + REAL bounded ffprobe (`probe_video` — arg list, timeout, bounded output) requiring a decodable video stream; duration cap; SERVER-OWNED storage `source_<uuid>.mp4` published atomically only after validation; `set_video` wrapped so a metadata failure removes the just-published source (no orphan) and re-raises — previous source stays present and SELECTED; staging removed on all error paths. `upload_replacement`: FULL `probe_image` (magic prefilter + Pillow `load()` full decode + reopen, dimension AND total-pixel caps), canonical extension/Content-Type per verified format (`replacement.<png|jpg|webp>`), atomic publish, metadata-update rollback, sibling-format cleanup. `delete_project`: validates + `_assert_contained` before `rmtree`. `get_replacement_image`: serves only files resolving under the project root + explicit media_type (`.webp` → `image/webp`, no octet-stream). `replacement-settings`: rejects absolute / `..` `asset_path` and `frame_sequence_dir`. All raw `proj_dir/"objects"/object_id` joins → `pwf.object_dir(...)`.
- `app/api/security.py` — `OriginGuardMiddleware` (configurable allowlist, no wildcard, credentials off, untrusted/`null` state-changing → 403 before route, untrusted preflight → 403 no ACAO, no-Origin local-app contract) + `validate_path_identifier`.
- `app/api/app.py` — removed wildcard `CORSMiddleware`; installed origin guard; global `InvalidPathIdentifierError → 422` handler (no 500 for hostile ids).
- `app/config.py` — `cors_origins`, `cors_allow_credentials`, `max_upload_bytes`, `max_image_upload_bytes`, `max_image_dimension`, `max_image_pixels`, `max_video_duration_seconds`, `decode_timeout_seconds`.
- `app/services/media_validation.py` — `probe_image` (full decode + caps, canonical MIME/ext), `sniff_video_container` (prefilter only), `is_reserved_entry_name` (case-insensitive).
- `app/services/video_probe.py`, `app/services/object_extraction.py`, `app/workflow/scene_chunking_service.py` — decoder timeouts + dimension/memory caps.
- `app/workflow/project_workflow.py` — centralized safe resolver: `_project_dir` validates; new `object_dir(project_id, object_id)` validates both + `_assert_project_contained`; `set_video` validates the (server-owned) filename.
- `app/workflow/replacement_service.py` — uses the resolver; validates object_id/filename.
- `tests/test_s08_h02_security.py` — 37 tests (rewritten/expanded): 15 C1 contracts + new `test_video_metadata_update_failure_rolls_back_file_and_state`; real ffmpeg MP4 fixture (no fake bytes).
- `tests/test_api.py` — `test_upload_video` uploads a real generated MP4; asserts server-owned filename.

## Per-acceptance evidence (15 contracts, re-proven by the suite)

1. `filename=project.json` cannot overwrite project.json → `test_filename_project_json_does_not_overwrite` (422; project.json byte-identical; GET project 200; no staging/orphan source).
2. Reserved names case-insensitive on Windows → `test_reserved_names_case_insensitive_never_overwrite` (PROJECT.JSON / Project.Json / project.JsOn / objects → 422; only `project.json` exists).
3. Client traversal/backslash filename cannot escape → `test_filename_traversal_and_backslash_never_escape` (422; drive-qualified filename safe either way; nothing escapes root).
4. Fake ftyp/EBML/Ogg/AVI header without a real stream → 415 → `test_fake_ftyp_only_rejected_415_no_state_change`, `test_malformed_video_rejected_415_and_cleaned`.
5. Valid video passes real bounded ffprobe → `test_valid_video_upload_ok_server_owned_name` (200; server-owned `source_<uuid>.mp4`; original filename metadata only).
6. Truncated PNG/JPEG/WebP with valid magic → 415 → `test_truncated_png_jpeg_webp_with_valid_magic_rejected_415`.
7. Valid PNG/JPEG/WebP correct extension + Content-Type → `test_valid_images_served_with_correct_bytes_and_mime` (image/png, image/jpeg, image/webp; byte-exact; `replacement.<ext>`).
8. Dimension + total-pixel caps → `test_oversized_dimensions_rejected_415`, `test_oversized_total_pixels_rejected_415`, `test_decompression_bomb_image_rejected_415`.
9. Replacement metadata failure rolls back files/state → `test_metadata_update_failure_rolls_back_file_and_state` (500; old bytes restored; metadata unchanged; no temps).
10. Publish-temp cleanup under injected failure → `test_publish_temp_cleanup_on_injected_failure` (500; no staging/publish-temp; no partial file).
11. Absolute/`..` replacement asset path rejected → `test_replacement_settings_reject_absolute_and_dotdot_asset_path` (all 422).
12. Replacement GET cannot read outside project root → `test_replacement_get_cannot_read_sentinel_outside_project_root` (404; sentinel unreachable).
13. Delete traversal cannot delete outside projects root → `test_delete_traversal_does_not_delete_outside_projects_root` (422; sentinel intact).
14. Invalid identifiers → stable 4xx, never 500 → traversal tests + isolated smoke (mask/delete `a..b` → 422).
15. Trusted/untrusted Origin behavior → `test_trusted_origin_works_and_gets_acao`, `test_untrusted_origin_state_changing_403_zero_side_effect`, `test_origin_null_state_changing_403`, `test_untrusted_preflight_403_no_acao`, `test_trusted_preflight_gets_acao_no_credentials`, `test_no_origin_local_contract_works`.

**NEW (recovery, mandate):** `test_video_metadata_update_failure_rolls_back_file_and_state` — set_video failure after a successful publish → response 500; new `source_<uuid>.mp4` REMOVED (no orphan); only previous source file remains; project.json byte-identical; previous source bytes intact; GET project 200 with previous `source_video`; no staging/publish-temp orphan.

## Tests and exact results (fresh isolated roots, `-p no:cacheprovider`, shallow basetemps `C:/Users/Admin/AppData/Local/Temp/s08h02c1rec-*`, `MOTIONFORGE_DATABASE_URL` unset)

1. `pytest tests/test_s08_h02_security.py::test_video_metadata_update_failure_rolls_back_file_and_state -q -p no:cacheprovider` → **1 passed** (2.92s).
2. `pytest tests/test_s08_h02_security.py tests/test_api.py -q -p no:cacheprovider` → **62 passed** (30.28s).
3. T01-T05 combined (6 files) → **184 passed** (98.93s).
4. R01 suites → **18 passed** (6.10s).
5. S05 41-suite → **41 passed** (93.67s).
6. S02 durable → **87 passed** (40.51s).
7. `ruff check` (12 changed files) → **All checks passed!**
8. `mypy app` → **Success: no issues found in 88 source files**.
9. `git diff --check` → exit 0 (only pre-existing LF→CRLF advisories); final `git status --short` = **169** (baseline; no reset/clean).
10. Migration round-trip: upgrade head `f6a7b8c9d0e1` → downgrade `f5a6b7c8d9e0` → re-upgrade `f6a7b8c9d0e1`; rows preserved 2/2; `superseded_by_id` restored; env unset after (`MOTIONFORGE_DATABASE_URL=[]`).
11. Isolated app smoke (real lifespan, QA root): health 200; untrusted Origin POST 403; trusted GET 200 + ACAO, no Access-Control-Allow-Credentials; trusted preflight 200 + ACAO; hostile ids → 422 (never 500).
12. Process/port cleanup: `netstat -ano` → NO_LISTENERS on 3012/8888/8000/3000/5173; no worktree-tied uvicorn/next-dev/node processes.
13. Protected MAIN comparison (read-only): channels.json SHA `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`; data/motionforge.db 311296 B SHA `67d5c7736042b9d4e4b7249e611bea3e85124df0317fafe6aaf32405ff79f2e6`; SAM2.1 898083611 B SHA `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` (mtime 2026-07-29 untouched).

## Deviations / limitations

- httpx/TestClient normalizes a bare `../` URL segment and (for drive-qualified filenames) may reduce a multipart filename to its basename before our guard sees it; the `..`/separator/reserved-name guard + server-owned storage still guarantee no escape (covered by unit tests + containment checks).
- A list-scoped `probe_image` reads the (byte-capped) staged image into memory for full verification; bounded by `max_image_upload_bytes` + `max_image_dimension`/`max_image_pixels`.
- Existing valid prior sources are never deleted on a NEW successful upload (server-owned names are append-only); project.json selects the latest.

## Recovery session lineage

C1 code/tests: session 20260818_020323_151164 (worker). Force-stopped mid REPORT append. Recovery: S08-H02-C1-recovery, resume 20260818_020323_151164, manager-authored RECOVERY_PROMPT. All validations above re-run fresh by the recovery writer; LOG.md contains the matching RECOVERY entry.

**Status: SUBMITTED.** No self-approval, no TASK.md / PM_REVIEW.md change, no commit/push/merge/reset/clean/stash. Sprint remains SPRINT_SUBMITTED.

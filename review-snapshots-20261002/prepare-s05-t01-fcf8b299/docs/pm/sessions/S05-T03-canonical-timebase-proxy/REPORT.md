# S05-T03 - Implementation Report (continuation)

**Status:** SUBMITTED
**Hermes session:** 20260805_092948_d404dd (continuation of 20260804_200632_d327bf — prior provider session ended with HTTP 502 at ~210k tokens; existing implementation preserved and continued, not recreated)
**Started:** 2026-08-05 09:29 +07:00
**Submitted:** 2026-08-05 +07:00
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`

## Outcome delivered

S05-T03 implements the canonical rational timebase (`app/services/timebase.py`, new) and the bounded editing-proxy `GENERATE_PROXY` durable job (`app/services/video_proxy.py`, new) per `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`, consuming the approved S05-T02 managed `ready` source artifact. A deterministic exact-rational mapping (never float drift) converts frame index ↔ canonical timestamp ↔ duration for both accepted CFR (`r_frame_rate`) and accepted VFR (`avg_frame_rate`) inputs with explicit floor/round-half-up/ceil rounding, monotonicity, boundary/duration rules and fail-closed stable codes. The proxy is generated through the durable worker (generate→verify→publish phases, checkpoint-resumable), FFmpeg discovery only via `ffmpeg_utils`, list arguments only, bounded execution/cancellation, and published as a managed `ready` `video` artifact with mandatory SHA-256 + size, path containment, atomic publication and an `artifact_owner` link (purpose `proxy`). Retry/restart reuses valid completed work, creates no duplicate rows/files and cleans only staging owned by the failed attempt; the immutable source artifact is preserved; no absolute managed path leaks into durable data. **No new schema** — the write surface is exactly the existing `artifact` and `artifact_owner` tables; the canonical timebase and proxy profile are persisted only in Job checkpoint/manifest JSON. No API routes, no frontend, no scene detection, no import-UI change, no `app/services/video_import.py` modification.

## Implementation summary (existing code, verified this session)

1. **Canonical timebase** (`app/services/timebase.py`, 461 lines) — frozen `CanonicalTimebase(fps_num, fps_den, classification, duration_seconds, nb_frames)` built from `Fraction`; rejects `fps_num<=0`/`fps_den<=0`/unknown classification with stable codes (`INVALID_TIMEBASE`, `UNSUPPORTED_CLASSIFICATION`) and Vietnamese actions. `frame_to_time(frame)` = exact `Fraction(frame*fps_den, fps_num)`; `time_to_frame(t, rounding=floor|round_half_up|ceil)` explicit; `nearest_frame` alias; `clamp_frame` playhead clamp; `frame_count_for_duration(d)` = nearest-half-up with min 1 for positive d, 0 for zero, `INVALID_DURATION` for negative; `duration_for_frames(n)` = exact `n/fps`, `INVALID_FRAME_INDEX` for negative. `from_probe` selects `r_frame_rate` (CFR) / `avg_frame_rate` (VFR) from the S05-T02 probe payload; `to_json`/`from_json` persist the schema-versioned exact rational payload (checkpoint-durable). `exact_seconds` converts ffprobe decimals to exact `Fraction` (no float on the conversion path).
2. **Submit** (`submit_proxy`) — validates the ownership chain (`video_import._validate_ownership`, S05-T02 helper, read-only reuse) + source artifact (`kind='video'`, `state='ready'`, owner link purpose `source`, sha256 recorded) **before** Job creation; creates the durable `GENERATE_PROXY` Job with the owner-scoped key `GENERATE_PROXY:video_item:<video_item_id>:<source_sha256>:<generation>`; completed duplicate → same Job reused (`reused=True`); active duplicate → `IdempotencyKeyInUse`; the request path never runs FFmpeg and never hashes the source.
3. **Source phase** — re-validates ownership + source at run time; resolves the managed file read-only from the artifact relative path; bounded probe (30s, list-args, JSON, discovery via `ffmpeg_utils`); checkpointed (absolute `file_path` stripped); re-run reuses valid source evidence.
4. **Timebase phase** — `CanonicalTimebase.from_probe`; the schema-versioned payload becomes durable in the checkpoint (this is where the canonical timebase is persisted, per task constraint — JSON payload, no DDL).
5. **Generate phase** — `ProxyProfile` (bounded knobs, all validated → `INVALID_PROXY_PROFILE`), FFmpeg with **list arguments only** (`_build_ffmpeg_command`: `-r num/den -fps_mode cfr` resample onto the canonical grid, scale to profile box, libx264/yuv420p/CRF, low-bitrate AAC when the source has audio, `-t` bounded to the source duration), discovery only via `ffmpeg_utils.find_ffmpeg`, bounded by `profile.timeout_seconds` (default 120); subprocess polled against `ctx.is_cancelled()` (≤0.5s): cancel → terminate + remove staging partial + `CANCELLED`; budget overrun → terminate + `PROXY_TIMEOUT` (transient); non-zero exit → `PROXY_FFMPEG_FAILED`. **This session fixed a real defect here:** the FFmpeg output directory `staging/<job_id>/<step_code>/` was never created (the worker creates step staging dirs lazily via `ctx.staging_dir()`, which this handler does not call), so every first-run encode failed with "No such file or directory" (`PROXY_FFMPEG_FAILED`); the handler now creates `staged_path.parent` explicitly (verified by the full success suite).
6. **Verify phase** — bounded ffprobe of the generated proxy: must decode (positive duration/width/height), recorded fps must equal the canonical grid **exactly**, duration within `max(0.05s, source×0.05)` tolerance; failure removes the staged file and raises `PROXY_VALIDATION_FAILED`.
7. **Publish phase** — atomic `os.replace` staging → final managed path `artifacts/<workspace_id>/video/<job_id>/<step_code>/proxy.mp4`, then **one transaction**: deterministic-id upsert of the `artifact` row (`kind='video'`, `state='ready'`, sha256, size, `mime_type='video/mp4'`) + `artifact_owner` link (`owner_type='video_item'`, purpose `proxy`). A DB failure removes the just-published file **only when this attempt created it** (`created_final` guard, S05-T02 correction #4 pattern); replay finds the ready row/file and reuses (committed files never deleted).
8. **Completion gate** — `register_generate_proxy_handler` registers an `output_validator` that re-verifies the published file on disk (exists + sha256 + size match the handler evidence); Job `completed` never precedes verified publication.
9. **Cancellation/failure cleanup** — every phase observes `ctx.is_cancelled()` and removes its own staging/partial files; `_cleanup_staging_partials` garbage-collects staging owned by this Job **and its predecessor** on re-run.
10. **Path containment** — every managed path through `ManagedRoot`; `ManagedPathError` → stable `PATH_CONTAINMENT`; source opened read-only, never mutated/deleted.
11. **Registration** — `app/workflow/job_service.py` registers `register_generate_proxy_handler` on every JobService-owned worker (minimal change, mirrors the ANALYZE_MEDIA wiring).
12. **Minimal durable-worker support (backward compatible)** — `PROXY_TIMEOUT` added to `TRANSIENT_ERROR_CODES` in `app/workflow/durable_worker.py` so the bounded-encode budget exhaustion is auto-retried (exact precedent: S05-T02 added `PROBE_TIMEOUT` to the same set and was APPROVED). AC5 requires "timeout → `PROXY_TIMEOUT` transient (auto-retry then `RETRIES_EXHAUSTED`)"; without this classification a timeout would be permanent and unretryable. No other worker behavior changed.

**Stable error codes used (contract §4 + S05-T02 taxonomy reuse):** `INVALID_TIMEBASE`, `UNSUPPORTED_CLASSIFICATION`, `INVALID_FRAME_INDEX`, `INVALID_DURATION` (timebase); `SOURCE_ARTIFACT_NOT_FOUND`, `SOURCE_NOT_READY`, `SOURCE_OWNER_MISMATCH`, `SOURCE_FILE_MISSING`, `FFMPEG_BINARY_NOT_FOUND`, `PROXY_FFMPEG_FAILED`, `PROXY_TIMEOUT` (transient), `PROXY_VALIDATION_FAILED`, `INVALID_PROXY_PROFILE` (proxy); reused import codes `VIDEO_ITEM_NOT_FOUND`, `PROJECT_NOT_FOUND`, `OWNERSHIP_MISMATCH`, `PUBLICATION_FAILED`, `CANCELLED`, `PATH_CONTAINMENT`, `INSUFFICIENT_DISK`, `INPUT_UNREADABLE`. Every code carries severity/location/reason and a Vietnamese suggested action — never a bare "failed".

## Acceptance criteria evidence

| AC | Status | Evidence |
|---|---|---|
| AC1 exact-rational mapping + explicit rounding + monotonicity + boundary + fail-closed codes | PASS | `tests/test_timebase.py` (29 tests): exact `frame_to_time` (incl. 24000/1001 NTSC), floor/round_half_up/ceil incl. exact boundaries and halves, non-decreasing frames for all three modes, strictly increasing times, frame 0 → 0, `frame_count_for_duration` half-up min-1 / 0 / negative, `duration_for_frames` exact, `INVALID_TIMEBASE` (zero/negative/non-integer), `UNSUPPORTED_CLASSIFICATION` (unknown classification + unknown persisted schema version), `INVALID_FRAME_INDEX`, `INVALID_DURATION`, `from_probe` CFR→r_frame_rate / VFR→avg_frame_rate / VFR zero-avg fail-closed, JSON round-trip, no-float-path assertions. |
| AC2 service + handler + registration + ffmpeg_utils-only discovery + list args + bounded/cancellable | PASS | `app/services/video_proxy.py` (1,326 lines): `submit_proxy`, `generate_proxy_handler` (source→timebase→generate→verify→publish, checkpoint resume), `_build_ffmpeg_command` (list only), `_run_ffmpeg` (bounded poll + cancel + timeout), `register_generate_proxy_handler` wired in `app/workflow/job_service.py`; verified by `test_ffmpeg_failure_stable_code_and_no_orphans` (real non-zero ffmpeg exit), `test_timeout_transient_auto_retry_completes`, `test_timeout_always_fails_retries_exhausted`, `test_cancellation_drains_and_cleans_staging`. |
| AC3 success path: completed, one ready video artifact (sha256/size), proxy owner link, contained path, decodes, source unchanged | PASS | `test_proxy_success_cfr_publishes_ready_artifact`: job `completed`; exactly one `ready` `video/mp4` artifact; `sha256 == SHA-256(file)`, `size_bytes == stat().st_size`; owner link (`video_item`/`proxy`); path under `artifacts/<ws>/video/<job>/proxy/` and relative; ffprobe of the final file: positive duration/width/height + `r_frame_rate == 30/1`; original file and managed source bytes unchanged. |
| AC4 owner-scoped idempotency | PASS | `test_duplicate_submit_active_raises_idempotency_key_in_use`; `test_duplicate_submit_completed_reuses_same_job` (same Job, `reused=True`, exactly one effect set); `test_same_source_bytes_two_video_items_two_independent_proxies` (same bytes → 2 VideoItems → 2 Jobs/artifacts/files, 2 proxy owner links, distinct keys); `test_owner_scoped_key_shape`. |
| AC5 failure/rollback/cancellation | PASS | `test_ffmpeg_failure_stable_code_and_no_orphans` (`PROXY_FFMPEG_FAILED`, zero proxy rows/files, staging clean); `test_proxy_timeout_is_transient` (`PROXY_TIMEOUT` ∈ `TRANSIENT_ERROR_CODES`, envelope class `transient`); `test_timeout_transient_auto_retry_completes` (first-attempt timeout auto-retried → completed, exactly one artifact, ≥2 attempts); `test_timeout_always_fails_retries_exhausted` (≥3 attempts → `RETRIES_EXHAUSTED`, no artifacts/leftovers); `test_cancellation_drains_and_cleans_staging` (terminal `cancelled`, no proxy rows, no final files, staging clean); `test_db_rollback_removes_only_this_attempts_files` (publication transaction failure → `PUBLICATION_FAILED`, no proxy rows, no orphan final files, no `.staging` leftovers); `test_publish_file_checksum_mismatch_keeps_existing_final`. |
| AC6 replay/restart | PASS | `test_restart_successor_no_duplicate_artifacts` (successor with same key/generation completes; exactly one artifact/file; staging clean; 2 Job rows but ONE effect set); `test_successor_cleans_crash_leftover_staging` (hard-crash partial garbage-collected by the successor); `test_replay_publication_failure_keeps_committed_artifact` (forced replay + injected DB failure → `PUBLICATION_FAILED`; committed row survives, committed file byte-identical, staging clean). |
| AC7 path containment + source immutability | PASS | `test_symlink_escape_rejected_and_nothing_written_outside` (proxy job dir symlink → `PATH_CONTAINMENT`, outside dir empty, staging clean); `test_source_artifact_never_mutated_or_deleted` (managed source bytes/size/sha unchanged, import job still `completed`); `test_proxy_checkpoint_has_no_absolute_managed_path` (checkpoint JSON contains no managed-root path; source evidence `relative_path` relative; probe `file_path` stripped to None; manifest `source_relative_path` relative). |
| AC8 no schema/migration/API/frontend changes; `video_import.py` untouched | PASS | No migration added; `git status --short` shows only the allowed files (see Files changed); `app/services/video_import.py` not modified (verified by `git status`); S05-T02 30-test suite passes unchanged. |
| AC9 real synthetic CFR and VFR fixtures | PASS | `test_proxy_success_cfr_publishes_ready_artifact` (CFR 30fps lavfi testsrc+sine); `test_proxy_vfr_resamples_onto_avg_frame_rate_grid` (real VFR fixture = concat of a 30fps and a 25fps MP4 segment via `-c copy`; ffprobe shows `r_frame_rate=30/1`, `avg_frame_rate=33/1` → probe classifies VFR; canonical grid = exact `avg_frame_rate`; proxy completes and its decoded `r_frame_rate` equals the canonical grid exactly; sha/size/file parity asserted; both fixtures under `tmp_path` only). |
| AC10 all validations | PASS | See "Tests and validation" below. |

## Files changed

- `app/services/timebase.py` (new, ~461 lines — canonical rational timebase; existed from the original session, verified).
- `app/services/video_proxy.py` (new, ~1,330 lines — GENERATE_PROXY service + handler; existed from the original session, verified; **one defect fixed this session**: staging output directory now created before the FFmpeg run).
- `app/workflow/job_service.py` (modified — register the GENERATE_PROXY handler; minimal, mirrors the ANALYZE_MEDIA wiring).
- `app/workflow/durable_worker.py` (modified — `PROXY_TIMEOUT` added to `TRANSIENT_ERROR_CODES`, backward compatible; exact S05-T02 `PROBE_TIMEOUT` precedent; pre-existing S05-T02 changes to this file preserved).
- `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md` (new — architecture note; existed from the original session, verified).
- `tests/test_timebase.py` (new — 29 tests; **created this session**).
- `tests/test_video_proxy.py` (new — 26 tests; **created this session**).
- `docs/pm/sessions/S05-T03-canonical-timebase-proxy/LOG.md` (appended this session), `REPORT.md` (this file).

Untouched (verified by `git status`): `app/services/video_import.py` (S05-T02, read-only reuse of helpers), PRD/MP/ROADMAP (PM-owned activation diff preserved), migrations, `pyproject.toml`/lockfiles, frontend source, database files, `channels.json`, `data/`, user data, the primary worktree `C:\Users\Admin\MotionForge2D`, S06 worktrees.

## Architecture/schema/API impact

- **Schema/migration:** none. The existing `artifact` + `artifact_owner` tables are the complete write surface; the canonical timebase and proxy profile live only in durable Job JSON (checkpoint/manifest).
- **API:** none. `submit_proxy` is a service-level entry point; no HTTP route, no frontend, no import-UI change.
- **Jobs/artifacts:** new job class `GENERATE_PROXY` (documented in the architecture note) with one sync step (`proxy`) and an `output_validator` completion gate; artifact purpose `proxy` added to the owner-link space.
- **Error classification:** `PROXY_TIMEOUT` is now transient (contract §6.1); structured exception `details` preserved in envelopes (S05-T02 behavior).

## Tests and validation

| Command | Result | Notes |
|---|---|---|
| `python -m pytest -q tests/test_timebase.py tests/test_video_proxy.py -p no:cacheprovider` | PASS | **55 passed** (29 timebase + 26 proxy) in 14.6–16.9s. Timebase: exact conversions, rounding modes, monotonicity, boundaries, fail-closed codes, CFR/VFR probe policy, JSON round-trip. Proxy: CFR + real VFR success (sha/size/file parity, decode, canonical-rate resample), owner-scoped idempotency (active/duplicate/two-owners), submit-time ownership/source rejections (incl. cross-project/cross-workspace/missing/not-ready/not-linked), run-time ownership revalidation, ffmpeg failure, timeout transient auto-retry + retries-exhausted, cancellation drain, DB rollback cleanup, successor restart, crash-leftover cleanup, replay publication failure keeps committed artifact, symlink containment, source immutability, no absolute path in durable data. |
| `python -m pytest -q tests/test_video_import.py -p no:cacheprovider` | PASS | **30 passed** in 11.7s — S05-T02 regression suite (owner-safe idempotency, optional SHA, ownership, replay cleanup) unaffected. |
| `python -m pytest -q tests/test_durable_worker.py tests/test_durable_job_api.py tests/test_durable_job_persistence.py tests/test_job_reconciliation.py tests/test_managed_artifacts.py tests/test_ffmpeg_discovery.py -p no:cacheprovider` | PASS | **184 passed, 2 skipped** in 43.5s — durable worker/job/persistence/reconciliation/artifact/ffmpeg regressions unaffected. |
| `python -m ruff check app tests` | PASS | `All checks passed!` (one auto-fix applied to import sorting in the new test file). |
| `python -m mypy app` | PASS | `Success: no issues found in 64 source files`. |
| `git diff --check` | PASS | exit 0 (LF→CRLF advisory only on `docs/pm/ROADMAP.md`). |
| `git status --short` | PASS | Only allowed files (see Files changed). |
| `scripts/quality-baseline.ps1` (fresh run) | PASS | **OVERALL: PASS (exit 0)**, run `20260805-095242` — 7/7 gates: env, python tests (**660 passed, 19 skipped, 7 deselected** in 147.4s — includes the 55 new S05-T03 tests), ruff, mypy, tsc, eslint, build. Summary: `output/quality-baseline/20260805-095242/summary.json`. |

## Manual UX/media verification

Not applicable — no UI/media rendering code in this task. Media behavior is verified end-to-end by the synthetic-fixture tests (real ffprobe + real lavfi/concatenated MP4 files, `tmp_path` only) and the artifact/file assertions (SHA-256, size, decode, canonical-rate resample, containment).

## Migration and rollback

None — no schema or migration change. The proxy writes through the existing `artifact`/`artifact_owner` tables; a failed/replayed/cancelled proxy leaves no orphan rows or files (verified by AC5/AC6 tests). The committed artifact file is never deleted by later failed attempts (`created_final` guard).

## Deviations from task

None. The only app-source change beyond the allowed list is the minimal, backward-compatible `PROXY_TIMEOUT` transient classification in `app/workflow/durable_worker.py` — the exact precedent S05-T02 used for `PROBE_TIMEOUT` and required by AC5 ("timeout → `PROXY_TIMEOUT` transient (auto-retry then `RETRIES_EXHAUSTED`)"). Documented above and in LOG.md.

## Out-of-scope findings

- The pre-existing untracked fixture trees (`tests/fixtures/legacy_import/...`), the S05-T01 packet/contract files, the S05-T02 packet, and the PM-owned ROADMAP activation diff are present in the worktree and were not modified by this session.
- The original session's implementation had one latent defect (missing staging dir creation before FFmpeg), fixed and verified this session; no other implementation defect was found by the 55-test suite.

## Known limitations/risks

- Proxy encoding is CPU libx264 (bounded profile); GPU encoding is out of scope by design.
- The VFR fixture (30fps+25fps concat) is genuinely VFR on this ffmpeg build (`r=30/1`, `avg=33/1`); the test asserts the canonical grid from the actual probe values, so it remains valid across builds that classify the same fixture VFR (it skips if a build produces a non-VFR concat).
- `submit_proxy` raises the approved S05-T02 `VideoImportError` class (same stable codes) for ownership-chain rejections — the stable error code is the contract.
- No HTTP import/proxy route yet (S05-T04/T05 owns the UI); `submit_proxy` is the service-level entry point.

## Recommended PM decision

`PENDING` — awaiting PM review per protocol (no self-approval; no commit; no roadmap edits; no next-task packet creation). Upon approval, S05-T04 (scene detection) may start.

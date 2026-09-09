# S12-T06B LOG — C2 W7 (F11 positive acceptance, rows C26-C29)

Resumed same owner session (20260907_224836_1bfbfe), S12-C2 W7.
Baseline: `5e6e0fa` (canonical post W1-W6 + upstream repairs). Branch
`codex/s12/s12-t06b-0907a`, porcelain 0 at start.
RULES_LOADED: `C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md`
SHA-256 `c9b068b2195461b1f867a5ec95714cea3ab09881757f5607094574d15dda428f`,
277 lines, read in full before any action.

## Writes this correction (allowlist only)

1. `tests/s12/s12-t06b/c27_stage1_worker.py` (new) — real owned worker
   subprocess: claim -> render ALL planned chunks (committed+verified) ->
   READY flag -> parks for the parent kill. Same job, same DB.
2. `tests/s12/s12-t06b/test_c26_normal_product.py` (new)
   - Real normal path: `submit_export_job` -> `_s12_export_handler`
     (F01 real publisher caller) -> run + job + candidate.
   - 3 MEASURED cases: 1920x1080->3840x2160 (F03 scale+pad), native
     3840x2160 control, 4:3 1440x1080 letterbox; all assert real
     candidate dims/frames/timing, zero `.partial`, and the F11
     fail-closed publication (run `failed`, retryable, no waive).
3. `tests/s12/s12-t06b/test_c27_same_job_fresh_process.py` (new)
   - ONE normal job: stage-1 subprocess renders + commits verified chunk
     progress; exact pid KILLED (tasklist-verified); production
     reconciler releases the expired lease (real fence); fresh pid
     re-claims (new fence token) and REUSES every verified chunk
     (mtime-identical, no re-render); candidate exact 30 frames; run
     failed (retryable); no `.partial` final.
4. `tests/s12/s12-t06b/test_c28_audio_mapping.py` (new)
   - Content mapping: real sine 440Hz source vs 880Hz control; decoded
     PCM dominant tone follows the mapped source.
   - Remux vs transcode EXPLICIT: `-c:v copy` (h264) + `-c:a aac`
     (transcode) verified by codec probes.
   - Start/end drift: 4s audio into 3s video pins output end to 3.0s
     (no tail bleed); 2s audio (short >0.5s) fails closed with
     `StitchError` (no loop/pad). Playable: ffprobe + wav decode.
5. `tests/s12/s12-t06b/conftest.py` — added `build_media_silent`,
   `decode_wav_pcm`, `audio_dominant_freq`; `db_factory` now yields
   `(factory, manifest_id, db_path)` (consumers updated).
6. `docs/pm/sessions/S12-T06B/EXTERNAL_ACCEPTANCE.md` (C29) + LOG/REPORT
   updates.

## Live verification (real output, isolated temp DBs)

- Full suite: `pytest tests/s12/s12-t06b/ -q -p no:cacheprovider`
  -> **18 passed, 1 skipped in 30.02s** (skip = clean-machine NOT_RUN).
- C26: 3/3 passed (real 4K renders + fail-closed publication).
- C27: kill pid (tasklist-verified), reconciler `expired=1 resumable`,
  chunk mtimes unchanged (reuse), candidate 30 frames, run failed.
- C28: 3/3 passed — 440Hz mapping (output ~440Hz, 880Hz control
  rejected by >200Hz), end pin 3.00s, short-audio StitchError.
- C29: EXTERNAL_ACCEPTANCE.md written; clean Windows NOT_RUN.

## REVERIFY on base 9a93475 (T03C findfix + T04A psnr delta)

- Full T06B suite: **20 passed, 1 skipped in 39.07s**; regression T03C
  **37 passed**, T04A **73 passed**.
- C26/C27 fail-closed assertions STILL hold (candidates real, chunks
  reused, zero `.partial`).
- New proof `test_c26_f11_remaining_blocker_proof`: positive publish
  STILL blocked on the fixed base, exactly because:
  - `publication._expectation_for` does NOT set `frame_match_mode`
    (defaults to `exact`) -> re-encoded/upscaled candidates ALWAYS fail
    `frame_order` (content digest mismatch at frame 0);
  - with `frame_match_mode="psnr"` the validator fails closed:
    "psnr mode requires documented frame_psnr_min_db (per profile)"
    and publication wires neither the mode nor the documented tolerance.
  Identity-copy candidates would be the only exact-matchable ones.
- New tamper proof `test_c26_tamper_reorder_and_audio_still_fail_under_psnr`:
  real reversed-concat candidate FAILs `frame_order` under PSNR
  (frame_psnr_min_db set) — tamper remains rejected.

## REVERIFY-2 on base 6352b1b (T03C WIRE-PSNR) — POSITIVE CLOSURE

- Full T06B suite: **20 passed, 1 skipped in 93.92s**; ruff F clean.
- C26 native 4K / same-raster re-encode: **publish COMPLETED** (psnr
  30dB PASS, measured 59-71dB), public artifact + sha256 sidecar, GET
  result/media served with playable decode (20 frames) — positive
  closure on the normal product path (F11-T06B-01 resolved by WIRE-PSNR
  for same-raster renders).
- C27 same-job kill/restart: **positive PASS** — stage-1 subprocess pid
  killed (tasklist-verified), production reconciler released expired
  lease, fresh pid re-claimed, verified chunks reused (mtime-identical),
  handler PUBLISHED (run completed).
- C28 audio: PASS (unchanged).
- Tamper under PSNR: reversed-concat candidate still FAILs frame_order —
  no tolerance leak.
- **F11-T06B-02 (new, owner T04A/T03C)**: cross-raster PSNR still
  blocked — `probe_frame_psnr` decodes reference at its ORIGINAL raster
  (no scale/pad to candidate raster), so upscale 1080p->4K and 4:3
  letterbox candidates fail frame_order (reference stream shorter than
  one candidate frame). Normal render pipeline only publishes when the
  candidate raster equals the source raster. Verifier does not fix.

## REVERIFY-4 FINAL on base 68f40b3 (T04A pipe-fix: ref -> temp raw file)

- Full T06B suite: **20 passed, 1 skipped in 90.94s**; ruff F clean.
- Native-4K positive closure PASS, C27 kill/restart PASS, C28 PASS,
  tamper reorder FAILs under PSNR (no tolerance leak).
- **F11-T06B-02 UPDATE (owner T04A/T03C) — STILL blocked**: the pipe-fix
  routed the REFERENCE decode to a temp raw FILE, but the CANDIDATE side
  keeps `_open_raw_pipe(candidate)` — a 4K candidate still pushes
  ~12.4MB/frame through the Windows pipe and drops frames:
  `probe_frame_psnr(candidate_4k, reference_1080p, 3840, 2160)` still
  returns **7 of 30** frames, PSNR ~7.6dB (same-raster 59-71dB).
  Upscale 1080p->4K and 4:3-letterbox candidates still fail frame_order
  and cannot publish. Fix direction: decode the CANDIDATE to a temp raw
  file as well (mirror the reference path). Verifier does not fix.
- C26 FINAL status: native-4K positive; upscale/letterbox fail-closed
  (F11-T06B-02 open). No case removal, no waive.

## REVERIFY-3 on base 3439545 (T04A cross-raster PSNR fit+pad) — vòng cuối

- Full T06B suite: **20 passed, 1 skipped in 89.35s**; ruff F clean.
- Native-4K same-raster positive closure: STILL PASS (publish completed +
  result/media 200 + playable).
- C27 kill/restart positive: PASS. C28 audio: PASS. Tamper under PSNR:
  reorder FAILs (no tolerance leak).
- **F11-T06B-02 UPDATE (owner T04A/T03C) — cross-raster PSNR STILL
  blocked on Windows**: T04A fit+pad landed, but on this machine
  `probe_frame_psnr(candidate_4k, reference_1080p, 3840, 2160)` returns
  **7 of 30 frames** with PSNR ~7.5dB (vs 59-71dB same-raster) -> the
  upscale and 4:3-letterbox candidates still fail frame_order and cannot
  publish.  Standalone evidence: the same fit+pad reference pipe decoded
  alone yields 30 frames; the failing shape is the TWO concurrent raw
  pipes each pushing ~12.4MB/frame — Windows pipe-read is not robust at
  that frame size (`src vs cand` at 1920x1080 = 3.1MB/frame works: 30).
  Test-side assertions (fail-closed) kept; verifier does not fix.
- C26 FULL status: native-4K positive; upscale/letterbox still
  fail-closed (F11-T06B-02 open).

## Findings routed (verifier does NOT fix production)

- F11-T06B-01 (owner T03C/T04A): `publication._expectation_for` gives
  the source-locked validator NO server-owned authority -> every real
  job candidate is rejected (provenance FAIL, frame_order NOT_MEASURED)
  and no job can publish positive on this base. C26/C27 assert the
  fail-closed behaviour with real render + real reuse; positive publish
  remains blocked until the owner wires authority.
- C28-F01 (owner T03C/T04A): `_expectation_for` sets
  `SourceReference.audio=None` -> audio-present candidates rejected as
  absent; assembly-layer audio proven independently (C28).
- Readiness gate consumed as external S11 domain, mocked at publication
  boundary exactly like T03C (never seeded into QC).

## Gates

`ruff check --select F tests/s12/s12-t06b/` All checks passed (fixed
F401 unused + F811 redefinitions); `py_compile` OK; `git diff --check`
clean; porcelain allowlist only at commit time.
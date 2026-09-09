# S12-T06B LOG — Independent acceptance + clean-machine/hardware report (W7)

Task: S12-T06B | Worktree: `s12-s12-t06b-0907a` | Branch: `codex/s12/s12-t06b-0907a`
Baseline: `1c9cd07` (clean, porcelain 0 — verified before code) | Date: 2026-09-07

RULES_LOADED: `C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md`
SHA-256 `c9b068b2195461b1f867a5ec95714cea3ab09881757f5607094574d15dda428f`,
277 lines, read in full (sections 1-12) before any action.

Role: verifier only. READ-ONLY production — zero production files touched
(verifier không sửa production; defect phát hiện thì ghi repro + route exact
owner, không tự fix).

## Writes (allowlist only)

1. `tests/s12/s12-t06b/__init__.py` (1 line) — package marker.
2. `tests/s12/s12-t06b/conftest.py` (455 lines)
   - Isolated fixtures: fresh migrated temp DB per test (`s12t06b_*`,
     never MAIN/dev), `seed_lineage` workspace/project/video/checkpoint/lock,
     `db_factory` fixture, tmp_path workdirs.
   - Real media builders: `build_source_1080p` (1920x1080 h264 + sine AAC),
     `build_native_4k` (3840x2160 h264 + sine AAC), `upscale_to_4k`
     (lanczos scale=3840:2160, returns method label
     `lanczos-ffmpeg-scale-x4`).
   - Real listeners: `probe_dims`/`probe_has_audio` (ffprobe JSON),
     `decode_audio_to_wav` (real pcm decode, returns wav bytes).
   - `gpu_info`/`cpu_info` best-effort probes (missing = NOT_RUN, never
     faked); `require_clean_machine` fixture skips unless
     `S12_T06B_CLEAN_MACHINE=1`.
   - `make_request`/`ok_ctx` pure preflight builders.
   - Markers registered: `measured` / `simulated` / `not_run`.
3. `tests/s12/s12-t06b/test_scenario_f_4k.py` (192 lines)
   - F1: real 1080p->2160p upscale, ffprobe out 3840x2160, DAR in==out
     (aspect preserve, no silent stretch/crop), verdict `upscale_4k` +
     labeled `upscale_method`, aspect check pass, 30 decoded frames,
     validator resolution/frame_count/av_policy PASS, real wav decode.
   - F2: real native 3840x2160 encode, verdict `native_4k`,
     `upscale_method` None, 20 decoded frames, validator PASS, wav decode.
   - F3: provenance decides (upscale vs native contexts); F-OBS-01
     documented: dims>=3840x2160 without provenance flag still classifies
     `native_4k` via dims-only fallback branch in
     `app/services/s12_export/preflight.py::classify_source_kind`
     -> owner T01 (route writer, verifier không fix).
   - F4: 4:3->16:9 drift + `fail_closed` -> `S12_EXPORT_ASPECT_MISMATCH`,
     eligible False; `letterbox` -> aspect pass.
4. `tests/s12/s12-t06b/test_scenario_g_resume.py` (320 lines)
   - G1: spawn owned ffmpeg (60->3600s duration so it survives to kill),
     `proc.kill()` pid-scoped, `wait` + `tasklist` verify dead
     (measured pid printed).
   - G2: full render (3 chunks, 320x180, 30 frames, audio_source=src) ->
     commit -> fresh-process relaunch reuses all 3 verified chunks
     (mtime + content_hash unchanged, no re-render) -> assemble exact
     30 frames, ffprobe duration 3.00s, validator frame_count/av_policy
     PASS, real wav decode, zero `.partial` in chunks dir, candidate is
     `.mp4` with no `.partial` sibling.
   - G3: chunk file deleted (crash) -> resume `RunnerError("tampered
     chunk")` fail-closed -> `_render_window_file` re-render that window
     -> resume finishes exact 30 frames, no `.partial` final.
   - G4: `.partial` copy of valid media -> `validate` verdict FAIL with
     completeness probe present.
5. `tests/s12/s12-t06b/test_hardware_matrix.py` (110 lines)
   - CPU MEASURED, GPU MEASURED-or-NOT_RUN (skip, no fake), SIMULATED 4K
     projection (method stated), clean-machine gate (skip NOT_RUN).
6. `docs/pm/sessions/S12-T06B/LOG.md` + `REPORT.md` (this dir).

## Live verification (real output)

- Full suite: `python -m pytest tests/s12/s12-t06b/ -q -p no:cacheprovider`
  -> **11 passed, 1 skipped in 9.55s** (exit 0).
- Measured prints:
  - `[G1] killed owned ffmpeg pid=38920 rc=1`
  - `[G2] reused 3 chunks, relaunch 0.1s, out 3.00s`
  - `[HW-CPU] MEASURED cpu='Name=Intel(R) Core(TM) i5-14600KF'
    150f/640x360 libx264 wall=0.08s fps=1923.1`
  - `[HW-GPU] MEASURED gpu='NVIDIA GeForce RTX 5070, 12227, 9255'
    150f/640x360 h264_nvenc wall=0.19s`
  - `[HW-SIM] SIMULATED method=linear-pixels measured_bpp=0.0013
    wall_1080p=0.20s projected_4k60f~624096B (estimate only)`
- Skip (NOT_RUN): `test_hw_clean_machine_not_run` — no clean VM on this
  host (`S12_T06B_CLEAN_MACHINE` unset; clean venv does NOT qualify).
- Fixes found live: (a) `ProbeVerdict` field is `.verdict`, not `.status`
  (test-side bug, 7 occurrences fixed); (b) G1 60s encode exited before
  kill (rc 0 pre-kill) -> duration 3600s; (c) first conftest draft built
  silent media (`-an`) while F/G asserted real audio -> builders emit sine
  AAC (review-caught before first run).
- Gates: `ruff check --select F tests/s12/s12-t06b/` All checks passed;
  `py_compile` 4 files OK; `git diff --check` 0; porcelain allowlist only.

## Known limitations / routed findings (not waived)

- F-OBS-01 -> owner T01: `classify_source_kind` dims>=3840x2160 fallback
  classifies `native_4k` without provenance flag. Contract says "file size
  alone never decides"; route returns `native_4k=True` only from
  ready+3840x2160+non-partial dims, so live route path is still
  provenance-shaped, but the pure-function fallback branch is dims-only.
  Repro: `ok_ctx(source_width=3840, source_height=2160,
  source_native_4k=False)` -> `classify_source_kind(...) == "native_4k"`.
  Verifier does not fix production.
- INT01 C1 correction (2026-09-09): T01-C1 closed F-OBS-01 in
  `0d5bc77` — bare >=3840x2160 dims without proved provenance now
  classify `upscale_4k`. T06B `test_f3` updated to assert the NEW
  behavior (`== "upscale_4k"`). NOTE: this T06B worktree baseline
  (`48bf514`) still carries pre-fix production, so the updated `test_f3`
  FAILS locally here by design (proves the test tracks the fix) and
  PASSES on canonical merged with T01-C1. Verifier stays read-only prod:
  no merge/rebase of production into this branch.
- Clean-machine: NOT_RUN (no clean VM; env `S12_T06B_CLEAN_MACHINE` unset).
  Beta packaging (T06A harness) therefore NOT claimed pass on clean machine.

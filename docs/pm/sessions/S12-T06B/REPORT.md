# S12-T06B REPORT — Independent acceptance + clean-machine/hardware (W7)

Status: **TASK_SUBMITTED** | Date: 2026-09-07 | Worker: S12-T06B owner
Branch: `codex/s12/s12-t06b-0907a` (worktree `s12-s12-t06b-0907a`)
Baseline: `1c9cd07` | No merge/fetch/push.

## Acceptance evidence (real numbers)

- Full suite `pytest tests/s12/s12-t06b/ -q -p no:cacheprovider`:
  **11 passed, 1 skipped in 9.55s**, exit 0, isolated temp DBs only.
- Scenario F (4K upscale honesty, MEASURED):
  - Real 1920x1080 h264+sine source -> lanczos upscale -> ffprobe
    **3840x2160**, DAR in == DAR out (no silent stretch/crop).
  - Preflight verdict `upscale_4k` with labeled
    `upscale_method=lanczos-ffmpeg-scale-x4`; aspect check pass.
  - Output decodes **30/30 frames**; validator resolution/frame_count/
    av_policy PASS; audio decodes to real wav bytes.
  - Native 4K control: real 3840x2160 encode -> verdict `native_4k`,
    `upscale_method` None, 20/20 frames, validator PASS, wav bytes.
  - Provenance decides (not file size); aspect drift + `fail_closed` ->
    `S12_EXPORT_ASPECT_MISMATCH`, eligible False; `letterbox` passes.
- Scenario G (kill + resume, MEASURED):
  - Owned ffmpeg pid killed (`pid=38920 rc=1`), death verified via
    `wait` + `tasklist`; no other process touched.
  - Relaunch reuses **3/3 verified chunks** (mtime + hash unchanged),
    relaunch 0.1s, assemble exact 30 frames, duration 3.00s, validator
    PASS, wav decode real, **zero `.partial`** in chunks or as final.
  - Missing chunk file -> `RunnerError("tampered chunk")` fail-closed ->
    window re-render -> resume exact; `.partial` path never validates.
- Hardware matrix:
  - CPU MEASURED: `Intel(R) Core(TM) i5-14600KF`, 150f 640x360 libx264,
    wall 0.08s, ~1923 fps.
  - GPU MEASURED: `NVIDIA GeForce RTX 5070` (12227 total / 9255 free MiB),
    150f 640x360 h264_nvenc wall 0.19s.
  - SIMULATED: 4K projection via linear-pixels measured_bpp=0.0013
    (estimate only, method stated).
  - Clean-machine: **NOT_RUN** — no clean VM on this host
    (`S12_T06B_CLEAN_MACHINE` unset; clean venv does NOT qualify).
    Beta pass on clean machine is NOT claimed.
- `ruff check --select F`: **All checks passed**. `py_compile`: OK.
  `git diff --check`: clean. Porcelain: allowlist only.

## Contract compliance (prompt items 5-6)

- Write allowlist respected: only `tests/s12/s12-t06b/` (new, 5 files)
  + `docs/pm/sessions/S12-T06B/` (LOG/REPORT per item 6).
- Forbidden respected: zero production files touched (porcelain proves);
  isolated DBs (`s12t06b_*` temp) — dev DB untouched; no SQL seed of
  readiness; only owned pids killed.
- Docs match artifact: all numbers above are the actually-run values.

## Routed findings

- **F-OBS-01 -> owner T01, CLOSED by T01-C1 `0d5bc77`**: bare
  >=3840x2160 dims without proved provenance now classify `upscale_4k`.
  T06B `test_f3` asserts the new behavior. This worktree still carries
  pre-fix production (baseline `48bf514`), so updated `test_f3` FAILS
  locally by design and PASSES on canonical merged with T01-C1. No prod
  merge/rebase by verifier.

## Files (new)

`tests/s12/s12-t06b/` (`__init__.py`, `conftest.py`,
`test_scenario_f_4k.py`, `test_scenario_g_resume.py`,
`test_hardware_matrix.py`), `docs/pm/sessions/S12-T06B/{LOG,REPORT}.md`.

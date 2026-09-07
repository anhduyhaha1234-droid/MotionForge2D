# S12-T03B LOG — Chunk render, stitch, checkpoint resume

Owner: S12-T03B worker. Baseline: `49fe2be1acddafbdd67d4635c61b0084edb0f070`.
Branch: `codex/s12/s12-t03b-0907a`. Date: 2026-09-07 ~14:22 VN.

## Freeze consume (read-only, verified no drift)

- `docs/contracts/s12-export.md` (s12-export-v1), `app/schemas/s12_export.py`,
  `app/services/s12_export/{preflight,capabilities,profiles,validation}.py`
  — untouched (`git status` shows only the 4 allowlist NEW paths).
- T03A persistence (`app/persistence/s12_export.py`) — consumed via fenced
  `upsert_chunk/transition_chunk/list_chunks/get_run/get_lease` only; no raw
  SQL, no row rewrite outside those methods.

## Work

1. `app/services/s12_export/chunks.py` (236 lines, NEW): `plan_chunks` tiles
   `[0, frame_count)` into contiguous cores (`next.start = prev.end + 1`,
   `verify_seam_coverage` asserts exact cover); `compute_content_hash` binds
   plan + position + attempt + checkpoint + profile + `TOOL_IDENTITY`
   (`s12-t03b-chunks-v1`); `check_disk_for_run` disk gate (T01 ESTIMATE_BPP
   basis, fail-closed `DiskInsufficientError`).
2. `app/services/s12_export/stitch.py` (394 lines, NEW): `trim_core`
   frame-exact overlap trim (verified decode count == core); `concat_cores`
   stream-copy; `mux_audio_once` maps source audio ONCE onto the video
   timeline (`-t <frames/fps>`, short audio refused — never looped/cut per
   chunk); `assemble_run` trims → concats → muxes → frame-count verifies →
   ONE atomic `os.replace`. Existing completed never overwritten; `.partial`
   paths refused as input and never produced as completed.
3. `app/services/s12_export/runner.py` (490 lines, NEW): `ensure_plan`
   (idempotent pin), `render_pending` (silent window render via `.partial`…
   → muxable `.tmp-render.mp4` scratch + atomic rename; verified+exact
   reuse; tampered file → fail-closed `RunnerError`; terminal failed/
   skipped → fail-closed, never rewritten), `resume` (fresh-process safe,
   no DB repair), `assemble` (incomplete → fail-closed). Guards:
   `StaleLeaseError` (no/foreign/expired lease), `CancelledError` (run
   status + cancel flag), `DiskFullError` (ENOSPC incl. stderr match).
   `code_for` maps every error to `S12_T03B_*` / `FENCED_WORKER` /
   `LEASE_CONFLICT` for T03C.
4. `tests/s12/s12-t03b/` (NEW, 19 tests): 8 plan/stitch + 11 runner/resume.

## Fixes from real output (no assumptions)

- `tests/s12` is not a package → file-location import of fixtures.
- Disk gate `stat` before `mkdir` → mkdir chunk/scratch dirs first.
- ffmpeg muxer sniffs format from extension → chunk scratch
  `<stem>.tmp-render.mp4`, candidate `scratch/candidate.tmp-finalize.mp4`.
- Completed+verified row + tampered file → fail-closed (T03A terminal rows
  are never rewritten by this runner); test restores the window then resumes.

## Gate (real numbers, this turn)

- T03B: 19 passed / 18.20s (`--basetemp=%TEMP%/s12t03b_r7`).
- Regression T01+T02+T03A+T04A: 99 passed / 53.14s.
- `ruff check --select F` on both new trees: All checks passed.
- `git diff --check`: clean (exit 0).
- Porcelain: exactly 4 NEW allowlist paths, zero drift on freeze set.

# S08-H02-C2 — LOG (append-only)

## 2026-08-19 — Packet materialized by manager (pre-launch)

- TASK.md / START_PROMPT.md created from Codex CHANGES_REQUESTED (S08-H02-C2:
  preset path containment + video_probe output ceiling).
- Manager verified findings on disk: P1#1 save L1943 (body.name traversal →
  project.json overwrite), P1#2 apply L1982 (preset_filename unvalidated),
  video_probe unbounded stdout parse.
- Launcher: `output/run-s08-h02-c2.ps1` (resume OWN H02 session
  20260818_020323_151164, flash). Baseline git status 169, ports free, 0 writers.
- Manager gate before launch: S08-T06-C2 manager-verified (all gates green).

## 2026-08-19 — CORRECTION ROUND C2 executed (resume OWN H02 session 20260818_020323_151164, flash)

- Hard worktree guard OK: pwd/toplevel = s08-integration, branch = codex/s08-integration, baseline `git status --short` = 170 (manager C2 packet materialized → +1 from 169; nothing reset/cleaned).
- Findings closed (Codex CHANGES_REQUESTED):
  - **P1#1 (save preset traversal):** `save_project_preset` built `presets_dir / f"{body.name.lower().replace(' ','_')}.json"` from client `body.name` → `..\project` escaped presets and overwrote `project.json`. Fixed: `body.name` is now DISPLAY-ONLY; the FILE name is a strict server-validated slug via `safe_preset_output_path` which rejects slash/backslash/`..`/dot-only/absolute/drive-qualified/control-byte/reserved names with 422 BEFORE any write, and proves the output resolves strictly under `<project>/presets`.
  - **P1#2 (apply preset traversal):** `apply_preset` joined client `preset_filename` into `proj_dir/"presets"/preset_filename` unvalidated → could read `project.json`/arbitrary files. Fixed: `safe_preset_path` requires a single safe `.json` segment and containment (symlink/junction escape rejected by resolving and proving under presets); hostile → 422, missing → 404, never 500.
  - **Secondary (video_probe unbounded parse):** `probe_video` used `capture_output=True` + `-show_streams` (all stdout, all streams, no size ceiling). Fixed: bounded runner `_run_ffprobe` with explicit `PROBE_MAX_OUTPUT_BYTES` (1 MiB) ceiling + deadline (fails closed via `ProbeOutputTooLargeError`/`TimeoutExpired`), queries ONLY required fields for the FIRST relevant streams (`-select_streams v:0 / a:0` + `-show_entries`), plus a `PROBE_MAX_STREAMS` parse ceiling + JSON-shape validation. Oversized/malformed probe output fails closed — callers do NOT publish media (route maps probe failure → 415, no file/state change).
  - **Remaining-join audit:** converted the only two remaining client-controlled filesystem joins (preset save/apply). Everything else verified: int-based paths (scene/frame/audio), `pwf._project_dir`/`object_dir` validated identifiers, asset_path served under containment, preset character lookups are fixed-dict keys (no path join).
- Code files changed: `app/api/routes/projects.py`, `app/services/video_probe.py`, `app/workflow/preset_service.py` (resolver). Tests: `tests/test_s08_h02_security.py` (+13 tests). Frontend NOT touched (backend-only round).
- Validation (fresh isolated roots, `-p no:cacheprovider`, shallow basetemps `C:/Users/Admin/AppData/Local/Temp/s08h02c2-*`, `MOTIONFORGE_DATABASE_URL` unset; exact commands in REPORT.md):
  1. New preset/video_probe tests → **20 passed** (9.75s).
  2. Full `tests/test_s08_h02_security.py` → **50 passed** (21.92s).
  3. `test_s08_h02_security.py` + `test_api.py` → **75 passed** (35.51s).
  4. Cross-suite (golden vertical + H02 + object_extraction_api + R01) → **77 passed** (76.25s; golden `s08h02c2-golden/golden-metrics.json`).
  5. `python -m ruff check app tests` → **All checks passed!**
  6. `python -m mypy app` → **Success: no issues found in 88 source files**.
  7. `git diff --check` → exit 0 (only pre-existing LF→CRLF advisories).
  8. Frontend tsc/lint/build: backend-only round — frontend untouched by this writer; the fresh 7/7 baseline still ran frontend gates (see 9).
  9. Fresh quality baseline `20260819-015528` → **7/7 PASS** (python suite 581.82s, lint, typing, tsc, lint, build all exit 0).
  10. Protected MAIN unchanged: channels.json SHA `dd7aae26…555`, DB 311296 B / `67d5c773…`, SAM2.1 898083611 B / `2647878d…` (mtime 2026-07-29); QA ports NO_LISTENERS.
- Final `git status --short` = 171 (baseline + golden evidence metrics file `output/s08-sprint/s08h02c2-golden/golden-metrics.json`).
- REPORT.md CORRECTION ROUND C2 section written. **Status: SUBMITTED** (never self-approved; TASK.md / PM_REVIEW.md untouched; no commit/reset/clean/stash).

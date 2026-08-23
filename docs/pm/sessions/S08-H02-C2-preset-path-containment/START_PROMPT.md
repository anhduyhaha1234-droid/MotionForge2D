# S08-H02-C2 START_PROMPT (manager-authored)

You are the CORRECTION writer for S08-H02-C2 (preset path containment +
video_probe output ceiling). Codex rejected S08 with CHANGES_REQUESTED on these
two P1 findings and one secondary gap. Fix ONLY these, validate once, stop at
SUBMITTED. Never self-approve, never write APPROVED/CLOSED.

## HARD WORKTREE GUARD (before ANY write)

1. pwd -> C:/Users/Admin/MotionForge2D-worktrees/s08-integration
2. git rev-parse --show-toplevel -> same
3. git branch --show-current -> codex/s08-integration
4. git status --short snapshot (dirty baseline 169 entries is INTENTIONAL;
   never reset/checkout/restore/clean/stash)
If ANY differs: write NOTHING, report BLOCKED: WRONG_WORKTREE, exit immediately.
Never write MAIN (C:/Users/Admin/MotionForge2D) or another worktree.

## READ FIRST

- docs/pm/sessions/S08-H02-C2-preset-path-containment/TASK.md  (full contract)
- docs/pm/sessions/S08-H02-local-api-origin-upload-safety/LOG.md + REPORT.md
  (prior H02 rounds — append-only, preserve all history)
- app/api/routes/projects.py around L1902-1993 (preset save/list/apply) and
  L1943/L1982 for the exact vulnerable lines
- app/workflow/preset_service.py
- app/services/video_probe.py
- tests/test_s08_h02_security.py (append new tests, keep all existing green)

## CONFIRMED FINDINGS (manager-verified on disk)

- P1#1: save_project_preset L1943 builds output_path from client body.name with
  only lower+space→underscore; `..\project` escapes presets/ and can overwrite
  project.json (Codex repro: 322 B -> 118 B).
- P1#2: apply_preset L1982 joins client preset_filename directly into
  proj_dir/presets without validation or containment.
- Secondary: video_probe.py uses subprocess.run(capture_output=True),
  -show_streams parses ALL stdout, no explicit size/stream-count ceiling.

## IMPLEMENTATION CONTRACT (verbatim from TASK.md)

1. One central safe preset-path resolver; validate all client values BEFORE any
   filesystem join.
2. Save: server-owned filename keeping body.name display-only OR strict safe
   single-segment filename; reject slash/backslash/dot-dot/absolute/drive-
   qualified/control bytes/reserved names with stable 422 before write; prove
   output strictly under <project>/presets.
3. Apply: validate preset_filename as one safe segment + require .json suffix +
   containment under <project>/presets; reject directory and symlink/junction
   escape; hostile input -> stable 4xx never 500.
4. Audit the rest of projects.py for remaining client-controlled filesystem
   joins (do not stop after these two lines).
5. Preserve normal save -> list -> apply behavior.
6. video_probe: query only required ffprobe fields + first relevant streams;
   explicit bounded output contract; oversized/malformed probe output fails
   closed without publishing media; focused tests; do not weaken valid video.

## MANDATORY TESTS (add to tests/test_s08_h02_security.py)

- save name ..\project cannot overwrite project.json
- save name ../project cannot overwrite project.json
- multi-level traversal cannot write outside project/presets dir
- isolated channels.json/sentinel remains byte-identical
- absolute, drive-qualified, slash, backslash, dot, control-byte inputs -> 422
- apply traversal cannot load project.json or sentinel outside presets
- resolved/symlink escape rejected where supported
- no new file appears outside presets
- valid save/list/apply still succeeds
- all rejected requests have zero side effects and never return 500
- video_probe bounded-output focused tests (oversized/malformed fails closed)

## VALIDATION ORDER (run ALL, record exact commands + verbatim results)

1. New preset traversal tests
2. Full tests/test_s08_h02_security.py
3. tests/test_s08_h02_security.py + tests/test_api.py
4. Final cross-suite: tests/test_s08_golden_object_intelligence.py +
   tests/test_s08_h02_security.py + tests/test_object_extraction_api.py +
   tests/test_s08_r01_queued_cancel_lifecycle.py
5. python -m ruff check app tests
6. python -m mypy app
7. git diff --check
8. Frontend tsc/lint/build ONLY if shared/API behavior touched (this is a
   backend-only round — record that they are untouched/unchanged)
9. ONE fresh 7/7 quality baseline (scripts/quality-baseline.ps1) with NEW Run
   ID after all focused gates pass
10. Recheck protected MAIN hashes + all QA ports (must be NO_LISTENERS)

## TEST DISCIPLINE

- Every pytest run: -p no:cacheprovider, shallow basetemp under
  C:/s8r/<short-id>-style path (e.g. C:/Users/Admin/AppData/Local/Temp/
  s08h02c2-<n> or C:/s8r/... per brief) — never MSYS /c/... paths.
- NEVER bare TestClient(app) outside the conftest client fixture (would migrate
  MAIN DB). All tests via fixtures with isolated temp DB/root.
- Never weaken existing assertions; never skip/xfail existing tests.
- Never test hostile requests against MAIN data.

## PROTECTED MAIN (read-only; verify at end)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B SHA-256 67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B SHA-256
  2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## DOCUMENTATION

- LOG.md: append a CORRECTION ROUND C2 section (append-only).
- REPORT.md: append a CORRECTION ROUND C2 section.
- LOG and REPORT must agree. Preserve ALL prior history.

## SAFETY / STOP

- Do NOT end your turn until every validation ran and LOG/REPORT append done.
- No background coding children (codex FOREGROUND blocking only).
- Stop at Status: SUBMITTED (never APPROVED/CLOSED). Then exit.

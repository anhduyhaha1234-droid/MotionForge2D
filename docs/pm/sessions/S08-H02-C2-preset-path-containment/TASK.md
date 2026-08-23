# S08-H02-C2 — Preset Path Containment (Codex CHANGES_REQUESTED follow-up)

**Status:** PLANNED
**Session type:** resume OWN H02 session `20260818_020323_151164` (flash) — same Task family
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Dirty baseline:** 169 git-status entries (intentional; never reset/clean/stash)

## Codex decision (verbatim distilled)

S08 = CHANGES_REQUESTED. Two P1 findings in preset path handling + one
secondary gap in video_probe. Fix ONLY these; validate once; stop at
SPRINT_SUBMITTED. Never APPROVED/CLOSED.

## P1 #1 — save preset filename traversal

`app/api/routes/projects.py` ~line 1943:

    output_path = presets_dir / f"{body.name.lower().replace(' ', '_')}.json"

`body.name` is client-controlled; only `.lower().replace(' ','_')` is applied,
so a name like `..\project` yields `<presets>/../project.json` → overwrites the
project's `project.json`. Codex reproduced: name `..\project` → project.json
changed 322 B → 118 B. Additional `../` segments can escape the project dir.

## P1 #2 — apply preset filename traversal

`app/api/routes/projects.py` ~line 1982:

    preset_path = proj_dir / "presets" / preset_filename

`preset_filename` (URL path param) is not validated or containment-checked;
Windows backslash traversal can resolve outside the presets directory and read
(e.g. `project.json`, or worse) arbitrary files.

## Secondary gap — video_probe unbounded parse

`app/services/video_probe.py`: `subprocess.run(capture_output=True)` captures
ALL stdout/stderr with no explicit hard ceiling; `-show_streams` parses every
stream. Timeout + dimension caps exist, but stdout size and stream count are
unbounded → a hostile container can drive unbounded capture/parse.

## Required implementation

1. Central safe preset-path resolver (validate → resolve → containment under
   `<project>/presets`).
2. Validate all client-controlled values BEFORE any filesystem join.
3. Save:
   - Prefer server-owned filename keeping `body.name` display-only; OR strict
     safe single-segment filename.
   - Reject slash, backslash, dot/dot-dot, absolute, drive-qualified, control
     bytes, reserved/colliding names → stable 422 before write.
   - Prove output strictly under `<project>/presets`.
4. Apply:
   - Validate preset_filename as one safe segment, require `.json` suffix,
     containment under `<project>/presets`.
   - Reject directory and symlink/junction escape.
   - Hostile input → stable 4xx, never 500.
5. Audit the rest of projects.py for remaining client-controlled filesystem
   joins (do not stop after the two lines).
6. Preserve normal save → list → apply behavior.
7. video_probe: query only required ffprobe fields/first relevant streams;
   explicit bounded output contract; oversized/malformed probe output fails
   closed without publishing media; focused tests; do not weaken valid video.

## Mandatory tests (tests/test_s08_h02_security.py)

- save name `..\project` cannot overwrite project.json.
- save name `../project` cannot overwrite project.json.
- multi-level traversal cannot write outside project/presets dir.
- isolated channels.json/sentinel remains byte-identical.
- absolute, drive-qualified, slash, backslash, dot, control-byte → 422.
- apply traversal cannot load project.json or sentinel outside presets.
- resolved/symlink escape rejected where supported.
- no new file appears outside presets.
- valid save/list/apply still succeeds.
- all rejected requests have zero side effects, never 500.

## Validation order

1. New preset traversal tests.
2. Full tests/test_s08_h02_security.py.
3. test_s08_h02_security.py + test_api.py.
4. Final cross-suite: test_s08_golden_object_intelligence.py +
   test_s08_h02_security.py + test_object_extraction_api.py +
   test_s08_r01_queued_cancel_lifecycle.py.
5. python -m ruff check app tests.
6. python -m mypy app.
7. git diff --check.
8. Frontend tsc/lint/build ONLY if shared/API behavior touched.
9. ONE fresh 7/7 quality baseline after all focused gates pass.
10. Recheck protected MAIN hashes + all QA ports.

## Protected MAIN expected (read-only)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B, SHA-256 67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B, SHA-256 2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## Files in scope

- app/api/routes/projects.py
- app/services/video_probe.py
- app/workflow/preset_service.py (if resolver belongs here)
- tests/test_s08_h02_security.py
- H02-C2 LOG.md / REPORT.md

## Forbidden

- Self-approve / write APPROVED/CLOSED.
- Modify TASK.md / PM_REVIEW.md.
- Commit/push/merge/reset/checkout/restore/clean/stash.
- Modify MAIN or another worktree.
- Overwrite prior LOG/REPORT content (append-only).
- Test hostile requests against MAIN data.

## Stop

Stop at SUBMITTED after full validation; never self-approve.

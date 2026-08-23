# S08-H02-C3 — Probe deadline + preset root containment + preset collision

**Status:** PLANNED
**Session type:** NEW session (Codex mandate: do NOT resume 20260818_020323_151164)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)
**Dirty baseline:** 171 git-status entries (intentional; never reset/clean/stash)

## Run timestamps (Codex protocol — never infer from a reused session)

- run_started_at_local: 2026-08-19T03:35:16+07:00
- run_started_at_utc: 2026-08-18T20:35:16Z
- run_finished_at_local/utc: (filled by writer after completion)
- elapsed_seconds: (fill = finished_epoch - started_epoch)

## Codex CHANGES_REQUESTED (S08-H02-C3) — fix ONLY these three

### Finding 1 — video_probe._run_ffprobe blocking sequential drain

`_run_ffprobe` does blocking `stdout.readline()` then `stderr` sequentially.
Codex repro: timeout requested 0.2s, actual elapsed 3.016s, deadline_enforced
= False.

Required:
- Drain stdout/stderr CONCURRENTLY.
- Enforce deadline and COMBINED output cap even when output has no newline or
  one pipe fills.
- Kill/reap the FULL child process on timeout/cap.
- Mandatory REAL subprocess tests (not only monkeypatch):
  - child sleeps 3s; timeout 0.2s must return/raise in under 1s.
  - child fills stderr before writing stdout; no deadlock.
  - child writes an over-cap line without newline; fails within bounded time.

### Finding 2 — preset root containment when <project>/presets is a symlink/junction

If `<project>/presets` itself is a symlink/junction pointing OUTSIDE the
project, current `safe_preset_output_path` / `safe_preset_path` accept outside
targets (they resolve `presets_dir` and prove containment relative to it, so a
relocated root passes).

Required:
- Anchor BOTH the unresolved AND resolved presets root to the VALIDATED
  project directory.
- Save/apply must return stable 422 with zero side effects.
- Add a DIRECTORY-symlink/junction test (not only a file-symlink test).

### Finding 3 — preset collision (distinct names map to same slug)

`A!` and `A?` both map to `a.json` (slugify strips `!`/`?`).

Required:
- Use a server-owned UNIQUE filename, OR reject existing/colliding targets
  explicitly with 409.
- Never silently overwrite an existing preset.
- Add normal save/list/apply AND collision-preservation tests.

## Files in scope

- app/services/video_probe.py
- app/workflow/preset_service.py
- app/api/routes/projects.py (only if resolver signatures/route calls change)
- tests/test_s08_h02_security.py
- S08-H02-C3 packet LOG.md / REPORT.md

## Validation order (run ALL)

1. New probe-deadline + preset-root + collision tests (focused -k).
2. Full tests/test_s08_h02_security.py.
3. tests/test_s08_h02_security.py + tests/test_api.py.
4. Cross-suite: test_s08_golden_object_intelligence.py + test_s08_h02_security.py
   + test_object_extraction_api.py + test_s08_r01_queued_cancel_lifecycle.py.
5. python -m ruff check app tests.
6. python -m mypy app.
7. git diff --check.
8. ONE fresh 7/7 quality baseline (scripts/quality-baseline.ps1, NEW Run ID).
9. Recheck protected MAIN hashes + all QA ports (NO_LISTENERS).

## Protected MAIN expected (read-only)

- channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
- data/motionforge.db 311296 B, SHA-256 67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
- models_checkpoints/sam2.1_hiera_large.pt 898083611 B, SHA-256 2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## Forbidden

- Self-approve / write APPROVED/CLOSED.
- Modify TASK.md / PM_REVIEW.md of any packet.
- Commit/push/merge/reset/checkout/restore/clean/stash.
- Modify MAIN or another worktree.
- Overwrite prior LOG/REPORT content (append-only).
- Test hostile requests against MAIN data.

## Stop

Stop at SUBMITTED after full validation; never self-approve. S08 stays
SPRINT_SUBMITTED. Do not start S07/S09.

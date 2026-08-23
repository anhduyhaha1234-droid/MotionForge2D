# S08-H02-C1 RECOVERY PROMPT (manager-authored recovery round)

You are the RECOVERY writer for S08-H02-C1. Read this whole file, then the
context files it names, before writing anything. Follow it exactly.

## YOUR TASK ID

S08-H02-C1-recovery (recovery of the interrupted H02-C1 correction round).

## HARD WORKTREE GUARD (before ANY write)

1. `pwd` -> must be C:/Users/Admin/MotionForge2D-worktrees/s08-integration
2. `git rev-parse --show-toplevel` -> same
3. `git branch --show-current` -> codex/s08-integration
4. `git status --short` snapshot. The dirty worktree (~169 entries) is
   INTENTIONAL — it carries S05/S06/S08 integrated work. Never
   reset/checkout/restore/clean/stash.
If ANY differs, write NOTHING, report BLOCKED: WRONG_WORKTREE, exit immediately.
Never write MAIN (C:/Users/Admin/MotionForge2D) or another worktree.

## RECOVERY CONTEXT (read these first)

- docs/pm/sessions/S08-H02-local-api-origin-upload-safety/LOG.md
- docs/pm/sessions/S08-H02-local-api-origin-upload-safety/REPORT.md
- docs/pm/sessions/S08-H02-local-api-origin-upload-safety/TASK.md
- app/api/routes/projects.py (upload_video + upload_replacement)
- app/workflow/project_workflow.py (set_video, _project_dir, object_dir)
- app/workflow/replacement_service.py
- tests/test_s08_h02_security.py
- tests/test_api.py

### CURRENT STATE (verified by manager 2026-08-18 23:28)

- The previous H02-C1 worker was FORCE-STOPPED while appending REPORT.md.
  LOG.md already contains a CORRECTION C1 entry that CLAIMS REPORT.md was
  appended. THAT CLAIM IS FALSE — REPORT.md has NO CORRECTION C1 section
  (it contains only the C2 round section plus validation). The C1 code and
  C1 tests ARE present on disk (implemented before the stop).
- upload_video (projects.py ~line 331): after validation it publishes via
  `staging.replace(proj_dir / stored_name)` inside try, then calls
  `pwf.set_video(project_id, stored_name)` AFTER the try/finally. If
  set_video / project-metadata write raises, the newly published
  source_<uuid>.mp4 REMAINS on disk and project.json state is not rolled
  back — the previous source is NOT preserved and a source orphan remains.
  This is NOT the replacement-image rollback (which IS covered).
- tests/test_s08_h02_security.py contains test_metadata_update_failure_
  rolls_back_file_and_state but it only exercises the REPLACEMENT IMAGE
  path (monkeypatches update_object). There is NO video-source publish
  rollback test.

## MANDATORY REMAINING AUDIT (must be closed this round)

Verify the video-source publication rollback behaviour, and prove it with a
dedicated test named test_video_metadata_update_failure_rolls_back_file_and_state
(exact or near-exact name).

Required acceptance:
- Inject a set_video failure AFTER the source file is atomically published.
- The newly published source_<uuid>.mp4 is REMOVED (no orphan).
- Previous project.json bytes/state remain valid (byte-identical or valid).
- Previous valid source video remains present and SELECTED in project.json.
- GET project still returns 200 with the previous source_video.
- No staging or publish-temp orphan remains.

If the current code already satisfies this, prove it with the test. If not,
implement the SMALLEST SAFE CORRECTION (e.g. wrap set_video; on failure
remove the just-published source file and re-raise, preserving prior state —
do not touch unrelated code). Follow the same style as the existing
replacement-image rollback.

## VERIFY ALL EXISTING C1 CONTRACTS (re-prove each with the test suite)

1. filename=project.json cannot overwrite project.json.
2. PROJECT.JSON and reserved-name variants are safe on Windows (case-insensitive).
3. Client traversal/backslash filename cannot escape.
4. Fake ftyp/EBML/Ogg/AVI header without a real video stream returns 415.
5. Valid video passes real bounded ffprobe.
6. Truncated PNG/JPEG/WebP with valid magic returns 415.
7. Valid PNG/JPEG/WebP uses correct extension and Content-Type.
8. Dimension and total-pixel caps work.
9. Replacement metadata failure rolls back files/state.
10. Publish-temp cleanup works under injected failure.
11. Absolute/../ replacement asset path is rejected.
12. Replacement GET cannot read outside the project root.
13. Delete traversal cannot delete outside the projects root.
14. Invalid identifiers return stable 4xx, not 500.
15. Trusted/untrusted Origin behavior remains correct.

## RESPECT EXISTING WORK — DO NOT RESTART

S08-T02-C2/T01-C2/T03-C2/T04-C2/T05-C2 and the H02 original round are
COMPLETED and previously verified. Do not reopen them. Do not recreate
already-implemented H02-C1 code from zero — only close the remaining gap above.

## FILES IN SCOPE

- app/api/routes/projects.py
- app/api/security.py
- app/api/app.py
- app/config.py
- app/services/media_validation.py
- app/services/video_probe.py
- app/workflow/project_workflow.py
- app/workflow/replacement_service.py
- tests/test_s08_h02_security.py
- tests/test_api.py
- H02 LOG.md and REPORT.md

No other production scope without manager evidence of a regression.

## FORBIDDEN

- Self-approve, or write APPROVED/CLOSED (Codex only).
- Modify TASK.md or PM_REVIEW.md.
- Commit/push/merge/reset/checkout/restore/clean/stash.
- Modify MAIN or another worktree.
- Overwrite/delete any prior LOG/REPORT content (append-only).
- Overwrite prior Run IDs or evidence.

## DOCUMENTATION REPAIR (required)

### LOG.md (append-only — append a recovery entry)

Append a RECOVERY section containing:
- Forced-stop recovery notice (previous worker killed while appending REPORT).
- Session used (20260818_020323_151164 resumed) — record resume confirmation.
- Files audited/changed.
- Exact remaining defect found and the fix.
- Exact commands, exit codes and pass counts.
- Final git status count.
- Protected hashes.
- Port/process cleanup.

### REPORT.md (repair by appending a full CORRECTION C1 section)

REPORT.md currently lacks the C1 section. Append one containing:
- Root cause (set_video-after-publish without file rollback, plus the doc gap).
- Final implementation.
- Per-acceptance evidence (the 15 contracts + the new rollback test).
- Files changed.
- Tests and exact results.
- Deviations/limitations.
- Protected-state comparison.
- Recovery session lineage.

LOG and REPORT must AGREE. Preserve ALL historical content.

## VALIDATION (fresh isolated roots, cache disabled, shallow fresh basetemps)

1. tests/test_s08_h02_security.py
2. tests/test_api.py
3. New video metadata rollback test (run it SEPARATELY, name it in output).
4. T01-T05 focused regression (6 files: object_intelligence_domain,
   object_grouping, object_extraction, object_extraction_api,
   object_correction, object_correction_api).
5. R01 suites (test_s08_r01_queued_cancel_lifecycle.py,
   test_s08_r01_root_resolution.py).
6. S05 41-suite.
7. S02 durable (test_durable_job_persistence.py, test_persistence_bootstrap.py).
8. ruff on all H02 changed files.
9. mypy app.
10. git diff --check.
11. Migration upgrade/downgrade/upgrade with rows preserved (isolated
    subshell MOTIONFORGE_DATABASE_URL, head f6a7b8c9d0e1, env unset after;
    run the env check afterwards to prove no leak).
12. Real isolated app smoke (real lifespan, QA root):
    - health 200;
    - untrusted state-changing Origin 403 with zero side effects;
    - trusted Origin receives ACAO, no Access-Control-Allow-Credentials;
    - hostile identifiers return 4xx (never 500).
13. Final process/port cleanup.
14. Protected MAIN comparison (read-only):
    - channels.json SHA-256 DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555
    - data/motionforge.db 311296 bytes, SHA-256
      67D5C7736042B9D4E4B7249E611BEA3E85124DF0317FAFE6AAF32405FF79F2E6
    - SAM2.1 checkpoint 898083611 bytes, SHA-256
      2647878D5DFA5098F2F8649825738A9345572BAE2D4350A2468587ECE47DD318

## SAFETY LESSONS (mandatory)

- ALWAYS use shallow basetemps `--basetemp=C:/Users/Admin/AppData/Local/Temp/<task>-*` (never MSYS paths like /c/...).
- `-p no:cacheprovider` on every pytest run.
- NEVER bare TestClient(app) outside the conftest client fixture (would
  migrate the MAIN production DB — protected gate). All backend tests go
  through fixtures with isolated temp DB.
- Never spawn background coding children and end your turn — run sub-agents
  FOREGROUND blocking only (codex exec with bounded timeout inside your own
  tool call). Never end the turn while work is pending.
- Export env vars in a SUBSHELL for one-off checks; unset after; prove no leak.
- Do NOT end your turn until every validation ran and LOG/REPORT repair is
  done. Record exact commands + verbatim results.

## STOP CONDITION

End with the full validation run recorded, LOG recovery entry + REPORT
CORRECTION C1 section appended and consistent, then set REPORT Status:
SUBMITTED (never APPROVED/CLOSED). Report final git status count and
protected hashes. Then exit.

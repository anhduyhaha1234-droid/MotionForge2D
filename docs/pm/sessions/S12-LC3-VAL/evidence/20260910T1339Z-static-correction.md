# S12-LC3-VAL R2 post-transport static correction

Transport correction only; no approval or closure claim.

## Scope and route

- Route recorded: `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.
- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val`
- Branch: `codex/s12-lc3-luna-val`
- Parent before correction commit: `a14ca87f4ee6cdf579bb6c260f5d4b2b1e5a232f`
- Correction runtime: `C:\Users\Admin\mfqa\s12-lc3-r2\20260910T124058Z\VAL-static-correction\runtime`
- Existing untracked `work/` was preserved.

The reported correction set was exactly these four paths:

```text
app/services/s12_export/publication.py
app/services/s12_export/validation.py
tests/s12/s12-lc3-val/test_r2_ownership_recovery.py
tests/s12/s12-t03c/test_publication.py
```

All edits are import ordering or import-block blank-line changes. No runtime
behavior was changed. An exploratory exact historical tree scan surfaced four
additional pre-existing I001s in older R1/T04A tests; those incidental edits
were reverted, and those paths are not in the correction diff.

## Raw test envelope

```text
python -m pytest tests/s12/s12-lc3-val/test_r2_ownership_recovery.py::test_r2_f01_real_handoff_cannot_overwrite_winner tests/s12/s12-lc3-val/test_r2_ownership_recovery.py::test_r2_f02_foreign_companion_is_not_overwritten tests/s12/s12-lc3-val/test_r2_ownership_recovery.py::test_r2_f02_child_kill_fresh_process_reclaims_same_db_job -q -s --tb=short
cwd C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val
start 2026-09-10T13:38:16.1494616Z
end   2026-09-10T13:38:24.6998658Z
duration_sec 8.550 exit 0
3 passed, 6 warnings in 7.40s
R2_F01_MICRO winner=completed loser=PublicationRaceLost final_sha256=1967f45adf8e5e1f55ada4d6f2037b20d062a00b6ab1a2eb1e35e37d4711739f run_status=completed job_state=queued
R2_F02_MICRO final_exists=False sidecar_unchanged=True candidate_exists=False
R2_F02_PROCESS_RESTART {"fresh_worker":"worker-fresh","job_id_stable":true,"killed_pid":37868,"retained_chunk_sha256":"4a86946f3e4d3b477b4167a33eccd457314a7b931f4d56ce80bd4c0e73115326","run_status":"running"}
```

## Raw static envelope

The final gate was run against the exact four-file correction allowlist:

```text
python -m compileall -q app/services/s12_export/publication.py app/services/s12_export/validation.py tests/s12/s12-lc3-val/test_r2_ownership_recovery.py tests/s12/s12-t03c/test_publication.py
python -m ruff check --select F,I app/services/s12_export/publication.py app/services/s12_export/validation.py tests/s12/s12-lc3-val/test_r2_ownership_recovery.py tests/s12/s12-t03c/test_publication.py
git diff --check
cwd C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val
start 2026-09-10T13:38:34.9967810Z
end   2026-09-10T13:38:35.1580433Z
duration_sec 0.161 exit 0
compileall=0 ruff_f_i=0 diff_check=0
```

The first expanded tree scan at `2026-09-10T13:34:42.5917066Z` passed
compileall/diff-check but reported four I001s outside the named correction
set. Those older-test import edits were reverted. The named-file I001 check
then passed before the final micro/static sequence.

## Post-correction file hashes

```text
app/services/s12_export/publication.py sha256=E72AF560648378C4A6DB6AD2C91A15A67E7FC092DBA0869147B801448B6FE98D size=36920 lines=1002
app/services/s12_export/validation.py sha256=66FB87169CE8141ACBAA2AB0D68591D49ED90BC6DED0C94F724664FF54F6507F size=76392 lines=2081
tests/s12/s12-lc3-val/test_r2_ownership_recovery.py sha256=FCAEEC8B6B4944FBC06F6DFBB465BBE8E95A8B525A1209B0296354DF040DE7A9 size=11720 lines=292
tests/s12/s12-t03c/test_publication.py sha256=0416C07ADCC0978D541976BB736949EE5263F158B283FCD509A60562ABDA9AA3 size=33948 lines=864
```

`git diff --name-only` and `git diff --numstat` before commit contained only
the four paths above: `2/1`, `1/1`, `1/2`, and `11/8` respectively.

## Cleanup and status

The runtime has the ownership marker `.owner` only after generated children
were removed following process shutdown. No R2 static-correction process
remained. The pre-existing `work/` remains untouched. The correction is a
local transport checkpoint only.

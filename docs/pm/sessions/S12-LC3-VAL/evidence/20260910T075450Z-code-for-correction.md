# VAL correction: `ExportRunner.code_for` placement

- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val`
- Branch: `codex/s12-lc3-luna-val`
- Parent: `735c47ec58380bf25e7265ba52e3bb406e844f0b`
- Changed production path: `app/services/s12_export/runner.py` only
- Fix: moved the existing `code_for` static method back inside `ExportRunner`;
  no API, UI, persistence, or behavior changes were made.

## Raw test commands

```text
python -m pytest tests/s12/s12-t03b/test_runner_resume.py::test_expired_lease_fails_closed tests/s12/s12-t03b/test_runner_resume.py::test_cancel_flag_stops_run tests/s12/s12-t03b/test_runner_resume.py::test_tampered_chunk_hash_replay_fails tests/s12/s12-t03b/test_runner_resume.py::test_audio_mapping_exact_not_looped -q
```

cwd: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val`

- Start UTC: `2026-09-10T07:53:38.5449568Z`
- End UTC: `2026-09-10T07:53:49.4942172Z`
- Exit: `0`
- Raw result: `4 passed, 8 warnings in 9.41s`

```text
python -m pytest tests/s12/s12-lc3-val -q
```

- Start UTC: `2026-09-10T07:54:20.3030705Z`
- End UTC: `2026-09-10T07:54:28.8220064Z`
- Exit: `0`
- Raw result: `7 passed in 7.44s`

```text
python -m compileall -q app/services/s12_export/runner.py tests/s12/s12-lc3-val
python -m ruff check --select F app/services/s12_export/runner.py tests/s12/s12-lc3-val
git diff --check
python -c "from app.services.s12_export.runner import ExportRunner; assert hasattr(ExportRunner, 'code_for'); print('HAS_CODE_FOR=1')"
```

- Start UTC: `2026-09-10T07:54:50.1026838Z`
- End UTC: `2026-09-10T07:54:50.9203858Z`
- Raw result: `COMPILE=0 RUFF_F=0 DIFF_CHECK=0 ATTR=0`

## Post-write guard

The supplied `baseline-val-guard.json` was re-run after the correction. Raw
result: `PASS_WITH_EXPECTED_ALLOWLIST_CHANGES`, `missing=[]`; all protected
baseline entries remain unchanged and `runner.py` is the only changed
production entry relative to the prior commit. See the updated
`20260910T071125Z-post-guard.json` for the complete hash table.

No gate was left running. Owned pytest temporary children were removed after
process shutdown; no source/test authority was deleted. This evidence makes
no approval or closure claim.

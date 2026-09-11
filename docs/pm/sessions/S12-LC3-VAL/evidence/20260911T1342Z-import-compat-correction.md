# S12-LC3-VAL post-integration import compatibility correction

This is the exact-owner VAL correction for session
`01a089a3-2ca7-7642-8c16-e2904d9f7afa`, route `gpt-5.6-luna`, reasoning
`high`, fallback `OFF`. No route/provider/config change was made.

The live VAL checkout was branch `codex/s12-lc3-luna-val` at
`ad0bf034fc218cc3d95cbf6b2e80c84eff89979f`, the requested parent. The
referenced integrated candidate `17fa931c76bcffb6be5148531d786d2f6e745c41`
exists as a merge object but is not the live VAL checkout. Its tree was
checked read-only: it contains
`tests/s12/s12-lc3-retry/test_export_jobs_api.py` and does not contain
`tests/s12/s12-t03c/test_export_jobs_api.py`. The transferred RETRY blob was
not moved or modified.

## Pre-fix evidence

The independent candidate collection red was reported for exactly:

```text
python -m pytest -q tests/s12/s12-lc3-val tests/s12/s12-t03c/test_publication.py tests/s12/s12-t04a/test_c2_source_locked.py
candidate HEAD: 17fa931c76bcffb6be5148531d786d2f6e745c41
failure: collection error at tests/s12/s12-t03c/test_publication.py import test_export_jobs_api as base
failure: ModuleNotFoundError: No module named 'test_export_jobs_api'
node IDs: none; collection stopped before node collection
```

That red belongs to the independent integrated tree and is not falsely
reproduced here: before the correction, the live VAL checkout still had the
old T03C helper, so the same command ran from
`2026-09-11T13:38:01.7356854Z` to `2026-09-11T13:39:07.6827296Z`, duration
`65.9428512s`, exit `0`, with `78 passed, 64 warnings`. The old helper was
read-only during this correction.

## Bounded correction

Only `tests/s12/s12-t03c/test_publication.py` changed. It imports `sys`,
computes the explicit sibling task-qualified path
`tests/s12/s12-lc3-retry`, prepends it only when that directory exists, and
then preserves the existing `import test_export_jobs_api as base` and every
test body/assertion. No RETRY file was moved or edited.

The R3 boundary micro after the edit passed:

```text
argv: python -m pytest -q tests/s12/s12-lc3-val/test_r3_publication_boundaries.py
cwd: C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val
start: 2026-09-11T13:39:21.1680125Z
end:   2026-09-11T13:39:35.4314691Z
duration_seconds: 14.2599471
exit: 0
result: 5 passed, 10 warnings
```

The exact finite affected command after the edit passed:

```text
argv: python -m pytest -q tests/s12/s12-lc3-val tests/s12/s12-t03c/test_publication.py tests/s12/s12-t04a/test_c2_source_locked.py
cwd: C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val
start: 2026-09-11T13:39:49.4743338Z
end:   2026-09-11T13:40:55.6460469Z
duration_seconds: 66.1678312
exit: 0
result: 78 passed, 64 warnings
```

The exact green node set is the collected set under
`tests/s12/s12-lc3-val`, `tests/s12/s12-t03c/test_publication.py`, and
`tests/s12/s12-t04a/test_c2_source_locked.py`; no collection errors remained.

Static checks passed:

```text
argv: python -m compileall -q <exact VAL paths>; python -m ruff check --select F,I <exact VAL paths>; git diff --check
cwd: C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val
start: 2026-09-11T13:41:06.9903764Z
end:   2026-09-11T13:41:07.1489255Z
duration_seconds: 0.1549751
exit: 0
result: compileall=0, ruff=0, diff_check=0
```

The first post-correction guard invocation ran from
`2026-09-11T13:43:52.5950695Z` to `2026-09-11T13:43:53.0252946Z`, duration
`0.4262233s`, exit `1`, with `2` failures. Those were the previously landed
R3 changes in `app/services/s12_export/publication.py` and
`tests/s12/s12-t04a/test_c2_source_locked.py`; they were omitted from the
initial correction invocation even though the supplied R3 baseline predates
those authorized changes. No new unlisted path was reported.

The corrected guard reran from `2026-09-11T13:44:14.6288807Z` to
`2026-09-11T13:44:14.7066513Z`, duration `0.0736926s`, exit `0`, using the
prior R3 allowances plus this correction's T03C/LOG/REPORT paths. It returned
`{"status":"VERIFIED","failures":0,"entries":75}` and wrote
`20260911T1342Z-post-guard.json`. Because LOG was then appended with the
guard record, the final guard rerun was `2026-09-11T13:44:48.3210229Z` to
`2026-09-11T13:44:48.3951011Z`, duration `0.0705654s`, exit `0`, with the same
`{"status":"VERIFIED","failures":0,"entries":75}` result. This is a
transport correction only; it makes no approval or closure claim.

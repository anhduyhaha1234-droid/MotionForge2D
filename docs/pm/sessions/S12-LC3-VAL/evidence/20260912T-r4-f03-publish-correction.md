# S12-LC3-VAL R4 F03 full-publisher path correction

Exact-owner VAL transport evidence only; no approval or closure claim.

| Field | Value |
|---|---|
| owner/session | VAL Wegener / `01a089a3-2ca7-7642-8c16-e2904d9f7afa` |
| route | `gpt-5.6-luna`, reasoning `high`, fallback `OFF` |
| worktree | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val` |
| branch | `codex/s12-lc3-luna-val` |
| parent | `5384e36d08c1c22be7cd9f99d0e2eef8ec68f933` |
| runtime lanes | `C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\VAL-f03-correction-3` and `...\VAL-f03-correction-4` |

## Candidate red and local pre-fix boundary

The independent candidate finite run at merged commit `5384e36` reported
`81 passed, 2 failed, exit 1`. The failed nodes were:

```text
tests/s12/s12-lc3-val/test_r3_publication_boundaries.py::test_r3_s05_actual_worker_child_kill_then_fresh_worker_converges
tests/s12/s12-lc3-val/test_r4_correction_boundaries.py::test_r4_f02_actual_worker_kill_after_final_then_fresh_process
```

The reported root trace was `_publish_candidate_exclusive` using
`os.open(str(temporary))`, `candidate.open`, and `os.link(temporary, final)`;
the deep runtime path raised `FileNotFoundError` before final publication.
This is preserved as candidate red evidence. A local pre-fix run in the
shorter `VAL-f03-correction-2` lane passed those two nodes (`2 passed, 4
warnings, 16.56s`), so it is not claimed as a reproduction of the longer
candidate path.

## Bounded correction

Only `app/services/s12_export/publication.py` changed. The existing
`_native_fs_path` conversion is now used for every filesystem operation in
`_publish_candidate_exclusive` that touches the candidate, private temporary,
or public final: exclusive `os.open`, candidate read, exclusive `os.link`,
and owned temporary cleanup. The hard-link primitive, candidate/final inode
separation, preflight, and R4 recovery protocol are unchanged.

Working source SHA-256 before commit:

```text
7c8180ca63c2ac5620fbd70c43886c047260137e1ab8dd7f0a86bab7595fca9b  app/services/s12_export/publication.py
```

## Post-fix micro

Exact command:

```text
C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe -m pytest -q --basetemp=C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\VAL-f03-correction-3\pytest tests/s12/s12-lc3-val/test_r4_correction_boundaries.py tests/s12/s12-lc3-val/test_r3_publication_boundaries.py::test_r3_s04_space_unicode_companions_remain_addressable tests/s12/s12-lc3-val/test_r3_publication_boundaries.py::test_r3_s05_actual_worker_child_kill_then_fresh_worker_converges -s
```

Result: `7 passed, 14 warnings, exit 0`, `20.50s`. Raw markers:

```text
R4_MICRO_POST_FINAL status=completed recovered=True sha256=ef28e8b6950395522f5d0acef690f77909a289e14f4b71f648b33ba61adb29ef sidecar=True receipt=True
R4_MICRO_TEMP_PREFLIGHT final_exists=False sidecar=False receipt=False
R4_FOREIGN_INTENT final=False intent_unchanged=True candidate=False
R4_TAMPERED_INTENT final=False intent_unchanged=True candidate=False
R4_F02_WORKER_KILL killed_pid=24132 chunk_count=2 claimed=1 requeued=1 job_state=completed run_status=completed intent=False
R3_S05_WORKER_E2E killed_pid=27228 chunk_count=2 claimed=1 job_state=completed run_status=completed
```

The actual worker final paths were:

```text
C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\VAL-f03-correction-3\pytest\test_r4_f02_actual_worker_kill0\r4-worker-e2e\final.mp4
C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\VAL-f03-correction-3\pytest\test_r3_s05_actual_worker_chil0\worker-e2e\final.mp4
```

Both final SHA-256 values were
`fd19749bb00a68052a27cf521380943c293dc80cec95401fc23bd00aabfad1c7`.
R4 stage stdout/stderr was retained under
`...\test_r4_f02_actual_worker_kill0\r4-worker-e2e\stage{1,2}.{stdout,stderr}.log`.
The owned children were terminated/reaped and no child remains.

## Full finite gate and static checks

Exact full finite command:

```text
C:\Users\Admin\AppData\Local\Programs\Python\Python311\python.exe -m pytest -q --basetemp=C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\VAL-f03-correction-4\pytest tests/s12/s12-lc3-val tests/s12/s12-t03c/test_publication.py tests/s12/s12-t04a/test_c2_source_locked.py --tb=short
```

Result: `83 passed, 74 warnings in 76.19s`, exit `0`.

The exact affected-path compileall command exited `0`. Ruff
`--select F,I` over the exact VAL production/test paths exited `0` with
`All checks passed!`. `git diff --check` exited `0` with only Git's
non-failure LF-to-CRLF working-copy warning for `publication.py`.

The post-write-set guard uses
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r4-owner-submission\20260911T195310Z\val-baseline-r4.json`,
allows only `app/services/s12_export/publication.py`, and writes
`docs/pm/sessions/S12-LC3-VAL/evidence/20260912T-post-guard-r4-f03-publish.json`.
Final result: `VERIFIED`, `9 entries`, `0 failures`. The prior untracked
`work/` tree remains byte-for-byte preserved and unstaged.

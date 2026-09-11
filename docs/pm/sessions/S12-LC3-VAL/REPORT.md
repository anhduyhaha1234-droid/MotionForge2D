# S12-LC3-VAL completion evidence

This report records the bounded VAL implementation and verification on branch
`codex/s12-lc3-luna-val`. It is not an approval or a closure decision.

## Scope

Only the VAL allowlist was changed: the five permitted production files, the
permitted T04A/T03C tests, the new `tests/s12/s12-lc3-val/` regressions, and
this session evidence. No API, schema, frontend, persistence, packaging,
migration, global configuration, or other worktree files were changed.

## R01 audio and publication

Transcode audio now uses two independent ffmpeg decoders and bounded 8192
sample windows. Numpy vectorized measurements cover channel-preserving
waveform correlation, broadband spectral cosine similarity, relative RMS
error, all windows, sample counts, and one-source-frame timing drift. The
documented AAC acceptance bounds are correlation >= 0.80, spectral cosine >=
0.85, and relative RMS error <= 0.40 for every content-bearing window.
Remux/copy remains decoded-content digest checked. Missing audio, wrong tone,
silence, stereo channel swap, and swapped track mapping fail. A valid AAC
re-encode passes.

The real publication-path wrong-audio test used these raw paths:

```text
root:    C:\Users\Admin\AppData\Local\Temp\pytest-of-Admin\pytest-988\test_publish_real_wrong_audio_0
source:  C:\Users\Admin\AppData\Local\Temp\pytest-of-Admin\pytest-988\test_publish_real_wrong_audio_0\src_audio.mp4
wrong:   C:\Users\Admin\AppData\Local\Temp\pytest-of-Admin\pytest-988\test_publish_real_wrong_audio_0\wrong_audio.mp4
scratch: C:\Users\Admin\AppData\Local\Temp\pytest-of-Admin\pytest-988\test_publish_real_wrong_audio_0\scratch
public:  C:\Users\Admin\AppData\Local\Temp\pytest-of-Admin\pytest-988\test_publish_real_wrong_audio_0\out.mp4
```

It exited `0`, passed `1` node in `4.18s`, left the run failed, left no
public output, and left no private scratch candidate.

## R03 bounded validation and resources

Cross-raster PSNR uses native ffmpeg `psnr` statistics with `-reinit_filter
0`, fit+pad alignment, strict ordered frame numbers, and one bounded stats
file. It no longer materializes a full-clip raw file or uses a Python
per-byte hot loop. Decoder nonzero exit, malformed/truncated input, short
read, timeout, cancellation, and stats cleanup fail closed. Runner ffmpeg
children are polled, killed on cancellation/deadline, waited, and reaped.

The fresh scaling node used this owned raw root:

```text
C:\Users\Admin\AppData\Local\Temp\pytest-of-Admin\pytest-987\test_r03_resource_scaling_is_b0
```

The exact scaling output was:

```json
{"measurements": [{"duration_sec": 0.038642, "frames": 4, "free_disk_after": 537298477056, "free_disk_before": 537298477056, "scratch_bytes": 0}, {"duration_sec": 0.038014, "frames": 8, "free_disk_after": 537298460672, "free_disk_before": 537298460672, "scratch_bytes": 0}, {"duration_sec": 0.040601, "frames": 16, "free_disk_after": 537298440192, "free_disk_before": 537298440192, "scratch_bytes": 0}], "peak_ffmpeg_rss_bytes": 20000768}
```

Resource node argv was:

```text
python -m pytest tests/s12/s12-lc3-val/test_r01_r03_r04_boundaries.py::test_r03_resource_scaling_is_bounded_and_recorded -q -s
```

cwd was `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val`, start
UTC `2026-09-10T07:11:56.6961691Z`, end UTC
`2026-09-10T07:12:03.7568779Z`, exit `0`. The timing series is a bounded
4/8/16-frame measurement, not a 30-minute run; any 30-minute arithmetic would
be extrapolation only. It observed zero post-run scratch bytes, actual free
disk on the owned temp volume, and 20,000,768 bytes peak ffmpeg RSS. No TB
allocation or full-clip raw buffer was used.

## R04 cleanup and C17/C18

Stitch, runner, workflow, and publication failure paths remove only known
private/partial children under the owned scratch/chunk roots. Completed
consumer chunks and successful public output are preserved. Publication
rechecks the fence immediately before rename; rename, sidecar, and CAS
transition faults do not strand an unpublished artifact. The five fault
boundary nodes for fence loss, rename, sidecar, transition, and real wrong
audio all passed.

C09 was exercised only through the mechanisms present in this VAL scope:
legitimate exact-reference/remux behavior, documented PSNR profile tolerance,
cross-raster fit+pad, explicit VFR rejection, reorder negatives, and missing
threshold/reference fail-closed controls. No separate C09 mechanism required
an out-of-allowlist change.

## Verification commands

Full affected test command, exact cwd:

```text
python -m pytest tests/s12/s12-t04a tests/s12/s12-t03c tests/s12/s12-lc3-val -q
```

HEAD before the final command was
`577e9a3eab0ff7b9efd95bf2cecdf2d79e759a59`. Start UTC
`2026-09-10T07:15:53.1124466Z`; end UTC
`2026-09-10T07:17:14.0242800Z`; wall duration `80.9118334s` (pytest reported
`79.51s`); exit `0`; `134 passed, 87 warnings`.

Static checks:

```text
python -m compileall -q [all affected VAL production/test paths]  -> 0
python -m ruff check --select F [all affected VAL production/test paths] -> 0
git diff --check -> 0
```

The supplied baseline guard was run against the current worktree. Its full
post-state is [20260910T071125Z-post-guard.json](evidence/20260910T071125Z-post-guard.json).
All changed entries are within the allowlist; baseline authority files not
owned for modification are unchanged. The unrelated untracked `work/` cache
was preserved and is not committed.

## Final state

No unlisted production fix was required. The exact local commit is recorded
after the guard and final status checks in the task response.

## Correction follow-up

QA Q1 found that the prior commit accidentally left `ExportRunner.code_for`
under the top-level cleanup helper. The correction moved only that method back
inside the class. The four reported T03B nodes passed, `hasattr(ExportRunner,
"code_for")` passed, the VAL focused suite passed, and the correction evidence
is [20260910T075450Z-code-for-correction.md](evidence/20260910T075450Z-code-for-correction.md).

## C3 R1 exact-owner continuation

This continuation started from `91bf577a2706a3351f7a72f9142fbd7b9c5671c3`
in the same worktree. The only additional production correction was to pass
the attempt/fence-owned scratch child into `RunnerConfig`; assembly
temporaries therefore remain under the current owner root. No persistence
file was changed. The new regression file is
`tests/s12/s12-lc3-val/test_r1_correction_boundaries.py`.

The first three R1 reproductions were intentionally run before the repair and
are retained as red evidence: `R01_STALE_CLEANUP` reported
`candidate_exists:false`, `R02_COMMIT_GAP` reported a public file but retry
refused overwrite, and `R03_AUDIO_DEADLINE` took `2.031s` for a `0.1s`
deadline; that run was `3 failed, 4 warnings` in `6.81s`. After the repair,
the same three nodes passed with the current-owner candidate preserved,
commit-gap reconciliation to `completed`, and deadline completion in about
`0.125s`. The expanded R1 micro set passed all `10` nodes, including the
actual broadband-plus-tone AAC control, tampered receipt preservation,
stderr-pressure/nonzero decoder, cancel, and deadline controls.

The explicit correction command passed `21` nodes (`4` T03B nodes plus all
`17` VAL nodes) with `18` warnings in `21.72s`; `hasattr(ExportRunner,
"code_for")` returned `HAS_CODE_FOR=1`. Its envelope was:

```text
start_utc=2026-09-10T10:51:53.8761151Z
end_utc=2026-09-10T10:52:17.8332407Z
duration_sec=23.954662 pytest=0 code_for=0
```

The full scope-qualified gate also passed all `102` nodes with `92` warnings
in `96.08s`; the corrected rerun envelope was:

```text
start_utc=2026-09-10T10:50:02.3699793Z
end_utc=2026-09-10T10:51:40.1403402Z
duration_sec=97.7677313 exit=0
```

The ambient affected command was run separately and remains `174 passed,
2 failed, 141 warnings in 135.81s`. The two preserved red nodes are
`tests/s12/s12-t03c/test_export_jobs_api.py::test_retry_after_cancel_converges`
(`export context is not current; retry rejected`) and
`tests/s12/s12-t03c/test_s12_t03c_c1_closure.py::test_c15_retry_converges_no_duplicate_successor`
(`S12_EXPORT_STALE_CHECKPOINT: retry context changed`). Both are outside
the VAL-owned write set; no QA-owned file was changed.

The owned resource root was
`C:\\Users\\Admin\\mfqa\\s12-lc3-r1\\20260910T101656Z\\VAL`. The latest
native ffmpeg validator scaling sample covered every frame at `4`, `8`, and
`16` frames using `96x54` candidate versus `64x36` reference. It measured
peak stats scratch `1788` bytes and peak validator ffmpeg RSS `32841728`
bytes, with zero scratch bytes after each sample. The free-disk readings
were `535401996288 -> 535401992192`, unchanged for the 8-frame sample, and
`535401975808 -> 535401955328` bytes for the 16-frame sample. The ffmpeg
version was `8.1.2-full_build-www.gyan.dev`. These are bounded small-sample
measurements; any 30-minute arithmetic is extrapolation only.

The publication receipt records run lineage, attempt, fence,
checkpoint/manifest/plan/profile identity, candidate/artifact SHA-256, PASS
probe names, and sidecar identity. A fresh session adopts only a receipt
whose bytes, sidecar, current readiness, current raw lease, and fresh
source-locked validation all match. Rename, sidecar, SQLite commit, lost
acknowledgement, authority handoff, and tampered-output paths preserve the
immutable winner and never perform an unchecked overwrite. Filesystem
operations and SQLite commit are intentionally documented as a boundary, not
falsely described as one transaction.

The complete command envelopes and raw repro summaries are in
[20260910T1052Z-r1.md](evidence/20260910T1052Z-r1.md) and the mirrored
external evidence set. The post-write-set guard is [20260910T1057Z-post-guard-r1.json](evidence/20260910T1057Z-post-guard-r1.json).
This is a transport checkpoint only, not an approval or closure claim.

## C3 R2 exact-owner continuation

This R2 continuation used route `gpt-5.6-luna`, high reasoning, fallback OFF,
in the frozen VAL worktree at `7dfbca84456501c3a995490e98741604d149aabf`.
The route was not changed or substituted. Existing R1 work and the pre-existing
58-file, 1,073,079-byte `work/` tree were preserved.

The first R2 micro reproduced both defects against the real publication path:
the stale participant overwrote the winner and a foreign sidecar was replaced
(`1 failed` overall, exit `1`). The repair uses exclusive hard-link creation
for the final, sidecar, and receipt files. A pre-publication rendezvous lets A
pause after its fence check; B expires/reclaims the same run with a real
repository claim and completes; A then receives typed `PublicationRaceLost`.
The winner's final/sidecar/receipt bytes, SHA-256 values, sizes, mtimes, run
row, and job row remain unchanged; A's private candidate remains untouched.
There is no overwrite-capable final rename in this race boundary.

The owned R2 probes passed:

- `test_r2_f01_real_handoff_cannot_overwrite_winner`: two live threads and
  separate sessions, expiry/reclaim, exclusive primitive, immutable winner,
  typed loser, durable row/file identity.
- `test_r2_f02_foreign_companion_is_not_overwritten`: foreign sidecar is
  preserved and candidate cleanup is owner-scoped.
- `test_r2_f02_child_kill_fresh_process_reclaims_same_db_job`: an actual owned
  child process was terminated, a fresh Python process reopened the same
  isolated SQLite DB/job, reclaimed the expired lease, and retained chunk bytes.

The full allowed gate passed `73` nodes with `54` warnings, exit `0`, in
`58.516s` wall time (`57.30s` pytest):

```text
python -m pytest tests/s12/s12-lc3-val tests/s12/s12-t03c/test_publication.py tests/s12/s12-t04a/test_c2_source_locked.py -q --tb=short
cwd C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val
start 2026-09-10T13:02:23.7355887Z
end   2026-09-10T13:03:22.2514259Z
exit  0
```

Compileall, Ruff F, and `git diff --check` all passed after one test-only
F811 correction. The bounded native resource sample covered 4/8/16 frames,
reported peak ffmpeg RSS `19,988,480` bytes, zero post-run scratch bytes, and
actual free disk readings. It is a small bounded scaling measurement only;
there is no whole-tree or 30-minute capacity claim, and any longer arithmetic
would be extrapolation.

The R2 raw envelopes, process/reaping result, resource sample, preserved red
micro, and cleanup boundary are in
[20260910T1305Z-r2.md](evidence/20260910T1305Z-r2.md). The pre-commit
baseline guard is [20260910T1305Z-post-guard-r2.json](evidence/20260910T1305Z-post-guard-r2.json)
and passed with all baseline entries present, no destructive shrink, and only
the allowlisted existing files changed. The exact-owner R2 result is a local
transport checkpoint only; it is not an approval or closure claim.

## C3 R3 exact-owner continuation

R3 continued in the reviewed VAL worktree at
`a9d350d7ac686af118ff4de35c41023cec70406f` with the requested
`gpt-5.6-luna/high/fallback-OFF` route unchanged. The pre-existing untracked
`work/` tree remained byte-for-byte unchanged at 58 files and 1,073,079 bytes.
The required design note and finite anti-omission matrix are
[20260911T-r3-design-matrix.md](evidence/20260911T-r3-design-matrix.md).

The bounded R3 publication changes are in `publication.py`: distinct private
candidate/public-final inodes through owner-scratch copy plus exclusive link,
typed companion-path preflight before public mutation, and fail-closed
pre-receipt recovery requiring matching candidate/sidecar hashes, distinct
inode identity, current readiness/fence, and fresh source-locked validation.
The actual worker E2E test reached the real publication boundary, killed and
reaped the owned child, then recovered the same SQLite job/run in a fresh
process while retaining chunks. Existing owned R1/R2 controls remain in the
finite gate; no persistence, workflow, API, UI, schema, or other owner files
were changed.

The final allowed gate was 78 passed with 64 warnings and exit 0. Exact
commands, UTC envelopes, raw markers, resource measurements, and preserved
red harness attempts are in
[20260911T041253Z-r3.md](evidence/20260911T041253Z-r3.md). Static checks were
compileall 0, Ruff F/I 0, and diff-check 0. The final supplied baseline guard
is [20260911T041253Z-post-guard-r3.json](evidence/20260911T041253Z-post-guard-r3.json).
This is a local transport checkpoint only, not an approval or closure claim.

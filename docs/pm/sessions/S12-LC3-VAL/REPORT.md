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

## Post-integration import compatibility correction

The independent integrated candidate at
`17fa931c76bcffb6be5148531d786d2f6e745c41` exposed collection failure because
the RETRY transfer removed `tests/s12/s12-t03c/test_export_jobs_api.py` while
T03C publication still imported that module as `base`. The live VAL branch
remained at the authorized parent `ad0bf034fc218cc3d95cbf6b2e80c84eff89979f`
and therefore could not reproduce that red locally; its pre-fix finite command
was green with the old helper present.

The bounded fix changes only
`tests/s12/s12-t03c/test_publication.py`: when present, the explicit sibling
`tests/s12/s12-lc3-retry` path is prepended before the unchanged helper import.
No RETRY file, test body, assertion, production path, or unlisted owner path
was changed. The R3 boundary micro passed 5 nodes; the exact full allowed
matrix passed 78 nodes with 64 warnings; compileall, Ruff F/I, and diff-check
passed. Full command envelopes and the honest pre-fix distinction are in
[20260911T1342Z-import-compat-correction.md](evidence/20260911T1342Z-import-compat-correction.md).
The final baseline post-guard is
[20260911T1342Z-post-guard.json](evidence/20260911T1342Z-post-guard.json).
This is a local transport correction only, not an approval or closure claim.

## C3 R4 exact-owner continuation

### F03 deep space/Unicode companion correction

The independent finite candidate reproduced a real `FileNotFoundError` when
the sidecar temp companion was created below a deep path containing spaces and
Unicode. The bounded correction changes only
`app/services/s12_export/publication.py`: Windows native filesystem calls now
use the extended path form when needed. Actual companion-temp preflight,
component fencing, R4 recovery, and inode isolation remain intact.

The post-fix R4 plus Unicode/deep-path micro passed `6` nodes; VAL-only passed
`30`; and the full allowed VAL/T03C/T04A gate passed `83` with `74` warnings,
exit `0`, in `75.00s`. Compileall, Ruff F/I, and diff-check passed. Exact raw
commands, paths, markers, and guard output are recorded in
[20260912T1502Z-r4-f03-correction.md](evidence/20260912T1502Z-r4-f03-correction.md).
This is a local transport correction only, not an approval or closure claim.

The candidate then exposed a second F03 gap in the full publisher path:
`_publish_candidate_exclusive` still passed raw long paths to `os.open`,
candidate reads, `os.link`, and temp cleanup. The bounded follow-up changes
only that function to use the existing `_native_fs_path` helper at all four
filesystem boundaries. The R4/R3 worker-boundary micro passed `7` nodes and
the full allowed finite gate passed `83` nodes with `74` warnings, exit `0`,
in `76.19s`. Evidence is
[20260912T-r4-f03-publish-correction.md](evidence/20260912T-r4-f03-publish-correction.md).
This is a local transport correction only, not an approval or closure claim.

This R4 correction resumed the existing VAL owner/session from
`acd2fd69c3bf48e4f4bf503cbb15d9bb1430c275` and preserved the pre-existing
untracked `work/` tree. The finite design and anti-omission matrix were locked
before editing in [20260912T-r4-design-matrix.md](evidence/20260912T-r4-design-matrix.md).

The bounded production correction is only in `app/services/s12_export/publication.py`.
It adds a durable identity-bound publication intent before the exclusive final
link, validates final/sidecar/receipt/intent temporary companion paths before
public mutation, exposes the real post-final/pre-sidecar fault seam, and
recovers a missing sidecar/receipt only from intact same-run private candidate
proof plus current readiness/fence and fresh source-locked PASS. Foreign,
malformed, tampered, missing, and aliased intent/candidate proof fails closed.

The new owned test is
`tests/s12/s12-lc3-val/test_r4_correction_boundaries.py`. Its real worker test
killed an owned publisher child after final creation and before sidecar, then a
fresh process reclaimed the same SQLite job/run. The final SHA-256 was
`fd19749bb00a68052a27cf521380943c293dc80cec95401fc23bd00aabfad1c7`; two
chunks retained their bytes and mtimes; sidecar/receipt were rebuilt and the
intent was removed after convergence. Raw paths and markers are in
[20260912T-r4.md](evidence/20260912T-r4.md) under the mandated contained
runtime lane.

The final contained-runtime gate passed `83` nodes, `74` warnings, exit `0`,
in `81.57s`. Compileall, Ruff F/I, and diff-check exited `0`. The supplied
R4 baseline guard first rejected the changed protected production file without
an allowance, then passed with only
`app/services/s12_export/publication.py` allowed: `9` entries, `0` failures.
This is a local transport checkpoint only, not an approval or closure claim.

## C3 R5 F02 exact-owner continuation

The same VAL owner resumed on `codex/s12-lc3-luna-val` at
`e9a1686df7c740934c6fa8e12e23e1597f04856f`, with the accepted route
`gpt-5.6-luna / high / fallback OFF`. No other production path changed.

The fresh before-red used an actual publisher subprocess: it established an
attempt-bound durable intent, created the final, and exited at the
post-final/pre-sidecar seam. A second process recovered the same run. The
separate synthetic unowned same-byte final+candidate+sidecar negative exposed
the defect (`DID NOT RAISE PublicationError`): current code inferred ownership
without an intent or receipt. The production fix now requires a present
intent matching run/project/attempt/output/content and its candidate digest
before pre-receipt recovery. Readiness and current-fence checks remain before
writing the sidecar/receipt or completing the run.

After repair, both F02 micro nodes passed. The real positive retained
completion, final hash, and distinct candidate/final inode assertions and
recovered in a second process; the unowned negative preserved DB status,
final/sidecar bytes and inodes, and absent intent/receipt. The full allowed
VAL/T03C publication/T04A source-lock finite gate passed `84` nodes with `76`
warnings, exit `0` in two runs; the measured repeat took `78.726475s`.
Compileall, Ruff F/I, and diff-check passed. Detailed
commands, raw markers, hashes, and the post-guard are recorded in
[20260912T1708Z-r5-f02-publication-recovery.md](evidence/20260912T1708Z-r5-f02-publication-recovery.md)
and the fresh external lane evidence.

Protected migration/model/T03A test files were not edited. The exact
pre-existing untracked `work/` tree was not cleaned or staged and is checked
against the manager snapshot in
[20260913T-post-guard-r5-f02.json](evidence/20260913T-post-guard-r5-f02.json).
The guard reports `VERIFIED`, `103` entries, `0` failures, including the
protected files and `work/`. This is a local transport checkpoint only, not
an integration, approval, or closure claim.

## R6 correction — F02 foreign-inode adoption / F03 stale-owner publication

Verdict carried in: CHANGES_REQUESTED (R5 F02, F03). Both mechanisms are
corrected on `app/services/s12_export/publication.py` from wave base
`83af5167e9dddc931bc8590f547684c0c811784b`.

**F02 — the fix.** Publication ownership is now proven by durable inode
identity, never by SHA equality or by a prewritten intent alone. The
publisher stages a private copy of the validated candidate before the seam
and records the staged inode's identity (volume + file index + size +
mtime) in the intent *before* the exclusive link; the receipt records the
published inode's identity; and every recovery path (pre-receipt companion
rebuild, full receipt reconciliation) adopts the public file only when its
inode provably equals that recorded identity. A byte-equal foreign copy is
a different inode — adoption, receipting and completion are denied and
nothing foreign is deleted, moved or rewritten (V02–V05; the reviewer's own
reproduction `test_foreign_final_arrives_after_real_intent_must_not_be_adopted[False/True]`
now passes). All four genuine own-crash windows still converge to the exact
1 Run / 1 Job pair (V06), as do commit-failure and lost-ack (V07) and a
killed real publisher process converged by a fresh process (V08).

**F03 — the fix.** The public mutation is serialized by a real
cross-process publication lock (`_PublicationGuard`: `msvcrt` byte-range
lock on Windows / `flock` elsewhere, on `<final>.publication.lock`) held
across ownership re-validation → intent → exclusive creation →
sidecar/receipt → fenced transitions. Under the release-A-first schedule the
expired participant is re-validated *inside* the lock and denied with a
typed fence-loss error — it performs no public publication at all — while
the current owner completes with its own bytes; the B-first control passes;
both live participants are joined and reaped with recorded PIDs/timeline
(V09–V11, including the equal-bytes case where ownership is independent of
SHA). The reviewer's handoff reproduction
(`test_lease_handoff_at_final_primitive_never_publishes_stale_owner[B/A]`)
now passes in both release orders.

**Compatibility and bounds.** `_publish_candidate_exclusive` keeps its exact
two-argument call shape (the staged path travels via a thread-scoped
contextvar), so the immutable t03c harnesses and the reviewer probes re-ran
unchanged; `tests/s12/s12-t03c/test_publication.py` is byte-identical
(`50b139bc…`, no edit). One bounded lane-test patch (`+4/-2`,
`test_r2_ownership_recovery.py`) updates the stale-loser expectation to the
new typed denial while keeping every zero-mutation and winner-identity
assertion. The lock file is an empty coordination artifact (never read as
data) and is validated in path preflight before any public write.

**Results.** New frozen V01–V15 nodes in
`tests/s12/s12-lc3-val/test_r6_publication_ownership.py`; VAL lane full run
`59 passed` (119.06s) exit 0; t03c module `20 passed`; affected t03c-extras
+ T04A `89 passed`; R5 reviewer probes re-run `4 passed`; Ruff `--select F`
clean with exactly the 4 inherited full-ruleset findings left explicit (no
compatibility-breaking exception rename). Raw per-command ledger, per-case
JSON and stdout/stderr are retained in the lane evidence directories; design
and identity detail in
[20260915T-r6-f02-f03.md](evidence/20260915T-r6-f02-f03.md). Open: human
playback and the public product chain remain NOT_REVIEWED / outside this
correction (QA/INT scope). This remains a local transport checkpoint only,
not an integration, approval, or closure claim.

## R7 correction — F01: lease transfer serialized with the publication section

Verdict carried in: CHANGES_REQUESTED (F01, P1, owner VAL). Wave base
`35f6cb2f…` (ff-only from `535d7c13…`; untracked `work/` untouched).

**The defect and the fix.** F01 showed the filesystem lock serialized
publishers while `claim_run` did not participate in that serialization: a
lease transfer could complete after the publisher's last fence read and
before its actual exclusive link, letting a stale owner install
`stale-A-bytes` while the current owner got `PublicationRaceLost` — an
incoherent end state. The correction (frozen design D1) serializes the
ownership transition with the real filesystem mutation: a NEW per-run
cross-process lock (`publication_lease_guard.py`) is taken by `claim_run`
AND by the publisher's whole critical section (fence re-validation →
intent → exclusive create → lease extension → sidecar/receipt → fenced
transitions, plus both final-exists recovery branches). A claim arriving
while a section is active waits bounded then fails typed
(`PublicationInProgressError`, code `S12_T03C_PUBLICATION_IN_PROGRESS`,
`S12ExportError` subclass, zero mutation); a publisher entering its section
re-validates ownership first, so a claim that committed earlier is observed
there. Inside the held section the current owner extends its own lease
immediately before the transitions (`extend_lease_for_publication`,
token-CAS without an expiry predicate — only safe because claims cannot
interleave with the section), so the section's commits stay authorized even
when the wall-clock TTL lapsed mid-section. This is not "another fence
read": the entry read is the last read and the section it guards is
claim-proof end-to-end. Dead processes release their locks via the OS.

**Proof.** The reviewer's own F01 reproduction
(`test_review_r6_inner_fence.py`, copied hash-identically, assertions
unchanged) now passes: `final_bytes = current-B-bytes`, link-success
`['B']`, lease `review-inner-B v2`, all participants reaped (`1 passed,
18.28s`). New frozen nodes (8 nodes / 16 instances) cover: section-first
prevention with the owner completing (typed denial, zero mutation, then a
typed "cannot be claimed" refusal after completion); claim-first stale
entry denial with B as sole publisher; a claim attempt at EVERY public
mutation boundary (pre-link, post-link/pre-sidecar, post-sidecar/pre-receipt,
receipt/precommit); the cross-process equivalent (real publisher child,
typed denial from another process, child reaped); a real child killed
post-link with a fresh process converging on the child's own inode; the
expired/released/reclaimed token matrix; the ordering × bytes cross-product
(ownership independent of SHA; foreign equal-SHA never owned); and
lost-ack + mid-section stale cleanup with stable hash+inode+mtime. Full
affected sweep: `184 passed` (172.61s) exit 0; `ruff --select F` clean with
exactly the four inherited full-ruleset findings left explicit; guard
`VERIFIED` (122 entries, 0 failures) and `work/` 58/58 byte-identical to
the Manager snapshot.

**Cross-lane mapping correction (§3).** The prompt stated the route maps
`S12ExportError` to 409 at `s12_export.py:377–382` and that subclassing
alone would satisfy the mapping. Read-code evidence: no
`except S12ExportError` exists anywhere under `app/`; that route's 409
branches catch `S12ExportSubmitError` (a ValueError subclass) and
`IdempotencyConflictError` by name (submit path only — claims never flow
through it). The real claim path is worker-internal
(`s12_export_jobs.py:744`), where the durable worker classifies step
exceptions (`app/workflow/durable_worker.py:891–905`) into a typed
retryable failure envelope via `_fail_job`; `PublicationInProgressError`
takes that path with its code visible and, being an `S12ExportError`
subclass as frozen, stays compatible with any broad family handling. No
RETRY file was touched, and none is required for F01. Full raw evidence in
`evidence/20260916T-r7-f01.md` §3 and
`…/A/VAL/r7_g3_mapping_evidence.txt`.

# S12-LC3-VAL continuation log

This log is a transport record for the exact-owner C3 R1 continuation. It
does not grant approval or declare closure.

| UTC | Event | Result |
|---|---|---|
| 2026-09-10T10:43:23Z–10:45:02Z | scope-qualified gate before workflow correction | 102 passed, exit 0 |
| 2026-09-10T10:48:10Z–10:48:11Z | compileall, Ruff F, diff check | all exit 0 |
| 2026-09-10T10:50:02Z–10:51:40Z | scope-qualified gate after workflow correction | 102 passed, exit 0 |
| 2026-09-10T10:51:53Z–10:52:17Z | four T03B nodes + 17 VAL nodes + `code_for` surface | 21 passed, exit 0 |

Ambient affected evidence remains `174 passed, 2 failed, 141 warnings`; both
failures are the pre-existing QA retry nodes recorded in the R1 evidence.
The exact raw commands, outputs, resource record, and cleanup boundary are in
`evidence/20260910T1052Z-r1.md`.

| 2026-09-10T12:49:14Z–12:49:20Z | R2 pre-fix publication race/foreign companion micro | 1 failed, preserved red evidence |
| 2026-09-10T12:53:07Z–12:53:13Z | R2 exclusive-publication micro | 2 passed, exit 0 |
| 2026-09-10T13:00:54Z–13:01:02Z | R2 ownership/process micro | 3 passed, exit 0 |
| 2026-09-10T13:02:23Z–13:03:22Z | R2 full allowed VAL/T03C publication/T04A gate | 73 passed, 54 warnings, exit 0 |
| 2026-09-10T13:04:02Z–13:04:03Z | R2 compileall, Ruff F, diff check | all exit 0 |
| 2026-09-10T13:04:15Z–13:04:22Z | R2 bounded 4/8/16-frame resource scaling | 1 passed, exit 0 |
| 2026-09-10T13:05:17Z | R2 baseline-val-r2 pre-commit guard | PASS; no missing/shrink/protected change |

The complete R2 envelopes and raw summaries are in `evidence/20260910T1305Z-r2.md`.

| 2026-09-10T13:34:22Z–13:36:08Z | R2 static correction micros and exploratory exact-tree I001 scan | micros passed; four incidental older-test edits reverted |
| 2026-09-10T13:38:16Z–13:38:24Z | R2 static-correction final three micros | 3 passed, 6 warnings, exit 0 |
| 2026-09-10T13:38:34Z–13:38:35Z | Exact four-file compileall, Ruff F/I, diff-check | all exit 0 |

The correction evidence is `evidence/20260910T1339Z-static-correction.md`.

## C3 R3 exact-owner continuation

| 2026-09-11T03:55:14Z–03:56:00Z | R3 S01/S02/S04 micro, including one preserved test-harness red | corrected micro 4 passed, exit 0 |
| 2026-09-11T04:00:52Z–04:01:20Z | R3 S05 actual-worker micro harness corrections | import/lease-expiry harness reds preserved; no production red |
| 2026-09-11T04:09:28.7280619Z–04:10:34.9141286Z | R3 full allowed VAL/T03C publication/T04A gate | 78 passed, 64 warnings, exit 0 |
| 2026-09-11T04:10:44.7661323Z–04:10:44.9159277Z | R3 exact-path compileall, Ruff F/I, diff check | all exit 0 |
| 2026-09-11T04:11:50.2818279Z–04:11:57.7844019Z | R3 bounded native 4/8/16-frame resource sample | 2 passed, exit 0; peak scratch/RSS recorded |
| 2026-09-11T04:14:02.9049017Z–04:14:02.9802085Z | R3 baseline-val-r3 post-write-set guard | VERIFIED; 75 entries, 0 failures, exit 0 |

The complete R3 command envelopes, raw markers, process reaping, resource
limits, and preserved work snapshot result are in
`evidence/20260911T041253Z-r3.md`. The final supplied `baseline-val-r3.json`
post-write-set guard is recorded as
`evidence/20260911T041253Z-post-guard-r3.json`. This remains a local
transport checkpoint, not an approval or closure claim.

## Post-integration import compatibility correction

| 2026-09-11T13:38:01.7356854Z–13:39:07.6827296Z | Candidate-red command on live pre-transfer VAL checkout | 78 passed; integrated candidate collection red is preserved as external evidence |
| 2026-09-11T13:39:21.1680125Z–13:39:35.4314691Z | R3 boundary micro after sibling-path correction | 5 passed, 10 warnings, exit 0 |
| 2026-09-11T13:39:49.4743338Z–13:40:55.6460469Z | Exact full allowed VAL/T03C/T04A correction gate | 78 passed, 64 warnings, exit 0 |
| 2026-09-11T13:41:06.9903764Z–13:41:07.1489255Z | Compileall, Ruff F/I, diff check | all exit 0 |
| 2026-09-11T13:43:52.5950695Z–13:43:53.0252946Z | Initial R3 post-guard with incomplete allowance set | 2 previously landed VAL deltas reported; preserved red guard evidence |
| 2026-09-11T13:44:14.6288807Z–13:44:14.7066513Z | Corrected R3 post-guard with prior and current VAL allowances | VERIFIED; 75 entries, 0 failures, exit 0 |

The exact candidate collection red, bounded change, and post-fix envelopes
are in `evidence/20260911T1342Z-import-compat-correction.md`. The RETRY
transferred file was preserved. The first incomplete-allowance guard result
and final verified guard result are recorded in the correction evidence and
`evidence/20260911T1342Z-post-guard.json`. This remains a local transport
correction, not an approval or closure claim.

## C3 R4 exact-owner continuation

| 2026-09-12 | R4 design note and finite anti-omission matrix | recorded before source edit; existing owner/session and work/ preserved |
| 2026-09-12 | R4 pre-fix publication/path micro | 2 intended reds preserved: no post-final recovery seam; temp companion not preflighted |
| 2026-09-12 | R4 post-fix micro and retained R2/R3 boundary controls | green; foreign/tampered intent preserves marker and cleans only owner candidate |
| 2026-09-12 | R4 actual worker kill after final/pre-sidecar | 1 passed; child killed/reaped, fresh same-DB worker completed job/run, chunks unchanged |
| 2026-09-12 | R4 full contained-runtime VAL/T03C/T04A gate | 83 passed, 74 warnings, exit 0, 81.57s |
| 2026-09-12 | R4 compileall, Ruff F/I, diff-check | all exit 0 |
| 2026-09-12 | R4 baseline guard | initial no-allow rejection retained; final `VERIFIED`, 9 entries, 0 failures with publication.py only |

Exact commands, raw runtime paths, process markers, hashes, and guard files
are in `evidence/20260912T-r4.md`. This remains a local transport checkpoint,
not an approval or closure claim.

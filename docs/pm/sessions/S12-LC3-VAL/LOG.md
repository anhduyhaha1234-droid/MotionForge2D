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

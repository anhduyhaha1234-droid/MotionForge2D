# S12-LC3-QA — Q1 blocked status

Status: `BLOCKED_Q1_R1_AUTHORITY_GATE` — evidence checkpoint committed locally;
acceptance remains blocked.
This document records evidence only; it does not approve or close any row.

R1 continuation supersedes the earlier pre-VAL counts and public-probe
description below where noted. The QA allowlist/evidence checkpoint is local
only; no production/frontend file was edited.

The branch is now at VAL-corrected candidate
`91bf577a2706a3351f7a72f9142fbd7b9c5671c3` (fast-forward from
`7261b38322bf4d31c0d5329b0adfdbdabb7f7303`). The existing Q1 assertion edits
survived the fast-forward.

## Transport and collection

- Branch: `codex/s12-lc3-luna-qa`
- Fast-forward target: `91bf577a2706a3351f7a72f9142fbd7b9c5671c3`
- UI transport parent: `cf9ca6b67698601e0a02610d468ee6da3ad2b04d`
- VAL transport parent: `735c47ec58380bf25e7265ba52e3bb406e844f0b`
- Required collection command: exit `0`, `341` nodes, empty stderr.
- Raw collection evidence: `q1-collect-full.command.txt`,
  `q1-collect-full.stdout.txt`, `q1-collect-full.stderr.txt`,
  `q1-collect-full.exit.txt`.

## Checks run

`tests/s12/s12-t06b` passed `20`, skipped `1`; the skip is the existing
clean-machine hardware gate (`NOT_RUN`), not a new skip. The focused C08
and C28 runs passed (`2 + 2 + 3`). After the VAL correction, the four T03B
nodes passed, and the bounded R1 retry rerun reproduced only the two current
authority failures. The post-VAL full S12 suite was:

```text
338 passed, 1 skipped, 2 failed
```

Raw post-VAL evidence is in `q1-r1-suite-final.command.txt`,
`q1-r1-suite-final.stdout.txt`, `q1-r1-suite-final.stderr.txt`, and
`q1-r1-suite-final.exit.txt`. The earlier six-failure run remains historical
evidence in `q1-suite.*`.

## Blocking failures

1. `tests/s12/s12-t03c/test_export_jobs_api.py::test_retry_after_cancel_converges`
   and `tests/s12/s12-t03c/test_s12_t03c_c1_closure.py::test_c15_retry_converges_no_duplicate_successor`
   fail at the production retry route's current-authority checks
   (`export context is not current` / `S12_EXPORT_STALE_CHECKPOINT`). Their
   existing fixture creates the old lineage shape without a current Full
   Apply authority. Changing the expected 409 to green would weaken the
   retry acceptance; fabricating completed authority with SQL is prohibited.

The original six-failure traceback is in `q1-suite.stdout.txt`; the final
post-VAL retry traces are in `q1-r1-retry-current-final.stdout.txt`.

## VAL correction rerun

The transported VAL correction restored the `ExportRunner.code_for` contract;
the four affected T03B nodes were rerun and passed (`4 passed`). The final
two-node retry rerun still failed at the production route's current-authority
checks; raw evidence is in `q1-val-correction-t03b.*` and
`q1-r1-retry-current-final.*`.

## Public API and bounded authority-route attempt

The final bounded probe used a fresh Alembic-migrated SQLite database, a real
decodable fixture, public durable project/video creation, the legacy 12-hex
create/upload/analyze path, and an explicitly started durable worker. The
legacy chain completed in the 10-second bound with one source artifact, one
proxy artifact, one scene, and three completed jobs. It then failed closed at
the S09/S10 authority prerequisites: config creation returned
`404 {"detail":"object role ownership mismatch"}`, the pack picker returned
an empty catalog, reapprove returned `404 ReskinConfig ... not found`, and
Full Apply returned `404 ApplyCheckpoint ... not found`. The v2 import path is
absent (`404 {"detail":"Not Found"}`), while the server-owned context for the
legacy-created video returned `200` with `S12_EXPORT_FULL_APPLY_MISSING` and
`S12_EXPORT_LOCK_MISSING`; export submit returned `409` with those reasons.

The complete route/identity/state/owner/mutation map is
`../PUBLIC_CHAIN_MAP.md`; the minimal upstream dependency proposal is
`../UPSTREAM_SCOPE_PROPOSAL.md`. Raw command, stdout, stderr, exit, and JSON
evidence are `q1-r1-public-legacy-worker-authority-final.*`. The probe records
`manual_sql_used: false`, and the rejected S12 submit left
`s12_export_runs == 0` and its pre-submit job count unchanged. This is not
normal-product export acceptance: the legacy source chain is positive source
evidence only; no Full Apply, S12 worker convergence, result, or media result
is claimed. The existing UI seed's direct-SQL completed authority remains
excluded.

## E2E boundary

The existing `frontend/e2e/s12-export-boot.py` invokes
`frontend/e2e/s12-export-seed.py`, which directly inserts completed
`s10_full_apply_run` and `s10_full_apply_publication` rows. That is not
valid Q1 normal-product evidence under the requested no-fabricated-
readiness/approved/completed rule, so Playwright was not counted or run
through that seed path.

## C01–C32 status map

`PASS` below means the mapped existing test evidence passed; it is not a
row approval. `PARTIAL` means only a mechanism or non-public path passed.
`BLOCKED` means the row is affected by the red suite or the required
normal-product evidence is unavailable. `NOT_ASSESSED` means no current
test/evidence mapping was present in this worktree.

| Row | Current evidence mapping | Q1 status |
|---|---|---|
| C01 | `tests/s12/s12-t03c/test_s12_t03c_c1_closure.py` | PASS |
| C02 | T01 preflight + T02 capability/profile tests | PASS |
| C03 | T01 provenance tests | PASS |
| C04 | T01 authority + T03C closure tests | PASS |
| C05 | T03C path/source denial tests | PASS |
| C06 | T03A replay identity tests | PASS |
| C07 | T03A identity-union/orphan tests | PASS |
| C08 | T03A barrier contention tests; typed loser repair focused green | PASS |
| C09 | T03A lease fencing tests | PASS |
| C10 | T03B runner 4K tests | PASS |
| C11 | T03B geometry/letterbox tests | PASS |
| C12 | T03B/T04A source-lock and timing tests | PASS |
| C13 | T03B chunk identity/resume tests; VAL-corrected four-node rerun green | PASS |
| C14 | T03B durable restart tests | PARTIAL; direct runner evidence only |
| C15 | T03C retry convergence test | BLOCKED by current-authority rejection |
| C16 | T03C durable job lifecycle tests | PASS |
| C17 | T03C publication fence tests | PASS |
| C18 | T03C atomic publication failure tests | PASS |
| C19 | T04A validator negative matrix | PASS |
| C20 | No current row-specific mapping found | NOT_ASSESSED |
| C21 | No current row-specific mapping found | NOT_ASSESSED |
| C22 | T03C scoped result/media tests | PASS |
| C23 | No current row-specific mapping found | NOT_ASSESSED |
| C24 | T06A manifest/endpoint denial tests | PASS |
| C25 | T06A process identity tests | PASS |
| C26 | T06B direct-handler real-media scenario | PARTIAL; readiness is stubbed |
| C27 | T06B direct-handler kill/restart scenario | PARTIAL; public API E2E unavailable |
| C28 | T06B real assembly + asserted audio authority mechanism | PARTIAL; public normal path unavailable |
| C29 | T06B hardware matrix | NOT_RUN on clean-machine gate |
| C30 | No current row-specific mapping found | NOT_ASSESSED |
| C31 | No current row-specific mapping found | NOT_ASSESSED |
| C32 | No current row-specific mapping found | NOT_ASSESSED |

## Guard and scope

The supplied R1 `baseline-qa-pre.json` and `baseline-qa-protected.json` were
verified after the final probe with `0` failures (`141` and `15` entries).
The final pre guard explicitly allowlisted this updated QA status document;
the protected guard remained unchanged and clean. Raw final guard evidence is
`q1-r1-guard-final-pre-allowdocs.*` and
`q1-r1-guard-final-protected.*`.
The existing Q1 guard also remains preserved. New raw evidence and session
docs are within the QA session scope; the only source changes are the
allowlisted C08/C28 assertion transport and the specifically named public
probe. No production/frontend file was edited by this worker.

Evidence: `q1-r1-guard-final-pre-allowdocs.report.json`,
`q1-r1-guard-final-protected.report.json`, `q1-r1-suite-final.*`,
`q1-r1-retry-current-final.*`, and
`q1-r1-public-legacy-worker-authority-final.*`.

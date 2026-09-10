# S12-LC3-QA — R1 C01–C32 evidence matrix

`PASS` is test evidence only; it is not row approval. `PARTIAL` means
mechanism/non-public evidence. `BLOCKED` means the current suite is red or
required normal-product evidence is unavailable. `NOT_RUN` is an environment
gate. `NOT_ASSESSED` means no row-specific current evidence was found.

| Row | Evidence mapping | R1 status |
|---|---|---|
| C01 | T03C closure | PASS |
| C02 | T01 preflight + T02 capability/profile | PASS |
| C03 | T01 provenance | PASS |
| C04 | T01 authority + T03C closure | PASS |
| C05 | T03C path/source denials | PASS |
| C06 | T03A replay identity | PASS |
| C07 | T03A identity union/orphans | PASS |
| C08 | T03A barrier contention; typed loser evidence | PASS |
| C09 | T03A lease fencing | PASS |
| C10 | T03B 4K runner | PASS |
| C11 | T03B geometry/letterbox | PASS |
| C12 | T03B/T04A source-lock/timing | PASS |
| C13 | T03B chunk identity/resume; four VAL correction nodes green | PASS |
| C14 | T03B durable restart mechanism | PARTIAL |
| C15 | T03C retry convergence; two current-authority failures | BLOCKED |
| C16 | T03C durable job lifecycle | PASS |
| C17 | T03C publication fence | PASS |
| C18 | T03C atomic publication failure | PASS |
| C19 | T04A validator negatives | PASS |
| C20 | No current row-specific mapping | NOT_ASSESSED |
| C21 | No current row-specific mapping | NOT_ASSESSED |
| C22 | T03C scoped result/media tests | PASS |
| C23 | No current row-specific mapping | NOT_ASSESSED |
| C24 | T06A manifest/endpoint denials | PASS |
| C25 | T06A process identity | PASS |
| C26 | T06B direct-handler real media; readiness stubbed | PARTIAL |
| C27 | T06B direct-handler kill/restart; public E2E unavailable | PARTIAL |
| C28 | T06B real assembly + asserted audio mechanism; public path unavailable | PARTIAL |
| C29 | T06B hardware matrix; clean-machine gate | NOT_RUN |
| C30 | No current row-specific mapping | NOT_ASSESSED |
| C31 | No current row-specific mapping | NOT_ASSESSED |
| C32 | No current row-specific mapping | NOT_ASSESSED |

Suite disposition: collection exit `0`, `341` nodes; full suite exit `1`,
`338 passed, 1 skipped, 2 failed`; the two failures are C15 retry cases.
Normal-product C26/C27/C28 and Q1c UI/E2E remain partial/blocked and were not
promoted by mechanism fixtures.


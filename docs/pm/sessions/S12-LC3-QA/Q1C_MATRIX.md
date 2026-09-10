# S12-LC3-QA — Q1c current-head C01–C32 evidence map

Candidate for this map: `codex/s12-lc3-luna-integration` at
`9f8e9fd0ffd318682313808b177bf711ad162739`. A status marked
`CARRY_FORWARD_ONLY` cites the committed R1 evidence at the prior candidate
head and is not a fresh Q1c pass. `PARTIAL` is bounded current evidence, not
row approval. `NOT_REASSESSED` means Q1c intentionally did not rerun that row.
No row is APPROVED or CLOSED.

| Row | Exact current/R1 evidence mapping | Q1c status |
|---|---|---|
| C01 | R1 T03C closure evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C02 | R1 T01/T02 evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C03 | R1 T01 provenance evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C04 | `q1c-public-chain-final.json`: public context `200`, non-ready reasons | PARTIAL |
| C05 | R1 T03C denials; no Q1c row run | CARRY_FORWARD_ONLY |
| C06 | R1 T03A replay evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C07 | R1 T03A identity evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C08 | R1 focused typed loser/barrier evidence; prior head only | CARRY_FORWARD_ONLY |
| C09 | R1 T03A fencing evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C10 | R1 T03B mechanism evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C11 | R1 geometry/letterbox evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C12 | R1 timing/source-lock evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C13 | R1 four-node VAL correction evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C14 | No current public committed-progress kill/restart proof | NOT_DEMONSTRATED |
| C15 | `evidence/q1c-retry-final.stdout.txt`, exit `1`, two exact retry nodes | BLOCKED |
| C16 | Q1c public legacy analyze chain: 3 jobs/2 artifacts completed | PARTIAL |
| C17 | R1 publication-fence evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C18 | R1 commit-failure mechanism evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C19 | R1 validator evidence; no Q1c row run | CARRY_FORWARD_ONLY |
| C20 | `q1c-ui-availability.*`: no `frontend/node_modules`; UI not run | NOT_RUN |
| C21 | `q1c-ui-availability.*`: no real UI recovery path reached | NOT_RUN |
| C22 | Q1c authority block; no result/media/playback reached | NOT_DEMONSTRATED |
| C23 | No Q1c packaging/stage gate run | NOT_REASSESSED |
| C24 | No Q1c package hash/dependency gate run | NOT_REASSESSED |
| C25 | `q1c-process-final.*`: no QA-owned process after probe | PARTIAL |
| C26 | Q1c context missing Full Apply/lock; no normal export | BLOCKED |
| C27 | No same-job public crash/expiry/restart reached | BLOCKED |
| C28 | No normal-product audio result; R1 mechanism only | BLOCKED |
| C29 | Clean-host/human gate remains external | NOT_RUN |
| C30 | No Q1c retained-data migration gate run | NOT_REASSESSED |
| C31 | `q1c-collection-final.*`: 351 nodes collected, no full suite | PARTIAL |
| C32 | Frozen candidate/head and QA evidence only; no closure gate | PARTIAL |

Totals: `CARRY_FORWARD_ONLY=15`, `PARTIAL=5`, `BLOCKED=4`,
`NOT_DEMONSTRATED=2`, `NOT_RUN=3`, `NOT_REASSESSED=3` = 32 rows.

# S12-LC3-QA — R2 C01–C32 evidence map

Candidate: `codex/s12-lc3-luna-qa` at
`7dfbca84456501c3a995490e98741604d149aabf`. Route: `gpt-5.6-luna`, high,
fallback OFF. `CARRY_FORWARD_ONLY` is historical evidence, not a fresh R2
pass. `PARTIAL` is bounded evidence, not row approval. `BLOCKED` and `OPEN`
remain unresolved. No row or sprint is APPROVED or CLOSED.

| Row | Exact evidence mapping | R2 status |
|---|---|---|
| C01 | R1 T03C closure evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C02 | R1 T01/T02 capability/profile evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C03 | R1 T01 provenance evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C04 | R2 `q2/public-chain-v2-20260910T125705Z.json`: v2 context `200`, missing Full Apply/lock reasons | PARTIAL |
| C05 | R1 T03C denial evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C06 | R1 T03A replay evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C07 | R1 T03A identity/orphan evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C08 | R1 typed loser/barrier evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C09 | R1 T03A lease fencing evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C10 | R1 T03B 4K mechanism evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C11 | R1 geometry/letterbox evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C12 | R1 source-lock/timing evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C13 | R1 four VAL correction nodes; VAL-owned bytes not touched | CARRY_FORWARD_ONLY |
| C14 | No R2 public committed-progress kill/restart proof | NOT_DEMONSTRATED |
| C15 | R2 `q1-micro/rerun-retry-fixed-isolated-20260910T125324Z.json`, exit `1`; both retry nodes reach the frozen route and fail on unique natural-key replay | BLOCKED |
| C16 | R2 public legacy chain: actual IDs, three completed durable jobs, two artifacts, `scenes_count=1` | PARTIAL |
| C17 | No R2 normal-product publication fence; prior mechanism evidence is not promoted | OPEN / NOT_DEMONSTRATED |
| C18 | No R2 normal-product atomic publication failure; prior mechanism evidence is not promoted | OPEN / NOT_DEMONSTRATED |
| C19 | R1 T04A validator evidence; no R2 row run | CARRY_FORWARD_ONLY |
| C20 | No valid authority for real export UI; UI not run | NOT_RUN |
| C21 | No valid authority for reload/recovery UI flow; UI not run | NOT_RUN |
| C22 | R2 public submit stopped at 409; no result/media/playback; R1 mechanism fixture remains separate | NOT_DEMONSTRATED |
| C23 | No R2 packaging/stage gate run | NOT_REASSESSED |
| C24 | No R2 package hash/dependency gate run | NOT_REASSESSED |
| C25 | R2 probe started/stopped its durable worker; final process review recorded in R2 log | PARTIAL |
| C26 | No normal-product Full Apply/export; direct-SQL/readiness-stub evidence excluded | BLOCKED |
| C27 | No normal-product cancel/expiry/restart reached after authority block | BLOCKED |
| C28 | No normal-product audio media; R1 mechanism-only audio evidence retained | BLOCKED |
| C29 | Clean-host/human playback gate remains external and not run | NOT_RUN |
| C30 | No R2 retained-data migration gate run | NOT_REASSESSED |
| C31 | R2 `checks/collection-full-tree-20260910T130000Z.json`: `python -m pytest tests/s12 --collect-only -q -p no:cacheprovider`, `351 tests collected`, exit `0` | COLLECTION_ONLY |
| C32 | Candidate/head, allowlist, evidence hashes and no-production scope recorded; no closure gate | PARTIAL |

## Open findings

`C17`, `C18`, `F01`, and `F02` remain open. The R2 public probe is positive
only for the legacy source-ingest/durable worker chain. It does not
demonstrate normal S12 export, publisher/result/media, UI, playback, or
download. The two C15 retry nodes remain red against frozen production and
are retained as regression evidence.

Current R2 disposition: `BLOCKED_Q1_RETRY_IDENTITY_AND_EXTERNAL_AUTHORITY`.
This matrix is evidence transport only; it does not approve or close any row.

Totals: `CARRY_FORWARD_ONLY=13`, `PARTIAL=4`, `BLOCKED=4`, `OPEN / NOT_DEMONSTRATED=2`,
`NOT_DEMONSTRATED=2`, `NOT_RUN=3`, `NOT_REASSESSED=3`, `COLLECTION_ONLY=1` = 32 rows.

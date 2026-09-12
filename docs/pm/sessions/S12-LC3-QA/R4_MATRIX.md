# S12 LC3-R4 QA evidence matrix

Owner/session: QA Goodall / `01a08991-c909-7d03-86ed-ac236d50c87b`.
Candidate baseline for the original packet: integration `17b33f53b27da58e3330dd4a8270706ac853d37a`;
QA checkpoint before R4 evidence: `ac49c9d4e40e6c3d3a5b3cad49f67d6f12a80cdd`.
Route: `gpt-5.6-luna`, reasoning high, fallback OFF. This is a 62-row evidence
map, not a pass count and not a closure decision.

## Final candidate transport audit

Audited candidate: integration `b6d71873dd1597f191b3ead95cb15e5aff73a722`
(clean). Ancestor checks are green for VAL merge
`86630450213f5ed399aa7cbcace0c671999d8b89`, RETRY merge
`0df6cf370d655445953480b56d4797bfddec560f`, and QA merge
`617f7e809f7feb8fda0b69a49c469cc751a2e749`. The four relevant merged-scope
checks were micro-first and green in a short isolated runtime: VAL `2/2`
micro and `3/3` finite; RETRY `4/4` micro and `9/9` finite. Deselected counts,
warnings, exits, and raw hashes are in `R4_COMMAND_LEDGER.md` and
`R4_RAW_EVIDENCE_INDEX.md`. These are finite owner-scope checks only and do
not close the 62 rows.

Collection found 18 node IDs with exit `0`, no collection errors, and is marked
collection-only rather than pass. Compileall and diff-check are green. Ruff
has six pre-existing landed VAL production findings and is not green for the
merged candidate; QA made no production edit. Corrected duplicate-definition
and unresolved-import checks are green. Candidate guard is green (26 entries,
zero failures), and the final QA-owned process audit is clean. B01 remains the
external public StructuralLock/Full Apply blocker; no normal-product S12/video/
UI evidence is promoted.

## C01-C32 retained acceptance rows

| Row | Exact requirement/evidence locator | Status |
|---|---|---|
| C01 | Prior T03C closure evidence retained; R4 QA did not alter RETRY tests. | CARRY_FORWARD_ONLY |
| C02 | Prior T01/T02 capability/profile evidence retained; no R4 rerun. | CARRY_FORWARD_ONLY |
| C03 | Prior provenance evidence retained; R3 public source hash remains indexed. | CARRY_FORWARD_ONLY |
| C04 | R3 raw producer chain has actual legacy project/video/source IDs and completed import/proxy/scene jobs. | PARTIAL |
| C05 | Prior T03C denial evidence retained; no R4 owner-test edit. | CARRY_FORWARD_ONLY |
| C06 | Prior T03A replay evidence retained; R4 identity audit is read-only. | CARRY_FORWARD_ONLY |
| C07 | Prior T03A identity/orphan evidence retained; full adversarial identity matrix remains owner-gated. | CARRY_FORWARD_ONLY |
| C08 | Prior typed loser/barrier evidence retained; R4 does not replace RETRY race proof. | CARRY_FORWARD_ONLY |
| C09 | Prior lease-fencing evidence retained; no R4 rerun. | CARRY_FORWARD_ONLY |
| C10 | Prior T03B 4K mechanism evidence retained; no normal export reached. | CARRY_FORWARD_ONLY |
| C11 | Prior geometry/letterbox evidence retained; no normal media reached. | CARRY_FORWARD_ONLY |
| C12 | Prior source-lock/timing evidence retained; R3 current source/evidence inputs remain indexed. | CARRY_FORWARD_ONLY |
| C13 | VAL submission finite evidence retained; F02 boundary remains independent-owner work. | MECHANISM_GREEN / OPEN |
| C14 | VAL real-worker evidence is submission-only; post-final boundary remains open. | NOT_DEMONSTRATED |
| C15 | RETRY submission evidence retained; successor claim/worker proof remains owner-gated. | BLOCKED / OPEN |
| C16 | R3 raw public legacy/analyze/extraction graph remains partial because extraction policy was QA-only. | PARTIAL |
| C17 | Normal publisher/result proof unavailable; F02 and product authority remain open. | OPEN / NOT_DEMONSTRATED |
| C18 | Normal atomic publication proof unavailable; F02 remains open. | OPEN / NOT_DEMONSTRATED |
| C19 | Prior validator evidence retained; F03 full-publisher path remains open. | MECHANISM_GREEN / OPEN |
| C20 | Full Apply authority absent; real Export UI not run. | NOT_RUN |
| C21 | Full Apply authority absent; reload/recovery UI not run. | NOT_RUN |
| C22 | Public S12 submit stopped at 409 in R3; no result/media/playback. | NOT_DEMONSTRATED |
| C23 | Packaging/stage gate not reassessed in R4 QA lane. | NOT_REASSESSED |
| C24 | Package hash/dependency gate not reassessed in R4 QA lane. | NOT_REASSESSED |
| C25 | R3 QA-owned worker/orchestrator stopped and engine disposed; R4 process audit is indexed. | PARTIAL |
| C26 | Public S10 stopped at 422 with incomplete authority; no fabricated Full Apply. | BLOCKED |
| C27 | Normal cancel/expiry/restart after authority not reached. | BLOCKED |
| C28 | Normal-product audio not reached; mechanism audio evidence stays separate. | BLOCKED |
| C29 | Clean-host/human playback remains external and not run. | NOT_RUN |
| C30 | Retained-data migration evidence remains submission-only; no R4 migration. | NOT_REASSESSED |
| C31 | Prior collection evidence is collection-only, never execution/pass evidence. | COLLECTION_ONLY |
| C32 | Candidate hashes, ownership, guard, process cleanup, and R4 packet are recorded; no closure authority. | TRANSPORT_PARTIAL |

## S01-S10 prior independent findings

| Row | Exact requirement/evidence locator | Status |
|---|---|---|
| S01 | F02 pre-receipt crash: final/sidecar/receipt boundary faults, same DB/run/job, stable bytes/mtime. | OPEN / VAL_OWNER |
| S02 | Commit/private-public alias perturbation and restart assembly controls. | PARTIAL / VAL_OWNER |
| S03 | Retry attempt 1/2/3 claim and actual worker successor chain. | OPEN / RETRY_OWNER |
| S04 | Full publisher companion temp-path preflight including long/deep/Unicode controls. | OPEN / VAL_OWNER |
| S05 | Actual worker kill after final before sidecar and fresh same-DB convergence. | OPEN / VAL_OWNER |
| S06 | Normal public export chain after real authority; R3 B01 proof remains blocked. | BLOCKED / QA |
| S07 | Current exclusive race at the contested operation with stale cleanup. | PARTIAL / VAL_OWNER |
| S08 | Stale cleanup preserves winner files and metadata. | PARTIAL / VAL_OWNER |
| S09 | Audio deadline/error/cancel/provenance controls. | PARTIAL / VAL_OWNER |
| S10 | Context/UI stale/ownership/navigation guards after terminal candidate pin. | NOT_RUN / INT_UI_GATE |

## P01-P10 product-stage map

| Row | Exact stage and evidence | Status |
|---|---|---|
| P01 | Legacy public project/upload returned actual 12-hex project, UUID video, source artifact. | DEMONSTRATED / R3_RAW |
| P02 | Legacy analyze/import/proxy/scene durable chain completed. | DEMONSTRATED / R3_RAW |
| P03 | Public extraction job completed; deterministic provider is QA fixture-only. | PARTIAL / FIXTURE_ONLY |
| P04 | Actual roles, occurrences, and structural-evidence segments returned. | DEMONSTRATED / R3_RAW |
| P05 | Public character/version/assets validation and publish completed. | DEMONSTRATED / R3_RAW |
| P06 | Public cast/config consumers created; lock pin is null. | PARTIAL / R3_RAW |
| P07 | No public StructuralLock create/activate route or production caller. | BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY |
| P08 | S09 v1/reapprove returned 201 but authority is non-executable without lock/source. | BLOCKED |
| P09 | S10 returned 422 incomplete authority. | BLOCKED |
| P10 | S12 context/submit returned missing-lock/full-apply responses; media/UI not reached. | NOT_DEMONSTRATED / NOT_RUN |

## R01-R10 current correction/evidence rows

| Row | Exact proposed control, counts, and evidence requirement | Status |
|---|---|---|
| R01 | RETRY valid cancelled/failed predecessor chains: 3 Runs/3 all Job rows; attempts 1/2/3 claim and worker; malformed/foreign/self/cyclic zero mutation. | NOT_RUN / RETRY_OWNER |
| R02 | RETRY two live callers rendezvous at claim/create, bounded joins, exactly 1 logical winner, 1 successor, 1 Job; all rows 2/2. | NOT_RUN / RETRY_OWNER |
| R03 | RETRY union identity/tamper/query-error/commit-uncertainty controls; valid replay zero delta, wrong/ambiguous zero mutation. | NOT_RUN / RETRY_OWNER |
| R04 | VAL pre-final/post-final/pre-sidecar/post-sidecar/receipt/commit faults; own recovery 1 Run/1 Job, stable chunks/mtime, foreign/tamper zero mutation. | NOT_RUN / VAL_OWNER |
| R05 | VAL actual DurableWorker kill at post-final/pre-sidecar; fresh same-DB Run/Job reaches completed, no extra rows. | NOT_RUN / VAL_OWNER |
| R06 | VAL real expiry race and stale cleanup; one winner, private handle/rebuild cannot mutate winner bytes/mtime. | NOT_RUN / VAL_OWNER |
| R07 | VAL full publisher short/deep/space/Unicode and basename155+ temp preflight; unsupported typed before public mutation. | NOT_RUN / VAL_OWNER |
| R08 | QA/INT retained S01-S10/C01-C32 controls, migration/hash retention, exact applicable module execution after owners terminal. | GATED / NOT_RUN |
| R09 | QA packet audit: all 62 rows, exact commands/envelopes/hashes/owner/model/turn/HEAD/guards/processes. | PARTIAL / QA_R4 |
| R10 | QA B01 audit: no public StructuralLock producer/activation; exact zero manifest/S12 counts and downstream typed failures. | BLOCKED_DEPENDENCY / QA_R4 |

Totals: C=32, S=10, P=10, R=10, total=62. R01-R08 require their exact
owners and terminal candidate transport; R09 is the QA packet audit and R10 is
the independently confirmed external dependency. No collected-test count is
treated as executed or passed.

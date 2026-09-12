# S12 LC3-R4 packet audit

The packet is owned by QA Goodall session
`01a08991-c909-7d03-86ed-ac236d50c87b`, on QA checkpoint
`ac49c9d4e40e6c3d3a5b3cad49f67d6f12a80cdd`, against frozen integration
candidate `17b33f53b27da58e3330dd4a8270706ac853d37a`. It is not a review
approval or closure packet.

The final read-only candidate transport audit was performed against clean
integration HEAD `b6d71873dd1597f191b3ead95cb15e5aff73a722`. Ancestors for the
VAL merge `86630450213f5ed399aa7cbcace0c671999d8b89`, RETRY merge
`0df6cf370d655445953480b56d4797bfddec560f`, and QA merge
`617f7e809f7feb8fda0b69a49c469cc751a2e749` are present. This supersedes the
prior candidate pin for transport evidence only; it does not approve or close
the packet.

Required navigation artifacts:

- [R4_MATRIX.md](R4_MATRIX.md): exactly 62 rows: C01-C32, S01-S10, P01-P10, R01-R10.
- [R4_COMMAND_LEDGER.md](R4_COMMAND_LEDGER.md): prospective and executed command envelope index.
- [R4_SESSION_REGISTRY.md](R4_SESSION_REGISTRY.md): owner/model/branch/write-set registry.
- [R4_RAW_EVIDENCE_INDEX.md](R4_RAW_EVIDENCE_INDEX.md): raw result/hash locator.
- [R4_REPORT.md](R4_REPORT.md): terminal status, blocker, and gate disposition.

## Packet completeness audit

| Requirement | Evidence | Status |
|---|---|---|
| Owner/session exactness | R4_REPORT, R4_SESSION_REGISTRY | PRESENT |
| Model/reasoning/fallback | R4_REPORT, registry, ledger | PRESENT |
| Candidate/QA HEAD and clean state | `candidate-status-final-20260911T201000Z.*`, `qa-status-final-20260911T201000Z.*` | PRESENT / PASSING_EVIDENCE |
| 62-row matrix arithmetic | R4_MATRIX + `qa-packet-micro-terminal-20260911T202300Z.*` | PRESENT / PASSING_EVIDENCE |
| S01-S10 product producer map | R4_MATRIX P rows + R3 raw chain | PRESENT |
| C01-C32 retained acceptance | R4_MATRIX | PRESENT |
| P01-P10 product stages | R4_MATRIX | PRESENT |
| R01-R10 correction map | R4_MATRIX | PRESENT |
| Public StructuralLock route/call-site audit | R4_REPORT + `r4-readonly-audit.json` | PRESENT / PASSING_EVIDENCE |
| Exact S10/S12 responses and mutation counts | R3 raw JSON + R4 report | PRESENT |
| Guard/snapshots | supplied candidate/QA baselines + candidate/QA snapshot guard envelopes | PASSING_EVIDENCE |
| Process cleanup | `qa-process-terminal-20260911T202200Z.*` plus `qa-process-terminal-final-20260911T202600Z.*` | QA-owned clean before VAL overlap; latest broad audit retained as EXTERNAL_ENVIRONMENT_OVERLAP, not a product failure |
| No false green | blocked/not-run labels; collected != passed | PRESENT |

## Final b6 candidate audit addendum

| Requirement | Fresh evidence | Status |
|---|---|---|
| Merged VAL/RETRY micro first | Four short-contained command envelopes: VAL `2 passed`/`3 passed`; RETRY `4 passed`/`9 passed`; all exit `0` | PASSING_EVIDENCE / OWNER_SCOPE_ONLY |
| Candidate collection | `candidate-collect-val-retry-20260912T150200Z.command.json`; 18 nodes, exit `0`, no errors | COLLECTION_ONLY |
| Compile/diff/structure | compile `0`, diff-check `0`, duplicate scan `0`, import scan `0` | PASSING_EVIDENCE |
| Changed-scope Ruff | Six pre-existing landed VAL findings, exit `1` | OPEN / LANDED_STATIC_FINDINGS |
| Candidate guard and process | 26-entry guard exit `0`; zero QA-owned process matches | PASSING_EVIDENCE |
| VAL/RETRY owner artifacts | Actual worker-kill and contested-worker evidence inspected | MECHANISM_OWNER_EVIDENCE / NOT_NORMAL_PRODUCT |
| B01 public producer | Current b6 audit still has no public StructuralLock producer; S10 `422`, S12 `409` | BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY |
| Public S12/video/UI | No valid public authority; no media/UI pass promoted | NOT_DEMONSTRATED / NOT_RUN |

The packet micro was rerun after the candidate addendum:
`qa-packet-micro-candidate-b6-20260912T152700Z.command.json`, exit `0`,
`3 passed`, stdout SHA
`CB9CCAE7A25731B47BF196002B487FAD709F7ACC25B8ED060BE59B74A388EE4C`.

The supplied QA guard, QA diff-check, QA compileall, and QA Ruff controls also
exit `0`; their envelopes are indexed in `R4_COMMAND_LEDGER.md`. These checks
validate only the QA-owned packet, not the landed VAL Ruff findings or any
normal-product S12 claim.

## Audit rule

Only exact command envelopes and raw files can move a `VERIFY` item to
`PASSING_EVIDENCE`. Missing runtime support becomes `ENVIRONMENT_BLOCKED`, not
product green. No R01-R08 mechanism row is closed by this packet; R09 is the
packet-control result and R10 is the external StructuralLock dependency.

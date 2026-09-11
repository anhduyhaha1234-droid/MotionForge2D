# S12 LC3-R4 raw evidence index

Evidence root:
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r4-owner-submission\20260911T195310Z\qa-r08-r10-20260911T200414Z`

Runtime root:
`C:\Users\Admin\Documents\Codex\work\s12-r4\20260911T195310Z\qa-r08-r10-20260911T200414Z`

The lane uses the frozen candidate read-only and does not use MAIN, canonical
S12, demo, S11/S13, or live ports. Each captured command has `.command.json`,
`.stdout.txt`, and `.stderr.txt` siblings. R3 source evidence is retained at:

`C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3-r3\20260911T034253Z\public-producer-chain-20260911T035817Z.json`

## R3 carried raw evidence used for R10

- public producer-chain JSON: SHA-256 `C97FA33215908D4352BEDB547E1B8E8B3A68141696AEA10FA75E8683497612EA`
- public producer-chain stdout: SHA-256 `C97FA33215908D4352BEDB547E1B8E8B3A68141696AEA10FA75E8683497612EA`
- public producer-chain stderr: SHA-256 `124F2F3866280D26F6F7521251EBD7BE954CA24C07F3C1082D964EACCD181F54`
- public producer-chain command envelope: SHA-256 `9C38ECC5392E3BC8539B3FE6B719CEC5404CF5F2AE998743CDD563377B056AE9`

R3 command start/end/duration: `2026-09-11T03:58:17.6701313Z` /
`2026-09-11T03:58:30.2858493Z` / `12.615718s`, exit `0`.

## R4 captured artifacts

| Artifact | Path / result |
|---|---|
| Candidate guard | `candidate-prewrite-guard.json` in the R4 evidence root; exit 0, 15 entries, zero failures. |
| QA prewrite manifest/snapshots | `QA/prewrite-qa-owned.json` and `QA/prewrite-snapshots/**`; captured before new R4 files. |
| Read-only candidate audit | `qa-readonly-audit-final-20260911T200900Z.command.json`, `.stdout.txt`, `.stderr.txt`, and `r4-readonly-audit.json`; exit 0, result SHA `412CEC09E8B669706F5C39DA8012D6456B70D77A0298E4DA32E80E8412783147`. |
| Packet micro | `qa-packet-micro-terminal-20260911T202300Z.*`; exit 0, 3 passed, stdout SHA `ED7BA5BDA32D1147039D4BD04612B0A4C95C7976F71C1483743C6CCEE338F823`. Earlier packet envelopes, including red control attempts, are retained. |
| Collection | `qa-collection-r4-final-20260911T201300Z.*`; exit 0, collection-only. |
| Ruff/compile/diff | `qa-ruff-rerun-final-20260911T201300Z.*`, `qa-compile-final-20260911T201400Z.*`, `qa-diff-check-final-20260911T201400Z.*`; all exit 0. |
| Guards | `candidate-guard-final-20260911T201100Z.*`, `qa-guard-supplied-final-20260911T201500Z.*`, and `qa-prewrite-snapshot-verify-final-20260911T201500Z.*`; all exit 0, zero failures. |
| Process cleanup | Earlier `qa-process-terminal-20260911T202200Z.*` was exit 0 with zero matches. Latest `qa-process-terminal-final-20260911T202600Z.*` is exit 1 because the broad audit observed VAL-owned PID 13308 and transient PID 2924; stdout SHA `B529A36C33F5212B900CF4D4257F224B87E2D089F4A686C7C15F22AF727220AE`. Both are under the separate VAL lane; no QA-owned runtime was identified or terminated. |

No absent raw artifact is a pass. Candidate OpenAPI import succeeded, so no
environment import failure affected the B01 result. The typed missing producer
from the valid R3 public chain remains the product dependency finding.

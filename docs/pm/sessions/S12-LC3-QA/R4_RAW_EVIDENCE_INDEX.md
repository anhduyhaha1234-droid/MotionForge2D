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

## Fresh final candidate lane: b6d7187

Evidence root:
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r4-owner-submission\20260911T195310Z\qa-candidate-b6d7187-20260912T145123Z`.

Runtime/temp lane used by the authoritative finite checks:
`C:\Users\Admin\Documents\Codex\work\R4QA-b6-20260912T145123Z\tmp`.
The candidate worktree was read-only and remained clean. All final command
envelopes have `.stdout.txt` and `.stderr.txt` siblings in this lane.

| Evidence | Exact raw locator / SHA and disposition |
|---|---|
| Candidate graph | `candidate-merge-graph-verify-20260912T150700Z.command.json`; exit `0`; stdout SHA `1D93E14EB1A68BE397C74B6882E05ADC046B065D93B6AC2E0516A0C1E8E5404C`; VAL/RETRY/QA ancestors present. |
| Authoritative VAL checks | `candidate-val-micro-contained-short-20260912T151200Z.command.json` exit `0`, stdout SHA `A5FEB906D198CE10C3155C488F7CEB999DABA63A37C7F4EE3519F39A18759BDB`; `candidate-val-finite-contained-short-20260912T151400Z.command.json` exit `0`, stdout SHA `FA5A84DEF3DAE1883F8AE1CF9AC581BBDD88B25771D629C85F5104F4EC340DA6`; 2 and 3 passed respectively. |
| Authoritative RETRY checks | `candidate-retry-micro-contained-short-20260912T151300Z.command.json` exit `0`, stdout SHA `5809A5CB17FBB36B02BBAE93C97F3402A159FE61E50EF48E221AC77744C8514B`; `candidate-retry-finite-contained-short-20260912T151500Z.command.json` exit `0`, stdout SHA `4D196110435A2169E332BB7EEE1CA502C18EF22190F38CCD40DFDFEA1D8C9871`; 4 and 9 passed respectively. |
| Collection | `candidate-collect-val-retry-20260912T150200Z.command.json` exit `0`, stdout SHA `17F58E200BE6491F750BC510AEFB05664C0E69C967CE47AA05A0AAE8EEED0A91`; 18 node IDs, no errors; collection-only, not pass. |
| Static/structure | Compile envelope `candidate-compileall-20260912T145700Z.command.json` exit `0`; Ruff `candidate-ruff-changed-scope-20260912T145800Z.command.json` exit `1` with six landed VAL findings; diff `candidate-diff-check-merged-scope-20260912T145900Z.command.json` exit `0`; duplicate scan `candidate-duplicate-definition-scan-corrected-20260912T150400Z.command.json` exit `0`, SHA `A2EC905B7533535CE044039ED85E5477812E276A6AD6D8BCA024E28A3DDF89A4`; imports `candidate-public-import-scan-corrected-20260912T150600Z.command.json` exit `0`, SHA `5173D3AEFD727923672D0F2725FC302EA3680738E25855CE47753807F12B9D42`. |
| B01 | `candidate-readonly-audit-b6-20260912T150100Z.command.json` exit `0`; result SHA `D8D4EA8B1BB165077410CE4A8DFD8799B2CBFF296A255FEFC8A5D134C1AF4B8F`; no public StructuralLock producer/caller, S10 `422`, S12 `409`, zero manifests/runs. |
| Final guard/process | `candidate-write-set-verify-final-20260912T152100Z.command.json` exit `0`, stdout SHA `F981AE6D2BF47C47B4FD768FB199B247938DE0ACBCB4AC8906F6D2AE1A72D470`, 26/26 zero failures; `candidate-process-audit-final-20260912T152200Z.command.json` exit `0`, stdout SHA `9582F2BE2E315621823C9B7A4B038A86FB17BC7EB27F4031ADEE487D5F5A9CB4`, zero QA-owned matches. |

Actual owner evidence inspected from the earlier R4 roots remains linked above:
VAL F02 `post-final-boundary.json`, `fresh-worker.json`, and published media
receipt; RETRY `R04_micro.raw.txt`, `R04_finite.raw.txt`, and
`R01_after_green.raw.txt`. Those artifacts are mechanism/owner evidence, not
normal public S12/video/UI proof. B01 remains product-blocked; no fixture,
collection, or static result changes that classification.

The QA packet micro after the addendum is
`qa-packet-micro-candidate-b6-20260912T152700Z.command.json`, exit `0`, `3
passed`, stdout SHA
`CB9CCAE7A25731B47BF196002B487FAD709F7ACC25B8ED060BE59B74A388EE4C`.

Post-addendum QA controls:

- supplied QA baseline guard: `qa-supplied-guard-candidate-b6-20260912T152800Z.command.json`, exit `0`, zero failures, stdout SHA `C12654F7A2A29B9B9C493EB71A24F79EF7EEB5EBE5D9C58D5CB3ADA8F2700E6E`
- QA `git diff --check`: `qa-diff-check-candidate-b6-20260912T152900Z.command.json`, exit `0`, empty stdout/stderr
- QA compileall: `qa-compile-r4-candidate-b6-20260912T153000Z.command.json`, exit `0`
- QA Ruff: `qa-ruff-r4-candidate-b6-20260912T153100Z.command.json`, exit `0`, stdout SHA `A4443AFDCFB6D7363ADB285762515CCF7CF50473B1A05C20C1A50F6BED4D26B0`

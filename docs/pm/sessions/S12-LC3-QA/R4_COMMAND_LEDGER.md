# S12 LC3-R4 QA command ledger

All commands below are QA-owned or read-only candidate checks. The raw command
envelopes, stdout/stderr, exit codes, durations, and SHA-256 values are indexed
in `R4_RAW_EVIDENCE_INDEX.md`. The lane is
`qa-r08-r10-20260911T200414Z`.

## Prospective gate order

1. Preflight: branch/HEAD/status, candidate guard, QA baseline and process audit.
2. QA micro: the R4 packet control and frozen-candidate public-authority audit.
3. Matrix/readers: 62-row arithmetic, source-call-site and OpenAPI audit.
4. Focused/static: compile, Ruff, collection of the new QA module, diff/guard.
5. Final process/allowlist review and local QA checkpoint.

R01-R08 owner tests are not run by this QA lane before their exact owners are
terminal and INT pins a candidate. A collected count is never an executed or
passed count.

## Command envelopes

| Gate | Exact command / cwd | Result |
|---|---|---|
| Initial owner status | `git status --short && git rev-parse HEAD && git log -8 --oneline`; QA cwd | Clean; HEAD `ac49c9d4e40e6c3d3a5b3cad49f67d6f12a80cdd`. |
| Frozen candidate status | same read-only Git status/log commands; candidate cwd | Clean; HEAD `17b33f53b27da58e3330dd4a8270706ac853d37a`. |
| Candidate prewrite guard | `python C:\Users\Admin\MotionForge2D\docs\pm\tools\write_set_guard.py verify --root C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration --manifest ...\candidate-baseline-r4.json --report ...\candidate-prewrite-guard.json` | Exit 0; 15 entries, zero failures. |
| QA prewrite snapshot | `write_set_guard.py capture` for existing R3 docs/harness into R4 QA lane | Exit 0; 6 byte snapshots captured. |
| QA public producer audit | `python tests/s12/s12-lc3-qa-r4/r4_readonly_audit.py --candidate-root C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration --candidate-baseline ...\candidate-baseline-r4.json --r3-evidence ...\public-producer-chain-20260911T035817Z.json --output ...\r4-readonly-audit.json` through `r4_command_capture.py` | Final envelope `qa-readonly-audit-final-20260911T200900Z.command.json`; 2026-09-11T20:08:24.561455Z–20:08:28.768552Z, 4.204s, exit 0; stdout SHA `6FEA724EE8A251D12B18B774F34EBD0DEAB69AE0FCC15F65E916B4306DCB80D0`; result SHA `412CEC09E8B669706F5C39DA8012D6456B70D77A0298E4DA32E80E8412783147`. |
| QA packet micro | `python -m pytest tests/s12/s12-lc3-qa-r4/test_r4_review_packet.py -q -p no:cacheprovider` | Terminal envelope `qa-packet-micro-terminal-20260911T202300Z.command.json`; 2026-09-11T20:19:52.695566Z–20:19:55.865755Z, 3.172s, exit 0, 3 passed; stdout SHA `ED7BA5BDA32D1147039D4BD04612B0A4C95C7976F71C1483743C6CCEE338F823`. Earlier packet envelopes, including two red control attempts, are retained. |
| Static | `python -m compileall -q tests/s12/s12-lc3-qa-r4`; `ruff check tests/s12/s12-lc3-qa-r4`; `git diff --check` | Compile envelope `qa-compile-final-20260911T201400Z`: exit 0, 0.062s; Ruff final envelope `qa-ruff-rerun-final-20260911T201300Z`: exit 0, 0.015s, stdout SHA `A4443AFDCFB6D7363ADB285762515CCF7CF50473B1A05C20C1A50F6BED4D26B0`; diff envelope `qa-diff-check-final-20260911T201400Z`: exit 0, 0.016s. Initial Ruff red is retained. |
| QA guard | `write_set_guard.py verify` with supplied `qa-baseline-r4.json` and own six-file prewrite snapshot | Supplied guard envelope `qa-guard-supplied-final-20260911T201500Z`: exit 0, 0.063s, 2 baseline entries, zero failures; report SHA `207E7BE859F05D515797C2CCC8B6AB8BCEE14DBA13FCC6698F6D760158EB83DF`. Own snapshot envelope `qa-prewrite-snapshot-verify-final-20260911T201500Z`: exit 0, 0.062s, zero failures; report SHA `3FE987BEC7D13E005483DC9C8B8760530116D509B63FAD7ADF8E2595E5DB00E4`. Candidate guard exit 0, 15 entries, zero failures. |
| Process cleanup | `python tests/s12/s12-lc3-qa-r4/r4_process_audit.py` through `r4_command_capture.py` | Earlier clean envelope `qa-process-terminal-20260911T202200Z.command.json` was exit 0 with zero matches. The latest envelope `qa-process-terminal-final-20260911T202600Z.command.json` is exit 1 because its broad `s12-r4` needle observed two VAL-owned Python processes (raw stdout SHA `B529A36C33F5212B900CF4D4257F224B87E2D089F4A686C7C15F22AF727220AE`): VAL pytest PID 13308 and a transient VAL worker PID 2924, both under the separate `s12-lc3-luna-val` lane. No QA-owned process was identified; no external process was terminated. This is an environment/control overlap, not a product result. |

All listed R4 commands now have raw envelopes. The carried R3 producer command
retains its original timestamp in `R4_RAW_EVIDENCE_INDEX.md`; no R4 timestamp
was backfilled from R3.

## Final b6d7187 candidate transport audit

Fresh evidence root:
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r4-owner-submission\20260911T195310Z\qa-candidate-b6d7187-20260912T145123Z`.
Candidate cwd for every candidate command was
`C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration`.

| Gate | Exact command / raw envelope | Exit/result |
|---|---|---|
| Graph | `git merge-base --is-ancestor` checks for VAL `86630450213f5ed399aa7cbcace0c671999d8b89`, RETRY `0df6cf370d655445953480b56d4797bfddec560f`, QA `617f7e809f7feb8fda0b69a49c469cc751a2e749`; `candidate-merge-graph-verify-20260912T150700Z.command.json` | `0`; all ancestors present; HEAD `b6d71873dd1597f191b3ead95cb15e5aff73a722`; stdout SHA `1D93E14EB1A68BE397C74B6882E05ADC046B065D93B6AC2E0516A0C1E8E5404C` |
| VAL micro | `python -m pytest tests\\s12\\s12-lc3-val\\test_r4_correction_boundaries.py -k test_r4_micro -q -p no:cacheprovider`; `candidate-val-micro-contained-short-20260912T151200Z.command.json` | `0`; `2 passed, 3 deselected, 5 warnings`; stdout SHA `A5FEB906D198CE10C3155C488F7CEB999DABA63A37C7F4EE3519F39A18759BDB`; 6.047s |
| RETRY micro | `python -m pytest tests\\s12\\s12-lc3-retry\\test_r4_retry_execution.py -k valid_retry_chain_runs_in_actual_worker or contested_retry_has_one_logical_winner -q -p no:cacheprovider`; `candidate-retry-micro-contained-short-20260912T151300Z.command.json` | `0`; `4 passed, 9 deselected, 9 warnings`; stdout SHA `5809A5CB17FBB36B02BBAE93C97F3402A159FE61E50EF48E221AC77744C8514B`; 8.906s |
| VAL finite | `python -m pytest --disable-warnings -q tests/s12/s12-lc3-val/test_r4_correction_boundaries.py -p no:cacheprovider`; `candidate-val-finite-contained-short-20260912T151400Z.command.json` | `0`; `3 passed, 2 deselected, 7 warnings`; stdout SHA `FA5A84DEF3DAE1883F8AE1CF9AC581BBDD88B25771D629C85F5104F4EC340DA6`; 14.297s |
| RETRY finite | `python -m pytest --disable-warnings -q tests/s12/s12-lc3-retry/test_r4_retry_execution.py -p no:cacheprovider`; `candidate-retry-finite-contained-short-20260912T151500Z.command.json` | `0`; `9 passed, 4 deselected, 19 warnings`; stdout SHA `4D196110435A2169E332BB7EEE1CA502C18EF22190F38CCD40DFDFEA1D8C9871`; 15.297s |
| Collection | `python -m pytest tests/s12 --collect-only -q -p no:cacheprovider` scoped to merged VAL/RETRY audit collection; `candidate-collect-val-retry-20260912T150200Z.command.json` | `0`; 18 nodes collected, no collection errors; collection-only, not pass; stdout SHA `17F58E200BE6491F750BC510AEFB05664C0E69C967CE47AA05A0AAE8EEED0A91` |
| Compile | `python -m compileall -q` on changed Python scope; `candidate-compileall-20260912T145700Z.command.json` | `0`; stdout/stderr SHA `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` |
| Ruff | `ruff check` on changed scope with `--ignore E501`; `candidate-ruff-changed-scope-20260912T145800Z.command.json` | `1`; six existing landed VAL findings in `app/services/s12_export/publication.py`; stdout SHA `9CC87497BA5B392B1F973B012644A5B4A8A3FDE96974B258D899139C9C499D48`; no QA production edit |
| Diff | `git diff --check 17b33f53b27da58e3330dd4a8270706ac853d37a..b6d71873dd1597f191b3ead95cb15e5aff73a722`; `candidate-diff-check-merged-scope-20260912T145900Z.command.json` | `0`; empty stdout/stderr |
| Duplicate definitions | corrected top-level duplicate scan over 10 VAL/RETRY Python files; `candidate-duplicate-definition-scan-corrected-20260912T150400Z.command.json` | `0`; `duplicate_top_level_definitions=[]`, `files_scanned=10`; stdout SHA `A2EC905B7533535CE044039ED85E5477812E276A6AD6D8BCA024E28A3DDF89A4` |
| Imports | corrected public import scan for `app.api.app`, S12 route/persistence/publication/jobs; `candidate-public-import-scan-corrected-20260912T150600Z.command.json` | `0`; no import errors, five modules imported; stdout SHA `5173D3AEFD727923672D0F2725FC302EA3680738E25855CE47753807F12B9D42` |
| B01 audit | `r4_readonly_audit.py` against current b6; `candidate-readonly-audit-b6-20260912T150100Z.command.json` | `0`; OpenAPI imported, no public StructuralLock producer/caller, S10 `422`, S12 `409`, zero StructuralLock manifests/S12 runs; JSON SHA `D8D4EA8B1BB165077410CE4A8DFD8799B2CBFF296A255FEFC8A5D134C1AF4B8F` |
| Candidate guard | `write_set_guard.py verify` against `candidate-current-b6-manifest.json`; `candidate-write-set-verify-final-20260912T152100Z.command.json` | `0`; 26 entries, zero failures; stdout SHA `F981AE6D2BF47C47B4FD768FB199B247938DE0ACBCB4AC8906F6D2AE1A72D470` |
| Process audit | `python tests\\s12\\s12-lc3-qa-r4\\r4_process_audit.py`; `candidate-process-audit-final-20260912T152200Z.command.json` | `0`; `count=0`, no QA-owned matches; stdout SHA `9582F2BE2E315621823C9B7A4B038A86FB17BC7EB27F4031ADEE487D5F5A9CB4` |

| QA packet micro | `python -m pytest tests\\s12\\s12-lc3-qa-r4\\test_r4_review_packet.py -q -p no:cacheprovider`; `qa-packet-micro-candidate-b6-20260912T152700Z.command.json` | `0`; 3 passed; stdout SHA `CB9CCAE7A25731B47BF196002B487FAD709F7ACC25B8ED060BE59B74A388EE4C`; 3.375s |
| QA supplied guard | `write_set_guard.py verify` with `qa-baseline-r4.json`; `qa-supplied-guard-candidate-b6-20260912T152800Z.command.json` | `0`; zero failures; stdout SHA `C12654F7A2A29B9B9C493EB71A24F79EF7EEB5EBE5D9C58D5CB3ADA8F2700E6E` |
| QA diff | `git diff --check`; `qa-diff-check-candidate-b6-20260912T152900Z.command.json` | `0`; empty stdout/stderr |
| QA compile/Ruff | `python -m compileall -q tests\\s12\\s12-lc3-qa-r4`; `ruff check tests\\s12\\s12-lc3-qa-r4` | Both `0`; compile envelope `qa-compile-r4-candidate-b6-20260912T153000Z.command.json`; Ruff envelope `qa-ruff-r4-candidate-b6-20260912T153100Z.command.json`, stdout SHA `A4443AFDCFB6D7363ADB285762515CCF7CF50473B1A05C20C1A50F6BED4D26B0` |

Retained controls: `candidate-val-micro-contained-20260912T151000Z` failed
from reused output residue, and `candidate-val-micro-contained-fresh2-
20260912T151100Z` failed from the long temporary path. Both are preserved and
classified as fixture/environment controls; the short contained rerun above
is the authoritative result. The malformed final-state `python -c` envelope
is also retained as a command-envelope control failure, not a product result.

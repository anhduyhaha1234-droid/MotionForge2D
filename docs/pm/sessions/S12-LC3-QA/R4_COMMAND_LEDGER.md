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

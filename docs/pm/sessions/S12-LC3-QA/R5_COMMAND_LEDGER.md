# S12-LC3-R5 QA command ledger

Owner/session: QA Goodall / 01a08991-c909-7d03-86ed-ac236d50c87b. Route per accepted assignment: gpt-5.6-luna / high / fallback OFF. No final candidate suite runs before serial INT transport.

## Lane and identity

- Evidence root: C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r5-owner-submission/20260912T164057Z/QA/matrix-packet-20260912T171510Z
- Runtime root: C:/Users/Admin/Documents/Codex/work/s12-r5/20260912T164057Z/QA/matrix-packet-20260912T171510Z
- QA checkout: C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa; branch codex/s12-lc3-luna-qa; pre-write HEAD 550494c2bfdd90dce21958cd56d6901d12c5b80b.
- Candidate checkout: C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration; branch codex/s12-lc3-luna-integration; pre-INT read-only HEAD b6d620eb00f65d31af85b3d64badc7f31f504830.
- R3 authority SHA-256: 98C929FAB41A52BF5EF148A088230F0D87ADBFB28FD2BCE891C40DC9E6A4EC54.

## Packet micro execution ledger

All packet runs used the same argv: `python -B -m pytest tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py -q -p no:cacheprovider`, CWD `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`, with `S12_R5_CANDIDATE_ROOT=C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration` and expected full SHA `b6d620eb00f65d31af85b3d64badc7f31f504830`. Every `.command.json`, raw stdout, and raw stderr is retained in the evidence root above; each stderr SHA is the empty-file hash `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

| Run | Start UTC → end UTC; seconds | Exit / disposition | Raw stdout SHA-256 |
|---|---|---|---|
| r5-packet-micro-pretransport | 2026-09-12T17:35:50.851879Z → 17:35:54.295394Z; 3.453 | 1; C24 case-sensitive anchor and wrong T04A C12 path | `1087A63E6CF50C9D3358F079EF19BC7EAFDF13F7CA884A926BDD94A56BB5449A` |
| r5-packet-micro-correction-1 | 2026-09-12T17:36:27.730574Z → 17:36:31.255232Z; 3.516 | 1; assertion rejected the intentionally negated fresh-process phrase | `631D57D33F3674A0A32E9566E164A8D8561024756F6F251AD333893EA044FD63` |
| r5-packet-micro-correction-2 | 2026-09-12T17:36:51.017764Z → 17:36:54.515115Z; 3.500 | 1; R08 audio deadline/error/cancel was not a distinct phrase | `E09EB3E1DE830028B42AD6F97F04118F1FC84CAC3809CB64F0A6478DD664BD57` |
| r5-packet-micro-correction-3 | 2026-09-12T17:37:19.225418Z → 17:37:22.682814Z; 3.453 | 1; R10 blocker-code anchor absent from the selected cell | `38F84C363E4EC84A35F4A615FC5ADEC4B85C05C2FA5E571EC2901C27D9194A2C` |
| r5-packet-micro-correction-4 | 2026-09-12T17:37:43.176780Z → 17:37:46.678202Z; 3.500 | 1; P07 proposal/status column expectation conflicted with binding status | `FA2E8F00140E264CDB611EFE5B5EB2CE3E912E3C0B92C9B54D6A64916B1CBD39` |
| r5-packet-micro-c12-correction | 2026-09-12T17:41:38.846301Z → 17:41:42.116297Z; 3.265 | 1; valid inventory rows compared in a non-contractual order | `AE94FE95358274A24AD78B1F4E5FE56B94C22887CE204797C0C70DD8C464F7DE` |
| r5-packet-micro-r3-reconcile | 2026-09-12T17:43:50.078248Z → 17:43:53.511913Z; 3.438 | 1; R10 status/evidence index and C12 missing-class label mismatch | `0054BF77FABB247E969A95821800E61528163BB45A9AC4DD03BF100E9E13B7C1` |
| r5-packet-micro-final-r3-contract | 2026-09-12T17:44:29.340771Z → 17:44:32.733009Z; 3.390 | 1; exact R10 status had trailing punctuation | `3AA00B90BEE610BB3EDD92971C85C8BEC910B18820A0F67ECDB2A9450E0ED4A4` |
| r5-packet-micro-green-attempt | 2026-09-12T17:44:54.053010Z → 17:44:57.454288Z; 3.406 | 1; P07 evidence detail appended to the status cell | `C605244BD73AE5F32124F7F868341B62AD8063B32DBDA99774BF561AB8D20A84` |
| r5-packet-micro-authority-status | 2026-09-12T17:45:19.291747Z → 17:45:22.679271Z; 3.391 | 0; 3 passed, then-current packet assertions | `943AF77B0C924299C952CF453C3999FB4D04307B32A19D6CA460C039F4EACB32` |
| r5-packet-micro-final | 2026-09-12T17:47:04.660555Z → 17:47:08.082866Z; 3.422 | 0; 3 passed after P07/R10 status split | `943AF77B0C924299C952CF453C3999FB4D04307B32A19D6CA460C039F4EACB32` |
| r5-packet-micro-final-harness | 2026-09-12T17:48:24.706525Z → 17:48:28.153957Z; 3.453 | 0; final harness after Ruff-only source cleanup, 3 passed | `FDFCD384D5E6AD0889BDA391B2BBC5A5EC0F22D8D6EF70C60F3D2660BBC2CBDC` |

The C12 inventory explicitly maps `tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c12_source_order_cuts_rational_and_cfr` and `::test_c12_vfr_rejected_before_any_work` as PRESENT (static only), plus T04A `test_c12_seam_stitch_correct_order_passes`, `test_c12_vfr_rejected_pre_work`, and `test_c12_cfr_control_matches_manifest`. It records the obsolete path-qualified `tests/s12/s12-t04a/test_s12_t04a_c1_closure.py::test_c12_rational_cuts_placement_passes` as MISSING. The packet tests do not execute any candidate probe.

## Other checks and dispositions

| Gate | Exact command / CWD | Result / raw evidence |
|---|---|---|
| Preflight | PowerShell git status/branch/HEAD and `Get-FileHash -Algorithm SHA256 <R3_MATRIX_AUTHORITY.md>` / QA checkout | QA branch `codex/s12-lc3-luna-qa`, pre-write HEAD `550494c2bfdd90dce21958cd56d6901d12c5b80b`; authority SHA matched. |
| Candidate pin | `git -C <candidate> status --short`; branch, HEAD, merge-base / QA checkout | Candidate clean at `b6d620eb00f65d31af85b3d64badc7f31f504830`; merge-base was QA base. Read-only. |
| Pre-write QA guard | `write_set_guard.py capture` to `qa-prewrite.json` with byte snapshots / QA root | Exit 0, CAPTURED, 8 entries. |
| Pre-write candidate guard | `write_set_guard.py capture` to `candidate-probes-prewrite.json` / candidate root | Exit 0, CAPTURED, 17 named immutable source entries and snapshots. |
| Ruff initial | `python -m ruff check tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py` / QA root | Exit 1; import ordering and two SIM102 findings; raw `r5-qa-ruff.stdout.txt`, SHA `8560A4BCDE6932F353800BFD81884370D34AAF016F0D1B668DB13671373602AA`. |
| Ruff formatting follow-up | Same command / QA root | Exit 1; E501 line length; raw `r5-qa-ruff-corrected.stdout.txt`, SHA `FE156B3E185CDB9216A8CAA97934F91C0121A8E289FB6E5BA068FA2FC1FBBE2A`. |
| Ruff final | Same command / QA root | Exit 0; raw `r5-qa-ruff-final.stdout.txt`, SHA `A4443AFDCFB6D7363ADB285762515CCF7CF50473B1A05C20C1A50F6BED4D26B0`. |
| QA pre-write verify | `write_set_guard.py verify --manifest <evidence>/qa-prewrite.json`, allow only R5_MATRIX.md, R5_REPORT.md, and packet test / QA root | Exit 0, 8 entries; final report `qa-prewrite-verify-final.json`; stdout SHA `4AE8AA622CD2EEF431233BF1EB99731361A025411170DCE98A98EC4C4C414002`. R5_COMMAND_LEDGER.md was not in this original manifest and is covered by the separate precommit manifest. |
| Candidate probe verify | `write_set_guard.py verify --manifest <evidence>/candidate-probes-prewrite.json` / candidate root | Exit 0, 17 entries unchanged; final report `candidate-probes-verify-final.json`; stdout SHA `9D25F5CD10FC50BADF86816A45717E36EFFF650020AC34120EFA8562A39099D6`. |
| Stage allowlist | `git add -- docs/pm/sessions/S12-LC3-QA/R5_MATRIX.md docs/pm/sessions/S12-LC3-QA/R5_REPORT.md docs/pm/sessions/S12-LC3-QA/R5_COMMAND_LEDGER.md tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py` / QA root | Exit 0; exactly four staged paths. Git emitted only the standard LF→CRLF-on-next-touch warning for these four new files; raw `r5-stage-allowlist.stderr.txt`, SHA `8F02717F98F19018A4A35168B69BECF1197DCABFA3340A15CC144432B822A705`; ledger is re-staged after this update. |
| Diff check | `git diff --cached --check` after staging exactly those four QA paths / QA root | Exit 0, empty stdout/stderr; final locked envelope `r5-diff-check-locked.command.json`, empty-output SHA `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`. |
| Precommit guard | `write_set_guard.py capture` and `verify` for four R5 files plus five inherited protected QA docs / QA root | Exit 0 capture and verify, 9 entries; manifest `r5-qa-precommit-final.json`, byte snapshots under `r5-qa-precommit-final-snapshots`; recapture stdout SHA `B26B53192A108FB09CFBC136E2E5778EB542FDBFC592CE5E40E84122EE44A5C9`; verify stdout SHA `38EF93710AFD2D3A631A904C5D01402203D78F9A9076554165F513FA124CF726`. Re-capture/re-verify follows this ledger update. |
| Local commit and clean status | `git commit -m "qa(s12): restore R5 acceptance matrix semantics"`; then separately `git rev-parse HEAD` and `git status --porcelain=v1 --untracked-files=all` / QA root | Local QA-only commit; full SHA and clean porcelain captured in `r5-local-commit.command.json` and `r5-postcommit-status.command.json`. No push. Candidate suite remains gated until serial INT transport. |

All raw command envelopes and stdout/stderr files are in the evidence root above, named by run. Four inherited T03A migration failures are itemized in R5_REPORT.md and linked to the independent review raw trace; they are not waived.

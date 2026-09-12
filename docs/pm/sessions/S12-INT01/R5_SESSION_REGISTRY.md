# S12-LC3-R5 INT session registry

| Field | Value |
|---|---|
| owner | Pascal, existing INT owner |
| exact session | `01a0898b-823a-7053-a1de-27d6fc24fce3` |
| turn | R5 INT transport continuation; numeric turn not supplied |
| model route | `gpt-5.6-luna` |
| reasoning | `high` |
| fallback | `OFF` |
| candidate worktree | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration` |
| branch | `codex/s12-lc3-luna-integration` |
| pre-INT HEAD/status | `b6d620eb00f65d31af85b3d64badc7f31f504830`, clean |
| three-merge transport tip | `75adde4d3d50e469188e1766f20eb81b898d9485` |
| writer sequence | VAL `4f836627a3a8f0b7df0457230fee0987d4475bb3` -> RETRY `c60235f9fd2b6d6188dc9c974fc3640aa04c8031` -> QA `b6ab84e7e80ce673dda7a5c1ce517732fea06688` |
| merge SHAs | VAL `0f11465a4ae66a0eb3d0d44699b4c9f3d4216a8f`; RETRY `36ae3914d556a8f7c204827ddb6123751229dafd`; QA `75adde4d3d50e469188e1766f20eb81b898d9485` |
| candidate writer delta | exactly 15 paths, no extra path |
| source-parent allowlist checks | all three exact direct deltas matched; each source diff-check exit 0 |
| candidate write-set guard | 17 candidate probes, `VERIFIED`, 0 failures after each merge |
| static | compileall 0; Ruff 1 (four findings in VAL publication.py); R5 diff-check 0 |
| protected staged rename | guard `VERIFIED`, 1 entry; preserved |
| worker processes | none matched outside the query process |
| review disposition | `SPRINT_SUBMITTED / PENDING_CODEX_REVIEW / NOT_CLOSED` |
| product/approval/closure | not asserted; no broad/product/UI/video tests run by INT |

Evidence roots:

- `C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r5-owner-submission\20260912T164057Z\INT`
- `C:\Users\Admin\Documents\Codex\work\s12-r5\20260912T164057Z\INT`

Full commands, exact path lists, raw warnings, exit codes, and evidence hashes are in `R5_TRANSPORT_LEDGER.md` and `R5_INT_RAW_PROVENANCE.txt` in those INT roots.

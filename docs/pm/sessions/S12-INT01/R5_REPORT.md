# S12-LC3-R5 INT terminal transport report

## Status

`SPRINT_SUBMITTED / PENDING_CODEX_REVIEW / NOT_CLOSED`

This is a Git transport report, not approval or closure. Exact existing owner: Pascal, INT session `01a0898b-823a-7053-a1de-27d6fc24fce3`; route `gpt-5.6-luna`, reasoning high, fallback OFF.

## Candidate and merges

Worktree `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`, was clean at pre-INT `b6d620eb00f65d31af85b3d64badc7f31f504830`.

Serial ordinary non-FF merges completed, without conflicts:

1. VAL source `4f836627a3a8f0b7df0457230fee0987d4475bb3` (parent `e9a1686df7c740934c6fa8e12e23e1597f04856f`) -> merge `0f11465a4ae66a0eb3d0d44699b4c9f3d4216a8f`, parents `b6d620eb00f65d31af85b3d64badc7f31f504830` + exact source.
2. RETRY source `c60235f9fd2b6d6188dc9c974fc3640aa04c8031` (parent `2c9d793eb96ea330ba4d9ee1028ce45909cb9ea6`) -> merge `36ae3914d556a8f7c204827ddb6123751229dafd`, parents `0f11465a4ae66a0eb3d0d44699b4c9f3d4216a8f` + exact source.
3. QA source `b6ab84e7e80ce673dda7a5c1ce517732fea06688` (parent `550494c2bfdd90dce21958cd56d6901d12c5b80b`) -> merge `75adde4d3d50e469188e1766f20eb81b898d9485`, parents `36ae3914d556a8f7c204827ddb6123751229dafd` + exact source.

All stated source parents were ancestors of the candidate before transport, branch tips equaled pinned commits, and all three parent-to-tip changed-path lists exactly matched their lane allowlists (VAL 6, RETRY 5, QA 4). Each merge exited 0 and the candidate remained clean after each. Git emitted a geometric-repack/bad-object maintenance warning after successful merges; it did not change the merge exit or create conflicts. Exact commands and warning text are retained in the INT raw provenance.

## Final checks

- Exact R5 writer delta from `b6d620eb00f65d31af85b3d64badc7f31f504830` to transport tip `75adde4d3d50e469188e1766f20eb81b898d9485`: 15 paths, exactly the VAL + RETRY + QA allowlist union.
- Candidate 17-entry immutable-probe guard: `VERIFIED`, 0 failures after each merge.
- R5-range `git diff --check`: exit 0.
- Changed-scope compileall: exit 0.
- Changed-scope Ruff: exit 1, four diagnostics in merged VAL `publication.py` (N818, SIM103, SIM102, SIM105); no source/test change was made.
- T01 staged-rename guard: `VERIFIED`, one entry; staged rename preserved.
- No VAL/RETRY/QA worker process was found after excluding the process-query shell itself.
- MAIN, canonical S12, S11, S13, demo/C10, and UI refs stayed at captured HEADs. Existing unrelated dirty state was left untouched.
- No broad/product/UI/video tests were run by INT; the exact QA owner’s post-INT gates remain pending.

QA explicitly retains `BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY / NOT_CLOSED / NOT_APPROVED` and historical migration findings; INT makes no readiness or approval claim.

Full lane path lists, source guard references, protected refs, and merge records: [R5_TRANSPORT_LEDGER.md](R5_TRANSPORT_LEDGER.md). Owner/route/evidence registry: [R5_SESSION_REGISTRY.md](R5_SESSION_REGISTRY.md).

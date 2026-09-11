# S12-LC3-VAL R4 finite design matrix

Owner: VAL Wegener, session `01a089a3-2ca7-7642-8c16-e2904d9f7afa`.
Requested route: `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.
Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val`.
Branch: `codex/s12-lc3-luna-val`.
Starting HEAD: `acd2fd69c3bf48e4f4bf503cbb15d9bb1430c275`.
R4 candidate baseline supplied by the review: integration HEAD
`17b33f53b27da58e3330dd4a8270706ac853d37a`; it is not materialized on this
owner branch and will not be merged or reset here.

The supplied `val-baseline-r4.json` was verified before this note was added:
9 entries, 0 failures. The pre-existing untracked `work/` tree remains
protected and is not part of this implementation write set.

## Locked finite rows

| Row | Required mechanism | Green assertion | Required negatives / identity |
|---|---|---|---|
| R04-a | pre-final fault | no public final, sidecar, receipt, or intent; owned scratch is cleaned | fence/readiness/validation failure is typed and leaves foreign files alone |
| R04-b | actual post-final/pre-sidecar process loss | real publisher/worker child is killed at the named hook; fresh process on same DB/run/job completes exactly one publication | final is owned only by matching attempt/fence/lineage; chunks and all rows are retained |
| R04-c | post-sidecar/pre-receipt and receipt/pre-commit loss | fresh recovery converges without overwrite; final/sidecar hashes and mtimes are stable | missing, malformed, foreign, tampered, ambiguous, and read-error companions fail closed |
| R04-d | actual commit failure and lost acknowledgement | recovery/replay preserves completed winner and private candidate isolation | no unchecked overwrite or blind delete; run/job lineage remains one-to-one |
| R05 | full publisher path preflight | short, deep, space, and Unicode paths complete when addressable | basename `155 x + .mp4` and every actual temporary companion name are typed before public mutation |
| R06-a | contested expiry A/B | two live participants rendezvous immediately before exclusive filesystem publication; exactly one wins | stale loser cannot mutate final, sidecar, receipt, or private candidate; hashes/mtimes unchanged |
| R06-b | open-handle/rebuild isolation | private writable handle and post-commit rebuild perturbation cannot alter public winner | candidate and final are distinct inodes; foreign companion is preserved |
| R07 | retained controls | existing R1/R2/R3 audio, source-lock, order/timing, decoder, cancel, cleanup, and resource controls remain green | no skipped test or relaxed threshold substitutes for a mechanism row |

## Gate order and evidence

1. Run intended before-red micro cases only where the current code genuinely
   reaches the boundary; preserve raw failure/NOT_RUN evidence and do not call
   collection a pass.
2. Patch only the VAL production/test/doc allowlist with bounded preimages.
3. Repeat the same micro assertions after green.
4. Run the complete finite VAL publication matrix and retained allowed tests,
   then compileall, Ruff F/I, duplicate/unresolved-symbol checks, and diff
   checks.
5. Run the supplied baseline guard with all prior landed VAL deltas and the
   current correction paths explicitly allowlisted. Write post-guard evidence.

Every executable record must include exact argv, cwd, scoped runtime root,
start/end UTC, duration, exit, timeout/kill details, raw stdout/stderr path,
process IDs, final/sidecar/receipt/candidate SHA-256 and mtimes, row counts,
chunk hashes/mtimes, and cleanup status. Resource readings are bounded samples;
no 30-minute capacity claim is permitted.

The independent R3 verdict remains `CHANGES_REQUESTED / NOT_CLOSED /
NOT_APPROVED`. B01 / normal product producer authority remains outside VAL and
is not changed or waived by these mechanism tests.

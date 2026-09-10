# S12-LC3-QA Q0 collection audit

The fresh evidence root was
`C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\outputs\s12-luna-c3\20260910T041635Z`.
The supplied `baseline-qa-q0-guard.json` was verified before edits with 45
entries and zero failures.

The red command was exactly:

```text
python -m pytest tests/s12 --collect-only -q -p no:cacheprovider
```

It exited `2` in `4407 ms`, with empty stderr, and reported 269 collected
nodes before five collection errors. Errors were the duplicate basename
imports in T02/T03B/T03C/T04A and T03C C22 resolving the T01 module and
raising `AttributeError` for missing `FPS`.

The repaired command used the same exact argv and exited `0` in `3444 ms`.
It reported `326 tests collected in 2.34s`; native stderr was empty. Raw
streams are `q0-collect-green.stdout.txt` and `q0-collect-green.stderr.txt`.
The complete node list is `q0-node-id-manifest.txt`: 326 lines, zero duplicate
IDs.

The five identity renames are R100 and byte-identical to the supplied
snapshots. The only content patch is the T03C C22 import target. All 30 test
files retain 326 test definitions and 920 explicit AST `assert` nodes. There
are zero duplicate test basenames and zero unresolved imports after collection.

Static results: `ruff check --select F tests/s12` exit 0; `git diff --check`
and cached diff-check exit 0. The supplied guard, using a manifest that maps
only the five authorized old paths to their new paths and allows only the C22
import file to differ, reports 45 entries and zero failures. Its report is
`post-qa-q0-guard-report.json`.

The named `NEXT_LUNA_PROMPT.md`, `REVIEW.md`, and `MATRIX.md` files were not
present under the worktree, MAIN, or fresh evidence root; the active user
prompt and S12 session/transport records were used without fabricating those
missing files.

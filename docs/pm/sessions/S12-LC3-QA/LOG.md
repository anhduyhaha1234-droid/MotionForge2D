# S12-LC3-QA — Q0 collection identity/import repair log

Status: `Q0_CHECKPOINT_SUBMITTED` — collection transport only; no C26/C27
closure or row/sprint approval is claimed.

## Authority and scope

- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa`
- Branch: `codex/s12-lc3-luna-qa`
- Starting HEAD: `679bee88d80b66dc91323f8cb41f71e6f689a61b`
- Route: `gpt-5.6-luna`, reasoning `high`, fallback `OFF` (per the LC3
  registry and task route; no silent model switch).
- Write scope: `tests/s12/**` identity/import files and
  `docs/pm/sessions/S12-LC3-QA/**` evidence/docs only.
- Forbidden scope was not touched: production/frontend implementation,
  MAIN, canonical integration, S11, S13, demo, push/reset/clean/stash/rebase,
  or force-push.

The full worktree HERMES rules, worktree/Main AGENTS, frontend AGENTS,
SESSION_PROTOCOL, canonical `docs/contracts/s12-export.md`, S12 registry,
transport provenance, baseline, and relevant S12 task reports were read.
`NEXT_LUNA_PROMPT.md`, `REVIEW.md`, and `MATRIX.md` were not present in the
available repository or fresh evidence roots; this absence is recorded rather
than inventing or rewriting those documents.

## Preflight and red reproduction

The supplied `baseline-qa-q0-guard.json` verified before edits:

```text
python .../write_set_guard.py verify --root <worktree> --manifest <baseline-qa-q0-guard.json>
{"status": "VERIFIED", "failures": 0, "entries": 45}
```

Exact red command:

```text
python -m pytest tests/s12 --collect-only -q -p no:cacheprovider
```

Exit `2`, duration `4407 ms`, stderr empty. Pytest reported `269 tests
collected` before interruption and five collection errors: T02, T03B, T03C,
T03C C22, and T04A. The four duplicate-basename errors resolved
`test_c1_closure` to T01; C22 then failed with
`AttributeError: module 'test_c1_closure' has no attribute 'FPS'`.

## Bounded repair

Only these five identity-preserving `git mv` operations were made:

| Old basename | New task-qualified basename | Byte result |
|---|---|---|
| T01 `test_c1_closure.py` | `test_s12_t01_c1_closure.py` | exact bytes, R100 |
| T02 `test_c1_closure.py` | `test_s12_t02_c1_closure.py` | exact bytes, R100 |
| T03B `test_c1_closure.py` | `test_s12_t03b_c1_closure.py` | exact bytes, R100 |
| T03C `test_c1_closure.py` | `test_s12_t03c_c1_closure.py` | exact bytes, R100 |
| T04A `test_c1_closure.py` | `test_s12_t04a_c1_closure.py` | exact bytes, R100 |

One bounded preimage patch changed the T03C C22 import from
`test_c1_closure` to `test_s12_t03c_c1_closure`. No test body, fixture,
assertion, or business outcome was changed. The old T01 historical worktree
was not accessed or modified.

## Green collection and static gates

The repaired exact invocation exited `0` (captured duration `3444 ms`):

```text
python -m pytest tests/s12 --collect-only -q -p no:cacheprovider
```

Pytest reported `326 tests collected in 2.34s`; native stderr is empty. The
complete stdout and stderr are saved as `evidence/q0-collect-green.stdout.txt`
and `evidence/q0-collect-green.stderr.txt`; the complete 326-node list is also
in `evidence/q0-node-id-manifest.txt`.

- Collected node-ID lines: `326`.
- Duplicate collected node IDs: `0`.
- Duplicate `test_*.py` basename groups: `0` (30 unique test-file basenames).
- Unresolved imports/collection errors after repair: `0`.
- `ruff check --select F tests/s12`: exit `0`, all checks passed.
- `git diff --check` and cached diff-check: exit `0` (Git emitted only its
  normal LF-to-CRLF warning for the patched file).

The five renamed modules retained their exact test definitions/assertions:

| Task | Bytes | Lines | Test defs | AST `assert` nodes |
|---|---:|---:|---:|---:|
| T01 | 21298 | 513 | 23 | 78 |
| T02 | 5582 | 141 | 8 | 22 |
| T03B | 21898 | 530 | 13 | 37 |
| T03C | 23858 | 580 | 9 | 46 |
| T04A | 13664 | 372 | 22 | 49 |

Across all 30 collected `test_*.py` files, explicit AST `assert` nodes remain
`920` and test definitions remain `326`. T03C C22 changed only one import line;
its metrics remained 306 lines, 5 test definitions, and 14 assert nodes.

## Guard and scope evidence

`evidence/post-qa-q0-guard.json` is the supplied baseline manifest with only
the five authorized rename paths mapped to their new names. The supplied guard
verified all 45 entries with the sole allowed content change listed above:

```text
{"status": "VERIFIED", "failures": 0, "entries": 45}
```

The guard report is saved as `evidence/post-qa-q0-guard-report.json`.

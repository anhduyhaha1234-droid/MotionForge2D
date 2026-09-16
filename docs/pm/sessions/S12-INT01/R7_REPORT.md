# S12-LC3-INT R7 round 1 transport report

## Status

`ROUND1_TRANSPORT_COMPLETE_NOT_PUSHED` — transport provenance only; not an approval or closure. The combined candidate carries the exact R7 bytes of all five lanes; final combined/global gates and Codex review remain pending (`NOT_APPROVED / NOT_CLOSED`).

## Owner, route, boundary

- Hermes INT owner (unchanged): session `20260915_201612_9c9e7c`; route `ocg/deepseek-v4.1-flash` / provider `custom` / fallback `OFF` / native thinking ON.
- Candidate: worktree `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Pre-INT HEAD `35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86` (wave-base), clean tree, no `MERGE_HEAD`/`index.lock`/active hooks.
- Manager B order executed exactly: serial local `git merge --no-ff -m "Merge commit '<sha>' into codex/s12-lc3-luna-integration"`, order VAL → RETRY → B01 → BRIDGE → QA. Zero conflicts. No rebase/reset/stash/clean/force; no push; no source/test/conflict hand edits.

### Literal correction (documented, not a deviation)

The RETRY commit literal in the transport prompt and in `EXPORT_HANDOFF.json` reads `4ce3b136c8c9d7bd7c1aceace590dfb6a8c2d15ab` (41 hex chars — one duplicated `c`; impossible as a SHA-1). The resolved exact commit is `4ce3b136c8c9d7bd7c1aeace590dfb6a8c2d15ab` (40 chars): branch `codex/s12-lc3-luna-retry` tip; parent `35f6cb2…`; own diff = exactly the handoff's 3 files with `421 insertions(+), 27 deletions(-)`; and `A/manager/NO_ACTIVE_WRITER.json` itself records the 40-char form. Transport used the resolved commit; both forms are recorded here.

### Pre-merge verification (per lane)

| Lane | Branch tip == pinned | Owner worktree porcelain (expected) | Allowlist containment |
|---|---|---|---|
| VAL | `86b1a2a…` ✓ | `?? work/` (expected) ✓ | own diff = exact handoff 8-file list ✓ |
| RETRY | `4ce3b136c8c9d7bd7c1aeace590dfb6a8c2d15ab` ✓ (literal corrected) | `""` ✓ | own diff = exact handoff 3-file list ✓ |
| B01 | `a027c59…` ✓ | `""` ✓ (ephemeral `-c safe.directory` override; no global config change) | chain delta ⊆ B01 allowlist (8 files) ✓ |
| BRIDGE | `dae7632…` ✓ | `""` ✓ | chain delta ⊆ BRIDGE allowlist (13 files) ✓ |
| QA | `958d021…` ✓ | `""` ✓ | chain delta ⊆ QA scope incl. the authorized `tests/s12/s12-t03a/test_s12_export_migration.py` compatibility patch ✓ |

## Lane merges

| # | Lane | Source commit | Merge commit | Parents (first, second) | Delta | Diffstat |
|---|---|---|---|---|---|---|
| 1 | VAL | `86b1a2a42dbe2829b2c15b2ec629b74f359578f5` | `0ea57b5d38a9025605c22ccb17f19b5e3c5e9951` | `35f6cb2…`, `86b1a2a…` | 8 exact | 1427+/4− |
| 2 | RETRY | `4ce3b136c8c9d7bd7c1aeace590dfb6a8c2d15ab` | `2942efb59296354b5e975b18a83bc04ef3d481de` | `0ea57b5…`, `4ce3b13…` | 3 exact | 421+/27− |
| 3 | B01 | `a027c59d0c455b37f062be2e5c7bb4cbd59619ad` | `4cd2966fbfdfea943241e3d71d216b9fa1dc13f3` | `2942efb…`, `a027c59…` | 8 exact | 752+/46− |
| 4 | BRIDGE | `dae7632516d70d6978c980888202d6a33cee14b7` | `761414a4ea326eacde3478d2fd92661ba70d79f6` | `4cd2966…`, `dae7632…` | 13 exact | 4409+/136− |
| 5 | QA | `958d02121c361b4b38dafcda923aecf2814723cc` | `8704ec020960e67205cfeb93f4e54bda019205ae` | `761414a…`, `958d021…` | 6 exact | 564+/36− |

Every merge exited 0; post-merge `git diff --check` exit 0; `git status --porcelain` empty after each merge. Chain notes: B01/BRIDGE/QA lanes were each locally synced to `35f6cb2` beforehand (merge-base of every lane vs the candidate = `35f6cb2`), so each transported delta is only that lane's R7 work — no cross-lane path was pulled. Known pre-existing stderr warning (identical to R5/R6): `fatal: bad object refs/codex/turn-diffs/…` + `failed to perform geometric repack`, always exit 0, tree unaffected.

## Final verification

- Transport tip: `8704ec020960e67205cfeb93f4e54bda019205ae`.
- Union delta vs `35f6cb2…`: exactly **38 paths** (8+3+8+13+6, disjoint), `7573 insertions(+), 249 deletions(-)`.
- `git diff --check` over the full range: exit 0. `git status --porcelain`: empty.

## Static gates (changed scope)

- `python -B -m compileall -q app` → exit 0.
- `python -B -m py_compile` on the 24 changed/new `.py` files → exit 0.
- `ruff check --select F` (same 24 files) → exit 0 — `All checks passed!` (no F-class findings; no waiver needed).
- Informational full-ruleset `ruff check` → exit 1, 136 style-class diagnostics: 102×E501, 13×N802, 7×I001, 6×SIM105, 2×SIM103, 2×N818, 1×SIM108, 1×SIM102, 1×B904, 1×B007. None are F-class; INT made no edit to address any diagnostic. (2×N818 + several SIM entries are the inherited publication.py class carried forward; positions per raw log.)

## Evidence index (INT lane)

- `COMMAND_LEDGER.jsonl` — every command: executable/argv/cwd/UTC window/elapsed/exit + stdout/stderr SHA-256.
- `R7_INT_RAW_PROVENANCE.txt` — machine-concatenated stdout/stderr of every recorded command.
- `manifest_transport.tsv` / `manifest_static.tsv` / `manifest_docs.tsv`, `r7_int_round1.sh`, `r7_int_ledger.py` (copied to the INT evidence root).
- Manager-provided pre-guards (`guard-allow-pre.json`, `guard-protected-pre.json`) untouched.

## Hand-off notes

- Combined candidate now carries: VAL F01 lease/publication serialization (new `app/services/s12_export/publication_lease_guard.py` + lease-only additions in `app/persistence/s12_export.py`), RETRY F02 union identity semantics, B01 F03 exact source timing (new `app/services/structural_lock_source_timing.py`), BRIDGE F04 B03–B06 authority bridge (new `app/services/source_locked_timeline.py` + suite), QA R7 prep/inventory + authorized migration-compat patch.
- No push; no approval/closure; waiting on Manager B final combined gates + Codex review. `NOT_CLOSED`.

# S12INT transport ledger — S12-LC3-INT (wave base `2594de06`)

Transport provenance only. This ledger does not approve, accept or close anything; Codex reviews the candidate.

## 1. Identity and boundary

- Task ID: `S12-LC3-INT` (Manager packet `manager/packets/S12-LC3-INT-transport-roundC.md`).
- Owner session as dispatched: `20260915_201612_9c9e7c` (`--resume`).
- **Actual executing session: `20260924_214735_cd0f35`** — proven by the session's FIRST user message in the read-only
  `state.db` (`sessions.id='20260924_214735_cd0f35'`, first message id `224302`, content begins
  `# S12-LC3-INT — Git-only transport of the Manager-verified ranges into PRODUCT`; newest content match).
  `parent_session_id` is `NULL` for this row, i.e. this state.db does not record the `--resume` parent — disclosed,
  not inferred (see discipline note about never pairing resume parents by dispatch order).
- Route: `ocg/deepseek-v4.1-flash`, provider `custom` (`http://127.0.0.1:20128/v1`, `chat_completions`), thinking ON, fallback OFF.
- Candidate (PRODUCT): `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Baseline HEAD (Manager-measured fresh): `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`; `git status --porcelain` = 0 before and after.
- Evidence root: `C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/mf-core-tool-delivery-20260924/20260924T1055Z/S12INT`
  (raw command transcript: `raw/S12INT_TRANSPORT_RAW.txt`).
- Method: serial local `git merge --no-ff -m …`. **Git-only**: no rebase / reset / stash / restore / clean / force-push,
  no push, no amend of published history, no hand edit of any code or test, no conflict resolution by editing.
  Merge (not cherry-pick) was chosen so that each Manager-verified source SHA itself becomes an **ancestor** of the
  frozen candidate — strictly stronger provenance than a replay that rewrites SHAs; the introduced delta is proven
  byte-identical to the source range delta (see §3).

## 2. Transported commits — one row per commit

| # | Lane | Source SHA (full) | Commit subject | Method | Result SHA in PRODUCT | Conflicts | Own delta (measured) |
|---|---|---|---|---|---|---|---|
| 1 | MF-P1-QC-EVIDENCE | `de5435b9a29d7e47812f5c76ef0db27cd10bfca2` | real persisted evidence for all ten QC detectors | `merge --no-ff` of range HEAD `2809f9c8…` | `76f50bee8b1e9a0a1b172aea693f7fcf5d77aa42` | none | 12 files, +3876/−3 |
| 2 | MF-P1-QC-EVIDENCE | `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11` | correction round C: library target identity + independent rendered observation | `merge --no-ff` (range HEAD) | `76f50bee8b1e9a0a1b172aea693f7fcf5d77aa42` | none | 11 files, +2289/−168 |
| 3 | MF-P1-UI-BUILD | `bd16c6db2c6f93d5f2cb704638b29bd71393b787` | wrap AppNav `useSearchParams` in a Suspense boundary | `merge --no-ff` | `6871745dfed1f6c113cb5daeb095ba3342c4a338` | none | 6 files, +496/−3 |
| 4 | S12-LC3-QA | `13fa732d6c5570f41630c9af87326d7cfc675285` | prepare the product-P1 public-chain QA suite (preparation round) | `merge --no-ff` of range HEAD `22815ed4…` (merge-base `5947088e…`, i.e. **not** a descendant of the wave base) | `f991e243f5dfa7e42a04948504af0863cc92fa43` | none | 9 files, +1991/−4 |
| 5 | S12-LC3-QA | `cee2c5990b02043bd8f9f6c09d2d2be7ebc26378` | typed engine cases + QA-preparation round C | `merge --no-ff` (same merge commit) | `f991e243f5dfa7e42a04948504af0863cc92fa43` | none | 3 files, +276/−3 |
| 6 | S12-LC3-QA | `22815ed47b4169cc53961240547d0536c7180027` | wrap the long denial assertion in the engine-case test (ruff E501) | `merge --no-ff` (range HEAD) | `f991e243f5dfa7e42a04948504af0863cc92fa43` | none | 1 file, +4/−1 |

Row 1 full SHA: `de5435b9a29d7e47812f5c76ef0db27cd10bfca2` — existence itself checked with
`git rev-parse --verify de5435b^{commit}` plus `git log -1 --format="%H|%s"` (its parent is the wave base `2594de06…`,
so the QC range is a linear 2-commit chain). Disclosure: a first draft of this row carried a well-formed but
**non-existent** 40-hex SHA, because bare `git rev-parse <40hex>` echoes a syntactically valid argument back without
checking it, so the echo read like a resolution; `git log -1 <sha>` then answered `fatal: bad object`, and the real SHA
was read out of the commit chain. Rule applied from here on: use `--verify` (or a log/parent read), never a bare
`rev-parse` echo, before writing a SHA into a record. The exact range command is reproduced verbatim in §2.1.

### 2.1 Exact commands (verbatim, run from the candidate worktree)

```
git merge --no-ff -m "Merge MF-P1-QC-EVIDENCE 2809f9c8dd5cca5a2be86e80a2f190a11a0fff11 (all ten QC detectors persisted + correction round C; Manager VERIFIED, 68 passed)" 2809f9c8dd5cca5a2be86e80a2f190a11a0fff11
git merge --no-ff -m "Merge MF-P1-UI-BUILD bd16c6db2c6f93d5f2cb704638b29bd71393b787 (AppNav Suspense boundary; build RC 0 + tsc RC 0; Manager VERIFIED)" bd16c6db2c6f93d5f2cb704638b29bd71393b787
git merge --no-ff -m "Merge S12-LC3-QA 22815ed47b4169cc53961240547d0536c7180027 (public-chain QA suite 47 passed/3 skipped; QA2 BLOCKED_DEPENDENCY until this candidate; Manager VERIFIED)" 22815ed47b4169cc53961240547d0536c7180027
```

Merge results (measured, real output):

- M1 `76f50bee8b1e9a0a1b172aea693f7fcf5d77aa42` parents `2594de06…` + `2809f9c8…`; merge rc 0; `porcelain_after=0`; `git diff --check` rc 0; 14 files +5997/−3.
- M2 `6871745dfed1f6c113cb5daeb095ba3342c4a338` parents `76f50bee…` + `bd16c6db…`; merge rc 0; `porcelain_after=0`; `git diff --check` rc 0; 6 files +496/−3.
- M3 `f991e243f5dfa7e42a04948504af0863cc92fa43` parents `6871745d…` + `22815ed4…`; merge rc 0; `porcelain_after=0`; `git diff --check` rc 0; 11 files +2270/−7.
- Zero conflicts on all three merges; no `git merge --abort` was needed.

QC delta check executed before merging (read-only, to justify using one merge for a 2-commit range): the two
pre-existing files that the divergent QA range also touches had identical blob ids at the QA merge-base `5947088e…`
and at the wave base `2594de06…` — `tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py` =
`7085b32ae2414cba80602b1514cf67212874c353`, `tests/test_s09_t06_backend_authority.py` =
`4587e58133d37d927fd31803e7dbfc4047d55517` — and the wave base range `5947088e..2594de06` contains no commit touching
`tests/product_p1/**`, `tests/s12/s12-lc3-qa-r6/**` or `tests/test_s09_t06_backend_authority.py`.

## 3. Provenance and integrity proofs (all measured)

- **Ancestry** (`git merge-base --is-ancestor <sha> HEAD`): `2809f9c8…` = YES, `bd16c6db…` = YES, `22815ed4…` = YES.
  So all three Manager-verified SHAs themselves are ancestors of the frozen candidate; a reviewer can re-run the same
  predicate without trusting this document.
- **Delta equivalence** (source range delta vs merge-introduced delta, `git diff --no-color --binary`):

| Lane | source delta | merge-introduced delta | sha256 (both) | identical |
|---|---|---|---|---|
| QC | `git diff 2594de06 2809f9c8…` | `git diff 76f50bee^1 76f50bee` | `f02c6ea6aaa8b26ceba06eaf46003c7796b47b31db333af1d34ff560f107e114` | YES |
| UI | `git diff 2594de06 bd16c6db…` | `git diff 6871745^1 6871745` | `9568591c5183141557f1a70d300253fac724b9a424fc6c5a5fbc49d5bde7bc95` | YES |
| QA | `git diff 5947088e 22815ed4…` | `git diff f991e243^1 f991e243` | `80417aa10887de94babe69f57b310046fbcece7e9bcbb96e605f2de09b5f0276` | YES |

- **Union delta** `2594de06…HEAD`: 31 paths, 8763 insertions(+), 13 deletions(-) (name-status in raw transcript).
- **Per-path byte equality vs the source trees** — stronger than a range delta, because it proves no path was silently
  rewritten and no conflict resolution was applied. Command shape:
  `git diff --name-only <lane-source-sha> HEAD -- <the paths that lane itself touched>`:

| Lane | Paths checked | Result |
|---|---|---|
| QC | `app/services/qc_evidence`, `app/workflow/qc_checks_handler.py`, `tests/product_p1/qc_evidence`, `docs/pm/sessions/MF-P1-QC-EVIDENCE` | 0 differences |
| UI | `frontend/src/components/layout/AppNav.tsx`, `frontend/src/__tests__/product_p1`, `docs/pm/sessions/MF-P1-UI-BUILD` | 0 differences |
| QA | `tests/product_p1/__init__.py`, `tests/product_p1/public_chain`, `tests/s12/s12-lc3-qa-r6`, `tests/test_s09_t06_backend_authority.py` | 0 differences |

  Blob spot-check for the QA lane (`git rev-parse <src>:<path>` vs `git rev-parse HEAD:<path>`): `public_chain_cases.py`,
  `test_public_chain_frozen_candidate.py`, `test_r6_b01i_public_chain.py`, `test_s09_t06_backend_authority.py` — all IDENTICAL.

  **Scoping note (measured — read it before judging the raw transcript).** A first pass used the parent filter
  `tests/product_p1` for the QA lane and reported **5** differing paths. Those five are `A` (added) entries under
  `tests/product_p1/qc_evidence/**` — the **QC** lane's files, which the QA source tree never had, so they differ from the
  QA side by definition. They are not QA paths and not a transport defect: the QA range's own paths (row above) show 0
  differences, and all QA-touched files are blob-identical at source and at HEAD. Rule: scope the equality filter to the
  paths the lane actually touched, never to a parent directory that two lanes share.
- **Commit list** `git log --oneline 2594de06..f991e243…` — 9 lines (3 merge commits + 6 transported source commits).
- `git status --porcelain` = 0 after every merge and at freeze (only git-ignored `.pytest_cache/`, `.ruff_cache/` and
  `__pycache__/` are ever produced by the checks; `git check-ignore` confirms they are ignored, so they are not strays).

## 4. Static / consistency check on the frozen candidate (no running server)

| Check (at `f991e243…`) | Real result |
|---|---|
| `python -c "import app"` | `APP_IMPORT_OK …\app\__init__.py`, rc 0 |
| `python -c "import app.services.qc_evidence"` | `QC_EVIDENCE_OK`, rc 0 |
| `python -c "import app.workflow.qc_checks_handler"` | `QC_HANDLER_OK`, rc 0 |
| `python -c "import app.main"` | `APP_MAIN_IMPORT_OK`, rc 0 |
| `python -m compileall -q app/services/qc_evidence app/workflow/qc_checks_handler.py` | rc 0 |
| `python -m ruff check --select F app/services/qc_evidence app/workflow/qc_checks_handler.py tests/product_p1` | `All checks passed!`, rc 0 |
| `git status --porcelain` | 0 |

Cheap touched-module test run: `python -m pytest tests/product_p1/qc_evidence -q -p no:cacheprovider` — see
`S12INT_REPORT.md` §4 for the measured number (raw: `raw/pytest_qc_evidence.txt`). The Manager's own measured
command at `2809f9c` took 185.25 s, so the first attempt under a 180 s terminal limit was cut short at 66 dots —
that was a timeout, **not** a failure, and the run was repeated with a sufficient window.

## 5. QA-tree advance (step 4 of the packet)

Pre-flight quiescence evidence (do not take the packet's word for it — measured at 2026-09-24T14:52Z):

- receipt `manager/receipts/S12-LC3-QA-resume-after-502.json`: `exit_code=0`, `ended_at_utc=2026-09-24T14:46:19.352496+00:00`, `pid=34664`.
- that pid is absent from the live process table; no process writing inside the QA worktree.
- QA worktree `git status --porcelain` = 0; last tracked write is the commit itself (HEAD commit time 2026-09-24 21:28:39 +0700);
  the only files with a later mtime are git-ignored `.ruff_cache/**` entries.

Advance (in `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa`, branch `codex/s12-lc3-luna-qa`):

```
git merge --ff-only f991e243f5dfa7e42a04948504af0863cc92fa43
```

Measured: `Updating 22815ed..f991e24` / `Fast-forward`, rc 0, no conflicts, `porcelain_after=0`, `git diff --check` rc 0,
and `git merge-base --is-ancestor f991e243… HEAD` = YES. **QA branch HEAD: `22815ed47b…` → `f991e243f5dfa7e42a04948504af0863cc92fa43`**
(identical to the frozen candidate SHA). The QA2 gate was `RUNNING/BLOCKED_DEPENDENCY` precisely because the frozen
integrated candidate did not exist and QC `2809f9c8`/UI `bd16c6db` were not in the integration head; both conditions
are now satisfied on disk. Running the QA public chain itself remains the QA owner's step, not INT's, and INT did not
run it.

## 6. Freeze

- **Frozen integrated HEAD (candidate): `f991e243f5dfa7e42a04948504af0863cc92fa43`**; `HEAD^` = `6871745dfed1f6c113cb5daeb095ba3342c4a338`.
- Timestamp of freeze (UTC): `2026-09-24T15:02Z` (raw transcript header `2026-09-24T14:52:30Z` … see `raw/`).
- `docs/pm/sessions/S12-INT01/FROZEN_CANDIDATE.md` carries the same SHA.
- A docs-only commit **on top of** the frozen candidate records this ledger, the frozen-candidate file and the report,
  scoped to `docs/pm/sessions/S12-INT01/**` (the lane's declared write set). That commit changes no code and no test;
  the tree it produces is identical to the candidate except inside `docs/pm/sessions/S12-INT01/**`.

## 7. Disclosed conditions (not waived)

- `git merge`/commit printed `fatal: bad object refs/codex/turn-diffs/captures/…/base` + `error: failed to perform
  geometric repack` on every merge **while still succeeding**. That is git's automatic maintenance (`gc --auto`) hitting
  a pre-existing broken ref that belongs to another tool's namespace; every merge rc was 0 and the resulting commits are
  intact (`rev-parse`, parents, `--stat` all measured after the fact). Not "fixed" — refs outside this task were not touched.
- Nothing was pushed. `origin` was not contacted. MAIN/master was not touched.
- No range was reported blocked; no conflict occurred, so nothing had to be routed back to a lane owner.

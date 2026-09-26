# S12INT transport ledger — S12-LC3-INT (wave base `2594de06`)
> **ROUND D2 (2026-09-26) — read this first.** The current frozen integrated candidate is
> **`09489bab2c5513b731d92ade492a6017780f9373`** (round D2). Round D's candidate `04541443ff6dada4fe464e315888ac58a0dbfcd9`
> and round C's `f991e243f5dfa7e42a04948504af0863cc92fa43` are **superseded but preserved** — both remain ancestors of the
> current candidate, round D's record is in **SS9** and round C's in **SS8**; everything from SS1-SS7 below is round C's own
> ledger, kept verbatim. Round D2's transport row is in **SS10**.


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

## 8. History - superseded candidates (kept, not deleted)

| Round | Candidate SHA | HEAD^ | Frozen / created (UTC) | Delta transported | Evidence root |
|---|---|---|---|---|---|
| C | `f991e243f5dfa7e42a04948504af0863cc92fa43` | `6871745dfed1f6c113cb5daeb095ba3342c4a338` | frozen `2026-09-24T15:04:34Z` | QC `2594de06..2809f9c8` + UI `2594de06..bd16c6db` + QA `13fa732d..22815ed4` | `.../mf-core-tool-delivery-20260924/20260924T1055Z/S12INT` |
| **D (current)** | **`04541443ff6dada4fe464e315888ac58a0dbfcd9`** | `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` | created `2026-09-24T19:21:36Z`, freeze recorded `2026-09-24T19:27:22Z` | QC `2809f9c8..5ea5928a` + QA `f991e243..bf40b76e` | `.../mf-core-tool-delivery-20260924/20260924T1557Z/S12INT` |

`f991e243...` was NOT rewritten and NOT removed: it is an ancestor of the round-D candidate (it was the QA range's start).
Round C's ledger (`SS1`-`SS7` of this file, 158 lines, unchanged) stays readable as the record of that round; its
`FROZEN_CANDIDATE.md` text was superseded in place, as the round-D packet instructed.

## 9. ROUND D (2026-09-25) - transport rows, proofs and freeze

### 9.1 Identity and boundary

- Task: `S12-LC3-INT`, round D (transport of two Manager-verified ranges on top of the round-C candidate).
- Route: `ocg/deepseek-v4.1-flash`, provider `custom` (`http://127.0.0.1:20128/v1`, `chat_completions`), thinking ON, fallback OFF.
- Candidate tree: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Baseline HEAD (measured fresh at recon): `0ccbee343ed48a18737863427793f46fb9694411`; `git status --porcelain` = 0 before and after.
- Method: serial local `git merge --no-ff -m ...`, **Git-only**: no rebase / reset / stash / restore / clean / amend, no
  push, no hand edit of any code or test, no conflict resolution by editing. Merging (not cherry-picking) keeps each
  Manager-verified source SHA itself an **ancestor** of the candidate, and the introduced delta is proven byte-identical
  to the source range delta (SS9.3).
- Evidence root: `C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/mf-core-tool-delivery-20260924/20260924T1557Z/S12INT`
  (raw transcript `raw/proofs_transport.txt`, command ledger `raw/commands_ledger.jsonl`).

### 9.2 Rows - one per transported range

| # | Lane | Source range (full) | Commits | Method | Result SHA in PRODUCT | Conflicts | Merge-introduced delta (measured) |
|---|---|---|---|---|---|---|---|
| 1 | MF-P1-QC-EVIDENCE | `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11..5ea5928a216ec33f8598bab9669d873ad9d37e53` | 1 (`5ea5928a...`) | `git merge --no-ff` | `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` | none | 5 files, +2123/-199 |
| 2 | S12-LC3-QA | `f991e243f5dfa7e42a04948504af0863cc92fa43..bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` | 1 (`bf40b76e...`) | `git merge --no-ff` | `04541443ff6dada4fe464e315888ac58a0dbfcd9` | none | 1 file, +1619/-353 |

Both ranges are single-commit and their own merge-base with the pre-merge HEAD equals the range START
(`git merge-base 0ccbee34 5ea5928a` = `2809f9c8`; `git merge-base ccd0aba6 bf40b76e` = `f991e243`), which is why one merge
per range introduces exactly the tip delta (no replay of earlier commits).

**Exact commands (verbatim, run from the candidate worktree):**

```
git merge --no-ff 5ea5928a216ec33f8598bab9669d873ad9d37e53 -m "Merge MF-P1-QC-EVIDENCE 5ea5928a216ec33f8598bab9669d873ad9d37e53 (NR03/NR04 per-role identity + bounded payload; fixes WinError-206 regression; Manager VERIFIED)"
git merge --no-ff bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628 -m "Merge S12-LC3-QA bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628 (NR07 qc-items route tolerance + authoritative zero-item/eligibility facts; failure persistence proven; path-class guard scans chain body; S12 readiness gate asserted BLOCKED_EXACT; Manager VERIFIED)"
```

Measured: M1 = `ccd0aba6...` parents `0ccbee34... + 5ea5928a...`, rc 0, porcelain 0; M2 = `04541443...` parents
`ccd0aba6... + bf40b76e...`, rc 0, porcelain 0. Zero conflicts; no `git merge --abort` needed.

### 9.3 Provenance and integrity proofs (all measured, raw in `raw/proofs_transport.txt`)

- **Ancestry** (`git merge-base --is-ancestor <sha> HEAD`): `5ea5928a...` = YES (rc 0), `bf40b76e...` = YES (rc 0) - the
  Manager-verified SHAs themselves are ancestors, so a reviewer can re-run the predicate without trusting this file.
- **Range-tip existence**: both checked with `git rev-parse --verify <sha>^{commit}` (rc 0) - never a bare `rev-parse`
  echo, which returns a syntactically valid 40-hex string for a non-existent object.
- **Real 2-parent merges**: `git rev-list --parents -n 1` -> `ccd0aba6... 0ccbee34... 5ea5928a...` and
  `04541443... ccd0aba6... bf40b76e...`.
- **Delta equivalence** (sha256 of `git diff --no-color --binary`, source range delta vs merge-introduced delta):

| Lane | source delta | merge delta | sha256 (both) | identical |
|---|---|---|---|---|
| QC | `git diff 2809f9c8 5ea5928a` (128,188 B) | `git diff ccd0aba6^1 ccd0aba6` (128,188 B) | `44b41776b6a9ecf351ba094cd17554533b2a56546699b6d5876ec1131484342e` | YES |
| QA | `git diff f991e243 bf40b76e` (102,648 B) | `git diff 04541443^1 04541443` (102,648 B) | `8c88b36d28a34fe67b7b77715afc384fb95091461e584e8e89dd4a1889825288` | YES |

- **Per-path byte equality vs the source trees**, scoped to the paths each lane itself touched (NOT to a shared parent
  directory - that mistake produced 5 phantom differences in round C):
  `git diff --name-only <lane-source-sha> HEAD -- <lane's own paths>` -> **QC 0 differences, QA 0 differences**.
  Blob ids (`git rev-parse <src>:<path>` vs `HEAD:<path>`) all IDENTICAL: `compose.py 9452c669`,
  `observe.py 4cb72abc`, `sources.py 0a331e1d`, `test_correction_round_c.py 23bf5caf`,
  `test_correction_round_d.py ffe47792`, `test_public_chain_frozen_candidate.py 36990043`.
  Worktree bytes are deliberately NOT compared across trees: with `core.autocrlf=true` the same blob checks out with
  different byte counts, which reads as a false difference.
- **Union delta** `0ccbee34...HEAD`: 6 paths, +3742 / -552 (numstat in the raw transcript).
- `git status --porcelain` = 0 after every merge, after the checks, and at freeze.

### 9.4 Checks at the frozen HEAD (no running server)

| Check (at `04541443...`) | Real result |
|---|---|
| import smoke: `app`, `app.services.qc_evidence.{compose,observe,sources}`, `app.workflow.qc_checks_handler`, `app.main` | `IMPORT_SMOKE_OK`, rc 0 |
| `python -m compileall -q app/services/qc_evidence tests/product_p1/qc_evidence tests/product_p1/public_chain` | rc 0 |
| `python -m pytest tests/product_p1/qc_evidence -q` | **82 passed, 153 warnings in 244.30 s** (rc 0; wall 247 s) |
| `python -m pytest tests/product_p1/public_chain -q` | **29 passed, 2 skipped, 15 warnings in 12.03 s** (rc 0; wall 13 s) |
| `git status --porcelain` | 0 |

`qc_evidence` moved 68 -> 82 because the QC range adds `test_correction_round_d.py` (+1146 lines) and +35/-1 to
`test_correction_round_c.py`. Both suites ran in the background with a window large enough for their real duration (a
180 s window CUTS this suite at ~66 dots; that is a timeout, not a failure).

### 9.5 QA-tree advance (step 4) - only after measured quiescence

Pre-flight quiescence, measured not assumed: receipt `manager/receipts/S12-LC3-QA-roundD-finish.json`
`exit_code=0`, `ended_at_utc=2026-09-24T19:18:15.394504+00:00`, `pid=25928` (main round-D receipt: rc 0,
`ended_at_utc=2026-09-24T18:49:26Z`, `pid=33108`); both pids absent from the live process table; QA worktree
`git status --porcelain` = 0; two snapshots 43 s apart (`19:23:23Z` / `19:24:06Z`) identical in HEAD, porcelain and
newest-file mtime; the newest write in the tree (`19:15:54Z`) predates the receipt end.

```
git merge --ff-only 04541443ff6dada4fe464e315888ac58a0dbfcd9
```

Measured: `Updating bf40b76..0454144` / `Fast-forward`, rc 0, conflict-free, porcelain 0, `git diff --check` rc 0,
`git merge-base --is-ancestor bf40b76... HEAD` = **YES**. **QA HEAD: `bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` ->
`04541443ff6dada4fe464e315888ac58a0dbfcd9`.** Running the QA public chain remains the QA owner's step; INT did not run it.

### 9.6 Freeze

- **Frozen integrated HEAD (candidate): `04541443ff6dada4fe464e315888ac58a0dbfcd9`**; `HEAD^` = `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e`.
- Candidate created `2026-09-24T19:21:36Z`; freeze recorded `2026-09-24T19:27:22Z` (local `2026-09-25 02:27:22 +07`).
- `docs/pm/sessions/S12-INT01/FROZEN_CANDIDATE.md` (overwritten for this round) and `raw/frozen_candidate.json` carry the same SHA.

### 9.7 Disclosed conditions (not waived) and out-of-scope

- Both merges printed `fatal: bad object refs/codex/turn-diffs/captures/.../base` + `error: failed to perform geometric
  repack` and still succeeded (rc 0; verified after the fact). Pre-existing broken ref in another tool's namespace; not "fixed".
- Nothing pushed (`git branch -r --contains HEAD` = 0); `origin` not contacted; MAIN/`master` untouched (`a40e368`).
- Not transported, per standing scope: `MF-TOOL-CONTRACT 542570d..f0b918b` (C-CONTRACT, stays `BLOCKED_DEPENDENCY`), the
  CORE experiment trees (COMFY / VIDEO14B / BENCH), UI (no new commit this round).
- **Out of scope, not fixed by INT (by instruction):** the product-level finding QA measured - S12 export readiness is
  unreachable through public APIs (readiness needs a completed *current-scope full* QC run, while the full run is refused
  for the fixture's single segment). Product gap for the code branches / Codex to route; QA recorded it as an asserted
  `BLOCKED_EXACT` control. INT did transport + freeze only.

## 10. ROUND D2 (2026-09-26) - transport row, proofs and freeze

### 10.1 Identity and boundary

- Task: `S12-LC3-INT`, round D2 (transport of the single Manager-verified round-D2 range on top of the round-D candidate).
- Route: `ocg/deepseek-v4.1-flash`, provider `custom` (`http://127.0.0.1:20128/v1`, `chat_completions`), thinking ON, fallback OFF.
- Owner session (resumed): `20260924_214735_cd0f35` (same owner as round D; no new owner minted).
- Candidate tree: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Baseline HEAD (measured fresh at recon): `b077da0c8f8a96422d887b5877231bbd70e66324` (the round-D docs commit);
  `git status --porcelain` = 0 before and after.
- Method: one local `git merge --no-ff -m ...`, **Git-only**: no rebase / reset / stash / restore / clean / amend, no push,
  no hand edit of any code or test, no conflict resolution by editing. Merging (not cherry-picking) keeps the
  Manager-verified source SHA itself an **ancestor** of the candidate, and the introduced delta is proven byte-identical
  to the source range delta (SS10.3).
- Evidence root (same literal root as round D):
  `C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/mf-core-tool-delivery-20260924/20260924T1557Z/S12INT`
  (raw transcript `raw/proofs_transport_d2.txt`, command ledger `raw/commands_ledger.jsonl`).

### 10.2 Row - one per transported range

| # | Lane | Source range (full) | Commits | Method | Result SHA in PRODUCT | Conflicts | Merge-introduced delta (measured) |
|---|---|---|---|---|---|---|---|
| 3 | S12-LC3-QA | `04541443ff6dada4fe464e315888ac58a0dbfcd9..641b83df49d79b0b6fb02baab094a4bfddb03aa5` | 1 (`641b83df...`) | `git merge --no-ff` | `09489bab2c5513b731d92ade492a6017780f9373` | none | 1 file, +157/-17 |

The range is single-commit and its own merge-base with the pre-merge HEAD equals the range START
(`git merge-base b077da0c 641b83df` = `04541443ff6dada4fe464e315888ac58a0dbfcd9`), which is why one merge introduces
exactly the tip delta (no replay of earlier commits). The measured delta matches the Manager scope check.

**Exact command (verbatim, run from the candidate worktree):**

```
git merge --no-ff 641b83df49d79b0b6fb02baab094a4bfddb03aa5 -m "Merge S12-LC3-QA 641b83df49d79b0b6fb02baab094a4bfddb03aa5 (round D2: refusal accounting is three-way expected/tolerated/unexpected, probe tolerance bounded by CLIENT_ERRORS, why_expected replaced by the measured per-detector matrix; Manager VERIFIED)"
```

Measured: M3 = `09489bab...` parents `b077da0c... + 641b83df...`, rc 0, porcelain 0, zero conflicts, no `git merge --abort`.

### 10.3 Provenance and integrity proofs (all measured, raw in `raw/proofs_transport_d2.txt`)

- **Ancestry** (`git merge-base --is-ancestor <sha> HEAD`): `641b83df...` = YES (rc 0), `04541443...` = YES (rc 0) - the
  Manager-verified SHA itself is an ancestor, so a reviewer can re-run the predicate without trusting this ledger.
- **Range-tip existence**: `git rev-parse --verify 641b83df...^{commit}` rc 0 (never a bare `rev-parse` echo, which returns
  a syntactically valid 40-hex string for a non-existent object).
- **Real 2-parent merge**: `git rev-list --parents -n 1` -> `09489bab... b077da0c... 641b83df...`.
- **Delta equivalence** (sha256 of `git diff --no-color --binary`, source range delta vs merge-introduced delta):

| Lane | source delta | merge delta | sha256 (both) | bytes (both) | identical |
|---|---|---|---|---|---|
| QA | `git diff 04541443 641b83df` | `git diff 09489bab^1 09489bab` | `6e9ab1ae4503f49fef378c9fcfceae58ae9ec464c7ddf293a05b3e0a88555566` | 11,597 | YES |

- **Per-path equality vs the SOURCE TREE**, scoped to the path the lane itself touched (NOT to a shared parent directory -
  that mistake produced 5 phantom differences in round C):
  `git diff --name-only 641b83df HEAD -- tests/product_p1/public_chain/test_public_chain_frozen_candidate.py` -> **0**.
  Blob ids (`git rev-parse <tip>:<path>` vs `HEAD:<path>`) IDENTICAL: `f67e822742cf25535dc0f25d9934882aa2a27473`
  (at the round-D candidate / range start: `369900436b9543bd20b71af07d53b877daedc81f`).
  Worktree bytes are deliberately NOT compared across trees: with `core.autocrlf=true` the same blob checks out with
  different byte counts, which reads as a false difference.
- **Union delta** `b077da0c...HEAD`: 1 path, +157 / -17 (numstat in the raw transcript).
- `git status --porcelain` = 0 after the merge, after the checks, and at freeze; `git diff --check` rc 0.

### 10.4 Checks at the frozen HEAD (no running server)

| Check (at `09489bab2c5513b731d92ade492a6017780f9373`) | Real result |
|---|---|
| import smoke: `app`, `app.services.qc_evidence.{compose,observe,sources}`, `app.workflow.qc_checks_handler`, `app.main` | `IMPORT_SMOKE_OK`, rc 0 |
| `python -m compileall -q app/services/qc_evidence tests/product_p1/qc_evidence tests/product_p1/public_chain` | rc 0 |
| `python -m pytest tests/product_p1/qc_evidence -q` | **82 passed, 153 warnings in 251.37 s** (rc 0; wall 254 s) |
| `python -m pytest tests/product_p1/public_chain -q` | **30 passed, 2 skipped, 15 warnings in 12.18 s** (rc 0; wall 13 s) |
| `git status --porcelain` before checks / after suites | 0 / 0 |

`qc_evidence` stays at 82 passed (the range touches no file in that suite). `public_chain` moved 29 -> 30 passed (2 skipped
unchanged): the transported commit's own new non-vacuity unit test (a 5xx on a probe stays `unexpected`), so the delta is
explained by the transported commit. Both suites ran in the background with a window larger than their real duration (a
180 s window CUTS the 251 s suite at ~66 dots; that is a timeout, not a failure).

### 10.5 QA-tree advance (step 4) - only after measured quiescence

Pre-flight quiescence, measured not assumed: receipt `manager/receipts/S12-LC3-QA-roundD2.json` `exit_code=0`,
`started_at_utc=2026-09-26T10:35:07.191772+00:00`, `ended_at_utc=2026-09-26T10:59:37.520661+00:00`, `pid=6136`,
`duration_seconds=1470.329`; pid `6136` absent from the live process table; QA worktree `git status --porcelain` = 0; two
snapshots 60 s apart (`11:04:05Z` / `11:05:05Z`) identical in HEAD, porcelain line count and the newest-file mtime/size
list (1869 tracked-tree files scanned each time); the newest write in the tree (95,917 B) is `10:48:26Z`, before the
receipt end.

```
git merge --ff-only 09489bab2c5513b731d92ade492a6017780f9373
```

Measured: `Updating 641b83d..09489ba` / `Fast-forward`, rc 0, conflict-free, porcelain 0, `git diff --check` rc 0,
`git merge-base --is-ancestor 641b83df... HEAD` = **YES**. **QA HEAD: `641b83df49d79b0b6fb02baab094a4bfddb03aa5` ->
`09489bab2c5513b731d92ade492a6017780f9373`** (identical to the frozen candidate). Running the QA public chain remains the
QA owner's step; INT did not run it.

### 10.6 Freeze

- **Frozen integrated HEAD (candidate #2): `09489bab2c5513b731d92ade492a6017780f9373`**;
  `HEAD^` = `b077da0c8f8a96422d887b5877231bbd70e66324`, `HEAD^2` = `641b83df49d79b0b6fb02baab094a4bfddb03aa5`.
- Candidate created `2026-09-26T11:02:26Z`; freeze recorded `2026-09-26T11:08:12Z` (local `2026-09-26 18:08:12 +07`).
- `docs/pm/sessions/S12-INT01/FROZEN_CANDIDATE.md` (overwritten for this round, round C and round D kept in its SS7
  history table) and `raw/frozen_candidate.json` (round D's freeze JSON kept byte-for-byte as
  `raw/frozen_candidate_roundD.json`) carry the same SHA.

### 10.7 Disclosed conditions (not waived) and out-of-scope

- The merge printed `fatal: bad object refs/codex/turn-diffs/captures/.../base` + `error: failed to perform geometric
  repack` and still succeeded (rc 0; verified after the fact). Pre-existing broken ref in another tool's namespace; not "fixed".
- Nothing pushed (`git branch -r --contains HEAD` = 0); `origin` not contacted; `MAIN` (`C:/Users/Admin/MotionForge2D`)
  read-only and untouched (`a40e368f7c47c232cf2eeed9fb185c5972cb98ba`); its 103 porcelain entries pre-date this session.
- Not transported, per standing scope: `MF-TOOL-CONTRACT 542570d..f0b918b` (C-CONTRACT, stays `BLOCKED_DEPENDENCY`), the
  CORE experiment trees (COMFY / VIDEO14B / BENCH), UI (no new commit this round).
- **Out of scope, not fixed by INT (by instruction):** the product-level finding the QA lane measured - S12 export
  readiness is unreachable through public APIs because 3 of 8 visual QC detectors (`contact_break`, `z_order_error` =
  `QC_EVIDENCE_MISSING`; `edge_halo` = `QC_EVIDENCE_DEPENDENCY`) have no producer on this candidate. Routed finding:
  delta A -> `S08-T02`, delta B / chain leg -> `S08-T05`. INT did transport + freeze only; no visual verdict, no
  `APPROVED` / `CLOSED`, no gate loosened, no product code or test touched by INT.

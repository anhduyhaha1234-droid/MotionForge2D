# S12INT — S12-LC3-INT report (Git-only transport into PRODUCT, wave base `2594de06`)
> **ROUND D (2026-09-25) — read this first.** The current frozen integrated candidate is
> **`04541443ff6dada4fe464e315888ac58a0dbfcd9`** (SS1-SS9 below are round C's report, kept verbatim). Round D's
> transport rows, proofs and freeze are in **SS10**. Round C's candidate
> `f991e243f5dfa7e42a04948504af0863cc92fa43` is superseded but preserved (ledger SS8).


Transport report only. INT does not approve, accept or close; Codex reviews the candidate.

## 1. Identity

- Task: `S12-LC3-INT` — packet `manager/packets/S12-LC3-INT-transport-roundC.md`.
- Dispatched owner session: `20260915_201612_9c9e7c` (`--resume`).
- **Actual executing session (mine): `20260924_214735_cd0f35`** — proven by reading the session's own first user message
  out of the read-only `state.db` (row `sessions.id='20260924_214735_cd0f35'`, first message id `224302`, text begins
  `# S12-LC3-INT — Git-only transport of the Manager-verified ranges into PRODUCT`; newest content match).
  `parent_session_id` for that row is `NULL`, so this database does not record which session was resumed — disclosed as
  unproven lineage rather than claimed.
- Route: `ocg/deepseek-v4.1-flash`, provider `custom` (`http://127.0.0.1:20128/v1`, `chat_completions`), thinking ON, fallback OFF.
- Candidate: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration` @ `codex/s12-lc3-luna-integration`.
- Baseline (Manager-measured fresh): `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`, porcelain 0 — re-measured by me at start.
- Evidence root: `…/outputs/mf-core-tool-delivery-20260924/20260924T1055Z/S12INT` (`raw/` = command transcript).

## 2. Per-range transport result

| Lane | Source range | Method | Exact command | Result SHA | Conflicts |
|---|---|---|---|---|---|
| MF-P1-QC-EVIDENCE | `2594de06..2809f9c8dd5cca5a2be86e80a2f190a11a0fff11` (2 commits) | merge `--no-ff` | `git merge --no-ff -m "Merge MF-P1-QC-EVIDENCE 2809f9c8…" 2809f9c8dd5cca5a2be86e80a2f190a11a0fff11` | `76f50bee8b1e9a0a1b172aea693f7fcf5d77aa42` | none |
| MF-P1-UI-BUILD | `2594de06..bd16c6db2c6f93d5f2cb704638b29bd71393b787` (1 commit) | merge `--no-ff` | `git merge --no-ff -m "Merge MF-P1-UI-BUILD bd16c6db…" bd16c6db2c6f93d5f2cb704638b29bd71393b787` | `6871745dfed1f6c113cb5daeb095ba3342c4a338` | none |
| S12-LC3-QA | `13fa732d…..22815ed47b4169cc53961240547d0536c7180027` (3 commits; merge-base `5947088e…`) | merge `--no-ff` (real 3-way) | `git merge --no-ff -m "Merge S12-LC3-QA 22815ed4…" 22815ed47b4169cc53961240547d0536c7180027` | `f991e243f5dfa7e42a04948504af0863cc92fa43` | none |

Per-merge measured results: rc 0 each; `porcelain_after=0` each; `git diff --check` rc 0 each; deltas
14 files +5997/−3 (QC), 6 files +496/−3 (UI), 11 files +2270/−7 (QA). Per-commit rows are in
`S12INT_TRANSPORT_LEDGER.md` §2. **Zero conflicts, so no `--abort` and nothing to route back to a lane owner.**

Why merge rather than cherry-pick for the divergent QA range: the packet allowed "cherry-pick (or an equivalent
Git-only replay)". A `--no-ff` merge is the equivalent replay that keeps the Manager-verified SHA itself as an ancestor
of the candidate, and its introduced delta was proven byte-identical to the source range delta — strictly stronger
provenance than a rewrite. Pre-merge read-only check justified the clean outcome: the two pre-existing files the QA
range shares with the wave base had identical blob ids at `5947088e…` and `2594de06…`, and no commit in
`5947088e..2594de06` touched `tests/product_p1/**`, `tests/s12/s12-lc3-qa-r6/**` or `tests/test_s09_t06_backend_authority.py`.

## 3. Frozen integrated HEAD

- **`f991e243f5dfa7e42a04948504af0863cc92fa43`** (`M3`, the QA merge commit); `HEAD^` = `6871745dfed1f6c113cb5daeb095ba3342c4a338`.
- Chain: `2594de06` → `76f50be` (QC) → `6871745` (UI) → `f991e243` (QA).
- Union delta vs baseline: 31 paths, +8763/−13. Full `git log --oneline 2594de06..f991e243…` (9 lines) is in
  `FROZEN_CANDIDATE.md` §2.
- Ancestry: all three Manager-verified SHAs are ancestors (`git merge-base --is-ancestor` → YES ×3).
- Delta equivalence: source-vs-merge patch bytes identical — QC `f02c6ea6…`, UI `9568591c…`, QA `80417aa1…`.

## 4. Build / consistency check on the frozen HEAD (no running server)

| Check | Real output |
|---|---|
| `python -c "import app"` | `APP_IMPORT_OK …\app\__init__.py`, rc 0 |
| `python -c "import app.services.qc_evidence"` | `QC_EVIDENCE_OK`, rc 0 |
| `python -c "import app.workflow.qc_checks_handler"` | `QC_HANDLER_OK`, rc 0 |
| `python -c "import app.main"` | `APP_MAIN_IMPORT_OK`, rc 0 |
| `python -m compileall -q app/services/qc_evidence app/workflow/qc_checks_handler.py` | rc 0 |
| `python -m ruff check --select F app/services/qc_evidence app/workflow/qc_checks_handler.py tests/product_p1` | `All checks passed!`, rc 0 |
| `python -m pytest tests/product_p1/qc_evidence -q -p no:cacheprovider` | **68 passed, 125 warnings in 184.61 s**, rc 0 (`raw/pytest_qc_evidence.txt`) |
| `git status --porcelain` | 0 (after every merge, after the suites, at freeze) |

Per-path byte equality vs the source trees (addendum, measured): `git diff --name-only <lane-source> HEAD -- <that lane's
own paths>` returns **0 differences** for all three lanes, and each QA-touched file (`tests/product_p1/__init__.py`,
`tests/product_p1/public_chain/*`, `tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py`,
`tests/test_s09_t06_backend_authority.py`) has an **identical blob id** at the QA source and at HEAD. A first pass that
filtered on the parent directory `tests/product_p1` reported 5 differing paths; those are `A`-entries belonging to the QC
lane (`tests/product_p1/qc_evidence/**`), absent from the QA source tree — a filter-scoping artefact, not a transport
defect. Detail: `S12INT_TRANSPORT_LEDGER.md` §3.

The QC module suite result reproduces the Manager's own measured 68 passed at `2809f9c`. The QA `public_chain` suite and
the S09 authority module were **not** run by INT (they are the QA lane's chain, and QA2 is defined against the frozen
candidate after this freeze) — not attempted, not claimed.

## 5. QA-tree advance (packet step 4)

Pre-flight quiescence — measured, not assumed: QA receipt `manager/receipts/S12-LC3-QA-resume-after-502.json` reports
`exit_code=0`, `ended_at_utc=2026-09-24T14:46:19.352496+00:00`, `pid=34664`; that pid is absent from the live process
table; the QA worktree's `git status --porcelain` is 0 and its last tracked write is its own commit (HEAD time
`2026-09-24 21:28:39 +0700`), with only git-ignored `.ruff_cache/**` files newer than that.

Advance: in `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa` (branch `codex/s12-lc3-luna-qa`),
`git merge --ff-only f991e243f5dfa7e42a04948504af0863cc92fa43` → `Updating 22815ed..f991e24` / `Fast-forward`, rc 0,
conflict-free, `porcelain_after=0`, `git diff --check` rc 0. **QA branch HEAD: `22815ed47b…` → `f991e243f5dfa7e42a04948504af0863cc92fa43`**
(same SHA as the candidate). QA2's blocker (`RUNNING/BLOCKED_DEPENDENCY`: no frozen candidate; QC `2809f9c8`/UI
`bd16c6db` absent from the integration head) is now satisfied on disk. INT did not run the public chain.

## 6. Freeze artefacts

- `docs/pm/sessions/S12-INT01/S12INT_TRANSPORT_LEDGER.md` — per-commit ledger + integrity proofs + exact commands.
- `docs/pm/sessions/S12-INT01/FROZEN_CANDIDATE.md` — candidate SHA, ranges, commit list, timestamp `2026-09-24T15:04:34Z`.
- `docs/pm/sessions/S12-INT01/LOG.md` §13 — round entry.
- Evidence root `S12INT/`: this report, `S12INT_TRANSPORT_LEDGER.md`, `FROZEN_CANDIDATE.md`,
  `raw/S12INT_TRANSPORT_RAW.txt` (verbatim command transcript), `raw/pytest_qc_evidence.txt`,
  `raw/commands_ledger.jsonl`, `raw/frozen_candidate.json`.
- Bookkeeping: one docs-only commit on top of `f991e243…`, scoped to `docs/pm/sessions/S12-INT01/**` (the lane's
  declared write set) — no code, no test, no other path touched.

## 7. Blocked / routed

- Nothing blocked in this round; no conflict occurred.
- Not part of this transport, deliberately (packet §2): `MF-TOOL-CONTRACT` `5f5fd67..542570d` — remains
  `BLOCKED_DEPENDENCY` on the S13/C-CONTRACT path owner; the CORE experiment trees (COMFY / VIDEO14B / BENCH) stay out of PRODUCT.
- Remaining step after this freeze (not INT's): the QA lane runs the real public chain (QA2) against
  `f991e243…`; the Manager writes `manager/VERIFY_S12INT.md` and reviews the candidate.

## 8. Disclosures (not waived)

1. Every `git merge`/commit printed `fatal: bad object refs/codex/turn-diffs/captures/…/base` +
   `error: failed to perform geometric repack` **while succeeding** — git's `gc --auto` maintenance hitting a
   pre-existing broken ref belonging to another tool's namespace. Each merge rc was 0 and the commits were re-read
   afterwards (`rev-parse`, parents, `--stat`). Not "fixed"; refs outside this task were not touched.
2. The first QC-suite attempt was cut off by a 180 s terminal limit at 66 dots. That was a timeout, **not** a failure:
   the Manager's own measured run of the same command takes 185.25 s. Re-run with a sufficient window → 68 passed in 184.61 s.
3. A first draft of the ledger's row 1 carried a well-formed but non-existent 40-hex SHA, because a bare
   `git rev-parse <40hex>` echoes a syntactically valid argument back without checking existence, and the echo read like
   a resolution. `git log -1 <sha>` answered `fatal: bad object`; the real SHA
   (`de5435b9a29d7e47812f5c76ef0db27cd10bfca2`) was then read out of the commit chain and the ledger was corrected. The
   corrected row is what ships.
4. Nothing was pushed; `origin` was never contacted; MAIN/`master` untouched; no rebase / reset / stash / restore / clean /
   force-push; no amend of published history; no code or test was hand-edited by INT.

## 9. Terminal

`TASK_SUBMITTED` — all three ranges transported, the candidate frozen and recorded, the PRODUCT tree clean.
INT does not emit `APPROVED` / `CLOSED`; Codex reviews the candidate.

## 10. ROUND D (2026-09-25) — transport round D + freeze `04541443`

Packet: `manager/packets/S12-LC3-INT-transport-roundD.md` (two Manager-verified ranges). Route unchanged:
`ocg/deepseek-v4.1-flash` / provider `custom` / thinking ON / fallback OFF. Candidate tree
`C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.

### 10.1 Transported (Git-only, zero conflicts, zero hand edits)

| Lane | Source range | Method | Result SHA | Delta |
|---|---|---|---|---|
| MF-P1-QC-EVIDENCE | `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11..5ea5928a216ec33f8598bab9669d873ad9d37e53` (1 commit) | `git merge --no-ff` | `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` | 5 files, +2123/-199 |
| S12-LC3-QA | `f991e243f5dfa7e42a04948504af0863cc92fa43..bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` (1 commit) | `git merge --no-ff` | `04541443ff6dada4fe464e315888ac58a0dbfcd9` | 1 file, +1619/-353 |

Baseline `0ccbee343ed48a18737863427793f46fb9694411` (porcelain 0 at recon). Both deltas equal the Manager's own scope
check (5 files +2123/-199; 1 file +1619/-353) to the line. Each range's merge-base with the pre-merge HEAD equals the
range START (`2809f9c8`, `f991e243`), so each merge introduces exactly the tip delta. **Frozen candidate
`04541443ff6dada4fe464e315888ac58a0dbfcd9`**, `HEAD^` = `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e`.
`git log --oneline 0ccbee34..HEAD` = 4 lines (2 merge commits + the 2 transported source commits); union delta 6 paths
+3742/-552; porcelain 0 after every step.

### 10.2 Provenance proofs (measured; raw `raw/proofs_transport.txt`)

- `git merge-base --is-ancestor 5ea5928a… HEAD` = YES; `… bf40b76e… HEAD` = YES — the Manager-verified SHAs themselves are
  ancestors (not rewritten copies). Both tips verified with `git rev-parse --verify <sha>^{commit}` (never a bare
  `rev-parse` echo, which fabricates a plausible 40-hex answer for a non-existent object).
- Delta equivalence, sha256 of `git diff --no-color --binary`: QC source == QC merge
  (`44b41776b6a9ecf351ba094cd17554533b2a56546699b6d5876ec1131484342e`, 128,188 B both); QA source == QA merge
  (`8c88b36d28a34fe67b7b77715afc384fb95091461e584e8e89dd4a1889825288`, 102,648 B both).
- Per-path byte equality vs each SOURCE TREE, scoped to the lane's own paths: 0 differences for both lanes; all 6 blobs
  IDENTICAL (`compose.py 9452c669`, `observe.py 4cb72abc`, `sources.py 0a331e1d`, `test_correction_round_c.py 23bf5caf`,
  `test_correction_round_d.py ffe47792`, `test_public_chain_frozen_candidate.py 36990043`).

### 10.3 Checks at the frozen candidate (real output)

- import smoke (`app`, `app.services.qc_evidence.{compose,observe,sources}`, `app.workflow.qc_checks_handler`, `app.main`) rc 0;
  `compileall` over the touched scope rc 0.
- `pytest tests/product_p1/qc_evidence -q` → **82 passed, 153 warnings in 244.30 s** (rc 0; wall 247 s). The count moved
  68 → 82 because the transported QC range adds `test_correction_round_d.py` (+1146 lines) and +35/-1 to round C.
- `pytest tests/product_p1/public_chain -q` → **29 passed, 2 skipped, 15 warnings in 12.03 s** (rc 0; wall 13 s).
- `git status --porcelain` = 0 before the checks and after both suites.

### 10.4 QA-tree advance (only after measured quiescence)

Receipt `manager/receipts/S12-LC3-QA-roundD-finish.json`: `exit_code=0`, `ended_at_utc=2026-09-24T19:18:15Z`, `pid=25928`;
main round-D receipt rc 0 ended `18:49:26Z` pid `33108`; both pids absent from the live process table; QA worktree
porcelain 0; two snapshots 43 s apart (`19:23:23Z` / `19:24:06Z`) identical in HEAD/porcelain/newest mtime and the newest
tree write (`19:15:54Z`) predates the receipt end. Then `git merge --ff-only 04541443…` →
`Updating bf40b76..0454144` / `Fast-forward`, rc 0, porcelain 0, and
`git merge-base --is-ancestor bf40b76… HEAD` = YES. **QA HEAD: `bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` →
`04541443ff6dada4fe464e315888ac58a0dbfcd9`.** Running the chain stays the QA owner's step — INT did not run it.

### 10.5 Not done (deliberately)

- Not transported: `MF-TOOL-CONTRACT 542570d..f0b918b` (C-CONTRACT, stays `BLOCKED_DEPENDENCY`), CORE experiment trees
  (COMFY / VIDEO14B / BENCH), UI (no new commit this round).
- **Not fixed, by instruction:** the product-level finding QA measured — S12 export readiness unreachable via public APIs
  (needs a completed current-scope FULL QC run; the full run is refused for the fixture's single segment). Product gap for
  the code branches / Codex to route; QA recorded it as an asserted `BLOCKED_EXACT` control. INT did transport + freeze only.
- No push (`git branch -r --contains HEAD` = 0), `origin` not contacted, MAIN/`master` untouched, no rebase / reset /
  stash / restore / clean / amend, no code or test hand-edited.
- Disclosed: both merges printed the pre-existing `fatal: bad object refs/codex/turn-diffs/…` + `error: failed to perform
  geometric repack` maintenance noise while succeeding (rc 0, verified after the fact).

### 10.6 Terminal

`TASK_SUBMITTED` — both ranges transported, the candidate frozen and recorded, the PRODUCT tree clean. INT does not emit
`APPROVED` / `CLOSED`.

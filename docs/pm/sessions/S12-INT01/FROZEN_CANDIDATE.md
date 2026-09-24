# S12-LC3-INT — FROZEN INTEGRATED CANDIDATE (PRODUCT) — ROUND D

- Round: D (transport of two Manager-verified ranges on top of the round-C candidate).
- Freeze recorded (UTC): `2026-09-24T19:27:22Z` — local `2026-09-25 02:27:22 +07`.
- Candidate commit created (UTC): `2026-09-24T19:21:36Z` — local `2026-09-25 02:21:36 +07` (git `%cI` of the final merge).
- PRODUCTION tree: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Baseline at dispatch (Manager-measured fresh): `0ccbee343ed48a18737863427793f46fb9694411`, `git status --porcelain` = 0.
- **FROZEN INTEGRATED HEAD (candidate QA must test): `04541443ff6dada4fe464e315888ac58a0dbfcd9`**
- `HEAD^` = `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` (the first transport merge, i.e. the QC-EVIDENCE merge).
- `git status --porcelain` = 0 at freeze; `git diff --check` rc 0.

## 1. Transported ranges (Git-only, zero conflicts, zero hand edits)

| Lane | Source range | Commits | Method | Result SHA in PRODUCT | Conflicts | Merge-introduced delta (measured) |
|---|---|---|---|---|---|---|
| **MF-P1-QC-EVIDENCE** | `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11..5ea5928a216ec33f8598bab9669d873ad9d37e53` | 1 (`5ea5928a…`) | `git merge --no-ff` | `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` | none | 5 files, +2123/−199 |
| **S12-LC3-QA** | `f991e243f5dfa7e42a04948504af0863cc92fa43..bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` | 1 (`bf40b76e…`) | `git merge --no-ff` | `04541443ff6dada4fe464e315888ac58a0dbfcd9` | none | 1 file, +1619/−353 |

Both ranges are **single-commit**: `git merge-base <pre-merge HEAD> <range tip>` equals the range START in each case
(`2809f9c8…` for QC, `f991e243…` for QA — both already ancestors of the integration branch from round C), so each merge
introduces exactly the tip's own delta and no replay of the earlier commits. Measured, not assumed.

Not transported (per the standing scope, deliberately): `MF-TOOL-CONTRACT 542570d..f0b918b` (C-CONTRACT path — stays
`BLOCKED_DEPENDENCY`, must NOT enter PRODUCT), the CORE experiment trees (COMFY `a1dd05c`, VIDEO14B, BENCH), and UI
(no new UI commit this round).

## 2. Exact commands (verbatim, run from the candidate worktree)

```
git merge --no-ff 5ea5928a216ec33f8598bab9669d873ad9d37e53 -m "Merge MF-P1-QC-EVIDENCE 5ea5928a216ec33f8598bab9669d873ad9d37e53 (NR03/NR04 per-role identity + bounded payload; fixes WinError-206 regression; Manager VERIFIED)"
git merge --no-ff bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628 -m "Merge S12-LC3-QA bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628 (NR07 qc-items route tolerance + authoritative zero-item/eligibility facts; failure persistence proven; path-class guard scans chain body; S12 readiness gate asserted BLOCKED_EXACT; Manager VERIFIED)"
```

Measured results: M1 rc 0 (`Merge made by the 'ort' strategy.`), porcelain 0; M2 rc 0, porcelain 0. Zero conflicts; no
`git merge --abort` was needed. (Both merges printed the disclosed pre-existing `fatal: bad object
refs/codex/turn-diffs/…` + `error: failed to perform geometric repack` maintenance noise while succeeding — see §7.)

## 3. `git log --oneline 0ccbee343ed48a18737863427793f46fb9694411..HEAD`

```
0454144 Merge S12-LC3-QA bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628 (NR07 qc-items route tolerance + authoritative zero-item/eligibility facts; failure persistence proven; path-class guard scans chain body; S12 readiness gate asserted BLOCKED_EXACT; Manager VERIFIED)
ccd0aba Merge MF-P1-QC-EVIDENCE 5ea5928a216ec33f8598bab9669d873ad9d37e53 (NR03/NR04 per-role identity + bounded payload; fixes WinError-206 regression; Manager VERIFIED)
bf40b76 S12-LC3-QA round D finish: qc-items route tolerance + authoritative zero-item/eligibility facts; clean-QC (audio band) asserted; path-class guard scans the chain body and proves the exclusion hides nothing; S12 readiness gate becomes an asserted BLOCKED_EXACT control
5ea5928 MF-P1-QC-EVIDENCE correction round D: per-role identity (NR04) + bounded argv payload (fixes WinError 206)
```

Union delta vs the round-D baseline: **6 paths, +3742 / −552**.

## 4. Proof that the candidate carries VERIFIED provenance (all measured)

- **Ancestry** — `git merge-base --is-ancestor <sha> HEAD`: `5ea5928a216ec33f8598bab9669d873ad9d37e53` → YES (rc 0),
  `bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` → YES (rc 0). The Manager-verified SHAs themselves are ancestors, so a
  reviewer can re-run the same predicate without trusting this document.
- **Real 2-parent merges** — `git rev-list --parents -n 1`:
  `ccd0aba6… 0ccbee34… 5ea5928a…` and `04541443… ccd0aba6… bf40b76e…`.
- **Delta equivalence** — sha256 of `git diff --no-color --binary` on source-range delta vs merge-introduced delta
  (`<merge>^1..<merge>`):

| Lane | source delta | merge delta | sha256 (both) | identical |
|---|---|---|---|---|
| QC | `2809f9c8…5ea5928a…` | `ccd0aba6^1..ccd0aba6` | `44b41776b6a9ecf351ba094cd17554533b2a56546699b6d5876ec1131484342e` | YES |
| QA | `f991e243…bf40b76e…` | `04541443^1..04541443` | `8c88b36d28a34fe67b7b77715afc384fb95091461e584e8e89dd4a1889825288` | YES |

- **Per-path byte equality vs the SOURCE TREES**, scoped to the paths each lane itself touched (never a shared parent
  directory): `git diff --name-only <lane-source-sha> HEAD -- <lane's own paths>` → **0 differences** for both lanes.
  Blob spot-check (`git rev-parse <src>:<path>` vs `git rev-parse HEAD:<path>`), 6/6 IDENTICAL:
  `compose.py 9452c669…`, `observe.py 4cb72abc…`, `sources.py 0a331e1d…`,
  `test_correction_round_c.py 23bf5caf…`, `test_correction_round_d.py ffe47792…`,
  `test_public_chain_frozen_candidate.py 36990043…`. (Blob ids, not worktree bytes: `core.autocrlf=true` makes the same
  blob check out with different byte counts in two worktrees, which is a known false-difference.)
- Raw transcript: `raw/proofs_transport.txt` (+ the four `.patch` files it hashes).

## 5. Checks at the frozen HEAD (no running server) — real output

| Check (at `04541443…`) | Result |
|---|---|
| `import app, app.services.qc_evidence.{compose,observe,sources}, app.workflow.qc_checks_handler, app.main` | `IMPORT_SMOKE_OK …\app\__init__.py`, rc 0 |
| `python -m compileall -q app/services/qc_evidence tests/product_p1/qc_evidence tests/product_p1/public_chain` | rc 0 |
| `python -m pytest tests/product_p1/qc_evidence -q` | **82 passed, 153 warnings in 244.30 s** (rc 0; wall 247 s) |
| `python -m pytest tests/product_p1/public_chain -q` | **29 passed, 2 skipped, 15 warnings in 12.03 s** (rc 0; wall 13 s) |
| `git status --porcelain` before checks / after suites | 0 / 0 |

The `qc_evidence` suite count moved 68 → **82** because the transported QC range adds
`tests/product_p1/qc_evidence/test_correction_round_d.py` (1,146 lines) and +35/−1 to `test_correction_round_c.py` —
the same suite the Manager measured at `2809f9c`, now including round D. Raw logs:
`raw/check_candidate.log`, `raw/pytest_qc_evidence.txt`, `raw/pytest_public_chain.txt`. Both suites were run in the
background with a sufficient window (this suite needs ~250 s; a short timeout CUTS it rather than failing it).

## 6. QA tree advance (packet step 4)

Pre-flight quiescence proven, NOT assumed (receipt `manager/receipts/S12-LC3-QA-roundD-finish.json`:
`exit_code=0`, `ended_at_utc=2026-09-24T19:18:15.394504+00:00`, `pid=25928`; both QA pids `25928` and `33108` absent
from the live process table; QA worktree `git status --porcelain` = 0; two snapshots 43 s apart
(`19:23:23Z` vs `19:24:06Z`) identical in HEAD, porcelain and newest-file mtime, and the newest write in the tree
(`19:15:54Z`) predates the receipt's end — i.e. nothing was written after the writer exited).

In `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa`, branch `codex/s12-lc3-luna-qa`:

```
git merge --ff-only 04541443ff6dada4fe464e315888ac58a0dbfcd9
```

Measured: `Updating bf40b76..0454144` / `Fast-forward`, rc 0, conflict-free, `porcelain_after=0`, `git diff --check` rc 0,
and `git merge-base --is-ancestor bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628 HEAD` = **YES** (rc 0) — the QA range is still
an ancestor of the new QA HEAD. **QA branch HEAD: `bf40b76e7b3bdf6d80b4e12cb34adcaa21a5c628` → `04541443ff6dada4fe464e315888ac58a0dbfcd9`**
(identical to the frozen candidate). Running the public chain remains the QA owner's step — INT did not run it.

## 7. History — superseded candidate (kept, not deleted)

| Round | Candidate SHA | HEAD^ | Frozen at (UTC) | Evidence root |
|---|---|---|---|---|
| C | `f991e243f5dfa7e42a04948504af0863cc92fa43` | `6871745dfed1f6c113cb5daeb095ba3342c4a338` | `2026-09-24T15:04:34Z` | `…/mf-core-tool-delivery-20260924/20260924T1055Z/S12INT` |
| **D (current)** | **`04541443ff6dada4fe464e315888ac58a0dbfcd9`** | `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` | `2026-09-24T19:27:22Z` (created `19:21:36Z`) | `…/mf-core-tool-delivery-20260924/20260924T1557Z/S12INT` |

`f991e243` is **superseded** by this round: it is still an ancestor of the new candidate (it was the QA range's start and
a transport target in round C), so nothing was rewritten — the new candidate strictly contains it plus the two round-D
ranges. Round C's own ledger/report remain in the repository history
(`S12INT_TRANSPORT_LEDGER.md` §8 keeps the round-C record; it is not deleted).

## 8. Disclosed conditions (not waived)

- Both merges printed `fatal: bad object refs/codex/turn-diffs/captures/…/base` + `error: failed to perform geometric
  repack` and **still succeeded** (rc 0; parents, `--stat` and ancestry re-measured after the fact). That is git's
  automatic maintenance (`gc --auto`) hitting a pre-existing broken ref in another tool's namespace. Not "fixed" — refs
  outside this task were not touched. Same condition as round C.
- Nothing was pushed. `git branch -r --contains HEAD` = 0 branches; `origin` was not contacted. MAIN/`master` untouched
  (`a40e368`). One writer per tree; no rebase / reset / stash / restore / clean / amend; no hand edit of any code or test.
- No range was blocked and no conflict occurred, so nothing had to be routed back to a lane owner.
- **Out of scope (NOT fixed by INT, by instruction):** the product-level finding QA measured — S12 export readiness is
  unreachable through public APIs (readiness needs a completed *current-scope full* QC run, while the full run is refused
  for the fixture's single segment). That is a product gap for the code branches / Codex to route; QA recorded it as an
  asserted `BLOCKED_EXACT` control. INT performed transport + freeze only.

## 9. Bookkeeping commit (disclosed, no code impact)

A docs-only commit on top of the frozen SHA above records this file, the round-D ledger rows and the round-D report,
scoped to `docs/pm/sessions/S12-INT01/**` (this lane's declared write set). It changes no code and no test, so the tree
stays byte-identical to the candidate everywhere outside that directory. **The SHA in the header above is still the
candidate QA must test.**

## 10. Terminal

`TASK_SUBMITTED` — INT transports and freezes; it does not approve, accept or close. Reviewer: Codex.

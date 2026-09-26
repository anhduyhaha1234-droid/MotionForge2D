# S12-LC3-INT — FROZEN INTEGRATED CANDIDATE (PRODUCT) — ROUND D2

- Round: D2 (transport of the single Manager-verified round-D2 range on top of the round-D candidate).
- Freeze recorded (UTC): `2026-09-26T11:08:12Z` — local `2026-09-26 18:08:12 +07`.
- Candidate commit created (UTC): `2026-09-26T11:02:26Z` — local `2026-09-26 18:02:26 +07` (git `%cI` of the merge).
- PRODUCTION tree: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Baseline at dispatch (Manager-measured fresh): `b077da0c8f8a96422d887b5877231bbd70e66324` (the round-D docs commit), `git status --porcelain` = 0.
- **FROZEN INTEGRATED HEAD (candidate #2, what QA must test): `09489bab2c5513b731d92ade492a6017780f9373`**
- `HEAD^` = `b077da0c8f8a96422d887b5877231bbd70e66324` (the round-D docs commit; `HEAD^2` = the transported QA tip `641b83df…`).
- `git status --porcelain` = 0 at freeze; `git diff --check` rc 0.

## 1. Transported range (Git-only, zero conflicts, zero hand edits)

| Lane | Source range | Commits | Method | Result SHA in PRODUCT | Conflicts | Merge-introduced delta (measured) |
|---|---|---|---|---|---|---|
| **S12-LC3-QA** | `04541443ff6dada4fe464e315888ac58a0dbfcd9..641b83df49d79b0b6fb02baab094a4bfddb03aa5` | 1 (`641b83df…`) | `git merge --no-ff` | `09489bab2c5513b731d92ade492a6017780f9373` | none | 1 file, +157/−17 |

The range is **single-commit**: `git merge-base <pre-merge HEAD> <range tip>` = `04541443ff6dada4fe464e315888ac58a0dbfcd9`
= the range START (measured, not assumed), so the merge introduces exactly the tip's own delta and no replay of any earlier
commit. The delta matches the Manager scope check (1 file, +157/−17).

What the range carries (round D2, QA's own measurement — **not** re-litigated by INT): the refusal accounting in
`tests/product_p1/public_chain/test_public_chain_frozen_candidate.py` is now three-way (`expected` / `tolerated`
read-probe / `unexpected`), tolerance is bounded by `CLIENT_ERRORS` and wired through constants, `why_expected` for the
QC full-scope refusal is replaced by the measured per-detector matrix, plus a no-pin non-vacuity unit test.

Not transported (per the standing scope, deliberately): `MF-TOOL-CONTRACT 542570d..f0b918b` (C-CONTRACT path — stays
`BLOCKED_DEPENDENCY`, must NOT enter PRODUCT), the CORE experiment trees (COMFY / VIDEO14B / BENCH), and UI (no new
commit this round).

## 2. Exact command (verbatim, run from the candidate worktree)

```
git merge --no-ff 641b83df49d79b0b6fb02baab094a4bfddb03aa5 -m "Merge S12-LC3-QA 641b83df49d79b0b6fb02baab094a4bfddb03aa5 (round D2: refusal accounting is three-way expected/tolerated/unexpected, probe tolerance bounded by CLIENT_ERRORS, why_expected replaced by the measured per-detector matrix; Manager VERIFIED)"
```

Measured: rc 0 (`Merge made by the 'ort' strategy.`), porcelain 0, zero conflicts, no `git merge --abort` needed.
(The merge printed the disclosed pre-existing `fatal: bad object refs/codex/turn-diffs/…` + `error: failed to perform
geometric repack` maintenance noise while succeeding — see §7.)

## 3. `git log --oneline b077da0c8f8a96422d887b5877231bbd70e66324..HEAD`

```
09489ba Merge S12-LC3-QA 641b83df49d79b0b6fb02baab094a4bfddb03aa5 (round D2: refusal accounting is three-way expected/tolerated/unexpected, probe tolerance bounded by CLIENT_ERRORS, why_expected replaced by the measured per-detector matrix; Manager VERIFIED)
641b83d S12-LC3-QA round D2: refusal accounting is three-way (expected / tolerated read-probe / unexpected); probe tolerance bounded by CLIENT_ERRORS and wired through constants; why_expected for the QC full-scope refusal replaced with the per-detector MEASUREMENT
```

Union delta vs the round-D2 baseline (`b077da0..HEAD`): **1 path, +157 / −17**.

## 4. Proof that the candidate carries VERIFIED provenance (all measured)

- **Ancestry** — `git merge-base --is-ancestor <sha> HEAD`: `641b83df49d79b0b6fb02baab094a4bfddb03aa5` → YES (rc 0),
  `04541443ff6dada4fe464e315888ac58a0dbfcd9` → YES (rc 0). The Manager-verified SHA itself is an ancestor, so a reviewer
  can re-run the predicate without trusting this document.
- **Real 2-parent merge** — `git rev-list --parents -n 1`:
  `09489bab… b077da0c… 641b83df…`.
- **Delta equivalence** — sha256 of `git diff --no-color --binary` on the source-range delta vs the merge-introduced
  delta (`<merge>^1..<merge>`):

| Lane | source delta | merge delta | sha256 (both) | bytes (both) | identical |
|---|---|---|---|---|---|
| QA | `04541443…641b83d` | `09489bab^1..09489bab` | `6e9ab1ae4503f49fef378c9fcfceae58ae9ec464c7ddf293a05b3e0a88555566` | 11,597 | YES |

- **Per-path byte equality vs the SOURCE TREE**, scoped to the path the lane itself touched (never a shared parent
  directory): `git diff --name-only 641b83df… HEAD -- tests/product_p1/public_chain/test_public_chain_frozen_candidate.py`
  → **0 differences**. Blob id `git rev-parse <tip>:<path>` = `git rev-parse HEAD:<path>` =
  `f67e822742cf25535dc0f25d9934882aa2a27473` (at the round-D candidate / range start the same path was
  `369900436b9543bd20b71af07d53b877daedc81f`, i.e. the transport moved it forward exactly once). Blob ids, not worktree
  bytes: `core.autocrlf=true` makes one blob check out with different byte counts in two worktrees, a known false-difference.
- Raw transcript: `raw/proofs_transport_d2.txt` (+ `raw/delta_qa_d2_source.patch` and `raw/delta_qa_d2_merged.patch`,
  which the transcript hashes).

## 5. Checks at the frozen HEAD (no running server) — real output

| Check (at `09489bab…`) | Result |
|---|---|
| `import app, app.services.qc_evidence.{compose,observe,sources}, app.workflow.qc_checks_handler, app.main` | `IMPORT_SMOKE_OK …\app\__init__.py`, rc 0 |
| `python -m compileall -q app/services/qc_evidence tests/product_p1/qc_evidence tests/product_p1/public_chain` | rc 0 |
| `python -m pytest tests/product_p1/qc_evidence -q` | **82 passed, 153 warnings in 251.37 s** (rc 0; wall 254 s) |
| `python -m pytest tests/product_p1/public_chain -q` | **30 passed, 2 skipped, 15 warnings in 12.18 s** (rc 0; wall 13 s) |
| `git status --porcelain` before checks / after suites | 0 / 0 |

`qc_evidence` is unchanged at 82 passed (the round-D2 range touches no file in that suite). `public_chain` moved
29 passed → **30 passed** (+2 skipped unchanged): that is the transported range's own new non-vacuity unit test
(a 5xx on a probe must stay `unexpected`), so the delta is explained by the transported commit and not by the merge.
Raw logs: `raw/check_candidate_d2.log`, `raw/pytest_qc_evidence_d2.txt`, `raw/pytest_public_chain_d2.txt`. Both suites
ran in the background with a window larger than their real duration (a 180 s window would CUT the 251 s suite — a cut is
a timeout, not a failure).

## 6. QA tree advance (packet step 4)

Pre-flight quiescence proven, NOT assumed (receipt `manager/receipts/S12-LC3-QA-roundD2.json`: `exit_code=0`,
`started_at_utc=2026-09-26T10:35:07.191772+00:00`, `ended_at_utc=2026-09-26T10:59:37.520661+00:00`, `pid=6136`,
`duration_seconds=1470.329`; pid `6136` absent from the live process table; QA worktree `git status --porcelain` = 0;
two snapshots 60 s apart (`11:04:05Z` vs `11:05:05Z`) identical in HEAD, porcelain line count and the newest-file
mtime/size list; the newest write in the tree — `tests/product_p1/public_chain/test_public_chain_frozen_candidate.py`,
95,917 B — is `10:48:26Z`, i.e. **before** the receipt end, so nothing was written after the writer exited).

In `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa`, branch `codex/s12-lc3-luna-qa`:

```
git merge --ff-only 09489bab2c5513b731d92ade492a6017780f9373
```

Measured: `Updating 641b83d..09489ba` / `Fast-forward`, rc 0, conflict-free, `porcelain_after=0`, `git diff --check` rc 0,
and `git merge-base --is-ancestor 641b83df49d79b0b6fb02baab094a4bfddb03aa5 HEAD` = **YES** (rc 0) — the lane's own source
tip is still an ancestor of the new QA HEAD. **QA branch HEAD: `641b83df49d79b0b6fb02baab094a4bfddb03aa5` →
`09489bab2c5513b731d92ade492a6017780f9373`** (identical to this frozen candidate). Running the public chain remains the
QA owner's step — INT did not run it.

## 7. History — superseded candidates (kept, not deleted)

| Round | Candidate SHA | HEAD^ | Frozen at (UTC) | Evidence root |
|---|---|---|---|---|
| C | `f991e243f5dfa7e42a04948504af0863cc92fa43` | `6871745dfed1f6c113cb5daeb095ba3342c4a338` | `2026-09-24T15:04:34Z` | `…/mf-core-tool-delivery-20260924/20260924T1055Z/S12INT` |
| D | `04541443ff6dada4fe464e315888ac58a0dbfcd9` | `ccd0aba6cdba1e58ce7436c89ecc17450c79a50e` | `2026-09-24T19:27:22Z` (created `19:21:36Z`) | `…/mf-core-tool-delivery-20260924/20260924T1557Z/S12INT` |
| **D2 (current)** | **`09489bab2c5513b731d92ade492a6017780f9373`** | `b077da0c8f8a96422d887b5877231bbd70e66324` | `2026-09-26T11:08:12Z` (created `11:02:26Z`) | `…/mf-core-tool-delivery-20260924/20260924T1557Z/S12INT` |

Round D's candidate `04541443…` is **superseded but preserved**: it is still an ancestor of the new candidate (it was the
round-D2 range's start, measured above), so nothing was rewritten — the new candidate strictly contains it plus the
round-D2 range. Round C's and round D's own ledger/report records remain in the repository history
(`S12INT_TRANSPORT_LEDGER.md` §8 keeps round C verbatim, §9 keeps round D; neither is deleted) and the round-D freeze
JSON is kept byte-for-byte as `raw/frozen_candidate_roundD.json`.

## 8. Disclosed conditions (not waived)

- The merge printed `fatal: bad object refs/codex/turn-diffs/captures/…/base` + `error: failed to perform geometric
  repack` and **still succeeded** (rc 0; parents, `--stat`, delta equivalence and ancestry re-measured after the fact).
  That is git's automatic maintenance (`gc --auto`) hitting a pre-existing broken ref in another tool's namespace. Same
  condition as rounds C and D; not "fixed" — refs outside this task were not touched.
- Nothing was pushed. `git branch -r --contains HEAD` = 0 branches; `origin` was not contacted. `C:/Users/Admin/MotionForge2D`
  (`MAIN`) is read-only and untouched: HEAD `a40e368f7c47c232cf2eeed9fb185c5972cb98ba`, unchanged; its 103
  `git status --porcelain` entries pre-date this session. One writer per tree; no rebase / reset / stash / restore /
  clean / amend; no hand edit of any code or test; no conflict resolution by editing.
- No range was blocked and no conflict occurred, so nothing had to be routed back to a lane owner.
- **Out of scope (NOT fixed by INT, by explicit instruction):** the product gap the QA lane measured — S12 export
  readiness is unreachable through public APIs because 3 of 8 visual QC detectors (`contact_break`, `z_order_error`
  = `QC_EVIDENCE_MISSING`; `edge_halo` = `QC_EVIDENCE_DEPENDENCY`) have no producer on this candidate. It is a routed
  finding — delta A → `S08-T02`, delta B / chain leg → `S08-T05` — and INT performed transport + freeze only.
  INT also emits no visual verdict and no `APPROVED` / `CLOSED`.

## 9. Bookkeeping commit (disclosed, no code impact)

A docs-only commit on top of the frozen SHA above records this file, the round-D2 ledger rows (§10), the round-D2 report
section and the round-D2 log entry, scoped to `docs/pm/sessions/S12-INT01/**` (this lane's declared write set). It changes
no code and no test, so the tree stays byte-identical to the candidate everywhere outside that directory.
**The SHA in the header above is still the candidate QA must test.**

## 10. Terminal

`TASK_SUBMITTED` — INT transports and freezes; it does not approve, accept or close. Reviewer: Codex.

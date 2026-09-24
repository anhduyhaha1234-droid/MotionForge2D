# S12-LC3-INT — FROZEN INTEGRATED CANDIDATE (PRODUCT)

- Frozen at (UTC): `2026-09-24T15:04:34Z` — local `2026-09-24 22:04:34 +07`.
- PRODUCTION tree: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Baseline at dispatch (Manager-measured fresh): `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`, `git status --porcelain` = 0.
- **FROZEN INTEGRATED HEAD (candidate QA must test): `f991e243f5dfa7e42a04948504af0863cc92fa43`**
- `HEAD^` = `6871745dfed1f6c113cb5daeb095ba3342c4a338`
- `git status --porcelain` = 0 at freeze; `git diff --check` rc 0.

## 1. Transported ranges (Git-only, zero conflicts, zero hand edits)

| Lane | Source range / SHA | Method | Result SHA in PRODUCT |
|---|---|---|---|
| MF-P1-QC-EVIDENCE | `2594de06….2809f9c8dd5cca5a2be86e80a2f190a11a0fff11` (2 commits: `de5435b9a29d7e47812f5c76ef0db27cd10bfca2`, `2809f9c8dd5cca5a2be86e80a2f190a11a0fff11`) | `git merge --no-ff` | `76f50bee8b1e9a0a1b172aea693f7fcf5d77aa42` |
| MF-P1-UI-BUILD | `2594de06….bd16c6db2c6f93d5f2cb704638b29bd71393b787` (1 commit) | `git merge --no-ff` | `6871745dfed1f6c113cb5daeb095ba3342c4a338` |
| S12-LC3-QA | `13fa732d6c5570f41630c9af87326d7cfc675285..22815ed47b4169cc53961240547d0536c7180027` (3 commits; branch merge-base `5947088e4145d71bee6863bfb2619c8e45c2f1d4` — NOT a descendant of the wave base) | `git merge --no-ff` (real 3-way merge) | `f991e243f5dfa7e42a04948504af0863cc92fa43` |

Not transported (per packet, deliberately): `MF-TOOL-CONTRACT` `5f5fd67..542570d` (S13/C-CONTRACT path, stays
`BLOCKED_DEPENDENCY`); the CORE experiment trees (COMFY / VIDEO14B / BENCH).

## 2. `git log --oneline 2594de06..f991e243f5dfa7e42a04948504af0863cc92fa43`

```
f991e24 Merge S12-LC3-QA 22815ed47b4169cc53961240547d0536c7180027 (public-chain QA suite 47 passed/3 skipped; QA2 BLOCKED_DEPENDENCY until this candidate; Manager VERIFIED)
6871745 Merge MF-P1-UI-BUILD bd16c6db2c6f93d5f2cb704638b29bd71393b787 (AppNav Suspense boundary; build RC 0 + tsc RC 0; Manager VERIFIED)
76f50be Merge MF-P1-QC-EVIDENCE 2809f9c8dd5cca5a2be86e80a2f190a11a0fff11 (all ten QC detectors persisted + correction round C; Manager VERIFIED, 68 passed)
22815ed S12-LC3-QA: wrap the long denial assertion in the engine-case test (ruff E501)
cee2c59 S12-LC3-QA: typed engine cases + QA-preparation round C (engine-case split, b01i retained controls)
2809f9c MF-P1-QC-EVIDENCE correction round C: library target identity + independent rendered observation
13fa732 S12-LC3-QA: prepare the product-P1 public-chain QA suite (preparation round)
de5435b MF-P1-QC-EVIDENCE: real persisted evidence for all ten QC detectors
bd16c6d MF-P1-UI-BUILD: wrap AppNav useSearchParams in a Suspense boundary so the production build emits the app
```

Union delta vs the baseline: **31 paths, +8763 / −13**.

## 3. Proof that the candidate carries VERIFIED provenance

- `git merge-base --is-ancestor <sha> f991e243…` → `YES` for all three: `2809f9c8dd…`, `bd16c6db2c…`, `22815ed47b…`
  (the Manager-verified SHAs themselves are ancestors, not rewritten copies).
- Delta equivalence (source range delta vs merge-introduced delta, `git diff --no-color --binary`, sha256 on both):
  QC `f02c6ea6…` = identical; UI `9568591c…` = identical; QA `80417aa1…` = identical.

## 4. Checks at the frozen HEAD (no server required)

| Check | Result |
|---|---|
| `import app` / `app.services.qc_evidence` / `app.workflow.qc_checks_handler` / `app.main` | all rc 0 |
| `compileall` touched app scope | rc 0 |
| `ruff check --select F` touched scope (`app/services/qc_evidence`, `app/workflow/qc_checks_handler.py`, `tests/product_p1`) | `All checks passed!` |
| `pytest tests/product_p1/qc_evidence -q -p no:cacheprovider` | **68 passed, 125 warnings in 184.61 s** (rc 0) — reproduces the Manager's 68 at `2809f9c` |
| `git status --porcelain` | 0 |

## 5. QA tree advance (packet step 4)

QA branch `codex/s12-lc3-luna-qa` advanced **`22815ed47b4169cc53961240547d0536c7180027` → `f991e243f5dfa7e42a04948504af0863cc92fa43`**
via `git merge --ff-only f991e243f5dfa7e42a04948504af0863cc92fa43` → `Fast-forward`, rc 0, conflict-free, porcelain 0.
Pre-flight quiescence proven, not assumed (QA receipt `exit_code=0` @ `2026-09-24T14:46:19Z`, pid 34664 gone from the
process table, worktree porcelain 0, only git-ignored `.ruff_cache/**` written after the lane's own commit).
QA2's dependency is therefore satisfied on disk; **running** the public chain remains the QA owner's step — INT did not run it.

## 6. Bookkeeping commit (disclosed, no code impact)

Docs-only commit(s) are recorded on top of the frozen SHA above, scoped to `docs/pm/sessions/S12-INT01/**` (this lane's
declared write set in `manager/DAG_WRITESET_WAVES.md`): the bookkeeping commit (`S12INT_TRANSPORT_LEDGER.md`,
`S12INT_REPORT.md`, `FROZEN_CANDIDATE.md` (this file), `LOG.md` §13) and a second **verification addendum** commit that
adds the per-path byte-equality proof vs the source trees (§3 of the ledger; §4 of the report). Neither commit changes
any path outside `docs/pm/sessions/S12-INT01/**` — no code, no test — so the tree stays byte-identical to `f991e243…`
everywhere else. **The SHA in the header above is still the candidate QA must test**; the docs commits are bookkeeping
on top of it and do not alter the transported content.

## 7. Terminal

`TASK_SUBMITTED` — INT transports and freezes; it does not approve, accept or close. Nothing pushed; `origin` not
contacted; MAIN/`master` untouched. Reviewer: Codex.

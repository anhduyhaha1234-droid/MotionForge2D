# S12-LC3-INT R6 terminal transport report

## Status

`SPRINT_SUBMITTED / PENDING_CODEX_REVIEW / NOT_CLOSED` — transport provenance only. INT does not approve or close; a partial checkpoint never equals final product acceptance. Broad/product/UI/video gates remain with the Manager after freeze; independent Codex review remains pending.

## Owner, route, boundary

- New Hermes INT owner (one-time transfer from Codex, reason `USER_REQUESTED_PLATFORM_MODEL_TRANSFER`): Hermes session `20260915_201612_9c9e7c`; route `ocg/deepseek-v4.1-flash` / provider `custom` / fallback `OFF`.
- Candidate: worktree `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Pre-INT HEAD `83af5167e9dddc931bc8590f547684c0c811784b`, clean (`git status --porcelain` empty; no `MERGE_HEAD`, no `index.lock`, no hooks).
- Transport: serial local `git merge --no-ff --no-edit`, order VAL → RETRY → B01 → QA. No rebase/reset/stash/clean/force, no push, no conflict-resolution edits (zero conflicts occurred), no production/test/migration/config hand edits by INT.
- External evidence: `C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r6-hermes\20260915T131158Z\INT`.
- Runtime: `C:\Users\Admin\Documents\Codex\work\s12h\20260915T131158Z\INT`.

## Source commits, parents, and exact deltas

### VAL

- Source `535d7c136e0688bad1dc2905d4889a26869c995e`; parent `83af5167e9dddc931bc8590f547684c0c811784b` (verified before merge).
- Direct delta (6) — matches the pinned list exactly:
  - `app/services/s12_export/publication.py`
  - `docs/pm/sessions/S12-LC3-VAL/LOG.md`
  - `docs/pm/sessions/S12-LC3-VAL/REPORT.md`
  - `docs/pm/sessions/S12-LC3-VAL/evidence/20260915T-r6-f02-f03.md`
  - `tests/s12/s12-lc3-val/test_r2_ownership_recovery.py`
  - `tests/s12/s12-lc3-val/test_r6_publication_ownership.py`

### RETRY

- Source `1d9ed94f7a893967765e7d40a710cdcd99e90601`; parent `83af5167e9dddc931bc8590f547684c0c811784b` (verified before merge).
- Direct delta (5) — matches the pinned list exactly:
  - `app/workflow/s12_export_jobs.py`
  - `docs/contracts/s12-export.md`
  - `docs/pm/sessions/S12-LC3-RETRY/LOG.md`
  - `docs/pm/sessions/S12-LC3-RETRY/REPORT.md`
  - `tests/s12/s12-lc3-retry/test_r6_identity_resolution.py`

### B01

- Source tip `c8830b342d678f5defdf17ec66b6c0ad3c6ef1cf`; chain of 2 commits: `9caa22329cbb2cb0c0a07ee36e9878778b5a4496` (parent `83af5167e9dddc931bc8590f547684c0c811784b`) → `c8830b342d678f5defdf17ec66b6c0ad3c6ef1cf` (parent `9caa223…`). Both identities verified before merge.
- Chain delta (8) — matches the pinned list exactly:
  - `app/api/app.py`
  - `app/api/routes/structural_lock.py`
  - `app/schemas/structural_lock.py`
  - `app/services/structural_lock_producer.py`
  - `docs/pm/sessions/S09-LOCK-PRODUCER-B01/CONTRACT.md`
  - `docs/pm/sessions/S09-LOCK-PRODUCER-B01/LOG.md`
  - `docs/pm/sessions/S09-LOCK-PRODUCER-B01/REPORT.md`
  - `tests/test_s09_structural_lock_producer.py`

### QA

- Source `69a1280cd7c0130083ed529f425339036c917df3`; parent `83af5167e9dddc931bc8590f547684c0c811784b` (verified before merge).
- Direct delta (6) — matches the pinned list exactly:
  - `docs/pm/sessions/S12-LC3-QA/LOG.md`
  - `docs/pm/sessions/S12-LC3-QA/R6_INVENTORY.md`
  - `docs/pm/sessions/S12-LC3-QA/R6_REPORT.md`
  - `tests/s12/s12-lc3-qa-r6/r6_b01i_plan.py`
  - `tests/s12/s12-lc3-qa-r6/test_r6_b01i_prep.py`
  - `tests/s12/s12-lc3-qa-r6/test_r6_finite_inventory.py`

## Serial merge record

| Lane | Candidate before | Merge commit | Merge parents (first, second) | Delta | Post-state |
|---|---|---|---|---|---|
| VAL | `83af5167e9dddc931bc8590f547684c0c811784b` | `0b9ec15c4887422da995ff87cb392b3a7df8ffbb` | `83af5167e9dddc931bc8590f547684c0c811784b`, `535d7c136e0688bad1dc2905d4889a26869c995e` | 6 exact | diff-check 0; porcelain clean |
| RETRY | `0b9ec15c4887422da995ff87cb392b3a7df8ffbb` | `46abfba684ad94378be802ed872ac825b0d5e3fb` | `0b9ec15c4887422da995ff87cb392b3a7df8ffbb`, `1d9ed94f7a893967765e7d40a710cdcd99e90601` | 5 exact | diff-check 0; porcelain clean |
| B01 | `46abfba684ad94378be802ed872ac825b0d5e3fb` | `11e2de8f778783da9a8ce9d45fce7026e38849eb` | `46abfba684ad94378be802ed872ac825b0d5e3fb`, `c8830b342d678f5defdf17ec66b6c0ad3c6ef1cf` | 8 exact | diff-check 0; porcelain clean |
| QA | `11e2de8f778783da9a8ce9d45fce7026e38849eb` | `b5c62d151c758b6995a7a58ebd8edbb75efa27da` | `11e2de8f778783da9a8ce9d45fce7026e38849eb`, `69a1280cd7c0130083ed529f425339036c917df3` | 6 exact | diff-check 0; porcelain clean |

Every merge exited 0 and used the pinned source commit exactly; merge message is the Git default `Merge commit '<sha>' into codex/s12-lc3-luna-integration`. No extra path was pulled by any merge (each post-merge delta equals the pinned source delta).

Known repository warning (pre-existing state, identical to R5): after each successful merge, Git printed on stderr:

```
fatal: bad object refs/codex/turn-diffs/captures/1787896071503/34239ffd-2051-4233-a575-f5e8632b797a/base
error: failed to perform geometric repack
error: task 'geometric-repack' failed
```

Exit code stayed 0; the warning did not affect merge results, deltas, or the tree. Raw text retained in `R6_INT_RAW_PROVENANCE.txt`. No maintenance action was taken (out of INT scope).

## Transport tip and final verification

- Transport tip (QA merge): `b5c62d151c758b6995a7a58ebd8edbb75efa27da`.
- Union delta `83af5167e9dddc931bc8590f547684c0c811784b` → `b5c62d151c758b6995a7a58ebd8edbb75efa27da`: exactly **25 paths**, the disjoint union of the four pinned lane lists (6 + 5 + 8 + 6); `git diff --shortstat` = 25 files changed, 6408 insertions(+), 144 deletions(-).
- Range `git diff --check 83af5167… b5c62d1…`: exit 0.
- `git status --porcelain`: empty after every merge and at freeze.

### Static checks (changed scope)

| Check | Command | Result |
|---|---|---|
| Compile app | `python -m compileall -q app` | exit 0 |
| Compile changed/new tests | `python -m py_compile` (7 modules) | exit 0 |
| Lint gate | `ruff check --select F` (13 changed `.py`) | exit 0 — `All checks passed!` |
| Full ruleset (informational) | `ruff check` (same 13 files) | exit 1 — 52 style-class diagnostics: 41×E501 + 7×N802 + 1×N818 + SIM103/SIM102/SIM105 |

The four publication.py diagnostics (N818 line 77, SIM103 line 511, SIM102 line 1214, SIM105 line 1848) are the inherited pre-existing class carried from R5 (positions shifted by the 392-line VAL R6 delta); they are retained unchanged and not waived here. The E501/N802 diagnostics sit inside newly transported test modules (`test_r6_identity_resolution.py`, `test_r2_ownership_recovery.py`, `test_r6_publication_ownership.py`, `test_s09_structural_lock_producer.py`). No source/test edit was made by INT to address any diagnostic.

- No broad pytest / product / UI / video execution was run by INT (final broad gate and product chain belong to the Manager after freeze of the combined candidate).

## Evidence index (INT lane)

- `R6_INT_RAW_PROVENANCE.txt` — machine-concatenated stdout/stderr of every recorded command with per-file SHA-256.
- `COMMAND_LEDGER.jsonl` — one line per command: executable, argv, cwd, start/end UTC, elapsed ms, exit, stdout/stderr path + SHA-256.
- `manifest_transport.tsv`, `manifest_static.tsv`, `manifest_docs.tsv` — raw per-phase command manifests.
- Manager-provided readiness/gate artifacts also live in the same INT dir (`allow-list.json`, `guard-*.json`, `prompt-*.txt`, `readiness-console.txt`, `work-turn1-console.txt`) and are untouched by INT.

## Hand-off notes

- Combined candidate now carries exact R6 bytes for F01 (RETRY), F02/F03 (VAL), B01 producer + E01/E02 (B01), and the frozen finite inventory + harness prep (QA).
- Waiting on: final Manager/QA broad + product chain gates on this frozen candidate (B01-I public chain etc.), then Codex review. `NOT_CLOSED`.
- No push was performed; this docs commit is a local transport checkpoint on `codex/s12-lc3-luna-integration` only.

# S12-LC3-R5 INT transport ledger

Transport provenance only; this report does not approve or close the sprint.

## Identity and boundary

- Exact owner/session: Pascal, INT session `01a0898b-823a-7053-a1de-27d6fc24fce3`.
- Turn: R5 INT transport continuation; numeric turn identifier was not supplied.
- Route: `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.
- Candidate: `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration`, branch `codex/s12-lc3-luna-integration`.
- Pre-INT HEAD: `b6d620eb00f65d31af85b3d64badc7f31f504830`, clean.
- Transport order: VAL -> RETRY -> QA, ordinary local `git merge --no-ff --no-edit`.
- External evidence: `C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r5-owner-submission\20260912T164057Z\INT`.
- Runtime evidence: `C:\Users\Admin\Documents\Codex\work\s12-r5\20260912T164057Z\INT`.

## Source commits, parents, and exact deltas

### VAL

- Source `4f836627a3a8f0b7df0457230fee0987d4475bb3`; parent `e9a1686df7c740934c6fa8e12e23e1597f04856f`.
- Direct delta (6):
  - `app/services/s12_export/publication.py`
  - `tests/s12/s12-lc3-val/test_r3_publication_boundaries.py`
  - `docs/pm/sessions/S12-LC3-VAL/LOG.md`
  - `docs/pm/sessions/S12-LC3-VAL/REPORT.md`
  - `docs/pm/sessions/S12-LC3-VAL/evidence/20260912T1708Z-r5-f02-publication-recovery.md`
  - `docs/pm/sessions/S12-LC3-VAL/evidence/20260913T-post-guard-r5-f02.json`
- Source branch tip matched the pinned commit. Source worktree had only the declared pre-existing `?? work/`; that directory was not copied, staged, or touched.
- Source guard: manager VAL manifest has 103 entries; source post-guard is `VERIFIED`, zero failures. Guard JSON SHA-256: `1807644E948BCC20CE2029B6275DEF38B3EDEA34838650760F92B421E026D1D3`.

### RETRY

- Source `c60235f9fd2b6d6188dc9c974fc3640aa04c8031`; parent `2c9d793eb96ea330ba4d9ee1028ce45909cb9ea6`.
- Direct delta (5):
  - `app/persistence/s12_export.py`
  - `app/workflow/s12_export_jobs.py`
  - `docs/contracts/s12-export.md`
  - `docs/pm/sessions/S12-LC3-RETRY/LOG.md`
  - `tests/s12/s12-lc3-retry/test_r5_f01_f03.py`
- Source branch tip matched the pinned commit; worktree clean. Source pre/post guards are `VERIFIED`, zero failures; post-commit guard JSON SHA-256: `52026B3D53825CED3768A533E7A15B0557067A0D779B22E6DBA13DEE82625852`.

### QA

- Source `b6ab84e7e80ce673dda7a5c1ce517732fea06688`; parent `550494c2bfdd90dce21958cd56d6901d12c5b80b`.
- Direct delta (4), only:
  - `docs/pm/sessions/S12-LC3-QA/R5_COMMAND_LEDGER.md`
  - `docs/pm/sessions/S12-LC3-QA/R5_MATRIX.md`
  - `docs/pm/sessions/S12-LC3-QA/R5_REPORT.md`
  - `tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py`
- Source branch tip matched the pinned commit; worktree clean. QA prewrite/precommit guards were `VERIFIED` (8 and 9 entries); candidate immutable-probe guard was `VERIFIED` (17 entries), each with zero failures. Final packet micro/static evidence is in QA's R5 packet; INT did not rerun it.
- QA keeps P07 / R10 blocked on external StructuralLock authority and preserves the R4 migration findings; no product or closure claim is made here.

## Serial merge record

All source-parent commits were verified as ancestors of the candidate immediately before their merge. Before each merge, the candidate was clean and the pinned source branch tip, source commit identity, exact parent-to-tip path set, and source `git diff --check` were rechecked.

| Lane | UTC start | Candidate before | Merge commit | Merge parents (first, second) | Delta | Post guard / state |
|---|---|---|---|---|---:|---|
| VAL | `2026-09-12T18:05:58.4523843Z` | `b6d620eb00f65d31af85b3d64badc7f31f504830` | `0f11465a4ae66a0eb3d0d44699b4c9f3d4216a8f` | `b6d620eb00f65d31af85b3d64badc7f31f504830`, `4f836627a3a8f0b7df0457230fee0987d4475bb3` | 6 exact | 17-entry candidate probe guard `VERIFIED`, 0 failures; diff-check 0; clean |
| RETRY | `2026-09-12T18:06:30.3585340Z` | `0f11465a4ae66a0eb3d0d44699b4c9f3d4216a8f` | `36ae3914d556a8f7c204827ddb6123751229dafd` | `0f11465a4ae66a0eb3d0d44699b4c9f3d4216a8f`, `c60235f9fd2b6d6188dc9c974fc3640aa04c8031` | 5 exact | 17-entry candidate probe guard `VERIFIED`, 0 failures; diff-check 0; clean |
| QA | `2026-09-12T18:07:26.8168123Z` | `36ae3914d556a8f7c204827ddb6123751229dafd` | `75adde4d3d50e469188e1766f20eb81b898d9485` | `36ae3914d556a8f7c204827ddb6123751229dafd`, `b6ab84e7e80ce673dda7a5c1ce517732fea06688` | 4 exact | 17-entry candidate probe guard `VERIFIED`, 0 failures; diff-check 0; clean |

Each merge used the pinned source commit exactly and exited 0. No conflicts occurred. Git printed an existing bad-object/geometric-repack warning after the successful merges; the exact warning and exit codes are retained in `R5_INT_RAW_PROVENANCE.txt` in the external evidence and runtime roots. No conflict-resolution edits were made.

## Final verification

- Transport merge tip: `75adde4d3d50e469188e1766f20eb81b898d9485`; parents `36ae3914d556a8f7c204827ddb6123751229dafd` and exact QA source `b6ab84e7e80ce673dda7a5c1ce517732fea06688`.
- `git diff --name-only b6d620eb00f65d31af85b3d64badc7f31f504830 75adde4d3d50e469188e1766f20eb81b898d9485`: exactly 15 paths, the disjoint union of the three deltas above.
- Candidate-probe guard after each merge: 17 entries, `VERIFIED`, zero failures. Each report SHA-256 is `AEA0AE557C12D9104F86232E6A38809360DB2318E3DD8313C80907A6B1AEE45F`.
- `git diff --check` over the R5 transport range: exit 0.
- Changed-scope `python -m compileall -q`: exit 0.
- Changed-scope `ruff check ... --ignore E501`: exit 1 with four findings in merged `app/services/s12_export/publication.py` (N818 line 67; SIM103 line 337; SIM102 line 915; SIM105 line 1534). No source/test edits were made to address them.
- T01 staged-rename write-set guard: `VERIFIED`, 1 entry; the pre-existing staged rename remained `R tests/s12/s12-t01/test_c1_closure.py -> tests/s12/s12-t01/test_s12_export_c1_closure.py`.
- Final worker-process query had no VAL/RETRY/QA worker matches when excluding the query's own PowerShell process.
- Protected refs were unchanged: MAIN `a40e368f7c47c232cf2eeed9fb185c5972cb98ba`; canonical S12 `5f96ac7cce71d975aaa9e2524ed168c17d54331e`; S11 `1f5936d1167a55a583e8849ca67032e61297fe85`; S13 `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`; demo/C10 `1f5936d1167a55a583e8849ca67032e61297fe85`; UI `cf9ca6b67698601e0a02610d468ee6da3ad2b04d`. Existing unrelated/dirty state in MAIN, S13, and demo/C10 was observed but not changed.
- No broad/product/UI/video tests were run by INT. Independent final-candidate QA remains pending.

The coordination-doc commit created after this transport is recorded separately in the external INT final provenance; it contains only INT01 documentation and does not change the 15-path R5 writer delta.

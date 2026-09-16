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

---

# S12-LC3-QA — R6 finite inventory freeze + harness prep (Hermes owner transfer)

Status: `R6_INVENTORY_FROZEN` — QA preparation checkpoint only; no product, mechanism, UI, video or audio pass is claimed; NOT_CLOSED / NOT_APPROVED.

- Owner/session: Hermes owner after one-time transfer (USER_REQUESTED_PLATFORM_MODEL_TRANSFER), session `20260915_201612_aeb5e3`; route `ocg/deepseek-v4.1-flash` / provider `custom` / fallback OFF.
- Wave-base sync: `git merge --ff-only 83af5167e9dddc931bc8590f547684c0c811784b` fast-forwarded from `b6ab84e7e80ce673dda7a5c1ce517732fea06688`; clean status after sync.
- Frozen (new): `R6_INVENTORY.md` locks node/parameter IDs, typed outcomes, Run/Job counts and evidence templates for M01-M19 (RETRY), V01-V15 (VAL), B01-A-B01-I; `R6_REPORT.md` records the checkpoint.
- New QA micro: `tests/s12/s12-lc3-qa-r6/` (finite inventory checks, 62-row recheck, R04/R07/R08 retained-gate assertions, hash-proven reviewer assertion provenance, B01-I prepped-not-executed harness with exclusive per-run output dirs).
- Retained gates restored as machine-checkable assertions: R04 lost-ack/SHA prohibition, R07 interrupted temp / basename155+ / export_master.mp4, R08 exact collection/full modules/no extra skips.
- Reviewer provenance: R3 authority `98C929...` and corrected R5 probes hash-recorded and verified; R5 docs in this session remain byte-immutable (never overwritten).
- Waiting: WAITING_FOR RETRY/VAL/B01 executable nodes and INT transport -> B01-I stays PREPPED_NOT_EXECUTED; B01 remains BLOCKED_DEPENDENCY.
- Evidence lane: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/QA/` (raw pytest, node lists, guards/snapshots, COMMAND_LEDGER.jsonl). No push; no APPROVED/CLOSED claim.

---

# S12-LC3-QA — R6 B01-I product-chain execution (append 2026-09-15)

Status: `EXECUTED_BLOCKED_S10_SHOTS_OVERLAP` — honest blocker, not an approval.

- Frozen tip run: `0c18d2d19fdb40c7c62d88da9ac4d39a72e48385` (ff-synced from `69a1280`); five bounded runs, newest last; final recorded run `20260915T164349Z`.
- PASSED publicly (real returned IDs): upload/analyze/import/proxy/scene; DISCOVER_OBJECTS worker; roles; character pack publish (6 slots); ProjectCast/ReskinConfig per role; producer 201 (manifest `5111dbcd-7d9c-460b-8035-2315f99fb6e5`); CAS pin; S09 reapproval (`full_apply_executable=true`, checkpoint `83bccabe-...`); authority executable.
- BLOCKED: `POST /api/v2/projects/e5e93c5c336a/full-apply` → 422 `shots overlap or non-monotonic: shot 29963538-7ff4-5bb8-9212-aea7fc70c26d [0,119] and 627b554b-4bbb-55b6-8600-65df9edd3de4 [0,119]` — S10 segment-vs-shot contract collision; proposal for minimal owner/write-set recorded in R6_REPORT.md (S10 shot derivation from manifest shot_order; or producer typed denial). Codex decision required.
- Not reached: S10 run/publication, audio attach, QC/readiness, S12 context/preflight/submit, worker/publisher/media, UI submit/reload, replay checks. Browser UI NOT_RUN (no `frontend/node_modules`); human playback NOT_REVIEWED.
- Evidence: `outputs/s12-r6-hermes/20260915T131158Z/QA/B01-I/20260915T164349Z/` (b01i-chain.json `72BB20C7...`, b01i-stages.jsonl `FA50652D...`, summary, raw pytest). Runtime: `work/s12h/20260915T131158Z/QA/B01-I/20260915T164349Z/`.
- Bookkeeping: finite inventory reconciled to delivered node IDs (freeze names preserved); no case meaning/outcome/count weakened; R04/R07/R08 retained gates unchanged.

---

# S12-LC3-QA — R7 prep + compatibility (append 2026-09-16, wave-base 35f6cb2)

Status: R7_PREP_EXECUTED — no public chain; no closure claim.

- Q01 (evidence claims corrected): B01-I chain stops at `s10_full_apply_submit`; S12 preflight = NOT_REACHED / NOT_REEXECUTED (F05 acknowledged); “missing producer”/“B01 BLOCKED_DEPENDENCY” obsolete (P07 `PRODUCER_PRESENT_WITH_OPEN_F03`); “single residual” obsolete (open F01–F05). Corrected in `R6_REPORT.md` appendix + `R6_INVENTORY.md` (old text retained as provenance).
- Q02 (T03A migration compat, bounded exception): `tests/s12/s12-t03a/test_s12_export_migration.py` — TARGET_REV `c3d4e5f6a7b8` vs CURRENT_HEAD `d4e5f6a7b8c9` separated; both linear edges + linear walk asserted; fresh/retained-data/lineage-backfill at head executed on real temp DBs; both downgrade guards retained (exact messages), empty unwind verified. Full module: 9 passed / 0 failed (baseline 4 failed / 2 passed). No migration/model edit, no xfail/skip, coverage added only.
- Q03 (R5 audit env): exact values `S12_R5_CANDIDATE_ROOT=C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, `S12_R5_EXPECTED_CANDIDATE_SHA=35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86`; invocation + verify procedure in `R7_PREP.md` §Q03. Full R5 module with env: 3 passed / 0 failed (baseline without env: env-assert failure). Provenance assertions untouched.
- R7 freeze: original 62 + R6 unchanged; R7 rows (A01–A06, B01–B06, Q01–Q04, P01–P03) frozen in `R6_INVENTORY.md` §“R7 additions” with owners/outcomes/raw destinations; unimplemented nodes marked “to be frozen by owner”.
- Evidence: `outputs/s12-r7-two-managers/20260916T0351Z/B/QA/` (`baseline-t03a.*`, `t03a-fixed-v1.*`, `baseline-r5.*`, `r5-env.*`, guards, this prep record). Honest labels retained; B01-I still blocked at F04; NOT_CLOSED / NOT_APPROVED.

### 2026-09-16 — R7 PUBLIC CHAIN on c3cf0955 (Q04 + P01-P03)

- Wave-base `c3cf0955ffea02cb2070c0f6a3ce694c10ed3c5e` verified first (`git rev-parse`,
  clean tree, QA worktree already on the integration tip).
- Section A: R5 env refreshed to the new tip and the module re-run — 2 passed, 1 failed:
  the R5 packet still pins five pre-Q02 probe names (`test_single_head_is_new_revision`…)
  which the QA Q02 correction intentionally renamed; proposal recorded in R7_PREP §A.1
  (bounded exception needed — R5 test not in this lane's write-set; no silent xfail).
- Section B: one bounded public chain (extended node) executed against the frozen
  candidate; result **BLOCKED_EXACT_S12_READINESS** (canonical run 20260916T084317Z):
  * GREEN through S10: reapproval checklist carries the frozen timeline block
    (`s09.full-apply-timeline/v1`, 2 occurrences, pixel-scale boxes, clipped regions),
    the old 422 shots-overlap boundary is GONE, S10 completed + publication + B06
    `per_layer_evidence` sidecar verified 6 rows / 2 layers (Q9 frozen format, distinct
    artifacts, no dedup) once each role got its own pack/mask artifact.
  * BLOCKER: S12 preflight `S12_EXPORT_NOT_READY` — readiness `not_run` because the
    product has no public path to a completed SCOPE_FULL QC run (`compose_check_run_args`
    refuses every non-audio detector with 422 QC_RUN_EVIDENCE_UNAVAILABLE); audio scope
    completed but is not full-run authority. Corroborated by the S12 E2E seed writing
    the full run row directly. Exact evidence + minimal options in R7_PREP.
  * Replay/cancel/restart/expiry legs: NOT_REACHED behind the S12 gate (honest labels).
- Section C (P02): real UI on a disposable copy (npm ci, lockfile unchanged; prod build
  + next start :3101; backend :8901 with the chain's copied runtime; Chromium 390×844):
  context + preflight rendered REAL server truth, submit disabled fail-closed by the same
  S12 gate, reload + reopen (fresh profile) preserve the server state. Two copy-local
  route-config lines disclosed (candidate cannot build as-is under Next 16.2.12 —
  `useSearchParams` prerender errors; pre-existing finding R7-F3).
- Section D: R6_INVENTORY §R7 rows P01-P03 moved to EXECUTED/PARTIAL/BLOCKED labels with
  evidence run ids; Q04 row annotated (combined-candidate gate cannot be green until
  R7-F1 is ruled).
- Evidence: `.../B/QA/chain/20260916T084317Z/` + `.../B/QA/ui-20260916T084317Z/` +
  `r5-env-c3cf.*`; commit for this turn recorded at the end of this file.

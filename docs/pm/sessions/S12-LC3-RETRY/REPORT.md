# S12-LC3-RETRY — R6 F01 correction report (Hermes owner)

## Ownership and route

- Task: S12-LC3-RETRY (one-time owner transfer from Codex, reason
  USER_REQUESTED_PLATFORM_MODEL_TRANSFER).
- Owner session: `20260915_201417_80e003`; model `ocg/deepseek-v4.1-flash`,
  provider `custom`, fallback OFF (as instructed).
- Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-retry`,
  branch `codex/s12-lc3-luna-retry`.
- Wave base: single guarded `git merge --ff-only
  83af5167e9dddc931bc8590f547684c0c811784b` from clean tip
  `c60235f9fd2b6d6188dc9c974fc3640aa04c8031` (fast-forward, no conflict, no
  reset/clean/stash/rebase/force/push). Post-sync HEAD verified equal to the
  wave base; `git status --short` clean before edits.

## F01 correction — union Job discovery/classification

Problem (R5 F01): the durable-Job lookups filtered by canonical key + workspace
BEFORE establishing who actually claims a Run, so a Job whose
`input_manifest_json.run_id` still identified the Run disappeared from the
lookup when its key or workspace differed; ambiguity was accepted and
true-orphan paths could create extra Jobs (reviewer reproduction: 2 -> 3 Jobs).

One contract now resolves a Run's durable Job in
`app/workflow/s12_export_jobs.py` and is used by ALL of: initial replay
(`submit_export_job`), retry preparation + commit reconciliation (`ensure_pair`
via `reconcile_pair`), and the enqueue/bind lost-ack path
(`_enqueue_and_bind_job` / `_resolve_claim_after_enqueue_conflict`):

1. `_resolve_run_durable_job` gathers the claim UNION before any scope/type
   filter: (a) the run's durable pointer, (b) canonical key
   `s12_export_job:{run.id}` in ANY workspace, (c) any Job whose manifest
   `run_id` is this run (ANY key/workspace), (d) relevant generation/owner
   evidence. A manifest-identity claimant is never filtered away; equal
   `input_generation` alone is NOT identity (valid retry attempts share
   `run.plan_hash`).
2. `_run_job_claim_problems` validates every claimant against the full
   identity (workspace, type, owner, canonical key, pinned generation, full
   manifest run identity, and every present immutable lineage field) —
   mirroring the durable `bind_job` contract.
3. Classification: exactly one valid claimant is accepted (a missing pointer
   is restored once, committed); a TRUE zero-Job orphan (pointer null, no
   claimant, no unresolved evidence) is repaired with exactly one Job creation
   (a concurrent creator wins; the loser rolls back its conflicted attempt and
   converges on the durable winner); contradictory, ambiguous or unresolved
   identity raises a typed `S12ExportSubmitError` (`409`) with ZERO mutation —
   Run/Job rows, revisions, pointers, lease rows and artifacts are all
   preserved; read/parse (malformed relevant JSON) failures fail closed.
4. Detection of an unresolved relevant claimant uses
   `_weak_generation_candidates`: a generation/owner candidate attributable to
   another run (manifest names a run, or another run points at it) is skipped;
   anything else blocks orphan repair (a contradictory claimant cannot become
   an orphan).

Implementation note: an initial attempt used a SQLAlchemy savepoint around the
orphan Job creation. A live probe (`probe_savepoint.py`) proved the pysqlite
legacy transaction mode can auto-commit a savepoint's contents when the session
has no prior DML, violating the one-transaction contract; the savepoint was
removed and replaced with the rollback-and-re-resolve convergence above.

Files changed:

| Path | Pre SHA256 | Post SHA256 | Note |
|---|---|---|---|
| app/workflow/s12_export_jobs.py | 2fa4d11dd3f86c32d2a86ff250e527c41d981ea44f77d498830391e479ebf50c | 79c3a3cffbdf3b98e3e5cd11c0716d41b91d8c454db24d75e0468e3c6fb91d9b | F01 union contract (917 lines) |
| docs/contracts/s12-export.md | f7d80628de9d3959c3fb3eb9b37ea87f0b4fa1d67be8461bc069e61fc7b39cda | 12b78384e20f944bd34c1beb39ed485932e079855bc6ce2600aa2948e17767b5 | R5 text corrected + R6 addendum |
| tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | (new file) | 4ac4a4e7f96a3a771618ea7b0dab289f890e1c1ca17d030fa1eca19ca236d941 | M01-M19 matrix (941 lines) |

`app/persistence/s12_export.py` and `app/api/routes/s12_export.py` were in the
write-set but required NO change (byte-identical pre/post: bf9be7ac...,
3c3222db...); the union contract is enforced at the workflow sites that own
discovery, and the durable `bind_job` remains the strict pointer↔Job validator.

## Verification (real runs, exact node IDs)

New module — 46/46 passed (79.92s), command ledger step `11_r6_full_run3`:

- `test_r6_identity_resolution.py::test_m01_initial_replay_unchanged_no_duplicate`
- `...::test_m02_successor_replay_unchanged_no_duplicate`
- `...::test_m03_valid_retry_chain_attempts_1_2_3[failed|cancelled]`
- `...::test_m04_single_field_job_corruption[initial|successor-generation|key|manifest_run_id|workspace|type|owner_id]` (12 nodes)
- `...::test_m05_additional_canonical_key_claimant[initial|successor]`
- `...::test_m06_additional_off_key_manifest_claimant[initial|successor]`
- `...::test_m07_cross_workspace_claimant[initial|successor-canonical_key|off_key]`
- `...::test_m08_null_successor_pointer_changed_job_key_denies_2_2`
- `...::test_m09_null_pointer_changed_job_workspace_denies_2_2`
- `...::test_m10_null_pointer_changed_key_and_generation_denies_2_2`
- `...::test_m11_unresolved_generation_owner_claimant_cannot_become_orphan`
- `...::test_m12_pointer_redirected_to_other_job_denies_zero_mutation`
- `...::test_m13_null_pointer_restore_once_without_creating_job`
- `...::test_m14_actual_orphan_repair_once_then_unchanged`
- `...::test_m15_fail_closed_matrix[read_failure|malformed_json|enqueue_failure|bind_failure]`
- `...::test_m16_successful_commit_lost_ack_fresh_reconciliation_exact_pair`
- `...::test_m17_commit_fails_before_durability_no_successor_denied`
- `...::test_m18_malformed_predecessor_denial[attempt9|self|missing|cyclic|foreign_workspace|frozen_identity]`
- `...::test_m19_two_live_retries_one_logical_creator[same_client|different_clients]`
- `...::test_m19_sequential_retry_control_converges`

Every case snapshots ALL `s12_export_run` / `job` / `s12_export_lease` rows
(columns included) before its public operation and asserts the exact typed
outcome plus zero/known delta; M04-M07 run against BOTH the initial replay and
the existing-successor replay; M04-M12 assert "never 2/3".

Affected lane modules — 39/39 passed (57.07s), ledger step
`13_lane_affected_modules_run` (collection: step `12_lane_collect`):
test_export_jobs_api.py (9), test_r4_retry_execution.py (13 nodes incl. the
real-worker chain and the two-live-retry contested node), test_r5_f01_f03.py
(3), test_retry_identity_matrix.py (4), test_retry_migration.py (1),
test_s12_t03c_c1_closure.py (9). No skips added, no assertions weakened, old
F03 lineage regression retained.

Static: `python -B -m py_compile` OK; `ruff check --select F` clean on all four
Python paths (step `14_postimage_and_static`).

## Environment and limitations

- Runtime: `C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe`,
  `-B -p no:cacheprovider`, unique short basetemps in `%TEMP%`
  (`s12r6a_1` .. `s12r6e_1`); every test builds+uses its own migrated DB under
  the pytest tmp root — no real/MAIN database touched.
- Fixture-only engineering evidence: the S10 authority/seed rows and the
  frozen readiness aggregate are the lane's established fixtures; the public
  route/workflow/persistence code under test is real.
- UNRUN by design (outside this correction): normal-product export chain,
  UI/playback, and the VAL/B01/QA lanes.
- Errors during development (kept, not hidden): the first full run exposed a
  broken snapshot helper (lease table has no `id` column; 46 false failures),
  and the savepoint probe above. Fixture corrections were made in the NEW test
  file only; no existing test or source assertion was weakened.

## Evidence

- Evidence lane: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/RETRY/`
  (raw stdout/stderr per step, COMMAND_LEDGER.jsonl, HASH_MANIFEST.json,
  RAW_EVIDENCE_INDEX.md).
- Runtime lane: `C:/Users/Admin/Documents/Codex/work/s12h/20260915T131158Z/RETRY/`
  (live COMMAND_LEDGER.jsonl + cmdlog.py + probe_savepoint.py).

## Statements

- No `git push`, `fetch`, `pull`, `reset`, `clean`, `stash`, `rebase`, `force`,
  `checkout`-overwrite, or manual conflict resolution was performed.
- Only write-set paths were touched: `app/workflow/s12_export_jobs.py`,
  `docs/contracts/s12-export.md`, `tests/s12/s12-lc3-retry/test_r6_identity_resolution.py`,
  `docs/pm/sessions/S12-LC3-RETRY/**`. MAIN, S11/S13/demo/assets/voice, other
  worktree lanes, protected models/migrations/T03A tests, publication.py,
  validation.py, stitch.py, runner.py and app/api/app.py were not touched.
- This commit is a transport checkpoint only — NOT `APPROVED`; Codex review
  remains the gate.

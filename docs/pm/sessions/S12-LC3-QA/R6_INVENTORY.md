# S12-LC3-QA — R6 finite acceptance inventory (frozen before implementation)

Owner/session: Hermes owner (one-time platform/model transfer, reason USER_REQUESTED_PLATFORM_MODEL_TRANSFER), session `20260915_201612_aeb5e3`.
Route: `ocg/deepseek-v4.1-flash` / provider `custom` / fallback OFF.
QA worktree/branch: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa` / `codex/s12-lc3-luna-qa`.
Wave base after `git merge --ff-only 83af5167e9dddc931bc8590f547684c0c811784b`: HEAD `83af5167e9dddc931bc8590f547684c0c811784b`.
Verdict carried: CHANGES_REQUESTED / NOT_APPROVED / NOT_CLOSED. Lane finding: F04 (P2) + all 62-row meanings + finite acceptance.

This inventory freezes node IDs, parameter IDs, typed outcomes, all-row Run/Job counts and raw evidence paths per case, per `R6_ACCEPTANCE.md`. It is a freeze, not a pass: no owner-lane or product test is executed by the QA micro, and collection is not execution.

Lane evidence root template: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/<lane>/`. This lane's QA evidence root: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/QA/`. Runtime root template: `C:/Users/Admin/Documents/Codex/work/s12h/<uniqueUTC>/<lane>/`.

## Frozen finite mapping — M01–M19 (RETRY)

Owner module (frozen): `tests/s12/s12-lc3-retry/test_r6_identity_resolution.py`.

| Case | Lane | Owner module (frozen) | Node ID (frozen) | Parameter IDs (frozen) | Expected typed outcome | All-row counts (Run/Job) | Raw evidence path template (per case) | Status (frozen) |
|---|---|---|---|---|---|---|---|---|
| M01 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m01_initial_replay_unchanged_no_duplicate | none (delivered) | unchanged initial replay accepted: same pair, created=false; typed unchanged | 1/1 unchanged (1 Run/1 Job) | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M01/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M02 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m02_successor_replay_unchanged_no_duplicate | none (delivered) | unchanged immediate-successor replay: same successor pair, created=false | 2/2 unchanged (2 Runs/2 Jobs) | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M02/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M03 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m03_valid_retry_chain_attempts_1_2_3 | predecessor_kind[failed,cancelled] | valid retry chain runs in the actual worker; immutable predecessors; shared plan generation is valid | 3/3 (3 Runs / 3 Job rows) | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M03/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M04 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m04_single_field_job_corruption | field[generation,key,manifest_run_id,workspace,type,owner_id]; site[initial,successor] | every single-field Job corruption denies with zero mutation | all-row snapshot unchanged; no new Run/Job | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M04/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M05 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m05_additional_canonical_key_claimant | site[initial,successor] | additional canonical-key claimant with different generation denies ambiguity | all-row snapshot unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M05/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M06 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m06_additional_off_key_manifest_claimant | site[initial,successor] | additional off-key claimant retaining manifest run ID denies ambiguity; exact fresh reviewer failure retained | all-row snapshot unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M06/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M07 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m07_cross_workspace_claimant | variant[canonical_key,off_key]; site[initial,successor] | cross-workspace claimant denies; do not filter away the claimant | all-row snapshot unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M07/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M08 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m08_null_successor_pointer_changed_job_key_denies_2_2 | none (delivered) | null successor pointer + changed Job key denies | 2/2 unchanged; never 2/3 | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M08/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M09 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m09_null_pointer_changed_job_workspace_denies_2_2 | none (delivered) | null pointer + changed Job workspace denies | 2/2 unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M09/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M10 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m10_null_pointer_changed_key_and_generation_denies_2_2 | none (delivered) | null pointer + changed key and generation with manifest claim retained denies | 2/2 unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M10/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M11 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m11_unresolved_generation_owner_claimant_cannot_become_orphan | none (delivered) | explain candidate classification; unresolved/contradictory claimant cannot become orphan | no orphan repair; all-row unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M11/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M12 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m12_pointer_redirected_to_other_job_denies_zero_mutation | none (delivered) | pointer redirected to another legitimate Job while original claimant remains denies | zero mutation | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M12/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M13 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m13_null_pointer_restore_once_without_creating_job | none (delivered) | restore pointer once without creating a Job; repeat unchanged | 2/2 (no Job created) | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M13/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M14 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m14_actual_orphan_repair_once_then_unchanged | none (delivered) | actual orphan repaired once; repeated repair unchanged | 2/1 -> 2/2 after exact repair | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M14/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M15 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m15_fail_closed_matrix | failure[read_failure,malformed_json,enqueue_failure,bind_failure] | fail closed with rollback; no preparation-error reconciliation | all-row unchanged, zero partial rows | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M15/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M16 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m16_successful_commit_lost_ack_fresh_reconciliation_exact_pair | none (delivered) | fresh reconciliation returns the exact durable pair; successful commit / lost acknowledgement retained; repeat zero delta | exact pair unchanged; zero delta on repeat | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M16/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M17 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m17_commit_fails_before_durability_no_successor_denied | none (delivered) | deny if no durable successor; no phantom pair | 1/1 unchanged (1 Run/1 Job) | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M17/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M18 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m18_malformed_predecessor_denial | corruption[attempt9,self,missing,cyclic,foreign_workspace,frozen_identity] | typed denial before repair/reconciliation; old F03 regression retained | zero mutation | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M18/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| M19 | RETRY | tests/s12/s12-lc3-retry/test_r6_identity_resolution.py | test_m19_two_live_retries_one_logical_creator | client_ids[same_client,different_clients] | two live retries rendezvous at the actual claim/create; exactly one logical creator, one new successor/Job; sequential control kept separate | 2/2 (1 predecessor -> totals 2 Runs/2 Jobs) | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/RETRY/M19/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |

M-notes: discovery must combine direct pointer, canonical key, manifest Run identity and relevant generation/owner evidence before trusting scope/type filters. Equal generation alone is not a unique Run identity. Verified legitimate sibling Jobs must be distinguished from unexplained or contradictory claimants. Use the same classification contract for initial replay, preparation and fresh commit reconciliation. Run M04-M07 for both initial and existing-successor replay. No narrow special-case fix for only M08.

## Frozen finite mapping — V01–V15 (VAL)

Owner module (frozen): `tests/s12/s12-lc3-val/test_r6_publication_ownership.py`.

| Case | Lane | Owner module (frozen) | Node ID (frozen) | Parameter IDs (frozen) | Expected typed outcome | All-row counts (Run/Job) | Raw evidence path template (per case) | Status (frozen) |
|---|---|---|---|---|---|---|---|---|
| V01 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v01_owned_publication_and_completed_replay | none (delivered) | one final/receipt; same Run/Job; no reassembly or extra rows | 1/1; zero extra rows | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V01/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V02 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v02_foreign_final_before_intent_denied | bytes_variant[matching,different] | deny; preserve all foreign identities and rows | all-row unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V02/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V03 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v03_external_matching_copy_after_intent_denied | with_sidecar[False,True] | deny adoption on retry; no receipt/completed transition; preserve exact reviewer assertions | all-row unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V03/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V04 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v04_interruption_before_link_loss_handler_denied | none (delivered) | deny adoption; deleting intent only after caught race loss is insufficient | all-row unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V04/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V05 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v05_foreign_or_malformed_proof_denied | case[intent_crossrun,receipt_crossrun] | typed denial; no foreign cleanup; no success mutation | zero mutation | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V05/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V06 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v06_own_crash_window_recovers | window[pre_final,post_final_pre_sidecar,post_sidecar_pre_receipt,receipt_precommit] | recover or retry the legitimate attempt with coherent ownership and exact pair | same Run/Job pair | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V06/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V07 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v07_commit_failure_and_lost_ack_converge | case[commit_failure,lost_ack] | fresh recovery converges exact pair; chunks bytes/mtime preserved; actual commit failure + lost ack covered; SHA-only adoption forbidden (R04); never adopt by matching SHA alone | exact pair; zero extra rows | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V07/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V08 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v08_real_publisher_child_kill_post_final_fresh_process_converges | none (delivered) | actual DurableWorker child killed post-final/pre-sidecar; reap PID; fresh worker/process same DB completes same Run/Job; no sleeper substitution | zero extras; stable chunk hashes/mtime | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V08/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V09 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v09_handoff_release_b_first_b_is_sole_publisher | none (delivered) | B is sole publisher; stale A changes no winner identity | 1/1; one winner | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V09/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V10 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v10_handoff_release_a_first_stale_a_never_publishes | none (delivered) | A writes no public result/companions; B completes; preserve fresh reviewer failure evidence | 1/1; one winner | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V10/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V11 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v11_equal_bytes_ownership_independent_of_sha | schedule[b_first,a_first] | ownership proved independently of SHA; exactly one authorized publication winner | 1/1; one winner | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V11/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V12 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v12_interruption_between_companions_stale_cleanup_cannot_corrupt | none (delivered) | no stale companion/intent cleanup corrupts the current attempt; authorized recovery coherent | all-row unchanged | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V12/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V13 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v13_private_candidate_rebuild_cannot_mutate_public | none (delivered) | public final bytes/inode identity cannot be mutated through private alias | unchanged public identity | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V13/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V14 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v14_supported_paths_full_publisher_completes + test_v14_unsupported_path_typed_denial_zero_public_bytes | case[short,spaces_unicode,deep,export_master]; case[basename155,overlong250] | supported full publisher completes; unsupported typed denial before public writes; server export_master.mp4 covered | zero public bytes delta on denial | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V14/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| V15 | VAL | tests/s12/s12-lc3-val/test_r6_publication_ownership.py | test_v15_interrupted_temp_and_foreign_companion_preserved | none (delivered) | preserve foreign bytes/metadata; only owned temp cleanup | unchanged foreign bytes | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/VAL/V15/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |

V-notes: for V09-V12 record two live participants, actual primitive rendezvous, fence transition, exclusive-success count, both raw outcomes, bounded joins, all Run/Job/lease rows and final/sidecar/receipt/intent/current-candidate hash+inode+mtime. Do not solve only by another non-atomic fence read, SHA equality, trusting an intent written before success, or accepting stale publication after the database rejects it.

## Frozen finite mapping — B01-A–B01-I (producer + QA-owned B01-I)

Producer owner module (frozen): `tests/test_s09_structural_lock_producer.py` (existing file patched, not replaced). B01-I is QA-owned and prepped-not-executed.

| Case | Lane | Owner module (frozen) | Node ID (frozen) | Parameter IDs (frozen) | Expected typed outcome | All-row counts (Run/Job) | Raw evidence path template (per case) | Status (frozen) |
|---|---|---|---|---|---|---|---|---|
| B01-A | B01 | tests/test_s09_structural_lock_producer.py | test_B01_A_success_current_source_evidence_graph | none (delivered) | server-derived canonical nonempty manifest; exact source/evidence generation/hashes/segments/routes/timebase; one active current lock | one active current lock row | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-A/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-B | B01 | tests/test_s09_structural_lock_producer.py | test_B01_B_equivalent_replay_no_extra_rows | none (delivered) | same manifest/hash/version; no extra route, config, approval or manifest rows | zero extra rows | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-B/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-C | B01 | tests/test_s09_structural_lock_producer.py | test_B01_C_two_live_callers_exactly_one_creator | none (delivered) | exactly one creator; coherent same result or typed conflict as frozen contract dictates | all-row proof; one creator | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-C/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-D | B01 | tests/test_s09_structural_lock_producer.py | test_route_registration_and_unknown_identity_denied + test_missing_evidence_denied_typed + test_stale_expected_identity_conflicts_typed + test_tampered_source_and_evidence_denied_typed + test_cross_workspace_and_foreign_scope_denied_typed + test_client_authority_and_filesystem_fields_rejected + test_unsupported_policy_route_and_ambiguity_denied_typed + test_ambiguous_route_decisions_denied_typed + test_role_mapping_prerequisite_denied_typed + test_removal_only_only_graph_has_no_empty_success | none (delivered matrix) | typed denial before success mutation | zero mutation | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-D/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-E | B01 | tests/test_s09_structural_lock_producer.py | test_B01_E_generation_change_and_supersession | none (delivered) | current generation explicitly validated; old history preserved and never returned as current authority | supersession history retained | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-E/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-F | B01 | tests/test_s09_structural_lock_producer.py | test_B01_F_pin_and_reapproval_full_apply_executable | none (delivered) | correct returned lock; stale revision 409; actual public reapproval full_apply_executable=true | reapproval record; no stale acceptance | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-F/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-G | B01 | tests/test_s09_structural_lock_producer.py | test_role_mapping_prerequisite_denied_typed + test_removal_only_only_graph_has_no_empty_success | producer-internal prerequisites; executable proof in B01-F | every S09 executable-authority prerequisite satisfied; empty manifest is not a pass | all prerequisites proven | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-G/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-H | B01 | tests/test_s09_structural_lock_producer.py | test_B01_H_transaction_failure_no_partial_state_then_retry + test_B01_H_read_failure_typed_denial | none (delivered) | no partially authoritative manifest/routes/pins/approval; deterministic recovery or typed denial | zero partial rows | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/B01/B01-H/{before,after}.raw.txt + execution.json + allrows.json | DELIVERED_ON_INT_CANDIDATE |
| B01-I | QA | tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py | test_b01i_public_product_chain_submit_worker_publisher_result_media_ui | stage[s10_full_apply,s12_submit,durable_worker,publisher,result_media,ui_submit_reload]; executed, blocked at s10_full_apply | public S10->S12->worker->publisher->result/media chain with correct server IDs; one logical Run/Job; valid complete video/audio; UI submit+reload no duplicate; no seeded authoritative DB rows or private handler shortcut | one logical Run/Job; reload adds zero rows | C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/QA/B01-I/{before,after}.raw.txt + execution.json + allrows.json | EXECUTED_BLOCKED_S10_SHOTS_OVERLAP |

B01-notes: B01-A–B01-H belong to the producer owner (existing task S09-LOCK-PRODUCER-B01, patched test file, never replaced). QA independently verifies B01-I only after all implementation dependencies and mechanism gates are green. A further legacy/v2 consumer incompatibility stays an exact blocker with evidence and proposed minimal ownership; protected consumers are not mutated and B01-I is not marked passed.

## B01-I — prepped, not executed (QA-owned) — see execution result below

- Status: PREPPED_NOT_EXECUTED.
- Exact node: `tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py::test_b01i_public_product_chain_submit_worker_publisher_result_media_ui`.
- Exact command: `["C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe", "-B", "-m", "pytest", "tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py::test_b01i_public_product_chain_submit_worker_publisher_result_media_ui", "-q", "-p", "no:cacheprovider"]`.
- Required env: `S12_REVIEW_OUT`, `S12_R6_CANDIDATE_ROOT`, `S12_R6_EXPECTED_CANDIDATE_SHA`.
- Output dir NEW per run (S12_REVIEW_OUT style): run evidence lives under `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/QA/B01-I/<run_id>/` and the run dir is created exclusively (existing dirs are never reused or overwritten); old evidence is never touched.
- Dependencies (all required before dispatch): S12-LC3-RETRY terminal; S12-LC3-VAL terminal; S09-LOCK-PRODUCER-B01 terminal (B01-A–B01-H green); S12-LC3-INT serial transport integrated with frozen candidate SHA.
- The plan module `tests/s12/s12-lc3-qa-r6/r6_b01i_plan.py` freezes this contract and its dispatch guard refuses to run while any dependency is unsatisfied.

## Preserved gates — R04 lost-ack/SHA prohibition, R07 Windows companion paths, R08 exact collection/full modules/no skips

- R04 lost-ack/SHA prohibition: successful commit / lost acknowledgement is an executable requirement (M16, V07); never adopt by matching SHA alone (V07, V11); invalid/foreign/tampered/ambiguous/read-error cases preserve files and zero mutation (V02-V05). Chunks bytes/mtime preserved across recovery (V07, V08).
- R07 Windows companion paths: interrupted temp handling (V15) plus basename155+ and server export_master.mp4 (V14); supported full publisher completes; unsupported typed denial before public writes with zero public bytes delta; foreign companion bytes/metadata preserved.
- R08 exact collection/full modules/no new skips: snapshot exact collection/node lists; run complete applicable modules (full affected RETRY/VAL/B01 modules, not selections); no new skips or threshold relaxation; collection is not execution. Retained families must stay separate: source identity/timing/provenance; audio content/start-end; audio deadline/error/cancel (separate); geometry; migration/hash/Job binding; stale/readiness/ownership.

## 62-row authority carried verbatim

AUTHORITY-ID-LIST: C01 C02 C03 C04 C05 C06 C07 C08 C09 C10 C11 C12 C13 C14 C15 C16 C17 C18 C19 C20 C21 C22 C23 C24 C25 C26 C27 C28 C29 C30 C31 C32 S01 S02 S03 S04 S05 S06 S07 S08 S09 S10 P01 P02 P03 P04 P05 P06 P07 P08 P09 P10 R01 R02 R03 R04 R05 R06 R07 R08 R09 R10

62 rows = C01-C32 (32) + S01-S10 (10) + P01-P10 (10) + R01-R10 (10), carried verbatim with their R5_MATRIX.md meanings. No row is APPROVED or CLOSED; no row was added, removed, or renamed. The finite M01-M19 / V01-V15 / B01-A-B01-I mapping above is an executable supplement, not a replacement.

## B01-I execution result — 2026-09-15, frozen candidate 0c18d2d

Status: EXECUTED / BLOCKED_EXACT at `s10_full_apply_submit` (HTTP 422). One bounded real chain per run, public APIs only, no SQL seed and no private handler shortcut; evidence runs, newest last:

- `20260915T163219Z` — multi-scene fixture (2 scenes, red/blue): blocked at S10 submit `shots overlap or non-monotonic: shot 2e78b56f-9ef1-5796-9d68-9f4abfc64f8c [0,59] and 572ad59c-7a38-51f5-a5d0-faec26547af4 [0,59]`.
- `20260915T163651Z` — checkpoint-revision semantics corrected (`expected_checkpoint_revision` must equal the pinned `reskin_config_revision`), reached the same S10 boundary.
- `20260915T163912Z` — single-scene fixture: blocked at S10 submit (same contract).
- `20260915T164030Z` — single-scene fixture, pre-hardening harness: blocked at S10 submit `shots overlap or non-monotonic: shot 32843881-99d7-570d-9a1d-8b1180587af6 [0,119] and f5ad1448-9a86-577e-b1fb-c103e12c2f06 [0,119]`.
- `20260915T164349Z` — FINAL recorded run with full stage status, counts-at-failure and hashes (see below): blocked at S10 submit `shots overlap or non-monotonic: shot 29963538-7ff4-5bb8-9212-aea7fc70c26d [0,119] and 627b554b-4bbb-55b6-8600-65df9edd3de4 [0,119]`.

Stages reached and passed on the FINAL run (all public, real returned IDs): legacy project `e5e93c5c336a` + upload + analyze/import/proxy/scene chain completed; DISCOVER_OBJECTS durable worker completed; roles confirmed (2); character `6a076f1c-3f14-431e-bc8c-e208f7b27f76` + pack version `36cc0cf9-0b21-4439-b96a-b3c614d05c4c` published with all six pose slots; ProjectCast/ReskinConfig per role; producer `POST .../structural-lock` returned 201 with manifest `5111dbcd-7d9c-460b-8035-2315f99fb6e5`, hash `990152a3bb8f9641fa21928b92d8a6ab4fbe8211c17ac8191af87c3e6583330e`, segment_count 2, 2 route decisions; CAS pin applied (config revision 2); S09 reapproval v2 created checkpoint `83bccabe-dd4d-4b6c-b168-2d4c66a6f1a9` with `full_apply_executable=true`; full-apply authority read `"executable": true`.

Blocked stage (exact): `POST /api/v2/projects/e5e93c5c336a/full-apply?workspace_id=default` with `{video_item_id, apply_checkpoint_id: 83bccabe-..., expected_checkpoint_hash: d3a424a0..., expected_checkpoint_revision: 2}` returned 422 `{"detail":"shots overlap or non-monotonic: shot 29963538-7ff4-5bb8-9212-aea7fc70c26d [0,119] and 627b554b-4bbb-55b6-8600-65df9edd3de4 [0,119]"}`.

Root contract collision (evidence-backed, no verdict): `app/services/s10_full_apply.py` maps each v2-authority manifest SEGMENT 1:1 to a render "shot" (`shot_id = occurrence_segment_id`, its frame range), and `app/services/s10_chunk_plan.py::_normalize_shots` requires shots contiguous from 0 with no overlap. The public producer (B01 contract) legitimately includes ALL current-active segments; the sanctioned deterministic extraction world always co-occurs two objects per scene (`Hero` + `Twin`), whose segments necessarily overlap in frames. Therefore any producer manifest with >=2 co-occurring segments can never satisfy the S10 planner, while S09 eligibility still reports `full_apply_executable=true`.

DB delta at failure (all rows, unfiltered): structural_lock_manifests=1, apply_checkpoints=1, reskin_configs=2, artifacts=7, jobs=4, s10_full_apply_runs=0, s10_publications=0, s12_export_runs=0 (before-chain all zero) — zero S10/S12 rows created by the denied request.

Observations for the reviewer (exact):

1. Multi-scene deterministic extraction stores scene-local frame ranges per scene (`scene 2` segments `[0,59]` while the scene is `[60,119]`), recorded in run `20260915T163219Z` (segment ids `2e78b56f-...`, `572ad59c-...`); a multi-scene source additionally violates monotonicity across scenes.
2. Proposed minimal next ownership (NOT applied here): primary option — build S10 "shots" from the manifest `shot_order`/scenes (which are contiguous by construction) and keep per-segment regions/mappings for layers; write-set `app/services/s10_full_apply.py` (+ `app/services/s10_chunk_plan.py` if the shot/mapping model changes); owner S10-T01C lineage. Safety-net option — typed fail-closed denial when a produced manifest cannot be partitioned into renderable shots; write-set `app/services/structural_lock_producer.py` + `docs/contracts`. Both need Codex decision; neither lane is in this wave's write-set.
3. UI: real-browser Export UI could not run — `frontend/node_modules` absent (no install performed under this bounded task); UI submit/context/reload is represented by the public context/submit/replay API evidence and remains NOT_RUN for the browser.
4. Human playback: NOT_REVIEWED (no video was produced; the chain blocked before S12 export).

Evidence (final run): `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/QA/B01-I/20260915T164349Z/` — `b01i-chain.json` sha256 `72BB20C7F1ADC82FF8858A7D12FB740F2CE59E7D1626B6DDC06088396692078F`, `b01i-stages.jsonl` sha256 `FA50652D26EB18FAF9724BE5EC013828DD2F3C39B03D25D150FA4D4D4DA139BF`, `b01i-summary.json`, raw pytest stdout/stderr + exit. Runtime: `C:/Users/Admin/Documents/Codex/work/s12h/20260915T131158Z/QA/B01-I/20260915T164349Z/`.

## Reconciliation — delivered node IDs on the frozen candidate

The freeze commit recorded prospective node names. The RETRY/VAL/B01 owners then delivered equivalent executable nodes under their own naming, were Manager-verified and INT-transported. This section preserves the frozen names for provenance; the tables above now carry the delivered executable IDs (row cells updated 2026-09-15 on candidate 0c18d2d; case meanings, outcomes, counts and evidence templates unchanged). No acceptance was weakened: every case keeps its required outcome and its mandatory hash-proven reviewer backing.

| Case | Original frozen name (commit 69a1280) | Delivered node (frozen tables above) |
|---|---|---|
| `M01` | test_r6_m01_unchanged_initial_replay | test_m01_initial_replay_unchanged_no_duplicate |
| `M02` | test_r6_m02_unchanged_successor_replay | test_m02_successor_replay_unchanged_no_duplicate |
| `M03` | test_r6_m03_valid_worker_attempt_chain_runs | test_m03_valid_retry_chain_attempts_1_2_3 |
| `M04` | test_r6_m04_single_field_job_corruption_denies | test_m04_single_field_job_corruption |
| `M05` | test_r6_m05_extra_canonical_key_claimant_denies | test_m05_additional_canonical_key_claimant |
| `M06` | test_r6_m06_extra_offkey_claimant_manifest_run_denies | test_m06_additional_off_key_manifest_claimant |
| `M07` | test_r6_m07_cross_workspace_claimant_denies | test_m07_cross_workspace_claimant |
| `M08` | test_r6_m08_null_pointer_changed_job_key_denies | test_m08_null_successor_pointer_changed_job_key_denies_2_2 |
| `M09` | test_r6_m09_null_pointer_changed_workspace_denies | test_m09_null_pointer_changed_job_workspace_denies_2_2 |
| `M10` | test_r6_m10_null_pointer_changed_key_generation_denies | test_m10_null_pointer_changed_key_and_generation_denies_2_2 |
| `M11` | test_r6_m11_unresolved_claimant_cannot_become_orphan | test_m11_unresolved_generation_owner_claimant_cannot_become_orphan |
| `M12` | test_r6_m12_pointer_redirected_to_other_job_denies | test_m12_pointer_redirected_to_other_job_denies_zero_mutation |
| `M13` | test_r6_m13_restore_pointer_once_without_new_job | test_m13_null_pointer_restore_once_without_creating_job |
| `M14` | test_r6_m14_true_orphan_repaired_once | test_m14_actual_orphan_repair_once_then_unchanged |
| `M15` | test_r6_m15_fail_closed_discovery_and_flush_failures | test_m15_fail_closed_matrix |
| `M16` | test_r6_m16_successful_commit_lost_ack_reconciliation | test_m16_successful_commit_lost_ack_fresh_reconciliation_exact_pair |
| `M17` | test_r6_m17_commit_fail_before_durability_denies | test_m17_commit_fails_before_durability_no_successor_denied |
| `M18` | test_r6_m18_predecessor_identity_corruption_denials | test_m18_malformed_predecessor_denial |
| `M19` | test_r6_m19_two_live_retries_one_logical_creator | test_m19_two_live_retries_one_logical_creator |
| `V01` | test_r6_v01_owned_publication_and_completed_replay | test_v01_owned_publication_and_completed_replay |
| `V02` | test_r6_v02_foreign_matching_before_intent_denies | test_v02_foreign_final_before_intent_denied |
| `V03` | test_r6_v03_external_copy_after_genuine_intent_denies | test_v03_external_matching_copy_after_intent_denied |
| `V04` | test_r6_v04_interrupted_before_race_loss_handler_denies | test_v04_interruption_before_link_loss_handler_denied |
| `V05` | test_r6_v05_invalid_intent_receipt_denials | test_v05_foreign_or_malformed_proof_denied |
| `V06` | test_r6_v06_legitimate_failure_windows_recover | test_v06_own_crash_window_recovers |
| `V07` | test_r6_v07_commit_failure_and_lost_ack_converge | test_v07_commit_failure_and_lost_ack_converge |
| `V08` | test_r6_v08_worker_kill_post_final_fresh_process_completes | test_v08_real_publisher_child_kill_post_final_fresh_process_converges |
| `V09` | test_r6_v09_real_lease_handoff_release_b_first | test_v09_handoff_release_b_first_b_is_sole_publisher |
| `V10` | test_r6_v10_real_lease_handoff_release_expired_a_first | test_v10_handoff_release_a_first_stale_a_never_publishes |
| `V11` | test_r6_v11_ownership_proved_independently_of_sha | test_v11_equal_bytes_ownership_independent_of_sha |
| `V12` | test_r6_v12_ownership_loss_between_final_sidecar_receipt_commit | test_v12_interruption_between_companions_stale_cleanup_cannot_corrupt |
| `V13` | test_r6_v13_private_alias_cannot_mutate_public | test_v13_private_candidate_rebuild_cannot_mutate_public |
| `V14` | test_r6_v14_real_companion_paths | test_v14_supported_paths_full_publisher_completes |
| `V15` | test_r6_v15_interrupted_temp_and_foreign_companion_preserved | test_v15_interrupted_temp_and_foreign_companion_preserved |
| `B01-A` | test_b01_a_current_source_evidence_graph_manifest | test_B01_A_success_current_source_evidence_graph |
| `B01-B` | test_b01_b_equivalent_replay_no_extra_rows | test_B01_B_equivalent_replay_no_extra_rows |
| `B01-C` | test_b01_c_two_live_callers_one_creator | test_B01_C_two_live_callers_exactly_one_creator |
| `B01-D` | test_b01_d_invalid_scope_typed_denial | test_route_registration_and_unknown_identity_denied |
| `B01-E` | test_b01_e_generation_change_stale_replay_supersession | test_B01_E_generation_change_and_supersession |
| `B01-F` | test_b01_f_reskinconfig_cas_pin_stale_revision_reapproval | test_B01_F_pin_and_reapproval_full_apply_executable |
| `B01-G` | test_b01_g_executable_authority_prerequisites | test_role_mapping_prerequisite_denied_typed |
| `B01-H` | test_b01_h_transaction_failure_recovery | test_B01_H_transaction_failure_no_partial_state_then_retry |
| `B01-I` | test_b01i_public_product_chain_submit_worker_publisher_result_media_ui | test_b01i_public_product_chain_submit_worker_publisher_result_media_ui (QA, executed, blocked at S10) |
## Reviewer assertion provenance (hash-proven, immutable)

Hash algorithm: SHA-256 over bytes normalized (CRLF -> LF). External artifacts resolve under `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/`; the corrected R5 reviewer root in use is `s12-r5-independent-review-20260914` (the earlier navigation error to a nonexistent `s12-r5-independent-review/20260914` path is not repeated).

| Artifact (file) | SHA-256 (normalized) | Mapping to this freeze |
|---|---|---|
| s12-r4-independent-review-20260912/R3_MATRIX_AUTHORITY.md | 98C929FAB41A52BF5EF148A088230F0D87ADBFB28FD2BCE891C40DC9E6A4EC54 | 62-row authority + R01-R10 closure semantics -> all frozen rows |
| s12-r5-independent-review-20260914/REVIEW.md | B85ED4B6EC5E2740B2BE2C329D91B22D64D196E17F5AA87335C7B7F083826302 | F04 finding -> R04/R07/R08 preserved gates |
| s12-r5-independent-review-20260914/test_review_r5_identity.py | 155A2D2C32E31FEFC9F7CF6DC24C0D5FA1897FA53A4C4517F7556DD6E1146985 | F01 counterexamples -> M06/M08/M11/M14/M19 denials |
| s12-r5-independent-review-20260914/test_review_r5_publication.py | 5D5DB9C46EA20257EC9452038102385C9F5E4661572428B8D20CE67E844DB087 | F02/F03 counterexamples -> V03/V04/V09/V10 |
| s12-r5-independent-review-20260914/test_review_r5_publication.setup-v1.txt | DBF1A83BEE14500CA65C0519748D3D6DF9446D76E3E9AB6858076C87B47D8ED4 | preserved preimage of the corrected reviewer harness; only query patched was s12_export_lease keyed by run_id (not id) |
| s12-r6-hermes-deepseek-review-20260915/R6_ACCEPTANCE.md | 3CDDE8605501D8A7BEA6A540800257BF6ACF7D33D27831FB0C7EB33F37D0434E | finite contract source for all 43 frozen case rows |
| s12-r6-hermes-deepseek-review-20260915/REVIEW.md | AD5FFF3B97BF470FF007022C42FD94B6C947CA44858EE32F77D85905CE2ECEFB | verdict + handoff -> lane scope |
| s12-r6-hermes-deepseek-review-20260915/NEXT_HERMES_PROMPT.md | 29E6D6C6D2DA0425453C486C21BD21C3BC9703F47E327C0986762A44FB42BFFD | 8 QA write-set/outcome; 12 gate ordering |
| s12-r6-independent-review-20260914/REVIEW.md | C61220A6DCB7659409D0F7236F98783545BCAB0858E2CC85612599AC51DA45D1 | E01-E04; F04/E04 inventory completeness |
| docs/pm/sessions/S12-LC3-QA/R5_MATRIX.md | D601E8FACA20E096D44E8F97A0FA783890432BB63D441269B2DCE88ABC90735C | in-repo immutable 62-row matrix (not overwritten) |
| docs/pm/sessions/S12-LC3-QA/R5_REPORT.md | 5CCF38003CE077565F9733B74475084B48CA20EC1D2F3A31F9EDCDA7642EDEB2 | in-repo immutable R5 report (not overwritten) |
| docs/pm/sessions/S12-LC3-QA/R5_COMMAND_LEDGER.md | 5F3E7AAD03AA6F303CECDA87E063FE11164013FECF55763907D5DA5E4BFAF794 | in-repo immutable R5 ledger (not overwritten) |

The corrected reviewer assertions above are kept immutable and are hash-proven by the QA micro (existence + normalized SHA-256 equality). Nothing in the reviewer output trees was overwritten; every new run writes a new S12_REVIEW_OUT directory.

## Status summary and waiting list

- WAITING_FOR: RETRY (M01-M19 executable nodes), VAL (V01-V15 executable nodes), B01 (B01-A-B01-H in the patched producer test), INT (serial transport + frozen candidate SHA) -> gates B01-I.
- QA micro (this freeze + B01-I prep) executes no owner-lane or product test; no product, mechanism, UI, video or audio pass is claimed; B01 remains BLOCKED_DEPENDENCY until the producer lane lands.
- Terminal for this checkpoint: NOT_CLOSED / NOT_APPROVED; no push, no closure authority.

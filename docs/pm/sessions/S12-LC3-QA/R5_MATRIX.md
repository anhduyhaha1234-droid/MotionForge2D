# S12-LC3-R5 QA semantic and evidence matrix

Owner/session: QA Goodall / 01a08991-c909-7d03-86ed-ac236d50c87b. Route per accepted assignment: gpt-5.6-luna, reasoning high, fallback OFF. QA worktree/branch: C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa / codex/s12-lc3-luna-qa. Pre-write QA HEAD: 550494c2bfdd90dce21958cd56d6901d12c5b80b.

Read-only pre-INT candidate: C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration, codex/s12-lc3-luna-integration, full SHA b6d620eb00f65d31af85b3d64badc7f31f504830, clean at inspection. R4's b6d71873dd1597f191b3ead95cb15e5aff73a722 audit does not establish results for b6d620e or the future post-INT candidate. No final-candidate suite is run in this checkpoint.

Authority: R3_MATRIX_AUTHORITY.md SHA-256 98C929FAB41A52BF5EF148A088230F0D87ADBFB28FD2BCE891C40DC9E6A4EC54, verified before writes. The 62 tracked rows are scope rows, not 62 passes: C01-C32 original acceptance, S01-S10 prior-review findings, P01-P10 product stages, R01-R10 correction/evidence closure. “Inherited record” is historical evidence only; “R5 disposition” is this matrix/static-inventory micro only. No row is APPROVED or CLOSED. This checkpoint executes no product, immutable mechanism, UI, video, or migration test.

B01 remains BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY / PROPOSED_ONLY. No public StructuralLock producer/activation route or manifest is fabricated. No public S12 export, publisher, result, media, UI, or playback pass is claimed. Mechanism and seeded UI fixtures are not normal-product evidence.

## C01-C32

| ID | Original acceptance meaning retained | R3/R4 inherited record (not a new pass) | R5 disposition |
|---|---|---|---|
| C01 | T03C durable export-job API/lifecycle and scoped outcomes; retain original closure. | R3 carry-forward only; R4 did not alter RETRY tests. | NOT_EXECUTED |
| C02 | T01 preflight plus T02 capability/profile eligibility and fail-closed unknown/unsupported profiles. | R3 carry-forward only. | NOT_EXECUTED |
| C03 | Source provenance distinguishes proved native 4K from upscaled or ordinary 1080p; never infer from output size. | R3 carry-forward; fresh public source hashes recorded. | NOT_EXECUTED |
| C04 | Public legacy project/video/source identity and completed import/proxy/scene chain with returned IDs. | R3 partial; legacy chain recorded, not a ready S12 source. | NOT_EXECUTED |
| C05 | T03C public endpoint authorization/ownership denials precede unintended durable mutation. | R3 carry-forward only. | NOT_EXECUTED |
| C06 | Unchanged replay returns same run with no extra rows; changed identity/pins fail without extra rows. | R3 carry-forward; R03 adversarial identity proof open. | NOT_EXECUTED |
| C07 | Union identity rejects wrong/cross-scope/tampered/ambiguous claimants; repairs only a true zero-Job orphan once. | R3 carry-forward; union/ambiguity proof open. | NOT_EXECUTED |
| C08 | Two live callers meet at a real barrier: exactly one winner and typed loser; keep a separate sequential stale-snapshot control. | R3 carry-forward; contested-operation race required. | NOT_EXECUTED |
| C09 | Lease fencing: expired/released/reclaimed old token cannot mutate; current token remains valid. | R3 carry-forward only. | NOT_EXECUTED |
| C10 | Real runner 4K final raster 3840x2160 with measured codec eligibility; F1 1080p-to-4K upscale and F2 native 4K are separate controls. | R3 carry-forward, mechanism only; normal export not reached. | NOT_EXECUTED; mechanism is not product evidence. |
| C11 | Correct aspect/geometry: letterbox or fail closed, never stretch; retain portrait/non-16:9 controls. | R3 carry-forward; no normal media reached. | NOT_EXECUTED |
| C12 | Source-locked order/cuts and exact rational timing/CFR; reject VFR or missing timing authority before work. | R3 carry-forward; inputs indexed, not product proof. | NOT_EXECUTED; corrected static mapping is listed below, not execution evidence. |
| C13 | Chunk identity/resume binds source/config/tool and hashes; missing/truncated/tampered/changed chunks fail closed; do not overwrite good final. | R3 mechanism green; submission VAL evidence only. | NOT_EXECUTED |
| C14 | Committed chunk survives real worker kill/restart on same DB/run/job without duplicate rows. | R3 mechanism green / product not demonstrated; R4 worker evidence mechanism-scoped. | NOT_EXECUTED |
| C15 | Retry yields one usable immediate successor per predecessor; cancelled work is not replayed as success; successor may retry without duplication. | R3 green finite superseded by independent R4 b6d620e F01/F03 defects; OPEN/RED. | NOT_EXECUTED |
| C16 | Durable job/run lifecycle uses returned IDs and real worker state; legacy extraction fixture is not an S12 worker result. | R3 partial; legacy/analyze/extraction chain recorded, extraction fixture-only. | NOT_EXECUTED |
| C17 | Publication ownership fence prevents stale/foreign workers from adopting or mutating public output. | R3 mechanism green / product open; R4 independent F02 reproduced unsafe adoption. | NOT_EXECUTED; F02 remains open. |
| C18 | Atomic publication failure/recovery preserves one coherent result and exact run/job identity. | R3 mechanism green / product open; normal public chain unavailable. | NOT_EXECUTED |
| C19 | T04A validator rejects incomplete/corrupt/wrong codec, dimensions, frame/chunk/timing/audio/hash/source-lock evidence; only complete valid media passes. | R3 finite submission evidence; R4 full-publisher path remained open. | NOT_EXECUTED |
| C20 | Real project Export UI entry/context/preflight/submit, scoped to project/video and updating the server run pointer. | R3 NOT_RUN; seeded Playwright title is fixture-only. | NOT_EXECUTED; fixture is NOT_EQUIVALENT to product. |
| C21 | Distinct real UI reload/reopen/recovery retains the same server-owned active run and creates no duplicate. | R3 NOT_RUN; seeded reload probe is fixture-only. | NOT_EXECUTED; fixture is NOT_EQUIVALENT to product. |
| C22 | Completed-only server-owned result/media; deny partial/failed, cross-project, tampered, or unowned artifacts. | R3 NOT_DEMONSTRATED; submit stopped at 409; no result/media/playback. | NOT_EXECUTED |
| C23 | Packaging/stage gate for release artifact and required contents. | R3 NOT_REASSESSED. | NOT_EXECUTED |
| C24 | Package-hash and declared-dependencies gate verifies package identity and declared dependencies. | R3 NOT_REASSESSED; R4 semantic swap corrected. | NOT_EXECUTED |
| C25 | Owned process identity, bounded lifecycle, and cleanup; do not terminate another owner's process. | R3 partial; owned VAL/QA cleanup recorded, no normal product runtime. | NOT_EXECUTED |
| C26 | Normal public Full Apply authority through S12 export, durable worker, publisher, result, and media. | R3 BLOCKED at S10 422/B01; no authority fabricated. | BLOCKED_B01; no product proof. |
| C27 | Normal-product cancel, expiry/reconciliation, and fresh-worker restart after valid authority on same DB/job. | R3 BLOCKED; normal product path not reached. | BLOCKED_B01; no product execution. |
| C28 | Audio content identity (440 Hz source vs 880 Hz control), explicit remux/transcode, start/end sync, short-audio fail-closed, AudioReference channels/sample rate. | R3 mechanism controls green; public S12 audio media not reached. | NOT_EXECUTED; mechanism is NOT_EQUIVALENT to public-product audio. |
| C29 | Clean-host and human playback/listening gate, including audio when present. | R3 NOT_RUN; external gate open. | NOT_EXECUTED / NOT_REVIEWED |
| C30 | Retained-data migration preserves terminal rows, chunk/artifact hashes and pointers, and existing Job binding; no rewrite/data loss. | R3 RETRY migration green; R4 retained-data node passed; four inherited T03A compatibility failures remain. | NOT_EXECUTED in R5; four failures retained below. |
| C31 | Collection count/errors only; collection is never execution or pass evidence. | R3 collection-only at 364 collected. | NOT_EXECUTED |
| C32 | Candidate transport, ownership, hashes, guards, raw evidence, cleanup; transport confers no closure. | R3 transport green/not closed; R4 b6d7187 audit does not prove b6d620e. | PRE_INT_BASELINE_ONLY; post-INT audit pending. |

## S01-S10 prior-review findings

| ID | Original required control | R3 independent status | R5 disposition |
|---|---|---|---|
| S01 | Pre-receipt crash and real publishing-child kill/fresh worker on same DB/run/job; verify chunks and lifecycle. | OPEN_F02; fault probes not run. | NOT_EXECUTED |
| S02 | Private/public alias: commit fault, intact replay, rebuild/open-handle perturbation cannot change winner SHA; audit restart assembly. | PARTIAL; two controls passed, full alias/race matrix not rerun. | NOT_EXECUTED |
| S03 | Retry uniqueness: one successor/Job, immutable predecessor, repeated/two-live convergence, successor can retry. | OPEN_F01/F04 at successor claim. | NOT_EXECUTED |
| S04 | Windows companion temp preflight or typed supported-root denial before writes; short/deep/Unicode/space controls. | OPEN_F03; helper long-temp counterexample reproduced. | NOT_EXECUTED |
| S05 | Synchronized real child kill inside render/publication; fresh same-DB worker, all rows/lifecycle; dummy sleeper is not equivalent. | PARTIAL_SOURCE_ONLY; post-final boundary required. | NOT_EXECUTED |
| S06 | Normal public export through existing producers; identify genuine missing producer, no SQL/auto-approval, eventual media. | BLOCKED_B01. | BLOCKED_B01 |
| S07 | Actual expiry/current exclusive race; stale loser cannot mutate winner/companions; all rows. | PARTIAL; prior mechanism retained, full race not rerun. | NOT_EXECUTED |
| S08 | Stale cleanup preserves current owner files/companions and metadata. | PARTIAL; prior control retained. | NOT_EXECUTED |
| S09 | Preserve audio deadline/error/cancel/provenance thresholds without weakening. | PARTIAL; prior controls retained. | NOT_EXECUTED |
| S10 | Preserve C01-C32 stale-context, ownership, zero-mutation, navigation, retry guards after candidate terminal. | NOT_RUN; product UI gated. | NOT_EXECUTED |

## P01-P10 product stages

| ID | Original product-stage meaning | R3 evidence/status | R5 disposition |
|---|---|---|---|
| P01 | Legacy public project/video/source identities returned by server. | DEMONSTRATED in R3 raw chain. | NOT_REAUDITED |
| P02 | Public analyze/import/proxy/scene chain reaches durable shell. | DEMONSTRATED in R3 raw chain. | NOT_REAUDITED |
| P03 | Extraction worker completes; deterministic provider is fixture-only engineering mechanism evidence. | PARTIAL / FIXTURE_ONLY. | NOT_REAUDITED |
| P04 | Actual current roles, occurrences, structural-evidence segments. | DEMONSTRATED in R3 raw chain. | NOT_REAUDITED |
| P05 | Public character/version/assets validation and publish. | DEMONSTRATED in R3 raw chain. | NOT_REAUDITED |
| P06 | ProjectCast/ReskinConfig use returned IDs; lock pin was null. | PARTIAL in R3 raw chain. | NOT_REAUDITED |
| P07 | Server-owned public StructuralLock create/activate producer and manifest row. | BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY | NOT_EXECUTED; no public route/manifest. |
| P08 | Approved application authority executable by v2; S09 v1/reapprove 201 alone is insufficient. | BLOCKED; v2 authority not executable. | B01 BLOCKED / PROPOSED_ONLY |
| P09 | Full Apply accepts complete current authority. | BLOCKED; S10 returned 422 incomplete authority. | B01 BLOCKED / PROPOSED_ONLY |
| P10 | S12 export/media/UI reaches normal public result. | NOT_DEMONSTRATED / NOT_RUN; context missing authority, submit 409. | NOT_DEMONSTRATED / NOT_RUN |

## R01-R10 correction/evidence closure

| ID | Original mapping and closure semantics | R3 authority / R4 independent status | R5 disposition |
|---|---|---|---|
| R01 | F01/S03/C15: failed/cancelled predecessor; attempts 1/2/3; exactly 3 Runs and all 3 Jobs; one immediate successor each; immutable predecessor; malformed/self/cyclic/foreign/wrong-attempt denied without mutation. | R3 source confirmed, corrected runtime not run; R4 b6d620e reproduced F01/F03. | NOT_EXECUTED; OPEN/RED inherited. |
| R02 | F04/S03/C08,C15: two live sessions rendezvous at production successor creation; bounded join; one logical creator/successor/new Job for same/different client IDs; all-row totals 2/2; separate sequential control. | R3 open test structure; submitted probe source is not full reviewer closure. | NOT_EXECUTED |
| R03 | F04/C06,C07,C15: union identity/tamper, cross-scope/ambiguous claimant, read error, enqueue/bind/commit/lost ack; invalid is typed zero-delta, true zero-Job orphan repaired once, valid replay same pointer/zero delta, count all Jobs. | R3 adversarial gap; generation runtime not run; F01/F03 remain relevant. | NOT_EXECUTED |
| R04 | F02/S01/C17,C18: pre/post-final, sidecar, receipt, commit faults; own output converges to one Run/Job with stable chunk bytes/mtime; foreign/tampered/ambiguous/read-error preserves files and zero mutation. | R3 source confirmed, faults not run; R4 reproduced F02 ownership counterexample. | NOT_EXECUTED; OPEN |
| R05 | F02/S05/C14,C27: actual DurableWorker child killed at post-final/pre-sidecar; fresh same-DB Run/Job completes without extra rows; chunk hashes/mtime stable; record PIDs/rendezvous. | R3 partial source only; R4 exact probe exists, no R5 run. | NOT_EXECUTED |
| R06 | S02/S07/S08/C09,C17,C18: actual expiry race, exactly one publisher; stale cleanup/handle/rebuild cannot change winner/final/sidecar/receipt/candidate bytes or mtime; one Run/Job. | R3 partial; two controls passed, full race retained. | NOT_EXECUTED |
| R07 | F03/S04/C19: full publisher short/deep/space/Unicode and long server-derived temp names; supported completes, unsupported typed before public mutation; preserve foreign companion. | R3 helper counterexample reproduced; corrected path evidence finite, not full closure. | NOT_EXECUTED |
| R08 | S09/S10 and C01-C32 as separate controls: source identity/timing/provenance; audio content/start-end; audio deadline/error/cancel (separate); geometry; migration/hash/Job binding; stale/readiness/ownership. Never collapse or drop families. | R3 carry controls, not full reviewer rerun; RETRY retained-data migration passed; four T03A failures remain. | NOT_EXECUTED; inventory only. |
| R09 | F04 packet: all 62 rows, argv/cwd/start/end/duration/exit/raw/hash, failures, owner/model/turn/HEAD, guards/processes; collection is not execution. | R3 open evidence; R4 packet micro had semantic gaps. | Packet mapping micro only, not a candidate gate. |
| R10 | B01/S06/P07-P10: BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY; exact absent public StructuralLock producer/activation, zero manifest/S12 rows and typed downstream failure; no positive until separately owned producer exists. | BLOCKED_DEPENDENCY; R3/R4 public chain says no route/manifest, no approval/output. | BLOCKED_DEPENDENCY |

## Immutable probe inventory and classification

Static inventory against the clean pre-INT b6d620e candidate. PRESENT means source/function/title exists, not that it ran. NOT_EQUIVALENT means fixture/mechanism/packet evidence cannot satisfy the normal-product row. MISSING is the exact proposed node absent from the immutable R4 packet module. The R5 micro checks only this mapping.

| Case | Exact candidate path::probe | Inventory | Evidence class |
|---|---|---|---|
| C10 | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c10_runner_scales_320x180_to_real_3840x2160 | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C10 | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c10_hevc_eligible_only_when_measured | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C10 | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c10_unknown_profile_fails_explicit | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C10 | tests/s12/s12-t06b/test_scenario_f_4k.py::test_f1_upscale_1080p_to_2160_labeled | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C10 | tests/s12/s12-t06b/test_scenario_f_4k.py::test_f2_native_4k_control | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C10 | tests/s12/s12-t06b/test_scenario_f_4k.py::test_f3_provenance_decides_not_filesize | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C10 | tests/s12/s12-t06b/test_scenario_f_4k.py::test_f4_aspect_fail_closed_and_letterbox | PRESENT | MECHANISM_ONLY_NOT_PRODUCT |
| C20/C21 | frontend/e2e/s12-export.spec.ts::title: C20/C21: project-video entry point -> context -> submit updates scoped run pointer | PRESENT | SEEDED_E2E_FIXTURE_NOT_EQUIVALENT_TO_PUBLIC_PRODUCT |
| C21 | frontend/e2e/s12-export.spec.ts::title: C21: refresh giu nguyen run dang active, khong tao run moi | PRESENT | SEEDED_E2E_FIXTURE_NOT_EQUIVALENT_TO_PUBLIC_PRODUCT |
| C20 | tests/s12/s12-lc3-ui/test_export_context_contract.py::test_context_revision_changes_when_server_authority_changes | PRESENT | CONTRACT_ONLY_NOT_REAL_UI_CLICK |
| C20 | tests/s12/s12-lc3-ui/test_export_context_contract.py::test_context_response_rejects_client_filesystem_fields | PRESENT | CONTRACT_ONLY_NOT_REAL_UI_CLICK |
| C20 | tests/s12/s12-lc3-ui/test_export_context_contract.py::test_context_response_contains_no_filesystem_paths | PRESENT | CONTRACT_ONLY_NOT_REAL_UI_CLICK |
| C28 | tests/s12/s12-t06b/test_c28_audio_mapping.py::test_c28_audio_content_mapping_and_transcode_explicit | PRESENT | ENGINEERING_MEDIA_MECHANISM_NOT_PUBLIC_S12_AUDIO |
| C28 | tests/s12/s12-t06b/test_c28_audio_mapping.py::test_c28_start_end_drift_pin_and_fail_closed | PRESENT | ENGINEERING_MEDIA_MECHANISM_NOT_PUBLIC_S12_AUDIO |
| C28 | tests/s12/s12-t06b/test_c28_audio_mapping.py::test_c28_f01_publication_audio_reference_is_explicit | PRESENT | ENGINEERING_MEDIA_MECHANISM_NOT_PUBLIC_S12_AUDIO |
| C28 | tests/s12/s12-t04a/test_c2_source_locked.py::test_c28_remux_matching_audio_passes | PRESENT | VALIDATOR_MECHANISM_NOT_PUBLIC_S12_AUDIO |
| C28 | tests/s12/s12-t04a/test_c2_source_locked.py::test_c28_transcode_explicit_content_comparison_passes | PRESENT | VALIDATOR_MECHANISM_NOT_PUBLIC_S12_AUDIO |
| C28 | tests/s12/s12-t04a/test_c2_source_locked.py::test_c28_audio_start_drift_fails | PRESENT | VALIDATOR_MECHANISM_NOT_PUBLIC_S12_AUDIO |
| R08-provenance | tests/s12/s12-t01/test_s12_t01_c1_closure.py::test_c03_native_only_when_proved | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-provenance | tests/s12/s12-t01/test_s12_t01_c1_closure.py::test_c03_already_upscaled_4k_never_native | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-provenance | tests/s12/s12-t01/test_s12_t01_c1_closure.py::test_c03_1080p_upscale_honesty | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-provenance | tests/s12/s12-t01/test_s12_t01_c1_closure.py::test_c03_missing_provenance_below_4k | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-timing | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c12_source_order_cuts_rational_and_cfr | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-timing | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c12_vfr_rejected_before_any_work | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-timing | tests/s12/s12-t04a/test_s12_t04a_c1_closure.py::test_c12_seam_stitch_correct_order_passes | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-timing | tests/s12/s12-t04a/test_s12_t04a_c1_closure.py::test_c12_vfr_rejected_pre_work | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-timing | tests/s12/s12-t04a/test_s12_t04a_c1_closure.py::test_c12_cfr_control_matches_manifest | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-timing-mapping-correction | tests/s12/s12-t04a/test_s12_t04a_c1_closure.py::test_c12_rational_cuts_placement_passes | MISSING | C12_WRONG_MODULE_MAPPING_RETAINED_AS_MISSING |
| R08-geometry | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c11_portrait_pixels_letterboxed_no_stretch | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-geometry | tests/s12/s12-t03b/test_s12_t03b_c1_closure.py::test_c11_unsupported_profile_rejected | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-geometry | tests/s12/s12-t06b/test_scenario_f_4k.py::test_f4_aspect_fail_closed_and_letterbox | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-audio | tests/s12/s12-t06b/test_c28_audio_mapping.py::test_c28_audio_content_mapping_and_transcode_explicit | PRESENT | MECHANISM_NOT_PUBLIC_S12_AUDIO |
| R08-audio | tests/s12/s12-lc3-val/test_r1_correction_boundaries.py::test_r01_multicomponent_aac_transcode_passes_source_referenced_check | PRESENT | AUDIO_PROVENANCE_MECHANISM_NOT_R5_EXECUTED |
| R08-audio | tests/s12/s12-lc3-val/test_r1_correction_boundaries.py::test_r03_audio_cancel_mid_read_reaps_both_children | PRESENT | AUDIO_CANCEL_MECHANISM_NOT_R5_EXECUTED |
| R08-audio | tests/s12/s12-lc3-val/test_r1_correction_boundaries.py::test_r03_audio_deadline_interrupts_blocked_decoder_pipe | PRESENT | AUDIO_DEADLINE_MECHANISM_NOT_R5_EXECUTED |
| R08-audio | tests/s12/s12-lc3-val/test_r1_correction_boundaries.py::test_r03_stderr_pressure_and_nonzero_decoder_are_bounded | PRESENT | AUDIO_ERROR_MECHANISM_NOT_R5_EXECUTED |
| R08-migration | tests/s12/s12-lc3-retry/test_retry_migration.py::test_upgrade_retains_terminal_rows_hashes_and_binds_existing_job | PRESENT | R4_REVIEW_RETAINED_DATA_CONTROL_PASSED_NOT_R5_EXECUTED |
| R08-migration | tests/s12/s12-t03a/test_s12_export_migration.py::test_single_head_is_new_revision | PRESENT | INHERITED_COMPATIBILITY_FAILURE_RETAINED |
| R08-migration | tests/s12/s12-t03a/test_s12_export_migration.py::test_fresh_upgrade_creates_tables | PRESENT | INHERITED_COMPATIBILITY_FAILURE_RETAINED |
| R08-migration | tests/s12/s12-t03a/test_s12_export_migration.py::test_upgrade_from_parent_retains_data | PRESENT | INHERITED_COMPATIBILITY_FAILURE_RETAINED |
| R08-migration | tests/s12/s12-t03a/test_s12_export_migration.py::test_downgrade_with_rows_refuses | PRESENT | INHERITED_COMPATIBILITY_FAILURE_RETAINED |
| R08-migration | tests/s12/s12-t03a/test_s12_export_migration.py::test_history_links_parent | PRESENT | R4_REVIEW_CONTROL_PASSED_NOT_R5_EXECUTED |
| R08-migration | tests/s12/s12-t03a/test_s12_export_migration.py::test_empty_downgrade_drops_only_new_tables | PRESENT | R4_REVIEW_CONTROL_PASSED_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-t03a/test_s12_export_domain.py::test_create_stale_checkpoint_hash_fails_closed | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-t03a/test_s12_export_domain.py::test_create_stale_checkpoint_revision_fails_closed | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-t03a/test_s12_export_domain.py::test_create_stale_manifest_hash_fails_closed | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-t03a/test_s12_export_domain.py::test_create_stale_manifest_generation_fails_closed | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-t03a/test_s12_export_domain.py::test_create_cross_project_checkpoint_fails_closed | PRESENT | RETAINED_MECHANISM_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-t03a/test_s12_export_c1_closure.py::test_c09_expired_lease_old_token_zero_mutations | PRESENT | STALE_OWNERSHIP_MECHANISM_NOT_R5_EXECUTED |
| R08-stale-readiness | tests/s12/s12-lc3-ui/test_export_context_contract.py::test_context_revision_changes_when_server_authority_changes | PRESENT | CONTEXT_CONTRACT_NOT_REAL_UI_CLICK |
| R10 | tests/s12/s12-lc3-qa-r3/r3_public_producer_chain_harness.py::script | PRESENT | HISTORICAL_PUBLIC_CHAIN_BLOCKER_EVIDENCE_NOT_POSITIVE_PRODUCT_PROBE |
| R10 | tests/s12/s12-lc3-qa-r4/r4_readonly_audit.py::script | PRESENT | READ_ONLY_B01_AUDIT_NOT_POSITIVE_PRODUCT_PROBE |
| R10 | tests/s12/s12-lc3-qa-r4/test_r4_review_packet.py::test_r4_report_keeps_product_and_mechanism_separate | PRESENT | PACKET_ASSERTION_ONLY |
| R10 | tests/s12/s12-lc3-qa-r4/test_r4_review_packet.py::test_missing_authority_is_typed_and_zero_mutation | MISSING | R3_PROPOSED_ONLY_NODE_NOT_PRESENT_B01_REMAINS_BLOCKED |

The former C12 path-qualified mapping is retained as MISSING because that symbol is absent from `test_s12_t04a_c1_closure.py`. The corrected inventory uses the exact-rational T03B node and the three exact T04A nodes above. These are static source mappings only; no C12 tests were executed in this R5 packet micro.

Candidate probe bytes are snapshotted in candidate-probes-prewrite.json and candidate-probe-snapshots in the external lane. These are read-only inspection inputs; no probe was copied or edited.

## R4 semantic corrections and product boundary

- C10 is real runner 4K raster/codec behavior with distinct upscale/native controls, not retry or Job identity.
- C20 is project Export UI entry/context/preflight/submit; C21 is distinct reload/reopen/recovery preserving the same server run. Existing seeded Playwright is fixture-only.
- C24 is package hash plus declared dependencies.
- C28 is audio content identity and synchronization, not UI; mechanism tone/validator evidence cannot demonstrate public S12 audio.
- R08 retains separate timing/provenance, audio content/deadline/error/cancel, geometry, migration/hash/Job-binding, and stale/readiness/ownership families.
- The b6d7187 audit does not prove b6d620e. Post-INT immutable execution remains pending.
- P07 remains BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY; R10 remains BLOCKED_DEPENDENCY. No public export, result/media, UI, or playback is claimed.

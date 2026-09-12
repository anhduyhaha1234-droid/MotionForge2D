# S12-LC3-R5 QA checkpoint report

Status: QA-only F04 packet correction is green and ready for local checkpoint; not an approval or closure report.

Owner/session: QA Goodall / 01a08991-c909-7d03-86ed-ac236d50c87b. Route per accepted assignment: gpt-5.6-luna, reasoning high, fallback OFF. QA checkout/branch: C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa / codex/s12-lc3-luna-qa. Pre-write QA HEAD: 550494c2bfdd90dce21958cd56d6901d12c5b80b. Read-only pre-INT integration candidate: C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration / codex/s12-lc3-luna-integration at b6d620eb00f65d31af85b3d64badc7f31f504830, clean at inspection.

The full R3 authority hash was verified as 98C929FAB41A52BF5EF148A088230F0D87ADBFB28FD2BCE891C40DC9E6A4EC54. R5_MATRIX.md restores all 62 original row IDs and semantics, with historical evidence separated from this R5 packet status. It corrects C10 to actual 4K, keeps C20 project Export UI separate from C21 reload/recovery, restores C24 package-hash plus declared dependencies, restores C28 audio content/sync, and lists R08 retained control families separately. C12 static mapping includes T03B `test_c12_source_order_cuts_rational_and_cfr` and `test_c12_vfr_rejected_before_any_work`; T04A `test_c12_seam_stitch_correct_order_passes`, `test_c12_vfr_rejected_pre_work`, and `test_c12_cfr_control_matches_manifest`. The obsolete path-qualified `tests/s12/s12-t04a/test_s12_t04a_c1_closure.py::test_c12_rational_cuts_placement_passes` is explicitly MISSING, not counted as a pass; all mapping statuses are static inventory only.

P07 remains BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY and R10 remains BLOCKED_DEPENDENCY: no public StructuralLock producer/activation route or manifest is present or fabricated. The separate upstream B01 proposal is PROPOSED_ONLY; that is not a P07/R10 matrix status. No public S12 export, result/media, UI, playback, or download evidence is claimed. Mechanism 4K/audio tests and seeded Playwright remain NOT_EQUIVALENT to normal-product evidence.

The R4 independent review's four T03A migration compatibility failures are preserved without source edits, skip/xfail, or waiver:

- tests/s12/s12-t03a/test_s12_export_migration.py::test_single_head_is_new_revision — expected old sole head c3d4e5f6a7b8; actual head was d4e5f6a7b8c9.
- tests/s12/s12-t03a/test_s12_export_migration.py::test_fresh_upgrade_creates_tables — table/PK/index controls reached stale version assertion (expected c3d4e5f6a7b8, actual d4e5f6a7b8c9).
- tests/s12/s12-t03a/test_s12_export_migration.py::test_upgrade_from_parent_retains_data — retained workspace row assertion passed, then old version expectation failed (expected c3d4e5f6a7b8, actual d4e5f6a7b8c9).
- tests/s12/s12-t03a/test_s12_export_migration.py::test_downgrade_with_rows_refuses — downgrade refused before DDL, but actual “refusing downgrade (pre-DDL)” did not match old regex “refusing to downgrade”.

Source: independent review migration-focused.raw.txt and migration-focused.execution.json; raw SHA-256 bc18312396ec51e10d7d8301a6e31298b042b485e4ed9c91b38a0fbbc9af67cf. That review reported 3 passed / 4 failed across six T03A nodes plus retained RETRY migration; retained-data RETRY migration passed. Historical evidence only, not an R5 rerun.

## Gate boundary

The final packet-only invocation was `python -B -m pytest tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py -q -p no:cacheprovider` from the QA checkout with candidate root/SHA pinned to the clean pre-INT `b6d620eb00f65d31af85b3d64badc7f31f504830`. It exited 0 (`3 passed`); envelope `r5-packet-micro-final-harness.command.json`, raw stdout SHA-256 `FDFCD384D5E6AD0889BDA391B2BBC5A5EC0F22D8D6EF70C60F3D2660BBC2CBDC`. Ruff final exited 0; QA pre-write guard verification exited 0 (8 entries), immutable candidate-probe guard exited 0 (17 unchanged entries), and the final precommit guard capture/verify exited 0 across 9 entries. Failed packet and Ruff attempts remain preserved with exact envelopes/hashes in R5_COMMAND_LEDGER.md and the external evidence lane.

No immutable candidate test, S12 collection/full suite, UI flow, public API, video, or playback is run before serial INT transport. The R5 micro verifies packet rows, semantic anchors, and static source/probe mapping only. It is not product or mechanism proof. The b6d7187 audit is not substituted for b6d620e or the eventual exact post-INT candidate.

The packet micro is green and initial QA/candidate guards are clean. Commit only R5 QA-owned files locally after staged diff validation. Final-candidate checks remain gated while RETRY/VAL writers are active and until serial INT transport identifies the exact full SHA. Then audit that precise candidate: packet micro first, unchanged applicable immutable nodes by exact IDs, finite/static checks, and one bounded broad suite. Preserve all four migration failures. No merge, push, approval, or closure is authorized.

Evidence lane: C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r5-owner-submission/20260912T164057Z/QA/matrix-packet-20260912T171510Z. Runtime lane: C:/Users/Admin/Documents/Codex/work/s12-r5/20260912T164057Z/QA/matrix-packet-20260912T171510Z. Pre-write guard manifests: qa-prewrite.json and candidate-probes-prewrite.json.

Terminal at this checkpoint: post-INT candidate audit NOT_RUN_PENDING_SERIAL_INT; normal-product export/video/UI NOT_DEMONSTRATED; B01 blocked; NOT_CLOSED / NOT_APPROVED.

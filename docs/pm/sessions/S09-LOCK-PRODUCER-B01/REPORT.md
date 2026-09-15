# S09-LOCK-PRODUCER-B01 — owner report (Hermes, R6 correction)

Verdict requested: CHANGES_REQUESTED / NOT_APPROVED / NOT_CLOSED → this is the
bounded correction + missing public producer. Status: TASK_SUBMITTED →
pending independent review (no APPROVED/CLOSED claimed).

- Session: `20260915_201612_7bb91e` · model `ocg/deepseek-v4.1-flash` ·
  provider `custom` · fallback OFF.
- Worktree: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/work/s12-r6-b01`
  · branch `codex/s09-lock-producer-b01-r6` · base
  `83af5167e9dddc931bc8590f547684c0c811784b`.
- Transport commit: `9caa22329cbb2cb0c0a07ee36e9878778b5a4496` (parent =
  base; 8 files, +2728/-4; local only, NO push). Post-commit gate re-run:
  `17 passed in 67.40s` on the frozen commit.

## Files changed (exact)

| File | State | sha256 (postimage) | bytes | lines |
|---|---|---|---|---|
| `app/services/structural_lock_producer.py` | NEW | `c09c2ead418d0b75a2f9da0eab4bf7ec2def5c20336c14e5f0a7b1926189b152` | 39455 | 1016 |
| `app/api/routes/structural_lock.py` | NEW | `1385422a8e9fdb96d1d8b831414f6d60f28b35b1aabdb0a2d71863159f8c4fef` | 5261 | 139 |
| `app/schemas/structural_lock.py` | bounded +45/-4 | `e22d7ea3ac9ac33dd12ee679ceeb0346d02732203339b4ce46ca78072e4e332e` | 9099 | 243 |
| `app/api/app.py` | bounded +8 (import + mount only) | `312e755a91a8467a71d5b67c43d8af1a69bc5c682beda90ce88bf5499010c46a` | 9979 | 238 |
| `tests/test_s09_structural_lock_producer.py` | bounded patch (E02) | `3dcade0f329c070737ba6269ad1511125c086ae919e89b2bf65066074a8c490d` | 47502 | 1309 |
| `docs/pm/sessions/S09-LOCK-PRODUCER-B01/**` | NEW | see CONTRACT.md / LOG.md | | |

Preimages: test file `813ac599e115a6cb00234ecf89efd7ecb53c544a0d829be77c1d56d1d7533d1f`
(385 B/12 lines, recorded BEFORE patch; matches the reviewer snapshot);
`app.py` `ae79fdb2…`, schemas `78636fdf…` (via `git show 83af516:<path>`).

## B01-A–H case status (all executed, node ids exact)

| Case | Node | Result |
|---|---|---|
| B01-A | `test_B01_A_success_current_source_evidence_graph` | PASS — real current graph → nonempty server-derived manifest; exact source/generation/timebase/shot_order/fingerprints recomputed independently; removal-only segment excluded; exactly ONE active lock |
| B01-B | `test_B01_B_equivalent_replay_no_extra_rows` | PASS — same manifest/hash/version, `created=false`, zero extra route/config/checkpoint/manifest rows |
| B01-C | `test_B01_C_two_live_callers_exactly_one_creator` | PASS (stable x3) — barrier at actual creation; exactly one creator, one coherent manifest, all-row proof (1 manifest / 2 decisions) |
| B01-D | typed denial matrix: `test_missing_evidence_denied_typed`, `test_stale_expected_identity_conflicts_typed`, `test_tampered_source_and_evidence_denied_typed`, `test_cross_workspace_and_foreign_scope_denied_typed`, `test_client_authority_and_filesystem_fields_rejected`, `test_unsupported_policy_route_and_ambiguity_denied_typed`, `test_role_mapping_prerequisite_denied_typed`, `test_removal_only_only_graph_has_no_empty_success` | PASS — every denial typed with zero durable mutation |
| B01-E | `test_B01_E_generation_change_and_supersession` | PASS — stale key → typed conflict; supersession archives v1 bytes unchanged; new generation explicitly validated; old lock never current authority for the new generation |
| B01-F | `test_B01_F_pin_and_reapproval_full_apply_executable` | PASS — existing ReskinConfig CAS pin (stale revision 409); real public S09 reapproval → `full_apply_executable=true`, `reasons=[]`, `unsupported_routes=[]`, every segment executable |
| B01-G | prerequisites enforced in the producer (source, segments, geometry, role mappings, published pack, eligible routes); empty manifest denied; executable proof in B01-F | PASS |
| B01-H | `test_B01_H_transaction_failure_no_partial_state_then_retry`, `test_B01_H_read_failure_typed_denial` | PASS — mid-write failure → whole-transaction rollback, deterministic retry; read failure → typed 422 zero mutation |
| B01-I | downstream public chain incl. S10→S12→worker→publisher→media/UI | NOT_RUN here — QA-owned per acceptance (producer + pin + executable reapproval proven above) |

## E01 closure

Historical failure = wrong path (`…tr-x20\app\api\app.py`, omitted
`work/s12-r6-b01`) + shell patch argument/syntax errors. This session used
exact worktree-absolute paths with the native bounded patch tool: **no
operation was denied**, no permission workaround, no global repair. The
diagnosis "path/invocation, not permission" holds.

## E02 closure

Preimage preserved and recorded; bounded patch to the corrected harness
(route registration on the production app + typed denial matrix + valid
public success with isolated env/DB configured BEFORE app import, real
application lifespan, production close-only session dependency). Old invalid
node (fake ids → expect 201) removed; fake ids now asserted to be DENIED.
Execution: 17 passed x2 (`python -B -m pytest tests/test_s09_structural_lock_producer.py
-q -p no:cacheprovider`, 50.81s / 61.22s).

## Regression evidence

- `tests/test_s09_t00_structural_lock_domain.py` 11 passed.
- `tests/test_s09_reskin_source_locked_domain.py` 13 passed.
- `tests/test_s09_t06_backend_api.py` 15 passed.
- `tests/test_api.py` 25 passed; `tests/test_s08_h02_security.py` 71 passed.
- `tests/test_s09_t06_backend_authority.py` 20 passed + 1 **pre-existing**
  failure: `test_single_head_and_models_unchanged` pins head
  `a10b11c12d3e`, repo head is `d4e5f6a7b8c9` (commit f966225, ancestor of
  the base; no migration touched by this write-set).
- Ruff `--select F` clean on all five changed files.

## Consumer observations (exact, for the reviewer)

1. `ReskinConfig` CAS pin re-enforces the S07 compatibility policy: a pin is
   refused (409 `{"detail": "compatibility blocked:
   incomplete_pack,missing_required_pose"}`) when the pack lacks
   `CORE_POSE_SLOTS` (front/three_quarter/side/back/sitting/walking), even
   though `status="published"`. The producer prerequisite mirrors the S09
   executable-authority contract (pack published/ready) and stays unchanged;
   the pin remains the existing consumer gate. The QA/product chain must pin
   a config whose pack is complete (the R3 harness already attaches all six
   slots). No write-set change proposed unless the reviewer wants the
   producer to pre-check slot completeness.
2. Route-decision rows created by the producer are bound to the produced
   manifest id, so the existing config-pinned evidence surface
   (`reskin-configs/{id}/renderer-route-evidence`) can attribute them
   (rows with NULL manifest id remain excluded by that surface's contract).
3. No other legacy/v2 consumer incompatibility was reached.

## Evidence

`C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/B01/`
— `write-set-postimage-hashes.json`, `e02-test-preimage.json`,
`bounded-patch-log.txt`, `pytest-raw-final-r1.txt`, `pytest-raw-final-r2.txt`,
`regression-s09-raw.txt`, `COMMAND_LEDGER.jsonl`.

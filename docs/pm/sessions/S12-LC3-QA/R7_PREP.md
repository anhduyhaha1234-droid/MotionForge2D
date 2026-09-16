# S12-LC3-QA — R7 prep record (Q01 corrections, Q02 migration compat, Q03 R5 env)

Turn: R7 PREP + COMPATIBILITY, Hermes owner session `20260915_201612_aeb5e3`, route `ocg/deepseek-v4.1-flash` / provider custom / fallback OFF / native thinking ON. Wave-base worktree HEAD at start: `35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86` (branch `codex/s12-lc3-luna-qa`, clean). Public product chain NOT run this turn (dependencies: BRIDGE/B01 corrections not landed; B01-I stays blocked).

## Q03 — R5 audit environment: exact values and invocation

The R5 packet test reads the audited integration checkout via two environment variables and never weakens them (no skip, no `None` fallback — the assertions at `tests/s12/s12-lc3-qa-r5/test_r5_matrix_packet.py:52-82` stay byte-intact: root must exist, HEAD must equal the expected SHA, branch must be `codex/s12-lc3-luna-integration`, tree must be clean).

**Exact values for the R7 wave-base (frozen tip current at this turn):**

```
S12_R5_CANDIDATE_ROOT=C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration
S12_R5_EXPECTED_CANDIDATE_SHA=35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86
```

**Exact invocation (run from the QA worktree; no other change needed):**

```
export S12_R5_CANDIDATE_ROOT="C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration"
export S12_R5_EXPECTED_CANDIDATE_SHA="35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86"
C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests/s12/s12-lc3-qa-r5/ -q -p no:cacheprovider
```

**How to verify the values before a gate (all read-only):**

```
git -C C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration rev-parse HEAD      # must print the expected SHA
git -C C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration branch --show-current # must print codex/s12-lc3-luna-integration
git -C C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration status --porcelain   # must print nothing
```

When the integration owner transports a new verified wave (VAL/RETRY/B01/BRIDGE/QA), the expected SHA changes with the new frozen tip; Manager must re-read HEAD and export the two variables with the new value at gate time. The value recorded above is the wave-base record, not a permanent constant.

Evidence: `r5-env.stdout.txt` / `r5-env.stderr.txt` (this evidence dir) — full module `3 passed in 2.14s`, exit 0, including `test_r5_probe_inventory_is_static_and_exactly_mapped` with the env above. Baseline (env absent, before this turn): exit 1, `S12_R5_CANDIDATE_ROOT must identify the audited integration checkout` — recorded in `baseline-r5.stdout.txt`.

## Q02 — T03A migration test compatibility (bounded exception)

`tests/s12/s12-t03a/test_s12_export_migration.py` was written for revision `c3d4e5f6a7b8`; the current sole head is `d4e5f6a7b8c9` (additive retry-lineage + durable Job binding on top). The correction separates the two revisions explicitly and never replaces `NEW_REV` blindly:

- `TARGET_REV = "c3d4e5f6a7b8"` (revision the suite was written for; creates the three S12 export tables) and `CURRENT_HEAD = "d4e5f6a7b8c9"` (current sole head) are distinct constants; `NEW_REV` is gone.
- Both linear edges are asserted individually (`PARENT_REV -> TARGET_REV`, `TARGET_REV -> CURRENT_HEAD`) plus a linear walk from head to parent (no branch).
- Fresh upgrade, retained-data upgrade to head, and the lineage backfill (seed at `TARGET_REV`, upgrade to head: `lineage_id` from `natural_key`, unambiguous `job_id` binding, FK check clean) are all executed on real migrated temp DBs.
- Nonempty-downgrade refusal retained: exact current-head guard message asserted, head/rows unchanged; the export-domain guard text is proven retained in isolation; empty downgrade unwinds the lineage block at `TARGET_REV` (original six-field identity unique constraint restored) and then drops exactly the three tables back to `PARENT_REV`.
- No migration, model or schema file was touched; no xfail/skip; no assertion weakened (coverage was added).

Delivered node IDs (full module, all executed): `test_single_head_is_current_head`, `test_history_links_both_linear_edges`, `test_history_walk_from_head_is_linear_to_parent`, `test_fresh_upgrade_creates_tables`, `test_upgrade_from_parent_retains_data_to_current_head`, `test_upgrade_to_head_backfills_lineage_from_seeded_run`, `test_downgrade_with_rows_refuses_at_current_head`, `test_export_domain_guard_text_is_retained`, `test_empty_downgrade_unwinds_lineage_then_tables`.

Evidence: `t03a-fixed-v1.stdout.txt` / `t03a-fixed-v1.stderr.txt` — 9 passed in 9.49s, exit 0. Baseline (before): `baseline-t03a.stdout.txt` — 4 failed, 2 passed (four inherited stale-head failures).

## Q01 — corrected evidence claims

Corrected in QA-owned docs this turn (bounded patches; old text retained as provenance where it is historical):

1. The B01-I public chain stops at `s10_full_apply_submit` (HTTP 422 shots-overlap). S12 preflight is **NOT_REACHED / NOT_REEXECUTED**: the chain harness calls it only after a successful S10; no `s12_preflight` stage exists in `b01i-stages.jsonl`. (Reviewer F05.)
2. “Missing producer / B01 BLOCKED_DEPENDENCY” is obsolete: the public StructuralLock producer exists and is mounted (reviewer P07 disposition: `PRODUCER_PRESENT_WITH_OPEN_F03`); the open producer item is F03 timing defaults, owned by S09-LOCK-PRODUCER-B01.
3. “Single residual / only S10 overlap” is obsolete: open families per independent review are F01 (lease serialization), F02 (identity/encoding), F03 (invented timing), F04 (S09-executable vs S10 planning incl. co-occurring segments + points-only geometry + same-role disjoint ranges), F05 (C02 evidence claim).
4. Honest labels retained: fresh/inherited/not-run; setup failures and inherited broad failures kept as-is; deterministic-extraction / synthetic-media labels kept; human playback NOT_REVIEWED; no product/UI/video/audio pass claimed.

## Freeze inventory R7

See `R6_INVENTORY.md` section “R7 additions — freeze for writers”: original 62 + R6 rows unchanged; R7 rows (A01–A06 references, B01–B06, Q01–Q04, P01–P03) with owner, source location, required outcome and raw destination. Nodes that do not exist yet are explicitly marked “to be frozen by owner” (no invented node names); Q01–Q03 records this turn's executed/delivered state.

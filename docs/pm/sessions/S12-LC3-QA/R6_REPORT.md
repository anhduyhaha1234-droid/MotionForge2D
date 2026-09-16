# S12-LC3-QA — R6 finite inventory freeze + harness prep report

Status: R6_INVENTORY_FROZEN / HARNESS_PREPPED / QA_PRODUCT_NOT_EXECUTED. Terminal: NOT_CLOSED / NOT_APPROVED. This is a QA preparation checkpoint, not an approval or closure: no product, mechanism, UI, video or audio pass is claimed, and collection is not execution.

Owner/session: Hermes owner after one-time transfer (reason USER_REQUESTED_PLATFORM_MODEL_TRANSFER), session `20260915_201612_aeb5e3`.
Route: `ocg/deepseek-v4.1-flash` / provider `custom` / fallback OFF.
QA worktree/branch: `C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-qa` / `codex/s12-lc3-luna-qa`.
Wave base: `git merge --ff-only 83af5167e9dddc931bc8590f547684c0c811784b` fast-forwarded from `b6ab84e7e80ce673dda7a5c1ce517732fea06688`; HEAD is exactly `83af5167e9dddc931bc8590f547684c0c811784b` after sync, clean status; the local transport commit for this checkpoint is recorded in the lane COMMAND_LEDGER (message `S12-LC3-QA: R6 finite inventory freeze + harness prep`).

## What was frozen (before implementation of other lanes)

- `docs/pm/sessions/S12-LC3-QA/R6_INVENTORY.md` locks executable node IDs + parameter IDs for all of M01-M19 (RETRY), V01-V15 (VAL) and B01-A-B01-H (producer), plus B01-I (QA), with expected typed outcomes, all-row Run/Job counts and raw evidence path templates, per R6_ACCEPTANCE.md.
- RETRY module frozen: `tests/s12/s12-lc3-retry/test_r6_identity_resolution.py` (19 nodes).
- VAL module frozen: `tests/s12/s12-lc3-val/test_r6_publication_ownership.py` (15 nodes).
- Producer module frozen: `tests/test_s09_structural_lock_producer.py` (existing 385-byte preimage patched, not replaced; 8 nodes B01-A-B01-H).
- QA micro: `tests/s12/s12-lc3-qa-r6/test_r6_finite_inventory.py` (inventory/62-row/gates/provenance checks) and `tests/s12/s12-lc3-qa-r6/test_r6_b01i_prep.py` + `tests/s12/s12-lc3-qa-r6/r6_b01i_plan.py` (B01-I prepped-not-executed harness).

## Retained gates (must not disappear in summarization)

- R04 lost-ack/SHA prohibition: successful commit / lost acknowledgement executable rows M16 and V07; never adopt by matching SHA alone; chunks bytes/mtime preserved (V07, V08).
- R07 Windows companion paths: interrupted temp (V15), basename155+ and server export_master.mp4 (V14); supported full publisher completes; unsupported typed denial before public writes.
- R08 exact collection/full modules/no new skips: exact collection/node lists snapshotted; complete applicable modules; no new skips or threshold relaxation; retained families (source identity/timing/provenance; audio content/start-end; audio deadline/error/cancel; geometry; migration/hash/Job binding; stale/readiness/ownership) stay separate.
- Original 62-row authority carried verbatim: C01-C32 + S01-S10 + P01-P10 + R01-R10 = 62 unique IDs, no more, no fewer; no row APPROVED or CLOSED.

## Reviewer assertion provenance (file + mapping)

Corrected reviewer assertions are kept immutable and hash-proven in the QA micro (existence + normalized SHA-256):
`R3_MATRIX_AUTHORITY.md` 98C929FAB41A52BF5EF148A088230F0D87ADBFB28FD2BCE891C40DC9E6A4EC54 (62 rows + R01-R10) -> all frozen rows; R5 `REVIEW.md` B85ED4B6EC5E2740B2BE2C329D91B22D64D196E17F5AA87335C7B7F083826302 (F04) -> R04/R07/R08 gates; R5 `test_review_r5_identity.py` 155A2D2C32E31FEFC9F7CF6DC24C0D5FA1897FA53A4C4517F7556DD6E1146985 (F01) -> M06/M08/M11/M14/M19; R5 `test_review_r5_publication.py` 5D5DB9C46EA20257EC9452038102385C9F5E4661572428B8D20CE67E844DB087 (F02/F03) -> V03/V04/V09/V10; preserved preimage `test_review_r5_publication.setup-v1.txt` DBF1A83BEE14500CA65C0519748D3D6DF9446D76E3E9AB6858076C87B47D8ED4 (s12_export_lease keyed by run_id correction); `R6_ACCEPTANCE.md` 3CDDE8605501D8A7BEA6A540800257BF6ACF7D33D27831FB0C7EB33F37D0434E, packet `REVIEW.md` AD5FFF3B97BF470FF007022C42FD94B6C947CA44858EE32F77D85905CE2ECEFB, `NEXT_HERMES_PROMPT.md` 29E6D6C6D2DA0425453C486C21BD21C3BC9703F47E327C0986762A44FB42BFFD, R6-exec `REVIEW.md` C61220A6DCB7659409D0F7236F98783545BCAB0858E2CC85612599AC51DA45D1. In-repo R5 docs stay byte-immutable (R5_MATRIX.md D601E8FACA20E096D44E8F97A0FA783890432BB63D441269B2DCE88ABC90735C, R5_REPORT.md 5CCF38003CE077565F9733B74475084B48CA20EC1D2F3A31F9EDCDA7642EDEB2, R5_COMMAND_LEDGER.md 5F3E7AAD03AA6F303CECDA87E063FE11164013FECF55763907D5DA5E4BFAF794). The corrected reviewer root used is `s12-r5-independent-review-20260914` (not the nonexistent path from E04). Every new run uses a new S12_REVIEW_OUT directory; old outputs are never overwritten.

## B01-I — prepped, not executed

B01-I is frozen as PREPPED_NOT_EXECUTED in `r6_b01i_plan.py`: node `tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py::test_b01i_public_product_chain_submit_worker_publisher_result_media_ui`; exact command `["C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe", "-B", "-m", "pytest", "<node>", "-q", "-p", "no:cacheprovider"]`; env `S12_REVIEW_OUT`, `S12_R6_CANDIDATE_ROOT`, `S12_R6_EXPECTED_CANDIDATE_SHA`; per-run output dir created exclusively under `.../s12-r6-hermes/<uniqueUTC>/QA/B01-I/<run_id>/`; dispatch guard refuses until dependencies are recorded satisfied.

## Waiting list

- WAITING_FOR RETRY: M01-M19 executable nodes in the frozen RETRY module.
- WAITING_FOR VAL: V01-V15 executable nodes in the frozen VAL module.
- WAITING_FOR B01: B01-A-B01-H in the patched producer test (existing task, no duplicate).
- WAITING_FOR INT: serial transport VAL -> RETRY -> B01 -> QA and the frozen candidate SHA; then B01-I may run once.
- B01 remains BLOCKED_DEPENDENCY (no public producer yet); product rows C20-C22/C26-C27/P07-P10 remain blocked/unexecuted.

## Micro run

Command: `C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe -B -m pytest tests/s12/s12-lc3-qa-r6/ -q -p no:cacheprovider`.

- 11 tests collected; 11 passed, 0 failed, 0 skipped, 0 errors; exit 0 (draft run 11 passed in 1.75s; second run 11 passed in 1.81s; final confirmation run captured as `r6-qa-pytest-final.*`; exact collect-only node list and count in `r6-qa-collection.*`).
- Static gates: `ruff check --select F` exit 0; full `ruff check` exit 0 on the three QA R6 Python files.
- These are QA packet/static checks only. Exact collection/node IDs and counts are recorded in the lane evidence and never summarize a pass for any owner lane; collection is not execution. No new skip or threshold relaxation was introduced.

## Evidence paths

- Lane evidence root: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/QA/` (raw pytest stdout/stderr + command envelopes, collection/node lists, pre/post guard manifests with byte snapshots, new-file hash manifest, `COMMAND_LEDGER.jsonl`).
- Runtime root: `C:/Users/Admin/Documents/Codex/work/s12h/20260915T131158Z/QA/`.

## Boundaries

Production bytes, owner-lane tests (read-only), MAIN, S11/S13, demo, other worktrees: untouched. No push, reset, clean, stash, rebase or force. No new skips or weakened assertions. No APPROVED/CLOSED claim; Codex review remains the only closure authority.

---

# R6 B01-I execution — 2026-09-15, frozen candidate 0c18d2d (append)

Status: `EXECUTED_BLOCKED_S10_SHOTS_OVERLAP`. One bounded real public chain per run (no SQL seed, no private handler shortcut, every identity returned by a public route); FINAL recorded run `20260915T164349Z` on candidate `0c18d2d19fdb40c7c62d88da9ac4d39a72e48385` (QA worktree HEAD at run time; ff-synced from `69a1280`).

What PASSED on the final run (real IDs): legacy project `e5e93c5c336a` + upload + analyze/import/proxy/scene completed; DISCOVER_OBJECTS durable worker completed; 2 roles confirmed; character `6a076f1c-3f14-431e-bc8c-e208f7b27f76`, pack version `36cc0cf9-0b21-4439-b96a-b3c614d05c4c` published (6 pose slots); ProjectCast + ReskinConfig per role (configs `2b707a05-7d8f-44d8-ad84-564313d8d931`, `1f686989-929e-4438-9f76-e33767cc5449`); producer 201 → manifest `5111dbcd-7d9c-460b-8035-2315f99fb6e5` hash `990152a3bb8f9641fa21928b92d8a6ab4fbe8211c17ac8191af87c3e6583330e` (segment_count 2, 2 route decisions); CAS pins applied; S09 reapproval v2 → checkpoint `83bccabe-dd4d-4b6c-b168-2d4c66a6f1a9` with `full_apply_executable=true`; full-apply authority read executable.

BLOCKED stage (exact): `POST /api/v2/projects/e5e93c5c336a/full-apply?workspace_id=default` `{video_item_id: fca69c7b-14ee-4f0c-bfe7-c11f3220dd5c, apply_checkpoint_id: 83bccabe-dd4d-4b6c-b168-2d4c66a6f1a9, expected_checkpoint_hash: d3a424a034f789f2a4d1640b5e2f3c30ae08684760fa9f1f3b0ceb2f24ec502e, expected_checkpoint_revision: 2}` → 422 `shots overlap or non-monotonic: shot 29963538-7ff4-5bb8-9212-aea7fc70c26d [0,119] and 627b554b-4bbb-55b6-8600-65df9edd3de4 [0,119]`. Reproduced across five runs, including a multi-scene fixture (additional observation: scene-local frame ranges per scene). DB delta at failure: structural_lock_manifests=1, apply_checkpoints=1, reskin_configs=2, artifacts=7, jobs=4, s10_full_apply_runs=0, s10_publications=0, s12_export_runs=0 (all zero before the chain).

Root contract collision (evidence-backed, no verdict): the S10 service maps each manifest SEGMENT 1:1 to a render "shot" and the S10 chunk planner requires contiguous non-overlapping shots, while the public producer legitimately includes all current-active segments — co-occurring objects (the sanctioned deterministic extraction always co-occurs `Hero`+`Twin`) always overlap. Proposed minimal next ownership (not applied): primary — derive S10 shots from the manifest `shot_order`/scenes and keep per-segment regions/mappings (write-set `app/services/s10_full_apply.py`, maybe `app/services/s10_chunk_plan.py`; owner S10-T01C lineage); safety net — typed producer denial for unpartitionable graphs (`app/services/structural_lock_producer.py` + contract). Codex decides; neither lane is in this wave's write-set.

Not reached (dependency on the blocked stage): S10 run/job/publication, original-audio attach, QC/readiness, S12 context/preflight/submit, worker/publisher/media, UI submit/reload, replay/reload duplicate checks. UI additionally: real browser Export UI NOT_RUN — `frontend/node_modules` absent, no install performed. Human playback: NOT_REVIEWED. No B01-I acceptance is claimed; B01-I stays blocked in `R6_INVENTORY.md` with node `tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py::test_b01i_public_product_chain_submit_worker_publisher_result_media_ui` (dual-mode: executes with frozen env pins, otherwise verifies the newest recorded run and re-raises its terminal status).

Evidence (final run, exclusive dir; older runs preserved): `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/20260915T131158Z/QA/B01-I/20260915T164349Z/` — `b01i-chain.json` sha256 `72BB20C7F1ADC82FF8858A7D12FB740F2CE59E7D1626B6DDC06088396692078F`; `b01i-stages.jsonl` sha256 `FA50652D26EB18FAF9724BE5EC013828DD2F3C39B03D25D150FA4D4D4DA139BF`; `b01i-summary.json` (stage status, counts-at-failure, hashes); raw `pytest.stdout/stderr.txt` + `pytest.exit.txt` (exit 1). Runtime: `C:/Users/Admin/Documents/Codex/work/s12h/20260915T131158Z/QA/B01-I/20260915T164349Z/`. Node/command contract: `tests/s12/s12-lc3-qa-r6/r6_b01i_plan.py` (`S12_REVIEW_OUT` exclusive per-run output, `S12_R6_CANDIDATE_ROOT`, `S12_R6_EXPECTED_CANDIDATE_SHA`).

Bookkeeping in this checkpoint: the finite inventory was reconciled to the delivered+verified executable node IDs (RETRY `test_m01..m19_*`, VAL `test_v01..v15_*`, producer `test_B01_A..H` matrix) with the original freeze names preserved in `R6_INVENTORY.md` under "Reconciliation — delivered node IDs"; no case meaning, outcome, count or retained gate (R04/R07/R08) was weakened.

---

# R7 corrections appendix — reviewer F05 + dispositions (2026-09-16)

Acknowledged and corrected (reviewer `s12-hermes-r6-review-20260916`, verdict CHANGES_REQUESTED / NOT_APPROVED / NOT_CLOSED, candidate `35f6cb2`):

1. F05: the submitted matrix row C02 claimed the public chain exercised S12 preflight. In this lane's own evidence the B01-I chain stops at `s10_full_apply_submit` (HTTP 422 shots-overlap); S12 preflight is **NOT_REACHED / NOT_REEXECUTED** — there is no `s12_preflight` stage in `b01i-stages.jsonl`, and the harness calls preflight only after a successful S10 (chain module lines 783–797). Planning a stage was never execution.
2. “Missing producer” and “B01 remains BLOCKED_DEPENDENCY” are obsolete: the public StructuralLock producer exists and is mounted (reviewer P07 disposition `PRODUCER_PRESENT_WITH_OPEN_F03`); the open producer item is F03 (invented timing defaults) owned by `S09-LOCK-PRODUCER-B01`.
3. “Single residual / only S10 overlap” is obsolete: the open families are F01 (lease serialization), F02 (identity/JSON-encoding), F03 (invented timing), F04 (S09-executable vs S10 planning: co-occurring segments, points-only geometry, same-role disjoint ranges, `_stitch_verified_chunks` dedup) and F05 (evidence claim). F04 is now the bounded `S12-PUBLIC-AUTHORITY-BRIDGE` task.
4. Honest labels retained unchanged: fresh/inherited/not-run; setup failures and inherited broad failures stay as recorded; deterministic-extraction / synthetic-media labels stay; human playback NOT_REVIEWED; browser UI NOT_RUN (no `frontend/node_modules`); no product/UI/video/audio pass is claimed.

R7 prep executed this turn (evidence in `.../s12-r7-two-managers/20260916T0351Z/B/QA/`): Q01 corrections above; Q02 T03A migration compatibility corrected with target-vs-head separation and both edges — full module 9 passed (was 4 failed / 2 passed); Q03 R5 audit env configured with `S12_R5_CANDIDATE_ROOT=C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration`, `S12_R5_EXPECTED_CANDIDATE_SHA=35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86` — full R5 module 3 passed (was env-assert failure); R7 freeze for writers recorded in `R6_INVENTORY.md` §“R7 additions”. B01-I remains blocked at F04; no sprint closure is claimed.

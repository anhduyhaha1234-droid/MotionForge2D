# MATRIX — MF-V1-GOLDEN round 3 (continuation 02, cutout-crop fix)

Task **MF-V1-GOLDEN** · session `20260917_184835_1e70db` (continuation-02 pin) ·
branch `codex/mf-reskin-v1-golden` · base `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
· entrance HEAD `ee7aab4` (round-2 tip, re-asserted and un-touched as a base)

Machine-readable inputs: `GOLDEN_FIXTURE.json` (frozen), `SOURCE_PROBE.json`,
`HASH_TABLE.json`. Full argv/cwd/exit/duration for every command:
`ledger/commands.jsonl`; raw stdout/stderr per command: `ledger/raw/`. Pre-image
and after-image hashes for this round: `ledger/round3_preimage.json`,
`ledger/round3_tool_patch.json`, `ledger/round3_preserve.json`,
`ledger/round3_after.json`.

## A. Acceptance gate matrix (G-A1 … G-A12)

| Gate | Criterion | Status round 3 | Exact evidence (file · command) |
|---|---|---|---|
| G-A1 | HEAD == base SHA, tree clean before first write | **PASS** | `guards/guard_baseline.json`: HEAD `ee7aab4d0d1d08a101fea5d0a8c1d2e61087008d`, branch `codex/mf-reskin-v1-golden`, `porcelain_line_count 0`, `tracked_file_count 2017`, roots runtime 370 / EV 338 / in-repo 180 · `write_set_guard.py baseline` (run 19:31, **before** the first round-3 write) |
| G-A2 | Reference film re-probed: SHA, duration, rational rate, decoded frames, audio | **PASS (round 1, carried, not re-opened)** | `SOURCE_PROBE.json` (`d9d30533…`, byte-identical this round), `source_probe/ref_container.json`, `ref_count_frames.json` |
| G-A3 | Window set = book + 4–6 segments, 20–30 s, classes, ≥1 holdout | **PASS (frozen, carried)** | `GOLDEN_FIXTURE.json.windows` (7 windows, 28.0 s, `W07_HOLDOUT`), `window_set_summary` — fixture hash unchanged this round |
| G-A4 | Every window carries exact frame IDs + PTS, traceable to a command | **PASS (carried)** | `GOLDEN_FIXTURE.json.windows[*].pts_start/pts_end_exclusive/anchors`; re-proved this round by the keyframe/role regeneration reading the same frame ids |
| G-A5 | Role inventory covers people/props/background/foreground; unknown marked | **PASS (carried)** | `GOLDEN_FIXTURE.json.role_inventory` (88 roles / 7 windows), `exceptions` in `annotation_<TAG>.json` (byte-identical) |
| G-A6 | interaction group (man + two hands + book) as one constraint group | **PASS (carried)** | `GOLDEN_FIXTURE.json.interaction_group` `G_BOOK_MAN_HANDS` |
| G-A7 | visible/invisible/unknown separation present, non-overlapping | **PASS (carried)** | `annotation_<TAG>.json` per-anchor `mask_index_legend` + state counts — all 7 annotations byte-identical this round |
| G-A8 | every required role has a reference; artwork exists **or** exact unmet dependency | **PASS as outcome (b)** (unchanged; artwork is a separate authorised step) | 88 role references + `KEYFRAME_SPEC.md` (`4ed5b7bf…`, byte-identical) + `image_engine_probe.json` (`any_engine_reachable false`) · `make_references.py`, `probe_image_engine.py` |
| G-A9 | provenance recorded for every generated/imported asset | **PASS, extended this round** | per-role `reference_sha256`, `source_frame_id`, `source_pts`, `mask_index` (**new**), `role_index_candidates` (**new**), `crop_basis`/`crop_bbox_xywh`/`crop_origin_xy`/`crop_size_wh` (**new**), `annotation_declared_bbox_xywh` (alias of `bbox_xywh`), `derived_from_mask_artifact`, `provenance.source_film_sha256`; per-file rows in `COPY_MANIFEST.json` + `HASH_TABLE.json` · `make_references.py`, `publish_evidence.py` |
| G-A10 | fixture frozen before any candidate; freeze hash recorded | **PASS, re-asserted** | `freeze_hash_sha256 2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684` **re-derived this round from the file** by `verify_round3.py` (canonical JSON minus `freeze`) and equal to the pin; fixture file sha `7e1627e4…cd0dab` also equal |
| G-A11 | no file written outside the allowlist; guard VERIFIED | **PASS** | `guards/guard_baseline.json` (pre-write, HEAD `ee7aab4`, porcelain 0) + `guards/guard_verify.json` + `guards/guard_final_classification.json` → round-3 stage-aware classifier: **precommit `VERIFIED_WITH_EXPECTED_REGENERATION_PRECOMMIT` 12/12** and **postcommit `VERIFIED_WITH_EXPECTED_REGENERATION_AND_COMMIT` 12/12** (the raw guard verdict is `DRIFT` only because `write_set_guard.py` treats any HEAD movement / tracked-file change as a problem, and both are packet-mandated); every changed path inside the allowlist, `removed_count 0`, no destructive shrink; frozen-byte re-assertion 14/14 in `ledger/round3_after.json` · `write_set_guard.py`, `classify_guard_result_r3.py` |
| G-A12 | report states real pass *and* fail, no fabricated numbers | **PASS** | `REPORT.md` §6 lists the carried gaps, the still-wrong annotation bbox (0.433474 %), the 10/88 ambiguity, the 6/88 overshoot bboxes and the COPY_MANIFEST size discrepancy; `MATRIX.md` §E lists every round-3 command row, including the duplicated pre-image run |

## B. Window matrix (frozen fixture — unchanged this round)

| Window | Tag | Film frames | PTS start→end | Anchors (cadence 15) | Duration | Classes | Holdout | Roles | Keyframes | Role cutouts |
|---|---|---|---|---|---|---|---|---|---|---|
| W01_BOOK | BOOK | 1650–1769 | 844800→906240 | 1650…1755 | 4.0 s | prop_interaction, contact, hold | no | 8 | 8 | 8 |
| W02_CUT | CUT_660 | 660–779 | 337920→399360 | 660…765 | 4.0 s | hard_cut | no | 20 | 8 | 20 |
| W03_WALK | WALK_7927 | 7927–8046 | 4058624→4120064 | 7927…8032 | 4.0 s | walking | no | 5 | 8 | 5 |
| W04_TURN | TURN_795 | 795–914 | 407040→468480 | 795…900 | 4.0 s | turn_or_shape_change | no | 6 | 8 | 6 |
| W05_CAMERA | CAM_4212 | 4212–4331 | 2156544→2217984 | 4212…4317 | 4.0 s | camera_motion | no | 25 | 8 | 25 |
| W06_OVERLAP | OCC_14768 | 14768–14887 | 7561216→7622656 | 14768…14873 | 4.0 s | overlap_or_occlusion | no | 11 | 8 | 11 |
| W07_HOLDOUT | HOLDOUT_16231 | 16231–16350 | 8310272→8371712 | 16231…16336 | 4.0 s | unlabelled_holdout | **yes** | 13 | 8 | 13 |
| **Total** | | | | **56 anchors** | **28.0 s** | 9 classes | 1 holdout | **88** | **56** | **88** |

## C. Media-object matrix (unchanged, hashes re-asserted by `verify_round3.py`)

| Object | Path | Bytes | SHA-256 |
|---|---|---|---|
| REFERENCE_FILM (A) | `…\MotionForge2D\projects\2dc14177a212\Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4` | 36,971,916 | `5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2` |
| REFERENCE_FILM (B) | `…\projects\4503582811e8\…mp4` | 36,971,916 | `5a175454…399fa2` (identical to A) |
| DEMO_30S | `…\outputs\demo-luna-c7-review-20260910\fixture\source.mp4` | 877,221 | `22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a` |
| CLIP_4S_PROTOTYPE_A | `…\outputs\hand-prototype\20260913T102850Z\prototype-a\PROTOTYPE_A_diagnostic_4s_source-audio.mp4` | 133,761 | `dee47afcb5e12aff48076df6b59d84f527af4a0d9be9403550ae99a9e71755fb` |
| SAM 2.1 hiera-large checkpoint | `…\MotionForge2D\models_checkpoints\sam2.1_hiera_large.pt` | 898,083,611 | `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` |

Frozen set re-asserted this round (all byte-identical, `ledger/round3_after.json`):

| Artifact | sha256 |
|---|---|
| `GOLDEN_FIXTURE.json` | `7e1627e4c8c2421e77758b48f0c003c23d0b8b2f50fc73bc2118bc6b06cd0dab` |
| freeze hash (re-derived from the file) | `2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684` |
| `KEYFRAME_SPEC.md` | `4ed5b7bfec887c121b7a361c0d819302b8f991cd12efd4627ce483beafc940f4` |
| `SOURCE_PROBE.json` | `d9d3053323dd4dbc15fe9dd9b94d5f83b58f5fa9ba3b64c865156d085470420b` |
| `image_engine_probe.json` | `6dc834143fc3322ed94f6754c97853e2e87515ba9f4f7ef259b4174cd18e5b62` |
| `vision_route_probe.json` | `82cdbca8515f7ee32bc5c9dbd59d4f9a086c0361931480ec25d5033f8f48604f` |
| protected annotation tree, 126 files | aggregate `fdd4345f6d62660ae18e1c774d5e6caaa983898c0c1bda5c2137c4f93852844b` (pre == post) |

## D. Round-3 measurement matrix (before → after)

| Measurement | Round 2 | Round 3 | Artifact |
|---|---|---|---|
| Role cutouts delivered | 88 | 88 (regenerated) | `references_<TAG>.json` → `role_references[]` |
| Crop verdict | 88 `CLIPPED` | **88 `EXACT`** | `cutout_bounds_audit.json.verdict_histogram` |
| Mask px outside the crop applied | 9,058 / 2,089,631 | **0 / 2,089,631 (0.0 %)** | `cutout_bounds_audit.json.totals.mask_px_outside_crop` |
| Mask px outside the declared bbox (round-2 metric, kept) | 9,058 = 0.433474 % | **9,058 = 0.433474 %** | `cutout_bounds_audit.json.totals.mask_px_outside_declared_crop` |
| Worst case | `CAM_4212 role_25 f4317`, 990 px clipped | same role: declared `[0,0,639,359]` → tight/delivered `[0,0,640,360]`, 211,809 px, **0** outside | `cutout_bounds_audit.json.per_role` |
| Alpha integrity | 88/88 count-true | **88/88 element-wise true** | `alpha_elementwise_equals_mask` |
| References recording `mask_index` | 0/88 | **88/88** | `references_<TAG>.json.role_references[].mask_index` |
| Manifest index == max-area inference | n/a (inference only) | **88/88** | `cutout_bounds_audit.json.index_provenance` |
| Role→mask-index ambiguity at anchor | 10/88 | **10/88 (unchanged, still listed with candidates)** | `cutout_bounds_audit.json.per_role[].candidate_indices` |
| Roles whose declared bbox is 1 px short on **both** axes | not measured | **82/88** | derived from `declared_bbox_xywh` vs `mask_tight_bbox_xywh` |
| Roles whose declared bbox **overshoots** one axis | not measured | **6/88** (2–180 px) | same |
| Independent second derivation | n/a | **88/88 exact, 0 px outside, equal totals** | `ledger/round3_after.json.independent_cutout_check` |
| Frozen-byte re-assertion | n/a | **14/14 checks true, `failures []`** | `ledger/round3_after.json.checks` |
| Patched tools | 2 tools touched, no preimage record this granular | `make_references.py` `016f7acd…`→`9588e8d9…` (+54/−3); `measure_cutout_bounds.py` `665cdb34…`→`4c7a6943…` (+100/−31); `publish_evidence.py` `5399a175…`→`c5e904e9…` (+8/−1) for the measured `ledger/raw/` subdirectory crash | `ledger/round3_tool_patch.json` |
| Engine reachability / diffusion weights / vision | `false` / 0 / no vision | **not re-probed** (out of scope this round; round-2 evidence carried) | `image_engine_probe.json`, `vision_route_probe.json` |

## E. Command ledger — the round-3 rows

| # | step | exit | duration (s) | raw output |
|---|---|---|---|---|
| 87 | round3_preimage (1st invocation) | 0 | 0.120 | ledger/raw/20260917T123241_round3_preimage.txt |
| 88 | round3_preimage (2nd, authoritative) | 0 | 0.119 | ledger/raw/20260917T123412_round3_preimage.txt |
| 89 | **round3_preserve** | 0 | 0.106 | ledger/raw/20260917T134218_round3_preserve.txt |
| 90 | **round3_tool_patch** | 0 | 0.041 | ledger/raw/20260917T134234_round3_tool_patch.txt |
| 91 | **make_references_r3** | 0 | 0.942 | ledger/raw/20260917T134255_make_references_r3.txt |
| 92 | **measure_cutout_bounds_r3** | 0 | 0.285 | ledger/raw/20260917T134314_measure_cutout_bounds_r3.txt |
| 93 | **verify_round3** | 0 | 0.317 | ledger/raw/20260917T134424_verify_round3.txt |
| 94 | **publish_repo_r3** | 0 | 0.535 | ledger/raw/20260917T135330_publish_repo_r3.txt |
| 95 | guard_verify_precommit_r3 | **1** | 0.645 | ledger/raw/20260917T135359_guard_verify_precommit_r3.txt (verdict DRIFT = expected regeneration, see §A G-A11) |
| 96 | classify_guard_result_precommit_r3 (v1) | **1** | 0.050 | ledger/raw/20260917T135410_classify_guard_result_precommit_r3.txt (checker bug: demanded a HEAD advance pre-commit; kept) |
| 97 | classify_guard_result_precommit_r3_v2 | 0 | 0.055 | ledger/raw/20260917T135453_classify_guard_result_precommit_r3_v2.txt |
| 98 | publish_repo_guards_r3 | 0 | 0.202 | ledger/raw/20260917T135519_publish_repo_guards_r3.txt |
| — | **commit #1 `9f1b54c`** (105 files, all inside the write set) | — | — | `git show --stat 9f1b54c` |
| 99 | guard_verify_postcommit_r3 | **1** | 0.559 | ledger/raw/20260917T135610_guard_verify_postcommit_r3.txt (single problem: HEAD moved) |
| 100 | classify_guard_result_postcommit_r3 | 0 | 0.058 | ledger/raw/20260917T135611_classify_guard_result_postcommit_r3.txt |
| 101 | publish_repo_guards_tip_r3 | 0 | 0.210 | ledger/raw/20260917T135623_publish_repo_guards_tip_r3.txt |
| — | **commit #2 `4768be0`** (guard verdict + tip-timed refresh) | — | — | `git show --stat 4768be0` |
| 102 | publish_ev_r3 | **1** | 0.680 | ledger/raw/20260917T135757_publish_ev_r3.txt (`PermissionError` on `ledger\raw\round3_preimage`, kept) |
| 103 | round3_tool_patch_v2 | 0 | 0.045 | ledger/raw/20260917T135854_round3_tool_patch_v2.txt (adds the `publish_evidence.py` bounded patch) |
| 104 | round3_tool_patch_v3 | 0 | 0.039 | ledger/raw/20260917T135943_round3_tool_patch_v3.txt (idempotent: correct an already-patched label) |
| 105 | publish_ev_r3_v2 | 0 | 0.388 | ledger/raw/20260917T135943_publish_ev_r3_v2.txt (356 files, 0 problems) |
| 106 | round3_tool_patch_v4 | 0 | 0.042 | ledger/raw/20260917T140028_round3_tool_patch_v4.txt (idempotent: no bytes move) |
| 107 | hash_table_r3 | 0 | 1.178 | ledger/raw/20260917T140028_hash_table_r3.txt (5 inputs, 951 output rows) |

Rows 87–88 are the pre-image freeze (the duplicated invocation is disclosed in
`REPORT.md` §1; both raw outputs kept, the second is authoritative). Rows 89–107 are
this round's work — including its two **non-zero exits**, which are kept as raw
evidence rather than dropped: row 96 (round-3 classifier v1 was wrong on the
pre-commit state and was corrected, both runs kept) and row 102 (`publish --target
ev` hit a real `PermissionError` caused by this round's snapshot subdirectory; fixed
by a bounded patch to `publish_evidence.py`, re-run as row 105). Rows 1–86 are
rounds 1–2 and live in the round-2 table of the archived `report/round2/MATRIX.md`.
`make_references_r3` takes **0.942 s** versus round 2's 22.442 s because all 56
keyframes already existed and were therefore **not re-decoded** (the fixture was not
rebuilt) — proved afterwards by `verify_round3.py`: all 56 keyframe PNGs
byte-identical.

Every row in `ledger/commands.jsonl` carries argv, cwd, UTC+local start/end, exit
code, duration, raw output path and raw byte size. In the round-3 range 87–107 the
only non-zero exits are rows 95, 96, 99 and 102 — all four are named above and their
raw output is kept; every other row is exit 0.

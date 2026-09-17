# MATRIX — MF-V1-GOLDEN round 2

Task **MF-V1-GOLDEN** · session `20260917_180945_1e9357` · branch
`codex/mf-reskin-v1-golden` · base `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
· artifacts commit **674fc0c** (docs + SHA record in the following commit on the
same branch)

Machine-readable inputs: `GOLDEN_FIXTURE.json` (frozen),
`SOURCE_PROBE.json`, `HASH_TABLE.json`. Full argv/cwd/exit/duration for every
command: `ledger/commands.jsonl`; raw stdout/stderr per command: `ledger/raw/`.

## A. Acceptance gate matrix (G-A1 … G-A12)

| Gate | Criterion | Status | Exact evidence (file · command) |
|---|---|---|---|
| G-A1 | HEAD == base SHA, tree clean before first write | **PASS** | `ledger/guard_baseline.json` (`head 2594de0…`, `porcelain_line_count 0`, `tracked_file_count 1837`) · `write_set_guard.py baseline` |
| G-A2 | Reference film re-probed: SHA, duration, rational rate, decoded frames, audio | **PASS (round 1, carried)** | `SOURCE_PROBE.json`, `ref_container.json`, `ref_count_frames.json` · `ffprobe`/`ffmpeg -count_frames` steps `probe_ref_container`, `probe_ref_count_frames` |
| G-A3 | Window set = book + 4–6 segments, 20–30 s, classes, ≥1 holdout | **PASS (round 1, carried)** | `GOLDEN_FIXTURE.json.windows` (7 windows, 28.0 s, `W07_HOLDOUT`), `window_set_summary` · `build_fixture` |
| G-A4 | Every window carries exact frame IDs + PTS, traceable to a command | **PASS (round 1, carried)** | `GOLDEN_FIXTURE.json.windows[*].pts_start/pts_end_exclusive/anchors`; `t = f/30`, `pts = f*512` · `series_*`, `verify_demo_offset` |
| G-A5 | Role inventory covers people/props/background/foreground; unknown marked | **PASS (round 1, carried)** | `GOLDEN_FIXTURE.json.role_inventory` (structural kind histogram 88 roles across 7 windows), `exceptions` in `annotation_<TAG>.json` · `annotate_window`, `measure_role_relations` |
| G-A6 | interaction group (man + two hands + book) as one constraint group | **PASS (round 1, carried)** | `GOLDEN_FIXTURE.json.interaction_group` `G_BOOK_MAN_HANDS` (contact evidence per anchor) |
| G-A7 | visible/invisible/unknown separation present, non-overlapping | **PASS (round 1, carried)** | `annotation_<TAG>.json` per-anchor `mask_index_legend` + state counts in fixture `windows[*].roles[*].state_counts` |
| G-A8 | every required role has a reference; artwork exists **or** exact unmet dependency | **PASS as outcome (b)** | `references/references_<TAG>.json` (88 role references) + `KEYFRAME_SPEC.md` (artwork spec) + `image_engine_probe.json` (`any_engine_reachable false`, 0 weights, missing `diffusers`/`transformers`) + `probe/vision_route_probe.json` (no vision) · `make_references.py`, `probe_image_engine.py` |
| G-A9 | provenance recorded for every generated/imported asset | **PASS** | per-keyframe `keyframe_sha256` + `mask_index_sha256`; per-role `reference_sha256`, `source_frame_id`, `source_pts`, `bbox_xywh`, `derived_from_mask_artifact`, `provenance.source_film_sha256`; per-published-file row in `COPY_MANIFEST.json` and `HASH_TABLE.json` · `make_references.py`, `publish_evidence.py` |
| G-A10 | fixture frozen before any candidate; freeze hash recorded | **PASS (round 1, carried)** | `GOLDEN_FIXTURE.json.freeze.freeze_hash_sha256 2c558ce1…fa684`, `frozen_at_utc 2026-09-17T11:43:36Z`, `frozen_before "any candidate render"` · `build_fixture` |
| G-A11 | no file written outside the allowlist; guard VERIFIED | **PASS** | `ledger/guard_baseline.json` → `ledger/guard_verify.json`: `verdict VERIFIED`, `problems []`, `added 165`, `modified 1` (= `ledger/commands.jsonl`, inside allowlist), `removed 0`, every changed path under the three allowlist roots · `write_set_guard.py baseline` + `verify` |
| G-A12 | report states real pass *and* fail, no fabricated numbers | **PASS** | `REPORT.md` §3 lists the 6 measured defects/caveats; §6 lists 11 gaps; `MATRIX.md` §B ledger table excludes nothing |

## B. Window matrix (frozen fixture)

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

## C. Media-object matrix (re-hashed this round)

| Object | Path | Bytes | SHA-256 |
|---|---|---|---|
| REFERENCE_FILM (A) | `…\MotionForge2D\projects\2dc14177a212\Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4` | 36,971,916 | `5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2` |
| REFERENCE_FILM (B) | `…\projects\4503582811e8\…mp4` | 36,971,916 | `5a175454…399fa2` (identical to A) |
| DEMO_30S | `…\outputs\demo-luna-c7-review-20260910\fixture\source.mp4` | 877,221 | `22e7577d78f38355ffe133b3ea292e0b9c0bfa628bbcf24d37b6e9a64ca9ce1a` |
| CLIP_4S_PROTOTYPE_A | `…\outputs\hand-prototype\20260913T102850Z\prototype-a\PROTOTYPE_A_diagnostic_4s_source-audio.mp4` | 133,761 | `dee47afcb5e12aff48076df6b59d84f527af4a0d9be9403550ae99a9e71755fb` |
| SAM 2.1 hiera-large checkpoint | `…\MotionForge2D\models_checkpoints\sam2.1_hiera_large.pt` | 898,083,611 | `2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318` |

Freeze: `freeze_hash_sha256 2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684`
· fixture file hash `7e1627e4c8c2421e77758b48f0c003c23d0b8b2f50fc73bc2118bc6b06cd0dab`
· `SOURCE_PROBE.json` hash `d9d3053323dd4dbc15fe9dd9b94d5f83b58f5fa9ba3b64c865156d085470420b`.

## D. Round-2 measurement matrix

| Measurement | Value | Artifact |
|---|---|---|
| Aligned keyframes produced | 56 (7 × 8 anchors), exact frame-number decode | `references/references_<TAG>.json` → `keyframes[]` |
| Role reference cutouts produced | 88 (equals frozen per-window role counts) | `references_<TAG>.json` → `role_references[]` |
| Role-cutout crop verdict | 88 CLIPPED / 0 EXACT / 0 OVERSIZED / 0 ANOMALY | `cutout_bounds_audit.json` |
| Mask pixels outside declared crop | 9,058 of 2,089,631 = **0.433474 %** | `cutout_bounds_audit.json.totals` |
| Worst single cutout clip | 990 px of 211,809 (0.467 %) `CAM_4212 role_25 f4317` | `cutout_bounds_audit.json.per_role` |
| Alpha integrity | 88 / 88 true (`alpha_nonzero == mask px inside crop`) | `cutout_bounds_audit.json.per_role` |
| Role→mask-index ambiguity at anchor | 10 / 88 roles | `cutout_bounds_audit.json.role_index_ambiguous_count` |
| Engine reachability | `false`; ports 8188/8201/7860/8888/3000 refused | `image_engine_probe.json` |
| Diffusion weights in this runtime | 0 | `image_engine_probe.json` |
| Diffusion libs in this interpreter | `diffusers` MISSING, `transformers` MISSING (torch 2.11.0+cu128, PIL 12.2.0, cv2 5.0.0, sam2 present) | `image_engine_probe.json` |
| Sibling ComfyUI store (observed read-only, not used) | 1 file, 7,105,348,188 bytes | `image_engine_probe.json.sibling_comfy_model_store_observation` |
| Vision on active model route | unavailable — `[image omitted: model has no vision support]` | `vision_route_probe.json` |
| Published files byte-verified | in-repo 175 + EV (see `COPY_MANIFEST.json` in each root) | `COPY_MANIFEST.json` |
| Guard | baseline + verify → **VERIFIED**, problems `[]` | `guards/guard_baseline.json`, `guards/guard_verify.json` |

## E. Command ledger — every evidence-producing command

| # | step | exit | duration (s) | raw output |
|---|---|---|---|---|
| 1 | probe_ref_container | 0 | 0.025 | ledger/raw/20260917T111637_probe_ref_container.txt |
| 2 | probe_refB_container | 0 | 0.025 | ledger/raw/20260917T111637_probe_refB_container.txt |
| 3 | probe_demo_container | 0 | 0.022 | ledger/raw/20260917T111637_probe_demo_container.txt |
| 4 | probe_clip4_container | 0 | 0.024 | ledger/raw/20260917T111637_probe_clip4_container.txt |
| 5 | detect_scene_changes_raw | 0 | 2.076 | ledger/raw/20260917T111700_detect_scene_changes_raw.txt |
| 6 | probe_ref_count_frames | 0 | 4.735 | ledger/raw/20260917T111659_probe_ref_count_frames.txt |
| 7 | verify_book_window_stills | 0 | 0.165 | ledger/raw/20260917T112647_verify_book_window_stills.txt |
| 8 | locate_still_frame450 | 0 | 18.044 | ledger/raw/20260917T112707_locate_still_frame450.txt |
| 9 | locate_prototypeA450_in_demo30s | 0 | 0.554 | ledger/raw/20260917T112738_locate_prototypeA450_in_demo30s.txt |
| 10 | locate_demo_f0_in_ref | 0 | 18.924 | ledger/raw/20260917T112739_locate_demo_f0_in_ref.txt |
| 11 | verify_demo_offset | 0 | 0.899 | ledger/raw/20260917T112917_verify_demo_offset.txt |
| 12 | sam2_probe_frame1650 | **1** | 5.805 | ledger/raw/20260917T112919_sam2_probe_frame1650.txt (first attempt failed; see 13) |
| 13 | verify_demo_offset | 0 | 1.446 | ledger/raw/20260917T113034_verify_demo_offset.txt |
| 14 | verify_demo_offset | 0 | 1.495 | ledger/raw/20260917T113057_verify_demo_offset.txt |
| 15 | verify_demo_offset | 0 | 1.854 | ledger/raw/20260917T113123_verify_demo_offset.txt |
| 16 | verify_demo_offset | 0 | 2.005 | ledger/raw/20260917T113145_verify_demo_offset.txt |
| 17 | sam2_probe_frame1650 | 0 | 7.252 | ledger/raw/20260917T113233_sam2_probe_frame1650.txt |
| 18 | series_BOOKWIN_film1650_1770 | 0 | 0.306 | ledger/raw/20260917T113418_series_BOOKWIN_film1650_1770.txt |
| 19 | series_WHOLEFILM | 0 | 34.100 | ledger/raw/20260917T113448_series_WHOLEFILM.txt |
| 20 | analyze_shot_metrics | 0 | 0.132 | ledger/raw/20260917T113619_analyze_shot_metrics.txt |
| 21–47 | classify_candidates ×27 | 0 | 0.156–0.424 | ledger/raw/20260917T1137*_classify_candidates.txt … 20260917T113853_* |
| 48 | annotate_BOOK | 0 | 11.311 | ledger/raw/20260917T113956_annotate_BOOK.txt |
| 49–54 | annotate_window ×6 | 0 | 9.281–11.203 | ledger/raw/20260917T1140*_annotate_window.txt … 20260917T114152_* |
| 55 | measure_role_relations | 0 | 0.846 | ledger/raw/20260917T114240_measure_role_relations.txt |
| 56 | measure_role_relations | 0 | 0.617 | ledger/raw/20260917T114336_measure_role_relations.txt |
| 57 | build_fixture | 0 | 0.055 | ledger/raw/20260917T114336_build_fixture.txt |
| 58 | **guard_baseline_r2** | 0 | 0.410 | ledger/raw/20260917T115040_guard_baseline_r2.txt |
| 59 | **make_references_r2** | 0 | 22.442 | ledger/raw/20260917T115133_make_references_r2.txt |
| 60 | **measure_cutout_bounds_r2** | 0 | 0.229 | ledger/raw/20260917T115321_measure_cutout_bounds_r2.txt |
| 61 | **measure_cutout_bounds_r2_v2** | 0 | 0.236 | ledger/raw/20260917T115435_measure_cutout_bounds_r2_v2.txt |
| 62 | **probe_image_engine_r2** | 0 | 22.179 | ledger/raw/20260917T115544_probe_image_engine_r2.txt |
| 63 | **guard_verify_precommit_r2** | 0 | 0.310 | ledger/raw/20260917T115935_guard_verify_precommit_r2.txt |
| 64 | **publish_repo_r2** | 0 | 0.793 | ledger/raw/20260917T120016_publish_repo_r2.txt |

Rows 58–64 are round 2 (this continuation). The publish/guard/hash steps that
run *after* this file's own commit (`publish_repo_docs_r2`,
`guard_verify_final_r2`, `publish_ev_r2`, `hash_table_r2`) are not enumerated here
because this file is one of their inputs; their exact argv, exit code, duration
and raw output are in `ledger/commands.jsonl` and `ledger/raw/`, and their
verdicts are `guards/guard_verify.json` and `COPY_MANIFEST.json`.

Every row in `ledger/commands.jsonl` carries the full argv, cwd, UTC+local
start/end, exit code, duration, raw output path and raw byte size; rows above are
the same records abbreviated. The only non-zero exit in the whole ledger is entry
12 (a first SAM 2.1 probe attempt, superseded by entry 17, which is the inference
quoted in the fixture).

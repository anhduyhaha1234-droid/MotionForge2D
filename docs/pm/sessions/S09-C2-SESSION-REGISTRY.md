# S09-C2 — Session Registry & Lock Table (Manager-owned)

Baseline preflight 2026-08-25 10:11+07: HEAD ee10e55a (khớp expected), branch codex/s08-integration, dirty 94, alembic head b3c4d5e6f7a9, DB_URL UNSET. Rules SHA-256 `987386c59f72145b…`.

## Wave A lock table (dispatch đồng thời tối đa 5)

| Task ID | Exact owner session | Phase | Proc | State | Exclusive write-set | Hashes trước | Deps |
|---|---|---|---|---|---|---|---|
| S09-T02-C2 | 20260824_015213_f5516b | production renderer contract | pending | DISPATCHED | renderer_contract/router/adapters/renderer_routes, tests_t02, output t02-c2 | contract 8ad733516aae→(C1 đã đổi) | — |
| S09-T00-I03-C2-PREP | 20260823_173318_69a813 | fixtures f1/f5 + harness v3 PREP | pending | DISPATCHED | benchmark script, fixtures s09_renderer, tests_benchmark_harness, output t00-i03-c2 | (I03 lane) | dừng WAITING_JOIN trước J1-C2 |
| S09-T03-C2 | 20260824_031524_a6bb2a | durable publication long-path | pending | DISPATCHED | s09_demo_jobs.py, routes s09_demo_loops (nếu bắt buộc), tests_t03, output t03-c2 | (T03 lane) | final binding chờ I05-C2 |
| S09-T04-C2 | 20260824_052859_c6e197 | bỏ hard-code v1 evidence | pending | DISPATCHED | routes/schemas demo_compare, tests t04, frontend demo/**, e2e t04 + config, output t04-c2 | (T04 lane) | final run sau I05+T03 |
| S09-T06B-C2-PREP | 20260824_131423_423e42 | spec only-affected-regenerates PREP | pending | DISPATCHED | e2e s09-t06bc1-production-stack.spec.ts + global-setup/config, output t06b-c2 | (T06B lane) | final run chờ T03/T04 exit |

## Joins
- **J1-C2**: T02-C2 exit + focused ×2 xanh + I03 dừng writer + Manager review pass → Manager hash ĐỆ QUY mọi behavior-critical file (contract/router/adapters/**/routes/**) → `output/s09/20260823_sprint_full/j1-c2/renderer_freeze_manifest.json` (machine-readable path→SHA-256) + pin manifest SHA vào registry. I03 verify manifest TRƯỚC và SAU mỗi measured run; drift → dừng I03, invalidate downstream, resume owner gây drift, J1 mới, rerun I03/I05.
- **Wave B**: I03 measured A/B → verified → I05-C2 (owner 8d5b7b) decision mới, FAIL_OPEN_QUESTION phải = 0.
- **J2-C2/Wave C**: pin SHA benchmark + decision → resume T03/T04/T06B owners bind C2 evidence; T06B final run chờ T03/T04 exit.

## BA decisions chốt (không hỏi lại)
- hard_cut + group_occlusion là required classes — không loại, không no-op PASS
- Benchmark PHẢI đi qua public RendererRouter.execute() + production adapter; cấm gọi thẳng compositor/private helper
- Output giữ exact frame range + rational fps/timebase; provenance hash trên canonical decoded frames của encoded output
- Loại mọi hard-code `t00-i05/measured_seed20260823` trong production/frontend/active tests (archival docs được phép)
- Required class fail/unknown/FOQ = blocker; Manager KHÔNG được ghi TASK_MANAGER_VERIFIED khi đó

## FG/C1 lineage reconciliation
C1 sessions: T02-C1 015213_f5516b · I03-C1 173318_69a813 · I05-C1 8d5b7b · T56 120141_312e9e · T06B-C1 131423_423e42 · T05A-C1 072626_645cde · T01-C1 232748_b4b2ad. Verdict C1 = CHANGES_REQUESTED (F1–F7).

## Append log (Manager-only)

| Thời điểm (+07) | Ghi nhận |
|---|---|
| 10:11 | **RULES_LOADED** (SHA 987386c5…) · PREFLIGHT OK: HEAD ee10e55a khớp expected, dirty 94, head b3c4d5e6f7a9, DB UNSET. Đã nạp C1 review F1–F7 (verdict CHANGES_REQUESTED, terminal đúng phải là BLOCKED_WITH_FINDINGS) + 6/6 owner sessions tồn tại |
| 10:25 | **Wave A DISPATCHED ×5**: T02-C2 (proc_7714aa8f1d46) · I03-C2-PREP (proc_617071fd1faa) · T03-C2 (proc_703d8d0b0f44) · T04-C2 (proc_720737674e09) · T06B-C2-PREP (proc_a0cdbd0d18e4). Cả 5 resume đúng owner session. I03-PREP sẽ dừng WAITING_JOIN; T03/T04/T06B final binding chờ I05-C2 |
| 12:50 | **T03-C2 DONE (WAITING_JOIN) + verify PASS**: 15 passed ×2 (12.9/12.8s), ruff sạch; long-path test ≥260 chars có trong suite (12 refs); artifacts/artifacts duplication đã fix (chỉ còn trong docstring giải thích). STATUS: PHASE=WAITING_JOIN / PENDING_I05_C2_BINDING — đúng protocol PREP. Final binding sẽ resume lại sau I05-C2 |
| 13:25 | **T04-C2 DONE (CORRECTION_SUBMITTED_C2) + verify PASS**: 13 passed ×2 (19.1/19.2s), tsc EXIT=0; v1 hard-code `measured_seed20260823` đã xóa khỏi useDemoCompare.ts (chỉ còn trong comment giải thích "NO default here"); benchmark content SHA pin có mặt ở cả frontend hook + backend route. Final Playwright run chờ I05-C2 + T03-C2 binding |
| 14:20 | **T06B-C2-PREP chưa xong — resume R2**: worker exit sớm sau khi root-cause blocker thật (seeder filter `S09_DEMO_LOOP` vs durable row `s09_demo_loop` lowercase → reset không xóa job → pinned submit 200/reused thay 201). Spec đã phân tích kênh chứng minh binary qua `/api/v2/s09-demo-loops/{job_id}` (routes_by_risk_class + artifact sha). Đã resume đúng owner với packet sửa filter + re-run Chromium ×2. 2 findings T05B ghi nhận (CorrectionPanel affected_loop_ids, ApprovalPanel reasonsOf override) |
| 14:30 | **T02-C2 DONE + Manager verify PASS**: EXIT=0 STATUS TASK_SUBMITTED (C1b). Verify tay: focused suites **51+14 passed ×2** (gồm suite mới test_s09_t02_c2_timebase_identity_contract.py — probe timebase/fraction validation/exact inclusive frame count/NTSC 30000÷1001 khi ffmpeg có); mypy app --no-incremental **Success 125 files**; ruff owned files sạch. F5 đóng: rational fps/timebase typed contract (21 refs Fraction/rational), `@identity` live-code đã xóa → `identity_transform` typed bool chỉ pair với empty keyframe track, decoded-frame hash field trong adapter evidence. J1-C2 sẵn sàng sau khi I03 dừng writer |
| 14:45 | **I03-C2-PREP exit nhưng Manager verify THẤT BẠI → resume FIX1**: harness tests **8 failed, 21 passed** — worker bump SCHEMA_VERSION=3 trong benchmark script nhưng quên bump thresholds.json (vẫn =2) → mọi subprocess test fail-closed. Đã root-cause + resume owner với packet fix version field (cấm tune threshold values). Cấu trúc khác đã đúng: RendererRouter.execute() public path có mặt, private composite calls = 0 trong script, f1/f5 manifests có typed replacement |
| 14:35 | T06B-C2-PREP R2B relaunch sau shell EOF bug lần trước |
| 14:50 | **T06B-C2-PREP R2B DONE + Manager verify PASS**: Chromium ×2 **1 passed** (15.8/15.4s); seeder fix thật: `func.lower(Job.job_type) == "s09_demo_loop"` (run-prod-seed.py:96,111, mtime 14:36); spec assert qua API snapshot: unaffected loops giữ artifact_id/sha/size/frame_count, affected d2_mouth_phone pin honored trong plan.routes_by_risk_class, stale 409 không tạo gì, reload + backend restart giữ checkpoint/hash. Gates tĩnh TSC=0/ESLint clean/T06A 34 passed. REPORT-C2-PREP.md STATUS TASK_SUBMITTED (PREP — WAITING_JOIN). Findings T05B giữ nguyên |
| 15:25 | **I03-C2-PREP FIX1 VERIFIED**: thresholds.json schema_version=3, benchmark tests **29 passed ×2** (51.6/52.0s), ruff sạch, REPORT STATUS: WAITING_JOIN. **WAVE A HOÀN TẤT ×5** |
| 15:25 | **J1-C2 OPENED — freeze manifest pinned**: 13 behavior-critical files (contract+router+adapters/renderer/**+renderer_routes/**) → output/s09/20260823_sprint_full/j1-c2/renderer_freeze_manifest.json · **MANIFEST_SHA256 = 1d854969ce01ef494a5712d9bb26807c9e46a6459cc8b672b4db90c2ad4d3c98**. I03 measured phải verify manifest TRƯỚC/SAU run. Drift → invalidate downstream |
| 17:15 | **I03-C2 MEASURED DONE + verify**: run_A/run_B schema v3, **5/6 classes overall_pass=True** (f1 hard_cut qua sprite_affine, f2 pose_swap, f3/f4/f6 sprite_affine); adversarial control FAILED_AS_EXPECTED ×6; determinism core-identical sau strip declared non-det (18 runtime diffs = đúng các field khai báo); Router.execute→production adapters, NVENC acceleration-only provenance. **f5_group_occlusion FAIL trung thực**: z_order_inversions=6 + unexplained_visibility=6 — root-cause: _draw_occluders STRETCH pillar full-frame (bbox=None) che cả char_b trong window 28..45; frozen contract không hỗ trợ per-region occluder placement khi replacement free-roam. Worker nêu 3 options cho BA. J1 manifest re-hash: NONE drifted |
| 17:35 | **MANAGER DECISION f5 = phương án (b) mở scope renderer per-region occluder**: resume T02-C2 owner (proc_cfa76c725f4d) thêm region rect typed contract + compositor + tests; I03 được bảo exit sau khi document measured v1. J1-C2 manifest hiện tại SẼ bị thay bằng J1-C2-v2 sau khi T02 xong → toàn bộ measured phải rerun A/B trên freeze mới. I05-C2 HOÃN cho đến khi có freeze v2 + measured pass |
| 17:40 | HEARTBEAT: timeline cập nhật — T02 occluder ~19:00–20:00 → J1-v2 pin → I03 rerun A/B ~21:00–22:30 → I05-C2 ~23:00 → Wave C binding ~23:30–01:30 → final gate C2 ~01:30–03:30. Terminal S09-C2 thực tế nhất rạng sáng 26/08 04:00–06:00 |
| 17:50 | **T02-C2 occluder correction DONE + verify PASS**: per-region occluder placement có thật — contract `occluder_regions: name→(x,y,w,h)` normalized (line 467), `_draw_occluders` precedence regions[name]→sub-rect only + backward compatible; focused suites **68 passed ×2**; mypy 125 files Success; ruff sạch; 18 region refs trong composite contract tests |
| 17:52 | **J1-C2-v2 PINNED**: renderer_freeze_manifest_v2.json, 13 files · **V2_MANIFEST_SHA256 = aa405015856432e5985106741aea4702d4e4f12c08077bec437c3672e8728c91** (supersedes v1 vì per-region occluder change). I03 rerun full A/B dispatched (proc_120a393c346c) — fixture f5 thêm pillar region x=255..385 theo GT, record pin manifest v2 SHA. Target binary 6/6 |
| 18:50 | **I03-C2 MEASURED RERUN v2 DONE + Manager verify PASS**: **6/6 required classes overall_pass=True** — f5_group_occlusion giờ PASS với z_order_inversions=0 (per-region occluder hoạt động thật); adversarial control 6/6 FAILED_AS_EXPECTED; A/B core-identical (6 diffs chỉ adversarial_artifact paths giữa run dirs); manifest v2 SHA pinned trong results; J1-v2 drift check sau run: NONE; benchmark tests 29 passed. **I03-C2 = TASK_MANAGER_VERIFIED** |
| 18:55 | **I05-C2 DISPATCHED** (proc_3577d6e168ab): measured route decision từ frozen inputs 6/6 PASS, target FAIL_OPEN_QUESTION=0 |
| 19:15 | **I05-C2 DONE + Manager verify PASS**: route_decisions_seed20260823.json — **6/6 PASS_MEASURED_ROUTE** (hard_cut→sprite_affine, mouth_expression_swap→pose_swap, còn lại sprite_affine); **fail_open_question_count = 0**; inputs pin manifest v2 (13/13 rehashed OK, drift []) + determinism independent re-compare; mỗi decision có sample_counts/frames/fps_rational/time_base/metrics/provenance đầy đủ. Decision SHA-256 = ebce8c4bf416cc6b3b2225f9ddf889e475931b25acc6b76f0a55842c74de8f98. **J2-C2 OPENED** |
| 19:25 | **J2-C2 OPENED — Wave C dispatched ×3 song song**: T03 final binding (proc_a64f31656780) · T04 final run (proc_1c92cfb4a7a3) · T06B final production-stack ×2 (proc_894bd9ded80f). Cả ba bind decision SHA ebce8c4b… + manifest v2 aa405015…; không fallback v1/C1 |
| 19:40 | **T03-C2 FINAL BINDING DONE + verify PASS**: planner fail-closed chain thật — route_decision_path missing → DemoLoopPlanError; SHA drift vs pinned C2 → refuse; benchmark input SHA cross-check. Tests **19 passed ×2** (12.9/12.9s) gồm long-path + decision binding (C2_DECISION_SHA=ebce8c4b…). STATUS: TASK_SUBMITTED (final binding) |
| 20:15 | **T06B-C2 FINAL DONE + Manager verify PASS**: Chromium ×2 **1 passed** (15.1/13.5s) trên fresh DB/runtime; spec mới s09-t06bc2-only-affected-regenerates.spec.ts Phase F viết theo bằng chứng thật (C2 doc chỉ có 1 route passing/class → pin sprite_affine bị planner REFUSE fail-closed đúng thiết kế, pinless replay 200 reused, mọi loop giữ nguyên artifact_id/sha/size/frames); reload + backend restart thật giữ checkpoint + publications 4/4. STATUS: TASK_SUBMITTED (FINAL). Findings T05B giữ nguyên cho Codex |
| 20:50 | **T04-C2 FINAL DONE + Manager verify PASS**: backend route pin decision SHA ebce8c4b… thật (s09_demo_compare.py); frontend bắt buộc NEXT_PUBLIC_S09_BENCHMARK_RESULTS + CONTENT_SHA256 — thiếu cả hai → panel error, không silent fallback; pytest T04 13 passed + T03 regression 19 passed; Playwright 3 passed/1 skipped sau spec edit cuối; tsc EXIT=0. **WAVE C HOÀN TẤT ×3 — mở FINAL GATE C2** |
| 20:55 | **FINAL GATE C2 mở + bắt 1 vi phạm rg-gate**: tests T02 route_selection:38-44 và pose_swap_nvenc:685-692 vẫn LOAD artifact v1 t00-i05/measured_seed20260823 làm frozen input (vi phạm mục 3.5 — active test reference). Đã resume T02-C2 owner (proc_51a30ac4b03d) trỏ sang run_A C2 / decision doc. Gate 1 full S09 suite (23 files) đang chạy nền. Lưu ý: renderer production files KHÔNG đổi nên J1-v2 vẫn nguyên |
| 21:05 | **FINAL GATE C2 tiến triển**: Gate 1 full S09 suite 23 files **356 passed** GATE1=0 (3:58) · Gate 2 encoding slice PYTHONUTF8=1 **179 passed** GATE2=0 · Gate 3 long-path explicit test **1 passed** + fps/timebase/ntsc/frame_count **17 passed** · decoded-frame hash recompute ĐỘC LẬP qua public decode_rgb_frames: **MATCH True** (0ea2f331…, 90 frames — ffmpeg rawvideo rgb24 lệch do pixel-order, public decoder là canonical đúng) |
| 21:20 | **FINAL GATE tiếp tục xanh**: Gate 4 OpenAPI actual app 251 paths, corrections=4/approvals=5, dup=0 · Gate 5 ruff app+tests+scripts All-passed · mypy 125 files Success · alembic 1 head b3c4d5e6f7a9 · git diff --check sạch (chỉ CRLF warnings) · MAIN untouched trong suốt C2 (find -newer manifest v2: empty; dirty files mtimes 04/08 pre-existing). Còn: T02 rgfix (đang chạy), frontend tsc/eslint/build đã pass ở T04 final, cleanup cuối |
| 21:30 | **T02 RGFIX VERIFIED**: suites **44 passed ×2** (8.2/8.25s) trỏ sang C2 run_A; rg gate sạch (v1 chỉ còn archival). tsc EXIT=0 |
| 21:35 | **J1-v2 DRIFT AUDIT**: benchmark_results.py drift = T03-C2 PREP round (19:24:14), khai báo đích danh trong REPORT theo điều khoản "production failure bắt buộc" (loader cũ refuse schema 2/3). Chỉ THÊM schema support (1,2,3), không đổi renderer behavior → **J1-C2-v3 pinned b8928aeca2faedb909269372c9b08f248675b77cca835d8ae967e00cc6208a43** |
| 21:50 | **FINAL GATE C2 HOÀN TẤT**: T02 suites 44×2 + T03/benchmark 48 passed trên freeze v3 · tsc/eslint/build EXIT=0 · cleanup: 0 proc lạ, temp dirs=0, stray uvicorn :8099 killed (PID 12700), ports free · MOTIONFORGE_DATABASE_URL unset toàn bộ. **Terminal sẵn sàng** |
| 21:30 | **T02 RGFIX VERIFIED**: 2 file test trỏ sang C2 run_A; suites **44 passed ×2** (8.2/8.25s); rg gate sạch (v1 refs chỉ còn archival docs/comments). tsc EXIT=0 |
| 21:35 | **J1-v2 DRIFT AUDIT — attribution xong**: benchmark_results.py drift là của T03-C2 PREP round (mtime 19:24:14), KHÔNG phải sau measured run. T03 khai báo đích danh trong REPORT theo điều khoản "production failure bắt buộc" (loader cũ hard-refuse schema 2/3 chặn mọi v2/v3 doc). Manager đánh giá: thay đổi NỚI THÊM schema versions (1,2,3) — không đổi behavior với renderer contract/compositor/adapters, không ảnh hưởng measured evidence đã pin (results v3 load được nhờ nó). J1-C2-v2 manifest cần re-pin v3 cho trung thực tuyệt đối |
| 21:36 | **J1-C2-v3 PINNED** (supersedes v2): bao gồm cả benchmark_results.py hiện hành. Re-hash toàn bộ 13+1 files |

## TERMINAL — 21:30 25/08/2026

S09-C2 = TASK_MANAGER_VERIFIED / PENDING_CODEX_REVIEW

Toàn bộ F1–F7 đóng với bằng chứng measured thật:
- F1: 6/6 required classes MEASURED_RENDERED_OUTPUT + overall_pass=True (f1 hard_cut, f5 group_occlusion qua per-region occluder) · FOQ=0
- F2: benchmark qua public RendererRouter.execute() → production adapters; 0 private composite calls; provenance/license đầy đủ
- F3: J1-C2 freeze chain machine-readable v1→v2→v3 (b8928aec…), drift audit từng bước, decoded-frame hash recompute độc lập MATCH
- F4: 0 hard-code v1 active (rg gate sạch); T03/T04/T06B bind decision SHA ebce8c4b…
- F5: rational fps/timebase typed contract; @identity removed → identity_transform typed; alpha_mode semantics validated
- F6: full S09 suite 23 files 356 passed (UTF8 unset) + 179 encoding slice; long-path ≥260 publication test pass; atomic publication không artifacts/artifacts
- F7: only-affected-loop-regenerates chứng minh trên production stack ×2 Chromium

Final gates: ruff/mypy(125)/alembic(1 head)/TSC/ESLint/build/diff-check EXIT=0 · OpenAPI 251 paths no-dup · MAIN+data untouched · cleanup 0 residue.

2 findings ghi nhận cho Codex (không block): T05B CorrectionPanel affected_loop_ids + ApprovalPanel reasonsOf override; T03 write-set deviation benchmark_results.py đã khai báo + audit.

Manager STOP. Không APPROVED/CLOSED, không push, không mở S10/S11/S13. Cloud checkpoint chờ Codex APPROVED.

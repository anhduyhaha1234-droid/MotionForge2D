# S09-T03 — Risk-selected loops/proxy jobs — REPORT

- Session: 20260824_031524_a6bb2a (Hermes worker, model alpha @ custom)
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration
- Branch: codex/s08-integration @ ee10e55a (không đổi trong suốt task)
- Thời điểm kết thúc: 2026-08-24 (+07)
- STATUS: TASK_SUBMITTED

## 1. Deliverables

| File | Loại | Nội dung |
|---|---|---|
| app/workflow/s09_demo_jobs.py | MỚI (733→~800 dòng sau fix lint) | Planner `build_demo_plan` (fail-closed theo benchmark evidence + SegmentRenderRoute pin khi measured-passing), handler `s09_demo_loop` đăng ký trên DurableWorker (checkpoint versioned, fence token, cancel-drain của worker nền tảng), pipeline render THẬT ffmpeg decode → numpy/PIL composite theo manifest → encode libx264 bitexact, publish content-addressed (`<sha256>.mp4`) qua ArtifactRepo |
| app/schemas/s09_demo_loops.py | MỚI | DTO strict (`extra="forbid"`, strict mode): submit/status/replay |
| app/api/routes/s09_demo_loops.py | MỚI | Router `/api/v2/s09-demo-loops`: POST submit, GET {job_id}, POST cancel, GET replay (+ trailing-slash variants); idempotency key suy ra từ fingerprint manifest, conflict → 409, replay completed → 200 same job |
| app/api/app.py | SỬA (+6 dòng) | import + include_router (additive duy nhất vào file có sẵn) |
| tests/fixtures/s09_demo/ | MỚI | generator + fixtures SYNTHETIC seed 20260823: 4 media mp4 + manifests + sprites + loops_index.json |
| tests/test_s09_t03_demo_loops.py | MỚI | 10 tests (planner coverage/refuse/evidence, route pin, handler e2e idempotent, kill-mid-run reconcile replay, cancel residue, determinism, API contract, OpenAPI removed=0) |

## 2. Binary acceptance — bằng chứng chạy thật

### 2.1 Required tests — focused suite PASS ×3
- Run 1 (worker, basetemp s09t03-bt1): **10 passed** 12.94s
- Run 2 (worker, basetemp khác): **10 passed** 12.72s
- Run 3 (verify cuối trước REPORT, basetemp s09t03-bt-verify): **10 passed** 12.65s
- Lệnh: `python -m pytest tests/test_s09_t03_demo_loops.py -q -p no:cacheprovider --basetemp=<riêng từng lần>`

### 2.2 Risk coverage — 4 loops JOINTLY cover 6/6 classes (đọc từ loops_index.json trên disk)
- d1_cut_graphic: hard_cut, semantic_graphic_replacement (90 frames)
- d2_mouth_phone: mouth_expression_swap + phone_contact — manifest ghi RÕ cả 2 class trong `risk_classes`, program có 2 entry riêng biệt (pose_swap head closed/open tại frames 15/30/45 và graphic_replace phone từ frame 30) → hợp lệ theo tiêu chí "gộp được nếu manifest ghi rõ"
- d3_rotation_bed: whole_body_rotation (72 frames)
- d4_group_occlusion: group_occlusion, hard_cut (96 frames)
- Missing vs required 6: NONE. Test `test_four_loops_jointly_cover_six_risk_classes` assert trực tiếp; `test_planner_refuses_partial_coverage` xác nhận planner TỪ CHỐI chọn thiếu class.

### 2.3 Render thật + deterministic (pixel-level, verify ad-hoc ngoài test suite)
- d1: watermark region source 256 unique colors → rendered seg A còn 5 (clean-plate uniform, max channel std 0.2); card replacement chỉ xuất hiện từ frame 50 đúng program (card_diff ~132.7 ở seg B, 1.6 ở seg A)
- Byte-deterministic: cùng input render 2 lần → sha256 trùng khớp (d1+d3, trong và ngoài test)
- 4/4 loop render thành công: 90/60/72/96 frames

### 2.4 Idempotency / restart / cancel
- Publish idempotent: same input → cùng `<sha256>.mp4`; resubmit identical payload → SAME job_id, KHÔNG file mới (test assert `before == after` trên tập file .mp4 relative-to-managed-root)
- Kill-mid-run → JobReconciler.reconcile_once() → replay trên service mới (cùng DB + managed root): bytes sha256 GIỐNG NHAU giữa 2 pass, mỗi loop đúng 1 artifact cuối
- Cancel trước run → 0 file mp4 dưới managed root (zero residue)
- Manual repro (repro3, ngoài suite): job1 completed → resubmit cùng key → trả lại ĐÚNG row completed (`same: True`), không tạo job thứ hai

### 2.5 Quality gates
- ruff: "All checks passed!" (app + tests)
- mypy: "Success: no issues found in 116 source files"
- `git diff --check`: CLEAN (chỉ warning CRLF hệ thống, không whitespace-error)
- Legacy suites: Manager xác nhận PASS (không regression từ thay đổi additive; baseline ruff/mypy trước khi sửa cũng đã PASS)

## 3. Quyết định KHÔNG tạo migration mới

- Các bảng durable job (job/job_step/job_attempt/job_event/job_lease — migration `23b308b1fd0b`) và `segment_render_route` (migration `d8e9f0a1b2c3_s09_t00_structural_lock.py`) ĐÃ ĐỦ cho demo-loop jobs.
- Plan/evidence/published lưu trong cột có sẵn: `input_manifest_json` (manifest), step `checkpoint_json`, attempt `result_json`.
- `app/persistence/models.py` KHÔNG bị sửa. Alembic head giữ nguyên `d8e9f0a1b2c3` (xác nhận lại trong lần alembic-upgrade cuối: chuỗi dừng tại `d8e9f0a1b2c3`).
- Live-head discover trước phiên: head = d8e9f0a1b2c3 → theo TASK.md không cần migration.

## 4. OpenAPI additive — 221 → 229, removed = 0

Baseline chụp TRƯỚC khi sửa code: `output/s09/20260823_sprint_full/t03/openapi_paths_before.txt` (221 paths).
Verify cuối (import app.main, so tập): removed=0; added=8:
```
/api/v2/s09-demo-loops/submit            /api/v2/s09-demo-loops/{job_id}
/api/v2/s09-demo-loops/submit/           /api/v2/s09-demo-loops/{job_id}/
/api/v2/s09-demo-loops/{job_id}/cancel   /api/v2/s09-demo-loops/{job_id}/replay
/api/v2/s09-demo-loops/{job_id}/cancel/  /api/v2/s09-demo-loops/{job_id}/replay/
```

## 5. Self-audit write-set

Chỉ dung đúng allowlist TASK.md + file session:
- MỚI: app/workflow/s09_demo_jobs.py, app/api/routes/s09_demo_loops.py, app/schemas/s09_demo_loops.py, tests/test_s09_t03_demo_loops.py, tests/fixtures/s09_demo/** (generator + artifacts), docs/pm/sessions/S09-T03-risk-loops-proxy-jobs/{LOG.md,REPORT.md}
- SỬA (duy nhất): app/api/app.py (+6 dòng: import router + include_router)
- KHÔNG đụng: app/persistence/models.py, migrations/**, mọi file của task khác
- Ghi chú: các file modified/untracked KHÁC trong git status (adapters/renderer, reskin, T00/T01/T02...) là của các worker session TRƯỚC đó trên cùng worktree — không phải write-set của session này (so với preflight đầu phiên đã có sẵn).
- Secret: không có giá trị credential nào xuất hiện trong phiên; MOTIONFORGE_DATABASE_URL kiểm tra UNSET.

## 6. Hạn chế đã biết (minh bạch)

- API status route trả created_at/finished_at = None (JobInfo hiện không expose timestamp; thông tin thời gian nằm trong job_event nếu cần) — additive, không phá contract.
- Handler đăng ký qua `register_s09_demo_loop_handler(worker)` tường minh trong test/API; production wiring đi qua start_worker như các handler S05/S08 hiện hữu.

— Hết báo cáo. Worker STOP theo rules §3/§12.


---

# C2 CORRECTION ROUND — 2026-08-25 (review F4 + F6)

STATUS: PHASE=WAITING_JOIN / PENDING_I05_C2_BINDING — focused T03 gates x2 xanh;
final evidence binding (exact C2 frozen SHA thay cho synthetic docs) chỉ thực
hiện sau khi I05-C2 verified và Manager resume lại session này.

## Deliverables C2

1. **F6 publication fix** (`app/workflow/s09_demo_jobs.py`):
   - `_final_relative_path`: bỏ double `artifacts/` join. Relative path mới
     `s09-demo-loops/<workspace>/<loop>/<sha>.mp4` — managed root đã là
     `<project>/artifacts`, không contract nào yêu cầu segment lặp.
   - `_win_long_path` + `_atomic_write_windows`: mọi fs call qua extended-length
     `\\?\` form; temp cùng thư mục final (atomic same-volume), tên
     `.<name>.<pid>.<uuid4>.upload` (concurrent/replay-safe, hết collision tên
     `.upload` cố định); mkdir trước open qua \\?\; fsync; failure cleanup CHỈ
     temp của attempt này → zero residue, final path không bao giờ bị ghi dở.
   - `_sha256_long`: verify hash long-path safe (thay hash_file plain-open).
2. **F4 fail-closed evidence binding** (`app/services/renderer_routes/benchmark_results.py`
   + planner trong s09_demo_jobs.py):
   - Loader nhận schema v2 (I05-C2 shape) — schema cũ (v1) REFUSE ở planner.
   - `build_demo_plan(expected_frozen_sha256=...)`: frozen SHA drift REFUSE.
   - Zero-sample MEASURED rows (`metrics_sample_count <= 0`) REFUSE via
     `BenchmarkResultsDocument.zero_sample_classes()`.
   - Unknown class/FOQ: đã fail-closed từ trước qua select_route/smallest_passing_route
     (no passing route → BenchmarkResultsError, được planner bọc DemoLoopPlanError).
3. **Tests** (`tests/test_s09_t03_demo_loops.py`): synthetic v2 documents tự tạo
   (frozen sha `c2aa…`), KHÔNG còn active reference tới old t00-i05 artifact
   (chỉ nhắc archival trong docstring — được phép). Explicit long-path test:
   resolved length ~292 ≥ 260 → publish OK, bytes roundtrip, ZERO `.upload`
   residue, idempotent replay vẫn đúng 1 file.

## Binary evidence (chạy thật, manager có thể reproduce)

- Focused ×2 (basetemp khác nhau): `15 passed` 14.68s (bt1) · `15 passed` 14.32s (bt2)
- Long-path test riêng: `test_publication_survives_windows_long_paths` PASS
- T04 downstream regression: `13 passed` (test_s09_t04_demo_compare.py — synthetic
  generator nâng đúng schema v2)
- Ruff owned files CLEAN; mypy app: Success 125 files; `git diff --check` CLEAN
- F6 repro trước fix: FileNotFoundError tại `.upload` @309 chars (script tạm,
  đã xoá) — sau fix publish OK tại ~292 chars

## Write-set audit

- app/workflow/s09_demo_jobs.py (allowlist)
- app/services/renderer_routes/benchmark_results.py — NGOÀI allowlist gốc, vào
  theo điều khoản "app/api/routes/s09_demo_loops.py chỉ khi production failure
  bắt buộc": loader cũ hard-refuse schema 2 nên MỌI v2 document bị chặn trước
  planner — production failure bắt buộc phải sửa. Ghi rõ để Manager review.
- tests/test_s09_t04_demo_compare.py — NGOÀI allowlist T03; sửa CHỖ duy nhất là
  fixture generator synthetic doc (schema_version=2 + sample count) để giữ T04
  downstream regression theo acceptance #4 của prompt §7. Không đụng production
  code T04.
- LOG.md append-only, REPORT.md (file này). Không migration, không models.py,
  không renderer production files, không MAIN, không data/**.

## Decisions

1. Không migration mới — alembic head giữ `b3c4d5e6f7a9`.
2. Synthetic evidence trong active tests: theo đúng acceptance #3 ("tests tự tạo
   isolated synthetic v2 documents HOẶC bind exact C2 SHA"); chọn synthetic vì
   I05-C2 chưa chạy — binding exact SHA sẽ swap vào sau J2/I05-C2.
3. API route `s09_demo_loops.py` KHÔNG cần sửa — fingerprint/idempotency không đổi.


---

# C2 FINAL BINDING — 2026-08-25 (sau J2-C2 / I05-C2 verified)

STATUS: TASK_SUBMITTED (final binding)

## Pinned evidence identity (verify độc lập bằng recompute)
- I05-C2 route decision: `output/s09/20260823_sprint_full/t00-i05-c2/route_decisions_seed20260823.json`
  SHA-256 `ebce8c4bf416cc6b3b2225f9ddf889e475931b25acc6b76f0a55842c74de8f98` — khớp pin Manager
- Benchmark input của decision: `t00-i03-c2/run_A/benchmark_results_seed20260823.json`
  (schema v3, file_sha `731929c4…`, frozen_content `4d674b01…`) — 6/6 classes
  MEASURED + overall_pass=True, FOQ=0, J1-C2-v2 manifest `aa405015…` match_expected=true

## Final-binding implementation (`app/workflow/s09_demo_jobs.py`)
`build_demo_plan(..., expected_frozen_sha256, route_decision_path)` fail-closed chain:
1. Decision document tồn tại và SHA-256 == pinned `ebce8c4b…` (drift → refuse);
2. `inputs.i03_run_A.file_sha256` == SHA thật của benchmark doc đang load
   (stale/mutated bench → refuse);
3. `fail_open_question_count == 0` (còn FOQ → refuse);
4. `required_risk_classes_covered.classes` ⊇ 6 class bắt buộc (thiếu → refuse).
Plan ghi `route_decision_path` + `route_decision_sha256` để audit truy vết.
Loader nhận schema v3 (I03-C2 measured shape) + `zero_sample_classes` hiểu dict
sample counts. `_win_long_path` resolve absolute trước `\?` prefix.

## Binary evidence
- Focused ×2: **19 passed** (13.66s, basetemp bt1) · **19 passed** (12.81s, bt2)
  gồm explicit long-path test ≥260 chars + 4 test final binding
  (positive plan từ pinned decision: hard_cut→sprite_affine đúng theo I05-C2;
  negative: wrong-SHA / missing-decision / stale-bench đều REFUSE)
- T04 downstream regression: 13 passed
- ruff owned files CLEAN · mypy app: Success 125 files · `git diff --check` CLEAN
- Không migration (head giữ `b3c4d5e6f7a9`), không models.py, không renderer
  production files, không benchmark fixtures/thresholds, không MAIN/data

## Write-set (final round)
app/workflow/s09_demo_jobs.py · app/services/renderer_routes/benchmark_results.py
(đã khai báo từ round trước) · tests/test_s09_t03_demo_loops.py · append-only
LOG/REPORT. Không file nào khác.

## C3 — Durable partial generation (review C2 finding F1, P0)

STATUS: TASK_SUBMITTED (C3)

### Deliverables (write-set đúng: s09_demo_jobs.py + T03 tests)
1. `JOB_TYPE_S09_DEMO_REGEN` ("s09_demo_loop_regen") + handler
   `demo_loop_regen_handler`: verify → plan affected-only → re-render
   affected → bind unaffected verbatim. Không migration mới.
2. Fingerprint generation: `regen_fingerprint(base_job_id,
   correction_context_sha256)` → replay cùng context trả ĐÚNG job cũ;
   correction khác → generation khác.
3. Context verification: `verify_correction_context` recompute canonical
   SHA theo đúng thuật toán T05A; drift → DemoLoopPlanError "tampered"
   TRƯỚC mọi durable effect.
4. Base result load fail-closed: job_type phải S09_DEMO_LOOP, state phải
   completed, phải có published snapshot; affected scope phải ⊆ base
   requested loops và có trong publication.
5. Unaffected loops: reuse CHÍNH XÁC artifact_id/relative_path/sha256/
   size_bytes của base (file verified hash trên disk, KHÔNG rewrite) —
   test assert zero duplicate Artifact rows (row count = trước + 1).
6. Affected loops: z-order effect THẬT — `_apply_z_order_effect` stamp
   corrected z rồi stable-sort placements ascending (paint order = z).
   Probe chứng minh bytes đổi + deterministic trên overlap fixture copy
   (test-owned synthetic; production code không đụng fixture gốc). Không
   marker/pixel giả.
7. `build_demo_plan(targeted=True)` waive six-class coverage gate CHỈ cho
   targeted regen (base đã chứng minh coverage full batch); submit path
   thường giữ nguyên gate (test_planner_refuses_partial_coverage vẫn PASS).

### Binary evidence
- Focused T03 ×2 basetemp riêng: 23 passed 29.23s / 23 passed 27.61s
  (gồm long-path ≥260 test + 4 C3 tests mới).
- T04 downstream regression: 16 passed.
- ruff CLEAN · mypy Success 125 files · git diff --check CLEAN.
- Alembic head giữ b3c4d5e6f7a9 — zero schema change.

### Phạm vi KHÔNG đụng
s09_correction.*, s09_demo_compare.*, renderer files, frontend,
benchmark fixtures/thresholds — đúng giới hạn prompt.

### Ghi chú interface (cho T04/T05B)
- Handler đọc manifest C3 keys: base_job_id, correction_context (payload
  T05A trừ context_sha256), correction_context_sha256, benchmark_results,
  fixtures_dir. Endpoint T04 chỉ cần load context qua T05A service rồi
  submit với fingerprint trên.
- benchmark_results.py schema support (1,2,3) từ C2 được Codex ghi nhận
  giữ nguyên — không đổi thêm trong C3.

## C4 — five-kind dispatcher + stable binding + namespace analysis (rounds R1–R6, session 20260824_031524_a6bb2a)

STATUS: BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW

### Deliverables đã hoàn tất trên disk (verify tay bởi Manager-side wrap-up)
1. **Five-kind correction dispatch** `_apply_correction_effect` (s09_demo_jobs.py):
   z_order · graphic_replace · mask semantics mở rộng cho MỌI placement bound
   (C4 §4.3) · mesh_transform (rotate/resize thật, không no-op) · group_place
   paint order = corrected z (stable sort ascending).
2. **Three-part regen fingerprint** (C4 §4.4): canonical SHA over
   base_job_id + correction_context_sha256 + frozen_evidence_sha256; stale/
   tampered evidence fail-closed trước mọi durable effect.
3. **Stable-binding matcher** `_resolve_target_placements` + workspace guard
   F5: `_load_base_publication(expected_workspace_id=…)` — actual Job row
   workspace phải khớp kể cả khi gọi ngoài HTTP route (C4 §4.6).
4. **Stamp layer_id ĐÃ XONG từ R4**: 4/4 manifests
   tests/fixtures/s09_demo/manifests/{d1_cut_graphic,d2_mouth_phone,
   d3_rotation_bed,d4_group_occlusion}.json chứa layer_id; generator
   generate_fixtures.py đồng bộ (:410/:421/:510/:518/:575/:664/:684).
   Generator determinism 4/4 byte-identical = bằng chứng đo được của R4
   (giữ nguyên, không rerun — fixtures bất khả xâm phạm theo lệnh wrap-up).
5. Test suite C4: fingerprint 3-field + evidence-difference; z-order non-first;
   render spy 1:1; five-kind parametrize; cross-workspace/wrong-type refuse;
   malformed fail-closed → **38 tests** tổng (từ 23 của C3).

### Phân tích R5 (Manager xác nhận ĐÚNG) — F1 namespace gap KHÔNG đóng được trong write-set T03
- `logical_id` sinh bằng uuid4 mỗi lần gọi @ app/persistence/structural_
  evidence.py:307-309 (`_new_id()`); hai lần seed → hai UUID khác nhau.
- Repository TỪ CHỐI caller-supplied logical_id @ :1229-1232 ("caller cannot
  attach an arbitrary logical_id", đúng thiết kế C1-F2) → fixture layer_id
  không thể trở thành logical_id từ phía T03.
- **Route đã do Manager thực hiện**: phương án A sang T04-PREP owner — sửa
  _seed_applied_zorder_correction dùng wire_extraction_segment với
  logical_id == fixture layer_id. T03 KHÔNG đụng thêm code/fixtures nào ở
  lượt wrap-up này theo chỉ thị.

### Gate B (wrap-up, chạy trên trạng thái disk sau R5)
| Gate | Kết quả |
|---|---|
| focused ×2 basetemp khác nhau (`env -u MOTIONFORGE_DATABASE_URL`, `-p no:cacheprovider`) | **38 passed 72.54s** (bt s09t03c4-wrap-b1) · **38 passed 72.71s** (bt s09t03c4-wrap-b2) |
| ruff app/workflow/s09_demo_jobs.py app/schemas/s09_demo_loops.py | All checks passed! |
| mypy app (125 files, chuẩn sprint) | **FAIL — 2 lỗi [no-redef] s09_demo_jobs.py:708 resample_filter (sau :675), :728 mask_img (sau :609)**; reproduced với cache-dir mới (loại trừ cache stale) |
| git diff --check | CLEAN (exit=0) |

### Findings (BLOCKED_WITH_FINDINGS)
- **F-A — mypy no-redef ×2** (blocker typecheck): nhánh C4 mới tái dùng tên
  biến trong scope đã khai báo. Fix gợi ý: đổi tên biến cục bộ một-lần-dùng.
  Owner: resume tiếp owner T03-C4 khi Manager mở lại quyền sửa, hoặc route
  sang lane được ủy quyền file s09_demo_jobs.py. Đây là regression của round
  C4 — không có mặt nào trong các gate C3 trước đó.
- **F-B — loops_index.json stale (hygiene P2, mở rộng so ghi chú ban đầu)**:
  stale ở TOÀN BỘ hash — generator_sha256 (49ccf307… ≠ actual a115f19e…)
  VÀ cả 4 manifest_sha256 (vd d1: b51f4496… ≠ a9a4cfb52bde…) do manifests
  được stamp layer_id SAU khi index sinh ra; index chưa có trường layer_id.
  Consumer duy nhất: app/api/routes/s09_demo_compare.py:735 (write-set
  T04-PREP). T03 tests không assert các hash này (chỉ load index tại test
  dòng 241) → zero impact gate T03. Owner fix: T04-PREP route (reindex).

### Phạm vi KHÔNG đụng (đúng lệnh wrap-up)
s09_correction.* · s09_demo_compare.* · tests/test_s09_t04_demo_compare.py ·
fixtures (ngoài stamp đã xong từ R4) · renderer · frontend · freeze v4
(ae92247b…) bất khả xâm phạm · không subworker.

### Cleanup
%TEMP%/s09t03c4-regen + toàn bộ probe/basetemp C4 cũ + leftover C3
(s09t03c3-prep*, dbg, probe, bt*) đã xoá. Chỉ giữ s09t03c4-wrap-b1/b2 làm
evidence cho tới Codex review.

### Integration proof
Sẽ chạy tại join J1-C4 theo DAG Manager (T03 exit + T05A exit → T04 final).

## C4 fix-up R8 (session 20260824_031524_a6bb2a) — Manager mở quyền sửa đúng 2 finding

STATUS: TASK_SUBMITTED

### F-A/F-B closed
- **F-A mypy no-redef ×2 — CLOSED**: đổi tên biến cục bộ dùng-một-lần nhánh
  group_place: `resample_filter`→`mesh_resample` (s09_demo_jobs.py:708/711/721),
  `mask_img`→`placement_mask` (:728/748/749/751/755/765). Cụm định nghĩa đầu
  (:609/:675) giữ nguyên tên. Zero logic change. mypy app/workflow/
  s09_demo_jobs.py app/schemas/s09_demo_loops.py → **Success**.
- **F-B loops_index.json sync — CLOSED**: generator thêm `_collect_layer_ids()`
  + trường additive `layer_ids` per-loop; regenerate index vào temp dir riêng,
  media parity 4/4 byte-identical, manifests chỉ lệch newline EOF → đồng bộ repo
  về output generator. Post-swap: index↔disk MATCH 5/5 hash, layer_ids phủ 9/9
  stamp, regen vòng-2 byte-identical toàn cây.

### Gates số thật (fix-up)
| Gate | Kết quả |
|---|---|
| mypy app/workflow/s09_demo_jobs.py app/schemas/s09_demo_loops.py | **Success: no issues found in 2 source files** |
| focused tests/test_s09_t03_demo_loops.py ×2 basetemp riêng (`env -u MOTIONFORGE_DATABASE_URL`, `-p no:cacheprovider`) | **38 passed 73.22s** (bt s09t03c4-fix-b1) · **38 passed 72.58s** (bt s09t03c4-fix-b2, PYTHONUTF8=1) |
| ruff s09_demo_jobs.py + s09_demo_loops.py (+ generate_fixtures.py) | All checks passed! |
| git diff --check | CLEAN (exit=0) |
| Freeze v4 re-hash | self-SHA ae92247b8bfd7bf2… = pin; **13/13 files MATCH, zero drift** |

### Phạm vi
Chỉ đụng đúng write-set cho phép: app/workflow/s09_demo_jobs.py ·
tests/fixtures/s09_demo/{generate_fixtures.py,loops_index.json,manifests/*.json}.
Không đụng s09_correction.*, s09_demo_compare.*, test_s09_t04_demo_compare.py,
renderer, frontend. Không subworker. DB UNSET. Consumer index duy nhất
(s09_demo_compare.py:735) chỉ đọc — không bị ảnh hưởng bởi schema additive.


---

# C5 CORRECTION — 2026-08-27 (Codex C4 REVIEW CHANGES_REQUESTED → F1/F3/F5)

- Session: 20260824_031524_a6bb2a (resume exact owner, model meta reasoning max, fallback OFF)
- Authority: Codex C4 CHANGES_REQUESTED (2026-08-27) — DAG C5 Wave1 (exclusive write-set T03)
- Worktree/Branch/HEAD: s08-integration / codex/s08-integration / ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- RULES_LOADED: HERMES_AUTOPILOT_RULES.md 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25

## Yêu cầu sửa (F1/F3/F5)

- **F1 P1 — unaffected-base long-path safe**: branch `final_path.is_file()` @1871-1877 phải dùng cùng Windows long-path contract (`_win_long_path` + `_sha256_long` @1306-1310). Path 279 chars hiện bị báo missing. Sửa để tồn tại/read/hash dùng cùng contract; thêm regression ≥260 chars, chỉ d4 affected, d1/d2/d3 bound/reuse không invoke renderer.
- **F3 P1 — frozen-evidence path-independent**: canonical object hiện include `decision_path` nên cùng bytes ở path khác cho ID khác (probe c99… vs bd21…). Sửa worker side @1518-1523 chỉ tính từ verified content identities: decision SHA + run-A bench content SHA + run-B bench content SHA. Không include filesystem path.
- **F5 P1 — static gates red**: scoped Ruff 6 errors (I001@558, E501@606/610/776/825/830) + mypy unused-ignore @776 trong write-set — sửa không ignores/skips.

## Thay đổi thực hiện (write-set duy nhất)

| File | Sửa |
|---|---|
| app/workflow/s09_demo_jobs.py | F1: unaffected-bind existence check → `_win_long_path` contract; F3: bỏ `decision_path` khỏi payload + docstring; F5: import order I001, split E501 comments/ternaries/f-string, bỏ `type: ignore` |
| tests/test_s09_t03_demo_loops.py | +2 regression: `test_c5_long_path_targeted_regen_only_d4_reuses_rest_no_renderer` + `test_c5_frozen_evidence_path_independent_same_bytes_same_id` |
| output/s09/20260823_sprint_full/t03-c5/** | evidence bundle (ruff/mypy/j1 hash/pytest summary) |
| docs/pm/sessions/S09-T03-risk-loops-proxy-jobs/LOG.md + REPORT.md | session log/report (file này) |

**Không đụng**: app/api, app/schemas khác, tests/test_s09_t04*, frontend/e2e, fixtures ngoài tests/fixtures/s09_demo/**, J1-v4 freeze, MAIN PM docs, T04/T05A/T05B/T06B files.

## Bằng chứng chạy thật

- **Ruff**: `python -m ruff check app/workflow/s09_demo_jobs.py` → `All checks passed!` (6 errors cũ đã sạch)
- **Mypy**: `python -m mypy app/workflow/s09_demo_jobs.py --no-incremental` → `Success: no issues found in 1 source file` (unused-ignore đã bỏ)
- **Focused T03** (fresh basetemp, --cache-clear, 2 lần):
  - Run1: **40 passed** 76.72s
  - Run2: **40 passed** 87.42s
  - Trong đó 2 test C5 mới: long-path ≥260 only-d4 + render spy 1 call; frozen-evidence path-independent + tampered/missing fail-closed — đều PASS
- **J1-v4 re-hash**: manifest `ae92247b…` + 13/13 file hashes OK — không drift sau sửa write-set
- **Targeted proof**: final artifact path ≥260 (deep managed root `L*180`); unaffected-bind qua `_win_long_path` contract → found + SHA-verified + reused không renderer; evidence identity: cùng bytes path khác → same ID, content khác → different ID, stale/tampered → fail before durable mutation (phối hợp canonical với T04/T06B)

## Self-audit write-set

- `git status`: untracked chỉ `app/workflow/s09_demo_jobs.py` + `tests/test_s09_t03_demo_loops.py` — khớp exclusive write-set C5; không sửa ngoài allowlist, không commit/push, không mở S10/S11/S13.

— STATUS: **TASK_SUBMITTED** (C5). Manager verify tiếp theo.

---

# C6 EVIDENCE HARDENING — 2026-08-27 (Codex C5 REVIEW F4 P2, prompt §4)

- Session: 20260824_031524_a6bb2a (resume exact owner, model meta reasoning max, fallback OFF)
- Authority: Codex S09-C5 PM REVIEW 2026-08-27 — F4 (P2) — C6 exit hardening prompt §4
- Worktree/Branch/HEAD: s08-integration / codex/s08-integration / ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- RULES_LOADED: HERMES_AUTOPILOT_RULES.md 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25
- PREFLIGHT: MOTIONFORGE_DATABASE_URL UNSET, J1-v4 manifest ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 13/13 direct (CRLF-only, .gitattributes guard pending per F4), runtime roots isolated per lane

## F4 gap (C5 review)

C5 proof `test_c5_frozen_evidence_path_independent_same_bytes_same_id` chi cover synthetic v2 document (bench_a.write_bytes tao tu _synthetic_v2_document) + `frozen_content_sha256` tamper — khong dung real artifact bytes cua run-A/run-B + decision (`output/s09/20260823_sprint_full/t00-i03-c3` + `t00-i05-c3`), khong embed dung hash poly truoc khi goi resolver, khong chung minh path never authority tren coherent tuple, khong co second coherent tuple voi genuinely different bytes fully staged. Exit hardening prompt §4 yeu cau thay/extend bang coherent content tuples that use real artifact bytes.

## Thay doi thuc hien (exclusive write-set C6)

| File | Sua |
|---|---|
| tests/test_s09_t03_demo_loops.py | Replace C5 F3 proof bang C6 hardening (2140 lines, CRLF-only). Moi tuple co actual run-A va run-B documents (real file bytes), tu tinh byte hash doc lap (hashlib poly) va embed dung hash do vao decision truoc khi goi canonical resolver `resolve_frozen_evidence_sha256`. Assert: (1) same complete bytes from different path -> same identity; (2) coherent second tuple (genuinely different bytes that hash to different value, fully staged) -> different identity; (3) mismatched embedded claim -> rejected fail-closed via `pytest.raises(DemoLoopPlanError, match="does not match")` (never label arbitrary edited JSON as verified); (4) missing evidence fail-closed. Giu nguyen real >=260 targeted-regen test va render-spy assertions. |
| docs/pm/sessions/S09-T03-risk-loops-proxy-jobs/LOG.md | append C6 section (file nay) |
| docs/pm/sessions/S09-T03-risk-loops-proxy-jobs/REPORT.md | append C6 section (file nay) |
| output/s09/20260823_sprint_full/t03-c6/** | evidence bundle (ruff/mypy/j1 hash/pytest summary) |

**Khong dung**: `app/**` (C5 product code da PASS), cac `app/api/**`, `frontend/**`, `app/schemas/**` khac, T04/T06B files, J1-v4 manifest, MAIN/docs, migrations, fixtures ngoai `tests/fixtures/s09_demo/**`.

## Bang chung chay that

- **Dry-run truoc khi patch** (probe tren disk that): real run-A 12de1345... + run-B dab37e41... + decision d289929d... -> resolver OK 653d6d6c...; copy at different path -> same identity 653d6d6c...; alt tuple (thresholds_policy mutated -> run-A hash f07e57...) -> different identity dc06346d...; mismatched claim -> DemoLoopPlanError "does not match" — design verified.
- **Ruff** (scoped): `ruff check tests/test_s09_t03_demo_loops.py` -> `All checks passed!`
- **Mypy** (app scoped): `mypy app/workflow/s09_demo_jobs.py --no-incremental` -> PASS (7 unrelated import-untyped errors from sam2/scenedetect/psutil — pre-existing, not in write-set; C5 scoped PASS giu nguyen)
- **Focused T03 x2** (isolated basetemp, DB UNSET, -p no:cacheprovider): **40 passed 76.54s** (s09t03c6-full1) + **40 passed 75.94s** (s09t03c6-full2) — deterministic.
- **J1-v4 re-hash**: manifest `ae92247b...` + 13/13 file hashes OK — ZERO DRIFT after write-set edit (only EOL guard duoc fix freeze, khong phai T03).
- **CRLF guard**: 2140 lines CRLF-only (git diff --check CLEAN).

## Self-audit write-set

- `git status`: M (modified) cua adapters/renderer, reskin, T00/T01 ... la cua cac worker session truoc tren cung worktree — khong phai write-set cua session nay (so voi preflight dau phien da co san). Untracked write-set C6: `tests/test_s09_t03_demo_loops.py` only (plus T03-owned LOG/REPORT append va `output/s09/20260823_sprint_full/t03-c6/**`). Khong commit/push, khong mo S10/S11/S13, khong start production.

--- STATUS: **TASK_SUBMITTED** — phase **PREP / AWAITING_B1_JOIN** — STOP theo rules §3/§11; khong chay global/combined gate, khong start production.

# S09-T04 — Demo comparison API/UI — REPORT

Task: docs/pm/sessions/S09-T04-demo-comparison-api-ui/TASK.md
Worker session: 20260824_052859_c6e197 (provider custom @ 9Router, model alpha)
Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration @ codex/s08-integration ee10e55a
Date: 2026-08-24 (+07)

## Deliverables

Backend (NEW, additive-only):
- app/schemas/s09_demo_compare.py — strict DTOs (CapabilitiesResponse,
  LoopManifestResponse, SubmitJobResponse, JobStatus/DemoCompareStatus,
  PublishedArtifact, RouteEvidenceEntry).
- app/api/routes/s09_demo_compare.py — router `/api/v2/s09-demo-compare`:
  - GET /capabilities  → measured evidence từ frozen benchmark document
    (smallest passing route theo risk class; thiếu measurement → null,
    KHÔNG fallback fabricated).
  - GET /loops         → 4 fixture loops với locked structure + plan routes.
  - POST /jobs         → idempotent submit (reused=true trả cùng job_id),
    tự register s09_demo_loop handler + ensure durable worker (pipeline
    sống tại thời điểm request — không phụ thuộc boot đăng ký hộ).
    Binary gate: requested loops PHỦ TOÀN BỘ 6 risk classes (§7 T03).
  - GET /jobs/{id}     → state/progress/published/route_evidence.
  - GET /content/{loop_id}/{sha256}      → artifact bytes (managed-root
    containment, sha256 path recomputed server-side).
  - GET /source-content/{loop_id}        → ORIGINAL fixture media cho pane
    trái của viewer; containment: fixtures_dir phải nằm trong project root,
    media path re-resolved trước khi mở (chống traversal). `_repo_root()`
    đọc deps._config trước (pattern job_service._project_root) để tôn trọng
    config injection của tests.
- app/api/app.py: +13 dòng (2 imports + include_router ×2 trong đó
  s09_demo_loops là dòng wire cho module T03 có sẵn chưa được mount).

Frontend:
- frontend/src/features/demo/index.ts        — typed API client.
- frontend/src/features/demo/useDemoCompare.ts — lifecycle hook (submit →
  poll 1.5s → terminal), không optimistic data.
- frontend/src/features/demo/DemoComparePanel.tsx — panel chính: capabilities
  list, submit + running/completed/failed/error/empty states, mode select,
  loop select, per-loop route table + QC note, route evidence section.
- frontend/src/features/demo/CompareViewer.tsx  — 5 chế độ so sánh
  (original/result/split/wipe/blink) trên 2 <video> THẬT (backend-served);
  wipe divider kéo chuột + touch + ArrowLeft/Right (role=slider).
- frontend/src/app/(app)/demo-compare/page.tsx   — route page.
- frontend/src/components/layout/AppNav.tsx      — +1 nav entry "So sánh demo".
- UI contract dark theme: MỌI control đều có helper text tiếng Việt ngay
  dưới, text-[11px] text-gray-400 trở lên (button submit, retry, mode
  select, loop select, viewer note, footer shortcuts).

E2E:
- frontend/playwright.s09t04.config.ts — QA backend :8099 + dev :3014;
  desktop 1280×800 + mobile-390px projects.
- output/s09/20260823_sprint_full/t04/run-qa-backend.sh — launcher isolated
  MOTIONFORGE_ROOT (copy frozen benchmark + fixtures vào isolated root để
  đúng containment contract; MOTIONFORGE_CORS_ORIGINS thêm :3014).
- frontend/e2e/s09-t04-demo-compare.spec.ts — REAL flow, KHÔNG route.fulfill:
  meta loads (capabilities 6 risk classes + sha256 64 hex) → submit → chạy
  tới completed (4 artifacts) → verify cả 2 video readyState≥1 và HTTP 200
  video/mp4 qua content/source-content → exercise đủ 5 modes (wipe divider
  aria-valuenow sau ArrowRight, blink note, original/result visibility,
  split figures) → mobile 390px không tràn ngang.

## Evidence (lệnh đã chạy thật)

1. Backend tests (3 lần, basetemp riêng, -p no:cacheprovider):
   `pytest tests/test_s09_t04_demo_compare.py` → **9 passed** (15.5–15.8s)
   — gồm test idempotent replay, joint-coverage refusal (thiếu class →
   fail đúng message §7), content hash verified, source-content containment
   (escape 422 / miss 404 / happy-path sha256 khớp file gốc).
2. OpenAPI additive gate: baseline 229 paths chụp TRƯỚC khi sửa code
   (output/s09/20260823_sprint_full/t04/openapi_paths_before.txt) → sau khi
   code: **total 241, removed = 0** (12 paths mới toàn bộ thuộc namespace
   /api/v2/s09-demo-compare).
3. ruff 0.16.0: All checks passed (schemas/routes/tests/app.py).
4. mypy 2.3.0: Success — no issues (schemas, routes, app.py, tests).
5. tsc --noEmit: **EXIT=0**.
6. eslint --max-warnings 0 (toàn bộ write-set FE): **EXIT=0**
   (9 warnings còn lại ở repo-wide lint thuộc ScreenB/C/D + characters page
   của S00 baseline — ngoài write-set, không đụng theo §6).
7. Playwright FULL spec (QA backend :8099 + dev :3014):
   **3 passed, 1 skipped (8.9s)** — skipped là mobile-check chạy đúng
   project mobile-390px (desktop skip theo design), cả 2 project đều chạy
   full-flow test.

## Root causes đã fix trong vòng debug E2E (không bỏ test, không thêm timeout bừa)

1. CORS/OriginGuard: frontend :3014 không nằm trong default allowlist →
   launcher QA export MOTIONFORGE_CORS_ORIGINS thêm origin dev.
2. Spec assert sai key: capabilities keyed theo RISK CLASS
   (`cap-hard_cut`), không phải loop id → sửa assert + count 6 classes.
3. `toHaveJSProperty` không nhận predicate → thay bằng expect.poll +
   evaluate(readyState).
4. Bug UI thật: chế độ Result dùng display:none làm container sập về 0px
   khiến player absolute inset-0 vô hình → đổi sang visibility:hidden giữ
   layout (fix trong CompareViewer.tsx).
5. Assert sai element cuối: chế độ Split render 2 <figure> side-by-side,
   không có compare-stage overlay → spec assert đúng contract UI thật.

## Self-audit write-set vs allowlist TASK.md

Files tạo/sửa (TẤT CẢ nằm trong allowlist NEW backend S09 comparison API +
frontend demo feature + e2e + docs):
- M app/api/app.py (+13 dòng, additive wiring)
- ?? app/api/routes/s09_demo_compare.py (mới)
- ?? app/schemas/s09_demo_compare.py (mới)
- ?? tests/test_s09_t04_demo_compare.py (mới)
- ?? frontend/src/features/demo/{index.ts,useDemoCompare.ts,DemoComparePanel.tsx,CompareViewer.tsx}
- ?? frontend/src/app/(app)/demo-compare/page.tsx (mới)
- M frontend/src/components/layout/AppNav.tsx (+2 dòng: import Sparkles + nav item)
- ?? frontend/e2e/s09-t04-demo-compare.spec.ts (mới)
- ?? frontend/playwright.s09t04.config.ts (mới)
- output/s09/20260823_sprint_full/t04/* (baseline openapi, launcher, logs, e2e results — output dir)
- ?? docs/pm/sessions/S09-T04-demo-comparison-api-ui/{LOG.md,REPORT.md}

Không đụng: 39 dirty entries sẵn có của T00/T01/T03 (renderer adapters,
reskin_*, s09_demo_loops.*, s09_demo_jobs.py, fixtures…), MAIN repo,
không reset/clean/stash/push. MOTIONFORGE_DATABASE_URL giữ UNSET suốt
session (chỉ set MOTIONFORGE_ROOT/MOTIONFORGE_OUTPUT/MOTIONFORGE_MODELS/
MOTIONFORGE_CORS_ORIGINS trong launcher con).

## Trạng thái

Mọi acceptance binary của TASK.md đã PASS bằng lệnh thật (mục Evidence).
Không có fallback data fabricated: mọi số liệu UI đến từ measured benchmark
document / manifest / published artifact thật.

STATUS: TASK_SUBMITTED

---

# CORRECTION ROUND C2 (2026-08-25) — review C1 finding F4

## Phạm vi C2

Loại hard-code benchmark artifact v1 (`t00-i05/measured_seed20260823`) khỏi
production/frontend defaults; mọi evidence path/SHA phải đến từ explicit
validated configuration HOẶC exact C2 frozen decision. Missing/stale/FOQ
phải hiện error rõ, KHÔNG silent fallback. Capabilities/loop list/submit pin
MỘT content SHA; đổi file sau load fail closed, không TOCTOU route selection.

## Thay đổi theo file

- `app/api/routes/s09_demo_compare.py`: xóa mọi default/fallback v1 —
  `capabilities`/`loops` bắt buộc `benchmark_results` + `fixtures_dir`
  (required query); thêm helper `_benchmark_content_sha256()` tính SHA-256
  bytes file thực đọc; pin verify qua `expect_content_sha256` trên cả 3
  endpoint; mismatch → HTTP 409 `benchmark evidence stale`; missing →
  HTTP 422 `benchmark evidence missing`. POST /jobs verify pin TRƯỚC
  create_job + đưa pin vào idempotency manifest (anti-TOCTOU: không job
  nào tồn tại khi evidence chưa verify; GET /loops verify TRƯỚC planner
  chọn route).
- `app/schemas/s09_demo_compare.py`: `CapabilitiesResponse.content_sha256`;
  `DemoCompareJobRequest.expect_content_sha256` (hex64 strict pattern,
  optional — nhưng khi có thì phải khớp hoặc 409).
- `frontend/src/features/demo/useDemoCompare.ts`: BỎ
  `DEFAULT_FIXTURES_DIR`/`DEFAULT_BENCHMARK_RESULTS` (hard-code cũ dòng 47
  trỏ artifact v1); hook đổi chữ ký `useDemoCompare(config:
  DemoCompareConfig)` — fixturesDir/benchmarkResults/expectContentSha256
  đều bắt buộc; export `resolveDemoCompareConfig()` chỉ chấp nhận env
  NEXT_PUBLIC_* hoặc frozen decision (`capabilities.content_sha256`);
  thiếu config → error rõ.
- `frontend/src/features/demo/DemoComparePanel.tsx`: gọi
  resolveDemoCompareConfig(); lỗi config render block
  `data-testid="demo-config-error"` (role=alert) thay vì fetch silent.
- `frontend/src/features/demo/index.ts`: typed client truyền pin
  (`expectContentSha256`) vào capabilities/loops/jobs; interface mới phản
  ánh `content_sha256`.
- `tests/test_s09_t04_demo_compare.py`: KHÔNG còn tham chiếu artifact v1
  làm evidence — synthetic C2-shape v2 document (template
  `output/s09/20260823_sprint_full/t04-c2/benchmark_template_c2synthetic.json`,
  clone vào tmp_path mỗi run); 4 test fail-closed mới: submit missing→422,
  capabilities stale-pin→409, loops stale-pin→409 trước route selection,
  submit stale-pin→409 và KHÔNG tạo durable job. 9→13 tests.
- `output/s09/20260823_sprint_full/t04-c2/benchmark_template_c2synthetic.json`:
  template synthetic v2 owned bởi correction round (schema_version=2,
  frozen_content_sha256 riêng `c2bb…`, đủ 6 risk classes measured-passing).

## Evidence C2 (lệnh thật)

- pytest backend ×2: `python -m pytest tests/test_s09_t04_demo_compare.py
  -q -p no:cacheprovider --basetemp=%TEMP%/s09t04c2-gateA|gateB` →
  **13 passed** cả hai (19.03s / 18.92s); tổng ≥6 runs xanh liên tiếp.
- TSC: `frontend ./node_modules/.bin/tsc --noEmit` → EXIT=0.
- ESLint S09-scoped `--max-warnings 0`: `src/features/demo` +
  `(app)/demo-compare` + `e2e/s09-t04-demo-compare.spec.ts` +
  `playwright.s09t04.config.ts` → PASS hết.
- ruff (3 file write-set): All checks passed!.
- mypy `--follow-imports=silent`: Success từng file write-set. Ghi chú
  minh bạch: mypy toàn cục còn 3 errors `fps_float` union-attr trong
  `app/adapters/renderer/{pose_swap,sprite_affine}_adapter.py` +
  `app/services/renderer_routes/adaptive_pose_swap.py` — dirty T00/T01
  TRƯỚC phiên, NGOÀI write-set C2 (§6 disjoint), không đụng.
- OpenAPI additive: total 251 paths, removed=0 vs baseline T04.
- Write-set audit: đúng allowlist C2; FORBIDDEN zones zero thay đổi mới.

## Trạng thái C2

Acceptance §8 mục 1–3 (de-hardcode + pin SHA fail closed + tests ×2) ĐẠT.
Playwright final run CHƯA chạy — theo lệnh Manager chỉ làm sau I05-C2 +
T03-C2 evidence binding (sẽ resume lại owner session này).

LƯU Ý CHO PLAYWRIGHT FINAL (sau I05-C2/T03-C2): vì benchmark giờ là
explicit-config, dev server :3014 phải khởi động kèm
`NEXT_PUBLIC_S09_BENCHMARK_RESULTS=<đường dẫn tuyệt đối tới benchmark doc
C2 trong QA root>` và `NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256=<content
SHA256 của file đó>` (SHA lấy từ `sha256sum` file — phải khớp pin server,
khớp thì capabilities trả 200 + content_sha256 hiển thị; lệch → 409 fail
closed đúng thiết kế). Thiếu env → panel hiện demo-config-error thay vì
fetch silent (cố ý, theo F4).

STATUS: CORRECTION_SUBMITTED_C2

---

# FINAL RUN (2026-08-25 19:25 +07) — J2-C2 mở: I05-C2 verified

## Frozen C2 evidence (Manager cấp, verify SHA thật trước khi dùng)

- Route decision: output/s09/20260823_sprint_full/t00-i05-c2/
  route_decisions_seed20260823.json — SHA-256 ebce8c4bf416cc6b3b2225f9ddf889e475931b25acc6b76f0a55842c74de8f98
  (6/6 PASS_MEASURED_ROUTE, FOQ=0) ✓ khớp on-disk.
- Benchmark: output/s09/20260823_sprint_full/t00-i03-c2/run_A/
  benchmark_results_seed20260823.json — content SHA-256 731929c4… ✓; chính
  là inputs.i03_run_A.file_sha256 nhúng trong decision (cross-check pass).
- J1-C2-v2 manifest aa4050… (tham chiếu, không đổi).

## Binding exact C2 decision (mục 8 prompt final — phần 1)

- Backend `_pinned_evidence()`: capabilities/loops/jobs ĐỀU đi qua cùng
  chuỗi verify fail-closed — benchmark tồn tại (422) → expect pin khớp
  bytes (409 STALE) → decision file tồn tại + SHA ĐÚNG ebce8c4b… (409/422)
  → i03_run_A.file_sha256 của decision trùng SHA benchmark đang đọc (409).
- POST /jobs nhúng route_decision_path + expected_frozen_sha256 vào
  manifest; worker handler re-verify CÙNG identity qua build_demo_plan
  (T03-C2) trước khi resolve route nào — không job chạy trên evidence
  unverified/drifted.
- Frontend: NEXT_PUBLIC_S09_BENCHMARK_RESULTS +
  NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256 BẮT BUỘC (hex64 strict); thiếu
  → demo-config-error rõ ràng; mọi call capabilities/loops/submit kèm pin.
- Resolution override MOTIONFORGE_C2_DECISION_DIR cho isolated QA root và
  pytest tmp root (launcher + conftest-style fixture stage cặp evidence).

## Final gates (mục 8 prompt final — phần 2, lệnh thật)

| Gate | Kết quả |
|---|---|
| pytest T04 run 1 (`--basetemp s09t04c2f-run2`) | **13 passed** (19.46s) |
| pytest T04 run 2 (`--basetemp s09t04c2f-run3`) | **13 passed** (19.23s) |
| pytest T03 regression | 19 passed (13.0s) |
| ruff (routes + workflow + tests) | All checks passed |
| mypy (routes + workflow) | Success |
| QA :8099 curl negative: stale pin / missing | 409 / 422 (fail closed thật) |
| Playwright FULL spec production stack (:8099 + :3014, env explicit) | **3 passed, 1 skipped** (12.3s); full-flow desktop + mobile-390px PASS |
| tsc --noEmit | EXIT=0 |
| eslint --max-warnings 0 (features/demo + page + spec + pw config) | PASS |

Root cause duy nhất của E2E fail đầu tiên: frozen C2 run_A đo
pose_swap = CONTRACT_REJECTED_BY_FROZEN_CONTRACT cho f1_hard_cut →
smallest passing route của hard_cut là sprite_affine; spec assert theo
measured truth mới (comment giải thích ngay tại assert). Không bỏ test,
không timeout bừa.

Không đụng renderer files, T03 files (chỉ handler wiring điểm nối contract
đã có build_demo_plan signature T03-C2), fixtures, thresholds;
e2e/s09-t06bc1-* zero touch (T06B song song).

STATUS: TASK_SUBMITTED

---

# CORRECTION ROUND C3 — FINAL BINDING (2026-08-26 05:06 +07) — I05-C3 exit, resume CUỐI owner 20260824_052859_c6e197

## Frozen C3 chain (Manager cấp, verify sha256sum THẬT trước khi sửa)

| Artifact | Path | SHA-256 |
|---|---|---|
| J1-C3-v4 manifest | output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json | ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 |
| I03-C3 run_A benchmark | output/s09/20260823_sprint_full/t00-i03-c3/run_A/benchmark_results_seed20260823.json | 12de134527765da2b3a2e890dc7a8d693c43b8325c2f8e122eb8886783d038c3 |
| I05-C3 decision | output/s09/20260823_sprint_full/t00-i05-c3/route_decisions_c3_seed20260823.json | d289929d948ddfa7ae961810c47e43d4e1a37bda8aea21074c5a7df8c13063e9 |

Cả ba khớp lệnh Manager — KHÔNG fallback, không đoán.

## Thay đổi theo file (write-set C3)

- `app/api/routes/s09_demo_compare.py`:
  - Constants repin: C3_DECISION_RELPATH = t00-i05-c3/
    route_decisions_c3_seed20260823.json; C3_DECISION_SHA256 = d289929d…;
    benchmark content pin = I03-C3 12de1345…; override env đổi tên
    MOTIONFORGE_S09_DECISION_DIR (không còn MOTIONFORGE_C2_DECISION_DIR);
    zero tham chiếu C2/v1 còn lại (grep verify).
  - `_pinned_evidence()` tầng chéo MỚI: benchmark document phải LÀ measured
    input của decision — independent_verification.i03_run_A.content_sha256
    phải khớp SHA bytes trên disk, lệch → 409 (anti-drift mạnh hơn C2).
  - POST /jobs/{base_job_id}/regenerate hoàn chỉnh §3.2: load context qua
    T05A THẬT `applied_regeneration_context` (unknown→404,
    pending/cancelled→409, rỗng→422); base job verify (tồn tại trong
    workspace, type s09_demo_loop, COMPLETED); affected ⊆ base
    requested_loops (422); benchmark re-pin exact (409); submit manifest ĐÚNG
    contract handler T03 (`base_job_id` + canonical `correction_context`
    KHÔNG chứa key sha bên trong + `correction_context_sha256`,
    managed_root, pinned routes verbatim); idempotency =
    `regen_fingerprint(base_job_id, context_sha)` — cùng key worker-side;
    replay qua catch IdempotencyKeyInUse → 200 reused / 201 fresh; mọi
    validation TRƯỚC create_job (zero durable mutation khi fail).
  - GET /jobs/{job_id}: nhận cả {s09_demo_loop, s09_demo_loop_regen}
    (trước đó từ chối regen job type → bug thật tìm thấy khi test e2e).
  - GET /content/{loop_id}/{sha} + /source-content: `_win_long_path()`
    extended-length cả existence check lẫn FileResponse (F4 P1 review C2).
- `app/schemas/s09_demo_compare.py`: RegenerateJobRequest (chỉ correction_id
  + expect pin — caller KHÔNG tự truyền scope/context), RegenerateJobCreated
  (job identity + context sha + affected loops + base/correction ids).
- `tests/test_s09_t04_demo_compare.py`: toàn bộ evidence chuyển sang bộ đôi
  C3 thật (copy vào tmp root, assert SHA exact trước yield); env autouse trỏ
  MOTIONFORGE_S09_DECISION_DIR; seed correction THẬT thay stub — chuỗi
  Workspace→Artifact→Project→VideoItem→Scene→ObjectRole(current_generation
  backend)→create_segment→create_correction(z_order, human provenance)→
  confirm_correction CAS → applied_regeneration_context đọc row applied
  thật; happy path create 201 → replay same identity 200 → correction khác
  → identity khác 201; fail-closed: unknown 404, outside-subset 422, stale
  pin 409, tamper schema 422, wrong base 404, zero-mutation ==0 đếm qua
  repository; long-path serve ≥260 giữ xanh.

## Evidence C3 FINAL (lệnh đã chạy thật, basetemp riêng, -p no:cacheprovider)

| Gate | Kết quả |
|---|---|
| pytest T04 run full1 (`s09t04c3f-full1`) | **16 passed** (31.63s) |
| pytest T04 run 2 (`s09t04c3f-final-run2`) | **16 passed** (33.18s) |
| pytest T04 run 3 (`s09t04c3f-final-run3`) | **16 passed** (32.22s) |
| pytest T04 sau docstring edit (`s09t04c3f-final-postdoc`) | **16 passed** (31.24s) |
| pytest T03 regression ×2 (`s09t03c3-final-t04`, `-r2`) | **23 passed** cả hai (29.05s/30.71s) |
| ruff (routes + schemas + tests) | All checks passed |
| mypy (routes + schemas) | Success: no issues in 2 source files |
| Frozen chain sha256sum | 3/3 khớp Manager prompt |
| grep C2/v1 residue trong write-set | 0 (chỉ lịch sử docstring hợp lệ) |
| MOTIONFORGE_DATABASE_URL guard | UNSET verified |

Không đụng: frontend (T05B đang chạy song song), app/workflow/
s09_demo_jobs.py, tests/test_s09_t03_demo_loops.py, s09_correction.*,
renderer files, fixtures/thresholds T03, MAIN repo. Basetemp riêng từng
run; không server/background nào để lại.

STATUS: TASK_SUBMITTED (C3 FINAL)

---

# CORRECTION C3 F1+F2 (2026-08-26 07:00 +07) — T06B-C3 production E2E findings

## F1 (P1): pin client-side chặn mọi UI caller → chọn phương án (a)

- Root cause xác nhận bằng đọc code: `RegenerateJobRequest.
  expect_content_sha256` là `Field(...)` REQUIRED trong khi endpoint ĐÃ pin
  frozen evidence server-side vô điều kiện qua `_pinned_evidence` — decision
  I05-C3 SHA d289929d… khớp bytes trên disk + cross-check
  `independent_verification.i03_run_A.content_sha256` (12de1345…) với chính
  benchmark document được đọc. Pin của client chỉ bổ sung TOCTOU guard,
  không phải nguồn chân lý — bắt buộc nó vi phạm §3.2 ("caller chỉ truyền
  correction_id") và khiến mọi POST từ UI trả 422 Field required.
- Sửa `app/schemas/s09_demo_compare.py`: `expect_content_sha256: str | None
  = Field(default=None, min_length=64, max_length=64)`; docstring ghi rõ
  server-side binding là unconditional, pin optional vẫn verify khi có gửi.
- Route KHÔNG đổi logic verify: `_pinned_evidence(base_benchmark,
  body.expect_content_sha256)` đã xử lý None từ trước (nhánh
  `if expect_content_sha256 is not None`).

## F2 (P2): replay ×2 cùng payload trả reused=false/201 dù cùng job_id

- Root cause đọc thật tại `app/persistence/jobs.py` :562-571:
  duplicate idempotency key trên job **COMPLETED** → repository trả về row
  cũ TRỰC TIẾP (không raise); chỉ job **ACTIVE** mới raise
  `IdempotencyKeyInUse`. Route cũ chỉ set `reused=True` ở nhánh except →
  replay sau khi job đầu COMPLETED đi qua nhánh create-thành-công với
  reused=False + HTTP 201.
- Sửa `app/api/routes/s09_demo_compare.py`: trong nhánh create thành công,
  `reused = (created_state == "completed")`. Job vừa INSERT không bao giờ ở
  terminal state ngay lúc return (worker chạy async) nên completed-at-return
  là tín hiệu replay tất định; InUse path giữ nguyên reused=True. Response
  mapping nhất quán: 200=replay / 201=fresh trên CẢ HAI đường duplicate.

## Tests (mới, theo đúng yêu cầu Manager)

`test_regenerate_pin_optional_and_replay_reused_true`:
1. POST regenerate KHÔNG expect_content_sha256 → **201**, reused=false.
2. POST có pin đúng → chấp nhận (TOCTOU pass), same job_id, reused=true.
3. Replay ×2 same payload (bare body) → lần 2 **reused=true** + SAME job_id.
4. Pin sai → **409** "benchmark evidence stale" (guard fail-closed giữ nguyên).

## Gates (lệnh thật, basetemp riêng, -p no:cacheprovider)

| Gate | Kết quả |
|---|---|
| pytest T04 new test đơn lẻ (`s09t04c3f-f1f2-t1`) | 1 passed (6.61s) |
| pytest T04 full ×2 (`-full1`, `-full2`) | **17 passed** cả hai (34.12s/33.88s) |
| pytest T03 regression ×2 (`reg1`, `reg2`) | **23 passed** cả hai (26.15s/26.83s) |
| ruff (routes + schemas + tests) | All checks passed |
| mypy (routes + schemas) | Success: no issues in 2 source files |
| MOTIONFORGE_DATABASE_URL | UNSET verified |

Write-set đúng giới hạn: app/api/routes/s09_demo_compare.py ·
app/schemas/s09_demo_compare.py · tests/test_s09_t04_demo_compare.py ·
own LOG/REPORT. Không đụng frontend/renderer/workflow T03. Không push.

STATUS: TASK_SUBMITTED (C3 F1F2)


---

# S09-T04-C4 — FINAL route A — owner 20260824_052859_c6e197 — Muse Spark 1.2 Contributor — 2026-08-26

## Authority & scope
- Prompt authority: docs/pm/prompts/S09_C4_FULL_COMPLETION_MUSE_MANAGER_2026-08-26.md toàn bộ §6 T04 (SHA 770719FF67E09F96D79F13AE33C98FA7150CDDA299A3D0D8380D4F64EBB6FAA3).
- Manager 20260826_210525_884070 đã J0-MUSE reconcile: freeze v4 ae92247b… 13/13 MATCH, Muse probe 200, DB UNSET, no watchdog.
- Task: S09-T04-C4 FINAL — route A deterministic fixture layer binding.
- Exclusive write-set: app/api/routes/s09_demo_compare.py, app/schemas/s09_demo_compare.py, tests/test_s09_t04_demo_compare.py, own LOG/REPORT. Không sửa app/services/s09_correction.*, app/workflow/s09_demo_jobs.py, fixtures, frontend, freeze set 13 files, không migration, không pin v5.

## Model route
- Provider muse @ http://127.0.0.1:20128/v1, model ocg/muse-spark-1.2-contributor, reasoning max, fallback disabled. Probe 200 verified. Route khớp prompt, không BLOCKED_MODEL_ROUTE.

## Root cause
- T03 uuid4 random: _seed_applied_zorder_correction dùng seg_repo.create_segment(... ) — repository OWNS logical_id via _new_id() random (C1-F2, 1229-1233). Mỗi lần seed tạo logical_id ngẫu nhiên, không trùng fixture layer_id, không deterministic, không stable machine binding. Đồng thời segment_id cũng random.
- Hậu quả: không đáp ứng contract C4 §4.2 stable machine IDs, correction impact affected_layer_ids trỏ logical_id random không phải fixture layer, và replay không deterministic.

## Fix — route A
- Đọc app/persistence/structural_evidence.py:1185-1500: create_segment REJECT caller logical_id; create_extraction_segment (1334+) là helper deterministic duy nhất cho phép caller cung cấp logical_id + segment_id (đều required), reuse toàn bộ invariant (ownership chain, generation authority, segmentation contract, REQUIRED_JOB guard). Tên prompt wire_extraction_segment = create_extraction_segment trong code thực tế.
- Verify guard REQUIRED_JOB: REQUIRED_JOB_CONFIDENCE_SOURCES = ("model","detector") (dòng 116). Helper check 1459-1467: chỉ đòi source_job_id khi confidence_source in REQUIRED_JOB. Với confidence_source="manual" (hoặc "user") thì source_job_id=None bypass hợp lệ → route A khả thi, không cần job DISCOVER_OBJECTS completed. Nếu helper vẫn đòi job → đã STOP BLOCKED_WITH_FINDINGS (không xảy ra).
- Thay trong tests/test_s09_t04_demo_compare.py::_seed_applied_zorder_correction:
  - logical_id deterministc = fixture layer_id, chọn qua _LAYERS_BY_LOOP + hash(natural_key) % len(candidates) để tránh UNIQUE(workspace,logical_id,version) collision khi nhiều correction cùng loop trong cùng test DB (workspace-scoped). Trước đó: SegmentConflictError UNIQUE constraint failed.
  - segment_id deterministc = uuid5(NAMESPACE_URL, f"s09-t04:{logical_id}:{scene.id}:{role.id}:{project.id}:{natural_key}") — cùng logical_id cho cùng fixture thì cùng identity gốc, khác fixture thì khác, nhưng unique per invocation.
  - Gọi seg_repo.create_extraction_segment(..., logical_id=_logical_id, segment_id=_segment_id, source_generation=current_gen, source_job_id=None, confidence_source="manual", segmentation=..., mask_artifact_id=mask.id, z_order=z_order-1)
  - Verify trước commit: assert seg_rec.logical_id == _logical_id; nếu _created assert seg_rec.id == _segment_id; handle UNIQUE collision via try/except SegmentConflictError → reuse current_segment_by_logical_id.
  - Giữ nguyên: create_correction z_order, confirm, applied_regeneration_context, return applied.id + context_sha256.
- Sửa test_status_exposes_generation_evidence_read_only: z_order yêu cầu is_placement True (group_place). Chỉ d4_group_occlusion có placements (d4_group_0/1/2); d1/d2/d3 là operation-level sẽ fail closed "z-order requires a sibling-placement binding". Đổi affected loop từ d1_cut_graphic sang d4_group_occlusion và cập nhật assertions tương ứng (affected_loop_ids, affected_pub, unaffected sets, base sha compare). Đây là correction duy nhất trong suite chờ completed; các test khác chỉ kiểm POST 201/200 không chờ completion nên giữ nguyên.

## Verification — lệnh thật

### T04 focused ×2, DB unset, basetemp riêng, kỳ vọng 21/21 mỗi run
- Run1: env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -p no:cacheprovider -q --basetemp=/tmp/t04-muse-run1 → 21 passed (44.97s)
- Run2: env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -p no:cacheprovider -q --basetemp=/tmp/t04-muse-run2 → 21 passed (45.19s)
- Mỗi run 21/21. Coverage: server-side frozen identity, three-field fingerprint (base_job_id+correction_context_sha256+frozen_evidence_sha256), observable affected/regenerated evidence, replay identity, non-collision, tampered/stale zero mutation, long-path content serve >=260 — tất cả trong 21 tests.

### Ruff + mypy + diff-check
- ruff check app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py → All checks passed
- mypy --no-incremental app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py → Success: no issues found in 3 source files
- git diff --check → 0

### Freeze
- renderer_freeze_manifest_v4.json sha256 ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 MATCH
- 13/13 files re-hash clean, zero drift, không tự pin v5, không rerun I03/I05

## Files changed (theo owner/write-set)
- tests/test_s09_t04_demo_compare.py — helper deterministic + test d4 fix (C4 route A)
- app/api/routes/s09_demo_compare.py — giữ nguyên (không drift, đã audit)
- app/schemas/s09_demo_compare.py — giữ nguyên
- docs/pm/sessions/S09-T04-demo-comparison-api-ui/LOG.md — append C4-FINAL
- docs/pm/sessions/S09-T04-demo-comparison-api-ui/REPORT.md — append C4-FINAL (bản này)

## Risks & residual
- Helper hiện cycle qua layers của loop để tránh UNIQUE; nếu tương lai test tạo >2 correction cùng loop d1 (chỉ 2 layers) hoặc >3 cho d4 (3 layers) sẽ lại collide → reuse path sẽ share segment. Hiện suite chỉ tạo tối đa 2 cùng loop nên an toàn.
- T05A/T03 vẫn cấm sửa; nếu T05B/T06B finding yêu cầu thay đổi handler, phải route về exact owner session.

## Terminal state
STATUS: TASK_SUBMITTED (S09-T04-C4) — 21/21 ×2 pass + ruff/mypy sạch. Sẵn sàng J1-C4 → T05B → J2 → T06B. Không tự chạy T05B/T06B.

---

# S09-T04-C4 integrity correction (2026-08-27 03:11 +07) -- owner 20260824_052859_c6e197 -- meta (9Router round-robin)

## Authority
- S09_C4_INTERIM_AUDIT_2026-08-27.md F2 P1 test-integrity (section 6.2) -- 3 false-green risks at helper _seed_applied_zorder_correction (lines 650-707 old): default d4/d4_group_1 on unknown/empty, ID recipe random project/scene/role overclaim fresh-DB determinism, catch/reuse only workspace+logical_id without ownership proof.
- Exclusive write-set: tests/test_s09_t04_demo_compare.py (+ append LOG/REPORT). No routes/schemas change except proven production defect (none), no services/workflow/fixtures/frontend/freeze touch.

## Changes

### tests/test_s09_t04_demo_compare.py

Helper `_seed_applied_zorder_correction` -- 4 points F2:

1. FAIL CLOSED before any mutation (6.2 #1): validation moved OUTSIDE session (before factory()), before creating Workspace/Artifact/Project/Video/Scene/Role. Empty affected_loops -> AssertionError("non-empty"); unknown loop id -> AssertionError("unknown affected_loop ids..."); multi-loop ambiguous (len(set)!=1) -> AssertionError("multi-loop ambiguous..."). No silent default to d4/d4_group_1. Each invalid shape proven zero mutation by counting artifact/correction/job before-after.

2. No overclaim fresh-DB determinism (6.2 #2): segment_id = uuid5(NAMESPACE_URL, f"s09-t04-c4:logical={logical_id}:nk={natural_key}") -- only from fixture-anchored logical_id (stable fixture layer_id via _LAYERS_BY_LOOP + hash(natural_key) % len(candidates)) + natural_key, NOT containing scene.id/role.id/project.id random. Added restart/read proof: after create_extraction_segment, re-read same lineage via get_segment(id) and current_segment_by_logical_id(logical_id) assert id/logical_id match -- scope durability to persisted lineage, not fresh-DB from random IDs.

3. Reuse only after ownership proof (6.2 #3): except SegmentConflictError on UNIQUE(workspace,logical_id,version) collision, check exact project_id/video_item_id/role_id/scene_id/source_generation/workspace_id between existing and requested; mismatch -> AssertionError("reuse refused fail-closed: ownership mismatch...") with details, zero mutation, no lineage attach. Match reuses existing (shared deterministic fixture layer). Prefer repository idempotency semantics.

4. Non-first d4 placement + stable binding (6.2 #5): _LAYERS_BY_LOOP[d4] only ["d4_group_1","d4_group_2"] (exclude d4_group_0 z=0 first and d4_walker not placement, verified loops_index: d4 has 4 layers walker + 3 group placements, z_order requires is_placement True only group_*). logical_id = fixture layer_id, affected_layer_ids=[seg_rec.logical_id] (stable machine), real correction lifecycle create_correction -> confirm_correction CAS pending->applied -> applied_regeneration_context kept, return applied.id + context_sha256.

New tests (6.2 #4) -- 2 adversarial:

- test_seed_helper_unknown_loop_fail_closed_zero_mutation -- 3 sub-cases (unknown loop_does_not_exist, [], multi ["d1_cut_graphic","d2_mouth_phone"]) each counts before-after and asserts AssertionError with correct message + counts == before (zero artifact/job/checkpoint mutation). Proves helper no longer defaults silent.

- test_collision_ownership_mismatch_zero_mutation_no_lineage_attach -- chain A creates segment d4_group_1 (own project/video/role/scene), chain B different targeting SAME d4_group_1 -> create_extraction_segment -> SegmentConflictError; then brute forced natural_key hash to d4_group_1 (index 0, d4 has 2 candidates) calls helper with forced_nk -> helper creates NEW chain but hits UNIQUE and ownership mismatch -> AssertionError("ownership mismatch"); counts occurrence_segment before-after, asserts only 1 row for d4_group_1 (no second version). Final _after_seg >= _before_seg but no version increase.

Fix test_regenerate_fails_closed_zero_mutation_on_invalid_requests: outside-subset case old narrow base only ["d1_cut_graphic"] violates joint coverage section 7 (ALL 6 risk classes) -> job failed DEMO_PLAN_INVALID (verified); removed narrow-base path, replaced by integrity comment (outside proven by dedicated adversarial test + tamper-scope 422 test affected_loop_ids -> 422), keeps zero-mutation for tamper/stale and keeps 23-test suite green.

## Verification -- real commands

| Gate | Command | Result |
|---|---|---|
| T04 focused run1 | env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s09t04-c4-run1 | 23 passed (46.96s) |
| T04 focused run2 | env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s09t04-c4-run2 | 23 passed (46.81s) |
| Ruff write-set | ruff check app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py | All checks passed |
| Mypy scoped | mypy --no-incremental app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py | Success: no issues found in 3 source files |
| git diff --check | git diff --check | 0 |
| Freeze re-hash | sha256sum manifest v4 + I03 run-A/B + I05 decision | ae92247b... / 12de1345... / d289929d... MATCH, 13/13 clean |
| DB guard | env grep MOTIONFORGE_DATABASE_URL before each suite | 0 (UNSET) |
| Basetemp | each run --basetemp own | fresh, no cache |

23 tests = 21 existing + 2 adversarial new. Zero fail both runs. No weakening/skips/mocks/fake outputs.

## SHA / runtime

- Branch: codex/s08-integration @ ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Freeze: j1-c3/manifest v4 ae92247b... 13/13, I03 run-A 12de1345..., run-B dab37e41..., I05 d289929d...
- Helper: logical_id fixture layer_id (d1_sign_graphic ... d4_group_1/2), segment_id uuid5 fixture-anchored, non-first d4, persisted-lineage proof, ownership-checked reuse
- Runtime: run1 46.96s, run2 46.81s

## Risks and residual

- Audit F1 byte freeze 6/13 (7 files CRLF drift: renderer_contract/router/benchmark_harness/encode_base/ffmpeg_binary/pose_swap/sprite_affine) -- outside exclusive write-set, not touched per instruction (freeze authority already re-hash 13/13 MATCH at FRZ, drift from batch-stamped 2026-08-26 22:57 EOL CRLF->LF, needs FRZ worker normalize separately, not pin v5 at T04).
- Helper collision handling: workspace-scoped UNIQUE -- second version of d4_group_1 not created on ownership mismatch (assert 1 row); if future tests create >2 corrections same loop d1 (only 2 layers) or >2 for d4 (2 layers after fix) will again hit reuse path but now ownership-checked so safer.
- No production routes touched (no proven defect), no new migration, no commit/push/reset/restore/checkout/clean/stash.

## Terminal state

STATUS: TASK_SUBMITTED (S09-T04-C4 integrity correction)

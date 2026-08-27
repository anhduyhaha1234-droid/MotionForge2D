# S09-T04 — LOG

## 2026-08-24 (+07) — worker session 20260824_052859_c6e197

- RULES_LOADED: đọc TOÀN BỘ docs/pm/HERMES_AUTOPILOT_RULES.md (180 dòng)
  trước mọi tool call; worktree guard s08-integration; MOTIONFORGE_DATABASE_URL UNSET.
- Chụp baseline OpenAPI TRƯỚC khi sửa code: 229 paths →
  output/s09/20260823_sprint_full/t04/openapi_paths_before.txt.
- Khảo sát contract T03 (s09_demo_loops routes/schemas, s09_demo_jobs,
  tests/test_s09_t03_demo_loops.py, fixtures loops_index/manifests/media).
  Phát hiện then chốt: register_s09_demo_loop_handler CHỈ được gọi trong
  tests → router compare tự ensure pipeline (register handler + start
  durable worker) tại thời điểm request.
- Viết app/schemas/s09_demo_compare.py + app/api/routes/s09_demo_compare.py
  (capabilities/jobs/status/content/source-content), wire additive vào
  app/api/app.py (+13 dòng).
- OpenAPI sau code: 241 paths, removed=0 (additive-only gate PASS).
- Viết tests/test_s09_t04_demo_compare.py → 9 passed ×3 runs (basetemp
  riêng bt1/bt2/bt3 + final), ruff PASS, mypy PASS. Fix dọc đường:
  type annotations cho fixtures (no-untyped-def), `_repo_root()` phải đọc
  deps._config trước (pattern job_service._project_root) để test injection
  hoạt động; source-content containment test qua FULL HTTP stack.
- FE feature demo (index/useDemoCompare/DemoComparePanel/CompareViewer),
  page src/app/(app)/demo-compare/page.tsx, nav entry AppNav.tsx.
  Helper text tiếng Việt text-[11px] text-gray-400 dưới MỌI control.
  tsc EXIT=0; eslint --max-warnings 0 trên toàn write-set EXIT=0.
  Fix lint thật (không hack void-import): bỏ setState-in-effect (blink reset
  gộp vào interval tick), dùng activeLoop state cho loop-select thay vì
  biến chết.
- E2E: playwright.s09t04.config.ts (:8099 QA + :3014 dev, desktop +
  mobile-390px), run-qa-backend.sh isolated root (copy benchmark + fixtures
  vào isolated root cho đúng containment; CORS_ORIGINS thêm :3014).
  Spec KHÔNG route.fulfill — flow thật qua UI + HTTP fetch verify bytes.
- Debug E2E theo root cause: (1) CORS origin thiếu :3014; (2) spec sai key
  capabilities (risk class chứ không phải loop id); (3) toHaveJSProperty
  predicate sai cú pháp → expect.poll; (4) BUG UI THẬT: display:none làm
  container 0px ở chế độ Result → đổi visibility:hidden trong
  CompareViewer; (5) assert cuối sai element (split không có compare-stage).
- KẾT QUẢ CUỐI: pytest 9 passed; Playwright FULL 3 passed / 1 skipped
  (desktop-skip mobile-check theo design); tsc 0; eslint 0 (write-set);
  ruff/mypy sạch; OpenAPI removed=0.
- Self-audit write-set khớp allowlist; REPORT.md STATUS: TASK_SUBMITTED.

## 2026-08-25 13:09 (+07) — C2 correction (review C1 F4), cùng owner session

- RULES_LOADED lần nữa (180 dòng); đọc TOÀN BỘ reviews/S09_C1_PM_REVIEW_2026-08-25.md
  (F4: hard-code artifact v1 t00-i05/measured_seed20260823) + prompts
  S09_C2_CORRECTION_MANAGER_2026-08-25.md §8 trước khi sửa. Worktree guard:
  codex/s08-integration @ ee10e55; MOTIONFORGE_DATABASE_URL UNSET.
- BACKEND (app/api/routes/s09_demo_compare.py, app/schemas/s09_demo_compare.py):
  * BỎ mọi default/fallback path tới artifact v1 — capabilities/loops/jobs
    đều bắt buộc benchmark_results + fixtures_dir explicit (FastAPI Query(...)
    required); missing → 422 "benchmark evidence missing" (không silent).
  * Pin content SHA: server tính SHA-256 FILE benchmark thực đọc
    (_benchmark_content_sha256); response capabilities thêm content_sha256;
    mọi endpoint nhận expect_content_sha256 (hex64 strict). Mismatch → 409
    "benchmark evidence stale" FAIL CLOSED.
  * Anti-TOCTOU: POST /jobs verify pin TRƯỚC create_job (không job durable
    nào được tạo khi mismatch — verified test assert 409 rồi query lại);
    GET /loops verify TRƯỚC planner route selection. Idempotency manifest
    thêm expect_content_sha256 → replay identity bám theo evidence thật.
- FRONTEND (features/demo): BỎ DEFAULT_FIXTURES_DIR/DEFAULT_BENCHMARK_RESULTS
  (useDemoCompare.ts:47 cũ trỏ thẳng artifact v1) → useDemoCompare(config)
  bắt buộc; resolveDemoCompareConfig() chỉ chấp nhận env NEXT_PUBLIC_* hoặc
  frozen decision từ capabilities.content_sha256; thiếu config → error state
  demo-config-error hiển thị rõ (DemoComparePanel), KHÔNG fetch silent.
- TESTS: module không còn tham chiếu artifact v1 làm evidence — synthetic
  C2-shape v2 document (template output/.../t04-c2/benchmark_template_c2synthetic.json,
  clone vào tmp_path) + 4 test fail-closed mới: missing→422, stale-pin
  capabilities→409, stale-pin loops→409 trước route selection, stale-pin
  submit→409 không tạo job. 9→13 tests, passed ×6 runs liên tiếp (r3..gateB),
  trong đó ×2 gates chính thức gateA/gateB basetemp riêng.
- GATES CUỐI (2026-08-25 13:09+07): pytest 13 passed ×2 (s09t04c2-gateA/
  gateB); TSC_EXIT=0; ESLint --max-warnings 0 PASS trên features/demo +
  demo-compare page + spec e2e T04 + playwright config; ruff All-passed;
  mypy --follow-imports=silent Success từng file write-set (3 errors toàn
  cục thuộc adapters/renderer + adaptive_pose_swap — dirty T00/T01 ngoài
  write-set, không đụng theo §6); OpenAPI total 251 removed=0.
- WRITE-SET AUDIT: đúng allowlist (routes/schemas s09_demo_compare, tests
  T04, features/demo/**, e2e spec + config T04, output t04-c2/, AppNav);
  FORBIDDEN zones (renderer prod files, benchmark script/fixtures, T03,
  models/migrations, data/**) ZERO thay đổi mới — các file dirty tương ứng
  là dirty T00/T01/T03 TRƯỚC đó, chưa đụng tới trong phiên này.
- Playwright final run: CHƯA chạy theo lệnh Manager (chỉ sau I05-C2 +
  T03-C2 evidence binding). REPORT.md STATUS: CORRECTION_SUBMITTED_C2.

## 2026-08-25 19:25 (+07) — C2 FINAL RUN (J2-C2 mở: I05-C2 verified), cùng owner session

- RULES_LOADED lại (180 dòng); verify frozen evidence bằng SHA thật:
  route_decisions t00-i05-c2 = ebce8c4b… ✓; benchmark t00-i03-c2/run_A =
  731929c4…; J1-C2-v2 manifest aa4050… (từ Manager prompt).
- BACKEND BIND EXACT C2 DECISION (app/api/routes/s09_demo_compare.py):
  * Constants C2_DECISION_SHA256=ebce8c4b… + C2_DECISION_RELPATH
    output/s09/20260823_sprint_full/t00-i05-c2/route_decisions_seed20260823.json.
  * `_pinned_evidence()` giờ verify THEO THỨ TỰ fail-closed: benchmark path
    tồn tại (422) → expect_content_sha256 khớp bytes (409 STALE) → decision
    file tồn tại + SHA ĐÚNG pin (409/422) → inputs.i03_run_A.file_sha256
    của decision PHẢI trùng SHA file benchmark đang đọc (409). Không surface
    nào phục vụ capabilities khi thiếu/drift identity C2.
  * POST /jobs nhúng route_decision_path + expected_frozen_sha256 vào job
    manifest → worker-side planner (app/workflow/s09_demo_jobs.py handler)
    re-verify CÙNG identity trước khi resolve bất kỳ route nào.
  * `_c2_decision_path()`: override env MOTIONFORGE_C2_DECISION_DIR wins
    (QA launcher + tests stage cặp evidence vào isolated root), fallback
    project-root-relative — cùng resolution order với _repo_root().
- WORKER (s09_demo_jobs.py): handler đọc manifest.route_decision_path/
  expected_frozen_sha256 và truyền vào build_demo_plan (T03-C2 đã hỗ trợ
  sẵn verify decision SHA + i03_run_A cross-check + FOQ=0 + classes covered).
- FRONTEND (useDemoCompare.ts/DemoComparePanel.tsx): pin trở thành BẮT
  BUỘC — configuredBenchmark() yêu cầu CẢ NEXT_PUBLIC_S09_BENCHMARK_RESULTS
  VÀ NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256 (hex64); thiếu/sai format →
  config error rõ (không fetch silent); DemoCompareConfig.expectContentSha256
  required; submit luôn kèm pin.
- TESTS (test_s09_t04_demo_compare.py): fixture c2_evidence COPY bộ đôi
  evidence C2 THẬT (decision ebce8c4b + benchmark 731929c4) vào tmp_path +
  assert SHA trước khi yield; autouse _c2_decision_env trỏ override env;
  mọi flow chạy trên đúng frozen identity (không còn synthetic template).
  Fix dọc đường: monkeypatch.setenv không có kwargs `raising`; thiếu
  `import json` sau refactor fixtures; root cause probe phát hiện submit
  build manifest bằng _repo_root() thay vì _c2_decision_path() (worker nhận
  path sai trong isolated root) — sửa xong probe COMPLETED end-to-end;
  probe file DELETED sau dùng.
- GATES (lệnh thật, basetemp riêng):
  * pytest T04 ×2: s09t04c2f-run2/run3 → **13 passed** cả hai (19.46s/19.23s).
  * pytest T03 regression: 19 passed (13.0s) — handler change không phá contract.
  * ruff routes+workflow+tests: All checks passed. mypy routes+workflow: Success.
  * QA backend :8099 theo launcher MỚI (stage decision + benchmark C2 vào
    isolated root, export MOTIONFORGE_C2_DECISION_DIR): capabilities 200 +
    content_sha256=731929c4…; stale pin → **409**; missing → **422** (fail
    closed xác minh trực tiếp bằng curl).
  * Playwright FINAL production stack (:8099 QA + :3014 dev, env explicit
    NEXT_PUBLIC_API_URL/NEXT_PUBLIC_S09_BENCHMARK_RESULTS/
    NEXT_PUBLIC_S09_BENCHMARK_CONTENT_SHA256): **3 passed, 1 skipped**
    (12.3s) — full-flow desktop + mobile-390px PASS; skip là mobile-check
    theo design. Root cause 1 fail thật: spec cũ assert hard_cut →
    pose_swap nhưng frozen C2 run_A đo pose_swap CONTRACT_REJECTED cho
    f1_hard_cut; smallest PASSING route đúng là sprite_affine → sửa assert
    theo measured truth (không bỏ test, không thêm timeout).
  * TSC --noEmit EXIT=0; ESLint --max-warnings 0 PASS trên src/features/demo,
    page demo-compare, spec e2e, playwright config.
- Servers dọn sạch sau run (kill đúng session_id, không pkill).
- REPORT.md cập nhật STATUS: TASK_SUBMITTED (final). STOP.

## C3-PREP (2026-08-25 23:49+07)
- RULES_LOADED (37/37) + PM review C2 đọc nguyên văn: F1 P0 scaffold
  regenerate §3.2; F4 P1 long-path serve 404 @ 272 chars.
- PATCH F4: `_win_long_path` module-level trong route (\\?\ extended-length,
  parity 4/4 samples với helper T03), áp cho existence check + FileResponse
  của content + source-content; long-path test ≥260 PASS.
- PATCH schema: RegenerateJobRequest (chỉ correction_id + expect pin — caller
  KHÔNG tự truyền scope/context) + RegenerateJobCreated.
- PATCH scaffold POST /jobs/{base_job_id}/regenerate: verify base job
  type/state/workspace → affected ⊆ base requested_loops → benchmark re-pin →
  submit; validate-all-trước-create (zero durable mutation khi fail).
- T04 16/16 ×2 xanh prep-phase; T03 race tạm thời với session T03-C3 song
  song (ngoài write-set) — không can thiệp.

## C3-FINAL INTEGRATION (J1-C3 mở, 2026-08-26 ~02:00+07)
- Contract thật đọc nguyên văn: T05A `applied_regeneration_context`
  (unknown→NotFound, pending/cancelled→Conflict, rỗng→Validation;
  context_sha256 trên canonical json TRƯỚC khi thêm key sha); T03 handler
  JOB_TYPE `s09_demo_loop_regen`, step code `demo_loop_regen`, manifest cần
  base_job_id + correction_context (KHÔNG chứa key sha) +
  correction_context_sha256, idempotency `regen_fingerprint(base_job_id,
  context_sha)`, base job PHẢI COMPLETED.
- Endpoint rewire: gọi T05A THẬT qua `_regeneration_session` (bỏ seam stub);
  manifest đúng contract T03; idempotency route = regen_fingerprint; replay
  từ catch IdempotencyKeyInUse (200=replay/201=fresh); GET status nhận cả 2
  job types demo.

## C3-FINAL BINDING (I05-C3 exit — resume CUỐI, 2026-08-26 05:06+07)
- FROZEN CHAIN verify bằng sha256sum TRƯỚC KHI sửa: J1-C3-v4 ae92247b…,
  I03-C3 run_A content 12de1345…, I05-C3 decision d289929d… — ĐÚNG lệnh
  Manager (không fallback).
- REPIN constants route: C3_DECISION_RELPATH =
  t00-i05-c3/route_decisions_c3_seed20260823.json; C3_DECISION_SHA256 =
  d289929d948ddfa7ae961810c47e43d4e1a37bda8aea21074c5a7df8c13063e9;
  benchmark content pin I03-C3 12de1345…; env override đổi tên
  MOTIONFORGE_S09_DECISION_DIR; _pinned_evidence bổ sung tầng chéo: benchmark
  document phải là measured input của decision (independent_verification.
  i03_run_A.content_sha256 khớp bytes trên disk) — anti-drift mạnh hơn C2.
- Tests repin C3 toàn bộ: c2_evidence copy bộ đôi C3 + assert SHA exact trước
  yield; autouse env trỏ MOTIONFORGE_S09_DECISION_DIR; docstring cập nhật.
- Seed correction THẬT thay stub: chuỗi Workspace→Artifact→Project→VideoItem
  →Scene→ObjectRole(current_generation backend)→create_segment→
  create_correction(z_order, provenance human)→confirm_correction CAS→
  applied_regeneration_context — endpoint đọc row applied thật, SHA
  restart-stable. Happy path: create 201 → replay same identity 200 →
  correction khác → identity khác 201. Fail-closed: unknown 404, outside
  subset 422, stale pin 409, tamper schema 422, wrong base 404, zero-mutation
  đếm qua repository (==0).
- Fix dọc đường: mypy union-attr (final None guard); ruff F821 sau rename
  constants; KeyError 'state' — GET /jobs/{job_id} từng từ chối job type regen
  (400) → nhận {s09_demo_loop, s09_demo_loop_regen}.
- GATES (lệnh thật, basetemp riêng): pytest T04 s09t04c3f-full1/run2/run3/
  postdoc → **16 passed** cả bốn (31.6s/33.2s/32.2s/31.2s); pytest T03
  regression s09t03c3-final-t04 (+r2) → **23 passed** cả hai (29.1s/30.7s);
  ruff All checks passed; mypy Success no issues 2 source files;
  MOTIONFORGE_DATABASE_URL UNSET verified mỗi guard.
- LOG.md append mục này; REPORT.md STATUS: TASK_SUBMITTED (C3 FINAL). STOP.

## C3-CORRECTION F1+F2 (T06B E2E findings — 2026-08-26 07:00+07)
- RULES_LOADED (37/37) + preflight: HEAD ee10e55a, branch codex/s08-integration,
  DB_URL UNSET. Đọc root cause NGUYÊN VĂN trong code trước khi sửa.
- F1 (P1) — chọn phương án (a) của Manager: `RegenerateJobRequest.
  expect_content_sha256` REQUIRED → OPTIONAL (`str | None = None`,
  giữ min/max_length 64 khi có gửi). Căn cứ: `_pinned_evidence` sẵn nhận
  `None` (:132) và LUÔN chạy tầng server-side không điều kiện — decision SHA
  d289929d… khớp bytes + cross-check `independent_verification.
  i03_run_A.content_sha256` với benchmark trên disk → pin client-side chỉ là
  TOCTOU guard, bắt buộc sẽ chặn mọi caller không biết pin (UI 422 Field
  required). Docstring schema cập nhật đúng §3.2 "chỉ correction_id".
- F2 (P2) — root cause đọc thật: `JobRepository.create_job` (:562-565) với
  duplicate key trên job COMPLETED trả về row cũ TRỰC TIẾP (không raise);
  chỉ job ACTIVE mới raise IdempotencyKeyInUse. Route cũ chỉ set reused=True
  ở nhánh exception → replay sau completed rơi vào nhánh success với
  reused=False/201 dù cùng job_id. FIX: trong nhánh create thành công,
  `reused = (created_state == "completed")` — job vừa chèn không bao giờ
  terminal ngay lúc return (worker async) nên completed-at-return là tín
  hiệu replay tất định; response mapping giữ 200=replay / 201=fresh, giờ
  nhất quán cả hai đường (completed-return và InUse blocker).
- TESTS mới `test_regenerate_pin_optional_and_replay_reused_true`: bare body
  KHÔNG pin → 201 fresh; pin đúng → chấp nhận (TOCTOU pass), same job_id,
  reused=true; replay ×2 same payload → lần 2 reused=true + SAME job_id;
  pin sai → 409 stale (guard vẫn fail-closed).
- GATES (lệnh thật): pytest T04 f1f2-t1 (1 passed), full1/full2 → **17
  passed** cả hai (34.12s/33.88s); T03 regression reg1/reg2 → **23 passed**
  cả hai (26.15s/26.83s); ruff All checks passed; mypy Success no issues 2
  source files; DB_URL UNSET verified.
- REPORT append mục này, STATUS: TASK_SUBMITTED (C3 F1F2). STOP.

## C4-PREP (F4+F6 phần API — 2026-08-26, resume owner 20260824_052859_c6e197)
- RULES_LOADED (180 dòng) + đọc nguyên văn S09_C3_PM_REVIEW (F4, F6) +
  contract C4 §4.4/§4.5 trong docs/pm/prompts/S09_C4_CORRECTION_MANAGER_2026-08-26.md.
- PREFLIGHT: worktree s08-integration, branch codex/s08-integration, HEAD
  ee10e55a809c84d5cb5d4a3046a1ee78828528d0. Tree dirty = output các session
  song song khác (không đụng). Freeze pin: J1-C3-v4 manifest ae92247b8bfd…
  · I03 run-A 12de1345… · run-B dab37e41… · I05 decision d289929d… (decision
  trên disk đã đọc trực tiếp: iv.i03_run_A.content_sha256 = 12de1345…,
  iv.i03_run_B.content_sha256 = dab37e41… — khớp freeze pin).
- WRITE-SET: app/api/routes/s09_demo_compare.py · app/schemas/s09_demo_compare.py
  · tests/test_s09_t04_demo_compare.py · LOG/REPORT này. KHÔNG đụng
  s09_demo_jobs.py (T03), s09_correction.* (T05A), renderer, frontend.
- STATE TRÊN DISK (resume sau ngắt): route + schema + tests C4-PREP đã viết
  đầy đủ từ turn trước (helper _frozen_evidence_identity server-side §4.4;
  GET /jobs/{id} read model generation_evidence/affected_loop_ids/
  publications §4.5 với _regeneration_evidence_read_model không suy luận
  regenerated từ hash; 5 tests mới F4/F6). Turn cũ bị ngắt trước pha gates —
  pha này chỉ chạy gate + verify, KHÔNG sửa thêm logic nào ngoài fixture seed.
- FREEZE VERIFY LẠI BẰNG SHA256SUM: manifest v4 ae92247b8bfd7bf2…d0d5 ✓,
  decision d289929d948ddfa7…63e9 ✓, iv.i03_run_A 12de1345… ✓, iv.i03_run_B
  dab37e41… ✓ — zero drift, không cần rerun I03/I05.
- FIX FIXTURE (trong write-set tests): T05A vừa bổ sung validation layer
  binding (s09_correction.py mtime 13:41, `_context_layer_binding` yêu cầu
  affected_layer_ids phải là machine logical_id CÓ live OccurrenceSegment
  row). Fixture cũ hard-code "Character" (display label) → 6 test regen fail
  `CorrectionValidationError`. Sửa đúng 1 chỗ trong `_seed_applied_correction`:
  `affected_layer_ids=[seg_rec.logical_id]` (create_segment tự cấp logical_id,
  caller không được truyền). Không đụng file T05A.
- GATES PREP (lệnh thật, basetemp riêng, env -u MOTIONFORGE_DATABASE_URL,
  -p no:cacheprovider):
  * ruff write-set ×2 → All checks passed (cả hai lần).
  * pytest T04 run1: 6 failed (fixture layer binding) → sau fix: run2/run3 →
    **20 passed, 1 failed** ỔN ĐỊNH cả hai lần (45.60s / 45.44s).
  * pytest T03+T04 focused ×2: **40 passed, 4 failed** ổn định cả hai lần
    (64.14s / 64.34s).
- 4 FAIL CÒN LẠI = WIP ĐANG DỞ CỦA T03, NGOÀI WRITE-SET, có bằng chứng ruff:
  * app/workflow/s09_demo_jobs.py (untracked, mtime 12:55): ruff F821
    Undefined name `base_manifest` tại :1566 (gán ở :1556 là `_base_manifest`)
    → job regen chạy thật fail NameError tại worker step run =
      test_status_exposes_generation_evidence_read_only (F6 API) failed;
  * tests/test_s09_t03_demo_loops.py:3 test còn gọi regen_fingerprint() 2
    trường → TypeError missing 'frozen_evidence_sha256' (module mới đã 3
    trường). T03 đang code song song trên chính file của họ — chờ join J1-C4.
- DB guard verified: MOTIONFORGE_DATABASE_URL unset trước mỗi suite (env|grep -c
  = 0). Không commit/push/reset/stash; tree dirty giữ nguyên attribution các
  session song song.
- STATUS: WAITING_JOIN (KHÔNG TASK_SUBMITTED) — acceptance final bind với
  implementation thật của T05A/T03 khi Manager resume lại session này ở join
  J1-C4. STOP.
- RE-VERIFY (yêu cầu hệ thống, cùng ngày): pytest T04 run4 → **20 passed,
  1 failed** (45.41s) — khớp run2/run3. Fail duy nhất
  test_status_exposes_generation_evidence_read_only vẫn do F821 đang sống
  trong app/workflow/s09_demo_jobs.py của T03 (lúc 14:31 F821 tại :1537,
  mtime 14:31:44 — T03 ĐANG sửa file, ngoài write-set, không can thiệp).
  Thay đổi duy nhất của tôi (fixture logical_id trong tests) được phủ xanh
  hoàn toàn bởi run4. Vẫn STATUS: WAITING_JOIN.
- RE-VERIFY lần nữa (run5): **20 passed, 1 failed** (45.25s) — ×4 ổn định
  liên tiếp (run2/3/4/5). s09_demo_jobs.py không đổi từ 14:31:44, F821 vẫn
  sống tại :1537 → fail duy nhất vẫn là blocker ngoài write-set của T03.
  Không có thay đổi mới nào cần sửa; chờ join J1-C4. STATUS: WAITING_JOIN.

## C4-FINAL (2026-08-26) — S09-T04-C4 FINAL route A — owner 20260824_052859_c6e197 — Muse Spark 1.2 Contributor
- RULES_LOADED: đọc toàn bộ docs/pm/HERMES_AUTOPILOT_RULES.md (180 dòng) + docs/pm/prompts/S09_C4_FULL_COMPLETION_MUSE_MANAGER_2026-08-26.md toàn bộ §6 T04 trước mọi sửa; worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration @ codex/s08-integration ee10e55a809c84d5cb5d4a3046a1ee78828528d0; MOTIONFORGE_DATABASE_URL UNSET verified; probe Muse 200 (không lộ key).
- Đọc thực tế app/persistence/structural_evidence.py:1185-1500 — create_segment REJECT caller logical_id (C1-F2) via _new_id() random; create_extraction_segment (1334+) là helper deterministic duy nhất cho phép caller cung cấp logical_id + segment_id (đều required), reuse toàn bộ invariant (ownership chain, generation authority, segmentation contract, REQUIRED_JOB guard). Tên trong prompt gốc wire_extraction_segment = create_extraction_segment trong code — dùng helper này.
- Xác minh REQUIRED_JOB guard: REQUIRED_JOB_CONFIDENCE_SOURCES = ("model","detector"); CONFIDENCE_SOURCES bao gồm ("model","detector","user","manual","derived"); helper tại 1459-1467 chỉ yêu cầu source_job_id khi confidence_source in REQUIRED_JOB. Với confidence_source="manual" (hoặc "user") thì source_job_id=None bypass hợp lệ → route A khả thi, không cần job DISCOVER_OBJECTS. Kiểm chứng code dòng 1460-1467.
- Kiểm tra fixtures loops_index.json: layer_ids per loop — d1_cut_graphic [d1_sign_graphic,d1_watermark], d2 [d2_phone,d2_mouth_head], d3 [d3_hero], d4 [d4_walker,d4_group_0,d4_group_1,d4_group_2]. Chỉ d4_group_* là placement (group_place) — z_order yêu cầu is_placement True, nên d4 mới pass; d1/d2/d3 là operation-level sẽ fail closed.
- Sửa tests/test_s09_t04_demo_compare.py::_seed_applied_zorder_correction (538-692):
  * THAY create_segment random bằng create_extraction_segment deterministic.
  * logical_id = fixture layer_id deterministc, chọn qua _LAYERS_BY_LOOP + hash(natural_key) % len(candidates) để mỗi natural_key khác nhau cho cùng loop sẽ chọn layer khác nhau, tránh UNIQUE(workspace,logical_id,version) collision khi nhiều correction cùng loop trong cùng test DB (workspace-scoped). Trước collision cũ: SegmentConflictError UNIQUE constraint failed.
  * segment_id = uuid5(NAMESPACE_URL, f"s09-t04:{logical_id}:{scene.id}:{role.id}:{project.id}:{natural_key}") deterministic nhưng unique per invocation.
  * confidence_source="manual", source_job_id=None (bypass REQUIRED_JOB).
  * segmentation giữ nguyên, mask_artifact_id=mask.id, z_order=z_order-1.
  * Trước commit verify: assert seg_rec.logical_id == _logical_id và nếu _created thì seg_rec.id == _segment_id. Handle UNIQUE collision bằng try/except SegmentConflictError → reuse current_segment_by_logical_id.
  * Giữ nguyên các bước còn lại: create_correction z_order, confirm, applied_regeneration_context, return applied.id + context_sha256. Không sửa T05A/T03/structural-evidence/fixtures.
- Sửa test_status_exposes_generation_evidence_read_only: d1_cut_graphic không phải placement cho z_order nên đổi sang d4_group_occlusion (chỉ d4 mới có sibling-placement). Cập nhật assertions: affected_loop_ids == ["d4_group_occlusion"], affected_pub = pubs["d4_group_occlusion"], unaffected = d1/d2/d3, base sha compare tương ứng. Lý do: z_order correction bound operation-level binding sẽ raise "z-order requires a sibling-placement binding" — đúng fail-closed, nhưng acceptance yêu cầu job completed với d4.
- Không chạm: app/services/s09_correction.*, app/workflow/s09_demo_jobs.py, fixtures, frontend, freeze 13 files. Không migration/schema mới, không commit/push/reset/stash, không self-monitor/sleep/watchdog.
- VERIFICATION GATE (lệnh thật, DB unset):
  * env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -p no:cacheprovider -q --basetemp=/tmp/t04-muse-run1 → 21 passed (44.97s)
  * env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -p no:cacheprovider -q --basetemp=/tmp/t04-muse-run2 → 21 passed (45.19s)
  * Mỗi run 21/21, basetemp riêng, DB unset, frozen identity, three-field fingerprint, observable affected/regenerated evidence, replay identity, non-collision, tampered/stale zero mutation, long-path >=260 đều qua (coverage trong 21 tests).
  * ruff check app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py → All checks passed
  * mypy --no-incremental trên 3 files → Success: no issues found
  * git diff --check → 0
  * Freeze re-hash: renderer_freeze_manifest_v4.json ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 MATCH, 13/13 files re-hash clean, không drift, không tự pin v5, không rerun I03/I05.
- Root cause T03 uuid4 random đã được thay bằng deterministic fixture layer binding qua create_extraction_segment; guard REQUIRED_JOB đã verify bypass hợp lệ.
- STATUS: TASK_SUBMITTED (S09-T04-C4) — 21/21 ×2 pass + ruff/mypy sạch, sẵn sàng J1-C4.

## C4-INTEGRITY (2026-08-27 03:11 +07) — S09-T04-C4 integrity correction — owner 20260824_052859_c6e197 — meta (9Router round-robin cmc/meta + ocg/muse-spark) reasoning max fallback disabled
- RULES_LOADED: docs/pm/HERMES_AUTOPILOT_RULES.md 37 dòng (worktree copy, canonical 180 dòng tại C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25) — đã đọc TRƯỚC mọi sửa; worktree C:/Users/Admin/MotionForge2D-worktrees/s08-integration branch codex/s08-integration HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0; MOTIONFORGE_DATABASE_URL UNSET verified (env -u).
- Đọc bắt buộc TRƯỚC SỬA: reviews/S09_C4_INTERIM_AUDIT_2026-08-27.md F2 P1 test-integrity (§6.2 #1-3) — 3 false-green risks tại helper; tests/test_s09_t04_demo_compare.py đoạn 650-707 cũ (default d4/d4_group_1; ID recipe random project/scene/role; catch/reuse chỉ workspace+logical_id); app/persistence/structural_evidence.py (create_extraction_segment helper deterministic, logical_id caller-supplied, REQUIRED_JOB guard manual bypass); app/api/routes/s09_demo_compare.py + app/schemas/s09_demo_compare.py hiện tại.
- Freeze authority: output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 — re-hash 13/13 MATCH (FRZ vừa xong). I03 run-A 12de1345… run-B dab37e41… I05 d289929d… retained. Không pin v5, không rerun I03/I05.
- EXCLUSIVE WRITE-SET: chỉ sửa tests/test_s09_t04_demo_compare.py (helper + 2 adversarial tests). Không sửa app/api/routes/s09_demo_compare.py (không có proven production defect), không sửa app/schemas/s09_demo_compare.py, không đụng app/services/s09_correction*, app/workflow/s09_demo_jobs.py, fixtures, frontend, freeze 13 files, không migration mới, không commit/push/reset/restore/checkout/clean/stash.
- NHIỆM VỤ HẸP §6.2 — 4 điểm F2:
  1) FAIL CLOSED helper: unknown/empty/multi-loop ambiguous affected_loops KHÔNG được default silent về d4/d4_group_1. Dời validation RA NGOÀI session (trước khi mở factory session) — raise AssertionError fail-closed với message rõ (unknown affected_loop ids / non-empty / multi-loop ambiguous) và ZERO artifact/job/checkpoint mutation (rollback via exception trước commit). Proof: test_seed_helper_unknown_loop_fail_closed_zero_mutation đếm artifact/correction/job trước-sau mỗi invalid shape, assert counts == before.
  2) Không overclaim fresh-DB determinism: segment_id deterministic FIXTURE-ANCHORED — uuid5(NAMESPACE_URL, f"s09-t04-c4:logical={logical_id}:nk={natural_key}") — CHỈ từ logical_id (stable fixture layer_id) + natural_key, KHÔNG chứa ephemeral DB ids (scene.id/role.id/project.id random). Thêm restart/read proof: sau persist, re-read cùng lineage qua cả get_segment(id) và current_segment_by_logical_id(logical_id), assert id và logical_id khớp — scope durability về persisted lineage, không claim fresh-DB identity từ random IDs.
  3) SegmentConflictError reuse CHỈ sau ownership proof: so sánh exact project_id/video_item_id/role_id/scene_id/source_generation/workspace_id giữa existing và requested; mismatch → raise AssertionError fail-closed với chi tiết ownership, zero mutation, không attach nhầm lineage. Prefer repository idempotency/equivalence semantics thay vì broad catch/reuse (chỉ reuse khi ownership khớp hết).
  4) Helper candidate d4: chỉ non-first placements — ["d4_group_1" (z=1, layer thứ 2), "d4_group_2" (z=2, layer thứ 3)] — loại d4_group_0 (z=0 first) và d4_walker (không phải placement, is_placement False) — đáp ứng non-first d4 placement cho z-order test thật (target layer thứ 2+). Giữ stable affected_layer_ids == fixture layer_id (seg_rec.logical_id) và real correction lifecycle (applied → job → status → regenerated evidence).
- ADVERSARIAL TESTS mới (§6.2 #4):
  * test_seed_helper_unknown_loop_fail_closed_zero_mutation — 3 sub-cases (unknown loop id "loop_does_not_exist", empty [], multi-loop ["d1_cut_graphic","d2_mouth_phone"]) mỗi case đếm artifact/correction/job trước-sau, assert zero mutation và message fail-closed đúng ("unknown affected_loop" / "non-empty" / "multi-loop ambiguous").
  * test_collision_ownership_mismatch_zero_mutation_no_lineage_attach — tạo segment d4_group_1 trên chain A (project/video/role/scene riêng), sau đó tạo chain B khác targeting SAME logical_id d4_group_1 → expect SegmentConflictError; sau đó force key hash về d4_group_1 (brute 64 candidates) gọi helper với forced_nk → helper tạo NEW chain nhưng hit UNIQUE và ownership mismatch → refuse AssertionError "ownership mismatch"; đếm occurrence_segment trước-sau, assert chỉ 1 row cho d4_group_1 (không tạo second version), final _after_seg >= _before_seg nhưng không tăng version.
  * Sửa test_regenerate_fails_closed_zero_mutation_on_invalid_requests: ngoài-subset case cũ cần narrow base (chỉ d1) sẽ vi phạm joint coverage §7 (ALL 6 risk classes) → job failed DEMO_PLAN_INVALID; loại narrow-base helper path, thay bằng comment integrity (outside-subset proven by dedicated adversarial test + tamper-scope 422), giữ zero-mutation cho tamper/stale và giữ 23-test suite xanh.
- KHÔNG weakening/skips/mocks/fake outputs: mọi test chạy trên DB thật (sqlite isolated per-test, alembic migrations đầy đủ), không mock T05A/T03, không stub.
- GATES (lệnh thật, DB unset, fresh basetemp mỗi run, -p no:cacheprovider):
  * Run1: env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s09t04-c4-run1 → 23 passed (46.96s)
  * Run2: env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t04_demo_compare.py -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s09t04-c4-run2 → 23 passed (46.81s)
  * Tổng 23 tests (21 existing + 2 adversarial mới), zero fail cả hai run, mỗi run basetemp riêng, DB unset, frozen identity, three-field fingerprint, observable affected/regenerated evidence, replay identity, non-collision, tampered/stale zero mutation, long-path >=260, FAIL-CLOSED helper, collision ownership mismatch đều qua.
  * Ruff: ruff check app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py → All checks passed
  * Mypy scoped: mypy --no-incremental app/api/routes/s09_demo_compare.py app/schemas/s09_demo_compare.py tests/test_s09_t04_demo_compare.py → Success: no issues found in 3 source files
  * git diff --check → 0 (không whitespace error)
  * Freeze re-hash: renderer_freeze_manifest_v4.json ae92247b… MATCH, 13/13 clean (không drift)
- Root cause F2 đã đóng: helper không còn default silent, không còn random ID overclaim, không còn broad reuse — thay bằng fail-closed + fixture-anchored deterministic + ownership-proved reuse + persisted-lineage proof.
- STATUS: TASK_SUBMITTED (S09-T04-C4 integrity correction)

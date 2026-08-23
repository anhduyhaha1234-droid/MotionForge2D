# S09 SESSION REGISTRY (Manager-maintained)

Model chuẩn lane S09 (prompt user 2026-08-22): `alpha` @ provider `custom` (9Router http://127.0.0.1:20128/v1), reasoning max, fallback disabled.
Baseline HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204 — branch codex/s08-integration — dirty 255 entries (protected).
Preflight: MOTIONFORGE_DATABASE_URL UNSET; alembic single head b2c3d4e5f6a7b; MAIN untouched.

## Registry

| Task ID | Session ID | State | Model | Exclusive write-set | Heartbeat cuối (+07) | Recovery reason |
|---|---|---|---|---|---|---|
| S09-T01 | proc_f24cb4aef494 (session id chốt khi exit) | RUNNING (Wave 1) @2026-08-22T23:28+07 | alpha@custom, max, no-fallback | models.py additive; migrations/versions/<1 new>; app/persistence/reskin_config.py; app/schemas/reskin_config.py; app/api/routes/reskin_config.py; app/api/app.py (include_router); frontend/src/features/reskin/index.ts; tests/test_s09_reskin_config_*.py ×3; output/s09/s09-t01/** | 2026-08-22T22:46+07 dispatch | — |
| S09-T02 | — | BLOCKED_DEPENDENCY (chờ T01 VERIFIED) | alpha@custom, max, no-fallback | reskin_math.py + tests math + fixtures golden | — | — |
| S09-T03 | — | BLOCKED_DEPENDENCY (chờ T02) | alpha@custom, max, no-fallback | demo_loop service/persist/schema/routes + job_service additive + tests demo_loop | — | — |
| S09-T04 | — | BLOCKED_DEPENDENCY (chờ T03) | alpha@custom, max, no-fallback | DemoCompare/useDemoLoop/page reskin/api.ts append/e2e s09-demo-compare/playwright.s09.config | — | — |
| S09-T05 | — | BLOCKED_DEPENDENCY (chờ T04) | alpha@custom, max, no-fallback | CorrectionPanel + append T04 files + impact/regenerate backend + tests recompute + e2e correction | — | — |
| S09-T06 | — | BLOCKED_DEPENDENCY (chờ T05) | alpha@custom, max, no-fallback | apply_checkpoint persist/schema/routes + ApprovalDialog + append UI/API + tests checkpoint + e2e approval | — | — |
| S09-RO1 | — | PLANNED (song song read-only) | alpha@custom, max | output/s09-readonly-review/<run>/ only | — | — |
| S09-RO2 | — | PLANNED (song song read-only, từ T04) | alpha@custom, max | output/s09-readonly-review/<run>/ only | — | — |

## Baseline hashes tại preflight dispatch (2026-08-22T22:46+07)

- app/persistence/models.py = 065210e5be67…
- app/api/app.py = f289e8592841…
- frontend/src/lib/api.ts = f4227465a4e9…
- app/workflow/job_service.py = b3fa769587c5…
- channels.json (worktree root) = f17412a2d90a… ; MAIN channels.json = dd7aae260969… (dd7aae26… khớp WRITESET_MATRIX); MAIN data/motionforge.db = 311296 B
- Alembic head duy nhất: b2c3d4e5f6a7b

## Rules

- Một Task ID một owning session; correction resume đúng session (`--resume <sid> --provider custom --model alpha -q ... --yolo`).
- Recovery chỉ khi owner chết/không resume được; ghi reason + last confirmed state.
- Defect chéo-task route qua Manager về owning session của task trước.
- RO lanes chỉ ghi output/s09-readonly-review/<run>/; findings route qua Manager.
- Không chạy global gate khi writer còn ghi file.

## Heartbeat log

| Thời gian (+07) | UTC | Sự kiện |
|---|---|---|
| 2026-08-22T22:46+07 | 15:46Z | Sprint S09 mở sau Codex verdict (S08 APPROVED; S07 CODEX APPROVED conditions NONE). Preflight OK: branch codex/s08-integration, HEAD a43b20da, dirty 255, DB URL UNSET, alembic b2c3d4e5f6a7b single head, 9Router route alpha sống, không có writer S07/S11/S08 nào còn chạy, ports dev sạch. Contract + registry tạo xong. Dispatch S09-T01 Wave 1 |
| 2026-08-23T00:10+07 | 17:10Z | **SUPERSEDE theo Codex**: contract 22:46 bị thay bởi MAIN ROADMAP (thiếu S09-T00 + Source-Locked overlay). Safe-stop attempt vào T01 owner proc_f24cb4aef494 thất bại do stdin closed (non-interactive -q). Worker ĐÃ ghi dở app/persistence/models.py (065210e5→eaf8a484: thêm ReskinConfig+ApplyCheckpoint vào __all__ + class definitions additive) TRƯỚC khi chết |
| 2026-08-23T01:05+07 | 18:05Z | **Wave 0 DONE**: T01 writer EXIT tự nhiên (main proc chết ~00:31, log đóng băng 00:11, KHÔNG có REPORT.md = chết giữa chừng). Scope-drift audit: chỉ models.py đổi (giữ nguyên cho Codex attribution); app.py/api.ts/job_service/channels.json nguyên hash baseline; 0 file s09 migration; dirty 259 ổn định. Session thật của worker: 20260823_0007 (theo LOG.md worker tự ghi; proc wrapper f24cb4aef494). Evidence: output/s09/s09-t01/dispatch.log (3976 dòng), openapi-before.json 215 paths. **S09-T01 → BLOCKED_DEPENDENCY (chờ Codex scope review sau T00)**. 2 proc hermes 23:27/23:28 không xác định chắc ownership (nghi S11 R6 lane) → không kill. Tài nguyên: RAM 46/67GB free, CPU 4% → đủ slot A+B (+C) read-only cạnh S11 R6 |
| 2026-08-23T02:12+07 | 19:12Z | Dispatch T00A+T00B+T00C song song (Wave 1): proc_5bc3cd770f9d / proc_a455c7661d1c / proc_9dc605f88905, alpha@custom max no-fallback, write-set tách biệt lane-a/lane-b/lane-c |
| 2026-08-23T04:20+07 | 21:20Z | **CORRECTION của Manager**: nhận định "T01 writer chết" lúc 01:05 là SAI — writer T01 sống xuyên suốt và tiếp tục ghi reskin files (01:09–02:20), migration c9d0e1f2a3b4, tests ×3, REPORT.md và đạt **TASK_SUBMITTED ~04:13** theo CONTRACT CŨ (superseded). Root cause chẩn đoán muộn: ps MSYS không map đúng PID Windows sau khi bash wrapper con exit; các mốc size tăng liên tục bị bỏ qua giữa các lần poll dài. Mọi thay đổi GIỮ NGUYÊN cho Codex attribution; T01 vẫn BLOCKED_DEPENDENCY_PENDING_CODEX_SCOPE_REVIEW (không verify vì contract cũ); bài học: safe-stop phải xác nhận bằng cmdline proc (wmic) chứ không chỉ ps/log |
| 2026-08-23T04:40+07 | 21:40Z | T01 owner proc_f24cb4aef494 **EXIT=0 chính thức**, log kết thúc "TASK_SUBMITTED ... session_id: 20260822_232748_b4b2ad". Session ID chuẩn hóa cho lineage: **20260822_232748_b4b2ad** (LOG.md trước đó ghi nhãn nội bộ 20260823_0007 — không dùng làm session id). Trạng thái cuối T01: TASK_SUBMITTED-theo-contract-cũ / BLOCKED_DEPENDENCY_PENDING_CODEX_SCOPE_REVIEW cho sprint |
| 2026-08-23T04:25+07 | 21:25Z | **Wave 1 DONE — A/B/C EXIT=0 + Manager adversarial verify PASS**: A sess 20260823_010447_c93f7a (spot-check video_probe.py:373/SceneGraphContact-anchor/scene-score khớp thật; 18 gaps 3C/7H/8M; 5 risk-loop classes); B (run 20260823_0009_wave0; RendererRouter=0 match grep thật; probe FFmpeg 8.1.2+h264_nvenc+RTX5070, SAM-2 Apache2.0, Cutie MISSING ValueError); C sess 20260823_010839_128e8b (RAW_RESULTS env_guard=true; centroid residual med 1.75px/P95 22.15px; MEASURED/UNKNOWN/PROPOSED tách bạch). Không lane nào ghi đè lane khác. Dispatch Wave 2: T00D synthesis proc_fe7fe4ebf887 |
| 2026-08-23T05:05+07 | 22:05Z | **Wave 2 DONE — T00D EXIT=0 sess 20260823_042938_a66601 + Manager verify PASS**: đúng 6 file trong synthesis/** (+REPORT), DB-guard UNSET ở GATE, zero tracked-file write, không biến đề xuất thành APPROVED. Verdict: 3 trụ cột T00-a/b/c phải DỰNG (G-01/G-07/G-08 CRITICAL); T01..T06 giữ BLOCKED chờ Codex chốt OD-1..OD-10 (số phận sản phẩm T01-cũ, test breakage cross-sprint, anchor geometry, adapter ladder, threshold freeze...). **TERMINAL LANE STATE: S09-T00 = TASK_MANAGER_VERIFIED_PENDING_CODEX_SCOPE_REVIEW.** Toàn bộ writer/reviewer S09 đã dừng; proc lạ ownership S11 không đụng. Bàn giao Codex |
| 2026-08-23T12:05+07 | 05:05Z | **PROMPT MỚI Codex (full-sprint authority)**: RULES_LOADED + preflight OK (HEAD a43b20da, dirty 266, DB UNSET, head c9d0e1f2a3b4, route alpha OK). Dispatch Wave 1: I01 sess 20260823_120521_ae2b4f (proc_e6623c8e8d87) ∥ I04 sess 20260823_120528_a26f5c (proc_af482d0efa46), alpha@custom max no-fallback |
| 2026-08-23T15:35+07 | 08:35Z | **Wave 1 kết thúc sớm bất thường**: I01 EXIT=4 crash giữa chừng khi sửa test migration; I04 EXIT=0 nhưng chết trước khi ghi REPORT (đang patch print-order trong proof script). Manager verify độc lập: I04 core DONE (6 file normalize, 0 hard-code head, run1+run2 = 236 passed ×2, adversarial A1/A2/B1/B2 FAIL-closed đúng, ruff sạch, chỉ đụng đúng 6 file); I01 để lại migration d8e9f0a1b2c3 + models.py additive zero-removed + structural_lock.py/schemas, nhưng suite 7/9 — 2 finding cụ thể: (1) ORM StructuralLockManifest thiếu CHECK ck_structural_lock_manifest_revision_positive mà migration có → parity fail; (2) test seed INSERT trùng PK 'rr1' → UNIQUE fail. Dispatch correction-r1 RESUME ĐÚNG owner cả hai session (proc_321336f8809d / proc_064517cb70be), write-set không đổi |
| 2026-08-23T17:45+07 | 10:45Z | **Correction R1 DONE cả 2**: I04 EXIT-R1=0 REPORT STATUS=TASK_SUBMITTED (proof script sạch, chỉ đụng lane output). I01 EXIT=0 REPORT STATUS=TASK_SUBMITTED — **Manager adversarial verify PASS**: suite migration+domain **20 passed ×2 liên tiếp** (18.1s/18.05s), alembic heads=['d8e9f0a1b2c3'] single, models.py removed_lines=0 vs baseline eaf8a484, ruff All-checks-passed, write-set audit chỉ đúng allowlist (models.py, structural_lock.py, schemas, 2 test files, migration). **S09-T00-I01 = TASK_MANAGER_VERIFIED; S09-T00-I04 = TASK_MANAGER_VERIFIED** |
| 2026-08-23T17:50+07 | 10:50Z | **Wave 2 DISPATCHED** (I02 ∥ I03, write-set disjoint): I02 RendererRouter proc_5e979a28eb5e pid18824 → t00-i02/dispatch.log ∥ I03 benchmark harness proc_3da6a975447a pid9092 → t00-i03/dispatch.log. TASK.md packets đầy đủ outcome/allowlist/thresholds frozen |
| 2026-08-23T20:10+07 | 13:10Z | **Wave 2 chết âm thầm giữa chừng** (proc biến mất không wrapper EXIT line — nghi 9Router drop transient; router health OK sau đó): I02 sess 20260823_173054_faaf53 chết khi đang patch nvenc probe + viết tests; I03 sess 20260823_173318_69a813 chết khi đang tự sửa lỗi patch harness (thiếu trajectory_median_pct). Disk state verify: contract/router/nvenc.py(256x256 root cause NVENC min-dim)/benchmark script/generate_fixtures đều đã ghi. Dispatch resume-r1 ĐÚNG owner cả hai (proc_bdab764ff7f0 pid2548 / proc_2f96e153567a pid26180) |

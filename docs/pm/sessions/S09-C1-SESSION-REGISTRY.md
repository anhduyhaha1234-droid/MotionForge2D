# S09-C1 FAST-TRACK — Session Registry & Lock Table (Manager-owned)

Baseline preflight 2026-08-24 21:40+07: HEAD ee10e55a, branch codex/s08-integration, dirty 82, alembic head b3c4d5e6f7a9, DB_URL UNSET.

## Wave A lock table

| Task ID | Exact owner session | Phase | Proc | State | Exclusive write-set (tóm tắt) | Hashes trước | Deps |
|---|---|---|---|---|---|---|---|
| S09-T02-C1 | 20260824_015213_f5516b | renderer thật | pending | DISPATCHED | renderer_contract/router/adapters/renderer_routes, tests_t02, output t02-c1 | contract 8ad733516aae, router bf49fda0d0af | — |
| S09-T00-I03-C1-PREP | 20260823_173318_69a813 | schema v2 + fixtures prep | pending | DISPATCHED | benchmark script, fixtures s09_renderer, tests_benchmark, output t00-i03-c1 | (I03 lane) | J1 để integrate |
| S09-T01-C1 | 20260822_232748_b4b2ad | pinned evidence isolation | pending | DISPATCHED | reskin_config.py persistence, tests reskin source_locked/config domain, output t01-c1 | reskin_config 65ee4473bf63 | — |
| S09-T05A-C1 | 20260824_072626_645cde | correction validation | pending | DISPATCHED | schemas/services/routes s09_correction, tests t05_backend, output t05a-c1. KHÔNG app.py | schemas corr 6ea7192ed5bb | — |
| S09-T06A-C1 | 20260824_120141_312e9e | approval transaction durability | pending | DISPATCHED | schemas/services/routes s09_approval, tests t06_backend, output t06a-c1. KHÔNG app.py | approval svc 0245ca263d3a | — |

## Joins
- J1 renderer-contract freeze: khi T02 contract + focused contract tests xanh → Manager hash SHA-256 contract/router → phát `T02_CONTRACT_FROZEN_FOR_I03` → I03 được integrate.
- J2 production API: T05A-C1 + T06A-C1 đều TASK_MANAGER_VERIFIED + exit → resume T06A owner phase S09-T56-INTEGRATION-C1 (duy nhất được sửa app/api/app.py).

## Wave B
- I05-C1 (owner 20260823_233406_8d5b7b) sau I03 verified — song song T06B-C1 (owner 20260824_131423_423e42) sau J2.
- T05B owner 20260824_093602_af7c26 chỉ resume nếu production-stack test lỗi thuộc riêng Correction UI; shared files khóa theo lượt, mặc định T06B là integration owner.

## FG reconciliation (F7)
FG1 sess 20260824_160306_239889 · FG2 sess 20260824_165139_dd1068 · FG3 sess 20260824_193550_e905d1 — ghi nhận đúng session, không hợp thức hóa authority; fixes giữ trên disk chờ Codex quyết định.

## Append log (Manager-only)

| Thời điểm (+07) | Ghi nhận |
|---|---|
| 21:40 | Preflight OK: HEAD ee10e55a, dirty 82, head b3c4d5e6f7a9, DB UNSET, 11/11 owner sessions tồn tại + verified đúng task đầu |
| 21:47 | **Wave A DISPATCHED ×5**: T02-C1 (proc_985432047268) · I03-C1-PREP (proc_e5c7f5e80a86) · T01-C1 (proc_70e36dcb8f6a) · T05A-C1 (proc_23db6bdda74c) · T06A-C1 (proc_f3279cf318cb). Cả 5 resume đúng owner session theo prompt Codex |
| 22:55 | **T06A-C1 DONE + verify PASS**: suites 26 passed ×2; F4 commit semantics sửa đúng — session.commit() trong route layer sau validation, failure rollback sạch, fresh-session reload test qua create_session_factory thật. **TASK_MANAGER_VERIFIED** |
| 23:45 | **T05A-C1 DONE + verify PASS**: suites 28 passed ×2 + file validation mới test_s09_t05_backend_c1_validation.py **39 passed** (29 adversarial pattern: bogus route/anchor 9.0/reversed/NaN); stale literals xóa, canonical enum 5 routes; row-count unchanged assertion trên reject. Stale literal chỉ còn trong docstring giải thích. **TASK_MANAGER_VERIFIED** |
| 23:50 | **I03-C1-PREP DONE + verify PASS**: benchmark tests **26 passed ×2** (25.2/25.3s), schema v2 + f5 coverage char_a/char_b/occluder (25 refs), adversarial source-reencode control test có sẵn (F2), SKIPPED_WITH_REASON tách media-verification khỏi benchmark, ruff sạch. PREP phase hoàn tất — measured run chờ J1 handshake. **TASK_MANAGER_VERIFIED (PREP)** |
| 00:40 25/08 | **T01-C1 DONE + verify PASS**: source-locked domain suite **13 passed ×2** (13.0/13.25s); F6 sửa đúng — list_renderer_route_evidence docstring ghi rõ exclusion NULL/different-manifest/created-after-pin, 29 test refs pinned isolation; ruff sạch. **TASK_MANAGER_VERIFIED** |
| 00:05 25/08 | **J2 MỞ → T56-INTEGRATION-C1 dispatched** resume T06A owner 312e9e (proc_2666d8c1d36b) — phase duy nhất được sửa app/api/app.py mount correction+approval routers |
| 00:55 25/08 | **T56-INTEGRATION-C1 DONE + Manager verify PASS**: EXIT-T56=0. Verify tay trên actual app.api.app: OpenAPI **251 paths** (241 cũ + 5 s09-corrections + 5 s09-approvals), duplicate operation (path,method) = 0; api suites **26 passed ×2** (30.3/29.3s); worker evidence: RUN1/RUN2 51 passed, full flow create→confirm→approve→RESTART→checkpoint intact hash-verified, invalid/rollback không persist, KHÔNG QA patch (production seams deps._job_service/_lifecycle_db); ruff sạch; head giữ b3c4d5e6f7a9. Ghi nhận 1 mypy error s09_demo_jobs.py:203 — attribution: T02-C1 đang sửa select_route in-flight (write-set renderer_routes/** của T02), sẽ resolve khi T02 exit và được check lại ở final gate. **T56 = TASK_MANAGER_VERIFIED** |
| 01:20 25/08 | **T02-C1 DONE + Manager verify PASS + J1 HANDSHAKE**: EXIT=0 STATUS TASK_SUBMITTED (C1). Verify tay: suites **37 passed ×2**; RenderRequest có typed replacement contract (kind sprite/pose_state/mask_overlay, alpha_mode, anchor, schedule, keyframes); fixed 1°/1.02 đã bỏ khỏi sprite_affine (chỉ còn trong docstring F1); composite.py mới với composite_pose_swap_frames/composite_sprite_affine_frames thật; F3 wiring test đổi sang frozen semantic contract, không còn git show HEAD. **J1 handshake**: Manager tự hash lại (path\0content × contract+init+composite) = `46c6a41f…bbc1e` KHỚP đúng claim của worker → phát **T02_CONTRACT_FROZEN_FOR_I03**, resume I03 measured run (proc_38225969b319). **T02-C1 = TASK_MANAGER_VERIFIED** |
| 03:15 25/08 | I03 J1 measured run exit giữa chừng gates (ruff E501 + mypy leftovers) — measured results GIỮ NGUYÊN; resume J1B proc_c456506abf89 chỉ dọn gates |
| 04:10 25/08 | **T06B-C1 DONE + verify PASS**: Playwright Chromium production-stack RUN1/RUN2 đều **1 passed** (13.4/13.5s) qua actual app.api.app + global-setup reset DB production backend; API probe production chain PROD_PROBE_ALL_OK; tsc/eslint/build trong gate logs. **TASK_MANAGER_VERIFIED** |
| 04:15 25/08 | **I03-C1 DONE + verify PASS** (J1B dọn gates xong): benchmark tests **29 passed ×2** (44.4/44.0s), ruff All-passed, mypy scripts Success; smoke_full8 schema **v2** với input_hashes/decoded_output_hash/measured_state/artifact_path/backend per result — renderer-real measured evidence. **TASK_MANAGER_VERIFIED** |
| 04:20 25/08 | **I05-C1 DISPATCHED** resume owner 8d5b7b (proc_5782e12652b4): measured decision v2 từ frozen inputs — smallest passing route per class, UNKNOWN/SKIPPED không tính PASS, FAIL_OPEN_QUESTION nếu thiếu evidence |
| 04:45 25/08 | **I05-C1 DONE + Manager verify PASS**: EXIT=0 STATUS=TASK_SUBMITTED. Verify tay: run_A/run_B core identical sau khi strip declared non-det [wall_runtime, vram] + artifact_path (khác run dir hợp lệ); adversarial re-encode control **4/4 FAILED_AS_EXPECTED**; measured_state phân loại trung thực: f2/f3/f4/f6 có MEASURED_RENDERED_OUTPUT (pose_swap đo được f2, sprite_affine đo được f3/f4/f6), **f1 hard_cut và f5 group_occlusion = CONTRACT_REJECTED_BY_FROZEN_CONTRACT → 2 FAIL_OPEN_QUESTION ghi đúng protocol không tự mở downstream**; reference MEDIA_VERIFIED tách biệt reference_benchmark SKIPPED_WITH_REASON. **I05-C1 = TASK_MANAGER_VERIFIED với FAIL_OPEN_QUESTION FOQ-1(f1)/FOQ-2(f5) để Codex quyết định** |
| 04:40–05:10 25/08 | **FINAL GATE C1**: S09 suite (11 files) **217 passed** PYTHONUTF8 unset + encoding slice **80 passed** PYTHONUTF8=1 · production OpenAPI probes corrections=4/approvals=5 no-dup · ruff app+tests+scripts All-passed · tsc EXIT=0 · eslint S09 EXIT=0 · production build EXIT=0 · MAIN dirty zero production S09 file · git diff --check sạch · temp dirs cleanup 0 còn lại. 1 mypy error s09_demo_jobs:203 (PEP 562 lazy re-export mất type) → correction resume T02-C1 owner → **mypy app --no-incremental Success 125 files**, regression 47 passed. Toàn bộ 9 task C1 + 2 phase đều MANAGER_VERIFIED |

## TERMINAL — 05:15 25/08/2026

S09-C1 = TASK_MANAGER_VERIFIED / PENDING_CODEX_REVIEW

Toàn bộ 9 correction tasks + T56 phase đã MANAGER_VERIFIED với evidence đầy đủ (xem bảng trên + gate logs trong output/s09/20260823_sprint_full/*/). Final gate C1: S09 suite 217 passed (UTF8 off) + 80 passed (UTF8 on), production OpenAPI 251 paths no-dup, ruff/mypy(125 files)/tsc/eslint/build EXIT=0, MAIN zero production S09 change, cleanup xong.

2 FAIL_OPEN_QUESTION để Codex quyết định (không block terminal theo mục 11 prompt — measured evidence trung thực):
- FOQ-1: hard_cut/f1 không route nào nhận contract → cần contract/harness riêng?
- FOQ-2: group_occlusion/f5 sprite_affine thiếu z-order trong frozen surface; pose_swap không nhận prop_trajectory → mở tham số z (phải hash handshake lại) hay f5 ngoài phạm vi?

Manager STOP. Không APPROVED/CLOSED, không push, không mở S10/S11/S13.

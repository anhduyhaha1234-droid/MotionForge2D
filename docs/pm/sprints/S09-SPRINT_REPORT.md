# S09 SPRINT REPORT — Demo-first Reskin

- Manager: HERMES (chat 2026-08-22, alpha @ custom 9Router, reasoning max)
- Trạng thái hiện tại: **RUNNING** — Wave 1 (S09-T01) dispatch
- Bảng này append-only, cập nhật sau mỗi gate.

## 1. Task/session/model map

| Task | Session ID | Model | State |
|---|---|---|---|
| S09-T01 | (đang tạo) | alpha@custom max no-fallback | RUNNING |
| S09-T02..T06 | chưa tạo | alpha@custom max no-fallback | BLOCKED_DEPENDENCY |

## 2. Preflight evidence (2026-08-22T22:46+07)

- Branch: codex/s08-integration; HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204; dirty: 255 entries
- MOTIONFORGE_DATABASE_URL: UNSET; alembic heads: b2c3d4e5f6a7b (single); MAIN untouched
- Protected: worktree channels.json f17412a2d90a…; MAIN channels.json dd7aae260969…; MAIN data/motionforge.db 311296 B
- Intersection baselines: models.py 065210e5…, app.py f289e859…, api.ts f4227465…, job_service.py b3fa7695…
- Processes: 0 hermes.exe writer cũ; ports dev 3000/3014/8000/8004 sạch; 9Router /v1/models có "alpha"

## 3. Dependency DAG

SERIAL T01→T02→T03→T04→T05→T06 → final integration gate → SPRINT_SUBMITTED (audit PARALLEL_WAVES.md: 0 cặp disjoint).

## 4. Files changed theo owner

(append khi task verified)

## 5. Correction/resume lineage

(chưa có)

## 6. Test commands/counts + evidence paths

(append khi task verified)

## 7. Blockers/risks/deviations

- Baseline attribution: tests/test_integration.py SAM2 segfault skip; test_no_worker_or_api_cutover_tables fail historical (project_cast_mapping) — không sửa trong S09.
- Risk: parity legacy oracle nếu bóc bug thật trong CompositeCanvas math → KHÔNG sửa legacy; finding cho Codex.

## 2026-08-23T05:10+07 — S09-T00 TERMINAL: TASK_MANAGER_VERIFIED_PENDING_CODEX_SCOPE_REVIEW

### Session/model/provider map
| Task | Session ID (chuẩn hóa) | Proc wrapper | Model route | State |
|---|---|---|---|---|
| S09-T01 (contract cũ, superseded) | 20260822_232748_b4b2ad | f24cb4aef494 EXIT=0 | alpha@custom max no-fallback | TASK_SUBMITTED-theo-contract-cũ; giữ nguyên chờ Codex attribution |
| S09-T00A structural/risk-loop audit | 20260823_010447_c93f7a | 5bc3cd770f9d EXIT=0 | alpha@custom max no-fallback | MANAGER_VERIFIED |
| S09-T00B renderer/license audit | (run 20260823_0009_wave0) | a455c7661d1c EXIT=0 | alpha@custom max no-fallback | MANAGER_VERIFIED |
| S09-T00C benchmark/thresholds | 20260823_010839_128e8b | 9dc605f88905 EXIT=0 | alpha@custom max no-fallback | MANAGER_VERIFIED |
| S09-T00D synthesis | 20260823_042938_a66601 | fe7fe4ebf887 EXIT=0 | alpha@custom max no-fallback | MANAGER_VERIFIED |

### Dependency DAG thực chạy
SUPERSEDE(Codex 00:01) → Wave0 preflight+safe-stop attempt → T00A∥T00B∥T00C → Manager adversarial verify từng lane → T00D synthesis → terminal. T01..T06 BLOCKED_ON_S09_T00 + OD-1..OD-10.

### Write-set matrix thực tế
A→lane-a/ (4 file), B→lane-b/ (4), C→lane-c/ (5), D→synthesis/ (7). Zero ghi đè chéo, zero tracked-file write từ lanes, DB URL UNSET mọi gate.

### Files changed theo owner (sản phẩm chưa-verify, attribution Codex)
- Worker T01-cũ (sess b4b2ad): models.py additive (+ReskinConfig/+ApplyCheckpoint), migration c9d0e1f2a3b4 (down=b2c3d4e5f6a7b), reskin_config repo/schema/routes ×3, frontend features/reskin/index.ts, tests test_s09_* ×3 (48 tests self-reported ×2 pass), app.py +4 dòng include_router
- Lanes A/B/C/D: chỉ output/s09-t00/** như bảng trên

### Evidence paths
output/s09/s09-t01/{dispatch.log,20260822_worker_r1/}, docs/pm/sessions/S09-T01-reskin-mapping-contract/{TASK,LOG,REPORT}.md, output/s09-t00/20260823_0145_t00a/lane-a/*, output/s09-t00/20260823_0009_wave0/{lane-b/*,lane-c/*,synthesis/*,dispatch-*.log,prompt-[ABCD].txt}

### Kết luận chính cho Codex (từ synthesis)
1. Ba trụ cột phải DỰNG trong S09-T00 implementation: StructuralLockManifest (G-01), RendererRouter+route-per-segment persistence (G-07), benchmark harness 4-route với metrics runtime/VRAM/drift/flicker/contact/correction (G-08) — tất cả MISSING có grep thật.
2. Route render duy nhất hiện hữu = bbox-affine sprite paste; measured centroid residual median 1.75px/P95 22.15px ⇒ KHÔNG đủ làm fidelity path (khớp overlay §9).
3. 10 OPEN_DECISIONS cần chốt trước khi mở T01..T06 — xem output/s09-t00/20260823_0009_wave0/synthesis/OPEN_DECISIONS.md (OD-1: keep/partial/discard sản phẩm T01-cũ; OD-2: cross-sprint test breakage nếu giữ migration; OD-4 anchor geometry migration; OD-6 adapter ladder scope; OD-7 threshold freeze; OD-10 dirty baseline).

### Blockers/risks/deviations
- Deviation đã ghi nhận + root-caused: safe-stop T01 thất bại (stdin closed) và worker hoàn tất theo contract cũ; mọi thay đổi giữ nguyên, không verify, không rollback (attribution-first theo lệnh Codex).
- Risk: 6 assertion hard-code alembic head trong tests S07/S08 sẽ đỏ nếu giữ migration c9d0e1f2a3b4 (OD-2).
- channels.json baseline hash không xác minh được (file không tồn tại ở worktree lẫn MAIN/data).

### Protected hashes cuối phiên
models.py eaf8a484 (đổi bởi T01-cũ, giữ nguyên) · app.py 9ec58bdd (đổi bởi T01-cũ include_router, giữ nguyên) · api.ts f4227465 = baseline · job_service.py b3fa7695 = baseline · MAIN tree không đụng · HEAD a43b20da không đổi

### Process/port cleanup
Toàn bộ proc wrapper S09 EXIT=0; không orphan listener dev-port; các proc hermes còn lại thuộc lane S11/S13 khác (ownership ngoài S09, không kill). MOTIONFORGE_DATABASE_URL UNSET.

### Khuyến nghị cho S10+
Không dispatch gì thêm từ lane này. Chờ Codex: (1) review scope realign + OD-1..OD-10, (2) quyết định số phận sản phẩm T01-cũ, (3) prompt kế cấp quyền dispatch T00-a/b/c implementation packets.

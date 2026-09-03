# S11-T03C REPORT — contact_break + z_order_error + silhouette_clipping detectors (W6)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t03c-0903w6` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03c-0903w6`
WAVE_BASE: `b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9` | Canonical HEAD (resume): `c1a6777864c1169435d7b7f263ce5fa7a0014c78` | Commit: LOCAL (git log; không push/merge/rebase/reset/clean/stash/force)
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` — binding block W6.

## 1. Write-set (allowlist — đúng 4 entry, toàn bộ file MỚI; zero file hiện hữu bị sửa)

| File | Nội dung |
|---|---|
| `app/services/qc_checks/contact_break.py` | Detector contact_break — ContactRecord hết hạn trong cửa sổ phân tích trong khi 2 segment CÒN render-overlap sau expiry; metric = min vertical gap (px) giữa 2 mask bbox trên các frame overlap sau expiry (T06A2 `measure_contact_break` semantics), classify qua T03A policy. Entry `detect_contact_break(args)->list[dict]`; `register()` qua registry singleton; `measure_contact_gap()` |
| `app/services/qc_checks/z_order_error.py` | Detector z_order_error — observed render order vs occlusion graph: mỗi edge mà occluder KHÔNG strictly above occludee = 1 violation (count, T06A2 `measure_z_order_error` semantics); order đọc từ lock manifest QUA public S09 `structural_lock.validate_manifest` (ưu tiên) / `render_order` / z_order fallback. Entry `detect_z_order_error`; `register()`; `measure_z_order_violations()` |
| `app/services/qc_checks/silhouette_clipping.py` | Detector silhouette_clipping — mask bbox cắt ra ngoài render frame boundary; clipped-pixel ratio (T06A2 `measure_silhouette_clipping` raw formula) classify qua policy: vượt boundary → blocker, cosmetic → warning. Entry `detect_silhouette_clipping`; `register()`; `measure_clipping_ratio()` |
| `tests/test_s11_t03c_contact_zorder_clipping_detectors.py` | 29 tests — pass/fail binary theo policy boundaries; severity recompute từ policy runtime (không hard-code); idempotency ×2 byte-identical; runner child-process ×2; lock manifest S09 public + invalid manifest fail-closed; T06A2 calibration provenance; isolation flags |

KHÔNG đụng: runner/registry/thresholds (read-only import), orchestrator (T03F), models.py, migrations/**, structural_evidence.py/structural_lock.py/compositing.py (chỉ consume — z_order_error DÙNG public `validate_manifest`), frontend/**, MAIN, s11-integration, T02B/T06A1/T06A2 files.

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — Đủ 3 reason codes contact_break/z_order_error/silhouette_clipping trong outcome + acceptance (Decision B).**
ĐẠT. Mỗi detector: `DETECTOR_NAME` ∈ binding `QC_REASON_CODES` (10-code enum sau correction cascade) — audit: `contact_break: in QC_REASON_CODES = True`, `z_order_error: True`, `silhouette_clipping: True` (evidence/audit.txt §1). Tests: `test_detectors_registered_under_owned_names` assert entry points `app.services.qc_checks.<name>:detect_<name>`; 3 test functions assert reason_code/category == tên binding. KHÔNG reason nào UNKNOWN.

**AC2 — Mỗi detector pass/fail case binary theo policy boundaries; không item khi trong biên.**
ĐẠT. Mọi severity mapping đọc runtime từ `thresholds.get_threshold` + `classify` (policy T03A FREEZE):
- contact_break: warn=4.0, blocker=16.0 (px) — gap < 4 → NO item; ==4 → warning; ==16 → blocker (test gap ở 25%/99.9%/100%/200%/400% warning boundary, expected recompute từ policy).
- z_order_error: warn=4, blocker=8 (count) — 2 violations → NO item; 4 → warning; 8 → blocker; correct order → 0 items.
- silhouette_clipping: warn=0.166666667, blocker=0.5 (ratio) — clip 25px (0.0833) → NO item; cosmetic band → warning; clip 50px (==0.5) → blocker.
- Không item khi trong biên: `test_contact_break_within_boundary_no_item`, `test_z_order_error_within_boundary_no_item`, `test_z_order_error_correct_order_no_item`, `test_silhouette_clipping_within_boundary_no_item`, `test_contact_break_not_expired_or_no_overlap_no_item`, `test_silhouette_clipping_out_of_window_segment_ignored` (segment ngoài window bị bỏ qua). PASSED (evidence/run1.txt).

**AC3 — Đọc renderer route/lock manifest QUA contract public S09 (repository structural_lock.py) nếu cần — không import private của lane khác.**
ĐẠT. `z_order_error.py` import DUY NHẤT `from app.persistence.structural_lock import validate_manifest` (public S09) — không import private/repository methods. `test_z_order_error_reads_lock_manifest_via_s09_public_contract`: manifest hợp lệ theo `validate_manifest` → order = manifest segments order → 8 violations blocker; manifest INVALID (unknown_key) → `StructuralLockParamsError` fail-closed đúng public S09 error. Evidence `order_source ∈ {lock_manifest, render_order, z_order}` trong mỗi item.

**AC4 — Evidence schema_version=1 content-derived, idempotent.**
ĐẠT. Mọi item: `evidence.schema_version == 1`; `evidence_window_key` = sha256 hex (64 chars) over canonical JSON (sort_keys, compact separators) của content core (reason_code/layer_ref/metric/window/contact|order_source|bbox/schema_version). Idempotent ×2: `test_evidence_idempotent_byte_identical_x2` (3 detectors, canonical JSON bằng nhau, window_key bằng) + `test_evidence_idempotent_across_runner_child_process` (2 child process qua bounded runner, output byte-identical) + `test_evidence_window_key_is_content_derived` (key == sha256 recompute; khác value → khác key). Audit §3–4: byte_identical=True ×2, window_key_identical=True ×2, schema_version=1, cross-process byte_identical=True (evidence/audit.txt).

## 3. Isolation (lane-B §4 / RESOURCE_PLAN §3)

- Basetemp ngắn Windows-native: `C:/Users/Admin/AppData/Local/Temp/s11t03c-*` (r1/r2/g1-g5/reg1/reg2 — mỗi run unique).
- `-p no:cacheprovider` mọi lệnh pytest; `env -u MOTIONFORGE_DATABASE_URL`.
- Tests KHÔNG đụng DB/SQLite; input là scene-graph/mask dicts thuần (ContactRecord/OcclusionRecord/z_order/mask_artifact JSON-serializable).
- Runner child process chạy detector thật qua `run_detector(deadline_sec=30, capture_cap_bytes=65536)` — T03A bounded harness, PYTHONPATH project root.
- Không media, không network, không commit binary; calibration fixtures (T06A2) đọc read-only.

## 4. Bằng chứng (docs/pm/sessions/S11-T03C/evidence/)

- `baseline_scope.txt` — baseline WAVE_BASE b34d801 → canonical c1a6777; final porcelain: đúng 4 allowlist + docs dir; HEAD bất biến.
- `run1.txt`, `run2.txt` — `29 passed` ×2 (3.17s / 3.15s, EXIT 0).
- `regression_t03a_t06a2.txt` — `64 passed in 8.74s` (T03A runner/registry/thresholds + T06A2 consume regression).
- `regression_t02b.txt` — `40 passed in 49.30s` (T02B Depends-on regression).
- `static_gates.txt` — ruff `All checks passed!` RUFF_EXIT=0; PY_COMPILE_OK; DIFF_CHECK_OK.
- `audit.txt` — binding enum 3/3; severity mapping (warn/block per metric + fixture provenance); idempotency ×2 in-process byte-identical + window_key identical + schema v1; cross-process runner ×2 byte-identical; hard-code scan boundary literals = NONE ×3.
- `gen_audit.py` — script tái tạo audit (đã chạy, kết quả audit.txt).

## 5. Self-review diff scope

`git status --porcelain` trước commit: 3 untracked detector files + 1 untracked test file + `docs/pm/sessions/S11-T03C/` — đúng allowlist. KHÔNG file modified; HEAD bất biến `c1a6777`; không push/merge/rebase/reset/clean/stash/force. Commit local, SHA ghi terminal/LOG.

## 6. Ghi chú ownership (cho Manager/Codex review)

- Detector contract: `detect(args)->list[dict]` (JSON-serializable, [] = pass) — runner T03A child protocol; `register()` idempotent vào singleton registry; version `1.0.0`.
- Threshold CHỈ đọc `thresholds.get_threshold`/`classify` — zero literal boundary trong 3 detector modules (hard-code scan NONE, audit §5).
- `contact_break`: metric = min vertical gap trên post-expiry overlap frames; contact CHƯA hết hạn (end >= window end) → pass. Chú ý fail-closed: gap > blocker boundary (sanity max = blocker) → THRESHOLD_INVALID → KHÔNG item (vượt calibrated envelope là uncalibrated).
- `z_order_error`: order_source precedence lock_manifest (public S09 validate) > render_order > z_order ascend. Edge ngoài analysis window không đếm.
- `silhouette_clipping`: segment render window ngoài analysis window bị bỏ; ratio dùng đúng T06A2 raw formula (clipped area / bbox area).
- T03F orchestrator sẽ consume `DetectorRun.output` (list items) — mỗi item đủ field QCItem candidate (reason_code/category/severity/layer_ref/evidence_window_key/evidence/detector/detector_revision/confidence/confidence_source/checkpoint_ref).
- Chưa chạm E06/S09 output; không resume session task khác (session rule W6: NEW SESSION); không đụng file T03B/T03D/T03E.
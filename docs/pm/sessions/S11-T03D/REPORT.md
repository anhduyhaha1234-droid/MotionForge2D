# S11-T03D — REPORT (W6, identity_drift + edge_halo + temporal_flicker)

Session: S11-T03D · Branch: codex/s11/t03d-0903w6 · HEAD: c1a6777864c1169435d7b7f263ce5fa7a0014c78
Worktree: C:\Users\Admin\MotionForge2D-worktrees\s11-t03d-0903w6
Model route: ocg/deepseek-v4-flash (provider custom, reasoning max, fallback OFF, TTFB 900)

## Write-set (allowlist, 4 file MỚI — không sửa file hiện hữu nào)
- `app/services/qc_checks/identity_drift.py` — REASON_CODE identity_drift, detector_revision 1.0.0, FEATURE_REVISION 1.0.0
- `app/services/qc_checks/edge_halo.py` — REASON_CODE edge_halo, detector_revision 1.0.0
- `app/services/qc_checks/temporal_flicker.py` — REASON_CODE temporal_flicker, detector_revision 1.0.0
- `tests/test_s11_t03d_identity_halo_flicker_detectors.py` — 11 test functions

## Acceptance (binary) — mapping

### AC1 — 3 reason codes ownership + partition (Decision B)
- identity_drift / edge_halo / temporal_flicker là REASON_CODE + CATEGORY của từng detector, xuất hiện trong outcome + acceptance này.
- Partition 8 overlay codes đúng: T03D sở hữu đúng 3; T03E (audio) không đụng; T03F 10 checks không bị ảnh hưởng (chỉ consume registry).
- Registry: cả 3 detector đăng ký qua T03A `register_detector` (identity-idempotent), entry_point `app.services.qc_checks.<module>:detect`, verified qua runner child-process:
  `registered: ['edge_halo', 'identity_drift', 'temporal_flicker']`; `runner: ok QC_RUNNER_OK -> code: THRESHOLD_BLOCKER items: 1`.

### AC2 — pass/fail binary theo policy; flip liền kề = blocker riêng
- Test `test_identity_drift_metadata_stable_pixels_cross_boundary_blocker`: metadata giữ nguyên, pixels đổi tới blocker boundary → 1 item identity_drift severity=blocker (repo persist, status=open). warning band (delta=3) → warning item; trong biên (delta=1) → zero item; vượt max calibrated envelope (delta=10) → THRESHOLD_INVALID + zero item (fail-closed).
- Test `test_identity_flip_metadata_change_near_identical_pixels_blocker`: pixels gần giống (pass band) nhưng metadata flip → item blocker RIÊNG (flip_kind=adjacent_metadata_change); visual metric VẪN được đo ghi trong cùng evidence (measured_distance < 2.0) — flip KHÔNG thay thế visual metric.
- Test `test_adjacent_flip_vs_cast_pin_authority_blocker_immediate`: role/instance đổi đột ngột giữa frame liền kề vs ProjectCastMapping pin (seed DB thật: character/pack published + 6 CORE_POSE_SLOTS assets/role/mapping; `evaluate_compatibility(...)` → compatible=True) → blocker ngay; variant compatible=False (stale_revision) → flip_kind=cast_authority_incompatible blocker ngay. Cả 2 persist qua repository với reason_code=identity_drift.

### AC3 — metric derive từ calibration T06A2 (không số tùy tiện)
- `test_thresholds_derive_from_t06a2_calibration_raw_values`: đọc fixture `tests/fixtures/s11_qc/calibration/identity_halo_flicker.json`; assert với từng metric: warning_boundary == raw level-2, blocker_boundary == raw level-4, kind=increasing, sanity min=0; classify đúng warning/blocker tại các giá trị đó.
- identity distance: RMS pixel diff (đơn vị px, khớp unit policy); halo: ring_area/(2π·inner_radius) — formula y hệt T06A2 `measure_edge_halo`; flicker: mean(|diff(luminance)|) — formula y hệt T06A2 `measure_temporal_flicker`. Half-open ring sampling `[inner_r, inner_r+r)` tái tạo 4 raw values chính xác (0.939014164 / 2.021267777 / 4.217605992 / 8.737606376 — verified script).
- Zero network/model download; feature local deterministic (flatten crop / mask count / luminance diff), feature_revision ghi trong evidence.

### AC4 — evidence schema_version=1 content-derived idempotent
- `test_rerun_same_evidence_byte_identical_idempotent`: detect ×2 → JSON byte-identical; repo.create ×2 cùng natural key → cùng row id, evidence equal, list total=1.
- Evidence ghi: artifact hashes (pinned_reference + per-frame / rendered + expected mask), frame/window, mask/crop revision, feature revision, measured distance (reference_distance_max_px, max_adjacent_distance_px, measured_distance / halo_width_px + ring_area_px + inner_circumference_px / mean_interframe_luminance_delta), policy ref (policy_id + content_hash), schema_version=1.
- `evidence_window_key` = sha256(canonical evidence)[:32] content-derived.

### C4-F5 (5) — không UNKNOWN/deferred
- `test_no_unknown_or_deferred_reason_code_any_detector`: 3 detector → reason_code ∈ {identity_drift, edge_halo, temporal_flicker}; code ∈ {THRESHOLD_PASS, THRESHOLD_WARNING, THRESHOLD_BLOCKER, THRESHOLD_INVALID}; không chuỗi "UNKNOWN"/"deferred" trong toàn bộ result JSON; mọi item reason/category = detector owner.

### Fail-closed bổ sung
- `test_evidence_hash_mismatch_fail_closed_invalid`: sha256 tampered → THRESHOLD_INVALID + zero item (không fabricate measurement).

## Raw outputs (đã chạy thật)
```
RED:    ERROR tests/test_s11_t03d_identity_halo_flicker_detectors.py
        ModuleNotFoundError: No module named 'app.services.qc_checks.edge_halo'
GREEN:  11 passed in 7.99s            (basetemp %LOCALAPPDATA%/Temp/s11t03d_green5)
R1:     11 passed in 7.94s            (s11t03d_r1, fresh root)
R2:     11 passed in 8.06s            (s11t03d_r2, fresh root)
COMBO1: 64 passed in 33.72s           (T03D + T03A runner_registry + T03A thresholds_policy + T02B repository)
COMBO2: 64 passed in 30.51s           (post static-fix, same 4 test files)
RUFF:   ruff check --select F <4 files> -> All checks passed!  (exit 0)
COMPILE: py_compile 4 files -> OK
DIFF:   git diff --check -> OK
LEGACY: grep legacy reason_code trong 4 file = 0 (identity/flicker cũ)
SMOKE:  run_detector('temporal_flicker', child process) -> QC_RUNNER_OK, code THRESHOLD_BLOCKER, items 1
```

## Isolation
- basetemp Windows-native NGẮN `%LOCALAPPDATA%/Temp/s11t03d_*` (tránh WinError 206 trên path dài).
- `-p no:cacheprovider`; `env -u MOTIONFORGE_DATABASE_URL`; per-test SQLite temp riêng; không đụng MAIN/canonical.

## Scope self-review
- `git status --porcelain` trước stage: chỉ 4 file allowlist untracked — không file nào khác (runner/registry/thresholds/models/migrations/project_cast/compositing/frontend đều chỉ import read-only hoặc không đụng).
- Không sửa file hiện hữu; không push/merge/rebase/reset/clean/stash.

## Terminal
**TASK_SUBMITTED** — commit local `529d2a4fee5e3bde5af82b7b02fa8b6f79de4106` trên codex/s11/t03d-0903w6 (parent c1a6777864c1169435d7b7f263ce5fa7a0014c78), chờ Manager verify W6 + integration.
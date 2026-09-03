# S11-T03D — LOG (W6, identity_drift + edge_halo + temporal_flicker)

Session: S11-T03D (resume sau correction cascade schema — branch fast-forward tới canonical c1a677786)
Branch: codex/s11/t03d-0903w6
Worktree: C:\Users\Admin\MotionForge2D-worktrees\s11-t03d-0903w6
WAVE_BASE: b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9 → fast-forward HEAD c1a6777864c1169435d7b7f263ce5fa7a0014c78
Model: ocg/deepseek-v4-flash (custom, reasoning max, fallback OFF, TTFB 900)

## 1. Baseline (resume)
- `git status --porcelain` = 0 (trống); branch `codex/s11/t03d-0903w6`; HEAD = c1a6777864c1169435d7b7f263ce5fa7a0014c78 (canonical sau fix enum).
- Binding enum xác nhận: `QC_REASON_CODES` / `QC_ITEM_CATEGORIES` = 10 codes gồm identity_drift, edge_halo, temporal_flicker (models.py).
- Alembic head duy nhất: f9a0b1c2d3e4 (fix migration đã merge; chain a10b11c12d3e <- e11a02a2026f <- f9a0b1c2d3e4).
- Không có draft file còn lại (porcelain=0, chưa tồn tại docs/pm/sessions/S11-T03D/).
- Binding plan SHA: 342479267086485ef6fd44cb8b3a5f94e6f7b1afcc4439afda2910068fc76f4f (đối chiếu task block T03D lines 227–242, overlay MAIN docs/pm/TARGET_PROFILE_2D_SOURCE_LOCKED.md §S11).

## 2. RED (viết test trước)
- `tests/test_s11_t03d_identity_halo_flicker_detectors.py` viết trước (11 test functions).
- Chạy: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t03d_identity_halo_flicker_detectors.py -p no:cacheprovider --basetemp=%LOCALAPPDATA%/Temp/s11t03d_red1 -q`
  → `ERROR tests/... ModuleNotFoundError: No module named 'app.services.qc_checks.edge_halo'` (RED thật).

## 3. Implement (chỉ allowlist T03D)
- `app/services/qc_checks/identity_drift.py` — visual identity distance (RMS pixel diff giữa current rendered/masked crop vs pinned reference artifact+sha256 VÀ adjacent frames; max = measured), fail-closed identity flip metadata/cast-pin (flip_kind: cast_authority_incompatible / adjacent_metadata_change / metadata_vs_pin) = blocker RIÊNG, KHÔNG thay thế visual metric; feature local deterministic FEATURE_REVISION=1.0.0; hash evidence fail-closed THRESHOLD_INVALID; register_detector("identity_drift", "...:detect").
- `app/services/qc_checks/edge_halo.py` — mean halo width px = ring area / (2π·inner_radius) (đúng formula T06A2 measure_edge_halo, half-open ring sampling); register_detector("edge_halo").
- `app/services/qc_checks/temporal_flicker.py` — mean inter-frame luminance delta (đúng formula T06A2 measure_temporal_flicker); register_detector("temporal_flicker").
- Threshold đọc CHỈ-ĐỌC từ T03A `get_threshold(METRIC)` + `classify(...)`; round về calibration precision (9 decimals) trước classify — raw values T06A2 được lưu round-9.
- Evidence: schema_version=1, content-derived, evidence_window_key = sha256(canonical evidence)[:32]; ghi artifact hashes + frame/window + mask/crop revision + feature revision + measured distance.

## 4. Vòng sửa (từ real output)
1. `int(100.0 + 0.5)` truncate → fixture assertion dùng pass-band (`< 2.0`) thay vì ==0.5.
2. `zip(luminance, luminance[1:], strict=True)` → ValueError (zip strict cần cùng độ dài) → `zip(luminance[:-1], luminance[1:], strict=True)` (2 chỗ).
3. Discretization mask `<=` lệch raw T06A2 (r=2 → 1.9894 < warning 2.0212) — chuyển sang half-open `d < inner_r + halo_r` → ring `[inner_r, inner_r+r)` → tái tạo CHÍNH XÁC 4 raw values T06A2 (0.939014164 / 2.021267777 / 4.217605992 / 8.737606376, verified bằng script).
4. `classify` fail-closed envelope: value > max calibrated (level-4 raw) → THRESHOLD_INVALID (policy T03A cố định) → test dùng delta đúng boundary 8.0 cho blocker; delta 10.0 = fail-closed INVALID + zero item (giữ làm assertion).
5. Flip được detect nhưng top-level code không elevate → thêm: flip && code==PASS → status/code = blocker (flip fail-closed dominates, vẫn không thay visual item).
6. Round 9 decimals trước classify (flicker/halo) → boundary hits deterministic.
7. ruff F: bỏ import thừa (CODE_THRESHOLD_INVALID, STATUS_INVALID, pytest, VideoItem) + F841 engine → clean.

## 5. GREEN
- `--basetemp=%LOCALAPPDATA%/Temp/s11t03d_green5`: **11 passed in 7.99s**.
- Determinism ×2 fresh roots:
  - `s11t03d_r1`: **11 passed in 7.94s**
  - `s11t03d_r2`: **11 passed in 8.06s**
- Combo với dependency tests (1 process, registry singleton chung):
  - `s11t03d_combo1` (T03D + T03A runner_registry + T03A thresholds_policy + T02B repository): **64 passed in 33.72s**
  - `s11t03d_combo2` (post static-fix): **64 passed in 30.51s**
- Runner child-process smoke (T03A `run_detector` + entry point `app.services.qc_checks.temporal_flicker:detect`): `runner: ok QC_RUNNER_OK -> code: THRESHOLD_BLOCKER items: 1`; registry names = [edge_halo, identity_drift, temporal_flicker].
- Static: `ruff check --select F` 4 files → **All checks passed** (exit 0); `py_compile` 4 files → OK; `git diff --check` → OK.

## 6. Isolation flags
- basetemp: `%LOCALAPPDATA%/Temp/s11t03d_*` (Windows-native NGẮN) — tránh WinError 206.
- `-p no:cacheprovider` mọi lần chạy.
- `env -u MOTIONFORGE_DATABASE_URL` mọi lần chạy.
- DB: per-test temp SQLite `create_engine_for_path(tmp_path/"t03d.db")` + `Base.metadata.create_all` — không đụng MAIN data.

## 7. Scan trước commit
- Legacy reason codes (`reason_code='identity'|'flicker'`) trong 4 file allowlist: **0 match** (grep -c từng file = 0).
- `git status --porcelain`: chỉ 4 file allowlist untracked; không file nào khác bị đụng.

## 8. Commit
- Stage: đúng allowlist + `docs/pm/sessions/S11-T03D/**`.
- Commit local `529d2a4fee5e3bde5af82b7b02fa8b6f79de4106` trên codex/s11/t03d-0903w6 (parent c1a6777864c1169435d7b7f263ce5fa7a0014c78); không push/merge/rebase/reset/clean/stash.

## 9. Trạng thái
**TASK_SUBMITTED** — commit 529d2a4 local; chờ Manager verify W6.
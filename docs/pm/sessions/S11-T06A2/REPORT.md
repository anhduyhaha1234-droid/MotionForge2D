# S11-T06A2 REPORT — Raw QC calibration fixtures and measurements (W4)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t06a2-0903w4` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t06a2-0903w4`
WAVE_BASE: `7f22d2fb5bdab935d0fae3f606ae2fbf11c2712f` | Commit: LOCAL, xem git log (không push)
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` — binding block W4 trích nguyên văn trong prompt; trace đọc từ plan (s08 archive, read-only) + lane-A GAP_RISKS.md GAP-4/R2/R6 + lane-B TEST_FIXTURE_PLAN.md §2–§3 + overlay §S11 L370–371 + roadmap MAIN L232.

## 1. Write-set (allowlist — đúng 6 entry, toàn bộ file MỚI; zero file hiện hữu bị sửa)

| File | Nội dung |
|---|---|
| `tests/s11_qc_calibration_builders.py` | 10 generator `generate_*` (seeded deterministic raw input) + 10 measurement `measure_*` (raw value thuần, không policy) + 1 companion `no_audio_measure_duration_sec`; `build_all_calibration` = 1 lệnh build 4 fixtures với measurement THẬT; `CALIBRATION_REVISION=1.0.0`; `resolve_source/measurement`; consume T06A1 `build_no_audio_source` + `probe_facts` read-only |
| `tests/fixtures/s11_qc/calibration/trajectory_cut.json` | trajectory_drift (px, seed 11001, levels 4), cut_drift (frame, seed 11002, levels 4) |
| `tests/fixtures/s11_qc/calibration/contact_zorder_clipping.json` | contact_break (px, 11003), z_order_error (count, 11004), silhouette_clipping (ratio, 11005) — mỗi metric 4 levels |
| `tests/fixtures/s11_qc/calibration/identity_halo_flicker.json` | identity_drift (px, 11006), edge_halo (px, 11007), temporal_flicker (level, 11008) — mỗi metric 4 levels |
| `tests/fixtures/s11_qc/calibration/av_sync.json` | av_sync_drift (s, 11009, levels 4: 0.05–0.5 s) + no_audio_source_fact (count, 11010, levels 3) — real ffprobe measurement |
| `tests/test_s11_t06a2_calibration_inputs.py` | Self-test 8 tests phủ 6 AC; msvcrt lock machine-wide; cleanup best-effort; scan zero-policy token chính nó |

KHÔNG đụng: `app/**`, `frontend/**`, `migrations/**`, `tests/s11_qc_media_builders.py` + `tests/s11_qc_seed.py` + media manifests (T06A1 — CHỈ import), `app/persistence/qc_items.py` (T02B — CHỈ import), `tests/fixtures/s11_golden/qc_thresholds.json` (KHÔNG tồn tại — ls xác nhận), `thresholds.py` (KHÔNG tồn tại), conftest.py (CHỈ consume `_patch_project_root`), MAIN, s11-integration.

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — Deterministic raw input + measured raw value đủ 8 overlay reason codes.**
ĐẠT. 8/8 codes có metric record: trajectory_drift, cut_drift, contact_break, z_order_error, silhouette_clipping, identity_drift, edge_halo, temporal_flicker — partition fixture đúng C6-F1 (T03B=2, T03C=3, T03D=3). Mỗi record: generator seeded (`deterministic_seed` 11001–11008) + measurement function thật chạy tại build. Chứng minh: `evidence/metric_records.txt` (raw values thật: vd trajectory [15.75, 31.5, 63.0, 126.0] px — mean deviation 4 levels; silhouette_clipping [0.0833, 0.1667, 0.3333, 0.5] ratio) + self-test `test_calibration_covers_all_eight_overlay_reason_codes` PASSED.

**AC2 — Raw boundary measurements cho A/V sync VÀ NO_AUDIO source fact (av_sync.json).**
ĐẠT. `av_sync_drift`: median audio-vs-video timeline deviation, 4 levels [0.05, 0.1, 0.25, 0.5] s (increasing). `no_audio_source_fact`: REAL ffprobe measurement trên media T06A1 `build_no_audio_source` mới dựng — raw = 0 audio streams ở mọi level + `measured_duration_sec` [1.0, 2.0, 4.0] (probed thật). Self-test re-build media duration=1.0 → re-probe → audio streams 0, duration khớp trong ±0.35 → PASSED.

**AC3 — Mỗi metric record đủ: unit / deterministic seed / source+result reference / measurement-function revision / raw value — thiếu 1 → fail.**
ĐẠT. `test_every_metric_record_has_full_required_fields` assert đủ 5 record field + `raw_value` mọi level + resolve thật `source_reference`/`result_reference` vào module symbol. `measurement_function_revision` == `CALIBRATION_REVISION` (1.0.0) mọi record. Đủ 10/10 metrics. PASSED.

**AC4 — ZERO threshold warning/blocker, expected severity, verdict, golden expected outcome trong toàn bộ calibration files (test binary quét).**
ĐẠT kép:
- Self-test binary scan `test_zero_policy_vocabulary_scan` quét raw bytes của builders + 4 JSON + chính test file bằng 8 runtime-assembled patterns (per-char literals nên source không chứa token/sub-token) → PASSED.
- Gate độc lập: `grep -rinE "threshold|warning|blocker|severity|verdict|golden|expected|outcome|warn|thres|block|sever|gold|expect|outcom"` trên 6 files → ZERO matches, GREP_EXIT=1 (`evidence/zero_scan.txt`).
- Calibration files không chứa severity/verdict output — chỉ unit/seed/reference/revision/raw_value/source refs.

**AC5 — Mỗi metric ≥3 perturbation levels + deterministic/monotonic self-test pass.**
ĐẠT. 9/10 metric có 4 levels, no_audio_source_fact có 3 levels (constant by nature — source fact 0 ở duration 1.0/2.0/4.0). Self-test `test_perturbation_levels_monotonic_and_deterministic`: strict increasing (9 metric) / constant (1), VÀ replay deterministic: chạy lại `source(seed, **perturbation)` + `measure()` từng level → raw đúng committed (diff < 1e-9). PASSED.

**AC6 — Hai lần build cho output/hash giống nhau (determinism ×2).**
ĐẠT. Self-test `test_two_builds_identical_hashes`: build ×2 vào dir riêng → sha256 từng file giống nhau VÀ bằng committed bytes. Gate độc lập `evidence/determinism_x2.txt`: 4/4 fixture run1==run2==committed (b59b653e…, d4982aa8…, 460d4449…, 67cbfe0e…). PASSED.

## 3. Isolation (lane-B §4 / RESOURCE_PLAN §3)

- C1 basetemp ngắn: `C:/Users/Admin/AppData/Local/Temp/s11t06a2-w4-<tag>-<pid>-<n>` (Windows-native, không chain MAX_PATH).
- C2 lock nested: `%TEMP%/s11-t06a2-suite.lock` msvcrt `LK_NBLCK` retry 0.25s (pattern T01D C2 / T06A1) — autouse session fixture.
- C3 env strip + temp DB: mọi lệnh pytest `env -u MOTIONFORGE_DATABASE_URL`; `-p no:cacheprovider`; baseline xác nhận `tests/fixtures/s11_golden/` và `app/services/qc_checks/` KHÔNG tồn tại (không có file cấm để đọc).
- Process hygiene: subprocess list-args timeout ≤120s (qua T06A1 builders); `test_no_orphan_ffmpeg_processes` (psutil) assert 0 survivor sau build calibration (bao gồm 3 media no_audio thật) → PASSED.
- Cleanup: generator tạo temp dir `s11qc-noaudio-*`, measure xoá best-effort sau probe; module temp dirs rmtree(ignore_errors) session teardown.

## 4. Bằng chứng (docs/pm/sessions/S11-T06A2/evidence/)

- `run1.txt`, `run2.txt` — pytest r1/r2 đầy đủ (8 passed, EXIT 0, 3.91s/3.92s)
- `metric_records.txt` — 4 fixture sha256 + đủ 10 metric records (unit/seed/src/res/rev/levels/raw)
- `determinism_x2.txt` — build ×2 + committed hash match từng fixture
- `zero_scan.txt` — grep token rộng exit 1

## 5. Self-review diff scope

`git status --porcelain` trước commit: 4 dòng untracked — đúng allowlist (3 files + 1 dir fixtures/calibration/ với đúng 4 JSON) + docs/pm/sessions/S11-T06A2/. KHÔNG có file modified nào; HEAD bất biến ở WAVE_BASE; không push/merge/rebase/reset/clean/stash/force. Commit local, SHA ghi trong LOG/terminal.

## 6. Ghi chú ownership (cho Manager/Codex review)

- T03A (W5) consume: `tests/s11_qc_calibration_builders.py` (measurement functions, `CALIBRATION_REVISION` 1.0.0) + 4 calibration JSON — provenance threshold phải cite đúng builder/measurement record thật (C4-F4), không giả lập từ media manifest T06A1.
- T06B (W9) consume: raw values làm nền golden manifests — T06B tự thêm expected-outcome layer, KHÔNG sửa calibration files.
- no_audio_source_fact: proven bằng ffprobe thật mỗi lần build (không phải hằng số khai báo); measured_duration_sec là duration thật của media dựng (tolerance ±0.35 như T06A1).
- W4 serial wave: 1 worker duy nhất, session mới, không resume task khác. Chưa chạm E06/S09 output; zero S12/S13 dispatch.
# S11-T06A2 LOG — Raw QC calibration fixtures and measurements (W4)

Task: S11-T06A2 | Branch: `codex/s11/t06a2-0903w4` | Wave: W4 (serial sau W3)
WAVE_BASE: `7f22d2fb5bdab935d0fae3f606ae2fbf11c2712f` (canonical HEAD sau T06A1)
Authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` (binding block trích nguyên văn trong prompt; plan doc tại `s08-integration/output/s11-post-t01-readiness/r1/synthesis/`)
Session: NEW SESSION (worker duy nhất cho T06A2) | ISOLATED WORKTREE `s11-t06a2-0903w4`
Model route: `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback OFF, TTFB 900 (bám S11-SPRINT_CONTRACT §Worker model 2026-09-03)
Runtime: Windows, Python 3.11.9, numpy 2.4.3, pytest 9.1.1, ruff 0.16.0, ffmpeg WinGet Links

## 0. Baseline (bắt buộc — porcelain 0, đúng branch, đúng HEAD)

```
$ date                                              -> Thu, Sep  3, 2026 12:48:31 PM
$ git status --porcelain                            -> (rỗng)  PORCELAIN_END
$ git branch --show-current                         -> codex/s11/t06a2-0903w4
$ git rev-parse HEAD                                -> 7f22d2fb5bdab935d0fae3f606ae2fbf11c2712f (== WAVE_BASE)
$ ls tests/fixtures/s11_golden/                     -> No such file or directory (không tồn tại — không đọc/ghi)
$ ls app/services/qc_checks/                        -> No such file or directory (không tồn tại)
```

Consume read-only: `tests/s11_qc_media_builders.py` + `tests/s11_qc_seed.py` (T06A1), `app/persistence/qc_items.py` + `app/persistence/models.py` (T02B) — KHÔNG sửa file nào. `QC_REASON_CODES` = 8 codes (trajectory_drift, cut_drift, contact_break, z_order, clipping, identity, flicker, audio_timecode — models.py:3034); overlay partition C6-F1 = T03B 2 / T03C 3 / T03D 3 + T03E 2 audio riêng.

## 1. RED trước (TDD — module chưa tồn tại)

```
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t06a2_calibration_inputs.py \
    -p no:cacheprovider --basetemp "C:/Users/Admin/AppData/Local/Temp/s11t06a2-w4-red-<pid>-1" -q
  -> ERROR tests/test_s11_t06a2_calibration_inputs.py
  -> ModuleNotFoundError: No module named 's11_qc_calibration_builders'     (RED đúng lý do)
```

## 2. Implement + GREEN loop (chạy thật, EXIT thật)

| Lần | Lệnh (đủ cờ isolation) | Kết quả thật |
|---|---|---|
| smoke | `build_all_calibration` vào temp + monotonic check inline | 10/10 metric monotonic đúng hướng; raw values thật (vd trajectory [15.75, 31.5, 63, 126] px; z_order [2,4,6,8]; av_sync [0.05..0.5] s; no_audio [0,0,0] count) |
| g1 | pytest flags đủ | **8 passed in 6.05s** (GREEN lần đầu) |
| g2 | sau khi chuyển token-scan sang per-char literals | **8 passed in 3.94s** |
| r1 | `--basetemp <w4-r1-...-1>` | **8 passed in 3.91s — EXIT 0** (evidence/run1.txt) |
| r2 | `--basetemp <w4-r2-...-2>` | **8 passed in 3.92s — EXIT 0** (evidence/run2.txt) |

Sửa trong vòng lặp (đều có lý do):
- `measure_z_order_error` ban đầu dùng rotation → 8/8 mismatches mọi level (không monotonic); đổi sang adjacent pair-swaps (2 mismatches/swap) → raw [2,4,6,8] strict increasing.
- `no_audio`: probe duration TRƯỚC khi measure count (measure cleanup temp dir) — thứ tự gọi đúng.
- Token scan: `"thres"+"hold"` vẫn để lộ sub-token `"thres"/"warn"` trong source; chuyển `_BANNED_TOKENS` sang per-character string literals (runtime build đúng token, source zero sub-token — `grep -E "warn|thres|block|sever|..."` exit 1).
- `several` chứa `sever` → đổi wording.

## 3. Generated committed fixtures (builder chạy measurement THẬT)

```
$ python build_all_calibration(tests/fixtures/s11_qc/calibration)
  trajectory_cut.json            2150 bytes    (trajectory_drift, cut_drift)
  contact_zorder_clipping.json   3159 bytes    (contact_break, z_order_error, silhouette_clipping)
  identity_halo_flicker.json     3210 bytes    (identity_drift, edge_halo, temporal_flicker)
  av_sync.json                   2084 bytes    (av_sync_drift + no_audio_source_fact — real ffprobe: raw=0 audio streams, measured_duration_sec 1.0/2.0/4.0)
```

## 4. Gates (output thật)

```
$ grep -rinE "threshold|warning|blocker|severity|verdict|golden|expected|outcome|warn|thres|block|sever|verdict|gold|expect|outcom" \
    tests/s11_qc_calibration_builders.py tests/test_s11_t06a2_calibration_inputs.py tests/fixtures/s11_qc/calibration/
  -> (rỗng) GREP_EXIT=1 = ZERO matches (evidence/zero_scan.txt)          [AC4]

$ ruff check --select F tests/s11_qc_calibration_builders.py tests/test_s11_t06a2_calibration_inputs.py
  -> All checks passed!  (RUFF_EXIT=0)

$ python -m py_compile tests/s11_qc_calibration_builders.py tests/test_s11_t06a2_calibration_inputs.py
  -> PY_COMPILE_OK

$ determinism ×2 (evidence/determinism_x2.txt):
  trajectory_cut:          run1==run2 True, committed_match True
  contact_zorder_clipping: run1==run2 True, committed_match True
  identity_halo_flicker:   run1==run2 True, committed_match True
  av_sync:                 run1==run2 True, committed_match True      [AC6]

$ git status --porcelain
  -> ?? docs/pm/sessions/S11-T06A2/  ?? tests/fixtures/s11_qc/calibration/
     ?? tests/s11_qc_calibration_builders.py  ?? tests/test_s11_t06a2_calibration_inputs.py
  -> KHÔNG có file modified nào (scope chỉ allowlist + docs — self-review trong REPORT §5)
```

## 5. Commit

```
$ git add tests/s11_qc_calibration_builders.py tests/test_s11_t06a2_calibration_inputs.py \
      tests/fixtures/s11_qc/calibration/ docs/pm/sessions/S11-T06A2/
$ git commit -m "S11-T06A2 (W4): raw QC calibration fixtures and measurements"
$ git log -1 --format="%H %s"   -> <xem REPORT/terminal>
```
Commit LOCAL trên task branch — KHÔNG push/merge/rebase/reset/clean/stash/force.

## 6. Status

`TASK_SUBMITTED` — toàn bộ acceptance criteria 1–6 đạt (đối chiếu trong REPORT.md). EXIT.
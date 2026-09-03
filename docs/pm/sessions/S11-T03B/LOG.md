# S11-T03B LOG — trajectory_drift + cut_drift detectors (W6)

Branch/Worktree: `codex/s11/t03b-0903w6` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03b-0903w6`
HEAD: `c1a6777864c1169435d7b7f263ce5fa7a0014c78` (canonical sau defect-schema fix, đã fast-forward từ WAVE_BASE `b34d801c…` — HEAD bất biến suốt session, commit local cuối).
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` (binding block W6·T03B; trace: roadmap MAIN L229, overlay §S11 L370–371, lane-A QC_DOMAIN_CONTRACT §1.2 trajectory/cut, lane-B CHECK_CAPABILITY_MATRIX §6 Trajectory/Cut drift MISSING → implemented).

Mọi lệnh chạy từ worktree task với isolation: `env -u MOTIONFORGE_DATABASE_URL python -m pytest -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/<short-tag>` (Windows-native, ngắn, unique per run).

| Thời điểm | Hành động | Kết quả thật |
|---|---|---|
| 2026-09-03 pre-pause | Baseline trước implement: porcelain=0, HEAD=b34d801 (WAVE_BASE cũ), read contract T03A (registry/runner/thresholds), T02B repo, timebase/scene_detector, T06A1 media builders + manifest, T06A2 calibration builders | RED: test viết TRƯỚC implementation → `ModuleNotFoundError: No module named 'app.services.qc_checks.cut_drift'` (evidence/red.txt) |
| PAUSE | Worker bị pause vì defect schema enum QC reason codes — draft 3 file (2 detectors + 1 test) để nguyên untracked | — |
| RESUME | Fast-forward branch tới canonical `c1a6777` (fix merged, alembic head f9a0b1c2d3e4). Re-verify: enum mới 10 codes (trajectory_drift/cut_drift đều có — write-set KHÔNG đổi tên); policy hash `de215c62…` KHÔNG đổi; boundary trajectory 31.5/126.0 px, cut 3/12 frame; T02B API không đổi | evidence/baseline.txt; old-name scan trong write-set = 0 hits |
| Fix test 1 | `_cut_args` default 2 boundaries (position 0+1) trong khi mọi case truyền 1 cut → detector fail-closed `QC_CUT_INVALID_ARGS` (đúng contract, sai helper). Fix: default 1 boundary (position 1, start_frame 60 — scene 0 start không phải cut) | — |
| Fix test 2 | `_patched_policy` đọc `load_policy` đã bị patch lần 1 → copy-của-copy giữ blocker=80 → warning=200 không có hiệu lực. Fix: capture `_FROZEN_LOAD_POLICY` tại import (bản gốc lru_cached) | — |
| Fix test 3 | `QCItemRecord` không có attr `evidence_json` (DTO chứa `evidence` dict). Fix: so sánh byte qua `canonical_evidence_json(record.evidence)`; commit row trước recheck idempotency (session đóng = rollback) | — |
| GREEN ×3 | FOCUSED 23 tests, basetemp s11t03b_g1/g2/g3 | `23 passed in 16.11s` / `15.41s` / `15.41s` (evidence/run1..3.txt) |
| Probe evidence | Script độc lập chạy thật: policy identity, classify tại boundary, evidence byte-identical ×2, natural-key reuse, test-copy flip | `EVIDENCE_PROBE_OK` — checks.txt (xem REPORT §2) |
| Static gates | `ruff check --select F` 3 files; `py_compile` 3 files | `All checks passed!` (RUFF_EXIT=0); PY_COMPILE_OK (evidence/static_gates.txt) |
| Regression | T03A policy+runner, T02B repo+api, T06A2 calibration, + T03B focused (6 files) | `98 passed, 23 warnings` (Starlette/httpx deprecation có sẵn từ fastapi TestClient — 0 warning từ write-set) (evidence/regression.txt) |
| Final scope | `git status --porcelain` | Chỉ 4 untracked: 2 detectors + 1 test + docs/pm/sessions/S11-T03B/; KHÔNG file modified; HEAD bất biến |
| Commit | Stage CHỈ allowlist + `docs/pm/sessions/S11-T03B/**`; commit local | SHA ghi trong REPORT.md / terminal |

Không push/merge/rebase/reset/clean/stash/force. KHÔNG đụng: s11-integration canonical, MAIN, runner.py/registry.py/thresholds.py + qc_thresholds.json (CHỈ ĐỌC), orchestrator.py (chưa tồn tại — T03F), models.py/migrations/** (chỉ import/enum consume), qc_items repo/router (chỉ import), scene_detector.py/timebase.py (consume), frontend/**, T03C/D/E write-set.
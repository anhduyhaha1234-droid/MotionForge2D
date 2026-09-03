# S11-T06B LOG — Golden expected-outcome manifests (W9)

Session: NEW (worker duy nhất, isolated worktree). Không resume task khác.
Branch: `codex/s11/t06b-0903w9` | Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s11-t06b-0903w9`
WAVE_BASE: `b2501598078c702d875f57ac0a17a78e3e40237b` (canonical HEAD sau T03G, porcelain=0)
Model: `ocg/deepseek-v4-flash` (custom/9Router, reasoning max, fallback OFF, TTFB 900s)

## Baseline (policy hash neo — T03A frozen, đọc CHỈ)

`tests/fixtures/s11_golden/qc_thresholds.json` (calibration_revision=1.0.0):
- policy_id=`s11-qc-thresholds-v1`
- content_hash=`de215c6243e1c6bf300e2bfa1c8024fbda6d0358ecf3cad1730781e37419ea24`
- 10 metrics = 9 reason codes (mọi code trừ audio_missing — fact detector, không threshold) + no_audio_source_fact; boundary set 16 unique.

## Sequence (raw)

1. `git status --porcelain` -> rỗng (porcelain=0); `git rev-parse HEAD` = b2501598... (đúng WAVE_BASE).
   Worktree thực tế `s11-t06b-0903w9` (prompt ghi `s11-t06b-t06b-0903w9` — thư mục động, đúng convention `codex/s11/t06b-0903w9`).
2. Consume-point scan: T06A1 builders (`s11_qc_media_builders.py` MEDIA_SCENARIOS 7, `build_*` x7),
   seed (`s11_qc_seed.py`: seed_workspace_project_video / seed_qc_items_for_manifest / seed_all_reason_codes),
   T03F orchestrator `app/services/qc_checks/orchestrator.py::run_full_check_set`,
   T03G `app/persistence/qc_check_runs.py::check_run_readiness` (verdicts not_run/ready/blocked; run_state never_run/queued/failed/completed/stale),
   enum binding `app/persistence/models.py` QC_REASON_CODES (10) / QC_ITEM_SEVERITIES (blocker, warning, info) / QC_ITEM_STATUSES (open, acknowledged, resolved, dismissed).
3. RED: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t06b_golden_manifests.py -v -p no:cacheprovider --basetemp C:/Users/Admin/AppData/Local/Temp/s11t06b-w9-red-1`
   -> `14 failed in 1.99s` (FileNotFoundError golden_manifests/*.json — manifests chưa tồn tại, đúng thiết kế RED).
4. Viết 5 golden manifests (schema v1: schema_version / manifest_id / scenario / policy_ref / consumes
   / expected_qc_items / expected_readiness.before/after[/after_rerun/after_resolve] / expected_rerun_scope
   (scenario_d), queue_semantics (e2e_03), viewport+expected_rendering (e2e_04)).
5. GREEN v1: `14 passed` -> còn 4 fail thật (canonical sorting, ready_scenes token, rendering flag,
   policy metrics set = 9 codes + no_audio_source_fact). Sửa 4 chỗ -> GREEN ×2:
   `14 passed in 1.70s` (r1) + `14 passed in 1.69s` (r2), basetemp ngắn unique mỗi run.
6. Static gates: `ruff check --select F` -> All checks passed (sửa 6 lỗi: F401 x4, F541 x1, F841 x1);
   `python -m py_compile tests/s11_qc_golden.py tests/test_s11_t06b_golden_manifests.py` -> OK;
   JSON 5/5 valid.
7. Binary scan độc lập (script temp ngoài repo, `%TEMP%/s11t06b_scan.py`):
   ZERO_BOUNDARY_SCAN: PASS — 0 collisions trên 5 manifests; hash_match=True 5/5.
8. Final: `14 passed in 1.66s` (basetemp s11t06b-w9-final-1) — evidence/run_final.txt.
9. Scope review: `git status --porcelain` = đúng 7 path allowlist (5 manifest + helper + test) — 0 stray.

## Isolation flags (mọi lệnh pytest)

- `--basetemp C:/Users/Admin/AppData/Local/Temp/s11t06b-w9-<tag>-1` (Windows-native NGẮN, unique)
- `-p no:cacheprovider`
- `env -u MOTIONFORGE_DATABASE_URL` (suite này thuần JSON schema + import resolution — zero DB touch)

## Consume contract (không sửa file ngoài allowlist)

- T03A policy: CHỈ ĐỌC hash (baseline trên); manifest chỉ giữ policy_ref (id + hash).
- T06A1: reference builder theo TÊN trong `consumes.media` (scenario/builder/manifest) + seed helpers theo tên.
- T06A2 calibration, T03F orchestrator, T03G read authority: consume theo tên (test resolve importable callable).
- KHÔNG đụng: thresholds.py/qc_thresholds.json (ngoài đọc), app/**, frontend/**, MAIN, s11-integration.

## Commit

Local commit trên task branch, allowlist + `docs/pm/sessions/S11-T06B/**` — SHA xem REPORT.
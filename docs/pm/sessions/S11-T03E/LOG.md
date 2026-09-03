# S11-T03E LOG — audio_missing/output-audio + av_sync_drift checks (W6)

Branch/Worktree: `codex/s11/t03e-0903w6` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03e-0903w6`
WAVE_BASE: `b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9` → RESUME canonical `c1a6777864c1169435d7b7f263ce5fa7a0014c78` (fast-forward sau correction cascade T02A enum 10-code; HEAD bất biến suốt session — commit local cuối).
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` (binding block W6 T03E — Decision D freeze C2-F2).

Mọi lệnh pytest chạy với isolation: `env -u MOTIONFORGE_DATABASE_URL python -m pytest -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/<short-tag>` (Windows-native ngắn, unique mỗi run).

| Thời điểm | Hành động | Kết quả thật |
|---|---|---|
| RESUME | Verify worktree: `git status --porcelain` chỉ có draft `?? tests/test_s11_t03e_audio_sync_checks.py`; HEAD = `c1a6777 docs(s11): T02B-C1 record correction commit SHA in LOG/REPORT`; branch đúng | Evidence: baseline trong REPORT §3 |
| Enum scan | `QC_REASON_CODES`/`QC_ITEM_CATEGORIES` = binding 10 codes (gồm `audio_missing`, `av_sync_drift`); T02B repo API không đổi; thresholds policy v1 còn nguyên (`av_sync_drift` warn=0.1/block=0.5, sanity [0,0.5]) — verify bằng `classify()` thật | classify 0.05→pass, 0.1→warning, 0.25→warning, 0.5→blocker, 2000→invalid |
| Draft sửa | Rewrite test file: import top-level (`from s11_qc_media_builders import ...` — tests/ không có `__init__.py`, conftest chèn project root); reason_code = binding code mới; thêm assert category/detector/reason cho cả 2 detector | RED chạy: `ImportError: cannot import name 'audio_missing'` — đúng lỗi RED (module chưa tồn tại) |
| Implement | `app/services/qc_checks/audio_missing.py` (mới): NO_AUDIO_PRESENT → not_applicable + zero QCItem + không fabricate + không block; source-có-audio + attach fail/expected output thiếu/validated output mất audio → QCItem blocker/open reason_code=`audio_missing`; evidence content-derived (source_audio_present, output_audio_duration, audio_time_base...) | py_compile OK |
| Implement | `app/services/qc_checks/av_sync_drift.py` (mới): quy đổi MỘT CHIỀU qua CanonicalTimebase exact Fraction (scene: duration_seconds hoặc fps_num/fps_den/nb_frames → duration_for_frames); drift = |remux − scene| Fraction; classify qua frozen policy; unit-mismatch (ms/frame đọc nhầm giây) → fail-closed blocker `unit_mismatch_caught=True`; NO_AUDIO → not_applicable | py_compile OK |
| GREEN ×3 | `pytest tests/test_s11_t03e_audio_sync_checks.py` (basetemp s11t03e-g1/g2/fin1/fin2) | 17 passed ×4 (2.54s / 2.50s / 2.56s / 2.50s, EXIT 0) — evidence/final_green_v1.txt, final_green_v2.txt |
| Static gates | `ruff check --select F` 3 file; `py_compile` 3 file; fix F401 (3 unused imports trong av_sync_drift) | `All checks passed!` RUFF_EXIT=0; PY_COMPILE_OK (evidence/static_gates.txt) |
| Regression | `pytest tests/test_s11_t03a_thresholds_policy.py tests/test_s11_t03a_runner_registry.py tests/test_s11_t06a2_calibration_inputs.py tests/test_s11_t06a1_fixture_harness.py` (read-only consume) | 43 passed, 6 warnings (16.47s) — evidence/regression.txt |
| Idempotency | Script độc lập chạy detect ×2 mỗi detector trên args giống hệt, so sha256 JSON | audio_missing hash TRÙNG nhau (307d8a16…); av_sync_drift hash TRÙNG nhau (a1adb27c…) — evidence/idempotency_hash.txt |
| Old-token scan | `grep -rn "audio_timecode"` 3 file allowlist | ZERO matches (grep exit 1) |
| Final scope | `git status --porcelain` | Chỉ untracked allowlist (2 module + 1 test + docs/pm/sessions/S11-T03E/); KHÔNG file modified; HEAD bất biến |
| Commit | Stage CHỈ allowlist + `docs/pm/sessions/S11-T03E/**`; commit local | SHA ghi trong REPORT.md / terminal |

Không push/merge/rebase/reset/clean/stash/force. KHÔNG đụng s11-integration, MAIN, T02B repo (chỉ import read-only), thresholds/runner/registry (read-only), original_audio_remux/handler (chỉ consume envelope), timebase.py (chỉ consume), migrations/**, frontend/**, s08_golden/**, test fixtures T02B/T06A1 (chỉ đọc).
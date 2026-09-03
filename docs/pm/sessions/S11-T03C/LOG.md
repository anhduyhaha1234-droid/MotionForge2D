# S11-T03C LOG — contact_break + z_order_error + silhouette_clipping detectors (W6)

Branch/Worktree: `codex/s11/t03c-0903w6` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03c-0903w6`
WAVE_BASE: `b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9` → fast-forward canonical sau correction cascade: `c1a6777864c1169435d7b7f263ce5fa7a0014c78` (HEAD bất biến suốt session; commit local cuối, không push/merge/rebase/reset/clean/stash/force).
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` — binding block W6 · T03C (Outcome/Write-set/Forbidden/Tests/Session rule/Acceptance/Trace).
Resume: 2026-09-03 (sau correction cascade T02B-C1/T06A1-C1 — QC_REASON_CODES/QC_ITEM_CATEGORIES = binding 10 codes).

Mọi lệnh chạy từ worktree task với isolation: `env -u MOTIONFORGE_DATABASE_URL python -m pytest -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/<short-tag>` (Windows-native, ngắn).

| Thời điểm | Hành động | Kết quả thật |
|---|---|---|
| Session start | Baseline: porcelain=0, HEAD=`b34d801` (WAVE_BASE), qc_checks có `{__init__,registry,runner,thresholds}.py` (T03A), calibration `contact_zorder_clipping.json` có 3 metrics (contact_break px / z_order_error count / silhouette_clipping ratio, L2/L4 raw) | evidence/baseline_scope.txt |
| Resume check | HEAD=canonical `c1a6777` (fast-forward qua T02B-C1/T06A1-C1); `QC_REASON_CODES` = 10 codes binding; draft test còn trong worktree (untracked) | grep models.py L3041-3052 |
| RED | Viết `tests/test_s11_t03c_contact_zorder_clipping_detectors.py` (29 tests) TRƯỚC implementation | `ModuleNotFoundError: No module named 'app.services.qc_checks.contact_break'` (1 error collection, 0.52s) |
| Implement | 3 detector modules MỚI: `app/services/qc_checks/{contact_break,z_order_error,silhouette_clipping}.py` — detect(args)->list[dict] JSON-serializable, threshold READ-ONLY qua `thresholds.get_threshold`/`classify`, registry qua `register_detector`, z_order_error đọc lock manifest qua public S09 `structural_lock.validate_manifest`, evidence schema_version=1 + `evidence_window_key`=sha256(canonical content) | py_compile OK; ruff `All checks passed!` |
| GREEN fix 1 | Boundary bug: gap 24px > sanity max (blocker boundary 16px) → `THRESHOLD_INVALID` fail-closed, 0 items. Sửa test: blocker case nằm ĐÚNG boundary (gap == blocker boundary, đọc từ policy) | blocker test pass |
| GREEN fix 2 | Bbox math trong tests: `[10, 30+gap, ...]` cho gap = 10+gap (sai); đổi `[10, 20+gap, 40, 40+gap]` → gap chính xác | warning/within tests pass |
| GREEN fix 3 | `_chain_edges(8)` = 7 edges (count-1) — cần `_chain_edges(9)` cho 8 edges; `test_evidence_window_key_is_content_derived` đổi args2 sang khác metric value thay vì khác contact end (end không nằm trong key core) | tests pass |
| GREEN lần 1 | `pytest tests/test_s11_t03c_contact_zorder_clipping_detectors.py` | `29 passed in 3.23s` (evidence run1/run2) |
| GREEN ×2 | Rerun fresh basetemp ×2 | `29 passed in 3.17s` / `29 passed in 3.15s` (evidence/run1.txt, run2.txt) |
| Regression | T03A + T06A2 consume regression (read-only) | `64 passed in 8.74s` (evidence/regression_t03a_t06a2.txt) |
| Regression T02B | T02B repos (Depends-on) — không đụng file, chỉ regression | `40 passed, 23 warnings in 49.30s` (evidence/regression_t02b.txt) |
| Static gates | `ruff check --select F` (4 allowlist files); `py_compile`; `git diff --check` | `All checks passed!` RUFF_EXIT=0; PY_COMPILE_OK; DIFF_CHECK_OK (evidence/static_gates.txt) |
| Audit script | `gen_audit.py`: 3 reason codes ∈ binding enum; severity mapping vs policy; evidence idempotent ×2 byte-identical (in-process + runner child ×2); hard-code scan boundary literals = NONE | `AUDIT_WRITTEN` (evidence/audit.txt) |
| Final scope | `git status --porcelain` | Đúng allowlist: 3 detector files + 1 test file + `docs/pm/sessions/S11-T03C/`; KHÔNG file modified; HEAD bất biến `c1a6777` |
| Commit | Stage CHỈ allowlist + `docs/pm/sessions/S11-T03C/**`; commit local | SHA ghi REPORT.md / terminal |

Không push/merge/rebase/reset/clean/stash/force. KHÔNG đụng s11-integration, MAIN, runner/registry/thresholds (read-only), orchestrator (T03F), models.py, migrations/**, frontend/**, structural_evidence.py/structural_lock.py/compositing.py (chỉ consume public contract), T02B/T06A1/T06A2 files.
# S11-T03A LOG — Threshold policy v1 + bounded runner + registry contract (W5)

Branch/Worktree: `codex/s11/t03a-0903w5` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03a-0903w5`
WAVE_BASE: `8f27c6b17efce1e8b20c3685ec4ad42be33a90d4` (HEAD bất biến suốt session — commit local cuối).
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` (binding block W5 trích trong prompt; trace: roadmap MAIN L229, overlay §S11 L370–371, lane-A GAP_RISKS GAP-4/R2/R6, lane-B CHECK_CAPABILITY_MATRIX §6 hàng "Harness drain/deadline mở rộng").

Mọi lệnh chạy từ worktree task với isolation: `env -u MOTIONFORGE_DATABASE_URL python -m pytest -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/<short-tag>` (Windows-native, ngắn).

| Thời điểm | Hành động | Kết quả thật |
|---|---|---|
| 2026-09-03 T03A start | Baseline: `git status --porcelain` = 0; `git log --oneline -1` = `8f27c6b S11-T06A2 (W4)`; `test -d app/services/qc_checks` → ABSENT; `tests/fixtures/s11_golden/` ABSENT; psutil 7.2.2 | evidence/baseline.txt |
| RED | Viết 2 test files (policy + runner/registry) trước implementation | `ModuleNotFoundError: No module named 'app.services.qc_checks'` — 2 errors collection, 0.20s (evidence/red.txt) |
| T06A2 consume | Đọc `tests/s11_qc_calibration_builders.py` (624 dòng) + 4 calibration JSONs → 10 metric records (unit/seed/src/res/rev/levels/raw) | policy design: warning=L2 raw, blocker=L4 raw (increasing) / constant (fact) |
| Implement | 4 file MỚI: `app/services/qc_checks/{__init__,thresholds,runner,registry}.py` + golden fixture `tests/fixtures/s11_golden/qc_thresholds.json`; toàn bộ là file mới (verify trước khi tạo) | py_compile OK; policy build: policy_id `s11-qc-thresholds-v1`, content_hash `de215c6243e1c6bf300e2bfa1c8024fbda6d0358ecf3cad1730781e37419ea24`, 10 thresholds (evidence/policy_summary.txt) |
| GREEN lần 1 | `pytest tests/test_s11_t03a_thresholds_policy.py` | `12 passed in 4.01s` |
| GREEN runner fix 1 | Bug: `deadline` truyền như countdown (20.0) trong khi `remaining_budget = deadline - time.monotonic()` cần absolute monotonic timestamp (uptime lớn → budget âm → deadline sai ngay). Fix: `deadline=time.monotonic() + deadline_sec` (T01D contract) | 5/15 child tests chuyển từ deadline-spurious sang chạy thật |
| GREEN runner fix 2 | Bug: `child_env` (PYTHONPATH chứa project root + tests dir) được build nhưng KHÔNG truyền vào `subprocess.Popen` → child `ModuleNotFoundError: test_s11_t03a_runner_registry`. Fix: `_run_bounded(..., env=...)` | runner tests `15 passed in 4.82s` |
| GREEN full ×2 | `pytest` 27 tests, basetemp s11t03a-g1/g2 | `27 passed in 4.86s` / `27 passed in 4.85s` (evidence/run1.txt, run2.txt) |
| Static gates | `ruff check --select F` 6 files; `py_compile` 6 files; golden sha256 | `All checks passed!` (RUFF_EXIT=0); PY_COMPILE_OK; `54e5e7eb2b95f2e43c0437fd48916769a4df05d89bbc5972a2cfc07d9af5c400` (evidence/static_gates.txt) |
| Provenance audit | Script độc lập đối chiếu từng boundary với raw value level tương ứng trong fixture JSON thật + revision/seed/refs | `AUDIT_ALL_OK` — 10/10 metrics (evidence/provenance_audit.txt) |
| Regression T06A2 | `pytest tests/test_s11_t06a2_calibration_inputs.py` (read-only consume) | `8 passed in 3.89s`, EXIT=0 (evidence/t06a2_regression.txt) |
| Runner evidence | `pytest ... --basetemp=s11t03a-ev4 -v` | 15/15 PASSED — gồm deadline kill + capture-cap fail-closed + cancel + leak scan (evidence/runner_tests.txt) |
| Final scope | `git status --porcelain` | Chỉ untracked allowlist (4 new files + 2 dirs) + docs/pm/sessions/S11-T03A/; KHÔNG file modified; HEAD bất biến (evidence/baseline.txt bottom) |
| Commit | Stage CHỈ allowlist + `docs/pm/sessions/S11-T03A/**`; commit local | SHA ghi trong REPORT.md / terminal |

**CORRECTION C2 (2026-09-03, exit-gate mypy — resume session T03A):**
| Thời điểm | Hành động | Kết quả thật |
|---|---|---|
| RED | `python -m mypy app/services/qc_checks/{thresholds,runner,registry}.py` trên canonical-FF HEAD `15f4349` (porcelain=0) | `thresholds.py:280 no-any-return` + `runner.py:160 unused-ignore` — đúng 2 findings |
| Fix 1 | `thresholds.py get_threshold`: `return cast(dict[str, Any], entry)` + `from typing import Any, cast` (lru_cache wrapper → Any; cast đúng, không nới ignore, không đổi hành vi) | — |
| Fix 2 | `runner.py _kill_tree`: xóa `# type: ignore[import-not-found]` dư (mypy thấy psutil; giữ try/except ImportError fallback runtime) | — |
| GREEN | mypy 3 files → `Success: no issues found in 3 source files`; pytest 2 files `27 passed in 4.92s` + `27 passed in 4.91s` (basetemp s11t03a-c2-1/2, env strip); ruff F `All checks passed!`; py_compile OK; `git diff --check` sạch | — |
| Scope | `git status --porcelain` = chỉ `M app/services/qc_checks/{runner,thresholds}.py` + docs C2 append; KHÔNG đụng file khác; KHÔNG push/merge/rebase | — |
| Commit C2 | 1 commit local | SHA ghi REPORT.md / terminal |

Không push/merge/rebase/reset/clean/stash/force. KHÔNG đụng s11-integration, MAIN, T02B repo, T06A1 media manifests, calibration fixtures (T06A2 — read-only), frontend/**, migrations/**, s08_golden/**.
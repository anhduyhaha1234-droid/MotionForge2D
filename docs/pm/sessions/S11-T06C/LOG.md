# S11-T06C — One-command measured acceptance suite/report/leak gate (W14)

**Task ID:** S11-T06C
**State:** TASK_SUBMITTED
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s11-t06c-0903w14
**Branch:** codex/s11/t06c-0903w14 — commit LOCAL, no push/merge
**WAVE_BASE:** fce13a06b4b51b736d13434e812700094a8adaca (canonical HEAD sau T05B, porcelain=0 tại start)
**Model:** ocg/deepseek-v4-flash @ custom (9Router), reasoning max, fallback disabled
**Date:** 2026-09-03 (UTC run-id 20260903-155419)

## Trình tự thực hiện

1. Baseline: `git status --porcelain` = 0 (rỗng); HEAD = WAVE_BASE.
2. Đọc pattern: `tests/test_s11_original_audio_acceptance.py::_run_suite_tracked`
   (T01D — reader-thread drain, deadline RC124, ownership-scoped leak scan, máy-wide
   mutex via msvcrt file-lock, child basetemp ngắn dưới Windows temp root).
   Golden manifests T06B: `tests/s11_qc_golden.py` (GOLDEN_MANIFESTS 5 file,
   policy_ref_matches, validate_all), policy hash frozen
   `de215c6243e1c6bf300e2bfa1c8024fbda6d0358ecf3cad1730781e37419ea24`
   (s11-qc-thresholds-v1) — S11-SPRINT_CONTRACT §Global-gate mutex: kiểm tra
   không writer khác active (scan python/pytest processes = rỗng) TRƯỚC outer run.
3. RED → implement: `tests/test_s11_t02_t06_acceptance.py` (file MỚI, duy nhất
   trong write-set test). Frozen runner pattern T01D có attribution — KHÔNG sửa
   file gốc. `S11_QC_SUITE_FILES` = 20 file T02..T05 (314 tests).
4. Gate run #1 (run-id `20260903-154936-6064`): 9/10 pass — 1 FAIL
   `S11-T06C-22-audio-sync-slice-present` do filter `"/t03e" in f` sai (segment
   là `_t03e`, không có slash trước) → slice rỗng; test_t08 pass vacuous (loop
   rỗng). FIX: filter `"t03e"`/`"t04b"` (bare) + presence-check explicit trong
   cả hai test (chống vacuous pass).
5. Gate run #2 (run-id `20260903-155419-31900`): **10 passed, exit 0** — GREEN.
   Inner suite: 314 passed, 0 failed, 0 errors trong 242.719s (ref T01D 166.7s
   inner cho 52 tests — reference, không gate cứng).
6. Static gates: `python -m py_compile` OK; `ruff check --select F` clean
   (ruff 0.16.0 — CLI mới yêu cầu `ruff check`); 10 tests collect OK.
7. Self-review diff scope: chỉ 1 file test mới + session docs.
8. Evidence: `output/s11-t06-e2e/20260903-155419-31900/` (report.json,
   assertions.json, suite_stdout.txt 37.5KB, suite_stderr.txt 0B) — run-id MỚI,
   KHÔNG overwrite run cũ; bản copy vào `docs/pm/sessions/S11-T06C/evidence/`.
9. Commit local theo allowlist (ghi SHA bên dưới).

## Binary acceptance criteria — kết quả

| AC | Yêu cầu | Kết quả |
|---|---|---|
| 1 | Một lệnh: --ignore tests/test_integration.py, -p no:cacheprovider, basetemp riêng, env strip → exit 0; log actual counts khớp golden manifests (assert động theo policy hash) | GREEN: outer exit 0 (10 passed); inner 314 passed exit 0; 5/5 manifest policy hash == frozen hash (policy_ref_matches), counts động từ manifest JSON + policy, không hard-code |
| 2 | Báo cáo measured: per-file pass/fail counts, thời lượng phase (ref T01D ~166s inner — không gate cứng), ffmpeg/ffprobe survivors = 0 | report.json: per-file 20/20 (tổng 314/0/0), inner 242.719s / leak window 0.0s / total 242.719s, survivors [] (8 pids ownership-scoped, window 15s) |
| 3 | Epic exit L235: source voice/BGM/SFX unchanged in sync; Scenario D đạt không review full timeline | test_s11_t03e_audio_sync_checks.py green (17 pass) + scenario_d manifest rerun_target=affected_segment_only, ready scenes unchanged, after_rerun=ready |
| 4 | Evidence run-id MỚI dưới output/s11-t06-e2e/ — không overwrite | 20260903-155419-31900 (mới; run #1 20260903-154936-6064 giữ nguyên) |

Assertion ledger: 74/74 OK (assertions.json all_ok=true).

## Process deviation

Không có. Không git reset/clean/stash/restore/checkout/push/merge/force;
MAIN + s08 archive + s11-integration canonical NOT touched; production code
0 diff; fixtures/builders/manifests 0 diff (chỉ consume); tests gốc T01D 0
diff; các file S11-T02..T05 0 diff.

## File thay đổi (allowlist)

- `tests/test_s11_t02_t06_acceptance.py` — MỚI (frozen suite runner 20 file).
- `docs/pm/sessions/S11-T06C/` — LOG.md, REPORT.md, evidence/ (copy run-id).
- `output/s11-t06-e2e/20260903-155419-31900/` — runtime artifacts (gitignored
  output/ namespace, AC4).

## Commit

- SHA: `c3cc46e` (feat: test + REPORT + evidence) + `e795f1c`
- Parent: fce13a06b4b51b736d13434e812700094a8adaca (WAVE_BASE)

**Status: TASK_SUBMITTED** — chờ Manager verify. KHÔNG tự ghi APPROVED.
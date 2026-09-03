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

---

## S11-C1 lane C1-B — executable restart/resume epic-exit proof (resume exact owner)

**Finding (Codex P1, review 2026-09-04):** `tests/test_s11_t02_t06_acceptance.py:853-895`
Scenario D chỉ đọc golden manifest và assert chuỗi; `test_t08` chỉ verify các
file T04B đã từng báo pass — không enqueue recompute, không dừng/recreate
service/worker trên cùng durable DB, không resume persisted job. Evidence defect
trừ khi executable scenario phát hiện product defect.

**Fix (bounded patch, chỉ file allowlist):** thêm `test_t11_executable_restart_resume_epic_exit`
vào cùng file test — scenario THỰC THI qua stack thật (correction/recompute path
đã có, KHÔNG mock durable authority):

1. Fresh temp DB (Alembic head) + temp managed root mới, `env -u
   MOTIONFORGE_DATABASE_URL`, `-p no:cacheprovider`, basetemp Windows-native
   ngắn unique (`s11c1b_*`).
2. Seed project/video/QC blocker hợp lệ (envelope STREAM_COPY: source HAS audio
   nhưng output publish missing → audio_missing blocker + av_sync_drift blocker)
   và submit RUN_QC_CHECKS recompute qua stack thật (`submit_run_qc_checks`).
3. Dừng/recreate JobService (teardown svc1 + build svc2 cùng durable DB +
   cùng managed root) — process-boundary tương đương.
4. Resume persisted job, bounded poll (deadline 60s + interval 0.5s) tới terminal.
5. Chứng minh: đúng một successor/effect (1 completion, run_id deterministic
   64-hex duy nhất); không duplicate correction resolution / enqueue (completed
   duplicate reuses SAME job, QCItem count không đổi); readiness `blocked` trung
   thực sau fix-chưa-resolve + ổn định qua fresh repository re-query.
6. Lane evidence external: `C:\Users\Admin\MotionForge2D-evidence\s11-c1\lanes\c1b-t06c\c1b_restart_proof_<run_tag>.json`
   (job_id, terminal snapshot, 10 assertions S11-C1B-01..10, all_ok).

**Kết quả:** KHÔNG phát hiện product bug → KHÔNG cần T04B. Executable test XANH
với production hiện tại (1 passed standalone 2.96s; 11/11 toàn file 249.24s
exit 0). Full lane log: `/c/Users/Admin/AppData/Local/Temp/s11c1b_full.log`.

**Status: TASK_SUBMITTED** — lane C1-B, chờ Manager verify. KHÔNG tự ghi APPROVED.
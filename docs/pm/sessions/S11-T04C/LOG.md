# S11-T04C — Original-audio attach action API + A/V recheck trigger (W11) — LOG

Branch: `codex/s11/t04c-0903w11` (local only) | WAVE_BASE: `9bb920811b6aa7aeba09d7d1d65b13ef308004e7`
Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s11-t04c-0903w11`
Model route: provider `custom` / `ocg/deepseek-v4-flash` / reasoning max / fallback OFF / TTFB 900.

## 1. Baseline (porcelain = 0, HEAD = WAVE_BASE)

```
$ git status --porcelain            → (empty)
$ git rev-parse HEAD                → 9bb920811b6aa7aeba09d7d1d65b13ef308004e7
$ git hash-object app/workflow/original_audio_handler.py → c099063cbba026d4689697e3c6671fc1bd3fac27 (1284 dòng)
$ git hash-object app/api/app.py                            → de6f9ffa1c09c3c5b9c0fca3cf788d05be916b26 (211 dòng)
$ git hash-object app/workflow/durable_worker.py            → c4fbb56e7a664d5f756596217acf55e0fd21957f (1413 dòng)
$ git hash-object app/services/original_audio_remux.py      → 9065dbf2ca0801898438ed609ba283489a5a1672 (1314 dòng)
```

## 2. RED (trước implementation)

```
$ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t04c_attach_action_api.py \
    -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t04c_red -q
E   ModuleNotFoundError: No module named 'app.api.routes.original_audio_action'
ERROR tests/test_s11_t04c_attach_action_api.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.63s
```

## 3. Implementation (write-set FREEZE C4-F3 — exact 5)

| File | Change | Diff |
|---|---|---|
| `app/api/routes/original_audio_action.py` | NEW — server-owned POST `/api/v2/projects/{project_id}/original-audio-attach`; payload `{video_item_id}` extra=forbid; 202/409/404/422 fail-closed; reused → backfill `ensure_av_recheck` | whole-file mới |
| `app/services/qc_av_recheck.py` | NEW — `ensure_av_recheck` (submit authority T03G, scope `audio`, idempotent: completed→reused / active→covered / terminal-failed→RECHECK_TERMINAL_BLOCKED fail-closed; recheck job được lên lịch priority 40 < 50 = background audit) + `attach_recheck_evidence` (JobAttempt lifecycle read) | whole-file mới |
| `app/workflow/original_audio_handler.py` | EXTEND — `_trigger_av_recheck_after_validation` hook gọi `ensure_av_recheck` tại 2 điểm return của `_attach_output_validator` (published bytes OK + NO_AUDIO_PRESENT terminal); enqueue lỗi → validator raise → job KHÔNG complete; ctx không có session_factory (pure disk-validation seam) → skip | +38 dòng additive |
| `app/api/app.py` | EXTEND — 1 import + 1 include_router (kèm comment) | +6 dòng |
| `tests/test_s11_t04c_attach_action_api.py` | NEW — 12 tests phủ C4-F3 #1..#7 + Acceptance 1–5 | whole-file mới |

`durable_worker.py` + `original_audio_remux.py`: không chạm (verify bên dưới).

## 4. GREEN — focused (từng lần trên root tươi, `-p no:cacheprovider`, env strip MOTIONFORGE_DATABASE_URL)

| Run | Root | Kết quả | Thời gian |
|---|---|---|---|
| run1 | `%TEMP%/s11t04c_green3` | 12 passed (sau lần sửa đầu) | 17.35s |
| run2 | `%TEMP%/s11t04c_run2` | 12 passed | 17.64s |
| run3 | `%TEMP%/s11t04c_run3` | 12 passed | 20.02s |
| run4 | `%TEMP%/s11t04c_green4` | 12 passed (sau priority demote) | 17.64s |
| run5 | `%TEMP%/s11t04c_finalA` | 12 passed (sau getattr guard) | 17.49s |
| run6 | `%TEMP%/s11t04c_finalB` | 12 passed | 17.45s |

Test map (S11-T04C):
```
1  test_01_no_recheck_before_completion_recheck_after_verified_completion   — C4-F3 #2/#1 + scope/envelope + background priority
2  test_02_terminal_no_audio_present_triggers_recheck                       — C4-F3 #1 terminal nhánh
3  test_03_retry_validator_no_duplicate_run_and_active_conflict_covered     — C4-F3 #3/#5 + RECHECK_TERMINAL_BLOCKED
4  test_04_enqueue_failure_fail_closed_attach_not_completed                 — C4-F3 #3 fail-closed (VALIDATION_FAILED)
5  test_05_attach_failure_no_recheck                                        — C4-F3 #6 (source mất lúc run)
6  test_06_no_direct_qcitem_resolution_and_durable_worker_untouched         — C4-F3 #7 + Acceptance 5
7  test_07_payload_with_path_handler_provider_rejected_422                  — Decision H / Acceptance 1
8  test_08_route_fresh_submit_then_completion_triggers_recheck              — route E2E + reused + source authority
9  test_09_active_conflict_fail_closed_409_and_no_early_recheck             — C4-F3 #4/#5 (409, không enqueue sớm)
10 test_10_reused_completed_backfills_missing_recheck                       — C4-F3 #4 / Acceptance 4 (backfill run thiếu)
11 test_11_workspace_mismatch_fail_closed                                   — workspace mismatch fail-closed
12 test_12_router_shape_server_owned_and_include_once                       — Shape: 1 POST, 0 mutator, app.py 1 include
```

## 5. GREEN — regression 5 file S11-T01 (read-only, cùng lệnh regression)

| Run | Root | Kết quả | Ghi chú |
|---|---|---|---|
| reg1 | `%TEMP%/s11t04c_regression` | 58 passed / 6 failed | lỗi chọn-job: recheck leftover priority=50 preempt import kế tiếp + fake-ctx validator |
| reg2 | `%TEMP%/s11t04c_regression2` | 61 passed / 3 failed | sau priority demote 40: s07/06/12 xanh; còn a01/a02/test_08 |
| reg3 | `%TEMP%/s11t04c_regression3` | **64 passed / 0 failed** (271.77s) | sau getattr guard — GATE XANH |

Sửa gốc rễ (không đụng file regression):
- Recheck job được tạo qua T03G submit authority rồi demote priority 40 (background audit) — `run_once` claim priority-desc ⇒ import/attach (50) luôn được claim trước; regression giữ nguyên `run_once()==1` per submitted job.
- `_trigger_av_recheck_after_validation` dùng `getattr(ctx, "session_factory", None)` — ctx không có factory (pure disk-validation seam trong test_08 T01) được skip; worker thật luôn bind factory nên fail-closed enqueue vẫn giữ.

## 6. Static gates (cuối cùng)

```
$ python -m ruff check --select F <5 files>   → All checks passed!
$ python -m py_compile <5 files>              → OK (kèm import-smoke: app.api.app / qc_av_recheck OK)
$ grep -rn "QCItem\|qc_items" qc_av_recheck.py original_audio_action.py → rc=1 (không có)
$ git diff --exit-code -- app/workflow/durable_worker.py app/services/original_audio_remux.py → 0 (FORBIDDEN_ZERO)
```

## 7. Ví dụ raw output

```
[attach completion qua default JobService worker]
motionforge.durable_worker: step run_qc_checks attempt 1 failed: ... (chỉ khi band chưa register — tác vụ nền, không ảnh hưởng)
12 passed, 21 warnings in 17.64s   (focused, root tươi)
```

## 8. Commit

```
$ git add app/api/routes/original_audio_action.py app/services/qc_av_recheck.py \
          app/workflow/original_audio_handler.py app/api/app.py \
          tests/test_s11_t04c_attach_action_api.py docs/pm/sessions/S11-T04C/
$ git commit -m "feat(s11-t04c): original-audio attach action API + A/V recheck trigger (W11)"
SHA: 241e5393bf5fdfb6cad8aeb71a8b32c195057c74 (production+test+docs)
docs SHA bổ sung: (commit docs ghi SHA)
```
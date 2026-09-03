# S11-T04C — Original-audio attach action API + A/V recheck trigger (W11) — REPORT

Task ID: **S11-T04C** (W11, serial sau W10) | Branch: `codex/s11/t04c-0903w11` (local)
WAVE_BASE: `9bb920811b6aa7aeba09d7d1d65b13ef308004e7` | Trạng thái: **TASK_SUBMITTED**

---

## Tóm tắt

Server-owned attach action API (Decision H) + A/V recheck trigger chỉ sau
completion thật của attach output-validation, fail-closed toàn tuyến:

- `POST /api/v2/projects/{project_id}/original-audio-attach` — payload chỉ
  `{video_item_id}` (extra=forbid ⇒ path/handler/provider bị 422); server
  resolve source từ `VideoItem.source_artifact_id` authority qua
  `submit_attach_original_audio` hiện có; managed root từ JobService config
  (không nhận path từ client).
- Worker-side verified-completion hook trong `_attach_output_validator`
  (original_audio_handler.py): sau khi xác minh published bytes OK **hoặc**
  terminal NO_AUDIO_PRESENT → gọi `ensure_av_recheck`; enqueue lỗi → validator
  raise → attach job **KHÔNG** đạt completed (fail-closed).
- `ensure_av_recheck` (qc_av_recheck.py) dùng **submit authority T03G**
  (`submit_run_qc_checks`, scope `audio`): completed duplicate → reused;
  active duplicate → covered (không duplicate); terminal FAILED/CANCELLED
  duplicate → `RECHECK_TERMINAL_BLOCKED` fail-closed; job được lên lịch
  background priority 40 (không preempt user jobs priority 50).
- Route nhận completed/reused attach job cũ → `attach_recheck_evidence` +
  `ensure_av_recheck` **backfill run thiếu** (idempotent).
- Zero code path resolve trực tiếp QCItem; `durable_worker.py` +
  `original_audio_remux.py` không chạm (diff = 0).

## Acceptance criteria (binary)

| # | Tiêu chí | Bằng chứng |
|---|---|---|
| 1 | Route server-owned đúng Decision H; client payload KHÔNG chứa path/handler/provider | `test_07` (422 cho path/source_path/handler/provider/source_artifact_id) + `test_12` (schema chỉ `video_item_id`, extra=forbid) + grep source |
| 2 | Idempotency + conflict khớp AttachSubmitResult/IdempotencyKeyInUse — test cả 2 nhánh | `test_08` (reused=True, same job_id sau completion), `test_09` (409 IdempotencyKeyInUse khi active), `test_10` (resubmit ổn định) |
| 3 | Recheck chỉ enqueue sau verified completion (bytes OK hoặc NO_AUDIO_PRESENT) qua ensure_av_recheck; enqueue trước completion = test fail; enqueue lỗi ⇒ attach KHÔNG complete | `test_01` (0 recheck trước completion → 1 sau), `test_02` (NO_AUDIO_PRESENT → 1), `test_04` (enqueue raise → job failed `VALIDATION_FAILED`, 0 recheck) |
| 4 | Completed/reused attach cũ → backfill run thiếu; retry validator không duplicate (key fingerprint+policy hash) | `test_10` (xóa queued recheck → route backfill 1 run mới; resubmit giữ nguyên), `test_03` (active→covered, completed→reused, replay validator count=1) |
| 5 | Zero code path resolve trực tiếp QCItem; durable_worker.py untouched | `test_06` (source grep QCItem/qc_items = 0, `git diff --exit-code` worker+remux = 0) + grep rc=1 |
| 6 | Gate: focused mới xanh + 5 file S11-T01 regression read-only pass | 12 passed x4 root tươi; regression **64 passed** (0 failed) — xem bên dưới |

## Evidence — focused test (12 tests, root tươi, `-p no:cacheprovider`, `env -u MOTIONFORGE_DATABASE_URL`, basetemp Windows-native ngắn)

```
12 passed, 21 warnings in 17.35s   (run1, %TEMP%/s11t04c_green3)
12 passed, 21 warnings in 17.64s   (run2, %TEMP%/s11t04c_run2)
12 passed, 21 warnings in 20.02s   (run3, %TEMP%/s11t04c_run3)
12 passed, 21 warnings in 17.64s   (run4, %TEMP%/s11t04c_green4 — sau priority demote)
12 passed, 21 warnings in 17.49s   (run5, %TEMP%/s11t04c_finalA — sau getattr guard)
12 passed, 21 warnings in 17.45s   (run6, %TEMP%/s11t04c_finalB)
```

## Evidence — regression 5 file S11-T01 (read-only, không sửa file nào)

```
tests/test_s11_original_audio_remux.py
tests/test_s11_original_audio_integration.py
tests/test_s11_original_audio_contract.py
tests/test_s11_original_audio_acceptance.py
tests/test_s11_attach_original_audio_job.py

final: 64 passed, 78 warnings in 271.77s (0:04:31)   (%TEMP%/s11t04c_regression3)
```

Chuỗi sửa trong quá trình gate (root-cause, không đụng file regression):
1. Recheck job tạo qua T03G authority rồi **demote priority 40** (background
   audit; `run_once` claim priority-desc ⇒ import/attach priority 50 luôn được
   claim trước) — hết 3 failure do leftover preempt (`s07`, `06`, `12`).
2. Hook dùng `getattr(ctx, "session_factory", None)`: ctx thiếu factory =
   pure disk-validation seam (T01 `test_08` gọi validator trực tiếp với fake
   ctx) → skip; worker thật luôn bind factory → fail-closed enqueue giữ nguyên.

## Evidence — static gates

```
$ python -m ruff check --select F <5 files>   → All checks passed!        (RUFF_F_CLEAN)
$ python -m py_compile <5 files>              → OK                        (PYCOMPILE_OK)
$ python -c "import app.api.app; import app.services.qc_av_recheck; ..." → IMPORTS_OK (không cycle)
$ git diff --exit-code -- app/workflow/durable_worker.py app/services/original_audio_remux.py → 0
$ grep -rn "QCItem\|qc_items" app/services/qc_av_recheck.py app/api/routes/original_audio_action.py → rc=1
$ git status --porcelain: M app/api/app.py, M app/workflow/original_audio_handler.py,
  ?? app/api/routes/original_audio_action.py, ?? app/services/qc_av_recheck.py, ?? tests/test_s11_t04c_attach_action_api.py
```

## Diff scope (self-review)

- `original_audio_handler.py`: **+38 dòng additive** — 2 dòng gọi hook tại 2
  điểm return của `_attach_output_validator` + helper `_trigger_av_recheck_after_validation`.
- `app.py`: +6 dòng — 1 import + 1 include_router (+ comment).
- 3 file mới: router action (1 POST, 0 PUT/PATCH/DELETE), qc_av_recheck
  (ensure + evidence, không import QCItem/qc_items), test file 12 tests.
- Không đụng: durable_worker.py, original_audio_remux.py, qc_checks_handler.py,
  qc_items repo/router, models.py, migrations, frontend, corrections, MAIN.

## Trace references

- Roadmap MAIN L230; lane-C API_UI_GAP_MATRIX G9 + §3 rủi ro 3 (fail-closed
  ownership); REVIEW_QUEUE_CONTRACT §3.2 A/V sync; lane-B FAILURE_ROUTING §3
  (SOURCE_OWNER_MISMATCH v.v.).

## Files

```
NEW  app/api/routes/original_audio_action.py
NEW  app/services/qc_av_recheck.py
EXT  app/workflow/original_audio_handler.py   (+38 additive, completion path)
EXT  app/api/app.py                            (+6: import + 1 include_router)
NEW  tests/test_s11_t04c_attach_action_api.py  (12 tests)
NEW  docs/pm/sessions/S11-T04C/LOG.md
NEW  docs/pm/sessions/S11-T04C/REPORT.md
```

Commit local: `241e5393bf5fdfb6cad8aeb71a8b32c195057c74` (production + test + docs; KHÔNG push/merge/rebase).
Docs SHA bổ sung: (docs commit ghi SHA).
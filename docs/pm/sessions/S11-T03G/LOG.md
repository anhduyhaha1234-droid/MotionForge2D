# S11-T03G — Session LOG (W8)

- Task: Durable QC check-run job, server-owned action và read authority
- Branch: `codex/s11/t03g-0903w8` (local commits only — no push/merge/rebase)
- WAVE_BASE: `f6942593304742501ba88f671160b83addbb980b` (canonical HEAD sau T03F verify+merge; porcelain 0 at start)
- Model route: provider `custom` (9Router), `ocg/deepseek-v4-flash`, reasoning max, fallback off, TTFB 900s
- Session rule: NEW SESSION (this is the only S11-T03G worker session)
- Binding plan: `S11_T02_T06_PRODUCTION_PLAN.md` REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` (verified sha256sum match) — W8 block incorporated nguyên vẹn; Decisions A/F/G authority.

## 1. Baseline (verified at start)

- `git status --porcelain` = empty; branch `codex/s11/t03g-0903w8`; HEAD == WAVE_BASE `f6942593...`.
- Baseline hashes (existing files to be patched):
  - `app/workflow/job_service.py` = `cd6c2fb9352caf5549b8bd2c0e771b0ee7e60d789eebb0582c4abd2e23000522` (709 lines)
  - `app/api/app.py` = `d7a7cf3bfaea077f83c71a17110840092a99b6e6360f3a36be4c3d7974a2aa0d` (207 lines)
- Read-only contracts consumed: Job/JobStep/JobAttempt infra (`app/persistence/jobs.py`, models), T03F orchestrator `run_full_check_set` (contract đọc từ `app/services/qc_checks/orchestrator.py`), T03A registry/thresholds (read-only), T02B QCItemRepository (read), `video_import._validate_ownership`, attach-job contract (T01C) for server-owned evidence composition.
- `durable_worker.py` KHÔNG chạm (FORBIDDEN) — chỉ đọc WorkerContext/registration contract.

## 2. RED (before implementation)

- Wrote `tests/test_s11_t03g_qc_check_job.py` (17 tests) + `tests/test_s11_t03g_qc_check_api.py` (15 tests) FIRST.
- pytest: collection fails `ModuleNotFoundError: No module named 'app.persistence.qc_check_runs'` — expected RED reason. Evidence: `evidence/red.txt`.

## 3. Implementation (write-set only — exact 8)

NEW:
- `app/workflow/qc_checks_handler.py` — durable handler `qc_checks_handler` cho `JOB_TYPE_RUN_QC_CHECKS` gọi orchestrator T03F `run_full_check_set` (server-owned scopes: `full` = registry order, `audio` = audio_missing + av_sync_drift); completion block ghi policy_id/policy_content_hash/source_generation/source artifact fingerprint/evidence fingerprint/scope fingerprint/detector revisions/measured summary/zero-item completion evidence; fail-closed: evidence fingerprint đổi → `QC_RUN_EVIDENCE_CHANGED`, detector errors → `QC_RUN_DETECTOR_ERRORS` (KHÔNG bao giờ completed run với errors), deadline/cancel → `TRANSIENT` (worker retry); `submit_run_qc_checks` idempotency key `RUN_QC_CHECKS:video_item:<id>:<evidence_fp>:<policy_hash>:<scope>` (active dup → IdempotencyKeyInUse, completed dup → reuse); `compose_check_run_args` chỉ đọc evidence persisted (attach completion) — client payload không có implementation choice.
- `app/persistence/qc_check_runs.py` — read authority compute-on-the-fly (Decision F, KHÔNG table/migration): `latest_check_run_state` (never_run/queued/running/failed/stale/completed + zero-item evidence + summary + evidence/policy match), `check_run_readiness` (ready/blocked/not_run fail-closed kèm check-state detail).
- `app/schemas/qc_check_runs.py` — `QcCheckRunSubmitRequest` `extra="forbid"` (binary Decision-A gate: detector/handler/provider field → 422), submit/state/readiness responses.
- `app/api/routes/qc_check_runs.py` — POST `/api/v2/projects/{project_id}/qc-check-runs` (server-owned, 202; 409 active duplicate; 422 unknown scope/missing evidence/extra-field; 404 ownership), GET state + GET readiness.
- `tests/test_s11_t03g_qc_check_job.py`, `tests/test_s11_t03g_qc_check_api.py`.

EXTEND (bounded additive):
- `app/workflow/job_service.py` — CHỈ registration block RUN_QC_CHECKS (8 dòng, trước S10 full-apply registration).
- `app/api/app.py` — import + ĐÚNG MỘT `include_router(qc_check_runs.router)`.

Forbidden không đụng: models.py, migrations/**, detector modules, thresholds policy, frontend/**, `durable_worker.py`, MAIN, s08 archive, s11-integration canonical.

## 4. GREEN (1 lệnh, fresh root)

- `pytest tests/test_s11_t03g_qc_check_job.py tests/test_s11_t03g_qc_check_api.py` → **32 passed** (basetemp `%TEMP%/s11t03g_green2`, `-p no:cacheprovider`, env strip). Evidence: `evidence/green.txt`.
- Isolation: mỗi test DB SQLite tạm riêng (Alembic head), basetemp ngắn unique, cache provider tắt, `MOTIONFORGE_DATABASE_URL` không đặt.
- Binary checks đạt (AC1–AC6):
  1. Completed run zero QCItems (NO_AUDIO_PRESENT band) → JobAttempt result + step checkpoint có completion evidence + `zero_item_completion.evidence=True`; phân biệt với never-run (`run_state=="never_run"`) — chứng minh qua durable run evidence, KHÔNG qua emptiness QCItem table.
  2. never_run / queued / failed / stale → readiness `not_run` fail-closed kèm `check_state_detail`.
  3. Completed current run zero blocker → readiness `ready`; có blocker → `blocked`.
  4. Idempotency key chứa video id + evidence fingerprint + policy hash + scope; duplicate active → `IdempotencyKeyInUse` fail-closed (job + API 409); completed duplicate → reuse job id (`reused=True`), 1 effect set.
  5. Restart replay (same job row) + worker retry transient (deadline) → zero duplicate QCItem, run_id deterministic (orchestrator fingerprint), 1 completion block.
  6. POST payload chứa `detector`/`handler`/`provider`/`detectors` → 422 (extra forbid); POST /qc-items (PUT/PATCH) → 405; sqlite route chỉ có 1 POST server-owned + GET-only.

## 5. Static gates

- `ruff check --select F` 8 files → All checks passed (sau khi dọn 15 unused imports). Evidence: `evidence/static_gates.txt`.
- `py_compile` 8 files → OK.
- `git diff --check` → clean.
- `alembic heads` → `f9a0b1c2d3e4 (head)` — KHÔNG đổi, không migration. Evidence: `evidence/static_gates.txt`.

## 6. Regression (suites dùng chung module)

- `tests/test_s11_t02b_qc_api_readonly.py` → 14 passed (app.py include mới không phá Decision-A GET-only surface).
- `tests/test_s11_t03f_orchestrator.py` → 14 passed (real media; orchestrator contract không đổi).
- Evidence: `evidence/regression.txt`, `evidence/measured.txt`.

## 7. Commit (local only)

- Stage: đúng 8 file allowlist + `docs/pm/sessions/S11-T03G/**`.
- Commit message + SHA: xem `REPORT.md` §7.

## 8. S11-C1 lane C1-A — full-run authority (correction, Codex P1)

- Finding: `latest_check_run_state()` chọn newest RUN_QC_CHECKS bất kể
  scope/coverage → audio-only run mới nhất thành authority, readiness
  `ready` trong khi 8 visual checks chưa từng chạy (Codex probe).
- Fix (allowlist, bounded patches có preimage):
  - `app/persistence/qc_check_runs.py`: authority = newest FULL-scope run;
    `_completion_proves_full_coverage()` gate 6 điều kiện (manifest scope
    full + manifest scope_fp == content-derived + completion scope/fp khớp
    + detectors == binding band order-insensitive + revisions đủ + errors
    == 0 và checks_skipped == 0); coverage-unproven → failed/not_run;
    audio/partial runs invisible; newest-full non-completed/stale không
    fallback; + `full_coverage_detectors()` derive từ frozen T03A policy
    metrics (10 metric → 10 detectors, `no_audio_source_fact` →
    `audio_missing`) + `full_scope_fingerprint()`.
  - `app/workflow/qc_checks_handler.py`: `SCOPE_BANDS[SCOPE_FULL]` = frozen
    binding 10-detector band (thay registry live order — registry là
    runtime discovery view, tests có thể populate partial); xóa trailing
    whitespace `:12` (invariant 7).
  - `tests/test_s11_t03g_qc_check_job.py`: 12 tests C1-A mới (band derive,
    Codex probe, newer-audio giữ authority, audio-over-stale, newest-full
    queued/running/failed/stale no-fallback, scope/fp mismatch,
    missing-detector, errors/skipped, ready candidate, no-summing) + 6
    tests cũ encode hành vi buggy chuyển sang FULL authority (invariant
    1–3); blocked test thêm invariant 5 (audio mới hơn không xóa blocker).
  - `tests/test_s11_t03g_qc_check_api.py`: 2 tests encode buggy cập nhật
    (audio-only completed ⇒ never_run/not_run) + contrast FULL seeded
    current⇒completed / evidence-moved⇒stale.
- Blast radius T05A (forbidden, read-only check): T05A seed FULL completion
  chỉ 2 audio detectors → coverage-unproven dưới gate mới (7 failed,
  pre-existing, đã chứng minh bằng stash A/B: stash fix → 9 passed; pop →
  7 failed). T05A thuộc owner khác — KHÔNG chạm, báo Manager để T05A owner
  seed đủ 10-detector FULL completion.
- Gate: 44 passed (29 job + 15 api, 51.33s, basetemp `%TEMP%/s11c1a_gate1`,
  `-p no:cacheprovider`, `env -u MOTIONFORGE_DATABASE_URL`); ruff F clean;
  diff-check clean. Evidence: `C:/Users/Admin/MotionForge2D-evidence/s11-c1/lanes/c1a-t03g/`
  (`gate_full_run.txt`, `node_list.txt` 44 nodes, `gate_summary.txt`).
- Commit (local only): xem `REPORT.md` §8.
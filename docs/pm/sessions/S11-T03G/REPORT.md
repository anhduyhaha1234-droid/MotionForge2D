# S11-T03G — Worker REPORT (W8)

## 1. Task identity

| Field | Value |
|---|---|
| Task ID | S11-T03G |
| Wave | W8 (serial sau W7 T03F MANAGER_VERIFIED) |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t03g-0903w8` |
| Branch | `codex/s11/t03g-0903w8` (local, không push/merge/rebase/reset/clean/stash/force) |
| WAVE_BASE | `f6942593304742501ba88f671160b83addbb980b` (porcelain 0 tại start) |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

## 2. Verdict per acceptance criterion (ALL GREEN)

1. **Completed run zero QCItems có durable completion evidence và phân biệt với never-run**
   - `test_completed_zero_item_run_has_durable_completion_evidence`: NO_AUDIO_PRESENT audio band → 2 checks not_applicable, 0 items; JobAttempt result mang block `completed=True`, `run_id` 64-hex, policy id+hash, evidence/scope fingerprints, `detector_revisions`, measured `summary` (checks_requested/run = 2, errors = 0, created = 0, not_applicable = 2), `zero_item_completion = {evidence: True, qc_items_created: 0, issues_found: 0, checks_run: 2, not_applicable: 2}`; step checkpoint cùng block.
   - `test_zero_item_completed_run_distinguishable_from_never_run`: 2 videos cùng 0 QCItem rows; run đã chạy → `run_state=="completed"` + `zero_item_completion is True`; chưa chạy → `run_state=="never_run"` + `zero_item_completion is None`. Quyết định qua durable run evidence (C4-F2), KHÔNG qua bảng QCItem.
2. **Không completed current run / queued/running/failed/stale ⇒ not_run fail-closed kèm check-state detail**
   - `test_readiness_never_run_and_running_not_run_fail_closed`: never_run → not_run; queued → not_run; sau completed → ready.
   - `test_readiness_failed_run_not_run_with_detail`: orchestrator infra failure → job `failed` → not_run + detail "latest RUN_QC_CHECKS job is failed (not completed…)".
   - `test_read_authority_stale_*`: evidence fingerprint đổi (generation bump) → `stale` → not_run + detail; policy hash khác → `stale` + `policy_matches=False` → not_run.
   - API: `GET .../readiness` trả `status=not_run` + `check_state_detail` cho never-run và stale.
3. **Completed current run zero blocker ⇒ clean/ready candidate**
   - Job + API: completed + 0 blocker → `status=ready`, `zero_item_completion=True`; completed + blocker(s) → `status=blocked`, `blockers>=1` (inverse).
4. **Idempotency key gồm video / evidence fingerprint / policy hash / scope; duplicate active conflict fail-closed, completed duplicate reuse**
   - Key format `RUN_QC_CHECKS:video_item:<video_id>:<evidence_fp>:<policy_hash>:<scope>` (test split-tách 6 phần, mỗi phần khớp manifest).
   - Active duplicate → `IdempotencyKeyInUse` (job-level) và `409` (API); completed duplicate → `reused=True` + SAME job_id (job + API), 1 effect set.
   - Generation bump → fingerprint khác → logical run MỚI (không reuse chéo generation).
5. **Restart/retry không duplicate QCItem hoặc run effect**
   - `test_restart_replay_no_duplicate_qcitem_or_run_effect`: force-replay cùng job row → item set byte-identical (natural keys), `run_id` GIỐNG (deterministic orchestrator fingerprint), 1 completion block.
   - `test_worker_retry_transient_no_duplicate_qcitem`: attempt 1 deadline (transient) → retry → completed; 1 error attempt + 1 result attempt; duy nhất 1 item set.
6. **POST là server-owned action (Decision A), KHÔNG phải arbitrary QCItem CRUD**
   - `QcCheckRunSubmitRequest` `extra="forbid"`: payload `detector`/`handler`/`provider`/`detectors` → **422** (4 variants test).
   - POST/PUT/PATCH `qc-items` namespace → **405/404** (không route mutation tồn tại).
   - Route source: đúng 1 `@router.post`, 0 put/patch/delete; schema source không có field detector/handler/provider.
   - Server-owned end-to-end: POST `{video_item_id, scope:"audio"}` → 202 job; manifest `detector_args` chỉ chứa band audio + `checkpoint.status=NO_AUDIO_PRESENT` (composed từ attach evidence persisted, KHÔNG từ payload); worker chạy thật → completed; GET state hiện completion evidence.

## 3. Write-set compliance

| # | File | Op | Verified |
|---|---|---|---|
| 1 | `app/workflow/qc_checks_handler.py` | NEW | module import OK; handler registered |
| 2 | `app/workflow/job_service.py` | EXTEND registration-only | +8 dòng, diff additive; ruff/py_compile OK |
| 3 | `app/persistence/qc_check_runs.py` | NEW | read authority; no table/migration |
| 4 | `app/schemas/qc_check_runs.py` | NEW | extra=forbid request schema |
| 5 | `app/api/routes/qc_check_runs.py` | NEW | 1 POST + 2 GET; 0 QCItem mutation |
| 6 | `app/api/app.py` | EXTEND import + 1 include_router | +2 dòng |
| 7 | `tests/test_s11_t03g_qc_check_job.py` | NEW | 17 tests |
| 8 | `tests/test_s11_t03g_qc_check_api.py` | NEW | 15 tests |

Forbidden verified: `git status --porcelain` chỉ 8 file allowlist + docs; `models.py`, `migrations/**`, detector modules, `thresholds.py`, `frontend/**`, `durable_worker.py` UNCHANGED. `alembic heads` = `f9a0b1c2d3e4` (single, không đổi).

## 4. Isolation flags

- Runner: `--basetemp=C:/Users/Admin/AppData/Local/Temp/s11t03g_*` (short unique), `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`.
- `MOTIONFORGE_DATABASE_URL` không đặt (không dùng env DB); mỗi test DB SQLite tạm riêng qua `alembic upgrade head`.
- Không test nào viết vào canonical tree; managed root/staging trong tmp_path.

## 5. Measured runs

| Run | Command | Result | Time |
|---|---|---|---|
| RED | pytest 2 files (pre-impl) | 1 error (ModuleNotFoundError) | 0.60s |
| Job suite r5 | `test_s11_t03g_qc_check_job.py` | 17 passed | 21.60s |
| API suite r6 | `test_s11_t03g_qc_check_api.py` | 15 passed | 19.10s |
| GREEN (fresh root) | 2 files 1 lệnh | 32 passed | 39.36s |
| GREEN lặp lại | 2 files 1 lệnh | 32 passed | 39.36s |
| Regression T02B | `test_s11_t02b_qc_api_readonly.py` | 14 passed | 15.35s |
| Regression T03F | `test_s11_t03f_orchestrator.py` | 14 passed | 34.57s |

## 6. Evidence index

- `evidence/red.txt` — RED collection error
- `evidence/green.txt` — combined 32-pass run (GREEN fresh root)
- `evidence/static_gates.txt` — ruff F, py_compile, diff --check, alembic heads, diff stat
- `evidence/regression.txt` — T02B + T03F regression
- `evidence/measured.txt` — timing + isolation flags
- `evidence/baseline.txt` — start state + baseline hashes

## 7. Commit

- Commit local trên `codex/s11/t03g-0903w8`: `c3c088f79091d680b95985617f000c622d367f82` (production) + `ccee77b72f57211084209427f38f9394d3d533c7` (docs/evidence)
- Parent: WAVE_BASE `f6942593304742501ba88f671160b83addbb980b`
- Scope staged: 8 file allowlist + `docs/pm/sessions/S11-T03G/**`

## 8. S11-C1 lane C1-A correction

- Finding Codex P1: audio-only newest run thành readiness authority →
  `ready` trong khi 8 visual checks chưa chạy.
- Fix: FULL-run authority + 6-điều-kiện coverage gate (band 10 detector
  derive từ frozen T03A policy, không đoán).
- Gate: 44 passed (29 job + 15 api, basetemp `%TEMP%/s11c1a_gate1`);
  ruff F clean; diff-check clean; scope allowlist-only.
- Evidence external: `C:/Users/Admin/MotionForge2D-evidence/s11-c1/lanes/c1a-t03g/`
  (`gate_full_run.txt`, `node_list.txt`, `gate_summary.txt`).
- Blast radius: T05A seed FULL 2-audio → coverage-unproven (7 failed,
  pre-existing; stash A/B đã chứng minh). Thuộc owner khác — báo Manager.
- Commit local trên `codex/s11/t03g-0903w8`: `2712a5e9d5367a1fa99177f4b6e84a3b02f978a5`
  (C1-A correction: full-run authority + coverage gate + tests + docs).
  Parent chain: canonical `4d7ad8196c3f7a21af744906ef4174690159d889`
  (FF-only merge) ← C1 `c00060afaafca6b35d640d501e8c127d5cee8c7a`.
- Trạng thái: TASK_SUBMITTED (chi tiết LOG.md §8).

## 9. S11-C2 lane C2-A1 correction (completion envelope, unbounded authority)

- Trigger: C1 rereview CHANGES_REQUESTED — 4 gap C1-A (zero-default,
  identity, counts/revisions, limit-then-filter).
- Fix: `_newest_full_job()` query SQL trực tiếp unbounded (page-500
  walk tới FULL-scope đầu tiên); `_completion_from_attempts()` verbatim
  read-back (no default/coerce); `_completion_proves_full_coverage()`
  gate 8 mục (identity ×7 / summary types / errors+skipped+interrupts /
  counts / multiset / revisions / zero-item block).
- Gate: job 83 + api 15 = **98 passed** (basetemp `%TEMP%/s11c2a1_g2`,
  115.61s, `env -u MOTIONFORGE_DATABASE_URL`, `-p no:cacheprovider`);
  micro C2-A1 54 passed 62.97s; ruff F clean; mypy retained-scope
  Success; diff-check clean; forbidden-scan clean.
- Evidence: `docs/pm/sessions/S11-T03G/evidence/c2a1_preimage.txt`
  (+ external S11-C2 evidence khi Manager yêu cầu).
- Postimage: `qc_check_runs.py` `8ec905d07d876097` 29020B 688L;
  job tests `635f27cc05d83559` 73598B 1765L; api tests
  `d5d97d7f9ff9f1e4` 28376B 683L.
- Commit local trên `codex/s11/t03g-0903w8`:
  `a7f75b7` (C2-A1, parent `c9d5453` merged canonical).

## 10. S11-C3-A1 correction (exact authority identity)

- Trigger: C3 đóng 8 mục identity chính xác (manifest schema/policy/
  evidence/generation/source + completion revisions exact + giữ C2 +
  giữ mypy fix `e7e9242`).
- Fix: envelope gate mở rộng (manifest schema exact-int; manifest
  policy/evidence/generation/source vs current + completion vs
  manifest; recompute current evidence bằng manifest generation;
  revision values vs server-owned); stale/ready split giữ
  caller-supplied current (C1-A contract).
- Gate: job 127 + api 16 = **143 passed** (basetemp
  `%TEMP%/s11c3a1_gate`, 163.02s, `env -u
  MOTIONFORGE_DATABASE_URL`, `-p no:cacheprovider`); micro C3-A1 44
  passed; ruff F clean; mypy retained scope Success; diff-check
  clean; forbidden-scan clean.
- Evidence: `docs/pm/sessions/S11-T03G/evidence/c3a1_preimage.txt`.
- Postimage: `qc_check_runs.py` `9dcbe7c5d13b23a0` 39256B 893L; job
  tests `a96935de51c1ae94` 90817B 2177L; api tests `3c6842a545279c71`
  34385B 836L.
- Commit local trên `codex/s11/t03g-0903w8`: `b0a334d`
  (C3-A1, parent `e7e9242`).
## 10. S11-C4 recovery (2026-09-05, 2 P1 + 1 P2 → ALL GREEN)

- Defects: clean process registry rỗng → full RUN_QC_CHECKS chết
  QC_ORCHESTRATOR_MISSING_ARGS (P1-1); `qc_check_runs.py:554-579` catch-all
  → `{}` + fallback `"1.0.0"` chấp nhận forged 10-detector completion khi chỉ
  2/10 registered (P1-2); import-order + EOF-newline trên changed files (P2).
- Fixes (bounded preimage, exact allowlist 3 prod + 2 test):
  (1) `qc_checks_handler.py::ensure_full_band_registered` — production
  bootstrap duy nhất: snapshot PRE-IMPORT, import 7 self-register modules +
  `register()` 3 explicit modules với entry/revision từ constants của chính
  modules, pre-check conflict → QC_RUN_BOOTSTRAP_CONFLICT fail-closed,
  re-seat band order, post-verify set/order/revisions; idempotent.
  (2) `job_service.py::JobService.__init__` gọi bootstrap ngay sau
  `register_qc_checks_handler`. (3) `qc_check_runs.py` xóa mọi guessed
  fallback — resolver raise / map thiếu-thừa-rỗng / value lệch → failed +
  not_run + truthful detail. (4) fixtures 2 test modules dùng production
  bootstrap thay audio-only shim. (5) ruff configured 12 auto-fix trên
  changed files (2 findings còn lại pre-existing ngoài phạm vi C4).
- Proofs: RED pre-fix `red-prefix.log` (registry=[] → MISSING_ARGS);
  GREEN post-fix `green-probe.log` (10/10 band order, idempotent,
  full execute hết MISSING_ARGS, conflict 9.9.9 → BOOTSTRAP_CONFLICT).
  Lane: `C:/Users/Admin/MotionForge2D-evidence/s11-c4/20260905-034450/lanes/c4-recovery/`.
- Gate (đúng thứ tự): micro green-probe xanh → job 127 passed (143.64s) +
  api 16 passed (21.53s) fresh roots → ruff configured (2 pre-existing giữ
  nguyên) → mypy retained scope (handler+runs Success; 2 job_service lỗi
  pre-existing giữ nguyên) → `git diff --check` clean + guard allowlist →
  self-review mọi catch/default (không còn fallback 1.0.0/{}, except còn lại
  đều fail-closed có detail).
- Postimage: `qc_check_runs.py` `8768aa7f94263ee565447aa78b0d8a702f379033`
  39976B 910L; `qc_checks_handler.py` `6b9b0de13245037f27fae0112a7984da1b7ef9c8`
  37311B 922L; `job_service.py` `f61eb08d1da7a1550f4a41c8427a05e3ac97fbff`
  32507B 727L; job tests `735ee4fa3d48ba4d78da176f4cbf85508f580fc0` 90626B
  2174L; api tests `75ae5c391c509e4e612a64d2ee0b3463b0ac4cb4` 34455B 841L.
- Commit local trên `codex/s11/t03g-0903w8`: xem SHA bên dưới (C4, parent
  `28a22072c27a9cd5d1e5eacca82bf9740ce3558c`).

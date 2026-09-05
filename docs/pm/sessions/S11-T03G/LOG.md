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

## 9. S11-C2 lane C2-A1 — completion envelope + unbounded matching-full authority

- Trigger: C1 rereview CHANGES_REQUESTED (3 probe RED mới trên fresh
  Alembic-head DB mà C1-A không cover):
  1. `errors`/`checks_skipped` missing/null/string/bool được default về
     zero → completion rỗng được chấp nhận.
  2. Không so completion identity với manifest/current (schema, job
     type, scope, scope fp, evidence fp, policy id/hash, source
     generation) → tamper được chấp nhận.
  3. Không prove counts/revisions → requested/run thiếu, detector
     duplicate/missing/extra, revision missing/extra/empty vẫn pass.
  4. Query mixed job list có limit (50) rồi filter trong memory → 51+
     audio jobs mới che mất full authority hợp lệ.
- FF: `git merge --ff-only c9d5453` (merged canonical local) OK; porcelain
  rỗng trước khi sửa; preimage ghi tại
  `docs/pm/sessions/S11-T03G/evidence/c2a1_preimage.txt`.
- Fix (allowlist hẹp, `qc_checks_handler.py` READ-ONLY — producer đã ghi
  đủ field đúng type, KHÔNG mở scope):
  - `_newest_full_job()`: query SQL trực tiếp (job_type + owner, không
    limit-then-filter), walk newest-first UNBOUNDED theo page 500 tới
    FULL-scope đầu tiên — 51/101 audio mới hơn không bao giờ che full.
  - `_completion_from_attempts()`: read-back verbatim, KHÔNG normalize/
    default/coerce — missing stays None, wrong-type stays wrong-type.
  - `_completion_proves_full_coverage()` nhận `manifest + current
    evidence_fingerprint + policy_id + policy_content_hash`, gate 8 mục
    fail-closed kèm reason: identity (schema/job-type/manifest
    scope+fp/completion scope+fp/completion evidence-fp==current/
    policy-id+hash==current ×2 /generation+artifacts), required summary
    PRESENT đúng JSON type (bool/int/str KHÔNG phải number), errors==0
    && skipped==0 && !cancelled && !deadline (PRESENT + đúng type),
    counts requested/run == 10 == nhau, detectors multiset == band
    exact, revisions keys == band exact + non-empty, zero-item block
    PRESENT đúng type khi zero-item claim.
  - `latest_check_run_state()`/`check_run_readiness()`: stale branch giữ
    sau envelope (manifest-staleness cho changed-policy/current khi
    completion còn khớp manifest của chính nó); envelope fail → failed/
    not_run kèm reason.
- Tests (fresh real DB, `env -u MOTIONFORGE_DATABASE_URL`,
  `-p no:cacheprovider`): job 83 (29 cũ + 54 C2-A1:
  counts×16 + skipped×4 + identity-tamper×5 + identity-missing×4 +
  counts×5 + interrupt×2 + missing-flag×2 + duplicate/extra/named×3 +
  revisions×4 + pressure-51/101×2 + no-full-101 + nonterminal×3 +
  corrupt×3) + api 15 (V3 manifest bổ sung identity keys + 51-audio
  pressure assert exact full job_id, evidence-moved ⇒ envelope fail).
  6 tests cũ encode hành vi C1-A (stale expectations) cập nhật đúng
  ngữ nghĩa C2-A1 (envelope fire trước manifest-staleness khi completion
  non-current — fail-closed giữ nguyên, chỉ reason/state thành `failed`).
- Gate: job+api **98 passed** (basetemp `%TEMP%/s11c2a1_g2`, 115.61s);
  micro C2-A1 54 passed; `ruff check --select F` clean; mypy
  `--follow-imports=silent` Success; `git diff --check` clean;
  forbidden-scan clean (chỉ 3 file allowlist + evidence preimage mới).
- Postimage: `qc_check_runs.py` `8ec905d07d876097` 29020B 688L;
  `test_s11_t03g_qc_check_job.py` `635f27cc05d83559` 73598B 1765L;
  `test_s11_t03g_qc_check_api.py` `d5d97d7f9ff9f1e4` 28376B 683L.
- Commit (local only): xem `REPORT.md` §9.

## 10. S11-C3-A1 — exact authority identity (bounded guarded correction)

- Trigger: C3 yêu cầu đóng 8 mục identity chính xác trên authority
  (manifest schema/policy/evidence/generation/source + completion
  revisions exact + giữ C2 invariants + giữ mypy fix `e7e9242`).
- Preflight: tip `e7e9242` porcelain rỗng; preimage
  `docs/pm/sessions/S11-T03G/evidence/c3a1_preimage.txt`
  (`qc_check_runs.py` `505fc92bdf56ca09` 29065B 690L; job tests
  `635f27cc05d83559` 73598B 1765L; api tests `d5d97d7f9ff9f1e4`
  28376B 683L). Model turn: custom 9Router
  `cmc/muse-spark-1.3-contributor`, reasoning max, fallback OFF.
- Fix (allowlist hẹp, `qc_checks_handler.py` READ-ONLY — producer đã
  ghi đủ field đúng type; chỉ đọc qua import, không sửa):
  - Import read-only `detector_revisions as _server_…`,
    `evidence_fingerprint as _current_…`, `source_artifact_fingerprint
    as _current_source_…` (không đụng handler).
  - `_completion_proves_full_coverage()` thêm `job_generation` +
    `current_source_precomputed`; gate mở rộng: manifest schema exact
    integer == RUN_QC (bool KHÔNG phải int); manifest policy id/hash
    == current + completion == manifest; manifest evidence == current
    (caller recompute bằng manifest generation) + completion ==
    manifest; manifest generation non-empty str == job row generation +
    completion == cả hai; CURRENT evidence RECOMPUTE bằng manifest
    generation (pair đồng thuận generation sai vẫn fail); manifest
    source (id/SHA) == persisted current source (None+empty cho
    no-source hợp lệ, shape khác là corrupt) + completion == manifest;
    revision VALUES == server-owned (live registry cho member known,
    convention "1.0.0" cho member absent — forged value fail).
  - `latest_check_run_state()`: recompute current evidence bằng manifest
    generation cho envelope gate, nhưng stale/ready split giữ trên
    caller-supplied current evidence (run cũ generation ⇒ STALE đúng
    C1-A contract).
  - `_source_identity_from_manifest()`: shape check đúng representation
    producer (None+empty / real id+non-empty SHA), missing key ⇒ None.
- Tests: job 127 (83 cũ + 44 C3-A1: schema×4+int, policy×2,
  evidence×1, generation-pair×1, gen-type×3, field-matrix×24,
  source×3+manifest×1, revision-value×1, valid no-source/real-source×2,
  101-audio pressure×1) + api 16 (15 cũ + source-tamper HTTP
  readiness not_run). 3 expectations cũ cập nhật đúng ngữ nghĩa C3
  (evidence-moved pair-intact ⇒ stale — fail-closed giữ nguyên).
- Gate: job+api **143 passed** (basetemp `%TEMP%/s11c3a1_gate`,
  163.02s, `env -u MOTIONFORGE_DATABASE_URL`, `-p no:cacheprovider`);
  micro C3-A1 44 passed; `ruff check --select F` clean; mypy retained
  scope (`qc_check_runs.py --follow-imports=skip`) Success; `git diff
  --check` clean; forbidden-scan clean.
- Postimage: `qc_check_runs.py` `9dcbe7c5d13b23a0` 39256B 893L; job
  tests `a96935de51c1ae94` 90817B 2177L; api tests `3c6842a545279c71`
  34385B 836L.
- Commit (local only): xem `REPORT.md` §10.
## 2026-09-05 — S11-C4 recovery (P1-1 C4-A + P1-2 C4-B + P2 C4-C)
- RED pre-fix (current bytes 28a2207): clean-subprocess probe
  `lanes/c4-recovery/red_probe_c4.py` → `red-prefix.log`: registry=[] (0/10),
  full RUN_QC_CHECKS submit+execute → job failed
  `QC_ORCHESTRATOR_MISSING_ARGS` (all 10 unregistered). 12 RED-PROBE lines.
- C4-A (`app/workflow/qc_checks_handler.py::ensure_full_band_registered` +
  hook `app/workflow/job_service.py::JobService.__init__` sau
  `register_qc_checks_handler`): snapshot registry PRE-IMPORT (chống launder
  qua import side-effect), import 7 self-register modules + `register()` 3
  explicit modules (entry/revision từ constants của chính modules, không
  hard-code), pre-check conflict trên snapshot → QC_RUN_BOOTSTRAP_CONFLICT
  fail-closed trước mọi state change, re-seat registry về đúng band order,
  post-verify set/order/revision map. Idempotent (construct lần 2 no-op).
  Green probe `lanes/c4-recovery/green_probe_c4.py` → `green-probe.log`:
  pre=[] → post=10 đúng band order, revisions 10×1.0.0 từ modules,
  idempotent=True, full RUN_QC_CHECKS execute hết MISSING_ARGS
  (QC_RUN_DETECTOR_ERRORS trên minimal args — detectors RAN),
  conflicting version 9.9.9 → QC_RUN_BOOTSTRAP_CONFLICT fail-closed.
- C4-B (`app/persistence/qc_check_runs.py::_completion_proves_full_coverage`):
  XÓA `except Exception → {}` + `.get(name, "1.0.0")`; resolver raise →
  (False, truthful detail); expected map thiếu/thừa/rỗng → (False, detail);
  so sánh exact `revisions.get(name) != expected_revisions[name]`.
  Tests dùng production `ensure_full_band_registered()` thay audio-only shim.
- C4-C: `ruff check` (configured, E/F/I/N/W/UP/B/SIM/TCH) trên 5 changed
  files — 12 auto-fix (import order + EOF newline, kể cả pre-existing do
  C4/C3 để lại trên chính files này); còn lại 2 pre-existing
  (B017:530, SIM210:1532 trong job tests — ngoài phạm vi C4, giữ nguyên).
- Gate: job 127 passed (143.64s) + api 16 passed (21.53s) fresh roots,
  `env MOTIONFORGE_DATABASE_URL= trống`, `-p no:cacheprovider`;
  mypy retained scope: qc_checks_handler + qc_check_runs Success, 2 lỗi
  job_service pre-existing (532/717, giữ nguyên); `git diff --check` clean.
- Postimage: `qc_check_runs.py` `8768aa7f94263ee565447aa78b0d8a702f379033`
  39976B 910L; `qc_checks_handler.py` `6b9b0de13245037f27fae0112a7984da1b7ef9c8`
  37311B 922L; `job_service.py` `f61eb08d1da7a1550f4a41c8427a05e3ac97fbff`
  32507B 727L; job tests `735ee4fa3d48ba4d78da176f4cbf85508f580fc0` 90626B
  2174L; api tests `75ae5c391c509e4e612a64d2ee0b3463b0ac4cb4` 34455B 841L.
- Commit (local only): xem `REPORT.md` §10.

## 2026-09-05 — S11-C4-R1 recovery (writer session, exact lineage 20260905_043139_01a91f)
- P1 finding 1 (bootstrap snapshot/rollback): repro confirmed ghost→success-11 + conflict→partial-7-poisoned. Fixed `ensure_full_band_registered()`: FULL pre-call snapshot of ENTIRE registry; EVERY failure path restores exact snapshot (import conflict, band drift, pre-existing entry/version conflict, foreign entry, explicit-registration failure, post-verify mismatch); foreign non-band entries rejected (name-based, never entry-string match); post-verify demands exact equality (set+order+revisions).
- P1 finding 2 (durable clean-process): new `tests/test_s11_t03g_qc_check_c4r1.py` — fresh interpreter, empty registry, only ordinary app imports, real JobService over fresh Alembic-head DB asserts exact 10-band; rollback matrix (ghost/entry-conflict/version-conflict → RunQcChecksError + exact restore; clean → exact + idempotent).
- P1 finding 3 (authority matrix): 3 new legs in job module — resolver-raises→failed+not_run(unresolvable); two-audio-only registry claiming ten→failed+not_run; server revision drift→stale completion failed, restore→completed. Fixed order-dependence in the 2 registry-mutating tests (finally restores via ensure_full_band_registered, victim fixed to audio_missing).
- Gate: 148 passed (130 job + 16 api + 2 c4r1, 274.06s) + ruff --select F All checks passed + mypy binding scope Success + git diff --check CLEAN.

## 2026-09-05 — S11-C4-R2 recovery (single owner, §4 rows 1-8)
- Row 1 (process-wide lock): new `_BOOTSTRAP_LOCK = threading.RLock()`; public `ensure_full_band_registered()` wraps the WHOLE transaction (snapshot→imports→pre-existing checks→explicit registrations→post-verify→rollback) in `with _BOOTSTRAP_LOCK`. Inner renamed `_ensure_full_band_registered_locked`. Re-entrant so nested/repeat calls never deadlock.
- Row 2 (any-Exception rollback): wrapper snapshots FULL registry (order+name+entry_point+version+description) pre-lock-body; `except RunQcChecksError` → restore + re-raise unchanged; `except Exception` → restore + stable `RunQcChecksError(QC_RUN_BOOTSTRAP_CONFLICT)` with truthful `error_type`/`error_message` details, original as `__cause__`.
- Row 3 (KI/SystemExit policy): documented in wrapper docstring — rollback STILL runs, then original re-raised unwrapped (never converted, never swallowed). Live probe: poisoned `contact_break.register` + `KeyboardInterrupt` → propagated type OK, 10-name snapshot exact incl. description, clean reconverge to ten-band OK.
- Row 4 (R1 preserved): ghost/entry-conflict/version-conflict/exact-ten/clean-process/idempotence legs untouched (only R1 test docstring narrowed per row 8, no behavior change).
- Rows 5-7 (new durable subprocess tests in `tests/test_s11_t03g_qc_check_c4r1.py`): import-leg `RuntimeError` side effect → `RunQcChecksError`/`QC_RUN_BOOTSTRAP_CONFLICT`/`RuntimeError` cause + exact 1-entry snapshot restore + clean reconverge; explicit-leg `RuntimeError` (poisoned `contact_break.register`) → same assertions + exact 10-entry restore; two-live-thread contested bootstrap (barrier + failure event, bounded 60s joins) → failer `RunQcChecksError`/CONFLICT, succeeder 10 revs, final registry exactly ordered ten-band.
- Row 8: R1 test docstring now names the covered rows ("Ghost plus the two conflicting-identity rows restore pre-call state") instead of "every conflict".
- Gate: c4r1 file 5 passed (5.26s) + job 130 + api 16 = 151 passed; ruff `--select F` clean; mypy handler Success; `git diff --check` clean; guard VERIFIED (4 entries, 0 failures).
- Commit (local only): xem `REPORT.md` §12.

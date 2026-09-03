# S11-T03A REPORT — Threshold policy v1 + common bounded runner + detector registry contract (W5)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t03a-0903w5` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03a-0903w5`
WAVE_BASE: `8f27c6b17efce1e8b20c3685ec4ad42be33a90d4` | Commit: LOCAL (git log; không push/merge/rebase/reset/clean/stash/force)
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` — binding block W5.

## 1. Write-set (allowlist — đúng 7 entry, toàn bộ file MỚI; zero file hiện hữu bị sửa)

| File | Nội dung |
|---|---|
| `app/services/qc_checks/__init__.py` | Package init (T03A owner) — re-export policy/runner/registry public API + `__all__` |
| `app/services/qc_checks/thresholds.py` | **THRESHOLD POLICY v1 (FREEZE)** — `POLICY_ID="s11-qc-thresholds-v1"`, schema v1, `build_policy()`/`load_policy()`/`get_threshold()`/`classify()`; content_hash = sha256 canonical JSON; 10 thresholds; error codes `THRESHOLD_UNKNOWN_METRIC`/`THRESHOLD_CALIBRATION_MISSING`/`THRESHOLD_CALIBRATION_INVALID` |
| `app/services/qc_checks/runner.py` | Common bounded runner — `_run_bounded` (T01D pattern: deadline absolute monotonic timestamp, capture cap fail-closed, cancel, kill-tree psutil + fallback, remaining-budget-only reap) + `run_detector()` child-process protocol; codes `QC_RUNNER_*` |
| `app/services/qc_checks/registry.py` | Detector registry contract — `register` idempotent identity, conflict `QC_REGISTRY_CONFLICT`, `unregister` idempotent, `get` unknown → `QC_REGISTRY_UNKNOWN`, invalid args fail-closed; module singleton + convenience fns |
| `tests/fixtures/s11_golden/qc_thresholds.json` | v1 freeze snapshot — deep-equal `load_policy()` (0 drift, test-enforced) |
| `tests/test_s11_t03a_thresholds_policy.py` | 12 tests — identity/hash ×2 loads, 5 thuộc tính/threshold, golden == code 100%, coverage 10 metrics, re-derive từ calibration, sanity reject (âm/ngoài envelope/NaN/inf), classify statuses L1→L4, provenance resolve thật |
| `tests/test_s11_t03a_runner_registry.py` | 15 tests — registry contract + runner ok/deadline-kill/cap/cancel/invalid/child-error + T01D ownership-scoped leak scan (mọi pid spawned phải chết) |

KHÔNG đụng: detector modules (T03B/C/D/E — chưa tồn tại, sở hữu tương lai), orchestrator (T03F), qc_items repo/router (chỉ import), frontend/**, migrations/**, tests/fixtures/s08_golden/** (read-only), `tests/s11_qc_calibration_builders.py` + `tests/fixtures/s11_qc/calibration/*.json` (T06A2 — CHỈ đọc/consume), `tests/s11_qc_media_builders.py` (T06A1 — không import trực tiếp), MAIN, s11-integration.

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — Policy dict versioned (`policy_id` + `content_hash`); JSON fixture khớp code 100% (không drift).**
ĐẠT. `policy_id=s11-qc-thresholds-v1`, `schema_version=1`, `content_hash=de215c6243e1c6bf300e2bfa1c8024fbda6d0358ecf3cad1730781e37419ea24` (64-hex). `test_content_hash_stable_across_two_loads_and_builds` PASSED (build ×2 hash bằng; load ×2 dict bằng). `test_golden_fixture_matches_code_one_hundred_percent` PASSED; gate độc lập `golden==load_policy: True` (evidence/policy_summary.txt). Golden sha256 `54e5e7eb…` (evidence/static_gates.txt).

**AC2 — Mỗi threshold đủ 5 thuộc tính (unit/warning/blocker/provenance/sanity); thiếu 1 → fail.**
ĐẠT. `test_every_threshold_has_all_five_attributes` assert đủ 5 key + `sanity_bounds`={min,max} + min≤max + 0≤warning≤blocker cho cả 10 thresholds; điều kiện `warning_boundary ≤ blocker_boundary` bắt buộc. PASSED.

**AC3 — Provenance từng threshold cite nguồn derive thật từ T06A2 (builder/manifest/measurement record) — không số tùy tiện.**
ĐẠT. MỌI boundary là raw_value đọc từ fixture JSON với citation `tests/fixtures/s11_qc/calibration/<fixture>.json:metric=<m>:level=<L>:raw_value` + provenance record: fixture, metric_record, `measurement_function_revision=1.0.0` (== CALIBRATION_REVISION, asserted ở load), deterministic_seed, source_reference, result_reference, monotonic, sanity_min_rule (physical non-negativity), sanity_max_source. `test_boundaries_derived_from_calibration_raw_values` recompute độc lập bằng đọc JSON → khớp 100%; `test_provenance_citations_resolve_to_real_t06a2_records` resolve `source_reference`/`result_reference` vào function thật của `s11_qc_calibration_builders.py` (vd `generate_trajectory_drift_input`, `measure_av_sync_drift`). Audit độc lập `AUDIT_ALL_OK` 10/10 (evidence/provenance_audit.txt). Vd: `trajectory_drift` warn=31.5 = L2 raw, block=126.0 = L4 raw (trajectory_cut.json, seed 11001); `av_sync_drift` warn=0.1/block=0.5 s (av_sync.json, seed 11009); `no_audio_source_fact` warn=block=0 (constant, av_sync.json L1–L3 đều 0 — fact ffprobe thật).

**AC4 — Runner: quá deadline → kill + stable code; capture cap → fail-closed; cancel → dừng sạch không residue process (T01D leak-scan ownership-scoped).**
ĐẠT. `test_deadline_exceeded_kills_child_stable_code` PASSED — `QC_RUNNER_DEADLINE_EXCEEDED`, pid file của child (sleeping 60s) sau đó psutil `pid_exists=False` (deadline=2.5s, kill + reap trong remaining budget). `test_capture_cap_exceeded_fail_closed_stable_code` PASSED — child flood 480KB stdout, cap=4096 → `QC_RUNNER_OUTPUT_CAP_EXCEEDED`, child chết, KHÔNG nhận partial result (post-loop abort check fail-closed). `test_cancel_event_stops_cleanly_no_residue` PASSED — `QC_RUNNER_CANCELLED`, worker thread trả về <20s, child pid chết. `test_no_residue_processes_after_all_runs` PASSED — quét toàn bộ pid files đã spawn trong module, ZERO survivor. (evidence/runner_tests.txt; run1/run2.txt)

**AC5 — Registry contract: register/unregister/get idempotent; detector chưa đăng ký → stable error.**
ĐẠT. `test_registry_register_get_idempotent` (re-register cùng identity → cùng spec); `test_registry_same_name_different_entry_point_conflict` → `QC_REGISTRY_CONFLICT`; `test_registry_unregister_idempotent` (×2 → True/False, không lỗi); `test_registry_get_unknown_stable_error` → `QC_REGISTRY_UNKNOWN`; `test_run_unknown_detector_stable_error` → `QC_REGISTRY_UNKNOWN` (unregistered detector không thể chạy ngầm); `test_registry_register_invalid_args_fail_closed` → `QC_REGISTRY_INVALID_ARGS`. PASSED.

## 3. Isolation (lane-B §4 / RESOURCE_PLAN §3)

- Basetemp ngắn Windows-native: `C:/Users/Admin/AppData/Local/Temp/s11t03a-*` (mỗi run unique).
- `-p no:cacheprovider` mọi lệnh pytest; `env -u MOTIONFORGE_DATABASE_URL`.
- Conftest của tests chỉ được consume (không sửa); tests KHÔNG đụng DB/SQLite.
- Process hygiene: runner kill-tree psutil children-first + fallback `proc.kill()`; leak scan sau mỗi module (ZERO survivor); child `PYTHONPATH` = project root + sys.path kế thừa (tests dir) → double resolve `test_s11_t03a_runner_registry` trong child; `PYTHONIOENCODING/UTF8` để protocol JSON không vỡ mã hóa.

## 4. Bằng chứng (docs/pm/sessions/S11-T03A/evidence/)

- `baseline.txt` — pre-work: porcelain=0, HEAD=8f27c6b, qc_checks ABSENT, s11_golden ABSENT; post-work scope
- `red.txt` — RED trước implementation (ModuleNotFoundError, 2 errors, 0.20s)
- `run1.txt`, `run2.txt` — 27 passed ×2 (4.83s / 4.87s, EXIT 0)
- `policy_summary.txt` — policy_id, content_hash, 10 thresholds + provenance fixture, hash_stable_two_builds=True, golden==load_policy=True
- `provenance_audit.txt` — AUDIT_ALL_OK 10/10 (fixture/revision/seed/refs/warn_raw/block_raw/sanity_max từng metric)
- `static_gates.txt` — ruff `All checks passed!` (RUFF_EXIT=0), PY_COMPILE_OK, golden sha256
- `t06a2_regression.txt` — 8 passed (read-only consume không phá T06A2)
- `runner_tests.txt` — 15/15 PASSED (registry + bounded failures + leak scan)

## 5. Self-review diff scope

`git status --porcelain` trước commit: 4 untracked (2 dirs + 2 test files) — đúng allowlist + `docs/pm/sessions/S11-T03A/`. KHÔNG file modified; HEAD bất biến ở WAVE_BASE 8f27c6b; không push/merge/rebase/reset/clean/stash/force. Commit local, SHA ghi terminal/LOG.

## 6. Ghi chú ownership (cho Manager/Codex review)

- **FREEZE (Decision C):** policy v1 đã freeze trong phiên này — sau MANAGER_VERIFIED mọi task khác CHỈ ĐỌC `thresholds.py` + `qc_thresholds.json`. Đổi policy = resume đúng session T03A này + rerun dependent gates. Mọi threshold boundary là raw calibration đã freeze (không hard-code).
- W6 tiêu thụ: T03B/C/D/E đăng ký detector qua `register_detector(name, "module:qualname")` và chạy qua `run_detector(..., deadline_sec, capture_cap_bytes, cancel_event)`; T03F orchestrator tổ hợp `classify()` với `DetectorRun.output`. Registry singleton `registry` là điểm đăng ký chung.
- Runner child protocol: detector function nhận `args` dict, trả JSON-serializable; runner chỉ chấp nhận line JSON cuối stdout; mọi fail đều kill-tree + reap trong remaining budget (T01D).
- `no_audio_source_fact` kind=constant: sanity [0,0] — mọi deviation → INVALID (fail-closed); threshold 0/0 belt-and-braces.
- Chưa chạm E06/S09 output; zero S12/S13 dispatch; không resume session task khác (session rule W5: NEW SESSION).

## 7. CORRECTION C2 — exit-gate mypy (resume session T03A, canonical-FF HEAD `15f434928c1b24d88a8649468873c3da8295f3a6`)

- **Finding 1** `thresholds.py:280 no-any-return`: `load_policy()` là lru_cache-wrapper → mypy thấy Any; `return entry` chạm `dict[str, Any]`. Fix: `cast(dict[str, Any], entry)` sau None-check + `from typing import Any, cast` — KHÔNG nới ignore, KHÔNG đổi hành vi (policy schema đảm bảo entry là dict).
- **Finding 2** `runner.py:160 unused-ignore`: `# type: ignore[import-not-found]` dư vì mypy resolve được psutil. Fix: xóa comment ignore, GIỮ try/except ImportError fallback runtime.
- Scope: CHỈ 2 production files (`git status` = 2 modified) + docs C2; zero file khác.
- Verify thật: mypy 3 files `Success`; pytest `27 passed` ×2 (4.92s/4.91s, basetemp s11t03a-c2-*, `-p no:cacheprovider`, `env -u MOTIONFORGE_DATABASE_URL`); ruff `--select F` `All checks passed!`; py_compile OK; `git diff --check` sạch.
- Commit C2 local 1 commit; SHA ghi terminal (không push/merge/rebase).

## 8. CORRECTION S11-C1 lane C1-C — formatting sau Codex review P2 (resume session T03A, canonical-FF HEAD `4d7ad8196c3f7a21af744906ef4174690159d889`)

- **Finding Codex P2:** `git diff --check 7751598214eedb6b72e3783e39a2a408721abe40..HEAD` báo trailing whitespace tại `docs/pm/sessions/S11-T03A/evidence/provenance_audit.txt:2-11`. Dòng `app/workflow/qc_checks_handler.py:12` cùng range thuộc lane T03G — KHÔNG đụng (forbidden).
- **Fix:** strip đúng 1 trailing space cuối dòng 2–11; nội dung provenance KHÔNG đổi (không tái tạo evidence, không đổi code/test).
- **Byte-proof thật:** HEAD blob (LF-norm, do `core.autocrlf=true`) sha256 `7b77af5d33b5d632707ee984733e4ee21032f8924fb4c7812e57313952408e24`, 1032 bytes / 12 lines → worktree LF-norm sha256 `09edfc7a6153b4dacc049d1b1fba38041c9a5ae492999ddcde178300b0bcca47`, 1022 bytes (delta đúng -10 = mười space bị strip), line-count giữ nguyên. So từng dòng: chỉ dòng 2–11 khác nhau, trailing-WS-only.
- **Verify:** `git diff --check HEAD -- docs/pm/sessions/S11-T03A/` EXIT 0 (own-diff sạch); `qc_checks_handler.py` untouched (status empty); scope = 1 file + LOG/REPORT append.
- **Không chạy pytest** (không đổi code/test, theo yêu cầu §5).
- Commit C1-C local 1 commit; SHA ghi terminal (không push/merge/rebase).
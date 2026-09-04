# S11-T06C — REPORT (measured acceptance suite/report/leak gate)

**Status:** TASK_SUBMITTED · **Branch:** codex/s11/t06c-0903w14
**Run-id evidence:** `output/s11-t06-e2e/20260903-155419-31900/` (+ copy `docs/pm/sessions/S11-T06C/evidence/`)
**Outer command (một lệnh — AC1, worker invocation):**

```
env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t02_t06_acceptance.py \
  --ignore=tests/test_integration.py -p no:cacheprovider \
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t06c-outer -v
```

**Outer exit:** 0 — `10 passed in 244.46s (0:04:04)`

**Inner frozen command (records spawn bởi harness; ran trong child, mutex máy-wide):

```
python -m pytest tests/test_s11_t02a_qc_migration.py tests/test_s11_t02a_qc_schema.py \
  tests/test_s11_t02b_qc_api_readonly.py tests/test_s11_t02b_qc_repository_lifecycle.py \
  tests/test_s11_t03a_runner_registry.py tests/test_s11_t03a_thresholds_policy.py \
  tests/test_s11_t03b_trajectory_cut_detectors.py tests/test_s11_t03c_contact_zorder_clipping_detectors.py \
  tests/test_s11_t03d_identity_halo_flicker_detectors.py tests/test_s11_t03e_audio_sync_checks.py \
  tests/test_s11_t03f_orchestrator.py tests/test_s11_t03g_qc_check_api.py tests/test_s11_t03g_qc_check_job.py \
  tests/test_s11_t04a_navigation_api.py tests/test_s11_t04a_navigation_resolver.py \
  tests/test_s11_t04b_correction_rerun.py tests/test_s11_t04b_stale_reopen.py \
  tests/test_s11_t04c_attach_action_api.py tests/test_s11_t05a_next_action_flip.py \
  tests/test_s11_t05a_readiness_api.py --ignore=tests/test_integration.py \
  -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11t06c-suite-31900-0 -v
```

**Inner result:** exit 0 · 314 passed, 0 failed, 0 errors · `suite_stdout.txt` 358 lines.

## Isolation flags (AC1, ghi trong report.json)

```
ignore: [tests/test_integration.py]  cacheprovider: no
basetemp: C:/Users/Admin/AppData/Local/Temp/s11t06c-suite-31900-0  (short, unique, Windows-native)
env_strip: [MOTIONFORGE_DATABASE_URL]  recursion_guard_env: S11_QC_ACCEPTANCE_NESTED=1  verbosity: -v
mutex: C:\Users\Admin\AppData\Local\Temp\s11-t06c-inner-suite.lock (held_while_inner_suite: true)
```

## Per-file pass/fail counts (đo từ verbose output — AC2)

| File | Passed | Failed | Errors |
|---|---|---|---|
| tests/test_s11_t02a_qc_migration.py | 9 | 0 | 0 |
| tests/test_s11_t02a_qc_schema.py | 28 | 0 | 0 |
| tests/test_s11_t02b_qc_api_readonly.py | 14 | 0 | 0 |
| tests/test_s11_t02b_qc_repository_lifecycle.py | 26 | 0 | 0 |
| tests/test_s11_t03a_runner_registry.py | 15 | 0 | 0 |
| tests/test_s11_t03a_thresholds_policy.py | 12 | 0 | 0 |
| tests/test_s11_t03b_trajectory_cut_detectors.py | 23 | 0 | 0 |
| tests/test_s11_t03c_contact_zorder_clipping_detectors.py | 29 | 0 | 0 |
| tests/test_s11_t03d_identity_halo_flicker_detectors.py | 11 | 0 | 0 |
| tests/test_s11_t03e_audio_sync_checks.py | 17 | 0 | 0 |
| tests/test_s11_t03f_orchestrator.py | 14 | 0 | 0 |
| tests/test_s11_t03g_qc_check_api.py | 15 | 0 | 0 |
| tests/test_s11_t03g_qc_check_job.py | 17 | 0 | 0 |
| tests/test_s11_t04a_navigation_api.py | 16 | 0 | 0 |
| tests/test_s11_t04a_navigation_resolver.py | 21 | 0 | 0 |
| tests/test_s11_t04b_correction_rerun.py | 12 | 0 | 0 |
| tests/test_s11_t04b_stale_reopen.py | 9 | 0 | 0 |
| tests/test_s11_t04c_attach_action_api.py | 12 | 0 | 0 |
| tests/test_s11_t05a_next_action_flip.py | 5 | 0 | 0 |
| tests/test_s11_t05a_readiness_api.py | 9 | 0 | 0 |
| **TOTAL** | **314** | **0** | **0** |

## Phase durations (AC2 — reference, không gate cứng)

```
inner_suite_s:              242.719   (T01D baseline ref: 166.7s cho 52 tests — reference only)
leak_window_s:                0.000   (survivors died instantly; window 15s đầy đủ đã poll)
total_s:                    242.719
```

## Leak gate — ffmpeg/ffprobe survivors (AC2)

```
seen (ownership-scoped, trong child tree): [2016, 10888, 23740, 27356, 35848, 36532, 37068, 39268]
survivors (window 15s):                     []   → survivors = 0 ✓
psutil: 7.2.2 available · window_s: 15.0 · leak_window_elapsed_s: 0.0
```

## Golden manifests T06B — dynamic counts (assert động, policy hash khớp)

| Manifest | Items | Count sum | Declared total | Blockers | Hash == frozen policy |
|---|---|---|---|---|---|
| scenario_d_targeted_rerun | 2 | 2 | (n/a) | [] | TRUE |
| e2e_01_vertical_review | 10 | 10 | 10 | [] | TRUE |
| e2e_02_blocker_readiness | 5 | 5 | (n/a) | [audio_missing] | TRUE |
| e2e_03_queue_states | 5 | 5 | 5 | [] | TRUE |
| e2e_04_a11y_mobile | 2 | 2 | (n/a) | [audio_missing] | TRUE |

Frozen policy: `s11-qc-thresholds-v1` hash
`de215c6243e1c6bf300e2bfa1c8024fbda6d0358ecf3cad1730781e37419ea24` —
mọi manifest `policy_ref.policy_content_hash` KHỚP (động qua `policy_ref_matches`).

## Epic exit L235 (AC3)

- **Source voice/BGM/SFX unchanged in sync:** `test_s11_t03e_audio_sync_checks.py`
  green trong suite (17 passed) — slice audio-sync của wave.
- **Scenario D đạt không review full timeline:** golden manifest
  `scenario_d_targeted_rerun` → `expected_rerun_scope.rerun_target =
  affected_segment_only`, `unchanged = ready_scenes remain Ready (no
  re-check/re-review/re-render)`, `after_rerun.status = ready`; restart-resume
  sanity giữa recompute (pattern T01D scenario 5): `test_s11_t04b_correction_rerun.py`
  (12) + `test_s11_t04b_stale_reopen.py` (9) green trong report per-file.

## Assertion ledger

74/74 OK (`assertions.json` all_ok=true) — bao gồm S11-T06C-00..25 (+21a),
leak-gate survivors rỗng trong cửa sổ 15s.

## S11-C1 lane C1-B — executable restart/resume epic-exit proof (Codex P1)

Thay manifest/proxy proof bằng scenario THỰC THI (fresh DB + managed root mới):

```text
seed (project/video/QC blocker) → submit RUN_QC_CHECKS recompute qua stack thật
→ dừng/recreate JobService trên cùng durable DB + managed root
→ resume persisted job (bounded poll 60s/0.5s) → terminal completed
```

**Test mới:** `test_t11_executable_restart_resume_epic_exit` trong cùng file
allowlist (không chạm production — lane này KHÔNG sửa production code).

| Assertion | Nội dung | Kết quả |
|---|---|---|
| S11-C1B-01 | Submit enqueue persisted (queued) | ✓ |
| S11-C1B-02 | Resume tới terminal completed | ✓ |
| S11-C1B-03 | Đúng một successor/effect (1 completion) | ✓ |
| S11-C1B-04 | Run-id deterministic duy nhất (64-hex) | ✓ |
| S11-C1B-05 | Blocker issue tạo đúng một lần | ✓ |
| S11-C1B-06 | Không duplicate natural keys | ✓ |
| S11-C1B-07 | Completed duplicate reuses SAME job | ✓ |
| S11-C1B-08 | Không duplicate resolution sau restart | ✓ |
| S11-C1B-09 | Readiness blocked trung thực (có blocker mở) | ✓ |
| S11-C1B-10 | Readiness ổn định qua fresh re-query | ✓ |

**Kết luận:** KHÔNG phát hiện product bug → KHÔNG cần T04B (`NEEDS_T04B_PRODUCT_FIX`
không kích hoạt). Executable assertion node là REAL submit authority + REAL
recompute handler + REAL `run_full_check_set` — không đọc golden JSON.

**Lane evidence (external, allowlist):**
`C:\Users\Admin\MotionForge2D-evidence\s11-c1\lanes\c1b-t06c\c1b_restart_proof_20260903-185130.json`
(all_ok=true, terminal completed, 1 attempt, steps completed)
+ copy `docs/pm/sessions/S11-T06C/evidence/c1b_restart_proof_20260903-185130.json`.

## Static gates

```
python -m py_compile tests/test_s11_t02_t06_acceptance.py   → OK
ruff check --select F tests/test_s11_t02_t06_acceptance.py  → All checks passed (ruff 0.16.0)
pytest --collect-only tests/test_s11_t02_t06_acceptance.py  → 11 tests collected
```

**Lane command (một lệnh — §6):**

```
env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t02_t06_acceptance.py \
  -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s11c1b_2 -q
→ 11 passed in 249.24s (0:04:09), exit 0
```

## File đã thay đổi

- `tests/test_s11_t02_t06_acceptance.py` (10 → 11 tests, 933 → 1301 lines,
  +368: helpers C1-B + `test_t11`; sha pre b3862d86 — xem SHA cuối khi commit)
- `docs/pm/sessions/S11-T06C/{LOG,REPORT}.md` + `evidence/` (report.json,
  assertions.json, suite_stdout.txt, suite_stderr.txt — copy run-id wave cũ +
  `c1b_restart_proof_20260903-185130.json` mới)
- `output/s11-t06-e2e/20260903-155419-31900/**` (runtime namespace wave cũ, gitignored)
- External lane evidence (ngoài worktree diff, allowlist):
  `MotionForge2D-evidence/s11-c1/lanes/c1b-t06c/c1b_restart_proof_*.json`

**Status: TASK_SUBMITTED** — lane C1-B, chờ Manager/Codex verify. KHÔNG tự ghi APPROVED.
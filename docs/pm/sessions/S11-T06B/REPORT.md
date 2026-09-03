# S11-T06B REPORT — Golden expected-outcome manifests (W9)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t06b-0903w9` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t06b-0903w9`
WAVE_BASE: `b2501598078c702d875f57ac0a17a78e3e40237b` | Commit: LOCAL (xem cuối report, không push)

## 1. Write-set (allowlist C2-F4 — 7 file mới, KHÔNG sửa file hiện hữu)

| File | Nội dung |
|---|---|
| `tests/fixtures/s11_qc/golden_manifests/scenario_d_targeted_rerun.json` | Scenario D: 2 expected QCItem (trajectory_drift, cut_drift — warning/open, affected segment), readiness not_run→ready→after_rerun ready, rerun scope affected_segment_only + ready_scenes unchanged + recheck fail-closed |
| `tests/fixtures/s11_qc/golden_manifests/e2e_01_vertical_review.json` | Full 10-code envelope (seed_all_reason_codes), total 10 items warning/open, readiness not_run→ready, queue path |
| `tests/fixtures/s11_qc/golden_manifests/e2e_02_blocker_readiness.json` | audio_missing blocker/open + 4 overlay warning; readiness not_run→**blocked** (blocker_codes [audio_missing])→after_resolve **ready**; resolution method recheck_fresh_evidence |
| `tests/fixtures/s11_qc/golden_manifests/e2e_03_queue_states.json` | 5 items trải lifecycle open→acknowledged/resolved/dismissed/open (unfixed); actionable vs terminal statuses; reopen_allowed=false (GAP-8) |
| `tests/fixtures/s11_qc/golden_manifests/e2e_04_a11y_mobile.json` | Mobile 390x844, touch-first, badges blocker/warning/info, helper_text_under_buttons=true, min 11px, contrast readable_on_dark_theme; blocked verdict visible |
| `tests/test_s11_t06b_golden_manifests.py` | 14 tests: schema validation, policy hash khớp frozen (stale → đỏ), binary zero-boundary scan, binding enum check, builder-by-name resolve, T03F/T03G consume resolve, Scenario D/E2E-01/E2E-02/E2E-04 truth, helper invariants, stale-fail-fast |
| `tests/s11_qc_golden.py` | Helper: load_manifest/iter_manifests (canonical), load_policy, policy_boundary_numbers (derive từ policy), collect_numbers, policy_ref_matches, schema_violations, validate_all |

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — Mỗi scenario golden có manifest (items reason_code/severity/status-at-create, readiness trước/sau, rerun scope; đủ Scenario D + E2E-01 + E2E-02).** ĐẠT. 5/5 manifest (evidence/scan_output.txt inventory): mọi item có 3 trường enum binding (test_expected_items_use_binding_enums_and_counts); readiness before+after ở mọi manifest, after_rerun (scenario_d) + after_resolve (e2e_02); test_scenario_d_manifest_carries_targeted_rerun_truth + test_e2e_02_manifest_carries_blocker_readiness_truth + test_e2e_01_vertical_review_covers_full_envelope xác nhận.

**AC2 — Manifest không chứa con số threshold (chỉ policy id/hash) — binary scan 0 boundary numbers.** ĐẠT. Scan độc lập: boundary set 16 unique derive từ chính policy (warning/blocker/sanity min/max của 10 metrics); mọi numeric literal trong 5 manifests (chỉ 1/10/5/390/844/11 — counts/viewport/schema_version) KHÔNG nằm trong set; `ZERO_BOUNDARY_SCAN: PASS` (evidence/scan_output.txt + test_no_threshold_boundary_numbers_in_any_manifest).

**AC3 — Hash check: manifest.policy_content_hash == thresholds policy content_hash hiện tại; mismatch → suite đỏ.** ĐẠT. Test đọc policy frozen tại runtime, so sánh 5/5 manifest (hash_match=True); `test_stale_manifest_fails_fast` chứng minh hash cũ bị từ chối (mismatch → fail).

**AC4 — Validate pass một lệnh isolation chuẩn.** ĐẠT. `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s11_t06b_golden_manifests.py -p no:cacheprovider --basetemp <TEMP-short>` → `14 passed` ×4 (r1 1.70s, r2 1.69s, final 1.66s — evidence/run_final.txt; RED đầu: 14 failed 1.99s vì manifests chưa tồn tại).

## 3. Isolation (lane-B §4)

- C1 basetemp ngắn Windows-native: `C:/Users/Admin/AppData/Local/Temp/s11t06b-w9-<tag>-1`, unique mỗi run.
- C3 env strip: mọi lệnh `env -u MOTIONFORGE_DATABASE_URL`; suite thuần JSON schema + import resolution — zero DB.
- `-p no:cacheprovider` mọi lệnh. Không ffmpeg/network. Scan script để ngoài repo (`%TEMP%/s11t06b_scan.py`).

## 4. Static gates (thật)

- `ruff check --select F tests/s11_qc_golden.py tests/test_s11_t06b_golden_manifests.py` → All checks passed (đã sửa 6 lỗi F: 4 import thừa, 1 f-string, 1 biến thừa).
- `python -m py_compile` cả 2 file → OK. JSON 5/5 parse OK.

## 5. Trạng thái (thời điểm submit)

- `git status --porcelain` trước stage: 7 path allowlist (golden_manifests/ 5 file + helper + test) — 0 file ngoài danh sách.
- HEAD trước commit = WAVE_BASE; commit local, KHÔNG push/merge/rebase/reset/clean/stash.
- Evidence: `docs/pm/sessions/S11-T06B/evidence/{baseline.txt, scan_output.txt, run_final.txt}`.

## 6. Ownership notes (cho Manager/Codex review)

- Manifest = truth cho T06C assertions ĐỘNG (consume schema via `s11_qc_golden`); helper expose `policy_boundary_numbers()`/`collect_numbers()`/`policy_ref_matches()` để T06C tái dùng.
- Policy: CHỈ ĐỌC hash — manifest không có bất kỳ threshold value nào (AC2).
- Thiết kế blocker: seed-plan baseline của T06A1 là warning-only → e2e_02/e2e_04 khai `creation: seed_override_blocker` (1 item audio_missing severity blocker) — khác biệt chủ đích, ghi rõ trong manifest.
- Lite note: policy metrics = 9 reason codes + no_audio_source_fact (audio_missing là fact detector — không có threshold boundary); boundary set 16 unique sau dedup.

## 7. Commit SHA

```
(ghi sau khi commit — xem git log -1 trên branch)
```
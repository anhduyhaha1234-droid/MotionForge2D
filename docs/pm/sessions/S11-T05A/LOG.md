# S11-T05A — Worker LOG (W12)

## Session identity

- Task ID: S11-T05A (Compute-on-the-fly readiness API blocker-only versioned)
- Worktree: `C:\Users\Admin\MotionForge2D-worktrees\s11-t05a-0903w12`
- Branch: `codex/s11/t05a-0903w12` (local only, không push/merge/rebase/reset/clean/stash/force)
- WAVE_BASE: `a146034d2282d2857fb9aee6d0ca4af3c178efb5` (porcelain=0 at start)
- Model: `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback disabled
- Status: TASK_SUBMITTED

## Required reading (authority)

1. Binding plan REV7/C6 — `s08-integration/output/s11-post-t01-readiness/r1/synthesis/S11_T02_T06_PRODUCTION_PLAN.md` — SHA-256 verified `342479267086485ef6fd44cb8b3a5f94e6f7b1afcc4439afda2910068fc76f4f`; W12 T05A block lines 413–431 + write-set matrix + Decision F.
2. T03G read authority — `app/persistence/qc_check_runs.py` (latest_check_run_state + check_run_readiness: never-run vs completed-zero-item qua durable run evidence, C4-F2; stale/queued/running/failed fail-closed).
3. lane-C §4.2 response shape — `REVIEW_QUEUE_CONTRACT.md` §4 (status ready/blocked/not_run, blockers[] với location/reason/action, warning_count, computed_at) + API_UI_GAP_MATRIX G10/G11.
4. lane-A GAP_RISKS R4 + QC_DOMAIN_CONTRACT §1.3 rules 1–2 (blocker KHÔNG dismiss; chỉ resolved bằng recheck evidence).
5. FREEZE C2-F3 — summaries.py `FUTURE_CAPABILITY_BLOCKERS["review_work"]` flip point (L159).
6. T03A frozen policy — `app/services/qc_checks/thresholds.py` POLICY_ID `s11-qc-thresholds-v1` + content_hash (Decision F identity).
7. T04A canonical resolver — `app/services/qc_navigation.py` (resolve_navigation/canonical_location) để tái sử dụng WS-07 location/action.
8. E2E_SCENARIOS E2E-02 (A 1 blocker + 3 warnings; fix → ready, warnings chỉ đếm; C chưa check → not_run wins).

## Baseline

- `git status --porcelain` = 0; HEAD = WAVE_BASE.
- SHA-256 trước: `app/persistence/summaries.py` = `60256a4f...e3c69`, `app/api/app.py` = `bd3c63c5...b198c`.
- Alembic single head `f9a0b1c2d3e4`; migrations không chạm.

## Work log

1. **RED** (pre-impl): 11 failed / 3 passed — fails đúng các mảnh chưa có (ModuleNotFoundError readiness modules, route chưa tồn tại, flip chưa xong).
2. **Implement**:
   - `app/persistence/readiness.py` (mới): `compute_project_readiness` on-the-fly (Decision F); per-video verdict qua T03G authority (evidence_fingerprint + policy_bundle hiện tại); aggregate: any not_run → not_run wins; blockers[] = open blocker của videos completed current run, mỗi cái đủ location/reason_vi/action_vi/action (resolve_navigation T04A; unknown kind → explain fail-closed); warning_count = open warning của current-run videos; policy_version=POLICY_ID + content_hash từ policy_bundle().
   - `app/schemas/readiness.py` (mới): DTO strict extra=forbid, shape lane-C §4.2 + Decision F fields + per-video detail.
   - `app/api/routes/readiness.py` (mới): GET `/api/v2/projects/{project_id}/readiness` (GET-only; 404 unknown project).
   - `app/api/app.py`: +1 import + 1 include_router (diff = 2 insertions).
   - `app/persistence/summaries.py`: 1-line flip `review_work: "qc_unavailable" → None` (FREEZE C2-F3); không đụng semantic action, không đụng entry S10/S12 khác.
3. **GREEN**: 14 passed x3 fresh roots (14.54/14.93/14.59s, basetemp `%TEMP%/s11t05a_*`); ruff --select F clean; py_compile OK; alembic head không đổi; migrations-diff = 0.
4. **Regression backend consumers**: 121 passed (T02B x2, T03G x2, T04A x2, T04C) trong 123.73s.
5. **Flip impact** (ngoài allowlist, phải báo Manager): 5 legacy tests trong `tests/test_project_summary.py` + `tests/test_project_summary_mapping.py` assert PRE-flip contract (`review_work` disabled + `qc_unavailable`) → FAIL đúng 5 ca, tất cả cùng root cause; không test nào khác vỡ. Owner update ngoài write-set T05A → Manager cần dispatch follow-on.

## Isolation

- `--basetemp=C:/Users/Admin/AppData/Local/Temp/s11t05a_*` (short unique), `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`.
- `MOTIONFORGE_DATABASE_URL` không đặt; mỗi test DB SQLite tạm riêng qua `alembic upgrade head`.
- Không test nào viết canonical tree.

## Gate status

- [x] RED trước implement (fails thật)
- [x] GREEN 14 passed x3 fresh roots
- [x] ruff --select F clean (7 files)
- [x] py_compile OK
- [x] Alembic head f9a0b1c2d3e4 không đổi; migrations diff = 0
- [x] Regression 121 passed
- [x] Self-review diff scope: chỉ allowlist + docs
- [x] Commit local (SHA ghi trong REPORT)
## C2-B section (INT01 BLOCKED_GATE_RED, real owner 4a4548 — C2-A1 envelope)

1. **INT01 incident**: combined gate 789d303 T05A 7/9 failed (T05A 7 failed, 2 passed → acceptance 2 failed propagation). Route: M1 T03G-C2A1 (0ba0a7b) đổi authority semantics — T05A seed cũ (session T04D misroute tạo ở 3beee0d) thành not_run. Misroute commit 3beee0d kept as-is (không rewrite history); owner thật re-derive độc lập.
2. **Preflight**: status v1 rỗng, tip 3beee0d, FF lên canonical 91db651 (M1 ff 0ba0a7b + M2 no-ff 789d303) OK; preimage c2b_preimage.txt (8 paths SHA/size/lines); MOTIONFORGE_DATABASE_URL unset, SQLite + basetemp ngắn %TEMP%/s11c2b*.
3. **Root cause**: T03G-C2A1 completion envelope 13-point (manifest scope/scope_fp + completion scope/scope_fp + evidence_fp + policy_id/hash + source_generation; summary checks_skipped/cancelled/deadline_exceeded PRESENT exact bool/int; detectors multiset==full band; revisions keyset==band) — T05A seed cũ missing summary checks_skipped/cancelled/deadline_exceeded + manifest policy_id/source_generation → coverage_ok False → not_run.
4. **Fix (allowlist, bounded patch with preimage)**: tests/test_s11_t05a_readiness_api.py — summary +3 fields (checks_skipped 0, cancelled False, deadline_exceeded False) + cả 2 manifest +5 fields (policy_id, source_generation, source_artifact_id, source_sha256, schema_version); read-only: readiness.py không đụng (consumer defect là envelope, không phải logic).
5. **Micro matrix 7 rows**: 1) missing summary field → not_run 2) identity mismatch → not_run 3) valid FULL + 51 audio → exact FULL authority 4) no FULL + 51 audio → not_run 5) multi-video 1 corrupt FULL → project not_run 6) valid FULL zero-item → ready candidate 7) valid FULL + blocker → blocked — evidence: c2b_micro_matrix.txt.
6. **GREEN**: 9/9 (s11c2b_fix2, 13.27s) + 14/14 full T05A (s11c2b_full, 14.12s) ×2 fresh; diff-check 7751598..HEAD exit 0; ruff F clean; allowlist-only commit.
7. **C3-B (retry, real owner 4a4548, baseline caf8dcf — KHONG merge/fetch)**: T03G-C3A1 b0a334d doi envelope (15-point gate: completion source_artifact_id+fingerprint + revisions=server registry). Seed C2-B thieu 2 truong + hardcode revisions 1.0.0 -> coverage_ok False -> 7 rows not_run. Fix: _completion_block +15/-1 (import detector_revisions + source_artifact_fingerprint; source identity = persisted CURRENT source; revisions = server registry). GREEN: 14/14 fresh root s11c3b_fix1 (14.22s); ruff F clean; diff-check 7751598 exit 0.

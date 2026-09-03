# S11-T05A — Worker REPORT (W12)

## 1. Task identity

| Field | Value |
|---|---|
| Task ID | S11-T05A |
| Wave | W12 (song song T04D — BACKEND thuần, không đụng frontend/api.ts) |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t05a-0903w12` |
| Branch | `codex/s11/t05a-0903w12` (local, không push/merge/rebase/reset/clean/stash/force) |
| WAVE_BASE | `a146034d2282d2857fb9aee6d0ca4af3c178efb5` (porcelain 0 tại start) |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

## 2. Verdict per acceptance criterion (ALL GREEN)

1. **Response shape lane-C §4.2 + policy_version/content_hash (Decision F); mỗi blocker có location/reason/action (WS-07)**
   - `GET /api/v2/projects/{project_id}/readiness` → `{status, blockers[], warning_count, videos[], policy_version, content_hash, computed_at}`.
   - blocker entry: `qc_item_id, code, video_item_id, layer_ref_type, layer_ref_id, location{scene_id,frame_index,timecode_ms,object_role_id,segment_row_id,segment_logical_id}, reason_vi, action_vi, action{kind,method,target,endpoint,code,reason}`.
   - `location`/`action` tái sử dụng T04A canonical resolver (`resolve_navigation`); kind không có mapping → `action.kind="explain"` + `code=unknown_kind` fail-closed (không dead link, không crash aggregate).
   - `policy_version == "s11-qc-thresholds-v1"` (POLICY_ID constant), `content_hash == policy_bundle()["policy_content_hash"]` — khớp frozen T03A policy.
   - Schema strict `extra="forbid"` (ReadinessResponse/Blocker/Video).
2. **Fail-closed binary**
   - Per-video verdict: `check_run_readiness` (T03G authority, import-only) với `evidence_fingerprint` + `policy_content_hash` hiện tại của từng video — KHÔNG suy luận từ bảng QCItem trống (C4-F2).
   - any video `not_run` (never_run/queued/running/failed/stale) ⇒ aggregate `not_run` — not_run WINS; mỗi video mang `run_state` + `check_state_detail` + `latest_job_id`.
   - completed zero-item run ⇒ per-video `ready` (zero_item_completion=True), KHÔNG not_run.
   - `blocked` chỉ khi mọi video completed current run và còn open blocker; `ready` chỉ khi zero unresolved blocker.
   - Dismissed blocker không thể tồn tại (repo guard `QCItemBlockedDismissalError` + DB CHECK `ck_qc_item_blocker_not_dismissed`) — không đường nào dismissal giúp ready (R4).
3. **KHÔNG migration/table readiness**
   - `models.py` chưa chạm; `migrations/**` diff = 0; alembic single head `f9a0b1c2d3e4` không đổi; không class `Readiness` trong models (test binary).
4. **Capability flip FREEZE C2-F3 — test riêng `tests/test_s11_t05a_next_action_flip.py`**
   - TRƯỚC (tái lập từ map + 1 entry): `review_work → blocker=qc_unavailable`; SAU T05A: `review_work → enabled=True, blocker=None`; diff đúng 1 entry (`{"review_work": (None, "qc_unavailable")}`).
   - Zero đụng S10/S12: `apply_reskin=capability_unavailable`, `export_video=output_unavailable`, `retry_failed=capability_unavailable`, `analyze/map/create=capability_unavailable` intact + vẫn disabled.
   - not_run readiness vẫn fail-closed sau flip (DB thật: project never-run → `not_run`, cả HTTP lẫn compute).

## 3. Test evidence — E2E-02 backend cases (14 passed x3 fresh roots)

| Case | Result | Evidence |
|---|---|---|
| A 1 blocker + 3 warnings (completed current run) | `status=blocked`, blockers[] chỉ 1 item của A, `warning_count=3`, warnings không vào blockers[] | `test_readiness_blocked_only_by_unresolved_blockers_warnings_just_count` |
| Fix blocker qua recheck evidence `recheck_resolved` | `status=ready`, `blockers=[]`, `warning_count=3` giữ nguyên | `test_readiness_ready_after_blocker_resolved_warning_count_stays` |
| Video C chưa check (E2E-02 step 5) | `status=not_run` wins; C: `run_state=never_run` + detail; blocker hiện tại của A vẫn liệt kê | `test_readiness_not_run_wins_for_unchecked_video` |
| Video D completed run zero QCItem (T03G evidence) | `status=ready`, KHÔNG not_run; D `run_state=completed`, `zero_item_completion=True` | `test_readiness_completed_zero_item_run_is_clean_not_not_run` |
| queued / running / failed / stale runs | aggregate `not_run`; từng video `run_state` đúng + `check_state_detail` + `latest_job_id` | `test_readiness_queued_running_failed_stale_not_run_with_detail` |
| dismissed-blocker (R4) | `recheck_dismissed` blocker → `QCItemBlockedDismissalError`; count row (blocker,dismissed)=0; readiness vẫn blocked | `test_readiness_blocker_dismissal_never_helps_ready` |
| policy_version + content_hash | `== POLICY_ID` / `== policy_bundle()["policy_content_hash"]` (frozen T03A) | trong case 1 + flip file |
| unknown kind blocker | aggregate 200 `blocked`, action `explain`/`unknown_kind`, location structured-only | `test_readiness_blocker_unknown_kind_fail_closed_explain` |
| unknown project | 404 | `test_readiness_unknown_project_404` |
| GET-only + app.py 1 include + no readiness table | router zero mutation decorators; `include_router(readiness.router)` count=1; `models` không có class Readiness | `test_readiness_static_gates_router_app_migrations` |

## 4. Write-set compliance

| # | File | Op | Verified |
|---|---|---|---|
| 1 | `app/persistence/readiness.py` | NEW | compute function; import OK |
| 2 | `app/schemas/readiness.py` | NEW | strict DTO |
| 3 | `app/api/routes/readiness.py` | NEW | 1 GET, 0 mutation |
| 4 | `app/api/app.py` | EXTEND | +2 dòng (import + 1 include_router); diff 2 insertions |
| 5 | `app/persistence/summaries.py` | 1-line flip | `review_work: qc_unavailable → None` (FREEZE C2-F3) |
| 6 | `tests/test_s11_t05a_readiness_api.py` | NEW | 9 tests |
| 7 | `tests/test_s11_t05a_next_action_flip.py` | NEW | 5 tests |

Forbidden verified: `git status --porcelain` chỉ 7 file allowlist + docs; `models.py`, `migrations/**`, `qc_items` repo/router (chỉ import), `frontend/**`, MAIN không chạm; `alembic heads` = `f9a0b1c2d3e4` (single, không đổi); migrations diff = 0.

## 5. ⚠️ Flip impact ngoài allowlist — cần Manager dispatch follow-on

FREEZE C2-F3 đổi hành vi `review_work` từ disabled → enabled (bắt buộc theo plan). Hệ quả: **5 legacy tests** assert PRE-flip contract giờ FAIL (root cause DUY NHẤT là `review_work`):

- `tests/test_project_summary.py::test_next_action_maps_status_deterministically` — needs_review assert `enabled is False`
- `tests/test_project_summary.py::test_next_action_capability_honesty_vocabulary` — `FUTURE_CAPABILITY_BLOCKERS[code] in NEXT_ACTION_BLOCKERS` (None không thuộc vocab)
- `tests/test_project_summary.py::test_next_action_future_capability_disabled_with_blocker` — needs_review assert disabled + qc_unavailable
- `tests/test_project_summary_mapping.py::test_next_action_maps_each_status_deterministically` — assert blocker mapping PRE-flip
- `tests/test_project_summary_mapping.py::test_next_action_future_capabilities_emit_stable_blockers` — `set(values) <= set(NEXT_ACTION_BLOCKERS)` chứa None

Hai file này NẰM NGOÀI write-set T05A (allowlist chỉ 2 test file mới) nên worker KHÔNG được sửa. Plan REV7/C6 quy định flip + test riêng (AC4) nên đây là hệ quả đã biết của FREEZE C2-F3: **Manager cần dispatch một correction/chủ sở hữu các file summaries-test để cập nhật kỳ vọng sang hậu-flip** (review_work enabled + blocker None; entries S10/S12 giữ nguyên). Không test nào khác vỡ (121 regression pass).

## 6. Isolation flags

- Runner: `--basetemp=C:/Users/Admin/AppData/Local/Temp/s11t05a_*` (short unique), `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`.
- `MOTIONFORGE_DATABASE_URL` không đặt; SQLite tạm qua `alembic upgrade head` mỗi test.
- Không test nào viết canonical tree; managed root/staging trong tmp_path.

## 7. Measured runs

| Run | Command | Result | Time |
|---|---|---|---|
| RED (pre-impl) | 2 test files | 11 failed, 3 passed | 14.97s |
| GREEN f1 | 2 files 1 lệnh | 3 failed (fixture) → sửa | 14.77s |
| GREEN f3 | 2 files 1 lệnh | 14 passed | 14.54s |
| GREEN f4 (repeat, fresh root) | 2 files 1 lệnh | 14 passed | 14.93s |
| GREEN f5 (final, fresh root) | 2 files 1 lệnh | 14 passed | 14.59s |
| Regression backend consumers | T02B x2 + T03G x2 + T04A x2 + T04C | 121 passed | 123.73s |
| Flip impact (ngoài scope) | test_project_summary.py + mapping | 44 passed, 5 failed (PRE-FLIP claims) | 46.35s |
| Static gates | ruff --select F 7 files; py_compile 7 files; alembic heads; migrations diff | All clean | — |

## 8. Evidence index

- `evidence/green_final.txt` — 14-pass final run (PASSED per test)
- `evidence/static_gates.txt` — ruff F, py_compile, alembic heads, migrations diff=0, porcelain
- `evidence/runs_summary.txt` — baseline/RED/GREEN/regression/isolation summary

## 9. Commit

- Commit local trên `codex/s11/t05a-0903w12` (SHA ghi sau khi commit)
- Parent: WAVE_BASE `a146034d2282d2857fb9aee6d0ca4af3c178efb5`
- Scope staged: 7 file allowlist + `docs/pm/sessions/S11-T05A/**`
# S11-T03B REPORT — trajectory_drift + cut_drift detectors (W6)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t03b-0903w6` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03b-0903w6`
HEAD: `c1a6777864c1169435d7b7f263ce5fa7a0014c78` (canonical sau defect-schema fix; WAVE_BASE gốc `b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9` đã được Manager fast-forward). Commit: LOCAL (git log; không push/merge/rebase/reset/clean/stash/force).
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` — binding block W6·T03B.

## 1. Write-set (allowlist — đúng 3 file MỚI; zero file hiện hữu bị sửa)

| File | Nội dung |
|---|---|
| `app/services/qc_checks/trajectory_drift.py` | Detector trajectory_drift (visual) — `detect(args)` entry point runner T03A; `create_qc_items(session, args)` tạo QCItem qua T02B repo; self-register `register_detector("trajectory_drift", "<module>:detect")`; measure = mean \|observed−reference\| px (cùng semantics `measure_trajectory_drift` T06A2); classify THỂ CHỈ-ĐỌC policy; evidence schema_version=1 content-derived |
| `app/services/qc_checks/cut_drift.py` | Detector cut_drift (timecode) — `detect`/`create_qc_items` như trên; frame↔ms QUA `CanonicalTimebase` exact `Fraction` (`frame_to_time`/`nearest_frame`); so render cut (ms) vs scene boundary frame (scene_detector GT); classify policy `cut_drift` (frame); boundary_time_ms đồng nhất `scene_ms_range` |
| `tests/test_s11_t03b_trajectory_cut_detectors.py` | 23 tests: registry ×2 detector; runner child ×2; trajectory blocker/warning/mid-band/pass + calibration semantics + evidence byte ×2 + natural-key idempotent + policy test-copy flip ×2 hướng + fail-closed ×2; cut blocker (GT từ T06A1 two_scene_source + cuts_to_scenes/scene_ms_range) + warning/pass + exact-Fraction 29.97 + evidence byte/idempotent + test-copy flip + fail-closed ×2; policy sanity ×2 |

KHÔNG đụng: runner/registry/thresholds + qc_thresholds.json (CHỈ ĐỌC), orchestrator (T03F), models.py/migrations/** (chỉ import/enum), qc_items repo/router (chỉ import), scene_detector.py/timebase.py (consume), frontend/**, T03C/D/E write-set, MAIN, s11-integration.

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — trajectory_drift: lệch quá blocker boundary → severity=blocker; trong warning band → warning; trong biên → không item.**
ĐẠT (checks.txt §2 + run1..3): amp=4.0→value=126.0 px → `status=blocker severity=blocker` (item tạo reason_code=trajectory_drift, category=trajectory_drift, DB count=1); amp=1.0→31.5 px (warning boundary) → `warning`; amp=0.2→6.3 px → `pass` KHÔNG item (records==[], count==0). Mid-band amp=2.0→63.0 px → warning (không bị đẩy lên blocker).

**AC2 — cut_drift: so cut-point render vs scene boundary (scene_detector GT) bằng tolerance frame từ policy; lệch > blocker boundary → blocker QCItem category=timecode.**
ĐẠT (checks.txt §2 + test blocker): render 2400 ms → render_frame=72 vs boundary frame 60 (GT: `cuts_to_scenes([60],120,30)` = [(0,59),(60,119)] từ T06A1 two_scene_source manifest: cut 2.0 s @ 30 fps) → drift_frames=12 = blocker boundary → `severity=blocker`; boundary_time_ms=2000 == `scene_ms_range(tb,60,119)[0]` (đồng nhất ms với scene_detector). Bản ghi category: frozen QC taxonomy (T02A) có 10 category KHÔNG chứa literal "timecode"; mapping chuẩn 1:1 reason→category (tiền lệ T06A1 seed) là `category="cut_drift"` — DB CHECK `ck_qc_item_category` từ chối bất kỳ category nào khác. Evidence mang toàn bộ nội dung timecode: boundary_time_ms, render_cut_ms, render_frame, drift_frames, fps, timebase. Tolerance đọc từ policy: warning=3, blocker=12 frame (evidence chứa cả 2, không hard-code).

**AC3 — Evidence schema_version=1 content-derived only; natural-key idempotent qua recheck.**
ĐẠT (checks.txt §3–4, tests `test_evidence_byte_identical_*` + `test_natural_key_idempotent_*`): evidence `{"schema_version": 1, ...}` chỉ chứa content-derived facts — trajectory: content hashes (sha256 canonical rounded points của reference/observed), window [start,end,count], value, boundaries, policy_id, confidence (min(value/blocker,1.0) round 6), checkpoint_ref; cut: boundary_frame, boundary_time_ms (exact Fraction), render_cut_ms, render_frame, drift_frames, timebase.to_json(), fps "num/den", boundaries, policy_id, confidence. `canonical_evidence_json` 2 run độc lập byte-bằng nhau: True/True. Recreate cùng args → SAME row id (True/True), `SELECT COUNT(*)` = 2 (1 trajectory + 1 cut) — không duplicate (T02B `ON CONFLICT DO NOTHING` natural key 7 cột).

**AC4 — Cả 2 reason codes xuất hiện đủ trong outcome + acceptance (Decision B).**
ĐẠT: reason_code `trajectory_drift` xuất hiện trong item blocker + warning case; reason_code `cut_drift` xuất hiện trong item blocker + warning case; cả 2 đều trong `QC_REASON_CODES` mới (10 codes); registry names = {trajectory_drift, cut_drift} + entry points đúng; cả 2 chạy qua bounded runner child (QC_RUNNER_OK).

**Tests cần thêm (binding):** mỗi detector 1 pass + 1 fail tạo QCItem đúng reason/category/severity theo policy boundary ✓ (blocker fail-case + in-bounds pass-case, cộng warning-band); evidence byte-identical 2 lần chạy ✓; threshold load từ policy — test-copy đổi boundary → kết quả đổi ✓ (2 hướng mỗi detector: blocker 126→80 làm 100.8 px warning→blocker; warning 31.5→200 làm 100.8 px blocker→pass; cut 12→6 làm drift 9 warning→blocker; 3→99 làm drift 9 blocker→pass); cut_drift quy frame↔ms QUA CanonicalTimebase exact Fraction ✓ (29.97: frame 90 = EXACTLY 3003 ms; 3303 ms → frame 99 = round-half-up(98.991…); detector evidence khớp scene_ms_range).

## 3. Isolation (lane-B §4 / RESOURCE_PLAN §3)

- Basetemp ngắn Windows-native unique per run: `C:/Users/Admin/AppData/Local/Temp/s11t03b_{g1,g2,g3,reg}`.
- `-p no:cacheprovider` mọi lệnh pytest; `env -u MOTIONFORGE_DATABASE_URL`.
- DB: fresh per-test temp SQLite (ORM metadata `create_all`) — KHÔNG đụng MAIN/motionforge.db; FK chain seed qua `s11_qc_seed.seed_workspace_project_video` (read-only consume T06A1 infra).
- Detector `detect()` tuyệt đối không mở DB/network (runner child isolation); `create_qc_items` chỉ dùng session caller cấp.
- Media: KHÔNG build ffmpeg (2 detector numeric — trajectory dùng T06A2 calibration generators; cut dùng T06A1 manifest facts + scene_detector helpers + CanonicalTimebase).
- Process hygiene: T03A runner kill-tree — leak test nằm ở suite T03A (regression xanh).

## 4. Bằng chứng (docs/pm/sessions/S11-T03B/evidence/)

- `baseline.txt` — HEAD c1a6777, porcelain pre-work (chỉ 4 untracked), enum 10 codes verified, policy hash `de215c62…` không đổi, old-name scan 0
- `red.txt` — RED trước implementation (ModuleNotFoundError, collection error)
- `run1.txt` / `run2.txt` / `run3.txt` — `23 passed` ×3 (16.11s / 15.41s / 15.41s)
- `checks.txt` — EVIDENCE_PROBE_OK: policy identity, classify tại boundary (pass/warning/blocker mỗi detector), evidence byte-identical True×2, natural-key same-id True×2 + count=2, test-copy flip frozen→copy
- `static_gates.txt` — ruff `All checks passed!` (RUFF_EXIT=0), PY_COMPILE_OK
- `regression.txt` — 98 passed (T03A 27 + T02B + T06A2 8 + T03B 23), warnings chỉ Starlette/httpx deprecation có sẵn

## 5. Self-review diff scope

`git status --porcelain` trước commit: đúng 4 untracked: 2 detector files + 1 test file + `docs/pm/sessions/S11-T03B/`; KHÔNG file modified; HEAD bất biến ở c1a6777; grep tên reason cũ (audio_timecode/z_order/clipping/flicker) trong write-set = 0 hits; scan reason codes dùng = chỉ trajectory_drift/cut_drift. Commit local, SHA ghi terminal/LOG.

## 6. Ghi chú ownership (cho Manager/Codex review)

- **Registry:** cả 2 module self-register khi import (idempotent identity T03A). Entry points: `app.services.qc_checks.trajectory_drift:detect`, `app.services.qc_checks.cut_drift:detect` — chạy được qua `run_detector(name, args=..., deadline_sec, capture_cap_bytes)` (đã chứng minh bằng 2 test runner).
- **Contract chi tiết args (cho T03F orchestrator):** trajectory: workspace/project/video_item/layer_ref, `reference_x`/`observed_x` (list float — GT fixture + path render), `frame_start`; cut: `timebase` = CanonicalTimebase.to_json(), `scene_boundaries` = [{position, start_frame}] (scene_detector GT), `render_cuts_ms` (1 cut/boundary, fail-closed nếu lệch độ dài), `checkpoint_ref` optional (default `s11-qc-t03b`).
- **Fail-closed:** args sai → `QC_TRAJECTORY_INVALID_ARGS`/`QC_CUT_INVALID_ARGS`; measurement ngoài envelope (policy THRESHOLD_INVALID — sanity max = calibrated envelope) → `QC_*_MEASUREMENT_INVALID` (raise, KHÔNG tạo item giả).
- **Confidence:** content-derived `round(min(value/blocker, 1.0), 6)`; `confidence_source="detector"` (hợp lệ trong OCCURRENCE_CONFIDENCE_SOURCES).
- **Item anchor:** video-level (`layer_ref_type="video_item"`, layer_ref_id=video_item_id) — segment/scene anchoring để T03F orchestrator quyết (hoặc mở rộng args layer_ref).
- **Category note AC2:** literal "timecode" không tồn tại trong frozen taxonomy → đã dùng category hợp lệ duy nhất cho reason cut_drift = `cut_drift` (1:1), evidence chứa đủ dữ liệu timecode. Nếu binding muốn item nhóm timecode khác, đó là đổi enum T02A — ngoài write-set T03B.
- Không resume session task khác (W6 rule: NEW SESSION). ETA/scope không đổi — submit đúng hạn sau correction cascade.
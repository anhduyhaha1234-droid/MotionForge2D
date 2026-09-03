# S11-T03E REPORT — audio_missing/output-audio + av_sync_drift checks (W6)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t03e-0903w6` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t03e-0903w6`
WAVE_BASE: `b34d801c60e9bdfdfed2a887b493e7eb8f54a8b9` | RESUME canonical HEAD: `c1a6777864c1169435d7b7f263ce5fa7a0014c78` | Commit: LOCAL (git log ghi SHA; không push/merge/rebase/reset/clean/stash/force)
Plan authority: S11_T02_T06_PRODUCTION_PLAN.md REV7/C6 SHA `342479267086485EF6FD44CB8B3A5F94E6F7B1AFCC4439AFDA2910068FC76F4F` — binding block W6 T03E (Decision D freeze C2-F2). Session rule: NEW SESSION (resume chính xác S11-T03E sau correction cascade; KHÔNG resume task khác).

## 1. Write-set (allowlist — đúng 3 entry, toàn bộ file MỚI; zero file hiện hữu bị sửa)

| File | Nội dung |
|---|---|
| `app/services/qc_checks/audio_missing.py` | Detector W6 tự đăng ký (`register_detector("audio_missing", "app.services.qc_checks.audio_missing:detect")`). Quyết định D C2-F2: source thật sự NO_AUDIO_PRESENT → `applicability=not_applicable`, ZERO QCItem, không fabricate audio, `block_readiness=False`; source CÓ audio nhưng attach job failed / expected output thiếu / validated output mất audio → 1 QCItem severity=blocker status=open, reason_code=category=`audio_missing`; healthy → applicable pass zero QCItem. Evidence 100% content-derived từ checkpoint/published/error envelopes (source_audio_present, source_audio_codec, output_audio_duration, audio_time_base...), idempotent; `evidence_window_key` = sha256 content-derived (64 hex) |
| `app/services/qc_checks/av_sync_drift.py` | Detector W6 tự đăng ký (`av_sync_drift`). Quy đổi thời gian MỘT CHIỀU qua `CanonicalTimebase` exact `Fraction` (scene `duration_seconds` → `exact_seconds`; scene frame grid `fps_num/fps_den/nb_frames` → `duration_for_frames` — CẤM float thô frame/ms/s); drift = |remux decimal6 − scene| Fraction; classify qua frozen policy `s11-qc-thresholds-v1` (av_sync_drift warn=0.1/block=0.5, sanity [0,0.5]); drift ngoài envelope (unit mismatch ms/frame đọc nhầm giây) → fail-closed blocker `unit_mismatch_caught=True`; NO_AUDIO → not_applicable |
| `tests/test_s11_t03e_audio_sync_checks.py` | 17 tests — mỗi nhánh có test riêng (NO_AUDIO not_applicable zero item ×2; attach-failed/output-missing/output-lost-audio blocker/open; healthy pass; frames→exact Fraction pass; unit mismatch ms + frames caught; warning band L3, warning boundary L2, blocker boundary L4, beyond-blocker, below-warning pass; NO_AUDIO av_sync; idempotency ×2; registry + runner end-to-end) |

KHÔNG đụng: original_audio_remux.py/original_audio_handler.py (CHỈ consume checkpoint/published/error envelope — không import module), timebase.py (chỉ import read-only), runner/registry/thresholds (read-only), orchestrator (T03F chưa tồn tại), migrations/**, frontend/**, MAIN, s11-integration, T02B repo (không sửa), fixtures T02B/T06A1 (chỉ đọc).

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — Khớp nguyên văn Decision D freeze C2-F2: nhánh NO_AUDIO_PRESENT → not_applicable + zero QCItem; nhánh source-có-audio-mất-output → blocker/open; av_sync_drift warning/blocker theo policy — mỗi nhánh có test riêng.**
ĐẠT. 17/17 test riêng per branch (evidence/final_green_v1.txt):
- `test_no_audio_present_real_source_not_applicable_zero_items` — REAL T06A1 no_audio_source fixture, probe xác nhận 0 audio stream → `applicability=not_applicable`, `qc_items==[]` (binary count 0), `block_readiness=False`, evidence `source_audio_present=False`, không có key "fabricated".
- `test_source_audio_attach_job_failed_blocker_open` / `test_source_audio_expected_output_missing_blocker_open` / `test_source_audio_validated_output_lost_audio_blocker_open` — REAL `_make_multistream_aac` fixture → 1 QCItem `severity=blocker`, `status=open`, `reason_code=audio_missing`, failure_kind đúng nhánh.
- 6 test av_sync band: warning L3 (0.25) / warning boundary (0.1) / blocker boundary (0.5) / beyond blocker (0.6) / below warning (0.05) / frames-timeline pass — severity mapping khớp frozen policy.

**AC2 — Fixture multistream `_make_multistream_aac` tái dùng: canonical first-audio, không trộn streams (frozen §2 sprint contract).**
ĐẠT. Test importa `_make_multistream_aac` từ `tests/test_s11_original_audio_integration.py` (đúng T06A1 fixture gốc). `_multistream_checkpoint` probe thật và assert `first_audio.index == 1` (canonical first audio tại stream index 1, video ở 0) — streams KHÔNG bị trộn.

**AC3 — Quy đổi thời gian một chiều qua CanonicalTimebase; test chứng minh unit-mismatch bị bắt.**
ĐẠT. `av_sync_drift.py` chỉ quy đổi qua `exact_seconds`/`CanonicalTimebase.duration_for_frames` (exact Fraction); `test_av_sync_frames_timeline_exact_fraction_pass` chứng minh 60 frames @ 30fps == 2.000000 giây exact (drift 0, pass); `test_av_sync_unit_mismatch_ms_caught` (2000.000000 ms đọc nhầm giây → drift ~1998s ngoài envelope → blocker, `unit_mismatch_caught=True`) và `test_av_sync_unit_mismatch_frames_caught` (60 frames đọc nhầm giây → blocker) — KHÔNG bao giờ silent pass.

**AC4 — Evidence content-derived (checkpoint fields source_audio_present/output_audio_duration/audio_time_base), idempotent.**
ĐẠT. `test_both_checks_idempotent_x2` (JSON byte-identical ×2) + script độc lập (evidence/idempotency_hash.txt): audio_missing sha256 trùng `307d8a161799...`, av_sync_drift sha256 trùng `a1adb27c3b8e...`. Evidence chỉ gồm checkpoint/published/error fields + kết quả đo; không timestamp/random.

**Static/regression:** ruff `--select F` 3 file → `All checks passed!` (RUFF_EXIT=0); py_compile OK (evidence/static_gates.txt); regression read-only 43 passed (T03A policy/runner + T06A2 + T06A1) (evidence/regression.txt); grep old token `audio_timecode` = ZERO matches.

## 3. Isolation (lane-B §4 / RESOURCE_PLAN §3)

- Basetemp ngắn Windows-native: `C:/Users/Admin/AppData/Local/Temp/s11t03e-*` — mỗi run unique (g1, g2, fin1, fin2, red2).
- `-p no:cacheprovider` mọi lệnh pytest; `env -u MOTIONFORGE_DATABASE_URL`.
- KHÔNG đụng DB/SQLite (không import repository, không session factory); fixtures media là REAL file ffmpeg trong basetemp.
- Process hygiene: runner test end-to-end chạy child process qua `run_detector` (bounded, capture cap 8192) — protocol JSON round-trip OK.

## 4. Bằng chứng (docs/pm/sessions/S11-T03E/evidence/)

- `final_green_v1.txt`, `final_green_v2.txt` — 17 passed ×2 fresh roots (-v / -q, EXIT 0)
- `static_gates.txt` — ruff All checks passed + RUFF_EXIT=0 + PY_COMPILE_OK
- `regression.txt` — 43 passed (T03A + T06A2 + T06A1, read-only)
- `idempotency_hash.txt` — sha256 trùng ×2 mỗi detector + status/bands
- `red.txt` — RED trước implementation (ImportError audio_missing — module thiếu)

## 5. Self-review diff scope

`git status --porcelain` trước commit: chỉ untracked = 3 file allowlist + `docs/pm/sessions/S11-T03E/**` (LOG, REPORT, evidence/). ZERO file modified; HEAD bất biến ở canonical c1a6777; không push/merge/rebase/reset/clean/stash/force. Commit local, SHA ghi terminal/LOG.

## 6. Ghi chú ownership (cho Manager/Codex review)

- Cả 2 detector tự `register_detector` ở import (idempotent theo registry contract) — T03F chỉ cần import module hoặc gọi `run_detector("audio_missing"/"av_sync_drift", ...)`.
- `reason_code`/`category` dùng EXACT binding code sau correction C1: `audio_missing`, `av_sync_drift` — grep `audio_timecode` = 0.
- QCItem payload trả về sẵn các field khớp `QCItemRepository.create()` (workspace/project/video_item/layer_ref/reason/evidence_window_key/evidence/severity/category/detector/detector_revision/confidence/confidence_source/checkpoint_ref) + `status="open"` — orchestrator persist qua T02B repo; create() mặc định open nên status=open nhất quán.
- `evidence_window_key` = sha256 content-derived (64 hex, ≤64 constraint) — idempotent nên re-run không sinh duplicate natural key.
- av_sync drift đo bằng exact Fraction nhưng `classify()` nhận float — quy đổi frame/ms/s KHÔNG bao giờ qua float thô; float chỉ xuất hiện ở biên classify (frozen policy interface).
- Chưa chạm E06/S09 output; zero S12/S13 dispatch; không resume session task khác.
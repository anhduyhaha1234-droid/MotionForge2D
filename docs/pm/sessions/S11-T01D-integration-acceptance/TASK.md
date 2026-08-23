# S11-T01D — Real Integration and Acceptance (Original Audio)

**Task ID:** S11-T01D
**State:** READY (dispatched khi T01A+B+C MANAGER_VERIFIED)
**Owning session:** 20260822_003041_b18319 (alpha @ custom, Hermes CLI)
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204

## Outcome

Chứng minh end-to-end thật: import video MP4 (AAC) → durable job ATTACH_ORIGINAL_AUDIO → engine remux → artifact `original_audio` publish + owner link → trạng thái hệ thống đúng. Kèm acceptance suite chạy được như một bộ kiểm định duy nhất.

## Verified dependencies (đọc-only)

- app/services/video_import.py (T01A — non-AAC accept-with-warning)
- app/services/original_audio_remux.py (T01B engine, hash 8c3a3bb7 — KHÔNG sửa)
- app/workflow/original_audio_handler.py + job_service.py registration (T01C — KHÔNG sửa)
- docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md, VIDEO_PREFLIGHT_CONTRACT.md
- tests/test_s11_original_audio_contract.py, test_s11_original_audio_remux.py, test_s11_attach_original_audio_job.py (pattern tham khảo)

## Exclusive write ownership

| File | Phạm vi |
|---|---|
| tests/test_s11_original_audio_integration.py | NEW |
| tests/test_s11_original_audio_acceptance.py | NEW |
| docs/pm/sessions/S11-T01D-integration-acceptance/ | packet/evidence |
| output/s11-t01d/<run-id>/ | logs, outputs |

KHÔNG sửa bất kỳ file production nào. Nếu integration lộ defect trong code T01A/B/C → KHÔNG tự sửa; STOP ghi BLOCKED_ENGINE_DEFECT/BLOCKED_WIRING_DEFECT vào LOG.md (Manager resume owning session tương ứng).

## Required scenarios (binary, FFmpeg thật, temp SQLite + temp managed root)

1. Happy path: MP4 H.264+AAC import → attach → completed; artifact kind=audio, purpose=original_audio, owner video_item; file publish đúng managed root; job chỉ complete sau publish.
2. No-audio MP4 → NO_AUDIO_PRESENT outcome đúng contract (không crash, không artifact).
3. Corrupt/truncated source → fail-closed, zero publication, error code đúng.
4. Non-AAC first audio stream (AC-3/MP3) → import warning path rồi attach vẫn chạy (stream-copy/transcode theo engine).
5. Restart giữa chừng (kill worker sau checkpoint) → resume không duplicate artifact.
6. Cancellation giữa remux → zero publication, staging sạch.
7. Idempotency: submit trùng → reuse; conflicting → fail closed.
8. Analysis generation: ObjectRole/occurrence không đổi sau attach.
9. Acceptance suite: một lệnh chạy trọn bộ S11 (contract+remux+attach+integration+acceptance) xanh; ghi đúng lệnh vào evidence.
10. Không process leak (ffmpeg/ffprobe) sau toàn bộ suite.

## Known pre-existing (KHÔNG phải của S11 — không sửa)

- tests/test_durable_job_persistence.py::test_no_worker_or_api_cutover_tables fail do S07 migration thêm bảng project_cast_mapping mà guard-test chưa update — ghi nhận trong evidence, không đụng.
- tests/test_integration.py SKIP (SAM2 segfault) — loại khỏi suite command.

## Worker protocol

- Hard worktree guard trước mọi write (pwd + git rev-parse --show-toplevel khớp worktree này); sai → BLOCKED WRONG_WORKTREE.
- Cấm: git reset/clean/stash/restore/checkout/commit/push/merge; MAIN; production DB/data/motionforge.db; git global config; migrations; file ngoài allowlist (kể cả sửa file S11 A/B/C — chỉ đọc).
- Tests: temp SQLite, temp managed root, basetemp Windows-native riêng, -p no:cacheprovider, env -u MOTIONFORGE_DATABASE_URL.
- Kết thúc: điền Owning session ID, REPORT.md status=SUBMITTED, evidence lệnh+output thật vào LOG.md. KHÔNG tự ghi APPROVED.
- Model: alpha @ custom (9Router), reasoning max, fallback disabled. Route chết → BLOCKED_MODEL_ROUTE.
